"""Der MDG-Parser bleibt die eigenständige Browser-Fassung.

Die Platform liefert den Parser mit Datei-Upload, fünf Ansichten und sechs
Exporten aus. Der Test hält fest, dass `dist/` wirklich die alte Fassung ist
und nicht wieder durch eine reine Tabellen-Seite ersetzt wird.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "mdg-web" / "index.html"
OUT = ROOT / "apps" / "mdg-web" / "dist" / "EAM-MDG-Parser.html"


PROMPT = ROOT / "apps" / "admbw-extractor" / "ADMBw-Prompt.md"


def test_auslieferung_ist_die_alte_fassung() -> None:
    if not OUT.is_file():
        pytest.skip("MDG-Parser nicht gebaut")
    # Der Master-Prompt wird beim Bauen eingesetzt; alles andere ist byte-gleich.
    erwartet = SRC.read_text(encoding="utf-8").replace(
        "{{MASTER_PROMPT}}", PROMPT.read_text(encoding="utf-8").strip("\n"), 1
    )
    assert OUT.read_text(encoding="utf-8") == erwartet
    assert "{{MASTER_PROMPT}}" not in OUT.read_text(encoding="utf-8")
    text = OUT.read_text(encoding="utf-8")
    assert 'id="file"' in text
    for ansicht in ("Stereotype", "Topologie", "Viewpoints", "Tag-Typen", "Stereotyp-Tags"):
        assert ansicht in text
    assert "downloadAll" in text
    assert "downloadMd" in text
    assert "5 Regeldateien" in text


def test_master_prompt_ist_downloadbar() -> None:
    """Der Prompt des ehemaligen Extraktors ist optionaler Teil des Parsers."""
    if not OUT.is_file():
        pytest.skip("MDG-Parser nicht gebaut")
    text = OUT.read_text(encoding="utf-8")
    assert "downloadPrompt" in text
    assert "ADMBw-Prompt.md" in text
    # Der Text steht vollstaendig in der Datei, nicht nur ein Verweis.
    prompt = PROMPT.read_text(encoding="utf-8").strip("\n")
    assert prompt in text
