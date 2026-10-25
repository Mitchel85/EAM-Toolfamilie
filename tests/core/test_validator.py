"""Abnahmetests fuer validator.py: IR gegen Regelwerk pruefen.

Deckt die Definition of Done ab:
  * unbekannter Stereotyp -> Fehler mit Objektname
  * verbotene Kante -> Fehler mit Regel-ID
  * fehlende Pflichtbeziehung -> Warnung
  * findings.json als Liste mit Schweregrad, Objekt, Regel, Meldung
  * keine stille Korrektur, deterministische Ausgabe

Alle Fixtures sind synthetisch (keine echten Modelle, keine Personendaten).
"""

from __future__ import annotations

import copy
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
if str(ROOT) not in sys.path:  # pragma: no cover - Import-Komfort
    sys.path.insert(0, str(ROOT))

import rules_schema  # noqa: E402
from validator import ValidatorError, build_rules, dumps_findings, validate_model  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"  # Monorepo
RULES_PATH = FIXTURES / "rules_validator.json"
REQUIREMENTS_PATH = FIXTURES / "requirements_validator.json"
SCHEMA_PATH = ROOT / "rules.schema.json"


# --------------------------------------------------------------------------
# Fixtures (synthetisch)
# --------------------------------------------------------------------------


def rules_document() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def requirements_document() -> list[dict]:
    return json.loads(REQUIREMENTS_PATH.read_text(encoding="utf-8"))


def clean_ir() -> dict:
    """Modell, das alle Regeln und alle Pflichtbeziehungen erfuellt."""
    return {
        "ir_version": 1,
        "technology": {"profile": "Synthetisch", "name": "Synthetisches Modell", "version": "1.0"},
        "packages": [
            {"path": "Modell"},
            {"path": "Modell/Komponenten"},
            {"path": "Modell/Schnittstellen", "stereotype": "ArchitecturalDescription"},
        ],
        "elements": [
            {"package": "Modell/Komponenten", "name": "System A", "stereotype": "System", "ea_type": "Class"},
            {"package": "Modell/Komponenten", "name": "System B", "stereotype": "System", "ea_type": "Class"},
            {"package": "Modell/Komponenten", "name": "Dienst C", "stereotype": "ServiceSpecification", "ea_type": "Class"},
            {"package": "Modell/Komponenten", "name": "Faehigkeit F", "stereotype": "Capability", "ea_type": "Class"},
            {"package": "Modell/Komponenten", "name": "Aktivitaet V", "stereotype": "OperationalActivity", "ea_type": "Class"},
            {"package": "Modell/Komponenten", "name": "Bedingung B", "stereotype": "ActualCondition", "ea_type": "Class"},
            {"package": "Modell/Schnittstellen", "name": "Port X", "stereotype": "ServicePort", "ea_type": "Port"},
            {"package": "Modell/Schnittstellen", "name": "Port Y", "stereotype": "ServicePort", "ea_type": "Port"},
            {"package": "Modell/Schnittstellen", "name": "Standort L", "stereotype": "ActualLocation", "ea_type": "Class"},
        ],
        "connectors": [
            {
                "source": "Modell/Komponenten::System A",
                "target": "Modell/Schnittstellen::Port X",
                "stereotype": "Provides",
                "ea_type": "Dependency",
            },
            {
                "source": "Modell/Komponenten::System B",
                "target": "Modell/Schnittstellen::Port Y",
                "stereotype": "Provides",
                "ea_type": "Dependency",
            },
            {
                "source": "Modell/Komponenten::Faehigkeit F",
                "target": "Modell/Komponenten::Dienst C",
                "stereotype": "Exhibits",
                "ea_type": "Abstraction",
            },
            {
                "source": "Modell/Komponenten::Aktivitaet V",
                "target": "Modell/Komponenten::Dienst C",
                "stereotype": "ActivitySupportsService",
                "ea_type": "Realisation",
            },
            {
                "source": "Modell/Schnittstellen::Standort L",
                "target": "Modell/Komponenten::Bedingung B",
                "stereotype": "LocatedIn",
                "ea_type": "Dependency",
            },
            {
                "source": "Modell/Komponenten::Faehigkeit F",
                "target": "Modell/Komponenten::Faehigkeit F",
                "stereotype": "DependsOn",
                "ea_type": "Dependency",
            },
        ],
        "diagrams": [],
    }


def validate(ir: dict | None = None, rules: dict | None = None, requirements=None):
    return validate_model(
        clean_ir() if ir is None else ir,
        rules_document() if rules is None else rules,
        requirements_document() if requirements is None else requirements,
    )


