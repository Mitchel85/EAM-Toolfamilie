# EAM Toolfamilie

Drei eigenständige HTML-Werkzeuge aus den archivierten Altständen, dazu der
Python-Kern, der MDG-Parser und die Prompt-Werkzeuge. Kein gemeinsamer
UI-Kern, keine drei Varianten derselben Oberfläche.

> Unabhängiges Werkzeug. Keine Verbindung zu Sparx Systems Pty Ltd.

## Download

| Werkzeug | Fassung | Was es macht | Datei |
|---|---|---|---|
| **EAM AI Suite** | 9.1 | Prosa/Handbuch rein, `.qea` raus; prüfen, ansehen, bearbeiten | [EAM-AI-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.html) |
| **EAM QEA Analyzer** | 4.0 | vorhandene `.qea` lesen und prüfen; ohne Bearbeiten, ohne KI | [EAM-QEA-Analyzer.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-QEA-Analyzer.html) |
| **EAM Suite** | 8.4 | Modelle verschmelzen, bearbeiten, zurückschreiben; ohne KI | [EAM-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.html) |
| **EAM MDG Parser** | alt | MDG-XML laden: 318 Stereotype, 203 Regeln, 52 Viewpoints, 27 Tag-Typen | [EAM-MDG-Parser.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-MDG-Parser.html) |
| **Open-WebUI-Tool** | — | `.qea` in Open WebUI abfragen | [eam_qea_analyzer_openwebui.py](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam_qea_analyzer_openwebui.py) |
| **Python/CLI** | 2.4.0 | `eam-ai`, Webdienst, MCP | [eam-ai-suite-python.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam-ai-suite-python.zip) |

Die HTML-Dateien laufen per Doppelklick, ohne Installation und ohne Netz.
Alle Dateien liegen als Release-Assets; kein GitHub-Konto nötig.
Prüfsummen: [SHA256SUMS](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/SHA256SUMS).

## Aufbau

```
packages/
  rules/     MDG-Parser — die einzige Wahrheit für Stereotype und Regeln
  core/      Lesen, Schreiben und Prüfen von Modelldateien, CLI-Kern
apps/
  html-suite/      EAM AI Suite 9.1   (eigener Quellstand, eigener Build)
  html-analyzer/   EAM QEA Analyzer 4.0 (eigener Quellstand, eigener Build)
  html-editor/     EAM Suite 8.4      (eigener Quellstand, eigener Build)
  mdg-web/         EAM MDG Parser     (alte Browser-Fassung, byte-gleich)
  cli/             Kommandozeile
  mcp/             Modelleinbindung (MCP, Open WebUI)
  admbw-batch/     Prosa → JSON-Batches
  admbw-extractor/ Prosa → Stereotype/Beziehungen
  admbw-script-maker/ Modellbehelf → EA-JScript
knowledge/         Wissensbasis, erzeugt — nicht von Hand ändern
vendor/            kanonische Browser-Bibliotheken (sql.js, PDF.js, JSZip)
scripts/           Bau, Prüfung, Einsammeln
tests/             ein Testlauf für alles
```

Jede HTML-App bringt ihren eigenen `src/`- und `vendor/`-Stand mit. `app.json`
nennt nur Produkt, Fassung, Quell-Repository, Quell-Commit und die erwarteten
Ausgabedateien — keine sichtbaren Reiter, keine Editionstexte. Die Manifeste
unter `package.json` sind Zellen des eigenen Auslieferungsgraphen; verbindlich
ist `scripts/verify_graph.py`, nicht der native GitHub-Graph (interne
Paketnamen, kein npm-Lockfile).

## Abhängigkeiten

Die Karte steht in [`docs/ABHAENGIGKEITEN.md`](docs/ABHAENGIGKEITEN.md). Sie ist
erzeugt und wird von `scripts/dependency_report.py --check` gegen den
Arbeitsbaum geprüft.

