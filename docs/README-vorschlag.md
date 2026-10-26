# EAM Toolfamilie

Werkzeuge für Architekturmodelle im Format `.qea`: aus Regelwerk und Beschreibung ein
geprüftes Modell bauen, vorhandene Modelle ansehen, zusammenführen und bearbeiten.
Die HTML-Werkzeuge laufen per Doppelklick im Browser — ohne Installation, ohne Konto.

> Unabhängiges Werkzeug, ohne Verbindung zum Hersteller der Modellierungssoftware.
> Produktnamen Dritter beschreiben nur Dateiformate.

## Was die Toolfamilie tut

- **Hinein:** das Regelwerk der Technologie (MDG-XML), bei Bedarf ein Startpaket mit
  Standardelementen, ein vorhandenes Modell und Text — Handbuch, Beschreibung, PDF oder Bild.
- **Heraus:** eine `.qea`-Datei mit Paketen, Elementen, Beziehungen und Tags, geprüft gegen
  das Regelwerk, gedacht für Werkzeuge, die `.qea` auswerten.
- **Wofür:** eine Architekturbeschreibung in ein prüfbares Modell übersetzen, statt sie von
  Hand nachzubauen; vorhandene Modelle verstehen, zusammenlegen und nachbessern.
- **Was sie nicht ist:** kein Ersatz für ein Modellierungswerkzeug, keine Layout-Engine.
  Substanz sind Pakete, Elemente, Beziehungen und Tags; Diagramme sind Darstellung.
- **Daten:** ohne KI arbeiten die HTML-Werkzeuge lokal im Browser. Mit KI gehen der Text
  bzw. der gewählte Modellausschnitt an den KI-Zugang, den man selbst einträgt.

## Der Ablauf in sieben Schritten

1. **MDG rein** — die Technologie-XML laden. Daraus entsteht das Regelwerk: Stereotype
   (auch die abstrakten 🔒), Topologie-Regeln, Viewpoints, Tag-Typen. Wie viele es sind,
   bestimmt der MDG-Stand; die Regeldatei wird laufend fortgeschrieben.
2. **ggf. Startpaket rein** — Standardelemente kommen als zweite `.qea`. Ihre `ea_guid`
   bleibt wörtlich erhalten, damit Modelle mit demselben Standard zusammenfinden.
3. **Prosa rein** — Handbuch, Text, PDF oder Bild. Daraus werden Elemente und Beziehungen,
   jede mit Angabe ihrer Herkunft.
4. **Architektur bauen** — gegen die Regeln der MDG prüfen. Abstrakte Stereotype (🔒)
   werden nie instanziiert; eine Regel mit abstraktem Endpunkt gilt für alle konkreten
   Subtypen.
5. **Architektur sehen** — Viewer: Pakete, Sichten, Graph, Pfade zwischen Elementen.
6. **Architektur bearbeiten** — korrigieren (von Hand oder in Worten), Standardelemente
   nachziehen, als neue `.qea` speichern. Das Original bleibt unberührt.
7. **Fertig** — die `.qea` liegt vor.

**Der Rückweg ist ein Test, kein Workflowschritt.** `.qea` → Doku (Handbuch) → Vergleich
mit der Eingabe zeigt beiläufig, ob das Modell die Eingabe noch trägt. Er gehört nicht in
den Ablauf. Messwerte und Grenzen: [docs/ABNAHME.md](docs/ABNAHME.md).

- Die MDG kommt zuerst. Ohne Regelwerk wird nichts gebaut.
- Das Startpaket übernehmen beide AI Suiten technisch als Zusammenführung in ein Modell
  (HTML: Bereich „Standardelemente“, Python: `eam-ai toolbox`). Es lässt sich deshalb auch
  nach dem Bauen nachziehen.

## Welches Werkzeug wofür

- **EAM AI Suite** (eine HTML-Datei, Fassung 9.1) — die ganze Kette im Browser: MDG laden,
  Standardelemente übernehmen, Prosa mit KI in ein Modell übersetzen, prüfen, ansehen,
  bearbeiten, Handbuch für den Rückweg-Test erzeugen.
- **EAM AI Suite Python** (Kommandozeile `eam-ai` und Webdienst) — dieselbe Kette ohne
  Browser, für Serienläufe, Server und Läufe ohne KI.
