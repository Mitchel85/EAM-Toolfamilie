"""handbuch_generator.py -- aus einer .qea ein Betriebshandbuch in Prosa.

Das Modul liest eine beliebige Ablage (nur lesend) und schreibt daraus ein
Betriebshandbuch in deutscher Erzählform. Thema ist ausschließlich das
beschriebene System: sein Auftrag, sein Aufbau, seine Dienste, seine Abläufe,
seine Fähigkeiten und die Vorgaben, unter denen es betrieben wird.

Grundsatz: Im Code steht kein Fachwissen zu einem einzelnen Vorhaben. Alle
Aussagen stammen aus Namen, Notizen, Stereotypen und Verbindungen der
gelesenen Ablage. Fehlt eine Angabe, sagt der Text das -- erfunden wird nichts.

Öffentliche Schnittstelle::

    from handbuch_generator import generate_handbook

    kennzahlen = generate_handbook("vorhaben.qea", "handbuch.md")

CLI::

    python3 handbuch_generator.py QUELLE.qea --md handbuch.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from roundtrip_export import Modell, lade_modell

TITEL = "Betriebshandbuch"

KAPITEL: tuple[str, ...] = (
    "Zweck und Auftrag",
    "Das System im Überblick",
    "Aufbau",
    "Die Dienste",
    "Abläufe und Verfahren",
    "Fähigkeiten und Leistungsvermögen",
    "Betrieb und Überwachung",
    "Sicherheit und Randbedingungen",
    "Glossar",
    "Anhang",
)

#: Begriffe, die die Herkunft der Angaben verraten würden. Jeder Treffer
#: bricht die Ausgabe ab; der Text beschreibt das System, nicht die Ablage.
VERBOTEN: tuple[str, ...] = (
    "Architektur",
    "Modell",
    "Element",
    "Stereotyp",
    "Paket",
    "Sicht",
    "Diagramm",
    "GUID",
    "Datenbank",
    "Katalog",
    "Metamodell",
)

DIENST_STEREOTYPE = frozenset({"ServiceSpecification", "ActualService"})
BAUTEIL_STEREOTYPE = frozenset(
    {
        "ActualResource",
        "Resource",
        "Component",
        "System",
        "Subsystem",
        "OperationalPerformer",
        "ActualOrganization",
        "ActualPost",
    }
)
FAEHIGKEIT_STEREOTYPE = frozenset({"Capability"})
ZIEL_STEREOTYPE = frozenset({"EnterpriseGoal", "Goal", "ActualGoal"})
RANDBEDINGUNG_STEREOTYPE = frozenset({"ResourceConstraint"})
FORDERUNG_STEREOTYPE = frozenset(
    {"Requirement", "FunctionalRequirement", "NonfunctionalRequirement"}
)
ABLAUF_STEREOTYPE = frozenset(
    {"OperationalActivity", "Activity", "Function", "Process", "ActualProcess"}
)
ZUSTAND_STEREOTYPE = frozenset({"State", "ActualState", "StateMachine"})

KATEGORIEN: tuple[tuple[str, frozenset[str]], ...] = (
    ("dienst", DIENST_STEREOTYPE),
    ("bauteil", BAUTEIL_STEREOTYPE),
    ("faehigkeit", FAEHIGKEIT_STEREOTYPE),
    ("forderung", FORDERUNG_STEREOTYPE),
    ("vorgabe", RANDBEDINGUNG_STEREOTYPE),
    ("ablauf", ABLAUF_STEREOTYPE),
    ("zustand", ZUSTAND_STEREOTYPE),
    ("ziel", ZIEL_STEREOTYPE),
)


class HandbuchFehler(ValueError):
    """Das Handbuch kann so nicht geschrieben werden."""


# --------------------------------------------------------------------------
# Textwerkzeuge
# --------------------------------------------------------------------------

_MEHRFACH = re.compile(r"[ \t]{2,}")
_UMBRUCH = re.compile(r"\s*\n\s*")
_KLAMMER = re.compile(r"\{[^}]*\}")


def _flach(text: object) -> str:
    if not text:
        return ""
    sauber = _KLAMMER.sub("", str(text))
    sauber = _UMBRUCH.sub(" ", sauber)
    sauber = _MEHRFACH.sub(" ", sauber)
    return sauber.strip()


def _name(text: object) -> str:
    return _flach(text)


def _satz(text: str) -> str:
    sauber = text.strip()
    if not sauber:
        return ""
    if sauber[-1] not in ".!?":
        sauber += "."
    return sauber


def _reihe(teile: Sequence[str], bindewort: str = "und") -> str:
    teile = [t for t in teile if t]
    if not teile:
        return ""
    if len(teile) == 1:
        return teile[0]
    return ", ".join(teile[:-1]) + f" {bindewort} " + teile[-1]


def _zahlwort(anzahl: int) -> str:
    return {
        0: "keine",
        1: "eine",
        2: "zwei",
        3: "drei",
        4: "vier",
        5: "fünf",
        6: "sechs",
        7: "sieben",
        8: "acht",
        9: "neun",
        10: "zehn",
        11: "elf",
        12: "zwölf",
    }.get(anzahl, str(anzahl))


#: Ersatzworte für Begriffe, die in Namen und Notizen vorkommen können. Sie
#: werden nur im erzählenden Teil ersetzt; das Verzeichnis nennt die echten
#: Bezeichnungen, sonst wäre der Rückweg unvollständig.
NEUTRAL: tuple[tuple[str, str], ...] = (
    ("Architektur", "Aufbau"),
    ("Metamodell", "Ordnungsrahmen"),
    ("Modell", "Vorhaben"),
    ("Stereotyp", "Art"),
    ("Element", "Bestandteil"),
    ("Paket", "Bündel"),
    ("Sicht", "Ansicht"),
    ("Diagramm", "Darstellung"),
    ("Datenbank", "Ablage"),
    ("Katalog", "Verzeichnis"),
)


#: Ein Begriff zählt am Wortanfang, nicht mitten im Wort. Sonst wird aus
#: "unberücksichtigt" ein "unberückAnAnsichtigt", und "Ansicht" zählt als
#: verbotene "Sicht". Wortanfang heißt: davor steht kein Buchstabe.
_WORTANFANG = r"(?<![A-Za-zÄÖÜäöüß])"


def entschaerfen(text: str) -> str:
    """Ersetzt Herkunftsbegriffe im erzählenden Text, ohne Sinn zu verlieren."""
    sauber = text
    for alt, neu in NEUTRAL:
        sauber = re.sub(_WORTANFANG + re.escape(alt), neu, sauber, flags=re.IGNORECASE)
    return sauber


def verbote_zaehlen(text: str) -> dict[str, int]:
    """Zählt die verbotenen Begriffe am Wortanfang (auch "Sichten")."""
    treffer = {
        wort: len(re.findall(_WORTANFANG + re.escape(wort), text, flags=re.IGNORECASE))
        for wort in VERBOTEN
    }
    return {wort: anzahl for wort, anzahl in treffer.items() if anzahl}


# --------------------------------------------------------------------------
# Aufbereitete Quelle
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Posten:
    name: str
    kategorie: str
    note: str
    stereotype: str
    id: int
    nachbarn: tuple[str, ...] = ()
    #: Objektkennung aus der Ablage -- bleibt ueber Export und Rueckbau gleich.
    schluessel: str = ""
    #: Paketpfad; dient als Ersatz, wenn keine Kennung vorliegt.
    paket: str = ""

    def sortierwert(self) -> tuple[str, str, str]:
        """Reihenfolge der Nennung: nach Kennung, nicht nach Datenbankzeile.

        Die ``Object_ID`` haengt davon ab, in welcher Reihenfolge Elemente
        angelegt wurden. Aendert sich der Rueckbau, aendert sich auch, welche
        Baugruppen die Einleitung nennt -- das Handbuch waere dann nicht mehr
        wiederholbar. Die Kennung bleibt gleich.
        """
        return (self.schluessel.casefold(), self.paket.casefold(), self.name.casefold())


@dataclass(frozen=True)
class Verbindung:
    quelle: str
    ziel: str
    art: str
    note: str = ""


@dataclass
class Quelle:
    titel: str
    untertitel: str
    posten: tuple[Posten, ...]
    kennzahlen: dict[str, int]
    alle_namen: tuple[str, ...]
    kanten: tuple[Verbindung, ...] = ()
    pakete: tuple[str, ...] = ()

    def der(self, kategorie: str) -> tuple[Posten, ...]:
        return tuple(p for p in self.posten if p.kategorie == kategorie)

    def zahl(self, schluessel: str) -> int:
        return int(self.kennzahlen.get(schluessel, 0))


def _kategorie(stereotype: str) -> str:
    for schluessel, menge in KATEGORIEN:
        if stereotype in menge:
            return schluessel
    return "sonstiges"


def _ist_systemname(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if name[0].isdigit():
        return False
    if verbote_zaehlen(name):
        return False
    if re.fullmatch(r"[\d\s.,%/-]+", name):
        return False
    return True


def lade_quelle(pfad: str | Path) -> Quelle:
    """Liest die Ablage und bereitet sie für das Handbuch auf."""
    ort = Path(pfad)
    if not ort.is_file():
        raise FileNotFoundError(f"Quelle nicht gefunden: {ort}")
    modell: Modell = lade_modell(ort)

    elemente = sorted(modell.elemente, key=lambda e: e.id)
    namen = {e.id: _name(e.name) for e in elemente}

    kanten: list[Verbindung] = []
    for kante in sorted(modell.kanten, key=lambda k: getattr(k, "id", 0)):
        quelle = _flach(getattr(kante, "quelle", "") or namen.get(getattr(kante, "start_id", None), ""))
        ziel = _flach(getattr(kante, "ziel", "") or namen.get(getattr(kante, "end_id", None), ""))
        art = _flach(getattr(kante, "stereotype", "") or getattr(kante, "typ", ""))
        note = _flach(getattr(kante, "notes", ""))
        if quelle and ziel:
            kanten.append(Verbindung(quelle, ziel, art, note))

    nachbar_map: dict[str, list[str]] = {}
    for kante in kanten:
        for a, b in ((kante.quelle, kante.ziel), (kante.ziel, kante.quelle)):
            if a and b and a != b:
                nachbar_map.setdefault(a, []).append(b)

    pakete = tuple(_name(p.name) for p in sorted(modell.pakete.values(), key=lambda p: p.id))
    # Pfad je Paket-ID, damit jeder Posten sein Paket kennt
    pfade: dict[object, str] = {}

    def pfad_von(pid: object) -> str:
        if pid in pfade:
            return pfade[pid]
        paket = modell.pakete.get(pid) if hasattr(modell.pakete, "get") else None
        if paket is None:
            pfade[pid] = ""
        elif getattr(paket, "path", ""):
            pfade[pid] = str(paket.path)
        else:
            oben = pfad_von(getattr(paket, "parent_id", 0))
            name_paket = _name(getattr(paket, "name", ""))
            pfade[pid] = f"{oben}/{name_paket}" if oben else name_paket
        return pfade[pid]
    posten: list[Posten] = []
    for e in elemente:
        name = namen.get(e.id, "")
        if not _ist_systemname(name):
            continue
        posten.append(
            Posten(
                name=name,
                kategorie=_kategorie(_flach(getattr(e, "stereotype", ""))),
                note=_flach(getattr(e, "notes", "")),
                stereotype=_flach(getattr(e, "stereotype", "")),
                id=e.id,
                nachbarn=tuple(dict.fromkeys(nachbar_map.get(name, ()))),
                schluessel=_flach(getattr(e, "guid", "")),
                paket=pfad_von(getattr(e, "paket_id", 0)),
            )
        )

    untertitel = pakete[0] if pakete else ""
    if untertitel.casefold().startswith("model") and len(pakete) > 1:
        untertitel = pakete[1]

    kennzahlen = {
        "dienste": sum(1 for p in posten if p.kategorie == "dienst"),
        "bauteile": sum(1 for p in posten if p.kategorie == "bauteil"),
        "faehigkeiten": sum(1 for p in posten if p.kategorie == "faehigkeit"),
        "forderungen": sum(1 for p in posten if p.kategorie == "forderung"),
        "vorgaben": sum(1 for p in posten if p.kategorie == "vorgabe"),
        "ablaeufe": sum(1 for p in posten if p.kategorie == "ablauf"),
        "ziele": sum(1 for p in posten if p.kategorie == "ziel"),
        "kanten": len(kanten),
        "bezeichnungen": len(posten),
    }
    return Quelle(
        titel=TITEL,
        untertitel=untertitel,
        posten=tuple(sorted(posten, key=Posten.sortierwert)),
        kennzahlen=kennzahlen,
        alle_namen=tuple(sorted({p.name for p in posten})),
        kanten=tuple(kanten),
        pakete=pakete,
    )


# --------------------------------------------------------------------------
# Buch (Markdown)
# --------------------------------------------------------------------------


class Buch:
    """Sammelt Absätze; die Sprachprüfung läuft am Ende über den Gesamttext."""

    def __init__(self) -> None:
        self._teile: list[str] = []

    def h1(self, text: str) -> None:
        # Auch Ueberschriften entschaerfen: der oberste Paketname ist often
        # "Architektur" und wuerde sonst als Titel im Dokument stehen.
        self._teile.append(f"# {entschaerfen(_flach(text))}\n")

    def h2(self, text: str) -> None:
        self._teile.append(f"\n## {_flach(text)}\n")

    def h3(self, text: str) -> None:
        self._teile.append(f"\n### {entschaerfen(_flach(text))}\n")

    def p(self, *absaetze: str) -> None:
        for absatz in absaetze:
            sauber = _satz(entschaerfen(_flach(absatz))) if absatz else ""
            if sauber:
                self._teile.append(sauber + "\n")

    def liste(self, zeilen: Iterable[str]) -> None:
        eintraege = [_flach(z) for z in zeilen if _flach(z)]
        if eintraege:
            self._teile.append("\n".join(f"- {z}" for z in eintraege) + "\n")

    def tabelle(self, kopf: Sequence[str], zeilen: Iterable[Sequence[str]]) -> None:
        self._teile.append("| " + " | ".join(kopf) + " |")
        self._teile.append("| " + " | ".join("---" for _ in kopf) + " |")
        for zeile in zeilen:
            self._teile.append("| " + " | ".join(str(z) for z in zeile) + " |")
        self._teile.append("")

    def text(self) -> str:
        roh = "\n".join(self._teile)
        roh = re.sub(r"\n{3,}", "\n\n", roh)
        return roh.strip() + "\n"


# --------------------------------------------------------------------------
# Kapitel
# --------------------------------------------------------------------------


def _kapitel_auftrag(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"1 {KAPITEL[0]}")
    name = quelle.untertitel or "Das System"
    ziele = quelle.der("ziel")
    faehigkeiten = quelle.der("faehigkeit")

    buch.h3("1.1 Wozu dieses Handbuch")
    buch.p(
        f"Dieses Handbuch beschreibt {name} im Betrieb. Es richtet sich an alle, "
        "die mit dem System arbeiten, es betreiben, ausbilden oder darüber "
        "entscheiden. Es erzählt, was das System tut, wie seine Baugruppen "
        "zusammenwirken und nach welchen Verfahren gearbeitet wird.",
        "Das Handbuch ist keine Bedienungsanleitung im engeren Sinn. Es erklärt "
        "die Zusammenhänge und die Gründe hinter den Handgriffen, damit die "
        "Beteiligten in Lagen entscheiden können, die in keiner Vorschrift "
        "stehen. Wo eine Regel eng gefasst ist, steht das ausdrücklich dabei.",
    )

    buch.h3("1.2 Der Auftrag")
    if ziele:
        buch.p(
            "Der Auftrag steht in den Zielen des Vorhabens. Sie sind im "
            "Einzelnen festgehalten und werden hier in ihrer Wirkung "
            "beschrieben: Sie bestimmen, welche Dienste es gibt, welche "
            "Fähigkeiten erbracht werden müssen und welche Grenzen dabei gelten."
        )
        for ziel in ziele:
            if ziel.note:
                buch.p(f"Für {ziel.name} ist festgehalten: {_satz(entschaerfen(ziel.note))}")
    else:
        buch.p(
            "Ein ausformulierter Auftrag ist nicht festgehalten. Was das System "
            "leisten soll, lässt sich aus seinen Fähigkeiten und Diensten "
            "ablesen; wo die Unterlagen schweigen, sagt dieses Handbuch das "
            "ausdrücklich und vermeidet Annahmen."
        )

    if faehigkeiten:
        namen = [f.name for f in faehigkeiten[:6]]
        buch.p(
            f"Getragen wird der Auftrag von {_zahlwort(len(faehigkeiten))} "
            f"Fähigkeiten, darunter {_reihe(namen)}. Sie sind der Maßstab, an "
            "dem sich der Betrieb messen lassen muss, und werden in Kapitel "
            "sechs einzeln vorgestellt."
        )

    buch.h3("1.3 Wie dieses Handbuch aufgebaut ist")
    buch.p(
        "Das zweite Kapitel beschreibt das System als Ganzes, das dritte seine "
        "Baugruppen. Das vierte stellt jeden Dienst in einem eigenen Abschnitt "
        "vor, das fünfte erzählt die Abläufe, in denen diese Dienste wirken. "
        "Die Kapitel sechs bis acht behandeln Fähigkeiten, Betrieb und "
        "Sicherheit; Kapitel neun erklärt die Begriffe, Kapitel zehn sammelt "
        "Kennzahlen und Verzeichnisse."
    )


def _kapitel_ueberblick(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"2 {KAPITEL[1]}")
    name = quelle.untertitel or "Das System"
    dienste = quelle.der("dienst")
    bauteile = quelle.der("bauteil")

    buch.h3("2.1 Was das System ausmacht")
    buch.p(
        f"{name} wird über seine Baugruppen und Dienste beschrieben. "
        f"Genannt sind {len(bauteile)} {'Baugruppe' if len(bauteile) == 1 else 'Baugruppen'} und "
        f"{len(dienste)} {'Dienst' if len(dienste) == 1 else 'Dienste'}; dazu treten "
        f"{quelle.zahl('faehigkeiten')} Fähigkeiten und "
        f"{quelle.zahl('vorgaben')} Vorgaben, die den Betrieb begrenzen."
    )
    if bauteile:
        buch.p(
            f"Die Baugruppen tragen das System: {_reihe([b.name for b in bauteile[:6]])}. "
            "Sie werden im dritten Kapitel einzeln vorgestellt, zusammen mit "
            "dem, was zu ihnen festgehalten ist und womit sie verbunden sind."
        )
    if dienste:
        buch.p(
            f"Die Dienste erbringen die Leistung: {_reihe([d.name for d in dienste[:6]])}. "
            "Sie laufen nicht einzeln, sondern greifen ineinander; Kapitel vier "
            "beschreibt jeden für sich, Kapitel fünf ihr Zusammenspiel."
        )

    buch.h3("2.2 Wie die Teile zusammenwirken")
    if quelle.kanten:
        arten: dict[str, int] = {}
        for kante in quelle.kanten:
            schluessel = kante.art or "Verbindung"
            arten[schluessel] = arten.get(schluessel, 0) + 1
        haeufig = sorted(arten.items(), key=lambda pa: (-pa[1], pa[0]))[:4]
        buch.p(
            f"Zwischen den Teilen sind {quelle.zahl('kanten')} Verbindungen "
            "festgehalten. Sie sagen, wer wen braucht, wer wem zuarbeitet und "
            "wovon etwas abhängt. Am häufigsten treten "
            f"{_reihe([f'{_flach(a)} ({n})' for a, n in haeufig])} auf."
        )
        gesehen: set[str] = set()
        for kante in quelle.kanten:
            note = _flach(kante.note)
            if not note or note.casefold() in gesehen:
                continue
            gesehen.add(note.casefold())
            buch.p(
                f"Für {kante.quelle} und {kante.ziel} ist festgehalten: {_satz(entschaerfen(note))}"
            )
        buch.p(
            "Wer eine Störung sucht, geht diesen Verbindungen nach: von der "
            "Meldung, die auffällt, zu dem Teil, das sie erzeugt, und von dort "
            "zu denen, die auf sie warten. Die Richtung ist dabei wichtig — sie "
            "steht in Kapitel fünf bei den Abläufen."
        )
    else:
        buch.p(
            "Verbindungen zwischen den Teilen sind nicht festgehalten. Das "
            "System wird deshalb über seine Bestandteile beschrieben; "
            "Abhängigkeiten lassen sich nur dort ablesen, wo sie ausdrücklich "
            "genannt sind."
        )


def _kapitel_aufbau(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"3 {KAPITEL[2]}")
    bauteile = quelle.der("bauteil")

    buch.p(
        "Dieses Kapitel geht die Baugruppen der Reihe nach durch. Zu jeder "
        "steht, was zu ihr festgehalten ist, womit sie verbunden ist und "
        "welche Aufgabe sie im Ganzen trägt. Wer eine Störung sucht, findet "
        "hier den Weg vom Symptom zur Baugruppe."
    )
    if not bauteile:
        buch.p(
            "Eigene Baugruppen sind nicht festgehalten. Der Aufbau ergibt sich "
            "dann allein aus den Diensten und ihren Verbindungen."
        )
        return

    for nummer, teil in enumerate(bauteile, start=1):
        buch.h3(f"3.{nummer} {teil.name}")
        if teil.note:
            buch.p(f"Zu dieser Baugruppe ist festgehalten: {_satz(teil.note)}")
        else:
            buch.p(
                "Zu dieser Baugruppe ist kein eigener Text festgehalten. Ihre "
                f"Rolle ergibt sich aus den {_zahlwort(len(teil.nachbarn))} "
                "Verbindungen, die zu ihr führen."
            )
        if teil.nachbarn:
            buch.p(
                f"Verbunden ist {teil.name} mit {_reihe(list(teil.nachbarn[:8]))}. "
                "Diese Nachbarschaft bestimmt, was die Baugruppe liefert und "
                "was sie von anderer Stelle erwartet."
            )


def _kapitel_dienste(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"4 {KAPITEL[3]}")
    dienste = quelle.der("dienst")

    if not dienste:
        buch.p(
            "Eigene Dienste sind nicht festgehalten. Die Leistung des Systems "
            "wird dann allein über seine Baugruppen und Abläufe beschrieben."
        )
        return

    buch.p(
        f"Das System erbringt seine Leistung über {_zahlwort(len(dienste))} "
        "Dienste. Jeder wird hier einzeln vorgestellt: mit dem, was zu ihm "
        "festgehalten ist, und mit seinen Nachbarn. Die Reihenfolge folgt dem "
        "Aufbau, nicht der Wichtigkeit."
    )
    for nummer, dienst in enumerate(dienste, start=1):
        buch.h3(f"4.{nummer} {dienst.name}")
        if dienst.note:
            buch.p(f"Zu diesem Dienst ist festgehalten: {_satz(dienst.note)}")
        else:
            buch.p(
                "Zu diesem Dienst ist kein eigener Text festgehalten. Seine "
                "Aufgabe ergibt sich aus den Verbindungen zu den übrigen "
                "Teilen des Systems."
            )
        if dienst.nachbarn:
            buch.p(
                f"Er ist verbunden mit {_reihe(list(dienst.nachbarn[:8]))}. "
                "Daraus ergibt sich, wem er zuarbeitet und wessen Meldungen er "
                "verarbeitet."
            )


def _kapitel_ablaeufe(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"5 {KAPITEL[4]}")
    ablaeufe = quelle.der("ablauf")
    verbindungen = [k for k in quelle.kanten if k.quelle != k.ziel]

    buch.p(
        "Ein Ablauf entsteht nicht aus einem einzelnen Teil, sondern aus dem "
        "Zusammenspiel mehrerer. Dieses Kapitel folgt den Verbindungen und "
        "erzählt, in welcher Reihenfolge etwas geschieht und wer dabei "
        "beteiligt ist."
    )
    if ablaeufe:
        for nummer, ablauf in enumerate(ablaeufe, start=1):
            buch.h3(f"5.{nummer} {ablauf.name}")
            if ablauf.note:
                buch.p(f"Zu diesem Ablauf ist festgehalten: {_satz(ablauf.note)}")
            if ablauf.nachbarn:
                buch.p(
                    f"Beteiligt sind {_reihe(list(ablauf.nachbarn[:8]))}. Der "
                    "Ablauf beginnt bei dem Teil, das die Auslösung liefert, "
                    "und endet bei dem, das das Ergebnis übernimmt."
                )
            else:
                buch.p(
                    "Beteiligte sind nicht ausdrücklich festgehalten; der "
                    "Ablauf steht damit für sich und wird im Betrieb durch die "
                    "zuständige Stelle ausgelöst."
                )
    else:
        buch.p(
            "Eigene Abläufe sind nicht festgehalten. Wo etwas geschieht, lässt "
            "es sich aus den Verbindungen der Dienste ablesen; eine feste "
            "Reihenfolge ist damit nicht belegt."
        )


def _kapitel_faehigkeiten(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"6 {KAPITEL[5]}")
    faehigkeiten = quelle.der("faehigkeit")

    if not faehigkeiten:
        buch.p(
            "Eigene Fähigkeiten sind nicht festgehalten. Das Leistungsvermögen "
            "lässt sich dann nur aus den Diensten und ihren Grenzen ableiten."
        )
        return

    buch.p(
        f"Das System soll {_zahlwort(len(faehigkeiten))} Fähigkeiten "
        "erbringen. Sie sind der Maßstab des Betriebs: Was hier nicht steht, "
        "muss auch nicht geliefert werden."
    )
    for nummer, faehigkeit in enumerate(faehigkeiten, start=1):
        buch.h3(f"6.{nummer} {faehigkeit.name}")
        if faehigkeit.note:
            buch.p(f"Dazu ist festgehalten: {_satz(faehigkeit.note)}")
        if faehigkeit.nachbarn:
            buch.p(
                f"Getragen wird sie von {_reihe(list(faehigkeit.nachbarn[:8]))}. "
                "Fällt einer dieser Teile aus, ist die Fähigkeit nicht mehr "
                "vollständig erbracht."
            )


def _kapitel_betrieb(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"7 {KAPITEL[6]}")
    zustaende = quelle.der("zustand")
    ablaeufe = quelle.der("ablauf")

    buch.p(
        "Der Betrieb besteht aus wenigen wiederkehrenden Handlungen: prüfen, "
        "melden, freigeben, nachhalten. Dieses Kapitel beschreibt, woran der "
        "Zustand des Systems abgelesen wird und wer dabei welche Rolle trägt."
    )
    buch.h3("7.1 Zustände")
    if zustaende:
        buch.p(
            f"Festgehalten sind {_zahlwort(len(zustaende))} Zustände: "
            f"{_reihe([z.name for z in zustaende[:8]])}. Sie beschreiben, in "
            "welcher Lage sich das System befinden kann und woran der Übergang "
            "zu erkennen ist."
        )
        for zustand in zustaende:
            if zustand.note:
                buch.p(f"{zustand.name}: {_satz(entschaerfen(zustand.note))}")
    else:
        buch.p(
            "Eigene Zustände sind nicht festgehalten. Der Betrieb wird deshalb "
            "über die laufenden Abläufe und die Meldungen der Dienste "
            "beschrieben."
        )

    buch.h3("7.2 Wiederkehrende Handlungen")
    if ablaeufe:
        buch.p(
            f"Im Betrieb wiederholen sich {_zahlwort(len(ablaeufe))} Abläufe. "
            "Sie werden ausgelöst, sobald die Voraussetzungen vorliegen, und "
            "enden mit einer Meldung an die zuständige Stelle."
        )
    else:
        buch.p(
            "Wiederkehrende Abläufe sind nicht ausdrücklich festgehalten. Der "
            "Betrieb stützt sich auf die Dienste und die Grenzen, die in "
            "Kapitel acht genannt sind."
        )


def _kapitel_sicherheit(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"8 {KAPITEL[7]}")
    vorgaben = quelle.der("vorgabe")
    forderungen = quelle.der("forderung")

    buch.p(
        "Kein System arbeitet ohne Grenzen. Sie stehen hier im Wortlaut, weil "
        "sich eine Vorgabe nicht zusammenfassen lässt, ohne sie zu verändern."
    )
    buch.h3("8.1 Vorgaben")
    if vorgaben:
        for vorgabe in vorgaben:
            if vorgabe.note:
                buch.p(f"Für {vorgabe.name} gilt: {_satz(vorgabe.note)}")
            else:
                buch.p(
                    f"Für {vorgabe.name} ist eine Vorgabe festgehalten, ihr "
                    "Wortlaut aber nicht überliefert."
                )
    else:
        buch.p(
            "Eigene Vorgaben sind nicht festgehalten. Der Betrieb richtet sich "
            "damit nach den Forderungen, die an das System gestellt sind."
        )

    if forderungen:
        buch.h3("8.2 Forderungen")
        buch.p(
            f"An das System sind {_zahlwort(len(forderungen))} Forderungen "
            "gestellt. Sie beschreiben, was es leisten muss, und sind im "
            "Anhang vollständig verzeichnet."
        )
        for forderung in forderungen:
            if forderung.note:
                buch.p(f"Für {forderung.name} gilt: {_satz(entschaerfen(forderung.note))}")


def _kapitel_glossar(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"9 {KAPITEL[8]}")
    # Alle Angaben, die in keinem eigenen Kapitel stehen (Organisationen,
    # Personen, Orte, Software, Dokumente, Grenzen ...). Vorher waren hier nur
    # kurze Namen und hoechstens 40 Eintraege -- lange Notizen und damit ganze
    # Quellabsaetze fielen aus dem Rueckweg. Jetzt gilt: jede Notiz kommt vor.
    begriffe = sorted(
        (p for p in quelle.posten if p.note and p.kategorie == "sonstiges"),
        key=lambda p: p.name.casefold(),
    )
    buch.p(
        "Die folgenden Begriffe kommen im Handbuch vor und werden hier kurz "
        "erklärt. Grundlage ist jeweils das, was zu ihnen festgehalten ist."
    )
    if not begriffe:
        buch.p("Eigene Begriffserklärungen sind nicht festgehalten.")
        return
    for begriff in begriffe:
        buch.p(f"**{begriff.name}** — {_satz(entschaerfen(begriff.note))}")


def _kapitel_anhang(quelle: Quelle, buch: Buch) -> None:
    buch.h2(f"10 {KAPITEL[9]}")

    buch.h3("10.1 Kennzahlen")
    buch.tabelle(
        ["Kennzahl", "Wert"],
        [
            ("Dienste", quelle.zahl("dienste")),
            ("Baugruppen", quelle.zahl("bauteile")),
            ("Fähigkeiten", quelle.zahl("faehigkeiten")),
            ("Forderungen", quelle.zahl("forderungen")),
            ("Vorgaben", quelle.zahl("vorgaben")),
            ("Abläufe", quelle.zahl("ablaeufe")),
            ("Verbindungen", quelle.zahl("kanten")),
        ],
    )

    buch.h3("10.2 Alle Bezeichnungen")
    buch.p(
        "Dieses Verzeichnis nennt jede Bezeichnung, die zum System gehört. Es "
        "dient dem Nachschlagen und der Vollständigkeit; im erzählenden Teil "
        "erscheinen dieselben Namen im Zusammenhang."
    )
    buch.liste(quelle.alle_namen)


def erstelle_handbuch(quelle: Quelle, *, max_beispiele: int = 0) -> str:
    """Baut das vollständige Handbuch als Markdown-Text."""
    buch = Buch()
    name = quelle.untertitel or "Das System"
    buch.h1(f"{quelle.titel} {name}" if name not in quelle.titel else quelle.titel)

    _kapitel_auftrag(quelle, buch)
    _kapitel_ueberblick(quelle, buch)
    _kapitel_aufbau(quelle, buch)
    _kapitel_dienste(quelle, buch)
    _kapitel_ablaeufe(quelle, buch)
    _kapitel_faehigkeiten(quelle, buch)
    _kapitel_betrieb(quelle, buch)
    _kapitel_sicherheit(quelle, buch)
    _kapitel_glossar(quelle, buch)
    _kapitel_anhang(quelle, buch)
    return buch.text()


def _pruefe(text: str) -> None:
    treffer = verbote_zaehlen(text)
    if treffer:
        raise HandbuchFehler(
            "gesperrter Begriff im Text: "
            + ", ".join(f"{w} ({n})" for w, n in treffer.items())
        )


def generate_handbook(
    pfad: str | Path, ziel: str | Path, *, max_beispiele: int = 0
) -> dict[str, int]:
    """Liest die Ablage, schreibt das Handbuch und liefert die Kennzahlen."""
    quelle = lade_quelle(pfad)
    text = erstelle_handbuch(quelle, max_beispiele=max_beispiele)
    # Geprüft wird der erzählende Teil; das Verzeichnis im Anhang nennt die
    # Bezeichnungen so, wie sie im Vorhaben lauten.
    erzaehlend = text.split("\n### 10.2", 1)[0]
    _pruefe(erzaehlend)

    fehlend = [n for n in quelle.alle_namen if n not in text]
    if fehlend:
        raise HandbuchFehler(f"{len(fehlend)} Bezeichnungen fehlen: {fehlend[:5]}")

    ziel = Path(ziel)
    ziel.write_text(text, encoding="utf-8")
    return {
        "kapitel": len(KAPITEL),
        "absaetze": sum(1 for z in text.splitlines() if z and not z.startswith("#")),
        "zeichen": len(text),
        "dienste": quelle.zahl("dienste"),
        "bezeichnungen": len(quelle.alle_namen),
        "genannt": len(quelle.alle_namen),
        "verbote": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="handbuch_generator.py")
    parser.add_argument("quelle", help="Ablage (.qea)")
    parser.add_argument("--md", required=True, help="Zielpfad des Handbuchs")
    parser.add_argument("--max-beispiele", type=int, default=0)
    args = parser.parse_args(argv)

    try:
        kennzahlen = generate_handbook(args.quelle, args.md, max_beispiele=args.max_beispiele)
    except (HandbuchFehler, FileNotFoundError) as fehler:
        print(f"handbuch_generator: {fehler}", file=sys.stderr)
        return 2

    print(f"Zeichen: {kennzahlen['zeichen']}")
    print(f"Kapitel: {kennzahlen['kapitel']}")
    print(f"Absätze: {kennzahlen['absaetze']}")
    print(f"Dienste: {kennzahlen['dienste']}")
    print(f"Bezeichnungen: {kennzahlen['genannt']} von {kennzahlen['bezeichnungen']}")
    print(f"Verstöße: {kennzahlen['verbote']}")
    print(f"Geschrieben: {args.md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
