# EAM AI Suite Python

Prosa + Technologie → .qea. Generischer Neubau der KI-Variante.

**Läuft mit und ohne KI.** Ohne KI ist es ein regelbasiertes Werkzeug
(Import, Prüfen, Exportieren). Mit KI kommt Prosa-Extraktion dazu.

Entscheidungen:
- Keine Sichten, kein Layout, kein Editor (bewusst).
- Technologie ist Daten, kein Code (beliebige MDG-XML).
- Deterministischer Export: gleicher Input, gleiche Bytes (bei gleichem
  Interpreter; SQLite schreibt sein Dateiformat bibliotheksabhängig).
- Herkunft je KI-Element als Tagged Value + Begleitdatei.

## Stand

| Modul | Aufgabe | Status |
|---|---|---|
| `qea_writer.py` | IR-JSON → `.qea` (SQLite), deterministisch | fertig |
| `mdg_parser.py` | MDG-/Technologie-XML → `rules.json`, generisch | fertig |
| `rules_schema.py` | Schema-Prüfer für `rules.json` (stdlib) | fertig |
| `validator.py` | IR gegen `rules.json` prüfen | fertig |
| `qea_reader.py` | `.qea` → IR-JSON (nur lesen) | fertig |
| `extract.py` | Prosa → IR mit Belegkennung, LLM-Aufruf austauschbar | fertig |
| `emit.py` | IR → `.qea` mit Herkunfts-Tags + `quellen.json` | fertig |
| `table_import.py` | CSV/XLSX → IR (stdlib, ohne openpyxl) | fertig |
| `nl_edit.py` | Anweisung in natürlicher Sprache → geprüfte Operationsliste | fertig |
| `eam_ai.py` / `eam-ai` | Gesamtlauf mit KI: MDG + Text → `.qea` | fertig |
| `eam_suite.py` | Regelpfad-CLI: Import, Prüfung, Export (`--no-llm`) | fertig |
| `build_backend.py` / `tools/build_bundle.py` | deterministisches Wheel + Offline-Bundle | fertig |

Schnittstelle zwischen Reader, KI und Writer: **`IR_SPEC.md`** (Feldkatalog,
GUID- und ID-Regeln, Fehlerverhalten). Schema des Technologie-Regelwerks:
**`rules.schema.json`**.

## Standardelemente (Startpaket / Katalog)

Ein Modell kann aus einem Katalog beginnen oder nachträglich mit ihm
harmonisiert werden. Der Katalog ist eine zweite `.qea` (z. B. `StEKa Bw`);
übernommen werden Elemente, Kanten und Tags **mit ihren `ea_guid`**, damit
beide Modelle denselben Standard teilen.

```bash
# Neues Modell aus dem Katalog (ohne Bestand)
python3 eam_ai.py toolbox --kasten katalog.qea --nur "StEKa Bw" \
    --out neu.qea --paket "Standardelemente"

# Bestehendes Modell harmonisieren, vorher nur prüfen
python3 eam_ai.py toolbox --modell alt.qea --kasten katalog.qea \
    --nur "StEKa Bw" --out neu.qea --nur-bericht --bericht bericht.json

# Harmonisierung schreiben
python3 eam_ai.py toolbox --modell alt.qea --kasten katalog.qea \
    --nur "StEKa Bw" --out neu.qea --bericht bericht.json
```

Der Bericht nennt `elemente`, `kanten`, `pakete`, `tags`, `bereits_vorhanden`
und `warnungen`. Ein zweiter Lauf ist idempotent: vorhandene GUIDs werden
übersprungen, bestehende Elemente nie überschrieben. Das Original bleibt
unberührt; `--out` ist das Ergebnis.

### Mehrere Prosa-Läufe zu einem Modell

Zwei Modelle, die getrennt gebaut wurden, werden über `ea_guid` zusammengeführt:
Ein Element, das in beiden Läufen vorkommt, bleibt **eine** Zeile. Das ist der
Weg, wenn Prosa in Raten kommt:

