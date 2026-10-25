/*
 * run_tests.js — functional test suite for EAM-AI-ADMBw-Script-Maker templates
 * against the in-memory EA mock (tests/mock_ea.js). Node only, no network.
 *
 * Usage: node tests/run_tests.js [repoRoot]
 * Writes tests/results.json and prints a compact matrix.
 * Exit code: 0 wenn alle Tests PASS/BLOCKED, 1 wenn mindestens ein FAIL.
 *
 * Verify-Semantik (templates/verify_model.js, Stand 19.10.2026):
 *   EXPECTED.elements/connectors/diagrams: null = kein Sollwert (nur Ist-Meldung "--"),
 *                                          0 = harte Null (IST > 0 => FAIL).
 *   EXPECTED.stereotypes: Map Stereotyp -> Anzahl; nur genannte Stereotype werden geprüft.
 *   Urteil: "VERIFY: FAIL" sobald ein Sollwert abweicht oder ein SQL-Ergebnis
 *   unlesbar ist; ohne gesetzte Sollwerte ist der Report eine reine Zählung
 *   ("VERIFY: PASS (nur geprüfte Sollwerte ...)") — nie eine Erfolgsgarantie.
 */
'use strict';

var fs = require('fs');
var path = require('path');
var vm = require('vm');
var cp = require('child_process');
var mock = require('./mock_ea.js');

var ROOT = process.argv[2] || path.resolve(__dirname, '..');
var TPL = path.join(ROOT, 'templates');
var EX = path.join(ROOT, 'examples');
var results = [];
var t0 = Date.now();

function add(id, fn, tc, expected, ok, evidence, note) {
    results.push({
        id: id, funktion: fn, testfall: tc, erwartung: expected,
        ergebnis: ok === null ? 'BLOCKED' : (ok ? 'PASS' : 'FAIL'),
        evidenz: evidence, befund: note || ''
    });
}

