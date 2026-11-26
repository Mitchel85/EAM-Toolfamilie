#!/usr/bin/env python3
"""model_diff.py -- Architektur-Standsvergleich ueber alle 4 Formate.

Vergleicht zwei Modellstaende (``.qea``, ``.xmi``, ArchiMate ``.xml``, ``.json``
oder bereits geladene IR-Mappings) deterministisch und ohne KI:

* **Pakete**: neu, entfernt, geaendert (Stereotyp, Notiz).
* **Elemente**: Zuordnung primar ueber ``ea_guid`` / ``guid`` (erkennt auch
  Umbenennungen und Paket-Umzuege), nachrangig ueber ``(Paket, Name)`` bzw.
  eindeutigen Namen (erkennt Stereotyp-, Notiz-, Status- und Tag-Aenderungen).
* **Beziehungen**: Abgleich ueber aufgeloeste Endpunkt-Identitaeten, Stereotyp
  und Typ -- unabhaengig von internen numerischen IDs oder Dateiformaten.
* **MDG-Delta (optional)**: wird ``--mdg`` uebergeben, weist der Bericht
  zusaetzlich behobene und neu hinzugekommene Regelverstoesse aus.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import validator


class DiffError(RuntimeError):
    """Modellvergleich fehlgeschlagen."""


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm_guid(el: Mapping[str, Any]) -> str:
    raw = _s(el.get("guid") or el.get("ea_guid"))
    if raw:
        return raw.casefold()
    tags = el.get("tags")
    if isinstance(tags, Mapping):
        for k, v in tags.items():
            if _s(k).casefold() in ("originalguid", "ea_guid", "standardelementguid") and _s(v):
                return _s(v).casefold()
    return ""


def _tags_dict(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        _s(k): _s(v)
        for k, v in sorted(raw.items(), key=lambda item: _s(item[0]).casefold())
        if _s(k)
    }


def _load_any(source: str | os.PathLike[str] | Mapping[str, Any], label: str) -> tuple[dict[str, Any], str]:
    if isinstance(source, Mapping):
        return dict(source), label
    path = Path(source)
    if not path.is_file():
        raise DiffError(f"{label}: Datei nicht gefunden: {path}")
    try:
        return validator.load_ir(path), str(path)
    except Exception as exc:  # noqa: BLE001
        raise DiffError(f"{label} ({path}): nicht lesbar ({exc})") from exc


def _el_summary(el: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "package": _s(el.get("package")),
        "name": _s(el.get("name")),
        "stereotype": _s(el.get("stereotype")),
        "ea_type": _s(el.get("ea_type")) or "Class",
    }
    guid = _s(el.get("guid") or el.get("ea_guid"))
    if guid:
        out["guid"] = guid
    return out


def _build_ref_resolver(
    elements: Sequence[Mapping[str, Any]],
    canon_by_idx: Mapping[int, str],
) -> dict[str, str]:
    """Ordnet IR-Referenzen (ref, guid, package::name, eindeutiger name) der kanonischen Kennung zu."""
    resolver: dict[str, str] = {}
    name_counts: dict[str, int] = {}
    for el in elements:
        nm = _s(el.get("name")).casefold()
        if nm:
            name_counts[nm] = name_counts.get(nm, 0) + 1

    for idx, el in enumerate(elements):
        canon = canon_by_idx[idx]
        pkg = _s(el.get("package"))
        nm = _s(el.get("name"))
        ref = _s(el.get("ref"))
        guid = _s(el.get("guid") or el.get("ea_guid"))
        if ref:
            resolver[ref] = canon
            resolver[ref.casefold()] = canon
        if guid:
            resolver[guid] = canon
            resolver[guid.casefold()] = canon
        if pkg and nm:
            qual = f"{pkg}::{nm}"
            resolver[qual] = canon
            resolver[qual.casefold()] = canon
        if nm and name_counts.get(nm.casefold(), 0) == 1:
            resolver.setdefault(nm, canon)
            resolver.setdefault(nm.casefold(), canon)
    return resolver


def _resolve_endpoint(raw: str, guid_raw: str, resolver: Mapping[str, str]) -> str:
    for candidate in (guid_raw, guid_raw.casefold(), raw, raw.casefold()):
        if candidate and candidate in resolver:
            return resolver[candidate]
    return raw.strip()


@dataclass(frozen=True)
class DiffResult:
    alt_label: str
    neu_label: str
    identical: bool
    summary: dict[str, int]
    packages: dict[str, list[dict[str, Any]]]
    elements: dict[str, list[dict[str, Any]]]
    connectors: dict[str, list[dict[str, Any]]]
    mdg: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "alt": self.alt_label,
            "neu": self.neu_label,
            "identical": self.identical,
            "summary": dict(self.summary),
            "packages": self.packages,
            "elements": self.elements,
            "connectors": self.connectors,
        }
        if self.mdg is not None:
            out["mdg"] = self.mdg
        return out


def diff_models(
    alt_source: str | os.PathLike[str] | Mapping[str, Any],
    neu_source: str | os.PathLike[str] | Mapping[str, Any],
    *,
    mdg: str | os.PathLike[str] | validator.RuleSet | None = None,
) -> DiffResult:
    """Vergleicht ``alt_source`` und ``neu_source`` deterministisch."""
    ir_alt, lbl_alt = _load_any(alt_source, "Altmodell")
    ir_neu, lbl_neu = _load_any(neu_source, "Neumodell")

    # 1. Pakete
    pkgs_alt = {_s(p.get("path")): p for p in (ir_alt.get("packages") or ()) if isinstance(p, Mapping) and _s(p.get("path"))}
    pkgs_neu = {_s(p.get("path")): p for p in (ir_neu.get("packages") or ()) if isinstance(p, Mapping) and _s(p.get("path"))}
    pkg_added = [{"path": k, "stereotype": _s(pkgs_neu[k].get("stereotype"))} for k in sorted(set(pkgs_neu) - set(pkgs_alt))]
    pkg_removed = [{"path": k, "stereotype": _s(pkgs_alt[k].get("stereotype"))} for k in sorted(set(pkgs_alt) - set(pkgs_neu))]
    pkg_changed: list[dict[str, Any]] = []
    for k in sorted(set(pkgs_alt) & set(pkgs_neu)):
        pa, pn = pkgs_alt[k], pkgs_neu[k]
        changes: dict[str, dict[str, str]] = {}
        for fld in ("stereotype", "notes"):
            va, vn = _s(pa.get(fld)), _s(pn.get(fld))
            if va != vn:
                changes[fld] = {"before": va, "after": vn}
        if changes:
            pkg_changed.append({"path": k, "changes": changes})

    # 2. Elemente zuordnen (1. GUID, 2. Paket+Name, 3. eindeutiger Name)
    els_alt = [e for e in (ir_alt.get("elements") or ()) if isinstance(e, Mapping)]
    els_neu = [e for e in (ir_neu.get("elements") or ()) if isinstance(e, Mapping)]

    matched_alt_to_neu: dict[int, int] = {}
    used_neu: set[int] = set()

    neu_by_guid: dict[str, list[int]] = {}
    for j, el in enumerate(els_neu):
        g = _norm_guid(el)
        if g:
            neu_by_guid.setdefault(g, []).append(j)

    for i, el in enumerate(els_alt):
        g = _norm_guid(el)
        if g and g in neu_by_guid:
            for j in neu_by_guid[g]:
                if j not in used_neu:
                    matched_alt_to_neu[i] = j
                    used_neu.add(j)
                    break

    neu_by_pkg_name: dict[tuple[str, str], list[int]] = {}
    for j, el in enumerate(els_neu):
        if j in used_neu:
            continue
        key = (_s(el.get("package")).casefold(), _s(el.get("name")).casefold())
        if key[1]:
            neu_by_pkg_name.setdefault(key, []).append(j)

    for i, el in enumerate(els_alt):
        if i in matched_alt_to_neu:
            continue
        key = (_s(el.get("package")).casefold(), _s(el.get("name")).casefold())
        cands = [j for j in neu_by_pkg_name.get(key, ()) if j not in used_neu]
        if cands:
            # Gleicher Stereotyp bevorzugt
            st_a = _s(el.get("stereotype")).casefold()
            same_st = [j for j in cands if _s(els_neu[j].get("stereotype")).casefold() == st_a]
            chosen = same_st[0] if same_st else cands[0]
            matched_alt_to_neu[i] = chosen
            used_neu.add(chosen)

    # Eindeutige Namen fuer Paket-Umzuege ohne GUID
    unmatched_alt_names: dict[str, list[int]] = {}
    for i, el in enumerate(els_alt):
        if i not in matched_alt_to_neu and _s(el.get("name")):
            unmatched_alt_names.setdefault(_s(el.get("name")).casefold(), []).append(i)
    unmatched_neu_names: dict[str, list[int]] = {}
    for j, el in enumerate(els_neu):
        if j not in used_neu and _s(el.get("name")):
            unmatched_neu_names.setdefault(_s(el.get("name")).casefold(), []).append(j)
    for nm_low, alt_idxs in unmatched_alt_names.items():
        neu_idxs = unmatched_neu_names.get(nm_low, [])
        if len(alt_idxs) == 1 and len(neu_idxs) == 1:
            matched_alt_to_neu[alt_idxs[0]] = neu_idxs[0]
            used_neu.add(neu_idxs[0])

    # Kanonische Identitaeten fuer Kanten-Aufloesung
    canon_alt: dict[int, str] = {}
    canon_neu: dict[int, str] = {}
    label_by_canon: dict[str, str] = {}

    for i, el in enumerate(els_alt):
        if i in matched_alt_to_neu:
            j = matched_alt_to_neu[i]
            cid = f"M#{i}"
            canon_alt[i] = cid
            canon_neu[j] = cid
            en = els_neu[j]
            pkg_lbl = _s(en.get("package"))
            nm_lbl = _s(en.get("name"))
            label_by_canon[cid] = f"{pkg_lbl}::{nm_lbl}" if pkg_lbl else nm_lbl
        else:
            cid = f"A#{i}"
            canon_alt[i] = cid
            pkg_lbl = _s(el.get("package"))
            nm_lbl = _s(el.get("name"))
            label_by_canon[cid] = f"{pkg_lbl}::{nm_lbl}" if pkg_lbl else nm_lbl

    for j, el in enumerate(els_neu):
        if j not in canon_neu:
            cid = f"N#{j}"
            canon_neu[j] = cid
            pkg_lbl = _s(el.get("package"))
            nm_lbl = _s(el.get("name"))
            label_by_canon[cid] = f"{pkg_lbl}::{nm_lbl}" if pkg_lbl else nm_lbl

    el_added = [_el_summary(els_neu[j]) for j in range(len(els_neu)) if j not in used_neu]
    el_removed = [_el_summary(els_alt[i]) for i in range(len(els_alt)) if i not in matched_alt_to_neu]
    el_added.sort(key=lambda x: (x["package"].casefold(), x["name"].casefold(), x["stereotype"].casefold()))
    el_removed.sort(key=lambda x: (x["package"].casefold(), x["name"].casefold(), x["stereotype"].casefold()))

    el_changed: list[dict[str, Any]] = []
    for i, j in sorted(matched_alt_to_neu.items()):
        ea, en = els_alt[i], els_neu[j]
        fchanges: dict[str, Any] = {}
        for fld, default in (
            ("name", ""),
            ("package", ""),
            ("stereotype", ""),
            ("ea_type", "Class"),
            ("status", ""),
            ("alias", ""),
            ("notes", ""),
        ):
            va = _s(ea.get(fld)) or default
            vn = _s(en.get(fld)) or default
            if va != vn:
                if fld == "notes":
                    fchanges[fld] = {
                        "before": va[:240],
                        "after": vn[:240],
                    }
                else:
                    fchanges[fld] = {"before": va, "after": vn}
        ta, tn = _tags_dict(ea.get("tags")), _tags_dict(en.get("tags"))
        if ta != tn:
            t_added = {k: tn[k] for k in sorted(set(tn) - set(ta))}
            t_removed = {k: ta[k] for k in sorted(set(ta) - set(tn))}
            t_mod = {
                k: {"before": ta[k], "after": tn[k]}
                for k in sorted(set(ta) & set(tn))
                if ta[k] != tn[k]
            }
            if t_added or t_removed or t_mod:
                fchanges["tags"] = {
                    "added": t_added,
                    "removed": t_removed,
                    "changed": t_mod,
                }
        if fchanges:
            entry: dict[str, Any] = {
                "package": _s(en.get("package")) or _s(ea.get("package")),
                "name": _s(en.get("name")) or _s(ea.get("name")),
                "stereotype": _s(en.get("stereotype")) or _s(ea.get("stereotype")),
                "changes": fchanges,
            }
            guid = _s(en.get("guid") or en.get("ea_guid") or ea.get("guid") or ea.get("ea_guid"))
            if guid:
                entry["guid"] = guid
            el_changed.append(entry)
    el_changed.sort(key=lambda x: (x["package"].casefold(), x["name"].casefold()))

    # 3. Beziehungen
    res_alt = _build_ref_resolver(els_alt, canon_alt)
    res_neu = _build_ref_resolver(els_neu, canon_neu)

    def _conn_map(conns: Sequence[Any], resolver: Mapping[str, str]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
        out: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for c in conns:
            if not isinstance(c, Mapping):
                continue
            src = _resolve_endpoint(_s(c.get("source")), _s(c.get("source_guid")), resolver)
            tgt = _resolve_endpoint(_s(c.get("target")), _s(c.get("target_guid")), resolver)
            st = _s(c.get("stereotype"))
            nm = _s(c.get("name"))
            key = (src, tgt, st.casefold(), nm.casefold())
            out[key] = {
                "source": label_by_canon.get(src, src),
                "target": label_by_canon.get(tgt, tgt),
                "stereotype": st,
                "ea_type": _s(c.get("ea_type")) or "Association",
                "name": nm,
                "notes": _s(c.get("notes")),
            }
        return out

    cmap_alt = _conn_map(ir_alt.get("connectors") or (), res_alt)
    cmap_neu = _conn_map(ir_neu.get("connectors") or (), res_neu)

    conn_added = [
        {k: v for k, v in cmap_neu[key].items() if k != "notes" or v}
        for key in sorted(set(cmap_neu) - set(cmap_alt))
    ]
    conn_removed = [
        {k: v for k, v in cmap_alt[key].items() if k != "notes" or v}
        for key in sorted(set(cmap_alt) - set(cmap_neu))
    ]
    conn_changed: list[dict[str, Any]] = []
    for key in sorted(set(cmap_alt) & set(cmap_neu)):
        ca, cn = cmap_alt[key], cmap_neu[key]
        c_diff: dict[str, Any] = {}
        for fld in ("ea_type", "notes"):
            if ca[fld] != cn[fld]:
                c_diff[fld] = {"before": ca[fld][:200], "after": cn[fld][:200]}
        if c_diff:
            conn_changed.append(
                {
                    "source": cn["source"],
                    "target": cn["target"],
                    "stereotype": cn["stereotype"],
                    "changes": c_diff,
                }
            )

    # 4. Optionales MDG-Delta
    mdg_delta: dict[str, Any] | None = None
    if mdg is not None:
        ruleset = mdg if isinstance(mdg, validator.RuleSet) else validator.load_rules(Path(mdg))
        f_alt = validator.validate_model(ir_alt, ruleset)
        f_neu = validator.validate_model(ir_neu, ruleset)
        s_alt = validator.summarize_findings(f_alt)
        s_neu = validator.summarize_findings(f_neu)

        def _fkey(f: Mapping[str, Any]) -> tuple[str, str, str, str]:
            return (
                _s(f.get("severity")),
                _s(f.get("check")),
                _s(f.get("object") or f.get("object_label")),
                _s(f.get("message")),
            )

        map_fa = {_fkey(f): dict(f) for f in f_alt}
        map_fn = {_fkey(f): dict(f) for f in f_neu}
        resolved = [map_fa[k] for k in sorted(set(map_fa) - set(map_fn))]
        introduced = [map_fn[k] for k in sorted(set(map_fn) - set(map_fa))]
        mdg_delta = {
            "rules": ruleset.name,
            "before": s_alt,
            "after": s_neu,
            "error_delta": s_neu["error"] - s_alt["error"],
            "warning_delta": s_neu["warning"] - s_alt["warning"],
            "resolved": resolved,
            "new": introduced,
        }

    summary = {
        "packages_added": len(pkg_added),
        "packages_removed": len(pkg_removed),
        "packages_changed": len(pkg_changed),
        "elements_added": len(el_added),
        "elements_removed": len(el_removed),
        "elements_changed": len(el_changed),
        "connectors_added": len(conn_added),
        "connectors_removed": len(conn_removed),
        "connectors_changed": len(conn_changed),
    }
    identical = all(v == 0 for v in summary.values())

    return DiffResult(
        alt_label=lbl_alt,
        neu_label=lbl_neu,
        identical=identical,
        summary=summary,
        packages={"added": pkg_added, "removed": pkg_removed, "changed": pkg_changed},
        elements={"added": el_added, "removed": el_removed, "changed": el_changed},
        connectors={"added": conn_added, "removed": conn_removed, "changed": conn_changed},
        mdg=mdg_delta,
    )


def render_markdown(diff: DiffResult, *, limit: int = 50) -> str:
    """Formatiert das Vergleichsergebnis als kompakten deutschen Markdown-Bericht."""
    s = diff.summary
    lines = [
        "# Architektur-Änderungsbericht (Modell-Diff)",
        "",
        f"- **Altstand:** `{diff.alt_label}`",
        f"- **Neustand:** `{diff.neu_label}`",
        f"- **Status:** {'Identisch (keine fachlichen Abweichungen)' if diff.identical else 'Abweichungen festgestellt'}",
        "",
        "## Kennzahlen",
        "",
        "| Bereich | Neu (+) | Entfernt (-) | Geändert (~) |",
        "|---|---:|---:|---:|",
        f"| Pakete | {s['packages_added']} | {s['packages_removed']} | {s['packages_changed']} |",
        f"| Elemente | {s['elements_added']} | {s['elements_removed']} | {s['elements_changed']} |",
        f"| Beziehungen | {s['connectors_added']} | {s['connectors_removed']} | {s['connectors_changed']} |",
    ]
    if diff.mdg is not None:
        m = diff.mdg
        lines.extend(
            [
                "",
                f"## MDG-Konformitäts-Delta ({m['rules']})",
                "",
                f"- **Fehler:** {m['before']['error']} -> {m['after']['error']} ({m['error_delta']:+d})",
                f"- **Warnungen:** {m['before']['warning']} -> {m['after']['warning']} ({m['warning_delta']:+d})",
                f"- **Behobene Befunde:** {len(m['resolved'])} | **Neue Befunde:** {len(m['new'])}",
            ]
        )

    def _section(title: str, items: Sequence[str]) -> None:
        if not items:
            return
        lines.extend(["", f"## {title}", ""])
        shown = items[:limit] if limit > 0 else items
        lines.extend(f"- {item}" for item in shown)
        if limit > 0 and len(items) > limit:
            lines.append(f"- ... (+{len(items) - limit} weitere)")

    _section(
        "Neue Elemente (+)",
        [
            f"`{e['package']}::{e['name']}`" + (f" «{e['stereotype']}»" if e["stereotype"] else "")
            for e in diff.elements["added"]
        ],
    )
    _section(
        "Entfernte Elemente (-)",
        [
            f"`{e['package']}::{e['name']}`" + (f" «{e['stereotype']}»" if e["stereotype"] else "")
            for e in diff.elements["removed"]
        ],
    )
    _section(
        "Geänderte Elemente (~)",
        [
            f"`{e['package']}::{e['name']}`: "
            + ", ".join(
                f"{k} ({v['before']!r} -> {v['after']!r})" if "before" in v else k
                for k, v in e["changes"].items()
            )
            for e in diff.elements["changed"]
        ],
    )
    _section(
        "Neue Beziehungen (+)",
        [
            f"`{c['source']}` -[{c['stereotype'] or c['ea_type']}]-> `{c['target']}`"
            for c in diff.connectors["added"]
        ],
    )
    _section(
        "Entfernte Beziehungen (-)",
        [
            f"`{c['source']}` -[{c['stereotype'] or c['ea_type']}]-> `{c['target']}`"
            for c in diff.connectors["removed"]
        ],
    )
    return "\n".join(lines) + "\n"


def render_text(diff: DiffResult) -> str:
    s = diff.summary
    head = (
        f"Modell-Diff: {'IDENTISCH' if diff.identical else 'GEAENDERT'} -- "
        f"Pakete +{s['packages_added']}/-{s['packages_removed']}/~{s['packages_changed']}, "
        f"Elemente +{s['elements_added']}/-{s['elements_removed']}/~{s['elements_changed']}, "
        f"Beziehungen +{s['connectors_added']}/-{s['connectors_removed']}/~{s['connectors_changed']}"
    )
    if diff.mdg is not None:
        m = diff.mdg
        head += (
            f" | MDG Fehler {m['before']['error']}->{m['after']['error']}, "
            f"behoben {len(m['resolved'])}, neu {len(m['new'])}"
        )
    return head + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Architektur-Standsvergleich (.qea, .xmi, .xml, .json)")
    p.add_argument("--alt", required=True, type=Path, help="Altes/Referenz-Modell")
    p.add_argument("--neu", required=True, type=Path, help="Neues/Geaendertes Modell")
    p.add_argument("--mdg", type=Path, default=None, help="Optionale MDG-XML oder rules.json fuer Befund-Delta")
    p.add_argument("--format", "-f", choices=("text", "md", "json"), default="md")
    p.add_argument("--out", "-o", type=Path, default=None, help="Bericht in Datei schreiben")
    p.add_argument("--fail-on-changes", action="store_true", help="Exit 1 bei Abweichungen")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        res = diff_models(args.alt, args.neu, mdg=args.mdg)
    except DiffError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        text = json.dumps(res.as_dict(), ensure_ascii=False, indent=2) + "\n"
    elif args.format == "text":
        text = render_text(res)
    else:
        text = render_markdown(res)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.fail_on_changes and not res.identical:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
