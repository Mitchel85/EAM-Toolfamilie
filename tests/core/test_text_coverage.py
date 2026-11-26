"""Tests fuer die deterministische Textabdeckungs-Pruefung (text_coverage.py)."""

from __future__ import annotations

import json
from pathlib import Path

import eam_ai
import qea_writer
import text_coverage


def test_evaluate_coverage_erkennt_abgedeckte_und_offene_kapitel(tmp_path: Path) -> None:
    pflichtenheft = (
        "## 1 Sensorik\n\n"
        "Der Radarsensor erfasst Luftziele.\n\n"
        "Die Kamera liefert optische Bilder.\n\n"
        "## 2 Kommunikation\n\n"
        "Das Funkmodul uebertraegt Lagedaten verschluesselt.\n"
    )
    txt_file = tmp_path / "pflichtenheft.md"
    txt_file.write_text(pflichtenheft, encoding="utf-8")

    ir = {
        "ir_version": 1,
        "packages": [{"path": "Arch"}],
        "elements": [
            {
                "package": "Arch",
                "name": "Radarsensor",
                "stereotype": "System",
                "tags": {"source_ref": "D1-S2", "source_doc": "D1", "source_confidence": "0.90"},
            }
        ],
        "connectors": [],
    }
    cov = text_coverage.evaluate_coverage(ir, text_source=txt_file)
    assert cov is not None
    # 5 Segmente gesamt, davon 2 reine Ueberschriften -> 3 Fachabsaetze, 1 abgedeckt (D1-S2)
    assert cov.total_segments == 5
    assert cov.content_segments == 3
    assert cov.covered_segments == 1
    assert cov.uncovered_segments == 2
    assert cov.coverage_pct == 33.3
    uncov_refs = [u["ref"] for u in cov.uncovered]
    assert uncov_refs == ["D1-S3", "D1-S5"]

    chapters = {c["chapter"]: c for c in cov.chapters}
    assert chapters["1 Sensorik"]["covered"] == 1
    assert chapters["2 Kommunikation"]["covered"] == 0


def test_qs_cli_integriert_textabdeckung(tmp_path: Path) -> None:
    txt = tmp_path / "quelle.txt"
    txt.write_text("System Alpha verarbeitet Meldungen.\n\nSystem Beta speichert Archivdaten.\n", encoding="utf-8")
    qea = qea_writer.write_qea(
        {
            "ir_version": 1,
            "packages": [{"path": "Arch"}],
            "elements": [
                {
                    "package": "Arch",
                    "name": "System Alpha",
                    "stereotype": "System",
                    "tags": {"source_ref": "D1-S1"},
                }
            ],
            "connectors": [],
        },
        tmp_path / "m.qea",
    )
    out = tmp_path / "qs.json"
    eam_ai.main(["qs", "--in", str(qea), "--text", str(txt), "--out", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "coverage" in data
    assert data["coverage"]["coverage_pct"] == 50.0
    assert data["coverage"]["uncovered"][0]["ref"] == "D1-S2"
