"""Tests fuer den CLI-Unterbefehl ``eam-ai toolbox``.

Der Katalog wird synthetisch erzeugt (zwei Pakete, drei Elemente, eine Kante),
damit die Tests ohne die grosse ``Testarchitektur.qea`` laufen. Geprueft wird:
Start aus dem Katalog, Vorschau ohne Datei, Harmonisierung eines Bestands und
Idempotenz des zweiten Laufs.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import eam_ai
import qea_writer


def _write(path: Path, packages, elements, connectors=()) -> Path:
    return qea_writer.write_qea(
        {
            "ir_version": 1,
            "technology": {"profile": ""},
            "packages": list(packages),
            "elements": list(elements),
            "connectors": list(connectors),
            "diagrams": [],
        },
        path,
    )


@pytest.fixture()
def katalog(tmp_path: Path) -> Path:
    """Kleiner Katalog: ein Standardelement-Paket mit zwei Elementen."""
    return _write(
        tmp_path / "katalog.qea",
        [{"path": "Standards"}, {"path": "Standards/Projekte"}],
        [
            {
                "package": "Standards/Projekte",
                "name": "Standardprojekt",
                "stereotype": "Project",
                "notes": "Vorlage fuer Projekte",
            },
            {
                "package": "Standards",
                "name": "Standardrolle",
                "stereotype": "OperationalPerformer",
            },
        ],
        [
            {
                "source": "Standards::Standardrolle",
                "target": "Standards/Projekte::Standardprojekt",
                "stereotype": "IsResponsibleFor",
            }
        ],
    )


def _counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            "elemente": con.execute("select count(*) from t_object").fetchone()[0],
            "klassen": con.execute(
                "select count(*) from t_object where Object_Type = 'Class'"
            ).fetchone()[0],
            "kanten": con.execute("select count(*) from t_connector").fetchone()[0],
            "platzhalter": con.execute(
                "select count(*) from t_object where Name like '%platzhalter%'"
            ).fetchone()[0],
        }
    finally:
        con.close()


def test_start_aus_katalog_schreibt_modell(tmp_path: Path, katalog: Path) -> None:
    ziel = tmp_path / "start.qea"
    code = eam_ai.main(
        ["toolbox", "--kasten", str(katalog), "--out", str(ziel), "--paket", "StEKa"]
    )

    assert code == 0
    assert ziel.exists()
    werte = _counts(ziel)
    assert werte["klassen"] == 2
    assert werte["kanten"] == 1
    assert werte["platzhalter"] == 0


def test_guid_bleibt_erhalten(tmp_path: Path, katalog: Path) -> None:
    ziel = tmp_path / "start.qea"
    assert eam_ai.main(["toolbox", "--kasten", str(katalog), "--out", str(ziel)]) == 0

    def guids(path: Path) -> dict[str, str]:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return dict(
                con.execute(
                    "select Name, ea_guid from t_object where Object_Type = 'Class'"
                ).fetchall()
            )
        finally:
            con.close()

    vorher = guids(katalog)
    nachher = guids(ziel)
    for name in ("Standardprojekt", "Standardrolle"):
        assert nachher[name] == vorher[name]


def test_vorschau_schreibt_keine_datei(tmp_path: Path, katalog: Path) -> None:
    ziel = tmp_path / "vorschau.qea"
    bericht = tmp_path / "bericht.json"
    code = eam_ai.main(
        [
            "toolbox",
            "--kasten",
            str(katalog),
            "--out",
            str(ziel),
            "--nur-bericht",
            "--bericht",
            str(bericht),
        ]
    )

    assert code == 0
    assert not ziel.exists()
    daten = json.loads(bericht.read_text(encoding="utf-8"))
    assert daten["elemente"] == 2
    assert daten["kanten"] == 1


def test_harmonisierung_ist_idempotent(tmp_path: Path, katalog: Path) -> None:
    # Bestand enthaelt bereits ein Element aus dem Katalog.
    modell = _write(
        tmp_path / "modell.qea",
        [{"path": "Standards"}],
        [
            {
                "package": "Standards",
                "name": "Standardrolle",
                "stereotype": "OperationalPerformer",
            }
        ],
    )
    erstes = tmp_path / "harmonisiert.qea"
    zweites = tmp_path / "harmonisiert2.qea"

    code = eam_ai.main(
        [
            "toolbox",
            "--modell",
            str(modell),
            "--kasten",
            str(katalog),
            "--out",
            str(erstes),
            "--bericht",
            str(tmp_path / "b1.json"),
        ]
    )
    assert code == 0
    bericht1 = json.loads((tmp_path / "b1.json").read_text(encoding="utf-8"))
    assert bericht1["elemente"] == 1          # nur das fehlende Projekt
    assert bericht1["bereits_vorhanden"] == 1

    code = eam_ai.main(
        [
            "toolbox",
            "--modell",
            str(erstes),
            "--kasten",
            str(katalog),
            "--out",
            str(zweites),
            "--bericht",
            str(tmp_path / "b2.json"),
        ]
    )
    assert code == 0
    bericht2 = json.loads((tmp_path / "b2.json").read_text(encoding="utf-8"))
    assert bericht2["elemente"] == 0
    assert bericht2["bereits_vorhanden"] == 2


def test_unbekannter_kasten_ist_laut(tmp_path: Path) -> None:
    ziel = tmp_path / "x.qea"
    code = eam_ai.main(
        ["toolbox", "--kasten", str(tmp_path / "fehlt.qea"), "--out", str(ziel)]
    )
    assert code == 1
    assert not ziel.exists()
