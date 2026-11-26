#!/usr/bin/env python3
"""text_coverage.py -- Deterministische Quellbeleg- und Textabdeckungs-Pruefung.

Prueft ohne KI und ohne Netz (``--no-llm``-tauglich), welche Absaetze und
Kapitel eines Pflichtenhefts / Handbuchs tatsaechlich im Architekturmodell
durch Elemente oder Beziehungen (``source_ref``) abgedeckt sind -- und welche
Abschnitte noch unmodelliert geblieben sind.

Unterstuetzte Quellen fuer die Gegenpruefung:
1. Explizite Textdatei(en) (``.txt``, ``.md``, ``.docx``, ``.pdf``, ``.csv``)
   oder Rohtext-Strings.
2. Begleitdatei ``quellen.json`` (``D1-S1`` -> Absatztext) neben einer ``.qea``.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def _read_text_file(path: Path) -> str:
    """Liest Quelltext fuer die Abdeckungspruefung ohne KI-/Netz-Abhaengigkeit."""
    sfx = path.suffix.lower()
    if sfx == ".docx":
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paras: list[str] = []
        with zipfile.ZipFile(path, "r") as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
        for p in root.iter(f"{ns}p"):
            txt = "".join(t.text or "" for t in p.iter(f"{ns}t")).strip()
            if txt:
                paras.append(txt)
        return "\n\n".join(paras)
    if sfx == ".pdf":
        import pdf_text  # noqa: PLC0415

        return pdf_text.extract_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm_ref(value: str) -> str:
    txt = _s(value)
    if txt.startswith("[") and txt.endswith("]"):
        txt = txt[1:-1].strip()
    return txt.upper()


def _extract_refs_from_value(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,;\s]+", raw.strip())
    out: list[str] = []
    for p in parts:
        n = _norm_ref(p)
        if re.match(r"^D\d+-S\d+$", n):
            out.append(n)
    if not out and _norm_ref(raw):
        out.append(_norm_ref(raw))
    return out


def collect_model_refs(ir: Mapping[str, Any]) -> dict[str, list[str]]:
    """Sammelt ``source_ref -> [Objektbezeichnungen]`` aus Elementen und Beziehungen."""
    refs: dict[str, list[str]] = {}

    for el in ir.get("elements") or ():
        if not isinstance(el, Mapping):
            continue
        label = _s(el.get("name")) or _s(el.get("guid") or el.get("ea_guid")) or "Element"
        pkg = _s(el.get("package"))
        full_label = f"{pkg}::{label}" if pkg else label
        raw_vals: list[str] = []
        if _s(el.get("source_ref")):
            raw_vals.append(_s(el.get("source_ref")))
        tags = el.get("tags")
        if isinstance(tags, Mapping):
            for k, v in tags.items():
                if _s(k).casefold() in ("source_ref", "herkunft", "quellbeleg") and _s(v):
                    raw_vals.append(_s(v))
        for rv in raw_vals:
            for r in _extract_refs_from_value(rv):
                lst = refs.setdefault(r, [])
                if full_label not in lst:
                    lst.append(full_label)

    for conn in ir.get("connectors") or ():
        if not isinstance(conn, Mapping):
            continue
        c_label = f"{_s(conn.get('source'))} -> {_s(conn.get('target'))}"
        raw_vals = []
        if _s(conn.get("source_ref")):
            raw_vals.append(_s(conn.get("source_ref")))
        tags = conn.get("tags")
        if isinstance(tags, Mapping):
            for k, v in tags.items():
                if _s(k).casefold() in ("source_ref", "herkunft", "quellbeleg") and _s(v):
                    raw_vals.append(_s(v))
        for rv in raw_vals:
            for r in _extract_refs_from_value(rv):
                lst = refs.setdefault(r, [])
                if c_label not in lst:
                    lst.append(c_label)

    return refs


def split_text_segments(texts: Sequence[str]) -> list[dict[str, str]]:
    """Zerlegt Dokumenttexte identisch zu ``extract.split_documents`` in ``D<n>-S<m>``."""
    out: list[dict[str, str]] = []
    for doc_idx, raw in enumerate(texts, start=1):
        norm = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
        paras = [b.strip() for b in _PARAGRAPH_SPLIT.split(norm) if b.strip()]
        chapter = "(Einleitung)"
        for seg_idx, p in enumerate(paras, start=1):
            first_line = p.splitlines()[0].strip()
            m = _HEADING_RE.match(first_line)
            is_heading = bool(m and len(p.splitlines()) == 1)
            if m:
                chapter = m.group(2).strip()
            out.append(
                {
                    "ref": f"D{doc_idx}-S{seg_idx}",
                    "document": f"D{doc_idx}",
                    "chapter": chapter,
                    "is_heading": "1" if is_heading else "",
                    "text": p,
                }
            )
    return out


def discover_quellen_sidecar(model_path: str | os.PathLike[str] | None) -> Path | None:
    """Sucht ``<modell>.quellen.json`` oder ``quellen.json`` neben der Modelldatei."""
    if model_path is None:
        return None
    mp = Path(model_path)
    candidates = [
        mp.with_name(mp.stem + ".quellen.json"),
        mp.with_suffix(".quellen.json"),
        mp.parent / "quellen.json",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def load_quellen_map(path: str | os.PathLike[str] | None) -> dict[str, str]:
    if path is None:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, Mapping):
        # quellen.json ist entweder flach {"D1-S1": "..."} oder {"quellen": {...}}
        inner = data.get("quellen") if isinstance(data.get("quellen"), Mapping) else data
        return {
            _norm_ref(str(k)): str(v)
            for k, v in inner.items()
            if isinstance(v, str) and _norm_ref(str(k))
        }
    return {}


@dataclass(frozen=True)
class CoverageReport:
    source: str
    total_segments: int
    content_segments: int
    covered_segments: int
    uncovered_segments: int
    coverage_pct: float
    chapters: tuple[dict[str, Any], ...]
    uncovered: tuple[dict[str, str], ...]
    quellen: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "total_segments": self.total_segments,
            "content_segments": self.content_segments,
            "covered_segments": self.covered_segments,
            "uncovered_segments": self.uncovered_segments,
            "coverage_pct": self.coverage_pct,
            "chapters": list(self.chapters),
            "uncovered": list(self.uncovered),
        }


def evaluate_coverage(
    ir: Mapping[str, Any],
    *,
    text_source: str | os.PathLike[str] | Sequence[str | os.PathLike[str]] | None = None,
    quellen_path: str | os.PathLike[str] | None = None,
    model_path: str | os.PathLike[str] | None = None,
) -> CoverageReport | None:
    """Berechnet die Textabdeckung fuer ein Modell; ``None``, wenn keine Quelle vorliegt."""
    model_refs = collect_model_refs(ir)
    segments: list[dict[str, str]] = []
    source_label = ""
    quellen_map: dict[str, str] = {}

    if text_source is not None:
        items: list[str | os.PathLike[str]]
        if isinstance(text_source, (str, os.PathLike)):
            items = [text_source]
        else:
            items = list(text_source)
        raw_docs: list[str] = []
        labels: list[str] = []
        for it in items:
            if isinstance(it, os.PathLike) or (isinstance(it, str) and len(it) < 260 and Path(it).is_file()):
                p = Path(it)
                raw_docs.append(_read_text_file(p))
                labels.append(p.name)
            else:
                raw_docs.append(str(it))
                labels.append("inline")
        segments = split_text_segments(raw_docs)
        source_label = ", ".join(labels)
        quellen_map = {s["ref"]: s["text"] for s in segments}
    else:
        q_path = Path(quellen_path) if quellen_path else discover_quellen_sidecar(model_path)
        if q_path and q_path.is_file():
            quellen_map = load_quellen_map(q_path)
            source_label = q_path.name
        elif isinstance(ir.get("meta"), Mapping) and isinstance(ir["meta"].get("quellen"), Mapping):
            quellen_map = {
                _norm_ref(str(k)): str(v)
                for k, v in ir["meta"]["quellen"].items()
                if isinstance(v, str)
            }
            source_label = "meta.quellen"
        if quellen_map:
            def _ref_sort_key(ref: str) -> tuple[int, int, str]:
                m = re.match(r"^D(\d+)-S(\d+)$", ref)
                return (int(m.group(1)), int(m.group(2)), ref) if m else (999999, 999999, ref)

            chapter = "(Quellbelege)"
            for ref in sorted(quellen_map, key=_ref_sort_key):
                txt = quellen_map[ref].strip()
                first = txt.splitlines()[0].strip() if txt else ""
                hm = _HEADING_RE.match(first)
                is_h = bool(hm and len(txt.splitlines()) == 1)
                if hm:
                    chapter = hm.group(2).strip()
                segments.append(
                    {
                        "ref": ref,
                        "document": ref.split("-", 1)[0] if "-" in ref else "D1",
                        "chapter": chapter,
                        "is_heading": "1" if is_h else "",
                        "text": txt,
                    }
                )

    if not segments:
        return None

    # Reine einzeilige Kapitelueberschriften zaehlen nicht als unmodellierte Fachluecke
    content_segs = [s for s in segments if not s["is_heading"]]
    basis = content_segs if content_segs else segments

    covered = [s for s in basis if s["ref"] in model_refs]
    uncovered_list = [
        {
            "ref": s["ref"],
            "chapter": s["chapter"],
            "preview": (s["text"][:180] + "...") if len(s["text"]) > 180 else s["text"],
        }
        for s in basis
        if s["ref"] not in model_refs
    ]

    chap_stats: dict[str, dict[str, int]] = {}
    chap_order: list[str] = []
    for s in basis:
        ch = s["chapter"]
        if ch not in chap_stats:
            chap_stats[ch] = {"total": 0, "covered": 0}
            chap_order.append(ch)
        chap_stats[ch]["total"] += 1
        if s["ref"] in model_refs:
            chap_stats[ch]["covered"] += 1

    chapters = tuple(
        {
            "chapter": ch,
            "total": chap_stats[ch]["total"],
            "covered": chap_stats[ch]["covered"],
            "uncovered": chap_stats[ch]["total"] - chap_stats[ch]["covered"],
            "coverage_pct": round(100.0 * chap_stats[ch]["covered"] / max(1, chap_stats[ch]["total"]), 1),
        }
        for ch in chap_order
    )

    pct = round(100.0 * len(covered) / max(1, len(basis)), 1)
    return CoverageReport(
        source=source_label,
        total_segments=len(segments),
        content_segments=len(basis),
        covered_segments=len(covered),
        uncovered_segments=len(uncovered_list),
        coverage_pct=pct,
        chapters=chapters,
        uncovered=tuple(uncovered_list),
        quellen=quellen_map,
    )
