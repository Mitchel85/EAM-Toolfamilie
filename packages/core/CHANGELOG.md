# Changelog

Alle Aenderungen am Lieferumfang. Die Version steht an genau drei Stellen und
wird von `tests/test_packaging.py` gegeneinander geprueft:
`eam_ai.__version__`, `pyproject.toml` und diese Datei.

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