- **EAM Suite** (eine HTML-Datei, Fassung 8.4) — vorhandene Modelle öffnen, mehrere
  verschmelzen, von Hand bearbeiten und als neue `.qea` speichern; ohne MDG-Prüfung, ohne
  KI, ohne Prosa.
- **EAM QEA Analyzer** (eine HTML-Datei, Fassung 4.0) — vorhandene `.qea` nur lesen und
  verstehen: Explorer, Sichten, Graph, Pfade, Export als Bild oder Tabelle; schreibt nichts.
- **EAM MDG Parser** (eine HTML-Datei) — MDG-XML im Browser durchsuchen und als
  Regeldateien exportieren; baut kein Modell.

Schnellwahl
- Neues Modell aus Text → EAM AI Suite (für Serien und Server: EAM AI Suite Python)
- Modell nur ansehen → EAM QEA Analyzer
- Modelle zusammenlegen oder von Hand ändern → EAM Suite
- Regelwerk nachschlagen → EAM MDG Parser

Abgrenzung
- Nur die beiden AI Suiten können den ganzen Ablauf. HTML und Python sind zwei getrennte
  Umsetzungen derselben Kette.
- EAM Suite, EAM QEA Analyzer und EAM MDG Parser sind eigenständige Einzelwerkzeuge mit
  eigenem Quellstand. Es gibt keinen gemeinsamen UI-Kern.
- Änderungen wandern nicht automatisch mit: ein Fix in der EAM Suite ist kein Fix in der
  EAM AI Suite — und umgekehrt.
- EAM Suite und EAM QEA Analyzer zeigen ein fest eingebautes ADMBw-Referenzraster. Es folgt
  einer neuen MDG nicht; gegen die aktuelle MDG prüfen nur die beiden AI Suiten.
- Die KI-Schritte der EAM AI Suite brauchen einen KI-Zugang (Endpunkt, Schlüssel). Laden,
  Sehen und Bearbeiten gehen ohne.
- Fragen an ein Modell, nur lesend, beantworten die EAM AI Suite, `eam-ai frage` und das
  Open-WebUI-Werkzeug.
- Weitere Werkzeuge der Familie: EAM-AI-QEA-Analyzer (das Open-WebUI-Werkzeug) und die
  Prompt-Werkzeuge EAM-AI-ADMBw-Extractor, -Batch und -Script-Maker. Sie arbeiten mit der
  Wissensbasis aus der MDG; Quellen unter `apps/`.

## Herunterladen

Alle Dateien liegen im öffentlichen Release — kein Konto, kein Login.

- Einstieg mit Übersicht aller Werkzeuge:
  [START-HIER.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/START-HIER.html)
- EAM AI Suite:
  [EAM-AI-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.html)
  · für SharePoint:
  [EAM-AI-Suite.aspx](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-AI-Suite.aspx)
- EAM AI Suite Python:
  [eam-ai-suite-python.zip](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam-ai-suite-python.zip)
- EAM Suite:
  [EAM-Suite.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.html)
  · für SharePoint:
  [EAM-Suite.aspx](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-Suite.aspx)
- EAM QEA Analyzer:
  [EAM-QEA-Analyzer.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-QEA-Analyzer.html)
  · für SharePoint:
  [EAM-QEA-Analyzer.aspx](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-QEA-Analyzer.aspx)
- EAM MDG Parser:
  [EAM-MDG-Parser.html](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/EAM-MDG-Parser.html)
- Open-WebUI-Werkzeug (fragt eine `.qea` ab, statt zu raten):
  [eam_qea_analyzer_openwebui.py](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/eam_qea_analyzer_openwebui.py)
