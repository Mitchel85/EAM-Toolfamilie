"""Werkzeugkasten-Merge: externes Standardpaket in ein bestehendes .qea uebernehmen.

Zweck
-----
Ein Modell soll um einen ``Werkzeugkasten`` (Standardelemente, Referenzarchitektur)
aus einer zweiten .qea erweitert werden -- ohne bestehende Elemente zu veraendern.
Kern der Anforderung: die ``ea_guid`` der uebernommenen Elemente bleibt
**woertlich** erhalten. Nur so finden zwei Modelle, die denselben Standard
nutzen, ueber die GUID zusammen (Austausch, Vergleich, Referenzen).

Warum nicht ueber ``qea_writer`` schreiben?
-------------------------------------------
``qea_writer`` ist ein Generator: er baut ein Modell aus IR neu auf und leitet
jede GUID per ``sha256(paketpfad|stereotype|name)`` ab (``guid_for()``); ein
IR-Feld ``guid`` lehnt er ausdruecklich ab. Ein Merge ueber den Writer wuerde
deshalb (a) die geforderte GUID-Identitaet zerstoeren und (b) das vorhandene
Modell komplett neu schreiben. Der Merge arbeitet daher auf einer byte-genauen
Kopie der Zieldatei und fuegt ausschliesslich Zeilen ein -- vorhandene Zeilen
werden nie angefasst. Die Schemakenntnis kommt aus ``qea_writer``
(``AARON_REQUIRED_TABLES``: die 15 Pflichttabellen externer Leser); die
Zieldatei wird gegen diese Liste geprueft.

Regeln
------
* IDs (Package_ID, Object_ID, Connector_ID, PropertyID, Attribut-ID) werden im
  Ziel neu vergeben: hoechste vorhandene ID + 1.
* ``ea_guid`` wird woertlich aus dem Kasten uebernommen (Elemente, Kanten,
  Pakete, Attribute).
* Existiert eine GUID bereits im Ziel, wird das Element uebersprungen und als
  ``bereits_vorhanden`` gezaehlt -- nie ueberschrieben. Das macht den Merge
  idempotent.
* Uebernommen werden: Paketbaum (Eltern-Kind ueber die Original-Parent_ID),
  Paketspiegel samt Paket-Stereotypen (``t_xref`` am Paket-GUID), Elemente,
  Tagged Values aus ``t_objectproperties`` UND ``t_xref``, Attribute
  samt Attribut-Tags/-Constraints, interne Kanten (beide Enden im Kasten) samt
  Kanten-Tags/-Constraints.
* Eine Kante wird uebernommen, wenn ihre ``ea_guid`` im Ziel fehlt UND beide
  Endpunkte im Ziel aufloesbar sind -- egal ob sie in diesem Lauf eingefuegt
  wurden oder schon vorher dort standen. Endpunkte werden ueber ihre ``ea_guid``
  aufgeloest, nicht ueber den Namen. Fehlt ein Endpunkt wirklich, bleibt die
  Kante weg und wird als Warnung gemeldet.
* Kein Loeschen, kein Umbenennen, keine Aenderung bestehender Zeilen.
* Sichten/Diagramme werden nicht uebernommen (kein Layout); Verweise darauf
  werden nicht mitkopiert und als Warnung gemeldet.
* Deterministisch: gleiche Eingaben -> identische Bytes (keine Zeitstempel,
  keine Zufalls-GUIDs, feste Einfuegereihenfolge).

Oeffentliche API
----------------
    merge_toolbox(modell, kasten, ziel, *, paketname="Standard", nur=None) -> dict
    main(argv) -> int

CLI
---
    python3 toolbox_merge.py MODELL.qea KASTEN.qea --out NEU.qea \\
        [--paket Standard] [--nur PaketA --nur PaketB]

Bericht als JSON auf stdout, Klartextfehler auf stderr, Exit 2 bei nicht
lesbarer Datei.
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
from typing import Any, Iterable, Mapping, Sequence

import qea_writer

__all__ = ["ToolboxMergeError", "merge_toolbox", "main"]

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

#: Objekttyp der Paketspiegel in ``t_object`` (kein Element, nur Darstellung).
_PACKAGE_OBJECT_TYPE = "Package"

#: Spalten, die nie aus der Quelle uebernommen werden, weil sie die Identitaet
#: oder den Zielkontext beschreiben (IDs werden neu vergeben).
_NEVER_COPY = frozenset(
    {"package_id", "object_id", "connector_id", "propertyid", "id"}
)

_MAX_WARNINGS = 200


class ToolboxMergeError(ValueError):
    """Eingabe- oder Zustandsfehler. Immer laut, nie still."""


# --------------------------------------------------------------------------
# Kleine Helfer
# --------------------------------------------------------------------------


def _quote(identifier: str) -> str:
    """SQLite-Bezeichner quoten (Namen wie ``Constraint`` sind reserviert)."""
    return '"' + identifier.replace('"', '""') + '"'


def _stable_guid(seed: str) -> str:
    """Deterministische Ersatz-GUID im EA-Format ``{8-4-4-4-12}``.

    Nur fuer Faelle ohne vorhandene GUID (leere ``ea_guid``, neue Sammelpakete,
    ``t_xref.XrefID``). Bewusst dieselbe Formatierung wie
    ``qea_writer._format_guid`` -- die Funktion dort ist privat, deshalb hier
    lokal (kein Eingriff in den Writer).
    """
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


def _connect_ro(path: Path) -> sqlite3.Connection:
    """Oeffnet eine .qea ausschliesslich lesend (URI ``mode=ro``)."""
    if not path.exists():
        raise ToolboxMergeError(f"{path}: Datei nicht gefunden")
    if not path.is_file():
        raise ToolboxMergeError(f"{path}: kein regulaere Datei")
    uri = "file:" + urllib.parse.quote(str(path)) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:  # pragma: no cover - sehr selten
        raise ToolboxMergeError(f"{path}: nicht lesbar ({error})") from error
    con.row_factory = sqlite3.Row
    con.text_factory = str
    try:
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as error:
        con.close()
        raise ToolboxMergeError(f"{path}: keine lesbare .qea ({error})") from error
    return con


def _table_names(con: sqlite3.Connection) -> dict[str, str]:
    """Tatsaechliche Tabellennamen, Schluessel kleingeschrieben."""
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]).lower(): str(row[0]) for row in rows}


class _Table:
    """Gelesene Tabelle: Spaltenliste plus Zeilen mit kleingeschriebenen Schluesseln.

    Kleingeschriebene Schluessel machen den Zugriff unabhaengig davon, ob EA
    ``ea_guid``, ``ea_GUID`` oder ``EA_Guid`` schreibt (die echten Dateien
    variieren hier).
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
            raise ToolboxMergeError(f"Pflicht-Tabelle {name} fehlt in der Datenbank")
        warnings.append(
            f"{name}: Tabelle fehlt -- zugehoerige Inhalte werden nicht uebernommen"
        )
        return _empty_table(name)
    columns = [str(row[1]) for row in con.execute(f"PRAGMA table_info({_quote(actual)})")]
    rows: list[dict[str, Any]] = []
    for raw in con.execute(f"SELECT * FROM {_quote(actual)}"):
        rows.append({column.lower(): raw[index] for index, column in enumerate(columns)})
    return _Table(actual, columns, rows)


