# Kanban — BPMN Nachtlauf (04./05.11.2026)

Tafel: dieses Dokument. Fortschritt wird von jedem Lauf unten eingetragen.
Plan: `docs/plans/2026-11-04-bpmn-nachtlauf.md`

| Karte | Inhalt | Status | Lauf | Beleg |
|---|---|---|---|---|
| K1 | Regelauszug BPMN→ADMBw (`knowledge/bpmn/prozess-regeln.json`) | erledigt | 1 | `scripts/build_bpmn_regeln.py`, `tests/bpmn/test_regeln.py` |
| K2 | Datenmodell + BPMN-2.0-XML (`packages/bpmn/`) | erledigt | 1 | `packages/bpmn/modell.py`, `bpmn_xml.py`, `tests/bpmn/test_bpmn_xml.py` |
| K3 | SVG/PNG-Export, deterministisch | erledigt | 1 | `packages/bpmn/exporte.py`, `tests/bpmn/test_exporte.py` |
| K4 | ADMBw-Mapping, L4-MK-Prüfung, „konform machen" | erledigt | 1 | `packages/bpmn/admbw.py`, `tests/bpmn/test_admbw.py` |
| K5 | Prosa-Extraktion + optionaler KI-Adapter | erledigt | 2 | `packages/bpmn/extraktion.py`, `ki.py`, `tests/bpmn/test_extraktion.py` |
| K6 | `.qea`-Brücke über `qea_writer.py` | erledigt | 2 | `packages/bpmn/qea_bpmn.py`, `tests/bpmn/test_qea_bpmn.py` |
| K7 | HTML-Studio, Einzeldatei, offline | erledigt | 2 | `apps/bpmn-studio/`, `tests/test_bpmn_studio.py` |
| K8 | Austauschtest (XSD, bpmn.io, ARIS, EA) | erledigt | 3 | `docs/BPMN-KOMPATIBILITAET.md`, `tests/bpmn/test_austausch.py` |
| K9 | Doku, Auslieferung, Release 3.14.0 | erledigt | 3 | `README.md`, `scripts/collect_releases.py` |

## Läufe

| Lauf | Cron-Job | Start (UTC) | Zustand |
|---|---|---|---|
| 1 | `9447316968a7` | 04.11. 20:32 | abgeschlossen |
| 2 | `121b9a694332` | 04.11. 23:28 | abgeschlossen |
| 3 | `9574697975c` | 05.11. 02:28 | abgeschlossen |
