"""Test fuer das uebernommene Extractor-Werkzeug und seine eine Wissensquelle.

Der ADMBw-Extractor liegt als App im Monorepo. Seine Wissensdateien sind
**Symlinks** auf ``knowledge/`` — keine zweiten Kopien. Dieser Test haelt
das fest: wer einen Symlink durch eine Kopie ersetzt, macht den Lauf rot.

(Nachtrag 05.11.2026: `apps/admbw-batch` und `apps/admbw-script-maker` sind
entfernt. Der JSON-Batch wird als Exportformat in `packages/core` ueberfuehrt;
die Batch-Pruefdateien liegen unter `packages/core/fixtures/batch-*`.)
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"

EXTRACTOR = ROOT / "apps" / "admbw-extractor"

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


def test_wissensdateien_sind_symlinks() -> None:
    for alt, neu in GENERATED.items():
        pfad = EXTRACTOR / alt
        assert pfad.is_symlink(), f"{pfad} ist eine Kopie, kein Verweis"
        assert pfad.resolve() == (KNOWLEDGE / neu).resolve()
        assert _sha(pfad) == _sha(KNOWLEDGE / neu)


def test_connectors_kommen_aus_der_wissensbasis() -> None:
    """Die Connectors-Uebersicht war bis 24.10. in drei Apps von Hand gepflegt.

    Seit der Konsolidierung wird sie aus dem Regelwerk erzeugt; die App liest
    sie ueber einen Symlink. Eine regulaere Datei hier waere eine zweite Quelle.
    """
    pfad = EXTRACTOR / "ADMBw-Knowledge-Connectors.md"
    assert pfad.is_symlink(), pfad
    assert pfad.resolve() == (KNOWLEDGE / "admbw-knowledge-connectors.md").resolve()


def test_extractor_prueft_sich_selbst() -> None:
    result = subprocess.run(
        [sys.executable, "checks/verify.py"],
        cwd=EXTRACTOR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_prompt_und_wissen_sind_im_monorepo_eine_quelle() -> None:
    """Kein generierter Wissensstand liegt doppelt mit anderem Hash."""
    for alt, neu in GENERATED.items():
        assert _sha(EXTRACTOR / alt) == _sha(KNOWLEDGE / neu), f"abweichende Kopie: {neu}"