def _warn(warnings: list[str], message: str) -> None:
    """Warnung anhaengen, Gesamtzahl begrenzen (kein unbegrenztes Wachstum)."""
    if len(warnings) < _MAX_WARNINGS:
        warnings.append(message)
    elif len(warnings) == _MAX_WARNINGS:
        warnings.append("weitere Warnungen unterdrueckt")


# --------------------------------------------------------------------------
# Kasten lesen
# --------------------------------------------------------------------------


@dataclass
class _Source:
    """Der gelesene Werkzeugkasten (nur die ausgewaehlten Pakete)."""

    path: Path
    packages: _Table
    objects: _Table
    tags: _Table
    xrefs: _Table
    attributes: _Table
    attribute_tags: _Table
    attribute_constraints: _Table
    connectors: _Table
    connector_tags: _Table
    connector_constraints: _Table
    selected: list[int]
    by_id: dict[int, dict[str, Any]]
    objects_by_package: dict[int, list[dict[str, Any]]]
    #: Paketspiegel (Object_Type 'Package') je GUID -- Vorlage fuer neue Spiegel.
    package_objects: dict[str, dict[str, Any]]
    #: Alle Object_IDs der ausgewaehlten Pakete (inkl. Paketspiegel).
    selected_objects: set[int]
    package_mirrors: int
    diagram_objects: int
    warnings: list[str] = field(default_factory=list)


def _tree_order(
    by_id: Mapping[int, Mapping[str, Any]],
    selected: Iterable[int],
) -> list[int]:
    """Ausgewaehlte Pakete in Baumreihenfolge: Eltern vor Kindern, dann Package_ID.

    Zyklen (defekte Modelle) werden abgefangen: bereits besuchte Knoten kommen
    nicht erneut in die Liste.
    """
    wanted = set(selected)

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

    return sorted(wanted, key=lambda pid: (depth(pid), pid))


def _select_packages(
    packages: _Table,
    nur: Sequence[str] | None,
    warnings: list[str],
) -> tuple[list[int], dict[int, dict[str, Any]]]:
    """Auswahl der Kasten-Pakete.

    ``nur=None`` -> alle Pakete. Sonst: die genannten Pakete **samt Unterpaketen**
    (der Kasten wird als Teilbaum verstanden). Ein unbekannter Name ist eine
    Warnung; ist keiner der Namen vorhanden, bricht der Merge ab.
    """
    by_id: dict[int, dict[str, Any]] = {}
    for row in packages.rows:
        package_id = _as_int(_Table.get(row, "Package_ID"))
        if package_id <= 0:
            continue
        by_id[package_id] = row
    if not by_id:
        raise ToolboxMergeError("der Kasten enthaelt kein Paket (t_package ist leer)")

    if nur is None:
        return sorted(by_id), by_id

    wanted_names = [name.strip() for name in nur if _as_text(name).strip()]
    if not wanted_names:
        raise ToolboxMergeError("nur: die Paketliste ist leer")

    roots: list[int] = []
    for name in wanted_names:
        hits = [
            package_id
            for package_id, row in sorted(by_id.items())
            if _as_text(row.get("name")).strip().casefold() == name.casefold()
        ]
        if not hits:
            _warn(warnings, f"Paket {name!r} im Kasten nicht gefunden -- nicht uebernommen")
            continue
        if len(hits) > 1:
            _warn(
                warnings,
                f"Paketname {name!r} ist im Kasten {len(hits)}x vorhanden "
                f"(Package_IDs {hits}) -- alle werden uebernommen",
            )
        roots.extend(hits)
    if not roots:
        raise ToolboxMergeError(
            "keines der Pakete aus 'nur' ist im Kasten vorhanden: "
            + ", ".join(repr(name) for name in wanted_names)
        )

    children: dict[int, list[int]] = defaultdict(list)
    for package_id, row in by_id.items():
        children[_as_int(row.get("parent_id"))].append(package_id)

    chosen: set[int] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in chosen:
            continue
        chosen.add(current)
        stack.extend(children.get(current, []))
    return _tree_order(by_id, chosen), by_id


