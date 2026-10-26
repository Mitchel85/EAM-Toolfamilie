# Review: EAM-Toolfamilie gegen die Abdeckungsgrafik

- Prüfer: Opus 5.5 (Subagent), 25.10.2026
- Gegenstand: Grafik „Ein Workflow, fünf Werkzeuge“ — Matrix 5 Werkzeuge × 7 Schritte plus Abstammungszeile (Renderer `render_workflow_abdeckung.py`, Zellwerte dort in `WERKZEUGE`)
- Lokaler Stand: `c1cc411`, Arbeitsbaum sauber. Öffentlicher Stand: `Mitchel85/EAM-Toolfamilie`, `main` = `52b48fe`, Release `v3.0.3`
- Urteile: **belegt** · **teilweise** · **falsch** · *nicht geprüft*. Zeilenangaben beziehen sich auf den lokalen Stand.

## Kurzurteil

- Die Kernaussage trägt: nur die beiden AI Suiten decken die Kette ab; EAM Suite, QEA Analyzer und MDG Parser je einen Ausschnitt. Matrix: 31 von 35 Zellen belegt, 3 teilweise, 1 falsch.
- Schwachstelle der Matrix ist Spalte 7. „Fertig — Rückweg = Test“ stellt den Test als Spalte in den Ablauf — genau das, was ausgeschlossen sein soll — und wertet dadurch die EAM Suite falsch.
- Die Abstammungszeile ist der schwächste Teil: der Pfeil „Regelwerk“ hat keinen Codepfad, „− Bearbeiten“ zeigt in die falsche Richtung, „+ KI, + Prüfung“ hat die falsche Quelle.
- Ergebnisse: Tests grün (789 passed, 4 skipped), Artefakte prüfsummengleich, Abnahmezahlen in den Rohdaten wiedergefunden. Es bröselt an den Rändern: Abnahme nicht aus dem Repo nachrechenbar, 4 MCP-Tests laufen nie, Versionsetiketten widersprüchlich.
- Größtes Repo-Risiko ist kein Code: lokaler und öffentlicher Stand sind auseinandergelaufen; beide Seiten haben Fixes, die der anderen fehlen. „Die lokale README ist die Quelle“ stimmt derzeit nicht.

## 1 Stimmt die Grafik?

### 1.1 Matrix im Überblick

Symbol = Aussage der Grafik, Wort = Urteil.

| Werkzeug | 1 MDG | 2 Startpaket | 3 Prosa | 4 Bauen/Prüfen | 5 Sehen | 6 Bearbeiten | 7 Fertig/Rückweg |
|---|---|---|---|---|---|---|---|
| EAM AI Suite | ● belegt | ● belegt | ● belegt | ● belegt | ● belegt | ● belegt | ○ teilweise |
| EAM AI Suite Python | ● belegt | ● belegt | ● belegt | ● belegt | ● teilweise | ● belegt | ○ belegt |
| EAM Suite | — belegt | — teilweise | — belegt | ◐ belegt | ● belegt | ● belegt | — falsch |
| EAM QEA Analyzer | — belegt | — belegt | — belegt | — belegt | ● belegt | — belegt | — belegt |
| EAM MDG Parser | ● belegt | — belegt | — belegt | — belegt | — belegt | — belegt | — belegt |

### 1.2 Belege je Zeile

**EAM AI Suite (HTML 9.1)** — Quellen unter `apps/html-suite/src/`
- 1 MDG ● — belegt. `part6_ki.js:71` (`loadMdg`), `:79` (XML-Parser), `:98` (`isAbstract`), `:104` (Metaconstraints), `:636` (`requireMdg`); UI `part1_head_body.html:772`.
  - Korrektur zur Vorgabe „part0/part6“: `part0` lädt keine MDG. Es ist der QEA-Leser (`part0_reader_data.js:7`, `qeaOpen`) plus ein fester Referenzauszug (`:478`, `ADMBW_DATA`).
- 2 Startpaket ● — belegt. `part8_stdimport.js:7-9` (ea_guid bleibt wörtlich), `:960`/`:1011` (übernehmen, schreiben); UI `part1_head_body.html:931`.
  - Lage: im Bereich Bearbeiten (ab `:887`), also nach dem Bauen — nicht vor der Prosa.
