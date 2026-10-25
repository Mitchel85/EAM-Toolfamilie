"""Abnahmetests fuer den deterministischen .qea-Writer.

Deckt die Definition of Done ab:
  * zwei Builds -> byte-identische Datei (sha256 gleich)
  * Datei in sqlite3 lesbar, alle geforderten Tabellen vorhanden
plus die harten Regeln (GUID-Formel, ID-Vergabe, keine Zeitstempel,
lautes Scheitern statt stillem Leerergebnis).
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
if str(ROOT) not in sys.path:  # pragma: no cover - Import-Komfort
    sys.path.insert(0, str(ROOT))

import qea_writer  # noqa: E402
from qea_writer import QeaWriterError, guid_for, plan_model, render_bytes, write_qea  # noqa: E402

FIXTURE = ROOT / "fixtures" / "ir_synthetic_mini.json"
TABLES = {
    "t_package",
    "t_object",
    "t_connector",
    "t_objectproperties",
    "t_diagram",
    "t_xref",
}


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


# --------------------------------------------------------------------------
# Akzeptanzkriterien
# --------------------------------------------------------------------------


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    ir = load_fixture()
    first = write_qea(ir, tmp_path / "a.qea")
    second = write_qea(ir, tmp_path / "b.qea")
    assert sha256(first) == sha256(second)
    # Auch ein erneuter Build auf denselben Pfad muss identisch sein.
    again = write_qea(ir, tmp_path / "a.qea")
    assert sha256(again) == sha256(first)


def test_two_processes_produce_identical_bytes(tmp_path: Path) -> None:
    """Kein prozessabhaengiger Zustand (Hash-Salt, PID, Uhrzeit)."""
    hashes = []
    for name in ("p1", "p2"):
        target = tmp_path / name / "modell.qea"
        result = subprocess.run(
            [sys.executable, str(ROOT / "qea_writer.py"), str(FIXTURE), str(target)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        hashes.append(sha256(target))
    assert hashes[0] == hashes[1]


def test_file_is_readable_and_has_all_tables(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        names = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = TABLES - names
        assert not missing, f"fehlende Tabellen: {sorted(missing)}"
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        counts = {table: con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in TABLES}
    finally:
        con.close()
    assert counts["t_package"] == 3
    # Wurzelpaket ohne Spiegel: 3 Pakete - 1 Wurzel = 2 Spiegel + 5 Elemente
    assert counts["t_object"] == 7
    assert counts["t_connector"] == 4
    assert counts["t_objectproperties"] == 6
    assert counts["t_diagram"] == 0
    assert counts["t_xref"] == 10


# --------------------------------------------------------------------------
# GUID-Regeln
# --------------------------------------------------------------------------


def test_element_guid_matches_documented_formula(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    expected = guid_for("Beispielmodell/Komponenten", "System", "Komponente A")
    digest = hashlib.sha256("Beispielmodell/Komponenten|System|Komponente A".encode()).hexdigest()
    assert expected == "{" + "-".join(
        [digest[:8], digest[8:12], digest[12:16], digest[16:20], digest[20:32]]
    ).upper() + "}"
    con = connect(path)
    try:
        row = con.execute(
            "SELECT ea_guid FROM t_object WHERE Name = ? AND Object_Type <> 'Package'",
            ("Komponente A",),
        ).fetchone()
    finally:
        con.close()
    assert row["ea_guid"] == expected


def test_all_guids_are_ea_formatted_and_unique(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        for table in ("t_package", "t_object", "t_connector"):
            guids = [row["ea_guid"] for row in con.execute(f'SELECT ea_guid FROM "{table}"')]
            assert len(guids) == len(set(guids)), f"doppelte GUID in {table}"
            for value in guids:
                assert value.startswith("{") and value.endswith("}"), value
                assert len(value) == 38, value
                assert value[9] == "-" and value[14] == "-" and value[19] == "-" and value[24] == "-"
                assert value[1:37].replace("-", "").upper() == value[1:37].replace("-", "")
    finally:
        con.close()


def test_duplicate_elements_get_numbered_guids(tmp_path: Path) -> None:
    """Gleiche (Pfad, Stereotyp, Name) sind in echten Modellen vorhanden."""
    ir = load_fixture()
    duplicate = copy.deepcopy(ir["elements"][0])
    duplicate["notes"] = "Synthetische Komponente A (zweite Auspraegung)."
    ir["elements"].append(duplicate)
    for connector in ir["connectors"]:
        for side in ("source", "target"):
            if connector[side].endswith("::Komponente A"):
                connector[side] += "#1"

    first = render_bytes(ir)
    plan = plan_model(ir)
    guids = [element.guid for element in plan.elements if element.name == "Komponente A"]
    assert len(guids) == 2
    assert guids[0] != guids[1]
    canonical = guid_for("Beispielmodell/Komponenten", "System", "Komponente A")
    assert canonical in guids

    # Reihenfolge im IR darf das Ergebnis nicht veraendern.
    ir["elements"].reverse()
    ir["packages"].reverse()
    ir["connectors"].reverse()
    assert render_bytes(ir) == first


def test_duplicate_names_need_occurrence_suffix() -> None:
    ir = load_fixture()
    duplicate = copy.deepcopy(ir["elements"][1])
    duplicate["name"] = "Komponente A"
    duplicate["notes"] = "Zweite Auspraegung von A."
    ir["elements"].append(duplicate)

    with pytest.raises(QeaWriterError, match="mehrdeutig"):
        plan_model(ir)

    for connector in ir["connectors"]:
        for side in ("source", "target"):
            if connector[side].endswith("::Komponente A"):
                connector[side] += "#1"
    # Ersatz fuer den urspruenglichen Verweis auf 'Komponente B' bleibt eindeutig.
    plan = plan_model(ir)
    assert len(plan.elements) == 6
    assert len({element.guid for element in plan.elements}) == 6
    with pytest.raises(QeaWriterError, match="Vorkommen 3"):
        broken = copy.deepcopy(ir)
        broken["connectors"][0]["source"] = "Beispielmodell/Komponenten::Komponente A#3"
        plan_model(broken)


# --------------------------------------------------------------------------
# IDs, Sortierung, Zeitstempel
# --------------------------------------------------------------------------


def test_ids_are_consecutive_from_one(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        package_ids = [row[0] for row in con.execute("SELECT Package_ID FROM t_package ORDER BY 1")]
        object_ids = [row[0] for row in con.execute("SELECT Object_ID FROM t_object ORDER BY 1")]
        connector_ids = [row[0] for row in con.execute("SELECT Connector_ID FROM t_connector ORDER BY 1")]
        property_ids = [row[0] for row in con.execute("SELECT PropertyID FROM t_objectproperties ORDER BY 1")]
    finally:
        con.close()
    assert package_ids == list(range(1, len(package_ids) + 1))
    assert object_ids == list(range(1, len(object_ids) + 1))
    assert connector_ids == list(range(1, len(connector_ids) + 1))
    assert property_ids == list(range(1, len(property_ids) + 1))


def test_ids_follow_sorted_package_path_and_name(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        packages = [
            (row["Package_ID"], row["Name"])
            for row in con.execute("SELECT Package_ID, Name FROM t_package ORDER BY Package_ID")
        ]
        # Paket-IDs folgen der Pfadsortierung: Beispielmodell < Beispielmodell/Komponenten < .../Schnittstellen
        assert packages == [(1, "Beispielmodell"), (2, "Komponenten"), (3, "Schnittstellen")]
        rows = con.execute(
            "SELECT o.Object_ID, o.Name, p.Name AS paket FROM t_object o "
            "JOIN t_package p ON p.Package_ID = o.Package_ID "
            "WHERE o.Object_Type <> 'Package' ORDER BY o.Object_ID"
        ).fetchall()
    finally:
        con.close()
    keys = [(row["paket"], row["Name"]) for row in rows]
    assert keys == sorted(keys)


def test_no_timestamps_anywhere(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        for table, column in (
            ("t_package", "CreatedDate"),
            ("t_package", "ModifiedDate"),
            ("t_object", "CreatedDate"),
            ("t_object", "ModifiedDate"),
        ):
            values = {
                row[0]
                for row in con.execute(f'SELECT "{column}" FROM "{table}"')
            }
            assert values <= {""}, f"{table}.{column} enthaelt Zeitstempel: {values}"
    finally:
        con.close()


# --------------------------------------------------------------------------
# Semantik: Paketspiegel, Tags, Stereotype, Kanten
# --------------------------------------------------------------------------


def test_package_mirror_convention(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        roots = con.execute("SELECT Package_ID, Name FROM t_package WHERE Parent_ID = 0").fetchall()
        assert len(roots) == 1
        assert con.execute(
            "SELECT COUNT(*) FROM t_object WHERE Object_Type='Package' AND Name=?",
            (roots[0]["Name"],),
        ).fetchone()[0] == 0

        mirrors = con.execute(
            "SELECT o.Object_ID, o.Name, o.Package_ID, o.PDATA1, o.NType, o.ea_guid, "
            "p.Package_ID AS eigene_id, p.Parent_ID, p.ea_guid AS paket_guid "
            "FROM t_object o JOIN t_package p ON p.ea_guid = o.ea_guid "
            "WHERE o.Object_Type = 'Package'"
        ).fetchall()
        assert len(mirrors) == 2
        for row in mirrors:
            assert row["PDATA1"] == str(row["eigene_id"])
            assert row["NType"] == 0
            assert row["Package_ID"] == row["Parent_ID"]
            assert row["ea_guid"] == row["paket_guid"]
    finally:
        con.close()


def test_tags_are_written_as_object_properties(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        rows = con.execute(
            "SELECT o.Name, p.Property, p.Value, p.ea_guid FROM t_objectproperties p "
            "JOIN t_object o ON o.Object_ID = p.Object_ID ORDER BY p.PropertyID"
        ).fetchall()
        values = {(row["Name"], row["Property"], row["Value"]) for row in rows}
        assert ("Komponente A", "Herkunft", "synthetisch") in values
        assert ("Komponente A", "Reifegrad", "2") in values
        assert ("Dienst C", "Verfuegbarkeit", "99.5") in values
        assert ("Schnittstelle Y", "Richtung", "eingehend") in values
        assert all(row["ea_guid"].startswith("{") for row in rows)
        assert len({row["ea_guid"] for row in rows}) == len(rows)
    finally:
        con.close()


def test_connector_tags_are_written(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        rows = con.execute(
            "SELECT c.Stereotype, t.Property, t.VALUE, t.ea_guid FROM t_connectortag t "
            "JOIN t_connector c ON c.Connector_ID = t.ElementID"
        ).fetchall()
        assert len(rows) == 1
        assert (rows[0]["Stereotype"], rows[0]["Property"], rows[0]["VALUE"]) == (
            "Satisfy",
            "Begruendung",
            "synthetisch",
        )
    finally:
        con.close()


def test_xref_contains_one_stereo_row_per_stereotyped_item(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        rows = con.execute(
            "SELECT Type, Description, Client FROM t_xref ORDER BY Client, Type"
        ).fetchall()
        element_rows = [row for row in rows if row["Type"] == "element property"]
        connector_rows = [row for row in rows if row["Type"] == "connector property"]
        assert len(element_rows) == 6  # 5 Elemente + 1 Paket mit Stereotyp
        assert len(connector_rows) == 4
        for row in rows:
            assert row["Description"].startswith("@STEREO;Name=")
            assert row["Description"].endswith("@ENDSTEREO;")
            assert "FQName=Beispielprofil::" in row["Description"]
            assert row["Client"].startswith("{")
        clients = [row["Client"] for row in rows]
        assert len(clients) == len(set(clients))
        # Client-GUIDs zeigen auf existierende Objekte/Kanten.
        known = {
            row[0]
            for row in con.execute("SELECT ea_guid FROM t_object UNION SELECT ea_guid FROM t_connector")
        }
        assert set(clients) <= known
    finally:
        con.close()


def test_connectors_reference_existing_objects(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        broken = con.execute(
            "SELECT COUNT(*) FROM t_connector WHERE Start_Object_ID NOT IN "
            "(SELECT Object_ID FROM t_object) OR End_Object_ID NOT IN (SELECT Object_ID FROM t_object)"
        ).fetchone()[0]
        assert broken == 0
        names = {
            (row["Start_Object_ID"], row["End_Object_ID"], row["Stereotype"])
            for row in con.execute("SELECT Start_Object_ID, End_Object_ID, Stereotype FROM t_connector")
        }
        lookup = {
            row["Name"]: row["Object_ID"]
            for row in con.execute("SELECT Name, Object_ID FROM t_object WHERE Object_Type <> 'Package'")
        }
        assert (lookup["Komponente A"], lookup["Schnittstelle X"], "Provides") in names
    finally:
        con.close()


def test_diagram_table_is_empty_and_diagrams_are_rejected(tmp_path: Path) -> None:
    path = write_qea(load_fixture(), tmp_path / "modell.qea")
    con = connect(path)
    try:
        assert con.execute("SELECT COUNT(*) FROM t_diagram").fetchone()[0] == 0
    finally:
        con.close()
    ir = load_fixture()
    ir["diagrams"] = [{"name": "Nicht erlaubt"}]
    with pytest.raises(QeaWriterError, match="Sichten"):
        plan_model(ir)


# --------------------------------------------------------------------------
# Stabilitaet gegen Eingabereihenfolge
# --------------------------------------------------------------------------


def test_shuffled_input_produces_identical_bytes() -> None:
    ir = load_fixture()
    reference = render_bytes(ir)
    rng = random.Random(20261021)
    for _ in range(3):
        shuffled = copy.deepcopy(ir)
        for key in ("packages", "elements", "connectors"):
            rng.shuffle(shuffled[key])
        assert render_bytes(shuffled) == reference


def test_tag_order_does_not_matter(tmp_path: Path) -> None:
    ir = load_fixture()
    reference = render_bytes(ir)
    reordered = copy.deepcopy(ir)
    for element in reordered["elements"]:
        if "tags" in element:
            element["tags"] = dict(reversed(list(element["tags"].items())))
    assert render_bytes(reordered) == reference


# --------------------------------------------------------------------------
# Laute Fehler (kein stilles Leerergebnis)
# --------------------------------------------------------------------------


def test_connector_can_end_at_a_package() -> None:
    """EA-Modelle verbinden auch Pakete (MASC: 234 Kanten an Paketspiegeln)."""
    ir = load_fixture()
    ir["connectors"].append(
        {
            "source": "Beispielmodell/Komponenten::Komponente A",
            "target": "Beispielmodell/Schnittstellen",
            "stereotype": "Contains",
            "ea_type": "Dependency",
        }
    )
    plan = plan_model(ir)
    connector = next(c for c in plan.connectors if c.stereotype == "Contains")
    package = next(p for p in plan.packages if p.path == "Beispielmodell/Schnittstellen")
    assert connector.target_object_id == package.mirror_object_id

    ir["connectors"][-1]["target"] = "Beispielmodell"
    with pytest.raises(QeaWriterError, match="Wurzelpaket"):
        plan_model(ir)
    ir["connectors"][-1]["target"] = "Gibt/Es/Nicht"
    with pytest.raises(QeaWriterError, match="kein deklariertes Paket"):
        plan_model(ir)


def test_unnamed_elements_are_kept_and_addressable() -> None:
    """Echte Modelle enthalten unbenannte Notizen/Texte (MASC: 268)."""
    ir = load_fixture()
    ir["elements"].append(
        {
            "package": "Beispielmodell/Komponenten",
            "name": "",
            "stereotype": "",
            "ea_type": "Text",
            "notes": "Synthetische Notiz ohne Namen.",
        }
    )
    ir["connectors"].append(
        {
            "source": "Beispielmodell/Komponenten::Komponente A",
            "target": "Beispielmodell/Komponenten::#1",
            "stereotype": "NoteLink",
            "ea_type": "NoteLink",
        }
    )
    plan = plan_model(ir)
    unnamed = next(element for element in plan.elements if element.name == "")
    connector = next(c for c in plan.connectors if c.stereotype == "NoteLink")
    assert connector.target_object_id == unnamed.object_id
    assert render_bytes(ir) == render_bytes(ir)

    # Zweites unbenanntes Element: '#2' adressiert es, ohne Nummer ist die
    # Referenz unvollstaendig (kein Name, keine Position).
    two = copy.deepcopy(ir)
    second = dict(two["elements"][-1], notes="Zweite Notiz ohne Namen.")
    two["elements"].append(second)
    two["connectors"][-1]["target"] = "Beispielmodell/Komponenten::#2"
    plan_two = plan_model(two)
    connector_two = next(c for c in plan_two.connectors if c.stereotype == "NoteLink")
    target = next(e for e in plan_two.elements if e.object_id == connector_two.target_object_id)
    assert target.notes == "Zweite Notiz ohne Namen."

    with pytest.raises(QeaWriterError, match="Elementname"):
        plan_model(copy.deepcopy(ir) | {"connectors": [dict(ir["connectors"][-1], target="Beispielmodell/Komponenten::")]})


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda ir: ir.pop("packages"), "packages"),
        (lambda ir: ir.update(ir_version=2), "ir_version"),
        (lambda ir: ir.update(unbekannt=True), "unbekannte Felder"),
        (lambda ir: ir["elements"][0].update(package="Nicht/Da"), "nicht deklariert"),
        (lambda ir: ir["elements"][0].pop("name"), "name"),
        (lambda ir: ir["connectors"][0].update(source="Beispielmodell::Fehlt"), "kein deklariertes Element"),
        (lambda ir: ir["packages"].append({"path": "Beispielmodell/OhneEltern/Kind"}), "nicht deklariert"),
        (lambda ir: ir["packages"].append({"path": "Beispielmodell"}), "mehrfach deklariert"),
        (lambda ir: ir["packages"].append({"path": "Beispielmodell/Rueck\\slash"}), "Backslash"),
        (lambda ir: ir["elements"][0].update(tags={"Herkunft": None}), "null"),
        (lambda ir: ir["elements"][1].update(name="Komponente A"), "mehrdeutig"),
        (lambda ir: ir["elements"].clear(), "kein Element"),
    ],
)
def test_invalid_ir_fails_loudly(mutate, match: str) -> None:
    ir = load_fixture()
    mutate(ir)
    with pytest.raises(QeaWriterError, match=match):
        plan_model(ir)


def test_root_package_tags_are_rejected_instead_of_dropped() -> None:
    ir = load_fixture()
    ir["packages"][0]["tags"] = {"Quelle": "synthetisch"}
    with pytest.raises(QeaWriterError, match="Wurzelpakete"):
        plan_model(ir)


def test_broken_json_and_wrong_suffix_fail_loudly(tmp_path: Path) -> None:
    broken = tmp_path / "kaputt.json"
    broken.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(QeaWriterError, match="kein gueltiges JSON"):
        qea_writer.load_ir(broken)
    with pytest.raises(QeaWriterError, match="Endung"):
        write_qea(load_fixture(), tmp_path / "modell.sqlite")


def test_ir_as_file_path_is_accepted(tmp_path: Path) -> None:
    path = write_qea(FIXTURE, tmp_path / "modell.qea")
    assert path.exists()
    assert sha256(path) == hashlib.sha256(render_bytes(load_fixture())).hexdigest()


def test_selftest_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "qea_writer.py"), "--selftest"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("OK:")
