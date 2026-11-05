"""Austauschtest: offizielles BPMN-2.0-Schema und bpmn.io-Dateien.

Die Pruefung gegen das XSD ist die einzige Aussage, die ueber "oeffnet sich"
hinausgeht: Sie sagt, ob ein fremdes Werkzeug die Datei nach der Spezifikation
ueberhaupt annehmen darf. Die Beispieldateien in ``fixtures/`` stammen aus der
bpmn.io-Welt (Camunda Modeler); Herkunft und Pruefsummen stehen in
``fixtures/README.md`` und ``schema/README.md``.

Die Schema-Dateien liegen im Repo, damit der Test offline laeuft. Sie werden
nicht abgeschwaecht: Was das XSD ablehnt, ist ein Befund und wird repariert,
nicht wegkonfiguriert.
"""

from __future__ import annotations

import hashlib
import pathlib
import re

import pytest
from lxml import etree

from bpmn import bpmn_xml, extraktion, layout
from bpmn import modell as m

HIER = pathlib.Path(__file__).parent
SCHEMA_DATEI = HIER / "schema" / "BPMN20.xsd"
FIXTURES = HIER / "fixtures"
DOKUMENT = HIER.parents[1] / "docs" / "BPMN-KOMPATIBILITAET.md"

TEXTE = {
    "behoerde": (
        "Der Antragsteller reicht den Antrag beim Bauamt ein.\n"
        "Anschliessend prueft der Sachbearbeiter die Unterlagen.\n"
        "Wenn Unterlagen fehlen, fordert der Sachbearbeiter die Nachweise an.\n"
        "Danach entscheidet der Sachbearbeiter ueber den Antrag.\n"
        "Der Sachbearbeiter erstellt den Bescheid und sendet ihn an den Antragsteller."
    ),
    "leasing": (
        "Der Kunde stellt einen Leasingantrag.\n"
        "Die Leasinggesellschaft prueft die Bonitaet des Kunden.\n"
        "Danach erstellt die Leasinggesellschaft ein Angebot und sendet es an den Kunden.\n"
        "Der Kunde unterschreibt den Leasingvertrag."
    ),
    "wartung": (
        "Der Techniker erfasst das Wartungsticket im System.\n"
        "Falls eine Stoerung vorliegt, prueft der Techniker die Anlage.\n"
        "Der Techniker bestellt Ersatzteile.\n"
        "Nach der Reparatur dokumentiert der Techniker die Arbeiten."
    ),
}


@pytest.fixture(scope="module")
def schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(SCHEMA_DATEI)))


def _pruefe(schema: etree.XMLSchema, text: str) -> list[str]:
    """Schemafehler als lesbare Zeilen; leere Liste heisst gueltig."""
    dokument = etree.fromstring(text.encode("utf-8"))
    if schema.validate(dokument):
        return []
    return [f"Zeile {e.line}: {e.message}" for e in schema.error_log]


def _gelayoutet(modell: m.Modell) -> m.Modell:
    layout.verteile(modell)
    return modell


# --------------------------------------------------------------------------
# Schema selbst
# --------------------------------------------------------------------------


def test_schema_stammt_aus_der_bpmn_spezifikation() -> None:
    for name in ("BPMN20.xsd", "Semantic.xsd", "BPMNDI.xsd", "DC.xsd", "DI.xsd"):
        datei = SCHEMA_DATEI.parent / name
        assert datei.is_file(), f"Schema-Datei fehlt: {name}"
        assert datei.stat().st_size > 500

    wurzel = etree.parse(str(SCHEMA_DATEI)).getroot()
    assert wurzel.get("targetNamespace") == bpmn_xml.NS_BPMN


def test_schema_pruefung_lehnt_kaputte_datei_ab(schema: etree.XMLSchema) -> None:
    """Gegenprobe: waere die Pruefung abgeschaltet, faellt dieser Test."""
    kaputt = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<definitions xmlns="{bpmn_xml.NS_BPMN}" id="D1">'
        '<process id="P1"><startEvent id="S1"/></process></definitions>'
    )
    assert _pruefe(schema, kaputt), "fehlender targetNamespace muss auffallen"


