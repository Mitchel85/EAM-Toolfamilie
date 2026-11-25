#!/usr/bin/env python3
"""Erzeugt docs/toolfamilie-tabelle.png -- aktuelle Gesamtuebersicht der EAM Toolfamilie.

Aufruf:
    python3 scripts/make_table_image.py
"""
from __future__ import annotations

import textwrap
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ZIEL = ROOT / "docs" / "toolfamilie-tabelle.png"

WEIT = 2000
HOCH = 1140

NAVY = (15, 29, 51)
HEAD_BG = (28, 39, 56)
TEXT = (30, 41, 59)
MUTED = (100, 116, 139)
LINIE = (226, 232, 240)
ALT_BG = (248, 250, 252)

_FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
_FONT_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def _pick(candidates: tuple[str, ...]) -> str:
    for p in candidates:
        if Path(p).is_file():
            return p
    raise FileNotFoundError(f"Keine Schriftart gefunden: {candidates}")


FONT_R = _pick(_FONT_REGULAR)
FONT_B = _pick(_FONT_BOLD)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_B if bold else FONT_R, size)


def _core_version() -> str:
    pyproject = ROOT / "packages" / "core" / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as h:
            return str(tomllib.load(h)["project"]["version"])
    return ""


ROWS = [
    (
        "EAM AI Suite",
        "Bauen, Chat & Weiterbau",
        "Aus Text, DOCX, PDF, Bild oder Tabelle MDG-geprüfte Modelle bauen, live in Explorer/Graph/QS ansehen, per Chat with Data befragen & per Sprache weiterbauen.",
        "Text, DOCX, PDF, Bild, MDG-XML, Startpaket",
        ".qea, .xmi, .json, ArchiMate .xml, Handbuch",
        "HTML / ASPX",
    ),
    (
        "EAM AI Suite Python",
        "CLI, WebUI & Batch",
        "Dieselbe Kette für Server & große Quellen (Batch/Stufen 1–4); WebUI (eam-ai serve) mit Live-Viewer, Chat with Data, NL-Änderung & Prosa-Weiterbau.",
        "Text, DOCX, PDF, Bild, CSV, MDG-XML, Startpaket",
        ".qea, .xmi, .json, ArchiMate .xml, Berichte",
        "CLI, WebUI, Docker",
    ),
    (
        "EAM Suite",
        "Prüfen & Bearbeiten (ohne KI)",
        "Bestehende Modelle offline laden, verschmelzen, analysieren, per Auto-QS gegen MDG prüfen und bearbeiten (kein Neuaufbau von null).",
        "eine oder mehrere .qea/.xmi/.json/.xml-Dateien",
        ".qea, .xmi, .json, ArchiMate .xml, PNG, XLSX",
        "HTML / ASPX / EN",
    ),
    (
        "EAM Analyzer",
        "Abfragen, Impact & QS",
        "Vorhandene Modelle gezielt befragen (Chat with Data), gegen MDG/ArchiMate prüfen sowie Impact-, Nachbarschafts- & Pfadanalysen fahren.",
        ".qea, .xmi, ArchiMate .xml, .json",
        "Antworten, QS- & Impact-Berichte",
        "Open WebUI, MCP",
    ),
    (
        "BPMN Studio",
        "Prozessarchitektur (L4)",
        "BPMN-2.0-Prozesse zeichnen, aus Text/Bild erfassen, gegen 15 L4-Regeln prüfen & ADMBw-konform inkl. Aktivitätsdiagramm exportieren.",
        "BPMN 2.0, Text, DOCX, PDF, Bild",
        ".bpmn, .qea, .xmi, .xml, .json, SVG, PNG",
        "HTML / ASPX / Py",
    ),
    (
        "ADMBw Extraktor",
        "MDG-Regelwerk",
        "Beliebige MDG-XML dynamisch auslesen: Stereotype, Topologie, Viewpoints & Tags durchsuchen und als 6 Markdown-Dateien oder JSON exportieren.",
        "MDG-XML (.xml / .mdg)",
        "6 Markdown-Dateien, rules.json",
        "HTML / Python",
    ),
    (
        "Sichten-Archiv",
        "Sichten & Layout (SHA-256)",
        "Diagrammsichten und Layout aus einer .qea bit-identisch (SHA-256) in ein .archiv auslagern und nach Pipeline-Läufen verlustfrei zurückspielen.",
        ".qea / .archiv",
        ".archiv / .qea (bit-identisch)",
        "HTML / ASPX / Py",
    ),
]


def main() -> int:
    img = Image.new("RGB", (WEIT, HOCH), "white")
    draw = ImageDraw.Draw(img)

    ver = _core_version()
    draw.text((76, 46), "EAM Toolfamilie", font=font(54, True), fill=NAVY)
    draw.text(
        (76, 114),
        "Sieben Werkzeuge für NAF 4 / UAF (MDG), ArchiMate 3.2 (Brücke) und BPMN 2.0 — lokal im Browser, CLI, WebUI & MCP",
        font=font(24),
        fill=MUTED,
    )
    if ver:
        draw.text((WEIT - 320, 62), f"Kern v{ver}", font=font(24, True), fill=MUTED)

    cols = [
        ("WERKZEUG", 76, 305),
        ("AUFGABE", 385, 710),
        ("EINGABE", 1105, 315),
        ("ERGEBNIS", 1430, 290),
        ("FORM", 1725, 195),
    ]
    top = 180
    hdr_h = 56
    draw.rectangle((76, top, WEIT - 76, top + hdr_h), fill=HEAD_BG)
    for title, x, _ in cols:
        draw.text((x + 14, top + 16), title, font=font(18, True), fill="white")

    y = top + hdr_h
    row_h = 118
    for idx, (name, sub, aufgabe, eingabe, ergebnis, form) in enumerate(ROWS):
        if idx % 2 == 1:
            draw.rectangle((76, y, WEIT - 76, y + row_h), fill=ALT_BG)
        draw.line((76, y + row_h, WEIT - 76, y + row_h), fill=LINIE, width=1)

        draw.text((90, y + 22), name, font=font(23, True), fill=NAVY)
        draw.text((90, y + 58), sub, font=font(17), fill=MUTED)

        for ci, (txt, wrap_w) in enumerate([(aufgabe, 60), (eingabe, 26), (ergebnis, 23), (form, 18)], start=1):
            x = cols[ci][1] + 14
            lines = textwrap.wrap(txt, width=wrap_w)[:4]
            ly = y + (16 if len(lines) >= 3 else 26)
            for line in lines:
                draw.text((x, ly), line, font=font(18), fill=TEXT)
                ly += 25
        y += row_h

    draw.text((76, HOCH - 52), "Lokal im Browser (ohne Server), auf der Kommandozeile, als Webdienst oder per MCP.", font=font(18), fill=MUTED)
    draw.text((WEIT - 410, HOCH - 52), "mitchel85.github.io/EAM-Toolfamilie", font=font(18, True), fill=NAVY)

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    img.save(ZIEL, optimize=True)
    print(f"geschrieben: {ZIEL} ({ZIEL.stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
