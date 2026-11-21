"""Tests fuer ``skeleton_arch`` -- Geruest in MASC-Struktur.

Warum eigene Tests: Das Geruest ist die Antwort auf die Frage "warum steht so
wenig in der .qea". Es muss belegen, dass (a) die Paketstruktur der
Musterarchitektur entsteht, (b) der Katalog vollstaendig aus dem Regelwerk
kommt, (c) nichts erfunden wird und (d) die Datei schreibbar und ruecklesbar
ist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent          # tests/core
ROOT = HERE.parent.parent                        # Projektwurzel
CORE = ROOT / "packages" / "core"
RULES = ROOT / "packages" / "rules"
for path in (CORE, RULES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import skeleton_arch  # noqa: E402

MDG = RULES / "NAFv4-ADMBw-MDG-2026.05.xml"


@pytest.fixture(scope="module")
def rules():
    import mdg_parser

    return mdg_parser.parse_mdg(MDG)


@pytest.fixture(scope="module")
def ir(rules):
    return skeleton_arch.build_arch_skeleton(rules, package="Projektarchitektur")


def _paths(ir):
    return {entry["path"] for entry in ir["packages"]}


def test_volumes_and_katalog_exist(ir):
    paths = _paths(ir)
    base = "Projektarchitektur/Projektarchitektur - Idealtypische Architektur"
    for volume in ("Architekturauftrag", "Geschäftsarchitektur", "Servicearchitektur",
                   "Systemarchitektur", "Anforderungen", "Modellelementekatalog"):
        assert f"{base}/{volume}" in paths, volume
    assert "Projektarchitektur/Startseite Projektarchitektur" in paths
    assert "Projektarchitektur/Viewpoints (Gesamtgefüge)" in paths
    assert "Projektarchitektur/Projektarchitektur - Glossar/Abkürzungsverzeichnis" in paths


def test_keine_metaklassenpakete(ir):
    """Der alte Weg legte Pakete wie ``Class``/``Object`` an -- die gibt es hier nicht."""
    namen = {path.rsplit("/", 1)[-1] for path in _paths(ir)}
    for technisch in ("Class", "Object", "Part", "Slot", "StateMachine"):
        assert technisch not in namen, technisch


def test_katalog_kommt_aus_dem_regelwerk(ir, rules):
    elemente = [e for e in ir["elements"] if "/Modellelementekatalog/" in e["package"]]
    instanziierbar = [
        entry for entry in rules["elementStereotypes"]
        if [m for m in entry.get("metaclasses") or [] if str(m).strip().lower() != "package"]
        and entry.get("abstract") is not True
    ]
    assert len(elemente) == len(instanziierbar)
    # Jedes Element traegt den Stereotyp, den es beschreibt.
    assert all(entry["stereotype"] == entry["name"] for entry in elemente)
    # Keine leeren Notizen: jede Beschreibung stammt aus dem Regelwerk oder nennt
    # ihre Herkunft ("Element-Stereotyp ... aus dem Regelwerk").
    assert all(entry["notes"].strip() for entry in elemente)


def test_viewpoints_vollstaendig(ir, rules):
    view = [e for e in ir["elements"] if e["stereotype"] == "Viewpoint"
            and "/Viewpoints (Gesamtgefüge)/" in e["package"]]
    assert len(view) == len(rules["viewpoints"])


def test_determinismus(rules):
    first = json.dumps(skeleton_arch.build_arch_skeleton(rules, package="P"), sort_keys=True)
    second = json.dumps(skeleton_arch.build_arch_skeleton(rules, package="P"), sort_keys=True)
    assert first == second


def test_keine_erfundenen_namen(ir, rules):
    """Jeder Name stammt aus dem Regelwerk oder ist eine dokumentierte Struktur."""
    erlaubt_struktur = {
        "Beispielarchitektur", "Projektarchitektur", "Projektarchitektur - Glossar",
        "Projektarchitektur - Idealtypische Architektur", "Startseite Projektarchitektur",
        "Viewpoints (Gesamtgefüge)", "Abkürzungsverzeichnis", "Modellelementekatalog",
        "Architekturauftrag", "Geschäftsarchitektur", "Servicearchitektur",
        "Systemarchitektur", "Anforderungen",
    }
    bekannt = {entry["name"] for entry in rules["elementStereotypes"]}
    bekannt |= {str(vp.get("name")) for vp in rules["viewpoints"]}
    bekannt |= {str(vp.get("name")).split(" - ", 1)[-1] for vp in rules["viewpoints"]}
    for entry in ir["elements"]:
        if entry["name"] in erlaubt_struktur:
            continue
        assert entry["name"] in bekannt, entry["name"]


def test_qea_schreibbar_und_ruecklesbar(ir, tmp_path):
    from qea_reader import read_qea
    from qea_writer import write_qea

    ziel = tmp_path / "geruest.qea"
    write_qea(ir, ziel)
    back = read_qea(ziel)
    assert len(back["packages"]) == len(ir["packages"])
    assert len(back["elements"]) == len(ir["elements"])


def test_ungueltiges_paket(rules):
    with pytest.raises(skeleton_arch.ArchSkeletonError):
        skeleton_arch.build_arch_skeleton(rules, package="A\\B")