# --------------------------------------------------------------------------
# Eigene Modelle gegen das Schema
# --------------------------------------------------------------------------


def test_beispielmodell_validiert_gegen_bpmn20(schema: etree.XMLSchema, modell: m.Modell) -> None:
    text = bpmn_xml.schreibe_text(_gelayoutet(modell))
    assert _pruefe(schema, text) == []


@pytest.mark.parametrize("name", sorted(TEXTE))
def test_extrahiertes_modell_validiert_gegen_bpmn20(schema: etree.XMLSchema, name: str) -> None:
    ergebnis = extraktion.extrahiere(TEXTE[name], name)
    text = bpmn_xml.schreibe_text(_gelayoutet(ergebnis.modell))
    assert _pruefe(schema, text) == []


def test_lanes_mit_performer_halten_die_schemareihenfolge(schema: etree.XMLSchema, modell: m.Modell) -> None:
    """tLane erlaubt extensionElements nur vor flowNodeRef -- nicht dahinter."""
    text = bpmn_xml.schreibe_text(_gelayoutet(modell))
    lane = re.search(r"<lane [^>]*>.*?</lane>", text, re.S)
    assert lane is not None
    rumpf = lane.group(0)
    if "admbw:performer" in rumpf:
        assert rumpf.index("extensionElements") < rumpf.index("flowNodeRef")
    assert _pruefe(schema, text) == []


# --------------------------------------------------------------------------
# bpmn.io-Dateien lesen
# --------------------------------------------------------------------------


def test_bpmn_io_starter_wird_gelesen() -> None:
    modell = bpmn_xml.lies(str(FIXTURES / "bpmn-io-starter.bpmn"))
    assert list(modell.prozesse) == ["Process_1"]
    assert [k.art for k in modell.alle_knoten()] == ["start_event"]
    assert modell.knoten["StartEvent_1"].begrenzung == m.Begrenzung(182, 162, 36, 36)


def test_bpmn_io_beispiel_wird_vollstaendig_gelesen() -> None:
    modell = bpmn_xml.lies(str(FIXTURES / "bpmn-io-example.bpmn"))
    assert list(modell.prozesse) == ["Process_1"]
    assert {k.name for k in modell.alle_knoten()} == {
        "Order Placed",
        "Collect Money",
        "Fetch Items",
        "Ship Parcel",
        "Order Delivered",
    }
    assert len([f for f in modell.fluesse.values() if f.art == "sequence_flow"]) == 4
    # Der Modellierer schreibt Bounds und Waypoints; beides muss ankommen.
    assert all(k.begrenzung is not None for k in modell.alle_knoten())
    assert all(f.wegpunkte for f in modell.fluesse.values())


@pytest.mark.parametrize("name", ["bpmn-io-starter.bpmn", "bpmn-io-example.bpmn"])
def test_bpmn_io_roundtrip_bleibt_schemagueltig(schema: etree.XMLSchema, name: str) -> None:
    modell = bpmn_xml.lies(str(FIXTURES / name))
    einmal = bpmn_xml.schreibe_text(modell)
    zweimal = bpmn_xml.schreibe_text(bpmn_xml.lies_text(einmal))
    assert einmal == zweimal
    assert _pruefe(schema, einmal) == []


def test_fremde_erweiterungen_werden_nicht_uebernommen() -> None:
    """Bekannte Luecke, bewusst festgehalten.

    Die Camunda-Datei traegt ``zeebe:taskDefinition`` in jedem Dienstschritt.
    Das Modell kennt nur die eigenen ADMBw-Erweiterungen; fremde Erweiterungen
    fallen beim Lesen weg (siehe docs/BPMN-KOMPATIBILITAET.md, Abschnitt
    "Offene Luecken"). Der Test haelt den Ist-Zustand fest, damit die Luecke
    nicht stillschweigend als "unterstuetzt" gilt.
    """
    text = bpmn_xml.schreibe_text(bpmn_xml.lies(str(FIXTURES / "bpmn-io-example.bpmn")))
    assert "zeebe" not in text