def _read_source(path: Path, nur: Sequence[str] | None) -> _Source:
    """Liest den Kasten (Pakete, Elemente, Tags, Attribute, Kanten)."""
    warnings: list[str] = []
    con = _connect_ro(path)
    try:
        tables = _table_names(con)
        packages = _read_table(con, tables, "t_package", warnings, required=True)
        objects = _read_table(con, tables, "t_object", warnings, required=True)
        tags = _read_table(con, tables, "t_objectproperties", warnings)
        xrefs = _read_table(con, tables, "t_xref", warnings)
        attributes = _read_table(con, tables, "t_attribute", warnings)
        attribute_tags = _read_table(con, tables, "t_attributetag", warnings)
        attribute_constraints = _read_table(con, tables, "t_attributeconstraints", warnings)
        connectors = _read_table(con, tables, "t_connector", warnings)
        connector_tags = _read_table(con, tables, "t_connectortag", warnings)
        connector_constraints = _read_table(con, tables, "t_connectorconstraint", warnings)
        diagram_objects = 0
        if "t_diagramobjects" in tables:
            row = con.execute(
                f"SELECT count(*) FROM {_quote(tables['t_diagramobjects'])}"
            ).fetchone()
            diagram_objects = _as_int(row[0] if row else 0)
    finally:
        con.close()

    selected, by_id = _select_packages(packages, nur, warnings)
    chosen = set(selected)
    selected_guid_keys = {
        _guid_key(_Table.get(row, "ea_guid"))
        for row in by_id.values()
        if _guid_key(_Table.get(row, "ea_guid"))
    }

    objects_by_package: dict[int, list[dict[str, Any]]] = defaultdict(list)
    package_objects: dict[str, dict[str, Any]] = {}
    selected_objects: set[int] = set()
    mirrors = 0
    for row in sorted(objects.rows, key=lambda item: _as_int(_Table.get(item, "Object_ID"))):
        package_id = _as_int(_Table.get(row, "Package_ID"))
        if package_id not in chosen:
            continue
        selected_objects.add(_as_int(_Table.get(row, "Object_ID")))
        is_package_object = (
            _as_text(_Table.get(row, "Object_Type")).strip().casefold()
            == _PACKAGE_OBJECT_TYPE.casefold()
        )
        if is_package_object:
            # Paketspiegel sind keine Elemente. Sie dienen als Vorlage fuer die
            # Spiegel der neu angelegten Pakete (Stereotyp, Style, PDATA ...).
            key = _guid_key(_Table.get(row, "ea_guid"))
            if key and key in selected_guid_keys:
                package_objects.setdefault(key, row)
            mirrors += 1
            continue
        objects_by_package[package_id].append(row)

    return _Source(
        path=path,
        packages=packages,
        objects=objects,
        tags=tags,
        xrefs=xrefs,
        attributes=attributes,
        attribute_tags=attribute_tags,
        attribute_constraints=attribute_constraints,
        connectors=connectors,
        connector_tags=connector_tags,
        connector_constraints=connector_constraints,
        selected=selected,
        by_id=by_id,
        objects_by_package=dict(objects_by_package),
        package_objects=package_objects,
        selected_objects=selected_objects,
        package_mirrors=mirrors,
        diagram_objects=diagram_objects,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Ziel lesen und Plan bauen
# --------------------------------------------------------------------------


@dataclass
class _Target:
    """Was im Ziel schon da ist (nur gelesen, nie geaendert)."""

    tables: dict[str, _Table]
    package_ids: dict[int, dict[str, Any]]
    object_ids: dict[int, dict[str, Any]]
    package_guids: dict[str, int]
    object_guids: dict[str, int]
    connector_guids: dict[str, int]
    xref_ids: set[str]
    attribute_constraints: set[tuple[str, int]]
    next_package_id: int
    next_object_id: int
    next_connector_id: int
    next_property_id: int
    next_attribute_id: int
    next_tpos: dict[int, int]
    next_object_tpos: dict[int, int]


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


def _read_target(path: Path, warnings: list[str]) -> _Target:
    con = _connect_ro(path)
    try:
        tables = _table_names(con)
        missing = [name for name in qea_writer.AARON_REQUIRED_TABLES if name.lower() not in tables]
        if missing:
            _warn(
                warnings,
                "Zielmodell kennt nicht alle 15 Pflichttabellen externer Leser "
                f"(fehlen: {', '.join(missing)}) -- es wird nur in vorhandene Tabellen geschrieben",
            )
        snapshot: dict[str, _Table] = {}
        for name in _WRITE_ORDER:
            actual = tables.get(name.lower())
            if actual is None:
                _warn(warnings, f"Ziel: Tabelle {name} fehlt -- Inhalte koennen nicht uebernommen werden")
                snapshot[name] = _empty_table(name)
                continue
            columns = [str(row[1]) for row in con.execute(f"PRAGMA table_info({_quote(actual)})")]
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
    # Ohne ea_guid im Ziel ist weder GUID-Erhalt noch Kollisionspruefung moeglich.
    for name, column in (("t_package", "ea_guid"), ("t_object", "ea_guid"), ("t_connector", "ea_guid")):
        if not snapshot[name].has(column):
            _warn(
                warnings,
                f"Ziel: {name} hat keine Spalte {column} -- "
                "GUID-Erhalt und Kollisionspruefung sind nicht moeglich",
            )
    package_guids: dict[str, int] = {}
    for package_id, row in sorted(package_ids.items()):
        key = _guid_key(_Table.get(row, "ea_guid"))
        if key:
            package_guids.setdefault(key, package_id)
    object_guids: dict[str, int] = {}
    for object_id, row in sorted(object_ids.items()):
        key = _guid_key(_Table.get(row, "ea_guid"))
        if key:
            object_guids.setdefault(key, object_id)
    connector_guids: dict[str, int] = {}
    for row in snapshot["t_connector"].rows:
        key = _guid_key(_Table.get(row, "ea_guid"))
        if key:
            connector_guids.setdefault(key, _as_int(_Table.get(row, "Connector_ID")))

    return _Target(
        tables=snapshot,
        package_ids=package_ids,
        object_ids=object_ids,
        package_guids=package_guids,
        object_guids=object_guids,
        connector_guids=connector_guids,
        xref_ids={
            _guid_key(_Table.get(row, "XrefID"))
            for row in snapshot["t_xref"].rows
            if _guid_key(_Table.get(row, "XrefID"))
        },
        attribute_constraints={
            (
                _as_text(_Table.get(row, "Constraint")),
                _as_int(_Table.get(row, "ID")),
            )
            for row in snapshot["t_attributeconstraints"].rows
            if snapshot["t_attributeconstraints"].has("Constraint")
        },
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
        next_tpos=_next_tpos_map(snapshot["t_package"], "Parent_ID"),
        next_object_tpos=_next_tpos_map(snapshot["t_object"], "Package_ID"),
    )


@dataclass
class _MergePlan:
    """Alle einzufuegenden Zeilen plus Bericht."""

    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)

    def add(self, table: str, row: dict[str, Any]) -> None:
        self.rows.setdefault(table, []).append(row)

    def total(self) -> int:
        return sum(len(rows) for rows in self.rows.values())


