/*
 * create_model_from_ir.js — baut aus einem IR-JSON (Prosa-Parser-Output) ein EA-Repository.
 * Review-Fixes (EAP 07.09. & Sparx Doku Check): ZWEI-PHASEN-Build (erst alle Elemente, dann alle Connectors,
 * damit paketuebergreifende Beziehungen funktionieren), findConnector-Idempotenz,
 * setTaggedValue statt AddNew-Duplikaten, BatchAppend vor Connector-Phase deaktiviert,
 * pkg.Element.Update() fuer Paket-Stereotype.
 * Nachtlauf 19.10.2026: Sync-Pfad — bestehende Pakete/Elemente werden bei Wiederholungsläufen
 * auf Stereotyp + Tags des IR aktualisiert (statt still zu überspringen); Zähler unterscheiden
 * "neu erzeugt" von "übersprungen/aktualisiert"; doppelte Elementnamen im selben Paket werden
 * als EL DUBLETTE gemeldet. Identität bleibt paketqualifiziert (Paket + Name), NICHT global per Name.
 * Ausfuehrung: EA-Scripting-Fenster (JavaScript).
 */

var IR = {
    modelName: "ADMBw-Architektur",
    packages: [
        {
            name: "C1 - Capability Taxonomy",
            stereo: "ArchitecturalDescription",
            elements: [
                { name: "Weltraumaufklärung",   type: "Class", stereo: "Capability", tags: { MoE: "bewertet" } },
                { name: "Sensornetz",           type: "Class", stereo: "Capability" }
            ],
            connectors: [
                { from: "Sensornetz", to: "Weltraumaufklärung", meta: "Generalization", stereo: "CapabilityGeneralization" }
            ]
        }
    ]
};

function log(msg) { Session.Output(msg); }

/* Eindeutiger Schlüssel: Paket + Elementname. Verhindert, dass ein
   gleichnamiges Element in einem anderen Paket einen Connector kapert
   (AAroN-Referenz: EAObject.Object_ID/Package_ID sind die Identität,
   nicht der Name). Optional kann das IR in Connectors fromPackage/toPackage
   setzen; sonst wird zuerst im aktuellen Paket, dann global eindeutig gesucht. */
function pkgKey(pkgName, elemName) {
    return String(pkgName) + "\u0001" + String(elemName);
}

function resolveElement(ref, pkgName, all) {
    var local = all[pkgKey(pkgName, ref)];
    if (local) return local;
    var hits = [];
    for (var k in all) {
        if (!all.hasOwnProperty(k)) continue;
        if (k.split("\u0001")[1] === String(ref)) hits.push(all[k]);
    }
    if (hits.length === 1) return hits[0];
    if (hits.length > 1) {
        log("CON FEHLER (mehrdeutig): '" + ref + "' existiert in mehreren Paketen — fromPackage/toPackage im IR setzen.");
        return null;
    }
    log("CON FEHLER (unbekannt): '" + ref + "'");
    return null;
}

function findElement(pkg, name) {
    for (var i = 0; i < pkg.Elements.Count; i++) {
        var e = pkg.Elements.GetAt(i);
        if (e.Name === name) return e;
    }
    return null;
}

