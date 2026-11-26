#!/usr/bin/env python3
"""Erzeugt die aktuelle LinkedIn-Übersichtsgrafik der EAM Toolfamilie.

Schreibt nach ``docs/eam-toolfamilie-linkedin.png`` und synchronisiert optional
die LinkedIn-Arbeitskopie unter ``../buchprojekt/EAM_TOOLFAMILIE_LINKEDIN.png``,
falls vorhanden.
"""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ZIEL = ROOT / "docs" / "eam-toolfamilie-linkedin.png"
LINKEDIN_COPY = ROOT.parent / "buchprojekt" / "EAM_TOOLFAMILIE_LINKEDIN.png"

W, H = 1600, 900

BG = (13, 24, 38)
CARD_BG = (19, 34, 54)
CARD_BORDER = (43, 66, 94)
BLUE = (14, 165, 233)
GOLD = (245, 158, 11)
TEXT = (241, 245, 249)
MUTED = (176, 194, 214)
PILL_BG = (22, 42, 66)

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


def _pick(cands: tuple[str, ...]) -> str:
    for p in cands:
        if Path(p).is_file():
            return p
    raise FileNotFoundError(f"Keine Schriftart gefunden: {cands}")


FR, FB = _pick(_FONT_REGULAR), _pick(_FONT_BOLD)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FB if bold else FR, size)


def draw_poly_bg(draw: ImageDraw.ImageDraw) -> None:
    polys = [
        ([(0, 0), (420, 0), (260, 320), (0, 240)], (16, 29, 46)),
        ([(420, 0), (960, 0), (740, 290), (260, 320)], (12, 23, 37)),
        ([(960, 0), (1600, 0), (1600, 340), (1140, 280)], (17, 32, 50)),
        ([(0, 240), (260, 320), (180, 720), (0, 620)], (11, 21, 34)),
        ([(1140, 280), (1600, 340), (1600, 900), (1240, 780)], (15, 28, 44)),
        ([(180, 720), (760, 660), (1240, 780), (1600, 900), (0, 900)], (10, 19, 31)),
    ]
    for pts, color in polys:
        draw.polygon(pts, fill=color)
    # Feine Top-Akzentlinie
    for x in range(W):
        t = x / max(1, W - 1)
        r = int(14 + (245 - 14) * t)
        g = int(165 + (158 - 165) * t)
        b = int(233 + (11 - 233) * t)
        draw.line((x, 0, x, 6), fill=(r, g, b))


def draw_pill(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    *,
    border: tuple[int, int, int] = CARD_BORDER,
    fg: tuple[int, int, int] = TEXT,
    fsize: int = 18,
) -> int:
    f = font(fsize, True)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pw, ph = tw + 28, th + 18
    draw.rounded_rectangle((x, y, x + pw, y + ph), radius=10, fill=PILL_BG, outline=border, width=2)
    draw.text((x + pw / 2, y + ph / 2), text, font=f, fill=fg, anchor="mm")
    return pw


