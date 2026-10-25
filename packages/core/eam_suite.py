#!/usr/bin/env python3
"""eam_suite.py -- Gesamtlauf der EAM AI Suite Python: importieren, pruefen, exportieren.

Der Regelpfad ist vollstaendig KI-frei:

    import   JSON-IR | .qea | CSV | XLSX  ->  IR-JSON
    validate IR + Regelwerk               ->  findings.json
    export   IR                           ->  .qea (deterministisch)
    run      Quelle -> pruefen -> .qea    (ein Aufruf, ohne KI)

KI ist kein Bestandteil des Kerns. Dieses Modul importiert weder ein
Extraktions- noch ein Netzwerk-Modul. Der Modus ``--no-llm`` macht das
verbindlich und pruefbar:

* ein Import-Finder blockiert KI- und Netzwerk-Client-Module
  (``extract``, ``openai``, ``requests``, ``http``, ...),
* ``socket.connect``/``create_connection``/``getaddrinfo`` werden gesperrt --
  ein Lauf kann also gar nicht ins Netz greifen.

Ohne ``--no-llm`` bleibt das Verhalten identisch (der Kern laedt keine KI);
das Flag ist die harte Zusage fuer Pruefungen und den Offline-Betrieb.

Exit-Codes
----------
0 = Erfolg, 1 = Regelverstoss (oder Warnung mit --strict; kein Export),
2 = Aufruffehler (argparse), 3 = Eingabefehler (unlesbar, strukturell falsch).

Beispiel
--------
    python3 eam_suite.py --no-llm run --from xlsx modell.xlsx \\
        --rules rules.json -o modell.qea --findings findings.json

Grenzen: keine Sichten, kein Layout, kein interaktiver Editor. Kein Netz.
"""

from __future__ import annotations

import argparse
import importlib.abc
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qea_reader import QeaReaderError, read_qea_ex, render_json
from qea_writer import QeaWriterError, load_ir, plan_model, write_qea
from table_import import TableImportError, import_table, import_tables
from validator import (
    ValidatorError,
    build_rules,
    dumps_findings,
    load_requirements,
    load_rules,
    summarize,
    validate_model,
    write_findings,
)

# Module, die im KI-/Netzpfad liegen. Der Kern braucht keines davon.
_LLM_ROOTS = frozenset(
    {
        "extract",
        "llm",
        "llm_client",
        "openai",
        "anthropic",
        "mistralai",
        "cohere",
        "litellm",
        "transformers",
        "torch",
        "llama_cpp",
        "sentence_transformers",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "websocket",
        "websockets",
        "http",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "xmlrpc",
    }
)
_LLM_PREFIXES = (
    "urllib.request",
    "urllib.error",
    "google.generativeai",
    "google.cloud.aiplatform",
    "google.oauth2",
)

_SOURCE_KINDS = ("auto", "json", "qea", "csv", "xlsx")
_SUFFIXES = {".json": "json", ".qea": "qea", ".csv": "csv", ".xlsx": "xlsx"}


class NetworkBlocked(RuntimeError):
    """Ein Netzwerkzugriff wurde durch --no-llm verhindert."""


class NoLlmImportBlocked(ImportError):
    """Ein KI-/Netzwerkmodul wurde durch --no-llm blockiert."""


def _blocked_module(name: str) -> bool:
    if name.split(".", 1)[0] in _LLM_ROOTS:
        return True
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _LLM_PREFIXES)


class _NoLlmFinder(importlib.abc.MetaPathFinder):
    """Blockiert KI- und Netzwerkmodule, bevor sie geladen werden."""

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if _blocked_module(fullname):
            raise NoLlmImportBlocked(
                f"--no-llm: Import von '{fullname}' gesperrt (KI/Netz gehoert nicht zum Regelpfad)"
            )
        return None


_GUARD_INSTALLED = False
_NETWORK_INSTALLED = False
_META_FINDER: _NoLlmFinder | None = None
_ORIGINALS: dict[str, Any] = {}


def _install_network_guard() -> None:
    """Sperrt ausgehende Verbindungen im laufenden Prozess (idempotent)."""
    global _NETWORK_INSTALLED
    if _NETWORK_INSTALLED:
        return
    import socket

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise NetworkBlocked("--no-llm: Netzwerkzugriff gesperrt")

    _ORIGINALS["socket.connect"] = socket.socket.connect
    _ORIGINALS["socket.connect_ex"] = socket.socket.connect_ex
    _ORIGINALS["socket.sendto"] = socket.socket.sendto
    _ORIGINALS["socket.create_connection"] = socket.create_connection
    _ORIGINALS["socket.getaddrinfo"] = socket.getaddrinfo

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.socket.connect_ex = denied  # type: ignore[method-assign]
    socket.socket.sendto = denied  # type: ignore[method-assign]
    socket.create_connection = denied  # type: ignore[assignment]
    socket.getaddrinfo = denied  # type: ignore[assignment]
    _NETWORK_INSTALLED = True


