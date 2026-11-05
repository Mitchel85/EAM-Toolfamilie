"""Deterministische Anordnung eines BPMN-Modells.

Kein Zufall, keine Uhrzeit, keine Abhaengigkeit von der Einfuegereihenfolge
der Woerterbuecher: Gleiches Modell ergibt gleiche Geometrie. Damit sind SVG
und PNG byte-stabil und als Goldenfiles pruefbar.

Das Verfahren ist bewusst einfach (kein Sugiyama mit Kreuzungsminimierung):

1. Raenge aus den Sequenzfluessen (laengster Weg ab Startereignis).
2. Je Pool ein Band je Lane, in Dokumentreihenfolge.
3. Knoten eines Rangs stehen in ihrer Lane untereinander, sortiert nach
   Kennung. Spaltenbreite und Bandhoehe richten sich nach dem dichtesten
   Rang.
4. Kanten laufen rechtwinklig mit festen Stuetzpunkten.
"""

from __future__ import annotations

from . import modell as m

#: Abstand vom Blattrand.
RAND = 40.0
#: Breite einer Rangspalte.
SPALTE = 220.0
#: Hoehe einer Zeile innerhalb einer Lane.
ZEILE = 80.0
#: Kopfhoehe eines Pools (Beschriftung).
POOL_KOPF = 30.0
#: Mindesthoehe einer Lane.
BAND_MIN = 90.0
#: Abstand der Knoten vom Lane-Rand.
INNEN = 20.0

GROESSE = {
    "task": (140.0, 60.0),
    "service_task": (140.0, 60.0),
    "user_task": (140.0, 60.0),
    "send_task": (140.0, 60.0),
    "receive_task": (140.0, 60.0),
    "script_task": (140.0, 60.0),
    "manual_task": (140.0, 60.0),
    "business_rule_task": (140.0, 60.0),
    "start_event": (36.0, 36.0),
    "end_event": (36.0, 36.0),
    "intermediate_catch_event": (36.0, 36.0),
    "intermediate_throw_event": (36.0, 36.0),
    "exclusive_gateway": (44.0, 44.0),
    "parallel_gateway": (44.0, 44.0),
    "inclusive_gateway": (44.0, 44.0),
    "event_based_gateway": (44.0, 44.0),
    "complex_gateway": (44.0, 44.0),
    "data_object_reference": (100.0, 50.0),
    "data_object": (100.0, 50.0),
}


def groesse(knoten: m.Knoten) -> tuple[float, float]:
    return GROESSE.get(knoten.art, (120.0, 60.0))


def raenge(modell: m.Modell, prozess: m.Prozess) -> dict[str, int]:
    """Rang je Knoten: laengster Weg ab einem Startereignis.

    Zyklen werden nicht bestraft: ein bereits gesetzter Rang wird nicht
    ueberschrieben, wenn der neue Weg nicht laenger ist. Das Ergebnis ist
    damit auch fuer unsaubere Modelle definiert.
    """
    knoten_ids = prozess.knoten_ids(modell)
    rang: dict[str, int] = {}
    for kid in knoten_ids:
        if modell.knoten[kid].ist_start:
            rang[kid] = 0
    # Breitensuche mit Entspannung, begrenzt durch die Knotenzahl.
    for _ in range(len(knoten_ids) + 1):
        geaendert = False
        for kid in knoten_ids:
            if kid not in rang:
                continue
            for fluss in modell.ausgehend(kid):
                if fluss.ziel not in rang or rang[fluss.ziel] < rang[kid] + 1:
                    if fluss.ziel in rang and rang[fluss.ziel] >= rang[kid] + 1:
                        continue
                    if fluss.ziel in prozess.elemente:
                        rang[fluss.ziel] = rang[kid] + 1
                        geaendert = True
        if not geaendert:
            break
    # Alles, was von keinem Start erreichbar ist, hinten anstellen.
    naechster = max(rang.values(), default=-1) + 1
    for kid in knoten_ids:
        if kid not in rang:
            rang[kid] = naechster
    return rang


