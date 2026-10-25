---
name: eam-ai-admbw-script-maker
description: "Use when generating Sparx EA JS to build ADMBw from prose."
---

# EA-Scripting — Prosa → EA-JavaScript → ADMBw-Architektur

## When to Use

- User will eine Architektur aus deutscher Prosa automatisiert in Sparx Systems Enterprise Architect erzeugen (Prosa → Skript → Architektur)
- User braucht **ADMBw/NAFv4-konforme Elemente, Beziehungen, Diagrams** per Skript (Batch/Massendatenänderungen mit Funktionen)
- Code-Generierung, Konsistenz-Checks, Massenimport in ein EA-Repository
- Vorstufe zur Verifikation: Element-/Connector-Zählung per Skript (immer nach Write re-readen)

## Pipeline (Kern-Auftrag)

```
Architekturprosa (deutsch)  →  Parser → IR-JSON  →  EA-JavaScript-Generator  →  Scripting-Fenster  →  Repository  →  Verify-Skript  →  Report
        │
        └─ Nutze vorhandenen Parser + Muster: Skill prose-to-qea (12 Element-/16 Beziehungsmuster, MASC-gelernt)
```

## EA-Scripting-Fakten (offiziell, EA 17.x)

- Scripting-Fenster unterstützt **JavaScript**, **JScript**, **VBScript** (Pro Group-Typ)
- Jedes Skript hat ein **eingebautes `Repository`-Objekt** (Einstieg: Models, GetPackageByID, GetElementByID, SQLQuery …)
- Eingebautes **`Session`-Objekt**: `Session.Output(text)` → System-Output-Tab; `Session.Prompt(msg, promptYESNO)` → `resultYes`/`resultNo`; Konsolen: JA = JavaScript, JS = JScript, `?name` gibt Variablenwert aus
- **`!include`-Directive** importiert andere Skripte (`!INC Wrappers.Include` bei Bellekens-Bibliothek)
- Skript-Gruppen mit Typ (JS/JA/VBS) — pro Gruppe wird ein Template angezeigt
- Output erscheint im **System Output → 'Script'-Tab**

## API-Goldene Regeln (aus offiziellem Objektmodell + Praxis)

1. **AddNew → Properties setzen → Update() → Refresh() der Parent-Collection** — ohne Refresh sehen nachfolgende AddNew-Aufrufe das neue Element nicht (offizielles Sample-Verhalten).
2. **`Update()`-Rückgabe prüfen** — bei `false` via `GetLastError()` den Grund ausgeben (häufigste Fehler: Pflichtfelder fehlen / Duplikat-Name).
3. **Collections nur einmal laden, in lokale Variable legen** — offizieller Hinweis: `GetAt(idx)` lädt das Objekt bei JEDEM Aufruf neu.
4. **IDs nie raten**: nach `AddNew`+`Update` die neue `ElementID`/`PackageID`/`ConnectorID` aus dem Objekt lesen — GUIDs via `ElementGUID` sichern (Import-Idempotenz!).
5. **Massendaten**: `Repository.BatchAppend = true` und `Repository.EnableUIUpdates = false` für Geschwindigkeit (am Ende zurücksetzen).
6. **Stereotype**: `Element.StereotypeEx` (mehrere durch Komma), MDG-Stereotype nur setzen, wenn MDG-Technologie aktiv ist.
7. **Tagged Values**: `Element.TaggedValues.AddNew(name, value)` → `Update()` → `Refresh()`.
8. **Diagramme**: `Diagram.Type` = genauer Diagramm-Typ-String — für MDG-Views den Typ **einmal manuell erzeugen und per Skript auslesen** (Diag.Type), dann im Generator verwenden.
9. **Langsame Muster**: `Repository.SQLQuery` liefert XML `<EADATA><Dataset><Data><Row><ALIAS>wert</ALIAS></Row>…` — **kein** `-1-`-Trenner und **kein** CLASSGUID-Zwang; Parser-Muster siehe `templates/verify_model.js` (`sqlNumber`). Fehler-/leere Resultsets sind Fehler, nie Zählwert 0.
10. **Idempotenz**: Vor `AddNew` immer nach vorhandenem Namen suchen — Skript muss mehrfach laufen können, ohne Duplikate zu erzeugen.

## Verifikation (Pflicht nach jedem Write)

