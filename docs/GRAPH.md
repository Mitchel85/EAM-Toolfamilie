# Graph: ArchiMate-Modelle abfragen

`packages/core/graph.py` legt ein Modell als Graph in SQLite ab — **ohne Neo4j**,
ohne Server, ohne Zusatzpaket. Danach sind die zwei Fragen, die im Alltag
wirklich gestellt werden, eine Abfrage statt einer Bastelstunde:

- *Welche Elemente hängen an dieser Fähigkeit?*
- *Welche Kanten sind ungültig?*

Der Graph ist eine **Momentaufnahme des Modells**, kein zweiter Writer:

- Er bildet das Modell ab, **wie es ist**. Ungültige Kanten werden gemeldet,
  nicht repariert. Was der Writer beim Export tut (invertieren, umhängen,
  verwerfen) ist eine Entscheidung am Ausgang; im Graphen wäre es ein
  verfälschtes Bild der Vorlage.
- Er ist **vollständiger als der Export**: jedes fachliche Element und jedes
  Paket ist ein Knoten. Der Writer lässt Elemente ohne Abbildungsregel weg;
  der Graph behält sie mit leerem `archimate_typ`, damit keine Lücke unsichtbar
  wird.

## 1. Laden

Drei Eingabeformate, ein Ergebnis — die Kennungen sind in allen Fällen
dieselben (GUID bzw. `identifier` aus dem Austauschformat):

```bash
# .qea (EA), ArchiMate-3.2-XML oder IR-JSON
python3 packages/core/graph.py laden --in Musterarchitektur_MASC.qea --db masc.graph.sqlite
python3 packages/core/graph.py laden --in modell.xml --db modell.graph.sqlite --report bericht.json
python3 packages/core/graph.py laden --in ir.json --db ir.graph.sqlite --ersetzt
```

| Schalter | Wirkung |
|---|---|
| `--db` | Zieldatei (Default `graph.sqlite`) |
| `--ersetzt` | vorhandene Datenbank überschreiben — ohne diesen Schalter bricht der Lader ab |
| `--strict` | Warnungen der Reader (`.qea`/XML) als Fehler behandeln |
| `--report` | Ladebericht als JSON |
| `--json` | Bericht auf der Standardausgabe |

Der Ladebericht nennt jede Näherung, es gibt keinen stillen Verlust:

```
Geladen: Musterarchitektur_MASC.qea [qea] sha256 d64506532debac09...
  Knoten:  1016 Elemente, 226 Pakete
  Kanten:  1733 (1644 gueltig, 89 ungueltig)
  Befunde: 292 (K01 51, K02 2, K04 38, K05 28, K06 73, K09 38, K10 62)
  Schwere: fehler 91, hinweis 100, warnung 101
  Uebersprungen: darstellung 265, fachmechanik 27, notelink 14
  Auf Traeger zusammengefasst: 122
```

Dieselbe Ausgabe als Python:

```python
from graph import lade

bericht = lade("Musterarchitektur_MASC.qea", "masc.graph.sqlite")
print(bericht.knoten_elemente, bericht.kanten, bericht.befunde_je_regel)
```

**Determinismus.** Zwei Läufe auf derselben Datei liefern dieselben Zeilen und
dieselben Kennungen; die SQLite-Datei selbst ist (wie bei `qea_writer`) nicht
byte-identisch. Zeitstempel schreibt der Graph nicht — auch nicht in `meta`.

## 2. Das Schema

Fünf Tabellen, vier Sichten. Die Namen sind deutsch, weil sie in Abfragen
stehen, die Menschen lesen.

