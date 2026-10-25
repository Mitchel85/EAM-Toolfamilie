#!/usr/bin/env python3
"""validator.py -- IR gegen ein Technologie-Regelwerk (rules.json) pruefen.

Zweck
-----
Vor dem Export pruefen, ob ein IR die Regeln der Technologie einhaelt.
Es wird ausschliesslich gemeldet, nie korrigiert: IR und Regelwerk bleiben
unveraendert. Jede Pruefung liefert Findings mit Schweregrad, Objekt, Regel
und Meldung; die Ausgabe ist deterministisch (gleicher Input -> gleiche Bytes).

Geprueft wird
-------------
* Element- und Paket-Stereotyp im Regelwerk bekannt?              (Fehler)
* Kanten-Stereotyp als Konnektor-Regel bekannt?                  (Fehler)
* Quelle und Ziel einer Kante nach ihrer Regel erlaubt?          (Fehler, mit Regel-ID)
* Endpunkt einer Kante aufloesbar und eindeutig?                 (Fehler, sonst
  waere die Regelpruefung still)
* Pflichtbeziehung vorhanden?                                    (Warnung)
* Abstrakter Stereotyp direkt verwendet?                         (Warnung)
* Metaklasse (ea_type) passend?                                  (Warnung)

Endpunkt-Erlaubnis
------------------
Erlaubt sind exakte Namen, lokale Namen qualifizierter Referenzen
('Profil::Stereotyp') und Spezialisierungen ueber 'generalizes': ein
Spezialist erbt die Endpunkt-Erlaubnis seines Eltern-Stereotyps. Das ist
notwendig, weil die ADMBw-MDG Endpunkte auch auf abstrakte Stereotype
(MeasurableElement, OperationalAgent, ...) einschraenkt, die nie direkt
instanziiert werden. Der Platzhalter '*' einer Regel bedeutet: keine
Einschraenkung (kein stilles 'leer = alles').

Pflichtbeziehungen
------------------
Die MDG kennt nur *erlaubte* Beziehungen (metarelationships), keine
Pflichten. Pflichtbeziehungen sind deshalb eine Projektkonvention und
kommen aus einer expliziten Liste:

    [{"id": "req:CapabilityZeigtDienst",
      "stereotype": "Capability",
      "connector": "Exhibits",
      "role": "source",            # source | target | any (Default: any)
      "minimum": 1,                 # Default: 1
      "message": "optionaler Hinweis"}]

Die Liste steht entweder als Schluessel "requiredRelationships" im
Regelwerk (Projekt-Erweiterung; mdg_parser erzeugt ihn nicht) oder in
einer eigenen Datei (--requirements). Fehlt beides, entstehen keine
Pflichtbeziehungs-Findings -- das ist kein stiller Erfolg, sondern eine
nicht aktivierte Regel. Eine Pflicht gilt auch fuer Spezialisierungen des
genannten Element-Stereotyps (generalizes); der Kanten-Stereotyp wird
exakt verglichen.

Ausgabe (findings.json)
-----------------------
Liste, kanonisch sortiert (Fehler vor Warnungen), je Eintrag:

    {"severity": "error"|"warning",
     "object":   "<paket>::<element>" | "<quelle> -> <ziel> [<stereotyp>]",
     "rule":     "cr:<stereotyp>" | "req:<id>" | "",
     "check":    "<Pruefungsname>",
     "message":  "<Meldung mit konkreten Werten>"}

Schweregrade: "error" = Regelverstoss, Export verletzt das Regelwerk;
"warning" = Auffaelligkeit, die fachlich zu pruefen ist.

Grenze zur Strukturpruefung
---------------------------
Feldnamen, Paketbaum, GUIDs und die kanonische Writer-Sortierung prueft
qea_writer.plan_model. Dieser Validator prueft das Regelwerk und die
Endpunkte, die fuer die Regelpruefung noetig sind. Kann ein Endpunkt nicht
aufgeloest werden, wird das als Fehler gemeldet, nicht uebersprungen.

Exit-Codes der CLI
------------------
0 = keine Fehler (Warnungen erlaubt), 1 = Fehler vorhanden (oder Warnungen
mit --strict), 3 = Eingabefehler (IR/Regelwerk nicht pruefbar).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

IR_VERSION = 1
SCHEMA_VERSION = 1

ERROR = "error"
WARNING = "warning"

ANY = "*"

# Metaklassen-Defaults des Writers (bewusst gespiegelt, nicht importiert:
# der Validator soll auch ohne qea_writer lauffaehig und pruefbar sein).
DEFAULT_OBJECT_TYPE = "Class"
DEFAULT_CONNECTOR_TYPE = "Dependency"

REQUIREMENT_ROLES = frozenset({"source", "target", "any"})

# EA schreibt je nach Version/Technologie beide Schreibweisen.
_METACLASS_ALIASES = {"realization": "realisation"}


class ValidatorError(ValueError):
    """IR oder Regelwerk ist strukturell nicht pruefbar."""


# --------------------------------------------------------------------------
# Kleine, laute Lesehelfer
# --------------------------------------------------------------------------


def _fail(message: str) -> NoReturn:
    raise ValidatorError(message)


def _type_name(value: Any) -> str:
    return type(value).__name__


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{what}: Objekt erwartet, gefunden {_type_name(value)}")
    return value


def _sequence(value: Any, what: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(f"{what}: Liste erwartet, gefunden {_type_name(value)}")
    return value


def _text(
    value: Any,
    what: str,
    *,
    default: str | None = None,
    allow_empty: bool = True,
) -> str:
    if value is None:
        if default is None:
            _fail(f"{what}: Zeichenkette erwartet, gefunden None")
        return default
    if not isinstance(value, str):
        _fail(f"{what}: Zeichenkette erwartet, gefunden {_type_name(value)}")
    if not allow_empty and not value.strip():
        _fail(f"{what}: darf nicht leer sein")
    return value


def _path_text(value: Any, what: str) -> str:
    """Logischer Paketpfad: '/' als Trenner, keine Sonderformen (wie IR_SPEC)."""
    path = _text(value, what, allow_empty=False)
    if "\\" in path:
        _fail(f"{what}: Backslash in Pfad {path!r} -- Trenner ist '/'")
    if "::" in path:
        _fail(f"{what}: '::' ist als Trenner fuer Element-Referenzen reserviert ({path!r})")
    if path.startswith("/") or path.endswith("/") or "//" in path:
        _fail(f"{what}: ungueltiger Pfad {path!r} (kein fuehrender/abschliessender '/', kein '//')")
    for part in path.split("/"):
        if part in ("", ".", ".."):
            _fail(f"{what}: ungueltiges Pfadsegment {part!r} in {path!r}")
    return path


def _text_list(value: Any, what: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    items = _sequence(value, what)
    out: list[str] = []
    for index, item in enumerate(items):
        name = _text(item, f"{what}[{index}]", allow_empty=False).strip()
        if not name:
            _fail(f"{what}[{index}]: darf nicht leer sein")
        out.append(name)
    if not out and not allow_empty:
        _fail(f"{what}: darf nicht leer sein")
    if len(set(out)) != len(out):
        _fail(f"{what}: doppelte Eintraege")
    return tuple(sorted(out))


def _tag_pairs(value: Any, what: str) -> tuple[tuple[str, str], ...]:
    """Tagged Values kanonisch als (Name, Wert)-Tupel -- nur fuer die Sortierung."""
    if value is None:
        return ()
    obj = _mapping(value, what)
    rows: list[tuple[str, str]] = []
    for key, item in obj.items():
        name = _text(key, f"{what}.<Schluessel>", allow_empty=False)
        if isinstance(item, bool):
            text = "True" if item else "False"
        elif isinstance(item, (int, float)):
            text = str(item)
        elif item is None:
            _fail(f"{what}[{name!r}]: Wert ist null")
        else:
            text = _text(item, f"{what}[{name!r}]")
        rows.append((name, text))
    return tuple(sorted(rows))


def _local_name(name: str) -> str:
    """'Profil::Stereotyp' -> 'Stereotyp'; lokale Namen bleiben unveraendert."""
    return name.rsplit("::", 1)[-1].strip()


def _stereotype_tokens(raw: str) -> tuple[str, ...]:
    """EA kann mehrere Stereotype kommagetrennt in einer Spalte fuehren."""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _metaclass_key(value: str) -> str:
    key = value.strip().lower()
    return _METACLASS_ALIASES.get(key, key)


def _names(refs: Sequence[str]) -> str:
    return ", ".join(refs) if refs else "(kein Stereotyp)"


def _quoted_names(refs: Sequence[str]) -> str:
    return ", ".join(f"'{name}'" for name in refs) if refs else "'(kein Stereotyp)'"


# --------------------------------------------------------------------------
# Regelwerk (rules.json)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ElementRule:
    name: str
    abstract: bool
    metaclasses: tuple[str, ...]
    generalizes: tuple[str, ...]
    #: Zweite Elternquelle der MDG. Traegt Rollen wie ``CapableElement``, ueber
    #: die eine Kante zulaessig wird -- ohne sie meldet der Validator einen
    #: Verstoss, den es nicht gibt.
    base_stereotypes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConnectorRule:
    id: str
    stereotype: str
    source: tuple[str, ...]
    target: tuple[str, ...]
    metaclasses: tuple[str, ...]
    direction: str


@dataclass(frozen=True)
class Requirement:
    id: str
    stereotype: str
    connector: str
    role: str
    minimum: int
    message: str


@dataclass(frozen=True)
class RuleSet:
    name: str
    elements: Mapping[str, ElementRule]
    connectors: Mapping[str, ConnectorRule]
    requirements: tuple[Requirement, ...]
    closures: Mapping[str, frozenset[str]]


def _stereotype_closures(elements: Mapping[str, ElementRule]) -> dict[str, frozenset[str]]:
    """Transitive Elternhuelle je Element-Stereotyp (lokal, zyklensicher).

    Folgt ``generalizes`` **und** ``baseStereotypes``: die MDG verteilt
    Vererbung auf beide Felder, und eine Kante ueber eine Sammelrolle wie
    ``CapableElement`` ist nur mit beiden Elternquellen zulaessig.
    """
    closures: dict[str, frozenset[str]] = {}
    for name in elements:
        if name in closures:
            continue
        seen: set[str] = set()
        stack = [_local_name(name)]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            rule = elements.get(current)
            if rule is None:
                continue
            for parent in (*rule.generalizes, *rule.base_stereotypes):
                stack.append(_local_name(parent))
        closures[name] = frozenset(seen)
    return closures


def _check_wildcard(refs: Sequence[str], what: str) -> None:
    if ANY in refs and len(refs) != 1:
        _fail(f"{what}: '{ANY}' darf nur allein stehen (keine Mischung aus Platzhalter und Namen)")


def _read_requirements(
    items: Sequence[Any],
    *,
    elements: Mapping[str, ElementRule],
    connectors: Mapping[str, ConnectorRule],
) -> tuple[Requirement, ...]:
    allowed_keys = {"id", "stereotype", "connector", "role", "minimum", "message"}
    seen: set[str] = set()
    requirements: list[Requirement] = []
    for index, item in enumerate(items):
        what = f"requiredRelationships[{index}]"
        obj = _mapping(item, what)
        unknown = sorted(set(obj) - allowed_keys)
        if unknown:
            _fail(f"{what}: unbekannte Felder {unknown} (erlaubt: {sorted(allowed_keys)})")
        req_id = _text(obj.get("id"), f"{what}.id", allow_empty=False)
        if req_id in seen:
            _fail(f"{what}.id: '{req_id}' ist doppelt definiert")
        stereotype = _text(obj.get("stereotype"), f"{what}.stereotype", allow_empty=False)
        if stereotype not in elements:
            _fail(
                f"{what}.stereotype: '{stereotype}' ist kein Element-Stereotyp des Regelwerks"
            )
        connector = _text(obj.get("connector"), f"{what}.connector", default=ANY)
        if connector != ANY and connector not in connectors:
            _fail(
                f"{what}.connector: '{connector}' ist keine Konnektor-Regel des Regelwerks "
                f"(oder '{ANY}')"
            )
        role = _text(obj.get("role"), f"{what}.role", default="any")
        if role not in REQUIREMENT_ROLES:
            _fail(
                f"{what}.role: '{role}' ist unbekannt (erlaubt: "
                f"{', '.join(sorted(REQUIREMENT_ROLES))})"
            )
        minimum = obj.get("minimum", 1)
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            _fail(f"{what}.minimum: ganze Zahl >= 1 erwartet, gefunden {minimum!r}")
        message = _text(obj.get("message"), f"{what}.message", default="")
        requirements.append(
            Requirement(
                id=req_id,
                stereotype=stereotype,
                connector=connector,
                role=role,
                minimum=minimum,
                message=message,
            )
        )
        seen.add(req_id)
    requirements.sort(key=lambda item: item.id)
    return tuple(requirements)


def build_rules(
    document: Mapping[str, Any],
    required_relationships: Sequence[Any] | None = None,
) -> RuleSet:
    """Liest und prueft ein Regelwerk; wirft ValidatorError bei Verstoessen."""
    doc = _mapping(document, "Regelwerk")
    version = doc.get("schemaVersion")
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        _fail(f"Regelwerk.schemaVersion: {SCHEMA_VERSION} erwartet, gefunden {version!r}")

    name = ""
    source = doc.get("source")
    if isinstance(source, Mapping):
        raw = source.get("technologyName") or source.get("technologyId") or ""
        if isinstance(raw, str):
            name = raw.strip()

    elements: dict[str, ElementRule] = {}
    for index, item in enumerate(_sequence(doc.get("elementStereotypes"), "Regelwerk.elementStereotypes")):
        what = f"Regelwerk.elementStereotypes[{index}]"
        obj = _mapping(item, what)
        element_name = _text(obj.get("name"), f"{what}.name", allow_empty=False)
        if element_name in elements:
            _fail(f"{what}.name: Stereotyp '{element_name}' ist doppelt definiert")
        abstract = obj.get("abstract", False)
        if not isinstance(abstract, bool):
            _fail(f"{what}.abstract: Wahrheitswert erwartet, gefunden {_type_name(abstract)}")
        elements[element_name] = ElementRule(
            name=element_name,
            abstract=abstract,
            metaclasses=_text_list(obj.get("metaclasses", []), f"{what}.metaclasses", allow_empty=True),
            generalizes=_text_list(obj.get("generalizes", []), f"{what}.generalizes", allow_empty=True),
            base_stereotypes=_text_list(
                obj.get("baseStereotypes", []), f"{what}.baseStereotypes", allow_empty=True
            ),
        )

    connectors: dict[str, ConnectorRule] = {}
    for index, item in enumerate(_sequence(doc.get("connectorRules"), "Regelwerk.connectorRules")):
        what = f"Regelwerk.connectorRules[{index}]"
        obj = _mapping(item, what)
        stereotype = _text(obj.get("stereotype"), f"{what}.stereotype", allow_empty=False)
        if stereotype in connectors:
            _fail(f"{what}.stereotype: Konnektor-Regel '{stereotype}' ist doppelt definiert")
        rule_id = _text(obj.get("id"), f"{what}.id", allow_empty=False)
        expected = f"cr:{stereotype}"
        if rule_id != expected:
            _fail(f"{what}.id: '{expected}' erwartet, gefunden '{rule_id}'")
        source_refs = _text_list(obj.get("source"), f"{what}.source")
        target_refs = _text_list(obj.get("target"), f"{what}.target")
        _check_wildcard(source_refs, f"{what}.source")
        _check_wildcard(target_refs, f"{what}.target")
        connectors[stereotype] = ConnectorRule(
            id=rule_id,
            stereotype=stereotype,
            source=source_refs,
            target=target_refs,
            metaclasses=_text_list(obj.get("metaclasses", []), f"{what}.metaclasses", allow_empty=True),
            direction=_text(obj.get("direction"), f"{what}.direction", default="").strip(),
        )

    overlap = sorted(set(elements) & set(connectors))
    if overlap:
        _fail(
            "Regelwerk: Stereotyp(en) " + ", ".join(overlap) +
            " sind gleichzeitig Element- und Kanten-Stereotyp -- nicht eindeutig pruefbar"
        )
    if not elements and not connectors:
        _fail("Regelwerk enthaelt keine Pruefregeln (keine Element- und keine Kanten-Stereotype)")

    inline = _sequence(doc.get("requiredRelationships", []), "Regelwerk.requiredRelationships")
    combined: list[Any] = list(inline)
    if required_relationships:
        combined.extend(_sequence(required_relationships, "required_relationships"))
    requirements = _read_requirements(combined, elements=elements, connectors=connectors)

    return RuleSet(
        name=name or "unbenannt",
        elements=elements,
        connectors=connectors,
        requirements=requirements,
        closures=_stereotype_closures(elements),
    )


# --------------------------------------------------------------------------
# IR lesen (nur was fuer die Regelpruefung noetig ist)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelPackage:
    index: int
    path: str
    stereotype: str
    is_root: bool


@dataclass(frozen=True)
class ModelElement:
    index: int
    package: str
    name: str
    stereotype: str
    ea_type: str
    ea_type_declared: bool
    sort_key: tuple[Any, ...]


@dataclass(frozen=True)
class ModelConnector:
    index: int
    source: str
    target: str
    stereotype: str
    ea_type: str
    ea_type_declared: bool


@dataclass(frozen=True)
class Model:
    packages: tuple[ModelPackage, ...]
    elements: tuple[ModelElement, ...]
    connectors: tuple[ModelConnector, ...]
    package_map: Mapping[str, ModelPackage]
    element_groups: Mapping[tuple[str, str], tuple[int, ...]]


def _read_model(ir: Mapping[str, Any]) -> Model:
    doc = _mapping(ir, "IR")
    version = doc.get("ir_version")
    if isinstance(version, bool) or version != IR_VERSION:
        _fail(f"IR.ir_version: {IR_VERSION} erwartet, gefunden {version!r}")
    if doc.get("diagrams"):
        _fail(
            "IR.diagrams: Sichten und Layout sind bewusst nicht Teil des IR "
            "-- die Liste muss leer sein"
        )

    raw_packages = _sequence(doc.get("packages"), "IR.packages")
    if not raw_packages:
        _fail("IR.packages: das IR enthaelt kein Paket -- Abbruch statt leerem Erfolg")
    packages: list[ModelPackage] = []
    package_map: dict[str, ModelPackage] = {}
    for index, item in enumerate(raw_packages):
        what = f"IR.packages[{index}]"
        obj = _mapping(item, what)
        path = _path_text(obj.get("path"), f"{what}.path")
        if path in package_map:
            _fail(f"{what}.path: Paket '{path}' ist mehrfach deklariert")
        package = ModelPackage(
            index=index,
            path=path,
            stereotype=_text(obj.get("stereotype"), f"{what}.stereotype", default=""),
            is_root="/" not in path,
        )
        packages.append(package)
        package_map[path] = package

    raw_elements = _sequence(doc.get("elements"), "IR.elements")
    if not raw_elements:
        _fail("IR.elements: das IR enthaelt kein Element -- Abbruch statt leerem Erfolg")
    elements: list[ModelElement] = []
    for index, item in enumerate(raw_elements):
        what = f"IR.elements[{index}]"
        obj = _mapping(item, what)
        name = _text(obj.get("name"), f"{what}.name")
        if "::" in name:
            _fail(f"{what}.name: '::' ist im Elementnamen reserviert ({name!r})")
        declared = "ea_type" in obj and obj["ea_type"] is not None
        ea_type = _text(
            obj.get("ea_type"),
            f"{what}.ea_type",
            default=DEFAULT_OBJECT_TYPE,
            allow_empty=False,
        )
        tags = _tag_pairs(obj.get("tags"), f"{what}.tags")
        notes = _text(obj.get("notes"), f"{what}.notes", default="")
        alias = _text(obj.get("alias"), f"{what}.alias", default="")
        status = _text(obj.get("status"), f"{what}.status", default="")
        elements.append(
            ModelElement(
                index=index,
                package=_text(obj.get("package"), f"{what}.package", allow_empty=False),
                name=name,
                stereotype=_text(obj.get("stereotype"), f"{what}.stereotype", default=""),
                ea_type=ea_type,
                ea_type_declared=declared,
                sort_key=(ea_type, notes, alias, status, tags),
            )
        )

    element_groups: dict[tuple[str, str], list[int]] = {}
    for element in elements:
        element_groups.setdefault((element.package, element.name), []).append(element.index)
    # Kanonische Reihenfolge wie qea_writer._element_index: Inhalt, nicht IR-Position.
    # Damit adressiert '#N' in einer Meldung dasselbe Vorkommen wie im Export.
    for group in element_groups.values():
        group.sort(key=lambda position: elements[position].sort_key)
    frozen_groups = {key: tuple(value) for key, value in element_groups.items()}

    raw_connectors = _sequence(doc.get("connectors", []), "IR.connectors")
    connectors: list[ModelConnector] = []
    for index, item in enumerate(raw_connectors):
        what = f"IR.connectors[{index}]"
        obj = _mapping(item, what)
        declared = "ea_type" in obj and obj["ea_type"] is not None
        connectors.append(
            ModelConnector(
                index=index,
                source=_text(obj.get("source"), f"{what}.source", allow_empty=False),
                target=_text(obj.get("target"), f"{what}.target", allow_empty=False),
                stereotype=_text(obj.get("stereotype"), f"{what}.stereotype", default=""),
                ea_type=_text(
                    obj.get("ea_type"),
                    f"{what}.ea_type",
                    default=DEFAULT_CONNECTOR_TYPE,
                    allow_empty=False,
                ),
                ea_type_declared=declared,
            )
        )

    return Model(
        packages=tuple(packages),
        elements=tuple(elements),
        connectors=tuple(connectors),
        package_map=package_map,
        element_groups=frozen_groups,
    )


# --------------------------------------------------------------------------
# Endpunkte
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Endpoint:
    kind: str  # "element" | "package" | "unresolved" | "ambiguous"
    stereotypes: tuple[str, ...] = ()
    indices: tuple[int, ...] = ()
    detail: str = ""


def _resolve_endpoint(model: Model, ref: str) -> _Endpoint:
    """'<paket>::<name>[#N]' oder '<paketpfad>' aufloesen (wie qea_writer)."""
    if "::" in ref:
        package_path, rest = ref.rsplit("::", 1)
        if not rest:
            return _Endpoint(
                "unresolved",
                detail=(
                    f"'{ref}' nennt keinen Elementnamen "
                    "(unbenannte Elemente mit '<paket>::#1' adressieren)"
                ),
            )
        group = model.element_groups.get((package_path, rest))
        occurrence: int | None = None
        if group is None:
            name, sep, number = rest.rpartition("#")
            if sep and number.isdigit():
                group = model.element_groups.get((package_path, name))
                if group is not None:
                    occurrence = int(number)
                    rest = name
        if group is None:
            return _Endpoint(
                "unresolved",
                detail=f"'{ref}' verweist auf kein Element des IR",
            )
        if occurrence is not None:
            if not 1 <= occurrence <= len(group):
                return _Endpoint(
                    "unresolved",
                    detail=(
                        f"'{ref}' verlangt Vorkommen {occurrence}, "
                        f"vorhanden sind {len(group)}"
                    ),
                )
            chosen = (group[occurrence - 1],)
            return _Endpoint(
                "element",
                stereotypes=(model.elements[chosen[0]].stereotype,),
                indices=chosen,
            )
        if len(group) > 1:
            forms = ", ".join(f"{package_path}::{rest}#{position}" for position in range(1, len(group) + 1))
            return _Endpoint(
                "ambiguous",
                indices=tuple(group),
                detail=(
                    f"'{ref}' ist mehrdeutig ({len(group)} gleichnamige Elemente) "
                    f"-- eindeutig mit: {forms}"
                ),
            )
        return _Endpoint(
            "element",
            stereotypes=(model.elements[group[0]].stereotype,),
            indices=(group[0],),
        )

    package = model.package_map.get(ref)
    if package is None:
        return _Endpoint(
            "unresolved",
            detail=f"'{ref}' verweist auf kein Paket des IR",
        )
    if package.is_root:
        return _Endpoint(
            "unresolved",
            detail=(
                f"'{ref}' ist ein Wurzelpaket; Wurzelpakete haben keinen "
                "t_object-Spiegel und koennen kein Kantenendpunkt sein"
            ),
        )
    return _Endpoint("package", stereotypes=(package.stereotype,))


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    severity: str
    object: str
    rule: str
    check: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "object": self.object,
            "rule": self.rule,
            "check": self.check,
            "message": self.message,
        }


def _finding_key(finding: Finding) -> tuple[Any, ...]:
    return (
        0 if finding.severity == ERROR else 1,
        finding.object,
        finding.rule,
        finding.check,
        finding.message,
    )


def _add(
    findings: list[Finding],
    severity: str,
    *,
    object_label: str,
    rule: str,
    check: str,
    message: str,
) -> None:
    findings.append(
        Finding(
            severity=severity,
            object=object_label,
            rule=rule,
            check=check,
            message=message,
        )
    )


def _element_label(model: Model, index: int) -> str:
    element = model.elements[index]
    group = model.element_groups[(element.package, element.name)]
    if len(group) == 1:
        return f"{element.package}::{element.name}"
    position = group.index(index) + 1
    return f"{element.package}::{element.name}#{position}"


def _connector_label(connector: ModelConnector) -> str:
    base = f"{connector.source} -> {connector.target}"
    stereotype = connector.stereotype.strip()
    return f"{base} [{stereotype}]" if stereotype else base


# --------------------------------------------------------------------------
# Regelanwendung
# --------------------------------------------------------------------------


def _stereotypes_match(
    actual: Sequence[str],
    allowed: Sequence[str],
    closures: Mapping[str, frozenset[str]],
) -> bool:
    if ANY in allowed:
        return True
    allowed_locals = {_local_name(ref) for ref in allowed}
    for raw in actual:
        for token in _stereotype_tokens(raw):
            local = _local_name(token)
            names = closures.get(local, frozenset({local}))
            if names & allowed_locals:
                return True
    return False


def _lookup_element_rule(rules: RuleSet, token: str) -> ElementRule | None:
    return rules.elements.get(token) or rules.elements.get(_local_name(token))


def _lookup_connector_rule(rules: RuleSet, token: str) -> ConnectorRule | None:
    return rules.connectors.get(token) or rules.connectors.get(_local_name(token))


def _metaclass_message(
    subject: str,
    metaclasses: Sequence[str],
    ea_type: str,
    declared: bool,
    default: str,
) -> str | None:
    """Warnung, wenn die effektive Metaklasse nicht zur Regel passt."""
    if not metaclasses:
        return None
    allowed = {_metaclass_key(name) for name in metaclasses}
    effective = ea_type if declared else default
    if _metaclass_key(effective) in allowed:
        return None
    allowed_text = ", ".join(metaclasses)
    if declared:
        return (
            f"Metaklasse '{ea_type}' passt nicht zu {subject} "
            f"(erlaubt: {allowed_text})"
        )
    return (
        f"ea_type fehlt im IR - der Writer schreibt '{default}'; "
        f"{subject} erlaubt nur: {allowed_text}"
    )


def _check_packages(findings: list[Finding], model: Model, rules: RuleSet) -> None:
    for package in model.packages:
        if not package.stereotype.strip():
            continue
        label = package.path
        for token in _stereotype_tokens(package.stereotype):
            rule = _lookup_element_rule(rules, token)
            if rule is None:
                hint = ""
                if _lookup_connector_rule(rules, token) is not None:
                    hint = f" '{token}' ist dort eine Konnektor-Regel, kein Element-Stereotyp."
                _add(
                    findings,
                    ERROR,
                    object_label=label,
                    rule="",
                    check="unknownPackageStereotype",
                    message=(
                        f"Paket '{label}': Stereotyp '{token}' ist im Regelwerk "
                        f"'{rules.name}' nicht definiert.{hint}"
                    ),
                )
                continue
            if rule.abstract:
                _add(
                    findings,
                    WARNING,
                    object_label=label,
                    rule="",
                    check="abstractElementStereotype",
                    message=(
                        f"Paket '{label}': Stereotyp '{rule.name}' ist abstrakt und "
                        "im Regelwerk nicht zur direkten Verwendung vorgesehen."
                    ),
                )
            problem = _metaclass_message(
                f"Stereotyp '{rule.name}'",
                rule.metaclasses,
                ea_type="Package",
                declared=True,
                default="Package",
            )
            if problem:
                _add(
                    findings,
                    WARNING,
                    object_label=label,
                    rule="",
                    check="elementMetaclassMismatch",
                    message=f"Paket '{label}': {problem}.",
                )


def _check_elements(findings: list[Finding], model: Model, rules: RuleSet) -> None:
    for element in model.elements:
        if not element.stereotype.strip():
            continue
        label = _element_label(model, element.index)
        for token in _stereotype_tokens(element.stereotype):
            rule = _lookup_element_rule(rules, token)
            if rule is None:
                hint = ""
                if _lookup_connector_rule(rules, token) is not None:
                    hint = f" '{token}' ist dort eine Konnektor-Regel, kein Element-Stereotyp."
                _add(
                    findings,
                    ERROR,
                    object_label=label,
                    rule="",
                    check="unknownElementStereotype",
                    message=(
                        f"Element '{label}': Stereotyp '{token}' ist im Regelwerk "
                        f"'{rules.name}' nicht definiert.{hint}"
                    ),
                )
                continue
            if rule.abstract:
                _add(
                    findings,
                    WARNING,
                    object_label=label,
                    rule="",
                    check="abstractElementStereotype",
                    message=(
                        f"Element '{label}': Stereotyp '{rule.name}' ist abstrakt und "
                        "im Regelwerk nicht zur direkten Verwendung vorgesehen."
                    ),
                )
            problem = _metaclass_message(
                f"Stereotyp '{rule.name}'",
                rule.metaclasses,
                ea_type=element.ea_type,
                declared=element.ea_type_declared,
                default=DEFAULT_OBJECT_TYPE,
            )
            if problem:
                _add(
                    findings,
                    WARNING,
                    object_label=label,
                    rule="",
                    check="elementMetaclassMismatch",
                    message=f"Element '{label}': {problem}.",
                )


def _check_connectors(
    findings: list[Finding],
    model: Model,
    rules: RuleSet,
) -> tuple[dict[int, tuple[_Endpoint, _Endpoint]], set[int]]:
    resolved: dict[int, tuple[_Endpoint, _Endpoint]] = {}
    invalid: set[int] = set()
    for connector in model.connectors:
        label = _connector_label(connector)
        source = _resolve_endpoint(model, connector.source)
        target = _resolve_endpoint(model, connector.target)
        resolved[connector.index] = (source, target)

        for role, endpoint in (("Quelle", source), ("Ziel", target)):
            if endpoint.kind == "unresolved":
                invalid.add(connector.index)
                _add(
                    findings,
                    ERROR,
                    object_label=label,
                    rule="",
                    check="unresolvedConnectorEndpoint",
                    message=f"Kante '{label}': {role} {endpoint.detail}.",
                )
            elif endpoint.kind == "ambiguous":
                invalid.add(connector.index)
                _add(
                    findings,
                    ERROR,
                    object_label=label,
                    rule="",
                    check="ambiguousConnectorEndpoint",
                    message=f"Kante '{label}': {role} {endpoint.detail}.",
                )

        for token in _stereotype_tokens(connector.stereotype):
            rule = _lookup_connector_rule(rules, token)
            if rule is None:
                invalid.add(connector.index)
                hint = ""
                if _lookup_element_rule(rules, token) is not None:
                    hint = f" '{token}' ist dort ein Element-Stereotyp, kein Kanten-Stereotyp."
                _add(
                    findings,
                    ERROR,
                    object_label=label,
                    rule="",
                    check="unknownConnectorStereotype",
                    message=(
                        f"Kante '{label}': Stereotyp '{token}' ist im Regelwerk "
                        f"'{rules.name}' nicht definiert.{hint}"
                    ),
                )
                continue

            if source.kind in ("element", "package") and target.kind in ("element", "package"):
                source_problem = _endpoint_problem(source, rule, rule.source, rules, "Quelle")
                target_problem = _endpoint_problem(target, rule, rule.target, rules, "Ziel")
                if source_problem or target_problem:
                    invalid.add(connector.index)
                    parts = [part for part in (source_problem, target_problem) if part]
                    _add(
                        findings,
                        ERROR,
                        object_label=label,
                        rule=rule.id,
                        check="forbiddenConnectorEndpoints",
                        message=f"Kante '{label}': " + "; ".join(parts) + ".",
                    )

            problem = _metaclass_message(
                f"Regel '{rule.id}'",
                rule.metaclasses,
                ea_type=connector.ea_type,
                declared=connector.ea_type_declared,
                default=DEFAULT_CONNECTOR_TYPE,
            )
            if problem:
                _add(
                    findings,
                    WARNING,
                    object_label=label,
                    rule=rule.id,
                    check="connectorMetaclassMismatch",
                    message=f"Kante '{label}': {problem}.",
                )
    return resolved, invalid


def _endpoint_problem(
    endpoint: _Endpoint,
    rule: ConnectorRule,
    allowed: Sequence[str],
    rules: RuleSet,
    role: str,
) -> str:
    if _stereotypes_match(endpoint.stereotypes, allowed, rules.closures):
        return ""
    actual: list[str] = []
    for raw in endpoint.stereotypes:
        actual.extend(_local_name(token) for token in _stereotype_tokens(raw))
    return (
        f"{role} {_quoted_names(actual)} ist nach Regel '{rule.id}' nicht erlaubt "
        f"(erlaubt: {_names(allowed)})"
    )


def _check_requirements(
    findings: list[Finding],
    model: Model,
    rules: RuleSet,
    resolved: Mapping[int, tuple[_Endpoint, _Endpoint]],
    invalid: set[int],
) -> None:
    if not rules.requirements:
        return
    by_source: dict[int, set[int]] = {}
    by_target: dict[int, set[int]] = {}
    for connector in model.connectors:
        if connector.index in invalid:
            # Eine regelwidrige Kante erfuellt keine Pflicht.
            continue
        source, target = resolved[connector.index]
        for index in source.indices:
            by_source.setdefault(index, set()).add(connector.index)
        for index in target.indices:
            by_target.setdefault(index, set()).add(connector.index)

    role_text = {"source": "als Quelle", "target": "als Ziel", "any": "als Quelle oder Ziel"}
    for requirement in rules.requirements:
        for element in model.elements:
            if not _stereotypes_match(
                (element.stereotype,), (requirement.stereotype,), rules.closures
            ):
                continue
            candidates: set[int] = set()
            if requirement.role in ("source", "any"):
                candidates |= by_source.get(element.index, set())
            if requirement.role in ("target", "any"):
                candidates |= by_target.get(element.index, set())
            if requirement.connector != ANY:
                candidates = {
                    position
                    for position in candidates
                    if any(
                        _local_name(token) == requirement.connector
                        for token in _stereotype_tokens(model.connectors[position].stereotype)
                    )
                }
            found = len(candidates)
            if found >= requirement.minimum:
                continue
            keyword = (
                f"'{requirement.connector}'"
                if requirement.connector != ANY
                else "(beliebiger Stereotyp)"
            )
            label = _element_label(model, element.index)
            hint = f" Hinweis: {requirement.message}" if requirement.message else ""
            _add(
                findings,
                WARNING,
                object_label=label,
                rule=requirement.id,
                check="missingRequiredRelationship",
                message=(
                    f"Element '{label}': Pflichtbeziehung fehlt - Regel '{requirement.id}' "
                    f"verlangt mindestens {requirement.minimum} Kante(n) {keyword} "
                    f"{role_text[requirement.role]}; gefunden: {found}.{hint}"
                ),
            )


def validate_model(
    ir: Mapping[str, Any],
    rules: Mapping[str, Any] | RuleSet,
    required_relationships: Sequence[Any] | None = None,
) -> list[dict[str, str]]:
    """Prueft ein IR gegen ein Regelwerk und liefert kanonisch sortierte Findings."""
    model = _read_model(ir)
    if isinstance(rules, RuleSet):
        if required_relationships:
            _fail(
                "required_relationships: das uebergebene RuleSet enthaelt die "
                "Pflichtbeziehungen bereits -- nicht zusaetzlich uebergeben"
            )
        ruleset = rules
    else:
        ruleset = build_rules(rules, required_relationships)

    findings: list[Finding] = []
    _check_packages(findings, model, ruleset)
    _check_elements(findings, model, ruleset)
    resolved, invalid = _check_connectors(findings, model, ruleset)
    _check_requirements(findings, model, ruleset, resolved, invalid)

    unique = sorted(set(findings), key=_finding_key)
    return [finding.as_dict() for finding in unique]


# --------------------------------------------------------------------------
# Laden, Serialisieren, CLI
# --------------------------------------------------------------------------


def _read_json(path: str | Path, what: str) -> Any:
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"{what}: {target} ist nicht lesbar: {exc}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(f"{what}: {target} ist kein gueltiges JSON ({exc})")


def load_ir(path: str | Path) -> dict[str, Any]:
    doc = _read_json(path, "IR")
    if not isinstance(doc, Mapping):
        _fail(f"IR: {path}: die Wurzel muss ein JSON-Objekt sein")
    return dict(doc)


def load_rules(path: str | Path) -> RuleSet:
    doc = _read_json(path, "Regelwerk")
    return build_rules(_mapping(doc, str(path)))


def load_requirements(path: str | Path) -> list[dict[str, Any]]:
    doc = _read_json(path, "Pflichtbeziehungen")
    items = _sequence(doc, "Pflichtbeziehungen")
    return [dict(_mapping(item, f"Pflichtbeziehungen[{index}]")) for index, item in enumerate(items)]


def dumps_findings(findings: Sequence[Mapping[str, Any]]) -> str:
    """Kanonischer Text: sortierte Schluessel, 2 Leerzeichen, UTF-8, LF."""
    return json.dumps(list(findings), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_findings(findings: Sequence[Mapping[str, Any]], path: str | Path) -> Path:
    target = Path(path)
    target.write_text(dumps_findings(findings), encoding="utf-8", newline="\n")
    return target


def summarize(findings: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    errors = sum(1 for finding in findings if finding.get("severity") == ERROR)
    warnings = sum(1 for finding in findings if finding.get("severity") == WARNING)
    return {"total": len(findings), "error": errors, "warning": warnings}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validator.py",
        description="IR gegen ein Technologie-Regelwerk (rules.json) pruefen.",
    )
    parser.add_argument("ir", type=Path, help="IR-JSON des Modells")
    parser.add_argument("rules", type=Path, help="Regelwerk-JSON (aus mdg_parser.py)")
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        help="findings.json schreiben (ohne Angabe: JSON nach stdout)",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        help="Pflichtbeziehungen als JSON-Liste (Projektkonvention)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Warnungen zaehlen wie Fehler (Exit 1)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="keine Zusammenfassung auf stderr")
    args = parser.parse_args(argv)

    try:
        ir = load_ir(args.ir)
        rules_document = _read_json(args.rules, "Regelwerk")
        requirements = load_requirements(args.requirements) if args.requirements else None
        ruleset = build_rules(_mapping(rules_document, str(args.rules)), requirements)
        findings = validate_model(ir, ruleset)
        model = _read_model(ir)
    except ValidatorError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 3

    if args.out:
        try:
            write_findings(findings, args.out)
        except OSError as exc:
            print(f"FEHLER: findings.json nicht schreibbar: {exc}", file=sys.stderr)
            return 3
    else:
        sys.stdout.write(dumps_findings(findings))

    summary = summarize(findings)
    if not args.quiet:
        print(
            f"Geprueft: {len(model.elements)} Elemente, {len(model.connectors)} Kanten, "
            f"{len(model.packages)} Pakete gegen {len(ruleset.elements)} Element-Stereotype "
            f"und {len(ruleset.connectors)} Kanten-Regeln.",
            file=sys.stderr,
        )
        print(
            f"{summary['total']} Findings: {summary['error']} Fehler, "
            f"{summary['warning']} Warnungen.",
            file=sys.stderr,
        )

    if summary["error"]:
        return 1
    if args.strict and summary["warning"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
