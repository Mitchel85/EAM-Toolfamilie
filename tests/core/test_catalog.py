"""Standardelemente aus dem Katalog: Kennung und Heimatpaket kommen vom Katalog.

Der Prozess der Bw: Standardelemente (StEKa/Modellelementekatalog) werden
wiederverwendet, nicht nachgebaut. Ein Element, das die Prosa nennt und das im
Katalog steht, muss dessen ``ea_guid`` und dessen Paket tragen. Nur wirklich
neue Elemente bekommen eine eigene, abgeleitete Kennung.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import catalog_index
import eam_ai
import qea_reader
import qea_writer

from test_build import MDG  # gemeinsame Testhilfe (conftest legt tests/core auf den Pfad)


KATALOG_GUID = "{11111111-2222-3333-4444-555555555555}"


def _katalog(tmp_path: Path) -> Path:
    pfad = qea_writer.write_qea(
        {
            "ir_version": 1,
            "technology": {"profile": ""},
            "packages": [
                {"path": "MASC"},
                {"path": "MASC/Modellelementekatalog"},
                {"path": "MASC/Modellelementekatalog/ResourceArchitectures"},
            ],
            "elements": [
                {
                    "package": "MASC/Modellelementekatalog/ResourceArchitectures",
                    "name": "Kampfpanzer",
                    "stereotype": "ServiceSpecification",
                    "ea_type": "Class",
                }
            ],
            "connectors": [],
            "diagrams": [],
        },
        tmp_path / "katalog.qea",
    )
    con = sqlite3.connect(str(pfad))
    try:
        con.execute("update t_object set ea_guid = ? where Name = 'Kampfpanzer'", (KATALOG_GUID,))
        con.commit()
    finally:
        con.close()
    return pfad


def _text(tmp_path: Path) -> Path:
    pfad = tmp_path / "prosa.md"
    pfad.write_text(
        "Der Kampfpanzer meldet an das System Lagezentrum.\n",
        encoding="utf-8",
    )
    return pfad


def _antwort():
    import json

    import extract

    elemente = [
        {"name": "Kampfpanzer", "stereotype": "ServiceSpecification", "notes": "x",
         "source_ref": "D1-S1", "confidence": 0.9},
        {"name": "System Lagezentrum", "stereotype": "ServiceSpecification", "notes": "x",
         "source_ref": "D1-S1", "confidence": 0.9},
    ]
    return extract.StaticBackend([json.dumps({"elements": elemente})] * 3, name="test")


def test_katalogelement_behaelt_kennung_und_paket(tmp_path: Path) -> None:
    katalog = _katalog(tmp_path)
    ziel = tmp_path / "ergebnis.qea"
    eam_ai.build(
        mdg=MDG,
        text=_text(tmp_path),
        out=ziel,
        backend=_antwort(),
        findings_path=tmp_path / "f.json",
        sidecar=False,
        katalog=katalog,
    )

    con = sqlite3.connect(str(ziel))
    try:
        kampfpanzer = con.execute(
            "select ea_guid, Package_ID from t_object where Name = 'Kampfpanzer'"
        ).fetchone()
        paket = con.execute(
            "select Name from t_package where Package_ID = ?", (kampfpanzer[1],)
        ).fetchone()[0]
    finally:
        con.close()

    assert kampfpanzer[0] == KATALOG_GUID
    assert paket == "ResourceArchitectures"
    elemente = {e["name"] for e in qea_reader.read_qea(ziel)["elements"]}
    assert "System Lagezentrum" in elemente  # neues Element bleibt erhalten


def test_neues_element_bekommt_eigene_kennung(tmp_path: Path) -> None:
    katalog = _katalog(tmp_path)
    ziel = tmp_path / "ergebnis.qea"
    eam_ai.build(
        mdg=MDG,
        text=_text(tmp_path),
        out=ziel,
        backend=_antwort(),
        findings_path=tmp_path / "f.json",
        sidecar=False,
        katalog=katalog,
    )

    con = sqlite3.connect(str(ziel))
    try:
        guid_neu = con.execute(
            "select ea_guid from t_object where Name = 'System Lagezentrum'"
        ).fetchone()[0]
    finally:
        con.close()
    assert guid_neu != KATALOG_GUID
    assert guid_neu == qea_writer.guid_for("Architektur", "ServiceSpecification", "System Lagezentrum")


def test_katalog_ist_im_prompt_und_wird_nachgeschlagen(tmp_path: Path) -> None:
    katalog = _katalog(tmp_path)
    geladen = catalog_index.Catalog.from_qea(katalog)
    assert len(geladen) == 1
    treffer = geladen.lookup("kampfpanzer", "")
    assert treffer is not None and treffer.guid == KATALOG_GUID

    # Der Prompt nennt das Standardelement beim Namen (bekannte Liste).
    assert "Kampfpanzer" in geladen.inventory(10)


def test_ohne_katalog_bleibt_alles_wie_bisher(tmp_path: Path) -> None:
    ziel = tmp_path / "ergebnis.qea"
    eam_ai.build(
        mdg=MDG,
        text=_text(tmp_path),
        out=ziel,
        backend=_antwort(),
        findings_path=tmp_path / "f.json",
        sidecar=False,
    )
    con = sqlite3.connect(str(ziel))
    try:
        guid = con.execute(
            "select ea_guid from t_object where Name = 'Kampfpanzer'"
        ).fetchone()[0]
    finally:
        con.close()
    assert guid == qea_writer.guid_for("Architektur", "ServiceSpecification", "Kampfpanzer")


def test_katalogkennung_behaelt_schreibweise(tmp_path: Path, monkeypatch) -> None:
    """Gemischte Gross-/Kleinschreibung im Katalog kommt woertlich im Ergebnis an."""
    import sys

    gemischt = "{ABCD0000-12ab-34CD-56ef-0000000000a1}"
    monkeypatch.setattr(sys.modules[__name__], "KATALOG_GUID", gemischt)
    katalog = _katalog(tmp_path)
    ziel = tmp_path / "ergebnis.qea"
    eam_ai.build(
        mdg=MDG,
        text=_text(tmp_path),
        out=ziel,
        backend=_antwort(),
        findings_path=tmp_path / "f.json",
        sidecar=False,
        katalog=katalog,
    )
    con = sqlite3.connect(str(ziel))
    try:
        guid = con.execute("select ea_guid from t_object where Name = 'Kampfpanzer'").fetchone()[0]
    finally:
        con.close()
    assert guid == gemischt
