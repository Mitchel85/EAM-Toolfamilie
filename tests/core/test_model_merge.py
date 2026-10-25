"""Tests fuer ``model_merge.py``.

Die Mini-.qea werden mit ``qea_writer`` erzeugt (schemakonform, 15 Pflicht-
tabellen). Der Writer akzeptiert vorgegebene ``guid``-Werte im IR; damit lassen
sich zwei Modelle bauen, die dasselbe Element mit **derselben** GUID enthalten --
genau der Fall, fuer den der Merge die Identitaet erhalten muss. Attribute und
``@PROP``-Zeilen ergaenzt eine kurze sqlite-Nachbearbeitung, weil das IR sie
nicht kennt.

Geprueft wird: GUID-Erhalt, Unveraendertheit der Basiszeilen, Aufloesung der
Kantenenden ueber GUIDs, Zusammenfuehren gleicher Paketpfade, Konflikte
(Stereotyp, Tag), Idempotenz, Determinismus, das Sammelpaket und die CLI.
Beleglaeufe gegen die echte ``Musterarchitektur_MASC.qea`` (12 MB) und die
kleine ``/tmp/ds_test/final2.qea`` laufen nur, wenn die Dateien vorhanden sind.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import model_merge as mm
import qea_reader
import qea_writer

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
#: Echtes Modell mit 226 Paketen, 1430 Elementen und 1747 Kanten (12 MB).
MASC = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"
#: Kleines Modell mit 96 Elementen und 24 Kanten (ausserhalb des Repos).
SMALL = Path("/tmp/ds_test/final2.qea")

# Feste GUIDs: so ist im Test ohne Nachrechnen klar, welches Objekt gemeint ist.
P_A = "{AAAA0000-0000-0000-0000-000000000001}"
P_SUB = "{AAAA0000-0000-0000-0000-000000000002}"
P_B = "{AAAA0000-0000-0000-0000-000000000003}"
E_X = "{BBBB0000-0000-0000-0000-000000000001}"
E_Y = "{BBBB0000-0000-0000-0000-000000000002}"
E_Z = "{BBBB0000-0000-0000-0000-000000000003}"
C_XY = "{CCCC0000-0000-0000-0000-000000000001}"
P_NEU = "{AAAA0000-0000-0000-0000-000000000004}"


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


def _rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _count(path: Path, table: str) -> int:
    return _rows(path, f'SELECT count(*) FROM "{table}"')[0][0]


def _objects(path: Path) -> dict[str, tuple]:
    """Elementname -> (Object_ID, Stereotyp, ea_guid) der echten Elemente."""
    return {
        name: (object_id, stereotype, guid)
        for object_id, name, stereotype, guid in _rows(
            path,
            "SELECT Object_ID, Name, Stereotype, ea_guid FROM t_object"
            " WHERE Object_Type <> 'Package' ORDER BY Object_ID",
        )
    }


def _object_rows(path: Path) -> dict[int, tuple]:
    """Object_ID -> vollstaendige Zeile (ohne rowid) fuer den Unveraendert-Test."""
    columns = [row[1] for row in _rows(path, 'PRAGMA table_info("t_object")')]
    rows = _rows(path, f'SELECT {", ".join(columns)} FROM t_object ORDER BY Object_ID')
    return {row[0]: tuple(row) for row in rows}


def _connectors(path: Path) -> list[tuple]:
    return _rows(
        path,
        "SELECT Connector_ID, Start_Object_ID, End_Object_ID, ea_guid"
        " FROM t_connector ORDER BY Connector_ID",
    )


def _guids(path: Path) -> set[str]:
    """Alle Objekt-, Paket- und Kanten-GUIDs einer Datei (grossgeschrieben)."""
    found: set[str] = set()
    for table in ("t_object", "t_package", "t_connector"):
        for (value,) in _rows(path, f'SELECT ea_guid FROM "{table}"'):
            if value:
                found.add(str(value).upper())
    return found


@pytest.fixture()
def basis(tmp_path: Path) -> Path:
    """Basismodell: zwei Pakete, zwei Elemente, eine Kante, zwei Tags."""
    return _write(
        tmp_path / "basis.qea",
        [{"path": "A", "guid": P_A}, {"path": "A/Sub", "guid": P_SUB}],
        [
            {
                "package": "A",
                "name": "X",
                "ea_type": "Class",
                "stereotype": "Standard",
                "guid": E_X,
                "tags": {"Quelle": "intern", "NurA": "1"},
            },
            {"package": "A/Sub", "name": "Y", "ea_type": "Class", "guid": E_Y},
        ],
        [
            {
                "source": "A::X",
                "target": "A/Sub::Y",
                "stereotype": "Dep",
                "ea_type": "Dependency",
                "guid": C_XY,
            }
        ],
    )


@pytest.fixture()
def zulieferung(tmp_path: Path) -> Path:
    """Zulieferung: X mit derselben GUID, neues Z, Kante Z -> X ohne ea_guid.

    Zusaetzlich bekommt Z ein Attribut, ein Attribut-Tag und eine
    ``@PROP``-Zeile in ``t_xref`` -- Inhalte, die das IR nicht abbildet.
    """
    path = _write(
        tmp_path / "zulieferung.qea",
        [{"path": "A", "guid": P_A}],
        [
            {
                "package": "A",
                "name": "X",
                "ea_type": "Class",
                "stereotype": "Standard",
                "guid": E_X,
                "tags": {"Quelle": "extern", "Neu": "2"},
            },
            {"package": "A", "name": "Z", "ea_type": "Class", "guid": E_Z},
        ],
        [
            {
                "source": "A::Z",
                "target": "A::X",
                "stereotype": "Dep",
                "ea_type": "Dependency",
                "name": "z-nach-x",
            }
        ],
    )
    _sql(
        path,
        ("UPDATE t_connector SET ea_guid = NULL", ()),
        (
            "INSERT INTO t_attribute (Object_ID, Name, Stereotype, Type, ID, ea_guid)"
            " SELECT Object_ID, 'attribut', '', 'String', 1,"
            " '{DDDD0000-0000-0000-0000-000000000001}' FROM t_object WHERE ea_guid = ?",
            (E_Z,),
        ),
        (
            "INSERT INTO t_attributetag (PropertyID, ElementID, Property, VALUE, ea_guid)"
            " VALUES (1, 1, 'einheit', 'm', '{DDDD0000-0000-0000-0000-000000000002}')",
            (),
        ),
        (
            "INSERT INTO t_xref (XrefID, Name, Type, Description, Client)"
            " VALUES ('{EEEE0000-0000-0000-0000-000000000001}', 'CustomProperties',"
            " 'element property',"
            " '@PROP=@NAME=Herkunft@ENDNAME;@TYPE=string@ENDTYPE;"
            "@VALU=Zulieferung@ENDVALU;@PRMT=@ENDPRMEND;@ENDPROP;', ?)",
            (E_Z,),
        ),
    )
    return path


# --------------------------------------------------------------------------
# Kernverhalten
# --------------------------------------------------------------------------


def test_zwei_modelle_werden_zusammengefuehrt(basis: Path, zulieferung: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.qea"
    result = mm.merge_models([basis, zulieferung], out)

    assert Path(result.written) == out
    assert result.models == 2
    assert result.elements == 1, "nur Z ist neu; X liegt schon vor"
    assert result.merged == 1
    assert result.packages == 0, "Paket A liegt schon vor"
    assert result.connections == 1
    assert _count(out, "t_object") == _count(basis, "t_object") + 1
    assert set(_objects(out)) == {"X", "Y", "Z"}


def test_guids_bleiben_woertlich(basis: Path, zulieferung: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.qea"
    mm.merge_models([basis, zulieferung], out)

    assert _guids(zulieferung) <= _guids(out), "jede Quell-GUID muss im Ziel stehen"
    assert _objects(out)["X"][2] == E_X
    assert _objects(out)["Z"][2] == E_Z


def test_basiszeilen_bleiben_unveraendert(basis: Path, zulieferung: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.qea"
    mm.merge_models([basis, zulieferung], out)

    before = _object_rows(basis)
    after = _object_rows(out)
    for object_id, row in before.items():
        assert after[object_id] == row, f"Object_ID {object_id} wurde veraendert"

    assert basis.read_bytes() != b"", "Basismodell bleibt unangetastet"
    assert _count(basis, "t_object") == len(before)


def test_kante_ohne_guid_wird_ueber_die_endpunkt_guids_aufgeloest(
    basis: Path, zulieferung: Path, tmp_path: Path
) -> None:
    """X liegt schon im Ziel: die neue Kante muss trotzdem auf X zeigen."""
    out = tmp_path / "out.qea"
    mm.merge_models([basis, zulieferung], out)

    x_id = _objects(out)["X"][0]
    z_id = _objects(out)["Z"][0]
    neue = [row for row in _connectors(out) if row[3] not in {C_XY.upper(), C_XY}]
    assert len(neue) == 1
    connector_id, start, end, guid = neue[0]
    assert (start, end) == (z_id, x_id), "Package_IDs duerfen keine Rolle spielen"
    assert guid and guid.startswith("{") and guid.endswith("}"), "Ersatz-GUID im EA-Format"


def test_kante_ohne_guid_bekommt_dieselbe_guid_wie_im_ersten_lauf(
    basis: Path, zulieferung: Path, tmp_path: Path
) -> None:
    first = tmp_path / "first.qea"
    second = tmp_path / "second.qea"
    mm.merge_models([basis, zulieferung], first)
    mm.merge_models([basis, zulieferung], second)

    assert first.read_bytes() == second.read_bytes()
    assert _connectors(first) == _connectors(second)


def test_idempotent_gleiche_eingaben(basis: Path, zulieferung: Path, tmp_path: Path) -> None:
    first = tmp_path / "first.qea"
    second = tmp_path / "second.qea"
    mm.merge_models([basis, zulieferung], first)
    mm.merge_models([basis, zulieferung], second)
    assert first.read_bytes() == second.read_bytes()


def test_idempotent_ergebnis_als_basis(basis: Path, zulieferung: Path, tmp_path: Path) -> None:
    """Ein zweiter Lauf auf dem Ergebnis darf nichts mehr aendern."""
    first = tmp_path / "first.qea"
    mm.merge_models([basis, zulieferung], first)

    again = tmp_path / "again.qea"
    result = mm.merge_models([first, zulieferung], again)

    assert again.read_bytes() == first.read_bytes()
    assert (result.elements, result.connections, result.packages, result.merged) == (0, 0, 0, 2)


def test_pakete_mit_gleichem_pfad_werden_zusammengefuehrt(
    basis: Path, zulieferung: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.qea"
    mm.merge_models([basis, zulieferung], out)

    namen = [row[0] for row in _rows(out, "SELECT Name FROM t_package ORDER BY Package_ID")]
    assert namen == ["A", "Sub"], "kein zweites Paket A"
    assert sorted(entry["path"] for entry in qea_reader.read_qea(out)["packages"]) == ["A", "A/Sub"]


def test_neues_paket_bekommt_paketspiegel(tmp_path: Path) -> None:
    """Nicht-Wurzelpakete brauchen einen Spiegel; Wurzeln nicht (EA-Konvention)."""
    links = _write(
        tmp_path / "links.qea",
        [{"path": "L", "guid": P_B}, {"path": "L/Unter", "guid": P_SUB}],
        [{"package": "L/Unter", "name": "U", "ea_type": "Class", "guid": E_Y}],
    )
    rechts = _write(
        tmp_path / "rechts.qea",
        [{"path": "R", "guid": P_A}, {"path": "R/Neu", "guid": P_NEU}],
        [{"package": "R/Neu", "name": "V", "ea_type": "Class", "guid": E_X}],
    )
    out = tmp_path / "out.qea"
    result = mm.merge_models([links, rechts], out)

    assert result.packages == 2
    spiegel = _rows(
        out,
        "SELECT Name, Package_ID, ea_guid FROM t_object WHERE Object_Type = 'Package'",
    )
    assert sorted(name for name, _, _ in spiegel) == ["Neu", "Unter"]
    r_id = _rows(out, "SELECT Package_ID FROM t_package WHERE Name = 'R'")[0][0]
    assert ("Neu", r_id, P_NEU) in spiegel, "Spiegel haengt im Elternpaket und traegt die Paket-GUID"
    assert all(guid != P_A for _, _, guid in spiegel), "Wurzel R bekommt keinen Spiegel"


def test_konflikt_bei_unterschiedlichem_stereotyp(basis: Path, tmp_path: Path) -> None:
    anders = _write(
        tmp_path / "anders.qea",
        [{"path": "A", "guid": P_A}],
        [{"package": "A", "name": "X", "ea_type": "Class", "stereotype": "Spezial"}],
    )
    out = tmp_path / "out.qea"
    result = mm.merge_models([basis, anders], out)

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict["art"] == "stereotype"
    assert conflict["paket"] == "A"
    assert conflict["name"] == "X"
    assert conflict["vorhanden"] == ["Standard"]
    assert conflict["uebernommen"] == "Spezial"

    stereotypen = sorted(
        row[0]
        for row in _rows(
            out, "SELECT Stereotype FROM t_object WHERE Name = 'X' AND Object_Type <> 'Package'"
        )
    )
    assert stereotypen == ["Spezial", "Standard"], "beide Elemente bleiben erhalten"


def test_tag_ziel_gewinnt_und_konflikt_wird_gemeldet(
    basis: Path, zulieferung: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.qea"
    result = mm.merge_models([basis, zulieferung], out)

    tags = dict(
        _rows(
            out,
            "SELECT Property, Value FROM t_objectproperties WHERE Object_ID ="
            " (SELECT Object_ID FROM t_object WHERE Name = 'X' AND Object_Type <> 'Package')",
        )
    )
    assert tags["Quelle"] == "intern", "der Zielwert gewinnt"
    assert tags["NurA"] == "1", "Ziel-Tag bleibt"
    assert tags["Neu"] == "2", "unbekanntes Tag der Quelle wird ergaenzt"

    tag_konflikte = [item for item in result.conflicts if item["art"] == "tag"]
    assert len(tag_konflikte) == 1
    assert tag_konflikte[0] == {
        "art": "tag",
        "paket": "A",
        "name": "X",
        "tag": "Quelle",
        "ziel": "intern",
        "quelle": "extern",
        "modell": 1,
        "datei": "zulieferung.qea",
    }


def test_attribut_und_attributtag_werden_uebernommen(
    basis: Path, zulieferung: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.qea"
    mm.merge_models([basis, zulieferung], out)

    z_id = _objects(out)["Z"][0]
    attribute = _rows(out, "SELECT ID, Object_ID, Name, Type FROM t_attribute")
    assert len(attribute) == 1
    attribute_id, owner, name, typ = attribute[0]
    assert (owner, name, typ) == (z_id, "attribut", "String")

    tags = _rows(out, "SELECT ElementID, Property, VALUE FROM t_attributetag")
    assert tags == [(attribute_id, "einheit", "m")]


def test_xref_custom_property_wird_mitgenommen(
    basis: Path, zulieferung: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.qea"
    mm.merge_models([basis, zulieferung], out)

    beschreibungen = [
        row[0]
        for row in _rows(out, "SELECT Description FROM t_xref WHERE Client = ?", (E_Z,))
    ]
    assert any("@NAME=Herkunft" in text and "@VALU=Zulieferung" in text for text in beschreibungen)


def test_fehlender_endpunkt_wird_nicht_erfunden(tmp_path: Path) -> None:
    links = _write(
        tmp_path / "links.qea",
        [{"path": "L"}],
        [{"package": "L", "name": "V", "ea_type": "Class", "guid": E_X}],
    )
    rechts = _write(
        tmp_path / "rechts.qea",
        [{"path": "R"}],
        [{"package": "R", "name": "W", "ea_type": "Class", "guid": E_Y}],
        [
            {
                "source": "R::W",
                "target": "R::W",
                "stereotype": "Dep",
                "ea_type": "Dependency",
            }
        ],
    )
    # Ziel der Kante auf eine Object_ID legen, die es nicht gibt.
    _sql(rechts, ("UPDATE t_connector SET End_Object_ID = 9999", ()))

    out = tmp_path / "out.qea"
    result = mm.merge_models([links, rechts], out)

    assert result.connections == 0
    assert _count(out, "t_connector") == 0
    assert any("nicht per ea_guid aufloesbar" in text for text in result.warnings)


def test_ein_modell_ist_eine_byte_genaue_kopie(basis: Path) -> None:
    out = basis.with_name("kopie.qea")
    result = mm.merge_models([basis], out)
    assert out.read_bytes() == basis.read_bytes()
    assert (result.elements, result.connections, result.packages) == (0, 0, 0)


def test_dasselbe_modell_zweimal_aendert_nichts(basis: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.qea"
    result = mm.merge_models([basis, basis], out)
    assert out.read_bytes() == basis.read_bytes()
    assert result.elements == 0
    assert result.merged == 2


def test_sammelpaket_haelt_gleichnamige_wurzeln_auseinander(tmp_path: Path) -> None:
    links = _write(
        tmp_path / "links.qea",
        [{"path": "Wurzel", "guid": P_A}],
        [{"package": "Wurzel", "name": "V", "ea_type": "Class", "guid": E_X}],
    )
    rechts = _write(
        tmp_path / "rechts.qea",
        [{"path": "Wurzel", "guid": P_B}],
        [{"package": "Wurzel", "name": "W", "ea_type": "Class", "guid": E_Y}],
    )
    out = tmp_path / "out.qea"
    result = mm.merge_models([links, rechts], out, package="Import")

    assert result.packages == 2
    pfade = sorted(entry["path"] for entry in qea_reader.read_qea(out)["packages"])
    assert pfade == ["Import", "Import/Wurzel", "Wurzel"]
    elemente = {(entry["package"], entry["name"]) for entry in qea_reader.read_qea(out)["elements"]}
    assert elemente == {("Wurzel", "V"), ("Import/Wurzel", "W")}


# --------------------------------------------------------------------------
# Fehler, Bericht, CLI
# --------------------------------------------------------------------------


def test_out_darf_kein_eingabemodell_sein(basis: Path, zulieferung: Path) -> None:
    with pytest.raises(mm.MergeError):
        mm.merge_models([basis, zulieferung], basis)


def test_leere_liste_ist_ein_fehler(tmp_path: Path) -> None:
    with pytest.raises(mm.MergeError):
        mm.merge_models([], tmp_path / "out.qea")


def test_fehlende_datei_ist_ein_fehler(tmp_path: Path, basis: Path) -> None:
    with pytest.raises(mm.MergeError):
        mm.merge_models([basis, tmp_path / "gibtsnicht.qea"], tmp_path / "out.qea")


def test_bericht_ist_json_ohne_zeitstempel(basis: Path, zulieferung: Path, tmp_path: Path) -> None:
    result = mm.merge_models([basis, zulieferung], tmp_path / "out.qea")
    report = result.as_dict()

    assert set(report) == {
        "geschrieben",
        "modelle",
        "pakete",
        "elemente",
        "kanten",
        "tags",
        "zusammengefuehrt",
        "konflikte",
        "warnungen",
    }
    assert not {"zeit", "datum", "timestamp", "created"} & set(report)
    text = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert json.loads(text) == report


def test_cli_schreibt_bericht(basis: Path, zulieferung: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "out.qea"
    code = mm.main([str(basis), str(zulieferung), "--out", str(out)])

    assert code == 0
    assert out.is_file()
    report = json.loads(capsys.readouterr().out)
    assert report["elemente"] == 1
    assert report["kanten"] == 1
    assert report["modelle"] == 2


def test_cli_meldet_fehler_mit_exit_2(tmp_path: Path) -> None:
    assert mm.main([str(tmp_path / "fehlt.qea"), "--out", str(tmp_path / "out.qea")]) == 2


def test_unterbefehl_merge_in_eam_ai(basis: Path, zulieferung: Path, tmp_path: Path) -> None:
    import eam_ai

    out = tmp_path / "out.qea"
    bericht = tmp_path / "bericht.json"
    code = eam_ai.main(
        [
            "merge",
            "--qea",
            str(basis),
            str(zulieferung),
            "--out",
            str(out),
            "--bericht",
            str(bericht),
        ]
    )
    assert code == 0
    assert out.is_file()
    assert json.loads(bericht.read_text(encoding="utf-8"))["elemente"] == 1


# --------------------------------------------------------------------------
# Regression: Paketspiegel must point to the new package ID
# --------------------------------------------------------------------------


def test_neues_unterpaket_kollidiert_nicht_mit_vorhandener_package_id(tmp_path: Path) -> None:
    """PDATA1 des neuen Spiegels muss auf die Ziel-Package_ID zeigen.

    Sonst ordnet ``qea_reader`` den Spiegel ueber die zufaellig gleiche
    Quell-Package_ID einem vorhandenen Paket zu und meldet zwei Spiegel.
    """
    base = _write(
        tmp_path / "base.qea",
        [
            {"path": "A", "guid": "{AAAA0000-0000-0000-0000-000000000011}"},
            {"path": "A/Sub", "guid": "{AAAA0000-0000-0000-0000-000000000012}"},
        ],
        [{"package": "A", "name": "X", "ea_type": "Class", "guid": "{BBBB0000-0000-0000-0000-000000000011}"}],
    )
    add = _write(
        tmp_path / "add.qea",
        [
            {"path": "A", "guid": "{AAAA0000-0000-0000-0000-000000000011}"},
            {"path": "A/New", "guid": "{AAAA0000-0000-0000-0000-000000000013}"},
        ],
        [{"package": "A/New", "name": "Y", "ea_type": "Class", "guid": "{BBBB0000-0000-0000-0000-000000000012}"}],
    )
    out = tmp_path / "out.qea"

    result = mm.merge_models([base, add], out)

    assert result.packages == 1
    ir, report = qea_reader.read_qea_ex(out)
    assert any(p.get("path") == "A/New" for p in ir["packages"])
    assert not any("zwei Spiegel" in warning for warning in report.warnings)
    mirror = _rows(
        out,
        "SELECT o.PDATA1, p.Package_ID FROM t_object o"
        " JOIN t_package p ON p.ea_guid = o.ea_guid"
        " WHERE p.Name = 'New'",
    )
    assert mirror and mirror[0][0] == str(mirror[0][1])


# --------------------------------------------------------------------------
# Beleglaeufe gegen echte Modelle
# --------------------------------------------------------------------------


@pytest.mark.skipif(not (MASC.is_file() and SMALL.is_file()), reason="grosse Belegdateien fehlen")
def test_beleglauf_masc_plus_kleines_modell(tmp_path: Path) -> None:
    out = tmp_path / "masc_klein.qea"
    result = mm.merge_models([MASC, SMALL], out)

    assert result.elements == 96
    assert result.connections == 24
    assert result.packages == 1
    # Jede GUID des kleinen Modells steht danach im grossen.
    klein = {
        str(value).upper()
        for (value,) in _rows(SMALL, "SELECT ea_guid FROM t_object WHERE ea_guid IS NOT NULL")
    }
    assert klein <= _guids(out)

    # Das Ergebnis ist ein lesbares Modell, kein Zeilenfriedhof.
    ir, report = qea_reader.read_qea_ex(out)
    assert len(ir["elements"]) == 1526
    assert len(ir["connectors"]) == 1771
    assert not any("Spiegel von Wurzelpaketen" in text for text in report.warnings)

    # Determinismus und Idempotenz auf 12 MB.
    second = tmp_path / "masc_klein_2.qea"
    mm.merge_models([MASC, SMALL], second)
    assert out.read_bytes() == second.read_bytes()

    again = tmp_path / "masc_klein_3.qea"
    repeat = mm.merge_models([out, SMALL], again)
    assert again.read_bytes() == out.read_bytes()
    assert (repeat.elements, repeat.connections, repeat.packages) == (0, 0, 0)


@pytest.mark.skipif(not MASC.is_file(), reason="grosse Belegdatei fehlt")
def test_beleglauf_masc_mit_sich_selbst(tmp_path: Path) -> None:
    out = tmp_path / "masc_masc.qea"
    result = mm.merge_models([MASC, MASC], out)

    assert out.read_bytes() == MASC.read_bytes(), "Selbstmerge darf kein Byte aendern"
    assert result.elements == 0
    assert result.connections == 0
    assert result.merged == 1430
