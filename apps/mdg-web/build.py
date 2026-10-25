#!/usr/bin/env python3
"""Liefert den vollständigen MDG-Browser-Parser aus.

    python3 apps/mdg-web/build.py

`index.html` ist der eigenständige Parser mit Datei-Upload, fünf Ansichten
(Stereotype, Topologie, Viewpoints, Tag-Typen, Stereotyp-Tags) und sechs
Downloads. Er wird unverändert nach `dist/EAM-MDG-Parser.html` kopiert — keine
zweite generierte Fassung, keine Abweichung zwischen Quelle und Auslieferung.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "index.html"
OUT = HERE / "dist" / "EAM-MDG-Parser.html"


def baue() -> Path:
    if not SRC.is_file():
        raise SystemExit(f"Quelle fehlt: {SRC}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(SRC.read_bytes())
    return OUT


if __name__ == "__main__":
    ziel = baue()
    print(f"{ziel} ({ziel.stat().st_size} Bytes)")
