/* ============================================================================
   ADMBw QEA Analyzer v5.0 (Edit-Edition) — Teil 5: BEARBEITEN + SPEICHERN
   ----------------------------------------------------------------------------
   Vorgemerkte Änderungen werden beim Speichern mit einer eingebetteten
   SQLite-Engine (sql.js, MIT-Lizenz, https://github.com/sql-js/sql.js) in eine
   NEUE .qea-Datei geschrieben. Die Originaldatei bleibt unverändert.

   EA-Konventionen (an Musterarchitektur_MASC.qea verifiziert):
   - Notizen: nicht-ASCII als &#NNN;-Entities, Zeilenumbrüche als CRLF
   - Namen/Alias/Stereotype/Tag-Werte: roher UTF-8-Text
   - Datum: 'YYYY-MM-DD HH:MM:SS' (TEXT)
   - IDs: je Tabelle eigene AUTOINCREMENT-Sequenz -> beim Einfügen weglassen
   - Pakete doppelt (t_package + t_object), Verknüpfung über ea_guid
   - Stereotype zusätzlich in t_xref ('@STEREO;Name=...;FQName=...;')
   ============================================================================ */

var EDIT = (function () {
  var changes = [];
  var changeId = 0;
  var srcBytes = null;
  var srcName = '';
  var sqlPromise = null;
  var formHandler = null;
  var _connSrcOid = null;
  var _connEndOid = null;
  var toastTimer = null;

  /* ================= kleine Helfer ================= */
  function p2(n) { return (n < 10 ? '0' : '') + n; }
  function nowStamp() {
    var d = new Date();
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate()) + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes()) + ':' + p2(d.getSeconds());
  }
  function fileStamp() {
    var d = new Date();
    return d.getFullYear() + p2(d.getMonth() + 1) + p2(d.getDate()) + '-' + p2(d.getHours()) + p2(d.getMinutes());
  }
  function newGuid() {
    var hex = '0123456789ABCDEF';
    var rnd = new Uint8Array(16), i;
    if (window.crypto && window.crypto.getRandomValues) { window.crypto.getRandomValues(rnd); }
    else { for (i = 0; i < 16; i++) rnd[i] = Math.floor(Math.random() * 256); }
    function by(x) { return hex.charAt(x >> 4) + hex.charAt(x & 15); }
    return '{' + by(rnd[0]) + by(rnd[1]) + by(rnd[2]) + by(rnd[3]) + '-' + by(rnd[4]) + by(rnd[5]) + '-' + by(rnd[6]) + by(rnd[7]) + '-' + by(rnd[8]) + by(rnd[9]) + '-' + by(rnd[10]) + by(rnd[11]) + by(rnd[12]) + by(rnd[13]) + by(rnd[14]) + by(rnd[15]) + '}';
  }
  function s0(v) { return v == null ? '' : String(v); }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function keys(o) { var n = 0, k; for (k in o) if (has(o, k)) n++; return n; }

  /* Notiz-Kodierung: EA-Konvention (Entities + CRLF) */
  function encNote(s) {
    s = s0(s).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    var out = '', i, ch, code;
    for (i = 0; i < s.length; i++) {
      ch = s.charAt(i); code = s.charCodeAt(i);
      if (ch === '\n') out += '\r\n';
      else if (code === 9) out += '\t';
      else if (code < 32) out += ' ';
      else if (code > 126) out += '&#' + code + ';';
      else out += ch;
    }
    return out;
  }
  function decNote(s) {
    s = s0(s);
    s = s.replace(/&#(\d+);/g, function (m, n) { var c = parseInt(n, 10); return c ? String.fromCharCode(c) : m; });
    s = s.replace(/&#[xX]([0-9a-fA-F]+);/g, function (m, n) { var c = parseInt(n, 16); return c ? String.fromCharCode(c) : m; });
    s = s.replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
    return s.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  }

  /* ================= Rohdatenzugriff über den bestehenden Parser ================= */
  function rowsOf(table) { try { return (DB && DB.rows) ? DB.rows(table) : []; } catch (e) { return []; } }
  function findRow(table, keyCol, keyVal) {
    var rows = rowsOf(table), i, v;
    for (i = 0; i < rows.length; i++) {
      v = qcol(rows[i], keyCol);
      if (v != null && String(v) === String(keyVal)) return rows[i];
    }
    return null;
  }
  function rv(row, col) { return row ? qcol(row, col) : null; }
  function pkgIdForObject(oid) {
    var r = findRow('t_object', 'Object_ID', oid);
    if (!r) return null;
    var g = s0(rv(r, 'ea_guid'));
    if (!g) return null;
    var p = findRow('t_package', 'ea_guid', g);
    return p ? rv(p, 'Package_ID') : null;
  }

  /* ================= ausstehende Vormerkung zu Objekt finden ================= */
  function findPending(kind, key) {
    for (var i = 0; i < changes.length; i++) if (changes[i].kind === kind && changes[i].key === key) return changes[i];
    return null;
  }

  /* ================= Änderung einreihen ================= */
  function q(ch) {
    var i;
    if (ch.key) {
      for (i = 0; i < changes.length; i++) {
        if (changes[i].kind === ch.kind && changes[i].key === ch.key) { changes.splice(i, 1); break; }
      }
    }
    ch.cid = ++changeId;
    changes.push(ch);
    renderDrawer(); updateBadge();
    toast(ch.label + ' — vorgemerkt');
  }
  function removeChange(cid) {
    for (var i = 0; i < changes.length; i++) if (changes[i].cid === cid) { changes.splice(i, 1); break; }
    renderDrawer(); updateBadge();
  }
  function clearAll(silent) {
    changes = [];
    renderDrawer(); updateBadge();
    if (!silent) toast('Alle Vormerkungen verworfen.');
  }
  function clearAllConfirm() {
    if (!changes.length) { toast('Keine Vormerkungen vorhanden.'); return; }
    openModal('🗑 Alle Änderungen verwerfen',
      '<div class="eform"><p style="font-size:13px">Alle <b>' + changes.length + '</b> vorgemerkten Änderungen verwerfen? Die geladene Datei selbst ist davon nicht betroffen — nur die Vormerkliste wird geleert.</p></div>',
      '<button class="btn-sm" onclick="EDIT.modalClose()">Abbrechen</button><button class="btn-sm danger" onclick="EDIT._clearConfirmOk()">Alle verwerfen</button>');
  }
  function _clearConfirmOk() { modalClose(); clearAll(false); }

  /* ================= UI: Badge / Drawer / Toasts ================= */
  function updateBadge() {
    var n = changes.length;
    var c = el('editcnt'); if (c) c.textContent = n;
    var b = el('editbtn'); if (b) b.className = n ? 'btn-sm amber hot' : 'btn-sm amber';
  }
  var ICONS = { 'el.set': '📦', 'pkg.set': '📁', 'diag.set': '🖼️', 'conn.set': '🔗', 'tag.set': '🏷️', 'tag.add': '🏷️', 'tag.del': '🏷️', 'el.create': '➕', 'conn.create': '➕', 'el.del': '🗑️', 'conn.del': '🗑️' };
  function renderDrawer() {
    var d = el('editdrawer');
    if (!d) return;
    var h = [];
    h.push('<div class="edr-head"><b>✏️ Änderungen an der Architektur (' + changes.length + ')</b><button onclick="EDIT.closePanel()" title="Schließen">✕</button></div>');
    h.push('<div class="edr-hint">Gespeichert wird erst über <b>„Als neue .qea speichern“</b> — in eine <b>neue Datei</b>. Die Originaldatei bleibt unverändert. Für den ersten Test: Ergebnis in einer <b>Kopie</b> mit Sparx EA prüfen.</div>');
    if (!changes.length) {
      h.push('<div class="edr-empty">Noch keine Änderungen vorgemerkt.<br><span class="dim">Nutzen Sie die ✏️-Buttons an Elementen, Paketen, Sichten und Beziehungen.</span></div>');
    } else {
      h.push('<div class="edr-list">');
      for (var i = 0; i < changes.length; i++) {
        var c = changes[i];
        h.push('<div class="edr-item"><span class="edr-ic">' + (ICONS[c.kind] || '•') + '</span><div class="edr-txt"><b>' + esc(c.label || c.kind) + '</b>' +
          (c.sub ? '<div class="edr-sub">' + esc(c.sub) + '</div>' : '') +
          '</div><button class="edr-del" onclick="EDIT.removeChange(' + c.cid + ')" title="Vormerkung entfernen">✕</button></div>');
      }
      h.push('</div>');
    }
    h.push('<div class="edr-foot">' +
      '<button id="edr-save" class="btn-sm pri" onclick="EDIT.save()"' + (changes.length ? '' : ' disabled') + '>💾 Als neue .qea speichern</button>' +
      '<button class="btn-sm" onclick="EDIT.exportCSV()">⤓ Protokoll (CSV)</button>' +
      '<button class="btn-sm amber" onclick="EDIT.clearAllConfirm()"' + (changes.length ? '' : ' disabled') + '>🗑 Verwerfen</button>' +
      '</div>');
    d.innerHTML = h.join('');
  }
  function openPanel() { var d = el('editdrawer'); if (!d) return; renderDrawer(); d.removeAttribute('hidden'); }
  function closePanel() { var d = el('editdrawer'); if (d) d.setAttribute('hidden', ''); }
  function toast(msg) {
    var t = el('edittoast');
    if (!t) return;
    t.textContent = msg;
    t.removeAttribute('hidden');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.setAttribute('hidden', ''); }, 2600);
  }

  /* ================= UI: Modal ================= */
  function escKey(e) { if (e.keyCode === 27) modalClose(); }
  function openModal(title, bodyHtml, footHtml) {
    var m = el('editmodal');
    if (!m) return;
    m.innerHTML = '<div class="em-back" onclick="EDIT.modalClose()"></div><div class="em-box">' +
      '<div class="em-head"><b>' + title + '</b><button onclick="EDIT.modalClose()" title="Schließen (Esc)">✕</button></div>' +
      '<div class="em-body">' + bodyHtml + '</div>' +
      '<div class="em-foot">' + (footHtml || '<button class="btn-sm" onclick="EDIT.modalClose()">Schließen</button>') + '</div>' +
      '</div>';
    m.removeAttribute('hidden');
    document.addEventListener('keydown', escKey);
  }
  function modalClose() {
    var m = el('editmodal');
    if (m) { m.setAttribute('hidden', ''); m.innerHTML = ''; }
    formHandler = null;
    document.removeEventListener('keydown', escKey);
  }
  function formOk() { if (formHandler) formHandler(); }
  function okFooter(label, cls) {
    return '<button class="btn-sm" onclick="EDIT.modalClose()">Abbrechen</button><button class="btn-sm ' + (cls || 'pri') + '" onclick="EDIT.formOk()">' + (label || 'Vormerken') + '</button>';
  }
  function fld(label, id, val, hint) {
    return '<label for="' + id + '">' + label + '</label><input type="text" id="' + id + '" value="' + esc(s0(val)) + '">' + (hint ? '<div class="dim">' + hint + '</div>' : '');
  }
  function fldTA(label, id, val) {
    return '<label for="' + id + '">' + label + '</label><textarea id="' + id + '">' + esc(s0(val)) + '</textarea>';
  }
  function gv(id) { var e = el(id); return e ? e.value : ''; }
  function sel(id, options, cur) {
    var h = '<select id="' + id + '">', i;
    for (i = 0; i < options.length; i++) {
      h += '<option value="' + esc(options[i]) + '"' + (options[i] === cur ? ' selected' : '') + '>' + esc(options[i]) + '</option>';
    }
    return h + '</select>';
  }
  function diffLine(lbl, oldV, newV) {
    if (oldV === newV) return '';
    return lbl + ': „' + shortLabel(s0(oldV).replace(/\n/g, ' '), 70) + '“ → „' + shortLabel(s0(newV).replace(/\n/g, ' '), 70) + '“';
  }
  function objectTypeList() {
    var counts = {}, rows = rowsOf('t_object'), i, t;
    for (i = 0; i < rows.length; i++) { t = s0(qcol(rows[i], 'Object_Type')) || 'Class'; counts[t] = (counts[t] || 0) + 1; }
    var arr = [];
    for (var k in counts) if (has(counts, k) && k !== 'Package' && k !== 'Text') arr.push([k, counts[k]]);
    arr.sort(function (a, b) { return b[1] - a[1]; });
    var out = [];
    for (i = 0; i < arr.length && i < 24; i++) out.push(arr[i][0]);
    if (out.indexOf('Class') < 0) out.unshift('Class');
    return out;
  }
  var COMMON_CONNTYPES = ['Dependency', 'Realisation', 'Generalization', 'Association', 'Aggregation', 'Composition', 'InformationFlow', 'ControlFlow', 'ObjectFlow', 'StateFlow', 'Abstraction', 'Usage', 'Connector', 'NoteLink', 'Package'];
  function connTypeList() {
    var counts = {}, i, t, arr = [];
    for (i = 0; i < CONS.length; i++) { t = CONS[i].type || ''; if (t) counts[t] = (counts[t] || 0) + 1; }
    for (var k in counts) if (has(counts, k)) arr.push([k, counts[k]]);
    arr.sort(function (a, b) { return b[1] - a[1]; });
    var out = [];
    for (i = 0; i < arr.length; i++) out.push(arr[i][0]);
    for (i = 0; i < COMMON_CONNTYPES.length; i++) if (out.indexOf(COMMON_CONNTYPES[i]) < 0) out.push(COMMON_CONNTYPES[i]);
    return out;
  }
  var DIRECTIONS = ['Source -> Destination', 'Destination -> Source', 'Unspecified'];

  /* ================= Editor: Element ================= */
  function elEdit(oid) {
    oid = String(oid);
    var o = OBJS[oid];
    if (!o) return;
    var raw = findRow('t_object', 'Object_ID', oid);
    if (!raw) { toast('Elementzeile nicht gefunden.'); return; }
    var pend = findPending('el.set', 'el:' + oid);
    var curName = s0(rv(raw, 'Name')), curSt = s0(rv(raw, 'Stereotype')), curAlias = s0(rv(raw, 'Alias'));
    var curStatus = s0(rv(raw, 'Status')), curNote = decNote(rv(raw, 'Note'));
    if (pend) {
      if (has(pend.fields, 'Name')) curName = pend.fields.Name;
      if (has(pend.fields, 'Stereotype')) curSt = pend.fields.Stereotype;
      if (has(pend.fields, 'Alias')) curAlias = pend.fields.Alias;
      if (has(pend.fields, 'Status')) curStatus = pend.fields.Status;
      if (has(pend.fields, 'Note')) curNote = pend.fields.Note;
    }
    var body = '<div class="eform">' +
      fld('Name', 'ee-name', curName) +
      fld('Stereotype', 'ee-st', curSt) +
      fld('Alias', 'ee-alias', curAlias) +
      '<label for="ee-status">Status</label><input type="text" id="ee-status" value="' + esc(curStatus) + '" list="edstatuslist"><datalist id="edstatuslist"><option>Proposed</option><option>Validated</option><option>Approved</option><option>Implemented</option><option>Mandatory</option></datalist>' +
      fldTA('Beschreibung / Notiz', 'ee-note', curNote) +
      '<div class="dim">Element-ID ' + esc(oid) + ' · Typ ' + esc(o.type || '') + ' · Paket: ' + esc(o.pkg || '') + '</div>' +
      '<div style="margin-top:10px" class="dim">Element löschen: über „🗑 Löschen“ im Steckbrief.</div>' +
      '</div>';
    formHandler = function () {
      var nm = gv('ee-name'), st = gv('ee-st'), al = gv('ee-alias'), stat = gv('ee-status'), nt = gv('ee-note');
      var fields = {}, subs = [];
      var t1;
      t1 = diffLine('Name', s0(rv(raw, 'Name')), nm); if (t1) { fields.Name = nm; subs.push(t1); }
      t1 = diffLine('Stereotype', s0(rv(raw, 'Stereotype')), st); if (t1) { fields.Stereotype = st; subs.push(t1); }
      t1 = diffLine('Alias', s0(rv(raw, 'Alias')), al); if (t1) { fields.Alias = al; subs.push(t1); }
      t1 = diffLine('Status', s0(rv(raw, 'Status')), stat); if (t1) { fields.Status = stat; subs.push(t1); }
      t1 = diffLine('Notiz', decNote(rv(raw, 'Note')), nt); if (t1) { fields.Note = nt; subs.push(t1); }
      if (!keys(fields)) { toast('Keine Änderung.'); modalClose(); return; }
      if (!nm) { toast('Hinweis: Element ohne Namen kann in EA Probleme machen.'); }
      var ch = { kind: 'el.set', key: 'el:' + oid, id: Number(oid), fields: fields, oldStereotype: s0(rv(raw, 'Stereotype')), label: 'Element „' + shortLabel(nm || o.name, 44) + '“', sub: subs.join('\n') };
      modalClose(); q(ch);
    };
    openModal('✏️ Element bearbeiten', body, okFooter('Änderung vormerken'));
  }

  /* ================= Editor: Paket ================= */
  function pkgEdit(pid) {
    if (pid == null) return;
    var p = PKG[pid];
    var raw = findRow('t_package', 'Package_ID', pid);
    if (!p || !raw) { toast('Paket nicht gefunden.'); return; }
    var pend = findPending('pkg.set', 'pkg:' + pid);
    var curName = s0(rv(raw, 'Name')), curNotes = decNote(rv(raw, 'Notes'));
    if (pend) {
      if (has(pend.fields, 'Name')) curName = pend.fields.Name;
      if (has(pend.fields, 'Notes')) curNotes = pend.fields.Notes;
    }
    var body = '<div class="eform">' +
      fld('Paketname', 'ep-name', curName) +
      fldTA('Beschreibung / Notiz', 'ep-notes', curNotes) +
      '<div class="dim">Der Name wird in <code>t_package</code> und in der gespiegelten <code>t_object</code>-Zeile aktualisiert.</div>' +
      '</div>';
    formHandler = function () {
      var nm = gv('ep-name'), nt = gv('ep-notes');
      var fields = {}, subs = [], t1;
      t1 = diffLine('Name', s0(rv(raw, 'Name')), nm); if (t1) { fields.Name = nm; subs.push(t1); }
      t1 = diffLine('Notiz', decNote(rv(raw, 'Notes')), nt); if (t1) { fields.Notes = nt; subs.push(t1); }
      if (!keys(fields)) { toast('Keine Änderung.'); modalClose(); return; }
      modalClose();
      q({ kind: 'pkg.set', key: 'pkg:' + pid, id: Number(pid), fields: fields, label: 'Paket „' + shortLabel(nm || p.name, 44) + '“', sub: subs.join('\n') });
    };
    openModal('✏️ Paket bearbeiten', body, okFooter('Änderung vormerken'));
  }

  /* ================= Editor: Sicht (Diagramm) ================= */
  function diagEdit(diagId) {
    if (diagId == null) return;
    var d = DIAGMAP[diagId];
    var raw = findRow('t_diagram', 'Diagram_ID', diagId);
    if (!d || !raw) { toast('Sicht nicht gefunden.'); return; }
    var pend = findPending('diag.set', 'diag:' + diagId);
    var curName = s0(rv(raw, 'Name')), curNotes = decNote(rv(raw, 'Notes'));
    if (pend) {
      if (has(pend.fields, 'Name')) curName = pend.fields.Name;
      if (has(pend.fields, 'Notes')) curNotes = pend.fields.Notes;
    }
    var body = '<div class="eform">' +
      fld('Sicht-/Diagrammname', 'ed-name', curName) +
      fldTA('Sicht-Beschreibung', 'ed-notes', curNotes) +
      '<div class="dim">Diagramm-ID ' + esc(String(diagId)) + ' · Typ ' + esc(d.type || '') + '</div>' +
      '</div>';
    formHandler = function () {
      var nm = gv('ed-name'), nt = gv('ed-notes');
      var fields = {}, subs = [], t1;
      t1 = diffLine('Name', s0(rv(raw, 'Name')), nm); if (t1) { fields.Name = nm; subs.push(t1); }
      t1 = diffLine('Beschreibung', decNote(rv(raw, 'Notes')), nt); if (t1) { fields.Notes = nt; subs.push(t1); }
      if (!keys(fields)) { toast('Keine Änderung.'); modalClose(); return; }
      modalClose();
      q({ kind: 'diag.set', key: 'diag:' + diagId, id: Number(diagId), fields: fields, label: 'Sicht „' + shortLabel(nm || d.name, 44) + '“', sub: subs.join('\n') });
    };
    openModal('✏️ Sicht bearbeiten', body, okFooter('Änderung vormerken'));
  }

  /* ================= Editor: Beziehung ================= */
  function connEdit(cid) {
    if (cid == null) return;
    var raw = findRow('t_connector', 'Connector_ID', cid);
    if (!raw) { toast('Beziehung nicht gefunden.'); return; }
    var pend = findPending('conn.set', 'conn:' + cid);
    var a = OBJS[String(rv(raw, 'Start_Object_ID'))], b = OBJS[String(rv(raw, 'End_Object_ID'))];
    var curName = s0(rv(raw, 'Name')), curSt = s0(rv(raw, 'Stereotype')), curDir = s0(rv(raw, 'Direction')), curNotes = decNote(rv(raw, 'Notes'));
    if (pend) {
      if (has(pend.fields, 'Name')) curName = pend.fields.Name;
      if (has(pend.fields, 'Stereotype')) curSt = pend.fields.Stereotype;
      if (has(pend.fields, 'Direction')) curDir = pend.fields.Direction;
      if (has(pend.fields, 'Notes')) curNotes = pend.fields.Notes;
    }
    var body = '<div class="eform">' +
      '<div class="dim">Verbindung: <b>' + esc(a ? a.name : ('#' + rv(raw, 'Start_Object_ID'))) + '</b> → <b>' + esc(b ? b.name : ('#' + rv(raw, 'End_Object_ID'))) + '</b> · Typ ' + esc(s0(rv(raw, 'Connector_Type'))) + '</div>' +
      fld('Beziehungsname (optional)', 'ec-name', curName) +
      fld('Stereotype', 'ec-st', curSt) +
      '<label>Richtung</label>' + sel('ec-dir', DIRECTIONS, curDir) +
      fldTA('Beschreibung / Notiz', 'ec-notes', curNotes) +
      '</div>';
    var foot = '<button class="btn-sm danger" onclick="EDIT._connDelFromEdit(' + cid + ')">🗑 Beziehung entfernen…</button><span style="flex:1"></span><button class="btn-sm" onclick="EDIT.modalClose()">Abbrechen</button><button class="btn-sm pri" onclick="EDIT.formOk()">Änderung vormerken</button>';
    formHandler = function () {
      var nm = gv('ec-name'), st = gv('ec-st'), dir = gv('ec-dir'), nt = gv('ec-notes');
      var fields = {}, subs = [], t1;
      t1 = diffLine('Name', s0(rv(raw, 'Name')), nm); if (t1) { fields.Name = nm; subs.push(t1); }
      t1 = diffLine('Stereotype', s0(rv(raw, 'Stereotype')), st); if (t1) { fields.Stereotype = st; subs.push(t1); }
      t1 = diffLine('Richtung', s0(rv(raw, 'Direction')), dir); if (t1) { fields.Direction = dir; subs.push(t1); }
      t1 = diffLine('Notiz', decNote(rv(raw, 'Notes')), nt); if (t1) { fields.Notes = nt; subs.push(t1); }
      if (!keys(fields)) { toast('Keine Änderung.'); modalClose(); return; }
      modalClose();
      var lbl = 'Beziehung „' + shortLabel(st || s0(rv(raw, 'Connector_Type')), 40) + '“ zwischen „' + shortLabel(a ? a.name : '?', 30) + '“ und „' + shortLabel(b ? b.name : '?', 30) + '“';
      q({ kind: 'conn.set', key: 'conn:' + cid, id: Number(cid), fields: fields, oldStereotype: s0(rv(raw, 'Stereotype')), label: lbl, sub: subs.join('\n') });
    };
    openModal('✏️ Beziehung bearbeiten', body, foot);
  }
  function _connDelFromEdit(cid) { modalClose(); connDel(cid); }

  /* ================= Editor: Tags (Tagged Values) ================= */
  function tagOpen(oid) {
    oid = String(oid);
    var o = OBJS[oid];
    if (!o) return;
    var all = rowsOf('t_objectproperties'), rows = [], i, r, p1;
    var deleted = {}, sets = {};
    for (i = 0; i < changes.length; i++) {
      var c = changes[i];
      if (c.kind === 'tag.del' && String(c.oid) === oid) deleted[String(c.pid)] = true;
      if (c.kind === 'tag.set' && String(c.oid) === oid) sets[String(c.pid)] = c.fields;
    }
    for (i = 0; i < all.length; i++) {
      r = all[i];
      if (String(qcol(r, 'Object_ID')) !== oid) continue;
      p1 = String(rv(r, 'PropertyID'));
      if (deleted[p1]) continue;
      var prop = s0(rv(r, 'Property')), val = s0(rv(r, 'Value')), mark = '';
      if (sets[p1]) {
        if (has(sets[p1], 'Property')) prop = sets[p1].Property;
        if (has(sets[p1], 'Value')) val = sets[p1].Value;
        mark = ' <span class="b b-diag">geändert (vorgemerkt)</span>';
      }
      rows.push({ pid: p1, prop: prop, val: val, pend: !!sets[p1] });
    }
    var adds = [];
    for (i = 0; i < changes.length; i++) {
      if (changes[i].kind === 'tag.add' && String(changes[i].oid) === oid) adds.push(changes[i]);
    }
    var h = ['<div class="eform">'];
    h.push('<div class="dim">Element: <b>' + esc(o.name) + '</b> · ' + (rows.length + adds.length) + ' Tag(s)</div>');
    h.push('<table class="data" style="font-size:12px;margin-top:8px"><thead><tr><th>Eigenschaft</th><th>Wert</th><th style="width:70px"></th></tr></thead><tbody>');
    for (i = 0; i < rows.length; i++) {
      var rr = rows[i];
      h.push('<tr><td><b>' + esc(rr.prop) + '</b>' + (rr.pend ? ' ✦' : '') + '</td><td>' + esc(shortLabel(rr.val, 90)) + '</td>' +
        '<td><button class="btn-sm" onclick="EDIT._tagEdit(\'' + oid + '\',' + rr.pid + ')" title="Tag bearbeiten">✏️</button> ' +
        '<button class="btn-sm" onclick="EDIT._tagDel(\'' + oid + '\',' + rr.pid + ')" title="Tag entfernen">🗑</button></td></tr>');
    }
    for (i = 0; i < adds.length; i++) {
      h.push('<tr><td><b>' + esc(adds[i].prop) + '</b> <span class="b b-els">neu</span></td><td>' + esc(shortLabel(adds[i].val, 90)) + '</td>' +
        '<td><button class="btn-sm" onclick="EDIT.removeChange(' + adds[i].cid + ')" title="Vormerkung entfernen">✕</button></td></tr>');
    }
    if (!rows.length && !adds.length) h.push('<tr><td colspan="3" class="dim">Keine Tags vorhanden.</td></tr>');
    h.push('</tbody></table>');
    h.push('<h3 style="margin-top:14px">Neuen Tag hinzufügen</h3>');
    h.push(fld('Eigenschaft', 'et-prop', '') );
    h.push(fld('Wert', 'et-val', ''));
    h.push('<button class="btn-sm green" style="margin-top:8px" onclick="EDIT._tagAdd(\'' + oid + '\')">＋ Tag vormerken</button>');
    h.push('<div class="dim" style="margin-top:8px">✦ = es liegt bereits eine vorgemerkte Änderung vor (wird beim Speichern angewendet).</div>');
    h.push('</div>');
    openModal('🏷️ Tags bearbeiten', h.join(''), '<button class="btn-sm" onclick="EDIT.modalClose()">Fertig</button>');
  }
  function _tagEdit(oid, pid) {
    var raw = null, all = rowsOf('t_objectproperties'), i;
    for (i = 0; i < all.length; i++) { if (String(rv(all[i], 'PropertyID')) === String(pid)) { raw = all[i]; break; } }
    if (!raw) { toast('Tag nicht gefunden.'); return; }
    var pend = findPending('tag.set', 'tag:' + pid);
    var curProp = s0(rv(raw, 'Property')), curVal = s0(rv(raw, 'Value')), curNotes = s0(rv(raw, 'Notes'));
    if (pend) {
      if (has(pend.fields, 'Property')) curProp = pend.fields.Property;
      if (has(pend.fields, 'Value')) curVal = pend.fields.Value;
      if (has(pend.fields, 'Notes')) curNotes = pend.fields.Notes;
    }
    var body = '<div class="eform">' + fld('Eigenschaft', 'te-prop', curProp) + fld('Wert', 'te-val', curVal) + fld('Notiz (optional)', 'te-notes', curNotes) + '</div>';
    formHandler = function () {
      var pr = gv('te-prop'), va = gv('te-val'), no = gv('te-notes');
      var fields = {}, subs = [], t1;
      t1 = diffLine('Eigenschaft', s0(rv(raw, 'Property')), pr); if (t1) { fields.Property = pr; subs.push(t1); }
      t1 = diffLine('Wert', s0(rv(raw, 'Value')), va); if (t1) { fields.Value = va; subs.push(t1); }
      t1 = diffLine('Notiz', s0(rv(raw, 'Notes')), no); if (t1) { fields.Notes = no; subs.push(t1); }
      if (!keys(fields)) { toast('Keine Änderung.'); modalClose(); return; }
      modalClose();
      q({ kind: 'tag.set', key: 'tag:' + pid, id: Number(pid), oid: oid, fields: fields, label: 'Tag „' + shortLabel(pr, 40) + '“', sub: subs.join('\n') });
      tagOpen(oid);
    };
    openModal('🏷️ Tag bearbeiten', body, okFooter('Änderung vormerken'));
  }
  function _tagDel(oid, pid) {
    q({ kind: 'tag.del', key: 'tagdel:' + pid, id: Number(pid), oid: oid, label: 'Tag entfernen (Element „' + shortLabel((OBJS[oid] || {}).name || oid, 34) + '“)', sub: 'PropertyID ' + pid });
    tagOpen(oid);
  }
  function _tagAdd(oid) {
    var pr = gv('et-prop'), va = gv('et-val');
    if (!pr) { toast('Bitte eine Eigenschaft angeben.'); return; }
    q({ kind: 'tag.add', oid: oid, prop: pr, val: va, label: 'Neuer Tag „' + shortLabel(pr, 40) + '“', sub: 'Wert: „' + shortLabel(va, 50) + '“' });
    tagOpen(oid);
  }

  /* ================= Neu: Element ================= */
  function elNew(pid) {
    var p = PKG[pid];
    if (!p) { toast('Paket nicht gefunden.'); return; }
    var types = objectTypeList();
    var body = '<div class="eform">' +
      '<label>Objekttyp</label>' + sel('en-type', types, 'Class') +
      fld('Name', 'en-name', '') +
      fld('Stereotype', 'en-st', '') +
      fldTA('Beschreibung / Notiz', 'en-note', '') +
      '<div class="dim">Neues Element im Paket <b>„' + esc(p.name) + '“</b>' + (p.path ? ' (' + esc(p.shortPath || p.path) + ')' : '') + '.</div>' +
      '</div>';
    formHandler = function () {
      var ty = gv('en-type'), nm = gv('en-name'), st = gv('en-st'), nt = gv('en-note');
      if (!nm) { toast('Bitte einen Namen angeben.'); return; }
      modalClose();
      q({ kind: 'el.create', pkgId: Number(pid), objType: ty, name: nm, stereotype: st, note: nt, label: 'Neues Element „' + shortLabel(nm, 44) + '“', sub: 'Typ: ' + ty + ' · Paket: ' + shortLabel(p.name, 40) });
    };
    openModal('➕ Neues Element anlegen', body, okFooter('Element vormerken'));
  }

  /* ================= Neu: Beziehung ================= */
  var _connEndSearch = function () {
    var inp = el('cn-endq');
    var res = el('cn-endres');
    if (!inp || !res) return;
    var qq = norm(inp.value || '').toLowerCase();
    if (!qq) { res.style.display = 'none'; res.innerHTML = ''; return; }
    var ids = Object.keys(OBJS), i, o, n = 0, h = '';
    for (i = 0; i < ids.length && n < 9; i++) {
      o = OBJS[ids[i]];
      if (String(o.id) === String(_connSrcOid)) continue;
      if (o.type === 'Package') continue;
      if ((o.name + ' ' + o.alias + ' ' + o.st).toLowerCase().indexOf(qq) >= 0) {
        h += '<div class="epickrow" onclick="EDIT._connEndPick(\'' + o.id + '\')"><b>' + esc(o.name) + '</b> <span class="dim">' + esc(o.st || '') + ' · ' + esc(o.pkg || '') + '</span></div>';
        n++;
      }
    }
    if (!h) h = '<div class="epickrow dim">Keine Treffer.</div>';
    res.innerHTML = h;
    res.style.display = 'block';
  };
  function connNew(oid) {
    oid = String(oid);
    var o = OBJS[oid];
    if (!o) return;
    _connSrcOid = oid;
    _connEndOid = null;
    var types = connTypeList();
    var body = '<div class="eform">' +
      '<div class="dim">Quelle: <b>' + esc(o.name) + '</b> <span>' + esc(o.st || '') + '</span></div>' +
      '<label>Ziel-Element suchen &amp; anklicken</label>' +
      '<input type="text" id="cn-endq" placeholder="🔍 Name / Alias / Stereotype …" oninput="EDIT._connEndSearch()">' +
      '<div class="epickres" id="cn-endres"></div>' +
      '<div id="cn-endsel" class="pchipsel" style="display:none"></div>' +
      '<label>Beziehungstyp</label>' + sel('cn-type', types, 'Dependency') +
      fld('Beziehungsname (optional)', 'cn-name', '') +
      fld('Stereotype', 'cn-st', '') +
      '<label>Richtung</label>' + sel('cn-dir', DIRECTIONS, 'Source -> Destination') +
      fldTA('Beschreibung / Notiz', 'cn-note', '') +
      '</div>';
    formHandler = function () {
      if (!_connEndOid) { toast('Bitte zuerst das Ziel-Element auswählen.'); return; }
      var ty = gv('cn-type'), nm = gv('cn-name'), st = gv('cn-st'), dir = gv('cn-dir'), nt = gv('cn-note');
      var target = OBJS[String(_connEndOid)];
      modalClose();
      q({ kind: 'conn.create', a: Number(oid), b: Number(_connEndOid), connType: ty, name: nm, stereotype: st, direction: dir, note: nt, label: 'Neue Beziehung „' + shortLabel(nm || ty, 40) + '“', sub: shortLabel(o.name, 34) + ' → ' + shortLabel(target ? target.name : _connEndOid, 34) + ' · Typ: ' + ty });
    };
    openModal('➕ Neue Beziehung anlegen', body, okFooter('Beziehung vormerken'));
  }
  var _connEndPick = function (oid) {
    _connEndOid = oid;
    var o = OBJS[String(oid)];
    var s = el('cn-endsel');
    if (s) {
      s.innerHTML = '<span>Ziel:</span> <b>' + esc(o ? o.name : oid) + '</b> <a href="javascript:void(0)" onclick="EDIT._connEndClear()">✕ ändern</a>';
      s.style.display = 'inline-flex';
    }
    var res = el('cn-endres'); if (res) { res.style.display = 'none'; }
    var inp = el('cn-endq'); if (inp) inp.value = '';
    toast('Ziel gewählt: ' + shortLabel(o ? o.name : oid, 40));
  };
  var _connEndClear = function () {
    _connEndOid = null;
    var s = el('cn-endsel'); if (s) { s.style.display = 'none'; s.innerHTML = ''; }
  };

  /* ================= Löschen: Element ================= */
  function elDel(oid) {
    oid = String(oid);
    var o = OBJS[oid];
    if (!o) return;
    if (o.type === 'Package') { toast('Pakete werden hier nicht gelöscht — bitte in Sparx EA.'); return; }
    var conns = 0, i, kinds = [];
    for (i = 0; i < CONS.length; i++) { if (String(CONS[i].a) === oid || String(CONS[i].b) === oid) { conns++; if (kinds.length < 4) kinds.push(s0(CONS[i].st) || s0(CONS[i].type)); } }
    var dgs = 0, k;
    for (k in DIAGOBJ) if (has(DIAGOBJ, k)) { var arr = DIAGOBJ[k]; for (i = 0; i < arr.length; i++) if (String(arr[i].oid) === oid) dgs++; }
    var tags = (TAGS[oid] || []).length;
    var attrs = 0, ar = rowsOf('t_attribute');
    for (i = 0; i < ar.length; i++) if (String(rv(ar[i], 'Object_ID')) === oid) attrs++;
    var body = '<div class="eform"><div class="danger"><b>Element „' + esc(o.name) + '“ aus der Datei entfernen?</b><br>' +
      'Beim Speichern werden mitentfernt:<br>• <b>' + conns + '</b> Beziehung(en)' + (kinds.length ? ' (u. a. ' + esc(kinds.join(', ')) + ')' : '') + '<br>' +
      '• <b>' + dgs + '</b> Sicht-Platzierung(en) (t_diagramobjects)<br>' +
      '• <b>' + tags + '</b> Tag(s)' + (attrs ? '<br>• <b>' + attrs + '</b> Attribut(e)' : '') + '<br>• zugehörige xref-/Link-Einträge.</div>' +
      '<div class="dim">Die Aktion wird erst beim Speichern in der neuen Datei wirksam — Original bleibt unverändert.</div></div>';
    formHandler = function () {
      modalClose();
      q({ kind: 'el.del', key: 'eldel:' + oid, id: Number(oid), label: '🗑 Element „' + shortLabel(o.name, 40) + '“ löschen', sub: 'Entfernt ' + conns + ' Beziehung(en), ' + dgs + ' Sicht-Platzierung(en), ' + tags + ' Tag(s)' + (attrs ? ', ' + attrs + ' Attribut(e)' : '') + '.' });
    };
    openModal('🗑 Element löschen', body, '<button class="btn-sm" onclick="EDIT.modalClose()">Abbrechen</button><button class="btn-sm danger" onclick="EDIT.formOk()">Löschen vormerken</button>');
  }

  /* ================= Löschen: Beziehung ================= */
  function connDel(cid) {
    if (cid == null) return;
    var raw = findRow('t_connector', 'Connector_ID', cid);
    if (!raw) { toast('Beziehung nicht gefunden.'); return; }
    var a = OBJS[String(rv(raw, 'Start_Object_ID'))], b = OBJS[String(rv(raw, 'End_Object_ID'))];
    var body = '<div class="eform"><div class="danger"><b>Beziehung entfernen?</b><br>' +
      '„' + esc(a ? a.name : '?') + '“ → „' + esc(b ? b.name : '?') + '“ · Typ ' + esc(s0(rv(raw, 'Connector_Type'))) + (s0(rv(raw, 'Stereotype')) ? ' · «' + esc(s0(rv(raw, 'Stereotype'))) + '»' : '') +
      '<br><span class="dim">Wird beim Speichern aus t_connector, den Diagramm-Links und den Architektur-Eigenschaften entfernt.</span></div></div>';
    formHandler = function () {
      modalClose();
      q({ kind: 'conn.del', key: 'conndel:' + cid, id: Number(cid), label: '🗑 Beziehung „' + shortLabel(s0(rv(raw, 'Stereotype')) || s0(rv(raw, 'Connector_Type')), 34) + '“ zwischen „' + shortLabel(a ? a.name : '?', 28) + '“ und „' + shortLabel(b ? b.name : '?', 28) + '“', sub: '' });
    };
    openModal('🗑 Beziehung löschen', body, '<button class="btn-sm" onclick="EDIT.modalClose()">Abbrechen</button><button class="btn-sm danger" onclick="EDIT.formOk()">Löschen vormerken</button>');
  }

  /* ================= Quelle (Original-Bytes) ================= */
  function setSource(buffer, name) {
    try {
      srcBytes = (buffer instanceof Uint8Array) ? new Uint8Array(buffer) : new Uint8Array(buffer);
    } catch (e) { srcBytes = null; }
    srcName = name || 'modell.qea';
    changes = [];
    changeId = 0;
    renderDrawer();
    updateBadge();
  }

  /* ================= SQLite-Engine (sql.js) ================= */
  function loadSQL() {
    if (sqlPromise) return sqlPromise;
    sqlPromise = new Promise(function (resolve, reject) {
      if (typeof initSqlJs !== 'function') { reject(new Error('SQLite-Engine (sql.js) nicht geladen — Edit-Edition unvollständig gebaut?')); return; }
      var b64 = window.SQLJS_WASM_B64 || '';
      if (!b64) { reject(new Error('Eingebettete WASM-Daten fehlen.')); return; }
      var bin, i, n, u8;
      try {
        bin = atob(b64);
        n = bin.length;
        u8 = new Uint8Array(n);
        for (i = 0; i < n; i++) u8[i] = bin.charCodeAt(i);
      } catch (e) { reject(new Error('WASM-Daten konnten nicht dekodiert werden.')); return; }
      /* 1) bevorzugt: wasmBinary direkt (funktioniert auch bei file://) */
      var tried = false;
      function fallback() {
        if (tried) return; tried = true;
        try {
          var url = URL.createObjectURL(new Blob([u8], { type: 'application/wasm' }));
          initSqlJs({ locateFile: function () { return url; } }).then(resolve, reject);
        } catch (e2) { reject(e2); }
      }
      try {
        initSqlJs({ wasmBinary: u8.buffer }).then(resolve, function () { fallback(); });
      } catch (e3) { fallback(); }
    });
    return sqlPromise;
  }
  function execRows(db, sql, params) {
    var st = db.prepare(sql), rows = [];
    if (params) st.bind(params);
    while (st.step()) rows.push(st.getAsObject());
    st.free();
    return rows;
  }
  function one(db, sql, params) { var r = execRows(db, sql, params); return r.length ? r[0] : null; }
  function tablesSet(db) {
    var m = {}, r = db.exec("SELECT name FROM sqlite_master WHERE type='table'");
    if (r.length) for (var i = 0; i < r[0].values.length; i++) m[r[0].values[i][0]] = true;
    return m;
  }
  function colNames(db, table) {
    var out = [], r = db.exec('PRAGMA table_info(' + table + ')');
    if (r.length) for (var i = 0; i < r[0].values.length; i++) out.push(r[0].values[i][1]);
    return out;
  }

  /* Stereotype-Eintrag in t_xref nachführen (EA: '@STEREO;Name=…;FQName=…;')
     AAroN-Referenz (schmitze87/AAroN, EAXref/XRefProcessor): t_xref.Client =
     ea_guid des Elements/Connectors, Type = 'element property' bzw.
     'connector property', Description = '@STEREO;Name=…;FQName=…;@ENDSTEREO;'.
     Beim Anlegen fehlte der Eintrag bisher komplett — jetzt wird er ergänzt. */
  function stereoXrefSync(db, guid, type, newSt) {
    if (!guid) return;
    var rows = execRows(db, 'SELECT XrefID, Description FROM t_xref WHERE Client=? AND Type=?', [guid, type]);
    var found = false;
    for (var i = 0; i < rows.length; i++) {
      var desc = s0(rows[i].Description);
      if (desc.indexOf('@STEREO;') !== 0) continue;
      found = true;
      if (!newSt) { db.run('DELETE FROM t_xref WHERE XrefID=?', [rows[i].XrefID]); continue; }
      var newDesc, m = /FQName=([^;]*);/.exec(desc);
      if (m && m[1]) {
        var fq = m[1], ix = fq.lastIndexOf('::');
        newDesc = '@STEREO;Name=' + newSt + ';FQName=' + (ix >= 0 ? fq.substring(0, ix + 2) + newSt : newSt) + ';@ENDSTEREO;';
      } else {
        newDesc = '@STEREO;Name=' + newSt + ';@ENDSTEREO;';
      }
      db.run('UPDATE t_xref SET Description=? WHERE XrefID=?', [newDesc, rows[i].XrefID]);
    }
    if (!found && newSt) {
      var fqName = '';
      var tpl = execRows(db, 'SELECT Description FROM t_xref WHERE Description LIKE ? LIMIT 1', ['@STEREO;Name=' + newSt + ';%']);
      if (tpl.length) {
        var tm = /FQName=([^;]*);/.exec(s0(tpl[0].Description));
        if (tm && tm[1]) fqName = tm[1];
      }
      /* Neuanlage: FQName immer mitschreiben (EA-Konvention). Vorzug aus
         vorhandener Vorlage mit gleichem Stereotyp (Profil-Information),
         sonst der Stereotyp selbst (unprofiliert, wie EA bei neuen Werten). */
      var insDesc = '@STEREO;Name=' + newSt + ';FQName=' + (fqName || newSt) + ';@ENDSTEREO;';
      db.run('INSERT INTO t_xref (XrefID, Type, Description, Client) VALUES (?,?,?,?)', [newGuid(), type, insDesc, guid]);
    }
  }

  /* Eine Änderung auf die SQLite-Verbindung anwenden */
  function applyChange(db, ch) {
    var now = nowStamp(), f = ch.fields || {}, i, t;
    if (ch.kind === 'el.set') {
      var sets = [], vals = [];
      if (has(f, 'Name')) { sets.push('Name=?'); vals.push(f.Name); }
      if (has(f, 'Stereotype')) { sets.push('Stereotype=?'); vals.push(f.Stereotype || null); }
      if (has(f, 'Alias')) { sets.push('Alias=?'); vals.push(f.Alias || null); }
      if (has(f, 'Status')) { sets.push('Status=?'); vals.push(f.Status || null); }
      if (has(f, 'Note')) { sets.push('Note=?'); vals.push(encNote(f.Note) || null); }
      sets.push('ModifiedDate=?'); vals.push(now);
      vals.push(ch.id);
      db.run('UPDATE t_object SET ' + sets.join(', ') + ' WHERE Object_ID=?', vals);
      if (has(f, 'Stereotype')) {
        var g1 = one(db, 'SELECT ea_guid FROM t_object WHERE Object_ID=?', [ch.id]);
        stereoXrefSync(db, g1 ? g1.ea_guid : null, 'element property', f.Stereotype);
      }
      return;
    }
    if (ch.kind === 'pkg.set') {
      var psets = [], pvals = [];
      if (has(f, 'Name')) { psets.push('Name=?'); pvals.push(f.Name); }
      if (has(f, 'Notes')) { psets.push('Notes=?'); pvals.push(encNote(f.Notes)); }
      psets.push('ModifiedDate=?'); pvals.push(now); pvals.push(ch.id);
      db.run('UPDATE t_package SET ' + psets.join(', ') + ' WHERE Package_ID=?', pvals);
      var p = one(db, 'SELECT ea_guid FROM t_package WHERE Package_ID=?', [ch.id]);
      if (p && p.ea_guid) {
        var osets = [], ovals = [];
        if (has(f, 'Name')) { osets.push('Name=?'); ovals.push(f.Name); }
        if (has(f, 'Notes')) { osets.push('Note=?'); ovals.push(encNote(f.Notes)); }
        if (osets.length) {
          osets.push('ModifiedDate=?'); ovals.push(now); ovals.push(p.ea_guid);
          db.run('UPDATE t_object SET ' + osets.join(', ') + ' WHERE ea_guid=?', ovals);
        }
      }
      return;
    }
    if (ch.kind === 'diag.set') {
      var dsets = [], dvals = [];
      if (has(f, 'Name')) { dsets.push('Name=?'); dvals.push(f.Name); }
      if (has(f, 'Notes')) { dsets.push('Notes=?'); dvals.push(encNote(f.Notes)); }
      dsets.push('ModifiedDate=?'); dvals.push(now); dvals.push(ch.id);
      db.run('UPDATE t_diagram SET ' + dsets.join(', ') + ' WHERE Diagram_ID=?', dvals);
      return;
    }
    if (ch.kind === 'conn.set') {
      var csets = [], cvals = [];
      if (has(f, 'Name')) { csets.push('Name=?'); cvals.push(f.Name || null); }
      if (has(f, 'Stereotype')) { csets.push('Stereotype=?'); cvals.push(f.Stereotype || null); }
      if (has(f, 'Direction')) { csets.push('Direction=?'); cvals.push(f.Direction || null); }
      if (has(f, 'Notes')) { csets.push('Notes=?'); cvals.push(encNote(f.Notes) || null); }
      cvals.push(ch.id);
      db.run('UPDATE t_connector SET ' + csets.join(', ') + ' WHERE Connector_ID=?', cvals);
      if (has(f, 'Stereotype')) {
        var g2 = one(db, 'SELECT ea_guid FROM t_connector WHERE Connector_ID=?', [ch.id]);
        stereoXrefSync(db, g2 ? g2.ea_guid : null, 'connector property', f.Stereotype);
        if (ch.oldStereotype) {
          var lblCols = ['Top_Start_Label', 'Top_Mid_Label', 'Top_End_Label', 'Btm_Start_Label', 'Btm_Mid_Label', 'Btm_End_Label'];
          var oldLbl = '«' + ch.oldStereotype + '»', newLbl = f.Stereotype ? ('«' + f.Stereotype + '»') : '';
          for (i = 0; i < lblCols.length; i++) {
            db.run('UPDATE t_connector SET ' + lblCols[i] + "=REPLACE(COALESCE(" + lblCols[i] + ",''), ?, ?) WHERE Connector_ID=? AND COALESCE(" + lblCols[i] + ",'') LIKE '%'||?||'%'", [oldLbl, newLbl, ch.id, oldLbl]);
          }
        }
      }
      return;
    }
    if (ch.kind === 'tag.set') {
      var tsets = [], tvals = [];
      if (has(f, 'Property')) { tsets.push('Property=?'); tvals.push(f.Property); }
      if (has(f, 'Value')) { tsets.push('Value=?'); tvals.push(f.Value == null ? null : String(f.Value)); }
      if (has(f, 'Notes')) { tsets.push('Notes=?'); tvals.push(f.Notes || null); }
      if (!tsets.length) return;
      tvals.push(ch.id);
      db.run('UPDATE t_objectproperties SET ' + tsets.join(', ') + ' WHERE PropertyID=?', tvals);
      return;
    }
    if (ch.kind === 'tag.add') {
      db.run('INSERT INTO t_objectproperties (Object_ID, Property, Value, Notes, ea_guid) VALUES (?,?,?,?,?)', [Number(ch.oid), ch.prop, ch.val == null ? '' : String(ch.val), null, newGuid()]);
      return;
    }
    if (ch.kind === 'tag.del') {
      db.run('DELETE FROM t_objectproperties WHERE PropertyID=?', [ch.id]);
      return;
    }
    if (ch.kind === 'el.create') {
      var cols = colNames(db, 't_object');
      var t1 = execRows(db, 'SELECT * FROM t_object WHERE Object_Type=? LIMIT 1', [ch.objType]);
      var tmpl = t1.length ? t1[0] : one(db, 'SELECT * FROM t_object WHERE Object_Type=? LIMIT 1', ['Class']);
      if (!tmpl) tmpl = {};
      var row = {};
      for (i = 0; i < cols.length; i++) row[cols[i]] = has(tmpl, cols[i]) ? tmpl[cols[i]] : null;
      row.Object_Type = ch.objType;
      row.Name = ch.name;
      row.Stereotype = ch.stereotype || null;
      row.Alias = null;
      row.Note = ch.note ? encNote(ch.note) : null;
      row.Package_ID = ch.pkgId;
      row.ea_guid = newGuid();
      row.CreatedDate = now; row.ModifiedDate = now;
      row.Author = '';
      row.Status = 'Proposed';
      row.Diagram_ID = 0; row.TPos = 0; row.ParentID = 0; row.Classifier = 0;
      row.StyleEx = null; row.StateFlags = null; row.ActionFlags = null; row.EventFlags = null; row.PackageFlags = null; row.Classifier_guid = null;
      if (has(row, 'Object_ID')) delete row.Object_ID;
      var ic = [], ph = [], iv = [];
      for (var k1 in row) if (has(row, k1)) { ic.push(k1); ph.push('?'); iv.push(row[k1] === undefined ? null : row[k1]); }
      db.run('INSERT INTO t_object (' + ic.join(',') + ') VALUES (' + ph.join(',') + ')', iv);
      stereoXrefSync(db, row.ea_guid, 'element property', ch.stereotype);
      return;
    }
    if (ch.kind === 'conn.create') {
      var ccols = colNames(db, 't_connector');
      var t2 = execRows(db, 'SELECT * FROM t_connector WHERE Connector_Type=? LIMIT 1', [ch.connType]);
      var tmpl2 = t2.length ? t2[0] : one(db, 'SELECT * FROM t_connector LIMIT 1');
      if (!tmpl2) tmpl2 = {};
      var crow = {};
      for (i = 0; i < ccols.length; i++) crow[ccols[i]] = has(tmpl2, ccols[i]) ? tmpl2[ccols[i]] : null;
      crow.Connector_Type = ch.connType;
      crow.Start_Object_ID = ch.a;
      crow.End_Object_ID = ch.b;
      crow.Name = ch.name || null;
      crow.Stereotype = ch.stereotype || null;
      crow.Notes = ch.note ? encNote(ch.note) : null;
      crow.Direction = ch.direction || 'Source -> Destination';
      crow.ea_guid = newGuid();
      crow.DiagramID = 0;
      var nulls = ['Top_Start_Label', 'Top_Mid_Label', 'Top_End_Label', 'Btm_Start_Label', 'Btm_Mid_Label', 'Btm_End_Label', 'PDATA1', 'PDATA2', 'PDATA3', 'PDATA4', 'PDATA5', 'StyleEx', 'StateFlags', 'ActionFlags', 'EventFlags'];
      for (i = 0; i < nulls.length; i++) if (has(crow, nulls[i])) crow[nulls[i]] = null;
      if (has(crow, 'Connector_ID')) delete crow.Connector_ID;
      var ic2 = [], ph2 = [], iv2 = [];
      for (var k2 in crow) if (has(crow, k2)) { ic2.push(k2); ph2.push('?'); iv2.push(crow[k2] === undefined ? null : crow[k2]); }
      db.run('INSERT INTO t_connector (' + ic2.join(',') + ') VALUES (' + ph2.join(',') + ')', iv2);
      stereoXrefSync(db, crow.ea_guid, 'connector property', ch.stereotype);
      return;
    }
    if (ch.kind === 'el.del') {
      var g3 = one(db, 'SELECT ea_guid FROM t_object WHERE Object_ID=?', [ch.id]);
      var myGuid = g3 ? g3.ea_guid : null;
      var cgs = execRows(db, 'SELECT ea_guid FROM t_connector WHERE Start_Object_ID=? OR End_Object_ID=?', [ch.id, ch.id]);
      var sub = 'SELECT Connector_ID FROM t_connector WHERE Start_Object_ID=? OR End_Object_ID=?';
      if (T_ok('t_connectortag')) db.run('DELETE FROM t_connectortag WHERE ElementID IN (' + sub + ')', [ch.id, ch.id]);
      if (T_ok('t_diagramlinks')) db.run('DELETE FROM t_diagramlinks WHERE ConnectorID IN (' + sub + ')', [ch.id, ch.id]);
      for (i = 0; i < cgs.length; i++) if (cgs[i].ea_guid) db.run("DELETE FROM t_xref WHERE Client=? AND Type='connector property'", [cgs[i].ea_guid]);
      db.run('DELETE FROM t_connector WHERE Start_Object_ID=? OR End_Object_ID=?', [ch.id, ch.id]);
      if (T_ok('t_attributetag') && T_ok('t_attribute')) db.run('DELETE FROM t_attributetag WHERE ElementID IN (SELECT ID FROM t_attribute WHERE Object_ID=?)', [ch.id]);
      if (T_ok('t_attribute')) db.run('DELETE FROM t_attribute WHERE Object_ID=?', [ch.id]);
      var sat = ['t_objectconstraint', 't_objecteffort', 't_objectfiles', 't_objectmetrics', 't_objectproblems', 't_objectproperties', 't_objectrequires', 't_objectresource', 't_objectrisks', 't_objectscenarios', 't_objecttests', 't_objecttrx', 't_method'];
      for (i = 0; i < sat.length; i++) { t = sat[i]; if (T_ok(t)) db.run('DELETE FROM ' + t + ' WHERE Object_ID=?', [ch.id]); }
      if (T_ok('t_diagramobjects')) db.run('DELETE FROM t_diagramobjects WHERE Object_ID=?', [ch.id]);
      if (T_ok('t_document')) db.run('DELETE FROM t_document WHERE ElementID=?', [ch.id]);
      if (myGuid) db.run("DELETE FROM t_xref WHERE Client=? AND Type='element property'", [myGuid]);
      db.run('DELETE FROM t_object WHERE Object_ID=?', [ch.id]);
      return;
    }
    if (ch.kind === 'conn.del') {
      var g4 = one(db, 'SELECT ea_guid FROM t_connector WHERE Connector_ID=?', [ch.id]);
      if (T_ok('t_connectortag')) db.run('DELETE FROM t_connectortag WHERE ElementID=?', [ch.id]);
      if (T_ok('t_diagramlinks')) db.run('DELETE FROM t_diagramlinks WHERE ConnectorID=?', [ch.id]);
      if (g4 && g4.ea_guid) db.run("DELETE FROM t_xref WHERE Client=? AND Type='connector property'", [g4.ea_guid]);
      db.run('DELETE FROM t_connector WHERE Connector_ID=?', [ch.id]);
      return;
    }
    throw new Error('Unbekannte Änderungsart: ' + ch.kind);
  }
  /* Tabellen-Check für die aktuelle Speicher-Session */
  var _tables = {};
  function T_ok(t) { return !!_tables[t]; }

  /* ================= Speichern ================= */
  function makeFileName() {
    var base = srcName.replace(/\.(qea|qeax|eapx|sqlite)$/i, '');
    if (!base) base = 'Modell';
    return base + '_bearbeitet_' + fileStamp() + '.qea';
  }
  function snapCounts(db) {
    var keysL = ['t_object', 't_connector', 't_objectproperties', 't_diagramobjects', 't_diagram', 't_package'];
    var o = {};
    for (var i = 0; i < keysL.length; i++) {
      try { var r = db.exec('SELECT COUNT(*) FROM ' + keysL[i]); o[keysL[i]] = r.length ? r[0].values[0][0] : -1; } catch (e) { o[keysL[i]] = -1; }
    }
    return o;
  }
  var COUNT_LABEL = { t_object: 'Elemente', t_connector: 'Beziehungen', t_objectproperties: 'Tags', t_diagramobjects: 'Sicht-Platzierungen', t_diagram: 'Sichten', t_package: 'Pakete' };
  function deltaStr(b, a) {
    var parts = [];
    for (var k in COUNT_LABEL) if (has(COUNT_LABEL, k)) {
      if (b[k] !== a[k]) parts.push(COUNT_LABEL[k] + ' ' + b[k] + ' → ' + a[k]);
    }
    return parts.length ? parts.join(' · ') : 'keine Bestandsänderungen (nur Feldwerte aktualisiert)';
  }
  function reenableSave() {
    var b = el('edr-save');
    if (b) { b.disabled = false; b.textContent = '💾 Als neue .qea speichern'; }
  }
  function failSave(msg) {
    openModal('⚠️ Speichern nicht möglich',
      '<div class="eform"><div class="danger"><b>Es wurde nichts geschrieben.</b><br>' + esc(msg) + '</div>' +
      '<div class="dim">Die Originaldatei und Ihre Vormerkliste bleiben unverändert.</div></div>',
      '<button class="btn-sm" onclick="EDIT.modalClose()">OK</button>');
    reenableSave();
  }
  function save() {
    if (!changes.length) { toast('Keine Änderungen vorgemerkt.'); return; }
    if (!srcBytes) { toast('Keine QEA-Datei geladen.'); return; }
    var n = changes.length, list = changes.slice();
    var sb = el('edr-save');
    if (sb) { sb.disabled = true; sb.textContent = '⏳ Schreibe …'; }
    _tables = {};
    loadSQL().then(function (SQL) {
      var db;
      try { db = new SQL.Database(srcBytes); }
      catch (e) { failSave('QEA-Datei konnte nicht in der SQLite-Engine geöffnet werden: ' + e.message); return; }
      try {
        _tables = tablesSet(db);
        var before = snapCounts(db);
        db.run('BEGIN');
        for (var i = 0; i < list.length; i++) applyChange(db, list[i]);
        var chk = db.exec('PRAGMA integrity_check');
        var okv = (chk.length && chk[0].values.length) ? String(chk[0].values[0][0]) : '?';
        if (okv.toLowerCase() !== 'ok') throw new Error('SQLite-Integritätsprüfung meldet: ' + okv);
        db.run('COMMIT');
        var after = snapCounts(db);
        var out = db.export();
        /* Selbsttest: mit der eingebauten Reader-Engine erneut einlesen */
        var probe;
        try { probe = qeaOpen(out.slice().buffer); }
        catch (e2) { throw new Error('Selbsttest fehlgeschlagen (Ausgabedatei nicht lesbar): ' + e2.message); }
        var cnt2 = { t_object: 0 };
        try { cnt2.t_object = probe.rows('t_object').length; } catch (e3) { }
        if (after.t_object >= 0 && cnt2.t_object !== after.t_object) {
          throw new Error('Selbsttest: Elementzahl weicht ab (' + cnt2.t_object + ' vs. ' + after.t_object + ').');
        }
        var fname = makeFileName();
        var dstr = deltaStr(before, after);
        /* Ausliefern */
        if (typeof window.__editSink === 'function') {
          try { window.__editSink(out, fname); } catch (e4) { }
        } else {
          var blob = new Blob([out], { type: 'application/octet-stream' });
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url; a.download = fname;
          document.body.appendChild(a);
          a.click();
          setTimeout(function () { try { document.body.removeChild(a); URL.revokeObjectURL(url); } catch (e5) { } }, 4000);
        }
        /* Erfolgsfenster */
        openModal('✅ Änderungen gespeichert',
          '<div class="eform"><p style="font-size:13px"><b>' + n + '</b> Änderungen wurden in eine <b>neue Datei</b> geschrieben:</p>' +
          '<div class="ok"><b>' + esc(fname) + '</b><br><span class="dim">' + esc(dstr) + '</span></div>' +
          '<p class="dim">Die Originaldatei wurde nicht verändert. Empfehlung: Die neue Datei zunächst in einer Kopie mit Sparx EA öffnen und prüfen.</p></div>',
          '<button class="btn-sm pri" onclick="EDIT.modalClose()">OK</button>');
        /* Ansicht auf den gespeicherten Stand aktualisieren (setzt auch die Vormerkliste zurück) */
        setTimeout(function () {
          try { loadQea(out.slice().buffer, fname); toast('Ansicht auf gespeicherten Stand aktualisiert.'); }
          catch (e6) { }
        }, 80);
      } catch (e) {
        try { db.run('ROLLBACK'); } catch (e7) { }
        failSave(e.message || String(e));
      } finally {
        try { db.close(); } catch (e8) { }
        reenableSave();
      }
    }, function (e) {
      failSave('SQLite-Engine konnte nicht geladen werden: ' + (e && e.message ? e.message : e));
    });
  }

  /* ================= CSV-Protokoll ================= */
  function csvc(v) {
    v = s0(v);
    if (v.indexOf(';') >= 0 || v.indexOf('"') >= 0 || v.indexOf('\n') >= 0) {
      return '"' + v.replace(/"/g, '""') + '"';
    }
    return v;
  }
  function exportCSV() {
    if (!changes.length) { toast('Keine Änderungen vorgemerkt.'); return; }
    var labels = { 'el.set': 'Element geändert', 'pkg.set': 'Paket geändert', 'diag.set': 'Sicht geändert', 'conn.set': 'Beziehung geändert', 'tag.set': 'Tag geändert', 'tag.add': 'Tag neu', 'tag.del': 'Tag entfernt', 'el.create': 'Element neu', 'conn.create': 'Beziehung neu', 'el.del': 'Element gelöscht', 'conn.del': 'Beziehung gelöscht' };
    var lines = ['Nr;Aktion;Objekt;Details'];
    for (var i = 0; i < changes.length; i++) {
      var c = changes[i];
      lines.push([String(i + 1), csvc(labels[c.kind] || c.kind), csvc(c.label), csvc(s0(c.sub).replace(/\n/g, ' | '))].join(';'));
    }
    downloadText('ADMBw_Aenderungen_' + safeName(MODELLNAME || 'Modell') + '_' + fileStamp() + '.csv', '\ufeff' + 'sep=;\r\n' + lines.join('\r\n'));
  }

  /* ================= Export der Fassade ================= */
  return {
    version: 'v5.0',
    setSource: setSource,
    q: q,
    save: save,
    removeChange: removeChange,
    clearAll: clearAll,
    clearAllConfirm: clearAllConfirm,
    _clearConfirmOk: _clearConfirmOk,
    openPanel: openPanel,
    closePanel: closePanel,
    togglEdit: function () { },
    modalClose: modalClose,
    formOk: formOk,
    exportCSV: exportCSV,
    elEdit: elEdit,
    pkgEdit: pkgEdit,
    diagEdit: diagEdit,
    connEdit: connEdit,
    tagOpen: tagOpen,
    elNew: elNew,
    connNew: connNew,
    elDel: elDel,
    connDel: connDel,
    pkgIdForObject: pkgIdForObject,
    _tagEdit: _tagEdit,
    _tagDel: _tagDel,
    _tagAdd: _tagAdd,
    _connEndSearch: _connEndSearch,
    _connEndPick: _connEndPick,
    _connEndClear: _connEndClear,
    _connDelFromEdit: _connDelFromEdit,
    _internal: { count: function () { return changes.length; }, list: function () { return changes.slice(); } }
  };
})();