CARDS = [
    (
        "EAM AI Suite",
        "HTML & Python",
        BLUE,
        "KI-Pipelines (HTML & WebUI): MDG-geprüfte Modelle iterativ bauen, live prüfen (Diff/Undo, Auto-Repair, Textabdeckung), befragen & weiterbauen.",
    ),
    (
        "EAM Suite",
        "HTML · ohne KI",
        BLUE,
        "Bestehende Modelle offline laden, verschmelzen, vergleichen (Diff & Undo), regelbasiert reparieren & gegen MDG/ArchiMate-Matrix prüfen.",
    ),
    (
        "EAM Analyzer",
        "MCP · Open WebUI",
        BLUE,
        "Modelle (.qea, .xmi, ArchiMate, .json) per Open WebUI oder Stdlib-MCP (eam-ai mcp) befragen, validieren & Impact-/Pfadanalysen fahren.",
    ),
    (
        "BPMN Studio",
        "HTML & Python",
        GOLD,
        "Prozesse zeichnen, gegen 15 L4-Regeln prüfen, mit L3-Katalog (GUIDs/Represents) verknüpfen & nach .qea/.xmi/.xml/.json exportieren.",
    ),
    (
        "ADMBw Extraktor",
        "HTML & Python",
        GOLD,
        "Beliebige MDG-XML dynamisch durchsuchen und Stereotype, Beziehungen, Viewpoints & Tags als 6 Markdown-Dateien oder JSON exportieren.",
    ),
    (
        "Sichten-Archiv",
        "HTML & Python",
        GOLD,
        "Diagrammsichten & Layout aus .qea mit SHA-256-Prüfsumme auslagern und nach Pipeline-Läufen verlustfrei zurückspielen.",
    ),
]


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_poly_bg(draw)

    draw.text((64, 52), "OPEN-SOURCE EAM · NAF 4 / UAF · ADMBW · ARCHIMATE · BPMN 2.0", font=font(18, True), fill=GOLD)
    draw.text((64, 86), "EAM Tool-Familie", font=font(56, True), fill=TEXT)
    draw.text(
        (64, 158),
        "Sechs eigenständige Werkzeuge für Architekturmodelle — lokal im Browser, als Python-CLI/WebUI oder per MCP.",
        font=font(22),
        fill=MUTED,
    )

    # Top-right Format-Pills
    px = 1090
    for lbl, brd, col in [(".qea", BLUE, TEXT), (".xmi", BLUE, TEXT), (".json", BLUE, TEXT), ("ArchiMate .xml", GOLD, GOLD)]:
        px += draw_pill(draw, px, 56, lbl, border=brd, fg=col, fsize=16) + 10
    px2 = 1230
    for lbl, brd, col in [("NAF 4 / UAF", GOLD, GOLD), ("BPMN 2.0", BLUE, TEXT)]:
        px2 += draw_pill(draw, px2, 108, lbl, border=brd, fg=col, fsize=16) + 10

    # 3x2 Karten
    gap_x, gap_y = 26, 26
    card_w = (W - 128 - 2 * gap_x) // 3
    card_h = 250
    start_y = 250

    for idx, (title, badge, accent, body) in enumerate(CARDS):
        col = idx % 3
        row = idx // 3
        x0 = 64 + col * (card_w + gap_x)
        y0 = start_y + row * (card_h + gap_y)
        draw.rounded_rectangle((x0, y0, x0 + card_w, y0 + card_h), radius=16, fill=CARD_BG, outline=CARD_BORDER, width=2)
        draw.rounded_rectangle((x0 + 2, y0 + 2, x0 + card_w - 2, y0 + 8), radius=4, fill=accent)

        draw.text((x0 + 26, y0 + 28), title, font=font(27, True), fill=TEXT)
        bf = font(15, True)
        bb = draw.textbbox((0, 0), badge, font=bf)
        bw, bh = bb[2] - bb[0] + 24, bb[3] - bb[1] + 16
        bx = x0 + card_w - 26 - bw
        by = y0 + 28
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=8, fill=PILL_BG, outline=accent, width=2)
        draw.text((bx + bw / 2, by + bh / 2), badge, font=bf, fill=accent if accent == GOLD else TEXT, anchor="mm")

        ly = y0 + 84
        for line in textwrap.wrap(body, width=42)[:5]:
            draw.text((x0 + 26, ly), line, font=font(19), fill=MUTED)
            ly += 29

    # Footer pills
    fx = 64
    for lbl in ("Open Source · MIT", "Browser, CLI, WebUI & MCP", "Live-Viewer · Chat with Data · Weiterbau"):
        fx += draw_pill(draw, fx, H - 78, lbl, border=CARD_BORDER, fg=TEXT, fsize=16) + 12
    draw.text((W - 430, H - 68), "mitchel85.github.io/EAM-Toolfamilie", font=font(21, True), fill=GOLD)

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    img.save(ZIEL, optimize=True)
    print(f"geschrieben: {ZIEL} ({ZIEL.stat().st_size} Bytes)")
    if LINKEDIN_COPY.parent.is_dir():
        shutil.copyfile(ZIEL, LINKEDIN_COPY)
        print(f"synchronisiert: {LINKEDIN_COPY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
