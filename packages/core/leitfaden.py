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

#: Perspektiven der übergreifenden Paketstruktur (Leitfaden Abbildung 1).
VIEWPOINT_FAMILY: tuple[str, ...] = (
    "Architecture Foundation",
    "Concepts",
    "Logical Specifications",
    "Service Specifications",
    "Physical Resource Specifications",
    "Requirements",
)


@dataclass(frozen=True)
class PackageRule:
    """Ein Paket, das der Leitfaden verlangt."""

    code: str                      # Konventions-ID, z. B. "A1-MK01"
    path: str                      # "Architecture Foundation/A1/Meta-Data Definitions"
    viewpoint: str                 # "A1"
    family: str                    # "Architecture Foundation"

    @property
    def rendered(self) -> str:
        return self.path.replace("{projekt}", "{projekt}")


@dataclass(frozen=True)
class DiagramRule:
    """Ein Diagramm, das der Leitfaden verlangt."""

    code: str                      # "A1-MK02"
    viewpoint: str                 # "A1"
    diagram_type: str              # MDG-Viewpoint-Name, z. B. "A1 - Meta-Data Definitions"
    name: str                      # "A1 : {projekt} : Meta-Data Definitions"
    package: str                   # Paketpfad (mit {projekt})

    @property
    def rendered_name(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Pakete -- wörtlich aus den "Es ist ein Package ... angelegt"-Konventionen.
# Reihenfolge: Leitfaden. Schreibweisen wie "Architecture Foundation" (ohne
# "al") und "Ressource Specifications" werden NICHT korrigiert: der Leitfaden
# ist an dieser Stelle selbst inkonsistent, die Konvention gilt wörtlich.
# ---------------------------------------------------------------------------

PACKAGES: tuple[PackageRule, ...] = (
    PackageRule("St-MK01", "{projekt} - Startseite", "St", ""),
    PackageRule("A1-MK01", "Architecture Foundation/A1/Meta-Data Definitions", "A1", "Architecture Foundation"),
    PackageRule("A2-MK01", "Architecture Foundation/A2 - Stakeholder", "A2", "Architecture Foundation"),
    PackageRule("A2-MK08", "Architecture Foundation/A2/Concerns", "A2", "Architecture Foundation"),
    PackageRule("A2-MK15", "Architecture Foundation/A2/Viewpoints", "A2", "Architecture Foundation"),
    PackageRule("A3-MK01", "Architecture Foundation/A3/Architecture Correspondence", "A3", "Architecture Foundation"),
    PackageRule("A6-MK01", "Architecture Foundation/A6/Architecture Version", "A6", "Architecture Foundation"),
    PackageRule("A7-MK01", "Architecture Foundation/A7/Architecture Compliance", "A7", "Architecture Foundation"),
    PackageRule("A7-MK07", "Architecture Foundation/A7/Findings and Recommendations", "A7", "Architecture Foundation"),
    PackageRule("A7-MK17", "Architecture Foundation/A7/Compliance Statement", "A7", "Architecture Foundation"),
    PackageRule("A8-MK01", "Architecture Foundation/A8/Standards", "A8", "Architecture Foundation"),
    PackageRule("Ar-MK01", "Architecture Foundation/Ar/Architecture Roadmap", "Ar", "Architecture Foundation"),
    PackageRule("C1-MK01", "Concepts/C1/Capability Taxonomy", "C1", "Concepts"),
    PackageRule("C8-MK01", "Concepts/C8/Planning Assumptions", "C8", "Concepts"),
    PackageRule("Cr-MK01", "Concepts/Cr/Capability Roadmap", "Cr", "Concepts"),
    PackageRule("L1-MK01", "Logical Specifications/L1/Node Types", "L1", "Logical Specifications"),
    PackageRule("L2-MK01", "Logical Specifications/L2/Logical Nodes", "L2", "Logical Specifications"),
    PackageRule("L2-MK05", "Logical Specifications/L2/Logical Scenario", "L2", "Logical Specifications"),
    PackageRule("L3-MK01", "Logical Specifications/L3/Node Interaction", "L3", "Logical Specifications"),
    PackageRule("L4-MK01", "Logical Specifications/L4/Logical Activities", "L4", "Logical Specifications"),
    PackageRule("L7-MK01", "Logical Specifications/L7/Information Model", "L7", "Logical Specifications"),
    PackageRule("L8-MK01", "Logical Specifications/L8/Logical Constraints", "L8", "Logical Specifications"),
    PackageRule("S1-MK01", "Service Specifications/S1/Charakterisierung - Service Description", "S1", "Service Specifications"),
    PackageRule("S1-MK12", "Service Specifications/S1/IT-Service Varianten", "S1", "Service Specifications"),
    PackageRule("S2-MK01", "Service Specifications/S2/IT-Service Komposition", "S2", "Service Specifications"),
    PackageRule("S2-MK05", "Service Specifications/S2/Serviceabhängigkeiten", "S2", "Service Specifications"),
    PackageRule("S2-MK10", "Service Specifications/S2/Warranties", "S2", "Service Specifications"),
    PackageRule("S3-MK01", "Service Specifications/S3/Logische Kontextsicht", "S3", "Service Specifications"),
    PackageRule("S4-MK01", "Service Specifications/S4/Servicefunktion", "S4", "Service Specifications"),
    PackageRule("S7-MK01", "Service Specifications/S7/Serviceinterface", "S7", "Service Specifications"),
    PackageRule("Sr-MK01", "Service Specifications/Sr/Service Change", "Sr", "Service Specifications"),
    PackageRule("P1-MK01", "Physical Resource Specifications/P1/Resource Types", "P1", "Physical Resource Specifications"),
    PackageRule("P1-MK07", "Physical Resource Specifications/P1/Service Provision", "P1", "Physical Resource Specifications"),
    PackageRule("P2-MK01", "Physical Resource Specifications/P2/Resource Structure", "P2", "Physical Resource Specifications"),
    PackageRule("P2-MK07", "Physical Resource Specifications/P2/Internal Dependencies", "P2", "Physical Resource Specifications"),
    PackageRule("P2-MK12", "Physical Resource Specifications/P2/External Dependencies", "P2", "Physical Resource Specifications"),
    PackageRule("P2-MK20", "Physical Resource Specifications/P2/Node Realization", "P2", "Physical Resource Specifications"),
    PackageRule("P2-MK25", "Physical Resource Specifications/P2/Application Hosting", "P2", "Physical Resource Specifications"),
    PackageRule("P7-MK01", "Physical Resource Specifications/P7/Data Model", "P7", "Physical Resource Specifications"),
    PackageRule("P8-MK01", "Physical Resource Specifications/P8/Resource Constraint Realization", "P8", "Physical Resource Specifications"),
    PackageRule("R2-MK01", "Requirements/R2/Requirement Catalogue", "R2", "Requirements"),
    PackageRule("R3-MK01", "Requirements/R3/Requirement Dependencies", "R3", "Requirements"),
    PackageRule("R7-MK01", "Requirements/R7/Requirement Derivation", "R7", "Requirements"),
)

#: Zusätzliche Perspektivpakete, die der Leitfaden nennt (R8, Rr sind in
#: Abbildung 1 sichtbar, im Fließtext ohne eigene MK-Konvention). Aufgenommen,
#: weil die Abbildung sie zeigt -- als Hinweis, nicht als Pflicht.
HINWEIS_PACKAGES: tuple[str, ...] = (
    "Requirements/R8",
    "Requirements/Rr",
    "Modellelementekatalog",
)


# ---------------------------------------------------------------------------
# Diagramme -- wörtlich aus den "ist ein Diagramm vom Typ ... angelegt"-Regeln.
# Der Diagrammtyp ist der MDG-Viewpoint-Name; die Zuordnung zum EA-Diagrammtyp
# steht in DIAGRAM_EA_TYPE.
# ---------------------------------------------------------------------------

DIAGRAMS: tuple[DiagramRule, ...] = (
    DiagramRule("St-MK02", "St", "A2 - Architecture Products", "Startseite {projekt}", "{projekt} - Startseite"),
    DiagramRule("A1-MK02", "A1", "A1 - Meta-Data Definitions", "A1 : {projekt} : Meta-Data Definitions", "Architecture Foundation/A1/Meta-Data Definitions"),
    DiagramRule("A2-MK02", "A2", "A2 - Architecture Products", "A2 : {projekt} : Stakeholder", "Architecture Foundation/A2 - Stakeholder"),
    DiagramRule("A2-MK09", "A2", "A2 - Architecture Products", "A2 : {projekt} : Concerns", "Architecture Foundation/A2/Concerns"),
    DiagramRule("A2-MK16", "A2", "A2 - Architecture Products", "A2 : {projekt} : Viewpoints", "Architecture Foundation/A2/Viewpoints"),
    DiagramRule("A6-MK02", "A6", "A6 - Architecture Version", "A6 : {projekt} : Architecture Versions", "Architecture Foundation/A6/Architecture Version"),
    DiagramRule("A7-MK02", "A7", "A7 - Architecture Compliance", "A7 : {projekt} : Architecture Compliance", "Architecture Foundation/A7/Architecture Compliance"),
    DiagramRule("A7-MK08", "A7", "A7 - Architecture Compliance", "A7 : {projekt} : Findings and Recommendations", "Architecture Foundation/A7/Findings and Recommendations"),
    DiagramRule("A7-MK18", "A7", "A7 - Architecture Compliance", "A7 : {projekt} : Compliance Statement", "Architecture Foundation/A7/Compliance Statement"),
    DiagramRule("A8-MK02", "A8", "A8 - Standards", "A8 : {projekt} : Standards", "Architecture Foundation/A8/Standards"),
    DiagramRule("Ar-MK02", "Ar", "Ar - Architecture Roadmap", "Ar : {projekt} : Architecture Roadmap", "Architecture Foundation/Ar/Architecture Roadmap"),
    DiagramRule("C1-MK02", "C1", "C1 - Capability Taxonomy", "C1 : {projekt} : Funktionale Bausteine", "Concepts/C1/Capability Taxonomy"),
    DiagramRule("C1-MK04", "C1", "C1 - Capability Taxonomy", "C1 : {projekt} : NATO Capability Codes", "Concepts/C1/Capability Taxonomy"),
    DiagramRule("C1-MK06", "C1", "C1 - Capability Taxonomy", "C1 : {projekt} : Fähigkeitsforderungen", "Concepts/C1/Capability Taxonomy"),
    DiagramRule("C1-MK08", "C1", "C1 - Capability Taxonomy", "C1 : {projekt} : EU Priorities", "Concepts/C1/Capability Taxonomy"),
    DiagramRule("Cr-MK02", "Cr", "Cr - Capability Roadmap", "Cr : {projekt} : Capability Roadmap", "Concepts/Cr/Capability Roadmap"),
    DiagramRule("L1-MK02", "L1", "L1 - Node Types", "L1 : {projekt} : Node Types", "Logical Specifications/L1/Node Types"),
    DiagramRule("L2-MK02", "L2", "L2 - Logical Scenario", "L2 : {projekt} : Logical Nodes", "Logical Specifications/L2/Logical Nodes"),
    DiagramRule("L2-MK05", "L2", "L2 - Logical Scenario", "L2 : {projekt} : Logical Scenario", "Logical Specifications/L2/Logical Scenario"),
    DiagramRule("L3-MK02", "L3", "L3 - Node Interactions", "L3 : {projekt} : Node Interaction", "Logical Specifications/L3/Node Interaction"),
    DiagramRule("L4-MK02", "L4", "L4 - Logical Activities", "L4 : {projekt} : Hierarchie", "Logical Specifications/L4/Logical Activities"),
    DiagramRule("L7-MK02", "L7", "L7 - Information Model", "L7 : {projekt} : Information Model", "Logical Specifications/L7/Information Model"),
    DiagramRule("L8-MK02", "L8", "L8 - Logical Constraints", "L8 : {projekt} : Logical Constraints", "Logical Specifications/L8/Logical Constraints"),
    DiagramRule("S1-MK13", "S1", "S1 - Service Taxonomy", "S1 : {projekt} : Service Variants", "Service Specifications/S1/IT-Service Varianten"),
    DiagramRule("S2-MK06", "S2", "S2 - Service Structure", "S2 : {projekt} : External Service Dependencies", "Service Specifications/S2/Serviceabhängigkeiten"),
    DiagramRule("S2-MK11", "S2", "S2 - Service Structure", "S2 : {projekt} : Service Warranties", "Service Specifications/S2/Warranties"),
    DiagramRule("S3-MK02", "S3", "S3 - Service Interfaces", "S3 : {projekt} : Service Interfaces", "Service Specifications/S3/Logische Kontextsicht"),
    DiagramRule("S4-MK02", "S4", "S4 - Service Functions", "S4 : {projekt} : Service Functions", "Service Specifications/S4/Servicefunktion"),
    DiagramRule("S7-MK02", "S7", "S7 - Service Interface Parameters", "S7 : {projekt} : Service Interface Parameters", "Service Specifications/S7/Serviceinterface"),
    DiagramRule("Sr-MK02", "Sr", "Sr - Service Roadmap", "Sr : {projekt} : Service Change", "Service Specifications/Sr/Service Change"),
    DiagramRule("P1-MK02", "P1", "P1 - Resource Types", "P1 : {projekt} : Resource Types", "Physical Resource Specifications/P1/Resource Types"),
    DiagramRule("P1-MK08", "P1", "P1 - Resource Types", "P1 : {projekt} : Service Provision", "Physical Resource Specifications/P1/Service Provision"),
    DiagramRule("P2-MK02", "P2", "P2 - Resource Structure", "P2 : {projekt} : Resource Structure", "Physical Resource Specifications/P2/Resource Structure"),
    DiagramRule("P2-MK08", "P2", "P2 - Resource Structure", "P2 : {projekt} : Internal Dependencies", "Physical Resource Specifications/P2/Internal Dependencies"),
    DiagramRule("P2-MK13", "P2", "P2 - Resource Structure", "P2 : {projekt} : External Dependencies", "Physical Resource Specifications/P2/External Dependencies"),
    DiagramRule("P2-MK21", "P2", "P2 - Resource Structure", "P2 : {projekt} : Node Realization", "Physical Resource Specifications/P2/Node Realization"),
    DiagramRule("P2-MK26", "P2", "P2 - Resource Structure", "P2 : {projekt} : Application Hosting", "Physical Resource Specifications/P2/Application Hosting"),
    DiagramRule("P8-MK02", "P8", "P8 - Resource Constraints", "P8 : {projekt} : Resource Constraint", "Physical Resource Specifications/P8/Resource Constraint Realization"),
    DiagramRule("R2-MK02", "R2", "R2 - Requirement Catalogue", "R2 : {projekt} : Requirement Catalogue", "Requirements/R2/Requirement Catalogue"),
    DiagramRule("R3-MK02", "R3", "R3 - Requirement Dependencies", "R3 : {projekt} : Requirements Dependencies", "Requirements/R3/Requirement Dependencies"),
    DiagramRule("R7-MK02", "R7", "R7 - Requirement Derivation", "R7 : {projekt} : Requirements Derivation", "Requirements/R7/Requirement Derivation"),
)

#: Schreibweisen, die der Leitfaden selbst abweichend verwendet (L3 "Node
#: Interaction" im Fließtext, "Node Interactions" in der MDG). Übernommen wird
#: die MDG-Schreibweise, weil der Diagrammtyp aus der Technologie kommen muss.

#: EA-Diagrammtyp je Viewpoint-Familie. Der Leitfaden verlangt die
#: MDG-Viewpoint-Stereotype (``MDGDgm``); der EA-Grundtyp ist bei ADMBw
#: durchgaengig ``Custom`` -- so stehen alle 265 Sichten der Musterarchitektur.
DIAGRAM_EA_TYPE = "Custom"


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
