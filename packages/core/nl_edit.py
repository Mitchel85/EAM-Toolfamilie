"""nl_edit.py -- Natuerlichsprachliche Korrekturen an einer .qea.

Der Weg ist absichtlich zweistufig und sicher:

1. Aus einer Anweisung wird eine **Vorschlagsliste** von Operationen. Mit
   Sprachmodell geschieht das ueber einen strengen JSON-Vertrag, ohne
   Sprachmodell ueber eine kleine, feste Befehlsgrammatik.
2. Jede Operation wird gegen das **geladene Modell** aufgeloest. Namen, die
   dort nicht vorkommen, werden abgelehnt -- das Modell erfindet keine Ziele.
3. Erst ein zweiter Aufruf schreibt die Aenderungen in eine **neue** Datei.
   Loeschoperationen verlangen zusaetzlich eine ausdrueckliche Bestaetigung.

Damit gilt auch hier: die KI schlaegt vor, das Modell entscheidet. Ohne
Backend bleibt der Weg vollstaendig nutzbar (``--backend`` fehlt).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import extract
import model_edit

__all__ = [
    "NlEditError",
    "Element",
    "Connector",
    "Inventory",
    "Proposal",
    "read_inventory",
    "parse_command",
    "propose",
    "apply",
    "preview_lines",
]

#: Operationen, die Daten entfernen. Sie brauchen eine Bestaetigung.
DESTRUCTIVE = frozenset({"delete_element", "delete_connector"})

#: Kanonische Namen und die vom Sprachmodell oft gelieferten Synonyme.
_OP_ALIASES: dict[str, str] = {
    "rename": "set_name",
    "renameelement": "set_name",
    "umbenennen": "set_name",
    "setname": "set_name",
    "set_name": "set_name",
    "setnote": "set_note",
    "set_note": "set_note",
    "notiz": "set_note",
    "setstatus": "set_status",
    "set_status": "set_status",
    "status": "set_status",
    "setalias": "set_alias",
    "set_alias": "set_alias",
    "alias": "set_alias",
    "setstereotype": "set_stereotype",
    "set_stereotype": "set_stereotype",
    "stereotype": "set_stereotype",
    "removeelement": "delete_element",
    "deleteelement": "delete_element",
    "delete_element": "delete_element",
    "loeschen": "delete_element",
    "addconnector": "add_connector",
    "add_connector": "add_connector",
    "removeconnector": "delete_connector",
    "deleteconnector": "delete_connector",
    "delete_connector": "delete_connector",
}

_SIMPLE_OPS = ("set_name", "set_note", "set_status", "set_alias", "set_stereotype")

#: Deutsche Bezeichnungen fuer Beziehungstypen (nur Vorschlaege, keine Pflicht).
_CONNECTOR_TYPES: dict[str, str] = {
    "abhaengigkeit": "Dependency",
    "abhängigkeit": "Dependency",
    "dependency": "Dependency",
    "realisierung": "Realisation",
    "realisation": "Realisation",
    "verallgemeinerung": "Generalization",
    "generalization": "Generalization",
    "generalisierung": "Generalization",
    "aggregation": "Aggregation",
    "zusammensetzung": "Composition",
    "composition": "Composition",
    "informationsfluss": "InformationFlow",
    "informationflow": "InformationFlow",
    "steuerfluss": "ControlFlow",
    "controlflow": "ControlFlow",
    "zustandsfluss": "StateFlow",
    "stateflow": "StateFlow",
    "benutzung": "Usage",
    "usage": "Usage",
    "abstraktion": "Abstraction",
    "abstraction": "Abstraction",
}

_VERBS = (
    "benenne|nenne|umbenennen|umbenenne|setze|aendere|ändere|ergaenze|ergänze|"
    "ueberschreibe|überschreibe|loesche|lösche|entferne|verbinde|verknuepfe|"
    "verknüpfe|trenne|loese|löse"
)


class NlEditError(ValueError):
    """Anweisung nicht eindeutig, Ziel nicht vorhanden oder Eingabe ungueltig."""


@dataclass(frozen=True)
class Element:
    guid: str
    name: str
    package: str
    stereotype: str = ""
    alias: str = ""
    note: str = ""
    status: str = ""
    object_id: int = 0


@dataclass(frozen=True)
class Connector:
    guid: str
    name: str
    stereotype: str
    source_guid: str
    target_guid: str
    source: str
    target: str


@dataclass(frozen=True)
class Inventory:
    path: Path
    packages: tuple[str, ...]
    elements: tuple[Element, ...]
    connectors: tuple[Connector, ...]

    def by_guid(self, guid: str) -> Element | None:
        key = guid.strip().strip("{}").upper()
        for element in self.elements:
            if element.guid.strip("{}").upper() == key:
                return element
        return None


def _text(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = row[name] if name in row.keys() else None
        if value is not None:
            return str(value)
    return ""


def _package_paths(con: sqlite3.Connection) -> dict[int, str]:
    rows = {
        int(row["Package_ID"]): row
        for row in con.execute("SELECT Package_ID, Name, Parent_ID FROM t_package")
    }
    paths: dict[int, str] = {}

    def path_of(package_id: int) -> str:
        if package_id in paths:
            return paths[package_id]
        parts: list[str] = []
        seen: set[int] = set()
        current = package_id
        while current in rows and current not in seen:
            seen.add(current)
            parts.append(_text(rows[current], "Name").strip())
            current = int(rows[current]["Parent_ID"] or 0)
        result = "/".join(reversed(parts))
        paths[package_id] = result
        return result

    for package_id in rows:
        path_of(package_id)
    return paths


def read_inventory(path: str | Path) -> Inventory:
    """Liest Pakete, Elemente und Kanten samt GUIDs aus einer .qea."""

    source = Path(path)
    if not source.is_file():
        raise NlEditError(f"{source}: Modell nicht gefunden")
    try:
        con = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - seltene Dateifehler
        raise NlEditError(f"{source}: nicht lesbar ({exc})") from exc
    con.row_factory = sqlite3.Row
    try:
        tables = {
            str(row["name"])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "t_object" not in tables or "t_package" not in tables:
            raise NlEditError(f"{source}: keine EA-Struktur (t_object/t_package fehlt)")
        paths = _package_paths(con)
        elements: list[Element] = []
        by_id: dict[int, Element] = {}
        for row in con.execute(
            "SELECT * FROM t_object WHERE coalesce(Object_Type, '') <> 'Package' ORDER BY Object_ID"
        ):
            package_id = int(row["Package_ID"] or 0)
            element = Element(
                guid=_text(row, "ea_guid").strip(),
                name=_text(row, "Name"),
                package=paths.get(package_id, ""),
                stereotype=_text(row, "Stereotype"),
                alias=_text(row, "Alias"),
                note=_text(row, "Note", "Notes"),
                status=_text(row, "Status"),
                object_id=int(row["Object_ID"] or 0),
            )
            elements.append(element)
            by_id[element.object_id] = element

        connectors: list[Connector] = []
        if "t_connector" in tables:
            for row in con.execute("SELECT * FROM t_connector ORDER BY Connector_ID"):
                start = by_id.get(int(row["Start_Object_ID"] or 0))
                end = by_id.get(int(row["End_Object_ID"] or 0))
                if start is None or end is None:
                    continue
                connectors.append(
                    Connector(
                        guid=_text(row, "ea_guid").strip(),
                        name=_text(row, "Name"),
                        stereotype=_text(row, "Stereotype"),
                        source_guid=start.guid,
                        target_guid=end.guid,
                        source=start.name,
                        target=end.name,
                    )
                )
        return Inventory(
            path=source,
            packages=tuple(sorted(set(paths.values()))),
            elements=tuple(elements),
            connectors=tuple(connectors),
        )
    finally:
        con.close()


def _norm(value: str) -> str:
    return " ".join(value.strip().strip('"').strip("'").split()).casefold()


def _clean_ref(value: str) -> str:
    text = value.strip().strip('"').strip("'").strip()
    text = re.sub(r"^(?:das|der|die|den)\s+(?:element|paket)\s+", "", text, flags=re.I)
    text = re.sub(r"^(?:element|paket)\s+", "", text, flags=re.I)
    return text.strip().strip('"').strip("'").strip(" .,;:")


def _package_matches(element: Element, package: str | None) -> bool:
    if not package:
        return True
    wanted = package.strip().replace(" / ", "/").strip("/").casefold()
    actual = element.package.replace(" / ", "/").strip("/").casefold()
    return actual == wanted or actual.endswith("/" + wanted) or wanted.endswith("/" + actual)


def resolve_element(inventory: Inventory, ref: str, package: str | None = None) -> Element:
    """Loest einen Namen against das Inventar auf; nie raten."""

    name = _clean_ref(ref)
    if not name:
        raise NlEditError("Elementname fehlt")
    exact = [e for e in inventory.elements if _norm(e.name) == _norm(name)]
    if package:
        exact = [e for e in exact if _package_matches(e, package)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        packages = ", ".join(sorted({e.package or "(ohne Paket)" for e in exact}))
        raise NlEditError(
            f"Element {name!r} ist nicht eindeutig ({len(exact)} Treffer in {packages}) -- Paket angeben"
        )
    # Nur fuer die Fehlermeldung: aehnliche Namen nennen, nicht automatisch waehlen.
    needle = _norm(name)
    near = [
        f"{e.package}::{e.name}"
        for e in inventory.elements
        if needle in _norm(e.name) or _norm(e.name) in needle
    ][:5]
    hint = f" -- meintest du: {', '.join(near)}" if near else ""
    raise NlEditError(f"Kein Element {name!r} im Modell{hint}")


def _resolve_connector(
    inventory: Inventory,
    *,
    source: str | None = None,
    target: str | None = None,
    stereotype: str = "",
    guid: str = "",
    name: str = "",
) -> Connector:
    if guid:
        key = guid.strip().strip("{}").upper()
        hits = [c for c in inventory.connectors if c.guid.strip("{}").upper() == key]
        if len(hits) == 1:
            return hits[0]
        raise NlEditError(f"Keine Kante mit ea_guid {guid}")
    hits = list(inventory.connectors)
    if name:
        hits = [c for c in hits if _norm(c.name) == _norm(name)]
    if source:
        source_el = resolve_element(inventory, source)
        hits = [c for c in hits if c.source_guid == source_el.guid]
    if target:
        target_el = resolve_element(inventory, target)
        hits = [c for c in hits if c.target_guid == target_el.guid]
    if stereotype:
        hits = [c for c in hits if _norm(c.stereotype) == _norm(stereotype)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise NlEditError("Keine passende Beziehung gefunden")
    raise NlEditError(f"Beziehung ist nicht eindeutig ({len(hits)} Treffer) -- Stereotyp oder GUID angeben")


def _split_clauses(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\s*;\s*", text) if p.strip()]
    result: list[str] = []
    for part in parts:
        chunks = re.split(rf"\s+und\s+(?=(?:{_VERBS})\b)", part, flags=re.I)
        result.extend(chunk.strip() for chunk in chunks if chunk.strip())
    return result


def _parse_clause(clause: str) -> list[dict[str, Any]]:
    text = clause.strip().rstrip(".!").strip()
    text = (
        text.replace("„", '"')
        .replace("“", '"')
        .replace("‚", "'")
        .replace("‘", "'")
        .replace("«", '"')
        .replace("»", '"')
    )
    text = re.sub(r"^(?:bitte\s+|kannst\s+du\s+(?:bitte\s+)?)", "", text, flags=re.I)
    if re.match(r"^(?:benenne|nenne|umbenennen|umbenenne)\b", text, flags=re.I):
        text = re.sub(r"\s+um$", "", text, flags=re.I)

    # 1. Beziehung entfernen (vor "entferne <Element>", sonst frisst es den Satz).
    match = re.match(
        rf"^(?:trenne|loese|löse|entferne)\s+(?:die\s+)?(?:beziehung|verbindung|kante)\s+"
        rf"(?:zwischen\s+)?(.+?)\s+(?:und|von)\s+(.+?)(?:\s+(?:mit|ueber|über)\s+(.+))?$",
        text,
        flags=re.I,
    )
    if match:
        op: dict[str, Any] = {
            "op": "delete_connector",
            "source": _clean_ref(match.group(1)),
            "target": _clean_ref(match.group(2)),
        }
        if match.group(3):
            op["stereotype"] = _clean_ref(match.group(3))
        return [op]

    # 2. Beziehung anlegen.
    match = re.match(
        rf"^(?:verbinde|verknuepfe|verknüpfe)\s+(.+?)\s+mit\s+(.+?)"
        rf"(?:\s+(?:ueber|über|via|als)\s+(.+))?$",
        text,
        flags=re.I,
    )
    if not match:
        match = re.match(
            rf"^(?:erstelle|fuege|füge)\s+(?:eine\s+)?(?:beziehung|verbindung|kante)\s+"
            rf"(?:von\s+)?(.+?)\s+(?:nach|zu|mit)\s+(.+?)(?:\s+(?:ueber|über|via|als)\s+(.+))?$",
            text,
            flags=re.I,
        )
    if match:
        raw_type = _clean_ref(match.group(3)) if match.group(3) else ""
        kind = _CONNECTOR_TYPES.get(_norm(raw_type), raw_type or "Dependency")
        return [
            {
                "op": "add_connector",
                "source": _clean_ref(match.group(1)),
                "target": _clean_ref(match.group(2)),
                "stereotype": kind,
                "ea_type": "Dependency",
            }
        ]

    # 3. Feldoperationen. Reihenfolge: laengere Schluesselworte zuerst.
    for pattern, op_name in (
        (r"notiz|beschreibung", "set_note"),
        (r"status", "set_status"),
        (r"alias|kurzname", "set_alias"),
        (r"stereotyp(?:en)?", "set_stereotype"),
    ):
        match = re.match(
            rf"^(?:setze|aendere|ändere|ergaenze|ergänze|ueberschreibe|überschreibe)\s+"
            rf"(?:die\s+|den\s+)?(?:{pattern})\s+"
            rf"(?:von|bei|fuer|für|des\s+elements|der)\s+(.+?)\s+(?:auf|zu)\s+(.+)$",
            text,
            flags=re.I,
        )
        if match:
            return [
                {
                    "op": op_name,
                    "name": _clean_ref(match.group(1)),
                    "value": match.group(2).strip().strip('"').strip("'"),
                }
            ]

    # 4. Umbenennen (auch ueber das Feld "Name").
    match = re.match(
        r"^(?:aendere|ändere|setze)\s+den\s+namen\s+(?:von|bei|fuer|für)\s+(.+?)\s+"
        r"(?:in|auf|zu)\s+(.+)$",
        text,
        flags=re.I,
    )
    if match:
        new_name = _clean_ref(match.group(2))
        if not new_name:
            raise NlEditError("Neuer Name fehlt")
        return [{"op": "set_name", "name": _clean_ref(match.group(1)), "value": new_name}]

    match = re.match(
        rf"^(?:benenne|umbenennen|umbenenne|nenne)\s+(?:das\s+)?(?:element\s+)?(.+?)\s+"
        rf"(?:in|zu|um\s+in)\s+(.+)$",
        text,
        flags=re.I,
    )
    if match:
        new_name = _clean_ref(match.group(2))
        if not new_name:
            raise NlEditError("Neuer Name fehlt")
        return [{"op": "set_name", "name": _clean_ref(match.group(1)), "value": new_name}]

    # 5. Loeschen.
    match = re.match(
        rf"^(?:loesche|lösche|entferne)\s+(?:das\s+)?(?:element\s+)?(.+)$",
        text,
        flags=re.I,
    )
    if match:
        return [{"op": "delete_element", "name": _clean_ref(match.group(1))}]

    raise NlEditError(f"Anweisung nicht verstanden: {clause!r}")


def parse_command(text: str) -> list[dict[str, Any]]:
    """Kleine, feste Befehlsgrammatik -- ohne Sprachmodell nutzbar."""

    if not isinstance(text, str) or not text.strip():
        raise NlEditError("Anweisung fehlt")
    clauses = _split_clauses(text)
    if not clauses:
        raise NlEditError("Anweisung fehlt")
    ops: list[dict[str, Any]] = []
    for clause in clauses:
        ops.extend(_parse_clause(clause))
    return ops


def _inventory_text(inventory: Inventory, *, max_elements: int = 400) -> str:
    lines = [
        f"Pakete ({len(inventory.packages)}): " + ", ".join(inventory.packages[:80]),
        f"Elemente ({len(inventory.elements)}):",
    ]
    for element in inventory.elements[:max_elements]:
        alias = f" (Alias: {element.alias})" if element.alias else ""
        lines.append(f"- {element.package}::{element.name} «{element.stereotype}»{alias}")
    if len(inventory.elements) > max_elements:
        lines.append(f"- … {len(inventory.elements) - max_elements} weitere Elemente (nicht gelistet)")
    if inventory.connectors:
        lines.append(f"Beziehungen ({len(inventory.connectors)}), erste 80:")
        for connector in inventory.connectors[:80]:
            lines.append(
                f"- {connector.source} -«{connector.stereotype}»→ {connector.target}"
            )
    return "\n".join(lines)


_SYSTEM_PROMPT = """Du bist ein Assistent fuer Enterprise-Architekturmodelle.
Der Nutzer will ein vorhandenes Modell in natuerlicher Sprache korrigieren.
Du erfindest keine Elemente, Pakete oder Beziehungen. Du verwendest ausschliesslich
Namen, die im mitgelieferten Inventar vorkommen.

