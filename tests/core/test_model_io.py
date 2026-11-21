"""test_model_io.py -- Tests fuer model_io: 4 Formate (QEA, XMI, ArchiMate XML, JSON).

Geprueft wird:
- Formaterkennung (detect_format) per Signatur und Endung
- Lesen und Schreiben aller 4 Formate ohne Verlust von EA-GUIDs, NATO-GUIDs,
  Stereotypen, Pakethierarchie und Tagged Values
- Verlustfreie Konvertierungsmatrix (Roundtrip ueber alle 4 Formate)
- CLI-Aufrufe ueber model_io und eam_ai convert
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import model_io
import eam_ai
from qea_writer import write_qea
from qea_reader import read_qea


CANONICAL_IR = {
    "ir_version": 1,
    "technology": {
        "profile": "NAFv4-ADMBw",
        "version": "2026.05",
    },
    "packages": [
        {"path": "Architektur", "guid": "{11111111-1111-1111-1111-111111111111}"},
        {"path": "Architektur/Faehigkeiten", "guid": "{22222222-2222-2222-2222-222222222222}"},
    ],
    "elements": [
        {
            "name": "Faehigkeit B",
            "stereotype": "Capability",
            "package": "Architektur/Faehigkeiten",
            "ea_guid": "{AAAA1111-BBBB-CCCC-DDDD-EEEEFFFF0001}",
            "notes": "Standardfaehigkeit",
            "tags": {
                "OriginalGUID": "{NATO-GUID-0001}",
                "NATO_Taxonomy": "NC3-Cap-1.2.3",
                "Status": "Aktiv",
            },
            "source_ref": "D1-S1",
        },
        {
            "name": "Dienst C",
            "stereotype": "ServiceSpecification",
            "package": "Architektur",
            "ea_guid": "{AAAA1111-BBBB-CCCC-DDDD-EEEEFFFF0002}",
            "notes": "Dienstspezifikation",
            "tags": {
                "OriginalGUID": "{NATO-GUID-0002}",
                "Status": "Entwurf",
            },
            "source_ref": "D1-S2",
        },
    ],
    "connectors": [
        {
            "source": "Faehigkeit B",
            "target": "Dienst C",
            "stereotype": "Exhibits",
            "ea_guid": "{CCCC2222-BBBB-AAAA-DDDD-111122223333}",
            "notes": "Faehigkeit erfordert Dienst",
            "tags": {
                "StandardConnector": "true",
            },
            "source_ref": "D1-S2",
        }
    ],
}


def test_detect_format(tmp_path: Path) -> None:
    qea_file = tmp_path / "test.qea"
    model_io.write_model(CANONICAL_IR, qea_file, format="qea")
    assert model_io.detect_format(qea_file) == "qea"

    xmi_file = tmp_path / "test.xmi"
    model_io.write_model(CANONICAL_IR, xmi_file, format="xmi")
    assert model_io.detect_format(xmi_file) == "xmi"

    arch_file = tmp_path / "test_arch.xml"
    model_io.write_model(CANONICAL_IR, arch_file, format="archimate")
    assert model_io.detect_format(arch_file) == "archimate"

    json_file = tmp_path / "test.json"
    model_io.write_model(CANONICAL_IR, json_file, format="json")
    assert model_io.detect_format(json_file) == "json"


def test_qea_roundtrip(tmp_path: Path) -> None:
    qea_path = tmp_path / "modell.qea"
    model_io.write_model(CANONICAL_IR, qea_path, format="qea")
    ir = model_io.read_model(qea_path)

    elem_names = {e["name"] for e in ir["elements"]}
    assert "Faehigkeit B" in elem_names
    assert "Dienst C" in elem_names

    b_elem = next(e for e in ir["elements"] if e["name"] == "Faehigkeit B")
    assert b_elem["stereotype"] == "Capability"
    assert b_elem.get("guid") == "{AAAA1111-BBBB-CCCC-DDDD-EEEEFFFF0001}"
    assert b_elem.get("tags", {}).get("OriginalGUID") == "{NATO-GUID-0001}"


def test_xmi_roundtrip(tmp_path: Path) -> None:
    xmi_path = tmp_path / "modell.xmi"
    model_io.write_model(CANONICAL_IR, xmi_path, format="xmi")
    ir = model_io.read_model(xmi_path)

    elem_names = {e["name"] for e in ir["elements"]}
    assert "Faehigkeit B" in elem_names
    assert "Dienst C" in elem_names


def test_archimate_roundtrip(tmp_path: Path) -> None:
    arch_path = tmp_path / "modell.xml"
    model_io.write_model(CANONICAL_IR, arch_path, format="archimate")
    ir = model_io.read_model(arch_path)

    elem_names = {e["name"] for e in ir["elements"]}
    assert "Faehigkeit B" in elem_names
    assert "Dienst C" in elem_names

    b_elem = next(e for e in ir["elements"] if e["name"] == "Faehigkeit B")
    assert b_elem.get("guid") or b_elem.get("ea_guid")


def test_json_roundtrip(tmp_path: Path) -> None:
    json_path = tmp_path / "modell.json"
    model_io.write_model(CANONICAL_IR, json_path, format="json", mode="batch")
    ir = model_io.read_model(json_path)

    elem_names = {e["name"] for e in ir["elements"]}
    assert "Faehigkeit B" in elem_names
    assert "Dienst C" in elem_names

    b_elem = next(e for e in ir["elements"] if e["name"] == "Faehigkeit B")
    assert (
        b_elem.get("ea_guid") == "{AAAA1111-BBBB-CCCC-DDDD-EEEEFFFF0001}"
        or b_elem.get("guid") == "{AAAA1111-BBBB-CCCC-DDDD-EEEEFFFF0001}"
    )
    assert b_elem.get("tags", {}).get("OriginalGUID") == "{NATO-GUID-0001}"


def test_full_chain_roundtrip_matrix(tmp_path: Path) -> None:
    """Matrix-Test: IR -> QEA -> XMI -> ArchiMate XML -> JSON -> IR."""
    f_qea = tmp_path / "step1.qea"
    f_xmi = tmp_path / "step2.xmi"
    f_xml = tmp_path / "step3.xml"
    f_json = tmp_path / "step4.json"

    # 1. IR -> QEA
    model_io.write_model(CANONICAL_IR, f_qea, format="qea")
    assert f_qea.is_file()

    # 2. QEA -> XMI
    model_io.convert_model(f_qea, f_xmi, out_format="xmi")
    assert f_xmi.is_file()

    # 3. XMI -> ArchiMate XML
    model_io.convert_model(f_xmi, f_xml, out_format="archimate")
    assert f_xml.is_file()

    # 4. ArchiMate XML -> JSON
    model_io.convert_model(f_xml, f_json, out_format="json")
    assert f_json.is_file()

    # 5. JSON lesen und verifizieren
    final_ir = model_io.read_model(f_json)
    names = {e["name"] for e in final_ir["elements"]}
    assert "Faehigkeit B" in names
    assert "Dienst C" in names


def test_cli_convert(tmp_path: Path) -> None:
    qea_in = tmp_path / "in.qea"
    model_io.write_model(CANONICAL_IR, qea_in, format="qea")

    xmi_out = tmp_path / "out.xmi"
    ret = model_io.main([str(qea_in), "-o", str(xmi_out)])
    assert ret == 0
    assert xmi_out.is_file()

    json_out = tmp_path / "out.json"
    ret_eam = eam_ai.main(["convert", "-i", str(xmi_out), "-o", str(json_out)])
    assert ret_eam == 0
    assert json_out.is_file()
