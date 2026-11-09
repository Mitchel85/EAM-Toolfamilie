"""archimate_reader.py -- ArchiMate 3.x Model Exchange XML -> IR.

Die Umkehrung von ``archimate_writer.py``. Die Datei wird geparst und in
dieselbe IR-Form uebersetzt, die ``qea_reader.py`` liefert
(``ir_version``/``packages``/``elements``/``connectors``/``diagrams``). Damit
ist ``.xml`` ueberall dort einsetzbar, wo heute ``.qea`` gelesen wird -- fuer
den Graphen, die Pruefung und die AI-Suite.

Was gelesen wird
----------------
- **Elemente:** ``<elements><element xsi:type="...">`` mit Name, Documentation
  und Properties.
- **Beziehungen:** ``<relationships><relationship xsi:type="..." source="..."
  target="...">``; die Endpunkte werden auf die IR-Referenzen der Elemente
  uebersetzt.
- **Properties:** die vier ADMBw-Properties des Writers (Stereotyp,
  Metaklasse, EA-GUID, Paketpfad) werden zu IR-Feldern; jede weitere Property
  landet als Tagged Value in ``tags``.
- **Gruppen:** ``<organizations>`` (Enthaltenseinsbaum) wird -- nur wo der
  Paketpfad fehlt -- zum Paketpfad. ``Grouping``-Elemente sind regulaere
  Elemente mit ``xsi:type="Grouping"``.

Kernentscheidungen (alle deterministisch)
-----------------------------------------
- **Dokumentreihenfolge bleibt erhalten.** Anders als der qea-Reader sortiert
  dieser Reader nicht: Elemente und Beziehungen stehen im IR in der Reihenfolge
  der Datei. Nur so ist ``qea -> XML -> IR -> XML`` byte-identisch -- der
  Writer schreibt in IR-Reihenfolge.
- **Identitaet zuerst.** Die XML-Kennung wird woertlich uebernommen, wenn sie
  sich nicht aus der GUID ableiten laesst (Feld ``identifier``). Der Writer
  benutzt sie dann unveraendert. Das betrifft vor allem Beziehungen (das
  Format kennt dort keine GUID-Property) und die aus Paketen erzeugten
  Grouping-Elemente.
- **``ea_type`` ist die Wahrheit.** Steht ``ADMBw_Metaklasse`` in den
  Properties, gilt sie. Sonst ist das Element bereits ein ArchiMate-Element
  (Import aus Archi oder einem anderen Werkzeug) und traegt seinen
  ``xsi:type`` als ``ea_type``; der Writer erkennt ihn ueber die
  Typidentitaet wieder.
- **Referenzen wie im qea-Reader:** ``paket::name``, bei Namensgruppen > 1 mit
  ``#N``, unbenannte Elemente als ``paket::#N``. Die Nummer ist die Position
  in der kanonischen Inhaltsreihenfolge ``(ea_type, notes, tags)`` mit der
  Kennung als Tiebreak.
- **Modellkopf** (Name, Kennung, Formatversion) steht in
  ``meta.archimate`` -- der Writer schreibt ihn daraus zurueck.
- **Laut statt still:** ungueltiges XML, falscher Namensraum, fehlende oder
  doppelte Kennungen, unbekannte ArchiMate-Typen und Beziehungen auf nicht
  vorhandene Elemente brechen mit ``ArchimateReaderError`` ab. Es gibt keinen
  stillen Teil-Erfolg.

Oeffentliche API::

    from archimate_reader import read_archimate, read_archimate_ex

    ir = read_archimate("modell.xml")                  # dict, writer-kompatibel
    ir, report = read_archimate_ex("modell.xml")       # dict + Statistiken
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from archimate_writer import (
    ARCHIMATE_ELEMENT_TYPES,
    ARCHIMATE_RELATIONSHIP_TYPES,
    kennung,
)

NS = "http://www.opengroup.org/xsd/archimate/3.0/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

IR_VERSION = 1
DEFAULT_OBJECT_TYPE = "Class"

#: EA-GUID-Form (32 Hexziffern in 8-4-4-4-12). Nur so geformte Kennungen
#: duerfen als ``guid`` ins IR: ``qea_writer`` prueft das Format.
EA_GUID = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)

#: Akzeptierte Namensraeume. Das Open-Group-Format fuehrt 3.x unter der
#: 3.0-Kennung; die 3.1/3.2-Schreibweisen sind Aufnahmebereitschaft, kein
#: anderes Format.
NAMESPACES = frozenset({
    "http://www.opengroup.org/xsd/archimate/3.0/",
    "http://www.opengroup.org/xsd/archimate/3.1/",
    "http://www.opengroup.org/xsd/archimate/3.2/",
})

#: Property-Kennung (oder Ersatzname) -> IR-Feld. Die Kennung ist der
#: verlaessliche Schluessel; der Name deckt Dateien ab, die ohne
#: ``propertyDefinitions`` geschrieben wurden.
BEKANNTE_PROPERTIES: dict[str, str] = {
    "prop-admbw-stereotype": "stereotype",
    "prop-admbw-metatype": "ea_type",
    "prop-ea-guid": "guid",
    "prop-paketpfad": "package",
    "ADMBw_Stereotyp": "stereotype",
    "ADMBw_Metaklasse": "ea_type",
    "Sparx_EA_GUID": "guid",
    "Paketpfad": "package",
}


class ArchimateReaderError(ValueError):
    """Unlesbares XML, inkonsistentes Modell oder Verlustgefahr. Immer laut."""


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ReadReport:
    """Was der Reader tatsaechlich gesehen hat -- nie leerer Erfolg ohne Zahlen."""

    packages: int = 0
    elements: int = 0
    relationships: int = 0
    element_tags: int = 0
    relationship_tags: int = 0
    property_definitions: int = 0
    organization_nodes: int = 0
    diagrams: int = 0
    imported_elements: int = 0
    namespace: str = ""
    model_name: str = ""
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "packages": self.packages,
            "elements": self.elements,
            "relationships": self.relationships,
            "element_tags": self.element_tags,
            "relationship_tags": self.relationship_tags,
            "property_definitions": self.property_definitions,
            "organization_nodes": self.organization_nodes,
            "diagrams": self.diagrams,
            "imported_elements": self.imported_elements,
            "namespace": self.namespace,
            "model_name": self.model_name,
            "warnings": list(self.warnings),
        }

    def summary(self) -> str:
        text = (
            f"{self.packages} Pakete, {self.elements} Elemente, "
            f"{self.relationships} Beziehungen, {self.element_tags} Element-Tags"
        )
        if self.imported_elements:
            text += f" | {self.imported_elements} Elemente ohne ADMBw-Metaklasse"
        if self.organization_nodes:
            text += f" | {self.organization_nodes} Organisationsknoten"
        if self.diagrams:
            text += f" | {self.diagrams} Sichten bewusst nicht uebernommen"
        return text


# --------------------------------------------------------------------------
# Interne Datensicht
# --------------------------------------------------------------------------
@dataclass
class _Item:
    art: str                      # "element" | "beziehung"
    identifier: str
    typ: str                      # xsi:type
    name: str = ""
    notes: str = ""
    stereotype: str = ""
    ea_type: str = ""
    guid: str = ""
    package: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    quelle: str = ""
    ziel: str = ""
    hat_metaklasse: bool = True


# --------------------------------------------------------------------------
# XML-Hilfen (namensraumtolerant innerhalb des geprueften Namensraums)
# --------------------------------------------------------------------------
def _lokal(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kinder(element: ET.Element, name: str) -> list[ET.Element]:
    return [kind for kind in element if _lokal(kind.tag) == name]


def _kind(element: ET.Element, name: str) -> ET.Element | None:
    for kind in element:
        if _lokal(kind.tag) == name:
            return kind
    return None


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _langtext(eltern: ET.Element, name: str) -> str:
    """Erster Text zu ``name``; Deutsch hat Vorrang, dann ohne ``xml:lang``."""
    treffer = _kinder(eltern, name)
    if not treffer:
        return ""
    for kind in treffer:
        if (kind.get(XML_LANG) or "").lower().startswith("de"):
            return _text(kind)
    for kind in treffer:
        if not kind.get(XML_LANG):
            return _text(kind)
    return _text(treffer[0])


def _erster_wert(property_element: ET.Element) -> str:
    werte = _kinder(property_element, "value")
    if not werte:
        return ""
    for wert in werte:
        if (wert.get(XML_LANG) or "").lower().startswith("de"):
            return _text(wert)
    for wert in werte:
        if not wert.get(XML_LANG):
            return _text(wert)
    return _text(werte[0])


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


# --------------------------------------------------------------------------
# Property-Definitionen und Properties
# --------------------------------------------------------------------------
def _definitionen(wurzel: ET.Element) -> dict[str, str]:
    """``propertyDefinition``-Kennung -> Name (fuer die Feldzuordnung)."""
    definitionen: dict[str, str] = {}
    for block in _kinder(wurzel, "propertyDefinitions"):
        for definition in _kinder(block, "propertyDefinition"):
            kennung_wert = (definition.get("identifier") or "").strip()
            if not kennung_wert:
                continue
            definitionen[kennung_wert] = _langtext(definition, "name")
    return definitionen


def _properties(
    element: ET.Element, definitionen: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Liefert (bekannte IR-Felder, uebrige Tagged Values)."""
    felder: dict[str, str] = {}
    tags: dict[str, str] = {}
    for block in _kinder(element, "properties"):
        for property_element in _kinder(block, "property"):
            referenz = (property_element.get("propertyDefinitionRef") or "").strip()
            if not referenz:
                continue
            wert = _erster_wert(property_element)
            name = definitionen.get(referenz) or referenz
            feld = BEKANNTE_PROPERTIES.get(referenz) or BEKANNTE_PROPERTIES.get(name)
            if feld:
                # Erster Wert gewinnt: das IR kennt je Feld genau einen Wert.
                felder.setdefault(feld, wert)
            elif name:
                tags.setdefault(name, wert)
    return felder, tags


