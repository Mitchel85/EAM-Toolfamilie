"""Statische Pruefung des Kerns: nur Standardbibliothek, kein Netz, deterministisch.

Geprueft werden alle Module der Repo-Wurzel (der Kern) und die CI-Bausteine
unter ``ci/``. Die Pruefung ist bewusst ohne Fremdpakete umgesetzt (``ast`` aus
der Standardbibliothek), damit sie auf einem Runner ohne Netz laeuft.

Regeln:

* ``syntax``       -- Modul laesst sich nicht uebersetzen.
* ``python``       -- Laufzeit ist aelter als 3.11 (harte Vorgabe).
* ``fremdpaket``   -- Import ausserhalb der Standardbibliothek und der eigenen Module.
* ``netz``         -- Netzwerkmodul im Kern (erlaubt ist nur ``urllib.request`` in
                      ``extract.py``, weil das LLM-Backend dort HTTP spricht).
* ``determinismus``-- ``time``/``datetime``/``uuid``/``random`` oder ``os.urandom``
                      im Kern: Zeitstempel und Zufall gehoeren nicht in die Ausgabe.
* ``kern``         -- die Weboberflaeche darf den Kern nicht importieren; sie
                      orchestriert ausschliesslich ueber die Kommandozeile.

Die Weboberflaeche ``webui.py`` ist die einzige bewusste Netz-aussenstelle des
Projekts (``http.server``, Zeit fuer Limits und Aufraeumen, Zufall fuer
Auftrags-IDs). Sie schreibt selbst keine ``.qea``; ihre Ausnahmen sind eng auf
diese eine Datei begrenzt, damit der Kern weiter ohne Netz und Zeit bleibt.

Exit 0 nur ohne Befund. Jeder Befund nennt Datei, Zeile, Regel und Grund.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

MIN_PYTHON = (3, 11)
LOCAL_ONLY_MODULES = {"__future__"}
NETWORK_ROOTS = {
    "socket",
    "ssl",
    "http",
    "http.client",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "websocket",
    "websockets",
    "openai",
    "anthropic",
    "mistralai",
    "cohere",
    "litellm",
    "transformers",
    "torch",
    "llama_cpp",
    "sentence_transformers",
}
# Einzige erlaubte Netz-Ausnahmen im Kern:
# * extract.py spricht HTTP (austauschbares LLM-Backend).
# * eam_suite.py importiert socket nur, um es fuer den --no-llm-Pfad zu sperren.
NETWORK_EXCEPTIONS = {
    ("extract.py", "urllib.request"),
    ("extract.py", "urllib.error"),
    ("eam_suite.py", "socket"),
}
NONDETERMINISTIC_ROOTS = {"time", "datetime", "uuid", "random"}
CI_ALLOWED_EXTRA = {"urllib.request", "urllib.error", "urllib.parse", "socket"}
# Die Weboberflaeche ist die einzige bewusste Netz-aussenstelle (siehe Modul-
# Docstring). Der Kern selbst bleibt ohne Ausnahme netzfrei und ohne Zeit.
FRONTEND_MODULES = {"webui.py"}
# Der MDG-Leser liegt in packages/rules und wird nicht mehr als Fremdpaket
# gezaehlt: er ist Teil dieses Quellstands, nur an anderer Stelle.
SIBLING_PACKAGES = {"mdg_parser"}
CORE_MODULES = {
    "eam_ai",
    "eam_suite",
    "emit",
    "extract",
    "qea_reader",
    "qea_writer",
    "rules_schema",
    "table_import",
    "validator",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    """Alle importierten Module mit Zeilennummer, auch Importe in Funktionen."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # relativer Import bleibt im Paket
            if node.module:
                found.append((node.lineno, node.module))
    return found


def _calls(tree: ast.AST) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            parts: list[str] = []
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                parts.append(target.id)
            if parts:
                calls.append((node.lineno, ".".join(reversed(parts))))
    return calls


