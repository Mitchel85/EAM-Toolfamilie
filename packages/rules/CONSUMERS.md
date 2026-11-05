# Verbraucher — wer die Wissensbasis nutzt, und wie

Die Wissensbasis entsteht in `knowledge/` aus dem Parser in `packages/rules`.
Verbraucher bekommen sie **nicht** als Kopie ins Repository, sondern zur Bau-
oder Laufzeit. Dieses Dokument hält fest, was jeder Verbraucher wirklich nutzt,
damit beim Umstellen nichts stillschweigend verschwindet.

## Was erzeugt wird, und wer es braucht

| Datei im Monorepo | Extractor | Python-Suite | HTML-Suite |
|---|---|---|---|
| `admbw-stereotypes.json` | ja | ja | ja |
| `admbw-aliases.json` | ja | ja | ja |
| `admbw-knowledge-stereotypes.md` | ja | ja | ja |
| `admbw-knowledge-topology.md` | ja | ja | ja |
| `admbw-knowledge-viewpoints.md` | ja | ja | ja |
| `admbw-knowledge-tagtypes.md` | ja | ja | ja |
| `admbw-knowledge-stereotype-tags.md` | ja | ja | ja |
| `admbw-meta.md` | ja | – | – |
| `admbw-prompt.md` | ja | – | – |

## Vertrag

1. **Kein Verbraucher hält eine eigene Kopie** dieser Dateien im Git.
2. Zugriff erfolgt über den Pfad `knowledge/<datei>` (Build-Zeit) oder über
   das Paket `packages/rules` (Laufzeit).
3. Die Groß-/Kleinschreibung der Dateinamen ist im Monorepo **einheitlich
   klein** (`admbw-…`). Alte Repos benutzten `ADMBw-…`; das war nur eine
   Umbenennung, kein anderer Inhalt.
4. `admbw-prompt.md` enthielt in den Alt-Repos je nach Werkzeug unterschiedliche
   Dateinamen im Fließtext (`ADMBw-Knowledge-Stereotypes.md` vs.
   `admbw-knowledge-stereotypes.md`). Im Monorepo gilt **eine** Schreibweise.

## Ausnahmen

`ADMBw-Knowledge-Connectors.md` wurde **nie** vom Parser erzeugt — sie war
handgeschrieben und werkzeugspezifisch. Seit der Konsolidierung wird sie aus
dem Regelwerk erzeugt und liegt als `knowledge/admbw-knowledge-connectors.md`
an einer Stelle; der Extractor liest sie über einen Symlink. Die
werkzeugspezifischen Alt-Fassungen aus den Batch-/Script-Maker-Repos sind mit
deren Löschung (05.11.2026) entfallen.

## Umstellung (abgeschlossen)

Die Verteilung an die Alt-Repos ist entfallen. Die neun Alt-Repos sind am
05.11.2026 nach lokalem Mirror-Backup bei GitHub geloescht; ihre letzte
Fassung traegt den Tag `pre-consolidation-2026-10` im Backup-Archiv.
Innerhalb des Monorepos lesen die Apps die
Wissensbasis ueber Symlinks aus `knowledge/` — es gibt keine Kopien und keinen
Synchronisationsschritt mehr. Waechter: `scripts/check_single_source.py`.