# --------------------------------------------------------------------------
# Organisationsbaum -> Paketpfad (nur wo kein Paketpfad-Property steht)
# --------------------------------------------------------------------------
def _organisation(
    eltern: ET.Element,
    pfad: str,
    ziel: dict[str, str],
    zaehler: list[int],
) -> None:
    for block in _kinder(eltern, "organizations"):
        for item in _kinder(block, "item"):
            _organisations_knoten(item, pfad, ziel, zaehler)


def _organisations_knoten(
    item: ET.Element, pfad: str, ziel: dict[str, str], zaehler: list[int]
) -> None:
    zaehler[0] += 1
    referenz = (item.get("identifierRef") or "").strip()
    if referenz:
        # Erste Zuordnung gewinnt; ein Element kann in mehreren Baeumen haengen.
        ziel.setdefault(referenz, pfad)
    bezeichnung = _langtext(item, "label") or _langtext(item, "name")
    neuer_pfad = pfad
    if not referenz and bezeichnung:
        neuer_pfad = f"{pfad}/{bezeichnung}" if pfad else bezeichnung
    for kind in _kinder(item, "item"):
        _organisations_knoten(kind, neuer_pfad, ziel, zaehler)


# --------------------------------------------------------------------------
# Elemente und Beziehungen lesen
# --------------------------------------------------------------------------
def _lese_element(
    element: ET.Element, definitionen: Mapping[str, str], index: int
) -> _Item:
    identifier = (element.get("identifier") or "").strip()
    if not identifier:
        raise ArchimateReaderError(f"elements[{index}]: identifier fehlt")

    typ = (element.get(f"{{{XSI}}}type") or "").strip().rsplit(":", 1)[-1]
    if not typ:
        raise ArchimateReaderError(
            f"Element {identifier!r}: xsi:type fehlt -- ohne ArchiMate-Typ nicht darstellbar"
        )
    if typ in ARCHIMATE_RELATIONSHIP_TYPES:
        raise ArchimateReaderError(
            f"Element {identifier!r}: {typ!r} ist ein Beziehungstyp, kein Elementtyp"
        )
    if typ not in ARCHIMATE_ELEMENT_TYPES:
        raise ArchimateReaderError(
            f"Element {identifier!r}: unbekannter ArchiMate-Typ {typ!r} "
            "(ArchiMate 3.2 kennt diesen Typ nicht)"
        )

    felder, tags = _properties(element, definitionen)
    return _Item(
        art="element",
        identifier=identifier,
        typ=typ,
        name=_langtext(element, "name"),
        notes=_langtext(element, "documentation"),
        stereotype=felder.get("stereotype", ""),
        ea_type=felder.get("ea_type", "") or typ,
        guid=felder.get("guid", ""),
        package=felder.get("package", ""),
        tags=tags,
        hat_metaklasse="ea_type" in felder,
    )


