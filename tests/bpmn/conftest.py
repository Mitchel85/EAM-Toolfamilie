"""Gemeinsame Fixtures fuer die BPMN-Tests.

Die Modelle werden im Code gebaut, nicht als XML mitgeliefert: So ist
nachvollziehbar, was jeder Test voraussetzt, und die Dateien bleiben klein.
"""

from __future__ import annotations

import pytest

from bpmn import layout, modell as m


@pytest.fixture
def modell() -> m.Modell:
    """Ein kleines, korrektes Kollaborationsmodell mit zwei Pools."""
    modell = m.Modell(id="Definitions_1", name="Antragsbearbeitung")
    modell.ziel_namespace = "https://example.invalid/bpmn"

    antrag = modell.neuer_prozess("Antrag bearbeiten", "Process_Antrag")
    pruefung = modell.neuer_prozess("Antrag pruefen", "Process_Pruefung")

    modell.kollaboration = m.Kollaboration(id="Collaboration_1", name="Antragsbearbeitung")
    kunde = m.Teilnehmer(
        id="Participant_Kunde",
        name="Antragsteller",
        prozess_ref=antrag.id,
        typ="OperationalArchitecture_Antrag",
    )
    sachgebiet = m.Teilnehmer(
        id="Participant_Sachgebiet",
        name="Sachgebiet",
        prozess_ref=pruefung.id,
        typ="OperationalArchitecture_Antrag",
    )
    modell.kollaboration.teilnehmer.extend([kunde, sachgebiet])

    laneset_a = m.LaneSet(id="LaneSet_Antrag")
    lane_a = m.Lane(id="Lane_Antragsteller", name="Antragsteller", performer="Performer_Antragsteller")
    laneset_a.lanes.append(lane_a)
    antrag.lane_sets.append(laneset_a)

    laneset_p = m.LaneSet(id="LaneSet_Pruefung")
    lane_p = m.Lane(id="Lane_Sachbearbeiter", name="Sachbearbeiter", performer="Performer_Sachbearbeiter")
    laneset_p.lanes.append(lane_p)
    pruefung.lane_sets.append(laneset_p)

    start = modell.neuer_knoten("start_event", "Antrag gestellt", antrag)
    start.ereignis_rolle = "trigger"
    aufgabe = modell.neuer_knoten("user_task", "Antrag erfassen", antrag)
    aufgabe.stereotype = "OperationalActivityAction"
    senden = modell.neuer_knoten("send_task", "Antrag senden", antrag)
    senden.stereotype = "OperationalActivityAction"
    ende_a = modell.neuer_knoten("end_event", "Antrag abgegeben", antrag)
    ende_a.ereignis_rolle = "ergebnis"

    empfang = modell.neuer_knoten("start_event", "Antrag eingegangen", pruefung)
    empfang.ereignis_definition = "message"
    empfang.ereignis_rolle = "trigger"
    pruefen = modell.neuer_knoten("user_task", "Antrag pruefen", pruefung)
    pruefen.stereotype = "OperationalActivityAction"
    entscheidung = modell.neuer_knoten("exclusive_gateway", "vollstaendig?", pruefung)
    nachfrage = modell.neuer_knoten("send_task", "Unterlagen anfordern", pruefung)
    nachfrage.stereotype = "OperationalActivityAction"
    buchen = modell.neuer_knoten("service_task", "Antrag buchen", pruefung)
    buchen.stereotype = "OperationalActivityAction"
    ende_p = modell.neuer_knoten("end_event", "Antrag gebucht", pruefung)
    ende_p.ereignis_rolle = "ergebnis"

    for knoten in (start, aufgabe, senden, ende_a):
        lane_a.knoten.append(knoten.id)
    for knoten in (empfang, pruefen, entscheidung, nachfrage, buchen, ende_p):
        lane_p.knoten.append(knoten.id)

    f1 = modell.neuer_fluss("sequence_flow", start.id, aufgabe.id, prozess=antrag)
    f2 = modell.neuer_fluss("sequence_flow", aufgabe.id, senden.id, prozess=antrag)
    f3 = modell.neuer_fluss("sequence_flow", senden.id, ende_a.id, prozess=antrag)

    g1 = modell.neuer_fluss("sequence_flow", empfang.id, pruefen.id, prozess=pruefung)
    g2 = modell.neuer_fluss("sequence_flow", pruefen.id, entscheidung.id, prozess=pruefung)
    g3 = modell.neuer_fluss("sequence_flow", entscheidung.id, buchen.id, prozess=pruefung)
    g3.bedingung = "vollstaendig"
    g4 = modell.neuer_fluss("sequence_flow", entscheidung.id, nachfrage.id, prozess=pruefung)
    g4.bedingung = "unvollstaendig"
    g5 = modell.neuer_fluss("sequence_flow", nachfrage.id, entscheidung.id, prozess=pruefung)
    g6 = modell.neuer_fluss("sequence_flow", buchen.id, ende_p.id, prozess=pruefung)

    # Conveyed Items an den Aktionen (L4-MK17).
    unterlagen = modell.neues_datenobjekt("Antragsunterlagen", prozess=antrag)
    modell.assoziiere(unterlagen.id, f1.id, prozess=antrag)
    modell.assoziiere(unterlagen.id, f2.id, prozess=antrag)
    modell.assoziiere(unterlagen.id, f3.id, prozess=antrag)

    eingang = modell.neues_datenobjekt("Antrag (Datensatz)", prozess=pruefung)
    modell.assoziiere(eingang.id, g1.id, prozess=pruefung)
    modell.assoziiere(eingang.id, g2.id, prozess=pruefung)
    modell.assoziiere(eingang.id, g3.id, prozess=pruefung)
    nachforderung = modell.neues_datenobjekt("Nachforderung", prozess=pruefung)
    modell.assoziiere(nachforderung.id, g4.id, prozess=pruefung)
    modell.assoziiere(nachforderung.id, g5.id, prozess=pruefung)
    bescheid = modell.neues_datenobjekt("Bescheid", prozess=pruefung)
    modell.assoziiere(bescheid.id, g6.id, prozess=pruefung)

    # Nachrichtenfluss zwischen den Pools, mit Conveyed Item.
    nachricht = modell.neuer_fluss("message_flow", senden.id, empfang.id, name="Antrag")
    modell.neues_datenobjekt("Antrag (Nachricht)", prozess=antrag)
    daten_nachricht = list(modell.daten.values())[-1]
    modell.assoziiere(daten_nachricht.id, nachricht.id, prozess=antrag)

    layout.verteile(modell)
    return modell


