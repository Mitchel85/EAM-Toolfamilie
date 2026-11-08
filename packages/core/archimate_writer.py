"""archimate_writer.py -- IR -> ArchiMate 3.2 Model Exchange XML.

Bestimmung
----------
Nimmt das IR aus ``qea_reader`` (``with_refs=True, with_owners=True``) und
schreibt eine Datei nach dem Open-Group-Format ``archimate3_Model.xsd``.
Damit ist ArchiMate ein viertes Ausgabeformat neben ``.qea``, ``.xmi`` und
``.json`` -- dieselbe Quelle, dasselbe Governance-Gate, anderes Ziel.

Kernentscheidungen (alle deterministisch)
-----------------------------------------
- **Keine 1:1-Uebersetzung.** Der NAFv4.1-ArchiMate-Guide (2026.06) sagt
  ausdruecklich, dass NAF-Elemente auf *mehrere* ArchiMate-Typen zeigen. Das
  Mapping hier ist eine Ingenieursentscheidung und steht als Tabelle im Modul,
  nicht versteckt im Code. Elemente ohne Stereotyp fallen sichtbar auf
  ``Grouping``/``Requirement`` zurueck und werden gezaehlt.
- **Ports, Parts, Pins haben kein ArchiMate-Konzept.** Kanten daran werden auf
  das Traegerelement gezogen (IR-Feld ``owner``). Ohne diese Aufloesung
  verliert MASC rund 200 Kanten.
- **Beziehungen werden gegen die ArchiMate-Matrix geprueft.** Quelle ist
  ``archimate/relationships.xml`` aus Archi (EPL-2.0). Illegale Kanten werden
  ueber ``Realization -> Serving -> Association`` umgebaut und im Report
  ausgewiesen -- nicht stillschweigend umgedeutet.
- **Keine Zeitstempel, keine Zufallswerte.** Kennung ist die IR-GUID (sonst
  SHA-256 aus Paketpfad|Stereotyp|Name). Zwei Laeufe -> gleiche Bytes.
- **Laut statt still:** ungueltiges IR bricht mit ``ArchimateWriterError`` ab.

Oeffentliche API::

    from archimate_writer import render_bytes, write_archimate, ArchimateReport

    daten = render_bytes(ir)                 # bytes
    report = write_archimate(ir, "modell.xml")
"""

from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, NoReturn, Sequence
from xml.dom import minidom

NS = "http://www.opengroup.org/xsd/archimate/3.0/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
IR_VERSION = 1

MATRIX_DIR = Path(__file__).resolve().parent / "archimate"


class ArchimateWriterError(ValueError):
    """IR oder Zielformat nicht darstellbar -- Abbruch statt Teil-Erfolg."""