```
knoten                kanten                     befunde
──────                ──────                     ───────
kennung  TEXT PK      kennung    TEXT PK         id        INTEGER PK
art      element|paket position   INTEGER        kante     -> kanten.kennung
name     TEXT         typ        TEXT (ArchiMate) regel    K01..K10
typ      TEXT (Quelle)quell_typ  TEXT (EA-Typ)    schwere  fehler|warnung|hinweis
archimate_typ TEXT    stereotyp  TEXT             nachricht TEXT
stereotyp TEXT        quelle     -> knoten.kennung
paket    TEXT         ziel       -> knoten.kennung eigenschaften
dokumentation TEXT    quelle_ref TEXT (roh)       ─────────────
status   TEXT         ziel_ref   TEXT (roh)       kennung   -> knoten.kennung
                      name, dokumentation         schluessel, wert
                      gueltig    0|1              (PK: kennung+schluessel)
```

- **`knoten.typ`** ist der Typ im Quellmodell (EA-Metaklasse, etwa `Class`),
  **`knoten.archimate_typ`** der aufgelöste ArchiMate-3.2-Typ (etwa
  `Capability`). Die Matrixprüfung rechnet mit dem zweiten.
- **`kanten.typ`** ist der ArchiMate-Beziehungstyp (`Realization`, `Serving`, …),
  **`kanten.quell_typ`** der Typ im Quellmodell (`Realisation`, `Dependency`, …).
- **`kanten.quelle_ref`/`ziel_ref`** bleiben stehen, auch wenn ein Endpunkt
  nicht auflösbar ist. `quelle`/`ziel` sind dann `NULL`.
- **`kanten.gueltig`** ist genau dann `1`, wenn kein Befund der Schwere
  `fehler` vorliegt. Warnungen und Hinweise lassen die Kante gültig.
- **Pakete** sind Knoten mit `art='paket'` und `archimate_typ='Grouping'`
  (oder dem Typ ihres Stereotyps, etwa `Product` bei
  `ArchitecturalDescription`). Ein Paketknoten ist ein Container, kein Element
  des Austauschformats.

### Sichten

| Sicht | Inhalt |
|---|---|
| `v_kanten` | jede Kante mit beiden Enden (Name, ArchiMate-Typ), auch offene |
| `v_nachbarschaft` | jede Kante aus Sicht **beider** Enden (`knoten`, `nachbar`, `richtung` `aus`/`ein`) |
| `v_befunde` | alle Befunde mit beiden Kantenenden |
| `v_ungueltige_kanten` | nur die Befunde der Schwere `fehler` |

### Kennungen

Die Kennung ist die Identität aus dem Austauschformat (`identifier`), sonst die
Ableitung aus der GUID (`archimate_writer.kennung`: `id-<guid>`, ohne GUID ein
SHA-256 über die IR-Referenz). Kanten im `.qea`-Format tragen keine GUID; ihre
Kennung ist ein stabiler Hash aus `quelle>ziel>typ`, bei echten Dubletten mit
laufender Nummer (`-2`, `-3`). Pakete bekommen `id-<sha256 von "paket:"+Pfad>`.

## 3. Welche Elemente hängen an einer Fähigkeit?

### Per Kommandozeile

```bash
python3 packages/core/graph.py faehigkeit \
    --db masc.graph.sqlite --name "Informationsüberlegenheit sicherstellen" --tiefe 2
```

```
Faehigkeit: Informationsüberlegenheit sicherstellen  [id-ee9c9f17-…]  Capability, Paket …/EnduringTasks
  1  <- Serving        Capability           Weltraumaufklärung
  2  -> Association    Grouping             Erdnaher Orbit
  2  <- Realization    BusinessProcess      Geoinformationswesen sicherstellen
  2  <- Realization    ApplicationService   Spacecraft Information Service Bw
  ...
```

`<-` heißt: die Kante zeigt **auf** die Fähigkeit (der Nachbar erbringt,
realisiert oder spezialisiert sie). `->` heißt: die Kante geht von der Fähigkeit
aus. `--richtung aus|ein|beide` schränkt das ein, `--tiefe N` die Schrittzahl,
`--json` liefert Maschinenlesbares.

### Per Python

```python
import graph

con = graph.oeffne("masc.graph.sqlite")
start, umfeld = graph.elemente_an_faehigkeit(
    con, "Informationsüberlegenheit sicherstellen", tiefe=2
)
for zeile in umfeld:
    print(zeile["tiefe"], zeile["richtung"], zeile["beziehung"],
          zeile["archimate_typ"], zeile["name"])
con.close()
```