function eq(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

function runCode(code, repoEnv) {
    var sandbox = {
        Repository: repoEnv.Repository,
        Session: repoEnv.Session,
        console: console,
        JSON: JSON,
        Math: Math,
        String: String,
        parseInt: parseInt,
        isNaN: isNaN
    };
    try {
        vm.runInNewContext(code, sandbox, { filename: 'ea-script.js', timeout: 20000 });
        return { ok: true, error: null };
    } catch (e) {
        return { ok: false, error: String(e && e.stack ? e.stack : e) };
    }
}

function freshRepo(opts) { return mock.createRepository(opts || {}); }

function readJs(name) { return fs.readFileSync(path.join(TPL, name), 'utf8'); }

function buildWith(ir, opts) {
    var env = freshRepo(opts || {});
    var code = readJs('create_model_from_ir.js');
    var re = /var IR = \{[\s\S]*?\n\};/;
    if (!re.test(code)) throw new Error('IR block not found in create_model_from_ir.js');
    code = code.replace(re, 'var IR = ' + JSON.stringify(ir) + ';');
    var r = runCode(code, env);
    return { env: env, repo: env.repo, run: r, code: code };
}

/* verify_model.js ausführen; optional EXPECTED-Block ersetzen (Sollwerte aus dem IR) */
function verify(env, expected) {
    var code = readJs('verify_model.js');
    if (expected !== undefined) {
        var re = /var EXPECTED = \{[\s\S]*?\n\};/;
        if (!re.test(code)) throw new Error('EXPECTED block not found in verify_model.js');
        code = code.replace(re, 'var EXPECTED = ' + JSON.stringify(expected) + ';');
    }
    var r = runCode(code, env);
    return { run: r, out: env.repo.output.slice() };
}

function lastBuildLine(out) {
    for (var i = out.length - 1; i >= 0; i--) {
        if (out[i].indexOf('=== BUILD ENDE') === 0) return out[i];
    }
    return '';
}
function parseBuildLine(line) {
    var m = line.match(/(\d+) Pakete, (\d+) Elemente, (\d+) Connectors/);
    return m ? { packages: +m[1], elements: +m[2], connectors: +m[3] } : null;
}

function userElements(repo) {
    return repo.allElements().filter(function (e) { return !e._isPackageElement; });
}

var IR = JSON.parse(fs.readFileSync(path.join(EX, 'ir_beispiel.json'), 'utf8'));

/* ============================ A. Syntax / ES5 ============================ */
var jsFiles = ['templates/ea_jscript_skeleton.js', 'templates/create_model_from_ir.js',
    'templates/verify_model.js', 'examples/build_skript.js'];
jsFiles.forEach(function (f, i) {
    var res;
    try {
        cp.execSync('node --check ' + JSON.stringify(path.join(ROOT, f)), { stdio: 'pipe' });
        res = true;
    } catch (e) { res = false; }
    add('A' + (i + 1), 'Syntax', 'node --check ' + f, 'Syntax OK', res,
        'node --check exit ' + (res ? 0 : 1));
});

var es5Hits = [];
jsFiles.forEach(function (f) {
    var src = fs.readFileSync(path.join(ROOT, f), 'utf8');
    var re = /\b(?:let|const|class)\b|=>|`|\.forEach\(|Promise\b|async\s+function|await\s+/g;
    var m;
    while ((m = re.exec(src)) !== null) {
        es5Hits.push(f + ': ' + m[0] + ' @' + (src.slice(0, m.index).split('\n').length));
    }
});
add('A5', 'ES5-Kompatibilität', 'Statischer Scan auf let/const/arrow/Promise/template literals',
    'keine Treffer', es5Hits.length === 0, 'Treffer: ' + (es5Hits.join('; ') || '0'));

var bom = jsFiles.map(function (f) {
    var b = fs.readFileSync(path.join(ROOT, f));
    return f + ':' + (b[0] === 0xEF && b[1] === 0xBB && b[2] === 0xBF ? 'BOM' : 'kein BOM');
});
add('A6', 'Encoding', 'UTF-8-BOM-Prüfung (SKILL verlangt BOM)', 'alle Dateien mit BOM',
    bom.every(function (s) { return /:BOM$/.test(s); }), bom.join(', '));

var utf8ok = true;
jsFiles.forEach(function (f) {
    var buf = fs.readFileSync(path.join(ROOT, f));
    if (buf.toString('utf8').indexOf('\uFFFD') !== -1) utf8ok = false;
});
add('A7', 'Encoding', 'UTF-8-Dekodierung ohne Ersatzzeichen', 'keine U+FFFD', utf8ok,
    'Umlaute in Kommentaren (z. B. „Paketübergreifend“) lesbar');

add('A8', 'Skeleton', 'ea_jscript_skeleton.js gegen Mock ausführen', 'kein Exception, START/ENDE, UI-Updates wieder true',
    (function () {
        var env = freshRepo({});
        var r = runCode(readJs('ea_jscript_skeleton.js'), env);
        return r.ok && /=== START ===/.test(env.repo.output.join('\n')) &&
            /=== ENDE/.test(env.repo.output.join('\n')) && env.repo.EnableUIUpdates === true;
    })(),
    'Skeleton läuft leer durch, setzt BatchAppend/EnableUIUpdates korrekt zurück');

/* ====================== B. Build gegen Mock-Repository ====================== */
var b1 = buildWith(IR);
var b1out = b1.repo.output;
var b1line = lastBuildLine(b1out);
var b1counts = parseBuildLine(b1line);

add('B1', 'Build IR→Repository', 'examples/ir_beispiel.json ausführen',
    'kein Exception, 1 Paket / 3 Elemente / 2 Connectors',
    b1.run.ok && b1counts && b1counts.packages === 1 && b1counts.elements === 3 && b1counts.connectors === 2,
    b1line + (b1.run.error ? ' | ' + b1.run.error : ''));

add('B2', 'Build IR→Repository', 'Modell + Paket tatsächlich angelegt',
    '1 Modell, 1 Unterpaket, PaketGUID gesetzt',
    b1.repo._models.length === 1 && b1.repo._models[0].Packages.Count === 1 &&
    !!b1.repo._models[0].Packages.GetAt(0).PackageGUID,
    'Models=' + b1.repo._models.length + ', SubPkgs=' + b1.repo._models[0].Packages.Count);

var pkg1 = b1.repo._models[0].Packages.GetAt(0);
add('B3', 'Paket-Stereotyp', 'pkg.Element.Update() statt pkg.Update()',
    'StereotypeEx=ArchitecturalDescription, Element persisted',
    pkg1.Element.StereotypeEx === 'ArchitecturalDescription' && pkg1.Element._persisted === true,
    'pkg.Element.StereotypeEx=' + pkg1.Element.StereotypeEx + ', persisted=' + pkg1.Element._persisted);

var els1 = userElements(b1.repo);
var stereoMap = {};
els1.forEach(function (e) { stereoMap[e.Name] = e.Stereotype; });
add('B4', 'Elemente', 'Stereotype je Element', 'Node, Node, ServiceSpecification',
    stereoMap['Verteilzentrum Hamburg'] === 'Node' &&
    stereoMap['Kühlbereich Hannover'] === 'Node' &&
    stereoMap['Temperaturgeführte Lieferung'] === 'ServiceSpecification',
    JSON.stringify(stereoMap));

add('B5', 'IDs/GUIDs', 'IDs und GUIDs nach AddNew+Update lesbar',
    '3 nichtleere ElementIDs, 3 eindeutige GUIDs',
    els1.length === 3 && els1.every(function (e) { return e.ElementID > 0 && /^\{[0-9a-f-]{36}\}$/.test(e.ElementGUID); }) &&
    new Set(els1.map(function (e) { return e.ElementGUID; })).size === 3,
    els1.map(function (e) { return e.Name + '#' + e.ElementID + ' ' + e.ElementGUID; }).join(' | '));

var cons1 = b1.repo.persistedConnectors();
var c1 = cons1.filter(function (c) { return c.Stereotype === 'IsCapableOfPerforming'; })[0];
var c2 = cons1.filter(function (c) { return c.Stereotype === 'Provides'; })[0];
add('B6', 'Connectors', 'Endpunkte + Stereotyp + Metatyp',
    '2 Dependencies, korrekte Client/Supplier-IDs',
    cons1.length === 2 && c1 && c2 &&
    c1.ClientID === els1.filter(function (e) { return e.Name === 'Verteilzentrum Hamburg'; })[0].ElementID &&
    c1.SupplierID === els1.filter(function (e) { return e.Name === 'Kühlbereich Hannover'; })[0].ElementID &&
    c1.Type === 'Dependency' && c2.Type === 'Dependency',
    cons1.map(function (c) { return c.ClientID + '->' + c.SupplierID + ' ' + c.Type + ' «' + c.Stereotype + '»'; }).join(' | '));

var tv = els1.filter(function (e) { return e.Name === 'Verteilzentrum Hamburg'; })[0].TaggedValues;
add('B7', 'Tagged Values', 'tags.role=Hub setzen', 'genau 1 TV role=Hub',
    tv.Count === 1 && tv.GetAt(0).Name === 'role' && tv.GetAt(0).Value === 'Hub',
    'Count=' + tv.Count + ', ' + (tv.Count ? tv.GetAt(0).Name + '=' + tv.GetAt(0).Value : '-'));

add('B8', 'Repository-API', 'GetElementByID/GetPackageByID/GetConnectorByID',
    'liefern dieselben Objekte',
    b1.repo.GetElementByID(els1[0].ElementID) === els1[0] &&
    b1.repo.GetPackageByID(pkg1.PackageID) === pkg1 &&
    b1.repo.GetConnectorByID(cons1[0].ConnectorID) === cons1[0],
    'IDs: el=' + els1[0].ElementID + ' pkg=' + pkg1.PackageID + ' con=' + cons1[0].ConnectorID);

add('B9', 'BatchAppend', 'BatchAppend true in Elementphase, false vor Connectorphase',
    'Sequenz [true,false] und EnableUIUpdates am Ende true',
    b1.repo.batchLog[0] === true && b1.repo.batchLog.indexOf(false) > 0 &&
    b1.repo.batchLog[b1.repo.batchLog.length - 1] === false && b1.repo.EnableUIUpdates === true,
    'batchLog=' + JSON.stringify(b1.repo.batchLog) + ', UI=' + b1.repo.EnableUIUpdates);

add('B10', 'Build-Log', 'Zähler im Build-Log erster Lauf',
    '1/3/2', eq(b1counts, { packages: 1, elements: 3, connectors: 2 }), b1line);

/* ============================ C. Idempotenz ============================ */
var b1OutLen = b1.repo.output.length;
var guidBefore = els1.map(function (e) { return e.ElementGUID; }).join(',');
var idsBefore = els1.map(function (e) { return e.ElementID; }).join(',');
var r2 = runCode(b1.code, b1.env);
var els2 = userElements(b1.repo);
var cons2 = b1.repo.persistedConnectors();

add('C1', 'Idempotenz', 'Skript zweimal gegen dasselbe Repository',
    'unverändert 1 Paket / 3 Elemente / 2 Connectors, gleiche IDs/GUIDs, 1 Modell',
    r2.ok && b1.repo._models.length === 1 && b1.repo._models[0].Packages.Count === 1 &&
    els2.length === 3 && cons2.length === 2 &&
    els2.map(function (e) { return e.ElementGUID; }).join(',') === guidBefore &&
    els2.map(function (e) { return e.ElementID; }).join(',') === idsBefore,
    'nach 2. Lauf: models=' + b1.repo._models.length + ' pkgs=' + b1.repo._models[0].Packages.Count +
    ' els=' + els2.length + ' cons=' + cons2.length + ' | ' + lastBuildLine(b1.repo.output.slice(b1OutLen)));

add('C2', 'Idempotenz-Log', 'Build-Zähler im 2. Lauf',
    'meldet 0 neu erzeugte Objekte + Übersprung-Zähler (1 Pkg + 3 El + 2 Con = 6)',
    /0 Pakete, 0 Elemente, 0 Connectors/.test(lastBuildLine(b1.repo.output.slice(b1OutLen))) &&
    /übersprungen\/aktualisiert: 6/.test(lastBuildLine(b1.repo.output.slice(b1OutLen))),
    lastBuildLine(b1.repo.output.slice(b1OutLen)) + ' — Zähler trennt neu/übersprungen');

var irChanged = JSON.parse(JSON.stringify(IR));
irChanged.packages[0].elements[0].stereo = 'Capability';
irChanged.packages[0].elements[0].tags = { role: 'Spoke', newTag: 'X' };
var b3 = buildWith(IR, {});
var changedCode = readJs('create_model_from_ir.js').replace(/var IR = \{[\s\S]*?\n\};/,
    'var IR = ' + JSON.stringify(irChanged) + ';');
runCode(changedCode, b3.env);
var elChanged = b3.repo.allElements().filter(function (e) { return e.Name === 'Verteilzentrum Hamburg'; })[0];
add('C3', 'Idempotenz/Sync', 'IR-Änderung (Stereotyp/Tag) + Wiederholungslauf',
    'bestehendes Element wird aktualisiert (Stereotype Capability, Tag role=Spoke, neuer Tag)',
    elChanged.Stereotype === 'Capability' && elChanged.TaggedValues.GetAt(0).Value === 'Spoke' &&
    elChanged.TaggedValues.Count === 2 && /EL aktualisiert: Verteilzentrum Hamburg/.test(b3.repo.output.join('\n')),
    'Ist: Stereotype=' + elChanged.Stereotype + ', role=' + elChanged.TaggedValues.GetAt(0).Value +
    ', TV-Count=' + elChanged.TaggedValues.Count + ' — Sync-Pfad greift');

var irDupCon = JSON.parse(JSON.stringify(IR));
irDupCon.packages[0].connectors.push(JSON.parse(JSON.stringify(irDupCon.packages[0].connectors[0])));
var b4 = buildWith(irDupCon, {});
add('C4', 'Idempotenz', 'identischer Connector zweimal im IR',
    '2 persistierte Connectors (Dublette übersprungen, Zähler: 2 neu + 1 übersprungen)',
    b4.repo.persistedConnectors().length === 2 && /2 Connectors/.test(lastBuildLine(b4.repo.output)) &&
    /übersprungen\/aktualisiert: 1/.test(lastBuildLine(b4.repo.output)),
    'persistierte Connectors=' + b4.repo.persistedConnectors().length + ' | ' + lastBuildLine(b4.repo.output));

add('C5', 'Idempotenz/Sync', 'Paket-Stereotyp im IR geändert, Wiederholungslauf',
    'bestehendes Paket erhält neues Stereotyp (DataModel)',
    (function () {
        var env = buildWith(IR, {}).env;
        var changed = JSON.parse(JSON.stringify(IR));
        changed.packages[0].stereo = 'DataModel';
        var code = readJs('create_model_from_ir.js').replace(/var IR = \{[\s\S]*?\n\};/,
            'var IR = ' + JSON.stringify(changed) + ';');
        runCode(code, env);
        return env.repo._models[0].Packages.GetAt(0).Element.StereotypeEx === 'DataModel' &&
            /PKG aktualisiert: Logistik/.test(env.repo.output.join('\n'));
    })(),
    'Paket-Stereotyp wird beim Wiederholungslauf synchronisiert (addPackage-Sync)');

/* ============================== D. Verify ============================== */
/* D1: Verify mit Sollwerten aus dem IR -> PASS mit Soll/Ist-Zeilen */
var v1 = verify(b1.env, {
    elements: 3, connectors: 2, diagrams: 0,
    stereotypes: { Node: 2, ServiceSpecification: 1 }
});
var fullOut = v1.out.join('\n');
add('D1', 'Verify', 'verify_model.js nach erfolgreichem Build, EXPECTED aus dem IR gesetzt',
    'Soll/Ist PASS: 3 Elemente, 2 Connectors, Node=2, ServiceSpecification=1, Integrität 0, Dup-GUIDs 0',
    v1.run.ok && /VERIFY: PASS/.test(fullOut) &&
    /OK  Elemente gesamt: 3 \(Soll 3\)/.test(fullOut) &&
    /OK  Connectors gesamt: 2 \(Soll 2\)/.test(fullOut) &&
    /OK  Elemente «ServiceSpecification»: 1 \(Soll 1\)/.test(fullOut) &&
    /OK  Elemente «Node»: 2 \(Soll 2\)/.test(fullOut) &&
    /OK  Connectors mit ungültigen Endpunkten \(SOLL 0\): 0/.test(fullOut) &&
    /OK  Doppelte Element-GUIDs \(SOLL 0\): 0/.test(fullOut) &&
    /OK  Doppelte Connector-GUIDs \(SOLL 0\): 0/.test(fullOut),
    fullOut.split('\n').filter(function (l) { return /VERIFY|OK  |!!  /.test(l); }).join(' || '));

add('D2', 'Verify', 'Reportformat', '--- VERIFY REPORT ---, Urteil und === VERIFY ENDE ===',
    /--- VERIFY REPORT ---/.test(fullOut) && /=== VERIFY ENDE ===/.test(fullOut) &&
    /Prüfungen: \d+ · Fehler: 0/.test(fullOut),
    'Reportzeilen=' + fullOut.split('\n').length);

/* D3: null = kein Sollwert -> reine Ist-Zählung ("--"), kein OK, kein FAIL */
var vNullEnv = freshRepo({});
var vNull = verify(vNullEnv); // Default-EXPECTED (alles null)
var nullOut = vNull.out.join('\n');
add('D3', 'Verify-Semantik', 'EXPECTED = null (Default) gegen leeres Repository',
    'kein Sollwert -> Ist-Zählung (--), keine Soll-Abweichungs-FAILs, Urteil mit Disclaimer',
    vNull.run.ok && /--  Elemente gesamt: 0 \(kein Sollwert gesetzt\)/.test(nullOut) &&
    /--  Connectors gesamt: 0 \(kein Sollwert gesetzt\)/.test(nullOut) &&
    !/!!  /.test(nullOut) &&
    /VERIFY: PASS \(nur geprüfte Sollwerte/.test(nullOut),
    nullOut.split('\n').filter(function (l) { return /--  |VERIFY/.test(l); }).join(' || '));

/* D4: 0 = harte Null: leeres Repository, Soll 3/2 -> FAIL mit IST/SOLL */
var vEmptyEnv = freshRepo({});
var vEmpty = verify(vEmptyEnv, { elements: 3, connectors: 2, stereotypes: { Node: 2, ServiceSpecification: 1 } });
var emptyOut = vEmpty.out.join('\n');
add('D4', 'Verify-Semantik', 'EXPECTED = 3 Elemente/2 Connectors gegen leeres Repository',
    'VERIFY: FAIL mit IST 0 / SOLL 3 (harte Null)',
    vEmpty.run.ok && /VERIFY: FAIL/.test(emptyOut) &&
    /!!  Elemente gesamt: IST 0 \/ SOLL 3/.test(emptyOut) &&
    /!!  Connectors gesamt: IST 0 \/ SOLL 2/.test(emptyOut) &&
    /!!  Elemente «Node»: IST 0 \/ SOLL 2/.test(emptyOut),
    emptyOut.split('\n').filter(function (l) { return /IST|VERIFY/.test(l); }).join(' || '));

/* D5: Referenzintegrität SOLL 0 -> 1 ungültiger Endpunkt => FAIL */
var vb = buildWith(IR, {});
var elBad = vb.repo.allElements().filter(function (e) { return e.Name === 'Kühlbereich Hannover'; })[0];
var dangling = elBad.Connectors.AddNew('', 'Dependency');
dangling.SupplierID = 999999;
dangling.StereotypeEx = 'Provides';
dangling._persisted = true; // force a corrupt row that EA could contain after a crash
var vBad = verify(vb.env, { elements: 3, connectors: 2 });
var badOut = vBad.out.join('\n');
add('D5', 'Verify-Integrität', 'Connector mit ungültigem Supplier (999999)',
    'Integritätszeile IST 1 / SOLL 0 und VERIFY: FAIL',
    /!!  Connectors mit ungültigen Endpunkten \(SOLL 0\): IST 1 \/ SOLL 0/.test(badOut) &&
    /VERIFY: FAIL/.test(badOut),
    badOut.split('\n').filter(function (l) { return /ungültigen|VERIFY/.test(l); }).join(' || '));

/* D6: SQLQuery liefert leeres Resultset (DB-Fehler) -> FAIL, nie 0/OK */
var vErrEnv = freshRepo({ sqlErrorMode: true });
var vErr = verify(vErrEnv, { elements: 3 });
var errOut = vErr.out.join('\n');
add('D6', 'Verify-Fehlerfall', 'SQLQuery liefert leeres Resultset (DB-Fehler)',
    'Verify meldet FAIL (nicht als Zahl lesbar), nie 0/OK',
    /!!  Elemente gesamt: Ergebnis nicht als Zahl lesbar/.test(errOut) &&
    /VERIFY: FAIL/.test(errOut) && !/OK  Elemente gesamt/.test(errOut),
    errOut.split('\n').filter(function (l) { return /!!  |VERIFY/.test(l); }).join(' || '));

/* D7: sqlNumber unit tests (XML-Formate) */
var verifySrc = readJs('verify_model.js').replace(/\nmain\(\);\s*$/, '\n');
function sqlNumberWith(res) {
    var sandbox = { Repository: { SQLQuery: function () { return res; } }, Session: { Output: function () {} }, parseInt: parseInt, isNaN: isNaN };
    vm.runInNewContext(verifySrc, sandbox);
    return sandbox.sqlNumber('SELECT 1');
}
var fmt = {
    standard: sqlNumberWith('<?xml version="1.0"?><EADATA><Dataset><Data><Row><C>42</C></Row></Data></Dataset></EADATA>'),
    whitespace: sqlNumberWith('<EADATA><Dataset><Data><Row><C> 7 </C></Row></Data></Dataset></EADATA>'),
    zero: sqlNumberWith('<EADATA><Dataset><Data><Row><C>0</C></Row></Data></Dataset></EADATA>'),
    errorDoc: sqlNumberWith('<EADATA><Dataset><Error>ORA-00933</Error></Dataset></EADATA>'),
    negative: sqlNumberWith('<EADATA><Dataset><Data><Row><C>-1</C></Row></Data></Dataset></EADATA>'),
    multiRow: sqlNumberWith('<EADATA><Dataset><Data><Row><C>5</C></Row><Row><C>6</C></Row></Data></Dataset></EADATA>'),
    scalar: sqlNumberWith('42')
};
add('D7', 'sqlNumber', 'XML-Formate: Standard/Whitespace/0/Fehlerdoc/negativ/mehrzeilig/skalar',
    '42/7/0/-1(Fehler)/-1/5/42 — Fehlerdokumente nie als Zahl',
    fmt.standard === 42 && fmt.whitespace === 7 && fmt.zero === 0 &&
    fmt.errorDoc === -1 && fmt.negative === -1 && fmt.multiRow === 5 && fmt.scalar === 42,
    JSON.stringify(fmt));

/* D8: Verify prüft genau die im EXPECTED genannten Stereotype */
var vNode = verify(b4.env, { stereotypes: { Node: 2, Capability: 0 } }); // b4: Node/Node/ServiceSpecification
var nodeOut = vNode.out.join('\n');
add('D8', 'Verify-Abdeckung', 'EXPECTED.stereotypes = {Node: 2, Capability: 0} auf Node-Modell',
    'genannte Stereotype geprüft (Node OK, Capability harte Null OK), keine implizite Checkliste',
    /OK  Elemente «Node»: 2 \(Soll 2\)/.test(nodeOut) &&
    /OK  Elemente «Capability»: 0 \(Soll 0\)/.test(nodeOut) &&
    !/«OperationalActivity»/.test(nodeOut) && !/«ServiceSpecification»/.test(nodeOut),
    nodeOut.split('\n').filter(function (l) { return /Elemente «/.test(l); }).join(' || '));

/* D9: doppelte Connector-GUIDs -> FAIL (t_object UND t_connector) */
var vDupGuid = buildWith(IR, {});
var dgCons = vDupGuid.repo.persistedConnectors();
dgCons[1].ConnectorGUID = dgCons[0].ConnectorGUID;
var vDupOut = verify(vDupGuid.env, { elements: 3, connectors: 2 }).out.join('\n');
add('D9', 'Verify-GUID', 'zwei Connectors mit identischer ConnectorGUID',
    'Doppelte Connector-GUIDs (SOLL 0): IST 1 / SOLL 0 + VERIFY: FAIL',
    /!!  Doppelte Connector-GUIDs \(SOLL 0\): IST 1 \/ SOLL 0/.test(vDupOut) &&
    /VERIFY: FAIL/.test(vDupOut),
    vDupOut.split('\n').filter(function (l) { return /GUIDs|VERIFY/.test(l); }).join(' || '));

/* D10: Connector-Typ "Realization" (offizielle EA-17.1-Schreibweise) */
var vReal = buildWith({
    modelName: 'RealizationTest',
    packages: [{ name: 'P', elements: [{ name: 'A', type: 'Class', stereo: 'Node' }, { name: 'B', type: 'Class', stereo: 'Node' }],
        connectors: [{ from: 'A', to: 'B', meta: 'Realization', stereo: 'RealiseRequirement' }] }]
});
var realOut = verify(vReal.env, { elements: 2, connectors: 1 }).out.join('\n');
add('D10', 'Verify-Typnamen', 'Connector-Typ "Realization" (offizielle EA-17.1-Schreibweise)',
    'Verify zählt Realization-Connectors (Ist-Zeile) und Connectors gesamt PASS',
    /--  Connectors Realization: 1/.test(realOut) && /OK  Connectors gesamt: 1 \(Soll 1\)/.test(realOut),
    realOut.split('\n').filter(function (l) { return /Realization|Connectors gesamt/.test(l); }).join(' || '));

/* ============================ E. Edge Cases ============================ */
var bEmpty = buildWith({ modelName: 'Leer', packages: [] });
add('E1', 'Edge Case', 'leeres IR (packages: [])',
    'kein Exception, 0/0/0, Modell wird angelegt',
    bEmpty.run.ok && /0 Pakete, 0 Elemente, 0 Connectors/.test(lastBuildLine(bEmpty.repo.output)) &&
    bEmpty.repo._models.length === 1,
    lastBuildLine(bEmpty.repo.output));

var bNoPkgs = buildWith({ modelName: 'OhnePakete' });
add('E2', 'Edge Case', 'IR ohne packages-Feld',
    'kontrollierte Fehlermeldung, kein unbehandelter Absturz',
    bNoPkgs.run.ok && /EXCEPTION/.test(bNoPkgs.repo.output.join('\n')),
    bNoPkgs.repo.output.filter(function (l) { return /EXCEPTION|BUILD ENDE/.test(l); }).join(' || '));

var irUnknown = JSON.parse(JSON.stringify(IR));
irUnknown.packages[0].elements[0].stereo = 'VoelligErfundenesStereotyp';
var bUnknown = buildWith(irUnknown, {});
var elUnknown = bUnknown.repo.allElements().filter(function (e) { return e.Name === 'Verteilzentrum Hamburg'; })[0];
add('E3', 'Edge Case', 'unbekanntes Stereotyp (nicht in 318er-KB)',
    'Warnung oder Ablehnung (ADMBw-Konformität)',
    null,
    'StereotypeEx="' + elUnknown.StereotypeEx + '" ohne Warnung gesetzt',
    'BLOCKED: KB-Validierung gehört in den IR-Generator (LLM), nicht in das EA-Skript — das Skript hat keine 318er-KB und prüft bewusst nur Format/Referenzen.');

var irDupSame = JSON.parse(JSON.stringify(IR));
irDupSame.packages[0].elements = [
    { name: 'Doppelt', type: 'Class', stereo: 'Capability', tags: { a: '1' } },
    { name: 'Doppelt', type: 'Class', stereo: 'Node', tags: { b: '2' } }
];
irDupSame.packages[0].connectors = [];
var bDupSame = buildWith(irDupSame, {});
var dupSameEls = bDupSame.repo.allElements().filter(function (e) { return e.Name === 'Doppelt'; });
add('E4', 'Edge Case', 'zwei Elemente gleichen Namens im selben Paket',
    'eindeutige EL DUBLETTE-Warnung + Sync (1 Element, zweite Spezifikation gewinnt)',
    dupSameEls.length === 1 && /EL DUBLETTE im IR/.test(bDupSame.repo.output.join('\n')) &&
    dupSameEls[0].Stereotype === 'Node' && dupSameEls[0].TaggedValues.Count === 2,
    dupSameEls.length + ' Element (Stereotype=' + (dupSameEls[0] && dupSameEls[0].Stereotype) +
    ', Tags=' + (dupSameEls[0] ? dupSameEls[0].TaggedValues.Count : 0) + ') | Log: ' +
    lastBuildLine(bDupSame.repo.output) + ' | Warnung: ' + (/EL DUBLETTE im IR/.test(bDupSame.repo.output.join('\n')) ? 'ja' : 'nein'));

var irDupCross = {
    modelName: 'CrossDup',
    packages: [
        { name: 'P1', elements: [{ name: 'X', type: 'Class', stereo: 'Capability' }, { name: 'A', type: 'Class', stereo: 'Node' }], connectors: [{ from: 'X', to: 'A', meta: 'Dependency', stereo: 'Provides' }] },
        { name: 'P2', elements: [{ name: 'X', type: 'Class', stereo: 'Capability' }, { name: 'B', type: 'Class', stereo: 'Node' }], connectors: [] }
    ]
};
var bCross = buildWith(irDupCross, {});
var p1 = bCross.repo._models[0].Packages.GetAt(0);
var p2 = bCross.repo._models[0].Packages.GetAt(1);
var x1 = p1.Elements.GetAt(0), x2 = p2.Elements.GetAt(0);
var crossCon = bCross.repo.persistedConnectors()[0];
add('E5', 'Edge Case', 'gleicher Elementname in zwei Paketen + paketübergreifender Connector',
    'Connector startet am Element in P1 (x1) — paketqualifizierte Identität',
    crossCon && crossCon.ClientID === x1.ElementID,
    'ClientID=' + (crossCon ? crossCon.ClientID : '-') + ', P1.X=' + x1.ElementID + ', P2.X=' + x2.ElementID);

var bMissingName = buildWith({
    modelName: 'OhneName',
    packages: [{ name: 'P', elements: [{ type: 'Class', stereo: 'Node' }, { name: 'Gut', type: 'Class', stereo: 'Node' }], connectors: [] }]
});
add('E6', 'Edge Case', 'Element ohne name (Pflichtfeld)',
    'Fehlerzeile für das Element, übrige Elemente werden gebaut',
    /EL FEHLER/.test(bMissingName.repo.output.join('\n')) && !!bMissingName.repo.allElements().filter(function (e) { return e.Name === 'Gut'; }).length,
    bMissingName.repo.output.filter(function (l) { return /EL FEHLER|BUILD ENDE/.test(l); }).join(' || '));

var bGhost = buildWith({
    modelName: 'Ghost',
    packages: [{
        name: 'P', elements: [{ name: 'A', type: 'Class', stereo: 'Node' }, { name: 'B', type: 'Class', stereo: 'Node' }],
        connectors: [{ from: 'A', to: 'Geist', meta: 'Dependency' }, { from: 'A', to: 'B', meta: 'Dependency' }]
    }]
});
add('E7', 'Edge Case', 'Connector auf unbekanntes Element',
    'Fehlerzeile, gültiger Connector wird trotzdem gebaut',
    /CON FEHLER/.test(bGhost.repo.output.join('\n')) && bGhost.repo.persistedConnectors().length === 1,
    bGhost.repo.output.filter(function (l) { return /CON FEHLER|BUILD ENDE/.test(l); }).join(' || '));

var bigEls = [], bigCons = [];
for (var i = 0; i < 200; i++) {
    bigEls.push({ name: 'E' + i, type: 'Class', stereo: i % 2 ? 'Capability' : 'Node', tags: { idx: String(i) } });
    if (i > 0) bigCons.push({ from: 'E' + (i - 1), to: 'E' + i, meta: 'Dependency', stereo: 'Provides' });
}
var tBig = Date.now();
var bBig = buildWith({ modelName: 'Big', packages: [{ name: 'Gross', elements: bigEls, connectors: bigCons }] }, {});
var bigMs = Date.now() - tBig;
add('E8', 'Performance/Groß-IR', '200 Elemente, 199 Connectors, 200 Tags',
    '200/199 korrekt, Laufzeit < 5 s',
    userElements(bBig.repo).length === 200 && bBig.repo.persistedConnectors().length === 199 && bigMs < 5000,
    'elements=' + userElements(bBig.repo).length + ', connectors=' + bBig.repo.persistedConnectors().length +
    ', Dauer=' + bigMs + ' ms (Node/Mock)');

var irUml = {
    modelName: 'Umlaute-Ü',
    packages: [{
        name: 'Kühlkette – München',
        stereo: 'ArchitecturalDescription',
        elements: [
            { name: 'Außenstelle Straße 5', type: 'Class', stereo: 'Node', tags: { 'Größe': '5 "groß"' } },
            { name: 'Prüfungs-Gebäude Nr. 7', type: 'Class', stereo: 'Node' }
        ],
        connectors: [{ from: 'Außenstelle Straße 5', to: 'Prüfungs-Gebäude Nr. 7', meta: 'Dependency', stereo: 'Provides' }]
    }]
};
var bUml = buildWith(irUml, {});
var umlEls = userElements(bUml.repo);
add('E9', 'Edge Case', 'Umlaute/Sonderzeichen in Paket-, Element- und Tag-Namen',
    'Namen 1:1 erhalten, keine Mojibake',
    umlEls.length === 2 && umlEls[0].Name === 'Außenstelle Straße 5' &&
    umlEls[0].TaggedValues.GetAt(0).Name === 'Größe' &&
    bUml.repo._models[0].Packages.GetAt(0).Name === 'Kühlkette – München',
    JSON.stringify(umlEls.map(function (e) { return e.Name; })) + ' / ' + umlEls[0].TaggedValues.GetAt(0).Name);

var bElFail = buildWith(IR, { failElementUpdates: ['Kühlbereich Hannover'] });
add('E10', 'Fehlerpfad', 'Element.Update() schlägt fehl',
    'EL FEHLER mit GetLastError, Build läuft weiter, keine Exception',
    /EL FEHLER Kühlbereich Hannover: Mock: element update rejected/.test(bElFail.repo.output.join('\n')) &&
    bElFail.run.ok && userElements(bElFail.repo).length === 2,
    bElFail.repo.output.filter(function (l) { return /EL FEHLER|CON FEHLER|BUILD ENDE/.test(l); }).join(' || '));

var bPkgFail = buildWith(IR, { failPackageUpdates: ['Logistik'] });
add('E11', 'Fehlerpfad', 'Paket.Update() schlägt fehl',
    'PKG FEHLER, Paket wird übersprungen, Build endet kontrolliert',
    /PKG FEHLER Logistik/.test(bPkgFail.repo.output.join('\n')) && bPkgFail.run.ok &&
    /0 Pakete, 0 Elemente/.test(lastBuildLine(bPkgFail.repo.output)),
    bPkgFail.repo.output.filter(function (l) { return /PKG FEHLER|BUILD ENDE/.test(l); }).join(' || '));

var bConFail = buildWith(IR, { failConnectorUpdate: true });
add('E12', 'Fehlerpfad', 'Connector.Update() schlägt fehl',
    'CON FEHLER mit GetLastError, keine Exception',
    /CON FEHLER: Mock: connector update rejected/.test(bConFail.repo.output.join('\n')) && bConFail.run.ok,
    bConFail.repo.output.filter(function (l) { return /CON FEHLER|BUILD ENDE/.test(l); }).join(' || '));

var bBadMeta = buildWith({
    modelName: 'BadMeta',
    packages: [{ name: 'P', elements: [{ name: 'A', type: 'Class', stereo: 'Node' }, { name: 'B', type: 'Class', stereo: 'Node' }], connectors: [{ from: 'A', to: 'B', meta: 'Class', stereo: 'X' }] }]
});
add('E13', 'Edge Case', 'Connector mit Element-Metatyp ("Class")',
    'CON FEHLER, kein korrupter Connector',
    /CON FEHLER/.test(bBadMeta.repo.output.join('\n')) && bBadMeta.repo.persistedConnectors().length === 0,
    bBadMeta.repo.output.filter(function (l) { return /CON FEHLER|BUILD ENDE/.test(l); }).join(' || '));

var bBadElType = buildWith({
    modelName: 'BadElType',
    packages: [{ name: 'P', elements: [{ name: 'A', type: 'Dependency', stereo: 'Node' }], connectors: [] }]
});
add('E14', 'Edge Case', 'Element mit Connector-Metatyp ("Dependency")',
    'EL FEHLER, kein Element gespeichert',
    /EL FEHLER/.test(bBadElType.repo.output.join('\n')) && userElements(bBadElType.repo).length === 0,
    bBadElType.repo.output.filter(function (l) { return /EL FEHLER|BUILD ENDE/.test(l); }).join(' || '));

/* ====================== F. Statische Regelprüfung ====================== */
var createSrc = readJs('create_model_from_ir.js');
add('F1', 'Statik', 'Kein Element-Metatyp an Connectors.AddNew',
    'nur Connector-Typen (Dependency/Generalization/...)',
    !/Connectors\.AddNew\([^)]*\b(Class|Object|Activity|Node|Requirement)\b/.test(createSrc),
    'Connectors.AddNew-Aufrufe: ' + (createSrc.match(/Connectors\.AddNew\([^)]*\)/g) || []).join(' | '));

add('F2', 'Statik', 'Paket-Stereotyp über pkg.Element.Update()',
    'StereotypeEx-Zuweisung wird mit pkg.Element.Update() abgeschlossen',
    /pkg\.Element\.StereotypeEx\s*=[^;]+;[\s\S]{0,160}pkg\.Element\.Update\(\)/.test(createSrc),
    'pkg.Element.Update() folgt direkt auf die StereotypeEx-Zuweisung; pkg.Update() nur beim Anlegen');

add('F3', 'Statik', 'Keine geratenen IDs (keine AddNew()+1 / ElementID++)',
    'IDs werden aus Objekt gelesen',
    !/ElementID\s*\+|ConnectorID\s*\+|PackageID\s*\+/.test(createSrc),
    'keine ID-Arithmetik gefunden');

add('F4', 'Statik', 'Refresh nach AddNew/Update',
    'Refresh-Aufrufe auf Parent-Collections vorhanden',
    (createSrc.match(/\.Refresh\(\)/g) || []).length >= 4,
    'Refresh-Aufrufe=' + (createSrc.match(/\.Refresh\(\)/g) || []).length);

var createNoDiagram = !/Diagrams\.AddNew/.test(createSrc);
add('F5', 'Statik/Doku', 'Builder erzeugt Diagramme (SKILL/README-Anspruch)',
    'Builder legt keine Diagramme an — Doku entsprechend korrigiert (kein falsches Versprechen)',
    createNoDiagram ? null : false,
    'kein Diagrams.AddNew in create_model_from_ir.js',
    'BLOCKED: Diagramm-Erzeugung bewusst nicht im Builder — MDG-Diagrammtyp-String ist nur per EA-GUI auslesbar (einmalig manuell anlegen). SKILL/README versprechen keine Diagramme mehr; verify zählt t_diagram nur mit gesetztem Sollwert.');

var exampleSrc = fs.readFileSync(path.join(EX, 'build_skript.js'), 'utf8');
var exampleNoIr = exampleSrc.replace(/var IR = \{[\s\S]*?\n\};/, 'var IR = {};');
var tplNoIr = readJs('create_model_from_ir.js').replace(/var IR = \{[\s\S]*?\n\};/, 'var IR = {};');
add('F6', 'Beispiele', 'examples/build_skript.js = Template + eingebettetes IR',
    'Code identisch bis auf IR-Block',
    exampleNoIr === tplNoIr,
    'Differenz nach IR-Normalisierung: ' + (exampleNoIr === tplNoIr ? '0 Zeichen' : 'abweichend'));

/* ============================ Summary ============================ */
var counts = { PASS: 0, FAIL: 0, BLOCKED: 0 };
results.forEach(function (r) { counts[r.ergebnis]++; });
var summary = {
    repo: ROOT,
    timestamp: new Date().toISOString(),
    durationMs: Date.now() - t0,
    counts: counts,
    results: results
};
fs.writeFileSync(path.join(__dirname, 'results.json'), JSON.stringify(summary, null, 2));
console.log('\n=== TESTMATRIX ===');
results.forEach(function (r) {
    console.log(r.id + '\t' + r.ergebnis + '\t' + r.funktion + ' :: ' + r.testfall + ' :: ' +
        r.evidenz.replace(/\s+/g, ' ').slice(0, 240));
});
console.log('\n=== SUMMARY ===', JSON.stringify(counts), 'duration', summary.durationMs + 'ms');
/* Grüner Lauf = Exit 0; jeder echte FAIL bricht den Runner (Gate für CI/Reviews) */
if (counts.FAIL > 0) {
    console.log('\nFAIL: ' + counts.FAIL + ' echte Fehlschläge — Runner endet mit Exit 1.');
    process.exitCode = 1;
} else {
    console.log('\nKeine echten FAILs — Runner endet mit Exit 0.');
    process.exitCode = 0;
}
