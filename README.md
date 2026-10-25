# EAM Toolfamilie

Werkzeuge für Architekturmodelle: eine `.qea`-Datei lesen, prüfen, bearbeiten
und wieder herausschreiben — ohne Installation, ohne Konto, ohne Internet.
Alles läuft direkt im Browser.

**Du brauchst keine Programmierkenntnisse und keinen GitHub-Account.**
Drei Schritte: Datei herunterladen, Doppelklick, fertig.

> Unabhängiges Werkzeug. Keine Verbindung zu Sparx Systems Pty Ltd.
> Produktnamen Dritter dienen nur der Beschreibung von Dateiformaten.

---

## In 30 Sekunden starten

1. **Werkzeug aussuchen** — Tabelle unten oder die Übersichtsseite
   [`START-HIER.html`](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/START-HIER.html)
   (dort gibt es für jedes Werkzeug einen Knopf).
2. **Auf den Dateinamen klicken** — der Download startet sofort. Kein Login.
3. **Die Datei doppelklicken.** Sie öffnet sich im Browser. Jetzt die eigene
   `.qea` hineinziehen.

Es gibt nichts zu installieren, nichts zu registrieren, kein Abo, keine Cloud.
Die Modelldatei bleibt auf dem eigenen Rechner.

> **Windows:** Chrome oder Edge fragen beim ersten Mal „Dateien dieses Typs
> werden normalerweise nicht geöffnet“. Das ist normal — die Datei ist eine
> Web-Anwendung, kein Programm. Auf „Öffnen“ klicken.

---

## Welches Werkzeug wofür?

| Ich möchte … | Werkzeug | Download (ein Klick) |
|---|---|---|
| **aus Prosa, PDF oder Handbuch eine `.qea` bauen** und prüfen | **EAM AI Suite 9.1** | [EAM-AI-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.html) |
| **nur nachsehen**, was in einer `.qea` steckt | **EAM QEA Analyzer 4.0** | [EAM-QEA-Analyzer.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-QEA-Analyzer.html) |
| **Modelle bearbeiten oder zwei Modelle verschmelzen** | **EAM Suite 8.4** | [EAM-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.html) |
| **die MDG-Regeln nachschlagen** (Stereotype, Viewpoints, Tags) | **EAM MDG Parser** | [EAM-MDG-Parser.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-MDG-Parser.html) |
| **in Open WebUI** ein Modell `.qea`-fähig machen | **Open-WebUI-Tool** | [eam_qea_analyzer_openwebui.py](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam_qea_analyzer_openwebui.py) |
| **in der Konsole oder auf einem Server** arbeiten | **Python-Kern 2.4.0** | [eam-ai-suite-python.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam-ai-suite-python.zip) |

**Kurzfassung:**

- **AI Suite** ist das größte Werkzeug: Prosa rein, Modell raus, prüfen,
  ansehen, bearbeiten, Handbuch zurück.
- **QEA Analyzer** liest und prüft nur. Kein Bearbeiten, keine KI — ideal,
  um fremde Modelle gefahrlos anzusehen.
- **EAM Suite** lädt mehrere Modelle, führt sie zusammen und schreibt eine neue
  `.qea`. Ohne KI.
- **MDG Parser** braucht keine Modelldatei, nur die MDG-XML (Regelwerk).

---

## Was die HTML-Werkzeuge können

| | AI Suite 9.1 | QEA Analyzer 4.0 | EAM Suite 8.4 | MDG Parser |
|---|---|---|---|---|
| `.qea` lesen | ✅ | ✅ | ✅ | — |
| Prüfen / Validieren | ✅ | ✅ | ✅ | — |
| Ansehen, Suchen, Pfade | ✅ | ✅ | ✅ | ✅ |
| Bearbeiten, speichern | ✅ | — | ✅ | — |
| Mehrere Modelle verschmelzen | — | — | ✅ | — |
| Prosa / PDF / Bild → Modell | ✅ | — | — | — |
| MDG-Regeln durchsuchen | ✅ | — | — | ✅ |
| KI nötig | optional | nein | nein | nein |
| Installation | keine | keine | keine | keine |
| Größe | 3,4 MB | 299 KB | 1,3 MB | 31 KB |

Alle vier laufen offline. Die Modelldatei wird nie hochgeladen — der Browser
liest sie lokal.

---

## Was ist eine `.qea`?

