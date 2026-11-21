"""model_io.py -- Einheitliche Schnittstelle fuer alle 4 Architekturformate.

Unterstuetzte Formate:
1. ``.qea``       -- Sparx Enterprise Architect (SQLite 3)
2. ``.xmi``       -- XML Metadata Interchange (UML 2.1 & 1.3)
3. ArchiMate      -- The Open Group ArchiMate 3.2 Exchange File Format (``.xml``)
4. ``.json``      -- IR-JSON oder JSON-Batch (Knoten/Kanten fuer Graphen/ArAMIS)

Alle Lese- und Schreiboperationen sind deterministisch und arbeiten ueber
das kanonische Zwischenformat (IR - Intermediate Representation).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import archimate_reader
import archimate_writer
import json_batch
import qea_reader
import qea_writer
import xmi_reader
import xmi_writer

FORMATS = ("qea", "xmi", "archimate", "xml", "json")


class ModelIOError(RuntimeError):
    """Fehler beim Lesen, Schreiben oder Konvertieren von Modellen."""


def detect_format(source: str | Path | bytes) -> str:
    """Erkennt das Format anhand der Endung oder des Inhalts."""
    raw = b""
    ext = ""
    if isinstance(source, bytes):
        raw = source[:2048]
    elif isinstance(source, (str, os.PathLike)):
        p = Path(source)
        ext = p.suffix.lower()
        if p.is_file():
            try:
                with p.open("rb") as f:
                    raw = f.read(2048)
            except OSError:
                raw = b""
    else:
        raise TypeError(f"detect_format erwartet Pfad oder Bytes, nicht {type(source).__name__}")

    if raw.startswith(b"SQLite format 3\x00") or ext == ".qea":
        return "qea"

    if ext == ".xmi":
        return "xmi"
    if ext == ".json":
        return "json"

    stripped = raw.strip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return "json"

    if stripped.startswith(b"<") or b"<?xml" in raw[:100]:
        lower = raw.lower()
        if b"archimate" in lower or b"http://www.opengroup.org" in lower:
            return "archimate"
        if b"xmi" in lower or b"uml" in lower:
            return "xmi"
        if ext in (".archimate", ".xml"):
            return "archimate"

    if ext == ".xml":
        return "archimate"

    raise ModelIOError(f"Format konnte nicht erkannt werden: {source}")


def batch_to_ir(data: Mapping[str, Any]) -> dict[str, Any]:
    """Wandelt ein JSON-Batch (Knoten/Kanten) verlustfrei in ein kanonisches IR-Dict."""
    if not isinstance(data, Mapping):
        raise ModelIOError("JSON-Batch muss ein Objekt sein")

    # Wenn es bereits ein IR-Dict ist, direkt zurueckgeben
    if "elements" in data or "packages" in data:
        return dict(data)

    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ModelIOError("JSON-Batch erfordert 'nodes' und 'edges' als Arrays")

    nodes_by_id: dict[str, dict[str, Any]] = {}
    for n in nodes:
        if isinstance(n, dict) and "id" in n:
            nodes_by_id[str(n["id"])] = n

    meta = data.get("metadata") or {}
    standard = str(meta.get("standard") or "")
    technology = {"profile": standard} if standard else {}

    packages: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []

    for n in nodes:
        if not isinstance(n, dict):
            continue
        metaclass = str(n.get("metaclass") or "")
        name = str(n.get("name") or "")
        stereotype = str(n.get("stereotype") or "")
        props = dict(n.get("properties") or {})
        notes = str(props.pop("notes", "") or "")
        alias = str(props.pop("alias", "") or "")
        status = str(props.pop("status", "") or "")
        origin = str(props.pop("origin", "") or "")
        ea_guid = str(n.get("ea_guid") or props.pop("ea_guid", "") or "")
        tags = {str(k): str(v) for k, v in props.items()}

        if metaclass == "Package":
            pkg_entry: dict[str, Any] = {"path": name}
            if stereotype:
                pkg_entry["stereotype"] = stereotype
            if notes:
                pkg_entry["notes"] = notes
            if ea_guid:
                pkg_entry["ea_guid"] = ea_guid
            if tags:
                pkg_entry["tags"] = tags
            packages.append(pkg_entry)
        else:
            package_path = str(n.get("package") or "")
            elem_entry: dict[str, Any] = {
                "name": name,
                "package": package_path,
                "ea_type": metaclass or "Class",
            }
            if stereotype:
                elem_entry["stereotype"] = stereotype
            if notes:
                elem_entry["notes"] = notes
            if alias:
                elem_entry["alias"] = alias
            if status:
                elem_entry["status"] = status
            if origin:
                elem_entry["origin"] = origin
            if ea_guid:
                elem_entry["ea_guid"] = ea_guid
            if tags:
                elem_entry["tags"] = tags
            elements.append(elem_entry)

    connectors: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src_id = str(edge.get("source_id") or "")
        tgt_id = str(edge.get("target_id") or "")
        src_node = nodes_by_id.get(src_id)
        tgt_node = nodes_by_id.get(tgt_id)
        if not src_node or not tgt_node:
            continue

        src_pkg = str(src_node.get("package") or "")
        src_name = str(src_node.get("name") or "")
        src_ref = f"{src_pkg}::{src_name}" if src_pkg and src_node.get("metaclass") != "Package" else src_name

        tgt_pkg = str(tgt_node.get("package") or "")
        tgt_name = str(tgt_node.get("name") or "")
        tgt_ref = f"{tgt_pkg}::{tgt_name}" if tgt_pkg and tgt_node.get("metaclass") != "Package" else tgt_name

        conn_name = str(edge.get("name") or "")
        stereotype = str(edge.get("connector") or "")
        metaclass = str(edge.get("metaclass") or "Dependency")
        e_props = dict(edge.get("properties") or {})
        notes = str(e_props.pop("notes", "") or "")
        ea_guid = str(edge.get("ea_guid") or e_props.pop("ea_guid", "") or "")
        tags = {str(k): str(v) for k, v in e_props.items()}

        conn_entry: dict[str, Any] = {
            "source": src_ref,
            "target": tgt_ref,
            "ea_type": metaclass,
        }
        if conn_name:
            conn_entry["name"] = conn_name
        if stereotype:
            conn_entry["stereotype"] = stereotype
        if notes:
            conn_entry["notes"] = notes
        if ea_guid:
            conn_entry["ea_guid"] = ea_guid
        if tags:
            conn_entry["tags"] = tags
        connectors.append(conn_entry)

    ir: dict[str, Any] = {
        "ir_version": 1,
        "packages": packages,
        "elements": elements,
        "connectors": connectors,
    }
    if technology:
        ir["technology"] = technology
    if "diagrams" in data:
        ir["diagrams"] = data["diagrams"]

    return ir


def read_model(path: str | Path, format: str | None = None) -> dict[str, Any]:
    """Liest ein Architekturmodell aus einer beliebigen der 4 Formate und liefert das IR-Dict."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Quelldatei nicht gefunden: {p}")

    fmt = (format or detect_format(p)).lower()
    if fmt == "qea":
        try:
            return qea_reader.read_qea(p)
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Lesen von QEA {p}: {exc}") from exc

    elif fmt == "xmi":
        try:
            return xmi_reader.read_xmi(p)
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Lesen von XMI {p}: {exc}") from exc

    elif fmt in ("archimate", "xml"):
        # Bei .xml pruefen, ob es echtes ArchiMate oder XMI ist
        detected = detect_format(p)
        if detected == "xmi":
            return xmi_reader.read_xmi(p)
        try:
            return archimate_reader.read_archimate(p)
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Lesen von ArchiMate {p}: {exc}") from exc

    elif fmt == "json":
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "nodes" in raw and "edges" in raw:
                return batch_to_ir(raw)
            return raw
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Lesen von JSON {p}: {exc}") from exc

    else:
        raise ModelIOError(f"Unbekanntes Format: {fmt} (gueltig: qea, xmi, archimate, xml, json)")


