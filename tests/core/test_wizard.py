"""Tests fuer den Abgleich mit den Model-Wizard-Vorlagen des ADMBw.

Die Vorlagen liegen unter ``knowledge/modelwizard`` (52 XML/RTF-Paare,
BAAINBw). Sie sind der Massstab je Viewpoint; der Leitfaden ist der Massstab
fuer die Architektur als Ganzes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import architektur
import leitfaden
import mdg_parser
import mdg_source
import struktur
import wizard

VORLAGEN = Path(__file__).resolve().parents[2] / "knowledge" / "modelwizard"


@pytest.fixture(scope="module")
def vorlagen():
    if not VORLAGEN.is_dir():
        pytest.skip("Model-Wizard-Vorlagen nicht vorhanden")
    return wizard.lade_alle(VORLAGEN)


@pytest.fixture(scope="module")
def ir():
    rules = mdg_parser.parse_mdg(mdg_source.path())
    return architektur.build_architektur(
        rules,
        architektur.Auftrag(
            projekt="Testprojekt", titel="Testprojekt", architekt="", einstufung="OFFEN"
        ),
    )


def test_vorlagen_sind_vollstaendig(vorlagen) -> None:
    """52 Viewpoints, jeder mit XML und RTF."""
    assert len(vorlagen) == 52
    assert all(v.rtf for v in vorlagen.values()), [
        n for n, v in vorlagen.items() if not v.rtf
    ]


def test_vorlage_enthaelt_diagramm_und_elemente(vorlagen) -> None:
    """Eine Vorlage ohne Diagramm waere als Modellmuster wertlos."""
    a2 = vorlagen["A2 - Architecture Products"]
    assert a2.diagramme
    assert a2.elemente
    assert "Viewpoint" in a2.stereotype
    assert "View" in a2.stereotype


def test_parser_liest_stereotype(vorlagen) -> None:
    s3 = vorlagen["S3 - Service Interfaces"]
    assert {"ServiceInterface", "ServiceSpecification"} <= set(s3.stereotype)


def test_abgleich_ohne_fehler(ir, vorlagen) -> None:
    """Alle Viewpoints im Leitfaden-Geltungsbereich haben Paket und Sicht."""
    befund = wizard.vergleiche(
        ir,
        vorlagen,
        geltungsbereich={d.viewpoint for d in leitfaden.DIAGRAMS if d.viewpoint},
        pflichtstereotype={
            code: list(werte) for code, werte in leitfaden.PFLICHT_STEREOTYPE.items()
        },
    )
    fehler = [b for b in befund if b.severity == "error"]
    assert not fehler, [f"{b.viewpoint}: {b.message}" for b in fehler[:5]]


def test_pflichtstereotype_liegen_auf_den_sichten(ir, vorlagen) -> None:
    """Was der Leitfaden verlangt und die Vorlage zeigt, muss die Sicht zeigen."""
    befund = wizard.vergleiche(
        ir,
        vorlagen,
        geltungsbereich={d.viewpoint for d in leitfaden.DIAGRAMS if d.viewpoint},
        pflichtstereotype={
            code: list(werte) for code, werte in leitfaden.PFLICHT_STEREOTYPE.items()
        },
    )
    warnungen = [b for b in befund if b.severity == "warning"]
    assert not warnungen, [f"{b.viewpoint}: {b.message}" for b in warnungen]


def test_viewpoints_ausserhalb_des_leitfadens_sind_hinweise(ir, vorlagen) -> None:
    """Der Wizard deckt 52 Viewpoints ab, der Leitfaden nur 26."""
    befund = wizard.vergleiche(
        ir,
        vorlagen,
        geltungsbereich={d.viewpoint for d in leitfaden.DIAGRAMS if d.viewpoint},
        pflichtstereotype={
            code: list(werte) for code, werte in leitfaden.PFLICHT_STEREOTYPE.items()
        },
    )
    infos = [b for b in befund if b.severity == "info"]
    assert infos
    assert all("Geltungsbereich" in b.message for b in infos)


def test_fehlt_das_verzeichnis_ist_das_ein_fehler() -> None:
    with pytest.raises(FileNotFoundError):
        wizard.lade_alle("/nonexistent/modelwizard")
