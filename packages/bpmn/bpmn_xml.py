"""BPMN 2.0 XML lesen und schreiben -- mit Diagrammteil.

Geschrieben wird von Hand statt ueber einen Serialisierer, weil die
Reihenfolge der Kindelemente in BPMN 2.0 vom Schema vorgeschrieben ist
(``laneSet`` vor ``flowElement``, ``incoming``/``outgoing`` vor
``eventDefinition``, ``BPMNShape`` vor ``BPMNEdge``). Ein ``dict`` haelt diese
Reihenfolge nicht verlaesslich; hier steht sie im Code und ist damit pruefbar.

Gelesen wird namespace-tolerant: Standard-Namespace oder Praefix, beides
ergibt dieselben Kennungen. Unbekannte Attribute bleiben erhalten, damit ein
Roundtrip nichts verliert.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Iterable, Iterator
from xml.sax.saxutils import escape, quoteattr

from . import modell as m

NS_BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
NS_BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
NS_DC = "http://www.omg.org/spec/DD/20100524/DC"
NS_DI = "http://www.omg.org/spec/DD/20100524/DI"
NS_ADMBW = "https://eam-platform.local/bpmn/admbw"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

#: Attribute, die das Modell selbst fuehrt und die deshalb nicht in die
#: Restmenge wandern.
BEKANNTE_ATTRIBUTE = {
    "id",
    "name",
    "isExecutable",
    "isExpanded",
    "isMarkerVisible",
    "sourceRef",
    "targetRef",
    "default",
    "gatewayDirection",
    "processRef",
    "bpmnElement",
    "isHorizontal",
    "isForCompensation",
    "triggeredByEvent",
    "instantiate",
}


def _lokal(tag: str) -> str:
    """Tag ohne Namespace."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _attr(element: ET.Element, name: str, standard: str = "") -> str:
    """Attribut lesen, egal ob mit oder ohne Namespace."""
    for schluessel, wert in element.attrib.items():
        if _lokal(schluessel) == name:
            if standard and _ns(schluessel) not in ("", standard):
                continue
            return wert
    return ""


def _rest_attribute(element: ET.Element, bekannt: Iterable[str] = ()) -> dict[str, str]:
    ergebnis: dict[str, str] = {}
    for schluessel, wert in element.attrib.items():
        lokal = _lokal(schluessel)
        if lokal in BEKANNTE_ATTRIBUTE or lokal in bekannt:
            continue
        ergebnis[lokal] = wert
    return ergebnis


def _nummer(wert: str) -> float:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return 0.0


def _zahl(wert: float) -> str:
    """Feste Zahlenschreibweise -- kein ``1.0``, wo ``1`` genuegt."""
    if abs(wert - round(wert)) < 1e-9:
        return str(int(round(wert)))
    return f"{wert:.3f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------
# Lesen
# --------------------------------------------------------------------------


def lies(pfad: str) -> m.Modell:
    """BPMN-Datei lesen."""
    return lies_text(open(pfad, encoding="utf-8").read())


def lies_text(text: str) -> m.Modell:
    """BPMN-XML aus einer Zeichenkette lesen."""
    wurzel = ET.fromstring(text)
    if _lokal(wurzel.tag) != "definitions":
        raise ValueError(f"kein BPMN-Dokument: Wurzel {_lokal(wurzel.tag)!r}")
    modell = m.Modell(
        id=_attr(wurzel, "id", NS_BPMN) or "Definitions_1",
        name=_attr(wurzel, "name", NS_BPMN),
        ziel_namespace=_attr(wurzel, "targetNamespace", NS_BPMN)
        or "https://eam-platform.local/bpmn",
    )

    hoechste = 0
    for kind in wurzel:
        name = _lokal(kind.tag)
        if name == "process":
            prozess = _lies_prozess(kind, modell)
            modell.prozesse[prozess.id] = prozess
        elif name == "collaboration":
            modell.kollaboration = _lies_kollaboration(kind, modell)
        elif name == "BPMNDiagram":
            modell.diagramme.append(_lies_diagramm(kind))
        elif name in ("message", "signal", "error", "escalation", "dataStore", "category"):
            # Wurzelelemente, die das Modell nicht auswertet, aber behaelt.
            modell.weitere_wurzelelemente.append(name)
        for element in kind.iter():
            if "id" in element.attrib:
                hoechste = max(hoechste, _zaehlerstand(element.attrib["id"]))
    _wende_diagramm_an(modell)
    _loese_conveyed_auf(modell)
    modell.zaehler_setzen(hoechste + 1)
    return modell


