"""Bruecke vom BPMN-Modell zur .qea-Datei (Enterprise-Architect-Format).

Geschrieben wird ueber :mod:`qea_writer`, nicht ueber eine zweite SQLite-Implementierung.
Die Abbildung folgt der ADMBw-MDG 2026.05:

============================  ==========================  ==================
BPMN-Element                  ADMBw-Stereotyp             EA-Typ
============================  ==========================  ==================
Pool (Teilnehmer)             ``OperationalArchitecture`` Class
Lane                          ``OperationalPerformer``    Class
Aufgabe/Aktion                ``OperationalActivityAction`` Action
Kontrollfluss                 ``OperationalControlFlow``  ControlFlow
Nachrichtenfluss              ``OperationalMessageFlow``  ControlFlow
Datenobjekt / Conveyed Item   ``InformationElement``      Class
Datenbezug                    ``OperationalExchange``     InformationFlow
Ereignis, Gateway             *(kein Stereotyp)*          StateNode
============================  ==========================  ==================

Begruendete Abweichungen:

* ``ExchangeItem`` ist laut MDG **abstrakt** und darf nicht instanziiert
  werden. Ein Conveyed Item wird deshalb als konkretes ``InformationElement``
  geschrieben und ueber ``OperationalExchange`` an die Quellaktion gebunden;
  die BPMN-Kennung steht als Tag ``bpmn_id`` daran.
* Fuer Ereignisse und Gateways fuehrt die MDG kein eigenes Stereotyp. Sie
  werden als ``StateNode`` mit dem Tag ``bpmn_type`` abgelegt, damit die
  Prozesssemantik nicht verloren geht. Eine ADMBw-Konformitaetsaussage ist
  damit fuer diese Elemente ausdruecklich **nicht** verbunden.
* Eine BPMN-Assoziation zeigt auf einen *Fluss*, einer Kante im EA-Modell.
  EA-Konnektoren koennen keine Kante als Endpunkt haben. Der Datenbezug wird
  darum auf die Quellaktion des Flusses gezogen; der Tag ``bpmn_flow`` nennt
  die urspruengliche BPMN-Kante.

Oeffentliche API::

    als_ir(modell, paket="Prozesse") -> dict
    schreibe_qea(modell, ziel, paket="Prozesse") -> Path
    qea_bytes(modell, paket="Prozesse") -> bytes
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from . import modell as m
from core import qea_writer

STEREOTYP_POOL = "OperationalArchitecture"
STEREOTYP_LANE = "OperationalPerformer"
STEREOTYP_AKTION = "OperationalActivityAction"
STEREOTYP_KONTROLLFLUSS = "OperationalControlFlow"
STEREOTYP_NACHRICHTENFLUSS = "OperationalMessageFlow"
STEREOTYP_AUSTAUSCH = "OperationalExchange"
STEREOTYP_INFORMATIONSELEMENT = "InformationElement"

EA_TYP_POOL = "Class"
EA_TYP_LANE = "Class"
EA_TYP_AKTION = "Action"
EA_TYP_FLUSS = "ControlFlow"
EA_TYP_AUSTAUSCH = "InformationFlow"
EA_TYP_INFORMATIONSELEMENT = "Class"
EA_TYP_EREIGNIS = "StateNode"

#: BPMN-Art -> EA-Typ fuer Knoten ohne ADMBw-Stereotyp.
EREIGNIS_TYPEN = set(m.EREIGNIS_ARTEN) | set(m.GATEWAY_ARTEN)


def _segment(text: str) -> str:
    """Paketsegment ohne Pfadtrenner und ohne reservierte Zeichen."""
    text = (text or "").strip() or "Prozess"
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r"\s+", " ", text)
    return text[:80]


def _eindeutig(name: str, verwendet: set[str]) -> str:
    name = (name or "").strip() or "Ohne Namen"
    if name not in verwendet:
        verwendet.add(name)
        return name
    zaehler = 2
    while f"{name} ({zaehler})" in verwendet:
        zaehler += 1
    neu = f"{name} ({zaehler})"
    verwendet.add(neu)
    return neu


def _tags(**werte: str) -> dict[str, str]:
    return {k: v for k, v in werte.items() if v}


def _element(
    paket: str,
    name: str,
    stereotype: str,
    ea_type: str,
    *,
    notes: str = "",
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    eintrag: dict[str, Any] = {
        "package": paket,
        "name": name,
        "ea_type": ea_type,
    }
    if stereotype:
        eintrag["stereotype"] = stereotype
    if notes:
        eintrag["notes"] = notes
    if tags:
        eintrag["tags"] = tags
    return eintrag


def _kante(
    quelle: str,
    ziel: str,
    *,
    stereotype: str,
    ea_type: str,
    name: str = "",
    notes: str = "",
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    eintrag: dict[str, Any] = {
        "source": quelle,
        "target": ziel,
        "ea_type": ea_type,
    }
    if stereotype:
        eintrag["stereotype"] = stereotype
    if name:
        eintrag["name"] = name
    if notes:
        eintrag["notes"] = notes
    if tags:
        eintrag["tags"] = tags
    return eintrag


def _norm_key(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def _lade_katalog_eintraege(
    katalog: str | os.PathLike[str] | Mapping[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Liest Elemente eines L2/L3-Architekturmodells (.qea, .xmi, .xml, .json oder IR) nach Name/Alias."""
    if katalog is None:
        return {}
    if isinstance(katalog, Mapping):
        ir = dict(katalog)
    else:
        from core import validator

        ir = validator.load_ir(Path(katalog))
    index: dict[str, list[dict[str, Any]]] = {}
    for el in ir.get("elements") or ():
        if not isinstance(el, Mapping):
            continue
        nm = str(el.get("name") or "").strip()
        if not nm:
            continue
        item = {
            "name": nm,
            "package": str(el.get("package") or "").strip(),
            "stereotype": str(el.get("stereotype") or "").strip(),
            "ea_type": str(el.get("ea_type") or "Class").strip(),
            "guid": str(el.get("guid") or el.get("ea_guid") or "").strip(),
            "tags": dict(el.get("tags") or {}) if isinstance(el.get("tags"), Mapping) else {},
        }
        index.setdefault(_norm_key(nm), []).append(item)
        al = str(el.get("alias") or "").strip()
        if al and _norm_key(al) != _norm_key(nm):
            index.setdefault(_norm_key(al), []).append(item)
    return index