def by_check(findings, check: str) -> list[dict]:
    return [finding for finding in findings if finding["check"] == check]


def element(ir: dict, name: str) -> dict:
    matches = [item for item in ir["elements"] if item["name"] == name]
    assert len(matches) == 1, f"Fixture-Element {name!r} nicht eindeutig"
    return matches[0]


# --------------------------------------------------------------------------
# Sauberer Lauf, Determinismus, keine Nebenwirkungen
# --------------------------------------------------------------------------


def test_rules_fixture_entspricht_dem_schema() -> None:
    """Das synthetische Regelwerk ist ein gueltiges rules.json."""
    rules_schema.validate(rules_document(), rules_schema.load_schema(SCHEMA_PATH))


def test_sauberes_modell_erzeugt_keine_findings() -> None:
    assert validate() == []


def test_ir_und_regelwerk_bleiben_unveraendert() -> None:
    ir = clean_ir()
    rules = rules_document()
    requirements = requirements_document()
    before = copy.deepcopy((ir, rules, requirements))
    validate(ir, rules, requirements)
    assert (ir, rules, requirements) == before


def test_findings_sind_byte_identisch_bei_wiederholung() -> None:
    first = dumps_findings(validate())
    second = dumps_findings(validate())
    assert first == second


def test_findings_sind_unabhaengig_von_der_ir_reihenfolge() -> None:
    reference = dumps_findings(validate())
    shuffled = clean_ir()
    rng = random.Random(20261021)
    rng.shuffle(shuffled["elements"])
    rng.shuffle(shuffled["connectors"])
    assert dumps_findings(validate(shuffled)) == reference


# --------------------------------------------------------------------------
# Element- und Paket-Stereotype
# --------------------------------------------------------------------------


def test_unbekannter_element_stereotyp_ist_fehler_mit_objektname() -> None:
    ir = clean_ir()
    element(ir, "System A")["stereotype"] = "Unbekannt"
    findings = validate(ir)
    unknown = by_check(findings, "unknownElementStereotype")
    assert len(unknown) == 1
    assert unknown[0]["severity"] == "error"
    assert unknown[0]["object"] == "Modell/Komponenten::System A"
    assert unknown[0]["rule"] == ""
    assert "'Unbekannt'" in unknown[0]["message"]


def test_kommaliste_meldet_nur_den_unbekannten_teil() -> None:
    ir = clean_ir()
    element(ir, "System A")["stereotype"] = "System, Unbekannt"
    unknown = by_check(validate(ir), "unknownElementStereotype")
    assert len(unknown) == 1
    assert "'Unbekannt'" in unknown[0]["message"]
    assert unknown[0]["object"] == "Modell/Komponenten::System A"


def test_leerer_stereotyp_ist_erlaubt() -> None:
    ir = clean_ir()
    ir["elements"].append({"package": "Modell/Komponenten", "name": "Notiz", "notes": "ohne Stereotyp"})
    findings = validate(ir)
    assert by_check(findings, "unknownElementStereotype") == []
    assert findings == []


def test_kantenstereotyp_auf_element_wird_mit_hinweis_gemeldet() -> None:
    ir = clean_ir()
    element(ir, "System A")["stereotype"] = "Provides"
    unknown = by_check(validate(ir), "unknownElementStereotype")
    assert len(unknown) == 1
    assert "Konnektor-Regel" in unknown[0]["message"]


def test_abstrakter_stereotyp_ist_warnung() -> None:
    ir = clean_ir()
    element(ir, "System A")["stereotype"] = "MeasurableElement"
    findings = by_check(validate(ir), "abstractElementStereotype")
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert findings[0]["object"] == "Modell/Komponenten::System A"


def test_unbekanntes_paketstereotyp_ist_fehler() -> None:
    ir = clean_ir()
    ir["packages"][2]["stereotype"] = "Unbekannt"
    findings = by_check(validate(ir), "unknownPackageStereotype")
    assert len(findings) == 1
    assert findings[0]["object"] == "Modell/Schnittstellen"
    assert "'Unbekannt'" in findings[0]["message"]


def test_paketstereotyp_mit_falscher_metaklasse_ist_warnung() -> None:
    ir = clean_ir()
    ir["packages"][2]["stereotype"] = "System"
    findings = by_check(validate(ir), "elementMetaclassMismatch")
    assert len(findings) == 1
    assert findings[0]["object"] == "Modell/Schnittstellen"
    assert "Package" in findings[0]["message"]