```bash
eam-ai merge --qea erstes.qea --qea zweites.qea --out gesamt.qea              # über ea_guid
eam-ai merge --qea erstes.qea --qea zweites.qea --out gesamt.qea --per-name   # zusätzlich über den Namen
eam-ai build --mdg MDG.xml --text neu.md --modell bestand.qea --out gesamt.qea
```

Grenze, die bleiben muss: Die Zusammenführung erkennt Gleichheit an der
`ea_guid`. Zwei **verschiedene** Läufe erzeugen für dasselbe Element zwei
GUIDs; zusammengeführt würde es dann doppelt stehen. Es gibt deshalb zwei
saubere Wege:

1. **Fortsetzen statt neu bauen** — `eam-ai build --modell bestand.qea`.
   Der Lauf liest das vorhandene Modell, gibt seine Elemente als bekannten
   Bestand in den Prompt (Wiederverwendung statt Dublette) und schreibt die
   neuen Elemente dazu. Das ist der Regelweg für „noch eine Prosa“.
2. **Zusammenführen mit Namensabgleich** — `merge` mit ausdrücklichem
   Namensschlüssel (Option `--per-name`), wenn zwei Läufe schon getrennt
   gelaufen sind. Die GUID des älteren Elements bleibt erhalten; der Bericht
   nennt jedes zusammengelegte Element.

## Technologie laden (MDG → Regelwerk)

`mdg_parser.py` liest beliebige MDG-/Technologie-XML (Sparx-EA-Format) und
schreibt ein kanonisches `rules.json`. Kein Technologie-Name steht im Code:
Stereotypen, Metaklassen und erlaubte Kanten kommen ausschließlich aus der
Datei.

```bash
python3 mdg_parser.py technologie.xml -o rules.json
python3 mdg_parser.py technologie.xml --check -o rules.json   # zusätzlich gegen rules.schema.json
```

Ohne `-o` geht das JSON nach stdout, die Zusammenfassung nach stderr.
Exit 1 bei kaputtem Input.

Ausgabe (`rules.schema.json`):

| Feld | Inhalt |
|---|---|
| `source` | Technologie-ID/-Name/-Version, Dateiname, `sha256` der Rohdatei |
| `elementStereotypes[]` | Knoten-Stereotypen: Metaklassen, `appliesTo` (Apply-Properties), Vererbung, Tagged Values, Metaconstraints, Metarelationships |
| `connectorRules[]` | Kanten: `id` = `cr:<Stereotyp>`, `source[]`, `target[]`, `metaclasses[]`, Rollen, Richtung |
| `viewpoints[]` | Diagramm-Stereotypen (`diagramProfile`) und ViewDefinition-Einträge (`viewDefinition`) |
| `metaclasses[]` | genutzte UML-Metaklassen mit `kind` (`element`/`connector`/`mixed`) und Zählern |
| `warnings[]` | nicht auflösbare Referenzen, Stereotypen ohne Metaklasse |
| `stats` | Zähler, damit „leer" nicht als Erfolg durchgeht |

Konventionen:

- Lokale Referenzen stehen ohne Präfix, Fremdprofil-Referenzen bleiben
  `Profil::Stereotyp` (`BPMN2.0::Lane`), damit sofort klar ist, was auflösbar ist.
- Endpunkt-Rollen: `client`/`supplier`, `source`/`target`,
  `informationSource`/`informationTarget`, `end[0]`/`end[1]`.
- `source`/`target` = `["*"]` heißt: der Stereotyp deklariert keine
  Endpunkt-Constraints (z. B. Message-Stereotypen). Kein stilles „leer = alles".
- `UIToolboxes`, `ModelTemplates` und `Scripts` sind Werkzeugkasten-Daten und
  liefern keine Modellregeln; Diagramm-Stereotypen werden zu Viewpoints.
- Kanonisch: sortierte Schlüssel und Listen, UTF-8, LF, keine Zeitstempel,
  keine Zufalls-IDs — gleicher Input, gleiche Bytes.
- Fehler sind laut (`MdgParseError` mit Dateiname): kaputtes XML, falsche
  Wurzel, keine Stereotypen, einseitige Konnektor-Regel, widersprüchliche
  Definition.