def _lese_beziehung(
    element: ET.Element, definitionen: Mapping[str, str], index: int
) -> _Item:
    identifier = (element.get("identifier") or "").strip()
    if not identifier:
        raise ArchimateReaderError(f"relationships[{index}]: identifier fehlt")

    typ = (element.get(f"{{{XSI}}}type") or "").strip().rsplit(":", 1)[-1]
    if not typ:
        raise ArchimateReaderError(
            f"Beziehung {identifier!r}: xsi:type fehlt -- ohne ArchiMate-Typ nicht darstellbar"
        )
    if typ in ARCHIMATE_ELEMENT_TYPES:
        raise ArchimateReaderError(
            f"Beziehung {identifier!r}: {typ!r} ist ein Elementtyp, kein Beziehungstyp"
        )
    if typ not in ARCHIMATE_RELATIONSHIP_TYPES:
        raise ArchimateReaderError(
            f"Beziehung {identifier!r}: unbekannter ArchiMate-Beziehungstyp {typ!r}"
        )

    quelle = (element.get("source") or "").strip()
    ziel = (element.get("target") or "").strip()
    if not quelle or not ziel:
        raise ArchimateReaderError(
            f"Beziehung {identifier!r}: source oder target fehlt"
        )

    felder, tags = _properties(element, definitionen)
    return _Item(
        art="beziehung",
        identifier=identifier,
        typ=typ,
        name=_langtext(element, "name"),
        notes=_langtext(element, "documentation"),
        stereotype=felder.get("stereotype", ""),
        ea_type=felder.get("ea_type", "") or typ,
        guid=felder.get("guid", ""),
        tags=tags,
        quelle=quelle,
        ziel=ziel,
    )


