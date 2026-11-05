# EAM Tool-Familie

Werkzeuge für Architekturmodelle — Architektur **erstellen** und **analysieren** in den
Formaten `.qea`, `.xmi` und `.json`: niederschwellig, ohne Installation und auf Wunsch
KI-gestützt. Jede Anwendung ist eine eigenständige Datei, die im Browser läuft oder sich
als Paket für Kommandozeile und Server einsetzen lässt.

## Einstieg

**<https://mitchel85.github.io/EAM-Toolfamilie/>** — Übersichtsseite mit allen Werkzeugen,
je eine Karte mit Zweck, Download und Direktlink. Ein Klick lädt die Datei; sie öffnet
sich anschließend im Browser. Viele HTML-Werkzeuge laufen dort auch ohne Herunterladen
direkt im Browser.

## Der Ablauf — und welches Werkzeug ihn trägt

Eine Architektur entsteht in einem festen Prozess. Jeder Schritt hat sein Werkzeug; Daten
und Wissensbasis ziehen sich durch den ganzen Weg — sie werden nicht gepflegt, sondern
aus **einer** Quelle erzeugt: dem Regelwerk der Technologie (MDG-XML). Daraus gehen
Stereotypen, Beziehungsregeln, Sichten und Tags hervor; dazu kommen die
Standardelemente (StEKa), die mit unveränderten Kennungen übernommen werden, damit
Modelle zusammenfinden.

| Schritt | Was passiert | Werkzeug |
|---|---|---|
| **1 · Regelwerk** | MDG-XML laden; daraus werden erlaubte Typen, Regeln, Sichten und Tags | **ADMBw Extraktor** (HTML oder Python) |
| **2 · Standardelemente** | Startpaket (StEKa) übernehmen — die Kennungen bleiben unverändert | **EAM AI Suite** · `eam-ai toolbox` |
| **3 · Prosa einlesen** | Handbuch, Beschreibung, PDF oder Bild; mit KI entstehen daraus Elemente und Beziehungen — jede mit Herkunftsangabe | **EAM AI Suite** (HTML oder Python) |
| **4 · Bauen & prüfen** | Geprüft wird gegen die Regeln der MDG; gesperrte Typen (🔒) werden nie direkt verwendet | **EAM AI Suite** |
| **5 · Sehen** | Modell ansehen: Pakete, Sichten, Graph, Pfade | **EAM Suite** |
| **6 · Bearbeiten** | Korrigieren, verschmelzen, Standardelemente nachziehen, zurückschreiben | **EAM Suite** |
| **7 · Abfragen** | Fragen an ein vorhandenes Modell — als Werkzeug in Open WebUI oder per MCP | **EAM Analyzer** |
| **8 · Prozesse** | BPMN 2.0 lesen, zeichnen, prüfen, ADMBw-konform machen | **BPMN Studio** |

**Das Ergebnis** liegt als `.qea`, `.xmi` oder `.json` vor — alle drei Formate sind
gleichwertig und in der ganzen Familie lesbar. Damit lässt sich der Weg auch rückwärts
gehen: eine `.xmi` aus einem anderen Werkzeug wird gelesen, geprüft und weiterbearbeitet.

## Die Werkzeuge im Vergleich

Kurz, was jedes Werkzeug kann — und wie sie sich unterscheiden.