def _local_modules(root: Path) -> set[str]:
    return {path.stem for path in root.glob("*.py")} | {"ci"}


def check_core_module(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    relative = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError) as exc:
        return [Finding(relative, getattr(exc, "lineno", 0) or 0, "syntax", str(exc))]

    local = _local_modules(root) | SIBLING_PACKAGES
    stdlib = set(sys.stdlib_module_names)
    frontend = relative in FRONTEND_MODULES
    for line, module in _imported_modules(tree):
        root_module = module.split(".", 1)[0]
        if frontend and (root_module in CORE_MODULES or module in CORE_MODULES):
            findings.append(
                Finding(
                    relative,
                    line,
                    "kern",
                    f"{module} -- die Weboberflaeche orchestriert nur ueber die CLI",
                )
            )
            continue
        if (relative, module) in NETWORK_EXCEPTIONS:
            continue
        if root_module in NETWORK_ROOTS or module in NETWORK_ROOTS:
            if frontend:
                continue
            findings.append(
                Finding(relative, line, "netz", f"{module} -- der Kern spricht kein Netz")
            )
            continue
        if root_module == "urllib" and module != "urllib.parse":
            if frontend:
                continue
            findings.append(
                Finding(relative, line, "netz", f"{module} -- der Kern spricht kein Netz")
            )
            continue
        if root_module in NONDETERMINISTIC_ROOTS:
            if frontend:
                continue
            findings.append(
                Finding(
                    relative,
                    line,
                    "determinismus",
                    f"{module} -- Zeit/Zufall gehoert nicht in die Ausgabe",
                )
            )
            continue
        if root_module in LOCAL_ONLY_MODULES or root_module in stdlib or root_module in local:
            continue
        findings.append(
            Finding(relative, line, "fremdpaket", f"{module} -- nur Standardbibliothek erlaubt")
        )

    if frontend:
        return findings
    for line, call in _calls(tree):
        if call in {"os.urandom", "random.random", "uuid.uuid4"}:
            findings.append(
                Finding(relative, line, "determinismus", f"{call}() -- Ausgabe muss reproduzierbar sein")
            )
    return findings


def check_ci_module(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    relative = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError) as exc:
        return [Finding(relative, getattr(exc, "lineno", 0) or 0, "syntax", str(exc))]

    stdlib = set(sys.stdlib_module_names)
    for line, module in _imported_modules(tree):
        root_module = module.split(".", 1)[0]
        if root_module in LOCAL_ONLY_MODULES or root_module in stdlib or root_module in {"ci"}:
            continue
        if module in CI_ALLOWED_EXTRA:
            continue
        findings.append(
            Finding(relative, line, "fremdpaket", f"{module} -- CI-Werkzeug bleibt standardbibliothek")
        )
    return findings


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if tuple(sys.version_info[:2]) < MIN_PYTHON:
        findings.append(
            Finding(
                ".",
                0,
                "python",
                f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ noetig, laeuft mit {sys.version.split()[0]}",
            )
        )
    core_modules = sorted(
        path for path in root.glob("*.py") if path.name != "conftest.py"
    )
    if not core_modules:
        findings.append(Finding(".", 0, "python", "keine Kernmodule gefunden -- falsches Verzeichnis?"))
    for path in core_modules:
        findings.extend(check_core_module(path, root))
    ci_modules = sorted((root / "ci").glob("*.py"))
    for path in ci_modules:
        findings.extend(check_ci_module(path, root))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ci.lint_core",
        description="Kern auf Standardbibliothek, Netzfreiheit und Determinismus pruefen.",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()

    findings = run(root)
    for finding in findings:
        print(finding.render())
    modules = len([path for path in root.glob("*.py") if path.name != "conftest.py"])
    modules += len(list((root / "ci").glob("*.py")))
    if findings:
        print(f"lint_core: {len(findings)} Befund(e) in {modules} Modul(en)", file=sys.stderr)
        return 1
    print(f"lint_core: {modules} Modul(e), 0 Befunde")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
