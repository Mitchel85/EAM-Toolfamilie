"""AAroN-Kompatibilitaet: alle 15 Pflichttabellen stehen in der .qea.

Beleg statt Vermutung
---------------------
``AAroN-Core/src/main/java/aaron/sparx/SparxSQLiteConverter.java`` ruft in
``convert()`` achtzehn ``handleTable(...)``-Aufrufe nacheinander ab, jeder mit
einem ``SELECT * FROM <Tabelle> ORDER BY ...``. ``handleTable()`` in
``AbstractSparxConverter`` faengt die ``SQLException`` einer fehlenden Tabelle
nicht ab -- der Import bricht ab, bevor das erste Modell entsteht.

Daraus folgt fuer den Writer:

* alle 15 Pflichttabellen anlegen, auch leer (0 Zeilen),
* ``usys_system`` mit Spalte ``Property`` (erste Abfrage: ``ORDER BY
  "Property"``),
* ``t_diagramobjects``/``t_diagramlinks`` vorhanden, aber leer -- keine
  Sichten, kein Layout (Kartenentscheidung),
* keine Sichten: die Tabellen existieren nur.

Und fuer den Reader: fehlende Tabellen bleiben tolerant (aeltere Dateien,
Fremdwerkzeuge). Beides wird hier geprueft.

Definition of Done: ``pytest tests/test_aaron_compat.py`` gruen.
Hart: Python 3.11+, stdlib + sqlite3, deterministisch, keine Sichten.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
from pathlib import Path

import pytest

from qea_reader import read_qea, semantic_equal
from qea_writer import (
    AARON_READ_TABLES,
    AARON_REQUIRED_TABLES,
    SYSTEM_SCHEMA_VERSION,
    plan_model,
    project_guid,
    render_bytes,
    write_qea,
)

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
FIXTURE = ROOT / "fixtures" / "ir_synthetic_mini.json"

#: Echte, von Sparx EA geschriebene Referenz (gitignored). Wenn sie lokal liegt,
#: wird das Spaltenschema gegen sie geprueft; sonst entfaellt nur dieser Test.
EA_REFERENCE = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"

#: Die neun Tabellen, die dieser Auftrag ergaenzt -- Spalten = Spalten von EA.
NEW_TABLES: tuple[str, ...] = (
    "usys_system",
    "t_attribute",
    "t_attributetag",
    "t_attributeconstraints",
    "t_operation",
    "t_operationtag",
    "t_connectorconstraint",
    "t_diagramobjects",
    "t_diagramlinks",
)

#: Tabellen, die leer bleiben: Layout/Sichten und Attribute/Operationen sind
#: nicht Teil von ir_version 1.
EMPTY_TABLES: tuple[str, ...] = (
    "t_diagram",
    "t_diagramobjects",
    "t_diagramlinks",
    "t_attribute",
    "t_attributetag",
    "t_attributeconstraints",
    "t_operation",
    "t_operationtag",
    "t_connectorconstraint",
)

#: Die achtzehn Abfragen aus ``SparxSQLiteConverter.convert()`` -- 1:1, gleiche
#: Reihenfolge, gleiches ``ORDER BY``. ``t_operation`` und
#: ``t_attributeconstraints`` kommen zweimal vor (Operation/Parameter bzw.
#: Objekt-/Attribut-Constraints), ``t_xref`` liest AAroN zusaetzlich.
AARON_QUERIES: tuple[tuple[str, str], ...] = (
    ("usys_system", 'SELECT * FROM usys_system ORDER BY "Property"'),
    ("t_package", "SELECT * FROM t_package ORDER BY Package_ID"),
    ("t_diagram", "SELECT * FROM t_diagram ORDER BY Diagram_ID"),
    ("t_object", "SELECT * FROM t_object ORDER BY Object_ID"),
    ("t_objectproperties", "SELECT * FROM t_objectproperties ORDER BY PropertyID"),
    (
        "t_attributeconstraints",
        'SELECT * FROM t_attributeconstraints ORDER BY Object_ID, "Constraint"',
    ),
    ("t_connector", "SELECT * FROM t_connector ORDER BY Connector_ID"),
    ("t_connectortag", "SELECT * FROM t_connectortag ORDER BY PropertyID"),
    (
        "t_connectorconstraint",
        'SELECT * FROM t_connectorconstraint ORDER BY ConnectorID, "Constraint"',
    ),
    ("t_diagramobjects", "SELECT * FROM t_diagramobjects ORDER BY Diagram_ID, Object_ID"),
    ("t_diagramlinks", "SELECT * FROM t_diagramlinks ORDER BY DiagramID, ConnectorID"),
    ("t_operation", "SELECT * FROM t_operation ORDER BY OperationID"),
    ("t_operationtag", "SELECT * FROM t_operationtag ORDER BY PropertyID"),
    # EAOperationParams: Parameterzeilen liegen ebenfalls in t_operation.
    ("t_operation", "SELECT * FROM t_operation ORDER BY OperationID, Name"),
    ("t_attribute", "SELECT * FROM t_attribute ORDER BY ID"),
    ("t_attributetag", "SELECT * FROM t_attributetag ORDER BY PropertyID"),
    (
        "t_attributeconstraints",
        'SELECT * FROM t_attributeconstraints ORDER BY ID, Object_ID, "Constraint"',
    ),
    ("t_xref", "SELECT * FROM t_xref ORDER BY XrefID"),
)

#: Spalten, die AAroN aus den neun neuen Tabellen liest (Column-Konstanten aus
#: ``AAroN-Core/src/main/java/aaron/sparx/model/*.java``).
AARON_COLUMNS: dict[str, tuple[str, ...]] = {
    "usys_system": ("Property", "Value"),
    "t_attribute": (
        "Object_ID", "Name", "Scope", "Stereotype", "Containment", "IsStatic",
        "IsCollection", "IsOrdered", "AllowDuplicates", "LowerBound", "UpperBound",
        "Container", "Notes", "Derived", "ID", "Pos", "GenOption", "Length", "Precision",
        "Scale", "Const", "Style", "Classifier", "Default", "Type", "ea_guid", "StyleEx",
    ),
    "t_attributetag": ("PropertyID", "ElementID", "Property", "VALUE", "NOTES", "ea_guid"),
    "t_attributeconstraints": (
        "Object_ID", "Constraint", "AttName", "Type", "Notes", "ID", "ConstraintType",
        "Weight", "Status",
    ),
    "t_operation": (
        "OperationID", "Object_ID", "Name", "Scope", "Type", "ReturnArray", "Stereotype",
        "IsStatic", "Concurrency", "Notes", "Behaviour", "Abstract", "GenOption",
        "Synchronized", "Pos", "Const", "Style", "Pure", "Throws", "Classifier", "Code",
        "IsRoot", "IsLeaf", "IsQuery", "StateFlags", "ea_guid", "StyleEx", "Default", "Kind",
    ),
    "t_operationtag": ("PropertyID", "ElementID", "Property", "VALUE", "NOTES", "ea_guid"),
    "t_connectorconstraint": ("ConnectorID", "Constraint", "ConstraintType", "Notes"),
    "t_diagramobjects": (
        "Diagram_ID", "Object_ID", "RectTop", "RectLeft", "RectRight", "RectBottom",
        "Sequence", "ObjectStyle", "Instance_ID",
    ),
    "t_diagramlinks": (
        "DiagramID", "ConnectorID", "Geometry", "Style", "Hidden", "Path", "Instance_ID",
    ),
}

#: Spalten, die AAroN liest, die EA in keiner geprueften Datei schreibt
#: (Schemaversion 4.01). ``Column.value()`` liefert dort ``null``; das ist kein
#: Fehlerfall, deshalb sind es bewusste Ausnahmen statt Schemaerweiterungen.
AAroN_ONLY_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("t_attributeconstraints", "ConstraintType"),
        ("t_attributeconstraints", "Status"),
        ("t_attributeconstraints", "Weight"),
        ("t_operation", "Default"),
        ("t_operation", "Kind"),
    }
)

#: EA-GUID-Form: {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
GUID_PATTERN = re.compile(r"^\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$")


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def load_ir() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build(tmp_path: Path, name: str = "modell.qea") -> Path:
    return write_qea(load_ir(), tmp_path / name)


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def table_info(con: sqlite3.Connection, table: str) -> list[tuple]:
    """Spaltenschema wie SQLite es meldet: Name, Typ, NOT NULL, Default, PK."""
    return [
        (row[1], row[2].upper(), row[3], row[4], row[5])
        for row in con.execute(f'PRAGMA table_info("{table}")')
    ]


def column_names(con: sqlite3.Connection, table: str) -> set[str]:
    return {name.lower() for name, *_rest in table_info(con, table)}


class AaronRow(dict):
    """Eine Zeile, wie AAroN sie sieht.

    ``readResultSet()`` legt die Spaltennamen klein ab; ``Column.value(map)``
    liest mit ``map.get(name.toLowerCase())``. Eine fehlende Spalte ergibt
    ``null`` -- und *keine* Ausnahme. Genau darum duerfen Spalten fehlen,
    Tabellen aber nicht.
    """

    def value(self, column: str) -> object:
        return self.get(column.lower())


def read_like_aaron(con: sqlite3.Connection, sql: str, chunk_size: int = 1000) -> list[AaronRow]:
    """Bildet ``handleTable()`` nach: LIMIT/OFFSET, Spalten klein, Chunks."""
    rows: list[AaronRow] = []
    offset = 0
    while True:
        cursor = con.execute(f"{sql} LIMIT {chunk_size} OFFSET {offset}")
        columns = [description[0].lower() for description in cursor.description]
        chunk = [AaronRow(zip(columns, values)) for values in cursor.fetchall()]
        if not chunk:
            return rows
        rows.extend(chunk)
        if len(chunk) < chunk_size:
            return rows
        offset += len(chunk)


def run_aaron_converter(path: Path) -> list[tuple[str, list[AaronRow]]]:
    """Fuehrt alle achtzehn Abfragen aus -- in der Reihenfolge von AAroN."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [(table, read_like_aaron(con, sql)) for table, sql in AARON_QUERIES]
    finally:
        con.close()


