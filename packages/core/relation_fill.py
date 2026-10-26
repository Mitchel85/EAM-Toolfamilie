#!/usr/bin/env python3
"""relation_fill.py -- fehlende Kanten aus eindeutigen Handlungssaetzen ergaenzen.

Die Extraktion liefert Elemente und Notizen zuverlaessig, Kanten aber duenn.
Dieser Schritt liest den Quelltext noch einmal und ergaenzt nur dort eine
Kante, wo der Satz **genau zwei** Elementnamen und ein Handlungsverb nennt.
Damit ist die Aussage eindeutig auf zwei Endpunkte bezogen; Saetze mit drei
oder mehr Namen bleiben unangetastet, weil dort die Zuordnung mehrdeutig ist.

Warum nicht alles der KI ueberlassen?
-------------------------------------
Der Modellaufruf ist gut darin, Elemente und Notizen zu finden, aber er
entscheidet bei Kanten oft gegen die MDG. Ein Satz wie "Die Sensoren dienen
der Aufklaerung ... die Effektoren bekaempfen" nennt beide Endpunkte; die
Kante fehlt trotzdem. Der Nachtrag ist deterministisch, wiederholbar und
prueft jeden Kandidaten gegen das Regelwerk, bevor er ihn behaelt.

Grenzen
-------
* Nur Saetze mit genau zwei Elementnamen. Alles andere waere geraten.
* Nur Kanten, die die MDG-Pruefung als **fehlerfrei** besteht. Ein Kandidat,
  der nur mit einer Warnung durchkommt, wird verworfen.
* Keine Dubletten: existiert zwischen den beiden Elementen bereits eine
  Kante (in beliebiger Richtung), bleibt der Satz unveraendert.
* Der Nachtrag erfindet keine Elemente und keine Notizen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import validator

#: Reihenfolge der Kandidaten. Die erste Regel, die die MDG besteht, gewinnt.
#: Die Liste beginnt bewusst mit fachlich engen Kanten und endet mit den
#: allgemeinen; so entsteht nicht bei jedem Satz dieselbe Allzweck-Kante.
KANDIDATEN: tuple[str, ...] = (
    "Satisfy",
    "ActualResourceRelationship",
    "ResourceToServiceDependency",
    "Consumes",
    "Provides",
    "Control",
    "Composition",
    "Aggregation",
    "Association",
    "Generalization",
    "Specialization",
    "HostedOn",
    "Implements",
    "Dependency",
)

_WORTANFANG = r"(?<![A-Za-zÄÖÜäöüß])"


@dataclass(frozen=True)
class Nachtrag:
    """Eine ergaenzte Kante mit ihrem Belegsatz."""

    quelle: str
    ziel: str
    stereotyp: str
    satz: str
    ref: str


def _saetze(text: str) -> list[str]:
    """Saetze absatzweise; Tabellen und fett gesetzte Glossarlabels fallen weg."""
    saetze: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        zeilen = [
            zeile.strip().replace("**", "")
            for zeile in block.splitlines()
            if zeile.strip() and not zeile.lstrip().startswith(("#", "|"))
        ]
        if not zeilen:
            continue
        for roh in re.split(r"(?<=[.!?])\s+", " ".join(zeilen)):
            for satz in re.split(r"(?<=[.!?])(?=[A-ZÄÖÜ])", roh):
                # Ein Semikolon trennt zwei Aussagen; nur die erste nennt oft
                # beide Endpunkte, die zweite wiederholt das Objekt.
                for teil in satz.split(";"):
                    if len(teil.split()) >= 2:
                        saetze.append(teil.strip())
    return saetze


def _namen(ir: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Elementnamen auf ihr IR-Objekt, ohne Dubletten.

    Elemente *sind* die Endpunkte der Kante. Deshalb wird hier nichts
    weggefiltert: nur Namen, die im Modell stehen, koennen Endpunkt sein.
    """
    namen: dict[str, Mapping[str, Any]] = {}
    for element in ir.get("elements") or ():
        if not isinstance(element, Mapping):
            continue
        name = str(element.get("name") or "").strip()
        if len(name) < 3:
            continue
        namen.setdefault(name, element)
    return namen


