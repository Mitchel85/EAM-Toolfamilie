"""JSON-Batch als Zielformat: Schema, Determinismus, Endpunkte.

``.json`` ist ein Ausgabeformat wie ``.qea`` und ``.xmi``: dasselbe IR,
dasselbe Gate. Der Batch ist ein Graph (``nodes``/``edges``), verbindlich
gegen ``packages/core/batch-schema.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import json_batch
from qea_reader import read_qea

CORE = Path(__file__).resolve().parents[2] / "packages" / "core"
FIXTURES = CORE / "fixtures"
SCHEMA = json.loads((CORE / "batch-schema.json").read_text(encoding="utf-8"))


def _lade(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_altbeispiel_validiert_weiter() -> None:
    """Das ADMBw-Beispiel bleibt gegen das generische Schema gueltig."""
    beispiel = json.loads(
        (FIXTURES / "batch-output-example.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(beispiel, SCHEMA)


def test_export_validiert_und_ist_deterministisch() -> None:
    ir = _lade("ir_synthetic_mini.json")
    text1 = json_batch.render_text(ir, source_document="mini.txt")
    text2 = json_batch.render_text(ir, source_document="mini.txt")
    assert text1 == text2
    jsonschema.validate(json.loads(text1), SCHEMA)


def test_zaehler_sind_gezaehlt_nicht_behauptet() -> None:
    ir = _lade("ir_roundtrip_mini.json")
    daten = json.loads(json_batch.render_text(ir, source_document="mini.txt"))
    assert daten["metadata"]["node_count"] == len(daten["nodes"])
    assert daten["metadata"]["edge_count"] == len(daten["edges"])


def test_alle_endpunkte_zeigen_auf_knoten() -> None:
    ir = _lade("ir_synthetic_mini.json")
    daten = json.loads(json_batch.render_text(ir, source_document="mini.txt"))
    ids = {n["id"] for n in daten["nodes"]}
    for kante in daten["edges"]:
        assert kante["source_id"] in ids, kante
        assert kante["target_id"] in ids, kante


def test_pakete_sind_knoten() -> None:
    """Beziehungen koennen an Paketen enden -- ohne Paketknoten ginge die
    Kante verloren."""
    ir = _lade("ir_roundtrip_mini.json")
    daten = json.loads(json_batch.render_text(ir, source_document="mini.txt"))
    pakete = [n for n in daten["nodes"] if n["metaclass"] == "Package"]
    assert len(pakete) == len(ir["packages"])
    for paket in pakete:
        assert paket["name"]


def test_elementknoten_tragen_den_paketpfad() -> None:
    """Ohne `package` waere der Paketbaum beim Import nicht wiederherstellbar."""
    ir = _lade("ir_roundtrip_mini.json")
    daten = json.loads(json_batch.render_text(ir, source_document="mini.txt"))
    elemente = [n for n in daten["nodes"] if n["metaclass"] != "Package"]
    assert elemente
    for knoten in elemente:
        assert knoten.get("package"), knoten
        assert "/" in knoten["package"] or knoten["package"]


def test_leeres_source_document_bricht_ab() -> None:
    with pytest.raises(json_batch.JsonBatchError):
        json_batch.render_text(_lade("ir_roundtrip_mini.json"), source_document="  ")


def test_kanten_typ_ist_upper_snake() -> None:
    assert json_batch._upper_snake("CapabilityDependency") == "CAPABILITY_DEPENDENCY"
    assert json_batch._upper_snake("Dependency") == "DEPENDENCY"
    assert json_batch._upper_snake("Provides") == "PROVIDES"


def test_querformat_masc_export(tmp_path: Path) -> None:
    qea_pfad = FIXTURES / "Musterarchitektur_MASC.qea"
    if not qea_pfad.is_file():
        pytest.skip("MASC-Fixture fehlt")
    ir = read_qea(qea_pfad)
    pfad = tmp_path / "masc.json"
    json_batch.write_json_batch(ir, pfad, source_document="MASC")
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    jsonschema.validate(daten, SCHEMA)
    ids = {n["id"] for n in daten["nodes"]}
    assert len(ids) == daten["metadata"]["node_count"]
    assert all(e["source_id"] in ids and e["target_id"] in ids for e in daten["edges"])
    assert daten["metadata"]["standard"] == "NAFv4-ADMBw"
