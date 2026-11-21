"""wizard.py -- Modellvorlagen des Model Wizard als Pruefmassstab.

Quelle
------
Die 52 Viewpoint-Vorlagen, die das BAAINBw zusammen mit dem ADMBw
veroeffentlicht (``knowledge/modelwizard``, XMI 1.1 / UML 1.3, EA-Export).
Je Viewpoint ein XML-Modellmuster und eine RTF-Dokumentvorlage.

Wozu
----
Die Vorlagen sind die *offizielle Soll-Struktur je Sicht*: sie zeigen, welche
Pakete, Modellierungselemente, Stereotype und Beziehungen ein Viewpoint
enthaelt. Der Leitfaden sagt, wie die Architektur als Ganzes aussehen muss --
die Vorlagen sagen es je Sicht.

Was hier geprueft wird
----------------------
Nur der Elementbestand je Viewpoint (Stereotype) und das Vorhandensein von
Paket und Sicht. Kein Namensvergleich: die Vorlagen enthalten MASC-Beispiel-
inhalte ("Raumschiff", "Aufklaerungselement Weltraum"), die fuer ein anderes
Projekt nicht gelten.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class Vorlage:
    """Eine Viewpoint-Vorlage aus dem Model Wizard."""

    name: str
    packages: tuple[str, ...]
    elemente: tuple[tuple[str, str, str], ...]  # (name, stereotype, ea_type)
    assoziationen: int
    diagramme: tuple[str, ...]
    rtf: bool
    #: (Stereotyp der Beziehung, Stereotyp der Quelle, Stereotyp des Ziels)
    beziehungen: tuple[tuple[str, str, str], ...] = ()

    @property
    def stereotype(self) -> tuple[str, ...]:
        """Die im Muster verwendeten Stereotype, ohne Beispielinhalte."""
        return tuple(sorted({s for _, s, _ in self.elemente if s}))


_CLASS = re.compile(
    r'<UML:Class name="(?P<name>[^"]*)"[^>]*?xmi\.id="[^"]*"[^>]*?>(?P<body>.*?)</UML:Class>',
    re.S,
)
_CLASS_EMPTY = re.compile(r'<UML:Class name="([^"]*)"[^>]*?/>')
_PACKAGE = re.compile(r'<UML:Package name="([^"]*)"')
_DIAGRAM = re.compile(r'<UML:Diagram name="([^"]*)"')
_ASSOC = re.compile(r'<UML:Association ')
_STEREO = re.compile(r'<UML:Stereotype name="([^"]*)"')
_KNOTEN_TAG = re.compile(
    r"<UML:(?P<tag>[A-Za-z_][A-Za-z0-9_.]*)\b(?P<attrs>(?:[^>\"]|\"[^\"]*\")*?)(?P<slash>/?)>",
    re.S,
)
_CLASS_TAG = re.compile(r"<UML:Class\b(?P<attrs>[^>]*?)(?P<slash>/?)>", re.S)
_ASSOC_BLOCK = re.compile(r"<UML:Association\b.*?</UML:Association>", re.S)
_ASSOC_ENDE = re.compile(r"<UML:AssociationEnd\b[^>]*?type=\"([^\"]*)\"")
_XMI_ID = re.compile(r'xmi\.id="([^"]+)"')
_STYPE = re.compile(r'tag="ea_stype" value="([^"]*)"')
_PKGNAME = re.compile(r'tag="package_name" value="([^"]*)"')


#: Elemente, die keine Modellknoten sind und deshalb nicht in die Zuordnung
#: Kennung -> Stereotyp gehoeren.
KEINE_KNOTEN = frozenset(
    {
        "Association",
        "AssociationEnd",
        "AssociationClass",
        "Diagram",
        "DiagramElement",
        "DiagramLink",
        "Event",
        "Model",
        "ModelElement",
        "Namespace",
        "Package",
        "Stereotype",
        "TaggedValue",
    }
)


def _stereotyp_nach_kennung(raw: str) -> dict[str, str]:
    """Kennung -> Stereotyp fuer alle Modellknoten einer Vorlage.

    Assoziationsenden nennen nur die Kennung ihres Gegenuebers. Die Gegenstelle
    ist in diesen Vorlagen selten eine Klasse -- BPMN-Sichten bestehen aus
    ActionState, Transition, ClassifierRole. Deshalb wird jeder Knoten
    aufgenommen, nicht nur ``UML:Class``.
    """
    out: dict[str, str] = {}
    for treffer in _KNOTEN_TAG.finditer(raw):
        tag = treffer.group("tag")
        if tag in KEINE_KNOTEN or tag.startswith("ModelElement."):
            continue
        kennung = _XMI_ID.search(treffer.group("attrs"))
        if not kennung:
            continue
        if treffer.group("slash") == "/":
            out[kennung.group(1)] = ""
            continue
        ende = raw.find(f"</UML:{tag}>", treffer.end())
        rumpf = raw[treffer.end() : ende if ende > 0 else treffer.end()]
        stereo = _STEREO.search(rumpf)
        out[kennung.group(1)] = stereo.group(1) if stereo else ""
    return out


def parse_vorlage(xml_path: str | Path) -> Vorlage:
    """Eine Vorlage lesen. Fehlende Dateien sind ein Fehler, kein leeres Ergebnis."""
    source = Path(xml_path)
    raw = source.read_bytes().decode("windows-1252", errors="replace")
    elemente: list[tuple[str, str, str]] = []
    for treffer in _CLASS.finditer(raw):
        name = treffer.group("name")
        if name == "EARootClass":
            continue  # technische EA-Wurzel, kein Modellelement
        body = treffer.group("body")
        stereo = _STEREO.search(body)
        stype = _STYPE.search(body)
        paket = _PKGNAME.search(body)
        if paket is None and not _DIAGRAM.search(body):
            # Klassen ohne Paketangabe sind Diagrammrahmen (z. B. "C3").
            continue
        elemente.append(
            (
                name,
                stereo.group(1) if stereo else "",
                stype.group(1) if stype else "Class",
            )
        )
    # Welche Stereotype verbinden die Assoziationen? Dafuer wird die Kennung
    # jedes Klassenblocks aufgeloest; die Enden nennen nur die Kennung.
    nach_kennung = _stereotyp_nach_kennung(raw)

    beziehungen: list[tuple[str, str, str]] = []
    for block in _ASSOC_BLOCK.findall(raw):
        stereo = _STEREO.search(block)
        enden = _ASSOC_ENDE.findall(block)
        if len(enden) < 2:
            continue
        beziehungen.append(
            (
                stereo.group(1) if stereo else "",
                nach_kennung.get(enden[0], ""),
                nach_kennung.get(enden[1], ""),
            )
        )

    rtf = source.with_suffix(".rtf")
    return Vorlage(
        name=source.stem,
        packages=tuple(dict.fromkeys(_PACKAGE.findall(raw))),
        elemente=tuple(elemente),
        assoziationen=len(_ASSOC.findall(raw)),
        diagramme=tuple(_DIAGRAM.findall(raw)),
        rtf=rtf.is_file(),
        beziehungen=tuple(sorted(set(beziehungen))),
    )


def lade_alle(verzeichnis: str | Path) -> dict[str, Vorlage]:
    """Alle Vorlagen eines Verzeichnisses, Schluessel ist der Viewpoint-Name."""
    base = Path(verzeichnis)
    if not base.is_dir():
        raise FileNotFoundError(f"Vorlagenverzeichnis fehlt: {base}")
    out: dict[str, Vorlage] = {}
    for pfad in sorted(base.glob("*.xml")):
        vorlage = parse_vorlage(pfad)
        out[vorlage.name] = vorlage
    return out


@dataclass
class Befund:
    """Eine Abweichung zwischen Bau und Vorlage."""

    viewpoint: str
    art: str
    severity: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "viewpoint": self.viewpoint,
            "art": self.art,
            "severity": self.severity,
            "message": self.message,
        }


def _viewpoint_code(name: str) -> str:
    return name.split(" ")[0].strip()


def vergleiche(
    modell: Mapping[str, Any],
    vorlagen: Mapping[str, Vorlage],
    *,
    geltungsbereich: Iterable[str] | None = None,
    pflichtstereotype: Mapping[str, Iterable[str]] | None = None,
) -> list[Befund]:
    """Bau gegen die Vorlagen halten -- je Viewpoint.

    Geprueft wird:
    * existiert ein Paket, das den Viewpoint traegt,
    * existiert eine Sicht mit dem Viewpoint-Kuerzel,
    * welche Stereotype nutzt die Vorlage, die im Bau fehlen.

    ``geltungsbereich`` grenzt ein, welche Viewpoints ueberhaupt Pflicht sind.
    Der Model Wizard deckt alle 52 ADMBw-Viewpoints ab; der Leitfaden fuer
    FFFmLV nur 26 davon. Ein fehlender Viewpoint ausserhalb des Geltungs-
    bereichs ist kein Fehler, sondern eine Information.

    Nicht geprueft wird der Beispielinhalt: die Vorlagen sind MASC-Muster.
    ``pflichtstereotype`` schneidet die Beispielinhalte weg: nur Stereotype,
    die der Leitfaden fuer den Viewpoint nennt *und* die in der Vorlage
    vorkommen, gelten als Pflicht. Ohne diese Angabe wird der gesamte
    Elementbestand der Vorlage verglichen -- das erzeugt Fehlalarme, weil die
    Muster konkrete Projektinhalte enthalten.
    """
    bereich = {str(c) for c in geltungsbereich} if geltungsbereich else None
    pflicht_map = {
        str(code): {str(s) for s in werte}
        for code, werte in (pflichtstereotype or {}).items()
    }
    befund: list[Befund] = []

    pakete = [str(p.get("path") or "") for p in modell.get("packages") or ()]
    elemente = [
        {
            "package": str(e.get("package") or ""),
            "name": str(e.get("name") or ""),
            "stereotype": str(e.get("stereotype") or ""),
        }
        for e in modell.get("elements") or ()
    ]
    sichten = [str(d.get("name") or "") for d in modell.get("diagrams") or ()]

    # Welche Elemente zeigt eine Sicht? In EA steht ein Element in vielen
    # Sichten, ohne kopiert zu werden -- fuer den Abgleich zaehlt, was auf der
    # Sicht liegt, nicht nur was im Paket liegt.
    nach_ref: dict[str, str] = {}
    for element in elemente:
        nach_ref[f"{element['package']}::{element['name']}"] = element["stereotype"]
    sicht_elemente: dict[str, set[str]] = {}
    for diagram in modell.get("diagrams") or ():
        code = str(diagram.get("name") or "").split(":")[0].strip()
        menge = sicht_elemente.setdefault(code, set())
        # Zwei Quellen: das IR liefert die Mitglieder als Objekte, die
        # geschriebene .qea liefert sie als "paket::name" (member_refs) und
        # daneben nur die Anzahl.
        roh = diagram.get("member_refs")
        if not roh:
            roh = diagram.get("members")
        if not isinstance(roh, (list, tuple)):
            roh = ()
        for mitglied in roh:
            if isinstance(mitglied, dict):
                ref = str(mitglied.get("element") or "")
            else:
                ref = str(mitglied)
            stereo = nach_ref.get(ref)
            if stereo:
                menge.add(stereo)

    for name, vorlage in sorted(vorlagen.items()):
        code = _viewpoint_code(name)
        if not code:
            continue
        # Paket: der Viewpoint-Code steht als Pfadsegment im Bau.
        pflicht = bereich is None or code in bereich
        stufe = "error" if pflicht else "info"
        hat_paket = any(
            f"/{code}/" in f"/{pfad.strip('/')}/" for pfad in pakete
        )
        if not hat_paket:
            befund.append(
                Befund(
                    name,
                    "package",
                    stufe,
                    ("Kein Paket fuer Viewpoint " if pflicht else "Ausserhalb des "
                     "Leitfaden-Geltungsbereichs, kein Paket: ") + code,
                )
            )
        hat_sicht = any(s.split(":")[0].strip() == code for s in sichten)
        if not hat_sicht:
            befund.append(
                Befund(
                    name,
                    "diagram",
                    stufe,
                    ("Keine Sicht fuer Viewpoint " if pflicht else "Ausserhalb des "
                     "Leitfaden-Geltungsbereichs, keine Sicht: ") + code,
                )
            )
        # Stereotype: was die Vorlage nutzt, muss der Bau kennen.
        im_bau = {
            e["stereotype"]
            for e in elemente
            if f"/{code}/" in f"/{e['package'].strip('/')}/"
        } | sicht_elemente.get(code, set())
        if pflichtstereotype is None:
            # Ohne Pflichtliste gilt der gesamte Elementbestand der Vorlage --
            # brauchbar fuer eine reine Bestandsaufnahme, nicht fuer eine
            # Freigabe (die Muster enthalten Beispielinhalte).
            gefordert = set(vorlage.stereotype)
        else:
            gefordert = pflicht_map.get(code, set()) & set(vorlage.stereotype)
        fehlend = sorted(gefordert - im_bau)
        if fehlend and hat_paket and pflicht:
            befund.append(
                Befund(
                    name,
                    "stereotype",
                    "warning",
                    "Stereotype der Vorlage fehlen im Bau: " + ", ".join(fehlend),
                )
            )
    return befund


def bericht(befunde: Iterable[Befund]) -> str:
    """Kurzfassung fuer die Konsole."""
    liste = list(befunde)
    if not liste:
        return "Model-Wizard-Abgleich: keine Abweichungen."
    fehler = sum(1 for b in liste if b.severity == "error")
    warnungen = sum(1 for b in liste if b.severity == "warning")
    infos = sum(1 for b in liste if b.severity == "info")
    zeilen = [
        f"Model-Wizard-Abgleich: {fehler} Fehler, {warnungen} Warnungen, "
        f"{infos} ausserhalb des Geltungsbereichs"
    ]
    for b in liste:
        if b.severity == "info":
            continue
        zeilen.append(f"  {b.severity:7s} {b.viewpoint:42s} {b.message}")
    return "\n".join(zeilen)
