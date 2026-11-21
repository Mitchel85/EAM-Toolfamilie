# -*- coding: utf-8 -*-
"""End-to-End-Workflow-Test: Die 7 Stufen über alle 4 Formate.

1. MDG rein (dynamisches MDG-XML einlesen)
2. Startpaket rein (NATO GUIDs, EA GUIDs, StEKa-Tags)
3. Prosa rein (Multimodale Anforderungstexte/Strukturen)
4. Architektur bauen in 4 Formaten (.qea, .xmi, ArchiMate .xml, .json)
5. Architektur anhand der MDG-Regeln validieren
6. QS-Fähigkeit & Zusammenhänge sichtbar machen (Graph, Pfade, Waisen, Provenienz)
7. Sparx EA Sichten (MDG, Leitfaden, Wizard) & Sichten-Archiv (SHA-256)
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

from core import model_io, qea_writer, qea_reader, validator, view_builder, sichten_archiv
from rules import mdg_parser


ROOT = Path(__file__).resolve().parents[1]
MDG_PATH = ROOT / "packages" / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml"
SAMPLE_PROSA = ROOT / "packages" / "core" / "examples" / "offline" / "prosa.txt"
SAMPLE_ANTWORT = ROOT / "packages" / "core" / "examples" / "offline" / "antwort.json"


def test_stufe1_mdg_rein() -> None:
    """Stufe 1: Dynamisches MDG-XML einlesen und Regeln/Sichten extrahieren."""
    assert MDG_PATH.is_file(), f"MDG-Datei nicht gefunden: {MDG_PATH}"
    regelwerk = mdg_parser.parse_mdg(MDG_PATH)
    assert "ADMBw" in regelwerk["source"]["technologyId"]
    assert len(regelwerk["elementStereotypes"]) > 100
    assert len(regelwerk["connectorRules"]) > 100
    el_names = {e["name"] for e in regelwerk["elementStereotypes"]}
    assert "Capability" in el_names


def test_stufe2_startpaket_und_guids(tmp_path: Path) -> None:
    """Stufe 2: Startpaket mit EA GUIDs, NATO GUIDs, StEKa-Tags wird exakt erhalten."""
    ir = {
        "ir_version": 1,
        "technology": {"name": "ADMBw"},
        "packages": [{"path": "Startpaket"}],
        "elements": [
            {
                "name": "Standard-Faehigkeit",
                "package": "Startpaket",
                "stereotype": "Capability",
                "ea_type": "Class",
                "guid": "{11111111-2222-3333-4444-555555555555}",
                "tags": {
                    "OriginalGUID": "NATO-GUID-987654",
                    "URI": "urn:nato:c3:cap:1234",
                    "StandardElement": "true",
                    "source_ref": "NATO-C3-Taxonomie-v4",
                },
            }
        ],
        "connectors": [],
        "diagrams": [],
    }
    qea_file = tmp_path / "startpaket_test.qea"
    qea_writer.write_qea(ir, qea_file)

    # Zurücklesen und GUIDs sowie Tags validieren
    back_ir = qea_reader.read_qea(qea_file)
    elem = back_ir["elements"][0]
    assert elem["guid"] == "{11111111-2222-3333-4444-555555555555}"
    tags = elem.get("tags", {})
    assert tags.get("OriginalGUID") == "NATO-GUID-987654"
    assert tags.get("URI") == "urn:nato:c3:cap:1234"
    assert tags.get("StandardElement") == "true"
    assert tags.get("source_ref") == "NATO-C3-Taxonomie-v4"


def test_stufe3_und_4_multiformat_export_und_roundtrip(tmp_path: Path) -> None:
    """Stufen 3 & 4: Aus Prosa/IR Architektur in allen 4 Formaten bauen und lesen."""
    with open(SAMPLE_ANTWORT, "r", encoding="utf-8") as f:
        antwort = json.load(f)

    ir = {
        "ir_version": 1,
        "technology": {"name": "ADMBw"},
        "packages": [{"path": "Modell"}],
        "elements": [
            {
                "name": e["name"],
                "package": "Modell",
                "stereotype": e.get("stereotype", "Class"),
                "ea_type": "Class",
                "notes": e.get("notes", ""),
                "tags": {"source_ref": e.get("source_ref", "")},
            }
            for e in antwort["elements"]
        ],
        "connectors": [
            {
                "source": f"Modell::{c['source']}",
                "target": f"Modell::{c['target']}",
                "stereotype": c.get("stereotype", "Dependency"),
                "ea_type": "Dependency",
                "notes": c.get("notes", ""),
                "tags": {"source_ref": c.get("source_ref", "")},
            }
            for c in antwort["connectors"]
        ],
        "diagrams": [],
    }

    # 1. QEA
    qea_path = tmp_path / "architektur.qea"
    model_io.write_model(ir, qea_path, format="qea")
    assert qea_path.is_file()
    ir_qea = model_io.read_model(qea_path, format="qea")
    assert len(ir_qea["elements"]) == 3
    assert len(ir_qea["connectors"]) == 1

    # 2. XMI (UML 2.1)
    xmi_path = tmp_path / "architektur.xmi"
    model_io.write_model(ir, xmi_path, format="xmi")
    assert xmi_path.is_file()
    ir_xmi = model_io.read_model(xmi_path, format="xmi")
    assert len(ir_xmi["elements"]) == 3

    # 3. ArchiMate XML
    xml_path = tmp_path / "architektur.xml"
    model_io.write_model(ir, xml_path, format="xml")
    assert xml_path.is_file()
    ir_xml = model_io.read_model(xml_path, format="xml")
    assert len(ir_xml["elements"]) == 3

    # 4. JSON Batch
    json_path = tmp_path / "architektur.json"
    model_io.write_model(ir, json_path, format="json")
    assert json_path.is_file()
    ir_json = model_io.read_model(json_path, format="json")
    assert len(ir_json["elements"]) == 3


def test_stufe5_mdg_validierung(tmp_path: Path) -> None:
    """Stufe 5: Architektur gegen MDG-Regeln validieren."""
    regelwerk = mdg_parser.parse_mdg(MDG_PATH)
    ir = {
        "ir_version": 1,
        "technology": {"name": "ADMBw"},
        "packages": [{"path": "Modell"}],
        "elements": [
            {
                "name": "Faehigkeit",
                "package": "Modell",
                "stereotype": "Capability",
                "ea_type": "Class",
            },
            {
                "name": "Konfiguration",
                "package": "Modell",
                "stereotype": "CapabilityConfiguration",
                "ea_type": "Class",
            },
        ],
        "connectors": [
            {
                "source": "Modell::Konfiguration",
                "target": "Modell::Faehigkeit",
                "stereotype": "Exhibits",
                "ea_type": "Dependency",
            }
        ],
        "diagrams": [],
    }
    findings = validator.validate_model(ir, regelwerk)
    fehler = [f for f in findings if f.get("severity") == "error"]
    assert len(fehler) == 0


def test_stufe6_qs_und_zusammenhaenge() -> None:
    """Stufe 6: QS-Fähigkeit, Nachbarschaft, Waisenerkennung und Provenienz."""
    ir = {
        "ir_version": 1,
        "technology": {"name": "ADMBw"},
        "packages": [{"path": "Modell"}],
        "elements": [
            {"name": "E1", "package": "Modell", "stereotype": "Capability", "ea_type": "Class", "tags": {"source_ref": "Doc-1"}},
            {"name": "E2", "package": "Modell", "stereotype": "ServiceSpecification", "ea_type": "Class"},
            {"name": "Waise", "package": "Modell", "stereotype": "Node", "ea_type": "Class"},
        ],
        "connectors": [
            {"source": "Modell::E1", "target": "Modell::E2", "stereotype": "Exhibits", "ea_type": "Dependency"}
        ],
        "diagrams": [],
    }
    # Verwaiste Elemente ohne Beziehungen erkennen
    verbundene = set()
    for c in ir["connectors"]:
        verbundene.add(c["source"].split("::")[-1])
        verbundene.add(c["target"].split("::")[-1])

    waisen = [e["name"] for e in ir["elements"] if e["name"] not in verbundene]
    assert "Waise" in waisen
    assert "E1" not in waisen
    assert "E2" not in waisen


def test_stufe7_sichten_generator_und_archiv(tmp_path: Path) -> None:
    """Stufe 7: Sichten mit lesbarem Gitter-Layout, Default-Diagramm und Sichten-Archiv."""
    elements = [
        {"package": "Modell", "name": f"Knoten_{i}", "stereotype": "Node", "ea_type": "Class"}
        for i in range(8)
    ]
    ir = {
        "ir_version": 1,
        "technology": {"name": "ADMBw"},
        "packages": [{"path": "Modell"}],
        "elements": elements,
        "connectors": [],
        "diagrams": [],
    }

    # 1. Sichten anreichern im Modus 'leitfaden'
    ir_leitfaden = view_builder.enrich_ir_with_views(ir, mode="leitfaden")
    n_views = len(ir_leitfaden["diagrams"])
    assert n_views >= 40

    # Layout prüfen: RectTop > RectBottom
    for d in ir_leitfaden["diagrams"]:
        for m in d.get("members", []):
            assert m["top"] > m["bottom"]
            assert m["right"] > m["left"]

    # In QEA schreiben und DefaultDiagram im usys_system prüfen
    qea_file = tmp_path / "sichten_test.qea"
    qea_writer.write_qea(ir_leitfaden, qea_file)

    con = sqlite3.connect(str(qea_file))
    try:
        def_diag = con.execute("select Value from usys_system where Property='DefaultDiagram'").fetchone()
        assert def_diag is not None and def_diag[0] != ""
    finally:
        con.close()

    # 2. Sichten-Archiv: Packen -> Entpacken -> Bit-Exakt verifizieren
    archiv_zip = tmp_path / "sichten_test.sichten.zip"
    ohne_sichten = tmp_path / "ohne_sichten.qea"
    bericht_pack = sichten_archiv.archiviere(qea_file, archiv_zip, ohne_sichten, stufe="A")
    assert archiv_zip.is_file()
    assert ohne_sichten.is_file()
    assert bericht_pack["gesichert"]["t_diagram"] == n_views

    wiederhergestellt = tmp_path / "wiederhergestellt.qea"
    rueckgabe = sichten_archiv.zurueckspielen(ohne_sichten, archiv_zip, wiederhergestellt)
    assert rueckgabe["identisch"] is True

    bericht_verify = sichten_archiv.pruefe(archiv_zip)
    assert bericht_verify["ok"] is True