`elemente_an_faehigkeit` sucht über Kennung, Name oder Namensteil, verlangt
einen Knoten mit `archimate_typ='Capability'` und rät bei mehreren Treffern
nicht: dann kommt `Mehrdeutig` mit der Kandidatenliste (die CLI endet mit
Rückgabewert 2). Für beliebige Startknoten heißt die Funktion `umfeld(con, kennung, tiefe=…, richtung=…)`.

### Per SQL (rekursiv, ohne Python)

```sql
WITH RECURSIVE umfeld(kennung, tiefe) AS (
    SELECT kennung, 0 FROM knoten
     WHERE archimate_typ = 'Capability' AND name = :name
    UNION
    SELECT n.nachbar, u.tiefe + 1
      FROM umfeld u JOIN v_nachbarschaft n ON n.knoten = u.kennung
     WHERE u.tiefe < :tiefe
)
SELECT w.name, w.archimate_typ, MIN(u.tiefe) AS tiefe
  FROM umfeld u JOIN knoten w ON w.kennung = u.kennung
 GROUP BY w.kennung
 ORDER BY tiefe, w.name;
```

`v_nachbarschaft` ist die Voraussetzung dafür: es gibt je Kante zwei Zeilen
(hin und zurück), deshalb findet die Suche auch Kanten, die auf die Fähigkeit
zeigen. Dieselbe Abfrage steht als Test in `tests/core/test_graph.py` — die
Doku kann nicht verrotten.

### Verwandt: der Weg zwischen zwei Elementen

```bash
python3 packages/core/graph.py pfad --db masc.graph.sqlite \
    --von "Spacecraft Information Service Bw" --nach "Weltraumaufklärung"
```

## 4. Welche Kanten sind ungültig?

```bash
python3 packages/core/graph.py ungueltig --db masc.graph.sqlite          # nur Fehler
python3 packages/core/graph.py befunde   --db masc.graph.sqlite          # alle Befunde
python3 packages/core/graph.py befunde   --db masc.graph.sqlite --schwere hinweis --regel K09
```

```python
from graph import oeffne, ungueltige_kanten, befunde

con = oeffne("masc.graph.sqlite")
for befund in ungueltige_kanten(con):            # Schwere "fehler"
    print(befund["regel"], befund["position"], befund["nachricht"])
warnungen = befunde(con, schwere="warnung")
```

```sql
-- Die Pflichtabfrage in einem Satz
SELECT regel, schwere, position, quell_name, beziehung, ziel_name, nachricht
  FROM v_ungueltige_kanten
 ORDER BY regel, position;
```

### Die Regeln

| Code | Regel | Schwere | Bedeutung |
|---|---|---|---|
| K01 | `endpunkt_fehlt` | Fehler | Quelle oder Ziel verweist auf keinen Knoten des Modells |
| K02 | `selbstkante` | Fehler | Quelle und Ziel sind dasselbe Element |
| K03 | `beziehungstyp_unbekannt` | Fehler | kein ArchiMate-3.2-Beziehungstyp |
| K04 | `matrix_verstoss` | Fehler | Typpaar lässt diese Beziehung laut ArchiMate 3.2 nicht zu |
| K05 | `richtung_verkehrt` | Warnung | nur die Gegenrichtung ist zulässig (der Writer invertiert beim Export) |
| K06 | `duplikat` | Warnung | dieselbe Beziehung steht mehrfach im Modell |
| K07 | `nicht_pruefbar` | Warnung | ein Endpunkt hat keinen ArchiMate-Typ — die Matrix ist nicht anwendbar |
| K08 | `mehrdeutiger_endpunkt` | Warnung | gleichnamige Elemente im selben Paket; die erste Position wurde gewählt |
| K09 | `verdichtung` | Hinweis | zwei Modellkanten fallen nach der Träger-Zusammenfassung auf eine ArchiMate-Kante |
| K10 | `selbstkante_traeger` | Hinweis | beide Enden liegen nach der Zusammenfassung auf demselben Träger |

