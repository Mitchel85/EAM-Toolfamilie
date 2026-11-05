#!/usr/bin/env python3
"""Minimaler JSON-Schema-Pruefer fuer rules.json (Teilmenge von Draft 2020-12).

Warum eigener Pruefer: Der Kern des Projekts darf nur die Standardbibliothek
verwenden. Fuer die Selbstpruefung des Regelwerks genuegt eine kleine,
nachvollziehbare Teilmenge:

    $ref (nur lokal "#/$defs/..."), $defs, type (auch Liste), const, enum,
    required, properties, additionalProperties (bool), items, minLength,
    minItems, uniqueItems, pattern, minimum

Nicht unterstuetzt (bewusst, wuerde still durchrutschen): oneOf/anyOf/allOf,
if/then, Format-Pruefungen, externe Referenzen. Begegnet der Pruefer einem
dieser Schluessel, bricht er laut ab, statt ihn zu ignorieren.

Kein Netzwerk, keine Fremdbibliotheken.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Schluessel, die dieser Pruefer nicht auswertet. Sie duerfen im Schema nicht
# vorkommen, sonst wuerde eine Pruefung faelschlich "gruen" melden.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "oneOf",
        "anyOf",
        "allOf",
        "not",
        "if",
        "then",
        "else",
        "patternProperties",
        "propertyNames",
        "dependentRequired",
        "dependentSchemas",
        "prefixItems",
        "contains",
        "format",
        "multipleOf",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }
)

_TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


class SchemaError(Exception):
    """Dokument verletzt das Schema (oder das Schema nutzt Unbekanntes)."""


def load_schema(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"{source}: Schema nicht lesbar: {exc}") from exc
    try:
        schema = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"{source}: Schema ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(schema, dict):
        raise SchemaError(f"{source}: Schema-Wurzel muss ein Objekt sein")
    return schema


def validate(document: Any, schema: dict[str, Any]) -> None:
    """Prueft document gegen schema; wirft SchemaError mit JSON-Pfad."""
    _check_unsupported(schema, "$")
    _validate(document, schema, schema, "$")


def _check_unsupported(node: Any, path: str) -> None:
    if isinstance(node, dict):
        unknown = UNSUPPORTED_KEYWORDS.intersection(node)
        if unknown:
            raise SchemaError(
                f"{path}: nicht unterstuetzte Schema-Schluessel: {', '.join(sorted(unknown))}"
            )
        for key, value in node.items():
            _check_unsupported(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _check_unsupported(value, f"{path}/{index}")


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise SchemaError(f"externe $ref wird nicht unterstuetzt: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"$ref nicht aufloesbar: {ref}")
        node = node[part]
    if not isinstance(node, dict):
        raise SchemaError(f"$ref zeigt nicht auf ein Schema-Objekt: {ref}")
    return node


def _type_name(value: Any) -> str:
    for name, check in _TYPE_CHECKS.items():
        if check(value):
            return name
    return type(value).__name__


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        _validate(value, _resolve(schema["$ref"], root), root, path)
        return

    if "type" in schema:
        expected = schema["type"]
        expected_list = [expected] if isinstance(expected, str) else list(expected)
        for name in expected_list:
            if name not in _TYPE_CHECKS:
                raise SchemaError(f"{path}: unbekannter Typ im Schema: {name}")
        if not any(_TYPE_CHECKS[name](value) for name in expected_list):
            raise SchemaError(
                f"{path}: Typ {_type_name(value)} ist nicht erlaubt "
                f"(erwartet: {', '.join(expected_list)})"
            )

    if "const" in schema and value != schema["const"]:
        raise SchemaError(f"{path}: Wert {value!r} ist nicht {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: Wert {value!r} ist nicht in {schema['enum']!r}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaError(
                f"{path}: Zeichenkette zu kurz ({len(value)} < {schema['minLength']})"
            )
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise SchemaError(
                f"{path}: Wert {value!r} passt nicht auf Muster {schema['pattern']!r}"
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{path}: Wert {value!r} ist kleiner als {schema['minimum']!r}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaError(
                f"{path}: zu wenige Eintraege ({len(value)} < {schema['minItems']})"
            )
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(seen) != len(set(seen)):
                raise SchemaError(f"{path}: Eintraege sind nicht eindeutig")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate(item, item_schema, root, f"{path}/{index}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{path}: Pflichtfeld '{key}' fehlt")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], root, f"{path}/{key}")
            elif schema.get("additionalProperties") is False:
                raise SchemaError(f"{path}: unerlaubtes Feld '{key}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate(item, schema["additionalProperties"], root, f"{path}/{key}")
