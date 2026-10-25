"""Der Auslieferungsgraph: jede Zelle vorhanden, jede Kante aufgelöst.

Der Test hält das fest, was `scripts/verify_graph.py` für Nutzer ausgibt:
Wer eine neue Auslieferung anlegt, ohne sie zu verbinden, bekommt hier einen
Fehler — nicht erst beim Suchenden.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _modul():
    pfad = ROOT / "scripts" / "verify_graph.py"
    spec = importlib.util.spec_from_file_location("verify_graph", pfad)
    modul = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(modul)
    return modul


def test_jede_zelle_ist_verbunden() -> None:
    if not (ROOT / "apps" / "mdg-web" / "dist" / "EAM-MDG-Parser.html").is_file():
        pytest.skip("Auslieferungen nicht gebaut")
    bericht = _modul().pruefe()
    assert bericht["befunde"] == [], "\n".join(bericht["befunde"])
    assert len(bericht["knoten"]) == 12


def test_jede_abhaengigkeit_zeigt_auf_eine_zelle() -> None:
    bericht = _modul().pruefe()
    namen = {k["name"] for k in bericht["knoten"]}
    for k in bericht["knoten"]:
        for feld in ("dependencies", "devDependencies"):
            for abhaengig in k[feld]:
                assert abhaengig in namen, f"{k['path']} -> {abhaengig}"


def test_vendor_ist_eine_zelle_und_die_html_apps_haengen_daran() -> None:
    bericht = _modul().pruefe()
    knoten = {k["path"]: k for k in bericht["knoten"]}
    assert knoten["vendor"]["name"] == "@mitchel85/eam-vendor"
    for app in ("apps/html-suite", "apps/html-analyzer", "apps/html-editor"):
        assert "@mitchel85/eam-vendor" in knoten[app]["devDependencies"]
    assert knoten["apps/mdg-web"]["dependencies"] == {}


def test_wissensbasis_wird_nicht_kopiert() -> None:
    bericht = _modul().pruefe()
    kopien = [b for b in bericht["befunde"] if "Kopie statt Symlink" in b]
    assert kopien == []


def test_wichtigste_auslieferungen_existieren() -> None:
    if not (ROOT / "apps" / "mdg-web" / "dist" / "EAM-MDG-Parser.html").is_file():
        pytest.skip("Auslieferungen nicht gebaut")
    artefakte = {a["path"] for a in _modul().pruefe()["artefakte"]}
    erwartet = {
        "apps/html-suite/dist/EAM-AI-Suite.html",
        "apps/html-suite/dist/EAM-AI-Suite.aspx",
        "apps/html-analyzer/dist/EAM-QEA-Analyzer.html",
        "apps/html-analyzer/dist/EAM-QEA-Analyzer.aspx",
        "apps/html-editor/dist/EAM-Suite.html",
        "apps/html-editor/dist/EAM-Suite.aspx",
        "apps/mdg-web/dist/EAM-MDG-Parser.html",
    }
    assert erwartet == artefakte
