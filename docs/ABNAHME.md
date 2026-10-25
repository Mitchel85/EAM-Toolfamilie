# Abnahme: der MASC-Rundlauf

Stand 24.10.2026. Diese Datei hält den Durchlauf fest, der zählt: ein
Bedienhandbuch hinein, eine Architektur heraus, dieselbe Architektur wieder
als Handbuch — mit Zahlen, nicht mit Eindrücken.

## Aufbau des Laufs

| Schritt | Eingabe | Werkzeug | Ergebnis |
|---|---|---|---|
| 1 | `01-quelle-handbuch.md` (7.990 Wörter) | `eam-ai build --repair` | `09-volltext-modell.qea` |
| 2 | `.qea` | `handbuch_generator.py` | `10-volltext-handbuch.md` |
| 3 | Quelle + Rückweg | `prosa_vergleich.py` | `10-vergleich.json` |
| 4 | Modell + StEKa | `eam-ai toolbox` | `11-mit-steka.qea` |
| 5 | Modell | `viewer_html.py` | `12-viewer.html` |
| 6 | Modell + Anweisung | `eam-ai korrigiere --apply` | `05-korrigiert.qea` |
| 7 | Modell | Open-WebUI-Tool | Statistik + Trefferliste |

Alle Dateien liegen unter
`MASC-Roundtrip/masc-roundtrip/`.

## Kopfzeile: der gültige Stand

| Kennzahl | Wert | Quelle |
|---|---|---|
| Faktenabdeckung Rückweg | **98,4 %** (63/64) | dritter Lauf, `13-vergleich.json` |
| Faktenabdeckung ohne Notizen | 20,3 % (13/64) | Gegenprobe, dritter Lauf |
| Bezeichnungen | **100 %** | alle Läufe |
| Notizen vollständig | **65/65** | dritter Lauf |
| Belegte Textabsätze | **27/27** | dritter Lauf |
| Gültige Beziehungen | 4 von 11 gelieferten | dritter Lauf; vierter Lauf: 6/6 |
| Kantenausbeute | **75,0 % / 100,0 %** (zwei Läufe) | vierter Lauf, `18`/`19` |
| MDG-Prüfung | 0 Fehler, 0 Warnungen | alle Läufe |
| Sprachverstöße | 0 | alle Läufe |
| Open-WebUI-Werkzeug | **OK** (Datei, Statistik, Suche, Paketbaum) | `apps/mcp/checks/verify_openwebui.py` |
| Download-Einstieg | **7 Karten, 14 Release-Assets** | `START-HIER.html`, Release `v3.0.2` |
| Release `v3.0.2` | **14 Assets**, `sha256sum -c` **11/11 OK** | Asset-Prüfung 24.10. |
| Release `v2.4.3` | **10 Assets**, `sha256sum -c` OK | Asset-Prüfung 24.10. |

Die Abschnitte darunter sind der Verlauf in der Reihenfolge der Läufe; die
Zahlen dort sind historisch und mit dem jeweiligen Stand gemessen.

## Messwerte

### Extraktion

- 56 Absätze gelesen, **79 Elemente** und **3 Beziehungen** erzeugt.
- **0 Fehler, 0 Warnungen** nach der Reparaturrunde.
- **246 Herkunfts-Tags** (`source_ref`, `source_doc`, `source_confidence`).
- Notizen sind wörtlicher Quelltext: passt eine Modellantwort nicht wörtlich
  zum Absatz, ersetzt der Kern sie durch den Absatz selbst
  (`_note_wortgleich`). Deshalb steht in jeder Notiz ein belegter Satz, keine
  Zusammenfassung.

### Rückweg (Handbuch)

- **79 von 79 Bezeichnungen** im Text (100 %).
- **74,6 % Faktenabdeckung** (50 von 67 Sätzen, `difflib`, Schwelle 72 %).
  Das ist **Wortlaut-Treue**, kein Faktennachweis: Passiv und Paraphrase
  fallen durch, obwohl der Fakt im Text steht. Vorher: 19,4 % — der Sprung
  kommt aus den wörtlichen Notizen, nicht aus erfundenen Sätzen.
- 10 Kapitel, 0 Verstöße gegen die Sprachliste.

### Standardelemente

- StEKa Bw aus `Testarchitektur.qea`, Paket 141:
  **296 Elemente, 273 Kanten, 10 Pakete, 3.343 Tags**, 0 bereits vorhanden.