@pytest.fixture
def schlechtes_modell() -> m.Modell:
    """Ein Modell mit den typischen Anfaengerfehlern -- fuer die Pruefung."""
    modell = m.Modell(id="Definitions_schlecht", name="Pruefmodell")
    prozess = modell.neuer_prozess("Antrag", "Process_1")
    modell.kollaboration = m.Kollaboration(id="Collab_1", name="Kollaboration")
    modell.kollaboration.teilnehmer.append(
        m.Teilnehmer(id="Pool_1", name="Sachgebiet", prozess_ref="Process_1")
    )
    lane_set = m.LaneSet(id="LS_1")
    lane = m.Lane(id="Lane_1", name="")
    lane_set.lanes.append(lane)
    prozess.lane_sets.append(lane_set)

    start = modell.neuer_knoten("start_event", "Start", prozess)
    erste = modell.neuer_knoten("task", "Antrag pruefen", prozess)
    zweite = modell.neuer_knoten("task", "", prozess)
    teilen = modell.neuer_knoten("parallel_gateway", "Parallel", prozess)
    links = modell.neuer_knoten("task", "Zweig eins", prozess)
    rechts = modell.neuer_knoten("task", "Zweig zwei", prozess)
    zusammen = modell.neuer_knoten("exclusive_gateway", "Zusammen", prozess)
    danach = modell.neuer_knoten("task", "Nachbereiten", prozess)
    for knoten in (start, erste, zweite, teilen, links, rechts, zusammen):
        lane.knoten.append(knoten.id)

    modell.neuer_fluss("sequence_flow", start.id, erste.id, prozess=prozess)
    bedingt = modell.neuer_fluss("sequence_flow", erste.id, zweite.id, prozess=prozess)
    bedingt.bedingung = "vollstaendig"
    modell.neuer_fluss("sequence_flow", zweite.id, teilen.id, prozess=prozess)
    # Zweiter Ausgang direkt an einer Aktion -- klassischer Modellierfehler.
    modell.neuer_fluss("sequence_flow", zweite.id, danach.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", teilen.id, links.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", teilen.id, rechts.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", links.id, zusammen.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", rechts.id, zusammen.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", zusammen.id, danach.id, prozess=prozess)
    modell.neuer_fluss("message_flow", erste.id, zweite.id)
    return modell
