# packages/rules — MDG-Parser

Einzige Quelle fuer Regeln und Wissensbasis.

- Eingabe: MDG-XML (Technologiebeschreibung, beliebige Fassung)
- Ausgabe: Stereotype, Aliases, Regeltexte, Topologie, Viewpoints

```
python3 mdg_parser.py <MDG.xml> --out ./output --no-timestamp
```

Die Ausgabe wird im Repository **nicht** von Hand gepflegt: sie entsteht ueber
`scripts/build_knowledge.py` in `knowledge/` und wird dort geprueft.

## Stand und Aktualisierung

- `CURRENT` nennt die aktuelle MDG-Datei; Parser, Bau, Tests und CI lesen sie dort
  (einzige Quelle: `mdg_source.py`).
- Der GitHub-Workflow `rules-watch.yml` prueft taeglich die amtliche Quelle
  (BAAINBw, „Methode Architektur") auf ein neues Regelwerk. Bei Aenderung uebernimmt
  `scripts/regelwerk_update.py` alles automatisch: Herunterladen, Entpacken,
  `CURRENT` setzen, Wissensbasis weiterreichen — als Branch `rules/auto-update`
  mit PR, nie als direkter Commit auf `main`.
- **PII-Neutralisierung:** die amtliche MDG enthaelt eine Absenderadresse im
  `Documentation`-Element. Die hier liegende Fassung ersetzt sie durch
  `support@example.invalid`; `regelwerk_update.py` reproduziert das bei jeder
  Uebernahme. Nur so darf eine neue MDG eingelagert werden.
- Handweg fuer die uebrigen Quellen (PDFs, Handbuecher):
  `fetch_quellen.py` → `extract_leitfaden.py` → `build_regelwerk.py`.
