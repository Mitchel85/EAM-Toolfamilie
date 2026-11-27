#!/usr/bin/env python3
"""eam_ai.py -- Gesamtlauf: Technologie + Prosa -> .qea.

Ein Aufruf, sechs Schritte, keine versteckten Nebenwege::

    eam-ai build --mdg technologie.xml --text architektur.pdf --out modell.qea
    eam-ai build --mdg technologie.xml --bild architektur.png --out modell.qea
    eam-ai build --mdg technologie.xml --out geruest.qea      # ohne Text, ohne KI

    1. Technologie laden      (MDG-XML -> Regelwerk im Speicher)
    2. Technologie pruefen    (Schema, nutzbare Stereotype)
    3. Quelle lesen           (.txt/.md/.docx/.pdf -> Absaetze; --bild -> Prosa)
    4. Extrahieren            (Sprachmodell -> Kandidaten-IR)
       oder Geruest bauen     (ohne --text/--bild und ohne Backend: nur Regelwerk)
    5. Validieren             (IR gegen Regelwerk -> findings.json)
    6. Emittieren             (IR -> .qea + quellen.json)

Der Geruest-Weg ruft kein Modell auf und ist vollstaendig offline. Bilder
werden base64 als multimodale Nachricht an ein OpenAI-kompatibles Backend
geschickt (``image_input``); die Beschreibung wird der Prosa vorangestellt.

Vertrag
-------
* Exit 0 nur bei **null Fehlern**. Warnungen blockieren nicht, mit ``--strict``
  schon. Jeder andere Ausgang ist Exit 1; argparse nutzt 2 fuer Aufruffehler.
* ``findings.json`` wird bei jedem Lauf geschrieben (auch leer). Bei einem
  technischen Abbruch vor der Pruefung enthaelt sie einen Lauf-Fehler.
* ``--dry-run`` schreibt keine ``.qea`` und keine ``quellen.json``. Geprueft
  wird trotzdem vollstaendig.
* Fortschritt geht nach stderr, das Ergebnis nach stdout.
* Kein Netzwerk ausser im ausdruecklich gewaehlten Backend. Der Kern ist
  deterministisch: gleiche Eingaben und gleiche Antwort -> gleiche Bytes.

Der Regelpfad ohne KI bleibt ``eam_suite.py`` (``--no-llm``). Dieses Modul
importiert ``eam_suite`` nicht und umgekehrt.

Weitere Unterbefehle
--------------------
    eam-ai merge --qea A.qea B.qea [...] --out ZIEL.qea [--bericht bericht.json]
    eam-ai edit  --qea MODELL.qea --ops ops.json --out NEU.qea [--mdg MDG.xml]

``merge`` fuehrt mehrere Modelle GUID-erhaltend zusammen (``model_merge``),
``edit`` wendet gezielte Aenderungen auf eine Kopie an (``model_edit``) und
prueft sie mit ``--mdg`` gegen das Regelwerk. Beide Unterbefehle schreiben nur
in die Zieldatei, nie in eine Eingabedatei.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import warnings
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Der MDG-Leser ist der einzige seiner Art und liegt in packages/rules.
_REGELN = Path(__file__).resolve().parent.parent / "rules"
if _REGELN.is_dir() and str(_REGELN) not in sys.path:
    sys.path.insert(0, str(_REGELN))

import emit as emit_module
import extract as extract_module
import image_input
import mdg_parser
import pdf_text
import relation_fill as relation_module
import repair_loop as repair_module
import rules_schema
import skeleton as skeleton_module
import skeleton_arch as skeleton_arch_module
import architektur as architektur_module
import struktur as struktur_module
import wizard as wizard_module

#: Geruestart, wenn keine gewaehlt wurde: MASC-Struktur.
LEITFADEN_KIND = "leitfaden"
MASC_KIND = "masc"
ARCH_SKELETON_KIND = LEITFADEN_KIND
import validator
from emit import EmitError, EmitReport
from extract import ExtractionError, ExtractionResult
from mdg_parser import MdgParseError
from qea_reader import QeaReaderError
from qea_writer import QeaWriterError
from validator import ValidatorError

DEFAULT_PACKAGE = extract_module.DEFAULT_PACKAGE
DEFAULT_SCHEMA = Path(__file__).resolve().parent / "rules.schema.json"
FINDINGS_NAME = "findings.json"

# Eine Quelle fuer die Version: hier. pyproject.toml und CHANGELOG.md muessen
# dazu passen; tests/test_packaging.py prueft die drei Stellen gegeneinander.
__version__ = "1.0.0"

# DOCX ist eine ZIP-Datei mit genau diesem Pfad fuer den sichtbaren Text.
_DOCX_MAIN = "word/document.xml"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

Log = Callable[[str], None]


class BuildError(RuntimeError):
    """Gesamtlauf abgebrochen. Immer laut, nie ein stiller Teilerfolg."""


@dataclass(frozen=True)
class BuildReport:
    """Ergebnis eines Gesamtlaufs (fuer CLI, Tests und Einbettung)."""

    technology: Mapping[str, str]
    backend: str
    segments: int
    elements: int
    connectors: int
    dropped: tuple[Mapping[str, str], ...]
    attempts: int
    findings: tuple[Mapping[str, str], ...]
    findings_path: Path
    out: Path
    qea: Path | None
    quellen: Path | None
    digest: str
    provenance_tags: int
    exported: bool
    dry_run: bool
    strict: bool
    batches: int = 0

    @property
    def summary(self) -> dict[str, int]:
        return validator.summarize(self.findings)

    @property
    def blocked(self) -> bool:
        counts = self.summary
        return bool(counts["error"]) or (self.strict and bool(counts["warning"]))

    def result_line(self) -> str:
        """Eine kanonische Ergebniszeile fuer stdout."""
        counts = self.summary
        common = (
            f"{self.elements} Elemente, {self.connectors} Beziehungen, "
            f"{counts['error']} Fehler, {counts['warning']} Warnungen"
        )
        if self.dry_run:
            return f"Trockenlauf: {self.out} nicht geschrieben, {common}"
        if not self.exported:
            return f"{self.out}: nicht geschrieben, {common}"
        parts = [
            f"{self.out}: geschrieben",
            common,
            f"{self.provenance_tags} Herkunfts-Tags",
            f"sha256 {self.digest}",
        ]
        if self.quellen is not None:
            parts.append(f"{self.quellen}")
        return ", ".join(parts)


# --------------------------------------------------------------------------
# Technologie
# --------------------------------------------------------------------------


def load_technology(mdg: str | Path, *, schema_path: str | Path | None = None) -> dict[str, Any]:
    """MDG-XML lesen und gegen ``rules.schema.json`` pruefen.

    Liefert das geparste Regelwerk. Ein kaputtes XML, eine fremde Wurzel oder
    ein Schemaverstoss brechen laut ab -- es gibt keinen Teil-Erfolg.
    """
    source = Path(mdg)
    try:
        rules = mdg_parser.parse_mdg(source)
    except MdgParseError as exc:
        raise BuildError(f"Technologie: {exc}") from exc

    schema = Path(schema_path) if schema_path is not None else DEFAULT_SCHEMA
    try:
        rules_schema.validate(rules, rules_schema.load_schema(schema))
    except rules_schema.SchemaError as exc:
        raise BuildError(
            f"Technologie {source}: Regelwerk verletzt das Schema {schema}: {exc}"
        ) from exc

    stats = rules.get("stats")
    if not isinstance(stats, Mapping):
        raise BuildError(f"Technologie {source}: Regelwerk ohne stats -- kein belastbarer Lauf")
    if int(stats.get("elementStereotypes", 0)) <= 0:
        raise BuildError(
            f"Technologie {source}: keine Element-Stereotype im Regelwerk "
            f"-- ohne Technologie keine Extraktion"
        )
    return rules


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------


def _read_plain(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BuildError(f"Text {path}: keine UTF-8-Datei ({exc})") from exc
    except OSError as exc:
        raise BuildError(f"Text {path}: nicht lesbar ({exc})") from exc


def _docx_run_text(element: ET.Element) -> str:
    """Sichtbaren Text eines WordprocessingML-Knotens in Dokumentreihenfolge."""
    tag = element.tag
    if tag == _W + "t":
        return element.text or ""
    if tag == _W + "tab":
        return "\t"
    if tag in (_W + "br", _W + "cr"):
        return "\n"
    if tag == _W + "noBreakHyphen":
        return "-"
    parts: list[str] = []
    for child in element:
        parts.append(_docx_run_text(child))
    return "".join(parts)


def _docx_cell_text(tc: ET.Element) -> str:
    parts: list[str] = []
    for child in tc:
        if child.tag == _W + "p":
            t = _docx_run_text(child).strip()
            if t:
                parts.append(t)
        elif child.tag == _W + "tbl":
            sub = _docx_table_to_markdown(child)
            if sub:
                parts.append(sub)
    text = " ".join(parts).strip()
    return text.replace("|", r"\|").replace("\n", " ").replace("\r", " ")


def _docx_table_to_markdown(tbl: ET.Element) -> str:
    rows: list[list[str]] = []
    for child in tbl:
        if child.tag == _W + "tr":
            row_cells: list[str] = []
            for tc in child:
                if tc.tag == _W + "tc":
                    row_cells.append(_docx_cell_text(tc))
            if row_cells and any(c.strip() for c in row_cells):
                rows.append(row_cells)
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    if col_count == 0:
        return ""
    norm_rows = [r + [""] * (col_count - len(r)) for r in rows]
    md_lines = [
        "| " + " | ".join(norm_rows[0]) + " |",
        "| " + " | ".join(["---"] * col_count) + " |",
    ]
    for r in norm_rows[1:]:
        md_lines.append("| " + " | ".join(r) + " |")
    return "\n".join(md_lines)


def _docx_paragraphs(container: ET.Element) -> list[str]:
    """Absaetze und Tabellen aus dem Dokumentbaum."""
    paragraphs: list[str] = []
    for child in container:
        tag = child.tag
        if tag == _W + "p":
            text = _docx_run_text(child)
            if text.strip():
                paragraphs.append(text.strip())
        elif tag == _W + "tbl":
            md_tbl = _docx_table_to_markdown(child)
            if md_tbl.strip():
                paragraphs.append(md_tbl.strip())
        elif tag in (
            _W + "sdt",
            _W + "sdtContent",
            _W + "body",
            _W + "hdr",
            _W + "ftr",
            _W + "footnotes",
            _W + "footnote",
            _W + "endnotes",
            _W + "endnote",
        ):
            paragraphs.extend(_docx_paragraphs(child))
    return paragraphs


def _read_docx(path: Path, image_sink: list[tuple[bytes, str, str]] | None = None) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                payload = archive.read(_DOCX_MAIN)
            except KeyError as exc:
                raise BuildError(
                    f"Text {path}: {_DOCX_MAIN} fehlt -- keine Word-Datei"
                ) from exc

            try:
                root = ET.fromstring(payload)
            except ET.ParseError as exc:
                raise BuildError(f"Text {path}: {_DOCX_MAIN} ist kein gueltiges XML: {exc}") from exc

            paragraphs = _docx_paragraphs(root)

            # Kopf-/Fusszeilen und Fussnoten
            for name in sorted(archive.namelist()):
                if re.match(r"^word/(header\d+|footer\d+|footnotes|endnotes)\.xml$", name):
                    try:
                        extra_root = ET.fromstring(archive.read(name))
                        extra_paras = _docx_paragraphs(extra_root)
                        if extra_paras:
                            paragraphs.extend(extra_paras)
                    except Exception:
                        pass

            # Eingebettete Bilder (word/media/*)
            if image_sink is not None:
                for name in sorted(archive.namelist()):
                    if name.startswith("word/media/"):
                        data = archive.read(name)
                        mime = image_input._sniff(data)
                        if not mime:
                            sfx = Path(name).suffix.lower()
                            mime = image_input._SUFFIX_MIME.get(sfx, "")
                        if mime:
                            image_sink.append((data, Path(name).name, mime))

    except zipfile.BadZipFile as exc:
        raise BuildError(f"Text {path}: kein gueltiges DOCX (ZIP): {exc}") from exc
    except OSError as exc:
        raise BuildError(f"Text {path}: nicht lesbar ({exc})") from exc

    if not paragraphs:
        raise BuildError(f"Text {path}: kein Absatz mit Text -- leerer Text ist kein Ergebnis")
    return "\n\n".join(paragraphs)


def _read_csv_table(path: Path) -> str:
    import csv
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BuildError(f"Text {path}: nicht lesbar ({exc})") from exc
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise BuildError(f"Text {path}: leere CSV-Tabelle")
    delimiter = "," if "," in lines[0] else ";"
    reader = csv.reader(lines, delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise BuildError(f"Text {path}: leere CSV-Tabelle")
    col_count = max(len(r) for r in rows)
    norm_rows = [r + [""] * (col_count - len(r)) for r in rows]
    md_lines = [
        "| " + " | ".join(c.replace("|", r"\|").strip() for c in norm_rows[0]) + " |",
        "| " + " | ".join(["---"] * col_count) + " |",
    ]
    for r in norm_rows[1:]:
        md_lines.append("| " + " | ".join(c.replace("|", r"\|").strip() for c in r) + " |")
    return "\n".join(md_lines)


def _read_pdf(path: Path, image_sink: list[tuple[bytes, str, str]] | None = None) -> str:
    """PDF ueber den stdlib-Leser auslesen; Fehler als BuildError melden."""
    try:
        result = pdf_text.extract_text(path)
        text = result.text
        if result.warnings:
            for warning in result.warnings:
                warnings.warn(warning)
    except pdf_text.PdfError as exc:
        # Falls Scan-PDF ohne Textebene aber mit Bildern
        if image_sink is not None and "Bild" in str(exc):
            pdf_imgs = pdf_text.extract_images(path)
            for idx, (img_bytes, mime) in enumerate(pdf_imgs, start=1):
                image_sink.append((img_bytes, f"seite_{idx}.{'jpg' if 'jpeg' in mime else 'png'}", mime))
            if pdf_imgs:
                return f"[Scan-PDF {path.name}: {len(pdf_imgs)} Bild(er) extrahiert]"
        raise BuildError(str(exc)) from exc

    if image_sink is not None:
        pdf_imgs = pdf_text.extract_images(path)
        for idx, (img_bytes, mime) in enumerate(pdf_imgs, start=1):
            image_sink.append((img_bytes, f"seite_{idx}.{'jpg' if 'jpeg' in mime else 'png'}", mime))

    return text


def read_text_source(path: str | Path, image_sink: list[tuple[bytes, str, str]] | None = None) -> str:
    """Quelltext lesen. Unterstuetzt ``.txt``, ``.md``, ``.docx``, ``.pdf`` und ``.csv``."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".docx":
        text = _read_docx(source, image_sink=image_sink)
    elif suffix == ".pdf":
        text = _read_pdf(source, image_sink=image_sink)
    elif suffix in (".csv", ".tsv"):
        text = _read_csv_table(source)
    elif suffix in (".txt", ".md", ".markdown", ".text"):
        text = _read_plain(source)
    else:
        raise BuildError(
            f"Text {source}: Endung {suffix or '(ohne)'} wird nicht gelesen "
            f"(erlaubt: .txt, .md, .docx, .pdf, .csv)"
        )
    if not text.strip():
        raise BuildError(f"Text {source}: leerer Text ist kein Ergebnis")
    return text


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def resolve_findings_path(out: str | Path, findings: str | Path | None) -> Path:
    """Findings-Ziel: explizit oder ``findings.json`` neben der .qea."""
    if findings is not None:
        return Path(findings)
    return Path(out).parent / FINDINGS_NAME


