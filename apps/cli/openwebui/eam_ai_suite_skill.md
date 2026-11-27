---
name: eam-ai-suite-python
description: >-
  Enterprise-Architecture-Workflow (NAF 4 / UAF, ADMBw & ArchiMate 3.2) ueber
  das Open-WebUI-Tool `eam_ai_suite_openwebui.py` und den EAM-AI-Suite-Container:
  Prosa in MDG-gepruefte Modelle ueberfuehren, QS/Textabdeckung pruefen,
  regelbasiert reparieren, vergleichen (Diff/Undo) und per Chat with Data befragen.
---

# EAM AI Suite Python — Open WebUI Skill

Nutze die Werkzeuge aus `eam_ai_suite_openwebui.py` verbindlich in dieser Reihenfolge,
sobald der Nutzer Architekturprosa modellieren oder ein bestehendes Modell (`.qea`,
`.xmi`, ArchiMate `.xml`, `.json`) pruefen, vergleichen, reparieren oder befragen will.

## Verbindliche Regeln

1. **Keine erfundenen Elemente oder Stereotype:** Alle Architektur-Aussagen stuetzen
   sich ausschliesslich auf Werkzeugausgaben (`<Paket>::<Element>` oder `job_id`).
2. **Erst pruefen, dann aendern:** Bei bestehenden Modellen immer zuerst `validate_and_qs`
   oder `ask_architecture` ausfuehren.
3. **Reparatur immer zuerst als Vorschau:** `repair_architecture(..., apply=False)` zeigt
   deterministische MDG-Korrekturen ohne KI; erst nach Rueckmeldung des Nutzers mit
   `apply=True` anwenden.
4. **Loeschungen bestaetigen lassen:** `edit_architecture(..., confirm_delete=True)` nur
   nach ausdruecklicher Freigabe.
5. **Downloads & Viewer immer mitliefern:** Nach jedem `build_architecture` die
   Links (`viewer`, `zip`, `handbuch`) und die `job_id` fuer Folgefragen nennen.

## Standard-Ablauf (7 Stufen)

1. **Bauen:** `build_architecture(prose_text=..., output_format="qea", views_mode="leitfaden")`
   (bei kleinen lokalen LLMs `context_tokens=8192` setzen).
2. **Pruefen & Textabdeckung:** `validate_and_qs(model_path_or_job_id=<job_id>)` —
   meldet MDG-Befunde, ArchiMate-3.2-Matrixverstoesse, Waisen und fehlende Quellbelege.
3. **Regelbasiert reparieren (ohne KI):** Falls Fehler vorliegen,
   `repair_architecture(<job_id>, apply=False)` vorschlagen und bei Zustimmung anwenden.
4. **Gezielt weiterbauen & vergleichen:** `edit_architecture(<job_id>, instruction=..., apply=False/True)`,
   anschliessend `diff_architectures(<job_id>)` zeigen; bei Fehlgriff `undo_architecture(<job_id>)`.
5. **Befragen (Chat with Data):** `ask_architecture(<job_id>, question=..., scope_kind="model|package|element")`
   und in der Antwort stets die zurueckgelieferten Quellen nennen.