- Prüfsummen:
  [SHA256SUMS](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/SHA256SUMS)
  · Inhalt des Release:
  [RELEASES.md](https://github.com/Mitchel85/EAM-Toolfamilie/releases/latest/download/RELEASES.md)

So geht's
1. Datei herunterladen.
2. Doppelklick — sie öffnet sich im Browser.
3. Die eigene `.qea` bzw. die MDG-XML hineinziehen.

- Die `.aspx`-Dateien sind dieselben Anwendungen für SharePoint/IIS (UTF-8 mit BOM).
- Prüfsummen kontrollieren, im Download-Ordner: `sha256sum -c --ignore-missing SHA256SUMS`

### EAM AI Suite Python

```bash
unzip eam-ai-suite-python.zip
pip install ./eam-ai-suite-python
eam-ai --help
```

- `eam-ai build --mdg technologie.xml --text beschreibung.pdf --out modell.qea` — Schritte 1,
  3 und 4; braucht ein KI-Backend (`--backend openai` oder `ollama`, offline `--backend datei`).
- `eam-ai build --mdg technologie.xml --out geruest.qea` — Gerüst nur aus dem Regelwerk,
  ohne Text, ohne KI.
- `eam-ai toolbox` — Standardelemente aus einem Startpaket übernehmen, GUID-erhaltend.
- `eam-ai merge` · `eam-ai edit` · `eam-ai korrigiere` — zusammenführen, gezielt ändern,
  in Worten korrigieren.
- `eam-ai frage` — Frage an eine vorhandene `.qea`.
- `eam-ai serve` — Weboberfläche.
- Viewer (`viewer_html.py`) und Handbuch für den Rückweg-Test (`handbuch_generator.py`,
  `prosa_vergleich.py`) liegen als Module im Paket; eigene `eam-ai`-Befehle dafür gibt es
  noch nicht.

## Für Entwickler

Aufbau
- `packages/rules/` — MDG-Leser. Welche MDG-Datei gilt, steht in einer einzigen Zeile:
  `packages/rules/CURRENT`.
- `packages/core/` — Python-Kern: lesen, prüfen, schreiben, zusammenführen, bearbeiten,
  Viewer, Handbuch.
- `apps/html-suite`, `apps/html-editor`, `apps/html-analyzer`, `apps/mdg-web` — die
  HTML-Auslieferungen, je mit eigenem Quellstand und eigenem Build; der MDG Parser wird
  byte-gleich übernommen.
- `apps/cli`, `apps/mcp`, `apps/admbw-*` — Kommandozeile, MCP und Open WebUI,
  Prompt-Werkzeuge.
- `knowledge/` — Wissensbasis, **erzeugt** aus der MDG; nicht von Hand ändern.
- `vendor/` — Browser-Bibliotheken, kanonisch; wird beim Bauen in die Apps gespiegelt
  (`apps/*/vendor/` ist nicht versioniert).

Keine festen Zahlen
- Die MDG ändert sich laufend: Stereotype, Regeln, Viewpoints und Tag-Typen kommen und
  gehen. Der Parser extrahiert immer vollständig; die Anzahl ist variabel.
- Die Zahlen eines MDG-Stands stehen in der Baseline
  `packages/rules/schemas/baseline-mdg-<release>.json` und in `knowledge/admbw-meta.md` —
  nicht in Code, README oder Prüfskript.
- Neuer MDG-Stand: XML ablegen → `packages/rules/CURRENT` anpassen → Wissensbasis neu
  erzeugen → nach fachlicher Prüfung eine neue Baseline schreiben.

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
- Die große Musterarchitektur liegt bewusst nicht im Repository (Prüfsumme in
  `packages/core/ci/fixtures_manifest.json`). Ohne sie werden die Prüfläufe, die sie
  brauchen, sichtbar übersprungen. Lokal: Datei nach `packages/core/fixtures/` legen oder
  `EAM_FIXTURE_STORE` setzen; die MCP-Tests brauchen zusätzlich `MASC_QEA_PATH`.
- Regelpfad ohne KI im Quellstand: in `packages/core/` `python3 eam_suite.py --no-llm run …`.

Weiterlesen
- [docs/HERKUNFT.md](docs/HERKUNFT.md) — Herkunft der Einzelwerkzeuge und gebaute Hashes
- [docs/STRUKTUR.md](docs/STRUKTUR.md) — Struktur und Auslieferungen
- [docs/ABHAENGIGKEITEN.md](docs/ABHAENGIGKEITEN.md) — Abhängigkeitskarte (erzeugt)
- [docs/MIGRATION.md](docs/MIGRATION.md) — Migration
- [docs/ABNAHME.md](docs/ABNAHME.md) — Abnahmelauf und Rückweg-Test

Lizenz: [LICENSE](LICENSE) · Hinweise zu Drittkomponenten: [NOTICE.md](NOTICE.md)
