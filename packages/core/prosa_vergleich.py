#!/usr/bin/env python3
"""Vergleicht zwei Prosafassungen: Quelle und Rueckweg aus der Architektur.

Der Bericht beantwortet drei Fragen:

1. Wie viel Text steht auf beiden Seiten (Umfang, Satzbau)?
2. Deckt der Rueckweg die Kapitel der Quelle ab (Jaccard je Ueberschrift)?
3. Kommen alle Bezeichnungen des Modells im Rueckweg vor (Recall)?

Zusaetzlich werden Zahlen verglichen: Zahlen, die nur im Rueckweg stehen,
sind ein Hinweis auf erfundene Angaben; Zahlen, die nur in der Quelle
stehen, auf verlorene Details.

Aufruf::

    python3 prosa_vergleich.py quelle.md zurueck.md [--qea modell.qea]
        [--md bericht.md] [--json bericht.json]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path

import handbuch_generator as hg
from typing import Any, Sequence

WORT = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]*")
SATZ = re.compile(r"(?<=[.!?])\s+")
ZAHL = re.compile(r"\b\d+(?:[.,]\d+)?\b")
KAPITEL = re.compile(r"^##\s+(.+)$", re.M)


def kennzahlen(text: str) -> dict[str, Any]:
    woerter = WORT.findall(text)
    saetze = [s for s in SATZ.split(text) if len(s.split()) > 2]
    absaetze = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return {
        "zeichen": len(text),
        "woerter": len(woerter),
        "saetze": len(saetze),
        "absaetze": len(absaetze),
        "ueberschriften": len(KAPITEL.findall(text)),
        "mittlere_satzlaenge": round(len(woerter) / max(1, len(saetze)), 1),
    }


def kapitel(text: str) -> dict[str, str]:
    treffer = list(KAPITEL.finditer(text))
    ergebnis: dict[str, str] = {}
    for i, treffer_ in enumerate(treffer):
        ende = treffer[i + 1].start() if i + 1 < len(treffer) else len(text)
        ergebnis[treffer_.group(1).strip()] = text[treffer_.end():ende]
    return ergebnis


def jaccard(a: str, b: str) -> float:
    links = {w.lower() for w in re.findall(r"\w{4,}", a)}
    rechts = {w.lower() for w in re.findall(r"\w{4,}", b)}
    if not links and not rechts:
        return 1.0
    return round(len(links & rechts) / max(1, len(links | rechts)), 3)


def kennzahlen_im_text(text: str) -> dict[str, int]:
    """Liest die Tabelle 10.1 als Bezeichnung -> Wert."""
    treffer = KENNZAHLENBLOCK.search(text)
    if not treffer:
        return {}
    werte: dict[str, int] = {}
    for zeile in treffer.group(1).splitlines():
        teile = [teil.strip() for teil in zeile.strip().strip("|").split("|")]
        if len(teile) == 2 and teile[1].isdigit():
            werte[teile[0]] = int(teile[1])
    return werte


#: Bezeichnung in der Tabelle -> Zaehlung in der Ablage.
#: Die Kennzahlen tragen dieselben Namen wie die Tabelle im Handbuch
#: (handbuch_generator.py, Abschnitt 10.1). Vorher hiessen sie hier anders
#: ("Dienste an Bord", "Meilensteine"), wodurch vier von sieben Zeilen
#: "modell: null" meldeten - ein Vergleich, der nie stattfand.
def _zaehle(*stereotypes: str) -> str:
    liste = ", ".join(f"'{name}'" for name in sorted(stereotypes))
    return f"select count(distinct Name) from t_object where Stereotype in ({liste})"


MODELLZAEHLUNG = {
    "Dienste": _zaehle(*hg.DIENST_STEREOTYPE),
    "Baugruppen": _zaehle(*hg.BAUTEIL_STEREOTYPE),
    "Fähigkeiten": _zaehle(*hg.FAEHIGKEIT_STEREOTYPE),
    "Forderungen": _zaehle(*hg.FORDERUNG_STEREOTYPE),
    "Vorgaben": _zaehle(*hg.RANDBEDINGUNG_STEREOTYPE),
    "Abläufe": _zaehle(*hg.ABLAUF_STEREOTYPE),
    "Verbindungen": "select count(*) from t_connector",
}


def modellkennzahlen(pfad: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    try:
        return {name: int(con.execute(sql).fetchone()[0]) for name, sql in MODELLZAEHLUNG.items()}
    finally:
        con.close()


def modellnamen(pfad: Path) -> list[str]:
    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    try:
        return sorted(
            {
                str(name).strip()
                for (name,) in con.execute(
                    "select Name from t_object where Object_Type in ('Class','Object') and Name is not null and Name != ''"
                )
            }
        )
    finally:
        con.close()


def _saetze(text: str) -> list[str]:
    """Saetze aus Textabsaetzen, ohne Ueberschriften mit dem Text zu verkleben.

    Ein Absatz ist die Einheit: Ueberschriftzeilen darin benennen nur und
    beginnen deshalb keinen Satz. Vorher wurde der ganze Text zu einer Zeile
    verflacht; dadurch entstand aus ``## Sensoren`` und dem folgenden Absatz
    ein Satz, den kein Rueckweg je treffen konnte - ein Messfehler zu Lasten
    der Quote.
    """
    saetze: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        zeilen = [
            zeile.strip()
            for zeile in block.splitlines()
            if zeile.strip() and not zeile.lstrip().startswith("#")
        ]
        if not zeilen:
            continue
        for roh in re.split(r"(?<=[.!?])\s+", " ".join(zeilen)):
            if len(roh.split()) >= 8:
                saetze.append(roh.strip())
    return saetze


def faktenabdeckung(quelle: str, zurueck: str) -> dict[str, Any]:
    """Anteil der Quellsaetze, die im Rueckweg inhaltlich wiederkehren.

    Wortgleichheit ist bei frei formulierter Prosa kein Massstab; gemessen
    wird die beste Uebereinstimmung eines Quellsatzes mit irgendeinem Satz
    des Rueckwegs (Wortfolge, difflib).
    """
    soll = _saetze(ohne_gliederung(quelle))
    ist = [s.casefold() for s in _saetze(ohne_gliederung(zurueck))]
    if not soll or not ist:
        return {"quote": 0.0, "geprueft": 0, "getroffen": 0, "schwach": []}
    getroffen = 0
    schwach: list[str] = []
    for satz in soll:
        a = satz.casefold()
        bestes = 0.0
        for kandidat in ist:
            schnell = difflib.SequenceMatcher(None, a, kandidat).quick_ratio()
            if schnell < 0.55:
                continue
            bestes = max(bestes, difflib.SequenceMatcher(None, a, kandidat).ratio())
            if bestes >= 0.72:
                break
        if bestes >= 0.72:
            getroffen += 1
        else:
            schwach.append(satz[:160])
    return {
        "quote": round(100.0 * getroffen / len(soll), 1),
        "geprueft": len(soll),
        "getroffen": getroffen,
        "schwach": schwach[:15],
    }


def vergleiche(quelle: str, zurueck: str, qea: Path | None = None) -> dict[str, Any]:
    kap_quelle, kap_zurueck = kapitel(quelle), kapitel(zurueck)
    gemeinsam = [k for k in kap_quelle if k in kap_zurueck]
    nur_quelle = [k for k in kap_quelle if k not in kap_zurueck]
    nur_zurueck = [k for k in kap_zurueck if k not in kap_quelle]

    schnitt = {k: jaccard(kap_quelle[k], kap_zurueck[k]) for k in gemeinsam}
    namen = modellnamen(qea) if qea is not None else []
    zahlen_quelle = zahlen(quelle, namen)
    zahlen_zurueck = zahlen(zurueck, namen)

    bericht: dict[str, Any] = {
        "quelle": kennzahlen(quelle),
        "zurueck": kennzahlen(zurueck),
        "kapitel": {
            "gemeinsam": len(gemeinsam),
            "nur_quelle": nur_quelle,
            "nur_zurueck": nur_zurueck,
            "jaccard": schnitt,
            "mittel": round(sum(schnitt.values()) / max(1, len(schnitt)), 3),
        },
        "zahlen": {
            "nur_im_rueckweg": sorted(zahlen_zurueck - zahlen_quelle),
            "nur_in_der_quelle": sorted(zahlen_quelle - zahlen_zurueck),
        },
        "fakten": faktenabdeckung(quelle, zurueck),
    }

    if qea is not None:
        soll = modellkennzahlen(qea)
        ist = kennzahlen_im_text(zurueck)
        bericht["kennzahlen"] = [
            {"bezeichnung": name, "text": wert, "modell": soll.get(name), "ok": wert == soll.get(name)}
            for name, wert in ist.items()
        ]
        namen = namen or modellnamen(qea)
        klein = zurueck.casefold()
        fehlend = [n for n in namen if n.casefold() not in klein]
        bericht["bezeichnungen"] = {
            "gesamt": len(namen),
            "genannt": len(namen) - len(fehlend),
            "quote": round(100.0 * (len(namen) - len(fehlend)) / max(1, len(namen)), 1),
            "fehlend": fehlend[:50],
        }
    return bericht


#: Nummerierung von Ueberschriften, damit Gliederungsnummern nicht als
#: inhaltliche Zahlen gelten (sonst meldet der Vergleich "3.14" als Zahl).
GLIEDERUNG = re.compile(r"^#{1,6}\s+[\d.]*\d+\s", re.M)


def _ist_gliederungsnummer(text: str, stelle: int) -> bool:
    """Gehoert die Zahl zu einer Gliederung ("## 4.1 …", "4.3.2 Titel")?"""
    zeilen_anfang = text.rfind("\n", 0, stelle) + 1
    davor = text[zeilen_anfang:stelle]
    if davor.strip() and not re.fullmatch(r"[#\s]*[\d.]*", davor):
        return False
    return bool(re.match(r"[\d.]*[\d](?=[\s.|])", text[stelle:stelle + 12]))


def ohne_gliederung(text: str) -> str:
    """Entfernt die Nummerierung von Ueberschriften, nicht die Ueberschrift.

    So bleiben die Titel im Wortvergleich, und "1 Zweck und Auftrag" zaehlt
    nicht als Zahl 1.
    """
    zeilen = []
    for zeile in text.splitlines():
        treffer = GLIEDERUNG.match(zeile)
        if treffer:
            raute = len(zeile) - len(zeile.lstrip("#"))
            zeilen.append(zeile[:raute] + " " + zeile[treffer.end():])
        else:
            zeilen.append(zeile)
    return "\n".join(zeilen)


#: Auspraegungsnummern wie "Service Bw 1.1" gehoeren zum Namen, nicht zum Inhalt.
AUSPRAEGUNG = re.compile(r"\b\d+\.\d+\s*$")


#: Die Kennzahlentabelle wird eigens gegen das Modell geprueft und daher
#: aus dem freien Zahlenvergleich herausgehalten.
KENNZAHLENBLOCK = re.compile(
    r"^###\s+10\.1\s+Kennzahlen\s*$(.*?)(?=^###|^##|\Z)", re.M | re.S
)


def ohne_kennzahlen(text: str) -> str:
    return KENNZAHLENBLOCK.sub("", text)


def zahlen(text: str, namen: Sequence[str] = ()) -> set[str]:
    """Inhaltliche Zahlen; Gliederung, Kennzahlen und Namen zaehlen nicht."""
    ohne = ohne_kennzahlen(text)
    for name in sorted(namen, key=len, reverse=True):
        ohne = ohne.replace(name, " ")
    ohne = ohne_gliederung(ohne)
    ergebnis: set[str] = set()
    for treffer in ZAHL.finditer(ohne):
        stelle = treffer.start()
        if _ist_gliederungsnummer(ohne, stelle):
            continue
        # "… Service Bw 1.1": Zahl steht am Ende einer Bezeichnung vor "|" oder Zeilenende.
        davor = ohne[max(0, stelle - 60):stelle]
        if ". " in treffer.group(0) or AUSPRAEGUNG.search(davor):
            continue
        ergebnis.add(treffer.group(0))
    return ergebnis


def als_markdown(bericht: dict[str, Any]) -> str:
    q, z = bericht["quelle"], bericht["zurueck"]
    zeilen = ["# Prosa-Vergleich", "", "## Umfang", "",
              "| Kennzahl | Quelle | Rückweg |", "| --- | ---: | ---: |"]
    for schluessel, titel in (
        ("zeichen", "Zeichen"), ("woerter", "Wörter"), ("saetze", "Sätze"),
        ("absaetze", "Absätze"), ("ueberschriften", "Überschriften"),
        ("mittlere_satzlaenge", "Ø Satzlänge"),
    ):
        zeilen.append(f"| {titel} | {q[schluessel]} | {z[schluessel]} |")

    k = bericht["kapitel"]
    zeilen += ["", "## Kapitel", "",
               f"- gemeinsam: **{k['gemeinsam']}**",
               f"- mittlere Wortüberdeckung (Jaccard): **{k['mittel']}**"]
    if k["nur_quelle"]:
        zeilen.append("- nur in der Quelle: " + ", ".join(k["nur_quelle"]))
    if k["nur_zurueck"]:
        zeilen.append("- nur im Rückweg: " + ", ".join(k["nur_zurueck"]))

    zeilen += ["", "### Überdeckung je Kapitel", "", "| Kapitel | Jaccard |", "| --- | ---: |"]
    for name, wert in sorted(k["jaccard"].items(), key=lambda paar: paar[1]):
        zeilen.append(f"| {name} | {wert:.2f} |")

    zahlen = bericht["zahlen"]
    zeilen += ["", "## Zahlen", "",
               f"- nur im Rückweg (mögliche Erfindung): {', '.join(zahlen['nur_im_rueckweg']) or '—'}",
               f"- nur in der Quelle (verlorene Details): {', '.join(zahlen['nur_in_der_quelle'][:30]) or '—'}"]

    fakten = bericht["fakten"]
    zeilen += ["", "## Faktenabdeckung", "",
               f"- Quellsätze mit Entsprechung: **{fakten['getroffen']} von {fakten['geprueft']}** ({fakten['quote']} %)",
               "- Maßstab: bester Satz im Rückweg mit mindestens 72 % Wortfolge-Übereinstimmung"]
    if fakten["schwach"]:
        zeilen.append("- ohne klare Entsprechung (Auszug):")
        zeilen += [f"  - {s}" for s in fakten["schwach"][:8]]

    if bericht.get("kennzahlen"):
        zeilen += ["", "## Kennzahlen gegen das Modell", "",
                   "| Kennzahl | im Text | im Modell | Status |", "| --- | ---: | ---: | --- |"]
        for eintrag in bericht["kennzahlen"]:
            status = "ok" if eintrag["ok"] else "**abweichend**"
            zeilen.append(
                f"| {eintrag['bezeichnung']} | {eintrag['text']} | {eintrag['modell']} | {status} |"
            )

    if "bezeichnungen" in bericht:
        b = bericht["bezeichnungen"]
        zeilen += ["", "## Bezeichnungen aus dem Modell", "",
                   f"- genannt: **{b['genannt']} von {b['gesamt']}** ({b['quote']} %)"]
        if b["fehlend"]:
            zeilen.append("- fehlend: " + ", ".join(b["fehlend"]))

    return "\n".join(zeilen) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quelle und Rückweg als Prosa vergleichen.")
    parser.add_argument("quelle", type=Path)
    parser.add_argument("zurueck", type=Path)
    parser.add_argument("--qea", type=Path, default=None, help="Modell für die Bezeichnungsquote")
    parser.add_argument("--md", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        bericht = vergleiche(
            args.quelle.read_text(encoding="utf-8"),
            args.zurueck.read_text(encoding="utf-8"),
            args.qea,
        )
    except OSError as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 2

    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(als_markdown(bericht), encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(bericht, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Kapitel {bericht['kapitel']['gemeinsam']} gemeinsam, "
        f"Jaccard {bericht['kapitel']['mittel']:.2f}, "
        f"Bezeichnungen {bericht.get('bezeichnungen', {}).get('quote', '—')} %"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
