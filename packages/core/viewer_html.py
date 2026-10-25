"""viewer_html.py -- grafische Pruefung einer gebauten .qea als *eine* HTML-Datei.

Der Viewer ist das Gegenstueck zur Zahlenpruefung: er zeigt, was wirklich in
der Datenbank steht -- Knoten, Kanten, Paketfarben, Stereotype, Notizen.
Er laeuft ohne Server, ohne Netz, ohne Build-Schritt: die Graph-Daten stehen
als JSON in der Datei, gezeichnet wird mit Canvas und Vanilla-JS.

Aufruf::

    python3 viewer_html.py modell.qea --out viewer.html
    python3 viewer_html.py modell.qea --out viewer.html --max-knoten 800

Oeffentliche API (auch von ``webui.py`` benutzt)::

    from viewer_html import build_html, read_model, render_html, ViewerError

    html_text = build_html("modell.qea")
    model = read_model("modell.qea", max_nodes=800)

Entscheidungen:

- Gelesen wird die SQLite-Datei direkt und **nur lesend** (``mode=ro`` plus
  ``PRAGMA query_only``). Die Kanten enden auf ``Object_ID``; damit braucht der
  Viewer keine Rekonstruktion der IR-Referenzen und zeigt garantiert dieselben
  Endpunkte wie EA.
- ``t_object.Object_Type = 'Package'`` sind Paketspiegel, keine Elemente. Sie
  werden -- wie im Reader -- uebersprungen. Kanten, die auf einen Spiegel
  zeigen, werden gezaehlt, aber nicht gezeichnet (der Graph hat dort keinen
  Knoten).
- Farben: eine Farbe je oberstem Paket. Gibt es nur *ein* Wurzelpaket (der
  Normalfall: ``MASC/...``), wird die zweite Ebene gefaerbt -- sonst waere das
  ganze Modell einfach. Die Regel steht auch in der Legende.
- Das Layout startet deterministisch: Pakete bekommen Plaetze auf einer
  Golden-Winkel-Spirale, Elemente einen Kreis darum. Im Browser laeuft dann
  ein Force-Layout ohne Zufall weiter -- zwei Laeufe liefern byte-identische
  Dateien.
- Notizen werden bei ``NOTE_CHARS`` gekuerzt (mit Hinweis), damit auch grosse
  Modelle unter der Groessengrenze bleiben.
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

DEFAULT_MAX_NODES = 6000
NOTE_CHARS = 2000
VIEWER_VERSION = "1.0"

#: Farbpalette fuer die obersten Pakete. Reihenfolge = Vergabe; bewusst
#: kontrastreich auf dunklem Grund und auch bei Rot/Gruen-Schwaeche trennbar.
GROUP_COLORS = (
    "#4f9cf9",
    "#f2b544",
    "#4ade80",
    "#f472b6",
    "#a78bfa",
    "#2dd4bf",
    "#fb923c",
    "#e879f9",
    "#93c5fd",
    "#facc15",
    "#34d399",
    "#f87171",
    "#c4b5fd",
    "#67e8f9",
    "#fdba74",
    "#a3e635",
)


class ViewerError(ValueError):
    """Die Datei ist keine lesbare .qea oder der Aufruf ist unbrauchbar."""


# --------------------------------------------------------------------------
# Datenmodell
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ViewerModel:
    """Was gezeichnet wird -- plus die Zahlen, die der Kopf anzeigt."""

    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    packages: tuple[dict[str, Any], ...]
    groups: tuple[dict[str, Any], ...]
    counts: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "viewer_version": VIEWER_VERSION,
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "packages": list(self.packages),
            "groups": list(self.groups),
            "counts": dict(self.counts),
        }


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise ViewerError(f"{path}: Datei existiert nicht")
    if not path.is_file():
        raise ViewerError(f"{path}: keine regulaere Datei")
    uri = "file:" + quote(path.resolve().as_posix(), safe="/") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as error:
        raise ViewerError(f"{path}: keine lesbare SQLite-Datenbank ({error})") from error
    return con


def _table_names(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
    return {str(row[0]).lower(): str(row[0]) for row in rows}


def _columns(con: sqlite3.Connection, table: str) -> dict[str, str]:
    quoted = '"' + table.replace('"', '""') + '"'
    return {
        str(row[1]).lower(): str(row[1])
        for row in con.execute(f"PRAGMA table_info({quoted})")
    }


def _pick(columns: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        if name.lower() in columns:
            return columns[name.lower()]
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_note(value: Any) -> str:
    text = html_module.unescape(_text(value)).replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()
    if len(text) > NOTE_CHARS:
        text = text[:NOTE_CHARS].rstrip() + " [...]"
    return text


def _package_rows(con: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns = _columns(con, table)
    id_column = _pick(columns, "Package_ID")
    name_column = _pick(columns, "Name")
    parent_column = _pick(columns, "Parent_ID")
    pos_column = _pick(columns, "TPos")
    if id_column is None or name_column is None:
        raise ViewerError(f"Tabelle {table!r} ohne Package_ID/Name -- keine .qea")
    quoted = '"' + table.replace('"', '""') + '"'
    rows: list[dict[str, Any]] = []
    for row in con.execute(f"SELECT * FROM {quoted}"):
        package_id = _int(row[id_column])
        if package_id is None:
            continue
        rows.append(
            {
                "id": package_id,
                "name": _text(row[name_column]).strip(),
                "parent": _int(row[parent_column], 0) if parent_column else 0,
                "pos": _int(row[pos_column], 0) if pos_column else 0,
            }
        )
    rows.sort(key=lambda entry: (entry["pos"], entry["id"]))
    return rows


def _package_paths(rows: Sequence[dict[str, Any]]) -> dict[int, str]:
    """Pfad aus Anzeigenamen. Gleichnamige Geschwister bleiben gleichnamig --
    der Filter arbeitet mit der Package_ID, der Pfad ist nur Anzeige."""
    by_id = {row["id"]: row for row in rows}

    def path_of(package_id: int, seen: frozenset[int] = frozenset()) -> str:
        row = by_id.get(package_id)
        if row is None or package_id in seen:
            return ""
        name = row["name"] or f"Paket {package_id}"
        parent = row["parent"] or 0
        if parent and parent in by_id and parent != package_id:
            prefix = path_of(parent, seen | {package_id})
            return f"{prefix}/{name}" if prefix else name
        return name

    return {package_id: path_of(package_id) for package_id in by_id}


def _group_key(package_path: str, depth: int) -> str:
    parts = [part for part in package_path.split("/") if part]
    if not parts:
        return "(ohne Paket)"
    return "/".join(parts[:depth])


def _color_depth(paths: Iterable[str], minimum: int = 3, maximum: int = 3) -> int:
    """Farbe je Paket welcher Ebene? Die flachste Ebene, die mindestens
    ``minimum`` Gruppen ergibt -- sonst waere ein Modell mit einem Wurzelpaket
    (der Normalfall ``MASC/...``) einfarbig."""
    paths = tuple(paths)
    for depth in range(1, maximum + 1):
        if len({_group_key(path, depth) for path in paths}) >= minimum:
            return depth
    return 1


def _initial_positions(
    nodes: list[dict[str, Any]], package_order: Mapping[str, int]
) -> None:
    """Deterministischer Start: Pakete auf einer Golden-Winkel-Spirale,
    Elemente als kleiner Kranz darum. Kein Zufall, keine Zeitabhaengigkeit."""
    golden = math.pi * (3.0 - math.sqrt(5.0))
    per_package: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        per_package.setdefault(node["pkg"], []).append(node)

    for package_path, members in per_package.items():
        index = package_order.get(package_path, 0)
        radius = 190.0 * math.sqrt(index + 1.0)
        angle = index * golden
        center_x = radius * math.cos(angle)
        center_y = radius * math.sin(angle)
        for position, node in enumerate(members):
            ring = 16.0 + 17.0 * math.sqrt(len(members))
            theta = position * golden
            node["x"] = round(center_x + ring * math.cos(theta), 1)
            node["y"] = round(center_y + ring * math.sin(theta), 1)


def read_model(path: str | Path, *, max_nodes: int = DEFAULT_MAX_NODES) -> ViewerModel:
    """Liest die .qea und baut den Graph. ``max_nodes`` kappt sehr grosse Modelle
    (die abgeschnittenen Knoten werden im Kopf der Seite gemeldet)."""
    if max_nodes < 1:
        raise ViewerError("max_nodes muss mindestens 1 sein")
    target = Path(path)
    con = _open_readonly(target)
    try:
        tables = _table_names(con)
        if "t_object" not in tables or "t_package" not in tables:
            raise ViewerError(
                f"{target.name}: t_object/t_package fehlen -- keine vollstaendige .qea"
            )

        package_rows = _package_rows(con, tables["t_package"])
        paths = _package_paths(package_rows)
        object_table = tables["t_object"]
        columns = _columns(con, object_table)
        object_id_column = _pick(columns, "Object_ID")
        if object_id_column is None:
            raise ViewerError("t_object ohne Object_ID -- keine .qea")
        name_column = _pick(columns, "Name")
        type_column = _pick(columns, "Object_Type")
        stereotype_column = _pick(columns, "Stereotype")
        note_column = _pick(columns, "Note")
        package_column = _pick(columns, "Package_ID")
        quoted = '"' + object_table.replace('"', '""') + '"'

        raw_nodes: list[dict[str, Any]] = []
        mirror_ids: set[int] = set()
        skipped_packages = 0
        for row in con.execute(f"SELECT * FROM {quoted}"):
            object_id = _int(row[object_id_column])
            if object_id is None:
                continue
            ea_type = _text(row[type_column]).strip() if type_column else ""
            if ea_type.lower() == "package":
                mirror_ids.add(object_id)
                skipped_packages += 1
                continue
            package_id = _int(row[package_column]) if package_column else 0
            package_path = paths.get(package_id or 0, "") or "(ohne Paket)"
            raw_nodes.append(
                {
                    "id": object_id,
                    "name": _text(row[name_column]).strip() if name_column else "",
                    "type": ea_type or "Class",
                    "stereo": (
                        _text(row[stereotype_column]).strip() if stereotype_column else ""
                    ),
                    "pkg": package_path,
                    "note": _clean_note(row[note_column]) if note_column else "",
                    "_package_id": package_id or 0,
                }
            )

        # Sortierung ist die Identitaet der Reihenfolge: Paketpfad, Typ, Name, ID.
        raw_nodes.sort(key=lambda n: (n["pkg"], n["type"], n["name"], n["id"]))
        nodes_total = len(raw_nodes)
        omitted = 0
        if len(raw_nodes) > max_nodes:
            omitted = len(raw_nodes) - max_nodes
            raw_nodes = raw_nodes[:max_nodes]

        index_of = {node["id"]: position for position, node in enumerate(raw_nodes)}
        for position, node in enumerate(raw_nodes):
            node["index"] = position
            node["degree"] = 0

        edges: list[dict[str, Any]] = []
        skipped_edges = 0
        omitted_edges = 0
        skipped_missing = 0
        if "t_connector" in tables:
            connector_table = tables["t_connector"]
            connector_columns = _columns(con, connector_table)
            start_column = _pick(connector_columns, "Start_Object_ID")
            end_column = _pick(connector_columns, "End_Object_ID")
            type_column_c = _pick(connector_columns, "Connector_Type")
            stereo_column_c = _pick(connector_columns, "Stereotype")
            name_column_c = _pick(connector_columns, "Name")
            if start_column is None or end_column is None:
                raise ViewerError("t_connector ohne Start_Object_ID/End_Object_ID")
            quoted_c = '"' + connector_table.replace('"', '""') + '"'
            for row in con.execute(f"SELECT * FROM {quoted_c}"):
                start = _int(row[start_column])
                end = _int(row[end_column])
                if start is None or end is None:
                    skipped_missing += 1
                    continue
                source = index_of.get(start)
                target_index = index_of.get(end)
                if source is None or target_index is None:
                    # Paketspiegel sind keine Knoten; alles andere fehlt nur,
                    # weil --max-knoten gekappt hat.
                    if start in mirror_ids or end in mirror_ids:
                        skipped_edges += 1
                    else:
                        omitted_edges += 1
                    continue
                edge: dict[str, Any] = {
                    "s": source,
                    "t": target_index,
                    "type": (_text(row[type_column_c]).strip() if type_column_c else "")
                    or "Connector",
                }
                stereotype = _text(row[stereo_column_c]).strip() if stereo_column_c else ""
                if stereotype:
                    edge["stereo"] = stereotype
                name = _text(row[name_column_c]).strip() if name_column_c else ""
                if name:
                    edge["name"] = name
                edges.append(edge)
                raw_nodes[source]["degree"] += 1
                raw_nodes[target_index]["degree"] += 1

        edges.sort(
            key=lambda e: (e["s"], e["t"], e["type"], e.get("stereo", ""), e.get("name", ""))
        )

        # Gruppen (Farbe) und Pakete (Filter) in stabiler Reihenfolge.
        color_depth = _color_depth(node["pkg"] for node in raw_nodes)
        group_counts: dict[str, int] = {}
        for node in raw_nodes:
            group = _group_key(node["pkg"], color_depth)
            node["group"] = group
            group_counts[group] = group_counts.get(group, 0) + 1
        group_names = sorted(group_counts)
        groups = [
            {
                "name": name,
                "color": GROUP_COLORS[position % len(GROUP_COLORS)],
                "count": group_counts[name],
            }
            for position, name in enumerate(group_names)
        ]
        color_of = {group["name"]: group["color"] for group in groups}
        for node in raw_nodes:
            node["color"] = color_of[node["group"]]
            node.pop("_package_id", None)

        # Filter zaehlt den Teilbaum: ein Klick auf "MASC/Katalog" zeigt auch
        # alles aus "MASC/Katalog/...". Deshalb zaehlt jedes Paket seine
        # Elemente plus die seiner Unterpakete.
        node_paths = [node["pkg"] for node in raw_nodes]
        package_list = []
        for package_id, path_value in sorted(paths.items(), key=lambda item: item[1]):
            if not path_value:
                continue
            prefix = path_value + "/"
            count = sum(
                1 for node_path in node_paths
                if node_path == path_value or node_path.startswith(prefix)
            )
            if count:
                package_list.append({"path": path_value, "count": count, "id": package_id})

        package_order = {entry["path"]: position for position, entry in enumerate(package_list)}
        _initial_positions(raw_nodes, package_order)

        counts = {
            "nodes": len(raw_nodes),
            "nodes_total": nodes_total,
            "edges": len(edges),
            "edges_total": len(edges) + skipped_edges + omitted_edges + skipped_missing,
            "packages": len(package_rows),
            "packages_im_filter": len(package_list),
            "groups": len(groups),
            "omitted_nodes": omitted,
            "skipped_edges": skipped_edges,
            "omitted_edges": omitted_edges,
            "skipped_package_mirrors": skipped_packages,
            "single_root": color_depth > 1,
            "color_depth": color_depth,
            "source": target.name,
        }
        return ViewerModel(
            nodes=tuple(raw_nodes),
            edges=tuple(edges),
            packages=tuple(package_list),
            groups=tuple(groups),
            counts=counts,
        )
    finally:
        con.close()


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------


def _embed_json(payload: Mapping[str, Any]) -> str:
    """JSON fuer einen <script>-Block: '<' und '>' als \\uXXXX.

    Damit kann kein Elementname (auch ``</script>``) den Block verlassen; das
    JSON bleibt gueltig und liest sich mit json.loads unveraendert zurueck.
    """
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_html(model: ViewerModel, *, title: str | None = None) -> str:
    """Setzt die selbsttragende Seite zusammen. Reine Funktion: gleiche Eingabe
    ergibt byte-identische Ausgabe (keine Zeit, keine Zufallswerte)."""
    counts = model.counts
    source = str(counts.get("source") or "Modell")
    page_title = title or f"Modellansicht {source}"
    data = _embed_json(model.payload())
    substitutions = {
        "__TITLE__": html_module.escape(page_title),
        "__MODEL__": html_module.escape(source),
        "__DATA__": data,
        "__VERSION__": VIEWER_VERSION,
        "__NODES__": str(counts["nodes"]),
        "__EDGES__": str(counts["edges"]),
        "__PACKAGES__": str(counts["packages"]),
        "__NODES_TOTAL__": str(counts["nodes_total"]),
        "__EDGES_TOTAL__": str(counts["edges_total"]),
    }
    page = _TEMPLATE
    for key, value in substitutions.items():
        page = page.replace(key, value)
    return page


def build_html(
    path: str | Path,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    title: str | None = None,
) -> str:
    """Bequemer Weg fuer Aufrufer (Weboberflaeche): Datei -> fertige Seite."""
    return render_html(read_model(path, max_nodes=max_nodes), title=title)


def write_html(page: str, target: str | Path) -> Path:
    out = Path(target)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8", newline="\n")
    return out


# --------------------------------------------------------------------------
# Kommandozeile
# --------------------------------------------------------------------------


def _positive(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} ist keine Zahl") from error
    if number < 1:
        raise argparse.ArgumentTypeError("muss mindestens 1 sein")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="viewer_html.py",
        description="Baut eine selbsttragende HTML-Modellansicht aus einer .qea.",
    )
    parser.add_argument("qea", type=Path, help="gebaute .qea (SQLite)")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Zieldatei (Standard: <name>_viewer.html neben der .qea)",
    )
    parser.add_argument(
        "--max-knoten",
        dest="max_nodes",
        type=_positive,
        default=DEFAULT_MAX_NODES,
        help=f"hoechstens so viele Knoten zeichnen (Standard {DEFAULT_MAX_NODES})",
    )
    parser.add_argument("--title", default=None, help="Titel der Seite")
    arguments = parser.parse_args(argv)

    target = arguments.out or arguments.qea.with_name(arguments.qea.stem + "_viewer.html")
    try:
        model = read_model(arguments.qea, max_nodes=arguments.max_nodes)
        page = render_html(model, title=arguments.title)
        write_html(page, target)
    except ViewerError as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"FEHLER: {target}: {error}", file=sys.stderr)
        return 1

    size = target.stat().st_size
    counts = model.counts
    print(
        f"{target}: {counts['nodes']} Knoten, {counts['edges']} Kanten, "
        f"{counts['packages']} Pakete, {size / 1024:.0f} kB"
    )
    if counts["omitted_nodes"]:
        print(
            f"Hinweis: {counts['omitted_nodes']} Knoten wegen --max-knoten "
            f"{arguments.max_nodes} nicht gezeichnet",
            file=sys.stderr,
        )
    if counts["skipped_edges"]:
        print(
            f"Hinweis: {counts['skipped_edges']} Kanten enden auf einem Paketspiegel "
            "und werden nicht gezeichnet",
            file=sys.stderr,
        )
    if counts["omitted_edges"]:
        print(
            f"Hinweis: {counts['omitted_edges']} Kanten enden auf einem wegen "
            "--max-knoten nicht geladenen Knoten",
            file=sys.stderr,
        )
    return 0


_TEMPLATE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #0b1220; --panel: #111c30; --line: #22304a; --text: #e6edf7;
  --muted: #93a3bd; --accent: #4f9cf9; --warn: #f2b544; --ok: #4ade80;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text); overflow: hidden;
  font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
#app {
  display: grid; height: 100vh;
  grid-template-columns: 286px minmax(320px, 1fr) 344px;
  grid-template-rows: 58px 1fr;
  grid-template-areas: "head head head" "left stage right";
}
header {
  grid-area: head; display: flex; align-items: center; gap: 18px;
  padding: 0 16px; border-bottom: 1px solid var(--line); background: #0d1729;
  min-width: 0;
}
.brand { font-weight: 700; letter-spacing: -0.01em; white-space: nowrap; }
.brand .sub { font-weight: 400; color: var(--muted); margin-left: 8px; font-size: 13px; }
.stats { display: flex; gap: 14px; flex-wrap: nowrap; color: var(--muted); font-size: 12.5px;
  margin-left: auto; justify-content: flex-end; min-width: 0; overflow: hidden; }
.stats b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
.stats .sep { color: #33415c; }
aside { background: var(--panel); overflow-y: auto; min-height: 0; }
#left { grid-area: left; border-right: 1px solid var(--line); padding: 14px; }
#right { grid-area: right; border-left: 1px solid var(--line); padding: 14px 16px; }
main { grid-area: stage; position: relative; min-width: 0; min-height: 0; background: var(--bg); }
canvas { display: block; width: 100%; height: 100%; cursor: grab; touch-action: none; }
canvas.dragging { cursor: grabbing; }
h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.09em;
  color: var(--muted); margin: 18px 0 8px; font-weight: 600; }
h2:first-child { margin-top: 0; }
label.field { display: block; margin: 0 0 10px; color: var(--muted); font-size: 12px; }
select, input[type=search] {
  width: 100%; margin-top: 4px; padding: 7px 9px; border-radius: 7px;
  border: 1px solid var(--line); background: #0b1526; color: var(--text); font: inherit;
}
input[type=search] { font-size: 13px; }
select:focus, input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
label.check { display: flex; gap: 8px; align-items: center; margin: 7px 0; color: var(--text); font-size: 12.5px; }
label.check input { accent-color: var(--accent); margin: 0; }
button {
  font: inherit; font-size: 12.5px; border: 1px solid var(--line); border-radius: 7px;
  padding: 7px 10px; background: #16233a; color: var(--text); cursor: pointer;
}
button:hover { border-color: #33456a; background: #1b2b46; }
button.primary { background: var(--accent); border-color: var(--accent); color: #06101f; font-weight: 600; }
.row { display: flex; gap: 8px; }
.row > * { flex: 1; }
#hits { list-style: none; margin: 8px 0 0; padding: 0; max-height: 190px; overflow-y: auto; }
#hits li { padding: 5px 7px; border-radius: 6px; cursor: pointer; font-size: 12.5px;
  display: flex; gap: 6px; align-items: baseline; }
#hits li:hover { background: #182740; }
#hits li .t { color: var(--muted); font-size: 11px; margin-left: auto; white-space: nowrap; }
#hits li .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#hits li mark { background: #7a5a12; color: #ffe9b0; border-radius: 3px; padding: 0 1px; }
.hint { color: var(--muted); font-size: 11.5px; margin: 8px 0 0; line-height: 1.5; }
#legend { list-style: none; margin: 0; padding: 0; }
#legend li { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 6px;
  cursor: pointer; font-size: 12.5px; }
#legend li:hover { background: #182740; }
#legend li.off { opacity: 0.38; }
#legend .sw { width: 11px; height: 11px; border-radius: 3px; flex: none; box-shadow: 0 0 0 1px #0006 inset; }
#legend .n { margin-left: auto; color: var(--muted); font-variant-numeric: tabular-nums; font-size: 11.5px; }
#legend .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#detail h3 { margin: 2px 0 8px; font-size: 16px; line-height: 1.3; overflow-wrap: anywhere; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { font-size: 11.5px; padding: 2px 8px; border-radius: 99px; background: #17253c;
  border: 1px solid var(--line); color: #c3d2e8; }
.chip.stereo { border-color: #3b5a86; color: #bcd7ff; }
.kv { display: grid; grid-template-columns: 76px 1fr; gap: 4px 8px; font-size: 12.5px; margin-bottom: 10px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; overflow-wrap: anywhere; }
.note { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12.5px; color: #cfdcee;
  background: #0b1526; border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px;
  max-height: 240px; overflow-y: auto; margin: 8px 0 4px; }
.elist { list-style: none; margin: 0; padding: 0; }
.elist li { display: flex; gap: 7px; align-items: baseline; padding: 4px 6px; border-radius: 6px;
  cursor: pointer; font-size: 12.5px; }
.elist li:hover { background: #182740; }
.elist .arrow { color: var(--muted); flex: none; font-family: ui-monospace, Menlo, monospace; }
.elist .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.elist .ty { margin-left: auto; color: var(--muted); font-size: 11px; flex: none; }
.muted { color: var(--muted); }
#tip {
  position: absolute; pointer-events: none; padding: 5px 8px; border-radius: 6px;
  background: #0a1220ee; border: 1px solid #33456a; font-size: 12px; color: var(--text);
  max-width: 320px; transform: translate(12px, 12px); display: none; z-index: 5;
  box-shadow: 0 6px 18px #0008; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#tip .ty { color: var(--muted); }
#flyout {
  position: absolute; right: 14px; bottom: 14px; z-index: 6; display: flex; gap: 8px;
  background: #0d1729cc; border: 1px solid var(--line); border-radius: 10px; padding: 7px;
  backdrop-filter: blur(4px);
}
#flyout button { min-width: 34px; text-align: center; }
#empty { position: absolute; inset: 0; display: none; place-items: center; pointer-events: none; }
#empty div { background: #0d1729e6; border: 1px solid var(--line); border-radius: 10px;
  padding: 16px 20px; color: var(--muted); text-align: center; max-width: 340px; }
.badge { display: inline-block; font-size: 11px; color: var(--muted); border: 1px solid var(--line);
  border-radius: 99px; padding: 1px 7px; margin-left: 6px; vertical-align: 2px; }
@media (max-width: 1180px) {
  #app { grid-template-columns: 250px minmax(280px, 1fr) 300px; }
  .stats { font-size: 11.5px; gap: 9px; }
}
</style>
</head>
<body>
<div id="app">
  <header>
    <div class="brand">Modellansicht<span class="sub">__MODEL__</span><span class="badge">v__VERSION__</span></div>
    <div class="stats">
      <span>Knoten <b id="stat-nodes">__NODES__</b></span>
      <span class="sep">|</span>
      <span>Kanten <b id="stat-edges">__EDGES__</b><span id="stat-edges-total"></span></span>
      <span class="sep">|</span>
      <span>Pakete <b id="stat-pkgs">__PACKAGES__</b></span>
      <span class="sep">|</span>
      <span>sichtbar <b id="stat-visible">__NODES__</b></span>
      <span class="sep">|</span>
      <span id="stat-load">l&auml;dt &hellip;</span>
    </div>
  </header>

  <aside id="left">
    <h2>Suche</h2>
    <input type="search" id="q" placeholder="Name, Stereotyp, Notiz &hellip;" autocomplete="off" spellcheck="false">
    <p class="hint" id="q-hint">Tippen filtert und markiert im Graphen. Enter springt zum Treffer.</p>
    <ul id="hits"></ul>

    <h2>Filter</h2>
    <label class="field">Paket
      <select id="pkg"><option value="">alle Pakete</option></select>
    </label>
    <label class="field">Stereotyp
      <select id="stereo"><option value="">alle Stereotype</option></select>
    </label>
    <label class="field">Elementtyp
      <select id="type"><option value="">alle Typen</option></select>
    </label>
    <label class="check"><input type="checkbox" id="hide-isolated"> Isolierte Knoten ausblenden</label>
    <label class="check"><input type="checkbox" id="all-edges"> Kanten zu ausgeblendeten Knoten</label>
    <label class="check"><input type="checkbox" id="show-labels" checked> Beschriftungen</label>
    <div class="row" style="margin-top:8px">
      <button id="fit" type="button">Einpassen</button>
      <button id="reset" type="button">Zur&uuml;cksetzen</button>
    </div>

    <h2>Paketfarben</h2>
    <ul id="legend"></ul>
    <p class="hint" id="legend-hint"></p>

    <h2>Hinweis</h2>
    <p class="hint">Ziehen = Knoten bewegen, Hintergrund ziehen = verschieben,
      Mausrad = zoomen, Doppelklick = Nachbarschaft heranholen.
      Tasten: <b>/</b> Suche, <b>0</b> einpassen, <b>Esc</b> Auswahl loesen.</p>
  </aside>

  <main id="stage">
    <canvas id="c"></canvas>
    <div id="tip"></div>
    <div id="flyout">
      <button id="zoom-out" type="button" title="kleiner">&minus;</button>
      <button id="zoom-in" type="button" title="groesser">+</button>
      <button id="zoom-fit" type="button" title="einpassen">&#9633;</button>
    </div>
    <div id="empty"><div id="empty-text">Kein Knoten passt zum Filter.</div></div>
  </main>

  <aside id="right">
    <div id="detail">
      <h2>Details</h2>
      <p class="hint">Knoten anklicken: Name, Typ, Stereotyp, Notiz und alle
        eingehenden und ausgehenden Kanten.</p>
    </div>
    <h2>Modell</h2>
    <dl class="kv">
      <dt>Datei</dt><dd id="m-file">__MODEL__</dd>
      <dt>Knoten</dt><dd id="m-nodes">__NODES_TOTAL__</dd>
      <dt>Kanten</dt><dd id="m-edges">__EDGES_TOTAL__</dd>
      <dt>Pakete</dt><dd id="m-pkgs">__PACKAGES__</dd>
    </dl>
    <p class="hint" id="m-note"></p>
  </aside>
</div>

<script>
"use strict";
(function () {
  const DATA = /*DATA-BEGIN*/__DATA__/*DATA-END*/;
  const t0 = (window.performance && performance.now) ? performance.now() : Date.now();

  const nodes = DATA.nodes.map((raw, index) => Object.assign({}, raw, {
    i: index, vx: 0, vy: 0, pinned: false
  }));
  const edges = DATA.edges.map((raw, index) => Object.assign({}, raw, { i: index }));

  const outgoing = nodes.map(() => []);
  const incoming = nodes.map(() => []);
  const incident = nodes.map(() => []);
  edges.forEach((edge) => {
    outgoing[edge.s].push(edge);
    incoming[edge.t].push(edge);
    incident[edge.s].push(edge);
    incident[edge.t].push(edge);
  });

  const byId = new Map(nodes.map((node) => [node.id, node]));
  const EDGE_COLORS = {
    Dependency: "#6b7f9e", Realisation: "#4ade80", Generalization: "#a78bfa",
    InformationFlow: "#38bdf8", Abstraction: "#f2b544", Aggregation: "#f472b6",
    Composition: "#fb7185", NoteLink: "#46536b", ControlFlow: "#2dd4bf",
    ObjectFlow: "#22d3ee", StateFlow: "#60a5fa", Sequence: "#94a3b8",
    Association: "#7dd3fc", Realization: "#4ade80", Usage: "#fbbf24"
  };
  const NONE = "\u0000ohne";

  const state = {
    cam: { x: 0, y: 0, k: 1 },
    pkg: "", stereo: "", type: "",
    q: "", query: "", matches: new Set(), hits: [],
    hidden: new Set(),
    sel: -1, hover: -1, drag: -1,
    panning: false, moved: 0,
    showAllEdges: false, labels: true, hideIsolated: false,
    alpha: 1, running: true
  };

  const canvas = document.getElementById("c");
  const ctx = canvas.getContext("2d");
  const tip = document.getElementById("tip");
  let W = 0, H = 0, dpr = 1;

  const $ = (id) => document.getElementById(id);
  const fmt = (value) => Number(value).toLocaleString("de-DE");

  function norm(text) {
    return String(text || "").toLowerCase()
      .replace(/\u00df/g, "ss")
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  // -- Sichtbarkeit --------------------------------------------------------
  const vis = new Uint8Array(nodes.length);
  let visibleCount = 0;
  let visibleEdges = [];

  function isVisible(node) {
    if (state.hideIsolated && node.degree === 0) return false;
    if (state.hidden.has(node.group)) return false;
    if (state.pkg && !(node.pkg === state.pkg || node.pkg.indexOf(state.pkg + "/") === 0)) return false;
    if (state.type && node.type !== state.type) return false;
    if (state.stereo === NONE) { if (node.stereo) return false; }
    else if (state.stereo && node.stereo !== state.stereo) return false;
    return true;
  }

  function recompute() {
    visibleCount = 0;
    for (let i = 0; i < nodes.length; i++) {
      const on = isVisible(nodes[i]) ? 1 : 0;
      vis[i] = on;
      visibleCount += on;
    }
    visibleEdges = edges.filter((edge) => {
      const a = vis[edge.s] === 1, b = vis[edge.t] === 1;
      return state.showAllEdges ? (a || b) : (a && b);
    });
    $("stat-visible").textContent = fmt(visibleCount);
    $("stat-edges").textContent = fmt(visibleEdges.length);
    $("stat-edges-total").textContent = " / " + fmt(DATA.counts.edges_total);
    $("empty").style.display = visibleCount ? "none" : "grid";
    if (state.sel >= 0 && !vis[state.sel]) select(-1, false);
  }

  // -- Suche ---------------------------------------------------------------
  function runSearch() {
    state.query = state.q.trim();
    state.matches = new Set();
    state.hits = [];
    if (state.query) {
      const needle = norm(state.query);
      const terms = needle.split(/\s+/).filter(Boolean);
      for (const node of nodes) {
        const hay = norm(node.name) + "\u0001" + norm(node.stereo) + "\u0001" +
          norm(node.type) + "\u0001" + norm(node.pkg) + "\u0001" + norm(node.note);
        if (terms.every((term) => hay.indexOf(term) >= 0)) {
          state.matches.add(node.i);
          if (state.hits.length < 60) state.hits.push(node.i);
        }
      }
    }
    renderHits();
    draw();
  }

  function renderHits() {
    const list = $("hits");
    list.textContent = "";
    const hint = $("q-hint");
    if (!state.query) {
      hint.textContent = "Tippen filtert und markiert im Graphen. Enter springt zum Treffer.";
      return;
    }
    hint.textContent = state.matches.size
      ? fmt(state.matches.size) + " Treffer" + (state.matches.size > state.hits.length ? " (erste " + state.hits.length + ")" : "")
      : "Kein Treffer.";
    const needle = norm(state.query).split(/\s+/)[0] || "";
    state.hits.slice(0, 14).forEach((index) => {
      const node = nodes[index];
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.className = "nm";
      const label = node.name || "(ohne Namen)";
      const normalized = norm(label);
      // Nur hervorheben, wenn die Normalisierung die Laenge nicht verschiebt
      // (sonst zeigt der Index auf die falsche Stelle, z. B. bei "ss").
      const at = normalized.length === label.length ? normalized.indexOf(needle) : -1;
      if (needle && at >= 0) {
        name.appendChild(document.createTextNode(label.slice(0, at)));
        const mark = document.createElement("mark");
        mark.textContent = label.slice(at, at + needle.length);
        name.appendChild(mark);
        name.appendChild(document.createTextNode(label.slice(at + needle.length)));
      } else {
        name.textContent = label;
      }
      const type = document.createElement("span");
      type.className = "t";
      type.textContent = node.type;
      item.appendChild(name);
      item.appendChild(type);
      item.addEventListener("click", () => { select(index, true); focusOn(node); });
      list.appendChild(item);
    });
  }

  // -- Kamera --------------------------------------------------------------
  function toScreen(x, y) {
    return [(x - state.cam.x) * state.cam.k + W / 2, (y - state.cam.y) * state.cam.k + H / 2];
  }
  function toWorld(sx, sy) {
    return [(sx - W / 2) / state.cam.k + state.cam.x, (sy - H / 2) / state.cam.k + state.cam.y];
  }

  function fit() {
    // Einpassen auf das 2-%-bis-98-%-Rechteck: einzelne Ausreisser (isolierte
    // Notizen, weit abgedriftete Knoten) sollen die Hauptmasse nicht
    // zusammenschrumpfen. Ausreisser bleiben per Pan erreichbar.
    const xs = [], ys = [];
    for (const node of nodes) {
      if (!vis[node.i]) continue;
      xs.push(node.x);
      ys.push(node.y);
    }
    if (!xs.length) { state.cam = { x: 0, y: 0, k: 1 }; draw(); return; }
    xs.sort((a, b) => a - b);
    ys.sort((a, b) => a - b);
    const low = Math.min(xs.length - 1, Math.floor(xs.length * 0.02));
    const high = Math.max(0, Math.ceil(xs.length * 0.98) - 1);
    const minX = xs[low], maxX = xs[high], minY = ys[low], maxY = ys[high];
    const width = Math.max(1, maxX - minX), height = Math.max(1, maxY - minY);
    const k = Math.max(0.03, Math.min(3.2, Math.min((W - 90) / width, (H - 90) / height)));
    state.cam = { x: (minX + maxX) / 2, y: (minY + maxY) / 2, k: k };
    draw();
  }

  // Treffer holen: Knoten und Nachbarschaft so einpassen, dass Namen lesbar
  // sind. Bei einem Knoten ohne Kanten bleibt es beim reinen Zentrieren.
  function zoomToNeighborhood(index, maxK) {
    const node = nodes[index];
    const ids = new Set([index]);
    incident[index].forEach((edge) => ids.add(edge.s === index ? edge.t : edge.s));
    let minX = node.x, maxX = node.x, minY = node.y, maxY = node.y;
    ids.forEach((other) => {
      const item = nodes[other];
      minX = Math.min(minX, item.x); maxX = Math.max(maxX, item.x);
      minY = Math.min(minY, item.y); maxY = Math.max(maxY, item.y);
    });
    const width = Math.max(150, maxX - minX), height = Math.max(150, maxY - minY);
    const limit = maxK || 2.4;
    state.cam.k = Math.max(0.6, Math.min(limit, Math.min((W - 160) / width, (H - 160) / height)));
    state.cam.x = (minX + maxX) / 2;
    state.cam.y = (minY + maxY) / 2;
    draw();
  }

  function focusOn(node) {
    zoomToNeighborhood(node.i, 1.8);
  }

  function zoomAt(factor, sx, sy) {
    const before = toWorld(sx, sy);
    state.cam.k = Math.max(0.03, Math.min(8, state.cam.k * factor));
    const after = toWorld(sx, sy);
    state.cam.x += before[0] - after[0];
    state.cam.y += before[1] - after[1];
    draw();
  }

  // -- Layout --------------------------------------------------------------
  const CELL = 110, IDEAL = 88, REP = 2800;
  const grid = new Map();

  function simulate(stepCount) {
    for (let step = 0; step < stepCount; step++) {
      const alpha = state.alpha;
      grid.clear();
      for (const node of nodes) {
        if (!vis[node.i]) continue;
        const key = Math.floor(node.x / CELL) + ":" + Math.floor(node.y / CELL);
        let bucket = grid.get(key);
        if (!bucket) { bucket = []; grid.set(key, bucket); }
        bucket.push(node);
      }
      for (const node of nodes) {
        if (!vis[node.i]) continue;
        const cx = Math.floor(node.x / CELL), cy = Math.floor(node.y / CELL);
        for (let dx = -1; dx <= 1; dx++) {
          for (let dy = -1; dy <= 1; dy++) {
            const bucket = grid.get((cx + dx) + ":" + (cy + dy));
            if (!bucket) continue;
            for (const other of bucket) {
              // Jedes Paar genau einmal: halbiert die Arbeit, Ergebnis bleibt
              // symmetrisch, weil beide Knoten den gleichen Impuls bekommen.
              if (other.i <= node.i) continue;
              let ox = node.x - other.x, oy = node.y - other.y;
              let d2 = ox * ox + oy * oy;
              if (d2 > CELL * CELL * 2.1) continue;
              if (d2 < 1e-4) {
                ox = ((node.i % 7) - 3) * 0.4 + 0.15;
                oy = ((node.i % 5) - 2) * 0.4 + 0.15;
                d2 = ox * ox + oy * oy;
              }
              const d = Math.sqrt(d2);
              const force = Math.min(REP / d2, 6) * alpha;
              const fx = (ox / d) * force, fy = (oy / d) * force;
              node.vx += fx; node.vy += fy;
              other.vx -= fx; other.vy -= fy;
            }
          }
        }
      }
      for (const edge of visibleEdges) {
        const a = nodes[edge.s], b = nodes[edge.t];
        let dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = Math.max(-0.35, Math.min(0.35, ((d - IDEAL) / d) * 0.055 * alpha));
        a.vx += dx * force; a.vy += dy * force;
        b.vx -= dx * force; b.vy -= dy * force;
      }
      for (const node of nodes) {
        if (!vis[node.i]) continue;
        if (node.pinned) { node.x = node.px; node.y = node.py; node.vx = 0; node.vy = 0; continue; }
        node.vx += -node.x * 0.0025 * alpha;
        node.vy += -node.y * 0.0025 * alpha;
        node.vx *= 0.82; node.vy *= 0.82;
        const speed = Math.hypot(node.vx, node.vy);
        if (speed > 24) { node.vx = node.vx / speed * 24; node.vy = node.vy / speed * 24; }
        node.x += node.vx; node.y += node.vy;
        if (!isFinite(node.x) || !isFinite(node.y)) {
          node.x = (node.i % 37) * 12; node.y = Math.floor(node.i / 37) * 12;
          node.vx = node.vy = 0;
        }
      }
      state.alpha *= 0.985;
    }
    if (state.alpha < 0.02) state.alpha = 0.02;
  }

  // -- Zeichnen ------------------------------------------------------------
  let lastDraw = 0, frames = 0, fps = 0, lastDrawMs = 0;

  function radiusOf(node) {
    return 3.2 + Math.min(10, Math.sqrt(node.degree) * 1.35);
  }

  function draw() {
    const tDrawStart = (window.performance && performance.now) ? performance.now() : Date.now();
    const k = state.cam.k;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, W, H);
    drawGrid(k);

    const selected = state.sel >= 0 ? nodes[state.sel] : null;
    const neighborSet = new Set();
    if (selected) {
      neighborSet.add(selected.i);
      incident[selected.i].forEach((edge) => {
        neighborSet.add(edge.s === selected.i ? edge.t : edge.s);
      });
    }
    const dragging = state.drag >= 0;
    const thin = dragging && visibleEdges.length > 1200;
    const arrow = k > 0.75 && visibleEdges.length <= 3200 && !thin;
    let drawnEdges = 0;

    // Kanten nach Farbe/Zustand buendeln: wenige stroke()-Aufrufe statt 1500.
    const plain = new Map(), ghosts = new Map(), active = new Map(), arrows = new Map();
    const push = (map, color, segment) => {
      let list = map.get(color);
      if (!list) { list = []; map.set(color, list); }
      list.push(segment);
    };
    for (const edge of visibleEdges) {
      if (thin && edge.s !== state.drag && edge.t !== state.drag) continue;
      const a = nodes[edge.s], b = nodes[edge.t];
      const pa = toScreen(a.x, a.y), pb = toScreen(b.x, b.y);
      if (Math.max(pa[0], pb[0]) < -60 || Math.min(pa[0], pb[0]) > W + 60) continue;
      if (Math.max(pa[1], pb[1]) < -60 || Math.min(pa[1], pb[1]) > H + 60) continue;
      const color = EDGE_COLORS[edge.type] || "#5a6b88";
      const ghost = !vis[edge.s] || !vis[edge.t];
      const isActive = selected && (edge.s === selected.i || edge.t === selected.i);
      const segment = [pa[0], pa[1], pb[0], pb[1]];
      if (ghost) push(ghosts, color, segment);
      else if (selected) { if (isActive) push(active, color, segment); else push(plain, color, segment); }
      else push(plain, color, segment);
      if (arrow && !ghost && (!selected || isActive)) {
        const dx = pb[0] - pa[0], dy = pb[1] - pa[1];
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len > 26) {
          const ux = dx / len, uy = dy / len;
          const tipX = pb[0] - ux * (radiusOf(b) + 2), tipY = pb[1] - uy * (radiusOf(b) + 2);
          push(arrows, color, [tipX, tipY, ux, uy]);
        }
      }
      drawnEdges++;
    }
    const strokeBatches = (map, alpha, width, dash) => {
      if (!map.size) return;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = width;
      ctx.setLineDash(dash);
      map.forEach((segments, color) => {
        ctx.beginPath();
        for (const s of segments) { ctx.moveTo(s[0], s[1]); ctx.lineTo(s[2], s[3]); }
        ctx.strokeStyle = color;
        ctx.stroke();
      });
    };
    strokeBatches(plain, selected ? 0.06 : 0.34, 1, []);
    strokeBatches(ghosts, 0.09, 0.7, [4, 5]);
    strokeBatches(active, 0.85, 1.6, []);
    ctx.setLineDash([]);
    if (arrows.size) {
      ctx.globalAlpha = 1;
      arrows.forEach((triangles, color) => {
        ctx.beginPath();
        for (const t of triangles) {
          const ux = t[2], uy = t[3];
          ctx.moveTo(t[0], t[1]);
          ctx.lineTo(t[0] - ux * 6 - uy * 3.2, t[1] - uy * 6 + ux * 3.2);
          ctx.lineTo(t[0] - ux * 6 + uy * 3.2, t[1] - uy * 6 - ux * 3.2);
          ctx.closePath();
        }
        ctx.fillStyle = color;
        ctx.fill();
      });
    }
    ctx.globalAlpha = 1;

    const labelOn = state.labels && k > 0.55 && (selected !== null || visibleCount <= 1200);
    const cull = (x, y) => x < -80 || y < -40 || x > W + 80 || y > H + 40;
    const sizeFactor = Math.max(0.75, Math.min(1.7, Math.sqrt(k)));

    // Knoten nach Farbe buendeln; Umriss und Ringe danach in wenigen Zuegen.
    // Bei Auswahl bleibt der Rest als blasser Kontext stehen, damit man die
    // Nachbarschaft im Modell verorten kann.
    const circles = new Map(), outline = [], rings = [], matched = [], dimmed = [];
    for (const node of nodes) {
      if (!vis[node.i]) continue;
      const p = toScreen(node.x, node.y);
      if (cull(p[0], p[1])) continue;
      const r = radiusOf(node) * sizeFactor;
      const dim = selected && !neighborSet.has(node.i);
      if (dim) { dimmed.push(p[0], p[1], r); continue; }
      let list = circles.get(node.color);
      if (!list) { list = []; circles.set(node.color, list); }
      list.push(p[0], p[1], r);
      if (node.i !== state.sel) outline.push(p[0], p[1], r);
      if (state.matches.has(node.i)) matched.push(p[0], p[1], r);
      else if (node.i === state.hover) rings.push(p[0], p[1], r);
    }
    if (dimmed.length) {
      ctx.beginPath();
      for (let i = 0; i < dimmed.length; i += 3) {
        ctx.moveTo(dimmed[i] + dimmed[i + 2], dimmed[i + 1]);
        ctx.arc(dimmed[i], dimmed[i + 1], dimmed[i + 2], 0, Math.PI * 2);
      }
      ctx.globalAlpha = 0.5;
      ctx.fillStyle = "#2b3b57";
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    circles.forEach((batch, color) => {
      ctx.beginPath();
      for (let i = 0; i < batch.length; i += 3) {
        ctx.moveTo(batch[i] + batch[i + 2], batch[i + 1]);
        ctx.arc(batch[i], batch[i + 1], batch[i + 2], 0, Math.PI * 2);
      }
      ctx.fillStyle = color;
      ctx.fill();
    });
    if (outline.length) {
      ctx.beginPath();
      for (let i = 0; i < outline.length; i += 3) {
        ctx.moveTo(outline[i] + outline[i + 2], outline[i + 1]);
        ctx.arc(outline[i], outline[i + 1], outline[i + 2], 0, Math.PI * 2);
      }
      ctx.lineWidth = 1.1;
      ctx.strokeStyle = "#0a1220";
      ctx.stroke();
    }
    if (selected) {
      const p = toScreen(selected.x, selected.y);
      ctx.beginPath();
      ctx.arc(p[0], p[1], radiusOf(selected) * sizeFactor, 0, Math.PI * 2);
      ctx.fillStyle = selected.color;
      ctx.fill();
      ctx.lineWidth = 2.4;
      ctx.strokeStyle = "#ffffff";
      ctx.stroke();
    }
    if (matched.length) {
      ctx.beginPath();
      for (let i = 0; i < matched.length; i += 3) {
        ctx.moveTo(matched[i] + matched[i + 2] + 3.4, matched[i + 1]);
        ctx.arc(matched[i], matched[i + 1], matched[i + 2] + 3.4, 0, Math.PI * 2);
      }
      ctx.strokeStyle = "#facc15";
      ctx.lineWidth = 1.8;
      ctx.stroke();
    }
    if (rings.length) {
      ctx.beginPath();
      for (let i = 0; i < rings.length; i += 3) {
        ctx.moveTo(rings[i] + rings[i + 2] + 3, rings[i + 1]);
        ctx.arc(rings[i], rings[i + 1], rings[i + 2] + 3, 0, Math.PI * 2);
      }
      ctx.strokeStyle = "#cfe0f7";
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }

    if (labelOn) {
      const fontSize = Math.round(Math.min(22, Math.max(10, 12 * Math.sqrt(k))));
      ctx.font = fontSize + "px ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.lineWidth = 3.2;
      ctx.strokeStyle = "rgba(11,18,32,0.88)";
      ctx.fillStyle = "#dbe7f7";
      // Beschriftungen kollisionsarm: wichtige Knoten (hoher Grad) zuerst,
      // danach nur, wo das Rechteck noch frei ist. Sonst ueberlappen die
      // Namen in dichten Clustern unlesbar.
      const candidates = [];
      for (const node of nodes) {
        if (!vis[node.i]) continue;
        if (selected && !neighborSet.has(node.i)) continue;
        if (candidates.length >= 600) break;
        const p = toScreen(node.x, node.y);
        if (cull(p[0], p[1])) continue;
        candidates.push([node, p[0], p[1]]);
      }
      candidates.sort((a, b) => b[0].degree - a[0].degree || a[0].i - b[0].i);
      const occupied = new Set();
      const cell = 46;
      let labels = 0;
      for (const [node, sx, sy] of candidates) {
        if (labels >= 420) break;
        const label = node.name || "(ohne Namen)";
        const short = label.length > 30 ? label.slice(0, 29) + "\u2026" : label;
        const x = sx + radiusOf(node) * sizeFactor + 5;
        const width = ctx.measureText(short).width;
        const x0 = Math.floor(x / cell), x1 = Math.floor((x + width) / cell);
        const y0 = Math.floor((sy - fontSize) / cell), y1 = Math.floor((sy + fontSize) / cell);
        let blocked = false;
        for (let gx = x0; gx <= x1 && !blocked; gx++) {
          for (let gy = y0; gy <= y1; gy++) {
            if (occupied.has(gx + ":" + gy)) { blocked = true; break; }
          }
        }
        if (blocked) continue;
        for (let gx = x0; gx <= x1; gx++) {
          for (let gy = y0; gy <= y1; gy++) occupied.add(gx + ":" + gy);
        }
        ctx.strokeText(short, x, sy);
        ctx.fillText(short, x, sy);
        labels++;
      }
    }
    ctx.globalAlpha = 1;
    lastDrawMs = ((window.performance && performance.now) ? performance.now() : Date.now()) - tDrawStart;

    frames++;
    const now = (window.performance && performance.now) ? performance.now() : Date.now();
    if (now - lastDraw > 500) {
      fps = Math.round(frames * 1000 / (now - lastDraw));
      frames = 0;
      lastDraw = now;
      window.__viewerFps = fps;
      window.__viewerDrawnEdges = drawnEdges;
      document.body.dataset.viewerFps = String(fps);
      document.body.dataset.viewerDrawMs = lastDrawMs.toFixed(2);
    }
  }

  function drawGrid(k) {
    let step = 100;
    while (step * k < 46) step *= 2;
    while (step * k > 190) step /= 2;
    const originX = W / 2 - state.cam.x * k;
    const originY = H / 2 - state.cam.y * k;
    const startX = ((originX % (step * k)) + step * k) % (step * k);
    const startY = ((originY % (step * k)) + step * k) % (step * k);
    ctx.fillStyle = "#1b2840";
    const size = step * k > 90 ? 2 : 1.4;
    for (let x = startX; x < W; x += step * k) {
      for (let y = startY; y < H; y += step * k) {
        ctx.fillRect(x, y, size, size);
      }
    }
  }

  // -- Auswahl / Details ---------------------------------------------------
  function select(index, push) {
    state.sel = index;
    renderDetail();
    if (push !== false) draw();
  }

  function edgeLabel(edge) {
    return edge.name || edge.stereo || edge.type;
  }

  function renderDetail() {
    const box = $("detail");
    box.textContent = "";
    const head = document.createElement("h2");
    head.textContent = "Details";
    box.appendChild(head);

    if (state.sel < 0) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Knoten anklicken: Name, Typ, Stereotyp, Notiz und alle " +
        "eingehenden und ausgehenden Kanten.";
      box.appendChild(hint);
      return;
    }
    const node = nodes[state.sel];
    const title = document.createElement("h3");
    title.textContent = node.name || "(ohne Namen)";
    box.appendChild(title);

    const chips = document.createElement("div");
    chips.className = "chips";
    const typeChip = document.createElement("span");
    typeChip.className = "chip";
    typeChip.textContent = node.type;
    chips.appendChild(typeChip);
    if (node.stereo) {
      const stereoChip = document.createElement("span");
      stereoChip.className = "chip stereo";
      stereoChip.textContent = "\u00ab" + node.stereo + "\u00bb";
      chips.appendChild(stereoChip);
    }
    const groupChip = document.createElement("span");
    groupChip.className = "chip";
    groupChip.textContent = node.group;
    groupChip.style.borderColor = node.color;
    chips.appendChild(groupChip);
    box.appendChild(chips);

    const kv = document.createElement("dl");
    kv.className = "kv";
    const addRow = (key, value) => {
      const dt = document.createElement("dt");
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.textContent = value;
      kv.appendChild(dt);
      kv.appendChild(dd);
    };
    addRow("Paket", node.pkg);
    addRow("ID", String(node.id));
    addRow("Grad", node.degree + " (" + incoming[node.i].length + " ein / " +
      outgoing[node.i].length + " aus)");
    box.appendChild(kv);

    if (node.note) {
      const noteHead = document.createElement("h2");
      noteHead.textContent = "Notiz";
      box.appendChild(noteHead);
      const note = document.createElement("div");
      note.className = "note";
      note.textContent = node.note;
      box.appendChild(note);
    }

    const listBlock = (caption, list, arrow) => {
      const h = document.createElement("h2");
      h.textContent = caption + " (" + list.length + ")";
      box.appendChild(h);
      if (!list.length) {
        const p = document.createElement("p");
        p.className = "hint";
        p.textContent = "\u2014 keine \u2014";
        box.appendChild(p);
        return;
      }
      const ul = document.createElement("ul");
      ul.className = "elist";
      list.slice(0, 150).forEach((edge) => {
        const other = nodes[edge.s === node.i ? edge.t : edge.s];
        const li = document.createElement("li");
        const ar = document.createElement("span");
        ar.className = "arrow";
        ar.textContent = arrow;
        const nm = document.createElement("span");
        nm.className = "nm";
        nm.textContent = other.name || "(ohne Namen)";
        const ty = document.createElement("span");
        ty.className = "ty";
        ty.textContent = edgeLabel(edge);
        li.appendChild(ar);
        li.appendChild(nm);
        li.appendChild(ty);
        li.title = other.name + " \u2014 " + edge.type +
          (other.stereo ? " \u00ab" + other.stereo + "\u00bb" : "");
        li.addEventListener("click", () => { select(other.i, true); focusOn(other); });
        ul.appendChild(li);
      });
      box.appendChild(ul);
      if (list.length > 150) {
        const more = document.createElement("p");
        more.className = "hint";
        more.textContent = "+ " + (list.length - 150) + " weitere";
        box.appendChild(more);
      }
    };
    listBlock("Ausgehend", outgoing[node.i], "\u2192");
    listBlock("Eingehend", incoming[node.i], "\u2190");
  }

  // -- Maus/Tastatur -------------------------------------------------------
  function resize() {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(2.5, window.devicePixelRatio || 1);
    W = Math.max(1, Math.round(rect.width));
    H = Math.max(1, Math.round(rect.height));
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    draw();
  }

  function hitTest(sx, sy) {
    let best = -1, bestDistance = Infinity;
    for (const node of nodes) {
      if (!vis[node.i]) continue;
      const p = toScreen(node.x, node.y);
      const dx = p[0] - sx, dy = p[1] - sy;
      const distance = Math.sqrt(dx * dx + dy * dy);
      const r = radiusOf(node) * Math.max(0.75, Math.min(1.7, Math.sqrt(state.cam.k))) + 3;
      if (distance <= r && distance < bestDistance) { best = node.i; bestDistance = distance; }
    }
    return best;
  }

  function pointerPosition(event) {
    const rect = canvas.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  }

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const [sx, sy] = pointerPosition(event);
    const hit = hitTest(sx, sy);
    state.moved = 0;
    try { canvas.setPointerCapture(event.pointerId); } catch (error) { /* ohne Capture weiter */ }
    if (hit >= 0) {
      state.drag = hit;
      const node = nodes[hit];
      node.pinned = true;
      node.px = node.x;
      node.py = node.y;
      canvas.classList.add("dragging");
    } else {
      state.panning = true;
      state.panStart = { x: sx, y: sy, cx: state.cam.x, cy: state.cam.y };
    }
  });

  canvas.addEventListener("pointermove", (event) => {
    const [sx, sy] = pointerPosition(event);
    if (state.drag >= 0) {
      const world = toWorld(sx, sy);
      const node = nodes[state.drag];
      node.px = world[0];
      node.py = world[1];
      state.moved += 1;
      state.alpha = Math.max(state.alpha, 0.16);
      kick();
      return;
    }
    if (state.panning) {
      state.cam.x = state.panStart.cx - (sx - state.panStart.x) / state.cam.k;
      state.cam.y = state.panStart.cy - (sy - state.panStart.y) / state.cam.k;
      state.moved += 1;
      draw();
      return;
    }
    const hit = hitTest(sx, sy);
    if (hit !== state.hover) {
      state.hover = hit;
      draw();
    }
    if (hit >= 0) {
      const node = nodes[hit];
      tip.style.display = "block";
      tip.textContent = "";
      const name = document.createElement("span");
      name.textContent = (node.name || "(ohne Namen)") + "  ";
      const type = document.createElement("span");
      type.className = "ty";
      type.textContent = node.type + (node.stereo ? " \u00ab" + node.stereo + "\u00bb" : "");
      tip.appendChild(name);
      tip.appendChild(type);
      tip.style.left = sx + "px";
      tip.style.top = sy + "px";
    } else {
      tip.style.display = "none";
    }
  });

  function endPointer(event) {
    if (state.drag >= 0) {
      const node = nodes[state.drag];
      if (state.moved < 3) {
        select(node.i, true);
      } else {
        state.alpha = Math.max(state.alpha, 0.35);
        kick();
      }
      node.pinned = false;
      state.drag = -1;
      canvas.classList.remove("dragging");
    } else if (state.panning) {
      state.panning = false;
    }
    if (canvas.hasPointerCapture && event.pointerId !== undefined &&
        canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
  }
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);
  canvas.addEventListener("pointerleave", () => {
    tip.style.display = "none";
    if (state.hover >= 0) { state.hover = -1; draw(); }
  });

  canvas.addEventListener("dblclick", (event) => {
    const [sx, sy] = pointerPosition(event);
    const hit = hitTest(sx, sy);
    if (hit < 0) return;
    select(hit, true);
    zoomToNeighborhood(hit, 2.6);
  });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const [sx, sy] = pointerPosition(event);
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, sx, sy);
  }, { passive: false });

  window.addEventListener("keydown", (event) => {
    const tag = (event.target && event.target.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
      // Enter im Suchfeld springt zum ersten Treffer; Escape gibt die Karte frei.
      if (event.key === "Enter" && event.target.id === "q" && state.hits.length) {
        event.preventDefault();
        const node = nodes[state.hits[0]];
        select(node.i, true);
        focusOn(node);
      } else if (event.key === "Escape") {
        event.target.blur();
      }
      return;
    }
    if (event.key === "/") { event.preventDefault(); $("q").focus(); return; }
    if (event.key === "Escape") { select(-1, true); return; }
    if (event.key === "0") { fit(); return; }
    if (event.key === "+" || event.key === "=") { zoomAt(1.2, W / 2, H / 2); return; }
    if (event.key === "-") { zoomAt(1 / 1.2, W / 2, H / 2); return; }
    if (event.key === "Enter" && state.hits.length) {
      const node = nodes[state.hits[0]];
      select(node.i, true);
      focusOn(node);
    }
  });

  // -- Bedienfelder --------------------------------------------------------
  function fillSelect(id, values) {
    const select = $(id);
    values.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    });
  }

  const packages = DATA.packages.slice().sort((a, b) => a.path.localeCompare(b.path, "de"));
  fillSelect("pkg", packages.map((entry) => [entry.path, entry.path + " (" + entry.count + ")"]));

  const stereoCounts = new Map();
  const typeCounts = new Map();
  nodes.forEach((node) => {
    const key = node.stereo || NONE;
    stereoCounts.set(key, (stereoCounts.get(key) || 0) + 1);
    typeCounts.set(node.type, (typeCounts.get(node.type) || 0) + 1);
  });
  const stereoValues = Array.from(stereoCounts.entries()).sort((a, b) =>
    a[0] === NONE ? 1 : b[0] === NONE ? -1 : a[0].localeCompare(b[0], "de"));
  fillSelect("stereo", stereoValues.map(([value, count]) =>
    [value, (value === NONE ? "(ohne Stereotyp)" : value) + " (" + count + ")"]));
  fillSelect("type", Array.from(typeCounts.entries()).sort((a, b) => b[1] - a[1])
    .map(([value, count]) => [value, value + " (" + count + ")"]));

  const legend = $("legend");
  DATA.groups.slice().sort((a, b) => b.count - a.count).forEach((group) => {
    const item = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "sw";
    swatch.style.background = group.color;
    const name = document.createElement("span");
    name.className = "nm";
    name.textContent = group.name;
    const count = document.createElement("span");
    count.className = "n";
    count.textContent = fmt(group.count);
    item.appendChild(swatch);
    item.appendChild(name);
    item.appendChild(count);
    item.title = "Klick blendet die Gruppe aus/ein";
    item.addEventListener("click", () => {
      if (state.hidden.has(group.name)) state.hidden.delete(group.name);
      else state.hidden.add(group.name);
      item.classList.toggle("off", state.hidden.has(group.name));
      recompute();
      draw();
    });
    legend.appendChild(item);
  });
  $("legend-hint").textContent = DATA.counts.color_depth > 1
    ? "Eine Farbe je Paket der Ebene " + DATA.counts.color_depth +
      " -- Ebene 1 waere bei diesem Modell fast einfarbig. Klick blendet eine Gruppe aus."
    : "Eine Farbe je oberstem Paket. Klick auf einen Eintrag blendet die Gruppe aus.";

  $("q").addEventListener("input", (event) => { state.q = event.target.value; runSearch(); });
  $("pkg").addEventListener("change", (event) => { state.pkg = event.target.value; recompute(); draw(); });
  $("stereo").addEventListener("change", (event) => {
    state.stereo = event.target.value; recompute(); draw();
  });
  $("type").addEventListener("change", (event) => { state.type = event.target.value; recompute(); draw(); });
  $("hide-isolated").addEventListener("change", (event) => {
    state.hideIsolated = event.target.checked; recompute(); draw();
  });
  $("all-edges").addEventListener("change", (event) => {
    state.showAllEdges = event.target.checked; recompute(); draw();
  });
  $("show-labels").addEventListener("change", (event) => {
    state.labels = event.target.checked; draw();
  });
  $("fit").addEventListener("click", fit);
  $("zoom-fit").addEventListener("click", fit);
  $("zoom-in").addEventListener("click", () => zoomAt(1.25, W / 2, H / 2));
  $("zoom-out").addEventListener("click", () => zoomAt(1 / 1.25, W / 2, H / 2));
  $("reset").addEventListener("click", () => {
    state.pkg = ""; state.stereo = ""; state.type = ""; state.q = ""; state.query = "";
    state.matches = new Set(); state.hits = []; state.hidden.clear();
    state.showAllEdges = false; state.hideIsolated = false;
    $("pkg").value = ""; $("stereo").value = ""; $("type").value = "";
    $("q").value = ""; $("all-edges").checked = false; $("hide-isolated").checked = false;
    Array.from(legend.children).forEach((item) => item.classList.remove("off"));
    select(-1, false);
    renderHits();
    recompute();
    fit();
  });

  // -- Start ---------------------------------------------------------------
  function kick() {
    if (!state.running) {
      state.running = true;
      requestAnimationFrame(loop);
    }
  }

  function loop() {
    if (state.running === false) return;
    if (state.alpha > 0.02) {
      const tSim = (window.performance && performance.now) ? performance.now() : Date.now();
      simulate(2);
      document.body.dataset.viewerSimMs = (((window.performance && performance.now) ? performance.now() : Date.now()) - tSim).toFixed(2);
      draw();
      requestAnimationFrame(loop);
    } else {
      state.running = false;
      draw();
    }
  }

  function boot() {
    resize();
    recompute();
    renderDetail();
    // Erster Blick: alles einpassen, dann langsam "festlaufen" lassen.
    fit();
    simulate(24);
    fit();
    requestAnimationFrame(loop);
    const now = (window.performance && performance.now) ? performance.now() : Date.now();
    const loadMs = Math.round(now - t0);
    $("stat-load").textContent = "geladen in " + (loadMs / 1000).toFixed(2).replace(".", ",") + " s";
    document.body.dataset.viewerLoadMs = String(loadMs);
    document.body.dataset.viewerCounts = JSON.stringify(DATA.counts);
    const noteParts = [];
    noteParts.push(DATA.counts.skipped_edges
      ? DATA.counts.skipped_edges + " Kanten enden auf einem Paketspiegel und werden nicht gezeichnet."
      : "Alle Kanten haben zwei Element-Endpunkte.");
    if (DATA.counts.omitted_edges) {
      noteParts.push(DATA.counts.omitted_edges + " Kanten enden auf einem nicht geladenen Knoten.");
    }
    $("m-note").textContent = noteParts.join(" ");
    if (DATA.counts.omitted_nodes) {
      $("m-note").textContent += " " + DATA.counts.omitted_nodes +
        " Knoten wurden wegen der Knotengrenze nicht geladen.";
    }
    if (!DATA.counts.nodes) {
      document.getElementById("empty-text").textContent =
        "Dieses Modell enthaelt keine Elemente -- die .qea ist leer.";
    }
    window.__viewer = {
      counts: DATA.counts,
      loadMs: loadMs,
      visible: visibleCount,
      nodes: nodes.length,
      edges: edges.length
    };
    setTimeout(draw, 60);
  }

  window.addEventListener("resize", resize);
  window.addEventListener("load", boot);
  if (document.readyState === "complete") boot();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
