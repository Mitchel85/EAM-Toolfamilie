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

import os
import re
from pathlib import Path
from typing import Any

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


def als_ir(modell: m.Modell, paket: str = "Prozesse") -> dict[str, Any]:
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

    return {
        "ir_version": qea_writer.IR_VERSION,
        "technology": {"profile": "ADMBw"},
        "packages": pakete,
        "elements": elemente,
        "connectors": kanten,
        "diagrams": [],
    }


def schreibe_qea(
    modell: m.Modell, ziel: str | os.PathLike[str], paket: str = "Prozesse"
) -> Path:
    """Schreibt das BPMN-Modell als .qea und liefert den Pfad."""
    return qea_writer.write_qea(als_ir(modell, paket), ziel)


def qea_bytes(modell: m.Modell, paket: str = "Prozesse") -> bytes:
    """Liefert die .qea als Bytes (deterministisch, ohne Zwischendatei)."""
    return qea_writer.render_bytes(als_ir(modell, paket))


__all__ = ["STEREOTYP_POOL", "STEREOTYP_LANE", "STEREOTYP_AKTION", "als_ir", "schreibe_qea", "qea_bytes"]