Antworte NUR mit gueltigem JSON in genau dieser Form:
{"reply":"kurze Antwort auf Deutsch","ops":[{...}]}

Erlaubte Operationen (Feld op):
- set_name:        {"op":"set_name","package":"Paket/Pfad","name":"Alt","value":"Neu"}
- set_note:        {"op":"set_note","package":"Paket/Pfad","name":"Element","value":"Neuer Text"}
- set_status:      {"op":"set_status","package":"Paket/Pfad","name":"Element","value":"Proposed"}
- set_alias:       {"op":"set_alias","package":"Paket/Pfad","name":"Element","value":"Kurzname"}
- set_stereotype:  {"op":"set_stereotype","package":"Paket/Pfad","name":"Element","value":"Capability"}
- delete_element:  {"op":"delete_element","package":"Paket/Pfad","name":"Element"}
- add_connector:   {"op":"add_connector","source":"Paket/Pfad::Name","target":"Paket/Pfad::Name","stereotype":"Dependency","ea_type":"Dependency"}
- delete_connector:{"op":"delete_connector","source":"Paket/Pfad::Name","target":"Paket/Pfad::Name","stereotype":"Dependency"}

Regeln:
1. "package" ist der vollstaendige Paketpfad mit "/" als Trenner.
2. Wenn ein Name im Inventar nicht eindeutig ist, nimm den Paketpfad mit auf.
3. Loeschen nur, wenn der Nutzer es ausdruecklich verlangt.
4. Keine Operation erfinden, um die Anweisung "irgendwie" zu erfuellen; lieber
   eine leere ops-Liste und eine erklaerende reply.
