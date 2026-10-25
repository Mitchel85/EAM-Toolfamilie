# Abhängigkeiten der EAM-Toolfamilie

> Erzeugt von `scripts/dependency_report.py`; nicht von Hand ändern.
> Prüfen mit `python3 scripts/dependency_report.py --check`.
> GitHub rendert den Mermaid-Block; lokal zeigen ihn VS Code oder Obsidian.

## 0. Graph

```mermaid
flowchart LR
  z0["@mitchel85/eam-rules<br/>packages/rules"]
  z1["@mitchel85/eam-core<br/>packages/core"]
  z2["@mitchel85/eam-vendor<br/>vendor"]
  z3["eam-ai-suite<br/>apps/html-suite"]
  z4["eam-qea-analyzer<br/>apps/html-analyzer"]
  z5["eam-suite<br/>apps/html-editor"]
  z6["eam-mdg-web<br/>apps/mdg-web"]
  z7["eam-mcp<br/>apps/mcp"]
  z8["eam-admbw-extractor<br/>apps/admbw-extractor"]
  z9["eam-admbw-batch<br/>apps/admbw-batch"]
  z10["eam-admbw-script-maker<br/>apps/admbw-script-maker"]
  z11["eam-ai-cli<br/>apps/cli"]
  z1 --> z0
  z3 -.-> z2
  z4 -.-> z2
  z5 -.-> z2
  z7 --> z1
  z8 --> z0
  z9 --> z0
  z10 --> z0
  z11 --> z1
  z11 --> z0
```

## 1. Zellen und Kanten

Eine Zelle ist ein Ordner mit `package.json`. `dependencies` sind Laufzeit-,
`devDependencies` sind Build-Zeit-Kanten.

| Zelle | Name | Version | Abhängigkeiten |
|---|---|---|---|
| `packages/rules` | @mitchel85/eam-rules | 2.5.0 | — |
| `packages/core` | @mitchel85/eam-core | 2.4.0 | `@mitchel85/eam-rules` |
| `vendor` | @mitchel85/eam-vendor | 1.0.0 | — |
| `apps/html-suite` | eam-ai-suite | 9.1.0 | `@mitchel85/eam-vendor` |
| `apps/html-analyzer` | eam-qea-analyzer | 4.0.0 | `@mitchel85/eam-vendor` |
| `apps/html-editor` | eam-suite | 8.4.0 | `@mitchel85/eam-vendor` |
| `apps/mdg-web` | eam-mdg-web | 2.0.0 | — |
| `apps/mcp` | eam-mcp | 2.4.0 | `@mitchel85/eam-core` |
| `apps/admbw-extractor` | eam-admbw-extractor | 2.4.0 | `@mitchel85/eam-rules` |
| `apps/admbw-batch` | eam-admbw-batch | 2.4.0 | `@mitchel85/eam-rules` |
| `apps/admbw-script-maker` | eam-admbw-script-maker | 2.4.0 | `@mitchel85/eam-rules` |
| `apps/cli` | eam-ai-cli | 2.4.0 | `@mitchel85/eam-core`, `@mitchel85/eam-rules` |

## 2. Kanonische Quellen

| Quelle | Wird zu | Mechanik | Prüfung |
|---|---|---|---|
| `packages/rules/NAFv4-ADMBw-MDG-2026.05.xml` | `knowledge/admbw-*` | `build_knowledge.py` | `--check --check-provenance` |
| `packages/rules/mdg_parser.py` + `documents.py` | `knowledge/admbw-*` | Parser → Dokumente | `check_single_source.py` |
| `knowledge/*` | `apps/admbw-*/` | Symlink, keine Kopie | `verify_graph.py` |
| `vendor/*` | `apps/html-*/vendor/` | `sync_vendor.py` | `sync_vendor.py --check` |
| `apps/html-*/src` + `vendor` | `apps/html-*/dist` | `build_legacy_app.py` | `test_html_artifacts.py` |
| `apps/mdg-web/index.html` | `apps/mdg-web/dist` | byte-gleiche Kopie | `test_mdg_web.py` |
| `apps/*/dist` | `dist/` | `collect_releases.py` | `test_collect_releases.py` |

