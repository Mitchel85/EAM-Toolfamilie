#!/usr/bin/env python3
"""Erzeugt docs/workflow-abdeckung.png -- die Matrix 'Ein Workflow, sieben Werkzeuge'.

Reine Darstellung: Die Zeilen und Symbole stehen unten in ``ZEILEN``. Wird ein
Werkzeug geaendert, nur hier anpassen und das Bild neu erzeugen:

    python3 scripts/make_workflow_image.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ZIEL = ROOT / "docs" / "workflow-abdeckung.png"

WEIT = 1920
HOCH = 1220

NAVY = (11, 42, 74)
TEXT = (43, 61, 86)
MUTED = (100, 116, 139)
LINIE = (226, 232, 240)
GRUEN = (46, 125, 50)
GELB = (242, 169, 0)
GRAU = (148, 163, 184)
VIOLETT = (124, 58, 237)

_FONT_CANDIDATES_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
_FONT_CANDIDATES_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def _pick_font(candidates: tuple[str, ...]) -> str:
    for path in candidates:
        if Path(path).is_file():
            return path
    raise FileNotFoundError(f"Keine passende Schriftart gefunden: {candidates}")


SCHRIFT = _pick_font(_FONT_CANDIDATES_REGULAR)
SCHRIFT_FETT = _pick_font(_FONT_CANDIDATES_BOLD)


def font(groesse: int, fett: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(SCHRIFT_FETT if fett else SCHRIFT, groesse)


SPALTEN = [
    ("1", "MDG", "einlesen"),
    ("2", "Startpaket", "GUID-treu"),
    ("3", "Prosa", "multimodal"),
    ("4", "Bauen &", "Weiterbau"),
    ("5", "Ansehen", "Viewer & QS"),
    ("6", "Bearbeiten", "im Modell"),
    ("7", "Export", "4 Formate"),
]
ZUSATZ = ("zusätzlich", "Chat with Data", "Fragen & Rückweg")

#: (Titel, Untertitel, sieben Schritte, Chat/Rueckweg)
#: "voll", "teil", "nein", "chat"
ZEILEN = [
    ("EAM AI Suite", "HTML · 9.1 · Bauen, Diff/Undo, Auto-Repair & Chat",
     ["voll", "voll", "voll", "voll", "voll", "voll", "voll"], "chat"),
    ("EAM AI Suite Python", "CLI, WebUI & Stdlib-MCP · Diff, Repair & Weiterbau",
     ["voll", "voll", "voll", "voll", "voll", "voll", "voll"], "chat"),
    ("EAM Suite", "HTML · 8.6 · ohne KI (Auto-QS, Matrix, Diff & Repair)",
     ["voll", "voll", "nein", "nein", "voll", "voll", "voll"], "nein"),
    ("Sichten-Archiv", "HTML · 1.0 + Python · SHA-256 Sichten-Transfer",
     ["nein", "nein", "nein", "nein", "nein", "teil", "teil"], "nein"),
    ("BPMN Studio", "HTML + Python · BPMN 2.0, L4-Regeln & L3-Katalogbrücke",
     ["nein", "teil", "voll", "voll", "voll", "voll", "voll"], "nein"),
    ("ADMBw Extraktor", "HTML + Python · MDG-Regelwerk & 6 Exporte",
     ["voll", "nein", "nein", "nein", "nein", "nein", "teil"], "nein"),
    ("EAM Analyzer", "Open WebUI + MCP · Abfragen, Impact, Diff & QS",
     ["voll", "nein", "nein", "nein", "voll", "nein", "nein"], "chat"),
]


def symbol(draw: ImageDraw.ImageDraw, x: int, y: int, art: str) -> None:
    if art == "voll":
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill=GRUEN)
    elif art == "teil":
        draw.pieslice((x - 15, y - 15, x + 15, y + 15), 180, 360, fill=GELB)
        draw.line((x - 15, y, x + 15, y), fill=(255, 255, 255), width=2)
    elif art == "chat":
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill=VIOLETT)
    else:
        draw.line((x - 14, y, x + 14, y), fill=GRAU, width=4)


def main() -> int:
    bild = Image.new("RGB", (WEIT, HOCH), "white")
    draw = ImageDraw.Draw(bild)

    draw.text((80, 48), "EAM TOOLFAMILIE", font=font(22, True), fill=MUTED)
    draw.text((80, 82), "Ein Workflow, sieben Werkzeuge", font=font(50, True), fill=NAVY)
    draw.text(
        (80, 148),
        "Abdeckung der sieben Workflow-Schritte sowie Chat with Data (Fragen & Rückweg).",
        font=font(24),
        fill=TEXT,
    )

    links, rechts = 80, WEIT - 80
    spalten_start = 560
    spalten_breite = 160
    kopf_y = 236

    for i, (nummer, titel, unter) in enumerate(SPALTEN):
        x = spalten_start + i * spalten_breite
        draw.text((x, kopf_y), nummer, font=font(19, True), fill=MUTED)
        draw.text((x, kopf_y + 25), titel, font=font(22, True), fill=NAVY)
        draw.text((x, kopf_y + 54), unter, font=font(17), fill=MUTED)

    x_extra = spalten_start + len(SPALTEN) * spalten_breite + 10
    draw.text((x_extra, kopf_y), ZUSATZ[0], font=font(18, True), fill=VIOLETT)
    draw.text((x_extra, kopf_y + 25), ZUSATZ[1], font=font(21, True), fill=NAVY)
    draw.text((x_extra, kopf_y + 54), ZUSATZ[2], font=font(16), fill=MUTED)

    zeilen_start = 342
    zeilen_hoehe = 104
    for r, (titel, unter, schritte, chat_art) in enumerate(ZEILEN):
        y = zeilen_start + r * zeilen_hoehe
        mitte = y + zeilen_hoehe // 2 - 4
        if r:
            draw.line((links, y - 6, rechts, y - 6), fill=LINIE, width=1)
        draw.text((links, y + 16), titel, font=font(25, True), fill=NAVY)
        draw.text((links, y + 50), unter, font=font(17), fill=MUTED)
        for i, art in enumerate(schritte):
            symbol(draw, spalten_start + i * spalten_breite + 56, mitte, art)
        symbol(draw, x_extra + 66, mitte, chat_art)

    legende_y = 1104
    draw.line((links, legende_y - 26, rechts, legende_y - 26), fill=LINIE, width=1)
    symbol(draw, 95, legende_y, "voll")
    draw.text((120, legende_y - 12), "vollständig unterstützt", font=font(19), fill=TEXT)
    symbol(draw, 390, legende_y, "teil")
    draw.text((415, legende_y - 12), "teilweise / spezialisiert", font=font(19), fill=TEXT)
    symbol(draw, 680, legende_y, "nein")
    draw.text((705, legende_y - 12), "nicht enthalten", font=font(19), fill=TEXT)
    symbol(draw, 910, legende_y, "chat")
    draw.text((935, legende_y - 12), "Chat with Data (Fragen ans Modell & Rückweg)", font=font(19), fill=TEXT)

    draw.text(
        (80, 1146),
        "EAM AI Suite (HTML & Python WebUI) bieten nach dem Bau sofortige Live-Ansicht, Chat with Data sowie iterativen Weiterbau per Sprache/Prosa.",
        font=font(17),
        fill=MUTED,
    )
    draw.text(
        (80, 1174),
        "EAM Suite (ohne KI) lädt, verschmilzt, analysiert, prüft (Auto-QS) und bearbeitet bestehende Modelle — bewusst kein Neuaufbau von null.",
        font=font(17),
        fill=MUTED,
    )

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ZIEL, optimize=True)
    print(f"geschrieben: {ZIEL} ({ZIEL.stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