1. **Re-Read**: Zählung per SQLQuery — Elemente je Stereotyp, Connectors je Typ, Diagramme je View (Soll vs. Ist).
2. **Sollwerte**: Im Template `templates/verify_model.js` den `EXPECTED`-Block aus dem IR füllen:
   - `elements`/`connectors`/`diagrams`: **`null` = kein Sollwert** (nur Ist-Zählung `--`, keine Bestätigung), **`0` = harte Null** (IST > 0 ⇒ FAIL), sonst Anzahl.
   - `stereotypes`: Map `Stereotyp -> Anzahl`; **nur** genannte Stereotype werden geprüft (keine hartkodierte Checkliste).
3. **Urteil**: `VERIFY: FAIL` sobald ein Sollwert abweicht oder ein SQL-Ergebnis unlesbar ist (auch leeres Resultset = Fehler, nie „OK 0“). `VERIFY: PASS (nur geprüfte Sollwerte …)` — ohne gesetzte Sollwerte ist das eine reine Zählung, **keine** Erfolgsgarantie.
4. **Immer SOLL 0**: Referenzintegrität (ungültige Endpunkte) + doppelte GUIDs über `t_object` **und** `t_connector`.
5. **Nach Report nie „alles grün“ behaupten ohne Re-Read-Nachweis** (vgl. KDP-Lektion 2026-09: kaputtes Ergebnis sah „fertig“ aus).

## ADMBw / NAFv4

- Wissensbasis (318 Katalog-Stereotype, 203 Topologie-Regeln, 133 vollständige Kanten, 52 Viewpoints, EA-Metatypen) = `references/admbw-knowledge-*.md` — automatisch generiert aus der offiziellen MDG 2026.05 via Mitchel85/EAM-ADMBw-MDG-Parser
- MDG: **NAF_V4/ADMBw muss aktiv sein** (EA 15.1+; bei Mitch EA 17.x + MDG installiert ✓).
- NAFv4 = UML-Erweiterung: MODEM-Elemente = UML-Klasse mit `«Stereotyp»` + Tagged Values; Canonical-Defs in „Common Data“-Packages, Views referenzieren sie (Reuse-through-Reference!).

## Referenzen

- `references/ea-api-reference.md` — kondensiertes offizielles Objektmodell (Repository/Package/Element/Connector/Diagram/Collection, Enums, Fakten)
- `references/ea-code-recipes.md` — JS-Rezepte (offizielle Samples nach JS portiert + Bellekens/Kilian-Muster)
- `references/admbw-knowledge-stereotypes.md` — **318 Katalog-Stereotype mit AppliesTo** (293 nutzbar, 44 abstrakt; MDG 2026.05, generiert via Mitchel85/EAM-ADMBw-MDG-Parser)
- `references/admbw-knowledge-connectors.md` — **EA-Metatyp → Stereotyp-Brücke** (Dependency/Class/Object/Part/…) + 53-Viewpoint-Liste
- `references/admbw-knowledge-topology.md` — Source → Connector → Target-Regeln (Metaconstraints)
- `references/admbw-knowledge-viewpoints.md` — 52 Viewpoints mit MDG-Beschreibung
- `references/admbw-knowledge-stereotype-tags.md` — 225 konkrete Tags an 66 Stereotypen (Typ, erlaubte Werte, Default)
- `references/admbw-prompt.md` — gemeinsamer Prompt-Kern (Auftrag, eiserne Regeln, Ausgabeformat, Dateiverzeichnis)
- `references/admbw-meta.md` — MDG-Version, Extraktionszeit, Kennzahlen
- `references/admbw-extractor-system-prompt.md` — kompletter Extractor-Prompt v7.1 (4 Modi + 9 Checks, Abstrakt-Auflösung; Sync aus dem Extractor-Repo)
- `templates/ea_jscript_skeleton.js` — Grundgerüst (Reporting, try/catch, Helpers)
- `templates/create_model_from_ir.js` — IR→Repository-Builder (Package/Element/Connector, idempotent + Sync bestehender Objekte; Diagramme legt der Builder **bewusst nicht** an — MDG-Diagrammtyp einmal in EA auslesen und manuell anlegen)
- `templates/verify_model.js` — Re-Read-Verifikation mit Soll/Ist-Abgleich (EXPECTED aus dem IR; null/0-Semantik) + Report
- `tests/run_tests.js` + `tests/mock_ea.js` — Node-Testsuite gegen In-Memory-EA-Mock (`node tests/run_tests.js`, Exit 0 = grün)

