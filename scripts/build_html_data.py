#!/usr/bin/env python3
"""Schreibt ADMBW_DATA fuer die HTML-Suite aus dem Regelwerk-Artefakt.

Die HTML-Suite ist eine Einzeldatei und kann zur Laufzeit nichts nachladen.
Deshalb bekommt sie ihre Referenzdaten beim **Bauen** eingeschrieben -- aus
``knowledge/regelwerk.json``, nicht aus einer zweiten, von Hand gepflegten
Kopie im Quelltext.

Erzeugt werden:

* ``grid`` -- die Viewpoint-Matrix (fuenf NAF-Ebenen plus Anforderungen und
  Bruecken-Sichten),
* ``vp``   -- je Viewpoint: englischer Name, Ebene, Elementliste, Beschreibung,
* ``topo`` -- erlaubte Beziehungen je Viewpoint aus der MDG.

Die englischen Beschreibungen sind Fachtext, keine Regel: sie stehen einmal in
``knowledge/viewpoint-descriptions.json`` und werden hier nur eingesetzt.

Aufruf::

    python3 scripts/build_html_data.py --schreiben   # Quelldatei ersetzen
    python3 scripts/build_html_data.py --pruefen     # nur vergleichen
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGELWERK = ROOT / "knowledge" / "regelwerk.json"
BESCHREIBUNGEN = ROOT / "knowledge" / "viewpoint-descriptions.json"
#: Ziel je App. Beide Altwerkzeuge tragen denselben Datenblock.
ZIELE = {
    "html-suite": ROOT / "apps" / "html-suite" / "src" / "part0_reader_data.js",
    "html-editor": ROOT / "apps" / "html-editor" / "src" / "part0_reader_data.js",
}

BEGINN = "var ADMBW_DATA = "
ENDE = ";\n"

#: Reihenfolge der Ebenen in der Matrix. Die Namen kommen aus der Leitfaden-
#: Abbildung; sie sind Anzeige, keine Regel.

#: (Schluessel, Anzeigename, Beschreibung, Gruppe im Artefakt, neun Zellen)
MATRIX = [
    ("Concept", "Konzepte", "Strategischer Kontext: Fähigkeiten, Vision, Abhängigkeiten",
     "Concept Viewpoints",
     ["C1", "C2", "C3", "C4", "C5", None, "C7", "C8", "Cr"]),
    ("Service", "Dienste", "Service-Spezifikation: Dienste, Schnittstellen, Funktionen",
     "Service Specification Viewpoints",
     ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "Sr"]),
    ("Logical", "Logisch", "Logische Spezifikation: Knoten, Aktivitäten, Informationsmodell",
     "Logical Specification Viewpoints",
     ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "Lr"]),
    ("Physical", "Physisch", "Physische Ressourcen: Typen, Struktur, Konnektivität",
     "Physical Resource Specification Viewpoints",
     ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "Pr"]),
    ("ArchFdn", "Architektur-Grundlagen", "Architekturgrundlagen: Metadaten, Produkte, Standards",
     "Architecture Foundation Viewpoints",
     ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "Ar"]),
    ("Req", "Anforderungen", "Anforderungs-Viewpoints: Katalog, Abhängigkeiten, Erfüllung",
     "Requirement Viewpoints",
     [None, "R2", "R3", "R7", "R8", None, None, None, "Rr"]),
]



def _name(titel: str) -> str:
    """'C2 - Enterprise Vision' -> 'Enterprise Vision'."""
    return titel.split(" - ", 1)[1] if " - " in titel else titel


def erzeuge(regelwerk: dict, beschreibungen: dict) -> dict:
    viewpoints = regelwerk["viewpoints"]

    # --- vp
    vp: dict[str, dict] = {}
    for code, eintrag in viewpoints.items():
        if code in {"St", "VÜ"}:
            continue
        elemente = sorted(eintrag["mdg"]["elemente"])
        if not elemente:
            continue
        vp[code] = {
            "n": _name(eintrag["titel"]),
            "layer": eintrag["gruppe"],
            "cnt": len(elemente),
            "els": elemente,
            "desc": beschreibungen.get(code, ""),
        }

    # --- grid: die NAF-Matrix (Abbildung 1). Die neun Spalten sind eine
    # Darstellung der Methode, keine Regel -- welche Sicht in welcher Zelle
    # steht, ist hier festgelegt und wird gegen die vorhandenen Sichten geprueft.
    zeilen = []
    for schluessel, label, desc, gruppe, zellen in MATRIX:
        fehlend = [c for c in zellen if c and c not in vp]
        if fehlend:
            raise SystemExit(f"Matrix nennt unbekannte Sichten: {fehlend}")
        zeilen.append({"layer": schluessel, "label": label, "desc": desc, "cells": zellen})
    zeilen.append({
        "layer": "Mapping",
        "label": "Bridge/Mapping",
        "desc": "Brücken-Sichten zwischen Bereichen",
        "cells": ["C1-S1", "L2-L3", "L4-P4", None, None, None, None, None, None],
        "bridge": True,
    })

    # --- topo
    topo: dict[str, list] = {}
    for code, eintrag in viewpoints.items():
        regeln = [
            {"rel": stereo, "from": [quelle], "to": [ziel]}
            for stereo, quelle, ziel in eintrag["mdg"]["konnektoren"]
        ]
        if regeln:
            regeln.sort(key=lambda r: (r["rel"], r["from"][0], r["to"][0]))
            topo[code] = regeln

    return {
        "grid": {
            "cols": ["taxonomy", "structure", "connectivity", "processes", "states",
                     "sequences", "information", "constraints", "roadmap"],
            "col_de": ["Taxonomie", "Struktur", "Konnektivität", "Prozesse", "Zustände", "Sequenzen", "Information", "Restriktionen", "Roadmap"],
            "rows": zeilen,
        },
        "vp": dict(sorted(vp.items())),
        "topo": dict(sorted(topo.items())),
    }


def als_js(daten: dict) -> str:
    return BEGINN + json.dumps(daten, ensure_ascii=False, separators=(",", ":")) + ";\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="ADMBW_DATA aus dem Regelwerk erzeugen")
    ap.add_argument("--app", choices=sorted(ZIELE), default="html-suite", help="welche App")
    ap.add_argument("--schreiben", action="store_true", help="Quelldatei ersetzen")
    ap.add_argument("--pruefen", action="store_true", help="nur vergleichen")
    args = ap.parse_args()

    regelwerk = json.loads(REGELWERK.read_text(encoding="utf-8"))
    beschreibungen = json.loads(BESCHREIBUNGEN.read_text(encoding="utf-8"))
    neu = erzeuge(regelwerk, beschreibungen)
    block = als_js(neu)

    ZIEL = ZIELE[args.app]
    quelle = ZIEL.read_text(encoding="utf-8")
    if BEGINN not in quelle:
        print(f"{ZIEL.name}: kein ADMBW_DATA gefunden", file=sys.stderr)
        return 1
    anfang = quelle.index(BEGINN)
    # Bis zur schliessenden Klammer zaehlen -- im JSON steht kein Zeilenumbruch,
    # ein Semikolon kann aber in Text vorkommen.
    tiefe = 0
    for pos in range(anfang, len(quelle)):
        if quelle[pos] == "{":
            tiefe += 1
        elif quelle[pos] == "}":
            tiefe -= 1
            if tiefe == 0:
                ende = pos + 1
                break
    else:
        print(f"{ZIEL.name}: ADMBW_DATA nicht geschlossen", file=sys.stderr)
        return 1
    if quelle[ende:ende + 1] == ";":
        ende += 1
    vorhanden = quelle[anfang:ende]

    if args.pruefen:
        if vorhanden.rstrip("\n") == block.rstrip("\n"):
            print(f"ADMBW_DATA unveraendert ({len(neu['vp'])} Viewpoints, {len(neu['topo'])} Topologien)")
            return 0
        print("ADMBW_DATA weicht ab -- neu schreiben mit --schreiben", file=sys.stderr)
        return 1

    if not args.schreiben:
        print(block[:400] + " ...")
        print(f"\n{len(block):,} Zeichen, {len(neu['vp'])} Viewpoints, {len(neu['topo'])} Topologien")
        return 0

    ZIEL.write_text(quelle[:anfang] + block.rstrip("\n") + quelle[ende:], encoding="utf-8")
    print(f"{ZIEL.relative_to(ROOT)}: ADMBW_DATA neu geschrieben")
    print(f"  {len(block):,} Zeichen | {len(neu['vp'])} Viewpoints | {len(neu['topo'])} Topologien")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
