"""BPMN 2.0 XML: Roundtrip, Namensraeume, Reihenfolge.

Die Reihenfolgepruefungen sind keine Pedanterie: bpmn.io und ARIS lesen nur,
was das BPMN-Schema in dieser Ordnung erlaubt (``laneSet`` vor ``flowElement``,
``BPMNShape`` vor ``BPMNEdge``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from bpmn import bpmn_xml, layout
from bpmn import modell as m

NS = {
    "bpmn": bpmn_xml.NS_BPMN,
    "bpmndi": bpmn_xml.NS_BPMNDI,
    "dc": bpmn_xml.NS_DC,
    "di": bpmn_xml.NS_DI,
}


def test_roundtrip_ist_byte_stabil(modell: m.Modell) -> None:
    einmal = bpmn_xml.schreibe_text(modell)
    zweimal = bpmn_xml.schreibe_text(bpmn_xml.lies_text(einmal))
    assert einmal == zweimal


def test_roundtrip_ueber_datei(tmp_path, modell: m.Modell) -> None:
    pfad = tmp_path / "prozess.bpmn"
    bpmn_xml.schreibe(modell, str(pfad))
    wieder = bpmn_xml.lies(str(pfad))
    assert set(wieder.prozesse) == set(modell.prozesse)
    assert set(wieder.knoten) == set(modell.knoten)
    assert set(wieder.fluesse) == set(modell.fluesse)
    assert set(wieder.daten) == set(modell.daten)


def test_roundtrip_erhaelt_alle_semantischen_felder(modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(modell)
    wieder = bpmn_xml.lies_text(text)

    for knoten_id, knoten in modell.knoten.items():
        kopie = wieder.knoten[knoten_id]
        assert kopie.name == knoten.name
        assert kopie.art == knoten.art
        assert kopie.stereotype == knoten.stereotype
        assert kopie.ereignis_rolle == knoten.ereignis_rolle
        assert kopie.ereignis_definition == knoten.ereignis_definition

    for fluss_id, fluss in modell.fluesse.items():
        kopie = wieder.fluesse[fluss_id]
        assert kopie.quelle == fluss.quelle
        assert kopie.ziel == fluss.ziel
        assert kopie.bedingung == fluss.bedingung
        assert kopie.art == fluss.art

    for teilnehmer in modell.alle_teilnehmer():
        kopie = wieder.teilnehmer_von_prozess(teilnehmer.prozess_ref)
        assert kopie is not None
        assert kopie.name == teilnehmer.name
        assert kopie.typ == teilnehmer.typ

    lane = modell.prozesse["Process_Antrag"].alle_lanes()[0]
    kopie_lane = wieder.prozesse["Process_Antrag"].alle_lanes()[0]
    assert kopie_lane.performer == lane.performer
    assert kopie_lane.knoten == lane.knoten


def test_geometrie_ueberlebt_den_roundtrip(modell: m.Modell) -> None:
    wieder = bpmn_xml.lies_text(bpmn_xml.schreibe_text(modell))
    assert len(wieder.diagramme) == len(modell.diagramme)
    aufgabe = next(k for k in modell.knoten.values() if k.ist_aufgabe)
    form = wieder.diagramme[0].form(aufgabe.id)
    assert form is not None
    assert form.begrenzung.breite == aufgabe.begrenzung.breite
    fluss = next(f for f in modell.fluesse.values() if f.art == "sequence_flow")
    kante = wieder.diagramme[0].kante(fluss.id)
    assert kante is not None and len(kante.wegpunkte) >= 2


def test_namensraeume_sind_bpmn_konform(modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(modell)
    wurzel = ET.fromstring(text)
    assert wurzel.tag == f"{{{bpmn_xml.NS_BPMN}}}definitions"
    for praefix, uri in (
        ("bpmndi", bpmn_xml.NS_BPMNDI),
        ("dc", bpmn_xml.NS_DC),
        ("di", bpmn_xml.NS_DI),
    ):
        assert f'xmlns:{praefix}="{uri}"' in text

    # Jedes Element liegt in einem der deklarierten Namensraeume; die
    # ADMBw-Erweiterungen bewusst in einem eigenen, damit sie niemand mit
    # BPMN-Standard verwechselt.
    erlaubt = (
        bpmn_xml.NS_BPMN,
        bpmn_xml.NS_BPMNDI,
        bpmn_xml.NS_DC,
        bpmn_xml.NS_DI,
        bpmn_xml.NS_ADMBW,
    )
    for element in wurzel.iter():
        if "}" in element.tag:
            raum = element.tag.split("}")[0][1:]
            assert raum in erlaubt
    erweiterungen = [
        e for e in wurzel.iter() if e.tag.startswith(f"{{{bpmn_xml.NS_ADMBW}}}")
    ]
    assert erweiterungen, "Fixture sollte ADMBw-Erweiterungen schreiben"
    assert 'xmlns:admbw="https://eam-platform.local/bpmn/admbw"' in text


def test_di_hat_plane_shapes_und_edges(modell: m.Modell) -> None:
    wurzel = ET.fromstring(bpmn_xml.schreibe_text(modell))
    diagramme = wurzel.findall("bpmndi:BPMNDiagram", NS)
    assert diagramme
    ebenen = diagramme[0].findall("bpmndi:BPMNPlane", NS)
    assert len(ebenen) == 1
    assert ebenen[0].get("bpmnElement") == modell.kollaboration.id
    assert len(ebenen[0].findall("bpmndi:BPMNShape", NS)) >= len(modell.knoten)
    assert len(ebenen[0].findall("bpmndi:BPMNEdge", NS)) >= 1
    for kante in ebenen[0].findall("bpmndi:BPMNEdge", NS):
        assert len(kante.findall("di:waypoint", NS)) >= 2


def test_elementreihenfolge_im_prozess(modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(modell)
    prozess_start = text.index("<process ")
    assert text.index("<laneSet", prozess_start) < text.index("<startEvent", prozess_start)
    # Datenobjekte und Assoziationen stehen hinter den Flussknoten.
    assert text.index("<dataObjectReference") < text.index("<association ")
    assert text.index("<sequenceFlow") < text.index("<dataObjectReference")


def test_incoming_und_outgoing_vor_eventdefinition(modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(modell)
    block = re.search(r"<startEvent [^>]*name=\"Antrag eingegangen\".*?</startEvent>", text, re.S)
    assert block is not None
    inhalt = block.group(0)
    assert "<incoming" in inhalt or "<outgoing" in inhalt
    if "<eventDefinition" in inhalt:
        assert inhalt.index("<outgoing") < inhalt.index("<eventDefinition")


def test_teinehmer_vor_messageflow_und_shapes_vor_edges(modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(modell)
    assert text.index("<participant ") < text.index("<messageFlow ")
    assert text.rindex("<bpmndi:BPMNShape") < text.index("<bpmndi:BPMNEdge")


def test_leere_elemente_werden_kurz_geschrieben(modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(modell)
    assert "<sequenceFlow" in text
    assert not re.search(r"<sequenceFlow[^>]*>\s*</sequenceFlow>", text)


def test_namespace_tolerant_lesen() -> None:
    """Praefigierte Dokumente (andere Werkzeuge) muessen genauso gelesen werden."""
    text = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
                  id="D1" targetNamespace="http://example.invalid">
  <bpmn:process id="P1" name="Praefix" isExecutable="false">
    <bpmn:startEvent id="S1" name="Start"/>
    <bpmn:task id="T1" name="Arbeit"/>
    <bpmn:endEvent id="E1" name="Ende"/>
    <bpmn:sequenceFlow id="F1" sourceRef="S1" targetRef="T1"/>
    <bpmn:sequenceFlow id="F2" sourceRef="T1" targetRef="E1"/>
  </bpmn:process>
</bpmn:definitions>
"""
    modell = bpmn_xml.lies_text(text)
    assert modell.prozesse["P1"].name == "Praefix"
    assert set(modell.knoten) == {"S1", "T1", "E1"}
    assert modell.fluesse["F1"].ziel == "T1"
    wieder = bpmn_xml.schreibe_text(modell)
    assert 'xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"' in wieder


