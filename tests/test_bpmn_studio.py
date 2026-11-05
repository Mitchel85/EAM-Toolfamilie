"""Das BPMN Studio ist eine Einzeldatei ohne Netz und kennt den Auftrag."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATEI = ROOT / "apps" / "bpmn-studio" / "dist" / "BPMN-Studio.html"


def test_studio_ist_gebaut_und_offline() -> None:
    text = DATEI.read_text(encoding="utf-8")
    assert len(text) > 500_000, "Studio zu klein -- vermutlich nicht gebaut"
    # Keine externen Ressourcen. Verweise (bpmn.io-Lizenz) sind erlaubt, Ladungen nicht.
    assert not re.search(r'src="https?://', text), "externes Skript geladen"
    assert not re.search(r'<link[^>]+href="https?://', text), "externes Stylesheet geladen"
    assert "url(http" not in text, "externe Schrift oder Grafik geladen"
    assert "bpmn-js" in text or "BpmnModeler" in text


def test_studio_kennt_den_auftrag() -> None:
    text = DATEI.read_text(encoding="utf-8")
    assert 'id="text-auftrag"' in text
    assert "abschnittFuerAuftrag" in text
    assert "Prozess Rechnungslauf" in text  # Beispiel im Platzhalter


def test_studio_marken_sind_gesetzt() -> None:
    text = DATEI.read_text(encoding="utf-8")
    for marke in ("ADMBw", "BPMN 2.0", "SVG", "PNG"):
        assert marke in text
