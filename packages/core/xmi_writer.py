"""xmi_writer.py -- IR -> XMI 2.1 (UML 2.x + EA-Erweiterungen).

Bestimmung
----------
Nimmt ein IR nach ``IR_SPEC.md`` (``qea_reader``, ``extract.py``,
``table_import.py``) und schreibt eine **XMI 2.1**-Datei: UML-2.x-Kern
(``uml:Model``/``packagedElement``) plus ``xmi:Extension``-Bloecke fuer
Stereotypen, Tagged Values, Notizen und Sichten. Damit ist ``.xmi`` ein
vollwertiges Ausgabeformat neben ``.qea`` -- selbe Quelle, selbes Regelwerk,
dasselbe Governance-Gate, anderes Ziel.

Aufbau der Datei::

    <xmi:XMI xmi:version="2.1">
      <uml:Model xmi:type="uml:Model" ...>          Pakete/Elemente verschachtelt
      <xmi:Extension extender="Enterprise Architect">
        <connectors> ... </connectors>              Beziehungen (EA-Dialekt)
        <diagrams>   ... </diagrams>                Sichten + Mitglieder
      </xmi:Extension>
    </xmi:XMI>

Kernentscheidungen (alle deterministisch):

- **Ein Plan, drei Formate.** Sortierung, GUID-Ableitung und Referenz-
  Aufloesung kommen ausschliesslich aus ``qea_writer.plan_model`` -- der
  XMI-Writer erfindet nichts und bildet nur ab. Gleiche IR-Eingabe ->
  byte-identische ``.xmi``.
- **EA-Typen bleiben erhalten.** Jedes Element und jede Beziehung traegt den
  EA-Object-/Connector-Type als Attribut ``ea_type`` im Extension-Block. Die
  UML-Metaklasse im Kern ist die beste Abbildung fuer Fremdwerkzeuge, nicht
  die Wahrheit -- wer die Datei zurueckliest, bekommt den Originaltyp.
- **Pakete verschachteln sich** wie im IR (``path`` mit ``/``); Elemente
  stehen in ihrem Paket, Beziehungen im Paket ihres Quellelements.
- **Sichten** stehen im EA-Dialekt: ``<diagram>`` mit ``<elements>`` und
  Geometrie. Leere Geometrie ist erlaubt (EA ordnet beim Oeffnen an).
- **Keine Zeitstempel, keine Zufallswerte.** GUIDs stammen aus dem Plan
  (Inhalts-Hash oder IR-Vorgabe). Zwei Laeufe auf gleichem IR -> gleiche Bytes.
- **Laut statt still:** ungueltiges IR bricht mit ``XmiWriterError`` ab --
  derselbe Lauf wie im ``.qea``-Pfad, nur ein anderes Ziel.

Oeffentliche API::

    from xmi_writer import write_xmi, render_bytes, XmiWriterError

    write_xmi(ir, "modell.xmi")   # IR-Dict oder Pfad zur IR-JSON
    daten = render_bytes(ir)      # bytes

Fehler werden laut geworfen (``XmiWriterError``), nie still verschluckt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, NoReturn
from xml.sax.saxutils import escape, quoteattr

from qea_writer import ModelPlan, QeaWriterError, plan_model

#: EA-Object-Type -> UML-Metaklasse. Fuer Fremdwerkzeuge; die Wahrheit steht
#: als ``ea_type`` im Extension-Block. Alles ohne Eintrag wird ``uml:Class``.
EA_TYPE_ZU_UML: dict[str, str] = {
    "Activity": "uml:Activity",
    "Actor": "uml:Actor",
    "Artifact": "uml:Artifact",
    "Association": "uml:Association",
    "Boundary": "uml:Class",
    "Change": "uml:Class",
    "Class": "uml:Class",
    "Component": "uml:Component",
    "Constraint": "uml:Constraint",
    "DataType": "uml:DataType",
    "Entity": "uml:Class",
    "Enumeration": "uml:Enumeration",
    "Interface": "uml:Interface",
    "Interaction": "uml:Interaction",
    "Node": "uml:Node",
    "Note": "uml:Comment",
    "Object": "uml:InstanceSpecification",
    "Package": "uml:Package",
    "Requirement": "uml:Class",
    "Signal": "uml:Signal",
    "State": "uml:State",
    "StateMachine": "uml:StateMachine",
    "Text": "uml:Comment",
    "UseCase": "uml:UseCase",
}

#: EA-Connector-Type -> UML-Metaklasse. ``Aggregation``/``Composition`` sind
#: UML-seitig eine Association mit Aggregationsgrad -- die Genauigkeit bleibt
#: als ``ea_type`` im Extension-Block.
CONNECTOR_ZU_UML: dict[str, str] = {
    "Abstraction": "uml:Dependency",
    "Aggregation": "uml:Association",
    "Assembly": "uml:Dependency",
    "Association": "uml:Association",
    "Composition": "uml:Association",
    "Connector": "uml:Association",
    "Dependency": "uml:Dependency",
    "Generalization": "uml:Generalization",
    "InformationFlow": "uml:InformationFlow",
    "Manifest": "uml:Dependency",
    "NoteLink": "uml:Dependency",
    "Realization": "uml:Realization",
    "Substitution": "uml:Dependency",
    "Trace": "uml:Dependency",
    "Usage": "uml:Dependency",
}

XMI_NS = "http://www.omg.org/spec/XMI/20131001"
UML_NS = "http://www.omg.org/spec/UML/20131001"

INDENT = "  "


class XmiWriterError(ValueError):
    """Eingabe- oder Zustandsfehler. Immer laut, nie still."""


def _fail(message: str) -> NoReturn:
    raise XmiWriterError(message)


# --------------------------------------------------------------------------
# XML-Hilfen (von Hand, damit Zeilenumbrueche und Reihenfolgen feststehen)
# --------------------------------------------------------------------------


def _attr(name: str, value: Any) -> str:
    serialisiert = quoteattr(str(value))
    # Attributwert-Normalisierung des XML-Parsers (CR/LF/Tab -> Space) durch
    # Zeichenreferenzen aushebeln -- Tagged Values duerfen Umbrueche tragen.
    # Ersetzt wird die SERIALIZIERTE Form, sonst maskiert quoteattr das '&'.
    serialisiert = (
        serialisiert.replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")
    )
    return f" {name}={serialisiert}"


def _leer(tag: str, attrs: str = "", tiefe: int = 0) -> str:
    return f"{INDENT * tiefe}<{tag}{attrs}/>"


def _block(tag: str, attrs: str, inhalt: list[str], tiefe: int = 0) -> list[str]:
    kopf = f"{INDENT * tiefe}<{tag}{attrs}>"
    schluss = f"{INDENT * tiefe}</{tag}>"
    return [kopf, *inhalt, schluss]


def _textblock(tag: str, text: str, tiefe: int = 0) -> list[str]:
    # Text inline -- ein eingerueckter Textknoten wuerde beim Lesen
    # Formatierungs-Whitespace in den Wert ziehen. CR bleibt als
    # Zeichenreferenz erhalten (der Parser normalisiert Zeilenenden sonst).
    inhalt = escape(text).replace("\r", "&#13;")
    return [f"{INDENT * tiefe}<{tag}>{inhalt}</{tag}>"]


# --------------------------------------------------------------------------
# Abbildung Plan -> XMI
# --------------------------------------------------------------------------


def _model_guid(plan: ModelPlan) -> str:
    roh = f"model|{plan.profile or ''}".encode("utf-8")
    return _digest_guid(roh)


def _digest_guid(roh: bytes) -> str:
    wert = hashlib.sha256(roh).hexdigest()
    return (
        "{"
        + f"{wert[0:8]}-{wert[8:12]}-{wert[12:16]}-{wert[16:20]}-{wert[20:32]}"
        + "}"
    ).upper()


def _tags_block(tags: tuple[tuple[str, str], ...], tiefe: int) -> list[str]:
    if not tags:
        return []
    zeilen = [
        f"{INDENT * tiefe}<tags>",
        *[
            f"{INDENT * (tiefe + 1)}<tag{_attr('name', k)}{_attr('value', v)}/>"
            for k, v in tags
        ],
        f"{INDENT * tiefe}</tags>",
    ]
    return zeilen


def _element_extension(element: Any, tiefe: int) -> list[str]:
    """EA-Erweiterung eines Elements: Typ, Stereotyp, Notizen, Tags, Herkunft."""
    attrs = ""
    props = _attr("ea_type", element.ea_type)
    if element.alias:
        props += _attr("alias", element.alias)
    if element.status:
        props += _attr("status", element.status)
    if element.origin:
        props += _attr("origin", element.origin)
    inhalt: list[str] = []
    if element.stereotype:
        inhalt += _textblock("stereotype", element.stereotype, tiefe + 1)
    inhalt += _leer("properties", props, tiefe + 1).splitlines()
    if element.notes:
        inhalt += _textblock("notes", element.notes, tiefe + 1)
    inhalt += _tags_block(element.tags, tiefe + 1)
    if element.xref_tags:
        inhalt += _block(
            "xrefs", "",
            [
                f"{INDENT * (tiefe + 2)}<tag{_attr('name', k)}{_attr('value', v)}/>"
                for k, v in element.xref_tags
            ],
            tiefe + 1,
        )
    return _block("xmi:Extension", _attr("extender", "Enterprise Architect"), inhalt, tiefe)


def _element_zeilen(element: Any, tiefe: int, idmap: dict[int, str]) -> list[str]:
    uml = EA_TYPE_ZU_UML.get(element.ea_type, "uml:Class")
    # Unbenannte Elemente: name="" bleibt gesetzt, damit die ID-Zuordnung
    # eindeutig bleibt.
    attrs = _attr("xmi:type", uml) + _attr("xmi:id", element.guid) + _attr("name", element.name)
    idmap[element.object_id] = element.guid
    return _block("packagedElement", attrs, _element_extension(element, tiefe + 1), tiefe)


def _ref_guid(ref: Any) -> str:
    if ref is None:  # pragma: no cover -- plan_model bricht vorher ab
        return ""
    if ref.kind == "element" and ref.element is not None:
        return ref.element.guid
    if ref.kind == "package" and ref.package is not None:
        return ref.package.guid
    return ""  # pragma: no cover -- plan_model bricht vorher ab


def _connector_zeilen(connector: Any, tiefe: int) -> list[str]:
    uml = CONNECTOR_ZU_UML.get(connector.ea_type, "uml:Dependency")
    attrs = _attr("xmi:type", uml) + _attr("xmi:id", connector.guid)
    if connector.name:
        attrs += _attr("name", connector.name)
    if connector.direction and connector.direction != "Source -> Destination":
        attrs += _attr("direction", connector.direction)

    quelle = _ref_guid(connector.source)
    ziel = _ref_guid(connector.target)
    if not quelle or not ziel:  # pragma: no cover -- plan_model bricht vorher ab
        _fail(f"Beziehung {connector.guid}: Quelle oder Ziel ohne Kennung")

    kern: list[str] = []
    if uml == "uml:Generalization":
        kern.append(_leer("specific", _attr("xmi:idref", quelle), tiefe + 1))
        kern.append(_leer("general", _attr("xmi:idref", ziel), tiefe + 1))
    else:
        kern.append(_leer("client", _attr("xmi:idref", quelle), tiefe + 1))
        kern.append(_leer("supplier", _attr("xmi:idref", ziel), tiefe + 1))

    ext_inhalt: list[str] = [_leer("properties", _attr("ea_type", connector.ea_type), tiefe + 1)]
    if connector.stereotype:
        ext_inhalt += _textblock("stereotype", connector.stereotype, tiefe + 1)
    if connector.notes:
        ext_inhalt += _textblock("notes", connector.notes, tiefe + 1)
    ext_inhalt += _tags_block(connector.tags, tiefe + 1)
    kern += _block(
        "xmi:Extension", _attr("extender", "Enterprise Architect"), ext_inhalt, tiefe + 1
    )
    return _block("packagedElement", attrs, kern, tiefe)


def _diagram_zeilen(diagram: Any, tiefe: int, idmap: dict[int, str]) -> list[str]:
    attrs = (
        _attr("xmi:id", diagram.guid)
        + _attr("name", diagram.name)
        + _attr("type", diagram.diagram_type)
        + _attr("package", diagram.package_path)
    )
    if diagram.parent_name:
        attrs += _attr("parent", diagram.parent_name)
    if diagram.is_default:
        attrs += _attr("default", "1")
    if diagram.mdg_viewpoint:
        attrs += _attr("viewpoint", diagram.mdg_viewpoint)

    inhalt: list[str] = []
    if diagram.stereotype:
        inhalt += _textblock("stereotype", diagram.stereotype, tiefe + 1)
    if diagram.notes:
        inhalt += _textblock("notes", diagram.notes, tiefe + 1)
    mitglieder: list[str] = []
    for mitglied in diagram.members:
        ziel = idmap.get(mitglied.object_id)
        if not ziel:  # pragma: no cover -- plan_model prueft die Mitglieder
            _fail(f"Sicht {diagram.name}: Mitglied ohne Element-Kennung")
        mitglieder.append(
            _leer(
                "element",
                _attr("xmi:idref", ziel)
                + _attr("left", mitglied.left)
                + _attr("top", mitglied.top)
                + _attr("right", mitglied.right)
                + _attr("bottom", mitglied.bottom)
                + _attr("sequence", mitglied.sequence),
                tiefe + 2,
            )
        )
    inhalt += _block("elements", "", mitglieder, tiefe + 1)
    return _block("diagram", attrs, inhalt, tiefe)


def _natuerlich(pfad: str) -> list[Any]:
    """Sortierschluessel mit Zahlensinn: ``P#2`` vor ``P#10``.

    Die Disambiguierung gleichnamiger Geschwister (``#2``, ``#3`` ...) ist
    numerisch; eine lexikographische Sortierung wuerde ``#10`` vor ``#2``
    stellen und beim Zuruecklesen die Nummern permutieren.
    """
    teile: list[Any] = []
    for stueck in re.split(r"(\d+)", pfad):
        teile.append(int(stueck) if stueck.isdigit() else stueck)
    return teile


def _paket_baum(plan: ModelPlan, tiefe: int, idmap: dict[int, str]) -> list[str]:
    """Pakete verschachtelt, Elemente darin, Beziehungen im Quellpaket."""
    von_pfad = {p.path: p for p in plan.packages}
    kinder: dict[str, list[Any]] = {p.path: [] for p in plan.packages}
    wurzel: list[Any] = []
    for paket in sorted(plan.packages, key=lambda p: _natuerlich(p.path)):
        eltern = paket.parent_path
        if eltern in kinder:
            kinder[eltern].append(paket)
        else:
            wurzel.append(paket)

    elemente_pro_paket: dict[str, list[Any]] = {}
    for element in plan.elements:
        elemente_pro_paket.setdefault(element.package_path, []).append(element)

    beziehungen_pro_paket: dict[str, list[Any]] = {}
    for connector in plan.connectors:
        pfad = ""
        if connector.source is not None:
            pfad = connector.source.package_path
        beziehungen_pro_paket.setdefault(pfad, []).append(connector)

    def knoten(paket: Any, tiefe: int) -> list[str]:
        attrs = _attr("xmi:type", "uml:Package") + _attr("xmi:id", paket.guid) + _attr("name", paket.name)
        ext_inhalt: list[str] = []
        if paket.stereotype:
            ext_inhalt += _textblock("stereotype", paket.stereotype, tiefe + 2)
        if paket.notes:
            ext_inhalt += _textblock("notes", paket.notes, tiefe + 2)
        ext_inhalt += _tags_block(paket.tags, tiefe + 2)
        inhalt: list[str] = []
        if ext_inhalt:
            inhalt += _block(
                "xmi:Extension", _attr("extender", "Enterprise Architect"), ext_inhalt, tiefe + 1
            )
        for unter in sorted(kinder.get(paket.path, []), key=lambda p: _natuerlich(p.path)):
            inhalt += knoten(unter, tiefe + 1)
        for element in elemente_pro_paket.get(paket.path, []):
            inhalt += _element_zeilen(element, tiefe + 1, idmap)
        for connector in beziehungen_pro_paket.get(paket.path, []):
            inhalt += _connector_zeilen(connector, tiefe + 1)
        return _block("packagedElement", attrs, inhalt, tiefe)

    zeilen: list[str] = []
    for paket in sorted(wurzel, key=lambda p: _natuerlich(p.path)):
        zeilen += knoten(paket, tiefe)
    # Beziehungen, deren Quelle ein Element ohne Paketknoten ist (darf bei
    # plan_model nicht vorkommen) und Quellpakete selbst:
    for pfad in sorted(beziehungen_pro_paket):
        if pfad in von_pfad:
            continue
        for connector in beziehungen_pro_paket[pfad]:
            zeilen += _connector_zeilen(connector, tiefe)
    return zeilen


def render_bytes(ir: Any) -> bytes:
    """IR -> XMI-Bytes. Deterministisch: gleiches IR -> gleiche Bytes."""
    try:
        plan = plan_model(ir)
    except QeaWriterError as exc:
        raise XmiWriterError(str(exc)) from exc

    idmap: dict[int, str] = {}
    paket_kern = _paket_baum(plan, 2, idmap)

    model_attrs = (
        _attr("xmi:type", "uml:Model")
        + _attr("xmi:id", _model_guid(plan))
        + _attr("name", "Model")
    )

    ext_inhalt: list[str] = []
    technologie = ir.get("technology") if isinstance(ir, Mapping) else None
    if isinstance(technologie, Mapping):
        attrs = ""
        for feld in ("profile", "name", "version"):
            wert = str(technologie.get(feld, "") or "")
            if wert:
                attrs += _attr(feld, wert)
        if attrs:
            ext_inhalt.append(_leer("technology", attrs, 2))
    connector_block: list[str] = []
    for connector in plan.connectors:
        # Im Kern steht die Beziehung schon (packagedElement). Der
        # EA-Block referenziert sie -- fuer Werkzeuge, die nur den
        # Extension-Dialekt lesen.
        connector_block.append(_leer("ref", _attr("xmi:idref", connector.guid), 3))
    ext_inhalt += _block("connectors", "", connector_block, 2)

    diagram_block: list[str] = []
    for d in sorted(plan.diagrams, key=lambda d: (d.package_path, d.name)):
        diagram_block.extend(_diagram_zeilen(d, 3, idmap))
    ext_inhalt += _block("diagrams", "", diagram_block, 2)

    zeilen: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<xmi:XMI{_attr("xmi:version", "2.1")} xmlns:xmi={quoteattr(XMI_NS)} xmlns:uml={quoteattr(UML_NS)}>',
    ]
    zeilen += _block("uml:Model", model_attrs, paket_kern, 1)
    zeilen += _block(
        "xmi:Extension", _attr("extender", "Enterprise Architect"), ext_inhalt, 1
    )
    zeilen.append("</xmi:XMI>")
    return ("\n".join(zeilen) + "\n").encode("utf-8")


def write_xmi(
    ir: "Mapping[str, Any] | str | os.PathLike[str]", target: str | os.PathLike[str]
) -> Path:
    """Schreibt die XMI-Datei und liefert ihren Pfad."""
    daten = ir
    if isinstance(ir, (str, os.PathLike)):
        pfad = Path(ir)
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise XmiWriterError(f"IR nicht lesbar: {pfad} ({exc})") from exc
    roh = render_bytes(daten)
    ziel = Path(target)
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(roh)
    except OSError as exc:
        raise XmiWriterError(f"{ziel} nicht schreibbar ({exc})") from exc
    return ziel


def main() -> int:
    ap = argparse.ArgumentParser(description="IR -> XMI 2.1")
    ap.add_argument("ir", type=Path, help="IR-JSON")
    ap.add_argument("-o", "--out", type=Path, required=True, help="Ziel .xmi")
    args = ap.parse_args()
    pfad = write_xmi(args.ir, args.out)
    print(f"geschrieben: {pfad} ({pfad.stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
