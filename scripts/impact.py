#!/usr/bin/env python3
"""Zeigt, welche Zellen eine Änderung berührt und was danach zu tun ist.

    python3 scripts/impact.py --changed packages/rules/mdg_parser.py
    python3 scripts/impact.py --git
    python3 scripts/impact.py --git --json

Die Matrix steht in `scripts/dependency_rules.py`; sie ist die kurze,
maschinenlesbare Fassung von `docs/ABHAENGIGKEITEN.md`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from dependency_rules import REGELN, treffer  # noqa: E402


def git_dateien() -> list[str]:
    for args in (["git", "diff", "--name-only", "HEAD"],
                 ["git", "diff", "--name-only", "HEAD~1", "HEAD"]):
        ergebnis = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
        dateien = [z.strip() for z in ergebnis.stdout.splitlines() if z.strip()]
        if dateien:
            return dateien
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Änderungswirkung anzeigen.")
    ap.add_argument("--changed", nargs="+", help="geänderte Dateien")
    ap.add_argument("--git", action="store_true", help="Änderungen aus git diff nehmen")
    ap.add_argument("--json", action="store_true", help="Maschinenlesbar ausgeben")
    args = ap.parse_args()
    if not args.changed and not args.git:
        ap.error("--changed DATEI… oder --git angeben")

    dateien = args.changed or git_dateien()
    if not dateien:
        print("Keine Änderungen gefunden.")
        return 0

    regeln: list[dict[str, object]] = []
    zellen: list[str] = []
    for datei in dateien:
        for regel in treffer(datei):
            if regel not in regeln:
                regeln.append(regel)
            for zelle in regel["zellen"]:
                if zelle not in zellen:
                    zellen.append(zelle)

    if args.json:
        print(json.dumps(
            {
                "dateien": dateien,
                "zellen": zellen,
                "regeln": [
                    {"id": r["id"], "befehl": r["befehl"], "hinweis": r["hinweis"]}
                    for r in regeln
                ],
            },
            indent=2,
            ensure_ascii=False,
        ))
        return 0

    print("Geändert:")
    for datei in dateien:
        print(f"  - {datei}")
    if not regeln:
        print("\nKeine Regel greift. Neue Datei? Matrix in scripts/dependency_rules.py ergänzen.")
        return 1
    print("\nBetroffen:")
    for zelle in zellen:
        print(f"  - {zelle}")
    print("\nNächste Schritte:")
    for regel in regeln:
        print(f"  [{regel['id']}] {regel['hinweis']}")
        print(f"    {regel['befehl']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