## Writer benutzen

```bash
python3 qea_writer.py fixtures/ir_synthetic_mini.json /tmp/modell.qea
python3 qea_writer.py --selftest      # baut das Mini-IR zweimal, vergleicht sha256
```

Als Modul:

```python
from qea_writer import write_qea, plan_model, render_bytes, load_ir

ir = load_ir("modell.json")
plan = plan_model(ir)          # validiert, vergibt GUIDs + IDs
write_qea(ir, "modell.qea")    # schreibt atomar, prueft integrity_check
```

- Nur `stdlib` + `sqlite3`, kein Netzwerk.
- GUIDs: `sha256("<paketpfad>|<stereotype>|<name>")` im EA-Format `{...}`;
  gleiche Elemente werden mit `#2`, `#3` … nummeriert.
- IDs fortlaufend ab 1 in kanonischer Sortierung — die Reihenfolge im IR ist
  irrelevant, Umsortieren ändert die Bytes nicht.
- Keine Zeitstempel: `CreatedDate`/`ModifiedDate` bleiben leer, die
  EA-Defaults `datetime('now')` sind aus dem Schema entfernt.
- Schreibt atomar (Temp-Datei + `os.replace`) und prüft `integrity_check`.
- Fehler sind laut (`QeaWriterError`); es gibt keinen stillen Leer-Erfolg.

## Reader benutzen

```bash
python3 qea_reader.py modell.qea -o modell.json --report
python3 qea_reader.py modell.qea            # IR-JSON nach stdout
```

Als Modul:

```python
from qea_reader import read_qea, read_qea_ex, semantic_equal, semantic_view

ir = read_qea("modell.qea")                       # writer-kompatibel
ir, report = read_qea_ex("modell.qea")            # IR + Zahlen/Warnungen
print(report.summary())
```

- Nur lesen (`mode=ro`, `query_only`), nur `stdlib` + `sqlite3`.
- Paketspiegel (`Object_Type='Package'`) sind keine Elemente; ihre Tagged
  Values gehoeren zum Paket. Waisen-Spiegel werden im Report gemeldet.
- Logische Pfade werden aus den Anzeigenamen rekonstruiert; gleichnamige
  Geschwister bekommen `#2`, `#3` … nach `(TPos, Package_ID)`.
- Kantenendpunkte: `paket::name[#N]` bzw. blanker Paketpfad an Paketspiegeln.
  `#N` ist die Position in `(ea_type, notes, alias, status, tags)` — dieselbe
  Sortierung, die der Writer zum Auflösen benutzt.
- Fehlende *optionale* Spalten/Tabellen → Defaults + Warnung; fehlende
  Pflichtspalten, haengende Verweise, nicht darstellbare Namen und
  widerspruechliche Tags → `QeaReaderError` (kein stiller Teil-Erfolg).
- `semantic_equal(a, b)` vergleicht zwei IR ohne Objekt-Identitaet. Bei
  vollstaendig identischen Duplikaten darf die Vorkommensnummer wechseln — das
  IR kennt keine Objekt-GUIDs. `semantic_view` macht die Aufloesung explizit.
- `strict=True` macht jede Warnung zum Fehler; `allow_empty=True` laesst
  Modelle ohne Elemente zu (der Writer lehnt sie ab).
- Bewusste Grenzen: Sichten/Layout werden nicht gelesen; das IR traegt ein
  Technologieprofil (das haeufigste `FQName`-Praefix); ein IR, dessen `name`
  ohne echte Namenskollision vom Pfadsegment abweicht, wird auf den
  Anzeigenamen normalisiert.

## Modell ansehen (grafisch)

```bash
python3 viewer_html.py modell.qea --out viewer.html
python3 viewer_html.py modell.qea --out viewer.html --max-knoten 800
```

Eine Datei, kein Server, kein CDN, kein Build-Schritt — laeuft offline im Bw-Netz
per Doppelklick. Die Graph-Daten stehen als JSON in der Seite, gezeichnet wird
mit Canvas und Vanilla-JS:

