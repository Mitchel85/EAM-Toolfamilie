/*
 * EA-JavaScript-Grundgerüst (Scripting-Fenster, Gruppe: JavaScript)
 * Review-Fixes (EAP 07.09.): pkg.Element.Update(), findConnector-Idempotenz,
 * setTaggedValue (MDG-Dubletten vermeiden), BatchAppend-Hinweis.
 * Nachtlauf 19.10.2026: addPackage idempotent (Namenssuche + Stereo-Sync).
 */

function log(msg) { Session.Output(msg); }

function addPackage(parentPkg, name, stereo) {
    for (var i = 0; i < parentPkg.Packages.Count; i++) {
        var p = parentPkg.Packages.GetAt(i);
        if (p.Name === name) {
            if (stereo && p.Element.StereotypeEx !== stereo) {
                p.Element.StereotypeEx = stereo;
                if (!p.Element.Update()) { log("PKG EL FEHLER " + name + ": " + p.Element.GetLastError()); }
            }
            return p;
        }
    }
    var pkg = parentPkg.Packages.AddNew(name, "");
    if (!pkg.Update()) { log("PKG FEHLER " + name + ": " + pkg.GetLastError()); return null; }
    parentPkg.Packages.Refresh();
    if (stereo) {
        // Stereotyp liegt am zugehoerigen ELEMENT -> pkg.Element.Update(), nicht pkg.Update()!
        pkg.Element.StereotypeEx = stereo;
        if (!pkg.Element.Update()) { log("PKG EL FEHLER " + name + ": " + pkg.Element.GetLastError()); }
    }
    return pkg;
}

function findElement(pkg, name) {
    for (var i = 0; i < pkg.Elements.Count; i++) {
        var e = pkg.Elements.GetAt(i);
        if (e.Name === name) return e;
    }
    return null;
}

function addElement(pkg, name, type, stereo) {
    var existing = findElement(pkg, name);
    if (existing) { log("übersprungen (existiert): " + name); return existing; }
    var el = pkg.Elements.AddNew(name, type);
    if (!el.Update()) { log("EL FEHLER " + name + ": " + el.GetLastError()); return null; }
    if (stereo) { el.StereotypeEx = stereo; el.Update(); }
    pkg.Elements.Refresh();
    return el;
}

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
    if (!src || !tgt) { log("CON FEHLER (unbekanntes Element)"); return null; }
    var existing = findConnector(src, tgt, metaType, stereo);
    if (existing) { log("Connector existiert, übersprungen: " + metaType + " -> " + tgt.Name); return existing; }
    var con = src.Connectors.AddNew("", metaType);
    con.SupplierID = tgt.ElementID;
    if (stereo) con.StereotypeEx = stereo;
    if (!con.Update()) { log("CON FEHLER: " + con.GetLastError()); return null; }
    src.Connectors.Refresh();
    return con;
}

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

function main() {
    Session.Output("=== START ===");
    Repository.BatchAppend = true;
    Repository.EnableUIUpdates = false;
    try {
        // HIER: Modellbau (siehe templates/create_model_from_ir.js)
    } finally {
        Repository.BatchAppend = false;
        Repository.EnableUIUpdates = true;
    }
    Session.Output("=== ENDE (re-read mit templates/verify_model.js) ===");
}

main();
