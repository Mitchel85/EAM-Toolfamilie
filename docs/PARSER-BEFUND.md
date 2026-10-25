# Befund: Zwei Parser, zwei Aufgaben

Stand 24.10.2026, gemessen an den beiden Dateien im Monorepo.

## Die Kurzfassung

Die „zwei Parser-Versionen" sind **keine zwei Fassungen derselben Sache**. Es
sind zwei verschiedene Werkzeuge mit ähnlichem Namen:

| | `packages/rules/mdg_parser.py` | `packages/core/mdg_parser.py` |
|---|---|---|
| Herkunft | EAM-ADMBw-MDG-Parser | EAM AI Suite Python |
| Zeilen | 796 | 772 |
| Aufgabe | MDG → **Dokumente** (Markdown, JSON-Wissensbasis) | MDG → **Regelmodell im Speicher** |
| Öffentliche API | `extract_*`, `build_md`, `build_prompt_doc`, `build_suite_rules`, `main` | `MdgParseError`, `parse_mdg`, `parse_mdg_bytes`, `dumps_rules`, `write_rules`, `main` |
| Ausgabe | Dateien in `knowledge/` | Objekte, die `validator.py` und `model_edit.py` prüfen |
| Klassen | keine | `MdgParseError` |

**Gemeinsamkeit:** beide lesen dasselbe XML. **Kein gemeinsamer Code.**

## Was der Kern wirklich braucht

Der Kern nutzt aus seinem Parser genau drei Dinge:

```
parse_mdg       6 Aufrufe   (eam_ai, model_edit, repair_loop, skeleton)
MdgParseError   2 Aufrufe   (Fehlerbehandlung)
```

Das ist eine sehr kleine Schnittstelle. Sie ist der ideale Ansatzpunkt für eine
Zusammenführung — nicht die 772 Zeilen, sondern die drei Namen.

## Warum das die Redundanz-Frage verändert

Die ursprüngliche Annahme war: „zwei Fassungen, die auseinandergelaufen sind,
eine davon abschaffen". Das war falsch. Richtig ist:

- **Es gibt keine doppelt gepflegte Regel-Logik.** Doppelt gepflegt war nur die
  *Wissensbasis* (4× byte-identisch) — und die ist in Phase 1 aufgelöst.
- Der eigentliche Gewinn liegt woanders: beide Parser lesen XML mit eigenen
  Mitteln. Ein gemeinsamer Leser (Elementbaum, Namensräume, Fehlerbehandlung)
  würde die zweite Hälfte der Redundanz beseitigen.

## Vorschlag

**Nicht** zusammenlegen — **schichten**:

```
packages/rules/
  mdg_xml.py      gemeinsamer Leser: Baum, Namensräume, Version, Fehler
  documents.py    MDG → Wissensbasis (heute rules/mdg_parser.py)
  model.py        MDG → Regelmodell (heute core/mdg_parser.py, API bleibt)
```

Der Kern importiert danach `from rules.model import parse_mdg, MdgParseError` —
gleiche Namen, gleiches Verhalten, andere Stelle. Die 668 Kerntests sind der
Beweis, dass der Umzug nichts verändert hat.

**Reihenfolge:** erst `model.py` umziehen und Tests grün halten, dann
`documents.py`, dann den gemeinsamen Leser herausziehen — jeder Schritt einzeln
messbar.

## Was daraus für die Roadmap folgt

- P1 „Parser-Source definieren" ist **erledigt** — nicht durch Auswahl, sondern
  durch Klärung.
- Neuer Punkt in Phase 2: `core/mdg_parser.py` nach `packages/rules/model.py`
  verschieben, Importe umstellen, Tests unverändert lassen.
- Der gemeinsame XML-Leser ist **optional** und kommt erst, wenn beide Seiten
  im Monorepo liegen — er ist eine Verbesserung, keine Voraussetzung.
