"""Macht Kern, Parser, Skripte und Tests im Monorepo importierbar.

Das Monorepo setzt keine Installation voraus: der Kern ist stdlib-only und wird
direkt aus ``packages/`` importiert. Damit die umgezogenen Tests ohne Anpassung
laufen, steht hier derselbe Suchpfad bereit, den das Alt-Repo über seine eigene
Wurzel hatte.

Wichtig für die Fixtures: der Kern sucht sie relativ zu seiner eigenen Wurzel
(``packages/core/fixtures``) und über ``EAM_FIXTURE_STORE``. Beides wird hier
gesetzt, damit die Tests nicht an einem Umzugspfad scheitern.
"""

from __future__ import annotations

import os
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CORE = ROOT / "packages" / "core"
RULES = ROOT / "packages" / "rules"
SCRIPTS = ROOT / "scripts"

for pfad in (SCRIPTS, RULES, CORE):
    if pfad.is_dir() and str(pfad) not in sys.path:
        sys.path.insert(0, str(pfad))

# Der Dateiname der MDG steht genau einmal im Repo (packages/rules/CURRENT).
# Tests fragen ihn hier ab, statt ihn zu wiederholen.
from mdg_source import name as mdg_name, path as mdg_pfad  # noqa: E402

FIXTURES = CORE / "fixtures"
if FIXTURES.is_dir():
    os.environ.setdefault("EAM_FIXTURE_STORE", str(FIXTURES))
    # Die MCP-Tests lesen einen eigenen Namen (MASC_QEA_PATH). Ohne diese Zeile
    # werden sie immer uebersprungen, auch wenn die Musterarchitektur vorliegt.
    _masc = FIXTURES / "Musterarchitektur_MASC.qea"
    if _masc.is_file():
        os.environ.setdefault("MASC_QEA_PATH", str(_masc))


def vorhanden(pfad: object) -> bool:
    """Prueft eine Datei, ohne bei fehlenden Rechten abzubrechen.

    Gleichlautend mit dem Alt-Repo, damit umgezogene Tests unveraendert laufen.
    """
    try:
        return Path(str(pfad)).is_file()
    except OSError:
        return False


def fixture_pfad(name: str, *alternativen: object) -> Path:
    """Sucht eine Fixture: Store, Repo-Fixtures, dann bekannte Altpfade."""
    kandidaten: list[Path] = []
    store = os.environ.get("EAM_FIXTURE_STORE")
    if store:
        kandidaten.append(Path(store) / name)
    kandidaten.append(FIXTURES / name)
    kandidaten.extend(Path(str(a)) for a in alternativen)
    for kandidat in kandidaten:
        if vorhanden(kandidat):
            return kandidat
    return FIXTURES / name


# --------------------------------------------------------------------------
# Fixture-Sperre: die grosse Referenzarchitektur liegt nicht im Repository
# (siehe `.gitignore` und `packages/core/ci/fixtures_manifest.json`). Ohne sie
# wären die Prüfläufe in der CI rot, obwohl nichts kaputt ist — sie werden
# darum sichtbar übersprungen, nicht still.
# --------------------------------------------------------------------------

MASC = Path(os.environ.get("EAM_FIXTURE_STORE") or FIXTURES) / "Musterarchitektur_MASC.qea"

#: Tests, deren Prüfläufe das echte Referenzmodell brauchen.
BRAUCHT_MASC = frozenset(
    {
        "test_masc_golden",
        "test_model_merge",
        "test_toolbox_merge",
        "test_prosa_import",
        "test_aaron_compat",
        "test_handbuch_generator",
        "test_roundtrip_metrics",
        "test_roundtrip_export",
    }
)


def pytest_collection_modifyitems(config, items):
    """Überspringt MASC-Prüfläufe, wenn die Fixture fehlt."""
    if MASC.is_file():
        return
    marker = pytest.mark.skip(
        reason=(
            "Fixture Musterarchitektur_MASC.qea fehlt — nicht im Repo, "
            "kommt aus dem internen Fixture-Store (EAM_FIXTURE_STORE)"
        )
    )
    for item in items:
        modul = getattr(item, "module", None)
        if modul is not None and getattr(modul, "__name__", "").split(".")[-1] in BRAUCHT_MASC:
            item.add_marker(marker)