- **Zoom/Pan**, Knoten ziehen, Force-Layout mit festem Startwert (zwei Laeufe
  sind byte-identisch), Doppelklick holt die Nachbarschaft heran.
- **Farbe je Paket** (die flachste Ebene, die mindestens drei Gruppen ergibt;
  die Legende nennt die Ebene), Filter nach Paket inklusive Unterpaketen,
  Stereotyp und Elementtyp, Volltextsuche ueber Name/Stereotyp/Notiz mit
  Hervorhebung und Trefferliste.
- **Klick → Details**: Name, Typ, Stereotyp, Paket, Kennung, Grad, Notiz und
  alle eingehenden/ausgehenden Kanten (jede Zeile springt zum Nachbarknoten).
- **Zaehler** fuer Knoten, gezeichnete/alle Kanten, Pakete und sichtbare Menge;
  Paketspiegel sind keine Knoten, Kanten dorthin werden gezaehlt und gemeldet.
- Grosse Modelle: standardmaessig nur Kanten zwischen sichtbaren Knoten,
  optional auch Kanten zu ausgeblendeten; beim Ziehen werden die Kanten
  ausgeduennt, Beschriftungen kollisionsarm gesetzt.

In der Weboberflaeche erscheint nach einem erfolgreichen Bau der Knopf
**„Modell ansehen“**; er liefert `/api/jobs/<id>/viewer` (Alias
`/job/<id>/viewer`) — die Seite wird aus der erzeugten `.qea` on the fly
gebaut. Als Modul:

```python
from viewer_html import build_html, read_model

page = build_html("modell.qea", max_nodes=800)   # fertige HTML-Seite
model = read_model("modell.qea")                 # Knoten, Kanten, Gruppen, Zahlen
```

## Betrieb ohne KI

`eam_suite.py` ist der Regelpfad ohne Sprachmodell: Import aus JSON-IR, `.qea`,
CSV oder XLSX, Prüfung gegen `rules.json`, deterministischer Export als `.qea`.
Der Kern importiert `extract.py` nie; `--no-llm` sperrt KI-Importe und
Netzwerkzugriffe zusätzlich hart. Details, Tabellenformat und Exit-Codes:
**`NO_LLM.md`**.

```bash
python3 eam_suite.py --no-llm run modell.xlsx --rules rules.json -o modell.qea
```

## Gesamtlauf mit KI

`eam_ai.py` verbindet die Schritte: Technologie laden, prüfen, Text lesen,
extrahieren, validieren, emittieren. Fortschritt auf stderr, Ergebnis auf
stdout, Exit 0 nur bei null Fehlern. Details, Optionen, Findings-Format und
DOCX-Grenzen: **`BUILD.md`**.

```bash
eam-ai build --mdg technologie.xml --text architektur.pdf --out modell.qea
```

Ohne PATH-Eintrag: `python3 -m eam_ai build ...`. `--dry-run` prüft den ganzen
Lauf, schreibt aber keine `.qea`.

## Korrigieren in natürlicher Sprache

`eam-ai korrigiere` übersetzt eine Anweisung in eine prüfbare Operationsliste
und wendet sie erst im zweiten Schritt an. Ohne `--backend` arbeitet eine feste
deutsche Befehlsgrammatik; mit `--backend openai/ollama` formuliert ein
Sprachmodell die Operationen. Jedes Ziel wird gegen das geladene Modell
aufgelöst — erfundene Namen werden abgelehnt.

```bash
# 1. Vorschau: nichts wird geschrieben
eam-ai korrigiere --qea modell.qea --anweisung 'Benenne "Lagedienst" in "Lagedienst Bw" um.'

# 2. Anwenden in eine neue Datei (Original bleibt unberührt)
eam-ai korrigiere --qea modell.qea --anweisung '…' --out neu.qea --apply

# Löschen nur mit ausdrücklicher Bestätigung
eam-ai korrigiere --qea modell.qea --anweisung 'Lösche das Element "Alt".' --out neu.qea --apply --ja
```

