"""Tests fuer die Herkunftskennung (``origin``) -- stabile GUIDs ueber das IR.

Zusage: Ein Element aus dem Standardkatalog behaelt seine ``ea_guid``, egal in
welchem Paket, unter welchem Namen und unter welcher Rolle es im Modell steht.
Neue Elemente bekommen eine deterministische Kennung; echte Zufallskennungen
bleiben die Ausnahme.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import qea_reader
import qea_writer
import toolbox_merge as tm

KATALOG_GUID = "{11111111-2222-3333-4444-555555555555}"


def _ir(elements: list[dict], packages: list[dict] | None = None) -> dict:
    return {
        "ir_version": 1,
        "technology": {"profile": ""},
        "packages": packages or [{"path": "Architektur"}],
        "elements": elements,
        "connectors": [],
        "diagrams": [],
    }


def _guids(path: Path) -> dict[str, str]:
    con = sqlite3.connect(str(path))
    try:
        return dict(
            con.execute(
                "select Name, ea_guid from t_object where Object_Type <> 'Package'"
            ).fetchall()
        )
    finally:
        con.close()


def test_origin_haelt_die_guid_beim_paketwechsel(tmp_path: Path) -> None:
    """Gleiche Herkunft, anderes Paket, anderer Name -- gleiche Kennung."""
    erst = qea_writer.write_qea(
        _ir(
            [
                {
                    "package": "Architektur",
                    "name": "Kampfpanzer",
                    "stereotype": "ResourceArchitecture",
                    "origin": "D-001/Kampfpanzer",
                }
            ]
        ),
        tmp_path / "a.qea",
    )
    zweit = qea_writer.write_qea(
        _ir(
            [
                {
                    "package": "Architektur/Systeme",
                    "name": "KPz Kampfpanzer",
                    "stereotype": "ResourceArchitecture",
                    "origin": "D-001/Kampfpanzer",
                }
            ],
            packages=[{"path": "Architektur"}, {"path": "Architektur/Systeme"}],
        ),
        tmp_path / "b.qea",
    )

    guid_a = _guids(erst)["Kampfpanzer"]
    guid_b = _guids(zweit)["KPz Kampfpanzer"]
    assert guid_a == guid_b, "Kennung ist an Paket oder Namen gebunden"


def test_ohne_origin_rechnet_der_writer_wie_bisher(tmp_path: Path) -> None:
    """Ohne Herkunft bleibt es beim Inhalts-Hash (unveraendertes Verhalten)."""
    pfad = qea_writer.write_qea(
        _ir([{"package": "Architektur", "name": "System X", "stereotype": "ResourceArchitecture"}]),
        tmp_path / "a.qea",
    )
    erwartet = qea_writer.guid_for("Architektur", "ResourceArchitecture", "System X")
    assert _guids(pfad)["System X"] == erwartet


def test_origin_ist_unabhaengig_von_der_rolle(tmp_path: Path) -> None:
    """Derselbe Katalogeintrag in anderer Rolle -- die Kennung bleibt."""
    eins = qea_writer.write_qea(
        _ir(
            [
                {
                    "package": "Architektur",
                    "name": "Kampfpanzer",
                    "stereotype": "Process",
                    "origin": "D-001/Kampfpanzer",
                }
            ]
        ),
        tmp_path / "a.qea",
    )
    zwei = qea_writer.write_qea(
        _ir(
            [
                {
                    "package": "Architektur",
                    "name": "Kampfpanzer",
                    "stereotype": "ServiceSpecification",
                    "origin": "D-001/Kampfpanzer",
                }
            ]
        ),
        tmp_path / "b.qea",
    )
    assert _guids(eins)["Kampfpanzer"] == _guids(zwei)["Kampfpanzer"]


def test_katalog_uebernahme_behaelt_guid_und_vermerkt_herkunft(tmp_path: Path) -> None:
    """Der Kasten-Eintrag kommt mit seiner Kennung an und traegt seine Herkunft."""
    katalog = qea_writer.write_qea(
        _ir(
            [
                {
                    "package": "Standard/Waffensysteme",
                    "name": "Kampfpanzer",
                    "stereotype": "ResourceArchitecture",
                }
            ],
            packages=[{"path": "Standard"}, {"path": "Standard/Waffensysteme"}],
        ),
        tmp_path / "katalog.qea",
    )
    con = sqlite3.connect(str(katalog))
    try:
        con.execute("update t_object set ea_guid = ? where Name = 'Kampfpanzer'", (KATALOG_GUID,))
        con.commit()
    finally:
        con.close()

    modell = qea_writer.write_qea(
        _ir([{"package": "Architektur", "name": "Bestand A", "ea_type": "Class"}]),
        tmp_path / "modell.qea",
    )

    out = tmp_path / "mit-katalog.qea"
    tm.merge_toolbox(modell, katalog, out, paketname="Standard")

    assert _guids(out)["Kampfpanzer"] == KATALOG_GUID
    con = sqlite3.connect(str(out))
    try:
        herkunft = con.execute(
            "select Value from t_objectproperties where Property = 'Herkunft'"
        ).fetchall()
    finally:
        con.close()
    assert [wert for (wert,) in herkunft] == ["katalog:ResourceArchitecture/Kampfpanzer"]


def test_zweiter_katalog_ergeben_keine_dublette(tmp_path: Path) -> None:
    """Element schon im Modell (andere Kennung, gleiche Herkunft) -- keine zweite Zeile."""
    katalog = qea_writer.write_qea(
        _ir(
            [
                {
                    "package": "Standard",
                    "name": "Kampfpanzer",
                    "ea_type": "Class",
                    "stereotype": "ResourceArchitecture",
                }
            ],
            packages=[{"path": "Standard"}],
        ),
        tmp_path / "katalog.qea",
    )

    # Modell enthaelt das Element schon -- mit anderer Kennung, aber gleicher Herkunft
    modell = qea_writer.write_qea(
        _ir(
            [
                {
                    "package": "Architektur",
                    "name": "Kampfpanzer",
                    "ea_type": "Class",
                    "stereotype": "ResourceArchitecture",
                }
            ]
        ),
        tmp_path / "modell.qea",
    )
    con = sqlite3.connect(str(modell))
    try:
        object_id = con.execute(
            "select Object_ID from t_object where Name = 'Kampfpanzer'"
        ).fetchone()[0]
        con.execute(
            "insert into t_objectproperties (PropertyID, Object_ID, Property, Value, Notes, ea_guid)"
            " values (?, ?, 'Herkunft', 'katalog:ResourceArchitecture/Kampfpanzer', '', ?)",
            (9001, object_id, "{AAAAAAAA-0000-0000-0000-000000009001}"),
        )
        con.commit()
    finally:
        con.close()

    out = tmp_path / "zusammen.qea"
    bericht = tm.merge_toolbox(modell, katalog, out, paketname="Standard")

    elemente = qea_reader.read_qea(out)["elements"]
    namen = [e["name"] for e in elemente]
    assert namen.count("Kampfpanzer") == 1, namen
    assert bericht["elemente"] == 0