def _wende_diagramm_an(modell: m.Modell) -> None:
    """Uebertraegt die DI-Geometrie auf Knoten, Daten, Lanes und Fluesse.

    Ohne diesen Schritt kennt das Modell nach dem Lesen keine Positionen; ein
    erneutes Schreiben wuerde das Layout verlieren und fremde Dateien (bpmn.io,
    ARIS, EA) saehen nach dem Roundtrip anders aus.
    """
    lanes: dict[str, m.Lane] = {}

    def _sammle(lane_liste: list[m.Lane]) -> None:
        for lane in lane_liste:
            lanes[lane.id] = lane
            _sammle(lane.lanes)

    for prozess in modell.prozesse.values():
        for lane_set in prozess.lane_sets:
            _sammle(lane_set.lanes)
    for diagramm in modell.diagramme:
        for form in diagramm.formen:
            ziel = (
                modell.knoten.get(form.element_ref)
                or modell.daten.get(form.element_ref)
                or lanes.get(form.element_ref)
            )
            if ziel is not None and form.begrenzung is not None:
                ziel.begrenzung = form.begrenzung
            if ziel is not None and form.label is not None and hasattr(ziel, "label"):
                ziel.label = form.label
        for kante in diagramm.kanten:
            fluss = modell.fluesse.get(kante.element_ref)
            if fluss is not None and kante.wegpunkte:
                fluss.wegpunkte = list(kante.wegpunkte)
            if fluss is not None and kante.label is not None:
                fluss.label = kante.label


def _loese_conveyed_auf(modell: m.Modell) -> None:
    """Bindet Assoziationen wieder an ihren Fluss (Gegenstueck zum Schreiben)."""
    for fluss in modell.fluesse.values():
        ziel = fluss.attribute.pop("conveyed", "")
        if fluss.art != "association" or not ziel:
            continue
        if fluss.quelle in modell.daten:
            fluss.ziel = ziel
        elif fluss.ziel in modell.daten:
            fluss.quelle = ziel


def _zaehlerstand(kennung: str) -> int:
    treffer = re.search(r"_(\d+)$", kennung or "")
    return int(treffer.group(1)) if treffer else 0


def _lies_prozess(element: ET.Element, modell: m.Modell) -> m.Prozess:
    prozess = m.Prozess(
        id=_attr(element, "id", NS_BPMN),
        name=_attr(element, "name", NS_BPMN),
        ausfuehrbar=_attr(element, "isExecutable", NS_BPMN).lower() == "true",
        dokumentation=_text_von(element, "documentation"),
        attribute=_rest_attribute(element),
    )
    position = 0
    for kind in element:
        name = _lokal(kind.tag)
        if name == "laneSet":
            prozess.lane_sets.append(_lies_laneset(kind))
        elif name in m.ART_VON_XML and m.ART_VON_XML[name] in m.KNOTEN_ARTEN:
            knoten = _lies_knoten(kind, m.ART_VON_XML[name])
            knoten.position = position
            position += 1
            modell.knoten[knoten.id] = knoten
            prozess.elemente.append(knoten.id)
        elif name == "sequenceFlow":
            fluss = _lies_fluss(kind, "sequence_flow")
            fluss.position = position
            position += 1
            modell.fluesse[fluss.id] = fluss
            prozess.elemente.append(fluss.id)
        elif name in ("dataObjectReference", "dataObject", "textAnnotation"):
            daten = _lies_daten(kind, m.ART_VON_XML[name])
            modell.daten[daten.id] = daten
            prozess.elemente.append(daten.id)
        elif name == "association":
            fluss = _lies_fluss(kind, "association")
            fluss.position = position
            position += 1
            modell.fluesse[fluss.id] = fluss
            prozess.elemente.append(fluss.id)
        elif name == "extensionElements":
            _lies_erweiterungen(kind, prozess)
    return prozess