5. Antworte auf Deutsch, ohne Markdown."""


def _parse_llm_json(raw: str) -> tuple[str, list[dict[str, Any]]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NlEditError(f"KI-Antwort ist kein gueltiges JSON: {exc}") from exc
    if isinstance(payload, list):
        return "", [dict(item) for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        raise NlEditError("KI-Antwort ist kein JSON-Objekt")
    reply = str(payload.get("reply") or "")
    ops_raw = payload.get("ops")
    if ops_raw is None:
        ops_raw = payload.get("operationen") or []
    if not isinstance(ops_raw, Sequence) or isinstance(ops_raw, (str, bytes)):
        raise NlEditError("KI-Antwort: 'ops' ist keine Liste")
    return reply, [dict(item) for item in ops_raw if isinstance(item, Mapping)]


def _normalize_op(op: Mapping[str, Any]) -> dict[str, Any]:
    raw_name = str(op.get("op") or op.get("operation") or "").strip()
    canonical = _OP_ALIASES.get(raw_name.casefold(), raw_name)
    if canonical not in _OP_ALIASES.values():
        raise NlEditError(f"Unbekannte Operation {raw_name!r}")
    result = dict(op)
    result["op"] = canonical

    if canonical in _SIMPLE_OPS or canonical == "delete_element":
        if not result.get("name"):
            target = result.get("target")
            if isinstance(target, str):
                result["name"] = target
            elif isinstance(target, Mapping):
                result["name"] = target.get("name", "")
                result.setdefault("package", target.get("package", ""))
        if canonical == "set_name":
            if "value" not in result:
                for key in ("to", "neu", "new"):
                    if key in result:
                        result["value"] = result[key]
                        break
        if canonical in ("set_note", "set_status", "set_alias", "set_stereotype"):
            if "value" not in result:
                for key in ("to", "neu", "new", "text"):
                    if key in result:
                        result["value"] = result[key]
                        break
    elif canonical == "add_connector":
        if "source" not in result:
            result["source"] = result.get("from", result.get("quelle", ""))
        if "target" not in result:
            result["target"] = result.get("to", result.get("ziel", ""))
        result.setdefault("stereotype", "")
        result.setdefault("ea_type", "Dependency")
    elif canonical == "delete_connector":
        if "source" not in result:
            result["source"] = result.get("from", result.get("quelle", ""))
        if "target" not in result:
            result["target"] = result.get("to", result.get("ziel", ""))
    return result


def _prepare_ops(
    inventory: Inventory, raw_ops: Iterable[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    ops: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, raw in enumerate(raw_ops, start=1):
        try:
            op = _normalize_op(raw)
            kind = op["op"]
            if kind in _SIMPLE_OPS:
                element = resolve_element(inventory, str(op.get("name") or ""), op.get("package"))
                value = op.get("value")
                if not isinstance(value, str):
                    raise NlEditError("Feld 'value' fehlt oder ist kein Text")
                if kind == "set_name" and not value.strip():
                    raise NlEditError("Neuer Name darf nicht leer sein")
                old = {
                    "set_name": element.name,
                    "set_note": element.note,
                    "set_status": element.status,
                    "set_alias": element.alias,
                    "set_stereotype": element.stereotype,
                }[kind]
                if old == value:
                    warnings.append(
                        f"{index}. {element.name}: Wert ist bereits {value!r} -- keine Aenderung"
                    )
                    continue
                prepared = {
                    "op": kind,
                    "guid": element.guid,
                    "package": element.package,
                    "name": element.name,
                    "value": value,
                }
                ops.append(prepared)
            elif kind == "delete_element":
                element = resolve_element(inventory, str(op.get("name") or ""), op.get("package"))
                ops.append(
                    {
                        "op": "delete_element",
                        "guid": element.guid,
                        "package": element.package,
                        "name": element.name,
                    }
                )
            elif kind == "add_connector":
                source = resolve_element(inventory, str(op.get("source") or ""))
                target = resolve_element(inventory, str(op.get("target") or ""))
                if source.guid == target.guid:
                    raise NlEditError("Quelle und Ziel sind dasselbe Element")
                stereotype = str(op.get("stereotype") or "").strip()
                if stereotype:
                    stereotype = _CONNECTOR_TYPES.get(_norm(stereotype), stereotype)
                ops.append(
                    {
                        "op": "add_connector",
                        "source": {"guid": source.guid},
                        "target": {"guid": target.guid},
                        "source_name": f"{source.package}::{source.name}",
                        "target_name": f"{target.package}::{target.name}",
                        "stereotype": stereotype,
                        "ea_type": str(op.get("ea_type") or "Dependency"),
                        "name": str(op.get("name") or ""),
                    }
                )
            elif kind == "delete_connector":
                connector = _resolve_connector(
                    inventory,
                    source=op.get("source"),
                    target=op.get("target"),
                    stereotype=str(op.get("stereotype") or ""),
                    guid=str(op.get("guid") or ""),
                    name=str(op.get("name") or ""),
                )
                ops.append(
                    {
                        "op": "delete_connector",
                        "guid": connector.guid,
                        "name": connector.name,
                        "stereotype": connector.stereotype,
                    }
                )
            else:  # pragma: no cover - durch _normalize_op ausgeschlossen
                raise NlEditError(f"Operation {kind!r} wird nicht unterstuetzt")
        except NlEditError as exc:
            raise NlEditError(f"Operation {index}: {exc}") from exc
    return ops, warnings


@dataclass
class Proposal:
    instruction: str
    ops: list[dict[str, Any]]
    reply: str = ""
    backend: str = "ohne KI"
    warnings: list[str] = field(default_factory=list)
    source: Path | None = None

    @property
    def destructive(self) -> bool:
        return any(op.get("op") in DESTRUCTIVE for op in self.ops)

    def as_dict(self) -> dict[str, Any]:
        return {
            "anweisung": self.instruction,
            "antwort": self.reply,
            "backend": self.backend,
            "operationen": self.ops,
            "warnungen": self.warnings,
            "loescht": self.destructive,
        }


def preview_lines(proposal: Proposal) -> list[str]:
    lines: list[str] = []
    for index, op in enumerate(proposal.ops, start=1):
        kind = op["op"]
        if kind in _SIMPLE_OPS:
            label = {
                "set_name": "umbenennen",
                "set_note": "Notiz aendern",
                "set_status": "Status setzen",
                "set_alias": "Alias setzen",
                "set_stereotype": "Stereotyp setzen",
            }[kind]
            lines.append(
                f"{index}. {label}: {op.get('package')}::{op.get('name')} -> {op.get('value')!r}"
            )
        elif kind == "delete_element":
            lines.append(f"{index}. LOESCHEN: {op.get('package')}::{op.get('name')} (samt Kanten)")
        elif kind == "add_connector":
            lines.append(
                f"{index}. Beziehung anlegen: {op.get('source_name')} -> "
                f"{op.get('target_name')} «{op.get('stereotype')}»"
            )
        elif kind == "delete_connector":
            lines.append(f"{index}. Beziehung loeschen: {op.get('name') or op.get('guid')}")
    return lines


def _badge(backend: Any) -> str:
    return getattr(backend, "name", "") or type(backend).__name__ or "KI"


def propose(
    qea: str | Path,
    instruction: str,
    *,
    backend: extract.Backend | None = None,
) -> Proposal:
    """Erzeugt einen Vorschlag, ohne die Datei zu veraendern."""

    inventory = read_inventory(qea)
    text = instruction.strip()
    if not text:
        raise NlEditError("Anweisung fehlt")
    if backend is None:
        raw_ops = parse_command(text)
        reply = "Vorschlag aus der Befehlsgrammatik (ohne KI)."
        backend_name = "ohne KI"
    else:
        prompt = (
            _SYSTEM_PROMPT
            + "\n\nINVENTAR DES MODELLS:\n"
            + _inventory_text(inventory)
            + "\n\nANWEISUNG DES NUTZERS:\n"
            + text
        )
        raw = backend.complete(prompt)
        reply, raw_ops = _parse_llm_json(raw)
        backend_name = _badge(backend)
    if not raw_ops:
        raise NlEditError("Die Anweisung ergab keine Operation" + (f": {reply}" if reply else ""))
    ops, warnings = _prepare_ops(inventory, raw_ops)
    if not ops:
        raise NlEditError("Keine wirksame Operation" + (f": {reply}" if reply else ""))
    return Proposal(
        instruction=text,
        ops=ops,
        reply=reply,
        backend=backend_name,
        warnings=warnings,
        source=inventory.path,
    )


def apply(
    proposal: Proposal,
    out: str | Path,
    *,
    mdg: str | Path | None = None,
    confirm: bool = False,
) -> model_edit.EditResult:
    """Schreibt den Vorschlag in eine neue Datei; Original bleibt unberuehrt."""

    if proposal.destructive and not confirm:
        raise NlEditError(
            "Der Vorschlag enthaelt eine Loeschoperation. Mit confirm=True bzw. --ja bestaetigen."
        )
    if proposal.source is None:
        raise NlEditError("Vorschlag ohne Quelldatei")
    return model_edit.edit_model(proposal.source, proposal.ops, out, mdg=mdg)