def order_by_columns(sql: str) -> list[str]:
    """Spalten aus ``ORDER BY`` -- fehlt eine, scheitert die Abfrage wirklich."""
    tail = sql.split("ORDER BY", 1)[-1]
    return [part.strip().strip('"') for part in tail.split(",") if part.strip()]


# --------------------------------------------------------------------------
# 1. Alle 15 Pflichttabellen: COUNT(*) ohne Ausnahme
# --------------------------------------------------------------------------


def test_pflichtliste_hat_genau_15_tabellen() -> None:
    assert len(AARON_REQUIRED_TABLES) == 15
    assert len(set(AARON_REQUIRED_TABLES)) == 15
    assert set(NEW_TABLES) <= set(AARON_REQUIRED_TABLES)


def test_alle_15_pflichttabellen_sind_zaehlbar(tmp_path: Path) -> None:
    path = build(tmp_path)
    con = connect(path)
    try:
        kinds = {row["name"]: row["type"] for row in con.execute("SELECT name, type FROM sqlite_master")}
        for table in AARON_REQUIRED_TABLES:
            assert table in kinds, f"AAroN-Pflichttabelle {table!r} fehlt in der .qea"
            assert kinds[table] == "table", f"{table} ist {kinds[table]!r}, keine Tabelle"
            count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert isinstance(count, int) and count >= 0
    finally:
        con.close()


