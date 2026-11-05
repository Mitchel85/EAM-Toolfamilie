#!/usr/bin/env python3
"""kantenausbeute.py -- wie viele Handlungssaetze werden zur gueltigen MDG-Kante?

Zweck
-----
Die Extraktion liefert Elemente, Notizen und Beziehungen. Notizen tragen den
Rueckweg (Faktenabdeckung), Beziehungen tragen die Struktur. Dieses Werkzeug
misst die Struktur an der Quelle: es zaehlt die **Handlungssaetze** des Textes
und prueft, wie viele davon eine Kante ergeben, die die MDG-Pruefung uebersteht.

Begriffe (bewusst festgelegt, damit die Zahl reproduzierbar bleibt)
-------------------------------------------------------------------
* **Handlungssatz** -- ein Satz der Quelle, der
  (a) mindestens zwei im Modell vorhandene Elementnamen nennt (Wortgrenze,
      Gross-/Kleinschreibung egal, Name mindestens drei Zeichen) und
  (b) ein Handlungsverb enthaelt (Liste ``HANDLUNGSVERBEN``, Grundformen mit
      Inflexion: nutzt/nutzen, liefert, steuert, erfasst, uebermittelt,
      gehoert zu, benoetigt, greift auf, erzeugt, prueft, bedient, wartet ...).
  Ueberschriften beginnen keinen Satz (``prosa_vergleich._saetze``).
* **Gedeckt** -- es gibt eine Kante im Modell, die die MDG-Pruefung besteht
  (``validator._check_connectors``) und deren Quelle **und** Ziel in genau
  diesem Satz genannt sind. Die Richtung ist dabei egal: ob "Sensor erfasst
  Ziel" als Sensor->Ziel oder Ziel->Sensor modelliert ist, entscheidet die
  MDG-Regel, nicht dieser Zaehler.
* **Ausbeute** -- gedeckte Handlungssaetze / Handlungssaetze. Zusaetzlich
  steht die **Kantenausbeute** (gueltige Kanten / gelieferte Kanten) im
  Bericht, weil beide Zahlen zusammen die Struktur beschreiben.

Grenzen
-------
* Der Zaehler bewertet keine Semantik: eine Kante zwischen den richtigen zwei
  Elementen mit falschem Stereotyp gilt als gedeckt, solange die MDG sie
  zulaesst -- der Stereotyp wird an anderer Stelle geprueft.
* Die Bezugsgroesse haengt am Modell: extrahiert es weniger Elemente, sinkt die
  Zahl der Handlungssaetze. Deshalb stehen beide Zaehler (Nenner und Treffer)
  im Bericht, nicht nur die Quote.
* Deterministisch: gleiche Quelle + gleiches Modell = gleiche Zahlen, keine
  Zeitstempel, sortierte Ausgabe.

CLI::

    python3 kantenausbeute.py --text QUELLE.md --ir MODELL.json \\
        --mdg MDG.xml --json bericht.json [--md bericht.md]

Exit-Codes: 0, wenn ein Bericht entsteht (auch bei schlechter Ausbeute);
2, wenn Quelle, IR oder Regelwerk nicht lesbar sind.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import validator

MIN_NAME = 3
MIN_WOERTER = 2

LISTEN_LIMIT = 20

# Grundformen der Handlungsverben. Der Stamm wird gebildet, indem die Endung
# "en"/"n" abfaellt; die Inflexion kommt als Suffix zurueck. Umlaute bleiben
# Umlaute, weil der Quelltext sie schreibt.
HANDLUNGSVERBEN: tuple[str, ...] = (
    "nutzen", "liefern", "bereitstellen", "stellen", "steuern", "erfassen",
    "uebermitteln", "übermitteln", "gehoeren", "gehören", "benoetigen",
    "benötigen", "greifen", "erzeugen", "bekaempfen", "bekämpfen", "pruefen",
    "prüfen", "sammeln", "ordnen", "verteilen", "rechnen", "dienen", "fuehren",
    "führen", "geben", "nehmen", "empfangen", "senden", "uebertragen",
    "übertragen", "werten", "bestimmen", "ermitteln", "melden", "freigeben",
    "loesen", "lösen", "starten", "tragen", "halten", "gewaehrleisten",
    "gewährleisten", "sichern", "unterstuetzen", "unterstützen", "ermoeglichen",
    "ermöglichen", "aufklaeren", "aufklären", "bilden", "wirken", "ausbilden",
    "bedienen", "warten", "schulen", "speichern", "abrufen", "verbinden",
    "trennen", "regeln", "schuetzen", "schützen", "ueberwachen", "überwachen",
    "vornehmen", "erheben", "zuordnen", "ausgeben", "einholen", "vorhalten",
)

_SUFFIX = r"(?:en|e|t|et|st|est|te|ten|test|tet)?"


class AusbeuteFehler(RuntimeError):
    """Quelle, IR oder Regelwerk nicht lesbar."""


# --------------------------------------------------------------------------
# Saetze und Handlungen
# --------------------------------------------------------------------------


def _saetze(text: str) -> list[str]:
    """Saetze absatzweise; Ueberschriften beginnen keinen Satz.

    Gleiche Trennung wie ``prosa_vergleich._saetze`` (dort per Test
    abgesichert): der ganze Text darf nicht zu einer Zeile verflachen.
    """
    saetze: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        zeilen = [
            zeile.strip()
            for zeile in block.splitlines()
            if zeile.strip() and not zeile.lstrip().startswith(("#", "|"))
        ]
        if not zeilen:
            continue
        for roh in re.split(r"(?<=[.!?])\s+", " ".join(zeilen)):
            for satz in re.split(r"(?<=[.!?])(?=[A-ZÄÖÜ])", roh):
                # Eine Definition ("Es gibt zwei Arten ...") beschreibt keine
                # Handlung; ein Semikolon trennt zwei Aussagen, die getrennt
                # gezaehlt werden muessen.
                if satz.strip().casefold().startswith("es gibt"):
                    continue
                for teil in satz.split(";"):
                    if len(teil.split()) >= MIN_WOERTER:
                        saetze.append(teil.strip())
    return saetze


def _verb_muster() -> re.Pattern[str]:
    staemme: set[str] = set()
    for verb in HANDLUNGSVERBEN:
        stamm = verb[:-2] if verb.endswith("en") else verb[:-1]
        if stamm:
            staemme.add(stamm)
    return re.compile(
        r"\b(?:" + "|".join(sorted(staemme, key=len, reverse=True)) + r")" + _SUFFIX + r"\b",
        re.IGNORECASE,
    )


_VERB = _verb_muster()


def hat_handlung(satz: str) -> bool:
    """Enthaelt der Satz ein Handlungsverb aus der Liste?"""
    return _VERB.search(satz) is not None


def _name_muster(name: str) -> re.Pattern[str]:
    return re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)


def elementnamen(ir: Mapping[str, Any]) -> list[str]:
    """Elementnamen aus dem IR, ohne Paketprefix, ohne Dubletten, sortiert."""
    namen: set[str] = set()
    for element in ir.get("elements") or ():
        if not isinstance(element, Mapping):
            continue
        name = str(element.get("name") or "").strip()
        if len(name) >= MIN_NAME:
            namen.add(name)
    return sorted(namen)


def handlungssaetze(text: str, namen: Sequence[str]) -> list[dict[str, Any]]:
    """Alle Handlungssaetze mit den Elementnamen, die sie nennen."""
    muster = [(name, _name_muster(name)) for name in namen]
    treffer: list[dict[str, Any]] = []
    for satz in _saetze(text):
        genannt = [name for name, pattern in muster if pattern.search(satz)]
        if len(genannt) >= 2 and hat_handlung(satz):
            treffer.append({"satz": satz, "elemente": genannt})
    return treffer


# --------------------------------------------------------------------------
# Kanten
# --------------------------------------------------------------------------


def _ohne_paket(ref: str) -> str:
    return str(ref).split("::")[-1].strip()


def kanten(ir: Mapping[str, Any], ruleset: validator.RuleSet) -> list[dict[str, Any]]:
    """Jede Kante des IR mit ihrem MDG-Urteil."""
    model = validator._read_model(ir)
    findings: list[Any] = []
    _, invalid = validator._check_connectors(findings, model, ruleset)
    gruende: dict[str, list[str]] = {}
    for finding in findings:
        gruende.setdefault(getattr(finding, "object", ""), []).append(
            getattr(finding, "message", "")
        )
    rows: list[dict[str, Any]] = []
    for connector in model.connectors:
        label = validator._connector_label(connector)
        rows.append(
            {
                "kante": label,
                "quelle": _ohne_paket(connector.source),
                "ziel": _ohne_paket(connector.target),
                "stereotyp": connector.stereotype,
                "gueltig": connector.index not in invalid,
                "gruende": gruende.get(label, []),
            }
        )
    return rows


def ausbeute(
    text: str,
    ir: Mapping[str, Any],
    ruleset: validator.RuleSet,
) -> dict[str, Any]:
    """Handlungssaetze gegen gueltige Kanten rechnen."""
    namen = elementnamen(ir)
    saetze = handlungssaetze(text, namen)
    kantenliste = kanten(ir, ruleset)
    gueltig = [row for row in kantenliste if row["gueltig"]]

    gedeckt: list[dict[str, Any]] = []
    offen: list[dict[str, Any]] = []
    for satz in saetze:
        genannt = {name.casefold() for name in satz["elemente"]}
        passend = [
            row
            for row in gueltig
            if row["quelle"].casefold() in genannt and row["ziel"].casefold() in genannt
        ]
        eintrag = dict(satz)
        eintrag["kanten"] = [row["kante"] for row in passend]
        if passend:
            gedeckt.append(eintrag)
        else:
            offen.append(eintrag)

    gesamt = len(saetze)
    return {
        "handlungssaetze": gesamt,
        "gedeckt": len(gedeckt),
        "ausbeute": round(100.0 * len(gedeckt) / gesamt, 1) if gesamt else 0.0,
        "kanten_roh": len(kantenliste),
        "kanten_gueltig": len(gueltig),
        "kantenausbeute": round(100.0 * len(gueltig) / len(kantenliste), 1)
        if kantenliste
        else 0.0,
        "elemente": len(namen),
        "ungedeckt": [
            {"satz": eintrag["satz"], "elemente": eintrag["elemente"]}
            for eintrag in offen[:LISTEN_LIMIT]
        ],
        "ungedeckt_gesamt": len(offen),
        "kanten": kantenliste,
    }


# --------------------------------------------------------------------------
# Ein- und Ausgabe
# --------------------------------------------------------------------------


def _lies_text(pfad: Path) -> str:
    try:
        return pfad.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise AusbeuteFehler(f"{pfad}: Quelle nicht lesbar: {exc}") from exc


def _lies_json(pfad: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AusbeuteFehler(f"{pfad}: IR nicht lesbar: {exc}") from exc
    if not isinstance(data, Mapping):
        raise AusbeuteFehler(f"{pfad}: IR ist kein JSON-Objekt")
    return data


def lade_regeln(mdg: Path) -> validator.RuleSet:
    """Regelwerk aus der MDG-XML bauen (gleicher Weg wie ``eam-ai build``)."""
    import mdg_parser  # packages/rules, liegt im Suchpfad

    try:
        daten = mdg_parser.parse_mdg(str(mdg))
    except Exception as exc:  # noqa: BLE001 -- Parserfehler im Klartext melden
        raise AusbeuteFehler(f"{mdg}: Regelwerk nicht lesbar: {exc}") from exc
    try:
        return validator.build_rules(daten)
    except validator.ValidatorError as exc:
        raise AusbeuteFehler(f"{mdg}: Regelwerk ungueltig: {exc}") from exc


def bericht(text_pfad: Path, ir_pfad: Path, mdg_pfad: Path) -> dict[str, Any]:
    text = _lies_text(text_pfad)
    ir = _lies_json(ir_pfad)
    ruleset = lade_regeln(mdg_pfad)
    daten = ausbeute(text, ir, ruleset)
    daten["quelle"] = str(text_pfad)
    daten["modell"] = str(ir_pfad)
    daten["regelwerk"] = ruleset.name or str(mdg_pfad)
    return daten


def render_markdown(daten: Mapping[str, Any]) -> str:
    zeilen = [
        "# Kantenausbeute",
        "",
        f"- Quelle: `{daten.get('quelle', '')}`",
        f"- Modell: `{daten.get('modell', '')}`",
        f"- Regelwerk: {daten.get('regelwerk', '')}",
        "",
        "| Kennzahl | Wert |",
        "|---|---|",
        f"| Elemente im Modell | {daten.get('elemente', 0)} |",
        f"| Handlungssaetze | {daten.get('handlungssaetze', 0)} |",
        f"| davon mit gueltiger Kante | {daten.get('gedeckt', 0)} |",
        f"| **Ausbeute** | **{daten.get('ausbeute', 0)} %** |",
        f"| Kanten geliefert / gueltig | {daten.get('kanten_roh', 0)} / "
        f"{daten.get('kanten_gueltig', 0)} |",
        f"| Kantenausbeute | {daten.get('kantenausbeute', 0)} % |",
        "",
    ]
    offen = daten.get("ungedeckt") or []
    if offen:
        zeilen += [f"## Ohne gueltige Kante ({daten.get('ungedeckt_gesamt', 0)})", ""]
        for eintrag in offen:
            zeilen.append(f"- {eintrag['satz']}")
            zeilen.append(f"  Elemente: {', '.join(eintrag['elemente'])}")
        zeilen.append("")
    return "\n".join(zeilen)


def _schreibe(pfad: Path, inhalt: str) -> None:
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(inhalt, encoding="utf-8")
    except OSError as exc:
        raise AusbeuteFehler(f"{pfad}: nicht schreibbar: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kantenausbeute einer Extraktion messen")
    parser.add_argument("--text", required=True, type=Path, help="Quelltext")
    parser.add_argument("--ir", required=True, type=Path, help="IR als JSON")
    parser.add_argument("--mdg", required=True, type=Path, help="MDG-/Technologie-XML")
    parser.add_argument("--json", type=Path, default=None, help="Bericht als JSON")
    parser.add_argument("--md", type=Path, default=None, help="Bericht als Markdown")
    args = parser.parse_args(argv)

    try:
        daten = bericht(args.text, args.ir, args.mdg)
    except AusbeuteFehler as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json is not None:
        try:
            _schreibe(args.json, text)
        except AusbeuteFehler as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.md is not None:
        try:
            _schreibe(args.md, render_markdown(daten))
        except AusbeuteFehler as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.json is None and args.md is None:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