# --------------------------------------------------------------------------
# Referenzen
# --------------------------------------------------------------------------
def _refs_bauen(items: Iterable[_Item]) -> dict[int, str]:
    """Ref-String je Element: ``paket::name``, ``paket::name#N``, ``paket::#N``."""
    gruppen: dict[tuple[str, str], list[_Item]] = {}
    for item in items:
        if item.art == "element":
            gruppen.setdefault((item.package, item.name), []).append(item)

    for gruppe in gruppen.values():
        # Dieselbe Nummerierung wie qea_reader/xmi_reader: Inhalt zuerst,
        # Kennung als Tiebreak -- auch fuer inhaltlich identische Zwillinge.
        gruppe.sort(
            key=lambda e: (
                e.ea_type,
                e.notes,
                tuple(sorted(e.tags.items())),
                e.identifier,
            )
        )

    refs: dict[int, str] = {}
    for (pfad, name), gruppe in gruppen.items():
        for position, item in enumerate(gruppe, start=1):
            if not name:
                refs[id(item)] = f"{pfad}::#{position}"
            elif len(gruppe) == 1:
                refs[id(item)] = f"{pfad}::{name}"
            else:
                refs[id(item)] = f"{pfad}::{name}#{position}"
    return refs


def _pakete(elemente: Iterable[_Item], organisationspfade: Iterable[str]) -> list[dict[str, str]]:
    """Alle Paketpfade samt Eltern -- der IR-Vertrag verlangt sie vollstaendig."""
    pfade: set[str] = set()
    for item in elemente:
        if item.package:
            pfade.add(item.package)
    for pfad in organisationspfade:
        if pfad:
            pfade.add(pfad)
    # Eltern ergaenzen, damit jedes Paket deklariert ist (qea_writer prueft das).
    for pfad in list(pfade):
        teile = pfad.split("/")
        for grenze in range(1, len(teile)):
            pfade.add("/".join(teile[:grenze]))
    return [{"path": pfad} for pfad in sorted(pfade) if pfad]