# --------------------------------------------------------------------------
# Mapping ADMBw/NAF -> ArchiMate 3.2
# --------------------------------------------------------------------------
ELEMENT_MAP: Mapping[str, str] = {
    # Strategie / Konzepte
    "Capability": "Capability",
    "FieldedCapability": "Capability",
    "CapabilityConfiguration": "Grouping",
    "CapabilityRole": "BusinessRole",
    "EnterpriseGoal": "Goal",
    "EnterpriseVision": "Goal",
    "HighLevelOperationalConcept": "BusinessObject",
    "EnduringTask": "BusinessFunction",
    "ActualEnduringTask": "BusinessProcess",
    "StrategicConstraint": "Constraint",
    "OperationalConstraint": "Constraint",
    "ResourceConstraint": "Constraint",
    "Constraint": "Constraint",
    "ServicePolicy": "Requirement",
    "Principle": "Principle",
    "Driver": "Driver",
    "Goal": "Goal",
    "Outcome": "Outcome",
    "Value": "Value",
    "CourseOfAction": "CourseOfAction",
    # Operative Ebene
    "OperationalPerformer": "BusinessRole",
    "OperationalRole": "BusinessRole",
    "OperationalActivity": "BusinessProcess",
    "OperationalActivityAction": "BusinessProcess",
    "StandardOperationalActivity": "BusinessProcess",
    "OperationalArchitecture": "Grouping",
    "OperationalStateDescription": "Grouping",
    "Organization": "BusinessActor",
    "ActualOrganization": "BusinessActor",
    "Post": "BusinessRole",
    "ActualPost": "BusinessRole",
    "ActualPerson": "BusinessActor",
    "Location": "Location",
    "ActualLocation": "Location",
    "Environment": "Grouping",
    "ActualEnvironment": "Grouping",
    "WholeLifeEnterprise": "Grouping",
    "WholeLifeConfiguration": "Grouping",
    "VersionOfConfiguration": "Artifact",
    "EnterprisePhase": "Plateau",
    "ActualEnterprisePhase": "Plateau",
    "Project": "WorkPackage",
    "ActualProject": "WorkPackage",
    "ProjectMilestone": "Deliverable",
    "ActualProjectMilestone": "Deliverable",
    "ProjectMilestoneRole": "BusinessRole",
    "MeasurementType": "Constraint",
    "Measurement": "Constraint",
    "Finding": "Assessment",
    "Recommendation": "Assessment",
    "Issue": "Assessment",
    "SMEReference": "BusinessActor",
    # Information
    "InformationElement": "BusinessObject",
    "DataElement": "DataObject",
    "DataModel": "Grouping",
    "DocumentReference": "Artifact",
    "GlossaryEntry": "BusinessObject",
    "GlossaryCategory": "Grouping",
    "Information": "BusinessObject",
    # Services / Anwendungen
    "ServiceSpecification": "ApplicationService",
    "ServiceSpecificationRole": "ApplicationService",
    "ServiceFunction": "ApplicationFunction",
    "ServiceFunctionAction": "ApplicationFunction",
    "Function": "BusinessFunction",
    "FunctionAction": "BusinessFunction",
    "ServiceInterface": "ApplicationInterface",
    "ResourceInterface": "ApplicationInterface",
    "ServicePort": "ApplicationInterface",
    "ResourcePort": "ApplicationInterface",
    "Software": "ApplicationComponent",
    "System": "ApplicationComponent",
    # Technik
    "Protocol": "TechnologyInterface",
    "Protocolstack": "TechnologyInterface",
    "ProtocolLayer": "TechnologyInterface",
    "ResourceArtifact": "Artifact",
    "ResourceArchitecture": "Grouping",
    # Anforderungen
    "FunctionalRequirement": "Requirement",
    "NonfunctionalRequirement": "Requirement",
    "FulfilmentCriterion": "Requirement",
    "FitCriterion": "Requirement",
    "RequirementCategory": "Grouping",
    "RequirementCatalogue": "Grouping",
    # Katalog / Modellierung
    "Classification": "Grouping",
    "Standard": "Constraint",
    "Concern": "Driver",
    "Viewpoint": "Grouping",
    "View": "Grouping",
    "model document": "Grouping",
    "ArchitecturalDescription": "Grouping",
    "NavigationCell": "Grouping",
}

#: Nur Darstellung oder Prozessmechanik -- kein ArchiMate-Element.
SKIP_EA_TYPES = frozenset({
    "text", "note", "boundary", "activitypartition", "lane", "pool",
    "state", "statenode", "decision", "event", "synchronization", "mergenode",
    "statemachine", "proxyconnector", "umlconnector", "sequence",
})

FX = {
    "Requirement": "Requirement",
    "Activity": "BusinessProcess",
    "Class": "Grouping",
    "Object": "Grouping",
    "Package": "Grouping",
}

RELATIONSHIP_MAP: Mapping[str, str] = {
    "Implements": "Realization",
    "ToBeRealizedBy": "Realization",
    "Satisfy": "Realization",
    "ConformsTo": "Realization",
    "CompliesViewpoint": "Realization",
    "CapabilityGeneralization": "Specialization",
    "ServiceSpecificationGeneralization": "Specialization",
    "PropertySetGeneralisation": "Specialization",
    "PropertySetGeneralization": "Specialization",
    "PartOfCategory": "Aggregation",
    "OwnedMilestone": "Composition",
    "ViewsInArchitecturalDescription": "Composition",
    "ViewpointsInArchitecturalDescription": "Composition",
    "ServiceMessage": "Flow",
    "OperationalMessage": "Flow",
    "OperationalControlFlow": "Triggering",
    "JustifiedBy": "Association",
    "DerivedFrom": "Association",
    "Evaluates": "Association",
    "RatifiedStandards": "Association",
    "StakeholderConcern": "Association",
    "ConcernForView": "Association",
    "ConcernForViewpoint": "Association",
    "ConcernForActualEnterprisePhase": "Association",
    "ViewpointToStakeholder": "Association",
    "Classified": "Association",
    "ArchitectureForProject": "Association",
    "OriginatesFrom": "Association",
}