- 3 Prosa ● — belegt, mit KI. `part6_ki.js:2-4` (Text, docx/pdf, Bilder → .qea); UI `:784` (KI-Anbindung), `:796` (Architektur beschreiben). Prosa ohne KI: *nicht geprüft*.
- 4 Bauen/Prüfen ● — belegt. `part6_ki.js:206` (`validateModel`), `:244` (`mdgCoverage`), `:992`/`:1093` (.qea schreiben).
  - Korrektur zur Vorgabe „part7 = Prüfen“: `part7_qa.js:2` lautet „Teil 7: RÜCKWEG (Frage & Antwort über die .qea)“. part7 liest und beantwortet Fragen; geprüft wird in part6.
- 5 Sehen ● — belegt. `part3_app_graph.js:42` (`renderGrid`), `:96` (`openVP`); `part4_path.js:35` (`findShortestPath`), `:70` (`findAltPaths`).
- 6 Bearbeiten ● — belegt. `part5_edit.js:954`/`:990` (als .qea speichern); `part10_nledit.js:39`, `:65`, `:81` (Ändern in Worten); UI `:887`, `:891`.
- 7 Rückweg ○ — teilweise. `part9_handbuch.js` erzeugt das Handbuch (UI `:948`) und misst die Abdeckung Modell → Text (`:2727` Namensquote, `:2833` Kantenabdeckung).
  - Einen Vergleich mit der ursprünglichen Prosa wie in `prosa_vergleich.py` habe ich im HTML-Code nicht gefunden (Suche Quote|Vergleich|Abdeckung|Treue: 4 Treffer, 3 gesichtet).
  - „Fertig“ selbst (.qea liegt vor) kann die Suite; die Zelle zeigt das nicht.

**EAM AI Suite Python** — Quellen unter `packages/core/`
- 1 MDG ● — belegt. `eam-ai build --help`: `--mdg` ist Pflicht; Beispiel `eam_ai.py:6`.
- 2 Startpaket ● — belegt, als Folgeschritt. `eam_ai.py:907`, `:914`, `:931` (`toolbox`, `--startpaket`), `toolbox_merge.py`.
  - `build` hat keine Startpaket-Option; in der Abnahme kommt das Startpaket nach dem Bauen (`docs/ABNAHME.md:14`).
- 3 Prosa ● — belegt. `build --text` (.txt/.md/.docx/.pdf), `--bild`; `extract.py`, `image_input.py`, `pdf_text.py`; Backends openai/ollama/datei.
- 4 Bauen/Prüfen ● — belegt. `eam-ai --help` („MDG laden, Quelle extrahieren …, prüfen, .qea schreiben“); `validator.py`, `repair_loop.py` (`--repair`), `qea_writer.py`.
- 5 Sehen ● — teilweise. `viewer_html.py:1`, `:10`: eigenständiges Skript, genutzt von `webui.py`. Kein `eam-ai`-Unterbefehl (vorhanden: build, frage, serve, merge, edit, korrigiere, toolbox). Tiefe gegenüber dem HTML-Viewer (Sichten, Pfade): *nicht geprüft*.
- 6 Bearbeiten ● — belegt, nicht interaktiv. `edit` (ops.json, `eam_ai.py:40`), `korrigiere --apply`, `merge`; `model_edit.py`, `nl_edit.py`, `model_merge.py`.
- 7 Rückweg ○ — belegt als Test. `handbuch_generator.py`, `prosa_vergleich.py`, `roundtrip_export.py`, `roundtrip_metrics.py` (alle im ZIP); `tests/core/test_roundtrip.py`; Abnahme `docs/ABNAHME.md:12-13`. Kein CLI-Unterbefehl.