def _lies_kollaboration(element: ET.Element, modell: m.Modell) -> m.Kollaboration:
    kollaboration = m.Kollaboration(
        id=_attr(element, "id", NS_BPMN),
        name=_attr(element, "name", NS_BPMN),
        attribute=_rest_attribute(element),
    )
    for kind in element:
        name = _lokal(kind.tag)
        if name == "participant":
            teilnehmer = m.Teilnehmer(
                id=_attr(kind, "id", NS_BPMN),
                name=_attr(kind, "name", NS_BPMN),
                prozess_ref=_attr(kind, "processRef", NS_BPMN),
                attribute=_rest_attribute(kind, {"processRef"}),
            )
            for eintrag in kind:
                if _lokal(eintrag.tag) != "extensionElements":
                    continue
                for detail in eintrag:
                    if _lokal(detail.tag) == "typ":
                        teilnehmer.typ = detail.attrib.get("ref", "")
            kollaboration.teilnehmer.append(teilnehmer)
        elif name == "messageFlow":
            fluss = _lies_fluss(kind, "message_flow")
            modell.fluesse[fluss.id] = fluss
            kollaboration.botschaftsfluesse.append(fluss.id)
        elif name == "association":
            fluss = _lies_fluss(kind, "association")
            modell.fluesse[fluss.id] = fluss
        elif name == "extensionElements":
            for eintrag in kind:
                if _lokal(eintrag.tag) == "stereotype":
                    kollaboration.attribute["stereotype"] = eintrag.attrib.get("name", "")
    return kollaboration


def _lies_knoten(element: ET.Element, art: str) -> m.Knoten:
    knoten = m.Knoten(
        id=_attr(element, "id", NS_BPMN),
        art=art,
        name=_attr(element, "name", NS_BPMN),
        dokumentation=_text_von(element, "documentation"),
        attribute=_rest_attribute(element),
    )
    for kind in element:
        name = _lokal(kind.tag)
        if name == "extensionElements":
            _lies_knoten_erweiterungen(kind, knoten)
        elif name == "eventDefinition":
            definition = _lokal(kind.tag)
            # Das Kind ist z. B. <bpmn:messageEventDefinition/>.
            for eintrag in kind:
                knoten.ereignis_definition = _lokal(eintrag.tag).replace(
                    "EventDefinition", ""
                ).lower()
                break
            else:
                knoten.ereignis_definition = definition.replace(
                    "EventDefinition", ""
                ).lower()
        elif name in ("messageEventDefinition", "timerEventDefinition", "signalEventDefinition",
                      "conditionalEventDefinition", "errorEventDefinition", "escalationEventDefinition",
                      "compensateEventDefinition", "linkEventDefinition", "terminateEventDefinition",
                      "cancelEventDefinition"):
            knoten.ereignis_definition = name.replace("EventDefinition", "").lower()
    return knoten


def _lies_knoten_erweiterungen(element: ET.Element, knoten: m.Knoten) -> None:
    for eintrag in element:
        name = _lokal(eintrag.tag)
        if name == "stereotype":
            knoten.stereotype = eintrag.attrib.get("name", "")
        elif name == "ereignis":
            knoten.ereignis_rolle = eintrag.attrib.get("rolle", "")
    if not knoten.ereignis_definition:
        definition = _attr(element, "ereignisDefinition", NS_ADMBW)
        if definition:
            knoten.ereignis_definition = definition


def _lies_erweiterungen(element: ET.Element, prozess: m.Prozess) -> None:
    for eintrag in element:
        if _lokal(eintrag.tag) == "stereotype":
            prozess.attribute["stereotype"] = eintrag.attrib.get("name", "")


def _lies_fluss(element: ET.Element, art: str) -> m.Fluss:
    fluss = m.Fluss(
        id=_attr(element, "id", NS_BPMN),
        art=art,
        quelle=_attr(element, "sourceRef", NS_BPMN),
        ziel=_attr(element, "targetRef", NS_BPMN),
        name=_attr(element, "name", NS_BPMN),
        attribute=_rest_attribute(element, {"sourceRef", "targetRef"}),
    )
    for kind in element:
        name = _lokal(kind.tag)
        if name == "conditionExpression":
            fluss.bedingung = (kind.text or "").strip()
        elif name == "extensionElements":
            for eintrag in kind:
                lokal = _lokal(eintrag.tag)
                if lokal == "stereotype":
                    fluss.stereotype = eintrag.attrib.get("name", "")
                elif lokal == "conveyed":
                    # Eigene Semantik: die Assoziation haengt fachlich am Fluss,
                    # im XML aber am Knoten. Der Verweis wird nach dem Einlesen
                    # aller Elemente aufgeloest (siehe lies_text).
                    fluss.attribute["conveyed"] = eintrag.attrib.get("fluss", "")
    return fluss