Eine `.qea` ist eine Modell-Datenbank, wie sie Sparx Enterprise Architect
erzeugt (SQLite-Format). Die Werkzeuge lesen und schreiben dieses Format,
brauchen aber **kein** Enterprise Architect und keine Lizenz.

---

## Häufige Fragen

**Muss ich ein Konto anlegen?**
Nein. Weder bei GitHub noch sonst wo.

**Ist das sicher für interne Modelle?**
Ja. Die HTML-Dateien laden nichts nach, senden nichts weg und arbeiten ohne
Netz. Du kannst den Rechner vom Netz nehmen, es funktioniert weiter.
Ausnahme: Die AI Suite darf optional eine KI anbinden — abgeschaltet, solange
kein Schlüssel eingetragen ist.

**Warum sehe ich auf GitHub nur Text, wenn ich auf die Datei klicke?**
Weil GitHub HTML nur als Quelltext anzeigt. Nimm die Download-Links oben oder
die Seite
[`START-HIER.html`](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/START-HIER.html) —
dort gibt es für jedes Werkzeug einen Knopf.

**Welche Datei ist die richtige: `.html` oder `.aspx`?**
`.html` für den eigenen Rechner. `.aspx` nur, wenn die Datei auf einem
SharePoint-/IIS-Server liegt.

**Wie prüfe ich, dass der Download vollständig ist?**
Die Prüfsummen stehen in
[`SHA256SUMS`](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/SHA256SUMS).
Für den Alltag nicht nötig.

**Darf ich die Datei weitergeben?**
Ja, unverändert weitergeben ist erlaubt (MIT-Lizenz). Details in
[`LICENSE`](LICENSE) und [`NOTICE.md`](NOTICE.md).

---

## Alle Downloads und Prüfsummen

- **Alle Dateien auf einen Blick:**
  [Releases ansehen](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest)
- **Übersichtsseite mit Knöpfen:**
  [`START-HIER.html`](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/START-HIER.html)
- **Prüfsummen:**
  [`SHA256SUMS`](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/SHA256SUMS)

Aktuelle Fassung: **3.0.3** (Release-Tag `v3.0.3`).

---

## Für Terminal, Server und Automatisierung

<details>
<summary><b>Python-Paket installieren (aufklappen)</b></summary>

Voraussetzung: Python 3.11 oder neuer. Sonst nichts.

```bash
unzip eam-ai-suite-python.zip
pip install ./eam-ai-suite-python
eam-ai --version
eam-ai --help
```

Weboberfläche starten:

```bash
eam-ai serve --host 127.0.0.1 --port 8080
# -> http://127.0.0.1:8080/
```

</details>

<details>
<summary><b>Container (Docker)</b></summary>

```bash
docker pull ghcr.io/mitchel85/eam-toolfamilie:v3.0.3
docker run --rm -p 8080:8080 ghcr.io/mitchel85/eam-toolfamilie:v3.0.3
# -> http://127.0.0.1:8080/
```

`eam-ai` ist im Image direkt aufrufbar:

```bash
docker run --rm --entrypoint eam-ai ghcr.io/mitchel85/eam-toolfamilie:v3.0.3 --help
```

</details>

<details>
<summary><b>Open WebUI</b></summary>

1. In Open WebUI unter **Werkzeuge** eine neue Werkzeugdatei anlegen.
2. Inhalt von
   [`eam_qea_analyzer_openwebui.py`](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam_qea_analyzer_openwebui.py)
   einfügen oder die Datei hochladen.
3. Werkzeug für das Modell aktivieren.

Details: [`apps/mcp/openwebui_integration.md`](apps/mcp/openwebui_integration.md).

</details>

---

## Für Entwickler

<details>
<summary><b>Aufbau des Repositories</b></summary>

```
packages/
  rules/     MDG-Parser — die einzige Wahrheit für Stereotype und Regeln
  core/      Lesen, Schreiben und Prüfen von Modelldateien, CLI-Kern
apps/
  html-suite/         EAM AI Suite 9.1     (eigener Quellstand, eigener Build)
  html-analyzer/      EAM QEA Analyzer 4.0 (eigener Quellstand, eigener Build)
  html-editor/        EAM Suite 8.4        (eigener Quellstand, eigener Build)
  mdg-web/            EAM MDG Parser       (ältere Browser-Fassung, byte-gleich)
  cli/                Kommandozeile
  mcp/                Modelleinbindung (MCP, Open WebUI)
  admbw-batch/        Prosa → JSON-Batches
  admbw-extractor/    Prosa → Stereotype/Beziehungen
  admbw-script-maker/ Modellbehelf → EA-JScript
knowledge/            Wissensbasis, erzeugt — nicht von Hand ändern
vendor/               kanonische Browser-Bibliotheken (sql.js, PDF.js, JSZip)
scripts/              Bau, Prüfung, Einsammeln
tests/                ein Testlauf für alles
```

