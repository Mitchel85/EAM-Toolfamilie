# Beispiel-Prosa → IR → EA-Skript (Testlauf für Enterprise Architect 17.x)

Diese Beispielkette dient als **Laufbeweis**: Sie zeigt die vollständige Pipeline
von einem Stück Architektur-Prosa bis zum fertigen, ausführbaren EA-Skript.

## 1 · Prosa (Eingabe für das LLM)

> Das Unternehmen betreibt ein Verteilzentrum in Hamburg und einen Kühlbereich in Hannover.
> Das Verteilzentrum ist verantwortlich für die Kühllogistik. Beide Standorte sind über
> die Lieferkette miteinander verbunden. Die Kühllogistik stellt das Serviceangebot
> „Temperaturgeführte Lieferung" bereit.

## 2 · IR-JSON (Ausgabe des LLM, Eingabe des Skripts)

Siehe [`ir_beispiel.json`](ir_beispiel.json).

## 3 · Fertiges EA-Skript

Siehe [`build_skript.js`](build_skript.js) — das ist `templates/create_model_from_ir.js`
mit eingebettetem IR-Beispiel.

## So prüfst du den Lauf (ca. 10 Minuten)

1. Sparx EA 17 öffnen (MDG NAFv4/ADMBw aktiv — einmal `Tools → MDG Technologies` prüfen).
2. `Tools → Scripting` (Gruppe **JavaScript**), neues Skript anlegen.
3. Inhalt von [`build_skript.js`](build_skript.js) einfügen, speichern.
4. Skript ausführen (Rechtsklick → `Run Script`).
5. `System Output → Script`-Tab: die Zeilen ab `=== BUILD START ===` bis `=== BUILD ENDE ===` kopieren.
6. Inhalt von [`../templates/verify_model.js`](../templates/verify_model.js) in ein zweites Skript einfügen — **vorher den `EXPECTED`-Block mit den Sollwerten aus dem IR füllen**: `elements: 3`, `connectors: 2`, `stereotypes: { "Node": 2, "ServiceSpecification": 1 }` (Sollwerte aus `ir_beispiel.json`). Ohne Sollwerte liefert Verify nur Ist-Zählungen (`--`) und **kein** PASS-Urteil.
7. Den `--- VERIFY REPORT ---`-Block ebenfalls kopieren.

**Beide Ausgaben an Michael schicken.** Erwartung: 1 Paket, 3 Elemente, 2 Connectors, `VERIFY: PASS`, 0 Fehlerzeilen.
