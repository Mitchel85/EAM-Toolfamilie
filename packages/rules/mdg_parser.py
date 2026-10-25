#!/usr/bin/env python3
"""Generischer Parser fuer MDG-Technologie-XML -> kanonisches Regelwerk.

DIESER LESER IST DER EINZIGE MDG-LESER DER WERKZEUGFAMILIE.

Er ersetzt den frueheren Dokumenten-Parser (796 Zeilen), nachdem beide an
denselben Eingaben verglichen wurden
(scripts/compare_parsers.py). Gruende fuer diesen:
  * besitzt ein geprueftes Schema und lief gegen eine echte MDG,
  * verarbeitet auch fremde Technologien, ohne eine bestimmte anzunehmen,
  * meldet Fehler als benannte Ausnahme mit Datei und Stelle,
  * erzeugt reproduzierbare Bytes (gleicher Input -> gleiche Ausgabe).

Die frueheren Dokumente (Wissensbasis als Markdown) werden jetzt hieraus
abgeleitet (packages/rules/documents.py), nicht mehr aus einer zweiten
XML-Leseschicht.

Technologie ist Daten, kein Code: Der Parser kennt keine Fachkonzepte und keine
Technologie-Namen. Er liest aus der MDG-Datei

  * Element-Stereotypen (Name, Metaklassen, Tagged Values, Vererbung),
  * Konnektor-Regeln (Stereotyp + erlaubte Quelle/Ziele),
  * Viewpoints (Diagramm-Stereotypen und ViewDefinition-Eintraege),
  * die verwendeten UML-Metaklassen

und schreibt daraus ein kanonisches Regelwerk. Kanonisch heisst: gleicher
Input -> gleiche Bytes (sortierte Schluessel und Listen, keine Zeitstempel,
keine Zufalls-IDs).

Nur Standardbibliothek, kein Netzwerk, keine Schreibzugriffe ausser der
optionalen Ausgabedatei.

Aufruf:
    python3 mdg_parser.py technologie.xml -o rules.json [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

# Wurzelnamen, die in freier Wildbahn vorkommen (EA 15/16).
ROOT_TAGS = frozenset({"MDG.Technology", "MDGTechnology"})

# UML-Metamodell-Wissen (gilt fuer jede Technologie, daher kein Hardcoding
# einer bestimmten Technologie):
#   client/supplier              -> Dependency, Abstraction, Realisation
#   source/target                -> Association, Aggregation, Connector, ...
#   informationSource/Target     -> InformationFlow
#   end[0]/end[1]                -> Assoziationsenden
# Rollen werden ohne Ruecksicht auf Gross-/Kleinschreibung verglichen.
SOURCE_ROLES = frozenset(
    {"client", "source", "informationsource", "end[0]", "end[0].role"}
)
TARGET_ROLES = frozenset(
    {"supplier", "target", "informationtarget", "end[1]", "end[1].role"}
)

# Platzhalter fuer "keine Endpunkt-Einschraenkung": ein Konnektor-Stereotyp,
# das eine Konnektor-Metaklasse nennt, aber keine Endpunkt-Rollen deklariert
# (z. B. Message-Stereotypen in Sequenzdiagrammen), erlaubt jeden Endpunkt.
ANY_ENDPOINT = "*"

# Metaklassen, die Kanten repraesentieren. Alles andere gilt als Knoten.
CONNECTOR_METACLASSES = frozenset(
    {
        "Abstraction",
        "Aggregation",
        "Association",
        "Composition",
        "Connector",
        "ControlFlow",
        "Dependency",
        "Deployment",
        "Extend",
        "Generalization",
        "Include",
        "InformationFlow",
        "Manifestation",
        "Message",
        "ObjectFlow",
        "Realisation",
        "Realization",
        "Substitution",
        "Usage",
    }
)

# Apply-Typen, die Diagramme (Viewpoints) beschreiben, beginnen damit
# (z. B. "Diagram_Custom", "Diagram_Analysis").
DIAGRAM_APPLY_PREFIX = "Diagram"

# Container, die nur Werkzeugkasten-/Vorlagen-Definitionen enthalten und
# deshalb keine Modellregeln liefern.
IGNORED_PROFILE_CONTAINERS = frozenset({"UIToolboxes", "ModelTemplates", "Scripts"})

VIEWPOINT_TAGS = frozenset({"ViewDefinition", "Viewpoint", "View"})

_TRUE = frozenset({"1", "true", "yes", "ja"})


class MdgParseError(Exception):
    """Die MDG-Datei ist strukturell nicht verwertbar."""


# --------------------------------------------------------------------------
# XML-Helfer (namensraum-tolerant, dokumentreihenfolge-erhaltend)
# --------------------------------------------------------------------------


def _local(tag: str) -> str:
    """Tag-Name ohne {namespace}."""
    return tag.rsplit("}", 1)[-1]


def _kids(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in elem if _local(child.tag) == name]


def _kid(elem: ET.Element | None, name: str) -> ET.Element | None:
    if elem is None:
        return None
    for child in elem:
        if _local(child.tag) == name:
            return child
    return None


def _attr(elem: ET.Element, name: str) -> str | None:
    value = elem.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split(value: str | None) -> list[str]:
    """Leerraum-getrennte Referenzliste, sortiert und dedupliziert."""
    if not value:
        return []
    return sorted({part for part in value.split() if part})


def _flag(elem: ET.Element, name: str) -> bool:
    value = _attr(elem, name)
    return bool(value) and value.lower() in _TRUE


class _Names:
    """Normalisiert Stereotyp-Referenzen der Form 'Profil::Stereotyp'.

    Referenzen auf das eigene Technologieprofil werden auf den blossen
    Stereotyp-Namen gekuerzt, Referenzen auf Fremdprofile bleiben voll
    qualifiziert ('Profil::Stereotyp') - so ist im Regelwerk sofort
    erkennbar, ob eine Referenz lokal aufloesbar ist.
    """

    def __init__(self, prefixes: list[str]) -> None:
        self._prefixes = {prefix.strip() for prefix in prefixes if prefix and prefix.strip()}

    def __call__(self, raw: str | None) -> str:
        name = (raw or "").strip()
        if not name:
            return ""
        if "::" in name:
            prefix, _, rest = name.partition("::")
            if prefix.strip() in self._prefixes:
                return rest.strip()
        return name

    def constraint_set(self, raw: str | None) -> list[str]:
        """'A::X;B::Y' -> ['X', 'B::Y'] (sortiert, ohne Leerstring)."""
        if not raw:
            return []
        return sorted({ref for ref in (self(part) for part in raw.split(";")) if ref})


# --------------------------------------------------------------------------
# Bestandteile eines Stereotyps
# --------------------------------------------------------------------------


def _applies(elem: ET.Element, stereotype: str) -> list[dict[str, Any]]:
    box = _kid(elem, "AppliesTo")
    if box is None:
        return []
    applies: list[dict[str, Any]] = []
    for apply_el in _kids(box, "Apply"):
        metaclass = _attr(apply_el, "type")
        if not metaclass:
            raise MdgParseError(
                f"Stereotyp '{stereotype}': Apply ohne Metaklasse (Attribut 'type' fehlt)"
            )
        properties: dict[str, str] = {}
        for prop in _kids(apply_el, "Property"):
            key = _attr(prop, "name")
            if not key:
                raise MdgParseError(
                    f"Stereotyp '{stereotype}': Property in Apply '{metaclass}' ohne Namen"
                )
            properties[key] = _attr(prop, "value") or ""
        applies.append({"metaclass": metaclass, "properties": properties})
    applies.sort(
        key=lambda entry: (
            entry["metaclass"],
            json.dumps(entry["properties"], sort_keys=True, ensure_ascii=False),
        )
    )
    return applies


def _tagged_values(elem: ET.Element) -> list[dict[str, str]]:
    box = _kid(elem, "TaggedValues")
    if box is None:
        return []
    tags: list[dict[str, str]] = []
    for tag in _kids(box, "Tag"):
        name = _attr(tag, "name")
        if not name:
            raise MdgParseError("Tagged Value ohne Namen")
        tags.append(
            {
                "name": name,
                "type": _attr(tag, "type") or "",
                "description": _attr(tag, "description") or "",
                "unit": _attr(tag, "unit") or "",
                "values": _attr(tag, "values") or "",
                "default": _attr(tag, "default") or "",
            }
        )
    tags.sort(key=lambda entry: entry["name"])
    return tags


def _property_types(root: ET.Element) -> list[dict[str, str]]:
    """Definitionen der Technologie-Eigenschaften aus <TaggedValueTypes>.

    Die MDG fuehrt dort Datensaetze (u. a. "Property Types") als DataRows mit
    Spalten Property / Description / Notes. Diese Tabelle ist die einzige
    Quelle fuer "welche Eigenschaft gibt es ueberhaupt"; die Tags an den
    Stereotypen sind dagegen Verwendungen. Ohne diese Trennung zaehlt man 167
    statt 27 Typen.
    """
    box = _kid(root, "TaggedValueTypes")
    if box is None:
        return []
    out: list[dict[str, str]] = []
    for dataset in root.iter():
        if _local(dataset.tag) != "DataSet":
            continue
        if (_attr(dataset, "name") or "").strip() != "Property Types":
            continue
        for row in dataset:
            if _local(row.tag) != "DataRow":
                continue
            werte: dict[str, str] = {}
            for column in row:
                name = _attr(column, "name")
                if name:
                    werte[name] = _attr(column, "value") or ""
            eigenschaft = werte.get("Property", "").strip()
            if not eigenschaft:
                continue
            out.append(
                {
                    "name": eigenschaft,
                    "description": werte.get("Description", "").strip(),
                    "notes": werte.get("Notes", "").strip(),
                }
            )
    out.sort(key=lambda entry: entry["name"].lower())
    return out


def _metaconstraints(elem: ET.Element, names: _Names) -> list[dict[str, Any]]:
    box = _kid(elem, "metaconstraints")
    if box is None:
        return []
    merged: dict[str, set[str]] = {}
    for constraint in _kids(box, "metaconstraint"):
        role = _attr(constraint, "umlRole")
        if not role:
            raise MdgParseError("metaconstraint ohne 'umlRole'")
        refs = names.constraint_set(_attr(constraint, "constraint"))
        if not refs:
            raise MdgParseError(f"metaconstraint '{role}' ohne 'constraint'")
        merged.setdefault(role, set()).update(refs)
    return [
        {"role": role, "constraints": sorted(merged[role])}
        for role in sorted(merged)
    ]


def _metarelationships(elem: ET.Element, names: _Names) -> list[dict[str, Any]]:
    box = _kid(elem, "metarelationships")
    if box is None:
        return []
    out: list[dict[str, Any]] = []
    for relation in _kids(box, "metarelationship"):
        metaclass = _attr(relation, "metaclass")
        if not metaclass:
            raise MdgParseError("metarelationship ohne 'metaclass'")
        targets = names.constraint_set(_attr(relation, "constraint"))
        if not targets:
            raise MdgParseError(f"metarelationship '{metaclass}' ohne 'constraint'")
        out.append({"metaclass": metaclass, "targets": targets})
    out.sort(key=lambda entry: (entry["metaclass"], entry["targets"]))
    return out


def _in(role: str, wanted: frozenset[str]) -> bool:
    return role.strip().lower() in wanted


def _roles(constraints: list[dict[str, Any]], wanted: frozenset[str]) -> list[str]:
    """Rollen, die in 'wanted' liegen (fuer die Herkunftsangabe der Regel)."""
    return sorted({entry["role"] for entry in constraints if _in(entry["role"], wanted)})


def _endpoints(
    constraints: list[dict[str, Any]], wanted: frozenset[str]
) -> list[str]:
    refs: set[str] = set()
    for entry in constraints:
        if _in(entry["role"], wanted):
            refs.update(entry["constraints"])
    return sorted(refs)


def _direction(applies: list[dict[str, Any]], metaclasses: list[str]) -> str | None:
    values = {
        entry["properties"]["direction"]
        for entry in applies
        if entry["metaclass"] in metaclasses and entry["properties"].get("direction")
    }
    return values.pop() if len(values) == 1 else None


# --------------------------------------------------------------------------
# Profile / Stereotypen einsammeln
# --------------------------------------------------------------------------


def _profiles(root: ET.Element) -> Iterator[tuple[str | None, ET.Element]]:
    """Liefert (Container-Name, UMLProfile) fuer alle Profile der Technologie."""
    for container in root:
        tag = _local(container.tag)
        if tag == "UMLProfile":
            yield None, container
        elif tag in {"UMLProfiles", "DiagramProfile", "UIToolboxes", "ModelTemplates", "Scripts"}:
            for profile in _kids(container, "UMLProfile"):
                yield tag, profile


def _profile_name(profile: ET.Element) -> str | None:
    documentation = _kid(profile, "Documentation")
    if documentation is None:
        return None
    return _attr(documentation, "name") or _attr(documentation, "id")


def _profile_stereotypes(profile: ET.Element) -> list[ET.Element]:
    content = _kid(profile, "Content")
    box = _kid(content, "Stereotypes") if content is not None else _kid(profile, "Stereotypes")
    if box is None:
        return []
    return _kids(box, "Stereotype")


def _view_definitions(profile: ET.Element) -> list[ET.Element]:
    content = _kid(profile, "Content")
    box = _kid(content, "ViewDefinitions") if content is not None else _kid(profile, "ViewDefinitions")
    if box is None:
        return []
    return [child for child in box if _local(child.tag) in VIEWPOINT_TAGS]


def _is_diagram_stereotype(applies: list[dict[str, Any]]) -> bool:
    return any(entry["metaclass"].startswith(DIAGRAM_APPLY_PREFIX) for entry in applies)


def _viewpoint(
    *,
    group: str | None,
    name: str,
    alias: str | None,
    notes: str,
    kind: str,
    properties: dict[str, str],
) -> dict[str, Any]:
    return {
        "group": group,
        "name": name,
        "alias": alias,
        "notes": notes,
        "kind": kind,
        "properties": properties,
    }


def _viewpoints(root: ET.Element, technology_name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for container, profile in _profiles(root):
        if container in IGNORED_PROFILE_CONTAINERS:
            continue
        group = _profile_name(profile) or technology_name
        for stereotype in _profile_stereotypes(profile):
            name = _attr(stereotype, "name")
            if not name:
                raise MdgParseError("Stereotyp ohne Namen")
            applies = _applies(stereotype, name)
            if not _is_diagram_stereotype(applies):
                continue
            properties: dict[str, str] = {}
            for entry in applies:
                properties.update(entry["properties"])
            out.append(
                _viewpoint(
                    group=group,
                    name=name,
                    alias=_attr(stereotype, "alias"),
                    notes=_attr(stereotype, "notes") or "",
                    kind="diagramProfile",
                    properties=properties,
                )
            )
        for definition in _view_definitions(profile):
            name = _attr(definition, "name")
            if not name:
                raise MdgParseError("ViewDefinition ohne Namen")
            properties = {
                key: value
                for key, value in definition.attrib.items()
                if key not in {"name", "alias", "notes"} and not key.startswith("{")
            }
            out.append(
                _viewpoint(
                    group=group,
                    name=name,
                    alias=_attr(definition, "alias"),
                    notes=_attr(definition, "notes") or "",
                    kind="viewDefinition",
                    properties=properties,
                )
            )
    out.sort(key=lambda entry: (entry["group"] or "", entry["name"], entry["kind"]))
    return out


# --------------------------------------------------------------------------
# Regelwerk bauen
# --------------------------------------------------------------------------


def _definition(
    stereotype: ET.Element,
    *,
    applies: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Gemeinsamer Stereotyp-Kern fuer Elemente und Konnektoren.

    Enthaelt alles, was in der MDG steht: Metaklassen, Apply-Properties,
    Vererbung, Tagged Values und Metaconstraints. Nichts davon darf auf dem
    Weg ins Regelwerk verloren gehen. Metarelationships gibt es nur bei
    Knoten-Stereotypen und werden daher am Element ergaenzt.
    """
    return {
        # isAbstract gilt fuer Element- und Konnektor-Stereotype; vorher ging
        # es bei Konnektoren verloren (z. B. InteractionMessage).
        "abstract": _flag(stereotype, "isAbstract"),
        "alias": _attr(stereotype, "alias"),
        "notes": _attr(stereotype, "notes") or "",
        "metatype": _attr(stereotype, "metatype"),
        "metaclasses": sorted({entry["metaclass"] for entry in applies}),
        "appliesTo": applies,
        "generalizes": _split(_attr(stereotype, "generalizes")),
        "baseStereotypes": _split(_attr(stereotype, "baseStereotypes")),
        "taggedValues": _tagged_values(stereotype),
        "metaconstraints": constraints,
    }