## Offizielle Quellen

- Objektmodell (364 S.): https://sparxsystems.com/resources/user-guides/17.1/automation/enterprise-architect-object-model.pdf
- Scripting-User-Guide: https://sparxsystems.com/enterprise_architect_user_guide/17.1/add-ins___scripting/the_scripter_window.html
- ADMBw-Profil (Bw, 2026.05): https://www.bundeswehr.de/resource/blob/5572728/2df2e5da515c496b11d88588ed46443f/dokumentation-admbw-en-data.pdf
- NAFv4-MDG: https://www.sparxsystems.eu/third-party-extensions-for-enterprise-architect/addins-for-sparxsystems-uml-tool/mdg-technology-naf-v4
- Bücher/Praxis: Thomas Kilian „Scripting Enterprise Architect“ (Leanpub), Geert Bellekens Enterprise-Architect-VBScript-Library (GitHub, Patterns), Sparx-Webinar „Introduction to Scripting using EA“

## Pitfalls

- **Zivil-Begriffe vermeiden**: ADMBw-Modellierung braucht Bw-Wording (Organisationsbereich, Bedarfsträger, Leitungsebene) — nicht Unternehmens-/Stakeholder-Sprache (vgl. MVA-Framework).
- **MDG-Diagramm-Typ**: „Logical“ usw. sind Standard; MDG-Views brauchen den echten Typ-String — nicht raten, einmal auslesen.
- **Doppelte Namen**: EA erlaubt meist Duplikate — Generator MUSS auf GUID sichern, nicht auf Namen. Der Builder nutzt **paketqualifizierte Identität** (Paket + Elementname); Duplikate im selben Paket werden als `EL DUBLETTE` gemeldet (zweite Spezifikation überschreibt per Sync), gleiche Namen in verschiedenen Paketen verdrahten keine falschen Connectors.
- **Umlaute in Skripten**: Skript-Dateien als UTF-8 mit BOM speichern (EA-Scriptfenster), sonst Encoding-Artefakte.
- **ES5-konform bleiben** (`var`, `function`), kein exotisches modernes JS im EA-Script-Fenster.

## Review-Fixes (EAP-Modell-Review 07.09.2026 — verifiziert gegen EA-17-API + ADMBw-KB)

1. **Paket-Stereotyp: IMMER `pkg.Element.Update()`** — `pkg.Update()` speichert Änderungen am zugehörigen Element (Stereotyp!) nicht. (CRITICAL)
2. **`Repository.SQLQuery()` liefert KEIN `<Value>`-XML** — Format: `<row><ALIAS>wert</ALIAS>…</row>`. Parser muss Alias/Generik nutzen (siehe `verify_model.js` `sqlNumber`). Ein Regex auf `<Value>` liefert still 0 → Verifikation wäre nutzlos. (CRITICAL)
3. **Connector-Idempotenz**: Vor `AddNew` Existenzprüfung (SupplierID + Type + Stereotype) — sonst Dubletten bei Wiederholungsläufen. (MAJOR)
4. **Paketübergreifende Connectors**: IR-Build in ZWEI Phasen (erst ALLE Elemente, dann Connectors, globaler Element-Cache) — Connector zwischen Paket A und B sonst unmöglich. (MAJOR)
5. **Tagged Values bei MDG-Stereotypen**: MDG erzeugt Tags automatisch → vorhandenen Tag per Name suchen und `Value` setzen, NIE blind `AddNew` (Dubletten). (MAJOR)
6. **Element- vs. Connector-Metatyp strikt trennen**: `Connectors.AddNew(name, "Class")` ist ungültig! Element-Stereotype gehören zu `Element.Type` (Class/Object/Activity/…), Connector-Stereotype zu `Connector.Type` (Dependency/Abstraction/Generalization/…). (MAJOR — Tabelle in `admbw-knowledge-connectors.md` entsprechend geteilt)
7. **SQL-Subqueries brauchen Alias** (`… ) AS DupTable`) — Access/.eap und PostgreSQL werfen sonst Syntaxfehler. (MINOR)
8. **`BatchAppend=true` + ID-Referenzierung im selben Lauf ist riskant**: `ElementID` kann 0 liefern → vor Connector-Phase `BatchAppend=false`. (MINOR)
