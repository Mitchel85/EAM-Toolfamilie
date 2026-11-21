#!/usr/bin/env python3
"""Prüft die amtliche Quelle auf ein neues Regelwerk und übernimmt es.

    python3 scripts/regelwerk_update.py --pruefen
    python3 scripts/regelwerk_update.py --uebernehmen [--protokoll datei.md]

Die Quelle ist die BAAINBw-Seite „Methode Architektur". Die ``resource/blob``-
Links dort sind die einzige Wahrheit für neue Versionen; verglichen wird gegen
den Stand in ``scripts/fetch_quellen.py`` (``DATEIEN``). Der Blob-Pfad enthält
einen Hash — ändert er sich, liegt eine neue Fassung vor.

``--pruefen`` meldet nur (Exit 0 = Stand aktuell, Exit 2 = Neues vorhanden).
``--uebernehmen`` führt den Ablauf aus, den ``packages/rules/mdg_source.py``
beschreibt, automatisiert aus:

1. MDG-ZIP herunterladen und das XML daraus entpacken.
2. **PII neutralisieren**: E-Mail-Adressen werden durch den Neutralwert
   ``support@example.invalid`` ersetzt — dieselbe Behandlung, die die
   bereits im Repository liegende Fassung erfahren hat (die amtliche Datei
   enthält eine Absenderadresse). Ohne diesen Schritt landen
   personenbezogene Angaben im Repository.
3. Nach ``packages/rules/`` legen, ``packages/rules/CURRENT`` setzen.
4. ``scripts/propagate.py --write`` weiterreichen (Wissensbasis, Artefakte).
5. Den neuen Blob-Pfad in ``fetch_quellen.py`` eintragen.

Geänderte Quellen ohne Regelbezug (PDFs, Handbücher) werden nur ins Protokoll
geschrieben; deren Aufbereitung bleibt der beschriebene Handweg
(``fetch_quellen.py`` → ``extract_leitfaden.py`` → ``build_regelwerk.py``).

Direkte Commits auf ``main`` macht dieses Skript nie — der Workflow legt den
Branch ``rules/auto-update`` an und öffnet einen PR.
"""
from __future__ import annotations

import argparse
import gzip
import io
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SEITE = (
    "https://www.bundeswehr.de/de/organisation/ausruestung-baainbw/"
    "vergabe/methode-architektur"
)
BASIS = "https://www.bundeswehr.de/resource/blob/"

FETCH = ROOT / "scripts" / "fetch_quellen.py"
RULES = ROOT / "packages" / "rules"
CURRENT = RULES / "CURRENT"

#: PII-Neutralwert — identisch zur bereits eingelagerten Fassung.
NEUTRALWERT = b"support@example.invalid"
#: E-Mail-Muster als Bytes: die MDG ist windows-1252, ASCII-Muster bleiben
#: unter allen Zeichenständen gleich.
EMAIL = re.compile(rb"[\w.+-]+@[\w.-]+\.\w+")
#: Blob-Pfade auf der Quellseite; gespeichert wird der Pfad ohne
#: `resource/blob/`-Präfix, so wie ihn fetch_quellen.py führt.
BLOB = re.compile(r"resource/blob/\d+/[a-f0-9]+/[^\"'?\s]+")
#: Tupel in der DATEIEN-Liste von fetch_quellen.py.
TUPEL = re.compile(r'\("([^"]+)",\s*"([^"]+)"\)')


def lade_seite() -> str:
    """Quellseite laden; die Antwort kommt gzip-komprimiert, egal was wir bitten."""
    anfrage = urllib.request.Request(
        SEITE,
        headers={"User-Agent": "EAM-Toolfamilie-Regelwerk-Waechter/1.0"},
    )
    with urllib.request.urlopen(anfrage, timeout=60) as antwort:
        roh = antwort.read()
        if roh[:2] == b"\x1f\x8b":
            roh = gzip.decompress(roh)
    return roh.decode("utf-8", "replace")


