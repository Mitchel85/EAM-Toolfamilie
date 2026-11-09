"""archimate_writer.py -- IR -> ArchiMate 3.2 Model Exchange XML.

Bestimmung
----------
Nimmt das IR aus ``qea_reader`` (``with_refs=True, with_owners=True``) und
schreibt eine Datei nach dem Open-Group-Format ``archimate3_Model.xsd``.
Damit ist ArchiMate ein viertes Ausgabeformat neben ``.qea``, ``.xmi`` und
``.json`` -- dieselbe Quelle, dasselbe Governance-Gate, anderes Ziel.

Kernentscheidungen (alle deterministisch)
-----------------------------------------
- **Keine 1:1-Uebersetzung.** Der NAFv4.1-ArchiMate-Guide (2026.06) sagt
  ausdruecklich, dass NAF-Elemente auf *mehrere* ArchiMate-Typen zeigen. Das
  Mapping hier ist eine Ingenieursentscheidung und steht als Tabelle im Modul,
  nicht versteckt im Code. Elemente ohne Stereotyp fallen sichtbar auf
  ``Grouping``/``Requirement`` zurueck und werden gezaehlt.
- **Schicht bleibt eine Modellfrage (offen).** Der Guide fuehrt Dienst,
  Funktion und Schnittstelle je einmal pro Schicht (Business/Application/
  Technology). ADMBw traegt die Schicht nicht im Stereotyp, sondern nur im
  Paketpfad; der Writer waehlt daher je Begriff eine dokumentierte
  Default-Schicht (Application) und behauptet keine Schicht, die das IR nicht
  liefert. Sobald das IR die Schicht mitbringt, ist ``ELEMENT_MAP`` der Ort der
  Erweiterung -- nicht der Code.
- **Ports, Parts, Pins haben kein ArchiMate-Konzept.** Kanten daran werden auf
  das Traegerelement gezogen (IR-Feld ``owner``). Ohne diese Aufloesung
  verliert MASC rund 200 Kanten.
- **Beziehungen werden gegen die ArchiMate-Matrix geprueft.** Quelle ist
  ``archimate/relationships.xml`` aus Archi (EPL-2.0). Ist eine Kante nur in
  Gegenrichtung legal, wird sie invertiert und als ``inverted`` gezaehlt
  (z. B. ``ViewsInArchitecturalDescription``: das Produkt enthaelt die Sicht,
  nicht umgekehrt). Sonst wird sie auf die semantisch naechste legale Relation
  umgebaut (``FALLBACK_PRAEFERENZ``) und je ``(von, nach, Quelltyp, Zieltyp)``
  gezaehlt -- nicht stillschweigend umgedeutet.
- **Jede Naeherung ist im Report sichtbar.** Selbstkanten, Duplikate,
  NoteLinks, nicht abgebildete Pakete, getrennt gezaehlte Darstellungs- und
  Fachtyp-Elemente, der Schicht-Ersatz ``Zustand/Ereignis -> BusinessEvent``
  und nicht zuordenbare Elemente haben eigene Zaehler. Es gibt keinen stillen
  Verlust mehr (Audit T2, Abschnitt 4).
- **Keine Zeitstempel, keine Zufallswerte.** Kennung ist die IR-GUID (sonst
  SHA-256 aus Paketpfad|Stereotyp|Name). Zwei Laeufe -> gleiche Bytes.
- **Laut statt still:** ungueltiges IR bricht mit ``ArchimateWriterError`` ab.

Oeffentliche API::

    from archimate_writer import render_bytes, write_archimate, ArchimateReport

    daten = render_bytes(ir)                 # bytes
    report = write_archimate(ir, "modell.xml")
"""

from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, NoReturn, Sequence
from xml.dom import minidom

NS = "http://www.opengroup.org/xsd/archimate/3.0/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
IR_VERSION = 1

MATRIX_DIR = Path(__file__).resolve().parent / "archimate"


class ArchimateWriterError(ValueError):
    """IR oder Zielformat nicht darstellbar -- Abbruch statt Teil-Erfolg."""


