"""Round-Trip-Tests: .qea -> IR -> .qea -> IR.

Ausschliesslich synthetische Daten (keine echten Modelle, keine Personendaten).
DoD: ``pytest tests/test_roundtrip.py`` gruen.

Die Tests decken drei Dinge ab:

1. Der Reader ist die exakte Umkehrung des Writers: das synthetische IR kommt
   nach ``write -> read`` byte-gleich als Dict zurueck.
2. Robustheit: fehlende optionale Spalten/Tabellen werden tolerant behandelt,
   strukturelle Schaeden brechen laut ab.
3. Semantische Gleichheit: bei vollstaendig identischen Duplikaten darf die
   Vorkommensnummer wechseln; ``semantic_view`` macht das sichtbar.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from qea_reader import (
    QeaReaderError,
    read_qea,
    read_qea_ex,
    render_json,
    semantic_equal,
    semantic_view,
)
from qea_writer import render_bytes, write_qea

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
FIXTURE = ROOT / "fixtures" / "ir_roundtrip_mini.json"


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build(tmp_path: Path, ir: dict, name: str = "modell.qea") -> Path:
    return write_qea(ir, tmp_path / name)


PACKAGE_DDL = (
    'CREATE TABLE t_package ("Package_ID" INTEGER PRIMARY KEY, "Name" TEXT, '
    '"Parent_ID" INTEGER, "Notes" TEXT, "ea_guid" TEXT, "TPos" INTEGER)'
)
OBJECT_DDL = (
    'CREATE TABLE t_object ("Object_ID" INTEGER PRIMARY KEY, "Object_Type" TEXT, '
    '"Name" TEXT, "Package_ID" INTEGER, "Stereotype" TEXT, "Note" TEXT, '
    '"Alias" TEXT, "Status" TEXT, "PDATA1" TEXT, "ea_guid" TEXT)'
)
CONNECTOR_DDL = (
    'CREATE TABLE t_connector ("Connector_ID" INTEGER PRIMARY KEY, "Name" TEXT, '
    '"Direction" TEXT, "Notes" TEXT, "Connector_Type" TEXT, "Stereotype" TEXT, '
    '"Start_Object_ID" INTEGER, "End_Object_ID" INTEGER)'
)
TAGS_DDL = (
    'CREATE TABLE t_objectproperties ("PropertyID" INTEGER PRIMARY KEY, '
    '"Object_ID" INTEGER, "Property" TEXT, "Value" TEXT)'
)
CONNTAGS_DDL = (
    'CREATE TABLE t_connectortag ("PropertyID" INTEGER PRIMARY KEY, '
    '"ElementID" INTEGER, "Property" TEXT, "VALUE" TEXT)'
)
XREF_DDL = (
    'CREATE TABLE t_xref ("XrefID" TEXT PRIMARY KEY, "Type" TEXT, '
    '"Description" TEXT, "Client" TEXT)'
)
DIAGRAM_DDL = (
    'CREATE TABLE t_diagram ("Diagram_ID" INTEGER PRIMARY KEY, "Name" TEXT)'
)


class QeaBuilder:
    """Baut eine minimale, synthetische .qea -- bewusst ohne EA-Komfortspalten."""

    def __init__(
        self,
        path: Path,
        *,
        package_ddl: str = PACKAGE_DDL,
        object_ddl: str = OBJECT_DDL,
        connector_ddl: str = CONNECTOR_DDL,
        tags: bool = True,
        connector_tags: bool = True,
        xref: bool = True,
        diagrams: bool = False,
    ) -> None:
        self.path = Path(path)
        self.con = sqlite3.connect(self.path)
        self.con.execute(package_ddl)
        self.con.execute(object_ddl)
        self.con.execute(connector_ddl)
        if tags:
            self.con.execute(TAGS_DDL)
        if connector_tags:
            self.con.execute(CONNTAGS_DDL)
        if xref:
            self.con.execute(XREF_DDL)
        if diagrams:
            self.con.execute(DIAGRAM_DDL)

    # -- Zeilen ---------------------------------------------------------
    def _insert(self, table: str, values: dict) -> None:
        """Nur vorhandene Spalten fuellen (Tests mit absichtlich schmalem Schema)."""
        columns = {row[1] for row in self.con.execute(f'PRAGMA table_info("{table}")')}
        keys = [key for key in values if key in columns]
        placeholders = ", ".join("?" for _ in keys)
        names = ", ".join(f'"{key}"' for key in keys)
        self.con.execute(
            f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
            [values[key] for key in keys],
        )

    def package(
        self,
        package_id: int,
        name: str,
        parent: int = 0,
        *,
        notes: str = "",
        guid: str | None = None,
        tpos: int = 0,
    ) -> "QeaBuilder":
        self._insert(
            "t_package",
            {
                "Package_ID": package_id,
                "Name": name,
                "Parent_ID": parent,
                "Notes": notes,
                "ea_guid": guid or f"{{PKG-{package_id}}}",
                "TPos": tpos,
            },
        )
        return self

    def obj(
        self,
        object_id: int,
        object_type: str,
        name: str,
        package_id: int,
        *,
        stereotype: str = "",
        note: str = "",
        alias: str = "",
        status: str = "",
        guid: str | None = None,
        pdata1: str | None = None,
    ) -> "QeaBuilder":
        self._insert(
            "t_object",
            {
                "Object_ID": object_id,
                "Object_Type": object_type,
                "Name": name,
                "Package_ID": package_id,
                "Stereotype": stereotype,
                "Note": note,
                "Alias": alias,
                "Status": status,
                "PDATA1": pdata1,
                "ea_guid": guid or f"{{OBJ-{object_id}}}",
            },
        )
        return self

    def mirror(
        self, object_id: int, package_id: int, name: str, parent_id: int = 0, **kwargs
    ) -> "QeaBuilder":
        return self.obj(
            object_id,
            "Package",
            name,
            parent_id,
            pdata1=str(package_id),
            **kwargs,
        )

    def connector(
        self,
        connector_id: int,
        start: int,
        end: int,
        *,
        name: str = "",
        direction: str = "Source -> Destination",
        connector_type: str = "Dependency",
        stereotype: str = "",
        notes: str = "",
    ) -> "QeaBuilder":
        self._insert(
            "t_connector",
            {
                "Connector_ID": connector_id,
                "Name": name,
                "Direction": direction,
                "Notes": notes,
                "Connector_Type": connector_type,
                "Stereotype": stereotype,
                "Start_Object_ID": start,
                "End_Object_ID": end,
            },
        )
        return self

    def object_tag(self, object_id: int, prop: str, value: str | None) -> "QeaBuilder":
        self._insert(
            "t_objectproperties",
            {"Object_ID": object_id, "Property": prop, "Value": value},
        )
        return self

    def connector_tag(self, connector_id: int, prop: str, value: str | None) -> "QeaBuilder":
        self._insert(
            "t_connectortag",
            {"ElementID": connector_id, "Property": prop, "VALUE": value},
        )
        return self

    def xref(self, client: str, stereotype: str, profile: str = "TestProfil") -> "QeaBuilder":
        description = (
            f"@STEREO;Name={stereotype};FQName={profile}::{stereotype};@ENDSTEREO;"
        )
        self._insert(
            "t_xref",
            {
                "XrefID": f"{{XREF-{client}-{stereotype}}}",
                "Type": "element property",
                "Description": description,
                "Client": client,
            },
        )
        return self

    def close(self) -> None:
        self.con.commit()
        self.con.close()

    def __enter__(self) -> "QeaBuilder":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


# --------------------------------------------------------------------------
# 1. DoD: read -> write -> read ist stabil
# --------------------------------------------------------------------------


def test_fixture_has_required_shape() -> None:
    ir = load_fixture()
    assert len(ir["packages"]) == 2
    assert len(ir["elements"]) == 5
    assert len(ir["connectors"]) == 4
    assert ir["diagrams"] == []
    assert "synthetisch" in FIXTURE.read_text(encoding="utf-8").lower()


def test_read_reproduces_source_ir_exactly(tmp_path: Path) -> None:
    ir = load_fixture()
    qea = build(tmp_path, ir)
    assert read_qea(qea) == ir


def test_read_write_read_is_stable_and_byte_identical(tmp_path: Path) -> None:
    first_ir = read_qea(build(tmp_path, load_fixture(), "erste.qea"))
    second_qea = build(tmp_path, first_ir, "zweite.qea")
    second_ir = read_qea(second_qea)

    assert first_ir == second_ir
    assert render_json(first_ir) == render_json(second_ir)
    assert render_bytes(first_ir) == second_qea.read_bytes()
    assert hashlib.sha256(render_bytes(second_ir)).digest() == hashlib.sha256(
        second_qea.read_bytes()
    ).digest()


def test_two_reads_produce_identical_json(tmp_path: Path) -> None:
    qea = build(tmp_path, load_fixture())
    assert render_json(read_qea(qea)) == render_json(read_qea(qea))


def test_report_counts_match_model(tmp_path: Path) -> None:
    qea = build(tmp_path, load_fixture())
    ir, report = read_qea_ex(qea)
    assert (report.packages, report.elements, report.connectors) == (2, 5, 4)
    assert report.element_tags == 5
    assert report.package_tags == 1
    assert report.connector_tags == 1
    assert report.diagrams == 0
    assert report.ignored_package_mirrors == 0
    assert report.technology_profile == "MiniProfil"
    assert report.warnings == ()
    assert ir["technology"] == {"profile": "MiniProfil"}


def test_package_endpoint_is_written_as_plain_path(tmp_path: Path) -> None:
    ir = read_qea(build(tmp_path, load_fixture()))
    package_edges = [c for c in ir["connectors"] if "::" not in c["source"]]
    assert len(package_edges) == 1
    assert package_edges[0]["source"] == "MiniModell/Elemente"


def test_package_stereotype_and_tags_survive(tmp_path: Path) -> None:
    ir = read_qea(build(tmp_path, load_fixture()))
    child = ir["packages"][1]
    assert child["path"] == "MiniModell/Elemente"
    assert child["stereotype"] == "ArchitecturalDescription"
    assert child["tags"] == {"Quelle": "synthetisch"}


def test_diagrams_are_counted_but_not_exported(tmp_path: Path) -> None:
    with QeaBuilder(tmp_path / "sichten.qea", diagrams=True) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.con.execute("INSERT INTO t_diagram VALUES (1, 'Sicht 1')")
        builder.con.execute("INSERT INTO t_diagram VALUES (2, 'Sicht 2')")
    ir, report = read_qea_ex(tmp_path / "sichten.qea")
    assert report.diagrams == 2
    assert ir["diagrams"] == []


# --------------------------------------------------------------------------
# 2. Mehrdeutige Namen: #N-Konvention des Writers
# --------------------------------------------------------------------------


def test_duplicate_element_names_keep_occurrence_numbers(tmp_path: Path) -> None:
    ir = {
        "ir_version": 1,
        "packages": [{"path": "P"}],
        "elements": [
            {"package": "P", "name": "X", "ea_type": "Class", "notes": "zwei"},
            {"package": "P", "name": "X", "ea_type": "Class", "notes": "eins"},
        ],
        "connectors": [
            {"source": "P::X#2", "target": "P::X#1", "ea_type": "Dependency"}
        ],
        "diagrams": [],
    }
    qea = build(tmp_path, ir)
    first = read_qea(qea)
    assert first["connectors"][0]["source"] == "P::X#2"
    assert first["connectors"][0]["target"] == "P::X#1"
    second = read_qea(build(tmp_path, first, "zweite.qea"))
    assert first == second


def test_duplicate_sibling_packages_keep_logical_paths(tmp_path: Path) -> None:
    ir = {
        "ir_version": 1,
        "packages": [
            {"path": "P"},
            {"path": "P/Views"},
            {"path": "P/Views#2", "name": "Views"},
        ],
        "elements": [
            {"package": "P/Views", "name": "E", "ea_type": "Class"},
            {"package": "P/Views#2", "name": "E", "ea_type": "Class"},
        ],
        "connectors": [
            {"source": "P/Views::E", "target": "P/Views#2::E", "ea_type": "Dependency"}
        ],
        "diagrams": [],
    }
    first = read_qea(build(tmp_path, ir))
    assert [p["path"] for p in first["packages"]] == ["P", "P/Views", "P/Views#2"]
    assert first["packages"][2]["name"] == "Views"
    assert first["connectors"][0]["target"] == "P/Views#2::E"
    assert first == read_qea(build(tmp_path, first, "zweite.qea"))


def test_unnamed_element_uses_position_reference(tmp_path: Path) -> None:
    ir = {
        "ir_version": 1,
        "packages": [{"path": "P"}],
        "elements": [
            {"package": "P", "name": "", "ea_type": "Note", "notes": "ohne Namen"},
            {"package": "P", "name": "A", "ea_type": "Class"},
        ],
        "connectors": [
            {"source": "P::A", "target": "P::#1", "ea_type": "NoteLink"}
        ],
        "diagrams": [],
    }
    first = read_qea(build(tmp_path, ir))
    assert first["elements"][0]["name"] == ""
    assert first["connectors"][0]["target"] == "P::#1"
    assert first == read_qea(build(tmp_path, first, "zweite.qea"))


def test_semantic_view_keeps_distinct_content_apart() -> None:
    ir = {
        "ir_version": 1,
        "packages": [{"path": "P"}],
        "elements": [
            {"package": "P", "name": "X", "ea_type": "Class", "notes": "eins"},
            {"package": "P", "name": "X", "ea_type": "Class", "notes": "zwei"},
        ],
        "connectors": [
            {"source": "P::X#1", "target": "P::X#2", "ea_type": "Dependency"}
        ],
        "diagrams": [],
    }
    swapped = json.loads(json.dumps(ir))
    swapped["connectors"][0]["source"] = "P::X#2"
    swapped["connectors"][0]["target"] = "P::X#1"
    assert not semantic_equal(ir, swapped)
    assert semantic_equal(ir, json.loads(json.dumps(ir)))


def test_identical_duplicates_are_semantically_stable(tmp_path: Path) -> None:
    elements = [{"package": "P", "name": "A", "ea_type": "Class"} for _ in range(3)]
    ir = {
        "ir_version": 1,
        "packages": [{"path": "P"}],
        "elements": elements,
        "connectors": [
            {"source": "P::A#1", "target": "P::A#2", "ea_type": "Dependency"},
            {"source": "P::A#2", "target": "P::A#3", "ea_type": "Dependency"},
            {"source": "P::A#3", "target": "P::A#1", "ea_type": "Dependency"},
        ],
        "diagrams": [],
    }
    first = read_qea(build(tmp_path, ir))
    second = read_qea(build(tmp_path, first, "zweite.qea"))
    assert len(first["connectors"]) == len(second["connectors"]) == 3
    assert semantic_equal(first, second)
    assert semantic_view(first) == semantic_view(second)


# --------------------------------------------------------------------------
# 3. Robustheit: fehlende Spalten und optionale Tabellen
# --------------------------------------------------------------------------


def test_missing_optional_columns_use_defaults(tmp_path: Path) -> None:
    path = tmp_path / "schmal.qea"
    with QeaBuilder(
        path,
        package_ddl='CREATE TABLE t_package ("Package_ID" INTEGER PRIMARY KEY, "Name" TEXT, "Parent_ID" INTEGER)',
        object_ddl='CREATE TABLE t_object ("Object_ID" INTEGER PRIMARY KEY, "Object_Type" TEXT, "Name" TEXT, "Package_ID" INTEGER)',
        connector_ddl='CREATE TABLE t_connector ("Connector_ID" INTEGER PRIMARY KEY, "Start_Object_ID" INTEGER, "End_Object_ID" INTEGER)',
        tags=False,
        connector_tags=False,
        xref=False,
    ) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.obj(2, "Port", "B", 1)
        builder.connector(1, 1, 2)

    ir, report = read_qea_ex(path)
    assert [p["path"] for p in ir["packages"]] == ["P"]
    assert ir["elements"][1] == {"package": "P", "name": "B", "ea_type": "Port"}
    assert ir["connectors"] == [
        {"source": "P::A", "target": "P::B", "ea_type": "Dependency"}
    ]
    assert "technology" not in ir
    assert any("t_objectproperties" in w for w in report.warnings)
    assert any("t_connectortag" in w for w in report.warnings)
    assert any("t_xref" in w for w in report.warnings)


def test_missing_optional_tables_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "ohne_tags.qea"
    with QeaBuilder(
        path, tags=False, connector_tags=False, xref=False
    ) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.connector(1, 1, 1)
    ir, report = read_qea_ex(path)
    assert "tags" not in ir["elements"][0]
    assert report.element_tags == 0
    assert report.connector_tags == 0
    assert len(report.warnings) == 3
    assert any("t_objectproperties" in warning for warning in report.warnings)
    assert any("t_connectortag" in warning for warning in report.warnings)
    assert any("t_xref" in warning for warning in report.warnings)


def test_missing_parent_column_treats_all_packages_as_roots(tmp_path: Path) -> None:
    path = tmp_path / "ohne_parent.qea"
    with QeaBuilder(
        path,
        package_ddl='CREATE TABLE t_package ("Package_ID" INTEGER PRIMARY KEY, "Name" TEXT)',
    ) as builder:
        builder.package(1, "A")
        builder.package(2, "B")
        builder.obj(1, "Class", "X", 1)
        builder.obj(2, "Class", "Y", 2)
        builder.connector(1, 1, 2)
    ir, report = read_qea_ex(path)
    assert [p["path"] for p in ir["packages"]] == ["A", "B"]
    assert any("Parent_ID" in warning for warning in report.warnings)


def test_missing_package_mirror_is_not_an_element(tmp_path: Path) -> None:
    path = tmp_path / "ohne_spiegel.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.package(2, "Q", 1)
        builder.obj(1, "Class", "A", 2)
        builder.connector(1, 1, 1)
    ir, report = read_qea_ex(path)
    assert report.elements == 1
    assert [p["path"] for p in ir["packages"]] == ["P", "P/Q"]


def test_package_tags_on_mirror_go_to_package(tmp_path: Path) -> None:
    path = tmp_path / "spiegel_tags.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.package(2, "Q", 1)
        builder.mirror(10, 2, "Q", parent_id=1)
        builder.obj(1, "Class", "A", 2)
        builder.object_tag(10, "Quelle", "synthetisch")
        builder.connector(1, 1, 1)
    ir, report = read_qea_ex(path)
    assert ir["packages"][1]["tags"] == {"Quelle": "synthetisch"}
    assert report.package_tags == 1
    assert report.element_tags == 0


def test_null_tag_value_becomes_empty_string(tmp_path: Path) -> None:
    path = tmp_path / "null_tag.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.object_tag(1, "URI", None)
        builder.connector(1, 1, 1)
    ir = read_qea(path)
    assert ir["elements"][0]["tags"] == {"URI": ""}


# --------------------------------------------------------------------------
# 4. Laute Fehler (nie stiller Teil-Erfolg)
# --------------------------------------------------------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(QeaReaderError, match="existiert nicht"):
        read_qea(tmp_path / "gibt_es_nicht.qea")


def test_non_sqlite_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "kein_qea.qea"
    path.write_text("das ist keine Datenbank", encoding="utf-8")
    with pytest.raises(QeaReaderError):
        read_qea(path)


def test_missing_required_table_raises(tmp_path: Path) -> None:
    path = tmp_path / "ohne_objekte.qea"
    con = sqlite3.connect(path)
    con.execute(PACKAGE_DDL)
    con.execute("INSERT INTO t_package VALUES (1, 'P', 0, '', '{P}', 0)")
    con.commit()
    con.close()
    with pytest.raises(QeaReaderError, match="t_object"):
        read_qea(path)


def test_dangling_connector_raises(tmp_path: Path) -> None:
    path = tmp_path / "haengende_kante.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.connector(1, 1, 99)
    with pytest.raises(QeaReaderError, match="haengender Verweis"):
        read_qea(path)


def test_model_without_elements_raises_by_default(tmp_path: Path) -> None:
    path = tmp_path / "leer.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
    with pytest.raises(QeaReaderError, match="kein Element"):
        read_qea(path)
    ir, report = read_qea_ex(path, allow_empty=True)
    assert ir["elements"] == []
    assert report.elements == 0


def test_conflicting_tag_values_raise(tmp_path: Path) -> None:
    path = tmp_path / "tag_konflikt.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.object_tag(1, "Status", "alt")
        builder.object_tag(1, "Status", "neu")
        builder.connector(1, 1, 1)
    with pytest.raises(QeaReaderError, match="widerspruechliche Werte"):
        read_qea(path)


def test_identical_duplicate_tags_collapse(tmp_path: Path) -> None:
    path = tmp_path / "tag_doppelt.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.object_tag(1, "Status", "gleich")
        builder.object_tag(1, "Status", "gleich")
        builder.connector(1, 1, 1)
    ir, report = read_qea_ex(path)
    assert ir["elements"][0]["tags"] == {"Status": "gleich"}
    assert report.element_tags == 1


def test_element_name_with_reference_separator_raises(tmp_path: Path) -> None:
    path = tmp_path / "name_mit_doppelpunkt.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A::B", 1)
        builder.connector(1, 1, 1)
    with pytest.raises(QeaReaderError, match="::"):
        read_qea(path)


def test_package_name_with_path_separator_raises(tmp_path: Path) -> None:
    path = tmp_path / "paket_mit_slash.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "A/B")
        builder.obj(1, "Class", "X", 1)
        builder.connector(1, 1, 1)
    with pytest.raises(QeaReaderError, match="nicht darstellbar"):
        read_qea(path)


def test_orphan_package_mirror_is_reported_not_silent(tmp_path: Path) -> None:
    path = tmp_path / "waise.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.obj(99, "Package", "Waise", 1, pdata1="", guid="{WAISE-99}")
        builder.connector(1, 1, 1)
    ir, report = read_qea_ex(path)
    assert report.ignored_package_mirrors == 1
    assert report.elements == 1
    assert any("Paketspiegel" in warning for warning in report.warnings)
    with pytest.raises(QeaReaderError, match="strikter Modus"):
        read_qea(path, strict=True)


def test_package_mirror_with_tags_but_no_package_raises(tmp_path: Path) -> None:
    path = tmp_path / "waise_mit_tags.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.obj(99, "Package", "Waise", 1, pdata1="", guid="{WAISE-99}")
        builder.object_tag(99, "Quelle", "synthetisch")
        builder.connector(1, 1, 1)
    with pytest.raises(QeaReaderError, match="keinem darstellbaren Paket"):
        read_qea(path)


def test_root_package_tag_without_mirror_raises(tmp_path: Path) -> None:
    path = tmp_path / "wurzel_tag.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "A", 1)
        builder.object_tag(42, "Quelle", "synthetisch")
        builder.connector(1, 1, 1)
    with pytest.raises(QeaReaderError, match="unbekannte Object_IDs"):
        read_qea(path)


def test_dangling_package_parent_raises(tmp_path: Path) -> None:
    path = tmp_path / "eltern_fehlt.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P", parent=99)
        builder.obj(1, "Class", "A", 1)
        builder.connector(1, 1, 1)
    with pytest.raises(QeaReaderError, match="Parent_ID"):
        read_qea(path)


def test_reference_number_shadowing_raises(tmp_path: Path) -> None:
    path = tmp_path / "ref_kollision.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Class", "X", 1, note="eins")
        builder.obj(2, "Class", "X", 1, note="zwei")
        builder.obj(3, "Class", "X#2", 1)
        builder.connector(1, 1, 2)
    with pytest.raises(QeaReaderError, match="kollidiert"):
        read_qea(path)


def test_unnamed_reference_shadowing_raises(tmp_path: Path) -> None:
    path = tmp_path / "ref_kollision_leer.qea"
    with QeaBuilder(path) as builder:
        builder.package(1, "P")
        builder.obj(1, "Note", "", 1)
        builder.obj(2, "Class", "#1", 1)
        builder.connector(1, 2, 2)
    with pytest.raises(QeaReaderError, match="kollidiert"):
        read_qea(path)


def test_reader_does_not_modify_source(tmp_path: Path) -> None:
    qea = build(tmp_path, load_fixture())
    before = (qea.stat().st_mtime_ns, hashlib.sha256(qea.read_bytes()).hexdigest())
    read_qea(qea)
    after = (qea.stat().st_mtime_ns, hashlib.sha256(qea.read_bytes()).hexdigest())
    assert before == after
