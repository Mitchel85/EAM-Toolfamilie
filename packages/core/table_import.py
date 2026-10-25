#!/usr/bin/env python3
"""table_import.py -- Tabellen (CSV/XLSX) in das IR-JSON uebersetzen.

Zweck
-----
Der Regelpfad der Suite muss ohne KI auskommen. Neben JSON-IR und bestehenden
.qea-Dateien sind Tabellen die dritte strukturierte Quelle: Fachbereiche
pflegen Elemente und Kanten in Excel, das Werkzeug macht daraus IR.

Nur stdlib: ``csv``, ``zipfile`` und ``xml.etree.ElementTree``. Kein Netz,
keine externen Pakete (kein openpyxl), keine Zeitstempel, keine Zufallswerte.

Tabellenformat
--------------
Eine Tabelle ist eine Liste von Datensaetzen mit Kopfzeile. Die Spaltennamen
sind die IR-Feldnamen (siehe IR_SPEC.md), zusaetzlich:

    record     nur bei gemischten CSV: package | element | connector
    tag:<Name> Tagged Value <Name> des Datensatzes

Erlaubte Spalten je Datensatzart:

    packages    path, name, notes, stereotype
    elements    package, name, stereotype, ea_type, notes, alias, status
    connectors  source, target, stereotype, ea_type, name, direction, notes

* CSV: eine Datei je Art (``kind``) oder eine gemischte Datei mit Spalte
  ``record`` (``kind="mixed"``). Trennzeichen ist ``,`` -- Semikolon wird
  erkannt und laut mit Hinweis abgelehnt, nicht still umgedeutet.
* XLSX: Arbeitsmappe mit den Blaettern ``packages``, ``elements``,
  ``connectors`` (Gross-/Kleinschreibung egal). Andere Blaetter sind ein
  Fehler, damit ein Tippfehler nicht still als "leer" durchgeht. Fehlende
  Blaetter liefern null Datensaetze.

Regeln
------
* Zellen werden von umgebenden Leerzeichen befreit (Tabellenformatierung).
* Unbekannte Spalten, doppelte Spalten, fehlende Pflichtspalten und fehlende
  Pflichtwerte brechen mit Zeilenangabe ab (``TableImportError``).
* Vollstaendig leere Zeilen werden uebersprungen; teilweise gefuellte Zeilen
  werden geprueft und scheitern an ihren Pflichtfeldern.
* Ein Modell ohne Element ist ein Fehler (der Writer lehnt es ebenfalls ab).
* Ausgabe ist kanonisch: Pakete nach Pfad, Elemente und Kanten nach Inhalt
  sortiert, nur gesetzte optionale Felder -- gleicher Input, gleiche Bytes.

Oeffentliche API
----------------
    import_table(pfad, kind="auto", delimiter=None, encoding="utf-8-sig",
                 profile=None) -> dict
    import_csv(pfad, kind="auto", ...) -> dict
    import_xlsx(pfad, ...) -> dict
    build_ir(packages=..., elements=..., connectors=..., technology=...) -> dict

CLI: ``python3 table_import.py tabelle.csv -o modell.json``
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple, NoReturn, Sequence

IR_VERSION = 1
DEFAULT_OBJECT_TYPE = "Class"
DEFAULT_CONNECTOR_TYPE = "Dependency"
DEFAULT_DIRECTION = "Source -> Destination"

KINDS = ("packages", "elements", "connectors")
_SINGULAR = {"package": "packages", "pkgs": "packages", "packages": "packages",
             "element": "elements", "elements": "elements",
             "connector": "connectors", "connectors": "connectors"}

FIELDS: dict[str, tuple[str, ...]] = {
    "packages": ("path", "name", "notes", "stereotype"),
    "elements": ("package", "name", "stereotype", "ea_type", "notes", "alias", "status"),
    "connectors": (
        "source", "target", "stereotype", "ea_type", "name", "direction", "notes",
    ),
}
REQUIRED: dict[str, tuple[str, ...]] = {
    "packages": ("path",),
    "elements": ("package", "name"),
    "connectors": ("source", "target"),
}
MIXED_FIELDS = ("record",)
TAG_PREFIX = "tag:"
_ALL_KNOWN = set(FIELDS["packages"]) | set(FIELDS["elements"]) | set(FIELDS["connectors"])

_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_SHEET_BY_KIND = {kind: kind for kind in KINDS}


class TableImportError(ValueError):
    """Eingabefehler in einer Tabelle. Immer laut, nie still."""


def _fail(message: str) -> NoReturn:
    raise TableImportError(message)


class Record(NamedTuple):
    """Ein Datensatz mit Herkunftsangabe und aufgeloester Art."""

    kind: str
    label: str
    fields: dict[str, str]
    tags: dict[str, str]


# --------------------------------------------------------------------------
# Kopfzeile / Zellen
# --------------------------------------------------------------------------


def _column_names(cells: Sequence[str], *, where: str, allowed: set[str]) -> list[tuple[int, str]]:
    """Prueft die Kopfzeile und liefert (Spaltenindex, kanonischer Name)."""
    columns: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(cells):
        name = raw.strip()
        if not name:
            _fail(f"{where}: Spalte {index + 1} hat keinen Namen")
        lowered = name.lower()
        if lowered.startswith(TAG_PREFIX):
            key = name[len(TAG_PREFIX):].strip()
            if not key:
                _fail(f"{where}: Tag-Spalte '{name}' ohne Namen")
            canonical = TAG_PREFIX + key
            if canonical in seen:
                _fail(f"{where}: Spalte '{name}' kommt doppelt vor")
        elif lowered in allowed:
            canonical = lowered
            if canonical in seen:
                _fail(f"{where}: Spalte '{name}' kommt doppelt vor")
        else:
            _fail(
                f"{where}: unbekannte Spalte '{name}' -- erlaubt sind "
                + ", ".join(sorted(allowed))
                + " und tag:<Name>"
            )
        seen.add(canonical)
        columns.append((index, canonical))
    if not columns:
        _fail(f"{where}: Kopfzeile ist leer")
    return columns


def _row_values(cells: Sequence[str], width: int) -> list[str]:
    values = [cell.strip() for cell in cells[:width]]
    if len(values) < width:
        values.extend([""] * (width - len(values)))
    return values


def _records(
    header: Sequence[str],
    rows: Iterable[tuple[int, Sequence[str]]],
    *,
    where: str,
    kind: str,
) -> list[Record]:
    """Baut Datensaetze fuer eine Art (packages/elements/connectors) oder gemischt."""
    if kind == "mixed":
        allowed = set(_ALL_KNOWN) | set(MIXED_FIELDS)
    else:
        allowed = set(FIELDS[kind])
    columns = _column_names(header, where=where, allowed=allowed)
    names = {name for _, name in columns}
    if kind != "mixed":
        missing = [name for name in REQUIRED[kind] if name not in names]
        if missing:
            _fail(f"{where}: Pflichtspalte(n) fehlen: {', '.join(missing)}")
    elif "record" not in names:
        _fail(f"{where}: gemischte Tabelle braucht die Spalte 'record'")

    width = len(header)
    records: list[Record] = []
    for number, cells in rows:
        label = f"{where} Zeile {number}"
        if len(cells) > width:
            _fail(f"{label}: {len(cells)} Zellen, aber nur {width} Spalten")
        values = _row_values(cells, width)
        if not any(values):
            continue
        fields: dict[str, str] = {}
        tags: dict[str, str] = {}
        for index, name in columns:
            value = values[index]
            if name.startswith(TAG_PREFIX):
                if value:
                    tags[name[len(TAG_PREFIX):]] = value
            else:
                fields[name] = value

        if kind == "mixed":
            raw_kind = fields.pop("record", "").lower()
            resolved = _SINGULAR.get(raw_kind)
            if resolved is None:
                _fail(
                    f"{label}: 'record' muss package, element oder connector sein "
                    f"(gefunden: {raw_kind or 'leer'})"
                )
            for name, value in fields.items():
                if name not in FIELDS[resolved] and value:
                    _fail(
                        f"{label}: Spalte '{name}' ist fuer record={raw_kind} nicht erlaubt "
                        f"(Wert: {value!r})"
                    )
            fields = {name: value for name, value in fields.items() if name in FIELDS[resolved]}
        else:
            resolved = kind

        missing_values = [
            name for name in REQUIRED[resolved] if not fields.get(name, "").strip()
        ]
        if missing_values:
            _fail(f"{label}: Pflichtwert(e) leer: {', '.join(missing_values)}")
        records.append(Record(kind=resolved, label=label, fields=fields, tags=tags))
    return records


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------


def _decode(raw: bytes, encoding: str, where: str) -> str:
    try:
        return raw.decode(encoding)
    except LookupError as error:
        _fail(f"{where}: unbekannte Kodierung {encoding!r} ({error})")
    except UnicodeDecodeError as error:
        _fail(
            f"{where}: nicht als {encoding} lesbar ({error}) -- "
            "Kodierung mit --encoding angeben"
        )


def _csv_text(path: Path, encoding: str) -> str:
    try:
        raw = path.read_bytes()
    except OSError as error:
        _fail(f"CSV {path}: nicht lesbar ({error})")
    if not raw.strip():
        _fail(f"CSV {path}: Datei ist leer")
    return _decode(raw, encoding, f"CSV {path}")


def _csv_rows(text: str, delimiter: str, where: str) -> list[list[str]]:
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        return [list(row) for row in reader]
    except csv.Error as error:
        _fail(f"{where}: kein gueltiges CSV ({error})")


def _detect_kind(header: Sequence[str], where: str) -> str:
    columns = {cell.strip().lower() for cell in header if cell.strip()}
    if "record" in columns:
        return "mixed"
    if {"source", "target"} <= columns:
        return "connectors"
    if "path" in columns and "package" not in columns:
        return "packages"
    if {"package", "name"} <= columns:
        return "elements"
    _fail(
        f"{where}: Spaltenart nicht erkennbar -- erwartet werden 'path' (Pakete), "
        "'package'+'name' (Elemente), 'source'+'target' (Kanten) oder 'record' "
        f"(gemischt); gefunden: {', '.join(sorted(columns)) or 'nichts'}"
    )


def _records_to_ir(
    packages: Sequence[Record],
    elements: Sequence[Record],
    connectors: Sequence[Record],
    *,
    technology: Mapping[str, str] | None,
    source: str,
) -> dict[str, Any]:
    if not elements:
        _fail(f"{source}: Tabelle enthaelt kein Element -- Abbruch statt leerem Modell")
    return build_ir(
        packages=packages,
        elements=elements,
        connectors=connectors,
        technology=technology,
        source=source,
    )


def read_csv_records(
    path: str | Path,
    *,
    kind: str = "auto",
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
) -> dict[str, list[Record]]:
    """Liest eine CSV-Datei und liefert die Datensaetze nach Art gruppiert.

    ``kind``: ``auto`` (aus der Kopfzeile), ``packages``, ``elements``,
    ``connectors`` oder ``mixed`` (Spalte ``record``).
    ``delimiter``: Default ``,``; ein Semikolon in der Kopfzeile wird laut
    abgelehnt, damit niemand versehentlich eine Spalte importiert.
    """
    target = Path(path)
    where = f"CSV {target.name}"
    text = _csv_text(target, encoding)
    if delimiter is None:
        first = text.splitlines()[0] if text.splitlines() else ""
        if ";" in first and "," not in first:
            _fail(
                f"{where}: Semikolon als Trennzeichen erkannt -- "
                "mit --delimiter ';' erneut aufrufen (kein stilles Umdrehen)"
            )
        delimiter = ","
    if len(delimiter) != 1:
        _fail(f"{where}: Trennzeichen muss genau ein Zeichen sein (gefunden: {delimiter!r})")

    rows = _csv_rows(text, delimiter, where)
    if not rows:
        _fail(f"{where}: keine Kopfzeile")
    header = rows[0]
    if not any(cell.strip() for cell in header):
        _fail(f"{where}: Kopfzeile ist leer")
    resolved = _detect_kind(header, where) if kind in ("auto", "", None) else kind
    if resolved not in KINDS and resolved != "mixed":
        _fail(f"{where}: unbekannte Art {resolved!r} -- erlaubt: auto, mixed, " + ", ".join(KINDS))

    data = [(number, row) for number, row in enumerate(rows[1:], start=2)]
    records = _records(header, data, where=where, kind=resolved)
    grouped: dict[str, list[Record]] = {name: [] for name in KINDS}
    for record in records:
        grouped[record.kind].append(record)
    return grouped


def import_csv(
    path: str | Path,
    *,
    kind: str = "auto",
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    profile: str | None = None,
) -> dict[str, Any]:
    """Liest eine CSV-Datei und liefert IR (eine Tabelle, ggf. gemischt)."""
    grouped = read_csv_records(path, kind=kind, delimiter=delimiter, encoding=encoding)
    technology = {"profile": profile.strip()} if profile and profile.strip() else None
    return _records_to_ir(
        grouped["packages"],
        grouped["elements"],
        grouped["connectors"],
        technology=technology,
        source=str(path),
    )


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------


def _xlsx_member(archive: zipfile.ZipFile, name: str, where: str) -> bytes:
    try:
        return archive.read(name)
    except KeyError:
        _fail(f"{where}: Pflichtdatei {name} fehlt -- keine gueltige .xlsx-Arbeitsmappe")


def _xml(data: bytes, where: str) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        _fail(f"{where}: kaputtes XML ({error})")


def _shared_strings(archive: zipfile.ZipFile, where: str) -> list[str]:
    try:
        data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = _xml(data, f"{where} sharedStrings.xml")
    strings: list[str] = []
    for item in root.iter(f"{_XLSX_NS}si"):
        strings.append("".join(text.text or "" for text in item.iter(f"{_XLSX_NS}t")))
    return strings


def _sheet_targets(archive: zipfile.ZipFile, where: str) -> list[tuple[str, str]]:
    workbook = _xml(_xlsx_member(archive, "xl/workbook.xml", where), f"{where} workbook.xml")
    rels = _xml(
        _xlsx_member(archive, "xl/_rels/workbook.xml.rels", where),
        f"{where} workbook.xml.rels",
    )
    relation = {}
    for rel in rels:
        rel_id = rel.get("Id")
        rel_target = rel.get("Target")
        if rel_id and rel_target:
            relation[rel_id] = rel_target
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.iter(f"{_XLSX_NS}sheet"):
        name = sheet.get("name") or ""
        rel_id = next(
            (value for key, value in sheet.attrib.items() if key.endswith("}id")), None
        )
        if not name or not rel_id or rel_id not in relation:
            _fail(f"{where}: Blatt ohne Namen oder ohne Beziehung ({name or '?'})")
        target = relation[rel_id].replace("\\", "/")
        if target.startswith("/"):
            member = target.lstrip("/")
        else:
            member = posixpath.normpath(posixpath.join("xl", target))
        if not member.startswith("xl/"):
            _fail(f"{where}: Blattziel {target!r} liegt ausserhalb von xl/")
        sheets.append((name, member))
    if not sheets:
        _fail(f"{where}: Arbeitsmappe enthaelt kein Blatt")
    return sheets


def _column_number(reference: str) -> int:
    match = re.match(r"([A-Za-z]+)", reference)
    if not match:
        _fail(f"ungueltige Zellreferenz {reference!r}")
    number = 0
    for char in match.group(1).upper():
        number = number * 26 + (ord(char) - ord("A") + 1)
    return number - 1


def _number_text(raw: str) -> str:
    """Zahlzelle deterministisch als Text (Ganzzahlen ohne .0)."""
    text = raw.strip()
    if not text:
        return ""
    if re.fullmatch(r"-?\d+", text):
        return text
    try:
        number = float(text)
    except ValueError:
        _fail(f"Zahlzelle {raw!r} ist keine Zahl")
    if number.is_integer() and abs(number) < 10**15:
        return str(int(number))
    return repr(number)


def _cell_value(
    cell: ET.Element, shared: Sequence[str], where: str, reference: str
) -> str:
    cell_type = cell.get("t") or "n"
    value = cell.find(f"{_XLSX_NS}v")
    if cell_type == "s":
        if value is None or value.text is None or not value.text.strip():
            _fail(f"{where}: Textzelle {reference} ohne sharedString-Index")
        try:
            return shared[int(value.text.strip())]
        except (ValueError, IndexError):
            _fail(f"{where}: Textzelle {reference} verweist auf unbekannten sharedString")
    if cell_type == "inlineStr":
        inline = cell.find(f"{_XLSX_NS}is")
        if inline is None:
            return ""
        return "".join(text.text or "" for text in inline.iter(f"{_XLSX_NS}t"))
    if cell_type == "str":
        return value.text or "" if value is not None else ""
    if cell_type == "b":
        return "TRUE" if (value is not None and (value.text or "").strip() == "1") else "FALSE"
    if cell_type == "e":
        _fail(f"{where}: Fehlerzelle {reference} ({value.text if value is not None else ''})")
    if cell_type in ("n", "d"):
        return _number_text(value.text or "") if value is not None else ""
    _fail(f"{where}: nicht unterstuetzter Zelltyp {cell_type!r} in {reference}")


def _sheet_rows(
    archive: zipfile.ZipFile,
    member: str,
    shared: Sequence[str],
    where: str,
) -> list[tuple[int, list[str]]]:
    root = _xml(_xlsx_member(archive, member, where), f"{where} {member}")
    rows: list[tuple[int, list[str]]] = []
    for position, row in enumerate(root.iter(f"{_XLSX_NS}row"), start=1):
        number = int(row.get("r") or position)
        cells: dict[int, str] = {}
        for offset, cell in enumerate(row.findall(f"{_XLSX_NS}c")):
            reference = cell.get("r") or ""
            column = _column_number(reference) if reference else offset
            cells[column] = _cell_value(cell, shared, where, reference or f"Spalte {column + 1}")
        if not cells:
            continue
        width = max(cells) + 1
        values = [cells.get(index, "") for index in range(width)]
        if not any(value.strip() for value in values):
            continue
        rows.append((number, values))
    return rows


def read_xlsx_records(path: str | Path) -> dict[str, list[Record]]:
    """Liest eine .xlsx-Arbeitsmappe und liefert Datensaetze nach Art gruppiert."""
    target = Path(path)
    where = f"XLSX {target.name}"
    try:
        archive = zipfile.ZipFile(target)
    except OSError as error:
        _fail(f"{where}: nicht lesbar ({error})")
    except zipfile.BadZipFile as error:
        _fail(f"{where}: keine gueltige .xlsx-Datei ({error})")
    with archive:
        try:
            sheets = _sheet_targets(archive, where)
            shared = _shared_strings(archive, where)
            known: dict[str, list[tuple[int, list[str]]]] = {}
            for name, member in sheets:
                key = name.strip().lower()
                if key not in _SHEET_BY_KIND:
                    _fail(
                        f"{where}: unbekanntes Blatt {name!r} -- erlaubt sind "
                        + ", ".join(KINDS)
                    )
                if key in known:
                    _fail(f"{where}: Blatt {name!r} kommt doppelt vor")
                known[key] = _sheet_rows(archive, member, shared, where)
        except zipfile.BadZipFile as error:
            _fail(f"{where}: kaputtes ZIP ({error})")

    grouped: dict[str, list[Record]] = {name: [] for name in KINDS}
    for kind in KINDS:
        rows = known.get(kind, [])
        if not rows:
            continue
        header = rows[0][1]
        if not any(cell.strip() for cell in header):
            _fail(f"{where} Blatt {kind}: Kopfzeile ist leer")
        records = _records(
            header,
            [(number, values) for number, values in rows[1:]],
            where=f"{where} Blatt {kind}",
            kind=kind,
        )
        grouped[kind].extend(records)
    return grouped


def import_xlsx(
    path: str | Path,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    """Liest eine .xlsx-Arbeitsmappe mit den Blaettern packages/elements/connectors."""
    grouped = read_xlsx_records(path)
    technology = {"profile": profile.strip()} if profile and profile.strip() else None
    return _records_to_ir(
        grouped["packages"],
        grouped["elements"],
        grouped["connectors"],
        technology=technology,
        source=str(path),
    )


# --------------------------------------------------------------------------
# IR aufbauen
# --------------------------------------------------------------------------


def _package_segment(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _check_path(path: str, label: str) -> None:
    if not path:
        _fail(f"{label}: Paketpfad ist leer")
    if "::" in path:
        _fail(f"{label}: Paketpfad {path!r} enthaelt '::' (reserviert fuer Elemente)")
    if "\\" in path:
        _fail(f"{label}: Paketpfad {path!r} nutzt '\\' -- Trenner ist '/'")
    if path.startswith("/") or path.endswith("/") or "//" in path:
        _fail(f"{label}: Paketpfad {path!r} hat ein leeres Segment")
    for segment in path.split("/"):
        if not segment.strip():
            _fail(f"{label}: Paketpfad {path!r} hat ein leeres Segment")


def _tag_dict(tags: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in sorted(tags.items()) if value != ""}


def build_ir(
    *,
    packages: Sequence[Record],
    elements: Sequence[Record],
    connectors: Sequence[Record],
    technology: Mapping[str, str] | None = None,
    source: str = "Tabellen",
) -> dict[str, Any]:
    """Baut kanonisches IR aus bereits geprueften Datensaetzen."""
    if not elements:
        _fail(f"{source}: kein Element vorhanden -- Abbruch statt leerem Modell")

    package_items: list[dict[str, Any]] = []
    by_path: dict[str, str] = {}
    for record in packages:
        path = record.fields["path"]
        _check_path(path, record.label)
        if path in by_path:
            _fail(f"{record.label}: Paketpfad {path!r} doppelt (schon in {by_path[path]})")
        by_path[path] = record.label

    for path in sorted(by_path):
        if "/" in path and path.rsplit("/", 1)[0] not in by_path:
            _fail(
                f"{by_path[path]}: Elternpaket {path.rsplit('/', 1)[0]!r} fehlt "
                "(jedes Elternpaket muss deklariert sein)"
            )

    for path in sorted(by_path):
        record = next(item for item in packages if item.fields["path"] == path)
        item: dict[str, Any] = {"path": path}
        name = record.fields.get("name", "")
        if name and name != _package_segment(path):
            item["name"] = name
        if record.fields.get("stereotype", ""):
            item["stereotype"] = record.fields["stereotype"]
        if record.fields.get("notes", ""):
            item["notes"] = record.fields["notes"]
        tags = _tag_dict(record.tags)
        if tags:
            item["tags"] = tags
        package_items.append(item)

    element_items: list[dict[str, Any]] = []
    for record in elements:
        package = record.fields["package"]
        if package not in by_path:
            _fail(f"{record.label}: Paket {package!r} ist nicht deklariert")
        item = {
            "package": package,
            "name": record.fields["name"],
        }
        if record.fields.get("stereotype", ""):
            item["stereotype"] = record.fields["stereotype"]
        item["ea_type"] = record.fields.get("ea_type", "") or DEFAULT_OBJECT_TYPE
        for field in ("notes", "alias", "status"):
            if record.fields.get(field, ""):
                item[field] = record.fields[field]
        tags = _tag_dict(record.tags)
        if tags:
            item["tags"] = tags
        element_items.append(item)
    element_items.sort(
        key=lambda item: (
            item["package"],
            item["name"],
            item["ea_type"],
            item.get("stereotype", ""),
            item.get("notes", ""),
            item.get("alias", ""),
            item.get("status", ""),
            tuple(sorted(item.get("tags", {}).items())),
        )
    )

    connector_items: list[dict[str, Any]] = []
    for record in connectors:
        source_ref = record.fields["source"]
        target_ref = record.fields["target"]
        for ref in (source_ref, target_ref):
            _check_endpoint(ref, by_path, record.label)
        item: dict[str, Any] = {"source": source_ref, "target": target_ref}
        if record.fields.get("stereotype", ""):
            item["stereotype"] = record.fields["stereotype"]
        item["ea_type"] = record.fields.get("ea_type", "") or DEFAULT_CONNECTOR_TYPE
        if record.fields.get("name", ""):
            item["name"] = record.fields["name"]
        direction = record.fields.get("direction", "")
        if direction and direction != DEFAULT_DIRECTION:
            item["direction"] = direction
        if record.fields.get("notes", ""):
            item["notes"] = record.fields["notes"]
        tags = _tag_dict(record.tags)
        if tags:
            item["tags"] = tags
        connector_items.append(item)
    connector_items.sort(
        key=lambda item: (
            item["source"],
            item["target"],
            item.get("stereotype", ""),
            item.get("name", ""),
            item["ea_type"],
            item.get("direction", ""),
            item.get("notes", ""),
            tuple(sorted(item.get("tags", {}).items())),
        )
    )

    ir: dict[str, Any] = {"ir_version": IR_VERSION}
    if technology:
        cleaned = {key: value for key, value in technology.items() if value}
        if cleaned:
            ir["technology"] = cleaned
    ir["packages"] = package_items
    ir["elements"] = element_items
    ir["connectors"] = connector_items
    ir["diagrams"] = []
    return ir


def _check_endpoint(reference: str, packages: Mapping[str, str], label: str) -> None:
    if not reference:
        _fail(f"{label}: Kantenendpunkt ist leer")
    if "::" in reference:
        package, _, name = reference.partition("::")
        if not package or not name:
            _fail(f"{label}: Endpunkt {reference!r} ist unvollstaendig (paket::name)")
        if package not in packages:
            _fail(f"{label}: Endpunkt {reference!r} nutzt unbekanntes Paket {package!r}")
        if "/" not in package:
            _fail(
                f"{label}: Endpunkt {reference!r} zeigt auf ein Wurzelpaket -- "
                "Wurzelpakete haben keinen Paketspiegel"
            )
        return
    if reference not in packages:
        _fail(
            f"{label}: Endpunkt {reference!r} ist weder 'paket::element' "
            "noch ein deklariertes Paket"
        )
    if "/" not in reference:
        _fail(
            f"{label}: Endpunkt {reference!r} zeigt auf ein Wurzelpaket -- "
            "Wurzelpakete haben keinen Paketspiegel"
        )


# --------------------------------------------------------------------------
# Einstieg / CLI
# --------------------------------------------------------------------------


def import_table(
    path: str | Path,
    *,
    kind: str = "auto",
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    profile: str | None = None,
) -> dict[str, Any]:
    """Liest .csv oder .xlsx und liefert IR."""
    return import_tables(
        [path],
        kind=kind,
        delimiter=delimiter,
        encoding=encoding,
        profile=profile,
    )


def import_tables(
    paths: Sequence[str | Path],
    *,
    kind: str = "auto",
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    profile: str | None = None,
) -> dict[str, Any]:
    """Liest eine oder mehrere Tabellen (.csv/.xlsx) und baut ein gemeinsames IR.

    Mehrere CSV-Dateien duerfen je eine Art liefern (Pakete, Elemente, Kanten)
    oder gemischt sein; die Datensaetze werden zusammengefuehrt. Mehrere
    Arbeitsmappen werden ebenfalls zusammengefuehrt -- doppelte Datensaetze
    fallen anschliessend bei der Pruefung auf.
    """
    if not paths:
        _fail("keine Tabelle angegeben")
    grouped: dict[str, list[Record]] = {name: [] for name in KINDS}
    for raw in paths:
        path = Path(raw)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            part = read_csv_records(
                path, kind=kind, delimiter=delimiter, encoding=encoding
            )
        elif suffix == ".xlsx":
            if kind not in ("auto", "", None):
                _fail(
                    f"{path}: Blattart wird bei .xlsx ueber die Blattnamen bestimmt, "
                    "nicht per kind"
                )
            part = read_xlsx_records(path)
        else:
            _fail(
                f"{path}: nur .csv und .xlsx werden gelesen "
                f"(gefunden: {suffix or 'ohne Endung'})"
            )
        for name in KINDS:
            grouped[name].extend(part[name])
    technology = {"profile": profile.strip()} if profile and profile.strip() else None
    return _records_to_ir(
        grouped["packages"],
        grouped["elements"],
        grouped["connectors"],
        technology=technology,
        source=", ".join(str(path) for path in paths),
    )


def dumps_ir(ir: Mapping[str, Any]) -> str:
    """Kanonischer IR-Text (identisch zu qea_reader.render_json)."""
    return json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="table_import.py",
        description="Tabelle (CSV/XLSX) in IR-JSON uebersetzen. Ohne KI, ohne Netz.",
    )
    parser.add_argument("tabelle", type=Path, help="Quelldatei .csv oder .xlsx")
    parser.add_argument("-o", "--out", type=Path, help="Ziel-IR-JSON (Default: stdout)")
    parser.add_argument(
        "--kind",
        default="auto",
        choices=("auto", "mixed", "packages", "elements", "connectors"),
        help="Art der CSV-Tabelle (Default: aus der Kopfzeile)",
    )
    parser.add_argument("--delimiter", help="CSV-Trennzeichen (Default: ',')")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV-Kodierung")
    parser.add_argument("--profile", help="Technologieprofil fuer das IR")
    args = parser.parse_args(argv)

    try:
        ir = import_table(
            args.tabelle,
            kind=args.kind,
            delimiter=args.delimiter,
            encoding=args.encoding,
            profile=args.profile,
        )
    except (TableImportError, OSError) as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 2

    text = dumps_ir(ir)
    if args.out:
        try:
            args.out.write_text(text, encoding="utf-8", newline="\n")
        except OSError as error:
            print(f"FEHLER: {args.out}: nicht schreibbar ({error})", file=sys.stderr)
            return 2
        print(
            f"{args.out}: {len(ir['packages'])} Pakete, {len(ir['elements'])} Elemente, "
            f"{len(ir['connectors'])} Kanten",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
