"""Tests fuer ``model_edit.py``.

Die Mini-.qea entstehen mit ``qea_writer`` (schemakonform, 15 Pflichttabellen)
und festen ``guid``-Werten; ein Attribut samt Tag und eine ``@PROP``-Zeile in
``t_xref`` ergaenzt eine kurze sqlite-Nachbearbeitung. Damit sind alle Ziele
im Test ohne Nachrechnen adressierbar.

Geprueft wird: jede erlaubte Operation, die Adressierung per GUID **und** per
Paketpfad+Name, Ablehnungen (unbekannte Operation, unbekanntes Ziel, mehrdeutiger
Name), die MDG-Pruefung (unzulaessiger Stereotyp und verletzte Endpunktregel
werden abgelehnt, nicht geschrieben), Unveraendertheit des Originals,
Determinismus, ``integrity_check`` und die CLI-Exit-Codes. Ein Test prueft das
Journal direkt: eine geloeschte Elementzeile wird exakt wiederhergestellt.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import model_edit as me
import qea_reader
import qea_writer

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
#: Kleines, schnelles MDG mit Capability/Process/ServiceSpecification und
#: drei Konnektor-Regeln -- Beleg fuer die Regelpruefung.
MDG = ROOT / "examples" / "offline" / "mdg_admbw_auszug.xml"

P_MAIN = "{11110000-0000-0000-0000-000000000001}"
P_SUB = "{11110000-0000-0000-0000-000000000002}"
E_A = "{22220000-0000-0000-0000-000000000001}"
E_B = "{22220000-0000-0000-0000-000000000002}"
E_C = "{22220000-0000-0000-0000-000000000003}"
C_AB = "{33330000-0000-0000-0000-000000000001}"


def _write(path: Path, packages, elements, connectors=()) -> Path:
    """Schemakonforme .qea ueber den Writer erzeugen."""
    ir = {
        "ir_version": 1,
        "technology": {"profile": "Testprofil"},
        "packages": list(packages),
        "elements": list(elements),
        "connectors": list(connectors),
        "diagrams": [],
    }
    return qea_writer.write_qea(ir, path)


def _sql(path: Path, *statements: tuple[str, tuple]) -> None:
    con = sqlite3.connect(path)
    try:
        for sql, params in statements:
            con.execute(sql, params)
        con.commit()
    finally:
        con.close()


def _rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _value(path: Path, column: str, name: str) -> str:
    rows = _rows(
        path,
        f'SELECT {column} FROM t_object WHERE Name = ? AND Object_Type <> "Package"',
        (name,),
    )
    assert len(rows) == 1, f"Element {name!r} nicht eindeutig"
    return rows[0][0]


def _tags(path: Path, name: str) -> dict[str, str]:
    return dict(
        _rows(
            path,
            "SELECT Property, Value FROM t_objectproperties WHERE Object_ID ="
            ' (SELECT Object_ID FROM t_object WHERE Name = ? AND Object_Type <> "Package")',
            (name,),
        )
    )


@pytest.fixture()
def modell(tmp_path: Path) -> Path:
    """Drei Elemente, eine Kante, ein Tag, ein Attribut und eine @PROP-Zeile."""
    path = _write(
        tmp_path / "modell.qea",
        [{"path": "P", "guid": P_MAIN}, {"path": "P/Q", "guid": P_SUB}],
        [
            {
                "package": "P",
                "name": "A",
                "ea_type": "Class",
                "stereotype": "Capability",
                "guid": E_A,
                "tags": {"Quelle": "intern"},
            },
            {
                "package": "P",
                "name": "B",
                "ea_type": "Class",
                "stereotype": "ServiceSpecification",
                "guid": E_B,
            },
            {
                "package": "P/Q",
                "name": "C",
                "ea_type": "Class",
                "stereotype": "Capability",
                "guid": E_C,
            },
        ],
        [
            {
                "source": "P::A",
                "target": "P::B",
                "stereotype": "Exhibits",
                "ea_type": "Dependency",
                "name": "a-nach-b",
                "guid": C_AB,
            }
        ],
    )
    _sql(
        path,
        (
            "INSERT INTO t_attribute (Object_ID, Name, Stereotype, Type, ID, ea_guid)"
            " SELECT Object_ID, 'attribut', '', 'String', 1,"
            " '{44440000-0000-0000-0000-000000000001}' FROM t_object WHERE ea_guid = ?",
            (E_A,),
        ),
        (
            "INSERT INTO t_attributetag (PropertyID, ElementID, Property, VALUE, ea_guid)"
            " VALUES (900, 1, 'einheit', 'm', '{44440000-0000-0000-0000-000000000002}')",
            (),
        ),
        (
            "INSERT INTO t_xref (XrefID, Name, Type, Description, Client)"
            " VALUES ('{55550000-0000-0000-0000-000000000001}', 'CustomProperties',"
            " 'element property',"
            " '@PROP=@NAME=Herkunft@ENDNAME;@TYPE=string@ENDTYPE;"
            "@VALU=Alt@ENDVALU;@PRMT=@ENDPRMEND;@ENDPROP;', ?)",
            (E_A,),
        ),
    )
    return path


def _edit(modell: Path, ops, tmp_path: Path, *, mdg: Path | None = None, name: str = "out.qea"):
    out = tmp_path / name
    result = me.edit_model(modell, ops, out, mdg=mdg)
    return out, result


# --------------------------------------------------------------------------
# Feldoperationen und Adressierung
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "column", "value"),
    [
        ("set_name", "Name", "A-neu"),
        ("set_note", "Note", "Eine Notiz"),
        ("set_status", "Status", "Proposed"),
        ("set_alias", "Alias", "Kurz"),
    ],
)
def test_feldoperationen_setzen_den_wert(
    modell: Path, tmp_path: Path, op: str, column: str, value: str
) -> None:
    out, result = _edit(modell, [{"op": op, "guid": E_A, "value": value}], tmp_path)

    assert result.applied == 1
    assert result.rejected == []
    assert _value(out, column, "A" if op != "set_name" else value) == value
    assert _value(modell, column, "A") != value or op == "set_status"


def test_ziel_per_paketpfad_und_name(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(
        modell, [{"op": "set_alias", "package": "P/Q", "name": "C", "value": "ueber-Pfad"}], tmp_path
    )
    assert result.applied == 1
    assert _value(out, "Alias", "C") == "ueber-Pfad"


def test_beide_adressierungsarten_treffen_dasselbe_element(modell: Path, tmp_path: Path) -> None:
    per_guid, _ = _edit(
        modell, [{"op": "set_alias", "guid": E_C, "value": "gleich"}], tmp_path, name="a.qea"
    )
    per_pfad, _ = _edit(
        modell, [{"op": "set_alias", "package": "P/Q", "name": "C", "value": "gleich"}],
        tmp_path,
        name="b.qea",
    )
    assert per_guid.read_bytes() == per_pfad.read_bytes()


def test_unbekannte_guid_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(
        modell,
        [
            {"op": "set_alias", "guid": "{99999999-9999-9999-9999-999999999999}", "value": "x"},
            {"op": "set_alias", "guid": E_A, "value": "ok"},
        ],
        tmp_path,
    )
    assert result.applied == 1
    assert len(result.rejected) == 1
    assert result.rejected[0]["op"] == 0
    assert result.rejected[0]["typ"] == "set_alias"
    assert "kein Element mit ea_guid" in result.rejected[0]["grund"]
    assert _value(out, "Alias", "A") == "ok"


def test_unbekanntes_paket_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(modell, [{"op": "set_alias", "package": "P/GibtsNicht", "name": "A", "value": "x"}], tmp_path)
    assert result.applied == 0
    assert "existiert nicht" in result.rejected[0]["grund"]


def test_mehrdeutiger_name_wird_abgelehnt(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "doppelt.qea",
        [{"path": "P", "guid": P_MAIN}],
        [
            {"package": "P", "name": "D", "ea_type": "Class", "guid": E_A},
            {"package": "P", "name": "D", "ea_type": "Class", "guid": E_B, "notes": "zweite"},
        ],
    )
    _, result = _edit(path, [{"op": "set_alias", "package": "P", "name": "D", "value": "x"}], tmp_path)
    assert result.applied == 0
    assert "nicht eindeutig" in result.rejected[0]["grund"]


def test_unbekannte_operation_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(modell, [{"op": "set_farbe", "guid": E_A, "value": "rot"}], tmp_path)
    assert result.applied == 0
    assert "unbekannte Operation" in result.rejected[0]["grund"]


def test_fehlendes_ziel_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(modell, [{"op": "set_alias", "value": "x"}], tmp_path)
    assert result.applied == 0
    assert "Ziel fehlt" in result.rejected[0]["grund"]


def test_fehlender_wert_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(modell, [{"op": "set_alias", "guid": E_A}], tmp_path)
    assert result.applied == 0
    assert "'value'" in result.rejected[0]["grund"]


def test_name_ohne_doppelpunkt_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(modell, [{"op": "set_name", "guid": E_A, "value": "P::A"}], tmp_path)
    assert result.applied == 0
    assert "'::'" in result.rejected[0]["grund"]


# --------------------------------------------------------------------------
# Stereotyp und Tagged Values
# --------------------------------------------------------------------------


def test_set_stereotype_schreibt_die_xref_zeile(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(modell, [{"op": "set_stereotype", "guid": E_A, "value": "Process"}], tmp_path)

    assert result.applied == 1
    assert _value(out, "Stereotype", "A") == "Process"
    descriptions = [
        row[0] for row in _rows(out, "SELECT Description FROM t_xref WHERE Client = ?", (E_A,))
    ]
    stereotype_rows = [text for text in descriptions if text.startswith("@STEREO;")]
    assert len(stereotype_rows) == 1, "die vorhandene @STEREO-Zeile wird aktualisiert, nicht verdoppelt"
    assert "Name=Process" in stereotype_rows[0]
    assert "FQName=Testprofil::Process" in stereotype_rows[0]
    assert qea_reader.read_qea(out)["elements"][0]["stereotype"] == "Process"


def test_leerer_stereotyp_entfernt_die_xref_zeile(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(modell, [{"op": "set_stereotype", "guid": E_A, "value": ""}], tmp_path)

    assert result.applied == 1
    assert _value(out, "Stereotype", "A") == ""
    descriptions = [
        row[0] for row in _rows(out, "SELECT Description FROM t_xref WHERE Client = ?", (E_A,))
    ]
    assert not [text for text in descriptions if text.startswith("@STEREO;")]
    assert any("@NAME=Herkunft" in text for text in descriptions), "CustomProperties bleiben"


def test_add_tag_legt_an_und_aktualisiert(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(
        modell,
        [
            {"op": "add_tag", "guid": E_A, "tag": "Kosten", "value": "100"},
            {"op": "add_tag", "guid": E_A, "tag": "Quelle", "value": "extern"},
        ],
        tmp_path,
    )
    assert result.applied == 2
    tags = _tags(out, "A")
    assert tags["Kosten"] == "100"
    assert tags["Quelle"] == "extern"
    assert len(_rows(out, "SELECT * FROM t_objectproperties")) == 2, "kein doppelter Tag"


def test_add_tag_synchronisiert_die_custom_property_zeile(modell: Path, tmp_path: Path) -> None:
    out, _ = _edit(modell, [{"op": "add_tag", "guid": E_A, "tag": "Herkunft", "value": "Neu"}], tmp_path)
    descriptions = [
        row[0] for row in _rows(out, "SELECT Description FROM t_xref WHERE Client = ?", (E_A,))
    ]
    herkunft = [text for text in descriptions if "@NAME=Herkunft" in text]
    assert len(herkunft) == 1
    assert "@VALU=Neu" in herkunft[0]


def test_remove_tag_entfernt_tag_und_xref(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(
        modell,
        [
            {"op": "remove_tag", "guid": E_A, "tag": "Quelle"},
            {"op": "remove_tag", "guid": E_A, "tag": "Herkunft"},
        ],
        tmp_path,
    )
    assert result.applied == 2
    assert _tags(out, "A") == {}
    assert not [
        text
        for (text,) in _rows(out, "SELECT Description FROM t_xref WHERE Client = ?", (E_A,))
        if "@NAME=Herkunft" in text
    ]


def test_remove_tag_ohne_tag_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(modell, [{"op": "remove_tag", "guid": E_A, "tag": "GibtsNicht"}], tmp_path)
    assert result.applied == 0
    assert "existiert nicht" in result.rejected[0]["grund"]


# --------------------------------------------------------------------------
# Elemente und Kanten
# --------------------------------------------------------------------------


def test_delete_element_entfernt_auch_kanten_tags_und_xrefs(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(modell, [{"op": "delete_element", "guid": E_A}], tmp_path)

    assert result.applied == 1
    assert [row[0] for row in _rows(out, "SELECT Name FROM t_object WHERE Object_Type <> 'Package'")] == ["B", "C"]
    assert _rows(out, "SELECT * FROM t_objectproperties") == []
    assert _rows(out, "SELECT * FROM t_attribute") == []
    assert _rows(out, "SELECT * FROM t_attributetag") == []
    assert _rows(out, "SELECT * FROM t_connector") == [], "Kante A -> B haengt an A"
    assert _rows(out, "SELECT * FROM t_xref WHERE Client = ?", (E_A,)) == []
    lesen = qea_reader.read_qea(out)
    assert {entry["name"] for entry in lesen["elements"]} == {"B", "C"}
    assert lesen["connectors"] == []


def test_delete_element_entfernt_eingebettete_objekte(tmp_path: Path) -> None:
    """Ein Port ohne seinen Traeger waere eine Waise -- er geht mit."""
    path = _write(
        tmp_path / "port.qea",
        [{"path": "P", "guid": P_MAIN}],
        [
            {"package": "P", "name": "A", "ea_type": "Class", "guid": E_A},
            {"package": "P", "name": "B", "ea_type": "Class", "guid": E_B},
        ],
    )
    _sql(
        path,
        (
            "INSERT INTO t_object (Object_Type, Name, Package_ID, ParentID, ea_guid)"
            " SELECT 'Port', 'p1', Package_ID, Object_ID,"
            " '{66660000-0000-0000-0000-000000000001}' FROM t_object WHERE ea_guid = ?",
            (E_A,),
        ),
    )
    out, result = _edit(path, [{"op": "delete_element", "guid": E_A}], tmp_path)

    assert result.applied == 1
    namen = [row[0] for row in _rows(out, "SELECT Name FROM t_object ORDER BY Object_ID")]
    assert namen == ["B"], "Port p1 haengt an A und wird mitgeloescht"
    assert "1 eingebetteten" in result.changes[0]


def test_delete_connector_entfernt_kante_und_sterne(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "k.qea",
        [{"path": "P", "guid": P_MAIN}],
        [
            {"package": "P", "name": "A", "ea_type": "Class", "guid": E_A},
            {"package": "P", "name": "B", "ea_type": "Class", "guid": E_B},
        ],
        [
            {
                "source": "P::A",
                "target": "P::B",
                "stereotype": "Dep",
                "ea_type": "Dependency",
                "guid": C_AB,
            }
        ],
    )
    out, result = _edit(path, [{"op": "delete_connector", "guid": C_AB}], tmp_path)
    assert result.applied == 1
    assert _rows(out, "SELECT * FROM t_connector") == []
    assert _rows(out, "SELECT * FROM t_xref WHERE Client = ?", (C_AB,)) == []


def test_delete_connector_unbekannt_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(
        modell, [{"op": "delete_connector", "guid": "{99999999-9999-9999-9999-999999999999}"}], tmp_path
    )
    assert result.applied == 0
    assert "keine Kante" in result.rejected[0]["grund"]


def test_add_connector_legt_kante_mit_stereotyp_an(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(
        modell,
        [
            {
                "op": "add_connector",
                "source": "P::A",
                "target": "P/Q::C",
                "stereotype": "CapabilityDependency",
                "ea_type": "Dependency",
                "name": "a-nach-c",
            }
        ],
        tmp_path,
    )
    assert result.applied == 1
    kanten = _rows(
        out,
        "SELECT Connector_ID, Start_Object_ID, End_Object_ID, Connector_Type, Stereotype, ea_guid"
        " FROM t_connector ORDER BY Connector_ID",
    )
    assert len(kanten) == 2
    neu = kanten[1]
    a_id = _rows(out, "SELECT Object_ID FROM t_object WHERE Name = 'A' AND Object_Type <> 'Package'")[0][0]
    c_id = _rows(out, "SELECT Object_ID FROM t_object WHERE Name = 'C' AND Object_Type <> 'Package'")[0][0]
    assert (neu[1], neu[2]) == (a_id, c_id)
    assert neu[3] == "Dependency"
    assert neu[4] == "CapabilityDependency"
    xrefs = _rows(out, "SELECT Description FROM t_xref WHERE Client = ?", (neu[5],))
    assert xrefs and "Name=CapabilityDependency" in xrefs[0][0]


def test_add_connector_mit_gleichen_endpunkten_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(
        modell, [{"op": "add_connector", "source": "P::A", "target": "P::A", "ea_type": "Dependency"}], tmp_path
    )
    assert result.applied == 0
    assert "dasselbe Element" in result.rejected[0]["grund"]


def test_add_connector_mit_unbekanntem_endpunkt_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(
        modell,
        [{"op": "add_connector", "source": "P::A", "target": "P/GibtsNicht::X", "ea_type": "Dependency"}],
        tmp_path,
    )
    assert result.applied == 0
    assert "existiert nicht" in result.rejected[0]["grund"]


def test_add_connector_ist_deterministisch(modell: Path, tmp_path: Path) -> None:
    ops = [{"op": "add_connector", "source": E_A, "target": E_C, "name": "neu"}]
    first, _ = _edit(modell, ops, tmp_path, name="a.qea")
    second, _ = _edit(modell, ops, tmp_path, name="b.qea")
    assert first.read_bytes() == second.read_bytes()


# --------------------------------------------------------------------------
# MDG-Pruefung
# --------------------------------------------------------------------------


@pytest.mark.skipif(not MDG.is_file(), reason="MDG-Belegdatei fehlt")
def test_mdg_unbekannter_stereotyp_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    # C haengt an keiner Kante: der Stereotypwechsel erzeugt keinen Folgefehler.
    out, result = _edit(
        modell,
        [
            {"op": "set_stereotype", "guid": E_C, "value": "GibtEsNicht"},
            {"op": "set_stereotype", "guid": E_C, "value": "Process"},
        ],
        tmp_path,
        mdg=MDG,
    )
    assert result.mdg == str(MDG)
    assert result.applied == 1
    assert len(result.rejected) == 1
    assert "MDG-Verstoss" in result.rejected[0]["grund"]
    assert "GibtEsNicht" in result.rejected[0]["grund"]
    assert _value(out, "Stereotype", "C") == "Process"


@pytest.mark.skipif(not MDG.is_file(), reason="MDG-Belegdatei fehlt")
def test_mdg_verletzte_endpunktregel_wird_abgelehnt(modell: Path, tmp_path: Path) -> None:
    """CapabilityDependency verlangt Capability -> Capability."""
    _, result = _edit(
        modell,
        [
            {
                "op": "add_connector",
                "source": "P::A",
                "target": "P::B",
                "stereotype": "CapabilityDependency",
                "ea_type": "Dependency",
            }
        ],
        tmp_path,
        mdg=MDG,
    )
    assert result.applied == 0
    assert "nicht erlaubt" in result.rejected[0]["grund"]


@pytest.mark.skipif(not MDG.is_file(), reason="MDG-Belegdatei fehlt")
def test_mdg_erlaubte_kante_wird_angelegt(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(
        modell,
        [
            {
                "op": "add_connector",
                "source": "P::A",
                "target": "P/Q::C",
                "stereotype": "CapabilityDependency",
                "ea_type": "Dependency",
            }
        ],
        tmp_path,
        mdg=MDG,
    )
    assert result.applied == 1
    assert len(_rows(out, "SELECT * FROM t_connector")) == 2


@pytest.mark.skipif(not MDG.is_file(), reason="MDG-Belegdatei fehlt")
def _dump(path: Path) -> dict[str, list[tuple]]:
    """Alle Inhalte, die eine Bearbeitung beruehren kann (ohne Dateikopf)."""
    names = (
        "t_object",
        "t_objectproperties",
        "t_xref",
        "t_attribute",
        "t_attributetag",
        "t_attributeconstraints",
        "t_connector",
        "t_connectortag",
        "t_connectorconstraint",
        "t_package",
    )
    inhalt = {name: _rows(path, f'SELECT * FROM "{name}" ORDER BY rowid') for name in names}
    inhalt["sqlite_sequence"] = _rows(path, "SELECT name, seq FROM sqlite_sequence ORDER BY name")
    return inhalt


def test_abgelehnte_operation_hinterlaesst_keine_spur(modell: Path, tmp_path: Path) -> None:
    """Mit und ohne abgelehnte Operation muss derselbe Inhalt entstehen."""
    ohne, _ = _edit(modell, [{"op": "set_note", "guid": E_A, "value": "ok"}], tmp_path, mdg=MDG, name="a.qea")
    mit, result = _edit(
        modell,
        [
            {"op": "set_note", "guid": E_A, "value": "ok"},
            {
                "op": "add_connector",
                "source": "P::A",
                "target": "P::B",
                "stereotype": "CapabilityDependency",
            },
        ],
        tmp_path,
        mdg=MDG,
        name="b.qea",
    )
    assert result.rejected, "die Kante muss abgelehnt werden"
    assert _dump(mit) == _dump(ohne), "eine abgelehnte Operation darf keine Zeile hinterlassen"


@pytest.mark.skipif(not MDG.is_file(), reason="MDG-Belegdatei fehlt")
def test_ohne_mdg_ist_dieselbe_aenderung_erlaubt(modell: Path, tmp_path: Path) -> None:
    _, result = _edit(
        modell, [{"op": "set_stereotype", "guid": E_A, "value": "GibtEsNicht"}], tmp_path
    )
    assert result.applied == 1
    assert result.rejected == []


@pytest.mark.skipif(not MDG.is_file(), reason="MDG-Belegdatei fehlt")
def test_letztes_element_kann_mit_mdg_geloescht_werden(tmp_path: Path) -> None:
    """Ein leeres Modell ist pruefbar; die Loeschung darf nicht daran scheitern."""
    path = _write(
        tmp_path / "einzel.qea",
        [{"path": "P", "guid": P_MAIN}],
        [{"package": "P", "name": "A", "ea_type": "Class", "stereotype": "Capability", "guid": E_A}],
    )
    out, result = _edit(path, [{"op": "delete_element", "guid": E_A}], tmp_path, mdg=MDG)

    assert result.applied == 1
    assert result.rejected == []
    assert _rows(out, "SELECT * FROM t_object WHERE Object_Type <> 'Package'") == []


# --------------------------------------------------------------------------
# Datei, Determinismus, Journal, CLI
# --------------------------------------------------------------------------


def test_original_bleibt_unberuehrt(modell: Path, tmp_path: Path) -> None:
    before = modell.read_bytes()
    out, _ = _edit(modell, [{"op": "set_alias", "guid": E_A, "value": "x"}], tmp_path)
    assert modell.read_bytes() == before
    assert out.read_bytes() != before


def test_out_darf_nicht_das_original_sein(modell: Path) -> None:
    with pytest.raises(me.EditError):
        me.edit_model(modell, [], modell)


def test_fehlendes_modell_ist_ein_fehler(tmp_path: Path) -> None:
    with pytest.raises(me.EditError):
        me.edit_model(tmp_path / "gibtsnicht.qea", [], tmp_path / "out.qea")


def test_leere_operationsliste_ergibt_eine_kopie(modell: Path, tmp_path: Path) -> None:
    out, result = _edit(modell, [], tmp_path)
    assert result.applied == 0
    assert out.read_bytes() == modell.read_bytes()


def test_integrity_check_und_lesbarkeit(modell: Path, tmp_path: Path) -> None:
    out, _ = _edit(modell, [{"op": "set_status", "guid": E_A, "value": "Approved"}], tmp_path)
    assert _rows(out, "PRAGMA integrity_check") == [("ok",)]
    ir = qea_reader.read_qea(out)
    assert {entry["name"] for entry in ir["elements"]} == {"A", "B", "C"}


def test_gleiche_operationen_ergeben_gleiche_bytes(modell: Path, tmp_path: Path) -> None:
    ops = [
        {"op": "set_stereotype", "guid": E_A, "value": "Process"},
        {"op": "add_tag", "guid": E_A, "tag": "Neu", "value": "1"},
        {"op": "add_connector", "source": "P::A", "target": "P/Q::C", "name": "neu"},
    ]
    first, _ = _edit(modell, ops, tmp_path, name="a.qea")
    second, _ = _edit(modell, ops, tmp_path, name="b.qea")
    assert first.read_bytes() == second.read_bytes()


def test_journal_stellt_geloeschtes_element_wieder_her(modell: Path, tmp_path: Path) -> None:
    """Die Ruecknahme einer Loeschung muss Zeile fuer Zeile exakt sein."""
    import shutil

    arbeitskopie = tmp_path / "kopie.qea"
    shutil.copyfile(modell, arbeitskopie)

    before = _dump(arbeitskopie)
    con = sqlite3.connect(arbeitskopie)
    con.row_factory = sqlite3.Row
    try:
        model = me._Model(con, arbeitskopie)
        editor = me._Editor(model)
        journal = me._Journal(con)
        editor.apply({"op": "delete_element", "guid": E_A}, 0, journal)
        con.commit()
        assert _dump(arbeitskopie)["t_object"] != before["t_object"], "Loeschung muss wirken"

        journal.restore()
        con.commit()
    finally:
        con.close()

    assert _dump(arbeitskopie) == before, "nach der Ruecknahme ist alles wie vorher"


def test_cli_exit_codes(modell: Path, tmp_path: Path, capsys) -> None:
    ops_datei = tmp_path / "ops.json"
    ops_datei.write_text(
        json.dumps([{"op": "set_alias", "guid": E_A, "value": "x"}]), encoding="utf-8"
    )
    out = tmp_path / "out.qea"
    assert me.main([str(modell), "--ops", str(ops_datei), "--out", str(out)]) == 0
    bericht = json.loads(capsys.readouterr().out)
    assert bericht["angewendet"] == 1
    assert bericht["operationen"] == 1

    ablehnend = tmp_path / "ablehnend.json"
    ablehnend.write_text(
        json.dumps([{"op": "set_alias", "guid": "{99999999-9999-9999-9999-999999999999}", "value": "x"}]),
        encoding="utf-8",
    )
    assert me.main([str(modell), "--ops", str(ablehnend), "--out", str(tmp_path / "out2.qea")]) == 1
    capsys.readouterr()

    assert me.main([str(modell), "--ops", str(tmp_path / "fehlt.json"), "--out", str(tmp_path / "out3.qea")]) == 2


def test_unterbefehl_edit_in_eam_ai(modell: Path, tmp_path: Path) -> None:
    import eam_ai

    ops_datei = tmp_path / "ops.json"
    ops_datei.write_text(
        json.dumps([{"op": "set_note", "guid": E_B, "value": "per CLI"}]), encoding="utf-8"
    )
    out = tmp_path / "out.qea"
    assert eam_ai.main(["edit", "--qea", str(modell), "--ops", str(ops_datei), "--out", str(out)]) == 0
    assert _value(out, "Note", "B") == "per CLI"


@pytest.mark.skipif(not MDG.is_file(), reason="MDG-Belegdatei fehlt")
def test_unterbefehl_edit_mit_mdg_meldet_ablehnung(modell: Path, tmp_path: Path) -> None:
    import eam_ai

    ops_datei = tmp_path / "ops.json"
    ops_datei.write_text(
        json.dumps([{"op": "set_stereotype", "guid": E_A, "value": "GibtEsNicht"}]), encoding="utf-8"
    )
    out = tmp_path / "out.qea"
    code = eam_ai.main(
        ["edit", "--qea", str(modell), "--ops", str(ops_datei), "--out", str(out), "--mdg", str(MDG)]
    )
    assert code == 1
    assert out.is_file(), "die uebrigen Operationen werden trotzdem geschrieben"