- Ergebnis `11-mit-steka.qea`: **375 Knoten, 276 Kanten, 12 Pakete**;
  das MASC-Element bleibt erhalten, der Katalog hängt als eigenes Paket darunter.

### Viewer

- `12-viewer.html`: **375 Knoten, 273 gezeichnete Kanten, 12 Pakete**.
- 3 Kanten enden auf einem Paketspiegel und werden bewusst nicht gezeichnet.
- Im Browser geprüft: keine `pageerror`, Filter „Architektur (79)“ liefert
  einen lesbaren Graphen.

### Sprachprofil (natürlichsprachliche Änderung)

Anweisung: „Benenne `Raketenantrieb RA-2x` in `Raketenantrieb RA-3x` um und
setze für `Schleuse` die Notiz …“.

- Vorschau: 2 Operationen, nichts geschrieben.
- `--apply`: **2 von 2 Operationen** angewendet.
- Nachgelesen in der Datei: `Raketenantrieb RA-3x` vorhanden, `RA-2x` weg,
  Schleuse-Notiz gesetzt.

### Open WebUI

`eam_qea_analyzer_openwebui.py` mit `11-mit-steka.qea`:

- `analyze_qea_statistics()` → 12 Pakete, 385 Elemente, 276 Konnektoren,
  3.154 Objekt-Tags, 62 Konnektor-Tags.
- `find_elements_in_qea(stereotype="ServiceSpecification")` → Trefferliste
  mit GUID, Paket und Notiz.
- Der Aufruf läuft ohne Open-WebUI-Installation; die Klasse `Tools` ist die
  Schnittstelle, die Open WebUI erwartet.

### Python-Bundle

- ZIP aus `dist/` entpackt, `pip install ./eam-ai-suite-python` in einer
  frischen venv: **`eam-ai 2.4.0`**.
- Demo aus dem Bundle:
  `eam-ai build --mdg examples/offline/mdg_admbw_auszug.xml --text examples/offline/prosa.txt --backend datei --antwort examples/offline/antwort.json`
  → **3 Elemente, 1 Beziehung, 12 Herkunfts-Tags, 0 Fehler**.
- Das Bundle ist damit ohne Netz, ohne Docker und ohne Repo-Kenntnis benutzbar.

### Container und Release

- `eam-ai-web` läuft mit `ghcr.io/mitchel85/eam-toolfamilie:v3.0.2`,
  `healthz` meldet `version 2.4.0` (Produktversion des Kerns), Port
  `<Tailscale-IP>:8080`. Rollback steht als `eam-ai-web-rollback-3.0.0`.
- Release `v2.4.1`: sieben Assets (drei HTML-Apps, ASPX, MDG-Parser,
  Open-WebUI-Tool, `SHA256SUMS`), alle `uploaded`.
- Das Quellarchiv `eam-ai-suite-python-<tag>.zip` ist ab dem nächsten Tag
  zusätzlich dabei; es enthält `examples/offline`, `rules.schema.json` und
  `mdg_parser.py` und ist mit `pip install ./eam-ai-suite-python` installierbar.
- CI und Release sind auf dem aktuellen Commit grün.

## Was der Lauf nicht behauptet

- **74,6 % sind keine 100 % semantische Deckung.** Die restlichen Sätze sind
  im Handbuch paraphrasiert oder als eigenständige Aussage nicht extrahiert.
  Wer 100 % braucht, muss die Extraktion weiter treiben; der Generator erfindet
  nichts dazu.
- **Das Handbuch ist kein Rückweg.** Es nennt Beispiele, nicht alle Elemente.
  Vollständigkeit kommt aus dem Elementverzeichnis (`roundtrip_export`) bzw.
  aus dem StEKa-Katalog, nicht aus dem Erzähltext.
- **Bilder und PDF** wurden in diesem Lauf nicht als Eingang geprüft; der
  Pfad existiert (`--bild`, `pdf_text.py`), ist aber nicht Teil dieser Abnahme.
- **Die Zahlen gelten für dieses Handbuch und dieses Modell.** Ein anderes
  Vorhaben erzeugt andere Werte; die Kette ist generisch, die Quote nicht.

## Zweiter Lauf: 55-Elemente-Modell mit StEKa (Task `t_d8473386`)