def _copy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Zeile kopieren, Identitaetsspalten entfernen (werden neu vergeben)."""
    return {key: value for key, value in row.items() if key.lower() not in _NEVER_COPY}


def _build_plan(target: _Target, box: _Source, paketname: str) -> _MergePlan:
    """Baut den Einfuegeplan: Paketbaum, Elemente, Tags, Attribute, Kanten."""
    warnings = list(box.warnings)
    plan = _MergePlan()
    counts = {"pakete": 0, "elemente": 0, "kanten": 0, "tags": 0, "bereits_vorhanden": 0}

    # ---- t_xref (Stereotype/Tagged Values am Objekt) ---------------------
    xrefs_by_client: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(box.xrefs.rows, key=lambda item: _as_text(_Table.get(item, "XrefID"))):
        client = _guid_key(_Table.get(row, "Client"))
        if client:
            xrefs_by_client[client].append(row)

    def add_xrefs(guid: str) -> None:
        """xref-Zeilen eines Objekts uebernehmen (Client bleibt die GUID)."""
        for index, source_row in enumerate(xrefs_by_client.get(_guid_key(guid), [])):
            xref_type = _as_text(_Table.get(source_row, "Type"))
            candidate = _stable_guid(f"toolbox_merge|xref|{_guid_key(guid)}|{xref_type}|{index}")
            suffix = 1
            while _guid_key(candidate) in target.xref_ids:
                candidate = _stable_guid(
                    f"toolbox_merge|xref|{_guid_key(guid)}|{xref_type}|{index}|{suffix}"
                )
                suffix += 1
            target.xref_ids.add(_guid_key(candidate))
            row = _copy_row(source_row)
            row["xrefid"] = candidate
            row["client"] = guid
            plan.add("t_xref", row)
            counts["tags"] += 1

    # ---- Dachpaket -------------------------------------------------------
    wanted = paketname.strip()
    if not wanted:
        raise ToolboxMergeError("paketname: darf nicht leer sein")
    candidates = [
        (package_id, row)
        for package_id, row in sorted(target.package_ids.items())
        if _as_text(_Table.get(row, "Name")).strip().casefold() == wanted.casefold()
    ]
    roots = [(package_id, row) for package_id, row in candidates if _as_int(_Table.get(row, "Parent_ID")) == 0]
    if roots:
        container_id, container_row = roots[0]
    elif candidates:
        container_id, container_row = candidates[0]
        _warn(
            warnings,
            f"Dachpaket {wanted!r} liegt im Ziel nicht auf Wurzelebene -- "
            f"verwendet wird Package_ID {container_id}",
        )
    else:
        container_id = target.next_package_id
        target.next_package_id += 1
        container_row = {
            "package_id": container_id,
            "name": wanted,
            "parent_id": 0,
            "notes": "",
            "ea_guid": _stable_guid(f"toolbox_merge|package|{wanted.casefold()}"),
            "createddate": "",
            "modifieddate": "",
            "version": "1.0",
            "tpos": target.next_tpos.get(0, 0),
        }
        target.next_tpos[0] = target.next_tpos.get(0, 0) + 1
        plan.add("t_package", container_row)
        counts["pakete"] = 0  # Dach zaehlt nicht als Kasten-Paket
    container_id = _as_int(_Table.get(container_row, "Package_ID"), default=container_id)

    # ---- Paketbaum -------------------------------------------------------
    package_map: dict[int, int] = {container_id: container_id}
    #: Quell-Object_ID eines Paketspiegels -> neue Object_ID des Spiegels.
    package_object_map: dict[int, int] = {}
    # Naechste freie Position je Zieleltern; unbekannte Eltern starten bei 0.
    package_positions: dict[int, int] = dict(target.next_tpos)

    for source_id in box.selected:
        source_row = box.by_id[source_id]
        parent_source = _as_int(_Table.get(source_row, "Parent_ID"))
        parent_target = package_map.get(parent_source, container_id)
        guid = _as_text(_Table.get(source_row, "ea_guid")).strip()
        name = _as_text(_Table.get(source_row, "Name"))

        if guid and _guid_key(guid) in target.package_guids:
            existing = target.package_guids[_guid_key(guid)]
            package_map[source_id] = existing
            existing_parent = _as_int(_Table.get(target.package_ids.get(existing, {}), "Parent_ID"))
            if existing_parent != parent_target:
                _warn(
                    warnings,
                    f"Paket {name!r} existiert bereits (GUID {guid}, Package_ID {existing}) "
                    "an anderer Stelle -- wird nicht verschoben",
                )
            continue

        new_id = target.next_package_id
        target.next_package_id += 1
        row = _copy_row(source_row)
        row["package_id"] = new_id
        row["parent_id"] = parent_target
        if not guid:
            guid = _stable_guid(f"toolbox_merge|package|{paketname.casefold()}|{source_id}|{name}")
            _warn(warnings, f"Paket {name!r} ohne ea_guid -- deterministische GUID vergeben ({guid})")
        row["ea_guid"] = guid
        position = package_positions.get(parent_target, 0)
        package_positions[parent_target] = position + 1
        row["tpos"] = position
        plan.add("t_package", row)
        package_map[source_id] = new_id
        target.package_guids[_guid_key(guid)] = new_id
        counts["pakete"] += 1

        # Paketspiegel in t_object (EA-Konvention: jedes Nicht-Wurzelpaket hat
        # eine Package-Zeile im Elternpaket). Gibt es im Kasten einen Spiegel
        # mit derselben GUID, wird dessen Zeile uebernommen (Stereotyp, Style,
        # PDATA bleiben so erhalten), sonst eine minimale Zeile erzeugt.
        mirror_id = target.next_object_id
        target.next_object_id += 1
        source_mirror = box.package_objects.get(_guid_key(guid))
        mirror: dict[str, Any]
        if source_mirror is not None:
            mirror = _copy_row(source_mirror)
        else:
            mirror = {
                "object_type": _PACKAGE_OBJECT_TYPE,
                "name": name,
                "alias": "",
                "note": "",
                "stereotype": _PACKAGE_OBJECT_TYPE,
                "status": "",
                "version": "1.0",
                "createddate": "",
                "modifieddate": "",
            }
        mirror["object_id"] = mirror_id
        mirror["package_id"] = parent_target
        if "diagram_id" in mirror:
            mirror["diagram_id"] = 0  # Sichten werden nicht uebernommen
        mirror["ea_guid"] = guid
        mirror["tpos"] = position
        plan.add("t_object", mirror)
        target.object_guids[_guid_key(guid)] = mirror_id
        if source_mirror is not None:
            package_object_map[_as_int(_Table.get(source_mirror, "Object_ID"))] = mirror_id

        # Paket-Stereotype liegen in t_xref am Paket-GUID.
        add_xrefs(guid)

    # ---- Elemente --------------------------------------------------------
    element_map: dict[int, int] = {}
    element_guid: dict[int, str] = {}
    object_position: dict[int, int] = defaultdict(lambda: 0)
    for parent in list(target.next_object_tpos):
        object_position[parent] = target.next_object_tpos[parent]

    diagram_bound = 0
    for source_id in box.selected:
        for source_row in box.objects_by_package.get(source_id, []):
            object_id = _as_int(_Table.get(source_row, "Object_ID"))
            guid = _as_text(_Table.get(source_row, "ea_guid")).strip()
            name = _as_text(_Table.get(source_row, "Name"))
            if _as_int(_Table.get(source_row, "Diagram_ID")) > 0:
                diagram_bound += 1
            if guid and _guid_key(guid) in target.object_guids:
                counts["bereits_vorhanden"] += 1
                continue

            new_id = target.next_object_id
            target.next_object_id += 1
            row = _copy_row(source_row)
            row["object_id"] = new_id
            row["package_id"] = package_map[source_id]
            if "diagram_id" in row:
                row["diagram_id"] = 0  # Sichten werden nicht uebernommen
            if not guid:
                guid = _stable_guid(
                    f"toolbox_merge|element|{source_id}|{object_id}|{name}"
                )
                _warn(
                    warnings,
                    f"Element {name!r} (Object_ID {object_id}) ohne ea_guid -- "
                    f"deterministische GUID vergeben ({guid})",
                )
            row["ea_guid"] = guid
            position = object_position[package_map[source_id]]
            object_position[package_map[source_id]] = position + 1
            row["tpos"] = position
            plan.add("t_object", row)
            element_map[object_id] = new_id
            element_guid[object_id] = guid
            target.object_guids[_guid_key(guid)] = new_id
            counts["elemente"] += 1

    if diagram_bound:
        _warn(
            warnings,
            f"{diagram_bound} Kasten-Elemente waren auf Sichten platziert -- "
            "Sichten/Layout werden nicht uebernommen (Diagram_ID auf 0 gesetzt)",
        )

    # ---- Tags aus t_objectproperties ------------------------------------
    # Auch Paketspiegel koennen Tagged Values tragen (Paket-Tags in EA).
    tag_owner_map: dict[int, int] = dict(element_map)
    tag_owner_map.update(package_object_map)
    for tag in sorted(box.tags.rows, key=lambda row: _as_int(_Table.get(row, "PropertyID"))):
        owner = _as_int(_Table.get(tag, "Object_ID"))
        if owner not in tag_owner_map:
            continue
        row = _copy_row(tag)
        row["propertyid"] = target.next_property_id
        target.next_property_id += 1
        row["object_id"] = tag_owner_map[owner]
        plan.add("t_objectproperties", row)
        counts["tags"] += 1

    # ---- Tags aus t_xref (Elemente) -------------------------------------
    for source_id in sorted(element_map):
        add_xrefs(element_guid[source_id])

    # ---- Attribute -------------------------------------------------------
    attribute_map: dict[int, int] = {}
    for attribute in sorted(box.attributes.rows, key=lambda row: _as_int(_Table.get(row, "ID"))):
        owner = _as_int(_Table.get(attribute, "Object_ID"))
        if owner not in element_map:
            continue
        old_attribute_id = _as_int(_Table.get(attribute, "ID"))
        row = _copy_row(attribute)
        row["id"] = target.next_attribute_id
        target.next_attribute_id += 1
        row["object_id"] = element_map[owner]
        plan.add("t_attribute", row)
        if old_attribute_id:
            attribute_map[old_attribute_id] = _as_int(row["id"])

    for tag in sorted(box.attribute_tags.rows, key=lambda row: _as_int(_Table.get(row, "PropertyID"))):
        owner = _as_int(_Table.get(tag, "ElementID"))
        if owner not in attribute_map:
            continue
        row = _copy_row(tag)
        row["propertyid"] = target.next_property_id
        target.next_property_id += 1
        row["elementid"] = attribute_map[owner]
        plan.add("t_attributetag", row)
        counts["tags"] += 1

    for constraint in sorted(
        box.attribute_constraints.rows,
        key=lambda row: (_as_int(_Table.get(row, "Object_ID")), _as_text(_Table.get(row, "Constraint"))),
    ):
        owner = _as_int(_Table.get(constraint, "Object_ID"))
        if owner not in element_map:
            continue
        old_id = _as_int(_Table.get(constraint, "ID"))
        if old_id not in attribute_map:
            _warn(
                warnings,
                "Attribut-Constraint "
                f"{_as_text(_Table.get(constraint, 'Constraint'))!r} ohne zugeordnetes "
                "Attribut -- nicht uebernommen",
            )
            continue
        row = _copy_row(constraint)
        row["object_id"] = element_map[owner]
        row["id"] = attribute_map[old_id]
        key = (_as_text(_Table.get(constraint, "Constraint")), attribute_map[old_id])
        if key in target.attribute_constraints:
            _warn(warnings, f"Attribut-Constraint {key[0]!r} existiert bereits -- uebersprungen")
            continue
        target.attribute_constraints.add(key)
        plan.add("t_attributeconstraints", row)

    # ---- Kanten ----------------------------------------------------------
    connector_map: dict[int, int] = {}
    # Endpunkte duerfen auch Paketspiegel sein (z. B. Dependency Paket -> Klasse).
    endpoint_map: dict[int, int] = dict(element_map)
    endpoint_map.update(package_object_map)
    selected_objects = box.selected_objects
    #: Quell-Object_ID -> ea_guid aller Kastenobjekte (Elemente und Paketspiegel).
    #: Endpunkte werden ueber die ea_guid im Ziel aufgeloest: ein Endpunkt kann
    #: schon vor diesem Lauf im Ziel liegen (GUID-Kollision), ist dann aber ein
    #: gueltiger Endpunkt. Der Name ist kein Identitaetsmerkmal.
    source_guids: dict[int, str] = {}
    for row in box.objects.rows:
        object_id = _as_int(_Table.get(row, "Object_ID"))
        guid = _as_text(_Table.get(row, "ea_guid")).strip()
        if object_id in selected_objects and guid:
            source_guids.setdefault(object_id, guid)

    def resolve_endpoint(object_id: int) -> int | None:
        """Ziel-Object_ID eines Kasten-Endpunkts: neu eingefuegt oder vorhanden."""
        if object_id in endpoint_map:
            return endpoint_map[object_id]
        guid = source_guids.get(object_id)
        if not guid:
            return None
        return target.object_guids.get(_guid_key(guid))

    skipped_edges: list[str] = []
    for connector in sorted(box.connectors.rows, key=lambda row: _as_int(_Table.get(row, "Connector_ID"))):
        start = _as_int(_Table.get(connector, "Start_Object_ID"))
        end = _as_int(_Table.get(connector, "End_Object_ID"))
        if start not in selected_objects or end not in selected_objects:
            continue  # Kante verlaesst den Kasten -- nicht Teil des Kastens
        connector_id = _as_int(_Table.get(connector, "Connector_ID"))
        guid = _as_text(_Table.get(connector, "ea_guid")).strip()
        if guid and _guid_key(guid) in target.connector_guids:
            continue  # Kante ist bereits im Ziel -- kein Verlust, keine Warnung
        new_start = resolve_endpoint(start)
        new_end = resolve_endpoint(end)
        if new_start is None or new_end is None:
            # Endpunkt fehlt wirklich im Ziel: Kante auslassen und warnen.
            skipped_edges.append(
                f"Connector_ID {connector_id} ({_as_text(_Table.get(connector, 'Connector_Type'))}): "
                "Endpunkt ist im Ziel nicht aufloesbar (weder in diesem Lauf uebernommen "
                "noch ueber ea_guid vorhanden), Kante fehlt im Ziel"
            )
            continue
        if not guid:
            guid = _stable_guid(f"toolbox_merge|connector|{connector_id}|{start}|{end}")
            _warn(
                warnings,
                f"Kante Connector_ID {connector_id} ohne ea_guid -- deterministische GUID vergeben ({guid})",
            )
        row = _copy_row(connector)
        row["connector_id"] = target.next_connector_id
        target.next_connector_id += 1
        row["start_object_id"] = new_start
        row["end_object_id"] = new_end
        row["ea_guid"] = guid
        plan.add("t_connector", row)
        target.connector_guids[_guid_key(guid)] = _as_int(row["connector_id"])
        connector_map[connector_id] = _as_int(row["connector_id"])
        counts["kanten"] += 1

    for message in skipped_edges[:_MAX_WARNINGS]:
        _warn(warnings, "Kante nicht uebernommen: " + message)
    if len(skipped_edges) > _MAX_WARNINGS:
        _warn(warnings, f"weitere {len(skipped_edges) - _MAX_WARNINGS} Kanten nicht uebernommen")

    for tag in sorted(box.connector_tags.rows, key=lambda row: _as_int(_Table.get(row, "PropertyID"))):
        owner = _as_int(_Table.get(tag, "ElementID"))
        if owner not in connector_map:
            continue
        row = _copy_row(tag)
        row["propertyid"] = target.next_property_id
        target.next_property_id += 1
        row["elementid"] = connector_map[owner]
        plan.add("t_connectortag", row)
        counts["tags"] += 1

    for constraint in sorted(
        box.connector_constraints.rows,
        key=lambda row: (_as_int(_Table.get(row, "ConnectorID")), _as_text(_Table.get(row, "Constraint"))),
    ):
        owner = _as_int(_Table.get(constraint, "ConnectorID"))
        if owner not in connector_map:
            continue
        row = _copy_row(constraint)
        row["connectorid"] = connector_map[owner]
        plan.add("t_connectorconstraint", row)

    plan.report = {
        "pakete": counts["pakete"],
        "elemente": counts["elemente"],
        "kanten": counts["kanten"],
        "tags": counts["tags"],
        "bereits_vorhanden": counts["bereits_vorhanden"],
        "warnungen": warnings,
    }
    return plan


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------


def _insert_rows(
    con: sqlite3.Connection,
    table: _Table,
    rows: Sequence[Mapping[str, Any]],
) -> int:
    """Fuegt Zeilen ein; nur Spalten, die Ziel UND Quelle kennen.

    Fehlende Zielspalten werden nicht erfunden (kein Schema-Umbau); die
    betroffenen Werte meldet der Aufrufer als Warnung.
    """
    if not rows:
        return 0
    keys = set()
    for row in rows:
        keys.update(row.keys())
    columns = [column for column in table.columns if column.lower() in keys]
    if not columns:
        raise ToolboxMergeError(
            f"{table.name}: keine gemeinsame Spalte zwischen Kasten und Ziel -- Abbruch"
        )
    placeholders = ", ".join("?" for _ in columns)
    sql = (
        f"INSERT INTO {_quote(table.name)} ("
        + ", ".join(_quote(column) for column in columns)
        + f") VALUES ({placeholders})"
    )
    payload = [
        tuple(row.get(column.lower()) for column in columns)
        for row in rows
    ]
    con.executemany(sql, payload)
    return len(payload)


def _warn_lost_columns(box: _Source, target: _Target, warnings: list[str]) -> None:
    """Warnt, wenn das Ziel Quellspalten nicht kennt (sonst stiller Wertverlust)."""
    sources = {
        "t_package": box.packages,
        "t_object": box.objects,
        "t_objectproperties": box.tags,
        "t_xref": box.xrefs,
        "t_attribute": box.attributes,
        "t_attributetag": box.attribute_tags,
        "t_attributeconstraints": box.attribute_constraints,
        "t_connector": box.connectors,
        "t_connectortag": box.connector_tags,
        "t_connectorconstraint": box.connector_constraints,
    }
    for name, source in sources.items():
        destination = target.tables.get(name)
        if destination is None or not source.columns or not destination.columns:
            continue
        known = {column.lower() for column in destination.columns}
        lost = sorted(
            column
            for column in source.columns
            if column.lower() not in known and column.lower() not in _NEVER_COPY
        )
        if lost:
            preview = ", ".join(lost[:5]) + (" ..." if len(lost) > 5 else "")
            _warn(
                warnings,
                f"{name}: Ziel kennt {len(lost)} Quellspalten nicht ({preview}) -- "
                "diese Werte werden nicht uebernommen",
            )


def _write(
    plan: _MergePlan,
    model_path: Path,
    out_path: Path,
    target: _Target,
) -> None:
    """Sicherung anlegen, Basis kopieren, Zeilen einfuegen, atomar ersetzen.

    Basis ist die vorhandene Zieldatei (sie ist der aktuelle Modellstand, daher
    die Sicherung); existiert sie noch nicht, wird das Modell kopiert.
    """
    backup_path = out_path.with_suffix(".bak.qea")
    if backup_path == out_path:
        raise ToolboxMergeError(
            f"{out_path}: Zieldatei darf nicht auf .bak.qea enden (Sicherung wuerde sie ueberschreiben)"
        )
    base_path = out_path if out_path.exists() else model_path
    if not base_path.is_file():
        raise ToolboxMergeError(f"{base_path}: Basisdatei nicht lesbar")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base_path, backup_path)

    if plan.total() == 0:
        if base_path != out_path:
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
                    _insert_rows(con, target.tables[name], plan.rows.get(name, []))
            check = con.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise ToolboxMergeError(
                    f"{out_path}: SQLite integrity_check fehlgeschlagen ({check!r})"
                )
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


def merge_toolbox(
    model_qea: str | os.PathLike[str],
    toolbox_qea: str | os.PathLike[str],
    out_qea: str | os.PathLike[str],
    *,
    paketname: str = "Standard",
    nur: Sequence[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Uebernimmt einen Werkzeugkasten in ein Modell und schreibt ``out_qea``.

    :param model_qea: Zielmodell (wird nur gelesen).
    :param toolbox_qea: Kasten mit den Standardelementen (wird nur gelesen).
    :param out_qea: Ergebnis. Existiert die Datei bereits, ist sie der aktuelle
        Modellstand und wird weitergefuehrt; vorher wird sie nach
        ``out_qea.with_suffix('.bak.qea')`` gesichert.
    :param paketname: Dachpaket im Ziel, unter dem der Kasten haengt
        (wird angelegt, falls es fehlt).
    :param nur: Paketnamen aus dem Kasten (samt Unterpaketen); ``None`` = alle.
    :returns: ``{"pakete", "elemente", "kanten", "tags", "bereits_vorhanden",
        "warnungen"}``. ``tags`` zaehlt alle uebernommenen Tag-Zeilen
        (``t_objectproperties``, ``t_xref``, ``t_attributetag``,
        ``t_connectortag``); ``bereits_vorhanden`` zaehlt uebersprungene
        Elemente (GUID schon im Ziel).
    :raises ToolboxMergeError: bei nicht lesbaren Dateien oder ungueltiger Auswahl.
    """
    model_path = Path(model_qea)
    box_path = Path(toolbox_qea)
    out_path = Path(out_qea)

    if model_path.resolve() == box_path.resolve():
        raise ToolboxMergeError("MODELL und KASTEN sind dieselbe Datei")
    if out_path.resolve() == box_path.resolve():
        raise ToolboxMergeError(f"{out_path}: Zieldatei ist der Kasten -- Abbruch")
    if not model_path.exists():
        raise ToolboxMergeError(f"{model_path}: Modell nicht gefunden")
    if not box_path.exists():
        raise ToolboxMergeError(f"{box_path}: Kasten nicht gefunden")

    box = _read_source(box_path, nur)
    # Eine leere Auswahl ist ein Fehler, kein stiller Nichts-Merge.
    if not any(box.objects_by_package.get(package_id) for package_id in box.selected):
        if nur is not None:
            _warn(
                box.warnings,
                "die ausgewaehlten Kasten-Pakete enthalten kein Element -- nur die Paketstruktur wird uebernommen",
            )

    # Basis ist die vorhandene Zieldatei: sie ist der aktuelle Modellstand und
    # wird vor dem Schreiben gesichert. Sonst startet der Merge beim Modell.
    base_path = out_path if out_path.exists() else model_path
    target = _read_target(base_path, box.warnings)
    _warn_lost_columns(box, target, box.warnings)
    plan = _build_plan(target, box, paketname)
    if not dry_run:
        _write(plan, model_path, out_path, target)
    return plan.report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: Bericht als JSON auf stdout, Fehler auf stderr, Exit 2 bei Lesefehler."""
    parser = argparse.ArgumentParser(
        prog="toolbox_merge.py",
        description=(
            "Werkzeugkasten (Standardelemente) aus einer .qea in ein Modell uebernehmen; "
            "die ea_guid der uebernommenen Elemente bleibt woertlich erhalten."
        ),
    )
    parser.add_argument("modell", help="Zielmodell (.qea, wird nur gelesen)")
    parser.add_argument("kasten", help="Werkzeugkasten (.qea, wird nur gelesen)")
    parser.add_argument("--out", required=True, help="Ergebnisdatei (.qea)")
    parser.add_argument(
        "--paket",
        default="Standard",
        metavar="NAME",
        help="Dachpaket im Ziel (Default: Standard)",
    )
    parser.add_argument(
        "--nur",
        action="append",
        default=None,
        metavar="PAKET",
        help="nur dieses Kasten-Paket uebernehmen (mehrfach angebbar)",
    )
    args = parser.parse_args(argv)

    try:
        report = merge_toolbox(
            args.modell,
            args.kasten,
            args.out,
            paketname=args.paket,
            nur=args.nur,
        )
    except (ToolboxMergeError, OSError, sqlite3.Error) as error:
        print(f"toolbox_merge: {error}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
