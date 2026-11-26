"""Tests fuer den formatuebergreifenden Architektur-Diff (model_diff.py)."""

from __future__ import annotations

import json
from pathlib import Path

import eam_ai
import model_diff
import model_io
import qea_writer

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "packages" / "core" / "fixtures" / "rules_validator.json"


def _sample_ir_alt() -> dict:
    return {
        "ir_version": 1,
        "packages": [{"path": "Architektur"}, {"path": "Architektur/Alt"}],
        "elements": [
            {
                "package": "Architektur",
                "name": "Sensorknoten",
                "stereotype": "System",
                "ea_type": "Class",
                "guid": "{11111111-1111-4111-8111-111111111111}",
                "notes": "Erfasst Rohdaten.",
                "tags": {"OriginalGUID": "NATO-1"},
            },
            {
                "package": "Architektur/Alt",
                "name": "Altdienst",
                "stereotype": "ServiceSpecification",
                "ea_type": "Class",
                "guid": "{22222222-2222-4222-8222-222222222222}",
            },
        ],
        "connectors": [
            {
                "source": "Architektur::Sensorknoten",
                "target": "Architektur/Alt::Altdienst",
                "stereotype": "InvalidEdge",
                "ea_type": "Dependency",
            }
        ],
    }


def _sample_ir_neu() -> dict:
    return {
        "ir_version": 1,
        "packages": [{"path": "Architektur"}, {"path": "Architektur/Dienste"}],
        "elements": [
            {
                # Gleiche GUID, aber umbenannt und mit geaenderter Notiz:
                "package": "Architektur",
                "name": "Sensorknoten Nord",
                "stereotype": "System",
                "ea_type": "Class",
                "guid": "{11111111-1111-4111-8111-111111111111}",
                "notes": "Erfasst und filtert Rohdaten.",
                "tags": {"OriginalGUID": "NATO-1", "Zone": "Nord"},
            },
            {
                "package": "Architektur/Dienste",
                "name": "Lagebilddienst",
                "stereotype": "ServicePort",
                "ea_type": "Port",
                "guid": "{33333333-3333-4333-8333-333333333333}",
            },
        ],
        "connectors": [],
    }


def test_diff_erkennt_umbenennung_per_guid_und_mdg_delta(tmp_path: Path) -> None:
    alt_qea = qea_writer.write_qea(_sample_ir_alt(), tmp_path / "alt.qea")
    neu_json = model_io.write_model(_sample_ir_neu(), tmp_path / "neu.json", format="json")

    res = model_diff.diff_models(alt_qea, neu_json, mdg=RULES)
    assert not res.identical
    assert res.summary["packages_added"] == 1
    assert res.summary["packages_removed"] == 1
    assert res.summary["elements_added"] == 1
    assert res.summary["elements_removed"] == 1
    assert res.summary["elements_changed"] == 1

    changed = res.elements["changed"][0]
    assert changed["changes"]["name"] == {"before": "Sensorknoten", "after": "Sensorknoten Nord"}
    assert "Zone" in changed["changes"]["tags"]["added"]
    assert res.summary["connectors_removed"] == 1

    # MDG-Delta: die ungueltige Kante InvalidEdge wurde im Neustand behoben!
    assert res.mdg is not None
    assert res.mdg["error_delta"] < 0
    assert len(res.mdg["resolved"]) >= 1

    md = model_diff.render_markdown(res)
    assert "Sensorknoten Nord" in md
    assert "MDG-Konformitäts-Delta" in md


def test_cli_diff_subcommand(tmp_path: Path, capsys) -> None:
    alt_p = model_io.write_model(_sample_ir_alt(), tmp_path / "a.json", format="json")
    neu_p = model_io.write_model(_sample_ir_alt(), tmp_path / "b.json", format="json")
    out_p = tmp_path / "diff.json"

    rc = eam_ai.main(["diff", "--alt", str(alt_p), "--neu", str(neu_p), "--format", "json", "--out", str(out_p)])
    assert rc == 0
    payload = json.loads(out_p.read_text(encoding="utf-8"))
    assert payload["identical"] is True
