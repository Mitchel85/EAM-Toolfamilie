"""Prozess-Extraktion aus deutschem Fliesstext -- regelbasiert und offline.

Der Extraktor liest Beschreibungen wie "Der Sachbearbeiter prueft den Antrag,
anschliessend erstellt er den Bescheid." und baut daraus ein BPMN-Modell nach
:mod:`bpmn.modell`. Er arbeitet ohne Netz, ohne Modell und ohne Zufall: gleiche
Eingabe, gleiches Ergebnis.

Erkannt werden

* **Schritte** -- Saetze oder Listenpunkte mit einer Handlung (Verb + Objekt),
* **Rollen** -- Subjekt eines Satzes oder Agens im Passiv ("vom Sachbearbeiter"),
* **Kontrollfluss** -- Reihenfolge, explizite Marker ("danach", "anschliessend")
  und Bedingungssaetze ("Wenn ..., dann ...").

Jedes erkannte Element traegt einen Sicherheitsgrad:

* ``sicher``   -- explizites Subjekt, konjugiertes Verb und Objekt im selben Satz
                  (oder Listenpunkt mit Verb und Objekt),
* ``unsicher`` -- Passiv ohne Agens, fehlendes Objekt, geerbte Rolle oder eine
                  aus der Reihenfolge abgeleitete Kante.

Der Sicherheitsgrad ist bewusst *kein* Freibrief: ``unsicher`` heisst "fachlich
pruefen", nicht "verwerfen". Die Zuordnung steht in :attr:`Extraktion.sicherheit`
je Element-ID und zusaetzlich als Begruendung in :attr:`Extraktion.begruendungen`.

Abgrenzung: Pools und Nachrichtenfluesse lassen sich aus Prosa nicht sicher
ableiten. Der Extraktor legt deshalb *einen* Pool mit einer Lane je handelnder
Rolle an. Wer Pools braucht, trennt sie anschliessend im Editor.

Die optionale KI-Unterstuetzung liegt in :mod:`bpmn.ki` und ist standardmaessig
aus. Dieses Modul hier ruft niemals ein Netz auf.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from . import layout
from . import modell as m

SICHER = "sicher"
UNSICHER = "unsicher"

#: Marker, die eine Reihenfolge ausdruecklich nennen.
SEQUENZ_MARKER = (
    "anschliessend",
    "anschließend",
    "danach",
    "daraufhin",
    "dann",
    "im anschluss",
    "im anschluss daran",
    "nachfolgend",
    "zunaechst",
    "zunächst",
    "zuerst",
    "als naechstes",
    "als nächstes",
    "in der folge",
    "hiernach",
)

#: Satzeinleitungen, die eine Bedingung ankuendigen.
BEDINGUNG_WOERTER = ("wenn", "falls", "sofern", "sobald")

#: Einleitungen eines Gegenfalls.
SONST_WOERTER = ("andernfalls", "sonst", "im anderen fall", "anderenfalls")

#: Abkuerzungen, deren Punkt keinen Satz beendet.
ABKUERZUNGEN = (
    "z. B.",
    "z.B.",
    "bzw.",
    "d. h.",
    "d.h.",
    "u. a.",
    "u.a.",
    "Dr.",
    "Nr.",
    "ca.",
    "vgl.",
    "etc.",
    "inkl.",
    "zzgl.",
    "sog.",
    "Abs.",
    "Art.",
)

#: Woerter, die eine Handlung ankuenden (Infinitive).
VERBEN: dict[str, tuple[str, ...]] = {
    "pruefen": ("prüft", "prüfen", "prüfte", "geprüft", "prüfe", "zu prüfen"),
    "erfassen": ("erfasst", "erfassen", "erfasste", "erfaßt"),
    "bearbeiten": ("bearbeitet", "bearbeiten", "bearbeitete"),
    "anlegen": ("anlegen", "angelegt", "legte an"),
    "senden": ("sendet", "senden", "sandte", "gesendet", "schickt", "schicken", "geschickt"),
    "uebermitteln": ("übermittelt", "übermitteln", "übermittelte"),
    "weiterleiten": ("weiterleiten", "weitergeleitet"),
    "empfangen": ("empfängt", "empfangen", "empfing"),
    "erhalten": ("erhält", "erhalten", "erhielt"),
    "entgegennehmen": ("entgegennehmen", "entgegengenommen"),
    "genehmigen": ("genehmigt", "genehmigen", "genehmigte"),
    "freigeben": ("freigeben", "freigegeben"),
    "ablehnen": ("ablehnen", "abgelehnt"),
    "entscheiden": ("entscheidet", "entscheiden", "entschied", "entschieden"),
    "buchen": ("bucht", "buchen", "buchte", "gebucht"),
    "zahlen": ("zahlt", "zahlen", "zahlte", "gezahlt"),
    "ausstellen": ("ausstellen", "ausgestellt"),
    "erstellen": ("erstellt", "erstellen", "erstellte"),
    "dokumentieren": ("dokumentiert", "dokumentieren", "dokumentierte"),
    "archivieren": ("archiviert", "archivieren", "archivierte"),
    "unterschreiben": ("unterschreibt", "unterschreiben", "unterschrieb", "unterschrieben"),
    "zeichnen": ("zeichnet", "zeichnen", "gezeichnet"),
    "melden": ("meldet", "melden", "gemeldet"),
    "beauftragen": ("beauftragt", "beauftragen", "beauftragte"),
    "liefern": ("liefert", "liefern", "lieferte", "geliefert"),
    "montieren": ("montiert", "montieren", "montierte"),
    "reparieren": ("repariert", "reparieren", "reparierte"),
    "warten": ("wartet", "warten", "wartete", "gewartet"),
    "bestellen": ("bestellt", "bestellen", "bestellte"),
    "versenden": ("versendet", "versenden", "versandt"),
    "kontrollieren": ("kontrolliert", "kontrollieren", "kontrollierte"),
    "berechnen": ("berechnet", "berechnen", "berechnete"),
    "stellen": ("stellt", "stellen", "stellte", "gestellt"),
    "ausfuellen": ("ausfüllt", "ausfüllen", "ausgefüllt"),
    "einreichen": ("einreichen", "eingereicht"),
    "beantragen": ("beantragt", "beantragen", "beantragte"),
    "vermerken": ("vermerkt", "vermerken", "vermerkte"),
    "protokollieren": ("protokolliert", "protokollieren", "protokollierte"),
    "klaeren": ("klärt", "klären", "klärte", "geklärt"),
    "abstimmen": ("abstimmen", "abgestimmt"),
    "uebergeben": ("übergibt", "übergeben", "übergab"),
    "uebernehmen": ("übernimmt", "übernehmen", "übernahm"),
    "hinterlegen": ("hinterlegt", "hinterlegen"),
    "loeschen": ("löscht", "löschen", "gelöscht"),
    "sperren": ("sperrt", "sperren", "gesperrt"),
    "aktivieren": ("aktiviert", "aktivieren", "aktivierte"),
    "deaktivieren": ("deaktiviert", "deaktivieren", "deaktivierte"),
    "installieren": ("installiert", "installieren", "installierte"),
    "konfigurieren": ("konfiguriert", "konfigurieren", "konfigurierte"),
    "informieren": ("informiert", "informieren", "informierte"),
    "benachrichtigen": ("benachrichtigt", "benachrichtigen", "benachrichtigte"),
    "anfordern": ("anfordern", "angefordert"),
    "anfragen": ("anfragen", "angefragt"),
    "zuweisen": ("zuweisen", "zugewiesen"),
    "abschliessen": ("abschliessen", "abgeschlossen"),
    "aufnehmen": ("aufnehmen", "aufgenommen"),
    "eintragen": ("eintragen", "eingetragen"),
    "festsetzen": ("festsetzen", "festgesetzt"),
    "abrufen": ("abrufen", "abgerufen"),
    "eingeben": ("eingeben", "eingegeben"),
    "abrechnen": ("abrechnen", "abgerechnet"),
}

#: Trennbare Verben: (konjugierte Form, Partikel) -> Infinitiv.
SEPARABEL: dict[tuple[str, str], str] = {
    ("legt", "an"): "anlegen",
    ("fuellt", "aus"): "ausfuellen",
    ("füllt", "aus"): "ausfuellen",
    ("reicht", "ein"): "einreichen",
    ("stellt", "aus"): "ausstellen",
    ("gibt", "frei"): "freigeben",
    ("schickt", "weiter"): "weiterleiten",
    ("nimmt", "entgegen"): "entgegennehmen",
    ("lehnt", "ab"): "ablehnen",
    ("ruft", "ab"): "abrufen",
    ("gibt", "ein"): "eingeben",
    ("rechnet", "ab"): "abrechnen",
    ("fordert", "an"): "anfordern",
    ("fragt", "an"): "anfragen",
    ("setzt", "fest"): "festsetzen",
    ("weist", "zu"): "zuweisen",
    ("schliesst", "ab"): "abschliessen",
    ("schließt", "ab"): "abschliessen",
    ("nimmt", "auf"): "aufnehmen",
    ("greift", "auf"): "aufgreifen",
    ("traegt", "ein"): "eintragen",
    ("trägt", "ein"): "eintragen",
    ("stimmt", "ab"): "abstimmen",
    ("meldet", "an"): "anmelden",
}

#: Form -> Infinitiv (aus :data:`VERBEN` abgeleitet).
FORMEN: dict[str, str] = {}
for _infinitiv, _formen in VERBEN.items():
    for _form in _formen:
        FORMEN[_form.lower()] = _infinitiv
# ASCII-Schreibweisen (pruefen statt prüfen) tolerieren -- Copy&Paste aus
# Werkzeugen, die Umlaute ersetzen, soll nicht zu stummen Fehlern fuehren.
_ASCII = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
for _form, _infinitiv in list(FORMEN.items()):
    FORMEN.setdefault(_form.translate(_ASCII), _infinitiv)

#: Hilfs- und Modalverben sind keine Handlung.
HILFSVERBEN = {
    "wird",
    "werden",
    "wurde",
    "wurden",
    "ist",
    "sind",
    "war",
    "waren",
    "hat",
    "haben",
    "hatte",
    "hatten",
    "muss",
    "müssen",
    "soll",
    "sollen",
    "kann",
    "können",
    "darf",
    "dürfen",
    "mag",
    "mögen",
    "will",
    "wollen",
}

#: Artikel und Determinierer, die vor einem Objekt stehen duerfen.
ARTIKEL = {
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "einen",
    "einem",
    "einer",
    "eines",
    "kein",
    "keine",
    "keinen",
    "keinem",
    "keiner",
    "ihren",
    "ihre",
    "ihrem",
    "seinen",
    "seine",
    "seinem",
    "denen",
}

#: Wo ein Objekt endet.
STOPPWOERTER = {
    "an",
    "am",
    "auf",
    "aus",
    "bei",
    "beim",
    "bis",
    "durch",
    "fuer",
    "für",
    "gegen",
    "im",
    "in",
    "mit",
    "nach",
    "ohne",
    "seit",
    "ueber",
    "über",
    "um",
    "unter",
    "vom",
    "von",
    "vor",
    "zu",
    "zum",
    "zur",
    "des",
    "deren",
    "dessen",
    "waehrend",
    "während",
}

#: Rollenlexikon (klein geschrieben). Weitere Rollen werden ueber Endungen erkannt.
ROLLEN: set[str] = {
    "antragsteller",
    "antragstellerin",
    "antragstellers",
    "sachbearbeiter",
    "sachbearbeiterin",
    "sachbearbeiters",
    "bearbeiter",
    "bearbeiterin",
    "mitarbeiter",
    "mitarbeiterin",
    "buchhaltung",
    "personalabteilung",
    "rechtsabteilung",
    "vertrieb",
    "einkauf",
    "disposition",
    "werkstatt",
    "techniker",
    "technikerin",
    "kunde",
    "kundin",
    "kunden",
    "lieferant",
    "lieferantin",
    "leasinggesellschaft",
    "leasingnehmer",
    "leasinggeber",
    "fahrzeugwerkstatt",
    "versicherung",
    "zulassungsstelle",
    "behoerde",
    "behörde",
    "bauamt",
    "ordnungsamt",
    "standesamt",
    "pruefstelle",
    "prüfstelle",
    "pruefer",
    "prüfer",
    "prueferin",
    "prüferin",
    "genehmigungsbehoerde",
    "genehmigungsbehörde",
    "antragsbearbeitung",
    "abteilung",
    "team",
    "leitung",
    "geschaeftsfuehrung",
    "geschäftsführung",
    "vorstand",
    "empfang",
    "lager",
    "logistik",
    "produktion",
    "qualitaetssicherung",
    "qualitätssicherung",
    "system",
    "fachanwendung",
    "helpdesk",
    "servicedesk",
    "servicecenter",
    "support",
    "kundenservice",
    "bank",
    "kasse",
    "poststelle",
    "hausverwaltung",
    "verwaltung",
    "amt",
    "referat",
    "dezernat",
}

ROLLEN_SUFFIXE = (
    "abteilung",
    "behoerde",
    "behörde",
    "gesellschaft",
    "verwaltung",
    "werkstatt",
    "service",
    "stelle",
    "zentrale",
    "kasse",
    "bank",
    "team",
    "amt",
)

#: Schreibvarianten auf eine Anzeigeform abbilden.
ROLLEN_KANONISCH = {
    "kunden": "Kunde",
    "sachbearbeiters": "Sachbearbeiter",
    "antragstellers": "Antragsteller",
    "behoerde": "Behörde",
    "pruefstelle": "Prüfstelle",
    "pruefer": "Prüfer",
    "prueferin": "Prüferin",
    "genehmigungsbehoerde": "Genehmigungsbehörde",
    "geschaeftsfuehrung": "Geschäftsführung",
    "qualitaetssicherung": "Qualitätssicherung",
}

#: Pronomen, die ein vorheriges Objekt aufgreifen.
SUBJEKT_PRONOMEN = {"er", "sie", "es", "wir", "ich"}
PRONOMEN_OBJEKT = {"ihn", "sie", "es", "ihm", "diesen", "diese", "dieses", "den", "die", "das"}

#: Verben, die eine Nachricht kennzeichnen.
SENDE_VERBEN = {"senden", "uebermitteln", "weiterleiten", "versenden", "informieren", "benachrichtigen"}
EMPFANGS_VERBEN = {"empfangen", "erhalten", "entgegennehmen"}

#: Rollen, die als System gelten und damit Service-Aufgaben ausloesen.
SYSTEM_ROLLEN = {"system", "fachanwendung", "helpdesk", "servicedesk", "servicecenter", "support"}


# --------------------------------------------------------------------------
# Ergebnisobjekte
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Schritt:
    """Ein erkannter Prozessschritt mit Herkunft und Sicherheitsgrad."""

    nummer: int
    rolle: str
    aktion: str
    objekt: str
    art: str
    bedingung: str
    herkunft: str
    sicherheit: str
    begruendung: str
    quelle: str = "satz"
    sonst: bool = False
    #: Reihenfolge im Text ausdruecklich genannt (Marker, Liste, Teilsatz)?
    explizite_folge: bool = False

    @property
    def name(self) -> str:
        """Aktionsname in der Form "Objekt Infinitiv" (ohne Artikel)."""
        objekt = self.objekt.strip()
        if objekt:
            return f"{objekt[0].upper() + objekt[1:]} {self.aktion}"
        return self.aktion[0].upper() + self.aktion[1:]

    def als_dict(self) -> dict[str, Any]:
        return {
            "nummer": self.nummer,
            "rolle": self.rolle,
            "aktion": self.aktion,
            "objekt": self.objekt,
            "name": self.name,
            "art": self.art,
            "bedingung": self.bedingung,
            "herkunft": self.herkunft,
            "sicherheit": self.sicherheit,
            "begruendung": self.begruendung,
            "quelle": self.quelle,
            "sonst": self.sonst,
            "explizite_folge": self.explizite_folge,
        }


@dataclass
class Extraktion:
    """Ergebnis eines Extraktionslaufs: Modell plus Belege."""

    modell: m.Modell
    schritte: list[Schritt] = field(default_factory=list)
    rollen: list[str] = field(default_factory=list)
    sicherheit: dict[str, str] = field(default_factory=dict)
    begruendungen: dict[str, str] = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)
    quelle: str = "regeln"

    def grad(self, element_id: str) -> str:
        return self.sicherheit.get(element_id, UNSICHER)

    def als_dict(self) -> dict[str, Any]:
        return {
            "quelle": self.quelle,
            "schritte": [s.als_dict() for s in self.schritte],
            "rollen": list(self.rollen),
            "sicherheit": dict(self.sicherheit),
            "begruendungen": dict(self.begruendungen),
            "hinweise": list(self.hinweise),
        }

    def texte(self) -> list[str]:
        """Kurze, menschenlesbare Zusammenfassung fuer die Kommandozeile."""
        zeilen = [f"{len(self.schritte)} Schritt(e), {len(self.rollen)} Rolle(n)"]
        for schritt in self.schritte:
            zeilen.append(
                f"  {schritt.nummer}. [{schritt.sicherheit}] {schritt.rolle or '—'}: {schritt.name}"
            )
        if self.hinweise:
            zeilen.extend(f"  Hinweis: {h}" for h in self.hinweise)
        return zeilen


# --------------------------------------------------------------------------
# Textzerlegung
# --------------------------------------------------------------------------


def _normalisiere(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[•·▪◦]", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _saetze(text: str) -> Iterator[tuple[str, bool]]:
    """Liefert (Satz, ist_listenpunkt) in Dokumentreihenfolge."""
    for rohzeile in _normalisiere(text).split("\n"):
        zeile = rohzeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        treffer = re.match(r"^(?:[-–—*]|\d+[.)])\s+(.*)$", zeile)
        if treffer:
            inhalt = treffer.group(1).strip()
            if inhalt:
                yield inhalt, True
            continue
        for satz in _teile_saetze(zeile):
            if satz:
                yield satz, False


def _teile_saetze(zeile: str) -> list[str]:
    geschuetzt = zeile
    for nummer, abkuerzung in enumerate(ABKUERZUNGEN):
        geschuetzt = geschuetzt.replace(abkuerzung, f"§{nummer}§")
    teile = re.split(r"(?<=[.!?])\s+|\s*;\s*", geschuetzt)
    ergebnis: list[str] = []
    for teil in teile:
        for nummer, abkuerzung in enumerate(ABKUERZUNGEN):
            teil = teil.replace(f"§{nummer}§", abkuerzung)
        teil = teil.strip()
        if teil:
            ergebnis.append(teil)
    return ergebnis


def _klauseln(satz: str) -> list[str]:
    """Teilt "A und B" nur, wenn beide Teile eine Handlung enthalten."""
    teile = re.split(r"\s+und\s+", satz)
    ergebnis: list[str] = []
    for teil in teile:
        teil = teil.strip()
        if not teil:
            continue
        if ergebnis and not _finde_verb(teil):
            ergebnis[-1] = f"{ergebnis[-1]} und {teil}"
        else:
            ergebnis.append(teil)
    return ergebnis or [satz]


def _woerter(satz: str) -> list[str]:
    return re.findall(r"[\wÄÖÜäöüß-]+", satz, flags=re.UNICODE)


def _finde_verb(satz: str) -> tuple[str, int, str] | None:
    """Erstes Handlungsverb als (Infinitiv, Wortindex, Oberflaeche)."""
    woerter = _woerter(satz)
    klein = [w.lower() for w in woerter]
    for index, wort in enumerate(klein):
        if wort in HILFSVERBEN or wort in {"zu", "nicht", "auch", "bereits"}:
            continue
        if wort in FORMEN:
            return FORMEN[wort], index, woerter[index]
        for (form, partikel), infinitiv in SEPARABEL.items():
            if wort != form:
                continue
            for abstand in range(1, 6):
                if index + abstand >= len(klein):
                    break
                if klein[index + abstand] == partikel:
                    return infinitiv, index, f"{woerter[index]} ... {woerter[index + abstand]}"
    return None


def _hat_verb(satz: str) -> bool:
    return _finde_verb(satz) is not None


def _ist_rolle(wort: str) -> bool:
    klein = wort.lower()
    if klein in ROLLEN:
        return True
    if len(klein) >= 6 and klein.endswith(ROLLEN_SUFFIXE):
        return True
    return False


def _rolle_anzeige(wort: str) -> str:
    klein = wort.lower()
    if klein in ROLLEN_KANONISCH:
        return ROLLEN_KANONISCH[klein]
    return wort[0].upper() + wort[1:]


def _rolle_im_satz(satz: str) -> tuple[str, bool]:
    """Rolle und ob sie ausdruecklich im selben Satz steht.

    Reihenfolge der Muster: Subjekt am Satzanfang, Subjekt nach dem Verb
    (Inversion), Agens im Passiv ("von/vom/durch"), sonstige Artikelphrase.
    """
    # 1. Subjekt am Anfang: "Der Sachbearbeiter prueft ..."
    treffer = re.match(
        r"^(?:Der|Die|Das|Ein|Eine)\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]*)", satz
    )
    if treffer and _ist_rolle(treffer.group(1)):
        return _rolle_anzeige(treffer.group(1)), True

    # 2. Subjekt nach dem Verb: "prueft der Techniker die Anlage"
    #    Nur Nominativ (der/die/das); "den Antragsteller" ist Empfaenger, nicht Agens.
    for treffer in re.finditer(
        r"\b(?:der|die|das)\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]*)", satz
    ):
        if _ist_rolle(treffer.group(1)):
            return _rolle_anzeige(treffer.group(1)), True

    # 3. Agens im Passiv: "vom Sachbearbeiter", "durch die Buchhaltung"
    for treffer in re.finditer(
        r"\b(?:von|vom|durch)\s+(?:der|die|dem|den)?\s*([A-ZÄÖÜ][\wÄÖÜäöüß-]*)",
        satz,
    ):
        if _ist_rolle(treffer.group(1)):
            return _rolle_anzeige(treffer.group(1)), True

    return "", False


def _rolle_als_empfaenger(satz: str) -> str:
    """Rolle in einer Praepositionsphrase, auch wenn sie nicht handelt."""
    for treffer in re.finditer(
        r"\b(?:an|an den|an die|an das|beim|bei|zur|zum)\s+"
        r"(?:der|die|dem|den)?\s*([A-ZÄÖÜ][\wÄÖÜäöüß-]*)",
        satz,
    ):
        if _ist_rolle(treffer.group(1)):
            return _rolle_anzeige(treffer.group(1))
    return ""


def _bedingung(satz: str) -> tuple[str, str, bool]:
    """Zerlegt "Wenn X, dann Y" in (Bedingung, Hauptsatz, war_bedingung)."""
    treffer = re.match(
        r"^(Wenn|Falls|Sofern|Sobald)\s+(.+?),\s*(?:dann\s+)?(.+)$", satz, re.IGNORECASE
    )
    if treffer:
        return treffer.group(2).strip(), treffer.group(3).strip(), True
    return "", satz, False


def _ist_sonst(satz: str) -> bool:
    return bool(re.match(r"^(?:Andernfalls|Sonst|Im anderen Fall|Anderenfalls)\b", satz, re.I))


def _objekt(
    satz: str, verb_index: int, passive: bool = False, rolle: str = ""
) -> str:
    """Objektphrase nach dem Verb (oder Subjekt im Passiv).

    In Inversionssaetzen ("prueft der Techniker die Anlage") steht das Subjekt
    zwischen Verb und Objekt; es wird anhand der erkannten Rolle uebersprungen.
    """
    woerter = _woerter(satz)
    klein = [w.lower() for w in woerter]
    rollen_teile = [t.lower() for t in _woerter(rolle)] if rolle else []

    if passive:
        # "Der Antrag wird geprueft." -> Objekt ist das Subjekt vor "wird".
        for index, wort in enumerate(klein):
            if wort in {"wird", "werden", "wurde", "wurden"}:
                kandidat = _phrase_vor(woerter, index)
                if kandidat:
                    return kandidat
                break

    # "ist zu pruefen" / "sind zu pruefen"
    if verb_index >= 1 and klein[verb_index - 1] in {"zu", "zum"}:
        for index, wort in enumerate(klein):
            if wort in {"ist", "sind"}:
                kandidat = _phrase_vor(woerter, index)
                if kandidat:
                    return kandidat
                break

    start = verb_index + 1
    # Inversionssatz: "Danach sendet sie die Rechnung." Das Pronomen ist das
    # Subjekt, nicht das Objekt -- aber nur ueberspringen, wenn danach noch
    # Inhalt folgt ("prueft sie" bleibt ohne Objekt).
    # Nur ueberspringen, wenn danach eine Objektphrase mit Artikel folgt.
    # "sendet es an den Kunden" behaelt "es": das Pronomen ist das Objekt.
    if (
        start + 1 < len(klein)
        and klein[start] in SUBJEKT_PRONOMEN
        and klein[start + 1] in ARTIKEL
    ):
        start += 1
    # Artikel und ein eingeschobenes Subjekt ueberspringen.
    weitergesucht = True
    while weitergesucht and start < len(klein):
        weitergesucht = False
        while start < len(klein) and klein[start] in ARTIKEL:
            start += 1
            weitergesucht = True
        if rollen_teile and klein[start : start + len(rollen_teile)] == rollen_teile:
            start += len(rollen_teile)
            weitergesucht = True

    ende = start
    while ende < len(klein) and klein[ende] not in STOPPWOERTER:
        if klein[ende] in {"und", "oder", "sowie"}:
            break
        if klein[ende] in {
            "anschliessend",
            "anschließend",
            "danach",
            "daraufhin",
            "dann",
            "zunaechst",
            "zunächst",
            "zuerst",
            "hiernach",
        }:
            break
        ende += 1
    kandidat = " ".join(woerter[start:ende]).strip(" ,.;:!?")

    # Imperativ/Infinitiv am Satzende: "Antrag erfassen" -> Objekt steht davor.
    if not kandidat and verb_index == len(woerter) - 1:
        kandidat = _phrase_vor(woerter, verb_index)

    # "entscheidet ueber den Antrag": Objekt steht hinter einer Praeposition.
    if not kandidat and start < len(klein) and klein[start] in {
        "ueber",
        "über",
        "zu",
        "zum",
        "zur",
        "fuer",
        "für",
        "auf",
        "gegen",
    }:
        ende = start + 1
        while ende < len(klein) and klein[ende] in ARTIKEL:
            ende += 1
        beginn = ende
        while ende < len(klein) and klein[ende] not in STOPPWOERTER:
            ende += 1
        kandidat = " ".join(woerter[beginn:ende]).strip(" ,.;:!?")

    return kandidat


def _phrase_vor(woerter: list[str], ende: int) -> str:
    """Nominalphrase unmittelbar vor einem Index, Artikel entfernt."""
    beginn = ende
    while beginn > 0 and woerter[beginn - 1].lower() not in ARTIKEL:
        beginn -= 1
    if beginn >= ende:
        return ""
    return " ".join(woerter[beginn:ende]).strip(" ,.;:!?")


# --------------------------------------------------------------------------
# Schritt-Erkennung
# --------------------------------------------------------------------------


def _art_fuer(aktion: str, rolle: str) -> str:
    if aktion in SENDE_VERBEN:
        return "send_task"
    if aktion in EMPFANGS_VERBEN:
        return "receive_task"
    if rolle.lower() in SYSTEM_ROLLEN:
        return "service_task"
    return "user_task"


def _schritt_aus_satz(
    satz: str,
    nummer: int,
    *,
    liste: bool,
    letzte_rolle: str,
    letztes_objekt: str,
    quelle: str = "satz",
    folgeklausel: bool = False,
    explizite_folge: bool = False,
) -> tuple[Schritt | None, str]:
    """Baut einen Schritt aus einem Satz. Rueckgabe: (Schritt, geerbte Rolle)."""
    bedingung, hauptsatz, war_bedingung = _bedingung(satz)
    sonst = _ist_sonst(hauptsatz)
    if sonst:
        hauptsatz = re.sub(
            r"^(?:Andernfalls|Sonst|Im anderen Fall|Anderenfalls)[,\s]+", "", hauptsatz, flags=re.I
        )

    verb = _finde_verb(hauptsatz)
    if verb is None:
        # Listenpunkte ohne Verb sind trotzdem Schritte -- aber unsicher.
        if liste and hauptsatz.strip():
            rolle, rolle_sicher = _rolle_im_satz(hauptsatz)
            if not rolle:
                rolle, rolle_sicher = letzte_rolle, False
            return (
                Schritt(
                    nummer=nummer,
                    rolle=rolle,
                    aktion="bearbeiten",
                    objekt=hauptsatz.strip(" .;:!?"),
                    art="user_task",
                    bedingung=bedingung,
                    herkunft=satz,
                    sicherheit=UNSICHER,
                    begruendung="Listenpunkt ohne erkennbares Handlungsverb",
                    quelle="liste",
                    sonst=sonst,
                    explizite_folge=True,
                ),
                rolle,
            )
        return None, letzte_rolle

    aktion, verb_index, form = verb
    rolle, rolle_sicher = _rolle_im_satz(hauptsatz)
    geerbte_rolle = False
    pronomen = ""
    if not rolle and letzte_rolle:
        rolle = letzte_rolle
        geerbte_rolle = True
        treffer = re.search(r"\b(er|sie|es)\b", hauptsatz, re.I)
        pronomen = treffer.group(1).lower() if treffer else ""
        # Innerhalb desselben Satzes traegt das Subjekt weiter (Koordination);
        # ueber die Satzgrenze hinweg ist es eine Annahme.
        rolle_sicher = folgeklausel

    passive = bool(
        re.search(r"\b(?:wird|werden|wurde|wurden)\b", hauptsatz, re.I)
        or re.search(r"\b(?:ist|sind)\s+zu\s+\w+", hauptsatz, re.I)
    )
    objekt = _objekt(hauptsatz, verb_index, passive=passive, rolle=rolle)
    if objekt.lower() in PRONOMEN_OBJEKT and letztes_objekt:
        objekt = letztes_objekt

    if not objekt:
        sicherheit = UNSICHER
        begruendung = f"Verb '{form}' erkannt, aber kein Objekt"
    elif passive and not rolle:
        sicherheit = UNSICHER
        begruendung = f"Passiv ohne Agens: Verb '{form}', Objekt '{objekt}'"
    elif geerbte_rolle and not rolle_sicher:
        sicherheit = UNSICHER
        begruendung = (
            f"Rolle '{rolle}' ueber Pronomen '{pronomen}' aus dem vorigen Satz geerbt"
            if pronomen
            else f"Rolle '{rolle}' aus dem vorigen Satz geerbt"
        )
    elif rolle_sicher:
        sicherheit = SICHER
        begruendung = (
            f"Rolle '{rolle}' aus dem vorigen Teilsatz, Verb '{form}', Objekt '{objekt}'"
            if geerbte_rolle
            else f"Rolle '{rolle}', Verb '{form}', Objekt '{objekt}'"
        )
    elif not rolle:
        # Der Schritt selbst ist explizit (Verb + Objekt); die Rolle fehlt und
        # wird als eigenes Element (Lane) mit "unsicher" gefuehrt.
        sicherheit = SICHER
        begruendung = f"Verb '{form}' mit Objekt '{objekt}', Rolle nicht genannt"
    else:
        sicherheit = UNSICHER
        begruendung = f"Verb '{form}' mit Objekt '{objekt}', Rolle nur erschlossen"

    if war_bedingung and not bedingung:
        bedingung = "Bedingung"

    return (
        Schritt(
            nummer=nummer,
            rolle=rolle,
            aktion=aktion,
            objekt=objekt,
            art=_art_fuer(aktion, rolle),
            bedingung=bedingung,
            herkunft=satz,
            sicherheit=sicherheit,
            begruendung=begruendung,
            quelle="liste" if liste else quelle,
            sonst=sonst,
            explizite_folge=explizite_folge,
        ),
        rolle,
    )


def _beginnt_mit_marker(satz: str) -> bool:
    klein = satz.strip().lower()
    return any(marker in klein for marker in SEQUENZ_MARKER)


def erkenne_schritte(text: str) -> list[Schritt]:
    """Alle Prozessschritte in Dokumentreihenfolge."""
    schritte: list[Schritt] = []
    letzte_rolle = ""
    letztes_objekt = ""
    for satz, liste in _saetze(text):
        marker = liste or _beginnt_mit_marker(satz)
        for position, klausel in enumerate(_klauseln(satz)):
            schritt, rolle = _schritt_aus_satz(
                klausel,
                len(schritte) + 1,
                liste=liste,
                letzte_rolle=letzte_rolle,
                letztes_objekt=letztes_objekt,
                quelle="liste" if liste else "satz",
                folgeklausel=position > 0,
                explizite_folge=marker or position > 0,
            )
            if schritt is None:
                continue
            schritte.append(schritt)
            if rolle:
                letzte_rolle = rolle
            if schritt.objekt:
                letztes_objekt = schritt.objekt
    return schritte


def erkenne_rollen(text: str, schritte: Iterable[Schritt] | None = None) -> list[str]:
    """Alle Rollen in Reihenfolge des ersten Auftretens."""
    gesehen: set[str] = set()
    ergebnis: list[str] = []

    def merke(name: str) -> None:
        if name and name.lower() not in gesehen:
            gesehen.add(name.lower())
            ergebnis.append(name)

    for schritt in schritte if schritte is not None else erkenne_schritte(text):
        merke(schritt.rolle)
    for satz, _ in _saetze(text):
        merke(_rolle_als_empfaenger(satz))
    return ergebnis


# --------------------------------------------------------------------------
# Modellbau
# --------------------------------------------------------------------------


def _slug(text: str) -> str:
    ersatz = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
    }
    for alt, neu in ersatz.items():
        text = text.replace(alt, neu)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text or "Element"


def _eindeutig(name: str, verwendet: set[str]) -> str:
    name = name.strip() or "Ohne Namen"
    if name not in verwendet:
        verwendet.add(name)
        return name
    zaehler = 2
    while f"{name} ({zaehler})" in verwendet:
        zaehler += 1
    neu = f"{name} ({zaehler})"
    verwendet.add(neu)
    return neu


def baue_modell(
    schritte: Iterable[Schritt | dict[str, Any]],
    prozess_name: str = "Extrahierter Prozess",
    *,
    quelle: str = "regeln",
    hinweise: Iterable[str] | None = None,
) -> Extraktion:
    """Baut aus Schritten ein BPMN-Modell mit Pool, Lanes und Kontrollfluss."""
    schritt_liste = [
        s if isinstance(s, Schritt) else _schritt_aus_dict(s) for s in schritte
    ]
    modell = m.Modell(id="Definitions_1", name=prozess_name)
    modell.ziel_namespace = "https://eam-platform.local/bpmn"
    prozess = modell.neuer_prozess(prozess_name, "Process_1")

    modell.kollaboration = m.Kollaboration(id="Collaboration_1", name=prozess_name)
    pool = m.Teilnehmer(
        id="Participant_1",
        name=prozess_name,
        prozess_ref=prozess.id,
        typ="OperationalArchitecture",
    )
    modell.kollaboration.teilnehmer.append(pool)

    lane_set = m.LaneSet(id="LaneSet_1")
    prozess.lane_sets.append(lane_set)
    lanes: dict[str, m.Lane] = {}
    verwendete_lane_namen: set[str] = set()
    for schritt in schritt_liste:
        rolle = schritt.rolle or "Bearbeitung"
        if rolle not in lanes:
            lane_name = _eindeutig(rolle, verwendete_lane_namen)
            lane = m.Lane(
                id=f"Lane_{len(lanes) + 1}",
                name=lane_name,
                performer=f"OperationalPerformer_{_slug(lane_name)}",
            )
            lane_set.lanes.append(lane)
            lanes[rolle] = lane

    start = modell.neuer_knoten("start_event", f"{prozess_name} gestartet", prozess)
    start.ereignis_rolle = "trigger"
    ende = modell.neuer_knoten("end_event", f"{prozess_name} abgeschlossen", prozess)
    ende.ereignis_rolle = "ergebnis"
    standard_lane = lane_set.lanes[0] if lane_set.lanes else None
    if standard_lane is not None:
        standard_lane.knoten.extend([start.id, ende.id])

    sicherheit: dict[str, str] = {}
    begruendungen: dict[str, str] = {}
    sicherheit[start.id] = UNSICHER
    begruendungen[start.id] = "Startereignis aus dem Text abgeleitet (nicht explizit genannt)"
    sicherheit[ende.id] = UNSICHER
    begruendungen[ende.id] = "Endereignis aus dem Text abgeleitet (nicht explizit genannt)"

    for rolle, lane in lanes.items():
        sicherheit[lane.id] = SICHER if any(s.rolle == rolle for s in schritt_liste) else UNSICHER
        begruendungen[lane.id] = f"Rolle '{rolle}' aus dem Text"

    daten: dict[str, m.Datenobjekt] = {}
    knoten_ids: list[str] = []
    letzter: str = start.id
    offene_verzweigung: tuple[str, str] | None = None
    vorherige_position = -1

    def ordne_lane(knoten: m.Knoten, rolle: str = "") -> None:
        lane = lanes.get(rolle) or (standard_lane if standard_lane is not None else None)
        if lane is not None and knoten.id not in lane.knoten:
            lane.knoten.append(knoten.id)

    def fluss(quelle: str, ziel: str, *, bedingung: str = "", sicher: bool = True) -> m.Fluss:
        f = modell.neuer_fluss("sequence_flow", quelle, ziel, prozess=prozess)
        f.bedingung = bedingung
        sicherheit[f.id] = SICHER if sicher else UNSICHER
        begruendungen[f.id] = (
            "explizite Reihenfolge im Text" if sicher else "Reihenfolge aus der Textfolge abgeleitet"
        )
        return f

    for schritt in schritt_liste:
        if schritt.sonst and offene_verzweigung is not None:
            split_id, merge_id = offene_verzweigung
            knoten = _neuer_schrittknoten(modell, prozess, schritt, lanes)
            fluss(split_id, knoten.id, bedingung="andernfalls", sicher=True)
            fluss(knoten.id, merge_id, sicher=True)
            sicherheit[knoten.id] = schritt.sicherheit
            begruendungen[knoten.id] = schritt.begruendung
            knoten_ids.append(knoten.id)
            letzter = merge_id
            offene_verzweigung = None
            continue

        if schritt.bedingung:
            split = modell.neuer_knoten(
                "exclusive_gateway", f"Bedingung: {schritt.bedingung}", prozess
            )
            merge = modell.neuer_knoten("exclusive_gateway", "Zusammenfuehrung", prozess)
            ordne_lane(split, schritt.rolle)
            ordne_lane(merge, schritt.rolle)
            sicherheit[split.id] = SICHER
            begruendungen[split.id] = f"Bedingungssatz '{schritt.bedingung}' erkannt"
            sicherheit[merge.id] = UNSICHER
            begruendungen[merge.id] = "Zusammenfuehrung fuer die Verzweigung eingefuegt"

            fluss(letzter, split.id, sicher=schritt.explizite_folge)
            knoten = _neuer_schrittknoten(modell, prozess, schritt, lanes)
            fluss(split.id, knoten.id, bedingung=schritt.bedingung, sicher=True)
            fluss(split.id, merge.id, sicher=False)
            fluss(knoten.id, merge.id, sicher=True)
            sicherheit[knoten.id] = schritt.sicherheit
            begruendungen[knoten.id] = schritt.begruendung
            knoten_ids.append(knoten.id)
            letzter = merge.id
            offene_verzweigung = (split.id, merge.id)
        else:
            knoten = _neuer_schrittknoten(modell, prozess, schritt, lanes)
            fluss(letzter, knoten.id, sicher=schritt.explizite_folge)
            sicherheit[knoten.id] = schritt.sicherheit
            begruendungen[knoten.id] = schritt.begruendung
            knoten_ids.append(knoten.id)
            letzter = knoten.id
            offene_verzweigung = None
        vorherige_position += 1

    fluss(letzter, ende.id, sicher=vorherige_position >= 0)

    # Conveyed Items: je Objekt ein Datenobjekt, an den Schrittfluss gehaengt.
    for schritt, knoten_id in zip(schritt_liste, knoten_ids):
        if not schritt.objekt:
            continue
        schluessel = schritt.objekt.lower()
        if schluessel not in daten:
            daten[schluessel] = modell.neues_datenobjekt(schritt.objekt, prozess=prozess)
            sicherheit[daten[schluessel].id] = schritt.sicherheit
            begruendungen[daten[schluessel].id] = f"Objekt '{schritt.objekt}' aus dem Schritt"
        daten_id = daten[schluessel].id
        for kante in list(modell.fluesse.values()):
            if kante.art != "sequence_flow":
                continue
            if knoten_id not in (kante.quelle, kante.ziel):
                continue
            # Doppelte Assoziationen (gleiches Objekt, gleiche Kante) vermeiden.
            schon_da = any(
                a.art == "association"
                and ((a.quelle == daten_id and a.ziel == kante.id) or (a.ziel == daten_id and a.quelle == kante.id))
                for a in modell.fluesse.values()
            )
            if not schon_da:
                modell.assoziiere(daten_id, kante.id, prozess=prozess)

    layout.verteile(modell)

    hinweis_liste = list(hinweise or [])
    if not schritt_liste:
        hinweis_liste.append("Kein Prozessschritt erkannt -- Text pruefen oder KI-Adapter einsetzen.")
    hinweis_liste.append(
        "Rollen werden als Lanes in einem Pool modelliert; Pools und Nachrichtenfluesse "
        "sind aus Prosa nicht sicher ableitbar."
    )
    hinweis_liste.append(
        "Sicherheitsgrad 'unsicher' bedeutet: fachlich pruefen, nicht automatisch verwerfen."
    )

    return Extraktion(
        modell=modell,
        schritte=schritt_liste,
        rollen=[lane.name for lane in lane_set.lanes],
        sicherheit=sicherheit,
        begruendungen=begruendungen,
        hinweise=hinweis_liste,
        quelle=quelle,
    )


def _schritt_aus_dict(daten: dict[str, Any]) -> Schritt:
    """Nimmt die Struktur des KI-Adapters auf, ohne sie zu vertrauen."""
    return Schritt(
        nummer=int(daten.get("nummer") or 0),
        rolle=str(daten.get("rolle") or "").strip(),
        aktion=str(daten.get("aktion") or "bearbeiten").strip().lower(),
        objekt=str(daten.get("objekt") or "").strip(),
        art=str(daten.get("art") or "user_task").strip() or "user_task",
        bedingung=str(daten.get("bedingung") or "").strip(),
        herkunft=str(daten.get("herkunft") or "").strip(),
        sicherheit=str(daten.get("sicherheit") or UNSICHER).strip(),
        begruendung=str(daten.get("begruendung") or "Angabe des KI-Adapters").strip(),
        quelle=str(daten.get("quelle") or "ki").strip(),
        sonst=bool(daten.get("sonst")),
        explizite_folge=bool(daten.get("explizite_folge", True)),
    )


def _neuer_schrittknoten(
    modell: m.Modell, prozess: m.Prozess, schritt: Schritt, lanes: dict[str, m.Lane]
) -> m.Knoten:
    name = schritt.name
    if not name:
        name = "Aktion (benennen)"
    knoten = modell.neuer_knoten(schritt.art, name, prozess)
    knoten.stereotype = "OperationalActivityAction"
    rolle = schritt.rolle or "Bearbeitung"
    lane = lanes.get(rolle) or next(iter(lanes.values()))
    lane.knoten.append(knoten.id)
    return knoten


# --------------------------------------------------------------------------
# Oeffentliche Kurzform
# --------------------------------------------------------------------------


def extrahiere(
    text: str,
    prozess_name: str | None = None,
    anweisung: str | None = None,
) -> Extraktion:
    """Regelbasierte Extraktion: Text hinein, Modell plus Sicherheitsgrade heraus.

    ``anweisung`` ist der Auftrag in eigenen Worten, etwa "anbei Handbuch,
    extrahiere den Prozess Rechnungslauf". Genannt der Auftrag einen Prozess,
    wird dieser Abschnitt aus dem Dokument geschnitten; ohne Treffer bleibt der
    ganze Text die Grundlage. Die Entscheidung steht danach in ``hinweise``.
    """
    if not isinstance(text, str):
        raise TypeError("text muss eine Zeichenkette sein")
    hinweise: list[str] = []
    arbeits_text = text
    if anweisung:
        gesucht = _prozessname_aus_anweisung(anweisung)
        if gesucht:
            prozess_name = prozess_name or gesucht
            abschnitt = _abschnitt_waehlen(text, gesucht)
            if abschnitt is not None:
                arbeits_text, zeilen = abschnitt
                hinweise.append(
                    f'Auftrag: Abschnitt "{gesucht}" gewaehlt ({zeilen} Zeilen); '
                    "der uebrige Text wurde nicht ausgewertet."
                )
            else:
                hinweise.append(
                    f'Auftrag nennt "{gesucht}", im Text aber kein passender '
                    "Abschnitt gefunden -- ganzer Text ausgewertet."
                )
        elif anweisung.strip():
            hinweise.append("Auftrag ohne Prozessnamen -- ganzer Text ausgewertet.")
    schritte = erkenne_schritte(arbeits_text)
    name = prozess_name or _prozessname_aus_text(arbeits_text)
    ergebnis = baue_modell(schritte, name, hinweise=hinweise)
    ergebnis.rollen = erkenne_rollen(arbeits_text, schritte)
    return ergebnis


def _prozessname_aus_anweisung(anweisung: str) -> str:
    """Prozessnamen aus einem Auftragssatz ziehen.

    Erkannt werden Anfuehrungszeichen und die Formen "Prozess X",
    "Vorgang X", "Verfahren X". Ohne solchen Hinweis bleibt es leer.
    """
    text = anweisung.strip()
    for muster in (
        r'[\"„“\']([^\"“”\']{3,80})[\"“”\']',
        r"\b(?:prozess|vorgang|verfahren)\s+([A-Za-zÄÖÜäöüß0-9][\w\-äöüß ]{2,60})",
    ):
        treffer = re.search(muster, text, re.IGNORECASE)
        if treffer:
            name = treffer.group(1).strip(" .,;:-")
            name = re.split(r"\s+(?:aus|auszugsweise|bitte|und|sowie)\b", name, maxsplit=1)[0]
            if len(name) >= 3:
                return name.strip()
    return ""


def _abschnitt_waehlen(text: str, name: str) -> tuple[str, int] | None:
    """Schneidet den Abschnitt, dessen Ueberschrift den Namen traegt.

    Eine Ueberschrift ist eine kurze Zeile ohne Satzende. Der Abschnitt reicht
    bis zur naechsten Ueberschrift derselben Ebene -- angenaehert ueber die
    Zeilenlaenge, weil Dokumente selten saubere Ebenen mitbringen.
    """
    zeilen = _normalisiere(text).split("\n")
    klein = name.casefold()
    for i, zeile in enumerate(zeilen):
        roh = zeile.strip().strip("#*=-–— ")
        if nicht_ueberschrift(roh) or klein not in roh.casefold():
            continue
        grenze = _naechste_ueberschrift(zeilen, i, len(roh))
        block = [z for z in zeilen[i:grenze] if z.strip()]
        if len(block) >= 2:
            return "\n".join(block), len(block)
    return None


def nicht_ueberschrift(zeile: str) -> bool:
    """Kurze Zeile ohne Satzende gilt als Ueberschrift."""
    return not zeile or len(zeile) > 90 or zeile.endswith((".", "!", "?", ";"))


def _naechste_ueberschrift(zeilen: list[str], start: int, laenge: int) -> int:
    for j in range(start + 1, len(zeilen)):
        roh = zeilen[j].strip().strip("#*=-–— ")
        if not nicht_ueberschrift(roh):
            continue
        # Aehnliche Laenge spricht fuer dieselbe Ebene; sehr lange Zeilen sind Text.
        if abs(len(roh) - laenge) <= max(25, laenge // 2):
            return j
    return len(zeilen)


def _prozessname_aus_text(text: str) -> str:
    """Erste kurze Zeile ohne Satzende als Prozessname, sonst ein neutraler Name."""
    for zeile in _normalisiere(text).split("\n"):
        zeile = zeile.strip(" #*-–—")
        if not zeile or zeile.endswith((".", "!", "?", ";", ":")):
            continue
        if 3 <= len(zeile) <= 80:
            return zeile
    return "Extrahierter Prozess"


def main(argv: list[str] | None = None) -> int:
    """Kleine Kommandozeile: ``python -m bpmn.extraktion text.txt --name X --xml out.bpmn``."""
    import argparse
    import sys
    from pathlib import Path

    from . import bpmn_xml

    parser = argparse.ArgumentParser(description="Prozess aus Fliesstext extrahieren.")
    parser.add_argument("quelle", help="Textdatei (UTF-8)")
    parser.add_argument("--name", default="", help="Prozessname")
    parser.add_argument("--xml", default="", help="Zielpfad fuer BPMN-XML")
    parser.add_argument("--json", default="", help="Zielpfad fuer die Extraktionsbelege")
    args = parser.parse_args(argv)

    text = Path(args.quelle).read_text(encoding="utf-8")
    ergebnis = extrahiere(text, args.name or None)
    if args.xml:
        bpmn_xml.schreibe(ergebnis.modell, args.xml)
    if args.json:
        import json

        Path(args.json).write_text(
            json.dumps(ergebnis.als_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print("\n".join(ergebnis.texte()))
    return 0 if ergebnis.schritte else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
