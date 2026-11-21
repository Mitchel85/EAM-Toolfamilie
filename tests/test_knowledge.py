"""Tests fuer die Wissensbasis: eine Quelle, maschinell erzeugt, geprueft.

Der Kern dieser Tests ist der Drift-Waechter: weicht eine eingecheckte Datei
von dem ab, was der Parser aus der MDG erzeugen wuerde, muss der Lauf rot
werden. Ohne diesen Test ist die Wissensbasis nach zwei Wochen wieder
handgepflegt.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import mdg_source  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_knowledge.py"
PARSER = ROOT / "packages" / "rules" / "mdg_parser.py"
MDG = mdg_source.path()
KNOWLEDGE = ROOT / "knowledge"
PROVENANCE = KNOWLEDGE / "PROVENANCE.json"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--mdg", str(MDG), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch):
    """Kopie des Wissensordners, damit Tests das Repo nicht anfassen."""
    kopie = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE, kopie)
    prov = kopie / "PROVENANCE.json"
    if prov.is_file():
        data = json.loads(prov.read_text(encoding="utf-8"))
        data["files"] = {}
        prov.write_text(json.dumps(data), encoding="utf-8")
    import build_knowledge as modul  # type: ignore

    monkeypatch.setattr(modul, "KNOWLEDGE", kopie)
    monkeypatch.setattr(modul, "PROVENANCE", kopie / "PROVENANCE.json")
    return modul, kopie


def test_quelle_und_wissensbasis_passen_zusammen() -> None:
    result = run("--check", "--check-provenance")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passt zur Quelle" in result.stdout


def test_alle_dateien_werden_erzeugt() -> None:
    erwartet = {
        "admbw-aliases.json",
        "admbw-knowledge-connectors.md",
        "admbw-knowledge-stereotype-tags.md",
        "admbw-knowledge-stereotypes.md",
        "admbw-knowledge-tagtypes.md",
        "admbw-knowledge-topology.md",
        "admbw-knowledge-viewpoints.md",
        "admbw-meta.md",
        "admbw-prompt.md",
        "admbw-stereotypes.json",
    }
    vorhanden = {p.name for p in KNOWLEDGE.glob("admbw-*")}
    assert vorhanden == erwartet


def test_provenienz_nennt_quelle_und_hashes() -> None:
    data = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert data["mdg"] == MDG.name
    assert len(data["mdg_sha256"]) == 64
    assert data["parser"] == "packages/rules/mdg_parser.py"
    assert len(data["files"]) == 10
    for name in data["files"]:
        assert (KNOWLEDGE / name).is_file()


def test_handedit_wird_erkannt(sandbox) -> None:
    modul, kopie = sandbox
    ziel = kopie / "admbw-aliases.json"
    ziel.write_text(ziel.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert modul.check(MDG, False) == 1


def test_fehlende_datei_wird_erkannt(sandbox) -> None:
    modul, kopie = sandbox
    (kopie / "admbw-aliases.json").unlink()
    assert modul.check(MDG, False) == 1


def test_zusaetzliche_datei_wird_erkannt(sandbox) -> None:
    modul, kopie = sandbox
    (kopie / "admbw-veraltet.md").write_text("alt", encoding="utf-8")
    assert modul.check(MDG, False) == 1


def test_parser_aenderung_ohne_neuaufbau_wird_erkannt(sandbox) -> None:
    modul, kopie = sandbox
    assert modul.check(MDG, True) == 0
    data = json.loads((kopie / "PROVENANCE.json").read_text(encoding="utf-8"))
    data["parser_sha256"] = "0" * 64
    (kopie / "PROVENANCE.json").write_text(json.dumps(data), encoding="utf-8")
    assert modul.check(MDG, True) == 1


def test_pfadzeile_in_meta_wird_normalisiert(sandbox) -> None:
    """Der Aufrufpfad ist kein Inhalt: er darf den Vergleich nicht stoeren."""
    modul, _ = sandbox
    assert modul._normalize("admbw-meta.md", "- **MDG-Datei:** `tests/fixtures/x.xml`\n") \
        == "- **MDG-Datei:** `x.xml`\n"
    assert modul._normalize("admbw-stereotypes.json", "a b ") == "a b "


def test_parser_laeuft_allein() -> None:
    """Der kanonische Parser muss ohne Zusatzpakete laufen."""
    result = subprocess.run(
        [sys.executable, str(PARSER), str(MDG), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--out" in result.stdout