# --------------------------------------------------------------------------
# Kanten
# --------------------------------------------------------------------------


def test_verbotene_quelle_ist_fehler_mit_regel_id() -> None:
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell/Komponenten::System A",
            "target": "Modell/Komponenten::Dienst C",
            "stereotype": "ActivitySupportsService",
            "ea_type": "Realisation",
        }
    )
    findings = by_check(validate(ir), "forbiddenConnectorEndpoints")
    assert any(finding["rule"] == "cr:ActivitySupportsService" for finding in findings)
    finding = next(item for item in findings if item["rule"] == "cr:ActivitySupportsService")
    assert finding["severity"] == "error"
    assert "Quelle" in finding["message"]
    assert "System" in finding["message"]


def test_verbotenes_ziel_ist_fehler_mit_regel_id() -> None:
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell/Komponenten::System A",
            "target": "Modell/Komponenten::Dienst C",
            "stereotype": "Provides",
            "ea_type": "Dependency",
        }
    )
    findings = by_check(validate(ir), "forbiddenConnectorEndpoints")
    assert len(findings) == 1
    assert findings[0]["rule"] == "cr:Provides"
    assert "Ziel" in findings[0]["message"]
    assert "ServiceSpecification" in findings[0]["message"]


def test_unbekanntes_kantenstereotyp_ist_fehler() -> None:
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell/Komponenten::System A",
            "target": "Modell/Schnittstellen::Port X",
            "stereotype": "Bogus",
        }
    )
    findings = by_check(validate(ir), "unknownConnectorStereotype")
    assert len(findings) == 1
    assert findings[0]["severity"] == "error"
    assert findings[0]["object"].endswith("[Bogus]")
    assert "'Bogus'" in findings[0]["message"]


def test_qualifizierte_profilreferenz_trifft_lokalen_namen() -> None:
    """cr:LocatedIn erlaubt 'Externprofil::ActualCondition'; das IR nennt nur den lokalen Namen."""
    assert by_check(validate(), "forbiddenConnectorEndpoints") == []


def test_vererbte_endpunkte_sind_erlaubt() -> None:
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell/Komponenten::Faehigkeit F",
            "target": "Modell/Komponenten::Dienst C",
            "stereotype": "DependsOn",
            "ea_type": "Dependency",
        }
    )
    assert by_check(validate(ir), "forbiddenConnectorEndpoints") == []


def test_nicht_vererbter_endpunkt_bleibt_verboten() -> None:
    """System erbt nicht von MeasurableElement, DependsOn ist dort also verboten."""
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell/Komponenten::System A",
            "target": "Modell/Komponenten::Dienst C",
            "stereotype": "DependsOn",
            "ea_type": "Dependency",
        }
    )
    findings = by_check(validate(ir), "forbiddenConnectorEndpoints")
    assert len(findings) == 1
    assert findings[0]["rule"] == "cr:DependsOn"


def test_wildcard_regel_erlaubt_jede_kante() -> None:
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell/Schnittstellen::Port X",
            "target": "Modell/Komponenten::Aktivitaet V",
            "stereotype": "StoredIn",
            "ea_type": "Dependency",
        }
    )
    assert by_check(validate(ir), "forbiddenConnectorEndpoints") == []


def test_metaklasse_der_kante_ist_warnung() -> None:
    ir = clean_ir()
    ir["connectors"][0]["ea_type"] = "Realisation"
    findings = by_check(validate(ir), "connectorMetaclassMismatch")
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert findings[0]["rule"] == "cr:Provides"
    assert "Realisation" in findings[0]["message"]


def test_mehrdeutiger_endpunkt_ist_fehler() -> None:
    ir = clean_ir()
    ir["elements"].append(
        {
            "package": "Modell/Komponenten",
            "name": "System A",
            "stereotype": "System",
            "ea_type": "Requirement",
        }
    )
    ir["connectors"].append(
        {
            "source": "Modell/Komponenten::System A",
            "target": "Modell/Schnittstellen::Port X",
            "stereotype": "Provides",
            "ea_type": "Dependency",
        }
    )
    findings = by_check(validate(ir), "ambiguousConnectorEndpoint")
    assert len(findings) == 1
    assert findings[0]["severity"] == "error"
    assert "#1, " in findings[0]["message"] and "#2" in findings[0]["message"]
    # Die Regelpruefung wird nicht geraten: keine zweite Verboten-Meldung.
    assert by_check(validate(ir), "forbiddenConnectorEndpoints") == []