Stand 24.10.2026, 16:40 UTC. Ausgangsmodell ist das in diesem Lauf korrigierte
`05-korrigiert.qea` (55 Elemente + 1 Notiz, 3 Kanten, 1 Paket). Die vollständige
Fassung mit allen Befehlen und Hashes liegt als
`masc-roundtrip/abnahme-steka/ABNAHME-55-Elemente.md`; die Dateien selbst unter
`MASC-Roundtrip/masc-roundtrip/abnahme-steka/`.

### Standardelemente

- Katalog `StEKa Bw` (Paket 141): **296 Elemente, 273 Kanten, 10 Pakete, 3.343 Tags**,
  0 bereits vorhanden, 0 Warnungen.
- Ergänztes Modell `04-mit-steka.qea`: **351 Elemente + 1 Notiz = 352 Knoten,
  276 Kanten, 12 Pakete**, 3.085 Objekt-Tags, 62 Kanten-Tags.
- GUIDs: **296/296** Elemente, **12/12** Pakete, **273/273** Kanten; Basis **56/56**
  Zeilen und **3/3** Kanten. AAroN 15/15, `integrity_check = ok`.
- Zweiter Lauf: 0/0, **296 bereits vorhanden**, Ausgabe **byte-identisch**.
- **Befund:** `toolbox` ohne `--modell` plus `merge` ergibt nur **267 Elemente** —
  `merge` fasst 84 gleichnamige Katalogzeilen zusammen (72 `Classifications`,
  6 `Projects`, 4 `Classification NAFv4`, 2 `ArchRepoBw META`). Für Kataloge
  `toolbox --modell` verwenden.

### Viewer

- `05-viewer.html` aus dem finalen Modell: **352 Knoten, 273 von 276 Kanten,
  12 Pakete**, 144 kB, Ladezeit 0,19–0,21 s.
- Chromium 1600 × 1000: **keine `pageerror`, keine Konsolenfehler**. Filter
  `Architektur`: 56 Knoten, 3 Kanten. Suche `Raketenantrieb RA-4x`: 1 Treffer,
  Detailpanel `Class`/«System»/ID 29.
- Bilder: `05-viewer-gesamt.png`, `05-viewer-architektur.png`,
  `05-viewer-suche-ra4x.png`.

### Sprachprofil (natürlichsprachliche Änderung)

Anweisung: `Raketenantrieb RA-3x` → `Raketenantrieb RA-4x` (`deepseek-flash`).

- Vorschau: **1 Operation**, nichts geschrieben. `--apply`: **1 von 1**.
- In der Datei nachgelesen: GUID `{32D33BF8-C001-A629-BB5C-4D085699BD06}` unverändert,
  **genau eine** Namensänderung, 0 GUIDs hinzu/weg, Zähler unverändert,
  `integrity_check = ok`.
- Handbuch enthält `Raketenantrieb RA-4x` 2 ×, `RA-3x` 0 ×.

### Rückweg

- Handbuch `07-rueckweg.md`: 20.869 Zeichen, 10 Kapitel, 379 Absätze, 4 Dienste,
  **267 von 267 Bezeichnungen**, **0 Sprachverstöße**.
- Vergleich `08-vergleich.json`: **242/247 Bezeichnungen = 98,0 %**, Faktenabdeckung
  **11/67 = 16,4 %**, Kennzahlen **7/7 `ok`** (Verbindungen 276), Jaccard 0,186.
- Gegenprobe ohne StEKa (Basismodell, Stand 16:33): 45/45 = 100 %, 11/67 = 16,4 %,
  7/7 `ok`, 3 Verbindungen.
- **Befund 1:** 5 Katalognamen fehlen — `Architekturart`, `Architekturebene`,
  `Architekturtyp`, `IT-Service-Architektur`, `IT-System-Architektur` (Stereotyp
  `Standard`); der Generator filtert Herkunftswörter. Katalognamen im Anhang
  unverändert zulassen oder 98 % als katalogbedingte Ausnahme abnehmen.
- **Befund 2:** Die Faktenabdeckung bleibt bei 16,4 % — StEKa bringt keine Quellsätze
  mit; die Ursache sind knappe Notizen und 3 Kanten im Ausgangsmodell, nicht der
  Generator.

Hinweis: Dieser StEKa-Abschnitt und der Abschnitt über den ersten Lauf wurden
gemessen, während ein zweiter Lauf parallel an Notizen und Satztrennung arbeitete.
Für die Abnahme zählt der **dritte Lauf** (unten): dort sind Notizen, Satztrennung
und Sprachwächter committet, und die Quote ist mit der korrigierten Messung
gerechnet. Die älteren Werte bleiben als Verlauf stehen, nicht als Stand.

