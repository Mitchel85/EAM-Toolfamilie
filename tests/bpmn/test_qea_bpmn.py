"""Die .qea-Bruecke: schreiben, mit dem vorhandenen Leser zuruecklesen, pruefen.

Der Test benutzt bewusst den Produktionsleser ``qea_reader`` und nicht den
Writer-eigenen Plan: nur so ist belegt, dass die Datei auch fuer fremde Leser
die erwarteten Elemente und Kanten enthaelt.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import qea_reader
from bpmn import modell as m
from bpmn import qea_bpmn


def _elemente(ir: dict) -> list[dict]:
    return list(ir["elements"])


def _find(ir: dict, name: str, stereotype: str | None = None) -> dict:
    treffer = [
        eintrag
        for eintrag in ir["elements"]
        if eintrag["name"] == name
        and (stereotype is None or eintrag.get("stereotype") == stereotype)
    ]
    assert treffer, f"Element fehlt: {name} ({stereotype})"
    return treffer[0]


def _kanten(ir: dict) -> list[dict]:
    return list(ir["connectors"])


def test_pool_lane_aktion_und_kanten_stehen_in_der_qea(modell: m.Modell, tmp_path: Path) -> None:
    ziel = qea_bpmn.schreibe_qea(modell, tmp_path / "prozess.qea")
    ir = qea_reader.read_qea(ziel)

    assert ziel.is_file()
    assert ziel.read_bytes()[:16].startswith(b"SQLite format 3")
    pool = _find(ir, "Antragsteller", "OperationalArchitecture")
    assert pool["ea_type"] == "Class"
    assert pool["package"] == "Prozesse"
    lane = _find(ir, "Sachbearbeiter", "OperationalPerformer")
    assert lane["ea_type"] == "Class"
    assert lane["package"].startswith("Prozesse/")
    aktion = _find(ir, "Antrag pruefen", "OperationalActivityAction")
    assert aktion["ea_type"] == "Action"
    # Ereignisse und Gateways: kein ADMBw-Stereotyp, Semantik im Tag.
    ereignis = _find(ir, "Antrag gestellt")
    assert "stereotype" not in ereignis
    assert ereignis["ea_type"] == "StateNode"
    assert ereignis.get("tags", {}).get("bpmn_type") == "start_event"
    assert ereignis["tags"]["bpmn_id"] == "StartEvent_1"


def test_kontroll_und_nachrichtenfluesse_haben_ihre_stereotype(
    modell: m.Modell, tmp_path: Path
) -> None:
    ziel = qea_bpmn.schreibe_qea(modell, tmp_path / "prozess.qea")
    ir = qea_reader.read_qea(ziel)
    kanten = _kanten(ir)

    kontroll = [k for k in kanten if k.get("stereotype") == "OperationalControlFlow"]
    nachrichten = [k for k in kanten if k.get("stereotype") == "OperationalMessageFlow"]
    assert len(kontroll) == 9  # 3 im Antragsprozess, 6 im Pruefprozess
    assert all(k["ea_type"] == "ControlFlow" for k in kontroll + nachrichten)
    assert len(nachrichten) == 1
    nachricht = nachrichten[0]
    assert nachricht["source"].endswith("::Antrag senden")
    assert nachricht["target"].endswith("::Antrag eingegangen")
    # Paketuebergreifend: Quelle und Ziel liegen in verschiedenen Prozesspaketen.
    assert nachricht["source"].split("::")[0] != nachricht["target"].split("::")[0]


def test_conveyed_items_werden_zu_informationselementen(
    modell: m.Modell, tmp_path: Path
) -> None:
    ziel = qea_bpmn.schreibe_qea(modell, tmp_path / "prozess.qea")
    ir = qea_reader.read_qea(ziel)
    kanten = _kanten(ir)

    assert _find(ir, "Antragsunterlagen", "InformationElement")["ea_type"] == "Class"
    austausch = [k for k in kanten if k.get("stereotype") == "OperationalExchange"]
    assert austausch
    assert all(k["ea_type"] == "InformationFlow" for k in austausch)
    # Der Austausch haengt an einer Aktion, nicht an einem Ereignis.
    ziele = {k["target"] for k in austausch}
    assert any(ziel.endswith("::Antrag erfassen") for ziel in ziele)
    assert not any(ziel.endswith("::Antrag gestellt") for ziel in ziele)


def test_qea_ist_byte_stabil(modell: m.Modell) -> None:
    assert qea_bpmn.qea_bytes(modell) == qea_bpmn.qea_bytes(modell)


def test_gleichnamige_aktionen_bleiben_erhalten() -> None:
    modell = m.Modell(id="D", name="Doppelt")
    prozess = modell.neuer_prozess("Doppelt", "P1")
    modell.kollaboration = m.Kollaboration(id="C", name="Doppelt")
    modell.kollaboration.teilnehmer.append(
        m.Teilnehmer(id="Pool", name="Stelle", prozess_ref="P1")
    )
    start = modell.neuer_knoten("start_event", "Start", prozess)
    eins = modell.neuer_knoten("user_task", "Pruefen", prozess)
    zwei = modell.neuer_knoten("user_task", "Pruefen", prozess)
    ende = modell.neuer_knoten("end_event", "Ende", prozess)
    modell.neuer_fluss("sequence_flow", start.id, eins.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", eins.id, zwei.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", zwei.id, ende.id, prozess=prozess)

    ir = qea_bpmn.als_ir(modell)
    namen = [e["name"] for e in ir["elements"] if e.get("stereotype") == "OperationalActivityAction"]
    assert namen == ["Pruefen", "Pruefen (2)"]


def test_leeres_modell_wird_abgelehnt() -> None:
    with pytest.raises(ValueError):
        qea_bpmn.als_ir(m.Modell())


def test_datei_hat_die_pflicht_tabellen(modell: m.Modell, tmp_path: Path) -> None:
    ziel = qea_bpmn.schreibe_qea(modell, tmp_path / "prozess.qea")
    con = sqlite3.connect(str(ziel))
    try:
        tabellen = {zeile[0] for zeile in con.execute("select name from sqlite_master where type='table'")}
        for name in ("t_object", "t_connector", "t_package", "t_xref", "t_diagram"):
            assert name in tabellen
        objekte = con.execute("select count(*) from t_object").fetchone()[0]
        kanten = con.execute("select count(*) from t_connector").fetchone()[0]
    finally:
        con.close()
    assert objekte >= 10
    assert kanten >= 10
