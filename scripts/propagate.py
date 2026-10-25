#!/usr/bin/env python3
"""Ein Befehl für die Abhängigkeitskette.

    python3 scripts/propagate.py --check
    python3 scripts/propagate.py --write
    python3 scripts/propagate.py --build
    python3 scripts/propagate.py --release
    python3 scripts/propagate.py --all

--check    prüft Wissensbasis, Vendor-Kopien, Manifeste, Karte und Ein-Quellen-Regel
--write    erzeugt Wissensbasis und Vendor-Kopien neu, pflegt Manifeste/Karte
--build    baut die drei HTML-Werkzeuge und den MDG-Parser, sammelt `dist/`
--release  sammelt `dist/` aus bereits gebauten Artefakten
--all      write + build; die Tests bleiben ein eigener Schritt.

Der Unterschied zu einem bloßen Build: eine Änderung an der MDG, am Parser
oder an `vendor/` wird zuerst an die abhängigen Stellen weitergereicht, bevor
gebaut wird. `--check` ist der CI-Wächter gegen vergessene Kopien.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MDG = "packages/rules/NAFv4-ADMBw-MDG-2026.05.xml"
APPS = ("html-suite", "html-analyzer", "html-editor")


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def write() -> None:
    run(sys.executable, "scripts/build_knowledge.py", "--mdg", MDG)
    run(sys.executable, "scripts/sync_vendor.py", "--write")
    run(sys.executable, "scripts/sync_dependency_files.py")
    run(sys.executable, "scripts/dependency_report.py", "--write")


def check() -> None:
    run(sys.executable, "scripts/build_knowledge.py", "--mdg", MDG,
        "--check", "--check-provenance")
    run(sys.executable, "scripts/sync_vendor.py", "--check")
    run(sys.executable, "scripts/sync_dependency_files.py", "--check")
    run(sys.executable, "scripts/dependency_report.py", "--check")
    run(sys.executable, "scripts/check_single_source.py")


def build() -> None:
    for app in APPS:
        run(sys.executable, "scripts/build_legacy_app.py", f"apps/{app}")
    run(sys.executable, "apps/mdg-web/build.py")
    release()


def release() -> None:
    run(sys.executable, "scripts/collect_releases.py")
    run(sys.executable, "scripts/verify_graph.py", "--md", "dist/GRAPH.md")


def main() -> int:
    ap = argparse.ArgumentParser(description="Abhängigkeiten weiterreichen und bauen.")
    modus = ap.add_mutually_exclusive_group(required=True)
    modus.add_argument("--check", action="store_true")
    modus.add_argument("--write", action="store_true")
    modus.add_argument("--build", action="store_true")
    modus.add_argument("--release", action="store_true")
    modus.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.check:
        check()
    elif args.write:
        write()
    elif args.build:
        write()
        build()
    elif args.release:
        release()
    else:
        write()
        build()
        print("\nNächster Schritt: python3 -m pytest -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