**EAM Suite (Basis 8.4)** — Quellen unter `apps/html-editor/src/`
- 1 MDG — — belegt für „MDG rein“: kein Laden, keine Prüfung (`dist/EAM-Suite.html`: `requireMdg` 0, `validateModel` 0; „MDG“ nur im Paketfilter `part0_reader_data.js:250-252`).
  - „Kein MDG-Regelwerk“ wäre zu stark: fest eingebauter Auszug `ADMBW_DATA` (`part0_reader_data.js:478`; Schlüssel grid/vp/topo, vp mit 52, topo mit 37 Einträgen), sichtbar als Referenz-Grid (`part1_head_body.html:588`, `:624`). Er folgt keiner neuen MDG.
- 2 Startpaket — — teilweise (zu stark). Kein Import von Standardelementen (kein part8; nur Paketfilter `part0_reader_data.js:248`).
  - Manuell geht es: Startpaket-.qea als Ausgangsmodell öffnen und ergänzen (`part5_edit.js:515` `elNew`, `:956` speichern) oder per GUID dazuverschmelzen (`part1_head_body.html:517`, `part2_app_core.js:1381`). Keine Harmonisierung wie `toolbox`.
- 3 Prosa — — belegt. KI/LLM/Prosa: 0 Treffer im Quellstand; `vendor/` nur sql.js; der Test verbietet `window.KI` und `tab-ki` (`tests/test_html_artifacts.py:50`).
- 4 Bauen ◐ — belegt. Anlegen `part5_edit.js:515` (`elNew`), `:556` (`connNew`), `:858` (INSERT t_object); Verschmelzen `part2_app_core.js:1381` (`applyMergePreview`); keine Regelprüfung (`validateModel` 0, `part5_edit.js` nutzt `ADMBW_DATA` nicht).
- 5 Sehen ● — belegt. `part3_app_graph.js:889` (`openGlobalGraph`), `:945` (`initGraph`); `part4_path.js:35`, `:70`; Reiter `part1_head_body.html:584-588`.
- 6 Bearbeiten ● — belegt. `part5_edit.js:281` (`elEdit`), `:325`, `:355`, `:385`, `:478` (Tags), `:956`/`:992` (als .qea speichern).
- 7 Fertig — — falsch, wenn die Spalte „Fertig“ meint: die Suite schreibt eine .qea (`part5_edit.js:992`). Richtig nur als „kein Rückweg-Test“ (Handbuch: 0 Treffer).

**EAM QEA Analyzer (4.0)** — Quellen unter `apps/html-analyzer/src/`
- 1–4 — — belegt. Kein MDG-Laden, keine Prüfung, kein Schreiben (`dist/EAM-QEA-Analyzer.html`: INSERT, UPDATE, `.export()`, `MERGE_CANDS` je 0). Gleicher fester Referenzauszug wie die EAM Suite (Daten identisch; Grid `part1_head_body.html:461`, `:505`).
- 5 Sehen ● — belegt. Graph `part3_app_graph.js:778`, `:834`; Pfade `part4_path.js:35`, `:73`, `:168`; Export `part2_app_core.js:313` (XLSX), `:518` (PNG), `:632` (PDF).
- 6–7 — — belegt. Edit-Teile entfernt: `build_release.py:140-143`, `:167-178` (Edit-Knopf und -Container raus), `:181-186` (nur part1–4), `:189`; Test `tests/test_html_artifacts.py:40` (verbotene Edit- und KI-Marker).
- Die Doku übertreibt, die Grafik nicht: `README.md:14`, `dist/README.md:33` und START-HIER („Nur prüfen“, „Prüfen → QEA Analyzer“) sagen „prüfen“. Der Analyzer prüft nichts gegen Regeln; Titel laut `tests/test_html_artifacts.py:35`: „analysieren, erkunden & exportieren“.

**EAM MDG Parser (Vorstufe)** — `apps/mdg-web/`
- 1 MDG ● — belegt, mit Abstrich. `index.html`: XML-Parser, Exportnamen `admbw-knowledge-*.md` (5), `admbw-meta.md`, `admbw-stereotypes.json`. Kein Prompt-, Alias- oder Connector-Export — die gibt es nur in `knowledge/` aus `packages/rules/mdg_parser.py`.
- 2–7 — — belegt. Kein Modellschreiben: sql.js, `.qea`, `t_object` je 0 Treffer in `index.html`.
- Byte-gleich: belegt. `build.py:21-26` (kopiert Bytes), `app.json:6`; `dist/EAM-MDG-Parser.html` = `index.html` = Pages-Kopie im archivierten Parser-Repo (Byte-Vergleich).