def test_vorkommensnummer_loest_mehrdeutigkeit_auf() -> None:
    ir = clean_ir()
    ir["elements"].append(
        {
            "package": "Modell/Komponenten",
            "name": "System A",
            "stereotype": "System",
            "ea_type": "Requirement",
        }
    )
    # Die vorhandene Kante adressiert das zweite Vorkommen eindeutig.
    ir["connectors"][0]["source"] = "Modell/Komponenten::System A#2"
    findings = validate(ir)
    assert by_check(findings, "ambiguousConnectorEndpoint") == []
    assert by_check(findings, "forbiddenConnectorEndpoints") == []


def test_nicht_aufloesbarer_endpunkt_ist_fehler() -> None:
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell/Komponenten::Fehlt",
            "target": "Modell/Schnittstellen::Port X",
            "stereotype": "Provides",
        }
    )
    findings = by_check(validate(ir), "unresolvedConnectorEndpoint")
    assert len(findings) == 1
    assert findings[0]["severity"] == "error"
    assert "'Modell/Komponenten::Fehlt'" in findings[0]["message"]


def test_wurzelpaket_als_endpunkt_ist_fehler() -> None:
    ir = clean_ir()
    ir["connectors"].append(
        {
            "source": "Modell",
            "target": "Modell/Schnittstellen::Port X",
            "stereotype": "Provides",
        }
    )
    findings = by_check(validate(ir), "unresolvedConnectorEndpoint")
    assert len(findings) == 1
    assert "Wurzelpaket" in findings[0]["message"]


# --------------------------------------------------------------------------
# Metaklassen
# --------------------------------------------------------------------------


def test_element_metaklasse_ist_warnung() -> None:
    ir = clean_ir()
    element(ir, "System A")["ea_type"] = "Requirement"
    findings = by_check(validate(ir), "elementMetaclassMismatch")
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert "Requirement" in findings[0]["message"]


def test_fehlendes_ea_type_nutzt_writer_default() -> None:
    ir = clean_ir()
    element(ir, "Faehigkeit F").pop("ea_type")  # Default Class ist erlaubt
    assert by_check(validate(ir), "elementMetaclassMismatch") == []

    ir = clean_ir()
    element(ir, "Port X").pop("ea_type")  # Default Class ist fuer Port verboten
    findings = by_check(validate(ir), "elementMetaclassMismatch")
    assert len(findings) == 1
    assert "ea_type fehlt" in findings[0]["message"]
    assert "'Class'" in findings[0]["message"]


# --------------------------------------------------------------------------
# Pflichtbeziehungen
# --------------------------------------------------------------------------


def test_fehlende_pflichtbeziehung_ist_warnung() -> None:
    ir = clean_ir()
    ir["connectors"] = [item for item in ir["connectors"] if item["stereotype"] != "Exhibits"]
    findings = by_check(validate(ir), "missingRequiredRelationship")
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert findings[0]["rule"] == "req:CapabilityZeigtDienst"
    assert findings[0]["object"] == "Modell/Komponenten::Faehigkeit F"
    assert "Pflichtbeziehung fehlt" in findings[0]["message"]
    assert "gefunden: 0" in findings[0]["message"]


def test_pflichtbeziehung_prueft_die_zielrichtung() -> None:
    ir = clean_ir()
    ir["connectors"] = [
        item for item in ir["connectors"] if item["stereotype"] != "ActivitySupportsService"
    ]
    findings = by_check(validate(ir), "missingRequiredRelationship")
    assert len(findings) == 1
    assert findings[0]["rule"] == "req:DienstWirdGenutzt"
    assert findings[0]["object"] == "Modell/Komponenten::Dienst C"
    assert "als Ziel" in findings[0]["message"]


def test_regelwidrige_kante_erfuellt_keine_pflicht() -> None:
    ir = clean_ir()
    # Die einzige Provides-Kante von System A zeigt auf ein verbotenes Ziel.
    ir["connectors"][0]["target"] = "Modell/Komponenten::Dienst C"
    findings = validate(ir)
    assert by_check(findings, "forbiddenConnectorEndpoints")
    missing = [
        finding
        for finding in by_check(findings, "missingRequiredRelationship")
        if finding["rule"] == "req:SystemHatPort"
    ]
    assert len(missing) == 1
    assert missing[0]["object"] == "Modell/Komponenten::System A"


