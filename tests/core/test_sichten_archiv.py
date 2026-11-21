"""Sichten-Archiv: Auslagern und Zurueckspielen muss verlustfrei sein.

Abnahme
-------
* Stufe A entfernt Sichtzeilen, laesst die Tabellen aber vorhanden (AAroN).
* Die Zieldatei ist kleiner als die Quelle.
* Zurueckspielen stellt jede Sichtzeile wieder her -- Hash ueber die Zeilenmenge
  vor und nach dem Rundlauf ist identisch.
* Alle uebrigen Tabellen behalten ihre Zeilenzahl.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

import sichten_archiv

FIXTURE = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures" / "Musterarchitektur_MASC.qea"

SICHT_TABELLEN = ("t_diagram", "t_diagramobjects", "t_diagramlinks", "t_image")


def _zeilenzahlen(pfad: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    try:
        tabellen = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tabellen
        }
    finally:
        conn.close()


@pytest.mark.skipif(not FIXTURE.is_file(), reason="Musterarchitektur fehlt")
def test_archivieren_und_zurueckspielen_ist_verlustfrei(tmp_path: Path) -> None:
    quelle = tmp_path / "quelle.qea"
    shutil.copy2(FIXTURE, quelle)

    archiv = tmp_path / "sichten.archiv"
    ohne_sichten = tmp_path / "ohne_sichten.qea"

    bericht = sichten_archiv.archiviere(quelle, archiv, ohne_sichten, stufe="A")

    # Die Quelldatei bleibt unangetastet.
    assert _zeilenzahlen(quelle)["t_diagram"] > 0

    # Tabellen bleiben vorhanden, sind aber leer.
    assert all(bericht["ziel_tabellen_vorhanden"].values())
    assert all(anzahl == 0 for anzahl in bericht["ziel_zeilen"].values())

    # Kleiner muss sie sein, und zwar spuerbar.
    assert bericht["ziel_bytes"] < bericht["quelle_bytes"]
    assert bericht["ersparnis_prozent"] > 10

    # Zurueckspielen: Zeilenweise identisch.
    wiederhergestellt = tmp_path / "wiederhergestellt.qea"
    rueckgabe = sichten_archiv.zurueckspielen(ohne_sichten, archiv, wiederhergestellt)
    assert rueckgabe["identisch"] is True
    for tabelle in SICHT_TABELLEN:
        assert rueckgabe["pruefsummen"][tabelle]["gleich"] is True

    # Keine andere Tabelle hat Zeilen verloren.
    vorher = _zeilenzahlen(quelle)
    nachher = _zeilenzahlen(wiederhergestellt)
    unterschiede = {
        name: (vorher[name], nachher.get(name))
        for name in vorher
        if vorher[name] != nachher.get(name)
    }
    assert unterschiede == {}


@pytest.mark.skipif(not FIXTURE.is_file(), reason="Musterarchitektur fehlt")
def test_archiv_pruefen_meldet_ok(tmp_path: Path) -> None:
    quelle = tmp_path / "quelle.qea"
    shutil.copy2(FIXTURE, quelle)
    archiv = tmp_path / "sichten.archiv"
    sichten_archiv.archiviere(quelle, archiv, None, stufe="A")
    bericht = sichten_archiv.pruefe(archiv)
    assert bericht["ok"] is True


def test_unbekannte_stufe_wird_abgelehnt(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        sichten_archiv.archiviere(tmp_path / "fehlt.qea", tmp_path / "a", None, stufe="C")
