"""model_merge.py -- mehrere .qea-Modelle GUID-erhaltend zusammenfuehren.

Zweck
-----
Zwei oder mehr Modelle (Teilarchitekturen, Zulieferungen, Standards) sollen zu
einem Modell werden, ohne dass die Identitaet der Objekte verloren geht. Kern
der Anforderung: die ``ea_guid`` jedes uebernommenen Objekts bleibt
**woertlich** erhalten -- nur so finden Modelle, die denselben Standard nutzen,
ueber die GUID zusammen (Austausch, Vergleich, Referenzen).

Warum nicht ueber ``qea_writer`` schreiben?
-------------------------------------------
``qea_writer`` ist ein Generator: er baut ein Modell aus IR neu auf und leitet
jede GUID aus dem Inhalt ab; ein IR-Feld ``guid`` lehnt er ausdruecklich ab.
Ein Merge ueber den Writer wuerde die GUID-Identitaet zerstoeren und das
Basismodell komplett neu schreiben. Der Merge arbeitet daher wie
``toolbox_merge`` auf einer byte-genauen Kopie des **ersten** Modells und fuegt
ausschliesslich Zeilen ein -- vorhandene Zeilen werden nie angefasst.

Regeln
------
* Basis ist ``paths[0]``: ``out`` ist dessen byte-genaue Kopie, ergaenzt um die
  Zeilen der weiteren Modelle. Kein Loeschen, kein Umbenennen, keine Aenderung
  einer bestehenden Zeile.
* ``ea_guid`` wird woertlich uebernommen (Elemente, Pakete, Kanten, Attribute).
  Nur wenn die Quelle keine GUID hat, wird eine deterministische Ersatz-GUID
  aus dem Inhalt abgeleitet (und im Bericht genannt).
* Existiert eine GUID bereits im Ziel, wird das Objekt uebersprungen. Das macht
  den Lauf idempotent: derselbe Aufruf auf dem Ergebnis aendert nichts.
* Pakete werden ueber ihren **Pfad** zusammengefuehrt (bei gleichem Pfad gibt es
  kein zweites Paket), sonst ueber die GUID, sonst neu eingefuegt. Ein neues
  Paket bekommt wie in EA ueblich einen Paketspiegel in ``t_object``.
* Elemente werden ueber (Paketpfad, Name, Stereotyp) als dasselbe Element
  erkannt und nicht dupliziert. Haben zwei Modelle am selben Pfad denselben
  Namen mit **unterschiedlichem** Stereotyp, sind das zwei verschiedene
  Elemente: beide bleiben erhalten, der Widerspruch steht im Bericht
  (``conflicts``).
* Kanten werden ueber die ``ea_guid`` ihrer Endpunkte aufgeloest, nie ueber
  ``Package_ID`` (die IDs werden beim Einfuegen neu vergeben). Eine Kante wird
  uebernommen, wenn ihre ``ea_guid`` im Ziel fehlt und beide Endpunkte per GUID
  aufloesbar sind -- auch wenn die Endpunkte schon vorher im Ziel lagen.
* Tagged Values werden aus ``t_objectproperties`` und den ``@PROP``-Zeilen in
  ``t_xref`` mitgenommen. Bei gleichem Tag und gleichem Owner gewinnt der
  Zielwert; weicht der Quellwert ab, steht das im Bericht. Grundlage des
  Vergleichs ist ``t_objectproperties`` -- der Speicher, den ``qea_reader``
  liest; eine vorhandene ``@PROP``-Zeile wird nie ueberschrieben.
* Sichten/Diagramme werden nicht uebernommen (kein Layout); Verweise darauf
  werden auf 0 gesetzt und gezaehlt.
* Deterministisch: gleiche Eingaben -> identische Bytes. Keine Zeitstempel,
  keine Zufalls-GUIDs, feste Einfuegereihenfolge, sortierter Bericht.

Oeffentliche API
----------------
    merge_models(paths, out, package=None) -> MergeResult
    main(argv) -> int

CLI
---
    python3 model_merge.py A.qea B.qea [...] --out ZIEL.qea [--paket NAME]
    eam-ai merge --qea A.qea B.qea [...] --out ZIEL.qea [--bericht bericht.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import qea_writer

__all__ = ["MergeError", "MergeResult", "merge_models", "main"]

#: Tabellen, in die der Merge schreibt -- in dieser Reihenfolge (Eltern zuerst).
_WRITE_ORDER: tuple[str, ...] = (
    "t_package",
    "t_object",
    "t_objectproperties",
    "t_xref",
    "t_attribute",
    "t_attributetag",
    "t_attributeconstraints",
    "t_connector",
    "t_connectortag",
    "t_connectorconstraint",
)

#: Pflicht-Tabellen: ohne sie ist kein Merge moeglich (Abbruch statt Teilmerge).
_REQUIRED: tuple[str, ...] = ("t_package", "t_object", "t_connector")

#: Objekttyp der Paketspiegel in ``t_object`` (kein Element, nur Darstellung).
_PACKAGE_OBJECT_TYPE = "Package"

#: Spalten, die nie aus der Quelle uebernommen werden (Identitaet, Zielkontext).
_NEVER_COPY = frozenset({"package_id", "object_id", "connector_id", "propertyid", "id"})

#: ``t_xref``-Typen, die zu einem Objekt gehoeren (keine Sicht-Eigenschaften).
_OBJECT_XREF_TYPES = frozenset({"element property", "connector property", "stereotype"})

_PROP_PREFIX = "@PROP="
_NAME_MARK = "@NAME="
_NAME_END = "@ENDNAME;"
_VALU_MARK = "@VALU="
_VALU_END = "@ENDVALU;"

_MAX_WARNINGS = 200


class MergeError(ValueError):
    """Eingabe- oder Zustandsfehler. Immer laut, nie still."""


@dataclass
class MergeResult:
    """Ergebnis eines Merge-Laufs (fuer CLI, Tests und Einbettung)."""

    #: Pfad der geschriebenen Datei.
    written: str
    #: Neu eingefuegte Elemente (ohne Paketspiegel).
    elements: int
    #: Neu eingefuegte Kanten.
    connections: int
    #: Widersprueche, jeweils ein dict mit ``art`` und Kontext.
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    #: Neu eingefuegte Pakete.
    packages: int = 0
    #: Neu eingefuegte Tag-Zeilen (``t_objectproperties``, ``t_xref``, ...).
    tags: int = 0
    #: Wie viele Modelle gelesen wurden (inklusive Basis).
    models: int = 0
    #: Wie viele Elemente schon vorhanden waren und deshalb nicht dupliziert wurden.
    merged: int = 0
    #: Nicht uebernommene Kanten und andere Auffaelligkeiten.
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Kanonischer Bericht: sortierte Schluessel, keine Zeitstempel."""
        return {
            "geschrieben": self.written,
            "modelle": self.models,
            "pakete": self.packages,
            "elemente": self.elements,
            "kanten": self.connections,
            "tags": self.tags,
            "zusammengefuehrt": self.merged,
            "konflikte": self.conflicts,
            "warnungen": self.warnings,
        }


# --------------------------------------------------------------------------
# Kleine Helfer
# --------------------------------------------------------------------------


def _quote(identifier: str) -> str:
    """SQLite-Bezeichner quoten (Namen wie ``Constraint`` sind reserviert)."""
    return '"' + identifier.replace('"', '""') + '"'


