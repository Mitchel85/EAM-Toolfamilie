#!/usr/bin/env python3
"""Liest die Modellierungskonventionen aus einem Leitfaden-PDF-Text.

Beide Leitfaeden (FFfmLV und PBN Service/System) setzen die Konventionen als
dreispaltige Tabelle: "Nummer | Modellierungskonvention | Verweis". Das
Layout-PDF bricht Zeilen mitten im Satz, wiederholt Seitenkoepfe und schiebt
die Verweis-Spalte weit nach rechts.

Der Leser arbeitet deshalb spaltenweise statt zeilenweise:

1. Ein Tabellenblock beginnt mit der Kopfzeile "Modellierungskonvention ...
   Verweis" und endet mit "Tabelle N: ...".
2. Die Verweis-Spalte wird aus den Daten bestimmt, nicht aus dem Kopf: In
   einem Block enden alle Zeilen mit Verweis an derselben Position. Der
   linke Rand dieser Spalte ist der kleinste Tokenanfang unter den Zeilen,
   die bis an den rechten Rand des Blocks reichen.
3. Alles links davon ist Konventionstext und wird ueber die Zeilen hinweg
   wieder zu einem Satz verbunden.

Ausgabe: Liste von {id, viewpoint, kind, text, verweis}.
"""
from __future__ import annotations

import json
from collections import Counter
import re
import sys
from pathlib import Path

#: Beginn einer Konvention: "A1-MK01", "St-MK01", "C1-S1-MK03".
START = re.compile(r"^([^\s]+?-MK\d{2})\s+(.*)$")

#: Tabellenunterschrift beendet den Block (auch die Beispielabbildung davor).
TABELLE_ENDE = re.compile(r"^\s*(?:Tabelle|Abbildung)\s+\d+\s*:")

#: Seitenkoepfe und -fuesse wiederholen sich mitten in der Tabelle und
#: verfaelschen die Spaltenbreite.
RAUSCHEN = re.compile(
    r"^\s*(?:"
    r"\d+\s+(?:Service- und Systemarchitekturen|Leitfaden|Architekturen)|"
    r"V\d+\.\d+\s*\|\s*\d{1,2}\s+\w+\s*,?\s*\d{4}|"
    r"(?:Service- und System|System- und Service)architekturen \(PBN\)|"
    r"ÖFFENTLICH\s*$"
    r")"
)

#: Ein Token am Zeilenende, dem mindestens drei Leerzeichen vorangehen.
RANDTOKEN = re.compile(r"\s{3,}(\S.*?)\s*$")


def _ist_kopf(lines: list[str], i: int) -> bool:
    """Tabellenkopf, nicht die Prosa, die das Wort ebenfalls enthaelt.

    Der Kopf traegt immer eine der Spaltenueberschriften. Bei breiten Tabellen
    steht "Verweis" erst in der Folgezeile, deshalb wird ein kurzes Fenster
    mitgeprueft. Ein Satz aus dem Fliesstext faellt damit heraus.
    """
    zeile = lines[i]
    if "Modellierungskonvention" not in zeile or "Tabelle" in zeile:
        return False
    fenster = " ".join(lines[i : i + 3])
    return any(w in fenster for w in ("Nummer", "Konventions", "Verweis"))


def _spaltenrand(block: list[str]) -> int | None:
    """Linker Rand der Verweis-Spalte, aus den Daten bestimmt.

    Die Verweis-Spalte ist rechtsbuendig. Gesucht ist die letzte grosse
    Luecke einer Zeile; steht danach nur ein kurzes Token, ist das der
    Verweis. Der haeufigste Fund im Block gewinnt, weil sich die Spalte
    ueber alle Zeilen wiederholt -- ein einzelner Ausreisser kippt sie nicht.
    """
    if not block:
        return None
    breite = max(len(z) for z in block if z.strip())
    kandidaten: list[int] = []
    for zeile in block:
        luecken = list(re.finditer(r"\s{3,}", zeile))
        if not luecken:
            continue
        start = luecken[-1].end()
        token = zeile[start:].strip()
        if not token or len(token) > 40:
            continue
        if start < breite * 0.55:  # zu weit links: Textluecke, keine Spalte
            continue
        kandidaten.append(start)
    if not kandidaten:
        return None
    return Counter(kandidaten).most_common(1)[0][0]


