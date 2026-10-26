"""qea_reader.py -- liest eine .qea (EA-SQLite) und liefert IR-JSON.

Nur lesen: die Datei wird mit ``mode=ro`` geoeffnet, zusaetzlich
``PRAGMA query_only``. Kein Netzwerk, keine Zeitstempel, keine Zufallswerte.
Der Reader ist die Umkehrung von ``qea_writer.py``; ``IR_SPEC.md`` ist der
Vertrag zwischen beiden.

Kernentscheidungen (alle deterministisch):

- Paketspiegel (``t_object.Object_Type = 'Package'``) sind **keine** Elemente.
  Ihre Tagged Values gehoeren zum Paket. Waisen-Spiegel ohne ``t_package``-Zeile
  werden uebersprungen und im Report gemeldet (echte Modelle enthalten sie).
- Der logische Pfad wird aus den Anzeigenamen rekonstruiert. Gleichnamige
  Geschwister bekommen ``#2``, ``#3`` ... in der Reihenfolge ``(TPos,
  Package_ID)`` -- dieselbe Konvention, die der Writer beim Schreiben von
  ``TPos`` anwendet.
- Kantenendpunkte werden als ``<paketpfad>::<name>`` geschrieben, bei
  Namensgruppen > 1 mit ``#N``; unbenannte Elemente immer als
  ``<paketpfad>::#N``. Die Nummer ist die Position in der kanonischen
  Inhaltsreihenfolge ``(ea_type, notes, alias, status, tags)`` -- exakt die
  Sortierung aus ``qea_writer._element_index``.
- Kanten an Paketspiegeln werden als blanker Paketpfad geschrieben.
- Fehlende *optionale* Spalten werden durch Defaults ersetzt (Robustheit).
  Fehlende Pflichtspalten/-tabellen, haengende Verweise, nicht darstellbare
  Namen und widerspruechliche Tags brechen laut ab (``QeaReaderError``) --
  es gibt keinen stillen Teil-Erfolg.

Oeffentliche API::

    from qea_reader import read_qea, read_qea_ex, ReadReport, QeaReaderError

    ir = read_qea("modell.qea")                  # dict, writer-kompatibel
    ir, report = read_qea_ex("modell.qea")       # dict + Statistiken/Warnungen
"""

from __future__ import annotations

import argparse
import json
import hashlib
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

IR_VERSION = 1

DEFAULT_OBJECT_TYPE = "Class"
DEFAULT_CONNECTOR_TYPE = "Dependency"
DEFAULT_DIRECTION = "Source -> Destination"


class QeaReaderError(ValueError):
    """Lauter Fehler: unlesbare Datei, inkonsistentes Modell, Verlustgefahr."""


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadReport:
    """Was der Reader tatsaechlich gesehen hat -- nie leerer Erfolg ohne Zahlen."""

    packages: int = 0
    elements: int = 0
    connectors: int = 0
    element_tags: int = 0
    package_tags: int = 0
    connector_tags: int = 0
    diagrams: int = 0
    ignored_package_mirrors: int = 0
    technology_profile: str = ""
    profiles_seen: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "packages": self.packages,
            "elements": self.elements,
            "connectors": self.connectors,
            "element_tags": self.element_tags,
            "package_tags": self.package_tags,
            "connector_tags": self.connector_tags,
            "diagrams": self.diagrams,
            "ignored_package_mirrors": self.ignored_package_mirrors,
            "technology_profile": self.technology_profile,
            "profiles_seen": list(self.profiles_seen),
            "warnings": list(self.warnings),
        }

    def summary(self) -> str:
        text = (
            f"{self.packages} Pakete, {self.elements} Elemente, "
            f"{self.connectors} Kanten, {self.element_tags + self.package_tags} Objekt-Tags, "
            f"{self.connector_tags} Kanten-Tags"
        )
        if self.diagrams:
            text += f" | {self.diagrams} Sichten bewusst nicht uebernommen"
        if self.ignored_package_mirrors:
            text += f" | {self.ignored_package_mirrors} Waisen-Paketspiegel ignoriert"
        return text


# --------------------------------------------------------------------------
# Interne Datensichten
# --------------------------------------------------------------------------


@dataclass
class _Package:
    package_id: int
    name: str
    parent_id: int
    notes: str
    guid: str
    tpos: int
    path: str = ""


@dataclass
class _Element:
    object_id: int
    package_path: str
    name: str
    stereotype: str
    ea_type: str
    notes: str
    alias: str
    status: str
    tags: dict[str, str]
    origin: str = ""
    guid: str = ""
    ref: str = ""

    def content_key(self) -> tuple[Any, ...]:
        """Exakt die Sortierung aus qea_writer._element_index (ohne Paket/Name)."""
        return (
            self.ea_type,
            self.notes,
            self.alias,
            self.status,
            tuple(sorted(self.tags.items())),
            self.origin,
        )

    def order_key(self) -> tuple[Any, ...]:
        """Kanonische IR-Reihenfolge: Inhalt zuerst, Object_ID nur als Tiebreak."""
        return (
            self.package_path,
            self.name,
            self.ea_type,
            self.stereotype,
            self.notes,
            self.alias,
            self.status,
            tuple(sorted(self.tags.items())),
            self.object_id,
        )


