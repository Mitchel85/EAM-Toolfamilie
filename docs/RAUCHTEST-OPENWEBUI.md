# Rauchtest: Open-WebUI-Werkzeug ohne Open WebUI

Stand 24.10.2026. Geprüft wird die ausgelieferte Datei
`dist/eam_qea_analyzer_openwebui.py` — dieselbe Datei, die in Open WebUI unter
*Werkzeuge* abgelegt wird. Der Test braucht **keine** Open-WebUI-Installation,
keinen Container, kein Netz und kein LLM: er lädt die Datei als Python-Modul,
instanziiert die Klasse `Tools` und ruft die beiden Funktionen auf, die ein
Modell dort zuerst benutzt.

## Modell

Das Modell entsteht im Test aus dem IR-Writer des Monorepos
(`packages/core/qea_writer.py`), ist also reproduzierbar und enthält keine
echten Daten:

| Merkmal | Wert |
|---|---|
| Pakete | 4 (`Rauchtest55` + drei Fachpakete) |
| Fachliche Elemente | **55** — 22 `Capability`, 13 `System`, 10 `OperationalActivity`, 10 `Requirement` |
| Zeilen in `t_object` | 58 (55 Elemente + 3 Paketspiegel, EA-Konvention) |
| Kanten | 3 (`Realization`, `Provides`, `Satisfy`) |
| Sichten | 0 |

## Aufrufe und Ist-Werte

Beide Fassungen — Quelle `apps/mcp/eam_qea_tool.py` und Auslieferung
`dist/eam_qea_analyzer_openwebui.py` — liefern dasselbe Ergebnis; die Dateien
sind byte-identisch (SHA-256 `43614b24…`). Laufzeit je Aufruf: 1–2 ms.

| Aufruf | Ergebnis |
|---|---|
| `analyze_qea_statistics(qea_path=…)` | `Packages 4`, `Elements 58`, `Connectors 3`, `Diagrams 0` |
| `ElementTypes` | `Class 35`, `Activity 10`, `Requirement 10`, `Package 3` |
| `Stereotypes` | `Capability 22`, `System 13`, `Requirement 10`, `OperationalActivity 10` — Summe **55** |
| `find_elements_in_qea(stereotype="Capability")` | 22 Treffer, alle `Class`, Paket `01 Faehigkeiten` |
| `find_elements_in_qea(object_type="Activity")` | 10 Treffer, Stereotyp `OperationalActivity` |
| `find_elements_in_qea(object_type="Class", limit=200)` | 35 Treffer |
| `find_elements_in_qea(name="Faehigkeit 0")` | 9 Treffer (`Faehigkeit 01`…`09`) |
| `find_elements_in_qea()` ohne Filter | **50** Treffer (Vorgabe `limit=50`) |
| `find_elements_in_qea(limit=200)` | 58 Treffer |
| `find_elements_in_qea(stereotype="GibtEsNicht")` | 0 Treffer, keine Ausnahme |
| `get_element_detail_from_qea(element_id=36)` | `System 01`, 1 Kante ausgehend, 2 eingehend, 1 Tag |
| `analyze_qea_statistics()` **ohne** `qea_path` | findet `Rauchtest55.qea` selbst (Pakete 4, Elemente 58) |
| `list_available_qea_files()` | `["Rauchtest55.qea"]` |
| falscher `qea_path` | `{"error": "No file found matching the provided qea_path: …"}` |

## Befunde

1. **Die Zahl der Elemente hängt an der Zählweise.** `Elements` zählt Zeilen in
   `t_object` — inklusive der Paketspiegel, die Enterprise Architect und der
   Writer je Unterpaket anlegen. Ein Modell mit 55 fachlichen Elementen meldet
   deshalb 58; die Stereotypensumme ist die verlässliche Zahl der Elemente.
2. **Ohne `limit` bleiben Treffer liegen.** Die Werkzeugfunktion setzt
   `limit=50`, die Analyzer-Methode darunter `200`. Bei 58 Zeilen liefert der
   Aufruf ohne Argument also 50 Treffer. Wer die Vollständigkeit braucht, muss
   `limit` setzen — das Modell sieht die Kürzung nicht und kann daraus falsche
   Schlüsse ziehen.
3. **Auto-Erkennung funktioniert ohne Pfad.** Fehlt `qea_path`, durchsucht das
   Werkzeug seine Suchordner (`Valves.qea_search_dirs`, Vorgabe
   `/app/backend/data`) und nimmt die **zuletzt geänderte** Datei. Im Test
   zeigte der Valve auf den Testordner.
4. **Fehler kommen als JSON, nicht als Ausnahme.** Ein unbekannter Pfad oder ein
   fehlender Treffer führt zu `{"error": …}`; das Werkzeug bricht nicht ab.

## Wiederholen

```bash
cd <pfad-zum-repo>
python3 -m pytest tests/apps/test_openwebui_werkzeug.py -v
```

Der Test `test_ausgelieferte_fassung_ist_die_quelle` schlägt fehl, sobald
`dist/` und `apps/mcp/eam_qea_tool.py` auseinanderlaufen — dann fehlt
`python3 scripts/collect_releases.py`.

## Grenzen

- Geprüft ist der Werkzeugcode, nicht die Einbettung in Open WebUI (Schema-Export,
  Valve-Oberfläche, Rechte). Dafür braucht es eine laufende Instanz.
- Kein LLM im Spiel: der Test belegt, dass die Funktionen die richtigen Daten
  liefern, nicht wie ein Modell sie formuliert.
