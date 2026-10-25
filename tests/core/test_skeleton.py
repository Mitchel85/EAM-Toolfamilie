"""Tests fuer das Geruest allein aus dem MDG-Regelwerk.

Kern des Auftrags: ohne Text und ohne Backend entsteht aus dem Regelwerk ein
Modell, das die MDG-Pruefung mit **null Fehlern** besteht. Die Tests pruefen
zusaetzlich, dass dabei nichts erfunden wird (nur Regelwerk-Namen), dass kein
Modellaufruf stattfindet und dass der Lauf deterministisch ist.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import eam_ai
import mdg_parser
import skeleton
import validator
from qea_reader import read_qea

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"  # Monorepo
MDG = FIXTURES / "admbw_auszug.xml"
import mdg_source  # noqa: E402

REAL_MDG = mdg_source.path()


def _rules() -> dict:
    return mdg_parser.parse_mdg(MDG)


def _findings(ir: dict, rules: dict) -> list[dict]:
    return validator.validate_model(ir, validator.build_rules(rules))


def test_geruest_aus_regelwerk_besteht_die_mdg_pruefung() -> None:
    rules = _rules()
    ir = skeleton.build_skeleton(rules)

    assert ir["ir_version"] == 1
    assert [paket["path"] for paket in ir["packages"]] == [
        "NAFv4-ADMBw",
        "NAFv4-ADMBw/Class",
    ]
    names = {element["name"] for element in ir["elements"]}
    assert names == {
        "ActualProject",
        "Capability",
        "OperationalActivity",
        "Process",
        "ServiceSpecification",
    }
    assert "MeasurableElement" not in names, "abstrakte Stereotype sind kein Geruest"
    for element in ir["elements"]:
        assert element["package"] == "NAFv4-ADMBw/Class"
        assert element["stereotype"] == element["name"]
        assert element["ea_type"] == "Class"
        assert element["notes"].strip()
    assert ir["meta"]["extraction"]["backend"] == skeleton.SKELETON_BACKEND

    findings = _findings(ir, rules)
    assert validator.summarize(findings) == {
        "total": 0,
        "error": 0,
        "warning": 0,
    }


def test_geruest_nennt_nur_was_im_regelwerk_steht() -> None:
    rules = _rules()
    ir = skeleton.build_skeleton(rules)
    erlaubt = {entry["name"] for entry in rules["elementStereotypes"]}
    bekannt = {entry["stereotype"] for entry in rules["connectorRules"]}

    for element in ir["elements"]:
        assert element["name"] in erlaubt
        assert element["stereotype"] in erlaubt
    for connector in ir["connectors"]:
        assert connector["stereotype"] in bekannt


def test_geruest_uebernimmt_die_beschreibung_des_stereotyps() -> None:
    rules = _rules()
    notizen = {
        entry["name"]: (entry.get("notes") or "").strip()
        for entry in rules["elementStereotypes"]
    }
    ir = skeleton.build_skeleton(rules)
    for element in ir["elements"]:
        note = element["notes"].strip()
        if notizen[element["name"]]:
            assert note == notizen[element["name"]]
        else:
            assert note.startswith(f"Element-Stereotyp '{element['name']}'")


def test_geruest_beziehungen_kommen_aus_konnektor_regeln() -> None:
    rules = _rules()
    ir = skeleton.build_skeleton(rules)
    assert {(kante["stereotype"], kante["source"], kante["target"]) for kante in ir["connectors"]} == {
        ("ActivitySupportsService", "NAFv4-ADMBw/Class::OperationalActivity", "NAFv4-ADMBw/Class::ServiceSpecification"),
        ("CapabilityDependency", "NAFv4-ADMBw/Class::Capability", "NAFv4-ADMBw/Class::Capability"),
        ("Exhibits", "NAFv4-ADMBw/Class::Capability", "NAFv4-ADMBw/Class::ServiceSpecification"),
    }


def test_paket_je_metaklasse() -> None:
    rules = mdg_parser.parse_mdg(FIXTURES / "fremd_klein.xml")
    ir = skeleton.build_skeleton(rules)
    assert [paket["path"] for paket in ir["packages"]] == [
        "Acme Bausteine",
        "Acme Bausteine/Class",
        "Acme Bausteine/Interface",
    ]
    pakete = {element["name"]: element["package"] for element in ir["elements"]}
    assert pakete == {
        "Baustein": "Acme Bausteine/Class",
        "Dienst": "Acme Bausteine/Class",
        "Schnittstelle": "Acme Bausteine/Interface",
    }
    assert validator.summarize(_findings(ir, rules))["error"] == 0


def test_geruest_ohne_modellaufruf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _verboten(*_args, **_kwargs):
        raise AssertionError("ohne Text und ohne Bild darf kein Backend gebaut werden")

    monkeypatch.setattr(eam_ai.extract_module, "make_backend", _verboten)
    target = tmp_path / "geruest.qea"

    report = eam_ai.build(
        mdg=MDG,
        out=target,
        findings_path=tmp_path / "findings.json",
    )

    assert report.exported is True
    assert report.blocked is False
    assert report.backend == skeleton.SKELETON_BACKEND
    assert report.segments == 0
    assert report.attempts == 0
    assert report.elements == 5
    assert report.connectors == 3
    assert report.provenance_tags == 0
    assert report.quellen is None
    assert target.is_file()
    assert json.loads((tmp_path / "findings.json").read_text(encoding="utf-8")) == []

    ir = read_qea(target)
    assert {element["name"] for element in ir["elements"]} == {
        "ActualProject",
        "Capability",
        "OperationalActivity",
        "Process",
        "ServiceSpecification",
    }


def test_backend_ohne_quelle_ist_laut(tmp_path: Path) -> None:
    with pytest.raises(eam_ai.BuildError, match="kein Modellaufruf"):
        eam_ai.build(
            mdg=MDG,
            out=tmp_path / "geruest.qea",
            backend_kind="openai",
        )
    assert not (tmp_path / "geruest.qea").exists()


def test_leeres_backend_objekt_ohne_quelle_ist_laut(tmp_path: Path) -> None:
    import extract as ex

    with pytest.raises(eam_ai.BuildError, match="kein Modellaufruf"):
        eam_ai.build(
            mdg=MDG,
            out=tmp_path / "geruest.qea",
            backend=ex.StaticBackend(['{"elements": []}']),
        )


def test_cli_baut_geruest_ohne_schluessel_offline(tmp_path: Path) -> None:
    target = tmp_path / "geruest.qea"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY", "EXTRACT_BACKEND", "EXTRACT_MODEL"}
    }
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "eam_ai.py"),
            "build",
            "--mdg",
            str(MDG),
            "--out",
            str(target),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "0 Fehler" in result.stdout
    assert "Geruest" in result.stderr
    assert target.is_file()
    assert (tmp_path / "findings.json").is_file()
    assert not (tmp_path / "quellen.json").exists()


def test_zwei_laeufe_sind_byte_identisch(tmp_path: Path) -> None:
    first = eam_ai.build(mdg=MDG, out=tmp_path / "eins.qea", findings_path=tmp_path / "f1.json")
    second = eam_ai.build(mdg=MDG, out=tmp_path / "zwei.qea", findings_path=tmp_path / "f2.json")
    assert first.digest == second.digest
    assert (tmp_path / "eins.qea").read_bytes() == (tmp_path / "zwei.qea").read_bytes()
    assert (tmp_path / "f1.json").read_bytes() == (tmp_path / "f2.json").read_bytes()


def test_wurzelpaket_ist_setzbar() -> None:
    ir = skeleton.build_skeleton(_rules(), package="Geruest/NAF")
    paths = [paket["path"] for paket in ir["packages"]]
    assert paths[:2] == ["Geruest", "Geruest/NAF"]
    assert "Geruest/NAF/Class" in paths
    assert all(element["package"] == "Geruest/NAF/Class" for element in ir["elements"])


def test_ungueltiges_paket_ist_laut() -> None:
    with pytest.raises(skeleton.SkeletonError, match="Trenner"):
        skeleton.build_skeleton(_rules(), package="Geruest\\NAF")
    with pytest.raises(skeleton.SkeletonError, match="Endung|ungueltiger Pfad"):
        skeleton.build_skeleton(_rules(), package="/Geruest")


@pytest.mark.skipif(not REAL_MDG.is_file(), reason="echte ADMBw-MDG liegt lokal nicht vor")
def test_echte_admbw_mdg_besteht_die_pruefung() -> None:
    import extract as ex

    rules = mdg_parser.parse_mdg(REAL_MDG)
    ir = skeleton.build_skeleton(rules)
    assert len(ir["elements"]) == len(ex.load_rules(rules).elements)
    assert len(ir["connectors"]) > 0
    summary = validator.summarize(_findings(ir, rules))
    assert summary["error"] == 0
    assert summary["warning"] == 0