def _lane_reihenfolge(prozess: m.Prozess) -> list[m.Lane]:
    """Lanes in Dokumentreihenfolge, verschachtelte nach ihrer Mutter."""
    ergebnis: list[m.Lane] = []
    for lane_set in prozess.lane_sets:
        for lane in lane_set.lanes:
            for eintrag in lane.alle_lanes():
                ergebnis.append(eintrag)
    return ergebnis


def verteile(modell: m.Modell) -> m.Modell:
    """Setzt Begrenzungen, Wegpunkte und ein Diagramm. Aendert das Modell.

    Vorhandene Geometrie wird verworfen -- die Anordnung ist eine bewusste
    Neuberechnung und kein Flickwerk.
    """
    for knoten in modell.knoten.values():
        knoten.begrenzung = None
    for daten in modell.daten.values():
        daten.begrenzung = None
    for fluss in modell.fluesse.values():
        fluss.wegpunkte = []
    for prozess in modell.prozesse.values():
        for lane in prozess.alle_lanes():
            lane.begrenzung = None
    for teilnehmer in modell.alle_teilnehmer():
        teilnehmer.begrenzung = None
    modell.diagramme.clear()

    y = RAND
    for teilnehmer in modell.alle_teilnehmer():
        prozess = modell.prozesse.get(teilnehmer.prozess_ref)
        if prozess is None:
            continue
        lanes = _lane_reihenfolge(prozess)
        lane_index = {lane.id: i for i, lane in enumerate(lanes)}
        rang = raenge(modell, prozess)
        knoten_ids = prozess.knoten_ids(modell)

        # Zuordnung Knoten -> Band (Lane oder Sammelband).
        band: dict[str, int] = {}
        for kid in knoten_ids:
            lane = prozess.lane_von(kid)
            if lane is not None:
                band[kid] = lane_index[lane.id]
            else:
                band[kid] = len(lanes)  # Sammelband "ohne Lane"

        anzahl_baender = len(lanes) + (1 if any(b == len(lanes) for b in band.values()) else 0)
        # Dichte je Band und Rang.
        dichte: dict[tuple[int, int], int] = {}
        for kid in knoten_ids:
            schluessel = (band[kid], rang[kid])
            dichte[schluessel] = dichte.get(schluessel, 0) + 1

        band_hoehe: list[float] = []
        for b in range(anzahl_baender):
            hoechste = 1
            for (bb, _r), n in dichte.items():
                if bb == b:
                    hoechste = max(hoechste, n)
            band_hoehe.append(max(BAND_MIN, hoechste * ZEILE + 2 * INNEN))

        hoechster_rang = max(rang.values(), default=0)
        breite = RAND + (hoechster_rang + 1) * SPALTE + 80.0
        hoehe = sum(band_hoehe) + POOL_KOPF

        teilnehmer.begrenzung = m.Begrenzung(RAND, y, breite, hoehe)

        # Lane-Baender von oben nach unten.
        band_oben: list[float] = []
        lauf = y + POOL_KOPF
        for h in band_hoehe:
            band_oben.append(lauf)
            lauf += h
        for lane in lanes:
            b = lane_index[lane.id]
            lane.begrenzung = m.Begrenzung(RAND, band_oben[b], breite, band_hoehe[b])

        # Knoten setzen: je (Band, Rang) untereinander.
        zaehler: dict[tuple[int, int], int] = {}
        for kid in sorted(knoten_ids, key=lambda k: (rang[k], band[k], k)):
            knoten = modell.knoten[kid]
            b = band[kid]
            r = rang[kid]
            n = zaehler.get((b, r), 0)
            zaehler[(b, r)] = n + 1
            w, h = groesse(knoten)
            x = RAND + 60.0 + r * SPALTE
            yy = band_oben[b] + INNEN + n * ZEILE
            knoten.begrenzung = m.Begrenzung(x, yy, w, h)
        y = y + hoehe + 40.0

    # Prozess ohne Pool: eigenes Feld.
    ohne_pool = [
        p
        for p in modell.prozesse.values()
        if modell.teilnehmer_von_prozess(p.id) is None
    ]
    for prozess in ohne_pool:
        _verteile_ohne_pool(modell, prozess, y)
        y += 400.0

    _kanten(modell)
    _daten_platzieren(modell)
    _kanten_daten(modell)
    _diagramm(modell)
    return modell


