---
# EA JavaScript-Rezepte (offizielle Samples → JS portiert + Praxis)

> Basis: offizielle Code-Samples („Add and Manage Packages/Elements/Connectors/Diagrams“, „Element Extras“, „Stereotypes“) aus dem EA-Objektmodell + Kilian/Bellekens-Praxis.
> Ausführung im EA-Scripting-Fenster (JavaScript-Gruppe). Skriptdatei: UTF-8 **mit BOM** speichern.

## Rezept 1: Modell + Unterpakete anlegen

```javascript
function addPackage(parentPkg, name, stereotype) {
    var pkg = parentPkg.Packages.AddNew(name, "");
    if (!pkg.Update()) { Session.Output("Pkg-Fehler: " + pkg.GetLastError()); return null; }
    parentPkg.Packages.Refresh();
    if (stereotype) {
        // Stereotyp liegt am zugehoerigen ELEMENT -> pkg.Element.Update(), NICHT pkg.Update()!
        pkg.Element.StereotypeEx = stereotype;
        if (!pkg.Element.Update()) { Session.Output("Pkg-El-Fehler: " + pkg.Element.GetLastError()); }
    }
    return pkg;
}

var model = Repository.Models.AddNew("ADMBw-Architektur", "");
model.Update();
Repository.Models.Refresh();
var view       = addPackage(model, "C1 - Capability Taxonomy", "");
var commonData = addPackage(model, "Common Data", "");
```

## Rezept 2: Element mit Stereotyp + Tagged Values

```javascript
function setTaggedValue(el, name, value) {
    var tv = null;
    for (var i = 0; i < el.TaggedValues.Count; i++) {
        var t = el.TaggedValues.GetAt(i);
        if (t.Name === name) { tv = t; break; }
    }
    if (!tv) { tv = el.TaggedValues.AddNew(name, ""); }
    tv.Value = String(value);
    tv.Update();
    el.TaggedValues.Refresh();
}

function addElement(pkg, name, type, stereo, tags) {
    var el = pkg.Elements.AddNew(name, type);
    if (!el.Update()) { Session.Output("El-Fehler: " + el.GetLastError()); return null; }
    if (stereo) { el.StereotypeEx = stereo; el.Update(); }
    if (tags) {
        // MDG-Stereotyp erzeugt Tags selbst -> vorhandene Tags AKTUALISIEREN, nicht duplizieren
        for (var k in tags) { setTaggedValue(el, k, tags[k]); }
    }
    pkg.Elements.Refresh();
    return el;   // ElementID + ElementGUID für spätere Verknüpfung merken
}

var cap = addElement(view, "Fähigkeitsbeispiel", "Class", "Capability", {MoE: "bewertet"});
var sub = addElement(view, "Sensornetz", "Class", "Capability");
```

## Rezept 3: Connector mit Metatyp + Stereotyp

```javascript
function findConnector(src, tgt, metaType, stereo) {
    for (var i = 0; i < src.Connectors.Count; i++) {
        var c = src.Connectors.GetAt(i);
        if (c.SupplierID === tgt.ElementID && c.Type === metaType) {
            if (!stereo || (c.Stereotype || '') === stereo || (c.StereotypeEx || '').indexOf(stereo) !== -1) {
                return c;
            }
        }
    }
    return null;
}

function addConnector(src, tgt, metaType, stereo) {
    var existing = findConnector(src, tgt, metaType, stereo);
    if (existing) return existing;   // Idempotenz: mehrfaches Laufen erzeugt keine Dubletten
    var con = src.Connectors.AddNew("", metaType);
    con.SupplierID = tgt.ElementID;
    if (stereo) con.StereotypeEx = stereo;
    if (!con.Update()) { Session.Output("Con-Fehler: " + con.GetLastError()); return null; }
    src.Connectors.Refresh();
    return con;
}

// „ist Teilfähigkeit von“ → Generalization «CapabilityGeneralization»
addConnector(sub, cap, "Generalization", "CapabilityGeneralization");
// „erfüllt“ → Dependency «Satisfy»
addConnector(cap, reqEl, "Dependency", "Satisfy");
```

