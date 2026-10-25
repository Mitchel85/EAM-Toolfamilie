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
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CORE = ROOT / "packages" / "core"
RULES = ROOT / "packages" / "rules"
SCRIPTS = ROOT / "scripts"

for pfad in (SCRIPTS, RULES, CORE):
    if pfad.is_dir() and str(pfad) not in sys.path:
        sys.path.insert(0, str(pfad))

FIXTURES = CORE / "fixtures"
if FIXTURES.is_dir():
    os.environ.setdefault("EAM_FIXTURE_STORE", str(FIXTURES))


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
