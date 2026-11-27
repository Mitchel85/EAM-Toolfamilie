#!/usr/bin/env python3
"""Sammelt alle Auslieferungen flach in `dist/`, packt den Quellstand und schreibt den Katalog.

    python3 scripts/collect_releases.py [--dist dist] [--version 2.4.1]

Ausgeliefert wird genau die Liste `AUSLIEFERUNGEN` plus das Quell-Archiv
`eam-ai-suite-python-<version>.zip`. Nur diese Dateien stehen in `SHA256SUMS`
und `RELEASES.md`. Was sonst in `dist/` liegt — Katalog, Graph, Altbestand —,
ist kein Download-Posten und wird nicht mitgeprüft.

  dist/README.md      welche Datei wofür, plus Einstieg
  dist/RELEASES.md    Dateiname, Größe, SHA-256 — Beleg statt Behauptung
  dist/SHA256SUMS     Prüfsummen im Standardformat — nur ausgelieferte Dateien

Quelle bleibt das Repo: hier wird nichts kompiliert, nur eingesammelt. Das
Quell-Archiv entsteht deterministisch: sortierte Einträge, feste Zeitstempel,
feste Rechte — gleicher Quellstand ergibt gleiche Bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path
from string import Template
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]

#: (Quelle im Repo, Zielname in dist/, Produkt, Einstiegshinweis)
#: Kopfzeilen fuer Auslieferungen, die eine Marke tragen sollen, ohne dass die
#: Quelle sie enthaelt.
KOPFZEILE = {
    "admbw-extraktor.py": (
        '# ADMBw Extraktor -- MDG-Auswertung\n'
        '#\n'
        '# Liest die MDG-Technologie der Bundeswehr und schreibt das Regelwerk\n'
        '# (Stereotype, Konnektoren, Viewpoints, Tag-Typen, Werkzeugkaesten).\n'
        '#\n'
        '# Aufruf:  python3 admbw-extraktor.py <mdg.xml> -o rules.json\n'
        '#\n'
        '# Die Engine ist technologieneutral und liest jede MDG-/UML-Profil-XML.\n'
        '\n'
    ),
}
#: Altnamen behalten dieselbe Kopfzeile -- der Inhalt ist identisch.
KOPFZEILE["eam-mdg-parser.py"] = KOPFZEILE["admbw-extraktor.py"]

AUSLIEFERUNGEN = [
    (
        "apps/html-suite/dist/EAM-AI-Suite.html",
        "EAM-AI-Suite.html",
        "EAM AI Suite v9.1 — eine HTML-Datei",
        "Prosa oder Handbuch hinein, `.qea` heraus: live prüfen (inkl. ArchiMate-Matrix, Diff, Auto-Repair & Textabdeckung), per Chat with Data befragen, per Sprache weiterbauen.",
    ),
    (
        "apps/html-suite/dist/EAM-AI-Suite.aspx",
        "EAM-AI-Suite.aspx",
        "EAM AI Suite — SharePoint-Fassung",
        "Dieselbe Anwendung als ASPX mit BOM für SharePoint/IIS.",
    ),
    (
        "apps/html-editor/dist/EAM-Suite.html",
        "EAM-Suite.html",
        "EAM Suite v8.6 — eine HTML-Datei",
        "Mehrere Modelle laden, verschmelzen, vergleichen (Diff & Undo), regelbasiert reparieren, bearbeiten und zurückschreiben; ohne KI.",
    ),
    (
        "apps/html-editor/dist/EAM-Suite.aspx",
        "EAM-Suite.aspx",
        "EAM Suite v8.6 — SharePoint-Fassung",
        "Dieselbe Bearbeiten-App als ASPX mit BOM für SharePoint/IIS; ohne KI.",
    ),
    (
        "apps/html-editor/dist/EAM-Suite-en.html",
        "EAM-Suite-en.html",
        "EAM Suite v8.6 — englische Fassung",
        "Dieselbe App mit englischer Oberfläche; Modellinhalte und Dateiformat bleiben unverändert.",
    ),
    (
        "apps/html-sichten-archiv/dist/Sichten-Archiv.html",
        "Sichten-Archiv.html",
        "Sichten-Archiv v1.0 — eine HTML-Datei",
        "Sichten und Layout aus einer `.qea` in ein `.archiv` auslagern und verlustfrei zurückspielen.",
    ),
    (
        "apps/html-sichten-archiv/dist/Sichten-Archiv.aspx",
        "Sichten-Archiv.aspx",
        "Sichten-Archiv v1.0 — SharePoint-Fassung",
        "Dieselbe Anwendung als ASPX mit BOM für SharePoint/IIS.",
    ),
    (
        "apps/bpmn-studio/dist/BPMN-Studio.html",
        "BPMN-Studio.html",
        "BPMN Studio — eine HTML-Datei",
        "Prozesse als BPMN 2.0 anzeigen, bearbeiten, prüfen, ADMBw-konform machen; Export als XML, SVG und PNG. Offline im Browser.",
    ),
    (
        "apps/bpmn-studio/dist/BPMN-Studio.aspx",
        "BPMN-Studio.aspx",
        "BPMN Studio — SharePoint-Fassung",
        "Dieselbe Anwendung als ASPX mit BOM für SharePoint/IIS. KI nur mit eigenem Zugang, weil kein Schluessel in der Datei steht.",
    ),
    (
        "apps/admbw-extractor/html/dist/ADMBw-Extraktor.html",
        "ADMBw-Extraktor.html",
        "ADMBw Extraktor — eine HTML-Datei",
        "MDG-XML laden: Stereotype, Topologie, Viewpoints, Tag-Typen und Stereotyp-Tags durchsuchen; sechs Regeldateien exportieren. Offline im Browser.",
    ),
    (
        "packages/rules/mdg_parser.py",
        "admbw-extraktor.py",
        "ADMBw Extraktor — Python-Variante",
        "Dieselbe Datei wie im Python-ZIP: MDG-XML in ein Regelwerk übersetzen; ohne Browser.",
    ),
    (
        "apps/admbw-extractor/html/dist/ADMBw-Extraktor.html",
        "EAM-MDG-Parser.html",
        "EAM MDG Parser — Altname (unveraendert bedient)",
        "Dieselbe Datei unter dem frueheren Namen; alte Links und Lesezeichen bleiben gueltig.",
    ),
    (
        "packages/rules/mdg_parser.py",
        "eam-mdg-parser.py",
        "EAM MDG Parser — Python-Altname (unveraendert bedient)",
        "Dieselbe Datei unter dem frueheren Namen; alte Aufrufe bleiben gueltig.",
    ),
    (
        "apps/mcp/eam_qea_tool.py",
        "eam_qea_analyzer_openwebui.py",
        "EAM QEA Analyzer — Open-WebUI-Tool",
        "In Open WebUI unter Werkzeuge einfügen; das Modell fragt damit eine `.qea` ab, statt zu raten.",
    ),
    (
        "apps/mcp/mcp_server.py",
        "eam-qea-mcp-server.py",
        "EAM QEA Analyzer — MCP-Server",
        "MCP-Wrapper für Open WebUI, Claude Desktop und VS Code; braucht eam_qea_analyzer_openwebui.py im selben Ordner.",
    ),
    (
        "apps/cli/openwebui/eam_ai_suite_openwebui.py",
        "eam_ai_suite_openwebui.py",
        "EAM AI Suite Python — Open-WebUI-Tool (Dual-Modus)",
        "In Open WebUI unter Werkzeuge einfügen; spricht den GHCR-Container (`eam-ai serve`) oder lokales `eam-ai` an.",
    ),
    (
        "apps/cli/openwebui/eam_ai_suite_pipe.py",
        "eam_ai_suite_pipe.py",
        "EAM AI Suite Python — Open-WebUI-Pipe (7-Stufen-Architekt)",
        "In Open WebUI unter Functions einfügen; erscheint als eigenes Modell mit Fortschrittsstatus und Download-Links.",
    ),
]

#: App-Buendel fuer den Auto-Zip: je Anwendung ein Archiv mit Kurzanleitung.
#: Der Dateiname bleibt ueber Releases hinweg gleich, damit Links auf
#: `releases/latest/download/<name>.zip` dauerhaft funktionieren; die Version
#: steht in der Kurzanleitung und im Katalog.


class AppBuendel(TypedDict):
    """Eine Anwendung im Auto-Zip: Metadaten, Dateien, Startschritte."""

    name: str
    produkt: str
    text: str
    #: (Pfad im Archiv, Quelle im Repo, Zweck) — Quelle darf ein Verzeichnis sein.
    dateien: tuple[tuple[str, str, str], ...]
    start: tuple[str, ...]


APP_ZIPS: tuple[AppBuendel, ...] = (
    {
        "name": "EAM-Suite",
        "produkt": "EAM Suite — komplettes Paket (HTML, ASPX, englisch)",
        "text": "Modelle laden (`.qea`, `.xmi`, `.json`), analysieren, verschmelzen, bearbeiten und zurückschreiben — ohne KI, vollständig im Browser.",
        "dateien": (
            ("EAM-Suite.html", "apps/html-editor/dist/EAM-Suite.html", "Hauptfassung: im Browser öffnen"),
            ("EAM-Suite.aspx", "apps/html-editor/dist/EAM-Suite.aspx", "SharePoint-/IIS-Fassung mit BOM"),
            ("EAM-Suite-en.html", "apps/html-editor/dist/EAM-Suite-en.html", "Englische Oberfläche"),
        ),
        "start": ("EAM-Suite.html im Browser öffnen", "Modell(e) laden", "Prüfen, bearbeiten, als neue Datei speichern"),
    },
    {
        "name": "EAM-AI-Suite",
        "produkt": "EAM AI Suite — komplettes Paket (HTML, ASPX)",
        "text": "Text, Handbuch, DOCX, PDF oder Bild iterativ einlesen und daraus ein Modell erzeugen; direkt in Explorer/Graph/QS ansehen, per Chat with Data befragen, im Dialog oder per Sprache weiterbauen und als `.qea`, `.xmi`, `.json` oder ArchiMate `.xml` speichern.",
        "dateien": (
            ("EAM-AI-Suite.html", "apps/html-suite/dist/EAM-AI-Suite.html", "Hauptfassung: im Browser öffnen"),
            ("EAM-AI-Suite.aspx", "apps/html-suite/dist/EAM-AI-Suite.aspx", "SharePoint-/IIS-Fassung mit BOM"),
        ),
        "start": ("EAM-AI-Suite.html im Browser öffnen", "Quelle angeben (Text, Handbuch, DOCX, PDF, Bild)", "Modell erzeugen, live prüfen, befragen & weiterbauen"),
    },
    {
        "name": "EAM-Analyzer",
        "produkt": "EAM Analyzer — Open-WebUI-Tool und MCP-Server",
        "text": "Vorhandene Modelle befragen (`.qea` und `.xmi`): als Werkzeug in Open WebUI oder als MCP-Server für Open WebUI, Claude Desktop und VS Code.",
        "dateien": (
            ("eam_qea_analyzer_openwebui.py", "apps/mcp/eam_qea_tool.py", "Open-WebUI-Tool: unter „Werkzeuge“ einfügen"),
            ("eam-qea-mcp-server.py", "apps/mcp/mcp_server.py", "MCP-Server: starten und im Client verbinden"),
        ),
        "start": ("Open-WebUI-Tool in Open WebUI einfügen", "Modell laden (`.qea` oder `.xmi`)", "Fragen stellen"),
    },
    {
        "name": "ADMBw-Extraktor",
        "produkt": "ADMBw Extraktor — HTML und Python",
        "text": "MDG-XML laden: Stereotype, Topologie, Viewpoints, Tag-Typen und Stereotyp-Tags durchsuchen; sechs Regeldateien exportieren.",
        "dateien": (
            ("ADMBw-Extraktor.html", "apps/admbw-extractor/html/dist/ADMBw-Extraktor.html", "HTML-Fassung: im Browser öffnen"),
            ("admbw-extraktor.py", "packages/rules/mdg_parser.py", "Python-Variante: `python3 admbw-extraktor.py <mdg.xml> -o regeln/`"),
        ),
        "start": ("ADMBw-Extraktor.html im Browser öffnen", "MDG-XML laden", "Regeldateien exportieren"),
    },
    {
        "name": "BPMN-Studio",
        "produkt": "BPMN Studio — HTML, ASPX und Python",
        "text": "BPMN 2.0 lesen, anzeigen, bearbeiten und prüfen; auf Knopfdruck ADMBw-konform machen; Export als XML, SVG und PNG.",
        "dateien": (
            ("BPMN-Studio.html", "apps/bpmn-studio/dist/BPMN-Studio.html", "HTML-Fassung: im Browser öffnen"),
            ("BPMN-Studio.aspx", "apps/bpmn-studio/dist/BPMN-Studio.aspx", "SharePoint-/IIS-Fassung mit BOM"),
            ("python/bpmn", "packages/bpmn", "Python-Paket: `PYTHONPATH=python python3 -m bpmn.cli pruefen prozess.bpmn`"),
            ("knowledge/bpmn/prozess-regeln.json", "knowledge/bpmn/prozess-regeln.json", "ADMBw-L4-Regeldatei für das Python-Paket"),
        ),
        "start": ("BPMN-Studio.html im Browser öffnen", "Prozess laden oder zeichnen", "Prüfen, ADMBw-konform machen, exportieren"),
    },
    {
        "name": "Sichten-Archiv",
        "produkt": "Sichten-Archiv — komplettes Paket (HTML, ASPX)",
        "text": "Sichten und Layout aus einer `.qea` auslagern und nach einer Pipeline-Bearbeitung verlustfrei zurückspielen — vollständig im Browser.",
        "dateien": (
            ("Sichten-Archiv.html", "apps/html-sichten-archiv/dist/Sichten-Archiv.html", "Hauptfassung: im Browser öffnen"),
            ("Sichten-Archiv.aspx", "apps/html-sichten-archiv/dist/Sichten-Archiv.aspx", "SharePoint-/IIS-Fassung mit BOM"),
        ),
        "start": ("Sichten-Archiv.html im Browser öffnen", "`.qea` laden und Sichten in `.archiv` auslagern", "Nach Bearbeitung `.archiv` wieder in die `.qea` zurückspielen"),
    },
    {
        "name": "EAM-AI-Suite-OpenWebUI",
        "produkt": "EAM AI Suite Python — Open-WebUI-Paket (Tool, Pipe, Skill & Compose)",
        "text": "Open-WebUI-Tool (`mode=http|local`), Pipe-Funktion (7-Stufen-Architekt), Skill-Markdown und Docker-Compose-Vorlage für Open WebUI + GHCR-Container.",
        "dateien": (
            ("eam_ai_suite_openwebui.py", "apps/cli/openwebui/eam_ai_suite_openwebui.py", "Open-WebUI-Tool (Workspace -> Tools)"),
            ("eam_ai_suite_pipe.py", "apps/cli/openwebui/eam_ai_suite_pipe.py", "Open-WebUI-Pipe (Workspace -> Functions)"),
            ("eam_ai_suite_skill.md", "apps/cli/openwebui/eam_ai_suite_skill.md", "Open-WebUI-Skill / System-Prompt"),
            ("docker-compose.openwebui.yml", "apps/cli/openwebui/docker-compose.openwebui.yml", "Docker Compose: Open WebUI + ghcr.io/mitchel85/eam-toolfamilie:latest"),
            ("README.md", "apps/cli/openwebui/README.md", "Einrichtungsanleitung"),
        ),
        "start": ("`docker compose -f docker-compose.openwebui.yml up -d` starten", "`eam_ai_suite_openwebui.py` in Open WebUI importieren", "`eam_ai_suite_skill.md` als Skill/Prompt hinterlegen"),
    },
)

#: Dateien des Python-Kerns, die ins Quell-Archiv gehören. Das Archiv ist
#: installierbar: entpacken, `pip install ./eam-ai-suite-python`.
QUELLSTAND = [
    "packages/core/pyproject.toml",
    "packages/core/README.md",
    "packages/core/CHANGELOG.md",
    "packages/core/PACKAGING.md",
    "packages/core/rules.schema.json",
    "packages/core/batch-schema.json",
    "packages/rules/mdg_parser.py",
    "LICENSE",
    "NOTICE.md",
]

#: Ordnernamen und Muster, die frühere Sammelläufe hinterlassen haben
#: (build_all.py: offline-Bundles, Wheel, HTML; alte Quellstand-Kopie).
VERALTET = ("offline", "wheel", "html", "eam-ai-suite-python")
VERALTET_MUSTER = ("*.whl", "*.tar.gz", "eam-ai-suite-python-*.zip")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def release_version(explicit: str | None) -> str:
    """Versionsnummer aus Argument, Tag-Umgebung oder Git-Tag; sonst pyproject."""
    kandidaten: list[str] = []
    if explicit:
        kandidaten.append(explicit)
    kandidaten.append(os.environ.get("GITHUB_REF_NAME", ""))
    try:
        tags = subprocess.run(
            ["git", "tag", "--points-at", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        kandidaten.extend(tags.stdout.split())
    except (OSError, subprocess.SubprocessError):
        pass
    for kandidat in kandidaten:
        name = kandidat.strip().lstrip("v")
        if re.fullmatch(r"\d+\.\d+\.\d+", name):
            return name
    with (ROOT / "packages" / "core" / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def raeume_altbestand(dist: Path) -> None:
    """Entfernt Rückstände früherer Sammelläufe, damit sie nicht mitlaufen."""
    for name in VERALTET:
        shutil.rmtree(dist / name, ignore_errors=True)
    for muster in VERALTET_MUSTER:
        for datei in dist.glob(muster):
            datei.unlink(missing_ok=True)


def quellstand_dateien() -> list[tuple[str, Path]]:
    """Alle Dateien des Archivs als (Name im Archiv, Pfad im Repo), sortiert."""
    kern = ROOT / "packages" / "core"
    dateien = [
        (f"eam-ai-suite-python/{pfad.name}", pfad)
        for pfad in sorted(kern.glob("*.py"))
        if pfad.name != "conftest.py"
    ]
    dateien += [(f"eam-ai-suite-python/{Path(rel).name}", ROOT / rel) for rel in QUELLSTAND]
    for unterordner in ("examples/offline", "examples/archimate", "archimate"):
        ordner = ROOT / "packages" / "core" / unterordner
        if ordner.is_dir():
            dateien += [
                (f"eam-ai-suite-python/{unterordner}/{pfad.name}", pfad)
                for pfad in sorted(ordner.glob("*"))
                if pfad.is_file()
            ]
    regelwerk_json = ROOT / "knowledge" / "regelwerk.json"
    if regelwerk_json.is_file():
        dateien.append(("eam-ai-suite-python/knowledge/regelwerk.json", regelwerk_json))
    current_mdg_file = ROOT / "packages" / "rules" / "CURRENT"
    if current_mdg_file.is_file():
        dateien.append(("eam-ai-suite-python/rules/CURRENT", current_mdg_file))
        mdg_name = current_mdg_file.read_text(encoding="utf-8").strip()
        mdg_xml = ROOT / "packages" / "rules" / mdg_name
        if mdg_xml.is_file():
            dateien.append((f"eam-ai-suite-python/rules/{mdg_name}", mdg_xml))
    return sorted(dateien, key=lambda eintrag: eintrag[0])


def baue_quellarchiv(dist: Path, version: str) -> Path:
    """Packt das Quell-Archiv ohne Zeitstempel und ohne Zufallswerte."""
    eintraege = quellstand_dateien()
    fehlend = [str(pfad.relative_to(ROOT)) for _, pfad in eintraege if not pfad.is_file()]
    if fehlend:
        raise SystemExit("Quellstand unvollständig: " + ", ".join(fehlend))
    ziel = dist / f"eam-ai-suite-python-{version}.zip"
    temporaer = ziel.with_name(ziel.name + ".tmp")
    with zipfile.ZipFile(temporaer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archiv:
        for name, pfad in eintraege:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archiv.writestr(info, pfad.read_bytes(), compresslevel=9)
    os.replace(temporaer, ziel)
    return ziel


def kurzanleitung(buendel: AppBuendel, version: str) -> str:
    """Kurzanleitung als Textdatei fuer das App-Buendel (ohne Zeitstempel)."""
    produkt = buendel["produkt"]
    zeilen = [produkt, "=" * len(produkt), "", buendel["text"], "", "Inhalt:"]
    for archivname, _quelle, zweck in buendel["dateien"]:
        zeilen.append(f"- {archivname} — {zweck}")
    zeilen += ["", "Start:"]
    for nummer, schritt in enumerate(buendel["start"], start=1):
        zeilen.append(f"{nummer}. {schritt}")
    zeilen += [
        "",
        "Systemvoraussetzungen: ein moderner Browser (Chrome, Edge, Firefox, Safari).",
        "Keine Installation, kein Konto, kein Netz: alles läuft lokal auf dem Rechner.",
        "",
        f"EAM Toolfamilie {version} — {REPO_URL}",
        "",
    ]
    return "\n".join(zeilen)


def baue_app_zip(dist: Path, buendel: AppBuendel, version: str) -> Path:
    """Packt eine Anwendung mit Kurzanleitung deterministisch als `<name>.zip`.

    Quelle ist ein Verzeichnis (z. B. `packages/bpmn`): dann kommen alle
    Python-Dateien darin in den gleichnamigen Zielordner.
    """
    name = buendel["name"]
    dateien: list[tuple[str, Path]] = []
    for archivname, quelle, _zweck in buendel["dateien"]:
        pfad = ROOT / quelle
        if pfad.is_dir():
            for datei in sorted(pfad.glob("*.py")):
                dateien.append((f"{name}/{archivname}/{datei.name}", datei))
        else:
            dateien.append((f"{name}/{archivname}", pfad))
    fehlend = [rel for rel, pfad in dateien if not pfad.is_file()]
    if fehlend:
        raise SystemExit("App-Buendel unvollständig: " + ", ".join(fehlend))
    ziel = dist / f"{name}.zip"
    temporaer = ziel.with_name(ziel.name + ".tmp")
    with zipfile.ZipFile(temporaer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archiv:
        info = zipfile.ZipInfo(f"{name}/KURZANLEITUNG.txt", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o644 << 16
        archiv.writestr(
            info,
            kurzanleitung(buendel, version).encode("utf-8"),
            compresslevel=9,
        )
        for rel, pfad in dateien:
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archiv.writestr(info, pfad.read_bytes(), compresslevel=9)
    os.replace(temporaer, ziel)
    return ziel


REPO_URL = "https://github.com/Mitchel85/EAM-Toolfamilie"
#: GitHub Pages: jede HTML-App läuft dort direkt im Browser.
SEITEN = "https://mitchel85.github.io/EAM-Toolfamilie/"
STARTSEITE = "START-HIER.html"

_START_TEMPLATE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EAM Toolfamilie — Werkzeuge für Architekturmodelle</title>
<style>
:root{
  --bg:#f6f7f9;
  --surface:#ffffff;
  --surface-subtle:#f1f4f8;
  --ink:#0f172a;
  --ink-secondary:#334155;
  --muted:#5b6778;
  --border:#e2e8f0;
  --border-strong:#cbd5e1;
  --brand:#0f6b63;
  --brand-hover:#0b534d;
  --brand-soft:#eef8f6;
  --brand-border:#bfe5df;
  --navy:#0f2433;
  --navy-soft:#1c3648;
  --radius-sm:8px;
  --radius-md:12px;
  --shadow-xs:0 1px 2px rgba(15,23,42,.04);
  --shadow-sm:0 4px 16px rgba(15,23,42,.05);
  --font-sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --font-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
  --max-w:1080px;
}
*,*::before,*::after{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-sans);line-height:1.6;font-size:16px;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:3px}
a:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
code{font-family:var(--font-mono);font-size:.86em;background:var(--surface-subtle);padding:1px 5px;border-radius:4px;color:var(--ink)}
.wrap{max-width:var(--max-w);margin:0 auto;padding:0 24px}

.site-nav{position:sticky;top:0;z-index:40;background:rgba(255,255,255,.92);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.nav-inner{max-width:var(--max-w);margin:0 auto;padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap}
.brand{display:inline-flex;align-items:center;gap:11px;color:var(--ink);font-weight:750;font-size:1rem;letter-spacing:-.015em}
.brand:hover{text-decoration:none}
.brand-mark{width:32px;height:30px;border-radius:8px;background:var(--navy);color:#f8fafc;display:grid;place-items:center;font-size:.72rem;font-weight:800;letter-spacing:-.02em;flex-shrink:0}
.nav-links{display:flex;align-items:center;gap:22px;flex-wrap:wrap;font-size:.92rem;font-weight:500}
.nav-links a{color:var(--ink-secondary)}
.nav-links a:hover{color:var(--ink);text-decoration:none}

.hero{background:linear-gradient(180deg,#ffffff 0%,#f6f7f9 100%);border-bottom:1px solid var(--border);padding:56px 0 46px}
.hero-inner{max-width:780px}
.eyebrow{display:inline-block;font-size:.76rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--brand);margin-bottom:12px}
.hero h1{margin:0 0 14px;font-size:clamp(1.95rem,4vw,2.75rem);line-height:1.14;letter-spacing:-.03em;font-weight:800;color:var(--ink)}
.hero-lead{margin:0 0 26px;font-size:1.08rem;line-height:1.62;color:var(--ink-secondary);max-width:66ch}
.btn-row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:10px 16px;border-radius:var(--radius-sm);font-weight:650;font-size:.9rem;line-height:1.2;border:1px solid transparent;cursor:pointer;transition:background-color .15s ease,border-color .15s ease,color .15s ease;text-decoration:none}
.btn:hover{text-decoration:none}
.btn-primary{background:var(--brand);color:#ffffff}
.btn-primary:hover{background:var(--brand-hover)}
.btn-secondary{background:var(--surface);color:var(--ink);border-color:var(--border-strong)}
.btn-secondary:hover{background:var(--surface-subtle);border-color:#94a3b8}
.btn-sm{padding:8px 13px;font-size:.85rem}

.section{padding:52px 0}
.section-alt{background:var(--surface);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.section-head{margin-bottom:24px;max-width:720px}
.section-head h2{margin:0 0 6px;font-size:clamp(1.35rem,2.4vw,1.7rem);letter-spacing:-.025em;font-weight:780;color:var(--ink)}
.section-head p{margin:0;color:var(--muted);font-size:.95rem}

.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.grid-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);padding:22px 24px;box-shadow:var(--shadow-xs);display:flex;flex-direction:column;justify-content:space-between;gap:14px}
.badge{display:inline-block;align-self:flex-start;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--brand);background:var(--brand-soft);border:1px solid var(--brand-border);padding:3px 9px;border-radius:999px;margin-bottom:8px}
.badge-muted{color:var(--ink-secondary);background:var(--surface-subtle);border-color:var(--border)}
.card h3{margin:0 0 6px;font-size:1.14rem;font-weight:760;letter-spacing:-.015em;color:var(--ink)}
.card p{margin:0;font-size:.92rem;color:var(--muted);line-height:1.58}
.meta{margin-top:12px;font-size:.82rem;color:var(--ink-secondary);background:var(--surface-subtle);padding:7px 10px;border-radius:6px;word-break:break-word}
.cmd{margin:10px 0 0;background:var(--navy);color:#e2e8f0;padding:10px 12px;border-radius:var(--radius-sm);overflow-x:auto;font-family:var(--font-mono);font-size:.8rem;line-height:1.45}
.cmd code{background:transparent;padding:0;color:inherit;font-size:inherit}
.actions{display:flex;flex-wrap:wrap;gap:8px;padding-top:12px;border-top:1px solid var(--border)}

.alt-bar{margin-top:20px;padding:14px 18px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:.88rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:6px 18px}
.alt-bar strong{color:var(--ink-secondary)}

.steps-list{margin:0;padding:0;list-style:none;display:grid;gap:10px;counter-reset:step}
.steps-list li{counter-increment:step;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:13px 16px 13px 48px;position:relative;font-size:.93rem;color:var(--ink-secondary)}
.steps-list li::before{content:counter(step);position:absolute;left:14px;top:13px;width:24px;height:24px;border-radius:50%;background:var(--brand-soft);border:1px solid var(--brand-border);color:var(--brand);font-size:.78rem;font-weight:800;display:grid;place-items:center}
.steps-list li b{color:var(--ink)}

.two-col{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.info-box{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);padding:20px 22px;box-shadow:var(--shadow-xs)}
.info-box h3{margin:0 0 10px;font-size:1.02rem;font-weight:750;color:var(--ink)}
.info-box ul{margin:0;padding-left:18px;color:var(--ink-secondary);font-size:.91rem}
.info-box li{margin-bottom:6px}
.info-box li:last-child{margin-bottom:0}

.site-footer{background:var(--surface);border-top:1px solid var(--border);padding:28px 0;font-size:.86rem;color:var(--muted)}
.footer-inner{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px 24px}
.footer-links{display:flex;flex-wrap:wrap;gap:16px}
.footer-links a{color:var(--ink-secondary)}
.footer-links a:hover{color:var(--brand)}

@media(max-width:920px){
  .grid-3{grid-template-columns:1fr}
}
@media(max-width:760px){
  .grid,.two-col{grid-template-columns:1fr}
  .hero{padding:40px 0 34px}
  .section{padding:38px 0}
}
</style>
</head>
<body>
<header class="site-nav">
  <div class="nav-inner">
    <a class="brand" href="#top">
      <span class="brand-mark" aria-hidden="true">EAM</span>
      <span>EAM Toolfamilie</span>
    </a>
    <nav class="nav-links" aria-label="Hauptnavigation">
      <a href="#werkzeuge">Werkzeuge</a>
      <a href="#python-plattform">Python &amp; Open WebUI</a>
      <a href="#workflow">Workflow</a>
      <a href="#archimate">ArchiMate</a>
      <a href="#chatbot">Chatbot</a>
      <a href="https://estel.email/">estel.email</a>
    </nav>
  </div>
</header>

<section id="top" class="hero">
  <div class="wrap">
    <div class="hero-inner">
      <span class="eyebrow">EAM Toolfamilie &middot; Release ${version}</span>
      <h1>Werkzeuge für Architekturmodelle.</h1>
      <p class="hero-lead">
        Erstellen, prüfen, vergleichen und analysieren von Modellen nach <strong>NAF 4 / UAF</strong> (ADMBw &amp; eigene MDG-XMLs),
        <strong>ArchiMate 3.2</strong> und <strong>BPMN 2.0</strong> — lokal im Browser, als Python-CLI/WebUI oder Container.
      </p>
      <div class="btn-row">
        <a class="btn btn-primary" href="${releases}">Release ${version} ansehen</a>
        <a class="btn btn-secondary" href="${repo}">Quelltext &amp; README (GitHub)</a>
      </div>
    </div>
  </div>
</section>

<main>
  <section id="werkzeuge" class="section">
    <div class="wrap">
      <div class="grid">
${cards}
      </div>
      <div class="alt-bar">
        <span><strong>SharePoint / IIS (.aspx):</strong>
          <a href="https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.aspx">EAM-AI-Suite.aspx</a> &middot;
          <a href="https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.aspx">EAM-Suite.aspx</a> &middot;
          <a href="https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/BPMN-Studio.aspx">BPMN-Studio.aspx</a> &middot;
          <a href="https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/Sichten-Archiv.aspx">Sichten-Archiv.aspx</a>
        </span>
        <span><strong>Englisch:</strong> <a href="EAM-Suite-en.html">EAM-Suite-en.html</a></span>
      </div>
    </div>
  </section>

  <section id="python-plattform" class="section section-alt">
    <div class="wrap">
      <div class="section-head">
        <h2>EAM AI Suite Python — CLI, Container &amp; Open WebUI</h2>
        <p>Derselbe abhängigkeitsfreie Python-Kern (<code>eam-ai</code>) für Terminal, WebUI, Docker-Server, Stdlib-MCP und direkte Einbindung als Tool, Pipe oder Skill in Open WebUI.</p>
      </div>
      <div class="grid-3">
${python_cards}
      </div>
    </div>
  </section>

  <section id="workflow" class="section">
    <div class="wrap">
      <div class="section-head">
        <h2>Workflow in 7 Stufen</h2>
        <p>Von der MDG-Technologie bis zum geprüften Modell — durchgängig über Browser, CLI, WebUI und MCP.</p>
      </div>
      <ol class="steps-list">
        <li><b>MDG einlesen.</b> Beliebige MDG-XML dynamisch parsen (Stereotype, <code>metarelationships</code>, Tags, Viewpoints).</li>
        <li><b>Startpaket übernehmen.</b> Standardelemente (StEKa, Kataloge) mit EA-/NATO-GUIDs und <code>t_xref</code> unverändert halten.</li>
        <li><b>Prosa &amp; Tabellen aufnehmen.</b> Text, DOCX, PDF, Bilder oder CSV — adaptiv gechunked auch für lokale 4k–16k-Modelle.</li>
        <li><b>Modell bauen.</b> Verlustfrei in <code>.qea</code>, <code>.xmi</code> und <code>.json</code> sowie als Projektion nach ArchiMate 3.2 <code>.xml</code>.</li>
        <li><b>Validieren &amp; reparieren.</b> MDG-Konformität, ArchiMate-3.2-Matrix (Python &amp; Browser) und regelbasierte Reparatur-Vorschau ohne KI.</li>
        <li><b>QS, Diff &amp; Herkunft.</b> Pfad-/Impact-Analyse, Waisen, Modell-Diff &amp; Undo, Textabdeckung und Sprung zum Originalabsatz (<code>source_ref</code>).</li>
        <li><b>Sichten &amp; Archiv.</b> Optionale EA-Diagramme (<code>--sichten</code>) oder bit-identisches Auslagern und Zurückspielen per Sichten-Archiv.</li>
      </ol>
    </div>
  </section>

  <section id="archimate" class="section section-alt">
    <div class="wrap">
      <div class="section-head">
        <h2>ArchiMate 3.2 — Einordnung</h2>
        <p>Kern-Metamodell ist NAF 4 / UAF (MDG); ArchiMate 3.2 wird als Brücken- und Prüf-Format unterstützt.</p>
      </div>
      <div class="two-col">
        <div class="info-box">
          <h3>Was funktioniert</h3>
          <ul>
            <li>Deterministische Export-Projektion NAF 4 / UAF &rarr; ArchiMate 3.2 (<code>eam-ai archimate</code>) inkl. Näherungsreport.</li>
            <li>Native Prüfung gegen die offizielle 61&times;61-Beziehungsmatrix in Python (<code>archimate-check</code>), MCP und direkt im Browser.</li>
            <li>Verlustfreier Rückweg nach <code>.qea</code>/IR für Dateien aus dem eigenen Exporter.</li>
          </ul>
        </div>
        <div class="info-box">
          <h3>Bewusste Grenzen</h3>
          <ul>
            <li>Kein nativer KI-Modellbau direkt in ArchiMate 3.2 — die KI baut NAF 4 / UAF bzw. die geladene MDG.</li>
            <li>Keine automatische 1:1-Übersetzung fremder ArchiMate-Modelle in NAFv4/UAF-Stereotype.</li>
            <li>Keine verlustfreie 1:1-Gleichheit zwischen UAF- und ArchiMate-Metamodell.</li>
          </ul>
        </div>
      </div>
    </div>
  </section>

  <section id="chatbot" class="section">
    <div class="wrap">
      <div class="section-head">
        <h2>ADMBw-Regeldateien im eigenen Chatbot</h2>
        <p>Die sechs Markdown-Dateien aus dem ADMBw Extraktor dienen als Wissensquelle in ChatGPT, Claude, Gemini oder Open WebUI.</p>
      </div>
      <ol class="steps-list">
        <li><b>Exportieren.</b> Im ADMBw Extraktor die MDG-XML laden und alle 6 Wissensdateien (<code>admbw-knowledge-*.md</code>, <code>admbw-meta.md</code>) speichern.</li>
        <li><b>Als Knowledge hinterlegen.</b> In Open WebUI (Workspace &rarr; Knowledge), ChatGPT/Claude-Projekten oder lokalem Kontext einbinden.</li>
        <li><b>Prompt + kleine Schritte.</b> <code>ADMBw-Prompt.md</code> als System-Anweisung setzen und abschnittsweise arbeiten (max. 10–15 Elemente je Schritt).</li>
        <li><b>Prüfen bleibt Werkzeugsache.</b> Der Chatbot schlägt vor — valide Prüfung übernehmen EAM Suite, EAM AI Suite oder <code>eam-ai validate</code>.</li>
      </ol>
    </div>
  </section>
</main>

<footer class="site-footer">
  <div class="wrap footer-inner">
    <div>EAM Toolfamilie &middot; Release ${version} &middot; <a href="${releases}">Alle Releases</a> &middot; <a href="${sums}">SHA256SUMS</a></div>
    <div class="footer-links">
      <a href="https://estel.email/">Michael Estel (estel.email)</a>
      <a href="https://estel.email/impressum.html">Impressum</a>
      <a href="https://estel.email/datenschutz.html">Datenschutz</a>
    </div>
  </div>
</footer>
</body>
</html>
"""


