"""Stellt sicher, dass die Repo-Wurzel importierbar ist (qea_writer, spaeter qea_reader)."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def vorhanden(pfad: object) -> bool:
    """Prueft eine Datei, ohne bei fehlenden Rechten abzubrechen.

    Ein Test darf nicht daran scheitern, dass ein Entwicklerpfad existiert,
    aber fuer den CI-Benutzer nicht lesbar ist. Fehlende Rechte zaehlen wie
    "nicht vorhanden"; der Test wird dann uebersprungen.
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
    kandidaten.append(ROOT / "fixtures" / name)
    kandidaten.extend(Path(str(a)) for a in alternativen)
    for kandidat in kandidaten:
        if vorhanden(kandidat):
            return kandidat
    return ROOT / "fixtures" / name