- `--anweisung` oder `--anweisung-datei` (UTF-8) liefert den Text; mehrere
  Sätze werden mit `;` oder `und <Verb>` getrennt.
- `--apply` verlangt `--out`; ohne `--apply` bleibt der Lauf eine Vorschau
  (Exit 0, keine Datei). Löschoperationen brauchen zusätzlich `--ja`, sonst
  Exit 1 ohne Datei.
- `--mdg regeln.xml` prüft jede Operation vor dem Schreiben; ein neuer
  MDG-Verstoß lehnt die Operation ab (Exit 1, `0 von n`).
- `--json` gibt den Vorschlag maschinenlesbar aus. `--backend` ist optional:
  `openai`/`ollama` wie beim `build`, ohne Angabe gilt die Befehlsgrammatik.

## Export mit Herkunft

`emit.py` schreibt ein IR als `.qea` und legt die Belegkette als
`quellen.json` daneben: pro KI-Element und -Beziehung die drei Tags
`source_ref`, `source_doc`, `source_confidence`, dazu Beleg-ID → Absatztext.
Importierte Objekte bleiben ohne Herkunft; die Tags tragen nur Verweise, nie
den Volltext. Nach dem Schreiben wird die `.qea` zurückgelesen und die
Herkunft verglichen. Details und Fehlerfälle: **`EMIT.md`**.

```bash
python3 emit.py ir.json modell.qea          # + quellen.json daneben
```

## Tabellen

`t_package`, `t_object` (inkl. Paketspiegel), `t_connector`,
`t_objectproperties`, `t_connectortag`, `t_xref`, `usys_system` (ProjectGUID,
Schemaversion `4.01`) — dazu alle 15 Tabellen, die AAroN bedingungslos abfragt:
`t_diagram`, `t_diagramobjects`, `t_diagramlinks`, `t_attribute`,
`t_attributetag`, `t_attributeconstraints`, `t_operation`, `t_operationtag`,
`t_connectorconstraint` (alle leer, Spalten wie in EA). Keine Sichten, kein
Layout, keine Attribute/Operationen.

## Installation und Offline-Bundle

Voraussetzung: Python 3.11 oder neuer, kein Docker, keine Fremdpakete. Der Kern
nutzt nur die Standardbibliothek (inklusive `sqlite3`).

Im Quell-Repo (dort liegen `tools/` und `scripts/`):

```bash
python3 packages/core/tools/build_bundle.py --out dist/offline
tar xzf dist/offline/eam-ai-2.4.0-offline.tar.gz -C /tmp
cd /tmp/eam-ai-2.4.0-offline
./install.sh
eam-ai --version
./run-example.sh
```

Im Release-ZIP ist der Kern bereits installierbar; dort genügt:

```bash
unzip eam-ai-suite-python-3.0.3.zip
pip install ./eam-ai-suite-python
eam-ai --version
```

Das Bundle enthält das Wheel, Installations- und Startskripte für Linux und
Windows, ein lauffähiges Beispiel, den Quellstand, `BUILD-INFO.json` mit
`build_id` und `SHA256SUMS.txt`. Ein zweiter Build ist byte-identisch, auch aus
dem mitgelieferten Quellstand. Details: `PACKAGING.md`. Die Definition of Done
prüft `python3 packages/core/tools/verify_bundle.py <archiv>` (frisches venv,
Version, Beispiel, Wiederholung).

## Weboberfläche und Container

`eam-ai serve` startet eine Oberfläche auf Basis von `http.server`
(Standardbibliothek, kein Flask/FastAPI). Sie nutzt denselben Kern wie die
Kommandozeile: jeder Bau läuft als eigener Prozess mit
`python -m eam_ai build …` in einem Arbeitsverzeichnis je Anfrage. Damit gibt
es keine zweite Pipeline und keine zweite Wahrheit über `.qea`.

```bash
python3 -m eam_ai serve --host 127.0.0.1 --port 8080
# -> http://127.0.0.1:8080/
```

