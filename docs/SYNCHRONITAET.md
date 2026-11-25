# Synchronitäts-Checkliste (EAM Toolfamilie)

Jede funktionale Änderung an einer App, der Python-CLI/WebUI oder den Regeln muss **sofort** in allen abhängigen Artefakten nachgezogen werden, damit Doku, Grafiken, GitHub Pages, LinkedIn-Material und Agensi-Skills niemals auseinanderlaufen.

## 1. Repo-interne Artefakte (Pflicht vor jedem Commit)
1. **Apps & Manifeste:**
   - Geänderte HTML-Apps neu bauen (`python3 scripts/build_legacy_app.py apps/<app>`).
   - `sourceTreeSha256` in `apps/<app>/app.json` und Bytegröße/Marker in `tests/test_html_artifacts.py` aktualisieren.
2. **Prosa & Seiten:**
   - `README.md` (Ablauftabelle, Werkzeug-Vergleich, Abgrenzungen).
   - `packages/core/README.md` (Module, CLI/WebUI-Befehle).
   - `scripts/collect_releases.py` (`AUSLIEFERUNGEN`, `APP_ZIPS`, `START-HIER.html` -> **GitHub Pages** `https://mitchel85.github.io/EAM-Toolfamilie/`).
3. **Grafiken & Wissensgraph (ein Befehl):**
   ```bash
   python3 scripts/sync_all_artifacts.py
   ```
   Regeneriert deterministisch:
   - `docs/workflow-abdeckung.png` (`scripts/make_workflow_image.py`)
   - `docs/toolfamilie-tabelle.png` (`scripts/make_table_image.py`)
   - `docs/eam-toolfamilie-linkedin.png` + Kopie nach `../buchprojekt/EAM_TOOLFAMILIE_LINKEDIN.png` (`scripts/make_linkedin_image.py`)
   - Prüft die Architekturkarte per `scripts/verify_graph.py`.

## 2. Externe Artefakte (bei jeder größeren Funktionsänderung mitprüfen)
1. **Zentrale Website (`https://estel.email/`):**
   - Repo `Mitchel85/Mitchel85` (`../Mitchel85/index.html`) — Karte *EAM Tool-Familie* synchron halten, committen & pushen.
2. **Agensi-Skills (`agensi.io`):**
   - `docs-to-architecture-builder-prose-docx-to-validated-qea-archimate-xmi` (`SKILL.md` + `scripts/eam_builder.py`)
   - `enterprise-architecture-qa-impact-analyzer-qea-xmi-archimate-json` (`SKILL.md` + `scripts/eam_analyzer.py`)
   - `bpmn-2-0-process-validator-auto-fixer-no-ai-needed-nafv4-admbw-neutral`
   - `mdg-architecture-rules-extractor-nafv4-admbw-to-json-markdown`
   - Bei Funktionsänderungen betroffene Skills per `update_skill` (und ggf. `upload_skill_media`) nachziehen.
3. **LinkedIn (`https://www.linkedin.com/in/michael-estel/`):**
   - Aktuelle Grafik `docs/eam-toolfamilie-linkedin.png` (synchron in `../buchprojekt/EAM_TOOLFAMILIE_LINKEDIN.png`) für Beiträge/Featured-Einträge bereithalten.
