# Wissensbasis

Drei Schichten, ein Artefakt: `regelwerk.json`.

## Die drei Schichten

| Schicht | Frage | Quelle | Wie sie entsteht |
|---|---|---|---|
| **erlaubt** | Was darf gebaut werden? | MDG (`packages/rules/NAFv4-ADMBw-MDG-2026.05.xml`) | gelesen vom einzigen MDG-Leser `packages/rules/mdg_parser.py` |
| **gefordert** | Was verlangt der Auftraggeber? | Leitfaden FFFmLV v2.0, Leitfaden PBN Service/System v2.1 | aus den PDFs extrahiert, je Sicht als Konvention |
| **gemustert** | Wie sieht eine gute Sicht aus? | Model Wizard, 52 Vorlagen | gelesen von `packages/core/wizard.py` |

Die MDG sagt, welche Bausteine es gibt und wie sie verbunden werden dürfen.
Sie sagt **nicht**, welche Sichten ein Projekt braucht und was in ihnen stehen
muss. Das steht in den Leitfäden — und für die Sichten, die dort nicht
vorkommen, im Model Wizard.

## Das Artefakt

`regelwerk.json` führt je Viewpoint zusammen:

```json
"C2": {
  "titel": "C2 - Enterprise Vision",
  "gruppe": "Concept Viewpoints",
  "mdg": { "elemente": ["..."], "konnektoren": [["CapabilityDependency", "Capability", "Capability"]] },
  "leitfaeden": { "ffmlv": {"konventionen": 0, "ids": []}, "pbn": {"konventionen": 0, "ids": []} },
  "model_wizard": { "vorlage": "C2 - Enterprise Vision", "elemente": ["..."], "beziehungen": [["...", "...", "..."]] },
  "luecken": ["ffmlv", "pbn"]
}
```

Daneben der Abschnitt `pruefung`: 43 verlangte Pakete, 41 verlangte Sichten und
20 Pflichtstereotype je Viewpoint -- die Ebene, gegen die `struktur.py` prüft.
Sie stammt aus `knowledge/leitfaden/pruefung.json` und wird beim Bauen
eingemischt. `leitfaden.py` hält keine eigene Kopie mehr, sondern liest sie aus
dem Artefakt.

`luecken` nennt, welche Schicht zu einer Sicht nichts sagt. Das ist keine
Warnung, sondern eine Auskunft: C2 ist im Wizard gemustert, in beiden
Leitfäden aber nicht verlangt.

Zugriff im Code über `packages/core/regelwerk.py`:

```python
import regelwerk
regelwerk.sichten()            # Viewpoints mit Leitfadenvorgabe
regelwerk.nur_wizard()         # Viewpoints, die nur der Wizard kennt
regelwerk.stereotype("C2")     # (erlaubt laut MDG, verwendet im Muster)
```

## Bauen

```bash
python3 scripts/fetch_quellen.py            # amtliche PDFs nach ~/.cache/eam-quellen
python3 scripts/extract_leitfaden.py <text> # Konventionen aus einem Leitfaden
python3 scripts/build_regelwerk.py          # Artefakt schreiben
python3 scripts/build_regelwerk.py --check  # nur prüfen (Exit 1 bei Drift)
```

`--check` läuft in der Testsuite (`tests/core/test_regelwerk.py`). Ändert sich
eine Quelle, ohne dass das Artefakt neu gebaut wurde, wird der Test rot.

## Was hier nicht liegt

Die amtlichen PDFs und das Model-Wizard-Archiv liegen **nicht** im Repository:
fremde Dokumente, rund 20 MB, für den Betrieb nicht nötig. `fetch_quellen.py`
holt sie; die daraus erzeugten Dateien sind versioniert.

Die 52 Model-Wizard-Vorlagen (7,3 MB) sind aus demselben Grund nicht
versioniert (`.gitignore`). Fehlen sie, arbeitet der Wizard nicht still weiter,
sondern meldet es.

## Abgeleitete Dateien

`admbw-knowledge-*.md` und `admbw-stereotypes.json` sind **Erzeugnisse** der
MDG, keine eigene Quelle. Sie entstehen mit `scripts/build_knowledge.py` und
werden von `scripts/check_single_source.py` gegen die MDG geprüft. Wer sie von
Hand ändert, verliert die Änderung beim nächsten Lauf.
