"""Testlauf mit Netz-Sperre und JUnit-Bericht.

Warum ein Wrapper? Die Sperre muss fuer den **Testprozess** gelten, nicht fuer
die Installation der Testwerkzeuge davor. Statt in jeder Pipeline eine
Umgebungsvariable vor den Befehl zu schreiben (und damit die Paritaet zwischen
GitLab und GitHub zu zerfasern), macht das genau eine Stelle: dieses Skript.

Es startet ``pytest`` als Unterprozess mit:

* ``EAM_NET_GUARD=1`` -- ``ci/sitecustomize.py`` sperrt ausgehende Verbindungen
  zu nicht-lokalen Zielen (Loopback bleibt erlaubt, damit lokale Testserver
  funktionieren),
* ``PYTHONPATH=<repo>/ci`` -- damit ``sitecustomize`` ueberhaupt geladen wird,
* angelegtem ``reports/``-Verzeichnis fuer den JUnit-Bericht.

Exit-Code ist der von pytest. Fehlt pytest, endet der Lauf laut mit Exit 1.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "reports" / "junit.xml"


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    report = DEFAULT_REPORT
    for index, argument in enumerate(arguments):
        if argument.startswith("--junitxml="):
            report = Path(argument.split("=", 1)[1]).resolve()
        elif argument == "--junitxml" and index + 1 < len(arguments):
            report = Path(arguments[index + 1]).resolve()

    available = importlib.util.find_spec("pytest") is not None
    if not available:
        print(
            "FEHLER: pytest fehlt -- 'python -m pip install --requirement ci/requirements-ci.txt'",
            file=sys.stderr,
        )
        return 1

    report.parent.mkdir(parents=True, exist_ok=True)

    environment = dict(os.environ)
    environment["EAM_NET_GUARD"] = "1"
    local_ci = str(ROOT / "ci")
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        local_ci if not existing else local_ci + os.pathsep + existing
    )
    environment.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    command = [sys.executable, "-m", "pytest", *arguments]
    if not any(argument.startswith("--junitxml") for argument in arguments):
        command.append(f"--junitxml={report}")
    print(f"run_tests: {' '.join(command)} (Netz gesperrt)", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=environment)
    print(f"run_tests: pytest Exit {completed.returncode}, Bericht {report}", flush=True)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
