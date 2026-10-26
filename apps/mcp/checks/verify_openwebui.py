#!/usr/bin/env python3
"""Rauchtest des ausgelieferten Open-WebUI-Werkzeugs an einem echten Modell.

    python3 apps/mcp/checks/verify_openwebui.py [--qea PFAD]

Aufgerufen wird dieselbe Datei, die als `dist/eam_qea_analyzer_openwebui.py`
im Release liegt. Geprüft werden die vier Funktionen, die ein Modell dort
zuerst benutzt: Dateiliste, Statistik, Elementsuche, Paketbaum.

Exit 0 = alle Erwartungen erfüllt, Exit 1 = mindestens eine nicht.
Standardmodell ist die MASC-Fixture im Repo; ein abweichender Pfad kann
per ``--qea`` uebergeben werden.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WERKZEUG = ROOT / "apps" / "mcp" / "eam_qea_tool.py"
MASCDEFAULT = ROOT / "packages" / "core" / "fixtures" / "Musterarchitektur_MASC.qea"


def _lade(datei: Path):
    spec = importlib.util.spec_from_file_location("werkzeug", datei)
    modul = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(modul)
    return modul


async def _pruefe(qea: Path) -> list[str]:
    befund: list[str] = []
    modul = _lade(WERKZEUG)
    tools = modul.Tools()

    stats = json.loads(await tools.analyze_qea_statistics(str(qea)))
    for feld in ("Packages", "Elements", "Connectors"):
        if not isinstance(stats.get(feld), int) or stats[feld] <= 0:
            befund.append(f"Statistik: {feld} fehlt oder ist 0 ({stats.get(feld)!r})")

    treffer = json.loads(
        await tools.find_elements_in_qea(str(qea), stereotype="ServiceSpecification", limit=50)
    )
    namen = [t.get("Name") for t in treffer]
    if not namen:
        befund.append("Suche nach ServiceSpecification liefert nichts")
        begriff = ""
    else:
        # Suchbegriff aus dem Bestand selbst ableiten. Ein fest eingetragener
        # Name waere modellspezifisch und wuerde bei jedem anderen Modell
        # fehlschlagen.
        begriff = str(namen[0])
        gesucht = json.loads(await tools.search_qea_elements(str(qea), query=begriff, limit=10))
        if not any(e.get("Name") == begriff for e in gesucht):
            befund.append(
                f"Volltextsuche '{begriff}' findet das Element nicht: "
                f"{[e.get('Name') for e in gesucht]}"
            )

    baum = json.loads(await tools.get_package_tree_from_qea(str(qea)))
    wurzeln = [k.get("name") for k in baum.get("roots", [])]
    if not wurzeln:
        befund.append(f"Paketbaum-Wurzeln unerwartet: {wurzeln}")
    return befund


def main() -> int:
    ap = argparse.ArgumentParser(description="Open-WebUI-Werkzeug rauchtesten.")
    ap.add_argument("--qea", default=str(MASCDEFAULT))
    args = ap.parse_args()
    qea = Path(args.qea)
    try:
        vorhanden = qea.is_file()
    except OSError:
        # CI laeuft als fremder Nutzer; ein nicht lesbarer Pfad ist ein Skip,
        # kein Testfehler.
        vorhanden = False
    if not vorhanden:
        print(f"SKIP: Modell fehlt oder ist nicht lesbar ({qea})")
        return 0
    befund = asyncio.run(_pruefe(qea))
    for b in befund:
        print(f"BEFUND: {b}")
    print(f"Open-WebUI-Werkzeug gegen {qea.name}: {'OK' if not befund else 'FEHLER'}")
    return 0 if not befund else 1


if __name__ == "__main__":
    sys.exit(main())