def _lies_daten(element: ET.Element, art: str) -> m.Datenobjekt:
    return m.Datenobjekt(
        id=_attr(element, "id", NS_BPMN),
        art=art,
        name=_attr(element, "name", NS_BPMN),
        dokumentation=_text_von(element, "documentation"),
        data_object_ref=_attr(element, "dataObjectRef", NS_BPMN),
        attribute=_rest_attribute(element, {"dataObjectRef"}),
    )


def _text_von(element: ET.Element, name: str) -> str:
    for kind in element:
        if _lokal(kind.tag) == name:
            return (kind.text or "").strip()
    return ""


def _lies_laneset(element: ET.Element) -> m.LaneSet:
    laneset = m.LaneSet(id=_attr(element, "id", NS_BPMN), name=_attr(element, "name", NS_BPMN))
    for kind in element:
        if _lokal(kind.tag) == "lane":
            laneset.lanes.append(_lies_lane(kind))
    return laneset


def _lies_lane(element: ET.Element) -> m.Lane:
    lane = m.Lane(
        id=_attr(element, "id", NS_BPMN),
        name=_attr(element, "name", NS_BPMN),
        attribute=_rest_attribute(element),
    )
    for kind in element:
        name = _lokal(kind.tag)
        if name == "flowNodeRef":
            if (kind.text or "").strip():
                lane.knoten.append(kind.text.strip())
        elif name == "childLaneSet":
            for eintrag in kind:
                if _lokal(eintrag.tag) == "lane":
                    lane.lanes.append(_lies_lane(eintrag))
        elif name == "extensionElements":
            for eintrag in kind:
                if _lokal(eintrag.tag) == "performer":
                    lane.performer = eintrag.attrib.get("ref", "")
    return lane


def _lies_diagramm(element: ET.Element) -> m.Diagramm:
    diagramm = m.Diagramm(
        id=_attr(element, "id", NS_BPMNDI),
        name=_attr(element, "name", NS_BPMNDI),
    )
    for kind in element:
        if _lokal(kind.tag) != "BPMNPlane":
            continue
        diagramm.ebenen_element = _attr(kind, "bpmnElement", NS_BPMNDI)
        for form in kind:
            name = _lokal(form.tag)
            if name == "BPMNShape":
                element_ref = _attr(form, "bpmnElement", NS_BPMNDI)
                begrenzung = m.Begrenzung()
                label = None
                for kind2 in form:
                    if _lokal(kind2.tag) == "Bounds":
                        begrenzung = m.Begrenzung(
                            _nummer(_attr(kind2, "x", NS_DC)),
                            _nummer(_attr(kind2, "y", NS_DC)),
                            _nummer(_attr(kind2, "width", NS_DC)),
                            _nummer(_attr(kind2, "height", NS_DC)),
                        )
                    elif _lokal(kind2.tag) == "BPMNLabel":
                        for kind3 in kind2:
                            if _lokal(kind3.tag) == "Bounds":
                                label = m.Begrenzung(
                                    _nummer(_attr(kind3, "x", NS_DC)),
                                    _nummer(_attr(kind3, "y", NS_DC)),
                                    _nummer(_attr(kind3, "width", NS_DC)),
                                    _nummer(_attr(kind3, "height", NS_DC)),
                                )
                diagramm.formen.append(
                    m.Form(
                        element_ref=element_ref,
                        begrenzung=begrenzung,
                        ist_ausgeklappt=_attr(form, "isExpanded", NS_BPMNDI).lower() != "false",
                        ist_marker_visible=_attr(form, "isMarkerVisible", NS_BPMNDI).lower()
                        != "false",
                        label=label,
                    )
                )
            elif name == "BPMNEdge":
                element_ref = _attr(form, "bpmnElement", NS_BPMNDI)
                punkte: list[m.Punkt] = []
                label = None
                for kind2 in form:
                    if _lokal(kind2.tag) == "waypoint":
                        punkte.append(
                            m.Punkt(
                                _nummer(_attr(kind2, "x", NS_DI)),
                                _nummer(_attr(kind2, "y", NS_DI)),
                            )
                        )
                    elif _lokal(kind2.tag) == "BPMNLabel":
                        for kind3 in kind2:
                            if _lokal(kind3.tag) == "Bounds":
                                label = m.Begrenzung(
                                    _nummer(_attr(kind3, "x", NS_DC)),
                                    _nummer(_attr(kind3, "y", NS_DC)),
                                    _nummer(_attr(kind3, "width", NS_DC)),
                                    _nummer(_attr(kind3, "height", NS_DC)),
                                )
                diagramm.kanten.append(m.Kante(element_ref, punkte, label))
    return diagramm


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------


