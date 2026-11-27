# EAM AI Suite Python — Open WebUI Integration (Tool, Pipe & Skill)

Drei schlanke Dateien ohne Fremdpakete, die die **EAM AI Suite Python** direkt in **Open WebUI** verfuegbar machen — wahlweise ueber den automatisch aktuellen GHCR-Container (`mode="http"`, empfohlen) oder lokal installiertes `eam-ai` (`mode="local"`).

## Enthaltene Dateien

| Datei | Einsatz in Open WebUI | Zweck |
|---|---|---|
| `eam_ai_suite_openwebui.py` | **Workspace → Tools** | Stellt dem Sprachmodell 8 Werkzeuge bereit (`build_architecture`, `validate_and_qs`, `diff_architectures`, `repair_architecture`, `edit_architecture`, `undo_architecture`, `ask_architecture`, `convert_architecture`). |
| `eam_ai_suite_pipe.py` | **Workspace → Functions (Pipe)** | Erscheint als eigenes auswaehlbares Modell **„EAM AI Suite (7-Stufen-Architekt)“** mit Live-Fortschritt und Direktkommandos (`frage`, `aendere`, `diff`, `repair`, `undo`). |
| `eam_ai_suite_skill.md` | **Workspace → Skills** (oder System-Prompt) | Gibt dem Sprachmodell die verbindliche 7-Stufen-Reihenfolge vor (erst pruefen, Reparatur zuerst als Vorschau, Quellen nennen). |
| `docker-compose.openwebui.yml` | Docker Compose | Startet Open WebUI + `ghcr.io/mitchel85/eam-toolfamilie:latest` im selben internen Netz (`http://eam-toolfamilie:8080`). |

## Einrichtung in 3 Schritten

1. **Container starten** (oder bestehenden `eam-ai serve`-Dienst nutzen):
   ```bash
   docker compose -f docker-compose.openwebui.yml up -d
   ```
2. **Tool (und optional Pipe) importieren:**
   - In Open WebUI unter **Workspace → Tools → „+“** den Inhalt von `eam_ai_suite_openwebui.py` einfuegen und speichern.
   - Optional in den **Valves** `eam_api_url` (`http://eam-toolfamilie:8080`) und `public_api_url` (`http://localhost:8080`) pruefen.
   - Optional unter **Workspace → Functions** `eam_ai_suite_pipe.py` als Pipe-Funktion einfuegen.
3. **Skill hinterlegen:**
   - Unter **Workspace → Skills** (oder im Modell-Systemprompt) `eam_ai_suite_skill.md` hinterlegen und das Tool dem Modell zuweisen.