# --------------------------------------------------------------------------
# Oeffentliche API
# --------------------------------------------------------------------------
def read_archimate_ex(
    path: str | Path, *, strict: bool = False, unresolved: str = "error"
) -> tuple[dict[str, Any], ReadReport]:
    """Liest ein ArchiMate-Modell und liefert (IR-Dict, ReadReport).

    ``strict=True`` macht jede Warnung zum Fehler (kein stiller Verlust).

    ``unresolved`` steuert, was mit Beziehungen geschieht, deren Endpunkt auf
    kein Element zeigt:

    * ``"error"`` (Standard) -- Abbruch. Fuer Export und Umbau ist ein
      kaputter Verweis ein Grund anzuhalten; ein halbes Modell waere schlimmer.
    * ``"keep"`` -- der rohe ``identifier`` bleibt als Endpunkt stehen und die
      Beziehung wandert mit Warnung ins IR. Nur so kann eine *Pruefung* den
      offenen Verweis melden, statt vor ihm davonzulaufen
      (``archimate_check`` nutzt diesen Weg).
    """
    if unresolved not in ("error", "keep"):
        raise ArchimateReaderError(
            f"unresolved: 'error' oder 'keep' erwartet, gefunden {unresolved!r}"
        )
    quelle = Path(path)
    try:
        roh = quelle.read_bytes()
    except OSError as exc:
        raise ArchimateReaderError(f"{quelle}: nicht lesbar ({exc})") from exc
    try:
        wurzel = ET.fromstring(roh)
    except ET.ParseError as exc:
        raise ArchimateReaderError(f"{quelle}: XML nicht parsebar ({exc})") from exc

    if _lokal(wurzel.tag) != "model":
        raise ArchimateReaderError(
            f"{quelle}: Wurzelelement ist <{_lokal(wurzel.tag)}>, <model> erwartet"
        )
    namespace = _namespace(wurzel.tag)
    if namespace not in NAMESPACES:
        raise ArchimateReaderError(
            f"{quelle}: Namensraum {namespace!r} ist kein ArchiMate-3.x-Austauschformat"
        )

    warnungen: list[str] = []
    definitionen = _definitionen(wurzel)

    elemente: list[_Item] = []
    for block in _kinder(wurzel, "elements"):
        for index, element in enumerate(_kinder(block, "element")):
            elemente.append(_lese_element(element, definitionen, index))

    beziehungen: list[_Item] = []
    for block in _kinder(wurzel, "relationships"):
        for index, element in enumerate(_kinder(block, "relationship")):
            beziehungen.append(_lese_beziehung(element, definitionen, index))

    # Organisationsbaum: Paketpfad-Ersatz fuer Elemente ohne Paketpfad.
    organisationspfade: dict[str, str] = {}
    zaehler = [0]
    _organisation(wurzel, "", organisationspfade, zaehler)
    for item in elemente:
        if not item.package and item.identifier in organisationspfade:
            item.package = organisationspfade[item.identifier]

    refs = _refs_bauen(elemente)
    ident_zu_ref: dict[str, str] = {}
    for item in elemente:
        treffer = refs.get(id(item))
        if treffer is None:  # pragma: no cover - _refs_bauen deckt alle Elemente ab
            raise ArchimateReaderError(f"keine Referenz fuer {item.name!r}")
        if item.identifier in ident_zu_ref:
            raise ArchimateReaderError(
                f"doppelte Element-Kennung {item.identifier!r} -- das Format "
                "verlangt eindeutige identifier"
            )
        ident_zu_ref[item.identifier] = treffer
        if not item.name:
            warnungen.append(f"Element {item.identifier!r} ohne Namen")

    element_items: list[dict[str, Any]] = []
    tag_zaehler = 0
    importiert = 0
    for item in elemente:  # Dokumentreihenfolge -- Grundlage des Rundlaufs
        if not item.hat_metaklasse:
            # Kein ADMBw-Property: das Element kommt aus einem ArchiMate-Werkzeug
            # und traegt seinen xsi:type selbst.
            importiert += 1
        ref = ident_zu_ref[item.identifier]
        eintrag: dict[str, Any] = {"package": item.package, "name": item.name}
        if item.stereotype:
            eintrag["stereotype"] = item.stereotype
        eintrag["ea_type"] = item.ea_type
        if item.notes:
            eintrag["notes"] = item.notes
        if item.tags:
            eintrag["tags"] = dict(sorted(item.tags.items()))
            tag_zaehler += len(item.tags)
        if item.guid:
            eintrag["guid"] = item.guid
        eintrag["ref"] = ref
        # Kennung nur, wenn sie sich nicht aus der GUID ableiten laesst.
        if kennung(item.guid, ref) != item.identifier:
            eintrag["identifier"] = item.identifier
        element_items.append(eintrag)

    connector_items: list[dict[str, Any]] = []
    connector_tags = 0
    for item in beziehungen:
        quelle_ref = ident_zu_ref.get(item.quelle)
        if quelle_ref is None:
            if unresolved != "keep":
                raise ArchimateReaderError(
                    f"Beziehung {item.identifier!r}: Quelle {item.quelle!r} zeigt auf kein Element"
                )
            warnungen.append(
                f"Beziehung {item.identifier!r}: Quelle {item.quelle!r} zeigt auf kein Element"
            )
            quelle_ref = item.quelle
        ziel_ref = ident_zu_ref.get(item.ziel)
        if ziel_ref is None:
            if unresolved != "keep":
                raise ArchimateReaderError(
                    f"Beziehung {item.identifier!r}: Ziel {item.ziel!r} zeigt auf kein Element"
                )
            warnungen.append(
                f"Beziehung {item.identifier!r}: Ziel {item.ziel!r} zeigt auf kein Element"
            )
            ziel_ref = item.ziel
        eintrag = {"source": quelle_ref, "target": ziel_ref}
        if item.stereotype:
            eintrag["stereotype"] = item.stereotype
        eintrag["ea_type"] = item.ea_type
        if item.name:
            eintrag["name"] = item.name
        if item.notes:
            eintrag["notes"] = item.notes
        if item.tags:
            eintrag["tags"] = dict(sorted(item.tags.items()))
            connector_tags += len(item.tags)
        # Das Format kennt keine GUID-Property an Beziehungen. Die Kennung ist
        # die Identitaet; sie wird als GUID gefuehrt, wenn das Format stimmt,
        # sonst woertlich als ``identifier`` (dann leitet qea_writer seine
        # eigene GUID ab, statt an einer Hash-Kennung zu scheitern).
        kandidat = item.identifier[3:] if item.identifier.startswith("id-") else ""
        if kandidat and EA_GUID.match(kandidat) and kennung(kandidat, "") == item.identifier:
            eintrag["guid"] = kandidat
        else:
            eintrag["identifier"] = item.identifier
        connector_items.append(eintrag)

    # Sichten: Das Modell-XSD enthaelt sie nicht; falls ein Diagramm-XSD
    # angehaengt wurde, werden sie gezaehlt, aber nicht uebernommen.
    diagramme = sum(1 for e in wurzel.iter() if _lokal(e.tag) == "view")

    ir: dict[str, Any] = {"ir_version": IR_VERSION}
    kopf: dict[str, str] = {}
    name = _langtext(wurzel, "name")
    identifier = (wurzel.get("identifier") or "").strip()
    version = (wurzel.get("version") or "").strip()
    if name:
        kopf["name"] = name
    if identifier:
        kopf["identifier"] = identifier
    if version:
        kopf["version"] = version
    if kopf:
        kopf["namespace"] = namespace
        ir["meta"] = {"archimate": kopf}
    ir["packages"] = _pakete(elemente, organisationspfade.values())
    ir["elements"] = element_items
    ir["connectors"] = connector_items
    ir["diagrams"] = []

    report = ReadReport(
        packages=len(ir["packages"]),
        elements=len(element_items),
        relationships=len(connector_items),
        element_tags=tag_zaehler,
        relationship_tags=connector_tags,
        property_definitions=len(definitionen),
        organization_nodes=zaehler[0],
        diagrams=diagramme,
        imported_elements=importiert,
        namespace=namespace,
        model_name=name,
        warnings=tuple(warnungen),
    )
    if strict and report.warnings:
        raise ArchimateReaderError(
            "strikter Modus: " + " | ".join(report.warnings) + f" ({quelle})"
        )
    return ir, report