### 1.3 Spalten

- 1 MDG — belegt. Lücke: der feste Referenzauszug in EAM Suite und Analyzer bleibt unsichtbar.
- 2 Startpaket — teilweise. Beide AI Suiten können es, aber als Übernahme in ein vorhandenes Modell (HTML `part1_head_body.html:931` nach `:887`; Python `toolbox` nach `build`). Die Position „vor der Prosa“ bildet kein Werkzeug ab.
- 3 Prosa — belegt.
- 4 „Bauen — prüfen“ — teilweise. Die Spalte vermischt Bauen und Prüfen; der ◐ der EAM Suite heißt „bauen ohne prüfen“. Vorschlag: „Bauen + MDG-Prüfung“.
- 5 Sehen — teilweise (Python-Zeile).
- 6 Bearbeiten — belegt.
- 7 „Fertig — Rückweg = Test“ — falsch konstruiert.
  - Schritt 7 und Test teilen sich eine Spalte. Das widerspricht der Festlegung „Rückweg ist kein Workflowschritt“ und erzeugt die falsche EAM-Suite-Zelle.
  - Vorschlag: Spalte 7 = „fertig (.qea liegt vor)“: ● AI Suite, ● Python, ● EAM Suite, — Analyzer, — Parser. Der Rückweg-Test als Kennzeichen außerhalb der sieben Spalten (HTML: Handbuch + Abdeckung; Python: Handbuch + Vergleich).

### 1.4 Abstammungszeile

- „EAM MDG Parser · Vorstufe · Regelwerk“ — teilweise. Eigenständige Vorstufe: belegt (s. o.).
  - Pfeil „Regelwerk“ → EAM Suite: **falsch**. Die EAM Suite liest weder MDG noch Parser-Exporte. Die AI Suiten parsen die MDG selbst (`part6_ki.js:71`; Python `build --mdg` über `packages/rules/mdg_parser.py`). Der Browser-Parser speist zur Laufzeit niemanden.
- „EAM Suite · Basis · 8.4“ — teilweise.
  - Basis der AI Suite: belegt. Gleiche Dateien part0–5, part6–10 neu (z. B. `part2_app_core.js` 113.606 B vs. 109.893 B); Versionsfolge 8.4 → 9.x; das AI-Suite-Altrepo beginnt am 17.10. mit „v9.0 KI-Edition“.
  - Basis des Analyzers: nein (nächster Punkt).
- „− Bearbeiten → EAM QEA Analyzer · Auskopplung · 4.0“ — teilweise, Richtung falsch.
  - Belegt ist der Mechanismus: `apps/html-analyzer/app.json:6` („aus dem Edit-Master durch Entfernen der Edit-Teile“) und `src/build_release.py:140-189`.
  - Der Edit-Master ist aber die eigene v5.0-Edit-Edition des Analyzers (`build_release.py:3`), nicht `apps/html-editor`. Alle gemeinsamen Dateien weichen ab (z. B. `part2_app_core.js` 113.606 B vs. 71.632 B).
  - Geschichte laut Alt-Repos: Analyzer v4.0 (15.10., `0c93a8f`) → Analyzer v5.0 Edit-Edition (16.10., `2cbfece`) → Editor-Repo beginnt als „ADMBw QEA Editor v5.0 — Edit-Edition als eigenständiges Repository“ (16.10., `234da29`) → v6.1 Verschmelzen (`478c1c5`). Die EAM Suite stammt vom Analyzer ab, nicht umgekehrt.
- „+ KI, + Prüfung → EAM AI Suite“ — teilweise.
  - Die Zusätze sind belegt (`part6_ki.js`). Die Quelle ist falsch: die AI Suite trägt Bearbeiten und Verschmelzen (`tests/test_html_artifacts.py:29`: `var EDIT =`, `var MERGE`), die dem Analyzer fehlen — sie kommt aus der EAM-Suite-Linie.
  - Unvollständig: + Standardelemente (part8), + Handbuch (part9), + Ändern in Worten (part10), + Fragen ans Modell (part7).
