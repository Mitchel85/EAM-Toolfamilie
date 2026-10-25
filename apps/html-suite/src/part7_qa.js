/* ============================================================================
   EAM AI Suite v9.1 (KI-Edition) — Teil 7: RÜCKWEG (Frage & Antwort über die .qea)
   ----------------------------------------------------------------------------
   Getrennter Pfad zum KI-Architekten (Teil 6):

     Teil 6  = Aufbau/Änderung eines Modells im Speicher (JSON-Operationen).
     Teil 7  = LIES die geladene .qea (SQLite) und beantworte Fragen als TEXT.

   Es geht ausschließlich der gewählte Ausschnitt (ganzes Modell | Paket mit
   Unterpaketen | einzelnes Element) als kompakter Textkontext an den
   BESTEHENDEN KI-Endpunkt aus dem KI-Tab (keine zweite Konfiguration).
   Ohne API-Schlüssel wird eine lokale Beschreibung des Ausschnitts erzeugt
   und klar als „ohne KI“ gekennzeichnet.

   Kein Schlüssel wird gespeichert, geloggt oder exportiert.
   ============================================================================ */

var QA = (function () {
  'use strict';

  var MAX_CTX = 26000;     /* Zeichen, die maximal in den Prompt gehen */
  var MAX_NOTE = 320;      /* Zeichen je Notiz im Kontext */
  var MAX_LIST = 80;       /* Zeilen je Abschnitt in der lokalen Beschreibung */

  var ST = {
    scope: 'model',
    pkgId: '',
    oid: '',
    fileN: 0,
    answer: '',
    mode: '',              /* 'ki' | 'noki' */
    meta: null,
    selLabel: '',
    lastQ: '',
    busy: false
  };
  var CACHE = { db: null, tables: {} };

  /* ------------------------------ kleine Helfer ------------------------------ */
  function s(v) { return v == null ? '' : String(v); }
  function byId(id) { return document.getElementById(id); }
  function files() { return (typeof MODEL_FILES !== 'undefined' && MODEL_FILES) ? MODEL_FILES : []; }
  function modelName() { return (typeof MODELLNAME !== 'undefined' && MODELLNAME) ? String(MODELLNAME) : '(unbenannt)'; }
  function fileName() {
    var fs = files(), i, n = Number(ST.fileN);
    if (fs.length) {
      for (i = 0; i < fs.length; i++) if (Number(fs[i].n) === n) return s(fs[i].name);
      return s(fs[fs.length - 1].name);
    }
    return modelName();
  }
  function noteText(v) {
    var t;
    try { t = (typeof cleanNote === 'function') ? cleanNote(v) : s(v); }
    catch (e) { t = s(v); }
    t = s(t).replace(/\s+/g, ' ').trim();
    return t.length > MAX_NOTE ? t.substring(0, MAX_NOTE) + ' …' : t;
  }
  function shortPath(map, id) {
    var p = map[id], segs = [], guard = 0;
    while (p && guard < 30) {
      segs.unshift(p.name);
      if (!p.parent || p.parent === '0' || !map[p.parent]) break;
      p = map[p.parent];
      guard++;
    }
    return segs.join(' / ');
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function stamp() {
    var d = new Date();
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }
  function fileStamp() {
    var d = new Date();
    return d.getFullYear() + pad2(d.getMonth() + 1) + pad2(d.getDate()) + '-' + pad2(d.getHours()) + pad2(d.getMinutes());
  }
  function safeName(x) {
    return String(x || 'Modell').replace(/\.[a-z0-9]+$/i, '').replace(/[^\wäöüÄÖÜß\-]+/g, '_').replace(/^_+|_+$/g, '').substring(0, 60) || 'Modell';
  }

  /* --------------------------- Datenbank der geladenen Datei --------------------------- */
  function dbFor(n) {
    if (typeof MODEL_DBS !== 'undefined' && MODEL_DBS && MODEL_DBS[n]) return MODEL_DBS[n];
    return (typeof DB !== 'undefined') ? DB : null;
  }
  function curDb() {
    var fs = files(), i;
    if (fs.length > 1) {
      var n = Number(ST.fileN);
      if (!n) n = (typeof MODEL_N !== 'undefined' && MODEL_N) ? MODEL_N : fs[fs.length - 1].n;
      for (i = 0; i < fs.length; i++) {
        if (Number(fs[i].n) === n) return dbFor(n);
      }
      return dbFor(fs[0].n);
    }
    if (typeof MODEL_DB !== 'undefined' && MODEL_DB) return MODEL_DB;
    return (typeof DB !== 'undefined') ? DB : null;
  }
  function tableRows(name) {
    var d = curDb();
    if (!d || !d.rows) return [];
    if (CACHE.db !== d) CACHE = { db: d, tables: {} };
    if (!CACHE.tables[name]) {
      try { CACHE.tables[name] = d.rows(name) || []; }
      catch (e) { CACHE.tables[name] = []; }
    }
    return CACHE.tables[name];
  }
  function packageMap() {
    var rows = tableRows('t_package'), map = {}, i, id;
    for (i = 0; i < rows.length; i++) {
      id = s(rows[i].Package_ID);
      if (!id) continue;
      map[id] = {
        id: id,
        name: s(rows[i].Name) || ('Paket ' + id),
        parent: s(rows[i].Parent_ID) || '0',
        notes: noteText(rows[i].Notes)
      };
    }
    return map;
  }
  function isPackageRow(r) { return s(r.Object_Type) === 'Package'; }

  /* ---------------------------- Ausschnitt zusammenstellen ---------------------------- */
  function subtreeIds(map, rootId) {
    var out = {}, stack = [s(rootId)], guard = 0, id, k;
    while (stack.length && guard < 200000) {
      id = stack.pop();
      if (!id || out[id]) continue;
      out[id] = true;
      guard++;
      for (k in map) {
        if (map.hasOwnProperty(k) && map[k].parent === id) stack.push(k);
      }
    }
    return out;
  }

  /* Liefert den Ausschnitt als Rohdaten oder null, wenn nichts gewählt ist. */
  function buildSelection() {
    var map = packageMap();
    var objs = tableRows('t_object');
    var conns = tableRows('t_connector');
    var tags = tableRows('t_objectproperties');
    var kind = ST.scope;
    var sel = { kind: kind, label: '', pkgs: [], objs: [], conns: [], tags: [], ext: 0, pkgSet: {}, objSet: {} };
    var i, r, id, pid;

    if (kind === 'pkg') {
      if (!ST.pkgId || !map[ST.pkgId]) return null;
      sel.pkgSet = subtreeIds(map, ST.pkgId);
      sel.label = 'Paket „' + shortPath(map, ST.pkgId) + '“ (mit Unterpaketen)';
    } else if (kind === 'el') {
      if (!ST.oid) return null;
      for (i = 0; i < objs.length; i++) {
        if (s(objs[i].Object_ID) === s(ST.oid)) { r = objs[i]; break; }
      }
      if (!r) return null;
      sel.objSet[s(ST.oid)] = true;
      sel.label = 'Element „' + (s(r.Name) || '(ohne Name)') + '“' + (s(r.Stereotype) ? ' «' + s(r.Stereotype) + '»' : '');
    } else {
      sel.label = 'Ganzes Modell';
    }

    /* Elemente */
    for (i = 0; i < objs.length; i++) {
      r = objs[i];
      if (isPackageRow(r)) continue;
      id = s(r.Object_ID);
      if (!id) continue;
      if (kind === 'pkg' && !sel.pkgSet[s(r.Package_ID)]) continue;
      if (kind === 'el' && !sel.objSet[id]) continue;
      sel.objs.push(r);
      sel.objSet[id] = true;
    }

    /* Pakete */
    if (kind === 'model') {
      for (pid in map) if (map.hasOwnProperty(pid)) sel.pkgs.push(map[pid]);
    } else if (kind === 'pkg') {
      for (pid in map) if (map.hasOwnProperty(pid) && sel.pkgSet[pid]) sel.pkgs.push(map[pid]);
    } else if (kind === 'el' && sel.objs.length) {
      var ownPkg = s(sel.objs[0].Package_ID);
      if (map[ownPkg]) sel.pkgs.push(map[ownPkg]);
    }

    /* Beziehungen: bei Paket nur innenliegende, beim Element alle anliegenden */
    for (i = 0; i < conns.length; i++) {
      r = conns[i];
      var a = s(r.Start_Object_ID), b = s(r.End_Object_ID);
      var ina = !!sel.objSet[a], inb = !!sel.objSet[b];
      if (kind === 'model') { sel.conns.push(r); continue; }
      if (kind === 'pkg') {
        if (ina && inb) sel.conns.push(r);
        else if (ina || inb) sel.ext++;
        continue;
      }
      if (ina || inb) sel.conns.push(r);
    }

    /* Tag-Werte */
    for (i = 0; i < tags.length; i++) {
      r = tags[i];
      if (sel.objSet[s(r.Object_ID)]) sel.tags.push(r);
    }

    sel.empty = !sel.objs.length && !sel.pkgs.length;
    return sel;
  }

  /* ------------------------------ Textkontext für den Prompt ------------------------------ */
  function ctxText(sel) {
    var parts = [], used = 0, truncated = false, map = packageMap();
    var objName = {}, objInfo = {}, i, r, id;

    function push(line) {
      line = s(line);
      if (used + line.length + 1 > MAX_CTX) { truncated = true; return false; }
      parts.push(line);
      used += line.length + 1;
      return true;
    }
    function section(title, items) {
      push('');
      push(title + ' (' + items.length + '):');
      for (var k = 0; k < items.length; k++) {
        if (!push(items[k])) {
          push('… (' + (items.length - k) + ' weitere Einträge aus Platzgründen gekürzt)');
          break;
        }
      }
    }

    /* Namensregister über ALLE Elemente (auch außerhalb des Ausschnitts, für Kantenenden) */
    var allObjs = tableRows('t_object');
    for (i = 0; i < allObjs.length; i++) {
      r = allObjs[i];
      id = s(r.Object_ID);
      if (!id) continue;
      objName[id] = s(r.Name) || ('Objekt ' + id);
    }
    for (i = 0; i < sel.objs.length; i++) {
      r = sel.objs[i];
      objInfo[s(r.Object_ID)] = {
        name: s(r.Name) || '(ohne Name)',
        st: s(r.Stereotype),
        type: s(r.Object_Type),
        pkg: shortPath(map, s(r.Package_ID)),
        note: noteText(r.Note)
      };
    }

    push('MODELL: ' + modelName());
    push('DATEI: ' + fileName());
    push('AUSSCHNITT: ' + sel.label);
    push('UMFANG: ' + sel.pkgs.length + ' Pakete, ' + sel.objs.length + ' Elemente, ' + sel.conns.length + ' Beziehungen' +
      (sel.tags.length ? ', ' + sel.tags.length + ' Tag-Werte' : '') + (sel.ext ? ', ' + sel.ext + ' Beziehungen nach außen' : ''));

    /* Pakete */
    var pItems = [];
    for (i = 0; i < sel.pkgs.length; i++) {
      r = sel.pkgs[i];
      pItems.push('- ' + shortPath(map, r.id) + (r.notes ? ' — ' + r.notes : ''));
    }
    section('PAKETE', pItems);

    /* Elemente */
    var eItems = [];
    for (i = 0; i < sel.objs.length; i++) {
      r = sel.objs[i];
      var oi = objInfo[s(r.Object_ID)];
      eItems.push('- ' + (oi.st ? '«' + oi.st + '» ' : '') + oi.name +
        (oi.type ? ' [' + oi.type + ']' : '') +
        (oi.pkg ? ' · Paket: ' + oi.pkg : '') +
        (oi.note ? ' — ' + oi.note : ''));
    }
    section('ELEMENTE', eItems);

    /* Beziehungen */
    var cItems = [];
    for (i = 0; i < sel.conns.length; i++) {
      r = sel.conns[i];
      var a = s(r.Start_Object_ID), b = s(r.End_Object_ID);
      var an = objInfo[a] ? objInfo[a].name : (objName[a] || ('Objekt ' + a));
      var bn = objInfo[b] ? objInfo[b].name : (objName[b] || ('Objekt ' + b));
      var cst = s(r.Stereotype), cty = s(r.Connector_Type), cnm = s(r.Name);
      cItems.push('- ' + an + ' -' + (cst ? '«' + cst + '»' : '') + '(' + (cty || 'Connector') + ')→ ' + bn +
        (cnm ? ' „' + cnm + '“' : '') + (noteText(r.Notes) ? ' — ' + noteText(r.Notes) : ''));
    }
    section('BEZIEHUNGEN', cItems);

    /* Tags */
    var tItems = [];
    for (i = 0; i < sel.tags.length; i++) {
      r = sel.tags[i];
      var on = objInfo[s(r.Object_ID)] ? objInfo[s(r.Object_ID)].name : (objName[s(r.Object_ID)] || ('Objekt ' + s(r.Object_ID)));
      tItems.push('- ' + on + ' · ' + (s(r.Property) || '(ohne Namen)') + ' = ' + (s(r.Value) || ''));
    }
    section('TAG-WERTE (t_objectproperties)', tItems);

    if (truncated) parts.push('… HINWEIS: Der Textkontext wurde wegen der Längenbegrenzung (' + MAX_CTX + ' Zeichen) gekürzt. Für eine vollständige Sicht bitte einen kleineren Ausschnitt (Paket oder Element) wählen.');
    return parts.join('\n');
  }

  /* ------------------------------ Markdown -> sicheres HTML ------------------------------ */
  function mdInline(t) {
    var x = esc(t);
    x = x.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    x = x.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    x = x.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    x = x.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    x = x.replace(/(^|[^_\w])_([^_\n]+)_/g, '$1<em>$2</em>');
    return x;
  }
  /* Rendert Markdown zu HTML. Alle Texte werden ZUERST escaped; es wird nie
     Roh-HTML aus der KI-Antwort übernommen (kein innerHTML mit Rohdaten). */
  function mdHtml(md) {
    var lines = s(md).replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
    var out = [], para = [], inCode = false, list = '', i, m;
    function flushPara() {
      if (para.length) { out.push('<p>' + mdInline(para.join(' ')) + '</p>'); para = []; }
    }
    function closeList() { if (list) { out.push('</' + list + '>'); list = ''; } }
    for (i = 0; i < lines.length; i++) {
      var ln = lines[i];
      if (/^\s*```/.test(ln)) {
        flushPara(); closeList();
        if (inCode) { out.push('</code></pre>'); inCode = false; }
        else { out.push('<pre><code>'); inCode = true; }
        continue;
      }
      if (inCode) { out.push(esc(ln)); continue; }
      if (!ln.trim()) { flushPara(); closeList(); continue; }

      if ((m = /^(#{1,6})\s+(.*)$/.exec(ln))) {
        flushPara(); closeList();
        var lv = Math.min(m[1].length + 1, 4);
        out.push('<h' + lv + '>' + mdInline(m[2]) + '</h' + lv + '>');
        continue;
      }
      if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(ln)) { flushPara(); closeList(); out.push('<hr>'); continue; }

      /* Pipe-Tabelle */
      if (/^\s*\|.*\|\s*$/.test(ln) && i + 1 < lines.length && /^\s*\|[\s:|\-]+\|\s*$/.test(lines[i + 1])) {
        flushPara(); closeList();
        var cells = ln.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|');
        var h = ['<table class="data"><thead><tr>'];
        for (var c = 0; c < cells.length; c++) h.push('<th>' + mdInline(cells[c].trim()) + '</th>');
        h.push('</tr></thead><tbody>');
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          var rc = lines[i].replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|');
          h.push('<tr>');
          for (var c2 = 0; c2 < rc.length; c2++) h.push('<td>' + mdInline(rc[c2].trim()) + '</td>');
          h.push('</tr>');
          i++;
        }
        i--;
        h.push('</tbody></table>');
        out.push(h.join(''));
        continue;
      }

      if ((m = /^\s*[-*+]\s+(.*)$/.exec(ln))) {
        flushPara();
        if (list !== 'ul') { closeList(); out.push('<ul>'); list = 'ul'; }
        out.push('<li>' + mdInline(m[1]) + '</li>');
        continue;
      }
      if ((m = /^\s*\d+[.)]\s+(.*)$/.exec(ln))) {
        flushPara();
        if (list !== 'ol') { closeList(); out.push('<ol>'); list = 'ol'; }
        out.push('<li>' + mdInline(m[1]) + '</li>');
        continue;
      }
      if ((m = /^\s*>\s?(.*)$/.exec(ln))) {
        flushPara(); closeList();
        out.push('<blockquote>' + mdInline(m[1]) + '</blockquote>');
        continue;
      }
      closeList();
      para.push(ln);
    }
    if (inCode) out.push('</code></pre>');
    flushPara(); closeList();
    return out.join('\n');
  }

  /* ------------------------------ lokale Beschreibung (ohne KI) ------------------------------ */
  function localAnswer(sel, q) {
    var map = packageMap(), lines = [], i, r, st = {}, order = [];
    lines.push('# Ausschnitt-Beschreibung — **ohne KI**');
    lines.push('');
    lines.push('**Frage:** ' + s(q));
    lines.push('');
    lines.push('**Modell:** ' + modelName() + '  ');
    lines.push('**Ausschnitt:** ' + sel.label + '  ');
    lines.push('**Erzeugt:** ' + stamp());
    lines.push('');
    lines.push('> Es ist **kein API-Schlüssel** hinterlegt. Deshalb wurde keine KI befragt; diese Übersicht stammt ausschließlich aus der geladenen Datei (SQLite-Tabellen `t_package`, `t_object`, `t_connector`, `t_objectproperties`).');
    lines.push('');
    lines.push('## Umfang');
    lines.push('');
    lines.push('- Pakete: **' + sel.pkgs.length + '**');
    lines.push('- Elemente: **' + sel.objs.length + '**');
    lines.push('- Beziehungen: **' + sel.conns.length + '**' + (sel.ext ? ' (+' + sel.ext + ' nach außen)' : ''));
    lines.push('- Tag-Werte: **' + sel.tags.length + '**');
    lines.push('');
    lines.push('## Pakete');
    lines.push('');
    if (!sel.pkgs.length) lines.push('_keine_');
    for (i = 0; i < sel.pkgs.length && i < MAX_LIST; i++) {
      r = sel.pkgs[i];
      lines.push('- ' + shortPath(map, r.id) + (r.notes ? ' — ' + r.notes : ''));
    }
    if (sel.pkgs.length > MAX_LIST) lines.push('- … ' + (sel.pkgs.length - MAX_LIST) + ' weitere');
    lines.push('');

    for (i = 0; i < sel.objs.length; i++) {
      var k = s(sel.objs[i].Stereotype) || '(ohne Stereotyp)';
      if (!st[k]) { st[k] = 0; order.push(k); }
      st[k]++;
    }
    order.sort(function (a, b) { return st[b] - st[a]; });
    lines.push('## Elemente nach Stereotyp');
    lines.push('');
    if (!order.length) lines.push('_keine_');
    for (i = 0; i < order.length && i < 40; i++) lines.push('- «' + order[i] + '»: ' + st[order[i]]);
    lines.push('');
    lines.push('## Elemente');
    lines.push('');
    if (!sel.objs.length) lines.push('_keine_');
    for (i = 0; i < sel.objs.length && i < MAX_LIST; i++) {
      r = sel.objs[i];
      lines.push('- ' + (s(r.Stereotype) ? '«' + s(r.Stereotype) + '» ' : '') + (s(r.Name) || '(ohne Name)') +
        (s(r.Object_Type) ? ' [' + s(r.Object_Type) + ']' : '') +
        (s(r.Package_ID) ? ' · ' + shortPath(map, s(r.Package_ID)) : ''));
    }
    if (sel.objs.length > MAX_LIST) lines.push('- … ' + (sel.objs.length - MAX_LIST) + ' weitere');
    lines.push('');
    lines.push('## Beziehungen (Kanten)');
    lines.push('');
    if (!sel.conns.length) lines.push('_keine_');
    var nm = {}, oRows = tableRows('t_object');
    for (i = 0; i < oRows.length; i++) nm[s(oRows[i].Object_ID)] = s(oRows[i].Name) || ('Objekt ' + s(oRows[i].Object_ID));
    for (i = 0; i < sel.conns.length && i < MAX_LIST; i++) {
      r = sel.conns[i];
      var ea = s(r.Start_Object_ID), eb = s(r.End_Object_ID);
      lines.push('- ' + (nm[ea] || ('Objekt ' + ea)) + ' -«' + (s(r.Stereotype) || s(r.Connector_Type) || 'Connector') + '»→ ' + (nm[eb] || ('Objekt ' + eb)) +
        (s(r.Name) ? ' „' + s(r.Name) + '“' : ''));
    }
    if (sel.conns.length > MAX_LIST) lines.push('- … ' + (sel.conns.length - MAX_LIST) + ' weitere');
    lines.push('');
    lines.push('## Tag-Werte');
    lines.push('');
    if (!sel.tags.length) lines.push('_keine_');
    for (i = 0; i < sel.tags.length && i < MAX_LIST; i++) {
      r = sel.tags[i];
      lines.push('- Element ' + s(r.Object_ID) + ' · ' + (s(r.Property) || '(ohne Namen)') + ' = ' + (s(r.Value) || ''));
    }
    if (sel.tags.length > MAX_LIST) lines.push('- … ' + (sel.tags.length - MAX_LIST) + ' weitere');
    lines.push('');
    lines.push('## Hinweis');
    lines.push('');
    lines.push('Für eine inhaltliche Antwort auf die Frage: API-Schlüssel im Tab **„🤖 KI-Architekt“**, Abschnitt 3 eintragen — danach geht nur dieser Ausschnitt als Textkontext an den dort konfigurierten Endpunkt.');
    return lines.join('\n');
  }

  /* ------------------------------ KI-Konfiguration (bestehend, nur lesend) ------------------------------ */
  function cfg() {
    var c = { base: 'https://api.deepseek.com/v1', model: 'deepseek-flash', key: '' };
    if (window.KI && typeof KI.cfg === 'function') {
      try {
        var k = KI.cfg();
        if (k) { c.base = k.base || c.base; c.model = k.model || c.model; c.key = k.key || ''; }
      } catch (e) { }
    }
    if (!c.key) {
      try {
        var raw = localStorage.getItem('amki_settings');
        if (raw) {
          var j = JSON.parse(raw);
          if (j) { c.base = c.base || j.base; c.model = c.model || j.model; c.key = s(j.key); }
        }
      } catch (e2) { }
    }
    return c;
  }
  function cfgText() {
    var c = cfg();
    return c.base + ' · Modell ' + c.model + ' · Schlüssel ' + (c.key ? 'hinterlegt' : 'nicht hinterlegt (nur lokale Beschreibung)');
  }

  function askKi(c, system, user) {
    var url = s(c.base).replace(/\/+$/, '') + '/chat/completions';
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + c.key },
      body: JSON.stringify({
        model: c.model,
        messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
        temperature: 0.2,
        max_tokens: 3000,
        stream: false
      })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) {
          var msg = (j && j.error && j.error.message) || '';
          throw new Error('API-Fehler ' + r.status + (msg ? ': ' + String(msg).substring(0, 200) : ''));
        }
        var ch = j && j.choices && j.choices[0];
        var content = ch && ch.message && ch.message.content;
        if (!content) throw new Error('Leere KI-Antwort' + (ch && ch.finish_reason ? ' (finish_reason=' + ch.finish_reason + ')' : '') + '.');
        return content;
      });
    });
  }

  /* ------------------------------ Anzeige ------------------------------ */
  function status(t, cls) {
    var e = byId('qa-status');
    if (!e) return;
    e.className = 'qa-status' + (cls ? ' ' + cls : '');
    e.textContent = s(t);
  }
  function badge(mode) {
    var b = byId('qa-badge');
    if (!b) return;
    if (mode === 'ki') { b.className = 'qa-badge ki'; b.textContent = 'KI-Antwort'; }
    else if (mode === 'noki') { b.className = 'qa-badge noki'; b.textContent = 'ohne KI'; }
    else { b.className = 'qa-badge none'; b.textContent = 'noch keine'; }
  }
  function setAnswer(md, mode, sel, info) {
    ST.answer = md;
    ST.mode = mode;
    ST.meta = info || null;
    ST.selLabel = sel ? sel.label : '';
    var box = byId('qa-answer');
    if (box) box.innerHTML = mdHtml(md);
    badge(mode);
    var meta = byId('qa-meta');
    if (meta) {
      meta.textContent = (sel ? 'Ausschnitt: ' + sel.label + ' · ' : '') +
        (info && info.chars ? info.chars + ' Zeichen Kontext · ' : '') +
        (mode === 'ki' ? 'Modell: ' + info.model + ' · ' : 'Erzeugt lokal, ohne KI · ') +
        stamp();
    }
  }
  function clearAnswer() {
    ST.answer = ''; ST.mode = ''; ST.selLabel = ''; ST.lastQ = '';
    var box = byId('qa-answer');
    if (box) box.innerHTML = '<span class="dim">Noch keine Antwort — Ausschnitt wählen und Frage stellen.</span>';
    badge('');
    var meta = byId('qa-meta');
    if (meta) meta.textContent = '';
    status('');
  }

  /* ------------------------------ Auswahllisten ------------------------------ */
  function fillFiles() {
    var fs = files(), sel = byId('qa-file'), wrap = byId('qa-filewrap'), i, h = [];
    if (!sel) return;
    if (fs.length <= 1) {
      if (wrap) wrap.style.display = 'none';
      return;
    }
    if (wrap) wrap.style.display = '';
    var cur = Number(ST.fileN) || Number(fs[fs.length - 1].n);
    for (i = 0; i < fs.length; i++) {
      h.push('<option value="' + fs[i].n + '"' + (Number(fs[i].n) === cur ? ' selected' : '') + '>M' + fs[i].n + ' — ' + esc(fs[i].name) + '</option>');
    }
    sel.innerHTML = h.join('');
    ST.fileN = cur;
  }
  function fillPkgs() {
    var sel = byId('qa-pkg'), map = packageMap(), arr = [], k, h = [];
    if (!sel) return;
    for (k in map) if (map.hasOwnProperty(k)) arr.push(map[k]);
    arr.sort(function (a, b) { return shortPath(map, a.id).localeCompare(shortPath(map, b.id), 'de'); });
    for (var i = 0; i < arr.length; i++) {
      var depth = 0, p = arr[i];
      while (p && p.parent && p.parent !== '0' && map[p.parent] && depth < 30) { depth++; p = map[p.parent]; }
      h.push('<option value="' + esc(arr[i].id) + '"' + (s(arr[i].id) === s(ST.pkgId) ? ' selected' : '') + '>' +
        (depth ? new Array(depth + 1).join('\u00A0\u00A0\u00A0') : '') + esc(arr[i].name) + '</option>');
    }
    sel.innerHTML = h.join('') || '<option value="">(keine Pakete)</option>';
    if (!ST.pkgId && arr.length) ST.pkgId = s(arr[0].id);
  }
  function fillEls() {
    var sel = byId('qa-el'), objs = tableRows('t_object'), arr = [], i, r, h = [];
    if (!sel) return;
    for (i = 0; i < objs.length; i++) {
      r = objs[i];
      if (isPackageRow(r)) continue;
      arr.push(r);
    }
    arr.sort(function (a, b) { return s(a.Name).localeCompare(s(b.Name), 'de'); });
    for (i = 0; i < arr.length; i++) {
      r = arr[i];
      h.push('<option value="' + esc(s(r.Object_ID)) + '"' + (s(r.Object_ID) === s(ST.oid) ? ' selected' : '') + '>' +
        esc(s(r.Name) || '(ohne Name)') + (s(r.Stereotype) ? ' «' + esc(s(r.Stereotype)) + '»' : '') + '</option>');
    }
    sel.innerHTML = h.join('') || '<option value="">(keine Elemente)</option>';
    if (!ST.oid && arr.length) ST.oid = s(arr[0].Object_ID);
  }

  function readScopeInputs() {
    var sc = byId('qa-scope'), pk = byId('qa-pkg'), elx = byId('qa-el');
    if (sc) ST.scope = sc.value || 'model';
    if (pk && byId('qa-pkgwrap') && byId('qa-pkgwrap').style.display !== 'none') ST.pkgId = s(pk.value);
    if (elx && byId('qa-elwrap') && byId('qa-elwrap').style.display !== 'none') ST.oid = s(elx.value);
  }

  function scopeInfo() {
    var info = byId('qa-scopeinfo');
    if (!info) return null;
    if (!curDb()) { info.textContent = 'Noch keine Datei geladen.'; return null; }
    readScopeInputs();
    var sel = buildSelection();
    if (!sel) { info.textContent = 'Bitte einen gültigen Ausschnitt wählen.'; return null; }
    var txt = ctxText(sel);
    var kb = (txt.length / 1024).toFixed(1).replace('.', ',');
    info.innerHTML = 'Ausschnitt: <b>' + esc(sel.label) + '</b> · ' + sel.pkgs.length + ' Pakete · ' + sel.objs.length +
      ' Elemente · ' + sel.conns.length + ' Beziehungen' + (sel.ext ? ' (+' + sel.ext + ' nach außen)' : '') +
      ' · ' + sel.tags.length + ' Tag-Werte · Textkontext ca. <b>' + kb + ' KB</b> (max. ' + fmt(MAX_CTX) + ' Zeichen)';
    return sel;
  }

  /* ------------------------------ Aktionen ------------------------------ */
  function scopeChanged() {
    var sc = byId('qa-scope');
    ST.scope = sc ? sc.value : 'model';
    var pw = byId('qa-pkgwrap'), ew = byId('qa-elwrap');
    if (pw) pw.style.display = (ST.scope === 'pkg') ? '' : 'none';
    if (ew) ew.style.display = (ST.scope === 'el') ? '' : 'none';
    if (ST.scope === 'pkg') fillPkgs();
    if (ST.scope === 'el') fillEls();
    scopeInfo();
  }
  function fileChanged() {
    var f = byId('qa-file');
    if (f) ST.fileN = Number(f.value) || 0;
    CACHE = { db: null, tables: {} };
    ST.pkgId = ''; ST.oid = '';
    fillPkgs(); fillEls();
    scopeChanged();
  }

  function ask() {
    if (ST.busy) return;
    if (!curDb()) { status('Bitte zuerst eine .qea laden.', 'warn'); return; }
    var qe = byId('qa-question');
    var q = qe ? s(qe.value).trim() : '';
    if (!q) { status('Bitte eine Frage eingeben.', 'warn'); if (qe) qe.focus(); return; }
    ST.lastQ = q;
    var sel = scopeInfo();
    if (!sel) { status('Der gewählte Ausschnitt enthält keine Datensätze.', 'warn'); return; }

    var txt = ctxText(sel);
    var c = cfg();
    var btn = byId('qa-ask');

    if (!c.key) {
      var local = localAnswer(sel, q);
      setAnswer(local, 'noki', sel, { chars: txt.length });
      status('Ohne KI: Ausschnitt lokal beschrieben (kein API-Schlüssel hinterlegt).', 'warn');
      return;
    }

    if (btn) btn.disabled = true;
    ST.busy = true;
    status('⏳ Frage geht an ' + c.model + ' — nur der Ausschnitt (' + (txt.length / 1024).toFixed(1).replace('.', ',') + ' KB) wird übertragen …');

    var system = 'Du bist Enterprise-Architekt für ADMBw/NAFv4 und beantwortest Fragen zu einem gelieferten Modellausschnitt aus einer Sparx-EA-Datei (.qea). ' +
      'Antworte auf Deutsch, sachlich und als Markdown (kurze Absätze, Überschriften, Listen). ' +
      'Stütze dich ausschließlich auf den gelieferten Ausschnitt und erfinde keine Elemente, Beziehungen oder Werte. ' +
      'Wenn Informationen im Ausschnitt fehlen, benenne diese Lücke ausdrücklich. ' +
      'Dies ist eine reine Lese- und Analysefunktion: Stelle Änderungen nicht als bereits ausgeführt dar.';
    var user = 'AUSSCHNITT AUS DER GELADENEN .QEA (Textkontext):\n' + txt + '\n\nFRAGE DES NUTZERS:\n' + q;

    askKi(c, system, user).then(function (content) {
      setAnswer(content, 'ki', sel, { chars: txt.length, model: c.model });
      status('✔ Antwort erhalten (' + c.model + ').', 'ok');
    }).catch(function (e) {
      status('⚠ ' + e.message + ' — bitte Endpunkt/Modell/Schlüssel im KI-Tab prüfen.', 'warn');
    }).then(function () {
      ST.busy = false;
      if (btn) btn.disabled = false;
    });
  }

  function downloadMd(name, text) {
    try {
      var blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click();
      setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 150);
    } catch (e) {
      window.open('data:text/markdown;charset=utf-8,' + encodeURIComponent(text));
    }
  }

  function exportMd() {
    if (!ST.answer) { status('Noch keine Antwort zum Exportieren.', 'warn'); return; }
    var md = [];
    md.push('# ' + (ST.mode === 'noki' ? 'Ausschnitt-Beschreibung (ohne KI)' : 'Antwort auf eine Frage zum Modellausschnitt'));
    md.push('');
    md.push('- **Modell:** ' + modelName());
    md.push('- **Datei:** ' + fileName());
    md.push('- **Ausschnitt:** ' + (ST.selLabel || '—'));
    md.push('- **Frage:** ' + (ST.lastQ || '—'));
    md.push('- **Erzeugt:** ' + stamp());
    md.push('- **Quelle:** ' + (ST.mode === 'noki' ? 'lokal aus der .qea, ohne KI' : 'KI-Endpunkt (Modell ' + (ST.meta && ST.meta.model ? ST.meta.model : cfg().model) + ')'));
    md.push('');
    md.push('---');
    md.push('');
    md.push(ST.answer);
    md.push('');
    var name = 'EAM_Rueckweg_' + safeName(modelName()) + '_' + fileStamp() + '.md';
    downloadMd(name, md.join('\n'));
    status('⤓ Als „' + name + '“ heruntergeladen.', 'ok');
  }

  /* ------------------------------ Ein-/Ausstieg ------------------------------ */
  function render() {
    if (!byId('qa-scope')) return;
    var c = cfg();
    var cfgEl = byId('qa-cfg');
    if (cfgEl) cfgEl.textContent = cfgText();
    var wrap = byId('qa-filewrap');
    if (wrap && files().length <= 1) wrap.style.display = 'none';
    if (files().length > 1) fillFiles();
    if (!curDb()) {
      var info0 = byId('qa-scopeinfo');
      if (info0) info0.textContent = 'Noch keine Datei geladen.';
      return;
    }
    fillPkgs();
    fillEls();
    var sc = byId('qa-scope');
    if (sc) ST.scope = sc.value || ST.scope;
    var pw = byId('qa-pkgwrap'), ew = byId('qa-elwrap');
    if (pw) pw.style.display = (ST.scope === 'pkg') ? '' : 'none';
    if (ew) ew.style.display = (ST.scope === 'el') ? '' : 'none';
    if (!ST.answer) badge('');
    scopeInfo();
  }

  function onModelChanged() {
    CACHE = { db: null, tables: {} };
    ST.pkgId = ''; ST.oid = ''; ST.fileN = 0;
    if (!byId('qa-scope')) return;
    if (!curDb()) {
      var i0 = byId('qa-scopeinfo');
      if (i0) i0.textContent = 'Noch keine Datei geladen.';
      return;
    }
    fillFiles(); fillPkgs(); fillEls();
    var cfgEl = byId('qa-cfg');
    if (cfgEl) cfgEl.textContent = cfgText();
    if (byId('qa-answer')) {
      /* Ausschnitt hat sich geändert -> alte Antwort ist nicht mehr gültig */
      clearAnswer();
      status('Modell geladen — Ausschnitt wählen und Frage stellen.', 'ok');
    }
    scopeInfo();
  }

  return {
    render: render,
    onModelChanged: onModelChanged,
    scopeChanged: scopeChanged,
    scopeInfo: scopeInfo,
    fileChanged: fileChanged,
    ask: ask,
    exportMd: exportMd,
    clearAnswer: clearAnswer,
    _ctxText: ctxText,
    _buildSelection: buildSelection,
    _mdHtml: mdHtml,
    _state: ST
  };
})();

/* Globale Einstiegspunkte (deutsche Bedienung, wie in der Oberfläche verdrahtet) */
function qaAsk() { QA.ask(); }
function qaScopeChanged() { QA.scopeChanged(); }
function qaExport() { QA.exportMd(); }
