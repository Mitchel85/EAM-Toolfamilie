/* Testet den Issue-Schreiber (part5b) ohne Browser:
   echte MASC-Datei oeffnen, Befunde einfuegen, Ergebnis als .qea schreiben. */
const fs = require('fs');
const path = require('path');
const initSqlJs = require(path.join(__dirname, 'vendor/sql-wasm.js'));

global.window = global;

(async () => {
  const SQL = await initSqlJs({ locateFile: f => path.join(__dirname, 'vendor', f) });
  const buf = fs.readFileSync('/root/hermes-workspace/admbw-qea-editor/Musterarchitektur_MASC.qea');
  const db = new SQL.Database(new Uint8Array(buf));

  function one(d, sql, params) {
    const st = d.prepare(sql);
    try { if (params) st.bind(params); if (!st.step()) return null; return st.getAsObject(); }
    finally { st.free(); }
  }
  function colNames(d, table) {
    const st = d.prepare('PRAGMA table_info(' + table + ')');
    const out = [];
    while (st.step()) out.push(st.getAsObject().name);
    st.free();
    return out;
  }
  function newGuid() {
    const h = '0123456789ABCDEF';
    let s = '';
    for (let i = 0; i < 32; i++) s += h[Math.floor(Math.random() * 16)];
    return '{' + s.slice(0, 8) + '-' + s.slice(8, 12) + '-' + s.slice(12, 16) + '-' + s.slice(16, 20) + '-' + s.slice(20) + '}';
  }
  function stereoXrefSync(d, guid, type, st) {
    if (!st) return;
    d.run('INSERT INTO t_xref (XrefID,Name,Type,Visibility,Description,Client,Supplier) VALUES (?,?,?,?,?,?,?)',
      [newGuid(), 'Stereotypes', type, 'Public',
       '@STEREO;Name=' + st + ';FQName=NAFv4-ADMBw::' + st + ';@ENDSTEREO;', guid, '<none>']);
  }
  const encNote = s => String(s).replace(/[\u0080-\uFFFF]/g, ch => '&#' + ch.charCodeAt(0) + ';').replace(/\r?\n/g, '\r\n');
  const shortLabel = (s, n) => (String(s || '').length > n ? String(s).substring(0, n - 1) + '…' : String(s || ''));

  // echtes Element fuer die Verknuepfung suchen
  const target = one(db, "SELECT Object_ID, Name FROM t_object WHERE Object_Type='Class' AND Name IS NOT NULL LIMIT 1");

  global.applyIssueBatch = null;
  global.EDIT = { q: function () { } };   /* im Browser vorhanden; hier nur als Wächter */
  const code = fs.readFileSync(path.join(__dirname, 'src/part5b_issue.js'), 'utf8');
  eval(code);

  const n = window.applyIssueBatch(db, {
    paket: 'Qualitätssicherung',
    sicht: 'A2 : MASC : Architecture Products',
    befunde: [
      { severity: 'befund', text: 'Sicht zeigt Elemente ohne Verbindung.', elementId: String(target.Object_ID), elementName: target.Name, ts: '2026-11-03T10:00:00Z' },
      { severity: 'kritisch', text: 'Stereotyp passt nicht zur Konvention A2-MK02.', elementId: '', elementName: '', ts: '2026-11-03T10:01:00Z' }
    ]
  }, {
    now: '2026-11-03 10:00:00', encNote, one, colNames, newGuid, stereoXrefSync, shortLabel
  });

  const out = '/tmp/viewertest/masc_mit_issues.qea';
  fs.writeFileSync(out, Buffer.from(db.export()));
  console.log(JSON.stringify({ angelegt: n, datei: out, bytes: fs.statSync(out).size }));
})().catch(e => { console.error('FEHLER:', e.message); process.exit(1); });