def read_archimate(path: str | Path, *, strict: bool = False) -> dict[str, Any]:
    """Liest ein ArchiMate-Modell und liefert nur das IR-Dict."""
    ir, _report = read_archimate_ex(path, strict=strict)
    return ir


def render_json(ir: Mapping[str, Any]) -> str:
    """Kanonische JSON-Darstellung (sortierte Schluessel, UTF-8, 2 Leerzeichen)."""
    return json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_ir(ir: Mapping[str, Any], path: str | Path) -> Path:
    ziel = Path(path)
    ziel.write_text(render_json(ir), encoding="utf-8")
    return ziel


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archimate_reader",
        description="ArchiMate 3.x Model Exchange XML -> IR-JSON",
    )
    parser.add_argument("--in", "-i", dest="quelle", required=True, type=Path,
                        help="ArchiMate-XML")
    parser.add_argument("--out", "-o", dest="ziel", type=Path, default=None,
                        help="IR-JSON schreiben (Default: stdout)")
    parser.add_argument("--report", type=Path, default=None, help="Report als JSON")
    args = parser.parse_args(argv)

    try:
        ir, report = read_archimate_ex(args.quelle)
    except (ArchimateReaderError, OSError, ValueError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    text = render_json(ir)
    if args.ziel:
        args.ziel.write_text(text, encoding="utf-8")
        print(f"{args.ziel}: {report.summary()}")
    else:
        print(text, end="")
    if args.report:
        args.report.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
