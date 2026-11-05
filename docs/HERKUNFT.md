# Herkunft der HTML-Auslieferungen

Stand 24.10.2026. Jede HTML-Datei wird aus ihrem eigenen Altstand gebaut.
`app.json` im App-Ordner ist die maschinenlesbare Fassung dieser Tabelle.

| App | Alt-Repo | Commit | Anpassung in der Kopie | Ausgabe |
|---|---|---|---|---|
| EAM AI Suite 9.1 | `Mitchel85/EAM-AI-Suite` (`architektur-mate-ki`) | `897058d` | keine | 3.533.445 B |
| EAM QEA Analyzer 4.0 | `Mitchel85/EAM-QEA-Analyzer` (`admbw-qea-analyzer`) | `9967a89` | HTML-Fassung am 05.11.2026 entfernt (ohne KI-Anbindung redundant); Analyse läuft als Open-WebUI-Tool/MCP (`apps/mcp`, abgeleitet von `schmitze87/AAroN`) | — |
| EAM Suite 8.4 | `Mitchel85/EAM-Suite` (`admbw-qea-editor`) | `3407bc0` | Titel/H1 ohne den Altvermerk „EXPERIMENTELL“; Funktion unverändert | 1.369.379 B |
| ADMBw Extraktor | `Mitchel85/EAM-ADMBw-MDG-Parser` (`eam-mdg-parser`) | `8d9f170` (Altstand) | keine; `index.html` byte-gleich | 31.606 B |

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
| `EAM-AI-Suite.html` | `a28afedac3ddb213eab0d90d2c08f7d325a936d987fff0dab28f58a74f5a6718` |
| `EAM-Suite.html` | `6030479f89b9ee9d182e0d24a31700d1d0c28bd044755ba1328cad94f270a656` |
| `ADMBw-Extraktor.html` | `7021ce9370c1b2901d96a28c1993f9b156adc6721fd2ce933e6a48c295fddc7e` |

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
