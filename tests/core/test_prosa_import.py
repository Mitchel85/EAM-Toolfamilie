"""Tests fuer ``prosa_import.py`` -- Markdown-Dokument zurueck nach .qea."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import prosa_import as pi
import roundtrip_export as rx
import roundtrip_metrics as rm

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
FIXTURE = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"

G_P1 = "{AAAA0000-0000-0000-0000-000000000001}"
G_P2 = "{AAAA0000-0000-0000-0000-000000000002}"
G_E1 = "{EEEE0000-0000-0000-0000-000000000010}"
G_E2 = "{EEEE0000-0000-0000-0000-000000000011}"
G_E3 = "{EEEE0000-0000-0000-0000-000000000012}"
G_E4 = "{EEEE0000-0000-0000-0000-000000000014}"
G_C1 = "{CCCC0000-0000-0000-0000-000000000005}"
G_C2 = "{CCCC0000-0000-0000-0000-000000000006}"
G_C3 = "{CCCC0000-0000-0000-0000-000000000007}"


def _dokument() -> str:
    """Synthetisches Dokument: 2 Pakete, 4 Elemente (ein Name doppelt), 3 Kanten."""
    return f"""# Architektur-Dokumentation \u2014 mini.md

Quelle: `mini.qea`  
SHA-256: `0000000000000000000000000000000000000000000000000000000000000000`  
Format: `roundtrip_export 2`

## Kennzahlen

| Kennzahl | Wert |
| --- | ---: |
| Pakete | 2 |

## Paket\u00fcbersicht

| Paketpfad | Paket-ID | GUID |
| --- | ---: | --- |
| Wurzel | 1 | `{G_P1}` |

## Wurzel

Paket-ID: `1` \u00b7 GUID: `{G_P1}`

- **Alpha** \u2014 Typ: `Class` \u00b7 Stereotyp: `System` \u00b7 ID: `10` \u00b7 GUID: `{G_E1}` \u00b7 Alias: `A` \u00b7 Status: `Proposed`
  - Notiz: Alpha-Notiz mit Umlaut \u00dc
  - Tags: `Beschreibung=Alpha, Beta, Gamma`, `Leer=`
- **Pr\u00fcf\\*\\_Gr\u00f6\u00dfe** \u2014 Typ: `Class` \u00b7 Stereotyp: `-` \u00b7 ID: `11` \u00b7 GUID: `{G_E2}` \u00b7 Alias: `-` \u00b7 Status: `-`
  - Rohname: "Pr\u00fcf*_Gr\u00f6\u00dfe\\\\r\\\\nZeile"
  - Tags (xref): `Quelle=Referenz, mit Komma`

## Wurzel/Kind

Paket-ID: `2` \u00b7 GUID: `{G_P2}`

Notiz: Kind-Notiz

- **Doppelt** \u2014 Typ: `Class` \u00b7 Stereotyp: `-` \u00b7 ID: `13` \u00b7 GUID: `{G_E3}` \u00b7 Alias: `-` \u00b7 Status: `-`
  - Tags: `Nr=1`
- **Doppelt** \u2014 Typ: `Class` \u00b7 Stereotyp: `-` \u00b7 ID: `14` \u00b7 GUID: `{G_E4}` \u00b7 Alias: `-` \u00b7 Status: `-`
  - Tags: `Nr=2`

## Beziehungen

3 Beziehungen.

- `Wurzel::Alpha` \u2192 `Wurzel/Kind::Doppelt` \u2014 Typ: `Dependency` \u00b7 Stereotyp: `-` \u00b7 Name: `-` \u00b7 ID: `5` \u00b7 GUID: `{G_C1}` \u00b7 Quelle-GUID: `{G_E1}` \u00b7 Ziel-GUID: `{G_E4}` \u00b7 Richtung: `Source -> Destination`
- `Wurzel/Kind::Doppelt` \u2192 `Wurzel/Kind` \u2014 Typ: `Realisation` \u00b7 Stereotyp: `-` \u00b7 Name: `-` \u00b7 ID: `6` \u00b7 GUID: `{G_C2}` \u00b7 Quelle-GUID: `{G_E3}` \u00b7 Ziel-GUID: `{G_P2}` \u00b7 Richtung: `Source -> Destination`
- `Wurzel::Pr\u00fcf*_Gr\u00f6\u00dfe` \u2192 `Wurzel/Kind::Doppelt#1` \u2014 Typ: `Dependency` \u00b7 Stereotyp: `-` \u00b7 Name: `-` \u00b7 ID: `7` \u00b7 GUID: `{G_C3}` \u00b7 Quelle-GUID: `{G_E2}` \u00b7 Ziel-GUID: `{G_E3}` \u00b7 Richtung: `Source -> Destination`