function addPackage(parentPkg, name, stereo, stats) {
    for (var i = 0; i < parentPkg.Packages.Count; i++) {
        var p = parentPkg.Packages.GetAt(i);
        if (p.Name === name) {
            /* Sync: bestehendes Paket auf neuen Stereotyp aktualisieren */
            if (stereo && p.Element.StereotypeEx !== stereo) {
                p.Element.StereotypeEx = stereo;
                if (p.Element.Update()) { log("PKG aktualisiert: " + name); }
                else { log("PKG EL FEHLER " + name + ": " + p.Element.GetLastError()); }
            }
            if (stats) stats.skipped++;
            return p;
        }
    }
    var pkg = parentPkg.Packages.AddNew(name, "");
    if (!pkg.Update()) { log("PKG FEHLER " + name + ": " + pkg.GetLastError()); return null; }
    parentPkg.Packages.Refresh();
    if (stereo) {
        // Offizielle Sparx EA API: Paket-Stereotyp liegt am zugehoerigen Element!
        pkg.Element.StereotypeEx = stereo;
        if (!pkg.Element.Update()) { log("PKG EL FEHLER " + name + ": " + pkg.Element.GetLastError()); }
    }
    if (stats) stats.packages++;
    return pkg;
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

function addElement(pkg, spec, stats) {
    var el = findElement(pkg, spec.name);
    if (el) {
        /* Sync: bestehendes Element auf Stereotyp + Tags des IR aktualisieren */
        var changed = false;
        if (spec.stereo && el.StereotypeEx !== spec.stereo) { el.StereotypeEx = spec.stereo; changed = true; }
        if (spec.tags) {
            for (var k in spec.tags) { setTaggedValue(el, k, spec.tags[k]); changed = true; }
        }
        if (changed) {
            if (el.Update()) { log("EL aktualisiert: " + spec.name); }
            else { log("EL FEHLER " + spec.name + ": " + el.GetLastError()); }
            pkg.Elements.Refresh();
        }
        if (stats) stats.skipped++;
        return el;
    }
    el = pkg.Elements.AddNew(spec.name, spec.type);
    if (!el.Update()) { log("EL FEHLER " + spec.name + ": " + el.GetLastError()); return null; }
    if (spec.stereo) { el.StereotypeEx = spec.stereo; el.Update(); }
    if (spec.tags) {
        for (var k in spec.tags) { setTaggedValue(el, k, spec.tags[k]); }
    }
    pkg.Elements.Refresh();
    if (stats) stats.elements++;
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

function addConnector(src, tgt, metaType, stereo, stats) {
    if (!src || !tgt) { log("CON FEHLER (unbekanntes Element): " + metaType); return null; }
    var existing = findConnector(src, tgt, metaType, stereo);
    if (existing) { log("Connector existiert, übersprungen: " + metaType); if (stats) stats.skipped++; return existing; }
    var con = src.Connectors.AddNew("", metaType);
    con.SupplierID = tgt.ElementID;
    if (stereo) con.StereotypeEx = stereo;
    if (!con.Update()) { log("CON FEHLER: " + con.GetLastError()); return null; }
    src.Connectors.Refresh();
    if (stats) stats.connectors++;
    return con;
}

function main() {
    Session.Output("=== BUILD START ===");
    var built = { packages: 0, elements: 0, connectors: 0, skipped: 0 };
    Repository.BatchAppend = true;
    Repository.EnableUIUpdates = false;
    var allElements = {};
    try {
        // Modell suchen/anlegen
        var model = null;
        for (var i = 0; i < Repository.Models.Count; i++) {
            if (Repository.Models.GetAt(i).Name === IR.modelName) { model = Repository.Models.GetAt(i); break; }
        }
        if (!model) {
            model = Repository.Models.AddNew(IR.modelName, "");
            model.Update();
            Repository.Models.Refresh();
        }

        // PHASE 1: Pakete + Elemente (ElementID-Referenzen müssen vor Connectors stehen)
        for (var p = 0; p < IR.packages.length; p++) {
            var pspec = IR.packages[p];
            var pkg = addPackage(model, pspec.name, pspec.stereo, built);
            if (!pkg) continue;
            var seen = {};
            for (var e = 0; e < pspec.elements.length; e++) {
                var spec = pspec.elements[e];
                var ename = spec && spec.name;
                if (seen[ename]) {
                    log("EL DUBLETTE im IR: Paket '" + pspec.name + "', Element '" + ename + "' — zweite Spezifikation aktualisiert das vorhandene Element.");
                }
                seen[ename] = true;
                var el = addElement(pkg, spec, built);
                if (el) allElements[pkgKey(pspec.name, ename)] = el;
            }
        }

        // PHASE 2: Connectors (BatchAppend aus, damit ElementIDs garantiert final sind)
        Repository.BatchAppend = false;
        for (var p2 = 0; p2 < IR.packages.length; p2++) {
            var pspec2 = IR.packages[p2];
            if (!pspec2.connectors) continue;
            for (var c = 0; c < pspec2.connectors.length; c++) {
                var cs = pspec2.connectors[c];
                var src = resolveElement(cs.from, cs.fromPackage || pspec2.name, allElements);
                var tgt = resolveElement(cs.to, cs.toPackage || pspec2.name, allElements);
                addConnector(src, tgt, cs.meta, cs.stereo, built);
            }
        }
    } catch (ex) {
        Session.Output("EXCEPTION: " + ex);
    } finally {
        Repository.BatchAppend = false;
        Repository.EnableUIUpdates = true;
    }
    Session.Output("=== BUILD ENDE: " + built.packages + " Pakete, " + built.elements + " Elemente, " + built.connectors + " Connectors" + (built.skipped ? " (übersprungen/aktualisiert: " + built.skipped + ")" : "") + " ===");
    Session.Output("ACHTUNG: Re-Read mit verify_model.js — nie dem Build-Log allein vertrauen!");
}

main();
