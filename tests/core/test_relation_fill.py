"""Tests fuer relation_fill.py -- nur eindeutige Saetze werden zur Kante."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import relation_fill as rf
import validator

FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"
RULES_PATH = FIXTURES / "rules_validator.json"


@pytest.fixture(scope="module")
def ruleset() -> validator.RuleSet:
    return validator.build_rules(json.loads(RULES_PATH.read_text(encoding="utf-8")))


def make_ir(connectors: list[tuple[str, str, str]] | None = None) -> dict:
    return {
        "ir_version": 1,
        "packages": [{"path": "Architektur"}],
        "elements": [
            {
                "package": "Architektur",
                "name": "Lagebildsystem",
                "stereotype": "System",
                "ea_type": "Class",
                "notes": "",
                "tags": {},
            },
            {
                "package": "Architektur",
                "name": "Dienst Lagebild",
                "stereotype": "ServicePort",
                "ea_type": "Port",
                "notes": "",
                "tags": {},
            },
            {
                "package": "Architektur",
                "name": "Dienst Wetter",
                "stereotype": "ServicePort",
                "ea_type": "Port",
                "notes": "",
                "tags": {},
            },
        ],
        "connectors": [
            {
                "source": f"Architektur::{source}",
                "target": f"Architektur::{target}",
                "stereotype": stereotype,
                "ea_type": "Dependency",
                "name": "",
                "direction": "Source -> Destination",
                "notes": "",
                "tags": {},
            }
            for source, target, stereotype in (connectors or [])
        ],
        "diagrams": [],
        "meta": {"quellen": {}, "extraction": {}},
    }


def absatz(text: str, ref: str = "D1-S1") -> SimpleNamespace:
    return SimpleNamespace(text=text, ref=ref)


def test_zwei_namen_und_verb_ergeben_eine_kante(ruleset):
    ir = make_ir()
    nachtraege = rf.ergaenze(
        ir,
        [absatz("Das Lagebildsystem stellt den Dienst Lagebild bereit.")],
        ruleset,
    )

    assert len(nachtraege) == 1
    assert len(ir["connectors"]) == 1
    kante = ir["connectors"][0]
    assert kante["source"] == "Architektur::Lagebildsystem"
    assert kante["target"] == "Architektur::Dienst Lagebild"
    assert kante["tags"]["source_ref"] == "D1-S1"
    assert nachtraege[0].stereotyp in ruleset.connectors


def test_drei_namen_bleiben_unangetastet(ruleset):
    ir = make_ir()
    text = "Das Lagebildsystem stellt den Dienst Lagebild und den Dienst Wetter bereit."
    assert rf.ergaenze(ir, [absatz(text)], ruleset) == []
    assert ir["connectors"] == []


def test_ohne_verb_keine_kante(ruleset):
    ir = make_ir()
    assert rf.ergaenze(ir, [absatz("Das Lagebildsystem und der Dienst Lagebild.")], ruleset) == []
    assert ir["connectors"] == []


def test_bestehende_kante_wird_nicht_verdoppelt(ruleset):
    ir = make_ir([("Lagebildsystem", "Dienst Lagebild", "Provides")])
    nachtraege = rf.ergaenze(
        ir,
        [absatz("Das Lagebildsystem stellt den Dienst Lagebild bereit.")],
        ruleset,
    )
    assert nachtraege == []
    assert len(ir["connectors"]) == 1


def test_tabelle_zaehlt_nicht_glossarlabel_schon(ruleset):
    ir = make_ir()
    text = "| Lagebildsystem | Dienst Lagebild |\n\n**Lagebildsystem** — stellt den Dienst Lagebild bereit."
    nachtraege = rf.ergaenze(ir, [absatz(text)], ruleset)
    assert len(nachtraege) == 1
    assert len(ir["connectors"]) == 1


def test_wiederholung_ist_idempotent(ruleset):
    ir = make_ir()
    absaetze = [absatz("Das Lagebildsystem stellt den Dienst Lagebild bereit.")]
    assert len(rf.ergaenze(ir, absaetze, ruleset)) == 1
    assert rf.ergaenze(ir, absaetze, ruleset) == []
    assert len(ir["connectors"]) == 1
