"""Datenmodell fuer BPMN 2.0 -- ausgerichtet auf die ADMBw-Sicht L4.

Das Modell ist eine verlustfreie Zwischenform: Was in der XML stand, steht
danach im Modell und kommt beim Schreiben wieder heraus. Deshalb sind alle
Kennungen Zeichenketten, die unveraendert bleiben, und alle Geometrien werden
mitgefuehrt. Neue Elemente bekommen Kennungen aus einem Zaehler, damit zwei
Laeufe auf demselben Ausgangsmodell dieselben Kennungen erzeugen.

Fachliche Leitlinien (siehe ``knowledge/bpmn/prozess-regeln.json``):

* Ein Prozess ist die Abfolge von Aktionen, Ereignissen und Gateways.
* Ein Pool (``Teilnehmer``) traegt genau einen Prozess.
* Lanes gliedern den Pool nach Aufgabentraegern.
* Ein "Conveyed Item" ist ein Datenobjekt, das ueber eine Assoziation an einem
  Sequenzfluss haengt (L4-MK17) -- so verlangt es der Leitfaden, und so
  stellt es auch ein BPMN-Werkzeug dar.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Iterable, Iterator

# --------------------------------------------------------------------------
# Elementarten
# --------------------------------------------------------------------------

EREIGNIS_ARTEN = (
    "start_event",
    "end_event",
    "intermediate_catch_event",
    "intermediate_throw_event",
)

AUFGABEN_ARTEN = (
    "task",
    "service_task",
    "user_task",
    "send_task",
    "receive_task",
    "script_task",
    "manual_task",
    "business_rule_task",
)

GATEWAY_ARTEN = (
    "exclusive_gateway",
    "parallel_gateway",
    "inclusive_gateway",
    "event_based_gateway",
    "complex_gateway",
)

KNOTEN_ARTEN = EREIGNIS_ARTEN + AUFGABEN_ARTEN + GATEWAY_ARTEN

#: BPMN-Elementname (XML) je interner Art.
XML_NAME = {
    "start_event": "startEvent",
    "end_event": "endEvent",
    "intermediate_catch_event": "intermediateCatchEvent",
    "intermediate_throw_event": "intermediateThrowEvent",
    "task": "task",
    "service_task": "serviceTask",
    "user_task": "userTask",
    "send_task": "sendTask",
    "receive_task": "receiveTask",
    "script_task": "scriptTask",
    "manual_task": "manualTask",
    "business_rule_task": "businessRuleTask",
    "exclusive_gateway": "exclusiveGateway",
    "parallel_gateway": "parallelGateway",
    "inclusive_gateway": "inclusiveGateway",
    "event_based_gateway": "eventBasedGateway",
    "complex_gateway": "complexGateway",
    "sequence_flow": "sequenceFlow",
    "message_flow": "messageFlow",
    "association": "association",
    "data_object_reference": "dataObjectReference",
    "data_object": "dataObject",
    "text_annotation": "textAnnotation",
    "group": "group",
}

#: Umkehrung: XML-Name -> interne Art.
ART_VON_XML = {v: k for k, v in XML_NAME.items()}

#: Ereignisdefinitionen, die ein Ereignis tragen kann (BPMN-Standard).
EREIGNIS_DEFINITIONEN = (
    "message",
    "timer",
    "signal",
    "conditional",
    "error",
    "escalation",
    "compensate",
    "link",
    "terminate",
    "cancel",
)

#: Richtung eines Ereignisses in der ADMBw-Lesart.
EREIGNIS_ROLLEN = ("trigger", "ergebnis", "bedingung")


def leerer_text(wert: object) -> str:
    """Text ohne umschliessende Leerzeichen; ``None`` wird zur leeren Zeichenkette."""
    return "" if wert is None else str(wert).strip()


# --------------------------------------------------------------------------
# Geometrie
# --------------------------------------------------------------------------


@dataclass
class Begrenzung:
    """Rechteck eines Elements im Diagramm (DC:Bounds)."""

    x: float = 0.0
    y: float = 0.0
    breite: float = 100.0
    hoehe: float = 60.0

    def als_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "breite": self.breite, "hoehe": self.hoehe}

    @property
    def rechts(self) -> float:
        return self.x + self.breite

    @property
    def unten(self) -> float:
        return self.y + self.hoehe

    @property
    def mitte_x(self) -> float:
        return self.x + self.breite / 2.0

    @property
    def mitte_y(self) -> float:
        return self.y + self.hoehe / 2.0

    def verschiebe(self, dx: float, dy: float) -> "Begrenzung":
        return Begrenzung(self.x + dx, self.y + dy, self.breite, self.hoehe)


@dataclass
class Punkt:
    """Stuetzpunkt eines Kantenzugs (DI:waypoint)."""

    x: float
    y: float

    def als_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


# --------------------------------------------------------------------------
# Elemente
# --------------------------------------------------------------------------


@dataclass
class Knoten:
    """Ein FlowNode: Ereignis, Aufgabe oder Gateway."""

    id: str
    art: str
    name: str = ""
    dokumentation: str = ""
    begrenzung: Begrenzung | None = None
    #: ADMBw-Stereotyp (nur gesetzt, wenn er in der MDG-Liste steht).
    stereotype: str = ""
    #: Ereignisdefinition (nur bei Ereignissen), z. B. ``message``.
    ereignis_definition: str = ""
    #: Fachliche Rolle des Ereignisses: Trigger, Ergebnis oder Bedingung.
    ereignis_rolle: str = ""
    #: Freie Attribute aus dem Quelltext (bleiben beim Roundtrip erhalten).
    attribute: dict[str, str] = field(default_factory=dict)
    #: Reihenfolge im Prozessdokument.
    position: int = 0

    def __post_init__(self) -> None:
        if self.art not in KNOTEN_ARTEN:
            raise ValueError(f"unbekannte Knotenart: {self.art!r}")
        self.name = leerer_text(self.name)
        self.dokumentation = leerer_text(self.dokumentation)

    @property
    def ist_ereignis(self) -> bool:
        return self.art in EREIGNIS_ARTEN

    @property
    def ist_aufgabe(self) -> bool:
        return self.art in AUFGABEN_ARTEN

    @property
    def ist_gateway(self) -> bool:
        return self.art in GATEWAY_ARTEN

    @property
    def ist_start(self) -> bool:
        return self.art == "start_event"

    @property
    def ist_ende(self) -> bool:
        return self.art == "end_event"

    def kopie(self) -> "Knoten":
        return Knoten(
            id=self.id,
            art=self.art,
            name=self.name,
            dokumentation=self.dokumentation,
            begrenzung=None
            if self.begrenzung is None
            else Begrenzung(**self.begrenzung.als_dict()),
            stereotype=self.stereotype,
            ereignis_definition=self.ereignis_definition,
            ereignis_rolle=self.ereignis_rolle,
            attribute=dict(self.attribute),
            position=self.position,
        )


@dataclass
class Fluss:
    """Kontrollfluss, Nachrichtenfluss oder Assoziation."""

    id: str
    art: str
    quelle: str
    ziel: str
    name: str = ""
    bedingung: str = ""
    stereotype: str = ""
    wegpunkte: list[Punkt] = field(default_factory=list)
    attribute: dict[str, str] = field(default_factory=dict)
    position: int = 0

    def __post_init__(self) -> None:
        if self.art not in ("sequence_flow", "message_flow", "association"):
            raise ValueError(f"unbekannte Flussart: {self.art!r}")
        self.name = leerer_text(self.name)

    def kopie(self) -> "Fluss":
        return Fluss(
            id=self.id,
            art=self.art,
            quelle=self.quelle,
            ziel=self.ziel,
            name=self.name,
            bedingung=self.bedingung,
            stereotype=self.stereotype,
            wegpunkte=[Punkt(p.x, p.y) for p in self.wegpunkte],
            attribute=dict(self.attribute),
            position=self.position,
        )


@dataclass
class Datenobjekt:
    """Datenobjekt, Datenreferenz oder Textanmerkung (Artefakt)."""

    id: str
    art: str = "data_object_reference"
    name: str = ""
    dokumentation: str = ""
    begrenzung: Begrenzung | None = None
    #: Kennung des Datenobjekts, auf das eine Referenz zeigt.
    data_object_ref: str = ""
    attribute: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.art not in ("data_object_reference", "data_object", "text_annotation"):
            raise ValueError(f"unbekannte Datenart: {self.art!r}")
        self.name = leerer_text(self.name)


@dataclass
class Lane:
    """Eine Spur innerhalb eines Pools."""

    id: str
    name: str = ""
    knoten: list[str] = field(default_factory=list)
    lanes: list["Lane"] = field(default_factory=list)
    begrenzung: Begrenzung | None = None
    #: Aufgabentraeger (ADMBw: OperationalPerformer), auf den die Lane zeigt.
    performer: str = ""
    attribute: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = leerer_text(self.name)

    def alle_lanes(self) -> Iterator["Lane"]:
        yield self
        for kind in self.lanes:
            yield from kind.alle_lanes()

    def knoten_tief(self) -> list[str]:
        ids = list(self.knoten)
        for kind in self.lanes:
            ids.extend(kind.knoten_tief())
        return ids


@dataclass
class LaneSet:
    id: str
    name: str = ""
    lanes: list[Lane] = field(default_factory=list)

    def alle_knoten(self) -> list[str]:
        ids: list[str] = []
        for lane in self.lanes:
            ids.extend(lane.knoten_tief())
        return ids


@dataclass
class Prozess:
    """Ein BPMN-Prozess (ein Pool kann genau einen tragen)."""

    id: str
    name: str = ""
    ausfuehrbar: bool = False
    dokumentation: str = ""
    lane_sets: list[LaneSet] = field(default_factory=list)
    #: Geordnete Kennungen der Flussknoten und Sequenzfluesse.
    elemente: list[str] = field(default_factory=list)
    attribute: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = leerer_text(self.name)

    def knoten_ids(self, modell: "Modell") -> list[str]:
        return [e for e in self.elemente if e in modell.knoten]

    def fluss_ids(self, modell: "Modell") -> list[str]:
        return [e for e in self.elemente if e in modell.fluesse]

    def lane_von(self, knoten_id: str) -> Lane | None:
        for lane_set in self.lane_sets:
            for lane in lane_set.lanes:
                for kandidat in lane.alle_lanes():
                    if knoten_id in kandidat.knoten:
                        return kandidat
        return None

    def alle_lanes(self) -> list[Lane]:
        ergebnis: list[Lane] = []
        for lane_set in self.lane_sets:
            for lane in lane_set.lanes:
                ergebnis.extend(lane.alle_lanes())
        return ergebnis


@dataclass
class Teilnehmer:
    """Ein Pool im Kollaborationsdiagramm."""

    id: str
    name: str = ""
    prozess_ref: str = ""
    begrenzung: Begrenzung | None = None
    #: ADMBw-Typisierung des Pools (Anwendungsfall): OperationalArchitecture.
    typ: str = ""
    attribute: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = leerer_text(self.name)


@dataclass
class Kollaboration:
    """Die BPMN-Kollaboration: Pools und die Nachrichtenfluesse dazwischen."""

    id: str
    name: str = ""
    teilnehmer: list[Teilnehmer] = field(default_factory=list)
    botschaftsfluesse: list[str] = field(default_factory=list)
    attribute: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = leerer_text(self.name)


@dataclass
class Form:
    """BPMNShape: Geometrie eines Elements im Diagramm."""

    element_ref: str
    begrenzung: Begrenzung
    ist_ausgeklappt: bool = True
    ist_marker_visible: bool = True
    label: Begrenzung | None = None


@dataclass
class Kante:
    """BPMNEdge: Wegpunkte eines Flusses im Diagramm."""

    element_ref: str
    wegpunkte: list[Punkt] = field(default_factory=list)
    label: Begrenzung | None = None


@dataclass
class Diagramm:
    """Ein BPMNDiagramm mit einer Ebene."""

    id: str
    name: str = ""
    ebenen_element: str = ""
    formen: list[Form] = field(default_factory=list)
    kanten: list[Kante] = field(default_factory=list)

    def form(self, element_ref: str) -> Form | None:
        for eintrag in self.formen:
            if eintrag.element_ref == element_ref:
                return eintrag
        return None

    def kante(self, element_ref: str) -> Kante | None:
        for eintrag in self.kanten:
            if eintrag.element_ref == element_ref:
                return eintrag
        return None


# --------------------------------------------------------------------------
# Wurzelmodell
# --------------------------------------------------------------------------


@dataclass
class Modell:
    """Das vollstaendige BPMN-Dokument."""

    id: str = "Definitions_1"
    name: str = ""
    ziel_namespace: str = "https://eam-platform.local/bpmn"
    prozesse: dict[str, Prozess] = field(default_factory=dict)
    kollaboration: Kollaboration | None = None
    knoten: dict[str, Knoten] = field(default_factory=dict)
    fluesse: dict[str, Fluss] = field(default_factory=dict)
    daten: dict[str, Datenobjekt] = field(default_factory=dict)
    diagramme: list[Diagramm] = field(default_factory=list)
    #: Weitere Wurzelelemente, die unveraendert durchgereicht werden.
    weitere_wurzelelemente: list[str] = field(default_factory=list)

    _zaehler: itertools.count = field(default_factory=lambda: itertools.count(1), repr=False)

    # -- Kennungen ------------------------------------------------------
    def neue_id(self, praefix: str) -> str:
        """Deterministische Kennung: ``praefix_1``, ``praefix_2``, ...

        Der Zaehler laeuft modellweit; ein zweiter Lauf auf demselben Modell
        erzeugt dieselbe Folge, weil er denselben Ausgangsstand sieht.
        """
        while True:
            kandidat = f"{praefix}_{next(self._zaehler)}"
            if (
                kandidat not in self.knoten
                and kandidat not in self.fluesse
                and kandidat not in self.daten
                and kandidat not in self.prozesse
            ):
                return kandidat

    def zaehler_setzen(self, wert: int) -> None:
        """Zaehler hinter eine vorhandene Kennung setzen (nach dem Einlesen)."""
        self._zaehler = itertools.count(max(1, wert))

    # -- Aufbau ---------------------------------------------------------
    def prozess(self, prozess_id: str) -> Prozess:
        if prozess_id not in self.prozesse:
            raise KeyError(f"Prozess unbekannt: {prozess_id}")
        return self.prozesse[prozess_id]

    def neuer_prozess(self, name: str, prozess_id: str | None = None) -> Prozess:
        pid = prozess_id or self.neue_id("Process")
        prozess = Prozess(id=pid, name=name)
        self.prozesse[pid] = prozess
        return prozess

    def neuer_knoten(
        self,
        art: str,
        name: str = "",
        prozess: Prozess | None = None,
        knoten_id: str | None = None,
    ) -> Knoten:
        kid = knoten_id or self.neue_id(_praefix_fuer(art))
        knoten = Knoten(id=kid, art=art, name=name)
        self.knoten[kid] = knoten
        if prozess is not None:
            prozess.elemente.append(kid)
        return knoten

    def neuer_fluss(
        self,
        art: str,
        quelle: str,
        ziel: str,
        prozess: Prozess | None = None,
        fluss_id: str | None = None,
        name: str = "",
    ) -> Fluss:
        fid = fluss_id or self.neue_id(_praefix_fuer(art))
        fluss = Fluss(id=fid, art=art, quelle=quelle, ziel=ziel, name=name)
        self.fluesse[fid] = fluss
        if prozess is not None and art in ("sequence_flow", "association"):
            prozess.elemente.append(fid)
        if art == "message_flow" and self.kollaboration is not None:
            self.kollaboration.botschaftsfluesse.append(fid)
        return fluss

    def neues_datenobjekt(
        self, name: str, art: str = "data_object_reference", prozess: Prozess | None = None
    ) -> Datenobjekt:
        did = self.neue_id(_praefix_fuer(art))
        daten = Datenobjekt(id=did, art=art, name=name)
        self.daten[did] = daten
        if prozess is not None:
            prozess.elemente.append(did)
        return daten

    # -- Abfragen -------------------------------------------------------
    def alle_teilnehmer(self) -> list[Teilnehmer]:
        return list(self.kollaboration.teilnehmer) if self.kollaboration else []

    def teilnehmer_von_prozess(self, prozess_id: str) -> Teilnehmer | None:
        for teilnehmer in self.alle_teilnehmer():
            if teilnehmer.prozess_ref == prozess_id:
                return teilnehmer
        return None

    def prozess_von_element(self, element_id: str) -> Prozess | None:
        for prozess in self.prozesse.values():
            if element_id in prozess.elemente:
                return prozess
        return None

    def eingehend(self, knoten_id: str) -> list[Fluss]:
        return [
            f
            for f in self.fluesse.values()
            if f.art == "sequence_flow" and f.ziel == knoten_id
        ]

    def ausgehend(self, knoten_id: str) -> list[Fluss]:
        return [
            f
            for f in self.fluesse.values()
            if f.art == "sequence_flow" and f.quelle == knoten_id
        ]

    def nachfolger(self, knoten_id: str) -> list[str]:
        return [f.ziel for f in self.ausgehend(knoten_id)]

    def vorgaenger(self, knoten_id: str) -> list[str]:
        return [f.quelle for f in self.eingehend(knoten_id)]

    def alle_knoten(self) -> list[Knoten]:
        """Alle Knoten in Dokumentreihenfolge (Prozess fuer Prozess)."""
        ergebnis: list[Knoten] = []
        gesehen: set[str] = set()
        for prozess in self.prozesse.values():
            for element_id in prozess.elemente:
                knoten = self.knoten.get(element_id)
                if knoten is not None and knoten.id not in gesehen:
                    ergebnis.append(knoten)
                    gesehen.add(knoten.id)
        for knoten in self.knoten.values():  # Nachzuegler ohne Prozessbezug
            if knoten.id not in gesehen:
                ergebnis.append(knoten)
        return ergebnis

    def aktionen(self, prozess: Prozess | None = None) -> list[Knoten]:
        knoten = self.alle_knoten() if prozess is None else [
            self.knoten[e] for e in prozess.elemente if e in self.knoten
        ]
        return [k for k in knoten if k.ist_aufgabe]

    # -- "Conveyed Items" (L4-MK17) -------------------------------------
    def conveyed_items(self, fluss_id: str) -> list[Datenobjekt]:
        """Datenobjekte, die ueber eine Assoziation an diesem Fluss haengen.

        Zwei Formen gelten: die eigene (Assoziation haengt am Fluss, L4-MK17)
        und die fremde (Assoziation haengt an der Aktion, wie bpmn.io, ARIS und
        EA es schreiben). Beim Lesen fremder Dateien bleibt der Prueflauf damit
        begruendbar, statt "fehlendes Conveyed Item" zu melden, obwohl Daten
        sichtbar am Schritt haengen.
        """
        ergebnis: list[Datenobjekt] = []
        for fluss in self.fluesse.values():
            if fluss.art != "association":
                continue
            if fluss.ziel == fluss_id and fluss.quelle in self.daten:
                ergebnis.append(self.daten[fluss.quelle])
            elif fluss.quelle == fluss_id and fluss.ziel in self.daten:
                ergebnis.append(self.daten[fluss.ziel])
        if ergebnis:
            return ergebnis
        fluss = self.fluesse.get(fluss_id)
        if fluss is None or fluss.art == "association":
            return ergebnis
        gesammelt: list[Datenobjekt] = []
        for ende in (fluss.quelle, fluss.ziel):
            for daten in self._daten_an_knoten(ende):
                if daten not in gesammelt:
                    gesammelt.append(daten)
        return gesammelt

    def _daten_an_knoten(self, knoten_id: str) -> list[Datenobjekt]:
        """Datenobjekte, die per Assoziation direkt an einer Aktion haengen."""
        ergebnis: list[Datenobjekt] = []
        for fluss in self.fluesse.values():
            if fluss.art != "association":
                continue
            if fluss.ziel == knoten_id and fluss.quelle in self.daten:
                ergebnis.append(self.daten[fluss.quelle])
            elif fluss.quelle == knoten_id and fluss.ziel in self.daten:
                ergebnis.append(self.daten[fluss.ziel])
        return ergebnis

    def assoziation_enden(self, assoziation: Fluss) -> tuple[str, str]:
        """Datenende und BPMN-Element einer Assoziation.

        BPMN 2.0 erlaubt eine Assoziation an ein Basiselement; bpmn-js,
        ARIS und EA akzeptieren sie nicht an einem Sequenz- oder
        Nachrichtenfluss und verwerfen sie beim Import. Deshalb wird der Fluss
        beim Schreiben auf den Knoten abgebildet, der ihn ausloest; die
        Flussbindung steht als ``admbw:conveyed`` daneben und geht beim
        rueckwaertigen Lesen nicht verloren.
        """
        if assoziation.quelle in self.daten:
            daten, anderer = assoziation.quelle, assoziation.ziel
        elif assoziation.ziel in self.daten:
            daten, anderer = assoziation.ziel, assoziation.quelle
        else:
            return assoziation.quelle, assoziation.ziel
        fluss = self.fluesse.get(anderer)
        if fluss is not None and fluss.art != "association":
            for kandidat in (fluss.quelle, fluss.ziel):
                if kandidat in self.knoten:
                    return daten, kandidat
        return daten, anderer

    def assoziiere(self, daten_id: str, fluss_id: str, prozess: Prozess | None = None) -> Fluss:
        """Datenobjekt als Conveyed Item an einen Fluss haengen."""
        return self.neuer_fluss("association", daten_id, fluss_id, prozess=prozess)

    # -- Pruefungen der Struktur ---------------------------------------
    def sortiert(self) -> "Modell":
        """Elemente nach Dokumentposition ordnen; gibt das Modell zurueck."""
        for prozess in self.prozesse.values():
            prozess.elemente.sort(
                key=lambda e: (
                    self.knoten[e].position
                    if e in self.knoten
                    else self.fluesse[e].position
                    if e in self.fluesse
                    else 10**9
                )
            )
        return self


def _praefix_fuer(art: str) -> str:
    return {
        "start_event": "StartEvent",
        "end_event": "EndEvent",
        "intermediate_catch_event": "IntermediateCatchEvent",
        "intermediate_throw_event": "IntermediateThrowEvent",
        "task": "Task",
        "service_task": "ServiceTask",
        "user_task": "UserTask",
        "send_task": "SendTask",
        "receive_task": "ReceiveTask",
        "script_task": "ScriptTask",
        "manual_task": "ManualTask",
        "business_rule_task": "BusinessRuleTask",
        "exclusive_gateway": "ExclusiveGateway",
        "parallel_gateway": "ParallelGateway",
        "inclusive_gateway": "InclusiveGateway",
        "event_based_gateway": "EventBasedGateway",
        "complex_gateway": "ComplexGateway",
        "sequence_flow": "SequenceFlow",
        "message_flow": "MessageFlow",
        "association": "Association",
        "data_object_reference": "DataObjectReference",
        "data_object": "DataObject",
        "text_annotation": "TextAnnotation",
    }.get(art, "Element")


def kanten_als_text(fluss: Fluss) -> str:
    """Lesbare Darstellung eines Flusses fuer Protokolle."""
    return f"{fluss.quelle} -> {fluss.ziel}"


def iteriere_knoten(knoten: Iterable[Knoten]) -> Iterator[Knoten]:
    return iter(knoten)
