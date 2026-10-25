"""Definition of Done: `pytest tests/test_mdg_generic.py` ist gruen und beide
Technologien (ADMBw-Auszug und eine fremde Kleintechnologie) werden geparst.

Die Tests pruefen nicht nur "es kommt etwas zurueck", sondern die konkreten
Stereotypen, Regeln, Viewpoints und die Schema-Konformitaet. Fixtures sind
synthetisch; die echte ADMBw-MDG wird zusaetzlich geprueft, wenn sie lokal
vorliegt (sie ist gitignored).
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mdg_parser import (
    MdgParseError,
    dumps_rules,
    parse_mdg,
    parse_mdg_bytes,
    write_rules,
)
from rules_schema import SchemaError, load_schema, validate

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
RULES = Path(__file__).resolve().parents[2] / 'packages' / 'rules'  # einziger MDG-Leser
FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"  # Monorepo
ADMBW = FIXTURES / "admbw_auszug.xml"
FREMD = FIXTURES / "fremd_klein.xml"
import mdg_source  # noqa: E402

REAL = mdg_source.path()
SCHEMA = ROOT / "rules.schema.json"

BOTH = pytest.mark.parametrize("pfad", [ADMBW, FREMD], ids=["admbw", "fremd"])


def _by_name(entries: list[dict]) -> dict[str, dict]:
    return {entry["name"]: entry for entry in entries}


def _tech(stereotypes: str, *, documentation: bool = True) -> bytes:
    """Minimaltechnologie fuer Fehlerfaelle."""
    head = '<Documentation id="T" name="Testtechnik" version="1.0"/>' if documentation else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f"<MDG.Technology>{head}"
        "<UMLProfiles><UMLProfile><Content><Stereotypes>"
        f"{stereotypes}"
        "</Stereotypes></Content></UMLProfile></UMLProfiles>"
        "</MDG.Technology>"
    ).encode("utf-8")


# --------------------------------------------------------------------------
# Technologie 1: ADMBw-Auszug
# --------------------------------------------------------------------------


def test_admbw_auszug_elemente() -> None:
    rules = parse_mdg(ADMBW)
    elements = _by_name(rules["elementStereotypes"])

    assert set(elements) == {
        "ActualProject",
        "Capability",
        "MeasurableElement",
        "OperationalActivity",
        "Process",
        "ServiceSpecification",
    }
    assert rules["stats"]["elementStereotypes"] == len(elements) == 6

    # Abstrakte Wurzel ohne eigene Metaklasse bleibt erhalten.
    measurable = elements["MeasurableElement"]
    assert measurable["abstract"] is True
    assert measurable["metaclasses"] == []
    assert measurable["appliesTo"] == []
    assert measurable["generalizes"] == []

    # Tagged Values vollstaendig und sortiert.
    capability = elements["Capability"]
    assert capability["metaclasses"] == ["Class"]
    assert capability["appliesTo"] == [{"metaclass": "Class", "properties": {"isActive": ""}}]
    assert [tag["name"] for tag in capability["taggedValues"]] == ["genehmigtAm", "reifegrad"]
    reifegrad = capability["taggedValues"][1]
    assert reifegrad == {
        "name": "reifegrad",
        "type": "Enum",
        "description": "Reifegrad der Faehigkeit",
        "unit": "",
        "values": "A;B;C",
        "default": "B",
    }

    # Klassifizierende Constraint, Technologie-Praefix entfernt.
    assert elements["OperationalActivity"]["metaconstraints"] == [
        {"role": "classifier", "constraints": ["Process"]}
    ]

    # Metarelationship (Komposition) bleibt sichtbar.
    assert elements["ActualProject"]["metarelationships"] == [
        {"metaclass": "Composition", "targets": ["ActualProject"]}
    ]

    # windows-1252 wurde korrekt gelesen (Gedankenstrich, kein Mojibake).
    assert "–" in capability["notes"]

    # Herkunft und Hash belegen die Eingabedatei.
    source = rules["source"]
    assert source["technologyId"] == "NAFv4-ADMBw"
    assert source["technologyVersion"] == "2026.05"
    assert source["file"] == "admbw_auszug.xml"
    assert source["sha256"] == hashlib.sha256(ADMBW.read_bytes()).hexdigest()


def test_admbw_auszug_konnektor_regeln() -> None:
    rules = parse_mdg(ADMBW)
    assert [rule["id"] for rule in rules["connectorRules"]] == [
        "cr:ActivitySupportsService",
        "cr:CapabilityDependency",
        "cr:Exhibits",
    ]

    dependency = rules["connectorRules"][1]
    assert dependency["stereotype"] == "CapabilityDependency"
    assert dependency["metaclasses"] == ["Dependency"]
    assert dependency["source"] == ["Capability"]
    assert dependency["target"] == ["Capability"]
    assert dependency["direction"] == "Source -> Destination"
    assert dependency["roles"] == {"source": ["client"], "target": ["supplier"]}

    # Fremdprofil-Referenz in baseStereotypes bleibt voll qualifiziert.
    exhibits = rules["connectorRules"][2]
    assert exhibits["baseStereotypes"] == ["MeasurableElement", "SysML1.4::allocate"]
    assert exhibits["metaclasses"] == ["Abstraction"]
    assert exhibits["source"] == ["Capability"]
    assert exhibits["target"] == ["ServiceSpecification"]

    # Jede Regel ist vollstaendig und eindeutig.
    ids = [rule["id"] for rule in rules["connectorRules"]]
    assert len(ids) == len(set(ids))
    for rule in rules["connectorRules"]:
        assert rule["id"] == f"cr:{rule['stereotype']}"
        assert rule["source"] and rule["target"]
        assert all(isinstance(ref, str) and ref for ref in rule["source"] + rule["target"])


def test_admbw_auszug_viewpoints_ohne_toolbox_regeln() -> None:
    rules = parse_mdg(ADMBW)

    assert rules["viewpoints"] == [
        {
            "group": "ADMBw Concept Viewpoints",
            "name": "C1 - Capability Taxonomy",
            "alias": "C1 - Capability Taxonomy",
            "notes": "Faehigkeiten und ihre Hierarchie.",
            "kind": "diagramProfile",
            "properties": {
                "alias": "C1 – Capability Taxonomy",
                "diagramID": "C1",
                "toolbox": "ADMBw-C1-Toolbox",
            },
        }
    ]

    # UIToolbox-Eintraege sind Werkzeugkasten-Daten und duerfen keine Regeln werden.
    elements = _by_name(rules["elementStereotypes"])
    assert elements["Capability"]["metaclasses"] == ["Class"]
    assert all(
        "ToolboxItem" not in element["metaclasses"] for element in rules["elementStereotypes"]
    )
    assert rules["stats"]["elementStereotypes"] == 6


def test_admbw_auszug_warnungen_sind_sichtbar() -> None:
    rules = parse_mdg(ADMBW)
    assert rules["warnings"] == [
        {
            "kind": "stereotypeWithoutMetaclass",
            "subject": "MeasurableElement",
            "detail": "kein <Apply>; auf kein UML-Element anwendbar (als abstrakt markiert)",
        }
    ]
    assert rules["stats"]["warnings"] == 1


# --------------------------------------------------------------------------
# Technologie 2: fremde Kleintechnologie (Namespace, source/target, ViewDefinition)
# --------------------------------------------------------------------------


def test_fremde_technologie_elemente() -> None:
    rules = parse_mdg(FREMD)
    elements = _by_name(rules["elementStereotypes"])

    assert set(elements) == {"Baustein", "Dienst", "Schnittstelle"}
    assert elements["Baustein"]["metaclasses"] == ["Class"]
    assert elements["Schnittstelle"]["metaclasses"] == ["Interface"]
    assert elements["Baustein"]["taggedValues"][0]["values"] == "A;B;C"
    # Zweites UMLProfile derselben Technologie wird mitgelesen, Praefix entfernt.
    assert elements["Dienst"]["metaconstraints"] == [
        {"role": "classifier", "constraints": ["Baustein"]}
    ]
    assert rules["warnings"] == []


def test_fremde_technologie_konnektoren() -> None:
    rules = parse_mdg(FREMD)
    rules_by_id = {rule["id"]: rule for rule in rules["connectorRules"]}
    assert set(rules_by_id) == {"cr:meldung", "cr:nutzt", "cr:verbindet"}

    nutzt = rules_by_id["cr:nutzt"]
    assert nutzt["metaclasses"] == ["Association"]
    assert nutzt["source"] == ["Baustein"]
    assert nutzt["target"] == ["Schnittstelle"]
    assert nutzt["roles"] == {"source": ["source"], "target": ["target"]}
    assert nutzt["direction"] is None

    # Konnektor ohne Endpunkt-Constraints: expliziter Platzhalter, keine leere Liste.
    meldung = rules_by_id["cr:meldung"]
    assert meldung["metaclasses"] == ["Message"]
    assert meldung["source"] == ["*"]
    assert meldung["target"] == ["*"]
    assert meldung["roles"] == {"source": [], "target": []}


def test_fremde_technologie_viewpoint_aus_viewdefinition() -> None:
    rules = parse_mdg(FREMD)
    assert rules["viewpoints"] == [
        {
            "group": "Acme Bausteine",
            "name": "Bausteinlandkarte",
            "alias": "BLK",
            "notes": "Uebersicht aller Bausteine.",
            "kind": "viewDefinition",
            "properties": {"category": "Acme", "diagramID": "BLK"},
        }
    ]


# --------------------------------------------------------------------------
# Querschnitt: Metaklassen, Schema, Determinismus
# --------------------------------------------------------------------------


@BOTH
def test_metaklassen_abschnitt_stimmt_mit_den_arrays(pfad: Path) -> None:
    rules = parse_mdg(pfad)
    erwartet: dict[str, dict[str, int]] = {}
    for element in rules["elementStereotypes"]:
        for metaclass in element["metaclasses"]:
            eintrag = erwartet.setdefault(
                metaclass, {"stereotypeCount": 0, "ruleCount": 0}
            )
            eintrag["stereotypeCount"] += 1
    for rule in rules["connectorRules"]:
        for metaclass in rule["metaclasses"]:
            eintrag = erwartet.setdefault(
                metaclass, {"stereotypeCount": 0, "ruleCount": 0}
            )
            eintrag["ruleCount"] += 1

    assert [entry["name"] for entry in rules["metaclasses"]] == sorted(erwartet)
    for entry in rules["metaclasses"]:
        assert entry["stereotypeCount"] == erwartet[entry["name"]]["stereotypeCount"]
        assert entry["ruleCount"] == erwartet[entry["name"]]["ruleCount"]
        assert entry["kind"] in {"element", "connector", "mixed"}
    assert rules["stats"]["metaclasses"] == len(rules["metaclasses"])


@BOTH
def test_ausgabe_ist_schema_konform(pfad: Path) -> None:
    rules = parse_mdg(pfad)
    validate(rules, load_schema(SCHEMA))
    # JSON-Rundreise veraendert nichts (kanonischer Text).
    assert json.loads(dumps_rules(rules)) == rules


@BOTH
def test_gleicher_input_ergibt_gleiche_bytes(pfad: Path, tmp_path: Path) -> None:
    erster_text = dumps_rules(parse_mdg(pfad))
    zweiter_text = dumps_rules(parse_mdg(pfad))
    assert erster_text == zweiter_text
    assert "\r" not in erster_text
    assert erster_text.endswith("\n")

    erste_datei = write_rules(parse_mdg(pfad), tmp_path / "eins.json")
    zweite_datei = write_rules(parse_mdg(pfad), tmp_path / "zwei.json")
    assert erste_datei.read_bytes() == zweite_datei.read_bytes()

    # Ausgabe ist UTF-8 und ungeordnete Quell-XML-Attribute beeinflussen sie nicht.
    text = erste_datei.read_bytes().decode("utf-8")
    assert text == erster_text


def test_kern_ohne_zeitstempel_und_zufall() -> None:
    quelle = (RULES / "mdg_parser.py").read_text(encoding="utf-8")
    for verboten in ("import time", "import uuid", "import random", "datetime", "urandom"):
        assert verboten not in quelle, f"Determinismus verletzt: {verboten}"


def test_kein_technologie_hardcoding_im_parser() -> None:
    quelle = (RULES / "mdg_parser.py").read_text(encoding="utf-8").lower()
    for technologie in ("nafv4", "admbw", "bpmn2.0", "sysml1.4", "musterarchitektur"):
        assert technologie not in quelle, (
            f"Technologie-Name '{technologie}' steht im Parser; Technologie muss Daten bleiben"
        )


# --------------------------------------------------------------------------
# Schema-Pruefer: Fehler werden laut gemeldet
# --------------------------------------------------------------------------


def _mutiert(mutation) -> dict:
    rules = copy.deepcopy(parse_mdg(FREMD))
    mutation(rules)
    return rules


@pytest.mark.parametrize(
    ("name", "mutation", "erwartung"),
    [
        (
            "pflichtfeld",
            lambda rules: rules.pop("stats"),
            "Pflichtfeld 'stats' fehlt",
        ),
        (
            "unerlaubtes-feld",
            lambda rules: rules["stats"].__setitem__("extra", 1),
            "unerlaubtes Feld 'extra'",
        ),
        (
            "falscher-typ",
            lambda rules: rules["stats"].__setitem__("elementStereotypes", "6"),
            "Typ string ist nicht erlaubt",
        ),
        (
            "ungueltiger-hash",
            lambda rules: rules["source"].__setitem__("sha256", "abc"),
            "passt nicht auf Muster",
        ),
        (
            "leere-regelseite",
            lambda rules: rules["connectorRules"][0].__setitem__("source", []),
            "zu wenige Eintraege",
        ),
        (
            "falsche-regel-id",
            lambda rules: rules["connectorRules"][0].__setitem__("id", "regel-1"),
            "passt nicht auf Muster",
        ),
        (
            "doppelter-metaklassen-eintrag",
            lambda rules: rules["metaclasses"].append(dict(rules["metaclasses"][0])),
            "Eintraege sind nicht eindeutig",
        ),
        (
            "unbekannter-warnungstyp",
            lambda rules: rules["warnings"].append(
                {"kind": "irgendwas", "subject": "X", "detail": "Y"}
            ),
            "ist nicht in",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_schema_pruefer_meldet_fehler(name: str, mutation, erwartung: str) -> None:
    schema = load_schema(SCHEMA)
    with pytest.raises(SchemaError) as fehler:
        validate(_mutiert(mutation), schema)
    assert erwartung in str(fehler.value)


def test_schema_pruefer_akzeptiert_gueltige_ausgabe() -> None:
    validate(parse_mdg(ADMBW), load_schema(SCHEMA))
    validate(parse_mdg(FREMD), load_schema(SCHEMA))


# --------------------------------------------------------------------------
# Fehler sind laut, nie still
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "daten", "erwartung"),
    [
        ("leer", b"", "Datei ist leer"),
        ("kein-xml", b"das ist kein xml", "kein gueltiges XML"),
        ("falsche-wurzel", b"<nope/>", "ist keine MDG-Technologie"),
        (
            "ohne-dokumentation",
            _tech("", documentation=False),
            "ohne <Documentation>",
        ),
        ("ohne-stereotypen", _tech(""), "enthaelt keine Stereotypen"),
        (
            "ohne-namen",
            _tech('<Stereotype metatype="x"/>'),
            "Stereotyp ohne Namen",
        ),
        (
            "apply-ohne-metaklasse",
            _tech('<Stereotype name="X"><AppliesTo><Apply/></AppliesTo></Stereotype>'),
            "Apply ohne Metaklasse",
        ),
        (
            "constraint-ohne-ziel",
            _tech(
                '<Stereotype name="X"><AppliesTo><Apply type="Class"/></AppliesTo>'
                '<metaconstraints><metaconstraint umlRole="client" constraint=""/></metaconstraints>'
                "</Stereotype>"
            ),
            "ohne 'constraint'",
        ),
        (
            "einseitige-regel",
            _tech(
                '<Stereotype name="X"><AppliesTo><Apply type="Dependency"/></AppliesTo>'
                '<metaconstraints><metaconstraint umlRole="client" constraint="T::A"/></metaconstraints>'
                "</Stereotype>"
            ),
            "nur eine Seite",
        ),
        (
            "endpunkte-ohne-konnektor-metaklasse",
            _tech(
                '<Stereotype name="X"><AppliesTo><Apply type="Class"/></AppliesTo>'
                '<metaconstraints>'
                '<metaconstraint umlRole="client" constraint="T::A"/>'
                '<metaconstraint umlRole="supplier" constraint="T::B"/>'
                "</metaconstraints></Stereotype>"
            ),
            "keine Konnektor-Metaklasse",
        ),
        (
            "widerspruechliche-definition",
            _tech(
                '<Stereotype name="X"><AppliesTo><Apply type="Class"/></AppliesTo></Stereotype>'
                '<Stereotype name="X"><AppliesTo><Apply type="Object"/></AppliesTo></Stereotype>'
            ),
            "mehrfach mit unterschiedlicher Definition",
        ),
        (
            "viewdefinition-ohne-namen",
            (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<MDG.Technology><Documentation id="T" name="Testtechnik"/>'
                "<UMLProfiles><UMLProfile><Content><Stereotypes>"
                '<Stereotype name="A"><AppliesTo><Apply type="Class"/></AppliesTo></Stereotype>'
                "</Stereotypes><ViewDefinitions><ViewDefinition alias='X'/>"
                "</ViewDefinitions></Content></UMLProfile></UMLProfiles></MDG.Technology>"
            ).encode("utf-8"),
            "ViewDefinition ohne Namen",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and "\n" not in value else "",
)
def test_fehler_sind_laut(name: str, daten: bytes, erwartung: str) -> None:
    with pytest.raises(MdgParseError) as fehler:
        parse_mdg_bytes(daten, filename="testfall.xml")
    assert erwartung in str(fehler.value)
    assert "testfall.xml" in str(fehler.value)


def test_datei_nicht_lesbar(tmp_path: Path) -> None:
    with pytest.raises(MdgParseError) as fehler:
        parse_mdg(tmp_path / "gibt-es-nicht.xml")
    assert "nicht lesbar" in str(fehler.value)


def test_leere_technologie_ist_kein_erfolg() -> None:
    """Gegenprobe zum Verbot, eine leere Liste als Erfolg zu verkaufen."""
    with pytest.raises(MdgParseError):
        parse_mdg_bytes(_tech(""), filename="leer.xml")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _cli(*argumente: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RULES / "mdg_parser.py"), *argumente],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_schreibt_datei_und_prueft_schema(tmp_path: Path) -> None:
    ziel = tmp_path / "rules.json"
    lauf = _cli(str(ADMBW), "--check", "-o", str(ziel))

    assert lauf.returncode == 0, lauf.stderr
    assert lauf.stdout == ""
    assert "Element-Stereotypen" in lauf.stderr
    assert json.loads(ziel.read_text(encoding="utf-8")) == parse_mdg(ADMBW)


def test_cli_ohne_ausgabedatei_nach_stdout() -> None:
    lauf = _cli(str(FREMD), "-q")
    assert lauf.returncode == 0, lauf.stderr
    assert lauf.stderr == ""
    assert json.loads(lauf.stdout) == parse_mdg(FREMD)


def test_cli_meldet_fehler_mit_exitcode(tmp_path: Path) -> None:
    kaputt = tmp_path / "kaputt.xml"
    kaputt.write_text("<nope/>", encoding="utf-8")
    ziel = tmp_path / "rules.json"

    lauf = _cli(str(kaputt), "-o", str(ziel))

    assert lauf.returncode == 1
    assert "fehler:" in lauf.stderr
    assert "keine MDG-Technologie" in lauf.stderr
    assert not ziel.exists()


# --------------------------------------------------------------------------
# Echte ADMBw-MDG (lokal vorhanden, gitignored)
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not REAL.exists(),
    reason=f"lokale ADMBw-MDG fehlt ({REAL.name} ist gitignored)",
)
def test_echte_admbw_mdg_wird_geparst() -> None:
    rules = parse_mdg(REAL)
    validate(rules, load_schema(SCHEMA))

    stats = rules["stats"]
    assert stats["elementStereotypes"] + stats["connectorRules"] == 318
    assert stats["elementStereotypes"] >= 170
    assert stats["connectorRules"] >= 130
    assert stats["viewpoints"] >= 50
    assert stats["metaclasses"] >= 20

    # Fremdprofile bleiben unterscheidbar, lokale Referenzen sind normalisiert.
    referenzen = {
        ref
        for rule in rules["connectorRules"]
        for ref in rule["source"] + rule["target"]
    }
    assert any(ref.startswith("BPMN2.0::") for ref in referenzen)
    assert all("NAFv4" not in ref for ref in referenzen)

    # Nicht definierte Verweise werden gemeldet, nicht verschluckt.
    gemeldet = {warning["subject"] for warning in rules["warnings"]}
    assert "DecisionNode" in gemeldet
    assert rules["stats"]["warnings"] == len(rules["warnings"])

    # Jede Regel nennt mindestens eine Quelle und ein Ziel.
    for rule in rules["connectorRules"]:
        assert rule["source"] and rule["target"]