class _Schreiber:
    """Kleiner XML-Schreiber mit fester Einrueckung und Attributreihenfolge."""

    def __init__(self) -> None:
        self.zeilen: list[str] = []
        self._tiefe = 0
        self._offen: list[int] = []

    def kopf(self) -> None:
        self.zeilen.append('<?xml version="1.0" encoding="UTF-8"?>')

    def auf(self, name: str, attribute: Iterable[tuple[str, str]] = ()) -> None:
        self.zeilen.append("  " * self._tiefe + f"<{name}{self._attrs(attribute)}>")
        self._offen.append(len(self.zeilen))
        self._tiefe += 1

    def zu(self, name: str) -> None:
        self._tiefe -= 1
        index = self._offen.pop()
        if len(self.zeilen) == index:
            # Seit dem Oeffnen kam nichts dazu: Element in einer Zeile schliessen.
            self.zeilen[-1] = self.zeilen[-1][:-1] + "/>"
            return
        self.zeilen.append("  " * self._tiefe + f"</{name}>")

    def leer(self, name: str, attribute: Iterable[tuple[str, str]] = ()) -> None:
        self.zeilen.append("  " * self._tiefe + f"<{name}{self._attrs(attribute)}/>")

    def text(self, name: str, inhalt: str, attribute: Iterable[tuple[str, str]] = ()) -> None:
        self.zeilen.append(
            "  " * self._tiefe
            + f"<{name}{self._attrs(attribute)}>{escape(inhalt)}</{name}>"
        )

    _tiefe = 0

    @staticmethod
    def _attrs(attribute: Iterable[tuple[str, str]]) -> str:
        teile = []
        for name, wert in attribute:
            if wert is None or wert == "":
                continue
            teile.append(f" {name}={quoteattr(str(wert))}")
        return "".join(teile)

    def ergebnis(self) -> str:
        return "\n".join(self.zeilen) + "\n"


def schreibe(modell: m.Modell, pfad: str) -> None:
    with open(pfad, "w", encoding="utf-8", newline="\n") as datei:
        datei.write(schreibe_text(modell))


def schreibe_text(modell: m.Modell) -> str:
    """Modell als BPMN-2.0-XML. Deterministisch: gleiche Eingabe, gleiche Bytes."""
    s = _Schreiber()
    s.kopf()
    s.auf(
        "definitions",
        [
            ("xmlns", NS_BPMN),
            ("xmlns:bpmndi", NS_BPMNDI),
            ("xmlns:dc", NS_DC),
            ("xmlns:di", NS_DI),
            ("xmlns:admbw", NS_ADMBW),
            ("xmlns:xsi", NS_XSI),
            ("id", modell.id),
            ("targetNamespace", modell.ziel_namespace),
            ("exporter", "eam-platform bpmn"),
            ("exporterVersion", "0.1"),
        ],
    )

    for prozess in modell.prozesse.values():
        _schreibe_prozess(s, modell, prozess)

    if modell.kollaboration is not None:
        _schreibe_kollaboration(s, modell, modell.kollaboration)

    if modell.diagramme:
        for nummer, diagramm in enumerate(modell.diagramme, start=1):
            _schreibe_diagramm(s, diagramm, nummer)
    else:
        for nummer, prozess in enumerate(modell.prozesse.values(), start=1):
            _schreibe_diagramm(s, _standard_diagramm(modell, prozess, nummer), nummer)

    s.zu("definitions")
    return s.ergebnis()