- „Vollkette · HTML + Python“ in einer Box — teilweise. Beide Vollketten: belegt. Abstammung der Python-Suite aus dieser Linie: falsch — eigene Umsetzung (`packages/core`, `webui.py`: „eine Seite, kein Framework“). Die Fußzeile sagt das selbst.
- Belegte Linie (Vorschlag): Analyzer 4.0 → (+ Bearbeiten) Analyzer 5.0 Edit → (+ Verschmelzen …) EAM Suite 8.4 → (+ MDG, KI, Prüfung, Standardelemente, Handbuch) EAM AI Suite 9.1. Ausgeliefert wird der Analyzer als Master minus Edit-Teile. MDG Parser und Python-Suite: eigene Linien.

### 1.5 Fußzeilen

- „Die drei Basisstände sind eigenständig: ein Fix in der Basis wandert nicht automatisch in die Suite.“ — belegt in der Sache (eigenes `src/` je App, alle gemeinsamen Dateien byte-verschieden; `README.md:103-105`). Der Begriff ist unglücklich, weil „Basis“ in derselben Grafik die Rolle der EAM Suite ist. Besser: „Die drei HTML-Stände sind eigenständig …“.
- „HTML und Python sind zwei Umsetzungen derselben Kette — gemeinsamer UI-Kern: nein.“ — belegt.

### 1.6 Zu stark / fehlt

Zu stark
- Spalte 7 als Ablaufspalte für den Test.
- EAM Suite „Fertig —“: sie schreibt .qea.
- EAM Suite „Startpaket —“: manuell möglich.
- Python „Sehen ●“: Viewer nur als Modul bzw. im Webdienst.
- AI Suite HTML „Rückweg ○“ ohne Hinweis, dass der Vergleich gegen die Eingabe fehlt.
- Pfeil „Regelwerk“ MDG Parser → EAM Suite: kein Codepfad.
- Pfeil „− Bearbeiten“ EAM Suite → Analyzer: umgekehrte Richtung.
- Pfeil „+ KI, + Prüfung“ Analyzer → AI Suite: falsche Quelle.
- Box „Vollkette · HTML + Python“ als Ende einer Abstammung.
- Implizit Startpaket an Position 2 bei beiden AI Suiten; tatsächlich Folgeschritt.

Fehlt
- Der feste ADMBw-Referenzauszug in EAM Suite und Analyzer (in der AI Suite zusätzlich neben der geladenen MDG).
- Verschmelzen als eigene Fähigkeit (EAM Suite, beide AI Suiten).
- Fragen ans Modell, nur lesend (HTML part7, `eam-ai frage`).
- KI-Zugang als Voraussetzung für Prosa in der HTML-Suite.
- Die vollständigen Zusätze der AI Suite (+ Standardelemente, + Handbuch, + Ändern in Worten, + Fragen).
- Der echte Abnehmer der „Vorstufe“: die Wissensbasis `knowledge/` für die KI-Werkzeuge. Sie entsteht aus `packages/rules/mdg_parser.py`, nicht aus dem Browser-Parser.

## 2 Passen die Ergebnisse?

### Tests
- `python -m pytest -q -rs`, einmal gelaufen (`-rs` nur für die Skip-Gründe), Python 3.14.7: **789 passed, 4 skipped, 79,6 s, Exit 0**. Deckt sich mit der Vorgabe.
- Alle 4 Skips: `apps/mcp/tests/test_eam_qea_tool.py:138`, `:147`, `:156`, `:165` — „MASC_QEA_PATH not set“.
  - Die Musterarchitektur liegt lokal vor. Der Wurzel-`conftest.py:37` setzt nur `EAM_FIXTURE_STORE`; die MCP-Tests lesen `MASC_QEA_PATH` (`test_eam_qea_tool.py:29`).
  - Folge: diese 4 laufen im Standardlauf nie, auch nicht mit Fixture. `README.md:150-152` nennt nur Fixture-Ordner und `EAM_FIXTURE_STORE`.

