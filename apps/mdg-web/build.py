#!/usr/bin/env python3
"""Liefert den vollständigen MDG-Browser-Parser aus.

    python3 apps/mdg-web/build.py

`index.html` ist der eigenständige Parser mit Datei-Upload, fünf Ansichten
(Stereotype, Topologie, Viewpoints, Tag-Typen, Stereotyp-Tags) und sechs
Downloads.

Beim Bauen wird zusätzlich der Master-Prompt des ehemaligen ADMBw-Extraktors
(`apps/admbw-extractor/ADMBw-Prompt.md`) an der Stelle `{{MASTER_PROMPT}}`
eingesetzt. Es gibt genau eine Quelle für den Text; die Auslieferung wird
erzeugt, nicht gepflegt. Fehlt die Vorlage, bricht der Bau ab — sonst wäre der
Knopf in der ausgelieferten Datei wirkungslos.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "index.html"
OUT = HERE / "dist" / "EAM-MDG-Parser.html"
PROMPT = HERE.parent / "admbw-extractor" / "ADMBw-Prompt.md"
PLATZHALTER = "{{MASTER_PROMPT}}"


def lade_prompt() -> str:
    if not PROMPT.is_file():
        raise SystemExit(f"Master-Prompt fehlt: {PROMPT}")
    text = PROMPT.read_text(encoding="utf-8").strip("\n")
    # "</script>" im Text würde den Block vorzeitig beenden.
    if "</script" in text.lower():
        raise SystemExit(f"Master-Prompt enthält '</script': {PROMPT}")
    return text


def baue() -> Path:
    if not SRC.is_file():
        raise SystemExit(f"Quelle fehlt: {SRC}")
    html = SRC.read_text(encoding="utf-8")
    if PLATZHALTER not in html:
        raise SystemExit(f"Platzhalter {PLATZHALTER} fehlt in {SRC}")
    html = html.replace(PLATZHALTER, lade_prompt(), 1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    ziel = baue()
    print(f"{ziel} ({ziel.stat().st_size} Bytes)")