def _standard_diagramm(modell: m.Modell, prozess: m.Prozess, nummer: int) -> m.Diagramm:
    """Notdiagramm, wenn keines vorhanden ist -- nur vorhandene Geometrie."""
    diagramm = m.Diagramm(
        id=f"BPMNDiagram_{nummer}", name=prozess.name, ebenen_element=prozess.id
    )
    for lane in prozess.alle_lanes():
        if lane.begrenzung is not None:
            diagramm.formen.append(m.Form(lane.id, lane.begrenzung))
    for element_id in prozess.elemente:
        knoten = modell.knoten.get(element_id)
        if knoten is not None and knoten.begrenzung is not None:
            diagramm.formen.append(m.Form(knoten.id, knoten.begrenzung))
        daten = modell.daten.get(element_id)
        if daten is not None and daten.begrenzung is not None:
            diagramm.formen.append(m.Form(daten.id, daten.begrenzung))
    for fluss in modell.fluesse.values():
        if fluss.art == "sequence_flow" and fluss.wegpunkte:
            diagramm.kanten.append(m.Kante(fluss.id, list(fluss.wegpunkte)))
    return diagramm


def _schreibe_prozess(s: _Schreiber, modell: m.Modell, prozess: m.Prozess) -> None:
    s.auf(
        "process",
        [
            ("id", prozess.id),
            ("name", prozess.name),
            ("isExecutable", "true" if prozess.ausfuehrbar else "false"),
        ],
    )
    if prozess.dokumentation:
        s.text("documentation", prozess.dokumentation)
    if prozess.attribute.get("stereotype"):
        s.auf("extensionElements")
        s.leer("admbw:stereotype", [("name", prozess.attribute["stereotype"])])
        s.zu("extensionElements")

    for lane_set in prozess.lane_sets:
        _schreibe_laneset(s, lane_set)

    for element_id in prozess.elemente:
        knoten = modell.knoten.get(element_id)
        if knoten is not None:
            _schreibe_knoten(s, modell, knoten)
            continue
        fluss = modell.fluesse.get(element_id)
        if fluss is not None and fluss.art == "sequence_flow":
            _schreibe_sequenzfluss(s, fluss)

    # Flussknoten zuerst, dann Datenobjekte (beides flowElement), zuletzt
    # Artefakte (Assoziation, Textanmerkung) -- so verlangt es das Schema.
    for element_id in prozess.elemente:
        daten = modell.daten.get(element_id)
        if daten is not None and daten.art != "text_annotation":
            _schreibe_daten(s, daten)

    for element_id in prozess.elemente:
        daten = modell.daten.get(element_id)
        if daten is not None and daten.art == "text_annotation":
            _schreibe_daten(s, daten)
        fluss = modell.fluesse.get(element_id)
        if fluss is not None and fluss.art == "association":
            _schreibe_assoziation(s, modell, fluss)

    s.zu("process")


def _schreibe_laneset(s: _Schreiber, lane_set: m.LaneSet) -> None:
    s.auf("laneSet", [("id", lane_set.id), ("name", lane_set.name)])
    for lane in lane_set.lanes:
        _schreibe_lane(s, lane)
    s.zu("laneSet")


def _schreibe_lane(s: _Schreiber, lane: m.Lane) -> None:
    s.auf("lane", [("id", lane.id), ("name", lane.name)])
    # Reihenfolge nach tLane: tBaseElement (documentation, extensionElements),
    # dann partitionElement, flowNodeRef, childLaneSet. extensionElements
    # hinter flowNodeRef waere schema-widrig -- das XSD prueft das.
    if lane.performer:
        s.auf("extensionElements")
        s.leer("admbw:performer", [("ref", lane.performer)])
        s.zu("extensionElements")
    for kid in lane.knoten:
        s.text("flowNodeRef", kid)
    if lane.lanes:
        s.auf("childLaneSet", [("id", f"{lane.id}_childLaneSet")])
        for kind in lane.lanes:
            _schreibe_lane(s, kind)
        s.zu("childLaneSet")
    s.zu("lane")