```bash
python3 scripts/propagate.py --check   # Drift: Wissensbasis, Vendor, Manifeste, Karte
python3 scripts/propagate.py --write   # Quellen weiterreichen, ohne zu bauen
python3 scripts/propagate.py --all     # weiterreichen, bauen, einsammeln, Graph prüfen
python3 scripts/impact.py --git        # welche Zellen und Befehle sind betroffen?
```

Die Regel: **`vendor/` und die MDG-XML sind Quellen; alles andere ist daraus
abgeleitet.** `knowledge/` wird erzeugt, die Apps lesen es über Symlinks,
`vendor/` wird in die drei HTML-Apps gespiegelt, und die Builds schreiben
`apps/*/dist`. `propagate --check` bricht in der CI ab, wenn eine Kopie oder
die Karte nicht zum Quellstand passt.

„Automatisch“ heißt hier an der Build- und CI-Grenze, nicht per Datei-Watcher:
Wer eine Quelle ändert, ruft `propagate.py --all` (oder `build_all.py`) auf;
die CI blockiert jeden Stand, bei dem eine abhängige Kopie fehlt. Eine Änderung
in einer App-Quelle wirkt bewusst **nur** in dieser App — die drei HTML-Stände
bleiben eigenständig.

## Bauen

```bash
python3 scripts/build_legacy_app.py apps/html-suite
python3 scripts/build_legacy_app.py apps/html-analyzer
python3 scripts/build_legacy_app.py apps/html-editor
python3 apps/mdg-web/build.py

python3 scripts/build_all.py          # HTML, Wheel, Offline-Bundle, SHA256SUMS
python3 scripts/collect_releases.py   # Auslieferungen + Quell-Archiv, Manifest
python3 scripts/verify_graph.py       # jede Zelle, jede Kante, jedes Artefakt
```

Jeder App-Build prüft seine JavaScript-Blöcke mit `node --check`, schreibt
`.html` und `.aspx` (UTF-8 mit BOM) und ist deterministisch: zweimal bauen
ergibt dieselben Bytes. Die Tests in `tests/test_html_artifacts.py` halten
Größe, Titel, Funktionsmarker und die Trennung der drei Werkzeuge fest.

## Wissensbasis

`knowledge/` ist erzeugt, nicht gepflegt. Einzige Quelle ist die MDG-XML in
`packages/rules/`. Wer hier etwas ändert, macht es beim nächsten Lauf wieder
rückgängig — und die CI wird rot.

```bash
python3 scripts/build_knowledge.py --mdg packages/rules/NAFv4-ADMBw-MDG-2026.05.xml
python3 scripts/build_knowledge.py --mdg packages/rules/NAFv4-ADMBw-MDG-2026.05.xml --check --check-provenance
```

`knowledge/PROVENANCE.json` hält MDG-Datei und Parserstand mit SHA-256 fest.
Die drei ADMBw-Apps lesen dieselben Dateien über Symlinks; es gibt keine
zweiten Kopien.

## Tests

```bash
python3 -m pytest -q
python apps/admbw-batch/checks/verify.py
python apps/admbw-extractor/checks/verify.py
node apps/admbw-script-maker/tests/run_tests.js
python3 scripts/verify_graph.py
python3 scripts/sync_dependency_files.py --check
```

## Stand

| Phase | Inhalt | Status |
|---|---|---|
| 0 | Sicherung, Altstände, Messung | erledigt |
| 1 | EAM AI Suite aus `architektur-mate-ki` | erledigt |
| 2 | EAM QEA Analyzer aus `admbw-qea-analyzer` | erledigt |
| 3 | EAM Suite aus `admbw-qea-editor` | erledigt |
| 4 | Graph, CI, Release | erledigt |

Details: `docs/HERKUNFT.md`, `docs/STRUKTUR.md`, `docs/MIGRATION.md`, `docs/ABNAHME.md`,
`docs/ABHAENGIGKEITEN.md`.