### Artefakte
- `dist/SHA256SUMS`: 11 Einträge, alle stimmen. `apps/*/dist` und `dist/` byte-gleich (7 Dateien). Größen festgeschrieben (`tests/test_html_artifacts.py:26`, `:36`, `:46`), Determinismus-Test `:81`.
- Öffentliches Release `v3.0.3` (14 Assets): alle Links aus `README.md` erreichbar (HTTP 206), ebenso die `.aspx`, `RELEASES.md` und `START-HIER.html`.
  - Gleich zu lokal: AI Suite, Analyzer, MDG Parser, Open-WebUI-Tool.
  - Verschieden: `EAM-Suite.html/.aspx`, `START-HIER.html`, Python-ZIP (lokal `2.4.0`, öffentlich `3.0.3`).

### Messwerte (`docs/ABNAHME.md`)
- In den Rohdaten wiedergefunden: Faktenabdeckung 98,4 % = 63/64 (`13-vergleich.json` ↔ `ABNAHME.md:26`, `:225`); Bezeichnungen 100 % (43/43 ↔ `:28`); erster Lauf 74,6 % = 50/67 (`10-vergleich.json` ↔ `:58`).
- Abweichung: `ABNAHME.md:57` nennt „79 von 79 Bezeichnungen“, `10-vergleich.json` zählt 66/66. Quote gleich, Basis verschieden — ungeklärt.
- Die Rohdaten liegen außerhalb des Repos (lokaler Ausgabeordner mit Nutzerkennung, `ABNAHME.md:19-20`). Kein Test und keine CI rechnet die Kopfzahlen nach; aus einem Klon nicht nachrechenbar.
- Die Datei ist ehrlich zu ihren Grenzen (`:120-132`, `:247-256`): die Treue hängt an vollständigen Notizen (ohne sie 20,3 %), die Struktur ist dünn (4 von 11 Beziehungen gültig; vierter Lauf 6/6). Die Kette trägt Texttreue sicher, Struktur erst mit dem Kantennachtrag.
- Versionen passen nicht zusammen: `ABNAHME.md:36-38` nennt die Releases `v3.0.1`/`v2.4.3`; der lokale Build trägt „Release 2.4.0“ (START-HIER, ZIP); `pyproject.toml` lokal und öffentlich `2.4.0`; öffentliches Release `v3.0.3`.

### Doku gegen Code
- `README.md:51` „`--no-llm` ist Pflichtpfad“: die Option gibt es nur in `packages/core/eam_suite.py:12-30`. Installiert wird allein `eam-ai` (`pyproject.toml:32-33`), dort fehlt sie. Ohne-KI-Weg dort: `build` ohne `--text`, `--backend datei`.
- „Rückweg“ heißt im Code dreierlei: Fragen ans Modell (`part1_head_body.html:695`, `:845`; `part7_qa.js:2`), Handbuch (part9), Markdown → .qea (`prosa_import.py`, Docstring Zeile 1). Nur das zweite passt zur Definition in der Doku.
- UI-Reihenfolge der HTML-Suite ≠ Workflow: „1 · Grundgerüst (EABase)“ (`part1_head_body.html:760`) vor „2 · Regeln (MDG)“ (`:772`); Standardelemente erst im Bearbeiten-Bereich (`:931`).
- Feste Katalogzahlen:
  - START-HIER, Karte MDG Parser (Quelle `scripts/collect_releases.py:358`).
  - Alle drei HTML-UIs: Überschrift „ADMBw-Referenz-Grid — 52 Standard-Viewpoints“ (`apps/html-editor/src/part1_head_body.html:624`, `apps/html-analyzer/src/part1_head_body.html:505`, `apps/html-suite/src/part1_head_body.html:741`) plus Zählervorgabe `52`.
- `docs/HERKUNFT.md:19` nennt für `EAM-Suite.html` einen alten Hash (`a06bd8fc…`; gebaut ist `b58ff26e…`), obwohl `:22-24` Reproduzierbarkeit zusichert.

### Wo es bröselt
1. Die Abnahme hängt an Dateien außerhalb des Repos.
2. 4 MCP-Tests sind strukturell abgeschaltet.
3. Python: Viewer und Rückweg nur als Module, ohne `eam-ai`-Befehl; `--no-llm` fehlt im installierten Befehl.
4. Der HTML-Rückweg vergleicht nicht gegen die Eingabe.
5. Versionen: Paket 2.4.0, Tags 3.0.x, Etiketten gemischt.

