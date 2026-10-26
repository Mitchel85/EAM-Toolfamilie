# Offline-Bundle: bauen, pruefen, installieren

Ziel: ein installierbares Artefakt fuer Bw-Umgebungen **ohne Netz**, **ohne
Docker** und ohne Fremdpakete. Der Kern haengt nur an der Standardbibliothek
(inklusive `sqlite3`).

## Mindeststand

| Punkt | Wert |
|---|---|
| Python | 3.11 oder neuer (getestet mit 3.12) |
| Betriebssystem | Linux und Windows 10/11 (Startskripte fuer beide) |
| Container | nicht noetig, nicht vorgesehen |
| Netzwerk | nicht noetig zum Bauen, Installieren und fuer `--backend datei` |
| Rechte | keine Adminrechte; die virtuelle Umgebung liegt im Bundle-Ordner |
| Laufzeitabhaengigkeiten | keine (`dependencies = []`) |

## Bauen

```bash
python3 tools/build_bundle.py --out dist/offline
```

Ergebnis:

```text
dist/offline/
  eam-ai-3.1.1-offline/          # entpacktes Bundle
  eam-ai-2.4.0-offline.zip        # universell, auch Windows
  eam-ai-2.4.0-offline.tar.gz     # Linux, mit Ausfuehrungsrechten
  eam-ai-2.4.0-offline.zip.sha256
  eam-ai-2.4.0-offline.tar.gz.sha256
```

Das Wheel allein baut auch `python3 -m pip wheel . --no-deps -w dist/wheel`;
das in-tree Backend (`backend-path = ["."]`) wird dabei ohne Netz aufgerufen.

### Reproduzierbarkeit

- feste ZIP-Zeitstempel (1980-01-01), sortierte Eintraege, feste Rechte,
  keine Kompression,
- keine Zeitangaben, Build-IDs oder Zufallswerte in Wheel, Bundle oder
  `BUILD-INFO.json`,
- Quellstand-Hashes und `build_id` in `BUILD-INFO.json`,
- `SHA256SUMS.txt` ueber jede Datei des Bundles.

Zweimal bauen ergibt byte-identische Archive. Auch ein Neubau aus dem
mitgelieferten `source/`-Ordner ist byte-identisch:

```bash
python3 eam-ai-3.1.1-offline/source/tools/build_bundle.py --out /tmp/neubau
sha256sum eam-ai-2.4.0-offline.zip /tmp/neubau/eam-ai-2.4.0-offline.zip
```

Die Definition of Done laesst sich mit dem mitgelieferten Pruefer wiederholen
(POSIX; legt ein frisches `.venv` an, installiert offline, prueft Version und
Beispiel):

```bash
python3 packages/core/tools/verify_bundle.py dist/offline/eam-ai-2.4.0-offline.tar.gz
```

Das gilt fuer den Build selbst. Die erzeugte `.qea` ist bei gleichem Input und
**gleichem Interpreter** byte-identisch; SQLite schreibt sein Dateiformat
bibliotheksabhaengig (Python 3.12 mit SQLite 3.45 und Python 3.14 mit SQLite
3.53 liefern dieselben Daten und GUIDs, aber unterschiedliche Datei-Bytes).
Fuer Abgaben in Bw-Umgebungen deshalb den Interpreter festhalten.

## Bundle-Inhalt

| Pfad | Inhalt |
|---|---|
| `eam_ai-<version>-py3-none-any.whl` | installierbares Paket, Entry-Point `eam-ai` |
| `install.sh`, `install.cmd` | virtuelle Umgebung anlegen, Wheel offline installieren |
| `eam-ai.sh`, `eam-ai.cmd` | Aufruf von `eam-ai` aus der lokalen Umgebung |
| `run-example.sh`, `run-example.cmd` | Beispiel-Lauf mit `--backend datei` |
| `example/` | MDG-Auszug, Prosa, Antwortdatei (synthetisch) |
| `vendor/README.txt` | Begruendung: keine Fremdpakete zu vendorn |
| `source/` | Quellstand zum Nachbau und Pruefen |
| `BUILD-INFO.json` | Version, Python-Mindeststand, Hash des Wheels, `build_id` |
| `SHA256SUMS.txt` | SHA-256 jeder Bundle-Datei |
| `CHANGELOG.md` | Versionshistorie |
| `README-OFFLINE.md` | Kurzanleitung im Bundle |

## Installieren (offline)

Linux:

```bash
tar xzf eam-ai-2.4.0-offline.tar.gz
cd eam-ai-2.4.0-offline
./install.sh
eam-ai --version
./run-example.sh
```

Windows (Eingabeaufforderung, nicht PowerShell noetig):

```bat
install.cmd
eam-ai.cmd --version
run-example.cmd
```

`install.sh`/`install.cmd` rufen ausschliesslich
`python -m pip install --no-index --no-deps <wheel>` auf. Es wird nichts
nachgeladen; fehlt Python 3.11+, brechen beide Skripte mit Exit 1 und einer
klaren Meldung ab.

## Integritaet pruefen

```bash
sha256sum -c SHA256SUMS.txt          # Linux, im Bundle-Ordner
certutil -hashfile <datei> SHA256    # Windows
```

Der Hash des Gesamtarchivs steht in der `.sha256`-Datei daneben (ein Archiv
kann seinen eigenen Hash nicht enthalten). Im Bundle selbst stehen die Hashes
in `SHA256SUMS.txt` und `BUILD-INFO.json`.

## Beispiel-Lauf (Definition of Done)

```bash
eam-ai build \
  --mdg example/mdg_admbw_auszug.xml \
  --text example/prosa.txt \
  --out out/beispiel.qea \
  --backend datei --antwort example/antwort.json \
  --findings out/findings.json --quellen out/quellen.json
```

Erwartung: Exit 0, `3 Elemente, 1 Beziehungen`, `findings.json` enthaelt `[]`,
`quellen.json` drei Belege. Zwei Laeufe liefern dieselbe `sha256` fuer die
`.qea` (kein Zeitstempel, keine GUID-Berechnung im Writer).

## KI und kein KI

- Ohne KI: `eam-ai build ... --backend datei --antwort <datei>` oder der
  Regelpfad `python -m eam_suite` (im Wheel enthalten).
- Mit KI: `--backend openai` oder `--backend ollama`. Das ist der einzige
  Pfad, der Netzzugriff hat; das Bundle enthaelt kein Modell.

## Versionierung

`eam_ai.__version__` ist die fuehrende Quelle. `pyproject.toml` und
`CHANGELOG.md` muessen denselben Wert tragen; `tests/test_packaging.py` bricht
sonst laut ab. Eine sdist wird bewusst nicht erzeugt -- ausgeliefert wird das
Wheel plus Quellstand im Bundle.
