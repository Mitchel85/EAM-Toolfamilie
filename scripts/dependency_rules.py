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
            "dist",
        ),
        "befehl": "python3 scripts/propagate.py --all",
        "hinweis": "MDG/Reader geändert: Wissensbasis neu erzeugen, Downstream prüfen.",
    },
    {
        "id": "wissensbasis",
        "pfade": ("knowledge/*",),
        "zellen": ("apps/admbw-extractor",),
        "befehl": "python3 scripts/propagate.py --write && python3 -m pytest -q tests/apps",
        "hinweis": "Die App liest die Wissensbasis über Symlinks; keine Kopie nötig.",
    },
    {
        "id": "vendor",
        "pfade": ("vendor/*",),
        "zellen": (
            "apps/html-suite",
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
        "id": "html-editor",
        "pfade": ("apps/html-editor/*",),
        "zellen": ("apps/html-editor", "dist"),
        "befehl": "python3 scripts/build_legacy_app.py apps/html-editor && python3 scripts/propagate.py --release",
        "hinweis": "Eigenständiger Altstand: nur diese App und ihr Release-Asset ändern sich.",
    },
    {
        "id": "admbw-extractor-html",
        "pfade": ("apps/admbw-extractor/html/*",),
        "zellen": ("apps/admbw-extractor/html", "dist"),
        "befehl": "python3 apps/admbw-extractor/html/build.py && python3 scripts/propagate.py --release",
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
        "id": "admbw-extractor",
        "pfade": ("apps/admbw-extractor/*",),
        "zellen": ("apps/admbw-extractor",),
        "befehl": "python3 scripts/propagate.py --check && python3 apps/admbw-extractor/checks/verify.py",
        "hinweis": "Der Extractor liest die Wissensbasis über Symlinks; nur Checks nötig.",
    },
    {
        "id": "formate",
        "pfade": (
            "packages/core/xmi_reader.py",
            "packages/core/xmi_writer.py",
            "packages/core/json_batch.py",
        ),
        "zellen": ("apps/cli", "apps/mcp", "dist"),
        "befehl": "python3 -m pytest -q tests/core/test_xmi_format.py tests/core/test_json_batch.py && python3 scripts/propagate.py --build",
        "hinweis": "Format-Module (xmi/json): Roundtrip-Tests, dann Neu-Bau der Auslieferungen.",
    },
    {
        "id": "bpmn",
        "pfade": (
            "packages/bpmn/*",
            "apps/bpmn-studio/*",
        ),
        "zellen": ("apps/bpmn-studio", "dist"),
        "befehl": "python3 scripts/propagate.py --check && python3 -m pytest -q tests/",
        "hinweis": "BPMN-Regeln oder -Studio geändert: Prüflauf, ggf. Neu-Bau der HTML.",
    },
    {
        "id": "rules-strahlkraft",
        "pfade": ("packages/rules/*",),
        "zellen": (
            "knowledge",
            "apps/admbw-extractor",
            "apps/cli",
            "apps/mcp",
            "apps/html-suite",
            "apps/html-editor",
            "apps/admbw-extractor/html",
            "dist",
        ),
        "befehl": "python3 scripts/propagate.py --all && python3 -m pytest -q",
        "hinweis": "Regelwerk geändert: Strahlkraft in ALLE Funktionen — Wissensbasis, Apps, CLI, MCP, Auslieferungen.",
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