def _dl(name: str) -> str:
    return f"{REPO_URL}/releases/latest/download/{name}"


def _menschlich(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB".replace(".", ",")
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _karte(titel: str, badge: str, text: str, datei: str, label: str,
           schritte: list[str] | None = None, extra: str = "", groesse: str = "",
           slug: str = "", weitere: list[tuple[str, str]] | None = None,
           seiten: str = "", muted_badge: bool = False) -> str:
    del schritte  # bewusst keine redundanten 1-2-3-Listen mehr in den Karten
    meta = html.escape(datei) + (f" &middot; {html.escape(groesse)}" if groesse else "")
    kennung = f' id="{html.escape(slug)}"' if slug else ""
    badge_cls = "badge badge-muted" if muted_badge else "badge"
    aktionen: list[str] = []
    if seiten:
        aktionen.append(f'<a class="btn btn-primary btn-sm" href="{html.escape(seiten)}">Im Browser öffnen</a>')
        aktionen.append(f'<a class="btn btn-secondary btn-sm" href="{html.escape(_dl(datei))}">{html.escape(label)}</a>')
    else:
        aktionen.append(f'<a class="btn btn-primary btn-sm" href="{html.escape(_dl(datei))}">{html.escape(label)}</a>')
    for andere, andere_label in (weitere or []):
        aktionen.append(f'<a class="btn btn-secondary btn-sm" href="{html.escape(_dl(andere))}">{html.escape(andere_label)}</a>')
    return f"""<article class="card"{kennung}>
  <div>
    <span class="{badge_cls}">{html.escape(badge)}</span>
    <h3>{html.escape(titel)}</h3>
    <p>{html.escape(text)}</p>
    <div class="meta">{meta}</div>
    {extra}
  </div>
  <div class="actions">{"".join(aktionen)}</div>
</article>"""


def schreibe_startseite(dist: Path, version: str) -> Path:
    """Schreibt eine klickbare Einstiegsseite im estel.email-Design; keine externen Ressourcen."""
    def groesse(name: str) -> str:
        datei = dist / name
        return _menschlich(datei.stat().st_size) if datei.is_file() else ""

    karten = [
        _karte(
            "EAM AI Suite", "KI · Browser",
            "Aus Prosa, DOCX, PDF, Bild oder Tabelle iterativ (auch 4k–16k) MDG-geprüfte Modelle bauen, live prüfen (ArchiMate-Matrix, Diff, Undo, Auto-Repair), befragen und per Sprache weiterbauen.",
            "EAM-AI-Suite.html", "HTML herunterladen",
            groesse=groesse("EAM-AI-Suite.html"),
            slug="ai-suite",
            seiten=SEITEN + "eam-ai-suite/",
        ),
        _karte(
            "EAM Suite", "Offline · Ohne KI",
            "Vorhandene Modelle (.qea, .xmi, .json, ArchiMate-.xml) laden, verschmelzen, vergleichen (Diff & Undo), regelbasiert reparieren und gegen MDG bzw. ArchiMate-3.2-Matrix prüfen.",
            "EAM-Suite.html", "HTML herunterladen",
            groesse=groesse("EAM-Suite.html"),
            slug="suite",
            seiten=SEITEN + "eam-suite/",
            muted_badge=True,
        ),
        _karte(
            "BPMN Studio", "Prozesse · L3 ↔ L4",
            "BPMN 2.0 zeichnen, gegen 15 L4-Regeln prüfen, ADMBw-konform machen, mit L3-Architekturkatalogen (GUIDs & Represents) abgleichen und nach .qea, .xmi, .xml, .json, SVG & PNG exportieren.",
            "BPMN-Studio.html", "HTML herunterladen",
            groesse=groesse("BPMN-Studio.html"),
            slug="bpmn",
            seiten=SEITEN + "bpmn-studio/",
        ),
        _karte(
            "ADMBw Extraktor", "MDG-Regelwerk",
            "MDG-XML durchsuchen (Stereotype, Topologie, Viewpoints, Tags) und als sechs Markdown-Wissensdateien oder JSON exportieren — im Browser oder per Python.",
            "ADMBw-Extraktor.html", "HTML herunterladen",
            groesse=groesse("ADMBw-Extraktor.html"),
            slug="mdg",
            weitere=[("admbw-extraktor.py", "Python-Skript")],
            seiten=SEITEN + "admbw-extraktor/",
            muted_badge=True,
        ),
        _karte(
            "Sichten-Archiv", "Sichten · SHA-256",
            "Diagrammsichten und Layout aus einer .qea bit-identisch in ein .archiv auslagern und nach Pipeline-Läufen verlustfrei zurückspielen.",
            "Sichten-Archiv.html", "HTML herunterladen",
            groesse=groesse("Sichten-Archiv.html"),
            slug="sichten-archiv",
            seiten=SEITEN + "sichten-archiv/",
            muted_badge=True,
        ),
        _karte(
            "EAM Analyzer", "Open WebUI & MCP",
            "Modelle (.qea, .xmi, ArchiMate-.xml, .json) in Open WebUI oder per MCP befragen, gegen MDG/ArchiMate prüfen sowie Impact- und Pfadanalysen fahren.",
            "eam_qea_analyzer_openwebui.py", "Open-WebUI-Tool",
            groesse=groesse("eam_qea_analyzer_openwebui.py"),
            slug="qea-analyzer",
            weitere=[("eam-qea-mcp-server.py", "MCP-Server")],
            muted_badge=True,
        ),
    ]
    python_karten = [
        _karte(
            "Python CLI & WebUI", "Paket · Stdlib-MCP",
            "Kommandozeile eam-ai (build, convert, validate, qs, diff, repair, mcp, stufe1–4, serve) sowie WebUI mit Live-Viewer, Chat with Data, NL-Edit, Diff, Auto-Repair & Undo.",
            "eam-ai-suite-python.zip", "ZIP herunterladen",
            extra='<pre class="cmd"><code>pip install ./eam-ai-suite-python &amp;&amp; eam-ai serve</code></pre>',
            groesse=groesse("eam-ai-suite-python.zip"),
            slug="python",
        ),
        f"""<article class="card" id="container">
  <div>
    <span class="badge">Container &middot; Auto-Sync</span>
    <h3>Docker-Image (GHCR)</h3>
    <p>Fertiger Webdienst inkl. <code>eam-ai</code>-CLI und Regelwerk ohne lokale Python-Installation; baut bei jedem grünen Push auf <code>main</code> automatisch neu.</p>
    <div class="meta">ghcr.io/mitchel85/eam-toolfamilie:latest &middot; Tag v{html.escape(version)}</div>
    <pre class="cmd"><code>docker run --rm -p 8080:8080 ghcr.io/mitchel85/eam-toolfamilie:latest</code></pre>
  </div>
  <div class="actions">
    <a class="btn btn-primary btn-sm" href="{html.escape(REPO_URL + "/pkgs/container/eam-toolfamilie")}">Container-Seite</a>
  </div>
</article>""",
        _karte(
            "Open WebUI Tool, Pipe & Skill", "Open WebUI · Dual-Modus",
            "Bindet EAM AI Suite Python direkt in Open WebUI ein — wahlweise gegen den GHCR-Container (mode=http) oder lokal (mode=local). Inklusive Pipe-Funktion, Skill-Markdown und Docker-Compose-Vorlage.",
            "EAM-AI-Suite-OpenWebUI.zip", "Komplettpaket (.zip)",
            groesse=groesse("EAM-AI-Suite-OpenWebUI.zip"),
            slug="openwebui",
            weitere=[
                ("eam_ai_suite_openwebui.py", "Tool (.py)"),
                ("eam_ai_suite_pipe.py", "Pipe (.py)"),
            ],
        ),
    ]
    ziel = dist / STARTSEITE
    ziel.write_text(
        Template(_START_TEMPLATE).substitute(
            cards="\n".join(karten),
            python_cards="\n".join(python_karten),
            version=html.escape(version),
            releases=f"{REPO_URL}/releases",
            repo=REPO_URL,
            sums=_dl("SHA256SUMS"),
        ),
        encoding="utf-8",
        newline="\n",
    )
    return ziel


def main() -> int:
    ap = argparse.ArgumentParser(description="Auslieferungen nach dist/ einsammeln.")
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--version", default=None, help="Release-Version für das Quell-Archiv (Default: Tag)")
    args = ap.parse_args()
    dist = (ROOT / args.dist).resolve()
    dist.mkdir(parents=True, exist_ok=True)
    raeume_altbestand(dist)

    zeilen: list[str] = []
    vorhanden: list[tuple[str, str, str]] = []
    ausgeliefert: list[tuple[str, Path]] = []
    fehlend: list[str] = []
    for rel, zielname, produkt, hinweis in AUSLIEFERUNGEN:
        quelle = ROOT / rel
        if not quelle.is_file():
            fehlend.append(rel)
            continue
        ziel = dist / zielname
        ziel.parent.mkdir(parents=True, exist_ok=True)
        if zielname in KOPFZEILE:
            # Marke nur in der Auslieferung, nicht in der Engine: der Parser
            # selbst bleibt technologieneutral (tests/test_technology_agnostic).
            ziel.write_text(KOPFZEILE[zielname] + quelle.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(quelle, ziel)
        groesse = f"{ziel.stat().st_size:,}".replace(",", ".")
        zeilen.append(f"| `{zielname}` | {produkt} | {groesse} B | `{sha256(ziel)[:16]}…` |")
        vorhanden.append((zielname, produkt, hinweis))
        ausgeliefert.append((zielname, ziel))

    version = release_version(args.version)
    archiv = baue_quellarchiv(dist, version)
    arch_name = archiv.name
    produkt = "EAM AI Suite Python — Quellstand (Archiv)"
    hinweis = (
        "Entpacken, dann `pip install ./eam-ai-suite-python` ergibt den Befehl `eam-ai` "
        "(CLI, Webdienst, MCP)."
    )
    groesse = f"{archiv.stat().st_size:,}".replace(",", ".")
    zeilen.append(f"| `{arch_name}` | {produkt} | {groesse} B | `{sha256(archiv)[:16]}…` |")
    vorhanden.append((arch_name, produkt, hinweis))
    ausgeliefert.append((arch_name, archiv))

    # Stabile Kopie für direkte Links in README und Einstiegsseite: der
    # Dateiname bleibt über Releases hinweg gleich, die Version steht im Inhalt.
    stabil = dist / "eam-ai-suite-python.zip"
    shutil.copyfile(archiv, stabil)
    groesse = f"{stabil.stat().st_size:,}".replace(",", ".")
    zeilen.append(
        f"| `{stabil.name}` | EAM AI Suite Python — immer die neueste Fassung | {groesse} B | "
        f"`{sha256(stabil)[:16]}…` |"
    )
    ausgeliefert.append((stabil.name, stabil))

    # App-Buendel: je Anwendung ein ZIP mit Kurzanleitung (Auto-Zip).
    for buendel in APP_ZIPS:
        app_zip = baue_app_zip(dist, buendel, version)
        groesse = f"{app_zip.stat().st_size:,}".replace(",", ".")
        zeilen.append(
            f"| `{app_zip.name}` | {buendel['produkt']} | {groesse} B | "
            f"`{sha256(app_zip)[:16]}…` |"
        )
        vorhanden.append((app_zip.name, buendel["produkt"], buendel["text"]))
        ausgeliefert.append((app_zip.name, app_zip))

    start = schreibe_startseite(dist, version)
    start_groesse = f"{start.stat().st_size:,}".replace(",", ".")
    zeilen.insert(
        0,
        f"| `{STARTSEITE}` | Einstiegsseite — alle Werkzeuge mit Download-Knopf | "
        f"{start_groesse} B | `{sha256(start)[:16]}…` |",
    )
    ausgeliefert.append((STARTSEITE, start))

    katalog = [
        "# Auslieferungen zum Herunterladen",
        "",
        f"**Einstieg:** [START-HIER.html]({_dl(STARTSEITE)}) — alle Werkzeuge "
        "in einer Übersicht.",
        "",
        "Jede Datei ist eigenständig: herunterladen, öffnen, arbeiten. Die HTML-Dateien "
        "funktionieren ohne Netz und ohne Installation; die Apps selbst brauchen kein "
        "Konto. Der Download ist ohne GitHub-Konto möglich.",
        "",
        "| Datei | Produkt | Größe | SHA-256 (Anfang) |",
        "|---|---|---|---|",
        *zeilen,
        "",
        "## Welche Datei wofür",
        "",
    ]
    for zielname, produkt, hinweis in vorhanden:
        katalog += [f"**{produkt}** — `{zielname}`", "", f"{hinweis}", ""]

    katalog += [
        "## Einstieg und stabile Links",
        "",
        f"**Einstiegsseite** — `{STARTSEITE}`",
        "",
        "Alle Werkzeuge als Übersicht mit einem Download-Knopf. ",
        "Einstieg und Orientierung, wenn unklar ist, welche Datei gebraucht wird.",
        "",
        "**Python ohne Versionsnummer** — `eam-ai-suite-python.zip`",
        "",
        "Immer die neueste Fassung; der Dateiname bleibt über Releases hinweg "
        "gleich. Die versionierte ZIP daneben ist derselbe Stand zum Archivieren.",
        "",
    ]

    katalog += [
        "## Python und Container",
        "",
        "```bash",
        "# CLI und Webdienst aus dem Quellstand",
        f"unzip {arch_name}",
        "pip install ./eam-ai-suite-python",
        "eam-ai --version",
        "",
        "# Container (Webdienst mit Upload und Job-Status)",
        "docker run --rm -p 127.0.0.1:8080:8080 ghcr.io/mitchel85/eam-toolfamilie:latest",
        "```",
        "",
        "Der Container enthält dieselbe Kette: Prosa, Handbuch, PDF oder Bild hinein, "
        "`.qea` samt Befundbericht zurück.",
        "",
    ]
    (dist / "README.md").write_text("\n".join(katalog), encoding="utf-8", newline="\n")

    # Manifest und Beleg führen ausschließlich die ausgelieferten Dateien.
    releases = ["# Release-Inhalt", "", "| Datei | Bytes | SHA-256 |", "|---|---|---|"]
    sums = []
    for name, datei in sorted(ausgeliefert):
        d = sha256(datei)
        releases.append(f"| `{name}` | {datei.stat().st_size} | `{d}` |")
        sums.append(f"{d}  {name}")
    (dist / "RELEASES.md").write_text("\n".join(releases) + "\n", encoding="utf-8", newline="\n")
    (dist / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")

    for f in fehlend:
        print(f"FEHLT: {f} — zuerst bauen")
    print(f"{len(vorhanden)} Auslieferungen, {len(sums)} Dateien in {dist}")
    return 0 if not fehlend else 1


if __name__ == "__main__":
    raise SystemExit(main())