def test_pflichtbeziehung_im_regelwerk_wird_gelesen() -> None:
    rules = rules_document()
    rules["requiredRelationships"] = [
        {
            "id": "req:SystemHaengtAb",
            "stereotype": "System",
            "connector": "DependsOn",
            "role": "source",
            "minimum": 1,
        }
    ]
    findings = validate(rules=rules)
    assert by_check(findings, "missingRequiredRelationship")
    assert all(
        finding["rule"] == "req:SystemHaengtAb"
        for finding in by_check(findings, "missingRequiredRelationship")
    )


def test_pflichtbeziehungen_als_parameter() -> None:
    findings = validate_model(
        clean_ir(),
        rules_document(),
        [
            {
                "id": "req:OrtHatKante",
                "stereotype": "ActualLocation",
                "connector": "StoredIn",
                "role": "any",
            }
        ],
    )
    assert any(finding["rule"] == "req:OrtHatKante" for finding in findings)


# --------------------------------------------------------------------------
# Laute Fehler (kein stiller Leererfolg)
# --------------------------------------------------------------------------


def test_leeres_modell_ist_laut() -> None:
    ir = clean_ir()
    ir["elements"] = []
    with pytest.raises(ValidatorError) as error:
        validate(ir)
    assert "kein Element" in str(error.value)


def test_leeres_regelwerk_ist_laut() -> None:
    rules = rules_document()
    rules["elementStereotypes"] = []
    rules["connectorRules"] = []
    with pytest.raises(ValidatorError) as error:
        build_rules(rules)
    assert "keine Pruefregeln" in str(error.value)


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda doc: doc.update(schemaVersion=2), "schemaVersion"),
        (lambda doc: doc.pop("connectorRules"), "connectorRules"),
        (
            lambda doc: doc["connectorRules"].append(copy.deepcopy(doc["connectorRules"][0])),
            "doppelt definiert",
        ),
        (
            lambda doc: doc["connectorRules"][0].update(id="cr:Falsch"),
            "cr:ActivitySupportsService",
        ),
        (
            lambda doc: doc["connectorRules"][0].update(source=["OperationalActivity", "*"]),
            "darf nur allein stehen",
        ),
        (
            lambda doc: doc["connectorRules"][0].update(source=[], target=[]),
            "source",
        ),
        (
            lambda doc: doc["elementStereotypes"].append(
                copy.deepcopy(doc["elementStereotypes"][0])
            ),
            "doppelt definiert",
        ),
        (
            lambda doc: doc["elementStereotypes"].append(
                {
                    "name": "Provides",
                    "abstract": False,
                    "metaclasses": ["Class"],
                    "generalizes": [],
                }
            ),
            "gleichzeitig Element- und Kanten-Stereotyp",
        ),
        (
            lambda doc: doc.update(
                requiredRelationships=[
                    {"id": "req:Unbekannt", "stereotype": "GibtsNicht", "connector": "Provides"}
                ]
            ),
            "kein Element-Stereotyp",
        ),
        (
            lambda doc: doc.update(
                requiredRelationships=[
                    {"id": "req:Unbekannt", "stereotype": "System", "connector": "GibtsNicht"}
                ]
            ),
            "keine Konnektor-Regel",
        ),
        (
            lambda doc: doc.update(
                requiredRelationships=[
                    {"id": "req:Unbekannt", "stereotype": "System", "tippfehler": True}
                ]
            ),
            "unbekannte Felder",
        ),
        (
            lambda doc: doc.update(
                requiredRelationships=[
                    {"id": "req:Doppelt", "stereotype": "System", "connector": "Provides"},
                    {"id": "req:Doppelt", "stereotype": "System", "connector": "Provides"},
                ]
            ),
            "doppelt definiert",
        ),
        (
            lambda doc: doc.update(
                requiredRelationships=[
                    {"id": "req:Falsch", "stereotype": "System", "role": "mitte"}
                ]
            ),
            "role",
        ),
    ],
)
def test_kaputtes_regelwerk_ist_laut(mutate, fragment: str) -> None:
    document = rules_document()
    mutate(document)
    with pytest.raises(ValidatorError) as error:
        build_rules(document)
    assert fragment in str(error.value)


