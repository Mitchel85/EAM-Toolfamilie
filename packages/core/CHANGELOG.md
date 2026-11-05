# Changelog

Alle Aenderungen am Lieferumfang. Die Version steht an genau drei Stellen und
wird von `tests/test_packaging.py` gegeneinander geprueft:
`eam_ai.__version__`, `pyproject.toml` und diese Datei.

## 3.4.2 - 2026-11-05

### Auftrag bei der Prosa-Extraktion

Neben dem Text laesst sich ein Auftrag mitgeben, etwa "Anbei das Handbuch,
extrahiere den Prozess Rechnungslauf". Genannt der Auftrag einen Prozess,
schneidet das Werkzeug genau diesen Abschnitt aus dem Dokument; ohne Treffer
wird der ganze Text ausgewertet, und der Hinweis sagt das offen.

- HTML-Studio: Feld "Auftrag (optional)" ueber dem Prozesstext
- Kommandozeile: `--anweisung`
- KI-Adapter: der Auftrag geht als Vorgabe in die Anfrage
- Test: Abschnittswahl in Python, Marker im Studio

## 3.4.1 - 2026-11-05

### BPMN Studio: Kommandozeile

`python -m bpmn.cli` mit vier Befehlen: `pruefen`, `konform`, `export`
(XML/SVG/PNG) und `extrahieren`. Damit ist die Python-Fassung nicht nur eine
Bibliothek, sondern ein benutzbares Werkzeug. Test deckt alle vier Befehle ab.

## 3.4.0 - 2026-11-05

### Neues Werkzeug: BPMN Studio

Prozesse als BPMN 2.0 lesen, anzeigen, bearbeiten, pruefen und ausgeben.
Zwei Fassungen aus einer Quelle: `packages/bpmn/` (Python) und
`apps/bpmn-studio/` (Einzeldatei, offline).

- BPMN 2.0 mit Diagrammgeometrie; XSD-validiert, Roundtrip byte-stabil
- Pruefung nach den L4-MK-Konventionen des Leitfadens (20 Regeln), Befunde
  mit Regel-ID und Objektname
- Knopf "ADMBw-konform machen": Transformation mit Protokoll, idempotent
- Export XML, SVG, PNG; SVG und PNG deterministisch
- Prosa-Extraktion regelbasiert; KI-Adapter optional und standardmaessig aus
- `.qea`-Bruecke ueber den vorhandenen Writer
- bpmn.js 18.31.1 (MIT) gebuendelt, keine Laufzeit-Netzabhaengigkeit

Kompatibilitaet zu bpmn.io selbst geprueft (Import, 10/10 Assoziationen,
0 Seitenfehler); ARIS und Enterprise Architect nur aus Dokumenten belegt --
siehe `docs/BPMN-KOMPATIBILITAET.md`.

## 3.3.6 - 2026-11-04

### Altnamen wirklich im Release

3.3.4 hat die Altnamen gebaut, aber der Release-Ablauf laedt nur eine feste
Dateiliste hoch -- `EAM-MDG-Parser.html` und `eam-mdg-parser.py` fehlten
deshalb im Release und die alten Links liefen ins Leere. Die Liste ist
ergaenzt; beide Namen werden jetzt mitgeliefert.

## 3.3.5 - 2026-11-04

### Anleitung: Regeldateien im Chatbot

Der ADMBw Extraktor, die Startseite und die README erklaeren jetzt an derselben
Stelle, wie die sechs Markdown-Regeldateien in einem Chatbot genutzt werden --
mit Schritt fuer Schritt fuer Open WebUI (Knowledge-Sammlung, `#` im Chat,
Zuordnung am Modell) und fuer ChatGPT, Claude, Gemini und lokale Modelle.

Klarstellung: Der Chatbot schlaegt vor, er prueft nicht; bei Widerspruch gilt
die MDG.

## 3.3.4 - 2026-11-04

### Altnamen bleiben bedienbar

`ADMBw-Extraktor.html` und `admbw-extraktor.py` werden zusaetzlich unter den
frueheren Namen `EAM-MDG-Parser.html` und `eam-mdg-parser.py` ausgeliefert.
Inhalt und Pruefsumme sind identisch; alte Links und Lesezeichen laufen
weiter. Die neuen Namen bleiben die empfohlenen.

