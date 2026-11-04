#!/usr/bin/env python3
"""Holt die amtlichen Quelldokumente der Methode Architektur.

Die PDFs und Archive des BAAINBw gehoeren nicht ins Repository: sie sind
fremde Dokumente, mehrere MB gross, und fuer den Betrieb nicht noetig -- das
Ergebnis (``knowledge/regelwerk.json`` und die Konventionsdateien) liegt
versioniert daneben.

Wer das Artefakt neu bauen will, holt die Quellen vorher:

    python3 scripts/fetch_quellen.py [--ziel ~/.cache/eam-quellen]

Danach:
    python3 scripts/extract_leitfaden.py <ziel>/leitfaden-ffmlv-v2.0.txt
    python3 scripts/build_regelwerk.py
"""
from __future__ import annotations

import argparse
import gzip
import sys
import urllib.request
from pathlib import Path

BASIS = "https://www.bundeswehr.de/resource/blob"
SEITE = "https://www.bundeswehr.de/de/organisation/ausruestung-baainbw/vergabe/methode-architektur"

#: (Dateiname, Pfad in der Ressource)
DATEIEN = [
    ("grundlagen-nafv4.pdf", "5570630/150b1d550eefc9f68b0058e6f550c52b/grundlagen-methode-architektur-nach-nafv4--data.pdf"),
    ("admbw-sparx-ea.pdf", "5570650/237332d2cb398f280a68c45ebdeea384/dokumentation-verwendung-des-admbw-im-sparx-ea--data.pdf"),
    ("admbw-mdg-2026.05.zip", "5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip"),
    ("admbw-dokumentation.pdf", "5570644/2df2e5da515c496b11d88588ed46443f/dokumentation-admbw--data.pdf"),
    ("admbw-release-notes.pdf", "6117920/173e5ae1cba4a5fca196742440899a79/release-notes-admbw--data.pdf"),
    ("model-wizard.7z", "6117924/9a605811a7a031963de64dc059c45c00/model-wizard-data.7z"),
    ("leitfaden-ffmlv-v2.0.pdf", "5932800/bc0578b2f8c9e9c132bb7dbf8dfc29ad/leitfaden-architekturen-fuer-die-fff-mit-loesungsvorschlag-pbn--data.pdf"),
    ("leitfaden-pbn-service-system.pdf", "5570784/c621597c9bec9d36ce7d8324dd1155da/leitfaden-projektarchitekturen-pbn-anteil-service-und-system-data.pdf"),
]

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def hole(url: str) -> bytes:
    anfrage = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(anfrage, timeout=120) as antwort:  # noqa: S310
        return antwort.read()


def main() -> int:
    ap = argparse.ArgumentParser(description="Quelldokumente der Methode Architektur holen")
    ap.add_argument("--ziel", default="~/.cache/eam-quellen")
    args = ap.parse_args()
    ziel = Path(args.ziel).expanduser()
    ziel.mkdir(parents=True, exist_ok=True)

    fehler = 0
    for name, pfad in DATEIEN:
        datei = ziel / name
        if datei.is_file() and datei.stat().st_size > 1000:
            print(f"  vorhanden  {name}")
            continue
        try:
            roh = hole(f"{BASIS}/{pfad}")
        except OSError as exc:
            print(f"  FEHLER     {name}: {exc}")
            fehler += 1
            continue
        # Der Server liefert ohne --compressed gzip-kodierte Bytes.
        if roh[:2] == b"\x1f\x8b":
            roh = gzip.decompress(roh)
        datei.write_bytes(roh)
        print(f"  geladen    {name}  ({len(roh):,} B)")

    print(f"\nQuellen: {ziel}")
    print(f"Seite:   {SEITE}")
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