def _saeubern(teile: list[str]) -> str:
    text = " ".join(t.strip() for t in teile if t.strip())
    text = re.sub(r"\s{2,}", " ", text)
    text = text.replace("\u00ad", "")
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)  # Silbentrennung ueber Zeilen
    return text.strip()


def _bloecke(lines: list[str]) -> list[tuple[list[str], int | None]]:
    """Tabellenbloecke samt Spaltenrand."""
    bloecke: list[tuple[list[str], int | None]] = []
    i = 0
    while i < len(lines):
        if not _ist_kopf(lines, i):
            i += 1
            continue
        i += 1
        koerper: list[str] = []
        while i < len(lines) and not TABELLE_ENDE.match(lines[i]) and not _ist_kopf(lines, i):
            roh = lines[i]
            if roh.strip() and not RAUSCHEN.match(roh):
                koerper.append(roh)
            i += 1
        bloecke.append((koerper, _spaltenrand(koerper)))
    return bloecke


def parse(text: str) -> list[dict[str, str]]:
    lines = [z.replace("\f", "") for z in text.splitlines()]
    out: list[dict[str, str]] = []

    for koerper, rand in _bloecke(lines):
        aktuell: dict[str, str] | None = None
        puffer: list[str] = []
        verweise: list[str] = []

        def abschliessen() -> None:
            nonlocal aktuell, puffer, verweise
            if aktuell is None:
                return
            rumpf = _saeubern(puffer)
            if rumpf:
                aktuell["text"] = rumpf
                aktuell["verweis"] = _saeubern(verweise)
                out.append(aktuell)
            aktuell, puffer, verweise = None, [], []

        for roh in koerper:
            if rand is not None and len(roh) > rand:
                links, rechts = roh[:rand], roh[rand:].strip()
            else:
                links, rechts = roh, ""
            treffer = START.match(links.strip())
            if treffer:
                abschliessen()
                aktuell = {
                    "id": treffer.group(1),
                    "viewpoint": treffer.group(1).split("-MK")[0],
                    "kind": "",
                    "text": "",
                    "verweis": "",
                }
                puffer = [treffer.group(2)]
            elif aktuell is not None:
                puffer.append(links)
            if rechts:
                verweise.append(rechts)
        abschliessen()

    # Art bestimmen: Package, Diagramm, Element, Beziehung, Sonstiges.
    for eintrag in out:
        t = eintrag["text"].lower()
        if "package" in t:
            eintrag["kind"] = "package"
        elif "diagramm" in t:
            eintrag["kind"] = "diagram"
        elif "verbunden" in t or "beziehung" in t or "relation" in t:
            eintrag["kind"] = "connector"
        elif "element" in t or "stereotyp" in t:
            eintrag["kind"] = "element"
        else:
            eintrag["kind"] = "other"

    # Erklaertabelle mit Platzhalterkennungen ("xx-MK01") ist keine Konvention.
    out = [e for e in out if not e["id"].startswith("xx")]

    # Dubletten: derselbe Eintrag kann durch Seitenwechsel zweimal auftauchen.
    gesehen: dict[str, dict[str, str]] = {}
    for eintrag in out:
        gesehen.setdefault(eintrag["id"], eintrag)
    return list(gesehen.values())


def main() -> int:
    if len(sys.argv) < 2:
        print("Aufruf: extract_leitfaden.py <text.txt> [-o ausgabe.json]", file=sys.stderr)
        return 2
    quelle = Path(sys.argv[1])
    ziel = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "-o" else quelle.with_suffix(".json")
    eintraege = parse(quelle.read_text(encoding="utf-8", errors="replace"))
    ziel.write_text(json.dumps(eintraege, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(eintraege)} Konventionen -> {ziel}")
    print("Viewpoints:", ", ".join(sorted({e['viewpoint'] for e in eintraege})))
    leer = [e["id"] for e in eintraege if len(e["text"]) < 15]
    print("zu kurz:", leer or "keine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
