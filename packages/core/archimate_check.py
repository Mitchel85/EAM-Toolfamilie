"""archimate_check.py -- ArchiMate-Modelle lesen, verstehen, beurteilen.

Der Werkzeugpfad der AI-Suite fuer das Austauschformat: **lesen ->
zusammenfassen -> pruefen**. Ein Modell (Model Exchange XML, IR-JSON oder
``.qea``) wird zu einer Zusammenfassung und einem Qualitaetsbefund. Beides ist
deterministisch, in der Sprache der Suite und ohne erfundenes Modellwissen --
die Grundlage fuer jede Antwort der KI ueber ein Modell.

Was geprueft wird
-----------------
* **Offene Referenzen** -- eine Beziehung zeigt auf ein Element, das im Modell
  nicht existiert. Die Kante behauptet eine Aussage, ihr Ende fehlt.
* **Matrixverstoesse** -- die Beziehungsart ist fuer das Paar aus Quell- und
  Zielkonzept nicht erlaubt. Maszstab ist die ArchiMate-3.2-Matrix, die der
  Writer mitliefert (``archimate/relationships.xml``, Archi EPL-2.0).
* **Verwaiste Elemente** -- ein Element haengt an keiner aufloesbaren
  Beziehung. Es steht im Katalog, aber in keiner Aussage.
* Dazu die kleinen Faelle, die dieselben Fehler vorbereiten: doppelte
  Kennungen, Selbstbezuege, Elemente ohne Namen.

Grundsaetze
-----------
* **Kein erfundenes Modellwissen.** Jede Meldung nennt das Objekt aus dem
  Modell und -- wo geurteilt wird -- die Regel: Matrix, Kennung, Name. Was
  sich nicht zuordnen laesst, wird als *nicht pruefbar* gezaehlt, nicht
  geraten.
* **Eine Zuordnungskette.** Stereotyp und Metaklasse werden mit derselben
  Funktion aufgeloest wie beim Schreiben (``archimate_writer.archimate_konzept``).
  Der Bericht urteilt damit ueber dasselbe Modell, das der Export schreibt.
* **Deutsch und deterministisch.** Kein Zeitstempel, kein Zufall: gleiche
  Eingabe, gleicher Bericht, gleiche Bytes.
* **Laut statt still.** Unlesbare Datei, falsches IR, fehlende Matrix:
  ``ArchimateCheckError``. Es gibt keinen halben Befund.

Oeffentliche API::

    from archimate_check import lade_modell, pruefe, render_markdown

    ir, format = lade_modell("modell.xml")
    befund = pruefe(ir)
    print(render_markdown(befund))

CLI::

    eam-ai archimate-check --in MODELL.xml [--out BERICHT.md]
        [--format text|md|json|prompt] [--frage "..."] [--strict]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import archimate_reader
import archimate_writer
from archimate_writer import MATRIX_TYPE, Konzept, archimate_beziehung, archimate_konzept

#: Kennung des IR, das alle Reader liefern. Ein anderes IR wird nicht geprueft.
IR_VERSION = archimate_reader.IR_VERSION

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: Reihenfolge der Schweregrade -- bestimmt Sortierung und Zusammenfassung.
_SEVERITY_RANK = {ERROR: 0, WARNING: 1, INFO: 2}

#: Deutsche Beschriftung fuer Text- und Markdown-Bericht.
_SEVERITY_LABEL = {ERROR: "Fehler", WARNING: "Warnung", INFO: "Hinweis"}

#: Obergrenze fuer Meldungen im Bericht; der Rest wird gezaehlt, nicht
#: verschwiegen. ``0`` bedeutet: alles ausgeben.
DEFAULT_LIMIT = 40

#: Obergrenze fuer Zeilen je Verteilung in der Zusammenfassung.
TOP_ZEILEN = 12


class ArchimateCheckError(ValueError):
    """Modell, Matrix oder IR taugen nicht. Immer laut."""


# --------------------------------------------------------------------------
# Schichten (ArchiMate 3.2, feste Tabelle)
# --------------------------------------------------------------------------
#: Zuordnung der Konzepte zu den Schichten nach ArchiMate 3.2. Die Tabelle ist
#: bewusst vollstaendig und wird im Test gegen ``ARCHIMATE_ELEMENT_TYPES``
#: geprueft: ein neues Konzept ohne Schicht faellt sofort auf, statt still
#: unter "ohne Schicht" zu verschwinden.
SCHICHTEN: Mapping[str, tuple[str, ...]] = {
    "Strategie": ("Capability", "CourseOfAction", "Resource", "ValueStream"),
    "Geschaeft": (
        "BusinessActor", "BusinessRole", "BusinessCollaboration",
        "BusinessInterface", "BusinessProcess", "BusinessFunction",
        "BusinessInteraction", "BusinessEvent", "BusinessService",
        "BusinessObject", "Contract", "Representation", "Product",
    ),
    "Anwendung": (
        "ApplicationComponent", "ApplicationCollaboration", "ApplicationInterface",
        "ApplicationProcess", "ApplicationFunction", "ApplicationInteraction",
        "ApplicationEvent", "ApplicationService", "DataObject",
    ),
    "Technik": (
        "Node", "Device", "SystemSoftware", "TechnologyCollaboration",
        "TechnologyInterface", "Path", "CommunicationNetwork",
        "TechnologyProcess", "TechnologyFunction", "TechnologyInteraction",
        "TechnologyEvent", "TechnologyService", "Artifact", "Equipment",
        "Facility", "DistributionNetwork", "Material",
    ),
    "Motivation": (
        "Stakeholder", "Driver", "Assessment", "Goal", "Outcome", "Principle",
        "Requirement", "Constraint", "Meaning", "Value",
    ),
    "Umsetzung": (
        "WorkPackage", "Deliverable", "ImplementationEvent", "Plateau", "Gap",
    ),
    "Zusammengesetzt": (
        "Grouping", "Location", "AndJunction", "OrJunction", "Junction",
    ),
}

#: Konzept -> Schicht (umgekehrter Index der Tabelle oben).
SCHICHT_VON: Mapping[str, str] = {
    konzept: schicht for schicht, konzepte in SCHICHTEN.items() for konzept in konzepte
}

#: Beschriftung, wenn ein Konzept nicht bestimmbar ist.
OHNE_SCHICHT = "ohne Schicht"
OHNE_KONZEPT = "ohne Konzept"
OHNE_ART = "(ohne Art)"


# --------------------------------------------------------------------------
# Befund
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    """Eine Meldung zum Modell -- mit Objekt, Regel und Pruefung.

    Dieselben Felder wie ``validator.py`` und ``struktur.py`` (``check``,
    ``severity``, ``object``, ``message``), damit alle Berichte der Suite
    zusammen ausgewertet werden koennen.
    """

    check: str
    severity: str
    object: str
    message: str
    rule: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "check": self.check,
            "severity": self.severity,
            "object": self.object,
            "message": self.message,
            "rule": self.rule,
        }


@dataclass(frozen=True)
class Zusammenfassung:
    """Was im Modell steht -- gezaehlt, nicht interpretiert."""

    modell: str
    kennung: str
    format: str
    pakete: int
    elemente: int
    beziehungen: int
    sichten: int
    schichten: Mapping[str, int] = field(default_factory=dict)
    konzepte: Mapping[str, int] = field(default_factory=dict)
    beziehungsarten: Mapping[str, int] = field(default_factory=dict)
    herkunft: Mapping[str, int] = field(default_factory=dict)
    ohne_beziehung: int = 0
    ohne_konzept: int = 0
    ohne_konzept_grund: Mapping[str, int] = field(default_factory=dict)
    kanten_ohne_art: int = 0
    kanten_ohne_art_typen: Mapping[str, int] = field(default_factory=dict)
    paket_endpunkte: int = 0
    datei: str = ""

    @property
    def fachlich(self) -> int:
        """Elemente, die Architektur sind -- ohne Darstellung und Prozessmechanik."""
        return self.elemente - self.ohne_konzept_grund.get("Darstellung", 0) - (
            self.ohne_konzept_grund.get("Prozessmechanik", 0)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "datei": self.datei,
            "modell": self.modell,
            "kennung": self.kennung,
            "format": self.format,
            "pakete": self.pakete,
            "elemente": self.elemente,
            "fachlich": self.fachlich,
            "beziehungen": self.beziehungen,
            "sichten": self.sichten,
            "schichten": dict(self.schichten),
            "konzepte": dict(self.konzepte),
            "beziehungsarten": dict(self.beziehungsarten),
            "herkunft": dict(self.herkunft),
            "ohne_beziehung": self.ohne_beziehung,
            "ohne_konzept": self.ohne_konzept,
            "ohne_konzept_grund": dict(self.ohne_konzept_grund),
            "kanten_ohne_art": self.kanten_ohne_art,
            "kanten_ohne_art_typen": dict(self.kanten_ohne_art_typen),
            "paket_endpunkte": self.paket_endpunkte,
        }


@dataclass(frozen=True)
class Befund:
    """Zusammenfassung plus Meldungen -- das Ergebnis von :func:`pruefe`."""

    zusammenfassung: Zusammenfassung
    findings: tuple[Finding, ...] = ()

    def summary(self) -> dict[str, int]:
        fehler = sum(1 for f in self.findings if f.severity == ERROR)
        warnungen = sum(1 for f in self.findings if f.severity == WARNING)
        hinweise = sum(1 for f in self.findings if f.severity == INFO)
        return {
            "total": len(self.findings),
            "error": fehler,
            "warning": warnungen,
            "info": hinweise,
        }

    def nach_pruefung(self) -> dict[str, int]:
        """Meldungen je Pruefung -- zeigt, welche Pruefung angeschlagen hat."""
        zaehler: dict[str, int] = {}
        for finding in self.findings:
            zaehler[finding.check] = zaehler.get(finding.check, 0) + 1
        return dict(sorted(zaehler.items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "zusammenfassung": self.zusammenfassung.as_dict(),
            "summary": self.summary(),
            "nach_pruefung": self.nach_pruefung(),
            "findings": [finding.as_dict() for finding in self.findings],
        }


# --------------------------------------------------------------------------
# Modell lesen
# --------------------------------------------------------------------------
def _format_label(suffix: str, ir: Mapping[str, Any]) -> str:
    if suffix == ".xml":
        meta = ir.get("meta")
        archimate = meta.get("archimate") if isinstance(meta, Mapping) else None
        namespace = ""
        if isinstance(archimate, Mapping):
            namespace = str(archimate.get("namespace") or "")
        return f"ArchiMate Model Exchange ({namespace or 'Namensraum unbekannt'})"
    if suffix == ".qea":
        return "EA-Repository (.qea)"
    return "IR-JSON"


def lade_modell(pfad: str | Path) -> tuple[dict[str, Any], str]:
    """Liest ein Modell und liefert ``(IR, Formatbezeichnung)``.

    Erkannt wird an der Endung: ``.xml`` (Model Exchange), ``.json`` (IR) und
    ``.qea`` (EA-Repository). Alles andere wird abgelehnt -- ein Rateversuch
    waere schlimmer als eine klare Meldung.
    """
    quelle = Path(pfad)
    if not quelle.is_file():
        raise ArchimateCheckError(f"{quelle}: Datei nicht gefunden")
    suffix = quelle.suffix.lower()
    try:
        if suffix == ".xml":
            # "keep": offene Verweise sind hier ein Befund, kein Abbruch --
            # die Pruefung soll sie melden, nicht vor ihnen davonlaufen.
            ir, _report = archimate_reader.read_archimate_ex(quelle, unresolved="keep")
        elif suffix == ".json":
            ir = json.loads(quelle.read_text(encoding="utf-8-sig"))
        elif suffix == ".qea":
            import qea_reader

            ir, _report = qea_reader.read_qea_ex(quelle, with_refs=True)
        else:
            raise ArchimateCheckError(
                f"{quelle}: Endung {suffix or '(keine)'} wird nicht gelesen "
                "(erwartet .xml, .json oder .qea)"
            )
    except ArchimateCheckError:
        raise
    except (OSError, ValueError) as exc:
        raise ArchimateCheckError(f"{quelle}: nicht lesbar ({exc})") from exc

    if not isinstance(ir, Mapping):
        raise ArchimateCheckError(f"{quelle}: IR ist kein Objekt")
    if ir.get("ir_version") != IR_VERSION:
        raise ArchimateCheckError(
            f"{quelle}: ir_version {ir.get('ir_version')!r} -- erwartet {IR_VERSION}"
        )
    return dict(ir), _format_label(suffix, ir)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _anzeige(ref: str) -> str:
    """Referenz ohne leeren Paketpraefix: ``::Name`` -> ``Name``.

    Die Referenz selbst bleibt unveraendert (sie identifiziert das Element);
    nur die Anzeige im Bericht wird lesbar.
    """
    return ref[2:] if ref.startswith("::") else ref


def _tags_key(tags: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(tags, Mapping):
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in tags.items()))


def _refs_ergaenzen(elemente: Sequence[Mapping[str, Any]]) -> list[str]:
    """IR ohne ``ref``: dieselben Referenzen bilden wie die Reader.

    Regel (``archimate_reader``/``qea_reader``): ``paket::name``, bei
    Namensgruppen > 1 mit ``#N``, unbenannte Elemente als ``paket::#N``. Die
    Nummer ist die Position in der kanonischen Inhaltsreihenfolge mit der
    Kennung als Tiebreak. Der Test vergleicht diese Funktion mit der Ausgabe
    des Readers -- laufen die Regeln auseinander, faellt es auf.
    """
    gruppen: dict[tuple[str, str], list[int]] = {}
    for index, element in enumerate(elemente):
        gruppen.setdefault(
            (_text(element.get("package")), _text(element.get("name"))), []
        ).append(index)

    refs: list[str] = [""] * len(elemente)
    for (paket, name), indizes in gruppen.items():
        indizes.sort(
            key=lambda i: (
                _text(elemente[i].get("ea_type")),
                _text(elemente[i].get("notes")),
                _tags_key(elemente[i].get("tags")),
                _text(elemente[i].get("identifier")),
            )
        )
        for position, index in enumerate(indizes, start=1):
            if not name:
                refs[index] = f"{paket}::#{position}"
            elif len(indizes) == 1:
                refs[index] = f"{paket}::{name}"
            else:
                refs[index] = f"{paket}::{name}#{position}"
    return refs


@dataclass(frozen=True)
class _Element:
    ref: str
    name: str
    paket: str
    ea_type: str
    konzept: Konzept

    @property
    def grund(self) -> str:
        """Warum ein Element kein ArchiMate-Konzept hat (nur bei ``keine``).

        Die Einordnung benutzt dieselben Listen wie der Writer
        (``SKIP_DISPLAY_TYPES``/``SKIP_FACH_TYPES``) -- sie behauptet nichts
        ueber das Modell, sondern sagt, was das Element ist.
        """
        schluessel = self.ea_type.lower()
        if schluessel in archimate_writer.SKIP_DISPLAY_TYPES:
            return "Darstellung"
        if schluessel in archimate_writer.SKIP_FACH_TYPES:
            return "Prozessmechanik"
        return "ohne Zuordnung"

    @property
    def fachlich(self) -> bool:
        """True, wenn das Element ein ArchiMate-Konzept hat (Architektur ist).

        Nur solche Elemente werden auf Waise und Namen geprueft: ein
        Beschriftungstext ohne Beziehung ist kein Qualitaetsmangel.
        """
        return self.konzept.typ is not None


def _elemente(ir: Mapping[str, Any]) -> tuple[list[_Element], list[str]]:
    """Elementindex mit Referenzen; Abbruch bei halben Referenzen.

    Doppelte Kennungen werden nicht hier verworfen, sondern von der Pruefung
    als Fehler gemeldet -- der Bericht soll zeigen, was im Modell steht.
    """
    roh = ir.get("elements") or ()
    if not isinstance(roh, Sequence) or isinstance(roh, (str, bytes)):
        raise ArchimateCheckError("elements: Liste erwartet")

    eintraege: list[Mapping[str, Any]] = []
    for index, eintrag in enumerate(roh):
        if not isinstance(eintrag, Mapping):
            raise ArchimateCheckError(f"elements[{index}]: Objekt erwartet")
        eintraege.append(eintrag)

    vorhanden = [_text(e.get("ref")) for e in eintraege]
    if any(vorhanden) and not all(vorhanden):
        fehlend = [i for i, ref in enumerate(vorhanden) if not ref]
        raise ArchimateCheckError(
            "elements: einige Eintraege haben 'ref', andere nicht "
            f"(ohne ref: {fehlend[:5]}) -- halbe Referenzen sind nicht pruefbar"
        )
    refs = vorhanden if all(vorhanden) else _refs_ergaenzen(eintraege)

    elemente = [
        _Element(
            ref=refs[index],
            name=_text(eintrag.get("name")),
            paket=_text(eintrag.get("package")),
            ea_type=_text(eintrag.get("ea_type")),
            konzept=archimate_konzept(
                _text(eintrag.get("stereotype")), _text(eintrag.get("ea_type"))
            ),
        )
        for index, eintrag in enumerate(eintraege)
    ]
    return elemente, refs


def _pakete(ir: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    pfade: dict[str, Mapping[str, Any]] = {}
    for eintrag in ir.get("packages") or ():
        if isinstance(eintrag, Mapping):
            pfad = _text(eintrag.get("path"))
            if pfad:
                pfade[pfad] = eintrag
    return pfade


def _kanten(ir: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    roh = ir.get("connectors") or ()
    if not isinstance(roh, Sequence) or isinstance(roh, (str, bytes)):
        raise ArchimateCheckError("connectors: Liste erwartet")
    return [kante for kante in roh if isinstance(kante, Mapping)]


def _zaehle(werte: Iterable[str]) -> dict[str, int]:
    zaehler: dict[str, int] = {}
    for wert in werte:
        zaehler[wert] = zaehler.get(wert, 0) + 1
    return dict(sorted(zaehler.items(), key=lambda paar: (-paar[1], paar[0])))


def _zaehl(zaehler: dict[str, int], schluessel: str, anzahl: int = 1) -> None:
    zaehler[schluessel] = zaehler.get(schluessel, 0) + anzahl


def _kopf(ir: Mapping[str, Any]) -> tuple[str, str]:
    """Modellname und Kennung aus ``meta.archimate`` (nur wenn vorhanden)."""
    meta = ir.get("meta")
    archimate = meta.get("archimate") if isinstance(meta, Mapping) else None
    if not isinstance(archimate, Mapping):
        return "", ""
    return _text(archimate.get("name")), _text(archimate.get("identifier"))


# --------------------------------------------------------------------------
# Zusammenfassung
# --------------------------------------------------------------------------
def _zusammenfassung(
    elemente: Sequence[_Element],
    kanten: Sequence[Mapping[str, Any]],
    ir: Mapping[str, Any],
    format: str,
    datei: str = "",
) -> Zusammenfassung:
    konzepte = _zaehle(element.konzept.typ or OHNE_KONZEPT for element in elemente)
    schichten = _zaehle(
        SCHICHT_VON.get(element.konzept.typ or "", OHNE_SCHICHT) for element in elemente
    )
    herkunft = _zaehle(element.konzept.herkunft for element in elemente)
    ohne_grund = _zaehle(
        element.grund for element in elemente if element.konzept.typ is None
    )
    arten = _zaehle(
        archimate_beziehung(_text(k.get("stereotype")), _text(k.get("ea_type"))) or OHNE_ART
        for k in kanten
    )
    arten_ohne = _zaehle(
        (_text(k.get("ea_type")) or _text(k.get("stereotype")) or "(leer)")
        for k in kanten
        if archimate_beziehung(_text(k.get("stereotype")), _text(k.get("ea_type"))) is None
    )

    refs = {element.ref for element in elemente}
    fachliche_refs = {element.ref for element in elemente if element.fachlich}
    pakete = _pakete(ir)
    beteiligt: set[str] = set()
    paket_endpunkte = 0
    for kante in kanten:
        for seite in ("source", "target"):
            ziel = _text(kante.get(seite))
            if ziel in refs:
                beteiligt.add(ziel)
            elif ziel in pakete:
                paket_endpunkte += 1

    diagramme = ir.get("diagrams") or ()
    modell, kennung = _kopf(ir)
    return Zusammenfassung(
        modell=modell,
        kennung=kennung,
        format=format,
        pakete=len(pakete),
        elemente=len(elemente),
        beziehungen=len(kanten),
        sichten=len(diagramme) if isinstance(diagramme, Sequence) else 0,
        schichten=schichten,
        konzepte=konzepte,
        beziehungsarten=arten,
        herkunft=herkunft,
        ohne_beziehung=len(fachliche_refs - beteiligt),
        ohne_konzept=konzepte.get(OHNE_KONZEPT, 0),
        ohne_konzept_grund=ohne_grund,
        kanten_ohne_art=arten.get(OHNE_ART, 0),
        kanten_ohne_art_typen=arten_ohne,
        paket_endpunkte=paket_endpunkte,
        datei=datei,
    )


def zusammenfassen(
    ir: Mapping[str, Any], *, format: str = "IR-JSON", datei: str = ""
) -> Zusammenfassung:
    """Zaehlt das Modell aus: Groesse, Schichten, Konzepte, Beziehungsarten."""
    elemente, _refs = _elemente(ir)
    return _zusammenfassung(elemente, _kanten(ir), ir, format, datei)


# --------------------------------------------------------------------------
# Pruefungen
# --------------------------------------------------------------------------
def _kanten_label(kante: Mapping[str, Any], nummer: int) -> str:
    name = _text(kante.get("name"))
    if name:
        return name
    quelle = _anzeige(_text(kante.get("source"))) or "?"
    ziel = _anzeige(_text(kante.get("target"))) or "?"
    art = _text(kante.get("ea_type")) or _text(kante.get("stereotype")) or "Kante"
    return f"{art} {quelle} -> {ziel} (#{nummer})"


def _pruefe_referenzen(
    elemente: Sequence[_Element],
    kanten: Sequence[Mapping[str, Any]],
    pakete: Mapping[str, Mapping[str, Any]],
    findings: list[Finding],
) -> None:
    refs = [element.ref for element in elemente]
    haeufigkeit = _zaehle(refs)
    for ref, anzahl in haeufigkeit.items():
        if anzahl > 1:
            findings.append(
                Finding(
                    check="duplicateIdentifier",
                    severity=ERROR,
                    object=_anzeige(ref),
                    message=(
                        f"Kennung ist {anzahl}x vergeben -- Verweise sind nicht eindeutig."
                    ),
                )
            )

    bekannt = set(refs)
    for nummer, kante in enumerate(kanten, start=1):
        label = _kanten_label(kante, nummer)
        for seite, rolle in (("source", "Quelle"), ("target", "Ziel")):
            ziel = _text(kante.get(seite))
            if ziel in bekannt or ziel in pakete:
                # Paket als Endpunkt ist im IR erlaubt; der Writer macht nur
                # dann ein Element daraus, wenn das Paket einen Stereotyp hat.
                continue
            findings.append(
                Finding(
                    check="unresolvedReference",
                    severity=ERROR,
                    object=label,
                    message=(
                        f"{rolle} '{_anzeige(ziel) or '(leer)'}' zeigt auf kein Element "
                        "und kein Paket des Modells."
                    ),
                )
            )


def _pruefe_matrix(
    elemente: Sequence[_Element],
    kanten: Sequence[Mapping[str, Any]],
    matrix: Mapping[tuple[str, str], set[str]],
    findings: list[Finding],
    pruefbar: dict[str, int],
) -> None:
    nach_ref = {element.ref: element for element in elemente}
    for nummer, kante in enumerate(kanten, start=1):
        label = _kanten_label(kante, nummer)
        quelle = _text(kante.get("source"))
        ziel = _text(kante.get("target"))

        if quelle and quelle == ziel:
            findings.append(
                Finding(
                    check="selfReference",
                    severity=WARNING,
                    object=label,
                    message="Quelle und Ziel sind dasselbe Element.",
                )
            )

        art = archimate_beziehung(_text(kante.get("stereotype")), _text(kante.get("ea_type")))
        if art is None:
            _zaehl(pruefbar, "kante_ohne_art")
            continue
        quell_element = nach_ref.get(quelle)
        ziel_element = nach_ref.get(ziel)
        if quell_element is None or ziel_element is None:
            # Offene Referenz: dort gemeldet, hier nicht doppelt.
            _zaehl(pruefbar, "kante_mit_offener_referenz")
            continue
        quelltyp = quell_element.konzept.typ
        zieltyp = ziel_element.konzept.typ
        if not quelltyp or not zieltyp:
            _zaehl(pruefbar, "kante_ohne_konzept")
            continue
        quelltyp = MATRIX_TYPE.get(quelltyp, quelltyp)
        zieltyp = MATRIX_TYPE.get(zieltyp, zieltyp)
        if archimate_writer.matrix_erlaubt(matrix, quelltyp, art, zieltyp):
            _zaehl(pruefbar, "kante_geprueft")
            continue
        findings.append(
            Finding(
                check="matrixViolation",
                severity=ERROR,
                object=label,
                rule="ArchiMate 3.2 Beziehungsmatrix",
                message=(
                    f"{art} von {quelltyp} nach {zieltyp} ist nicht erlaubt "
                    f"({_anzeige(quell_element.ref)} -> {_anzeige(ziel_element.ref)})."
                ),
            )
        )


def _pruefe_elemente(
    elemente: Sequence[_Element],
    kanten: Sequence[Mapping[str, Any]],
    findings: list[Finding],
) -> None:
    refs = {element.ref for element in elemente}
    beteiligt: set[str] = set()
    for kante in kanten:
        for seite in ("source", "target"):
            ziel = _text(kante.get(seite))
            if ziel in refs:
                beteiligt.add(ziel)

    for element in elemente:
        if not element.fachlich:
            # Beschriftung und Prozessmechanik: kein ArchiMate-Element, also
            # auch kein Qualitaetsmangel, wenn es allein steht.
            continue
        label = _anzeige(element.ref)
        if not element.name:
            findings.append(
                Finding(
                    check="unnamedElement",
                    severity=WARNING,
                    object=label,
                    message=f"{element.konzept.typ} ohne Namen.",
                )
            )
        if element.ref not in beteiligt:
            findings.append(
                Finding(
                    check="orphanElement",
                    severity=WARNING,
                    object=label,
                    message=(
                        f"{element.konzept.typ} haengt an keiner aufloesbaren "
                        "Beziehung (weder Quelle noch Ziel)."
                    ),
                )
            )


def _sortierschluessel(finding: Finding) -> tuple[Any, ...]:
    return (
        _SEVERITY_RANK.get(finding.severity, 9),
        finding.check,
        finding.object,
        finding.message,
    )


def pruefe(
    ir: Mapping[str, Any],
    *,
    format: str = "IR-JSON",
    matrix: Mapping[tuple[str, str], set[str]] | None = None,
    datei: str = "",
) -> Befund:
    """Prueft ein Modell und liefert Zusammenfassung plus Meldungen.

    ``matrix`` ist die Beziehungsmatrix; ohne Angabe wird die mitgelieferte
    ArchiMate-3.2-Matrix geladen. ``datei`` ist nur die Herkunftsangabe fuer
    den Bericht (IR kennt keinen Dateinamen).
    """
    if not isinstance(ir, Mapping):
        raise ArchimateCheckError("IR: Objekt erwartet")
    elemente, _refs = _elemente(ir)
    kanten = _kanten(ir)
    pakete = _pakete(ir)
    if matrix is None:
        try:
            matrix = archimate_writer.load_matrix()
        except archimate_writer.ArchimateWriterError as exc:
            raise ArchimateCheckError(f"Beziehungsmatrix nicht ladbar: {exc}") from exc

    findings: list[Finding] = []
    pruefbar: dict[str, int] = {}
    _pruefe_referenzen(elemente, kanten, pakete, findings)
    _pruefe_matrix(elemente, kanten, matrix, findings, pruefbar)
    _pruefe_elemente(elemente, kanten, findings)

    # Dieselbe Meldung nur einmal: doppelte Kennungen erzeugen sonst je
    # Vorkommen ein eigenes "verwaist".
    eindeutig = sorted(
        {(f.check, f.object, f.message): f for f in findings}.values(),
        key=_sortierschluessel,
    )
    return Befund(
        zusammenfassung=_zusammenfassung(elemente, kanten, ir, format, datei),
        findings=tuple(eindeutig),
    )


# --------------------------------------------------------------------------
# Ausgabe
# --------------------------------------------------------------------------
def _top(werte: Mapping[str, int], grenze: int = TOP_ZEILEN) -> list[tuple[str, int]]:
    return list(werte.items())[:grenze]


def _zahl(text: Any, breite: int) -> str:
    return str(text).rjust(breite)


def render_text(befund: Befund, *, limit: int = DEFAULT_LIMIT) -> str:
    """Bericht als reiner Text -- fuer Terminal, Log und Weiterverarbeitung."""
    z = befund.zusammenfassung
    zeilen: list[str] = ["MODELL"]
    zeilen.append(f"  Datei:     {z.datei or '(unbekannt)'}")
    zeilen.append(f"  Name:      {z.modell or '(ohne Namen)'}")
    zeilen.append(f"  Kennung:   {z.kennung or '(ohne Kennung)'}")
    zeilen.append(f"  Format:    {z.format}")
    zeilen.append(
        f"  Groesse:   {z.pakete} Pakete, {z.elemente} Elemente "
        f"({z.fachlich} fachlich), {z.beziehungen} Beziehungen, {z.sichten} Sichten"
    )
    zeilen.extend(["", "SCHICHTEN"])
    for schicht, anzahl in _top(z.schichten):
        zeilen.append(f"  {schicht:<18}{_zahl(anzahl, 6)}")
    zeilen.extend(["", "KONZEPTE (Top)"])
    for konzept, anzahl in _top(z.konzepte):
        zeilen.append(f"  {konzept:<24}{_zahl(anzahl, 6)}")
    zeilen.extend(["", "BEZIEHUNGSARTEN"])
    for art, anzahl in _top(z.beziehungsarten):
        zeilen.append(f"  {art:<24}{_zahl(anzahl, 6)}")
    zeilen.extend(
        [
            "",
            "PRUEFBARKEIT",
            f"  Elemente ohne Konzept:       {z.ohne_konzept}",
        ]
    )
    for grund, anzahl in _top(z.ohne_konzept_grund, 6):
        zeilen.append(f"    davon {grund:<22}{_zahl(anzahl, 6)}")
    zeilen.append(f"  Kanten ohne Beziehungsart:   {z.kanten_ohne_art}")
    for art, anzahl in _top(z.kanten_ohne_art_typen, 4):
        zeilen.append(f"    davon {art:<22}{_zahl(anzahl, 6)}")
    zeilen.extend(
        [
            f"  Elemente ohne Beziehung:     {z.ohne_beziehung}",
            f"  Pakete als Kantenendpunkt:   {z.paket_endpunkte}",
            "",
        ]
    )

    summary = befund.summary()
    zeilen.append("BEFUND")
    zeilen.append(
        f"  {summary['total']} Meldungen: {summary['error']} Fehler, "
        f"{summary['warning']} Warnungen, {summary['info']} Hinweise"
    )
    if befund.findings:
        gezeigt = befund.findings if limit <= 0 else befund.findings[:limit]
        for finding in gezeigt:
            regel = f" [{finding.rule}]" if finding.rule else ""
            zeilen.append(
                f"  {_SEVERITY_LABEL[finding.severity]:<9}{finding.check:<24}"
                f"{finding.object}{regel}: {finding.message}"
            )
        rest = len(befund.findings) - len(gezeigt)
        if rest > 0:
            zeilen.append(f"  ... {rest} weitere Meldungen (--limit 0 zeigt alle)")
    else:
        zeilen.append("  Keine Meldungen.")
    return "\n".join(zeilen) + "\n"


def render_markdown(befund: Befund, *, limit: int = DEFAULT_LIMIT) -> str:
    """Bericht als Markdown -- fuer Ablage, Ticket und Uebergabe an die KI."""
    z = befund.zusammenfassung
    zeilen: list[str] = [
        "# ArchiMate-Modellbefund",
        "",
        f"- **Datei:** {z.datei or '(unbekannt)'}",
        f"- **Modell:** {z.modell or '(ohne Namen)'}",
        f"- **Kennung:** {z.kennung or '(ohne Kennung)'}",
        f"- **Format:** {z.format}",
        f"- **Groesse:** {z.pakete} Pakete, {z.elemente} Elemente "
        f"({z.fachlich} fachlich), {z.beziehungen} Beziehungen, {z.sichten} Sichten",
        "",
        "## Zusammenfassung",
        "",
        "| Schicht | Elemente |",
        "| --- | ---: |",
    ]
    for schicht, anzahl in _top(z.schichten):
        zeilen.append(f"| {schicht} | {anzahl} |")
    zeilen.extend(["", "| Konzept | Elemente |", "| --- | ---: |"])
    for konzept, anzahl in _top(z.konzepte):
        zeilen.append(f"| {konzept} | {anzahl} |")
    zeilen.extend(["", "| Beziehungsart | Kanten |", "| --- | ---: |"])
    for art, anzahl in _top(z.beziehungsarten):
        zeilen.append(f"| {art} | {anzahl} |")
    zeilen.extend(
        [
            "",
            "## Pruefbarkeit",
            "",
            f"- Elemente ohne Konzept: **{z.ohne_konzept}**"
            + (
                " ("
                + ", ".join(f"{grund} {anzahl}" for grund, anzahl in z.ohne_konzept_grund.items())
                + ")"
                if z.ohne_konzept_grund
                else ""
            ),
            f"- Kanten ohne Beziehungsart: **{z.kanten_ohne_art}**"
            + (
                " ("
                + ", ".join(f"{art} {anzahl}" for art, anzahl in z.kanten_ohne_art_typen.items())
                + ")"
                if z.kanten_ohne_art_typen
                else ""
            ),
            f"- Elemente ohne Beziehung: **{z.ohne_beziehung}**",
            f"- Pakete als Kantenendpunkt: **{z.paket_endpunkte}**",
            "",
        ]
    )

    summary = befund.summary()
    zeilen.extend(
        [
            "## Qualitaetsbefund",
            "",
            f"**{summary['total']} Meldungen:** {summary['error']} Fehler, "
            f"{summary['warning']} Warnungen, {summary['info']} Hinweise.",
            "",
        ]
    )
    if not befund.findings:
        zeilen.extend(["Keine Meldungen.", ""])
        return "\n".join(zeilen)

    zeilen.extend(["| Schwere | Pruefung | Objekt | Befund |", "| --- | --- | --- | --- |"])
    gezeigt = befund.findings if limit <= 0 else befund.findings[:limit]
    for finding in gezeigt:
        objekt = finding.object.replace("|", "\\|")
        message = finding.message.replace("|", "\\|")
        zeilen.append(
            f"| {_SEVERITY_LABEL[finding.severity]} | `{finding.check}` | "
            f"{objekt} | {message} |"
        )
    rest = len(befund.findings) - len(gezeigt)
    if rest > 0:
        zeilen.extend(["", f"*... {rest} weitere Meldungen (mit `--limit 0` alle).*"])
    zeilen.append("")
    return "\n".join(zeilen)


def render_json(befund: Befund) -> str:
    """Bericht als JSON (sortierte Schluessel, UTF-8, 2 Leerzeichen)."""
    return json.dumps(befund.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


#: Regeln fuer den Prompt. Sie muessen zu ``qea_chat.PROMPT_KOPF`` passen --
#: ein Modell, eine Sprache; der Test haelt beide Seiten zusammen.
PROMPT_KOPF = (
    "Du beantwortest Fragen zu einem EAM-Architekturmodell im ArchiMate-Austauschformat. "
    "Grundlage ist ausschliesslich der folgende Befund, der von einem Programm aus dem "
    "Modell erzeugt wurde. Erfinde keine Elemente, Beziehungen, Zahlen oder Quellen. "
    "Wenn der Befund die Frage nicht beantwortet, sage das ausdruecklich. "
    "Nenne als Belegstelle den Pfad '<Paket>::<Element>' oder die Kennung aus dem Befund. "
    "Antworte auf Deutsch in vollstaendigen Saetzen."
)


def render_prompt(befund: Befund, frage: str = "", *, limit: int = DEFAULT_LIMIT) -> str:
    """Bericht als fertiger Prompt -- die KI sieht nur, was im Modell steht."""
    zeilen = [PROMPT_KOPF, "", "MODELLBEFUND:", render_text(befund, limit=limit).rstrip()]
    zeilen.extend(
        [
            "",
            "FRAGE:",
            frage.strip()
            or "(keine Frage gestellt -- dies ist der Kontext fuer eine Frage)",
        ]
    )
    return "\n".join(zeilen) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archimate_check.py",
        description="ArchiMate-Modell lesen, zusammenfassen und pruefen.",
    )
    parser.add_argument(
        "--in", "-i", dest="quelle", required=True, type=Path,
        help="Modell (.xml ArchiMate Model Exchange, .json IR oder .qea)",
    )
    parser.add_argument(
        "--out", "-o", type=Path, default=None, help="Bericht in diese Datei schreiben"
    )
    parser.add_argument(
        "--format", "-f", dest="format",
        choices=("text", "md", "json", "prompt"),
        default="text",
        help="Ausgabeformat (Default: text)",
    )
    parser.add_argument("--frage", default="", help="Frage fuer --format prompt")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"Meldungen im Bericht (Default: {DEFAULT_LIMIT}; 0 = alle)",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Warnungen zaehlen wie Fehler (Exit 1)"
    )
    args = parser.parse_args(argv)

    try:
        ir, format_label = lade_modell(args.quelle)
        befund = pruefe(ir, format=format_label, datei=args.quelle.name)
    except ArchimateCheckError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 3

    if args.format == "json":
        text = render_json(befund)
    elif args.format == "md":
        text = render_markdown(befund, limit=args.limit)
    elif args.format == "prompt":
        text = render_prompt(befund, args.frage, limit=args.limit)
    else:
        text = render_text(befund, limit=args.limit)

    summary = befund.summary()
    if args.out:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"FEHLER: Bericht nicht schreibbar: {exc}", file=sys.stderr)
            return 3
        print(
            f"{args.out}: {summary['error']} Fehler, {summary['warning']} Warnungen, "
            f"{summary['info']} Hinweise",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)

    if summary["error"]:
        return 1
    if args.strict and summary["warning"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
