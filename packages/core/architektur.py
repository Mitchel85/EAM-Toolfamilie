"""architektur.py -- eine Architektur bauen, die der Leitfaden verlangt.

Was dieser Baustein tut
-----------------------
Er baut aus einem geparsten MDG-Regelwerk ein Modell mit der **Struktur, die
der Leitfaden in Abbildung 1 zeigt** und den **Sichten, die die
Konventionen ``xx-MK01`` ff. vorschreiben**:

    StEKa                                  Standardelementekatalog (eigene Wurzel)
    <Projekt>
    ├── <Projekt> - Startseite             Diagramm "Startseite <Projekt>" (St-MK03)
    ├── <Projekt> - Glossar
    │   └── Glossar
    ├── «ArchitecturalDescription» <Projekt> - Projektarchitektur
    │   ├── Architecture Foundation        A1..A8, Ar
    │   ├── Concepts                       C1, C8, Cr
    │   ├── Logical Specifications         L1..L8
    │   ├── Service Specifications         S1..S7, Sr
    │   ├── Physical Resource Specifications P1, P2, P7, P8
    │   ├── Requirements                   R2, R3, R7
    │   └── Modellelementekatalog          je Stereotyp ein Paket
    └── «ArchitecturalDescription» <Projekt> - PBN-Architektur

Warum diese Form
----------------
Die Musterarchitektur MASC zeigt sie (Abbildung 1 des Leitfadens: "MASC -
Projektarchitektur" mit genau diesen Perspektiven und dem
Modellelementekatalog), und die Konventionen ``xx-MK01`` schreiben je
Viewpoint ein Paket mit festem Namen vor. Der Leitfaden nennt die Perspektive
"Architecture Foundation", MASC schreibt "Architekturauftrag"; dieser Baustein
folgt dem Leitfaden, weil dieser verbindlich ist (Kapitel 2.6).

Projektinhalte
--------------
Der Katalog enthält die Stereotyp-Definitionen des Regelwerks, die
Viewpoint-Pakete je Viewpoint ein ``Viewpoint`` und ein ``View``. Inhalte
aus Prosa werden **nicht** erfunden: ``inhalte`` ist eine Liste bereits
belegter IR-Elemente/Kanten, die in die passende Perspektive einsortiert
werden. Fehlt sie, steht eine ehrliche Formalarchitektur da -- vollständig in
der Form, leer an projektspezifischem Inhalt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import extract
import leitfaden

#: Kennung im IR.
ARCH_BACKEND = "leitfaden-architektur"

#: Perspektive -> (Konventionspaket, Viewpoint-Codes, MASC-Paketname).
PERSPEKTIVEN: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Architecture Foundation", ("A1", "A2", "A3", "A6", "A7", "A8", "Ar"), "Architecture Foundation"),
    ("Concepts", ("C1", "C8", "Cr"), "Concepts"),
    ("Logical Specifications", ("L1", "L2", "L3", "L4", "L7", "L8"), "Logical Specifications"),
    ("Service Specifications", ("S1", "S2", "S3", "S4", "S7", "Sr"), "Service Specifications"),
    ("Physical Resource Specifications", ("P1", "P2", "P7", "P8"), "Physical Resource Specifications"),
    ("Requirements", ("R2", "R3", "R7"), "Requirements"),
)

#: Stereotyp -> Perspektive. Bestimmt, wohin ein Inhaltselement einsortiert
#: wird, wenn die Prosa es liefert. Unbekannte Stereotype landen in der
#: Perspektive des Viewpoints, der sie zuerst nennt -- sonst "Concepts".
STEREO_PRAEFIX: tuple[tuple[str, str], ...] = (
    ("Architectural", "Architecture Foundation"),
    ("Classification", "Architecture Foundation"),
    ("Standard", "Architecture Foundation"),
    ("View", "Architecture Foundation"),
    ("Viewpoint", "Architecture Foundation"),
    ("Concern", "Architecture Foundation"),
    ("Finding", "Architecture Foundation"),
    ("Recommendation", "Architecture Foundation"),
    ("Capability", "Concepts"),
    ("Enterprise", "Concepts"),
    ("WholeLife", "Concepts"),
    ("ActualEnterprisePhase", "Concepts"),
    ("Strategic", "Concepts"),
    ("OperationalArchitecture", "Logical Specifications"),
    ("OperationalPerformer", "Logical Specifications"),
    ("OperationalActivity", "Logical Specifications"),
    ("OperationalConstraint", "Logical Specifications"),
    ("InformationElement", "Logical Specifications"),
    ("Information", "Logical Specifications"),
    ("Service", "Service Specifications"),
    ("Resource", "Physical Resource Specifications"),
    ("System", "Physical Resource Specifications"),
    ("Software", "Physical Resource Specifications"),
    ("Hardware", "Physical Resource Specifications"),
    ("Requirement", "Requirements"),
    ("FunctionalRequirement", "Requirements"),
    ("NonFunctionalRequirement", "Requirements"),
)

MODEL_CATALOG = "Modellelementekatalog"


class ArchitekturFehler(ValueError):
    """Regelwerk oder Auftrag taugen nicht. Immer laut."""


def _projekt(auftrag: Mapping[str, Any] | str) -> str:
    if isinstance(auftrag, str):
        text = auftrag.strip()
        if not text:
            raise ArchitekturFehler("Projektkürzel darf nicht leer sein")
        if any(ch in text for ch in "/\\:"):
            raise ArchitekturFehler(f"Projektkürzel {text!r} enthält unzulässige Zeichen (/ \\ :)")
        return text
    return ""


def _perspektive_fuer(stereotype: str) -> str:
    for prefix, perspektive in STEREO_PRAEFIX:
        if stereotype.startswith(prefix):
            return perspektive
    return "Concepts"


def _segment(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().replace("/", "∕").replace("::", ":")


@dataclass(frozen=True)
class Auftrag:
    """Was eine Architektur ausmacht -- ohne den Inhalt zu erfinden."""

    projekt: str
    titel: str = ""
    architekt: str = ""
    version: str = "1.0"
    einstufung: str = "OFFEN"
    phase: str = ""

    @classmethod
    def von_mapping(cls, data: Mapping[str, Any]) -> "Auftrag":
        projekt = _projekt(str(data.get("projekt") or "").strip())
        return cls(
            projekt=projekt,
            titel=str(data.get("titel") or "").strip(),
            architekt=str(data.get("architekt") or "").strip(),
            version=str(data.get("version") or "1.0").strip(),
            einstufung=str(data.get("einstufung") or "OFFEN").strip(),
            phase=str(data.get("phase") or "").strip(),
        )


def _catalog_entries(rules: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Instanziierbare Element-Stereotype (nicht abstrakt, nicht nur Package)."""
    out: list[dict[str, Any]] = []
    for entry in rules.get("elementStereotypes") or ():
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name") or "").strip()
        if not name or entry.get("abstract") is True:
            continue
        metaclasses = [m for m in entry.get("metaclasses") or [] if str(m).strip()]
        if not metaclasses:
            continue  # ohne Metaklasse nicht instanziierbar (MDG-Warnung)
        if all(str(m).strip().lower() == "package" for m in metaclasses):
            # Paketstereotype (ArchitecturalDescription, DataModel) werden als
            # Paketstereotyp am Perspektivpaket verwendet, nicht als Element.
            continue
        out.append(
            {
                "name": name,
                "ea_type": str(metaclasses[0]).strip(),
                "notes": str(entry.get("notes") or "").strip()
                or f"Element-Stereotyp '{name}' aus dem Regelwerk.",
            }
        )
    return sorted(out, key=lambda item: (item["name"].casefold(), item["name"]))


