#!/usr/bin/env python3
"""mcp_stdio.py -- Abhaengigkeitsfreier 4-Format-MCP-Server (JSON-RPC 2.0 ueber stdio).

Stellt den kompletten Python-Kern (``.qea``, ``.xmi``, ArchiMate ``.xml``,
``.json``) als Model Context Protocol (MCP) Werkzeugserver bereit -- **ohne**
``fastmcp``, ``pandas`` oder ``networkx`` und komplett ohne Netzwerk-/Zeit-Importe
(100 % ``lint_core``- und ``--no-llm``-konform).

Aufruf::

    eam-ai mcp
    python3 -m mcp_stdio
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import archimate_check
import graph
import model_diff
import model_edit
import model_io
import nl_edit
import repair_loop
import text_coverage
import validator

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "eam-ai-core"


def _default_mdg_path() -> Path | None:
    here = Path(__file__).resolve().parent
    for cand in (
        here / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml",
        here.parent / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml",
        here / "knowledge" / "regelwerk.json",
        here.parent / "knowledge" / "regelwerk.json",
        here.parent.parent / "knowledge" / "regelwerk.json",
    ):
        if cand.is_file():
            return cand
    return None


TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "eam_inspect_model",
        "description": "Liest Kennzahlen, Pakete, Elemente und Beziehungen aus .qea, .xmi, ArchiMate .xml oder .json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Pfad zur Modelldatei (.qea, .xmi, .xml, .json)"},
                "stereotype": {"type": "string", "description": "Optionaler Stereotyp-Filter"},
                "query": {"type": "string", "description": "Optionaler Suchbegriff fuer Name/Notiz"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["path"],
        },
    },
    {
        "name": "eam_validate_mdg",
        "description": "Prueft ein Modell (.qea, .xmi, .xml, .json) gegen eine MDG-XML oder rules.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Pfad zur Modelldatei"},
                "mdg": {"type": "string", "description": "Optionaler Pfad zur MDG-XML oder rules.json"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "eam_archimate_check",
        "description": "Fuehrt die native ArchiMate-3.2-Matrix-, Konzept- und Waisenpruefung durch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Pfad zur ArchiMate-.xml, .qea oder .json Datei"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "eam_diff_models",
        "description": "Vergleicht zwei Architekturstaende (Alt vs. Neu) ueber alle 4 Formate inkl. optionalem MDG-Befund-Delta.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "alt": {"type": "string", "description": "Pfad zum Alt-/Referenzmodell"},
                "neu": {"type": "string", "description": "Pfad zum Neumodell"},
                "mdg": {"type": "string", "description": "Optionaler Pfad zur MDG-XML oder rules.json"},
            },
            "required": ["alt", "neu"],
        },
    },
    {
        "name": "eam_text_coverage",
        "description": "Prueft deterministisch (ohne KI), welche Absaetze/Kapitel eines Pflichtenhefts im Modell abgedeckt sind.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Pfad zur Modelldatei"},
                "text_path": {"type": "string", "description": "Optionaler Pfad zur Quelldatei (.txt, .md, .docx, .pdf)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "eam_repair_model",
        "description": "Leitet deterministische MDG-Reparaturen ab (Vorschau oder Schreiben in Zieldatei).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Eingabemodell"},
                "mdg": {"type": "string", "description": "Optionaler Pfad zur MDG-XML oder rules.json"},
                "out": {"type": "string", "description": "Optionale Zieldatei (nur mit apply=true)"},
                "apply": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "eam_nl_edit",
        "description": "Aendert oder erweitert eine .qea ueber die deterministische deutsche Befehlsgrammatik (Vorschau oder Schreiben).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "qea_path": {"type": "string", "description": "Quell-.qea"},
                "instruction": {"type": "string", "description": "Anweisung auf Deutsch"},
                "out": {"type": "string", "description": "Ziel-.qea (fuer apply=true)"},
                "mdg": {"type": "string", "description": "Optionale MDG-XML zur Pruefung"},
                "apply": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["qea_path", "instruction"],
        },
    },
    {
        "name": "eam_convert_model",
        "description": "Konvertiert ein Modell zwischen .qea, .xmi, ArchiMate .xml und .json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Quelldatei"},
                "target": {"type": "string", "description": "Zieldatei"},
                "target_format": {"type": "string", "description": "Optional: qea, xmi, archimate, json"},
            },
            "required": ["source", "target"],
        },
    },
    {
        "name": "eam_graph_query",
        "description": "Analysiert Nachbarschaft/Impact oder kuerzeste Pfade im Architekturgraphen.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Modelldatei (.qea, .xmi, .xml, .json)"},
                "element": {"type": "string", "description": "Elementname fuer Umfeld-/Impact-Suche"},
                "target_element": {"type": "string", "description": "Optionales Zielelement fuer Pfadsuche"},
                "depth": {"type": "integer", "default": 2},
            },
            "required": ["path"],
        },
    },
)


def _call_tool(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    if name == "eam_inspect_model":
        ir = validator.load_ir(Path(str(args["path"])))
        els = list(ir.get("elements") or ())
        conns = list(ir.get("connectors") or ())
        pkgs = list(ir.get("packages") or ())
        st_filter = str(args.get("stereotype") or "").strip().casefold()
        q_filter = str(args.get("query") or "").strip().casefold()
        limit = max(1, min(500, int(args.get("limit") or 50)))
        filtered = []
        for e in els:
            if st_filter and str(e.get("stereotype") or "").casefold() != st_filter:
                continue
            if q_filter:
                hay = f"{e.get('name', '')} {e.get('notes', '')} {e.get('package', '')}".casefold()
                if q_filter not in hay:
                    continue
            filtered.append(
                {
                    "package": e.get("package", ""),
                    "name": e.get("name", ""),
                    "stereotype": e.get("stereotype", ""),
                    "ea_type": e.get("ea_type", "Class"),
                    "guid": e.get("guid") or e.get("ea_guid") or "",
                }
            )
        return {
            "format": model_io.detect_format(Path(str(args["path"]))),
            "counts": {"packages": len(pkgs), "elements": len(els), "connectors": len(conns)},
            "elements": filtered[:limit],
            "truncated": len(filtered) > limit,
        }

    if name == "eam_validate_mdg":
        mdg_p = Path(str(args["mdg"])) if args.get("mdg") else _default_mdg_path()
        if mdg_p is None or not mdg_p.is_file():
            raise ValueError("Kein Regelwerk gefunden -- bitte 'mdg' angeben.")
        ir = validator.load_ir(Path(str(args["path"])))
        ruleset = validator.load_rules(mdg_p)
        findings = validator.validate_model(ir, ruleset)
        return {
            "rules": ruleset.name,
            "summary": validator.summarize_findings(findings),
            "findings": findings[:100],
        }

    if name == "eam_archimate_check":
        ir, fmt = archimate_check.lade_modell(Path(str(args["path"])))
        befund = archimate_check.pruefe(ir, format=fmt, datei=str(args["path"]))
        return befund.as_dict()

    if name == "eam_diff_models":
        mdg_arg = Path(str(args["mdg"])) if args.get("mdg") else None
        res = model_diff.diff_models(Path(str(args["alt"])), Path(str(args["neu"])), mdg=mdg_arg)
        return res.as_dict()

    if name == "eam_text_coverage":
        mp = Path(str(args["path"]))
        ir = validator.load_ir(mp)
        tp = Path(str(args["text_path"])) if args.get("text_path") else None
        cov = text_coverage.evaluate_coverage(ir, text_source=tp, model_path=mp)
        if cov is None:
            return {"available": False, "reason": "Weder text_path noch quellen.json vorhanden."}
        return {"available": True, **cov.as_dict()}

    if name == "eam_repair_model":
        mp = Path(str(args["path"]))
        mdg_p = Path(str(args["mdg"])) if args.get("mdg") else _default_mdg_path()
        if mdg_p is None or not mdg_p.is_file():
            raise ValueError("Kein Regelwerk gefunden -- bitte 'mdg' angeben.")
        ir = validator.load_ir(mp)
        ruleset = validator.load_rules(mdg_p)
        outcome = repair_loop.repair(ir, ruleset, max_rounds=6)
        changes = [c.as_dict() for r in outcome.rounds for c in r.changes]
        written = ""
        if args.get("apply") and args.get("out"):
            out_p = model_io.write_model(outcome.ir, Path(str(args["out"])))
            written = str(out_p)
        return {
            "applied": bool(written),
            "written": written,
            "changes_count": len(changes),
            "changes": changes,
            "summary_after": validator.summarize_findings(outcome.findings),
        }

    if name == "eam_nl_edit":
        qp = Path(str(args["qea_path"]))
        prop = nl_edit.propose(qp, str(args["instruction"]), backend=None)
        if not args.get("apply"):
            return {"mode": "preview", **prop.as_dict(), "preview": nl_edit.preview_lines(prop)}
        if not args.get("out"):
            raise ValueError("apply=true erfordert 'out'.")
        mdg_p = Path(str(args["mdg"])) if args.get("mdg") else None
        applied = nl_edit.apply(prop, Path(str(args["out"])), mdg=mdg_p, confirm=bool(args.get("confirm")))
        return {
            "mode": "applied",
            "written": str(applied.written),
            "applied": applied.applied,
            "ops": applied.ops,
            "changes": list(applied.changes),
            "rejected": list(applied.rejected),
        }

    if name == "eam_convert_model":
        out = model_io.convert_model(
            Path(str(args["source"])),
            Path(str(args["target"])),
            out_format=str(args["target_format"]) if args.get("target_format") else None,
        )
        return {"written": str(out), "bytes": out.stat().st_size}

    if name == "eam_graph_query":
        mp = Path(str(args["path"]))
        with tempfile.NamedTemporaryFile(suffix=".db", prefix="eam-mcp-g-", delete=False) as tf:
            tmp_db = Path(tf.name)
        try:
            graph.lade(mp, tmp_db, ersetzen=True)
            con = graph.oeffne(tmp_db)
            try:
                out_g: dict[str, Any] = {"statistik": graph.statistik(con)}
                el_name = str(args.get("element") or "").strip()
                tgt_name = str(args.get("target_element") or "").strip()
                depth = max(1, min(6, int(args.get("depth") or 2)))
                if el_name and tgt_name:
                    out_g["pfad"] = graph.pfad(con, el_name, tgt_name)
                elif el_name:
                    start = graph._ein_knoten(con, el_name)
                    out_g["start"] = dict(start)
                    out_g["umfeld"] = [dict(z) for z in graph.umfeld(con, start["kennung"], tiefe=depth)]
                return out_g
            finally:
                con.close()
        finally:
            tmp_db.unlink(missing_ok=True)

    raise KeyError(f"Unbekanntes MCP-Werkzeug: {name}")


def dispatch_request(message: Mapping[str, Any], *, version: str = "1.0.0") -> dict[str, Any] | None:
    """Verarbeitet eine einzelne JSON-RPC-2.0-Nachricht (synchron, testfreundlich)."""
    method = str(message.get("method") or "")
    msg_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), Mapping) else {}

    # JSON-RPC Notifications (ohne id) erwarten keine Antwort
    if "id" not in message:
        return None

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    if method == "initialize":
        req_proto = str(params.get("protocolVersion") or PROTOCOL_VERSION)
        return ok(
            {
                "protocolVersion": req_proto,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": version},
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": list(TOOLS)})
    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        tool_args = params.get("arguments") if isinstance(params.get("arguments"), Mapping) else {}
        try:
            payload = _call_tool(tool_name, tool_args)
            return ok(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False, indent=2),
                        }
                    ],
                    "isError": False,
                }
            )
        except KeyError as exc:
            return err(-32602, str(exc))
        except Exception as exc:  # noqa: BLE001
            return ok(
                {
                    "content": [{"type": "text", "text": f"FEHLER: {exc}"}],
                    "isError": True,
                }
            )
    return err(-32601, f"Unbekannte Methode: {method}")


def serve_stdio(*, version: str = "3.9.0") -> int:
    """Liest JSON-RPC-Nachrichten von stdin (Zeilen-JSON oder Content-Length) und antwortet auf stdout."""
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        line = stdin.readline()
        if not line:
            break
        stripped = line.strip()
        if not stripped:
            continue
        framed = False
        if stripped.lower().startswith(b"content-length:"):
            framed = True
            length = int(stripped.split(b":", 1)[1].strip())
            while True:
                hdr = stdin.readline()
                if not hdr or hdr in (b"\r\n", b"\n"):
                    break
            raw_body = stdin.read(length)
        else:
            raw_body = stripped

        try:
            msg = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            resp_err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            data = json.dumps(resp_err, ensure_ascii=False).encode("utf-8")
            stdout.write(data + b"\n")
            stdout.flush()
            continue

        if not isinstance(msg, Mapping):
            continue
        response = dispatch_request(msg, version=version)
        if response is None:
            continue
        out_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
        if framed:
            stdout.write(f"Content-Length: {len(out_bytes)}\r\n\r\n".encode("ascii") + out_bytes)
        else:
            stdout.write(out_bytes + b"\n")
        stdout.flush()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EAM 4-Format MCP-Server (stdio, ohne Fremdpakete)")
    ap.add_argument("--list-tools", action="store_true", help="Werkzeuge als JSON ausgeben und beenden")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.list_tools:
        sys.stdout.write(json.dumps({"tools": list(TOOLS)}, ensure_ascii=False, indent=2) + "\n")
        return 0
    return serve_stdio()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
