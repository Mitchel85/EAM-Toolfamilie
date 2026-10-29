#!/usr/bin/env python3
"""Erzeugt docs/workflow-abdeckung.png -- die Matrix 'Ein Workflow, fünf Werkzeuge'.

Reine Darstellung: Die Zeilen und Symbole stehen unten in ``ZEILEN``. Wird ein
Werkzeug ersetzt, nur hier aendern und das Bild neu erzeugen:

    python3 scripts/make_workflow_image.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ZIEL = ROOT / "docs" / "workflow-abdeckung.png"

WEIT = 1920
HOCH = 1080

NAVY = (11, 42, 74)
TEXT = (43, 61, 86)
MUTED = (100, 116, 139)
LINIE = (226, 232, 240)
PANEL = (248, 250, 252)
GRUEN = (46, 125, 50)
GELB = (242, 169, 0)
GRAU = (148, 163, 184)
VIOLETT = (124, 58, 237)

SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SCHRIFT_FETT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(groesse: int, fett: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(SCHRIFT_FETT if fett else SCHRIFT, groesse)


SPALTEN = [
    ("1", "MDG", "einlesen"),
    ("2", "Startpaket", "übernehmen"),
    ("3", "Prosa", "einlesen"),
    ("4", "Bauen", "und prüfen"),
    ("5", "Ansehen", "Viewer"),
    ("6", "Bearbeiten", "im Modell"),
    ("7", "Ergebnis", ".qea-Datei"),
]
ZUSATZ = ("zusätzlich", "Rückweg-Test", "nicht Teil des Ablaufs")

#: (Titel, Untertitel, sieben Schritte, Rückweg)
#: "voll", "teil", "nein", "test"
ZEILEN = [
    ("EAM AI Suite", "HTML · 9.1 · vollständiger Ablauf",
     ["voll"] * 7, "test"),
    ("EAM AI Suite Python", "CLI/Webdienst · vollständiger Ablauf",
     ["voll", "voll", "voll", "voll", "teil", "voll", "voll"], "test"),
    ("EAM Suite", "HTML · 8.4 · ohne KI",
     ["nein", "teil", "nein", "teil", "voll", "voll", "voll"], "nein"),
    ("EAM MDG Parser", "HTML + Python",
     ["voll", "nein", "nein", "nein", "nein", "nein", "nein"], "nein"),
    ("EAM QEA Analyzer", "Open WebUI + MCP",
     ["nein", "nein", "nein", "nein", "teil", "nein", "nein"], "nein"),
]


def symbol(draw: ImageDraw.ImageDraw, x: int, y: int, art: str) -> None:
    if art == "voll":
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill=GRUEN)
    elif art == "teil":
        draw.pieslice((x - 15, y - 15, x + 15, y + 15), 180, 360, fill=GELB)
        draw.line((x - 15, y, x + 15, y), fill=(255, 255, 255), width=2)
    elif art == "test":
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), outline=VIOLETT, width=4)
    else:
        draw.line((x - 14, y, x + 14, y), fill=GRAU, width=4)


def main() -> int:
    bild = Image.new("RGB", (WEIT, HOCH), "white")
    draw = ImageDraw.Draw(bild)

    draw.text((80, 54), "EAM TOOLFAMILIE", font=font(22, True), fill=MUTED)
    draw.text((80, 90), "Ein Workflow, fünf Werkzeuge", font=font(52, True), fill=NAVY)
    draw.text((80, 160), "Abdeckung der sieben Workflow-Schritte.",
              font=font(25), fill=TEXT)

    links, rechts = 80, WEIT - 80
    spalten_start = 545
    spalten_breite = 168
    zusatz_breite = 175

    kopf_y = 270
    for i, (nummer, titel, unter) in enumerate(SPALTEN):
        x = spalten_start + i * spalten_breite
        draw.text((x, kopf_y), nummer, font=font(20, True), fill=MUTED)
        draw.text((x, kopf_y + 26), titel, font=font(23, True), fill=NAVY)
        draw.text((x, kopf_y + 56), unter, font=font(18), fill=MUTED)

    x_extra = spalten_start + len(SPALTEN) * spalten_breite + 12
    draw.text((x_extra, kopf_y), ZUSATZ[0], font=font(18, True), fill=VIOLETT)
    draw.text((x_extra, kopf_y + 26), ZUSATZ[1], font=font(20, True), fill=NAVY)
    draw.text((x_extra, kopf_y + 54), ZUSATZ[2], font=font(16), fill=MUTED)

    zeilen_start = 390
    zeilen_hoehe = 112
    for r, (titel, unter, schritte, rueckweg) in enumerate(ZEILEN):
        y = zeilen_start + r * zeilen_hoehe
        mitte = y + zeilen_hoehe // 2 - 6
        if r:
            draw.line((links, y - 8, rechts, y - 8), fill=LINIE, width=1)
        draw.text((links, y + 18), titel, font=font(26, True), fill=NAVY)
        draw.text((links, y + 52), unter, font=font(18), fill=MUTED)
        for i, art in enumerate(schritte):
            symbol(draw, spalten_start + i * spalten_breite + 62, mitte, art)
        symbol(draw, x_extra + 62, mitte, rueckweg)

    legende_y = 985
    symbol(draw, 92, legende_y, "voll")
    draw.text((118, legende_y - 12), "unterstützt den Schritt", font=font(19), fill=TEXT)
    symbol(draw, 400, legende_y, "teil")
    draw.text((426, legende_y - 12), "teilweise unterstützt", font=font(19), fill=TEXT)
    symbol(draw, 668, legende_y, "nein")
    draw.text((694, legende_y - 12), "nicht enthalten", font=font(19), fill=TEXT)
    symbol(draw, 900, legende_y, "test")
    draw.text((926, legende_y - 12), "Rückweg-Test (nicht Teil des Ablaufs)",
              font=font(19), fill=TEXT)

    draw.text((80, 1032),
              "EAM QEA Analyzer beantwortet Fragen zum Modell (Open WebUI/MCP) — "
              "kein eigener HTML-Viewer; die EAM Suite übernimmt das Ansehen.",
              font=font(17), fill=MUTED)
    draw.text((80, 1056),
              "EAM MDG Parser: HTML-Variante und Python-Variante (dieselbe Datei wie im Python-ZIP).",
              font=font(17), fill=MUTED)

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ZIEL, optimize=True)
    print(f"geschrieben: {ZIEL} ({ZIEL.stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
