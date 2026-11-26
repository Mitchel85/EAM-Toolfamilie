"""Tests fuer den abhaengigkeitsfreien 4-Format-MCP-Server (mcp_stdio.py / eam-ai mcp)."""

from __future__ import annotations

import json
from pathlib import Path

import eam_ai
import mcp_stdio
import qea_writer

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "packages" / "core" / "fixtures" / "rules_validator.json"


def _mini_qea(path: Path, name: str = "Sensorknoten", st: str = "System") -> Path:
    return qea_writer.write_qea(
        {
            "ir_version": 1,
            "packages": [{"path": "Arch"}],
            "elements": [
                {
                    "package": "Arch",
                    "name": name,
                    "stereotype": st,
                    "ea_type": "Class",
                    "tags": {"source_ref": "D1-S1"},
                }
            ],
            "connectors": [],
        },
        path,
    )


def test_mcp_initialize_und_tools_list() -> None:
    init_resp = mcp_stdio.dispatch_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        version="3.9.0",
    )
    assert init_resp is not None
    assert init_resp["result"]["serverInfo"]["name"] == "eam-ai-core"

    # Notification ohne id liefert None
    assert mcp_stdio.dispatch_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    list_resp = mcp_stdio.dispatch_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert list_resp is not None
    tool_names = {t["name"] for t in list_resp["result"]["tools"]}
    assert {
        "eam_inspect_model",
        "eam_validate_mdg",
        "eam_archimate_check",
        "eam_diff_models",
        "eam_text_coverage",
        "eam_repair_model",
        "eam_nl_edit",
        "eam_convert_model",
        "eam_graph_query",
    } <= tool_names


def test_mcp_tools_call_inspect_diff_repair_convert(tmp_path: Path) -> None:
    qea1 = _mini_qea(tmp_path / "m1.qea", "Sensorknoten", "ServiceSpecification")
    qea2 = qea_writer.write_qea(
        {
            "ir_version": 1,
            "packages": [{"path": "Arch"}],
            "elements": [
                {"package": "Arch", "name": "Lagebildknoten", "stereotype": "UnbekannterTyp", "ea_type": "Class"},
                {"package": "Arch", "name": "Sensordienst", "stereotype": "ServiceSpecification", "ea_type": "Class"},
            ],
            "connectors": [
                {
                    "source": "Arch::Lagebildknoten",
                    "target": "Arch::Sensordienst",
                    "stereotype": "ActivitySupportsService",
                    "ea_type": "Realisation",
                }
            ],
        },
        tmp_path / "m2.qea",
    )

    # 1. Inspect
    r_insp = mcp_stdio.dispatch_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "eam_inspect_model", "arguments": {"path": str(qea1)}},
        }
    )
    assert r_insp is not None and not r_insp["result"]["isError"]
    insp_data = json.loads(r_insp["result"]["content"][0]["text"])
    assert insp_data["counts"]["elements"] == 1

    # 2. Diff
    r_diff = mcp_stdio.dispatch_request(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "eam_diff_models", "arguments": {"alt": str(qea1), "neu": str(qea2), "mdg": str(RULES)}},
        }
    )
    assert r_diff is not None and not r_diff["result"]["isError"]
    diff_data = json.loads(r_diff["result"]["content"][0]["text"])
    assert diff_data["identical"] is False

    # 3. Repair (preview + apply to .json)
    repaired_json = tmp_path / "repaired.json"
    r_rep = mcp_stdio.dispatch_request(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "eam_repair_model",
                "arguments": {"path": str(qea2), "mdg": str(RULES), "out": str(repaired_json), "apply": True},
            },
        }
    )
    assert r_rep is not None and not r_rep["result"]["isError"]
    rep_data = json.loads(r_rep["result"]["content"][0]["text"])
    assert rep_data["applied"] is True
    assert rep_data["changes_count"] >= 1
    assert repaired_json.is_file()


def test_cli_mcp_list_tools(capsys) -> None:
    rc = eam_ai.main(["mcp", "--list-tools"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["tools"]) >= 9
