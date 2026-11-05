"""Tests für den Handbuch-Generator.

Der Generator ist vorhabensneutral: Er kennt kein einzelnes System, sondern
liest Bezeichnungen, Notizen und Verbindungen aus einer beliebigen Ablage.
Die Tests prüfen deshalb den Vertrag, nicht einen bestimmten Wortlaut:

* zehn Kapitel, erzählende Absätze, keine Rohdaten im Haupttext,
* jede Bezeichnung des Vorhabens kommt vor,
* keine Herkunftsbegriffe im erzählenden Teil,
* gleiche Eingabe ergibt Byte für Byte dasselbe Ergebnis,
* ein fremdes Vorhaben erbt keine Fachbegriffe aus dem Code.
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import handbuch_generator as hg

HIER = Path(__file__).resolve().parents[2] / 'packages' / 'core' / 'fixtures'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
WURZEL = HIER.parent
MASC = WURZEL / "fixtures" / "Musterarchitektur_MASC.qea"


def _kleines_modell(pfad: Path, *, paket: str = "Prüfvorhaben") -> Path:
    """Baut eine winzige Ablage mit drei Elementen und einer Verbindung."""
    with sqlite3.connect(pfad) as con:
        con.executescript(
            """
            create table t_package (Package_ID integer primary key, Name text,
                Parent_ID integer, ea_guid text, Notes text, tpos integer);
            create table t_object (Object_ID integer primary key, Object_Type text,
                Name text, Note text, Stereotype text, ea_guid text, Package_ID integer);
            create table t_connector (Connector_ID integer primary key, Name text,
                Connector_Type text, Stereotype text, Start_Object_ID integer,
                End_Object_ID integer, ea_guid text, Direction text);
            """
        )
        con.execute("insert into t_package values (1, ?, 0, '{P1}', '', 0)", (paket,))
        zeilen = [
            (1, "Class", "Leitstelle", "Nimmt Meldungen an und gibt Aufträge weiter.",
             "ActualResource", "{O1}", 1),
            (2, "Class", "Auswertung", "Verdichtet Meldungen zu einem Lagebild.",
             "ActualService", "{O2}", 1),
            (3, "Class", "Bericht", "Hält das Ergebnis für die Freigabe fest.",
             "Requirement", "{O3}", 1),
        ]
        con.executemany("insert into t_object values (?,?,?,?,?,?,?)", zeilen)
        con.execute(
            "insert into t_connector values (1, 'meldet an', 'Dependency',"
            " 'ServiceDependency', 1, 2, '{K1}', 'Source -> Destination')"
        )
        con.commit()
    return pfad


@pytest.fixture()
def klein(tmp_path: Path) -> Path:
    return _kleines_modell(tmp_path / "klein.qea")


def test_handbuch_hat_zehn_kapitel(klein: Path, tmp_path: Path) -> None:
    ziel = tmp_path / "handbuch.md"
    kennzahlen = hg.generate_handbook(klein, ziel)
    text = ziel.read_text(encoding="utf-8")

    assert kennzahlen["kapitel"] == 10
    for nummer, titel in enumerate(hg.KAPITEL, start=1):
        assert f"## {nummer} {titel}" in text


def test_jede_bezeichnung_kommt_vor(klein: Path, tmp_path: Path) -> None:
    ziel = tmp_path / "handbuch.md"
    kennzahlen = hg.generate_handbook(klein, ziel)
    text = ziel.read_text(encoding="utf-8")

    assert kennzahlen["genannt"] == kennzahlen["bezeichnungen"] == 3
    for name in ("Leitstelle", "Auswertung", "Bericht"):
        assert name in text


def test_notizen_werden_zitiert(klein: Path, tmp_path: Path) -> None:
    ziel = tmp_path / "handbuch.md"
    hg.generate_handbook(klein, ziel)
    text = ziel.read_text(encoding="utf-8")

    assert "Nimmt Meldungen an und gibt Aufträge weiter." in text
    assert "Verdichtet Meldungen zu einem Lagebild." in text


def test_verbindungen_werden_erzaehlt(klein: Path, tmp_path: Path) -> None:
    ziel = tmp_path / "handbuch.md"
    hg.generate_handbook(klein, ziel)
    text = ziel.read_text(encoding="utf-8")

    assert "Verbindungen" in text
    assert "Leitstelle" in text and "Auswertung" in text


def test_keine_herkunftsbegriffe(klein: Path, tmp_path: Path) -> None:
    ziel = tmp_path / "handbuch.md"
    hg.generate_handbook(klein, ziel)
    text = ziel.read_text(encoding="utf-8")

    assert hg.verbote_zaehlen(text) == {}
    for wort in ("Stereotyp", "GUID", "Datenbank", "Metamodell"):
        assert wort not in text


def test_waechter_bricht_bei_gesperrtem_wort() -> None:
    with pytest.raises(hg.HandbuchFehler):
        hg._pruefe("Dieses Architektur-Bild ist ein Modell.")


def test_entschaerfen_ersetzt_herkunftsworte() -> None:
    assert "Vorhaben" in hg.entschaerfen("Das Modell ist fertig.")
    assert "Bestandteil" in hg.entschaerfen("Jedes Element zählt.")
    assert hg.verbote_zaehlen(hg.entschaerfen("Das Modellhafte Element im Paket")) == {}


def test_deterministisch(klein: Path, tmp_path: Path) -> None:
    eins = tmp_path / "a.md"
    zwei = tmp_path / "b.md"
    hg.generate_handbook(klein, eins)
    hg.generate_handbook(klein, zwei)
    assert hashlib.sha256(eins.read_bytes()).hexdigest() == hashlib.sha256(
        zwei.read_bytes()
    ).hexdigest()


def test_kein_erbe_aus_dem_code(tmp_path: Path) -> None:
    """Ein fremdes Vorhaben darf keine Fachbegriffe eines anderen erben."""
    quelle = _kleines_modell(tmp_path / "fremd.qea", paket="Fertigungslinie")
    ziel = tmp_path / "fremd.md"
    hg.generate_handbook(quelle, ziel)
    text = ziel.read_text(encoding="utf-8")

    for wort in ("Raumschiff", "Raumfahrzeug", "Rakete", "Besatzung", "Orbit"):
        assert wort not in text
    assert "Fertigungslinie" in text


def test_leere_ablage_wird_ehrlich_benannt(tmp_path: Path) -> None:
    pfad = tmp_path / "leer.qea"
    with sqlite3.connect(pfad) as con:
        con.executescript(
            """
            create table t_package (Package_ID integer primary key, Name text,
                Parent_ID integer, ea_guid text, Notes text, tpos integer);
            create table t_object (Object_ID integer primary key, Object_Type text,
                Name text, Note text, Stereotype text, ea_guid text, Package_ID integer);
            create table t_connector (Connector_ID integer primary key, Name text,
                Connector_Type text, Stereotype text, Start_Object_ID integer,
                End_Object_ID integer, ea_guid text, Direction text);
            """
        )
        con.execute("insert into t_package values (1, 'Leeres Vorhaben', 0, '{P}', '', 0)")
        con.commit()
    ziel = tmp_path / "leer.md"
    # Eine Ablage ohne Inhalt wird laut abgelehnt statt still ein leeres
    # Handbuch zu schreiben.
    with pytest.raises(Exception) as fehler:
        hg.generate_handbook(pfad, ziel)
    assert "keine Elemente" in str(fehler.value)
    assert not ziel.exists()


def test_quelle_fehlt(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        hg.lade_quelle(tmp_path / "gibtsnicht.qea")


def test_cli_schreibt_handbuch(klein: Path, tmp_path: Path) -> None:
    ziel = tmp_path / "cli.md"
    ergebnis = subprocess.run(
        [sys.executable, "handbuch_generator.py", str(klein), "--md", str(ziel)],
        cwd=WURZEL, capture_output=True, text=True, timeout=120,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ziel.exists()
    assert "Zeichen:" in ergebnis.stdout


def test_cli_meldet_fehlende_quelle(tmp_path: Path) -> None:
    ergebnis = subprocess.run(
        [sys.executable, "handbuch_generator.py", str(tmp_path / "weg.qea"), "--md",
         str(tmp_path / "x.md")],
        cwd=WURZEL, capture_output=True, text=True, timeout=120,
    )
    assert ergebnis.returncode == 2
    assert "nicht gefunden" in ergebnis.stderr or "Quelle" in ergebnis.stderr


@pytest.mark.skipif(not MASC.exists(), reason="Musterablage nicht vorhanden")
def test_masc_laeuft_durch(tmp_path: Path) -> None:
    """Die große Ablage ist der Härtetest: vollständig, ohne Sprachverstoß."""
    ziel = tmp_path / "masc.md"
    kennzahlen = hg.generate_handbook(MASC, ziel)
    text = ziel.read_text(encoding="utf-8")

    assert kennzahlen["kapitel"] == 10
    assert kennzahlen["verbote"] == 0
    assert kennzahlen["genannt"] == kennzahlen["bezeichnungen"]
    assert kennzahlen["bezeichnungen"] > 500
    assert hg.verbote_zaehlen(text.split("### 10.2", 1)[0]) == {}
