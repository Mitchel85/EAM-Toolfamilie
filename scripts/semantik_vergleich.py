#!/usr/bin/env python3
"""Semantischer Vergleich: steht der Inhalt des Originals im erzeugten Text?

Misst Faktentreue statt Wortgleichheit. Das Original wird in einzelne
Sachaussagen zerlegt; fuer jede Aussage prueft ein Sprachmodell anhand der
passendsten Absaetze des erzeugten Textes, ob dort dieselbe Aussage steht.
Andere Worte, andere Saetze, andere Gliederung zaehlen nicht -- nur, ob der
Sachverhalt wieder drinsteht. Ergebnis: Anteil belegter Aussagen
("teilweise" zaehlt halb).

Werkzeug fuer Abnahmetests, nicht Teil der Anwendung. Es kennt kein Modell und
kein Dokument; alles kommt aus den uebergebenen Dateien.

    python3 scripts/semantik_vergleich.py ORIGINAL.md ERZEUGT.md [...] \
        --model deepseek-flash --ohne Anhang --fakten fakten.json --bericht bericht.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL / "packages" / "core"))
import extract  # noqa: E402

PROMPT_FAKTEN = """Zerlege den folgenden Abschnitt eines Architektur-Handbuchs in einzelne, ueberpruefbare Sachaussagen.
Regeln:
- Je Aussage genau ein Sachverhalt (Gegenstand und Eigenschaft oder Beziehung), eigenstaendig verstaendlich, mit den Namen aus dem Text.
- Keine Aussagen ueber das Dokument selbst (Gliederung, Kapitel, Leserfuehrung).
- Nichts ergaenzen, was nicht im Text steht.
- Antworte ausschliesslich mit JSON: {{"aussagen": ["...", "..."]}}

Abschnitt:
{text}
"""

PROMPT_URTEIL = """Pruefe fuer jede nummerierte Aussage, ob der darunter stehende Auszug aus einem zweiten Dokument dieselbe Aussage trifft.
- "ja": der Auszug sagt dasselbe aus (gleiche Gegenstaende, gleiche Eigenschaft oder Beziehung; andere Worte sind egal).
- "teilweise": der Kern stimmt, ein Detail fehlt oder weicht ab.
- "nein": nicht enthalten oder widersprochen. Gleiche Namen allein genuegen nicht.
Antworte ausschliesslich mit JSON: {{"urteile": [{{"nr": 1, "urteil": "ja"}}]}}

