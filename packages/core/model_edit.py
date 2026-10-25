"""model_edit.py -- gezielte Aenderungen an einer .qea, nachvollziehbar und pruefbar.

Zweck
-----
Ein fertiges Modell soll ohne EA nachgeschaerft werden: Stereotyp setzen, Name,
Notiz, Status oder Alias korrigieren, Tagged Values pflegen, Elemente und Kanten
loeschen oder ergaenzen. Jede Operation nennt ihr Ziel **gezielt** -- entweder
ueber die ``ea_guid`` oder ueber Paketpfad und Name. Damit ist der Eingriff
nachpruefbar und trifft nie "zufaellig das erste Element mit dem Namen".

Grenzen (bewusst)
-----------------
* Das Original wird nie angefasst: gearbeitet wird auf einer Kopie, die am Ende
  atomar an ``out`` gesetzt wird. ``out`` darf nicht das Original sein.
* IDs und ``ea_guid`` bleiben erhalten. Nur neue Zeilen (Tag, Kante) bekommen
  eine neue ID; ihre GUID wird deterministisch aus dem Inhalt abgeleitet, damit
  derselbe Aufruf dieselben Bytes ergibt.
* Kein Layout: Sichten werden weder erzeugt noch veraendert (beim Loeschen eines
  Elements werden nur dessen Sichtverweise entfernt).
* Mit ``--mdg`` wird **jede** Operation gegen das Technologie-Regelwerk geprueft
  (``validator``). Entsteht dadurch ein neuer Fehler, wird die Operation
  abgelehnt und im Bericht genannt -- sie wird nicht geschrieben. Warnungen
  blockieren nicht.
* Vor dem Schreiben laeuft ``PRAGMA integrity_check``; schlaegt er fehl, bleibt
  die Ausgabedatei unberuehrt.

Operationen
-----------
Jede Operation ist ein dict mit ``op`` und einem Ziel (``guid`` **oder**
``package`` + ``name``)::

    {"op": "set_stereotype", "guid": "{...}", "value": "Capability"}
    {"op": "set_name",       "package": "MASC/Katalog", "name": "Alt", "value": "Neu"}
    {"op": "set_note",       "guid": "{...}", "value": "Text"}
    {"op": "set_status",     "guid": "{...}", "value": "Proposed"}
    {"op": "set_alias",      "guid": "{...}", "value": "Kurzname"}
    {"op": "add_tag",        "guid": "{...}", "name_tag": "Quelle", "value": "intern"}
    {"op": "remove_tag",     "guid": "{...}", "name_tag": "Quelle"}
    {"op": "delete_element", "guid": "{...}"}
    {"op": "add_connector",  "source": "{...}", "target": "{...}",
                             "stereotype": "Exhibits", "ea_type": "Dependency", "name": ""}
    {"op": "delete_connector", "guid": "{...}"}

Fuer ``add_tag``/``remove_tag`` heisst das Tag-Feld ``tag`` (Alias ``name_tag``),
damit ``name`` weiter das Element meint. Endpunkte einer Kante duerfen als
``{"guid": ...}``, als ``{"package": ..., "name": ...}`` oder als Text
``"paket/unterpaket::Elementname"`` angegeben werden; ein nackter Name ist nur
zulaessig, wenn er im ganzen Modell eindeutig ist.

Oeffentliche API
----------------
    edit_model(path, ops, out, *, mdg=None) -> EditResult
    main(argv) -> int

CLI
---
    python3 model_edit.py MODELL.qea --ops ops.json --out NEU.qea [--mdg MDG.xml]
    eam-ai edit --qea MODELL.qea --ops ops.json --out NEU.qea [--mdg MDG.xml]

Exit-Codes: 0 = alle Operationen angewendet, 1 = mindestens eine abgelehnt
(Ergebnisdatei trotzdem geschrieben), 2 = technischer Fehler (nichts geschrieben).
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

import mdg_parser
import qea_reader
import validator

__all__ = ["EditError", "EditResult", "edit_model", "main"]

#: Erlaubte Operationen.
OPERATIONS: tuple[str, ...] = (
    "set_stereotype",
    "set_name",
    "set_note",
    "set_status",
    "set_alias",
    "add_tag",
    "remove_tag",
    "delete_element",
    "add_connector",
    "delete_connector",
)

#: Einfache Feldoperationen: op -> Spalte in ``t_object``.
_SIMPLE_FIELDS: dict[str, str] = {
    "set_name": "Name",
    "set_note": "Note",
    "set_status": "Status",
    "set_alias": "Alias",
}

#: Spalten, die eine Elementzeile nie verlieren darf.
_ELEMENT_REQUIRED = ("Object_ID", "Package_ID", "Name", "ea_guid")

_STEREO_ROW_NAME = "Stereotypes"
_CUSTOM_ROW_NAME = "CustomProperties"
_ELEMENT_XREF = "element property"
_CONNECTOR_XREF = "connector property"

_PROP_PREFIX = "@PROP="
_NAME_MARK = "@NAME="
_NAME_END = "@ENDNAME;"
_TYPE_MARK = "@TYPE="
_TYPE_END = "@ENDTYPE;"
_VALU_MARK = "@VALU="
_VALU_END = "@ENDVALU;"
_PROP_TAIL = "@PRMT=@ENDPRMT;@ENDPROP;"

_MAX_WARNINGS = 200


class EditError(ValueError):
    """Eingabe- oder Zustandsfehler. Immer laut, nie still."""


class _Reject(Exception):
    """Eine einzelne Operation ist unzulaessig -- der Lauf geht weiter."""


@dataclass
class EditResult:
    """Ergebnis eines Bearbeitungslaufs."""

    #: Pfad der geschriebenen Datei.
    written: str
    #: Zahl der angewendeten Operationen.
    applied: int
    #: Abgelehnte Operationen, je ein dict mit ``op``, ``typ``, ``ziel``, ``grund``.
    rejected: list[dict[str, Any]] = field(default_factory=list)
    #: Zahl der eingereichten Operationen.
    ops: int = 0
    #: Regelwerk, gegen das geprueft wurde (leer = keine MDG-Pruefung).
    mdg: str = ""
    #: Kurzprotokoll der angewendeten Operationen (in Reihenfolge).
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Kanonischer Bericht: sortierte Schluessel, keine Zeitstempel."""
        return {
            "geschrieben": self.written,
            "operationen": self.ops,
            "angewendet": self.applied,
            "abgelehnt": self.rejected,
            "aenderungen": self.changes,
            "mdg": self.mdg,
            "warnungen": self.warnings,
        }


