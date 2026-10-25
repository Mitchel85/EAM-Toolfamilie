"""Tests fuer die uebernommenen Werkzeuge und ihre eine Wissensquelle.

Die drei ADMBw-Werkzeuge liegen jetzt als Apps im Monorepo. Ihre Wissensdateien
sind **Symlinks** auf ``knowledge/`` — keine zweiten Kopien. Dieser Test haelt
das fest: wer einen Symlink durch eine Kopie ersetzt, macht den Lauf rot.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"

BATCH = ROOT / "apps" / "admbw-batch"
EXTRACTOR = ROOT / "apps" / "admbw-extractor"
SCRIPT_MAKER = ROOT / "apps" / "admbw-script-maker"

GENERATED = {
    "ADMBw-Stereotypes.json": "admbw-stereotypes.json",
    "ADMBw-Aliases.json": "admbw-aliases.json",
    "ADMBw-Meta.md": "admbw-meta.md",
    "ADMBw-Prompt.md": "admbw-prompt.md",
    "ADMBw-Knowledge-Stereotypes.md": "admbw-knowledge-stereotypes.md",
    "ADMBw-Knowledge-Topology.md": "admbw-knowledge-topology.md",
    "ADMBw-Knowledge-Viewpoints.md": "admbw-knowledge-viewpoints.md",
    "ADMBw-Knowledge-TagTypes.md": "admbw-knowledge-tagtypes.md",
    "ADMBw-Knowledge-Stereotype-Tags.md": "admbw-knowledge-stereotype-tags.md",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("app", [BATCH, EXTRACTOR])
def test_wissensdateien_sind_symlinks(app: Path) -> None:
    for alt, neu in GENERATED.items():
        pfad = app / alt
        assert pfad.is_symlink(), f"{pfad} ist eine Kopie, kein Verweis"
        assert pfad.resolve() == (KNOWLEDGE / neu).resolve()
        assert _sha(pfad) == _sha(KNOWLEDGE / neu)


def test_script_maker_verweist_auf_dieselbe_quelle() -> None:
    for alt, neu in [
        ("admbw-stereotypes.json", "admbw-stereotypes.json"),
        ("admbw-aliases.json", "admbw-aliases.json"),
        ("admbw-knowledge-stereotypes.md", "admbw-knowledge-stereotypes.md"),
    ]:
        pfad = SCRIPT_MAKER / "references" / alt
        assert pfad.is_symlink(), f"{pfad} ist eine Kopie, kein Verweis"
        assert pfad.resolve() == (KNOWLEDGE / neu).resolve()


def test_connectors_kommen_aus_der_wissensbasis() -> None:
    """Die Connectors-Uebersicht war bis 24.10. in drei Apps von Hand gepflegt.

    Seit der Konsolidierung wird sie aus dem Regelwerk erzeugt; die Apps lesen
    sie ueber einen Symlink. Eine regulaere Datei hier waere eine zweite Quelle.
    """
    for app in (BATCH, EXTRACTOR):
        pfad = app / "ADMBw-Knowledge-Connectors.md"
        assert pfad.is_symlink(), pfad
        assert pfad.resolve() == (KNOWLEDGE / "admbw-knowledge-connectors.md").resolve()


def test_batch_und_extractor_pruefen_sich_selbst() -> None:
    for app, name in ((BATCH, "Batch"), (EXTRACTOR, "Extractor")):
        result = subprocess.run(
            [sys.executable, "checks/verify.py"],
            cwd=app,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS" in result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt")
def test_script_maker_tests() -> None:
    result = subprocess.run(
        ["node", "tests/run_tests.js"],
        cwd=SCRIPT_MAKER,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"FAIL":0' in result.stdout


def test_prompt_und_wissen_sind_im_monorepo_eine_quelle() -> None:
    """Kein generierter Wissensstand liegt doppelt mit anderem Hash."""
    gesehen: dict[str, str] = {}
    for app in (BATCH, EXTRACTOR):
        for alt, neu in GENERATED.items():
            digest = _sha(app / alt)
            if neu in gesehen:
                assert gesehen[neu] == digest
            gesehen[neu] = digest
    for neu, digest in gesehen.items():
        assert digest == _sha(KNOWLEDGE / neu), f"abweichende Kopie: {neu}"