def _binde_an_architektur_katalog(
    ir: dict[str, Any],
    katalog_index: Mapping[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """Verknuepft L4-BPMN-Elemente kennungserhaltend mit L2/L3-Architekturelementen."""
    stats = {"direkt_uebernommen": 0, "l3_bruecken": 0}
    if not katalog_index:
        return stats

    pakete: list[dict[str, Any]] = ir["packages"]
    vorhandene_pakete = {str(p.get("path") or "") for p in pakete}

    def ensure_pkg(pfad: str) -> None:
        teile = [t for t in pfad.split("/") if t]
        for idx in range(1, len(teile) + 1):
            sub = "/".join(teile[:idx])
            if sub and sub not in vorhandene_pakete:
                pakete.append({"path": sub})
                vorhandene_pakete.add(sub)

    used_guids: set[str] = set()
    ref_remap: dict[str, str] = {}
    anker_elemente: list[dict[str, Any]] = []
    bruecken_kanten: list[dict[str, Any]] = []
    anker_refs: dict[str, str] = {}

    l3_activity_stereos = {"operationalactivity", "function", "servicefunction", "businessprocess", "applicationprocess"}
    l3_actor_stereos = {"node", "system", "capability", "businessactor", "businessrole", "applicationcomponent"}

    for el in ir["elements"]:
        nm = str(el.get("name") or "").strip()
        st = str(el.get("stereotype") or "").strip()
        old_pkg = str(el.get("package") or "").strip()
        old_ref = f"{old_pkg}::{nm}" if old_pkg else nm
        kandidaten = katalog_index.get(_norm_key(nm), [])
        if not kandidaten:
            continue

        # 1. Exakter Stereotyp-Treffer -> identisches Modellelement (GUID + Heimatpaket uebernehmen)
        exact = next(
            (
                k
                for k in kandidaten
                if k["stereotype"].casefold() == st.casefold()
                and (not k["guid"] or k["guid"] not in used_guids)
            ),
            None,
        )
        if exact is not None:
            if exact["guid"]:
                el["guid"] = exact["guid"]
                used_guids.add(exact["guid"])
            if exact["tags"]:
                merged_tags = dict(exact["tags"])
                merged_tags.update(dict(el.get("tags") or {}))
                el["tags"] = merged_tags
            if exact["package"] and exact["package"] != old_pkg:
                ensure_pkg(exact["package"])
                el["package"] = exact["package"]
                ref_remap[old_ref] = f"{exact['package']}::{nm}"
            stats["direkt_uebernommen"] += 1
            continue

        # 2. L3 <-> L4 Bruecke (z.B. OperationalActivityAction -> OperationalActivity / Function)
        if st == STEREOTYP_AKTION:
            l3 = next((k for k in kandidaten if k["stereotype"].casefold() in l3_activity_stereos), None)
            rel_st, rel_ty = "Implements", "Realisation"
        elif st in (STEREOTYP_LANE, STEREOTYP_POOL):
            l3 = next((k for k in kandidaten if k["stereotype"].casefold() in l3_actor_stereos), None)
            rel_st, rel_ty = "Association", "Association"
        else:
            l3 = None
            rel_st, rel_ty = "", ""

        if l3 is not None:
            l3_pkg = l3["package"] or "Architektur"
            ensure_pkg(l3_pkg)
            l3_ref = f"{l3_pkg}::{l3['name']}"
            if l3_ref not in anker_refs:
                anker_el = _element(
                    l3_pkg,
                    l3["name"],
                    l3["stereotype"],
                    l3["ea_type"] or "Class",
                    notes=f"L3-Architekturelement aus Katalog ({l3['stereotype']})",
                    tags=dict(l3["tags"]) if l3["tags"] else None,
                )
                if l3["guid"] and l3["guid"] not in used_guids:
                    anker_el["guid"] = l3["guid"]
                    used_guids.add(l3["guid"])
                anker_elemente.append(anker_el)
                anker_refs[l3_ref] = l3_ref
            cur_ref = ref_remap.get(old_ref, old_ref)
            bruecken_kanten.append(
                _kante(
                    cur_ref,
                    l3_ref,
                    stereotype=rel_st,
                    ea_type=rel_ty,
                    notes=f"L3-L4-Kopplung ({st} -> {l3['stereotype']})",
                    tags=_tags(l3_l4_bridge="true", target_guid=l3["guid"]),
                )
            )
            stats["l3_bruecken"] += 1

    if ref_remap:
        for kante in ir["connectors"]:
            for end_key in ("source", "target"):
                val = str(kante.get(end_key) or "")
                if val in ref_remap:
                    kante[end_key] = ref_remap[val]
        for diag in ir.get("diagrams") or ():
            for mem in diag.get("members") or ():
                if isinstance(mem, dict):
                    for mk in ("ref", "element"):
                        if mem.get(mk) in ref_remap:
                            mem[mk] = ref_remap[mem[mk]]

    ir["elements"].extend(anker_elemente)
    ir["connectors"].extend(bruecken_kanten)
    ir.setdefault("meta", {})["katalog_kopplung"] = stats
    return stats


def als_ir(
    modell: m.Modell,
    paket: str = "Prozesse",
    sichten: bool = True,
    *,
    katalog: str | os.PathLike[str] | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut das IR fuer :func:`qea_writer.write_qea`."""
    if not modell.prozesse:
        raise ValueError("Modell enthaelt keinen Prozess -- nichts zu schreiben")

    paket = _segment(paket)
    pakete: list[dict[str, Any]] = [{"path": paket}]
    elemente: list[dict[str, Any]] = []
    kanten: list[dict[str, Any]] = []

    pool_ref: dict[str, str] = {}
    refs: dict[str, str] = {}
    daten_refs: dict[str, str] = {}
    knoten_paket: dict[str, str] = {}
    fluss_paket: dict[str, str] = {}
    pool_namen: set[str] = set()
    paket_namen: dict[str, set[str]] = {}

    # ---- Pools im Wurzelpaket, Prozessinhalt im Unterpaket -----------------
    for prozess in modell.prozesse.values():
        teilnehmer = modell.teilnehmer_von_prozess(prozess.id)
        pool_name = teilnehmer.name if teilnehmer and teilnehmer.name else (prozess.name or prozess.id)
        pool_name = _eindeutig(pool_name, pool_namen)
        pool_id = teilnehmer.id if teilnehmer else f"Pool_{_segment(prozess.id)}"
        pool_notes = f"BPMN Pool {pool_id} (Prozess {prozess.id})"
        elemente.append(
            _element(
                paket,
                pool_name,
                STEREOTYP_POOL,
                EA_TYP_POOL,
                notes=pool_notes,
                tags=_tags(bpmn_id=pool_id, bpmn_type="participant", prozess_ref=prozess.id),
            )
        )
        pool_ref[prozess.id] = f"{paket}::{pool_name}"

    for prozess in modell.prozesse.values():
        unterpaket = f"{paket}/{_segment(prozess.name or prozess.id)}"
        # Gleichnamige Prozesse bekommen ein eindeutiges Paket.
        vorhandene_pakete = {p["path"] for p in pakete}
        if unterpaket in vorhandene_pakete:
            zaehler = 2
            while f"{unterpaket} ({zaehler})" in vorhandene_pakete:
                zaehler += 1
            unterpaket = f"{unterpaket} ({zaehler})"
        pakete.append({"path": unterpaket})
        verwendet = paket_namen.setdefault(unterpaket, set())

        # Lanes
        for lane in prozess.alle_lanes():
            lane_name = _eindeutig(lane.name or f"Lane {lane.id}", verwendet)
            elemente.append(
                _element(
                    unterpaket,
                    lane_name,
                    STEREOTYP_LANE,
                    EA_TYP_LANE,
                    notes=f"BPMN Lane {lane.id}; Aufgabentraeger: {lane.performer or 'nicht gesetzt'}",
                    tags=_tags(
                        bpmn_id=lane.id,
                        bpmn_type="lane",
                        performer=lane.performer,
                        prozess_ref=prozess.id,
                    ),
                )
            )
            refs[lane.id] = f"{unterpaket}::{lane_name}"

        # Knoten
        for element_id in prozess.elemente:
            knoten = modell.knoten.get(element_id)
            if knoten is None:
                continue
            name = _eindeutig(knoten.name or knoten.id, verwendet)
            if knoten.ist_aufgabe:
                elemente.append(
                    _element(
                        unterpaket,
                        name,
                        STEREOTYP_AKTION,
                        EA_TYP_AKTION,
                        notes=f"BPMN {m.XML_NAME.get(knoten.art, knoten.art)} {knoten.id}",
                        tags=_tags(
                            bpmn_id=knoten.id,
                            bpmn_type=knoten.art,
                            prozess_ref=prozess.id,
                        ),
                    )
                )
            else:
                elemente.append(
                    _element(
                        unterpaket,
                        name,
                        "",
                        EA_TYP_EREIGNIS,
                        notes=(
                            f"BPMN {m.XML_NAME.get(knoten.art, knoten.art)} {knoten.id} -- "
                            "kein ADMBw-Stereotyp (MDG); Semantik ueber Tag bpmn_type"
                        ),
                        tags=_tags(
                            bpmn_id=knoten.id,
                            bpmn_type=knoten.art,
                            ereignis_definition=knoten.ereignis_definition,
                            prozess_ref=prozess.id,
                        ),
                    )
                )
            refs[knoten.id] = f"{unterpaket}::{name}"
            knoten_paket[knoten.id] = unterpaket

        # Datenobjekte
        for element_id in prozess.elemente:
            daten = modell.daten.get(element_id)
            if daten is None:
                continue
            name = _eindeutig(daten.name or daten.id, verwendet)
            elemente.append(
                _element(
                    unterpaket,
                    name,
                    STEREOTYP_INFORMATIONSELEMENT,
                    EA_TYP_INFORMATIONSELEMENT,
                    notes=f"BPMN {m.XML_NAME.get(daten.art, daten.art)} {daten.id}",
                    tags=_tags(bpmn_id=daten.id, bpmn_type=daten.art, prozess_ref=prozess.id),
                )
            )
            daten_refs[daten.id] = f"{unterpaket}::{name}"

    # ---- Kanten -----------------------------------------------------------
    def _ref(element_id: str) -> str:
        return refs.get(element_id) or daten_refs.get(element_id) or ""

    def _paket_von(element_id: str) -> str:
        for unterpaket in paket_namen:
            if element_id in knoten_paket and knoten_paket[element_id] == unterpaket:
                return unterpaket
        return paket

    for fluss in modell.fluesse.values():
        if fluss.art == "sequence_flow":
            quelle, ziel = _ref(fluss.quelle), _ref(fluss.ziel)
            if not quelle or not ziel:
                continue
            paket_fluss = knoten_paket.get(fluss.quelle) or _paket_von(fluss.quelle)
            fluss_paket[fluss.id] = paket_fluss
            kanten.append(
                _kante(
                    quelle,
                    ziel,
                    stereotype=STEREOTYP_KONTROLLFLUSS,
                    ea_type=EA_TYP_FLUSS,
                    name=fluss.name,
                    notes=f"BPMN Sequenzfluss {fluss.id}",
                    tags=_tags(bpmn_id=fluss.id, bpmn_type="sequence_flow", bedingung=fluss.bedingung),
                )
            )
        elif fluss.art == "message_flow":
            quelle, ziel = _ref(fluss.quelle), _ref(fluss.ziel)
            if not quelle or not ziel:
                continue
            paket_fluss = knoten_paket.get(fluss.quelle) or _paket_von(fluss.quelle)
            fluss_paket[fluss.id] = paket_fluss
            kanten.append(
                _kante(
                    quelle,
                    ziel,
                    stereotype=STEREOTYP_NACHRICHTENFLUSS,
                    ea_type=EA_TYP_FLUSS,
                    name=fluss.name,
                    notes=f"BPMN Nachrichtenfluss {fluss.id}",
                    tags=_tags(bpmn_id=fluss.id, bpmn_type="message_flow"),
                )
            )

    # Conveyed Items: Assoziation Datenobjekt -> Fluss wird zu
    # InformationElement -> Quellaktion (OperationalExchange).
    gesehen: set[tuple[str, str, str]] = set()
    for fluss in modell.fluesse.values():
        if fluss.art != "association":
            continue
        daten_id = fluss.quelle if fluss.quelle in daten_refs else fluss.ziel if fluss.ziel in daten_refs else ""
        anderer = fluss.ziel if daten_id == fluss.quelle else fluss.quelle
        if not daten_id:
            continue
        anker = ""
        bpmn_flow = ""
        if anderer in modell.fluesse:
            bpmn_flow = anderer
            bezug = modell.fluesse[anderer]
            # Bevorzugt die Aktion als Anker: Conveyed Items haengen fachlich an
            # der Handlung, nicht am Startereignis.
            if bezug.quelle in refs and bezug.quelle in modell.knoten and modell.knoten[bezug.quelle].ist_aufgabe:
                anker = bezug.quelle
            elif bezug.ziel in refs and bezug.ziel in modell.knoten and modell.knoten[bezug.ziel].ist_aufgabe:
                anker = bezug.ziel
            else:
                anker = bezug.quelle if bezug.quelle in refs else bezug.ziel
        elif anderer in refs:
            anker = anderer
        if not anker or anker not in refs:
            continue
        schluessel = (daten_id, anker, bpmn_flow)
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        kanten.append(
            _kante(
                daten_refs[daten_id],
                refs[anker],
                stereotype=STEREOTYP_AUSTAUSCH,
                ea_type=EA_TYP_AUSTAUSCH,
                name=modell.daten[daten_id].name,
                notes=(
                    f"Conveyed Item {daten_id}"
                    + (f" an BPMN-Kante {bpmn_flow}" if bpmn_flow else "")
                ),
                tags=_tags(bpmn_id=fluss.id, bpmn_type="association", bpmn_flow=bpmn_flow),
            )
        )

    diagramme: list[dict[str, Any]] = []
    if sichten:
        from core.view_builder import layout_members

        for prozess in modell.prozesse.values():
            unterpaket = f"{paket}/{_segment(prozess.name or prozess.id)}"
            p_knoten_refs = [refs[k_id] for k_id in prozess.elemente if k_id in refs]
            p_daten_refs = [daten_refs[d_id] for d_id in prozess.elemente if d_id in daten_refs]
            alle_refs = p_knoten_refs + p_daten_refs
            if alle_refs:
                d_name = prozess.name or prozess.id
                diagramme.append(
                    {
                        "name": f"Aktivitätsdiagramm {d_name}",
                        "type": "Activity",
                        "package": unterpaket,
                        "notes": f"BPMN-Aktivitätsdiagramm für Prozess {d_name}",
                        "members": layout_members([{"ref": r} for r in alle_refs]),
                        "is_default": len(diagramme) == 0,
                    }
                )

    ir: dict[str, Any] = {
        "ir_version": qea_writer.IR_VERSION,
        "technology": {"profile": "ADMBw"},
        "packages": pakete,
        "elements": elemente,
        "connectors": kanten,
        "diagrams": diagramme,
    }
    if katalog is not None:
        _binde_an_architektur_katalog(ir, _lade_katalog_eintraege(katalog))
    return ir


def schreibe_qea(
    modell: m.Modell,
    ziel: str | os.PathLike[str],
    paket: str = "Prozesse",
    sichten: bool = True,
    *,
    katalog: str | os.PathLike[str] | Mapping[str, Any] | None = None,
    bestand_verbinden: bool = False,
) -> Path:
    """Schreibt das BPMN-Modell als .qea (optional GUID-erhaltend gekoppelt an ein Architekturmodell)."""
    ir = als_ir(modell, paket, sichten=sichten, katalog=katalog)
    ziel_pfad = Path(ziel)
    if (
        bestand_verbinden
        and katalog is not None
        and not isinstance(katalog, Mapping)
        and Path(katalog).suffix.lower() == ".qea"
        and Path(katalog).is_file()
    ):
        from core import model_merge

        with tempfile.TemporaryDirectory(prefix="bpmn-qea-") as td:
            teil_qea = Path(td) / "prozess.qea"
            qea_writer.write_qea(ir, teil_qea)
            model_merge.merge_models([str(Path(katalog)), str(teil_qea)], ziel_pfad, per_name=True)
        return ziel_pfad
    return qea_writer.write_qea(ir, ziel_pfad)


def qea_bytes(
    modell: m.Modell,
    paket: str = "Prozesse",
    sichten: bool = True,
    *,
    katalog: str | os.PathLike[str] | Mapping[str, Any] | None = None,
) -> bytes:
    """Liefert die .qea als Bytes (deterministisch, ohne Zwischendatei)."""
    return qea_writer.render_bytes(als_ir(modell, paket, sichten=sichten, katalog=katalog))


__all__ = [
    "STEREOTYP_POOL",
    "STEREOTYP_LANE",
    "STEREOTYP_AKTION",
    "als_ir",
    "schreibe_qea",
    "qea_bytes",
]