## 3.3.3 - 2026-11-04

### ADMBw Extraktor

Der MDG-Parser heisst nach aussen ADMBw Extraktor. Umbenannt sind die
Auslieferungen (ADMBw-Extraktor.html, admbw-extraktor.py), die Titel in der
Browser-Fassung und die Hinweise in README und Release-Seite.

Die Engine bleibt `mdg_parser.py` und technologieneutral: sie liest jede
MDG-/UML-Profil-XML. Die Marke steht nur in der Auslieferung.

## 3.3.2 - 2026-11-04

### EAM Suite

Die Referenzdaten (ADMBW-Grid, Viewpoint-Namen, Elementlisten, Topologie)
werden beim Bauen aus `knowledge/regelwerk.json` erzeugt, nicht mehr von Hand
gepflegt. Damit stimmen die angezeigten Elemente mit der MDG ueberein; die
bisherige Liste war eine abgeschriebene NAF-Fassung und wich bei allen 52
Sichten ab. Der Bau bricht ab, wenn die eingebettete Fassung vom Regelwerk
abweicht.

Version 8.6.

## 3.3.1 - 2026-11-04

### EAM Suite

Die Sicht-Renderer- und BPMN-Ansicht aus 3.3.0 ist zurueckgenommen: Die
EAM Suite zeichnet Sichten nicht mehr selbst. Erhalten bleiben Bearbeiten,
Zusammenlegen, Notizen und der Issue-Tracker (Stereotyp «Issue», JSON- und
.qea-Export).

Diese Fassung ist die gueltige Auslieferung; 3.3.0 enthaelt noch die
BPMN-Ansicht.

## 3.3.0 - 2026-11-04

### Wissensbasis

Ein Artefakt statt drei getrennter Quellen: `knowledge/regelwerk.json` fuehrt
je Viewpoint zusammen, was die MDG erlaubt, was die Leitfaeden verlangen und
wie der Model Wizard die Sicht mustert. 54 Viewpoints, jede Aussage mit
Herkunft, Widersprueche gemeldet statt stillschweigend aufgeloest.

### Leitfaeden

Der bisher fehlende Leitfaden "Projektarchitekturen (PBN) - Anteil Service und
System" (V2.1) ist ausgewertet: 226 Modellierungskonventionen. Die
FFfmLV-Konventionen wurden neu aus dem PDF gewonnen (303 Eintraege); dabei
sind Reste der Verweisspalte aus dem Text verschwunden.

### MDG-Leser

`UIToolboxes` werden gelesen: 53 Werkzeugkaesten mit Stereotyp und
Metaklasse. Damit ist belegt, welche Elemente eine Sicht vorsieht.

### Model Wizard

Assoziationen der 52 Vorlagen werden aufgeloest statt nur gezaehlt -- beide
Enden ueber die xmi.id, auch fuer ActionState, Transition und ClassifierRole.

### EAM Suite

Die Fassung mit BPMN-Darstellung ersetzt die vorherige Auslieferung.

## 3.2.7 - 2026-10-27

### EAM Suite

Die Schaltfläche „MASC laden" und die zugehörige Ladefunktion entfallen. Die
Musterarchitektur wird bei Bedarf über „Eine Architektur laden" geöffnet.

## 3.2.6 - 2026-10-27

### Release-Asset

`EAM-Suite-en.html` wird jetzt auch als Release-Asset veröffentlicht. In 3.2.5
lag die Datei zwar auf GitHub Pages und in der Prüfsummenliste, fehlte aber in
der Asset-Liste des Releases.

## 3.2.5 - 2026-10-27

### Englische Fassung der EAM Suite

Die EAM Suite gibt es zusätzlich als `EAM-Suite-en.html` mit englischer
Oberfläche. Die Datei steht im Release neben der SharePoint-Fassung; die
Quellen und das Übersetzungswörterbuch liegen unter `apps/html-editor/`.

## 3.2.4 - 2026-10-27

### Beschreibung

Die EAM AI Suite wird als Bauen, Prüfen, Ansehen, Bearbeiten und Speichern
beschrieben. Das Handbuch ist kein Produktmerkmal; der Rückweg `.qea` →
Handbuch → Vergleich steht als Test in der README, nicht im Workflow.