## Dritter Lauf: Extraktion mit vollständigen Notizen (Task `t_c1da22b3`)

Stand 24.10.2026, 17:00 UTC. Gemessen mit dem Stand von `main` (Commit `c7ec62b`)
gegen `01-quelle-handbuch.md` von `deepseek-flash`; Modell
`13-treue-modell.qea`, Handbuch `13-treue-handbuch.md`, Vergleich
`13-vergleich.json` (alle unter `MASC-Roundtrip/masc-roundtrip/`).

### Extraktion

- **65 Elemente**, 18 verschiedene Stereotype, 0 abstrakte und 0 Sammelbegriffe
  (`Baugruppen`, `Dienste` u. ä. in diesem Lauf nicht extrahiert).
- **65 von 65 Notizen** sind der vollständige belegte Absatz (0 Teilsatz,
  0 Paraphrase). Vorher blieb eine vom Modell wörtlich gelieferte Teilnotiz
  stehen; seit `c7ec62b` ersetzt der Kern sie durch den ganzen Absatz.
- **27 von 27 Textabsätzen** belegt, 207 Herkunfts-Tags, 0 Findings nach der
  MDG-Prüfung.
- **11 Beziehungen** aus der Modellantwort, davon **4** nach der
  MDG-Endpunktprüfung gültig. Die übrigen 7 nennt die Reparatur mit
  `forbiddenConnectorEndpoints` und entfernt sie.
- Wiederholungslauf (gleiche Quelle, gleiches Modell): 66 Elemente, 2
  Beziehungen roh, **0** nach der Prüfung. Die Beziehungsausbeute schwankt
  stark; das ist der offene Rest dieser Extraktion.

### Rückweg

- 10 Kapitel, 176 Absätze, 32.871 Zeichen, 65 von 65 Bezeichnungen,
  0 Sprachverstöße.
- **Faktenabdeckung 63/64 = 98,4 %** (`difflib`, Schwelle 72 %).
  Vorher: 13/67 = 19,4 % (alte Satztrennung; mit der korrigierten Trennung
  12/64 = 18,8 %).
- 100 % Bezeichnungen, 7/7 Kennzahlen, Jaccard 0,249.
- Der eine verbleibende Satz steht im Glossar hinter dem Begriffslabel
  (`**Belastungsobergrenzen …** — Der Weltraumstart führt das Fahrzeug in den
  Orbit.`). Die Wortfolge ist vorhanden; das Label davor senkt die Ähnlichkeit
  unter die Schwelle. Kein Inhaltsverlust.
- Gegenprobe **ohne Notizen** (nur Struktur: Namen, Stereotype, 4 Kanten):
  **13/64 = 20,3 %**. Die Quote trägt also die vollständige Notiz, nicht die
  Struktur.

### Behobener Messfehler

`prosa_vergleich._saetze` hat den ganzen Text zu einer Zeile verflacht;
Überschriften klebten dadurch am Folgeabsatz und erzeugten Sätze, die kein
Rückweg treffen kann (`### Sensoren Die Sensoren dienen …`). Jetzt wird
absatzweise getrennt, Überschriftzeilen beginnen keinen Satz; Test
`test_ueberschrift_beginnt_keinen_satz`. Die alten Werte (19,4 %, 74,6 %) sind
mit der alten Trennung gemessen; die Basis wurde für den Vergleich oben neu
gerechnet (18,8 %).

### Was das heißt

- Die **Texttreue** ist hoch: kein belegter Absatz geht verloren.
- Die **Struktur** ist dünn: 4 gültige Kanten aus 27 Absätzen; ohne die Notizen
  bleibt die Quote bei 20,3 %. Wer mehr semantische Deckung will, muss
  Beziehungen extrahieren, nicht Notizen kürzen.
- Die Beziehungsausbeute ist instabil (11 → 4, 2 → 0). Ursache: Der Prompt nennt
  bei den Konnektor-Regeln nur die abstrakten Endpunkte (`CapableElement`,
  `LocationHolder`); die Elementzeilen nennen keine Vererbung. Das Modell paart
  deshalb Kanten mit Stereotypen, deren Endpunkte die MDG-Prüfung entfernt.