def _stable_guid(seed: str) -> str:
    """Deterministische Ersatz-GUID im EA-Format ``{8-4-4-4-12}``."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32].upper()
    return (
        "{"
        + digest[0:8]
        + "-"
        + digest[8:12]
        + "-"
        + digest[12:16]
        + "-"
        + digest[16:20]
        + "-"
        + digest[20:32]
        + "}"
    )


def _as_int(value: Any, *, default: int = 0) -> int:
    """Robuste Ganzzahl: NULL/Leertext -> default, sonst int()."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_text(value: Any) -> str:
    """Robuster Text: NULL -> "", sonst str(). Kein strip() (Werte bleiben roh)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _guid_key(value: Any) -> str:
    """Vergleichsschluessel fuer GUIDs: getrimmt, Grossbuchstaben, leer = ""."""
    return _as_text(value).strip().upper()


def _warn(warnings: list[str], message: str) -> None:
    """Warnung anhaengen, Gesamtzahl begrenzen (kein unbegrenztes Wachstum)."""
    if len(warnings) < _MAX_WARNINGS:
        warnings.append(message)
    elif len(warnings) == _MAX_WARNINGS:
        warnings.append("weitere Warnungen unterdrueckt")


def _connect_ro(path: Path) -> sqlite3.Connection:
    """Oeffnet eine .qea ausschliesslich lesend (URI ``mode=ro``)."""
    if not path.exists():
        raise MergeError(f"{path}: Datei nicht gefunden")
    if not path.is_file():
        raise MergeError(f"{path}: keine regulaere Datei")
    uri = "file:" + urllib.parse.quote(str(path)) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:  # pragma: no cover - sehr selten
        raise MergeError(f"{path}: nicht lesbar ({error})") from error
    con.row_factory = sqlite3.Row
    con.text_factory = str
    try:
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as error:
        con.close()
        raise MergeError(f"{path}: keine lesbare .qea ({error})") from error
    return con


def _table_names(con: sqlite3.Connection) -> dict[str, str]:
    """Tatsaechliche Tabellennamen, Schluessel kleingeschrieben."""
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]).lower(): str(row[0]) for row in rows}


class _Table:
    """Gelesene Tabelle: Spalten plus Zeilen mit kleingeschriebenen Schluesseln.

    Kleingeschriebene Schluessel machen den Zugriff unabhaengig davon, ob EA
    ``ea_guid``, ``ea_GUID`` oder ``EA_Guid`` schreibt (echte Dateien variieren).
    """

    __slots__ = ("name", "columns", "rows")

    def __init__(self, name: str, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]):
        self.name = name
        self.columns = list(columns)
        self.rows = [dict(row) for row in rows]

    def has(self, column: str) -> bool:
        lowered = column.lower()
        return any(item.lower() == lowered for item in self.columns)

    @staticmethod
    def get(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
        """Erster vorhandener Spaltenwert (Namen case-insensitiv)."""
        for name in names:
            key = name.lower()
            if key in row:
                return row[key]
        return default


def _empty_table(name: str = "") -> _Table:
    return _Table(name, (), ())


def _read_table(
    con: sqlite3.Connection,
    tables: Mapping[str, str],
    name: str,
    warnings: list[str],
    *,
    required: bool = False,
) -> _Table:
    """Liest eine Tabelle komplett; fehlt sie, wird gewarnt (oder abgebrochen)."""
    actual = tables.get(name.lower())
    if actual is None:
        if required:
            raise MergeError(f"Pflicht-Tabelle {name} fehlt in der Datenbank")
        warnings.append(
            f"{name}: Tabelle fehlt -- zugehoerige Inhalte werden nicht uebernommen"
        )
        return _empty_table(name)
    columns = [str(row[1]) for row in con.execute(f"PRAGMA table_info({_quote(actual)})")]
    rows: list[dict[str, Any]] = []
    for raw in con.execute(f"SELECT * FROM {_quote(actual)}"):
        rows.append({column.lower(): raw[index] for index, column in enumerate(columns)})
    return _Table(actual, columns, rows)


def _max_int(table: _Table, column: str) -> int:
    if not table.has(column):
        return 0
    return max((_as_int(_Table.get(row, column)) for row in table.rows), default=0)


def _next_tpos_map(table: _Table, parent_column: str, pos_column: str = "tpos") -> dict[int, int]:
    """Naechste freie Position je Elternknoten (deterministisch)."""
    result: dict[int, int] = defaultdict(int)
    if not table.has(pos_column):
        return dict(result)
    for row in table.rows:
        parent = _as_int(_Table.get(row, parent_column))
        result[parent] = max(result[parent], _as_int(_Table.get(row, pos_column)))
    return {parent: value + 1 for parent, value in result.items()}


def _copy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Zeile kopieren, Identitaetsspalten entfernen (werden neu vergeben)."""
    return {key: value for key, value in row.items() if key.lower() not in _NEVER_COPY}


# --------------------------------------------------------------------------
# Quelle lesen
# --------------------------------------------------------------------------