# --------------------------------------------------------------------------
# SQLite-Hilfen (tolerant gegen fehlende Spalten, streng bei Struktur)
# --------------------------------------------------------------------------


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _kanonische_guid(package: str, stereotype: str, name: str) -> str:
    """Dieselbe Ableitung wie ``qea_writer.guid_for`` -- ohne Importzyklus."""
    digest = hashlib.sha256(f"{package}|{stereotype}|{name}".encode("utf-8")).hexdigest()[:32].upper()
    return (
        "{" + digest[0:8] + "-" + digest[8:12] + "-" + digest[12:16] + "-"
        + digest[16:20] + "-" + digest[20:32] + "}"
    )


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise QeaReaderError(f"{path}: Datei existiert nicht")
    if not path.is_file():
        raise QeaReaderError(f"{path}: keine regulaere Datei")
    uri = "file:" + quote(path.resolve().as_posix(), safe="/") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as error:  # pragma: no cover - defensive
        raise QeaReaderError(f"{path}: keine lesbare SQLite-Datenbank ({error})") from error
    return con


def _table_names(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    return {row[0].lower(): row[0] for row in rows}


def _require_table(tables: Mapping[str, str], name: str) -> str:
    found = tables.get(name.lower())
    if found is None:
        raise QeaReaderError(
            f"Tabelle {name!r} fehlt -- das ist keine vollstaendige .qea "
            f"(vorhanden: {', '.join(sorted(tables.values())) or 'keine'})"
        )
    return found


def _columns(con: sqlite3.Connection, table: str) -> dict[str, str]:
    return {row[1].lower(): row[1] for row in con.execute(f"PRAGMA table_info({_quote_identifier(table)})")}


def _column(columns: Mapping[str, str], *names: str) -> str | None:
    """Erste vorhandene Spalte (Alias-Reihenfolge), sonst None."""
    for name in names:
        if name.lower() in columns:
            return columns[name.lower()]
    return None


def _require_column(columns: Mapping[str, str], table: str, *names: str) -> str:
    found = _column(columns, *names)
    if found is None:
        raise QeaReaderError(
            f"{table}: Pflichtspalte {names[0]!r} fehlt "
            f"(vorhanden: {', '.join(sorted(columns.values())) or 'keine'})"
        )
    return found


def _raw(row: sqlite3.Row, columns: Mapping[str, str], *names: str) -> Any:
    column = _column(columns, *names)
    if column is None:
        return None
    return row[column]


def _text(value: Any, what: str, *, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    raise QeaReaderError(f"{what}: Text erwartet, gefunden {type(value).__name__}")


def _int(value: Any, what: str, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise QeaReaderError(f"{what}: ganze Zahl erwartet, gefunden bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    raise QeaReaderError(f"{what}: ganze Zahl erwartet, gefunden {value!r}")


# --------------------------------------------------------------------------
# Pakete
# --------------------------------------------------------------------------


def _read_packages(
    con: sqlite3.Connection, tables: Mapping[str, str], warnings: list[str]
) -> dict[int, _Package]:
    table = _require_table(tables, "t_package")
    columns = _columns(con, table)
    id_column = _require_column(columns, table, "Package_ID")
    name_column = _require_column(columns, table, "Name")
    has_parent = _column(columns, "Parent_ID") is not None
    if not has_parent:
        warnings.append(
            "t_package.Parent_ID fehlt -- alle Pakete werden als Wurzelpakete gelesen "
            "(Hierarchie geht verloren)"
        )

    packages: dict[int, _Package] = {}
    for index, row in enumerate(con.execute(f'SELECT * FROM {_quote_identifier(table)}')):
        what = f"t_package Zeile {index + 1}"
        package_id = _int(row[id_column], f"{what}.Package_ID")
        if package_id is None:
            raise QeaReaderError(f"{what}: Package_ID ist leer")
        if package_id in packages:
            raise QeaReaderError(f"{what}: Package_ID {package_id} ist doppelt")
        name = _text(row[name_column], f"{what}.Name")
        if not name.strip():
            raise QeaReaderError(f"{what}: Paket {package_id} hat keinen Namen")
        parent_raw = _raw(row, columns, "Parent_ID")
        if parent_raw is None:
            parent_id = 0
        else:
            parent_id = _int(parent_raw, f"{what}.Parent_ID", default=0) or 0
        packages[package_id] = _Package(
            package_id=package_id,
            name=name,
            parent_id=parent_id,
            notes=_text(_raw(row, columns, "Notes"), f"{what}.Notes"),
            guid=_text(_raw(row, columns, "ea_guid"), f"{what}.ea_guid"),
            tpos=_int(_raw(row, columns, "TPos"), f"{what}.TPos", default=0) or 0,
        )

    if not packages:
        raise QeaReaderError("t_package ist leer -- eine .qea ohne Paket ist kein Modell")

    for package in packages.values():
        if package.parent_id and package.parent_id not in packages:
            raise QeaReaderError(
                f"Paket {package.package_id} ({package.name!r}): Parent_ID "
                f"{package.parent_id} existiert nicht"
            )

    guid_owners: dict[str, list[int]] = {}
    for package in packages.values():
        if package.guid:
            guid_owners.setdefault(package.guid.upper(), []).append(package.package_id)
    ambiguous = sorted(
        (guid, ids) for guid, ids in guid_owners.items() if len(ids) > 1
    )
    if ambiguous:
        warnings.append(
            "mehrdeutige Paket-GUIDs in t_package ("
            + ", ".join(f"{guid}: {ids}" for guid, ids in ambiguous[:3])
            + ") -- Spiegel-Zuordnung nutzt PDATA1 zuerst"
        )

    _assign_package_paths(packages)
    return packages


def _package_segment(name: str, used: set[str], package: _Package) -> str:
    for forbidden in ("/", "\\", "::"):
        if forbidden in name:
            raise QeaReaderError(
                f"Paket {package.package_id} ({name!r}): {forbidden!r} ist im "
                "Paketnamen nicht darstellbar (IR nutzt '/' als Pfadtrenner, "
                "'::' fuer Element-Referenzen)"
            )
    if name in (".", ".."):
        raise QeaReaderError(f"Paket {package.package_id}: ungueltiger Name {name!r}")
    segment = name
    number = 1
    while segment in used:
        number += 1
        segment = f"{name}#{number}"
    used.add(segment)
    return segment


def _assign_package_paths(packages: dict[int, _Package]) -> None:
    children: dict[int, list[_Package]] = {}
    for package in packages.values():
        children.setdefault(package.parent_id, []).append(package)

    paths: dict[int, str] = {}

    def walk(parent_id: int, prefix: str, depth: int) -> None:
        if depth > len(packages) + 1:
            raise QeaReaderError("Pakethierarchie enthaelt einen Zyklus")
        siblings = sorted(children.get(parent_id, []), key=lambda p: (p.tpos, p.package_id))
        used: set[str] = set()
        for package in siblings:
            segment = _package_segment(package.name, used, package)
            package.path = f"{prefix}/{segment}" if prefix else segment
            if package.package_id in paths:  # pragma: no cover - defensive
                raise QeaReaderError(f"Paket {package.package_id} ist mehrfach erreichbar")
            paths[package.package_id] = package.path
            walk(package.package_id, package.path, depth + 1)

    walk(0, "", 0)
    unreachable = sorted(set(packages) - set(paths))
    if unreachable:
        raise QeaReaderError(
            "Pakethierarchie ist nicht vollstaendig erreichbar (Zyklus oder "
            f"unbekannter Parent_ID): {unreachable[:10]}"
        )


# --------------------------------------------------------------------------
# Objekte, Paketspiegel, Tags
# --------------------------------------------------------------------------


@dataclass
class _ObjectRow:
    object_id: int
    name: str
    object_type: str
    stereotype: str
    notes: str
    alias: str
    status: str
    package_id: int
    pdata1: str
    guid: str


def _read_objects(
    con: sqlite3.Connection, tables: Mapping[str, str]
) -> list[_ObjectRow]:
    table = _require_table(tables, "t_object")
    columns = _columns(con, table)
    id_column = _require_column(columns, table, "Object_ID")
    name_column = _require_column(columns, table, "Name")
    type_column = _require_column(columns, table, "Object_Type")
    package_column = _require_column(columns, table, "Package_ID")

    objects: list[_ObjectRow] = []
    seen: set[int] = set()
    for index, row in enumerate(con.execute(f'SELECT * FROM {_quote_identifier(table)}')):
        what = f"t_object Zeile {index + 1}"
        object_id = _int(row[id_column], f"{what}.Object_ID")
        if object_id is None:
            raise QeaReaderError(f"{what}: Object_ID ist leer")
        if object_id in seen:
            raise QeaReaderError(f"{what}: Object_ID {object_id} ist doppelt")
        seen.add(object_id)
        package_id = _int(row[package_column], f"{what}.Package_ID", default=0) or 0
        objects.append(
            _ObjectRow(
                object_id=object_id,
                name=_text(row[name_column], f"{what}.Name"),
                object_type=_text(row[type_column], f"{what}.Object_Type"),
                stereotype=_text(_raw(row, columns, "Stereotype"), f"{what}.Stereotype"),
                notes=_text(_raw(row, columns, "Note", "Notes"), f"{what}.Note"),
                alias=_text(_raw(row, columns, "Alias"), f"{what}.Alias"),
                status=_text(_raw(row, columns, "Status"), f"{what}.Status"),
                package_id=package_id,
                pdata1=_text(_raw(row, columns, "PDATA1"), f"{what}.PDATA1"),
                guid=_text(_raw(row, columns, "ea_guid"), f"{what}.ea_guid"),
            )
        )
    return objects


@dataclass
class _Mirrors:
    """Paketspiegel: Object_ID -> Package_ID; nicht zuordenbare bleiben als Waisen."""

    by_object: dict[int, int] = field(default_factory=dict)
    orphans: list[_ObjectRow] = field(default_factory=list)
    root_mirrors: list[_ObjectRow] = field(default_factory=list)


def _match_mirror(
    obj: _ObjectRow, packages: Mapping[int, _Package], by_guid: Mapping[str, int]
) -> int | None:
    pdata = obj.pdata1.strip()
    if pdata:
        try:
            candidate = int(pdata)
        except ValueError:
            candidate = None
        if candidate in packages:
            return candidate
    if obj.guid:
        return by_guid.get(obj.guid.upper())
    return None


def _classify_mirrors(
    objects: Iterable[_ObjectRow], packages: Mapping[int, _Package], warnings: list[str]
) -> _Mirrors:
    mirrors = _Mirrors()
    by_guid: dict[str, int] = {}
    for package in packages.values():
        if package.guid:
            by_guid.setdefault(package.guid.upper(), package.package_id)
    owners: dict[int, int] = {}
    for obj in objects:
        if obj.object_type.strip().lower() != "package":
            continue
        target = _match_mirror(obj, packages, by_guid)
        if target is None:
            mirrors.orphans.append(obj)
            continue
        package = packages[target]
        if not package.parent_id:
            mirrors.root_mirrors.append(obj)
            continue
        if target in owners:
            raise QeaReaderError(
                f"Paket {target} ({package.name!r}) hat zwei Spiegel "
                f"(Object_IDs {owners[target]} und {obj.object_id})"
            )
        owners[target] = obj.object_id
        mirrors.by_object[obj.object_id] = target
    if mirrors.orphans:
        warnings.append(
            f"{len(mirrors.orphans)} Paketspiegel ohne passende t_package-Zeile "
            "ignoriert (z. B. Object_ID "
            + ", ".join(str(o.object_id) for o in mirrors.orphans[:3])
            + ")"
        )
    if mirrors.root_mirrors:
        warnings.append(
            f"{len(mirrors.root_mirrors)} Spiegel von Wurzelpaketen ignoriert "
            "(EA-Konvention: Wurzeln haben keinen Spiegel)"
        )
    return mirrors


def _read_tags(
    con: sqlite3.Connection,
    tables: Mapping[str, str],
    table_name: str,
    owner_columns: Sequence[str],
    owner_label: str,
    warnings: list[str],
) -> dict[int, dict[str, str]]:
    """Tagged Values je Owner. Doppelte, inhaltlich gleiche Zeilen kollabieren."""
    table = tables.get(table_name.lower())
    if table is None:
        warnings.append(f"{table_name} fehlt -- {owner_label} ohne Tagged Values gelesen")
        return {}
    columns = _columns(con, table)
    owner_column = _column(columns, *owner_columns)
    if owner_column is None:
        raise QeaReaderError(
            f"{table}: Spalte {owner_columns[0]!r} fehlt -- Tags sind keinem "
            f"{owner_label} zuordenbar"
        )
    property_column = _require_column(columns, table, "Property")
    value_column = _column(columns, "Value", "VALUE")
    order_column = _column(columns, "PropertyID", "Property_ID")

    tags: dict[int, dict[str, str]] = {}
    total = 0
    sql = f'SELECT * FROM {_quote_identifier(table)}'
    if order_column is not None:
        sql += f' ORDER BY {_quote_identifier(order_column)}'
    for row in con.execute(sql):
        total += 1
        what = f"{table} Zeile {total}"
        owner = _int(row[owner_column], f"{what}.{owner_column}", default=0) or 0
        prop = _text(row[property_column], f"{what}.Property")
        if not prop.strip():
            raise QeaReaderError(f"{what}: Tag ohne Property-Namen (Owner {owner})")
        value = "" if value_column is None else _text(row[value_column], f"{what}.Value")
        bucket = tags.setdefault(owner, {})
        if prop in bucket and bucket[prop] != value:
            raise QeaReaderError(
                f"{what}: Tag {prop!r} an Owner {owner} hat widerspruechliche Werte "
                f"({bucket[prop]!r} vs. {value!r}) -- IR-Tags sind eindeutig"
            )
        bucket[prop] = value
    return tags


# --------------------------------------------------------------------------
# Stereotype aus t_xref (Pakete haben keine Stereotype-Spalte)
# --------------------------------------------------------------------------

_STEREO_PREFIX = "@STEREO;"
_STEREO_SUFFIX = "@ENDSTEREO;"


def _parse_stereotype(description: str) -> tuple[str, str] | None:
    text = description.strip()
    if not text.startswith(_STEREO_PREFIX) or not text.endswith(_STEREO_SUFFIX):
        return None
    body = text[len(_STEREO_PREFIX) : -len(_STEREO_SUFFIX)]
    name = ""
    fqname = ""
    for part in body.split(";"):
        if part.startswith("Name="):
            name = part[len("Name=") :]
        elif part.startswith("FQName="):
            fqname = part[len("FQName=") :]
    if not name:
        return None
    return name, fqname


def _read_stereotypes(
    con: sqlite3.Connection,
    tables: Mapping[str, str],
    warnings: list[str],
    package_guids: set[str],
) -> tuple[dict[str, str], str, tuple[str, ...]]:
    """Liefert (Paket-GUID -> Paketstereotyp, dominantes Profil, alle Profile)."""
    table = tables.get("t_xref")
    if table is None:
        warnings.append("t_xref fehlt -- Paketstereotype und Technologieprofil unbekannt")
        return {}, "", ()
    columns = _columns(con, table)
    type_column = _column(columns, "Type")
    description_column = _column(columns, "Description")
    client_column = _column(columns, "Client")
    if type_column is None or description_column is None or client_column is None:
        warnings.append("t_xref ohne Type/Description/Client -- Stereotype nicht lesbar")
        return {}, "", ()

    by_guid: dict[str, str] = {}
    conflicts: dict[str, str] = {}
    profile_counts: dict[str, int] = {}
    for row in con.execute(f'SELECT * FROM {_quote_identifier(table)}'):
        if _text(row[type_column], "t_xref.Type").strip().lower() != "element property":
            continue
        parsed = _parse_stereotype(_text(row[description_column], "t_xref.Description"))
        if parsed is None:
            continue
        stereotype, fqname = parsed
        if "::" in fqname:
            profile = fqname.rsplit("::", 1)[0].strip()
            if profile:
                profile_counts[profile] = profile_counts.get(profile, 0) + 1
        client = _text(row[client_column], "t_xref.Client").strip().upper()
        # Element-/Kantenguids brauchen wir nicht: deren Stereotyp steht in
        # t_object.Stereotype bzw. t_connector.Stereotype. Nur Pakete haben
        # keine eigene Spalte und sind auf t_xref angewiesen.
        if not client or client not in package_guids:
            continue
        existing = by_guid.get(client)
        if existing is None:
            by_guid[client] = stereotype
        elif existing != stereotype:
            conflicts[client] = f"{existing!r} / {stereotype!r}"

    if conflicts:
        sample = ", ".join(f"{guid}: {value}" for guid, value in sorted(conflicts.items())[:3])
        raise QeaReaderError(
            "t_xref enthaelt widerspruechliche Stereotype fuer dieselbe GUID: " + sample
        )

    profiles = tuple(sorted(profile_counts))
    profile = ""
    if profiles:
        profile = sorted(profile_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if len(profiles) > 1:
            warnings.append(
                "mehrere Technologieprofile in t_xref ("
                + ", ".join(profiles)
                + f") -- IR nutzt das haeufigste: {profile}"
            )
    return by_guid, profile, profiles


# --------------------------------------------------------------------------
# Elemente
# --------------------------------------------------------------------------


def _build_elements(
    objects: Iterable[_ObjectRow],
    packages: Mapping[int, _Package],
    object_tags: Mapping[int, dict[str, str]],
) -> tuple[list[_Element], int]:
    elements: list[_Element] = []
    tag_count = 0
    for obj in objects:
        if obj.object_type.strip().lower() == "package":
            continue
        package = packages.get(obj.package_id)
        if package is None:
            raise QeaReaderError(
                f"Element Object_ID {obj.object_id} ({obj.name!r}): Package_ID "
                f"{obj.package_id} existiert nicht"
            )
        if "::" in obj.name:
            raise QeaReaderError(
                f"Element Object_ID {obj.object_id}: Name {obj.name!r} enthaelt '::' "
                "-- im IR als Element-Referenz nicht darstellbar"
            )
        ea_type = obj.object_type.strip() or DEFAULT_OBJECT_TYPE
        tags = dict(object_tags.get(obj.object_id, {}))
        tag_count += len(tags)
        # Herkunft aus dem Katalog (Tag ``Herkunft``) wird zur IR-Spalte
        # ``origin``: daraus leitet der Writer die GUID ab, unabhaengig vom Ort
        # des Elements im Modell. Der Tag selbst bleibt erhalten.
        herkunft = str(tags.get("Herkunft", "") or "").strip()
        origin = herkunft[len("katalog:"):] if herkunft.startswith("katalog:") else ""
        elements.append(
            _Element(
                object_id=obj.object_id,
                package_path=package.path,
                name=obj.name,
                stereotype=obj.stereotype,
                ea_type=ea_type,
                notes=obj.notes,
                alias=obj.alias,
                status=obj.status,
                tags=tags,
                origin=origin,
                guid=obj.guid,
            )
        )
    _assign_element_refs(elements)
    return elements, tag_count


def _assign_element_refs(elements: Sequence[_Element]) -> None:
    """Nummerierung exakt wie qea_writer._element_index (stabile Sortierung)."""
    ordered = sorted(elements, key=lambda e: e.order_key())
    groups: dict[tuple[str, str], list[_Element]] = {}
    for element in ordered:
        groups.setdefault((element.package_path, element.name), []).append(element)

    # Der IR-Referenzraum hat keine Escape-Syntax: 'paket::name#N' wird vom
    # Writer zuerst als *literaler* Elementname gesucht. Existiert ein solcher
    # Name, wuerde die Vorkommensnummer falsch aufgeloest -- das ist Verlust,
    # also laut abbrechen.
    names_by_package: dict[str, set[str]] = {}
    for element in ordered:
        names_by_package.setdefault(element.package_path, set()).add(element.name)

    for (package_path, name), group in groups.items():
        group.sort(key=lambda e: e.content_key())
        literal = names_by_package.get(package_path, set())
        for position, element in enumerate(group, start=1):
            if not name:
                element.ref = f"{package_path}::#{position}"
                shadow = f"#{position}"
            elif len(group) == 1:
                element.ref = f"{package_path}::{name}"
                continue
            else:
                element.ref = f"{package_path}::{name}#{position}"
                shadow = f"{name}#{position}"
            if shadow in literal:
                raise QeaReaderError(
                    f"Paket {package_path!r}: Elementname {shadow!r} kollidiert mit "
                    f"der Vorkommensnummer von {name!r} -- im IR nicht eindeutig "
                    "adressierbar (Element umbenennen)"
                )


# --------------------------------------------------------------------------
# Kanten
# --------------------------------------------------------------------------


def _read_connectors(
    con: sqlite3.Connection,
    tables: Mapping[str, str],
    elements: Sequence[_Element],
    packages: Mapping[int, _Package],
    mirrors: _Mirrors,
    connector_tags: Mapping[int, dict[str, str]],
) -> tuple[list[dict[str, Any]], int]:
    table = _require_table(tables, "t_connector")
    columns = _columns(con, table)
    id_column = _require_column(columns, table, "Connector_ID")
    start_column = _require_column(columns, table, "Start_Object_ID")
    end_column = _require_column(columns, table, "End_Object_ID")

    refs = {element.object_id: element.ref for element in elements}
    for object_id, package_id in mirrors.by_object.items():
        refs[object_id] = packages[package_id].path
    blocked = {obj.object_id for obj in mirrors.orphans} | {
        obj.object_id for obj in mirrors.root_mirrors
    }

    connectors: list[dict[str, Any]] = []
    tag_count = 0
    rows = list(con.execute(f'SELECT * FROM {_quote_identifier(table)}'))
    known_connector_ids = {
        _int(row[id_column], "t_connector.Connector_ID", default=0) for row in rows
    }
    dangling = sorted(set(connector_tags) - known_connector_ids)
    if dangling:
        raise QeaReaderError(
            "t_connectortag verweist auf unbekannte Connector_IDs: "
            + ", ".join(str(value) for value in dangling[:10])
        )
    for index, row in enumerate(rows):
        what = f"t_connector Zeile {index + 1}"
        connector_id = _int(row[id_column], f"{what}.Connector_ID")
        if connector_id is None:
            raise QeaReaderError(f"{what}: Connector_ID ist leer")
        endpoints: list[str] = []
        for column, side in ((start_column, "Start_Object_ID"), (end_column, "End_Object_ID")):
            object_id = _int(row[column], f"{what}.{side}")
            if object_id is None:
                raise QeaReaderError(f"{what}: {side} ist leer")
            if object_id in blocked:
                raise QeaReaderError(
                    f"{what}: {side} {object_id} zeigt auf einen Paketspiegel, "
                    "der im IR nicht darstellbar ist (Waisen-/Wurzelspiegel)"
                )
            if object_id not in refs:
                raise QeaReaderError(
                    f"{what}: {side} {object_id} zeigt auf kein Element und keinen "
                    "Paketspiegel -- haengender Verweis"
                )
            endpoints.append(refs[object_id])

        ea_type = _text(_raw(row, columns, "Connector_Type"), f"{what}.Connector_Type").strip()
        direction = _text(_raw(row, columns, "Direction"), f"{what}.Direction")
        tags = connector_tags.get(connector_id)
        if tags:
            tag_count += len(tags)
        connector: dict[str, Any] = {
            "source": endpoints[0],
            "target": endpoints[1],
        }
        stereotype = _text(_raw(row, columns, "Stereotype"), f"{what}.Stereotype")
        if stereotype:
            connector["stereotype"] = stereotype
        connector["ea_type"] = ea_type or DEFAULT_CONNECTOR_TYPE
        name = _text(_raw(row, columns, "Name"), f"{what}.Name")
        if name:
            connector["name"] = name
        if direction and direction != DEFAULT_DIRECTION:
            connector["direction"] = direction
        notes = _text(_raw(row, columns, "Notes"), f"{what}.Notes")
        if notes:
            connector["notes"] = notes
        if tags:
            connector["tags"] = dict(sorted(tags.items()))
        connectors.append(connector)

    connectors.sort(
        key=lambda c: (
            c["source"],
            c["target"],
            c.get("stereotype", ""),
            c.get("name", ""),
            c["ea_type"],
            c.get("direction", ""),
            c.get("notes", ""),
            tuple(sorted(c.get("tags", {}).items())),
        )
    )
    return connectors, tag_count


# --------------------------------------------------------------------------
# Oeffentliche API
# --------------------------------------------------------------------------


def read_qea_ex(
    path: str | Path, *, strict: bool = False, allow_empty: bool = False
) -> tuple[dict[str, Any], ReadReport]:
    """Liest eine .qea und liefert (IR-Dict, ReadReport).

    ``strict=True`` macht jede Warnung zum Fehler (kein stiller Verlust).
    ``allow_empty=True`` erlaubt Modelle ohne Elemente (Writer lehnt sie ab).
    """
    source = Path(path)
    con = _open_readonly(source)
    try:
        tables = _table_names(con)
        warnings: list[str] = []
        packages = _read_packages(con, tables, warnings)
        objects = _read_objects(con, tables)
        mirrors = _classify_mirrors(objects, packages, warnings)

        object_tags = _read_tags(
            con, tables, "t_objectproperties", ("Object_ID",), "Objekt", warnings
        )
        connector_tags = _read_tags(
            con,
            tables,
            "t_connectortag",
            ("ElementID", "Connector_ID", "ConnectorID"),
            "Kante",
            warnings,
        )
        stereotypes, profile, profiles_seen = _read_stereotypes(
            con,
            tables,
            warnings,
            {p.guid.upper() for p in packages.values() if p.guid},
        )

        known_object_ids = {obj.object_id for obj in objects}
        dangling_tag_owners = sorted(set(object_tags) - known_object_ids)
        if dangling_tag_owners:
            raise QeaReaderError(
                "t_objectproperties verweist auf unbekannte Object_IDs: "
                + ", ".join(str(value) for value in dangling_tag_owners[:10])
            )

        elements, element_tag_count = _build_elements(objects, packages, object_tags)
        if not elements and not allow_empty:
            raise QeaReaderError(
                "das Modell enthaelt kein Element -- Abbruch statt leerem IR "
                "(allow_empty=True nur fuer bewusst leere Modelle)"
            )

        package_stereotypes: dict[int, str] = {}
        for package in packages.values():
            if package.guid and package.guid.upper() in stereotypes:
                package_stereotypes[package.package_id] = stereotypes[package.guid.upper()]

        package_tags: dict[int, dict[str, str]] = {}
        for object_id, package_id in mirrors.by_object.items():
            package_tags[package_id] = dict(object_tags.get(object_id, {}))
        for obj in mirrors.orphans + mirrors.root_mirrors:
            if object_tags.get(obj.object_id):
                raise QeaReaderError(
                    f"Paketspiegel Object_ID {obj.object_id} ({obj.name!r}) traegt "
                    "Tagged Values, ist aber keinem darstellbaren Paket zugeordnet"
                )
        # Tags ohne Owner (Wurzelpaket ohne Spiegel) sind nicht darstellbar.
        accounted = {element.object_id for element in elements} | set(mirrors.by_object) | {
            obj.object_id for obj in mirrors.orphans + mirrors.root_mirrors
        }
        lost = sorted(set(object_tags) - accounted)
        if lost:
            raise QeaReaderError(
                "Tagged Values ohne darstellbaren Owner (Object_IDs): "
                + ", ".join(str(value) for value in lost[:10])
            )

        connectors, connector_tag_count = _read_connectors(
            con, tables, elements, packages, mirrors, connector_tags
        )

        package_items: list[dict[str, Any]] = []
        for package in sorted(packages.values(), key=lambda p: p.path):
            segment = package.path.rsplit("/", 1)[-1]
            item: dict[str, Any] = {"path": package.path}
            if package.name != segment:
                item["name"] = package.name
            stereotype = package_stereotypes.get(package.package_id, "")
            if stereotype:
                item["stereotype"] = stereotype
            if package.notes:
                item["notes"] = package.notes
            tags = package_tags.get(package.package_id)
            if tags:
                item["tags"] = dict(sorted(tags.items()))
            package_items.append(item)

        element_items: list[dict[str, Any]] = []
        for element in sorted(elements, key=lambda e: e.order_key()):
            item = {"package": element.package_path, "name": element.name}
            if element.stereotype:
                item["stereotype"] = element.stereotype
            item["ea_type"] = element.ea_type
            if element.notes:
                item["notes"] = element.notes
            if element.alias:
                item["alias"] = element.alias
            if element.status:
                item["status"] = element.status
            if element.tags:
                item["tags"] = dict(sorted(element.tags.items()))
            if element.origin:
                item["origin"] = element.origin
            # Weicht die Kennung von der Ableitung ab, ist sie gefuehrt (etwa aus
            # dem Katalog) und muss woertlich zurueckgeschrieben werden.
            # Katalogelemente (mit Herkunft) und fremde Kennungen werden
            # woertlich zurueckgegeben -- ihre Identitaet darf sich nicht aus
            # dem Ort im Modell ergeben.
            if element.guid and (
                element.origin
                or element.guid.upper()
                != _kanonische_guid(element.package_path, element.stereotype, element.name)
            ):
                item["guid"] = element.guid.upper()
            element_items.append(item)

        ir: dict[str, Any] = {"ir_version": IR_VERSION}
        if profile:
            ir["technology"] = {"profile": profile}
        ir["packages"] = package_items
        ir["elements"] = element_items
        ir["connectors"] = connectors
        ir["diagrams"] = []

        diagram_table = tables.get("t_diagram")
        diagram_count = 0
        if diagram_table is not None:
            diagram_count = con.execute(
                f'SELECT count(*) FROM {_quote_identifier(diagram_table)}'
            ).fetchone()[0]

        report = ReadReport(
            packages=len(package_items),
            elements=len(element_items),
            connectors=len(connectors),
            element_tags=element_tag_count,
            package_tags=sum(len(tags) for tags in package_tags.values()),
            connector_tags=connector_tag_count,
            diagrams=diagram_count,
            ignored_package_mirrors=len(mirrors.orphans) + len(mirrors.root_mirrors),
            technology_profile=profile,
            profiles_seen=profiles_seen,
            warnings=tuple(warnings),
        )
    except sqlite3.DatabaseError as error:
        raise QeaReaderError(f"{source}: SQLite-Fehler beim Lesen ({error})") from error
    finally:
        con.close()

    if strict and report.warnings:
        raise QeaReaderError("strikter Modus: " + " | ".join(report.warnings) + f" ({source})")
    return ir, report


def read_qea(path: str | Path, *, strict: bool = False, allow_empty: bool = False) -> dict[str, Any]:
    """Liest eine .qea und liefert nur das IR-Dict."""
    ir, _ = read_qea_ex(path, strict=strict, allow_empty=allow_empty)
    return ir


def render_json(ir: Mapping[str, Any]) -> str:
    """Kanonische JSON-Darstellung (sortierte Schluessel, UTF-8, 2 Leerzeichen)."""
    return json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_ir(ir: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.write_text(render_json(ir), encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# Semantische Sicht (fuer Round-Trip-Vergleiche)
# --------------------------------------------------------------------------


def _element_token(element: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        element.get("package", ""),
        element.get("name", ""),
        element.get("stereotype", ""),
        element.get("ea_type", DEFAULT_OBJECT_TYPE),
        element.get("notes", ""),
        element.get("alias", ""),
        element.get("status", ""),
        tuple(sorted(element.get("tags", {}).items())),
    )


def _semantic_groups(ir: Mapping[str, Any]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for element in ir.get("elements", []):
        groups.setdefault((element.get("package", ""), element.get("name", "")), []).append(
            element
        )
    for group in groups.values():
        group.sort(
            key=lambda e: (
                e.get("ea_type", DEFAULT_OBJECT_TYPE),
                e.get("notes", ""),
                e.get("alias", ""),
                e.get("status", ""),
                tuple(sorted(e.get("tags", {}).items())),
            )
        )
    return groups


def _semantic_ref(
    ref: str, groups: Mapping[tuple[str, str], list[Mapping[str, Any]]]
) -> tuple[str, Any]:
    if "::" not in ref:
        return ("package", ref)
    package_path, rest = ref.rsplit("::", 1)
    occurrence: int | None = None
    group = groups.get((package_path, rest))
    if group is None:
        name, separator, number = rest.rpartition("#")
        if separator and number.isdigit():
            group = groups.get((package_path, name))
            occurrence = int(number)
    if group is None:
        raise QeaReaderError(f"semantische Sicht: Referenz {ref!r} zeigt auf kein Element")
    if occurrence is None:
        if len(group) != 1:
            raise QeaReaderError(f"semantische Sicht: Referenz {ref!r} ist mehrdeutig")
        element = group[0]
    else:
        if not 1 <= occurrence <= len(group):
            raise QeaReaderError(
                f"semantische Sicht: Referenz {ref!r} verlangt Vorkommen {occurrence}, "
                f"vorhanden sind {len(group)}"
            )
        element = group[occurrence - 1]
    return ("element", _element_token(element))


def semantic_view(ir: Mapping[str, Any]) -> dict[str, Any]:
    """Identitaetsfreie Sicht fuer Vergleiche.

    Vollstaendig inhaltlich identische Duplikate (gleiches Paket, gleicher Name,
    gleiche Beschreibung, gleiche Tags) teilen sich im IR denselben Inhalt; nur
    ihre Vorkommensnummer unterscheidet sie. Diese Nummer kann sich beim
    Schreiben/erneuten Lesen aendern, weil das IR keine Objekt-Identitaet kennt.
    ``semantic_view`` loest jede Kantenreferenz auf den Elementinhalt auf und
    macht solche Umnummerierungen sichtbar als das, was sie sind: bedeutungslos.
    """
    groups = _semantic_groups(ir)
    packages = sorted(
        (
            package.get("path", ""),
            package.get("name", package.get("path", "").rsplit("/", 1)[-1]),
            package.get("notes", ""),
            package.get("stereotype", ""),
            tuple(sorted(package.get("tags", {}).items())),
        )
        for package in ir.get("packages", [])
    )
    elements = sorted(_element_token(element) for element in ir.get("elements", []))
    connectors = sorted(
        (
            _semantic_ref(connector["source"], groups),
            _semantic_ref(connector["target"], groups),
            connector.get("stereotype", ""),
            connector.get("name", ""),
            connector.get("ea_type", DEFAULT_CONNECTOR_TYPE),
            connector.get("direction", DEFAULT_DIRECTION),
            connector.get("notes", ""),
            tuple(sorted(connector.get("tags", {}).items())),
        )
        for connector in ir.get("connectors", [])
    )
    technology = ir.get("technology") or {}
    return {
        "ir_version": ir.get("ir_version"),
        "technology_profile": technology.get("profile", ""),
        "packages": packages,
        "elements": elements,
        "connectors": connectors,
    }


def semantic_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """True, wenn beide IR denselben Inhalt beschreiben (ohne Objekt-Identitaet)."""
    return semantic_view(left) == semantic_view(right)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="QEA-Reader: .qea (EA-SQLite) -> IR-JSON. Nur lesen."
    )
    parser.add_argument("qea", help="Quelldatei .qea")
    parser.add_argument("-o", "--out", help="Ziel-IR-JSON (Default: stdout)")
    parser.add_argument("--report", action="store_true", help="Report/Warnungen auf stderr")
    parser.add_argument("--strict", action="store_true", help="Warnungen als Fehler behandeln")
    parser.add_argument(
        "--allow-empty", action="store_true", help="Modelle ohne Elemente zulassen"
    )
    args = parser.parse_args(argv)

    try:
        ir, report = read_qea_ex(args.qea, strict=args.strict, allow_empty=args.allow_empty)
    except QeaReaderError as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 2

    if args.out:
        write_ir(ir, args.out)
        print(f"{args.out}: {report.summary()}")
    else:
        sys.stdout.write(render_json(ir))
    if args.report:
        print(report.summary(), file=sys.stderr)
        for warning in report.warnings:
            print(f"WARNUNG: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
