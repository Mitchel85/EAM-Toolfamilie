"""Optionaler KI-Adapter fuer die Prosa-Extraktion -- standardmaessig AUS.

Der Adapter spricht die OpenAI-kompatible Chat-Schnittstelle (``/chat/completions``)
und ist ausschliesslich ueber Umgebungsvariablen konfigurierbar:

===================  =========================================================
Variable             Bedeutung
===================  =========================================================
BPMN_KI_AKTIV        ``1``/``true``/``ja``/``on`` schaltet den Adapter ein
BPMN_KI_BASIS_URL    Basis-URL, z. B. ``https://api.example.invalid/v1``
BPMN_KI_MODELL       Modellname beim Anbieter
BPMN_KI_KEY          Schluessel; fehlt er in der Umgebung, wird ``.env`` gelesen
BPMN_KI_TIMEOUT      Zeitlimit in Sekunden (Standard 60)
===================  =========================================================

Gesucht wird ``.env`` in der Repo-Wurzel, im Arbeitsverzeichnis und unter
``~/.hermes/.env``. Es werden nur die ``BPMN_KI_*``-Werte uebernommen; bereits
gesetzte Umgebungsvariablen haben Vorrang. Der Schluessel erscheint niemals in
einer Ausgabe, einem Protokoll oder einer Fehlermeldung -- :func:`status` meldet
nur ``gesetzt`` oder ``fehlt``.

**Datenschutz (verbindlich):** An den konfigurierten Endpunkt duerfen keine
dienstlichen, vertraulichen oder personenbezogenen Daten gehen. Der Adapter
prueft den Text vor dem Versand auf E-Mail-Adressen, Telefonnummern, IBANs und
Kennzeichnungen wie "VS-NfD" oder "Nur fuer den Dienstgebrauch" und bricht bei
einem Treffer ab (:class:`KIDatenschutz`). Diese Heuristik ersetzt keine
Freigabe: Wer dienstliche Inhalte verarbeitet, nutzt den regelbasierten
Extraktor in :mod:`bpmn.extraktion` oder einen freigegebenen lokalen Dienst.

Ohne vollstaendige Konfiguration schaltet der Adapter *nicht* still auf die
Regeln um, sondern wirft :class:`KINichtKonfiguriert`. So ist im Aufrufer
eindeutig, woher ein Ergebnis stammt.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from . import extraktion

TRUE_WERTE = {"1", "true", "ja", "on", "yes", "an"}

#: Variablen, die der Adapter liest.
ENV_AKTIV = "BPMN_KI_AKTIV"
ENV_BASIS_URL = "BPMN_KI_BASIS_URL"
ENV_MODELL = "BPMN_KI_MODELL"
ENV_KEY = "BPMN_KI_KEY"
ENV_TIMEOUT = "BPMN_KI_TIMEOUT"

#: Nur diese Praefixe werden aus ``.env`` uebernommen.
ENV_PRAEFIX = "BPMN_KI_"

STANDARD_TIMEOUT = 60.0

#: Heuristik fuer Daten, die nicht an einen externen Endpunkt gehoeren.
DATENSCHUTZ_MUSTER: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("E-Mail-Adresse", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    (
        "Telefonnummer",
        re.compile(r"(?<!\d)(?:\+49|0049|0)[\s/()-]*\d(?:[\s/()-]*\d){6,}(?!\d)"),
    ),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[\s]?[A-Z0-9]{4}){3,7}[\s]?[A-Z0-9]{0,4}\b")),
    (
        "Verschlusssachen-Kennzeichnung",
        re.compile(r"\b(?:VS-NfD|VS-NUR FÜR DEN DIENSTGEBRAUCH|Verschlusssache)\b", re.I),
    ),
    (
        "Dienstgebrauch-Kennzeichnung",
        re.compile(r"\b(?:Nur für den Dienstgebrauch|Nur fuer den Dienstgebrauch)\b", re.I),
    ),
)


class KIError(RuntimeError):
    """Oberklasse aller Adapterfehler."""


class KINichtKonfiguriert(KIError):
    """Der Adapter ist aus oder unvollstaendig konfiguriert."""


class KIDatenschutz(KIError):
    """Der Text enthaelt Daten, die nicht extern verarbeitet werden duerfen."""

    def __init__(self, treffer: Iterable[str]):
        self.treffer = tuple(sorted(set(treffer)))
        super().__init__(
            "KI-Versand abgebrochen: der Text enthaelt "
            + ", ".join(self.treffer)
            + ". Nur erfundene Beispieldaten oder freigegebene Inhalte senden."
        )


class KIAntwortFehler(KIError):
    """Die Gegenstelle antwortete nicht verwertbar."""


@dataclass(frozen=True)
class Konfiguration:
    """Aufgeloeste Adapterkonfiguration (ohne Ausgabe des Schluessels)."""

    basis_url: str
    modell: str
    key: str
    aktiv: bool
    timeout: float = STANDARD_TIMEOUT

    @property
    def endpoint(self) -> str:
        basis = self.basis_url.rstrip("/")
        if basis.endswith("/chat/completions"):
            return basis
        return f"{basis}/chat/completions"

    def ohne_key(self) -> dict[str, Any]:
        return {
            "aktiv": self.aktiv,
            "basis_url": self.basis_url,
            "modell": self.modell,
            "key": "gesetzt" if self.key else "fehlt",
            "timeout": self.timeout,
        }


def _dotenv_pfade() -> list[Path]:
    hier = Path(__file__).resolve()
    return [
        Path.cwd() / ".env",
        hier.parents[2] / ".env",
        Path.home() / ".hermes" / ".env",
    ]


def _lies_dotenv() -> dict[str, str]:
    """Liest BPMN_KI_*-Werte aus der ersten passenden ``.env`` (ohne Override)."""
    werte: dict[str, str] = {}
    for pfad in _dotenv_pfade():
        try:
            if not pfad.is_file():
                continue
            for zeile in pfad.read_text(encoding="utf-8").splitlines():
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#") or "=" not in zeile:
                    continue
                schluessel, wert = zeile.split("=", 1)
                schluessel = schluessel.strip()
                if not schluessel.startswith(ENV_PRAEFIX):
                    continue
                wert = wert.strip().strip('"').strip("'")
                werte.setdefault(schluessel, wert)
        except OSError:
            continue
    return werte


def _wert(name: str, dotenv: Mapping[str, str]) -> str:
    return (os.environ.get(name) or dotenv.get(name) or "").strip()


def _wahr(wert: str) -> bool:
    return wert.strip().lower() in TRUE_WERTE


def lade_konfiguration() -> Konfiguration:
    """Liest die Konfiguration aus Umgebung und ``.env``."""
    dotenv = _lies_dotenv()
    try:
        timeout = float(_wert(ENV_TIMEOUT, dotenv) or STANDARD_TIMEOUT)
    except ValueError:
        timeout = STANDARD_TIMEOUT
    if timeout <= 0:
        timeout = STANDARD_TIMEOUT
    return Konfiguration(
        basis_url=_wert(ENV_BASIS_URL, dotenv),
        modell=_wert(ENV_MODELL, dotenv),
        key=_wert(ENV_KEY, dotenv),
        aktiv=_wahr(_wert(ENV_AKTIV, dotenv)),
        timeout=timeout,
    )


def konfiguriert(konfiguration: Konfiguration | None = None) -> bool:
    """True nur, wenn der Adapter aktiv und vollstaendig konfiguriert ist."""
    cfg = konfiguration or lade_konfiguration()
    return bool(cfg.aktiv and cfg.basis_url and cfg.modell and cfg.key)


def status(konfiguration: Konfiguration | None = None) -> dict[str, Any]:
    """Zustand fuer Anzeige und Diagnose -- ohne Schluesselwert."""
    cfg = konfiguration or lade_konfiguration()
    daten = cfg.ohne_key()
    if not cfg.aktiv:
        daten["grund"] = f"aus ({ENV_AKTIV} ist nicht gesetzt)"
    elif not cfg.basis_url:
        daten["grund"] = f"{ENV_BASIS_URL} fehlt"
    elif not cfg.modell:
        daten["grund"] = f"{ENV_MODELL} fehlt"
    elif not cfg.key:
        daten["grund"] = f"{ENV_KEY} fehlt (Umgebung und .env geprueft)"
    else:
        daten["grund"] = ""
    daten["konfiguriert"] = konfiguriert(cfg)
    return daten


def pruefe_datenschutz(text: str) -> list[str]:
    """Liefert die Arten personenbezogener/dienstlicher Daten im Text."""
    treffer: list[str] = []
    for name, muster in DATENSCHUTZ_MUSTER:
        if muster.search(text or ""):
            treffer.append(name)
    return treffer


def _system_prompt() -> str:
    return (
        "Du bist Prozessanalyst fuer Behoerdenprozesse. Zerlege den Text in "
        "Prozessschritte. Antworte ausschliesslich mit einem JSON-Objekt nach "
        "diesem Schema:\n"
        '{"schritte": [{"rolle": "...", "aktion": "...", "objekt": "...", '
        '"bedingung": "..."}]}\n'
        "Regeln: 'aktion' ist der Infinitiv (z. B. 'pruefen', 'senden'). "
        "'rolle' ist der handelnde Aufgabentraeger. 'objekt' ist das bearbeitete "
        "Dokument oder Ding. 'bedingung' bleibt leer, wenn keine Bedingung "
        "genannt ist. Erfinde nichts, was nicht im Text steht. Keine Erklaerung, "
        "kein Markdown."
    )


def _anfrage_bauen(text: str, konfiguration: Konfiguration) -> dict[str, Any]:
    return {
        "model": konfiguration.modell,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": text},
        ],
        "response_format": {"type": "json_object"},
    }


def _sende(
    anfrage: Mapping[str, Any],
    konfiguration: Konfiguration,
    opener: Callable[..., Any] | None = None,
) -> str:
    """Sendet die Anfrage und liefert den Antworttext (ohne Schluessel im Fehler)."""
    oeffner = opener or urllib.request.urlopen
    daten = json.dumps(anfrage, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        konfiguration.endpoint,
        data=daten,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {konfiguration.key}",
            "Accept": "application/json",
        },
    )
    try:
        with oeffner(request, timeout=konfiguration.timeout) as antwort:
            roh = antwort.read()
    except urllib.error.HTTPError as fehler:
        raise KIError(
            f"KI-Endpunkt antwortete mit HTTP {fehler.code}; Antwort nicht uebernommen"
        ) from None
    except urllib.error.URLError as fehler:
        raise KIError(f"KI-Endpunkt nicht erreichbar: {fehler.reason}") from None
    except TimeoutError:
        raise KIError(f"KI-Endpunkt hat das Zeitlimit von {konfiguration.timeout}s ueberschritten") from None
    try:
        return roh.decode("utf-8")
    except UnicodeDecodeError as fehler:
        raise KIAntwortFehler(f"Antwort ist kein UTF-8: {fehler}") from None


def _json_aus_antwort(text: str) -> dict[str, Any]:
    """Schneidet Markdown-Zaeune ab und liest das JSON-Objekt."""
    bereinigt = text.strip()
    if bereinigt.startswith("```"):
        bereinigt = re.sub(r"^```(?:json)?\s*", "", bereinigt, flags=re.I)
        bereinigt = re.sub(r"\s*```$", "", bereinigt)
    try:
        daten = json.loads(bereinigt)
    except json.JSONDecodeError as fehler:
        raise KIAntwortFehler(f"Antwort ist kein JSON: {fehler.msg}") from None
    if not isinstance(daten, dict):
        raise KIAntwortFehler("Antwort ist kein JSON-Objekt")
    return daten


def _schritte_aus_antwort(daten: Mapping[str, Any]) -> list[dict[str, Any]]:
    roh = daten.get("schritte")
    if not isinstance(roh, list):
        raise KIAntwortFehler("Antwort enthaelt keine Liste 'schritte'")
    schritte: list[dict[str, Any]] = []
    for nummer, eintrag in enumerate(roh, start=1):
        if not isinstance(eintrag, Mapping):
            raise KIAntwortFehler(f"schritte[{nummer}] ist kein Objekt")
        rolle = str(eintrag.get("rolle") or "").strip()
        aktion = str(eintrag.get("aktion") or "").strip().lower()
        objekt = str(eintrag.get("objekt") or "").strip()
        if not aktion:
            raise KIAntwortFehler(f"schritte[{nummer}] hat keine 'aktion'")
        schritte.append(
            {
                "nummer": nummer,
                "rolle": rolle,
                "aktion": re.sub(r"\s+", " ", aktion),
                "objekt": objekt,
                "bedingung": str(eintrag.get("bedingung") or "").strip(),
                # KI-Ausgaben sind Vorschlaege, keine Belege.
                "sicherheit": extraktion.UNSICHER,
                "begruendung": "KI-Angabe -- fachlich pruefen",
                "quelle": "ki",
            }
        )
    return schritte


def extrahiere_mit_ki(
    text: str,
    prozess_name: str | None = None,
    *,
    erlaube_personenbezug: bool = False,
    konfiguration: Konfiguration | None = None,
    opener: Callable[..., Any] | None = None,
) -> extraktion.Extraktion:
    """Extrahiert Schritte ueber den konfigurierten KI-Endpunkt.

    Es gibt keinen stillen Rueckfall auf die Regeln: Ist der Adapter aus oder
    unvollstaendig, wird :class:`KINichtKonfiguriert` geworfen.
    """
    cfg = konfiguration or lade_konfiguration()
    if not konfiguriert(cfg):
        raise KINichtKonfiguriert(
            "KI ist nicht konfiguriert: "
            + (status(cfg).get("grund") or "unbekannter Grund")
            + f". Benoetigt werden {ENV_AKTIV}=1, {ENV_BASIS_URL}, {ENV_MODELL}, {ENV_KEY}."
        )
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text muss eine nicht leere Zeichenkette sein")

    treffer = pruefe_datenschutz(text)
    if treffer and not erlaube_personenbezug:
        raise KIDatenschutz(treffer)

    roh = _sende(_anfrage_bauen(text, cfg), cfg, opener=opener)
    try:
        antwort = json.loads(roh)
        inhalt = antwort["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as fehler:
        raise KIAntwortFehler(f"Antwort hat kein erwartetes Chat-Format: {fehler}") from None

    schritte = _schritte_aus_antwort(_json_aus_antwort(str(inhalt or "")))
    ergebnis = extraktion.baue_modell(
        schritte,
        prozess_name or extraktion._prozessname_aus_text(text),
        quelle="ki",
        hinweise=[
            "KI-Ausgabe: alle Elemente stehen auf 'unsicher' und sind fachlich zu pruefen.",
            f"Modell: {cfg.modell}",
        ],
    )
    ergebnis.rollen = [lane.name for lane in ergebnis.modell.prozesse["Process_1"].alle_lanes()]
    return ergebnis


def main(argv: list[str] | None = None) -> int:
    """Diagnose: ``python -m bpmn.ki`` zeigt den Zustand ohne Schluessel."""
    import argparse

    parser = argparse.ArgumentParser(description="Status des optionalen KI-Adapters.")
    parser.add_argument("--status", action="store_true", help="nur den Zustand ausgeben")
    args = parser.parse_args(argv)
    daten = status()
    print(json.dumps(daten, ensure_ascii=False, indent=2))
    if args.status:
        return 0
    return 0 if daten["konfiguriert"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
