# Herkunft der HTML-Auslieferungen

Stand 24.10.2026. Jede HTML-Datei wird aus ihrem eigenen Altstand gebaut.
`app.json` im App-Ordner ist die maschinenlesbare Fassung dieser Tabelle.

| App | Alt-Repo | Commit | Anpassung in der Kopie | Ausgabe |
|---|---|---|---|---|
| EAM AI Suite 9.1 | `Mitchel85/EAM-AI-Suite` (`architektur-mate-ki`) | `897058d` | ADMBW_DATA aus `knowledge/regelwerk.json` | 3.633.753 B |
| EAM QEA Analyzer 4.0 | `Mitchel85/EAM-QEA-Analyzer` (`admbw-qea-analyzer`) | `9967a89` | HTML-Fassung am 05.11.2026 entfernt (ohne KI-Anbindung redundant); Analyse läuft als Open-WebUI-Tool/MCP (`apps/mcp`, abgeleitet von `schmitze87/AAroN`) | — |
| EAM Suite 8.6 | `Mitchel85/EAM-Suite` (`admbw-qea-editor`) | `3407bc0` | Titel/H1 ohne „EXPERIMENTELL“; Befunde (`«Issue»`), Standardelemente-Import und ADMBW_DATA aus dem Regelwerk | 1.506.594 B |
| Sichten-Archiv 1.0 | `Mitchel85/EAM-Toolfamilie` | `1ef12b3` | Einzeldatei-Werkzeug im Monorepo | 950.917 B |
| ADMBw Extraktor | `Mitchel85/EAM-ADMBw-MDG-Parser` (`eam-mdg-parser`) | `8d9f170` (Altstand) | Master-Prompt eingebettet, 5 Reiter inkl. Stereotyp-Tags | 47.886 B |
| BPMN Studio 3.14.0 | `Mitchel85/eam-platform` | `eigenbau` | Eigenentwicklung im Monorepo mit `bpmn-js 18.31.1` | 2.680.528 B |

## Bereinigung für die Veröffentlichung

Die früheren Alt-Repos sind archiviert und privat. Interne Verweise wurden aus
dem Editor-Quellstand und dem MASC-Fixture entfernt. Der Editor lädt MASC nur
noch aus der Datei neben der HTML; im Fixture wurde der Verweis durch eine
gleich lange Platzhalter-URL ersetzt. Die SQLite-Struktur und der Modellumfang
bleiben unverändert. MASC ist als Beispieldatei bewusst enthalten.

**Autorenangaben (04.11.2026):** In `t_object.Author` und `t_diagram.Author`
standen die Bearbeiter des Modells — Klarnamen, Dienststellen- und Firmenzusätze
sowie zwei numerische Kennungen (1.654 Objektzeilen, 265 Sichtzeilen, 34
verschiedene Werte). Diese Felder sind auf den Neutralwert `MASC` gesetzt.
Struktur, GUIDs, Namen, Tags und der Modellumfang sind unverändert. Ein reines
`UPDATE` genügt dafür nicht: Die alten Werte bleiben in freigegebenen
SQLite-Seiten lesbar. Die Datei wird deshalb anschließend per `VACUUM` neu
geschrieben (12.414.976 -> 10.600.448 B, freie Seiten 138 -> 0). Die
Neutralisierung ist wiederholbar über
`python3 scripts/neutralize_model_authors.py <modell.qea>`; `scripts/check_no_model_leak.py`
bricht ab, wenn erneut ein Autorenwert auftaucht. Die Prüfsumme in
`packages/core/ci/fixtures_manifest.json` wurde entsprechend aktualisiert.

## Gebaute Hashes

| Datei | SHA-256 |
|---|---|
| `EAM-AI-Suite.html` | `f67531574c26cdad57b81d7b9e30376df93e803b39e2e37c4fed322c3a7656e3` |
| `EAM-Suite.html` | `0368b0f63a2eff98f53c45b5d276e4e504e842f906ab8dff2abc07972e962136` |
| `Sichten-Archiv.html` | `4b04ec6d08a2e48ec7c4c64fce1f9bf66934e081d65076e21befa25aeac00c79` |
| `ADMBw-Extraktor.html` | `00ed6a39b69812091c7b19c09de4b7c6fa0674dd91f538f222383c667e78ada8` |
| `BPMN-Studio.html` | `a0b15d90c3551bedbd7b9fb12c9e242bf7ae416552f8c7cc218c373c5cf735a0` |

Die Hashes sind reproduzierbar: `python3 scripts/build_legacy_app.py <app>`
zweimal ausführen ergibt dieselben Bytes; `tests/test_html_artifacts.py`
prüft das. Die `.aspx`-Dateien sind dieselben Bytes mit UTF-8-BOM.

## Grenzen der Eigenständigkeit

Die drei Altstände sind historisch verwandt: Reader-, Graph- und Pfadmodule sind
teilweise nahezu gleich. Das ist Absicht — übernommen wird der bewährte
Altstand, nicht eine neue gemeinsame Bibliothek. Es gibt **keinen gemeinsamen
Build**, keine gemeinsame UI-Konfiguration und keine Querverweise zwischen den
Apps. `vendor/` liegt bewusst pro App, damit jede Build-Kette allein läuft.
Änderungen an einem historisch geteilten Modul müssen in der jeweiligen
App-Quelle erfolgen; ein automatischer Drift-Abgleich existiert nicht.
