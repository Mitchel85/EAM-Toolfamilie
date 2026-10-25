---
# EA API-Referenz (kondensiert, EA 17.x — offiziell verifiziert)

> Quelle: Sparx „Enterprise Architect Object Model“ (17.1, 364 S.) + „Scripting“-User-Guide.
> Volltext-Quelle bei Bedarf: /tmp/sparx_docs/ea_object_model.txt (15.388 Zeilen Text).

## Sprache & Laufzeit

- Scripting-Window: **JavaScript**, **JScript**, **VBScript** (Skript-Gruppen-Typ wählbar; Konsole: JA=JavaScript, JS=JScript)
- Eingebaut: **`Repository`** (immer) und **`Session`** (Output/Prompt/Input)
- `Session.Output(text)` → System-Output-Tab „Script“
- `Session.Prompt(msg, promptYESNO)` → Ergebnis `resultYes` / `resultNo`
- `!include`-Directive zum Einbinden anderer Skripte (Bellekens: `!INC Wrappers.Include`)
- Debugging im Scriptfenster ist print-basiert → nach jedem Block `Session.Output`

## Repository (Einstieg)

| Member | Zweck |
|---|---|
| `Models` | Collection der Top-Level-Modelle; `Models.AddNew(name, "")` + `Update()` + `Refresh()` |
| `GetPackageByID(id)` / `GetPackageByGuid(guid)` | Package direkt laden |
| `GetElementByID(id)` / `GetElementByGuid(guid)` | Element direkt laden |
| `GetConnectorByID(id)` / `GetConnectorByGuid(guid)` | Connector direkt laden |
| `GetTreeSelectedObject()` / `GetTreeSelectedItemType()` | Browser-Auswahl (Typ: `ot*`-Enum) |
| `SQLQuery(sql)` | Schnelle Abfrage; Ergebnis als XML-String `<EADATA><Dataset><Data><Row><ALIAS>wert</ALIAS></Row>…` — KEIN `-1-`-Zeilen-Trenner, KEIN CLASSGUID-Zwang |
| `BatchAppend` (Boolean) | true = schneller Massen-Insert |
| `EnableUIUpdates` (Boolean) | false während Builds, am Ende wieder true |
| `OpenFile(path)` / `Exit()` | VON AUSSEN (COM) |

## Package

- `Package.Packages` / `Package.Elements` / `Package.Diagrams` — Collections
- Unterpaket: `pkg.Packages.AddNew(name, "")`; neues Top-Level-Modul: `Repository.Models.AddNew(name, "")` (ParentID=0)
- `Package.Name`, `Package.Notes`, `Package.ParentID`, `Package.Element` (zugehöriges Element; `pkg.Element.Stereotype = "..."` möglich)
- `Package.IsModel` (read-only)

## Element

| Property | Bemerkung |
|---|---|
| `Element.Type` | EA-Typ-String, z.B. `Class`, `Object`, `Activity`, `Requirement`, `Package`, `Text`, `UseCase`, `Component`, `Node`, `Part`, `Slot`, `Action`, `StateMachine`, `DataType`, `Port` … |
| `Element.Name` | Name (EA erlaubt Duplikate → GUIDs nutzen!) |
| `Element.Stereotype` / `Element.StereotypeEx` | Stereotyp; `Ex` = mehrere (Komma-getrennt); MDG-Stereotype nur wenn Technologie aktiv |
| `Element.Alias`, `Element.Notes`, `Element.Author`, `Element.Complexity`, `Element.Status` | Metadaten |
| `Element.ElementID` / `Element.ElementGUID` | Identität — GUID nach Erstellung sofort merken |
| `Element.PackageID` | Zugehöriges Package |
| `Element.TaggedValues` | `AddNew(name, value)` → Update → Refresh |
| `Element.Connectors` | Verbindungen (siehe Connector) |
| `Element.Attributes` / `Element.Methods` | Features |
| `Element.Constraints` / `Element.Scenarios` / `Element.Risks` / `Element.Metrics` | Extras (AddNew→Update→Refresh→DeleteAt) |

**Anlegen:** `pkg.Elements.AddNew(name, type)` → Properties → `element.Update()` → `pkg.Elements.Refresh()`

## Connector

| Member | Zweck |
|---|---|
| `src.Connectors.AddNew(name, type)` | `type` = EA-Metatyp: `Association`, `Dependency`, `Generalization`, `Abstraction`, `Realisation`, `InformationFlow`, `Aggregation`, `Composition`, `ControlFlow`, `ObjectFlow`, `Message`, `Signal`, `Connector`, `NoteLink` … |
| `con.SupplierID` | Ziel-ElementID (MUSS gesetzt werden!) |
| `con.ClientID` | Quell-ElementID |
| `con.StereotypeEx` | Stereotyp (z.B. `AchievedEffect`, `Satisfy`, `Implements`) |
| `con.ClientEnd` / `con.SupplierEnd` | Rollen: `Visibility`, `Role`, `Aggregation` → `Update()` je Ende |
| `con.ConnectorID` / `con.ConnectorGUID` | Identität |

**Anlegen:** `con = src.Connectors.AddNew("", "Dependency")` → `con.SupplierID = tgt.ElementID` → `con.StereotypeEx = "..."` → `con.Update()` → `src.Connectors.Refresh()`

## Diagram

- `pkg.Diagrams.AddNew(name, type)` — `type` = Diagrammtyp-String: Standard (`Logical`, `Class` …) oder **MDG-Typ** (NAFv4/ADMBw: exakten Typ einmal per GUI erzeugen und via `diag.Type` auslesen!)
- `diag.DiagramObjects.AddNew("l=200;r=400;t=200;b=600;", "")` → `obj.ElementID = elem.ElementID` → `obj.Update()` → `diag.DiagramObjects.Refresh()`
- `diag.DiagramLinks` für Connector-Sichtbarkeit; `diag.DiagramID` merken

## Collection-Idiom

```javascript
var c = pkg.Elements;
for (var i = 0; i < c.Count; i++) {
    var e = c.GetAt(i);   // NICHT mehrfach GetAt() — lädt jedes Mal neu (offizieller Hinweis)
    ...
}
c.AddNew(name, type)
c.DeleteAt(idx, refresh)
c.Refresh()
```

## Enums (Auszug)

- `ObjectType`: `otElement`, `otPackage`, `otAttribute`, `otMethod`, `otConnector`, `otDiagram` …
- `Session.Prompt`: `promptYESNO` → `resultYes` / `resultNo`

## SQLQuery-Pattern

```javascript
var sql = "SELECT ea_guid, Object_ID, Name, Object_Type, Stereotype " +
          "FROM t_object WHERE Stereotype = 'Capability'";
var res = Repository.SQLQuery(sql);   // XML-String: <EADATA><Dataset><Data><Row><ea_guid>…</ea_guid></Row>…
```

## Externe COM (außerhalb EA, Windows)

```javascript
var ea = new ActiveXObject("EA.Repository");
ea.OpenFile("C:\\Pfad\\Modell.qea");
...
ea.Exit();
```

## Merkregeln

- `Update()` immer NACH allen Property-Setzungen; nach Stereotyp-/Tag-Änderungen erneut `Update()`.
- Refresh IMMER auf der Parent-Collection (`pkg.Elements.Refresh()`), nicht auf dem Objekt.
- Fehler: `obj.GetLastError()` ausgeben.
