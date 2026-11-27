# EAM AI Suite Python — Open WebUI Standalone (ohne Container)

Diese Variante ist für Zielhosts gedacht, auf denen du **nur Open-WebUI-Funktionen, Tools und Skills importieren**, aber **keine Docker-Container deployen** und kein `pip install` ausführen kannst (inkl. komplett abgeschotteter / air-gapped Umgebungen).

## Enthaltene Dateien

| Datei | Verwendung in Open WebUI |
|---|---|
| `eam_ai_suite_openwebui_standalone.py` | **Workspace → Tools → + Neues Tool**: 8 Werkzeuge (`build_architecture`, `validate_and_qs`, `nl_edit`, `diff_versions`, `repair_preview`, `ask_model`, `undo_version`, `export_artifact`). |
| `eam_ai_suite_pipe_standalone.py` | **Workspace → Functions → + Neue Function**: erscheint als eigenes Modell *„EAM AI Suite Standalone (7-Stufen-Architekt, ohne Container)“*. |
| `eam_ai_suite_skill.md` | **Workspace → Skills** (oder System-Prompt eines eigenen Modells). |

## Wie funktioniert das ohne Container?

- Der gesamte abhängigkeitsfreie Python-Kern (`packages/core`), der MDG-Parser (`mdg_parser.py`) sowie das aktuelle Regelwerk (`regelwerk.json` + MDG-XML) sind komprimiert direkt in der `.py`-Datei eingebettet.
- Beim ersten Aufruf entpackt sich die Laufzeitumgebung einmalig ins System-Temp-Verzeichnis (konfigurierbar über Valve `cache_dir`) und startet einen internen Loopback-Dienst (`127.0.0.1:<freier Port>`) im eigenen Python-Prozess von Open WebUI.
- **Keine externen Pakete (`requirements:` leer), kein Internetzugang, kein Docker, keine Root-Rechte.**

## Einrichtung (2 Minuten)

1. `eam_ai_suite_openwebui_standalone.py` unter **Workspace → Tools** (und/oder `eam_ai_suite_pipe_standalone.py` unter **Workspace → Functions**) einfügen und speichern.
2. In den **Valves** das LLM-Backend des Zielhosts eintragen:
   - `llm_backend`: `openai` (für Ollama, vLLM, OpenAI oder lokale Open-WebUI-API) — oder `datei` für einen Offline-Funktionstest ohne LLM.
   - `llm_base_url`: z. B. `http://localhost:11434/v1`
   - `llm_model`: gewünschtes Modell
   - `llm_api_key`: API-Key (falls erforderlich)
   - `export_dir` *(optional)*: Verzeichnis auf dem Host, in das `export_artifact` bzw. `export <datei>` fertige `.qea` / `.zip` schreibt.
3. Optional `eam_ai_suite_skill.md` als Skill hinterlegen und im Chat loslegen.