## 3. Änderungsmatrix

| Änderung | Betroffen | Befehl |
|---|---|---|
| `packages/rules/NAFv4-ADMBw-MDG-2026.05.xml`<br>`packages/rules/mdg_parser.py`<br>`packages/rules/documents.py`<br>`packages/rules/documents_format.py` | `knowledge`, `apps/admbw-extractor`, `apps/admbw-batch`, `apps/admbw-script-maker`, `dist` | `python3 scripts/propagate.py --all` |
| `knowledge/*` | `apps/admbw-extractor`, `apps/admbw-batch`, `apps/admbw-script-maker` | `python3 scripts/propagate.py --write && python3 -m pytest -q tests/apps` |
| `vendor/*` | `apps/html-suite`, `apps/html-analyzer`, `apps/html-editor`, `dist` | `python3 scripts/sync_vendor.py --write && python3 scripts/propagate.py --build` |
| `apps/html-suite/*` | `apps/html-suite`, `dist` | `python3 scripts/build_legacy_app.py apps/html-suite && python3 scripts/propagate.py --release` |
| `apps/html-analyzer/*` | `apps/html-analyzer`, `dist` | `python3 scripts/build_legacy_app.py apps/html-analyzer && python3 scripts/propagate.py --release` |
| `apps/html-editor/*` | `apps/html-editor`, `dist` | `python3 scripts/build_legacy_app.py apps/html-editor && python3 scripts/propagate.py --release` |
| `apps/mdg-web/*` | `apps/mdg-web`, `dist` | `python3 apps/mdg-web/build.py && python3 scripts/propagate.py --release` |
| `packages/core/*` | `apps/cli`, `apps/mcp`, `dist` | `python3 scripts/propagate.py --build` |
| `apps/mcp/*` | `apps/mcp`, `dist` | `python3 scripts/propagate.py --release` |
| `apps/admbw-extractor/*`<br>`apps/admbw-batch/*`<br>`apps/admbw-script-maker/*` | `apps/admbw-extractor`, `apps/admbw-batch`, `apps/admbw-script-maker` | `python3 scripts/propagate.py --check && python3 apps/admbw-batch/checks/verify.py` |
| `scripts/*`<br>`.github/workflows/*` | `alle`, `dist` | `python3 scripts/propagate.py --all && python3 -m pytest -q` |

## 4. Vendor

| Bibliothek | SHA-256 | Suite | Analyzer | Editor |
|---|---|---|---|---|
| `vendor/LICENSE-pdfjs.txt` | `cfc7749b96f63bd3…` | — | — | — |
| `vendor/LICENSE-sql.js` | `60a3f6e4d7b29b43…` | x | x | x |
| `vendor/jszip.min.js` | `acc7e41455a80765…` | x | — | — |
| `vendor/pdf.min.js` | `1fc294eefda602e5…` | x | — | — |
| `vendor/pdf.worker.min.js` | `99732130603cd498…` | x | — | — |
| `vendor/sql-wasm.js` | `694ca5b36aa3e6e7…` | x | x | x |
| `vendor/sql-wasm.wasm` | `0734155c83e49398…` | x | x | x |

## 5. Wissensbasis-Verweise

30 Symlinks in den Downstream-Apps:

