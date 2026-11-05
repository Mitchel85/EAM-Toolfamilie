"""Tests fuer kantenausbeute.py -- Handlungssaetze gegen gueltige MDG-Kanten.

Kein Netz, keine echten Modelle: das Regelwerk ist die synthetische Fixture
``rules_validator.json``, das IR wird im Test gebaut.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import kantenausbeute as ka
import validator

FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"
RULES_PATH = FIXTURES / "rules_validator.json"

TEXT = (
    "# Testhandbuch\n"
    "\n"
    "Das Lagebildsystem stellt den Dienst Lagebild bereit.\n"
    "\n"
    "Der Dienst Lagebild ist ein ServicePort des Lagebildsystems.\n"
    "\n"
    "Der Himmel ist blau und der Wind kommt von Westen.\n"
)


@pytest.fixture(scope="module")
def ruleset() -> validator.RuleSet:
    return validator.build_rules(json.loads(RULES_PATH.read_text(encoding="utf-8")))


def make_ir(connectors: list[tuple[str, str, str]]) -> dict:
    """Kleines IR mit zwei Elementen und den uebergebenen Kanten."""
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
            for source, target, stereotype in connectors
        ],
        "diagrams": [],
        "meta": {"quellen": {}, "extraction": {}},
    }


def test_handlungssatz_braucht_zwei_elemente_und_ein_verb():
    namen = ["Lagebildsystem", "Dienst Lagebild", "Himmel"]
    saetze = ka.handlungssaetze(TEXT, namen)

    assert len(saetze) == 1
    assert saetze[0]["satz"].startswith("Das Lagebildsystem stellt")
    assert set(saetze[0]["elemente"]) == {"Dienst Lagebild", "Lagebildsystem"}
    # Zwei Elemente, aber keine Handlung ("ist ein") -> kein Handlungssatz.
    assert all("ServicePort des Lagebildsystems" not in s["satz"] for s in saetze)


def test_handlungssatz_zaehlt_ohne_handlung_verb_nicht():
    assert ka.handlungssaetze("Himmel und Wind sind blau.", ["Himmel", "Wind"]) == []


def test_ueberschrift_beginnt_keinen_satz():
    saetze = ka.handlungssaetze(TEXT, ["Testhandbuch", "Lagebildsystem"])
    assert all(not s["satz"].startswith("#") for s in saetze)


def test_gueltige_kante_deckt_den_handlungssatz(ruleset):
    ir = make_ir([("Lagebildsystem", "Dienst Lagebild", "Provides")])
    ergebnis = ka.ausbeute(TEXT, ir, ruleset)

    assert ergebnis["handlungssaetze"] == 1
    assert ergebnis["gedeckt"] == 1
    assert ergebnis["ausbeute"] == 100.0
    assert ergebnis["kanten_gueltig"] == 1


def test_verbotene_kante_deckt_nichts(ruleset):
    # Provides verlangt System -> ServicePort; umgedreht ist die Kante ungueltig.
    ir = make_ir([("Dienst Lagebild", "Lagebildsystem", "Provides")])
    ergebnis = ka.ausbeute(TEXT, ir, ruleset)

    assert ergebnis["handlungssaetze"] == 1
    assert ergebnis["gedeckt"] == 0
    assert ergebnis["ausbeute"] == 0.0
    assert ergebnis["kanten_roh"] == 1
    assert ergebnis["kanten_gueltig"] == 0
    assert ergebnis["kantenausbeute"] == 0.0
    assert ergebnis["ungedeckt"]


def test_kante_zwischen_falschen_elementen_deckt_nicht(ruleset):
    ir = make_ir([("Lagebildsystem", "Dienst Lagebild", "Provides")])
    text = "Der Himmel nutzt den Wind und das Lagebildsystem liefert den Dienst Lagebild."
    ergebnis = ka.ausbeute(text, ir, ruleset)

    assert ergebnis["handlungssaetze"] == 1
    assert ergebnis["gedeckt"] == 1
    assert ergebnis["kanten_roh"] == 1


def test_ausbeute_ist_deterministisch(ruleset):
    ir = make_ir([("Lagebildsystem", "Dienst Lagebild", "Provides")])
    erst = ka.ausbeute(TEXT, ir, ruleset)
    zweit = ka.ausbeute(TEXT, ir, ruleset)
    assert json.dumps(erst, sort_keys=True) == json.dumps(zweit, sort_keys=True)


def test_leere_quelle_ergibt_null_ohne_ausnahme(ruleset):
    ir = make_ir([])
    ergebnis = ka.ausbeute("", ir, ruleset)
    assert ergebnis["handlungssaetze"] == 0
    assert ergebnis["ausbeute"] == 0.0
    assert ergebnis["kantenausbeute"] == 0.0


def test_markdown_bericht_nennt_beide_quoten(ruleset):
    ir = make_ir([("Lagebildsystem", "Dienst Lagebild", "Provides")])
    ergebnis = ka.ausbeute(TEXT, ir, ruleset)
    ergebnis["quelle"] = "quelle.md"
    ergebnis["modell"] = "modell.json"
    ergebnis["regelwerk"] = "Test"
    md = ka.render_markdown(ergebnis)
    assert "**Ausbeute** | **100.0 %**" in md
    assert "Kantenausbeute | 100.0 %" in md
