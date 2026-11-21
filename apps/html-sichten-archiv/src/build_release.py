#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baut das Sichten-Archiv als Einzeldatei (HTML + ASPX).

Aufbau:
  src/app.html  mit den Platzhaltern __SQLJS_GLUE__ und __WASM_B64__

ASPY-Regeln:
  * Die ASPX-Datei beginnt DIREKT mit '<!DOCTYPE html>' — keine <%@ … %>-Direktive.
  * UTF-8 MIT BOM; der Inhalt enthält keine '<%'-Sequenz.
  * Kein '</script' in eingebettetem Fremdcode.

Ausgabe: dist/Sichten-Archiv.html und dist/Sichten-Archiv.aspx
"""
from __future__ import annotations

import base64
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
REPO = APP.parents[1]
VENDOR = APP / "vendor" if (APP / "vendor").is_dir() else REPO / "vendor"
DIST = APP / "dist"

NAME = "Sichten-Archiv"
GLUE = VENDOR / "sql-wasm.js"
WASM = VENDOR / "sql-wasm.wasm"


def main() -> int:
    for datei in (GLUE, WASM, HERE / "app.html"):
        if not datei.is_file():
            raise SystemExit(f"Fehlt: {datei}")

    html = (HERE / "app.html").read_text(encoding="utf-8")
    glue = GLUE.read_text(encoding="utf-8")
    wasm_b64 = base64.b64encode(WASM.read_bytes()).decode("ascii")

    assert "</script" not in glue.lower(), "sql.js-Glue enthält '</script'"
    assert "__SQLJS_GLUE__" in html and "__WASM_B64__" in html, "Platzhalter fehlen in app.html"
    assert "<%" not in html, "'<%' im HTML-Inhalt gefunden"

    voll = html.replace("__SQLJS_GLUE__", glue.strip()).replace("__WASM_B64__", wasm_b64)
    assert "<%" not in voll, "'<%' nach dem Einsetzen gefunden"

    # Jeden Skriptblock syntaktisch prüfen.
    bloecke = re.findall(r"<script[^>]*>(.*?)</script>", voll, flags=re.S)
    print(f"Skriptblöcke: {len(bloecke)}")
    for nummer, block in enumerate(bloecke, 1):
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as fh:
            fh.write(block)
            pfad = fh.name
        ergebnis = subprocess.run(["node", "--check", pfad], capture_output=True, text=True)
        if ergebnis.returncode != 0:
            raise SystemExit(f"Skriptblock {nummer} fehlerhaft:\n{ergebnis.stderr}")
        Path(pfad).unlink(missing_ok=True)

    DIST.mkdir(parents=True, exist_ok=True)
    html_pfad = DIST / f"{NAME}.html"
    aspx_pfad = DIST / f"{NAME}.aspx"

    html_pfad.write_text(voll, encoding="utf-8", newline="\n")
    aspx_pfad.write_text(voll, encoding="utf-8-sig", newline="\n")

    for p in (html_pfad, aspx_pfad):
        print(f"{p.name}: {p.stat().st_size/1048576:.2f} MB")
    print(f"HTML: {html_pfad}")
    print(f"ASPX: {aspx_pfad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