# --------------------------------------------------------------------------
# Mapping ADMBw/NAF -> ArchiMate 3.2
# --------------------------------------------------------------------------
ELEMENT_MAP: Mapping[str, str] = {
    # Strategie / Konzepte
    "Capability": "Capability",
    "FieldedCapability": "Capability",
    "CapabilityConfiguration": "Grouping",
    "CapabilityRole": "BusinessRole",
    "EnterpriseGoal": "Goal",
    # Guide C2/C8 erlaubt Driver und Goal; Goal bleibt die belegte Wahl.
    "EnterpriseVision": "Goal",
    "HighLevelOperationalConcept": "BusinessObject",
    # Audit T2 (C2 §6.2): Enduring Task wird als Capability modelliert.
    "EnduringTask": "Capability",
    "ActualEnduringTask": "Capability",
    # Audit T2, Nr. 5 (C8/L8/P8/S8/A8): Constraint-Stereotype sind Requirements.
    "StrategicConstraint": "Requirement",
    "OperationalConstraint": "Requirement",
    "ResourceConstraint": "Requirement",
    "Constraint": "Requirement",
    "ServicePolicy": "Requirement",
    "Principle": "Principle",
    "Driver": "Driver",
    "Goal": "Goal",
    "Outcome": "Outcome",
    "Value": "Value",
    "CourseOfAction": "CourseOfAction",
    # Operative Ebene
    # Audit T2, Nr. 6 (L1 §23.2 / L4 §27.2): Performer ist die aktive Struktur,
    # die Rolle ist ein eigener Begriff. Guide trennt Actor und Role.
    "OperationalPerformer": "BusinessActor",
    "OperationalRole": "BusinessRole",
    "OperationalActivity": "BusinessProcess",
    "OperationalActivityAction": "BusinessProcess",
    "StandardOperationalActivity": "BusinessProcess",
    "OperationalArchitecture": "Grouping",
    "OperationalStateDescription": "Grouping",
    "Organization": "BusinessActor",
    "ActualOrganization": "BusinessActor",
    "Post": "BusinessRole",
    "ActualPost": "BusinessRole",
    "ActualPerson": "BusinessActor",
    "Location": "Location",
    "ActualLocation": "Location",
    "Environment": "Grouping",
    "ActualEnvironment": "Grouping",
    "WholeLifeEnterprise": "Grouping",
    "WholeLifeConfiguration": "Grouping",
    "VersionOfConfiguration": "Artifact",
    "EnterprisePhase": "Plateau",
    "ActualEnterprisePhase": "Plateau",
    "Project": "WorkPackage",
    "ActualProject": "WorkPackage",
    # Audit T2, Nr. 4 (Cr/Lr/Sr/Ar): Meilenstein ist ein Zeitpunkt/Ereignis,
    # kein Arbeitsergebnis (Deliverable).
    "ProjectMilestone": "ImplementationEvent",
    "ActualProjectMilestone": "ImplementationEvent",
    "ProjectMilestoneRole": "BusinessRole",
    # Audit T2, Nr. 3 (C5/C7/S8/A7): Measure ist ein Business object.
    "MeasurementType": "BusinessObject",
    "Measurement": "BusinessObject",
    "Finding": "Assessment",
    "Recommendation": "Assessment",
    "Issue": "Assessment",
    "SMEReference": "BusinessActor",
    # Information
    "InformationElement": "BusinessObject",
    "DataElement": "DataObject",
    # Audit T2 (P7 §40.2): Data Model ist ein Data object, kein Container.
    "DataModel": "DataObject",
    "DocumentReference": "Artifact",
    # Audit T2 (A1 §43.2): Glossarbegriff ist ein Meaning.
    "GlossaryEntry": "Meaning",
    "GlossaryCategory": "Grouping",
    "Information": "BusinessObject",
    # Services / Anwendungen
    "ServiceSpecification": "ApplicationService",
    "ServiceSpecificationRole": "ApplicationService",
    "ServiceFunction": "ApplicationFunction",
    "ServiceFunctionAction": "ApplicationFunction",
    # Audit T2, Nr. 7 (P1 §33.2 / P4 §36.2): Resource Function ist ein Prozess.
    "Function": "BusinessProcess",
    "FunctionAction": "BusinessProcess",
    "ServiceInterface": "ApplicationInterface",
    "ResourceInterface": "ApplicationInterface",
    "ServicePort": "ApplicationInterface",
    "ResourcePort": "ApplicationInterface",
    # Audit T2, Nr. 8 (S2 §14.2): ausfuehrbares Programm = System Software.
    "Software": "SystemSoftware",
    "System": "ApplicationComponent",
    # Technik
    # Audit T2, Nr. 9 (P3 §35.2): Protokoll ist ein Artefakt.
    "Protocol": "Artifact",
    "Protocolstack": "Artifact",
    "ProtocolLayer": "Artifact",
    "ResourceArtifact": "Artifact",
    "ResourceArchitecture": "Grouping",
    # Anforderungen
    "FunctionalRequirement": "Requirement",
    "NonfunctionalRequirement": "Requirement",
    "FulfilmentCriterion": "Requirement",
    "FitCriterion": "Requirement",
    "RequirementCategory": "Grouping",
    "RequirementCatalogue": "Grouping",
    # Katalog / Modellierung
    "Classification": "Grouping",
    # Audit T2, Nr. 2 (A8 §50.2 / P3 §35.2): Standard ist ein Contract.
    "Standard": "Contract",
    "Concern": "Driver",
    # Audit T2, Nr. 1 (A2 §44.2): Viewpoint ist ein Business object, View eine
    # Representation, die Architekturbeschreibung ein Product.
    "Viewpoint": "BusinessObject",
    "View": "Representation",
    "model document": "Grouping",
    "ArchitecturalDescription": "Product",
    "NavigationCell": "Grouping",
    # Audit T2, Anhang A (FEHLT): Energy ist konkret, der Guide nennt Material.
    "Energy": "Material",
}

#: EA-Typen ohne eigenes ArchiMate-Konzept, die der Guide dennoch abbildet.
#: Audit T2, Nr. 13 (S5 §17.2, L5 §28.2, P5 §38.2): Zustand und Ereignis sind
#: ein Event. Die Schicht steckt in ADMBw nicht im Stereotyp (Grenze 1 des
#: Audits); ``BusinessEvent`` ist die dokumentierte Naeherung und wird je
#: EA-Typ im Report gezaehlt (``approximations``).
EA_TYPE_MAP: Mapping[str, str] = {
    "state": "BusinessEvent",
    "statenode": "BusinessEvent",
    "event": "BusinessEvent",
}

#: Nur Darstellung -- kein fachliches Element, kein Semantikverlust.
SKIP_DISPLAY_TYPES = frozenset({"text", "note", "boundary", "navigationcell"})

#: Prozessmechanik ohne NAF-Pendant (Audit T2, Abschnitt 4.1: nicht vermeidbar).
#: Bleibt bewusst ohne Abbildung, wird aber getrennt gezaehlt.
SKIP_FACH_TYPES = frozenset({
    "activitypartition", "lane", "pool", "decision", "synchronization",
    "mergenode", "statemachine", "proxyconnector", "umlconnector", "sequence",
})

#: Rueckwaertskompatibler Sammelbegriff (Darstellung + Fachmechanik).
SKIP_EA_TYPES = SKIP_DISPLAY_TYPES | SKIP_FACH_TYPES

FX = {
    "Requirement": "Requirement",
    "Activity": "BusinessProcess",
    "Class": "Grouping",
    "Object": "Grouping",
    "Package": "Grouping",
}