def install_no_llm_guard() -> None:
    """Aktiviert Import- und Netz-/Netzsperre fuer den Regelpfad (idempotent)."""
    global _GUARD_INSTALLED, _META_FINDER
    if _GUARD_INSTALLED:
        return
    finder = _NoLlmFinder()
    sys.meta_path.insert(0, finder)
    _META_FINDER = finder
    _install_network_guard()
    _GUARD_INSTALLED = True


def remove_no_llm_guard() -> None:
    """Hebt die Sperren wieder auf (fuer Tests und Einbettung)."""
    global _GUARD_INSTALLED, _NETWORK_INSTALLED, _META_FINDER
    if not _GUARD_INSTALLED:
        return
    if _META_FINDER is not None and _META_FINDER in sys.meta_path:
        sys.meta_path.remove(_META_FINDER)
    if _NETWORK_INSTALLED:
        import socket

        socket.socket.connect = _ORIGINALS["socket.connect"]  # type: ignore[method-assign]
        socket.socket.connect_ex = _ORIGINALS["socket.connect_ex"]  # type: ignore[method-assign]
        socket.socket.sendto = _ORIGINALS["socket.sendto"]  # type: ignore[method-assign]
        socket.create_connection = _ORIGINALS["socket.create_connection"]  # type: ignore[assignment]
        socket.getaddrinfo = _ORIGINALS["socket.getaddrinfo"]  # type: ignore[assignment]
        _ORIGINALS.clear()
    _NETWORK_INSTALLED = False
    _META_FINDER = None
    _GUARD_INSTALLED = False


def source_kind(path: str | Path, requested: str = "auto") -> str:
    """Bestimmt die Quellenart; unbekannte oder widerspruechliche Endungen sind laut."""
    suffix = Path(path).suffix.lower()
    detected = _SUFFIXES.get(suffix)
    if requested != "auto":
        if detected != requested:
            raise TableImportError(
                f"{path}: --from {requested} passt nicht zur Dateiendung "
                f"({suffix or 'ohne Endung'})"
            )
        return requested
    if detected is None:
        raise TableImportError(
            f"{path}: Quellenart nicht erkannt (Endung {suffix or 'ohne Endung'!r}) -- "
            "erlaubt: .json, .qea, .csv, .xlsx oder --from angeben"
        )
    return detected