TYPE_MAP: Mapping[str, str | None] = {
    "Realisation": "Realization",
    "Realization": "Realization",
    "Generalization": "Specialization",
    "Aggregation": "Aggregation",
    "Composition": "Composition",
    "InformationFlow": "Flow",
    "ControlFlow": "Triggering",
    "ObjectFlow": "Flow",
    "Sequence": "Triggering",
    "StateFlow": "Triggering",
    "Abstraction": "Realization",
    "Dependency": "Serving",
    "Usage": "Serving",
    "Association": "Association",
    "Connector": "Serving",
    "Trace": "Association",
    "NoteLink": None,
}

FALLBACKS = ("Realization", "Serving", "Association")


# --------------------------------------------------------------------------
# Matrix
# --------------------------------------------------------------------------
def load_matrix(pfad: Path | None = None) -> dict[tuple[str, str], set[str]]:
    """Liest die ArchiMate-Beziehungsmatrix (Archi, EPL-2.0)."""
    basis = pfad or MATRIX_DIR / "relationships.xml"
    keys_datei = basis.with_name("relationships-keys.xml")
    if not basis.exists() or not keys_datei.exists():
        raise ArchimateWriterError(
            f"Beziehungsmatrix fehlt: {basis} (erwartet relationships.xml + relationships-keys.xml)"
        )
    keys = {
        k.get("char"): (k.get("relationship") or "").replace("Relationship", "")
        for k in ET.parse(keys_datei).getroot().iter("key")
    }
    matrix: dict[tuple[str, str], set[str]] = {}
    for quelle in ET.parse(basis).getroot().iter("source"):
        q = quelle.get("concept") or ""
        for ziel in quelle.iter("target"):
            for buchstabe in ziel.get("relations") or "":
                rel = keys.get(buchstabe)
                if rel:
                    matrix.setdefault((q, rel), set()).add(ziel.get("concept") or "")
    return matrix


def _erlaubt(matrix, quelle: str, rel: str, ziel: str) -> bool:
    if rel == "Association":
        return True
    return ziel in matrix.get((quelle, rel), set())


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
@dataclass
class ArchimateReport:
    elements: int = 0
    relationships: int = 0
    remapped: int = 0
    unresolved: int = 0
    skipped_display: int = 0
    skipped_package: int = 0
    collapsed: int = 0
    fallback: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_relation: dict[str, int] = field(default_factory=dict)
    unresolved_by_type: dict[str, int] = field(default_factory=dict)
    unmapped: tuple[dict[str, str], ...] = ()
    remap_samples: tuple[dict[str, str], ...] = ()


def _fail(message: str) -> NoReturn:
    raise ArchimateWriterError(message)