def test_tabellen_sind_leer_wo_das_ir_nichts_hat(tmp_path: Path) -> None:
    path = build(tmp_path)
    con = connect(path)
    try:
        for table in EMPTY_TABLES:
            count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert count == 0, f"{table} soll leer bleiben, hat {count} Zeilen"
    finally:
        con.close()


def test_keine_sichten(tmp_path: Path) -> None:
    path = build(tmp_path)
    con = connect(path)
    try:
        views = [row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'view'")]
        assert views == [], f"Sichten sind bewusst ausgeschlossen, gefunden: {views}"
    finally:
        con.close()


# --------------------------------------------------------------------------
# 2. usys_system: Spalte Property und Projektkennung
# --------------------------------------------------------------------------


def test_usys_system_hat_spalte_property(tmp_path: Path) -> None:
    path = build(tmp_path)
    con = connect(path)
    try:
        schema = {
            name.lower(): (typ, not_null, pk)
            for name, typ, not_null, _default, pk in table_info(con, "usys_system")
        }
        assert "property" in schema, f"usys_system ohne Spalte Property: {sorted(schema)}"
        typ, not_null, pk = schema["property"]
        assert typ == "TEXT"
        assert not_null == 1, "Property ist in EA NOT NULL"
        assert pk == 1, "Property ist in EA der Primaerschluessel"
        # Erste Abfrage von AAroN -- inklusive ORDER BY "Property".
        rows = con.execute('SELECT "Property", "Value" FROM usys_system ORDER BY "Property"').fetchall()
    finally:
        con.close()

    values = {row["Property"]: row["Value"] for row in rows}
    assert "ProjectGUID" in values, "ohne ProjectGUID baut AAroN keinen Projektknoten"
    assert GUID_PATTERN.match(values["ProjectGUID"]), values["ProjectGUID"]
    assert values["Version"] == SYSTEM_SCHEMA_VERSION


def test_projektkennung_ist_deterministisch(tmp_path: Path) -> None:
    ir = load_ir()
    first = project_guid(plan_model(ir))
    second = project_guid(plan_model(copy.deepcopy(ir)))
    assert first == second
    assert GUID_PATTERN.match(first)

    # Anderer Paketbaum -> andere Kennung (keine Zufalls-GUID, aber eindeutig).
    changed = copy.deepcopy(ir)
    changed["packages"].append({"path": "Beispielmodell/Zusatz"})
    assert project_guid(plan_model(changed)) != first

    # Zwei Builds desselben IR bleiben byte-identisch.
    assert render_bytes(ir) == render_bytes(copy.deepcopy(ir))


# --------------------------------------------------------------------------
# 3. Mini-Converter: die achtzehn AAroN-Abfragen laufen durch
# --------------------------------------------------------------------------


def test_mini_converter_liest_alle_tabellen_ohne_exception(tmp_path: Path) -> None:
    path = build(tmp_path)
    results = run_aaron_converter(path)

    assert len(results) == len(AARON_QUERIES) == 18
    assert {table for table, _rows in results} == set(AARON_READ_TABLES)

    # Spalten, die AAroN aus den neuen Tabellen liest: vorhanden oder bewusst
    # nur bei AAroN (EA schreibt sie nicht) -- nie ein Fehler.
    con = connect(path)
    try:
        present_per_table = {table: column_names(con, table) for table in AARON_READ_TABLES}
    finally:
        con.close()

    for table, rows in results:
        present = present_per_table[table]
        for column in AARON_COLUMNS.get(table, ()):
            if (table, column) in AAroN_ONLY_COLUMNS:
                assert column.lower() not in present, (
                    f"{table}.{column} steht auf der Ausnahmeliste, ist aber vorhanden -- "
                    "Liste und Schema auseinandergelaufen"
                )
            else:
                assert column.lower() in present, f"AAroN liest {table}.{column}, Spalte fehlt"
        for row in rows:
            for column in AARON_COLUMNS.get(table, ()):
                row.value(column)  # Column.value(): nie eine Ausnahme


def test_order_by_spalten_existieren(tmp_path: Path) -> None:
    """Fehlt eine ORDER-BY-Spalte, wirft schon das SELECT -- der haerteste Fall."""
    path = build(tmp_path)
    con = connect(path)
    try:
        for table, sql in AARON_QUERIES:
            present = column_names(con, table)
            for column in order_by_columns(sql):
                assert column.lower() in present, (
                    f"{table}: ORDER BY {column!r} aus AAroN -- Spalte fehlt, "
                    "die Abfrage wuerde scheitern"
                )
    finally:
        con.close()


def test_mini_converter_liest_die_echten_zeilen(tmp_path: Path) -> None:
    """Kein Leerlauf: der Mini-Converter sieht dieselben Zahlen wie der Writer."""
    path = build(tmp_path)
    counts: dict[str, int] = {}
    for table, rows in run_aaron_converter(path):
        counts[table] = counts.get(table, 0) + len(rows)

    assert counts["t_package"] == 3
    assert counts["t_object"] == 7  # 3 Pakete - Wurzel = 2 Spiegel + 5 Elemente
    assert counts["t_connector"] == 4
    assert counts["t_objectproperties"] == 6
    assert counts["t_connectortag"] == 1
    assert counts["t_xref"] == 10
    assert counts["usys_system"] == 2
    # t_attributeconstraints und t_operation werden zweimal gelesen (0 Zeilen).
    assert counts["t_attributeconstraints"] == 0
    assert counts["t_operation"] == 0


def test_fehlende_spalte_liefert_none_statt_exception() -> None:
    """Das Verhalten, auf dem die Ausnahmeliste beruht (AAroN ``Column.value``)."""
    row = AaronRow({"name": "Wert"})
    assert row.value("Name") == "Wert"
    assert row.value("Kind") is None
    assert row.value("gibt_es_nicht") is None


# --------------------------------------------------------------------------
# 4. Schema = Spalten von EA
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not EA_REFERENCE.is_file(),
    reason="echte EA-Referenz (.qea) liegt lokal nicht vor",
)
def test_spalten_der_neuen_tabellen_sind_das_ea_schema(tmp_path: Path) -> None:
    """Spalten, Typen, NOT NULL, Defaults und PK gegen eine echte EA-Datei."""
    path = build(tmp_path)
    built = connect(path)
    reference = sqlite3.connect(f"file:{EA_REFERENCE}?mode=ro", uri=True)
    try:
        for table in NEW_TABLES:
            assert table_info(built, table) == [
                (row[1], row[2].upper(), row[3], row[4], row[5])
                for row in reference.execute(f'PRAGMA table_info("{table}")')
            ], f"{table}: Spaltenschema weicht von EA ab"
    finally:
        built.close()
        reference.close()


