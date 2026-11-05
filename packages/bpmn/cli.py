"""Kommandozeile des BPMN Studio.

    python -m bpmn.cli pruefen prozess.bpmn
    python -m bpmn.cli konform prozess.bpmn -o konform.bpmn
    python -m bpmn.cli export prozess.bpmn --format svg -o bild.svg
    python -m bpmn.cli extrahieren text.txt -o prozess.bpmn

Die Befehle arbeiten ohne Netz. Der KI-Adapter ist optional und nur aktiv,
wenn er ausdruecklich konfiguriert ist.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import admbw, bpmn_xml, exporte, extraktion


def _lies(pfad: str):
    return bpmn_xml.lies(pfad)


def _befund_zeile(befund) -> str:
    return f"{befund.regel} [{befund.schwere}] {befund.objekt}: {befund.hinweis}"


def _pruefen(args) -> int:
    modell = _lies(args.datei)
    befunde = admbw.pruefe(modell)
    for befund in befunde:
        print(_befund_zeile(befund))
    fehler = sum(1 for b in befunde if b.schwere == "fehler")
    print(f"{len(befunde)} Befunde, davon {fehler} Fehler")
    return 1 if fehler else 0


def _konform(args) -> int:
    modell = _lies(args.datei)
    bericht = admbw.konform_machen(modell)
    ziel = Path(args.ausgabe)
    ziel.write_text(bpmn_xml.schreibe_text(modell), encoding="utf-8")
    for eintrag in bericht.aenderungen:
        print(eintrag)
    for eintrag in bericht.offen:
        print(f"offen: {eintrag}")
    rest = admbw.pruefe(modell)
    rest_fehler = [b for b in rest if b.schwere == "fehler"]
    print(f"geschrieben: {ziel} | offene Fehler: {len(rest_fehler)}")
    return 1 if rest_fehler else 0


def _export(args) -> int:
    modell = _lies(args.datei)
    ziel = Path(args.ausgabe)
    if args.format == "xml":
        ziel.write_text(bpmn_xml.schreibe_text(modell), encoding="utf-8")
    elif args.format == "svg":
        ziel.write_text(exporte.svg_text(modell), encoding="utf-8")
    else:
        ziel.write_bytes(exporte.exportiere_png(modell))
    print(f"geschrieben: {ziel} ({ziel.stat().st_size} Bytes)")
    return 0


def _extrahieren(args) -> int:
    text = Path(args.datei).read_text(encoding="utf-8")
    ergebnis = extraktion.extrahiere(text, anweisung=args.anweisung)
    modell = ergebnis.modell if hasattr(ergebnis, "modell") else ergebnis
    ziel = Path(args.ausgabe)
    ziel.write_text(bpmn_xml.schreibe_text(modell), encoding="utf-8")
    for hinweis in getattr(ergebnis, "hinweise", []):
        print(f"hinweis: {hinweis}")
    print(f"geschrieben: {ziel} | {len(modell.knoten)} Knoten, {len(modell.fluesse)} Fluesse")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bpmn", description="BPMN Studio (Kommandozeile)")
    unter = parser.add_subparsers(dest="befehl", required=True)

    p = unter.add_parser("pruefen", help="Modell gegen die ADMBw-Regeln pruefen")
    p.add_argument("datei")
    p.set_defaults(funktion=_pruefen)

    k = unter.add_parser("konform", help="ADMBw-konform machen und speichern")
    k.add_argument("datei")
    k.add_argument("-o", "--ausgabe", required=True)
    k.set_defaults(funktion=_konform)

    e = unter.add_parser("export", help="als XML, SVG oder PNG ausgeben")
    e.add_argument("datei")
    e.add_argument("--format", choices=("xml", "svg", "png"), default="svg")
    e.add_argument("-o", "--ausgabe", required=True)
    e.set_defaults(funktion=_export)

    x = unter.add_parser("extrahieren", help="aus Prosa ein Prozessmodell ableiten")
    x.add_argument("datei")
    x.add_argument("-o", "--ausgabe", required=True)
    x.add_argument("--anweisung", default=None,
                   help='Auftrag in eigenen Worten, z. B. "extrahiere den Prozess Rechnungslauf"')
    x.set_defaults(funktion=_extrahieren)

    args = parser.parse_args(argv)
    return args.funktion(args)


if __name__ == "__main__":
    sys.exit(main())