def finde_blobs(text: str) -> dict[str, str]:
    """Ressourcennamen -> Blob-Pfad; der Name am Ende ist über Versionen stabil.

    Der Pfad wird ohne `resource/blob/`-Präfix geführt — genau so steht er in
    `fetch_quellen.py`, und `lade_blob` hängt das Präfix wieder davor.
    """
    gefunden: dict[str, str] = {}
    for pfad in BLOB.findall(text):
        pfad = pfad.removeprefix("resource/blob/")
        name = pfad.rsplit("/", 1)[-1]
        gefunden[name] = pfad
    return gefunden


def bekannter_stand() -> dict[str, str]:
    """DATEIEN aus fetch_quellen.py: lokaler Name -> Blob-Pfad."""
    text = FETCH.read_text(encoding="utf-8")
    anfang = text.index("DATEIEN = [")
    ende = text.index("]", anfang)
    return {name: pfad for name, pfad in TUPEL.findall(text[anfang:ende])}


def vergleiche() -> tuple[dict[str, str], dict[str, str]]:
    """(geänderte Quellen, neu aufgetauchte Ressourcen) je Ressourcenname."""
    blobs = finde_blobs(lade_seite())
    stand = bekannter_stand()
    geaendert: dict[str, str] = {}
    for lokal, pfad in stand.items():
        ressourcename = pfad.rsplit("/", 1)[-1]
        if ressourcename in blobs and blobs[ressourcename] != pfad:
            geaendert[ressourcename] = blobs[ressourcename]
    bekannt = set(stand.values())
    neu = {name: pfad for name, pfad in blobs.items() if pfad not in bekannt}
    return geaendert, neu


def ist_mdg(ressourcename: str) -> bool:
    return "mdg" in ressourcename.lower() and ressourcename.lower().endswith(".zip")


def neutralisiere(daten: bytes) -> tuple[bytes, int]:
    """E-Mail-Adressen durch den Neutralwert ersetzen; Anzahl zurück."""
    ersatz, anzahl = EMAIL.subn(NEUTRALWERT, daten)
    return ersatz, anzahl


def lade_blob(pfad: str, ziel: Path) -> None:
    """Blob herunterladen; die Antwort kommt gzip-komprimiert."""
    anfrage = urllib.request.Request(
        BASIS + pfad,
        headers={"User-Agent": "EAM-Toolfamilie-Regelwerk-Waechter/1.0"},
    )
    with urllib.request.urlopen(anfrage, timeout=120) as antwort:
        roh = antwort.read()
        if roh[:2] == b"\x1f\x8b":
            roh = gzip.decompress(roh)
    ziel.write_bytes(roh)


def mdg_aus_zip(archiv: Path) -> tuple[str, bytes]:
    """(Dateiname im ZIP, XML-Inhalt) der MDG-Technologie."""
    with zipfile.ZipFile(archiv) as gepackt:
        kandidaten = [
            n for n in gepackt.namelist()
            if n.lower().endswith(".xml") and "mdg" in n.lower()
        ]
        if not kandidaten:
            kandidaten = [n for n in gepackt.namelist() if n.lower().endswith(".xml")]
        if len(kandidaten) != 1:
            raise SystemExit(f"MDG im ZIP nicht eindeutig: {kandidaten}")
        name = kandidaten[0]
        return name.rsplit("/", 1)[-1], gepackt.read(name)


def setze_current(dateiname: str) -> None:
    CURRENT.write_text(dateiname + "\n", encoding="utf-8")


def trage_fetch_quelle_ein(ressourcename: str, neuer_pfad: str, version: str) -> None:
    """Den betroffenen DATEIEN-Eintrag in fetch_quellen.py aktualisieren.

    Der lokale Name folgt der Version aus dem XML (`admbw-mdg-<version>.zip`).
    """
    text = FETCH.read_text(encoding="utf-8")
    zeilen = text.splitlines(keepends=True)
    neue_zeilen = []
    for zeile in zeilen:
        treffer = TUPEL.search(zeile)
        if treffer and treffer.group(2).rsplit("/", 1)[-1] == ressourcename:
            lokal = f"admbw-mdg-{version}.zip" if version else treffer.group(1)
            einzug = zeile[: len(zeile) - len(zeile.lstrip())]
            zeile = f'{einzug}("{lokal}", "{neuer_pfad}"),\n'
        neue_zeilen.append(zeile)
    FETCH.write_text("".join(neue_zeilen), encoding="utf-8")


