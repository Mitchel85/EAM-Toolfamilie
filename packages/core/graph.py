"""graph.py -- ArchiMate-Modelle als abfragbarer Graph (SQLite, ohne Neo4j).

Warum ein eigener Graph
-----------------------
Ein Modell ist ein Netz, kein Baum: dieselbe Faehigkeit haengt an Prozessen,
diese an Anwendungen, diese an Technik. Wer das mit SQL auf dem IR beantworten
will, schreibt fuer jede Frage einen Join ueber JSON-Listen. Der Graph
materialisiert das Netz einmal -- danach sind es zwei Tabellen und eine
rekursive Abfrage.

Der Graph ist eine **Momentaufnahme des Modells**, kein zweiter Writer:

- Er bildet das Modell ab, **wie es ist**. Ungueltige Kanten werden gemeldet,
  nicht repariert. Was der Writer beim Export tut (invertieren, umhaengen,
  verwerfen), ist eine bewusste Entscheidung am Ausgang -- hier waere es ein
  verfaelschtes Bild der Vorlage.
- Er ist **vollstaendiger als der Export**: Jedes fachliche Element und jedes
  Paket ist ein Knoten. Der Writer laesst Elemente ohne Abbildungsregel weg
  (und zaehlt sie); der Graph behaelt sie mit leerem ``archimate_typ``, damit
  keine Luecke unsichtbar wird.

Knoten und Kanten
-----------------
- **Knoten** (``knoten``): Elemente (``art='element'``) und Pakete
  (``art='paket'``). Jeder Knoten traegt ``kennung`` (Identitaet), ``typ``
  (Typ im Quellmodell, etwa die EA-Metaklasse), ``archimate_typ`` (ArchiMate
  3.2, Grundlage der Matrixpruefung) und ``stereotyp``.
- **Kanten** (``kanten``): die Beziehungen des Modells mit ``typ``
  (ArchiMate-Beziehungstyp), ``stereotyp``, ``kennung`` und den Endpunkten
  ``quelle``/``ziel``. Die Rohreferenzen ``quelle_ref``/``ziel_ref`` bleiben
  erhalten, auch wenn ein Endpunkt nicht aufloesbar ist.
- **Eigenschaften** (``eigenschaften``): die Tagged Values je Knoten.
- **Befunde** (``befunde``): je Regel ein Datensatz, mit Schwere und Text.

Identitaet (Kennung)
--------------------
Die Kennung ist die Identitaet aus dem Austauschformat (``identifier``), sonst
die Ableitung aus der GUID (``archimate_writer.kennung``). Kanten im
.qea-Format tragen keine GUID; ihre Kennung ist ein stabiler Hash aus
``quelle>ziel>typ`` mit laufender Nummer bei echten Dubletten. Zwei Laeufe auf
derselben Datei liefern dieselben Kennungen und dieselben Zeilen -- die
SQLite-Datei selbst ist (wie bei ``qea_writer``) nicht byte-identisch.

Pruefungen (welche Kante ist ungueltig)
--------------------------------------
Geprueft wird gegen die **ArchiMate-3.2-Beziehungsmatrix** (``archimate/
relationships.xml``, dieselbe Quelle wie der Writer) und gegen die Struktur
des Modells. Die Regeln stehen als Tabelle ``REGELN`` im Modul:

====  =========================  ========  ==================================
Code  Regel                      Schwere   Bedeutung
====  =========================  ========  ==================================
K01   endpunkt_fehlt             Fehler    Quelle oder Ziel ist kein Knoten
K02   selbstkante                Fehler    Quelle und Ziel sind dasselbe
K03   beziehungstyp_unbekannt    Fehler    kein ArchiMate-Beziehungstyp
K04   matrix_verstoss            Fehler    Typpaar laut Matrix nicht zulaessig
K05   richtung_verkehrt          Warnung   nur die Gegenrichtung ist zulaessig
K06   duplikat                   Warnung   dieselbe Kante steht mehrfach
K07   nicht_pruefbar             Warnung   Endpunkt ohne ArchiMate-Typ
K08   mehrdeutiger_endpunkt      Warnung   gleichnamige Elemente, erstes gewaehlt
K09   verdichtung                Hinweis   zwei Modellkanten, eine ArchiMate-Kante
K10   selbstkante_traeger        Hinweis   beide Enden auf demselben Traeger
====  =========================  ========  ==================================

**Ports, Parts und Pins sind keine ArchiMate-Elemente.** Wie der Writer zieht
der Lader ihre Kanten auf das Traegerelement. Zwei Kanten zwischen Ports
desselben Traegers werden dadurch zur Selbstkante oder zur doppelten Kante --
das ist kein Modellfehler, sondern der Preis der Abbildung, und steht als
``K09``/``K10`` (Hinweis) im Graphen. ``K02``/``K06`` melden nur, was schon im
Modell doppelt ist.

Nicht Teil des Graphen: die MDG-/ADMBw-Regeln. Die prueft ``validator.py``
gegen ein Regelwerk; beide arbeiten auf demselben IR und schliessen sich nicht
aus.

Oeffentliche API::

    from graph import lade, oeffne, elemente_an_faehigkeit, ungueltige_kanten

    bericht = lade("modell.qea", "modell.graph.sqlite")
    con = oeffne("modell.graph.sqlite")
    start, zeilen = elemente_an_faehigkeit(con, "Fuehrungsfaehigkeit", tiefe=1)
    fehler = ungueltige_kanten(con)              # nur Fehler
    alle = befunde(con, schwere="warnung")       # oder alle Befunde

Kommandozeile::

    python3 graph.py laden --in modell.qea --db modell.graph.sqlite
    python3 graph.py faehigkeit --db modell.graph.sqlite --name "Fuehrungsfaehigkeit"
    python3 graph.py ungueltig --db modell.graph.sqlite --regel K04
    python3 graph.py befunde --db modell.graph.sqlite --schwere hinweis
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import archimate_writer as aw

#: Format der Graphdatenbank. Steht in ``meta`` und wird beim Oeffnen geprueft.
GRAPH_FORMAT = 1

#: IR-Version, die gelesen wird (wie ``qea_writer``/``validator``).
IR_VERSION = 1

FEHLER = "fehler"
WARNUNG = "warnung"
HINWEIS = "hinweis"

#: Regelkatalog: Code -> (Schwere, Titel, Begruendung).
REGELN: Mapping[str, tuple[str, str, str]] = {
    "K01": (FEHLER, "endpunkt_fehlt", "Quelle oder Ziel verweist auf keinen Knoten des Modells."),
    "K02": (FEHLER, "selbstkante", "Eine Beziehung eines Elements auf sich selbst ist keine Aussage."),
    "K03": (FEHLER, "beziehungstyp_unbekannt", "Ohne ArchiMate-Typ ist die Kante nicht deutbar."),
    "K04": (FEHLER, "matrix_verstoss", "Das Typpaar laesst diese Beziehung laut ArchiMate 3.2 nicht zu."),
    "K05": (WARNUNG, "richtung_verkehrt", "Nur die Gegenrichtung ist zulaessig; der Writer invertiert beim Export."),
    "K06": (WARNUNG, "duplikat", "Dieselbe Beziehung steht mehrfach im Modell."),
    "K07": (WARNUNG, "nicht_pruefbar", "Ein Endpunkt hat keinen ArchiMate-Typ -- die Matrix ist nicht anwendbar."),
    "K08": (WARNUNG, "mehrdeutiger_endpunkt", "Gleichnamige Elemente im selben Paket; die erste Position wurde gewaehlt."),
    "K09": (HINWEIS, "verdichtung", "Zwei Modellkanten fallen nach der Traeger-Zusammenfassung auf eine ArchiMate-Kante."),
    "K10": (HINWEIS, "selbstkante_traeger", "Beide Enden liegen nach der Traeger-Zusammenfassung auf demselben Element."),
}

#: Elementtypen ohne fachliche Bedeutung (Darstellung) -- wie im Writer.
DARSTELLUNG = aw.SKIP_DISPLAY_TYPES

#: Prozessmechanik ohne ArchiMate-Konzept -- wie im Writer.
FACHMECHANIK = aw.SKIP_FACH_TYPES


class GraphError(ValueError):
    """Der Graph kann so nicht gebaut oder gelesen werden -- Abbruch statt Teil-Erfolg."""


class Mehrdeutig(GraphError):
    """Eine Suche trifft mehrere Knoten; die Auswahl muss der Aufrufer treffen."""

    def __init__(self, text: str, kandidaten: Sequence[Mapping[str, Any]]) -> None:
        self.kandidaten = tuple(dict(k) for k in kandidaten)
        zeilen = "\n".join(
            f"  {k['kennung']}  {k['name']}  ({k['archimate_typ'] or k['typ']}, {k['paket']})"
            for k in self.kandidaten
        )
        super().__init__(f"'{text}' ist mehrdeutig -- {len(self.kandidaten)} Treffer:\n{zeilen}")


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE meta (
    schluessel TEXT PRIMARY KEY,
    wert       TEXT NOT NULL
);

CREATE TABLE knoten (
    kennung       TEXT PRIMARY KEY,
    art           TEXT NOT NULL CHECK (art IN ('element', 'paket')),
    name          TEXT NOT NULL,
    typ           TEXT NOT NULL,
    archimate_typ TEXT NOT NULL,
    stereotyp     TEXT NOT NULL,
    paket         TEXT NOT NULL,
    dokumentation TEXT NOT NULL,
    status        TEXT NOT NULL
);
CREATE INDEX ix_knoten_name ON knoten (name);
CREATE INDEX ix_knoten_archimate_typ ON knoten (archimate_typ);
CREATE INDEX ix_knoten_paket ON knoten (paket);

CREATE TABLE eigenschaften (
    kennung    TEXT NOT NULL REFERENCES knoten (kennung) ON DELETE CASCADE,
    schluessel TEXT NOT NULL,
    wert       TEXT NOT NULL,
    PRIMARY KEY (kennung, schluessel)
);

CREATE TABLE kanten (
    kennung       TEXT PRIMARY KEY,
    position      INTEGER NOT NULL UNIQUE,
    typ           TEXT NOT NULL,
    quell_typ     TEXT NOT NULL,
    stereotyp     TEXT NOT NULL,
    quelle        TEXT REFERENCES knoten (kennung),
    ziel          TEXT REFERENCES knoten (kennung),
    quelle_ref    TEXT NOT NULL,
    ziel_ref      TEXT NOT NULL,
    name          TEXT NOT NULL,
    dokumentation TEXT NOT NULL,
    gueltig       INTEGER NOT NULL CHECK (gueltig IN (0, 1))
);
CREATE INDEX ix_kanten_quelle ON kanten (quelle);
CREATE INDEX ix_kanten_ziel ON kanten (ziel);
CREATE INDEX ix_kanten_typ ON kanten (typ);

CREATE TABLE befunde (
    id        INTEGER PRIMARY KEY,
    kante     TEXT NOT NULL REFERENCES kanten (kennung) ON DELETE CASCADE,
    regel     TEXT NOT NULL,
    schwere   TEXT NOT NULL,
    nachricht TEXT NOT NULL
);
CREATE INDEX ix_befunde_regel ON befunde (regel);

-- Lesbare Sicht: jede Kante mit beiden Enden (auch unaufgeloeste).
CREATE VIEW v_kanten AS
SELECT k.position,
       k.kennung,
       k.typ           AS beziehung,
       k.stereotyp,
       k.quelle,
       q.name          AS quell_name,
       q.archimate_typ AS quell_typ,
       k.quelle_ref,
       k.ziel,
       z.name          AS ziel_name,
       z.archimate_typ  AS ziel_typ,
       k.ziel_ref,
       k.gueltig
FROM kanten k
LEFT JOIN knoten q ON q.kennung = k.quelle
LEFT JOIN knoten z ON z.kennung = k.ziel;

-- Jede Kante aus Sicht beider Enden: Grundlage der Nachbarschaftsabfragen.
CREATE VIEW v_nachbarschaft AS
SELECT quelle AS knoten, ziel AS nachbar, kennung AS kante, typ AS beziehung, 'aus' AS richtung
FROM kanten WHERE quelle IS NOT NULL AND ziel IS NOT NULL
UNION ALL
SELECT ziel AS knoten, quelle AS nachbar, kennung AS kante, typ AS beziehung, 'ein' AS richtung
FROM kanten WHERE quelle IS NOT NULL AND ziel IS NOT NULL;

-- Alle Befunde, mit beiden Enden der betroffenen Kante.
CREATE VIEW v_befunde AS
SELECT b.regel,
       b.schwere,
       b.nachricht,
       k.position,
       k.kennung        AS kante,
       k.typ            AS beziehung,
       k.stereotyp,
       k.quelle,
       q.name           AS quell_name,
       q.archimate_typ  AS quell_typ,
       k.quelle_ref,
       k.ziel,
       z.name           AS ziel_name,
       z.archimate_typ  AS ziel_typ,
       k.ziel_ref
FROM befunde b
JOIN kanten k ON k.kennung = b.kante
LEFT JOIN knoten q ON q.kennung = k.quelle
LEFT JOIN knoten z ON z.kennung = k.ziel;

-- Die Pflichtabfrage im engeren Sinn: Kanten mit einem Fehler.
CREATE VIEW v_ungueltige_kanten AS
SELECT * FROM v_befunde WHERE schwere = 'fehler';
"""


