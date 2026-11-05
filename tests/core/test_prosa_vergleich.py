"""Tests fuer den Prosa-Vergleich (Quelle gegen Rueckweg)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import prosa_vergleich as pv
import qea_writer


QUELLE = """# Handbuch

## 1 Zweck

Das Fahrzeug klärt auf und wirkt nach Freigabe. Es gibt zwölf Plätze.

## 2 Aufbau

Der Rumpf trägt die Sensoren. Die Versorgung ist doppelt ausgelegt.
"""

RUECK = """# Handbuch

## 1 Zweck

Das Fahrzeug klärt auf und wirkt nach Freigabe. Es gibt zwölf Plätze.

## 2 Aufbau

Der Rumpf trägt die Sensoren.
"""


def test_umfang_und_satzlaenge() -> None:
    werte = pv.kennzahlen(RUECK)
    assert werte["zeichen"] == len(RUECK)
    assert werte["absaetze"] >= 4
    assert werte["ueberschriften"] == 2
    assert werte["mittlere_satzlaenge"] > 0


def test_kapitel_werden_zugeordnet() -> None:
    kapitel = pv.kapitel(QUELLE)
    assert list(kapitel) == ["1 Zweck", "2 Aufbau"]
    assert "zwölf" in kapitel["1 Zweck"]


def test_jaccard_erkennt_teilverlust() -> None:
    bericht = pv.vergleiche(QUELLE, RUECK)
    assert bericht["kapitel"]["gemeinsam"] == 2
    assert bericht["kapitel"]["jaccard"]["1 Zweck"] == 1.0
    assert bericht["kapitel"]["jaccard"]["2 Aufbau"] < 1.0
    assert bericht["kapitel"]["mittel"] < 1.0


def test_zahlen_werden_gegenuebergestellt() -> None:
    bericht = pv.vergleiche(QUELLE + "\nDie Laufzeit beträgt 41 Tage.\n", RUECK)
    assert "41" in bericht["zahlen"]["nur_in_der_quelle"]


def test_bezeichnungen_aus_dem_modell(tmp_path: Path) -> None:
    qea = qea_writer.write_qea(
        {
            "ir_version": 1,
            "technology": {"profile": ""},
            "packages": [{"path": "Raumschiff"}],
            "elements": [
                {"package": "Raumschiff", "name": "Rumpf", "stereotype": "ActualResource"},
                {"package": "Raumschiff", "name": "Versorgung", "stereotype": "ActualResource"},
                {"package": "Raumschiff", "name": "Sensor", "stereotype": "ActualResource"},
            ],
            "connectors": [],
        },
        tmp_path / "modell.qea",
    )
    bericht = pv.vergleiche(QUELLE, RUECK, qea)
    assert bericht["bezeichnungen"]["gesamt"] == 3
    assert bericht["bezeichnungen"]["genannt"] == 2
    assert bericht["bezeichnungen"]["quote"] == 66.7
    assert bericht["bezeichnungen"]["fehlend"] == ["Versorgung"]


def test_ueberschrift_beginnt_keinen_satz() -> None:
    """Eine Ueberschrift darf nicht mit dem folgenden Absatz verkleben.

    Vorher wurde der ganze Text zu einer Zeile verflacht; aus
    ``## Die Dienste`` und dem Satz darunter entstand ein Satz, den der
    Rueckweg nie wortgleich treffen konnte.
    """
    text = (
        "## 4 Die Dienste\n\n"
        "Der Spacecraft Information Service stellt seine Funktionalitaeten der Besatzung bereit.\n"
    )
    assert pv._saetze(text) == [
        "Der Spacecraft Information Service stellt seine Funktionalitaeten der Besatzung bereit."
    ]


def test_markdown_enthaelt_die_kernaussagen() -> None:
    text = pv.als_markdown(pv.vergleiche(QUELLE, RUECK))
    assert "# Prosa-Vergleich" in text
    assert "| Zeichen |" in text
    assert "## Kapitel" in text


def test_cli_schreibt_berichte(tmp_path: Path) -> None:
    quelle = tmp_path / "quelle.md"
    zurueck = tmp_path / "zurueck.md"
    quelle.write_text(QUELLE, encoding="utf-8")
    zurueck.write_text(RUECK, encoding="utf-8")
    md, js = tmp_path / "b.md", tmp_path / "b.json"

    code = pv.main([str(quelle), str(zurueck), "--md", str(md), "--json", str(js)])

    assert code == 0
    assert md.is_file() and js.is_file()
    daten = json.loads(js.read_text(encoding="utf-8"))
    assert daten["kapitel"]["gemeinsam"] == 2