@dataclass
class _Source:
    """Ein gelesenes Modell.

    Die Rohzeilen der Neben-Tabellen werden nur zum Indexieren gelesen; danach
    zaehlen die Indizes (Zugriff in O(1) statt wiederholtem Tabellenscan).
    """

    path: Path
    index: int
    packages: _Table
    objects: _Table
    connectors: _Table
    #: Package_ID -> Pfad aus Anzeigenamen ("A/B/C").
    package_paths: dict[int, str]
    #: Package_ID -> Zeile.
    package_rows: dict[int, dict[str, Any]]
    #: Package_IDs in Baumreihenfolge (Eltern vor Kindern).
    package_order: list[int]
    #: Package_ID -> Elementzeilen (ohne Paketspiegel), nach Object_ID.
    elements_by_package: dict[int, list[dict[str, Any]]]
    #: Object_ID -> ea_guid (Elemente *und* Paketspiegel).
    object_guids: dict[int, str]
    #: GUID-Schluessel -> Paketspiegelzeile (Vorlage fuer neue Spiegel).
    package_mirrors: dict[str, dict[str, Any]]
    #: Object_ID -> Tag-Zeilen.
    tags_by_object: dict[int, list[dict[str, Any]]]
    #: GUID-Schluessel -> xref-Zeilen mit Objektbezug.
    xrefs_by_client: dict[str, list[dict[str, Any]]]
    #: Object_ID -> Attributzeilen.
    attributes_by_object: dict[int, list[dict[str, Any]]]
    #: Attribute-ID -> Tag-Zeilen.
    attribute_tags: dict[int, list[dict[str, Any]]]
    #: Attribute-ID -> Constraint-Zeilen.
    attribute_constraints: dict[int, list[dict[str, Any]]]
    #: Connector_ID -> Tag-Zeilen.
    connector_tags: dict[int, list[dict[str, Any]]]
    #: Connector_ID -> Constraint-Zeilen.
    connector_constraints: dict[int, list[dict[str, Any]]]
    diagram_objects: int
    #: Object_ID -> (Paketpfad, Name, Stereotyp) fuer den Rueckgriff ohne ea_guid.
    identities: dict[int, tuple[str, str, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.path.name


def _identity_key(pfad: str, name: str, stereotyp: str) -> tuple[str, str, str]:
    """Vergleichsschluessel fuer Elemente ohne gemeinsame ``ea_guid``."""
    return (pfad.strip().casefold(), name.strip().casefold(), (stereotyp or "").strip().casefold())


def _identity_index(
    objects: _Table, package_paths: Mapping[int, str]
) -> dict[tuple[str, str, str], int]:
    """Kennung je (Pfad, Name, Stereotyp) -- aeltestes Element gewinnt."""
    gefunden: dict[tuple[str, str, str], int] = {}
    for object_id, schluessel in sorted(_element_identities(objects, package_paths).items()):
        gefunden.setdefault(_identity_key(*schluessel), object_id)
    return gefunden


def _element_identities(
    objects: _Table, package_paths: Mapping[int, str]
) -> dict[int, tuple[str, str, str]]:
    """Je Element (Package_ID, Name, Stereotyp) -- Grundlage des Pfad-Rueckgriffs.

    Nur benannte Elemente: unbenannte Notizen und Texte haben keinen
    fachlichen Namen und koennen nicht sinnvoll verglichen werden.
    """
    gefunden: dict[int, tuple[str, str, str]] = {}
    for row in objects.rows:
        typ = _as_text(_Table.get(row, "Object_Type")).strip().casefold()
        if typ == "package":
            continue
        name = _as_text(_Table.get(row, "Name")).strip()
        if not name:
            continue
        pfad = package_paths.get(_as_int(_Table.get(row, "Package_ID")), "")
        gefunden[_as_int(_Table.get(row, "Object_ID"))] = (
            pfad,
            name,
            _as_text(_Table.get(row, "Stereotype")).strip(),
        )
    return gefunden


def _package_paths(packages: _Table) -> tuple[dict[int, str], dict[int, dict[str, Any]]]:
    """Pfad je Paket aus den Anzeigenamen; Zyklen werden abgefangen."""
    rows: dict[int, dict[str, Any]] = {}
    for row in packages.rows:
        package_id = _as_int(_Table.get(row, "Package_ID"))
        if package_id > 0:
            rows[package_id] = row

    paths: dict[int, str] = {}

    def path_of(package_id: int) -> str:
        cached = paths.get(package_id)
        if cached is not None:
            return cached
        segments: list[str] = []
        seen: set[int] = set()
        current = package_id
        while current in rows and current not in seen:
            seen.add(current)
            segments.append(_as_text(_Table.get(rows[current], "Name")).strip())
            current = _as_int(_Table.get(rows[current], "Parent_ID"))
        result = "/".join(reversed(segments))
        paths[package_id] = result
        return result

    for package_id in rows:
        # Eltern zuerst fuellen: die Rekursion ist dann ein Dict-Zugriff.
        path_of(package_id)
    # Zwischenergebnisse mit Teilpfaden sind korrekt, weil path_of den ganzen
    # Stamm bis zur Wurzel laeuft; ein zweiter Durchlauf festigt sie.
    for package_id in sorted(rows):
        paths[package_id] = path_of(package_id)
    return paths, rows


def _tree_order(by_id: Mapping[int, Mapping[str, Any]]) -> list[int]:
    """Pakete in Baumreihenfolge: Eltern vor Kindern, dann Package_ID."""
    def depth(package_id: int) -> int:
        seen: set[int] = set()
        current = package_id
        level = 0
        while True:
            parent = _as_int(by_id.get(current, {}).get("parent_id"))
            if parent not in by_id or parent in seen or parent == current:
                return level
            seen.add(current)
            level += 1
            current = parent

    return sorted(by_id, key=lambda pid: (depth(pid), pid))


def _read_source(path: Path, index: int) -> _Source:
    """Liest ein Modell vollstaendig (nur lesend)."""
    warnings: list[str] = []
    con = _connect_ro(path)
    try:
        tables = _table_names(con)
        packages = _read_table(con, tables, "t_package", warnings, required=True)
        objects = _read_table(con, tables, "t_object", warnings, required=True)
        connectors = _read_table(con, tables, "t_connector", warnings, required=True)
        tags = _read_table(con, tables, "t_objectproperties", warnings)
        xrefs = _read_table(con, tables, "t_xref", warnings)
        attributes = _read_table(con, tables, "t_attribute", warnings)
        attribute_tags_table = _read_table(con, tables, "t_attributetag", warnings)
        attribute_constraints_table = _read_table(con, tables, "t_attributeconstraints", warnings)
        connector_tags_table = _read_table(con, tables, "t_connectortag", warnings)
        connector_constraints_table = _read_table(con, tables, "t_connectorconstraint", warnings)
        diagram_objects = 0
        for name in ("t_diagramobjects", "t_diagramlinks"):
            actual = tables.get(name)
            if actual is not None:
                row = con.execute(f"SELECT count(*) FROM {_quote(actual)}").fetchone()
                diagram_objects += _as_int(row[0] if row else 0)
    finally:
        con.close()

    paths, package_rows = _package_paths(packages)
    if not package_rows:
        raise MergeError(f"{path}: enthaelt kein Paket (t_package ist leer)")

    elements_by_package: dict[int, list[dict[str, Any]]] = defaultdict(list)
    object_guids: dict[int, str] = {}
    package_mirrors: dict[str, dict[str, Any]] = {}
    for row in sorted(objects.rows, key=lambda item: _as_int(_Table.get(item, "Object_ID"))):
        object_id = _as_int(_Table.get(row, "Object_ID"))
        if object_id <= 0:
            continue
        guid = _as_text(_Table.get(row, "ea_guid")).strip()
        if guid:
            object_guids.setdefault(object_id, guid)
        if _as_text(_Table.get(row, "Object_Type")).strip().casefold() == _PACKAGE_OBJECT_TYPE.casefold():
            key = _guid_key(guid)
            if key:
                package_mirrors.setdefault(key, row)
            continue
        elements_by_package[_as_int(_Table.get(row, "Package_ID"))].append(row)

    tags_by_object: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(tags.rows, key=lambda item: _as_int(_Table.get(item, "PropertyID"))):
        tags_by_object[_as_int(_Table.get(row, "Object_ID"))].append(row)

    xrefs_by_client: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(xrefs.rows, key=lambda item: _as_text(_Table.get(item, "XrefID"))):
        if _as_text(_Table.get(row, "Type")).strip().casefold() not in _OBJECT_XREF_TYPES:
            continue
        client = _guid_key(_Table.get(row, "Client"))
        if client:
            xrefs_by_client[client].append(row)

    attributes_by_object: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(attributes.rows, key=lambda item: _as_int(_Table.get(item, "ID"))):
        attribute_id = _as_int(_Table.get(row, "ID"))
        owner = _as_int(_Table.get(row, "Object_ID"))
        attributes_by_object[owner].append(row)
        if not attribute_id:
            continue

    attribute_tag_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(attribute_tags_table.rows, key=lambda item: _as_int(_Table.get(item, "PropertyID"))):
        attribute_tag_rows[_as_int(_Table.get(row, "ElementID"))].append(row)

    attribute_constraint_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(
        attribute_constraints_table.rows,
        key=lambda item: (_as_int(_Table.get(item, "Object_ID")), _as_text(_Table.get(item, "Constraint"))),
    ):
        attribute_constraint_rows[_as_int(_Table.get(row, "ID"))].append(row)

    connector_tag_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(connector_tags_table.rows, key=lambda item: _as_int(_Table.get(item, "PropertyID"))):
        connector_tag_rows[_as_int(_Table.get(row, "ElementID"))].append(row)

    connector_constraint_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(
        connector_constraints_table.rows,
        key=lambda item: (_as_int(_Table.get(item, "ConnectorID")), _as_text(_Table.get(item, "Constraint"))),
    ):
        connector_constraint_rows[_as_int(_Table.get(row, "ConnectorID"))].append(row)

    return _Source(
        path=path,
        index=index,
        packages=packages,
        objects=objects,
        connectors=connectors,
        package_paths=paths,
        package_rows=package_rows,
        package_order=_tree_order(package_rows),
        elements_by_package=dict(elements_by_package),
        object_guids=object_guids,
        package_mirrors=package_mirrors,
        tags_by_object=dict(tags_by_object),
        xrefs_by_client=dict(xrefs_by_client),
        attributes_by_object=dict(attributes_by_object),
        attribute_tags=dict(attribute_tag_rows),
        attribute_constraints=dict(attribute_constraint_rows),
        connector_tags=dict(connector_tag_rows),
        connector_constraints=dict(connector_constraint_rows),
        diagram_objects=diagram_objects,
        identities=_element_identities(objects, paths),
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Zielzustand (nur gelesen, dann fortschreibend gepflegt)
# --------------------------------------------------------------------------


@dataclass
class _Target:
    """Was im Ziel schon da ist; die Indizes wachsen mit jedem Einfuegen mit."""

    tables: dict[str, _Table]
    package_ids: dict[int, dict[str, Any]]
    package_paths: dict[int, str]
    package_by_path: dict[str, int]
    package_guids: dict[str, int]
    object_ids: dict[int, dict[str, Any]]
    object_guids: dict[str, int]
    connector_guids: set[str]
    xref_ids: set[str]
    #: (Paketpfad, Name) -> [(Stereotyp, Object_ID)] vorhandener Elemente.
    elements: dict[tuple[str, str], list[tuple[str, int]]]
    #: (Name, Stereotyp) -> [(Paketpfad, Object_ID)]; Grundlage des paketuebergreifenden Abgleichs.
    elements_by_name: dict[tuple[str, str], list[tuple[str, int]]]
    #: Object_ID -> {Tag-Name: Wert} vorhandener Tags.
    tag_index: dict[int, dict[str, str]]
    #: (Client-GUID, Tag-Name) -> Wert vorhandener ``@PROP``-Zeilen.
    xref_props: dict[tuple[str, str], str]
    next_package_id: int
    next_object_id: int
    next_connector_id: int
    next_property_id: int
    next_attribute_id: int
    next_package_tpos: dict[int, int]
    next_object_tpos: dict[int, int]
    #: Je Tabelle die Spalten, die das Ziel als Zahl ablegt (klein geschrieben).
    int_columns: dict[str, frozenset[str]]
    #: Naechste freie ``t_xref.XrefID``, wenn das Ziel sie als Zahl fuehrt.
    next_xref_id: int
    #: (Paketpfad, Name, Stereotyp) -> Object_ID; wird bei Bedarf gebaut.
    identities: dict[tuple[str, str, str], int] = field(default_factory=dict)


def _read_target(path: Path, warnings: list[str]) -> _Target:
    """Liest den Zielzustand (Basismodell) samt Indizes."""
    con = _connect_ro(path)
    try:
        tables = _table_names(con)
        missing = [name for name in qea_writer.AARON_REQUIRED_TABLES if name.lower() not in tables]
        if missing:
            _warn(
                warnings,
                "Basismodell kennt nicht alle 15 Pflichttabellen externer Leser "
                f"(fehlen: {', '.join(missing)}) -- es wird nur in vorhandene Tabellen geschrieben",
            )
        snapshot: dict[str, _Table] = {}
        int_columns: dict[str, frozenset[str]] = {}
        for name in _WRITE_ORDER:
            actual = tables.get(name.lower())
            if actual is None:
                _warn(warnings, f"Ziel: Tabelle {name} fehlt -- Inhalte koennen nicht uebernommen werden")
                snapshot[name] = _empty_table(name)
                continue
            info = list(con.execute(f"PRAGMA table_info({_quote(actual)})"))
            columns = [str(row[1]) for row in info]
            int_columns[name] = frozenset(
                str(row[1]).lower()
                for row in info
                if "INT" in str(row[2] or "").upper()
            )
            rows = [
                {column.lower(): raw[index] for index, column in enumerate(columns)}
                for raw in con.execute(f"SELECT * FROM {_quote(actual)}")
            ]
            snapshot[name] = _Table(actual, columns, rows)
    finally:
        con.close()

    package_ids = {
        _as_int(_Table.get(row, "Package_ID")): row
        for row in snapshot["t_package"].rows
        if _as_int(_Table.get(row, "Package_ID")) > 0
    }
    object_ids = {
        _as_int(_Table.get(row, "Object_ID")): row
        for row in snapshot["t_object"].rows
        if _as_int(_Table.get(row, "Object_ID")) > 0
    }
    paths, _ = _package_paths(snapshot["t_package"])

    package_by_path: dict[str, int] = {}
    for package_id in sorted(package_ids):
        path = paths.get(package_id, "")
        if path:
            package_by_path.setdefault(path, package_id)
    package_guids: dict[str, int] = {}
    for package_id in sorted(package_ids):
        key = _guid_key(_Table.get(package_ids[package_id], "ea_guid"))
        if key:
            package_guids.setdefault(key, package_id)
    object_guids: dict[str, int] = {}
    elements: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    #: (Name, Stereotyp) -> [(Paketpfad, Object_ID)] ueber alle Pakete.
    elements_by_name: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    tag_index: dict[int, dict[str, str]] = defaultdict(dict)
    for object_id in sorted(object_ids):
        row = object_ids[object_id]
        key = _guid_key(_Table.get(row, "ea_guid"))
        if key:
            object_guids.setdefault(key, object_id)
        if _as_text(_Table.get(row, "Object_Type")).strip().casefold() == _PACKAGE_OBJECT_TYPE.casefold():
            continue
        package_id = _as_int(_Table.get(row, "Package_ID"))
        path = paths.get(package_id, "")
        name = _as_text(_Table.get(row, "Name"))
        stereotype = _as_text(_Table.get(row, "Stereotype"))
        elements[(path, name)].append((stereotype, object_id))
        # Zusaetzlich ueber Name + Stereotyp, ueber Paketgrenzen hinweg.
        elements_by_name[(name, stereotype)].append((path, object_id))
    for row in snapshot["t_objectproperties"].rows:
        owner = _as_int(_Table.get(row, "Object_ID"))
        name = _as_text(_Table.get(row, "Property", "Name")).strip()
        if owner and name:
            tag_index[owner].setdefault(name, _as_text(_Table.get(row, "Value")))

    xref_props: dict[tuple[str, str], str] = {}
    for row in snapshot["t_xref"].rows:
        if _as_text(_Table.get(row, "Type")).strip().casefold() not in _OBJECT_XREF_TYPES:
            continue
        name, value = _parse_prop(_as_text(_Table.get(row, "Description")))
        client = _guid_key(_Table.get(row, "Client"))
        if client and name:
            xref_props.setdefault((client, name), value)

    return _Target(
        tables=snapshot,
        package_ids=package_ids,
        package_paths=paths,
        package_by_path=package_by_path,
        package_guids=package_guids,
        object_ids=object_ids,
        object_guids=object_guids,
        connector_guids={
            _guid_key(_Table.get(row, "ea_guid"))
            for row in snapshot["t_connector"].rows
            if _guid_key(_Table.get(row, "ea_guid"))
        },
        xref_ids={
            _guid_key(_Table.get(row, "XrefID"))
            for row in snapshot["t_xref"].rows
            if _guid_key(_Table.get(row, "XrefID"))
        },
        elements=dict(elements),
        elements_by_name=dict(elements_by_name),
        tag_index=dict(tag_index),
        xref_props=xref_props,
        next_package_id=_max_int(snapshot["t_package"], "Package_ID") + 1,
        next_object_id=_max_int(snapshot["t_object"], "Object_ID") + 1,
        next_connector_id=_max_int(snapshot["t_connector"], "Connector_ID") + 1,
        next_property_id=max(
            _max_int(snapshot["t_objectproperties"], "PropertyID"),
            _max_int(snapshot["t_connectortag"], "PropertyID"),
            _max_int(snapshot["t_attributetag"], "PropertyID"),
        )
        + 1,
        next_attribute_id=_max_int(snapshot["t_attribute"], "ID") + 1,
        next_package_tpos=_next_tpos_map(snapshot["t_package"], "Parent_ID"),
        next_object_tpos=_next_tpos_map(snapshot["t_object"], "Package_ID"),
        int_columns=int_columns,
        next_xref_id=_max_int(snapshot["t_xref"], "XrefID") + 1,
        identities=_identity_index(snapshot["t_object"], paths),
    )


def _parse_prop(description: str) -> tuple[str, str]:
    """Liest ``@NAME=...`` und ``@VALU=...`` aus einer ``t_xref``-Zeile."""
    if not description.startswith(_PROP_PREFIX):
        return "", ""
    start = description.find(_NAME_MARK)
    if start < 0:
        return "", ""
    start += len(_NAME_MARK)
    end = description.find(_NAME_END, start)
    if end < 0:
        return "", ""
    name = description[start:end]
    vstart = description.find(_VALU_MARK)
    value = ""
    if vstart >= 0:
        vstart += len(_VALU_MARK)
        vend = description.find(_VALU_END, vstart)
        value = description[vstart:vend] if vend >= 0 else description[vstart:]
    return name, value


# --------------------------------------------------------------------------
# Plan bauen
# --------------------------------------------------------------------------


@dataclass
class _Plan:
    """Alle einzufuegenden Zeilen plus Berichtszahlen."""

    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "pakete": 0,
            "elemente": 0,
            "kanten": 0,
            "tags": 0,
            "merged": 0,
        }
    )

    def add(self, table: str, row: dict[str, Any]) -> None:
        self.rows.setdefault(table, []).append(row)

    def total(self) -> int:
        return sum(len(rows) for rows in self.rows.values())


class _Merger:
    """Fuehrt ein Quellmodell in den Zielzustand ein (nur Zeilen anhaengen)."""

    def __init__(self, target: _Target, plan: _Plan, *, per_name: bool = False):
        self.target = target
        self.plan = plan
        self.per_name = per_name

    # -- Pakete ---------------------------------------------------------
    def packages(self, source: _Source, prefix: str, container_id: int) -> dict[int, int]:
        """Bildet Quell-Package_IDs auf Ziel-Package_IDs ab und legt neue an."""
        target = self.target
        plan = self.plan
        package_map: dict[int, int] = {}
        positions = dict(target.next_package_tpos)

        for source_id in source.package_order:
            row = source.package_rows[source_id]
            source_path = source.package_paths.get(source_id, _as_text(_Table.get(row, "Name")))
            path = f"{prefix}/{source_path}" if prefix else source_path
            parent_source = _as_int(_Table.get(row, "Parent_ID"))
            if parent_source in package_map:
                parent_target = package_map[parent_source]
            elif parent_source in source.package_rows:
                parent_target = container_id  # Eltern ausserhalb des Laufs
            else:
                parent_target = container_id

            guid = _as_text(_Table.get(row, "ea_guid")).strip()
            existing = target.package_by_path.get(path)
            if existing is None and guid:
                existing = target.package_guids.get(_guid_key(guid))
                if existing is not None:
                    _warn(
                        plan.warnings,
                        f"Paket {path!r} gibt es im Ziel schon unter anderem Pfad "
                        f"(GUID {guid}) -- wird dort verwendet, nicht verschoben",
                    )
            if existing is not None:
                package_map[source_id] = existing
                continue

            new_id = target.next_package_id
            target.next_package_id += 1
            new_row = _copy_row(row)
            new_row["package_id"] = new_id
            new_row["parent_id"] = parent_target
            if not guid:
                # Reine Inhaltsfunktion: derselbe Pfad ergibt dieselbe GUID,
                # unabhaengig davon, an welcher Stelle das Modell steht.
                guid = _stable_guid(f"model_merge|package|{path}")
                if _guid_key(guid) in target.package_guids:
                    package_map[source_id] = target.package_guids[_guid_key(guid)]
                    continue
                _warn(
                    plan.warnings,
                    f"Paket {path!r} ohne ea_guid -- deterministische GUID vergeben ({guid})",
                )
            new_row["ea_guid"] = guid
            position = positions.get(parent_target, 0)
            positions[parent_target] = position + 1
            if target.tables["t_package"].has("tpos"):
                new_row["tpos"] = position
            plan.add("t_package", new_row)
            package_map[source_id] = new_id
            target.package_ids[new_id] = new_row
            target.package_by_path[path] = new_id
            target.package_paths[new_id] = path
            target.package_guids[_guid_key(guid)] = new_id
            plan.counts["pakete"] += 1

            mirror_id = self._package_mirror(source, source_id, new_id, parent_target, guid, position)
            if mirror_id is not None:
                # Paket-Stereotype liegen in t_xref am Paket-GUID.
                self._add_xrefs(
                    source, _guid_key(guid), guid, allow_existing=False, owner=f"Paket {path!r}"
                )
        return package_map

    def _package_mirror(
        self,
        source: _Source,
        source_package_id: int,
        target_package_id: int,
        parent_target: int,
        guid: str,
        position: int,
    ) -> int | None:
        """Legt den EA-Paketspiegel in ``t_object`` an (Vorlage aus der Quelle).

        Wurzelpakete bekommen nur dann einen Spiegel, wenn die Quelle selbst
        einen hat -- EA-Konvention ist "kein Spiegel fuer Wurzeln", und
        ``qea_reader`` meldet ueberzaehlige Wurzelspiegel als Warnung.
        """
        target = self.target
        if not target.tables["t_object"].columns:
            return None
        if _guid_key(guid) in target.object_guids:
            return target.object_guids[_guid_key(guid)]
        source_mirror = source.package_mirrors.get(_guid_key(guid))
        if source_mirror is not None:
            mirror = _copy_row(source_mirror)
        elif parent_target != 0:
            mirror = {
                "object_type": _PACKAGE_OBJECT_TYPE,
                "name": _as_text(
                    _Table.get(source.package_rows.get(source_package_id, {}), "name")
                ),
                "alias": "",
                "note": "",
                "stereotype": "",
                "status": "",
                "version": "1.0",
                "createddate": "",
                "modifieddate": "",
            }
        else:
            return None
        mirror_id = target.next_object_id
        target.next_object_id += 1
        mirror["object_id"] = mirror_id
        mirror["package_id"] = parent_target
        # ``qea_reader`` ordnet Paketspiegel zuerst ueber ``PDATA1`` zu. Der
        # Wert zeigt auf die ``t_package.Package_ID`` des gespiegelten Pakets
        # und muss deshalb auf die neue Ziel-ID umgebogen werden; sonst kollidiert
        # ein eingefuegtes Unterpaket mit einem vorhandenen Paket gleicher ID.
        if "pdata1" in mirror:
            mirror["pdata1"] = str(target_package_id)
        if "diagram_id" in mirror:
            mirror["diagram_id"] = 0
        mirror["ea_guid"] = guid
        if target.tables["t_object"].has("tpos"):
            mirror["tpos"] = position
        self.plan.add("t_object", mirror)
        target.object_ids[mirror_id] = mirror
        target.object_guids[_guid_key(guid)] = mirror_id
        # Tags eines Paketspiegels haengen an dessen Object_ID, nicht am Paket.
        if source_mirror is not None:
            source_mirror_id = int(_as_text(_Table.get(source_mirror, "object_id")) or 0)
            if source_mirror_id:
                self._copy_tags(source, source_mirror_id, mirror_id)
        return mirror_id

    # -- xref -----------------------------------------------------------
    def _add_xrefs(
        self,
        source: _Source,
        client_key: str,
        client_guid: str,
        *,
        allow_existing: bool,
        owner: str,
    ) -> None:
        """Uebernimmt ``t_xref``-Zeilen eines Objekts (Stereotyp und ``@PROP``).

        ``t_xref.XrefID`` ist je nach Modellstand eine Zahl (aeltere Dateien)
        oder eine GUID (ab EA 16). Das Ziel gibt die Form vor; eine GUID in
        einer INTEGER-Spalte war bisher ein harter Abbruch ("datatype
        mismatch") mitten im Schreiben.
        """
        target = self.target
        xref_numeric = "xrefid" in target.int_columns.get("t_xref", frozenset())
        for row in source.xrefs_by_client.get(client_key, []):
            xref_type = _as_text(_Table.get(row, "Type"))
            description = _as_text(_Table.get(row, "Description"))
            name, value = _parse_prop(description)
            if allow_existing and description.startswith("@STEREO;"):
                # Das Zielobjekt existiert schon; sein Stereotyp ist massgeblich.
                # Eine zweite @STEREO-Zeile waere nur eine Dublette.
                continue
            if allow_existing and not name:
                # Keine Tag-Zeile (z. B. DefaultDiagram): gehoert zum Bestand.
                continue
            if allow_existing and (client_key, name) in target.xref_props:
                # Zielwert gewinnt -- kein Duplikat, kein Konflikt (der Tag-Bericht
                # fuer t_objectproperties nennt den Widerspruch bereits).
                continue
            if xref_numeric:
                candidate = target.next_xref_id
                target.next_xref_id += 1
            else:
                seed = f"model_merge|xref|{client_key}|{xref_type}|{name}|{description}"
                candidate = _stable_guid(seed)
                suffix = 1
                while _guid_key(candidate) in target.xref_ids:
                    if not allow_existing:
                        candidate = ""
                        break
                    candidate = _stable_guid(f"{seed}|{suffix}")
                    suffix += 1
                if not candidate:
                    continue
                target.xref_ids.add(_guid_key(candidate))
            new_row = _copy_row(row)
            new_row["xrefid"] = candidate
            new_row["client"] = client_guid
            self.plan.add("t_xref", new_row)
            self.plan.counts["tags"] += 1
            if name:
                target.xref_props.setdefault((client_key, name), value)

    # -- Elemente -------------------------------------------------------
    def elements(self, source: _Source, package_map: Mapping[int, int]) -> dict[int, int]:
        """Fuegt Elemente ein und liefert Quell-Object_ID -> Ziel-Object_ID."""
        target = self.target
        plan = self.plan
        element_map: dict[int, int] = {}
        positions = dict(target.next_object_tpos)

        for source_package in source.package_order:
            target_package = package_map.get(source_package)
            if target_package is None:
                continue
            path = target.package_paths.get(target_package, "")
            for row in source.elements_by_package.get(source_package, []):
                object_id = _as_int(_Table.get(row, "Object_ID"))
                name = _as_text(_Table.get(row, "Name"))
                stereotype = _as_text(_Table.get(row, "Stereotype"))
                guid = _as_text(_Table.get(row, "ea_guid")).strip()
                key = (path, name)
                # Paketuebergreifend: dasselbe Element (Name + Stereotyp) kann
                # im Lauf unter dem Arbeitspaket stehen und im Bestand unter dem
                # Standardpaket des Startkastens. Ueber den Pfad allein blieben
                # es zwei Zeilen -- genau der Fall, den die Wiederverwendung
                # verhindern soll.
                cross_key = (name, stereotype)

                if guid and _guid_key(guid) in target.object_guids:
                    existing_id = target.object_guids[_guid_key(guid)]
                    existing_row = target.object_ids.get(existing_id, {})
                    if (
                        _as_text(_Table.get(existing_row, "Object_Type")).strip().casefold()
                        == _PACKAGE_OBJECT_TYPE.casefold()
                    ):
                        _warn(
                            plan.warnings,
                            f"Element {name!r} in {path!r} hat die GUID eines Paketspiegels "
                            f"({guid}) -- nicht uebernommen",
                        )
                        continue
                    # Dasselbe Objekt (gleiche GUID): nicht duplizieren, aber die
                    # Tags der Quelle gegen den Zielwert pruefen.
                    element_map[object_id] = existing_id
                    plan.counts["merged"] += 1
                    target_path = target.package_paths.get(
                        _as_int(_Table.get(existing_row, "Package_ID")), path
                    )
                    target_name = _as_text(_Table.get(existing_row, "Name")) or name
                    self._merge_tags(source, object_id, existing_id, target_path, target_name, guid)
                    self._add_xrefs(
                        source,
                        _guid_key(guid),
                        _as_text(_Table.get(existing_row, "ea_guid")) or guid,
                        allow_existing=True,
                        owner=f"Element {target_name!r}",
                    )
                    continue

                # Standard: Gleichheit ueber die ea_guid. Damit bleibt ein
                # Element aus einem frueheren Lauf mit derselben Kennung eine
                # Zeile, und zwei wirklich verschiedene Elemente gleichen
                # Namens bleiben getrennt. ``per_name`` legt zusaetzlich ueber
                # Name+Stereotyp zusammen -- noetig, wenn zwei getrennte Laeufe
                # dasselbe Element unabhaengig angelegt haben.
                same = target.elements.get(key, [])
                match = (
                    next((item for item in same if item[0] == stereotype), None)
                    if self.per_name
                    else None
                )
                if match is None and self.per_name:
                    # Treffer ueber Name + Stereotyp, erster nach Object_ID
                    # (der aelteste Eintrag bleibt stehen).
                    cross = sorted(target.elements_by_name.get(cross_key, []), key=lambda i: i[1])
                    match = (stereotype, cross[0][1]) if cross else None
                if match is not None:
                    # Dasselbe Element liegt schon vor: nicht duplizieren, aber
                    # die Tags der Quelle gegen den Zielwert pruefen.
                    element_map[object_id] = match[1]
                    plan.counts["merged"] += 1
                    self._merge_tags(source, object_id, match[1], path, name, guid)
                    if guid:
                        self._add_xrefs(
                            source,
                            _guid_key(guid),
                            _as_text(_Table.get(target.object_ids.get(match[1], {}), "ea_guid")),
                            allow_existing=True,
                            owner=f"Element {name!r}",
                        )
                    continue

                if same:
                    plan.conflicts.append(
                        {
                            "art": "stereotype",
                            "paket": path,
                            "name": name,
                            "vorhanden": sorted({item[0] for item in same}),
                            "uebernommen": stereotype,
                            "modell": source.index,
                            "datei": source.label,
                        }
                    )

                new_id = target.next_object_id
                target.next_object_id += 1
                new_row = _copy_row(row)
                new_row["object_id"] = new_id
                new_row["package_id"] = target_package
                if "diagram_id" in new_row:
                    new_row["diagram_id"] = 0  # Sichten/Layout werden nicht uebernommen
                if not guid:
                    guid = _stable_guid(
                        f"model_merge|element|{path}|{name}|{stereotype}"
                    )
                    if _guid_key(guid) in target.object_guids:
                        element_map[object_id] = target.object_guids[_guid_key(guid)]
                        plan.counts["merged"] += 1
                        continue
                    _warn(
                        plan.warnings,
                        f"Element {name!r} in {path!r} ohne ea_guid -- "
                        f"deterministische GUID vergeben ({guid})",
                    )
                new_row["ea_guid"] = guid
                position = positions.get(target_package, 0)
                positions[target_package] = position + 1
                if target.tables["t_object"].has("tpos"):
                    new_row["tpos"] = position
                plan.add("t_object", new_row)
                element_map[object_id] = new_id
                target.object_ids[new_id] = new_row
                target.object_guids[_guid_key(guid)] = new_id
                target.elements.setdefault(key, []).append((stereotype, new_id))
                plan.counts["elemente"] += 1

                self._copy_tags(source, object_id, new_id)
                self._copy_attributes(source, object_id, new_id)
                self._add_xrefs(source, _guid_key(guid), guid, allow_existing=False, owner=f"Element {name!r}")
        return element_map

    def _copy_tags(self, source: _Source, object_id: int, new_object_id: int) -> None:
        """Alle Tag-Zeilen eines neu eingefuegten Elements uebernehmen."""
        target = self.target
        plan = self.plan
        index = target.tag_index.setdefault(new_object_id, {})
        for tag in source.tags_by_object.get(object_id, []):
            name = _as_text(_Table.get(tag, "Property", "Name")).strip()
            row = _copy_row(tag)
            row["propertyid"] = target.next_property_id
            target.next_property_id += 1
            row["object_id"] = new_object_id
            plan.add("t_objectproperties", row)
            plan.counts["tags"] += 1
            if name:
                index.setdefault(name, _as_text(_Table.get(tag, "Value")))

    def _merge_tags(
        self,
        source: _Source,
        object_id: int,
        target_object_id: int,
        path: str,
        element_name: str,
        guid: str,
    ) -> None:
        """Tags eines schon vorhandenen Elements: Zielwert gewinnt, Rest ergaenzen."""
        target = self.target
        plan = self.plan
        known = target.tag_index.setdefault(target_object_id, {})
        for tag in source.tags_by_object.get(object_id, []):
            name = _as_text(_Table.get(tag, "Property", "Name")).strip()
            value = _as_text(_Table.get(tag, "Value"))
            if not name:
                continue
            if name in known:
                if known[name] != value:
                    plan.conflicts.append(
                        {
                            "art": "tag",
                            "paket": path,
                            "name": element_name,
                            "tag": name,
                            "ziel": known[name],
                            "quelle": value,
                            "modell": source.index,
                            "datei": source.label,
                        }
                    )
                continue
            row = _copy_row(tag)
            row["propertyid"] = target.next_property_id
            target.next_property_id += 1
            row["object_id"] = target_object_id
            plan.add("t_objectproperties", row)
            plan.counts["tags"] += 1
            known[name] = value

    def _copy_attributes(self, source: _Source, object_id: int, new_object_id: int) -> None:
        """Attribute samt Tags und Constraints eines neuen Elements uebernehmen."""
        target = self.target
        plan = self.plan
        attribute_map: dict[int, int] = {}
        for attribute in source.attributes_by_object.get(object_id, []):
            old_id = _as_int(_Table.get(attribute, "ID"))
            row = _copy_row(attribute)
            row["id"] = target.next_attribute_id
            target.next_attribute_id += 1
            row["object_id"] = new_object_id
            plan.add("t_attribute", row)
            if old_id:
                attribute_map[old_id] = _as_int(row["id"])
        for old_id, new_id in sorted(attribute_map.items()):
            for tag in source.attribute_tags.get(old_id, []):
                row = _copy_row(tag)
                row["propertyid"] = target.next_property_id
                target.next_property_id += 1
                row["elementid"] = new_id
                plan.add("t_attributetag", row)
                plan.counts["tags"] += 1
            for constraint in source.attribute_constraints.get(old_id, []):
                row = _copy_row(constraint)
                row["id"] = new_id
                row["object_id"] = new_object_id
                plan.add("t_attributeconstraints", row)

    # -- Kanten ---------------------------------------------------------
    def connectors(self, source: _Source, object_map: Mapping[int, int]) -> int:
        """Fuegt Kanten ein, deren Endpunkte per GUID im Ziel aufloesbar sind."""
        target = self.target
        plan = self.plan
        inserted = 0
        skipped = 0
        for row in sorted(source.connectors.rows, key=lambda item: _as_int(_Table.get(item, "Connector_ID"))):
            connector_id = _as_int(_Table.get(row, "Connector_ID"))
            guid = _as_text(_Table.get(row, "ea_guid")).strip()
            if guid and _guid_key(guid) in target.connector_guids:
                continue

            start = _as_int(_Table.get(row, "Start_Object_ID"))
            end = _as_int(_Table.get(row, "End_Object_ID"))
            new_start = self._resolve(source, start, object_map)
            new_end = self._resolve(source, end, object_map)
            if new_start is None or new_end is None:
                skipped += 1
                _warn(
                    plan.warnings,
                    f"Kante Connector_ID {connector_id} "
                    f"({_as_text(_Table.get(row, 'Connector_Type'))}) aus {source.label}: "
                    "Endpunkt ist im Ziel nicht per ea_guid aufloesbar -- nicht uebernommen",
                )
                continue

            new_row = _copy_row(row)
            new_row["connector_id"] = target.next_connector_id
            target.next_connector_id += 1
            new_row["start_object_id"] = new_start
            new_row["end_object_id"] = new_end
            if not guid:
                start_guid = _guid_key(source.object_guids.get(start, ""))
                end_guid = _guid_key(source.object_guids.get(end, ""))
                guid = _stable_guid(
                    "model_merge|connector|"
                    f"{start_guid}|{end_guid}|{_as_text(_Table.get(row, 'Connector_Type'))}|"
                    f"{_as_text(_Table.get(row, 'Name'))}"
                )
                if _guid_key(guid) in target.connector_guids:
                    continue  # in einem frueheren Lauf schon uebernommen
                _warn(
                    plan.warnings,
                    f"Kante Connector_ID {connector_id} ohne ea_guid -- "
                    f"deterministische GUID vergeben ({guid})",
                )
            new_row["ea_guid"] = guid
            plan.add("t_connector", new_row)
            target.connector_guids.add(_guid_key(guid))
            inserted += 1
            plan.counts["kanten"] += 1

            for tag in source.connector_tags.get(connector_id, []):
                tag_row = _copy_row(tag)
                tag_row["propertyid"] = target.next_property_id
                target.next_property_id += 1
                tag_row["elementid"] = _as_int(new_row["connector_id"])
                plan.add("t_connectortag", tag_row)
                plan.counts["tags"] += 1
            for constraint in source.connector_constraints.get(connector_id, []):
                constraint_row = _copy_row(constraint)
                constraint_row["connectorid"] = _as_int(new_row["connector_id"])
                plan.add("t_connectorconstraint", constraint_row)
            self._add_xrefs(
                source,
                _guid_key(guid),
                guid,
                allow_existing=False,
                owner=f"Kante {_as_text(_Table.get(row, 'Name'))!r}",
            )
        if skipped:
            _warn(plan.warnings, f"{skipped} Kante(n) aus {source.label} blieben ohne aufloesbaren Endpunkt")
        return inserted

    def _resolve(self, source: _Source, object_id: int, object_map: Mapping[int, int]) -> int | None:
        """Ziel-Object_ID eines Quell-Endpunkts -- ueber die ea_guid, nie ueber IDs.

        Zusaetzlich wird auf den Pfad zurueckgegriffen, wenn zwei Modelle
        dasselbe Element unabhaengig angelegt haben: dann tragen beide
        verschiedene ``ea_guid``, meinen aber dieselbe Sache (gleicher Pfad,
        gleicher Name, gleicher Stereotyp). Ohne diesen Rueckgriff verliert
        eine Kante ihren Endpunkt und faellt stumm weg.
        """
        target = self.target
        mapped = object_map.get(object_id)
        if mapped is not None:
            return mapped
        guid = source.object_guids.get(object_id)
        if guid:
            treffer = target.object_guids.get(_guid_key(guid))
            if treffer is not None:
                return treffer
        return self._resolve_by_path(source, object_id)

    def _resolve_by_path(self, source: _Source, object_id: int) -> int | None:
        """Ziel-Endpunkt ueber (Paketpfad, Name, Stereotyp) suchen.

        Der Index im Ziel waechst weiter, sobald Elemente eingefuegt werden --
        die Indizes sind Paketpfade und Namen, keine temporaeren IDs.
        """
        schluessel = source.identities.get(object_id) if source.identities else None
        if schluessel is None:
            return None
        return self.target.identities.get(_identity_key(*schluessel))


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------


def _insert_rows(
    con: sqlite3.Connection,
    table: _Table,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    """Fuegt Zeilen ein; nur Spalten, die Ziel UND Quelle kennen.

    :returns: (eingefuegte Zeilen, Zahl der Quellspalten, die das Ziel nicht kennt)
    """
    if not rows:
        return 0, 0
    keys: set[str] = set()
    for row in rows:
        keys.update(row.keys())
    known = {column.lower() for column in table.columns}
    columns = [column for column in table.columns if column.lower() in keys]
    if not columns:
        raise MergeError(f"{table.name}: keine gemeinsame Spalte mit dem Ziel -- Abbruch")
    unknown = {
        key
        for key in keys
        if key not in known and key not in _NEVER_COPY
    }
    placeholders = ", ".join("?" for _ in columns)
    sql = (
        f"INSERT INTO {_quote(table.name)} ("
        + ", ".join(_quote(column) for column in columns)
        + f") VALUES ({placeholders})"
    )
    payload = [tuple(row.get(column.lower()) for column in columns) for row in rows]
    _pruefe_zahlenspalten(con, table, columns, payload)
    con.executemany(sql, payload)
    return len(payload), len(unknown)


def _pruefe_zahlenspalten(
    con: sqlite3.Connection,
    table: _Table,
    columns: Sequence[str],
    payload: Sequence[Sequence[Any]],
) -> None:
    """Meldet Text in einer Zielspalte, die laut Schema nur Zahlen aufnimmt.

    Ohne diese Pruefung bricht SQLite mitten im Schreiben mit
    ``datatype mismatch`` ab, ohne Tabelle und Spalte zu nennen. Die Typen
    kommen aus dem Zielschema (``PRAGMA table_info``), nicht aus Spaltennamen --
    ``ea_guid`` endet zwar auf ``id``, ist aber Text.
    """
    typen = {
        str(row[1]).lower(): str(row[2] or "").upper()
        for row in con.execute(f"PRAGMA table_info({_quote(table.name)})")
    }
    zahlenspalten = {column for column in columns if "INT" in typen.get(column.lower(), "")}
    if not zahlenspalten:
        return
    for zeile in payload:
        for column, wert in zip(columns, zeile):
            if column not in zahlenspalten or not isinstance(wert, str):
                continue
            if wert.strip().lstrip("-").isdigit():
                continue
            raise MergeError(
                f"{table.name}.{column}: Zielspalte nimmt Zahlen auf, Quelle liefert "
                f"den Text {wert!r} -- Abbruch vor dem Schreiben"
            )


def _write(plan: _Plan, base_path: Path, out_path: Path, target: _Target) -> None:
    """Basis byte-genau kopieren, Zeilen einfuegen, atomar ersetzen."""
    if plan.total() == 0:
        shutil.copyfile(base_path, out_path)
        os.chmod(out_path, 0o644)
        return

    temporary = out_path.with_name(out_path.name + ".merge-tmp")
    temporary.unlink(missing_ok=True)
    shutil.copyfile(base_path, temporary)
    try:
        con = sqlite3.connect(temporary)
        try:
            con.execute("PRAGMA foreign_keys = OFF")
            with con:
                for name in _WRITE_ORDER:
                    _, unknown = _insert_rows(con, target.tables[name], plan.rows.get(name, []))
                    if unknown:
                        _warn(
                            plan.warnings,
                            f"{name}: Ziel kennt {unknown} Quellspalte(n) nicht -- "
                            "diese Werte werden nicht uebernommen",
                        )
            check = con.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise MergeError(f"{out_path}: SQLite integrity_check fehlgeschlagen ({check!r})")
        finally:
            con.close()
        os.chmod(temporary, 0o644)
        os.replace(temporary, out_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------
# Oeffentliche API
# --------------------------------------------------------------------------


def _container(target: _Target, name: str, plan: _Plan) -> int:
    """Sammelpaket unter der Wurzel: vorhandenes wiederverwenden, sonst anlegen."""
    wanted = name.strip()
    if not wanted:
        raise MergeError("package: darf nicht leer sein")
    existing = target.package_by_path.get(wanted)
    if existing is not None:
        return existing
    candidates = [
        package_id
        for package_id, row in sorted(target.package_ids.items())
        if _as_text(_Table.get(row, "Name")).strip().casefold() == wanted.casefold()
        and _as_int(_Table.get(row, "Parent_ID")) == 0
    ]
    if candidates:
        return candidates[0]

    new_id = target.next_package_id
    target.next_package_id += 1
    guid = _stable_guid(f"model_merge|container|{wanted.casefold()}")
    position = target.next_package_tpos.get(0, 0)
    target.next_package_tpos[0] = position + 1
    row = {
        "package_id": new_id,
        "name": wanted,
        "parent_id": 0,
        "notes": "",
        "ea_guid": guid,
        "createddate": "",
        "modifieddate": "",
        "version": "1.0",
        "tpos": position,
    }
    plan.add("t_package", row)
    plan.counts["pakete"] += 1
    target.package_ids[new_id] = row
    target.package_by_path[wanted] = new_id
    target.package_paths[new_id] = wanted
    target.package_guids[_guid_key(guid)] = new_id
    # Kein Paketspiegel: das Sammelpaket liegt auf der Wurzelebene, und EA
    # fuehrt fuer Wurzelpakete keinen Spiegel (qea_reader warnt sonst).
    return new_id


def merge_models(
    paths: Sequence[str | os.PathLike[str]],
    out: str | os.PathLike[str],
    package: str | None = None,
    *,
    per_name: bool = False,
) -> MergeResult:
    """Fuehrt mehrere .qea zu einem Modell zusammen und schreibt ``out``.

    :param paths: Modelle in Einfuegereihenfolge. ``paths[0]`` ist die Basis:
        ``out`` wird eine byte-genaue Kopie davon.
    :param out: Ergebnisdatei. Wird ueberschrieben (atomar ueber eine
        Nebendatei); die Eingabedateien werden nie veraendert.
    :param per_name: Elemente zusaetzlich ueber Name und Stereotyp zusammenlegen.
        Ohne den Schalter entscheidet allein die ``ea_guid``; zwei getrennte
        Laeufe erzeugen fuer dasselbe Element zwei Kennungen und damit zwei
        Zeilen. Mit dem Schalter bleibt die aeltere Zeile stehen, die
        Beziehungen des zweiten Laufs werden auf sie umgebogen.
    :param package: optionaler Name eines Sammelpakets. Sind mehrere Modelle
        mit gleichem Wurzelnamen unterwegs, verhindert es, dass deren
        Wurzelpakete schon beim Pfadvergleich verschmelzen: die Wurzelpakete
        der weiteren Modelle haengen dann unter diesem Paket. Die GUID bleibt
        staerker als der Pfad -- liegt dieselbe GUID schon im Ziel, wird sie
        nie ein zweites Mal eingefuegt (eine GUID ist eine Identitaet, kein
        Name).
    :returns: :class:`MergeResult` mit Zaehlern und Konfliktliste. Die Zaehler
        nennen neu eingefuegte Zeilen; ein mit ``package`` angelegtes
        Sammelpaket zaehlt mit.
    :raises MergeError: bei fehlenden/unlesbaren Dateien oder gleichem Ziel.
    """
    if not paths:
        raise MergeError("paths: mindestens ein Modell noetig")
    out_path = Path(out)
    sources_in = [Path(path) for path in paths]
    for path in sources_in:
        if not path.is_file():
            raise MergeError(f"{path}: Modell nicht gefunden")
    if out_path.resolve() in {path.resolve() for path in sources_in}:
        raise MergeError(f"{out_path}: Zieldatei ist ein Eingabemodell -- Abbruch")

    base_path = sources_in[0]
    first = _read_source(base_path, 0)
    plan = _Plan(warnings=list(first.warnings))
    target = _read_target(base_path, plan.warnings)
    others: list[_Source] = [_read_source(path, index) for index, path in enumerate(sources_in[1:], start=1)]
    for source in others:
        for message in source.warnings:
            _warn(plan.warnings, f"{source.label}: {message}")

    container_id = 0
    prefix = ""
    if package is not None:
        container_id = _container(target, package, plan)
        prefix = package.strip()

    merger = _Merger(target, plan, per_name=per_name)
    for source in others:
        package_map = merger.packages(source, prefix, container_id)
        object_map = merger.elements(source, package_map)
        merger.connectors(source, object_map)
        if source.diagram_objects:
            _warn(
                plan.warnings,
                f"{source.label}: {source.diagram_objects} Sicht-/Layoutzeilen werden nicht "
                "uebernommen (Sichten und Layout sind nicht Teil des Merges)",
            )
        # Paketspiegel sind Objekte, aber keine Elemente: Endpunkte von Kanten
        # auf Pakete sind ueber die GUID bereits in object_map aufloesbar.

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write(plan, base_path, out_path, target)

    conflicts = sorted(
        plan.conflicts,
        key=lambda item: (
            item["art"],
            item.get("paket", ""),
            item.get("name", ""),
            item.get("tag", ""),
            item.get("modell", 0),
        ),
    )
    warnings = sorted(dict.fromkeys(plan.warnings)) if plan.warnings else []
    return MergeResult(
        written=str(out_path),
        elements=plan.counts["elemente"],
        connections=plan.counts["kanten"],
        conflicts=conflicts,
        packages=plan.counts["pakete"],
        tags=plan.counts["tags"],
        models=len(sources_in),
        merged=plan.counts["merged"],
        warnings=warnings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: Bericht als JSON auf stdout, Fehler auf stderr, Exit 2 bei Fehlern."""
    parser = argparse.ArgumentParser(
        prog="model_merge.py",
        description=(
            "Mehrere .qea zu einem Modell zusammenfuehren; die ea_guid aller "
            "uebernommenen Objekte bleibt woertlich erhalten."
        ),
    )
    parser.add_argument("qea", nargs="+", help="Modelle in Einfuegereihenfolge (erstes = Basis)")
    parser.add_argument("--out", required=True, help="Ergebnisdatei (.qea)")
    parser.add_argument(
        "--per-name",
        action="store_true",
        help="Elemente zusaetzlich ueber Name und Stereotyp zusammenlegen",
    )
    parser.add_argument(
        "--paket",
        default=None,
        metavar="NAME",
        help="optionales Sammelpaket fuer die Wurzelpakete der weiteren Modelle",
    )
    args = parser.parse_args(argv)

    try:
        result = merge_models(args.qea, args.out, package=args.paket, per_name=args.per_name)
    except (MergeError, OSError, sqlite3.Error) as error:
        print(f"model_merge: {error}", file=sys.stderr)
        return 2

    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
