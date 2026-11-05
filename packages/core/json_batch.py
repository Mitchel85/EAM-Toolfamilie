"""json_batch.py -- IR zu JSON-Batch (Knoten/Kanten, z.B. fuer ArAMIS/Neo4j).

``.json`` ist ein Ausgabeformat wie ``.qea`` und ``.xmi``: dieselbe Quelle,
dasselbe Regelwerk, dasselbe Governance-Gate -- nur ein anderes Ziel. Das
Modell wird als Graph ausgegeben: ``nodes[]`` fuer Pakete und Elemente,
``edges[]`` fuer Beziehungen. Das verbindliche Schema liegt in
``batch-schema.json`` (JSON Schema Draft 2020-12).

Kernentscheidungen (alle deterministisch):

- **Ein Plan, drei Formate.** Reihenfolge, Kennungen und Endpunkt-Aufloesung
  kommen ausschliesslich aus ``qea_writer.plan_model`` -- auch hier erfindet
  der Exporteur nichts. Gleiche IR-Eingabe -> byte-identisches JSON.
- **Pakete sind Knoten.** Eine Beziehung kann an einem Paket enden (EA-
  Spiegel); ohne Paketknoten waere die Kante nicht darstellbar. Paketknoten
  tragen ``metaclass: "Package"`` und den vollen Pfad als ``name``.
- **Metadaten sind Angaben, keine Behauptungen.** ``node_count``/``edge_count``
  sind die Laengen der Arrays, ``standard`` kommt aus
  ``technology.profile``, ``source_document`` ist eine Angabe des Aufrufers.
- **Laut statt still:** ungueltiges IR bricht mit ``JsonBatchError`` ab.

Oeffentliche API::

    from json_batch import write_json_batch, render_text, JsonBatchError

    write_json_batch(ir, "modell.json", source_document="auftrag.md")
    text = render_text(ir, source_document="auftrag.md")
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, NoReturn

from qea_writer import QeaWriterError, plan_model

GENERATOR = "eam-ai-json-batch"


class JsonBatchError(ValueError):
    """Eingabe- oder Zustandsfehler. Immer laut, nie still."""


def _fail(message: str) -> NoReturn:
    raise JsonBatchError(message)


def _upper_snake(text: str) -> str:
    """``CapabilityDependency`` -> ``CAPABILITY_DEPENDENCY``."""
    getrennt = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    return re.sub(r"[^A-Za-z0-9]+", "_", getrennt).strip("_").upper() or "RELATION"


def _knoten(knoten_id: str, name: str, stereotype: str, metaclass: str, package: str = "") -> dict[str, Any]:
    labels = [stereotype] if stereotype else [metaclass]
    eintrag: dict[str, Any] = {
        "id": knoten_id,
        "name": name,
        "metaclass": metaclass,
        "labels": labels,
    }
    if stereotype:
        eintrag["stereotype"] = stereotype
    if package:
        eintrag["package"] = package
    return eintrag


def render_text(ir: Any, *, source_document: str = "") -> str:
    """IR -> JSON-Text. Deterministisch: gleiches IR -> gleicher Text."""
    if not source_document or not str(source_document).strip():
        _fail("source_document: Angabe fehlt (mindestens ein Zeichen)")
    try:
        plan = plan_model(ir)
    except QeaWriterError as exc:
        raise JsonBatchError(str(exc)) from exc

    profil = ""
    if isinstance(ir, Mapping):
        technologie = ir.get("technology")
        if isinstance(technologie, Mapping):
            profil = str(technologie.get("profile", "") or "")

    knoten: list[dict[str, Any]] = []
    id_von: dict[tuple[str, int], str] = {}

    # Pakete zuerst (sortiert im Plan), dann Elemente -- beide bekommen
    # fortlaufende Knotennummern in Ausgabereihenfolge.
    for paket in plan.packages:
        nummer = len(knoten) + 1
        knoten_id = f"n{nummer}"
        eintrag = _knoten(
            knoten_id, paket.path, paket.stereotype, "Package"
        )
        if paket.notes:
            eintrag["properties"] = {"notes": paket.notes}
        if paket.tags:
            eintrag.setdefault("properties", {}).update(dict(paket.tags))
        knoten.append(eintrag)
        id_von[("paket", paket.package_id)] = knoten_id

    for element in plan.elements:
        nummer = len(knoten) + 1
        knoten_id = f"n{nummer}"
        eintrag = _knoten(
            knoten_id, element.name, element.stereotype, element.ea_type,
            package=element.package_path,
        )
        eigenschaften: dict[str, Any] = {}
        if element.notes:
            eigenschaften["notes"] = element.notes
        if element.alias:
            eigenschaften["alias"] = element.alias
        if element.status:
            eigenschaften["status"] = element.status
        if element.origin:
            eigenschaften["origin"] = element.origin
        eigenschaften.update(dict(element.tags))
        if eigenschaften:
            eintrag["properties"] = dict(sorted(eigenschaften.items()))
        knoten.append(eintrag)
        id_von[("element", element.object_id)] = knoten_id

    def endpunkt(ref: Any, was: str) -> str:
        if ref is None:  # pragma: no cover -- plan_model bricht vorher ab
            _fail(f"{was}: Endpunkt ohne Referenz")
        if ref.kind == "element" and ref.element is not None:
            schluessel = ("element", ref.element.object_id)
        elif ref.kind == "package" and ref.package is not None:
            schluessel = ("paket", ref.package.package_id)
        else:  # pragma: no cover -- plan_model bricht vorher ab
            _fail(f"{was}: Endpunkt ohne Ziel")
        treffer = id_von.get(schluessel)
        if treffer is None:  # pragma: no cover -- plan_model bricht vorher ab
            _fail(f"{was}: Endpunkt zeigt auf keinen Knoten")
        return treffer

    kanten: list[dict[str, Any]] = []
    for nummer, connector in enumerate(plan.connectors, start=1):
        connector_name = connector.stereotype or connector.ea_type
        eintrag: dict[str, Any] = {
            "id": f"e{nummer}",
            "source_id": endpunkt(connector.source, f"Kante e{nummer}"),
            "target_id": endpunkt(connector.target, f"Kante e{nummer}"),
            "connector": connector_name,
            "type": _upper_snake(connector_name),
            "metaclass": connector.ea_type,
        }
        eigenschaften = {}
        if connector.name:
            eintrag["name"] = connector.name
        if connector.notes:
            eigenschaften["notes"] = connector.notes
        eigenschaften.update(dict(connector.tags))
        if eigenschaften:
            eintrag["properties"] = dict(sorted(eigenschaften.items()))
        kanten.append(eintrag)

    daten = {
        "metadata": {
            "generator": GENERATOR,
            "standard": profil,
            "source_document": str(source_document),
            "node_count": len(knoten),
            "edge_count": len(kanten),
        },
        "nodes": knoten,
        "edges": kanten,
    }
    return json.dumps(daten, ensure_ascii=False, indent=2) + "\n"


def write_json_batch(
    ir: "Mapping[str, Any] | str | os.PathLike[str]",
    target: str | os.PathLike[str],
    *,
    source_document: str = "",
) -> Path:
    """Schreibt die JSON-Datei und liefert ihren Pfad."""
    daten = ir
    if isinstance(ir, (str, os.PathLike)):
        pfad = Path(ir)
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JsonBatchError(f"IR nicht lesbar: {pfad} ({exc})") from exc
    text = render_text(daten, source_document=source_document)
    ziel = Path(target)
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise JsonBatchError(f"{ziel} nicht schreibbar ({exc})") from exc
    return ziel


def main() -> int:
    ap = argparse.ArgumentParser(description="IR -> JSON-Batch (Knoten/Kanten)")
    ap.add_argument("ir", type=Path, help="IR-JSON")
    ap.add_argument("-o", "--out", type=Path, required=True, help="Ziel .json")
    ap.add_argument(
        "--source-document",
        default="",
        help="Angabe der Quelle fuer metadata.source_document",
    )
    args = ap.parse_args()
    quelle = args.source_document or args.ir.name
    pfad = write_json_batch(args.ir, args.out, source_document=quelle)
    print(f"geschrieben: {pfad} ({pfad.stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