def _daten_ids(modell: m.Modell, prozess: m.Prozess) -> set[str]:
    return {e for e in prozess.elemente if e in modell.daten}


def _verteile_ohne_pool(modell: m.Modell, prozess: m.Prozess, y: float) -> None:
    rang = raenge(modell, prozess)
    for kid in sorted(prozess.knoten_ids(modell), key=lambda k: (rang[k], k)):
        knoten = modell.knoten[kid]
        w, h = groesse(knoten)
        knoten.begrenzung = m.Begrenzung(
            RAND + 60.0 + rang[kid] * SPALTE, y + 60.0, w, h
        )


def _daten_platzieren(modell: m.Modell) -> None:
    """Datenobjekte ueber ihrem Fluss anordnen.

    Ueber dem Pool, senkrecht ueber dem Ankerpunkt des Flusses: Die
    Assoziation bleibt kurz und kreuzt keine Aktion.
    """
    for prozess in modell.prozesse.values():
        ids = [e for e in prozess.elemente if e in modell.daten]
        if not ids:
            continue
        teilnehmer = modell.teilnehmer_von_prozess(prozess.id)
        pool = teilnehmer.begrenzung if teilnehmer is not None else None
        knoten_bounds = [
            b
            for b in (modell.knoten[e].begrenzung for e in prozess.elemente if e in modell.knoten)
            if b is not None
        ]
        oben = min((b.y for b in knoten_bounds), default=RAND)
        y = (pool.y - 90.0) if pool is not None and pool.y >= 140.0 else oben - 90.0
        if y < RAND:
            y = (pool.unten + 20.0) if pool is not None else oben + 100.0
        for nummer, did in enumerate(sorted(ids)):
            daten = modell.daten[did]
            if daten.begrenzung is not None:
                continue
            anker = _ankerpunkt(modell, daten.id)
            x = (anker.x - 50.0) if anker is not None else RAND + nummer * 130.0
            daten.begrenzung = m.Begrenzung(x, y + nummer * 0.0, 120.0, 50.0)


