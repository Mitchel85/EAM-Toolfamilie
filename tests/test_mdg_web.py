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


def test_auslieferung_ist_die_alte_fassung() -> None:
    if not OUT.is_file():
        pytest.skip("MDG-Parser nicht gebaut")
    assert OUT.read_bytes() == SRC.read_bytes()
    text = OUT.read_text(encoding="utf-8")
    assert 'id="file"' in text
    for ansicht in ("Stereotype", "Topologie", "Viewpoints", "Tag-Typen", "Stereotyp-Tags"):
        assert ansicht in text
    assert "downloadAll" in text
    assert "downloadMd" in text
    assert "5 Regeldateien" in text
