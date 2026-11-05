"""SVG- und PNG-Export ohne Browser.

Beide Ausgaben sind deterministisch: keine Zeitstempel, keine Zufallswerte,
keine Kennungen aus ``id()``. Gleiches Modell, gleiche Bytes -- das prueft
``tests/bpmn/test_exporte.py``.

PNG entsteht in dieser Reihenfolge:

1. ``cairosvg`` (falls installiert) -- beste Qualitaet,
2. ``rsvg-convert`` (falls im Pfad),
3. ``Pillow`` (falls installiert),
4. eingebauter Rasterer (nur Standardbibliothek) -- zeichnet Rechtecke,
   Rauten, Kreise, Linien und Beschriftungen aus den Modellgeometrien.

Der eingebaute Rasterer ist der Rueckfall, der immer funktioniert; er ist
bewusst schlicht (5x7-Bitmapschrift), aber vollstaendig aus dem Modell
abgeleitet.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Iterable, Protocol

from . import modell as m


class Zeichner(Protocol):
    """Was die gemeinsame Zeichenlogik von einem Ausgabegeraet braucht."""

    def rechteck(
        self, x: float, y: float, w: float, h: float, farbe: str, rahmen: str, dicke: int = 1
    ) -> None: ...

    def linie(self, punkte: list[tuple[float, float]], farbe: str, dicke: int = 1) -> None: ...

    def kreis(
        self, cx: float, cy: float, r: float, farbe: str, rahmen: str, dicke: int = 1
    ) -> None: ...

    def raute(
        self, cx: float, cy: float, hx: float, hy: float, farbe: str, rahmen: str, dicke: int = 1
    ) -> None: ...

    def text(self, x: float, y: float, text: str, groesse: int, farbe: str) -> None: ...

#: Farben (zurueckhaltend, druckbar).
FARBE_HINTERGRUND = "#ffffff"
FARBE_RAHMEN = "#3b4a5a"
FARBE_POOL = "#f4f6f9"
FARBE_LANE = "#ffffff"
FARBE_TASK = "#eef3f8"
FARBE_TASK_RAHMEN = "#2f5d8a"
FARBE_EREIGNIS = "#ffffff"
FARBE_GATEWAY = "#fdf6e3"
FARBE_DATEN = "#f7f2e8"
FARBE_TEXT = "#1f2933"
FARBE_LEISE = "#6b7785"
FARBE_FLUSS = "#33475b"

SCHRIFT = "Segoe UI, Helvetica, Arial, sans-serif"
#: Grobe Zeichenbreite fuer den Umbruch (Anteil der Schriftgroesse).
ZEICHENBREITE = 0.55


def _f(wert: float) -> str:
    """Feste Schreibweise fuer SVG-Koordinaten."""
    text = f"{wert:.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# --------------------------------------------------------------------------
# Geometrie
# --------------------------------------------------------------------------


def _formen(modell: m.Modell) -> dict[str, m.Begrenzung]:
    ergebnis: dict[str, m.Begrenzung] = {}
    for diagramm in modell.diagramme:
        for form in diagramm.formen:
            ergebnis.setdefault(form.element_ref, form.begrenzung)
    for knoten in modell.knoten.values():
        if knoten.begrenzung is not None:
            ergebnis.setdefault(knoten.id, knoten.begrenzung)
    for daten in modell.daten.values():
        if daten.begrenzung is not None:
            ergebnis.setdefault(daten.id, daten.begrenzung)
    for teilnehmer in modell.alle_teilnehmer():
        if teilnehmer.begrenzung is not None:
            ergebnis.setdefault(teilnehmer.id, teilnehmer.begrenzung)
    for prozess in modell.prozesse.values():
        for lane in prozess.alle_lanes():
            if lane.begrenzung is not None:
                ergebnis.setdefault(lane.id, lane.begrenzung)
    return ergebnis


def _kanten(modell: m.Modell) -> dict[str, list[m.Punkt]]:
    ergebnis: dict[str, list[m.Punkt]] = {}
    for diagramm in modell.diagramme:
        for kante in diagramm.kanten:
            if kante.wegpunkte:
                ergebnis.setdefault(kante.element_ref, kante.wegpunkte)
    for fluss in modell.fluesse.values():
        if fluss.wegpunkte:
            ergebnis.setdefault(fluss.id, fluss.wegpunkte)
    return ergebnis


def _inhalt(modell: m.Modell) -> tuple[float, float, float, float]:
    formen = _formen(modell)
    punkte: list[m.Begrenzung] = list(formen.values())
    for weg in _kanten(modell).values():
        for punkt in weg:
            punkte.append(m.Begrenzung(punkt.x, punkt.y, 0.0, 0.0))
    if not punkte:
        return 0.0, 0.0, 400.0, 200.0
    links = min(b.x for b in punkte)
    oben = min(b.y for b in punkte)
    rechts = max(b.rechts for b in punkte)
    unten = max(b.unten for b in punkte)
    return links, oben, rechts - links, unten - oben


def _umbruch(text: str, breite: float, groesse: float) -> list[str]:
    """Zeilenumbruch an Wortgrenzen, deterministisch und ohne Messung."""
    if not text:
        return []
    zeichen = max(4, int(breite / (groesse * ZEICHENBREITE)))
    zeilen: list[str] = []
    aktuell = ""
    for wort in str(text).split():
        kandidat = f"{aktuell} {wort}".strip()
        if len(kandidat) <= zeichen:
            aktuell = kandidat
            continue
        if aktuell:
            zeilen.append(aktuell)
        while len(wort) > zeichen:
            zeilen.append(wort[:zeichen])
            wort = wort[zeichen:]
        aktuell = wort
    if aktuell:
        zeilen.append(aktuell)
    return zeilen


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------


def svg_text(modell: m.Modell) -> str:
    """Modell als SVG-Einzeldatei."""
    links, oben, breite, hoehe = _inhalt(modell)
    rand = 30.0
    x0 = links - rand
    y0 = oben - rand
    w = breite + 2 * rand
    h = hoehe + 2 * rand
    formen = _formen(modell)
    kanten = _kanten(modell)

    teile: list[str] = []
    teile.append('<?xml version="1.0" encoding="UTF-8"?>')
    teile.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{_f(w)}" height="{_f(h)}" viewBox="{_f(x0)} {_f(y0)} {_f(w)} {_f(h)}" '
        f'role="img" aria-label="{_esc(modell.name or "BPMN-Prozess")}">'
    )
    teile.append("  <title>" + _esc(modell.name or "BPMN-Prozess") + "</title>")
    teile.append("  <defs>")
    teile.append(
        '    <marker id="pfeil" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="' + FARBE_FLUSS + '"/></marker>'
    )
    teile.append(
        '    <marker id="pfeil-offen" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="1" markerHeight="1" orient="auto-start-reverse" markerUnits="strokeWidth">'
        '<path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="' + FARBE_FLUSS
        + '" stroke-width="1.5"/></marker>'
    )
    teile.append("  </defs>")
    teile.append(f'  <rect x="{_f(x0)}" y="{_f(y0)}" width="{_f(w)}" height="{_f(h)}" fill="{FARBE_HINTERGRUND}"/>')

    # 1. Pools
    for teilnehmer in modell.alle_teilnehmer():
        b = formen.get(teilnehmer.id) or teilnehmer.begrenzung
        if b is None:
            continue
        teile.append(
            f'  <rect x="{_f(b.x)}" y="{_f(b.y)}" width="{_f(b.breite)}" height="{_f(b.hoehe)}" '
            f'rx="0" fill="{FARBE_POOL}" stroke="{FARBE_RAHMEN}" stroke-width="1.5"/>'
        )

    # 2. Lanes
    for prozess in modell.prozesse.values():
        for lane in prozess.alle_lanes():
            b = formen.get(lane.id) or lane.begrenzung
            if b is None:
                continue
            teile.append(
                f'  <rect x="{_f(b.x)}" y="{_f(b.y)}" width="{_f(b.breite)}" height="{_f(b.hoehe)}" '
                f'fill="{FARBE_LANE}" fill-opacity="0.6" stroke="{FARBE_RAHMEN}" stroke-width="1"/>'
            )
            teile.append(_text_mehrzeilig(lane.name, b.x + 8, b.y + 18, 12, max_breite=b.breite - 16))

    # 3. Kanten
    for fluss in modell.fluesse.values():
        weg = kanten.get(fluss.id)
        if not weg:
            continue
        teile.append(_pfad(fluss, weg))
        if fluss.name:
            treffer = weg[len(weg) // 2]
            teile.append(_etikett(fluss.name, treffer.x, treffer.y - 6, 11))

    # 4. Datenobjekte
    for daten in modell.daten.values():
        b = formen.get(daten.id) or daten.begrenzung
        if b is None:
            continue
        if daten.art == "text_annotation":
            teile.append(
                f'  <path d="M {_f(b.x)} {_f(b.y)} h 12 M {_f(b.x)} {_f(b.y)} '
                f'v {_f(b.hoehe)} h 12" fill="none" stroke="{FARBE_LEISE}" stroke-width="1"/>'
            )
            teile.append(_text_mehrzeilig(daten.name, b.x + 16, b.y + 14, 12, max_breite=b.breite - 16))
            continue
        teile.append(
            f'  <path d="M {_f(b.x)} {_f(b.y)} h {_f(b.breite - 12)} l 12 12 '
            f'v {_f(b.hoehe - 12)} h {_f(-b.breite)} z" fill="{FARBE_DATEN}" '
            f'stroke="{FARBE_RAHMEN}" stroke-width="1"/>'
        )
        teile.append(_text_mehrzeilig(daten.name, b.x + 6, b.y + 16, 11, max_breite=b.breite - 12))

    # 5. Knoten
    for knoten in modell.alle_knoten():
        b = formen.get(knoten.id) or knoten.begrenzung
        if b is None:
            continue
        teile.append(_knoten(knoten, b))

    teile.append("</svg>")
    return "\n".join(teile) + "\n"


def _pfad(fluss: m.Fluss, weg: list[m.Punkt]) -> str:
    punkte = " ".join(f"{_f(p.x)},{_f(p.y)}" for p in weg)
    if fluss.art == "sequence_flow":
        return (
            f'  <polyline points="{punkte}" fill="none" stroke="{FARBE_FLUSS}" '
            f'stroke-width="1.5" marker-end="url(#pfeil)"/>'
        )
    if fluss.art == "message_flow":
        return (
            f'  <polyline points="{punkte}" fill="none" stroke="{FARBE_FLUSS}" '
            f'stroke-width="1.2" stroke-dasharray="6 4" marker-end="url(#pfeil-offen)"/>'
        )
    return (
        f'  <polyline points="{punkte}" fill="none" stroke="{FARBE_LEISE}" '
        f'stroke-width="1" stroke-dasharray="2 3"/>'
    )


def _knoten(knoten: m.Knoten, b: m.Begrenzung) -> str:
    if knoten.art in m.EREIGNIS_ARTEN:
        r = min(b.breite, b.hoehe) / 2.0
        cx, cy = b.mitte_x, b.mitte_y
        dicke = "3" if knoten.ist_ende else "1.5"
        teile = [
            f'  <circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="{FARBE_EREIGNIS}" '
            f'stroke="{FARBE_RAHMEN}" stroke-width="{dicke}"/>'
        ]
        if knoten.art.startswith("intermediate"):
            teile.append(
                f'  <circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r - 4)}" fill="none" '
                f'stroke="{FARBE_RAHMEN}" stroke-width="1"/>'
            )
        if knoten.ist_ende:
            teile.append(
                f'  <circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r - 4)}" fill="{FARBE_RAHMEN}"/>'
            )
        if knoten.ereignis_definition == "message":
            teile.append(
                f'  <path d="M {_f(cx - 8)} {_f(cy - 5)} h 16 v 10 h -16 z M {_f(cx - 8)} {_f(cy - 5)} '
                f'l 8 6 l 8 -6" fill="none" stroke="{FARBE_RAHMEN}" stroke-width="1"/>'
            )
        elif knoten.ereignis_definition == "timer":
            teile.append(
                f'  <circle cx="{_f(cx)}" cy="{_f(cy)}" r="8" fill="none" stroke="{FARBE_RAHMEN}" stroke-width="1"/>'
                f'<path d="M {_f(cx)} {_f(cy)} v -5 M {_f(cx)} {_f(cy)} h 4" stroke="{FARBE_RAHMEN}" stroke-width="1"/>'
            )
        return "\n".join(teile) + "\n" + _text_mehrzeilig(
            knoten.name, b.x - 10, b.unten + 14, 11, max_breite=b.breite + 60, zentriert=b.mitte_x
        )

    if knoten.ist_gateway:
        cx, cy = b.mitte_x, b.mitte_y
        hx, hy = b.breite / 2.0, b.hoehe / 2.0
        teile = [
            f'  <path d="M {_f(cx)} {_f(cy - hy)} L {_f(cx + hx)} {_f(cy)} '
            f'L {_f(cx)} {_f(cy + hy)} L {_f(cx - hx)} {_f(cy)} z" '
            f'fill="{FARBE_GATEWAY}" stroke="{FARBE_RAHMEN}" stroke-width="1.5"/>'
        ]
        if knoten.art == "exclusive_gateway":
            teile.append(
                f'  <path d="M {_f(cx - 6)} {_f(cy - 6)} L {_f(cx + 6)} {_f(cy + 6)} '
                f'M {_f(cx + 6)} {_f(cy - 6)} L {_f(cx - 6)} {_f(cy + 6)}" '
                f'stroke="{FARBE_RAHMEN}" stroke-width="2"/>'
            )
        elif knoten.art == "parallel_gateway":
            teile.append(
                f'  <path d="M {_f(cx - 7)} {_f(cy)} h 14 M {_f(cx)} {_f(cy - 7)} v 14" '
                f'stroke="{FARBE_RAHMEN}" stroke-width="2"/>'
            )
        elif knoten.art == "inclusive_gateway":
            teile.append(
                f'  <circle cx="{_f(cx)}" cy="{_f(cy)}" r="7" fill="none" stroke="{FARBE_RAHMEN}" stroke-width="2"/>'
            )
        return "\n".join(teile) + "\n" + _text_mehrzeilig(
            knoten.name, b.x - 10, b.unten + 14, 11, max_breite=b.breite + 60, zentriert=b.mitte_x
        )

    # Aufgabe
    teile = [
        f'  <rect x="{_f(b.x)}" y="{_f(b.y)}" width="{_f(b.breite)}" height="{_f(b.hoehe)}" '
        f'rx="8" fill="{FARBE_TASK}" stroke="{FARBE_TASK_RAHMEN}" stroke-width="1.5"/>'
    ]
    typ = _typ_text(knoten.art)
    if typ:
        teile.append(
            f'  <text x="{_f(b.x + 8)}" y="{_f(b.y + 13)}" font-family="{SCHRIFT}" '
            f'font-size="9" fill="{FARBE_LEISE}" letter-spacing="0.5">{_esc(typ)}</text>'
        )
    teile.append(_text_mehrzeilig(knoten.name, b.x + 8, b.y + 32, 12, max_breite=b.breite - 16))
    return "\n".join(teile)


def _typ_text(art: str) -> str:
    return {
        "service_task": "SERVICE",
        "user_task": "BENUTZER",
        "send_task": "SENDEN",
        "receive_task": "EMPFANGEN",
        "script_task": "SKRIPT",
        "manual_task": "MANUELL",
        "business_rule_task": "REGEL",
    }.get(art, "")


def _text_mehrzeilig(
    text: str,
    x: float,
    y: float,
    groesse: float,
    max_breite: float,
    zentriert: float | None = None,
) -> str:
    zeilen = _umbruch(text, max_breite, groesse)
    if not zeilen:
        return ""
    anker = f' text-anchor="middle"' if zentriert is not None else ""
    xpos = _f(zentriert if zentriert is not None else x)
    teile = [f'  <text x="{xpos}" y="{_f(y)}" font-family="{SCHRIFT}" font-size="{_f(groesse)}" '
             f'fill="{FARBE_TEXT}"{anker}>']
    for i, zeile in enumerate(zeilen):
        dy = "0" if i == 0 else f"{_f(groesse * 1.2)}"
        teile.append(f'    <tspan x="{xpos}" dy="{dy}">{_esc(zeile)}</tspan>')
    teile.append("  </text>")
    return "\n".join(teile)


def _etikett(text: str, x: float, y: float, groesse: float) -> str:
    breite = len(text) * groesse * ZEICHENBREITE + 8
    return (
        f'  <rect x="{_f(x - breite / 2)}" y="{_f(y - groesse)}" width="{_f(breite)}" '
        f'height="{_f(groesse + 4)}" fill="{FARBE_HINTERGRUND}" fill-opacity="0.9"/>\n'
        f'  <text x="{_f(x)}" y="{_f(y)}" font-family="{SCHRIFT}" font-size="{_f(groesse)}" '
        f'fill="{FARBE_TEXT}" text-anchor="middle">{_esc(text)}</text>'
    )


def exportiere_svg(modell: m.Modell, pfad: str | Path | None = None) -> str:
    text = svg_text(modell)
    if pfad is not None:
        Path(pfad).write_text(text, encoding="utf-8", newline="\n")
    return text


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------


def exportiere_png(
    modell: m.Modell,
    pfad: str | Path | None = None,
    backend: str = "auto",
    skalierung: float = 2.0,
) -> bytes:
    """PNG erzeugen. ``backend``: ``auto``, ``cairosvg``, ``rsvg``, ``pillow``, ``intern``."""
    daten = _png_bytes(modell, backend=backend, skalierung=skalierung)
    if pfad is not None:
        Path(pfad).write_bytes(daten)
    return daten


def _png_bytes(modell: m.Modell, backend: str, skalierung: float) -> bytes:
    svg = svg_text(modell)
    reihenfolge = ["cairosvg", "rsvg", "pillow", "intern"] if backend == "auto" else [backend]
    fehler: list[str] = []
    for name in reihenfolge:
        try:
            if name == "cairosvg":
                daten = _mit_cairosvg(svg, skalierung)
            elif name == "rsvg":
                daten = _mit_rsvg(svg, skalierung)
            elif name == "pillow":
                daten = _mit_pillow(modell, skalierung)
            elif name == "intern":
                daten = rastere(modell, skalierung=skalierung)
            else:
                raise ValueError(f"unbekannter PNG-Backend: {name!r}")
        except Exception as ausnahme:  # noqa: BLE001 -- Rueckfall ist der Zweck
            fehler.append(f"{name}: {ausnahme}")
            continue
        if daten[:8] != b"\x89PNG\r\n\x1a\n":
            fehler.append(f"{name}: kein PNG-Signal")
            continue
        return daten
    raise RuntimeError("PNG-Erzeugung fehlgeschlagen -- " + "; ".join(fehler))


def _mit_cairosvg(svg: str, skalierung: float) -> bytes:
    import cairosvg  # type: ignore

    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=skalierung)


def _mit_rsvg(svg: str, skalierung: float) -> bytes:
    werkzeug = shutil.which("rsvg-convert")
    if werkzeug is None:
        raise FileNotFoundError("rsvg-convert nicht im Pfad")
    prozess = subprocess.run(
        [werkzeug, f"--zoom={skalierung}", "--format=png"],
        input=svg.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if prozess.returncode != 0:
        raise RuntimeError(prozess.stderr.decode("utf-8", "replace")[:200])
    return prozess.stdout


def _mit_pillow(modell: m.Modell, skalierung: float) -> bytes:
    from PIL import Image, ImageDraw  # type: ignore

    breite, hoehe = _pixelmasse(modell, skalierung)
    bild = Image.new("RGB", (breite, hoehe), FARBE_HINTERGRUND)
    zeichner = ImageDraw.Draw(bild)
    _zeichne(modell, skalierung, _PillowZeichner(zeichner))
    from io import BytesIO

    puffer = BytesIO()
    bild.save(puffer, format="PNG", optimize=False)
    return puffer.getvalue()


class _PillowZeichner:
    def __init__(self, zeichner: object) -> None:
        self.z = zeichner

    def rechteck(self, x: float, y: float, w: float, h: float, farbe: str, rahmen: str, dicke: int = 1) -> None:
        self.z.rectangle([x, y, x + w, y + h], fill=farbe, outline=rahmen, width=dicke)  # type: ignore[attr-defined]

    def linie(self, punkte: list[tuple[float, float]], farbe: str, dicke: int = 1) -> None:
        self.z.line(punkte, fill=farbe, width=dicke, joint="curve")  # type: ignore[attr-defined]

    def kreis(self, cx: float, cy: float, r: float, farbe: str, rahmen: str, dicke: int = 1) -> None:
        self.z.ellipse([cx - r, cy - r, cx + r, cy + r], fill=farbe, outline=rahmen, width=dicke)  # type: ignore[attr-defined]

    def raute(self, cx: float, cy: float, hx: float, hy: float, farbe: str, rahmen: str, dicke: int = 1) -> None:
        self.z.polygon(  # type: ignore[attr-defined]
            [(cx, cy - hy), (cx + hx, cy), (cx, cy + hy), (cx - hx, cy)],
            fill=farbe,
            outline=rahmen,
        )

    def text(self, x: float, y: float, text: str, groesse: int, farbe: str) -> None:
        self.z.text((x, y), text, fill=farbe)  # type: ignore[attr-defined]


def _pixelmasse(modell: m.Modell, skalierung: float) -> tuple[int, int]:
    links, oben, breite, hoehe = _inhalt(modell)
    rand = 30.0
    return (
        max(1, int(round((breite + 2 * rand) * skalierung))),
        max(1, int(round((hoehe + 2 * rand) * skalierung))),
    )


def _zeichne(modell: m.Modell, s: float, z: "Zeichner") -> None:
    """Gemeinsame Zeichenlogik fuer Pillow und den eingebauten Rasterer."""
    formen = _formen(modell)
    kanten = _kanten(modell)
    links, oben, _, _ = _inhalt(modell)
    dx = 30.0 - links
    dy = 30.0 - oben

    def r(b: m.Begrenzung) -> tuple[float, float, float, float]:
        return (b.x + dx) * s, (b.y + dy) * s, b.breite * s, b.hoehe * s

    for teilnehmer in modell.alle_teilnehmer():
        b = formen.get(teilnehmer.id) or teilnehmer.begrenzung
        if b is None:
            continue
        x, y, w, h = r(b)
        z.rechteck(x, y, w, h, FARBE_POOL, FARBE_RAHMEN, max(1, int(1.5 * s)))  # type: ignore[attr-defined]
    for prozess in modell.prozesse.values():
        for lane in prozess.alle_lanes():
            b = formen.get(lane.id) or lane.begrenzung
            if b is None:
                continue
            x, y, w, h = r(b)
            z.rechteck(x, y, w, h, FARBE_LANE, FARBE_RAHMEN)  # type: ignore[attr-defined]
            z.text(x + 6 * s, y + 4 * s, lane.name, int(11 * s), FARBE_TEXT)  # type: ignore[attr-defined]
    for fluss in modell.fluesse.values():
        weg = kanten.get(fluss.id)
        if not weg:
            continue
        punkte = [((p.x + dx) * s, (p.y + dy) * s) for p in weg]
        z.linie(punkte, FARBE_FLUSS, max(1, int(1.5 * s)))  # type: ignore[attr-defined]
    for daten in modell.daten.values():
        b = formen.get(daten.id) or daten.begrenzung
        if b is None:
            continue
        x, y, w, h = r(b)
        z.rechteck(x, y, w, h, FARBE_DATEN, FARBE_RAHMEN)  # type: ignore[attr-defined]
        z.text(x + 4 * s, y + 4 * s, daten.name, int(10 * s), FARBE_TEXT)  # type: ignore[attr-defined]
    for knoten in modell.alle_knoten():
        b = formen.get(knoten.id) or knoten.begrenzung
        if b is None:
            continue
        x, y, w, h = r(b)
        if knoten.ist_ereignis:
            z.kreis(x + w / 2, y + h / 2, min(w, h) / 2, FARBE_EREIGNIS, FARBE_RAHMEN,
                    max(1, int((3 if knoten.ist_ende else 1.5) * s)))  # type: ignore[attr-defined]
        elif knoten.ist_gateway:
            z.raute(x + w / 2, y + h / 2, w / 2, h / 2, FARBE_GATEWAY, FARBE_RAHMEN,
                    max(1, int(1.5 * s)))  # type: ignore[attr-defined]
        else:
            z.rechteck(x, y, w, h, FARBE_TASK, FARBE_TASK_RAHMEN, max(1, int(1.5 * s)))  # type: ignore[attr-defined]
        if knoten.name:
            z.text(x, y + h + 2 * s, knoten.name, int(10 * s), FARBE_TEXT)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Eingebauter Rasterer (nur Standardbibliothek)
# --------------------------------------------------------------------------

#: 5x7-Bitmapschrift. Grossbuchstaben; Kleinbuchstaben werden hochgesetzt.
_SCHRIFT_5X7: dict[str, tuple[int, ...]] = {
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    ",": (0x00, 0x00, 0x00, 0x00, 0x0C, 0x04, 0x08),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    "/": (0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    "+": (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    "_": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    " ": (0, 0, 0, 0, 0, 0, 0),
}

_UMLAUTE = {"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS", "ä": "AE", "ö": "OE", "ü": "UE"}


class _Bild:
    """RGB-Bild mit einfachen Zeichenoperationen."""

    def __init__(self, breite: int, hoehe: int, farbe: tuple[int, int, int] = (255, 255, 255)) -> None:
        self.breite = breite
        self.hoehe = hoehe
        self.daten = bytearray(farbe * (breite * hoehe))

    def setze(self, x: int, y: int, farbe: tuple[int, int, int]) -> None:
        if 0 <= x < self.breite and 0 <= y < self.hoehe:
            i = (y * self.breite + x) * 3
            self.daten[i : i + 3] = bytes(farbe)

    def rechteck(self, x0: int, y0: int, x1: int, y1: int, farbe: tuple[int, int, int], gefuellt: bool = True) -> None:
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        if gefuellt:
            for y in range(max(0, y0), min(self.hoehe, y1)):
                start = (y * self.breite + max(0, x0)) * 3
                ende = (y * self.breite + min(self.breite, x1)) * 3
                self.daten[start:ende] = bytes(farbe) * max(0, min(self.breite, x1) - max(0, x0))
            return
        for x in range(x0, x1):
            self.setze(x, y0, farbe)
            self.setze(x, y1 - 1, farbe)
        for y in range(y0, y1):
            self.setze(x0, y, farbe)
            self.setze(x1 - 1, y, farbe)

    def linie(self, x0: int, y0: int, x1: int, y1: int, farbe: tuple[int, int, int], dicke: int = 1) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        fehler = dx + dy
        while True:
            for ox in range(dicke):
                for oy in range(dicke):
                    self.setze(x0 + ox, y0 + oy, farbe)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * fehler
            if e2 >= dy:
                fehler += dy
                x0 += sx
            if e2 <= dx:
                fehler += dx
                y0 += sy

    def kreis(self, cx: int, cy: int, r: int, farbe: tuple[int, int, int], gefuellt: bool = True, dicke: int = 1) -> None:
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                abstand = (x - cx) ** 2 + (y - cy) ** 2
                if abstand <= r * r and (gefuellt or abstand >= (r - dicke) ** 2):
                    self.setze(x, y, farbe)

    def raute(self, cx: int, cy: int, hx: int, hy: int, farbe: tuple[int, int, int], gefuellt: bool = True) -> None:
        for y in range(cy - hy, cy + hy + 1):
            anteil = 1.0 - abs(y - cy) / max(1, hy)
            halb = int(hx * anteil)
            if gefuellt:
                self.rechteck(cx - halb, y, cx + halb, y + 1, farbe)
            else:
                for x in (cx - halb, cx + halb - 1):
                    self.setze(x, y, farbe)

    def text(self, x: int, y: int, text: str, skalierung: int, farbe: tuple[int, int, int]) -> None:
        for zeichen in str(text).upper():
            zeichen = _UMLAUTE.get(zeichen, zeichen)
            for teil in zeichen:
                muster = _SCHRIFT_5X7.get(teil, _SCHRIFT_5X7["?"])
                for zeile, bits in enumerate(muster):
                    for spalte in range(5):
                        if bits & (1 << (4 - spalte)):
                            self.rechteck(
                                x + spalte * skalierung,
                                y + zeile * skalierung,
                                x + (spalte + 1) * skalierung,
                                y + (zeile + 1) * skalierung,
                                farbe,
                            )
                x += 6 * skalierung

    def png(self) -> bytes:
        roh = bytearray()
        stride = self.breite * 3
        for y in range(self.hoehe):
            roh.append(0)  # Filter "None" -- deterministisch und ohne Vorhersage
            roh.extend(self.daten[y * stride : (y + 1) * stride])

        def chunk(typ: bytes, inhalt: bytes) -> bytes:
            return (
                struct.pack(">I", len(inhalt))
                + typ
                + inhalt
                + struct.pack(">I", zlib.crc32(typ + inhalt) & 0xFFFFFFFF)
            )

        kopf = struct.pack(">IIBBBBB", self.breite, self.hoehe, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", kopf)
            + chunk(b"IDAT", zlib.compress(bytes(roh), 9))
            + chunk(b"IEND", b"")
        )


class _InternZeichner:
    def __init__(self, bild: _Bild) -> None:
        self.bild = bild

    def rechteck(self, x: float, y: float, w: float, h: float, farbe: str, rahmen: str, dicke: int = 1) -> None:
        self.bild.rechteck(int(x), int(y), int(x + w), int(y + h), _rgb(farbe))
        self.bild.rechteck(int(x), int(y), int(x + w), int(y + h), _rgb(rahmen), gefuellt=False)

    def linie(self, punkte: list[tuple[float, float]], farbe: str, dicke: int = 1) -> None:
        for (x0, y0), (x1, y1) in zip(punkte, punkte[1:]):
            self.bild.linie(int(x0), int(y0), int(x1), int(y1), _rgb(farbe), max(1, dicke))

    def kreis(self, cx: float, cy: float, r: float, farbe: str, rahmen: str, dicke: int = 1) -> None:
        self.bild.kreis(int(cx), int(cy), int(r), _rgb(farbe))
        self.bild.kreis(int(cx), int(cy), int(r), _rgb(rahmen), gefuellt=False, dicke=max(1, dicke))

    def raute(self, cx: float, cy: float, hx: float, hy: float, farbe: str, rahmen: str, dicke: int = 1) -> None:
        self.bild.raute(int(cx), int(cy), int(hx), int(hy), _rgb(farbe))
        self.bild.raute(int(cx), int(cy), int(hx), int(hy), _rgb(rahmen), gefuellt=False)

    def text(self, x: float, y: float, text: str, groesse: int, farbe: str) -> None:
        self.bild.text(int(x), int(y), text, max(1, groesse // 9), _rgb(farbe))


def _rgb(wert: str) -> tuple[int, int, int]:
    wert = wert.lstrip("#")
    if len(wert) == 3:
        wert = "".join(z * 2 for z in wert)
    return (int(wert[0:2], 16), int(wert[2:4], 16), int(wert[4:6], 16))


def rastere(modell: m.Modell, skalierung: float = 2.0) -> bytes:
    """PNG ohne Fremdbibliothek -- direkt aus den Modellgeometrien."""
    breite, hoehe = _pixelmasse(modell, skalierung)
    breite = min(breite, 8000)
    hoehe = min(hoehe, 8000)
    bild = _Bild(breite, hoehe)
    _zeichne(modell, skalierung, _InternZeichner(bild))
    return bild.png()


def backends() -> list[str]:
    """Verfuegbare PNG-Backends, in der Reihenfolge von ``auto``."""
    verfuegbar = ["intern"]
    if shutil.which("rsvg-convert"):
        verfuegbar.insert(0, "rsvg")
    try:
        import cairosvg  # noqa: F401

        verfuegbar.insert(0, "cairosvg")
    except Exception:  # noqa: BLE001
        pass
    try:
        import PIL  # noqa: F401

        verfuegbar.insert(0, "pillow")
    except Exception:  # noqa: BLE001
        pass
    return verfuegbar


def exportiere_alle(modell: m.Modell, verzeichnis: str | Path, name: str = "prozess") -> dict[str, Path]:
    """SVG und PNG nebeneinander ablegen."""
    ziel = Path(verzeichnis)
    ziel.mkdir(parents=True, exist_ok=True)
    svg_pfad = ziel / f"{name}.svg"
    png_pfad = ziel / f"{name}.png"
    exportiere_svg(modell, svg_pfad)
    exportiere_png(modell, png_pfad)
    return {"svg": svg_pfad, "png": png_pfad}


def iteration(elemente: Iterable[object]) -> list[object]:
    return list(elemente)
