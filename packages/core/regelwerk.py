"""regelwerk.py -- Zugriff auf das eine Regelwerk-Artefakt.

Das Artefakt ``knowledge/regelwerk.json`` fuehrt die drei Wissensschichten
zusammen:

* ``mdg``           -- was gebaut werden darf (Stereotype, Konnektoren,
                       Werkzeugkasten je Sicht)
* ``leitfaeden``    -- was verlangt wird (FFfmLV und PBN, je Konvention)
* ``model_wizard``  -- wie eine Sicht als Muster aussieht

Jede Aussage traegt ihre Herkunft. Wer eine Sicht bauen oder pruefen will,
fragt hier -- nicht bei den Einzelquellen. Damit gibt es genau einen Ort, an
dem die Vorgaben zusammenlaufen.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent


def finde() -> Path:
    """Das Artefakt suchen -- im Repo, im Bundle, neben dem Paket.

    Drei Lagen, in dieser Reihenfolge: ausdruecklicher Pfad (Umgebungsvariable),
    Repo-Wurzel ueber dem Paket, mitgeliefertes ``knowledge/`` neben dem Paket.
    Fehlt es ueberall, ist das ein Fehler und keine stille Rueckgabe.
    """
    aus_umgebung = os.environ.get("EAM_REGELWERK")
    kandidaten = [
        Path(aus_umgebung) if aus_umgebung else None,
        HIER.parents[1] / "knowledge" / "regelwerk.json",
        HIER.parent / "knowledge" / "regelwerk.json",
        HIER / "knowledge" / "regelwerk.json",
    ]
    for kandidat in kandidaten:
        if kandidat is not None and kandidat.is_file():
            return kandidat
    gesucht = ", ".join(str(p) for p in kandidaten if p is not None)
    raise FileNotFoundError(
        "knowledge/regelwerk.json nicht gefunden -- scripts/build_regelwerk.py laufen lassen "
        f"(gesucht: {gesucht})"
    )


@lru_cache(maxsize=4)
def lade(pfad: str | Path | None = None) -> dict[str, Any]:
    """Das Artefakt als dict. Fehlt die Datei, ist das ein Fehler."""
    ziel = Path(pfad) if pfad else finde()
    return json.loads(ziel.read_text(encoding="utf-8"))


def viewpoint(code: str, daten: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ein Viewpoint-Eintrag oder ``None``."""
    return (daten or lade())["viewpoints"].get(code)


def codes(daten: dict[str, Any] | None = None) -> list[str]:
    return sorted((daten or lade())["viewpoints"])


def sichten(daten: dict[str, Any] | None = None) -> list[str]:
    """Alle Viewpoints, die mindestens ein Leitfaden verlangt."""
    alle = (daten or lade())["viewpoints"]
    return sorted(
        code
        for code, eintrag in alle.items()
        if eintrag["leitfaeden"]["ffmlv"]["konventionen"]
        or eintrag["leitfaeden"]["pbn"]["konventionen"]
    )


def nur_wizard(daten: dict[str, Any] | None = None) -> list[str]:
    """Viewpoints, die nur der Model Wizard kennt -- keine Leitfadenvorgabe."""
    alle = (daten or lade())["viewpoints"]
    return sorted(
        code
        for code, eintrag in alle.items()
        if eintrag["model_wizard"]
        and "ffmlv" in eintrag["luecken"]
        and "pbn" in eintrag["luecken"]
    )


def stereotype(code: str, daten: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    """(erlaubt laut MDG, gefordert laut Model Wizard) fuer einen Viewpoint."""
    eintrag = viewpoint(code, daten)
    if eintrag is None:
        return [], []
    erlaubt = list(eintrag["mdg"]["elemente"])
    gefordert = list(eintrag["model_wizard"]["elemente"]) if eintrag["model_wizard"] else []
    return erlaubt, gefordert


def konflikte(daten: dict[str, Any] | None = None) -> list[dict[str, str]]:
    return list((daten or lade())["konflikte"])


def kennzahlen(daten: dict[str, Any] | None = None) -> dict[str, int]:
    return dict((daten or lade())["summary"])