def test_kaputtes_ir_ist_laut() -> None:
    ir = clean_ir()
    ir["ir_version"] = 2
    with pytest.raises(ValidatorError) as error:
        validate(ir)
    assert "ir_version" in str(error.value)

    ir = clean_ir()
    ir["diagrams"] = [{"name": "unzulaessig"}]
    with pytest.raises(ValidatorError) as error:
        validate(ir)
    assert "diagrams" in str(error.value)

    ir = clean_ir()
    ir["packages"] = []
    with pytest.raises(ValidatorError) as error:
        validate(ir)
    assert "kein Paket" in str(error.value)


# --------------------------------------------------------------------------
# Ausgabeformat
# --------------------------------------------------------------------------


def test_findings_haben_das_vereinbarte_format() -> None:
    ir = clean_ir()
    element(ir, "System A")["stereotype"] = "Unbekannt"
    ir["connectors"] = [item for item in ir["connectors"] if item["stereotype"] != "Exhibits"]
    findings = validate(ir)
    assert findings
    for finding in findings:
        assert set(finding) == {"severity", "object", "rule", "check", "message"}
        assert finding["severity"] in {"error", "warning"}
        assert isinstance(finding["object"], str)
        assert isinstance(finding["rule"], str)
        assert finding["message"]


def test_fehler_stehen_vor_warnungen() -> None:
    ir = clean_ir()
    element(ir, "System A")["stereotype"] = "Unbekannt"
    ir["connectors"] = [item for item in ir["connectors"] if item["stereotype"] != "Exhibits"]
    severities = [finding["severity"] for finding in validate(ir)]
    assert severities == sorted(severities, key=lambda value: 0 if value == "error" else 1)
    assert severities[0] == "error"


def test_dumps_findings_ist_kanonisch() -> None:
    findings = [{"severity": "warning", "object": "b", "rule": "r", "check": "c", "message": "m"}]
    text = dumps_findings(findings)
    assert text.startswith("[\n  {")
    assert text.endswith("}\n]\n")
    assert '"check": "c"' in text


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def write_inputs(tmp_path: Path, ir: dict) -> tuple[Path, Path, Path]:
    ir_path = tmp_path / "modell.json"
    rules_path = tmp_path / "rules.json"
    requirements_path = tmp_path / "pflichten.json"
    ir_path.write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    rules_path.write_text(json.dumps(rules_document(), ensure_ascii=False), encoding="utf-8")
    requirements_path.write_text(
        json.dumps(requirements_document(), ensure_ascii=False), encoding="utf-8"
    )
    return ir_path, rules_path, requirements_path


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "validator.py"), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_cli_sauberer_lauf(tmp_path: Path) -> None:
    ir_path, rules_path, requirements_path = write_inputs(tmp_path, clean_ir())
    out = tmp_path / "findings.json"
    result = run_cli(str(ir_path), str(rules_path), "--requirements", str(requirements_path),
                     "-o", str(out), "-q")
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == "[]\n"


def test_cli_meldet_fehler_mit_exit_1(tmp_path: Path) -> None:
    ir = clean_ir()
    element(ir, "System A")["stereotype"] = "Unbekannt"
    ir_path, rules_path, requirements_path = write_inputs(tmp_path, ir)
    out = tmp_path / "findings.json"
    result = run_cli(str(ir_path), str(rules_path), "--requirements", str(requirements_path),
                     "-o", str(out), "-q")
    assert result.returncode == 1
    findings = json.loads(out.read_text(encoding="utf-8"))
    assert any(finding["severity"] == "error" for finding in findings)


def test_cli_warnungen_mit_und_ohne_strict(tmp_path: Path) -> None:
    ir = clean_ir()
    ir["connectors"] = [item for item in ir["connectors"] if item["stereotype"] != "Exhibits"]
    ir_path, rules_path, requirements_path = write_inputs(tmp_path, ir)
    base = [str(ir_path), str(rules_path), "--requirements", str(requirements_path), "-q"]
    assert run_cli(*base).returncode == 0
    assert run_cli(*base, "--strict").returncode == 1


def test_cli_stdout_ohne_ausgabedatei(tmp_path: Path) -> None:
    ir_path, rules_path, requirements_path = write_inputs(tmp_path, clean_ir())
    result = run_cli(str(ir_path), str(rules_path), "--requirements", str(requirements_path), "-q")
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_cli_kaputte_eingabe_mit_exit_3(tmp_path: Path) -> None:
    ir_path, rules_path, requirements_path = write_inputs(tmp_path, clean_ir())
    rules_path.write_text("{kaputt", encoding="utf-8")
    result = run_cli(str(ir_path), str(rules_path), "--requirements", str(requirements_path), "-q")
    assert result.returncode == 3
    assert "FEHLER" in result.stderr
