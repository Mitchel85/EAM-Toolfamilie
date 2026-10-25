"""Die Änderungsmatrix und die erzeugte Abhängigkeitskarte bleiben konsistent."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dependency_report  # noqa: E402
from dependency_rules import treffer, zellen  # noqa: E402


def test_mdg_aenderung_trifft_wissensbasis_und_downstream() -> None:
    regeln = treffer("packages/rules/mdg_parser.py")
    assert any(r["id"] == "mdg-quelle" for r in regeln)
    assert "knowledge" in zellen(["packages/rules/mdg_parser.py"])
    assert "apps/admbw-batch" in zellen(["packages/rules/mdg_parser.py"])


def test_vendor_aenderung_trifft_alle_html_apps() -> None:
    betroffen = zellen(["vendor/sql-wasm.js"])
    for app in ("apps/html-suite", "apps/html-analyzer", "apps/html-editor"):
        assert app in betroffen


def test_unbekannter_pfad_hat_keine_regel() -> None:
    assert treffer("README.md") == []


def test_bericht_ist_aktuell() -> None:
    assert dependency_report.render() == dependency_report.ZIEL.read_text(encoding="utf-8")


def test_impact_gibt_maschinenlesbar_aus() -> None:
    ergebnis = subprocess.run(
        [sys.executable, "scripts/impact.py", "--changed", "vendor/sql-wasm.js", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    daten = json.loads(ergebnis.stdout)
    assert "apps/html-suite" in daten["zellen"]
    assert any(r["id"] == "vendor" for r in daten["regeln"])
