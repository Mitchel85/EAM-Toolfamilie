#!/usr/bin/env python3
"""Hält die Datei-Namensliste für den Abhängigkeitsgraphen aktuell.

    python3 scripts/sync_dependency_files.py [--check]

Der Auslieferungsgraph liest die Manifeste (`package.json`) und die
Dateikanten. Für diese Familie ist die **Datei** „packages/rules/mdg_parser.py"
die Abhängigkeit, die zählt: sie erzeugt die Wissensbasis, aus der alle Apps
lesen. Diese Liste setzt das Skript in jedes abhängige Manifest (Abschnitt
`overrides`), damit eine Änderung dort im eigenen Graphen sichtbar wird. Der
native GitHub-Dependency-Graph löst die internen Paketnamen nicht auf.

`--check` schreibt nicht, sondern meldet Abweichungen (Exit 1) — das ist der
CI-Schritt, der eine vergessene Nachführung aufdeckt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Quelle der Wahrheit -> Manifests, die sie verbrauchen.
#: `apps/mdg-web` fehlt bewusst: Der Browser-Parser liest XML selbst und
#: importiert weder `mdg_parser.py` noch die Wissensbasis.
KANTEN = {
    "packages/core": "packages/rules",
    "apps/cli": "packages/core",
    "apps/mcp": "packages/core",
    "apps/admbw-extractor": "packages/rules",
    "apps/admbw-batch": "packages/rules",
    "apps/admbw-script-maker": "packages/rules",
}


def dateien(zelle: str) -> dict[str, str]:
    """Wichtigste Datei einer Zelle, relativ zum Repo."""
    ordner = ROOT / zelle
    for name in ("mdg_parser.py", "eam_ai.py"):
        if (ordner / name).is_file():
            return {name: f"./{zelle}/{name}"}
    treffer = sorted(p.name for p in ordner.glob("*.py"))[:1]
    return {treffer[0]: f"./{zelle}/{treffer[0]}"} if treffer else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Datei-Kanten in den Manifesten pflegen.")
    ap.add_argument("--check", action="store_true", help="nur prüfen, nichts schreiben")
    args = ap.parse_args()

    abweichend = 0
    for verbraucher, quelle in KANTEN.items():
        manifest = ROOT / verbraucher / "package.json"
        if not manifest.is_file():
            print(f"FEHLT: {manifest.relative_to(ROOT)}")
            abweichend += 1
            continue
        daten = json.loads(manifest.read_text(encoding="utf-8"))
        soll = dateien(quelle)
        if daten.get("overrides") != soll:
            abweichend += 1
            if args.check:
                print(f"ABWEICHUNG: {manifest.relative_to(ROOT)} -> {soll} (ist {daten.get('overrides')})")
            else:
                daten["overrides"] = soll
                manifest.write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.check:
        print(f"{len(KANTEN) - abweichend}/{len(KANTEN)} Manifeste aktuell")
    else:
        print(f"{len(KANTEN)} Manifeste gepflegt, {abweichend} geändert")
    return 0 if abweichend == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
