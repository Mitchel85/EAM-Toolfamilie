"""Waechter fuer ``knowledge/bpmn/prozess-regeln.json``.

Die Datei ist erzeugt, nicht geschrieben. Diese Tests halten fest, dass sie

* aus den echten Quellen stammt (Pruefsummen, Stereotypeliste, MDG),
* keine Stereotype erfindet,
* jede Pruefregel auf eine existierende L4-Konvention stuetzt,
* und im Code tatsaechlich umgesetzt ist.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]
DATEI = WURZEL / "knowledge" / "bpmn" / "prozess-regeln.json"
ADMBW = WURZEL / "apps" / "admbw-extractor" / "ADMBw-Stereotypes.json"
MDG = WURZEL / "packages" / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml"
KONVENTIONEN = WURZEL / "knowledge" / "leitfaden" / "konventionen.json"


@pytest.fixture(scope="module")
def regeln() -> dict:
    assert DATEI.is_file(), f"fehlt: {DATEI} -- scripts/build_bpmn_regeln.py laufen lassen"
    return json.loads(DATEI.read_text(encoding="utf-8"))


def test_aufbau(regeln: dict) -> None:
    assert set(regeln) >= {
        "schemaVersion",
        "zweck",
        "quellen",
        "l4Sicht",
        "stereotype",
        "metaconstraints",
        "elementtypen",
        "konventionen",
        "pruefregeln",
        "nichtPruefbar",
        "transformationsRegeln",
    }
    assert regeln["schemaVersion"] == "1.0"


def test_quellen_pruefsummen_stimmen(regeln: dict) -> None:
    for schluessel, eintrag in regeln["quellen"].items():
        pfad = WURZEL / eintrag["datei"]
        assert pfad.is_file(), f"{schluessel}: {pfad} fehlt"
        ist = hashlib.sha256(pfad.read_bytes()).hexdigest()
        assert ist == eintrag["sha256"], f"{schluessel}: Pruefsumme veraltet"


def test_keine_erfundenen_stereotype(regeln: dict) -> None:
    quelle = {
        eintrag["name"]: eintrag
        for eintrag in json.loads(ADMBW.read_text(encoding="utf-8"))["stereotypes"]
    }
    for name, eintrag in regeln["stereotype"].items():
        assert name in quelle, f"{name} steht nicht in ADMBw-Stereotypes.json"
        assert eintrag["appliesTo"] == list(quelle[name].get("appliesTo") or [])
        assert eintrag["abstract"] == bool(quelle[name].get("abstract"))
    for art, eintrag in regeln["elementtypen"].items():
        name = eintrag.get("admbw")
        if name is not None:
            assert name in quelle, f"{art}: {name} ist erfunden"


def test_sicherheit_ist_begruendet(regeln: dict) -> None:
    for art, eintrag in regeln["elementtypen"].items():
        assert eintrag["sicherheit"] in ("belegt", "abgeleitet", "kein-stereotyp"), art
        assert eintrag["begruendung"].strip(), art
        assert eintrag["quelle"], art
        for kid in eintrag["konventionen"]:
            assert kid in regeln["konventionen"], f"{art}: unbekannte Konvention {kid}"


def test_konventionen_sind_vollstaendig(regeln: dict) -> None:
    konventionen = regeln["konventionen"]
    assert len(konventionen) == 20
    for nummer in range(1, 21):
        kid = f"L4-MK{nummer:02d}"
        assert kid in konventionen
        assert konventionen[kid]["text"].strip()
        assert konventionen[kid]["verweis"] is not None


def test_konventionstexte_stimmen_mit_der_quelle(regeln: dict) -> None:
    quelle = {
        eintrag["id"]: eintrag
        for eintrag in json.loads(KONVENTIONEN.read_text(encoding="utf-8"))
        if eintrag.get("viewpoint") == "L4"
    }
    for kid, eintrag in regeln["konventionen"].items():
        assert eintrag["text"] == quelle[kid]["text"]


def test_metaconstraints_stimmen_mit_der_mdg(regeln: dict) -> None:
    text = MDG.read_text(encoding="utf-8", errors="replace")
    for name, grenzen in regeln["metaconstraints"].items():
        block = re.search(r'<Stereotype name="%s".*?</Stereotype>' % name, text, re.S)
        assert block is not None, name
        for rolle, werte in grenzen.items():
            treffer = re.search(
                r'<metaconstraint umlRole="%s" constraint="([^"]+)"' % rolle, block.group(0)
            )
            assert treffer, f"{name}/{rolle}"
            assert [t.strip() for t in treffer.group(1).split(";")] == werte


def test_pruefregeln_sind_wohlgeformt(regeln: dict) -> None:
    ids = [regel["id"] for regel in regeln["pruefregeln"]]
    assert len(ids) == len(set(ids)), "Regel-IDs muessen eindeutig sein"
    assert len(ids) == 15
    for regel in regeln["pruefregeln"]:
        assert regel["schwere"] in ("fehler", "warnung", "hinweis")
        assert regel["konvention"] in regeln["konventionen"]
        assert regel["konventionstext"] == regeln["konventionen"][regel["konvention"]]["text"]
        assert regel["titel"].strip()
        assert regel["beschreibung"].strip()
        assert isinstance(regel["behebbar"], bool)
        assert regel["objekt"] in (
            "modell",
            "prozess",
            "teilnehmer",
            "lane",
            "knoten",
            "aktion",
            "fluss",
            "gateway",
        )


def test_jede_regel_ist_im_code_umgesetzt(regeln: dict) -> None:
    quelltext = (WURZEL / "packages" / "bpmn" / "admbw.py").read_text(encoding="utf-8")
    for regel in regeln["pruefregeln"]:
        assert f'"{regel["id"]}"' in quelltext, f"{regel['id']} fehlt in admbw.py"


def test_nicht_pruefbare_konventionen_sind_begruendet(regeln: dict) -> None:
    assert regeln["nichtPruefbar"]
    for eintrag in regeln["nichtPruefbar"]:
        assert eintrag["konvention"] in regeln["konventionen"]
        assert eintrag["grund"].strip()


def test_transformationsregeln_verweisen_auf_pruefregeln(regeln: dict) -> None:
    ids = {regel["id"] for regel in regeln["pruefregeln"]}
    for eintrag in regeln["transformationsRegeln"]:
        assert eintrag["regel"] in ids
        assert eintrag["aktion"].strip()


def test_generator_ist_aktuell() -> None:
    ergebnis = subprocess.run(
        [sys.executable, "scripts/build_bpmn_regeln.py", "--check"],
        cwd=WURZEL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "aktuell" in ergebnis.stdout


def test_l4_sicht_entspricht_dem_regelwerk(regeln: dict) -> None:
    regelwerk = json.loads((WURZEL / "knowledge" / "regelwerk.json").read_text(encoding="utf-8"))
    sicht = regelwerk["viewpoints"]["L4"]
    assert regeln["l4Sicht"]["titel"] == sicht["titel"]
    assert regeln["l4Sicht"]["toolbox"] == sicht["mdg"]["toolbox"]
    assert regeln["l4Sicht"]["konventionen"] == sorted(
        sicht["leitfaeden"]["ffmlv"]["ids"]
    )
