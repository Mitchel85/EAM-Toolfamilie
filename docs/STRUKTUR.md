# Struktur: ein Repo, verbundene Zellen, alles auffindbar

Stand 24.10.2026. Dieses Dokument beschreibt die drei Schichten, die zusammen
dafür sorgen, dass jeder Nutzer jede Auslieferung findet, auswählt und
herunterlädt — und dass eine Änderung an einer Stelle nicht still an einer
anderen vorbeiläuft.

## 1. Die Zelle — jede Auslieferung als eigenes Paket im selben Repo

Jeder Ordner unter `apps/` und `packages/` trägt eine `package.json`. Die
Manifeste beschreiben die Zellen und ihre Solllkanten:

```
@mitchel85/eam-rules   packages/rules
@mitchel85/eam-core    packages/core
@mitchel85/eam-vendor  vendor
eam-ai-suite           apps/html-suite       (eigener Quellstand: architektur-mate-ki)
eam-qea-analyzer       apps/html-analyzer    (eigener Quellstand: admbw-qea-analyzer)
eam-suite              apps/html-editor      (eigener Quellstand: admbw-qea-editor)
eam-mdg-web            apps/mdg-web
eam-mcp                apps/mcp
eam-admbw-extractor    apps/admbw-extractor
eam-admbw-batch        apps/admbw-batch
eam-admbw-script-maker apps/admbw-script-maker
eam-ai-cli             apps/cli
```

Die drei HTML-Zellen sind **keine Varianten eines gemeinsamen UI-Kerns**. Jede
bringt ihren eigenen `src/`- und `vendor/`-Stand aus dem jeweiligen Alt-Repo
mit. Laufzeit sind sie Wurzeln; ihre einzige deklarierte Kante ist die
Build-Zeit-Abhängigkeit `@mitchel85/eam-vendor`. Die Prompt-Werkzeuge und der
Python-Kern hängen an `packages/rules`, CLI und MCP an `packages/core`. Der
MDG-Browser-Parser `apps/mdg-web` ist eigenständig: er parst die hochgeladene
XML im Browser und hat keine Kante zum Python-Regelwerk.

**Der native GitHub-Dependency-Graph ist hier nicht maßgeblich.** Der Graph
löst die internen Namen `@mitchel85/...` nicht auf, weil sie nicht auf npm
veröffentlicht sind und kein Workspace-/Lockfile-Verbund existiert. Die `package.json`-Dateien
sind deshalb die strukturelle Landkarte im Repo, nicht die Quelle der
GitHub-„Used by"-Ansicht.

Maßgeblich ist der eigene Auslieferungsgraph: `scripts/verify_graph.py` liest
die `dependencies`, `devDependencies` und `overrides`, prüft **12 Zellen, 7 Artefakte** und die
Dateikanten und schreibt `dist/GRAPH.md`. Die Solllkanten sind
`rules` ← `core` ← `cli`/`mcp`, `rules` ← `admbw-*` sowie
`vendor` ← `html-*` (Build-Zeit, `devDependencies`). Der MDG-Browser-Parser
`apps/mdg-web` ist eigenständig und hat keine Laufzeitkante zum Regelwerk.
Die HTML-Dateien sind eigenständige Werkzeuge, keine gemeinsame Codebasis.

## 2. Die Prüfkette — eine Regeländerung zieht alles mit

```bash
python3 scripts/propagate.py --check         # Wissensbasis, Vendor, Manifeste, Karte
python3 scripts/build_knowledge.py --mdg packages/rules/NAFv4-ADMBw-MDG-2026.05.xml \
        --check --check-provenance      # Wissensbasis gegen MDG + Parser
python3 scripts/build_legacy_app.py apps/html-suite
python3 scripts/build_legacy_app.py apps/html-analyzer
python3 scripts/build_legacy_app.py apps/html-editor
python3 apps/mdg-web/build.py
python3 scripts/verify_graph.py            # jeder Knoten gemessen: Datei, Größe, SHA-256
python3 -m pytest -q                       # Kern und HTML-Marker
python apps/admbw-batch/checks/verify.py    # 40/40
python apps/admbw-extractor/checks/verify.py # 53/53
node apps/admbw-script-maker/tests/run_tests.js
python3 scripts/build_all.py                # HTML, Wheel, Offline-Bundle, SHA256SUMS
```