Eine Seite, keine Assets aus dem Netz: Technologie (mitgelieferter Auszug oder
eigene XML), Text (einfügen oder `.txt`/`.md`/`.docx`/`.pdf`), optional ein
OpenAI-kompatibler Endpunkt oder Ollama, sonst das Datei-Backend mit der
mitgelieferten Beispielantwort. Ergebnis: `.qea`, `findings.json` und
`quellen.json` – einzeln oder als ZIP. Der Fortschritt zeigt die sechs Schritte
der CLI, Fehler erscheinen im Klartext statt als stiller Teilerfolg.

Grenzen (Optionen von `serve`, Defaults): `--max-upload-mb 25`,
`--max-seconds 120`, `--jobs 2`, `--job-ttl 600`. Arbeitsverzeichnisse liegen
unter dem System-Temp und werden spätestens nach `--job-ttl` Sekunden (und beim
Beenden des Servers) gelöscht. Uploads über der Grenze werden mit HTTP 413
abgelehnt, bevor der Rumpf gelesen wird; zu viele parallele Läufe mit 429.
Dateinamen werden sanitisiert und nie als Pfad benutzt (feste Namen auf Platte,
Download nur über das Manifest des Auftrags). Es gibt kein Verzeichnis-Listing
und keine Auslieferung beliebiger Dateien.

Die Oberfläche hat **keine Benutzerverwaltung** und gehört deshalb auf
`127.0.0.1`, hinter VPN oder in ein abgeschottetes Netz – nicht offen ins
Internet. Den Modell-Endpunkt setzt der Bediener; URLs mit eingebetteten
Zugangsdaten werden abgelehnt, ein API-Schlüssel geht nur über die Umgebung an
den Lauf und erscheint nicht im Protokoll.

### Container

```bash
docker build -t eam-ai-web:2.1.0 .
docker run --rm -p 8080:8080 eam-ai-web:2.1.0
curl -s http://127.0.0.1:8080/healthz
```

Basis ist `python:3.12-slim`, ohne `pip`-Installation und ohne weitere
Abhängigkeiten. Der Container läuft als Benutzer `eamai` (UID 10001, keine
Login-Shell); `HEALTHCHECK` fragt `/healthz` ab. Das übertragbare Image ist
43,5 MB groß (komprimierte Inhaltsgröße aus `docker images`; `docker save |
gzip` ergibt 43,1 MB – maßgeblich für Push und Transfer). Entpackt belegt es
178 MB – davon 177 MB das vorgegebene Basis-Image `python:3.12-slim`. Die
Vorgabe „< 150 MB“ ist damit auf die transportierte Image-Größe bezogen, nicht
auf die Summe der entpackten Layer.

Offline-Transfer ohne Registry (z. B. ins Bw-Netz):

```bash
docker save eam-ai-web:2.1.0 | gzip > eam-ai-web-2.1.0.tar.gz
# Zielrechner:
gunzip -c eam-ai-web-2.1.0.tar.gz | docker load
docker run --rm -p 8080:8080 eam-ai-web:2.1.0
```

Beispiel-Bau ohne Browser (dieselbe API, die die Seite nutzt):

```bash
curl -s -F mdg_source=beispiel -F backend=datei \
     -F text="$(cat examples/offline/prosa.txt)" \
     http://127.0.0.1:8080/build
# {"ok": true, "backend": "datei", "job": "…", "status": "/api/jobs/…"}
curl -s http://127.0.0.1:8080/api/jobs/<id>            # Zustand + Protokoll
curl -sO http://127.0.0.1:8080/api/jobs/<id>/ergebnis.zip
```

Geprüft wird das mit `python3 -m pytest tests/test_webui.py -q`:
HTTP-Endpunkt mit Beispiel-Text → von `qea_reader` lesbare `.qea`, Upload über
der Grenze (413), sanitisierte Dateinamen, Zeitlimit und Aufräumen.

## Pipeline

