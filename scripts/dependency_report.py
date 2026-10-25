#!/usr/bin/env python3
"""Schreibt die lesbare Abhängigkeitskarte des Repos.

    python3 scripts/dependency_report.py --write
    python3 scripts/dependency_report.py --check

Die Karte ist erzeugt, nicht handgepflegt. Sie beantwortet drei Fragen:
Wer liest wen? Was passiert bei einer Änderung? Welche Datei ist kanonisch?
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from collect_releases import AUSLIEFERUNGEN  # noqa: E402
from dependency_rules import REGELN  # noqa: E402
from sync_vendor import QUELLE, ZUORDNUNG  # noqa: E402
from verify_graph import ZELLEN  # noqa: E402

ZIEL = ROOT / "docs" / "ABHAENGIGKEITEN.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def zellen_tabelle() -> list[str]:
    zeilen = ["| Zelle | Name | Version | Abhängigkeiten |", "|---|---|---|---|"]
    for rel in ZELLEN:
        manifest = ROOT / rel / "package.json"
        daten = json.loads(manifest.read_text(encoding="utf-8"))
        deps = [*daten.get("dependencies", {}), *daten.get("devDependencies", {})]
        text = ", ".join(f"`{d}`" for d in deps) or "—"
        zeilen.append(f"| `{rel}` | {daten.get('name')} | {daten.get('version')} | {text} |")
    return zeilen


def vendor_tabelle() -> list[str]:
    dateien = sorted(p for p in QUELLE.glob("*") if p.is_file() and p.name not in {"package.json", "README.md"})
    kopf = ["| Bibliothek | SHA-256 | Suite | Analyzer | Editor |", "|---|---|---|---|---|"]
    for datei in dateien:
        spalten = ["x" if datei.name in ZUORDNUNG[app] else "—" for app in
                   ("apps/html-suite", "apps/html-analyzer", "apps/html-editor")]
        kopf.append(f"| `vendor/{datei.name}` | `{sha256(datei)[:16]}…` | {' | '.join(spalten)} |")
    return kopf


def release_tabelle() -> list[str]:
    zeilen = ["| Asset | Quelle |", "|---|---|"]
    for quelle, ziel, *_ in AUSLIEFERUNGEN:
        zeilen.append(f"| `{ziel}` | `{quelle}` |")
    zeilen.append("| `eam-ai-suite-python.zip` | `packages/core` (Quellarchiv) |")
    return zeilen


def wissensbasis_verweise() -> list[str]:
    verweise: list[str] = []
    for app in ("apps/admbw-extractor", "apps/admbw-batch", "apps/admbw-script-maker"):
        for pfad in sorted((ROOT / app).rglob("*")):
            if pfad.is_symlink() and "knowledge" in str(pfad.resolve()):
                verweise.append(f"- `{pfad.relative_to(ROOT)}` → `{pfad.resolve().relative_to(ROOT)}`")
    return verweise


def graph() -> list[str]:
    """Mermaid-Diagramm aus den echten Manifestkanten."""
    ids = {rel: f"z{i}" for i, rel in enumerate(ZELLEN)}
    namen = {}
    for rel in ZELLEN:
        daten = json.loads((ROOT / rel / "package.json").read_text(encoding="utf-8"))
        namen[daten["name"]] = rel
    zeilen = ["## 0. Graph", "", "```mermaid", "flowchart LR"]
    for rel, knoten in ids.items():
        daten = json.loads((ROOT / rel / "package.json").read_text(encoding="utf-8"))
        zeilen.append(f'  {knoten}["{daten.get("name")}<br/>{rel}"]')
    for rel, knoten in ids.items():
        daten = json.loads((ROOT / rel / "package.json").read_text(encoding="utf-8"))
        for dep in daten.get("dependencies", {}):
            zeilen.append(f"  {knoten} --> {ids[namen[dep]]}")
        for dep in daten.get("devDependencies", {}):
            zeilen.append(f"  {knoten} -.-> {ids[namen[dep]]}")
    zeilen += ["```", ""]
    return zeilen


def render() -> str:
    zeilen = [
        "# Abhängigkeiten der EAM-Toolfamilie",
        "",
        "> Erzeugt von `scripts/dependency_report.py`; nicht von Hand ändern.",
        "> Prüfen mit `python3 scripts/dependency_report.py --check`.",
        "> GitHub rendert den Mermaid-Block; lokal zeigen ihn VS Code oder Obsidian.",
        "",
        *graph(),
        "## 1. Zellen und Kanten",
        "",
        "Eine Zelle ist ein Ordner mit `package.json`. `dependencies` sind Laufzeit-,",
        "`devDependencies` sind Build-Zeit-Kanten.",
        "",
        *zellen_tabelle(),
        "",
        "## 2. Kanonische Quellen",
        "",
        "| Quelle | Wird zu | Mechanik | Prüfung |",
        "|---|---|---|---|",
        "| `packages/rules/NAFv4-ADMBw-MDG-2026.05.xml` | `knowledge/admbw-*` | `build_knowledge.py` | `--check --check-provenance` |",
        "| `packages/rules/mdg_parser.py` + `documents.py` | `knowledge/admbw-*` | Parser → Dokumente | `check_single_source.py` |",
        "| `knowledge/*` | `apps/admbw-*/` | Symlink, keine Kopie | `verify_graph.py` |",
        "| `vendor/*` | `apps/html-*/vendor/` | `sync_vendor.py` | `sync_vendor.py --check` |",
        "| `apps/html-*/src` + `vendor` | `apps/html-*/dist` | `build_legacy_app.py` | `test_html_artifacts.py` |",
        "| `apps/mdg-web/index.html` | `apps/mdg-web/dist` | byte-gleiche Kopie | `test_mdg_web.py` |",
        "| `apps/*/dist` | `dist/` | `collect_releases.py` | `test_collect_releases.py` |",
        "",
        "## 3. Änderungsmatrix",
        "",
        "| Änderung | Betroffen | Befehl |",
        "|---|---|---|",
    ]
    for regel in REGELN:
        pfade = "<br>".join(f"`{p}`" for p in regel["pfade"])
        zellen = ", ".join(f"`{z}`" for z in regel["zellen"])
        zeilen.append(f"| {pfade} | {zellen} | `{regel['befehl']}` |")
    zeilen += [
        "",
        "## 4. Vendor",
        "",
        *vendor_tabelle(),
        "",
        "## 5. Wissensbasis-Verweise",
        "",
        f"{len(wissensbasis_verweise())} Symlinks in den Downstream-Apps:",
        "",
        *wissensbasis_verweise(),
        "",
        "## 6. Release-Assets",
        "",
        *release_tabelle(),
        "",
    ]
    return "\n".join(zeilen) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Abhängigkeitskarte schreiben oder prüfen.")
    ap.add_argument("--write", action="store_true", help="docs/ABHAENGIGKEITEN.md schreiben")
    ap.add_argument("--check", action="store_true", help="nur prüfen")
    args = ap.parse_args()
    if args.check == args.write:
        ap.error("genau eines von --check oder --write angeben")
    neu = render()
    if args.write:
        ZIEL.write_text(neu, encoding="utf-8")
        print(f"geschrieben: {ZIEL.relative_to(ROOT)} ({len(neu.splitlines())} Zeilen)")
        return 0
    if not ZIEL.is_file():
        print(f"FEHLT: {ZIEL.relative_to(ROOT)}")
        return 1
    alt = ZIEL.read_text(encoding="utf-8")
    if alt != neu:
        print(f"ABWEICHUNG: {ZIEL.relative_to(ROOT)} ist nicht aktuell")
        return 1
    print(f"{ZIEL.relative_to(ROOT)} ist aktuell ({len(neu.splitlines())} Zeilen)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