# --------------------------------------------------------------------------
# IR lesen
# --------------------------------------------------------------------------
def _text(value: Any, what: str, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        _fail(f"{what}: Zeichenkette erwartet, gefunden {type(value).__name__}")
    return value.strip()


def _roh(value: Any, what: str, *, default: str = "") -> str:
    """Wie _text, aber ohne Trimmen -- Referenzen sind exakt zu vergleichen."""
    if value is None:
        return default
    if not isinstance(value, str):
        _fail(f"{what}: Zeichenkette erwartet, gefunden {type(value).__name__}")
    return value


def _sequence(value: Any, what: str) -> Sequence[Any]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        _fail(f"{what}: Liste erwartet, gefunden {type(value).__name__}")
    return value


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{what}: Objekt erwartet, gefunden {type(value).__name__}")
    return value


def _kennung(guid: str, ref: str) -> str:
    roh = guid.strip("{}").lower() if guid else ""
    if not roh:
        roh = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:32]
    sicher = "".join(c if c.isalnum() or c in "-._" else "-" for c in roh)
    return "id-" + sicher


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------
def _aufbau(ir: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], ArchimateReport]:
    obj = _mapping(ir, "IR")
    if obj.get("ir_version") != IR_VERSION:
        _fail(f"ir_version: erwartet {IR_VERSION}, gefunden {obj.get('ir_version')!r}")

    report = ArchimateReport()
    roh_elemente = _sequence(obj.get("elements"), "elements")
    roh_kanten = _sequence(obj.get("connectors"), "connectors")
    if not roh_elemente:
        _fail("elements: das IR enthaelt kein Element -- Abbruch statt leerer Datei")

    # Index ref -> Element
    nach_ref: dict[str, Mapping[str, Any]] = {}
    for index, eintrag in enumerate(roh_elemente):
        e = _mapping(eintrag, f"elements[{index}]")
        ref = _roh(e.get("ref"), f"elements[{index}].ref")
        if not ref:
            _fail(
                f"elements[{index}]: 'ref' fehlt -- ArchiMate braucht stabile Referenzen "
                "(read_qea_ex(..., with_refs=True))"
            )
        if ref in nach_ref:
            _fail(f"elements[{index}]: Referenz {ref!r} ist doppelt")
        nach_ref[ref] = e

    # Ports/Parts/Pins auf ihren Traeger ziehen (auch ueber Ketten)
    roh_owner: dict[str, str] = {}
    for ref, e in nach_ref.items():
        owner = _roh(e.get("owner"), f"{ref}.owner")
        if owner:
            roh_owner[ref] = owner

    def _wurzel(ref: str) -> str:
        gesehen: set[str] = set()
        while ref in roh_owner and ref not in gesehen:
            gesehen.add(ref)
            ref = roh_owner[ref]
        return ref

    ersatz = {ref: _wurzel(ref) for ref in roh_owner}

    elemente: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    typen: dict[str, str] = {}
    for ref, e in nach_ref.items():
        ea_type = _text(e.get("ea_type"), f"{ref}.ea_type").lower()
        stereo = _text(e.get("stereotype"), f"{ref}.stereotype")
        if ref in roh_owner:
            # Traeger-Aufloesung: das Detailelement selbst entfaellt,
            # seine Kanten laufen auf das Traegerelement.
            report.collapsed += 1
            continue
        if ea_type in SKIP_EA_TYPES:
            report.skipped_display += 1
            continue
        if ea_type == "package" and not stereo:
            report.skipped_package += 1
            continue
        ziel_typ = ELEMENT_MAP.get(stereo)
        if not ziel_typ:
            ziel_typ = FX.get(_text(e.get("ea_type"), f"{ref}.ea_type"))
            if ziel_typ:
                report.fallback[ea_type or "?"] = report.fallback.get(ea_type or "?", 0) + 1
        if not ziel_typ:
            report.unmapped = report.unmapped + ({
                "ref": ref,
                "name": _text(e.get("name"), f"{ref}.name"),
                "ea_type": ea_type,
                "stereotype": stereo,
            },)
            continue
        kennung = _kennung(_text(e.get("guid"), f"{ref}.guid"), ref)
        ids[ref] = kennung
        typen[ref] = ziel_typ
        elemente.append({
            "id": kennung,
            "ref": ref,
            "type": ziel_typ,
            "name": _text(e.get("name"), f"{ref}.name") or "(ohne Namen)",
            "notes": _text(e.get("notes"), f"{ref}.notes"),
            "stereotype": stereo,
            "ea_type": _text(e.get("ea_type"), f"{ref}.ea_type"),
            "package": _text(e.get("package"), f"{ref}.package"),
            "guid": _text(e.get("guid"), f"{ref}.guid"),
        })
        report.by_type[ziel_typ] = report.by_type.get(ziel_typ, 0) + 1

    if not elemente:
        _fail("kein Element mit ArchiMate-Abbildung -- Abbruch")

    # Pakete, auf die Kanten zeigen, werden zu Grouping-Elementen
    pakete = {
        _roh(p.get("path"), f"packages[{i}].path"): p
        for i, p in enumerate(_sequence(obj.get("packages"), "packages"))
        if _roh(p.get("path"), f"packages[{i}].path")
    }
    paket_ids: dict[str, str] = {}
    for index, eintrag in enumerate(roh_kanten):
        c = _mapping(eintrag, f"connectors[{index}]")
        for seite in ("source", "target"):
            ref = _roh(c.get(seite), f"connectors[{index}].{seite}")
            if not ref or ref in ids or ref in paket_ids:
                continue
            paket = pakete.get(ref)
            if paket is None:
                continue
            stereo = _text(paket.get("stereotype"), f"{ref}.stereotype")
            ziel_typ = ELEMENT_MAP.get(stereo) if stereo else None
            if not ziel_typ:
                continue
            kennung = _kennung(_text(paket.get("guid"), f"{ref}.guid"), ref)
            paket_ids[ref] = kennung
            ids[ref] = kennung
            typen[ref] = ziel_typ
            elemente.append({
                "id": kennung,
                "ref": ref,
                "type": ziel_typ,
                "name": ref.rsplit("/", 1)[-1],
                "notes": _text(paket.get("notes"), f"{ref}.notes"),
                "stereotype": stereo,
                "ea_type": "Package",
                "package": ref.rsplit("/", 1)[0] if "/" in ref else "",
                "guid": _text(paket.get("guid"), f"{ref}.guid"),
            })
            report.by_type[ziel_typ] = report.by_type.get(ziel_typ, 0) + 1

    # Kanten
    matrix = load_matrix()
    kanten: list[dict[str, Any]] = []
    gesehen: set[tuple[str, str, str]] = set()
    for index, eintrag in enumerate(roh_kanten):
        c = _mapping(eintrag, f"connectors[{index}]")
        ea_type = _text(c.get("ea_type"), f"connectors[{index}].ea_type")
        stereo = _text(c.get("stereotype"), f"connectors[{index}].stereotype")
        rel = RELATIONSHIP_MAP.get(stereo) or TYPE_MAP.get(ea_type)
        if not rel:
            continue

        quelle = _roh(c.get("source"), f"connectors[{index}].source")
        ziel = _roh(c.get("target"), f"connectors[{index}].target")
        quelle = ersatz.get(quelle, quelle)
        ziel = ersatz.get(ziel, ziel)
        for seite, ref in (("source", quelle), ("target", ziel)):
            if ref and ref not in ids:
                report.unresolved += 1
                grund = _text(nach_ref.get(ref, {}).get("ea_type"), "ea_type") or "paket/unbekannt"
                report.unresolved_by_type[grund] = report.unresolved_by_type.get(grund, 0) + 1
                break
        else:
            if quelle == ziel:
                continue
            qtyp, ztyp = typen[quelle], typen[ziel]
            gewaehlt = rel
            if not _erlaubt(matrix, qtyp, rel, ztyp):
                gewaehlt = next(
                    (k for k in FALLBACKS if _erlaubt(matrix, qtyp, k, ztyp)), "Association"
                )
                report.remapped += 1
                if len(report.remap_samples) < 10:
                    report.remap_samples = report.remap_samples + ({
                        "von": rel, "nach": gewaehlt, "quelle": qtyp, "ziel": ztyp,
                    },)
            schluessel = (quelle, ziel, gewaehlt)
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            kanten.append({
                "id": _kennung(_text(c.get("guid"), f"connectors[{index}].guid"),
                               f"{quelle}>{ziel}>{gewaehlt}"),
                "type": gewaehlt,
                "source": ids[quelle],
                "target": ids[ziel],
                "name": _text(c.get("name"), f"connectors[{index}].name"),
            })
            report.by_relation[gewaehlt] = report.by_relation.get(gewaehlt, 0) + 1

    report.elements = len(elemente)
    report.relationships = len(kanten)
    return elemente, kanten, report


