"""roundtrip_metrics.py -- Treuequote zwischen Original-.qea und Rueckbau-.qea.

Das Werkzeug vergleicht zwei Sparx-EA-SQLite-Dateien (Original und Rueckbau)
und berechnet eine gewichtete Treuequote. Es liest ausschliesslich
(``mode=ro`` plus ``PRAGMA query_only``), schreibt nie in die Modelle und
liefert deterministische Ausgaben: keine Zeitstempel, keine Zufallswerte,
sortierte Listen und auf zwei Nachkommastellen gerundete Quoten.

Dimensionen und Gewichte
------------------------
* Elemente 45 % -- Schluessel ``(Paketpfad, Stereotyp, Name)``
* Kanten   30 % -- Schluessel ``(Quelle, Stereotyp, Typ, Ziel)``
* Pakete   15 % -- Schluessel ``Paketpfad``
* Tags     10 % -- je Element die Menge ``(Property, Value)``, Jaccard

Alle Schluessel werden normalisiert: Unicode-NFC und ``strip``. Namen bleiben
bewusst case-sensitiv, weil Gross-/Kleinschreibung in einem EA-Modell
bedeutungstragend sein kann. Mehrfach vorkommende Schluessel werden als
Multimenge verglichen (jede Vorkommnis muss wieder auftauchen); fehlende
Vorkommnnisse zaehlen als 0 und nicht als Teiltreffer. Die Gesamtquote wird
aus den gerundeten Dimensionsquoten gebildet, damit die Tabelle im Bericht
nachrechenbar bleibt.

Fachliche Festlegungen (bewusst und dokumentiert)
-------------------------------------------------
1. **Paketspiegel sind keine Elemente.** ``t_object`` enthaelt je Paket eine
   Zeile mit ``Object_Type = 'Package'`` (in der MASC 225 Stueck). Diese Zeilen
   werden ueber die Paket-Dimension gemessen, nicht zusaetzlich als Elemente.
   Die Rohzahl aller ``t_object``-Zeilen steht als ``elemente_gesamt`` im
   Bericht, damit nichts verdeckt wird.
2. **Leere Tag-Werte zaehlen als "leer".** In der MASC sind 5416 der 9237
   ``t_objectproperties``-Zeilen ohne Wert (NULL). Ein NULL-Wert wird zum
   Sentinel ``""`` normalisiert. Zusaetzlich wird bei leeren Werten in
   ``t_xref`` (``Type = 'element property'``, ``Client`` = Element-GUID,
   ``@PROP=``-Block mit passendem ``@NAME=``) nachgesehen, weil EA Werte
   dorthin auslagert. Die ``CustomProperties``- und ``Stereotypes``-Bloecke in
   ``t_xref`` zaehlen **nicht** als eigene Tags: sonst wuerde jeder Rueckbau
   ohne xref systematisch abgewertet, obwohl er fachlich vollstaendig ist.
3. **Sichten und Attribute sind Rohzahlen.** ``t_diagram``, ``t_diagramobjects``,
   ``t_diagramlinks`` und ``t_attribute`` gehen nicht in die Quote ein, weil der
   Rueckbau sie bewusst nicht erzeugt. Sie stehen in den Kennzahlen, damit der
   Verlust sichtbar bleibt.
4. **Leere Mengen sind treu.** Haben Original und Rueckbau keine Elemente,
   Kanten oder Pakete, gilt die Quote dieser Dimension als 100 % (es gibt
   nichts zu verlieren). Zwei leere Tag-Mengen ergeben Jaccard 1.0.
5. **Gleichnamige Geschwisterpakete** bekommen keinen ``#N``-Zusatz; ihre
   Pfade sind identisch. Die Paket-Dimension zaehlt Pfade als Multimenge, die
   Element-Dimension fasst sie dadurch zusammen (in der MASC betrifft das
   zweimal ``.../Modellelementekatalog/Views``).

CLI::

    python3 roundtrip_metrics.py ORIGINAL.qea NEU.qea --json bericht.json --md bericht.md

Exit-Codes: 0 immer dann, wenn ein Bericht entsteht (auch bei schlechter Quote);
2, wenn eine Datei nicht lesbar/keine gueltige .qea ist oder ein Bericht nicht
geschrieben werden kann -- mit Klartext auf stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

FORMAT_VERSION = "1"

# Gewichte der Dimensionen in Prozent; Summe = 100.
GEWICHTE: dict[str, int] = {"elemente": 45, "kanten": 30, "pakete": 15, "tags": 10}

# Obergrenze fuer die Fehllisten im JSON (die Zaehler stehen daneben vollstaendig).
LISTEN_LIMIT = 200
TOP = 20

OHNE_PAKET = "(ohne Paket)"
OHNE_NAMEN = "(ohne Namen)"
UNBEKANNT = "(unbekannt)"


class MetrikFehler(Exception):
    """Fachlicher Fehler: Datei nicht lesbar oder keine gueltige .qea."""


# ---------------------------------------------------------------------------
# Kleine Helfer
# ---------------------------------------------------------------------------


def _norm(wert: Any) -> str:
    """Normalisiert Text: Unicode-NFC und Aussenabstand weg."""
    if wert is None:
        return ""
    return unicodedata.normalize("NFC", str(wert)).strip()


def _tabellen(con: sqlite3.Connection) -> dict[str, str]:
    """Abbildung klein geschriebener Tabellenname -> tatsaechlicher Name."""
    namen = [zeile[0] for zeile in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {name.lower(): name for name in namen}


def _spalten(con: sqlite3.Connection, tabelle: str) -> dict[str, str]:
    """Abbildung klein geschriebener Spaltenname -> tatsaechlicher Name."""
    return {zeile[1].lower(): zeile[1] for zeile in con.execute(f'PRAGMA table_info("{tabelle}")')}


def _spalte(spalten: Mapping[str, str], *namen: str) -> str | None:
    for name in namen:
        if name.lower() in spalten:
            return spalten[name.lower()]
    return None


def _oeffne_readonly(pfad: Path) -> sqlite3.Connection:
    """Oeffnet eine .qea garantiert lesend und prueft, dass es eine SQLite-DB ist."""
    if not pfad.exists():
        raise MetrikFehler(f"Datei nicht gefunden: {pfad}")
    if not pfad.is_file():
        raise MetrikFehler(f"keine regulaere Datei: {pfad}")
    try:
        con = sqlite3.connect(f"file:{quote(str(pfad))}?mode=ro", uri=True)
        con.execute("PRAGMA query_only = ON")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as fehler:
        raise MetrikFehler(f"keine lesbare .qea/SQLite-Datei: {pfad} ({fehler})") from fehler
    con.row_factory = sqlite3.Row
    return con


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _zaehle(con: sqlite3.Connection, tabellen: Mapping[str, str], name: str) -> int:
    echt = tabellen.get(name.lower())
    if echt is None:
        return 0
    return int(con.execute(f'SELECT count(*) FROM "{echt}"').fetchone()[0])


# ---------------------------------------------------------------------------
# Modell lesen
# ---------------------------------------------------------------------------


@dataclass
class Element:
    """Ein fachliches Element (ohne Paketspiegel) mit Pfad, Stereotyp, Tags."""

    pfad: str
    name: str
    stereotyp: str
    typ: str
    tags: frozenset[tuple[str, str]] = frozenset()

    @property
    def schluessel(self) -> tuple[str, str, str]:
        return (self.pfad, self.stereotyp, self.name)

    @property
    def schluessel_ohne_pfad(self) -> tuple[str, str]:
        return (self.stereotyp, self.name)


@dataclass
class Kante:
    """Eine Kante mit aufgeloesten Endpunktnamen."""

    quelle: str
    ziel: str
    typ: str
    stereotyp: str

    @property
    def schluessel(self) -> tuple[str, str, str, str]:
        return (self.quelle, self.stereotyp, self.typ, self.ziel)


@dataclass
class Modell:
    """Alles, was fuer den Vergleich gebraucht wird."""

    datei: str
    sha256: str
    kennzahlen: dict[str, int]
    elemente: list[Element] = field(default_factory=list)
    kanten: list[Kante] = field(default_factory=list)
    pakete: list[str] = field(default_factory=list)


_PROP_BLOCK = re.compile(r"@PROP=", re.S)
_PROP_NAME = re.compile(r"@NAME=(.*?)@ENDNAME;", re.S)
_PROP_WERT = re.compile(r"@VALU=(.*?)@ENDVALU;", re.S)


def _parse_prop_bloecke(beschreibung: str | None) -> dict[str, str]:
    """Liest ``@PROP=...@NAME=x;@VALU=y;...@ENDPROP;`` aus einer t_xref-Zeile."""
    if not beschreibung:
        return {}
    ergebnis: dict[str, str] = {}
    for block in _PROP_BLOCK.split(str(beschreibung))[1:]:
        name = _PROP_NAME.search(block)
        if name is None:
            continue
        wert = _PROP_WERT.search(block)
        schluessel = _norm(name.group(1))
        if schluessel and schluessel not in ergebnis:
            ergebnis[schluessel] = _norm(wert.group(1)) if wert else ""
    return ergebnis


def _xref_werte(
    con: sqlite3.Connection,
    tabellen: Mapping[str, str],
    spalten: Mapping[str, str] | None,
) -> dict[str, dict[str, str]]:
    """GUID (gross geschrieben) -> {Property: Wert} aus t_xref, nur Element-Properties."""
    if spalten is None:
        return {}
    echt = tabellen["t_xref"]
    sp_client = _spalte(spalten, "Client")
    sp_typ = _spalte(spalten, "Type")
    sp_desc = _spalte(spalten, "Description")
    sp_xid = _spalte(spalten, "XrefID")
    if not (sp_client and sp_typ and sp_desc):
        return {}
    order = f'"{sp_xid}"' if sp_xid else "rowid"
    abfrage = (
        f'SELECT "{sp_client}", "{sp_desc}" FROM "{echt}" '
        f'WHERE "{sp_typ}" = \'element property\' ORDER BY {order}'
    )
    ergebnis: dict[str, dict[str, str]] = {}
    for client, beschreibung in con.execute(abfrage):
        guid = _norm(client).upper()
        if not guid or guid == "<NONE>":
            continue
        ziel = ergebnis.setdefault(guid, {})
        for name, wert in _parse_prop_bloecke(beschreibung).items():
            ziel.setdefault(name, wert)
    return ergebnis


def _lies_pakete(
    con: sqlite3.Connection, tabellen: Mapping[str, str]
) -> tuple[dict[int, tuple[str, int | None]], dict[int, str]]:
    """Liest t_package und berechnet je Paket-ID den vollen Pfad."""
    if "t_package" not in tabellen:
        return {}, {}
    echt = tabellen["t_package"]
    spalten = _spalten(con, echt)
    sp_id = _spalte(spalten, "Package_ID")
    sp_name = _spalte(spalten, "Name")
    sp_parent = _spalte(spalten, "Parent_ID")
    if sp_id is None:
        return {}, {}
    spalten_liste = [f'"{sp_id}"']
    spalten_liste.append(f'"{sp_name}"' if sp_name else "NULL")
    spalten_liste.append(f'"{sp_parent}"' if sp_parent else "NULL")
    roh: dict[int, tuple[str, int | None]] = {}
    for pid, name, parent in con.execute(
        f'SELECT {", ".join(spalten_liste)} FROM "{echt}" ORDER BY "{sp_id}"'
    ):
        try:
            ident = int(pid)
        except (TypeError, ValueError):
            continue
        parent_id: int | None
        try:
            parent_id = int(parent) if parent is not None else None
        except (TypeError, ValueError):
            parent_id = None
        roh[ident] = (_norm(name), parent_id)
    return roh, _pfade(roh)


def _pfade(roh: Mapping[int, tuple[str, int | None]]) -> dict[int, str]:
    """Bildet Paket-ID auf ``A/B/C`` ab; Zyklen und Waisen brechen sauber ab."""
    pfade: dict[int, str] = {}
    for start in sorted(roh):
        teile: list[str] = []
        gesehen: set[int] = set()
        aktuell: int | None = start
        while aktuell is not None and aktuell in roh and aktuell not in gesehen:
            gesehen.add(aktuell)
            name, parent = roh[aktuell]
            teile.append(name or OHNE_NAMEN)
            aktuell = parent
        pfade[start] = "/".join(reversed(teile))
    return pfade


def _lies_tags(
    con: sqlite3.Connection, tabellen: Mapping[str, str]
) -> dict[int, set[tuple[str, str]]]:
    """Liest t_objectproperties als {Object_ID: {(Property, Wert)}}; NULL -> ''."""
    if "t_objectproperties" not in tabellen:
        return {}
    echt = tabellen["t_objectproperties"]
    spalten = _spalten(con, echt)
    sp_obj = _spalte(spalten, "Object_ID")
    sp_prop = _spalte(spalten, "Property")
    sp_wert = _spalte(spalten, "Value")
    sp_id = _spalte(spalten, "PropertyID")
    if sp_obj is None or sp_prop is None:
        return {}
    order = f'"{sp_id}"' if sp_id else "rowid"
    wert_ausdruck = f'"{sp_wert}"' if sp_wert else "NULL"
    ergebnis: dict[int, set[tuple[str, str]]] = defaultdict(set)
    for oid, prop, wert in con.execute(
        f'SELECT "{sp_obj}", "{sp_prop}", {wert_ausdruck} FROM "{echt}" ORDER BY {order}'
    ):
        try:
            ident = int(oid)
        except (TypeError, ValueError):
            continue
        name = _norm(prop)
        if not name:
            continue
        ergebnis[ident].add((name, _norm(wert)))
    return dict(ergebnis)


def _lies_elemente(
    con: sqlite3.Connection,
    tabellen: Mapping[str, str],
    pfade: Mapping[int, str],
    tags: Mapping[int, set[tuple[str, str]]],
    xref: Mapping[str, Mapping[str, str]],
) -> list[Element]:
    """Liest t_object ohne Paketspiegel und haengt Pfad und Tags an."""
    if "t_object" not in tabellen:
        raise MetrikFehler("keine gueltige .qea: Tabelle t_object fehlt")
    echt = tabellen["t_object"]
    spalten = _spalten(con, echt)
    sp_id = _spalte(spalten, "Object_ID")
    if sp_id is None:
        raise MetrikFehler(f"keine gueltige .qea: {echt} hat keine Spalte Object_ID")
    sp_name = _spalte(spalten, "Name")
    sp_typ = _spalte(spalten, "Object_Type")
    sp_stereo = _spalte(spalten, "Stereotype")
    sp_pkg = _spalte(spalten, "Package_ID")
    sp_guid = _spalte(spalten, "ea_guid")
    felder = [
        f'"{sp_id}"',
        f'"{sp_name}"' if sp_name else "NULL",
        f'"{sp_typ}"' if sp_typ else "NULL",
        f'"{sp_stereo}"' if sp_stereo else "NULL",
        f'"{sp_pkg}"' if sp_pkg else "NULL",
        f'"{sp_guid}"' if sp_guid else "NULL",
    ]
    elemente: list[Element] = []
    for oid, name, typ, stereotyp, pkg, guid in con.execute(
        f'SELECT {", ".join(felder)} FROM "{echt}" ORDER BY "{sp_id}"'
    ):
        if _norm(typ).lower() == "package":
            continue
        try:
            ident = int(oid)
        except (TypeError, ValueError):
            ident = -1
        try:
            pkg_id = int(pkg) if pkg is not None else None
        except (TypeError, ValueError):
            pkg_id = None
        pfad = pfade.get(pkg_id, OHNE_PAKET) if pkg_id is not None else OHNE_PAKET
        eigene_tags = set(tags.get(ident, ()))
        if guid:
            ergaenzung = xref.get(_norm(guid).upper(), {})
            for prop, wert in ergaenzung.items():
                # Nur leere Werte aufloesen. Zusaetzliche xref-Properties
                # (CustomProperties wie _HideUmlLinks) werden NICHT als Tags
                # gezaehlt -- sonst wuerde jeder Rueckbau ohne xref abgewertet.
                if wert and (prop, "") in eigene_tags:
                    eigene_tags.discard((prop, ""))
                    eigene_tags.add((prop, wert))
        elemente.append(
            Element(
                pfad=pfad,
                name=_norm(name),
                stereotyp=_norm(stereotyp),
                typ=_norm(typ),
                tags=frozenset(eigene_tags),
            )
        )
    return elemente


def _lies_kanten(
    con: sqlite3.Connection, tabellen: Mapping[str, str]
) -> list[Kante]:
    """Liest t_connector und loest die Endpunkte ueber die Object_ID auf Namen auf.

    Endpunkte werden gegen **alle** ``t_object``-Zeilen aufgeloest, auch gegen
    Paketspiegel: 231 der 1747 MASC-Kanten haengen an einem Paket, und ohne
    diesen Namen waeren zwei verschiedene Paketenden nicht unterscheidbar.
    """
    if "t_connector" not in tabellen:
        return []
    echt = tabellen["t_connector"]
    spalten = _spalten(con, echt)
    sp_id = _spalte(spalten, "Connector_ID")
    sp_typ = _spalte(spalten, "Connector_Type")
    sp_stereo = _spalte(spalten, "Stereotype")
    sp_start = _spalte(spalten, "Start_Object_ID")
    sp_ende = _spalte(spalten, "End_Object_ID")
    if sp_start is None or sp_ende is None:
        return []
    felder = [
        f'"{sp_typ}"' if sp_typ else "NULL",
        f'"{sp_stereo}"' if sp_stereo else "NULL",
        f'"{sp_start}"',
        f'"{sp_ende}"',
    ]
    reihenfolge = f'ORDER BY "{sp_id}"' if sp_id else ""
    namen = _objekt_namen(con, tabellen)
    kanten: list[Kante] = []
    for typ, stereotyp, start, ende in con.execute(
        f'SELECT {", ".join(felder)} FROM "{echt}" {reihenfolge}'
    ):
        kanten.append(
            Kante(
                quelle=_endpunkt(start, namen),
                ziel=_endpunkt(ende, namen),
                typ=_norm(typ),
                stereotyp=_norm(stereotyp),
            )
        )
    return kanten


def _objekt_namen(con: sqlite3.Connection, tabellen: Mapping[str, str]) -> dict[int, str]:
    """Object_ID -> Name fuer alle Objekte (inklusive Paketspiegel)."""
    echt = tabellen["t_object"]
    spalten = _spalten(con, echt)
    sp_id = _spalte(spalten, "Object_ID")
    sp_name = _spalte(spalten, "Name")
    if sp_id is None:
        return {}
    name_ausdruck = f'"{sp_name}"' if sp_name else "NULL"
    namen: dict[int, str] = {}
    for oid, name in con.execute(f'SELECT "{sp_id}", {name_ausdruck} FROM "{echt}"'):
        try:
            namen[int(oid)] = _norm(name)
        except (TypeError, ValueError):
            continue
    return namen


def _endpunkt(wert: Any, namen: Mapping[int, str]) -> str:
    """Object_ID -> Elementname; unbekannte oder leere IDs ergeben einen Sentinel."""
    try:
        ident = int(wert)
    except (TypeError, ValueError):
        return UNBEKANNT
    return namen.get(ident, UNBEKANNT)


def lade_modell(pfad: str | Path) -> Modell:
    """Liest eine .qea vollstaendig in das Vergleichsmodell."""
    pfad = Path(pfad)
    con = _oeffne_readonly(pfad)
    try:
        tabellen = _tabellen(con)
        if "t_object" not in tabellen:
            raise MetrikFehler(f"keine gueltige .qea: Tabelle t_object fehlt in {pfad}")
        roh_pakete, paket_pfade = _lies_pakete(con, tabellen)
        tags = _lies_tags(con, tabellen)
        xref_spalten = _spalten(con, tabellen["t_xref"]) if "t_xref" in tabellen else None
        xref = _xref_werte(con, tabellen, xref_spalten)
        elemente = _lies_elemente(con, tabellen, paket_pfade, tags, xref)
        kanten = _lies_kanten(con, tabellen)
        kennzahlen = {
            "elemente": len(elemente),
            "elemente_gesamt": _zaehle(con, tabellen, "t_object"),
            "kanten": _zaehle(con, tabellen, "t_connector"),
            "pakete": _zaehle(con, tabellen, "t_package"),
            "tags": _zaehle(con, tabellen, "t_objectproperties"),
            "sichten": _zaehle(con, tabellen, "t_diagram"),
            "sicht_elemente": _zaehle(con, tabellen, "t_diagramobjects"),
            "sicht_kanten": _zaehle(con, tabellen, "t_diagramlinks"),
            "attribute": _zaehle(con, tabellen, "t_attribute"),
        }
        # Pfade bleiben als Liste erhalten: gleichnamige Geschwister ergeben
        # denselben Pfad und muessen als Multimenge zaehlen, nicht als Set.
        pakete = sorted(paket_pfade.values())
        return Modell(
            datei=pfad.name,
            sha256=_sha256(pfad),
            kennzahlen=kennzahlen,
            elemente=elemente,
            kanten=kanten,
            pakete=pakete,
        )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Vergleich
# ---------------------------------------------------------------------------


def _multiset(werte: Iterable[Any]) -> Counter:
    return Counter(werte)


def _treffer(original: Counter, neu: Counter) -> tuple[int, Counter, Counter]:
    """Multimengen-Vergleich: matched, fehlend (Original), extra (Rueckbau)."""
    matched = sum(min(anzahl, neu.get(schluessel, 0)) for schluessel, anzahl in original.items())
    fehlend = original - neu
    extra = neu - original
    return matched, fehlend, extra


def _quote(matched: int | float, gesamt: int) -> float:
    """Quote in Prozent; leere Grundmenge gilt als vollstaendig treu."""
    if gesamt <= 0:
        return 100.0
    return round(100.0 * float(matched) / float(gesamt), 2)


def _liste(counter: Counter, anzeige, limit: int = LISTEN_LIMIT) -> list[str]:
    """Deterministische Fehlliste: haeufigste zuerst, dann alphabetisch."""
    eintraege = sorted(counter.items(), key=lambda paar: (-paar[1], anzeige(paar[0])))
    ergebnis: list[str] = []
    for schluessel, anzahl in eintraege[:limit]:
        text = anzeige(schluessel)
        ergebnis.append(f"{text} (x{anzahl})" if anzahl > 1 else text)
    return ergebnis


def _tag_signatur(tags: frozenset[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(tags))


def _jaccard(links: frozenset[tuple[str, str]], rechts: frozenset[tuple[str, str]]) -> float:
    """Jaccard-Index zweier Tag-Mengen; zwei leere Mengen sind identisch (1.0)."""
    if not links and not rechts:
        return 1.0
    vereinigung = links | rechts
    if not vereinigung:
        return 1.0
    return len(links & rechts) / len(vereinigung)


def _tag_paare(
    original: Sequence[Element], neu: Sequence[Element]
) -> tuple[float, int, int]:
    """Paart Elemente je Schluessel und summiert Jaccard.

    Rueckgabe: (Summe Jaccard, Anzahl identischer Tag-Mengen, Anzahl gepruefter
    Original-Elemente). Nicht wiedergefundene Original-Elemente zaehlen mit 0.
    """
    gruppen_original: dict[tuple[str, str, str], list[Element]] = defaultdict(list)
    gruppen_neu: dict[tuple[str, str, str], list[Element]] = defaultdict(list)
    for element in original:
        gruppen_original[element.schluessel].append(element)
    for element in neu:
        gruppen_neu[element.schluessel].append(element)

    summe = 0.0
    identisch = 0
    geprueft = 0
    for schluessel in sorted(gruppen_original):
        links = sorted(gruppen_original[schluessel], key=lambda e: _tag_signatur(e.tags))
        rechts = sorted(gruppen_neu.get(schluessel, []), key=lambda e: _tag_signatur(e.tags))
        for index, element in enumerate(links):
            geprueft += 1
            if index < len(rechts):
                wert = _jaccard(element.tags, rechts[index].tags)
            else:
                wert = 0.0
            summe += wert
            if wert >= 1.0:
                identisch += 1
    return summe, identisch, geprueft


def vergleiche(original: Modell, neu: Modell) -> dict[str, Any]:
    """Berechnet alle Treffer und die gewichtete Gesamtquote."""
    element_matched, element_fehlt, element_extra = _treffer(
        _multiset(e.schluessel for e in original.elemente),
        _multiset(e.schluessel for e in neu.elemente),
    )
    element_ohne_pfad, _, _ = _treffer(
        _multiset(e.schluessel_ohne_pfad for e in original.elemente),
        _multiset(e.schluessel_ohne_pfad for e in neu.elemente),
    )
    kanten_matched, kanten_fehlt, kanten_extra = _treffer(
        _multiset(k.schluessel for k in original.kanten),
        _multiset(k.schluessel for k in neu.kanten),
    )
    pakete_matched, pakete_fehlt, pakete_extra = _treffer(
        _multiset(original.pakete), _multiset(neu.pakete)
    )
    tag_summe, tag_identisch, tag_geprueft = _tag_paare(original.elemente, neu.elemente)

    element_quote = _quote(element_matched, len(original.elemente))
    kanten_quote = _quote(kanten_matched, len(original.kanten))
    pakete_quote = _quote(pakete_matched, len(original.pakete))
    tags_quote = _quote(tag_summe, tag_geprueft)

    quoten = {
        "elemente": element_quote,
        "kanten": kanten_quote,
        "pakete": pakete_quote,
        "tags": tags_quote,
    }
    gesamt = sum(GEWICHTE[name] * quote_ / 100.0 for name, quote_ in quoten.items())

    anzeige_element = lambda schluessel: (
        f"{schluessel[0]} | {schluessel[2] or OHNE_NAMEN} | {schluessel[1] or '-'}"
    )
    anzeige_kante = lambda schluessel: (
        f"{schluessel[0] or OHNE_NAMEN} -> {schluessel[3] or OHNE_NAMEN}"
        f" | {schluessel[2] or '-'} | {schluessel[1] or '-'}"
    )

    return {
        "element_quote": element_quote,
        "kanten_quote": kanten_quote,
        "pakete_quote": pakete_quote,
        "tags_quote": tags_quote,
        "gesamtquote": round(gesamt, 2),
        "treffer": {
            "elemente": {
                "matched": element_matched,
                "quote": element_quote,
                "fehlend_gesamt": sum(element_fehlt.values()),
                "extra_gesamt": sum(element_extra.values()),
                "ohne_pfad": {
                    "matched": element_ohne_pfad,
                    "quote": _quote(element_ohne_pfad, len(original.elemente)),
                },
                "fehlend": _liste(element_fehlt, anzeige_element),
                "extra": _liste(element_extra, anzeige_element),
            },
            "kanten": {
                "matched": kanten_matched,
                "quote": kanten_quote,
                "fehlend_gesamt": sum(kanten_fehlt.values()),
                "extra_gesamt": sum(kanten_extra.values()),
                "fehlend": _liste(kanten_fehlt, anzeige_kante),
                "extra": _liste(kanten_extra, anzeige_kante),
            },
            "pakete": {
                "matched": pakete_matched,
                "quote": pakete_quote,
                "fehlend_gesamt": sum(pakete_fehlt.values()),
                "extra_gesamt": sum(pakete_extra.values()),
                "fehlend": _liste(pakete_fehlt, lambda pfad: pfad),
                "extra": _liste(pakete_extra, lambda pfad: pfad),
            },
            "tags": {
                "matched": tag_identisch,
                "geprueft": tag_geprueft,
                "quote": tags_quote,
            },
        },
        "top_fehlend": {
            "elemente": _liste(element_fehlt, anzeige_element, TOP),
            "kanten": _liste(kanten_fehlt, anzeige_kante, TOP),
        },
    }


# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------


def bericht(original_pfad: str | Path, neu_pfad: str | Path) -> dict[str, Any]:
    """Liest beide Modelle und liefert den Bericht als Dict."""
    original = lade_modell(original_pfad)
    neu = lade_modell(neu_pfad)
    vergleich = vergleiche(original, neu)
    return {
        "format_version": FORMAT_VERSION,
        "original": {
            "datei": original.datei,
            "sha256": original.sha256,
            "kennzahlen": original.kennzahlen,
        },
        "neu": {
            "datei": neu.datei,
            "sha256": neu.sha256,
            "kennzahlen": neu.kennzahlen,
        },
        "treffer": vergleich["treffer"],
        "gesamtquote": vergleich["gesamtquote"],
        "top_fehlend": vergleich["top_fehlend"],
    }


def render_json(bericht_: Mapping[str, Any]) -> str:
    """Serialisiert den Bericht deterministisch (sortierte Schluessel, UTF-8)."""
    return json.dumps(bericht_, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


_KENNZAHLEN_SPALTEN = (
    ("elemente", "Elemente"),
    ("elemente_gesamt", "t_object gesamt"),
    ("kanten", "Kanten"),
    ("pakete", "Pakete"),
    ("tags", "Tags"),
    ("sichten", "Sichten"),
    ("sicht_elemente", "Sicht-Elemente"),
    ("sicht_kanten", "Sicht-Kanten"),
    ("attribute", "Attribute"),
)


def render_markdown(bericht_: Mapping[str, Any]) -> str:
    """Erzeugt einen kurzen, deterministischen Markdown-Bericht."""
    original = bericht_["original"]
    neu = bericht_["neu"]
    treffer = bericht_["treffer"]
    zeilen: list[str] = []
    zeilen.append("# Roundtrip-Treue")
    zeilen.append("")
    zeilen.append(f"Original: `{original['datei']}` (sha256 `{original['sha256']}`)")
    zeilen.append("")
    zeilen.append(f"Rueckbau: `{neu['datei']}` (sha256 `{neu['sha256']}`)")
    zeilen.append("")
    zeilen.append(f"**Gesamtquote: {bericht_['gesamtquote']:.2f} %**")
    zeilen.append("")
    zeilen.append("## Kennzahlen (Rohzahlen)")
    zeilen.append("")
    zeilen.append("| Dimension | Original | Rueckbau |")
    zeilen.append("| --- | ---: | ---: |")
    for schluessel, beschriftung in _KENNZAHLEN_SPALTEN:
        links = original["kennzahlen"].get(schluessel, 0)
        rechts = neu["kennzahlen"].get(schluessel, 0)
        zeilen.append(f"| {beschriftung} | {links} | {rechts} |")
    zeilen.append("")
    zeilen.append("## Treffer je Dimension")
    zeilen.append("")
    zeilen.append("| Dimension | Gewicht | matched | fehlend | extra | Quote |")
    zeilen.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for schluessel, beschriftung in (
        ("elemente", "Elemente"),
        ("kanten", "Kanten"),
        ("pakete", "Pakete"),
    ):
        werte = treffer[schluessel]
        zeilen.append(
            f"| {beschriftung} | {GEWICHTE[schluessel]} % | {werte['matched']} |"
            f" {werte.get('fehlend_gesamt', 0)} | {werte.get('extra_gesamt', 0)} |"
            f" {werte['quote']:.2f} % |"
        )
    tags = treffer["tags"]
    zeilen.append(
        f"| Tags (Jaccard) | {GEWICHTE['tags']} % | {tags['matched']} von {tags['geprueft']} |"
        f" 0 | 0 | {tags['quote']:.2f} % |"
    )
    zeilen.append("")
    zeilen.append("## Die 20 wichtigsten Fehlstellen")
    zeilen.append("")
    zeilen.append("### Elemente")
    zeilen.append("")
    if bericht_["top_fehlend"]["elemente"]:
        for index, eintrag in enumerate(bericht_["top_fehlend"]["elemente"], start=1):
            zeilen.append(f"{index}. `{eintrag}`")
    else:
        zeilen.append("keine -- jedes Original-Element wurde wiedergefunden.")
    zeilen.append("")
    zeilen.append("### Kanten")
    zeilen.append("")
    if bericht_["top_fehlend"]["kanten"]:
        for index, eintrag in enumerate(bericht_["top_fehlend"]["kanten"], start=1):
            zeilen.append(f"{index}. `{eintrag}`")
    else:
        zeilen.append("keine -- jede Original-Kante wurde wiedergefunden.")
    zeilen.append("")
    zeilen.append("## Hinweise")
    zeilen.append("")
    zeilen.append(
        "- Elemente zaehlen ohne Paketspiegel (`t_object.Object_Type = 'Package'`);"
        " die Rohzahl aller `t_object`-Zeilen steht als `elemente_gesamt` daneben."
    )
    zeilen.append(
        "- Tag-Werte, die in der Quelle NULL sind, zaehlen als leer (`\"\"`);"
        " ein Wert wird nur dann aus `t_xref` nachgeladen, wenn dort ein"
        " gleichnamiger `@PROP`-Block steht."
    )
    zeilen.append(
        "- Sichten und Attribute sind Rohzahlen und gehen nicht in die Quote ein"
        " (der Rueckbau erzeugt sie bewusst nicht)."
    )
    zeilen.append(
        "- Fehlende Elemente zaehlen als 0, nicht als Teiltreffer;"
        " Mehrfachvorkommen werden als Multimenge verglichen."
    )
    zeilen.append("")
    return "\n".join(zeilen)


def _schreibe(pfad: str | Path, inhalt: str) -> None:
    ziel = Path(pfad)
    if ziel.parent and not ziel.parent.exists():
        ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(inhalt, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI-Einstieg; Exit 0 bei Bericht, 2 bei Dateiproblemen."""
    parser = argparse.ArgumentParser(
        prog="roundtrip_metrics.py",
        description="Vergleicht Original-.qea und Rueckbau-.qea und berechnet die Treuequote.",
    )
    parser.add_argument("original", metavar="ORIGINAL", type=Path, help="Original-.qea")
    parser.add_argument("neu", metavar="NEU", type=Path, help="Rueckbau-.qea")
    parser.add_argument(
        "--json", metavar="DATEI", type=Path, default=None, help="Bericht als JSON schreiben"
    )
    parser.add_argument(
        "--md", metavar="DATEI", type=Path, default=None, help="Bericht als Markdown schreiben"
    )
    args = parser.parse_args(argv)

    try:
        ergebnis = bericht(args.original, args.neu)
        if args.json is not None:
            _schreibe(args.json, render_json(ergebnis))
        if args.md is not None:
            _schreibe(args.md, render_markdown(ergebnis))
    except MetrikFehler as fehler:
        print(f"roundtrip_metrics: {fehler}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as fehler:
        print(f"roundtrip_metrics: Datei nicht lesbar/schreibbar: {fehler}", file=sys.stderr)
        return 2

    treffer = ergebnis["treffer"]
    print(
        f"Roundtrip-Treue: {ergebnis['gesamtquote']:.2f} %"
        f" (Elemente {treffer['elemente']['quote']:.2f},"
        f" Kanten {treffer['kanten']['quote']:.2f},"
        f" Pakete {treffer['pakete']['quote']:.2f},"
        f" Tags {treffer['tags']['quote']:.2f})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
