# Migration: von neun Repositories zu einem

Stand 24.10.2026. Die neun Alt-Repos sind **archiviert** (bei GitHub nur noch
lesbar), lokal unverändert und mit dem Tag `pre-consolidation-2026-10` gesichert.
Ihre READMEs verweisen auf dieses Repository. Gelöscht wurde nichts.

| Alt-Repo | Ziel im Monorepo | Status | Anmerkung |
|---|---|---|---|
| `EAM-AI-Suite` (`architektur-mate-ki`) | `apps/html-suite` | eigener Quellstand | `src/` + `vendor/` und eigener Build, keine UI-Konfiguration |
| `EAM-AI-Suite-Python` (`eam-suite-ai`) | `packages/core` + `apps/cli` | übernommen | 31 Module, 668 Tests, unveränderte Prüflogik |
| `EAM-Suite` (`admbw-qea-editor`) | `apps/html-editor` | eigener Quellstand | eigener Editor v8.4, kein gemeinsamer UI-Kern |
| `EAM-QEA-Analyzer` (`admbw-qea-analyzer`) | `apps/html-analyzer` | eigener Quellstand | eigener Analyzer v4.0, ohne Edit/KI |
| `EAM-AI-QEA-Analyzer` (`eam-qea-tool`) | `apps/mcp` | übernommen | CLI, MCP-Server, Web-API, Tests |
| `EAM-AI-ADMBw-Extractor` | `apps/admbw-extractor` | übernommen | Prüfungen 53/53 |
| `EAM-AI-ADMBw-Batch` | `apps/admbw-batch` | übernommen | Prüfungen 40/40 |
| `EAM-AI-ADMBw-Script-Maker` | `apps/admbw-script-maker` | übernommen | 51 PASS, 0 FAIL |
| `EAM-ADMBw-MDG-Parser` | `packages/rules` | übernommen | kanonischer Parser + Wissensbasis-Erzeugung |

## Was bewusst nicht mitgezogen wurde

- **Kopien der Wissensbasis**: ersetzt durch `knowledge/` und Symlinks.
- **`sync_tools.py` / `check_kb_sync.py`**: überflüssig, weil es nur noch eine
  Quelle gibt. Die Drift-Prüfung liegt in `scripts/build_knowledge.py`.
- **Alte `dist`-Artefakte**: werden aus dem Monorepo neu und deterministisch
  gebaut (`scripts/build_all.py`).
- **`.git`-Verläufe**: liegen als Bundles in
  `Backup-Archiv/` und in den unveränderten Alt-Repos.

## Endzustand

- **Eine Quelle:** `packages/rules` (Leser + Regelwerk), `knowledge/` (daraus erzeugt).
- **Drei eigenständige HTML-Werkzeuge:** `apps/html-suite` (AI Suite 9.1),
  `apps/html-analyzer` (QEA Analyzer 4.0) und `apps/html-editor` (EAM Suite 8.4)
  bringen jeweils eigenen `src/`- und `vendor/`-Stand mit; es gibt keinen
  gemeinsamen UI-Kern und keine per CSS versteckten Varianten.
- **Keine Verteilung mehr:** `sync_consumers.py` und `CONSUMERS.json` sind entfernt;
  die Apps lesen die Wissensbasis über Symlinks. Wächter:
  `scripts/check_single_source.py` (läuft in CI und als Test).
- **Ein Python-Leser:** `packages/rules/mdg_parser.py` erzeugt die Wissensbasis;
  der Browser-Parser `apps/mdg-web/index.html` liest die MDG-XML direkt
  (Upload, fünf Ansichten, sechs Exporte) und wird unverändert ausgeliefert.
  Der Altparser bleibt Prüfmaßstab unter `tools/referenz_parser/`.
- **Auslieferung:** `eam-html.service` dient direkt `apps/html-suite/dist`;
  Container `eam-ai-web` läuft mit `ghcr.io/mitchel85/eam-toolfamilie:v3.0.3`.
- **Rollback:** der Vorgänger steht gestoppt als `eam-ai-web-rollback-3.0.0`
  bereit; Zurücknehmen in einem Schritt:
  `docker rm -f eam-ai-web && docker rename eam-ai-web-rollback-3.0.0 eam-ai-web && docker start eam-ai-web`

## Was noch offen ist

1. Sichtbarkeit des GHCR-Pakets `eam-toolfamilie` separat festlegen (Registry-Paket;
   ggf. nur mit Anmeldung ziehbar). `apps/mdg-web` ist die alte Browser-Fassung:
   `build.py` kopiert `index.html` byte-gleich nach `dist/`; keine Erzeugung
   aus `knowledge/`.
