"""Prueft: steht irgendwo im Anwendungscode ein Element aus einem Testmodell?

Die Werkzeuge muessen fuer jeden Architekturauftrag funktionieren. Ein Name aus
dem Testmodell im Anwendungscode waere eingebautes Wissen ueber die erwartete
Antwort. Quelle der Pruefnamen ist ein Modell (.qea), das nur als Pruefgrundlage
dient (Standard: das oeffentliche Testmodell unter ``packages/core/fixtures``).
Geprueft wird ausschliesslich Anwendungscode und Dokumentation -- keine
Fixtures, keine Tests, keine gebauten Dateien.

Aufruf::

    python3 scripts/check_no_model_leak.py [modell.qea] [--bericht treffer.json]

Exit-Code 1, wenn ein Name gefunden wird.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
STANDARD_MODELL = WURZEL / "packages/core/fixtures/Musterarchitektur_MASC.qea"

#: Woerter, die im Testmodell als Name vorkommen, aber nicht aus ihm stammen:
#: Begriffe des Metamodells (Stereotypen, Spalten) und allgemeine Fachwoerter.
#: Hier steht nichts, was nur dieses eine Modell kennt.
TECHNISCH = {
    "Software", "Information", "Organisation", "Organization", "Functions",
    "Capabilities", "Dimension", "Transport", "Position", "Struktur", "Architekt",
    "Viewpoints", "Standards", "Protocols", "Framework", "EnterpriseGoal",
    "EnterpriseVision", "MeasurandType", "MeasurementType", "OperationalPerformer",
    "Modellelementekatalog", "Referenzarchitektur", "Systemarchitektur",
    "Bundeswehr", "required", "provided", "gespeichert", "vergleichen", "Meldung",
    "Bericht", "Katalog", "Einheit", "Fähigkeit", "Wirkung", "Betrieb", "Nachricht",
    "Spezialist", "Ebene 1",
    # allgemeine Fachwoerter (Tag-Namen, Erklaertexte, Metamodell-Doku)
    "Verfügbarkeit", "Domäne", "Führung", "Unterstützung",
}

DATEIENDUNGEN = {".py", ".js", ".html", ".css", ".json", ".toml", ".ys", ".txt", ".md"}
AUSGESCHLOSSEN = ("/fixtures/", "/dist/", "/node_modules/", "/.git/", "/tests/",
                  "/build/", "/vendor/", "/__pycache__/", "/CHANGELOG")


def pruefnamen(modell: Path) -> list[str]:
    con = sqlite3.connect(f"file:{modell}?mode=ro", uri=True)
    try:
        namen = sorted({
            str(name).strip()
            for (name,) in con.execute(
                "select Name from t_object where Name is not null and length(trim(Name)) >= 6"
            )
        })
    finally:
        con.close()
    return [
        n for n in namen
        if n not in TECHNISCH
        and (" " in n or re.search(r"[a-zäöüß]", n))
        and not re.fullmatch(r"[\d\s.,:/%GBit\-\+a-zA-Z]*", n)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("modell", nargs="?", type=Path, default=STANDARD_MODELL)
    parser.add_argument("--bericht", type=Path, default=None, help="Treffer als JSON")
    args = parser.parse_args(argv)

    namen = pruefnamen(args.modell)
    print(f"Pruefnamen aus {args.modell.name}: {len(namen)}")
    muster = re.compile("|".join(re.escape(n) for n in sorted(namen, key=len, reverse=True)))
    eigene = Path(__file__).resolve()

    treffer: dict[str, list[str]] = {}
    for pfad in sorted(WURZEL.rglob("*")):
        if not pfad.is_file() or pfad.suffix not in DATEIENDUNGEN or pfad.resolve() == eigene:
            continue
        text_p = pfad.as_posix()
        if any(teil in text_p for teil in AUSGESCHLOSSEN):
            continue
        if pfad.name.startswith(("Musterarchitektur", "MASC")):
            continue
        try:
            inhalt = pfad.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        gefunden = sorted(set(muster.findall(inhalt)))
        if gefunden:
            treffer[pfad.relative_to(WURZEL).as_posix()] = gefunden[:12]

    if args.bericht:
        args.bericht.parent.mkdir(parents=True, exist_ok=True)
        args.bericht.write_text(json.dumps(treffer, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Dateien mit Treffern: {len(treffer)}")
    for datei, gefunden in treffer.items():
        print(f"  {datei}: {gefunden}")
    return 1 if treffer else 0


if __name__ == "__main__":
    sys.exit(main())
