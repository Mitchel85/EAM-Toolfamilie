"""Kennungen bleiben: Katalogelemente behalten ihre GUID ueber den gesamten Weg.

Abnahme fuer die Anforderung aus der Architekturarbeit:

* Ein Element aus dem Standardkatalog behaelt seine ``ea_guid`` -- beim
  Uebernehmen, beim Umziehen in ein anderes Paket, beim erneuten Ausgeben.
* Der Weg ``.qea -> IR -> .qea`` ist stabil, auch mehrfach hintereinander.
* Nur neue Elemente bekommen eine eigene (deterministische) Kennung.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import qea_reader
import qea_writer
import toolbox_merge as tm


def _schreibe(path: Path, packages: list[dict], elements: list[dict]) -> Path:
    return qea_writer.write_qea(
        {
            "ir_version": 1,
            "technology": {"profile": ""},
            "packages": packages,
            "elements": elements,
            "connectors": [],
            "diagrams": [],
        },
        path,
    )


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


def _modell_mit_katalog(tmp_path: Path) -> Path:
    """Zielmodell plus Katalogelement aus dem Werkzeugkasten."""
    katalog = _schreibe(
        tmp_path / "katalog.qea",
        [{"path": "Standard"}, {"path": "Standard/Waffensysteme"}],
        [
            {
                "package": "Standard/Waffensysteme",
                "name": "Kampfpanzer",
                "ea_type": "Class",
                "stereotype": "ResourceArchitecture",
            }
        ],
    )
    modell = _schreibe(
        tmp_path / "modell.qea",
        [{"path": "Ziel"}],
        [{"package": "Ziel", "name": "Bestand A", "ea_type": "Class"}],
    )
    out = tmp_path / "start.qea"
    tm.merge_toolbox(modell, katalog, out, paketname="Standard")
    return out


def test_kennung_bleibt_beim_umzug_und_beim_umbenennen(tmp_path: Path) -> None:
    start = _modell_mit_katalog(tmp_path)
    guid_vorher = _guids(start)["Kampfpanzer"]

    ir = qea_reader.read_qea(start)
    ir["packages"].append({"path": "Ziel/Architektur"})
    for element in ir["elements"]:
        if element["name"] == "Kampfpanzer":
            element["package"] = "Ziel/Architektur"
            element["name"] = "KPz Kampfpanzer"
    umgezogen = qea_writer.write_qea(ir, tmp_path / "umgezogen.qea")

    assert _guids(umgezogen)["KPz Kampfpanzer"] == guid_vorher


def test_rueckweg_ist_wiederholbar_stabil(tmp_path: Path) -> None:
    """Dreimal .qea -> IR -> .qea: alle Kennungen bleiben gleich."""
    first = _modell_mit_katalog(tmp_path)
    kennungen = [_guids(first)]
    aktuell = first
    for nummer in (1, 2, 3):
        ir = qea_reader.read_qea(aktuell)
        aktuell = qea_writer.write_qea(ir, tmp_path / f"lauf{nummer}.qea")
        kennungen.append(_guids(aktuell))
    assert all(kennungen[0] == folge for folge in kennungen[1:]), kennungen


def test_nur_neue_elemente_bekommen_eigene_kennung(tmp_path: Path) -> None:
    start = _modell_mit_katalog(tmp_path)
    vorher = _guids(start)

    ir = qea_reader.read_qea(start)
    ir["elements"].append(
        {
            "package": "Ziel",
            "name": "System Neu",
            "stereotype": "ResourceArchitecture",
            "ea_type": "Class",
        }
    )
    erweitert = qea_writer.write_qea(ir, tmp_path / "erweitert.qea")
    nachher = _guids(erweitert)

    for name, guid in vorher.items():
        assert nachher[name] == guid, f"Kennung von {name!r} hat sich geaendert"
    assert nachher["System Neu"] not in vorher.values()
    # Deterministisch: derselbe Inhalt erzeugt dieselbe Kennung
    erneut = qea_writer.write_qea(qea_reader.read_qea(erweitert), tmp_path / "erneut.qea")
    assert _guids(erneut)["System Neu"] == nachher["System Neu"]


def test_fremde_kennung_wird_beim_uebernehmen_nicht_angetastet(tmp_path: Path) -> None:
    """Der Katalog bringt seine eigene GUID mit -- sie gilt, nicht unsere Ableitung."""
    kat_guid = "{11111111-2222-3333-4444-555555555555}"
    katalog = _schreibe(
        tmp_path / "katalog.qea",
        [{"path": "Standard"}],
        [
            {
                "package": "Standard",
                "name": "Kampfpanzer",
                "ea_type": "Class",
                "stereotype": "ResourceArchitecture",
            }
        ],
    )
    con = sqlite3.connect(str(katalog))
    try:
        con.execute("update t_object set ea_guid = ? where Name = 'Kampfpanzer'", (kat_guid,))
        con.commit()
    finally:
        con.close()

    modell = _schreibe(
        tmp_path / "modell.qea",
        [{"path": "Ziel"}],
        [{"package": "Ziel", "name": "Bestand A", "ea_type": "Class"}],
    )
    out = tmp_path / "uebernommen.qea"
    tm.merge_toolbox(modell, katalog, out, paketname="Standard")

    assert _guids(out)["Kampfpanzer"] == kat_guid