def render_bytes(ir: Any, *, modellname: str = "") -> bytes:
    """IR -> ArchiMate-XML als Bytes (deterministisch)."""
    elemente, kanten, _ = _aufbau(ir)
    ET.register_namespace("", NS)
    ET.register_namespace("xsi", XSI)

    name = modellname or "Modell"
    root = ET.Element(f"{{{NS}}}model", {
        "identifier": "id-model-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12],
        "version": "3.2",
    })
    ET.SubElement(root, f"{{{NS}}}name", {"xml:lang": "de"}).text = name

    block = ET.SubElement(root, f"{{{NS}}}elements")
    for e in elemente:
        el = ET.SubElement(block, f"{{{NS}}}element", {
            "identifier": e["id"], f"{{{XSI}}}type": e["type"],
        })
        ET.SubElement(el, f"{{{NS}}}name", {"xml:lang": "de"}).text = e["name"]
        if e["notes"]:
            ET.SubElement(el, f"{{{NS}}}documentation", {"xml:lang": "de"}).text = e["notes"]
        props = ET.SubElement(el, f"{{{NS}}}properties")
        for pid, wert in (
            ("prop-admbw-stereotype", e["stereotype"]),
            ("prop-admbw-metatype", e["ea_type"]),
            ("prop-ea-guid", e["guid"]),
            ("prop-paketpfad", e["package"]),
        ):
            if wert:
                ET.SubElement(props, f"{{{NS}}}property", {"propertyDefinitionRef": pid}).append(
                    _wert(wert)
                )

    block = ET.SubElement(root, f"{{{NS}}}relationships")
    for k in kanten:
        rel = ET.SubElement(block, f"{{{NS}}}relationship", {
            "identifier": k["id"], f"{{{XSI}}}type": k["type"],
            "source": k["source"], "target": k["target"],
        })
        if k["name"]:
            ET.SubElement(rel, f"{{{NS}}}name", {"xml:lang": "de"}).text = k["name"]

    defs = ET.SubElement(root, f"{{{NS}}}propertyDefinitions")
    for pid, pname in (
        ("prop-admbw-stereotype", "ADMBw_Stereotyp"),
        ("prop-admbw-metatype", "ADMBw_Metaklasse"),
        ("prop-ea-guid", "Sparx_EA_GUID"),
        ("prop-paketpfad", "Paketpfad"),
    ):
        d = ET.SubElement(defs, f"{{{NS}}}propertyDefinition", {"identifier": pid, "type": "string"})
        ET.SubElement(d, f"{{{NS}}}name", {"xml:lang": "en"}).text = pname

    roh = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(roh).toprettyxml(indent="  ", encoding="utf-8")


