"""Tests fuer ``nl_edit.py`` -- natuerlichsprachliche Korrekturen."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import extract
import eam_ai
import nl_edit
import qea_writer

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
MDG = ROOT / "examples" / "offline" / "mdg_admbw_auszug.xml"


def _qea(path: Path) -> Path:
    ir = {
        "ir_version": 1,
        "technology": {"profile": "Testprofil"},
        "packages": [{"path": "Architektur"}],
        "elements": [
            {
                "package": "Architektur",
                "name": "Lagedienst",
                "stereotype": "Capability",
                "ea_type": "Class",
                "notes": "Alte Notiz",
                "tags": {},
            },
            {
                "package": "Architektur",
                "name": "Kartendarstellung",
                "stereotype": "Capability",
                "ea_type": "Class",
                "notes": "",
                "tags": {},
            },
        ],
        "connectors": [
            {
                "source": "Architektur::Kartendarstellung",
                "target": "Architektur::Lagedienst",
                "stereotype": "CapabilityGeneralization",
                "ea_type": "Generalization",
                "notes": "",
                "tags": {},
            }
        ],
        "diagrams": [],
    }
    return qea_writer.write_qea(ir, path)


def _rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _value(path: Path, column: str, name: str) -> str:
    rows = _rows(path, f"SELECT {column} FROM t_object WHERE Name = ?", (name,))
    assert len(rows) == 1
    return rows[0][0]


def test_parse_command_rename_note_status_delete_and_connector() -> None:
    assert nl_edit.parse_command('Benenne "Lagedienst" in "Lagedienst Bw" um.') == [
        {"op": "set_name", "name": "Lagedienst", "value": "Lagedienst Bw"}
    ]
    # Zweite Formulierung fuer denselben Vorgang (Feld "Name").
    assert nl_edit.parse_command('Ändere den Namen von "Lagedienst" in "Lagedienst Bw".') == [
        {"op": "set_name", "name": "Lagedienst", "value": "Lagedienst Bw"}
    ]
    assert nl_edit.parse_command('Setze die Notiz von "Lagedienst" auf "Neu".') == [
        {"op": "set_note", "name": "Lagedienst", "value": "Neu"}
    ]
    assert nl_edit.parse_command('Setze den Status von "Lagedienst" auf Proposed.') == [
        {"op": "set_status", "name": "Lagedienst", "value": "Proposed"}
    ]
    assert nl_edit.parse_command('Loesche das Element "Lagedienst".') == [
        {"op": "delete_element", "name": "Lagedienst"}
    ]
    ops = nl_edit.parse_command('Verbinde "Lagedienst" mit "Kartendarstellung" ueber Dependency.')
    assert ops[0]["op"] == "add_connector"
    assert ops[0]["source"] == "Lagedienst"
    assert ops[0]["target"] == "Kartendarstellung"
    assert ops[0]["stereotype"] == "Dependency"


def test_parse_command_two_clauses() -> None:
    ops = nl_edit.parse_command(
        'Benenne "Lagedienst" in "Lagedienst Bw" um und setze die Notiz von "Lagedienst Bw" auf "Neu".'
    )
    assert [op["op"] for op in ops] == ["set_name", "set_note"]


def test_propose_resolves_element_and_rejects_unknown(tmp_path: Path) -> None:
    qea = _qea(tmp_path / "modell.qea")
    proposal = nl_edit.propose(qea, 'Benenne "Lagedienst" in "Lagedienst Bw" um.')
    assert len(proposal.ops) == 1
    assert proposal.ops[0]["op"] == "set_name"
    assert proposal.ops[0]["guid"].startswith("{")
    assert proposal.ops[0]["package"] == "Architektur"

    with pytest.raises(nl_edit.NlEditError, match="Kein Element"):
        nl_edit.propose(qea, 'Benenne "Gibtsnicht" in "X" um.')


def test_apply_preserves_guid_and_original(tmp_path: Path) -> None:
    qea = _qea(tmp_path / "modell.qea")
    original = qea.read_bytes()
    before = _value(qea, "ea_guid", "Lagedienst")

    proposal = nl_edit.propose(qea, 'Benenne "Lagedienst" in "Lagedienst Bw" um.')
    result = nl_edit.apply(proposal, tmp_path / "neu.qea")

    assert result.applied == 1
    assert result.rejected == []
    assert qea.read_bytes() == original
    assert _value(tmp_path / "neu.qea", "ea_guid", "Lagedienst Bw") == before
    assert _rows(tmp_path / "neu.qea", "SELECT Name FROM t_object WHERE Name = 'Lagedienst'") == []


def test_delete_requires_confirmation(tmp_path: Path) -> None:
    qea = _qea(tmp_path / "modell.qea")
    proposal = nl_edit.propose(qea, 'Loesche das Element "Lagedienst".')
    assert proposal.destructive is True
    with pytest.raises(nl_edit.NlEditError, match="bestaetigen"):
        nl_edit.apply(proposal, tmp_path / "neu.qea")
    result = nl_edit.apply(proposal, tmp_path / "neu.qea", confirm=True)
    assert result.applied == 1
    assert _rows(tmp_path / "neu.qea", "SELECT Name FROM t_object WHERE Name = 'Lagedienst'") == []


def test_add_and_delete_connector(tmp_path: Path) -> None:
    qea = _qea(tmp_path / "modell.qea")
    add = nl_edit.propose(qea, 'Verbinde "Lagedienst" mit "Kartendarstellung" ueber Dependency.')
    result = nl_edit.apply(add, tmp_path / "mit_kante.qea")
    assert result.applied == 1
    assert _rows(
        tmp_path / "mit_kante.qea",
        "SELECT COUNT(*) FROM t_connector WHERE Stereotype = 'Dependency'",
    )[0][0] >= 1

    remove = nl_edit.propose(
        tmp_path / "mit_kante.qea",
        'Entferne die Beziehung zwischen "Lagedienst" und "Kartendarstellung" mit Dependency.',
    )
    assert remove.destructive is True
    result = nl_edit.apply(remove, tmp_path / "ohne_kante.qea", confirm=True)
    assert result.applied == 1


def test_llm_json_with_static_backend_and_unknown_name(tmp_path: Path) -> None:
    qea = _qea(tmp_path / "modell.qea")
    answer = json.dumps(
        {
            "reply": "Ich benenne um.",
            "ops": [
                {
                    "op": "set_name",
                    "package": "Architektur",
                    "name": "Lagedienst",
                    "value": "Lagedienst Bw",
                }
            ],
        }
    )
    backend = extract.StaticBackend([answer], name="test")
    proposal = nl_edit.propose(qea, "Benenne Lagedienst um.", backend=backend)
    assert proposal.ops[0]["value"] == "Lagedienst Bw"

    bad = extract.StaticBackend(
        [json.dumps({"reply": "", "ops": [{"op": "set_name", "name": "Erfunden", "value": "X"}]})],
        name="test",
    )
    with pytest.raises(nl_edit.NlEditError, match="Kein Element"):
        nl_edit.propose(qea, "Benenne Erfunden um.", backend=bad)


def test_mdg_rejects_invalid_stereotype(tmp_path: Path) -> None:
    if not MDG.is_file():
        pytest.skip("MDG-Fixture fehlt")
    qea = _qea(tmp_path / "modell.qea")
    proposal = nl_edit.propose(
        qea, 'Setze den Stereotyp von "Lagedienst" auf VoelligFalsch.'
    )
    result = nl_edit.apply(proposal, tmp_path / "neu.qea", mdg=MDG)
    assert result.applied == 0
    assert result.rejected


# --------------------------------------------------------------------------
# CLI: eam-ai korrigiere
# --------------------------------------------------------------------------


def test_cli_preview_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    qea = _qea(tmp_path / "modell.qea")
    vorher = qea.read_bytes()
    out = tmp_path / "neu.qea"
    anweisung = tmp_path / "anweisung.txt"
    anweisung.write_text('Benenne "Lagedienst" in "Lagedienst Bw" um.\n', encoding="utf-8")

    code = eam_ai.main(
        [
            "korrigiere",
            "--qea",
            str(qea),
            "--anweisung-datei",
            str(anweisung),
            "--out",
            str(out),
        ]
    )
    ausgabe = capsys.readouterr()
    assert code == 0
    assert "umbenennen" in ausgabe.out
    assert "Vorschau" in ausgabe.err
    assert not out.exists(), "Vorschau schreibt keine Datei"
    assert qea.read_bytes() == vorher, "Original bleibt unberuehrt"


def test_cli_apply_schreibt_neue_datei(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    qea = _qea(tmp_path / "modell.qea")
    vorher = qea.read_bytes()
    guid = _value(qea, "ea_guid", "Lagedienst")
    out = tmp_path / "neu.qea"

    code = eam_ai.main(
        [
            "korrigiere",
            "--qea",
            str(qea),
            "--anweisung",
            'Ändere den Namen von "Lagedienst" in "Lagedienst Bw".',
            "--out",
            str(out),
            "--apply",
        ]
    )
    ausgabe = capsys.readouterr()
    assert code == 0
    assert "1 von 1" in ausgabe.out
    assert out.is_file()
    assert _value(out, "ea_guid", "Lagedienst Bw") == guid
    assert qea.read_bytes() == vorher
    assert _rows(qea, "SELECT Name FROM t_object WHERE Name = 'Lagedienst'") != []


def test_cli_loeschen_verlangt_ja(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    qea = _qea(tmp_path / "modell.qea")
    out = tmp_path / "neu.qea"
    args = [
        "korrigiere",
        "--qea",
        str(qea),
        "--anweisung",
        'Loesche das Element "Lagedienst".',
        "--out",
        str(out),
        "--apply",
    ]
    assert eam_ai.main(args) == 1
    ausgabe = capsys.readouterr()
    assert "bestaetigen" in ausgabe.err
    assert not out.exists(), "ohne --ja wird nichts geschrieben"

    assert eam_ai.main([*args, "--ja"]) == 0
    ausgabe = capsys.readouterr()
    assert "1 von 1" in ausgabe.out
    assert _rows(out, "SELECT Name FROM t_object WHERE Name = 'Lagedienst'") == []
    assert _rows(qea, "SELECT Name FROM t_object WHERE Name = 'Lagedienst'") != []


def test_cli_mdg_lehnt_ungueltigen_stereotyp_ab(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    if not MDG.is_file():
        pytest.skip("MDG-Fixture fehlt")
    qea = _qea(tmp_path / "modell.qea")
    out = tmp_path / "neu.qea"

    code = eam_ai.main(
        [
            "korrigiere",
            "--qea",
            str(qea),
            "--anweisung",
            'Setze den Stereotyp von "Lagedienst" auf VoelligFalsch.',
            "--out",
            str(out),
            "--apply",
            "--mdg",
            str(MDG),
        ]
    )
    ausgabe = capsys.readouterr()
    assert code == 1
    assert "0 von 1" in ausgabe.out
    assert "ABGELEHNT" in ausgabe.err
    assert _value(qea, "Stereotype", "Lagedienst") == "Capability"