## 3.2.3 - 2026-10-27

### Startseite

Der einleitende Absatz und die drei Schritte (Werkzeug wählen, Datei
herunterladen, im Browser öffnen) entfallen. Unter „Welches Werkzeug wofür"
stehen direkt die Karten.

## 3.2.2 - 2026-10-27

### Auslieferung

3.2.1 zeigte als Tag auf den Stand vor zwei Nachbesserungen: die Startseite
sagt wieder „Fünf Werkzeuge", und der MCP-Server findet das Open-WebUI-Tool
auch unter dem Auslieferungsnamen `eam_qea_analyzer_openwebui.py`. 3.2.2 baut
alle Assets reproduzierbar aus genau diesem Stand; die Dateien sind sonst
unverändert.

## 3.2.1 - 2026-10-27

### Lieferumfang

Der EAM QEA Analyzer ist keine eigene HTML-Auslieferung mehr; Analyse, Sichten
und Viewer stecken in der EAM Suite. Dafür werden zwei eigene Python-Wege
ausgeliefert: das Open-WebUI-Tool und der MCP-Server (beide brauchen einander).
Der EAM MDG Parser liegt als HTML und als Python-Skript bei; das Python-Skript
ist dieselbe Datei wie `mdg_parser.py` im Python-ZIP.

## 3.2.0 - 2026-10-26

### Kennungen woertlich erhalten (Gross-/Kleinschreibung)
`catalog_index`, `qea_writer` und die HTML-Suite behandelten `ea_guid` bisher
als Grossbuchstaben. Eine Kennung mit Kleinbuchstaben aus Katalog oder
Startpaket kam zwar als dieselbe UUID heraus, aber nicht Zeichen fuer Zeichen
identisch. Jetzt wird nur ohne Gross-/Kleinschreibung verglichen; geschrieben
bleibt die vorhandene Schreibweise. In der HTML-Suite werden vorhandene Zeilen
des Grundgeruests ausserdem direkt wiederverwendet statt neu angelegt.

### Vermerke an wiederverwendeten Bestandselementen
Traf ein extrahiertes Element auf eine vorhandene Zeile im Startpaket ohne
eigenen Vermerk (`Note`), ging der aus dem Quelltext gewonnene Absatz beim
Zusammenfuehren verloren (`model_merge` und HTML-Suite). Leere Vermerke am
Bestandselement werden jetzt aus der Quelle gefuellt, vorhandene Vermerke
bleiben unangetastet.

### Chargen nach Quelltextlaenge und Bestand im Prompt
`extract_batched` misst die Chargenschwelle jetzt am Quelltext statt am Prompt
und waehlt je Abschnitt zuerst die im Abschnitt genannten Bestandselemente.
Endpunkte einer Beziehung, die im Bestand stehen und im zitierten Absatz
woertlich vorkommen, werden mit diesem Absatz als Beleg uebernommen.

### Einheitliche Zaehlung und bereinigte Auslieferungen
Python-Parser, HTML-Suite und MDG-Web-Parser nutzen dieselben 19
Beziehungs-Metaklassen (138 Beziehungs-Stereotype in NAFv4-ADMBw 2026.05).
Hersteller- und Systemkuerzel in den ausgelieferten HTML-Werkzeugen sind durch
neutrale Fachbegriffe ersetzt.

### Lange Beschreibungen im Browser
Die HTML-Suite schickte die ganze Quelle in einem Aufruf und schnitt bei
12.000 Ausgabetokens ab -- ein Handbuch passt dort nie hinein. Jetzt teilt sie
an Kapitelgrenzen, ueberspringt reine Verzeichnisse (Namenslisten ohne Satz),
fuehrt die Teile ueber Name und Stereotyp zusammen und halbiert einen Abschnitt
erneut, wenn die Antwort trotzdem zu lang ist.

### Kanten folgen ihren Elementen
Uebernimmt der Katalog ein Element in sein Heimatpaket, zeigten dessen Kanten
weiter auf das alte Paket; der Export brach mit "zeigt auf kein deklariertes
Element" ab. Die Referenzen werden jetzt mitgezogen. Zusaetzlich haengt eine
Kante am Paket ihres Elements, nicht am Zielpaket des Laufs.

