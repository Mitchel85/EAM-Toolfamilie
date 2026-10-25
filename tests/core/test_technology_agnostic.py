"""Definition of Done: `pytest tests/test_technology_agnostic.py` ist gruen und
ein zweites Regelwerk wird unabhaengig geladen.

Der Nachweis der Technologie-Offenheit laeuft in fuenf Stufen:

1. Eine neue, fremde Technologie-XML (`tests/fixtures/fremd_netz.xml`,
   Energieverteilnetz) wird geparst. Sie hat eigene Stereotypen, eigene
   Konnektorregeln, eigene Rollen-Schreibweisen und einen eigenen Viewpoint.
2. Das Ergebnis ist schema-konform, kanonisch und byte-identisch
   reproduzierbar - auch ueber Prozessgrenzen.
3. Ein ADMBw-Regelwerk und das fremde Regelwerk werden in beiden
   Ladereihenfolgen geparst; sie vermischen sich nicht.
4. Eine dritte, nur im Speicher erzeugte Technologie wird ohne jede
   Codeaenderung geparst. Zusaetzlich wird statisch geprueft, dass in den
   Kernmodulen kein Technologie-Name und kein technologiespezifischer
   Stereotyp steht.
5. `validator.py` prueft Modelle gegen genau dieses fremde Regelwerk: ein
   konformes Modell bleibt ohne Findings, ein verbotener Endpunkt wird mit
   der Regel-ID `cr:...` gemeldet, ein unbekannter Stereotyp mit Objektnamen.
   Dieselben Modelle gegen das ADMBw-Regelwerk liefern andere Findings -
   die Regeln kommen aus der Datei, nicht aus dem Code.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import validator
from mdg_parser import dumps_rules, parse_mdg, parse_mdg_bytes, write_rules
from rules_schema import SchemaError, load_schema, validate as validate_schema

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
RULES = Path(__file__).resolve().parents[2] / 'packages' / 'rules'  # einziger MDG-Leser
FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"  # Monorepo
NETZ = FIXTURES / "fremd_netz.xml"
ADMBW = FIXTURES / "admbw_auszug.xml"
SCHEMA = ROOT / "rules.schema.json"

CORE_MODULES = ("rules_schema.py", "qea_writer.py")
RULES_MODULES = ("mdg_parser.py",)


def _by_name(entries: list[dict]) -> dict[str, dict]:
    return {entry["name"]: entry for entry in entries}


def _by_id(entries: list[dict]) -> dict[str, dict]:
    return {entry["id"]: entry for entry in entries}


def _dritte_technologie() -> bytes:
    """Eine Technologie, die in keiner Datei und in keinem Testfall steht.

    Sie belegt, dass eine neue Technologie nur Daten mitbringt: kein Name,
    kein Stereotyp und keine Regel ist im Parser bekannt.
    """
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
        "<MDG.Technology version=\"1.0\">"
        '<Documentation id="Verlag" name="Verlagswesen" version="1.0" '
        'notes="Nur im Speicher erzeugte Prueftechnologie."/>'
        "<UMLProfiles><UMLProfile profiletype=\"uml2\">"
        "<Documentation id=\"Verlag\" name=\"Verlag Basis\"/>"
        "<Content><Stereotypes>"
        '<Stereotype name="Regal" metatype="Regal" notes="Ablageort.">'
        '<AppliesTo><Apply type="Class"/></AppliesTo>'
        "</Stereotype>"
        '<Stereotype name="verweist" metatype="verweist" notes="Regal zeigt auf Regal.">'
        '<AppliesTo><Apply type="Dependency"/></AppliesTo>'
        "<metaconstraints>"
        '<metaconstraint umlRole="client" constraint="Verlag::Regal"/>'
        '<metaconstraint umlRole="supplier" constraint="Verlag::Regal"/>'
        "</metaconstraints>"
        "</Stereotype>"
        "</Stereotypes></Content>"
        "</UMLProfile></UMLProfiles></MDG.Technology>"
    ).encode("utf-8")


# --------------------------------------------------------------------------
# Stufe 1: fremde Technologie laden
# --------------------------------------------------------------------------


def test_fremdtechnologie_wird_geladen() -> None:
    rules = parse_mdg(NETZ)
    source = rules["source"]

    assert source["technologyId"] == "Netzplan"
    assert source["technologyName"] == "Stadtwerke Netzplan"
    assert source["technologyVersion"] == "2.4"
    assert source["file"] == "fremd_netz.xml"
    assert source["sha256"] == hashlib.sha256(NETZ.read_bytes()).hexdigest()

    # Zaehler und Listen muessen zusammenpassen: 0 waere kein Erfolg.
    stats = rules["stats"]
    assert stats == {
        "elementStereotypes": 4,
        "connectorRules": 4,
        "viewpoints": 2,
        "metaclasses": 7,
        "warnings": 1,
    }
    assert stats["elementStereotypes"] == len(rules["elementStereotypes"])
    assert stats["connectorRules"] == len(rules["connectorRules"])
    assert stats["viewpoints"] == len(rules["viewpoints"])
    assert stats["metaclasses"] == len(rules["metaclasses"])
    assert stats["warnings"] == len(rules["warnings"])


def test_eigene_stereotypen() -> None:
    elements = _by_name(parse_mdg(NETZ)["elementStereotypes"])

    assert set(elements) == {"Betriebsmittel", "Leitzentrale", "Messpunkt", "Netzsegment"}

    # Abstrakte Wurzel ohne Apply bleibt erhalten und wird zur Warnung.
    betriebsmittel = elements["Betriebsmittel"]
    assert betriebsmittel["abstract"] is True
    assert betriebsmittel["metaclasses"] == []
    assert betriebsmittel["appliesTo"] == []

    # Mehrere Metaklassen und mehrere Tagged Values, sortiert.
    netzsegment = elements["Netzsegment"]
    assert netzsegment["metaclasses"] == ["Class", "Object"]
    assert netzsegment["generalizes"] == ["Netzplan::Betriebsmittel"]
    assert [tag["name"] for tag in netzsegment["taggedValues"]] == [
        "laengeKm",
        "spannungsebene",
    ]
    spannung = netzsegment["taggedValues"][1]
    assert spannung["type"] == "Enum"
    assert spannung["values"] == "NS;MS;HS"
    assert spannung["default"] == "NS"
    assert spannung["unit"] == ""

    leitzentrale = elements["Leitzentrale"]
    assert leitzentrale["metaclasses"] == ["Class", "Component"]
    assert leitzentrale["taggedValues"] == []

    messpunkt = elements["Messpunkt"]
    assert messpunkt["metaclasses"] == ["Class"]
    assert messpunkt["taggedValues"][0]["name"] == "messart"


def test_eigene_konnektorregeln() -> None:
    rules = _by_id(parse_mdg(NETZ)["connectorRules"])

    assert set(rules) == {
        "cr:bindet",
        "cr:meldet",
        "cr:speist",
        "cr:uebermittelt",
    }
    assert all(rule_id.startswith("cr:") for rule_id in rules)

    # Association mit source/target-Rollen.
    speist = rules["cr:speist"]
    assert speist["stereotype"] == "speist"
    assert speist["metaclasses"] == ["Association"]
    assert speist["source"] == ["Messpunkt"]
    assert speist["target"] == ["Netzsegment"]
    assert speist["roles"] == {"source": ["source"], "target": ["target"]}

    # InformationFlow mit informationSource/informationTarget.
    uebermittelt = rules["cr:uebermittelt"]
    assert uebermittelt["metaclasses"] == ["InformationFlow"]
    assert uebermittelt["source"] == ["Messpunkt"]
    assert uebermittelt["target"] == ["Leitzentrale"]
    assert uebermittelt["roles"] == {
        "source": ["informationSource"],
        "target": ["informationTarget"],
    }

    # Dependency mit client/supplier: Reihenfolge ist Quelle -> Ziel.
    bindet = rules["cr:bindet"]
    assert bindet["metaclasses"] == ["Dependency"]
    assert bindet["source"] == ["Leitzentrale"]
    assert bindet["target"] == ["Netzsegment"]
    assert bindet["roles"] == {"source": ["client"], "target": ["supplier"]}

    # Message ohne Endpunkt-Constraints: explizit unconstrained, nicht leer.
    meldet = rules["cr:meldet"]
    assert meldet["metaclasses"] == ["Message"]
    assert meldet["source"] == ["*"]
    assert meldet["target"] == ["*"]
    assert meldet["roles"] == {"source": [], "target": []}


def test_eigene_viewpoints() -> None:
    viewpoints = parse_mdg(NETZ)["viewpoints"]
    kinds = {(entry["kind"], entry["name"]) for entry in viewpoints}

    assert kinds == {
        ("diagramProfile", "Netzdiagramm"),
        ("viewDefinition", "Netzuebersicht"),
    }
    uebersicht = next(entry for entry in viewpoints if entry["name"] == "Netzuebersicht")
    assert uebersicht["alias"] == "NU"
    assert uebersicht["properties"]["diagramID"] == "NU"
    assert uebersicht["properties"]["category"] == "Netzplan"


def test_warnung_wird_gemeldet_nicht_verschluckt() -> None:
    rules = parse_mdg(NETZ)
    warnings = rules["warnings"]

    assert warnings == [
        {
            "kind": "stereotypeWithoutMetaclass",
            "subject": "Betriebsmittel",
            "detail": "kein <Apply>; auf kein UML-Element anwendbar (als abstrakt markiert)",
        }
    ]
    # Eine Warnung ist kein Fehler: das Regelwerk bleibt vollstaendig.
    assert rules["stats"]["elementStereotypes"] == 4


# --------------------------------------------------------------------------
# Stufe 2: Schema, Kanonik, Determinismus
# --------------------------------------------------------------------------


def test_regelwerk_ist_schema_konform() -> None:
    rules = parse_mdg(NETZ)
    validate_schema(rules, load_schema(SCHEMA))

    # Gegenprobe: ein manipuliertes Regelwerk faellt durch.
    broken = json.loads(dumps_rules(rules))
    broken["connectorRules"][0]["source"] = []
    with pytest.raises(SchemaError):
        validate_schema(broken, load_schema(SCHEMA))


def test_gleicher_input_gleiche_bytes() -> None:
    first = dumps_rules(parse_mdg(NETZ))
    second = dumps_rules(parse_mdg(NETZ))

    assert first == second
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == hashlib.sha256(
        second.encode("utf-8")
    ).hexdigest()


def test_datei_und_speicher_ergebnis_sind_identisch(tmp_path: Path) -> None:
    rules = parse_mdg(NETZ)
    target = write_rules(rules, tmp_path / "rules.json")

    assert target.read_bytes() == dumps_rules(rules).encode("utf-8")


def test_zweites_regelwerk_wird_unabhaengig_geladen() -> None:
    netz_allein = dumps_rules(parse_mdg(NETZ))
    admbw_allein = dumps_rules(parse_mdg(ADMBW))

    # Beide Reihenfolgen im selben Prozess: kein Uebertrag zwischen Technologien.
    first_admbw = parse_mdg(ADMBW)
    then_netz = parse_mdg(NETZ)
    assert dumps_rules(then_netz) == netz_allein

    first_netz = parse_mdg(NETZ)
    then_admbw = parse_mdg(ADMBW)
    assert dumps_rules(then_admbw) == admbw_allein
    assert dumps_rules(first_netz) == netz_allein
    assert first_admbw["source"]["technologyId"] != first_netz["source"]["technologyId"]

    # Die Regel-IDs der beiden Technologien ueberschneiden sich nicht.
    netz_ids = {rule["id"] for rule in first_netz["connectorRules"]}
    admbw_ids = {rule["id"] for rule in first_admbw["connectorRules"]}
    assert netz_ids.isdisjoint(admbw_ids)

    # Getrennte Prozesse liefern dieselben Bytes wie der laufende Prozess.
    for pfad, erwartet in ((NETZ, netz_allein), (ADMBW, admbw_allein)):
        lauf = subprocess.run(
            [sys.executable, str(RULES / "mdg_parser.py"), str(pfad)],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        assert lauf.stdout.decode("utf-8") == erwartet


# --------------------------------------------------------------------------
# Stufe 3: keine Technologie im Code
# --------------------------------------------------------------------------


def test_kernmodule_enthalten_keine_technologie_namen() -> None:
    verboten = (
        "ADMBw",
        "NAFv4",
        "Netzplan",
        "Netzsegment",
        "Betriebsmittel",
        "Stadtwerke",
        "Baustein",
        "ArchitecturalDescription",
    )
    for name in CORE_MODULES + RULES_MODULES:
        basis = ROOT if name in CORE_MODULES else RULES
        quelle = (basis / name).read_text(encoding="utf-8")
        for wort in verboten:
            assert wort not in quelle, f"{name} enthaelt technologiespezifisches Wort {wort!r}"


def test_neue_technologie_ohne_codeaenderung() -> None:
    rules = parse_mdg_bytes(_dritte_technologie(), filename="verlag.xml")

    assert rules["source"]["technologyId"] == "Verlag"
    assert rules["source"]["technologyName"] == "Verlagswesen"
    assert rules["stats"]["elementStereotypes"] == 1
    assert rules["stats"]["connectorRules"] == 1
    assert rules["stats"]["warnings"] == 0

    regel = rules["connectorRules"][0]
    assert regel["id"] == "cr:verweist"
    assert regel["source"] == ["Regal"]
    assert regel["target"] == ["Regal"]
    assert rules["elementStereotypes"][0]["name"] == "Regal"

    # Auch diese Technologie ist kanonisch und schema-konform.
    validate_schema(rules, load_schema(SCHEMA))
    assert dumps_rules(rules) == dumps_rules(
        parse_mdg_bytes(_dritte_technologie(), filename="verlag.xml")
    )


def test_bekannte_technologie_aendert_sich_durch_zweite_nicht() -> None:
    """Die ADMBw-Fixture bleibt Fixture: fremde Technologie daneben aendert nichts."""
    vorher = hashlib.sha256(dumps_rules(parse_mdg(ADMBW)).encode("utf-8")).hexdigest()
    parse_mdg(NETZ)
    parse_mdg_bytes(_dritte_technologie(), filename="verlag.xml")
    nachher = hashlib.sha256(dumps_rules(parse_mdg(ADMBW)).encode("utf-8")).hexdigest()

    assert vorher == nachher


# --------------------------------------------------------------------------
# Stufe 4: CLI
# --------------------------------------------------------------------------


def test_cli_erzeugt_regelwerk(tmp_path: Path) -> None:
    ziel = tmp_path / "rules.json"
    lauf = subprocess.run(
        [
            sys.executable,
            str(RULES / "mdg_parser.py"),
            str(NETZ),
            "--check",
            "-o",
            str(ziel),
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )

    assert "Stadtwerke Netzplan" in lauf.stderr.decode("utf-8")
    assert ziel.read_bytes() == dumps_rules(parse_mdg(NETZ)).encode("utf-8")

    # Zweiter Lauf in neuem Prozess: byte-identisch.
    wieder = tmp_path / "rules2.json"
    subprocess.run(
        [sys.executable, str(RULES / "mdg_parser.py"), str(NETZ), "--check", "-o", str(wieder)],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    assert wieder.read_bytes() == ziel.read_bytes()


def test_cli_bricht_bei_kaputter_technologie_laut_ab(tmp_path: Path) -> None:
    kaputt = tmp_path / "kaputt.xml"
    kaputt.write_text("<MDG.Technology><Documentation id=\"X\" name=\"X\"/></MDG.Technology>", encoding="utf-8")
    lauf = subprocess.run(
        [sys.executable, str(RULES / "mdg_parser.py"), str(kaputt)],
        cwd=ROOT,
        capture_output=True,
    )

    assert lauf.returncode == 1
    assert b"fehler" in lauf.stderr.lower()
    assert lauf.stdout == b""


# --------------------------------------------------------------------------
# Stufe 5: Validator gegen das fremde Regelwerk
# --------------------------------------------------------------------------


def _element(paket: str, name: str, stereotype: str, ea_type: str = "Class") -> dict:
    return {"package": paket, "name": name, "stereotype": stereotype, "ea_type": ea_type}


def _kante(source: str, target: str, stereotype: str, ea_type: str) -> dict:
    return {
        "source": source,
        "target": target,
        "stereotype": stereotype,
        "ea_type": ea_type,
    }


def _ir(elemente: list[dict], kanten: list[dict]) -> dict:
    """IR nach IR_SPEC.md; nur die Felder, die der Validator liest."""
    return {
        "ir_version": 1,
        "technology": {
            "profile": "Netzplan",
            "name": "Stadtwerke Netzplan",
            "version": "2.4",
        },
        "packages": [{"path": "Netz"}],
        "elements": elemente,
        "connectors": kanten,
    }


def _konformes_netz() -> dict:
    """Modell, das die Regeln der fremden Technologie einhaelt."""
    return _ir(
        [
            _element("Netz", "Segment Nord", "Netzsegment"),
            _element("Netz", "Zaehler 1", "Messpunkt"),
            _element("Netz", "Warte", "Leitzentrale"),
        ],
        [
            _kante("Netz::Zaehler 1", "Netz::Segment Nord", "speist", "Association"),
            _kante("Netz::Zaehler 1", "Netz::Warte", "uebermittelt", "InformationFlow"),
            _kante("Netz::Warte", "Netz::Segment Nord", "bindet", "Dependency"),
        ],
    )


def _findings_mit(findings: list[dict], check: str) -> list[dict]:
    return [finding for finding in findings if finding["check"] == check]


def test_validator_akzeptiert_konformes_fremdmodell() -> None:
    findings = validator.validate_model(_konformes_netz(), parse_mdg(NETZ))

    # Kein "leerer Erfolg": das Modell hat Elemente und Kanten, die geprueft wurden.
    assert findings == []


def test_validator_meldet_verbotene_kante_mit_regel_id() -> None:
    modell = _konformes_netz()
    # speist laeuft Messpunkt -> Netzsegment; hier absichtlich umgedreht.
    modell["connectors"][0] = _kante(
        "Netz::Segment Nord", "Netz::Zaehler 1", "speist", "Association"
    )

    findings = validator.validate_model(modell, parse_mdg(NETZ))
    fehler = [f for f in findings if f["severity"] == "error"]

    assert len(fehler) == 1
    assert fehler[0]["check"] == "forbiddenConnectorEndpoints"
    assert fehler[0]["rule"] == "cr:speist"
    assert fehler[0]["object"] == "Netz::Segment Nord -> Netz::Zaehler 1 [speist]"
    assert "Netzsegment" in fehler[0]["message"]
    assert "Messpunkt" in fehler[0]["message"]


def test_validator_meldet_unbekannten_stereotyp_mit_objektnamen() -> None:
    modell = _konformes_netz()
    modell["elements"].append(_element("Netz", "Altbestand", "System"))

    findings = validator.validate_model(modell, parse_mdg(NETZ))
    fehler = [f for f in findings if f["severity"] == "error"]

    assert len(fehler) == 1
    assert fehler[0]["check"] == "unknownElementStereotype"
    assert fehler[0]["object"] == "Netz::Altbestand"
    assert "System" in fehler[0]["message"]
    # Die Meldung nennt das geladene Regelwerk, nicht ein eingebautes.
    assert "Stadtwerke Netzplan" in fehler[0]["message"]


def test_validator_meldet_unbekannte_konnektorregel() -> None:
    modell = _konformes_netz()
    modell["connectors"][0]["stereotype"] = "Provides"  # ADMBw-Regel, hier unbekannt

    findings = validator.validate_model(modell, parse_mdg(NETZ))
    fehler = [f for f in findings if f["severity"] == "error"]

    assert len(fehler) == 1
    assert fehler[0]["check"] == "unknownConnectorStereotype"
    assert fehler[0]["rule"] == ""
    assert "Provides" in fehler[0]["message"]


def test_validator_beachtet_fremde_wildcard_regel() -> None:
    """meldet deklariert keine Endpunkt-Constraints ('*') - also ist alles erlaubt."""
    modell = _konformes_netz()
    modell["connectors"].append(
        _kante("Netz::Segment Nord", "Netz::Warte", "meldet", "Message")
    )

    assert validator.validate_model(modell, parse_mdg(NETZ)) == []


def test_validator_trennt_warnung_von_fehler() -> None:
    modell = _konformes_netz()
    # Abstrakter Stereotyp: Warnung, kein Fehler.
    modell["elements"].append(_element("Netz", "Sammelschiene", "Betriebsmittel"))
    # Unbekannter Stereotyp: Fehler.
    modell["elements"].append(_element("Netz", "Altbestand", "System"))

    findings = validator.validate_model(modell, parse_mdg(NETZ))
    summary = validator.summarize(findings)

    assert summary == {"total": 2, "error": 1, "warning": 1}
    # Kanonische Sortierung: Fehler stehen vor Warnungen.
    assert findings[0]["severity"] == "error"
    assert findings[0]["check"] == "unknownElementStereotype"
    assert findings[1]["severity"] == "warning"
    assert findings[1]["check"] == "abstractElementStereotype"
    assert findings[1]["object"] == "Netz::Sammelschiene"


def test_validator_findings_sind_deterministisch() -> None:
    modell = _konformes_netz()
    modell["elements"].append(_element("Netz", "Altbestand", "System"))
    rules = parse_mdg(NETZ)

    first = validator.dumps_findings(validator.validate_model(modell, rules))
    second = validator.dumps_findings(validator.validate_model(modell, rules))

    assert first == second
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == hashlib.sha256(
        second.encode("utf-8")
    ).hexdigest()


def test_validator_laedt_zweites_regelwerk_unabhaengig(tmp_path: Path) -> None:
    netz_datei = write_rules(parse_mdg(NETZ), tmp_path / "rules_netz.json")
    admbw_datei = write_rules(parse_mdg(ADMBW), tmp_path / "rules_admbw.json")

    netz = validator.load_rules(netz_datei)
    admbw = validator.load_rules(admbw_datei)

    assert netz.name == "Stadtwerke Netzplan"
    assert admbw.name != netz.name
    assert set(netz.connectors) == {"bindet", "meldet", "speist", "uebermittelt"}
    assert "speist" not in admbw.connectors
    assert set(netz.elements) == {"Betriebsmittel", "Leitzentrale", "Messpunkt", "Netzsegment"}

    # Dasselbe Modell: gegen die eigene Technologie konform, gegen ADMBw nicht.
    modell = _konformes_netz()
    assert validator.validate_model(modell, netz) == []
    fremd = validator.validate_model(modell, admbw)
    assert validator.summarize(fremd)["error"] >= 1
    assert any("nicht definiert" in finding["message"] for finding in fremd)


def test_validator_cli_meldet_verstoss_mit_exit_1(tmp_path: Path) -> None:
    rules_datei = write_rules(parse_mdg(NETZ), tmp_path / "rules.json")
    modell = _konformes_netz()
    modell["connectors"][0] = _kante(
        "Netz::Segment Nord", "Netz::Zaehler 1", "speist", "Association"
    )
    ir_datei = tmp_path / "modell.json"
    ir_datei.write_text(json.dumps(modell, ensure_ascii=False), encoding="utf-8")
    findings_datei = tmp_path / "findings.json"

    lauf = subprocess.run(
        [
            sys.executable,
            str(ROOT / "validator.py"),
            str(ir_datei),
            str(rules_datei),
            "-o",
            str(findings_datei),
        ],
        cwd=ROOT,
        capture_output=True,
    )

    assert lauf.returncode == 1
    assert "1 Findings: 1 Fehler" in lauf.stderr.decode("utf-8")
    geschrieben = json.loads(findings_datei.read_text(encoding="utf-8"))
    assert geschrieben == validator.validate_model(modell, parse_mdg(NETZ))
    assert geschrieben[0]["rule"] == "cr:speist"
    assert "Messpunkt" in geschrieben[0]["message"]


def test_validator_cli_konformes_modell_exit_0(tmp_path: Path) -> None:
    rules_datei = write_rules(parse_mdg(NETZ), tmp_path / "rules.json")
    ir_datei = tmp_path / "modell.json"
    ir_datei.write_text(json.dumps(_konformes_netz(), ensure_ascii=False), encoding="utf-8")

    lauf = subprocess.run(
        [sys.executable, str(ROOT / "validator.py"), str(ir_datei), str(rules_datei)],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )

    assert json.loads(lauf.stdout.decode("utf-8")) == []
    assert "0 Findings" in lauf.stderr.decode("utf-8")
