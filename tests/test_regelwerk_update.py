"""Regelwerk-Wächter: Quellenabgleich, PII-Neutralisierung, Stand-Eintrag.

Die Tests sind hermetisch (kein Netz). Festgehalten wird der Fehler, den die
erste Einlagerung zeigte: die amtliche MDG enthält eine Absenderadresse; ohne
Neutralisierung käme sie ins Repository. Der Neutralwert bleibt
`support@example.invalid` — genau wie in der bereits eingelagerten Fassung.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKRIPT = ROOT / "scripts" / "regelwerk_update.py"


def _modul():
    spec = importlib.util.spec_from_file_location("regelwerk_update", SKRIPT)
    assert spec and spec.loader
    modul = importlib.util.module_from_spec(spec)
    sys.modules["regelwerk_update"] = modul
    spec.loader.exec_module(modul)
    return modul


SEITE = """
<html><body>
<a href="/resource/blob/5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip">MDG</a>
<a href="/resource/blob/6117920/173e5ae1cba4a5fca196742440899a79/release-notes-admbw--data.pdf">Notizen</a>
</body></html>
"""


def test_blobs_werden_nach_ressourcennamen_gesammelt() -> None:
    m = _modul()
    blobs = m.finde_blobs(SEITE)
    assert blobs["admbw-mdg-nafv4--data.zip"] == (
        "5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip"
    )
    assert len(blobs) == 2


def test_pii_wird_neutralisiert_wie_in_der_eingelagerten_fassung() -> None:
    m = _modul()
    amtlich = (
        b'<?xml version="1.0" encoding="windows-1252"?>\r\n'
        b'<MDG.Technology><Documentation name="NAFv4-ADMBw"'
        b' version="2026.05" notes="absender@dienststelle.example.org">'
    )
    bereinigt, anzahl = m.neutralisiere(amtlich)
    assert anzahl == 1
    assert b"dienststelle.example.org" not in bereinigt
    assert b"support@example.invalid" in bereinigt
    # Zeichen und Zeilenenden bleiben unangetastet (windows-1252, CRLF).
    assert bereinigt.count(b"\r\n") == amtlich.count(b"\r\n")


def test_neutralisiert_gar_nichts_wenn_keine_adresse_drinsteht() -> None:
    m = _modul()
    bereinigt, anzahl = m.neutralisiere(b"<MDG.Technology name='NAFv4'/>")
    assert anzahl == 0
    assert bereinigt == b"<MDG.Technology name='NAFv4'/>"


def test_mdg_erkennt_nur_zip_mit_mdg_im_namen() -> None:
    m = _modul()
    assert m.ist_mdg("admbw-mdg-nafv4--data.zip")
    assert not m.ist_mdg("release-notes-admbw--data.pdf")
    assert not m.ist_mdg("model-wizard-data.7z")
    assert not m.ist_mdg("grundlagen-methode-architektur-nach-nafv4--data.pdf")


def test_fetch_quelle_wird_zeilengenau_aktualisiert(tmp_path: Path, monkeypatch) -> None:
    m = _modul()
    quelle = tmp_path / "fetch_quellen.py"
    quelle.write_text(
        'DATEIEN = [\n'
        '    ("grundlagen.pdf", "5570630/aaa/grundlagen--data.pdf"),\n'
        '    ("admbw-mdg-2026.05.zip", "5570648/86b/admbw-mdg-nafv4--data.zip"),\n'
        ']\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "FETCH", quelle)
    m.trage_fetch_quelle_ein(
        "admbw-mdg-nafv4--data.zip",
        "5570648/999/admbw-mdg-nafv4--data.zip",
        "2026.11",
    )
    text = quelle.read_text(encoding="utf-8")
    assert '("admbw-mdg-2026.11.zip", "5570648/999/admbw-mdg-nafv4--data.zip")' in text
    # Die anderen Zeilen bleiben unangetastet.
    assert '("grundlagen.pdf", "5570630/aaa/grundlagen--data.pdf")' in text


def test_abgleich_findet_geaenderte_und_neue_quellen(monkeypatch) -> None:
    m = _modul()
    monkeypatch.setattr(
        m,
        "lade_seite",
        lambda: SEITE.replace("86b87446ff3b144de324f1dde2d85521", "a" * 32),
    )
    monkeypatch.setattr(
        m,
        "bekannter_stand",
        lambda: {
            "admbw-mdg-2026.05.zip": "5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip",
        },
    )
    geaendert, neu = m.vergleiche()
    assert geaendert == {
        "admbw-mdg-nafv4--data.zip": "5570648/" + "a" * 32 + "/admbw-mdg-nafv4--data.zip"
    }
    assert "release-notes-admbw--data.pdf" in neu


def test_abgleich_meldet_aktuellen_stand(monkeypatch) -> None:
    m = _modul()
    monkeypatch.setattr(m, "lade_seite", lambda: SEITE)
    monkeypatch.setattr(
        m,
        "bekannter_stand",
        lambda: {
            "admbw-mdg-2026.05.zip": "5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip",
            "release-notes.zip": "6117920/173e5ae1cba4a5fca196742440899a79/release-notes-admbw--data.pdf",
        },
    )
    geaendert, neu = m.vergleiche()
    assert geaendert == {}
    assert neu == {}