`scripts/propagate.py` ist der eine Weg, auf dem eine Quelländerung an die
abhängigen Stellen gelangt: MDG → Wissensbasis, `vendor/` → App-Kopien,
Manifeste und die Karte `docs/ABHAENGIGKEITEN.md`. `--check` ist der
CI-Wächter; `--all` reicht weiter, baut und sammelt ein. `scripts/impact.py`
zeigt vorab, welche Zellen eine Änderung berührt.

`scripts/verify_graph.py` ist die Instanz, die „eine Änderung zieht alles mit"
**nachweist** statt sie zu versprechen: es läuft den Graphen von den Blättern
(rules) zu den Auslieferungen ab und prüft, dass jedes erwartete Artefakt
existiert, dass die Wissensbasis-Symlinks in den Apps noch auf `knowledge/`
zeigen und dass jedes Artefakt in `dist/SHA256SUMS` steht. Ein Knoten gilt nur
als verbunden, wenn sein Verbraucher ihn wirklich liest.

## 3. Die Auslieferung — jeder Nutzer kommt direkt an seine Datei

`scripts/collect_releases.py` legt die Auslieferungen flach in `dist/` und
schreibt Katalog, `SHA256SUMS` und die Einstiegsseite. `scripts/build_all.py`
ist der lokale Gesamtbau (HTML, Wheel, Offline-Bundle); sein `offline/`- und
`wheel/`-Ergebnis ist **nicht** Teil des GitHub-Releases.

| Datei | Was es ist | Einstieg für |
|---|---|---|
| `EAM-AI-Suite.html` | Einzeldatei, offline lauffähig | Sachbearbeiter, SharePoint |
| `EAM-Suite.html` | Einzeldatei | Lesen, Prüfen, Bearbeiten, Verschmelzen |
| `EAM-MDG-Parser.html` | Browser-Werkzeug für die MDG-XML | Regelwerk prüfen |
| `eam-mdg-parser.py` | Python-Variante, dieselbe Datei wie im ZIP | Kommandozeile |
| `eam-ai-suite-python.zip` | Quellstand des Python-Kerns | `pip install ./eam-ai-suite-python` ohne Docker |
| `eam_qea_analyzer_openwebui.py` | Open-WebUI-Tool (eine Datei) | Open WebUI |
| `eam-qea-mcp-server.py` | MCP-Wrapper für dieselben Abfragen | Open WebUI, Claude Desktop, VS Code |
| Container `ghcr.io/mitchel85/eam-toolfamilie` | Webdienst + CLI | Rechner mit Docker |

Jede Zeile ist im README verlinkt **und** als GitHub-Release-Asset vorhanden.
Die Release-Seite ist damit die Auffindbarkeitsfläche: kein Klonen, kein
Bauen — herunterladen, öffnen.

## 4. Was ein Nutzer nicht braucht

- Kein Python, um die HTML-Dateien zu öffnen (Doppelklick genügt).
- Kein Netz für `EAM-AI-Suite.html` und `EAM-Suite.html`.
- Kein Docker für die HTML-Dateien; das Offline-Bundle entsteht lokal mit
  `scripts/build_all.py` und ist kein Release-Asset.
- GitHub-Zugang: Für die Release-Downloads nicht nötig; der Quellcode ist öffentlich.

## 5. Grenzen

- Ein Monorepo ist kein Ersatz für getrennte Repos, wenn **verschiedene
  Personen** verschiedene Freigaben brauchen; hier ist es ein Repo, weil die
  Auslieferungen dieselbe Wissensbasis teilen.
- Der native GitHub-Abhängigkeitsgraph löst die internen Paketnamen nicht auf. Die fachlichen und Datei-Kanten
  prüft ausschließlich `verify_graph.py`; `dist/GRAPH.md` ist die sichtbare
  Tabelle.
- `dist/` ist erzeugt. Wer dort etwas ändert, verliert es beim nächsten Lauf.
