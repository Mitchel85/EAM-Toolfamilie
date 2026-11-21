"""ADMBw-Abbildung, L4-Pruefung und "ADMBw-konform machen".

Drei Aufgaben, ein Modul:

* **Abbildung** -- welches ADMBw-Stereotyp gehoert zu welchem BPMN-Element.
  Die Tabelle steht in ``knowledge/bpmn/prozess-regeln.json`` und stammt aus
  der MDG 2026.05; hier wird sie nur gelesen.
* **Pruefung** -- die L4-Modellierungskonventionen als Befundliste. Jeder
  Befund nennt Regel, Schwere, Objekt und einen Hinweis, der ohne Nachschlagen
  verstaendlich ist.
* **Transformation** -- was sich mechanisch beheben laesst, wird behoben und
  protokolliert. Was fachliche Entscheidungen braucht, bleibt stehen; das
  Protokoll sagt warum.

Die Pruefung ist die einzige Wahrheit fuer die Transformation: Sie repariert
genau die Befunde, die sie selbst meldet. Zweimal konform machen aendert beim
zweiten Mal nichts -- das prueft ``tests/bpmn/test_admbw.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import modell as m

#: Reihenfolge der Schweregrade (fuer Sortierung und Zusammenfassung).
SCHWERE_RANG = {"fehler": 0, "warnung": 1, "hinweis": 2}

#: Standarddatei der Regeln, relativ zur Repo-Wurzel.
REGEL_DATEI = Path(__file__).resolve().parents[2] / "knowledge" / "bpmn" / "prozess-regeln.json"

#: BPMN-Art -> Name in den MDG-Metaconstraints.
MDG_TYP = {
    "start_event": "BPMN2.0::StartEvent",
    "end_event": "BPMN2.0::EndEvent",
    "intermediate_catch_event": "BPMN2.0::IntermediateEvent",
    "intermediate_throw_event": "BPMN2.0::IntermediateEvent",
    "exclusive_gateway": "BPMN2.0::Gateway",
    "parallel_gateway": "BPMN2.0::Gateway",
    "inclusive_gateway": "BPMN2.0::Gateway",
    "event_based_gateway": "BPMN2.0::Gateway",
    "complex_gateway": "BPMN2.0::Gateway",
}

for _art in m.AUFGABEN_ARTEN:
    MDG_TYP[_art] = "NAFv4-ADMBw::OperationalActivityAction"


@dataclass(frozen=True)
class Befund:
    """Ein Pruefergebnis zu genau einem Objekt."""

    regel: str
    schwere: str
    objekt: str
    name: str
    hinweis: str
    konvention: str = ""

    def als_dict(self) -> dict[str, str]:
        return {
            "regel": self.regel,
            "schwere": self.schwere,
            "objekt": self.objekt,
            "name": self.name,
            "hinweis": self.hinweis,
            "konvention": self.konvention,
        }

    def __str__(self) -> str:
        return f"[{self.schwere}] {self.regel} {self.objekt} ({self.name}): {self.hinweis}"


@dataclass
class Aenderung:
    """Eine vorgenommene Aenderung, mit Vorher und Nachher."""

    regel: str
    objekt: str
    was: str
    vorher: str = ""
    nachher: str = ""

    def als_dict(self) -> dict[str, str]:
        return {
            "regel": self.regel,
            "objekt": self.objekt,
            "was": self.was,
            "vorher": self.vorher,
            "nachher": self.nachher,
        }

    def __str__(self) -> str:
        return f"{self.regel} {self.objekt}: {self.was}"


@dataclass
class Protokoll:
    """Ergebnis von "ADMBw-konform machen"."""

    aenderungen: list[Aenderung] = field(default_factory=list)
    offen: list[Befund] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.aenderungen)

    def __len__(self) -> int:
        return len(self.aenderungen)

    def als_dict(self) -> dict[str, Any]:
        return {
            "aenderungen": [a.als_dict() for a in self.aenderungen],
            "anzahl": len(self.aenderungen),
            "offen": [b.als_dict() for b in self.offen],
        }

    def text(self) -> str:
        zeilen = [f"{len(self.aenderungen)} Aenderung(en)"]
        for aenderung in self.aenderungen:
            zeilen.append(f"  - {aenderung}")
        if self.offen:
            zeilen.append(f"{len(self.offen)} offene(r) Befund(e) -- fachlich zu entscheiden:")
            for befund in self.offen:
                zeilen.append(f"  - {befund}")
        return "\n".join(zeilen)


# --------------------------------------------------------------------------
# Regelwerk laden
# --------------------------------------------------------------------------


def lade_regeln(pfad: str | Path | None = None) -> dict[str, Any]:
    ziel = Path(pfad) if pfad else REGEL_DATEI
    if not ziel.is_file():
        raise FileNotFoundError(
            f"{ziel} fehlt -- scripts/build_bpmn_regeln.py laufen lassen"
        )
    return json.loads(ziel.read_text(encoding="utf-8"))


def mapping(art: str, regeln: dict[str, Any] | None = None) -> dict[str, Any]:
    """Abbildung eines BPMN-Elementtyps auf das ADMBw-Stereotyp."""
    daten = regeln or lade_regeln()
    eintrag = daten["elementtypen"].get(art)
    if eintrag is None:
        return {
            "bpmn": art,
            "admbw": None,
            "sicherheit": "unbekannt",
            "begruendung": "Elementtyp ist im Regelauszug nicht beschrieben.",
            "konventionen": [],
            "quelle": [],
        }
    return eintrag


def stereotype_fuer(art: str, regeln: dict[str, Any] | None = None) -> str | None:
    """Name des ADMBw-Stereotyps oder ``None`` (Element bleibt BPMN-Standard)."""
    eintrag = mapping(art, regeln)
    name = eintrag.get("admbw")
    if name is None:
        return None
    daten = regeln or lade_regeln()
    if name not in daten["stereotype"]:
        raise KeyError(
            f"Stereotyp {name!r} steht nicht in der MDG-Liste -- Regelauszug veraltet?"
        )
    return name


def regel_text(regel_id: str, regeln: dict[str, Any] | None = None) -> dict[str, Any]:
    daten = regeln or lade_regeln()
    for eintrag in daten["pruefregeln"]:
        if eintrag["id"] == regel_id:
            return eintrag
    raise KeyError(f"unbekannte Regel: {regel_id}")


# --------------------------------------------------------------------------
# Pruefung
# --------------------------------------------------------------------------


def pruefe(modell: m.Modell, regeln: dict[str, Any] | None = None) -> list[Befund]:
    """Alle pruefbaren L4-Konventionen als Befundliste.

    Sortiert nach Regel und Objekt -- gleiche Eingabe, gleiche Reihenfolge.
    """
    daten = regeln or lade_regeln()
    befunde: list[Befund] = []
    befunde.extend(_pruefe_kollaboration(modell, daten))
    befunde.extend(_pruefe_prozesse(modell, daten))
    befunde.extend(_pruefe_knoten(modell, daten))
    befunde.extend(_pruefe_fluesse(modell, daten))
    befunde.sort(key=lambda b: (SCHWERE_RANG.get(b.schwere, 9), b.regel, b.objekt))
    return befunde


def _befund(
    daten: dict[str, Any], regel: str, objekt: str, name: str, hinweis: str
) -> Befund:
    eintrag = next((r for r in daten["pruefregeln"] if r["id"] == regel), {})
    return Befund(
        regel=regel,
        schwere=eintrag.get("schwere", "fehler"),
        objekt=objekt,
        name=name,
        hinweis=hinweis,
        konvention=eintrag.get("konvention", ""),
    )


def _pruefe_kollaboration(modell: m.Modell, daten: dict[str, Any]) -> list[Befund]:
    befunde: list[Befund] = []
    if not modell.prozesse:
        # Ein leeres Dokument ist kein Modellierfehler, sondern ein leeres Dokument.
        return befunde
    if modell.kollaboration is None or not modell.kollaboration.teilnehmer:
        befunde.append(
            _befund(
                daten,
                "BPMN-L4-01",
                modell.kollaboration.id if modell.kollaboration else modell.id,
                modell.name or "Modell",
                "Keine Kollaboration mit Pool -- L4-MK08 verlangt ein BPMN-Kollaborationsdiagramm.",
            )
        )
        return befunde
    for teilnehmer in modell.kollaboration.teilnehmer:
        if not teilnehmer.prozess_ref or teilnehmer.prozess_ref not in modell.prozesse:
            befunde.append(
                _befund(
                    daten,
                    "BPMN-L4-01",
                    teilnehmer.id,
                    teilnehmer.name or teilnehmer.id,
                    "Pool zeigt auf keinen vorhandenen Prozess.",
                )
            )
        if not teilnehmer.name:
            befunde.append(
                _befund(
                    daten,
                    "BPMN-L4-02",
                    teilnehmer.id,
                    teilnehmer.id,
                    "Pool ohne Namen -- L4-MK09 verlangt Benennung.",
                )
            )
        if not teilnehmer.typ:
            befunde.append(
                _befund(
                    daten,
                    "BPMN-L4-15",
                    teilnehmer.id,
                    teilnehmer.name or teilnehmer.id,
                    "Pool ist nicht mit einem Anwendungsfall (OperationalArchitecture) typisiert.",
                )
            )
    return befunde


def _pruefe_prozesse(modell: m.Modell, daten: dict[str, Any]) -> list[Befund]:
    befunde: list[Befund] = []
    for prozess in modell.prozesse.values():
        knoten = [modell.knoten[e] for e in prozess.elemente if e in modell.knoten]
        starts = [k for k in knoten if k.ist_start]
        enden = [k for k in knoten if k.ist_ende]
        aktionen = [k for k in knoten if k.ist_aufgabe]
        if not starts:
            befunde.append(
                _befund(
                    daten,
                    "BPMN-L4-14",
                    prozess.id,
                    prozess.name or prozess.id,
                    "Prozess ohne Startereignis.",
                )
            )
        fehlend = []
        if not starts:
            fehlend.append("Startereignis")
        if not aktionen:
            fehlend.append("Aktion")
        if not enden:
            fehlend.append("Endereignis")
        if fehlend:
            befunde.append(
                _befund(
                    daten,
                    "BPMN-L4-10",
                    prozess.id,
                    prozess.name or prozess.id,
                    "Kein abgeschlossener Prozess: es fehlt " + ", ".join(fehlend) + ".",
                )
            )
        elif starts:
            erreichbar = _erreichbar(modell, prozess, starts[0].id)
            unerreichbar = [k for k in knoten if k.id not in erreichbar]
            if unerreichbar:
                namen = ", ".join(sorted(k.name or k.id for k in unerreichbar)[:5])
                befunde.append(
                    _befund(
                        daten,
                        "BPMN-L4-10",
                        prozess.id,
                        prozess.name or prozess.id,
                        f"Nicht vom Startereignis erreichbar: {namen}.",
                    )
                )
        for lane in prozess.alle_lanes():
            if not lane.name:
                befunde.append(
                    _befund(
                        daten,
                        "BPMN-L4-02",
                        lane.id,
                        lane.id,
                        "Lane ohne Namen -- L4-MK09 verlangt Benennung nach dem Aufgabentraeger.",
                    )
                )
            if not lane.performer and not lane.lanes:
                befunde.append(
                    _befund(
                        daten,
                        "BPMN-L4-03",
                        lane.id,
                        lane.name or lane.id,
                        "Lane ist keinem Aufgabentraeger (OperationalPerformer) zugeordnet.",
                    )
                )
    return befunde


def _pruefe_knoten(modell: m.Modell, daten: dict[str, Any]) -> list[Befund]:
    befunde: list[Befund] = []
    for prozess in modell.prozesse.values():
        lanes = prozess.alle_lanes()
        for element_id in prozess.elemente:
            knoten = modell.knoten.get(element_id)
            if knoten is None:
                continue
            name = knoten.name or knoten.id
            if lanes:
                treffer = [lane for lane in lanes if knoten.id in lane.knoten]
                if len(treffer) != 1:
                    befunde.append(
                        _befund(
                            daten,
                            "BPMN-L4-04",
                            knoten.id,
                            name,
                            "Knoten liegt in keiner oder in mehreren Lanes (L4-MK12).",
                        )
                    )
            if knoten.ist_aufgabe:
                if knoten.stereotype != "OperationalActivityAction":
                    befunde.append(
                        _befund(
                            daten,
                            "BPMN-L4-05",
                            knoten.id,
                            name,
                            f"ADMBw-Stereotyp fehlt (ist: {knoten.stereotype or 'keins'}).",
                        )
                    )
                if not _name_aussagekraeftig(knoten.name):
                    befunde.append(
                        _befund(
                            daten,
                            "BPMN-L4-06",
                            knoten.id,
                            name,
                            "Aktion ohne aussagefaehigen Namen (L4-MK14).",
                        )
                    )
                fehlend = []
                eingehend = modell.eingehend(knoten.id)
                ausgehend = modell.ausgehend(knoten.id)
                if eingehend and not any(modell.conveyed_items(f.id) for f in eingehend):
                    fehlend.append("Eingang")
                if ausgehend and not any(modell.conveyed_items(f.id) for f in ausgehend):
                    fehlend.append("Ausgang")
                if fehlend:
                    befunde.append(
                        _befund(
                            daten,
                            "BPMN-L4-11",
                            knoten.id,
                            name,
                            "Kein Conveyed Item am " + " und ".join(fehlend) + " (L4-MK17).",
                        )
                    )
            ein = len(modell.eingehend(knoten.id))
            aus = len(modell.ausgehend(knoten.id))
            if not knoten.ist_gateway and (ein > 1 or aus > 1):
                befunde.append(
                    _befund(
                        daten,
                        "BPMN-L4-08",
                        knoten.id,
                        name,
                        f"Verzweigung/Zusammenfuehrung an einem {knoten.art} "
                        f"({ein} ein, {aus} aus) -- zulaessig nur an Gateways.",
                    )
                )
            if knoten.ist_gateway and ein > 1:
                typ = _verzweigungstyp(modell, knoten)
                if typ and typ != knoten.art:
                    befunde.append(
                        _befund(
                            daten,
                            "BPMN-L4-09",
                            knoten.id,
                            name,
                            f"Zusammenfuehrung ist {knoten.art}, Verzweigung war {typ} (L4-MK15).",
                        )
                    )
    return befunde


def _name_aussagekraeftig(name: str) -> bool:
    """Grobpruefung: leer, zu kurz oder reiner Platzhalter zaehlt nicht."""
    if not name or len(name.strip()) < 3:
        return False
    return not name.strip().lower().startswith(("aktion ", "task ", "aufgabe "))


def _ist_platzhalter(name: str) -> bool:
    return "(benennen)" in (name or "").lower()


def _pruefe_fluesse(modell: m.Modell, daten: dict[str, Any]) -> list[Befund]:
    befunde: list[Befund] = []
    erlaubt = daten.get("metaconstraints", {})
    for fluss in modell.fluesse.values():
        if fluss.art == "sequence_flow":
            befunde.extend(_pruefe_sequenzfluss(modell, fluss, daten, erlaubt))
        elif fluss.art == "message_flow":
            befunde.extend(_pruefe_nachrichtenfluss(modell, fluss, daten))
    return befunde


def _art_name(modell: m.Modell, element_id: str) -> str:
    knoten = modell.knoten.get(element_id)
    return MDG_TYP.get(knoten.art, knoten.art) if knoten else ""


def _pruefe_sequenzfluss(
    modell: m.Modell, fluss: m.Fluss, daten: dict[str, Any], erlaubt: dict[str, Any]
) -> list[Befund]:
    befunde: list[Befund] = []
    grenzen = erlaubt.get("OperationalControlFlow", {})
    quelle = _art_name(modell, fluss.quelle)
    ziel = _art_name(modell, fluss.ziel)
    if quelle and grenzen.get("source") and quelle not in grenzen["source"]:
        befunde.append(
            _befund(
                daten,
                "BPMN-L4-07",
                fluss.id,
                fluss.name or fluss.id,
                f"Quelle {quelle} ist fuer einen Kontrollfluss nicht zulaessig (MDG).",
            )
        )
    if ziel and grenzen.get("target") and ziel not in grenzen["target"]:
        befunde.append(
            _befund(
                daten,
                "BPMN-L4-07",
                fluss.id,
                fluss.name or fluss.id,
                f"Ziel {ziel} ist fuer einen Kontrollfluss nicht zulaessig (MDG).",
            )
        )
    if fluss.bedingung:
        knoten = modell.knoten.get(fluss.quelle)
        if knoten is not None and not (knoten.ist_gateway or knoten.art.startswith("intermediate")):
            befunde.append(
                _befund(
                    daten,
                    "BPMN-L4-12",
                    fluss.id,
                    fluss.name or fluss.id,
                    "Bedingter Fluss geht von einer Aktion aus -- Vorbedingung als "
                    "Zwischenereignis modellieren (L4-MK18).",
                )
            )
    return befunde


def _pruefe_nachrichtenfluss(
    modell: m.Modell, fluss: m.Fluss, daten: dict[str, Any]
) -> list[Befund]:
    befunde: list[Befund] = []
    quelle_pool = pool_von_knoten(modell, fluss.quelle)
    ziel_pool = pool_von_knoten(modell, fluss.ziel)
    name = fluss.name or fluss.id
    if quelle_pool is not None and ziel_pool is not None and quelle_pool.id == ziel_pool.id:
        befunde.append(
            _befund(
                daten,
                "BPMN-L4-13",
                fluss.id,
                name,
                "Nachrichtenfluss innerhalb eines Pools -- L4-MK20 verlangt Austausch zwischen Pools.",
            )
        )
    if not modell.conveyed_items(fluss.id):
        befunde.append(
            _befund(
                daten,
                "BPMN-L4-13",
                fluss.id,
                name,
                "Nachrichtenfluss ohne Conveyed Item (L4-MK17/L4-MK20).",
            )
        )
    return befunde


def _erreichbar(modell: m.Modell, prozess: m.Prozess, start: str) -> set[str]:
    gesehen = {start}
    offen = [start]
    while offen:
        aktuell = offen.pop()
        for fluss in modell.ausgehend(aktuell):
            if fluss.ziel in gesehen or fluss.ziel not in prozess.knoten_ids(modell):
                continue
            gesehen.add(fluss.ziel)
            offen.append(fluss.ziel)
    return gesehen


def _verzweigungstyp(modell: m.Modell, gateway: m.Knoten) -> str | None:
    """Typ der naechstgelegenen Verzweigung oberhalb einer Zusammenfuehrung."""
    gesehen: set[str] = set()
    rand = [gateway.id]
    while rand:
        naechster: list[str] = []
        for kid in rand:
            for fluss in modell.eingehend(kid):
                quelle = fluss.quelle
                if quelle in gesehen:
                    continue
                gesehen.add(quelle)
                knoten = modell.knoten.get(quelle)
                if knoten is None:
                    continue
                if knoten.ist_gateway and len(modell.ausgehend(knoten.id)) > 1:
                    return knoten.art
                naechster.append(quelle)
        rand = naechster
    return None


def pool_von_knoten(modell: m.Modell, element_id: str) -> m.Teilnehmer | None:
    prozess = modell.prozess_von_element(element_id)
    if prozess is None:
        return None
    return modell.teilnehmer_von_prozess(prozess.id)


def zusammenfassung(befunde: Iterable[Befund]) -> dict[str, int]:
    zaehler = {"fehler": 0, "warnung": 0, "hinweis": 0}
    for befund in befunde:
        zaehler[befund.schwere] = zaehler.get(befund.schwere, 0) + 1
    return zaehler


# --------------------------------------------------------------------------
# Transformation
# --------------------------------------------------------------------------


def konform_machen(
    modell: m.Modell, regeln: dict[str, Any] | None = None
) -> Protokoll:
    """Behebt die mechanisch behebbaren Befunde und protokolliert alles."""
    daten = regeln or lade_regeln()
    protokoll = Protokoll()

    _sichere_kollaboration(modell, protokoll, daten)
    # Mehrere Runden, weil eine Reparatur neue Befunde erzeugen kann: ein
    # eingefuegtes Zwischenereignis macht aus einer Aktion einen Knoten mit
    # zwei Ausgaengen -- der braucht dann ein Gateway.
    for _runde in range(5):
        vorher = len(protokoll.aenderungen)
        for prozess in list(modell.prozesse.values()):
            _sichere_lanes(modell, prozess, protokoll, daten)
            _sichere_aktionen(modell, prozess, protokoll, daten)
            _sichere_gateways(modell, prozess, protokoll, daten)
            _sichere_start_ende(modell, prozess, protokoll, daten)
            _sichere_bedingungen(modell, prozess, protokoll, daten)
            _sichere_conveyed(modell, prozess, protokoll, daten)
        _sichere_nachrichtenfluesse(modell, protokoll, daten)
        if len(protokoll.aenderungen) == vorher:
            break

    protokoll.offen = [
        befund for befund in pruefe(modell, daten) if befund.schwere == "fehler"
    ]
    return protokoll


def _sichere_kollaboration(modell: m.Modell, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    if modell.kollaboration is None:
        modell.kollaboration = m.Kollaboration(id=modell.neue_id("Collaboration"), name=modell.name)
        protokoll.aenderungen.append(
            Aenderung("BPMN-L4-01", modell.kollaboration.id, "Kollaboration angelegt")
        )
    vorhanden = {t.prozess_ref for t in modell.kollaboration.teilnehmer}
    for prozess in modell.prozesse.values():
        if prozess.id in vorhanden:
            continue
        teilnehmer = m.Teilnehmer(
            id=modell.neue_id("Participant"),
            name=prozess.name or f"Pool {prozess.id}",
            prozess_ref=prozess.id,
        )
        modell.kollaboration.teilnehmer.append(teilnehmer)
        protokoll.aenderungen.append(
            Aenderung("BPMN-L4-01", teilnehmer.id, "Pool fuer Prozess angelegt",
                      vorher="", nachher=prozess.id)
        )
    for teilnehmer in modell.kollaboration.teilnehmer:
        if not teilnehmer.name:
            teilnehmer.name = f"Pool {teilnehmer.id}"
            protokoll.aenderungen.append(
                Aenderung("BPMN-L4-02", teilnehmer.id, "Pool benannt", "", teilnehmer.name)
            )


def _sichere_lanes(modell: m.Modell, prozess: m.Prozess, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    lanes = prozess.alle_lanes()
    knoten_ids = prozess.knoten_ids(modell)
    if not knoten_ids:
        return
    if not lanes:
        lane_set = m.LaneSet(id=modell.neue_id("LaneSet"))
        lane = m.Lane(id=modell.neue_id("Lane"), name="Aufgabentraeger (zu benennen)")
        lane_set.lanes.append(lane)
        prozess.lane_sets.append(lane_set)
        lanes = [lane]
        protokoll.aenderungen.append(
            Aenderung("BPMN-L4-04", lane.id, "Lane fuer Prozess angelegt", "", lane.name)
        )
    for lane in lanes:
        if not lane.name:
            lane.name = f"Lane {lane.id}"
            protokoll.aenderungen.append(
                Aenderung("BPMN-L4-02", lane.id, "Lane benannt", "", lane.name)
            )
    zugeordnet = {kid for lane in lanes for kid in lane.knoten}
    for kid in knoten_ids:
        if kid in zugeordnet:
            continue
        lanes[0].knoten.append(kid)
        protokoll.aenderungen.append(
            Aenderung(
                "BPMN-L4-04",
                kid,
                f"Knoten der Lane {lanes[0].name!r} zugeordnet",
                "",
                lanes[0].id,
            )
        )


def _sichere_aktionen(modell: m.Modell, prozess: m.Prozess, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    nummer = 0
    for element_id in list(prozess.elemente):
        knoten = modell.knoten.get(element_id)
        if knoten is None or not knoten.ist_aufgabe:
            continue
        nummer += 1
        if knoten.stereotype != "OperationalActivityAction":
            alt = knoten.stereotype
            knoten.stereotype = "OperationalActivityAction"
            protokoll.aenderungen.append(
                Aenderung("BPMN-L4-05", knoten.id, "ADMBw-Stereotyp gesetzt", alt, knoten.stereotype)
            )
        if not _name_aussagekraeftig(knoten.name) and not _ist_platzhalter(knoten.name):
            alt = knoten.name
            knoten.name = f"Aktion {nummer} (benennen)"
            protokoll.aenderungen.append(
                Aenderung("BPMN-L4-06", knoten.id, "Arbeitsnamen gesetzt", alt, knoten.name)
            )


def _sichere_gateways(modell: m.Modell, prozess: m.Prozess, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    # 1. Verzweigungen und Zusammenfuehrungen an Nicht-Gateways aufloesen.
    for element_id in list(prozess.knoten_ids(modell)):
        knoten = modell.knoten.get(element_id)
        if knoten is None or knoten.ist_gateway:
            continue
        ausgehend = modell.ausgehend(knoten.id)
        if len(ausgehend) > 1:
            _gateway_teilen(modell, prozess, knoten, ausgehend, protokoll)
        eingehend = modell.eingehend(knoten.id)
        if len(eingehend) > 1:
            _gateway_zusammenfuehren(modell, prozess, knoten, eingehend, protokoll)

    # 2. Zusammenfuehrungen auf den Typ der Verzweigung bringen.
    for element_id in list(prozess.knoten_ids(modell)):
        knoten = modell.knoten.get(element_id)
        if knoten is None or not knoten.ist_gateway:
            continue
        if len(modell.eingehend(knoten.id)) <= 1:
            continue
        typ = _verzweigungstyp(modell, knoten)
        if typ and typ != knoten.art:
            alt = knoten.art
            knoten.art = typ
            protokoll.aenderungen.append(
                Aenderung("BPMN-L4-09", knoten.id, "Gateway-Typ der Zusammenfuehrung angepasst", alt, typ)
            )


def _gateway_teilen(
    modell: m.Modell,
    prozess: m.Prozess,
    knoten: m.Knoten,
    ausgehend: list[m.Fluss],
    protokoll: Protokoll,
) -> None:
    gateway = modell.neuer_knoten("exclusive_gateway", "Verzweigung", prozess)
    _lane_uebernehmen(modell, prozess, knoten.id, gateway.id)
    for fluss in ausgehend:
        fluss.quelle = gateway.id
    modell.neuer_fluss("sequence_flow", knoten.id, gateway.id, prozess=prozess)
    protokoll.aenderungen.append(
        Aenderung(
            "BPMN-L4-08",
            gateway.id,
            f"Gateway vor {len(ausgehend)} ausgehenden Fluessen von {knoten.id} eingefuegt",
        )
    )


def _gateway_zusammenfuehren(
    modell: m.Modell,
    prozess: m.Prozess,
    knoten: m.Knoten,
    eingehend: list[m.Fluss],
    protokoll: Protokoll,
) -> None:
    gateway = modell.neuer_knoten("exclusive_gateway", "Zusammenfuehrung", prozess)
    _lane_uebernehmen(modell, prozess, knoten.id, gateway.id)
    for fluss in eingehend:
        fluss.ziel = gateway.id
    modell.neuer_fluss("sequence_flow", gateway.id, knoten.id, prozess=prozess)
    protokoll.aenderungen.append(
        Aenderung(
            "BPMN-L4-08",
            gateway.id,
            f"Gateway vor {len(eingehend)} eingehenden Fluessen von {knoten.id} eingefuegt",
        )
    )


def _lane_uebernehmen(modell: m.Modell, prozess: m.Prozess, von: str, nach: str) -> None:
    lane = prozess.lane_von(von)
    if lane is not None and nach not in lane.knoten:
        lane.knoten.append(nach)


def _sichere_start_ende(modell: m.Modell, prozess: m.Prozess, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    knoten = [modell.knoten[e] for e in prozess.elemente if e in modell.knoten]
    starts = [k for k in knoten if k.ist_start]
    enden = [k for k in knoten if k.ist_ende]
    if not starts:
        start = modell.neuer_knoten("start_event", "Prozessstart", prozess)
        start.stereotype = ""
        start.ereignis_rolle = "trigger"
        _lane_uebernehmen(modell, prozess, _erster_knoten(prozess, modell), start.id)
        erste = _erster_knoten(prozess, modell, ausser=start.id)
        if erste:
            modell.neuer_fluss("sequence_flow", start.id, erste, prozess=prozess)
        protokoll.aenderungen.append(
            Aenderung("BPMN-L4-14", start.id, "Startereignis ergaenzt", "", start.name)
        )
    if not enden:
        ende = modell.neuer_knoten("end_event", "Prozessende", prozess)
        ende.ereignis_rolle = "ergebnis"
        letzte = _letzter_knoten(prozess, modell, ausser=ende.id)
        _lane_uebernehmen(modell, prozess, letzte, ende.id)
        if letzte:
            modell.neuer_fluss("sequence_flow", letzte, ende.id, prozess=prozess)
        protokoll.aenderungen.append(
            Aenderung("BPMN-L4-10", ende.id, "Endereignis ergaenzt", "", ende.name)
        )


def _erster_knoten(prozess: m.Prozess, modell: m.Modell, ausser: str = "") -> str:
    for element_id in prozess.elemente:
        knoten = modell.knoten.get(element_id)
        if knoten is not None and knoten.id != ausser and not knoten.ist_ereignis:
            return knoten.id
    for element_id in prozess.elemente:
        knoten = modell.knoten.get(element_id)
        if knoten is not None and knoten.id != ausser:
            return knoten.id
    return ""


def _letzter_knoten(prozess: m.Prozess, modell: m.Modell, ausser: str = "") -> str:
    kandidaten = [
        modell.knoten[e].id
        for e in prozess.elemente
        if e in modell.knoten and e != ausser
    ]
    for kid in reversed(kandidaten):
        if not modell.ausgehend(kid):
            return kid
    return kandidaten[-1] if kandidaten else ""


def _sichere_conveyed(modell: m.Modell, prozess: m.Prozess, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    for element_id in list(prozess.knoten_ids(modell)):
        knoten = modell.knoten.get(element_id)
        if knoten is None or not knoten.ist_aufgabe:
            continue
        for richtung, fluesse in (
            ("Eingang", modell.eingehend(knoten.id)),
            ("Ausgang", modell.ausgehend(knoten.id)),
        ):
            if not fluesse:
                continue
            if any(modell.conveyed_items(f.id) for f in fluesse):
                continue
            fluss = fluesse[0]
            name = f"{knoten.name or knoten.id} -- {richtung} (benennen)"
            datenobjekt = m.Datenobjekt(
                id=modell.neue_id("DataObjectReference"),
                art="data_object_reference",
                name=name,
            )
            modell.daten[datenobjekt.id] = datenobjekt
            prozess.elemente.append(datenobjekt.id)
            modell.neuer_fluss("association", datenobjekt.id, fluss.id, prozess=prozess)
            protokoll.aenderungen.append(
                Aenderung(
                    "BPMN-L4-11",
                    datenobjekt.id,
                    f"Platzhalter fuer fehlendes Conveyed Item ({richtung}) angelegt -- fachlich zu benennen",
                    "",
                    name,
                )
            )


def _sichere_bedingungen(modell: m.Modell, prozess: m.Prozess, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    for fluss in list(modell.fluesse.values()):
        if fluss.art != "sequence_flow" or not fluss.bedingung:
            continue
        quelle = modell.knoten.get(fluss.quelle)
        if quelle is None or quelle.ist_gateway or quelle.art.startswith("intermediate"):
            continue
        ereignis = modell.neuer_knoten("intermediate_catch_event", f"Bedingung: {fluss.bedingung}", prozess)
        ereignis.ereignis_rolle = "bedingung"
        ereignis.ereignis_definition = "conditional"
        _lane_uebernehmen(modell, prozess, fluss.quelle, ereignis.id)
        alt = fluss.quelle
        fluss.quelle = ereignis.id
        modell.neuer_fluss("sequence_flow", alt, ereignis.id, prozess=prozess)
        protokoll.aenderungen.append(
            Aenderung(
                "BPMN-L4-12",
                ereignis.id,
                "Zwischenereignis vor bedingten Fluss gesetzt",
                alt,
                ereignis.id,
            )
        )


def _sichere_nachrichtenfluesse(modell: m.Modell, protokoll: Protokoll, daten: dict[str, Any]) -> None:
    for fluss in list(modell.fluesse.values()):
        if fluss.art != "message_flow":
            continue
        quelle_pool = pool_von_knoten(modell, fluss.quelle)
        ziel_pool = pool_von_knoten(modell, fluss.ziel)
        if quelle_pool is not None and ziel_pool is not None and quelle_pool.id == ziel_pool.id:
            # Innerhalb eines Pools ist der Nachrichtenfluss fachlich ein
            # Kontrollfluss; BPMN laesst ihn dort gar nicht zu.
            fluss.art = "sequence_flow"
            if modell.kollaboration is not None and fluss.id in modell.kollaboration.botschaftsfluesse:
                modell.kollaboration.botschaftsfluesse.remove(fluss.id)
            prozess = modell.prozess_von_element(fluss.quelle)
            if prozess is not None and fluss.id not in prozess.elemente:
                prozess.elemente.append(fluss.id)
            protokoll.aenderungen.append(
                Aenderung(
                    "BPMN-L4-13",
                    fluss.id,
                    "Nachrichtenfluss innerhalb eines Pools in einen Kontrollfluss umgewandelt",
                    "message_flow",
                    "sequence_flow",
                )
            )
            continue
        if not modell.conveyed_items(fluss.id):
            datenobjekt = m.Datenobjekt(
                id=modell.neue_id("DataObjectReference"),
                art="data_object_reference",
                name=f"{fluss.name or fluss.id} -- Nachricht (benennen)",
            )
            modell.daten[datenobjekt.id] = datenobjekt
            prozess = modell.prozess_von_element(fluss.quelle)
            if prozess is not None:
                prozess.elemente.append(datenobjekt.id)
                modell.neuer_fluss("association", datenobjekt.id, fluss.id, prozess=prozess)
            protokoll.aenderungen.append(
                Aenderung(
                    "BPMN-L4-13",
                    datenobjekt.id,
                    "Platzhalter fuer fehlendes Conveyed Item am Nachrichtenfluss",
                    "",
                    datenobjekt.name,
                )
            )


def konform_machen_und_pruefen(modell: m.Modell) -> tuple[Protokoll, list[Befund]]:
    """Bequemer Doppelschritt: reparieren, dann pruefen."""
    protokoll = konform_machen(modell)
    return protokoll, pruefe(modell)
