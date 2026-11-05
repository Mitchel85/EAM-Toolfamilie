"""Tests fuer ``roundtrip_export.py``.

Die synthetische Mini-.qea wird hier mit sqlite3 selbst aufgebaut: zwei Pakete,
zehn t_object-Zeilen (davon ein Paketspiegel), drei Kanten, zwei Sichten,
Attribute sowie Tagged Values in ``t_objectproperties`` UND ``t_xref`` --
inklusive HTML-Entity in einer Notiz und mehrerer ``@PROP=``-Bloecke in einer
``t_xref``-Zeile.

Der Test gegen die echte Fixture laeuft nur, wenn
``fixtures/Musterarchitektur_MASC.qea`` vorhanden ist.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import roundtrip_export as rx

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
FIXTURE = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"

GUID_P1 = "{AAAA0000-0000-0000-0000-000000000001}"
GUID_P2 = "{AAAA0000-0000-0000-0000-000000000002}"
GUID_E = {object_id: f"{{EEEE0000-0000-0000-0000-{object_id:012d}}}" for object_id in range(10, 20)}
GUID_C = {connector_id: f"{{CCCC0000-0000-0000-0000-{connector_id:012d}}}" for connector_id in range(100, 103)}
GUID_D = {diagram_id: f"{{DDDD0000-0000-0000-0000-{diagram_id:012d}}}" for diagram_id in range(200, 202)}

SCHEMA = """
CREATE TABLE t_package (
    Package_ID INTEGER PRIMARY KEY, Name TEXT, Parent_ID INTEGER,
    Notes TEXT, ea_guid TEXT, TPos INTEGER
);
CREATE TABLE t_object (
    Object_ID INTEGER PRIMARY KEY, Object_Type TEXT, Name TEXT, Alias TEXT,
    Note TEXT, Package_ID INTEGER, Stereotype TEXT, Status TEXT, ea_guid TEXT
);
CREATE TABLE t_connector (
    Connector_ID INTEGER PRIMARY KEY, Name TEXT, Direction TEXT, Notes TEXT,
    Connector_Type TEXT, Start_Object_ID INTEGER, End_Object_ID INTEGER,
    Stereotype TEXT, ea_guid TEXT
);
CREATE TABLE t_objectproperties (
    PropertyID INTEGER PRIMARY KEY, Object_ID INTEGER, Property TEXT,
    Value TEXT, Notes TEXT, ea_guid TEXT
);
CREATE TABLE t_xref (
    XrefID TEXT, Name TEXT, Type TEXT, Visibility TEXT, Description TEXT,
    Client TEXT, Supplier TEXT
);
CREATE TABLE t_attribute (
    ID INTEGER PRIMARY KEY, Object_ID INTEGER, Name TEXT, Type TEXT,
    Notes TEXT, ea_guid TEXT
);
CREATE TABLE t_operation (OperationID INTEGER PRIMARY KEY, Object_ID INTEGER, Name TEXT);
CREATE TABLE t_diagram (
    Diagram_ID INTEGER PRIMARY KEY, Package_ID INTEGER, Name TEXT,
    Diagram_Type TEXT, Notes TEXT, ea_guid TEXT, cx INTEGER, cy INTEGER
);
CREATE TABLE t_diagramobjects (
    Diagram_ID INTEGER, Object_ID INTEGER, RectTop INTEGER, RectLeft INTEGER,
    RectRight INTEGER, RectBottom INTEGER
);
CREATE TABLE t_diagramlinks (
    DiagramID INTEGER, ConnectorID INTEGER, Geometry TEXT
);
"""


def _prop(name: str, value: str) -> str:
    """Ein ``@PROP=``-Block, wie ihn EA in t_xref.Description schreibt."""
    return (
        f"@PROP=@NAME={name}@ENDNAME;@TYPE=string@ENDTYPE;"
        f"@VALU={value}@ENDVALU;@PRMT=@ENDPRMT;@ENDPROP;"
    )


def _build_mini_qea(path: Path) -> Path:
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO t_package VALUES (?,?,?,?,?,?)",
            [
                (1, "Wurzel", 0, None, GUID_P1, 0),
                (2, "Kind", 1, "Paketnotiz mit Umlaut: F&#252;hrung", GUID_P2, 0),
            ],
        )
        con.executemany(
            "INSERT INTO t_object VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (10, "Class", "Zeta", "Z", "F&#252;hrungsunterst&#252;tzung &amp; Lagebild", 1, "InformationElement", "Proposed", GUID_E[10]),
                (11, "Class", "Alpha", "", "<p>Zeile eins</p><br/>Zeile zwei", 1, "", "", GUID_E[11]),
                (12, "Class", "Beta", "", None, 2, "Service", "Draft", GUID_E[12]),
                (13, "Requirement", "Gamma", "", None, 2, "", "", GUID_E[13]),
                (14, "Class", "Delta", "", None, 2, "", "", GUID_E[14]),
                (15, "Class", "Epsilon", "", None, 1, "", "", GUID_E[15]),
                (16, "Note", "", "", "Notiz ohne Namen", 1, "", "", GUID_E[16]),
                (17, "Package", "Kind", "", None, 1, "ArchitecturalDescription", "Proposed", GUID_P2),
                (18, "Class", "Zeta", "", None, 2, "", "", GUID_E[18]),
                (19, "Class", "Eta", "", None, 2, "", "", GUID_E[19]),
            ],
        )
        con.executemany(
            "INSERT INTO t_connector VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (100, "bildet ab", "Source -> Destination", None, "Dependency", 10, 11, "CompliesViewpoint", GUID_C[100]),
                (101, "", "Source -> Destination", None, "Realisation", 11, 12, "", GUID_C[101]),
                (102, "", "Destination -> Source", None, "Generalization", 10, 13, "", GUID_C[102]),
            ],
        )
        con.executemany(
            "INSERT INTO t_objectproperties VALUES (?,?,?,?,?,?)",
            [
                (1, 10, "Auftraggeber", "BMVg", None, "{11111111-0000-0000-0000-000000000001}"),
                (2, 10, "Leer", None, None, "{11111111-0000-0000-0000-000000000002}"),
                (3, 11, "Status", "geplant", None, "{11111111-0000-0000-0000-000000000003}"),
                (4, 12, "Kosten", "100", None, "{11111111-0000-0000-0000-000000000004}"),
                (5, 12, "Kosten", "200", None, "{11111111-0000-0000-0000-000000000005}"),
            ],
        )
        con.executemany(
            "INSERT INTO t_xref VALUES (?,?,?,?,?,?,?)",
            [
                (
                    "{X1}", "CustomProperties", "element property", "Public",
                    _prop("_HideUmlLinks", "True") + _prop("Quelle", "Referenz"),
                    GUID_E[10], "<none>",
                ),
                (
                    "{X2}", "CustomProperties", "element property", "Public",
                    _prop("Auftraggeber", "XREF-darf-nicht-gewinnen"),
                    GUID_E[10], "<none>",
                ),
                (
                    "{X3}", "CustomProperties", "element property", "Public",
                    _prop("NurXref", "ja") + _prop("LeerXref", ""),
                    GUID_E[12].upper(), "<none>",
                ),
                (
                    "{X4}", "Stereotypes", "element property", "Public",
                    "@STEREO;Name=Ignoriert;FQName=Profil::Ignoriert;@ENDSTEREO;",
                    GUID_E[10], "<none>",
                ),
                ("{X5}", "CustomProperties", "element property", "Public", None, GUID_E[11], "<none>"),
            ],
        )
        con.executemany(
            "INSERT INTO t_attribute VALUES (?,?,?,?,?,?)",
            [
                (500, 10, "wert", "Integer", None, "{AA000000-0000-0000-0000-000000000500}"),
                (501, 10, "name", "char", None, "{AA000000-0000-0000-0000-000000000501}"),
                (502, 13, "prioritaet", "Integer", None, "{AA000000-0000-0000-0000-000000000502}"),
            ],
        )
        con.executemany(
            "INSERT INTO t_diagram VALUES (?,?,?,?,?,?,?,?)",
            [
                (200, 1, "\u00dcbersicht", "Custom", None, GUID_D[200], 800, 600),
                (201, 2, "Detail", "Logical", None, GUID_D[201], 1024, 768),
            ],
        )
        con.executemany(
            "INSERT INTO t_diagramobjects VALUES (?,?,?,?,?,?)",
            [(200, 10, 10, 10, 120, 60), (201, 12, 0, 0, 50, 50)],
        )
        con.execute(
            "INSERT INTO t_diagramlinks VALUES (?,?,?)",
            (200, 100, "EDGE=1;"),
        )
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture()
def mini_qea(tmp_path: Path) -> Path:
    return _build_mini_qea(tmp_path / "mini.qea")


def _export(tmp_path: Path, qea: Path, *, name: str = "out", **kwargs):
    md = tmp_path / f"{name}.md"
    js = tmp_path / f"{name}.json"
    stats = rx.export_documentation(qea, md, js, **kwargs)
    return stats, md, js


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def test_markdown_titel_kennzahlen_und_paketueberschriften(tmp_path, mini_qea):
    stats, md_path, _ = _export(tmp_path, mini_qea)
    md = md_path.read_text(encoding="utf-8")

    assert md.startswith("# Architektur-Dokumentation \u2014 mini.qea\n")
    assert "## Kennzahlen" in md
    assert "## Paket\u00fcbersicht" in md
    assert "## Wurzel\n" in md
    assert "## Wurzel/Kind\n" in md
    assert stats["pakete"] == 2
    assert stats["elemente"] == 10
    assert stats["kanten"] == 3
    assert stats["sichten"] == 2


def test_markdown_entity_dekodierung_und_html_bereinigung(tmp_path, mini_qea):
    _, md_path, _ = _export(tmp_path, mini_qea)
    md = md_path.read_text(encoding="utf-8")

    assert "F\u00fchrungsunterst\u00fctzung & Lagebild" in md
    assert "F\u00fchrung" in md  # Paketnotiz
    assert "Zeile eins Zeile zwei" in md  # <p>/<br/> entfernt, Umbruch = Leerzeichen
    assert "&#" not in md
    assert "&amp;" not in md
    assert "<p>" not in md
    assert "<br" not in md


def test_markdown_elementfelder_vollstaendig(tmp_path, mini_qea):
    _, md_path, _ = _export(tmp_path, mini_qea)
    md = md_path.read_text(encoding="utf-8")

    line = next(line for line in md.splitlines() if line.startswith("- **Zeta**"))
    assert "Typ: `Class`" in line
    assert "Stereotyp: `InformationElement`" in line
    assert "ID: `10`" in line
    assert f"GUID: `{GUID_E[10]}`" in line
    assert "Alias: `Z`" in line
    assert "Status: `Proposed`" in line
    assert "  - Notiz: F\u00fchrungsunterst\u00fctzung & Lagebild" in md
    assert "  - Attribute: `name`: `char`, `wert`: `Integer`" in md


def test_markdown_leere_felder_bleiben_lesbar(tmp_path, mini_qea):
    _, md_path, _ = _export(tmp_path, mini_qea)
    md = md_path.read_text(encoding="utf-8")

    assert "- **(unbenannt)** \u2014 Typ: `Note`" in md
    line = next(line for line in md.splitlines() if "ID: `13`" in line and line.startswith("- **Gamma**"))
    assert "Stereotyp: `-`" in line
    assert "Alias: `-`" in line
    assert "Status: `-`" in line


def test_markdown_beziehungen_und_sichten_ohne_koordinaten(tmp_path, mini_qea):
    _, md_path, _ = _export(tmp_path, mini_qea)
    md = md_path.read_text(encoding="utf-8")

    assert "## Beziehungen" in md
    assert "`Wurzel::Zeta` \u2192 `Wurzel::Alpha`" in md
    assert "Typ: `Dependency`" in md
    assert "Stereotyp: `CompliesViewpoint`" in md
    assert "Name: `bildet ab`" in md

    assert "## Sichten" in md
    assert "**\u00dcbersicht** \u2014 Typ: `Custom`" in md
    assert "**Detail** \u2014 Typ: `Logical`" in md
    # keine Layoutdaten (Diagramm-Koordinaten, Link-Geometrie)
    for verboten in ("RectTop", "RectLeft", "RectRight", "RectBottom", "Geometry", "1024", "768", "800"):
        assert verboten not in md


def test_kantenzeilen_enthalten_endpunkt_guids(tmp_path, mini_qea):
    _, md_path, _ = _export(tmp_path, mini_qea)
    md = md_path.read_text(encoding="utf-8")

    line = next(
        line
        for line in md.splitlines()
        if line.startswith("- `Wurzel::Zeta`")
        and "Quelle-GUID" in line
        and "ID: `100`" in line
    )
    assert f"Quelle-GUID: `{GUID_E[10]}`" in line
    assert f"Ziel-GUID: `{GUID_E[11]}`" in line
    assert "Richtung: `Source -> Destination`" in line
    # Jede Kante traegt beide Endpunkt-GUIDs.
    kanten = [line for line in md.splitlines() if line.startswith("- `") and "\u2192" in line]
    assert len(kanten) == 3
    assert all("Quelle-GUID: `{" in line and "Ziel-GUID: `{" in line for line in kanten)


def test_endpunkt_guid_nutzt_die_paket_guid():
    """Paketspiegel tragen in t_object eine eigene GUID; ausgegeben wird t_package."""
    pakete = {
        1: rx.Paket(1, "Wurzel", 0, GUID_P1, "", 0),
        2: rx.Paket(2, "Kind", 1, GUID_P2, "", 0),
    }
    spiegel = rx.Element(
        17, "Kind", "Package", "", "", 1, "", "", "{00000000-0000-0000-0000-00000000ABCD}",
        spiegel_paket_id=2,
    )
    assert rx._endpunkt_guid(17, {17: spiegel}, pakete) == GUID_P2
    echt = rx.Element(18, "Zeta", "Class", "", "", 2, "", "", GUID_E[18])
    assert rx._endpunkt_guid(18, {18: echt}, pakete) == GUID_E[18]
    assert rx._endpunkt_guid(99, {}, pakete) == ""


def test_tags_trennen_objectproperties_und_xref(tmp_path, mini_qea):
    _, md_path, _ = _export(tmp_path, mini_qea)
    zeilen = md_path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, zeile in enumerate(zeilen) if "- **Zeta**" in zeile and "ID: `10`" in zeile)
    block = []
    for zeile in zeilen[start:]:
        if block and (zeile.startswith("- **") or zeile.startswith("## ")):
            break
        block.append(zeile)
    tags_zeile = next(zeile for zeile in block if zeile.startswith("  - Tags: "))
    xref_zeile = next(zeile for zeile in block if zeile.startswith("  - Tags (xref): "))
    assert "`Auftraggeber=BMVg`" in tags_zeile
    assert "`Leer=`" in tags_zeile
    assert "_HideUmlLinks" not in tags_zeile
    assert "`_HideUmlLinks=True`" in xref_zeile
    assert "`Quelle=Referenz`" in xref_zeile
    assert "Auftraggeber" not in xref_zeile


def test_markdown_reihenfolge_ist_sortiert(tmp_path, mini_qea):
    _, md_path, _ = _export(tmp_path, mini_qea)
    md = md_path.read_text(encoding="utf-8")

    # Elemente im Paket Wurzel alphabetisch (casefold), leere Namen zuerst.
    abschnitt = md.split("## Wurzel\n", 1)[1].split("## Wurzel/Kind\n", 1)[0]
    namen = [
        zeile.split("**")[1]
        for zeile in abschnitt.splitlines()
        if zeile.startswith("- **")
    ]
    assert namen == sorted(namen, key=str.casefold)
    assert namen[0] == "(unbenannt)"
    assert "Alpha" in namen and "Zeta" in namen

    # Paketuebersicht: Pfade sortiert.
    pfade = [
        zeile.split("|")[1].strip()
        for zeile in md.splitlines()
        if zeile.startswith("| MASC") or zeile.startswith("| Wurzel")
    ]
    assert pfade == sorted(pfade, key=str.casefold)


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------


def test_tags_aus_objectproperties_und_xref_zusammengefuehrt(tmp_path, mini_qea):
    _, _, js_path = _export(tmp_path, mini_qea)
    belege = json.loads(js_path.read_text(encoding="utf-8"))
    elemente = {element["id"]: element for element in belege["elemente"]}

    tags = elemente[10]["tags"]
    assert tags["Auftraggeber"] == "BMVg"  # objectproperties gewinnt gegen xref
    assert tags["_HideUmlLinks"] == "True"  # nur in t_xref
    assert tags["Quelle"] == "Referenz"  # zweiter Block derselben xref-Zeile
    assert tags["Leer"] == ""  # NULL-Wert ist kein Fehler

    # Gross-/Kleinschreibung der Client-GUID ist egal (GUID_E[12].upper()).
    assert elemente[12]["tags"]["NurXref"] == "ja"
    assert elemente[12]["tags"]["LeerXref"] == ""
    assert elemente[12]["tags"]["Kosten"] == "100"  # erster Wert gewinnt

    # Stereotypes-Eintraege werden nicht als Tag gefuehrt.
    assert "Ignoriert" not in tags
    assert belege["quelle"]["kennzahlen"]["tag_konflikte"] == 1
    # Tags sind nach Schluessel sortiert (casefold, wie im Modul).
    assert list(tags) == sorted(tags, key=str.casefold)


def test_parse_prop_description_mehrere_bloecke():
    description = _prop("A", "1") + _prop("B", "") + "@PROP=@NAME=C@ENDNAME;"
    # Nur vollstaendige Bloecke zaehlen; ein abgeschnittener Block wird ignoriert.
    assert rx._parse_prop_description(description) == [("A", "1"), ("B", "")]
    assert rx._parse_prop_description(_prop("C", "3")) == [("C", "3")]
    assert rx._parse_prop_description("") == []
    assert rx._parse_prop_description("@STEREO;Name=X;@ENDSTEREO;") == []


# --------------------------------------------------------------------------
# JSON-Belege
# --------------------------------------------------------------------------


def test_belege_schema_und_kennzahlen(tmp_path, mini_qea):
    stats, _, js_path = _export(tmp_path, mini_qea)
    belege = json.loads(js_path.read_text(encoding="utf-8"))

    assert set(belege) == {"format_version", "quelle", "pakete", "elemente", "kanten", "sichten"}
    assert belege["format_version"] == rx.FORMAT_VERSION
    assert belege["quelle"]["datei"] == "mini.qea"
    assert belege["quelle"]["sha256"] == hashlib.sha256(mini_qea.read_bytes()).hexdigest()
    assert belege["quelle"]["kennzahlen"] == stats
    assert stats["elemente_ohne_paketspiegel"] == 9
    assert stats["attribute"] == 3
    assert stats["tags"] == sum(len(element["tags"]) for element in belege["elemente"])
    assert stats["gekuerzt"] is False

    for paket in belege["pakete"]:
        assert set(paket) == {"pfad", "id", "guid"}
    for element in belege["elemente"]:
        assert set(element) == {"id", "guid", "name", "stereotyp", "paket", "tags", "tags_xref"}
        assert isinstance(element["id"], int)
        assert isinstance(element["tags"], dict)
    for kante in belege["kanten"]:
        assert set(kante) == {"id", "guid", "typ", "stereotyp", "quelle", "ziel", "name"}
    for sicht in belege["sichten"]:
        assert set(sicht) == {"id", "guid", "name", "typ"}

    # Sortierung: Pakete nach Pfad, Kanten nach Quelle/Ziel/Typ/ID, Sichten nach Name.
    assert [p["pfad"] for p in belege["pakete"]] == ["Wurzel", "Wurzel/Kind"]
    assert [s["name"] for s in belege["sichten"]] == ["Detail", "\u00dcbersicht"]
    kanten_schluessel = [(k["quelle"].casefold(), k["ziel"].casefold(), k["typ"], k["id"]) for k in belege["kanten"]]
    assert kanten_schluessel == sorted(kanten_schluessel)
    assert belege["elemente"][0]["id"] == 16  # leerer Name sortiert zuerst


def test_belege_json_utf8_ohne_ascii_escaping(tmp_path, mini_qea):
    _, _, js_path = _export(tmp_path, mini_qea)
    roh = js_path.read_text(encoding="utf-8")
    assert "\\u00fc" not in roh
    assert "\u00dcbersicht" in roh
    assert roh.endswith("\n")
    assert roh.startswith("{\n  \"format_version\": 2,")


# --------------------------------------------------------------------------
# Determinismus und Grenzen
# --------------------------------------------------------------------------


def test_determinismus_byte_identisch(tmp_path, mini_qea):
    _, md_a, js_a = _export(tmp_path, mini_qea, name="lauf_a")
    _, md_b, js_b = _export(tmp_path, mini_qea, name="lauf_b")

    assert md_a.read_bytes() == md_b.read_bytes()
    assert js_a.read_bytes() == js_b.read_bytes()


def test_max_elements_kuerzt_und_filtert_kanten(tmp_path, mini_qea):
    stats, md_path, js_path = _export(tmp_path, mini_qea, max_elements=3)

    assert stats["elemente"] == 3
    assert stats["gekuerzt"] is True
    belege = json.loads(js_path.read_text(encoding="utf-8"))
    assert len(belege["elemente"]) == 3
    assert all(
        kante["quelle"].split("::")[-1] in {e["name"] for e in belege["elemente"]}
        for kante in belege["kanten"]
    )
    assert "begrenzt (--max-elements)" in md_path.read_text(encoding="utf-8")


def test_cli_schreibt_dateien(tmp_path, mini_qea, capsys):
    md = tmp_path / "cli.md"
    js = tmp_path / "cli.json"
    code = rx.main([str(mini_qea), "--md", str(md), "--belege", str(js)])
    assert code == 0
    assert md.is_file() and js.is_file()
    assert "Export ok" in capsys.readouterr().out


def test_cli_fehler_datei(tmp_path, capsys):
    code = rx.main([str(tmp_path / "fehlt.qea"), "--md", str(tmp_path / "a.md"), "--belege", str(tmp_path / "a.json")])
    assert code == 2
    assert "existiert nicht" in capsys.readouterr().err


def test_keine_qea_wirft_lauten_fehler(tmp_path):
    kaputt = tmp_path / "kaputt.qea"
    kaputt.write_text("kein sqlite", encoding="utf-8")
    with pytest.raises(rx.RoundtripExportError):
        rx.export_documentation(kaputt, tmp_path / "d.md", tmp_path / "d.json")


def test_fehlende_pflichttabelle_wirft_fehler(tmp_path):
    pfad = tmp_path / "ohne_object.qea"
    con = sqlite3.connect(pfad)
    con.execute("CREATE TABLE t_package (Package_ID INTEGER, Name TEXT)")
    con.execute("INSERT INTO t_package VALUES (1, 'X')")
    con.commit()
    con.close()
    with pytest.raises(rx.RoundtripExportError, match="t_object"):
        rx.export_documentation(pfad, tmp_path / "d.md", tmp_path / "d.json")


# --------------------------------------------------------------------------
# Echte Fixture (nur wenn vorhanden)
# --------------------------------------------------------------------------


@pytest.mark.skipif(not FIXTURE.exists(), reason="Fixture Musterarchitektur_MASC.qea fehlt")
def test_echte_fixture_kennzahlen_und_markdown(tmp_path):
    md = tmp_path / "masc.md"
    js = tmp_path / "masc.json"
    stats = rx.export_documentation(FIXTURE, md, js)

    assert stats["pakete"] >= 226
    assert stats["elemente"] >= 1600
    assert stats["kanten"] >= 1700
    assert stats["sichten"] >= 200

    belege = json.loads(js.read_text(encoding="utf-8"))
    assert len(belege["pakete"]) == stats["pakete"]
    assert len(belege["elemente"]) == stats["elemente"]
    assert len(belege["kanten"]) == stats["kanten"]
    assert belege["quelle"]["sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()

    text = md.read_text(encoding="utf-8")
    assert len(text) > 500_000
    assert "&#" not in text
    assert "## Beziehungen" in text
    assert "## Sichten" in text
    assert "F\u00fchrungsunterst\u00fctzungsbefehl" in text
    for paket in belege["pakete"][:25]:
        assert f"## {paket['pfad']}" in text
