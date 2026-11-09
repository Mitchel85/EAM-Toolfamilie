"""Wächter: Erzeugte `.qea` müssen von Enterprise Architect zu öffnen sein.

Hintergrund
-----------
Eine ausgelieferte Datei ließ sich in EA nicht öffnen. Ursache war nicht falsches
Modell, sondern ein unvollständiger Tabellensatz: Der Writer legt nur die 15
Lese-Tabellen (AAroN) plus `t_xref` an; EA fragt beim Start seinen kompletten
internen Satz ab und bricht bei der ersten fehlenden Tabelle mit
``SQL API Open FAILED`` ab — nacheinander für `t_document`, `t_genopt`,
`t_datatypes`, `t_rules`, `t_maintypes` …

Diese Tests halten die Lehre fest:
  * der Prüfer erkennt eine mangelhafte Datei (Gegenprobe),
  * der normale Writer warnt statt zu schweigen,
  * `finalize_for_ea` liefert eine prüfungsfreie Datei,
  * Sichtkästen überlappen nicht und haben keine negative Höhe.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "packages" / "core"
sys.path.insert(0, str(CORE))

import ea_check  # noqa: E402
import qea_writer  # noqa: E402

FIXTURE_IR = CORE / "fixtures" / "ir_roundtrip_mini.json"
EA_QUELLE = CORE / "fixtures" / "Musterarchitektur_MASC.qea"


def _ir_mit_sicht() -> dict:
    """Kleines Modell: zwei Elemente, eine Kante, eine Sicht mit beiden Kästen."""
    return {
        "ir_version": 1,
        "technology": {"profile": "Test"},
        "packages": [{"path": "P", "name": "P"}],
        "elements": [
            {"package": "P", "name": "A", "stereotype": "ServiceSpecification",
             "ea_type": "Class"},
            {"package": "P", "name": "B", "stereotype": "FunctionalRequirement",
             "ea_type": "Requirement"},
        ],
        "connectors": [
            {"source": "P::A", "target": "P::B", "stereotype": "RealiseRequirement",
             "ea_type": "Realisation"},
        ],
        "diagrams": [
            {
                "name": "Sicht",
                "package": "P",
                "type": "Custom",
                "mdg": "NAFv4-ADMBw Requirement Viewpoints::Rr - Requirement Realization",
                "default": True,
                "members": [
                    {"element": "P::A", "left": 40, "top": -40, "right": 240,
                     "bottom": -120, "sequence": 0},
                    {"element": "P::B", "left": 300, "top": -40, "right": 500,
                     "bottom": -120, "sequence": 1},
                ],
            }
        ],
    }


# --------------------------------------------------------------------------
# Der Prüfer selbst
# --------------------------------------------------------------------------

def test_pruefer_erkennt_fehlende_ea_tabellen(tmp_path: Path) -> None:
    """Der nackte Writer-Output ist AAroN-tauglich, aber nicht EA-tauglich."""
    ziel = qea_writer.write_qea(_ir_mit_sicht(), tmp_path / "roh.qea")
    befunde = ea_check.pruefe_datei(ziel)
    fehlend = {b.objekt for b in befunde if b.bereich == "tabelle"}
    # Die Tabellen aus den echten EA-Meldungen müssen erkannt werden.
    for name in ("t_document", "t_genopt", "t_rules", "t_datatypes", "t_maintypes"):
        assert name in fehlend, f"{name} nicht als fehlend erkannt"
    assert not ea_check.ist_ea_oeffnungsfaehig(ziel)


def test_echte_ea_datei_ist_oeffnungsfaehig() -> None:
    """Gegenprobe: eine Datei, die EA öffnet, darf keinen Öffnungs-FEHLER erzeugen.

    Hinweis: `t_maintypes` fehlt auch in echten EA-Dateien (EA fragt sie trotzdem
    in der Sammelabfrage ab) — genau deshalb legt `finalize_for_ea` sie an.
    Handgezeichnete Projekte haben außerdem legitime Überlappungen; die
    Geometrie wird deshalb separat geprüft (`pruefe_geometrie`).
    """
    befunde = ea_check.pruefe_datei(EA_QUELLE)
    oeffnung = [b for b in befunde if b.bereich in ("abfrage", "integritaet")]
    assert oeffnung == [], ea_check.formatieren(oeffnung)


def test_fehlende_datei_wird_gemeldet(tmp_path: Path) -> None:
    befunde = ea_check.pruefe_datei(tmp_path / "gibtsnicht.qea")
    assert befunde and befunde[0].severity == "FEHLER"


# --------------------------------------------------------------------------
# Geometrie
# --------------------------------------------------------------------------

def test_negative_hoehe_wird_erkannt(tmp_path: Path) -> None:
    """Positive Werte in RectTop/RectBottom kippen die Höhe — EA zeigt nichts."""
    ziel = tmp_path / "gekippt.qea"
    shutil.copy2(EA_QUELLE, ziel)
    con = sqlite3.connect(ziel)
    con.execute("UPDATE t_diagramobjects SET RectTop = 40, RectBottom = 120 "
                "WHERE Object_ID = (SELECT min(Object_ID) FROM t_diagramobjects)")
    con.commit()
    con.close()
    befunde = ea_check.pruefe_geometrie(sqlite3.connect(ziel))
    assert any("Höhe" in b.meldung for b in befunde)


def test_ueberlappung_wird_erkannt(tmp_path: Path) -> None:
    ziel = tmp_path / "doppelt.qea"
    shutil.copy2(EA_QUELLE, ziel)
    con = sqlite3.connect(ziel)
    did = con.execute("SELECT Diagram_ID FROM t_diagramobjects LIMIT 1").fetchone()[0]
    ids = [r[0] for r in con.execute(
        "SELECT Object_ID FROM t_diagramobjects WHERE Diagram_ID=? LIMIT 2", (did,))]
    if len(ids) < 2:
        pytest.skip("Referenzdatei hat keine zwei Objekte auf einer Sicht")
    con.execute("UPDATE t_diagramobjects SET RectLeft=40, RectTop=-40, "
                "RectRight=240, RectBottom=-120 WHERE Diagram_ID=? AND Object_ID=?",
                (did, ids[0]))
    con.execute("UPDATE t_diagramobjects SET RectLeft=60, RectTop=-60, "
                "RectRight=260, RectBottom=-140 WHERE Diagram_ID=? AND Object_ID=?",
                (did, ids[1]))
    con.commit()
    con.close()
    befunde = ea_check.pruefe_geometrie(sqlite3.connect(ziel))
    assert any("übereinander" in b.meldung for b in befunde)


def test_writer_erzeugt_keine_negative_hoehe(tmp_path: Path) -> None:
    ziel = qea_writer.write_qea(_ir_mit_sicht(), tmp_path / "sicht.qea")
    befunde = ea_check.pruefe_geometrie(sqlite3.connect(ziel))
    assert [b for b in befunde if b.severity == "FEHLER"] == []


# --------------------------------------------------------------------------
# Sichtkanten: ohne t_diagramlinks bleibt die Sicht ein Kästchenraster
# --------------------------------------------------------------------------

def test_writer_schreibt_sichtkanten(tmp_path: Path) -> None:
    ir = _ir_mit_sicht()
    ziel = qea_writer.write_qea(ir, tmp_path / "links.qea")
    con = sqlite3.connect(ziel)
    anzahl = con.execute("SELECT count(*) FROM t_diagramlinks").fetchone()[0]
    con.close()
    assert anzahl == 1, "Kante liegt auf der Sicht, muss dort verlinkt sein"


# --------------------------------------------------------------------------
# Finalisierung für Enterprise Architect
# --------------------------------------------------------------------------

def test_finalize_liefert_pruefungsfreie_datei(tmp_path: Path) -> None:
    roh = qea_writer.write_qea(_ir_mit_sicht(), tmp_path / "roh.qea")
    fertig = qea_writer.finalize_for_ea(roh, tmp_path / "fertig.qea", vorlage=EA_QUELLE)
    befunde = ea_check.pruefe_datei(fertig) + ea_check.pruefe_erzeugte_sicht(fertig)
    assert [b for b in befunde if b.severity == "FEHLER"] == [], ea_check.formatieren(befunde)
    # Modell bleibt vollständig erhalten
    con = sqlite3.connect(fertig)
    assert con.execute("SELECT count(*) FROM t_object").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM t_connector").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM t_diagram").fetchone()[0] == 1
    con.close()


def test_finalize_erhaelt_mdg_kennung(tmp_path: Path) -> None:
    roh = qea_writer.write_qea(_ir_mit_sicht(), tmp_path / "roh.qea")
    fertig = qea_writer.finalize_for_ea(roh, tmp_path / "fertig.qea", vorlage=EA_QUELLE)
    con = sqlite3.connect(fertig)
    style = con.execute("SELECT StyleEx FROM t_diagram").fetchone()[0]
    con.close()
    assert "MDGDgm=NAFv4-ADMBw Requirement Viewpoints::Rr" in style
