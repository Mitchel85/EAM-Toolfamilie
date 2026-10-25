# Changelog

Alle Aenderungen am Lieferumfang. Die Version steht an genau drei Stellen und
wird von `tests/test_packaging.py` gegeneinander geprueft:
`eam_ai.__version__`, `pyproject.toml` und diese Datei.

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
