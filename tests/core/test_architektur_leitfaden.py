"""Tests fuer den leitfadenkonformen Architekturbau.

Der Bau folgt dem Leitfaden (Abbildung 1 und die xx-MK-Konventionen), nicht
der aelteren MASC-Musterarchitektur. Diese Tests halten die Struktur fest,
damit sie bei spaeteren Aenderungen nicht still zurückfaellt.
"""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

import architektur
import mdg_parser
import mdg_source
import qea_writer
import struktur
import validator

MDG = mdg_source.path()


@pytest.fixture(scope="module")
def rules():
    return mdg_parser.parse_mdg(MDG)


@pytest.fixture(scope="module")
def ir(rules):
    return architektur.build_architektur(
        rules,
        architektur.Auftrag(
            projekt="Testprojekt",
            titel="Testprojekt",
            architekt="Test",
            einstufung="OFFEN",
        ),
    )


def test_wurzeln_nach_abbildung_eins(ir) -> None:
    """StEKa steht neben dem Projekt, der Katalog liegt darunter (Abb. 1)."""
    wurzeln = {p["path"] for p in ir["packages"] if "/" not in p["path"]}
    assert "StEKa" in wurzeln
    assert "Testprojekt - Startseite" in wurzeln
    assert "Testprojekt - Glossar" in wurzeln
    assert "Testprojekt - Projektarchitektur" in wurzeln
    assert "Testprojekt - PBN-Architektur" in wurzeln


def test_perspektiven_tragen_die_leitfadennamen(ir) -> None:
    """Nicht die MASC-Namen (Architekturauftrag, Geschaeftsarchitektur ...)."""
    pfade = " ".join(p["path"] for p in ir["packages"])
    for name in (
        "Architecture Foundation",
        "Concepts",
        "Logical Specifications",
        "Physical Resource Specifications",
        "Service Specifications",
        "Requirements",
    ):
        assert name in pfade, f"Perspektive fehlt: {name}"
    for alt in ("Architekturauftrag", "Geschäftsarchitektur", "Systemarchitektur"):
        assert alt not in pfade, f"MASC-Name steht noch im Modell: {alt}"


def test_modellelementekatalog_liegt_unter_der_projektarchitektur(ir) -> None:
    """Der Katalog ist keine eigene Wurzel -- er gehoert zur Architektur."""
    katalog = [
        p["path"]
        for p in ir["packages"]
        if p["path"].startswith("Testprojekt - Projektarchitektur/Modellelementekatalog")
    ]
    assert katalog
    assert not any(
        p["path"].startswith("Modellelementekatalog") for p in ir["packages"]
    )


def test_viewpoints_und_views_liegen_zentral(ir) -> None:
    """A2-MK05/MK18: einmal anlegen, von den Sichten referenzieren."""
    viewpoint_pakete = {
        str(e.get("package") or "")
        for e in ir["elements"]
        if str(e.get("stereotype") or "") == "Viewpoint"
        and "Modellelementekatalog" not in str(e.get("package") or "")
    }
    assert len(viewpoint_pakete) == 1, f"Viewpoints verstreut: {viewpoint_pakete}"
    assert viewpoint_pakete.pop().endswith("A2/Viewpoints")


def test_meta_kanten_nach_a2_mk20(ir) -> None:
    """CONCERNFORVIEWPOINT verbindet Viewpoint und Analysebedarf."""
    kanten = [
        c for c in ir["connectors"] if c["stereotype"] == "ConcernForViewpoint"
    ]
    assert kanten
    quellen = {
        str(e.get("package") or "") + "::" + str(e.get("name") or "")
        for e in ir["elements"]
        if str(e.get("stereotype") or "") == "Viewpoint"
    }
    for kante in kanten:
        assert kante["source"] in quellen


def test_keine_leeren_sichten_ausser_fachlich_offenen(ir) -> None:
    """Sieben Sichten bleiben offen -- mit bekannter Begruendung.

    * Ar  -- ARCHITECTURALDESCRIPTION ist im MDG ein Paket-Stereotyp.
    * C1 (4x) und Cr -- der Leitfaden laesst dort ausschliesslich Elemente aus
      dem Standardelementekatalog zu; ohne StEKa ist die Sicht leer.
    * Sr  -- den Stereotyp CHANGE gibt es im MDG 2026.05 nicht.
    """
    leer = {d["name"] for d in ir["diagrams"] if not d.get("members")}
    # Nur noch Ar: die Konvention Ar-MK03 verlangt eine ARCHITECTURALDESCRIPTION,
    # die im MDG ein Paket-Stereotyp ist und deshalb nicht als Element auf einer
    # Sicht liegen kann.
    assert leer == {"Ar : Testprojekt : Architecture Roadmap"}, sorted(leer)


def test_mdg_pruefung_ist_sauber(ir, rules) -> None:
    """Ein Modell mit Attributionsfehlern waere in der Methodikpruefung wertlos."""
    findings = validator.validate_model(
        {
            "ir_version": 1,
            "technology": ir.get("technology", {}),
            "packages": ir["packages"],
            "elements": ir["elements"],
            "connectors": ir["connectors"],
            "diagrams": [],
        },
        validator.build_rules(rules),
    )
    fehler = [f for f in findings if f["severity"] == "error"]
    assert not fehler, fehler[:3]
    assert not [f for f in findings if f["severity"] == "warning"], findings[:3]


def test_qea_ist_lesbar_und_leitfadenkonform(ir, tmp_path: Path) -> None:
    """Die geschriebene Datei muss der Leitfaden-Pruefer ohne Fehler lesen."""
    ziel = tmp_path / "architektur.qea"
    qea_writer.write_qea(ir, ziel)
    findings = struktur.validate(struktur.from_qea(ziel), "Testprojekt")
    fehler = [f for f in findings if f.severity == "error"]
    assert not fehler, fehler[:3]


def test_mini_regelwerk_erzeugt_keine_unbekannten_stereotype(rules) -> None:
    """Ein fremdes Profil darf keine Elemente mit fremden Stereotypen bekommen."""
    mini = mdg_parser.parse_mdg(
        Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures" / "admbw_auszug.xml"
    )
    gebaut = architektur.build_architektur(
        mini,
        architektur.Auftrag(projekt="Mini", titel="Mini", architekt="", einstufung="OFFEN"),
    )
    bekannt = {
        str(e.get("name")) for e in mini.get("elementStereotypes") or ()
    }
    verwendet = {
        str(e.get("stereotype")) for e in gebaut["elements"] if e.get("stereotype")
    }
    assert verwendet <= bekannt, sorted(verwendet - bekannt)