### Zusammenfuehren ohne Kennungsgleichheit
`merge_models` loeste Endpunkte nur ueber die `ea_guid`. Zwei Laeufe, die
dasselbe Element unabhaengig anlegen, verloren die Kante still. Jetzt greift
ein Rueckgriff ueber Paketpfad, Name und Stereotyp.

### Keine Modellbesonderheiten im Anwendungscode
Ein fest eingetragenes Baugruppenverzeichnis, ein Beispielszenario in
Platzhalter und Slider, ein Beispielname in Vorlage und Rezept sowie ein
Pruefskript mit eingehaerteten Modellnamen sind entfernt. Das Handbuch
erklaert Baugruppen jetzt aus Name und Vermerk. `scripts/check_no_model_leak.py`
prueft den Anwendungscode gegen die Namen eines beliebigen Modells.

### Handbuch vertraegt beliebige Modelle
Ein Modell darf "Architektur" heissen und gesperrte Begriffe in Notizen
tragen: der erzählende Teil ersetzt sie, das Verzeichnis nennt weiter die
echten Namen. Zahlen ohne Beleg, Wiederholungen und unerzaehlte Kanten sind
Befunde im Bericht statt Abbruchgruende.

## 3.1.1 - 2026-10-26

### Dokumentation

- Bauanleitung nennt `--katalog`: Standardelemente werden beim Bauen aus Prosa
  uebernommen (Kennung und Heimatpaket aus dem Katalog), neue Elemente bleiben
  abgeleitet.

## 3.1.0 - 2026-10-26

### Neu

- **Standardelemente aus dem Katalog.** `eam-ai build --katalog katalog.qea`
  liest den Standard-Elementekatalog (z. B. `Modellelementekatalog` der MASC,
  1.162 Elemente) und uebernimmt fuer genannte Elemente Kennung, Stereotyp und
  Heimatpaket. Neue Elemente behalten ihre abgeleitete Kennung. Die HTML-Fassung
  laedt denselben Katalog ueber die Schaltflaeche „Katalog laden" und wendet ihn
  vor der Pruefung an.
- **Kennungen ueberleben den Weg durch das IR.** Der Leser gibt gefuehrte
  Kennungen (`ea_guid`) woertlich zurueck, der Schreiber verwendet sie
  unveraendert. Der Weg `.qea -> IR -> .qea` ist damit byte-gleich; auch
  Umziehen oder Umbenennen aendert die Identitaet eines Katalogelements nicht.

- **Chargen fuer grosse Quellen.** `eam-ai build` teilt den Quelltext ab einer
  Promptlaenge von 200.000 Zeichen in Abschnitte von 120.000 Zeichen
  (`--chargen-zeichen`, `--chargen-schwelle`) und setzt sie vor der Pruefung
  wieder zusammen. Jede Charge sieht die bereits erfassten Elemente, damit
  Querverweise keine Dubletten erzeugen. Der Bericht nennt die Chargen in
  `meta.extraction.chargen`.
  Messung am MASC-Handbuch (106 Absaetze, vier Chargen): 114 Elemente und
  50 Beziehungen gegenueber 109 und 48 im Einzelaufruf, 0 Findings.
- **Wiederverwendung ueber Paketgrenzen.** Das Startpaket ist beim Bauen die
  Basis: seine Kennungen bleiben woertlich erhalten, gleiche Elemente aus dem
  Lauf werden ueber Name und Stereotyp auf die vorhandene Zeile gebogen -- auch
  dann, wenn sie im Arbeitspaket statt im Standardpaket stehen. Ein Kasten, der
  seine Wurzel wie das Dach nennt, legt kein zweites Dach mehr an
  (`Standard/Standard`).
- **Fortsetzen statt neu bauen.** `--modell bestand.qea` liest die Elemente des
  vorhandenen Modells und legt sie als bekannten Bestand in den Prompt. Das
  Ergebnis enthaelt Bestand und Neues; die Kennungen des Bestands bleiben
  unveraendert, der Bericht nennt den Gesamtstand und den Zuwachs des Laufs.
