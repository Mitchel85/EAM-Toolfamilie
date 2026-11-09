"""Graph: ArchiMate-Modelle als SQLite-Graph -- Laden, Abfragen, Befunde.

Der Vertrag des Moduls ``graph.py``:

1. **Knoten und Kanten tragen Typ, Stereotyp und Kennung.** Die Kennung ist die
   Identitaet aus dem Austauschformat (GUID/``identifier``), damit derselbe
   Graph aus .qea, XML und JSON dieselben Zeilen liefert.
2. **Die Befunde sind die des Writers.** K04 (Matrixverstoss), K05 (nur
   Gegenrichtung) und K02/K10 (Selbstkanten) muessen exakt den Zaehlern
   entsprechen, die ``archimate_writer`` beim Export ermittelt -- sonst
   widersprechen sich Graph und Export.
3. **Abfragen beantworten die zwei Fragen der Aufgabe:** was haengt an einer
   Faehigkeit, und welche Kanten sind ungueltig.
4. **Laute Fehler:** kaputtes IR, fremde Datenbanken, unbekannte Formate und
   mehrdeutige Suchbegriffe brechen ab, statt zu raten.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import archimate_writer as aw
import graph
from conftest import fixture_pfad, vorhanden
from graph import GraphError, Mehrdeutig
from qea_reader import read_qea_ex

CORE = Path(__file__).resolve().parents[2] / "packages" / "core"
FIXTURES = CORE / "fixtures"
MASC = FIXTURES / "Musterarchitektur_MASC.qea"
TESTARCHITEKTUR = fixture_pfad(
    "Testarchitektur.qea",
    "/root/hermes-workspace/admbw-qea-editor/Testarchitektur.qea",
)

P1 = "Modell"
P2 = "Modell/Faehigkeiten"


# --------------------------------------------------------------------------
# Bausteine
# --------------------------------------------------------------------------
def element(
    name: str,
    *,
    paket: str = P2,
    ea_type: str = "Class",
    stereotyp: str = "",
    guid: str = "",
    **rest: object,
) -> dict:
    eintrag: dict[str, object] = {"package": paket, "name": name, "ea_type": ea_type}
    if stereotyp:
        eintrag["stereotype"] = stereotyp
    if guid:
        eintrag["guid"] = guid
    eintrag.update(rest)
    return eintrag


def kante(quelle: str, ziel: str, *, ea_type: str = "Dependency", stereotyp: str = "", **rest: object) -> dict:
    eintrag: dict[str, object] = {"source": quelle, "target": ziel, "ea_type": ea_type}
    if stereotyp:
        eintrag["stereotype"] = stereotyp
    eintrag.update(rest)
    return eintrag


def ir(elemente: list[dict], kanten: list[dict] | None = None, *, pakete: list[dict] | None = None) -> dict:
    return {
        "ir_version": 1,
        "packages": pakete if pakete is not None else [{"path": P1}, {"path": P2}],
        "elements": elemente,
        "connectors": kanten or [],
    }


def lade(ir_daten: dict, db: Path, **kwargs: object) -> graph.Ladebericht:
    return graph.lade_ir(ir_daten, db, quelle="test.json", format="ir", **kwargs)


def dump(db: Path) -> dict[str, list[tuple]]:
    con = sqlite3.connect(db)
    try:
        return {
            tabelle: con.execute(f"SELECT * FROM {tabelle} ORDER BY 1, 2").fetchall()
            for tabelle in ("knoten", "kanten", "befunde", "eigenschaften")
        }
    finally:
        con.close()


# --------------------------------------------------------------------------
# Knoten und Kanten
# --------------------------------------------------------------------------
def test_knoten_tragen_typ_stereotyp_und_kennung(tmp_path: Path) -> None:
    guid = "{5A5C77DB-7532-4EE0-A7C0-748FB3341CF2}"
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Aufklaerung", stereotyp="Capability", guid=guid),
                element("Prozess", ea_type="Activity", stereotyp="Process", guid="{11111111-2222-3333-4444-555555555555}"),
            ]
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        zeilen = {z["name"]: z for z in graph.alle_knoten(con)}
    finally:
        con.close()

    faehigkeit = zeilen["Aufklaerung"]
    assert faehigkeit["art"] == "element"
    assert faehigkeit["typ"] == "Class"  # Typ des Quellmodells
    assert faehigkeit["stereotyp"] == "Capability"
    assert faehigkeit["archimate_typ"] == "Capability"  # ArchiMate 3.2
    assert faehigkeit["kennung"] == "id-5a5c77db-7532-4ee0-a7c0-748fb3341cf2"
    assert faehigkeit["paket"] == P2

    prozess = zeilen["Prozess"]
    assert prozess["typ"] == "Activity"
    assert prozess["archimate_typ"] == "BusinessProcess"  # FX: Activity -> BusinessProcess


def test_pakete_sind_knoten_der_hierarchie(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(ir([element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}")]), db)
    con = graph.oeffne(db)
    try:
        pakete = [z for z in graph.alle_knoten(con) if z["art"] == "paket"]
    finally:
        con.close()
    assert {p["name"] for p in pakete} == {"Modell", "Faehigkeiten"}
    wurzel = next(p for p in pakete if p["name"] == "Modell")
    kind = next(p for p in pakete if p["name"] == "Faehigkeiten")
    assert wurzel["paket"] == ""
    assert kind["paket"] == P1
    assert {k["archimate_typ"] for k in pakete} == {"Grouping"}


def test_paket_mit_stereotyp_traegt_dessen_archimate_typ(tmp_path: Path) -> None:
    """Ein Paket mit abbildbarem Stereotyp ist im Export ein Product (Writer)."""
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [element("A", paket="Architektur", guid="{AAAAAAAA-0000-0000-0000-000000000001}")],
            pakete=[{"path": "Architektur", "stereotype": "ArchitecturalDescription"}],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        paket = con.execute("SELECT * FROM knoten WHERE art = 'paket'").fetchone()
    finally:
        con.close()
    assert paket["name"] == "Architektur"
    assert paket["archimate_typ"] == "Product"


def test_kante_traegt_kennung_stereotyp_und_typ(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Prozess", ea_type="Activity", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Faehigkeit", stereotyp="Capability", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [
                kante(f"{P2}::Prozess", f"{P2}::Faehigkeit", ea_type="Realisation"),
                kante(f"{P2}::Prozess", f"{P2}::Faehigkeit", ea_type="Realisation",
                      identifier="id-kante-1"),
            ],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        kanten = [dict(z) for z in con.execute("SELECT * FROM kanten ORDER BY position")]
    finally:
        con.close()
    assert len(kanten) == 2
    erste, zweite = kanten
    assert erste["typ"] == "Realization"
    assert erste["quell_typ"] == "Realisation"
    assert erste["stereotyp"] == ""
    assert erste["position"] == 0
    assert erste["gueltig"] == 1
    # ohne Kennung im IR: stabiler Hash aus Quelle>Ziel>Typ
    assert erste["kennung"] == aw.kennung("", f"{P2}::Prozess>{P2}::Faehigkeit>Realization")
    # mit Kennung im IR: woertlich uebernommen
    assert zweite["kennung"] == "id-kante-1"
    assert zweite["position"] == 1


def test_kennung_ist_deterministisch(tmp_path: Path) -> None:
    daten = ir(
        [
            element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
            element("B", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
        ],
        [kante(f"{P2}::A", f"{P2}::B")],
    )
    eins, zwei = tmp_path / "eins.sqlite", tmp_path / "zwei.sqlite"
    assert lade(daten, eins).as_dict() == lade(daten, zwei).as_dict()
    assert dump(eins) == dump(zwei)


def test_gleichnamige_elemente_bekommen_vorkommensnummern(tmp_path: Path) -> None:
    """Ohne GUID muss '#N' dasselbe Element treffen wie im Export."""
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Doppelt", notes="eins"),
                element("Doppelt", notes="zwei"),
                element("Ziel", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [
                kante(f"{P2}::Doppelt#1", f"{P2}::Ziel"),
                kante(f"{P2}::Doppelt#2", f"{P2}::Ziel", ea_type="Association"),
            ],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        kanten = [dict(z) for z in con.execute("SELECT * FROM kanten ORDER BY position")]
        namen = {
            z["kennung"]: z["name"]
            for z in con.execute("SELECT kennung, name FROM knoten WHERE name = 'Doppelt'")
        }
    finally:
        con.close()
    assert kanten[0]["gueltig"] == 1
    assert {namen[kanten[0]["quelle"]]} == {"Doppelt"}


# --------------------------------------------------------------------------
# Was nicht in den Graphen kommt
# --------------------------------------------------------------------------
def test_darstellung_und_fachmechanik_entfallen(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    bericht = lade(
        ir(
            [
                element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Notiz", ea_type="Note"),
                element("Text", ea_type="Text"),
                element("Spur", ea_type="ActivityPartition", stereotyp="Lane"),
            ]
        ),
        db,
    )
    assert bericht.knoten_elemente == 1
    assert bericht.uebersprungen == {"darstellung": 2, "fachmechanik": 1}


def test_notelink_wird_nicht_zur_kante(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    bericht = lade(
        ir(
            [
                element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Notiz", ea_type="Note"),
            ],
            [kante(f"{P2}::A", f"{P2}::Notiz", ea_type="NoteLink")],
        ),
        db,
    )
    assert bericht.kanten == 0
    assert bericht.uebersprungen == {"darstellung": 1, "notelink": 1}
    assert bericht.befunde == 0


def test_port_wird_auf_traeger_gezogen(tmp_path: Path) -> None:
    """Ports/Parts/Pins sind keine ArchiMate-Elemente (wie im Writer)."""
    db = tmp_path / "g.sqlite"
    bericht = lade(
        ir(
            [
                element("Traeger", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Anschluss", ea_type="Port", guid="{BBBBBBBB-0000-0000-0000-000000000002}",
                        owner=f"{P2}::Traeger"),
                element("Ziel", guid="{CCCCCCCC-0000-0000-0000-000000000003}"),
            ],
            [kante(f"{P2}::Anschluss", f"{P2}::Ziel", ea_type="Association")],
        ),
        db,
    )
    assert bericht.zusammengefasst == 1
    con = graph.oeffne(db)
    try:
        zeile = con.execute("SELECT * FROM v_kanten").fetchone()
        namen = {z["kennung"]: z["name"] for z in con.execute("SELECT kennung, name FROM knoten")}
    finally:
        con.close()
    assert namen[zeile["quelle"]] == "Traeger"
    assert zeile["ziel_name"] == "Ziel"


# --------------------------------------------------------------------------
# Befunde
# --------------------------------------------------------------------------
def test_k01_endpunkt_fehlt(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}")],
            [kante(f"{P2}::A", f"{P2}::Gibt es nicht")],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        fehler = graph.ungueltige_kanten(con)
        alle = graph.befunde(con)
    finally:
        con.close()
    assert [f["regel"] for f in fehler] == ["K01"]
    assert "Gibt es nicht" in fehler[0]["nachricht"]
    assert fehler[0]["schwere"] == graph.FEHLER
    assert len(alle) == 1


def test_k02_selbstkante(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}")],
            [kante(f"{P2}::A", f"{P2}::A", ea_type="Association")],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        zeilen = graph.ungueltige_kanten(con, regel="K02")
    finally:
        con.close()
    assert len(zeilen) == 1
    assert "Selbstkante" in zeilen[0]["nachricht"]


def test_k03_unbekannter_beziehungstyp(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("B", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [kante(f"{P2}::A", f"{P2}::B", ea_type="Erfunden")],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        zeilen = graph.ungueltige_kanten(con, regel="K03")
    finally:
        con.close()
    assert len(zeilen) == 1
    assert "Erfunden" in zeilen[0]["nachricht"]


def test_k04_matrix_verstoss_mit_vorschlag(tmp_path: Path) -> None:
    """Capability --Realization--> ImplementationEvent ist in keiner Richtung legal."""
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Faehigkeit", ea_type="Capability", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Meilenstein", ea_type="ImplementationEvent", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [kante(f"{P2}::Faehigkeit", f"{P2}::Meilenstein", ea_type="Realisation")],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        zeilen = graph.ungueltige_kanten(con, regel="K04")
    finally:
        con.close()
    assert len(zeilen) == 1
    assert "Capability" in zeilen[0]["nachricht"]
    assert "ImplementationEvent" in zeilen[0]["nachricht"]
    assert "zulaessig waere" in zeilen[0]["nachricht"]


def test_k05_richtung_verkehrt(tmp_path: Path) -> None:
    """Capability --Realization--> BusinessProcess ist nur umgekehrt legal."""
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Faehigkeit", ea_type="Capability", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Prozess", ea_type="BusinessProcess", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [kante(f"{P2}::Faehigkeit", f"{P2}::Prozess", ea_type="Realisation")],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        warnungen = graph.befunde(con, regel="K05")
        fehler = graph.ungueltige_kanten(con)
    finally:
        con.close()
    assert len(warnungen) == 1
    assert warnungen[0]["schwere"] == graph.WARNUNG
    assert fehler == []  # eine Warnung macht die Kante nicht ungueltig


def test_k06_duplikat(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    k = kante(f"{P2}::A", f"{P2}::B")
    lade(
        ir(
            [
                element("A", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("B", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [k, dict(k)],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        zeilen = graph.befunde(con, regel="K06")
        anzahl = con.execute("SELECT COUNT(*) FROM kanten").fetchone()[0]
    finally:
        con.close()
    assert anzahl == 2  # beide bleiben erhalten -- der Graph zeigt das Modell
    assert len(zeilen) == 1
    assert "Position 0" in zeilen[0]["nachricht"]


def test_k07_nicht_pruefbar(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("A", ea_type="Issue", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("B", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [kante(f"{P2}::A", f"{P2}::B")],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        zeilen = graph.befunde(con, regel="K07")
    finally:
        con.close()
    assert len(zeilen) == 1
    assert "keinen ArchiMate-Typ" in zeilen[0]["nachricht"]


def test_k08_mehrdeutiger_endpunkt(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Doppelt", notes="eins"),
                element("Doppelt", notes="zwei"),
                element("Ziel", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ],
            [kante(f"{P2}::Doppelt", f"{P2}::Ziel")],
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        zeilen = graph.befunde(con, regel="K08")
        kante_zeile = con.execute("SELECT * FROM kanten").fetchone()
    finally:
        con.close()
    assert len(zeilen) == 1
    assert "mehrdeutig" in zeilen[0]["nachricht"]
    # die Kante bleibt bestehen; der Graph raet nicht, er meldet
    assert kante_zeile["quelle"] is not None


def test_k09_verdichtung_und_k10_selbstkante_durch_traeger(tmp_path: Path) -> None:
    """Zwei Ports desselben Traegers -- eine ArchiMate-Kante, ein Hinweis."""
    db = tmp_path / "g.sqlite"
    bericht = lade(
        ir(
            [
                element("Traeger", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("P1", ea_type="Port", guid="{BBBBBBBB-0000-0000-0000-000000000002}",
                        owner=f"{P2}::Traeger"),
                element("P2", ea_type="Port", guid="{CCCCCCCC-0000-0000-0000-000000000003}",
                        owner=f"{P2}::Traeger"),
            ],
            [
                kante(f"{P2}::P1", f"{P2}::P2", ea_type="Association"),
            ],
        ),
        db,
    )
    assert bericht.zusammengefasst == 2
    con = graph.oeffne(db)
    try:
        hinweise = graph.befunde(con, schwere=graph.HINWEIS)
        fehler = graph.ungueltige_kanten(con)
    finally:
        con.close()
    assert [h["regel"] for h in hinweise] == ["K10"]
    assert "Traeger" in hinweise[0]["nachricht"]
    assert fehler == []


# --------------------------------------------------------------------------
# Abfragen
# --------------------------------------------------------------------------
def faehigkeitsmodell() -> dict:
    return ir(
        [
            element("Fuehrungsfaehigkeit", ea_type="Capability", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
            element("Prozess", ea_type="BusinessProcess", guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            element("Anwendung", ea_type="ApplicationComponent", guid="{CCCCCCCC-0000-0000-0000-000000000003}"),
            element("Losgeloest", ea_type="BusinessActor", guid="{DDDDDDDD-0000-0000-0000-000000000004}"),
        ],
        [
            kante(f"{P2}::Prozess", f"{P2}::Fuehrungsfaehigkeit", ea_type="Realisation"),
            kante(f"{P2}::Anwendung", f"{P2}::Prozess", ea_type="Dependency"),
        ],
    )


def test_elemente_an_faehigkeit_tiefe_1(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    con = graph.oeffne(db)
    try:
        start, umfeld = graph.elemente_an_faehigkeit(con, "Fuehrungsfaehigkeit")
    finally:
        con.close()
    assert start["archimate_typ"] == "Capability"
    assert [(z["name"], z["beziehung"], z["richtung"], z["tiefe"]) for z in umfeld] == [
        ("Prozess", "Realization", "ein", 1)
    ]


def test_elemente_an_faehigkeit_tiefe_2(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    con = graph.oeffne(db)
    try:
        _, umfeld = graph.elemente_an_faehigkeit(con, "Fuehrungsfaehigkeit", tiefe=2)
        _, nur_aus = graph.elemente_an_faehigkeit(con, "Fuehrungsfaehigkeit", tiefe=2, richtung="aus")
    finally:
        con.close()
    assert [z["name"] for z in umfeld] == ["Prozess", "Anwendung"]
    assert {z["tiefe"] for z in umfeld} == {1, 2}
    assert nur_aus == []  # eine Faehigkeit hat keine ausgehenden Kanten im Beispiel


def test_elemente_an_faehigkeit_mehrdeutig(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Faehigkeit", ea_type="Capability", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Faehigkeit", ea_type="Capability", paket=P1, guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ]
        ),
        db,
    )
    con = graph.oeffne(db)
    try:
        with pytest.raises(Mehrdeutig) as excinfo:
            graph.elemente_an_faehigkeit(con, "Faehigkeit")
        assert len(excinfo.value.kandidaten) == 2
    finally:
        con.close()


def test_elemente_an_faehigkeit_ist_keine_faehigkeit(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    con = graph.oeffne(db)
    try:
        with pytest.raises(GraphError, match="keine Faehigkeit"):
            graph.elemente_an_faehigkeit(con, "Prozess")
    finally:
        con.close()


def test_pfad_zwischen_zwei_knoten(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    con = graph.oeffne(db)
    try:
        weg = graph.pfad(con, "Anwendung", "Fuehrungsfaehigkeit")
        kein_weg = graph.pfad(con, "Anwendung", "Losgeloest")
    finally:
        con.close()
    assert weg is not None and weg["tiefe"] == 2
    assert [k["typ"] for k in weg["kanten"]] == ["Realization", "Association"] or [
        k["typ"] for k in weg["kanten"]
    ] == ["Association", "Realization"]
    assert kein_weg is None


def test_recursive_cte_aus_der_dokumentation(tmp_path: Path) -> None:
    """Die Beispielabfrage der Doku muss laufen und dasselbe liefern."""
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    sql = """
        WITH RECURSIVE umfeld(kennung, tiefe) AS (
            SELECT kennung, 0 FROM knoten
             WHERE archimate_typ = 'Capability' AND name = :name
            UNION
            SELECT n.nachbar, u.tiefe + 1
              FROM umfeld u JOIN v_nachbarschaft n ON n.knoten = u.kennung
             WHERE u.tiefe < :tiefe
        )
        SELECT w.name, w.archimate_typ, MIN(u.tiefe) AS tiefe
          FROM umfeld u JOIN knoten w ON w.kennung = u.kennung
         GROUP BY w.kennung
         ORDER BY tiefe, w.name
    """
    con = graph.oeffne(db)
    try:
        zeilen = [tuple(z) for z in con.execute(sql, {"name": "Fuehrungsfaehigkeit", "tiefe": 2})]
        start, umfeld = graph.elemente_an_faehigkeit(con, "Fuehrungsfaehigkeit", tiefe=2)
    finally:
        con.close()
    assert zeilen == [
        ("Fuehrungsfaehigkeit", "Capability", 0),
        ("Prozess", "BusinessProcess", 1),
        ("Anwendung", "ApplicationComponent", 2),
    ]
    assert [z["name"] for z in umfeld] == [z[0] for z in zeilen[1:]]


def test_statistik(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    con = graph.oeffne(db)
    try:
        daten = graph.statistik(con)
    finally:
        con.close()
    assert daten["knoten_je_art"] == {"element": 4, "paket": 2}
    assert {t["archimate_typ"] for t in daten["typen"]} == {
        "Capability",
        "BusinessProcess",
        "ApplicationComponent",
        "BusinessActor",
    }
    assert daten["befunde"] == []


# --------------------------------------------------------------------------
# Laute Fehler
# --------------------------------------------------------------------------
def test_oeffne_ist_schreibgeschuetzt(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    con = graph.oeffne(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM knoten")
    finally:
        con.close()


def test_oeffne_lehnt_fremde_datenbank_ab(tmp_path: Path) -> None:
    fremd = tmp_path / "fremd.sqlite"
    con = sqlite3.connect(fremd)
    con.execute("CREATE TABLE irgendwas (x TEXT)")
    con.commit()
    con.close()
    with pytest.raises(GraphError, match="keine Graphdatenbank"):
        graph.oeffne(fremd)


def test_lade_ueberschreibt_nicht_ohne_auftrag(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    lade(faehigkeitsmodell(), db)
    with pytest.raises(GraphError, match="existiert bereits"):
        lade(faehigkeitsmodell(), db)
    lade(faehigkeitsmodell(), db, ersetzen=True)  # mit Auftrag


def test_unbekanntes_format(tmp_path: Path) -> None:
    datei = tmp_path / "modell.txt"
    datei.write_text("nichts", encoding="utf-8")
    with pytest.raises(GraphError, match="unbekanntes Format"):
        graph.lies_ir(datei)


def test_kaputtes_ir_bricht_ab(tmp_path: Path) -> None:
    with pytest.raises(GraphError, match="ir_version"):
        graph.aufbau({"ir_version": 99, "packages": [], "elements": []})
    with pytest.raises(GraphError, match="kein Paket"):
        graph.aufbau({"ir_version": 1, "packages": [], "elements": []})
    with pytest.raises(GraphError, match="nicht deklariert"):
        graph.aufbau(
            {
                "ir_version": 1,
                "packages": [{"path": P1}],
                "elements": [element("A", paket="Fehlt")],
            }
        )


def test_elementname_mit_trennzeichen_bricht_ab() -> None:
    with pytest.raises(GraphError, match="reserviert"):
        graph.aufbau(
            {
                "ir_version": 1,
                "packages": [{"path": P1}],
                "elements": [element("A::B", paket=P1)],
            }
        )


# --------------------------------------------------------------------------
# Eingabeformate: .qea, .xml, .json
# --------------------------------------------------------------------------
@pytest.mark.skipif(not vorhanden(TESTARCHITEKTUR), reason="Testarchitektur.qea fehlt")
def test_json_ir_und_qea_ergeben_denselben_graphen(tmp_path: Path) -> None:
    ir_daten, _ = read_qea_ex(TESTARCHITEKTUR, with_refs=True, with_owners=True)
    json_datei = tmp_path / "ir.json"
    json_datei.write_text(json.dumps(ir_daten, ensure_ascii=False), encoding="utf-8")

    aus_ir = tmp_path / "aus_ir.sqlite"
    aus_json = tmp_path / "aus_json.sqlite"
    graph.lade_ir(ir_daten, aus_ir, ersetzen=True)
    graph.lade(json_datei, aus_json, ersetzen=True)

    eins, zwei = dump(aus_ir), dump(aus_json)
    for tabelle in ("knoten", "kanten", "befunde", "eigenschaften"):
        assert eins[tabelle] == zwei[tabelle], tabelle


def mit_refs(daten: dict) -> dict:
    """IR mit expliziten Referenzen (der Writer verlangt sie, der Lader nicht)."""
    daten = json.loads(json.dumps(daten))
    for paket in daten["packages"]:
        paket["ref"] = paket["path"]
    for eintrag in daten["elements"]:
        eintrag["ref"] = f"{eintrag['package']}::{eintrag['name']}"
    return daten


def test_archimate_xml_liefert_denselben_graphen(tmp_path: Path) -> None:
    """IR -> XML -> Graph muss fuer ein sauberes Modell identisch sein."""
    ir_daten = mit_refs(faehigkeitsmodell())
    xml = tmp_path / "modell.xml"
    xml.write_bytes(aw.render_bytes(ir_daten))

    aus_ir, aus_xml = tmp_path / "aus_ir.sqlite", tmp_path / "aus_xml.sqlite"
    graph.lade_ir(faehigkeitsmodell(), aus_ir, ersetzen=True)
    graph.lade(xml, aus_xml, ersetzen=True)

    def kanten(db: Path) -> list[tuple]:
        con = sqlite3.connect(db)
        try:
            return con.execute(
                "SELECT k.typ, q.name, z.name, k.gueltig FROM kanten k"
                " JOIN knoten q ON q.kennung = k.quelle JOIN knoten z ON z.kennung = k.ziel"
                " ORDER BY q.name, z.name, k.typ"
            ).fetchall()
        finally:
            con.close()

    assert kanten(aus_ir) == kanten(aus_xml)
    assert dump(aus_ir)["befunde"] == dump(aus_xml)["befunde"]


@pytest.mark.skipif(not vorhanden(TESTARCHITEKTUR), reason="Testarchitektur.qea fehlt")
def test_writer_repariert_was_der_graph_meldet(tmp_path: Path) -> None:
    """Die Arbeitsteilung: der Graph zeigt den Verstoss, der Writer baut um.

    Die Testarchitektur enthaelt acht Kanten, die die ArchiMate-Matrix nicht
    zulaesst. Der Writer ersetzt sie beim Export (deshalb ist das XML sauber);
    der Graph meldet sie am IR. Beide Sichten sind richtig -- sie beantworten
    verschiedene Fragen.
    """
    ir_daten, _ = read_qea_ex(TESTARCHITEKTUR, with_refs=True, with_owners=True)
    xml = tmp_path / "modell.xml"
    xml.write_bytes(aw.render_bytes(ir_daten))

    aus_ir, aus_xml = tmp_path / "aus_ir.sqlite", tmp_path / "aus_xml.sqlite"
    graph.lade_ir(ir_daten, aus_ir, ersetzen=True)
    graph.lade(xml, aus_xml, ersetzen=True)

    con = graph.oeffne(aus_ir)
    try:
        fehler = graph.ungueltige_kanten(con)
        zahl = con.execute("SELECT COUNT(*) FROM kanten").fetchone()[0]
    finally:
        con.close()
    con = graph.oeffne(aus_xml)
    try:
        fehler_xml = graph.ungueltige_kanten(con)
        zahl_xml = con.execute("SELECT COUNT(*) FROM kanten").fetchone()[0]
    finally:
        con.close()

    assert [f["regel"] for f in fehler] == ["K04"] * 8
    assert fehler_xml == []
    assert zahl == zahl_xml == 422


# --------------------------------------------------------------------------
# Gegenprobe gegen den Writer (Musterarchitektur)
# --------------------------------------------------------------------------
@pytest.mark.skipif(not vorhanden(MASC), reason="Musterarchitektur fehlt")
def test_masc_befunde_entsprechen_den_writer_zaehlern(tmp_path: Path) -> None:
    """Graph und Export duerfen sich nicht widersprechen.

    Der Writer entscheidet beim Export je Kante: invertieren (nur die
    Gegenrichtung ist legal), auf die naechste legale Beziehung umbauen
    (Matrixverstoss) oder als Selbstkante verwerfen. Der Graph muss dieselben
    Faelle finden -- sonst zeigt er ein anderes Modell als der Export.
    """
    ir_daten, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)

    umbauten: list[tuple[str, str, str]] = []
    original = aw._naechste_legale
    aw._naechste_legale = lambda matrix, q, r, z: (
        umbauten.append((q, r, z)),
        original(matrix, q, r, z),
    )[1]
    try:
        _, _, report = aw._aufbau(ir_daten)
    finally:
        aw._naechste_legale = original

    knoten, kanten, befunde, _, _, bericht = graph.aufbau(ir_daten)
    typ_von = {k["kennung"]: k["archimate_typ"] for k in knoten}
    kante_von = {k["kennung"]: k for k in kanten}
    matrix_tripel = []
    for befund in befunde:
        if befund["regel"] != "K04":
            continue
        kante = kante_von[befund["kante"]]
        matrix_tripel.append(
            (
                aw.MATRIX_TYPE.get(typ_von[kante["quelle"]], typ_von[kante["quelle"]]),
                kante["typ"],
                aw.MATRIX_TYPE.get(typ_von[kante["ziel"]], typ_von[kante["ziel"]]),
            )
        )

    assert sorted(matrix_tripel) == sorted(umbauten)
    assert bericht.befunde_je_regel.get("K05", 0) == report.inverted
    assert bericht.befunde_je_regel.get("K02", 0) + bericht.befunde_je_regel.get(
        "K10", 0
    ) == report.self_edges


@pytest.mark.skipif(not vorhanden(MASC), reason="Musterarchitektur fehlt")
def test_masc_archimate_typen_entsprechen_dem_writer(tmp_path: Path) -> None:
    """Der Graph darf keinem Element einen anderen ArchiMate-Typ geben als der Export."""
    ir_daten, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    elemente, _, _ = aw._aufbau(ir_daten)
    knoten, _, _, _, _, bericht = graph.aufbau(ir_daten)

    graph_typen = {k["kennung"]: k["archimate_typ"] for k in knoten}
    verglichen = 0
    for element in elemente:
        if element["id"] not in graph_typen:
            continue  # Paket-Grouping des Writers: im Graphen ein Paketknoten
        assert graph_typen[element["id"]] == element["type"], element["name"]
        verglichen += 1
    assert verglichen >= 1000
    assert bericht.knoten_elemente == verglichen + 1  # + Issue ohne Abbildung


@pytest.mark.skipif(not vorhanden(MASC), reason="Musterarchitektur fehlt")
def test_masc_graph_ist_vollstaendig_aufloesbar(tmp_path: Path) -> None:
    """Bis auf Darstellung/Mechanik/Ports hat jede Kante zwei Knoten oder einen Befund."""
    db = tmp_path / "masc.sqlite"
    bericht = graph.lade(MASC, db)
    con = graph.oeffne(db)
    try:
        ohne_ende = con.execute(
            "SELECT COUNT(*) FROM kanten WHERE quelle IS NULL OR ziel IS NULL"
        ).fetchone()[0]
        offene_kanten = con.execute(
            "SELECT COUNT(DISTINCT kante) FROM befunde WHERE regel = 'K01'"
        ).fetchone()[0]
        kennungen = con.execute("SELECT COUNT(DISTINCT kennung) FROM knoten").fetchone()[0]
        knoten = con.execute("SELECT COUNT(*) FROM knoten").fetchone()[0]
    finally:
        con.close()
    assert ohne_ende == offene_kanten  # jede offene Kante ist als K01 begruendet
    assert kennungen == knoten
    assert bericht.kanten == 1733


# --------------------------------------------------------------------------
# Kommandozeile
# --------------------------------------------------------------------------
def test_kommandozeile_laden_und_fragen(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    quelle = tmp_path / "ir.json"
    quelle.write_text(json.dumps(faehigkeitsmodell(), ensure_ascii=False), encoding="utf-8")
    db = tmp_path / "g.sqlite"

    assert graph.main(["laden", "--in", str(quelle), "--db", str(db)]) == 0
    ausgabe = capsys.readouterr().out
    assert "Knoten:  4 Elemente, 2 Pakete" in ausgabe
    assert "Kanten:  2" in ausgabe

    assert graph.main(["faehigkeit", "--db", str(db), "--name", "Fuehrungsfaehigkeit"]) == 0
    assert "Prozess" in capsys.readouterr().out

    assert graph.main(["ungueltig", "--db", str(db)]) == 0
    assert "Keine ungueltigen Kanten" in capsys.readouterr().out

    assert graph.main(["statistik", "--db", str(db)]) == 0
    assert "Capability" in capsys.readouterr().out


def test_kommandozeile_meldet_mehrdeutigkeit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "g.sqlite"
    lade(
        ir(
            [
                element("Faehigkeit", ea_type="Capability", guid="{AAAAAAAA-0000-0000-0000-000000000001}"),
                element("Faehigkeit", ea_type="Capability", paket=P1, guid="{BBBBBBBB-0000-0000-0000-000000000002}"),
            ]
        ),
        db,
    )
    assert graph.main(["faehigkeit", "--db", str(db), "--name", "Faehigkeit"]) == 2
    fehler = capsys.readouterr().err
    assert "mehrdeutig" in fehler


def test_kommandozeile_meldet_fehler(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert graph.main(["statistik", "--db", str(tmp_path / "gibt-es-nicht.sqlite")]) == 1
    assert "FEHLER" in capsys.readouterr().err