Jede HTML-App bringt ihren eigenen `src/`- und `vendor/`-Stand mit. `app.json`
nennt nur Produkt, Fassung, Quellstand und erwartete Ausgabedateien. Verbindlich
für den Auslieferungsgraphen ist `scripts/verify_graph.py`, nicht der native
GitHub-Graph (interne Paketnamen, kein npm-Lockfile).

</details>

<details>
<summary><b>Bauen und prüfen</b></summary>

```bash
python3 scripts/build_all.py          # HTML, Wheel, Offline-Bundle, SHA256SUMS
python3 scripts/collect_releases.py   # Auslieferungen + Quell-Archiv, Manifest
python3 scripts/verify_graph.py       # jede Zelle, jede Kante, jedes Artefakt
python3 -m pytest -q                  # ein Testlauf für alles
```

Jeder App-Build prüft seine JavaScript-Blöcke mit `node --check`, schreibt
`.html` und `.aspx` (UTF-8 mit BOM) und ist deterministisch: zweimal bauen
ergibt dieselben Bytes. `tests/test_html_artifacts.py` hält Größe, Titel,
Funktionsmarker und die Trennung der drei Werkzeuge fest.

</details>

<details>
<summary><b>Abhängigkeiten und Propagation</b></summary>

Die Karte steht in [`docs/ABHAENGIGKEITEN.md`](docs/ABHAENGIGKEITEN.md). Sie ist
erzeugt und wird von `scripts/dependency_report.py --check` gegen den
Arbeitsbaum geprüft.

```bash
python3 scripts/propagate.py --check   # Drift: Wissensbasis, Vendor, Manifeste, Karte
python3 scripts/propagate.py --write   # Quellen weiterreichen, ohne zu bauen
python3 scripts/propagate.py --all     # weiterreichen, bauen, einsammeln, Graph prüfen
python3 scripts/impact.py --git        # welche Zellen und Befehle sind betroffen?
```

Regel: **`vendor/` und die MDG-XML sind Quellen; alles andere ist daraus
abgeleitet.** `knowledge/` wird erzeugt, die Apps lesen es über Symlinks,
`vendor/` wird in die drei HTML-Apps gespiegelt, die Builds schreiben
`apps/*/dist`. `propagate --check` bricht in der CI ab, wenn eine Kopie oder
die Karte nicht zum Quellstand passt.

„Automatisch“ heißt hier an der Build- und CI-Grenze, nicht per Datei-Watcher.
Änderungen in einer App-Quelle wirken bewusst **nur** in dieser App — die drei
HTML-Stände bleiben eigenständig.

</details>

<details>
<summary><b>Wissensbasis</b></summary>

`knowledge/` ist erzeugt, nicht gepflegt. Einzige Quelle ist die MDG-XML in
`packages/rules/`.

```bash
python3 scripts/build_knowledge.py --mdg packages/rules/NAFv4-ADMBw-MDG-2026.05.xml
python3 scripts/build_knowledge.py --mdg packages/rules/NAFv4-ADMBw-MDG-2026.05.xml --check --check-provenance
```

`knowledge/PROVENANCE.json` hält MDG-Datei und Parserstand mit SHA-256 fest.
Die drei ADMBw-Apps lesen dieselben Dateien über Symlinks; es gibt keine
zweiten Kopien.

</details>

<details>
<summary><b>Herkunft und Dokumentation</b></summary>

Jede HTML-Datei wird aus ihrem eigenen Altstand gebaut; Zuordnung von Repo,
Commit, Anpassung und Ausgabe steht in [`docs/HERKUNFT.md`](docs/HERKUNFT.md).
Weiter: [`docs/STRUKTUR.md`](docs/STRUKTUR.md),
[`docs/MIGRATION.md`](docs/MIGRATION.md),
[`docs/ABNAHME.md`](docs/ABNAHME.md),
[`docs/ABHAENGIGKEITEN.md`](docs/ABHAENGIGKEITEN.md).

</details>

---

## Lizenz

MIT für eigene Anteile — siehe [`LICENSE`](LICENSE). Eingebundene
Bibliotheken Dritter und deren Lizenzen stehen in [`NOTICE.md`](NOTICE.md).
