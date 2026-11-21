# Kanban-Nachtlauf: BMC — BPMN Model Converter (ADMBw-konforme Prozess-Extraktion)

## Auftrag (vom Nutzer, 04.11.2026)

Neues Werkzeug in der EAM-Toolfamilie: Prozesse **extrahieren, anzeigen, editieren,
exportieren** — BPMN 2.0 konform, NAF-konform, ADMBw-konform, leitfarbenkonform.
Zwei Anwendungen: **Python** und **HTML** (Einzeldatei, offline, wie die übrige Familie).
Optional KI über API. Exporte: **BPMN-XML, SVG, PNG**. Kompatibel zu **bpmn.io (bpmn-js)**,
**ARIS** und **Sparx EA**. Baut in einem Nachtlauf, morgens fertig.

## Harte Randbedingungen

- Repository: `/root/hermes-workspace/eam-platform` (Monorepo, Branch `main`).
- **Kein `codex` auf diesem Host** (`command -v codex` leer). Arbeit über Hermes-Agenten
  (`delegate_task`) und direkte Umsetzung. Die Skill `kanban-codex-lane` beschreibt die
  Gegenprobe; hier entfällt die Codex-Lane, das wird im Bericht festgehalten.
- **Keine dienstlichen, vertraulichen oder personenbezogenen Inhalte** an externe
  Modell-Endpunkte. KI-Funktion nur als **optionaler, konfigurierbarer** Baustein; im
  Testbetrieb ausschließlich mit erfundenen Beispieldaten.
- **Marken:** In Auslieferungen kein „Sparx" im Produktnamen. bpmn-js ist MIT-lizenziert
  und darf gebündelt werden (Lizenztext mitliefern); der Name bpmn.io darf als
  Kompatibilitätshinweis genannt werden, nicht als Produktname.
- **Keine Netzabhängigkeit der HTML-Fassung.** Einzeldatei, läuft offline.
- Tests müssen grün sein, CI muss grün sein, Release über Tag `v*`.

## Wissensbasis im Repo (zuerst lesen, nicht raten)

- `knowledge/regelwerk.json` — 54 Viewpoints, MDG-Stereotype, Konnektoren, Prüftabellen.
- `packages/core/regelwerk.py` — `lade()`, `viewpoint()`, `stereotype()`.
- `knowledge/leitfaden/pruefung.json` — 43 Pakete / 41 Sichten / 20 Pflichtstereotype.
- Quellen (nicht im Repo): `/root/eam-quellen/leitfaden-ffmlv-v2.0.txt` — maßgeblich.
  Besonders die Konventionen **L4-MK01 … L4-MK20** (Business Process Diagram als
  BPMN-Kollaborationsdiagramm, Pools/Lanes, Aktionen, Gateways, Kontrollfluss,
  Conveyed Items) sowie `admbw-dokumentation.txt` und `grundlagen-nafav4.txt`.
- MDG-Stereotype für Prozesse (aus `ADMBw-Stereotypes.json`, 2026.05, geprüft):
  - `OperationalActivityAction` → UML `Action` (nicht abstrakt)
  - `OperationalControlFlow` → UML `ControlFlow` (nicht abstrakt)
  - `OperationalMessageFlow` → UML `ControlFlow` (nicht abstrakt)
  - `OperationalObjectFlow` → UML `ObjectFlow` (nicht abstrakt)
  - `OperationalActivity` → UML `Activity` (nicht abstrakt)
  - `OperationalPerformer` → UML `Class` (nicht abstrakt)
  - abstrakt (nicht instanziieren, aber als Typ erlaubt): `OperationalActivityEdge`,
    `ExchangeItem`, `OperationalExchangeItem`, `BusinessProcess`, `OperationalAgent`
- Exportziel `.qea`: `packages/core/qea_writer.py` bereits vorhanden — wiederverwenden.

## Architektur (Vorschlag, darf begründet abweichen)

```
packages/bpmn/                    # reine Python-Bibliothek, keine UI
  modell.py        # Datenmodell: Process, Pool, Lane, Node, Edge, Exchange
  bpmn_xml.py      # Lesen/Schreiben BPMN 2.0 XML (DI enthalten)
  admbw.py         # Mapping BPMN <-> ADMBw-Stereotype + L4-MK-Prüfungen
  extraktion.py    # Aus Prosa/Text Prozessschritte + Akteure ziehen (regelbasiert)
  ki.py            # optionaler KI-Adapter (OpenAI-kompatibel, konfigurierbar, aus per Default)
  exporte.py       # SVG (deterministisch), PNG (via rsvg/cairosvg oder Pillow)
  qea_bpmn.py      # Brücke zum vorhandenen qea_writer
apps/bpmn-studio/               # HTML-Einzeldatei
  index.html, src/*.js, build.py, app.json
```

HTML-Fassung: Editor auf Basis von bpmn-js (MIT) gebündelt, Panel „ADMBw-Prüfung",
Knopf „ADMBw-konform machen", Export XML/SVG/PNG, optionaler KI-Schalter.

## Kanban-Karten (Reihenfolge)

| # | Karte | Ergebnis |
|---|---|---|
| K1 | Recherche und Regelauszug | Prozess-regelwerk.json (BPMN→ADMBw-Abbildung, L4-MK-Prüfregeln), Quellen zitiert |
| K2 | Datenmodell + BPMN-XML | Lesen/Schreiben BPMN 2.0, Roundtrip-Test byte-stabil |
| K3 | SVG/PNG-Export | deterministisch, ohne Browser, Goldenfile-Test |
| K4 | ADMBw-Mapping + Prüfung | L4-MK-Checks als Befunde, „konform machen" als Transformation |
| K5 | Prosa-Extraktion | regelbasiert (Schritte erkennen), KI-Adapter optional |
| K6 | `.qea`-Brücke | Prozess als Elemente/Konnektoren schreiben, Test gegen Fixture |
| K7 | HTML-Studio | Einzeldatei, Editor, Prüf-Panel, Exporte, offline |
| K8 | Austauschtest | bpmn.io-Validierung, ARIS-EPC-Import-Sicht, EA-Import-Notiz |
| K9 | Doku + Release | README, Anleitung, START-HIER, Release-Tag |

## Abnahme (nicht verhandelbar)

1. `pytest` im Repo grün, **neue Tests** für jede Karte.
2. BPMN-XML validiert gegen das offizielle XSD (Schema-Prüfung, nicht nur „öffnet").
3. Roundtrip: BPMN → intern → BPMN → intern, kein Verlustsemantik.
4. SVG/PNG erzeugt, im Browser und mit `vision_analyze` gesichtet.
5. HTML-Einzeldatei: öffnet offline, lädt/speichert, **0 externe Requests**.
6. CI grün auf frischem Klon, Release mit Tag.
7. Bericht: was gebaut, was geprüft, **was nicht geht und warum**.

## Ehrlichkeitsregeln

- Kein Kartenstatus „fertig" ohne Testbeleg.
- ARIS-Kompatibilität nur behaupten, soweit belegt (Import-Sicht, Dokumentation).
  Wenn ARIS ein eigenes Format verlangt: sagen, nicht schmücken.
- KI ohne Backend muss sauber abschalten (kein stiller Fehlschlag).
