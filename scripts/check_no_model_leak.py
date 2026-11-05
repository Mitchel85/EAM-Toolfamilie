"""Prueft: steht irgendwo im Anwendungscode ein Element aus einem Testmodell?

Die Werkzeuge muessen fuer jeden Architekturauftrag funktionieren. Ein Name aus
dem Testmodell im Anwendungscode waere eingebautes Wissen ueber die erwartete
Antwort. Quelle der Pruefnamen ist ein Modell (.qea), das nur als Pruefgrundlage
dient (Standard: das oeffentliche Testmodell unter ``packages/core/fixtures``).
Geprueft wird ausschliesslich Anwendungscode und Dokumentation -- keine
Fixtures, keine Tests, keine gebauten Dateien.

Zusaetzlich prueft das Skript das Modell selbst auf Autorenangaben. In
``t_object.Author`` und ``t_diagram.Author`` stehen bei gewachsenen Modellen
Klarnamen, Dienststellen und Kennungen. Eine veroeffentlichte Fixture darf
davon nichts enthalten; erlaubt sind nur leere Werte und der Neutralwert
``MASC``.

Aufruf::

    python3 scripts/check_no_model_leak.py [modell.qea] [--bericht treffer.json]

Exit-Code 1, wenn ein Name im Anwendungscode gefunden wird oder wenn das Modell
nicht neutralisierte Autorenangaben enthaelt.
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
    # Begriffe, die der Leitfaden selbst vorgibt (Viewpoint- und Sichtnamen,
    # Einstufungswerte, Paketnamen) -- sie stammen nicht aus dem Testmodell,
    # sondern aus der methodischen Vorgabe.
    "Fähigkeitsforderungen", "Fähigkeitsforderung", "Serviceabhängigkeiten", "Abkürzungsverzeichnis",
    "VS-NUR FÜR DEN DIENSTGEBRAUCH", "VS-VERTRAULICH",
}

DATEIENDUNGEN = {".py", ".js", ".html", ".css", ".json", ".toml", ".ys", ".txt", ".md"}
AUSGESCHLOSSEN = ("/fixtures/", "/dist/", "/node_modules/", "/.git/", "/tests/",
                  "/build/", "/vendor/", "/__pycache__/", "/CHANGELOG",
                  # Die Wissensbasis ist die Vorgabe selbst: der Leitfaden
                  # enthaelt MASC als Beispielmodellierung, masc_paketbaum.json
                  # ist bewusst daraus abgeleitet. Ein Treffer dort ist kein
                  # eingebautes Wissen, sondern die Quelle.
                  "/knowledge/leitfaden/", "/knowledge/masc_paketbaum.json",
                  "/knowledge/modelwizard/",
                  # skeleton_arch.py baut bewusst die MASC-Struktur (Vergleichs-
                  # pfad --geruest masc). Die MASC-Paketnamen sind dort Zweck,
                  # nicht Leck.
                  "/packages/core/skeleton_arch.py")


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


def pruefe_autoren(modell: Path) -> dict[str, int]:
    """Zaehlt Autorenwerte, die weder leer noch der Neutralwert sind.

    Personenbezug entsteht nicht durch die Anzahl, sondern durch den Inhalt:
    Klarnamen, Dienststellen und numerische Kennungen. Deshalb wird hier nicht
    auf ein Muster geprueft, sondern auf alles, was nicht ausdruecklich erlaubt
    ist -- ein neuer Bearbeitername faellt damit sofort auf.
    """
    erlaubt = {"", "MASC"}
    befunde: dict[str, int] = {}
    con = sqlite3.connect(f"file:{modell}?mode=ro", uri=True)
    try:
        vorhanden = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for tabelle, spalte in (("t_object", "Author"), ("t_diagram", "Author")):
            if tabelle not in vorhanden:
                continue
            werte = [
                r[0] for r in con.execute(
                    f'SELECT DISTINCT "{spalte}" FROM "{tabelle}" '
                    f'WHERE "{spalte}" IS NOT NULL AND TRIM("{spalte}")<>""'
                )
            ]
            offen = [w for w in werte if str(w).strip() not in erlaubt]
            if offen:
                befunde[f"{tabelle}.{spalte}"] = len(offen)
    finally:
        con.close()
    return befunde


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("modell", nargs="?", type=Path, default=STANDARD_MODELL)
    parser.add_argument("--bericht", type=Path, default=None, help="Treffer als JSON")
    args = parser.parse_args(argv)

    autoren = pruefe_autoren(args.modell)
    if autoren:
        print("PERSONENBEZUG: Autorenangaben nicht neutralisiert")
        for spalte, anzahl in autoren.items():
            print(f"  {spalte}: {anzahl} verschiedene Werte")
        print("  Behebung: python3 scripts/neutralize_model_authors.py <modell.qea>")
    else:
        print(f"Autorenangaben in {args.modell.name}: neutral")

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
    return 1 if (treffer or autoren) else 0


if __name__ == "__main__":
    sys.exit(main())
