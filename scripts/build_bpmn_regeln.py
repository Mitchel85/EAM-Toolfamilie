#!/usr/bin/env python3
"""Baut ``knowledge/bpmn/prozess-regeln.json`` -- die Regelgrundlage fuer BMC.

Warum ein Generator und keine handgeschriebene Datei
----------------------------------------------------
Der Auftrag verlangt: kein Stereotyp erfinden, jede Angabe mit Quelle. Beides
ist nur pruefbar, wenn die Datei aus den Quellen entsteht:

* ``apps/admbw-extractor/ADMBw-Stereotypes.json`` -- was es an Stereotypen
  gibt (Name, ``appliesTo``, abstrakt, Eltern),
* ``packages/rules/NAFv4-ADMBw-MDG-2026.05.xml`` -- wohin ein Stereotyp darf
  (Metaconstraints der Kanten),
* ``knowledge/leitfaden/konventionen.json`` -- die L4-MK-Texte,
* ``knowledge/regelwerk.json`` -- die L4-Sicht (erlaubte Elemente, Werkzeugkasten).

Die Abbildung BPMN-Element -> ADMBw-Stereotyp und die Pruefregeln stehen
unten als Tabelle im Code. Sie sind damit reviewbar; die Datei ist das
Ergebnis, nicht die Quelle.

Aufruf
------
    python3 scripts/build_bpmn_regeln.py [--check]

``--check`` schreibt nichts und vergleicht nur (Exit 1 bei Abweichung).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ZIEL = ROOT / "knowledge" / "bpmn" / "prozess-regeln.json"

STEREOYPE_DATEI = ROOT / "apps" / "admbw-extractor" / "ADMBw-Stereotypes.json"
MDG_DATEI = ROOT / "packages" / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml"
KONVENTIONEN_DATEI = ROOT / "knowledge" / "leitfaden" / "konventionen.json"
REGELWERK_DATEI = ROOT / "knowledge" / "regelwerk.json"

#: Stereotype, die im BPMN-Kontext vorkommen. Nur diese werden uebernommen;
#: alles andere bleibt draussen, damit die Datei lesbar bleibt.
RELEVANTE_STEREOTYPE = (
    "OperationalActivity",
    "OperationalActivityAction",
    "OperationalControlFlow",
    "OperationalMessageFlow",
    "OperationalObjectFlow",
    "OperationalActivityEdge",
    "OperationalExchange",
    "OperationalExchangeItem",
    "ExchangeItem",
    "OperationalPerformer",
    "OperationalAgent",
    "OperationalArchitecture",
    "OperationalRole",
    "InformationElement",
    "InformationRole",
    "OperationalSignal",
    "BusinessProcess",
    "StandardOperationalActivity",
    "Implements",
    "PerformsInContext",
)

#: BPMN-Element -> ADMBw. ``None`` heisst: kein Stereotyp in der MDG-Liste.
#: ``sicherheit``: ``belegt`` (Leitfaden nennt das Element ausdruecklich),
#: ``abgeleitet`` (aus Leitfaden und ``appliesTo`` geschlossen),
#: ``kein-stereotyp`` (bewusst ohne Stereotyp).
ELEMENTTYPEN: dict[str, dict[str, Any]] = {
    "start_event": {
        "bpmn": "startEvent",
        "admbw": None,
        "sicherheit": "kein-stereotyp",
        "begruendung": (
            "BPMN-Standardereignis. Die MDG 2026.05 fuehrt kein Stereotyp fuer "
            "Startereignisse; der Leitfaden nennt STARTEVENT nur als Prozesselement."
        ),
        "konventionen": ["L4-MK11", "L4-MK12", "L4-MK13", "L4-MK16"],
        "quelle": ["leitfaden:L4-MK11", "admbw-stereotypes:ohne-treffer"],
    },
    "end_event": {
        "bpmn": "endEvent",
        "admbw": None,
        "sicherheit": "kein-stereotyp",
        "begruendung": (
            "BPMN-Standardereignis ohne ADMBw-Stereotyp in der MDG 2026.05."
        ),
        "konventionen": ["L4-MK11", "L4-MK12", "L4-MK13", "L4-MK16"],
        "quelle": ["leitfaden:L4-MK11", "admbw-stereotypes:ohne-treffer"],
    },
    "intermediate_catch_event": {
        "bpmn": "intermediateCatchEvent",
        "admbw": None,
        "sicherheit": "kein-stereotyp",
        "begruendung": (
            "Fuer L4-MK18 vorgesehen (Bedingung vor einer Aktion). Kein eigenes "
            "ADMBw-Stereotyp; die MDG nennt BPMN2.0::IntermediateEvent nur als "
            "erlaubtes Ende von OperationalControlFlow und OperationalMessageFlow."
        ),
        "konventionen": ["L4-MK13", "L4-MK15", "L4-MK18", "L4-MK20"],
        "quelle": ["leitfaden:L4-MK18", "mdg:OperationalControlFlow"],
    },
    "intermediate_throw_event": {
        "bpmn": "intermediateThrowEvent",
        "admbw": None,
        "sicherheit": "kein-stereotyp",
        "begruendung": "Wie das empfangende Zwischenereignis: BPMN-Standard ohne ADMBw-Stereotyp.",
        "konventionen": ["L4-MK13", "L4-MK15", "L4-MK18"],
        "quelle": ["leitfaden:L4-MK18", "admbw-stereotypes:ohne-treffer"],
    },
    "task": {
        "bpmn": "task",
        "admbw": "OperationalActivityAction",
        "sicherheit": "belegt",
        "begruendung": (
            "L4-MK14 verlangt, dass Aktionen (OPERATIONALACTIVITYACTION) ueber das "
            "Behavior mit der Aktivitaet typisiert sind; OperationalActivityAction "
            "ist das einzige nicht abstrakte Stereotyp auf UML Action."
        ),
        "konventionen": ["L4-MK11", "L4-MK12", "L4-MK13", "L4-MK14", "L4-MK15", "L4-MK16", "L4-MK17"],
        "quelle": ["admbw-stereotypes:OperationalActivityAction", "admbw-doku:3.152", "leitfaden:L4-MK14"],
    },
    "service_task": {"wie": "task"},
    "user_task": {"wie": "task"},
    "send_task": {"wie": "task"},
    "receive_task": {"wie": "task"},
    "script_task": {"wie": "task"},
    "manual_task": {"wie": "task"},
    "business_rule_task": {"wie": "task"},
    "exclusive_gateway": {
        "bpmn": "exclusiveGateway",
        "admbw": None,
        "sicherheit": "kein-stereotyp",
        "begruendung": (
            "L4-MK15 verlangt Verzweigung und Zusammenfuehrung ueber Gateways. "
            "Die MDG fuehrt kein Gateway-Stereotyp; BPMN2.0::Gateway erscheint nur "
            "in den Metaconstraints der Kanten."
        ),
        "konventionen": ["L4-MK13", "L4-MK15"],
        "quelle": ["leitfaden:L4-MK15", "mdg:OperationalControlFlow"],
    },
    "parallel_gateway": {"wie": "exclusive_gateway"},
    "inclusive_gateway": {"wie": "exclusive_gateway"},
    "event_based_gateway": {"wie": "exclusive_gateway"},
    "complex_gateway": {"wie": "exclusive_gateway"},
    "sequence_flow": {
        "bpmn": "sequenceFlow",
        "admbw": "OperationalControlFlow",
        "sicherheit": "belegt",
        "begruendung": "L4-MK15: prozessual abhaengige Elemente sind ueber einen Kontrollfluss (CONTROLFLOW) verbunden.",
        "konventionen": ["L4-MK15", "L4-MK17"],
        "quelle": ["admbw-stereotypes:OperationalControlFlow", "mdg:OperationalControlFlow", "leitfaden:L4-MK15"],
    },
    "message_flow": {
        "bpmn": "messageFlow",
        "admbw": "OperationalMessageFlow",
        "sicherheit": "belegt",
        "begruendung": "L4-MK20: Der Informationsaustausch zwischen Pools erfolgt ueber OPERATIONALMESSAGEFLOW.",
        "konventionen": ["L4-MK20"],
        "quelle": ["admbw-stereotypes:OperationalMessageFlow", "admbw-doku:3.165", "leitfaden:L4-MK20"],
    },
    "association": {
        "bpmn": "association",
        "admbw": "OperationalExchange",
        "sicherheit": "abgeleitet",
        "begruendung": (
            "L4-MK17 verlangt Conveyed Items (EXCHANGEITEM), die mit dem Kontrollfluss "
            "verknuepft sind. In BPMN traegt die Assoziation Datenobjekt an Fluss; in "
            "ADMBw ist OperationalExchange (UML InformationFlow) die Beziehung mit "
            "conveyed-Element. Die Abbildung ist aus beiden Quellen geschlossen, nicht "
            "woertlich belegt."
        ),
        "konventionen": ["L4-MK17", "L4-MK20"],
        "quelle": ["admbw-stereotypes:OperationalExchange", "admbw-doku:3.161", "mdg:OperationalExchange", "leitfaden:L4-MK17"],
    },
    "data_object_reference": {
        "bpmn": "dataObjectReference",
        "admbw": "InformationElement",
        "sicherheit": "abgeleitet",
        "begruendung": (
            "L4-MK17: Conveyed Items sind EXCHANGEITEM. ExchangeItem und "
            "OperationalExchangeItem sind abstrakt und nicht instanziierbar; "
            "InformationElement ist der naechstliegende konkrete Nachfahre fuer "
            "Informationsfluesse. Bei Signalen ist OperationalSignal zu waehlen."
        ),
        "konventionen": ["L4-MK17", "L4-MK20"],
        "quelle": ["admbw-stereotypes:InformationElement", "admbw-stereotypes:ExchangeItem", "leitfaden:L4-MK17"],
    },
    "participant": {
        "bpmn": "participant",
        "admbw": "OperationalArchitecture",
        "sicherheit": "abgeleitet",
        "begruendung": (
            "L4-MK08: Der betrachtete Anwendungsfall (OPERATIONALARCHITECTURE) wird "
            "auf das Diagramm gezogen; L4-MK09 typisiert Pools mit ihm. Der Pool "
            "traegt den Typ, nicht das Stereotyp -- in ADMBw ist der Typ eine Klasse."
        ),
        "konventionen": ["L4-MK08", "L4-MK09", "L4-MK10", "L4-MK16"],
        "quelle": ["admbw-stereotypes:OperationalArchitecture", "leitfaden:L4-MK08", "leitfaden:L4-MK09"],
    },
    "lane": {
        "bpmn": "lane",
        "admbw": "OperationalPerformer",
        "sicherheit": "abgeleitet",
        "begruendung": (
            "L4-MK09: Lanes werden mit den Aufgabentraegern (OPERATIONALPERFORMER) "
            "typisiert. OperationalPerformer ist UML Class; die Lane traegt den Typ."
        ),
        "konventionen": ["L4-MK09", "L4-MK10", "L4-MK12"],
        "quelle": ["admbw-stereotypes:OperationalPerformer", "leitfaden:L4-MK09", "leitfaden:L4-MK10"],
    },
}

#: L4-Konventionen, die sich aus einer BPMN-Datei pruefen lassen.
PRUEFREGELN: list[dict[str, Any]] = [
    {
        "id": "BPMN-L4-01",
        "konvention": "L4-MK08",
        "schwere": "fehler",
        "titel": "Kollaborationsdiagramm mit Pool vorhanden",
        "beschreibung": (
            "Das Modell muss eine Kollaboration mit mindestens einem Teilnehmer (Pool) "
            "enthalten; jeder Teilnehmer muss auf einen vorhandenen Prozess zeigen."
        ),
        "objekt": "modell",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-02",
        "konvention": "L4-MK09",
        "schwere": "warnung",
        "titel": "Pool und Lanes sind benannt",
        "beschreibung": "Jeder Pool und jede Lane braucht einen Namen; Lanes sind nach Aufgabentraegern zu benennen.",
        "objekt": "teilnehmer",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-03",
        "konvention": "L4-MK09",
        "schwere": "warnung",
        "titel": "Lane ist mit einem Aufgabentraeger typisiert",
        "beschreibung": "Jede Lane soll auf einen OperationalPerformer verweisen (PERFORMSINCONTEXT, L4-MK10).",
        "objekt": "lane",
        "behebbar": False,
    },
    {
        "id": "BPMN-L4-04",
        "konvention": "L4-MK12",
        "schwere": "fehler",
        "titel": "Alle Knoten liegen in einer Lane",
        "beschreibung": (
            "Existieren Lanes, muss jeder Flussknoten genau einer Lane zugeordnet sein; "
            "sonst liegt er nur im Pool und ist fachlich nicht zugeordnet."
        ),
        "objekt": "knoten",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-05",
        "konvention": "L4-MK14",
        "schwere": "fehler",
        "titel": "Aktion traegt das ADMBw-Stereotyp",
        "beschreibung": "Jede Aufgabe muss das Stereotyp OperationalActivityAction tragen (UML Action, nicht abstrakt).",
        "objekt": "aktion",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-06",
        "konvention": "L4-MK14",
        "schwere": "warnung",
        "titel": "Aktion hat einen aussagefaehigen Namen",
        "beschreibung": "Der Name einer Aktion darf nicht leer sein und soll die Taetigkeit benennen (Verb + Objekt).",
        "objekt": "aktion",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-07",
        "konvention": "L4-MK15",
        "schwere": "fehler",
        "titel": "Kontrollfluss verbindet zulaessige Elemente",
        "beschreibung": (
            "Quelle eines OperationalControlFlow darf nur Gateway, Zwischenereignis, "
            "Startereignis oder Aktion sein; Ziel nur Endereignis, Gateway, "
            "Zwischenereignis oder Aktion (MDG-Metaconstraints)."
        ),
        "objekt": "fluss",
        "behebbar": False,
    },
    {
        "id": "BPMN-L4-08",
        "konvention": "L4-MK15",
        "schwere": "fehler",
        "titel": "Verzweigung und Zusammenfuehrung nur ueber Gateways",
        "beschreibung": (
            "Ein Knoten mit mehr als einem ausgehenden oder eingehenden Sequenzfluss "
            "muss ein Gateway sein; Verzweigungen duerfen nicht an Aktionen haengen."
        ),
        "objekt": "knoten",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-09",
        "konvention": "L4-MK15",
        "schwere": "fehler",
        "titel": "Zusammenfuehrung nutzt den Gateway-Typ der Verzweigung",
        "beschreibung": (
            "L4-MK15: Die Zusammenfuehrung erfolgt durch den Gateway-Typen, der fuer "
            "die Verzweigung verwendet wurde."
        ),
        "objekt": "gateway",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-10",
        "konvention": "L4-MK16",
        "schwere": "fehler",
        "titel": "Pool hat einen abgeschlossenen Prozess",
        "beschreibung": (
            "Jeder ausgemodellte Pool braucht mindestens Startereignis, eine Aktion und "
            "Endereignis; jeder Knoten muss vom Startereignis aus erreichbar sein."
        ),
        "objekt": "prozess",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-11",
        "konvention": "L4-MK17",
        "schwere": "warnung",
        "titel": "Aktion hat Trigger und Ergebnis als Conveyed Items",
        "beschreibung": (
            "Jede Aktion soll an eingehendem und ausgehendem Kontrollfluss je ein "
            "Datenobjekt (EXCHANGEITEM) tragen."
        ),
        "objekt": "aktion",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-12",
        "konvention": "L4-MK18",
        "schwere": "fehler",
        "titel": "Bedingung haengt an Gateway oder Zwischenereignis",
        "beschreibung": (
            "Ein bedingter Sequenzfluss darf nur von einem Gateway oder einem "
            "Zwischenereignis ausgehen; eine Vorbedingung vor einer Aktion ist als "
            "Zwischenereignis zu modellieren."
        ),
        "objekt": "fluss",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-13",
        "konvention": "L4-MK20",
        "schwere": "fehler",
        "titel": "Nachrichtenfluss ist pooluebergreifend und traegt ein Conveyed Item",
        "beschreibung": (
            "Ein Nachrichtenfluss verbindet zwei verschiedene Pools und soll ein "
            "Datenobjekt (EXCHANGEITEM) tragen; der Empfang vor einer Aktion ist als "
            "Zwischenereignis zu modellieren."
        ),
        "objekt": "fluss",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-14",
        "konvention": "L4-MK11",
        "schwere": "fehler",
        "titel": "Prozess hat ein Startereignis",
        "beschreibung": "Ohne Startereignis ist kein Einstiegspunkt definiert.",
        "objekt": "prozess",
        "behebbar": True,
    },
    {
        "id": "BPMN-L4-15",
        "konvention": "L4-MK10",
        "schwere": "hinweis",
        "titel": "Pool ist mit dem Anwendungsfall typisiert",
        "beschreibung": "Der Pool soll auf eine OperationalArchitecture (Anwendungsfall) verweisen.",
        "objekt": "teilnehmer",
        "behebbar": False,
    },
]

#: L4-Konventionen, die eine BPMN-Datei nicht beantworten kann.
NICHT_PRUEFBAR: list[dict[str, str]] = [
    {"konvention": "L4-MK01", "grund": "Package-Struktur im Modellrepository, nicht im BPMN-Dokument."},
    {"konvention": "L4-MK02", "grund": "Diagrammtyp und Diagrammname im Werkzeug, nicht im BPMN-Austausch."},
    {"konvention": "L4-MK03", "grund": "Katalogbezug (Modellelementekatalog) liegt ausserhalb der Datei."},
    {"konvention": "L4-MK04", "grund": "Referenzprozesse stammen aus dem Katalog, nicht aus dem Prozess."},
    {"konvention": "L4-MK05", "grund": "IMPLEMENTS-Verknuepfung zum Referenzprozess braucht das Zielmodell."},
    {"konvention": "L4-MK06", "grund": "TaggedValue abstractionLevel ist eine Modelleigenschaft, kein BPMN-Attribut."},
    {"konvention": "L4-MK07", "grund": "Composite-Diagramm der Aktivitaet -- Sache des Repositorys."},
    {"konvention": "L4-MK19", "grund": "IMPLEMENTS zum Referenzprozessschritt braucht den Referenzprozess."},
]


def sha256(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def lade_json(pfad: Path) -> Any:
    return json.loads(pfad.read_text(encoding="utf-8"))


def lese_stereotype() -> dict[str, dict[str, Any]]:
    daten = lade_json(STEREOYPE_DATEI)
    index = {eintrag["name"]: eintrag for eintrag in daten["stereotypes"]}
    ergebnis: dict[str, dict[str, Any]] = {}
    for name in RELEVANTE_STEREOTYPE:
        eintrag = index.get(name)
        if eintrag is None:
            continue
        ergebnis[name] = {
            "name": name,
            "appliesTo": list(eintrag.get("appliesTo") or []),
            "abstract": bool(eintrag.get("abstract")),
            "parents": list(eintrag.get("parents") or []),
            "konkreteNachfahren": list(eintrag.get("concreteDescendants") or [])[:12],
            "herkunft": {
                "datei": "apps/admbw-extractor/ADMBw-Stereotypes.json",
                "release": daten.get("release", ""),
                "quelle": daten.get("source", ""),
                "feld": f"stereotypes[name={name}]",
            },
        }
    return ergebnis


def lese_metaconstraints() -> dict[str, dict[str, list[str]]]:
    """Erlaubte Quellen und Ziele der Prozesskanten aus der MDG."""
    text = MDG_DATEI.read_text(encoding="utf-8", errors="replace")
    ergebnis: dict[str, dict[str, list[str]]] = {}
    for name in ("OperationalControlFlow", "OperationalMessageFlow", "OperationalObjectFlow"):
        treffer = re.search(
            r'<Stereotype name="%s".*?</Stereotype>' % re.escape(name), text, re.S
        )
        if not treffer:
            continue
        block = treffer.group(0)
        regeln: dict[str, list[str]] = {}
        for rolle in ("source", "target"):
            m = re.search(
                r'<metaconstraint umlRole="%s" constraint="([^"]+)"' % rolle, block
            )
            if m:
                regeln[rolle] = [teil.strip() for teil in m.group(1).split(";") if teil.strip()]
        ergebnis[name] = regeln
    return ergebnis


def lese_konventionen() -> dict[str, dict[str, str]]:
    eintraege = lade_json(KONVENTIONEN_DATEI)
    ergebnis: dict[str, dict[str, str]] = {}
    for eintrag in eintraege:
        if eintrag.get("viewpoint") == "L4":
            ergebnis[eintrag["id"]] = {
                "text": eintrag["text"],
                "verweis": eintrag.get("verweis", "-"),
                "art": eintrag.get("kind", ""),
            }
    return ergebnis


def lese_l4_sicht() -> dict[str, Any]:
    regelwerk = lade_json(REGELWERK_DATEI)
    sicht = regelwerk["viewpoints"].get("L4", {})
    return {
        "titel": sicht.get("titel", ""),
        "toolbox": sicht.get("mdg", {}).get("toolbox", ""),
        "elemente": sorted(sicht.get("mdg", {}).get("elemente", [])),
        "konventionen": sorted(sicht.get("leitfaeden", {}).get("ffmlv", {}).get("ids", [])),
        "herkunft": "knowledge/regelwerk.json:viewpoints.L4",
    }


def baue() -> dict[str, Any]:
    stereotype = lese_stereotype()
    metaconstraints = lese_metaconstraints()
    konventionen = lese_konventionen()

    elementtypen: dict[str, dict[str, Any]] = {}
    for art, eintrag in ELEMENTTYPEN.items():
        if "wie" in eintrag:
            basis = dict(elementtypen[eintrag["wie"]])
            basis["bpmn"] = eintrag.get("bpmn", basis["bpmn"])
            basis["hinweis"] = f"gleiche Abbildung wie {eintrag['wie']}"
            elementtypen[art] = basis
            continue
        kopie = dict(eintrag)
        kopie["admbwVorhanden"] = (
            eintrag["admbw"] in stereotype if eintrag.get("admbw") else False
        )
        elementtypen[art] = kopie

    # Pruefregeln mit Konventionstext anreichern; jede Regel muss eine
    # existierende L4-MK nennen.
    regeln: list[dict[str, Any]] = []
    for regel in PRUEFREGELN:
        kid = regel["konvention"]
        if kid not in konventionen:
            raise SystemExit(f"Pruefregel {regel['id']} verweist auf unbekannte Konvention {kid}")
        eintrag = dict(regel)
        eintrag["konventionstext"] = konventionen[kid]["text"]
        eintrag["verweis"] = konventionen[kid]["verweis"]
        eintrag["quelle"] = [f"leitfaden:{kid}", "knowledge/leitfaden/konventionen.json"]
        regeln.append(eintrag)

    for eintrag in NICHT_PRUEFBAR:
        if eintrag["konvention"] not in konventionen:
            raise SystemExit(f"unbekannte Konvention in nichtPruefbar: {eintrag['konvention']}")

    daten = {
        "schemaVersion": "1.0",
        "zweck": (
            "Regelgrundlage fuer BMC (BPMN-Werkzeug der EAM-Toolfamilie): Abbildung "
            "BPMN-Element -> ADMBw-Stereotyp der MDG 2026.05, L4-Modellierungskonventionen "
            "des Leitfadens FFfmLV 2.0 und die daraus pruefbaren Regeln."
        ),
        "stand": "2026-11-04",
        "quellen": {
            "stereotype": {
                "datei": "apps/admbw-extractor/ADMBw-Stereotypes.json",
                "release": lade_json(STEREOYPE_DATEI).get("release", ""),
                "sha256": sha256(STEREOYPE_DATEI),
            },
            "mdg": {
                "datei": "packages/rules/NAFv4-ADMBw-MDG-2026.05.xml",
                "sha256": sha256(MDG_DATEI),
            },
            "konventionen": {
                "datei": "knowledge/leitfaden/konventionen.json",
                "sha256": sha256(KONVENTIONEN_DATEI),
            },
            "regelwerk": {
                "datei": "knowledge/regelwerk.json",
                "sha256": sha256(REGELWERK_DATEI),
            },
        },
        "l4Sicht": lese_l4_sicht(),
        "stereotype": stereotype,
        "metaconstraints": metaconstraints,
        "elementtypen": elementtypen,
        "konventionen": {k: konventionen[k] for k in sorted(konventionen)},
        "pruefregeln": regeln,
        "nichtPruefbar": NICHT_PRUEFBAR,
        "transformationsRegeln": [
            {
                "regel": "BPMN-L4-05",
                "aktion": "Stereotyp OperationalActivityAction an jeder Aufgabe setzen",
            },
            {"regel": "BPMN-L4-06", "aktion": "Fehlenden Aktionsnamen als Platzhalter setzen und protokollieren"},
            {"regel": "BPMN-L4-04", "aktion": "Knoten ohne Lane der Standard-Lane des Pools zuordnen"},
            {"regel": "BPMN-L4-08", "aktion": "Fehlendes Gateway fuer Verzweigung/Zusammenfuehrung einfuegen"},
            {"regel": "BPMN-L4-09", "aktion": "Zusammenfuehrungs-Gateway auf den Typ der Verzweigung setzen"},
            {"regel": "BPMN-L4-10", "aktion": "Fehlendes Startereignis oder Endereignis ergaenzen"},
            {"regel": "BPMN-L4-11", "aktion": "Fehlendes Conveyed Item als InformationElement (Platzhalter) ergaenzen"},
            {"regel": "BPMN-L4-12", "aktion": "Zwischenereignis vor bedingten Fluss setzen"},
            {"regel": "BPMN-L4-13", "aktion": "Nachrichtenfluss mit Platzhalter-Informationselement versehen"},
        ],
    }
    return daten


def schreibe(daten: dict[str, Any], ziel: Path) -> None:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ziel.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="nur vergleichen, nichts schreiben")
    args = parser.parse_args(argv)

    daten = baue()
    if args.check:
        if not ZIEL.is_file():
            print(f"fehlt: {ZIEL}", file=sys.stderr)
            return 1
        vorhanden = json.loads(ZIEL.read_text(encoding="utf-8"))
        if vorhanden != daten:
            print("Abweichung: knowledge/bpmn/prozess-regeln.json ist nicht aktuell", file=sys.stderr)
            return 1
        print("aktuell")
        return 0

    schreibe(daten, ZIEL)
    print(f"geschrieben: {ZIEL.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