- **Namensabgleich beim Zusammenfuehren.** `merge --per-name` legt Elemente
  zusaetzlich ueber Name und Stereotyp zusammen. Ohne den Schalter entscheidet
  allein die `ea_guid`; der Writer vergibt fuer gleiche Pakete, Namen und
  Stereotypen dieselbe Kennung, sodass getrennte Laeufe aus demselben Haus
  ohnehin zusammenfinden. Der Schalter ist fuer Modelle aus fremder Quelle.
- **Startpaket im Bau.** `--startpaket` liest die Standardelemente (StEKa) und
  legt sie in den Prompt; nach dem Export werden sie uebernommen, mit
  woertlich unveraenderter `ea_guid`. Die HTML-Fassung liest das geladene
  Grundgeruest und nennt bis zu 300 Elemente im Prompt.
  Damit entstehen keine Dubletten mehr zu Elementen, die im Startpaket stehen.

## 3.0.4 - 2026-10-25

### Geaendert

- **Version angeglichen.** Paket (`eam_ai.__version__`, `pyproject.toml`) und
  Release-Tags liefen auseinander: im Release 3.0.3 steckte ein Paket 2.4.0.
  Beide stehen jetzt auf 3.0.4.
- **README neu.** Einstieg ohne Vorkenntnisse, Workflow in sieben Schritten,
  je ein Satz pro Werkzeug, alle Downloads auf `EAM-Toolfamilie`. Der
  Rueckweg ist ausdruecklich als Test beschrieben, nicht als Ablaufschritt.
- **Startseite.** Workflow-Abschnitt ergaenzt; keine festen Katalogzahlen mehr
  in der MDG-Karte (die Anzahl haengt vom MDG-Stand ab).
- **Container-Angaben** kommen aus einer Konstante; Image-Name und Link
  stimmen wieder mit dem ausgelieferten Paket ueberein.

### Behoben

- **`merge` scheiterte an aelteren Modellen.** `t_xref.XrefID` ist dort eine
  Zahl, in neueren eine GUID. Der Code schrieb immer eine GUID und brach mit
  `datatype mismatch` mitten im Schreiben ab. Die Form richtet sich jetzt nach
  dem Zielschema; eine Vorabpruefung nennt Tabelle und Spalte statt der
  SQLite-Meldung.
- **Vererbung aus `baseStereotypes` wurde ignoriert.** Die MDG verteilt Eltern
  auf `generalizes` und `baseStereotypes`. Ohne das zweite Feld listete die
  Sammelrolle `CapableElement` nur 12 statt 30 Mitglieder; Kanten wie
  `Exhibits` (Dienst erbringt Faehigkeit) entfielen still, der Validator
  verwarf sie zusaetzlich. Betroffen waren Extraktion **und** Pruefung. Die
  Eltern stehen jetzt zusaetzlich an jeder Elementzeile im Prompt.
  Messbar am MASC-Handbuch: 38 auf 48 Beziehungen, davon 9 neue `Exhibits`.
- **Speichern im Editor scheiterte an aelteren Modellen.** Das Update schrieb
  unbedingt in `ModifiedDate`, das diese Schemata in `t_object` und `t_diagram`
  nicht fuehren — jede Aenderung endete mit "no such column", ohne dass eine
  Datei entstand. Schreibspalten werden jetzt gegen `PRAGMA table_info`
  geprueft (Editor, Suite, Analyzer).

## 2.4.0 - 2026-10-24

### Hinzugefuegt

- **Natuerlichsprachliche Korrektur (`eam-ai korrigiere`).** Eine Anweisung
  wird zu einer nachpruefbaren Operationsliste. Mit `--backend openai/ollama`
  formuliert ein Sprachmodell die Operationen; ohne Backend arbeitet eine
  feste deutsche Befehlsgrammatik. Jedes Ziel wird gegen das geladene Modell
  aufgeloest -- erfundene Namen werden abgelehnt.
- **Zweistufig und schonend.** Ohne `--apply` bleibt der Lauf eine Vorschau.
  Mit `--apply` entsteht eine neue `.qea`; das Original bleibt unberuehrt.
  Loeschoperationen verlangen zusaetzlich `--ja`.