def _canonicalize_ir_for_qea(ir: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(ir)
    if "ir_version" not in out:
        out["ir_version"] = 1

    packages: list[dict[str, Any]] = []
    pkg_paths: set[str] = set()
    for p_entry in list(out.get("packages") or []):
        p_dict = dict(p_entry)
        if "guid" not in p_dict and "ea_guid" in p_dict:
            p_dict["guid"] = p_dict.pop("ea_guid")
        if p_dict.get("path"):
            pkg_paths.add(p_dict["path"])
        packages.append(p_dict)

    elements: list[dict[str, Any]] = []
    for e in out.get("elements") or []:
        e_dict = dict(e)
        if "guid" not in e_dict and "ea_guid" in e_dict:
            e_dict["guid"] = e_dict.pop("ea_guid")
        if "source_ref" in e_dict:
            sref = e_dict.pop("source_ref")
            tags = dict(e_dict.get("tags") or {})
            tags.setdefault("source_ref", sref)
            e_dict["tags"] = tags
        # Unbekannte Felder fuer qea_writer abfangen
        for unknown in ("confidence", "id"):
            e_dict.pop(unknown, None)

        pkg = e_dict.get("package") or "Modell"
        e_dict["package"] = pkg
        if pkg not in pkg_paths:
            parts = pkg.split("/")
            cur = ""
            for part in parts:
                cur = f"{cur}/{part}" if cur else part
                if cur not in pkg_paths:
                    packages.append({"path": cur})
                    pkg_paths.add(cur)
        elements.append(e_dict)

    if not packages:
        packages.append({"path": "Modell"})

    out["packages"] = packages
    out["elements"] = elements

    elem_pkg = {e["name"]: e["package"] for e in elements if e.get("name") and e.get("package")}
    connectors: list[dict[str, Any]] = []
    for c in out.get("connectors") or []:
        c_dict = dict(c)
        if "guid" not in c_dict and "ea_guid" in c_dict:
            c_dict["guid"] = c_dict.pop("ea_guid")
        if "source_ref" in c_dict:
            sref = c_dict.pop("source_ref")
            tags = dict(c_dict.get("tags") or {})
            tags.setdefault("source_ref", sref)
            c_dict["tags"] = tags
        for unknown in ("confidence", "id"):
            c_dict.pop(unknown, None)

        src = str(c_dict.get("source") or "")
        dst = str(c_dict.get("target") or "")
        if "::" not in src and src in elem_pkg:
            c_dict["source"] = f"{elem_pkg[src]}::{src}"
        if "::" not in dst and dst in elem_pkg:
            c_dict["target"] = f"{elem_pkg[dst]}::{dst}"
        connectors.append(c_dict)
    out["connectors"] = connectors
    return out


def _prepare_ir_for_archimate(ir: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(ir)
    elements: list[dict[str, Any]] = []
    name_to_ref: dict[str, str] = {}
    guid_to_ref: dict[str, str] = {}

    for idx, e in enumerate(out.get("elements") or [], start=1):
        e_dict = dict(e)
        ref = str(e_dict.get("ref") or "")
        if not ref:
            pkg = str(e_dict.get("package") or "Modell")
            name = str(e_dict.get("name") or f"elem_{idx}")
            ref = f"{pkg}::{name}"
            e_dict["ref"] = ref
        name = str(e_dict.get("name") or "")
        if name:
            name_to_ref[name] = ref
        guid = str(e_dict.get("guid") or e_dict.get("ea_guid") or "")
        if guid:
            guid_to_ref[guid] = ref
        elements.append(e_dict)
    out["elements"] = elements

    connectors: list[dict[str, Any]] = []
    for c in out.get("connectors") or []:
        c_dict = dict(c)
        src = str(c_dict.get("source") or "")
        tgt = str(c_dict.get("target") or "")
        c_dict["source"] = name_to_ref.get(src, guid_to_ref.get(src, src))
        c_dict["target"] = name_to_ref.get(tgt, guid_to_ref.get(tgt, tgt))
        connectors.append(c_dict)
    out["connectors"] = connectors
    return out


def write_model(
    ir: Mapping[str, Any],
    path: str | Path,
    format: str | None = None,
    *,
    source_document: str = "",
    modellname: str = "",
    mode: str = "batch",
    **kwargs: Any,
) -> Path:
    """Schreibt ein IR-Dict in eines der 4 Formate."""
    p = Path(path)
    fmt = (format or detect_format(p)).lower()
    p.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "qea":
        try:
            ir_dict = _canonicalize_ir_for_qea(ir)
            return qea_writer.write_qea(ir_dict, p, **kwargs)
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Schreiben von QEA {p}: {exc}") from exc

    elif fmt == "xmi":
        try:
            ir_dict = _canonicalize_ir_for_qea(ir)
            return xmi_writer.write_xmi(ir_dict, p, **kwargs)
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Schreiben von XMI {p}: {exc}") from exc

    elif fmt in ("archimate", "xml"):
        try:
            mname = modellname or p.stem
            ir_dict = _prepare_ir_for_archimate(ir)
            archimate_writer.write_archimate(ir_dict, p, modellname=mname, **kwargs)
            return p
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Schreiben von ArchiMate {p}: {exc}") from exc

    elif fmt == "json":
        try:
            if mode == "ir":
                p.write_text(json.dumps(ir, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return p
            src_doc = source_document or modellname or p.stem
            ir_dict = _canonicalize_ir_for_qea(ir)
            return json_batch.write_json_batch(ir_dict, p, source_document=src_doc)
        except Exception as exc:
            raise ModelIOError(f"Fehler beim Schreiben von JSON {p}: {exc}") from exc

    else:
        raise ModelIOError(f"Unbekanntes Zielformat: {fmt} (gueltig: qea, xmi, archimate, xml, json)")


def convert_model(
    src: str | Path,
    dst: str | Path,
    out_format: str | None = None,
    *,
    in_format: str | None = None,
    source_document: str = "",
    modellname: str = "",
    **kwargs: Any,
) -> Path:
    """Konvertiert ein Modell direkt von einer Quelldatei in eine Zieldatei."""
    ir = read_model(src, format=in_format)
    return write_model(
        ir,
        dst,
        format=out_format,
        source_document=source_document or Path(src).name,
        modellname=modellname or Path(dst).stem,
        **kwargs,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="model_io",
        description="Konvertiert Modelle zwischen .qea, .xmi, ArchiMate .xml und .json.",
    )
    parser.add_argument("source", type=Path, help="Quelldatei (.qea, .xmi, .xml, .json)")
    parser.add_argument("-o", "--out", type=Path, required=True, help="Zieldatei")
    parser.add_argument("--from", dest="in_format", choices=FORMATS, default=None, help="Quellformat explizit")
    parser.add_argument("--to", dest="out_format", choices=FORMATS, default=None, help="Zielformat explizit")
    parser.add_argument("--source-document", default="", help="Quellbeleg fuer Metadaten")
    args = parser.parse_args(argv)

    try:
        ziel = convert_model(
            args.source,
            args.out,
            in_format=args.in_format,
            out_format=args.out_format,
            source_document=args.source_document,
        )
        print(f"geschrieben: {ziel} ({ziel.stat().st_size} Bytes)")
        return 0
    except Exception as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