## Rezept 4: Diagramm + Elemente platzieren

```javascript
function addDiagram(pkg, name, type) {
    var d = pkg.Diagrams.AddNew(name, type);
    if (!d.Update()) { Session.Output("Diag-Fehler: " + d.GetLastError()); return null; }
    pkg.Diagrams.Refresh();
    return d;
}

var diag = addDiagram(view, "C1 Übersicht", "??");   // MDG-Typ ermitteln, s.u.
var obj = diag.DiagramObjects.AddNew("l=120;r=320;t=120;b=240;", "");
obj.ElementID = cap.ElementID;
obj.Update();
diag.DiagramObjects.Refresh();
```

**MDG-Diagramm-Typ ermitteln** (einmalig): Manuell eine NAFv4/ADMBw-View anlegen, dann auslesen:

```javascript
Session.Output("MDG-Type: " + Repository.GetDiagramByID(<id>).Type);
```

## Rezept 5: Massenzählung (Verifikation)

```javascript
function sqlNumber(sql, label) {
    var res = Repository.SQLQuery(sql);
    // EA-Format: <EADATA><Dataset><Data><Row><ALIAS>wert</ALIAS></Row>… — KEIN <Value>-Tag,
    // KEIN '-1-'-Trenner. Erstes <ALIAS>zahl</ALIAS> im ersten Row-Block ist die Antwort.
    var m = String(res).match(/<([A-Za-z0-9_]+)>\s*(-?\d+)\s*<\/\1>/);
    if (m) return parseInt(m[2], 10);
    // Fallback nur fuer skalare Treiberantworten (kein XML):
    if (String(res).indexOf('<') === -1) {
        var n = String(res).replace(/[^0-9-]/g, '');
        if (n !== '' && !isNaN(parseInt(n, 10))) return parseInt(n, 10);
    }
    // Fehler-/leeres Resultset = Fehler, NICHT 0:
    if (label) Session.Output('!!  ' + label + ': Ergebnis nicht als Zahl lesbar');
    return -1;
}
var n = sqlNumber("SELECT COUNT(*) AS C FROM t_object WHERE Stereotype = 'Capability'", "Capabilities");
Session.Output("Capabilities: " + n);
```

## Rezept 6: Massen-Update (Batch)

```javascript
Repository.BatchAppend = true;
Repository.EnableUIUpdates = false;
// ... Schleife mit AddNew/Update ...
Repository.BatchAppend = false;
Repository.EnableUIUpdates = true;
```

## Rezept 7: Idempotenz-Schutz

```javascript
function addElementIdem(pkg, spec) { /* findElement zuerst, dann addElement */ }
function findElement(pkg, name, type) {
    for (var i = 0; i < pkg.Elements.Count; i++) {
        var e = pkg.Elements.GetAt(i);
        if (e.Name === name && (type === undefined || e.Type === type)) return e;
    }
    return null;
}

// Batch: nur fuer reine Massen-Inserts. Wenn im selben Lauf Connectors per
// ElementID verknuepft werden: BatchAppend VOR Connector-Phase auf false
// (sonst kann ElementID noch 0 sein).
```

## Pitfalls (Praxis)

- **Umlaute**: Datei UTF-8 mit BOM; sonst „Ã¶“-Artefakte im Scriptfenster.
- **`GetAt`-Schleifen**: Referenz einmal holen (lädt sonst bei jedem Zugriff neu).
- **`StereotypeEx`** statt `Stereotype` bei MDG-Standard-Stereotypen; bei Mehrfach-Stereotypen `Ex` Pflicht.
- **`DeleteAt(idx, false)`** — zweiten Parameter beachten; danach `Refresh()`.
- **`SQLQuery`-XML**: Für Zählungen `COUNT(*) AS C` im SQL verwenden und den `<C>`-Wert per Alias-Regex auslesen — **kein** `<Value>`-Knoten (der existiert nicht), **kein** `-1-`-Trenner. Fehler-/leeres Resultset als Fehler melden, nie als 0 zählen.