def _write_findings(findings: Sequence[Mapping[str, str]], path: Path) -> Path:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return validator.write_findings(findings, path)
    except OSError as exc:
        raise BuildError(f"findings: {path} nicht schreibbar ({exc})") from exc


def _failure_findings(message: str) -> list[dict[str, str]]:
    return [
        {
            "severity": "error",
            "object": "(Lauf)",
            "rule": "build",
            "check": "lauf",
            "message": message,
        }
    ]


# --------------------------------------------------------------------------
# Gesamtlauf
# --------------------------------------------------------------------------



#: Verzeichnis mit den 52 Model-Wizard-Vorlagen (BAAINBw, ADMBw).
WIZARD_VERZEICHNIS = Path(__file__).resolve().parents[2] / "knowledge" / "modelwizard"


def _ist_leitfaden_mdg(rules: Mapping[str, Any]) -> bool:
    """Erkennt, ob das geladene Regelwerk zum ADMBw-/NAFv4-Leitfaden passt."""
    source = rules.get("source") or {}
    tech_id = str(source.get("technologyId") or "").casefold()
    tech_name = str(source.get("technologyName") or "").casefold()
    if "admbw" in tech_id or "nafv4" in tech_id or "admbw" in tech_name or "nafv4" in tech_name:
        return True
    stereos = {
        str(e.get("name") or "")
        for e in (rules.get("elementStereotypes") or ())
        if isinstance(e, Mapping)
    }
    return bool({"ArchitecturalDescription", "Capability", "ServiceSpecification"} & stereos)


def _wizard_vorlagen() -> dict[str, "wizard_module.Vorlage"]:
    """Die Modellvorlagen laden, wenn sie vorliegen -- sonst leer.

    Sie sind optional: ohne sie laeuft die Leitfaden-Pruefung, nur ohne den
    Abgleich je Viewpoint.
    """
    if not WIZARD_VERZEICHNIS.is_dir():
        return {}
    try:
        return wizard_module.lade_alle(WIZARD_VERZEICHNIS)
    except (OSError, ValueError):
        return {}


