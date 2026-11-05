"""Eine Quelle für den aktuellen MDG-Stand.

Der Dateiname der Technologie-Datei steht genau einmal im Repository: in
``packages/rules/CURRENT``. Parser, Build, Tests und CI lesen ihn dort.

Der Grund ist praktisch: die MDG wird laufend fortgeschrieben — Stereotype,
Regeln, Viewpoints und Tag-Typen kommen hinzu oder fallen weg. Vorher stand der
Dateiname an über fünfzig Stellen; jede neue Fassung war ein Suchen-und-Ersetzen
mit dem Risiko, eine Stelle zu übersehen, die danach still die alte Datei prüft.

Neuer MDG-Stand ist damit:

1. XML nach ``packages/rules/`` legen,
2. ``packages/rules/CURRENT`` auf den neuen Dateinamen setzen,
3. neue Baseline ``packages/rules/schemas/baseline-mdg-<release>.json`` schreiben.

Aufruf im Code::

    import mdg_source
    mdg_source.path()           # Pfad zur aktuellen XML
    mdg_source.name()           # Dateiname
    mdg_source.release()        # "2026.05"
    mdg_source.baseline()       # dict der Baseline oder {}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RULES = Path(__file__).resolve().parent
CURRENT = RULES / "CURRENT"
SCHEMAS = RULES / "schemas"

#: Release-Muster im Dateinamen, z. B. ``NAFv4-ADMBw-MDG-2026.05.xml``.
_RELEASE = re.compile(r"-(\d{4}\.\d{2})\.xml$", re.IGNORECASE)


def name() -> str:
    """Dateiname der aktuellen MDG. Erste nicht-leere Zeile aus ``CURRENT``."""
    if not CURRENT.is_file():
        raise FileNotFoundError(f"{CURRENT} fehlt — Dateiname der MDG unbekannt")
    for zeile in CURRENT.read_text(encoding="utf-8").splitlines():
        zeile = zeile.split("#", 1)[0].strip()
        if zeile:
            return zeile
    raise RuntimeError(f"{CURRENT} nennt keine MDG-Datei")


def path() -> Path:
    """Pfad zur aktuellen MDG-XML."""
    return RULES / name()


def release() -> str:
    """Release-Kennung aus dem Dateinamen, z. B. ``2026.05``.

    Fällt auf ``unbekannt`` zurück, wenn der Dateiname dem Muster nicht folgt —
    dann fehlt nur die Baseline, der Lauf selbst bleibt möglich.
    """
    treffer = _RELEASE.search(name())
    return treffer.group(1) if treffer else "unbekannt"


def baseline_path() -> Path:
    """Pfad zur Baseline des aktuellen Release."""
    return SCHEMAS / f"baseline-mdg-{release()}.json"


def baseline() -> dict:
    """Inhalt der Baseline oder ``{}``, wenn keine hinterlegt ist."""
    pfad = baseline_path()
    if not pfad.is_file():
        return {}
    return json.loads(pfad.read_text(encoding="utf-8"))


def counts() -> dict:
    """Erwartete Zählwerte des aktuellen Release (leer, wenn keine Baseline)."""
    return dict(baseline().get("counts", {}))


def fingerprints() -> dict:
    """Erwartete Fingerprints des aktuellen Release (leer, wenn keine Baseline)."""
    return dict(baseline().get("fingerprints", {}))


if __name__ == "__main__":  # pragma: no cover - kleine Selbstauskunft
    print(f"Datei:      {name()}")
    print(f"Pfad:       {path()}")
    print(f"Release:    {release()}")
    print(f"Baseline:   {baseline_path()} ({'vorhanden' if baseline() else 'fehlt'})")
    for schluessel, wert in counts().items():
        print(f"  {schluessel}: {wert}")