def _genannt(satz: str, namen: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Elementnamen in der Reihenfolge ihres Auftretens im Satz.

    Nur Namen aus dem Modell zaehlen. Ein Sammelbegriff wie "die Baugruppen"
    ist kein Endpunkt und steht folglich nicht im IR -- ein frueherer
    Filterkatalog dafuer war modellspezifisch und ist entfallen.
    """
    treffer: list[tuple[int, str]] = []
    for name in namen:
        m = re.search(_WORTANFANG + re.escape(name) + r"\b", satz, flags=re.IGNORECASE)
        if m:
            treffer.append((m.start(), name))
    return [name for _, name in sorted(treffer)]


def _ref(element: Mapping[str, Any]) -> str:
    paket = str(element.get("package") or "").strip()
    name = str(element.get("name") or "").strip()
    return f"{paket}::{name}" if paket else name


def _passt(ir: Mapping[str, Any], connector: Mapping[str, Any], ruleset: validator.RuleSet) -> bool:
    """Besteht die Kante die MDG-Pruefung ohne Fehler?"""
    probe = dict(ir)
    probe["connectors"] = list(ir.get("connectors") or ()) + [dict(connector)]
    label = f"{connector['source']} -> {connector['target']} [{connector['stereotype']}]"
    try:
        findings = validator.validate_model(probe, ruleset)
    except validator.ValidatorError:
        return False
    return not any(
        finding.get("severity") == validator.ERROR and finding.get("object") == label
        for finding in findings
    )


def _kandidat(
    ir: Mapping[str, Any],
    quelle: Mapping[str, Any],
    ziel: Mapping[str, Any],
    satz: str,
    ref: str,
    ruleset: validator.RuleSet,
    kandidaten: Sequence[str] = KANDIDATEN,
) -> Nachtrag | None:
    for stereotyp in kandidaten:
        if stereotyp not in ruleset.connectors:
            continue
        connector = {
            "source": _ref(quelle),
            "target": _ref(ziel),
            "stereotype": stereotyp,
            "ea_type": "Dependency",
            "name": "",
            "direction": "Source -> Destination",
            "notes": satz,
            "tags": {
                "source_ref": ref,
                "source_doc": ref.split("-")[0] if "-" in ref else "D1",
                "source_confidence": "0.60",
            },
        }
        if _passt(ir, connector, ruleset):
            return Nachtrag(
                quelle=str(quelle.get("name") or ""),
                ziel=str(ziel.get("name") or ""),
                stereotyp=stereotyp,
                satz=satz,
                ref=ref,
            )
    return None


def ergaenze(
    ir: dict[str, Any],
    absaetze: Sequence[Any],
    ruleset: validator.RuleSet,
) -> list[Nachtrag]:
    """Ergaenzt eindeutige Handlungssaetze als Kanten und meldet sie zurueck.

    ``absaetze`` sind Objekte mit ``text`` und ``ref`` (die Segmente aus
    ``extract.split_documents``). Das IR wird an Ort und Stelle veraendert.
    """
    namen = _namen(ir)
    if len(namen) < 2:
        return []
    vorhanden = {
        (str(c.get("source") or ""), str(c.get("target") or ""))
        for c in ir.get("connectors") or ()
        if isinstance(c, Mapping)
    }
    vorhanden |= {(ziel, quelle) for quelle, ziel in vorhanden}

    nachtraege: list[Nachtrag] = []
    for absatz in absaetze:
        for satz in _saetze(str(getattr(absatz, "text", "") or "")):
            genannt = _genannt(satz, namen)
            if len(genannt) != 2:
                continue
            if not _hat_handlung(satz):
                continue
            quelle, ziel = namen[genannt[0]], namen[genannt[1]]
            paar = (_ref(quelle), _ref(ziel))
            if paar in vorhanden:
                continue
            # "visuelle Sensoren" ist ein Unterbegriff von "Sensoren"; eine
            # HostedOn-Kante waere hier falsch. Nur Generalisierung zulassen,
            # sonst den Satz auslassen.
            teilbegriff = (
                genannt[0].casefold() in genannt[1].casefold()
                or genannt[1].casefold() in genannt[0].casefold()
            )
            kandidaten = (
                ("Generalization", "Specialization") if teilbegriff else KANDIDATEN
            )
            nachtrag = _kandidat(
                ir,
                quelle,
                ziel,
                satz,
                str(getattr(absatz, "ref", "") or ""),
                ruleset,
                kandidaten,
            )
            if nachtrag is None:
                continue
            ir.setdefault("connectors", []).append(
                {
                    "source": _ref(quelle),
                    "target": _ref(ziel),
                    "stereotype": nachtrag.stereotyp,
                    "ea_type": "Dependency",
                    "name": "",
                    "direction": "Source -> Destination",
                    "notes": satz,
                    "tags": {
                        "source_ref": nachtrag.ref,
                        "source_doc": nachtrag.ref.split("-")[0] if "-" in nachtrag.ref else "D1",
                        "source_confidence": "0.60",
                    },
                }
            )
            vorhanden.add(paar)
            vorhanden.add((paar[1], paar[0]))
            nachtraege.append(nachtrag)
    return nachtraege


_VERBEN = (
    "nutzen", "liefern", "bereitstellen", "stellen", "steuern", "erfassen",
    "übermitteln", "uebermitteln", "gehören", "gehoeren", "benötigen",
    "benoetigen", "greifen", "erzeugen", "prüfen", "pruefen", "sammeln",
    "ordnen", "verteilen", "dienen", "führen", "fuehren", "geben", "nehmen",
    "empfangen", "senden", "übertragen", "uebertragen", "bestimmen",
    "ermitteln", "melden", "freigeben", "starten", "tragen", "halten",
    "gewährleisten", "gewaehrleisten", "sichern", "unterstützen",
    "unterstuetzen", "ermöglichen", "ermoeglichen", "aufklären", "aufklaeren",
    "bilden", "wirken", "bedienen", "warten", "speichern", "abrufen",
    "verbinden", "trennen", "regeln", "schützen", "schuetzen", "überwachen",
    "ueberwachen", "erheben", "zuordnen", "ausgeben", "vorhalten",
)


#: Substantivformen, die wie ein Verbstamm aussehen ("Dienst" vs. "dient").
_KEINE_VERBEN = frozenset(
    {"Dienst", "Dienste", "Diensten", "Dienstes", "Bild", "Bilder", "Bildung"}
)


def _hat_handlung(satz: str) -> bool:
    """Enthaelt der Satz ein Handlungsverb (Wortanfang, Inflexion erlaubt)?"""
    for verb in _VERBEN:
        stamm = verb[:-2] if verb.endswith("en") else verb[:-1]
        for treffer in re.finditer(
            _WORTANFANG + re.escape(stamm) + r"\w*", satz, flags=re.IGNORECASE
        ):
            if treffer.group(0).casefold() not in {w.casefold() for w in _KEINE_VERBEN}:
                return True
    return False