def test_unbekannte_attribute_bleiben(modell: m.Modell) -> None:
    aufgabe = next(k for k in modell.knoten.values() if k.ist_aufgabe)
    aufgabe.attribute["completionQuantity"] = "1"
    wieder = bpmn_xml.lies_text(bpmn_xml.schreibe_text(modell))
    assert wieder.knoten[aufgabe.id].attribute["completionQuantity"] == "1"


def test_mehrere_diagramme_bleiben_erhalten(modell: m.Modell) -> None:
    modell.diagramme.append(
        m.Diagramm(id="BPMNDiagram_2", name="Zweite Sicht", ebenen_element="Process_Antrag")
    )
    wieder = bpmn_xml.lies_text(bpmn_xml.schreibe_text(modell))
    assert [d.id for d in wieder.diagramme] == ["BPMNDiagram_1", "BPMNDiagram_2"]


def test_zielnamespace_wird_geschrieben(modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(modell)
    assert 'targetNamespace="https://example.invalid/bpmn"' in text


def test_falsche_wurzel_wird_abgewiesen() -> None:
    with pytest.raises(ValueError):
        bpmn_xml.lies_text("<html/>")


def test_layout_erzeugt_diagramm_ohne_vorlage() -> None:
    modell = m.Modell(name="Ohne Diagramm")
    prozess = modell.neuer_prozess("P")
    start = modell.neuer_knoten("start_event", "Start", prozess)
    aufgabe = modell.neuer_knoten("task", "Arbeit", prozess)
    modell.neuer_fluss("sequence_flow", start.id, aufgabe.id, prozess=prozess)
    layout.verteile(modell)
    assert modell.knoten[start.id].begrenzung is not None
    text = bpmn_xml.schreibe_text(modell)
    assert "BPMNShape" in text and "BPMNEdge" in text
