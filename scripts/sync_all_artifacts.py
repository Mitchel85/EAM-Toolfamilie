#!/usr/bin/env python3
"""Regeneriert alle abgeleiteten Grafiken und meldet externe Synchronitaetsziele.

Aufruf nach jeder funktionalen Aenderung an der EAM Toolfamilie:

    python3 scripts/sync_all_artifacts.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GENERATORS = [
    "scripts/make_workflow_image.py",
    "scripts/make_table_image.py",
    "scripts/make_linkedin_image.py",
    "scripts/verify_graph.py",
]


def main() -> int:
    for script in GENERATORS:
        print(f"==> {script}")
        res = subprocess.run([sys.executable, script], cwd=ROOT, check=False)
        if res.returncode != 0:
            print(f"FEHLER in {script} (Exit {res.returncode})", file=sys.stderr)
            return res.returncode

    print("\n--- Externe Synchronitaetsziele (pruefen & bei Bedarf aktualisieren) ---")
    print("1. GitHub Pages & Release-Katalog: scripts/collect_releases.py -> START-HIER.html (automatisch via pages.yml)")
    print("2. Zentrale Website (estel.email): ../Mitchel85/index.html")
    print("3. LinkedIn-Grafik: ../buchprojekt/EAM_TOOLFAMILIE_LINKEDIN.png (bereits mitkopiert, falls vorhanden)")
    print("4. Agensi-Skills (agensi.io): docs-to-architecture-builder, enterprise-architecture-qa-impact-analyzer, bpmn-2-0-process-validator, mdg-architecture-rules-extractor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