def build(
    *,
    mdg: str | Path,
    skeleton: str | None = None,
    text: str | Path | None = None,
    out: str | Path,
    images: Sequence[str | Path] = (),
    package: str = DEFAULT_PACKAGE,
    backend: extract_module.Backend | None = None,
    backend_kind: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    answer_file: str | Path | None = None,
    timeout: float = 120.0,
    schema_path: str | Path | None = None,
    findings_path: str | Path | None = None,
    dry_run: bool = False,
    strict: bool = False,
    sidecar: bool = True,
    quellen_path: str | Path | None = None,
    repair: bool = False,
    repair_rounds: int = 6,
    batch_chars: int | None = None,
    batch_threshold: int | None = None,
    context_tokens: int | None = None,
    startpaket: str | Path | None = None,
    katalog: str | Path | None = None,
    modell: str | Path | None = None,
    ai_backend: object | None = None,
    repair_bericht: str | Path | None = None,
    repair_ir_path: str | Path | None = None,
    struktur: bool = True,
    mit_sichten: bool = True,
    sichten_modus: str = "leitfaden",
    wizard_dir: str | Path | None = None,
    ziel_format: str = "qea",
    log: Log | None = None,
) -> BuildReport:
    """Technologie + Prosa -> .qea/.xmi/.json. Liefert den Bericht, bricht laut ab.

    ``backend`` ist ein vorbereitetes Backend (Tests, Einbettung). Ohne Backend
    wird eines aus ``backend_kind`` gebaut; nur dieses spricht HTTP.

    Ohne ``text`` und ohne ``images`` wird kein Backend gebaut: dann entsteht
    ein Geruest allein aus dem Regelwerk (``skeleton``). Ein ausdruecklich
    gesetztes Backend ohne Quelle ist ein Aufruffehler, kein leerer Lauf.
    """
    out_path = Path(out)
    if ziel_format not in {"qea", "xmi", "archimate", "xml", "json"}:
        raise BuildError(f"Format {ziel_format!r} unbekannt -- qea, xmi, archimate, xml oder json")
    target_findings = resolve_findings_path(out_path, findings_path)
    if target_findings.resolve() == out_path.resolve():
        raise BuildError("findings und Zieldatei sind derselbe Pfad")

    say: Log = log if log is not None else (lambda _message: None)
    image_paths = tuple(Path(item) for item in images)

    findings: list[dict[str, str]] = []
    try:
        endungen = {".qea": "qea", ".xmi": "xmi", ".json": "json", ".xml": "archimate", ".archimate": "archimate"}
        erwartet = endungen.get(out_path.suffix.lower())
        if erwartet is None:
            raise BuildError(
                f"Ziel {out_path}: Endung muss .qea, .xmi, .xml oder .json sein"
            )
        effektiv_ziel = "archimate" if ziel_format == "xml" else ziel_format
        if erwartet != effektiv_ziel:
            raise BuildError(
                f"Ziel {out_path}: Endung {out_path.suffix} passt nicht zum "
                f"--format {ziel_format}"
            )
        if quellen_path is not None and Path(quellen_path).resolve() == out_path.resolve():
            raise BuildError("quellen und .qea sind derselbe Pfad")
        if quellen_path is not None and not sidecar:
            raise BuildError("--quellen und --no-quellen schliessen sich aus")

        # 1/6 Technologie laden
        rules = load_technology(mdg, schema_path=schema_path)
        source = rules.get("source", {})
        if not isinstance(source, Mapping):
            source = {}
        technique = {
            "name": str(source.get("technologyName", "")),
            "version": str(source.get("technologyVersion", "")),
            "id": str(source.get("technologyId", "")),
            "file": str(source.get("file", Path(mdg).name)),
            "sha256": str(source.get("sha256", "")),
        }
        stats = rules.get("stats", {})
        say(
            f"[1/6] Technologie: {technique['name']} {technique['version']}".rstrip()
            + f" ({stats.get('elementStereotypes', 0)} Element-Stereotypen,"
            + f" {stats.get('connectorRules', 0)} Konnektor-Regeln)"
        )

        # 2/6 Technologie pruefen: Schema ist bereits geprueft; zusaetzlich
        # muss die Extraktion mindestens ein instanziierbares Stereotyp sehen.
        try:
            rulebook = extract_module.load_rules(rules)
        except ExtractionError as exc:
            raise BuildError(f"Technologie: {exc}") from exc
        say(
            f"[2/6] Regelwerk: schema-konform, {len(rulebook.elements)} nutzbare "
            f"Element-Stereotype, {len(rulebook.connectors)} Beziehungs-Stereotype"
        )

        # 3/6 Quelle lesen -- Text und/oder Bilder. Ohne beides: Geruest.
        chosen = backend
        text_inputs: list[Path] = []
        if text is not None:
            if isinstance(text, (str, Path)):
                text_inputs.append(Path(text))
            elif isinstance(text, Sequence):
                for item in text:
                    if item:
                        text_inputs.append(Path(item))
        skeleton_mode = not text_inputs and not image_paths
        if skeleton_mode and (backend is not None or backend_kind):
            raise BuildError(
                "Ohne --text und ohne --bild kein Modellaufruf: Backend angegeben, "
                "aber keine Quelle -- Abbruch statt leerem Lauf"
            )

        # Bestand und Startpaket gelten fuer Extraktion UND Export. Hier
        # initialisieren: der Geruestpfad (ohne Modellaufruf) laeuft sonst in
        # einen UnboundLocalError beim Export.
        bestand: list[tuple[str, str]] = []
        bestand_qea: Path | None = None
        katalog_obj = None

        if skeleton_mode:
            say("[3/6] Kein Text, kein Bild: Geruest aus dem Regelwerk (kein Modellaufruf)")
            # Zwei Gerueste: "architektur" legt die MASC-Struktur an (Katalog,
            # Viewpoints, Volumes) -- das ist der Standard. "metaklasse" ist der
            # alte Weg (ein Paket je UML-Metaklasse) und bleibt fuer Vergleichs-
            # laeufe zugaenglich.
            geruest_art = skeleton or (
                ARCH_SKELETON_KIND
                if (struktur and _ist_leitfaden_mdg(rules))
                else skeleton_module.SKELETON_KIND
            )
            if geruest_art == skeleton_module.SKELETON_KIND:
                # Alter Weg: ein Paket je UML-Metaklasse (nur Vergleichslaeufe).
                try:
                    skeleton_ir = skeleton_module.build_skeleton(rules, package=package)
                except skeleton_module.SkeletonError as exc:
                    raise BuildError(f"Geruest: {exc}") from exc
                backend_label = skeleton_module.SKELETON_BACKEND
            elif geruest_art == MASC_KIND:
                # Musterarchitektur-Struktur (aeltere MASC-QEA). Nicht
                # leitfadenkonform -- bleibt fuer Vergleiche zugaenglich.
                try:
                    skeleton_ir = skeleton_arch_module.build_arch_skeleton(rules, package=package)
                except skeleton_arch_module.ArchSkeletonError as exc:
                    raise BuildError(f"Geruest: {exc}") from exc
                backend_label = skeleton_arch_module.ARCH_BACKEND
            else:
                # Standard: die in Abbildung 1 und den xx-MK01-Konventionen
                # vorgegebene Struktur des Leitfadens.
                auftrag = architektur_module.Auftrag(
                    projekt=str(package or "Architektur"),
                    titel=str(package or "Architektur"),
                    architekt="",
                    einstufung="OFFEN",
                )
                try:
                    skeleton_ir = architektur_module.build_architektur(
                        rules, auftrag, mit_sichten=mit_sichten, sichten_modus=sichten_modus, wizard_dir=wizard_dir
                    )
                except Exception as exc:  # noqa: BLE001 -- Fehler praezise weiterreichen
                    raise BuildError(f"Geruest: {exc}") from exc
                backend_label = architektur_module.ARCH_BACKEND
            result: ExtractionResult = ExtractionResult(
                ir=skeleton_ir,
                segments=(),
                dropped=(),
                attempts=0,
                backend=backend_label,
            )
            say(
                f"[4/6] Geruest ({geruest_art}): {len(result.elements)} Element(e), "
                f"{len(result.connectors)} Beziehung(en), "
                f"{len(result.ir['packages'])} Paket(e), 0 Modellaufrufe"
            )
        else:
            if chosen is None:
                try:
                    chosen = extract_module.make_backend(
                        backend_kind or "openai",
                        model=model,
                        base_url=base_url,
                        answer_file=answer_file,
                        timeout=timeout,
                        context_tokens=context_tokens,
                    )
                except ExtractionError as exc:
                    raise BuildError(f"Backend: {exc}") from exc

            bildbloecke: list[str] = []
            text_docs: list[str] = []
            import tempfile
            with tempfile.TemporaryDirectory() as tmp_dir_str:
                tmp_dir = Path(tmp_dir_str)
                # 1. Texte und eingebettete Bilder lesen
                for tp in text_inputs:
                    embedded_images: list[tuple[bytes, str, str]] = []
                    t_content = read_text_source(tp, image_sink=embedded_images)
                    text_docs.append(t_content)
                    for emb_bytes, emb_name, emb_mime in embedded_images:
                        emb_file = tmp_dir / emb_name
                        emb_file.write_bytes(emb_bytes)
                        try:
                            emb_desc = image_input.describe_image(emb_file, chosen)
                            bildbloecke.append(f"[Bildquelle: {tp.name} / {emb_name}]\n{emb_desc}")
                        except image_input.ImageInputError:
                            # Falls offline und kein Vision-Backend aktiv: Hinweis als Prosa
                            bildbloecke.append(f"[Eingebettetes Bild: {tp.name} / {emb_name}]")

                # 2. Explizite Bilder lesen
                for image_path in image_paths:
                    try:
                        description = image_input.describe_image(image_path, chosen)
                    except image_input.ImageInputError as exc:
                        raise BuildError(f"Bild {image_path}: {exc}") from exc
                    bildbloecke.append(f"[Bildquelle: {image_path.name}]\n{description}")

            # Dokumente zusammenstellen
            if len(text_docs) <= 1:
                document = text_docs[0] if text_docs else ""
                if bildbloecke:
                    if document.strip():
                        bildbloecke.append(document)
                    document = "\n\n".join(bildbloecke)
                batch_inputs = [document]
                documents = extract_module.split_documents(document)
            else:
                doc_sources: list[str] = []
                if bildbloecke:
                    doc_sources.append("\n\n".join(bildbloecke))
                doc_sources.extend(text_docs)
                batch_inputs = doc_sources
                documents = extract_module.split_documents(doc_sources)

            text_label = ", ".join(str(tp) for tp in text_inputs) if text_inputs else ""
            if image_paths and text_inputs:
                quellen_text = f"{text_label}: {len(documents)} Absaetze"
                quellen_text += f", {len(image_paths)} Bild(er) vorangestellt"
            elif image_paths:
                quellen_text = (
                    f"{len(image_paths)} Bild(er) als Prosa, {len(documents)} Absaetze"
                )
            else:
                quellen_text = f"{text_label}: {len(documents)} Absaetze"
            say(f"[3/6] Quelle: {quellen_text} (D1-S1..{documents[-1].ref})")

            # 4/6 Extrahieren. Ein Startpaket (StEKa) wird vorab gelesen und in
            # den Prompt gelegt: Seine Elemente sind bereits im Modell, die
            # Extraktion soll sie mit exaktem Namen wiederverwenden statt
            # Dubletten zu erfinden. Die Kennungen bleiben beim Export erhalten.
            if modell is not None:
                bestand_qea = Path(modell)
                if not bestand_qea.exists():
                    raise BuildError(f"Modell {bestand_qea}: Datei nicht gefunden")
                try:
                    bestand = _modell_inventar(bestand_qea)
                except (OSError, sqlite3.Error) as exc:
                    raise BuildError(f"Modell {bestand_qea}: {exc}") from exc
                say(f"        Bestand: {len(bestand)} vorhandene Element(e) im Prompt")
            katalog_obj = None
            katalog_bekannte: list[tuple[str, str]] = []
            if katalog is not None:
                try:
                    import catalog_index

                    katalog_obj = catalog_index.Catalog.from_qea(katalog)
                except Exception as exc:  # noqa: BLE001 - Meldung reicht dem Nutzer
                    raise BuildError(f"Katalog {katalog}: {exc}") from exc
                katalog_bekannte = [
                    (eintrag.name, eintrag.stereotype)
                    for eintrag in sorted(katalog_obj.entries, key=lambda e: (e.stereotype, e.name))[:400]
                ]
                say(f"        Katalog: {len(katalog_obj)} Standardelement(e) im Prompt")
            standard: list[tuple[str, str]] = []
            if startpaket is not None:
                try:
                    standard = _startpaket_inventar(Path(startpaket))
                except (OSError, sqlite3.Error) as exc:
                    raise BuildError(f"Startpaket {startpaket}: {exc}") from exc
                if not standard:
                    raise BuildError(
                        f"Startpaket {startpaket}: keine Elemente gefunden -- "
                        "das ist kein Startpaket"
                    )
                say(f"        Startpaket: {len(standard)} Standardelement(e) im Prompt")
            # Bestand zuerst: Vorhandenes vor Standardelementen. Beides zusammen
            # ist der Wiederverwendungs-Block im Prompt.
            bekannte = list(dict.fromkeys(katalog_bekannte + bestand + standard))
            try:
                result = extract_module.extract_batched(
                    batch_inputs,
                    rules=rulebook,
                    backend=chosen,
                    package=package,
                    known=tuple(bekannte),
                    context_tokens=context_tokens,
                    **(
                        {"budget_chars": batch_chars}
                        if batch_chars is not None
                        else {}
                    ),
                    **(
                        {"threshold_chars": batch_threshold}
                        if batch_threshold is not None
                        else {}
                    ),
                )
            except ExtractionError as exc:
                raise BuildError(f"Extraktion: {exc}") from exc
            # Eindeutige Handlungssaetze nachziehen, bevor die MDG prueft:
            # Der Modellaufruf findet Elemente und Notizen, laesst aber Kanten
            # liegen, deren beide Endpunkte im selben Satz stehen.
            nachtraege: list[Any] = []
            try:
                kantenregeln = validator.build_rules(rules)
                nachtraege = relation_module.ergaenze(result.ir, documents, kantenregeln)
            except validator.ValidatorError:
                nachtraege = []
            chargen = result.ir.get("meta", {}).get("extraction", {}).get("chargen", [])
            say(
                f"[4/6] Extraktion: {result.backend}: {len(result.elements)} Element(e), "
                f"{len(result.connectors)} Beziehung(en), {result.attempts} Versuch(e), "
                f"{len(result.dropped)} verworfen"
                + (f", {len(chargen)} Chargen" if chargen else "")
            )
            bestand_endpunkte = (
                result.ir.get("meta", {}).get("extraction", {}).get("bekannte_endpunkte", [])
            )
            if bestand_endpunkte:
                say(f"        Endpunkte aus dem Bestand: {len(bestand_endpunkte)}")
            if nachtraege:
                say(f"        Kanten nachgetragen: {len(nachtraege)}")
                for nachtrag in nachtraege:
                    say(
                        f"        + {nachtrag.quelle} -> {nachtrag.ziel} "
                        f"[{nachtrag.stereotyp}] ({nachtrag.ref})"
                    )
            for drop in result.dropped:
                say(f"        verworfen: {drop.kind} {drop.name!r}: {drop.reason}")

            # 4b/6 Inhalt in die Leitfaden-Struktur einsortieren.
            # Mit ``struktur=False`` bleibt das flache Extraktionsergebnis
            # stehen -- fuer Vergleichslaeufe und fuer Regelwerke, die die
            # Leitfaden-Struktur nicht abdecken.
            # Die Extraktion liefert ein flaches Modell (ein Zielpaket). Erst
            # hier entsteht die Struktur aus Abbildung 1: Perspektiven,
            # Viewpoint-Pakete, Katalog, Sichten. Der Inhalt behaelt Name,
            # Stereotyp, Notiz und Herkunft; nur das Paket wird gesetzt.
            if struktur and _ist_leitfaden_mdg(rules):
                auftrag = architektur_module.Auftrag(
                    projekt=str(package or "Architektur"),
                    titel=str(package or "Architektur"),
                    architekt="",
                    einstufung="OFFEN",
                )
                try:
                    struktur_ir = architektur_module.build_architektur(
                        rules,
                        auftrag,
                        inhalte=result.ir,
                        mit_sichten=mit_sichten,
                        sichten_modus=sichten_modus,
                        wizard_dir=wizard_dir,
                    )
                except Exception as exc:  # noqa: BLE001 -- Fehler praezise weiterreichen
                    raise BuildError(f"Leitfaden-Struktur: {exc}") from exc
                struktur_ir.setdefault("meta", {}).update(dict(result.ir.get("meta") or {}))
                result = dataclasses.replace(result, ir=struktur_ir)
                say(
                    f"[4b/6] Leitfaden-Struktur: {len(result.ir['packages'])} Paket(e), "
                    f"{len(result.elements)} Element(e), {len(result.connectors)} Beziehung(en), "
                    f"{len(result.ir.get('diagrams') or ())} Sicht(en)"
                )

        # 5/6 Validieren -- und mit --repair selbsttaetig gegen die MDG geraderuecken
        try:
            ruleset = validator.build_rules(rules)
            findings = validator.validate_model(result.ir, ruleset)
            if (
                repair
                and chosen is not None
                and any(f["severity"] == validator.ERROR for f in findings)
            ):
                outcome = repair_module.repair(
                    result.ir,
                    ruleset,
                    max_rounds=repair_rounds,
                    ai_fix=repair_module.make_ai_fix(chosen, rulebook),
                )
                result = replace(result, ir=outcome.ir)
                findings = outcome.findings
                for runde in outcome.rounds:
                    say(
                        f"        Reparatur Runde {runde.number}: "
                        f"{runde.errors_before} -> {runde.errors_after} Fehler, "
                        f"{len(runde.changes)} Aenderung(en)"
                    )
                if repair_bericht:
                    Path(repair_bericht).write_text(
                        json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
        except ValidatorError as exc:
            raise BuildError(f"Pruefung: {exc}") from exc
        counts = validator.summarize(findings)
        try:
            _write_findings(findings, target_findings)
        except BuildError as exc:
            raise BuildError(f"{exc} -- der Lauf ist damit nicht belegt") from exc
        say(
            f"[5/6] Pruefung: {counts['total']} Findings: {counts['error']} Fehler, "
            f"{counts['warning']} Warnungen -> {target_findings}"
        )

        # 5b) Methodische Pruefung: Leitfaden-Konventionen und die 52
        #     Model-Wizard-Vorlagen. Sie blockiert nicht -- ein Leitfaden-
        #     Verstoss ist ein Befund, kein Exportfehler.
        if _ist_leitfaden_mdg(rules):
            try:
                modell = struktur_module.from_ir(result.ir)
                vorlagen = _wizard_vorlagen()
                lf = struktur_module.validate(
                    modell,
                    str(result.ir.get("projekt") or package or "Projekt"),
                    vorlagen=vorlagen or None,
                )
            except Exception as exc:  # noqa: BLE001 -- Pruefung darf den Bau nicht kippen
                say(f"[5b] Leitfaden-Pruefung nicht ausfuehrbar: {exc}")
            else:
                zahlen = struktur_module.summary(lf)
                say(
                    f"[5b] Leitfaden-Pruefung: {zahlen['error']} Fehler, "
                    f"{zahlen['warning']} Warnungen, {zahlen['info']} Hinweise"
                    + ("" if not vorlagen else f" (inkl. {len(vorlagen)} Model-Wizard-Vorlagen)")
                )
                for zeile in struktur_module.render(lf, limit=8).splitlines()[1:]:
                    say("       " + zeile.strip())

        if repair_ir_path:
            # Zwischenstand sichern: zeigt, was die KI gebaut hat, bevor der
            # Export blockiert -- sonst ist ein gescheiterter Lauf nicht pruefbar.
            Path(repair_ir_path).write_text(
                json.dumps(result.ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        blocked = bool(counts["error"]) or (strict and bool(counts["warning"]))
        if blocked:
            reason = (
                "Warnungen blockieren (--strict)"
                if counts["error"] == 0 and strict
                else "Fehler im Modell"
            )
            say(f"[6/6] Kein Export: {reason}")
            return _report(
                technique, result, findings, target_findings, out_path,
                qea=None, quellen=None, digest="", provenance_tags=0, exported=False,
                dry_run=dry_run, strict=strict,
            )

        # 6/6 Emittieren
        if dry_run:
            say("[6/6] Trockenlauf: keine .qea, keine quellen.json geschrieben")
            return _report(
                technique, result, findings, target_findings, out_path,
                qea=None, quellen=None, digest="", provenance_tags=0, exported=False,
                dry_run=True, strict=strict,
            )

        # Standardelemente: Namen aus dem Katalog bekommen dessen Kennung und
        # Heimatpaket. Das geschieht vor dem Schreiben, damit die Datei von
        # Anfang an die Katalog-GUIDs traegt (und nicht erst ein Merge sie biegt).
        if katalog_obj is not None:
            zaehler = katalog_obj.apply(result.ir)
            say(
                f"        Katalog: {zaehler['katalog']} Element(e) wiedererkannt, "
                f"{zaehler['neu']} neu"
            )

        # 6/6 Emittieren -- drei Zielformate, ein Gate. Nur .qea kennt
        # quellen.json, Startpaket und Bestandszusammenfuehrung.
        if ziel_format != "qea":
            if startpaket is not None or bestand_qea is not None:
                raise BuildError(
                    "--startpaket/--modell gibt es nur beim Format qea"
                )
            if ziel_format == "xmi":
                import model_io

                ziel = model_io.write_model(result.ir, out_path, format="xmi")
            elif ziel_format in ("archimate", "xml"):
                import model_io

                ziel = model_io.write_model(
                    result.ir, out_path, format="archimate", modellname=out_path.stem
                )
            else:
                import model_io

                quelle = ""
                if isinstance(text, (str, Path)):
                    quelle = Path(text).name if isinstance(text, Path) else "prosa"
                ziel = model_io.write_model(
                    result.ir,
                    out_path,
                    format="json",
                    source_document=quelle or out_path.name,
                )
            digest = hashlib.sha256(ziel.read_bytes()).hexdigest()
            say(
                f"[6/6] Export ({ziel_format}): {ziel}: "
                f"{len(result.elements)} Elemente, {len(result.connectors)} Beziehungen, "
                f"sha256 {digest[:16]}"
            )
            return _report(
                technique, result, findings, target_findings, out_path,
                qea=ziel, quellen=None, digest=digest,
                provenance_tags=0, exported=True, dry_run=False, strict=strict,
            )

        emit_target = out_path
        zwischen: Path | None = None
        basis = bestand_qea
        if basis is not None and startpaket is None:
            # Fortsetzen: der Bestand ist die Basis, das neue Teilmodell kommt
            # dazu. Kollidierende Kennungen bleiben eine Zeile (merge_models).
            zwischen = out_path.with_name(out_path.stem + ".neu.qea")
            emit_target = zwischen
        if startpaket is not None or basis is not None:
            # Erst in eine Zwischendatei schreiben, dann den Katalog mit
            # unveraenderten ea_guid uebernehmen (toolbox_merge ist der
            # geprüfte Weg dafuer). So bleibt der Export atomar.
            zwischen = zwischen or out_path.with_name(out_path.stem + ".ohne-startpaket.qea")
            emit_target = zwischen
        try:
            emitted: EmitReport = emit_module.emit(
                result.ir,
                emit_target,
                quellen_path=quellen_path,
                sidecar=sidecar,
                verify=True,
            )
        except (EmitError, QeaWriterError, QeaReaderError, OSError) as exc:
            raise BuildError(f"Export: {exc}") from exc
        standard_report: dict[str, Any] | None = None
        if zwischen is not None and (startpaket is not None or basis is not None):
            try:
                import model_merge
                import toolbox_merge

                # Reihenfolge: erst das Startpaket, dann der vorhandene Bestand.
                # Umgekehrt zoege der Bestand seine eigenen (umgehaengten)
                # Katalogkopien mit herein, und dieselbe Sache stuende zweimal
                # in der Datei -- sowie unter zwei verschiedenen Elternpaketen.
                # model_merge legt danach ueber ea_guid UND Name zusammen.
                schritt = zwischen
                if startpaket is not None:
                    # Enthält das Startpaket nur einen Katalog (StEKa /
                    # Modellelementekatalog) in einem größeren Projektmodell
                    # (z. B. MASC), übernehmen wir mit toolbox_merge gezielt nur
                    # die Katalogpakete, damit keine fremden Wurzelpakete ins
                    # Modell kopiert werden und neue Diagramme erhalten bleiben.
                    start_pfad = Path(startpaket)
                    katalog_wurzeln: list[str] = []
                    con_s = sqlite3.connect(str(start_pfad))
                    con_s.execute("PRAGMA query_only = ON")
                    try:
                        alle_wurzeln = [
                            str(n or "")
                            for (n,) in con_s.execute(
                                "SELECT Name FROM t_package WHERE Parent_ID = 0"
                            )
                        ]
                        hat_fremd = any(
                            w and not w.casefold().startswith("steka") and w != "Modellelementekatalog"
                            for w in alle_wurzeln
                        )
                        if hat_fremd:
                            for (pname,) in con_s.execute("SELECT Name FROM t_package"):
                                p_str = str(pname or "").strip()
                                if (
                                    p_str == "Modellelementekatalog"
                                    or p_str.casefold().startswith("steka")
                                ):
                                    if p_str not in katalog_wurzeln:
                                        katalog_wurzeln.append(p_str)
                    finally:
                        con_s.close()
                    mit_start = out_path.with_name(out_path.stem + ".mit-startpaket.qea")
                    if katalog_wurzeln:
                        t_rep = toolbox_merge.merge_toolbox(
                            schritt,
                            start_pfad,
                            mit_start,
                            paketname="StEKa",
                            nur=katalog_wurzeln,
                        )
                        standard_report = {
                            "elemente": t_rep["elemente"],
                            "kanten": t_rep["kanten"],
                            "bereits_vorhanden": t_rep["bereits_vorhanden"],
                            "warnungen": list(t_rep.get("warnungen") or ()),
                        }
                        mit_start.with_suffix(".bak.qea").unlink(missing_ok=True)
                    else:
                        # Reines Startpaket: ist die Basis, damit seine ea_guid
                        # woertlich erhalten bleiben und gleiche Elemente aus
                        # dem Lauf ueber Name + Stereotyp auf die vorhandene
                        # Zeile gebogen werden.
                        startbasis = out_path.with_name(out_path.stem + ".startbasis.qea")
                        shutil.copyfile(start_pfad, startbasis)
                        rep = model_merge.merge_models(
                            [startbasis, schritt], mit_start, per_name=True
                        )
                        standard_report = {
                            "elemente": rep.elements,
                            "kanten": rep.connections,
                            "bereits_vorhanden": rep.merged,
                            "warnungen": list(rep.warnings),
                        }
                        startbasis.unlink(missing_ok=True)
                    schritt.unlink(missing_ok=True)
                    schritt = mit_start
                if basis is not None:
                    mit_bestand = out_path.with_name(out_path.stem + ".mit-bestand.qea")
                    model_merge.merge_models([schritt, basis], mit_bestand, per_name=True)
                    schritt.unlink(missing_ok=True)
                    schritt = mit_bestand
                schritt.replace(out_path)
            except Exception as exc:  # noqa: BLE001 - Fehlerabbildung unten
                zwischen.unlink(missing_ok=True)
                raise BuildError(f"Zusammenfuehrung: {exc}") from exc
            zwischen.unlink(missing_ok=True)
            # Bericht auf die tatsaechliche Zieldatei ziehen: Zahlen und
            # Pruefsumme stammen sonst von der Zwischendatei ohne Katalog.
            from dataclasses import replace as _replace

            con = sqlite3.connect(str(out_path))
            try:
                # Elemente sind alle Objekte ausser Paketspiegeln -- der
                # Reader zaehlt genauso. Ein Filter auf 'Class' unterschlaegt
                # Ports und Objects und meldet zu kleine Zahlen.
                elements_final = con.execute(
                    "select count(*) from t_object where Object_Type <> 'Package'"
                ).fetchone()[0]
                connectors_final = con.execute(
                    "select count(*) from t_connector"
                ).fetchone()[0]
            finally:
                con.close()
            emitted = _replace(
                emitted,
                qea=out_path,
                elements=int(elements_final),
                connectors=int(connectors_final),
                digest=hashlib.sha256(out_path.read_bytes()).hexdigest(),
            )
            if standard_report is not None:
                say(
                    f"        Startpaket uebernommen: {standard_report['elemente']} Element(e), "
                    f"{standard_report['kanten']} Kante(n), "
                    f"{standard_report['bereits_vorhanden']} bereits vorhanden"
                )
            if basis is not None:
                say(f"        Bestand zusammengefuehrt: {basis}")
        say(
            f"[6/6] Export: {emitted.qea}: {emitted.elements} Elemente, "
            f"{emitted.connectors} Beziehungen, {emitted.provenance_tags} Herkunfts-Tags, "
            f"sha256 {emitted.digest[:16]}"
        )
        if basis is not None:
            # Der Bericht nennt den Gesamtstand (Datei), die Extraktion den
            # Zuwachs dieses Laufs. Zwei Zahlen, zwei Aussagen.
            say(
                f"        Neu in diesem Lauf: {len(result.elements)} Element(e), "
                f"{len(result.connectors)} Beziehung(en)"
            )
        return _report(
            technique, result, findings, target_findings, out_path,
            qea=emitted.qea, quellen=emitted.quellen, digest=emitted.digest,
            provenance_tags=emitted.provenance_tags,
            exported=True, dry_run=False, strict=strict,
            elements=emitted.elements, connectors=emitted.connectors,
        )
    except BuildError as exc:
        # Auch ein technischer Abbruch hinterlaesst eine belastbare Spur.
        # Bereits ermittelte Findings bleiben erhalten.
        try:
            _write_findings(list(findings) + _failure_findings(str(exc)), target_findings)
        except BuildError as write_error:
            raise BuildError(f"{exc}; {write_error}") from exc
        raise


def _report(
    technique: Mapping[str, str],
    result: ExtractionResult,
    findings: Sequence[Mapping[str, str]],
    findings_path: Path,
    out: Path,
    *,
    qea: Path | None,
    quellen: Path | None,
    digest: str,
    provenance_tags: int,
    exported: bool,
    dry_run: bool,
    strict: bool,
    elements: int | None = None,
    connectors: int | None = None,
) -> BuildReport:
    chargen = result.ir.get("meta", {}).get("extraction", {}).get("chargen", [])
    return BuildReport(
        technology=dict(technique),
        backend=result.backend,
        batches=len(chargen),
        segments=len(result.segments),
        elements=len(result.elements) if elements is None else elements,
        connectors=len(result.connectors) if connectors is None else connectors,
        dropped=tuple(drop.as_json() for drop in result.dropped),
        attempts=result.attempts,
        findings=tuple(dict(finding) for finding in findings),
        findings_path=findings_path,
        out=out,
        qea=qea,
        quellen=quellen,
        digest=digest,
        provenance_tags=provenance_tags,
        exported=exported,
        dry_run=dry_run,
        strict=strict,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cmd_archimate(args) -> int:
    """IR -> ArchiMate 3.2 Model Exchange XML (viertes Zielformat)."""
    from archimate_writer import ArchimateWriterError, modellkopf, write_archimate
    from qea_reader import QeaReaderError, read_qea_ex

    try:
        if args.ir.suffix.lower() == ".json":
            ir = json.loads(args.ir.read_text(encoding="utf-8"))
        else:
            ir, _ = read_qea_ex(args.ir, with_refs=True, with_owners=True)
        # Ohne --name gilt der Modellkopf aus dem IR -- nur so bleibt
        # ``XML -> IR -> XML`` ueber die CLI byte-identisch. Fehlt er (etwa bei
        # einer .qea-Quelle), ist der Dateiname der Notbehelf.
        modellname = args.name
        if modellname is None:
            modellname = "" if modellkopf(ir)[0] else args.ir.stem
        report = write_archimate(ir, args.out, modellname=modellname)
    except (ArchimateWriterError, QeaReaderError, OSError, ValueError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    daten = report.as_dict()
    if args.report:
        args.report.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"{args.out}: {report.elements} Elemente, {report.relationships} Beziehungen, "
        f"{report.remapped} umgebaut, {report.unresolved} nicht aufloesbar"
    )
    if report.unresolved:
        print(
            "HINWEIS: " + ", ".join(f"{k} {v}" for k, v in sorted(report.unresolved_by_type.items())),
            file=sys.stderr,
        )
    if args.strict and report.unresolved:
        return 1
    return 0


def cmd_archimate_read(args) -> int:
    """ArchiMate 3.2 Model Exchange XML -> IR (Umkehrung von ``archimate``)."""
    from archimate_reader import ArchimateReaderError, read_archimate_ex, render_json

    try:
        ir, report = read_archimate_ex(args.quelle, strict=args.strict)
    except (ArchimateReaderError, OSError, ValueError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    text = render_json(ir)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.report:
        args.report.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(report.summary(), file=sys.stderr if not args.out else sys.stdout)
    return 0


def cmd_archimate_check(args) -> int:
    """ArchiMate-Modell lesen, zusammenfassen, pruefen (XML, IR-JSON, .qea)."""
    import archimate_check

    try:
        ir, format_label = archimate_check.lade_modell(args.quelle)
        befund = archimate_check.pruefe(
            ir, format=format_label, datei=args.quelle.name
        )
    except archimate_check.ArchimateCheckError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 3

    if args.format == "json":
        text = archimate_check.render_json(befund)
    elif args.format == "md":
        text = archimate_check.render_markdown(befund, limit=args.limit)
    elif args.format == "prompt":
        text = archimate_check.render_prompt(befund, args.frage, limit=args.limit)
    else:
        text = archimate_check.render_text(befund, limit=args.limit)

    summary = befund.summary()
    if args.out:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"FEHLER: Bericht nicht schreibbar: {exc}", file=sys.stderr)
            return 3
        print(
            f"{args.out}: {summary['error']} Fehler, {summary['warning']} Warnungen, "
            f"{summary['info']} Hinweise",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)

    if summary["error"]:
        return 1
    if args.strict and summary["warning"]:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eam-ai",
        description="Technologie + Prosa -> .qea (Extraktion, Pruefung, Export).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"eam-ai {__version__}",
        help="Version ausgeben und beenden",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser(
        "build",
        help="MDG laden, Quelle extrahieren (oder Geruest bauen), pruefen, .qea schreiben",
    )
    p_build.add_argument("--mdg", required=True, type=Path, help="MDG-/Technologie-XML")
    p_build.add_argument(
        "--text",
        type=Path,
        action="append",
        default=[],
        help="Quelltext (.txt, .md, .docx, .pdf, .csv), mehrfach angebbar; ohne --text/--bild entsteht ein Geruest",
    )
    p_build.add_argument(
        "--bild",
        type=Path,
        action="append",
        default=[],
        metavar="PFAD",
        help="Bild (PNG/JPG/WebP), mehrfach; Beschreibung wird der Prosa vorangestellt",
    )
    p_build.add_argument("--out", "-o", required=True, type=Path, help="Zieldatei (.qea, .xmi, .xml oder .json)")
    p_build.add_argument(
        "--format",
        dest="ziel_format",
        choices=("qea", "xmi", "archimate", "xml", "json"),
        default="qea",
        help="Zielformat: qea (Standard), xmi (UML 2.1), archimate/xml (ArchiMate 3.2 Exchange) oder json (Knoten/Kanten-Batch)",
    )
    p_build.add_argument(
        "--package", default=DEFAULT_PACKAGE, help=f"Zielpaket (Default: {DEFAULT_PACKAGE})"
    )
    p_build.add_argument(
        "--geruest",
        choices=(LEITFADEN_KIND, MASC_KIND, skeleton_module.SKELETON_KIND),
        default=ARCH_SKELETON_KIND,
        help=(
            "Art des Geruests ohne Quelle: 'leitfaden' = Leitfaden-Struktur "
            "(Katalog, Viewpoints, Volumes; Standard), 'metaklasse' = altes "
            "Geruest (ein Paket je UML-Metaklasse)"
        )
    )
    p_build.add_argument(
        "--backend",
        default=None,
        help="openai, ollama oder datei; ohne --text/--bild kein Modellaufruf",
    )
    p_build.add_argument(
        "--model", default=None, help="Modellname (Default aus EXTRACT_MODEL/OPENAI_MODEL/OLLAMA_MODEL)"
    )
    p_build.add_argument("--base-url", default=None, help="Basis-URL des Endpunkts")
    p_build.add_argument(
        "--antwort", type=Path, default=None, help="Antwortdatei fuer --backend datei (offline)"
    )
    p_build.add_argument("--timeout", type=float, default=120.0, help="HTTP-Zeitueberschreitung in s")
    p_build.add_argument(
        "--schema", type=Path, default=DEFAULT_SCHEMA, help="Schema fuer das Regelwerk"
    )
    p_build.add_argument(
        "--findings",
        type=Path,
        default=None,
        help=f"Findings-Ziel (Default: {FINDINGS_NAME} neben der .qea)",
    )
    p_build.add_argument(
        "--dry-run", action="store_true", help="alles pruefen, aber keine .qea schreiben"
    )
    p_build.add_argument(
        "--strict", action="store_true", help="Warnungen zaehlen wie Fehler"
    )
    p_build.add_argument(
        "--repair",
        action="store_true",
        help="MDG-Fehler selbsttaetig beheben und erneut pruefen (ohne KI)",
    )
    p_build.add_argument(
        "--repair-runden",
        type=int,
        default=6,
        help="Hochstzahl der Reparaturrunden (Default: 6)",
    )
    p_build.add_argument(
        "--ohne-struktur",
        action="store_true",
        help="Inhalt flach lassen (kein Leitfaden-Paketbaum) -- fuer Vergleichslaeufe",
    )
    p_build.add_argument(
        "--ohne-sichten",
        action="store_true",
        help="keine Diagramme anlegen (nur Pakete, Elemente, Beziehungen) -- fuer Pipelines",
    )
    p_build.add_argument(
        "--sichten",
        choices=("aus", "mdg", "leitfaden", "wizard"),
        default="leitfaden",
        help="Sichten-Erstellung: aus, mdg, leitfaden (Standard) oder wizard",
    )
    p_build.add_argument(
        "--wizard-dir",
        type=Path,
        default=None,
        help="Optionales Verzeichnis mit Model-Wizard-Vorlagen (.xml)",
    )
    p_build.add_argument(
        "--repair-ir",
        type=Path,
        default=None,
        help="Zwischenstand der IR als JSON (auch wenn der Export blockiert wird)",
    )
    p_build.add_argument(
        "--repair-bericht",
        type=Path,
        default=None,
        help="Bericht der Reparatur als JSON",
    )
    p_build.add_argument(
        "--chargen-zeichen",
        type=int,
        default=None,
        help=(
            "Quelltext je Charge in Zeichen (Default: 12000). Gilt nur, wenn der "
            "Quelltext die Schwelle ueberschreitet"
        ),
    )
    p_build.add_argument(
        "--chargen-schwelle",
        type=int,
        default=None,
        help="ab dieser Quelltextlaenge wird geteilt (Default: 16000 Zeichen)",
    )
    p_build.add_argument(
        "--kontext-tokens",
        type=int,
        default=None,
        help=(
            "Kontextfenster des Sprachmodells in Tokens (z.B. 8192 oder 4096 fuer kleine lokale LLMs). "
            "Verdichtet das Regelwerk im Prompt, begrenzt max_tokens/num_ctx und verkleinert Chargen automatisch"
        ),
    )
    p_build.add_argument(
        "--modell",
        type=Path,
        default=None,
        help=(
            "bestehendes Modell (.qea), an das dieser Lauf anknuepft: seine "
            "Elemente kommen in den Prompt, das Ergebnis enthaelt Bestand und Neues"
        ),
    )
    p_build.add_argument(
        "--startpaket",
        type=Path,
        default=None,
        help=(
            "Startpaket (StEKa) als .qea: Elemente kommen in den Prompt und mit "
            "unveraenderten Kennungen ins Ergebnis"
        ),
    )
    p_build.add_argument(
        "--katalog",
        type=Path,
        default=None,
        help=(
            "Standard-Elementekatalog (.qea, z. B. Modellelementekatalog der MASC): "
            "genannte Elemente uebernehmen Kennung und Heimatpaket des Katalogs"
        ),
    )
    p_build.add_argument("--quellen", type=Path, default=None, help="Pfad der quellen.json")
    p_build.add_argument(
        "--no-quellen", action="store_true", help="keine quellen.json schreiben"
    )
    p_build.add_argument("-q", "--quiet", action="store_true", help="keine Fortschrittsmeldungen")
    p_build.set_defaults(func=cmd_build)

    p_frage = sub.add_parser(
        "frage",
        help="Frage zu einer vorhandenen .qea beantworten (ohne --backend ohne KI)",
    )
    p_frage.add_argument("--qea", required=True, type=Path, help="Modell (.qea)")
    p_frage.add_argument("--frage", required=True, help="Frage in natuerlicher Sprache")
    scope_group = p_frage.add_mutually_exclusive_group()
    scope_group.add_argument("--paket", default=None, help="nur dieses Paket (mit Unterpaketen)")
    scope_group.add_argument("--element", default=None, help="nur dieses Element (Paket::Name)")
    p_frage.add_argument("--out", type=Path, default=None, help="Antwort als Markdown schreiben")
    p_frage.add_argument(
        "--backend", default=None, help="openai (ohne Angabe: nur Beschreibung, ohne KI)"
    )
    p_frage.add_argument("--model", default=None, help="Modellname (Default aus der Umgebung)")
    p_frage.add_argument("--base-url", default=None, help="Basis-URL des Endpunkts")
    p_frage.add_argument("--timeout", type=float, default=120.0, help="HTTP-Zeitueberschreitung in s")
    p_frage.set_defaults(func=cmd_frage)

    p_serve = sub.add_parser(
        "serve",
        help="Weboberflaeche starten (stdlib, eine Seite, gleicher Kern)",
    )
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bindeadresse (Default: 127.0.0.1; im Container 0.0.0.0)",
    )
    p_serve.add_argument("--port", type=int, default=8080, help="Port (Default: 8080)")
    p_serve.add_argument(
        "--max-upload-mb",
        type=int,
        default=25,
        help="Upload-Grenze in MB (Default: 25)",
    )
    p_serve.add_argument(
        "--max-seconds",
        type=float,
        default=1800.0,
        help="Gesamt-Zeitlimit je Lauf in Sekunden (Default: 1800 = 30 Min., fuer mehrstufige Chargen)",
    )
    p_serve.add_argument(
        "--jobs", type=int, default=2, help="gleichzeitige Laeufe (Default: 2)"
    )
    p_serve.add_argument(
        "--job-ttl",
        type=float,
        default=600.0,
        help="Aufbewahrung der Ergebnisse in Sekunden (Default: 600)",
    )
    p_serve.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Basis fuer Arbeitsverzeichnisse (Default: System-Temp)",
    )
    p_serve.add_argument(
        "--assets",
        type=Path,
        default=None,
        help="Verzeichnis mit Beispiel-Technologie und Beispielantwort",
    )
    p_serve.set_defaults(func=cmd_serve)

    p_merge = sub.add_parser(
        "merge",
        help="mehrere .qea zu einem Modell zusammenfuehren (GUID-erhaltend)",
    )
    p_merge.add_argument(
        "--qea",
        action="append",
        nargs="+",
        required=True,
        metavar="QEA",
        help="Modelle in Einfuegereihenfolge; das erste ist die Basis (mehrfach angebbar)",
    )
    p_merge.add_argument("--out", "-o", required=True, type=Path, help="Ziel .qea")
    p_merge.add_argument(
        "--paket",
        default=None,
        metavar="NAME",
        help="optionales Sammelpaket fuer die Wurzelpakete der weiteren Modelle",
    )
    p_merge.add_argument(
        "--bericht",
        type=Path,
        default=None,
        help="Bericht (JSON) zusaetzlich in diese Datei schreiben",
    )
    p_merge.add_argument(
        "--per-name",
        action="store_true",
        help=(
            "Elemente zusaetzlich ueber Name und Stereotyp zusammenlegen: noetig, "
            "wenn zwei getrennte Laeufe dasselbe Element neu angelegt haben"
        ),
    )
    p_merge.set_defaults(func=cmd_merge)

    p_edit = sub.add_parser(
        "edit",
        help="gezielte Aenderungen an einer .qea anwenden (Original bleibt unberuehrt)",
    )
    p_edit.add_argument("--qea", required=True, type=Path, help="Quellmodell .qea")
    p_edit.add_argument("--ops", required=True, type=Path, help="Operationen (JSON-Liste)")
    p_edit.add_argument("--out", "-o", required=True, type=Path, help="Ziel .qea")
    p_edit.add_argument(
        "--mdg",
        type=Path,
        default=None,
        help="MDG-/Technologie-XML: jede Operation wird gegen das Regelwerk geprueft",
    )
    p_edit.set_defaults(func=cmd_edit)

    p_korr = sub.add_parser(
        "korrigiere",
        help="Korrektur in natuerlicher Sprache vorschlagen (und mit --apply schreiben)",
    )
    p_korr.add_argument("--qea", required=True, type=Path, help="Quellmodell .qea")
    source = p_korr.add_mutually_exclusive_group(required=True)
    source.add_argument("--anweisung", help="Korrektur in natuerlicher Sprache")
    source.add_argument(
        "--anweisung-datei", type=Path, help="Textdatei mit der Korrektur"
    )
    p_korr.add_argument(
        "--out", "-o", type=Path, default=None, help="Ziel .qea (nur mit --apply)"
    )
    p_korr.add_argument(
        "--apply", action="store_true", help="Vorschlag wirklich schreiben (sonst nur Vorschau)"
    )
    p_korr.add_argument(
        "--ja",
        action="store_true",
        help="Loeschoperationen ausdruecklich bestaetigen (confirm-before-destroy)",
    )
    p_korr.add_argument(
        "--mdg", type=Path, default=None, help="MDG-/Technologie-XML fuer die Pruefung"
    )
    p_korr.add_argument(
        "--backend",
        default=None,
        help="openai oder ollama; ohne Angabe arbeitet die feste Befehlsgrammatik",
    )
    p_korr.add_argument("--model", default=None, help="Modellname fuer das Backend")
    p_korr.add_argument("--base-url", default=None, help="Basis-URL des Backends")
    p_korr.add_argument(
        "--antwort", type=Path, default=None, help="Antwortdatei fuer --backend datei"
    )
    p_korr.add_argument("--timeout", type=float, default=120.0, help="HTTP-Zeitueberschreitung in s")
    p_korr.add_argument("--json", action="store_true", help="Vorschlag als JSON ausgeben")
    p_korr.set_defaults(func=cmd_korrigiere)

    p_toolbox = sub.add_parser(
        "toolbox",
        help="Standardelemente aus einem Katalog uebernehmen (GUID-erhaltend)",
    )
    p_toolbox.add_argument(
        "--kasten",
        required=True,
        type=Path,
        metavar="QEA",
        help="Katalog-/Startpaket-Datei mit den Standardelementen (wird nur gelesen)",
    )
    p_toolbox.add_argument(
        "--modell",
        type=Path,
        default=None,
        metavar="QEA",
        help="bestehendes Modell harmonisieren; ohne Angabe startet ein leeres Modell",
    )
    p_toolbox.add_argument("--out", "-o", required=True, type=Path, help="Ziel .qea")
    p_toolbox.add_argument(
        "--paket",
        default="Standard",
        metavar="NAME",
        help="Dachpaket im Ziel, unter dem der Katalog haengt (Default: Standard)",
    )
    p_toolbox.add_argument(
        "--startpaket",
        default="Architektur",
        metavar="NAME",
        help="Wurzelpaket, wenn ohne --modell begonnen wird (Default: Architektur)",
    )
    p_toolbox.add_argument(
        "--nur",
        action="append",
        default=None,
        metavar="PAKET",
        help="nur diese Katalogpakete uebernehmen (mehrfach angebbar, samt Unterpaketen)",
    )
    p_toolbox.add_argument(
        "--bericht",
        type=Path,
        default=None,
        help="Bericht (JSON) zusaetzlich in diese Datei schreiben",
    )
    p_toolbox.add_argument(
        "--nur-bericht",
        action="store_true",
        help="nur pruefen und Bericht zeigen, keine .qea schreiben",
    )
    p_toolbox.set_defaults(func=cmd_toolbox)

    p_arch = sub.add_parser(
        "archimate",
        help="IR (.qea/.json) -> ArchiMate 3.2 Model Exchange XML",
    )
    p_arch.add_argument("--ir", required=True, type=Path, help="IR-JSON oder .qea")
    p_arch.add_argument("--out", "-o", required=True, type=Path, help="Zieldatei .xml")
    p_arch.add_argument("--name", default=None, help="Modellname (Default: Dateiname)")
    p_arch.add_argument("--report", type=Path, default=None, help="Report als JSON")
    p_arch.add_argument(
        "--strict",
        action="store_true",
        help="mit Exit 1 enden, wenn Kanten nicht aufloesbar sind",
    )
    p_arch.set_defaults(func=cmd_archimate)

    p_arch_lesen = sub.add_parser(
        "archimate-read",
        help="ArchiMate 3.2 Model Exchange XML -> IR (.json)",
    )
    p_arch_lesen.add_argument(
        "--in", "-i", dest="quelle", required=True, type=Path, help="ArchiMate-XML"
    )
    p_arch_lesen.add_argument(
        "--out", "-o", dest="out", type=Path, default=None,
        help="Ziel-IR (.json; Default: Standardausgabe)",
    )
    p_arch_lesen.add_argument("--report", type=Path, default=None, help="Report als JSON")
    p_arch_lesen.add_argument(
        "--strict",
        action="store_true",
        help="Warnungen (etwa unbenannte Elemente) als Fehler behandeln",
    )
    p_arch_lesen.set_defaults(func=cmd_archimate_read)

    p_arch_pruefen = sub.add_parser(
        "archimate-check",
        help="ArchiMate-Modell lesen, zusammenfassen und pruefen "
        "(offene Referenzen, Matrixverstoesse, verwaiste Elemente)",
    )
    p_arch_pruefen.add_argument(
        "--in", "-i", dest="quelle", required=True, type=Path,
        help="Modell (.xml ArchiMate Model Exchange, .json IR oder .qea)",
    )
    p_arch_pruefen.add_argument(
        "--out", "-o", type=Path, default=None, help="Bericht in diese Datei schreiben"
    )
    p_arch_pruefen.add_argument(
        "--format", "-f", dest="format",
        choices=("text", "md", "json", "prompt"),
        default="text",
        help="Ausgabeformat: text (Standard), md, json oder prompt (fertiger Prompt)",
    )
    p_arch_pruefen.add_argument(
        "--frage", default="", help="Frage fuer --format prompt"
    )
    p_arch_pruefen.add_argument(
        "--limit", type=int, default=40,
        help="Meldungen im Bericht (Default: 40; 0 = alle)",
    )
    p_arch_pruefen.add_argument(
        "--strict", action="store_true",
        help="Warnungen zaehlen wie Fehler (Exit 1)",
    )
    p_arch_pruefen.set_defaults(func=cmd_archimate_check)

    # -- Stufenlauf --------------------------------------------------------
    p_st1 = sub.add_parser(
        "stufe1",
        help="MDG und Startpaket als Tabellen ablegen (offline, ohne KI)",
    )
    p_st1.add_argument("--mdg", required=True, type=Path, help="MDG-/Technologie-XML")
    p_st1.add_argument("--startpaket", type=Path, default=None, help="Startpaket (StEKa) als .qea")
    p_st1.add_argument("--text", type=Path, default=None, help="Quelltext fuer Stufe 2 merken")
    p_st1.add_argument("--bild", type=Path, action="append", default=[], help="Bild(er) fuer Stufe 2 merken")
    p_st1.add_argument("--workdir", required=True, type=Path, help="Arbeitsordner fuer alle Stufen")
    p_st1.add_argument("--projekt", default=DEFAULT_PACKAGE, help=f"Projektkuerzel (Default: {DEFAULT_PACKAGE})")
    p_st1.add_argument("--package", default=None, help="Zielpaket im Modell (Default: Projektkuerzel)")
    p_st1.add_argument("--quiet", action="store_true")
    p_st1.set_defaults(func=cmd_stufe1)

    p_st2 = sub.add_parser(
        "stufe2",
        help="Prosa in Chargen extrahieren, mit Pause und Fortsetzung",
    )
    p_st2.add_argument("--workdir", required=True, type=Path, help="Arbeitsordner aus Stufe 1")
    p_st2.add_argument("--text", type=Path, default=None, help="Quelle (Default: aus Stufe 1)")
    p_st2.add_argument("--bild", type=Path, action="append", default=[], help="Zusaetzliche Bild(er)")
    p_st2.add_argument("--backend", default=None, help="openai oder ollama (Default: openai)")
    p_st2.add_argument("--model", default=None, help="Modellname")
    p_st2.add_argument("--base-url", default=None, help="Basis-URL des Endpunkts")
    p_st2.add_argument("--timeout", type=float, default=120.0, help="HTTP-Zeitueberschreitung in s")
    p_st2.add_argument("--pause", type=float, default=120.0, help="Pause zwischen zwei Aufrufen in s (Default: 120)")
    p_st2.add_argument("--charge", type=int, default=extract_module.DEFAULT_BATCH_CHARS,
                       help=f"Quelltext je Charge in Zeichen (Default: {extract_module.DEFAULT_BATCH_CHARS})")
    p_st2.add_argument(
        "--kontext-tokens",
        type=int,
        default=None,
        metavar="N",
        help="Kontextfenster des Modells in Tokens (z. B. 4096, 8192, 16384)",
    )
    p_st2.add_argument("--quiet", action="store_true")
    p_st2.set_defaults(func=cmd_stufe2)

    p_st3 = sub.add_parser(
        "stufe3",
        help="aus der Elementtabelle die Architektur bauen (offline)",
    )
    p_st3.add_argument("--workdir", required=True, type=Path, help="Arbeitsordner aus Stufe 1/2")
    p_st3.add_argument("--out", "-o", required=True, type=Path, help="Zieldatei (.qea)")
    p_st3.add_argument("--startpaket", type=Path, default=None, help="Startpaket (Default: aus Stufe 1)")
    p_st3.add_argument("--katalog", type=Path, default=None, help="Modellelementekatalog (Default: aus Stufe 1)")
    p_st3.add_argument("--strict", action="store_true", help="Warnungen zaehlen wie Fehler")
    p_st3.add_argument("--no-quellen", action="store_true", help="keine quellen.json schreiben")
    p_st3.add_argument(
        "--ohne-struktur",
        action="store_true",
        help="Inhalt flach lassen (kein Leitfaden-Paketbaum)",
    )
    p_st3.add_argument(
        "--ohne-sichten",
        action="store_true",
        help="keine Diagramme anlegen (nur Pakete, Elemente, Beziehungen)",
    )
    p_st3.add_argument(
        "--sichten",
        choices=("aus", "mdg", "leitfaden", "wizard"),
        default="leitfaden",
        help="Sichten-Erstellung: aus, mdg, leitfaden (Standard) oder wizard",
    )
    p_st3.add_argument(
        "--wizard-dir",
        type=Path,
        default=None,
        help="Optionales Verzeichnis mit Model-Wizard-Vorlagen (.xml)",
    )
    p_st3.add_argument("--quiet", action="store_true")
    p_st3.set_defaults(func=cmd_stufe3)

    p_st4 = sub.add_parser(
        "stufe4",
        help="Leitfaden, EA-Geometrie und Integritaet pruefen (offline)",
    )
    p_st4.add_argument("--qea", type=Path, default=None, help="Zieldatei (Default: aus Stufe 3)")
    p_st4.add_argument("--workdir", type=Path, default=None, help="Arbeitsordner fuer den Standardpfad")
    p_st4.add_argument("--projekt", default="", help="Projektkuerzel fuer die Leitfadenpruefung")
    p_st4.add_argument("--mdg", type=Path, default=None, help="MDG-/Technologie-XML zur zusaetzlichen Pruefung")
    p_st4.add_argument("--rules", type=Path, default=None, help="Regelwerk-JSON zur zusaetzlichen Pruefung")
    p_st4.add_argument("--bericht", type=Path, default=None, help="Pruefbericht als JSON")
    p_st4.add_argument("--quiet", action="store_true")
    p_st4.set_defaults(func=cmd_stufe4)

    p_alle = sub.add_parser(
        "alle",
        help="Stufe 1 bis 4 in einem Lauf (Stufe 2 mit Pausen)",
    )
    p_alle.add_argument("--mdg", required=True, type=Path, help="MDG-/Technologie-XML")
    p_alle.add_argument("--text", required=True, type=Path, help="Quelltext")
    p_alle.add_argument(
        "--bild",
        type=Path,
        action="append",
        default=[],
        metavar="PFAD",
        help="Bild(er)",
    )
    p_alle.add_argument("--startpaket", type=Path, default=None, help="Startpaket (StEKa) als .qea")
    p_alle.add_argument("--out", "-o", required=True, type=Path, help="Zieldatei (.qea, .xmi, .xml oder .json)")
    p_alle.add_argument(
        "--format",
        dest="ziel_format",
        choices=("qea", "xmi", "archimate", "xml", "json"),
        default=None,
        help="Zielformat (Default: aus Endung von --out abgeleitet)",
    )
    p_alle.add_argument("--workdir", required=True, type=Path, help="Arbeitsordner fuer alle Stufen")
    p_alle.add_argument("--projekt", default=DEFAULT_PACKAGE, help=f"Projektkuerzel (Default: {DEFAULT_PACKAGE})")
    p_alle.add_argument("--package", default=None, help="Zielpaket im Modell")
    p_alle.add_argument("--backend", default="openai", help="openai oder ollama")
    p_alle.add_argument("--model", default=None)
    p_alle.add_argument("--base-url", default=None)
    p_alle.add_argument("--timeout", type=float, default=120.0)
    p_alle.add_argument("--pause", type=float, default=120.0)
    p_alle.add_argument("--charge", type=int, default=extract_module.DEFAULT_BATCH_CHARS)
    p_alle.add_argument(
        "--kontext-tokens",
        type=int,
        default=None,
        metavar="N",
        help="Kontextfenster des Modells in Tokens (z. B. 4096, 8192, 16384)",
    )
    p_alle.add_argument("--ohne-struktur", action="store_true", help="Inhalt flach lassen")
    p_alle.add_argument("--ohne-sichten", action="store_true", help="keine Diagramme anlegen")
    p_alle.add_argument(
        "--sichten",
        choices=("aus", "mdg", "leitfaden", "wizard"),
        default="leitfaden",
        help="Sichten-Erstellung: aus, mdg, leitfaden (Standard) oder wizard",
    )
    p_alle.add_argument(
        "--wizard-dir",
        type=Path,
        default=None,
        help="Optionales Verzeichnis mit Model-Wizard-Vorlagen (.xml)",
    )
    p_alle.add_argument("--bericht", type=Path, default=None, help="Pruefbericht als JSON")
    p_alle.add_argument("--quiet", action="store_true")
    p_alle.set_defaults(func=cmd_alle)

    p_convert = sub.add_parser(
        "convert",
        help="Modelle zwischen allen 4 Formaten konvertieren (.qea, .xmi, ArchiMate .xml, .json)",
    )
    p_convert.add_argument("--in", "-i", dest="eingabe", required=True, type=Path, help="Quelldatei (.qea, .xmi, .xml, .json)")
    p_convert.add_argument("--out", "-o", dest="ausgabe", required=True, type=Path, help="Zieldatei (.qea, .xmi, .xml, .json)")
    p_convert.add_argument(
        "--format",
        "-f",
        dest="ziel_format",
        choices=("qea", "xmi", "archimate", "xml", "json"),
        default=None,
        help="Zielformat (Default: aus Endung abgeleitet)",
    )
    p_convert.add_argument(
        "--from",
        dest="quell_format",
        choices=("qea", "xmi", "archimate", "xml", "json"),
        default=None,
        help="Quellformat explizit",
    )
    p_convert.add_argument("--source-document", default="", help="Quellbeleg fuer Metadaten")
    p_convert.set_defaults(func=cmd_convert)

    p_validate = sub.add_parser(
        "validate",
        help="Modell (.qea, .xmi, .xml, .json) gegen Technologie (MDG-XML oder rules.json) validieren",
    )
    p_validate.add_argument("ir", nargs="?", type=Path, default=None, help="Modell-Datei (.qea, .xmi, .xml, .json)")
    p_validate.add_argument("rules", nargs="?", type=Path, default=None, help="Regelwerk (rules.json oder mdg.xml)")
    p_validate.add_argument("--in", "-i", dest="model_in", type=Path, help="Modell-Datei explizit")
    p_validate.add_argument("--mdg", type=Path, help="MDG-Technologie XML")
    p_validate.add_argument("--rules-file", "--rules", dest="rules_opt", type=Path, help="Regelwerk JSON oder XML")
    p_validate.add_argument(
        "-o",
        "--out",
        type=Path,
        help="findings.json schreiben (ohne Angabe: JSON nach stdout)",
    )
    p_validate.add_argument(
        "--requirements",
        type=Path,
        help="Pflichtbeziehungen als JSON-Liste (Projektkonvention)",
    )
    p_validate.add_argument(
        "--strict",
        action="store_true",
        help="Warnungen zaehlen wie Fehler (Exit 1)",
    )
    p_validate.add_argument("-q", "--quiet", action="store_true", help="keine Zusammenfassung auf stderr")
    p_validate.set_defaults(func=cmd_validate)

    p_handbuch = sub.add_parser(
        "handbuch",
        help="Betriebshandbuch als Markdown aus einem Modell generieren (.qea, .xmi, .xml, .json)",
    )
    p_handbuch.add_argument("--in", "-i", dest="modell", required=True, type=Path, help="Modell-Datei")
    p_handbuch.add_argument("--out", "-o", dest="ausgabe", required=True, type=Path, help="Zieldatei (Markdown .md)")
    p_handbuch.set_defaults(func=cmd_handbuch)

    p_eacheck = sub.add_parser(
        "ea-check",
        help="EA-Oeffnung, Geometrie und Integritaet pruefen (.qea)",
    )
    p_eacheck.add_argument("qea", type=Path, help="Zu pruefende .qea-Datei")
    p_eacheck.add_argument("--bereich", choices=("tabelle", "abfrage", "geometrie", "integritaet", "alle"), default="alle")
    p_eacheck.set_defaults(func=cmd_ea_check)

    p_graph = sub.add_parser(
        "graph",
        help="Graph-Analyse: Umfeld, Pfade, Zusammenhang und Kantenpruefung",
    )
    p_graph.add_argument("--in", "-i", dest="modell", required=True, type=Path, help="Modell-Datei (.qea, .xmi, .xml, .json)")
    p_graph.add_argument("--umfeld", help="Umfeld/Impact fuer einen Elementnamen oder eine Kennung")
    p_graph.add_argument("--von", help="Startknoten fuer Pfadsuche")
    p_graph.add_argument("--nach", help="Zielknoten fuer Pfadsuche")
    p_graph.add_argument("--tiefe", type=int, default=1, help="Tiefe fuer Umfeldsuche (Default: 1)")
    p_graph.add_argument("--befunde", action="store_true", help="Kantenbefunde ausgeben")
    p_graph.add_argument("--stats", action="store_true", help="Graph-Statistik ausgeben")
    p_graph.add_argument("-o", "--out", type=Path, help="Ergebnis als JSON schreiben")
    p_graph.set_defaults(func=cmd_graph)

    p_qs = sub.add_parser(
        "qs",
        help="Gesamte Qualitaetssicherung: MDG, Leitfaden, Geometrie, Waisen, Kanten, NATO-GUIDs",
    )
    p_qs.add_argument("--in", "-i", dest="modell", required=True, type=Path, help="Modell-Datei")
    p_qs.add_argument("--mdg", type=Path, help="MDG-Technologie XML oder rules.json")
    p_qs.add_argument("--projekt", default="", help="Projektkuerzel")
    p_qs.add_argument("--text", type=Path, default=None, help="Optionaler Quelltext fuer Textabdeckungs-Pruefung")
    p_qs.add_argument("-o", "--out", type=Path, help="QS-Bericht als JSON schreiben")
    p_qs.add_argument("--strict", action="store_true", help="Warnungen als Fehler werten (Exit 1)")
    p_qs.set_defaults(func=cmd_qs)

    p_diff = sub.add_parser(
        "diff",
        help="Architektur-Standsvergleich ueber alle 4 Formate (.qea, .xmi, .xml, .json)",
    )
    p_diff.add_argument("--alt", required=True, type=Path, help="Altes/Referenz-Modell")
    p_diff.add_argument("--neu", required=True, type=Path, help="Neues/Geaendertes Modell")
    p_diff.add_argument("--mdg", type=Path, default=None, help="Optionale MDG-XML oder rules.json fuer Befund-Delta")
    p_diff.add_argument("--format", "-f", choices=("text", "md", "json"), default="md")
    p_diff.add_argument("--out", "-o", type=Path, default=None, help="Bericht in Datei schreiben")
    p_diff.add_argument("--fail-on-changes", action="store_true", help="Exit 1 bei Abweichungen")
    p_diff.set_defaults(func=cmd_diff)

    p_repair = sub.add_parser(
        "repair",
        help="Regelbasierte MDG-Reparatur mit Vorschau (und mit --apply schreiben)",
    )
    p_repair.add_argument("--in", "-i", dest="modell", required=True, type=Path, help="Eingabemodell (.qea, .xmi, .xml, .json)")
    p_repair.add_argument("--mdg", type=Path, default=None, help="MDG-XML oder rules.json")
    p_repair.add_argument("--out", "-o", type=Path, default=None, help="Zielmodell (nur mit --apply)")
    p_repair.add_argument("--apply", action="store_true", help="Reparatur schreiben (sonst nur Vorschau)")
    p_repair.add_argument("--max-runden", type=int, default=6, help="Maximale Reparaturrunden (Default: 6)")
    p_repair.add_argument("--json", action="store_true", help="Vorschau/Ergebnis als JSON ausgeben")
    p_repair.set_defaults(func=cmd_repair)

    p_sa = sub.add_parser(
        "sichten-archiv",
        help="Sichten-Archiv: Diagramme und Layout aus .qea auslagern und verlustfrei zurueckspielen",
    )
    sa_sub = p_sa.add_subparsers(dest="aktion", required=True)

    sa_pack = sa_sub.add_parser("archivieren", aliases=["pack"], help="Sichtdaten sichern und aus einer Kopie entfernen")
    sa_pack.add_argument("quelle", type=Path, help="Quelldatei (.qea)")
    sa_pack.add_argument("archiv", type=Path, help="Zieldatei des Archivs (.archiv)")
    sa_pack.add_argument("--ziel", type=Path, default=None, help="Optionale Kopie ohne Sichtdaten")
    sa_pack.add_argument("--stufe", choices=("A", "B"), default="A", help="Stufe A (Diagramme) oder B (+Tags/Xref)")

    sa_unpack = sa_sub.add_parser("zurueckspielen", aliases=["unpack"], help="Sichtdaten aus dem Archiv wieder einsetzen")
    sa_unpack.add_argument("modell", type=Path, help="Modell ohne Sichten (.qea)")
    sa_unpack.add_argument("archiv", type=Path, help="Archivdatei (.archiv)")
    sa_unpack.add_argument("ziel", type=Path, help="Zieldatei mit wiederhergestellten Sichten (.qea)")
    sa_unpack.add_argument("--erzwingen", action="store_true", help="Bestehende Sichtdaten ueberschreiben")

    sa_pruef = sa_sub.add_parser("pruefen", aliases=["verify"], help="Archiv pruefen")
    sa_pruef.add_argument("archiv", type=Path, help="Archivdatei (.archiv)")

    p_sa.set_defaults(func=cmd_sichten_archiv)

    p_mcp = sub.add_parser(
        "mcp",
        help="Abhaengigkeitsfreier 4-Format-MCP-Server ueber stdio (JSON-RPC 2.0)",
    )
    p_mcp.add_argument(
        "--list-tools",
        action="store_true",
        help="Verfuegbare MCP-Werkzeuge als JSON ausgeben und beenden",
    )
    p_mcp.set_defaults(func=cmd_mcp)
    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    import validator

    model_path = args.model_in or args.ir
    rules_path = args.mdg or args.rules_opt or args.rules
    if not model_path:
        print("FEHLER: Eingabemodell fehlt (--in oder 1. Argument)", file=sys.stderr)
        return 3
    if not rules_path:
        print("FEHLER: Regelwerk fehlt (--mdg/--rules oder 2. Argument)", file=sys.stderr)
        return 3

    try:
        ir = validator.load_ir(model_path)
        ruleset = validator.load_rules(rules_path)
        if args.requirements:
            reqs = validator.load_requirements(args.requirements)
            parsed_reqs = validator._read_requirements(
                reqs, elements=ruleset.elements, connectors=ruleset.connectors
            )
            ruleset = validator.RuleSet(
                name=ruleset.name,
                elements=ruleset.elements,
                connectors=ruleset.connectors,
                requirements=ruleset.requirements + parsed_reqs,
                closures=ruleset.closures,
                tagged_value_types=ruleset.tagged_value_types,
            )
        findings = validator.validate_model(ir, ruleset)
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    summary = validator.summarize_findings(findings)
    text = json.dumps(findings, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    if not args.quiet:
        sys.stderr.write(
            f"Befunde: {summary['total']} gesamt ({summary['error']} Fehler, {summary['warning']} Warnungen)\n"
        )

    if summary["error"] > 0:
        return 1
    if args.strict and summary["warning"] > 0:
        return 1
    return 0


def cmd_handbuch(args: argparse.Namespace) -> int:
    import handbuch_generator

    try:
        kennzahlen = handbuch_generator.generate_handbook(args.modell, args.ausgabe)
        print(
            f"Handbuch generiert: {args.ausgabe} ({kennzahlen['kapitel']} Kapitel, "
            f"{kennzahlen['absaetze']} Absaetze, {kennzahlen['zeichen']} Zeichen, "
            f"{kennzahlen['dienste']} Dienste)"
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER Handbuch: {exc}", file=sys.stderr)
        return 1


def cmd_ea_check(args: argparse.Namespace) -> int:
    import ea_check

    pfad = Path(args.qea)
    if not pfad.is_file():
        print(f"FEHLER: Datei nicht gefunden: {pfad}", file=sys.stderr)
        return 1

    bereiche = (
        ("tabelle", "abfrage")
        if args.bereich in ("tabelle", "abfrage", "alle")
        else ()
    )
    befunde = []
    if bereiche:
        befunde.extend(ea_check.pruefe_datei(pfad, bereiche=bereiche))

    con = sqlite3.connect(str(pfad))
    con.execute("PRAGMA query_only = ON")
    try:
        if args.bereich in ("geometrie", "alle"):
            befunde.extend(ea_check.pruefe_geometrie(con))
        if args.bereich in ("integritaet", "alle"):
            befunde.extend(ea_check.pruefe_integritaet(con))
    finally:
        con.close()

    fehler = [b for b in befunde if b.severity == "FEHLER"]
    warnungen = [b for b in befunde if b.severity != "FEHLER"]
    for b in befunde:
        print(f"[{b.severity}] {b.bereich}: {b.meldung}")

    print(f"EA-Check: {len(fehler)} Fehler, {len(warnungen)} Warnungen")
    return 1 if fehler else 0


def cmd_graph(args: argparse.Namespace) -> int:
    import tempfile
    import graph

    with tempfile.NamedTemporaryFile(suffix=".db", prefix="eam-graph-", delete=False) as handle:
        tmp_db = Path(handle.name)

    try:
        ladebericht = graph.lade(args.modell, tmp_db, ersetzen=True)
        con = graph.oeffne(tmp_db)
        try:
            ergebnis: dict[str, Any] = {"modell": str(args.modell), "knoten": ladebericht.knoten, "kanten": ladebericht.kanten}
            if args.stats:
                st = graph.statistik(con)
                ergebnis["statistik"] = st
                print(f"Graph: {st['knoten']} Knoten, {st['kanten']} Kanten ({st['elemente']} Elemente, {st['pakete']} Pakete)")

            if args.befunde:
                bf = [dict(b) for b in graph.befunde(con)]
                ergebnis["befunde"] = bf
                print(f"Graph-Kantenbefunde: {len(bf)}")
                for b in bf[:10]:
                    print(f"  [{b.get('schwere')}] {b.get('regel')}: {b.get('meldung')}")

            if args.umfeld:
                start = graph._ein_knoten(con, args.umfeld)
                um = [dict(z) for z in graph.umfeld(con, start["kennung"], tiefe=args.tiefe)]
                ergebnis["start"] = dict(start)
                ergebnis["umfeld"] = um
                print(f"Umfeld fuer '{start.get('name')}' (Tiefe {args.tiefe}): {len(um)} Nachbarn")
                for u in um[:15]:
                    print(f"  {u.get('distanz')}. Schritt: {u.get('rel_typ')} -> {u.get('name')} ({u.get('stereotyp') or u.get('typ')})")

            if args.von and args.nach:
                pfad_res = graph.pfad(con, args.von, args.nach)
                ergebnis["pfad"] = pfad_res
                if pfad_res:
                    print(f"Pfad von '{args.von}' nach '{args.nach}' (Tiefe {pfad_res['tiefe']}):")
                    for k in pfad_res.get("knoten", []):
                        print(f"  -> {k.get('name')} ({k.get('stereotyp') or k.get('typ')})")
                else:
                    print(f"Kein Pfad zwischen '{args.von}' und '{args.nach}' gefunden.")

            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(ergebnis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        finally:
            con.close()
    finally:
        tmp_db.unlink(missing_ok=True)
    return 0


def cmd_qs(args: argparse.Namespace) -> int:
    import tempfile
    import validator
    import struktur
    import ea_check
    import model_io
    import graph

    model_path = Path(args.modell)
    if not model_path.is_file():
        print(f"FEHLER: Modell nicht gefunden: {model_path}", file=sys.stderr)
        return 1

    ir = validator.load_ir(model_path)
    projekt = args.projekt or model_path.stem

    findings: list[dict[str, Any]] = []

    rules_path = args.mdg
    if not rules_path:
        here = Path(__file__).resolve().parent
        for cand in (
            here / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml",
            here.parent / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml",
            here / "knowledge" / "regelwerk.json",
            here.parent / "knowledge" / "regelwerk.json",
            here.parent.parent / "knowledge" / "regelwerk.json",
        ):
            if cand.is_file():
                rules_path = cand
                break

    if rules_path and Path(rules_path).is_file():
        ruleset = validator.load_rules(rules_path)
        mdg_f = validator.validate_model(ir, ruleset)
        findings.extend(mdg_f)

    conns = ir.get("connectors") or []
    connected_refs = set()
    for c in conns:
        if c.get("source"): connected_refs.add(c["source"])
        if c.get("target"): connected_refs.add(c["target"])
        if c.get("source_guid"): connected_refs.add(c["source_guid"])
        if c.get("target_guid"): connected_refs.add(c["target_guid"])

    elements = ir.get("elements") or []
    waisen = []
    quellbelege_fehlen = []
    for el in elements:
        name = el.get("name") or el.get("guid") or ""
        ref = el.get("ref") or el.get("guid") or name
        tags = el.get("tags") or {}
        if ref not in connected_refs and name not in connected_refs:
            waisen.append(name)
            findings.append({
                "severity": "warning",
                "object_label": name,
                "rule": "qs:waise",
                "check": "isolatedElement",
                "message": f"Element '{name}': isolierter Knoten ohne Beziehungen (Waise).",
            })
        if not tags.get("source_ref") and not tags.get("source_doc") and not el.get("source_ref"):
            quellbelege_fehlen.append(name)

    ea_stats = {}
    temp_qea = None
    if model_path.suffix.lower() != ".qea":
        with tempfile.NamedTemporaryFile(suffix=".qea", prefix="eam-qs-", delete=False) as handle:
            temp_qea = Path(handle.name)
        model_io.convert_model(model_path, temp_qea, out_format="qea")
        pruef_qea = temp_qea
    else:
        pruef_qea = model_path

    try:
        modell_obj = struktur.from_qea(pruef_qea)
        lf_befunde = struktur.validate(modell_obj, projekt)
        for lf in lf_befunde:
            findings.append({
                "severity": lf.severity.lower() if lf.severity.lower() in ("error", "warning") else ("warning" if lf.severity == "WARNUNG" else "info"),
                "object_label": lf.object or "",
                "rule": lf.code,
                "check": lf.check or "leitfadenCheck",
                "message": lf.message,
            })

        con = sqlite3.connect(str(pruef_qea))
        con.execute("PRAGMA query_only = ON")
        try:
            geom = ea_check.pruefe_geometrie(con)
            integ = ea_check.pruefe_integritaet(con)
            for b in [*geom, *integ]:
                findings.append({
                    "severity": "error" if b.severity == "FEHLER" else "warning",
                    "object_label": b.bereich,
                    "rule": "ea:integrity",
                    "check": b.bereich,
                    "message": b.meldung,
                })
            ea_stats = {
                "pakete": con.execute("SELECT COUNT(*) FROM t_package").fetchone()[0],
                "elemente": con.execute("SELECT COUNT(*) FROM t_object").fetchone()[0],
                "beziehungen": con.execute("SELECT COUNT(*) FROM t_connector").fetchone()[0],
                "sichten": con.execute("SELECT COUNT(*) FROM t_diagram").fetchone()[0],
            }
        finally:
            con.close()
    finally:
        if temp_qea:
            temp_qea.unlink(missing_ok=True)

    summary = {
        "total": len(findings),
        "error": sum(1 for f in findings if f.get("severity") in ("error", "FEHLER")),
        "warning": sum(1 for f in findings if f.get("severity") in ("warning", "WARNUNG")),
        "waisen": len(waisen),
        "quellbelege_fehlen": len(quellbelege_fehlen),
        "elemente": len(elements),
        "beziehungen": len(conns),
    }

    import text_coverage
    cov = text_coverage.evaluate_coverage(
        ir,
        text_source=getattr(args, "text", None),
        model_path=model_path,
    )
    if cov is not None:
        summary["text_coverage_pct"] = cov.coverage_pct
        summary["uncovered_segments"] = cov.uncovered_segments

    report = {
        "modell": str(model_path),
        "ok": summary["error"] == 0 and (not args.strict or summary["warning"] == 0),
        "summary": summary,
        "waisen": waisen,
        "ea": ea_stats,
        "findings": findings,
    }
    if cov is not None:
        report["coverage"] = cov.as_dict()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cov_suffix = (
        f", Textabdeckung {cov.coverage_pct}% ({cov.covered_segments}/{cov.content_segments} Absaetze)"
        if cov is not None
        else ""
    )
    print(
        f"QS-Ergebnis: {'OK' if report['ok'] else 'NICHT OK'} -- "
        f"{summary['elemente']} Elemente, {summary['beziehungen']} Beziehungen; "
        f"{summary['error']} Fehler, {summary['warning']} Warnungen ({summary['waisen']} Waisen, "
        f"{summary['quellbelege_fehlen']} ohne Quellbeleg{cov_suffix})"
    )

    if summary["error"] > 0 or (args.strict and summary["warning"] > 0):
        return 1
    return 0


def cmd_sichten_archiv(args: argparse.Namespace) -> int:
    import sichten_archiv
    aktion = args.aktion
    if aktion in ("archivieren", "pack"):
        res = sichten_archiv.archiviere(args.quelle, args.archiv, ziel=args.ziel, stufe=args.stufe)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    elif aktion in ("zurueckspielen", "unpack"):
        res = sichten_archiv.zurueckspielen(args.modell, args.archiv, args.ziel, erzwingen=args.erzwingen)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("identisch") else 1
    elif aktion in ("pruefen", "verify"):
        res = sichten_archiv.pruefe(args.archiv)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    else:
        print(f"Unbekannte Aktion: {aktion}", file=sys.stderr)
        return 1


def cmd_convert(args: argparse.Namespace) -> int:
    import model_io

    try:
        ziel = model_io.convert_model(
            args.eingabe,
            args.ausgabe,
            in_format=args.quell_format,
            out_format=args.ziel_format,
            source_document=args.source_document or args.eingabe.name,
        )
        print(f"Konvertiert: {args.eingabe} -> {ziel} ({ziel.stat().st_size} Bytes)")
        return 0
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


def cmd_build(args: argparse.Namespace) -> int:
    def say(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    # EXTRACT_BACKEND nur lesen, wenn tatsaechlich eine Quelle extrahiert wird.
    # Ohne Quelle bleibt das Backend leer -- dann ist der Lauf ein Geruest.
    backend_kind = args.backend
    text_val = args.text if (args.text and (isinstance(args.text, (str, Path)) or len(args.text) > 0)) else None
    if backend_kind is None and (text_val is not None or args.bild):
        backend_kind = os.environ.get("EXTRACT_BACKEND") or None

    sichten_choice = getattr(args, "sichten", "leitfaden")
    if getattr(args, "ohne_sichten", False):
        sichten_choice = "aus"
    mit_sichten = (sichten_choice != "aus")

    try:
        report = build(
            mdg=args.mdg,
            text=text_val,
            images=args.bild,
            out=args.out,
            package=args.package,
            backend_kind=backend_kind,
            model=args.model,
            base_url=args.base_url,
            answer_file=args.antwort,
            timeout=args.timeout,
            schema_path=args.schema,
            findings_path=args.findings,
            dry_run=args.dry_run,
            strict=args.strict,
            repair=args.repair,
            repair_rounds=args.repair_runden,
            repair_bericht=args.repair_bericht,
            repair_ir_path=args.repair_ir,
            struktur=not getattr(args, "ohne_struktur", False),
            mit_sichten=mit_sichten,
            sichten_modus=sichten_choice,
            wizard_dir=getattr(args, "wizard_dir", None),
            batch_chars=args.chargen_zeichen,
            batch_threshold=args.chargen_schwelle,
            context_tokens=getattr(args, "kontext_tokens", None),
            skeleton=getattr(args, "geruest", None),
            ziel_format=getattr(args, "ziel_format", "qea"),
            startpaket=args.startpaket,
            katalog=args.katalog,
            modell=args.modell,
            sidecar=not args.no_quellen,
            quellen_path=args.quellen,
            log=say,
        )
    except BuildError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    counts = report.summary
    print(report.result_line())
    if report.blocked:
        print(
            f"FEHLER: {counts['error']} Fehler"
            + (f", {counts['warning']} Warnungen (--strict)" if report.strict and counts["warning"] else "")
            + f"; keine .qea geschrieben. Findings: {report.findings_path}",
            file=sys.stderr,
        )
        return 1
    return 0


def _stufen_modul():
    import stufen as stufen_module  # lokal: kein Zyklus beim Import des CLI

    return stufen_module


def _stufen_say(args: argparse.Namespace):
    def say(message: str) -> None:
        if not getattr(args, "quiet", False):
            print(message, file=sys.stderr, flush=True)

    return say


def cmd_stufe1(args: argparse.Namespace) -> int:
    try:
        ergebnis = _stufen_modul().stufe1(
            mdg=args.mdg,
            startpaket=args.startpaket,
            text=args.text,
            images=getattr(args, "bild", ()),
            workdir=args.workdir,
            projekt=args.projekt,
            package=args.package,
        )
    except Exception as exc:  # noqa: BLE001 -- Meldung reicht dem Nutzer
        print(f"FEHLER Stufe 1: {exc}", file=sys.stderr)
        return 1
    print(
        f"Stufe 1: {ergebnis['viewpoints']} Viewpoints, {ergebnis['elemente']} Element-Typen, "
        f"{ergebnis['beziehungen']} Beziehungs-Typen, {ergebnis['startelemente']} Startelemente"
    )
    print(f"  Regelwerk: {ergebnis['regelwerk']}")
    if ergebnis["startpaket"]:
        print(f"  Startpaket: {ergebnis['startpaket']}")
    if ergebnis.get("startpaket_hinweis"):
        print(f"  Hinweis: {ergebnis['startpaket_hinweis']}", file=sys.stderr)
    return 0


def cmd_stufe2(args: argparse.Namespace) -> int:
    backend_kind = args.backend or os.environ.get("EXTRACT_BACKEND") or "openai"
    try:
        ergebnis = _stufen_modul().stufe2(
            workdir=args.workdir,
            text=args.text,
            images=getattr(args, "bild", ()),
            backend_kind=backend_kind,
            model=args.model,
            base_url=args.base_url,
            timeout=args.timeout,
            pause=args.pause,
            charge=args.charge,
            context_tokens=getattr(args, "kontext_tokens", None),
            log=_stufen_say(args),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER Stufe 2: {exc}", file=sys.stderr)
        print(
            "Hinweis: bereits abgeschlossene Chargen bleiben erhalten; "
            "derselbe Aufruf setzt an der ersten fehlenden Charge fort.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Stufe 2: {ergebnis['chargen']} Charge(n), {ergebnis['elemente']} Element(e), "
        f"{ergebnis['beziehungen']} Beziehung(en), {ergebnis['aufrufe']} Aufruf(e) in diesem Lauf"
    )
    print(f"  Antwort: {ergebnis['antwort']}")
    return 0


def cmd_stufe3(args: argparse.Namespace) -> int:
    sichten_choice = getattr(args, "sichten", "leitfaden")
    if getattr(args, "ohne_sichten", False):
        sichten_choice = "aus"
    mit_sichten = (sichten_choice != "aus")

    try:
        report = _stufen_modul().stufe3(
            workdir=args.workdir,
            out=args.out,
            startpaket=args.startpaket,
            katalog=args.katalog,
            strict=args.strict,
            sidecar=not args.no_quellen,
            struktur=not getattr(args, "ohne_struktur", False),
            mit_sichten=mit_sichten,
            sichten_modus=sichten_choice,
            wizard_dir=getattr(args, "wizard_dir", None),
            log=_stufen_say(args),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER Stufe 3: {exc}", file=sys.stderr)
        return 1
    print(report.result_line())
    return 1 if report.blocked else 0


def _stufen_state(workdir: Path) -> dict:
    import json

    pfad = Path(workdir) / "state.json"
    if not pfad.is_file():
        return {}
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def cmd_stufe4(args: argparse.Namespace) -> int:
    qea = args.qea
    projekt = args.projekt
    if qea is None:
        if args.workdir is None:
            print("FEHLER Stufe 4: --qea oder --workdir angeben", file=sys.stderr)
            return 1
        state = _stufen_state(args.workdir)
        qea = Path(str(state.get("out") or "")) if state.get("out") else None
        projekt = projekt or str(state.get("projekt") or "")
    if qea is None:
        print("FEHLER Stufe 4: keine .qea gesetzt", file=sys.stderr)
        return 1
    try:
        bericht = _stufen_modul().stufe4(
            qea=qea,
            projekt=projekt,
            mdg=getattr(args, "mdg", None),
            rules=getattr(args, "rules", None),
            bericht=args.bericht,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER Stufe 4: {exc}", file=sys.stderr)
        return 1
    z = bericht["zahlen"]
    lf = bericht["leitfaden"]
    print(
        f"Stufe 4: {'OK' if bericht['ok'] else 'NICHT OK'} -- "
        f"{z['pakete']} Pakete, {z['elemente']} Elemente, {z['beziehungen']} Beziehungen, "
        f"{z['sichten']} Sichten"
    )
    print(
        f"  Leitfaden: {lf['error']} Fehler, {lf['warning']} Warnungen, {lf['info']} Hinweise; "
        f"Geometrie: {bericht['geometrie']['fehler']}; "
        f"Integritaet: {bericht['ea']['integritaet_fehler']}; "
        f"EA-Oeffnung: {bericht['ea']['oeffnung_fehler']} fehlende Tabellen/Abfragen"
    )
    if args.bericht:
        print(f"  Bericht: {args.bericht}")
    return 0 if bericht["ok"] else 1


def cmd_alle(args: argparse.Namespace) -> int:
    stufen = _stufen_modul()
    say = _stufen_say(args)
    try:
        say("[1/4] Regelwerk und Startpaket")
        stufen.stufe1(
            mdg=args.mdg,
            startpaket=args.startpaket,
            text=args.text,
            images=getattr(args, "bild", ()),
            workdir=args.workdir,
            projekt=args.projekt,
            package=args.package,
        )
        say("[2/4] Elemente und Beziehungen")
        stufen.stufe2(
            workdir=args.workdir,
            text=args.text,
            images=getattr(args, "bild", ()),
            backend_kind=args.backend,
            model=args.model,
            base_url=args.base_url,
            timeout=args.timeout,
            pause=args.pause,
            charge=args.charge,
            context_tokens=getattr(args, "kontext_tokens", None),
            log=say,
        )
        say("[3/4] Architektur bauen")
        sichten_choice = getattr(args, "sichten", "leitfaden")
        if getattr(args, "ohne_sichten", False):
            sichten_choice = "aus"
        mit_sichten = (sichten_choice != "aus")

        report = stufen.stufe3(
            workdir=args.workdir,
            out=args.out,
            sidecar=True,
            struktur=not getattr(args, "ohne_struktur", False),
            mit_sichten=mit_sichten,
            sichten_modus=sichten_choice,
            wizard_dir=getattr(args, "wizard_dir", None),
            log=say,
        )
        if report.blocked:
            print(report.result_line())
            print("FEHLER: Modell blockiert; Stufe 4 uebersprungen", file=sys.stderr)
            return 1
        say("[4/4] Pruefung")
        bericht = stufen.stufe4(
            qea=args.out,
            projekt=args.projekt,
            mdg=args.mdg,
            bericht=args.bericht,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER: {exc}", file=sys.stderr)
        print(
            "Hinweis: abgeschlossene Chargen bleiben erhalten; "
            "derselbe Aufruf setzt fort.",
            file=sys.stderr,
        )
        return 1
    z = bericht["zahlen"]
    print(
        f"Fertig: {z['pakete']} Pakete, {z['elemente']} Elemente, {z['beziehungen']} Beziehungen, "
        f"{z['sichten']} Sichten; {'OK' if bericht['ok'] else 'PRUEFUNG ROT'}"
    )
    return 0 if bericht["ok"] else 1


def cmd_frage(args: argparse.Namespace) -> int:
    """Frage zu einer .qea. Ohne --backend bleibt der Lauf offline (ohne KI)."""
    import qea_chat  # lokal: der Bau-Pfad importiert den Frage-Weg nicht

    scope: dict[str, str] | None = None
    if args.paket:
        scope = {"package": args.paket}
    elif args.element:
        scope = {"element": args.element}

    backend = None
    if args.backend:
        try:
            backend = extract_module.make_backend(
                args.backend,
                model=args.model,
                base_url=args.base_url,
                timeout=args.timeout,
            )
        except ExtractionError as exc:
            print(f"FEHLER: Backend: {exc}", file=sys.stderr)
            return 1
        # Eine Frage wird in Prosa beantwortet, nicht als JSON-Objekt. Der
        # Extraktionspfad erzwingt JSON; hier wird das ausdruecklich abgeschaltet.
        if (
            isinstance(backend, extract_module.OpenAICompatibleBackend)
            and backend.json_mode
        ):
            backend = replace(backend, json_mode=False)

    try:
        answer = qea_chat.ask_qea(args.qea, args.frage, backend=backend, scope=scope)
    except qea_chat.QeaChatError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(answer.text)
    if args.out is not None:
        try:
            target = qea_chat.export_answer(answer, args.out)
        except qea_chat.QeaChatError as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 1
        print(f"Antwort: {target}", file=sys.stderr)
    return 0


def cmd_korrigiere(args: argparse.Namespace) -> int:
    """Korrektur in natuerlicher Sprache: erst Vorschlag, dann auf Wunsch schreiben."""
    import model_edit
    import nl_edit  # lokal: der Bau-Pfad braucht den Korrektur-Weg nicht

    if args.anweisung_datei is not None:
        try:
            instruction = args.anweisung_datei.read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"FEHLER: {args.anweisung_datei}: nicht lesbar ({exc})", file=sys.stderr)
            return 1
    else:
        instruction = args.anweisung or ""

    backend = None
    if args.backend:
        try:
            backend = extract_module.make_backend(
                args.backend,
                model=args.model,
                base_url=args.base_url,
                answer_file=args.antwort,
                timeout=args.timeout,
            )
        except ExtractionError as exc:
            print(f"FEHLER: Backend: {exc}", file=sys.stderr)
            return 1

    try:
        proposal = nl_edit.propose(args.qea, instruction, backend=backend)
    except nl_edit.NlEditError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(proposal.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Vorschlag ({proposal.backend}, {len(proposal.ops)} Operation(en)):")
        if proposal.reply:
            print(f"  {proposal.reply}")
        for line in nl_edit.preview_lines(proposal):
            print(f"  {line}")
        for warning in proposal.warnings:
            print(f"  HINWEIS: {warning}")
        if proposal.destructive:
            print("  ACHTUNG: Loeschoperation enthalten.")

    if not args.apply:
        print(
            "Vorschau — nichts geschrieben. Mit --out ZIEL.qea --apply "
            + ("--ja " if proposal.destructive else "")
            + "ausfuehren.",
            file=sys.stderr,
        )
        return 0

    if args.out is None:
        print("FEHLER: --apply verlangt --out", file=sys.stderr)
        return 1
    try:
        result = nl_edit.apply(
            proposal, args.out, mdg=args.mdg, confirm=bool(args.ja)
        )
    except (nl_edit.NlEditError, model_edit.EditError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if not args.json:
        print(
            f"{result.written}: {result.applied} von {result.ops} Operation(en) angewendet"
            + (f", MDG: {result.mdg}" if result.mdg else "")
        )
        for change in result.changes:
            print(f"  - {change}")
        for warning in result.warnings:
            print(f"  HINWEIS: {warning}")
        for rejection in result.rejected:
            print(
                "  ABGELEHNT: " + str(rejection.get("op")) + ": " + str(rejection.get("grund")),
                file=sys.stderr,
            )
    return 0 if not result.rejected else 1


def cmd_serve(args: argparse.Namespace) -> int:
    """Weboberflaeche starten. Grenzen kommen aus den CLI-Optionen."""
    import webui  # lokal: der Regelpfad und ``build`` importieren keine Netzmodule

    try:
        server = webui.make_server(
            host=args.host,
            port=args.port,
            max_upload=max(1, args.max_upload_mb) * 1024 * 1024,
            max_seconds=args.max_seconds,
            max_jobs=args.jobs,
            job_ttl=args.job_ttl,
            workdir=args.workdir,
            assets=args.assets,
            version=__version__,
        )
    except webui.WebError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[0], server.server_address[1]
    print(f"eam-ai {__version__}: http://{host}:{port}/", file=sys.stderr, flush=True)
    print(
        f"Grenzen: {args.max_upload_mb} MB Upload, {args.max_seconds:g} s je Lauf, "
        f"{args.jobs} Laeufe parallel, Ergebnisse {args.job_ttl:g} s",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:  # pragma: no cover - Bedienung
        print("Beendet.", file=sys.stderr)
    finally:
        server.stop()
    return 0


#: Platzhalter im leeren Startmodell; wird nach dem Katalog-Merge entfernt.
_PLATZHALTER = "{00000000-0000-4000-8000-00000000AAAA}"


def _drop_element(path: Path, guid: str) -> None:
    """Entfernt ein einzelnes Element samt Anhang; nur fuer den Platzhalter gedacht."""
    import sqlite3

    con = sqlite3.connect(str(path))
    try:
        con.execute("delete from t_object where ea_guid = ?", (guid,))
        con.execute("delete from t_objectproperties where Object_ID not in (select Object_ID from t_object)")
        con.execute("delete from t_xref where Client = ?", (guid,))
        con.commit()
    finally:
        con.close()


def _modell_inventar(path: Path, limit: int = 400) -> list[tuple[str, str]]:
    """Elemente eines bestehenden Modells (Name, Stereotyp) fuer den Prompt."""
    return _startpaket_inventar(path, limit=limit)


def _startpaket_inventar(path: Path, limit: int = 400) -> list[tuple[str, str]]:
    """Elemente eines Startpakets (Name, Stereotyp) fuer den Prompt lesen.

    Lesend und ohne Schreiben: Das Startpaket bleibt unangetastet. Nur
    Klassen zaehlen; Pakete und Diagramme sind keine Standardelemente.
    """
    if not path.exists():
        raise OSError(f"{path}: Datei nicht gefunden")
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA query_only = ON")
    try:
        rows = con.execute(
            "select Name, ifnull(Stereotype, '') from t_object "
            "where Object_Type <> 'Package' and Name is not null and Name <> '' "
            "order by Name limit ?",
            (limit,),
        ).fetchall()
    finally:
        con.close()
    return [(str(name), str(stereotype)) for name, stereotype in rows]


def cmd_toolbox(args: argparse.Namespace) -> int:
    """Standardelemente aus einem Katalog uebernehmen oder ein Modell harmonisieren."""
    import sqlite3
    import tempfile

    import qea_writer
    import toolbox_merge

    try:
        if args.modell is not None:
            base = args.modell
        else:
            # Ohne Bestand beginnt das Modell mit einem leeren Traegerpaket;
            # der Katalog wird hineinkopiert, statt ein Modell zu erfinden.
            base = Path(tempfile.mkdtemp(prefix="eam-toolbox-")) / "basis.qea"
            # Der Writer lehnt ein Modell ohne Element ab. Fuer den Start aus
            # dem Katalog dient daher ein Platzhalter, der nach dem Merge
            # wieder entfernt wird -- er gehoert nicht zum Ergebnis.
            qea_writer.write_qea(
                {
                    "ir_version": 1,
                    "technology": {"profile": ""},
                    "packages": [{"path": args.startpaket}],
                    "elements": [
                        {
                            "package": args.startpaket,
                            "name": "__startpaket_platzhalter__",
                            "stereotype": "",
                            "guid": _PLATZHALTER,
                        }
                    ],
                    "connectors": [],
                },
                base,
            )
        report = toolbox_merge.merge_toolbox(
            base,
            args.kasten,
            args.out,
            paketname=args.paket,
            nur=args.nur,
            dry_run=args.nur_bericht,
        )
    except (toolbox_merge.ToolboxMergeError, qea_writer.QeaWriterError, OSError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if args.bericht is not None:
        args.bericht.parent.mkdir(parents=True, exist_ok=True)
        args.bericht.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if args.modell is None and not args.nur_bericht:
        _drop_element(args.out, _PLATZHALTER)

    if args.nur_bericht:
        print(
            f"Vorschau: {report['elemente']} Elemente, {report['kanten']} Kanten, "
            f"{report['pakete']} Pakete, {report['bereits_vorhanden']} bereits vorhanden "
            f"-- nichts geschrieben"
        )
        return 0
    print(
        f"{args.out}: geschrieben, {report['elemente']} Elemente, "
        f"{report['kanten']} Kanten, {report['pakete']} Pakete, "
        f"{report['bereits_vorhanden']} bereits vorhanden, {report['tags']} Tags"
    )
    for warning in report.get("warnungen", []):
        print(f"HINWEIS: {warning}", file=sys.stderr)
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Mehrere .qea zu einem Modell zusammenfuehren (GUID-erhaltend)."""
    import sqlite3

    import model_merge  # lokal: der Bau-Pfad braucht den Merge nicht

    paths = [str(item) for group in args.qea for item in group]
    try:
        result = model_merge.merge_models(
            paths, args.out, package=args.paket, per_name=args.per_name
        )
    except (model_merge.MergeError, OSError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    report = result.as_dict()
    if args.bericht is not None:
        args.bericht.parent.mkdir(parents=True, exist_ok=True)
        args.bericht.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(
        f"{result.written}: geschrieben, {result.elements} Elemente, "
        f"{result.connections} Kanten, {result.packages} Pakete, "
        f"{result.merged} zusammengefuehrt, {len(result.conflicts)} Konflikte "
        f"aus {result.models} Modellen"
    )
    for conflict in result.conflicts:
        print(
            f"KONFLIKT: {conflict.get('art')} {conflict.get('paket')}::"
            f"{conflict.get('name')} ({conflict.get('datei')})",
            file=sys.stderr,
        )
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    """Gezielte Aenderungen an einer .qea anwenden (Original bleibt unberuehrt)."""
    import sqlite3

    import model_edit  # lokal: der Bau-Pfad braucht den Editor nicht

    try:
        payload = json.loads(args.ops.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FEHLER: {args.ops}: nicht lesbar ({exc})", file=sys.stderr)
        return 1

    try:
        result = model_edit.edit_model(args.qea, payload, args.out, mdg=args.mdg)
    except (model_edit.EditError, OSError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(
        f"{result.written}: geschrieben, {result.applied} von {result.ops} "
        f"Operationen angewendet, {len(result.rejected)} abgelehnt"
        + (f" (MDG: {result.mdg})" if result.mdg else "")
    )
    for rejection in result.rejected:
        print(
            f"ABGELEHNT: op {rejection.get('op')} {rejection.get('typ')}: "
            f"{rejection.get('grund')}",
            file=sys.stderr,
        )
    return 0 if not result.rejected else 1


def cmd_diff(args: argparse.Namespace) -> int:
    """Vergleicht zwei Architekturstaende ueber alle 4 Formate."""
    import model_diff

    try:
        res = model_diff.diff_models(args.alt, args.neu, mdg=args.mdg)
    except model_diff.DiffError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        text = json.dumps(res.as_dict(), ensure_ascii=False, indent=2) + "\n"
    elif args.format == "text":
        text = model_diff.render_text(res)
    else:
        text = model_diff.render_markdown(res)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.fail_on_changes and not res.identical:
        return 1
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    """Regelbasierte MDG-Reparatur mit Vorschau und optionalem Schreiben."""
    import model_io
    import repair_loop
    import validator

    model_path = Path(args.modell)
    if not model_path.is_file():
        print(f"FEHLER: Modell nicht gefunden: {model_path}", file=sys.stderr)
        return 1
    rules_path = args.mdg
    if not rules_path:
        here = Path(__file__).resolve().parent
        for cand in (
            here / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml",
            here.parent / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml",
            here / "knowledge" / "regelwerk.json",
            here.parent / "knowledge" / "regelwerk.json",
            here.parent.parent / "knowledge" / "regelwerk.json",
        ):
            if cand.is_file():
                rules_path = cand
                break
    if not rules_path or not Path(rules_path).is_file():
        print("FEHLER: Regelwerk fehlt (--mdg angeben)", file=sys.stderr)
        return 1

    try:
        ir = validator.load_ir(model_path)
        ruleset = validator.load_rules(Path(rules_path))
        outcome = repair_loop.repair(ir, ruleset, max_rounds=max(1, args.max_runden))
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER Reparatur: {exc}", file=sys.stderr)
        return 1

    all_changes = [ch.as_dict() for r in outcome.rounds for ch in r.changes]
    summary_before = outcome.rounds[0].errors_before if outcome.rounds else validator.summarize_findings(outcome.findings)["error"]
    summary_after = validator.summarize_findings(outcome.findings)

    payload: dict[str, Any] = {
        "modell": str(model_path),
        "applied": bool(args.apply and args.out),
        "changes_count": len(all_changes),
        "errors_before": summary_before,
        "errors_after": summary_after["error"],
        "warnings_after": summary_after["warning"],
        "changes": all_changes,
        "remaining_findings": outcome.findings[:50],
    }

    if args.apply:
        if args.out is None:
            print("FEHLER: --apply verlangt --out", file=sys.stderr)
            return 1
        try:
            written = model_io.write_model(outcome.ir, args.out)
            payload["written"] = str(written)
        except Exception as exc:  # noqa: BLE001
            print(f"FEHLER beim Schreiben: {exc}", file=sys.stderr)
            return 1

    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        mode_lbl = f"Geschrieben nach {payload.get('written')}" if args.apply else "Vorschau (nichts geschrieben, mit --out ZIEL --apply ausfuehren)"
        print(
            f"MDG-Reparatur ({mode_lbl}): {len(all_changes)} Aenderung(en), "
            f"Fehler {summary_before} -> {summary_after['error']}, "
            f"Warnungen {summary_after['warning']}"
        )
        for ch in all_changes[:30]:
            print(f"  - [{ch['kind']}] {ch['target']}: {ch['before']!r} -> {ch['after']!r} ({ch['reason']})")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Startet den schlanken 4-Format-MCP-Server ueber stdio (ohne Fremdpakete)."""
    import mcp_stdio

    if args.list_tools:
        sys.stdout.write(
            json.dumps({"tools": list(mcp_stdio.TOOLS)}, ensure_ascii=False, indent=2) + "\n"
        )
        return 0
    return mcp_stdio.serve_stdio(version=__version__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover - Bedienung
        print("FEHLER: abgebrochen", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