# --------------------------------------------------------------------------
# Kleine Helfer
# --------------------------------------------------------------------------


def _quote(identifier: str) -> str:
    """SQLite-Bezeichner quoten."""
    return '"' + identifier.replace('"', '""') + '"'


def _stable_guid(seed: str) -> str:
    """Deterministische GUID im EA-Format ``{8-4-4-4-12}``."""
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
        raise EditError(f"{path}: Datei nicht gefunden")
    if not path.is_file():
        raise EditError(f"{path}: keine regulaere Datei")
    uri = "file:" + urllib.parse.quote(str(path)) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:  # pragma: no cover - sehr selten
        raise EditError(f"{path}: nicht lesbar ({error})") from error
    con.row_factory = sqlite3.Row
    con.text_factory = str
    try:
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as error:
        con.close()
        raise EditError(f"{path}: keine lesbare .qea ({error})") from error
    return con


def _table_names(con: sqlite3.Connection) -> dict[str, str]:
    """Tatsaechliche Tabellennamen, Schluessel kleingeschrieben."""
    return {
        str(row[0]).lower(): str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info({_quote(table)})")]


def _column(columns: Sequence[str], *names: str) -> str | None:
    """Erste vorhandene Spalte (Namen case-insensitiv)."""
    lowered = {column.lower(): column for column in columns}
    for name in names:
        hit = lowered.get(name.lower())
        if hit is not None:
            return hit
    return None


def _require_column(columns: Sequence[str], table: str, *names: str) -> str:
    hit = _column(columns, *names)
    if hit is None:
        raise EditError(f"{table}: Spalte {'/'.join(names)} fehlt -- Aenderung nicht moeglich")
    return hit


def _max_int(con: sqlite3.Connection, table: str, column: str) -> int:
    row = con.execute(f"SELECT max({_quote(column)}) FROM {_quote(table)}").fetchone()
    return _as_int(row[0] if row else 0)


def _row_get(row: Mapping[str, Any], *names: str) -> Any:
    """Erster vorhandener Spaltenwert einer Zeile (fehlende Spalten sind kein Fehler)."""
    for name in names:
        try:
            return row[name]
        except (IndexError, KeyError):
            continue
    return None


# --------------------------------------------------------------------------
# Journal: jede Aenderung ist umkehrbar
# --------------------------------------------------------------------------


class _Journal:
    """Merkt sich Vorher-Bilder, damit eine abgelehnte Operation zurueckgenommen wird.

    Ruecknahme heisst: die betroffenen Zeilen werden ueber ihre ``rowid``
    geloescht und mit allen Spalten wieder eingesetzt. Damit ist auch eine
    geloeschte Zeile exakt wiederhergestellt (gleiche ID, gleiche GUID).
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        #: (Tabelle, rowid, (Spalten, Werte) oder None fuer eine neue Zeile)
        self.entries: list[tuple[str, int, tuple[list[str], tuple[Any, ...]] | None]] = []

    def _snapshot(self, table: str, rowid: int) -> tuple[list[str], tuple[Any, ...]] | None:
        cursor = self.con.execute(
            f"SELECT rowid AS __rowid, * FROM {_quote(table)} WHERE rowid = ?", (rowid,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        keys = [description[0] for description in cursor.description]
        return keys[1:], tuple(row[1:])

    def update(self, table: str, rowid: int, values: Mapping[str, Any]) -> None:
        self.entries.append((table, rowid, self._snapshot(table, rowid)))
        assignments = ", ".join(f"{_quote(column)} = ?" for column in values)
        self.con.execute(
            f"UPDATE {_quote(table)} SET {assignments} WHERE rowid = ?",
            (*values.values(), rowid),
        )

    def insert(self, table: str, values: Mapping[str, Any]) -> int:
        columns = list(values)
        cursor = self.con.execute(
            f"INSERT INTO {_quote(table)} ("
            + ", ".join(_quote(column) for column in columns)
            + ") VALUES ("
            + ", ".join("?" for _ in columns)
            + ")",
            tuple(values[column] for column in columns),
        )
        rowid = _as_int(cursor.lastrowid)
        self.entries.append((table, rowid, None))
        return rowid

    def delete(self, table: str, rowid: int) -> None:
        self.entries.append((table, rowid, self._snapshot(table, rowid)))
        self.con.execute(f"DELETE FROM {_quote(table)} WHERE rowid = ?", (rowid,))

    def restore(self) -> None:
        """Alle gemerkten Zeilen in umgekehrter Reihenfolge zuruecksetzen."""
        for table, rowid, snapshot in reversed(self.entries):
            self.con.execute(f"DELETE FROM {_quote(table)} WHERE rowid = ?", (rowid,))
            if snapshot is None:
                continue
            columns, values = snapshot
            self.con.execute(
                f"INSERT INTO {_quote(table)} (rowid, "
                + ", ".join(_quote(column) for column in columns)
                + ") VALUES ("
                + ", ".join("?" for _ in range(len(columns) + 1))
                + ")",
                (rowid, *values),
            )
        self._reset_sequences()
        self.entries.clear()

    def _reset_sequences(self) -> None:
        """Zaehler von AUTOINCREMENT-Tabellen zurueck auf den echten Hoechstwert.

        Ohne das bliebe nach einer abgelehnten Operation eine Luecke in
        ``sqlite_sequence`` zurueck: die Datei waere dann nicht mehr Byte fuer
        Byte dieselbe wie ein Lauf ohne diese Operation.
        """
        tables = sorted({table for table, _, _ in self.entries})
        if not tables:
            return
        if not self.con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
        ).fetchone():
            return
        for table in tables:
            if not self.con.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)
            ).fetchone():
                continue
            row = self.con.execute(f"SELECT max(rowid) FROM {_quote(table)}").fetchone()
            highest = _as_int(row[0]) if row else 0
            if highest:
                self.con.execute(
                    "UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (highest, table)
                )
            else:
                self.con.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))


# --------------------------------------------------------------------------
# Zustand eines Modells (Index fuer gezieltes Finden)
# --------------------------------------------------------------------------


@dataclass
class _Element:
    """Ein Element (kein Paketspiegel) mit den Feldern, die Operationen brauchen."""

    rowid: int
    object_id: int
    package_id: int
    name: str
    stereotype: str
    guid: str
    note: str = ""
    status: str = ""
    alias: str = ""


class _Model:
    """Lesender Blick auf die Arbeitskopie plus Schreiboperationen."""

    def __init__(self, con: sqlite3.Connection, path: Path):
        self.con = con
        self.path = path
        self.tables = _table_names(con)
        for name in ("t_object", "t_package", "t_connector"):
            if name not in self.tables:
                raise EditError(f"{path}: Pflicht-Tabelle {name} fehlt")
        self.object_table = self.tables["t_object"]
        self.package_table = self.tables["t_package"]
        self.connector_table = self.tables["t_connector"]
        self.object_columns = _columns(con, self.object_table)
        self.package_columns = _columns(con, self.package_table)
        self.connector_columns = _columns(con, self.connector_table)
        self.property_table = self.tables.get("t_objectproperties")
        self.xref_table = self.tables.get("t_xref")
        self.attribute_table = self.tables.get("t_attribute")
        self.diagram_object_table = self.tables.get("t_diagramobjects")
        self.diagram_link_table = self.tables.get("t_diagramlinks")
        self.profile = self._dominant_profile()
        self.package_paths = self._package_paths()

    # -- Indexe ---------------------------------------------------------
    def _package_paths(self) -> dict[int, str]:
        rows = {
            _as_int(row["Package_ID"]): row
            for row in self.con.execute(f"SELECT * FROM {_quote(self.package_table)}")
        }
        paths: dict[int, str] = {}

        def path_of(package_id: int) -> str:
            if package_id in paths:
                return paths[package_id]
            segments: list[str] = []
            seen: set[int] = set()
            current = package_id
            while current in rows and current not in seen:
                seen.add(current)
                segments.append(_as_text(rows[current]["Name"]).strip())
                current = _as_int(rows[current]["Parent_ID"])
            result = "/".join(reversed(segments))
            paths[package_id] = result
            return result

        for package_id in rows:
            path_of(package_id)
        return paths

    def _dominant_profile(self) -> str:
        """Haeufigstes Technologieprofil aus den Stereotype-Zeilen (wie qea_reader)."""
        if self.xref_table is None:
            return ""
        columns = _columns(self.con, self.xref_table)
        description = _column(columns, "Description")
        xref_type = _column(columns, "Type")
        if description is None or xref_type is None:
            return ""
        counts: dict[str, int] = defaultdict(int)
        for row in self.con.execute(
            f"SELECT {_quote(xref_type)}, {_quote(description)} FROM {_quote(self.xref_table)}"
        ):
            if _as_text(row[0]).strip().lower() != _ELEMENT_XREF:
                continue
            text = _as_text(row[1])
            if not text.startswith("@STEREO;"):
                continue
            marker = "FQName="
            start = text.find(marker)
            if start < 0:
                continue
            start += len(marker)
            end = text.find(";", start)
            fqname = text[start:end] if end >= 0 else text[start:]
            if "::" in fqname:
                prefix = fqname.rsplit("::", 1)[0].strip()
                if prefix:
                    counts[prefix] += 1
        if not counts:
            return ""
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    # -- Finden ---------------------------------------------------------
    def element(self, op: Mapping[str, Any]) -> _Element:
        """Zielelement einer Operation: ueber GUID oder Paketpfad + Name."""
        guid = _as_text(op.get("guid")).strip()
        if guid:
            row = self.con.execute(
                f"SELECT rowid AS __rowid, * FROM {_quote(self.object_table)}"
                " WHERE upper(ea_guid) = upper(?) COLLATE NOCASE",
                (guid,),
            ).fetchone()
            if row is None:
                raise _Reject(f"kein Element mit ea_guid {guid}")
            if _as_text(row["Object_Type"]).strip().casefold() == "package":
                raise _Reject(f"ea_guid {guid} gehoert zu einem Paketspiegel, nicht zu einem Element")
            return self._to_element(row)

        package = _as_text(op.get("package")).strip().strip("/")
        name = _as_text(op.get("name"))
        if not package or not name:
            raise _Reject("Ziel fehlt: 'guid' oder 'package' + 'name' erwartet")
        package_ids = sorted(
            package_id for package_id, path in self.package_paths.items() if path == package
        )
        if not package_ids:
            raise _Reject(f"Paket {package!r} existiert nicht")
        if len(package_ids) > 1:
            raise _Reject(f"Paketpfad {package!r} ist nicht eindeutig ({len(package_ids)} Pakete)")
        rows = self.con.execute(
            f"SELECT rowid AS __rowid, * FROM {_quote(self.object_table)}"
            " WHERE Package_ID = ? AND Name = ?"
            " AND coalesce(Object_Type, '') <> 'Package' COLLATE NOCASE"
            " ORDER BY Object_ID",
            (package_ids[0], name),
        ).fetchall()
        if not rows:
            raise _Reject(f"kein Element {name!r} in Paket {package!r}")
        if len(rows) > 1:
            raise _Reject(
                f"Element {name!r} in Paket {package!r} ist nicht eindeutig "
                f"({len(rows)} Elemente) -- bitte 'guid' angeben"
            )
        return self._to_element(rows[0])

    def _to_element(self, row: Mapping[str, Any]) -> _Element:
        return _Element(
            rowid=_as_int(_row_get(row, "__rowid")),
            object_id=_as_int(_row_get(row, "Object_ID")),
            package_id=_as_int(_row_get(row, "Package_ID")),
            name=_as_text(_row_get(row, "Name")),
            stereotype=_as_text(_row_get(row, "Stereotype")),
            guid=_as_text(_row_get(row, "ea_guid")).strip(),
            note=_as_text(_row_get(row, "Note", "Notes")),
            status=_as_text(_row_get(row, "Status")),
            alias=_as_text(_row_get(row, "Alias")),
        )

    def connector(self, op: Mapping[str, Any]) -> dict[str, Any]:
        """Zielkante: ueber GUID oder ueber Name plus Endpunkte."""
        guid = _as_text(op.get("guid")).strip()
        if guid:
            row = self.con.execute(
                f"SELECT rowid AS __rowid, * FROM {_quote(self.connector_table)}"
                " WHERE upper(ea_guid) = upper(?) COLLATE NOCASE",
                (guid,),
            ).fetchone()
            if row is None:
                raise _Reject(f"keine Kante mit ea_guid {guid}")
            return dict(row)
        name = _as_text(op.get("name"))
        rows = self.con.execute(
            f"SELECT rowid AS __rowid, * FROM {_quote(self.connector_table)}"
            " WHERE coalesce(Name, '') = ?",
            (name,),
        ).fetchall()
        if not rows:
            raise _Reject(f"keine Kante mit Name {name!r}")
        if len(rows) > 1:
            raise _Reject(
                f"Kante {name!r} ist nicht eindeutig ({len(rows)} Kanten) -- bitte 'guid' angeben"
            )
        return dict(rows[0])

    def endpoint(self, raw: Any, what: str) -> _Element:
        """Endpunkt einer neuen Kante: GUID, Element-dict oder ``pfad::name``."""
        if isinstance(raw, Mapping):
            return self.element(raw)
        text = _as_text(raw).strip()
        if not text:
            raise _Reject(f"{what}: Ziel fehlt")
        if text.startswith("{"):
            return self.element({"guid": text})
        if "::" in text:
            package, _, name = text.rpartition("::")
            return self.element({"package": package, "name": name})
        # Nackter Name: nur zulaessig, wenn er im ganzen Modell eindeutig ist.
        rows = self.con.execute(
            f"SELECT rowid AS __rowid, * FROM {_quote(self.object_table)}"
            " WHERE Name = ? AND coalesce(Object_Type, '') <> 'Package' COLLATE NOCASE",
            (text,),
        ).fetchall()
        if not rows:
            raise _Reject(f"{what}: kein Element {text!r}")
        if len(rows) > 1:
            raise _Reject(f"{what}: Name {text!r} ist nicht eindeutig -- Paketpfad angeben")
        return self._to_element(rows[0])


# --------------------------------------------------------------------------
# Operationen
# --------------------------------------------------------------------------


def _value_text(op: Mapping[str, Any], *, what: str = "value", allow_empty: bool = True) -> str:
    """Prueft ein Textfeld der Operation."""
    if "value" not in op:
        raise _Reject(f"Feld 'value' fehlt ({what})")
    value = op["value"]
    if not isinstance(value, str):
        raise _Reject(f"Feld 'value' muss Text sein, gefunden {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise _Reject(f"Feld 'value' darf nicht leer sein ({what})")
    return value


def _describe_prop(name: str, value: str, type_name: str = "string") -> str:
    """``@PROP=``-Block wie EA ihn in ``t_xref.Description`` ablegt."""
    return (
        f"{_PROP_PREFIX}{_NAME_MARK}{name}{_NAME_END}"
        f"{_TYPE_MARK}{type_name}{_TYPE_END}"
        f"{_VALU_MARK}{value}{_VALU_END}{_PROP_TAIL}"
    )


def _profile_from_description(description: str) -> str:
    """Liest das Profilpraefix aus ``@STEREO;Name=X;FQName=Profil::X;``."""
    marker = "FQName="
    start = description.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = description.find(";", start)
    fqname = description[start:end] if end >= 0 else description[start:]
    if "::" not in fqname:
        return ""
    return fqname.rsplit("::", 1)[0].strip()


def _parse_prop(description: str) -> tuple[str, str]:
    """Liest ``@NAME=`` und ``@VALU=`` aus einer ``@PROP=``-Zeile."""
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
    if vstart < 0:
        return name, ""
    vstart += len(_VALU_MARK)
    vend = description.find(_VALU_END, vstart)
    return name, (description[vstart:vend] if vend >= 0 else description[vstart:])


class _Editor:
    """Wendet Operationen auf die Arbeitskopie an (jede einzeln journalisiert)."""

    def __init__(self, model: _Model):
        self.model = model
        self.con = model.con
        self.warnings: list[str] = []

    # -- Hilfen fuer Tag-Zeilen ----------------------------------------
    def _property_columns(self) -> tuple[str, str, str | None]:
        table = self.model.property_table
        if table is None:
            raise _Reject("Tabelle t_objectproperties fehlt -- Tagged Values nicht bearbeitbar")
        columns = _columns(self.con, table)
        name = _require_column(columns, table, "Property", "Name")
        value = _require_column(columns, table, "Value")
        notes = _column(columns, "Notes")
        return name, value, notes

    def _tag_rows(self, object_id: int, name: str) -> list[sqlite3.Row]:
        table = self.model.property_table
        if table is None:
            return []
        name_column, _, _ = self._property_columns()
        return self.con.execute(
            f"SELECT rowid AS __rowid, * FROM {_quote(table)}"
            f" WHERE Object_ID = ? AND coalesce({_quote(name_column)}, '') = ?"
            " COLLATE NOCASE ORDER BY PropertyID",
            (object_id, name),
        ).fetchall()

    def _stereotype_row(self, guid: str) -> sqlite3.Row | None:
        table = self.model.xref_table
        if table is None or not guid:
            return None
        columns = _columns(self.con, table)
        client = _require_column(columns, table, "Client")
        description = _require_column(columns, table, "Description")
        name_column = _column(columns, "Name")
        type_column = _column(columns, "Type")
        rows = self.con.execute(
            f"SELECT rowid AS __rowid, * FROM {_quote(table)}"
            f" WHERE {_quote(client)} = ? COLLATE NOCASE",
            (guid,),
        ).fetchall()
        for row in rows:
            if name_column is not None and _as_text(row[name_column]).strip().casefold() != _STEREO_ROW_NAME.casefold():
                continue
            if type_column is not None and _as_text(row[type_column]).strip().lower() != _ELEMENT_XREF:
                continue
            if _as_text(row[description]).startswith("@STEREO;"):
                return row
        return None

    # -- Anwenden -------------------------------------------------------
    def apply(self, op: Mapping[str, Any], index: int, journal: _Journal) -> str:
        """Fuehrt eine Operation aus; liefert eine kurze Beschreibung."""
        if not isinstance(op, Mapping):
            raise _Reject("Operation muss ein JSON-Objekt sein")
        kind = _as_text(op.get("op")).strip()
        if not kind:
            raise _Reject("Feld 'op' fehlt")
        if kind not in OPERATIONS:
            raise _Reject(f"unbekannte Operation {kind!r} (erlaubt: {', '.join(OPERATIONS)})")

        handler = getattr(self, f"_op_{kind}")
        return handler(op, index, journal)

    def _op_set_stereotype(self, op, index, journal) -> str:
        element = self.model.element(op)
        value = _value_text(op).strip()
        journal.update(self.model.object_table, element.rowid, {"Stereotype": value})
        self._write_stereotype_xref(element, value, op, journal)
        return f"Stereotyp {element.name!r}: {element.stereotype!r} -> {value!r}"

    def _write_stereotype_xref(self, element: _Element, value: str, op, journal: _Journal) -> None:
        """Haelt die ``@STEREO;``-Zeile in ``t_xref`` mit der Stereotyp-Spalte synchron."""
        table = self.model.xref_table
        if table is None:
            return
        row = self._stereotype_row(element.guid)
        if not value:
            if row is not None:
                journal.delete(table, _as_int(row["__rowid"]))
            return
        profile = _as_text(op.get("profile")).strip()
        if not profile and row is not None:
            # Ein vorhandenes FQName-Praefix bleibt erhalten; sonst wuerde ein
            # Stereotypwechsel stillschweigend das Profil wechseln.
            profile = _profile_from_description(_as_text(row["Description"]))
        if not profile:
            profile = self.model.profile
        fqname = f"FQName={profile}::{value};" if profile else ""
        description = f"@STEREO;Name={value};{fqname}@ENDSTEREO;"
        if row is not None:
            columns = _columns(self.con, table)
            description_column = _require_column(columns, table, "Description")
            journal.update(table, _as_int(row["__rowid"]), {description_column: description})
            return
        values = self._new_xref_values(
            client=element.guid,
            name=_STEREO_ROW_NAME,
            xref_type=_ELEMENT_XREF,
            description=description,
            seed=f"model_edit|stereotype|{_guid_key(element.guid)}|{value}",
        )
        journal.insert(table, values)

    def _new_xref_values(
        self,
        *,
        client: str,
        name: str,
        xref_type: str,
        description: str,
        seed: str,
    ) -> dict[str, Any]:
        """Vollstaendige ``t_xref``-Zeile mit determinstischer neuer XrefID."""
        table = self.model.xref_table
        assert table is not None
        columns = _columns(self.con, table)
        values: dict[str, Any] = {
            _require_column(columns, table, "XrefID"): self._free_guid(table, "XrefID", seed),
            _require_column(columns, table, "Client"): client,
            _require_column(columns, table, "Description"): description,
        }
        if (hit := _column(columns, "Name")) is not None:
            values[hit] = name
        if (hit := _column(columns, "Type")) is not None:
            values[hit] = xref_type
        return values

    def _free_guid(self, table: str, column: str, seed: str) -> str:
        """Deterministische GUID, die in ``table.column`` noch nicht vorkommt."""
        candidate = _stable_guid(seed)
        suffix = 1
        while self.con.execute(
            f"SELECT 1 FROM {_quote(table)} WHERE upper({_quote(column)}) = upper(?) LIMIT 1",
            (candidate,),
        ).fetchone():
            candidate = _stable_guid(f"{seed}|{suffix}")
            suffix += 1
        return candidate

    def _op_set_name(self, op, index, journal) -> str:
        element = self.model.element(op)
        value = _value_text(op, allow_empty=False)
        if "::" in value:
            raise _Reject("Name darf '::' nicht enthalten (IR-Referenzen waeren nicht darstellbar)")
        journal.update(self.model.object_table, element.rowid, {"Name": value})
        return f"Name: {element.name!r} -> {value!r}"

    def _op_set_note(self, op, index, journal) -> str:
        element = self.model.element(op)
        value = _value_text(op)
        journal.update(self.model.object_table, element.rowid, {"Note": value})
        return f"Notiz von {element.name!r} gesetzt ({len(value)} Zeichen)"

    def _op_set_status(self, op, index, journal) -> str:
        element = self.model.element(op)
        value = _value_text(op)
        journal.update(self.model.object_table, element.rowid, {"Status": value})
        return f"Status {element.name!r}: {element.status!r} -> {value!r}"

    def _op_set_alias(self, op, index, journal) -> str:
        element = self.model.element(op)
        value = _value_text(op)
        journal.update(self.model.object_table, element.rowid, {"Alias": value})
        return f"Alias {element.name!r}: {element.alias!r} -> {value!r}"

    def _tag_name(self, op) -> str:
        raw = op.get("tag", op.get("name_tag", op.get("property")))
        name = _as_text(raw).strip()
        if not name:
            raise _Reject("Feld 'tag' fehlt (Name des Tagged Value)")
        return name

    def _op_add_tag(self, op, index, journal) -> str:
        element = self.model.element(op)
        tag = self._tag_name(op)
        value = _value_text(op)
        name_column, value_column, notes_column = self._property_columns()
        table = self.model.property_table
        assert table is not None

        rows = self._tag_rows(element.object_id, tag)
        if rows:
            row = rows[0]
            journal.update(table, _as_int(row["__rowid"]), {value_column: value})
            for duplicate in rows[1:]:
                journal.delete(table, _as_int(duplicate["__rowid"]))
            action = "aktualisiert"
        else:
            columns = _columns(self.con, table)
            values: dict[str, Any] = {
                _require_column(columns, table, "PropertyID"): _max_int(
                    self.con, table, "PropertyID"
                )
                + 1,
                _require_column(columns, table, "Object_ID"): element.object_id,
                name_column: tag,
                value_column: value,
            }
            if notes_column is not None and ("notes" in op):
                values[notes_column] = _as_text(op.get("notes"))
            if (guid_column := _column(columns, "ea_guid")) is not None:
                values[guid_column] = self._free_guid(
                    table, guid_column, f"model_edit|tag|{_guid_key(element.guid)}|{tag}"
                )
            journal.insert(table, values)
            action = "angelegt"

        self._sync_custom_property(element, tag, value, op, journal)
        return f"Tag {tag!r} bei {element.name!r} {action}"

    def _op_remove_tag(self, op, index, journal) -> str:
        element = self.model.element(op)
        tag = self._tag_name(op)
        table = self.model.property_table
        assert table is not None
        rows = self._tag_rows(element.object_id, tag)
        removed = 0
        for row in rows:
            journal.delete(table, _as_int(row["__rowid"]))
            removed += 1
        removed += self._remove_custom_property(element, tag, journal)
        if not removed:
            raise _Reject(f"Tag {tag!r} bei {element.name!r} existiert nicht")
        return f"Tag {tag!r} bei {element.name!r} entfernt ({removed} Zeile(n))"

    def _custom_rows(self, guid: str, tag: str) -> list[sqlite3.Row]:
        table = self.model.xref_table
        if table is None or not guid:
            return []
        columns = _columns(self.con, table)
        client = _require_column(columns, table, "Client")
        description = _require_column(columns, table, "Description")
        rows = self.con.execute(
            f"SELECT rowid AS __rowid, * FROM {_quote(table)} WHERE {_quote(client)} = ? COLLATE NOCASE",
            (guid,),
        ).fetchall()
        hits: list[sqlite3.Row] = []
        for row in rows:
            name, _ = _parse_prop(_as_text(row[description]))
            if name and name.casefold() == tag.casefold():
                hits.append(row)
        return hits

    def _sync_custom_property(
        self, element: _Element, tag: str, value: str, op: Mapping[str, Any], journal: _Journal
    ) -> None:
        """Haelt eine vorhandene ``@PROP``-Zeile in ``t_xref`` aktuell.

        Neue ``@PROP``-Zeilen entstehen nur auf Wunsch (``"xref": true``), weil
        EA sie doppelt zu ``t_objectproperties`` fuehrt und der Reader
        ``t_objectproperties`` liest.
        """
        table = self.model.xref_table
        if table is None:
            return
        hits = self._custom_rows(element.guid, tag)
        description_column = _require_column(_columns(self.con, table), table, "Description")
        if hits:
            for row in hits:
                journal.update(table, _as_int(row["__rowid"]), {description_column: _describe_prop(tag, value)})
            return
        if not bool(op.get("xref")):
            return
        journal.insert(
            table,
            self._new_xref_values(
                client=element.guid,
                name=_CUSTOM_ROW_NAME,
                xref_type=_ELEMENT_XREF,
                description=_describe_prop(tag, value),
                seed=f"model_edit|prop|{_guid_key(element.guid)}|{tag}",
            ),
        )

    def _remove_custom_property(self, element: _Element, tag: str, journal: _Journal) -> int:
        table = self.model.xref_table
        if table is None:
            return 0
        hits = self._custom_rows(element.guid, tag)
        for row in hits:
            journal.delete(table, _as_int(row["__rowid"]))
        return len(hits)

    # -- Loeschen -------------------------------------------------------
    def _children(self, object_id: int) -> list[tuple[int, int, str]]:
        """Eingebettete Objekte (ParentID) rekursiv, tiefste zuerst.

        Ein Port oder Part ohne seinen Traeger waere eine Waise im Modell --
        EA loescht ihn mit. Zyklen (defekte Modelle) werden abgefangen.
        """
        gefunden: list[tuple[int, int, str]] = []
        gesehen: set[int] = {object_id}
        ebene = [object_id]
        while ebene:
            naechste: list[int] = []
            for parent in ebene:
                for row in self.con.execute(
                    f"SELECT rowid AS __rowid, Object_ID, ea_guid FROM {_quote(self.model.object_table)}"
                    " WHERE ParentID = ? ORDER BY Object_ID",
                    (parent,),
                ).fetchall():
                    child = _as_int(row["Object_ID"])
                    if child in gesehen:
                        continue
                    gesehen.add(child)
                    gefunden.append((child, _as_int(row["__rowid"]), _as_text(row["ea_guid"])))
                    naechste.append(child)
            ebene = naechste
        return list(reversed(gefunden))

    def _delete_object(self, object_id: int, rowid: int, guid: str, journal: _Journal) -> int:
        """Ein Objekt samt Tags, Attributen, Sichtverweisen und Kanten loeschen."""
        con = self.con
        removed_connectors = 0
        connectors = con.execute(
            f"SELECT rowid AS __rowid, Connector_ID, ea_guid FROM {_quote(self.model.connector_table)}"
            " WHERE Start_Object_ID = ? OR End_Object_ID = ?",
            (object_id, object_id),
        ).fetchall()
        for connector in connectors:
            self._delete_connector_row(connector, journal)
            removed_connectors += 1

        if self.model.property_table is not None:
            for row in con.execute(
                f"SELECT rowid AS __rowid FROM {_quote(self.model.property_table)} WHERE Object_ID = ?",
                (object_id,),
            ).fetchall():
                journal.delete(self.model.property_table, _as_int(row["__rowid"]))

        if self.model.attribute_table is not None:
            attribute_columns = _columns(con, self.model.attribute_table)
            id_column = _require_column(attribute_columns, self.model.attribute_table, "ID")
            for row in con.execute(
                f"SELECT rowid AS __rowid, {_quote(id_column)} FROM {_quote(self.model.attribute_table)}"
                " WHERE Object_ID = ?",
                (object_id,),
            ).fetchall():
                attribute_id = _as_int(row[1])
                journal.delete(self.model.attribute_table, _as_int(row["__rowid"]))
                for name in ("t_attributetag", "t_attributeconstraints"):
                    table = self.model.tables.get(name)
                    if table is None:
                        continue
                    key = _column(_columns(con, table), "ElementID", "ID")
                    if key is None:
                        continue
                    for tag in con.execute(
                        f"SELECT rowid AS __rowid FROM {_quote(table)} WHERE {_quote(key)} = ?",
                        (attribute_id,),
                    ).fetchall():
                        journal.delete(table, _as_int(tag["__rowid"]))

        if self.model.xref_table is not None and guid:
            client = _require_column(_columns(con, self.model.xref_table), self.model.xref_table, "Client")
            for row in con.execute(
                f"SELECT rowid AS __rowid FROM {_quote(self.model.xref_table)}"
                f" WHERE {_quote(client)} = ? COLLATE NOCASE",
                (guid,),
            ).fetchall():
                journal.delete(self.model.xref_table, _as_int(row["__rowid"]))

        if self.model.diagram_object_table is not None:
            key = _column(_columns(con, self.model.diagram_object_table), "Object_ID")
            if key is not None:
                for row in con.execute(
                    f"SELECT rowid AS __rowid FROM {_quote(self.model.diagram_object_table)}"
                    f" WHERE {_quote(key)} = ?",
                    (object_id,),
                ).fetchall():
                    journal.delete(self.model.diagram_object_table, _as_int(row["__rowid"]))

        journal.delete(self.model.object_table, rowid)
        return removed_connectors

    def _op_delete_element(self, op, index, journal) -> str:
        element = self.model.element(op)
        entfernt = 0
        kanten = self._delete_object(element.object_id, element.rowid, element.guid, journal)
        for object_id, rowid, guid in self._children(element.object_id):
            kanten += self._delete_object(object_id, rowid, guid, journal)
            entfernt += 1
        return (
            f"Element {element.name!r} geloescht "
            f"(mit {entfernt} eingebetteten Objekt(en), {kanten} Kante(n) und ihren Tags)"
        )

    def _delete_connector_row(self, connector: Mapping[str, Any], journal: _Journal) -> None:
        """Loescht eine Kante samt Tags, Constraints und Stereotype-Zeile."""
        con = self.con
        connector_id = _as_int(connector["Connector_ID"])
        for name in ("t_connectortag", "t_connectorconstraint"):
            table = self.model.tables.get(name)
            if table is None:
                continue
            columns = _columns(con, table)
            key = _column(columns, "ElementID", "ConnectorID", "Connector_ID")
            if key is None:
                continue
            for row in con.execute(
                f"SELECT rowid AS __rowid FROM {_quote(table)} WHERE {_quote(key)} = ?",
                (connector_id,),
            ).fetchall():
                journal.delete(table, _as_int(row["__rowid"]))
        if self.model.diagram_link_table is not None:
            key = _column(_columns(con, self.model.diagram_link_table), "ConnectorID")
            if key is not None:
                for row in con.execute(
                    f"SELECT rowid AS __rowid FROM {_quote(self.model.diagram_link_table)}"
                    f" WHERE {_quote(key)} = ?",
                    (connector_id,),
                ).fetchall():
                    journal.delete(self.model.diagram_link_table, _as_int(row["__rowid"]))
        guid = _as_text(connector["ea_guid"]).strip()
        if self.model.xref_table is not None and guid:
            columns = _columns(con, self.model.xref_table)
            client = _require_column(columns, self.model.xref_table, "Client")
            for row in con.execute(
                f"SELECT rowid AS __rowid FROM {_quote(self.model.xref_table)}"
                f" WHERE {_quote(client)} = ? COLLATE NOCASE",
                (guid,),
            ).fetchall():
                journal.delete(self.model.xref_table, _as_int(row["__rowid"]))
        journal.delete(self.model.connector_table, _as_int(connector["__rowid"]))

    def _op_delete_connector(self, op, index, journal) -> str:
        connector = self.model.connector(op)
        name = _as_text(connector["Name"]) or _as_text(connector["ea_guid"])
        self._delete_connector_row(connector, journal)
        return f"Kante {name!r} geloescht"

    # -- Kante anlegen --------------------------------------------------
    def _op_add_connector(self, op, index, journal) -> str:
        source = self.model.endpoint(op.get("source"), "source")
        target = self.model.endpoint(op.get("target"), "target")
        if source.object_id == target.object_id:
            raise _Reject("Quelle und Ziel sind dasselbe Element")
        stereotype = _as_text(op.get("stereotype")).strip()
        connector_type = (
            _as_text(op.get("ea_type")).strip()
            or _as_text(op.get("connector_type")).strip()
            or "Dependency"
        )
        name = _as_text(op.get("name"))
        direction = _as_text(op.get("direction")).strip() or "Source -> Destination"
        guid = _as_text(op.get("guid")).strip()
        if guid:
            hit = self.con.execute(
                f"SELECT 1 FROM {_quote(self.model.connector_table)}"
                " WHERE upper(ea_guid) = upper(?) LIMIT 1",
                (guid,),
            ).fetchone()
            if hit:
                raise _Reject(f"Kante mit ea_guid {guid} existiert bereits")
        else:
            guid = self._free_guid(
                self.model.connector_table,
                "ea_guid",
                "model_edit|connector|"
                f"{_guid_key(source.guid)}|{_guid_key(target.guid)}|{connector_type}|{name}",
            )

        columns = _columns(self.con, self.model.connector_table)
        values: dict[str, Any] = {
            _require_column(columns, self.model.connector_table, "Connector_ID"): _max_int(
                self.con, self.model.connector_table, "Connector_ID"
            )
            + 1,
            _require_column(columns, self.model.connector_table, "Start_Object_ID"): source.object_id,
            _require_column(columns, self.model.connector_table, "End_Object_ID"): target.object_id,
            _require_column(columns, self.model.connector_table, "Connector_Type"): connector_type,
            _require_column(columns, self.model.connector_table, "ea_guid"): guid,
        }
        if (hit := _column(columns, "Name")) is not None:
            values[hit] = name
        if (hit := _column(columns, "Direction")) is not None:
            values[hit] = direction
        if (hit := _column(columns, "Stereotype")) is not None:
            values[hit] = stereotype
        if (hit := _column(columns, "Notes")) is not None and "notes" in op:
            values[hit] = _as_text(op.get("notes"))
        journal.insert(self.model.connector_table, values)

        if stereotype and self.model.xref_table is not None:
            profile = _as_text(op.get("profile")).strip() or self.model.profile
            fqname = f"FQName={profile}::{stereotype};" if profile else ""
            journal.insert(
                self.model.xref_table,
                self._new_xref_values(
                    client=guid,
                    name=_STEREO_ROW_NAME,
                    xref_type=_CONNECTOR_XREF,
                    description=f"@STEREO;Name={stereotype};{fqname}@ENDSTEREO;",
                    seed=f"model_edit|connector-stereotype|{_guid_key(guid)}|{stereotype}",
                ),
            )
        return (
            f"Kante {source.name!r} -> {target.name!r} ({connector_type}"
            + (f", {stereotype}" if stereotype else "")
            + ") angelegt"
        )


# --------------------------------------------------------------------------
# MDG-Pruefung
# --------------------------------------------------------------------------


def _ziel_text(op: Mapping[str, Any]) -> str:
    """Kurzbezeichnung des Operationsziels fuer den Bericht."""
    for key in ("guid", "name", "source"):
        value = _as_text(op.get(key)).strip()
        if value:
            return value
    return ""


def _error_keys(findings: Iterable[Mapping[str, Any]]) -> set[tuple[str, ...]]:
    """Menge der Fehler-Findings als vergleichbare Schluessel (Warnungen zaehlen nicht)."""
    return {
        (
            _as_text(finding.get("object")),
            _as_text(finding.get("rule")),
            _as_text(finding.get("check")),
            _as_text(finding.get("message")),
        )
        for finding in findings
        if _as_text(finding.get("severity")) == validator.ERROR
    }


def _new_error(before: set[tuple[str, ...]], after: set[tuple[str, ...]]) -> str:
    """Erste neue Fehlermeldung (deterministisch sortiert) oder ""."""
    fresh = sorted(after - before)
    return fresh[0][3] if fresh else ""


def _load_rules(path: Path) -> validator.RuleSet:
    try:
        parsed = mdg_parser.parse_mdg(path)
    except mdg_parser.MdgParseError as error:
        raise EditError(f"{path}: MDG nicht lesbar ({error})") from error
    try:
        return validator.build_rules(parsed)
    except validator.ValidatorError as error:
        raise EditError(f"{path}: Regelwerk nicht nutzbar ({error})") from error


def _validate_errors(path: Path, ruleset: validator.RuleSet) -> set[tuple[str, ...]]:
    """Fehler-Findings des Modells gegen das Regelwerk (Warnungen zaehlen nicht).

    Ein Modell ohne Elemente hat keine Element- oder Kantenregel zu verletzen;
    ``validator`` lehnt ein leeres IR aber strukturell ab. Deshalb ist die
    Fehlermenge dann leer -- geloescht werden darf bis zum letzten Element.
    """
    ir = _read_ir(path, "Arbeitskopie")
    if not ir.get("elements"):
        return set()
    return _error_keys(validator.validate_model(ir, ruleset))


def _read_ir(path: Path, what: str) -> dict[str, Any]:
    try:
        # allow_empty: das letzte Element darf geloescht werden; ein leeres
        # Modell ist fuer die Regelpruefung kein Fehler.
        return qea_reader.read_qea(path, allow_empty=True)
    except qea_reader.QeaReaderError as error:
        raise EditError(f"{what}: {path} ist nicht als IR lesbar ({error})") from error


# --------------------------------------------------------------------------
# Oeffentliche API
# --------------------------------------------------------------------------


def _load_ops(ops: Any) -> list[dict[str, Any]]:
    """Prueft die Operationsliste (Liste oder {"ops": [...]})."""
    if isinstance(ops, Mapping):
        inner = ops.get("ops")
        if inner is None:
            raise EditError("ops: Objekt ohne Schluessel 'ops'")
        ops = inner
    if not isinstance(ops, Sequence) or isinstance(ops, (str, bytes)):
        raise EditError("ops: Liste von Operationen erwartet")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(ops):
        if not isinstance(item, Mapping):
            raise EditError(f"ops[{index}]: JSON-Objekt erwartet")
        result.append(dict(item))
    return result


def edit_model(
    path: str | os.PathLike[str],
    ops: Sequence[Mapping[str, Any]],
    out: str | os.PathLike[str],
    *,
    mdg: str | os.PathLike[str] | None = None,
) -> EditResult:
    """Wendet ``ops`` auf eine Kopie von ``path`` an und schreibt ``out``.

    :param path: Quellmodell (wird nur gelesen, nie veraendert).
    :param ops: Operationen in Reihenfolge; jede nennt ihr Ziel per ``guid``
        oder ``package`` + ``name``.
    :param out: Ergebnisdatei. Darf nicht das Quellmodell sein.
    :param mdg: optionales MDG-/Technologie-XML. Ist es gesetzt, wird jede
        Operation gegen das Regelwerk geprueft und bei einem neuen Fehler
        abgelehnt.
    :returns: :class:`EditResult` mit Zaehler und Ablehnungsliste.
    :raises EditError: bei strukturellen Fehlern (nichts wird geschrieben).
    """
    source_path = Path(path)
    out_path = Path(out)
    if not source_path.is_file():
        raise EditError(f"{source_path}: Modell nicht gefunden")
    if out_path.resolve() == source_path.resolve():
        raise EditError(f"{out_path}: Zieldatei ist das Original -- Abbruch")
    operations = _load_ops(ops)

    ruleset = _load_rules(Path(mdg)) if mdg is not None else None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_name(out_path.name + ".edit-tmp")
    temporary.unlink(missing_ok=True)
    shutil.copyfile(source_path, temporary)

    warnings: list[str] = []
    changes: list[str] = []
    rejected: list[dict[str, Any]] = []
    applied = 0
    try:
        con = sqlite3.connect(temporary)
        con.text_factory = str
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys = OFF")
            model = _Model(con, temporary)
            editor = _Editor(model)
            baseline: set[tuple[str, ...]] = set()
            if ruleset is not None:
                try:
                    baseline = _validate_errors(temporary, ruleset)
                except (validator.ValidatorError, EditError) as error:
                    raise EditError(f"Modell nicht gegen das MDG pruefbar: {error}") from error

            for index, op in enumerate(operations):
                kind = _as_text(op.get("op")).strip()
                journal = _Journal(con)
                try:
                    detail = editor.apply(op, index, journal)
                    con.commit()
                except _Reject as rejection:
                    con.rollback()
                    rejected.append(
                        {
                            "op": index,
                            "typ": kind,
                            "ziel": _ziel_text(op),
                            "grund": str(rejection),
                        }
                    )
                    continue
                except sqlite3.Error as error:
                    con.rollback()
                    rejected.append(
                        {
                            "op": index,
                            "typ": kind,
                            "ziel": _ziel_text(op),
                            "grund": f"Datenbankfehler: {error}",
                        }
                    )
                    continue

                if ruleset is not None:
                    try:
                        errors = _validate_errors(temporary, ruleset)
                    except (validator.ValidatorError, EditError) as error:
                        journal.restore()
                        con.commit()
                        rejected.append(
                            {
                                "op": index,
                                "typ": kind,
                                "ziel": _ziel_text(op),
                                "grund": f"nach der Aenderung nicht pruefbar: {error}",
                            }
                        )
                        continue
                    fresh = _new_error(baseline, errors)
                    if fresh:
                        journal.restore()
                        con.commit()
                        rejected.append(
                            {
                                "op": index,
                                "typ": kind,
                                "ziel": _ziel_text(op),
                                "grund": f"MDG-Verstoss: {fresh}",
                            }
                        )
                        continue
                    baseline = errors
                applied += 1
                if len(changes) < _MAX_WARNINGS:
                    changes.append(f"op {index}: {detail}")

            check = con.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise EditError(f"{out_path}: SQLite integrity_check fehlgeschlagen ({check!r})")
        finally:
            con.close()
        os.chmod(temporary, 0o644)
        os.replace(temporary, out_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return EditResult(
        written=str(out_path),
        applied=applied,
        rejected=rejected,
        ops=len(operations),
        mdg=str(mdg) if mdg is not None else "",
        changes=changes,
        warnings=warnings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: Bericht als JSON auf stdout, Fehler auf stderr."""
    parser = argparse.ArgumentParser(
        prog="model_edit.py",
        description="Gezielte Aenderungen an einer .qea (Kopie, Original bleibt unberuehrt).",
    )
    parser.add_argument("qea", help="Quellmodell (.qea, wird nur gelesen)")
    parser.add_argument("--ops", required=True, help="Operationsdatei (JSON)")
    parser.add_argument("--out", required=True, help="Ergebnisdatei (.qea)")
    parser.add_argument("--mdg", default=None, help="MDG-/Technologie-XML fuer die Regelpruefung")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.ops).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"model_edit: {args.ops}: nicht lesbar ({error})", file=sys.stderr)
        return 2

    try:
        result = edit_model(args.qea, payload, args.out, mdg=args.mdg)
    except (EditError, OSError, sqlite3.Error) as error:
        print(f"model_edit: {error}", file=sys.stderr)
        return 2

    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result.rejected else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