- **MDG-Pruefung auch fuer Korrekturen.** Mit `--mdg` wird jede Operation vor
  dem Schreiben gegen das Regelwerk geprueft; ein neuer Fehler fuehrt zur
  Ablehnung der Operation.

## 2.3.1 - 2026-10-24

### Geaendert

- **Produktname durchgaengig: EAM AI Suite Python.** README, Weboberflaeche,
  CLI-Beschreibung, Dockerfile, CI und Schema tragen denselben Namen; das
  Repository heisst `EAM-AI-Suite-Python`. Technische Kennungen bleiben
  stabil: Python-Modul `eam_ai`, Befehl `eam-ai`, Wheel-Name.

## 2.3.0 - 2026-10-24

### Hinzugefuegt

- **Pipeline ohne internen Fixture-Store.** `ci.stage_fixtures --optional`
  laesst den Build-Job auch dann laufen, wenn kein Store konfiguriert ist;
  als Technologie dient der synthetische Auszug `tests/fixtures/admbw_auszug.xml`.
  Ist ein Store gesetzt, bleibt die Pruefung streng (Groesse, SHA-256).
- **Freigabe aus der Pipeline.** Der Release-Job reicht `GITHUB_TOKEN` durch
  und legt fuer Tags `vX.Y.Z` eine Freigabe mit Pruefsummen und Modell an.
- **Container 2.3.0** enthaelt den vollen Befehlssatz (Ansicht, Handbuch,
  Rueckweg, Werkzeugkasten), nicht nur die Weboberflaeche.

### Behoben

- Tests hingen an einem absoluten Entwicklerpfad; auf dem CI-Runner brach
  dadurch die Sammlung mit `PermissionError` ab. Die Fixture-Suche prueft
  jetzt Store, Repo und Altpfad und behandelt fehlende Rechte wie "fehlt".

### Hinzugefuegt

- **Grafische Modellansicht.** `viewer_html.py` baut aus einer `.qea` eine
  einzige, selbsttragende HTML-Datei (Canvas + Vanilla-JS, kein CDN, kein
  Netz): Force-Layout mit festem Startwert, Zoom/Pan, Knoten ziehen, Farbe je
  Paket, Filter nach Paket/Stereotyp/Typ, Volltextsuche mit Hervorhebung,
  Detailpanel mit Notiz und allen ein- und ausgehenden Kanten, Legende und
  Zaehler. Kanten auf Paketspiegel werden gezaehlt und gemeldet,
  `--max-knoten` kappt sehr grosse Modelle sichtbar.
- **„Modell ansehen“ in der Weboberflaeche.** Nach einem erfolgreichen Bau
  liefert `/api/jobs/<id>/viewer` (Alias `/job/<id>/viewer`) die Ansicht der
  erzeugten `.qea` on the fly; das Manifest verlinkt sie als
  `links.viewer`.
- `tests/test_viewer_html.py`: 19 Faelle — Selbsttragung, valides JSON,
  Determinismus (zwei Laeufe byte-identisch), Umlaute, XSS ueber einen
  Elementnamen mit `<script>`, Spiegel-Kanten, `--max-knoten`, klare Fehler.

## 2.2.0 - 2026-10-22

### Hinzugefuegt

- **PDF als Prosa-Quelle.** `.pdf` wird von CLI und Weboberflaeche gelesen --
  ohne Fremdbibliothek (`pdf_text.py`, nur Standardbibliothek). Der Leser
  entpackt Objekt- und Inhaltsstroeme, wertet `Tj`/`TJ` aus, zieht
  `/ToUnicode`-Tabellen fuer Umlaute heran und setzt den Zeichenzustand ueber
  Stroemgrenzen hinweg fort (Word-Exporte beginnen mitten im Text).
- `tests/test_pdf_text.py`: acht Faelle -- Prosa, Umlaute ueber ToUnicode,
  `TJ`-Arrays und Absaetze, unkomprimierte Stroeme, Scan ohne Textebene,
  passwortgeschuetzte Datei, falscher Dateityp, leere Datei.

### Grenzen (werden laut gemeldet, nicht still falsch beantwortet)

