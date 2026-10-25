#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baut EAM-AI-Suite.html und .aspx (v9.1, Standalone-Repo).

Aufbau der Einzeldatei:
  part1_head_body.html
  + Grundblock (qeaOpen-Reader + ADMBW_DATA: Referenz-Grid/Viewpoints/Topologie)
  + <script>sql.js-Glue (vendor/sql-wasm.js)</script>
  + <script>var SQLJS_WASM_B64="..."</script>   (eingebettetes SQLite-WASM, MIT-Lizenz)
  + <script>part2_app_core.js + part3_app_graph.js + part4_path.js + part5_edit.js + part6_ki.js</script>
  + <script>part7_qa.js (Rückweg: Frage & Antwort über die geladene .qea + Bearbeiten-Hub)</script>
  + <script>part8_stdimport.js (Standardelemente-Katalog aus zweiter .qea, GUID-Erhalt)</script>
  + <script>part9_handbuch.js (Prosa-Export: Handbuch als Markdown, zehn Kapitel)</script>
  + <script>part10_nledit.js (Natuerlichsprachliche Korrektur der geladenen .qea)</script>

ASPY-Regeln (Vorgabe Mitch, 10/2026):
  * Die ASPX-Datei beginnt DIREKT mit '<!DOCTYPE html>' — KEINE <%@ … %>-Direktive!
  * UTF-8 MIT BOM; Inhalt enthält keine '<%'-Sequenz.

Ausführen im Repository-Wurzelverzeichnis:  python3 src/build_release.py
"""
import base64
import os
import re
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
DIST = os.path.join(REPO, "dist")
VEND = os.path.join(REPO, "vendor")
NAME = "EAM-AI-Suite"


def rd(*parts):
    with open(os.path.join(*parts), "r", encoding="utf-8") as f:
        return f.read()


part1 = rd(SRC, "part1_head_body.html")
part2 = rd(SRC, "part2_app_core.js")
part3 = rd(SRC, "part3_app_graph.js")
part4 = rd(SRC, "part4_path.js")
part5 = rd(SRC, "part5_edit.js")
part6 = rd(SRC, "part6_ki.js")
part7 = rd(SRC, "part7_qa.js")
part8 = rd(SRC, "part8_stdimport.js")
part9 = rd(SRC, "part9_handbuch.js")
part10 = rd(SRC, "part10_nledit.js")
script_reader = rd(SRC, "part0_reader_data.js")
jszip_lib = rd(VEND, "jszip.min.js")
pdfjs_lib = rd(VEND, "pdf.min.js")
pdf_worker = rd(VEND, "pdf.worker.min.js")
pdf_worker_b64 = base64.b64encode(pdf_worker.encode("utf-8")).decode("ascii")
sqlglue = rd(VEND, "sql-wasm.js")
with open(os.path.join(VEND, "sql-wasm.wasm"), "rb") as f:
    wasm_b64 = base64.b64encode(f.read()).decode("ascii")

assert "window.KI =" in part6, "KI-Modul fehlt!"
assert "function qeaOpen(" in script_reader, "qeaOpen-Reader fehlt!"
assert "var ADMBW_DATA =" in script_reader, "ADMBW_DATA fehlt!"
assert "var STDIMPORT =" in part8, "STDIMPORT-Modul fehlt!"
assert "var HANDBUCH =" in part9, "HANDBUCH-Modul fehlt!"
assert "var NL =" in part10, "NL-Modul fehlt!"
assert "applyNlOps" in part5, "EDIT.applyNlOps fehlt!"
assert "</scr" not in part10, "Teil 10 enthält '</scr'-Sequenz!"
assert "</scr" not in part9, "Teil 9 enthält '</scr'-Sequenz!"
assert "</scr" not in part8, "Teil 8 enthält '</scr'-Sequenz!"
assert "</script" not in sqlglue, "sql.js-Glue enthält '</script'!"
assert "</scr" not in script_reader, "Reader-Block enthält '</scr'-Sequenz!"
assert "</scr" not in jszip_lib, "JSZip enthält '</scr'-Sequenz!"
assert "</scr" not in pdfjs_lib, "pdf.js enthält '</scr'-Sequenz!"
assert "</scr" not in pdf_worker, "pdf.worker.js enthält '</scr'-Sequenz!"

full_html = (
    part1.rstrip() + "\n" +
    "<script>\n" + script_reader.strip() + "\n</script>\n" +
    "<script>\n" + sqlglue.strip() + "\n</script>\n" +
    "<script>var SQLJS_WASM_B64=\"" + wasm_b64 + "\";</script>\n" +
    "<script>\n" + jszip_lib.strip() + "\n</script>\n" +
    "<script>\n" + pdfjs_lib.strip() + "\n</script>\n" +
    "<script>var PDFJS_WORKER_B64=\"" + pdf_worker_b64 + "\";</script>\n" +
    "<script>\n" +
    part2.rstrip() + "\n\n" +
    part3.rstrip() + "\n\n" +
    part4.rstrip() + "\n\n" +
    part5.rstrip() + "\n\n" +
    part6.rstrip() + "\n" +
    "</script>\n" +
    "<script>\n" + part7.rstrip() + "\n</script>\n" +
    "<script>\n" + part8.rstrip() + "\n</script>\n" +
    "<script>\n" + part9.rstrip() + "\n</script>\n" +
    "<script>\n" + part10.rstrip() + "\n</script>\n" +
    "</body>\n</html>\n"
)

# ASPX-Sicherheit: keine Server-Direktiven im Inhalt
assert "<%" not in full_html, "Fehler: '<%' im HTML-Inhalt gefunden!"

# Alle <script>-Blöcke extrahieren und mit node --check prüfen
scripts = re.findall(r"<script[^>]*>(.*?)</script>", full_html, flags=re.S)
print(f"Gefundene <script>-Blöcke: {len(scripts)}")
assert len(scripts) == 11, f"Erwartet: 11 <script>-Blöcke, gefunden: {len(scripts)}"

for idx, sc in enumerate(scripts, 1):
    tmp_js = os.path.join(SRC, f"_check_block_{idx}.js")
    with open(tmp_js, "w", encoding="utf-8") as f:
        f.write(sc)
    subprocess.check_call(["node", "--check", tmp_js])
    os.remove(tmp_js)
    print(f"  Block {idx}: node --check OK ({len(sc)} chars)")

# 1. HTML schreiben
os.makedirs(DIST, exist_ok=True)
target_html = os.path.join(DIST, NAME + ".html")
with open(target_html, "w", encoding="utf-8") as f:
    f.write(full_html)

# 2. ASPX bauen: Inhalt identisch, beginnt DIREKT mit <!DOCTYPE html>, UTF-8 mit BOM
assert full_html.startswith('<!DOCTYPE html>')
assert full_html.lstrip('\ufeff').startswith('<!DOCTYPE html>'), "ASPY muss mit <!DOCTYPE html> beginnen!"
target_aspx = os.path.join(DIST, NAME + ".aspx")
with open(target_aspx, "wb") as f:
    f.write(b"\xef\xbb\xbf" + full_html.encode("utf-8"))

print("Build erfolgreich!")
print("  HTML:", target_html, os.path.getsize(target_html), "bytes")
print("  ASPX:", target_aspx, os.path.getsize(target_aspx), "bytes")