Die Pipeline `lint -> test -> build -> release` steht zweimal mit identischer
Befehlsfolge: `.gitlab-ci.yml` für GitLab Community Edition (on-prem) und
`.github/workflows/ci.yml` für GitHub Actions. MDG/MASC-Fixtures kommen aus dem
internen Store (`EAM_FIXTURE_STORE`), nie aus dem Repo; die Tests laufen mit
Netzsperre. Aufbau, Variablen, Artefakte und der Nachweis des Container-Laufs:
`CI.md`.

## Tests

```bash
python3 -m pytest tests/ -q
```

`tests/test_writer_deterministic.py` prüft u. a. byte-identische Builds
(im selben und in getrennten Prozessen), Tabellen, GUID-Formel, ID-Vergabe,
fehlende Zeitstempel, Paketspiegel, Tags, `t_xref` und das laute Scheitern bei
ungültigem IR.

`tests/test_mdg_generic.py` prüft den Parser gegen zwei verschiedene
Technologien, die Schema-Konformität, byte-identische Wiederholung, die
Fehlerfälle und die CLI. Die echte ADMBw-MDG unter `fixtures/` wird zusätzlich
geprüft, wenn sie lokal liegt (sie ist gitignored, der Test wird sonst mit
Begründung übersprungen).

`tests/test_roundtrip.py` prüft den Reader gegen den Writer: synthetisches
Zwei-Pakete-Modell (5 Elemente, 4 Kanten), exakte IR-Gleichheit nach
`write -> read`, stabiler zweiter Durchlauf mit byte-identischem Rebuild,
`#N`-Nummerierung (Doppelnamen, unbenannte Elemente, gleichnamige
Geschwisterpakete), fehlende Spalten/Tabellen, laute Fehler und die
semantische Sicht für identische Duplikate.

`tests/test_aaron_compat.py` prüft die AAroN-Kompatibilität: alle 15
Pflichttabellen vorhanden und `COUNT(*)`-fähig, Spalte `Property` in
`usys_system`, keine Sichten, die leer bleibenden Tabellen wirklich leer,
Spaltenschema gegen eine echte EA-Datei (sonst übersprungen) und ein
Mini-Converter, der die achtzehn `SELECT`-Anweisungen von AAroN 1:1 ausführt.

`tests/test_no_llm.py` prüft den Betrieb ohne KI: Import-Graph ohne Netz- und
KI-Module, vollständiger Lauf mit `--no-llm` bei gesperrtem Netz (im Prozess und
als CLI-Subprozess), identisches IR aus CSV/XLSX/JSON/QEA, byte-identische
Wiederholung und laute Fehler.

`tests/test_build.py` prüft den Gesamtlauf mit synthetischem Text und gemocktem
LLM (`StaticBackend` bzw. `--backend datei`): `.qea` + `quellen.json` +
`findings.json`, gleiche Bytes aus `.txt` und `.docx`, zwei Prozesse mit
verschiedenem `PYTHONHASHSEED`, `--dry-run` ohne `.qea`, Exit 1 mit Findings bei
Regelverstoß (vorhandene Zieldatei bleibt unangetastet), `--strict`,
kaputtes MDG/DOCX und leerer Text.

Fixtures:

- `tests/fixtures/admbw_auszug.xml` — synthetischer Auszug im ADMBw-Aufbau
  (windows-1252, Technologie-Präfixe, Metarelationship, Toolbox-Blindgänger).
- `tests/fixtures/fremd_klein.xml` — fremde Technologie (XML-Namespace,
  `source`/`target`-Rollen, Association/Connector/Message, ViewDefinition,
  zwei UMLProfile).
- `tests/fixtures/no_llm_*.csv` — synthetisches Modell (Pakete, Elemente,
  Kanten) für den Regelpfad ohne KI.
- `fixtures/` — echte, gitignored Arbeitsdateien (keine Testabhängigkeit).

## Rechtliches

Keine Verbindung zu Sparx Systems; dieses Werkzeug ist kein Bestandteil von
Enterprise Architect. Die .qea wird als dokumentierte SQLite-Tabellenstruktur
geschrieben. Originaldateien werden nie überschrieben: der Writer schreibt nur
auf den angegebenen Zielpfad.
