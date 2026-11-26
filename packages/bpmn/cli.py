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
import tempfile
from pathlib import Path

from . import admbw, bpmn_xml, exporte, extraktion, ki

try:
    from core import eam_ai, image_input, extract
except ImportError:
    from packages.core import eam_ai, image_input, extract


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
    elif args.format == "qea":
        from . import qea_bpmn

        qea_bpmn.schreibe_qea(
            modell,
            ziel,
            katalog=getattr(args, "katalog", None),
            bestand_verbinden=bool(getattr(args, "bestand_verbinden", False)),
        )
    else:
        ziel.write_bytes(exporte.exportiere_png(modell))
    print(f"geschrieben: {ziel} ({ziel.stat().st_size} Bytes)")
    return 0


def _lies_eingabe(datei_pfad: str | Path, ki_aktiv: bool = False) -> str:
    quelle = Path(datei_pfad)
    if not quelle.is_file():
        raise FileNotFoundError(f"Eingabedatei existiert nicht: {quelle}")

    suffix = quelle.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp"):
        if not ki_aktiv:
            raise ValueError(
                f"Bilddatei {quelle.name}: Bildanalyse erfordert das Flag --ki (multimodaler KI-Adapter)."
            )
        # Companion-Datei (<stem>.txt oder <stem>.md) hat Vorrang (offline/deterministisch)
        for ext in (".txt", ".md"):
            companion = quelle.with_suffix(ext)
            if companion.is_file():
                inhalt = companion.read_text(encoding="utf-8").strip()
                if inhalt:
                    return inhalt
        cfg = ki.lade_konfiguration()
        if not ki.konfiguriert(cfg):
            raise ki.KINichtKonfiguriert(
                f"KI fuer Bildanalyse nicht konfiguriert: {ki.status(cfg).get('grund')}"
            )
        backend = extract.OpenAICompatibleBackend(
            model=cfg.modell,
            base_url=cfg.basis_url,
            api_key=cfg.key,
            timeout=cfg.timeout,
        )
        prompt = (
            "Beschreibe den in diesem Bild dargestellten Geschaeftsprozess oder Ablauf "
            "detailliert in Schritten, inklusive Rollen, Aktionen, Objekten und Bedingungen."
        )
        return image_input.describe_image(quelle, backend, prompt=prompt)

    # Dokumente oder Textdateien
    embedded_images: list[tuple[bytes, str, str]] = []
    text = eam_ai.read_text_source(quelle, image_sink=embedded_images)

    if embedded_images and ki_aktiv:
        cfg = ki.lade_konfiguration()
        if ki.konfiguriert(cfg):
            backend = extract.OpenAICompatibleBackend(
                model=cfg.modell,
                base_url=cfg.basis_url,
                api_key=cfg.key,
                timeout=cfg.timeout,
            )
            with tempfile.TemporaryDirectory() as tmp_dir_str:
                tmp_dir = Path(tmp_dir_str)
                bildbloecke = []
                for img_bytes, img_name, _ in embedded_images:
                    tmp_img = tmp_dir / img_name
                    tmp_img.write_bytes(img_bytes)
                    try:
                        desc = image_input.describe_image(tmp_img, backend)
                        bildbloecke.append(f"[Bildquelle: {img_name}]\n{desc}")
                    except Exception:
                        bildbloecke.append(f"[Eingebettetes Bild: {img_name}]")
                if bildbloecke:
                    text = text + "\n\n" + "\n\n".join(bildbloecke)

    return text


def _extrahieren(args) -> int:
    ki_aktiv = getattr(args, "ki", False)
    text = _lies_eingabe(args.datei, ki_aktiv=ki_aktiv)
    if ki_aktiv:
        ergebnis = ki.extrahiere_mit_ki(text, anweisung=args.anweisung)
    else:
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

    e = unter.add_parser("export", help="als XML, SVG, PNG oder QEA ausgeben")
    e.add_argument("datei")
    e.add_argument("--format", choices=("xml", "svg", "png", "qea"), default="svg")
    e.add_argument("--katalog", default=None, help="L2/L3-Architekturmodell (.qea/.xmi/.xml/.json) zur GUID-Kopplung")
    e.add_argument("--bestand-verbinden", action="store_true", help="Bei .qea-Katalog Prozess direkt ins Gesamtmodell mergen")
    e.add_argument("-o", "--ausgabe", required=True)
    e.set_defaults(funktion=_export)

    x = unter.add_parser("extrahieren", help="aus Prosa ein Prozessmodell ableiten")
    x.add_argument("datei")
    x.add_argument("-o", "--ausgabe", required=True)
    x.add_argument("--anweisung", default=None,
                   help='Auftrag in eigenen Worten, z. B. "extrahiere den Prozess Rechnungslauf"')
    x.add_argument("--ki", action="store_true", default=False,
                   help="optionalen KI-Adapter fuer Extraktion und Bildverarbeitung nutzen")
    x.set_defaults(funktion=_extrahieren)

    args = parser.parse_args(argv)
    return args.funktion(args)


if __name__ == "__main__":
    sys.exit(main())
