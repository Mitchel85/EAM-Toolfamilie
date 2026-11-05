"""roundtrip_export.py -- .qea (Sparx EA, SQLite) -> Markdown-Doku + JSON-Belege.

Das Modul liest eine .qea-Datei ausschliesslich lesend (``mode=ro`` plus
``PRAGMA query_only``) und erzeugt zwei Artefakte:

1. ein deutsches Markdown-Dokument mit Titel, Kennzahlen, je Paket einer
   Ueberschrift samt Elementliste, einem Abschnitt "Beziehungen" und einem
   Abschnitt "Sichten" (ohne Koordinaten),
2. eine maschinenlesbare Belegdatei (JSON) mit Paketen, Elementen, Kanten und
   Sichten -- inklusive IDs und GUIDs, damit jede Aussage nachpruefbar bleibt.

Oeffentliche API::

    from roundtrip_export import export_documentation

    kennzahlen = export_documentation("modell.qea", "doku.md", "belege.json")

CLI::

    python3 roundtrip_export.py QUELLE.qea --md doku.md --belege belege.json \
        [--max-elements N]

Kodierung der Tagged Values in ``t_xref`` (in der MASC-Fixture die eigentliche
Wertquelle) -- gemessen, nicht geraten:

- Relevant sind Zeilen mit ``Name = 'CustomProperties'``. ``Client`` enthaelt die
  ``ea_guid`` des Owners (Element oder Kante); die Schreibweise der GUIDs ist
  gemischt, deshalb wird ueber ``upper()`` verglichen.
- ``Description`` enthaelt einen oder mehrere hintereinander stehende Bloecke::

      @PROP=@NAME=<Name>@ENDNAME;@TYPE=<Typ>@ENDTYPE;@VALU=<Wert>@ENDVALU;
      @PRMT=@ENDPRMT;@ENDPROP;

  In der Fixture tragen 717 Zeilen 979 Bloecke, also bis zu mehrere Bloecke je
  Zeile. ``@VALU=`` darf leer sein; fehlende Felder gelten als leer.
- ``t_objectproperties`` enthaelt in der Fixture 9237 Zeilen, davon nur 3821 mit
  einem Wert -- der Rest ist ``NULL``. Die Werte stehen dann in ``t_xref``.
  Beide Quellen werden zusammengefuehrt: ``t_objectproperties`` hat Vorrang,
  ``t_xref`` fuellt fehlende oder leere Werte. Widerspruechliche, nicht-leere
  Werte werden gezaehlt (``tag_konflikte``), aber nicht stillschweigend
  ueberschrieben.
- ``Name = 'Stereotypes'`` (``@STEREO;Name=...;FQName=...@ENDSTEREO;``) und
  ``Name = 'MOFProps'`` werden nicht als Tags gefuehrt: Stereotype stehen
  bereits in ``t_object.Stereotype``, MOFProps sind reine GUID-Listen ohne
  Schluessel/Wert-Paar.

Determinismus: alle Listen werden explizit sortiert (Paketpfad, Elementname,
ID), Tags nach Schluessel; es gibt keine Zeitstempel, keine Zufallswerte und
keine absoluten Pfade im Dokument (nur der Dateiname). Gleiche Eingabe erzeugt
daher byte-identische Ausgaben.

Format 2 (gegenueber 1)

* Jede Zeile im Abschnitt ``## Beziehungen`` nennt zusaetzlich
  ``Quelle-GUID`` und ``Ziel-GUID``. Bei Elementen ist das
  ``t_object.ea_guid``, bei Paketspiegeln ``t_package.ea_guid`` (die beiden
  Werte unterscheiden sich in echten EA-Dateien). Damit ist der Rueckweg auch
  bei doppelten (Paket, Name)-Paaren eindeutig; ``prosa_import.py`` loest
  Kantenendpunkte bevorzugt darueber auf.
* Elementzeilen trennen ``Tags:`` (aus ``t_objectproperties``) von
  ``Tags (xref):`` (aus ``t_xref``/``CustomProperties``). Der Rueckbau schreibt
  sie getrennt zurueck, sonst wuerden Tags gedoppelt.
* Weicht der gespeicherte Name vom aufbereiteten Anzeigenamen ab (Umbrueche,
  Mehrfach-Leerzeichen), steht der Originalname als JSON in ``Rohname:``.
* Die Kantenzeile nennt die gespeicherte ``Richtung``.

Kennzahlen (Schluessel in ``belege.json`` unter ``quelle.kennzahlen``):
``pakete``, ``elemente`` (alle Zeilen aus ``t_object``, inklusive der
Paketspiegel -- diese erscheinen im Dokument als Elemente vom Typ ``Package``),
``elemente_ohne_paketspiegel``, ``kanten``, ``sichten``, ``attribute``,
``operationen``, ``tags``, ``elemente_mit_notiz``, ``pakete_mit_notiz``,
``tag_konflikte`` (widerspruechliche Werte innerhalb von
``t_objectproperties``; der erste nicht-leere Wert gewinnt), ``gekuerzt``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

FORMAT_VERSION = 2

#: Anzeigename fuer Elemente ohne Namen (EA erlaubt leere Namen, z. B. bei
#: Text- und Notiz-Elementen).
OHNE_NAMEN = "(unbenannt)"

#: Anzeige fuer fehlende optionale Werte in der Prosa-Doku.
LEER = "-"


class RoundtripExportError(ValueError):
    """Lauter Fehler: unlesbare Datei, fehlende Pflichtspalten, kein Export."""


# --------------------------------------------------------------------------
# SQLite-Zugriff (nur lesen)
# --------------------------------------------------------------------------


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _open_readonly(path: Path) -> sqlite3.Connection:
    """Oeffnet die .qea ausschliesslich lesend."""
    if not path.exists():
        raise RoundtripExportError(f"{path}: Datei existiert nicht")
    if not path.is_file():
        raise RoundtripExportError(f"{path}: keine regulaere Datei")
    uri = "file:" + quote(path.resolve().as_posix(), safe="/") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as error:
        raise RoundtripExportError(
            f"{path}: keine lesbare SQLite-Datenbank ({error})"
        ) from error
    return con


def _tables(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    return {row[0].lower(): row[0] for row in rows}


def _require_table(tables: Mapping[str, str], name: str, path: Path) -> str:
    found = tables.get(name.lower())
    if found is None:
        raise RoundtripExportError(
            f"{path}: Tabelle {name!r} fehlt -- das ist keine vollstaendige .qea"
        )
    return found


def _columns(con: sqlite3.Connection, table: str) -> dict[str, str]:
    return {
        row[1].lower(): row[1]
        for row in con.execute(f"PRAGMA table_info({_quote_identifier(table)})")
    }


def _column(columns: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        if name.lower() in columns:
            return columns[name.lower()]
    return None


def _require_column(columns: Mapping[str, str], table: str, *names: str) -> str:
    found = _column(columns, *names)
    if found is None:
        raise RoundtripExportError(
            f"{table}: Pflichtspalte {names[0]!r} fehlt "
            f"(vorhanden: {', '.join(sorted(columns.values())) or 'keine'})"
        )
    return found


def _cell(row: sqlite3.Row, columns: Mapping[str, str], *names: str) -> Any:
    column = _column(columns, *names)
    if column is None:
        return None
    return row[column]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def _int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _count(con: sqlite3.Connection, table: str | None) -> int:
    if table is None:
        return 0
    return int(con.execute(f"SELECT count(*) FROM {_quote_identifier(table)}").fetchone()[0])


# --------------------------------------------------------------------------
# Textaufbereitung
# --------------------------------------------------------------------------

# HTML-Tags, die EA in Notizen hinterlaesst (z. B. <ul><li>...</li></ul>).
_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")
# In der Datenbank stehen teils echte Zeilenumbrueche, teils die Literale
# "\r\n" (Backslash r Backslash n) -- beides wird zu einem Leerzeichen.
_LITERAL_NEWLINE_RE = re.compile(r"\\r\\n|\\n|\\r")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_note(raw: Any) -> str:
    """Notiz als einzeiliger Klartext: Tags raus, Entities dekodiert, Umbrueche weg."""
    text = _text(raw)
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    # Erst Tags entfernen, dann Entities dekodieren -- sonst wuerde ein
    # maskiertes "&lt;b&gt;" faelschlich als Tag verschwinden.
    text = html.unescape(text)
    text = html.unescape(text)  # doppelt kodierte Entities (kommt in EA vor)
    text = _LITERAL_NEWLINE_RE.sub(" ", text)
    text = text.replace("\u00a0", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def _clean_value(raw: Any) -> str:
    """Tag-Wert: Entities dekodieren, Umbrueche/Mehrfach-Leerzeichen einebnen."""
    text = _text(raw)
    if not text:
        return ""
    text = html.unescape(text)
    text = _LITERAL_NEWLINE_RE.sub(" ", text)
    text = text.replace("\u00a0", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


_MD_ESCAPE_RE = re.compile(r"([\\`*_\[\]<>])")


def _md(text: str) -> str:
    """Maskiert Markdown-Sonderzeichen in Prosa und Namen."""
    return _MD_ESCAPE_RE.sub(r"\\\1", text)


def _code(text: str) -> str:
    """Inhalt fuer einen Code-Span; Backticks sind dort nicht maskierbar."""
    return text.replace("`", "'")


def _md_table(text: str) -> str:
    return _md(text).replace("|", r"\|")


# --------------------------------------------------------------------------
# Modell
# --------------------------------------------------------------------------


@dataclass
class Paket:
    id: int
    name: str
    parent_id: int
    guid: str
    notes: str
    tpos: int
    path: str = ""


@dataclass
class Element:
    id: int
    name: str
    typ: str
    stereotype: str
    notes: str
    paket_id: int
    alias: str
    status: str
    guid: str
    ref: str = ""
    #: Name, wie er in der Datenbank steht (nur gesetzt, wenn er sich vom
    #: aufbereiteten Anzeigenamen unterscheidet). Der Prosa-Import stellt
    #: damit den exakten Namen wieder her.
    roh_name: str = ""
    #: ``t_object.PDATA1`` bei Paketspiegeln: die ``t_package.Package_ID`` des
    #: gespiegelten Pakets. Nur so sind gleichnamige Geschwisterpakete
    #: (z. B. zweimal ``Views``) eindeutig zuzuordnen.
    spiegel_paket_id: int = 0


@dataclass
class Kante:
    id: int
    typ: str
    stereotype: str
    name: str
    direction: str
    guid: str
    start_id: int
    end_id: int
    quelle: str = ""
    ziel: str = ""
    #: GUIDs der beiden Endpunkte: bei Elementen ``t_object.ea_guid``, bei
    #: Paketspiegeln ``t_package.ea_guid`` (die beiden GUIDs unterscheiden
    #: sich in echten EA-Dateien).
    start_guid: str = ""
    end_guid: str = ""
    #: Freitext der Beziehung (``t_connector.Notes``); der Rueckweg uebernimmt
    #: ihn woertlich, damit die Begruendung einer Verbindung nicht verloren geht.
    notes: str = ""


@dataclass
class Sicht:
    id: int
    name: str
    typ: str
    guid: str
    paket_id: int
    notes: str


@dataclass
class Modell:
    quelle: Path
    sha256: str
    pakete: dict[int, Paket]
    elemente: list[Element]
    kanten: list[Kante]
    sichten: list[Sicht]
    attribute: dict[int, list[tuple[str, str]]]
    tags: dict[int, dict[str, str]]
    #: Nur die Tags aus ``t_objectproperties`` (ohne t_xref-Ergaenzungen).
    tags_own: dict[int, dict[str, str]] = field(default_factory=dict)
    #: Tags, die nur in ``t_xref`` (Name='CustomProperties') stehen und im
    #: Dokument als eigene Zeile gefuehrt werden. Sie gehoeren beim Rueckbau
    #: wieder nach ``t_xref`` -- nicht in ``t_objectproperties``.
    tags_xref: dict[int, dict[str, str]] = field(default_factory=dict)
    kennzahlen: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Pakete und Pfade
# --------------------------------------------------------------------------


def _clean_segment(name: str) -> str:
    """Ein Paketname als Pfadsegment (keine Pfadtrenner, keine Steuerzeichen)."""
    text = "".join(ch if ch.isprintable() else " " for ch in name)
    text = text.replace("/", "\u2215").replace("\\", "\u2216")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or "(ohne Namen)"


def _unique_segment(name: str, used: set[str]) -> str:
    base = _clean_segment(name)
    candidate = base
    number = 2
    while candidate in used:
        candidate = f"{base}#{number}"
        number += 1
    used.add(candidate)
    return candidate


def _assign_paths(pakete: dict[int, Paket]) -> None:
    """Setzt ``Pfad`` fuer jedes Paket; gleichnamige Geschwister bekommen #2, #3 ...

    Sortierung der Geschwister: (TPos, Package_ID). Zyklen und Waisen werden
    nicht verschluckt, sondern als eigenstaendige Wurzel mit Pfad versehen.
    """
    children: dict[int, list[Paket]] = {}
    for paket in pakete.values():
        parent = paket.parent_id if paket.parent_id in pakete else 0
        if parent == paket.id:
            parent = 0
        children.setdefault(parent, []).append(paket)
    for bucket in children.values():
        bucket.sort(key=lambda item: (item.tpos, item.id))

    used: dict[int, set[str]] = {}
    visited: set[int] = set()

    def walk(parent_id: int, parent_path: str, depth: int) -> None:
        if depth > 64:
            return
        for paket in children.get(parent_id, []):
            if paket.id in visited:
                continue
            visited.add(paket.id)
            segment = _unique_segment(paket.name, used.setdefault(parent_id, set()))
            paket.path = f"{parent_path}/{segment}" if parent_path else segment
            walk(paket.id, paket.path, depth + 1)

    walk(0, "", 0)
    # Waisen und Zyklusreste: eigener Wurzelpfad, deterministisch nach ID.
    for paket in sorted(pakete.values(), key=lambda item: item.id):
        if paket.path:
            continue
        visited.add(paket.id)
        segment = _unique_segment(paket.name, used.setdefault(0, set()))
        paket.path = segment


def _read_pakete(con: sqlite3.Connection, tables: Mapping[str, str], path: Path) -> dict[int, Paket]:
    table = _require_table(tables, "t_package", path)
    columns = _columns(con, table)
    id_column = _require_column(columns, table, "Package_ID")
    name_column = _require_column(columns, table, "Name")
    parent_column = _column(columns, "Parent_ID")
    guid_column = _column(columns, "ea_guid")
    notes_column = _column(columns, "Notes")
    tpos_column = _column(columns, "TPos")

    pakete: dict[int, Paket] = {}
    for row in con.execute(f"SELECT * FROM {_quote_identifier(table)}"):
        paket_id = _int(row[id_column])
        if paket_id in pakete:
            raise RoundtripExportError(f"{table}: Package_ID {paket_id} doppelt")
        pakete[paket_id] = Paket(
            id=paket_id,
            name=_text(row[name_column]),
            parent_id=_int(row[parent_column]) if parent_column else 0,
            guid=_text(row[guid_column]) if guid_column else "",
            notes=_clean_note(row[notes_column]) if notes_column else "",
            tpos=_int(row[tpos_column]) if tpos_column else 0,
        )
    _assign_paths(pakete)
    return pakete


# --------------------------------------------------------------------------
# Elemente
# --------------------------------------------------------------------------


def _read_elemente(
    con: sqlite3.Connection, tables: Mapping[str, str], path: Path
) -> list[Element]:
    table = _require_table(tables, "t_object", path)
    columns = _columns(con, table)
    id_column = _require_column(columns, table, "Object_ID")
    name_column = _require_column(columns, table, "Name")
    type_column = _column(columns, "Object_Type")
    stereotype_column = _column(columns, "Stereotype")
    note_column = _column(columns, "Note")
    package_column = _column(columns, "Package_ID")
    alias_column = _column(columns, "Alias")
    status_column = _column(columns, "Status")
    guid_column = _column(columns, "ea_guid")
    pdata1_column = _column(columns, "PDATA1")

    elemente: list[Element] = []
    seen: set[int] = set()
    for row in con.execute(f"SELECT * FROM {_quote_identifier(table)}"):
        object_id = _int(row[id_column])
        if object_id in seen:
            raise RoundtripExportError(f"{table}: Object_ID {object_id} doppelt")
        seen.add(object_id)
        raw_name = _text(row[name_column])
        elemente.append(
            Element(
                id=object_id,
                name=_clean_value(raw_name),
                typ=_text(row[type_column]) if type_column else "",
                stereotype=_clean_value(row[stereotype_column]) if stereotype_column else "",
                notes=_clean_note(row[note_column]) if note_column else "",
                paket_id=_int(row[package_column]) if package_column else 0,
                alias=_clean_value(row[alias_column]) if alias_column else "",
                status=_clean_value(row[status_column]) if status_column else "",
                guid=_text(row[guid_column]) if guid_column else "",
                roh_name=raw_name,
                spiegel_paket_id=_int(row[pdata1_column]) if pdata1_column else 0,
            )
        )
    elemente.sort(key=_element_order)
    return elemente


def _element_order(element: Element) -> tuple[str, str, int]:
    return (element.name.casefold(), element.name, element.id)


def _assign_refs(
    elemente: Sequence[Element], pakete: Mapping[int, Paket]
) -> dict[int, str]:
    """Eindeutige Referenz ``<paketpfad>::<name>`` je Element.

    Gleichnamige Elemente im selben Paket bekommen ``#2``, ``#3`` ... in
    ID-Reihenfolge (dieselbe Konvention wie im Reader).
    """
    groups: dict[tuple[str, str], list[Element]] = {}
    for element in elemente:
        paket = pakete.get(element.paket_id)
        paket_path = paket.path if paket is not None else ""
        label = element.name or f"#{element.id}"
        groups.setdefault((paket_path, label), []).append(element)

    refs: dict[int, str] = {}
    for (paket_path, label), group in groups.items():
        for index, element in enumerate(sorted(group, key=lambda item: item.id), start=1):
            suffix = label if index == 1 else f"{label}#{index}"
            element.ref = f"{paket_path}::{suffix}" if paket_path else suffix
            refs[element.id] = element.ref
    return refs


def _endpunkt_guid(
    object_id: int,
    elemente: Mapping[int, Element],
    pakete: Mapping[int, Paket],
) -> str:
    """GUID eines Kantenendpunkts.

    Paketspiegel sind Zeilen in ``t_object``; ihre ``ea_guid`` ist in echten
    EA-Dateien *nicht* die ``t_package.ea_guid``. Fuer den Rueckweg wird
    deshalb die Paket-GUID ausgegeben -- die Zuordnung erfolgt ueber
    ``t_object.PDATA1`` (Package_ID des gespiegelten Pakets), ersatzweise
    ueber (Elternpaket, Name), wenn das eindeutig ist.
    """
    element = elemente.get(object_id)
    if element is None:
        return ""
    if element.typ.lower() != "package":
        return element.guid
    paket = pakete.get(element.spiegel_paket_id)
    if paket is None:
        candidates = [
            item
            for item in pakete.values()
            if item.name == element.name and item.parent_id == element.paket_id
        ]
        paket = candidates[0] if len(candidates) == 1 else None
    return paket.guid if paket is not None else element.guid


# --------------------------------------------------------------------------
# Tagged Values: t_objectproperties + t_xref
# --------------------------------------------------------------------------

_PROP_BLOCK_RE = re.compile(r"@PROP=(.*?)@ENDPROP;", re.S)
_PROP_FIELD_RE = {
    "name": re.compile(r"@NAME=(.*?)@ENDNAME;", re.S),
    "type": re.compile(r"@TYPE=(.*?)@ENDTYPE;", re.S),
    "value": re.compile(r"@VALU=(.*?)@ENDVALU;", re.S),
}


def _parse_prop_description(description: str) -> list[tuple[str, str]]:
    """Zerlegt eine ``@PROP=...@ENDPROP;``-Beschreibung in (Name, Wert)-Paare."""
    pairs: list[tuple[str, str]] = []
    for block in _PROP_BLOCK_RE.findall(description or ""):
        name_match = _PROP_FIELD_RE["name"].search(block)
        if name_match is None:
            continue
        name = _clean_value(name_match.group(1))
        if not name:
            continue
        value_match = _PROP_FIELD_RE["value"].search(block)
        value = _clean_value(value_match.group(1)) if value_match else ""
        pairs.append((name, value))
    return pairs


def _read_object_tags(
    con: sqlite3.Connection, tables: Mapping[str, str]
) -> tuple[dict[int, dict[str, str]], int]:
    """Tags aus ``t_objectproperties``; Rueckgabe (Tags, Konflikte)."""
    table = tables.get("t_objectproperties")
    if table is None:
        return {}, 0
    columns = _columns(con, table)
    owner_column = _require_column(columns, table, "Object_ID")
    property_column = _require_column(columns, table, "Property")
    value_column = _column(columns, "Value")
    order_column = _column(columns, "PropertyID", "Property_ID")

    sql = f"SELECT * FROM {_quote_identifier(table)}"
    if order_column is not None:
        sql += f" ORDER BY {_quote_identifier(order_column)}"

    tags: dict[int, dict[str, str]] = {}
    conflicts = 0
    for row in con.execute(sql):
        owner = _int(row[owner_column])
        name = _clean_value(row[property_column])
        if not name:
            raise RoundtripExportError(
                f"{table}: Tag ohne Property-Namen (Object_ID {owner})"
            )
        value = _clean_value(row[value_column]) if value_column else ""
        bucket = tags.setdefault(owner, {})
        previous = bucket.get(name)
        if previous is None or (not previous and value):
            bucket[name] = value
        elif previous and value and previous != value:
            conflicts += 1  # erster nicht-leerer Wert gewinnt, Konflikt wird gezaehlt
    return tags, conflicts


def _read_xref_tags(con: sqlite3.Connection, tables: Mapping[str, str]) -> dict[str, dict[str, str]]:
    """Tags aus ``t_xref`` (Name='CustomProperties'), Schluessel: Owner-GUID upper()."""
    table = tables.get("t_xref")
    if table is None:
        return {}
    columns = _columns(con, table)
    name_column = _column(columns, "Name")
    description_column = _column(columns, "Description")
    client_column = _column(columns, "Client")
    if name_column is None or description_column is None or client_column is None:
        return {}

    result: dict[str, dict[str, str]] = {}
    sql = (
        f"SELECT {_quote_identifier(name_column)}, {_quote_identifier(description_column)}, "
        f"{_quote_identifier(client_column)} FROM {_quote_identifier(table)} "
        f"WHERE lower({_quote_identifier(name_column)}) = 'customproperties'"
    )
    for row in con.execute(sql):
        description = _text(row[description_column])
        if "@PROP=" not in description:
            continue
        owner = _text(row[client_column]).upper()
        if not owner:
            continue
        bucket = result.setdefault(owner, {})
        for name, value in _parse_prop_description(description):
            previous = bucket.get(name)
            if previous is None or (not previous and value):
                bucket[name] = value
    return result


def _merge_tags(
    primary: Mapping[str, str], secondary: Mapping[str, str]
) -> tuple[dict[str, str], int]:
    """Fuehrt Tags zusammen: ``primary`` hat Vorrang, ``secondary`` fuellt Luecken."""
    merged = dict(primary)
    filled = 0
    for name, value in secondary.items():
        if name not in merged:
            merged[name] = value
            filled += 1
        elif not merged[name] and value:
            merged[name] = value
            filled += 1
    return merged, filled


# --------------------------------------------------------------------------
# Kanten, Sichten, Attribute
# --------------------------------------------------------------------------


def _read_kanten(
    con: sqlite3.Connection, tables: Mapping[str, str], path: Path
) -> list[Kante]:
    table = _require_table(tables, "t_connector", path)
    columns = _columns(con, table)
    id_column = _require_column(columns, table, "Connector_ID")
    start_column = _require_column(columns, table, "Start_Object_ID")
    end_column = _require_column(columns, table, "End_Object_ID")
    type_column = _column(columns, "Connector_Type")
    stereotype_column = _column(columns, "Stereotype")
    name_column = _column(columns, "Name")
    direction_column = _column(columns, "Direction")
    guid_column = _column(columns, "ea_guid")
    notes_column = _column(columns, "Notes")

    kanten: list[Kante] = []
    for row in con.execute(f"SELECT * FROM {_quote_identifier(table)}"):
        kanten.append(
            Kante(
                id=_int(row[id_column]),
                typ=_text(row[type_column]) if type_column else "",
                stereotype=_clean_value(row[stereotype_column]) if stereotype_column else "",
                name=_clean_value(row[name_column]) if name_column else "",
                direction=_text(row[direction_column]) if direction_column else "",
                guid=_text(row[guid_column]) if guid_column else "",
                start_id=_int(row[start_column]),
                end_id=_int(row[end_column]),
                notes=_clean_note(row[notes_column]) if notes_column else "",
            )
        )
    kanten.sort(key=lambda item: (item.start_id, item.end_id, item.typ, item.id))
    return kanten


def _read_sichten(
    con: sqlite3.Connection, tables: Mapping[str, str]
) -> list[Sicht]:
    table = tables.get("t_diagram")
    if table is None:
        return []
    columns = _columns(con, table)
    id_column = _require_column(columns, table, "Diagram_ID")
    name_column = _column(columns, "Name")
    type_column = _column(columns, "Diagram_Type")
    guid_column = _column(columns, "ea_guid")
    package_column = _column(columns, "Package_ID")
    notes_column = _column(columns, "Notes")

    sichten: list[Sicht] = []
    for row in con.execute(f"SELECT * FROM {_quote_identifier(table)}"):
        sichten.append(
            Sicht(
                id=_int(row[id_column]),
                name=_clean_value(row[name_column]) if name_column else "",
                typ=_text(row[type_column]) if type_column else "",
                guid=_text(row[guid_column]) if guid_column else "",
                paket_id=_int(row[package_column]) if package_column else 0,
                notes=_clean_note(row[notes_column]) if notes_column else "",
            )
        )
    sichten.sort(key=lambda item: (item.name.casefold(), item.name, item.id))
    return sichten


def _read_attribute(
    con: sqlite3.Connection, tables: Mapping[str, str]
) -> dict[int, list[tuple[str, str]]]:
    """Attribute je Element als (Name, Typ), sortiert nach (Name, ID)."""
    table = tables.get("t_attribute")
    if table is None:
        return {}
    columns = _columns(con, table)
    owner_column = _require_column(columns, table, "Object_ID")
    name_column = _column(columns, "Name")
    type_column = _column(columns, "Type")
    id_column = _column(columns, "ID")
    if name_column is None:
        return {}

    rows: list[tuple[int, int, str, str]] = []
    for row in con.execute(f"SELECT * FROM {_quote_identifier(table)}"):
        rows.append(
            (
                _int(row[owner_column]),
                _int(row[id_column]) if id_column else 0,
                _clean_value(row[name_column]),
                _clean_value(row[type_column]) if type_column else "",
            )
        )
    rows.sort(key=lambda item: (item[0], item[2].casefold(), item[1]))
    result: dict[int, list[tuple[str, str]]] = {}
    for owner, _attribute_id, name, type_name in rows:
        result.setdefault(owner, []).append((name, type_name))
    return result


# --------------------------------------------------------------------------
# Modell laden
# --------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lade_modell(qea_path: str | Path, *, max_elements: int | None = None) -> Modell:
    """Liest die .qea und baut das Exportmodell (inkl. Kennzahlen)."""
    path = Path(qea_path)
    con = _open_readonly(path)
    try:
        tables = _tables(con)
        pakete = _read_pakete(con, tables, path)
        elemente = _read_elemente(con, tables, path)
        kanten = _read_kanten(con, tables, path)
        sichten = _read_sichten(con, tables)
        attribute = _read_attribute(con, tables)
        object_tags, tag_conflicts = _read_object_tags(con, tables)
        xref_tags = _read_xref_tags(con, tables)
        operationen = _count(con, tables.get("t_operation"))
    except sqlite3.DatabaseError as error:
        raise RoundtripExportError(f"{path}: SQLite-Fehler beim Lesen ({error})") from error
    finally:
        con.close()

    if not pakete:
        raise RoundtripExportError(f"{path}: keine Pakete -- kein Export")
    if not elemente:
        raise RoundtripExportError(f"{path}: keine Elemente -- kein Export")

    refs = _assign_refs(elemente, pakete)
    element_by_id = {element.id: element for element in elemente}
    for kante in kanten:
        kante.quelle = refs.get(kante.start_id, f"<unbekannt:{kante.start_id}>")
        kante.ziel = refs.get(kante.end_id, f"<unbekannt:{kante.end_id}>")
        kante.start_guid = _endpunkt_guid(kante.start_id, element_by_id, pakete)
        kante.end_guid = _endpunkt_guid(kante.end_id, element_by_id, pakete)
    kanten.sort(
        key=lambda item: (
            item.quelle.casefold(),
            item.quelle,
            item.ziel.casefold(),
            item.ziel,
            item.typ,
            item.id,
        )
    )

    tags: dict[int, dict[str, str]] = {}
    tags_own: dict[int, dict[str, str]] = {}
    tags_xref: dict[int, dict[str, str]] = {}
    filled_from_xref = 0
    for element in elemente:
        own = dict(object_tags.get(element.id, {}))
        external = xref_tags.get(element.guid.upper(), {}) if element.guid else {}
        merged, filled = _merge_tags(own, external)
        filled_from_xref += filled
        if own:
            tags_own[element.id] = dict(sorted(own.items(), key=lambda item: item[0].casefold()))
        if merged:
            tags[element.id] = dict(sorted(merged.items(), key=lambda item: item[0].casefold()))
        # Alles, was der zusammengefuehrte Stand aus t_xref bezieht, wird im
        # Dokument getrennt gefuehrt: beim Rueckbau gehoert es wieder nach
        # t_xref, nicht in t_objectproperties.
        extra = {
            name: value
            for name, value in merged.items()
            if own.get(name) != value
        }
        if extra:
            tags_xref[element.id] = dict(
                sorted(extra.items(), key=lambda item: item[0].casefold())
            )

    gesamt_elemente = len(elemente)
    if max_elements is not None:
        if max_elements < 1:
            raise RoundtripExportError("--max-elements muss >= 1 sein")
        elemente = elemente[:max_elements]
        behalten = {element.id for element in elemente}
        kanten = [
            kante for kante in kanten if kante.start_id in behalten and kante.end_id in behalten
        ]

    kennzahlen: dict[str, Any] = {
        "pakete": len(pakete),
        "elemente": len(elemente),
        "elemente_ohne_paketspiegel": sum(
            1 for element in elemente if element.typ.lower() != "package"
        ),
        "kanten": len(kanten),
        "sichten": len(sichten),
        "attribute": sum(len(items) for items in attribute.values()),
        "operationen": operationen,
        "tags": sum(len(bucket) for bucket in tags.values()),
        "elemente_mit_notiz": sum(1 for element in elemente if element.notes),
        "pakete_mit_notiz": sum(1 for paket in pakete.values() if paket.notes),
        "tag_konflikte": tag_conflicts,
        "gekuerzt": len(elemente) < gesamt_elemente,
    }

    return Modell(
        quelle=path,
        sha256=_sha256(path),
        pakete=pakete,
        elemente=elemente,
        kanten=kanten,
        sichten=sichten,
        attribute=attribute,
        tags=tags,
        tags_own=tags_own,
        tags_xref=tags_xref,
        kennzahlen=kennzahlen,
    )


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _element_lines(
    element: Element,
    tags: Mapping[str, str],
    attribute: Sequence[tuple[str, str]],
    xref_tags: Mapping[str, str] | None = None,
) -> list[str]:
    name = _md(element.name) if element.name else OHNE_NAMEN
    lines = [
        f"- **{name}** \u2014 Typ: `{_code(element.typ or LEER)}`"
        f" \u00b7 Stereotyp: `{_code(element.stereotype or LEER)}`"
        f" \u00b7 ID: `{element.id}`"
        f" \u00b7 GUID: `{_code(element.guid or LEER)}`"
        f" \u00b7 Alias: `{_code(element.alias or LEER)}`"
        f" \u00b7 Status: `{_code(element.status or LEER)}`"
    ]
    if element.notes:
        lines.append(f"  - Notiz: {_md(element.notes)}")
    if element.roh_name and element.roh_name != element.name:
        # Nur wenn die Aufbereitung den Namen veraendert hat (Umbruch,
        # Mehrfach-Leerzeichen). JSON haelt den Wert in einer Zeile.
        lines.append(f"  - Rohname: {json.dumps(element.roh_name, ensure_ascii=False)}")
    if tags:
        rendered = ", ".join(
            f"`{_code(key)}={_code(value)}`" for key, value in tags.items()
        )
        lines.append(f"  - Tags: {rendered}")
    if xref_tags:
        rendered = ", ".join(
            f"`{_code(key)}={_code(value)}`" for key, value in xref_tags.items()
        )
        lines.append(f"  - Tags (xref): {rendered}")
    if attribute:
        rendered = ", ".join(
            f"`{_code(attr_name)}`: `{_code(attr_type or LEER)}`"
            for attr_name, attr_type in attribute
        )
        lines.append(f"  - Attribute: {rendered}")
    return lines


def erstelle_markdown(modell: Modell) -> str:
    """Baut das vollstaendige Markdown-Dokument."""
    kennzahlen = modell.kennzahlen
    lines: list[str] = []
    add = lines.append

    add(f"# Architektur-Dokumentation \u2014 {modell.quelle.name}")
    add("")
    add(
        "Vollst\u00e4ndiger Auszug aus der Sparx-EA-Datenbank: alle Pakete, "
        "Elemente, Beziehungen und Sichten."
    )
    add("")
    add(f"Quelle: `{_code(modell.quelle.name)}`  ")
    add(f"SHA-256: `{modell.sha256}`  ")
    add(f"Format: `roundtrip_export {FORMAT_VERSION}`")
    add("")

    add("## Kennzahlen")
    add("")
    add("| Kennzahl | Wert |")
    add("| --- | ---: |")
    for label, value in (
        ("Pakete", kennzahlen["pakete"]),
        ("Elemente (t_object)", kennzahlen["elemente"]),
        ("davon ohne Paketspiegel", kennzahlen["elemente_ohne_paketspiegel"]),
        ("Beziehungen (t_connector)", kennzahlen["kanten"]),
        ("Sichten (t_diagram)", kennzahlen["sichten"]),
        ("Attribute (t_attribute)", kennzahlen["attribute"]),
        ("Operationen (t_operation)", kennzahlen["operationen"]),
        ("Tagged Values", kennzahlen["tags"]),
        ("Elemente mit Notiz", kennzahlen["elemente_mit_notiz"]),
        ("Pakete mit Notiz", kennzahlen["pakete_mit_notiz"]),
    ):
        add(f"| {label} | {value} |")
    add("")
    if kennzahlen["gekuerzt"]:
        add(
            f"> Hinweis: Die Elementliste ist auf {kennzahlen['elemente']} Elemente "
            "begrenzt (--max-elements). Die Beziehungen enthalten nur Kanten, deren "
            "beide Enden dokumentiert sind."
        )
        add("")

    add("## Paket\u00fcbersicht")
    add("")
    add("| Paketpfad | Paket-ID | GUID |")
    add("| --- | ---: | --- |")
    for paket in sorted(modell.pakete.values(), key=lambda item: (item.path.casefold(), item.id)):
        add(
            f"| {_md_table(paket.path)} | {paket.id} | "
            f"`{_code(paket.guid or LEER)}` |"
        )
    add("")

    by_package: dict[int, list[Element]] = {}
    for element in modell.elemente:
        by_package.setdefault(element.paket_id, []).append(element)

    for paket in sorted(modell.pakete.values(), key=lambda item: (item.path.casefold(), item.id)):
        add(f"## {_md(paket.path)}")
        add("")
        add(f"Paket-ID: `{paket.id}` \u00b7 GUID: `{_code(paket.guid or LEER)}`")
        add("")
        note = paket.notes
        if not note:
            # Bei Paketen liegt die Notiz oft am Paketspiegel (t_object).
            for element in by_package.get(paket.id, []):
                if element.typ.lower() == "package" and element.name == paket.name and element.notes:
                    note = element.notes
                    break
        if note:
            add(f"Notiz: {_md(note)}")
            add("")
        elements = by_package.get(paket.id, [])
        if not elements:
            add("_Keine Elemente in diesem Paket._")
            add("")
            continue
        for element in elements:
            lines.extend(
                _element_lines(
                    element,
                    modell.tags_own.get(element.id, {}),
                    modell.attribute.get(element.id, ()),
                    modell.tags_xref.get(element.id, {}),
                )
            )
        add("")

    add("## Beziehungen")
    add("")
    add(
        f"{kennzahlen['kanten']} Beziehungen, sortiert nach Quelle, Ziel und ID; "
        "die Richtung entspricht der Speicherung in `t_connector`."
    )
    add("")
    if not modell.kanten:
        add("_Keine Beziehungen._")
        add("")
    for kante in modell.kanten:
        name = _code(kante.name) if kante.name else LEER
        add(
            f"- `{_code(kante.quelle)}` \u2192 `{_code(kante.ziel)}`"
            f" \u2014 Typ: `{_code(kante.typ or LEER)}`"
            f" \u00b7 Stereotyp: `{_code(kante.stereotype or LEER)}`"
            f" \u00b7 Name: `{name}`"
            f" \u00b7 ID: `{kante.id}`"
            f" \u00b7 GUID: `{_code(kante.guid or LEER)}`"
            f" \u00b7 Quelle-GUID: `{_code(kante.start_guid or LEER)}`"
            f" \u00b7 Ziel-GUID: `{_code(kante.end_guid or LEER)}`"
            f" \u00b7 Richtung: `{_code(kante.direction or LEER)}`"
        )
    add("")

    add("## Sichten")
    add("")
    add(
        f"{kennzahlen['sichten']} Sichten (Diagramme) mit Name und Typ; "
        "Koordinaten und Layout werden bewusst nicht exportiert."
    )
    add("")
    if not modell.sichten:
        add("_Keine Sichten._")
        add("")
    for sicht in modell.sichten:
        paket = modell.pakete.get(sicht.paket_id)
        paket_path = paket.path if paket is not None else ""
        suffix = f" \u00b7 Paket: `{_code(paket_path)}`" if paket_path else ""
        add(
            f"- **{_md(sicht.name) if sicht.name else OHNE_NAMEN}**"
            f" \u2014 Typ: `{_code(sicht.typ or LEER)}`"
            f" \u00b7 ID: `{sicht.id}`"
            f" \u00b7 GUID: `{_code(sicht.guid or LEER)}`"
            f"{suffix}"
        )

    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Belege (JSON)
# --------------------------------------------------------------------------


def erstelle_belege(modell: Modell) -> dict[str, Any]:
    """Baut die maschinenlesbare Belegdatei (stabil sortiert)."""
    pakete = [
        {"pfad": paket.path, "id": paket.id, "guid": paket.guid}
        for paket in sorted(modell.pakete.values(), key=lambda item: (item.path.casefold(), item.id))
    ]
    elemente = [
        {
            "id": element.id,
            "guid": element.guid,
            "name": element.name,
            "stereotyp": element.stereotype,
            "paket": modell.pakete[element.paket_id].path
            if element.paket_id in modell.pakete
            else "",
            "tags": dict(modell.tags.get(element.id, {})),
            "tags_xref": dict(modell.tags_xref.get(element.id, {})),
        }
        for element in modell.elemente
    ]
    kanten = [
        {
            "id": kante.id,
            "guid": kante.guid,
            "typ": kante.typ,
            "stereotyp": kante.stereotype,
            "quelle": kante.quelle,
            "ziel": kante.ziel,
            "name": kante.name,
        }
        for kante in modell.kanten
    ]
    sichten = [
        {"id": sicht.id, "guid": sicht.guid, "name": sicht.name, "typ": sicht.typ}
        for sicht in modell.sichten
    ]
    return {
        "format_version": FORMAT_VERSION,
        "quelle": {
            "datei": modell.quelle.name,
            "sha256": modell.sha256,
            "kennzahlen": dict(modell.kennzahlen),
        },
        "pakete": pakete,
        "elemente": elemente,
        "kanten": kanten,
        "sichten": sichten,
    }


def _dump_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def export_documentation(
    qea_path: str | Path,
    md_path: str | Path,
    json_path: str | Path,
    *,
    max_elements: int | None = None,
) -> dict[str, Any]:
    """Exportiert eine .qea nach Markdown + JSON und liefert die Kennzahlen.

    ``max_elements`` begrenzt die Zahl der dokumentierten Elemente
    (deterministisch nach Paketpfad/Name/ID); die Kennzahl ``gekuerzt`` zeigt
    an, ob gekuerzt wurde.
    """
    modell = lade_modell(qea_path, max_elements=max_elements)
    markdown = erstelle_markdown(modell)
    belege = erstelle_belege(modell)

    md_file = Path(md_path)
    json_file = Path(json_path)
    _write_text(md_file, markdown)
    _write_text(json_file, _dump_json(belege))
    return dict(modell.kennzahlen)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="roundtrip_export.py",
        description="Exportiert eine .qea als Markdown-Dokumentation und JSON-Belege.",
    )
    parser.add_argument("quelle", help="Pfad zur .qea-Datei (Sparx EA, SQLite)")
    parser.add_argument("--md", required=True, help="Zielpfad der Markdown-Datei")
    parser.add_argument("--belege", required=True, help="Zielpfad der JSON-Belegdatei")
    parser.add_argument(
        "--max-elements",
        type=int,
        default=None,
        metavar="N",
        help="maximale Zahl dokumentierter Elemente (Default: alle)",
    )
    args = parser.parse_args(argv)

    try:
        kennzahlen = export_documentation(
            args.quelle,
            args.md,
            args.belege,
            max_elements=args.max_elements,
        )
    except (RoundtripExportError, OSError) as error:
        print(f"roundtrip_export: {error}", file=sys.stderr)
        return 2

    print(
        "Export ok: "
        f"{kennzahlen['pakete']} Pakete, {kennzahlen['elemente']} Elemente, "
        f"{kennzahlen['kanten']} Kanten, {kennzahlen['sichten']} Sichten"
    )
    print(f"Markdown: {args.md}")
    print(f"Belege:   {args.belege}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
