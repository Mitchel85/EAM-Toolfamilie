#!/usr/bin/env python3
"""Baut das BPMN Studio als eine offline lauffaehige HTML-Datei.

    python3 apps/bpmn-studio/build.py
    python3 apps/bpmn-studio/build.py --check

Quellen:

* ``src/index.html``   -- Geruest mit Platzhaltern
* ``src/studio.css``   -- Oberflaeche
* ``src/studio.js``    -- Editor, Pruefung, Text-Extraktion
* ``vendor/bpmn-js/``  -- bpmn-js 18.31.1 (MIT) samt CSS und Schrift
* ``knowledge/bpmn/prozess-regeln.json`` -- Regeltexte fuer das Pruef-Panel

Beim Bauen werden JavaScript, CSS und Schrift als Daten-URI eingebettet. Das
Ergebnis enthaelt keinen Verweis auf eine externe Ressource; der einzige
externe Verweis ist das bpmn.io-Wasserzeichen im gebuendelten Modellierer
(Lizenzbedingung, wird nicht nachgeladen).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = HERE / "src"
VENDOR = ROOT / "vendor" / "bpmn-js"
PDF_JS = ROOT / "vendor" / "pdf.min.js"
PDF_WORKER = ROOT / "vendor" / "pdf.worker.min.js"
REGELN = ROOT / "knowledge" / "bpmn" / "prozess-regeln.json"
AUSGABE = HERE / "index.html"
DIST = HERE / "dist" / "BPMN-Studio.html"

VERSION = "3.9.1"
BPMN_JS_VERSION = "18.31.1"

MIME = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".eot": "application/vnd.ms-fontobject",
    ".svg": "image/svg+xml",
}

CSS_DATEIEN = (
    VENDOR / "assets" / "bpmn-js.css",
    VENDOR / "assets" / "diagram-js.css",
    VENDOR / "assets" / "bpmn-font" / "css" / "bpmn-embedded.css",
)


def _daten_uri(pfad: Path) -> str:
    typ = MIME.get(pfad.suffix.lower(), "application/octet-stream")
    return f"data:{typ};base64,{base64.b64encode(pfad.read_bytes()).decode('ascii')}"


def _css_einbetten(css: str, basis: Path) -> str:
    """Ersetzt relative url(...) durch Daten-URIs."""

    def ersetze(treffer: re.Match[str]) -> str:
        ziel = treffer.group(2).strip()
        if ziel.startswith(("data:", "http:", "https:", "#")):
            return treffer.group(0)
        pfad_text = ziel.split("?", 1)[0].split("#", 1)[0]
        pfad = (basis / pfad_text).resolve()
        if not pfad.is_file():
            raise SystemExit(f"CSS verweist auf fehlende Datei: {ziel} (aus {basis})")
        return f"url('{_daten_uri(pfad)}')"

    return re.sub(r"url\((['\"]?)([^)'\"]+)\1\)", ersetze, css)


def _regeln() -> dict:
    daten = json.loads(REGELN.read_text(encoding="utf-8"))
    return {
        "schemaVersion": daten.get("schemaVersion"),
        "pruefregeln": daten.get("pruefregeln", []),
        "elementtypen": daten.get("elementtypen", {}),
        "metaconstraints": daten.get("metaconstraints", {}),
    }


def baue() -> str:
    for pfad in (SRC / "index.html", SRC / "studio.js", SRC / "studio.css", *CSS_DATEIEN,
                 PDF_JS, PDF_WORKER):
        if not pfad.is_file():
            raise SystemExit(f"Quelle fehlt: {pfad}")

    html = (SRC / "index.html").read_text(encoding="utf-8")
    studio_js = (SRC / "studio.js").read_text(encoding="utf-8")
    studio_css = (SRC / "studio.css").read_text(encoding="utf-8")
    bpmn_js = (VENDOR / "bpmn-modeler.production.min.js").read_text(encoding="utf-8")
    pdf_js = PDF_JS.read_text(encoding="utf-8")
    pdf_worker = PDF_WORKER.read_text(encoding="utf-8")

    if any("</script" in teil.lower() for teil in (studio_js, bpmn_js, pdf_js, pdf_worker)):
        raise SystemExit("JavaScript enthaelt '</script' und wuerde den HTML-Block beenden")

    bpmn_css_teile = [
        _css_einbetten(pfad.read_text(encoding="utf-8"), pfad.parent) for pfad in CSS_DATEIEN
    ]
    bpmn_css = "\n".join(bpmn_css_teile)

    regeln = json.dumps(_regeln(), ensure_ascii=False, sort_keys=True)
    regeln = regeln.replace("<", "\\u003c").replace(">", "\\u003e")

    for platzhalter, wert in (
        ("{{BPMN_CSS}}", bpmn_css),
        ("{{STUDIO_CSS}}", studio_css),
        ("{{PDF_JS}}", pdf_js),
        ("{{PDF_WORKER}}", pdf_worker),
        ("{{BPMN_JS}}", bpmn_js),
        ("{{STUDIO_JS}}", studio_js),
        ("{{PRUEFREGELN}}", regeln),
        ("{{VERSION}}", VERSION),
    ):
        if platzhalter not in html:
            raise SystemExit(f"Platzhalter fehlt: {platzhalter}")
        html = html.replace(platzhalter, wert)

    # Keine unaufgeloesten Platzhalter stehen lassen.
    rest = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if rest:
        raise SystemExit(f"unaufgeloeste Platzhalter: {sorted(set(rest))}")

    return html


def schreibe(inhalt: str) -> dict[str, Path]:
    AUSGABE.write_text(inhalt, encoding="utf-8")
    DIST.parent.mkdir(parents=True, exist_ok=True)
    DIST.write_text(inhalt, encoding="utf-8")
    return {"index": AUSGABE, "dist": DIST}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BPMN Studio bauen.")
    parser.add_argument("--check", action="store_true", help="nur pruefen, ob index.html aktuell ist")
    args = parser.parse_args(argv)

    inhalt = baue()
    if args.check:
        if not AUSGABE.is_file():
            print(f"fehlt: {AUSGABE}")
            return 1
        ist = AUSGABE.read_text(encoding="utf-8")
        if ist != inhalt:
            print("index.html ist nicht aktuell -- build.py laufen lassen")
            return 1
        print(f"aktuell: {AUSGABE} ({len(inhalt)} Zeichen)")
        return 0

    pfade = schreibe(inhalt)
    for name, pfad in pfade.items():
        print(f"{pfad} ({pfad.stat().st_size} Bytes, sha256 {hashlib.sha256(pfad.read_bytes()).hexdigest()[:16]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