def _add_unique(
    registry: dict[str, dict[str, Any]], key: str, entry: dict[str, Any], kind: str
) -> None:
    existing = registry.get(key)
    if existing is None:
        registry[key] = entry
        return
    if existing == entry:
        return
    raise MdgParseError(
        f"{kind} '{key}' ist mehrfach mit unterschiedlicher Definition definiert"
    )


def _technology_header(root: ET.Element, filename: str, digest: str) -> dict[str, Any]:
    documentation = _kid(root, "Documentation")
    if documentation is None:
        raise MdgParseError("Wurzelelement ohne <Documentation> (Technologie-Kopf fehlt)")
    technology_id = _attr(documentation, "id") or _attr(documentation, "name")
    technology_name = _attr(documentation, "name") or technology_id
    if not technology_id or not technology_name:
        raise MdgParseError("<Documentation> ohne 'id'/'name'")
    return {
        "technologyId": technology_id,
        "technologyName": technology_name,
        "technologyVersion": _attr(documentation, "version") or "",
        "technologyNotes": _attr(documentation, "notes") or "",
        "file": filename,
        "sha256": digest,
    }


def _collect_warnings(
    elements: dict[str, dict[str, Any]], rules: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    """Sammelt Auffaelligkeiten, statt sie still zu schlucken.

    * unresolvedReference: lokale Referenz auf einen Stereotyp, den die
      Technologie nicht definiert (z. B. Metaklasse aus einem Fremdprofil,
      ohne '::' geschrieben).
    * stereotypeWithoutMetaclass: Element-Stereotyp ohne <Apply>, also auf
      kein UML-Element anwendbar (typisch fuer abstrakte Eltern).
    """
    known = {entry["name"] for entry in elements.values()}
    known.update(rule["stereotype"] for rule in rules.values())
    users: dict[str, set[str]] = {}

    def _reference(ref: str, user: str) -> None:
        if not ref or ref == ANY_ENDPOINT or "::" in ref or ref in known:
            return
        users.setdefault(ref, set()).add(user)

    for rule in rules.values():
        for ref in rule["source"] + rule["target"]:
            _reference(ref, rule["id"])
    for entry in elements.values():
        for constraint in entry["metaconstraints"]:
            for ref in constraint["constraints"]:
                _reference(ref, entry["name"])
        for relation in entry["metarelationships"]:
            for ref in relation["targets"]:
                _reference(ref, entry["name"])
        for ref in entry["generalizes"] + entry["baseStereotypes"]:
            _reference(ref, entry["name"])

    warnings = [
        {
            "kind": "unresolvedReference",
            "subject": ref,
            "detail": "referenziert von: " + ", ".join(sorted(users[ref])),
        }
        for ref in sorted(users)
    ]
    for entry in sorted(elements.values(), key=lambda item: item["name"]):
        if entry["metaclasses"]:
            continue
        suffix = " (als abstrakt markiert)" if entry["abstract"] else ""
        warnings.append(
            {
                "kind": "stereotypeWithoutMetaclass",
                "subject": entry["name"],
                "detail": "kein <Apply>; auf kein UML-Element anwendbar" + suffix,
            }
        )
    warnings.sort(key=lambda entry: (entry["kind"], entry["subject"]))
    return warnings


def parse_mdg(path: str | Path) -> dict[str, Any]:
    """Liest eine MDG-Datei und liefert das Regelwerk als dict."""
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise MdgParseError(f"{source}: Datei nicht lesbar: {exc}") from exc
    return parse_mdg_bytes(data, filename=source.name)


def parse_mdg_bytes(data: bytes, *, filename: str = "<memory>") -> dict[str, Any]:
    """Wie parse_mdg(), aber auf Rohbytes (testbar ohne Dateisystem)."""
    if not data.strip():
        raise MdgParseError(f"{filename}: Datei ist leer")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise MdgParseError(f"{filename}: kein gueltiges XML: {exc}") from exc

    root_tag = _local(root.tag)
    if root_tag not in ROOT_TAGS:
        raise MdgParseError(
            f"{filename}: Wurzelelement '{root_tag}' ist keine MDG-Technologie "
            f"(erwartet: {', '.join(sorted(ROOT_TAGS))})"
        )

    try:
        return _build_rules(root, filename=filename, data=data)
    except MdgParseError as exc:
        message = str(exc)
        if message.startswith(f"{filename}:"):
            raise
        raise MdgParseError(f"{filename}: {message}") from exc


def _build_rules(root: ET.Element, *, filename: str, data: bytes) -> dict[str, Any]:
    """Baut das Regelwerk aus dem geparsten XML-Baum."""
    digest = hashlib.sha256(data).hexdigest()
    header = _technology_header(root, filename, digest)

    prefixes: list[str] = [
        header["technologyId"],
        header["technologyName"],
        str(header["technologyVersion"]),
    ]
    for _, profile in _profiles(root):
        documentation = _kid(profile, "Documentation")
        if documentation is not None:
            prefixes.extend(value for value in (_attr(documentation, "id"), _attr(documentation, "name")) if value)
    names = _Names(prefixes)

    elements: dict[str, dict[str, Any]] = {}
    rules: dict[str, dict[str, Any]] = {}
    stereotypes_seen = 0

    for container, profile in _profiles(root):
        if container in IGNORED_PROFILE_CONTAINERS:
            continue
        for stereotype in _profile_stereotypes(profile):
            name = _attr(stereotype, "name")
            if not name:
                raise MdgParseError(f"{filename}: Stereotyp ohne Namen in Profil '{_profile_name(profile)}'")

            applies = _applies(stereotype, name)
            if _is_diagram_stereotype(applies):
                # Diagramm-Stereotypen sind Viewpoints, keine Modellregeln.
                continue

            stereotypes_seen += 1
            constraints = _metaconstraints(stereotype, names)
            source_roles = _roles(constraints, SOURCE_ROLES)
            target_roles = _roles(constraints, TARGET_ROLES)
            metaclasses = sorted({entry["metaclass"] for entry in applies})
            connector_metaclasses = [
                metaclass for metaclass in metaclasses if metaclass in CONNECTOR_METACLASSES
            ]

            definition = _definition(
                stereotype, applies=applies, constraints=constraints
            )

            if connector_metaclasses:
                source = _endpoints(constraints, SOURCE_ROLES)
                target = _endpoints(constraints, TARGET_ROLES)
                if not source and not target:
                    # Kein Endpunkt deklariert: bewusst unconstrained, nicht leer.
                    source = [ANY_ENDPOINT]
                    target = [ANY_ENDPOINT]
                elif not source or not target:
                    raise MdgParseError(
                        f"{filename}: Konnektor-Regel '{name}' deklariert nur eine Seite "
                        f"(source={source}, target={target})"
                    )
                rule = {
                    "id": f"cr:{name}",
                    "stereotype": name,
                    "source": source,
                    "target": target,
                    "direction": _direction(applies, connector_metaclasses),
                    "roles": {"source": source_roles, "target": target_roles},
                    **definition,
                    "metaclasses": connector_metaclasses,
                }
                _add_unique(rules, rule["id"], rule, "Konnektor-Regel")
                continue

            if source_roles or target_roles:
                raise MdgParseError(
                    f"{filename}: Stereotyp '{name}' deklariert Konnektor-Endpunkte, "
                    f"gilt aber fuer keine Konnektor-Metaklasse ({metaclasses or 'keine'})"
                )

            entry = {
                "name": name,
                **definition,
                "metarelationships": _metarelationships(stereotype, names),
            }
            _add_unique(elements, entry["name"], entry, "Element-Stereotyp")

    if stereotypes_seen == 0:
        raise MdgParseError(f"{filename}: Technologie enthaelt keine Stereotypen")

    viewpoint_list = _viewpoints(root, header["technologyName"])

    metaclass_usage: dict[str, dict[str, Any]] = {}

    def _note_usage(name: str, kind: str, *, stereotype: bool) -> None:
        entry = metaclass_usage.setdefault(
            name,
            {"name": name, "kinds": set(), "stereotypeCount": 0, "ruleCount": 0},
        )
        entry["kinds"].add(kind)
        if stereotype:
            entry["stereotypeCount"] += 1
        else:
            entry["ruleCount"] += 1

    for entry in elements.values():
        for metaclass in entry["metaclasses"]:
            kind = "connector" if metaclass in CONNECTOR_METACLASSES else "element"
            _note_usage(metaclass, kind, stereotype=True)
    for rule in rules.values():
        for metaclass in rule["metaclasses"]:
            _note_usage(metaclass, "connector", stereotype=False)

    metaclasses = [
        {
            "name": name,
            "kind": "mixed" if len(data_["kinds"]) > 1 else next(iter(data_["kinds"])),
            "stereotypeCount": data_["stereotypeCount"],
            "ruleCount": data_["ruleCount"],
        }
        for name, data_ in sorted(metaclass_usage.items())
    ]

    warnings = _collect_warnings(elements, rules)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": header,
        "elementStereotypes": [elements[name] for name in sorted(elements)],
        "connectorRules": [rules[key] for key in sorted(rules)],
        "viewpoints": viewpoint_list,
        "taggedValueTypes": _property_types(root),
        "metaclasses": metaclasses,
        "warnings": warnings,
        "stats": {
            "elementStereotypes": len(elements),
            "connectorRules": len(rules),
            "viewpoints": len(viewpoint_list),
            "metaclasses": len(metaclasses),
            "warnings": len(warnings),
        },
    }