Geprüft wird gegen die **ArchiMate-3.2-Beziehungsmatrix**
(`packages/core/archimate/relationships.xml`, dieselbe Quelle wie der Writer).
`Association` gilt dort für 3841 von 3844 Typparen als zulässig; der Graph
übernimmt den Kurzschluss des Writers, damit Graph und Export nicht
auseinanderlaufen. K04 nennt in der Meldung, welche Beziehung an denselben
Endpunkten zulässig wäre.

### Ports, Parts, Pins

Sie sind keine ArchiMate-Elemente. Wie der Writer zieht der Lader ihre Kanten
auf das Trägerelement (`zusammengefasst` im Bericht). Zwei Kanten zwischen
Ports desselben Trägers werden dadurch zur Selbstkante oder zur doppelten
Kante — das ist **kein Modellfehler**, sondern der Preis der Abbildung, und
steht als `K09`/`K10` (Hinweis) im Graphen. `K02`/`K06` melden nur, was schon
im Modell doppelt ist.

### Nicht Teil des Graphen

Die MDG-/ADMBw-Regeln. Die prüft `validator.py` gegen ein Regelwerk
(`--rules`); beide arbeiten auf demselben IR und schließen sich nicht aus. Der
Graph beantwortet die Frage „ist das gültiges ArchiMate?“, der Validator die
Frage „ist das gültiges ADMBw?“.

## 5. Gegenprobe gegen den Export

Der Graph darf dem Export nicht widersprechen. Deshalb prüfen Tests auf der
Musterarchitektur, dass die Befunde **exakt** den Zählern des Writers
entsprechen:

| Graph | Writer-Report | Bedeutung |
|---|---|---|
| K04 (Matrixverstöße, als Tripel verglichen) | `remapped` | dieselben Kanten werden beim Export umgebaut |
| K05 (nur Gegenrichtung) | `inverted` | dieselben Kanten werden beim Export gedreht |
| K02 + K10 (Selbstkanten) | `self_edges` | dieselben Kanten fallen beim Export weg |
| `knoten.archimate_typ` je Element | `elemente[].type` | derselbe Typ je Kennung |

Gemessen an der Musterarchitektur (Stand 09.11.2026): 38 Matrixverstöße,
28 Drehungen, 64 Selbstkanten, 73 echte Dubletten, 51 offene Endpunkte.
Die Testarchitektur hat 422 Kanten, davon 8 Matrixverstöße — der Export ist
deshalb sauber, der Graph zeigt die acht Stellen.

Ein Unterschied ist gewollt: `K06` zählt **Dubletten im Modell** (gleiche
Rohreferenzen). Der Writer zählt erst nach dem Umbau; zwei verschiedene
Beziehungen, die auf dieselbe zulässige Beziehung abgebildet werden, sind bei
ihm Dubletten, im Modell aber zwei Aussagen.

## 6. Grenzen

- **Eine Datei, ein Modell.** Der Graph kennt keine Modellversionen; für einen
  Vergleich zweier Stände zwei Datenbanken laden und über die Kennungen
  joinen.
- **Kein Schreiben.** `oeffne()` öffnet schreibgeschützt; jede Änderung am
  Modell gehört in die `.qea` und danach in einen neuen Ladevorgang.
- **Kein Layout, keine Sichten.** Diagramme werden nicht übernommen.
- **Pakete aus XML sind unvollständig.** Das Austauschformat kennt nur Pakete,
  die Elemente tragen; leere Pakete einer `.qea` fehlen nach dem XML-Umweg.

## 7. Tests

```bash
python3 -m pytest tests/core/test_graph.py -q     # 40 Tests
```

Die Tests decken Knoten/Kanten/Kennungen, jede Regel, die Abfragen, die
rekursive Beispielabfrage der Doku, alle drei Eingabeformate, Determinismus,
schreibgeschütztes Öffnen und die Gegenprobe gegen den Writer ab.