- Reine Scans ohne Textebene brechen mit Hinweis ab.
- Passwortgeschuetzte PDFs brechen mit Hinweis ab.
- Schriften ohne jede Zeichentabelle koennen nicht sicher zugeordnet werden;
  der Leser liefert dann keinen Zeichensalat, sondern einen Fehler.

## 2.1.0 - 2026-10-22

### Hinzugefuegt

- `eam-ai serve`: Weboberflaeche auf Basis von `http.server` (Standard-
  bibliothek, kein Framework), eine Seite mit Upload, Text, optionalem
  Modell-Endpunkt, Fortschritt und ZIP-Download. Jeder Bau laeuft als eigener
  Prozess mit demselben CLI-Aufruf; Grenzen fuer Upload (25 MB), Zeit (120 s),
  parallele Laeufe (2) und Aufbewahrung, Aufraeumen der Arbeitsverzeichnisse,
  sanitisierte Dateinamen, kein Verzeichnis-Listing.
- `Dockerfile` und `.dockerignore`: `python:3.12-slim`, Benutzer `eamai`
  (UID 10001), `HEALTHCHECK` auf `/healthz`, Grenzen im Startbefehl.
- `tests/test_webui.py`: HTTP-Endpunkt baut aus Beispiel-Text eine von
  `qea_reader` lesbare `.qea`, Upload ueber der Grenze, sanitisierte Namen,
  Zeitlimit, Aufraeumen, klare Fehler.
- `ci/lint_core.py`: `webui.py` ist die benannte Netz-Ausnahme (Frontend) und
  darf den Kern nicht importieren; Regel `kern`.
- `README.md`: Abschnitt „Weboberflaeche und Container“ inklusive
  `docker save`/`docker load` fuer den Offline-Transfer.
- Pipeline `lint -> test -> build -> release` in `.gitlab-ci.yml` (GitLab
  Community Edition, on-prem) und `.github/workflows/ci.yml` (GitHub Actions,
  identische Befehlsfolge; `ci/validate_pipeline.py` prueft die Paritaet).
- CI-Bausteine in `ci/`: `lint_core`, `validate_pipeline`, `stage_fixtures`
  (Fixtures aus internem Store, SHA-256 gegen Manifest), `run_tests`
  (pytest mit Netzsperre und JUnit-Bericht), `build_reference` (zwei Seeds,
  Byte-Vergleich), `release` (Berichte und Freigabe, `--dry-run` ohne Netz).
- `CI.md` mit Aufbau, Variablen, Artefakten und dem Nachweis des
  Container-Laufs.
- `pyproject.toml` mit Entry-Point `eam-ai = "eam_ai:main"`, keine
  Laufzeitabhaengigkeiten, Mindeststand Python 3.11.
- Deterministisches PEP-517-Backend `build_backend.py` (nur Standardbibliothek):
  feste Zeitstempel, sortierte Eintraege, keine Kompression, keine Build-IDs.
- Offline-Bundle `tools/build_bundle.py`: Wheel, Start- und Installationsskripte
  fuer Linux und Windows, Beispiel, Quellstand, `BUILD-INFO.json`,
  `SHA256SUMS.txt` sowie `.zip` und `.tar.gz`.
- `eam-ai --version`.
- `PACKAGING.md` und `tests/test_packaging.py` (Version, Inhalt, Reproduzierbarkeit).

### Geaendert

- `README.md` verweist auf Installation und Offline-Betrieb.

## 2.0.0 - 2026-10-22

Sammelstand des Gesamtlaufs:

- `eam_ai.py` und `eam-ai`: MDG laden, Text lesen, extrahieren, validieren,
  emittieren; `findings.json` in jedem Lauf, Exit 0 nur bei null Fehlern.
- Herkunft je KI-Element als Tagged Value plus `quellen.json`.
- Alle 15 AAroN-Pflichttabellen im `.qea`-Writer.
- Golden-Test gegen die Musterarchitektur (byte-identischer Roundtrip).
- Regelpfad ohne KI (`eam_suite.py`, `table_import.py`), CSV/XLSX nur mit stdlib.

## 1.0.0 - 2026-10-21

Grundgeruest: `mdg_parser`, `rules_schema`, `validator`, `qea_reader`,
`qea_writer` und `IR_SPEC.md`.
