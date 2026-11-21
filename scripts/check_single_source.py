#!/usr/bin/env python3
"""Prueft die Ein-Quellen-Regel des Repos.

Der Anspruch: eine MDG hinein, eine Wissensbasis heraus, genau ein Leser.
Dieses Skript macht den Anspruch pruefbar, statt ihn nur zu behaupten.

Geprueft wird:

1. Genau **ein** MDG-Leser (``mdg_parser.py``) im Produktionscode. Der
   archivierte Altparser unter ``tools/referenz_parser`` ist Pruefmassstab
   und ausdruecklich ausgenommen.
2. Keine handgepflegte Wissensbasis ausserhalb von ``knowledge/``: jede
   ``admbw-*``-Datei in ``apps/`` ist ein Symlink in die Wissensbasis.
3. ``documents.py`` liest kein XML. Sonst entstuende ein zweiter Leser.
4. ``knowledge/PROVENANCE.json`` nennt jede erzeugte Datei.

Aufruf::

    python3 scripts/check_single_source.py

Exit 0 heisst: die Regel haelt. Exit 1 nennt jede Verletzung einzeln.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
RULES = ROOT / "packages" / "rules"
PARSER = RULES / "mdg_parser.py"
DOCUMENTS = RULES / "documents.py"
PROVENANCE = KNOWLEDGE / "PROVENANCE.json"

#: Ordner, die nicht zum Produktionscode zaehlen.
AUSGENOMMEN = {
    ".git",
    "dist",
    "build",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "tools",  # enthaelt den archivierten Pruefmassstab
}

#: Dateien, die keine Wissensbasis sind: der Extraktor-Prompt gehoert zur App
#: und wird von dort einmal gefuehrt, nicht aus der MDG erzeugt.
KEINE_WISSENSBASIS = {"admbw-extractor-system-prompt.md"}

XML_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:xml\.etree|xml\.dom|lxml|ElementTree)",
    re.MULTILINE,
)


def _wichtig(pfad: Path) -> bool:
    return not any(teil in AUSGENOMMEN for teil in pfad.relative_to(ROOT).parts)


def finde_parser() -> list[Path]:
    return sorted(
        p
        for p in ROOT.rglob("mdg_parser.py")
        if _wichtig(p) and p.is_file()
    )


def finde_kopien() -> tuple[list[Path], list[Path]]:
    """Regulaere Dateien und falsch aufloesende Symlinks in apps/."""
    dateien: list[Path] = []
    kaputt: list[Path] = []
    for pfad in ROOT.rglob("*"):
        if not _wichtig(pfad):
            continue
        if not fnmatch.fnmatch(pfad.name.lower(), "admbw-*"):
            continue
        if pfad.is_dir():
            continue
        if pfad.resolve().parent == KNOWLEDGE.resolve():
            continue  # die Quelle selbst
        if pfad.name.lower() in KEINE_WISSENSBASIS:
            continue
        if pfad.is_symlink():
            ziel = (pfad.parent / pfad.readlink()).resolve()
            try:
                ziel.relative_to(KNOWLEDGE.resolve())
            except ValueError:
                kaputt.append(pfad)
            else:
                if not ziel.is_file():
                    kaputt.append(pfad)
        else:
            dateien.append(pfad)
    return sorted(dateien), sorted(kaputt)


def pruefe_provenienz() -> list[str]:
    meldungen: list[str] = []
    if not PROVENANCE.is_file():
        return [f"{PROVENANCE.relative_to(ROOT)} fehlt"]
    data = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    genannt = set((data.get("files") or {}).keys())
    vorhanden = {p.name for p in KNOWLEDGE.glob("admbw-*") if p.is_file()}
    for name in sorted(vorhanden - genannt):
        meldungen.append(f"nicht in PROVENANCE.json: knowledge/{name}")
    for name in sorted(genannt - vorhanden):
        meldungen.append(f"PROVENANCE.json nennt fehlende Datei: knowledge/{name}")
    return meldungen


def pruefe() -> list[str]:
    meldungen: list[str] = []

    parser = finde_parser()
    if len(parser) != 1:
        relativ = ", ".join(str(p.relative_to(ROOT)) for p in parser)
        meldungen.append(f"erwartet genau ein mdg_parser.py, gefunden {len(parser)}: {relativ}")
    elif parser[0] != PARSER:
        meldungen.append(
            f"der MDG-Leser liegt nicht am kanonischen Ort: {parser[0].relative_to(ROOT)} "
            f"(erwartet {PARSER.relative_to(ROOT)})"
        )

    if DOCUMENTS.is_file():
        if XML_IMPORT.search(DOCUMENTS.read_text(encoding="utf-8")):
            meldungen.append("documents.py importiert einen XML-Leser — es darf nur einen geben")

    dateien, kaputt = finde_kopien()
    for pfad in dateien:
        meldungen.append(
            f"handgepflegte Wissensbasis ausserhalb von knowledge/: {pfad.relative_to(ROOT)}"
        )
    for pfad in kaputt:
        meldungen.append(
            f"Symlink zeigt nicht in die Wissensbasis: {pfad.relative_to(ROOT)}"
        )

    meldungen.extend(pruefe_provenienz())
    return meldungen


def main() -> int:
    meldungen = pruefe()
    if meldungen:
        print("Ein-Quellen-Regel verletzt:")
        for eintrag in meldungen:
            print("  -", eintrag)
        return 1
    print("Ein-Quellen-Regel haelt: ein Leser, eine Wissensbasis, keine Kopien in den Apps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