def _wert(text: str) -> ET.Element:
    v = ET.Element(f"{{{NS}}}value", {"xml:lang": "de"})
    v.text = text
    return v


def write_archimate(ir: Any, path: str | Path, *, modellname: str = "") -> ArchimateReport:
    """Schreibt die Datei und liefert den Report."""
    daten = render_bytes(ir, modellname=modellname)
    ziel = Path(path)
    ziel.write_bytes(daten)
    _, _, report = _aufbau(ir)
    return report


# --------------------------------------------------------------------------
# CLI (eigenstaendig, zusaetzlich zum eam-ai-Unterbefehl)
# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="archimate_writer",
        description="IR (.qea/.json) -> ArchiMate 3.2 Model Exchange XML",
    )
    parser.add_argument("--ir", required=True, type=Path, help="IR-JSON oder .qea")
    parser.add_argument("--out", "-o", required=True, type=Path, help="Zieldatei (.xml)")
    parser.add_argument("--report", type=Path, default=None, help="Report als JSON")
    args = parser.parse_args(argv)

    if args.ir.suffix.lower() == ".qea":
        from qea_reader import read_qea_ex

        ir, _ = read_qea_ex(args.ir, with_refs=True, with_owners=True)
        name = args.ir.stem
    else:
        ir = json.loads(args.ir.read_text(encoding="utf-8"))
        name = args.ir.stem

    report = write_archimate(ir, args.out, modellname=name)
    daten = {
        "elements": report.elements,
        "relationships": report.relationships,
        "remapped": report.remapped,
        "unresolved": report.unresolved,
        "skipped_display": report.skipped_display,
        "skipped_package": report.skipped_package,
        "collapsed": report.collapsed,
        "fallback": report.fallback,
        "by_type": report.by_type,
        "by_relation": report.by_relation,
        "unresolved_by_type": report.unresolved_by_type,
    }
    print(json.dumps(daten, ensure_ascii=False, indent=2))
    if args.report:
        args.report.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
