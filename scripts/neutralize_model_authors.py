"""Neutralisiert Autorenangaben in einer .qea-Datei.

Hintergrund: In ``t_object.Author`` und ``t_diagram.Author`` stehen bei
gewachsenen Modellen Klarnamen, Dienststellen und Kennungen der Bearbeiter.
Beim Veroeffentlichen einer Modell-Fixture sind das personenbezogene Daten.

Das Skript setzt diese Felder auf einen neutralen Wert. Es aendert ausschliesslich
die beiden Autorenspalten; Modellstruktur, GUIDs, Namen und Tags bleiben
unangetastet. Andere Spalten mit potentiell personenbezogenen Angaben werden
gemeldet, aber nicht stillschweigend veraendert.

Aufruf::

    python3 scripts/neutralize_model_authors.py <modell.qea> [--wert MASC] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

#: Spalten, die neutralisiert werden (Tabelle -> Spalte).
AUTORSPALTEN: tuple[tuple[str, str], ...] = (
    ("t_object", "Author"),
    ("t_diagram", "Author"),
)

#: Weitere Spalten, die auf personenbezogene Angaben hindeuten. Sie werden nur
#: gemeldet: eine automatische Leerung koennte fachliche Angaben zerstoeren.
MELDESPALTEN: tuple[tuple[str, str], ...] = (
    ("t_document", "Author"),
    ("t_authors", "AuthorName"),
    ("t_script", "ScriptAuthor"),
    ("t_testplans", "Author"),
    ("t_issues", "Owner"),
    ("t_tasks", "Owner"),
    ("t_package", "PkgOwner"),
    ("t_version", "Owner"),
)

STANDARD_WERT = "MASC"


def sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tabellen(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def bericht(con: sqlite3.Connection) -> dict[str, object]:
    """Zaehlt betroffene Zeilen und verschiedene Werte, ohne sie zu nennen."""
    vorhanden = tabellen(con)
    ergebnis: dict[str, object] = {}
    for tabelle, spalte in AUTORSPALTEN:
        if tabelle not in vorhanden:
            ergebnis[f"{tabelle}.{spalte}"] = {"vorhanden": False}
            continue
        zeilen = con.execute(
            f'SELECT COUNT(*) FROM "{tabelle}" WHERE "{spalte}" IS NOT NULL '
            f'AND TRIM("{spalte}")<>"" AND TRIM("{spalte}")<>?', (STANDARD_WERT,)
        ).fetchone()[0]
        werte = con.execute(
            f'SELECT COUNT(DISTINCT "{spalte}") FROM "{tabelle}" WHERE "{spalte}" IS NOT NULL '
            f'AND TRIM("{spalte}")<>"" AND TRIM("{spalte}")<>?', (STANDARD_WERT,)
        ).fetchone()[0]
        ergebnis[f"{tabelle}.{spalte}"] = {"vorhanden": True, "zeilen": zeilen, "werte": werte}
    gemeldet: dict[str, int] = {}
    for tabelle, spalte in MELDESPALTEN:
        if tabelle not in vorhanden:
            continue
        try:
            belegt = con.execute(
                f'SELECT COUNT(*) FROM "{tabelle}" WHERE "{spalte}" IS NOT NULL AND TRIM("{spalte}")<>""'
            ).fetchone()[0]
        except sqlite3.Error:
            continue
        if belegt:
            gemeldet[f"{tabelle}.{spalte}"] = belegt
    ergebnis["weitere_belegte_spalten"] = gemeldet
    return ergebnis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("modell", type=Path)
    parser.add_argument("--wert", default=STANDARD_WERT, help=f"Neutralwert (Standard: {STANDARD_WERT})")
    parser.add_argument("--dry-run", action="store_true", help="nur zaehlen, nichts schreiben")
    args = parser.parse_args(argv)

    if not args.modell.is_file():
        print(f"FEHLER: {args.modell} fehlt", file=sys.stderr)
        return 2

    vorher_hash = sha256(args.modell)
    groesse_vorher = args.modell.stat().st_size
    con = sqlite3.connect(str(args.modell))
    try:
        vorher = bericht(con)
        print(f"Datei: {args.modell} ({groesse_vorher:,} B, sha256 {vorher_hash[:16]}...)")
        for spalte, info in vorher.items():
            if spalte == "weitere_belegte_spalten":
                continue
            print(f"  {spalte}: {info}")
        if vorher["weitere_belegte_spalten"]:
            print(f"  weitere belegte Spalten (nicht geaendert): {vorher['weitere_belegte_spalten']}")
        if args.dry_run:
            print("dry-run: nichts geschrieben")
            return 0

        geaendert = 0
        for tabelle, spalte in AUTORSPALTEN:
            if tabelle not in tabellen(con):
                continue
            cur = con.execute(
                f'UPDATE "{tabelle}" SET "{spalte}"=? WHERE "{spalte}" IS NOT NULL '
                f'AND TRIM("{spalte}")<>"" AND TRIM("{spalte}")<>?', (args.wert, args.wert)
            )
            geaendert += cur.rowcount
            print(f"  {tabelle}.{spalte}: {cur.rowcount} Zeilen gesetzt")
        con.commit()
        print("  PRAGMA quick_check:", con.execute("PRAGMA quick_check").fetchone()[0])
        nachher = bericht(con)
        offen = sum(
            info.get("zeilen", 0) for spalte, info in nachher.items()
            if spalte != "weitere_belegte_spalten" and isinstance(info, dict)
        )
        print(f"  offene Autorenwerte danach: {offen}")

        # Ein UPDATE ueberschreibt die Zelle, gibt die alte Seite aber nur frei.
        # Die alten Werte bleiben dann im Dateiabbild lesbar (Strings-Suche).
        # VACUUM baut die Datei neu und entfernt diese Reste.
        frei_vorher = con.execute("PRAGMA freelist_count").fetchone()[0]
        con.execute("VACUUM")
        frei_nachher = con.execute("PRAGMA freelist_count").fetchone()[0]
        print(f"  VACUUM: freie Seiten {frei_vorher} -> {frei_nachher}")
        print("  PRAGMA quick_check danach:", con.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        con.close()

    nachher_hash = sha256(args.modell)
    print(f"  Bytes: {groesse_vorher:,} -> {args.modell.stat().st_size:,}")
    print(f"  sha256: {vorher_hash} -> {nachher_hash}")
    print(f"  geaenderte Zeilen: {geaendert}")
    return 0 if offen == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