{block}
"""


def abschnitte(text: str, ohne: list[str]) -> list[str]:
    teile = re.split(r"(?m)^(?=## )", text)
    gewaehlt = []
    for teil in teile:
        if not teil.strip():
            continue
        kopf = teil.strip().splitlines()[0]
        if kopf.startswith("## ") and any(o.casefold() in kopf.casefold() for o in ohne):
            continue
        gewaehlt.append(teil.strip())
    return gewaehlt


def stuecke(abschnitt: str, grenze: int = 6000) -> list[str]:
    ergebnis, aktuell = [], ""
    for absatz in re.split(r"\n\s*\n", abschnitt):
        if aktuell and len(aktuell) + len(absatz) > grenze:
            ergebnis.append(aktuell)
            aktuell = ""
        aktuell += ("\n\n" if aktuell else "") + absatz
    if aktuell:
        ergebnis.append(aktuell)
    return ergebnis


def json_liste(antwort: str, schluessel: str) -> list:
    text = re.sub(r"^```(?:json)?|```$", "", antwort.strip(), flags=re.M).strip()
    try:
        daten = json.loads(text)
    except json.JSONDecodeError:
        anfang, ende = text.find("["), text.rfind("]")
        if anfang < 0 or ende < anfang:
            return []
        try:
            daten = json.loads(text[anfang:ende + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(daten, dict):
        daten = daten.get(schluessel, next((v for v in daten.values() if isinstance(v, list)), []))
    return daten if isinstance(daten, list) else []


def woerter(text: str) -> set[str]:
    return set(re.findall(r"[0-9a-zäöüß][0-9a-zäöüß\-]{2,}", text.casefold()))


class Index:
    """Absaetze des erzeugten Textes; Tabellen zeilenweise, damit eine Zeile
    als Beleg reicht. Gewichtet nach Seltenheit der Woerter (IDF)."""

    def __init__(self, text: str) -> None:
        einheiten: list[str] = []
        kopf = ""
        for block in re.split(r"\n\s*\n", text):
            block = block.strip()
            if not block:
                continue
            if block.startswith("#"):
                kopf = block.splitlines()[0].lstrip("# ").strip()
            zeilen = block.splitlines()
            if sum(z.startswith("|") for z in zeilen) >= 3:
                einheiten += [f"{kopf}: {z}" for z in zeilen if z.startswith("|") and not set(z) <= set("|-: ")]
            elif len(block) > 20:
                einheiten.append(block)
        self.einheiten = einheiten
        self.mengen = [woerter(e) for e in einheiten]
        haeufig: dict[str, int] = {}
        for menge in self.mengen:
            for wort in menge:
                haeufig[wort] = haeufig.get(wort, 0) + 1
        n = len(self.mengen)
        self.idf = {w: math.log((n + 1) / (c + 0.5)) for w, c in haeufig.items()}

    def suche(self, aussage: str, k: int = 3) -> list[str]:
        frage = woerter(aussage)
        bewertet = sorted(
            ((sum(self.idf.get(w, 0.0) for w in frage & menge), i) for i, menge in enumerate(self.mengen)),
            reverse=True,
        )
        return [self.einheiten[i][:900] for wert, i in bewertet[:k] if wert > 0]


def urteilen(backend, posten: list[tuple[int, str, list[str]]]) -> dict[int, str]:
    block = "\n\n".join(
        f"[{nr}] Aussage: {aussage}\nAuszug:\n" + ("\n---\n".join(auszug) if auszug else "(kein passender Absatz)")
        for nr, aussage, auszug in posten
    )
    for _ in range(2):
        try:
            liste = json_liste(backend.complete(PROMPT_URTEIL.format(block=block)), "urteile")
        except Exception:  # noqa: BLE001 - Netz/Endpunkt: einmal wiederholen
            liste = []
        urteile = {}
        for eintrag in liste:
            if isinstance(eintrag, dict) and str(eintrag.get("urteil", "")).strip().lower() in ("ja", "teilweise", "nein"):
                try:
                    urteile[int(eintrag.get("nr"))] = str(eintrag["urteil"]).strip().lower()
                except (TypeError, ValueError):
                    continue
        if urteile:
            return urteile
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semantischer Vergleich zweier Handbuecher")
    parser.add_argument("original", type=Path)
    parser.add_argument("erzeugt", type=Path, nargs="+")
    parser.add_argument("--ohne", action="append", default=[], help="Kapitel (## ...) auslassen")
    parser.add_argument("--backend", default="openai")
    parser.add_argument("--model", default=None)
    parser.add_argument("--fakten", type=Path, default=None, help="Aussagen zwischenspeichern/wiederverwenden")
    parser.add_argument("--bericht", type=Path, default=None)
    parser.add_argument("--parallel", type=int, default=6)
    args = parser.parse_args(argv)

    backend = extract.make_backend(args.backend, model=args.model, timeout=240)
    if args.fakten and args.fakten.exists():
        fakten = json.loads(args.fakten.read_text(encoding="utf-8"))
    else:
        teile = [s for a in abschnitte(args.original.read_text(encoding="utf-8"), args.ohne) for s in stuecke(a)]
        with ThreadPoolExecutor(args.parallel) as pool:
            listen = list(pool.map(
                lambda s: json_liste(backend.complete(PROMPT_FAKTEN.format(text=s)), "aussagen"), teile))
        fakten = list(dict.fromkeys(str(f).strip() for liste in listen for f in liste if str(f).strip()))
        if args.fakten:
            args.fakten.write_text(json.dumps(fakten, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Aussagen im Original: {len(fakten)}" + (f" (ohne: {', '.join(args.ohne)})" if args.ohne else ""))

    bericht = {"original": str(args.original), "aussagen": len(fakten), "dokumente": {}}
    for pfad in args.erzeugt:
        index = Index(pfad.read_text(encoding="utf-8"))
        posten = [(i + 1, f, index.suche(f)) for i, f in enumerate(fakten)]
        gruppen = [posten[i:i + 12] for i in range(0, len(posten), 12)]
        with ThreadPoolExecutor(args.parallel) as pool:
            teilurteile = list(pool.map(lambda g: urteilen(backend, g), gruppen))
        urteile: dict[int, str] = {}
        for teil in teilurteile:
            urteile.update(teil)
        ja = sum(1 for v in urteile.values() if v == "ja")
        teilweise = sum(1 for v in urteile.values() if v == "teilweise")
        offen = len(fakten) - len(urteile)
        wert = (ja + 0.5 * teilweise) / len(fakten) if fakten else 0.0
        print(f"{pfad.name}: {wert:.0%}  ({ja} ja, {teilweise} teilweise, "
              f"{len(fakten) - ja - teilweise} nein{f', davon {offen} ohne Urteil' if offen else ''})")
        bericht["dokumente"][pfad.name] = {
            "wert": round(wert, 4), "ja": ja, "teilweise": teilweise,
            "nein": len(fakten) - ja - teilweise, "ohne_urteil": offen,
            "urteile": {fakten[nr - 1]: urteil for nr, urteil in sorted(urteile.items())},
        }
    if args.bericht:
        args.bericht.write_text(json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