def test_neue_tabellen_haben_primaerschluessel(tmp_path: Path) -> None:
    """Ohne PK legt SQLite Zeilen doppelt an; EA-Dateien haben einen."""
    path = build(tmp_path)
    con = connect(path)
    try:
        for table in ("usys_system", "t_attribute", "t_attributetag", "t_operation",
                      "t_operationtag", "t_diagramobjects", "t_diagramlinks"):
            primary = [row[0] for row in table_info(con, table) if row[4]]
            assert primary, f"{table} hat keinen Primaerschluessel"
    finally:
        con.close()


# --------------------------------------------------------------------------
# 5. Reader bleibt tolerant
# --------------------------------------------------------------------------


def test_reader_liest_die_neue_datei_unveraendert(tmp_path: Path) -> None:
    """Die zusaetzlichen Tabellen duerfen das Lesen nicht veraendern."""
    path = build(tmp_path)
    expected = load_ir()
    reread = read_qea(path)
    assert len(reread["packages"]) == 3
    assert len(reread["elements"]) == 5
    assert len(reread["connectors"]) == 4
    assert semantic_equal(reread, expected) is True


def test_reader_toleriert_fehlende_tabellen(tmp_path: Path) -> None:
    """Aeltere/Fremd-Dateien: fehlende optionale Tabellen sind Warnungen, keine Fehler."""
    path = build(tmp_path)
    con = sqlite3.connect(path)
    try:
        for table in AARON_READ_TABLES:
            if table in ("t_package", "t_object", "t_connector"):
                continue  # strukturell notwendig -- ohne sie gibt es kein Modell
            con.execute(f'DROP TABLE "{table}"')
        con.commit()
    finally:
        con.close()

    ir = read_qea(path)
    assert len(ir["packages"]) == 3
    assert len(ir["elements"]) == 5
    assert len(ir["connectors"]) == 4
