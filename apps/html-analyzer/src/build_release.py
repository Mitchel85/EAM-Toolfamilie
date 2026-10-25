#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baut ADMBw_QEA_Analyzer_Edit.html und .aspx (v5.0, Edit-Edition).

Aufbau der Einzeldatei:
  part1_head_body.html
  + v2-Skriptblock (qeaOpen + ADMBW_DATA aus backups/ADMBw_Viewpoint_Dashboard.html)
  + <script>sql.js-Glue (vendor/sql-wasm.js)</script>
  + <script>var SQLJS_WASM_B64="..."</script>   (eingebettetes SQLite-WASM, MIT-Lizenz)
  + <script>part2_app_core.js + part3_app_graph.js + part4_path.js + part5_edit.js</script>

ASPY-Regeln (Vorgabe Mitch, 10/2026):
  * Die ASPX-Datei beginnt DIREKT mit '<!DOCTYPE html>' — KEINE <%@ … %>-Direktive!
  * UTF-8 MIT BOM; Inhalt enthält keine '<%'-Sequenz.
Outputs: Arbeitsverzeichnis + dist/ + Auslieferungsordner.
"""
import base64
import os
import re
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DIR = HERE
VEND = os.path.join(REPO, "vendor")
BAK_HTML = os.path.join(DIR, "qea_open_and_data.html")
DIST = os.path.join(REPO, "dist")
DOCS = os.path.join(REPO, "docs")
OUT_DIR = os.path.join(REPO, "dist")
NAME = "ADMBw_QEA_Analyzer_Edit"

with open(BAK_HTML, "r", encoding="utf-8") as f:
    script_qea_and_data = f.read()

# Der QEA-Reader + ADMBW_DATA-Block liegt jetzt versioniert in src/ —
# kein externes Backup mehr nötig (reproduzierbarer Build, AAroN-Review 19.10.2026).
assert "function qeaOpen(" in script_qea_and_data, "qeaOpen fehlt!"
assert "var ADMBW_DATA =" in script_qea_and_data, "ADMBW_DATA fehlt!"


def rd(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


part1 = rd(os.path.join(DIR, "part1_head_body.html"))
part2 = rd(os.path.join(DIR, "part2_app_core.js"))
part3 = rd(os.path.join(DIR, "part3_app_graph.js"))
part4 = rd(os.path.join(DIR, "part4_path.js"))
part5 = rd(os.path.join(DIR, "part5_edit.js"))
sqlglue = rd(os.path.join(VEND, "sql-wasm.js"))
with open(os.path.join(VEND, "sql-wasm.wasm"), "rb") as f:
    wasm_b64 = base64.b64encode(f.read()).decode("ascii")

assert "</script" not in sqlglue, "sql.js-Glue enthält '</script'!"

full_html = (
    part1.rstrip() + "\n" +
    script_qea_and_data.rstrip() + "\n" +
    "<script>\n" + sqlglue.strip() + "\n</script>\n" +
    "<script>var SQLJS_WASM_B64=\"" + wasm_b64 + "\";</script>\n" +
    "<script>\n" +
    part2.rstrip() + "\n\n" +
    part3.rstrip() + "\n\n" +
    part4.rstrip() + "\n\n" +
    part5.rstrip() + "\n" +
    "</script>\n</body>\n</html>\n"
)

# ASPX-Sicherheit: keine Server-Direktiven im Inhalt
assert "<%" not in full_html, "Fehler: '<%' im HTML-Inhalt gefunden!"

# Alle <script>-Blöcke extrahieren und mit node --check prüfen
scripts = re.findall(r"<script[^>]*>(.*?)</script>", full_html, flags=re.S)
print(f"Gefundene <script>-Blöcke: {len(scripts)}")
assert len(scripts) == 5, f"Erwartet: 5 <script>-Blöcke, gefunden: {len(scripts)}"

for idx, sc in enumerate(scripts, 1):
    tmp_js = os.path.join(DIR, f"_check_block_{idx}.js")
    with open(tmp_js, "w", encoding="utf-8") as f:
        f.write(sc)
    subprocess.check_call(["node", "--check", tmp_js])
    os.remove(tmp_js)
    print(f"  Block {idx}: node --check OK ({len(sc)} chars)")

# 1. HTML schreiben (nur dist + Auslieferungsordner; src bleibt Quellcode)
targets_html = [
    os.path.join(DIST, NAME + ".html"),
    os.path.join(DOCS, NAME + ".html"),
    os.path.join(OUT_DIR, NAME + ".html"),
]
for p in targets_html:
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(full_html)

# 1b. index.html für GitHub Pages (Weiterleitung auf die Analyse-App)
with open(os.path.join(DIST, "index.html"), "w", encoding="utf-8") as f:
    f.write('<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0; url=' + NAME + '.html">'
            '<title>EAM QEA Analyzer</title></head><body>'
            '<p>Weiterleitung … <a href="' + NAME + '.html">EAM QEA Analyzer öffnen</a></p>'
            '</body></html>\n')

# 2. ASPX bauen: Inhalt identisch, beginnt DIREKT mit <!DOCTYPE html>, UTF-8 mit BOM
assert full_html.startswith('<!DOCTYPE html>')
assert "<%" not in full_html, "ASPY enthält Server-Direktiven!"
assert full_html.lstrip('\ufeff').startswith('<!DOCTYPE html>'), "ASPY muss mit <!DOCTYPE html> beginnen!"

targets_aspx = [
    os.path.join(DIST, NAME + ".aspx"),
    os.path.join(OUT_DIR, NAME + ".aspx"),
]
for p in targets_aspx:
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"\xef\xbb\xbf" + full_html.encode("utf-8"))

# 3. Quellbausteine + Vendor in die Projektstruktur kopieren (für GitHub)
SRC = os.path.join(REPO, "src")
VEND_REPO = os.path.join(REPO, "vendor")
os.makedirs(SRC, exist_ok=True)
for fn in ["part1_head_body.html", "part2_app_core.js", "part3_app_graph.js", "part4_path.js", "part5_edit.js"]:
    src = os.path.join(DIR, fn)
    dst = os.path.join(SRC, fn)
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)
build_dst = os.path.join(SRC, "build_release.py")
if os.path.abspath(__file__) != os.path.abspath(build_dst):
    shutil.copy2(__file__, build_dst)
os.makedirs(VEND_REPO, exist_ok=True)
for fn in ["sql-wasm.js", "sql-wasm.wasm", "LICENSE-sql.js"]:
    src = os.path.join(VEND, fn)
    dst = os.path.join(VEND_REPO, fn)
    if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)

# ================================================================
# 4. Analyse-Edition (v4.0, ohne Edit/Bearbeiten) aus denselben Quellen bauen:
#    part1 ohne v5-Edit-Bestandteile + QEA-Reader/ADMBW_DATA + part2–4.
#    Die App rendert Edit-Schaltflächen nur bei vorhandenem EDIT-Modul
#    (typeof EDIT !== 'undefined').
# ================================================================
PLAIN_NAME = "ADMBw_QEA_Analyzer"
EDIT_BADGE = '<span class="badge-v">v5.0 · Edit</span>'
PLAIN_BADGE = '<span class="badge-v">v4.0</span>'
EDIT_P = 'QEA-Architekturen verstehen <b>und bearbeiten</b>: Pakete &amp; Sichten erkunden, im Graphen analysieren, Verbindungen nachweisen, Elemente/Pakete/Sichten/Beziehungen ändern und als neue .qea speichern — 100&nbsp;% lokal im Browser, ohne KI.'
PLAIN_P = 'QEA-Architekturen verstehen: Pakete &amp; Sichten erkunden, im Graphen analysieren, Verbindungen zweier Elemente nachweisen und als PNG / Excel exportieren — 100&nbsp;% lokal im Browser, ohne KI.'
EDIT_FOOTER = 'EAM QEA Analyzer v5.0 (Edit-Edition) · 100 % Offline-Auswertung &amp; Bearbeitung im Browser (keine Datenübertragung) · Farben gemäß ADMBw/NAFv4.'
PLAIN_FOOTER = 'EAM QEA Analyzer v4.0 · 100 % Offline-Auswertung im Browser (keine Datenübertragung) · Farben gemäß ADMBw/NAFv4.'
V5_CSS_MARKER = '/* --- v5 Edit-Edition: Bearbeiten (Drawer, Modals, Toasts, Edit-Buttons) --- */'
# Design-Umschaltung steht am ENDE des <style>-Blocks und muss in BEIDEN Editionen bleiben
THEME_CSS_START = '  /* ---------- Designumschaltung: Standard = hell, Dunkel nur per Button ---------- */'

plain_part1 = part1
plain_part1 = plain_part1.replace(
    '<title>EAM QEA Analyzer (Edit) — QEA-Architekturen analysieren, erkunden, bearbeiten &amp; exportieren</title>',
    '<title>EAM QEA Analyzer — QEA-Architekturen niederschwellig analysieren, erkunden &amp; exportieren</title>')
assert V5_CSS_MARKER in plain_part1, "v5-Edit-CSS-Block nicht gefunden!"
assert THEME_CSS_START in plain_part1, "Design-Umschaltung CSS nicht gefunden!"
head_css, rest = plain_part1.split(V5_CSS_MARKER, 1)
theme_css = rest[rest.index(THEME_CSS_START):].split('</style>', 1)[0]   # Theme-CSS (hell/dunkel) bis </style>
tail_after_style = rest.split('</style>', 1)[1]
plain_part1 = head_css + theme_css.rstrip() + '\n</style>' + tail_after_style
assert EDIT_BADGE in plain_part1 and EDIT_P in plain_part1, "Edit-Kopfzeile nicht gefunden!"
plain_part1 = plain_part1.replace(EDIT_BADGE, PLAIN_BADGE).replace(EDIT_P, PLAIN_P)
plain_part1 = re.sub(
    r'\s*<button class="btn-sm amber" id="editbtn"[^>]*>.*?</button>', '', plain_part1,
    flags=re.S)
assert EDIT_FOOTER in plain_part1, "Edit-Footer nicht gefunden!"
plain_part1 = plain_part1.replace(EDIT_FOOTER, PLAIN_FOOTER)
for edit_div in ['<div id="editdrawer" hidden></div>',
                 '<div id="editmodal" class="emodal" hidden></div>',
                 '<div id="edittoast" hidden></div>']:
    assert edit_div in plain_part1, f"Edit-Container fehlt: {edit_div}"
    plain_part1 = plain_part1.replace('\n' + edit_div, '')
assert 'EDIT.openPanel' not in plain_part1 and 'id="editbtn"' not in plain_part1

full_plain = (
    plain_part1.rstrip() + "\n" +
    script_qea_and_data.rstrip() + "\n" +
    "<script>\n" +
    part2.rstrip() + "\n\n" +
    part3.rstrip() + "\n\n" +
    part4.rstrip() + "\n" +
    "</script>\n</body>\n</html>\n"
)
assert "typeof EDIT !== 'undefined'" in full_plain, "Edit-Guards fehlen in der Analyse-Edition"
assert "<%" not in full_plain, "Fehler: '<%' im Inhalt der Analyse-Edition gefunden!"
plain_scripts = re.findall(r"<script[^>]*>(.*?)</script>", full_plain, flags=re.S)
assert len(plain_scripts) == 3, f"Erwartet: 3 <script>-Blöcke (Analyse), gefunden: {len(plain_scripts)}"
for idx, sc in enumerate(plain_scripts, 1):
    tmp_js = os.path.join(DIR, f"_check_plain_{idx}.js")
    with open(tmp_js, "w", encoding="utf-8") as f:
        f.write(sc)
    subprocess.check_call(["node", "--check", tmp_js])
    os.remove(tmp_js)
    print(f"  Analyse-Block {idx}: node --check OK ({len(sc)} chars)")

# Genau ein Design-Button je Ausgabe (Style-/Script-Blöcke werden verdoppelt eingebettet)
assert full_html.count('id="themeBtn"') == 1, f"Edit-Edition: {full_html.count('id=\"themeBtn\"')} Design-Buttons"
assert full_plain.count('id="themeBtn"') == 1, f"Analyse-Edition: {full_plain.count('id=\"themeBtn\"')} Design-Buttons"

targets_plain_html = [
    os.path.join(DIST, PLAIN_NAME + ".html"),
    os.path.join(DOCS, PLAIN_NAME + ".html"),
    os.path.join(OUT_DIR, PLAIN_NAME + ".html"),
]
for p in targets_plain_html:
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(full_plain)
targets_plain_aspx = [
    os.path.join(DIST, PLAIN_NAME + ".aspx"),
    os.path.join(OUT_DIR, PLAIN_NAME + ".aspx"),
]
for p in targets_plain_aspx:
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"\xef\xbb\xbf" + full_plain.encode("utf-8"))

print("Build erfolgreich!")
print("  HTML (Edit):", targets_html[0], os.path.getsize(targets_html[0]), "bytes")
print("  ASPX (Edit):", targets_aspx[0], os.path.getsize(targets_aspx[0]), "bytes")
print("  HTML (Analyse):", targets_plain_html[0], os.path.getsize(targets_plain_html[0]), "bytes")
print("  ASPX (Analyse):", targets_plain_aspx[0], os.path.getsize(targets_plain_aspx[0]), "bytes")
