"""prosa_import.py -- Markdown-Dokumentation -> .qea (Rueckweg des Exports).

Liest das von :mod:`roundtrip_export` erzeugte Markdown-Dokument und baut
daraus wieder eine Sparx-EA-Datenbank. Der Weg ist verlustarm, weil das
Dokument seit Format 2 die GUIDs der Elemente, Pakete und Kantenendpunkte
mitfuehrt; damit sind auch doppelte (Paket, Name)-Paare eindeutig.

CLI::

    python3 prosa_import.py DOKU.md --out NEU.qea [--belege belege.json]

Optional kann die Belegdatei mitgegeben werden. Sie hat bei GUIDs und Tags
Vorrang und loest Mehrdeutigkeiten auf; ohne sie muss das Dokument allein
reichen (das tut es: jede Elementzeile traegt ihre GUID, jede Kantenzeile
Quelle- und Ziel-GUID).

Regeln:

* Pakete stammen aus den ``##``-Ueberschriften mit folgender Zeile
  ``Paket-ID: `n` · GUID: `{...}```.
* Elemente stammen aus den Listenzeilen inklusive Stereotyp, Typ, Alias,
  Status, Notiz und Tags. ``(unbenannt)`` wird wieder zu einem leeren Namen;
  ein abweichender Rohname steht in der Unterzeile ``Rohname: "..."``.
* Tags aus ``t_objectproperties`` stehen unter ``Tags:``, Tags aus
  ``t_xref``/``CustomProperties`` unter ``Tags (xref):``. Sie werden getrennt
  zurueckgeschrieben -- sonst wuerde der Rueckbau Tags doppeln.
* Kanten werden primaer ueber ``Quelle-GUID``/``Ziel-GUID`` aufgeloest,
  ersatzweise ueber ``Pfad::Name[#N]``.

Ausgabe ist deterministisch (keine Zeitstempel, keine Zufallswerte).
Formatfehler brechen mit Exit-Code 2 und Klartext ab.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from qea_writer import QeaWriterError, write_qea

IR_VERSION = 1

#: Anzeigename fuer Elemente ohne Namen (siehe roundtrip_export.OHNE_NAMEN).
OHNE_NAMEN = "(unbenannt)"
LEER = "-"

#: Zeichen, die ``roundtrip_export._md`` maskiert.
_MD_SPECIAL = set("\\`*_[]<>")


class ProsaImportError(ValueError):
    """Formatfehler im Dokument -- immer mit Klartext und Exit-Code 2."""


# --------------------------------------------------------------------------
# Kleine Parser
# --------------------------------------------------------------------------


def _unescape(text: str) -> str:
    """Kehrt ``roundtrip_export._md`` um (Backslash-Maskierung)."""
    out: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text) and text[index + 1] in _MD_SPECIAL:
            out.append(text[index + 1])
            index += 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


_PAKET_RE = re.compile(r"^Paket-ID: `(?P<id>\d+)` \u00b7 GUID: `(?P<guid>[^`]*)`$")

_ELEMENT_RE = re.compile(
    r"^- \*\*(?P<name>.*)\*\* \u2014 Typ: `(?P<typ>[^`]*)`"
    r" \u00b7 Stereotyp: `(?P<stereotype>[^`]*)`"
    r" \u00b7 ID: `(?P<id>\d+)`"
    r" \u00b7 GUID: `(?P<guid>[^`]*)`"
    r" \u00b7 Alias: `(?P<alias>[^`]*)`"
    r" \u00b7 Status: `(?P<status>[^`]*)`$"
)

_KANTE_RE = re.compile(
    r"^- `(?P<quelle>.*)` \u2192 `(?P<ziel>.*)`"
    r" \u2014 Typ: `(?P<typ>[^`]*)`"
    r" \u00b7 Stereotyp: `(?P<stereotype>[^`]*)`"
    r" \u00b7 Name: `(?P<name>[^`]*)`"
    r" \u00b7 ID: `(?P<id>\d+)`"
    r" \u00b7 GUID: `(?P<guid>[^`]*)`"
    r"(?: \u00b7 Quelle-GUID: `(?P<quelle_guid>[^`]*)`"
    r" \u00b7 Ziel-GUID: `(?P<ziel_guid>[^`]*)`"
    r" \u00b7 Richtung: `(?P<richtung>[^`]*)`)?$"
)


def _wert(text: str) -> str:
    """``-`` ist der Platzhalter fuer einen leeren Wert im Dokument."""
    return "" if text == LEER else text


def _parse_tags(text: str, wo: str) -> dict[str, str]:
    """Liest `` `k=v`, `k2=v2` ``; Kommas in Werten bleiben erhalten."""
    text = text.strip()
    if not text:
        return {}
    parts = text.split("`, `")
    if parts[0].startswith("`"):
        parts[0] = parts[0][1:]
    if parts[-1].endswith("`"):
        parts[-1] = parts[-1][:-1]
    tags: dict[str, str] = {}
    for part in parts:
        key, separator, value = part.partition("=")
        if not separator:
            raise ProsaImportError(f"{wo}: Tag {part!r} hat kein '='")
        if not key:
            raise ProsaImportError(f"{wo}: Tag ohne Namen")
        tags[key] = value
    return tags


# --------------------------------------------------------------------------
# Dokumentmodell
# --------------------------------------------------------------------------


@dataclass
class PaketDoku:
    path: str
    name: str
    parent: str
    id: int
    guid: str
    notes: str = ""
    #: Tags, die im Dokument am Paketspiegel stehen. Sie gehoeren in
    #: ``t_objectproperties`` des Spiegels und werden beim Schreiben wieder
    #: an das Paket gehaengt.
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class ElementDoku:
    paket: str
    name: str
    typ: str
    stereotype: str
    alias: str
    status: str
    guid: str
    notes: str = ""
    rohname: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    tags_xref: dict[str, str] = field(default_factory=dict)
    reihenfolge: int = 0


@dataclass
class KanteDoku:
    quelle: str
    ziel: str
    typ: str
    stereotype: str
    name: str
    guid: str
    richtung: str
    quelle_guid: str
    ziel_guid: str
    id: int = 0


@dataclass
class Dokument:
    pakete: list[PaketDoku] = field(default_factory=list)
    elemente: list[ElementDoku] = field(default_factory=list)
    kanten: list[KanteDoku] = field(default_factory=list)


def parse_document(text: str) -> Dokument:
    """Zerlegt das Markdown-Dokument in Pakete, Elemente und Kanten."""
    dokument = Dokument()
    lines = text.splitlines()
    aktuelles_paket: PaketDoku | None = None
    letztes_element: ElementDoku | None = None
    modus = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            if letztes_element is not None:
                _finalisiere_element(letztes_element)
                letztes_element = None
            heading = _unescape(line[3:].strip())
            folge = index + 1
            while folge < len(lines) and not lines[folge].strip():
                folge += 1
            if folge < len(lines) and lines[folge].startswith("Paket-ID:"):
                match = _PAKET_RE.match(lines[folge].strip())
                if match is None:
                    raise ProsaImportError(
                        f"Zeile {folge + 1}: Paketzeile nicht lesbar: {lines[folge]!r}"
                    )
                aktuelles_paket = PaketDoku(
                    path=heading,
                    name=heading.rsplit("/", 1)[-1],
                    parent=heading.rsplit("/", 1)[0] if "/" in heading else "",
                    id=int(match.group("id")),
                    guid=_wert(match.group("guid")),
                )
                dokument.pakete.append(aktuelles_paket)
                letztes_element = None
                modus = "paket"
                index = folge + 1
                continue
            aktuelles_paket = None
            letztes_element = None
            modus = "beziehungen" if heading == "Beziehungen" else "sonstiges"
            index += 1
            continue
        if modus == "paket" and aktuelles_paket is not None:
            if line.startswith("- **"):
                if letztes_element is not None:
                    _finalisiere_element(letztes_element)
                match = _ELEMENT_RE.match(line)
                if match is None:
                    raise ProsaImportError(
                        f"Zeile {index + 1}: Elementzeile nicht lesbar: {line!r}"
                    )
                letztes_element = ElementDoku(
                    paket=aktuelles_paket.path,
                    name=_unescape(match.group("name")),
                    typ=_wert(match.group("typ")),
                    stereotype=_wert(match.group("stereotype")),
                    alias=_wert(match.group("alias")),
                    status=_wert(match.group("status")),
                    guid=_wert(match.group("guid")),
                    reihenfolge=len(dokument.elemente),
                )
                dokument.elemente.append(letztes_element)
                index += 1
                continue
            if letztes_element is not None and line.startswith("  - "):
                if line.startswith("  - Notiz: "):
                    letztes_element.notes = _unescape(line[len("  - Notiz: "):])
                elif line.startswith("  - Rohname: "):
                    roh = line[len("  - Rohname: "):].strip()
                    try:
                        value = json.loads(roh)
                    except json.JSONDecodeError as error:
                        raise ProsaImportError(
                            f"Zeile {index + 1}: Rohname kein gueltiges JSON ({error})"
                        ) from error
                    if not isinstance(value, str):
                        raise ProsaImportError(
                            f"Zeile {index + 1}: Rohname muss eine Zeichenkette sein"
                        )
                    letztes_element.rohname = value
                elif line.startswith("  - Tags (xref): "):
                    letztes_element.tags_xref.update(
                        _parse_tags(line[len("  - Tags (xref): "):], f"Zeile {index + 1}")
                    )
                elif line.startswith("  - Tags: "):
                    letztes_element.tags.update(
                        _parse_tags(line[len("  - Tags: "):], f"Zeile {index + 1}")
                    )
                index += 1
                continue
            if line.startswith("Notiz: "):
                aktuelles_paket.notes = _unescape(line[len("Notiz: "):])
            index += 1
            continue

        if modus == "beziehungen" and line.startswith("- `"):
            match = _KANTE_RE.match(line)
            if match is None:
                raise ProsaImportError(
                    f"Zeile {index + 1}: Kantenzeile nicht lesbar: {line!r}"
                )
            dokument.kanten.append(
                KanteDoku(
                    quelle=_wert(match.group("quelle")),
                    ziel=_wert(match.group("ziel")),
                    typ=_wert(match.group("typ")),
                    stereotype=_wert(match.group("stereotype")),
                    name=_wert(match.group("name")),
                    guid=_wert(match.group("guid")),
                    richtung=_wert(match.group("richtung") or ""),
                    quelle_guid=_wert(match.group("quelle_guid") or ""),
                    ziel_guid=_wert(match.group("ziel_guid") or ""),
                    id=int(match.group("id")),
                )
            )
            index += 1
            continue

        index += 1

    if letztes_element is not None:
        _finalisiere_element(letztes_element)
    if not dokument.pakete:
        raise ProsaImportError("kein Paket gefunden -- ist das ein roundtrip_export-Dokument?")
    _bestimme_paketnamen(dokument)
    _uebernehme_paketspiegel_tags(dokument)
    return dokument


def _finalisiere_element(element: ElementDoku) -> None:
    """Loest den Anzeigenamen in den echten Namen auf."""
    if element.rohname is not None:
        element.name = element.rohname
    elif element.name == OHNE_NAMEN:
        element.name = ""  # noqa: PLC1901 -- exakter Sentinel, kein Leerstring
    element.rohname = None


def _bestimme_paketnamen(dokument: Dokument) -> None:
    """Entfernt ``#2``/``#3``-Zusaetze, die nur der Eindeutigkeit dienten.

    ``roundtrip_export`` haengt sie an gleichnamige Geschwisterpfade; der
    echte Paketname ist das Segment davor. Ein Literal ``#2`` im Namen bleibt
    erhalten, wenn es keinen Basis-Pfad gibt.
    """
    pfade = {paket.path for paket in dokument.pakete}
    for paket in dokument.pakete:
        segment = paket.path.rsplit("/", 1)[-1]
        parent = paket.parent
        match = re.match(r"^(?P<basis>.*)#(?P<nummer>\d+)$", segment)
        if match is None:
            continue
        basis_pfad = f"{parent}/{match.group('basis')}" if parent else match.group("basis")
        if basis_pfad in pfade:
            paket.name = match.group("basis")


def _uebernehme_paketspiegel_tags(dokument: Dokument) -> None:
    """Haengt Tags der Paketspiegel an das zugehoerige Paket.

    ``roundtrip_export`` listet Paketspiegel als Elementzeilen vom Typ
    ``Package``. Ihre Tagged Values gehoeren zum Paket; der Writer schreibt
    sie beim Rueckbau an den neu erzeugten Spiegel. Mehrdeutige Spiegelnamen
    (gleichnamige Geschwister) bleiben unberuecksichtigt, weil das Dokument
    dafuer keine weitere Kennung traegt.
    """
    nach_eltern_name: dict[tuple[str, str], list[PaketDoku]] = {}
    for paket in dokument.pakete:
        nach_eltern_name.setdefault((paket.parent, paket.name), []).append(paket)
    for element in dokument.elemente:
        if element.typ.lower() != "package" or not element.tags:
            continue
        kandidaten = [
            paket
            for paket in nach_eltern_name.get((element.paket, element.name), [])
            if not element.guid or not paket.guid or paket.guid.upper() == element.guid.upper()
        ]
        if len(kandidaten) != 1:
            kandidaten = nach_eltern_name.get((element.paket, element.name), [])
        if len(kandidaten) == 1:
            kandidaten[0].tags.update(element.tags)


# --------------------------------------------------------------------------
# Belege (optional)
# --------------------------------------------------------------------------


@dataclass
class Belege:
    pakete: dict[str, dict[str, Any]] = field(default_factory=dict)
    elemente: dict[str, dict[str, Any]] = field(default_factory=dict)
    kanten: dict[int, dict[str, Any]] = field(default_factory=dict)


def load_belege(path: str | Path) -> Belege:
    """Liest die Belegdatei; Strukturfehler werden laut gemeldet."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except OSError as error:
        raise ProsaImportError(f"{path}: nicht lesbar ({error})") from error
    except json.JSONDecodeError as error:
        raise ProsaImportError(f"{path}: kein gueltiges JSON ({error})") from error
    if not isinstance(data, Mapping):
        raise ProsaImportError(f"{path}: JSON-Objekt erwartet")
    version = data.get("format_version")
    if version not in (1, 2):
        raise ProsaImportError(f"{path}: unbekannte format_version {version!r}")
    belege = Belege()
    for paket in data.get("pakete") or ():
        if not isinstance(paket, Mapping) or not paket.get("guid"):
            raise ProsaImportError(f"{path}: Paket-Beleg ohne GUID")
        belege.pakete[str(paket["guid"]).upper()] = dict(paket)
    for element in data.get("elemente") or ():
        if not isinstance(element, Mapping) or not element.get("guid"):
            raise ProsaImportError(f"{path}: Element-Beleg ohne GUID")
        belege.elemente[str(element["guid"]).upper()] = dict(element)
    for kante in data.get("kanten") or ():
        if not isinstance(kante, Mapping) or "id" not in kante:
            raise ProsaImportError(f"{path}: Kanten-Beleg ohne ID")
        belege.kanten[int(kante["id"])] = dict(kante)
    return belege


