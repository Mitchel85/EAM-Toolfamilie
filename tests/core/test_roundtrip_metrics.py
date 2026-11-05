"""Tests fuer ``roundtrip_metrics.py``: Treuequote zwischen zwei .qea-Dateien.

Alle Modelle werden hier synthetisch per ``sqlite3`` erzeugt (Sparx-EA-Schema
im Kleinen). Das echte Referenzmodell wird nur gelesen und nie kopiert; der
Fixture-Test laeuft ausschliesslich gegen sich selbst und wird uebersprungen,
wenn die Datei fehlt.

Die Zahlen sind bewusst von Hand nachrechenbar:

* 2 Pakete (``Root``, ``Root/P1``)
* 6 Elemente ``A``..``F`` in ``P1`` (dazu ein Paketspiegel, der nicht zaehlt)
* 3 Kanten ``A->B``, ``C->D``, ``A->C``
* je Element 2 Tags ``(Tag1, <Name>)`` und ``(Tag2, fest)``

Der veraenderte Rueckbau loescht ``F``, die Kante ``C->D`` und den Tag
``(Tag1, A)`` und benennt ``E`` in ``E2`` um. Erwartung:

* Elemente 4/6 = 66,67 % (E und F fehlen, E2 ist zusaetzlich)
* Kanten   2/3 = 66,67 %
* Pakete   2/2 = 100,00 %
* Tags     (0,5 + 1 + 1 + 1 + 0 + 0)/6 = 58,33 %
* Gesamt   0,45*66,67 + 0,30*66,67 + 0,15*100 + 0,10*58,33 = 70,84 %

Die Tags des umbenannten Elements ``E`` zaehlen als 0: das Element selbst ist
im Element-Schluessel verloren, seine Tags duerfen nicht als Teiltreffer
durchrutschen. ``E2`` ist ein Zusatz und geht nicht in die Tag-Quote ein.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import roundtrip_metrics
from roundtrip_metrics import (
    bericht,
    lade_modell,
    main,
    render_json,
    render_markdown,
    vergleiche,
)

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
MASC = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"
TOLERANZ = 0.1

SCHEMA = (
    'CREATE TABLE "t_package" ("Package_ID" INTEGER PRIMARY KEY, "Name" TEXT, '
    '"Parent_ID" INTEGER, "ea_guid" TEXT)',
    'CREATE TABLE "t_object" ("Object_ID" INTEGER PRIMARY KEY, "Object_Type" TEXT, '
    '"Name" TEXT, "Package_ID" INTEGER, "Stereotype" TEXT, "Alias" TEXT, '
    '"Status" TEXT, "Note" TEXT, "ea_guid" TEXT)',
    'CREATE TABLE "t_connector" ("Connector_ID" INTEGER PRIMARY KEY, "Name" TEXT, '
    '"Connector_Type" TEXT, "Stereotype" TEXT, "Start_Object_ID" INTEGER, '
    '"End_Object_ID" INTEGER, "ea_guid" TEXT)',
    'CREATE TABLE "t_objectproperties" ("PropertyID" INTEGER PRIMARY KEY, '
    '"Object_ID" INTEGER, "Property" TEXT, "Value" TEXT)',
    'CREATE TABLE "t_connectortag" ("PropertyID" INTEGER PRIMARY KEY, '
    '"ElementID" INTEGER, "Property" TEXT, "VALUE" TEXT)',
    'CREATE TABLE "t_xref" ("XrefID" TEXT PRIMARY KEY, "Name" TEXT, "Type" TEXT, '
    '"Description" TEXT, "Client" TEXT)',
    'CREATE TABLE "t_diagram" ("Diagram_ID" INTEGER PRIMARY KEY, "Name" TEXT)',
    'CREATE TABLE "t_diagramobjects" ("Diagram_ID" INTEGER, "Object_ID" INTEGER)',
    'CREATE TABLE "t_diagramlinks" ("DiagramID" INTEGER, "ConnectorID" INTEGER)',
    'CREATE TABLE "t_attribute" ("ID" INTEGER PRIMARY KEY, "Object_ID" INTEGER, '
    '"Name" TEXT)',
)

PAKETE = ((1, "Root", None), (2, "P1", 1))
ELEMENTE = ((10, "A"), (11, "B"), (12, "C"), (13, "D"), (14, "E"), (15, "F"))
# (Connector_ID, Start, Ende, Connector_Type, Stereotype)
KANTEN = (
    (1, 10, 11, "Dependency", ""),
    (2, 12, 13, "Realisation", "realize"),
    (3, 10, 12, "Dependency", ""),
)
# Paketspiegel in t_object: zaehlt bewusst nicht als Element.
SPIEGEL = (20, "P1", "Package", 1)


def _guid(nummer: int) -> str:
    return f"{{00000000-0000-0000-0000-{nummer:012d}}}"


def baue_qea(
    pfad: Path,
    *,
    ohne_element: int | None = None,
    ohne_kante: int | None = None,
    ohne_tag: tuple[int, str] | None = None,
    umbenannt: tuple[int, str] | None = None,
    tag_als_null: bool = False,
    mit_spiegel: bool = True,
) -> Path:
    """Schreibt ein kleines, deterministisches Modell als .qea."""
    con = sqlite3.connect(pfad)
    try:
        for ddl in SCHEMA:
            con.execute(ddl)
        con.executemany('INSERT INTO "t_package" VALUES (?, ?, ?, ?)',
                        [(pid, name, parent, _guid(pid)) for pid, name, parent in PAKETE])
        objekte = []
        for oid, name in ELEMENTE:
            if oid == ohne_element:
                continue
            if umbenannt is not None and oid == umbenannt[0]:
                name = umbenannt[1]
            objekte.append((oid, "Class", name, 2, "Class", None, "Standard", None, _guid(oid)))
        if mit_spiegel:
            spiegel_id, spiegel_name, spiegel_typ, spiegel_pkg = SPIEGEL
            objekte.append(
                (spiegel_id, spiegel_typ, spiegel_name, spiegel_pkg,
                 None, None, None, None, _guid(spiegel_id))
            )
        con.executemany('INSERT INTO "t_object" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', objekte)
        kanten = [
            (cid, None, typ, stereo, start, ende, _guid(100 + cid))
            for cid, start, ende, typ, stereo in KANTEN
            if cid != ohne_kante
        ]
        con.executemany('INSERT INTO "t_connector" VALUES (?, ?, ?, ?, ?, ?, ?)', kanten)
        tags = []
        nummer = 0
        for oid, name in ELEMENTE:
            if oid == ohne_element:
                continue
            for prop, wert in (("Tag1", name), ("Tag2", "fest")):
                if ohne_tag is not None and (oid, prop) == ohne_tag:
                    continue
                nummer += 1
                if tag_als_null and prop == "Tag2":
                    tags.append((nummer, oid, prop, None))
                else:
                    tags.append((nummer, oid, prop, wert))
        con.executemany('INSERT INTO "t_objectproperties" VALUES (?, ?, ?, ?)', tags)
        con.execute('INSERT INTO "t_diagram" VALUES (1, "Uebersicht")')
        con.execute('INSERT INTO "t_diagramobjects" VALUES (1, 10)')
        con.execute('INSERT INTO "t_attribute" VALUES (1, 10, "attribut")')
        con.commit()
    finally:
        con.close()
    return pfad


@pytest.fixture()
def original(tmp_path: Path) -> Path:
    return baue_qea(tmp_path / "original.qea")


@pytest.fixture()
def kopie(tmp_path: Path) -> Path:
    return baue_qea(tmp_path / "kopie.qea")


@pytest.fixture()
def veraendert(tmp_path: Path) -> Path:
    return baue_qea(
        tmp_path / "veraendert.qea",
        ohne_element=15,
        ohne_kante=2,
        ohne_tag=(10, "Tag1"),
        umbenannt=(14, "E2"),
    )


# ---------------------------------------------------------------------------
# Identische Dateien
# ---------------------------------------------------------------------------


def test_identische_datei_ergibt_100_prozent(original: Path, kopie: Path) -> None:
    ergebnis = bericht(original, kopie)
    assert ergebnis["gesamtquote"] == pytest.approx(100.0, abs=TOLERANZ)
    for dimension in ("elemente", "kanten", "pakete", "tags"):
        assert ergebnis["treffer"][dimension]["quote"] == pytest.approx(100.0, abs=TOLERANZ)
    assert ergebnis["top_fehlend"] == {"elemente": [], "kanten": []}
    assert ergebnis["treffer"]["elemente"]["fehlend"] == []
    assert ergebnis["treffer"]["elemente"]["extra"] == []


def test_kennzahlen_und_paketspiegel(original: Path, kopie: Path) -> None:
    ergebnis = bericht(original, kopie)
    kennzahlen = ergebnis["original"]["kennzahlen"]
    assert kennzahlen["elemente"] == 6, "Paketspiegel darf nicht als Element zaehlen"
    assert kennzahlen["elemente_gesamt"] == 7, "Rohzahl t_object bleibt sichtbar"
    assert kennzahlen["kanten"] == 3
    assert kennzahlen["pakete"] == 2
    assert kennzahlen["tags"] == 12
    assert kennzahlen["sichten"] == 1
    assert kennzahlen["attribute"] == 1
    assert ergebnis["original"]["datei"] == "original.qea"
    assert re.fullmatch(r"[0-9a-f]{64}", ergebnis["original"]["sha256"])


def test_bericht_hat_die_geforderten_felder(original: Path, veraendert: Path) -> None:
    ergebnis = bericht(original, veraendert)
    assert set(ergebnis) == {
        "format_version", "original", "neu", "treffer", "gesamtquote", "top_fehlend"
    }
    assert set(ergebnis["original"]) == {"datei", "sha256", "kennzahlen"}
    assert set(ergebnis["treffer"]) == {"elemente", "kanten", "pakete", "tags"}
    for dimension in ("elemente", "kanten", "pakete"):
        assert {"matched", "fehlend", "extra", "quote"} <= set(ergebnis["treffer"][dimension])
    assert set(ergebnis["top_fehlend"]) == {"elemente", "kanten"}
    assert len(ergebnis["top_fehlend"]["elemente"]) <= 20
    assert len(ergebnis["top_fehlend"]["kanten"]) <= 20
    assert 0.0 <= ergebnis["gesamtquote"] <= 100.0
    json.loads(render_json(ergebnis))


# ---------------------------------------------------------------------------
# Gezielt veraenderter Rueckbau
# ---------------------------------------------------------------------------


def test_veraenderter_rueckbau_trifft_die_erwarteten_quoten(
    original: Path, veraendert: Path
) -> None:
    ergebnis = bericht(original, veraendert)
    treffer = ergebnis["treffer"]

    assert treffer["elemente"]["matched"] == 4
    assert treffer["elemente"]["quote"] == pytest.approx(66.67, abs=TOLERANZ)
    assert treffer["elemente"]["fehlend_gesamt"] == 2
    assert treffer["elemente"]["extra_gesamt"] == 1
    assert any("E" in eintrag and "E2" not in eintrag for eintrag in treffer["elemente"]["fehlend"])
    assert any("F" in eintrag for eintrag in treffer["elemente"]["fehlend"])
    assert any("E2" in eintrag for eintrag in treffer["elemente"]["extra"])

    assert treffer["kanten"]["matched"] == 2
    assert treffer["kanten"]["quote"] == pytest.approx(66.67, abs=TOLERANZ)
    assert treffer["kanten"]["fehlend_gesamt"] == 1
    assert any("C -> D" in eintrag for eintrag in treffer["kanten"]["fehlend"])

    assert treffer["pakete"]["matched"] == 2
    assert treffer["pakete"]["quote"] == pytest.approx(100.0, abs=TOLERANZ)

    assert treffer["tags"]["geprueft"] == 6
    assert treffer["tags"]["matched"] == 3
    assert treffer["tags"]["quote"] == pytest.approx(58.33, abs=TOLERANZ)

    assert ergebnis["gesamtquote"] == pytest.approx(70.84, abs=TOLERANZ)


def test_umbenanntes_element_wird_als_fehlend_und_extra_gemeldet(
    original: Path, veraendert: Path
) -> None:
    treffer = bericht(original, veraendert)["treffer"]
    fehlend = " ".join(treffer["elemente"]["fehlend"])
    extra = " ".join(treffer["elemente"]["extra"])
    assert "| E |" in fehlend
    assert "| E2 |" in extra
    assert "| E |" not in extra


def test_variante_ohne_paketpfad_erkennt_verschmelzung(tmp_path: Path) -> None:
    links = baue_qea(tmp_path / "links.qea")
    rechts = baue_qea(tmp_path / "rechts.qea", ohne_element=15)
    # Element F zusaetzlich in ein anderes Paket haengen: mit Pfad fehlt es,
    # ohne Pfad ist es weiterhin vorhanden.
    con = sqlite3.connect(rechts)
    try:
        con.execute('INSERT INTO "t_package" VALUES (3, "P2", 1, ?)', (_guid(3),))
        con.execute('UPDATE "t_object" SET "Package_ID" = 3 WHERE "Object_ID" = 14')
        con.commit()
    finally:
        con.close()

    ergebnis = bericht(links, rechts)
    elemente = ergebnis["treffer"]["elemente"]
    assert elemente["matched"] == 4
    assert elemente["ohne_pfad"]["matched"] == 5
    assert elemente["ohne_pfad"]["quote"] > elemente["quote"]


def test_fehlende_elemente_zaehlen_als_null_nicht_als_teiltreffer(tmp_path: Path) -> None:
    links = baue_qea(tmp_path / "links.qea")
    rechts = baue_qea(tmp_path / "rechts.qea", ohne_element=15)
    elemente = bericht(links, rechts)["treffer"]["elemente"]
    # F ist komplett weg: 5/6, kein Teiltreffer fuer die verlorenen Tags.
    assert elemente["matched"] == 5
    assert elemente["quote"] == pytest.approx(83.33, abs=TOLERANZ)
    tags = bericht(links, rechts)["treffer"]["tags"]
    assert tags["quote"] == pytest.approx(83.33, abs=TOLERANZ)


def test_leere_tag_werte_gelten_als_leer(tmp_path: Path) -> None:
    mit_null = baue_qea(tmp_path / "mit_null.qea", tag_als_null=True)
    mit_wert = baue_qea(tmp_path / "mit_wert.qea")
    # Original: (Tag2, NULL) -> "", Rueckbau: (Tag2, "fest") -> echter Wert.
    assert bericht(mit_null, mit_wert)["treffer"]["tags"]["quote"] < 100.0

    # NULL und leerer String sind dagegen gleichwertig: beide werden zu "".
    leerer_string = baue_qea(tmp_path / "leer.qea")
    con = sqlite3.connect(leerer_string)
    try:
        con.execute('UPDATE "t_objectproperties" SET "Value" = \'\' WHERE "Property" = \'Tag2\'')
        con.commit()
    finally:
        con.close()
    assert bericht(mit_null, leerer_string)["treffer"]["tags"]["quote"] == pytest.approx(
        100.0, abs=TOLERANZ
    )


def test_tag_jaccard_je_element(tmp_path: Path) -> None:
    links = baue_qea(tmp_path / "links.qea")
    rechts = baue_qea(tmp_path / "rechts.qea", ohne_tag=(10, "Tag1"))
    treffer = bericht(links, rechts)["treffer"]["tags"]
    # Ein Element verliert einen von zwei Tags: 5*1,0 + 0,5 = 5,5/6.
    assert treffer["quote"] == pytest.approx(91.67, abs=TOLERANZ)
    assert treffer["matched"] == 5


def test_schluessel_werden_normalisiert(tmp_path: Path) -> None:
    links = baue_qea(tmp_path / "links.qea")
    rechts = baue_qea(tmp_path / "rechts.qea")
    # Zerlegtes "u + Trema" und Aussenabstand im Rueckbau: gilt als identisch.
    con = sqlite3.connect(rechts)
    try:
        con.execute(
            'UPDATE "t_object" SET "Name" = ? WHERE "Object_ID" = 10', ("  Gru\u0308n  ",)
        )
        con.commit()
    finally:
        con.close()
    con = sqlite3.connect(links)
    try:
        con.execute('UPDATE "t_object" SET "Name" = ? WHERE "Object_ID" = 10', ("Gr\u00fcn",))
        con.commit()
    finally:
        con.close()
    treffer = bericht(links, rechts)["treffer"]["elemente"]
    assert treffer["matched"] == 6
    assert treffer["quote"] == pytest.approx(100.0, abs=TOLERANZ)


def test_mehrfach_vorkommen_zaehlen_als_multimenge(tmp_path: Path) -> None:
    links = baue_qea(tmp_path / "links.qea")
    rechts = baue_qea(tmp_path / "rechts.qea")
    # Ein zweites Element mit identischem Schluessel (gleicher Pfad, Name, Stereotyp).
    con = sqlite3.connect(links)
    try:
        con.execute(
            'INSERT INTO "t_object" VALUES (16, "Class", "F", 2, "Class", NULL, NULL, NULL, ?)',
            (_guid(16),),
        )
        con.commit()
    finally:
        con.close()
    # Im Rueckbau fehlt eine der beiden Vorkommnnisse von "F": die Zeile 15
    # ist weg, die inhaltsgleiche Zeile 16 bleibt.
    con = sqlite3.connect(rechts)
    try:
        con.execute('DELETE FROM "t_object" WHERE "Object_ID" = 15')
        con.execute(
            'INSERT INTO "t_object" VALUES (16, "Class", "F", 2, "Class", NULL, NULL, NULL, ?)',
            (_guid(16),),
        )
        con.commit()
    finally:
        con.close()
    elemente = bericht(links, rechts)["treffer"]["elemente"]
    assert elemente["matched"] == 6
    assert elemente["fehlend_gesamt"] == 1, "nur die zweite Vorkommnis fehlt"
    assert elemente["quote"] == pytest.approx(85.71, abs=TOLERANZ)


# ---------------------------------------------------------------------------
# Determinismus und Ausgabeformate
# ---------------------------------------------------------------------------


def test_zwei_laeufe_ergeben_identische_json_bytes(original: Path, veraendert: Path) -> None:
    erster = render_json(bericht(original, veraendert))
    zweiter = render_json(bericht(original, veraendert))
    assert erster == zweiter
    assert erster.encode("utf-8") == zweiter.encode("utf-8")


def test_ausgabe_enthaelt_keinen_zeitstempel(original: Path, veraendert: Path) -> None:
    daten = bericht(original, veraendert)
    text = render_json(daten) + render_markdown(daten)
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)
    assert "timestamp" not in text.lower()


def test_markdown_nennt_alle_dimensionen(original: Path, veraendert: Path) -> None:
    text = render_markdown(bericht(original, veraendert))
    for wort in ("Gesamtquote", "Elemente", "Kanten", "Pakete", "Tags", "70.84"):
        assert wort in text
    assert text.count("|") > 20


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_schreibt_json_und_markdown(original: Path, veraendert: Path, tmp_path: Path) -> None:
    json_pfad = tmp_path / "bericht.json"
    md_pfad = tmp_path / "bericht.md"
    code = main([str(original), str(veraendert), "--json", str(json_pfad), "--md", str(md_pfad)])
    assert code == 0
    daten = json.loads(json_pfad.read_text(encoding="utf-8"))
    assert daten["gesamtquote"] == pytest.approx(70.84, abs=TOLERANZ)
    assert "Gesamtquote" in md_pfad.read_text(encoding="utf-8")


def test_cli_exitcode_2_bei_fehlender_datei(original: Path, tmp_path: Path, capsys) -> None:
    code = main([str(original), str(tmp_path / "gibtsnicht.qea")])
    assert code == 2
    fehler = capsys.readouterr().err
    assert "roundtrip_metrics:" in fehler
    assert "gibtsnicht.qea" in fehler


def test_cli_exitcode_2_bei_kaputter_datei(original: Path, tmp_path: Path, capsys) -> None:
    kaputt = tmp_path / "kaputt.qea"
    kaputt.write_bytes(b"das ist keine sqlite-datei")
    code = main([str(original), str(kaputt)])
    assert code == 2
    assert "roundtrip_metrics:" in capsys.readouterr().err


def test_cli_als_skript_aufrufbar(original: Path, veraendert: Path, tmp_path: Path) -> None:
    json_pfad = tmp_path / "bericht.json"
    ergebnis = subprocess.run(
        [sys.executable, str(ROOT / "roundtrip_metrics.py"), str(original), str(veraendert),
         "--json", str(json_pfad)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Roundtrip-Treue: 70.84 %" in ergebnis.stdout
    assert json_pfad.exists()


# ---------------------------------------------------------------------------
# Echtes Referenzmodell (nur lesen, nur gegen sich selbst)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not MASC.exists(), reason="Fixture Musterarchitektur_MASC.qea fehlt lokal")
def test_masc_gegen_sich_selbst_ist_100_prozent() -> None:
    ergebnis = bericht(MASC, MASC)
    assert ergebnis["gesamtquote"] == pytest.approx(100.0, abs=TOLERANZ)
    for dimension in ("elemente", "kanten", "pakete", "tags"):
        assert ergebnis["treffer"][dimension]["quote"] == pytest.approx(100.0, abs=TOLERANZ)
    kennzahlen = ergebnis["original"]["kennzahlen"]
    assert kennzahlen["elemente_gesamt"] == 1655
    assert kennzahlen["kanten"] == 1747
    assert kennzahlen["pakete"] == 226
    assert kennzahlen["tags"] == 9237
    assert kennzahlen["sichten"] == 265
    assert kennzahlen["attribute"] == 59


@pytest.mark.skipif(not MASC.exists(), reason="Fixture Musterarchitektur_MASC.qea fehlt lokal")
def test_masc_modell_bleibt_unveraendert() -> None:
    """Der Vergleich darf die Fixture nicht anfassen (nur lesen)."""
    vorher = MASC.stat().st_size
    modell = lade_modell(MASC)
    assert len(modell.elemente) == modell.kennzahlen["elemente"]
    vergleiche(modell, modell)
    assert MASC.stat().st_size == vorher