def _schreibe_knoten(s: _Schreiber, modell: m.Modell, knoten: m.Knoten) -> None:
    name = m.XML_NAME[knoten.art]
    attribute = [("id", knoten.id), ("name", knoten.name)]
    for schluessel, wert in knoten.attribute.items():
        if schluessel in BEKANNTE_ATTRIBUTE:
            attribute.append((schluessel, wert))
    attribute.extend((k, v) for k, v in knoten.attribute.items() if k not in BEKANNTE_ATTRIBUTE)
    s.auf(name, attribute)
    if knoten.dokumentation:
        s.text("documentation", knoten.dokumentation)
    if knoten.stereotype or knoten.ereignis_rolle:
        s.auf("extensionElements")
        if knoten.stereotype:
            s.leer("admbw:stereotype", [("name", knoten.stereotype)])
        if knoten.ereignis_rolle:
            s.leer("admbw:ereignis", [("rolle", knoten.ereignis_rolle)])
        s.zu("extensionElements")
    for fluss in modell.eingehend(knoten.id):
        s.text("incoming", fluss.id)
    for fluss in modell.ausgehend(knoten.id):
        s.text("outgoing", fluss.id)
    if knoten.ereignis_definition:
        s.leer(
            f"{_bpmn_praefix(knoten.ereignis_definition)}EventDefinition",
            [("id", f"{knoten.id}_{knoten.ereignis_definition}Definition")],
        )
    s.zu(name)


def _bpmn_praefix(definition: str) -> str:
    return {
        "message": "message",
        "timer": "timer",
        "signal": "signal",
        "conditional": "conditional",
        "error": "error",
        "escalation": "escalation",
        "compensate": "compensate",
        "link": "link",
        "terminate": "terminate",
        "cancel": "cancel",
    }.get(definition, definition)


def _schreibe_sequenzfluss(s: _Schreiber, fluss: m.Fluss) -> None:
    attribute = [
        ("id", fluss.id),
        ("name", fluss.name),
        ("sourceRef", fluss.quelle),
        ("targetRef", fluss.ziel),
    ]
    attribute.extend((k, v) for k, v in fluss.attribute.items() if k not in BEKANNTE_ATTRIBUTE)
    s.auf("sequenceFlow", attribute)
    if fluss.stereotype:
        s.auf("extensionElements")
        s.leer("admbw:stereotype", [("name", fluss.stereotype)])
        s.zu("extensionElements")
    if fluss.bedingung:
        s.text("conditionExpression", fluss.bedingung, [("xsi:type", "tFormalExpression")])
    s.zu("sequenceFlow")


def _schreibe_assoziation(s: _Schreiber, modell: m.Modell, fluss: m.Fluss) -> None:
    daten_id, element_id = modell.assoziation_enden(fluss)
    s.auf(
        "association",
        [
            ("id", fluss.id),
            ("sourceRef", daten_id),
            ("targetRef", element_id),
            ("associationDirection", fluss.attribute.get("associationDirection", "None")),
        ],
    )
    # Die Bindung an den Fluss ist die eigene Semantik (L4-MK17). Sie steht als
    # Erweiterung daneben, weil BPMN-Werkzeuge eine Assoziation an einem
    # Sequenzfluss nicht annehmen -- das Element selbst zeigt auf den Knoten.
    ziel_fluss = fluss.ziel if fluss.quelle == daten_id else fluss.quelle
    if fluss.stereotype or ziel_fluss != element_id:
        s.auf("extensionElements")
        if fluss.stereotype:
            s.leer("admbw:stereotype", [("name", fluss.stereotype)])
        if ziel_fluss != element_id:
            s.leer("admbw:conveyed", [("fluss", ziel_fluss)])
        s.zu("extensionElements")
    s.zu("association")


def _schreibe_daten(s: _Schreiber, daten: m.Datenobjekt) -> None:
    if daten.art == "text_annotation":
        s.auf("textAnnotation", [("id", daten.id)])
        if daten.name:
            s.text("text", daten.name)
        s.zu("textAnnotation")
        return
    attribute = [("id", daten.id), ("name", daten.name)]
    if daten.art == "data_object_reference" and daten.data_object_ref:
        attribute.append(("dataObjectRef", daten.data_object_ref))
    if daten.art == "data_object":
        s.leer("dataObject", attribute)
        return
    s.auf("dataObjectReference", attribute)
    if daten.dokumentation:
        s.text("documentation", daten.dokumentation)
    s.zu("dataObjectReference")