def _tags_aus_beleg(element_beleg: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Trennt gemergte Beleg-Tags wieder in objectproperties und xref."""
    xref = {str(key): str(value) for key, value in (element_beleg.get("tags_xref") or {}).items()}
    tags = {str(key): str(value) for key, value in (element_beleg.get("tags") or {}).items()}
    for key, value in xref.items():
        if tags.get(key) == value:
            tags.pop(key, None)
    return tags, xref


# --------------------------------------------------------------------------
# IR bauen
# --------------------------------------------------------------------------


def _writer_sortierschluessel(element: ElementDoku) -> tuple[Any, ...]:
    """Dieselbe Reihenfolge, in der ``qea_writer._element_index`` sortiert."""
    return (
        element.typ,
        element.notes,
        element.alias,
        element.status,
        tuple(sorted(element.tags.items())),
    )


def _referenz(element: ElementDoku, position: int, *, immer_nummer: bool = False) -> str:
    if element.name:
        basis = f"{element.paket}::{element.name}"
        return f"{basis}#{position}" if immer_nummer or position > 1 else basis
    return f"{element.paket}::#{position}"


class _Aufloeser:
    """Loest Kantenendpunkte auf -- bevorzugt ueber GUID, sonst ueber Text."""

    def __init__(self, dokument: Dokument) -> None:
        self.pakete = {paket.path: paket for paket in dokument.pakete}
        self.paket_guids = {paket.guid.upper(): paket for paket in dokument.pakete if paket.guid}
        # Paketspiegel stehen zwar als Elementzeilen im Dokument, sind aber
        # keine Elemente: ihre GUID kann mit der Paket-GUID identisch sein
        # (EA ist da inkonsistent). Sie werden ueber die Paketkarte aufgeloest.
        echte_elemente = [
            element for element in dokument.elemente if element.typ.lower() != "package"
        ]
        self.element_guids = {
            element.guid.upper(): element for element in echte_elemente if element.guid
        }
        self.gruppen: dict[tuple[str, str], list[ElementDoku]] = {}
        for element in echte_elemente:
            self.gruppen.setdefault((element.paket, element.name), []).append(element)
        self.positionen: dict[int, int] = {}
        for gruppe in self.gruppen.values():
            gruppe.sort(key=_writer_sortierschluessel)
            for position, element in enumerate(gruppe, start=1):
                self.positionen[id(element)] = position

    def _element_ref(self, element: ElementDoku) -> str:
        gruppe = self.gruppen[(element.paket, element.name)]
        return _referenz(
            element,
            self.positionen[id(element)],
            # Der Writer verlangt auch fuer das erste Vorkommen ein #N,
            # sobald der Name im Paket mehrfach vorkommt.
            immer_nummer=len(gruppe) > 1,
        )

    def _paket_ref(self, paket: PaketDoku) -> str:
        if not paket.parent:
            raise ProsaImportError(
                f"Kante zeigt auf das Wurzelpaket {paket.path!r}; Wurzelpakete haben "
                "in Sparx EA keinen t_object-Spiegel und koennen kein Endpunkt sein"
            )
        return paket.path

    def aufloesen(self, guid: str, text: str, wo: str) -> str:
        key = guid.strip().upper()
        if key and key not in ("", LEER):
            element = self.element_guids.get(key)
            if element is not None:
                return self._element_ref(element)
            paket = self.paket_guids.get(key)
            if paket is not None:
                return self._paket_ref(paket)
        return self._text_aufloesen(text, wo)

    def _text_aufloesen(self, text: str, wo: str) -> str:
        text = text.strip()
        if not text:
            raise ProsaImportError(f"{wo}: Endpunkt ohne GUID und ohne Pfadangabe")
        if "::" not in text:
            paket = self.pakete.get(text)
            if paket is None:
                raise ProsaImportError(f"{wo}: Paket {text!r} ist nicht dokumentiert")
            return self._paket_ref(paket)
        pfad, rest = text.rsplit("::", 1)
        if pfad not in self.pakete:
            raise ProsaImportError(f"{wo}: Paket {pfad!r} ist nicht dokumentiert")
        if rest.startswith("#") and rest[1:].isdigit():
            name, occurrence = "", int(rest[1:])
        else:
            name, occurrence = rest, None
            if name not in {key[1] for key in self.gruppen if key[0] == pfad}:
                ohne, trenner, nummer = name.rpartition("#")
                if trenner and nummer.isdigit():
                    name, occurrence = ohne, int(nummer)
        gruppe = self.gruppen.get((pfad, name))
        if not gruppe:
            raise ProsaImportError(
                f"{wo}: Element {text!r} ist nicht dokumentiert"
            )
        if occurrence is None:
            if len(gruppe) > 1:
                formen = ", ".join(
                    f"{pfad}::{name}#{position}" for position in range(1, len(gruppe) + 1)
                )
                raise ProsaImportError(
                    f"{wo}: Endpunkt {text!r} ist mehrdeutig ({len(gruppe)} gleichnamige "
                    f"Elemente) -- eindeutig mit {formen} oder Quelle-GUID/Ziel-GUID"
                )
            occurrence = 1
        if not 1 <= occurrence <= len(gruppe):
            raise ProsaImportError(
                f"{wo}: Endpunkt {text!r} verlangt Vorkommen {occurrence}, "
                f"vorhanden sind {len(gruppe)}"
            )
        return _referenz(gruppe[occurrence - 1], occurrence)


def build_ir(dokument: Dokument, belege: Belege | None = None) -> dict[str, Any]:
    """Baut das Writer-IR aus dem Dokument (Belege haben Vorrang)."""
    # Belege koennen fehlende Dokumentangaben ergaenzen und Namen/GUIDs
    # bestaetigen; das Dokument bleibt die Strukturquelle.
    if belege is not None:
        for element in dokument.elemente:
            eintrag = belege.elemente.get(element.guid.upper()) if element.guid else None
            if eintrag is None:
                continue
            if not element.tags and not element.tags_xref:
                element.tags, element.tags_xref = _tags_aus_beleg(eintrag)
            if element.rohname is None and not element.name:
                name = eintrag.get("name")
                if isinstance(name, str):
                    element.name = name

    pakete = []
    for paket in sorted(dokument.pakete, key=lambda item: (item.path.casefold(), item.id)):
        eintrag = {
            "path": paket.path,
            "name": paket.name,
            "notes": paket.notes,
            "guid": paket.guid or None,
        }
        if paket.tags:
            eintrag["tags"] = paket.tags
        pakete.append(eintrag)
    elemente = []
    for element in dokument.elemente:
        if element.typ.lower() == "package":
            # Paketspiegel legt der Writer selbst an; ein zweites t_object
            # waere ein Doppel und keine treuere Datei.
            continue
        eintrag = {
            "package": element.paket,
            "name": element.name,
            "stereotype": element.stereotype,
            "ea_type": element.typ or "Class",
            "notes": element.notes,
            "alias": element.alias,
            "status": element.status,
            "tags": element.tags,
            "guid": element.guid or None,
        }
        if element.tags_xref:
            eintrag["xref_tags"] = element.tags_xref
        elemente.append(eintrag)

    aufloeser = _Aufloeser(dokument)
    kanten = []
    for kante in dokument.kanten:
        wo = f"Kante ID {kante.guid or '-'}"
        if belege is not None and (not kante.quelle_guid or not kante.ziel_guid):
            eintrag = belege.kanten.get(kante.id)
            if eintrag is not None:
                kante.quelle = kante.quelle or str(eintrag.get("quelle") or "")
                kante.ziel = kante.ziel or str(eintrag.get("ziel") or "")
        eintrag = {
            "source": aufloeser.aufloesen(kante.quelle_guid, kante.quelle, f"{wo}.source"),
            "target": aufloeser.aufloesen(kante.ziel_guid, kante.ziel, f"{wo}.target"),
            "stereotype": kante.stereotype,
            "ea_type": kante.typ or "Dependency",
            "name": kante.name,
            "tags": {},
            "guid": kante.guid or None,
        }
        if kante.richtung:
            eintrag["direction"] = kante.richtung
        kanten.append(eintrag)

    return {
        "ir_version": IR_VERSION,
        "packages": pakete,
        "elements": elemente,
        "connectors": kanten,
        "diagrams": [],
    }


def import_document(
    doku_path: str | Path,
    out_path: str | Path,
    *,
    belege_path: str | Path | None = None,
) -> tuple[int, int, int]:
    """Liest das Dokument und schreibt die .qea. Rueckgabe: (Pakete, Elemente, Kanten)."""
    path = Path(doku_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProsaImportError(f"{path}: nicht lesbar ({error})") from error
    dokument = parse_document(text)
    belege = load_belege(belege_path) if belege_path is not None else None
    ir = build_ir(dokument, belege)
    write_qea(ir, out_path)
    return len(ir["packages"]), len(ir["elements"]), len(ir["connectors"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prosa_import.py",
        description="Baut aus der Markdown-Dokumentation wieder eine .qea.",
    )
    parser.add_argument("doku", help="Markdown-Dokument (roundtrip_export, Format 2)")
    parser.add_argument("--out", required=True, help="Zielpfad der .qea")
    parser.add_argument("--belege", default=None, help="optionale Belegdatei (JSON)")
    args = parser.parse_args(argv)

    try:
        pakete, elemente, kanten = import_document(
            args.doku, args.out, belege_path=args.belege
        )
    except (ProsaImportError, QeaWriterError, OSError) as error:
        print(f"prosa_import: {error}", file=sys.stderr)
        return 2
    print(
        f"Import ok: {pakete} Pakete, {elemente} Elemente, {kanten} Kanten\n"
        f"Ziel: {args.out}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
