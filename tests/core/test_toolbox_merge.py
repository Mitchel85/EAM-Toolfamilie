"""Tests fuer ``toolbox_merge.py``.

Die Mini-.qea werden mit ``qea_writer`` erzeugt (schemakonform, 15 Pflicht-
tabellen) und anschliessend per sqlite3 gezielt nachbearbeitet: nur so lassen
sich ``ea_guid``-Werte woertlich setzen, denn der Writer leitet GUIDs aus dem
Inhalt ab und akzeptiert kein ``guid``-Feld im IR.

Geprueft wird: GUID-Erhalt, Zaehlungen, Idempotenz (zweiter Lauf), ``nur``,
Sicherung, Tags aus ``t_xref`` samt leeren Werten, Determinismus und die CLI.
Der Lauf gegen den echten Katalog ``Testarchitektur.qea`` (Paket ``StEKa Bw``)
ist der Beleglauf und wird uebersprungen, wenn die Datei fehlt.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import qea_writer
import toolbox_merge as tm
from conftest import fixture_pfad, vorhanden

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
#: Echter Standardelemente-Katalog (StEKa Bw). Er liegt bewusst nicht im
#: Repo: erst der Fixture-Store der Pipeline, dann bekannte Entwicklerpfade.
#: Fehlende Leserechte zaehlen wie "fehlt" -- sonst bricht die Sammlung ab.
STEKA = fixture_pfad(
    "Testarchitektur.qea",
    "admbw-qea-editor/Testarchitektur.qea",
)
#: Zielmodell mit Bestand, das einen Teil des Katalogs schon enthaelt.
MASC = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"

GUID_E1 = "{AAAA0000-0000-0000-0000-000000000001}"
GUID_E2 = "{AAAA0000-0000-0000-0000-000000000002}"
GUID_E3 = "{AAAA0000-0000-0000-0000-000000000003}"
GUID_XREF = "{BBBB0000-0000-0000-0000-000000000001}"


def _write(path: Path, packages, elements, connectors=()) -> Path:
    """Schemakonforme .qea ueber den Writer erzeugen."""
    ir = {
        "ir_version": 1,
        "technology": {"profile": ""},
        "packages": list(packages),
        "elements": list(elements),
        "connectors": list(connectors),
        "diagrams": [],
    }
    return qea_writer.write_qea(ir, path)


def _sql(path: Path, *statements: tuple[str, tuple]) -> None:
    """Kurze Nachbearbeitung einer .qea (nur in Tests)."""
    con = sqlite3.connect(path)
    try:
        for sql, params in statements:
            con.execute(sql, params)
        con.commit()
    finally:
        con.close()


def _objects(path: Path, *, elements_only: bool = True) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        sql = "SELECT Object_ID, Name, Object_Type, ea_guid FROM t_object"
        if elements_only:
            sql += " WHERE Object_Type <> 'Package'"
        return con.execute(sql + " ORDER BY Object_ID").fetchall()
    finally:
        con.close()


def _count(path: Path, table: str) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    finally:
        con.close()


def _guid_map(path: Path) -> dict[str, str]:
    """Elementname -> ea_guid (nur echte Elemente)."""
    return {name: guid for _, name, _, guid in _objects(path)}


def _subtree_packages(con: sqlite3.Connection, root_id: int) -> list[int]:
    """Package_IDs des Teilbaums unter ``root_id`` (inklusive Wurzel)."""
    parents = {
        int(package_id): int(parent or 0)
        for package_id, parent in con.execute("SELECT Package_ID, Parent_ID FROM t_package")
    }
    result = [root_id]
    index = 0
    while index < len(result):
        current = result[index]
        index += 1
        result.extend(
            package_id for package_id, parent in parents.items() if parent == current
        )
    return result


@pytest.fixture()
def ziel(tmp_path: Path) -> Path:
    """Kleines Zielmodell: ein Paket, zwei Elemente, ein Tag."""
    path = tmp_path / "modell.qea"
    _write(
        path,
        [{"path": "Ziel"}],
        [
            {"package": "Ziel", "name": "Bestand A", "ea_type": "Class", "tags": {"Quelle": "intern"}},
            {"package": "Ziel", "name": "Bestand B", "ea_type": "Class"},
        ],
    )
    return path


@pytest.fixture()
def kasten(tmp_path: Path) -> Path:
    """Werkzeugkasten: zwei Pakete, drei Elemente, eine interne Kante.

    ``Werkzeug/Teil`` haengt unter ``Werkzeug``; die Kante zeigt auf zwei
    Elemente im selben Paket. GUIDs werden woertlich gesetzt, ein Tag-Wert auf
    NULL und eine ``t_xref``-Zeile ergaenzt.
    """
    path = tmp_path / "kasten.qea"
    _write(
        path,
        [{"path": "Werkzeug"}, {"path": "Werkzeug/Teil"}],
        [
            {
                "package": "Werkzeug",
                "name": "Std Eins",
                "ea_type": "Class",
                "stereotype": "Classification",
                "tags": {"ID": "1", "Leer": ""},
            },
            {"package": "Werkzeug", "name": "Std Zwei", "ea_type": "Class", "stereotype": "Classification"},
            {"package": "Werkzeug/Teil", "name": "Std Drei", "ea_type": "Class", "stereotype": "Classification"},
        ],
        [
            {
                "source": "Werkzeug::Std Eins",
                "target": "Werkzeug::Std Zwei",
                "ea_type": "Realisation",
                "stereotype": "",
                "name": "",
            }
        ],
    )
    _sql(
        path,
        ("UPDATE t_object SET ea_guid = ? WHERE Name = ?", (GUID_E1, "Std Eins")),
        ("UPDATE t_object SET ea_guid = ? WHERE Name = ?", (GUID_E2, "Std Zwei")),
        ("UPDATE t_object SET ea_guid = ? WHERE Name = ?", (GUID_E3, "Std Drei")),
        ("UPDATE t_objectproperties SET Value = NULL WHERE Property = 'Leer'", ()),
        (
            "INSERT INTO t_xref (XrefID, Name, Type, Visibility, Namespace, Requirement,"
            ' "Constraint", Behavior, "Partition", Description, Client, Supplier, Link)'
            " VALUES (?, 'Stereotypes', 'element property', 'Public', NULL, NULL, NULL, NULL,"
            " '0', '@STEREO;Name=Classification;', ?, NULL, NULL)",
            (GUID_XREF, GUID_E1),
        ),
    )
    return path


# --------------------------------------------------------------------------
# Kern: uebernehmen und GUIDs erhalten
# --------------------------------------------------------------------------


def test_merge_uebernimmt_elemente_und_kante(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    out = tmp_path / "neu.qea"
    bericht = tm.merge_toolbox(ziel, kasten, out, paketname="Standard")

    assert bericht["elemente"] == 3
    assert bericht["kanten"] == 1
    assert bericht["pakete"] == 2
    assert bericht["bereits_vorhanden"] == 0
    assert bericht["warnungen"] == []

    # 2 Bestandselemente + 3 Kasten-Elemente
    assert len(_objects(out)) == 5
    assert _count(out, "t_connector") == 1

    # GUIDs des Kastens woertlich, Bestand unveraendert
    guids = _guid_map(out)
    assert guids["Std Eins"] == GUID_E1
    assert guids["Std Zwei"] == GUID_E2
    assert guids["Std Drei"] == GUID_E3
    assert guids["Bestand A"] == _guid_map(ziel)["Bestand A"]

    # Bestandszeilen sind zeilengleich geblieben
    con_alt, con_neu = sqlite3.connect(ziel), sqlite3.connect(out)
    try:
        alt = con_alt.execute("SELECT * FROM t_object ORDER BY Object_ID").fetchall()
        neu = con_neu.execute(
            "SELECT * FROM t_object WHERE Object_ID <= ? ORDER BY Object_ID", (len(alt),)
        ).fetchall()
        assert neu == alt
    finally:
        con_alt.close()
        con_neu.close()


def test_paketbaum_unter_dachpaket(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    out = tmp_path / "neu.qea"
    tm.merge_toolbox(ziel, kasten, out, paketname="Standard")

    con = sqlite3.connect(out)
    try:
        rows = con.execute("SELECT Name, Parent_ID FROM t_package ORDER BY Package_ID").fetchall()
        ids = {name: parent for name, parent in rows}
        assert list(ids) == ["Ziel", "Standard", "Werkzeug", "Teil"]
        assert ids["Standard"] == 0
        assert ids["Werkzeug"] == 2  # unter Standard
        assert ids["Teil"] == 3  # unter Werkzeug (Original-Parent_ID)
        # Paketspiegel fuer die neuen Pakete vorhanden
        spiegel = con.execute(
            "SELECT count(*) FROM t_object WHERE Object_Type = 'Package'"
        ).fetchone()[0]
        assert spiegel == 2
    finally:
        con.close()


def test_zweiter_lauf_ist_idempotent(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    out = tmp_path / "neu.qea"
    erster = tm.merge_toolbox(ziel, kasten, out, paketname="Standard")
    bytes_nach_erstem = out.read_bytes()

    zweiter = tm.merge_toolbox(ziel, kasten, out, paketname="Standard")

    assert erster["elemente"] == 3
    assert zweiter["elemente"] == 0
    assert zweiter["kanten"] == 0
    assert zweiter["bereits_vorhanden"] == 3
    assert zweiter["warnungen"] == []
    assert out.read_bytes() == bytes_nach_erstem
    assert len(_objects(out)) == 5


def test_nur_uebernimmt_nur_das_genannte_paket(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    out = tmp_path / "nur.qea"
    bericht = tm.merge_toolbox(ziel, kasten, out, paketname="Standard", nur=["Teil"])

    assert bericht["elemente"] == 1
    assert bericht["kanten"] == 0
    assert bericht["pakete"] == 1  # nur "Teil", ohne Eltern "Werkzeug"
    namen = [name for _, name, _, _ in _objects(out)]
    assert "Std Drei" in namen
    assert "Std Eins" not in namen and "Std Zwei" not in namen
    # Teil haengt direkt unter dem Dach, weil der Original-Elter nicht gewaehlt ist
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT Parent_ID FROM t_package WHERE Name = 'Teil'").fetchone()[0] != 0
    finally:
        con.close()


def test_nur_mit_unbekanntem_paket_bricht_laut_ab(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    with pytest.raises(tm.ToolboxMergeError):
        tm.merge_toolbox(ziel, kasten, tmp_path / "x.qea", nur=["Gibt Es Nicht"])


# --------------------------------------------------------------------------
# Sicherung, Tags, Determinismus
# --------------------------------------------------------------------------


def test_sicherung_entspricht_dem_original(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    out = tmp_path / "neu.qea"
    tm.merge_toolbox(ziel, kasten, out, paketname="Standard")
    sicherung = out.with_suffix(".bak.qea")
    assert sicherung == tmp_path / "neu.bak.qea"
    assert sicherung.exists()
    # Erster Lauf: Basis war das Modell
    assert sicherung.read_bytes() == ziel.read_bytes()

    # Zweiter Lauf: Basis ist jetzt das Ergebnis des ersten Laufs
    tm.merge_toolbox(ziel, kasten, out, paketname="Standard")
    assert sicherung.read_bytes() == out.read_bytes()


def test_tags_aus_objectproperties_und_xref(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    out = tmp_path / "neu.qea"
    bericht = tm.merge_toolbox(ziel, kasten, out, paketname="Standard")

    con = sqlite3.connect(out)
    try:
        neue_id = con.execute(
            "SELECT Object_ID FROM t_object WHERE Name = 'Std Eins'"
        ).fetchone()[0]
        tags = con.execute(
            "SELECT Property, Value FROM t_objectproperties WHERE Object_ID = ? ORDER BY PropertyID",
            (neue_id,),
        ).fetchall()
        # Kasten-Tags wie im Kasten, dazu die Herkunft (Grundlage der stabilen GUID)
        assert [t for t in tags if t[0] != "Herkunft"] == [("ID", "1"), ("Leer", None)]
        assert ("Herkunft", "katalog:Classification/Std Eins") in tags
        xref = con.execute("SELECT XrefID, Client FROM t_xref").fetchall()
        assert len(xref) == 1
        assert xref[0][0] != GUID_XREF  # neue XrefID (PK), Inhalt uebernommen
        assert xref[0][1] == GUID_E1  # Client bleibt die woertliche Element-GUID
    finally:
        con.close()

    # 2 Tagged Values + 1 xref-Zeile
    assert bericht["tags"] == 3

    # Tag-Werte bleiben erhalten, auch wenn das Ziel viele NULL-Werte hat
    con = sqlite3.connect(out)
    try:
        assert con.execute(
            "SELECT count(*) FROM t_objectproperties WHERE Value IS NULL"
        ).fetchone()[0] == 1
    finally:
        con.close()


def test_zweimal_gleicher_merge_ist_byte_identisch(ziel: Path, kasten: Path, tmp_path: Path) -> None:
    a = tmp_path / "a.qea"
    b = tmp_path / "b.qea"
    tm.merge_toolbox(ziel, kasten, a, paketname="Standard")
    tm.merge_toolbox(ziel, kasten, b, paketname="Standard")
    assert a.read_bytes() == b.read_bytes()


def test_guid_kollision_ueberschreibt_nicht(tmp_path: Path) -> None:
    """Ein Element des Ziels traegt bereits die Kasten-GUID: es bleibt unangetastet."""
    modell = tmp_path / "modell.qea"
    _write(modell, [{"path": "Ziel"}], [{"package": "Ziel", "name": "Vorhanden", "ea_type": "Class"}])
    _sql(modell, ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Vorhanden'", (GUID_E1,)))

    kasten = tmp_path / "kasten.qea"
    _write(
        kasten,
        [{"path": "Werkzeug"}],
        [
            {"package": "Werkzeug", "name": "Std Eins", "ea_type": "Class"},
            {"package": "Werkzeug", "name": "Std Zwei", "ea_type": "Class"},
        ],
    )
    _sql(
        kasten,
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Std Eins'", (GUID_E1,)),
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Std Zwei'", (GUID_E2,)),
    )

    out = tmp_path / "neu.qea"
    bericht = tm.merge_toolbox(modell, kasten, out)
    assert bericht["bereits_vorhanden"] == 1
    assert bericht["elemente"] == 1

    guids = _guid_map(out)
    assert guids["Vorhanden"] == GUID_E1  # nicht ueberschrieben, nicht umbenannt
    assert "Std Eins" not in guids
    assert guids["Std Zwei"] == GUID_E2


def test_kante_wird_ergaenzt_wenn_endpunkte_schon_im_ziel_liegen(tmp_path: Path) -> None:
    """Beide Endpunkte stehen schon im Ziel (gleiche ea_guid), nur die Kante fehlt.

    Frueher wurde die Kante verworfen, weil ihre Endpunkte nicht in diesem Lauf
    eingefuegt wurden. Sie muss ueber die ea_guid der Endpunkte aufgeloest und
    ergaenzt werden.
    """
    modell = tmp_path / "modell.qea"
    _write(
        modell,
        [{"path": "Ziel"}],
        [
            {"package": "Ziel", "name": "Bestand A", "ea_type": "Class"},
            {"package": "Ziel", "name": "Bestand B", "ea_type": "Class"},
        ],
    )
    _sql(
        modell,
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Bestand A'", (GUID_E1,)),
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Bestand B'", (GUID_E2,)),
    )

    kasten = tmp_path / "kasten.qea"
    _write(
        kasten,
        [{"path": "Werkzeug"}],
        [
            {"package": "Werkzeug", "name": "Std Eins", "ea_type": "Class"},
            {"package": "Werkzeug", "name": "Std Zwei", "ea_type": "Class"},
        ],
        [
            {
                "source": "Werkzeug::Std Eins",
                "target": "Werkzeug::Std Zwei",
                "ea_type": "Realisation",
                "stereotype": "",
                "name": "",
            }
        ],
    )
    _sql(
        kasten,
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Std Eins'", (GUID_E1,)),
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Std Zwei'", (GUID_E2,)),
    )

    out = tmp_path / "neu.qea"
    bericht = tm.merge_toolbox(modell, kasten, out)

    assert bericht["elemente"] == 0
    assert bericht["bereits_vorhanden"] == 2
    assert bericht["kanten"] == 1  # Kante fehlte im Ziel -> ergaenzt
    assert bericht["warnungen"] == []

    con = sqlite3.connect(out)
    try:
        ids = {guid: object_id for object_id, guid in con.execute("SELECT Object_ID, ea_guid FROM t_object")}
        kanten = con.execute("SELECT Start_Object_ID, End_Object_ID FROM t_connector").fetchall()
        # Endpunkte sind die vorhandenen Objekte, keine Dubletten
        assert kanten == [(ids[GUID_E1], ids[GUID_E2])]
        assert con.execute(
            "SELECT count(*) FROM t_object WHERE Object_Type <> 'Package'"
        ).fetchone()[0] == 2
    finally:
        con.close()


def test_kante_ohne_aufloesbaren_endpunkt_wird_gewarnt(tmp_path: Path) -> None:
    """Fehlt ein Endpunkt wirklich im Ziel, bleibt die Kante weg -- mit Warnung."""
    modell = tmp_path / "modell.qea"
    _write(modell, [{"path": "Ziel"}], [{"package": "Ziel", "name": "A", "ea_type": "Class"}])

    kasten = tmp_path / "kasten.qea"
    _write(
        kasten,
        [{"path": "Werkzeug"}],
        [
            {"package": "Werkzeug", "name": "Std Eins", "ea_type": "Class"},
            {"package": "Werkzeug", "name": "Std Zwei", "ea_type": "Class"},
        ],
        [
            {
                "source": "Werkzeug::Std Eins",
                "target": "Werkzeug::Std Zwei",
                "ea_type": "Realisation",
                "stereotype": "",
                "name": "",
            }
        ],
    )
    _sql(
        kasten,
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Std Eins'", (GUID_E1,)),
        ("UPDATE t_object SET ea_guid = ? WHERE Name = 'Std Zwei'", (GUID_E2,)),
        # Paketspiegel ohne passendes Kasten-Paket: Endpunkt ist im Ziel unbekannt.
        (
            "INSERT INTO t_object (Object_ID, Object_Type, Name, Package_ID, ea_guid)"
            " SELECT max(Object_ID) + 1, 'Package', 'Waise', Package_ID, ? FROM t_object",
            (GUID_E3,),
        ),
        (
            "INSERT INTO t_connector (Connector_ID, Connector_Type, Start_Object_ID, End_Object_ID, ea_guid)"
            " SELECT max(Connector_ID) + 1, 'Dependency',"
            " (SELECT Object_ID FROM t_object WHERE Name = 'Std Eins'),"
            " (SELECT Object_ID FROM t_object WHERE Name = 'Waise'), ? FROM t_connector",
            ("{DDDD0000-0000-0000-0000-000000000001}",),
        ),
    )

    out = tmp_path / "neu.qea"
    bericht = tm.merge_toolbox(modell, kasten, out)

    assert bericht["elemente"] == 2
    assert bericht["kanten"] == 1  # nur die Kante mit zwei aufloesbaren Endpunkten
    assert any("nicht aufloesbar" in warnung for warnung in bericht["warnungen"])

    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM t_connector").fetchone()[0] == 1
    finally:
        con.close()


def test_paketspiegel_behaelt_stereotyp_und_paket_tags(tmp_path: Path) -> None:
    """Paket-Stereotyp (t_xref) und Paket-Tags (t_objectproperties am Spiegel) bleiben."""
    modell = tmp_path / "modell.qea"
    _write(modell, [{"path": "Ziel"}], [{"package": "Ziel", "name": "A", "ea_type": "Class"}])

    # Unterpaket "Teil" hat im Kasten einen Paketspiegel (Wurzelpakete nicht).
    kasten = tmp_path / "kasten.qea"
    _write(
        kasten,
        [{"path": "Werkzeug"}, {"path": "Werkzeug/Teil"}],
        [
            {"package": "Werkzeug", "name": "E1", "ea_type": "Class"},
            {"package": "Werkzeug/Teil", "name": "E2", "ea_type": "Class"},
        ],
    )
    _sql(
        kasten,
        (
            "UPDATE t_object SET Stereotype = 'ArchitecturalDescription' "
            "WHERE Object_Type = 'Package' AND Name = 'Teil'",
            (),
        ),
        (
            "INSERT INTO t_objectproperties (Object_ID, Property, Value, Notes, ea_guid) "
            "SELECT Object_ID, 'purpose', NULL, '', NULL FROM t_object "
            "WHERE Object_Type = 'Package' AND Name = 'Teil'",
            (),
        ),
        (
            "INSERT INTO t_xref (XrefID, Name, Type, Visibility, Namespace, Requirement,"
            ' "Constraint", Behavior, "Partition", Description, Client, Supplier, Link)'
            " SELECT '{CCCC0000-0000-0000-0000-000000000001}', 'Stereotypes', 'element property',"
            " 'Public', NULL, NULL, NULL, NULL, '0', '@STEREO;Name=ArchitecturalDescription;',"
            " ea_guid, NULL, NULL FROM t_package WHERE Name = 'Teil'",
            (),
        ),
    )

    out = tmp_path / "neu.qea"
    tm.merge_toolbox(modell, kasten, out)

    con = sqlite3.connect(out)
    try:
        spiegel = con.execute(
            "SELECT Object_ID, Stereotype, ea_guid FROM t_object "
            "WHERE Object_Type = 'Package' AND Name = 'Teil'"
        ).fetchall()
        assert len(spiegel) == 1
        spiegel_id, stereotyp, spiegel_guid = spiegel[0]
        assert stereotyp == "ArchitecturalDescription"
        paket_guid = con.execute("SELECT ea_guid FROM t_package WHERE Name = 'Teil'").fetchone()[0]
        assert spiegel_guid == paket_guid
        tags = con.execute(
            "SELECT Property, Value FROM t_objectproperties WHERE Object_ID = ?", (spiegel_id,)
        ).fetchall()
        assert tags == [("purpose", None)]
        assert con.execute(
            "SELECT count(*) FROM t_xref WHERE Client = ?", (paket_guid,)
        ).fetchone()[0] == 1
    finally:
        con.close()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_gibt_json_bericht_aus(ziel: Path, kasten: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "cli.qea"
    code = tm.main([str(ziel), str(kasten), "--out", str(out), "--paket", "Standard", "--nur", "Werkzeug"])
    assert code == 0
    bericht = json.loads(capsys.readouterr().out)
    assert set(bericht) == {"pakete", "elemente", "kanten", "tags", "bereits_vorhanden", "warnungen"}
    # --nur Werkzeug schliesst das Unterpaket "Teil" ein
    assert bericht["elemente"] == 3
    assert out.exists()


def test_cli_meldet_nicht_lesbare_datei(tmp_path: Path, capsys) -> None:
    kaputt = tmp_path / "kaputt.qea"
    kaputt.write_bytes(b"kein sqlite")
    code = tm.main([str(tmp_path / "fehlt.qea"), str(kaputt), "--out", str(tmp_path / "x.qea")])
    assert code == 2
    assert "toolbox_merge:" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Beleglauf gegen die echte Fixture
# --------------------------------------------------------------------------


@pytest.mark.skipif(not vorhanden(STEKA), reason="Katalog Testarchitektur.qea fehlt")
def test_beleglauf_steka_bw(tmp_path: Path) -> None:
    """Belegfall: echter StEKa-Katalog (Paket 141, Teilbaum) auf ein kleines Ziel.

    Gemessen an der Datei: 10 Pakete, 305 ``t_object``-Zeilen (296 Elemente +
    9 Paketspiegel), 273 interne Kanten, 2917 Tagged Values, 373 xref-Zeilen,
    53 Kanten-Tags. Der Rest des Modells (265 Objekte) darf NICHT mitkommen.
    """
    modell = tmp_path / "ziel.qea"
    _write(
        modell,
        [{"path": "Ziel"}],
        [
            {"package": "Ziel", "name": "Bestand A", "ea_type": "Class"},
            {"package": "Ziel", "name": "Bestand B", "ea_type": "Class"},
        ],
    )
    bestand_guids = set(_guid_map(modell).values())

    out = tmp_path / "steka.qea"
    bericht = tm.merge_toolbox(modell, STEKA, out, paketname="Standard", nur=["StEKa Bw"])

    assert bericht["pakete"] == 10
    assert bericht["elemente"] == 296  # 305 t_object-Zeilen minus 9 Paketspiegel
    assert bericht["kanten"] == 273
    assert bericht["tags"] == 3343  # 2917 objectproperties + 373 xref + 53 Kanten-Tags
    assert bericht["bereits_vorhanden"] == 0
    assert bericht["warnungen"] == []

    con_quelle = sqlite3.connect(f"file:{STEKA}?mode=ro", uri=True)
    con_ziel = sqlite3.connect(out)
    try:
        teilbaum = _subtree_packages(con_quelle, 141)
        platzhalter = ",".join("?" * len(teilbaum))

        quell_objekte = {
            guid
            for (guid,) in con_quelle.execute(
                f"SELECT ea_guid FROM t_object WHERE Package_ID IN ({platzhalter})",
                teilbaum,
            )
        }
        assert len(quell_objekte) == 305
        ziel_objekte = {guid for (guid,) in con_ziel.execute("SELECT ea_guid FROM t_object")}
        assert quell_objekte <= ziel_objekte  # alle 305 woertlich erhalten
        assert bestand_guids <= ziel_objekte  # Bestand unangetastet

        quell_pakete = {
            guid
            for (guid,) in con_quelle.execute(
                f"SELECT ea_guid FROM t_package WHERE Package_ID IN ({platzhalter})",
                teilbaum,
            )
        }
        ziel_pakete = {guid for (guid,) in con_ziel.execute("SELECT ea_guid FROM t_package")}
        assert len(quell_pakete) == 10
        assert quell_pakete <= ziel_pakete

        # Nichts ausserhalb des Teilbaums darf mitgekommen sein.
        fremd = {
            guid
            for (guid,) in con_quelle.execute(
                f"SELECT ea_guid FROM t_object WHERE Package_ID NOT IN ({platzhalter})",
                teilbaum,
            )
        }
        assert len(fremd) == 265
        assert not (fremd & ziel_objekte)

        # Paketspiegel behalten ihren Stereotyp (ArchitecturalDescription).
        assert con_ziel.execute("SELECT count(*) FROM t_object WHERE Object_Type = 'Package'").fetchone()[0] == 10
        assert con_ziel.execute(
            "SELECT count(*) FROM t_object WHERE Object_Type = 'Package' "
            "AND Stereotype = 'ArchitecturalDescription'"
        ).fetchone()[0] == 4
        # Paket-Tags (71 Zeilen an Paketspiegeln) sind mitgekommen.
        assert con_ziel.execute(
            "SELECT count(*) FROM t_objectproperties WHERE Object_ID IN "
            "(SELECT Object_ID FROM t_object WHERE Object_Type = 'Package')"
        ).fetchone()[0] == 71
        assert con_ziel.execute(
            "SELECT count(*) FROM (SELECT ea_guid FROM t_object GROUP BY ea_guid HAVING count(*) > 1)"
        ).fetchone()[0] == 0

        # Zweiter Lauf: alles bereits vorhanden, Bytes unveraendert.
        erste_bytes = out.read_bytes()
        zweiter = tm.merge_toolbox(modell, STEKA, out, paketname="Standard", nur=["StEKa Bw"])
        assert zweiter["elemente"] == 0
        assert zweiter["bereits_vorhanden"] == 296
        assert out.read_bytes() == erste_bytes
    finally:
        con_quelle.close()
        con_ziel.close()


@pytest.mark.skipif(
    not (vorhanden(STEKA) and vorhanden(MASC)), reason="Katalog oder MASC-Fixture fehlt"
)
def test_beleglauf_steka_in_masc_uebernimmt_alle_kanten(tmp_path: Path) -> None:
    """Regression: Endpunkte stehen schon in der MASC -- die Kanten muessen trotzdem kommen.

    Gemessen: 273 kataloginterne Kanten in der Quelle. 24 davon fehlten frueher,
    weil beide Endpunkte bereits im Ziel lagen und die Uebernahmeregel nur in
    diesem Lauf eingefuegte Endpunkte kannte.
    """
    modell = tmp_path / "masc.qea"
    shutil.copyfile(MASC, modell)
    out = tmp_path / "masc_steka.qea"
    bericht = tm.merge_toolbox(modell, STEKA, out, paketname="Standard", nur=["StEKa Bw"])

    assert bericht["kanten"] == 24  # genau die in der MASC noch fehlenden Kanten
    assert bericht["bereits_vorhanden"] == 284  # Endpunkte standen schon im Ziel
    assert not [w for w in bericht["warnungen"] if "nicht aufloesbar" in w]

    con_quelle = sqlite3.connect(f"file:{STEKA}?mode=ro", uri=True)
    con_ziel = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        teilbaum = _subtree_packages(con_quelle, 141)
        platzhalter = ",".join("?" * len(teilbaum))
        kanten = {
            guid
            for (guid,) in con_quelle.execute(
                "SELECT ea_guid FROM t_connector WHERE Start_Object_ID IN "
                f"(SELECT Object_ID FROM t_object WHERE Package_ID IN ({platzhalter})) AND "
                f"End_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN ({platzhalter}))",
                teilbaum + teilbaum,
            )
        }
        assert len(kanten) == 273
        ziel_kanten = {guid for (guid,) in con_ziel.execute("SELECT ea_guid FROM t_connector")}
        assert kanten <= ziel_kanten
        # Keine Kante zeigt ins Leere.
        assert con_ziel.execute(
            "SELECT count(*) FROM t_connector WHERE Start_Object_ID NOT IN "
            "(SELECT Object_ID FROM t_object) OR End_Object_ID NOT IN "
            "(SELECT Object_ID FROM t_object)"
        ).fetchone()[0] == 0
    finally:
        con_quelle.close()
        con_ziel.close()


@pytest.mark.skipif(not vorhanden(STEKA), reason="Katalog Testarchitektur.qea fehlt")
def test_steka_laesst_modell_ausserhalb_des_teilbaums_weg(tmp_path: Path) -> None:
    """Ohne ``nur`` kaeme das ganze Modell (570 Objekte) -- mit ``nur`` nur der Teilbaum."""
    modell = tmp_path / "ziel.qea"
    _write(modell, [{"path": "Ziel"}], [{"package": "Ziel", "name": "A", "ea_type": "Class"}])

    out = tmp_path / "steka.qea"
    bericht = tm.merge_toolbox(modell, STEKA, out, nur=["StEKa Bw"])
    assert bericht["elemente"] == 296
    assert bericht["elemente"] < 570


def test_fixture_kasten_wird_nicht_veraendert(kasten: Path, tmp_path: Path) -> None:
    """Der Kasten ist reine Eingabe: Bytes bleiben gleich."""
    vorher = kasten.read_bytes()
    kopie = tmp_path / "kopie.qea"
    shutil.copyfile(kasten, kopie)
    modell = tmp_path / "m.qea"
    _write(modell, [{"path": "Ziel"}], [{"package": "Ziel", "name": "A", "ea_type": "Class"}])
    tm.merge_toolbox(modell, kasten, tmp_path / "out.qea")
    assert kasten.read_bytes() == vorher
    assert kopie.read_bytes() == vorher
