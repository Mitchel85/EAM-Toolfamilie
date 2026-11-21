"""Das Datenmodell haelt, was es verspricht: Kennungen, Lane-Zuordnung, Conveyed Items."""

from __future__ import annotations

import pytest

from bpmn import modell as m


def test_neue_kennungen_sind_fortlaufend_und_kollisionsfrei(modell: m.Modell) -> None:
    erste = modell.neue_id("Task")
    zweite = modell.neue_id("Task")
    assert erste != zweite
    assert erste.startswith("Task_")
    assert int(zweite.rsplit("_", 1)[1]) > int(erste.rsplit("_", 1)[1])


def test_gleiches_ausgangsmodell_ergibt_gleiche_kennungen() -> None:
    def baue() -> list[str]:
        modell = m.Modell()
        prozess = modell.neuer_prozess("P")
        modell.neuer_knoten("task", "A", prozess)
        modell.neuer_knoten("task", "B", prozess)
        return [k.id for k in modell.knoten.values()]

    assert baue() == baue()


def test_unbekannte_art_wird_abgewiesen() -> None:
    with pytest.raises(ValueError):
        m.Knoten(id="X", art="unbekannt")
    with pytest.raises(ValueError):
        m.Fluss(id="F", art="quatsch", quelle="A", ziel="B")


def test_knoten_kennt_seine_gattung(modell: m.Modell) -> None:
    knoten = next(k for k in modell.knoten.values() if k.art == "exclusive_gateway")
    assert knoten.ist_gateway
    assert not knoten.ist_aufgabe
    assert not knoten.ist_ereignis


def test_lane_findet_knoten_und_verschachtelte_lanes() -> None:
    prozess = m.Prozess(id="P")
    aussen = m.Lane(id="L1", name="Aussen", knoten=["A"])
    innen = m.Lane(id="L2", name="Innen", knoten=["B"])
    aussen.lanes.append(innen)
    prozess.lane_sets.append(m.LaneSet(id="LS", lanes=[aussen]))
    assert prozess.lane_von("A") is aussen
    assert prozess.lane_von("B") is innen
    assert prozess.lane_von("C") is None
    assert aussen.knoten_tief() == ["A", "B"]


def test_conveyed_items_haengen_am_fluss(modell: m.Modell) -> None:
    fluss = next(f for f in modell.fluesse.values() if f.art == "sequence_flow")
    daten = modell.conveyed_items(fluss.id)
    # Der erste Fluss des Antragsprozesses traegt die Antragsunterlagen.
    assert daten, "Fixture sollte ein Conveyed Item am ersten Fluss haben"
    assert all(d.art == "data_object_reference" for d in daten)


def test_conveyed_items_richtung_ist_egal(modell: m.Modell) -> None:
    """Assoziation darf in beide Richtungen zeigen -- EA schreibt sie mal so, mal so."""
    fluss = next(f for f in modell.fluesse.values() if f.art == "sequence_flow")
    daten = modell.conveyed_items(fluss.id)[0]
    assoziation = next(
        f for f in modell.fluesse.values() if f.art == "association" and f.quelle == daten.id
    )
    # Umdrehen: Fluss -> Datenobjekt.
    assoziation.quelle, assoziation.ziel = assoziation.ziel, assoziation.quelle
    assert daten in modell.conveyed_items(fluss.id)


def test_kopie_ist_unabhaengig(modell: m.Modell) -> None:
    knoten = next(iter(modell.knoten.values()))
    kopie = knoten.kopie()
    kopie.name = "anders"
    kopie.begrenzung.x = 999.0
    assert knoten.name != "anders"
    assert knoten.begrenzung.x != 999.0


def test_begrenzung_rechnet_ecken() -> None:
    b = m.Begrenzung(10.0, 20.0, 100.0, 40.0)
    assert b.rechts == 110.0
    assert b.unten == 60.0
    assert b.mitte_x == 60.0
    assert b.mitte_y == 40.0