# --------------------------------------------------------------------------
# Hilfen: IR lesen
# --------------------------------------------------------------------------
def _typname(value: Any) -> str:
    return type(value).__name__


def _text(value: Any, what: str, *, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise GraphError(f"{what}: Zeichenkette erwartet, gefunden None")
        return default
    if not isinstance(value, str):
        raise GraphError(f"{what}: Zeichenkette erwartet, gefunden {_typname(value)}")
    return value


def _pfad(value: Any, what: str) -> str:
    """Logischer Paketpfad: '/' als Trenner (wie IR-Spezifikation)."""
    pfad = _text(value, what)
    if not pfad.strip():
        raise GraphError(f"{what}: darf nicht leer sein")
    if "\\" in pfad:
        raise GraphError(f"{what}: Backslash in {pfad!r} -- Trenner ist '/'")
    if "::" in pfad:
        raise GraphError(f"{what}: '::' ist fuer Element-Referenzen reserviert ({pfad!r})")
    if pfad.startswith("/") or pfad.endswith("/") or "//" in pfad:
        raise GraphError(f"{what}: ungueltiger Pfad {pfad!r}")
    for teil in pfad.split("/"):
        if teil in ("", ".", ".."):
            raise GraphError(f"{what}: ungueltiges Pfadsegment {teil!r} in {pfad!r}")
    return pfad


def _tag_paare(value: Any, what: str) -> tuple[tuple[str, str], ...]:
    """Tagged Values kanonisch als (Name, Wert)-Tupel."""
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise GraphError(f"{what}: Objekt erwartet, gefunden {_typname(value)}")
    zeilen: list[tuple[str, str]] = []
    for schluessel, wert in value.items():
        name = _text(schluessel, f"{what}.<Schluessel>")
        if not name:
            raise GraphError(f"{what}: leerer Schluessel")
        if isinstance(wert, bool):
            text = "True" if wert else "False"
        elif isinstance(wert, (int, float)):
            text = str(wert)
        elif wert is None:
            raise GraphError(f"{what}[{name!r}]: Wert ist null")
        else:
            text = _text(wert, f"{what}[{name!r}]")
        zeilen.append((name, text))
    return tuple(sorted(zeilen))


def _sequenz(value: Any, what: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GraphError(f"{what}: Liste erwartet, gefunden {_typname(value)}")
    return value


# --------------------------------------------------------------------------
# Hilfen: Abbildung auf ArchiMate 3.2
# --------------------------------------------------------------------------
def archimate_typ(stereotype: str, ea_type: str) -> str:
    """ArchiMate-3.2-Typ eines Elements -- dieselbe Kette wie ``archimate_writer``.

    1. ``ELEMENT_MAP`` ueber den ADMBw-/NAF-Stereotyp,
    2. ``EA_TYPE_MAP`` ueber die EA-Metaklasse (Zustand/Ereignis -> Event),
    3. ``FX`` als dokumentierter Rueckfall,
    4. Identitaet, wenn die Metaklasse selbst ein ArchiMate-Typ ist (Import aus
       dem Austauschformat).

    Leere Zeichenkette = keine Abbildung. Der Aufrufer entscheidet, ob das ein
    Befund ist; hier wird nichts geraten.
    """
    ziel = aw.ELEMENT_MAP.get(stereotype)
    if ziel:
        return ziel
    ziel = aw.EA_TYPE_MAP.get(ea_type.lower())
    if ziel:
        return ziel
    ziel = aw.FX.get(ea_type)
    if ziel:
        return ziel
    if ea_type in aw.ARCHIMATE_ELEMENT_TYPES:
        return ea_type
    return ""


def beziehungstyp(stereotype: str, ea_type: str) -> str:
    """ArchiMate-Beziehungstyp einer Kante -- dieselbe Kette wie der Writer."""
    return aw.RELATIONSHIP_MAP.get(stereotype) or aw.TYPE_MAP.get(ea_type) or ""


def _matrix() -> dict[tuple[str, str], set[str]]:
    """Beziehungsmatrix einmal je Prozess laden (672 Eintraege, ~2 ms)."""
    global _MATRIX
    if _MATRIX is None:
        _MATRIX = aw.load_matrix()
    return _MATRIX


_MATRIX: dict[tuple[str, str], set[str]] | None = None


def _erlaubt(quelle: str, rel: str, ziel: str) -> bool:
    """Typpaar-Pruefung wie ``archimate_writer._erlaubt``.

    ``Association`` ist laut Matrix fuer 3841 von 3844 Typparen erlaubt (Ausnahme
    nur ``Junction``/``Relationship``); der Kurzschluss ist damit matrix-konform
    und haelt den Graphen deckungsgleich mit dem Export.
    """
    if rel == "Association":
        return True
    return ziel in _matrix().get((quelle, rel), set())


def _vorschlag(quelle: str, rel: str, ziel: str) -> str:
    """Erste semantisch naechste zulaessige Beziehung -- wie im Writer."""
    for kandidat in aw.FALLBACK_PRAEFERENZ.get(rel, ()) + aw.FALLBACKS:
        if _erlaubt(quelle, kandidat, ziel):
            return kandidat
    return ""


# --------------------------------------------------------------------------
# Hilfen: Aufloesung der IR-Referenzen
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _Ziel:
    art: str  # "element" | "paket" | "unaufgeloest" | "mehrdeutig"
    index: int = -1
    pfad: str = ""
    indices: tuple[int, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class _Seite:
    """Ein Kantenende, aufgeloest auf einen Knoten -- oder mit Grund dagegen."""

    kennung: str | None
    element: Mapping[str, Any] | None
    fehler: str = ""
    mehrdeutig: str = ""
    umgehaengt: str = ""  # Name des Traegers, auf den das Ende umgehaengt wurde

    def name(self, ersatz: str = "?") -> str:
        if self.element is not None:
            return str(self.element["name"]) or self.kennung or ersatz
        return self.kennung or ersatz


class _Index:
    """Elemente, Pakete und die Aufloesung von ``paket::name[#N]``.

    Die Vorkommensnummer ``#N`` folgt derselben kanonischen Reihenfolge wie
    ``qea_writer._element_index``: Inhalt zuerst, GUID als Tiebreak. Nur so
    adressiert ``paket::name#2`` im Graphen dasselbe Element wie im Export.
    """

    def __init__(self, elemente: Sequence[Mapping[str, Any]], pakete: Sequence[str]) -> None:
        self.elemente = elemente
        self.pakete = set(pakete)
        gruppen: dict[tuple[str, str], list[int]] = {}
        for index, element in enumerate(elemente):
            schluessel = (element["paket"], element["name"])
            gruppen.setdefault(schluessel, []).append(index)
        for gruppe in gruppen.values():
            gruppe.sort(key=lambda i: self._sortierschluessel(elemente[i]))
        self.gruppen = gruppen
        # Referenz je Element -- dieselbe Schreibweise wie qea_reader:
        # 'paket::name', bei Namensgruppen 'paket::name#N', ohne Namen 'paket::#N'.
        refs: dict[int, str] = {}
        for (paket, name), gruppe in gruppen.items():
            for position, index in enumerate(gruppe, start=1):
                if not name:
                    refs[index] = f"{paket}::#{position}"
                elif len(gruppe) == 1:
                    refs[index] = f"{paket}::{name}"
                else:
                    refs[index] = f"{paket}::{name}#{position}"
        self.refs = refs

    @staticmethod
    def _sortierschluessel(element: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            element["ea_type"],
            element["notes"],
            element["alias"],
            element["status"],
            element["tags"],
            element["origin"],
            element["guid"].upper(),
        )

    def loese(self, ref: str) -> _Ziel:
        if "::" in ref:
            paket, rest = ref.rsplit("::", 1)
            if not rest:
                return _Ziel(
                    "unaufgeloest",
                    detail=f"'{ref}' nennt keinen Elementnamen (unbenannte Elemente mit '<paket>::#1' adressieren)",
                )
            gruppe = self.gruppen.get((paket, rest))
            nummer: int | None = None
            if gruppe is None:
                name, trenner, zahl = rest.rpartition("#")
                if trenner and zahl.isdigit():
                    gruppe = self.gruppen.get((paket, name))
                    if gruppe is not None:
                        nummer = int(zahl)
            if gruppe is None:
                return _Ziel("unaufgeloest", detail=f"'{ref}' verweist auf kein Element des Modells")
            if nummer is not None:
                if not 1 <= nummer <= len(gruppe):
                    return _Ziel(
                        "unaufgeloest",
                        detail=f"'{ref}' verlangt Vorkommen {nummer}, vorhanden sind {len(gruppe)}",
                    )
                return _Ziel("element", index=gruppe[nummer - 1])
            if len(gruppe) > 1:
                return _Ziel(
                    "mehrdeutig",
                    indices=tuple(gruppe),
                    detail=(
                        f"'{ref}' ist mehrdeutig ({len(gruppe)} gleichnamige Elemente); "
                        f"eindeutig mit '{paket}::"
                        + (rest if rest else "")
                        + "#N'"
                    ),
                )
            return _Ziel("element", index=gruppe[0])
        if ref in self.pakete:
            return _Ziel("paket", pfad=ref)
        return _Ziel("unaufgeloest", detail=f"'{ref}' verweist auf kein Paket des Modells")


@dataclass
class Ladebericht:
    """Was beim Laden passiert ist -- jede Naeherung ist sichtbar."""

    quelle: str = ""
    format: str = ""
    sha256: str = ""
    knoten_elemente: int = 0
    knoten_pakete: int = 0
    kanten: int = 0
    kanten_gueltig: int = 0
    kanten_ungueltig: int = 0
    befunde: int = 0
    zusammengefasst: int = 0
    uebersprungen: dict[str, int] = field(default_factory=dict)
    befunde_je_regel: dict[str, int] = field(default_factory=dict)
    befunde_je_schwere: dict[str, int] = field(default_factory=dict)
    abbildung: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "quelle": self.quelle,
            "format": self.format,
            "sha256": self.sha256,
            "knoten": {"elemente": self.knoten_elemente, "pakete": self.knoten_pakete},
            "kanten": {
                "gesamt": self.kanten,
                "gueltig": self.kanten_gueltig,
                "ungueltig": self.kanten_ungueltig,
            },
            "befunde": self.befunde,
            "befunde_je_regel": dict(sorted(self.befunde_je_regel.items())),
            "befunde_je_schwere": dict(sorted(self.befunde_je_schwere.items())),
            "uebersprungen": dict(sorted(self.uebersprungen.items())),
            "zusammengefasst": self.zusammengefasst,
            "abbildung": dict(sorted(self.abbildung.items())),
        }

    def summary(self) -> str:
        zeilen = [
            f"Geladen: {self.quelle or '(IR)'} [{self.format or 'ir'}]"
            + (f" sha256 {self.sha256[:16]}..." if self.sha256 else ""),
            f"  Knoten:  {self.knoten_elemente} Elemente, {self.knoten_pakete} Pakete",
            f"  Kanten:  {self.kanten} ({self.kanten_gueltig} gueltig, {self.kanten_ungueltig} ungueltig)",
            f"  Befunde: {self.befunde}"
            + (
                " (" + ", ".join(f"{k} {v}" for k, v in sorted(self.befunde_je_regel.items())) + ")"
                if self.befunde_je_regel
                else ""
            ),
        ]
        if self.befunde_je_schwere:
            zeilen.append(
                "  Schwere: "
                + ", ".join(f"{k} {v}" for k, v in sorted(self.befunde_je_schwere.items()))
            )
        if self.uebersprungen:
            zeilen.append(
                "  Uebersprungen: "
                + ", ".join(f"{k} {v}" for k, v in sorted(self.uebersprungen.items()))
            )
        if self.zusammengefasst:
            zeilen.append(f"  Auf Traeger zusammengefasst: {self.zusammengefasst}")
        return "\n".join(zeilen)


# --------------------------------------------------------------------------
# IR -> Knoten, Kanten, Befunde
# --------------------------------------------------------------------------
def _lese_pakete(ir: Mapping[str, Any]) -> list[dict[str, Any]]:
    pakete: list[dict[str, Any]] = []
    gesehen: set[str] = set()
    for position, roh in enumerate(_sequenz(ir.get("packages"), "IR.packages")):
        what = f"IR.packages[{position}]"
        if not isinstance(roh, Mapping):
            raise GraphError(f"{what}: Objekt erwartet, gefunden {_typname(roh)}")
        pfad = _pfad(roh.get("path"), f"{what}.path")
        if pfad in gesehen:
            raise GraphError(f"{what}.path: Paket {pfad!r} ist mehrfach deklariert")
        gesehen.add(pfad)
        pakete.append(
            {
                "pfad": pfad,
                "stereotype": _text(roh.get("stereotype"), f"{what}.stereotype", default=""),
                "notes": _text(roh.get("notes"), f"{what}.notes", default=""),
                "tags": _tag_paare(roh.get("tags"), f"{what}.tags"),
                "guid": _text(roh.get("guid"), f"{what}.guid", default=""),
                "identifier": _text(roh.get("identifier"), f"{what}.identifier", default=""),
            }
        )
    if not pakete:
        raise GraphError("IR.packages: das IR enthaelt kein Paket -- Abbruch statt leerem Erfolg")
    return pakete


def _lese_elemente(ir: Mapping[str, Any], paketpfade: set[str]) -> list[dict[str, Any]]:
    elemente: list[dict[str, Any]] = []
    for position, roh in enumerate(_sequenz(ir.get("elements"), "IR.elements")):
        what = f"IR.elements[{position}]"
        if not isinstance(roh, Mapping):
            raise GraphError(f"{what}: Objekt erwartet, gefunden {_typname(roh)}")
        paket = _pfad(roh.get("package"), f"{what}.package")
        if paket not in paketpfade:
            raise GraphError(f"{what}.package: Paket {paket!r} ist nicht deklariert")
        name = _text(roh.get("name"), f"{what}.name")
        if "::" in name:
            raise GraphError(f"{what}.name: '::' ist im Elementnamen reserviert ({name!r})")
        ea_type = _text(roh.get("ea_type"), f"{what}.ea_type", default="Class")
        elemente.append(
            {
                "index": position,
                "paket": paket,
                "name": name,
                "stereotype": _text(roh.get("stereotype"), f"{what}.stereotype", default=""),
                "ea_type": ea_type,
                "notes": _text(roh.get("notes"), f"{what}.notes", default=""),
                "alias": _text(roh.get("alias"), f"{what}.alias", default=""),
                "status": _text(roh.get("status"), f"{what}.status", default=""),
                "tags": _tag_paare(roh.get("tags"), f"{what}.tags"),
                "guid": _text(roh.get("guid"), f"{what}.guid", default=""),
                "identifier": _text(roh.get("identifier"), f"{what}.identifier", default=""),
                "origin": _text(roh.get("origin"), f"{what}.origin", default=""),
                "owner": _text(roh.get("owner"), f"{what}.owner", default=""),
            }
        )
    if not elemente:
        raise GraphError("IR.elements: das IR enthaelt kein Element -- Abbruch statt leerem Erfolg")
    return elemente


def _kennung(identifier: str, guid: str, ref: str) -> str:
    return identifier or aw.kennung(guid, ref)


def aufbau(ir: Mapping[str, Any]) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[tuple[str, str, str]],
    dict[str, str],
    Ladebericht,
]:
    """IR -> (knoten, kanten, befunde, eigenschaften, meta, bericht).

    Reine Funktion ohne Datenbank: dieselbe Eingabe liefert dieselben Zeilen.
    """
    if not isinstance(ir, Mapping):
        raise GraphError(f"IR: Objekt erwartet, gefunden {_typname(ir)}")
    version = ir.get("ir_version")
    if isinstance(version, bool) or version != IR_VERSION:
        raise GraphError(f"IR.ir_version: {IR_VERSION} erwartet, gefunden {version!r}")

    bericht = Ladebericht()
    pakete = _lese_pakete(ir)
    elemente = _lese_elemente(ir, {p["pfad"] for p in pakete})
    index = _Index(elemente, [p["pfad"] for p in pakete])

    knoten: list[dict[str, Any]] = []
    eigenschaften: list[tuple[str, str, str]] = []
    belegt: dict[str, str] = {}

    def _belege(kennung: str, was: str) -> None:
        if kennung in belegt:
            raise GraphError(
                f"Kennung {kennung!r} ist doppelt ({belegt[kennung]} und {was}) -- "
                "das IR ist nicht eindeutig"
            )
        belegt[kennung] = was

    # Pakete als Knoten: Container der Hierarchie, kein ArchiMate-Element.
    # Ein Paket mit abbildbarem Stereotyp traegt dessen ArchiMate-Typ (wie im
    # Export), sonst gilt es als Grouping.
    paket_kennung: dict[str, str] = {}
    for paket in pakete:
        ziel_typ = aw.ELEMENT_MAP.get(paket["stereotype"], "") if paket["stereotype"] else ""
        ziel_typ = ziel_typ or "Grouping"
        kennung = _kennung(paket["identifier"], paket["guid"], "paket:" + paket["pfad"])
        _belege(kennung, f"Paket {paket['pfad']!r}")
        paket_kennung[paket["pfad"]] = kennung
        eltern = paket["pfad"].rsplit("/", 1)[0] if "/" in paket["pfad"] else ""
        knoten.append(
            {
                "kennung": kennung,
                "art": "paket",
                "name": paket["pfad"].rsplit("/", 1)[-1],
                "typ": "Package",
                "archimate_typ": ziel_typ,
                "stereotyp": paket["stereotype"],
                "paket": eltern,
                "dokumentation": paket["notes"],
                "status": "",
            }
        )
        for schluessel, wert in paket["tags"]:
            eigenschaften.append((kennung, schluessel, wert))
    bericht.knoten_pakete = len(pakete)

    # Traeger-Aufloesung fuer Ports/Parts/Pins (Ketten bis zur Wurzel).
    roh_owner = {e["index"]: e["owner"] for e in elemente if e["owner"]}

    def _traeger(element: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Element, an dem die Kanten eines Detail-Elements haengen sollen."""
        gesehen: set[int] = set()
        aktuell: Mapping[str, Any] = element
        while aktuell["index"] in roh_owner and aktuell["index"] not in gesehen:
            gesehen.add(aktuell["index"])
            ziel = index.loese(roh_owner[aktuell["index"]])
            if ziel.art == "mehrdeutig":
                aktuell = elemente[ziel.indices[0]]
            elif ziel.art == "element":
                aktuell = elemente[ziel.index]
            else:
                return None
        return None if aktuell is element else aktuell

    # Knoten bauen; Detail-Elemente werden zusammengefasst, Darstellung entfaellt.
    knoten_index: dict[int, dict[str, Any]] = {}
    for element in elemente:
        ea_type = element["ea_type"].strip()
        klein = ea_type.lower()
        if klein in DARSTELLUNG:
            bericht.uebersprungen["darstellung"] = bericht.uebersprungen.get("darstellung", 0) + 1
            continue
        if klein in FACHMECHANIK:
            bericht.uebersprungen["fachmechanik"] = bericht.uebersprungen.get("fachmechanik", 0) + 1
            continue
        if element["index"] in roh_owner:
            bericht.zusammengefasst += 1
            continue
        if klein == "package" and not element["stereotype"]:
            bericht.uebersprungen["paketzeile"] = bericht.uebersprungen.get("paketzeile", 0) + 1
            continue
        ziel_typ = archimate_typ(element["stereotype"], ea_type)
        kennung = _kennung(element["identifier"], element["guid"], index.refs[element["index"]])
        _belege(kennung, f"Element {element['paket']}::{element['name']!r}")
        knoten_index[element["index"]] = {
            "kennung": kennung,
            "art": "element",
            "name": element["name"],
            "typ": ea_type,
            "archimate_typ": ziel_typ,
            "stereotyp": element["stereotype"],
            "paket": element["paket"],
            "dokumentation": element["notes"],
            "status": element["status"],
        }
        knoten.append(knoten_index[element["index"]])
        for schluessel, wert in element["tags"]:
            eigenschaften.append((kennung, schluessel, wert))
        schluessel_typ = ziel_typ or "(ohne Abbildung)"
        bericht.abbildung[schluessel_typ] = bericht.abbildung.get(schluessel_typ, 0) + 1

    bericht.knoten_elemente = len(knoten_index)

    # ---- Kanten -----------------------------------------------------------
    kanten: list[dict[str, Any]] = []
    befunde: list[dict[str, Any]] = []
    gesehen_kennung: dict[str, int] = {}
    gesehen_roh: dict[tuple[str, str, str], int] = {}
    gesehen_aufgeloest: dict[tuple[str, str, str], int] = {}
    knoten_von = {k["kennung"]: k for k in knoten}

    def _seite(ref: str) -> _Seite:
        """Ein Kantenende aufloesen -- auf einen Knoten oder mit Begruendung."""
        ziel = index.loese(ref)
        if ziel.art == "paket":
            kennung = paket_kennung.get(ziel.pfad)
            if kennung is None:
                return _Seite(None, None, fehler=f"Paket {ziel.pfad!r} ist kein Knoten")
            return _Seite(kennung, None)
        if ziel.art == "element":
            element = elemente[ziel.index]
            traeger = _traeger(element)
            umgehaengt = ""
            if traeger is not None:
                umgehaengt = traeger["name"] or traeger["ea_type"]
                element = traeger
            eintrag = knoten_index.get(element["index"])
            if eintrag is None:
                return _Seite(
                    None,
                    element,
                    fehler=(
                        f"'{ref}' zeigt auf ein Element ohne Knoten "
                        f"(typ {element['ea_type']!r})"
                    ),
                )
            return _Seite(eintrag["kennung"], element, umgehaengt=umgehaengt)
        if ziel.art == "mehrdeutig":
            erster = elemente[ziel.indices[0]]
            traeger = _traeger(erster)
            umgehaengt = ""
            if traeger is not None:
                umgehaengt = traeger["name"] or traeger["ea_type"]
                erster = traeger
            eintrag = knoten_index.get(erster["index"])
            detail = ziel.detail + f"; verwendet wird '{erster['name'] or erster['ea_type']}'"
            return _Seite(
                eintrag["kennung"] if eintrag else None,
                erster,
                mehrdeutig=detail,
                umgehaengt=umgehaengt,
            )
        return _Seite(None, None, fehler=ziel.detail)

    for position, roh in enumerate(_sequenz(ir.get("connectors", []), "IR.connectors")):
        what = f"IR.connectors[{position}]"
        if not isinstance(roh, Mapping):
            raise GraphError(f"{what}: Objekt erwartet, gefunden {_typname(roh)}")
        quelle_ref = _text(roh.get("source"), f"{what}.source")
        ziel_ref = _text(roh.get("target"), f"{what}.target")
        stereotype = _text(roh.get("stereotype"), f"{what}.stereotype", default="")
        ea_type = _text(roh.get("ea_type"), f"{what}.ea_type", default="")
        typ = beziehungstyp(stereotype, ea_type)
        if not typ:
            # NoteLink ist reine Darstellung (der Writer zaehlt ihn getrennt).
            if ea_type and aw.TYPE_MAP.get(ea_type, "unbekannt") is None:
                bericht.uebersprungen["notelink"] = bericht.uebersprungen.get("notelink", 0) + 1
                continue
            typ = ea_type

        q_seite = _seite(quelle_ref) if quelle_ref else _Seite(None, None, fehler="Quelle fehlt")
        z_seite = _seite(ziel_ref) if ziel_ref else _Seite(None, None, fehler="Ziel fehlt")
        quelle, ziel = q_seite.kennung, z_seite.kennung

        eigenbefunde: list[tuple[str, str]] = []

        def _melde(regel: str, nachricht: str) -> None:
            eigenbefunde.append((regel, nachricht))

        if q_seite.fehler:
            _melde("K01", f"Quelle: {q_seite.fehler}")
        if z_seite.fehler:
            _melde("K01", f"Ziel: {z_seite.fehler}")
        if q_seite.mehrdeutig:
            _melde("K08", f"Quelle: {q_seite.mehrdeutig}")
        if z_seite.mehrdeutig:
            _melde("K08", f"Ziel: {z_seite.mehrdeutig}")
        if quelle is not None and ziel is not None and quelle == ziel:
            name = (knoten_von.get(quelle) or {}).get("name") or q_seite.name()
            if quelle_ref == ziel_ref:
                _melde("K02", f"Selbstkante: '{name}' ist Quelle und Ziel")
            else:
                _melde(
                    "K10",
                    f"Selbstkante in der ArchiMate-Sicht: '{quelle_ref}' und '{ziel_ref}' "
                    f"liegen beide auf dem Traeger '{q_seite.umgehaengt or z_seite.umgehaengt}'",
                )

        q_knoten = knoten_von.get(quelle) if quelle else None
        z_knoten = knoten_von.get(ziel) if ziel else None
        quell_typ = q_knoten["archimate_typ"] if q_knoten else ""
        ziel_typ = z_knoten["archimate_typ"] if z_knoten else ""

        if not typ:
            _melde("K03", f"Beziehungstyp fehlt (ea_type {ea_type!r}, Stereotyp {stereotype!r})")
        elif typ not in aw.ARCHIMATE_RELATIONSHIP_TYPES:
            _melde("K03", f"Beziehungstyp '{typ}' ist kein ArchiMate-3.2-Beziehungstyp")

        if typ in aw.ARCHIMATE_RELATIONSHIP_TYPES and q_knoten is not None and z_knoten is not None:
            if not quell_typ or not ziel_typ:
                seite = "Quelle" if not quell_typ else "Ziel"
                element = q_seite.element if not quell_typ else z_seite.element
                _melde(
                    "K07",
                    f"Nicht pruefbar: {seite} '{element['name'] if element else '?'}' hat keinen "
                    f"ArchiMate-Typ (typ {element['ea_type'] if element else '?'}, "
                    f"Stereotyp {(element['stereotype'] if element else '')!r})",
                )
            else:
                q_matrix = aw.MATRIX_TYPE.get(quell_typ, quell_typ)
                z_matrix = aw.MATRIX_TYPE.get(ziel_typ, ziel_typ)
                if not _erlaubt(q_matrix, typ, z_matrix):
                    if _erlaubt(z_matrix, typ, q_matrix):
                        _melde(
                            "K05",
                            f"Nur die Gegenrichtung ist zulaessig: '{ziel_typ}' --{typ}--> '{quell_typ}' "
                            "(der Writer invertiert die Kante beim Export)",
                        )
                    else:
                        besser = _vorschlag(q_matrix, typ, z_matrix)
                        _melde(
                            "K04",
                            f"'{quell_typ}' --{typ}--> '{ziel_typ}' ist laut ArchiMate-3.2-Matrix "
                            f"nicht zulaessig"
                            + (f"; zulaessig waere {besser}" if besser else "; kein Ersatz zulaessig"),
                        )

        roh_schluessel = (quelle_ref, ziel_ref, typ)
        aufgeloest = (quelle or "ref:" + quelle_ref, ziel or "ref:" + ziel_ref, typ)
        if roh_schluessel in gesehen_roh:
            _melde(
                "K06",
                f"Doppelte Kante: dieselbe Beziehung {typ or '?'} von "
                f"'{q_seite.name(quelle_ref)}' nach '{z_seite.name(ziel_ref)}' steht bereits an "
                f"Position {gesehen_roh[roh_schluessel]}",
            )
        elif aufgeloest in gesehen_aufgeloest:
            _melde(
                "K09",
                f"Verdichtung: '{quelle_ref}' --{typ or '?'}--> '{ziel_ref}' liegt nach der "
                f"Traeger-Zusammenfassung auf derselben Kante wie Position "
                f"{gesehen_aufgeloest[aufgeloest]}"
                + (
                    f" (Traeger '{q_seite.umgehaengt or z_seite.umgehaengt}')"
                    if q_seite.umgehaengt or z_seite.umgehaengt
                    else ""
                ),
            )
        gesehen_roh.setdefault(roh_schluessel, position)
        gesehen_aufgeloest.setdefault(aufgeloest, position)

        basis = _kennung(
            _text(roh.get("identifier"), f"{what}.identifier", default=""),
            _text(roh.get("guid"), f"{what}.guid", default=""),
            f"{quelle_ref}>{ziel_ref}>{typ}",
        )
        nummer = gesehen_kennung.get(basis, 0) + 1
        gesehen_kennung[basis] = nummer
        kennung = basis if nummer == 1 else f"{basis}-{nummer}"

        hat_fehler = any(REGELN[regel][0] == FEHLER for regel, _ in eigenbefunde)
        kanten.append(
            {
                "kennung": kennung,
                "position": position,
                "typ": typ,
                "quell_typ": ea_type,
                "stereotyp": stereotype,
                "quelle": quelle,
                "ziel": ziel,
                "quelle_ref": quelle_ref,
                "ziel_ref": ziel_ref,
                "name": _text(roh.get("name"), f"{what}.name", default=""),
                "dokumentation": _text(roh.get("notes"), f"{what}.notes", default=""),
                "gueltig": 0 if hat_fehler else 1,
            }
        )
        for regel, nachricht in eigenbefunde:
            befunde.append(
                {
                    "kante": kennung,
                    "regel": regel,
                    "schwere": REGELN[regel][0],
                    "nachricht": nachricht,
                }
            )

    bericht.kanten = len(kanten)
    bericht.kanten_ungueltig = sum(1 for kante in kanten if not kante["gueltig"])
    bericht.kanten_gueltig = bericht.kanten - bericht.kanten_ungueltig
    bericht.befunde = len(befunde)
    for befund in befunde:
        bericht.befunde_je_regel[befund["regel"]] = bericht.befunde_je_regel.get(befund["regel"], 0) + 1
        bericht.befunde_je_schwere[befund["schwere"]] = (
            bericht.befunde_je_schwere.get(befund["schwere"], 0) + 1
        )

    meta = {
        "format": str(GRAPH_FORMAT),
        "programm": "eam-ai graph",
        "modell": _modellname(ir),
    }
    return knoten, kanten, befunde, eigenschaften, meta, bericht


def _modellname(ir: Mapping[str, Any]) -> str:
    """Modellname aus ``meta.archimate`` (Rueckweg aus dem Austauschformat)."""
    meta = ir.get("meta")
    if isinstance(meta, Mapping):
        archimate = meta.get("archimate")
        if isinstance(archimate, Mapping):
            name = archimate.get("name")
            if isinstance(name, str):
                return name
    technology = ir.get("technology")
    if isinstance(technology, Mapping):
        name = technology.get("name")
        if isinstance(name, str):
            return name
    return ""


# --------------------------------------------------------------------------
# IR-Quellen
# --------------------------------------------------------------------------
def lies_ir(pfad: str | Path, *, strict: bool = False) -> tuple[Mapping[str, Any], str, Path]:
    """Liest .qea, ArchiMate-XML oder IR-JSON und nennt das Format."""
    quelle = Path(pfad)
    if not quelle.is_file():
        raise GraphError(f"{quelle}: Datei nicht gefunden")
    endung = quelle.suffix.lower()
    try:
        if endung == ".qea":
            from qea_reader import read_qea_ex

            ir, _ = read_qea_ex(quelle, strict=strict, with_refs=True, with_owners=True)
            return ir, "qea", quelle
        if endung in (".xml", ".archimate"):
            from archimate_reader import read_archimate_ex

            ir, _ = read_archimate_ex(quelle, strict=strict)
            return ir, "archimate", quelle
        if endung == ".json":
            roh = json.loads(quelle.read_text(encoding="utf-8"))
            return roh, "ir", quelle
    except GraphError:
        raise
    except Exception as exc:  # Reader-Fehler tragen ihre eigene Sprache
        raise GraphError(f"{quelle}: nicht lesbar ({exc})") from exc
    raise GraphError(f"{quelle}: unbekanntes Format {endung!r} -- erwartet .qea, .xml oder .json")


# --------------------------------------------------------------------------
# Schreiben und Oeffnen
# --------------------------------------------------------------------------
def _schreibe(
    ziel: Path,
    knoten: Sequence[Mapping[str, Any]],
    kanten: Sequence[Mapping[str, Any]],
    befunde: Sequence[Mapping[str, Any]],
    eigenschaften: Sequence[tuple[str, str, str]],
    meta: Mapping[str, str],
) -> None:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    temp = ziel.with_name(ziel.name + ".tmp")
    if temp.exists():
        temp.unlink()
    con = sqlite3.connect(temp)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = DELETE")  # keine -wal/-shm-Reste
        con.executescript(SCHEMA)
        con.execute("BEGIN")
        con.executemany(
            "INSERT INTO knoten (kennung, art, name, typ, archimate_typ, stereotyp, paket, dokumentation, status)"
            " VALUES (:kennung, :art, :name, :typ, :archimate_typ, :stereotyp, :paket, :dokumentation, :status)",
            knoten,
        )
        con.executemany(
            "INSERT INTO eigenschaften (kennung, schluessel, wert) VALUES (?, ?, ?)",
            eigenschaften,
        )
        con.executemany(
            "INSERT INTO kanten (kennung, position, typ, quell_typ, stereotyp, quelle, ziel, quelle_ref,"
            " ziel_ref, name, dokumentation, gueltig)"
            " VALUES (:kennung, :position, :typ, :quell_typ, :stereotyp, :quelle, :ziel, :quelle_ref,"
            " :ziel_ref, :name, :dokumentation, :gueltig)",
            kanten,
        )
        con.executemany(
            "INSERT INTO befunde (kante, regel, schwere, nachricht) VALUES (?, ?, ?, ?)",
            [(b["kante"], b["regel"], b["schwere"], b["nachricht"]) for b in befunde],
        )
        con.executemany(
            "INSERT INTO meta (schluessel, wert) VALUES (?, ?)",
            sorted(meta.items()),
        )
        con.commit()
    except Exception:
        con.close()
        temp.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(temp, ziel)


def lade_ir(
    ir: Mapping[str, Any],
    db: str | Path,
    *,
    quelle: str = "",
    format: str = "",
    sha256: str = "",
    ersetzen: bool = False,
) -> Ladebericht:
    """Schreibt ein IR in eine neue Graphdatenbank."""
    ziel = Path(db)
    if ziel.exists() and not ersetzen:
        raise GraphError(f"{ziel}: existiert bereits -- mit 'ersetzt=True' ueberschreiben")
    knoten, kanten, befunde, eigenschaften, meta, bericht = aufbau(ir)
    bericht.quelle = quelle
    bericht.format = format
    bericht.sha256 = sha256
    meta.update(
        {
            "quelle": quelle,
            "quelle_format": format,
            "quelle_sha256": sha256,
            "knoten": str(len(knoten)),
            "kanten": str(len(kanten)),
            "befunde": str(len(befunde)),
        }
    )
    _schreibe(ziel, knoten, kanten, befunde, eigenschaften, meta)
    return bericht


def lade(pfad: str | Path, db: str | Path, *, strict: bool = False, ersetzen: bool = False) -> Ladebericht:
    """Liest ein Modell (.qea, .xml, .json) und schreibt den Graphen.

    Der Quell-Hash wird ueber die Datei gebildet, nicht ueber das IR: damit ist
    nachvollziehbar, welche Datei den Graphen erzeugt hat.
    """
    ir, format, quelle = lies_ir(pfad, strict=strict)
    digest = hashlib.sha256(quelle.read_bytes()).hexdigest()
    return lade_ir(
        ir,
        db,
        quelle=quelle.name,
        format=format,
        sha256=digest,
        ersetzen=ersetzen,
    )


def _pruefe_format(con: sqlite3.Connection, pfad: Path) -> None:
    try:
        zeile = con.execute("SELECT wert FROM meta WHERE schluessel = 'format'").fetchone()
    except sqlite3.DatabaseError as exc:
        raise GraphError(f"{pfad}: keine Graphdatenbank ({exc})") from exc
    if zeile is None:
        raise GraphError(f"{pfad}: keine Graphdatenbank (meta.format fehlt)")
    if zeile[0] != str(GRAPH_FORMAT):
        raise GraphError(
            f"{pfad}: Graphformat {zeile[0]!r} -- dieses Programm liest Format {GRAPH_FORMAT}"
        )


def oeffne(db: str | Path) -> sqlite3.Connection:
    """Oeffnet eine Graphdatenbank schreibgeschuetzt."""
    pfad = Path(db)
    if not pfad.is_file():
        raise GraphError(f"{pfad}: Datei nicht gefunden")
    con = sqlite3.connect(f"{pfad.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        _pruefe_format(con, pfad)
    except Exception:
        con.close()
        raise
    return con


def meta(con: sqlite3.Connection) -> dict[str, str]:
    return {zeile["schluessel"]: zeile["wert"] for zeile in con.execute("SELECT * FROM meta")}


# --------------------------------------------------------------------------
# Abfragen
# --------------------------------------------------------------------------
def _zeile(zeile: sqlite3.Row) -> dict[str, Any]:
    return {schluessel: zeile[schluessel] for schluessel in zeile.keys()}


def alle_knoten(con: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_zeile(z) for z in con.execute("SELECT * FROM knoten ORDER BY name, kennung")]


def knoten_suchen(
    con: sqlite3.Connection,
    text: str,
    *,
    archimate_typ: str | None = None,
) -> list[dict[str, Any]]:
    """Knoten ueber Kennung, Name oder Namensteil finden.

    Reihenfolge: exakte Kennung, exakter Name, dann Namensteil. Teiltreffer
    werden in Python verglichen (SQLite-LIKE ist nicht umlautfest).
    """
    text = (text or "").strip()
    if not text:
        raise GraphError("Suche: leerer Suchbegriff")
    sql = "SELECT * FROM knoten WHERE kennung = ?"
    parameter: list[Any] = [text]
    treffer = [_zeile(z) for z in con.execute(sql, parameter)]
    if not treffer:
        treffer = [
            _zeile(z)
            for z in con.execute("SELECT * FROM knoten WHERE name = ? COLLATE NOCASE ORDER BY kennung", (text,))
        ]
    if not treffer:
        klein = text.lower()
        treffer = [
            k
            for k in alle_knoten(con)
            if klein in k["name"].lower() or klein in k["kennung"].lower()
        ]
    if archimate_typ is not None:
        treffer = [k for k in treffer if k["archimate_typ"] == archimate_typ]
    return treffer


def _kanten_um(con: sqlite3.Connection, kennung: str, richtung: str) -> list[sqlite3.Row]:
    if richtung == "aus":
        return list(
            con.execute(
                "SELECT kennung, typ, quelle, ziel, 'aus' AS richtung FROM kanten"
                " WHERE quelle = ? ORDER BY typ, kennung",
                (kennung,),
            )
        )
    if richtung == "ein":
        return list(
            con.execute(
                "SELECT kennung, typ, quelle, ziel, 'ein' AS richtung FROM kanten"
                " WHERE ziel = ? ORDER BY typ, kennung",
                (kennung,),
            )
        )
    return list(
        con.execute(
            "SELECT kennung, typ, quelle, ziel, 'aus' AS richtung FROM kanten WHERE quelle = ?"
            " UNION ALL "
            "SELECT kennung, typ, quelle, ziel, 'ein' AS richtung FROM kanten WHERE ziel = ?"
            " ORDER BY typ, kennung, richtung",
            (kennung, kennung),
        )
    )


def umfeld(
    con: sqlite3.Connection,
    start: str,
    *,
    tiefe: int = 1,
    richtung: str = "beide",
) -> list[dict[str, Any]]:
    """Knoten im Umfeld eines Knotens, mit Tiefe und Kantenrichtung.

    ``richtung``: ``aus`` (nur ausgehende Kanten), ``ein`` (nur eingehende),
    ``beide``. Jeder Knoten erscheint einmal, mit der kuerzesten Tiefe und der
    Kante, ueber die er zuerst erreicht wurde.
    """
    if tiefe < 1:
        raise GraphError("tiefe: mindestens 1")
    if richtung not in ("aus", "ein", "beide"):
        raise GraphError(f"richtung: 'aus', 'ein' oder 'beide' erwartet, gefunden {richtung!r}")
    if not any(True for _ in con.execute("SELECT 1 FROM knoten WHERE kennung = ?", (start,))):
        raise GraphError(f"Startknoten {start!r} ist nicht im Graphen")

    besucht = {start}
    frontier = [start]
    ergebnis: list[dict[str, Any]] = []
    for stufe in range(1, tiefe + 1):
        naechste: list[str] = []
        for knoten in frontier:
            for kante in _kanten_um(con, knoten, richtung):
                if kante["richtung"] == "aus":
                    nachbar = kante["ziel"]
                else:
                    nachbar = kante["quelle"]
                if nachbar is None or nachbar in besucht:
                    continue
                besucht.add(nachbar)
                naechste.append(nachbar)
                zeile = _zeile(
                    con.execute("SELECT * FROM knoten WHERE kennung = ?", (nachbar,)).fetchone()
                )
                zeile.update(
                    {
                        "tiefe": stufe,
                        "richtung": kante["richtung"],
                        "beziehung": kante["typ"],
                        "kante": kante["kennung"],
                    }
                )
                ergebnis.append(zeile)
        frontier = naechste
        if not frontier:
            break
    return ergebnis


def elemente_an_faehigkeit(
    con: sqlite3.Connection,
    faehigkeit: str,
    *,
    tiefe: int = 1,
    richtung: str = "beide",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Alles, was an einer Faehigkeit haengt -- (Faehigkeit, Umfeld).

    Die Faehigkeit wird ueber Kennung, Name oder Namensteil gesucht und muss ein
    ArchiMate-Typ ``Capability`` sein. Mehrdeutige Treffer werden nicht
    geraten: dann kommt ``Mehrdeutig`` mit der Kandidatenliste.
    """
    treffer = knoten_suchen(con, faehigkeit)
    if not treffer:
        raise GraphError(f"keine Faehigkeit gefunden fuer {faehigkeit!r}")
    kandidaten = [k for k in treffer if k["archimate_typ"] == "Capability"]
    if not kandidaten:
        arten = ", ".join(sorted({k["archimate_typ"] or k["typ"] for k in treffer}))
        raise GraphError(
            f"{faehigkeit!r} trifft {len(treffer)} Knoten, aber keine Faehigkeit "
            f"(gefunden: {arten})"
        )
    if len(kandidaten) > 1:
        exakt = [
            k
            for k in kandidaten
            if k["kennung"] == faehigkeit or k["name"].lower() == faehigkeit.strip().lower()
        ]
        if len(exakt) == 1:
            kandidaten = exakt
        else:
            raise Mehrdeutig(faehigkeit, kandidaten)
    start = kandidaten[0]
    return start, umfeld(con, start["kennung"], tiefe=tiefe, richtung=richtung)


def befunde(
    con: sqlite3.Connection,
    *,
    regel: str | None = None,
    schwere: str | None = None,
) -> list[dict[str, Any]]:
    """Alle Befunde des Graphen -- je Regel, Schwere und Kante eine Zeile."""
    sql = "SELECT * FROM v_befunde WHERE 1 = 1"
    parameter: list[Any] = []
    if regel:
        sql += " AND regel = ?"
        parameter.append(regel)
    if schwere:
        sql += " AND schwere = ?"
        parameter.append(schwere)
    sql += " ORDER BY regel, position, nachricht"
    return [_zeile(z) for z in con.execute(sql, parameter)]


def ungueltige_kanten(
    con: sqlite3.Connection,
    *,
    regel: str | None = None,
) -> list[dict[str, Any]]:
    """Kanten mit einem Fehler -- die Pflichtabfrage des Graphen."""
    return befunde(con, regel=regel, schwere=FEHLER)


def pfad(
    con: sqlite3.Connection,
    von: str,
    nach: str,
    *,
    max_tiefe: int = 8,
    richtung: str = "beide",
) -> dict[str, Any] | None:
    """Kuerzester Weg zwischen zwei Knoten (Breitensuche), sonst ``None``."""
    start = _ein_knoten(con, von)
    ziel = _ein_knoten(con, nach)
    if start["kennung"] == ziel["kennung"]:
        return {"tiefe": 0, "knoten": [start], "kanten": []}
    besucht = {start["kennung"]}
    vorgaenger: dict[str, tuple[str, str, str]] = {}  # nachbar -> (knoten, kante, typ)
    frontier = [start["kennung"]]
    for _ in range(max_tiefe):
        naechste: list[str] = []
        for knoten in frontier:
            for kante in _kanten_um(con, knoten, richtung):
                nachbar = kante["ziel"] if kante["richtung"] == "aus" else kante["quelle"]
                if nachbar is None or nachbar in besucht:
                    continue
                besucht.add(nachbar)
                vorgaenger[nachbar] = (knoten, kante["kennung"], kante["typ"])
                if nachbar == ziel["kennung"]:
                    return _wege(con, start["kennung"], ziel["kennung"], vorgaenger)
                naechste.append(nachbar)
        frontier = naechste
        if not frontier:
            break
    return None


def _wege(
    con: sqlite3.Connection, start: str, ziel: str, vorgaenger: Mapping[str, tuple[str, str, str]]
) -> dict[str, Any]:
    kanten: list[dict[str, str]] = []
    kennungen = [ziel]
    aktuell = ziel
    while aktuell != start:
        vorher, kante, typ = vorgaenger[aktuell]
        kanten.append({"kante": kante, "typ": typ, "von": vorher, "nach": aktuell})
        kennungen.append(vorher)
        aktuell = vorher
    kennungen.reverse()
    kanten.reverse()
    knoten = [
        _zeile(con.execute("SELECT * FROM knoten WHERE kennung = ?", (k,)).fetchone())
        for k in kennungen
    ]
    return {"tiefe": len(kanten), "knoten": knoten, "kanten": kanten}


def _ein_knoten(con: sqlite3.Connection, text: str) -> dict[str, Any]:
    treffer = knoten_suchen(con, text)
    if not treffer:
        raise GraphError(f"kein Knoten gefunden fuer {text!r}")
    if len(treffer) > 1:
        exakt = [k for k in treffer if k["kennung"] == text or k["name"].lower() == text.strip().lower()]
        if len(exakt) == 1:
            return exakt[0]
        raise Mehrdeutig(text, treffer)
    return treffer[0]


def statistik(con: sqlite3.Connection) -> dict[str, Any]:
    """Kennzahlen des Graphen -- was drin ist und was fehlt."""
    knoten_je_art = {
        zeile["art"]: zeile["anzahl"]
        for zeile in con.execute("SELECT art, COUNT(*) AS anzahl FROM knoten GROUP BY art ORDER BY art")
    }
    typen = [
        {"archimate_typ": z["archimate_typ"], "anzahl": z["anzahl"]}
        for z in con.execute(
            "SELECT archimate_typ, COUNT(*) AS anzahl FROM knoten WHERE art = 'element'"
            " GROUP BY archimate_typ ORDER BY anzahl DESC, archimate_typ"
        )
    ]
    beziehungen = [
        {"beziehung": z["beziehung"], "anzahl": z["anzahl"], "ungueltig": z["ungueltig"]}
        for z in con.execute(
            "SELECT typ AS beziehung, COUNT(*) AS anzahl, SUM(1 - gueltig) AS ungueltig"
            " FROM kanten GROUP BY typ ORDER BY anzahl DESC, typ"
        )
    ]
    regeln = [
        {"regel": z["regel"], "schwere": z["schwere"], "anzahl": z["anzahl"]}
        for z in con.execute(
            "SELECT regel, schwere, COUNT(*) AS anzahl FROM befunde GROUP BY regel, schwere ORDER BY regel"
        )
    ]
    ohne = con.execute(
        "SELECT COUNT(*) FROM knoten WHERE art = 'element' AND archimate_typ = ''"
    ).fetchone()[0]
    return {
        "meta": meta(con),
        "knoten_je_art": knoten_je_art,
        "ohne_abbildung": ohne,
        "typen": typen,
        "beziehungen": beziehungen,
        "befunde": regeln,
    }


# --------------------------------------------------------------------------
# Ausgabe
# --------------------------------------------------------------------------
def _drucke_umfeld(start: Mapping[str, Any], zeilen: Sequence[Mapping[str, Any]]) -> None:
    print(
        f"Faehigkeit: {start['name']}  [{start['kennung']}]  "
        f"{start['archimate_typ']}, Paket {start['paket'] or '-'}"
    )
    if not zeilen:
        print("  (keine Nachbarn)")
        return
    breite_tiefe = max(len(str(z["tiefe"])) for z in zeilen)
    breite_typ = max(len(z["archimate_typ"] or z["typ"]) for z in zeilen)
    for zeile in zeilen:
        pfeil = "->" if zeile["richtung"] == "aus" else "<-"
        print(
            f"  {zeile['tiefe']:>{breite_tiefe}}  {pfeil} {zeile['beziehung']:<14} "
            f"{(zeile['archimate_typ'] or zeile['typ']):<{breite_typ}}  {zeile['name']}"
        )


def _drucke_befunde(zeilen: Sequence[Mapping[str, Any]], limit: int = 20) -> None:
    if not zeilen:
        print("Keine ungueltigen Kanten.")
        return
    nach_regel: dict[str, list[Mapping[str, Any]]] = {}
    for zeile in zeilen:
        nach_regel.setdefault(zeile["regel"], []).append(zeile)
    for regel in sorted(nach_regel):
        eintraege = nach_regel[regel]
        schwere = eintraege[0]["schwere"]
        print(f"\n{regel} {REGELN[regel][1]} ({schwere}): {len(eintraege)}")
        for zeile in eintraege[:limit]:
            print(
                f"  #{zeile['position']:<5} {zeile['quell_name'] or zeile['quelle_ref']} "
                f"--{zeile['beziehung'] or '?'}--> {zeile['ziel_name'] or zeile['ziel_ref']}"
            )
            print(f"         {zeile['nachricht']}")
        if len(eintraege) > limit:
            print(f"  ... {len(eintraege) - limit} weitere (--limit 0 zeigt alle)")


# --------------------------------------------------------------------------
# Kommandozeile
# --------------------------------------------------------------------------
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph.py",
        description="ArchiMate-Modelle als Graph (SQLite): laden, Umfeld und ungueltige Kanten abfragen.",
    )
    sub = parser.add_subparsers(dest="befehl", required=True)

    p_laden = sub.add_parser("laden", help="Modell (.qea, .xml, .json) in eine Graphdatenbank schreiben")
    p_laden.add_argument("--in", "-i", dest="quelle", required=True, type=Path, help="Modelldatei")
    p_laden.add_argument("--db", type=Path, default=Path("graph.sqlite"), help="Ziel-Graphdatenbank")
    p_laden.add_argument("--ersetzt", action="store_true", help="vorhandene Datenbank ueberschreiben")
    p_laden.add_argument("--strict", action="store_true", help="Warnungen der Reader als Fehler behandeln")
    p_laden.add_argument("--report", type=Path, default=None, help="Ladebericht als JSON schreiben")
    p_laden.add_argument("--json", action="store_true", help="Bericht als JSON auf der Standardausgabe")
    p_laden.set_defaults(func=cmd_laden)

    p_faehig = sub.add_parser("faehigkeit", help="Elemente im Umfeld einer Faehigkeit")
    p_faehig.add_argument("--db", type=Path, default=Path("graph.sqlite"))
    p_faehig.add_argument("--name", "-n", required=True, help="Kennung, Name oder Namensteil")
    p_faehig.add_argument("--tiefe", type=int, default=1, help="Schritte (Default 1)")
    p_faehig.add_argument(
        "--richtung", choices=("beide", "aus", "ein"), default="beide", help="Kantenrichtung"
    )
    p_faehig.add_argument("--json", action="store_true")
    p_faehig.set_defaults(func=cmd_faehigkeit)

    p_bef = sub.add_parser("befunde", help="Befunde der Kantenpruefung (alle Schweregrade)")
    p_bef.add_argument("--db", type=Path, default=Path("graph.sqlite"))
    p_bef.add_argument("--regel", default=None, help="nur diese Regel (etwa K04)")
    p_bef.add_argument("--schwere", choices=(FEHLER, WARNUNG, HINWEIS), default=None)
    p_bef.add_argument("--limit", type=int, default=20, help="Zeilen je Regel (0 = alle)")
    p_bef.add_argument("--json", action="store_true")
    p_bef.set_defaults(func=cmd_befunde, nur_fehler=False)

    p_ung = sub.add_parser("ungueltig", help="nur Kanten mit einem Fehler")
    p_ung.add_argument("--db", type=Path, default=Path("graph.sqlite"))
    p_ung.add_argument("--regel", default=None, help="nur diese Regel (etwa K04)")
    p_ung.add_argument("--limit", type=int, default=20, help="Zeilen je Regel (0 = alle)")
    p_ung.add_argument("--json", action="store_true")
    p_ung.set_defaults(func=cmd_befunde, nur_fehler=True)

    p_pfad = sub.add_parser("pfad", help="kuerzester Weg zwischen zwei Knoten")
    p_pfad.add_argument("--db", type=Path, default=Path("graph.sqlite"))
    p_pfad.add_argument("--von", required=True)
    p_pfad.add_argument("--nach", required=True)
    p_pfad.add_argument("--tiefe", type=int, default=8, help="maximale Laenge (Default 8)")
    p_pfad.add_argument("--json", action="store_true")
    p_pfad.set_defaults(func=cmd_pfad)

    p_stat = sub.add_parser("statistik", help="Kennzahlen des Graphen")
    p_stat.add_argument("--db", type=Path, default=Path("graph.sqlite"))
    p_stat.add_argument("--json", action="store_true")
    p_stat.set_defaults(func=cmd_statistik)
    return parser


def cmd_laden(args: argparse.Namespace) -> int:
    bericht = lade(args.quelle, args.db, strict=args.strict, ersetzen=args.ersetzt)
    if args.report:
        args.report.write_text(
            json.dumps(bericht.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.json:
        print(json.dumps(bericht.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(bericht.summary())
        print(f"  Datenbank: {args.db}")
    return 0


def cmd_faehigkeit(args: argparse.Namespace) -> int:
    con = oeffne(args.db)
    try:
        start, zeilen = elemente_an_faehigkeit(
            con, args.name, tiefe=args.tiefe, richtung=args.richtung
        )
    finally:
        con.close()
    if args.json:
        print(
            json.dumps(
                {"faehigkeit": start, "umfeld": zeilen}, ensure_ascii=False, indent=2
            )
        )
    else:
        _drucke_umfeld(start, zeilen)
    return 0


def cmd_befunde(args: argparse.Namespace) -> int:
    con = oeffne(args.db)
    try:
        if getattr(args, "nur_fehler", False):
            zeilen = ungueltige_kanten(con, regel=args.regel)
        else:
            zeilen = befunde(con, regel=args.regel, schwere=args.schwere)
    finally:
        con.close()
    if args.json:
        print(json.dumps(zeilen, ensure_ascii=False, indent=2))
    else:
        _drucke_befunde(zeilen, limit=args.limit or 10**9)
        print(f"\n{len(zeilen)} Befund(e).")
    return 0


def cmd_pfad(args: argparse.Namespace) -> int:
    con = oeffne(args.db)
    try:
        ergebnis = pfad(con, args.von, args.nach, max_tiefe=args.tiefe)
    finally:
        con.close()
    if args.json:
        print(json.dumps(ergebnis, ensure_ascii=False, indent=2))
        return 0 if ergebnis else 1
    if not ergebnis:
        print(f"Kein Weg zwischen {args.von!r} und {args.nach!r} (max. {args.tiefe} Schritte).")
        return 1
    print(f"{ergebnis['tiefe']} Schritt(e):")
    for index, kante in enumerate(ergebnis["kanten"], start=1):
        print(f"  {index}. {kante['typ']:<14} {kante['von']} -> {kante['nach']}")
    return 0


def cmd_statistik(args: argparse.Namespace) -> int:
    con = oeffne(args.db)
    try:
        daten = statistik(con)
    finally:
        con.close()
    if args.json:
        print(json.dumps(daten, ensure_ascii=False, indent=2))
        return 0
    print(f"Modell: {daten['meta'].get('modell') or '-'}  ({daten['meta'].get('quelle') or '-'})")
    print(
        "Knoten: "
        + ", ".join(f"{anzahl} {art}" for art, anzahl in sorted(daten["knoten_je_art"].items()))
    )
    print(
        "Typen:  "
        + ", ".join(
            f"{t['archimate_typ'] or '(ohne Abbildung)'} {t['anzahl']}" for t in daten["typen"][:10]
        )
        + (" ..." if len(daten["typen"]) > 10 else "")
    )
    print(
        "Kanten: "
        + ", ".join(
            f"{z['beziehung'] or '?'} {z['anzahl']} ({z['ungueltig']} ungueltig)"
            for z in daten["beziehungen"]
        )
    )
    if daten["befunde"]:
        print("Befunde: " + ", ".join(f"{z['regel']} {z['anzahl']}" for z in daten["befunde"]))
    else:
        print("Befunde: keine")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Mehrdeutig as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (GraphError, OSError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
