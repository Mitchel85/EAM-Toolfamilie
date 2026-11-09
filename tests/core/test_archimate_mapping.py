"""Regeltests zum Mapping-Audit (T2) — eine Regel, ein Test.

Der Audit ``Mapping-Audit_Soll-Ist.md`` (Task t_8d9f3308) hat 23 Element-Regeln
und 17 Beziehungs-/Report-Luecken belegt. Dieses Modul pinnt jede Korrektur:

1. **Element-Regeln** — jeder korrigierte Stereotyp liefert den Guide-Typ.
2. **Beziehungs-Regeln** — jeder korrigierte Stereotyp liefert die Guide-Relation
   bzw. die von der ArchiMate-3.2-Matrix erlaubte Ersatzrelation.
3. **Matrix-Anwendung** — Inversion, semantischer Fallback, Association-Regel.
4. **Report** — jede Naeherung hat einen Zaehler (Audit T2, Abschnitt 4.2).
5. **Messmodell** — die Kennzahlen vor/nach sind festgeschrieben.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import archimate_writer
from archimate_writer import ArchimateWriterError
from qea_reader import read_qea_ex

NS = "{http://www.opengroup.org/xsd/archimate/3.0/}"
XSI = "{http://www.w3.org/2001/XMLSchema-instance}"
CORE = Path(__file__).resolve().parents[2] / "packages" / "core"
MASC = CORE / "fixtures" / "Musterarchitektur_MASC.qea"


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------
def _ir(elemente: list[dict], kanten: list[dict] | None = None) -> dict:
    return {
        "ir_version": 1,
        "technology": {"profile": "NAFv4-ADMBw"},
        "packages": [{"path": "P"}],
        "elements": elemente,
        "connectors": kanten or [],
        "diagrams": [],
    }


def _element(ref: str, stereo: str = "", typ: str = "Class", **extra) -> dict:
    eintrag = {"package": "P", "name": ref.rsplit("::", 1)[-1], "ea_type": typ, "ref": ref}
    if stereo:
        eintrag["stereotype"] = stereo
    eintrag.update(extra)
    return eintrag


def _element_typ(stereo: str) -> str:
    """Rendert ein Element mit diesem Stereotyp und liest den xsi:type."""
    xml = archimate_writer.render_bytes(_ir([_element("P::A", stereo=stereo)]))
    root = ET.fromstring(xml)
    elemente = list(root.iter(f"{NS}element"))
    assert len(elemente) == 1, f"{stereo}: erwartet ein Element, gefunden {len(elemente)}"
    return elemente[0].get(XSI + "type")


def _kante(
    quelle: str, ziel: str, stereo: str = "", ea_type: str = "Dependency"
) -> tuple[str, bool, bool]:
    """Rendert eine Kante zwischen zwei Elementen mit ArchiMate-Typ.

    Rueckgabe: (xsi:type der Beziehung, zeigt_von_Q_nach_Z, zeigt_von_Z_nach_Q).
    """
    ir = _ir(
        [
            {"ref": "P::Q", "package": "P", "name": "Q", "ea_type": quelle},
            {"ref": "P::Z", "package": "P", "name": "Z", "ea_type": ziel},
        ],
        [{"source": "P::Q", "target": "P::Z", "stereotype": stereo, "ea_type": ea_type}],
    )
    root = ET.fromstring(archimate_writer.render_bytes(ir))
    ids = {
        e.find(f"{NS}name").text: e.get("identifier")
        for e in root.iter(f"{NS}element")
    }
    kanten = list(root.iter(f"{NS}relationship"))
    assert len(kanten) == 1, f"{stereo or ea_type}: erwartet eine Kante, gefunden {len(kanten)}"
    k = kanten[0]
    return k.get(XSI + "type"), k.get("source") == ids["Q"], k.get("target") == ids["Z"]


# --------------------------------------------------------------------------
# 1. Element-Regeln (Audit T2, Abschnitt 2 und 5)
# --------------------------------------------------------------------------
ELEMENT_REGELN = [
    # Audit Nr. 1 — A2 §44.2
    ("View", "Representation"),
    ("Viewpoint", "BusinessObject"),
    # Audit Nr. 2 — A8 §50.2 / P3 §35.2
    ("Standard", "Contract"),
    # Audit Nr. 3 — C5/C7/S8/A7
    ("MeasurementType", "BusinessObject"),
    ("Measurement", "BusinessObject"),
    # Audit Nr. 4 — Cr/Lr/Sr/Ar
    ("ProjectMilestone", "ImplementationEvent"),
    ("ActualProjectMilestone", "ImplementationEvent"),
    # Audit Nr. 5 — C8/L8/P8/S8/A8
    ("Constraint", "Requirement"),
    ("StrategicConstraint", "Requirement"),
    ("OperationalConstraint", "Requirement"),
    ("ResourceConstraint", "Requirement"),
    # Audit Nr. 6 — L1 §23.2 / L4 §27.2
    ("OperationalPerformer", "BusinessActor"),
    # Audit Nr. 7 — P1 §33.2 / P4 §36.2
    ("Function", "BusinessProcess"),
    ("FunctionAction", "BusinessProcess"),
    # Audit Nr. 8 — S2 §14.2
    ("Software", "SystemSoftware"),
    # Audit Nr. 9 — P3 §35.2
    ("Protocol", "Artifact"),
    ("Protocolstack", "Artifact"),
    ("ProtocolLayer", "Artifact"),
    # Anhang A, ABWEICHUNG/FEHLT
    ("EnduringTask", "Capability"),
    ("ActualEnduringTask", "Capability"),
    ("GlossaryEntry", "Meaning"),
    ("Energy", "Material"),
    # Regressionsschutz: unveraenderte Guide-regelkonforme Regeln
    ("OperationalRole", "BusinessRole"),
    ("Capability", "Capability"),
    ("InformationElement", "BusinessObject"),
    ("Organization", "BusinessActor"),
]


@pytest.mark.parametrize("stereo,erwartet", ELEMENT_REGELN)
def test_element_regel_liefert_guide_typ(stereo: str, erwartet: str) -> None:
    assert archimate_writer.ELEMENT_MAP[stereo] == erwartet
    assert _element_typ(stereo) == erwartet


def test_view_und_standard_erzeugen_keine_groupings_mehr() -> None:
    """Audit Nr. 1/2: die groessten Fehlposten (163 + 49 Elemente) sind weg."""
    ir = _ir(
        [
            _element("P::Sicht", stereo="View"),
            _element("P::Standard", stereo="Standard"),
            _element("P::Mass", stereo="MeasurementType"),
        ]
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_elemente.xml")
    assert report.by_type == {"Contract": 1, "BusinessObject": 1, "Representation": 1}


def test_paket_stereotypen_werden_als_element_ausgegeben() -> None:
    """Audit Nr. 1: ArchitecturalDescription -> Product, DataModel -> DataObject."""
    ir = _ir([_element("P::Sicht", stereo="View")])
    ir["packages"] = [
        {"path": "P::AD", "stereotype": "ArchitecturalDescription", "name": "AD"},
        {"path": "P::DM", "stereotype": "DataModel", "name": "DM"},
        {"path": "P::Rest", "stereotype": "", "name": "Rest"},
    ]
    ir["connectors"] = [
        {"source": "P::AD", "target": "P::Sicht", "stereotype": "", "ea_type": "Association"},
        {"source": "P::DM", "target": "P::Sicht", "stereotype": "", "ea_type": "Association"},
    ]
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_pakete.xml")
    assert report.by_type["Product"] == 1
    assert report.by_type["DataObject"] == 1
    assert report.packages == 3
    assert report.packages_emitted == 2
    assert report.packages_not_emitted == 1


def test_zustand_und_ereignis_werden_zu_business_event() -> None:
    """Audit Nr. 13: State/StateNode/Event sind laut Guide Events."""
    ir = _ir(
        [
            _element("P::Zustand", typ="State"),
            _element("P::Zustandsknoten", typ="StateNode"),
            _element("P::Ereignis", typ="Event"),
        ]
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_events.xml")
    assert report.by_type == {"BusinessEvent": 3}
    assert report.approximations == {
        "state->BusinessEvent": 1,
        "statenode->BusinessEvent": 1,
        "event->BusinessEvent": 1,
    }
    assert report.skipped_fachlich == 0


def test_jede_element_regel_liegt_im_xsd_typsystem() -> None:
    """Kein EA-Name, kein Tippfehler: nur Typen aus archimate3_Model.xsd."""
    unbekannt = {
        stereo: typ
        for stereo, typ in archimate_writer.ELEMENT_MAP.items()
        if typ not in archimate_writer.ARCHIMATE_ELEMENT_TYPES
    }
    assert unbekannt == {}


# --------------------------------------------------------------------------
# 2. Beziehungs-Regeln (Audit T2, Abschnitt 3 und 5)
# --------------------------------------------------------------------------
BEZIEHUNGS_REGELN = [
    # Korrigiert, weil der Guide eine andere Relation nennt
    ("CapabilityForTask", "Serving"),
    ("IsCapableToPerform", "Assignment"),
    ("PerformsInContext", "Assignment"),
    ("Checks", "Influence"),
    ("ConcernForView", "Influence"),
    ("ConcernForViewpoint", "Influence"),
    ("ConcernForActualEnterprisePhase", "Influence"),
    ("DerivedFrom", "Influence"),
    ("JustifiedBy", "Influence"),
    ("DesiredEffect", "Influence"),
    ("GoalForActualEnterprisePhase", "Aggregation"),
    ("VisionForActualEnterprisePhase", "Aggregation"),
    ("OwnedMilestone", "Association"),
    ("VersionSuccession", "Triggering"),
    ("MilestoneDependency", "Triggering"),
    ("SuccessorOf", "Triggering"),
    ("ProjectSequence", "Triggering"),
    ("ArchitecturalSequence", "Triggering"),
    ("IsResponsibleFor", "Assignment"),
    ("IsAccountableFor", "Assignment"),
    ("HostedOn", "Assignment"),
    ("Evaluates", "Association"),  # Guide sagt Realization, Matrix erlaubt sie nicht
    # Neu explizit statt Default Serving (Audit Nr. 10)
    ("ConflictsWith", "Association"),
    ("SameAs", "Association"),
    ("IsDuplicateOf", "Association"),
    ("Replaces", "Association"),
    ("Refines", "Association"),
    ("Requires", "Association"),
    ("ResultsFrom", "Association"),
    ("trace", "Association"),
    ("VersionReleased", "Association"),
    ("VersionWithdrawn", "Association"),
    ("ResourceConnector", "Association"),
]


@pytest.mark.parametrize("stereo,erwartet", BEZIEHUNGS_REGELN)
def test_beziehungs_regel_liefert_guide_relation(stereo: str, erwartet: str) -> None:
    assert archimate_writer.RELATIONSHIP_MAP[stereo] == erwartet


def test_unbekannte_dependency_wird_nicht_mehr_serving() -> None:
    """Audit Nr. 10: 82 Stereotype fielen auf Serving; der Default ist neutral."""
    assert archimate_writer.TYPE_MAP["Dependency"] == "Association"
    typ, _, _ = _kante("BusinessActor", "BusinessProcess", stereo="VoelligNeuerStereotyp")
    assert typ == "Association"


def test_jede_beziehungs_regel_liegt_im_xsd_typsystem() -> None:
    unbekannt = {
        stereo: rel
        for stereo, rel in archimate_writer.RELATIONSHIP_MAP.items()
        if rel not in archimate_writer.ARCHIMATE_RELATIONSHIP_TYPES
    }
    assert unbekannt == {}


# --------------------------------------------------------------------------
# 3. Matrix-Anwendung
# --------------------------------------------------------------------------
def test_association_ist_laut_matrix_fuer_alle_erzeugten_paare_erlaubt() -> None:
    """Grundlage des Association-Kurzschlusses (Audit T2, Abschnitt 3.2)."""
    matrix = archimate_writer.load_matrix()
    for quelle in archimate_writer.ARCHIMATE_ELEMENT_TYPES:
        for ziel in archimate_writer.ARCHIMATE_ELEMENT_TYPES:
            assert archimate_writer._erlaubt(matrix, quelle, "Association", ziel)


def test_konforme_kante_bleibt_unveraendert() -> None:
    typ, von_q, _ = _kante("BusinessProcess", "Capability", stereo="Implements")
    assert typ == "Realization"
    assert von_q


def test_richtung_wird_invertiert_wenn_nur_die_gegenrichtung_legal_ist() -> None:
    """Audit Nr. 12: ToBeRealizedBy zeigt im Modell verkehrt herum."""
    ir = _ir(
        [
            {"ref": "P::Q", "package": "P", "name": "Q", "ea_type": "Requirement"},
            {"ref": "P::Z", "package": "P", "name": "Z", "ea_type": "Artifact"},
        ],
        [{"source": "P::Q", "target": "P::Z", "stereotype": "ToBeRealizedBy",
          "ea_type": "Dependency"}],
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_invert.xml")
    root = ET.fromstring(Path("/tmp/archimate_t3_invert.xml").read_bytes())
    ids = {e.find(f"{NS}name").text: e.get("identifier") for e in root.iter(f"{NS}element")}
    kante = next(root.iter(f"{NS}relationship"))
    assert kante.get(XSI + "type") == "Realization"
    assert kante.get("source") == ids["Z"] and kante.get("target") == ids["Q"]
    assert report.inverted == 1
    assert report.remapped == 0
    assert report.inverted_by_type == {"ToBeRealizedBy": 1}
    assert report.inverted_samples[0]["von_quelle"] == "Requirement"


def test_justified_by_wird_influence_und_dabei_invertiert() -> None:
    """Der Begruender beeinflusst das Begruendete (Guide: Influence)."""
    typ, von_q, _ = _kante("Requirement", "BusinessActor", stereo="JustifiedBy")
    assert typ == "Influence"
    assert not von_q  # Kante wurde gedreht: BusinessActor -> Requirement


def test_influence_und_assignment_entstehen_aus_admbw_eingaben() -> None:
    """Audit Nr. 15: beide Relationen kamen vorher null Mal vor."""
    assert _kante("Representation", "Driver", stereo="ConcernForView")[0] == "Influence"
    assert _kante("BusinessActor", "BusinessProcess", stereo="IsResponsibleFor")[0] == "Assignment"


def test_access_aus_dem_austauschformat_bleibt_erhalten() -> None:
    """Audit Nr. 15: ADMBw kennt keinen Zugriffs-Stereotyp (MDG 2026.05).

    ``Access`` entsteht daher nur auf dem Rueckweg XML -> IR -> XML; die
    Identitaetsregel in ``TYPE_MAP`` darf ihn nicht verlieren.
    """
    typ, von_q, _ = _kante("ApplicationComponent", "DataObject", ea_type="Access")
    assert typ == "Access"
    assert von_q


def test_fallback_waehlt_die_semantisch_naechste_relation() -> None:
    """Audit Nr. 11: nicht blind die erste legale Relation."""
    matrix = {
        ("A", "Assignment"): {"Z"},
        ("A", "Realization"): {"Z"},
        ("A", "Aggregation"): {"Z"},
    }
    assert archimate_writer._naechste_legale(matrix, "A", "Serving", "Z") == "Assignment"
    assert archimate_writer._naechste_legale(matrix, "A", "Composition", "Z") == "Aggregation"
    # Eine Realisierung wird nie als Generalisierung ausgegeben: Specialization
    # steht nicht in der Praeferenzliste, Assignment ist die naechste legale.
    gewaehlt = archimate_writer._naechste_legale(matrix, "A", "Realization", "Z")
    assert gewaehlt == "Assignment" and gewaehlt != "Specialization"


def test_fallback_ist_immer_matrix_legal() -> None:
    matrix = archimate_writer.load_matrix()
    for rel in archimate_writer.ARCHIMATE_RELATIONSHIP_TYPES:
        gewaehlt = archimate_writer._naechste_legale(matrix, "Artifact", rel, "Contract")
        assert archimate_writer._erlaubt(matrix, "Artifact", gewaehlt, "Contract"), rel


def test_umgebaute_kante_erscheint_in_der_remap_matrix() -> None:
    """Audit Nr. 11: Zaehlung je (von, nach, Quelltyp, Zieltyp) statt 10 Samples."""
    ir = _ir(
        [
            {"ref": "P::Q", "package": "P", "name": "Q", "ea_type": "Product"},
            {"ref": "P::Z", "package": "P", "name": "Z", "ea_type": "Contract"},
        ],
        [{"source": "P::Q", "target": "P::Z", "stereotype": "Satisfy",
          "ea_type": "Dependency"}],
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_remap.xml")
    assert report.remapped == 1
    assert report.remapped_by_relation == {"Realization": 1}
    assert report.remaps == {"Realization->Association": 1}
    assert report.remap_by_type == {"Realization->Association|Product->Contract": 1}


# --------------------------------------------------------------------------
# 4. Report: jede Naeherung sichtbar (Audit T2, Abschnitt 4.2)
# --------------------------------------------------------------------------
def test_selbstkanten_werden_gezaehlt() -> None:
    ir = _ir(
        [
            _element("P::System", stereo="System"),
            _element("P::Port", typ="Port", stereo="ResourcePort", owner="P::System"),
        ],
        [{"source": "P::Port", "target": "P::System", "stereotype": "",
          "ea_type": "InformationFlow"}],
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_self.xml")
    assert report.self_edges == 1
    assert report.self_edges_by_type == {"InformationFlow": 1}
    assert report.relationships == 0


def test_duplikate_werden_gezaehlt() -> None:
    ir = _ir(
        [_element("P::A", stereo="Capability"), _element("P::B", stereo="System")],
        [
            {"source": "P::A", "target": "P::B", "stereotype": "", "ea_type": "Association"},
            {"source": "P::A", "target": "P::B", "stereotype": "", "ea_type": "Association"},
        ],
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_dup.xml")
    assert report.relationships == 1
    assert report.duplicates == 1
    assert report.duplicates_by_relation == {"Association": 1}


def test_notelinks_werden_gezaehlt_und_nicht_als_unresolved() -> None:
    ir = _ir(
        [_element("P::A", stereo="Capability"), _element("P::B", stereo="System")],
        [{"source": "P::A", "target": "P::B", "stereotype": "", "ea_type": "NoteLink"}],
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_note.xml")
    assert report.note_links == 1
    assert report.unresolved == 0
    assert report.skipped_connector == 0


def test_beziehung_ohne_regel_wird_gezaehlt() -> None:
    ir = _ir(
        [_element("P::A", stereo="Capability"), _element("P::B", stereo="System")],
        [{"source": "P::A", "target": "P::B", "stereotype": "", "ea_type": "Unbekannt"}],
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_unbekannt.xml")
    assert report.skipped_connector == 1
    assert report.skipped_connector_by_type == {"Unbekannt": 1}


def test_darstellung_und_fachmechanik_werden_getrennt_gezaehlt() -> None:
    """Audit Nr. 14: 327 war ein Sammelzaehler fuer zwei verschiedene Verluste."""
    ir = _ir(
        [
            _element("P::A", stereo="Capability"),
            _element("P::Notiz", typ="Note"),
            _element("P::Text", typ="Text"),
            _element("P::Entscheidung", typ="Decision"),
            _element("P::Teil", typ="ActivityPartition"),
        ]
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_skip.xml")
    assert report.skipped_display == 2
    assert report.skipped_display_by_type == {"note": 1, "text": 1}
    assert report.skipped_fachlich == 2
    assert report.skipped_fachlich_by_type == {"decision": 1, "activitypartition": 1}


def test_darstellungs_endpunkt_ist_kein_fachlicher_verlust() -> None:
    """Audit Abschnitt 4.1: die Text-Kante war falsch als unresolved verbucht."""
    ir = _ir(
        [_element("P::A", stereo="Capability"), _element("P::Text", typ="Text")],
        [{"source": "P::Text", "target": "P::A", "stereotype": "", "ea_type": "Realisation"}],
    )
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_text.xml")
    assert report.unresolved == 0
    assert report.unresolved_display == 1


def test_pakete_werden_vollstaendig_gezaehlt() -> None:
    """Audit Nr. 17: skipped_package war tot, 222 Pakete blieben unsichtbar."""
    ir = _ir([_element("P::A", stereo="Capability")])
    ir["packages"] = [{"path": "P"}, {"path": "P::X"}, {"path": "P::Y"}]
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_pkg.xml")
    assert report.packages == 3
    assert report.packages_emitted == 0
    assert report.packages_not_emitted == 3


def test_unmapped_und_remap_samples_stehen_im_cli_report(tmp_path: Path, capsys) -> None:
    """Audit Nr. 16: der CLI-Report verschwieg unmapped und remap_samples."""
    ir = _ir(
        [
            {"ref": "P::Q", "package": "P", "name": "Q", "ea_type": "Product"},
            {"ref": "P::Z", "package": "P", "name": "Z", "ea_type": "Contract"},
            {"ref": "P::Fremd", "package": "P", "name": "Fremd", "ea_type": "FremdTyp"},
        ],
        [{"source": "P::Q", "target": "P::Z", "stereotype": "Satisfy",
          "ea_type": "Dependency"}],
    )
    quelle = tmp_path / "ir.json"
    ziel = tmp_path / "modell.xml"
    bericht = tmp_path / "report.json"
    quelle.write_text(json.dumps(ir), encoding="utf-8")

    assert archimate_writer.main(["--ir", str(quelle), "--out", str(ziel),
                                  "--report", str(bericht)]) == 0
    daten = json.loads(bericht.read_text(encoding="utf-8"))
    assert daten["unmapped"] == [
        {"ref": "P::Fremd", "name": "Fremd", "ea_type": "fremdtyp", "stereotype": ""}
    ]
    assert daten["remapped"] == 1
    assert daten["remap_samples"][0]["von"] == "Realization"
    assert "unmapped" in capsys.readouterr().out


def test_report_as_dict_ist_json_faehig() -> None:
    ir = _ir([_element("P::A", stereo="Capability")])
    report = archimate_writer.write_archimate(ir, "/tmp/archimate_t3_dict.xml")
    daten = report.as_dict()
    assert json.loads(json.dumps(daten))["elements"] == 1
    assert daten["approximations"] == {}
    assert daten["remap_by_type"] == {}


# --------------------------------------------------------------------------
# 5. Messmodell MASC: Kennzahlen vor/nach (Audit T2, Abschnitt 1)
# --------------------------------------------------------------------------
@pytest.mark.skipif(not MASC.is_file(), reason="Musterarchitektur_MASC.qea fehlt")
def test_masc_kennzahlen_nach_der_korrektur(tmp_path: Path) -> None:
    ir, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    bericht = archimate_writer.write_archimate(ir, tmp_path / "masc.xml", modellname="MASC")

    # vorher (Audit T2): 984 Elemente, 1526 Kanten, 116 Umbauten, 100 offen
    assert bericht.elements == 1019          # +35 Zustand/Zustandsknoten/Ereignis
    assert bericht.relationships == 1569     # +43 aufgeloeste Kanten
    assert bericht.remapped == 38            # 116 -> 38
    assert bericht.unresolved == 51          # 100 -> 51 (48 Mechanik + 3 Paket)
    assert bericht.unresolved_display == 1   # die eine Text-Kante, korrekt verbucht
    assert bericht.inverted == 28            # 13 Audit-Faelle + 22 JustifiedBy - 7
    assert bericht.collapsed == 122
    assert bericht.self_edges == 64
    assert bericht.note_links == 14
    assert bericht.skipped_display == 265
    assert bericht.skipped_fachlich == 27
    assert bericht.packages == 226
    assert bericht.packages_not_emitted == 222

    # Der Guide verlangt diese Relationen; vorher kamen sie null Mal vor.
    assert bericht.by_relation.get("Influence", 0) == 336
    assert bericht.by_relation.get("Assignment", 0) == 11
    assert bericht.by_type["BusinessEvent"] == 35
    assert "Constraint" not in bericht.by_type
    assert bericht.by_type["Contract"] == 49
    assert bericht.by_type["Representation"] == 163
    assert bericht.by_type["ImplementationEvent"] == 27


@pytest.mark.skipif(not MASC.is_file(), reason="Musterarchitektur_MASC.qea fehlt")
def test_masc_ausgabe_bleibt_deterministisch_und_typsystem_treu(tmp_path: Path) -> None:
    ir, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    archimate_writer.write_archimate(ir, tmp_path / "a.xml", modellname="MASC")
    archimate_writer.write_archimate(ir, tmp_path / "b.xml", modellname="MASC")
    einmal = (tmp_path / "a.xml").read_bytes()
    assert einmal == (tmp_path / "b.xml").read_bytes()

    root = ET.fromstring(einmal)
    typen = [e.get(XSI + "type") for e in root.iter(f"{NS}element")]
    assert set(typen) <= archimate_writer.ARCHIMATE_ELEMENT_TYPES
    rels = [e.get(XSI + "type") for e in root.iter(f"{NS}relationship")]
    assert set(rels) <= archimate_writer.ARCHIMATE_RELATIONSHIP_TYPES

    ids = {e.get("identifier") for e in root.iter(f"{NS}element")}
    assert len(ids) == len(typen)
    for kante in root.iter(f"{NS}relationship"):
        assert kante.get("source") in ids and kante.get("target") in ids