## Vierter Lauf: Kanten aus eindeutigen Handlungssätzen (Task `t_6f264cca`)

Stand 24.10.2026, 18:35 UTC. Ziel war **≥ 60 % der Handlungssätze mit einer
gültigen MDG-Kante**, gemessen über zwei Läufe. Der Zähler steht in
`packages/core/kantenausbeute.py`, der Nachtrag in
`packages/core/relation_fill.py`.

### Zählregel (damit die Zahl reproduzierbar ist)

- Ein **Handlungssatz** nennt genau zwei Elementnamen (Wortgrenze, ohne
  Gattungsbegriffe wie `Baugruppen`/`Dienste`) und enthält ein Handlungsverb.
- Tabellenzeilen zählen nicht; `Es gibt …`-Definitionen zählen nicht;
  ein Semikolon trennt zwei Aussagen und wird getrennt gezählt.
- **Gedeckt** ist ein Satz, wenn eine MDG-gültige Kante Quelle und Ziel in
  genau diesem Satz nennt (Richtung egal).

### Ergebnis

| Lauf | Modell | Handlungssätze | gedeckt | Quote | Kanten gültig |
|---|---|---|---|---|---|
| 18 | `18-kanten-modell.qea` | 4 | 3 | **75,0 %** | 6/6 |
| 19 | `19-kanten-modell.qea` | 4 | 4 | **100,0 %** | 6/6 |

Beide Läufe liegen über der geforderten Schwelle. Der Nachtrag ergänzte je
Lauf zwei Kanten, die das Modell trotz eindeutigem Satz nicht geliefert hatte:
`Führungsmodul -> Battle-Management-System Weltraum` und
`Schleusentür -> Steuerungssoftware` (beide `HostedOn`). Die Kanten tragen
`source_ref`, `source_doc` und `source_confidence = 0.60`; die Herkunft ist
damit vollständig.

### Nebenwirkung und Abgrenzung

- Lauf 19 hat **31 Elemente** und im Rückweg **75,0 % Faktenabdeckung**
  (48/64), 100 % Bezeichnungen. Das ist **nicht** der Rückgang gegenüber den
  98,4 % aus dem dritten Lauf: dort waren 65 Elemente und damit deutlich mehr
  belegte Notizen im Spiel. Die Extraktion streut bei der Elementzahl; der
  Kanten-Nachtrag ändert keine Notiz und keine Elementzahl.
- Der dritte Lauf bleibt der Beleg für die **semantische Treue** (98,4 %),
  der vierte für die **Struktur** (75/100 %). Beide Zahlen gehören zu
  unterschiedlichen Modellen und werden nicht zu einer Quote verrechnet.
- Die Kanten `HostedOn` sind die erste MDG-gültige Regel für das jeweilige
  Paar; fachlich enger wäre `Control` (Führungsmodul) bzw. `Composition`
  (Schleusentür), beide sind im Regelwerk für diese Stereotypen nicht
  zulässig. Der Nachtrag nimmt keine Regel an, die die MDG ablehnt.

## Fünfter Lauf: Download-Einstieg (Release `v2.4.4`)

Ziel: Jeder Nutzer findet ohne Suchen die passende Einzeldatei. Die
Einstiegsseite wird aus denselben Metadaten erzeugt wie der Release-Katalog;
sie kann nicht von den Assets abweichen.

- **`START-HIER.html`** wird von `scripts/collect_releases.py` erzeugt:
  sieben Karten (AI Suite, QEA Analyzer, EAM Suite, MDG Parser, Open-WebUI,
  Python, Container), direkte Links auf
  `releases/latest/download/<datei>`, Dateigrößen, Drei-Schritt-Anleitung,
  Schnellwahl und Prüfsummen-Hinweis. Keine externen Ressourcen, kein JavaScript.
- **Stabile Python-ZIP** `eam-ai-suite-python.zip` neben der versionierten
  `eam-ai-suite-python-2.4.4.zip`; beide haben denselben SHA-256.
- **README** führt die sieben Direktlinks jetzt oben unter „Sofort herunterladen“.
- **Release `v2.4.4`:** **12 Assets** (9 geprüfte Dateien + README, RELEASES,
  SHA256SUMS); `sha256sum -c` im Download-Ordner: **9/9 OK**.
- **Browser-Prüfung:** 7 Karten, 0 Page-Errors, Desktop und 390-px-Mobile ohne
  horizontalen Überlauf; Schnellwahl springt auf die Karten.
