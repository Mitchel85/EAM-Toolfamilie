"""Bereinigt die Modellierungskonventionen von Tabellen- und Abbildungstext.

Die Extraktion aus dem Leitfaden-PDF hat bei vielen Eintraegen den Text der
folgenden Tabelle und der Beispielabbildung mitgenommen. Diese Eintraege landen
so in den KI-Prompts: Sie zitieren fremde Inhalte, verlaengern den Prompt und
verwischen, welche Aussage zur Konvention gehoert.

Regel: Der Konventionstext endet vor der ersten Ueberschrift ``Tabelle N:``
oder ``Abbildung N:``. Alles danach ist Beschriftung, Tabellenzellen oder
Fließtext des naechsten Kapitels. Anschliessend werden Leerraum und
abschliessende Trennzeichen normalisiert.

Aufruf::

    python3 scripts/clean_konventionen.py [datei.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

STANDARD = Path(__file__).resolve().parents[1] / "knowledge" / "leitfaden" / "konventionen.json"

#: Erste Ueberschrift, ab der der Konventionstext endet.
SCHNITT = re.compile(r"\b(?:Tabelle|Abbildung)\s+\d+\s*:")

#: Tabellenkopf ohne Beschriftung ("Modellierungskonventionen Nummer ... Verweis").
#: Steht er hinter einem Satzende, beginnt dort die Tabelle (schneiden). Steht er
#: mitten im Satz, ist er nur hineingerutscht (entfernen).
TABELLENKOPF = re.compile(
    r"\s*Modellierungskonventionen\s+Nummer\s+Modellierungskonvention\s+Verweis\s*"
)

#: Abschliessende Trennzeichen, die nach dem Schnitt uebrig bleiben ("angelegt. -").
ABSCHLUSS = re.compile(r"[\s\-–—;:,]+$")

MK_KENNUNG = re.compile(r"\b([A-Z]{1,2}\d+(?:-[A-Z]\d+)?)-MK\d+\b")


def bereinige_text(text: str) -> str:
    """Schneidet Tabellen-/Abbildungsteil ab und normalisiert den Rest."""
    treffer = SCHNITT.search(text)
    kern = text[: treffer.start()] if treffer else text

    kopf = TABELLENKOPF.search(kern)
    if kopf:
        vorher = kern[: kopf.start()].rstrip()
        if vorher.endswith((".", "!", "?")):
            kern = vorher  # Tabelle beginnt hier
        else:
            kern = kern[: kopf.start()] + " " + kern[kopf.end():]  # Kopf entfernen

    kern = re.sub(r"\s+", " ", kern).strip()
    kern = ABSCHLUSS.sub("", kern)
    return kern.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("datei", nargs="?", type=Path, default=STANDARD)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    daten = json.loads(args.datei.read_text(encoding="utf-8"))
    vorher_zeichen = sum(len(e.get("text", "")) for e in daten)
    geaendert = 0
    leer = 0
    fremd = 0

    for eintrag in daten:
        alt = eintrag.get("text", "")
        neu = bereinige_text(alt)
        if neu != alt:
            geaendert += 1
        if not neu:
            leer += 1
            neu = alt  # nie einen Eintrag leeren -- lieber unbereinigt lassen
        eintrag["text"] = neu
        for m in MK_KENNUNG.finditer(neu):
            if m.group(0) != eintrag.get("id"):
                fremd += 1

    nachher_zeichen = sum(len(e.get("text", "")) for e in daten)
    print(f"Datei: {args.datei}")
    print(f"  Einträge: {len(daten)}")
    print(f"  geändert: {geaendert} | leer geblieben (unverändert gelassen): {leer}")
    print(f"  Zeichen: {vorher_zeichen:,} -> {nachher_zeichen:,} "
          f"({100 * (vorher_zeichen - nachher_zeichen) // max(vorher_zeichen, 1)} % weniger)")
    print(f"  fremde MK-Kennungen im Text: {fremd}")

    if args.dry_run:
        print("  dry-run: nichts geschrieben")
        return 0

    args.datei.write_text(json.dumps(daten, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("  geschrieben")
    return 0 if fremd == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
