"""Tests fuer den leitfadenkonformen Architekturbau.

Der Bau folgt dem Leitfaden (Abbildung 1 und die xx-MK-Konventionen), nicht
der aelteren MASC-Musterarchitektur. Diese Tests halten die Struktur fest,
damit sie bei spaeteren Aenderungen nicht still zurückfaellt.
"""

from __future__ import annotations

import collections
import sqlite3
from pathlib import Path

import pytest

import architektur
import ea_check
import leitfaden
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


def test_paketstruktur_genau_nach_leitfaden(ir) -> None:
    """Die 45 Viewpoint-Pakete aus dem Auftrag liegen unter der Architektur.

    Quelle ist ``knowledge/leitfaden/pruefung.json`` (Abschnitt ``packages``).
    Die Schreibweise ``A2 - Stakeholder`` aus dem Konventionstext ist dort
    bewusst zu ``A2/Stakeholder`` normalisiert -- so verlangt es die
    verbindliche Struktur, und nur so haengen Stakeholder, Concerns und
    Viewpoints unter demselben A2-Paket.
    """
    arch = "Testprojekt - Projektarchitektur"
    pfade = {p["path"] for p in ir["packages"]}
    erwartet = {
        f"{arch}/" + leitfaden.expand_projekt(rule.path, "Testprojekt")
        for rule in leitfaden.PACKAGES
        if rule.viewpoint != "St"
    }
    assert len(erwartet) == 45
    fehlend = erwartet - pfade
    assert not fehlend, sorted(fehlend)
    assert not any("Architectural Foundation" in p for p in pfade)
    assert not any("A2 - Stakeholder" in p for p in pfade)


def test_pflichtsichten_vollstaendig(ir) -> None:
    """Jede Sicht aus dem Regelwerk existiert genau einmal."""
    assert len(leitfaden.DIAGRAMS) == 44
    assert len(ir["diagrams"]) == len(leitfaden.DIAGRAMS)
    namen = [d["name"] for d in ir["diagrams"]]
    assert len(namen) == len(set(namen))
    for name in (
        "L2-L3 : Testprojekt : Logical Concept",
        "C1-S1 : Testprojekt : Capability to Service Mapping",
        "S1 : Testprojekt : Service Taxonomy",
    ):
        assert name in namen, name


def test_keine_leere_sicht_ohne_hinweis(ir) -> None:
    """Eine Sicht ohne Element erfuellt ihren Zweck nicht.

    Wo der Leitfaden keinen Projektinhalt zulaesst (Ar: die
    ARCHITECTURALDESCRIPTION ist im MDG ein Paket-Stereotyp), haelt ein
    Note-Element die Sicht offen und benennt die Luecke.
    """
    leer = [d["name"] for d in ir["diagrams"] if not d.get("members")]
    assert not leer, leer
    ar = next(d for d in ir["diagrams"] if d["name"] == "Ar : Testprojekt : Architecture Roadmap")
    ref = str(ar["members"][0]["element"])
    assert "::Nicht belegt:" in ref
    note = next(e for e in ir["elements"] if f"{e['package']}::{e['name']}" == ref)
    assert note["ea_type"] == "Note"
    assert "Ar-MK02" in note["notes"]


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


def test_sichtgeometrie_ist_ea_konform(ir, tmp_path: Path) -> None:
    """Keine negative Kastenhoehe und keine Ueberlappung in der .qea.

    Die IR-Koordinaten der Sichtmitglieder sind EA-Koordinaten: y waechst nach
    unten und wird negativ gespeichert, RectTop liegt naeher an 0 als
    RectBottom. Ein positiver ``top`` kippt die Hoehe und EA zeigt nichts.
    """
    ziel = tmp_path / "geometrie.qea"
    qea_writer.write_qea(ir, ziel)
    con = sqlite3.connect(ziel)
    try:
        befunde = ea_check.pruefe_geometrie(con)
    finally:
        con.close()
    fehler = [b for b in befunde if b.severity == "FEHLER"]
    assert not fehler, [b.meldung for b in fehler[:5]]


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


def test_ohne_sichten_bleibt_die_struktur_stehen(rules) -> None:
    """``mit_sichten=False`` liefert Pakete, Elemente und Kanten -- aber kein Diagramm.

    Fuer Pipelines (Pruefung, Dashboard, QEA-Analyse) sind Sichten ohne Wert;
    der Paketbaum und die belegten Elemente muessen trotzdem vollstaendig sein.
    """
    ohne = architektur.build_architektur(
        rules,
        architektur.Auftrag(projekt="OhneSichten", titel="OhneSichten", architekt="", einstufung="OFFEN"),
        mit_sichten=False,
    )
    mit = architektur.build_architektur(
        rules,
        architektur.Auftrag(projekt="OhneSichten", titel="OhneSichten", architekt="", einstufung="OFFEN"),
    )
    assert ohne["diagrams"] == []
    assert mit["diagrams"], "Gegenprobe: mit Sichten entstehen Diagramme"
    assert ohne["packages"] == mit["packages"], "Paketbaum darf sich nicht unterscheiden"
    assert {e["name"] for e in ohne["elements"]} <= {e["name"] for e in mit["elements"]}
    # Keine View-Elemente ohne Sichten: sie wuerden ins Leere zeigen.
    # (Der Katalogeintrag "View" bleibt -- er beschreibt den Stereotyp.)
    view_ablage = "Architecture Foundation/A2/Viewpoints/Views"
    assert not [
        e for e in ohne["elements"]
        if str(e.get("package") or "").endswith(view_ablage)
        and str(e.get("stereotype") or "") == "View"
    ]


def test_sichten_bleiben_ueberschaubar(ir) -> None:
    """Eine Sicht mit mehr als 30 Kaestchen ist keine Sicht mehr, sondern ein Raster."""
    groesste = max((len(d.get("members") or ()) for d in ir["diagrams"]), default=0)
    assert 0 < groesste <= 30, groesste
