#!/usr/bin/env python3
"""Hält die Vendor-Kopien der HTML-Werkzeuge mit der kanonischen Quelle synchron.

    python3 scripts/sync_vendor.py --check
    python3 scripts/sync_vendor.py --check --allow-missing
    python3 scripts/sync_vendor.py --write

Die Kopien in ``apps/<app>/vendor/`` entstehen beim Bauen und sind darum
nicht versioniert (siehe ``.gitignore``). Ein frischer Klon hat sie noch
nicht; ``--allow-missing`` toleriert genau das. Abweichende oder überzählige
Dateien bleiben auch dort ein Befund.

`vendor/` ist die einzige Quelle für gemeinsam genutzte Browser-Bibliotheken.
Die drei Altwerkzeuge brauchen lokale Kopien, weil ihre Build-Skripte und die
ausgelieferten Einzeldateien keinen Netzwerkzugriff haben. Dieses Skript hält
die Kopien byte-gleich und meldet jede Abweichung.

Die Zuordnung ist absichtlich explizit: nicht jede App braucht jede Bibliothek.
Ein neues Vendor-File wird hier eingetragen und danach in die Apps gespiegelt.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUELLE = ROOT / "vendor"

#: App -> Dateien, die in `apps/<app>/vendor/` liegen müssen.
ZUORDNUNG: dict[str, tuple[str, ...]] = {
    "apps/html-suite": (
        "jszip.min.js",
        "pdf.min.js",
        "pdf.worker.min.js",
        "sql-wasm.js",
        "sql-wasm.wasm",
        "LICENSE-sql.js",
    ),
    "apps/html-analyzer": (
        "sql-wasm.js",
        "sql-wasm.wasm",
        "LICENSE-sql.js",
    ),
    "apps/html-editor": (
        "sql-wasm.js",
        "sql-wasm.wasm",
        "LICENSE-sql.js",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def unterschiede(app: str) -> list[str]:
    """Fehlende, abweichende oder überzählige Dateien einer App."""
    ziel = ROOT / app / "vendor"
    erwartet = ZUORDNUNG[app]
    befunde: list[str] = []
    for name in erwartet:
        quelle = QUELLE / name
        zieldatei = ziel / name
        if not quelle.is_file():
            befunde.append(f"{app}: Quelle fehlt: vendor/{name}")
        elif not zieldatei.is_file():
            befunde.append(f"{app}: fehlt: {name}")
        elif sha256(quelle) != sha256(zieldatei):
            befunde.append(f"{app}: abweichend: {name}")
    if ziel.is_dir():
        for datei in sorted(ziel.iterdir()):
            if datei.is_file() and datei.name not in erwartet:
                befunde.append(f"{app}: nicht im Vendor-Manifest: {datei.name}")
    return befunde


def schreibe(app: str) -> list[str]:
    """Spiegelt die kanonischen Dateien; entfernt nur überzählige Dateien."""
    ziel = ROOT / app / "vendor"
    ziel.mkdir(parents=True, exist_ok=True)
    erwartet = ZUORDNUNG[app]
    for name in erwartet:
        quelle = QUELLE / name
        if not quelle.is_file():
            raise SystemExit(f"Vendor-Quelle fehlt: {quelle}")
        zieldatei = ziel / name
        if not zieldatei.is_file() or sha256(quelle) != sha256(zieldatei):
            shutil.copyfile(quelle, zieldatei)
    for datei in sorted(ziel.iterdir()):
        if datei.is_file() and datei.name not in erwartet:
            datei.unlink()
    return unterschiede(app)


def main() -> int:
    ap = argparse.ArgumentParser(description="Vendor-Kopien mit vendor/ synchronisieren.")
    ap.add_argument("--check", action="store_true", help="nur prüfen, nichts schreiben")
    ap.add_argument("--write", action="store_true", help="Kopien aktualisieren")
    ap.add_argument("--app", choices=sorted(ZUORDNUNG), help="nur eine App")
    ap.add_argument(
        "--allow-missing",
        action="store_true",
        help="fehlende Kopien tolerieren (der Klon ist schlank, gebaut wird trotzdem)",
    )
    args = ap.parse_args()
    if args.check == args.write:
        ap.error("genau eines von --check oder --write angeben")

    apps = [args.app] if args.app else sorted(ZUORDNUNG)
    befunde: list[str] = []
    for app in apps:
        if args.write:
            befunde.extend(schreibe(app))
        else:
            befunde.extend(unterschiede(app))
    if args.check and args.allow_missing:
        # Nur fehlende Zielkopien sind harmlos — fehlende Quellen und
        # abweichende Bytes bleiben Fehler.
        befunde = [b for b in befunde if ": fehlt: " not in b]
    for befund in befunde:
        print(f"BEFUND: {befund}")
    if args.check:
        print(f"{len(apps)} App(s) geprüft, {len(befunde)} Befund(e)")
        return 1 if befunde else 0
    print(f"{len(apps)} App(s) synchronisiert, {len(befunde)} Restbefund(e)")
    return 1 if befunde else 0


if __name__ == "__main__":
    sys.exit(main())