def schreibe_protokoll(ziel: Path | None, zeilen: list[str]) -> None:
    text = "\n".join(zeilen) + "\n"
    print(text, end="")
    if ziel:
        ziel.write_text(text, encoding="utf-8")


def uebernehmen(protokoll: Path | None) -> int:
    geaendert, neu = vergleiche()
    mdg_pfad = None
    for ressourcename, pfad in geaendert.items():
        if ist_mdg(ressourcename):
            mdg_pfad = pfad
    if mdg_pfad is None:
        for ressourcename, pfad in neu.items():
            if ist_mdg(ressourcename):
                mdg_pfad = pfad
    if mdg_pfad is None:
        print("Keine geänderte MDG gefunden — nichts zu tun.")
        return 0

    protokoll_zeilen = ["# Regelwerk-Übernahme", ""]
    archiv = ROOT / ".cache-regelwerk-tmp.zip"
    try:
        lade_blob(mdg_pfad, archiv)
        name, xml = mdg_aus_zip(archiv)
    finally:
        archiv.unlink(missing_ok=True)

    bereinigt, anzahl = neutralisiere(xml)
    ziel = RULES / name
    ziel.write_bytes(bereinigt)
    setze_current(name)
    versions_muster = re.search(r"(\d{4}\.\d{2})", name)
    trage_fetch_quelle_ein(
        mdg_pfad.rsplit("/", 1)[-1],
        mdg_pfad,
        versions_muster.group(1) if versions_muster else "",
    )

    subprocess.run(
        [sys.executable, "scripts/propagate.py", "--write"],
        cwd=ROOT,
        check=True,
    )

    protokoll_zeilen += [
        f"- **MDG übernommen:** `{name}` (Quelle: `{mdg_pfad}`)",
        f"- **PII neutralisiert:** {anzahl} E-Mail-Vorkommen → `support@example.invalid`",
        "- **Weitergereicht:** `propagate.py --write` (Wissensbasis, Artefakte)",
        "",
    ]
    if geaendert or neu:
        protokoll_zeilen.append("## Weitere geänderte Quellen (Handweg)")
        protokoll_zeilen.append("")
        for ressourcename, pfad in sorted(geaendert.items()):
            if not ist_mdg(ressourcename):
                protokoll_zeilen.append(f"- geändert: `{ressourcename}` → `{pfad}`")
        for ressourcename, pfad in sorted(neu.items()):
            if not ist_mdg(ressourcename):
                protokoll_zeilen.append(f"- neu: `{ressourcename}` → `{pfad}`")
        protokoll_zeilen += [
            "",
            "Aufbereitung dieser Quellen bleibt Handweg:",
            "`fetch_quellen.py` → `extract_leitfaden.py` → `build_regelwerk.py`.",
        ]
    schreibe_protokoll(protokoll, protokoll_zeilen)
    return 0


def pruefen() -> int:
    geaendert, neu = vergleiche()
    mdg_neu = any(ist_mdg(n) for n in list(geaendert) + list(neu))
    if geaendert or neu:
        for name, pfad in sorted(geaendert.items()):
            print(f"geändert: {name} -> {pfad}")
        for name, pfad in sorted(neu.items()):
            print(f"neu: {name} -> {pfad}")
    if mdg_neu:
        print("Neues Regelwerk vorhanden.")
        return 2
    print("Keine Regelwerkänderung; Stand aktuell.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Regelwerk-Quelle prüfen und übernehmen.")
    gruppe = ap.add_mutually_exclusive_group(required=True)
    gruppe.add_argument("--pruefen", action="store_true", help="nur prüfen (Exit 2 = neu)")
    gruppe.add_argument("--uebernehmen", action="store_true", help="herunterladen und einsetzen")
    ap.add_argument("--protokoll", default=None, help="Protokoll zusätzlich in eine Datei")
    args = ap.parse_args()
    if args.pruefen:
        return pruefen()
    return uebernehmen(Path(args.protokoll) if args.protokoll else None)


if __name__ == "__main__":
    raise SystemExit(main())