RELATIONSHIP_MAP: Mapping[str, str] = {
    # ---- Guide-konform (Audit T2, Anhang B: KONFORM) ----------------------
    "Implements": "Realization",
    "ToBeRealizedBy": "Realization",
    "Satisfy": "Realization",
    "ConformsTo": "Realization",
    "CompliesViewpoint": "Realization",
    "Exhibits": "Realization",
    "MapsToCapability": "Realization",
    "ServiceProvision": "Realization",
    "RealiseRequirement": "Realization",
    "AchievedEffect": "Realization",
    "CapabilityGeneralization": "Specialization",
    "ServiceSpecificationGeneralization": "Specialization",
    "PropertySetGeneralisation": "Specialization",
    "PropertySetGeneralization": "Specialization",
    "PartOfCatalogue": "Aggregation",
    "PartOfCategory": "Aggregation",
    "ViewsInArchitecturalDescription": "Composition",
    "ViewpointsInArchitecturalDescription": "Composition",
    "ServiceMessage": "Flow",
    "OperationalMessage": "Flow",
    "Command": "Flow",
    "OperationalExchange": "Flow",
    "ResourceExchange": "Flow",
    "FunctionObjectFlow": "Flow",
    "OperationalObjectFlow": "Flow",
    "OperationalControlFlow": "Triggering",
    "FunctionControlFlow": "Triggering",
    "OperationalMessageFlow": "Triggering",
    "ResourceMessage": "Triggering",
    "ArchitectureForProject": "Association",
    "Classified": "Association",
    "OriginatesFrom": "Association",
    "RatifiedStandards": "Association",
    "StakeholderConcern": "Association",
    "ViewpointToStakeholder": "Association",
    "CapabilityDependency": "Serving",
    "ConsumedBy": "Serving",
    "ProvidesServiceFunction": "Serving",
    "ResourceDependency": "Serving",
    "ServiceDependency": "Serving",
    "ServiceConnector": "Serving",
    # ---- Korrigiert nach Audit T2, Anhang B (Guide nennt eine andere Relation)
    # Abstraction: Capability wird von der Aufgabe genutzt (Serving), nicht
    # realisiert; IsCapableToPerform/PerformsInContext sind Zuordnungen.
    "CapabilityForTask": "Serving",
    "IsCapableToPerform": "Assignment",
    "PerformsInContext": "Assignment",
    # Begruendungs- und Herkunftsbeziehungen sind Influence (Motivation).
    # Wo die Matrix die Richtung nicht erlaubt, invertiert der Writer die Kante
    # (z. B. JustifiedBy: der Begruender beeinflusst das Begruendete).
    "Checks": "Influence",
    "ConcernForActualEnterprisePhase": "Influence",
    "ConcernForView": "Influence",
    "ConcernForViewpoint": "Influence",
    "DerivedFrom": "Influence",
    "JustifiedBy": "Influence",
    "DesiredEffect": "Influence",
    # Phasen-/Zielsichten sind Aggregationen.
    "GoalForActualEnterprisePhase": "Aggregation",
    "VisionForActualEnterprisePhase": "Aggregation",
    # ImplementationEvent ist kein Strukturelement; Composition ist illegal.
    "OwnedMilestone": "Association",
    # Nachfolge/Zeitfolge ist Triggering.
    "VersionSuccession": "Triggering",
    "MilestoneDependency": "Triggering",
    "SuccessorOf": "Triggering",
    "ProjectSequence": "Triggering",
    "ArchitecturalSequence": "Triggering",
    # Verantwortung/Zuweisung ist Assignment.
    "IsResponsibleFor": "Assignment",
    "IsAccountableFor": "Assignment",
    "HostedOn": "Assignment",
    # Verbinder zwischen Teilen sind keine Dienste.
    "ResourceConnector": "Association",
    # ---- Ohne Guide-Regel, aber explizit statt Default (Audit T2, Nr. 10) --
    # Der fruehere Default ``Dependency -> Serving`` hat 82 Stereotype
    # semantisch falsch verbucht. Jeder Stereotyp steht jetzt selbst in der
    # Tabelle; der Default ist neutral (Association).
    "ActualProjectConsults": "Association",
    "ActualProjectDependency": "Association",
    "ActualProjectInforms": "Association",
    "ArchitecturalReference": "Association",
    "ConflictsWith": "Association",
    "DescribedBy": "Association",
    "EnvironmentalCondition": "Association",
    "EnvironmentalContext": "Association",
    "Expresses": "Association",
    "Forecast": "Association",
    "ForecastPeriod": "Association",
    "IsDuplicateOf": "Association",
    "LocationType": "Association",
    "OperationalArchitectureOfEnterprisePhase": "Association",
    "PhysicalLocation": "Association",
    "RefersTo": "Association",
    "Refines": "Association",
    "Replaces": "Association",
    "RequiredEnvironment": "Association",
    "Requires": "Association",
    "ResultsFrom": "Association",
    "SameAs": "Association",
    "ServiceClassification": "Association",
    "trace": "Association",
    "VersionReleased": "Association",
    "VersionWithdrawn": "Association",
    # ---- Guide-Soll, aber von der ArchiMate-3.2-Matrix nicht erlaubt ------
    # Evaluates: Guide nennt Realization. ``Requirement --Realization-->
    # Requirement`` kommt in relationships.xml nicht vor (Ziele sind Goal,
    # Outcome, Principle, ...). Association ist die einzige legale Kante, die
    # nicht umgebaut werden muss; der Matrix-Einwand steht im Test.
    "Evaluates": "Association",
}

TYPE_MAP: Mapping[str, str | None] = {
    "Realisation": "Realization",
    "Realization": "Realization",
    "Generalization": "Specialization",
    "Aggregation": "Aggregation",
    "Composition": "Composition",
    "InformationFlow": "Flow",
    "ControlFlow": "Triggering",
    "ObjectFlow": "Flow",
    "Sequence": "Triggering",
    "StateFlow": "Triggering",
    "Abstraction": "Realization",
    # Audit T2, Nr. 10: Serving war ein Default fuer 82 Stereotype. Eine
    # unbekannte Abhaengigkeit ist neutral, nicht "erbringt Nutzen".
    "Dependency": "Association",
    "Usage": "Serving",
    "Association": "Association",
    "Connector": "Serving",
    "Trace": "Association",
    "NoteLink": None,
    # Bereits ArchiMate-Typen: Identitaet fuer den Rueckweg XML -> IR -> XML.
    # Ohne diese Zeilen wuerde der Writer seine eigene Ausgabe nicht wieder
    # erkennen und die betroffenen Beziehungen stillschweigend verlieren.
    "Access": "Access",
    "Assignment": "Assignment",
    "Flow": "Flow",
    "Influence": "Influence",
    "Serving": "Serving",
    "Specialization": "Specialization",
    "Triggering": "Triggering",
}

#: Notnagel-Reihenfolge, wenn keine praeferierte Relation legal ist.
FALLBACKS = ("Realization", "Serving", "Association")