## Sichten

0 Sichten (Diagramme) mit Name und Typ.
"""


@pytest.fixture()
def doku(tmp_path: Path) -> Path:
    path = tmp_path / "doku.md"
    path.write_text(_dokument(), encoding="utf-8")
    return path


def _db(path: Path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def test_import_schreibt_pakete_elemente_und_kanten(tmp_path: Path, doku: Path) -> None:
    ziel = tmp_path / "neu.qea"
    assert pi.import_document(doku, ziel) == (2, 4, 3)

    con = _db(ziel)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT count(*) FROM t_package").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM t_object").fetchone()[0] == 5  # 4 + 1 Spiegel
        assert con.execute("SELECT count(*) FROM t_connector").fetchone()[0] == 3

        objekte = {
            row["ea_guid"]: (row["Name"], row["Object_Type"], row["Stereotype"])
            for row in con.execute("SELECT * FROM t_object")
        }
        assert objekte[G_E1] == ("Alpha", "Class", "System")
        assert objekte[G_E2] == ("Pr\u00fcf*_Gr\u00f6\u00dfe\\r\\nZeile", "Class", "")
        assert {objekte[G_E3][0], objekte[G_E4][0]} == {"Doppelt"}
        assert objekte[G_P2][0] == "Kind"
        assert objekte[G_P2][1] == "Package"

        # Kante 5 zeigt auf das zweite "Doppelt" (GUID E4), nicht auf das erste.
        kante = con.execute(
            "SELECT c.ea_guid, ziel.ea_guid AS ziel FROM t_connector c "
            "JOIN t_object ziel ON ziel.Object_ID = c.End_Object_ID WHERE c.ea_guid = ?",
            (G_C1,),
        ).fetchone()
        assert kante["ziel"] == G_E4
    finally:
        con.close()


def test_import_trennt_tags_und_xref_tags(tmp_path: Path, doku: Path) -> None:
    ziel = tmp_path / "tags.qea"
    pi.import_document(doku, ziel)
    con = _db(ziel)
    try:
        alpha = {
            row["Property"]: row["Value"]
            for row in con.execute(
                "SELECT p.Property, p.Value FROM t_objectproperties p "
                "JOIN t_object o ON o.Object_ID = p.Object_ID WHERE o.ea_guid = ?",
                (G_E1,),
            )
        }
        assert alpha["Beschreibung"] == "Alpha, Beta, Gamma"
        assert alpha["Leer"] == ""

        pruef = con.execute(
            "SELECT count(*) FROM t_objectproperties WHERE Object_ID = "
            "(SELECT Object_ID FROM t_object WHERE ea_guid = ?)",
            (G_E2,),
        ).fetchone()[0]
        assert pruef == 0
        xref = con.execute(
            "SELECT Description FROM t_xref WHERE Client = ? AND Name = 'CustomProperties'",
            (G_E2,),
        ).fetchone()
        assert xref is not None
        assert "@VALU=Referenz, mit Komma@ENDVALU;" in xref["Description"]

        # Paketnotiz aus dem Abschnitt bleibt erhalten.
        assert con.execute("SELECT Notes FROM t_package WHERE Name = 'Kind'").fetchone()[0] == "Kind-Notiz"
    finally:
        con.close()


def test_import_ist_deterministisch(tmp_path: Path, doku: Path) -> None:
    a = tmp_path / "a.qea"
    b = tmp_path / "b.qea"
    pi.import_document(doku, a)
    pi.import_document(doku, b)
    assert a.read_bytes() == b.read_bytes()


def test_belege_haben_vorrang_bei_tags(tmp_path: Path) -> None:
    text = _dokument()
    # Tags-Zeilen entfernen: dann muss die Belegdatei einspringen.
    text = "\n".join(
        line for line in text.splitlines() if not line.startswith("  - Tags")
    ) + "\n"
    dokument = tmp_path / "ohne_tags.md"
    dokument.write_text(text, encoding="utf-8")
    belege = tmp_path / "belege.json"
    belege.write_text(
        json.dumps(
            {
                "format_version": 2,
                "pakete": [{"pfad": "Wurzel", "id": 1, "guid": G_P1}],
                "elemente": [
                    {
                        "id": 10,
                        "guid": G_E1,
                        "name": "Alpha",
                        "stereotyp": "System",
                        "paket": "Wurzel",
                        "tags": {"A": "1", "B": "2"},
                        "tags_xref": {"B": "2"},
                    }
                ],
                "kanten": [],
            }
        ),
        encoding="utf-8",
    )
    ziel = tmp_path / "belege.qea"
    pi.import_document(dokument, ziel, belege_path=belege)

    con = _db(ziel)
    try:
        tags = {
            row[0]: row[1]
            for row in con.execute(
                "SELECT p.Property, p.Value FROM t_objectproperties p "
                "JOIN t_object o ON o.Object_ID = p.Object_ID WHERE o.ea_guid = ?",
                (G_E1,),
            )
        }
        assert tags == {"A": "1"}
        xref = con.execute(
            "SELECT Description FROM t_xref WHERE Client = ? AND Name = 'CustomProperties'",
            (G_E1,),
        ).fetchone()
        assert "@NAME=B@ENDNAME;" in xref[0]
    finally:
        con.close()


def test_formatfehler_exit_2_und_klartext(tmp_path: Path, capsys) -> None:
    kaputt = tmp_path / "kaputt.md"
    kaputt.write_text(
        "## Wurzel\n\nPaket-ID: `1` \u00b7 GUID: `{AAAA0000-0000-0000-0000-000000000001}`\n\n"
        "- **Alpha** \u2014 Typ: `Class`\n",
        encoding="utf-8",
    )
    code = pi.main([str(kaputt), "--out", str(tmp_path / "x.qea")])
    assert code == 2
    assert "Elementzeile nicht lesbar" in capsys.readouterr().err
    assert not (tmp_path / "x.qea").exists()


def test_mehrdeutiger_text_endpunkt_ohne_guid_wird_gemeldet(tmp_path: Path) -> None:
    text = _dokument().replace(
        f"Quelle-GUID: `{G_E4}`", "Quelle-GUID: `-`"
    ).replace("`Wurzel/Kind::Doppelt` \u2192", "`Wurzel/Kind::Doppelt` \u2192")
    # Ziel-GUID entfernen, damit der Textfallback greifen muss.
    text = text.replace(f"Ziel-GUID: `{G_E4}`", "Ziel-GUID: `-`")
    pfad = tmp_path / "mehrdeutig.md"
    pfad.write_text(text, encoding="utf-8")
    with pytest.raises(pi.ProsaImportError, match="mehrdeutig"):
        pi.import_document(pfad, tmp_path / "y.qea")


@pytest.mark.skipif(not FIXTURE.exists(), reason="Fixture Musterarchitektur_MASC.qea fehlt")
def test_echte_masc_kette_erreicht_treue(tmp_path: Path) -> None:
    md = tmp_path / "masc.md"
    js = tmp_path / "belege.json"
    rx.export_documentation(FIXTURE, md, js)
    neu = tmp_path / "neu.qea"
    pakete, elemente, kanten = pi.import_document(md, neu)
    bericht = rm.bericht(FIXTURE, neu)

    assert pakete == 226
    assert elemente == 1430
    assert kanten == 1747
    treffer = bericht["treffer"]
    assert treffer["pakete"]["quote"] == 100.0
    assert treffer["elemente"]["quote"] >= 99.0
    assert treffer["kanten"]["quote"] >= 99.0
    assert treffer["tags"]["quote"] >= 99.0
    assert bericht["gesamtquote"] >= 99.5
