#!/usr/bin/env python3
"""Übersetzungshelfer: übersetzt offene Zeichenketten per DeepSeek und prüft sie.

    python3 apps/html-editor/translate_english.py --entwurf     # Entwurf erzeugen
    python3 apps/html-editor/translate_english.py --pruefen     # Entwurf prüfen

Der Entwurf landet in ``dist/_entwurf.json`` (deutsch -> englisch). Geprüfte
Einträge werden nach ``src/english.json`` übernommen — nur dort wirkt die
Übersetzung beim Bau.

Regeln, die das Skript selbst durchsetzt:

* Platzhalter im Ausgangstext (``%s``, ``{0}``, ``${…}``) müssen im Entwurf
  genau einmal vorkommen.
* Keine Entwürfe für SQL, Kennungen oder Texte, die offensichtlich schon
  englisch sind.
* Gleich lange Wörter ohne Umlaut (``in``, ``und``, ``von``) werden nie
  maschinell übersetzt — die stehen meist im Fließtext und würden dort
  Schaden anrichten.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
SRC = APP / "src"
DIST = APP / "dist"
WOERTERBUCH = SRC / "english.json"
ENTWURF = DIST / "_entwurf.json"

ENV_DATEIEN = [Path("/root/.hermes/.env"), APP.parents[1] / ".env"]

SYSTEM = """Übersetze kurze Oberflächentexte einer Architektur-Anwendung vom Deutschen ins
Englische. Antworte nur mit einem JSON-Objekt, das jeden Schlüssel unverändert
aufnimmt und den englischen Text als Wert zurückgibt.

Regeln:
- Kurz und knapp, wie in einer Software-Oberfläche. Keine Höflichkeitsfloskeln.
- Fachbegriffe: Element, Paket, Sicht, Beziehung, Stereotyp, Modell bleiben
  fachlich korrekt. Übersetze sie als element, package, view, connection,
  stereotype, model.
- Emoji und Satzzeichen am Rand unverändert übernehmen.
- Platzhalter wie %s, %d, {0}, ${version} exakt einmal übernehmen.
- HTML-Tags, Attribute und CSS-Klassen unverändert lassen; nur der sichtbare
  Text darin wird übersetzt.
- Ist ein Text bereits englisch, gib ihn unverändert zurück."""

VERBOTEN = re.compile(r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b")
PLATZHALTER = re.compile(r"%[sd]|\{\d+\}|\$\{[^}]+\}")


def schluessel() -> str:
    for datei in ENV_DATEIEN:
        if not datei.is_file():
            continue
        for zeile in datei.read_text(encoding="utf-8", errors="ignore").splitlines():
            if zeile.strip().startswith("DEEPSEEK_API_KEY"):
                return zeile.split("=", 1)[1].strip().strip("\"'")
    return os.environ.get("DEEPSEEK_API_KEY", "")


def offene() -> list[str]:
    sys.path.insert(0, str(APP))
    import build_english as b  # noqa: PLC0415

    woerter = json.loads(WOERTERBUCH.read_text(encoding="utf-8"))
    offen = []
    for liste in b.kandidaten().values():
        for text in liste:
            if text in woerter or len(text) < 4:
                continue
            if VERBOTEN.match(text.strip()) or text.strip() in {"in", "und", "von", "Die", "Über", "wurde"}:
                continue
            if re.fullmatch(r"[a-z_]+", text):
                continue
            offen.append(text)
    return sorted(set(offen))


def frage(text: list[str], key: str) -> dict[str, str]:
    nutzlast = json.dumps(
        {
            "model": "deepseek-chat",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(dict(zip(map(str, range(len(text))), text)), ensure_ascii=False)},
            ],
        }
    ).encode()
    anfrage = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=nutzlast,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(anfrage, timeout=180) as antwort:
        daten = json.loads(antwort.read())
    roh = json.loads(daten["choices"][0]["message"]["content"])
    return {text[int(k)]: v for k, v in roh.items() if k.isdigit() and int(k) < len(text)}


def entwurf(key: str) -> int:
    texte = offene()
    print(f"{len(texte)} offene Zeichenketten.")
    ergebnis: dict[str, str] = {}
    stapel = 40
    for i in range(0, len(texte), stapel):
        teil = texte[i : i + stapel]
        try:
            ergebnis.update(frage(teil, key))
        except Exception as fehler:  # noqa: BLE001
            print(f"  Stapel {i // stapel + 1}: {fehler}")
        print(f"  {min(i + stapel, len(texte))}/{len(texte)}")
        time.sleep(1)
    ENTWURF.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(ergebnis)} Entwürfe nach {ENTWURF}")
    return 0


def pruefen(uebernehmen: bool) -> int:
    entwuerfe = json.loads(ENTWURF.read_text(encoding="utf-8"))
    woerter = json.loads(WOERTERBUCH.read_text(encoding="utf-8"))
    gut, schlecht = {}, {}
    for de, en in entwuerfe.items():
        if not isinstance(en, str) or not en.strip():
            schlecht[de] = "leer"
            continue
        if sorted(PLATZHALTER.findall(de)) != sorted(PLATZHALTER.findall(en)):
            schlecht[de] = "Platzhalter"
            continue
        if de == en:
            schlecht[de] = "unverändert"
            continue
        if re.search(r"[äöüÄÖÜß]", en):
            schlecht[de] = "noch deutsch"
            continue
        gut[de] = en
    print(f"{len(gut)} brauchbar, {len(schlecht)} verworfen.")
    for de, grund in list(schlecht.items())[:15]:
        print(f"  {grund}: {de[:60]}")
    if uebernehmen:
        woerter.update(gut)
        WOERTERBUCH.write_text(json.dumps(woerter, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"übernommen: {WOERTERBUCH} ({len(woerter)} Einträge)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entwurf", action="store_true")
    parser.add_argument("--pruefen", action="store_true")
    parser.add_argument("--uebernehmen", action="store_true")
    args = parser.parse_args()
    if args.entwurf:
        key = schluessel()
        if not key:
            raise SystemExit("DEEPSEEK_API_KEY fehlt.")
        return entwurf(key)
    if args.pruefen:
        return pruefen(args.uebernehmen)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