def _schreibe_kollaboration(s: _Schreiber, modell: m.Modell, kollaboration: m.Kollaboration) -> None:
    s.auf("collaboration", [("id", kollaboration.id), ("name", kollaboration.name)])
    for teilnehmer in kollaboration.teilnehmer:
        s.auf(
            "participant",
            [
                ("id", teilnehmer.id),
                ("name", teilnehmer.name),
                ("processRef", teilnehmer.prozess_ref),
            ],
        )
        if teilnehmer.typ:
            s.auf("extensionElements")
            s.leer("admbw:typ", [("ref", teilnehmer.typ)])
            s.zu("extensionElements")
        s.zu("participant")
    for fluss_id in kollaboration.botschaftsfluesse:
        fluss = modell.fluesse.get(fluss_id)
        if fluss is None:
            continue
        s.auf(
            "messageFlow",
            [
                ("id", fluss.id),
                ("name", fluss.name),
                ("sourceRef", fluss.quelle),
                ("targetRef", fluss.ziel),
            ],
        )
        if fluss.stereotype:
            s.auf("extensionElements")
            s.leer("admbw:stereotype", [("name", fluss.stereotype)])
            s.zu("extensionElements")
        s.zu("messageFlow")
    for fluss in modell.fluesse.values():
        if fluss.art == "association" and modell.prozess_von_element(fluss.id) is None:
            _schreibe_assoziation(s, modell, fluss)
    s.zu("collaboration")


def _schreibe_diagramm(s: _Schreiber, diagramm: m.Diagramm, nummer: int) -> None:
    kennung = diagramm.id or f"BPMNDiagram_{nummer}"
    s.auf("bpmndi:BPMNDiagram", [("id", kennung), ("name", diagramm.name)])
    s.auf(
        "bpmndi:BPMNPlane",
        [("id", f"{kennung}_Plane"), ("bpmnElement", diagramm.ebenen_element)],
    )
    for form in diagramm.formen:
        attribute = [("id", f"Shape_{_kurz(form.element_ref)}"), ("bpmnElement", form.element_ref)]
        if form.ist_ausgeklappt is not None:
            attribute.append(("isExpanded", "true" if form.ist_ausgeklappt else "false"))
        if not form.ist_marker_visible:
            attribute.append(("isMarkerVisible", "false"))
        s.auf("bpmndi:BPMNShape", attribute)
        s.leer("dc:Bounds", _bounds(form.begrenzung))
        if form.label is not None:
            s.auf("bpmndi:BPMNLabel")
            s.leer("dc:Bounds", _bounds(form.label))
            s.zu("bpmndi:BPMNLabel")
        s.zu("bpmndi:BPMNShape")
    for kante in diagramm.kanten:
        s.auf("bpmndi:BPMNEdge", [("id", f"Edge_{_kurz(kante.element_ref)}"), ("bpmnElement", kante.element_ref)])
        for punkt in kante.wegpunkte:
            s.leer("di:waypoint", [("x", _zahl(punkt.x)), ("y", _zahl(punkt.y))])
        if kante.label is not None:
            s.auf("bpmndi:BPMNLabel")
            s.leer("dc:Bounds", _bounds(kante.label))
            s.zu("bpmndi:BPMNLabel")
        s.zu("bpmndi:BPMNEdge")
    s.zu("bpmndi:BPMNPlane")
    s.zu("bpmndi:BPMNDiagram")


def _bounds(begrenzung: m.Begrenzung) -> list[tuple[str, str]]:
    return [
        ("x", _zahl(begrenzung.x)),
        ("y", _zahl(begrenzung.y)),
        ("width", _zahl(begrenzung.breite)),
        ("height", _zahl(begrenzung.hoehe)),
    ]


def _kurz(kennung: str) -> str:
    """Kennung fuer DI-IDs: unveraendert, nur Zeichen, die XML nicht mag, ersetzt."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", kennung or "x")