- `apps/admbw-extractor/ADMBw-Aliases.json` → `knowledge/admbw-aliases.json`
- `apps/admbw-extractor/ADMBw-Knowledge-Connectors.md` → `knowledge/admbw-knowledge-connectors.md`
- `apps/admbw-extractor/ADMBw-Knowledge-Stereotype-Tags.md` → `knowledge/admbw-knowledge-stereotype-tags.md`
- `apps/admbw-extractor/ADMBw-Knowledge-Stereotypes.md` → `knowledge/admbw-knowledge-stereotypes.md`
- `apps/admbw-extractor/ADMBw-Knowledge-TagTypes.md` → `knowledge/admbw-knowledge-tagtypes.md`
- `apps/admbw-extractor/ADMBw-Knowledge-Topology.md` → `knowledge/admbw-knowledge-topology.md`
- `apps/admbw-extractor/ADMBw-Knowledge-Viewpoints.md` → `knowledge/admbw-knowledge-viewpoints.md`
- `apps/admbw-extractor/ADMBw-Meta.md` → `knowledge/admbw-meta.md`
- `apps/admbw-extractor/ADMBw-Prompt.md` → `knowledge/admbw-prompt.md`
- `apps/admbw-extractor/ADMBw-Stereotypes.json` → `knowledge/admbw-stereotypes.json`
- `apps/admbw-batch/ADMBw-Aliases.json` → `knowledge/admbw-aliases.json`
- `apps/admbw-batch/ADMBw-Knowledge-Connectors.md` → `knowledge/admbw-knowledge-connectors.md`
- `apps/admbw-batch/ADMBw-Knowledge-Stereotype-Tags.md` → `knowledge/admbw-knowledge-stereotype-tags.md`
- `apps/admbw-batch/ADMBw-Knowledge-Stereotypes.md` → `knowledge/admbw-knowledge-stereotypes.md`
- `apps/admbw-batch/ADMBw-Knowledge-TagTypes.md` → `knowledge/admbw-knowledge-tagtypes.md`
- `apps/admbw-batch/ADMBw-Knowledge-Topology.md` → `knowledge/admbw-knowledge-topology.md`
- `apps/admbw-batch/ADMBw-Knowledge-Viewpoints.md` → `knowledge/admbw-knowledge-viewpoints.md`
- `apps/admbw-batch/ADMBw-Meta.md` → `knowledge/admbw-meta.md`
- `apps/admbw-batch/ADMBw-Prompt.md` → `knowledge/admbw-prompt.md`
- `apps/admbw-batch/ADMBw-Stereotypes.json` → `knowledge/admbw-stereotypes.json`
- `apps/admbw-script-maker/references/admbw-aliases.json` → `knowledge/admbw-aliases.json`
- `apps/admbw-script-maker/references/admbw-knowledge-connectors.md` → `knowledge/admbw-knowledge-connectors.md`
- `apps/admbw-script-maker/references/admbw-knowledge-stereotype-tags.md` → `knowledge/admbw-knowledge-stereotype-tags.md`
- `apps/admbw-script-maker/references/admbw-knowledge-stereotypes.md` → `knowledge/admbw-knowledge-stereotypes.md`
- `apps/admbw-script-maker/references/admbw-knowledge-tagtypes.md` → `knowledge/admbw-knowledge-tagtypes.md`
- `apps/admbw-script-maker/references/admbw-knowledge-topology.md` → `knowledge/admbw-knowledge-topology.md`
- `apps/admbw-script-maker/references/admbw-knowledge-viewpoints.md` → `knowledge/admbw-knowledge-viewpoints.md`
- `apps/admbw-script-maker/references/admbw-meta.md` → `knowledge/admbw-meta.md`
- `apps/admbw-script-maker/references/admbw-prompt.md` → `knowledge/admbw-prompt.md`
- `apps/admbw-script-maker/references/admbw-stereotypes.json` → `knowledge/admbw-stereotypes.json`

## 6. Release-Assets

| Asset | Quelle |
|---|---|
| `EAM-AI-Suite.html` | `apps/html-suite/dist/EAM-AI-Suite.html` |
| `EAM-AI-Suite.aspx` | `apps/html-suite/dist/EAM-AI-Suite.aspx` |
| `EAM-QEA-Analyzer.html` | `apps/html-analyzer/dist/EAM-QEA-Analyzer.html` |
| `EAM-QEA-Analyzer.aspx` | `apps/html-analyzer/dist/EAM-QEA-Analyzer.aspx` |
| `EAM-Suite.html` | `apps/html-editor/dist/EAM-Suite.html` |
| `EAM-Suite.aspx` | `apps/html-editor/dist/EAM-Suite.aspx` |
| `EAM-MDG-Parser.html` | `apps/mdg-web/dist/EAM-MDG-Parser.html` |
| `eam_qea_analyzer_openwebui.py` | `apps/mcp/eam_qea_tool.py` |
| `eam-ai-suite-python.zip` | `packages/core` (Quellarchiv) |