#: Semantisch naechste legale Relation je Ausgangsrelation (Audit T2, 3.4:
#: "FALLBACKS waehlt stumpf die erste, nicht die semantisch naechste").
#: Reihenfolge = Naehe; ``Association`` steht ueberall am Ende, weil sie
#: matrix-technisch immer erlaubt ist und nichts behauptet.
FALLBACK_PRAEFERENZ: Mapping[str, tuple[str, ...]] = {
    "Serving": ("Assignment", "Realization", "Flow"),
    # Kein Specialization: eine Realisierung ist keine Generalisierung; lieber
    # die neutrale Association als eine falsche Taxonomie.
    "Realization": ("Serving", "Assignment"),
    "Composition": ("Aggregation",),
    "Aggregation": ("Composition",),
    "Specialization": ("Realization",),
    "Triggering": ("Flow",),
    "Flow": ("Triggering",),
    "Influence": ("Realization",),
    "Assignment": ("Serving",),
    "Access": ("Association",),
}

#: Die geschlossene Typwelt des Austauschformats (ArchiMate 3.2, XSD).
#: Sie ist zugleich der Rueckweg: ein Element oder eine Beziehung, die schon
#: einen ArchiMate-Typ traegt (Import aus XML), bleibt dieser Typ. Ohne diese
#: Identitaet wuerde ``XML -> IR -> XML`` die Beziehungen verlieren, weil
#: ``TYPE_MAP`` nur EA-Namen kennt.
ARCHIMATE_ELEMENT_TYPES = frozenset({
    "AndJunction", "ApplicationCollaboration", "ApplicationComponent",
    "ApplicationEvent", "ApplicationFunction", "ApplicationInteraction",
    "ApplicationInterface", "ApplicationProcess", "ApplicationService",
    "Artifact", "Assessment", "BusinessActor", "BusinessCollaboration",
    "BusinessEvent", "BusinessFunction", "BusinessInteraction",
    "BusinessInterface", "BusinessObject", "BusinessProcess", "BusinessRole",
    "BusinessService", "Capability", "CommunicationNetwork", "Constraint",
    "Contract", "CourseOfAction", "DataObject", "Deliverable", "Device",
    "DistributionNetwork", "Driver", "Equipment", "Facility", "Gap", "Goal",
    "Grouping", "ImplementationEvent", "Location", "Material", "Meaning",
    "Node", "OrJunction", "Outcome", "Path", "Plateau", "Principle", "Product",
    "Representation", "Requirement", "Resource", "Stakeholder",
    "SystemSoftware", "TechnologyCollaboration", "TechnologyEvent",
    "TechnologyFunction", "TechnologyInteraction", "TechnologyInterface",
    "TechnologyProcess", "TechnologyService", "Value", "ValueStream",
    "WorkPackage",
})

ARCHIMATE_RELATIONSHIP_TYPES = frozenset({
    "Access", "Aggregation", "Assignment", "Association", "Composition",
    "Flow", "Influence", "Realization", "Serving", "Specialization",
    "Triggering",
})

#: Die Beziehungsmatrix kennt nur das Konzept ``Junction``; das Austauschformat
#: unterscheidet ``AndJunction``/``OrJunction``. Ohne diese Normalisierung
#: wuerde jede Kante an einer Verzweigung auf ``Association`` zurueckfallen.
MATRIX_TYPE: Mapping[str, str] = {"AndJunction": "Junction", "OrJunction": "Junction"}


# --------------------------------------------------------------------------
# Eine Kette fuer Schreiben und Pruefen
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Konzept:
    """ArchiMate-Konzept eines IR-Elements samt Herkunft der Zuordnung.

    ``herkunft`` benennt die Stufe der Kette. Damit kann ein Bericht
    ausweisen, wie belastbar eine Zuordnung ist:

    * ``stereotype``  -- Guide-Stereotyp (die fachliche Zuordnung),
    * ``metaklasse``  -- UML-Metaklasse (Annaeherung, z. B. Zustand -> Event),
    * ``rueckfall``   -- generischer Rueckfall (Requirement, Class, ...),
    * ``import``      -- das Element bringt seinen ArchiMate-Typ selbst mit,
    * ``keine``       -- keine Zuordnung; das Element ist nicht pruefbar.
    """

    typ: str | None
    herkunft: str


def archimate_konzept(stereotype: str, ea_type: str) -> Konzept:
    """ArchiMate-Konzept aus Stereotyp und Metaklasse -- eine Kette fuer alle.

    Dieselbe Reihenfolge benutzt ``_aufbau`` beim Schreiben und
    ``archimate_check`` beim Pruefen. Zwei getrennte Ketten wuerden frueher
    oder spaeter auseinanderlaufen -- dann prueft der Bericht etwas anderes
    als der Export schreibt.
    """
    roh = ea_type or ""
    if stereotype:
        treffer = ELEMENT_MAP.get(stereotype)
        if treffer:
            return Konzept(treffer, "stereotype")
    # Audit T2, Nr. 13: Zustand/Ereignis -> Event, sichtbar als Annaeherung.
    treffer = EA_TYPE_MAP.get(roh.lower())
    if treffer:
        return Konzept(treffer, "metaklasse")
    treffer = FX.get(roh)
    if treffer:
        return Konzept(treffer, "rueckfall")
    if roh in ARCHIMATE_ELEMENT_TYPES:
        # Import aus dem Austauschformat: das Element traegt seinen Typ selbst.
        return Konzept(roh, "import")
    return Konzept(None, "keine")


def archimate_beziehung(stereotype: str, ea_type: str) -> str | None:
    """ArchiMate-Beziehungsart aus Stereotyp und Metaklasse (Kette des Writers)."""
    return RELATIONSHIP_MAP.get(stereotype or "") or TYPE_MAP.get(ea_type or "")