## 3 Ist das Repo optimal? (nach Wirkung, nur festgestellt)

Hoch
1. **Zwei Quellen statt einer.**
   - Öffentlich `8b99803` „Bugfixes: Merge-Spiegel, MDG-Build, Container-CLI, Lizenzen“ (23 Dateien) fehlt lokal: `packages/core/model_merge.py` und `tests/core/test_model_merge.py` abweichend, der Regressionstest dazu lokal nicht vorhanden; `apps/mcp/LICENSE-AAroN.txt` und `vendor/LICENSE-pdfjs.txt` fehlen lokal.
   - Umgekehrt fehlt öffentlich die lokale Härtung `c1cc411`: `packages/rules/CURRENT` gibt dort 404; die öffentliche EAM Suite trägt noch einen fest verdrahteten Testdateinamen (keine Adresse).
   - Öffentliche README (`52b48fe`, 293 Zeilen) ≠ lokale (174 Zeilen, 365 Diff-Zeilen).
   - Wirkung: ein Snapshot aus lokal verliert Merge-Fix, Lizenzdateien und die Einsteiger-README; wer öffentlich weiterbaut, verliert die Härtung.
2. **Interne Support-Adresse in der lokalen MDG-XML.** `packages/rules/NAFv4-ADMBw-MDG-2026.05.xml`, Attribut `supportURI` (ab Byte 487): Dienst-Mailadresse mit Bereichskennung, versioniert.
   - Öffentlich durch einen Platzhalter ersetzt (deshalb abweichender `mdg_sha256` in `knowledge/PROVENANCE.json`). `c1cc411` („interne Adresse raus“) hat sie nicht erfasst.
   - Sonst inhaltsgleich (gleiche Zeilenzahl, gleiche Zahl an Stereotype-Tags und 🔒; Differenz 8 Byte).
3. **Lokale Pfade mit Nutzerkennung in der Doku:** `docs/ABNAHME.md` (3×), `docs/RAUCHTEST-OPENWEBUI.md:68`, `docs/MIGRATION.md`, `docs/ROADMAP.md`. Öffentlich bereinigt — beim nächsten Snapshot aus lokal wieder drin.

Mittel
4. **Release-Generator veraltet** (`scripts/collect_releases.py`):
   - Container-Link `pkgs/container/eam-platform` → 404 (`dist/START-HIER.html:128`, aus `:385`).
   - Image-Name `eam-platform` (`:384`, `:510` → `dist/README.md:79`) ist anonym nicht abrufbar.
   - `docker pull … eam-toolfamilie:v2.4.0` nennt einen Tag, den es nicht gibt (vorhanden: v3.0.2, v3.0.3, latest).
   - „Der Download aus dem privaten Repo braucht GitHub-Zugang“ (`:473` → `dist/README.md:5`) widerspricht `README.md:21` und START-HIER („öffentlich, kein Konto“). Das Repo ist öffentlich.
5. **Versionen uneinheitlich** (s. Abschnitt 2).
6. **Fester Referenzauszug und „52“ in drei UIs:** altert still mit jeder MDG. In der AI Suite entstehen zwei Wahrheiten: die geladene MDG prüft, das Grid zeigt den Altstand.
7. **4 MCP-Tests laufen nie** (s. Abschnitt 2).
8. **HTML-Suite fragt die MDG nicht zuerst** (`part1_head_body.html:760` vor `:772`).

Niedrig
9. `README.md:78-80` „privates Free-Repo“ veraltet; `README.md:47` Tippfehler „Quotennechnung“; `README.md:7` nennt den Herstellernamen.
10. `docs/HERKUNFT.md:19`: Hash veraltet.
11. `dist/GRAPH.md` ist älter als der Rest und steht nicht in `SHA256SUMS`; `dist/__pycache__` entsteht durch Tests in `dist/` (beides ignoriert, `.gitignore:4`).
12. `dist/EAM-MDG-Parser.html:84` enthält einen Download-Hinweis auf eine Behördenseite; wegen der Byte-Gleichheit nur in der Doku abzufangen.
13. Altname `eam-platform` noch in `docs/STRUKTUR.md:98`, `docs/MIGRATION.md:44`, `:51`, `Dockerfile:4-5`; `docs/ROADMAP.md:96` empfiehlt noch ein privates Repo „EAM-Platform“.