# --------------------------------------------------------------------------
# Kanonische Serialisierung
# --------------------------------------------------------------------------


def dumps_rules(rules: dict[str, Any]) -> str:
    """Kanonischer Text: sortierte Schluessel, 2 Leerzeichen, UTF-8, LF."""
    return json.dumps(rules, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_rules(rules: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.write_text(dumps_rules(rules), encoding="utf-8", newline="\n")
    return target


def _summary(rules: dict[str, Any]) -> str:
    stats = rules["stats"]
    source = rules["source"]
    return (
        f"{source['technologyName']} {source['technologyVersion']}".strip()
        + f": {stats['elementStereotypes']} Element-Stereotypen,"
        + f" {stats['connectorRules']} Konnektor-Regeln,"
        + f" {stats['viewpoints']} Viewpoints,"
        + f" {stats['metaclasses']} Metaklassen"
        + (f", {stats['warnings']} Warnungen" if stats["warnings"] else "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mdg_parser.py",
        description="MDG-Technologie-XML in ein kanonisches Regelwerk (rules.json) uebersetzen.",
    )
    parser.add_argument("mdg", type=Path, help="MDG-/Technologie-XML")
    parser.add_argument("-o", "--out", type=Path, help="Ziel-Datei (sonst stdout)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Ergebnis gegen rules.schema.json pruefen (bricht bei Verstoss ab)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        # Das Schema gehoert zum Kern, nicht zum Regelwerk; der Pfad wird
        # relativ zur Datei aufgeloest, damit jeder Aufrufort passt.
        default=Path(__file__).resolve().parent.parent / "core" / "rules.schema.json",
        help="Pfad zum Schema (Default: neben dem Modul)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="keine Zusammenfassung")
    args = parser.parse_args(argv)

    try:
        rules = parse_mdg(args.mdg)
        if args.check:
            # Das Schema-Pruefwerkzeug liegt beim Kern; beim Aufruf aus
            # packages/rules muss der Suchpfad ergaenzt werden.
            _kern = Path(__file__).resolve().parent.parent / "core"
            if str(_kern) not in sys.path:
                sys.path.insert(0, str(_kern))
            from rules_schema import SchemaError, load_schema, validate

            try:
                validate(rules, load_schema(args.schema))
            except SchemaError as exc:
                raise MdgParseError(f"{args.schema}: Regelwerk verletzt das Schema: {exc}") from exc
        if args.out is not None:
            write_rules(rules, args.out)
        else:
            sys.stdout.write(dumps_rules(rules))
    except (MdgParseError, OSError) as exc:
        print(f"fehler: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        destination = f" -> {args.out}" if args.out is not None else ""
        print(_summary(rules) + destination, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