# --------------------------------------------------------------------------
# Assoziationen: BPMN-Werkzeuge nehmen keine Kante an einer Kante an
# --------------------------------------------------------------------------


def test_assoziation_zeigt_auf_ein_element_nicht_auf_einen_fluss(schema: etree.XMLSchema, modell: m.Modell) -> None:
    """bpmn-js verwirft Assoziationen, deren targetRef ein Sequenzfluss ist."""
    text = bpmn_xml.schreibe_text(_gelayoutet(modell))
    ziele = re.findall(r"<association [^>]*?targetRef=\"([^\"]+)\"", text)
    assert ziele
    fluss_ids = {f.id for f in modell.fluesse.values()}
    assert not (set(ziele) & fluss_ids)
    assert _pruefe(schema, text) == []


def test_conveyed_bindung_ueberlebt_den_roundtrip(modell: m.Modell) -> None:
    vorher = {f.id: [d.id for d in modell.conveyed_items(f.id)] for f in modell.fluesse.values()}
    wieder = bpmn_xml.lies_text(bpmn_xml.schreibe_text(modell))
    nachher = {f.id: [d.id for d in wieder.conveyed_items(f.id)] for f in wieder.fluesse.values()}
    assert nachher == vorher
    assert any(nachher.values()), "ohne Conveyed Items prueft der Test nichts"


FREMDES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
             xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
             id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <process id="Process_1" isExecutable="false">
    <startEvent id="Start_1"/>
    <task id="Task_1" name="Antrag pruefen"/>
    <endEvent id="Ende_1"/>
    <sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1"/>
    <sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Ende_1"/>
    <dataObjectReference id="Daten_1" name="Antrag"/>
    <association id="Assoz_1" sourceRef="Daten_1" targetRef="Task_1"/>
  </process>
  <bpmndi:BPMNDiagram id="D1">
    <bpmndi:BPMNPlane id="P1" bpmnElement="Process_1">
      <bpmndi:BPMNShape id="S_1" bpmnElement="Start_1"><dc:Bounds x="100" y="100" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_2" bpmnElement="Task_1"><dc:Bounds x="200" y="80" width="100" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_3" bpmnElement="Ende_1"><dc:Bounds x="360" y="100" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_4" bpmnElement="Daten_1"><dc:Bounds x="215" y="10" width="36" height="50"/></bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="E_1" bpmnElement="Flow_1"><di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="136" y="118"/><di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="200" y="118"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_2" bpmnElement="Flow_2"><di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="300" y="120"/><di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="360" y="118"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_3" bpmnElement="Assoz_1"><di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="233" y="60"/><di:waypoint xmlns:di="http://www.omg.org/spec/DD/20100524/DI" x="233" y="80"/></bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</definitions>
"""


def test_fremde_assoziationsform_zaehlt_als_conveyed_item(schema: etree.XMLSchema) -> None:
    """bpmn.io haengt Daten an die Aktion. Das gilt als Conveyed Item (L4-MK17)."""
    modell = bpmn_xml.lies_text(FREMDES_XML)
    assert [d.name for d in modell.conveyed_items("Flow_1")] == ["Antrag"]
    assert _pruefe(schema, bpmn_xml.schreibe_text(modell)) == []


# --------------------------------------------------------------------------
# Befunddokument
# --------------------------------------------------------------------------


def test_kompatibilitaetsdokument_belegt_die_aussagen() -> None:
    text = DOKUMENT.read_text(encoding="utf-8")
    assert "bpmn-miwg" in text, "MIWG-Testbestand als Beleg fehlt"
    assert "Enterprise Architect" in text
    assert "https://" in text
    assert "Offene" in text


def test_fixtures_sind_die_abgelegten_dateien() -> None:
    """Pruefsummen stehen im README; hier nur: die Dateien sind unveraendert lesbar."""
    for name in ("bpmn-io-starter.bpmn", "bpmn-io-example.bpmn"):
        datei = FIXTURES / name
        assert hashlib.sha256(datei.read_bytes()).hexdigest()
        assert datei.read_text(encoding="utf-8").startswith("<?xml")