Tote Verweise
- `README.md`: keiner. 7 Release-Links (HTTP 206), 1 Doku-Link und 4 Doku-Nennungen als Text — alle Ziele vorhanden, lokal wie öffentlich.
- `dist/START-HIER.html`: 1 toter Link (`:128`), dazu ein Befehl mit nicht vorhandenem Tag. Sprunganker: *nicht geprüft*.
- `dist/README.md`: Container-Befehl nicht abrufbar (`:79`).
- Lücke: `README.md` verlinkt weder START-HIER.html noch RELEASES.md noch die `.aspx`.

Struktur
- Der Aufbau ist klar: `packages/rules`, `packages/core`, `apps/*`, `knowledge/` erzeugt, `vendor/` kanonisch.
- `dist/README.md` und `START-HIER.html` entstehen in `scripts/collect_releases.py`; `dist/` ist ignoriert. Korrekturen gehören in den Generator, nicht in `dist/`.

## 4 Zum README-Vorschlag (`docs/README-vorschlag.md`)

- Neu geschrieben: Workflow und Entwicklerteil aus der lokalen README, Einstieg ohne Vorkenntnisse nach dem Muster der öffentlichen Fassung (dort nur der Kopf gesichtet).
- Downloads ausschließlich `…/releases/latest/download/<datei>` mit den erlaubten Namen. Alle 12 Ziele im Release `v3.0.3` erreichbar (HTTP 206).
- Bewusst weggelassen: Container (Image-Name uneinheitlich), Katalogzahlen, Herstellername, interne Adressen, Versionsnummer des Python-Pakets.
- Enthält die ehrlichen Grenzen aus diesem Befund: drei eigenständige Einzelwerkzeuge ohne gemeinsamen UI-Kern, Fixes wandern nicht mit, festes Referenzraster, KI-Zugang für Prosa in HTML, Startpaket technisch als Übernahme.
- Vor dem Veröffentlichen erst Punkt 3.1 klären: der Vorschlag nennt `packages/rules/CURRENT`, das öffentlich noch fehlt.

## Nicht geprüft

- Bedienung im Browser (keine Klickpfade, keine Screenshots); KI-Pfade mit echtem Endpunkt; Prosa ohne KI in der HTML-Suite.
- Ob die EAM Suite ein verschmolzenes Mehrfachmodell als eine .qea speichert.
- Funktionstiefe des Python-Viewers (Sichten, Pfade).
- Inhalt der öffentlichen Bugfixes (nur auf Dateiebene verglichen); Inhalt des Container-Images; `.aspx` unter SharePoint/IIS.
- Zahl der Downloads im MDG Parser (Doku: sechs; im Code sieben Dateinamen).
- Herkunft und Bedeutung von `ADMBW_DATA.topo`.
- Sprunganker in START-HIER; vierter Suchtreffer in `part9_handbuch.js`.

## Prüfprotokoll

- `python -m pytest -q -rs`, genau einmal (79,6 s).
- Code: Suche und Zeilenbereiche über `apps/*/src`, `packages/core`, `apps/mdg-web`; Markerzählung in `dist/*.html`. Keine HTML/JS-Datei vollständig gelesen.
- Artefakte: SHA-256 gegen `dist/SHA256SUMS`, Byte-Vergleich `apps/*/dist` ↔ `dist/`.
- Öffentlich: GitHub-API (Release, Commits, `docs/`), Raw-Dateien, HTTP-Status aller Links (Range-Abruf), Abfrage der Container-Tags.
- Alt-Repos: erste Commits und README-Zeilen der lokalen Archivklone.
- Geschrieben: nur `docs/REVIEW-opus-5.5.md` und `docs/README-vorschlag.md`; kein Commit, kein Push.
