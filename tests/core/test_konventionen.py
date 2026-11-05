"""Waechter fuer die bereinigten Modellierungskonventionen.

Die Datei ``knowledge/leitfaden/konventionen.json`` speist die KI-Prompts.
Wenn dort Tabellen- und Abbildungstext aus dem Leitfaden-PDF landet, zitiert
das Modell fremde Inhalte und der Prompt waechst. Diese Tests halten den
bereinigten Stand fest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]
DATEI = WURZEL / "knowledge" / "leitfaden" / "konventionen.json"

#: Ueberschriften, die auf mitkopierten Tabellen- oder Abbildungstext hindeuten.
CAPTION = re.compile(r"\b(?:Tabelle|Abbildung)\s+\d+\s*:")
TABELLENKOPF = re.compile(r"Modellierungskonventionen\s+Nummer\s+Modellierungskonvention")
MK_KENNUNG = re.compile(r"\b([A-Z]{1,2}\d+(?:-[A-Z]\d+)?)-MK\d+\b")

MAX_ZEICHEN = 800


@pytest.fixture(scope="module")
def konventionen() -> list[dict]:
    assert DATEI.is_file(), f"fehlt: {DATEI}"
    return json.loads(DATEI.read_text(encoding="utf-8"))


def test_aufbau_vollstaendig(konventionen: list[dict]) -> None:
    assert len(konventionen) == 303
    for eintrag in konventionen:
        assert set(eintrag) >= {"id", "viewpoint", "kind", "text"}, eintrag
        assert eintrag["id"].strip(), eintrag
        assert eintrag["text"].strip(), f"leerer Text: {eintrag['id']}"


def test_kennungen_eindeutig(konventionen: list[dict]) -> None:
    kennungen = [e["id"] for e in konventionen]
    doppelt = {k for k in kennungen if kennungen.count(k) > 1}
    assert not doppelt, f"doppelte Kennungen: {sorted(doppelt)}"


def test_kein_tabellen_oder_abbildungstext(konventionen: list[dict]) -> None:
    befunde = [e["id"] for e in konventionen if CAPTION.search(e["text"])]
    assert not befunde, f"Tabellen-/Abbildungstext in: {befunde}"


def test_kein_tabellenkopf_im_text(konventionen: list[dict]) -> None:
    befunde = [e["id"] for e in konventionen if TABELLENKOPF.search(e["text"])]
    assert not befunde, f"Tabellenkopf in: {befunde}"


def test_keine_fremden_kennungen(konventionen: list[dict]) -> None:
    """Ein Eintrag darf nur seine eigene MK-Kennung zitieren."""
    befunde: dict[str, list[str]] = {}
    for eintrag in konventionen:
        fremd = {
            m.group(0) for m in MK_KENNUNG.finditer(eintrag["text"])
            if m.group(0) != eintrag["id"]
        }
        if fremd:
            befunde[eintrag["id"]] = sorted(fremd)
    assert not befunde, f"fremde Kennungen: {befunde}"


def test_laenge_bleibt_im_rahmen(konventionen: list[dict]) -> None:
    """Ein Eintrag ist eine Konvention, kein Kapitel."""
    zu_lang = [(e["id"], len(e["text"])) for e in konventionen if len(e["text"]) > MAX_ZEICHEN]
    assert not zu_lang, f"ueber {MAX_ZEICHEN} Zeichen: {zu_lang}"


def test_bereinigung_ist_wiederholbar(konventionen: list[dict]) -> None:
    """Zweimal bereinigen darf nichts mehr aendern (Idempotenz)."""
    import importlib.util

    pfad = WURZEL / "scripts" / "clean_konventionen.py"
    spec = importlib.util.spec_from_file_location("clean_konventionen", pfad)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    for eintrag in konventionen:
        assert modul.bereinige_text(eintrag["text"]) == eintrag["text"], eintrag["id"]
