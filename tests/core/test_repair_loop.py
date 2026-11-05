"""Tests fuer repair_loop: MDG-Fehler ohne KI beheben."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import mdg_parser
import repair_loop
import validator

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
import mdg_source  # noqa: E402

MDG = mdg_source.path()

pytestmark = pytest.mark.skipif(not MDG.is_file(), reason="MDG-Fixture fehlt")


@pytest.fixture(scope="module")
def ruleset() -> validator.RuleSet:
    return validator.build_rules(mdg_parser.parse_mdg(MDG))


def _ir(element_stereotype: str, connector_stereotype: str) -> dict:
    return {
        "ir_version": 1,
        "packages": [{"path": "Raumschiff", "name": "Raumschiff"}],
        "elements": [
            {"package": "Raumschiff", "name": "Mehrzweckraumschiff",
             "stereotype": element_stereotype, "ea_type": "Object"},
            {"package": "Raumschiff", "name": "Weltraum",
             "stereotype": "ActualEnvironment", "ea_type": "Object"},
        ],
        "connectors": [
            {"source": "Raumschiff::Mehrzweckraumschiff",
             "target": "Raumschiff::Weltraum",
             "stereotype": connector_stereotype},
        ],
    }


def test_global_assignment_repairs_forbidden_endpoint(ruleset):
    ir = _ir("ActualResource", "RequiredEnvironment")
    before = validator.validate_model(ir, ruleset)
    assert any(f["check"] == "forbiddenConnectorEndpoints" for f in before)

    result = repair_loop.repair(ir, ruleset, max_rounds=4)
    assert result.clean, result.findings


def test_valid_model_is_untouched(ruleset):
    ir = _ir("ActualEnvironment", "RequiredEnvironment")
    ir["connectors"] = []  # ohne Kanten gibt es nichts zu beanstanden
    result = repair_loop.repair(ir, ruleset, max_rounds=3)
    assert result.rounds == []
    assert result.ir == ir


def test_repair_is_deterministic(ruleset):
    ir = _ir("ActualResource", "RequiredEnvironment")
    first = repair_loop.repair(ir, ruleset, max_rounds=4)
    second = repair_loop.repair(ir, ruleset, max_rounds=4)
    assert json.dumps(first.ir, sort_keys=True) == json.dumps(second.ir, sort_keys=True)


def test_unknown_connector_stereotype_is_removed(ruleset):
    ir = _ir("ActualEnvironment", "GibtEsNicht")
    result = repair_loop.repair(ir, ruleset, max_rounds=3)
    assert result.ir["connectors"] == []


def test_max_rounds_must_be_positive(ruleset):
    with pytest.raises(repair_loop.RepairError):
        repair_loop.repair(_ir("ActualEnvironment", "RequiredEnvironment"), ruleset, max_rounds=0)