| Werkzeug | Formate | KI | Wofür es gut ist | Im Browser |
|---|---|---|---|---|
| **EAM AI Suite** (HTML) | `.qea` · `.xmi` · `.json` | ja (eigener Zugang) | Die ganze Kette in einer Datei: aus Text, Handbuch, PDF oder Bild ein geprüftes Modell bauen, ansehen, bearbeiten | [öffnen](https://mitchel85.github.io/EAM-Toolfamilie/eam-ai-suite/) |
| **EAM AI Suite** (Python `eam-ai`) | `.qea` · `.xmi` · `.json` | ja (Backend) | Dieselbe Kette ohne Browser — für Serienläufe, Webdienst und Server | — |
| **EAM Suite** (HTML) | `.qea` · `.xmi` · `.json` | nein | Vorhandene Modelle analysieren und verstehen, mehrere verschmelzen, von Hand bearbeiten und zurückschreiben | [öffnen](https://mitchel85.github.io/EAM-Toolfamilie/eam-suite/) |
| **EAM Analyzer** (HTML, Open WebUI, MCP) | `.qea` · `.xmi` | über das KI-Modell des Werkzeugs | Ein Modell befragen — als Werkzeug in Open WebUI oder als MCP-Server für Open WebUI, Claude Desktop und VS Code | — (wird nur ausgeliefert) |
| **ADMBw Extraktor** (HTML, Python) | MDG-XML | nein | Regelwerk durchsuchen und als sechs Regeldateien exportieren; die Grundlage für alles andere | [öffnen](https://mitchel85.github.io/EAM-Toolfamilie/admbw-extraktor/) |
| **BPMN Studio** (HTML, Python) | BPMN 2.0 | optional | Prozesse lesen, zeichnen und prüfen; auf Knopfdruck ADMBw-konform machen; Export als XML, SVG und PNG | [öffnen](https://mitchel85.github.io/EAM-Toolfamilie/bpmn-studio/) |

Der Unterschied in einem Satz: die **AI Suiten bauen** Modelle (mit KI), die **EAM Suite
analysiert und bearbeitet** sie (ohne KI), der **EAM Analyzer befragt** sie (als Werkzeug
in Open WebUI bzw. MCP), der **ADMBw Extraktor** liefert das Regelwerk und **BPMN Studio**
arbeitet an Prozessen.

**Abgrenzung.** Die HTML-Werkzeuge sind eigenständige Einzeldateien mit eigenem
Quellstand — es gibt keinen gemeinsamen UI-Kern, und ein Fix in einem Werkzeug ist kein
Fix im anderen. Gegen die aktuelle MDG prüfen nur die beiden AI Suiten; die EAM Suite
zeigt ein fest eingebautes Referenzraster. Der EAM Analyzer arbeitet auf der
Tabellenstruktur der `.qea` bzw. der Struktur der `.xmi` und bringt kein eigenes Schema
mit. Kein Ersatz für ein Modellierungswerkzeug ist das Ganze auch nicht: Substanz sind
Pakete, Elemente, Beziehungen und Tags — Diagramme sind Darstellung.

## Herunterladen

Alle Dateien liegen im öffentlichen Release. Jedes Werkzeug gibt es einzeln und als
komplettes Paket (Anwendung + Kurzanleitung).

| Werkzeug | Einzeldatei | Paket |
|---|---|---|
| EAM AI Suite | [EAM-AI-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.html) · [.aspx](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.aspx) | [EAM-AI-Suite.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.zip) |
| EAM AI Suite Python | [eam-ai-suite-python.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam-ai-suite-python.zip) | — |
| EAM Suite | [EAM-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.html) · [.aspx](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.aspx) · [en](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite-en.html) | [EAM-Suite.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.zip) |
| EAM Analyzer | [EAM-QEA-Analyzer.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-QEA-Analyzer.html) · [.aspx](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-QEA-Analyzer.aspx) | [EAM-Analyzer.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Analyzer.zip) |
| ADMBw Extraktor | [ADMBw-Extraktor.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/ADMBw-Extraktor.html) · [admbw-extraktor.py](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/admbw-extraktor.py) | [ADMBw-Extraktor.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/ADMBw-Extraktor.zip) |
| BPMN Studio | [BPMN-Studio.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/BPMN-Studio.html) | [BPMN-Studio.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/BPMN-Studio.zip) |

Für Open WebUI und MCP: [eam_qea_analyzer_openwebui.py](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam_qea_analyzer_openwebui.py) und
[eam-qea-mcp-server.py](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam-qea-mcp-server.py).
Übersicht und Prüfsummen: [START-HIER.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/START-HIER.html) ·
[RELEASES.md](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/RELEASES.md) ·
[SHA256SUMS](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/SHA256SUMS)

So geht's
1. Datei herunterladen.
2. Datei öffnen — sie öffnet sich im Browser.
3. Die eigene Modell- bzw. MDG-Datei hineinziehen.

`.aspx` ist dieselbe Anwendung für SharePoint/IIS (UTF-8 mit BOM). `.py`-Dateien sind für
Kommandozeile, Open WebUI oder MCP; sie werden nicht im Browser geöffnet.

## Schnell in den Werkzeugen

### EAM AI Suite Python

```bash
unzip eam-ai-suite-python.zip
pip install ./eam-ai-suite-python
eam-ai --help
```

- `eam-ai build --mdg technologie.xml --text beschreibung.pdf --out modell.qea` — bauen;
  braucht ein KI-Backend (`--backend openai` oder `ollama`, offline `--backend datei`).
  Das Ergebnis geht auch als `--out modell.xmi` oder `--out modell.json`; `--format {qea,xmi,json}`
  erzwingt das Format.
- `eam-ai build … --modell bestand.qea` — an ein vorhandenes Modell anknüpfen: sein Inhalt
  geht in den Prompt, das Ergebnis enthält Bestand und Neues.
- `eam-ai build --mdg technologie.xml --out geruest.qea` — Gerüst nur aus dem Regelwerk,
  ohne Text, ohne KI.
- `eam-ai toolbox` — Standardelemente aus einem Startpaket übernehmen, kennungserhaltend.
- `eam-ai merge` · `eam-ai edit` · `eam-ai korrigiere` — zusammenführen, gezielt ändern,
  in Worten korrigieren.
- `eam-ai frage` — Frage an ein vorhandenes Modell. `eam-ai serve` — Weboberfläche.
- Viewer (`viewer_html.py`) und Handbuch (`handbuch_generator.py`, `prosa_vergleich.py`)
  liegen als Module im Paket; eigene `eam-ai`-Befehle dafür gibt es noch nicht.

### ADMBw Extraktor (Python)

```bash
python admbw-extraktor.py technologie.xml -o rules.json --check
```

Dieselbe Datei liegt im Python-ZIP als `mdg_parser.py`; sie wird nicht doppelt gepflegt.

### EAM Analyzer (Open WebUI / MCP)

Open-WebUI-Tool: `eam_qea_analyzer_openwebui.py` unter **Werkzeuge** einfügen.
MCP-Server: beide Dateien in einen Ordner legen, dann

```bash
pip install "mcp>=1.28,<2" pandas networkx requests
python eam-qea-mcp-server.py --sse          # http://localhost:8000/sse
python eam-qea-mcp-server.py --http         # http://localhost:8000/mcp
```

Der MCP-Server importiert `eam_qea_tool.py`; die Open-WebUI-Datei muss deshalb im selben
Ordner liegen.

### Regeldateien in einem Chatbot nutzen

Der ADMBw Extraktor schreibt sechs Markdown-Dateien — reine Fachdaten, die sich in jedem
Chatbot als Wissensquelle ablegen lassen (ChatGPT, Claude, Gemini, Open WebUI, lokal).
Der Chatbot schlägt damit vor; prüfen tut er nicht.

1. Im ADMBw Extraktor die MDG-XML laden und „Alle 6" herunterladen: `admbw-knowledge-stereotypes.md`,
   `-topology.md`, `-viewpoints.md`, `-tagtypes.md`, `-stereotype-tags.md`, `admbw-meta.md`.
2. **Open WebUI:** *Workspace → Knowledge → „+“*, Dateien hochladen, Sammlung
   *ADMBw-Regelwerk* nennen; im Chat mit `#` anhängen oder beim Modell als Knowledge
   eintragen.
3. **Andere Chatbots:** ChatGPT Projekt/Custom GPT → Knowledge; Claude Projekt →
   Knowledge; Gemini Gem oder Notebook; lokal in den Kontext legen.
4. **Master-Prompt:** `ADMBw-Prompt.md` als System-Anweisung, die sechs Dateien als
   Knowledge — der Prompt sagt, wie gebaut wird; die Dateien sagen, was erlaubt ist.
5. **Grenzen:** Die Dateien sind Daten, keine Befehle. Bei Widerspruch gilt die MDG.

## Häufige Fragen

**Ist das für interne Modelle sicher?**
Die HTML-Werkzeuge laden nichts nach und senden nichts weg; sie arbeiten ohne Netz.
Einzige Ausnahme: die AI Suiten dürfen auf Wunsch eine KI anbinden — nur wenn ein Zugang
eingetragen ist, und nur der ausgewählte Text bzw. Modellausschnitt geht dorthin.

**Warum sehe ich auf GitHub nur Text, wenn ich auf die Datei klicke?**
Weil GitHub HTML als Quelltext anzeigt. Nimm die Download-Links oben oder die
Übersichtsseite <https://mitchel85.github.io/EAM-Toolfamilie/>.

**Welche Datei ist die richtige: `.html` oder `.aspx`?**
`.html` für den eigenen Rechner. `.aspx` nur, wenn die Datei auf einem SharePoint-/IIS-Server
liegt.

**Was ist eigentlich eine `.qea`?**
Die Modelldatenbank eines Enterprise-Architecture-Werkzeugs (SQLite-Format). Diese
Werkzeuge lesen und schreiben das Format, brauchen aber kein solches Programm und keine
Lizenz. Die Formate `.xmi` (offener Austauschstandard) und `.json` (für Auswertung und
Graphdatenbanken) sind gleichwertig.

**Darf ich die Dateien weitergeben?**
Ja, unverändert weitergeben ist erlaubt (MIT-Lizenz). Details in [LICENSE](LICENSE) und
[NOTICE.md](NOTICE.md).

## Für Entwickler

Aufbau
- `packages/rules/` — MDG-Leser und einzige Quelle für Regeln; welche MDG-Datei gilt,
  steht in `packages/rules/CURRENT`. Neue MDG-Stände prüft der tägliche Wächter
  (`rules-watch.yml`) und schlägt sie als PR vor.
- `packages/core/` — Python-Kern: lesen, prüfen, schreiben, zusammenführen, bearbeiten,
  Viewer, Handbuch.
- `apps/` — die HTML-Auslieferungen mit eigenem Quellstand und eigenem Build;
  `apps/cli`, `apps/mcp` — Kommandozeile, MCP und Open WebUI.
- `knowledge/` — Wissensbasis, **erzeugt** aus der MDG; nicht von Hand ändern.
- `vendor/` — Browser-Bibliotheken, kanonisch; wird beim Bauen in die Apps gespiegelt
  (`apps/*/vendor/` ist nicht versioniert).

Keine festen Zahlen
- Die MDG ändert sich laufend: Stereotypen, Regeln, Sichten und Tags kommen und gehen.
  Zahlen eines Stands stehen in `packages/rules/schemas/baseline-mdg-<release>.json` und
  `knowledge/admbw-meta.md` — nicht in Code, README oder Prüfskript.

Bauen und prüfen

```bash
python3 scripts/build_knowledge.py --check --check-provenance
python3 scripts/propagate.py --check
python3 scripts/build_all.py
python -m pytest -q
python3 scripts/verify_graph.py
```

- Builds sind deterministisch; `tests/test_html_artifacts.py` hält Größe, Titel,
  Funktionsmarker und die Trennung der Werkzeuge fest.
- Die große Musterarchitektur liegt als öffentliche Test-Fixture versioniert im Repository
  (`packages/core/fixtures/Musterarchitektur_MASC.qea`, Prüfsumme in
  `packages/core/ci/fixtures_manifest.json`). `EAM_FIXTURE_STORE` zeigt optional auf einen
  anderen Fixture-Ordner; die MCP-Tests akzeptieren zusätzlich `MASC_QEA_PATH`.
- Regelpfad ohne KI im Quellstand: in `packages/core/` `python3 eam_suite.py --no-llm run …`.
- Der Abhängigkeitsgraph (11 Zellen) wird von `scripts/verify_graph.py` geprüft und in der
  CI erzwungen; jede neue Datei braucht ihre Kante.

Weiterlesen
- [docs/HERKUNFT.md](docs/HERKUNFT.md) — Herkunft der Einzelwerkzeuge und gebaute Hashes
- [docs/STRUKTUR.md](docs/STRUKTUR.md) — Struktur und Auslieferungen
- [docs/ABHAENGIGKEITEN.md](docs/ABHAENGIGKEITEN.md) — Abhängigkeitskarte (erzeugt)
- [docs/MIGRATION.md](docs/MIGRATION.md) — Migration
- [docs/ABNAHME.md](docs/ABNAHME.md) — Abnahmelauf und Prüfungen

## Danksagung

Der EAM Analyzer baut auf den Erfahrungen und dem Code von **Markus Schmitz**
([@schmitze87](https://github.com/schmitze87)) auf — sein Projekt
[**AAroN (ArAMIS)**](https://github.com/schmitze87/AAroN) hat die QEA-Tabellenstruktur
von Sparx EA dokumentiert und als Open-Source-Prozessoren verfügbar gemacht. Ohne diese
Arbeit wäre der Analyzer nicht entstanden: danke dafür. Die QEA-Analyse in
`apps/mcp/eam_qea_tool.py` ist daraus abgeleitet; der Lizenztext (Apache-2.0) liegt im
Repository als [`apps/mcp/LICENSE-AAroN.txt`](apps/mcp/LICENSE-AAroN.txt). Details zu
Rechten Dritter stehen in [NOTICE.md](NOTICE.md).

Lizenz: [LICENSE](LICENSE) · Hinweise zu Drittkomponenten: [NOTICE.md](NOTICE.md)