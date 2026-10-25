"""Tests fuer den Frage-Antwort-Weg ueber eine .qea.

Die .qea wird im Test aus einem kleinen IR geschrieben (qea_writer), damit
keine echte Datei und kein Netz noetig sind. Geprueft wird: der Ausschnitt
begrenzt den Prompt wirklich, ohne Backend kommt eine ehrliche "ohne KI"-
Beschreibung, und der Markdown-Export ist vollstaendig und deterministisch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eam_ai
import extract as ex
import qea_chat
from qea_writer import write_qea


def _ir() -> dict:
    return {
        "ir_version": 1,
        "technology": {"profile": "Testprofil"},
        "packages": [
            {"path": "Modell"},
            {"path": "Modell/A"},
            {"path": "Modell/B"},
        ],
        "elements": [
            {
                "package": "Modell/A",
                "name": "Alpha",
                "stereotype": "System",
                "ea_type": "Class",
                "notes": "Alpha-Notiz.",
            },
            {
                "package": "Modell/A",
                "name": "Gamma",
                "stereotype": "System",
                "ea_type": "Class",
                "notes": "Gamma-Notiz.",
            },
            {
                "package": "Modell/B",
                "name": "Beta",
                "stereotype": "System",
                "ea_type": "Class",
                "notes": "Beta-Notiz.",
            },
            {
                "package": "Modell/B",
                "name": "Delta",
                "stereotype": "System",
                "ea_type": "Class",
                "notes": "Delta-Notiz.",
            },
        ],
        "connectors": [
            {
                "source": "Modell/A::Alpha",
                "target": "Modell/B::Beta",
                "stereotype": "nutzt",
                "ea_type": "Dependency",
            }
        ],
        "diagrams": [],
    }


class RecordingBackend:
    """Minimales Backend: merkt sich den Prompt und liefert festen Text."""

    name = "test-modell"

    def __init__(self, text: str = "Alpha nutzt Beta.") -> None:
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


@pytest.fixture()
def modell(tmp_path: Path) -> Path:
    return write_qea(_ir(), tmp_path / "modell.qea")


# --------------------------------------------------------------------------
# Ohne Backend
# --------------------------------------------------------------------------


def test_ohne_backend_liefert_beschreibung_ohne_ki(modell: Path) -> None:
    answer = qea_chat.ask_qea(modell, "Welche Elemente gibt es?")

    assert answer.model == qea_chat.OHNE_KI
    assert answer.scope is None
    assert answer.text.startswith("# Ohne KI:")
    assert "Kein Sprachmodell beteiligt" in answer.text
    assert "Alpha" in answer.text and "Beta" in answer.text
    assert "Welche Elemente gibt es?" in answer.text
    assert answer.sources == ["Modell", "Modell/A", "Modell/B"]
    assert answer.question == "Welche Elemente gibt es?"
    assert answer.quelle == "modell.qea"


def test_paket_ausschnitt_begrenzt_die_beschreibung(modell: Path) -> None:
    answer = qea_chat.ask_qea(modell, "Was liegt hier?", scope={"package": "Modell/A"})
    assert answer.scope == {"package": "Modell/A"}
    assert "Alpha" in answer.text and "Gamma" in answer.text
    assert "Beta" not in answer.text and "Delta" not in answer.text
    assert answer.sources == ["Modell/A", "Modell/A::Alpha", "Modell/A::Gamma"]


def test_element_ausschnitt_nur_element_und_direkte_beziehungen(modell: Path) -> None:
    answer = qea_chat.ask_qea(modell, "Was ist Alpha?", scope={"element": "Modell/A::Alpha"})
    assert "Alpha" in answer.text
    assert "Beta" in answer.text, "die direkte Beziehung ist Teil des Ausschnitts"
    assert "Gamma" not in answer.text and "Delta" not in answer.text
    assert answer.sources == ["Modell/A::Alpha", "Modell/B::Beta"]


def test_paket_ohne_unterpakete_ist_weiter_erlaubt(modell: Path) -> None:
    answer = qea_chat.ask_qea(modell, "Was?", scope={"package": "Modell/B"})
    assert "Beta" in answer.text and "Delta" in answer.text
    assert "Alpha" not in answer.text


def test_oberpaket_enthaelt_unterpakete(modell: Path) -> None:
    answer = qea_chat.ask_qea(modell, "Alles?", scope={"package": "Modell"})
    for name in ("Alpha", "Gamma", "Beta", "Delta"):
        assert name in answer.text
    assert answer.sources[:3] == ["Modell", "Modell/A", "Modell/B"]


# --------------------------------------------------------------------------
# Mit Backend
# --------------------------------------------------------------------------


def test_backend_bekommt_nur_den_ausschnitt(modell: Path) -> None:
    backend = RecordingBackend()
    answer = qea_chat.ask_qea(
        modell, "Was ist Alpha?", backend=backend, scope={"element": "Modell/A::Alpha"}
    )
    prompt = backend.prompts[0]
    assert answer.text == "Alpha nutzt Beta."
    assert answer.model == "test-modell"
    assert "FRAGE:" in prompt and "Was ist Alpha?" in prompt
    assert "Alpha" in prompt and "Beta" in prompt
    assert "Gamma" not in prompt and "Delta" not in prompt
    assert "Technologie: Testprofil" in prompt
    assert "QUELLEN IM AUSSCHNITT:" in prompt


def test_backend_bekommt_ganzes_modell_ohne_scope(modell: Path) -> None:
    backend = RecordingBackend()
    qea_chat.ask_qea(modell, "Alles?", backend=backend)
    prompt = backend.prompts[0]
    for name in ("Alpha", "Gamma", "Beta", "Delta"):
        assert name in prompt


def test_backend_leere_antwort_ist_laut(modell: Path) -> None:
    with pytest.raises(qea_chat.QeaChatError, match="leere Antwort"):
        qea_chat.ask_qea(modell, "Frage", backend=RecordingBackend("   "))


def test_backend_fehler_wird_als_chatfehler_gemeldet(modell: Path) -> None:
    class Kaputt:
        @property
        def name(self) -> str:
            return "kaputt"

        def complete(self, prompt: str) -> str:
            raise ex.ExtractionError("HTTP 500")

    with pytest.raises(qea_chat.QeaChatError, match="HTTP 500"):
        qea_chat.ask_qea(modell, "Frage", backend=Kaputt())


def test_prompt_wird_bei_bedarf_mit_hinweis_gekuerzt(modell: Path) -> None:
    beschreibung = "x" * 50
    prompt = qea_chat.build_prompt("Frage", "Paket X", beschreibung, max_chars=10)
    assert "x" * 11 not in prompt
    assert "gekuerzt" in prompt
    assert "Frage" in prompt


# --------------------------------------------------------------------------
# Laute Fehler
# --------------------------------------------------------------------------


def test_leere_frage_ist_laut(modell: Path) -> None:
    with pytest.raises(qea_chat.QeaChatError, match="Frage"):
        qea_chat.ask_qea(modell, "   ")


def test_unbekanntes_paket_ist_laut(modell: Path) -> None:
    with pytest.raises(qea_chat.QeaChatError, match="nicht gefunden"):
        qea_chat.ask_qea(modell, "Frage", scope={"package": "Modell/Z"})


def test_unbekanntes_element_ist_laut(modell: Path) -> None:
    with pytest.raises(qea_chat.QeaChatError, match="nicht gefunden"):
        qea_chat.ask_qea(modell, "Frage", scope={"element": "Omega"})


def test_mehrdeutiges_element_ist_laut(tmp_path: Path) -> None:
    ir = _ir()
    ir["elements"].append(
        {
            "package": "Modell/B",
            "name": "Alpha",
            "stereotype": "System",
            "ea_type": "Class",
            "notes": "zweites Alpha",
        }
    )
    pfad = write_qea(ir, tmp_path / "doppelt.qea")
    with pytest.raises(qea_chat.QeaChatError, match="mehrdeutig"):
        qea_chat.ask_qea(pfad, "Frage", scope={"element": "Alpha"})


def test_scope_form_wird_geprueft(modell: Path) -> None:
    with pytest.raises(qea_chat.QeaChatError, match="genau ein Schluessel"):
        qea_chat.ask_qea(modell, "Frage", scope={"package": "Modell/A", "element": "Alpha"})
    with pytest.raises(qea_chat.QeaChatError, match="genau ein Schluessel"):
        qea_chat.ask_qea(modell, "Frage", scope={"foo": "bar"})
    with pytest.raises(qea_chat.QeaChatError, match="nicht-leerer"):
        qea_chat.ask_qea(modell, "Frage", scope={"package": "  "})


def test_kaputte_qea_ist_laut(tmp_path: Path) -> None:
    kaputt = tmp_path / "kaputt.qea"
    kaputt.write_bytes(b"keine sqlite-datei")
    with pytest.raises(qea_chat.QeaChatError):
        qea_chat.ask_qea(kaputt, "Frage")


# --------------------------------------------------------------------------
# Markdown-Export
# --------------------------------------------------------------------------


def test_export_answer_schreibt_markdown(modell: Path, tmp_path: Path) -> None:
    answer = qea_chat.ask_qea(modell, "Was ist Alpha?", scope={"package": "Modell/A"})
    ziel = qea_chat.export_answer(answer, tmp_path / "tief" / "antwort.md")

    assert ziel.is_file()
    text = ziel.read_text(encoding="utf-8")
    assert "# Frage-Antwort zum Architekturmodell" in text
    assert "**Frage:** Was ist Alpha?" in text
    assert "`modell.qea`" in text
    assert "Paket Modell/A" in text
    assert "`ohne KI`" in text
    assert "`Modell/A::Alpha`" in text
    assert answer.text.strip() in text

    zweite = qea_chat.export_answer(answer, tmp_path / "antwort2.md")
    assert ziel.read_bytes() == zweite.read_bytes(), "Export ist deterministisch"


def test_export_answer_lehnt_leeren_text_ab() -> None:
    with pytest.raises(qea_chat.QeaChatError, match="leer"):
        qea_chat.export_answer(qea_chat.Answer("  ", None, [], "x"), "egal.md")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_frage_ohne_backend(modell: Path, capsys: pytest.CaptureFixture) -> None:
    code = eam_ai.main(["frage", "--qea", str(modell), "--frage", "Was gibt es?"])
    ausgabe = capsys.readouterr()
    assert code == 0
    assert "Ohne KI" in ausgabe.out
    assert "Alpha" in ausgabe.out


def test_cli_frage_mit_paket_und_out(modell: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ziel = tmp_path / "antwort.md"
    code = eam_ai.main(
        [
            "frage",
            "--qea",
            str(modell),
            "--frage",
            "Was liegt in A?",
            "--paket",
            "Modell/A",
            "--out",
            str(ziel),
        ]
    )
    ausgabe = capsys.readouterr()
    assert code == 0
    assert ziel.is_file()
    assert "Antwort:" in ausgabe.err
    assert "Beta" not in ausgabe.out


def test_cli_frage_mit_backend(modell: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    backend = RecordingBackend("Antwort aus dem Modell.")
    monkeypatch.setattr(eam_ai.extract_module, "make_backend", lambda *_a, **_k: backend)

    code = eam_ai.main(
        ["frage", "--qea", str(modell), "--frage", "Frage?", "--backend", "openai"]
    )
    ausgabe = capsys.readouterr()
    assert code == 0
    assert ausgabe.out.strip() == "Antwort aus dem Modell."
    assert backend.prompts and "Frage?" in backend.prompts[0]


def test_cli_frage_openai_ohne_json_modus(
    modell: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Eine Frage ist Prosa: der Chat-Aufruf darf kein JSON-Format erzwingen."""
    captured: dict = {}

    def fake_post(url, payload, headers, timeout, what):
        captured.update(payload)
        return {"choices": [{"message": {"content": "Prosa-Antwort."}}]}

    monkeypatch.setattr(ex, "_post_json", fake_post)
    code = eam_ai.main(
        [
            "frage",
            "--qea",
            str(modell),
            "--frage",
            "Frage?",
            "--backend",
            "openai",
            "--model",
            "mock",
            "--base-url",
            "https://example.invalid/v1",
        ]
    )
    ausgabe = capsys.readouterr()
    assert code == 0
    assert ausgabe.out.strip() == "Prosa-Antwort."
    assert captured["model"] == "mock"
    assert "response_format" not in captured, "Prosa statt JSON erzwingen"


def test_cli_paket_und_element_schliessen_sich_aus(modell: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        eam_ai.main(
            [
                "frage",
                "--qea",
                str(modell),
                "--frage",
                "Frage",
                "--paket",
                "Modell/A",
                "--element",
                "Alpha",
            ]
        )
    assert excinfo.value.code == 2


def test_cli_frage_meldet_unbekanntes_paket(modell: Path, capsys: pytest.CaptureFixture) -> None:
    code = eam_ai.main(
        ["frage", "--qea", str(modell), "--frage", "Frage", "--paket", "Modell/Z"]
    )
    ausgabe = capsys.readouterr()
    assert code == 1
    assert "FEHLER" in ausgabe.err
    assert "nicht gefunden" in ausgabe.err
