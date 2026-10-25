#!/usr/bin/env python3
"""Die eine Änderungsmatrix: Quelle -> betroffene Zellen -> Befehl.

Die Regeln sind absichtlich grob (Pfadpräfixe), damit eine Änderung nicht
an einer Datei vorbeiläuft. `scripts/impact.py` nutzt sie für die Anzeige,
`scripts/dependency_report.py` für die Dokumentation.
"""

from __future__ import annotations

import sys
from fnmatch import fnmatch
from pathlib import Path

_RULES = Path(__file__).resolve().parents[1] / "packages" / "rules"
if str(_RULES) not in sys.path:
    sys.path.insert(0, str(_RULES))
import mdg_source  # noqa: E402  (bewusst nach dem Pfad-Aufbau)

#: Aktuelle MDG, relativ zur Repo-Wurzel — Quelle ist packages/rules/CURRENT.
MDG = f"packages/rules/{mdg_source.name()}"

#: id, Pfadmuster, betroffene Zellen, auszuführender Befehl, Erklärung
REGELN: tuple[dict[str, object], ...] = (
    {
        "id": "mdg-quelle",
        "pfade": (
            MDG,
            "packages/rules/mdg_parser.py",
            "packages/rules/documents.py",
            "packages/rules/documents_format.py",
        ),
        "zellen": (
            "knowledge",
            "apps/admbw-extractor",
            "apps/admbw-batch",
            "apps/admbw-script-maker",
            "dist",
        ),
        "befehl": "python3 scripts/propagate.py --all",
        "hinweis": "MDG/Reader geändert: Wissensbasis neu erzeugen, Downstream prüfen.",
    },
    {
        "id": "wissensbasis",
        "pfade": ("knowledge/*",),
        "zellen": (
            "apps/admbw-extractor",
            "apps/admbw-batch",
            "apps/admbw-script-maker",
        ),
        "befehl": "python3 scripts/propagate.py --write && python3 -m pytest -q tests/apps",
        "hinweis": "Die Apps lesen die Wissensbasis über Symlinks; keine Kopie nötig.",
    },
    {
        "id": "vendor",
        "pfade": ("vendor/*",),
        "zellen": (
            "apps/html-suite",
            "apps/html-analyzer",
            "apps/html-editor",
            "dist",
        ),
        "befehl": "python3 scripts/sync_vendor.py --write && python3 scripts/propagate.py --build",
        "hinweis": "Zentrale Browser-Bibliothek: lokale Kopien und HTML-Auslieferungen neu bauen.",
    },
    {
        "id": "html-suite",
        "pfade": ("apps/html-suite/*",),
        "zellen": ("apps/html-suite", "dist"),
        "befehl": "python3 scripts/build_legacy_app.py apps/html-suite && python3 scripts/propagate.py --release",
        "hinweis": "Eigenständiger Altstand: nur diese App und ihr Release-Asset ändern sich.",
    },
    {
        "id": "html-analyzer",
        "pfade": ("apps/html-analyzer/*",),
        "zellen": ("apps/html-analyzer", "dist"),
        "befehl": "python3 scripts/build_legacy_app.py apps/html-analyzer && python3 scripts/propagate.py --release",
        "hinweis": "Eigenständiger Altstand: nur diese App und ihr Release-Asset ändern sich.",
    },
    {
        "id": "html-editor",
        "pfade": ("apps/html-editor/*",),
        "zellen": ("apps/html-editor", "dist"),
        "befehl": "python3 scripts/build_legacy_app.py apps/html-editor && python3 scripts/propagate.py --release",
        "hinweis": "Eigenständiger Altstand: nur diese App und ihr Release-Asset ändern sich.",
    },
    {
        "id": "mdg-web",
        "pfade": ("apps/mdg-web/*",),
        "zellen": ("apps/mdg-web", "dist"),
        "befehl": "python3 apps/mdg-web/build.py && python3 scripts/propagate.py --release",
        "hinweis": "Browser-Parser ist eigenständig; keine Python-Regelwerk-Kante.",
    },
    {
        "id": "python-kern",
        "pfade": ("packages/core/*",),
        "zellen": ("apps/cli", "apps/mcp", "dist"),
        "befehl": "python3 scripts/propagate.py --build",
        "hinweis": "Kernänderung wirkt auf CLI, MCP und das Quell-Archiv.",
    },
    {
        "id": "mcp-werkzeug",
        "pfade": ("apps/mcp/*",),
        "zellen": ("apps/mcp", "dist"),
        "befehl": "python3 scripts/propagate.py --release",
        "hinweis": "Open-WebUI-Datei und MCP-Hülle werden als Release-Asset gesammelt.",
    },
    {
        "id": "admbw-tools",
        "pfade": ("apps/admbw-extractor/*", "apps/admbw-batch/*", "apps/admbw-script-maker/*"),
        "zellen": ("apps/admbw-extractor", "apps/admbw-batch", "apps/admbw-script-maker"),
        "befehl": "python3 scripts/propagate.py --check && python3 apps/admbw-batch/checks/verify.py",
        "hinweis": "Werkzeuge lesen die Wissensbasis über Symlinks; nur Checks nötig.",
    },
    {
        "id": "pipeline",
        "pfade": ("scripts/*", ".github/workflows/*"),
        "zellen": ("alle", "dist"),
        "befehl": "python3 scripts/propagate.py --all && python3 -m pytest -q",
        "hinweis": "Pipelineänderung: kompletter Durchlauf und Tests.",
    },
)


def treffer(pfad: str) -> list[dict[str, object]]:
    pfad = pfad.replace("\\", "/").lstrip("./")
    return [regel for regel in REGELN if any(fnmatch(pfad, muster) for muster in regel["pfade"])]


def zellen(pfade: list[str]) -> list[str]:
    gefunden: list[str] = []
    for pfad in pfade:
        for regel in treffer(pfad):
            for zelle in regel["zellen"]:
                if zelle not in gefunden:
                    gefunden.append(zelle)
    return gefunden
