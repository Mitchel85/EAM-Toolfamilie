"""Tests fuer den vierstufigen Lauf (Regelwerk, Elemente, Bau, Pruefung)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import eam_ai
import extract
import qea_writer
import stufen

ROOT = Path(__file__).resolve().parents[2]
MDG = ROOT / "packages" / "core" / "fixtures" / "admbw_auszug.xml"
MASC = ROOT / "packages" / "core" / "fixtures" / "Musterarchitektur_MASC.qea"

TEXT = (
    "Der Kampfpanzer meldet an das System Lagezentrum.\n\n"
    "Der Kampfpanzer wird vom System Lagezentrum gesteuert.\n"
)


class FakeBackend:
    """Antwortet je Prompt-Art; zeichnet die Aufrufe auf."""

    name = "fake"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "ausschliesslich ELEMENTE" in prompt:
            return json.dumps(
                {
                    "elements": [
                        {
                            "name": "Kampfpanzer",
                            "stereotype": "ServiceSpecification",
                            "notes": "Der Kampfpanzer meldet an das System Lagezentrum.",
                            "source_ref": "D1-S1",
                            "confidence": 0.9,
                        },
                        {
                            "name": "Lagezentrum",
                            "stereotype": "OperationalActivity",
                            "notes": "Der Kampfpanzer wird vom System Lagezentrum gesteuert.",
                            "source_ref": "D1-S2",
                            "confidence": 0.9,
                        },
                    ],
                    "connectors": [],
                }
            )
        if "ausschliesslich BEZIEHUNGEN" in prompt:
            return json.dumps(
                {
                    "elements": [],
                    "connectors": [
                        {
                            "source": "Lagezentrum",
                            "target": "Kampfpanzer",
                            "stereotype": "ActivitySupportsService",
                            "notes": "Das System Lagezentrum steuert den Kampfpanzer.",
                            "source_ref": "D1-S2",
                            "confidence": 0.8,
                        }
                    ],
                }
            )
        raise AssertionError(f"unbekannter Prompt: {prompt[:120]!r}")


@pytest.fixture()
def arbeitsordner(tmp_path: Path) -> Path:
    quelle = tmp_path / "quelle.md"
    quelle.write_text(TEXT, encoding="utf-8")
    return tmp_path


def test_stufe1_legt_regelwerk_und_startpaket_ab(arbeitsordner: Path) -> None:
    ergebnis = stufen.stufe1(
        mdg=MDG,
        startpaket=MASC,
        text=arbeitsordner / "quelle.md",
        workdir=arbeitsordner / "work",
        projekt="NSS",
    )
    work = arbeitsordner / "work"
    assert ergebnis["elemente"] > 0
    assert ergebnis["beziehungen"] > 0
    assert ergebnis["startelemente"] > 0
    assert (work / stufen.REGELWERK).is_file()
    assert (work / stufen.STARTPAKET).is_file()
    assert (work / "01_steka.qea").is_file()
    state = json.loads((work / stufen.STATE).read_text(encoding="utf-8"))
    assert state["projekt"] == "NSS"
    assert state["katalog"].endswith("01_steka.qea")


def test_stufe2_chargen_und_fortsetzung(arbeitsordner: Path) -> None:
    stufen.stufe1(
        mdg=MDG,
        text=arbeitsordner / "quelle.md",
        workdir=arbeitsordner / "work",
        projekt="NSS",
    )
    backend = FakeBackend()
    ergebnis = stufen.stufe2(
        workdir=arbeitsordner / "work",
        text=arbeitsordner / "quelle.md",
        backend=backend,
        pause=0,
        charge=60,
    )
    assert ergebnis["chargen"] >= 2
    assert ergebnis["elemente"] == 2
    assert ergebnis["beziehungen"] == 1
    assert ergebnis["aufrufe"] == ergebnis["chargen"] * 2
    antwort = json.loads((arbeitsordner / "work" / stufen.ANTWORT).read_text(encoding="utf-8"))
    assert {e["name"] for e in antwort["elements"]} == {"Kampfpanzer", "Lagezentrum"}
    assert antwort["connectors"][0]["stereotype"] == "ActivitySupportsService"

    # Zweiter Lauf: alle Chargen liegen vor, kein weiterer Aufruf.
    still = FakeBackend()
    ergebnis2 = stufen.stufe2(
        workdir=arbeitsordner / "work",
        text=arbeitsordner / "quelle.md",
        backend=still,
        pause=0,
        charge=60,
    )
    assert ergebnis2["aufrufe"] == 0
    assert still.prompts == []


def test_kompakter_prompt_ist_kleiner_als_der_vollprompt(arbeitsordner: Path) -> None:
    rules = eam_ai.load_technology(MDG)
    rulebook = extract.load_rules(rules)
    batch = extract.split_documents(TEXT)
    kompakt = stufen.element_prompt(batch, rulebook, package="NSS")
    voll = extract.build_prompt(batch, rulebook, "NSS")
    assert len(kompakt) < len(voll)


def test_stufe3_und_4_bauen_ohne_fremde_wurzel(arbeitsordner: Path) -> None:
    work = arbeitsordner / "work"
    stufen.stufe1(
        mdg=MDG,
        startpaket=MASC,
        text=arbeitsordner / "quelle.md",
        workdir=work,
        projekt="NSS",
    )
    stufen.stufe2(
        workdir=work,
        text=arbeitsordner / "quelle.md",
        backend=FakeBackend(),
        pause=0,
        charge=60,
    )
    ziel = arbeitsordner / "modell.qea"
    report = stufen.stufe3(
        workdir=work,
        out=ziel,
        sidecar=False,
        log=lambda _m: None,
    )
    assert report.exported
    assert ziel.is_file()

    con = sqlite3.connect(f"file:{ziel}?mode=ro", uri=True)
    try:
        wurzeln = {name for (name,) in con.execute("SELECT Name FROM t_package WHERE Parent_ID=0")}
        assert "MASC" not in wurzeln
        assert "StEKa" in wurzeln
        assert "NSS" in wurzeln
    finally:
        con.close()

    bericht = stufen.stufe4(qea=ziel, projekt="NSS")
    assert bericht["ok"], bericht["leitfaden"]
    assert bericht["zahlen"]["sichten"] == 44


def test_stufe3_ohne_sichten_schreibt_keine_diagramme(arbeitsordner: Path) -> None:
    """``--ohne-sichten``: Modell ohne Diagramme, Inhalt bleibt vollstaendig."""
    work = arbeitsordner / "work-ohne-sichten"
    stufen.stufe1(
        mdg=MDG,
        startpaket=MASC,
        text=arbeitsordner / "quelle.md",
        workdir=work,
        projekt="NSS",
    )
    stufen.stufe2(
        workdir=work,
        text=arbeitsordner / "quelle.md",
        backend=FakeBackend(),
        pause=0,
        charge=60,
    )
    ziel = arbeitsordner / "ohne_sichten.qea"
    report = stufen.stufe3(
        workdir=work,
        out=ziel,
        sidecar=False,
        mit_sichten=False,
        log=lambda _m: None,
    )
    assert report.exported
    con = sqlite3.connect(f"file:{ziel}?mode=ro", uri=True)
    try:
        assert con.execute("SELECT count(*) FROM t_diagram").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM t_diagramobjects").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM t_object").fetchone()[0] > 0
    finally:
        con.close()


def test_startpaket_ohne_ea_guid_wird_trotzdem_gelesen(arbeitsordner: Path) -> None:
    """Ein StEKa aus einem fremden Werkzeug hat oft keine ea_guid."""
    steka = qea_writer.write_qea(
        {
            "ir_version": 1,
            "packages": [{"path": "StEKa"}],
            "elements": [
                {
                    "package": "StEKa",
                    "name": "Kampfpanzer",
                    "stereotype": "ServiceSpecification",
                    "ea_type": "Class",
                }
            ],
            "connectors": [],
            "diagrams": [],
        },
        arbeitsordner / "steka.qea",
    )
    con = sqlite3.connect(steka)
    try:
        con.execute("update t_object set ea_guid = NULL")
        con.commit()
    finally:
        con.close()
    ergebnis = stufen.stufe1(
        mdg=MDG,
        startpaket=steka,
        text=arbeitsordner / "quelle.md",
        workdir=arbeitsordner / "work",
        projekt="NSS",
    )
    assert ergebnis["startelemente"] == 1
    assert "ohne ea_guid" in ergebnis["startpaket_hinweis"]
    assert (arbeitsordner / "work" / "01_steka.qea").is_file()
