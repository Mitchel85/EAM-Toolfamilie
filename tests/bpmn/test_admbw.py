"""ADMBw-Abbildung, L4-Pruefung und Transformation.

Der wichtigste Test ist der langweiligste: Nach ``konform_machen`` darf kein
Fehler mehr uebrig sein, und ein zweiter Lauf darf nichts mehr aendern.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bpmn import admbw
from bpmn import modell as m

WURZEL = Path(__file__).resolve().parents[2]
STEREOYPE_DATEI = WURZEL / "apps" / "admbw-extractor" / "ADMBw-Stereotypes.json"


@pytest.fixture(scope="module")
def stereotype_liste() -> dict[str, dict]:
    daten = json.loads(STEREOYPE_DATEI.read_text(encoding="utf-8"))
    return {eintrag["name"]: eintrag for eintrag in daten["stereotypes"]}


# --------------------------------------------------------------------------
# Abbildung
# --------------------------------------------------------------------------


def test_abbildung_nutzt_nur_vorhandene_stereotype(stereotype_liste: dict[str, dict]) -> None:
    regeln = admbw.lade_regeln()
    for art, eintrag in regeln["elementtypen"].items():
        name = eintrag.get("admbw")
        if name is None:
            continue
        assert name in stereotype_liste, f"{art}: {name} steht nicht in der MDG-Liste"


def test_abbildung_stimmt_mit_der_quelle(stereotype_liste: dict[str, dict]) -> None:
    regeln = admbw.lade_regeln()
    for name, eintrag in regeln["stereotype"].items():
        quelle = stereotype_liste[name]
        assert eintrag["appliesTo"] == list(quelle.get("appliesTo") or [])
        assert eintrag["abstract"] == bool(quelle.get("abstract"))


def test_aufgabe_bekommt_aktionsstereotyp() -> None:
    assert admbw.stereotype_fuer("task") == "OperationalActivityAction"
    assert admbw.stereotype_fuer("service_task") == "OperationalActivityAction"


def test_gateway_und_ereignis_bleiben_ohne_stereotyp() -> None:
    assert admbw.stereotype_fuer("exclusive_gateway") is None
    assert admbw.stereotype_fuer("start_event") is None
    assert admbw.stereotype_fuer("intermediate_catch_event") is None


def test_kanten_haben_ihre_stereotype() -> None:
    assert admbw.stereotype_fuer("sequence_flow") == "OperationalControlFlow"
    assert admbw.stereotype_fuer("message_flow") == "OperationalMessageFlow"
    assert admbw.stereotype_fuer("association") == "OperationalExchange"


def test_unbekannte_art_liefert_keine_erfindung() -> None:
    eintrag = admbw.mapping("gibt_es_nicht")
    assert eintrag["admbw"] is None
    assert eintrag["sicherheit"] == "unbekannt"


# --------------------------------------------------------------------------
# Pruefung
# --------------------------------------------------------------------------


def test_gutes_modell_hat_keine_befunde(modell: m.Modell) -> None:
    befunde = admbw.pruefe(modell)
    assert befunde == [], "\n".join(str(b) for b in befunde)


def test_schlechtes_modell_liefert_die_erwarteten_regeln(schlechtes_modell: m.Modell) -> None:
    regeln = {b.regel for b in admbw.pruefe(schlechtes_modell)}
    erwartet = {
        "BPMN-L4-04",  # Knoten ausserhalb der Lane
        "BPMN-L4-05",  # Stereotyp fehlt
        "BPMN-L4-06",  # Aktionsname fehlt
        "BPMN-L4-08",  # Verzweigung an einer Aktion
        "BPMN-L4-09",  # falscher Zusammenfuehrungstyp
        "BPMN-L4-10",  # kein Endereignis
        "BPMN-L4-12",  # Bedingung an einer Aktion
        "BPMN-L4-13",  # Nachrichtenfluss im selben Pool
    }
    assert erwartet <= regeln, f"fehlt: {erwartet - regeln}"


def test_befund_traegt_regel_schwere_objekt_und_hinweis(schlechtes_modell: m.Modell) -> None:
    for befund in admbw.pruefe(schlechtes_modell):
        assert befund.regel.startswith("BPMN-L4-")
        assert befund.schwere in ("fehler", "warnung", "hinweis")
        assert befund.objekt
        assert befund.hinweis
        assert befund.konvention.startswith("L4-MK")
        assert str(befund).startswith("[")


def test_pruefung_ist_reihenfolgestabil(schlechtes_modell: m.Modell) -> None:
    erste = [b.als_dict() for b in admbw.pruefe(schlechtes_modell)]
    zweite = [b.als_dict() for b in admbw.pruefe(schlechtes_modell)]
    assert erste == zweite
    schwere = [admbw.SCHWERE_RANG[b["schwere"]] for b in erste]
    assert schwere == sorted(schwere), "Fehler muessen vor Warnungen stehen"


def test_zusammenfassung_zaehlt(schlechtes_modell: m.Modell) -> None:
    zahlen = admbw.zusammenfassung(admbw.pruefe(schlechtes_modell))
    assert zahlen["fehler"] > 0
    assert set(zahlen) == {"fehler", "warnung", "hinweis"}


def test_nachrichtenfluss_zwischen_pools_ist_erlaubt(modell: m.Modell) -> None:
    regeln = {b.regel for b in admbw.pruefe(modell)}
    assert "BPMN-L4-13" not in regeln


def test_metaconstraints_werden_angewandt() -> None:
    """Ein Kontrollfluss von einem Endereignis weg ist laut MDG unzulaessig."""
    modell = m.Modell()
    prozess = modell.neuer_prozess("P")
    start = modell.neuer_knoten("start_event", "Start", prozess)
    ende = modell.neuer_knoten("end_event", "Ende", prozess)
    danach = modell.neuer_knoten("task", "Danach", prozess)
    modell.neuer_fluss("sequence_flow", start.id, ende.id, prozess=prozess)
    modell.neuer_fluss("sequence_flow", ende.id, danach.id, prozess=prozess)
    befunde = [b for b in admbw.pruefe(modell) if b.regel == "BPMN-L4-07"]
    assert befunde
    assert "EndEvent" in befunde[0].hinweis


# --------------------------------------------------------------------------
# Transformation
# --------------------------------------------------------------------------


def test_transformation_beseitigt_alle_fehler(schlechtes_modell: m.Modell) -> None:
    protokoll = admbw.konform_machen(schlechtes_modell)
    assert protokoll.aenderungen, "das schlechte Modell muss Aenderungen erzeugen"
    rest = [b for b in admbw.pruefe(schlechtes_modell) if b.schwere == "fehler"]
    assert rest == [], "\n".join(str(b) for b in rest)


def test_transformation_ist_idempotent(schlechtes_modell: m.Modell) -> None:
    admbw.konform_machen(schlechtes_modell)
    zweite = admbw.konform_machen(schlechtes_modell)
    assert zweite.aenderungen == []
    assert len(zweite) == 0


def test_protokoll_nennt_regel_und_objekt(schlechtes_modell: m.Modell) -> None:
    protokoll = admbw.konform_machen(schlechtes_modell)
    assert all(a.regel.startswith("BPMN-L4-") for a in protokoll.aenderungen)
    assert all(a.objekt for a in protokoll.aenderungen)
    daten = protokoll.als_dict()
    assert daten["anzahl"] == len(protokoll.aenderungen)
    assert "Aenderung" in protokoll.text()


def test_transformation_setzt_das_stereotyp(schlechtes_modell: m.Modell) -> None:
    admbw.konform_machen(schlechtes_modell)
    for knoten in schlechtes_modell.knoten.values():
        if knoten.ist_aufgabe:
            assert knoten.stereotype == "OperationalActivityAction"


def test_transformation_ergaenzt_start_und_ende() -> None:
    modell = m.Modell()
    prozess = modell.neuer_prozess("P")
    aufgabe = modell.neuer_knoten("task", "Arbeiten", prozess)
    modell.neuer_knoten("task", "Weiter", prozess)
    admbw.konform_machen(modell)
    arten = [k.art for k in modell.knoten.values()]
    assert "start_event" in arten
    assert "end_event" in arten
    start = next(k for k in modell.knoten.values() if k.ist_start)
    start_fluesse = modell.ausgehend(start.id)
    assert start_fluesse, "Startereignis muss angebunden sein"
    assert start_fluesse[0].ziel == aufgabe.id


def test_transformation_gleicht_gateway_typen_an(schlechtes_modell: m.Modell) -> None:
    zusammen = schlechtes_modell.knoten["ExclusiveGateway_7"]
    admbw.konform_machen(schlechtes_modell)
    assert zusammen.art == "parallel_gateway"


def test_transformation_macht_aus_dem_nachrichtenfluss_einen_kontrollfluss(
    schlechtes_modell: m.Modell,
) -> None:
    nachricht = next(f for f in schlechtes_modell.fluesse.values() if f.art == "message_flow")
    admbw.konform_machen(schlechtes_modell)
    assert nachricht.art == "sequence_flow"


def test_transformation_legt_platzhalter_fuer_conveyed_items_an(schlechtes_modell: m.Modell) -> None:
    admbw.konform_machen(schlechtes_modell)
    platzhalter = [d for d in schlechtes_modell.daten.values() if "(benennen)" in d.name]
    assert platzhalter
    assert all(d.art == "data_object_reference" for d in platzhalter)


def test_transformation_ist_nicht_destruktiv_an_namen(modell: m.Modell) -> None:
    vorher = {k.id: k.name for k in modell.knoten.values()}
    protokoll = admbw.konform_machen(modell)
    assert protokoll.aenderungen == []
    assert {k.id: k.name for k in modell.knoten.values()} == vorher


def test_leeres_modell_wird_konform_ohne_ausnahme() -> None:
    modell = m.Modell(name="leer")
    protokoll = admbw.konform_machen(modell)
    assert protokoll.aenderungen == [] or protokoll.aenderungen
    assert admbw.pruefe(modell) == []


def test_konform_machen_und_pruefen_liefert_beides(schlechtes_modell: m.Modell) -> None:
    protokoll, befunde = admbw.konform_machen_und_pruefen(schlechtes_modell)
    assert protokoll.aenderungen
    assert all(b.schwere != "fehler" for b in befunde)
