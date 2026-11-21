#!/usr/bin/env python3
"""Schreibt das Manifest fuer die amtliche MDG auf der Projektseite.

    python3 scripts/mdg_manifest.py packages/rules/NAFv4-ADMBw-MDG-2026.05.xml \
        --aus seite/admbw-extraktor/mdg/manifest.json

Das Manifest sagt dem Extraktor, welche Fassung die Projektseite bereithaelt
und wie ihre Pruefsumme lautet. Der Browser prueft damit die geladene Datei,
bevor er sie verarbeitet -- die Kette lautet: amtliche Quelle -> Waechter ->
Repository -> Projektseite -> Browser, und jede Stufe ist belegt.

Ausgabe ist deterministisch: gleiche Eingabe, gleiche Bytes (kein Zeitstempel).
Nur Standardbibliothek.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

#: Datei, die den aktuellen Stand im Repository benennt.
CURRENT = Path(__file__).resolve().parent.parent / "packages" / "rules" / "CURRENT"
#: Amtliche Quelle (Seite "Methode Architektur" beim BAAINBw).
QUELLE = (
    "https://www.bundeswehr.de/de/organisation/ausruestung-baainbw/"
    "vergabe/methode-architektur"
)


def version_aus_name(name: str) -> str:
    """Version aus dem Dateinamen, z. B. 2026.05 -> '2026.05'; sonst leer."""
    treffer = re.search(r"(\d{4}\.\d{2})", name)
    return treffer.group(1) if treffer else ""


def baue_manifest(xml: Path) -> dict:
    daten = xml.read_bytes()
    return {
        "datei": xml.name,
        "version": version_aus_name(xml.name),
        "bytes": len(daten),
        "sha256": hashlib.sha256(daten).hexdigest(),
        "quelle": QUELLE,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Manifest der amtlichen MDG schreiben")
    ap.add_argument("xml", type=Path, help="MDG-XML (oder ein Verzeichnis mit CURRENT)")
    ap.add_argument("--aus", type=Path, required=True, help="Zielpfad manifest.json")
    args = ap.parse_args()

    xml = args.xml
    if xml.is_dir():
        name = (xml / "CURRENT").read_text(encoding="utf-8").strip()
        xml = xml / name
    if not xml.is_file():
        raise SystemExit(f"MDG fehlt: {xml}")

    manifest = baue_manifest(xml)
    args.aus.parent.mkdir(parents=True, exist_ok=True)
    args.aus.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{args.aus} → {manifest['datei']} ({manifest['bytes']} Bytes, sha256 {manifest['sha256'][:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
