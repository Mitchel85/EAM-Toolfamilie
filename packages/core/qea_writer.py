"""Deterministischer .qea-Writer: IR-JSON -> SQLite-Datei im Sparx-EA-Format.

Kernziel: gleicher IR-Input -> byte-identische Datei. Deshalb
  * keine Zeitstempel (CreatedDate/ModifiedDate bleiben leer),
  * keine Zufalls-GUIDs (sha256 aus Inhalt),
  * keine abhaengige Reihenfolge von der Reihenfolge im IR
    (alles wird kanonisch sortiert, IDs fortlaufend ab 1),
  * nur stdlib + sqlite3, kein Netzwerk.

IR-Format: siehe IR_SPEC.md. Oeffentliche API:

    plan_model(ir)                -> ModelPlan (validiert, sortiert, IDs + GUIDs)
    write_qea(ir_oder_pfad, ziel) -> Path
    render_bytes(ir)              -> bytes
    guid_for(paketpfad, stereotype, name) -> "{...}"
    normalize_guid(wert, feld)    -> "{...}"

Optional kann jedes Paket, Element und jede Kante ein Feld ``guid`` vorgeben
(Format ``{8-4-4-4-12}``, Hex, Gross-/Kleinschreibung und fehlende Klammern
egal; EA-Platzhalter-GUIDs werden ebenfalls akzeptiert). Fehlt es, wird die
GUID wie bisher deterministisch aus dem Inhalt berechnet. Dubletten je Tabelle
brechen laut ab. Elemente kennen zusaetzlich ``xref_tags``: Tagged Values, die
EA in ``t_xref``/``CustomProperties`` haelt.

Fehler werden laut geworfen (QeaWriterError), nie still verschluckt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

IR_VERSION = 1

# Kein Zeitstempel im Modell: EA-Defaults mit datetime('now') sind bewusst entfernt.
FIXED_DATE = ""
FIXED_VERSION = "1.0"
DEFAULT_DIRECTION = "Source -> Destination"
DEFAULT_OBJECT_TYPE = "Class"
DEFAULT_CONNECTOR_TYPE = "Dependency"

#: Schema-Version, die EA in ``usys_system`` ablegt (alle geprueften EA-Dateien).
SYSTEM_SCHEMA_VERSION = "4.01"

#: Pflicht-Tabellen laut AAroN (github.com/schmitze87/AAroN).
#:
#: ``AAroN-Core/src/main/java/aaron/sparx/SparxSQLiteConverter.java`` fragt
#: diese Tabellen in ``convert()`` bedingungslos ab; ``handleTable()`` faengt
#: die ``SQLException`` einer fehlenden Tabelle nicht ab, der Import bricht ab.
#: Deshalb legt der Writer sie alle an -- auch leer (0 Zeilen), denn AAroN
#: liest eine Tabelle, nicht ihre Zeilen.
AARON_REQUIRED_TABLES: tuple[str, ...] = (
    "usys_system",
    "t_package",
    "t_diagram",
    "t_object",
    "t_objectproperties",
    "t_attributeconstraints",
    "t_connector",
    "t_connectortag",
    "t_connectorconstraint",
    "t_diagramobjects",
    "t_diagramlinks",
    "t_operation",
    "t_operationtag",
    "t_attribute",
    "t_attributetag",
)

#: Zusaetzlich zu den 15 Pflichttabellen liest AAroN ``t_xref`` (Stereotype).
AARON_READ_TABLES: tuple[str, ...] = AARON_REQUIRED_TABLES + ("t_xref",)


_TOP_LEVEL_KEYS = {
    "ir_version",
    "technology",
    "meta",
    "packages",
    "elements",
    "connectors",
    "diagrams",
}
_TECHNOLOGY_KEYS = {"profile", "name", "version"}
_PACKAGE_KEYS = {"path", "name", "notes", "stereotype", "tags", "guid"}
_ELEMENT_KEYS = {
    "package",
    "name",
    "stereotype",
    "ea_type",
    "notes",
    "alias",
    "status",
    "tags",
    "guid",
    "xref_tags",
}
_CONNECTOR_KEYS = {
    "source",
    "target",
    "stereotype",
    "ea_type",
    "name",
    "direction",
    "notes",
    "tags",
    "guid",
}


class QeaWriterError(ValueError):
    """Eingabe- oder Zustandsfehler. Immer laut, nie still."""


# --------------------------------------------------------------------------
# GUIDs
# --------------------------------------------------------------------------


def guid_for(package_path: str, stereotype: str, name: str) -> str:
    """Kanonische Element-GUID: sha256("<paketpfad>|<stereotype>|<name>").

    Ergebnis im EA-Format {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX} (32 Hex,
    Grossbuchstaben). Doppelte Elemente (gleicher Schluessel) bekommen
    "#2", "#3", ... angehaengt -- siehe _assign_guids().
    """
    return _format_guid(f"{package_path}|{stereotype}|{name}")


def _format_guid(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32].upper()
    return (
        "{" + digest[0:8] + "-" + digest[8:12] + "-" + digest[12:16] + "-"
        + digest[16:20] + "-" + digest[20:32] + "}"
    )


_GUID_HEX_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
#: EA schreibt in Testmodellen auch Platzhalter-GUIDs wie
#: ``{MASC-PKG-0000-0000-0000-000000000001}``. Sie sind nicht hexadezimal,
#: aber gueltige, eindeutige EA-GUIDs -- der Writer nimmt sie unveraendert an
#: (nur Grossschreibung und Klammern werden kanonisiert), statt den Rueckweg
#: an einer Formalie scheitern zu lassen.
_GUID_LEGACY_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+){3,}$")


def normalize_guid(value: Any, what: str) -> str:
    """Kanonische EA-GUID: ``{8-4-4-4-12}`` in Grossbuchstaben.

    Akzeptiert mit und ohne geschweifte Klammern, Gross-/Kleinschreibung ist
    egal. Zusaetzlich werden die in EA-Testmodellen vorkommenden
    Platzhalter-GUIDs (Buchstaben statt Hexziffern) angenommen und
    grossgeschrieben zurueckgegeben.
    """
    text = _text(value, what, allow_empty=False).strip()
    if text.startswith("{") or text.endswith("}"):
        if not (text.startswith("{") and text.endswith("}")):
            _fail(f"{what}: unbalancierte geschweifte Klammern in {text!r}")
        text = text[1:-1]
    if not text or len(text) > 64:
        _fail(f"{what}: ungueltige GUID {value!r}")
    if any(character.isspace() for character in text):
        _fail(f"{what}: Leerzeichen in GUID {value!r}")
    if _GUID_HEX_RE.match(text):
        return "{" + text.upper() + "}"
    if _GUID_LEGACY_RE.match(text):
        return "{" + text.upper() + "}"
    _fail(
        f"{what}: GUID {value!r} hat nicht das Format "
        "'{8-4-4-4-12}' (Hexziffern) -- Beispiel: {00000000-0000-0000-0000-000000000000}"
    )


def _optional_guid(value: Any, what: str) -> str:
    """``guid`` ist optional; fehlt es, vergibt :func:`plan_model` wie bisher."""
    if value is None:
        return ""
    return normalize_guid(value, what)


# --------------------------------------------------------------------------
# Validierung
# --------------------------------------------------------------------------


def _fail(message: str) -> NoReturn:
    raise QeaWriterError(message)


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{what}: JSON-Objekt erwartet, gefunden {type(value).__name__}")
    return value


def _sequence(value: Any, what: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(f"{what}: JSON-Liste erwartet, gefunden {type(value).__name__}")
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
            _fail(f"{what}: Pflichtfeld fehlt")
        return default
    if not isinstance(value, str):
        _fail(f"{what}: Zeichenkette erwartet, gefunden {type(value).__name__}")
    if not allow_empty and not value.strip():
        _fail(f"{what}: darf nicht leer sein")
    return value


def _free_text(value: Any, what: str, *, default: str = "") -> str:
    """Freitext (Notizen, Tag-Werte): Inhalt unveraendert, auch mit Zeilenumbruechen."""
    if value is None:
        return default
    if not isinstance(value, str):
        _fail(f"{what}: Zeichenkette erwartet, gefunden {type(value).__name__}")
    return value


def _check_keys(obj: Mapping[str, Any], allowed: set[str], what: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        _fail(f"{what}: unbekannte Felder {unknown} (erlaubt: {sorted(allowed)})")


def _tags(value: Any, what: str) -> tuple[tuple[str, str], ...]:
    """Tagged Values als Tupel (Property, Value), kanonisch sortiert."""
    if value is None:
        return ()
    obj = _mapping(value, what)
    rows: list[tuple[str, str]] = []
    for key, val in obj.items():
        prop = _text(key, f"{what}.<Schluessel>", allow_empty=False)
        if isinstance(val, bool):
            text = "True" if val else "False"
        elif isinstance(val, (int, float)):
            text = str(val)
        elif val is None:
            _fail(f"{what}[{prop!r}]: Wert ist null")
        else:
            text = _free_text(val, f"{what}[{prop!r}]")
        rows.append((prop, text))
    return tuple(sorted(rows))


def _normalize_path(raw: Any, what: str) -> str:
    path = _text(raw, what, allow_empty=False)
    if "\\" in path:
        _fail(f"{what}: Backslash in Pfad {path!r} -- Pfadtrenner ist '/'")
    if "::" in path:
        _fail(f"{what}: '::' ist als Trenner fuer Element-Referenzen reserviert ({path!r})")
    if path.startswith("/") or path.endswith("/") or "//" in path:
        _fail(f"{what}: ungueltiger Pfad {path!r} (kein fuehrender/abschliessender '/', kein '//')")
    parts = path.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            _fail(f"{what}: ungueltiges Pfadsegment {part!r} in {path!r}")
    return path


# --------------------------------------------------------------------------
# Plan (validiertes, sortiertes Modell)
# --------------------------------------------------------------------------


@dataclass
class Package:
    path: str
    name: str
    parent_path: str
    stereotype: str
    notes: str
    tags: tuple[tuple[str, str], ...]
    guid: str = ""
    package_id: int = 0
    tpos: int = 0
    mirror_object_id: int | None = None
    mirror_tpos: int = 0


@dataclass
class Element:
    package_path: str
    name: str
    stereotype: str
    ea_type: str
    notes: str
    alias: str
    status: str
    tags: tuple[tuple[str, str], ...]
    guid: str = ""
    #: Tags, die EA in ``t_xref`` (Name='CustomProperties') haelt.
    xref_tags: tuple[tuple[str, str], ...] = ()
    object_id: int = 0
    tpos: int = 0


@dataclass
class Ref:
    """Kantenendpunkt: Element oder Paket (EA erlaubt beides)."""

    kind: str  # "element" | "package"
    package_path: str  # Containerpfad des Elements bzw. Pfad des Pakets
    name: str  # Elementname; "" bei Paketen
    element: Element | None = field(default=None, repr=False, compare=False)
    package: Package | None = field(default=None, repr=False, compare=False)


@dataclass
class Connector:
    source_package: str
    source_name: str
    target_package: str
    target_name: str
    stereotype: str
    ea_type: str
    name: str
    direction: str
    notes: str
    tags: tuple[tuple[str, str], ...]
    source: Ref | None = field(default=None, repr=False, compare=False)
    target: Ref | None = field(default=None, repr=False, compare=False)
    source_object_id: int = 0
    target_object_id: int = 0
    guid: str = ""
    connector_id: int = 0


@dataclass
class ModelPlan:
    profile: str
    packages: list[Package]
    elements: list[Element]
    connectors: list[Connector]
    # (object_id, property, value, guid)
    object_tags: list[tuple[int, str, str, str]] = field(default_factory=list)
    # (connector_id, property, value, guid)
    connector_tags: list[tuple[int, str, str, str]] = field(default_factory=list)
    # (xref_id, xref_name, xref_type, description, client_guid)
    xrefs: list[tuple[str, str, str, str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------
# Aufbau
# --------------------------------------------------------------------------


def _read_packages(ir: Mapping[str, Any]) -> list[Package]:
    raw = _sequence(ir.get("packages"), "packages")
    packages: dict[str, Package] = {}
    for index, item in enumerate(raw):
        what = f"packages[{index}]"
        obj = _mapping(item, what)
        _check_keys(obj, _PACKAGE_KEYS, what)
        path = _normalize_path(obj.get("path"), f"{what}.path")
        if path in packages:
            _fail(f"{what}.path: Paket {path!r} ist mehrfach deklariert")
        segment = path.rsplit("/", 1)[-1]
        declared = obj.get("name")
        name = (
            segment
            if declared is None
            else _text(declared, f"{what}.name", allow_empty=False)
        )
        packages[path] = Package(
            path=path,
            name=name,
            parent_path=path.rsplit("/", 1)[0] if "/" in path else "",
            stereotype=_text(obj.get("stereotype"), f"{what}.stereotype", default=""),
            notes=_free_text(obj.get("notes"), f"{what}.notes"),
            tags=_tags(obj.get("tags"), f"{what}.tags"),
            guid=_optional_guid(obj.get("guid"), f"{what}.guid"),
        )
    if not packages:
        _fail("packages: das IR enthaelt kein Paket -- eine leere .qea ist kein Ergebnis")
    for pkg in packages.values():
        if pkg.parent_path and pkg.parent_path not in packages:
            _fail(
                f"packages: Elternpaket {pkg.parent_path!r} von {pkg.path!r} ist nicht deklariert"
            )
    return [packages[path] for path in sorted(packages)]


def _element_name(value: Any, what: str) -> str:
    """Elementname verbatim. Leer ist erlaubt (echte Modelle enthalten z. B.
    unbenannte Notizen/Texte); referenziert werden sie ueber 'paket::#N'."""
    name = _text(value, what)
    if "::" in name:
        _fail(f"{what}: '::' ist im Elementnamen reserviert ({name!r})")
    return name


def _read_elements(ir: Mapping[str, Any], packages: Mapping[str, Package]) -> list[Element]:
    raw = _sequence(ir.get("elements"), "elements")
    elements: list[Element] = []
    for index, item in enumerate(raw):
        what = f"elements[{index}]"
        obj = _mapping(item, what)
        _check_keys(obj, _ELEMENT_KEYS, what)
        package = _normalize_path(obj.get("package"), f"{what}.package")
        if package not in packages:
            _fail(f"{what}.package: Paket {package!r} ist nicht deklariert")
        elements.append(
            Element(
                package_path=package,
                name=_element_name(obj.get("name"), f"{what}.name"),
                stereotype=_text(obj.get("stereotype"), f"{what}.stereotype", default=""),
                ea_type=_text(
                    obj.get("ea_type"),
                    f"{what}.ea_type",
                    default=DEFAULT_OBJECT_TYPE,
                    allow_empty=False,
                ),
                notes=_free_text(obj.get("notes"), f"{what}.notes"),
                alias=_text(obj.get("alias"), f"{what}.alias", default=""),
                status=_text(obj.get("status"), f"{what}.status", default=""),
                tags=_tags(obj.get("tags"), f"{what}.tags"),
                guid=_optional_guid(obj.get("guid"), f"{what}.guid"),
                xref_tags=_tags(obj.get("xref_tags"), f"{what}.xref_tags"),
            )
        )
    return elements


def _element_index(elements: Sequence[Element]) -> dict[tuple[str, str], list[Element]]:
    """(Paket, Name) -> Treffer in kanonischer Reihenfolge.

    Gleichnamige Elemente im selben Paket sind in echten Modellen vorhanden.
    Sie werden nach Inhalt sortiert; die Position (1-basiert) ist die Nummer,
    mit der eine Kanten-Referenz eindeutig adressiert ('paket::name#2').
    """
    index: dict[tuple[str, str], list[Element]] = {}
    for element in elements:
        index.setdefault((element.package_path, element.name), []).append(element)
    for group in index.values():
        group.sort(key=lambda e: (e.ea_type, e.notes, e.alias, e.status, e.tags))
    return index


def _resolve_ref(
    ref: Any,
    what: str,
    index: Mapping[tuple[str, str], list[Element]],
    packages: Mapping[str, Package],
) -> Ref:
    """Liest einen Endpunkt: '<paketpfad>::<elementname>[#N]' oder '<paketpfad>'."""
    text = _text(ref, what, allow_empty=False)

    if "::" not in text:
        path = _normalize_path(text, what)
        package = packages.get(path)
        if package is None:
            _fail(f"{what}: Referenz {text!r} zeigt auf kein deklariertes Paket")
        if not package.parent_path:
            _fail(
                f"{what}: Wurzelpaket {path!r} hat keinen t_object-Spiegel "
                "und kann kein Kantenendpunkt sein"
            )
        return Ref(kind="package", package_path=path, name="", package=package)

    package_path, rest = text.rsplit("::", 1)
    package_path = _normalize_path(package_path, f"{what}.package")
    if not rest:
        _fail(
            f"{what}: Elementname in Referenz {text!r} fehlt "
            "(unbenannte Elemente mit '<paket>::#<n>' adressieren)"
        )

    occurrence: int | None = None
    group = index.get((package_path, rest))
    if group is None:
        name, sep, number = rest.rpartition("#")
        if sep and number.isdigit():
            group = index.get((package_path, name))
            if group is not None:
                occurrence = int(number)
                rest = name
    if group is None:
        _fail(f"{what}: Referenz {text!r} zeigt auf kein deklariertes Element")
    if occurrence is None:
        if len(group) > 1:
            forms = ", ".join(f"{package_path}::{rest}#{pos}" for pos in range(1, len(group) + 1))
            _fail(
                f"{what}: Referenz {text!r} ist mehrdeutig ({len(group)} gleichnamige Elemente) "
                f"-- eindeutig mit {forms}"
            )
        element = group[0]
    else:
        if not 1 <= occurrence <= len(group):
            _fail(
                f"{what}: Referenz {text!r} verlangt Vorkommen {occurrence}, "
                f"vorhanden sind {len(group)}"
            )
        element = group[occurrence - 1]
    return Ref(
        kind="element",
        package_path=package_path,
        name=element.name,
        element=element,
    )


def _read_connectors(
    ir: Mapping[str, Any],
    elements: Sequence[Element],
    packages: Mapping[str, Package],
) -> list[Connector]:
    raw = _sequence(ir.get("connectors"), "connectors")
    index = _element_index(elements)
    connectors: list[Connector] = []
    for pos, item in enumerate(raw):
        what = f"connectors[{pos}]"
        obj = _mapping(item, what)
        _check_keys(obj, _CONNECTOR_KEYS, what)
        source = _resolve_ref(obj.get("source"), f"{what}.source", index, packages)
        target = _resolve_ref(obj.get("target"), f"{what}.target", index, packages)
        connectors.append(
            Connector(
                source_package=source.package_path,
                source_name=source.name,
                target_package=target.package_path,
                target_name=target.name,
                stereotype=_text(obj.get("stereotype"), f"{what}.stereotype", default=""),
                ea_type=_text(
                    obj.get("ea_type"),
                    f"{what}.ea_type",
                    default=DEFAULT_CONNECTOR_TYPE,
                    allow_empty=False,
                ),
                name=_text(obj.get("name"), f"{what}.name", default=""),
                direction=_text(
                    obj.get("direction"),
                    f"{what}.direction",
                    default=DEFAULT_DIRECTION,
                    allow_empty=False,
                ),
                notes=_free_text(obj.get("notes"), f"{what}.notes"),
                tags=_tags(obj.get("tags"), f"{what}.tags"),
                guid=_optional_guid(obj.get("guid"), f"{what}.guid"),
                source=source,
                target=target,
            )
        )
    return connectors


def _ref_guid(ref: Ref) -> str:
    if ref.element is not None:
        return ref.element.guid
    if ref.package is not None:
        return ref.package.guid
    _fail("interner Fehler: Endpunkt ohne Objekt")  # pragma: no cover


def _ref_object_id(ref: Ref) -> int:
    if ref.element is not None:
        return ref.element.object_id
    if ref.package is not None and ref.package.mirror_object_id is not None:
        return ref.package.mirror_object_id
    _fail(f"interner Fehler: Endpunkt {ref.package_path!r} ohne Object_ID")  # pragma: no cover


def _connector_base_key(connector: Connector) -> str:
    """GUID-Basis einer Kante: Endpunkt-Identitaet + Stereotyp + Name + Typ."""
    if connector.source is None or connector.target is None:  # pragma: no cover
        _fail("interner Fehler: Kante ohne aufgeloeste Endpunkte")
    return (
        f"connector|{_ref_guid(connector.source)}|{_ref_guid(connector.target)}"
        f"|{connector.stereotype}|{connector.name}|{connector.ea_type}"
    )


def _assign_guids(
    items: Sequence[Any],
    base_key,
    content_key,
    set_guid,
) -> None:
    """GUIDs deterministisch vergeben, Duplikate mit #2, #3 ... nummerieren.

    Der erste Treffer einer Basis behaelt die kanonische GUID. Weitere Treffer
    werden nach ihrem Inhalt sortiert und mit '<basis>#<n>' gehasht. Bei
    inhaltlich identischen Duplikaten ist die Zuordnung beliebig -- das
    Ergebnis ist trotzdem byte-identisch, weil die Zeilen ununterscheidbar sind.

    Objekte mit bereits gesetzter ``guid`` (Vorgabe aus dem IR) bleiben
    unangetastet; ihre Eindeutigkeit prueft :func:`_check_unique`.
    """
    groups: dict[str, list[Any]] = {}
    for item in items:
        if getattr(item, "guid", ""):
            continue
        groups.setdefault(base_key(item), []).append(item)
    for key in sorted(groups):
        group = sorted(groups[key], key=content_key)
        for offset, item in enumerate(group):
            set_guid(item, _format_guid(key if offset == 0 else f"{key}#{offset + 1}"))


def plan_model(ir: Any, *, allow_empty: bool = False) -> ModelPlan:
    """Validiert das IR, vergibt GUIDs und IDs, liefert den Schreibplan."""
    obj = _mapping(ir, "IR")
    _check_keys(obj, _TOP_LEVEL_KEYS, "IR")
    version = obj.get("ir_version")
    if version != IR_VERSION:
        _fail(f"ir_version: erwartet {IR_VERSION}, gefunden {version!r}")
    technology = _mapping(obj.get("technology", {}), "technology")
    _check_keys(technology, _TECHNOLOGY_KEYS, "technology")
    profile = _text(technology.get("profile"), "technology.profile", default="")
    if obj.get("diagrams"):
        _fail(
            "diagrams: Sichten sind bewusst nicht Teil des Writers "
            "(keine Sichten, kein Layout) -- Liste muss leer sein"
        )

    packages = _read_packages(obj)
    package_map = {pkg.path: pkg for pkg in packages}
    elements = _read_elements(obj, package_map)
    if not elements and not allow_empty:
        _fail("elements: das IR enthaelt kein Element -- Abbruch statt leeres Modell")
    connectors = _read_connectors(obj, elements, package_map)

    # Paket-GUID: letztes Pfadsegment (logischer Schluessel), nicht der Anzeigename
    _assign_guids(
        packages,
        base_key=lambda p: f"{p.parent_path}|Package|{p.path.rsplit('/', 1)[-1]}",
        content_key=lambda p: (p.notes, p.tags),
        set_guid=lambda p, g: setattr(p, "guid", g),
    )
    # Element-GUID: sha256("<paketpfad>|<stereotype>|<name>")
    _assign_guids(
        elements,
        base_key=lambda e: f"{e.package_path}|{e.stereotype}|{e.name}",
        content_key=lambda e: (e.ea_type, e.notes, e.alias, e.status, e.tags),
        set_guid=lambda e, g: setattr(e, "guid", g),
    )

    # Paket-IDs: 1..N in Pfadsortierung (stabil), TPos je Elternpaket
    sibling_positions: dict[str, int] = {}
    for package in sorted(packages, key=lambda p: p.path):
        package.tpos = sibling_positions.get(package.parent_path, 0)
        sibling_positions[package.parent_path] = package.tpos + 1
    for package_id, package in enumerate(sorted(packages, key=lambda p: p.path), start=1):
        package.package_id = package_id

    # Objekt-IDs: Paketspiegel + Elemente gemeinsam, getrennte Nummernraeume
    # zu t_package. Sortierung (Paketpfad, Name, Stereotyp, ea_type, GUID).
    object_rows: list[tuple[tuple[Any, ...], Any]] = []
    for package in packages:
        if not package.parent_path:
            continue  # Wurzelpaket hat keinen t_object-Spiegel (EA-Konvention)
        object_rows.append(
            (
                (package.parent_path, package.name, "Package", "Package", package.guid),
                package,
            )
        )
    for element in elements:
        object_rows.append(
            (
                (element.package_path, element.name, element.stereotype, element.ea_type, element.guid),
                element,
            )
        )
    object_rows.sort(key=lambda item: item[0])
    per_package_tpos: dict[str, int] = {}
    for object_id, (_, owner) in enumerate(object_rows, start=1):
        if isinstance(owner, Package):
            owner.mirror_object_id = object_id
            owner.mirror_tpos = owner.tpos
            per_package_tpos.setdefault(owner.parent_path, 0)
        else:
            owner.object_id = object_id
            owner.tpos = per_package_tpos.get(owner.package_path, 0)
            per_package_tpos[owner.package_path] = owner.tpos + 1

    # Kanten-GUID: Endpunkt-GUIDs + Stereotyp + Name + Typ, Duplikate #n
    _assign_guids(
        connectors,
        base_key=_connector_base_key,
        content_key=lambda c: (c.direction, c.notes, c.tags),
        set_guid=lambda c, g: setattr(c, "guid", g),
    )
    for connector_id, connector in enumerate(
        sorted(
            connectors,
            key=lambda c: (
                c.source_package,
                c.source_name,
                c.target_package,
                c.target_name,
                c.stereotype,
                c.name,
                c.ea_type,
                c.guid,
            ),
        ),
        start=1,
    ):
        connector.connector_id = connector_id
        if connector.source is None or connector.target is None:  # pragma: no cover
            _fail("interner Fehler: Kante ohne aufgeloeste Endpunkte")
        connector.source_object_id = _ref_object_id(connector.source)
        connector.target_object_id = _ref_object_id(connector.target)

    # Tagged Values: eigene GUIDs, IDs in (Owner-ID, Property)-Sortierung
    object_tags: list[tuple[int, str, str, str]] = []
    for element in sorted(elements, key=lambda e: e.object_id):
        for prop, value in sorted(element.tags):
            object_tags.append(
                (element.object_id, prop, value, _format_guid(f"tag|{element.guid}|{prop}"))
            )
    for package in sorted(packages, key=lambda p: p.package_id):
        owner_guid = package.guid
        owner_id = package.mirror_object_id if package.mirror_object_id else 0
        if not owner_id:
            # Wurzelpaket ohne Spiegel: Tags haengen am Paket selbst (Object_ID 0
            # waere falsch) -- deshalb laut abbrechen statt still verlieren.
            if package.tags:
                _fail(
                    f"packages[{package.path!r}].tags: Wurzelpakete haben keinen "
                    "t_object-Spiegel und koennen keine Tagged Values tragen"
                )
            continue
        for prop, value in sorted(package.tags):
            object_tags.append((owner_id, prop, value, _format_guid(f"tag|{owner_guid}|{prop}")))
    object_tags.sort(key=lambda row: (row[0], row[1]))

    connector_tags: list[tuple[int, str, str, str]] = []
    for connector in sorted(connectors, key=lambda c: c.connector_id):
        for prop, value in sorted(connector.tags):
            connector_tags.append(
                (connector.connector_id, prop, value, _format_guid(f"tag|{connector.guid}|{prop}"))
            )
    connector_tags.sort(key=lambda row: (row[0], row[1]))

    # t_xref: Stereotyp-Eintraege (EA-Konvention @STEREO;Name=...;FQName=...;@ENDSTEREO;)
    # und CustomProperties (Tagged Values, die EA nicht in t_objectproperties haelt).
    # Tupel: (XrefID, Name, Type, Description, Client)
    xrefs: list[tuple[str, str, str, str, str]] = []
    for package in packages:
        if package.stereotype:
            xrefs.append(
                (
                    _format_guid(f"xref|element property|{package.guid}|{package.stereotype}"),
                    "Stereotypes",
                    "element property",
                    _stereo_description(package.stereotype, profile),
                    package.guid,
                )
            )
    for element in elements:
        if element.stereotype:
            xrefs.append(
                (
                    _format_guid(f"xref|element property|{element.guid}|{element.stereotype}"),
                    "Stereotypes",
                    "element property",
                    _stereo_description(element.stereotype, profile),
                    element.guid,
                )
            )
        for prop, value in sorted(element.xref_tags):
            xrefs.append(
                (
                    _format_guid(f"xref|CustomProperties|{element.guid}|{prop}"),
                    "CustomProperties",
                    "element property",
                    _custom_prop_description(prop, value),
                    element.guid,
                )
            )
    for connector in connectors:
        if connector.stereotype:
            xrefs.append(
                (
                    _format_guid(f"xref|connector property|{connector.guid}|{connector.stereotype}"),
                    "Stereotypes",
                    "connector property",
                    _stereo_description(connector.stereotype, profile),
                    connector.guid,
                )
            )
    xrefs.sort(key=lambda row: (row[4], row[2], row[1], row[3]))
    _check_unique(
        [r[0] for r in xrefs], "t_xref.XrefID (GUID-Kollision zwischen Stereotyp-Eintraegen)"
    )

    _check_unique([p.guid for p in packages], "t_package.ea_guid")
    _check_unique([e.guid for e in elements], "t_object.ea_guid (Elemente)")
    all_object_guids = [p.guid for p in packages] + [e.guid for e in elements]
    _check_unique(all_object_guids, "t_object.ea_guid")
    _check_unique([c.guid for c in connectors], "t_connector.ea_guid")

    return ModelPlan(
        profile=profile,
        packages=sorted(packages, key=lambda p: p.package_id),
        elements=sorted(elements, key=lambda e: e.object_id),
        connectors=sorted(connectors, key=lambda c: c.connector_id),
        object_tags=object_tags,
        connector_tags=connector_tags,
        xrefs=xrefs,
    )


def _check_unique(values: Sequence[str], what: str) -> None:
    seen: dict[str, int] = {}
    for value in values:
        seen[value] = seen.get(value, 0) + 1
    duplicates = sorted(v for v, count in seen.items() if count > 1)
    if duplicates:
        _fail(f"{what}: doppelte GUID(s) {duplicates[:5]} -- Input nicht eindeutig")


def _stereo_description(stereotype: str, profile: str) -> str:
    fq = f"FQName={profile}::{stereotype};" if profile else ""
    return f"@STEREO;Name={stereotype};{fq}@ENDSTEREO;"


def _custom_prop_description(prop: str, value: str) -> str:
    """Ein ``@PROP=``-Block, wie EA ihn in ``t_xref.Description`` ablegt."""
    return (
        f"@PROP=@NAME={prop}@ENDNAME;@TYPE=string@ENDTYPE;"
        f"@VALU={value}@ENDVALU;@PRMT=@ENDPRMT;@ENDPROP;"
    )


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

_TABLE_DDL: dict[str, tuple[str, ...]] = {
    "t_package": (
        '"Package_ID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"Name" TEXT NULL COLLATE NOCASE',
        '"Parent_ID" INTEGER NULL DEFAULT 0',
        f'"CreatedDate" TEXT NULL DEFAULT \'{FIXED_DATE}\' COLLATE NOCASE',
        f'"ModifiedDate" TEXT NULL DEFAULT \'{FIXED_DATE}\' COLLATE NOCASE',
        '"Notes" TEXT NULL COLLATE NOCASE',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
        '"XMLPath" TEXT NULL COLLATE NOCASE',
        '"IsControlled" INTEGER NULL DEFAULT 0',
        '"LastLoadDate" TEXT NULL COLLATE NOCASE',
        '"LastSaveDate" TEXT NULL COLLATE NOCASE',
        f'"Version" TEXT NULL DEFAULT \'{FIXED_VERSION}\' COLLATE NOCASE',
        '"Protected" INTEGER NULL DEFAULT 0',
        '"PkgOwner" TEXT NULL COLLATE NOCASE',
        '"UMLVersion" TEXT NULL COLLATE NOCASE',
        '"UseDTD" INTEGER NULL DEFAULT 0',
        '"LogXML" INTEGER NULL DEFAULT 0',
        '"CodePath" TEXT NULL COLLATE NOCASE',
        '"Namespace" TEXT NULL COLLATE NOCASE',
        '"TPos" INTEGER NULL',
        '"PackageFlags" TEXT NULL COLLATE NOCASE',
        '"BatchSave" INTEGER NULL',
        '"BatchLoad" INTEGER NULL',
    ),
    "t_object": (
        '"Object_ID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"Object_Type" TEXT NULL COLLATE NOCASE',
        '"Diagram_ID" INTEGER NULL DEFAULT 0',
        '"Name" TEXT NULL COLLATE NOCASE',
        '"Alias" TEXT NULL COLLATE NOCASE',
        '"Author" TEXT NULL COLLATE NOCASE',
        f'"Version" TEXT NULL DEFAULT \'{FIXED_VERSION}\' COLLATE NOCASE',
        '"Note" TEXT NULL COLLATE NOCASE',
        '"Package_ID" INTEGER NULL DEFAULT 0',
        '"Stereotype" TEXT NULL COLLATE NOCASE',
        '"NType" INTEGER NULL DEFAULT 0',
        '"Complexity" TEXT NULL DEFAULT \'2\' COLLATE NOCASE',
        '"Effort" INTEGER NULL DEFAULT 0',
        '"Style" TEXT NULL COLLATE NOCASE',
        '"Backcolor" INTEGER NULL DEFAULT 0',
        '"BorderStyle" INTEGER NULL DEFAULT 0',
        '"BorderWidth" INTEGER NULL DEFAULT 0',
        '"Fontcolor" INTEGER NULL DEFAULT 0',
        '"Bordercolor" INTEGER NULL DEFAULT 0',
        f'"CreatedDate" TEXT NULL DEFAULT \'{FIXED_DATE}\' COLLATE NOCASE',
        f'"ModifiedDate" TEXT NULL DEFAULT \'{FIXED_DATE}\' COLLATE NOCASE',
        '"Status" TEXT NULL COLLATE NOCASE',
        '"Abstract" TEXT NULL COLLATE NOCASE',
        '"Tagged" INTEGER NULL DEFAULT 0',
        '"PDATA1" TEXT NULL COLLATE NOCASE',
        '"PDATA2" TEXT NULL COLLATE NOCASE',
        '"PDATA3" TEXT NULL COLLATE NOCASE',
        '"PDATA4" TEXT NULL COLLATE NOCASE',
        '"PDATA5" TEXT NULL COLLATE NOCASE',
        '"Concurrency" TEXT NULL COLLATE NOCASE',
        '"Visibility" TEXT NULL COLLATE NOCASE',
        '"Persistence" TEXT NULL COLLATE NOCASE',
        '"Cardinality" TEXT NULL COLLATE NOCASE',
        '"GenType" TEXT NULL COLLATE NOCASE',
        '"GenFile" TEXT NULL COLLATE NOCASE',
        '"Header1" TEXT NULL COLLATE NOCASE',
        '"Header2" TEXT NULL COLLATE NOCASE',
        '"Phase" TEXT NULL COLLATE NOCASE',
        '"Scope" TEXT NULL COLLATE NOCASE',
        '"GenOption" TEXT NULL COLLATE NOCASE',
        '"GenLinks" TEXT NULL COLLATE NOCASE',
        '"Classifier" INTEGER NULL',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
        '"ParentID" INTEGER NULL',
        '"RunState" TEXT NULL COLLATE NOCASE',
        '"Classifier_guid" TEXT NULL COLLATE NOCASE',
        '"TPos" INTEGER NULL',
        '"IsRoot" INTEGER NULL DEFAULT 0',
        '"IsLeaf" INTEGER NULL DEFAULT 0',
        '"IsSpec" INTEGER NULL DEFAULT 0',
        '"IsActive" INTEGER NULL DEFAULT 0',
        '"StateFlags" TEXT NULL COLLATE NOCASE',
        '"PackageFlags" TEXT NULL COLLATE NOCASE',
        '"Multiplicity" TEXT NULL COLLATE NOCASE',
        '"StyleEx" TEXT NULL COLLATE NOCASE',
        '"ActionFlags" TEXT NULL COLLATE NOCASE',
        '"EventFlags" TEXT NULL COLLATE NOCASE',
    ),
    "t_connector": (
        '"Connector_ID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"Name" TEXT NULL COLLATE NOCASE',
        '"Direction" TEXT NULL COLLATE NOCASE',
        '"Notes" TEXT NULL COLLATE NOCASE',
        '"Connector_Type" TEXT NULL COLLATE NOCASE',
        '"SubType" TEXT NULL COLLATE NOCASE',
        '"SourceCard" TEXT NULL COLLATE NOCASE',
        '"SourceAccess" TEXT NULL COLLATE NOCASE',
        '"SourceElement" TEXT NULL COLLATE NOCASE',
        '"DestCard" TEXT NULL COLLATE NOCASE',
        '"DestAccess" TEXT NULL COLLATE NOCASE',
        '"DestElement" TEXT NULL COLLATE NOCASE',
        '"SourceRole" TEXT NULL COLLATE NOCASE',
        '"SourceRoleType" TEXT NULL COLLATE NOCASE',
        '"SourceRoleNote" TEXT NULL COLLATE NOCASE',
        '"SourceContainment" TEXT NULL COLLATE NOCASE',
        '"SourceIsAggregate" INTEGER NULL DEFAULT 0',
        '"SourceIsOrdered" INTEGER NULL DEFAULT 0',
        '"SourceQualifier" TEXT NULL COLLATE NOCASE',
        '"DestRole" TEXT NULL COLLATE NOCASE',
        '"DestRoleType" TEXT NULL COLLATE NOCASE',
        '"DestRoleNote" TEXT NULL COLLATE NOCASE',
        '"DestContainment" TEXT NULL COLLATE NOCASE',
        '"DestIsAggregate" INTEGER NULL DEFAULT 0',
        '"DestIsOrdered" INTEGER NULL DEFAULT 0',
        '"DestQualifier" TEXT NULL COLLATE NOCASE',
        '"Start_Object_ID" INTEGER NULL DEFAULT 0',
        '"End_Object_ID" INTEGER NULL DEFAULT 0',
        '"Top_Start_Label" TEXT NULL COLLATE NOCASE',
        '"Top_Mid_Label" TEXT NULL COLLATE NOCASE',
        '"Top_End_Label" TEXT NULL COLLATE NOCASE',
        '"Btm_Start_Label" TEXT NULL COLLATE NOCASE',
        '"Btm_Mid_Label" TEXT NULL COLLATE NOCASE',
        '"Btm_End_Label" TEXT NULL COLLATE NOCASE',
        '"Start_Edge" INTEGER NULL DEFAULT 0',
        '"End_Edge" INTEGER NULL DEFAULT 0',
        '"PtStartX" INTEGER NULL DEFAULT 0',
        '"PtStartY" INTEGER NULL DEFAULT 0',
        '"PtEndX" INTEGER NULL DEFAULT 0',
        '"PtEndY" INTEGER NULL DEFAULT 0',
        '"SeqNo" INTEGER NULL DEFAULT 0',
        '"HeadStyle" INTEGER NULL DEFAULT 0',
        '"LineStyle" INTEGER NULL DEFAULT 0',
        '"RouteStyle" INTEGER NULL DEFAULT 0',
        '"IsBold" INTEGER NULL DEFAULT 0',
        '"LineColor" INTEGER NULL DEFAULT 0',
        '"Stereotype" TEXT NULL COLLATE NOCASE',
        '"VirtualInheritance" TEXT NULL COLLATE NOCASE',
        '"LinkAccess" TEXT NULL COLLATE NOCASE',
        '"PDATA1" TEXT NULL COLLATE NOCASE',
        '"PDATA2" TEXT NULL COLLATE NOCASE',
        '"PDATA3" TEXT NULL COLLATE NOCASE',
        '"PDATA4" TEXT NULL COLLATE NOCASE',
        '"PDATA5" TEXT NULL COLLATE NOCASE',
        '"DiagramID" INTEGER NULL DEFAULT 0',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
        '"SourceConstraint" TEXT NULL COLLATE NOCASE',
        '"DestConstraint" TEXT NULL COLLATE NOCASE',
        '"SourceIsNavigable" INTEGER NULL',
        '"DestIsNavigable" INTEGER NULL',
        '"IsRoot" INTEGER NULL',
        '"IsLeaf" INTEGER NULL',
        '"IsSpec" INTEGER NULL',
        '"SourceChangeable" TEXT NULL COLLATE NOCASE',
        '"DestChangeable" TEXT NULL COLLATE NOCASE',
        '"SourceTS" TEXT NULL COLLATE NOCASE',
        '"DestTS" TEXT NULL COLLATE NOCASE',
        '"StateFlags" TEXT NULL COLLATE NOCASE',
        '"ActionFlags" TEXT NULL COLLATE NOCASE',
        '"IsSignal" INTEGER NULL',
        '"IsStimulus" INTEGER NULL',
        '"DispatchAction" TEXT NULL COLLATE NOCASE',
        '"Target2" INTEGER NULL',
        '"StyleEx" TEXT NULL COLLATE NOCASE',
        '"SourceStereotype" TEXT NULL COLLATE NOCASE',
        '"DestStereotype" TEXT NULL COLLATE NOCASE',
        '"SourceStyle" TEXT NULL COLLATE NOCASE',
        '"DestStyle" TEXT NULL COLLATE NOCASE',
        '"EventFlags" TEXT NULL COLLATE NOCASE',
    ),
    "t_objectproperties": (
        '"PropertyID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"Object_ID" INTEGER NULL DEFAULT 0',
        '"Property" TEXT NULL COLLATE NOCASE',
        '"Value" TEXT NULL COLLATE NOCASE',
        '"Notes" TEXT NULL COLLATE NOCASE',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
    ),
    "t_connectortag": (
        '"PropertyID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"ElementID" INTEGER NULL DEFAULT 0',
        '"Property" TEXT NULL COLLATE NOCASE',
        '"VALUE" TEXT NULL COLLATE NOCASE',
        '"NOTES" TEXT NULL COLLATE NOCASE',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
    ),
    "t_diagram": (
        '"Diagram_ID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"Package_ID" INTEGER NULL DEFAULT 1',
        '"ParentID" INTEGER NULL DEFAULT 0',
        '"Diagram_Type" TEXT NULL COLLATE NOCASE',
        '"Name" TEXT NULL COLLATE NOCASE',
        f'"Version" TEXT NULL DEFAULT \'{FIXED_VERSION}\' COLLATE NOCASE',
        '"Author" TEXT NULL COLLATE NOCASE',
        '"ShowDetails" INTEGER NULL DEFAULT 0',
        '"Notes" TEXT NULL COLLATE NOCASE',
        '"Stereotype" TEXT NULL COLLATE NOCASE',
        '"AttPub" INTEGER NOT NULL DEFAULT 1',
        '"AttPri" INTEGER NOT NULL DEFAULT 1',
        '"AttPro" INTEGER NOT NULL DEFAULT 1',
        '"Orientation" TEXT NULL DEFAULT \'P\' COLLATE NOCASE',
        '"cx" INTEGER NULL DEFAULT 0',
        '"cy" INTEGER NULL DEFAULT 0',
        '"Scale" INTEGER NULL DEFAULT 100',
        f'"CreatedDate" TEXT NULL DEFAULT \'{FIXED_DATE}\' COLLATE NOCASE',
        f'"ModifiedDate" TEXT NULL DEFAULT \'{FIXED_DATE}\' COLLATE NOCASE',
        '"HTMLPath" TEXT NULL COLLATE NOCASE',
        '"ShowForeign" INTEGER NOT NULL DEFAULT 1',
        '"ShowBorder" INTEGER NOT NULL DEFAULT 1',
        '"ShowPackageContents" INTEGER NOT NULL DEFAULT 1',
        '"PDATA" TEXT NULL COLLATE NOCASE',
        '"Locked" INTEGER NOT NULL DEFAULT 0',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
        '"TPos" INTEGER NULL',
        '"Swimlanes" TEXT NULL COLLATE NOCASE',
        '"StyleEx" TEXT NULL COLLATE NOCASE',
    ),
    "t_xref": (
        '"XrefID" TEXT NOT NULL COLLATE NOCASE PRIMARY KEY',
        '"Name" TEXT NULL COLLATE NOCASE',
        '"Type" TEXT NULL COLLATE NOCASE',
        '"Visibility" TEXT NULL COLLATE NOCASE',
        '"Namespace" TEXT NULL COLLATE NOCASE',
        '"Requirement" TEXT NULL COLLATE NOCASE',
        '"Constraint" TEXT NULL COLLATE NOCASE',
        '"Behavior" TEXT NULL COLLATE NOCASE',
        '"Partition" TEXT NULL COLLATE NOCASE',
        '"Description" TEXT NULL COLLATE NOCASE',
        '"Client" TEXT NULL COLLATE NOCASE',
        '"Supplier" TEXT NULL COLLATE NOCASE',
        '"Link" TEXT NULL COLLATE NOCASE',
    ),
    # --- AAroN-Pflichttabellen: Spalten exakt wie Sparx EA -------------------
    # Belegt an drei unabhaengig erzeugten EA-Dateien (identische DDL). Die
    # Tabellen bleiben leer, wenn das IR nichts dafuer enthaelt; Ausnahmen:
    # usys_system (Projektkennung + Schema-Version).
    "usys_system": (
        '"Property" TEXT NOT NULL COLLATE NOCASE PRIMARY KEY',
        '"Value" TEXT NULL COLLATE NOCASE',
    ),
    "t_attribute": (
        '"Object_ID" INTEGER NULL DEFAULT 0',
        '"Name" TEXT NULL COLLATE NOCASE',
        '"Scope" TEXT NULL COLLATE NOCASE',
        '"Stereotype" TEXT NULL COLLATE NOCASE',
        '"Containment" TEXT NULL COLLATE NOCASE',
        '"IsStatic" INTEGER NULL DEFAULT 0',
        '"IsCollection" INTEGER NULL DEFAULT 0',
        '"IsOrdered" INTEGER NULL DEFAULT 0',
        '"AllowDuplicates" INTEGER NULL DEFAULT 0',
        '"LowerBound" TEXT NULL COLLATE NOCASE',
        '"UpperBound" TEXT NULL COLLATE NOCASE',
        '"Container" TEXT NULL COLLATE NOCASE',
        '"Notes" TEXT NULL COLLATE NOCASE',
        '"Derived" TEXT NULL COLLATE NOCASE',
        '"ID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"Pos" INTEGER NULL',
        '"GenOption" TEXT NULL COLLATE NOCASE',
        '"Length" INTEGER NULL',
        '"Precision" INTEGER NULL',
        '"Scale" INTEGER NULL',
        '"Const" INTEGER NULL',
        '"Style" TEXT NULL COLLATE NOCASE',
        '"Classifier" TEXT NULL COLLATE NOCASE',
        '"Default" TEXT NULL COLLATE NOCASE',
        '"Type" TEXT NULL COLLATE NOCASE',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
        '"StyleEx" TEXT NULL COLLATE NOCASE',
    ),
    "t_attributetag": (
        '"PropertyID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"ElementID" INTEGER NULL DEFAULT 0',
        '"Property" TEXT NULL COLLATE NOCASE',
        '"VALUE" TEXT NULL COLLATE NOCASE',
        '"NOTES" TEXT NULL COLLATE NOCASE',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
    ),
    "t_attributeconstraints": (
        '"Object_ID" INTEGER NULL DEFAULT 0',
        '"Constraint" TEXT NOT NULL COLLATE NOCASE',
        '"AttName" TEXT NULL COLLATE NOCASE',
        '"Type" TEXT NULL COLLATE NOCASE',
        '"Notes" TEXT NULL COLLATE NOCASE',
        '"ID" INTEGER NOT NULL',
        'CONSTRAINT pk_attributeconstraints PRIMARY KEY ("Constraint", "ID")',
    ),
    "t_operation": (
        '"OperationID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"Object_ID" INTEGER NULL DEFAULT 0',
        '"Name" TEXT NULL COLLATE NOCASE',
        '"Scope" TEXT NULL COLLATE NOCASE',
        '"Type" TEXT NULL COLLATE NOCASE',
        '"ReturnArray" TEXT NULL COLLATE NOCASE',
        '"Stereotype" TEXT NULL COLLATE NOCASE',
        '"IsStatic" TEXT NULL COLLATE NOCASE',
        '"Concurrency" TEXT NULL COLLATE NOCASE',
        '"Notes" TEXT NULL COLLATE NOCASE',
        '"Behaviour" TEXT NULL COLLATE NOCASE',
        '"Abstract" TEXT NULL COLLATE NOCASE',
        '"GenOption" TEXT NULL COLLATE NOCASE',
        '"Synchronized" TEXT NULL COLLATE NOCASE',
        '"Pos" INTEGER NULL',
        '"Const" INTEGER NULL',
        '"Style" TEXT NULL COLLATE NOCASE',
        '"Pure" INTEGER NULL DEFAULT 0',
        '"Throws" TEXT NULL COLLATE NOCASE',
        '"Classifier" TEXT NULL COLLATE NOCASE',
        '"Code" TEXT NULL COLLATE NOCASE',
        '"IsRoot" INTEGER NULL DEFAULT 0',
        '"IsLeaf" INTEGER NULL DEFAULT 0',
        '"IsQuery" INTEGER NULL DEFAULT 0',
        '"StateFlags" TEXT NULL COLLATE NOCASE',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
        '"StyleEx" TEXT NULL COLLATE NOCASE',
    ),
    "t_operationtag": (
        '"PropertyID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
        '"ElementID" INTEGER NULL DEFAULT 0',
        '"Property" TEXT NULL COLLATE NOCASE',
        '"VALUE" TEXT NULL COLLATE NOCASE',
        '"NOTES" TEXT NULL COLLATE NOCASE',
        '"ea_guid" TEXT NULL COLLATE NOCASE',
    ),
    "t_connectorconstraint": (
        '"ConnectorID" INTEGER NOT NULL DEFAULT 0',
        '"Constraint" TEXT NOT NULL COLLATE NOCASE',
        '"ConstraintType" TEXT NULL COLLATE NOCASE',
        '"Notes" TEXT NULL COLLATE NOCASE',
        'CONSTRAINT pk_connectorconstraint PRIMARY KEY ("ConnectorID", "Constraint")',
    ),
    "t_diagramobjects": (
        '"Diagram_ID" INTEGER NULL DEFAULT 0',
        '"Object_ID" INTEGER NULL DEFAULT 0',
        '"RectTop" INTEGER NULL DEFAULT 0',
        '"RectLeft" INTEGER NULL DEFAULT 0',
        '"RectRight" INTEGER NULL DEFAULT 0',
        '"RectBottom" INTEGER NULL DEFAULT 0',
        '"Sequence" INTEGER NULL DEFAULT 0',
        '"ObjectStyle" TEXT NULL COLLATE NOCASE',
        '"Instance_ID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
    ),
    "t_diagramlinks": (
        '"DiagramID" INTEGER NULL',
        '"ConnectorID" INTEGER NULL DEFAULT 0',
        '"Geometry" TEXT NULL COLLATE NOCASE',
        '"Style" TEXT NULL COLLATE NOCASE',
        '"Hidden" INTEGER NOT NULL DEFAULT 0',
        '"Path" TEXT NULL COLLATE NOCASE',
        '"Instance_ID" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT',
    ),
}

_INDEX_DDL: tuple[str, ...] = (
    'CREATE INDEX "ix_package_parentid" ON "t_package" ("Parent_ID" ASC)',
    'CREATE UNIQUE INDEX "uq_package_eaguid" ON "t_package" ("ea_guid" ASC)',
    'CREATE INDEX "ix_object_packageid" ON "t_object" ("Package_ID" ASC)',
    'CREATE INDEX "ix_object_name" ON "t_object" ("Name" ASC)',
    'CREATE INDEX "ix_object_objecttype" ON "t_object" ("Object_Type" ASC)',
    'CREATE UNIQUE INDEX "uq_object_eaguid" ON "t_object" ("ea_guid" ASC)',
    'CREATE INDEX "ix_connector_startobjectid" ON "t_connector" ("Start_Object_ID" ASC)',
    'CREATE INDEX "ix_connector_endobjectid" ON "t_connector" ("End_Object_ID" ASC)',
    'CREATE INDEX "ix_connector_connectortype" ON "t_connector" ("Connector_Type" ASC)',
    'CREATE UNIQUE INDEX "uq_connector_eaguid" ON "t_connector" ("ea_guid" ASC)',
    'CREATE INDEX "ix_objectproperties_objectid" ON "t_objectproperties" ("Object_ID" ASC)',
    'CREATE INDEX "ix_objectproperties_property" ON "t_objectproperties" ("Property" ASC)',
    'CREATE INDEX "ix_connectortag_elementid" ON "t_connectortag" ("ElementID" ASC)',
    'CREATE INDEX "ix_xref_client" ON "t_xref" ("Client" ASC)',
    'CREATE INDEX "ix_xref_type" ON "t_xref" ("Type" ASC)',
)

_INSERT_COLUMNS: dict[str, tuple[str, ...]] = {
    "t_package": (
        "Package_ID",
        "Name",
        "Parent_ID",
        "CreatedDate",
        "ModifiedDate",
        "Notes",
        "ea_guid",
        "TPos",
        "Version",
    ),
    "t_object": (
        "Object_ID",
        "Object_Type",
        "Name",
        "Alias",
        "Note",
        "Package_ID",
        "Stereotype",
        "NType",
        "PDATA1",
        "Status",
        "TPos",
        "Version",
        "CreatedDate",
        "ModifiedDate",
        "ea_guid",
    ),
    "t_connector": (
        "Connector_ID",
        "Name",
        "Direction",
        "Notes",
        "Connector_Type",
        "Stereotype",
        "Start_Object_ID",
        "End_Object_ID",
        "ea_guid",
    ),
    "t_objectproperties": ("PropertyID", "Object_ID", "Property", "Value", "Notes", "ea_guid"),
    "t_connectortag": ("PropertyID", "ElementID", "Property", "VALUE", "NOTES", "ea_guid"),
    "t_xref": ("XrefID", "Name", "Type", "Description", "Client"),
    "usys_system": ("Property", "Value"),
}


def project_guid(plan: ModelPlan) -> str:
    """Projektkennung des Modells: deterministisch aus dem Paketbaum.

    EA legt sie in ``usys_system`` ab (``Property='ProjectGUID'``); AAroN baut
    daraus den Projektknoten (``EA_Project``), von dem CONTAINS-Kanten zu den
    Wurzelpaketen ausgehen. Abgeleitet wird aus Technologieprofil und sortierten
    Paketpfaden -- gleicher Modellaufbau, gleiche Kennung; kein Zeitstempel,
    keine Zufalls-GUID.
    """
    seed = "project|" + plan.profile + "|" + "|".join(sorted(p.path for p in plan.packages))
    return _format_guid(seed)


def _system_rows(plan: ModelPlan) -> tuple[tuple[str, str], ...]:
    """Zeilen fuer ``usys_system``: Projektkennung und EA-Schemaversion."""
    return (
        ("ProjectGUID", project_guid(plan)),
        ("Version", SYSTEM_SCHEMA_VERSION),
    )


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _ddl_script() -> str:
    # Absicherung: keine AAroN-Pflichttabelle darf beim Umbau des Schemas
    # verloren gehen -- AAroN bricht sonst beim Import ab.
    missing = [table for table in AARON_READ_TABLES if table not in _TABLE_DDL]
    if missing:
        _fail(f"Schema unvollstaendig: AAroN liest {missing} bedingungslos")
    statements = [
        f"CREATE TABLE {_quote(table)} (\n    " + ",\n    ".join(columns) + "\n)"
        for table, columns in _TABLE_DDL.items()
    ]
    statements.extend(_INDEX_DDL)
    return ";\n".join(statements) + ";"


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------


def _object_rows(plan: ModelPlan, package_ids: Mapping[str, int]) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    rows.extend(
        (
            package.mirror_object_id,
            "Package",
            package.name,
            "",
            "",
            package_ids[package.parent_path] if package.parent_path else 0,
            "",
            0,
            str(package.package_id),
            "",
            package.mirror_tpos,
            FIXED_VERSION,
            FIXED_DATE,
            FIXED_DATE,
            package.guid,
        )
        for package in plan.packages
        if package.mirror_object_id is not None
    )
    rows.extend(
        (
            element.object_id,
            element.ea_type,
            element.name,
            element.alias,
            element.notes,
            package_ids[element.package_path],
            element.stereotype,
            0,
            None,
            element.status,
            element.tpos,
            FIXED_VERSION,
            FIXED_DATE,
            FIXED_DATE,
            element.guid,
        )
        for element in plan.elements
    )
    rows.sort(key=lambda row: row[0])
    return rows


def _package_rows(plan: ModelPlan, package_ids: Mapping[str, int]) -> list[tuple[Any, ...]]:
    return [
        (
            package.package_id,
            package.name,
            package_ids[package.parent_path] if package.parent_path else 0,
            FIXED_DATE,
            FIXED_DATE,
            package.notes,
            package.guid,
            package.tpos,
            FIXED_VERSION,
        )
        for package in plan.packages
    ]


def _connector_rows(plan: ModelPlan) -> list[tuple[Any, ...]]:
    return [
        (
            connector.connector_id,
            connector.name,
            connector.direction,
            connector.notes,
            connector.ea_type,
            connector.stereotype,
            connector.source_object_id,
            connector.target_object_id,
            connector.guid,
        )
        for connector in plan.connectors
    ]


def _insert(con: sqlite3.Connection, table: str, rows: Sequence[Sequence[Any]]) -> int:
    if not rows:
        return 0
    columns = _INSERT_COLUMNS[table]
    placeholders = ", ".join("?" for _ in columns)
    sql = (
        f"INSERT INTO {_quote(table)} ("
        + ", ".join(_quote(column) for column in columns)
        + f") VALUES ({placeholders})"
    )
    con.executemany(sql, rows)
    return len(rows)


def _write_file(plan: ModelPlan, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        con = sqlite3.connect(temp_path)
        try:
            # Feste Seiten-/Kodierparameter: keine Ableitung aus Build-Defaults.
            con.execute("PRAGMA page_size = 4096")
            con.execute("PRAGMA encoding = 'UTF-8'")
            con.execute("PRAGMA auto_vacuum = 0")
            con.executescript(_ddl_script())
            package_ids = {package.path: package.package_id for package in plan.packages}
            with con:
                _insert(con, "t_package", _package_rows(plan, package_ids))
                _insert(con, "t_object", _object_rows(plan, package_ids))
                _insert(con, "t_connector", _connector_rows(plan))
                _insert(
                    con,
                    "t_objectproperties",
                    [
                        (property_id, object_id, prop, value, "", guid)
                        for property_id, (object_id, prop, value, guid) in enumerate(
                            plan.object_tags, start=1
                        )
                    ],
                )
                _insert(
                    con,
                    "t_connectortag",
                    [
                        (property_id, element_id, prop, value, "", guid)
                        for property_id, (element_id, prop, value, guid) in enumerate(
                            plan.connector_tags, start=1
                        )
                    ],
                )
                _insert(
                    con,
                    "t_xref",
                    [
                        (xref_id, xref_name, xref_type, description, client)
                        for xref_id, xref_name, xref_type, description, client in plan.xrefs
                    ],
                )
                # Projektkennung + Schemaversion: AAroN baut daraus den
                # Projektknoten; EA legt beides an.
                _insert(con, "usys_system", _system_rows(plan))
            result = con.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                _fail(f"SQLite integrity_check fehlgeschlagen: {result!r}")
        finally:
            con.close()
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def write_qea(ir: "Mapping[str, Any] | str | os.PathLike[str]", target: str | os.PathLike[str]) -> Path:
    """Schreibt eine .qea aus einem IR-Dict oder einer IR-JSON-Datei.

    Rueckgabe: Pfad der geschriebenen Datei. Fehler: QeaWriterError.
    """
    if isinstance(ir, (str, os.PathLike)):
        ir = load_ir(ir)
    plan = plan_model(ir)
    path = Path(target)
    if path.suffix.lower() != ".qea":
        _fail(f"Ziel {str(path)!r} hat nicht die Endung .qea")
    _write_file(plan, path)
    return path


def render_bytes(ir: "Mapping[str, Any] | str | os.PathLike[str]") -> bytes:
    """Baut die Datei im Temp-Verzeichnis und liefert die Bytes (fuer Tests/Hashes)."""
    if isinstance(ir, (str, os.PathLike)):
        ir = load_ir(ir)
    with tempfile.TemporaryDirectory(prefix="qea-writer-") as workdir:
        path = Path(workdir) / "model.qea"
        _write_file(plan_model(ir), path)
        return path.read_bytes()


def load_ir(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Liest IR-JSON von Platte. Kaputtes JSON wird laut gemeldet."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        _fail(f"{path}: kein gueltiges JSON ({error})")
    return _mapping(data, str(path))  # type: ignore[return-value]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Selbsttest / CLI
# --------------------------------------------------------------------------


def _selftest() -> int:
    """Baut das mitgelieferte Mini-IR zweimal und vergleicht die Hashes."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "ir_synthetic_mini.json"
    if not fixture.exists():
        print(f"FEHLER: Fixture fehlt: {fixture}", file=sys.stderr)
        return 2
    ir = load_ir(fixture)
    first = render_bytes(ir)
    second = render_bytes(ir)
    if first != second:
        print(
            "FEHLER: zwei Builds sind nicht byte-identisch "
            f"({digest(first)} != {digest(second)})",
            file=sys.stderr,
        )
        return 1
    plan = plan_model(ir)
    print(
        f"OK: {digest(first)} | {len(first)} Bytes | "
        f"{len(plan.packages)} Pakete, {len(plan.elements)} Elemente, "
        f"{len(plan.connectors)} Kanten, "
        f"{len(plan.object_tags) + len(plan.connector_tags)} Tags, "
        f"{len(plan.xrefs)} t_xref-Eintraege"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministischer .qea-Writer: IR-JSON -> SQLite (.qea)."
    )
    parser.add_argument("ir", nargs="?", help="IR-JSON-Datei")
    parser.add_argument("out", nargs="?", help="Ziel .qea")
    parser.add_argument("--selftest", action="store_true", help="Mini-IR zweimal bauen und vergleichen")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.ir or not args.out:
        parser.error("ir und out sind Pflicht (oder --selftest)")
    try:
        ir = load_ir(args.ir)
        plan = plan_model(ir)
        path = write_qea(ir, args.out)
    except QeaWriterError as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 2
    print(
        f"{path}: {len(plan.packages)} Pakete, {len(plan.elements)} Elemente, "
        f"{len(plan.connectors)} Kanten, "
        f"{len(plan.object_tags) + len(plan.connector_tags)} Tags"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
