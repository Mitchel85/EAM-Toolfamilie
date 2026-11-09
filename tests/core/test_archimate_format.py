"""ArchiMate 3.2 als Zielformat: Determinismus, Auflösung, laute Fehler.

Der Vertrag: ``.xml`` (ArchiMate Model Exchange) ist ein Ausgabeformat wie
``.qea`` und ``.xmi`` — dasselbe IR, dieselbe Prüfung, dasselbe Gate. Diese
Tests belegen:

1. **Determinismus** — gleiches IR, gleiche Bytes.
2. **Geschlossene Referenzen** — jede Kante zeigt auf ein vorhandenes Element.
3. **Träger-Auflösung** — Ports/Parts/Pins verschwinden als Element und ihre
   Kanten laufen auf das Trägerelement.
4. **Kein stiller Verlust** — IR ohne ``ref`` oder mit doppelten Referenzen
   bricht ab; unbekannte EA-Typen landen im Report.
5. **Typweißliste** — nur ArchiMate-Typen, keine EA-Namen.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import archimate_writer
from archimate_writer import ArchimateWriterError
from qea_reader import QeaReaderError, read_qea_ex

NS = "{http://www.opengroup.org/xsd/archimate/3.0/}"
CORE = Path(__file__).resolve().parents[2] / "packages" / "core"
FIXTURES = CORE / "fixtures"
MASC = FIXTURES / "Musterarchitektur_MASC.qea"

ELEMENT_TYPES = {
    "Access", "Aggregation", "ApplicationCollaboration", "ApplicationComponent",
    "ApplicationEvent", "ApplicationFunction", "ApplicationInteraction",
    "ApplicationInterface", "ApplicationProcess", "ApplicationService", "Artifact",
    "Assessment", "Assignment", "Association", "BusinessActor", "BusinessCollaboration",
    "BusinessEvent", "BusinessFunction", "BusinessInteraction", "BusinessInterface",
    "BusinessObject", "BusinessProcess", "BusinessRole", "BusinessService", "Capability",
    "CommunicationNetwork", "Composition", "Constraint", "Contract", "CourseOfAction",
    "DataObject", "Deliverable", "Device", "DistributionNetwork", "Driver", "Equipment",
    "Facility", "Flow", "Gap", "Goal", "Grouping", "ImplementationEvent", "Influence",
    "Location", "Material", "Meaning", "Node", "Outcome", "Path", "Plateau", "Principle",
    "Product", "Realization", "Representation", "Requirement", "Resource", "Serving",
    "Specialization", "Stakeholder", "SystemSoftware", "TechnologyCollaboration",
    "TechnologyEvent", "TechnologyFunction", "TechnologyInteraction",
    "TechnologyInterface", "TechnologyProcess", "TechnologyService", "Triggering",
    "Value", "ValueStream", "WorkPackage",
}


def _ir(eintraege: list[dict]) -> dict:
    return {
        "ir_version": 1,
        "technology": {"profile": "NAFv4-ADMBw"},
        "packages": [{"path": "P"}],
        "elements": eintraege,
        "connectors": [],
        "diagrams": [],
    }


def _element(ref: str, typ: str = "Class", stereo: str = "", guid: str = "", **extra) -> dict:
    eintrag = {"package": "P", "name": ref.rsplit("::", 1)[-1], "ea_type": typ, "ref": ref}
    if stereo:
        eintrag["stereotype"] = stereo
    if guid:
        eintrag["guid"] = guid
    eintrag.update(extra)
    return eintrag


def _typen(xml: bytes) -> tuple[list[str | None], list[str | None]]:
    root = ET.fromstring(xml)
    elemente = [e.get("{http://www.w3.org/2001/XMLSchema-instance}type")
                for e in root.iter(f"{NS}element")]
    kanten = [e.get("{http://www.w3.org/2001/XMLSchema-instance}type")
              for e in root.iter(f"{NS}relationship")]
    return elemente, kanten


# --------------------------------------------------------------------------
# 1. Determinismus und Grundform
# --------------------------------------------------------------------------
def test_render_ist_deterministisch():
    ir = _ir([_element("P::A", stereo="Capability"), _element("P::B", stereo="System")])
    ir["connectors"] = [{"source": "P::B", "target": "P::A",
                         "stereotype": "Implements", "ea_type": "Realisation", "tags": {}}]
    assert archimate_writer.render_bytes(ir) == archimate_writer.render_bytes(ir)


def test_nur_archimate_typen():
    ir = _ir([_element("P::A", stereo="Capability"), _element("P::B", stereo="System")])
    ir["connectors"] = [{"source": "P::B", "target": "P::A", "stereotype": "Satisfy",
                         "ea_type": "Realisation", "tags": {}}]
    elemente, kanten = _typen(archimate_writer.render_bytes(ir))
    assert set(elemente) <= ELEMENT_TYPES
    assert set(kanten) <= ELEMENT_TYPES


def test_kennungen_sind_eindeutig_und_referenzen_geschlossen(tmp_path: Path):
    ir = _ir([_element("P::A", stereo="Capability"), _element("P::B", stereo="System"),
              _element("P::C", stereo="Organization")])
    ir["connectors"] = [
        {"source": "P::B", "target": "P::A", "stereotype": "Satisfy", "ea_type": "Realisation", "tags": {}},
        {"source": "P::C", "target": "P::B", "stereotype": "", "ea_type": "Dependency", "tags": {}},
    ]
    xml = archimate_writer.render_bytes(ir)
    root = ET.fromstring(xml)
    ids = [e.get("identifier") for e in root.iter(f"{NS}element")]
    assert len(ids) == len(set(ids))
    vorhanden = set(ids)
    for rel in root.iter(f"{NS}relationship"):
        assert rel.get("source") in vorhanden
        assert rel.get("target") in vorhanden


# --------------------------------------------------------------------------
# 2. Träger-Auflösung
# --------------------------------------------------------------------------
def test_port_und_part_werden_auf_traeger_gezogen():
    ir = _ir([
        _element("P::System A", stereo="System", guid="{11111111-1111-1111-1111-111111111111}"),
        _element("P::System B", stereo="System", guid="{22222222-2222-2222-2222-222222222222}"),
        _element("P::Port A", typ="Port", stereo="ResourcePort", owner="P::System A"),
    ])
    ir["connectors"] = [{"source": "P::Port A", "target": "P::System B", "stereotype": "",
                         "ea_type": "InformationFlow", "tags": {}}]
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_port_test.xml")
    assert report.elements == 2
    assert report.relationships == 1
    assert report.unresolved == 0
    assert report.by_relation == {"Flow": 1}


def test_unaufgeloester_endpunkt_wird_gezaehlt():
    ir = _ir([_element("P::A", stereo="Capability")])
    ir["connectors"] = [{"source": "P::A", "target": "P::Fehlt", "stereotype": "",
                         "ea_type": "Dependency", "tags": {}}]
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_unresolved.xml")
    assert report.unresolved == 1
    assert report.relationships == 0
    assert report.unresolved_by_type


# --------------------------------------------------------------------------
# 3. Laute Fehler
# --------------------------------------------------------------------------
def test_ohne_ref_bricht_ab():
    ir = _ir([{"package": "P", "name": "A", "ea_type": "Class", "stereotype": "Capability"}])
    with pytest.raises(ArchimateWriterError, match="ref"):
        archimate_writer.render_bytes(ir)


def test_doppelte_ref_bricht_ab():
    ir = _ir([_element("P::A", stereo="Capability"), _element("P::A", stereo="System")])
    with pytest.raises(ArchimateWriterError, match="doppelt"):
        archimate_writer.render_bytes(ir)


def test_leeres_ir_bricht_ab():
    with pytest.raises(ArchimateWriterError, match="kein Element"):
        archimate_writer.render_bytes({"ir_version": 1, "elements": []})


def test_falsche_ir_version_bricht_ab():
    with pytest.raises(ArchimateWriterError, match="ir_version"):
        archimate_writer.render_bytes({"ir_version": 99, "elements": [_element("P::A")]})


# --------------------------------------------------------------------------
# 4. Mapping und Report
# --------------------------------------------------------------------------
def test_unbekannter_stereotyp_faellt_sichtbar_zurueck():
    ir = _ir([_element("P::A", typ="Class", stereo="GibtEsNicht")])
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_fallback.xml")
    assert report.elements == 1
    assert report.fallback == {"class": 1}
    assert report.by_type == {"Grouping": 1}


def test_darstellungs_und_pakettypen_werden_uebersprungen():
    ir = _ir([
        _element("P::A", stereo="Capability"),
        _element("P::Notiz", typ="Note"),
        _element("P::Text", typ="Text"),
        _element("P::Paket", typ="Package"),
    ])
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_skip.xml")
    assert report.elements == 1
    assert report.skipped_display == 2
    # Ein Paket-Eintrag in elements[] ist kein ArchiMate-Element; die echten
    # IR-Pakete werden getrennt gezaehlt (Audit T2, Nr. 17).
    assert report.skipped_package_entries == 1
    # Der IR-Helfer legt ein Paket an; es wird nicht als Element ausgegeben.
    assert report.packages == 1
    assert report.packages_not_emitted == 1


# --------------------------------------------------------------------------
# 5. Echtes Modell (uebersprungen, wenn die Fixture fehlt)
# --------------------------------------------------------------------------
@pytest.mark.skipif(not MASC.is_file(), reason="Musterarchitektur_MASC.qea fehlt")
def test_masc_konvertiert_und_ist_stabil(tmp_path: Path):
    ir, read = read_qea_ex(MASC, with_refs=True, with_owners=True)
    bericht = archimate_writer.write_archimate(ir, tmp_path / "masc.xml", modellname="MASC")
    assert bericht.elements > 900
    assert bericht.relationships > 1000
    # Zweiter Lauf: identische Bytes
    einmal = (tmp_path / "masc.xml").read_bytes()
    archimate_writer.write_archimate(ir, tmp_path / "masc2.xml", modellname="MASC")
    assert einmal == (tmp_path / "masc2.xml").read_bytes()

    root = ET.fromstring(einmal)
    ids = {e.get("identifier") for e in root.iter(f"{NS}element")}
    for rel in root.iter(f"{NS}relationship"):
        assert rel.get("source") in ids and rel.get("target") in ids