# --------------------------------------------------------------------------
# Matrix
# --------------------------------------------------------------------------
def load_matrix(pfad: Path | None = None) -> dict[tuple[str, str], set[str]]:
    """Liest die ArchiMate-Beziehungsmatrix (Archi, EPL-2.0)."""
    basis = pfad or MATRIX_DIR / "relationships.xml"
    keys_datei = basis.with_name("relationships-keys.xml")
    if not basis.exists() or not keys_datei.exists():
        raise ArchimateWriterError(
            f"Beziehungsmatrix fehlt: {basis} (erwartet relationships.xml + relationships-keys.xml)"
        )
    keys = {
        k.get("char"): (k.get("relationship") or "").replace("Relationship", "")
        for k in ET.parse(keys_datei).getroot().iter("key")
    }
    matrix: dict[tuple[str, str], set[str]] = {}
    for quelle in ET.parse(basis).getroot().iter("source"):
        q = quelle.get("concept") or ""
        for ziel in quelle.iter("target"):
            for buchstabe in ziel.get("relations") or "":
                rel = keys.get(buchstabe)
                if rel:
                    matrix.setdefault((q, rel), set()).add(ziel.get("concept") or "")
    return matrix


def _erlaubt(matrix, quelle: str, rel: str, ziel: str) -> bool:
    """Matrix-Pruefung eines Typ/Relation/Typ-Tripels.

    ``Association`` ist laut Matrix fuer 3841 von 3844 Typparen erlaubt (Ausnahme
    nur ``Junction``/``Relationship``, die der Writer nie erzeugt); der
    Kurzschluss ist daher matrix-konform und wird im Test geprueft.
    """
    if rel == "Association":
        return True
    return ziel in matrix.get((quelle, rel), set())


#: Oeffentlicher Name fuer dieselbe Pruefung (``archimate_check`` nutzt ihn).
matrix_erlaubt = _erlaubt


def _naechste_legale(matrix, quelle: str, rel: str, ziel: str) -> str:
    """Erste semantisch naechste legale Relation (Audit T2, Abschnitt 3.4).

    Reihenfolge: ``FALLBACK_PRAEFERENZ[rel]``, dann ``FALLBACKS``. Da
    ``Association`` laut Matrix immer erlaubt ist, endet die Suche spaetestens
    dort -- ein Rueckfall auf eine illegale Kante ist ausgeschlossen.
    """
    for kandidat in FALLBACK_PRAEFERENZ.get(rel, ()) + FALLBACKS:
        if _erlaubt(matrix, quelle, kandidat, ziel):
            return kandidat
    return "Association"



# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
@dataclass
class ArchimateReport:
    """Messprotokoll des Laufs. Jede Naeherung hat einen eigenen Zaehler.

    Die Felder sind bewusst flach und JSON-faehig: derselbe Report geht an die
    CLI, an ``eam-ai archimate`` und in die Abnahme (Audit T2, Abschnitt 4.2).
    """

    elements: int = 0
    relationships: int = 0
    remapped: int = 0          # Kante musste den Relationstyp wechseln
    inverted: int = 0          # Kante war nur in Gegenrichtung legal
    unresolved: int = 0        # fachlicher Endpunkt ohne Abbildung
    unresolved_display: int = 0  # Endpunkt ist ein Darstellungselement
    collapsed: int = 0         # Port/Part/Pin auf Traeger gezogen
    skipped_display: int = 0   # Text/Note/Boundary/NavigationCell
    skipped_fachlich: int = 0  # Prozessmechanik ohne NAF-Pendant
    skipped_package_entries: int = 0
    skipped_connector: int = 0  # Beziehung ohne Regel und ohne NoteLink
    self_edges: int = 0        # Quelle == Ziel nach Traegeraufloesung
    duplicates: int = 0        # gleiche Quelle/Ziel/Relation schon vorhanden
    note_links: int = 0        # Darstellungsbeziehung, kein Semantikverlust
    packages: int = 0
    packages_emitted: int = 0
    packages_not_emitted: int = 0
    fallback: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_relation: dict[str, int] = field(default_factory=dict)
    unresolved_by_type: dict[str, int] = field(default_factory=dict)
    unresolved_display_by_type: dict[str, int] = field(default_factory=dict)
    collapsed_by_type: dict[str, int] = field(default_factory=dict)
    skipped_display_by_type: dict[str, int] = field(default_factory=dict)
    skipped_fachlich_by_type: dict[str, int] = field(default_factory=dict)
    skipped_connector_by_type: dict[str, int] = field(default_factory=dict)
    self_edges_by_type: dict[str, int] = field(default_factory=dict)
    duplicates_by_relation: dict[str, int] = field(default_factory=dict)
    remapped_by_relation: dict[str, int] = field(default_factory=dict)
    remaps: dict[str, int] = field(default_factory=dict)
    remap_by_type: dict[str, int] = field(default_factory=dict)
    inverted_by_type: dict[str, int] = field(default_factory=dict)
    approximations: dict[str, int] = field(default_factory=dict)
    unmapped: tuple[dict[str, str], ...] = ()
    remap_samples: tuple[dict[str, str], ...] = ()
    inverted_samples: tuple[dict[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """JSON-faehige Fassung, deterministisch sortiert."""
        daten: dict[str, Any] = {}
        for name in (
            "elements", "relationships", "remapped", "inverted", "unresolved",
            "unresolved_display", "collapsed", "skipped_display",
            "skipped_fachlich", "skipped_package_entries", "skipped_connector",
            "self_edges", "duplicates", "note_links", "packages",
            "packages_emitted", "packages_not_emitted",
        ):
            daten[name] = getattr(self, name)
        for name in (
            "fallback", "by_type", "by_relation", "unresolved_by_type",
            "unresolved_display_by_type", "collapsed_by_type",
            "skipped_display_by_type", "skipped_fachlich_by_type",
            "skipped_connector_by_type", "self_edges_by_type",
            "duplicates_by_relation", "remapped_by_relation", "remaps",
            "remap_by_type", "inverted_by_type", "approximations",
        ):
            daten[name] = dict(sorted(getattr(self, name).items()))
        daten["unmapped"] = [dict(e) for e in self.unmapped]
        daten["remap_samples"] = [dict(e) for e in self.remap_samples]
        daten["inverted_samples"] = [dict(e) for e in self.inverted_samples]
        return daten


def _zaehl(speicher: dict[str, int], schluessel: str, n: int = 1) -> None:
    speicher[schluessel] = speicher.get(schluessel, 0) + n



def _fail(message: str) -> NoReturn:
    raise ArchimateWriterError(message)


# --------------------------------------------------------------------------
# IR lesen
# --------------------------------------------------------------------------
def _text(value: Any, what: str, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        _fail(f"{what}: Zeichenkette erwartet, gefunden {type(value).__name__}")
    return value.strip()


def _roh(value: Any, what: str, *, default: str = "") -> str:
    """Wie _text, aber ohne Trimmen -- Referenzen sind exakt zu vergleichen."""
    if value is None:
        return default
    if not isinstance(value, str):
        _fail(f"{what}: Zeichenkette erwartet, gefunden {type(value).__name__}")
    return value


def _sequence(value: Any, what: str) -> Sequence[Any]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        _fail(f"{what}: Liste erwartet, gefunden {type(value).__name__}")
    return value


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{what}: Objekt erwartet, gefunden {type(value).__name__}")
    return value


def kennung(guid: str, ref: str) -> str:
    """XML-Kennung eines Elements/einer Beziehung.

    Mit GUID: ``id-<guid>`` (bereinigt, klein). Ohne GUID: stabiler Hash aus
    der IR-Referenz. Der ``archimate_reader`` benutzt dieselbe Ableitung, um
    beim Einlesen zu pruefen, ob eine Kennung aus der GUID rekonstruierbar ist.
    """
    roh = guid.strip("{}").lower() if guid else ""
    if not roh:
        roh = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:32]
    sicher = "".join(c if c.isalnum() or c in "-._" else "-" for c in roh)
    return "id-" + sicher


#: Interner Name (Bestand) -- die Ableitung ist jetzt oeffentlich.
_kennung = kennung


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------
def _aufbau(ir: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], ArchimateReport]:
    obj = _mapping(ir, "IR")
    if obj.get("ir_version") != IR_VERSION:
        _fail(f"ir_version: erwartet {IR_VERSION}, gefunden {obj.get('ir_version')!r}")

    report = ArchimateReport()
    roh_elemente = _sequence(obj.get("elements"), "elements")
    roh_kanten = _sequence(obj.get("connectors"), "connectors")
    if not roh_elemente:
        _fail("elements: das IR enthaelt kein Element -- Abbruch statt leerer Datei")

    # Index ref -> Element
    nach_ref: dict[str, Mapping[str, Any]] = {}
    for index, eintrag in enumerate(roh_elemente):
        e = _mapping(eintrag, f"elements[{index}]")
        ref = _roh(e.get("ref"), f"elements[{index}].ref")
        if not ref:
            _fail(
                f"elements[{index}]: 'ref' fehlt -- ArchiMate braucht stabile Referenzen "
                "(read_qea_ex(..., with_refs=True))"
            )
        if ref in nach_ref:
            _fail(f"elements[{index}]: Referenz {ref!r} ist doppelt")
        nach_ref[ref] = e

    # Ports/Parts/Pins auf ihren Traeger ziehen (auch ueber Ketten)
    roh_owner: dict[str, str] = {}
    for ref, e in nach_ref.items():
        owner = _roh(e.get("owner"), f"{ref}.owner")
        if owner:
            roh_owner[ref] = owner

    def _wurzel(ref: str) -> str:
        gesehen: set[str] = set()
        while ref in roh_owner and ref not in gesehen:
            gesehen.add(ref)
            ref = roh_owner[ref]
        return ref

    ersatz = {ref: _wurzel(ref) for ref in roh_owner}

    elemente: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    typen: dict[str, str] = {}
    for ref, e in nach_ref.items():
        ea_type = _text(e.get("ea_type"), f"{ref}.ea_type").lower()
        stereo = _text(e.get("stereotype"), f"{ref}.stereotype")
        if ref in roh_owner:
            # Traeger-Aufloesung: das Detailelement selbst entfaellt,
            # seine Kanten laufen auf das Traegerelement.
            report.collapsed += 1
            _zaehl(report.collapsed_by_type, stereo or ea_type or "?")
            continue
        if ea_type in SKIP_DISPLAY_TYPES:
            report.skipped_display += 1
            _zaehl(report.skipped_display_by_type, ea_type)
            continue
        if ea_type in SKIP_FACH_TYPES:
            # Prozessmechanik ohne NAF-Pendant: bewusst ohne Abbildung, aber
            # als fachlicher Verlust getrennt von Darstellung gezaehlt.
            report.skipped_fachlich += 1
            _zaehl(report.skipped_fachlich_by_type, stereo or ea_type)
            continue
        if ea_type == "package" and not stereo:
            report.skipped_package_entries += 1
            continue
        konzept = archimate_konzept(stereo, _text(e.get("ea_type"), f"{ref}.ea_type"))
        ziel_typ = konzept.typ
        if konzept.herkunft == "metaklasse":
            # Audit T2, Nr. 13: Zustand/Ereignis -> Event, sichtbar gezaehlt.
            _zaehl(report.approximations, f"{ea_type}->{ziel_typ}")
        elif konzept.herkunft == "rueckfall":
            _zaehl(report.fallback, ea_type or "?")
        if not ziel_typ:
            report.unmapped = report.unmapped + ({
                "ref": ref,
                "name": _text(e.get("name"), f"{ref}.name"),
                "ea_type": ea_type,
                "stereotype": stereo,
            },)
            continue
        # Eine mitgelieferte Kennung hat Vorrang: sie ist die Identitaet des
        # Austauschformats und muss den Rueckweg unveraendert ueberstehen.
        element_id = _text(e.get("identifier"), f"{ref}.identifier") or _kennung(
            _text(e.get("guid"), f"{ref}.guid"), ref
        )
        ids[ref] = element_id
        typen[ref] = MATRIX_TYPE.get(ziel_typ, ziel_typ)
        elemente.append({
            "id": element_id,
            "ref": ref,
            "type": ziel_typ,
            "name": _text(e.get("name"), f"{ref}.name") or "(ohne Namen)",
            "notes": _text(e.get("notes"), f"{ref}.notes"),
            "stereotype": stereo,
            "ea_type": _text(e.get("ea_type"), f"{ref}.ea_type"),
            "package": _text(e.get("package"), f"{ref}.package"),
            "guid": _text(e.get("guid"), f"{ref}.guid"),
        })
        report.by_type[ziel_typ] = report.by_type.get(ziel_typ, 0) + 1

    if not elemente:
        _fail("kein Element mit ArchiMate-Abbildung -- Abbruch")

    # Pakete, auf die Kanten zeigen, werden zu ArchiMate-Elementen
    pakete = {
        _roh(p.get("path"), f"packages[{i}].path"): p
        for i, p in enumerate(_sequence(obj.get("packages"), "packages"))
        if _roh(p.get("path"), f"packages[{i}].path")
    }
    report.packages = len(pakete)
    paket_ids: dict[str, str] = {}
    for index, eintrag in enumerate(roh_kanten):
        c = _mapping(eintrag, f"connectors[{index}]")
        for seite in ("source", "target"):
            ref = _roh(c.get(seite), f"connectors[{index}].{seite}")
            if not ref or ref in ids or ref in paket_ids:
                continue
            paket = pakete.get(ref)
            if paket is None:
                continue
            stereo = _text(paket.get("stereotype"), f"{ref}.stereotype")
            ziel_typ = ELEMENT_MAP.get(stereo) if stereo else None
            if not ziel_typ:
                continue
            paket_id = _text(paket.get("identifier"), f"{ref}.identifier") or _kennung(
                _text(paket.get("guid"), f"{ref}.guid"), ref
            )
            paket_ids[ref] = paket_id
            ids[ref] = paket_id
            typen[ref] = MATRIX_TYPE.get(ziel_typ, ziel_typ)
            elemente.append({
                "id": paket_id,
                "ref": ref,
                "type": ziel_typ,
                "name": ref.rsplit("/", 1)[-1],
                "notes": _text(paket.get("notes"), f"{ref}.notes"),
                "stereotype": stereo,
                "ea_type": "Package",
                "package": ref.rsplit("/", 1)[0] if "/" in ref else "",
                "guid": _text(paket.get("guid"), f"{ref}.guid"),
            })
            report.by_type[ziel_typ] = report.by_type.get(ziel_typ, 0) + 1

    # Kanten
    matrix = load_matrix()
    kanten: list[dict[str, Any]] = []
    gesehen: set[tuple[str, str, str]] = set()
    for index, eintrag in enumerate(roh_kanten):
        c = _mapping(eintrag, f"connectors[{index}]")
        ea_type = _text(c.get("ea_type"), f"connectors[{index}].ea_type")
        stereo = _text(c.get("stereotype"), f"connectors[{index}].stereotype")
        rel = RELATIONSHIP_MAP.get(stereo) or TYPE_MAP.get(ea_type)
        if rel is None:
            # Zwei verschiedene Verluste, zwei Zaehler: NoteLink ist reine
            # Darstellung, alles andere hat keine Regel (Audit T2, 4.2).
            if TYPE_MAP.get(ea_type, "unbekannt") is None:
                report.note_links += 1
            else:
                report.skipped_connector += 1
                _zaehl(report.skipped_connector_by_type, stereo or ea_type or "?")
            continue

        quelle = _roh(c.get("source"), f"connectors[{index}].source")
        ziel = _roh(c.get("target"), f"connectors[{index}].target")
        quelle = ersatz.get(quelle, quelle)
        ziel = ersatz.get(ziel, ziel)
        offen = [ref for ref in (quelle, ziel) if ref and ref not in ids]
        if offen:
            ref = offen[0]
            offener_typ = _text(nach_ref[ref].get("ea_type"), "ea_type").lower() if ref in nach_ref else ""
            if offener_typ in SKIP_DISPLAY_TYPES:
                # Eine Darstellungs-Kante (Text an einem Element) ist kein
                # fachlicher Verlust; sie wird getrennt gezaehlt, nicht als
                # unresolved verbucht (Audit T2: "falsch verbucht").
                report.unresolved_display += 1
                _zaehl(report.unresolved_display_by_type, offener_typ)
            else:
                report.unresolved += 1
                grund = _text(nach_ref.get(ref, {}).get("ea_type"), "ea_type")
                if not grund:
                    grund = "paket" if ref in pakete else "unbekannt"
                _zaehl(report.unresolved_by_type, grund)
            continue

        if quelle == ziel:
            report.self_edges += 1
            _zaehl(report.self_edges_by_type, stereo or ea_type or "?")
            continue

        qtyp, ztyp = typen[quelle], typen[ziel]
        gewaehlt = rel
        if not _erlaubt(matrix, qtyp, rel, ztyp):
            if _erlaubt(matrix, ztyp, rel, qtyp):
                # Nur die Gegenrichtung ist legal. Das ADMBw-Modell zeichnet
                # die Kante vom Teil zum Ganzen (z. B.
                # ViewsInArchitecturalDescription: Sicht -> Produkt); ArchiMate
                # verlangt Produkt --Composition--> Sicht.
                alt_q, alt_z = qtyp, ztyp
                quelle, ziel = ziel, quelle
                qtyp, ztyp = ztyp, qtyp
                report.inverted += 1
                _zaehl(report.inverted_by_type, stereo or ea_type or "?")
                if len(report.inverted_samples) < 10:
                    report.inverted_samples = report.inverted_samples + ({
                        "relation": rel, "stereotype": stereo, "ea_type": ea_type,
                        "von_quelle": alt_q, "von_ziel": alt_z,
                        "nach_quelle": qtyp, "nach_ziel": ztyp,
                    },)
            else:
                gewaehlt = _naechste_legale(matrix, qtyp, rel, ztyp)
                report.remapped += 1
                _zaehl(report.remapped_by_relation, rel)
                _zaehl(report.remaps, f"{rel}->{gewaehlt}")
                _zaehl(report.remap_by_type, f"{rel}->{gewaehlt}|{qtyp}->{ztyp}")
                if len(report.remap_samples) < 10:
                    report.remap_samples = report.remap_samples + ({
                        "von": rel, "nach": gewaehlt, "quelle": qtyp, "ziel": ztyp,
                        "stereotype": stereo, "ea_type": ea_type,
                    },)
        schluessel = (quelle, ziel, gewaehlt)
        if schluessel in gesehen:
            report.duplicates += 1
            _zaehl(report.duplicates_by_relation, gewaehlt)
            continue
        gesehen.add(schluessel)
        kanten.append({
            "id": _text(c.get("identifier"), f"connectors[{index}].identifier")
                  or _kennung(_text(c.get("guid"), f"connectors[{index}].guid"),
                              f"{quelle}>{ziel}>{gewaehlt}"),
            "type": gewaehlt,
            "source": ids[quelle],
            "target": ids[ziel],
            "name": _text(c.get("name"), f"connectors[{index}].name"),
        })
        _zaehl(report.by_relation, gewaehlt)

    report.elements = len(elemente)
    report.relationships = len(kanten)
    report.packages_emitted = len(paket_ids)
    report.packages_not_emitted = report.packages - report.packages_emitted
    return elemente, kanten, report


def modellkopf(ir: Any) -> tuple[str, str]:
    """Modellname und -kennung aus ``meta.archimate`` (Rueckweg aus XML).

    Der Reader legt beides dort ab; ohne diesen Block waere ``XML -> IR -> XML``
    schon an der Modellkennung nicht mehr identisch. Fremde IR ohne den Block
    verhalten sich unveraendert.
    """
    obj = ir if isinstance(ir, Mapping) else {}
    meta = obj.get("meta")
    archimate = meta.get("archimate") if isinstance(meta, Mapping) else None
    if not isinstance(archimate, Mapping):
        return "", ""
    name = archimate.get("name")
    identifier = archimate.get("identifier")
    return (
        name if isinstance(name, str) else "",
        identifier if isinstance(identifier, str) else "",
    )


# Alter, privater Name bleibt als Alias -- Aufrufer ausserhalb des Pakets
# sollen nicht brechen.
_modellkopf = modellkopf


def render_bytes(ir: Any, *, modellname: str = "") -> bytes:
    """IR -> ArchiMate-XML als Bytes (deterministisch)."""
    elemente, kanten, _ = _aufbau(ir)
    ET.register_namespace("", NS)
    ET.register_namespace("xsi", XSI)

    meta_name, meta_identifier = modellkopf(ir)
    name = modellname or meta_name or "Modell"
    identifier = meta_identifier or (
        "id-model-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    )
    root = ET.Element(f"{{{NS}}}model", {
        "identifier": identifier,
        "version": "3.2",
    })
    ET.SubElement(root, f"{{{NS}}}name", {"xml:lang": "de"}).text = name

    block = ET.SubElement(root, f"{{{NS}}}elements")
    for e in elemente:
        el = ET.SubElement(block, f"{{{NS}}}element", {
            "identifier": e["id"], f"{{{XSI}}}type": e["type"],
        })
        ET.SubElement(el, f"{{{NS}}}name", {"xml:lang": "de"}).text = e["name"]
        if e["notes"]:
            ET.SubElement(el, f"{{{NS}}}documentation", {"xml:lang": "de"}).text = e["notes"]
        props = ET.SubElement(el, f"{{{NS}}}properties")
        for pid, wert in (
            ("prop-admbw-stereotype", e["stereotype"]),
            ("prop-admbw-metatype", e["ea_type"]),
            ("prop-ea-guid", e["guid"]),
            ("prop-paketpfad", e["package"]),
        ):
            if wert:
                ET.SubElement(props, f"{{{NS}}}property", {"propertyDefinitionRef": pid}).append(
                    _wert(wert)
                )

    block = ET.SubElement(root, f"{{{NS}}}relationships")
    for k in kanten:
        rel = ET.SubElement(block, f"{{{NS}}}relationship", {
            "identifier": k["id"], f"{{{XSI}}}type": k["type"],
            "source": k["source"], "target": k["target"],
        })
        if k["name"]:
            ET.SubElement(rel, f"{{{NS}}}name", {"xml:lang": "de"}).text = k["name"]

    defs = ET.SubElement(root, f"{{{NS}}}propertyDefinitions")
    for pid, pname in (
        ("prop-admbw-stereotype", "ADMBw_Stereotyp"),
        ("prop-admbw-metatype", "ADMBw_Metaklasse"),
        ("prop-ea-guid", "Sparx_EA_GUID"),
        ("prop-paketpfad", "Paketpfad"),
    ):
        d = ET.SubElement(defs, f"{{{NS}}}propertyDefinition", {"identifier": pid, "type": "string"})
        ET.SubElement(d, f"{{{NS}}}name", {"xml:lang": "en"}).text = pname

    roh = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(roh).toprettyxml(indent="  ", encoding="utf-8")


def _wert(text: str) -> ET.Element:
    v = ET.Element(f"{{{NS}}}value", {"xml:lang": "de"})
    v.text = text
    return v


def write_archimate(ir: Any, path: str | Path, *, modellname: str = "") -> ArchimateReport:
    """Schreibt die Datei und liefert den Report."""
    daten = render_bytes(ir, modellname=modellname)
    ziel = Path(path)
    ziel.write_bytes(daten)
    _, _, report = _aufbau(ir)
    return report


# --------------------------------------------------------------------------
# CLI (eigenstaendig, zusaetzlich zum eam-ai-Unterbefehl)
# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="archimate_writer",
        description="IR (.qea/.json) -> ArchiMate 3.2 Model Exchange XML",
    )
    parser.add_argument("--ir", required=True, type=Path, help="IR-JSON oder .qea")
    parser.add_argument("--out", "-o", required=True, type=Path, help="Zieldatei (.xml)")
    parser.add_argument("--report", type=Path, default=None, help="Report als JSON")
    args = parser.parse_args(argv)

    if args.ir.suffix.lower() == ".qea":
        from qea_reader import read_qea_ex

        ir, _ = read_qea_ex(args.ir, with_refs=True, with_owners=True)
    else:
        ir = json.loads(args.ir.read_text(encoding="utf-8"))

    # Ein IR aus dem Reader traegt seinen Modellkopf; ihn zu ueberschreiben
    # braeche den byte-identischen Rundlauf. Der Dateiname ist nur Notbehelf.
    name = "" if modellkopf(ir)[0] else args.ir.stem

    report = write_archimate(ir, args.out, modellname=name)
    daten = report.as_dict()
    print(json.dumps(daten, ensure_ascii=False, indent=2))
    if args.report:
        args.report.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