def import_source(
    path: str | Path,
    *,
    kind: str = "auto",
    table_kind: str = "auto",
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    profile: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Liest JSON-IR, .qea, CSV oder XLSX und liefert strukturell geprueftes IR."""
    resolved = source_kind(path, kind)
    if resolved not in ("csv", "xlsx"):
        if table_kind not in ("auto", "", None):
            raise TableImportError(
                f"--kind gilt nur fuer Tabellen (Quelle ist {resolved})"
            )
        if delimiter is not None:
            raise TableImportError("--delimiter gilt nur fuer CSV-Tabellen")
        if profile:
            raise TableImportError("--profile gilt nur fuer Tabellen")
    if resolved == "json":
        ir = load_ir(path)
        plan_model(ir)  # Struktur, Feldnamen, Paketbaum, leeres Modell
        return dict(ir)
    if resolved == "qea":
        ir, _ = read_qea_ex(path, strict=strict, allow_empty=False)
        plan_model(ir)
        return ir
    if resolved in ("csv", "xlsx"):
        ir = import_table(
            path,
            kind=table_kind,
            delimiter=delimiter,
            encoding=encoding,
            profile=profile,
        )
        plan_model(ir)
        return ir
    raise TableImportError(f"unbekannte Quellenart {resolved!r}")


def import_sources(
    sources: Sequence[str | Path],
    *,
    kind: str = "auto",
    table_kind: str = "auto",
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    profile: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Liest eine Quelle oder mehrere Tabellen (CSV/XLSX) zu einem IR.

    Mehrere Quellen sind nur fuer Tabellen erlaubt; JSON-IR und .qea sind
    immer genau eine Datei. Eine Mischung aus Tabelle und .qea waere eine
    stille Zusammenfuehrung zweier Modelle und wird abgelehnt.
    """
    paths = [Path(source) for source in sources]
    if not paths:
        raise TableImportError("keine Quelle angegeben")
    kinds = [source_kind(path, kind) for path in paths]
    if len(paths) > 1:
        if not all(item in ("csv", "xlsx") for item in kinds):
            raise TableImportError(
                "mehrere Quellen sind nur fuer Tabellen (.csv/.xlsx) erlaubt -- "
                "JSON-IR und .qea sind genau eine Datei"
            )
        ir = import_tables(
            paths,
            kind=table_kind,
            delimiter=delimiter,
            encoding=encoding,
            profile=profile,
        )
        plan_model(ir)
        return ir
    return import_source(
        paths[0],
        kind=kinds[0],
        table_kind=table_kind,
        delimiter=delimiter,
        encoding=encoding,
        profile=profile,
        strict=strict,
    )


@dataclass(frozen=True)
class RunResult:
    """Ergebnis des Gesamtlaufs (fuer Tests und Einbettung)."""

    ir: Mapping[str, Any]
    findings: Sequence[Mapping[str, str]]
    qea: Path
    exported: bool


def build_rules_from(
    rules_path: str | Path, requirements_path: str | Path | None = None
):
    """Regelwerk inklusive optionaler Pflichtbeziehungen laden."""
    if requirements_path is None:
        return load_rules(rules_path)
    return build_rules(_read_rules_document(rules_path), load_requirements(requirements_path))


def run_pipeline(
    sources: str | Path | Sequence[str | Path],
    *,
    rules_path: str | Path,
    target: str | Path,
    requirements_path: str | Path | None = None,
    kind: str = "auto",
    table_kind: str = "auto",
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    profile: str | None = None,
    strict: bool = False,
    findings_path: str | Path | None = None,
) -> RunResult:
    """Import -> Pruefung -> Export. Bei Regelverstoessen wird nicht exportiert."""
    paths: Sequence[str | Path]
    if isinstance(sources, (str, Path)):
        paths = [sources]
    else:
        paths = list(sources)
    ir = import_sources(
        paths,
        kind=kind,
        table_kind=table_kind,
        delimiter=delimiter,
        encoding=encoding,
        profile=profile,
    )
    rules = build_rules_from(rules_path, requirements_path)
    findings = validate_model(ir, rules)
    if findings_path is not None:
        write_findings(findings, findings_path)

    summary = summarize(findings)
    blocked = bool(summary["error"]) or (strict and bool(summary["warning"]))
    qea = Path(target)
    if blocked:
        return RunResult(ir=ir, findings=findings, qea=qea, exported=False)
    write_qea(ir, qea)
    return RunResult(ir=ir, findings=findings, qea=qea, exported=True)


def _read_rules_document(path: str | Path) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValidatorError(f"Regelwerk {path}: nicht lesbar ({error})") from error
    except json.JSONDecodeError as error:
        raise ValidatorError(f"Regelwerk {path}: kein gueltiges JSON ({error})") from error
    if not isinstance(document, dict):
        raise ValidatorError(f"Regelwerk {path}: Wurzel muss ein Objekt sein")
    return document


# --------------------------------------------------------------------------
# Unterkommandos
# --------------------------------------------------------------------------


def _write_text_ir(ir: Mapping[str, Any], out: Path | None) -> None:
    text = render_json(ir)
    if out is None:
        sys.stdout.write(text)
        return
    try:
        out.write_text(text, encoding="utf-8", newline="\n")
    except OSError as error:
        raise TableImportError(f"{out}: nicht schreibbar ({error})") from error


def cmd_import(args: argparse.Namespace) -> int:
    ir = import_sources(
        args.quellen,
        kind=args.source_kind,
        table_kind=args.table_kind,
        delimiter=args.delimiter,
        encoding=args.encoding,
        profile=args.profile,
        strict=args.strict,
    )
    _write_text_ir(ir, args.out)
    if args.out is not None and not args.quiet:
        print(
            f"{args.out}: {len(ir.get('packages', []))} Pakete, "
            f"{len(ir.get('elements', []))} Elemente, "
            f"{len(ir.get('connectors', []))} Kanten",
            file=sys.stderr,
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    ir = import_source(args.ir)
    rules = build_rules_from(args.rules, args.requirements)
    findings = validate_model(ir, rules)
    if args.out is not None:
        write_findings(findings, args.out)
    else:
        sys.stdout.write(dumps_findings(findings))

    summary = summarize(findings)
    if not args.quiet:
        print(
            f"{summary['total']} Findings: {summary['error']} Fehler, "
            f"{summary['warning']} Warnungen.",
            file=sys.stderr,
        )
    if summary["error"]:
        return 1
    if args.strict and summary["warning"]:
        return 1
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    ir = import_source(args.ir)
    target = write_qea(ir, args.ziel)
    if not args.quiet:
        print(f"{target}: geschrieben", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    result = run_pipeline(
        args.quellen,
        rules_path=args.rules,
        target=args.ziel,
        requirements_path=args.requirements,
        kind=args.source_kind,
        table_kind=args.table_kind,
        delimiter=args.delimiter,
        encoding=args.encoding,
        profile=args.profile,
        strict=args.strict,
        findings_path=args.findings,
    )
    summary = summarize(result.findings)
    if not args.quiet:
        print(
            f"{summary['total']} Findings: {summary['error']} Fehler, "
            f"{summary['warning']} Warnungen.",
            file=sys.stderr,
        )
    if not result.exported:
        if args.strict and summary["warning"] and not summary["error"]:
            print("FEHLER: --strict behandelt Warnungen als Fehler; kein Export.", file=sys.stderr)
        else:
            print("FEHLER: Regelverstoesse; kein Export (findings pruefen).", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"{result.qea}: geschrieben", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _add_table_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--from",
        dest="source_kind",
        default="auto",
        choices=_SOURCE_KINDS,
        help="Quellenart (Default: aus der Dateiendung)",
    )
    parser.add_argument(
        "--kind",
        dest="table_kind",
        default="auto",
        choices=("auto", "mixed", "packages", "elements", "connectors"),
        help="Art der CSV-Tabelle (Default: aus der Kopfzeile)",
    )
    parser.add_argument("--delimiter", help="CSV-Trennzeichen (Default: ',')")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV-Kodierung")
    parser.add_argument("--profile", help="Technologieprofil fuer das IR")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eam_suite.py",
        description="EAM AI Suite Python: Import, Pruefung und Export -- ohne KI, ohne Netz.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Regelpfad erzwingen: KI-Importe und Netzwerkzugriffe sperren",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="keine Statuszeilen")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="Quelle in kanonisches IR-JSON lesen")
    _add_table_options(p_import)
    p_import.add_argument(
        "quellen",
        nargs="+",
        type=Path,
        help="JSON-IR, .qea, .csv oder .xlsx (mehrere nur Tabellen)",
    )
    p_import.add_argument("-o", "--out", type=Path, help="Ziel-IR-JSON (Default: stdout)")
    p_import.add_argument("--strict", action="store_true", help="QEA-Warnungen als Fehler")
    p_import.set_defaults(func=cmd_import)

    p_validate = sub.add_parser("validate", help="IR gegen Regelwerk pruefen")
    p_validate.add_argument("ir", type=Path, help="IR-JSON")
    p_validate.add_argument("rules", type=Path, help="Regelwerk-JSON (mdg_parser.py)")
    p_validate.add_argument("-o", "--out", type=Path, help="findings.json (Default: stdout)")
    p_validate.add_argument("--requirements", type=Path, help="Pflichtbeziehungen (JSON)")
    p_validate.add_argument("--strict", action="store_true", help="Warnungen zaehlen wie Fehler")
    p_validate.set_defaults(func=cmd_validate)

    p_export = sub.add_parser("export", help="IR als .qea schreiben")
    p_export.add_argument("ir", type=Path, help="IR-JSON")
    p_export.add_argument("ziel", type=Path, help="Ziel .qea")
    p_export.set_defaults(func=cmd_export)

    p_run = sub.add_parser("run", help="Quelle importieren, pruefen, exportieren")
    _add_table_options(p_run)
    p_run.add_argument(
        "quellen",
        nargs="+",
        type=Path,
        help="JSON-IR, .qea, .csv oder .xlsx (mehrere nur Tabellen)",
    )
    p_run.add_argument("--rules", type=Path, required=True, help="Regelwerk-JSON")
    p_run.add_argument(
        "--requirements", type=Path, help="Pflichtbeziehungen als JSON-Liste"
    )
    p_run.add_argument("-o", "--out", dest="ziel", type=Path, required=True, help="Ziel .qea")
    p_run.add_argument("--findings", type=Path, help="findings.json schreiben")
    p_run.add_argument("--strict", action="store_true", help="Warnungen blockieren den Export")
    p_run.set_defaults(func=cmd_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    no_llm = "--no-llm" in arguments
    arguments = [value for value in arguments if value != "--no-llm"]
    if no_llm:
        install_no_llm_guard()

    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        return int(args.func(args))
    except NetworkBlocked as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 3
    except (TableImportError, QeaWriterError, QeaReaderError, ValidatorError, OSError) as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
