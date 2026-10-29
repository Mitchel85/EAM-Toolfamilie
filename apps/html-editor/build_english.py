#!/usr/bin/env python3
"""Erzeugt die englische Fassung der EAM Suite aus den deutschen Quellen.

    python3 apps/html-editor/build_english.py

Ablauf:

1. Alle sichtbaren deutschen Texte einsammeln (HTML-Textknoten, Attribute wie
   ``title``/``placeholder``, String-Literale der JS-Teile) und als
   ``dist/_kandidaten.json`` ausgeben. Gesichtet wird von Hand.
2. Beim Bauen wird ``src/english.json`` (deutsch -> englisch) angewandt, danach
   baut ``build_release.py`` die Einzeldatei.

Die Einzeldatei enthält viel HTML in JavaScript-Literalen, mal mit ``'``, mal
mit ``"`` begrenzt, oft verschachtelt. Deshalb wird nicht zeichenweise neu
gebaut, sondern jedes deutsche Vorkommen einzeln ersetzt — aber nur, wenn es
außerhalb eines ``<script>``-Blocks liegt oder innerhalb eines Literals mit
passendem Begrenzer steht. Kommentare, Kennungen und SQL bleiben tabu.

Nicht angefasst werden Elementnamen, Katalogdaten, Schlüssel und alles, was im
Wörterbuch fehlt. Fehlt eine Übersetzung, bleibt der deutsche Text stehen —
der Lauf meldet das, statt zu raten.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
SRC = APP / "src"
DIST = APP / "dist"
WOERTERBUCH = SRC / "english.json"
FREIGABE = DIST / "_englisch"

DATEIEN = [
    "part1_head_body.html",
    "part0_reader_data.js",
    "part2_app_core.js",
    "part3_app_graph.js",
    "part4_path.js",
    "part5_edit.js",
]

DE_WOERTER = set(
    """der die das den dem des ein eine einer eines und oder aber nicht kein keine nur auch noch
    werden wird wurde sind ist war sein hat haben hatte kann können muss müssen soll sollen darf
    für von mit auf aus bei nach vor über unter durch gegen ohne um zu im in am an als wie wenn
    dann dort hier alle alles viele einige Datei Dateien Modell Modelle Sicht Sichten Paket Pakete
    Element Elemente Beziehung Beziehungen laden öffnen speichern bearbeiten prüfen gefunden Fehler
    bitte wählen ausgewählt weitere vollständig Excel""".split()
)
DE_WOERTER = {w.lower() for w in DE_WOERTER}

LITERAL = re.compile(r"'([^'\\\n]{2,200})'|\"([^\"\\\n]{2,200})\"|`([^`]{2,200})`")
TEXTKNOTEN = re.compile(r">([^<>{}]{2,300})<")
ATTRIBUT = re.compile(r'(title|placeholder|aria-label|alt)="([^"]{2,300})"')
STATEMENT = re.compile(r"(?m)^\s*(?:var|let|const|function|return|/\*|\*|//)")


def ist_deutsch(text: str) -> bool:
    """Grobe Heuristik: Umlaut oder ein häufiges deutsches Funktionswort."""
    if re.search(r"[äöüÄÖÜß]", text):
        return True
    if not re.search(r"[A-Za-z]{2}", text):
        return False
    woerter = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", text.lower())
    return any(w in DE_WOERTER for w in woerter)


def _stellen(quelle: str) -> list[tuple[int, int, str]]:
    """Findet String-Literale zeichenweise.

    Ein Muster mit ``[^'\\n]`` scheitert an escapten Anfuehrungszeichen: In
    ``h.push(\'<button title="x">Text</button>\')`` beginnt das Literal hinter dem
    Escape und endet beim naechsten ``\'``. Deshalb hier ein kleiner Leser.

    Rueckgabe: (Start, Ende, Begrenzer) je Literal, Ende zeigt hinter das Ende.
    """
    stellen: list[tuple[int, int, str]] = []
    i = 0
    laenge = len(quelle)
    while i < laenge:
        art = quelle[i]
        if art not in "\"'`":
            i += 1
            continue
        j = i + 1
        while j < laenge:
            if quelle[j] == "\\":
                j += 2
                continue
            if quelle[j] == art:
                break
            if quelle[j] == "\n" and art != "`":
                break
            j += 1
        if j < laenge and quelle[j] == art:
            stellen.append((i, j + 1, art))
            i = j + 1
            continue
        i += 1
    return stellen


def literale(quelle: str) -> list[str]:
    gefunden = []
    for start, ende, art in _stellen(quelle):
        ganzer = quelle[start:ende]
        gefunden.append(ganzer[1:-1])
        gefunden.append(_entschluessle(ganzer[1:-1], art))
    return gefunden


def kandidaten() -> dict[str, list[str]]:
    ergebnis: dict[str, list[str]] = {}
    for name in DATEIEN:
        quelle = (SRC / name).read_text(encoding="utf-8")
        gefunden: list[str] = []
        if name.endswith(".html"):
            gefunden += [t.strip() for t in TEXTKNOTEN.findall(quelle)]
            gefunden += [t for _, t in ATTRIBUT.findall(quelle)]
        gefunden += literale(quelle)
        ergebnis[name] = sorted({t.strip() for t in gefunden if ist_deutsch(t)})
    return ergebnis


ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "0": "\0"}

#: Wort- und Phrasenersatz für Textstücke, die aus mehreren Teilen zusammengesetzt
#: sind (Zahlen, Namen, HTML). Längere Formen stehen zuerst, damit "Sicht(en)"
#: nicht als "View(en)" endet.
WORTE = [
    ("Referenz-Grid", "Reference grid"),
    ("Referenz Grid", "Reference grid"),
    ("Referenz", "Reference"),
    ("\\u{1F319} Dunkles Design", "🌙 Dark theme"),
    ("\\u2600\\uFE0F Helles Design", "☀️ Light theme"),
    ("Einstiegs-Sichten", "Entry views"),
    ("Einstiegs-Views", "Entry views"),
    ("Hauptbereiche (Packages)", "Main areas (packages)"),
    ("Hauptbereiche", "Main areas"),
    ("Protokoll (CSV)", "Change log (CSV)"),
    ("Verwerfen", "Discard"),
    ("Verbindungen", "Connections"),
    ("Klick: Fokus, Doppelklick: Nachbarschaft isolieren", "Click: focus, double-click: isolate neighbourhood"),
    ("Nachbarschaft", "Neighbourhood"),
    ("Kontext", "Context"),
    ("Inkl. Unterpakete", "Incl. sub-packages"),
    ("inkl. Unterpakete", "incl. sub-packages"),
    ("Unterpakete", "Sub-packages"),
    ("Unterpaket", "Sub-package"),
    ("Kanten", "Edges"),
    ("Diagramme", "Diagrams"),
    ("Dunkles Design", "Dark theme"),
    ("Helles Design", "Light theme"),
    ("Sicht(en)", "View(s)"),
    ("vorhandene Sicht(en)", "existing view(s)"),
    ("Unterpakete", "Sub-packages"),
    ("Unterpaket", "Sub-package"),
    ("Paket-Beschreibung", "Package description"),
    ("Paket-Inhalt", "Package content"),
    ("Paket im Graph visualisieren", "Visualise package in graph"),
    ("Paketpfad", "Package path"),
    ("Paketname", "Package name"),
    ("Sicht im interaktiven Graph erkunden", "Explore view in interactive graph"),
    ("Sicht-Beschreibung", "View description"),
    ("Sicht öffnen", "Open view"),
    ("Sicht bearbeiten", "Edit view"),
    ("Sicht als PNG", "View as PNG"),
    ("Sicht als Excel", "View as Excel"),
    ("Einzel-Sicht", "Single view"),
    ("Sichten (Diagramme)", "Views (diagrams)"),
    ("Sichten", "Views"),
    ("Sicht", "View"),
    ("Pakete", "Packages"),
    ("Paket", "Package"),
    ("Elemente", "Elements"),
    ("Element", "Element"),
    ("Beziehungen", "Connections"),
    ("Beziehung", "Connection"),
    ("Kanten", "Edges"),
    ("Modelle", "Models"),
    ("Modellierungswerkzeug", "modelling tool"),
    ("Modell", "Model"),
    ("Dunkles Design", "Dark theme"),
    ("Helles Design", "Light theme"),
    ("Hilfe & Schnell-Einstieg", "Help & quick start"),
    ("Einstiegs-Sichten", "Entry views"),
    ("Hauptbereiche (Pakete)", "Main areas (packages)"),
    ("Hauptpakete", "Main packages"),
    ("Häufigste Elementtypen", "Most common element types"),
    ("Kurzanleitung", "Quick guide"),
    ("Bearbeiten", "Edit"),
    ("Löschen", "Delete"),
    ("Schließen", "Close"),
    ("Abbrechen", "Cancel"),
    ("Weitere Datei laden", "Load another file"),
    ("Fusionsbericht", "Merge report"),
    ("Zusammenführungen prüfen", "Review merges"),
    ("Verschmelzung auflösen", "Undo merge"),
    ("Ausgewählte zusammenlegen", "Merge selected"),
    ("Ohne Zusammenführung fortfahren", "Continue without merging"),
    ("Alle zeigen", "Show all"),
    ("Inkl. Unterpakete", "Incl. sub-packages"),
    ("Ausgehende Beziehungen", "Outgoing connections"),
    ("Eingehende Beziehungen", "Incoming connections"),
    ("Erlaubte Meta-Modell-Elemente", "Allowed meta-model elements"),
    ("ADMBw-Regelwerk", "ADMBw ruleset"),
    ("ADMBw-Sicht", "ADMBw view"),
    ("Architektur-Sicht", "Architecture view"),
    ("Element-Umfeld", "Element neighbourhood"),
    ("Element-Name", "Element name"),
    ("Exportierte Sicht / Bereich", "Exported view / area"),
    ("Geladenes Modell (.qea)", "Loaded model (.qea)"),
    ("Paket-Beschreibung:", "Package description:"),
    ("Sicht-Beschreibung:", "View description:"),
    ("Paket:", "Package:"),
    ("Sicht:", "View:"),
    ("Modell:", "Model:"),
    ("Element:", "Element:"),
    ("Datei „", "File “"),
    ("Über", "About"),
]


def _escape(ziel: str, art: str) -> str:
    ziel = ziel.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return ziel.replace(art, "\\" + art)


def _wende_worte(text: str) -> str:
    for deutsch, englisch in WORTE:
        text = text.replace(deutsch, englisch)
    return text


def _entschluessle(innen: str, art: str) -> str:
    """Löst die im Literal erlaubten Escape-Folgen auf (nur zum Nachschlagen)."""
    aus = []
    i = 0
    while i < len(innen):
        zeichen = innen[i]
        if zeichen == "\\" and i + 1 < len(innen):
            folge = innen[i + 1]
            if folge in ESCAPES:
                aus.append(ESCAPES[folge])
            elif folge in ("\\", art):
                aus.append(folge)
            else:
                aus.append("\\" + folge)
            i += 2
            continue
        aus.append(zeichen)
        i += 1
    return "".join(aus)


def ersetze_literal(ganz: str, woerter: dict[str, str], offen: set[str]) -> str:
    """Ein Literal, das JS aus zwei Stücken zusammensetzt, ist kein Ganzes.

    ``'…onclick="x(\'' + oid + '\')">'`` beginnt und endet zwar mit ``'``, ist aber
    nur ein Teilstück; ein Ersetzen des Ganzen würde Code zerstören. Solche
    Stücke tragen deshalb ein unescaptes Begrenzerzeichen im Inneren und
    bleiben unangetastet.
    """
    if len(ganz) < 3 or ganz[0] != ganz[-1] or ganz[0] not in "\"'`":
        return ganz
    art = ganz[0]
    if art in "\"'":
        innen_pruefen = ganz[1:-1]
        i = 0
        while i < len(innen_pruefen):
            if innen_pruefen[i] == "\\":
                i += 2
                continue
            if innen_pruefen[i] == art:
                return ganz
            i += 1
    innen = ganz[1:-1]
    entschluesselt = _entschluessle(innen, art)
    schluessel = entschluesselt if entschluesselt in woerter else entschluesselt.strip()
    if schluessel in woerter:
        vorn = entschluesselt[: len(entschluesselt) - len(entschluesselt.lstrip())]
        hinten = entschluesselt[len(entschluesselt.rstrip()):]
        ziel = vorn + woerter[schluessel] + hinten
        return art + _escape(ziel, art) + art
    ziel = _wende_worte(entschluesselt)
    if ziel != entschluesselt:
        return art + _escape(ziel, art) + art
    if ist_deutsch(entschluesselt.strip()):
        offen.add(entschluesselt.strip())
    return ganz


def uebersetze_js(name: str, quelle: str, woerter: dict[str, str], offen: set[str]) -> str:
    ausgabe: list[str] = []
    pos = 0
    for start, ende, _art in _stellen(quelle):
        # Kommentare und Code zwischen den Literalen nicht anfassen.
        ausgabe.append(quelle[pos:start])
        ausgabe.append(ersetze_literal(quelle[start:ende], woerter, offen))
        pos = ende
    ausgabe.append(quelle[pos:])
    return "".join(ausgabe)


def uebersetze_html(quelle: str, woerter: dict[str, str], offen: set[str]) -> str:
    def knoten(m: re.Match) -> str:
        roh = m.group(1)
        vorn = roh[: len(roh) - len(roh.lstrip())]
        hinten = roh[len(roh.rstrip()):]
        mitte = roh.strip()
        if mitte in woerter:
            return ">" + vorn + woerter[mitte] + hinten + "<"
        if ist_deutsch(mitte):
            offen.add(mitte)
        return m.group(0)

    def attr(m: re.Match) -> str:
        wert = m.group(2)
        if wert in woerter:
            return f'{m.group(1)}="{woerter[wert]}"'
        if ist_deutsch(wert):
            offen.add(wert)
        return m.group(0)

    neu = TEXTKNOTEN.sub(knoten, quelle)
    neu = ATTRIBUT.sub(attr, neu)
    neu = neu.replace('<html lang="de"', '<html lang="en"')
    return neu.replace("&amp;", "&")


def baue(name: str, quelle: str, woerter: dict[str, str], offen: set[str]) -> str:
    if name.endswith(".html"):
        # Erst die HTML-Ebene, dann die Literale der Inline-Skripte.
        stuecke = re.split(r"(<script\b.*?</script>)", quelle, flags=re.S)
        teile = []
        for stueck in stuecke:
            if stueck.startswith("<script"):
                teile.append(uebersetze_js(name, stueck, woerter, offen))
            else:
                teile.append(uebersetze_html(stueck, woerter, offen))
        return "".join(teile)
    return uebersetze_js(name, quelle, woerter, offen)


def main() -> int:
    if not WOERTERBUCH.is_file():
        DIST.mkdir(parents=True, exist_ok=True)
        k = kandidaten()
        (DIST / "_kandidaten.json").write_text(
            json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"{sum(len(v) for v in k.values())} Kandidaten nach dist/_kandidaten.json geschrieben.")
        print("Erst src/english.json anlegen, dann erneut starten.")
        return 1

    woerter = json.loads(WOERTERBUCH.read_text(encoding="utf-8"))
    woerter = {k: v for k, v in woerter.items() if not k.startswith("_")}

    FREIGABE.mkdir(parents=True, exist_ok=True)
    offen: set[str] = set()
    for name in DATEIEN:
        quelle = (SRC / name).read_text(encoding="utf-8")
        neu = baue(name, quelle, woerter, offen)
        (FREIGABE / name).write_text(neu, encoding="utf-8")

    # Der Build-Skript liest aus src/ — dort kurzzeitig die englische Fassung
    # einspielen und den Bau danach zurücknehmen.
    sicherung = {n: (SRC / n).read_bytes() for n in DATEIEN}
    try:
        for name in DATEIEN:
            (SRC / name).write_bytes((FREIGABE / name).read_bytes())
        subprocess.check_call([sys.executable, str(SRC / "build_release.py")], cwd=APP)
    finally:
        for name, inhalt in sicherung.items():
            (SRC / name).write_bytes(inhalt)

    gebaut = DIST / "EAM_Suite.html"
    ziel = DIST / "EAM-Suite-en.html"
    if gebaut.is_file():
        ziel.write_bytes(gebaut.read_bytes())
        print(f"geschrieben: {ziel} ({ziel.stat().st_size} Bytes)")

    rest = sorted(offen)
    (DIST / "_englisch_offen.json").write_text(
        json.dumps(rest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{len(rest)} deutsche Stellen blieben offen (dist/_englisch_offen.json).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
