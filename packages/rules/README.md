# packages/rules — MDG-Parser

Einzige Quelle fuer Regeln und Wissensbasis.

- Eingabe: MDG-XML (Technologiebeschreibung, beliebige Fassung)
- Ausgabe: Stereotype, Aliases, Regeltexte, Topologie, Viewpoints

```
python3 mdg_parser.py <MDG.xml> --out ./output --no-timestamp
```

Die Ausgabe wird im Repository **nicht** von Hand gepflegt: sie entsteht ueber
`scripts/build_knowledge.py` in `knowledge/` und wird dort geprueft.
