"""Tests fuer das optionale IR-Feld ``guid`` und ``xref_tags`` im Writer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import qea_writer as qw

GUID_P1 = "{AAAA0000-0000-0000-0000-000000000001}"
GUID_P2 = "{AAAA0000-0000-0000-0000-000000000002}"
GUID_E1 = "{EEEE0000-0000-0000-0000-000000000010}"
GUID_E2 = "{EEEE0000-0000-0000-0000-000000000011}"
GUID_C1 = "{CCCC0000-0000-0000-0000-000000000005}"


def _ir(**overrides):
    ir = {
        "ir_version": 1,
        "packages": [
            {"path": "Wurzel", "guid": GUID_P1},
            {"path": "Wurzel/Kind", "guid": GUID_P2},
        ],
        "elements": [
            {
                "package": "Wurzel/Kind",
                "name": "Alpha",
                "ea_type": "Class",
                "stereotype": "System",
                "guid": GUID_E1,
                "tags": {"Richtung": "eingehend"},
                "xref_tags": {"Quelle": "Referenz, mit Komma"},
            },
            {
                "package": "Wurzel/Kind",
                "name": "Beta",
                "ea_type": "Class",
                "guid": GUID_E2,
            },
        ],
        "connectors": [
            {
                "source": "Wurzel/Kind::Alpha",
                "target": "Wurzel/Kind",
                "ea_type": "Dependency",
                "guid": GUID_C1,
            }
        ],
    }
    ir.update(overrides)
    return ir


def _rows(path: Path, sql: str):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_guid_wird_verbatim_geschrieben(tmp_path: Path) -> None:
    ziel = tmp_path / "guid.qea"
    qw.write_qea(_ir(), ziel)

    assert {row[0] for row in _rows(ziel, "SELECT ea_guid FROM t_package")} == {GUID_P1, GUID_P2}
    objekte = dict(_rows(ziel, "SELECT Name, ea_guid FROM t_object"))
    assert objekte["Alpha"] == GUID_E1
    assert objekte["Beta"] == GUID_E2
    assert objekte["Kind"] == GUID_P2  # Paketspiegel traegt die Paket-GUID
    assert _rows(ziel, "SELECT ea_guid FROM t_connector") == [(GUID_C1,)]
    assert _rows(ziel, "PRAGMA integrity_check") == [("ok",)]


def test_guid_ohne_klammern_und_klein_geschrieben(tmp_path: Path) -> None:
    """Klammern werden ergaenzt, die Schreibweise bleibt woertlich."""
    ir = _ir()
    klein = GUID_P1.strip("{}").lower()
    ir["packages"][0]["guid"] = klein
    ir["elements"][0]["guid"] = GUID_E1.strip("{}")
    qw.write_qea(ir, tmp_path / "klein.qea")
    assert {row[0] for row in _rows(tmp_path / "klein.qea", "SELECT ea_guid FROM t_package")} == {
        "{" + klein + "}",
        GUID_P2,
    }
    objekte = dict(_rows(tmp_path / "klein.qea", "SELECT Name, ea_guid FROM t_object"))
    assert objekte["Alpha"] == GUID_E1


def test_doppelte_guid_wird_abgelehnt(tmp_path: Path) -> None:
    ir = _ir()
    ir["elements"][1]["guid"] = GUID_E1
    with pytest.raises(qw.QeaWriterError, match="doppelte GUID"):
        qw.write_qea(ir, tmp_path / "doppelt.qea")


def test_guid_zwischen_paket_und_element_kollidiert(tmp_path: Path) -> None:
    ir = _ir()
    ir["elements"][0]["guid"] = GUID_P2
    with pytest.raises(qw.QeaWriterError, match="doppelte GUID"):
        qw.write_qea(ir, tmp_path / "kollision.qea")


def test_ungueltige_guid_wird_abgelehnt(tmp_path: Path) -> None:
    ir = _ir()
    ir["elements"][0]["guid"] = "keine-guid"
    with pytest.raises(qw.QeaWriterError, match="GUID"):
        qw.write_qea(ir, tmp_path / "kaputt.qea")


def test_ohne_guid_bleibt_das_bisherige_verhalten(tmp_path: Path) -> None:
    ir = _ir()
    for paket in ir["packages"]:
        paket.pop("guid")
    for element in ir["elements"]:
        element.pop("guid")
    for kante in ir["connectors"]:
        kante.pop("guid")
    qw.write_qea(ir, tmp_path / "alt.qea")

    objekte = dict(_rows(tmp_path / "alt.qea", "SELECT Name, ea_guid FROM t_object"))
    assert objekte["Alpha"] == qw.guid_for("Wurzel/Kind", "System", "Alpha")
    assert _rows(tmp_path / "alt.qea", "SELECT count(*) FROM t_package") == [(2,)]


def test_xref_tags_landen_in_t_xref_und_nicht_in_objectproperties(tmp_path: Path) -> None:
    ziel = tmp_path / "xref.qea"
    qw.write_qea(_ir(), ziel)

    tags = _rows(
        ziel,
        "SELECT Property, Value FROM t_objectproperties p "
        "JOIN t_object o ON o.Object_ID = p.Object_ID WHERE o.Name = 'Alpha'",
    )
    assert tags == [("Richtung", "eingehend")]
    xref = _rows(
        ziel,
        "SELECT Name, Type, Description, Client FROM t_xref WHERE Name = 'CustomProperties'",
    )
    assert len(xref) == 1
    name, typ, description, client = xref[0]
    assert name == "CustomProperties"
    assert typ == "element property"
    assert client == GUID_E1
    assert "@NAME=Quelle@ENDNAME;" in description
    assert "@VALU=Referenz, mit Komma@ENDVALU;" in description


def test_guid_feld_ist_rueckwaertskompatibel_im_plan() -> None:
    plan = qw.plan_model(_ir())
    assert [p.guid for p in plan.packages] == [GUID_P1, GUID_P2]
    assert [e.guid for e in plan.elements] == [GUID_E1, GUID_E2]
    assert [c.guid for c in plan.connectors] == [GUID_C1]
    assert any(row[1] == "CustomProperties" for row in plan.xrefs)


def test_gemischte_schreibweise_bleibt_woertlich(tmp_path: Path) -> None:
    """Eine Kennung aus Katalog oder Startpaket kommt Zeichen fuer Zeichen zurueck."""
    gemischt = "{ABCD0000-12ab-34CD-56ef-0000000000a1}"
    ir = _ir()
    ir["elements"][0]["guid"] = gemischt
    qw.write_qea(ir, tmp_path / "gemischt.qea")
    objekte = dict(_rows(tmp_path / "gemischt.qea", "SELECT Name, ea_guid FROM t_object"))
    assert objekte["Alpha"] == gemischt


def test_kennung_nur_in_schreibweise_verschieden_ist_doppelt(tmp_path: Path) -> None:
    ir = _ir()
    ir["elements"][0]["guid"] = GUID_E1.lower()
    ir["elements"][1]["guid"] = GUID_E1
    with pytest.raises(qw.QeaWriterError, match="doppelte GUID"):
        qw.write_qea(ir, tmp_path / "doppelt.qea")
