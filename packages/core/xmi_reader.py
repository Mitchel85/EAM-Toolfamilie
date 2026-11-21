"""xmi_reader.py -- XMI 2.1 -> IR. Die Umkehrung von ``xmi_writer.py``.

Nur lesen: die Datei wird geparst und in dieselbe IR-Form uebersetzt, die
``qea_reader.py`` liefert (``IR_SPEC.md`` ist der Vertrag). Damit ist
``.xmi`` ueberall dort einsetzbar, wo heute ``.qea`` gelesen wird.

Was gelesen wird
----------------
- **UML-Kern:** ``uml:Model`` mit verschachtelten ``packagedElement``
  (``uml:Package`` und Elemente) und Beziehungen (``client``/``supplier``,
  ``general``/``specific``).
- **EA-Erweiterungen:** ``xmi:Extension``-Bloecke mit ``stereotype``,
  ``properties`` (``ea_type``, ``alias``, ``status``, ``origin``), ``notes``,
  ``tags`` und ``xrefs`` (Tagged Values aus ``t_xref``).
- **Sichten:** ``<diagrams>`` mit Mitgliedern und Geometrie.

Kernentscheidungen (alle deterministisch):

- **Referenzkonvention wie im qea-Reader.** Kantenendpunkte werden
  ``<paketpfad>::<name>`` geschrieben, bei Namensgruppen > 1 mit ``#N``,
  unbenannte Elemente als ``<paketpfad>::#N``. Die Nummer ist die Position
  in der kanonischen Inhaltsreihenfolge ``(ea_type, notes, alias, status,
  tags)`` -- exakt die Sortierung aus ``qea_writer._element_index``.
  Kanten an Paketen werden als blanker Paketpfad geschrieben.
- **Pfaddisambiguierung wie im qea-Reader.** Gleichnamige Geschwisterpakete
  bekommen ``#2``, ``#3`` ... in Dokumentreihenfolge; der Anzeigename bleibt
  der ``name``-Eintrag im IR. Die Nummerierung geschieht beim Parsen -- die
  Elemente erben den bereits disambiguierten Pfad.
- **ea_type ist die Wahrheit.** Steht im Extension-Block ein ``ea_type``, gilt
  es; sonst wird die UML-Metaklasse abgebildet (``uml:Comment`` -> ``Note``).
- **GUIDs nur bei Abweichung.** Eine ``xmi:id`` wird ins IR uebernommen, wenn
  sie vom kanonischen Muster abweicht oder ``origin`` gesetzt ist -- sonst
  leitet der Writer sie wie gehabt aus dem Inhalt ab. Beziehungen tragen wie
  im qea-IR keine ``guid``.
- **Laut statt still:** ungueltiges XML, doppelte ``xmi:id``, haengende
  ``xmi:idref`` und nicht darstellbare Namen brechen mit ``XmiReaderError``
  ab. Es gibt keinen stillen Teil-Erfolg.

Oeffentliche API::

    from xmi_reader import read_xmi, read_xmi_ex, XmiReaderError

    ir = read_xmi("modell.xmi")              # dict, writer-kompatibel
    ir, report = read_xmi_ex("modell.xmi")   # dict + Statistiken/Warnungen
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from qea_writer import guid_for

IR_VERSION = 1

DEFAULT_OBJECT_TYPE = "Class"
DEFAULT_CONNECTOR_TYPE = "Dependency"
DEFAULT_DIRECTION = "Source -> Destination"

#: UML-Metaklasse (lokaler Name) -> EA-Object-Type, wenn der Extension-Block
#: kein ``ea_type`` traegt. Umkehrung der Schautafel im ``xmi_writer``.
UML_ZU_EA_TYPE: dict[str, str] = {
    "Activity": "Activity",
    "Actor": "Actor",
    "Artifact": "Artifact",
    "Class": "Class",
    "Component": "Component",
    "Constraint": "Constraint",
    "DataType": "DataType",
    "Enumeration": "Enumeration",
    "InformationFlow": "InformationFlow",
    "InstanceSpecification": "Object",
    "Interaction": "Interaction",
    "Interface": "Interface",
    "Comment": "Note",
    "Node": "Node",
    "Signal": "Signal",
    "State": "State",
    "StateMachine": "StateMachine",
    "UseCase": "UseCase",
}

UML_ZU_EA_CONNECTOR: dict[str, str] = {
    "Abstraction": "Abstraction",
    "Association": "Association",
    "Dependency": "Dependency",
    "Generalization": "Generalization",
    "InformationFlow": "InformationFlow",
    "Realization": "Realization",
}

#: XMI-Typen, die eine Beziehung darstellen (sonst Element).
BEZIEHUNG_TYPEN = frozenset(UML_ZU_EA_CONNECTOR)

_UNSICHTBAR = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class XmiReaderError(ValueError):
    """Lauter Fehler: unlesbare Datei, inkonsistentes Modell, Verlustgefahr."""


@dataclass
class ReadReport:
    """Zahlen und Warnungen eines Laufs."""

    packages: int = 0
    elements: int = 0
    connectors: int = 0
    element_tags: int = 0
    package_tags: int = 0
    connector_tags: int = 0
    diagrams: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------
# XML-Hilfen (Namensraum-unabhaengig: lokaler Name zaehlt)
# --------------------------------------------------------------------------


def _lokal(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _kinder(element: ET.Element, name: str) -> list[ET.Element]:
    return [k for k in element if _lokal(k.tag) == name]


def _kind(element: ET.Element, name: str) -> ET.Element | None:
    for k in element:
        if _lokal(k.tag) == name:
            return k
    return None


def _text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    # Keine Whitespace-Bereinigung: der qea-Reader hält Notizen exakt fest,
    # der Writer schreibt Texte inline -- beide Wege sind verlustfrei.
    return _UNSICHTBAR.sub("", element.text)


def _attr(element: ET.Element, *namen: str) -> str:
    for name in namen:
        wert = element.get(name)
        if wert is not None:
            return wert
    for key, wert in element.attrib.items():
        if _lokal(key) in namen:
            return wert
    return ""


# --------------------------------------------------------------------------
# Interne Haltestrukturen
# --------------------------------------------------------------------------


@dataclass
class _Item:
    """Paket, Element oder Beziehung in Lesereihenfolge."""

    art: str  # "paket" | "element" | "beziehung"
    name: str = ""
    paketpfad: str = ""
    stereotype: str = ""
    ea_type: str = ""
    notes: str = ""
    alias: str = ""
    status: str = ""
    origin: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    xref_tags: dict[str, str] = field(default_factory=dict)
    guid: str = ""
    position: int = 0
    # Beziehungen:
    quelle_id: str = ""
    ziel_id: str = ""
    richtung: str = ""


def _gilt_guid(guid: str, item: _Item) -> bool:
    """GUID ins IR uebernehmen, wenn sie nicht kanonisch ableitbar ist."""
    if not guid:
        return False
    if item.art == "beziehung":
        # Wie im qea-IR tragen Beziehungen keine guid.
        return False
    if item.origin:
        return True
    try:
        kanonisch = guid_for(item.paketpfad, item.stereotype, item.name)
    except Exception:  # noqa: BLE001 -- jede Ableitungsstrecke ist eine Abweichung
        return True
    return guid.upper() != kanonisch.upper()


# --------------------------------------------------------------------------
# Extension-Block auswerten
# --------------------------------------------------------------------------


def _extension(element: ET.Element, item: _Item) -> None:
    ext = _kind(element, "Extension")
    if ext is None:
        return
    stereotyp = _kind(ext, "stereotype")
    if stereotyp is not None:
        item.stereotype = _text(stereotyp)
    notes = _kind(ext, "notes")
    if notes is not None:
        item.notes = _text(notes)
    props = _kind(ext, "properties")
    if props is not None:
        item.ea_type = _attr(props, "ea_type") or item.ea_type
        item.alias = _attr(props, "alias")
        item.status = _attr(props, "status")
        item.origin = _attr(props, "origin")
    for tag_block in _kinder(ext, "tags"):
        for tag in _kinder(tag_block, "tag"):
            key = _attr(tag, "name")
            if key:
                item.tags[key] = _attr(tag, "value")
    for tag_block in _kinder(ext, "xrefs"):
        for tag in _kinder(tag_block, "tag"):
            key = _attr(tag, "name")
            if key:
                item.xref_tags[key] = _attr(tag, "value")


# --------------------------------------------------------------------------
# Baum lesen
# --------------------------------------------------------------------------


def _segment(name: str, benutzt: set[str], was: str) -> str:
    if "/" in name:
        raise XmiReaderError(f"{was}: '/' ist in Paketnamen nicht darstellbar ({name!r})")
    if not name:
        raise XmiReaderError(f"{was}: Paketname ist leer")
    kandidat = name
    zahl = 2
    while kandidat in benutzt:
        kandidat = f"{name}#{zahl}"
        zahl += 1
    benutzt.add(kandidat)
    return kandidat


def _knoten_lesen(
    element: ET.Element,
    elterpfad: str,
    geschwister: set[str],
    items: list[_Item],
    ids: dict[str, _Item],
    zaehler: list[int],
    warnungen: list[str],
) -> None:
    art = _attr(element, "xmi:type", "type")
    typ = art.split(":")[-1] if art else ""
    name = _attr(element, "name")
    guid = _attr(element, "xmi:id", "id")

    # Beziehung? Erkennungsmerkmal sind die Endpunkt-Kinder, nicht der Typ.
    quelle = _kind(element, "client")
    ziel = _kind(element, "supplier")
    if quelle is None and ziel is None:
        quelle = _kind(element, "specific")
        ziel = _kind(element, "general")

    if typ == "Package" and quelle is None:
        segment = _segment(name, geschwister, f"Paket {name!r}")
        pfad = f"{elterpfad}/{segment}" if elterpfad else segment
        item = _Item(art="paket", name=name, paketpfad=pfad, guid=guid)
        _extension(element, item)
        items.append(item)
        if guid:
            if guid in ids:
                raise XmiReaderError(f"doppelte xmi:id {guid!r}")
            ids[guid] = item
        eigene_geschwister: set[str] = set()
        for unter in element:
            lokal = _lokal(unter.tag)
            if lokal == "packagedElement":
                _knoten_lesen(
                    unter, pfad, eigene_geschwister, items, ids, zaehler, warnungen
                )
            elif lokal in {"Extension", "stereotype", "notes", "tags", "xrefs", "properties"}:
                pass
            else:
                warnungen.append(f"Paket {pfad!r}: Kind <{lokal}> wird nicht ausgewertet")
        return

    if quelle is not None or ziel is not None or typ in BEZIEHUNG_TYPEN:
        item = _Item(
            art="beziehung",
            name=name,
            guid=guid,
            ea_type=UML_ZU_EA_CONNECTOR.get(typ, DEFAULT_CONNECTOR_TYPE),
            quelle_id=_attr(quelle, "xmi:idref", "idref") if quelle is not None else "",
            ziel_id=_attr(ziel, "xmi:idref", "idref") if ziel is not None else "",
            richtung=_attr(element, "direction"),
        )
        _extension(element, item)
        if not item.ea_type:
            item.ea_type = DEFAULT_CONNECTOR_TYPE
        items.append(item)
        if guid:
            if guid in ids:
                raise XmiReaderError(f"doppelte xmi:id {guid!r}")
            ids[guid] = item
        return

    # Element
    item = _Item(
        art="element",
        name=name,
        paketpfad=elterpfad,
        guid=guid,
        ea_type=UML_ZU_EA_TYPE.get(typ, DEFAULT_OBJECT_TYPE),
    )
    _extension(element, item)
    if not item.ea_type:
        item.ea_type = DEFAULT_OBJECT_TYPE
    zaehler[0] += 1
    item.position = zaehler[0]
    # Herkunft aus dem Katalog (Tag ``Herkunft``) wird zur IR-Spalte ``origin``:
    # exakt die Ableitung des qea-Readers; der Tag selbst bleibt erhalten.
    herkunft = str(item.tags.get("Herkunft", "") or "").strip()
    if herkunft.startswith("katalog:"):
        item.origin = herkunft[len("katalog:"):]
    items.append(item)
    if guid:
        if guid in ids:
            raise XmiReaderError(f"doppelte xmi:id {guid!r}")
        ids[guid] = item


# --------------------------------------------------------------------------
# Referenzen
# --------------------------------------------------------------------------


def _refs_bauen(items: list[_Item]) -> dict[int, str]:
    """Ref-String je Element: ``paket::name``, ``paket::name#N``, ``paket::#N``."""
    gruppen: dict[tuple[str, str], list[_Item]] = {}
    for item in items:
        if item.art == "element":
            gruppen.setdefault((item.paketpfad, item.name), []).append(item)
    for gruppe in gruppen.values():
        # Exakt die Nummerierung des qea-Readers: Inhalt (content_key), dann
        # GUID als Tiebreak -- auch fuer inhaltlich identische Zwillinge.
        gruppe.sort(
            key=lambda e: (
                e.ea_type,
                e.notes,
                e.alias,
                e.status,
                tuple(sorted(e.tags.items())),
                e.origin,
                (e.guid or "").upper(),
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


def _ref_von(item: _Item, refs: Mapping[int, str]) -> str:
    if item.art == "paket":
        return item.paketpfad
    treffer = refs.get(id(item))
    if treffer is None:
        raise XmiReaderError(
            f"keine Referenz fuer {item.name!r} in {item.paketpfad!r}"
        )
    return treffer


def _mitglied_ref(item: _Item, refs: Mapping[int, str]) -> str:
    """Sichtmitglied: Ref-String, bei Mehrdeutigkeit die GUID.

    ``qea_writer._read_diagrams`` adressiert Mitglieder ueber
    ``paket::name`` (nur bei Eindeutigkeit) oder ueber die GUID -- die
    ``#N``-Form ist dort nicht aufloesbar.
    """
    ref = refs.get(id(item))
    gruppen_eindeutig = ref is not None and "#" not in ref
    if gruppen_eindeutig and item.name:
        return ref
    return item.guid.upper()


# --------------------------------------------------------------------------
# Sichten
# --------------------------------------------------------------------------


def _sichten_lesen(
    wurzel: ET.Element, ids: Mapping[str, _Item], refs: Mapping[int, str]
) -> list[dict[str, Any]]:
    """``<diagrams>``-Block -> IR-Sichtenliste."""
    diagrams: list[dict[str, Any]] = []
    for ext in [e for e in wurzel.iter() if _lokal(e.tag) == "Extension"]:
        for block in _kinder(ext, "diagrams"):
            for d in _kinder(block, "diagram"):
                name = _attr(d, "name")
                if not name:
                    raise XmiReaderError("Sicht ohne Namen ist nicht darstellbar")
                paket = _attr(d, "package")
                if not paket:
                    raise XmiReaderError(f"Sicht {name!r}: package-Attribut fehlt")
                eintrag: dict[str, Any] = {"name": name, "package": paket}
                typ = _attr(d, "type") or "Custom"
                if typ != "Custom":
                    eintrag["type"] = typ
                viewpoint = _attr(d, "viewpoint")
                if viewpoint:
                    eintrag["mdg"] = viewpoint
                parent = _attr(d, "parent")
                if parent:
                    eintrag["parent"] = parent
                if _attr(d, "default") in {"1", "true", "True"}:
                    eintrag["default"] = True
                stereotyp = _kind(d, "stereotype")
                if stereotyp is not None and _text(stereotyp):
                    eintrag["stereotype"] = _text(stereotyp)
                notes = _kind(d, "notes")
                if notes is not None and _text(notes):
                    eintrag["notes"] = _text(notes)
                mitglieder: list[dict[str, Any]] = []
                for element_block in _kinder(d, "elements"):
                    for m in _kinder(element_block, "element"):
                        ziel_id = _attr(m, "xmi:idref", "idref")
                        ziel = ids.get(ziel_id)
                        if ziel is None:
                            raise XmiReaderError(
                                f"Sicht {name!r}: Mitglied {ziel_id!r} zeigt auf nichts"
                            )
                        if ziel.art != "element":
                            raise XmiReaderError(
                                f"Sicht {name!r}: Mitglied {ziel_id!r} ist kein Element"
                            )
                        mitglied: dict[str, Any] = {
                            "element": _mitglied_ref(ziel, refs)
                        }
                        for feld in ("left", "top", "right", "bottom", "sequence"):
                            wert = _attr(m, feld)
                            if wert != "":
                                try:
                                    mitglied[feld] = int(wert)
                                except ValueError as exc:
                                    raise XmiReaderError(
                                        f"Sicht {name!r}: {feld}={wert!r} ist keine Zahl"
                                    ) from exc
                        mitglieder.append(mitglied)
                eintrag["members"] = mitglieder
                diagrams.append(eintrag)
    return diagrams


# --------------------------------------------------------------------------
# Oeffentliche API
# --------------------------------------------------------------------------


def read_xmi_ex(path: str | Path) -> tuple[dict[str, Any], ReadReport]:
    """Liest eine .xmi und liefert (IR-Dict, ReadReport)."""
    quelle = Path(path)
    try:
        roh = quelle.read_bytes()
    except OSError as exc:
        raise XmiReaderError(f"{quelle}: nicht lesbar ({exc})") from exc
    try:
        wurzel = ET.fromstring(roh)
    except ET.ParseError as exc:
        raise XmiReaderError(f"{quelle}: XML nicht parsebar ({exc})") from exc

    if _lokal(wurzel.tag) != "XMI":
        raise XmiReaderError(
            f"{quelle}: Wurzelelement ist <{_lokal(wurzel.tag)}>, <XMI> erwartet"
        )

    model = None
    for kind in wurzel:
        if _lokal(kind.tag) == "Model":
            model = kind
            break
    if model is None:
        raise XmiReaderError(f"{quelle}: kein <uml:Model> im Dokument")

    items: list[_Item] = []
    ids: dict[str, _Item] = {}
    zaehler = [0]
    warnungen: list[str] = []

    wurzel_geschwister: set[str] = set()
    for kind in model:
        if _lokal(kind.tag) == "packagedElement":
            _knoten_lesen(kind, "", wurzel_geschwister, items, ids, zaehler, warnungen)

    # Technologie aus dem EA-Extension-Block (profile/name/version).
    technologie: dict[str, str] = {}
    for ext in [e for e in wurzel.iter() if _lokal(e.tag) == "Extension"]:
        for tech in _kinder(ext, "technology"):
            for feld in ("profile", "name", "version"):
                wert = _attr(tech, feld)
                if wert:
                    technologie[feld] = wert

    refs = _refs_bauen(items)

    package_items: list[dict[str, Any]] = []
    element_items: list[dict[str, Any]] = []
    connectors: list[dict[str, Any]] = []
    tag_zaehler = {"paket": 0, "element": 0, "beziehung": 0}

    for item in items:
        if item.art == "paket":
            segment = item.paketpfad.rsplit("/", 1)[-1]
            eintrag: dict[str, Any] = {"path": item.paketpfad}
            if item.name != segment:
                eintrag["name"] = item.name
            if item.stereotype:
                eintrag["stereotype"] = item.stereotype
            if item.notes:
                eintrag["notes"] = item.notes
            if item.tags:
                eintrag["tags"] = dict(sorted(item.tags.items()))
                tag_zaehler["paket"] += len(item.tags)
            package_items.append(eintrag)
        elif item.art == "element":
            eintrag = {"package": item.paketpfad, "name": item.name}
            if item.stereotype:
                eintrag["stereotype"] = item.stereotype
            eintrag["ea_type"] = item.ea_type
            if item.notes:
                eintrag["notes"] = item.notes
            if item.alias:
                eintrag["alias"] = item.alias
            if item.status:
                eintrag["status"] = item.status
            if item.tags:
                eintrag["tags"] = dict(sorted(item.tags.items()))
                tag_zaehler["element"] += len(item.tags)
            if item.xref_tags:
                eintrag["xref_tags"] = dict(sorted(item.xref_tags.items()))
                tag_zaehler["element"] += len(item.xref_tags)
            if item.origin:
                eintrag["origin"] = item.origin
            if _gilt_guid(item.guid, item):
                eintrag["guid"] = item.guid.upper()
            element_items.append(eintrag)
        else:
            if not item.quelle_id or not item.ziel_id:
                raise XmiReaderError(
                    f"Beziehung {item.guid or item.name!r}: Quelle oder Ziel fehlt"
                )
            quelle = ids.get(item.quelle_id)
            ziel = ids.get(item.ziel_id)
            if quelle is None or ziel is None:
                haengend = item.quelle_id if quelle is None else item.ziel_id
                raise XmiReaderError(
                    f"Beziehung {item.guid or item.name!r}: "
                    f"Endpunkt {haengend!r} zeigt auf nichts"
                )
            eintrag = {"source": _ref_von(quelle, refs), "target": _ref_von(ziel, refs)}
            if item.stereotype:
                eintrag["stereotype"] = item.stereotype
            eintrag["ea_type"] = item.ea_type or DEFAULT_CONNECTOR_TYPE
            if item.name:
                eintrag["name"] = item.name
            if item.richtung and item.richtung != DEFAULT_DIRECTION:
                eintrag["direction"] = item.richtung
            if item.notes:
                eintrag["notes"] = item.notes
            if item.tags:
                eintrag["tags"] = dict(sorted(item.tags.items()))
                tag_zaehler["beziehung"] += len(item.tags)
            connectors.append(eintrag)

    connectors.sort(
        key=lambda c: (
            c["source"],
            c["target"],
            c.get("stereotype", ""),
            c.get("name", ""),
            c["ea_type"],
            c.get("direction", ""),
            c.get("notes", ""),
            tuple(sorted(c.get("tags", {}).items())),
        )
    )
    package_items.sort(key=lambda p: p["path"])
    element_items.sort(
        key=lambda e: (
            e["package"],
            e["name"],
            e["ea_type"],
            e.get("stereotype", ""),
            e.get("notes", ""),
            e.get("alias", ""),
            e.get("status", ""),
            tuple(sorted(e.get("tags", {}).items())),
        )
    )

    diagrams = _sichten_lesen(wurzel, ids, refs)

    ir: dict[str, Any] = {"ir_version": IR_VERSION}
    if technologie:
        ir["technology"] = {k: v for k, v in sorted(technologie.items()) if v}
    ir["packages"] = package_items
    ir["elements"] = element_items
    ir["connectors"] = connectors
    ir["diagrams"] = diagrams

    report = ReadReport(
        packages=len(package_items),
        elements=len(element_items),
        connectors=len(connectors),
        element_tags=tag_zaehler["element"],
        package_tags=tag_zaehler["paket"],
        connector_tags=tag_zaehler["beziehung"],
        diagrams=len(diagrams),
        warnings=tuple(warnungen),
    )
    return ir, report


def read_xmi(path: str | Path) -> dict[str, Any]:
    """Liest eine .xmi und liefert das IR-Dict (writer-kompatibel)."""
    ir, _report = read_xmi_ex(path)
    return ir


def main() -> int:
    ap = argparse.ArgumentParser(description="XMI 2.1 -> IR-JSON")
    ap.add_argument("xmi", type=Path, help="XMI-Datei")
    ap.add_argument("-o", "--out", type=Path, default=None, help="IR-JSON schreiben")
    args = ap.parse_args()
    ir, report = read_xmi_ex(args.xmi)
    text = json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"geschrieben: {args.out}")
    else:
        sys.stdout.write(text)
    print(
        f"{report.packages} Pakete, {report.elements} Elemente, "
        f"{report.connectors} Beziehungen, {report.diagrams} Sichten",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())