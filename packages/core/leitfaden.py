"""leitfaden.py -- Modellierungskonventionen des Leitfadens als Regelmodell.

Quelle
------
``Leitfaden Architekturen für FFFmLV``, Version 2.0 vom 17.04.2026
(BMVg, öffentlich). Der Leitfaden ist gegenüber der MDG die *methodische*
Vorgabe: Er bestimmt Paketstruktur, Diagrammtypen, Namen und Pflichtinhalte.
Die MDG bestimmt, welche Stereotype und Kanten es überhaupt gibt.

Was hier steht
--------------
Nur was sich aus dem Leitfaden **wörtlich** belegen lässt:

* ``PACKAGES`` -- Paketpfade aus den Konventionen ``xx-MK01`` (und den
  weiteren "Es ist ein Package ... angelegt"-Konventionen). ``{projekt}``
  wird zum Projektkürzel.
* ``DIAGRAMS`` -- Diagrammtyp und -name aus den Konventionen "Für die
  Darstellung ... ist ein Diagramm vom Typ ... angelegt".
* ``VIEWPOINT_FAMILY`` -- die sechs Perspektiven der Abbildung 1
  (Architecture Foundation, Concepts, Logical Specifications, Service
  Specifications, Physical Resource Specifications, Requirements).
* ``STARTSEITE`` -- St-/VÜ-Konventionen der Startseite.

Bewusst *nicht* erfunden: Projektinhalte. Dieses Modul beschreibt nur die
Form, die eine FFFmLV-konforme Architektur haben muss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

#: Titel und Stand des Regelwerks, gegen das geprüft wird.
LEITFADEN_TITEL = "Leitfaden Architekturen für FFFmLV"
LEITFADEN_VERSION = "2.0"
LEITFADEN_STAND = "17.04.2026"
LEITFADEN_MDG_VERSION = "2025.11"


#: Pflichtstereotype je Viewpoint.
#:
#: Schnittmenge aus zwei belegten Quellen:
#:   * der Leitfaden nennt den Stereotyp in einer ``xx-MK``-Konvention, und
#:   * die Model-Wizard-Vorlage des Viewpoints zeigt ihn.
#: Was nur in der Vorlage steht (MASC-Beispielinhalte wie "Project" in A1),
#: ist bewusst nicht enthalten -- sonst wuerde der Bau Beispielinhalte
#: nachbilden, die fuer ein anderes Projekt nicht gelten.
@dataclass(frozen=True)
class PackageRule:
    """Ein verlangtes Paket: Konvention, Pfad, Viewpoint, Perspektive."""

    code: str
    path: str
    viewpoint: str = ""
    family: str = ""


@dataclass(frozen=True)
class DiagramRule:
    """Eine verlangte Sicht: Konvention, Typ, Name, Paket."""

    code: str
    viewpoint: str
    diagram_type: str
    name: str
    package: str


#: Perspektiven der übergreifenden Paketstruktur (Leitfaden Abbildung 1).
VIEWPOINT_FAMILY: tuple[str, ...] = (
    "Architecture Foundation",
    "Concepts",
    "Logical Specifications",
    "Service Specifications",
    "Physical Resource Specifications",
    "Requirements",
)

#: EA-Diagrammtyp je Viewpoint-Familie. Der Leitfaden verlangt die
#: MDG-Viewpoint-Stereotype (``MDGDgm``); der EA-Grundtyp ist bei ADMBw
#: durchgaengig ``Custom`` -- so stehen alle 265 Sichten der Musterarchitektur.
DIAGRAM_EA_TYPE = "Custom"

#: Zusätzliche Perspektivpakete, die der Leitfaden nennt (R8, Rr sind in
#: Abbildung 1 sichtbar, im Fließtext ohne eigene MK-Konvention). Aufgenommen,
#: weil die Abbildung sie zeigt -- als Hinweis, nicht als Pflicht.
HINWEIS_PACKAGES: tuple[str, ...] = (
    "Requirements/R8",
    "Requirements/Rr",
    "Modellelementekatalog",
)

PFLICHT_STEREOTYPE: dict[str, tuple[str, ...]] = {}
PACKAGES: tuple[PackageRule, ...] = ()
DIAGRAMS: tuple[DiagramRule, ...] = ()


def _lade_regeln() -> tuple[dict[str, tuple[str, ...]], tuple[PackageRule, ...], tuple[DiagramRule, ...]]:
    """Die drei Tabellen aus dem Regelwerk-Artefakt.

    Sie stehen in ``knowledge/regelwerk.json`` (Abschnitt ``pruefung``) und
    werden von ``scripts/build_regelwerk.py`` aus
    ``knowledge/leitfaden/pruefung.json`` gebaut. Damit gibt es genau eine
    Quelle -- nicht eine im Code und eine daneben.
    """
    import regelwerk  # gleiche Ebene, kein Zyklus: regelwerk liest nur JSON

    pruefung = regelwerk.lade()["pruefung"]
    pflicht = {code: tuple(werte) for code, werte in pruefung["pflicht"].items()}
    pakete = tuple(PackageRule(**eintrag) for eintrag in pruefung["packages"])
    sichten = tuple(DiagramRule(**eintrag) for eintrag in pruefung["diagrams"])
    return pflicht, pakete, sichten


PFLICHT_STEREOTYPE, PACKAGES, DIAGRAMS = _lade_regeln()



def expand_projekt(text: str, projekt: str) -> str:
    """``{projekt}`` durch das Projektkürzel ersetzen (kein Leerzeichen erlaubt)."""
    return text.replace("{projekt}", projekt)


def package_paths(projekt: str) -> dict[str, str]:
    """Konventions-ID -> ausgeschriebener Paketpfad."""
    return {rule.code: expand_projekt(rule.path, projekt) for rule in PACKAGES}


def required_packages(projekt: str) -> tuple[str, ...]:
    """Alle vom Leitfaden verlangten Paketpfade, ohne Doppelungen, in Reihenfolge."""
    seen: list[str] = []
    for path in package_paths(projekt).values():
        if path not in seen:
            seen.append(path)
    return tuple(seen)


def required_diagrams(projekt: str) -> tuple[dict[str, str], ...]:
    """Vom Leitfaden verlangte Diagramme: Name, Typ, Paket, Konvention."""
    out: list[dict[str, str]] = []
    for rule in DIAGRAMS:
        out.append(
            {
                "code": rule.code,
                "viewpoint": rule.viewpoint,
                "type": rule.diagram_type,
                "name": expand_projekt(rule.name, projekt),
                "package": expand_projekt(rule.package, projekt),
            }
        )
    return tuple(out)


def normiere(text: str) -> str:
    """Vergleichsform für Paketnamen: Groß-/Kleinschreibung und Mehrfach-Leerzeichen egal.

    Der Leitfaden schreibt denselben Pfad mal "Architecture Foundation", mal
    "Architectural Foundation", mal mit zusätzlichem Leerzeichen. Ein Prüfer,
    der auf das letzte Leerzeichen achtet, meldet Fehler, die keine sind.
    """
    return re.sub(r"\s+", " ", text).strip().casefold()


def konventionen() -> list[dict[str, Any]]:
    """Alle Konventionen aus ``knowledge/leitfaden/konventionen.json``, roh."""
    from pathlib import Path
    import json

    for candidate in (
        Path(__file__).resolve().parent.parent.parent / "knowledge" / "leitfaden" / "konventionen.json",
        Path(__file__).resolve().parent / "knowledge" / "leitfaden" / "konventionen.json",
    ):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return []