- **Test:** `tests/test_collect_releases.py` prüft Kartenzahl, direkte Links,
  stabile ZIP und Einstiegsseite; Gesamtsuite **776 passed / 4 skipped**.

## Siebter Lauf: Rückbau auf die drei Altwerkzeuge

Die drei HTML-Dateien sind keine Varianten mehr. Jede wird aus ihrem eigenen
Altstand gebaut; `packages/ui` ist entfernt. Die Auslieferungen unterscheiden
sich in Quelle, Fassung, Größe und Funktionsmarkern:

| Werkzeug | Altquelle | Fassung | HTML | Marker |
|---|---|---|---|---|
| EAM AI Suite | `architektur-mate-ki` | 9.1 | 3.533.445 B | KI, Bearbeiten, Merge |
| EAM QEA Analyzer | `admbw-qea-analyzer` | 4.0 | 306.026 B | nur Analyse; kein Edit/KI |
| EAM Suite | `admbw-qea-editor` | 8.4 | 1.369.379 B | Edit, Merge; kein KI |
| EAM MDG Parser | `eam-mdg-parser` | alt | 31.606 B | Upload, fünf Ansichten, sechs Exporte |

Gebaut wird mit `scripts/build_legacy_app.py`: Das Skript führt den jeweiligen
Alt-Build aus, prüft die JavaScript-Blöcke mit `node --check` und kopiert die
Ergebnisse unter den Auslieferungsnamen. `tests/test_html_artifacts.py` prüft
Titel, Version, Größe, Funktionsmarker, ASPX-BOM und Determinismus; die drei
Dateien müssen verschiedene Hashes und Größen haben. `tests/test_mdg_web.py`
hält den MDG-Parser byte-gleich.

Messung mit `Musterarchitektur_MASC.qea`: AI Suite und Suite laden **226 Pakete,
265 Sichten, 1.655 Elemente, 1.747 Beziehungen** ohne Page-Errors; der Analyzer
lädt dieselbe Datei mit seinen fünf Analyse-Reitern. Der Graph meldet
**12 Zellen, 7 Artefakte, 0 Befunde**; die Gesamtsuite läuft mit
**786 passed / 7 skipped** nach dem Einsammeln (frischer Klon; mit gesetztem
`MASC_QEA_PATH` sind es 789/4). Ohne `dist/` werden die zwei Graphprüfungen
übersprungen, weil die gebauten Artefakte fehlen.

## Achter Lauf: Abhängigkeiten als eine Kette

Die Abhängigkeiten sind jetzt nicht nur beschrieben, sondern in vier Stufen
maschinell geführt:

| Stufe | Quelle | Ziel | Wächter |
|---|---|---|---|
| Regeln | `packages/rules/NAFv4-ADMBw-MDG-2026.05.xml` | `knowledge/admbw-*` | `propagate.py --check` |
| Wissen | `knowledge/*` | `apps/admbw-*/` per Symlink | `verify_graph.py` |
| Browser | `vendor/*` | `apps/html-*/vendor/` | `sync_vendor.py --check` |
| Auslieferung | `apps/*/dist` | `dist/` | `collect_releases.py` |

`vendor/` ist die zwölfte Zelle (`@mitchel85/eam-vendor`); die drei HTML-Apps
deklarieren sie als `devDependencies`. Der MDG-Browser-Parser bleibt ohne
Kante zum Python-Regelwerk, weil er die XML selbst im Browser liest.

`scripts/propagate.py --check` prüft Wissensbasis, Vendor-Kopien, Manifeste
und die erzeugte Karte `docs/ABHAENGIGKEITEN.md`. `--write` reicht Quellen
weiter, `--build` baut danach die drei HTML-Werkzeuge und den MDG-Parser,
`--release` sammelt `dist/`. `scripts/impact.py --git` zeigt vorab, welche
Zellen eine Änderung berührt und welcher Befehl fällig ist. `build_all.py`
ruft `propagate.py --write` vor dem Bau auf; `build_legacy_app.py` spiegelt
die Vendor-Dateien vor jedem Alt-Build.

Beleg: **12 Zellen, 7 Artefakte, 0 Befunde**, **786 passed / 7 skipped**
(frischer Klon; 789/4 mit `MASC_QEA_PATH`), `propagate.py --check` ohne Befund.