def _ankerpunkt(modell: m.Modell, daten_id: str) -> m.Punkt | None:
    """Punkt, an dem das Datenobjekt haengt (Knoten oder Flussmitte)."""
    for fluss in modell.fluesse.values():
        if fluss.art != "association":
            continue
        if fluss.quelle == daten_id or fluss.ziel == daten_id:
            _, element_id = modell.assoziation_enden(fluss)
            knoten = modell.knoten.get(element_id)
            if knoten is not None and knoten.begrenzung is not None:
                return m.Punkt(knoten.begrenzung.mitte_x, knoten.begrenzung.y)
            anderer = modell.fluesse.get(element_id)
            if anderer is not None and anderer.wegpunkte:
                return anderer.wegpunkte[len(anderer.wegpunkte) // 2]
    return None


def _kanten_daten(modell: m.Modell) -> None:
    """Assoziationen erst nach dem Platzieren der Datenobjekte routen."""
    for fluss in modell.fluesse.values():
        if fluss.art != "association" or fluss.wegpunkte:
            continue
        fluss.wegpunkte = _wegpunkte_daten(modell, fluss)


def _anknuepfung(modell: m.Modell, knoten_id: str, rechts: bool) -> m.Punkt:
    knoten = modell.knoten.get(knoten_id)
    if knoten is None or knoten.begrenzung is None:
        return m.Punkt(RAND, RAND)
    b = knoten.begrenzung
    return m.Punkt(b.rechts if rechts else b.x, b.mitte_y)


def _kanten(modell: m.Modell) -> None:
    for fluss in modell.fluesse.values():
        if fluss.art == "association" or fluss.wegpunkte:
            continue
        if fluss.quelle in modell.daten or fluss.ziel in modell.daten:
            fluss.wegpunkte = _wegpunkte_daten(modell, fluss)
            continue
        if fluss.quelle not in modell.knoten or fluss.ziel not in modell.knoten:
            continue
        start = _anknuepfung(modell, fluss.quelle, True)
        ende = _anknuepfung(modell, fluss.ziel, False)
        if ende.x < start.x:  # Rueckkante: unten herum
            fluss.wegpunkte = [
                start,
                m.Punkt(start.x + 30.0, start.y),
                m.Punkt(start.x + 30.0, start.y + 60.0),
                m.Punkt(ende.x - 30.0, start.y + 60.0),
                m.Punkt(ende.x - 30.0, ende.y),
                ende,
            ]
        else:
            mitte = (start.x + ende.x) / 2.0
            fluss.wegpunkte = [
                start,
                m.Punkt(mitte, start.y),
                m.Punkt(mitte, ende.y),
                ende,
            ]


def _wegpunkte_daten(modell: m.Modell, fluss: m.Fluss) -> list[m.Punkt]:
    """Assoziation von einem Datenobjekt zu seinem Element: kurzer Weg.

    Das Element ist der Knoten (so steht es im XML) -- nicht der Fluss, an dem
    die Assoziation fachlich haengt.
    """
    daten_id, element_id = modell.assoziation_enden(fluss)
    daten = modell.daten.get(daten_id)
    if daten is None:
        return []
    if daten.begrenzung is None:
        daten.begrenzung = m.Begrenzung(RAND, RAND, 100.0, 50.0)
    start = m.Punkt(daten.begrenzung.mitte_x, daten.begrenzung.mitte_y)
    knoten = modell.knoten.get(element_id)
    if knoten is not None and knoten.begrenzung is not None:
        b = knoten.begrenzung
        if b.mitte_y <= daten.begrenzung.mitte_y:
            return [start, m.Punkt(b.mitte_x, b.y)]
        return [start, m.Punkt(b.mitte_x, b.unten)]
    ziel_fluss = modell.fluesse.get(element_id)
    if ziel_fluss is not None and ziel_fluss.wegpunkte:
        anker = ziel_fluss.wegpunkte[len(ziel_fluss.wegpunkte) // 2]
        return [start, m.Punkt(anker.x, anker.y)]
    return [start]


def _diagramm(modell: m.Modell) -> None:
    """Ein Diagramm je Kollaboration bzw. je Pool-freiem Prozess."""
    if modell.diagramme:
        # Vorhandene Diagramme mit neuen Formen ergaenzen.
        for diagramm in modell.diagramme:
            _formen_ergaenzen(modell, diagramm)
        return
    if modell.kollaboration is not None:
        diagramm = m.Diagramm(
            id="BPMNDiagram_1",
            name=modell.kollaboration.name or modell.name,
            ebenen_element=modell.kollaboration.id,
        )
        modell.diagramme.append(diagramm)
        _formen_ergaenzen(modell, diagramm)
        return
    nummer = 1
    for prozess in modell.prozesse.values():
        diagramm = m.Diagramm(
            id=f"BPMNDiagram_{nummer}",
            name=prozess.name,
            ebenen_element=prozess.id,
        )
        nummer += 1
        modell.diagramme.append(diagramm)
        _formen_ergaenzen(modell, diagramm)


def _formen_ergaenzen(modell: m.Modell, diagramm: m.Diagramm) -> None:
    vorhanden = {f.element_ref for f in diagramm.formen}
    kanten = {k.element_ref for k in diagramm.kanten}

    def form(element_id: str, begrenzung: m.Begrenzung | None, ausgeklappt: bool = True) -> None:
        if begrenzung is None or element_id in vorhanden:
            return
        diagramm.formen.append(m.Form(element_id, begrenzung, ist_ausgeklappt=ausgeklappt))
        vorhanden.add(element_id)

    for teilnehmer in modell.alle_teilnehmer():
        form(teilnehmer.id, teilnehmer.begrenzung)
    for prozess in modell.prozesse.values():
        for lane in prozess.alle_lanes():
            form(lane.id, lane.begrenzung)
    for knoten in modell.knoten.values():
        form(knoten.id, knoten.begrenzung)
    for daten in modell.daten.values():
        form(daten.id, daten.begrenzung)
    for fluss in modell.fluesse.values():
        if fluss.id in kanten or not fluss.wegpunkte:
            continue
        diagramm.kanten.append(m.Kante(fluss.id, list(fluss.wegpunkte)))
        kanten.add(fluss.id)


def braucht_layout(modell: m.Modell) -> bool:
    """Wahr, wenn Knoten ohne Geometrie vorliegen."""
    return any(k.begrenzung is None for k in modell.knoten.values())
