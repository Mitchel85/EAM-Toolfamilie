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
        "Prosa oder Handbuch hinein, `.qea` heraus: prüfen, ansehen, bearbeiten.",
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
        "EAM Suite v8.4 — eine HTML-Datei",
        "Mehrere Modelle laden, verschmelzen, bearbeiten und zurückschreiben; ohne KI.",
    ),
    (
        "apps/html-editor/dist/EAM-Suite.aspx",
        "EAM-Suite.aspx",
        "EAM Suite v8.4 — SharePoint-Fassung",
        "Dieselbe Bearbeiten-App als ASPX mit BOM für SharePoint/IIS; ohne KI.",
    ),
    (
        "apps/html-editor/dist/EAM-Suite-en.html",
        "EAM-Suite-en.html",
        "EAM Suite v8.4 — englische Fassung",
        "Dieselbe App mit englischer Oberfläche; Modellinhalte und Dateiformat bleiben unverändert.",
    ),
    (
        "apps/bpmn-studio/dist/BPMN-Studio.html",
        "BPMN-Studio.html",
        "BPMN Studio — eine HTML-Datei",
        "Prozesse als BPMN 2.0 anzeigen, bearbeiten, prüfen, ADMBw-konform machen; Export als XML, SVG und PNG. Offline im Browser.",
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
        "apps/html-analyzer/dist/EAM-QEA-Analyzer.html",
        "EAM-QEA-Analyzer.html",
        "EAM Analyzer — eine HTML-Datei",
        "Modelle abfragen (`.qea` und `.xmi`): suchen, zählen, vergleichen, erklären. Offline im Browser, ohne KI-Anbindung.",
    ),
    (
        "apps/html-analyzer/dist/EAM-QEA-Analyzer.aspx",
        "EAM-QEA-Analyzer.aspx",
        "EAM Analyzer — SharePoint-Fassung",
        "Dieselbe Abfrage-App als ASPX mit BOM für SharePoint/IIS.",
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
        "text": "Text, Handbuch, PDF oder Bild einlesen und daraus ein Modell erzeugen; prüfen, ansehen, bearbeiten, als `.qea`, `.xmi` oder `.json` speichern.",
        "dateien": (
            ("EAM-AI-Suite.html", "apps/html-suite/dist/EAM-AI-Suite.html", "Hauptfassung: im Browser öffnen"),
            ("EAM-AI-Suite.aspx", "apps/html-suite/dist/EAM-AI-Suite.aspx", "SharePoint-/IIS-Fassung mit BOM"),
        ),
        "start": ("EAM-AI-Suite.html im Browser öffnen", "Quelle angeben (Text, Handbuch, PDF, Bild)", "Modell erzeugen und speichern"),
    },
    {
        "name": "EAM-Analyzer",
        "produkt": "EAM Analyzer — HTML, Open-WebUI-Tool und MCP-Server",
        "text": "Vorhandene Modelle befragen (`.qea` und `.xmi`): als HTML im Browser, als Werkzeug in Open WebUI oder als MCP-Server für Open WebUI, Claude Desktop und VS Code.",
        "dateien": (
            ("EAM-QEA-Analyzer.html", "apps/html-analyzer/dist/EAM-QEA-Analyzer.html", "HTML-Fassung: im Browser öffnen"),
            ("EAM-QEA-Analyzer.aspx", "apps/html-analyzer/dist/EAM-QEA-Analyzer.aspx", "SharePoint-/IIS-Fassung mit BOM"),
            ("eam_qea_analyzer_openwebui.py", "apps/mcp/eam_qea_tool.py", "Open-WebUI-Tool: unter „Werkzeuge“ einfügen"),
            ("eam-qea-mcp-server.py", "apps/mcp/mcp_server.py", "MCP-Server: starten und im Client verbinden"),
        ),
        "start": ("EAM-QEA-Analyzer.html im Browser öffnen", "Modell laden (`.qea` oder `.xmi`)", "Fragen stellen"),
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
        "produkt": "BPMN Studio — HTML und Python",
        "text": "BPMN 2.0 lesen, anzeigen, bearbeiten und prüfen; auf Knopfdruck ADMBw-konform machen; Export als XML, SVG und PNG.",
        "dateien": (
            ("BPMN-Studio.html", "apps/bpmn-studio/dist/BPMN-Studio.html", "HTML-Fassung: im Browser öffnen"),
            ("python/bpmn", "packages/bpmn", "Python-Paket: `PYTHONPATH=python python3 -m bpmn.cli pruefen prozess.bpmn`"),
        ),
        "start": ("BPMN-Studio.html im Browser öffnen", "Prozess laden oder zeichnen", "Prüfen, ADMBw-konform machen, exportieren"),
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
    beispiele = ROOT / "packages" / "core" / "examples" / "offline"
    if beispiele.is_dir():
        dateien += [
            (f"eam-ai-suite-python/examples/offline/{pfad.name}", pfad)
            for pfad in sorted(beispiele.glob("*"))
            if pfad.is_file()
        ]
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
<title>EAM Toolfamilie — Werkzeuge herunterladen</title>
<style>
:root{--ink:#12213a;--muted:#5b6b82;--line:#dbe3ee;--blue:#0b57d0;--blue2:#0842a0;--bg:#f2f6fb;--card:#fff;--green:#0f7b45}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;line-height:1.5}
a{color:var(--blue)}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.hero{background:linear-gradient(135deg,#0b1f3a 0%,#123a6b 60%,#0b57d0 100%);color:#fff;padding:46px 0 40px;margin-bottom:26px}
.kicker{font-size:13px;letter-spacing:.08em;text-transform:uppercase;opacity:.8;font-weight:700}
h1{font-size:clamp(28px,4vw,44px);line-height:1.12;margin:12px 0 14px;letter-spacing:-.02em}
.hero p{font-size:18px;max-width:760px;opacity:.94;margin:0 0 20px}
.steps{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 24px}
.steps span{background:rgba(255,255,255,.13);border:1px solid rgba(255,255,255,.22);padding:8px 12px;border-radius:999px;font-size:14px}
.steps b{color:#fff}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--blue);color:#fff;text-decoration:none;font-weight:800;padding:13px 18px;border-radius:12px;border:1px solid rgba(0,0,0,.05)}
.btn:hover{background:var(--blue2)}
.btn.light{background:#fff;color:#0b3b7a}
.btn.light:hover{background:#eaf1ff}
.note{background:#fff;border:1px solid var(--line);border-left:6px solid var(--green);border-radius:12px;padding:14px 16px;margin:22px 0;color:#24364f}
.note b{color:#0f5d38}
h2{font-size:26px;margin:30px 0 6px;letter-spacing:-.02em}
.lead{color:var(--muted);margin:0 0 18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;display:flex;flex-direction:column;box-shadow:0 6px 22px rgba(18,33,58,.06)}
.card.wide{grid-column:1/-1}
.card:hover{box-shadow:0 10px 30px rgba(18,33,58,.11)}
.badge{display:inline-block;align-self:flex-start;background:#e8f0fe;color:#0b4bb3;font-size:12px;font-weight:800;padding:5px 9px;border-radius:999px;margin-bottom:10px}
.card h3{font-size:21px;margin:0 0 6px}
.card p{color:#35465e;margin:0 0 12px}
.meta{font-size:13.5px;color:#4a5b73;margin:0 0 14px;word-break:break-word}
.card .btn{margin-top:auto;word-break:break-word;text-align:center}
.card .secondary{display:block;margin-top:10px;font-size:13.5px;color:var(--blue);text-decoration:underline}
.card ol{margin:12px 0 0;padding-left:20px;color:#2f4058;font-size:14.5px}
.card ol li{margin:3px 0}
.quick{background:#e8f0fe;border:1px solid #c8d9f8;border-radius:14px;padding:12px 16px;margin:0 0 16px;color:#173a6b}
.quick b{color:#0b3b7a}
.quick a{color:#0b3b7a;font-weight:700;text-decoration:underline}
pre{background:#0f1d33;color:#e8eefc;padding:14px;border-radius:10px;overflow:auto;font-size:13px;margin:10px 0 0}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.decision{background:#fff;border:1px solid var(--line);border-radius:16px;padding:8px 22px 18px;margin-top:10px}
.decision li{margin:10px 0;color:#2b3d56}
.decision b{color:var(--ink)}
.footer{color:var(--muted);font-size:14px;padding:34px 0 44px;border-top:1px solid var(--line);margin-top:30px}
@media(max-width:560px){.hero{padding:34px 0 30px}.card{padding:16px}.decision{padding:4px 14px 12px}}
</style>
</head>
<body>
<header class="hero">
  <div class="wrap">
    <div class="kicker">EAM Toolfamilie · Release ${version}</div>
    <h1>Werkzeuge für<br>Architekturmodelle</h1>
    <a class="btn light" href="${releases}">Alle Dateien im Release ansehen</a>
    <a class="btn light" href="${repo}">Quelltext und README</a>
  </div>
</header>
<main class="wrap">
  <h2>Welches Werkzeug wofür</h2>
  <p class="lead">Eine Karte je Werkzeug. Dateiname und Größe stehen darunter.</p>
  <div class="quick"><b>Schnellwahl:</b> <a href="#ai-suite">Bauen → EAM AI Suite</a> · <a href="#suite">Prüfen und Bearbeiten → EAM Suite</a> · <a href="#bpmn">Prozesse → BPMN Studio</a> · <a href="#mdg">Nachschlagen → ADMBw Extraktor</a> · <a href="#qea-analyzer">Abfragen → EAM Analyzer</a></div>
  <section class="grid">
${cards}
  </section>
  <div class="quick"><b>Ohne Herunterladen:</b> jede HTML-App läuft auch direkt im Browser unter
  <a href="https://mitchel85.github.io/EAM-Toolfamilie/">mitchel85.github.io/EAM-Toolfamilie</a> —
  die einzelnen Seiten stehen in den Karten als „Im Browser öffnen“.</div>
  <p class="lead" style="margin-top:14px">SharePoint-Fassung: <a href="https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.aspx">EAM-AI-Suite.aspx</a> — dieselbe App für SharePoint/IIS.<br>
  Englische Fassung: <a href="EAM-Suite-en.html">EAM-Suite-en.html</a> — dieselbe EAM Suite mit englischer Oberfläche.</p>

  <h2>Auswahl nach Aufgabe</h2>
  <ul class="decision">
    <li><b>Ich habe Text, ein Handbuch, PDF oder ein Bild und will ein Modell bauen.</b> → EAM AI Suite</li>
    <li><b>Ich habe ein Modell (.qea, .xmi oder .json) und will es verstehen und prüfen.</b> → EAM Suite</li>
    <li><b>Ich will Modelle bearbeiten, verschmelzen oder zurückschreiben.</b> → EAM Suite</li>
    <li><b>Ich will nur das Regelwerk nachschlagen.</b> → ADMBw Extraktor</li>
    <li><b>Ich will ein Modell abfragen — im Browser, in Open WebUI oder per MCP.</b> → EAM Analyzer</li>
    <li><b>Ich will Kommandozeile, Webdienst oder MCP.</b> → Python-ZIP</li>
    <li><b>Ich will einen eigenen Server.</b> → Container-Image</li>
  </ul>

  <h2>So entsteht eine Architektur</h2>
  <p class="lead">Der Weg durch die Werkzeuge, in dieser Reihenfolge.</p>
  <ol class="decision">
    <li><b>MDG einlesen.</b> Die Technologie-Datei (XML) wird geladen. Daraus entsteht das Regelwerk: Stereotype, Topologie-Regeln, Viewpoints, Tag-Typen. Die Anzahl hängt vom MDG-Stand ab und wird nicht festgeschrieben.</li>
    <li><b>Startpaket übernehmen — wenn vorhanden.</b> Die Standardelemente (StEKa) kommen als zweite <code>.qea</code> hinein; ihre GUIDs werden wörtlich übernommen, damit Modelle zusammenfinden.</li>
    <li><b>Prosa einlesen.</b> Handbuch, Text oder ein Abschnitt daraus — daraus werden Elemente, Beziehungen und die Herkunft jeder Aussage.</li>
    <li><b>Architektur bauen.</b> Geprüft wird gegen die Regeln der MDG; abstrakte Stereotype dürfen nicht instanziiert werden.</li>
    <li><b>Architektur sehen.</b> Modell im Viewer öffnen: Pakete, Sichten, Beziehungen, Pfade.</li>
    <li><b>Architektur bearbeiten.</b> Korrigieren, Standardelemente nachziehen, als neue <code>.qea</code> speichern.</li>
    <li><b>Ergebnis.</b> Das Modell liegt als <code>.qea</code>, <code>.xmi</code> oder <code>.json</code> vor — alle drei Formate sind gleichwertig und in der ganzen Toolfamilie lesbar.</li>
  </ol>
  <h2>Regeldateien in einem Chatbot nutzen</h2>
  <p class="lead">Die sechs Markdown-Dateien aus dem ADMBw Extraktor sind reine Fachdaten. Jeder Chatbot kann sie als Wissensquelle lesen — ChatGPT, Claude, Gemini, Open WebUI oder ein lokales Modell. Der Chatbot schlägt dann vor; prüfen tut er nicht.</p>
  <ol class="decision">
    <li><b>Dateien erzeugen.</b> Im ADMBw Extraktor die MDG-XML laden und „Alle 6" herunterladen: <code>admbw-knowledge-stereotypes.md</code>, <code>-topology.md</code>, <code>-viewpoints.md</code>, <code>-tagtypes.md</code>, <code>-stereotype-tags.md</code>, <code>admbw-meta.md</code>.</li>
    <li><b>Open WebUI.</b> <i>Workspace → Knowledge → „+"</i>, die sechs Dateien hochladen, Sammlung <i>ADMBw-Regelwerk</i> nennen. Im Chat mit <code>#</code> vor der Frage anhängen — oder unter <i>Workspace → Models</i> beim Modell als Knowledge eintragen, dann greift sie in jedem Chat.</li>
    <li><b>Andere Chatbots.</b> ChatGPT: Projekt anlegen, Dateien hinzufügen (oder Custom GPT → Knowledge). Claude: Projekt → Knowledge. Gemini: Gem oder Notebook mit den Dateien als Quelle. Lokal: Dateien in den Kontext legen oder einen Index bauen.</li>
    <li><b>Master-Prompt.</b> <code>ADMBw-Prompt.md</code> als System-Anweisung setzen, die sechs Wissensdateien als Knowledge. Der Prompt sagt, wie gebaut wird; die Dateien sagen, was erlaubt ist.</li>
    <li><b>Grenzen.</b> Die Dateien sind Daten, keine Befehle. Bei Widerspruch gilt die MDG, nicht die Chat-Antwort.</li>
  </ol>

  <h2>Prüfen</h2>
  <p class="lead">Jede Datei hat eine Prüfsumme. <a href="${sums}">SHA256SUMS herunterladen</a> und danach im Download-Ordner <code>sha256sum -c SHA256SUMS</code> ausführen.</p>

  <div class="footer">
    EAM Toolfamilie · Release ${version} · <a href="${releases}">Alle Releases</a> · <a href="${sums}">SHA256SUMS</a>
  </div>
</main>
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
           schritte: list[str], extra: str = "", groesse: str = "",
           slug: str = "", weitere: list[tuple[str, str]] | None = None,
           seiten: str = "") -> str:
    schritt_html = "".join(f"<li>{s}</li>" for s in schritte)
    meta = html.escape(datei) + (f" · {html.escape(groesse)}" if groesse else "")
    kennung = f' id="{html.escape(slug)}"' if slug else ""
    weitere_html = "".join(
        f'<a class="btn" style="margin-top:8px" href="{html.escape(_dl(andere))}">⬇ {html.escape(andere_label)}</a>'
        for andere, andere_label in (weitere or [])
    )
    seiten_html = (
        f'<a class="secondary" href="{html.escape(seiten)}">Im Browser öffnen (GitHub Pages)</a>'
        if seiten else ""
    )
    return f"""<article class="card"{kennung}>
  <span class="badge">{html.escape(badge)}</span>
  <h3>{html.escape(titel)}</h3>
  <p>{html.escape(text)}</p>
  <div class="meta">{meta}</div>
  <a class="btn" href="{html.escape(_dl(datei))}">⬇ {html.escape(label)}</a>
  {seiten_html}
  {weitere_html}
  {extra}
  <ol>{schritt_html}</ol>
</article>"""


def schreibe_startseite(dist: Path, version: str) -> Path:
    """Schreibt eine klickbare Einstiegsseite; keine externen Ressourcen."""
    def groesse(name: str) -> str:
        datei = dist / name
        return _menschlich(datei.stat().st_size) if datei.is_file() else ""

    karten = [
        _karte(
            "EAM AI Suite", "Bauen",
            "Text, Handbuch, PDF oder Bild einlesen und daraus ein Modell erzeugen; prüfen, ansehen, bearbeiten und als .qea, .xmi oder .json speichern.",
            "EAM-AI-Suite.html", "EAM-AI-Suite.html herunterladen",
            ["Datei herunterladen", "Datei öffnen", "Modell erzeugen"],
            groesse=groesse("EAM-AI-Suite.html"),
            slug="ai-suite",
            seiten=SEITEN + "eam-ai-suite/",
        ),
        _karte(
            "EAM Suite", "Prüfen und bearbeiten",
            "Modelle der Formate .qea, .xmi und .json analysieren und ansehen (Explorer, Sichten, Graph, Pfade), mehrere verschmelzen, bearbeiten und zurückschreiben; ohne KI.",
            "EAM-Suite.html", "EAM-Suite.html herunterladen",
            ["Datei herunterladen", "Datei öffnen", "Modelle bearbeiten"],
            groesse=groesse("EAM-Suite.html"),
            slug="suite",
            seiten=SEITEN + "eam-suite/",
        ),
        _karte(
            "BPMN Studio", "Prozesse",
            "BPMN 2.0 lesen, anzeigen, bearbeiten und prüfen; auf Knopfdruck ADMBw-konform machen; Export als XML, SVG und PNG.",
            "BPMN-Studio.html", "BPMN-Studio.html herunterladen",
            ["Datei herunterladen", "Datei öffnen", "Prozess bearbeiten"],
            groesse=groesse("BPMN-Studio.html"),
            slug="bpmn",
            seiten=SEITEN + "bpmn-studio/",
        ),
        _karte(
            "ADMBw Extraktor", "Nachschlagen und exportieren",
            "MDG-XML laden: Stereotype, Topologie, Viewpoints, Tag-Typen und Stereotyp-Tags durchsuchen; sechs Regeldateien exportieren. Als HTML im Browser oder als Python-Skript.",
            "ADMBw-Extraktor.html", "ADMBw-Extraktor.html herunterladen",
            ["HTML im Browser öffnen oder Python starten", "MDG-XML laden", "Regeldateien exportieren"],
            groesse=groesse("ADMBw-Extraktor.html"),
            slug="mdg",
            weitere=[("admbw-extraktor.py", "Python-Variante herunterladen")],
            seiten=SEITEN + "admbw-extraktor/",
        ),
        _karte(
            "EAM Analyzer", "Abfragen",
            "Vorhandene Modelle der Formate .qea und .xmi befragen: als HTML im Browser, als Open-WebUI-Tool oder als MCP-Server für Open WebUI, Claude Desktop und VS Code.",
            "EAM-QEA-Analyzer.html", "EAM-QEA-Analyzer.html herunterladen",
            ["HTML herunterladen und öffnen", "Modell laden (.qea oder .xmi)", "Modell fragen"],
            groesse=groesse("EAM-QEA-Analyzer.html"),
            slug="qea-analyzer",
            weitere=[
                ("eam_qea_analyzer_openwebui.py", "Open-WebUI-Tool herunterladen"),
                ("eam-qea-mcp-server.py", "MCP-Server herunterladen"),
            ],
            seiten=SEITEN + "eam-analyzer/",
        ),
        _karte(
            "EAM AI Suite Python", "Für Terminal und Server",
            "Kommandozeile <code>eam-ai</code>, Webdienst und MCP. Quellstand als ZIP.",
            "eam-ai-suite-python.zip", "eam-ai-suite-python.zip herunterladen",
            ["ZIP entpacken", "<code>pip install ./eam-ai-suite-python</code>", "<code>eam-ai --version</code>"],
            groesse=groesse("eam-ai-suite-python.zip"),
            slug="python",
        ),
        f"""<article class="card wide">
  <span class="badge">Für Server</span>
  <h3>Container</h3>
  <p>Fertiges Image mit Webdienst, Upload und Job-Status; Python muss auf dem Host nicht installiert sein.</p>
  <div class="meta">ghcr.io/mitchel85/eam-toolfamilie:v{html.escape(version)}</div>
  <a class="btn" href="{html.escape(REPO_URL + "/pkgs/container/eam-toolfamilie")}">Zur Container-Seite</a>
  <pre><code>docker pull ghcr.io/mitchel85/eam-toolfamilie:v{html.escape(version)}
docker run --rm -p 8080:8080 \\
  ghcr.io/mitchel85/eam-toolfamilie:v{html.escape(version)}</code></pre>
  <ol><li>Docker starten</li><li>Befehl kopieren</li><li>http://localhost:8080 öffnen</li></ol>
</article>""",
    ]
    ziel = dist / STARTSEITE
    ziel.write_text(
        Template(_START_TEMPLATE).substitute(
            cards="\n".join(karten),
            version=html.escape(version),
            releases=f"{REPO_URL}/releases",
            repo=REPO_URL,
            sums=_dl("SHA256SUMS"),
        ),
        encoding="utf-8",
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
            ziel.write_text(KOPFZEILE[zielname] + quelle.read_text(encoding="utf-8"), encoding="utf-8")
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
    (dist / "README.md").write_text("\n".join(katalog), encoding="utf-8")

    # Manifest und Beleg führen ausschließlich die ausgelieferten Dateien.
    releases = ["# Release-Inhalt", "", "| Datei | Bytes | SHA-256 |", "|---|---|---|"]
    sums = []
    for name, datei in sorted(ausgeliefert):
        d = sha256(datei)
        releases.append(f"| `{name}` | {datei.stat().st_size} | `{d}` |")
        sums.append(f"{d}  {name}")
    (dist / "RELEASES.md").write_text("\n".join(releases) + "\n", encoding="utf-8")
    (dist / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")

    for f in fehlend:
        print(f"FEHLT: {f} — zuerst bauen")
    print(f"{len(vorhanden)} Auslieferungen, {len(sums)} Dateien in {dist}")
    return 0 if not fehlend else 1


if __name__ == "__main__":
    raise SystemExit(main())