def _package_stereotypes(rules: Mapping[str, Any]) -> set[str]:
    """Stereotype, die nur auf Pakete angewendet werden dürfen."""
    out: set[str] = set()
    for entry in rules.get("elementStereotypes") or ():
        if not isinstance(entry, Mapping):
            continue
        metaclasses = [str(m).strip().lower() for m in entry.get("metaclasses") or ()]
        if metaclasses and all(m == "package" for m in metaclasses):
            out.add(str(entry.get("name") or ""))
    return out


def _viewpoints(rules: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in rules.get("viewpoints") or ():
        if not isinstance(entry, Mapping):
            continue
        properties = entry.get("properties") or {}
        code = str(properties.get("diagramID") or "").strip()
        if not code:
            code = str(entry.get("name") or "").split(" - ")[0].strip()
        if code:
            out.setdefault(code, dict(entry))
    return out


def _mdg_viewpoint(viewpoint: Mapping[str, Any]) -> str:
    """``MDGDgm``-Wert: "<Profil-Viewpoint-Gruppe>::<Viewpoint-Name>"."""
    group = str(viewpoint.get("group") or "").strip()
    name = str(viewpoint.get("name") or "").strip()
    return f"{group}::{name}" if group else name


def build_architektur(
    rules: Mapping[str, Any],
    auftrag: Auftrag,
    *,
    inhalte: Mapping[str, Any] | None = None,
    mit_katalog: bool = True,
    mit_viewpoint_paketen: bool = True,
    mit_startseite: bool = True,
    mit_viewpoint_uebersicht: bool = True,
    max_elemente_je_sicht: int = 60,
) -> dict[str, Any]:
    """Baut das Architektur-IR nach Leitfaden und MASC-Vorbild.

    ``inhalte`` ist ein IR-Ausschnitt (``elements``/``connectors``) mit
    belegten Projektinhalten; er wird in die Perspektiven einsortiert und mit
    den Pflichtelementen zusammengeführt.
    """
    projekt = auftrag.projekt
    viewpoints = _viewpoints(rules)
    catalog = _catalog_entries(rules) if mit_katalog else []
    pkg_stereos = _package_stereotypes(rules)

    packages: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    connectors: list[dict[str, Any]] = []
    diagrams: list[dict[str, Any]] = []

    root_notes = auftrag.titel or f"Projektarchitektur {projekt}"
    # Leitfaden Abbildung 1: "StEKa" steht als eigene Wurzel neben dem Projekt.
    # Es ist das Startpaket (initiale .qea mit Standardelementen). Ohne die
    # Datei bleibt das Paket leer -- aber es muss existieren, weil die
    # Konventionen Elemente "aus dem Modellelementekatalog entnehmen" und der
    # Katalog ohne StEKa nur die Regelwerk-Stereotype kennt.
    packages.append({"path": "StEKa", "notes": "Standardelementekatalog (Startpaket, Leitfaden Abbildung 1)."})
    packages.append({"path": projekt, "notes": root_notes})

    # --- Startseite -----------------------------------------------------
    startseite = f"{projekt} - Startseite"
    if mit_startseite:
        packages.append(
            {
                "path": startseite,
                "notes": "Startseite des Architekturmodells (Leitfaden St-MK01).",
                "stereotype": _sicher_paket(rules, "ArchitecturalDescription"),
            }
        )
        # St-MK04 verlangt ein Bild des ADMBw Grids. Ohne Startpaket liegt
        # kein Bild vor -- ein Text-Element zum Auftrag tritt an seine Stelle.
        auftrag_stereo, auftrag_type = _stereotyp(rules, "ArchitectureMetadata", "Definition")
        if auftrag_stereo:
            elements.append(
                {
                    "package": startseite,
                    "name": f"Architekturauftrag {projekt}",
                    "stereotype": auftrag_stereo,
                    "ea_type": auftrag_type,
                    "notes": _auftrag_note(auftrag),
                }
            )
        if auftrag.einstufung:
            elements.append(
                {
                    "package": startseite,
                    "name": auftrag.einstufung,
                    "stereotype": _sicher(rules, "Classification"),
                    "ea_type": "Class",
                    "notes": f"Einstufung der Architektur: {auftrag.einstufung}.",
                }
            )
        diagrams.append(
            {
                "name": f"Startseite {projekt}",
                "package": startseite,
                "type": leitfaden.DIAGRAM_EA_TYPE,
                "mdg": _startseite_mdg(viewpoints),
                "default": True,
                "notes": "Startseite (Leitfaden St-MK02, St-MK03).",
                "members": [
                    {"element": f"{startseite}::Architekturauftrag {projekt}"},
                    *(
                        [{"element": f"{startseite}::{auftrag.einstufung}", "left": 420, "top": 0,
                          "right": 620, "bottom": 80}]
                        if auftrag.einstufung
                        else []
                    ),
                ],
            }
        )

    # --- Glossar --------------------------------------------------------
    glossar = f"{projekt} - Glossar"
    abk = f"{glossar}/Abkürzungsverzeichnis"
    packages.append({"path": glossar, "notes": "Begriffe des Modells."})
    packages.append({"path": abk, "notes": "Abkürzungen."})
    elements.append(
        {
            "package": abk,
            "name": projekt,
            "stereotype": _sicher(rules, "DocumentReference"),
            "ea_type": "Class",
            "notes": f"Abkürzung für das Projekt {projekt}.",
        }
    )

    # --- Projektarchitektur --------------------------------------------
    arch = f"{projekt} - Projektarchitektur"
    packages.append(
        {
            "path": arch,
            "notes": "Projektarchitektur (Leitfaden Abbildung 1).",
            "stereotype": _sicher_paket(rules, "ArchitecturalDescription"),
        }
    )

    # 1) Modellelementekatalog: je Stereotyp ein Paket.
    if mit_katalog:
        katalog = f"{arch}/{MODEL_CATALOG}"
        packages.append(
            {
                "path": katalog,
                "notes": "Modellelementekatalog (StEKa-Ersatz, Leitfaden St-MK05).",
                "stereotype": "ElementCatalogue" if "ElementCatalogue" in pkg_stereos else "",
            }
        )
        for entry in catalog:
            pkg = f"{katalog}/{_segment(entry['name'])}"
            packages.append({"path": pkg, "notes": f"Stereotyp {entry['name']} ({entry['ea_type']})."})
            elements.append(
                {
                    "package": pkg,
                    "name": entry["name"],
                    "stereotype": entry["name"],
                    "ea_type": entry["ea_type"],
                    "notes": entry["notes"],
                }
            )

    # 2) Perspektiven mit ihren Viewpoint-Paketen und -Sichten.
    viewpoint_packages: dict[str, str] = {}
    for perspektive, codes, _masc_name in PERSPEKTIVEN:
        persp_path = f"{arch}/{perspektive}"
        packages.append(
            {
                "path": persp_path,
                "notes": f"Perspektive {perspektive} (Leitfaden Abbildung 1).",
                "stereotype": _sicher_paket(rules, "ArchitecturalDescription"),
            }
        )
        for code in codes:
            viewpoint = viewpoints.get(code)
            if viewpoint is None:
                continue
            vp_name = str(viewpoint.get("name") or code)
            code_paths = _pakete_fuer_viewpoint(projekt, code)
            if not code_paths:
                code_paths = [f"{persp_path}/{_segment(code)}"]
            for vp_path in code_paths:
                packages.append({"path": vp_path, "notes": vp_name})
                viewpoint_packages.setdefault(code, vp_path)

    # 3) Inhalt aus Prosa einsortieren.
    inhalt_elemente, inhalt_kanten = _inhalt_einsortieren(inhalte, arch, paket_stereos=pkg_stereos)
    elements.extend(inhalt_elemente)
    connectors.extend(inhalt_kanten)


    # 3b) Pflichtelemente je Viewpoint, damit keine Sicht leer bleibt.
    #     Der Inhalt ist aus dem Regelwerk ableitbar (Viewpoints, Views,
    #     Concerns, Standards, Classifications) -- es wird nichts erfunden.
    elements.extend(_pflichtelemente(rules, viewpoints, projekt, arch_pfad=arch, startseite=startseite))
    elements = _ohne_doppelnamen(elements)

    # 3c) Mindestinhalt je Sicht, damit keine Sicht leer bleibt. Belegt aus
    #     den jeweiligen Konventionen (SICHT_INHALT); kein erfundener Inhalt.
    vorhandene_pakete_3c = {p["path"] for p in packages}
    for rule in leitfaden.DIAGRAMS:
        sicht_teil = rule.name.split(" : ")[-1].split(" (")[0]
        for (code, teil), eintraege in SICHT_INHALT.items():
            if rule.viewpoint != code or teil.casefold() not in sicht_teil.casefold():
                continue
            package = paket_fuer_diagramm(rule.package, projekt, vorhandene_pakete_3c)
            if package is None:
                continue
            for name, kandidaten, notes, konvention in eintraege:
                stereotype, ea_type = _stereotyp(rules, *kandidaten)
                if not stereotype:
                    continue
                elements.append(
                    {
                        "package": package,
                        "name": name,
                        "stereotype": stereotype,
                        "ea_type": ea_type,
                        "notes": f"{notes} (Konvention {konvention}).",
                    }
                )

    # 4) Pflichtsichten je Konvention.
    vorhandene_pakete = {p["path"] for p in packages}
    bereits: set[tuple[str, str]] = {
        (str(d.get("package") or ""), str(d.get("name") or "")) for d in diagrams
    }
    for rule in leitfaden.DIAGRAMS:
        name = leitfaden.expand_projekt(rule.name, projekt)
        target = paket_fuer_diagramm(rule.package, projekt, vorhandene_pakete)
        if target is None:
            continue
        if (target, name) in bereits:
            continue  # Startseite ist bereits oben angelegt (mit Auftragsbezug)
        bereits.add((target, name))
        members = _mitglieder(rule.viewpoint, elements, target, inhalt_elemente, max_elemente_je_sicht)
        diagrams.append(
            {
                "name": name,
                "package": target,
                "type": leitfaden.DIAGRAM_EA_TYPE,
                "mdg": _mdg_fuer_code(rule.viewpoint, viewpoints),
                "notes": f"{rule.code}: {rule.diagram_type}.",
                "members": members,
            }
        )

    # 5) Viewpoints und Views zentral -- A2-MK05/A2-MK17/A2-MK18.
    #    Der Leitfaden laesst zu, Viewpoints und Views "aus dem
    #    Modellelementekatalog zu entnehmen" statt sie je Sicht neu anzulegen.
    #    Sie stehen deshalb einmal unter Architecture Foundation/A2/Viewpoints;
    #    die Sichten verweisen per DiagramMembership darauf (St-MK05).
    vp_ablage = f"{arch}/Architecture Foundation/A2/Viewpoints"
    view_ablage = f"{vp_ablage}/Views"
    packages.append({"path": vp_ablage, "notes": "Viewpoints der Architektur (A2-MK15)."})
    packages.append({"path": view_ablage, "notes": "Views der Architektur (A2-MK18)."})
    mitglieder_startseite: list[dict[str, Any]] = []
    view_stereo = _sicher(rules, "Viewpoint")
    view_klammer = _sicher(rules, "View")
    for code in sorted(viewpoints, key=lambda item: (item.casefold(), item)):
        if not view_stereo:
            break  # Regelwerk kennt "Viewpoint" nicht -- nichts anlegen
        viewpoint = viewpoints[code]
        vp_name = str(viewpoint.get("name") or code)
        elements.append(
            {
                "package": vp_ablage,
                "name": vp_name,
                "stereotype": view_stereo,
                "ea_type": "Class",
                "notes": str(viewpoint.get("notes") or vp_name),
            }
        )
        mitglieder_startseite.append({"element": f"{vp_ablage}::{vp_name}"})
        # Je Viewpoint ein View-Element als Klammer um seine Sichten (A2-MK18).
        sichten = [d for d in diagrams if str(d.get("mdg") or "").endswith(vp_name)]
        if not sichten or not view_klammer:
            continue
        view_name = f"{code} : {projekt} : {vp_name.split(' - ')[-1]}"
        elements.append(
            {
                "package": view_ablage,
                "name": view_name,
                "stereotype": view_klammer,
                "ea_type": "Class",
                "notes": f"View des Viewpoints {vp_name} (A2-MK18).",
            }
        )
    # St-MK05: die Viewpoints stehen auf der Startseite -- als Verweis, nicht
    # als Kopie. Der Writer legt dasselbe Element auf beiden Sichten ab.
    if mit_startseite:
        for diagram in diagrams:
            if diagram.get("default"):
                diagram.setdefault("members", []).extend(mitglieder_startseite)
                break

    # 4b) Die zweite Architekturbeschreibung im Projekt: die PBN-Architektur
    #     (Leitfaden Abbildung 1, neben der Projektarchitektur).
    pbn = f"{projekt} - PBN-Architektur"
    packages.append(
        {
            "path": pbn,
            "stereotype": _sicher_paket(rules, "ArchitecturalDescription"),
            "notes": "PBN-Architektur (Leitfaden Abbildung 1).",
        }
    )

    # 5b) Achtung: ``ArchitecturalDescription`` ist im Regelwerk ein
    #     *Paket*-Stereotyp (Metaklasse Package), kein Element. Die
    #     Architekturbeschreibung ist deshalb das Paket ``<Projekt> -
    #     Projektarchitektur`` selbst -- es wird kein Element angelegt, das
    #     eine falsche Metaklasse traegt.

    # 6) Meta-Kanten: die Beziehungen, die aus einer Sammlung von Sichten eine
    #    pruefbare Architektur machen. Woertlich belegt:
    #      A2-MK06 STAKEHOLDERCONCERN      Stakeholder -> Concern
    #      A2-MK07 VIEWPOINTTOSTAKEHOLDER  Viewpoint   -> Stakeholder
    #      A2-MK20 CONCERNFORVIEWPOINT     Viewpoint   -> Concern
    #      A2-MK21 CONCERNFORVIEW          View         -> Concern
    #      A1-MK10 CONFORMSTO              ArchitectureDescription -> Standard
    #      A1-MK12 CLASSIFIED              ArchitectureDescription -> Classification
    connectors.extend(
        _meta_kanten(
            elements,
            arch_pfad=arch,
            vp_ablage=f"{arch}/Architecture Foundation/A2/Viewpoints",
            view_ablage=f"{arch}/Architecture Foundation/A2/Viewpoints/Views",
            rules=rules,
        )
    )

    # 6b) A2-MK17/MK18: die Sicht "A2 : <Projekt> : Viewpoints" zeigt die
    #     Viewpoints und Views selbst -- sie liegen zentral und werden hier
    #     nur referenziert.
    vp_refs = [f"{vp_ablage}::{e.get('name')}" for e in elements
               if str(e.get("package") or "") == vp_ablage and str(e.get("stereotype") or "") == view_stereo]
    view_refs = [f"{view_ablage}::{e.get('name')}" for e in elements
                 if str(e.get("package") or "") == view_ablage and str(e.get("stereotype") or "") == view_klammer]
    for diagram in diagrams:
        if diagram.get("name") == f"A2 : {projekt} : Viewpoints":
            diagram["members"] = [{"element": ref} for ref in (*vp_refs, *view_refs)]

    # 6b2) Pflichtstereotype je Viewpoint. Der Leitfaden nennt sie, die
    #      Model-Wizard-Vorlage zeigt sie. Ein Element wird wiederverwendet,
    #      wenn es schon im Modell liegt -- in EA steht ein Element in vielen
    #      Sichten, ohne kopiert zu werden. Sonst entsteht es im Paket der
    #      Sicht und wird als Geruestelement gekennzeichnet.
    nach_stereotyp: dict[str, list[dict[str, Any]]] = {}
    for element in elements:
        stereo = str(element.get("stereotype") or "")
        if stereo:
            nach_stereotyp.setdefault(stereo, []).append(element)
    vorhandene_refs_set = {
        f"{e.get('package')}::{e.get('name')}" for e in elements
    }
    for diagram in diagrams:
        code = str(diagram.get("name") or "").split(":")[0].strip()
        pflicht = leitfaden.PFLICHT_STEREOTYPE.get(code, ())
        if not pflicht:
            continue
        paket = str(diagram.get("package") or "")
        refs = {str(m.get("element") or "") for m in diagram.get("members") or ()}
        im_paket = {
            str(e.get("stereotype") or "")
            for e in elements
            if str(e.get("package") or "") == paket
        }
        for stereotype in pflicht:
            if stereotype == "Viewpoint" or stereotype == "View":
                continue  # zentral in A2/Viewpoints, siehe oben
            if stereotype in im_paket:
                continue
            kandidat = next(
                (e for e in nach_stereotyp.get(stereotype, ())
                 if str(e.get("package") or "") == paket),
                None,
            )
            if kandidat is None:
                kandidat = next(iter(nach_stereotyp.get(stereotype, ())), None)
            if kandidat is not None:
                ref = f"{kandidat.get('package')}::{kandidat.get('name')}"
                if ref not in refs:
                    diagram.setdefault("members", []).append({"element": ref})
                    refs.add(ref)
                continue
            stereo_name, ea_type = _stereotyp(rules, stereotype)
            if not stereo_name:
                continue
            name = GERUEST_NAME.get(stereotype, stereotype)
            elements.append(
                {
                    "package": paket,
                    "name": name,
                    "stereotype": stereo_name,
                    "ea_type": ea_type or "Class",
                    "notes": (
                        f"Geruestelement fuer {code}: der Leitfaden verlangt "
                        f"{stereotype} in diesem Viewpoint."
                    ),
                }
            )
            nach_stereotyp.setdefault(stereotype, []).append(elements[-1])
            im_paket.add(stereotype)
            ref = f"{paket}::{name}"
            if ref not in refs:
                diagram.setdefault("members", []).append({"element": ref})
                refs.add(ref)
                vorhandene_refs_set.add(ref)

    # 6c) Sichtinhalt sicherstellen. Eine Sicht ohne Element erfuellt ihren
    #     Zweck nicht (der Leitfaden-Pruefer meldet das zu Recht). Wo der
    #     Leitfaden Projektinhalt zulaesst, wird ein benanntes Geruestelement
    #     angelegt und als solches gekennzeichnet.
    vorhandene_namen = {
        (str(e.get("package") or ""), str(e.get("name") or ""))
        for e in elements
    }
    for diagram in diagrams:
        if diagram.get("members"):
            continue
        sicht = str(diagram.get("name") or "")
        teile = [teil.strip() for teil in sicht.split(":")]
        if len(teile) < 3:
            continue
        code, kurz = teile[0], teile[-1]
        eintrag = SICHT_GERUEST.get((code, kurz))
        if not eintrag:
            continue
        name, stereotype, konvention = eintrag
        stereotype, ea_type = _stereotyp(rules, stereotype)
        if not stereotype:
            continue
        paket = str(diagram.get("package") or "")
        if (paket, name) in vorhandene_namen:
            # Element existiert bereits in diesem Paket -- nur referenzieren.
            pass
        else:
            elements.append(
                {
                    "package": paket,
                    "name": name,
                    "stereotype": stereotype,
                    "ea_type": ea_type or "Class",
                    "notes": (
                        f"Geruestelement nach {konvention}. Traegt die Sicht, "
                        "bis echter Projektinhalt vorliegt."
                    ),
                }
            )
            vorhandene_namen.add((paket, name))
        diagram.setdefault("members", []).append({"element": f"{paket}::{name}"})

    # 7) Sichten nur auf Elemente zeigen lassen, die es gibt. Ein Verweis auf
    #    ein Element, das das Regelwerk nicht hergibt, macht den Export
    #    unmoeglich -- die Sicht bleibt dann eben leer (und der Pruefer meldet
    #    das als Warnung), statt auf einen toten Verweis zu zeigen.
    vorhandene_refs = {
        f"{e.get('package')}::{e.get('name')}"
        for e in elements
        if e.get("package") and e.get("name")
    }
    for diagram in diagrams:
        diagram["members"] = [
            member for member in (diagram.get("members") or ())
            if str(member.get("element") or "") in vorhandene_refs
        ]

    packages = _eltern_ergaenzen(packages)

    ir: dict[str, Any] = {
        "ir_version": extract.IR_VERSION,
        "packages": packages,
        "elements": elements,
        "connectors": connectors,
        "diagrams": diagrams,
        "meta": {
            "auftrag": {
                "projekt": projekt,
                "titel": auftrag.titel,
                "architekt": auftrag.architekt,
                "version": auftrag.version,
                "einstufung": auftrag.einstufung,
            },
            "architektur": {
                "backend": ARCH_BACKEND,
                "leitfaden": f"{leitfaden.LEITFADEN_VERSION} ({leitfaden.LEITFADEN_STAND})",
                "pakete": len(packages),
                "elemente": len(elements),
                "sichten": len(diagrams),
                "katalogStereotype": len(catalog),
                "inhaltsElemente": len(inhalt_elemente),
            },
        },
    }
    source = rules.get("source")
    if isinstance(source, Mapping):
        technology: dict[str, str] = {}
        if source.get("technologyId"):
            technology["profile"] = str(source["technologyId"])
        if source.get("technologyName"):
            technology["name"] = str(source["technologyName"])
        if source.get("technologyVersion"):
            technology["version"] = str(source["technologyVersion"])
        if technology:
            ir["technology"] = technology
    return ir


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------




#: Minimalinhalt je (Viewpoint-Code, Teil des Sichtnamens). Jeder Eintrag
#: nennt (Name, Stereotyp-Kandidaten, Notiz, Konvention). Der Stereotyp wird
#: gegen das Regelwerk aufgeloest; fehlt er dort, entfaellt der Eintrag --
#: es wird nichts erfunden.
SICHT_INHALT: dict[tuple[str, str], tuple[tuple[str, tuple[str, ...], str, str], ...]] = {
    ("L2", "Logical Scenario"): (
        ("Beispielszenario", ("OperationalActivity", "OperationalActivityAction"),
         "Ablauf eines Anwendungsfalls als Aktivitaet", "L2-MK05"),
    ),
    ("S1", "Service Variants"): (
        ("IT-Service Standardvariante", ("ServiceSpecification",),
         "Standardvariante eines IT-Service", "S1-MK12"),
    ),
    ("S2", "External Service Dependencies"): (
        ("Externer Service", ("ServiceSpecification",),
         "Dienst ausserhalb des Verantwortungsbereichs", "S2-MK06"),
    ),
    ("S2", "Service Warranties"): (
        ("Service-Warranty", ("ServiceSpecification",),
         "zugesagte Servicemerkmale", "S2-MK10"),
    ),
    ("S2", "Internal"): (
        ("Teildienst", ("ServiceSpecification",),
         "Dienst als Bestandteil einer Komposition", "S2-MK01"),
    ),
    ("P1", "Service Provision"): (
        ("Bereitgestellter Service", ("ServiceSpecification",),
         "durch die Ressource erbrachter Service", "P1-MK07"),
    ),
    ("P2", "Internal Dependencies"): (
        ("Interne Ressourcenabhaengigkeit", ("ResourcePort", "ResourceInterface"),
         "Abhaengigkeit zwischen zwei Ressourcen", "P2-MK07"),
    ),
    ("P2", "External Dependencies"): (
        ("Externe Ressource", ("ResourceArtifact", "System"),
         "Ressource ausserhalb des betrachteten Systems", "P2-MK12"),
    ),
    ("P2", "Node Realization"): (
        ("Realisierungsknoten", ("System", "ResourceArtifact"),
         "Knoten, auf dem die Ressource laeuft", "P2-MK20"),
    ),
    ("P2", "Application Hosting"): (
        ("Hosting-Plattform", ("System",),
         "Plattform, auf der die Anwendung gehostet wird", "P2-MK25"),
    ),
    ("A7", "Findings and Recommendations"): (
        ("Erkenntnis Modellierung", ("Finding",),
         "Erkenntnis zum Modell oder zur Methode", "A7-MK07"),
        ("Empfehlung Modellierung", ("Recommendation",),
         "Empfehlung zur Erkenntnis", "A7-MK07"),
    ),
    ("A7", "Compliance Statement"): (
        ("Konformitaetserklaerung", ("Recommendation", "Finding"),
         "Erklaerung zur Konformitaet der Architektur", "A7-MK17"),
    ),
}


def _ohne_doppelnamen(elements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Gleicher Name im gleichen Paket ist im IR mehrdeutig -- erster gewinnt.

    Die Startseite trägt bewusst dieselben Viewpoints wie die Perspektiven; die
    Startseite kommt zuerst, damit auf ihr die vollständige Liste steht.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for element in elements:
        key = (str(element.get("package") or ""), str(element.get("name") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(element))
    return out


def _pflichtelemente(
    rules: Mapping[str, Any],
    viewpoints: Mapping[str, Mapping[str, Any]],
    projekt: str,
    *,
    arch_pfad: str,
    startseite: str,
) -> list[dict[str, Any]]:
    """Die Elemente, die der Leitfaden je Viewpoint verlangt -- aus dem Regelwerk.

    Belegt aus dem Leitfaden:

    * St-MK05 -- Viewpoints stehen auf der Startseite (und in A2).
    * A8-MK01 ff. -- Standards kommen aus dem Standardelementekatalog.
    * VÜ-MK02 -- konkretisierte Elemente sind klassifiziert; A1-MK11 verlangt
      die Einstufung aus dem Katalog, A1-MK12 die CLASSIFIED-Kante.
    * A2-MK08 ff. -- Concerns als Analysebedarf.
    """
    out: list[dict[str, Any]] = []

    def add(package: str, name: str, stereotype: str, notes: str, ea_type: str = "Class") -> None:
        if not name:
            return
        out.append(
            {
                "package": package,
                "name": name,
                "stereotype": stereotype,
                "ea_type": ea_type,
                "notes": notes,
            }
        )

    # St-MK05: Viewpoints stehen auf der Startseite -- aber als Verweis auf das
    # zentrale Element in A2/Viewpoints (DiagramMembership), nicht als Kopie.

    # A2: Viewpoints-Sicht und Concerns-Sicht.
    a2_concerns = f"{arch_pfad}/Architecture Foundation/A2/Concerns"
    # Viewpoints selbst liegen zentral in A2/Viewpoints (siehe build_architektur);
    # hier bleibt nur der Verweis auf die Sicht, damit sie nicht doppelt entstehen.
    for code in sorted(viewpoints, key=lambda item: (item.casefold(), item)):
        group = str(viewpoints[code].get("group") or "").strip()
        if not group:
            continue
        if _sicher(rules, "Concern"):
            add(
                a2_concerns,
                f"Analysebedarf {group}",
                "Concern",
                f"Analysebedarf des Viewpoint-Bereichs {group}.",
            )

    # A1: Meta-Daten + Einstufung (A1-MK11/MK12).
    a1 = f"{arch_pfad}/Architecture Foundation/A1/Meta-Data Definitions"
    meta_stereo, meta_type = _stereotyp(rules, "ArchitectureMetadata", "Definition")
    if meta_stereo:
        add(a1, "Architektur-Metadaten", meta_stereo, "Metadaten der Architektur.", meta_type)

    # A8: Standards.
    a8 = f"{arch_pfad}/Architecture Foundation/A8/Standards"
    for name, notes in (
        ("NAFv4-ADMBw", "NATO Architecture Framework Version 4, ADMBw-Erweiterung."),
        ("UAF Domain Metamodel", "UAF DMM als Grundlage der ADMBw-Notation (Leitfaden 2.5)."),
    ):
        if _sicher(rules, "Standard"):
            add(a8, name, "Standard", notes)

    # A6: Version der Architektur.
    a6 = f"{arch_pfad}/Architecture Foundation/A6/Architecture Version"
    version_stereo, version_type = _stereotyp(rules, "VersionOfConfiguration", "ArchitectureMetadata")
    if version_stereo:
        add(a6, f"{projekt} v1.0", version_stereo, "Freigegebene Version der Architektur.", version_type)

    # Katalog: Einstufungen (OFFEN als Standard, Leitfaden L7-MK05).
    katalog = f"{arch_pfad}/{MODEL_CATALOG}"
    for stufe in (("OFFEN", "VS-NUR FÜR DEN DIENSTGEBRAUCH", "VS-VERTRAULICH", "GEHEIM")
                  if _sicher(rules, "Classification") else ()):
        add(
            f"{katalog}/Classification",
            stufe,
            "Classification",
            f"Einstufung nach VS-Richtlinie: {stufe}.",
        )
    return out



def _meta_kanten(
    elements: Sequence[Mapping[str, Any]],
    *,
    arch_pfad: str,
    vp_ablage: str,
    view_ablage: str,
    rules: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Die Meta-Kanten der A2- und A1-Konventionen aus vorhandenen Elementen.

    Es wird nichts erfunden: die Kante entsteht nur, wenn beide Enden im Modell
    liegen und der Stereotyp im Regelwerk existiert. Fehlt ein Ende, entfaellt
    die Kante -- sie wird nicht durch ein Platzhalterelement erzwungen.
    """
    def vorhanden(stereotype: str) -> bool:
        # Kanten-Stereotype stehen im Regelwerk unter "connectors", nicht unter
        # "elementStereotypes" -- ein Element-Stereotyp gleichen Namens gibt es
        # fuer ConformsTo, Classified und die A2-Kanten nicht.
        return any(
            str(c.get("stereotype") or "") == stereotype
            for c in rules.get("connectorRules") or ()
        )

    def refs(paket: str, stereotype: str) -> list[str]:
        out = []
        for element in elements:
            if str(element.get("package") or "") != paket:
                continue
            if str(element.get("stereotype") or "") != stereotype:
                continue
            out.append(f"{paket}::{element.get('name')}")
        return out

    def kante(source: str, target: str, stereotype: str, code: str) -> dict[str, Any]:
        return {
            "source": source,
            "target": target,
            "stereotype": stereotype,
            "notes": f"Konvention {code}.",
        }

    kanten: list[dict[str, Any]] = []
    arch_paket = arch_pfad

    # A1-MK10 (CONFORMSTO) und A1-MK12 (CLASSIFIED) brauchen ein
    # Element als Ausgangspunkt: die Architekturbeschreibung ist im Regelwerk
    # aber ein Paket-Stereotyp. Solange kein Element mit
    # "ArchitecturalDescription" im Modell liegt, werden die Kanten nicht
    # erzeugt -- sie stehen als Finding im Struktur-Prüfer, statt auf ein
    # erfundenes Element zu zeigen.

    # A2: Viewpoints <-> Stakeholder, Viewpoints/Views <-> Concerns.
    viewpoints = refs(vp_ablage, "Viewpoint")
    views = refs(view_ablage, "View")
    concerns = refs(f"{arch_pfad}/Architecture Foundation/A2/Concerns", "Concern")
    stakeholder = refs(f"{arch_pfad}/Architecture Foundation/A2 - Stakeholder", "ActualPost")
    stakeholder += refs(f"{arch_pfad}/Architecture Foundation/A2 - Stakeholder", "ActualOrganization")
    stakeholder += refs(f"{arch_pfad}/Architecture Foundation/A2 - Stakeholder", "ActualPerson")

    def gruppe(ref: str) -> str:
        """Viewpoint-Code aus dem Elementnamen (z. B. "A2 : ... : Concerns").

        Die Zuordnung Viewpoint/View <-> Concern erfolgt ueber den
        Viewpoint-Bereich: der Leitfaden adressiert je Concern den Bereich,
        nicht die Kreuzproduktmenge aller Concerns. Eine Kante fuer jede
        Kombination waere erfunden.
        """
        name = str(ref).split("::")[-1]
        teil = name.split(" ")[0].rstrip(":")
        return teil if teil and teil[:1].isalpha() else ""

    # Concern-Namen beginnen mit "Analysebedarf <Gruppe>"; die Gruppe ist der
    # Viewpoint-Bereich (z. B. "Architecture Foundation").
    concern_gruppe: dict[str, str] = {}
    for element in elements:
        if str(element.get("stereotype") or "") != "Concern":
            continue
        name = str(element.get("name") or "")
        if not name.startswith("Analysebedarf "):
            continue
        concern_gruppe[f"{element.get('package')}::{name}"] = name[len("Analysebedarf "):].strip()

    # Viewpoint-Code -> Perspektive (aus dem Leitfaden-Regelmodell).
    familie: dict[str, str] = {}
    for rule in leitfaden.PACKAGES:
        if rule.family and rule.viewpoint not in familie:
            familie[rule.viewpoint] = rule.family

    if vorhanden("ViewpointToStakeholder"):
        for vp in viewpoints:
            for st in stakeholder:
                kanten.append(kante(vp, st, "ViewpointToStakeholder", "A2-MK07"))
    if vorhanden("ConcernForViewpoint"):
        for vp in viewpoints:
            bereich_vp = familie.get(gruppe(vp), "")
            for concern, bereich in concern_gruppe.items():
                if bereich_vp and bereich and bereich_vp.casefold() != bereich.casefold():
                    continue
                kanten.append(kante(vp, concern, "ConcernForViewpoint", "A2-MK20"))
    if vorhanden("ConcernForView"):
        for view in views:
            bereich_view = familie.get(gruppe(view), "")
            for concern, bereich in concern_gruppe.items():
                if bereich_view and bereich and bereich_view.casefold() != bereich.casefold():
                    continue
                kanten.append(kante(view, concern, "ConcernForView", "A2-MK21"))
    return kanten


def _package_exists(elements: Sequence[Mapping[str, Any]], path: str) -> bool:
    return any(str(e.get("package") or "") == path for e in elements)


def _arch_name(elements: Sequence[Mapping[str, Any]], arch_pfad: str) -> str:
    for element in elements:
        if str(element.get("package") or "") == arch_pfad:
            return str(element.get("name") or "")
    return arch_pfad.split("/")[-1]


def _eltern_ergaenzen(packages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Jeden Zwischenpfad deklarieren (IR-Regel: Eltern muessen existieren).

    Der Leitfaden nennt nur die Blattpakete. Ein Paket "A/B/C" ohne "A/B" ist
    im IR ein Fehler -- hier werden die fehlenden Ebenen ergaenzt, statt den
    Aufrufer damit zu belasten.
    """
    by_path: dict[str, dict[str, Any]] = {}
    for package in packages:
        path = str(package.get("path") or "")
        if not path:
            continue
        by_path.setdefault(path, dict(package))
    for path in list(by_path):
        parts = path.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            by_path.setdefault(parent, {"path": parent, "notes": ""})
    return [by_path[path] for path in sorted(by_path)]



def _stereotyp(rules: Mapping[str, Any], *kandidaten: str) -> tuple[str, str]:
    """Ersten vorhandenen Stereotyp nehmen und seine Metaklasse mitliefern.

    Ein Element mit falscher Metaklasse ist ein Prueffund (der Validator
    meldet ``elementMetaclassMismatch``): ``OperationalActivity`` ist eine
    ``Activity``, ``VersionOfConfiguration`` ein ``Part``. Deshalb kommt der
    ea_type aus dem Regelwerk, nicht aus einer Annahme.
    """
    for kandidat in kandidaten:
        if _stereotype_existiert(rules, kandidat):
            for entry in rules.get("elementStereotypes") or ():
                if str(entry.get("name") or "") == kandidat:
                    metaclasses = [
                        str(m) for m in entry.get("metaclasses") or ()
                        if str(m).strip() and str(m).lower() != "package"
                    ]
                    return kandidat, (metaclasses[0] if metaclasses else "Class")
    return "", ""



# Sichten, deren Inhalt aus dem Projekt kommt (nicht zwingend aus dem
# Standardelementekatalog): je Sicht ein benanntes Geruestelement, damit die
# Sicht ihre Aufgabe erfuellen kann. Der Beleg steht als Konventions-ID dabei.
# Sichten, deren Inhalt der Leitfaden ausdruecklich NUR aus dem StEKa zulaesst
# (C1-MK03/MK05/MK07/MK09, Cr-MK03), bleiben ohne Platzhalter -- dort waere
# ein erfundenes Element ein Verstoss gegen die Konvention.
SICHT_GERUEST: dict[tuple[str, str], tuple[str, str, str]] = {
    ("A2", "Stakeholder"): ("Fachverantwortlicher", "ActualPost", "A2-MK03"),
    ("A2", "Architecture Products"): ("Fachverantwortlicher", "ActualPost", "A2-MK03"),
    ("A7", "Architecture Compliance"): ("Compliance Statement", "Information", "A7-MK19"),
    ("L1", "Node Types"): ("Logischer Aufgabentraeger", "OperationalPerformer", "L1-MK03"),
    ("L2", "Logical Nodes"): ("Logischer Knoten", "OperationalPerformer", "L2-MK03"),
    ("L2", "Logical Scenario"): ("Anwendungsfall", "OperationalArchitecture", "L2-MK06"),
    ("L3", "Node Interaction"): ("Anwendungsfall", "OperationalArchitecture", "L3-MK03"),
    ("L4", "Hierarchie"): ("Aktivitaet", "OperationalActivity", "L4-MK03"),
    ("L7", "Information Model"): ("Informationselement", "InformationElement", "L7-MK03"),
    ("L8", "Logical Constraints"): ("Rahmenbedingung", "DocumentReference", "L8-MK03"),
    ("S3", "Service Interfaces"): ("Service", "ServiceSpecification", "S3-MK03"),
    ("S4", "Service Functions"): ("Service", "ServiceSpecification", "S4-MK03"),
    ("S7", "Service Interface Parameters"): ("Serviceschnittstelle", "ServiceInterface", "S7-MK03"),
    ("Sr", "Service Change"): ("Aenderungsbedarf", "Change", "Sr-MK04"),
    ("P1", "Resource Types"): ("Ressource", "System", "P1-MK03"),
    ("P2", "Resource Structure"): ("Ressource", "System", "P2-MK04"),
    ("P8", "Resource Constraint"): ("Implementierungsvorgabe", "ResourceConstraint", "P8-MK03"),
    ("R2", "Requirement Catalogue"): ("Forderungskatalog", "RequirementCatalogue", "R2-MK03"),
    ("R3", "Requirements Dependencies"): ("Forderung", "FunctionalRequirement", "R3-MK03"),
    ("R7", "Requirements Derivation"): ("Forderung", "FunctionalRequirement", "R7-MK03"),
}

#: Sprechende Namen fuer Geruestelemente, die der Bau anlegen muss, weil der
#: Viewpoint sie verlangt. Fehlt ein Eintrag, traegt das Element den
#: Stereotypnamen -- das ist eindeutig, wenn auch technisch.
GERUEST_NAME: dict[str, str] = {
    "Classification": "Einstufung",
    "Capability": "Faehigkeit",
    "Concern": "Analysebedarf",
    "DataElement": "Datenelement",
    "DocumentReference": "Dokumentreferenz",
    "InformationElement": "Informationselement",
    "Location": "Standort",
    "MeasurementType": "Messgroesse",
    "OperationalArchitecture": "Anwendungsfall",
    "OperationalConstraint": "Operationelle Vorgabe",
    "OperationalPerformer": "Logischer Aufgabentraeger",
    "Reference": "Referenz",
    "RequirementCatalogue": "Forderungskatalog",
    "RequirementCategory": "Forderungskategorie",
    "ResourceConstraint": "Implementierungsvorgabe",
    "SMEReference": "SME-Referenz",
    "ServiceInterface": "Serviceschnittstelle",
    "ServicePort": "Serviceport",
    "ServiceSpecification": "Service",
    "Standard": "Standard",
    "StrategicConstraint": "Strategische Vorgabe",
    "View": "View",
    "Viewpoint": "Viewpoint",
}


def _sicher(rules: Mapping[str, Any], stereotype: str) -> str:
    """Stereotyp nur zurueckgeben, wenn das Regelwerk ihn kennt -- sonst "".

    Ein Modell, das Stereotype aus einem fremden Profil enthaelt, faellt bei
    der MDG-Pruefung durch (``unknownElementStereotype``). Deshalb wird jede
    Erzeugung abgesichert, statt sich auf das ADMBw-Profil zu verlassen.
    """
    return stereotype if _stereotype_existiert(rules, stereotype) else ""


def _sicher_paket(rules: Mapping[str, Any], stereotype: str) -> str:
    """Wie ``_sicher``, aber fuer Paket-Stereotype.

    Paket-Stereotype stehen im Regelwerk unter ``elementStereotypes`` mit der
    Metaklasse ``Package``; die Existenz wird dort geprueft.
    """
    for entry in rules.get("elementStereotypes") or ():
        if str(entry.get("name") or "") != stereotype:
            continue
        if any(str(m).lower() == "package" for m in entry.get("metaclasses") or ()):
            return stereotype
    return ""


def _stereotype_existiert(rules: Mapping[str, Any], name: str) -> bool:
    return any(str(e.get("name") or "") == name for e in rules.get("elementStereotypes") or ())


def _auftrag_note(auftrag: Auftrag) -> str:
    teile = [f"Architekturauftrag für {auftrag.projekt}."]
    if auftrag.titel:
        teile.append(f"Titel: {auftrag.titel}.")
    if auftrag.architekt:
        teile.append(f"Architekt: {auftrag.architekt}.")
    if auftrag.phase:
        teile.append(f"Phase: {auftrag.phase}.")
    teile.append(f"Version {auftrag.version}.")
    if auftrag.einstufung:
        teile.append(f"Einstufung: {auftrag.einstufung}.")
    return " ".join(teile)


def _startseite_mdg(viewpoints: Mapping[str, Mapping[str, Any]]) -> str:
    for code in ("A2", "C1"):
        viewpoint = viewpoints.get(code)
        if viewpoint:
            return _mdg_viewpoint(viewpoint)
    return ""


def _mdg_fuer_code(code: str, viewpoints: Mapping[str, Mapping[str, Any]]) -> str:
    viewpoint = viewpoints.get(code)
    return _mdg_viewpoint(viewpoint) if viewpoint else ""


def _pakete_fuer_viewpoint(projekt: str, code: str) -> list[str]:
    """Alle Leitfaden-Pakete, die zu diesem Viewpoint gehören (ohne Dopplung)."""
    out: list[str] = []
    for rule in leitfaden.PACKAGES:
        if rule.viewpoint != code:
            continue
        path = f"{projekt} - Projektarchitektur/" + leitfaden.expand_projekt(rule.path, projekt)
        if path not in out:
            out.append(path)
    return out


def paket_fuer_diagramm(leitfaden_package: str, projekt: str, vorhanden: Iterable[str]) -> str | None:
    """Paketpfad eines Leitfaden-Diagramms auf das Modell abbilden.

    Der Leitfaden nennt Pakete ohne Projektwurzel (z. B.
    ``Architecture Foundation/A1/Meta-Data Definitions``). Im Modell liegen
    sie unter ``<Projekt> - Projektarchitektur/...``.
    """
    wanted = leitfaden.expand_projekt(leitfaden_package, projekt)
    if wanted.startswith(projekt):
        return wanted if wanted in set(vorhanden) else None
    for candidate in (f"{projekt} - Projektarchitektur/{wanted}", wanted):
        if candidate in set(vorhanden):
            return candidate
    return None


def _mitglieder(
    code: str,
    elements: Sequence[Mapping[str, Any]],
    package: str,
    inhalt_elemente: Sequence[Mapping[str, Any]],
    limit: int,
) -> list[dict[str, str]]:
    """Elemente einer Sicht: erst Projektinhalt, dann Pflichtelemente des Pakets.

    Layout: feste Spalten, Zeilenabstand 110 -- deterministisch, damit zwei
    Läufe dieselbe Datei ergeben. Feineinstellung bleibt Handarbeit in EA.
    """
    nach_paket: dict[str, list[str]] = {}
    for element in elements:
        nach_paket.setdefault(str(element.get("package") or ""), []).append(str(element.get("name") or ""))
    # Projektinhalt zuerst: Er liegt in der Perspektive (z. B. <AD>/Concepts),
    # die Sicht aber im Viewpoint-Paket darunter. Deshalb ueber den Stereotyp
    # zuordnen, nicht ueber den Paketpfad -- sonst bleibt jede Sicht leer.
    pflicht = set(leitfaden.PFLICHT_STEREOTYPE.get(code, ()))
    priorität: list[str] = []
    if pflicht:
        for element in inhalt_elemente:
            if str(element.get("stereotype") or "") not in pflicht:
                continue
            pkg = str(element.get("package") or "")
            name = str(element.get("name") or "")
            if pkg and name:
                priorität.append(f"{pkg}::{name}")
    inhalt_pakete = {str(e.get("package") or "") for e in inhalt_elemente}
    for pkg in sorted(nach_paket):
        if not pkg.startswith(package):
            continue
        for name in sorted(nach_paket[pkg]):
            if pkg in inhalt_pakete:
                priorität.append(f"{pkg}::{name}")
    for pkg in sorted(nach_paket):
        if not pkg.startswith(package):
            continue
        for name in sorted(nach_paket[pkg]):
            ref = f"{pkg}::{name}"
            if ref not in priorität:
                priorität.append(ref)
    members: list[dict[str, Any]] = []
    for position, ref in enumerate(priorität[:limit]):
        column = position % 4
        row = position // 4
        left = column * 260
        top = row * 110
        members.append(
            {
                "element": ref,
                "left": left,
                "top": top,
                "right": left + 220,
                "bottom": top + 70,
                "sequence": position,
            }
        )
    return members


def _inhalt_einsortieren(
    inhalte: Mapping[str, Any] | None,
    arch_pfad: str,
    *,
    paket_stereos: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Belegte Inhalte in die Perspektiven einsortieren.

    Jedes Element behält seinen Namen, Stereotyp und seine Notiz. Verschoben
    wird nur das *Paket*: ``<projekt> - Projektarchitektur/<Perspektive>``.
    Für Elemente mit Paketstereotyp (ArchitecturalDescription) bleibt das
    Element am Perspektivpaket; EA erlaubt es dort ohnehin.
    """
    if not inhalte:
        return [], []
    elements: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for entry in inhalte.get("elements") or ():
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name") or "").strip()
        stereotype = str(entry.get("stereotype") or "").strip()
        if not name:
            continue
        perspektive = _perspektive_fuer(stereotype)
        package = f"{arch_pfad}/{perspektive}"
        elements.append(
            {
                "package": package,
                "name": name,
                "stereotype": stereotype,
                "ea_type": str(entry.get("ea_type") or "Class"),
                "notes": str(entry.get("notes") or "").strip()
                or f"{name} ({stereotype}) -- aus der Quelle übernommen.",
                "tags": dict(entry.get("tags") or {}),
            }
        )
        mapping[name] = package
    connectors: list[dict[str, Any]] = []
    for entry in inhalte.get("connectors") or ():
        if not isinstance(entry, Mapping):
            continue
        source = str(entry.get("source") or "")
        target = str(entry.get("target") or "")
        def ref(value: str) -> str | None:
            name = value.split("::")[-1]
            package = mapping.get(name)
            return f"{package}::{name}" if package else None
        s, t = ref(source), ref(target)
        if not s or not t:
            continue
        connectors.append(
            {
                "source": s,
                "target": t,
                "stereotype": str(entry.get("stereotype") or ""),
                "ea_type": str(entry.get("ea_type") or "Dependency"),
                "name": "",
                "direction": str(entry.get("direction") or "Source -> Destination"),
                "notes": str(entry.get("notes") or ""),
                "tags": dict(entry.get("tags") or {}),
            }
        )
    return elements, connectors
