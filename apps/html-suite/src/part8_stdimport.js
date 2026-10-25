/* ============================================================================
   EAM AI Suite — Teil 8: Standardelemente-Katalog importieren
   ----------------------------------------------------------------------------
   Übernimmt Pakete samt Elementen, Tags, Attributen und internen Kanten aus
   einer zweiten .qea (Katalog) in das geladene Modell.

   Kernregel: Die ea_guid übernommener Pakete, Elemente und Kanten bleibt
   WÖRTLICH erhalten — nur so finden zwei Modelle desselben Standards über die
   GUID zusammen. Vorhandene GUIDs werden nie überschrieben, sondern als
   „bereits vorhanden“ gezählt (idempotent).

   Portierung von toolbox_merge.py (merge_toolbox), gleiche Semantik:
     * IDs (Package_ID, Object_ID, Connector_ID, PropertyID, Attribut-ID)
       werden im Ziel neu vergeben: höchste vorhandene ID + 1.
     * Katalogpakete hängen unter einem Dachpaket (Default „Standard“);
       existiert ein Paket mit gleicher ea_guid bereits an anderer Stelle,
       wird es nicht verschoben, sondern gemeldet.
     * Kanten nur, wenn beide Endpunkte per GUID im Ziel auflösbar sind
       (auch bereits vorhandene Endpunkte zählen); sonst Warnung.
     * Tags aus t_objectproperties, t_xref, t_attributetag, t_connectortag;
       Attribut-Constraints und Connector-Constraints werden mitgenommen.
     * Kein Löschen, kein Umbenennen, keine Änderung bestehender Zeilen.

   Geschrieben wird über sql.js in eine neue .qea; das Original bleibt
   unverändert. Das Ergebnis wird im Hauptstand neu geladen.
   ========================================================================== */
var STDIMPORT = (function () {
  'use strict';

  /* Reihenfolge wie im Python-Vorbild: Eltern vor Kindern. */
  var WRITE_ORDER = [
    't_package', 't_object', 't_objectproperties', 't_xref', 't_attribute',
    't_attributetag', 't_attributeconstraints', 't_connector',
    't_connectortag', 't_connectorconstraint'
  ];
  /* Identitätsspalten werden nie kopiert — sie werden neu vergeben. */
  var NEVER_COPY = { package_id: 1, object_id: 1, connector_id: 1, propertyid: 1, id: 1 };
  var MAX_WARNINGS = 200;

  var cat = null;              /* geladener Katalog */
  var lastReport = null;       /* {pakete, elemente, kanten, tags, bereits_vorhanden, warnungen} */
  var lastTableRows = null;    /* Zeilenzahl je Zieltabelle (Transparenz) */
  var lastMode = '';           /* 'check' | 'apply' */
  var lastFile = '';
  var busy = false;

  /* ================= kleine Helfer ================= */
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function elm(id) { return document.getElementById(id); }
  function asText(v) { return v == null ? '' : String(v); }
  function asInt(v) {
    if (v == null || v === '') return 0;
    var n = parseInt(v, 10);
    return isFinite(n) ? n : 0;
  }
  function gkey(v) { return asText(v).trim().toUpperCase(); }
  function quoteIdent(name) { return '"' + String(name).replace(/"/g, '""') + '"'; }
  function p2(n) { return (n < 10 ? '0' : '') + n; }
  function stamp() {
    var d = new Date();
    return d.getFullYear() + p2(d.getMonth() + 1) + p2(d.getDate()) + '-' + p2(d.getHours()) + p2(d.getMinutes());
  }

  /* Deterministische Ersatz-GUID im EA-Format {8-4-4-4-12} (synchron).
     Nur für Zeilen ohne vorhandene GUID (t_xref.XrefID, Sammelpaket).
     Vier FNV-1a-Läufe mit verschiedenen Startwerten -> 32 Hex-Zeichen. */
  function fnv32(str, seed) {
    var h = seed >>> 0, i;
    for (i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return ('00000000' + h.toString(16)).slice(-8).toUpperCase();
  }
  function stableGuid(seed) {
    var s = fnv32(seed, 2166136261) + fnv32(seed, 2246822519) +
            fnv32(seed, 3266489917) + fnv32(seed, 668265263);
    return '{' + s.slice(0, 8) + '-' + s.slice(8, 12) + '-' + s.slice(12, 16) +
      '-' + s.slice(16, 20) + '-' + s.slice(20, 32) + '}';
  }
  function warn(list, msg) {
    if (list.length < MAX_WARNINGS) list.push(msg);
    else if (list.length === MAX_WARNINGS) list.push('weitere Warnungen unterdrückt');
  }

  /* ================= Katalog lesen ================= */
  function lowerRow(r) {
    var o = {}, k;
    for (k in r) if (has(r, k)) o[String(k).toLowerCase()] = r[k];
    return o;
  }
  function lrows(db, table) {
    var rs = [], out = [], i;
    try { rs = db.rows(table) || []; } catch (e) { rs = []; }
    for (i = 0; i < rs.length; i++) out.push(lowerRow(rs[i]));
    return out;
  }
  function tableCols(db, table) {
    var t = null, k;
    try {
      if (db && db.tables) {
        for (k in db.tables) {
          if (has(db.tables, k) && String(k).toLowerCase() === String(table).toLowerCase()) { t = db.tables[k]; break; }
        }
      }
    } catch (e) { t = null; }
    return (t && t.cols) ? t.cols.slice() : [];
  }

  function buildCatalog(buffer, name) {
    var db = qeaOpen(buffer);
    var pkgs = lrows(db, 't_package');
    var objs = lrows(db, 't_object');
    if (!pkgs.length) throw new Error('Die Katalogdatei enthält kein Paket (t_package ist leer).');
    if (!objs.length) throw new Error('Die Katalogdatei enthält keine Elemente (t_object ist leer).');
    var byId = {}, children = {}, roots = [], i, r, id, pid;
    for (i = 0; i < pkgs.length; i++) {
      r = pkgs[i];
      id = asInt(r.package_id);
      if (id <= 0) continue;
      byId[id] = {
        id: id, name: asText(r.name), guid: asText(r.ea_guid),
        parent: asInt(r.parent_id), tpos: asInt(r.tpos),
        depth: 0, path: '', own: 0, sub: 0, subPkgs: 0
      };
    }
    if (!Object.keys(byId).length) throw new Error('Die Katalogdatei enthält kein gültiges Paket.');
    for (i = 0; i < pkgs.length; i++) {
      id = asInt(pkgs[i].package_id);
      if (!byId[id]) continue;
      pid = byId[id].parent;
      if (pid && byId[pid] && pid !== id) {
        if (!children[pid]) children[pid] = [];
        children[pid].push(id);
      } else {
        roots.push(id);
      }
    }
    function sortKids(list) {
      list.sort(function (a, b) {
        var pa = byId[a], pb = byId[b];
        if (pa.tpos !== pb.tpos) return pa.tpos - pb.tpos;
        return pa.name.localeCompare(pb.name, 'de');
      });
      for (var j = 0; j < list.length; j++) sortKids(children[list[j]] || []);
    }
    sortKids(roots);
    var flat = [];
    function walk(id, depth, pathNames) {
      var p = byId[id], names = pathNames.concat([p.name]);
      p.depth = depth; p.path = names.join(' / ');
      flat.push(p);
      var kids = children[id] || [];
      for (var j = 0; j < kids.length; j++) walk(kids[j], depth + 1, names);
    }
    roots.sort(function (a, b) {
      var pa = byId[a], pb = byId[b];
      if (pa.tpos !== pb.tpos) return pa.tpos - pb.tpos;
      return pa.name.localeCompare(pb.name, 'de');
    });
    for (i = 0; i < roots.length; i++) walk(roots[i], 0, []);
    /* Elemente je Paket (ohne Paketspiegel) */
    for (i = 0; i < objs.length; i++) {
      r = objs[i];
      pid = asInt(r.package_id);
      if (!byId[pid]) continue;
      if (asText(r.object_type).trim().toLowerCase() !== 'package') byId[pid].own++;
    }
    /* Unterbaum-Summen */
    function sum(id) {
      var p = byId[id], n = p.own, k = children[id] || [], j;
      p.subPkgs = k.length;
      for (j = 0; j < k.length; j++) n += sum(k[j]);
      p.sub = n;
      return n;
    }
    for (i = 0; i < roots.length; i++) sum(roots[i]);
    cat = {
      name: name, db: db, packages: pkgs, objects: objs,
      byId: byId, children: children, roots: roots, flat: flat
    };
    lastReport = null; lastTableRows = null; lastMode = ''; lastFile = '';
    renderCatalog();
    renderReport(null);
    var fi = elm('eh-std-fileinfo');
    if (fi) fi.textContent = name + ' · ' + flat.length + ' Pakete · ' + objs.length + ' Objekte';
    toast('Katalog geladen: ' + esc(name));
  }

  var catFile = null;

  function pickFile(input) {
    var f = input && input.files ? input.files[0] : null;
    if (!f) return;
    catFile = f;
    var rd = new FileReader();
    rd.onload = function () {
      try { buildCatalog(rd.result, f.name); }
      catch (e) {
        cat = null;
        renderCatalog();
        renderError('Katalog konnte nicht gelesen werden: ' + (e && e.message ? e.message : e));
        var fi = elm('eh-std-fileinfo');
        if (fi) fi.textContent = 'keine Datei geladen';
      }
    };
    rd.onerror = function () { renderError('Datei konnte nicht gelesen werden.'); };
    rd.readAsArrayBuffer(f);
  }

  /* ================= Katalog-UI ================= */
  function renderCatalog() {
    var box = elm('eh-std-pkgs');
    if (!box) return;
    if (!cat) {
      box.innerHTML = '<div class="eh-note">Noch kein Katalog geladen — bitte eine zweite .qea wählen.</div>';
      updateButtons();
      return;
    }
    var h = [], i, p;
    h.push('<div class="eh-std-head"><label><input type="checkbox" id="eh-std-all" onchange="STDIMPORT.toggleAll(this.checked)"> Alle Pakete</label>' +
      '<span>' + fmt(cat.objects.length) + ' Objekte im Katalog</span></div>');
    for (i = 0; i < cat.flat.length; i++) {
      p = cat.flat[i];
      h.push('<div class="eh-std-pkg" style="padding-left:' + (8 + p.depth * 16) + 'px">' +
        '<label title="' + esc(p.path) + '"><input type="checkbox" class="eh-stdpkg" data-id="' + p.id + '" onchange="STDIMPORT.pkgToggle()"> ' +
        '<span class="eh-std-nm">' + esc(p.name) + '</span></label>' +
        '<span class="eh-st">' + (p.sub !== p.own
          ? fmt(p.sub) + ' Elemente (inkl. Unterpakete)'
          : fmt(p.own) + ' Elemente') + '</span></div>');
    }
    box.innerHTML = h.join('');
    updateButtons();
  }

  function toggleAll(flag) {
    var list = document.querySelectorAll('.eh-stdpkg'), i;
    for (i = 0; i < list.length; i++) list[i].checked = !!flag;
    updateButtons();
  }
  function pkgToggle() { updateButtons(); }

  function selection() {
    var list = document.querySelectorAll('.eh-stdpkg:checked'), out = [], i;
    for (i = 0; i < list.length; i++) out.push(asInt(list[i].getAttribute('data-id')));
    return out;
  }
  /* Gewählte ID -> Wurzelmenge ohne Nachfahren einer ebenfalls gewählten ID */
  function selectionRoots(ids) {
    var chosen = {}, i, id, seen = {};
    for (i = 0; i < ids.length; i++) chosen[ids[i]] = 1;
    var out = [];
    for (i = 0; i < ids.length; i++) {
      id = ids[i];
      var cur = id, guard = 0, covered = false;
      while (cat.byId[cur] && guard++ < 500) {
        var parent = cat.byId[cur].parent;
        if (!parent || !cat.byId[parent]) break;
        if (chosen[parent]) { covered = true; break; }
        cur = parent;
      }
      if (!covered && !seen[id]) { seen[id] = 1; out.push(id); }
    }
    out.sort(function (a, b) { return a - b; });
    return out;
  }

  function updateButtons() {
    var n = selection().length;
    var chk = elm('eh-std-check'), app = elm('eh-std-apply'), opn = elm('eh-std-open');
    var ok = !!cat && n > 0 && !busy;
    if (chk) chk.disabled = !ok;
    if (app) app.disabled = !ok;
    if (opn) opn.disabled = !cat || busy;
  }

  function renderError(msg) {
    var box = elm('eh-std-report');
    if (!box) return;
    box.setAttribute('data-state', 'error');
    box.innerHTML = '<div class="eh-rep-warn"><b>Nicht ausgeführt.</b><br>' + esc(msg) + '</div>';
  }

  function countBox(label, value) {
    return '<span>' + esc(label) + ': <b>' + fmt(value) + '</b></span>';
  }

  function renderReport(rep, written, fname) {
    var box = elm('eh-std-report');
    if (!box) return;
    if (!rep) {
      box.innerHTML = '';
      box.removeAttribute('data-state');
      box.removeAttribute('data-report');
      return;
    }
    var h = [], i;
    h.push('<div class="eh-rep-nums">' +
      countBox('Pakete', rep.pakete) + countBox('Elemente', rep.elemente) +
      countBox('Kanten', rep.kanten) + countBox('Tags', rep.tags) +
      countBox('Bereits vorhanden', rep.bereits_vorhanden) + '</div>');
    if (lastTableRows) {
      var parts = [];
      for (i = 0; i < WRITE_ORDER.length; i++) {
        var t = WRITE_ORDER[i];
        if (lastTableRows[t]) parts.push(t + ' ' + fmt(lastTableRows[t]));
      }
      if (parts.length) h.push('<div class="eh-rep-dim">Neue Zeilen: ' + esc(parts.join(' · ')) + '</div>');
    }
    if (written) {
      h.push('<div class="eh-rep-ok">✅ Übernommen und als neue Datei ausgegeben: <b>' + esc(fname || lastFile) + '</b><br>' +
        '<span class="dim">Das Original wurde nicht verändert. Die Ansicht zeigt jetzt den übernommenen Stand.</span></div>');
    } else {
      h.push('<div class="eh-rep-dim">Vorschau („Nur prüfen“) — es wurde nichts geschrieben.</div>');
    }
    if (rep.warnungen && rep.warnungen.length) {
      var w = rep.warnungen.slice(0, 80);
      h.push('<div class="eh-rep-warn"><b>' + fmt(rep.warnungen.length) + ' Hinweis(e)</b><pre>' + esc(w.join('\n')) + '</pre></div>');
    }
    box.setAttribute('data-state', written ? 'written' : 'preview');
    box.setAttribute('data-report', JSON.stringify(rep));
    box.innerHTML = h.join('');
  }

  /* ================= Ziel (sql.js) lesen ================= */
  function qrows(db, sql, params) {
    var st = db.prepare(sql), out = [];
    if (params) st.bind(params);
    while (st.step()) out.push(lowerRow(st.getAsObject()));
    st.free();
    return out;
  }
  function colNames(db, table) {
    var out = [], r = db.exec('PRAGMA table_info(' + quoteIdent(table) + ')');
    if (r.length) for (var i = 0; i < r[0].values.length; i++) out.push(String(r[0].values[i][1]));
    return out;
  }
  function maxInt(table, column) {
    var col = String(column).toLowerCase(), best = 0, i, v;
    if (!table || !table.rows) return 0;
    for (i = 0; i < table.rows.length; i++) {
      if (!has(table.rows[i], col)) continue;
      v = asInt(table.rows[i][col]);
      if (v > best) best = v;
    }
    return best;
  }
  function nextTposMap(table, parentColumn) {
    var out = {}, i, parent, pos, col = String(parentColumn).toLowerCase();
    if (!table || !table.rows) return out;
    for (i = 0; i < table.rows.length; i++) {
      var r = table.rows[i];
      if (!has(r, 'tpos')) continue;
      parent = asInt(r[col]);
      pos = asInt(r.tpos);
      if (!has(out, parent) || pos > out[parent]) out[parent] = pos;
    }
    for (var k in out) if (has(out, k)) out[k] = out[k] + 1;
    return out;
  }

  function readTarget(db) {
    var warnings = [], actual = {}, r, i, name;
    r = db.exec("SELECT name FROM sqlite_master WHERE type='table'");
    if (r.length) for (i = 0; i < r[0].values.length; i++) actual[String(r[0].values[i][0]).toLowerCase()] = String(r[0].values[i][0]);
    var snap = {};
    for (i = 0; i < WRITE_ORDER.length; i++) {
      name = WRITE_ORDER[i];
      var act = actual[name];
      if (!act) {
        warn(warnings, 'Ziel: Tabelle ' + name + ' fehlt — Inhalte können nicht übernommen werden');
        snap[name] = { name: name, columns: [], rows: [] };
        continue;
      }
      snap[name] = { name: act, columns: colNames(db, act), rows: qrows(db, 'SELECT * FROM ' + quoteIdent(act)) };
    }
    var packageIds = {}, objectIds = {}, packageGuids = {}, objectGuids = {}, connectorGuids = {};
    var xrefIds = {}, attributeConstraints = {};
    var tPkg = snap.t_package, tObj = snap.t_object, tCon = snap.t_connector, tXref = snap.t_xref;
    for (i = 0; i < tPkg.rows.length; i++) {
      var pid = asInt(tPkg.rows[i].package_id);
      if (pid > 0) packageIds[pid] = tPkg.rows[i];
    }
    for (i = 0; i < tObj.rows.length; i++) {
      var oid = asInt(tObj.rows[i].object_id);
      if (oid > 0) objectIds[oid] = tObj.rows[i];
    }
    var ids = Object.keys(packageIds).map(Number).sort(function (a, b) { return a - b; });
    for (i = 0; i < ids.length; i++) {
      var pk = gkey(packageIds[ids[i]].ea_guid);
      if (pk && !has(packageGuids, pk)) packageGuids[pk] = ids[i];
    }
    ids = Object.keys(objectIds).map(Number).sort(function (a, b) { return a - b; });
    for (i = 0; i < ids.length; i++) {
      var ok = gkey(objectIds[ids[i]].ea_guid);
      if (ok && !has(objectGuids, ok)) objectGuids[ok] = ids[i];
    }
    for (i = 0; i < tCon.rows.length; i++) {
      var ck = gkey(tCon.rows[i].ea_guid);
      if (ck && !has(connectorGuids, ck)) connectorGuids[ck] = asInt(tCon.rows[i].connector_id);
    }
    for (i = 0; i < tXref.rows.length; i++) {
      var xk = gkey(tXref.rows[i].xrefid);
      if (xk) xrefIds[xk] = 1;
    }
    var tAc = snap.t_attributeconstraints;
    if (tAc && tAc.columns.length) {
      var hasConstraintCol = false;
      for (i = 0; i < tAc.columns.length; i++) if (String(tAc.columns[i]).toLowerCase() === 'constraint') hasConstraintCol = true;
      if (hasConstraintCol) {
        for (i = 0; i < tAc.rows.length; i++) {
          attributeConstraints[asText(tAc.rows[i].constraint) + '\u0000' + asInt(tAc.rows[i].id)] = 1;
        }
      }
    }
    var nextProperty = Math.max(
      maxInt(snap.t_objectproperties, 'PropertyID'),
      maxInt(snap.t_connectortag, 'PropertyID'),
      maxInt(snap.t_attributetag, 'PropertyID')
    ) + 1;
    return {
      tables: snap, warnings: warnings,
      packageIds: packageIds, objectIds: objectIds,
      packageGuids: packageGuids, objectGuids: objectGuids, connectorGuids: connectorGuids,
      xrefIds: xrefIds, attributeConstraints: attributeConstraints,
      nextPackageId: maxInt(tPkg, 'Package_ID') + 1,
      nextObjectId: maxInt(tObj, 'Object_ID') + 1,
      nextConnectorId: maxInt(tCon, 'Connector_ID') + 1,
      nextPropertyId: nextProperty,
      nextAttributeId: maxInt(snap.t_attribute, 'ID') + 1,
      nextTpos: nextTposMap(tPkg, 'Parent_ID'),
      nextObjectTpos: nextTposMap(tObj, 'Package_ID'),
      counts: {
        t_package: tPkg.rows.length, t_object: tObj.rows.length,
        t_connector: tCon.rows.length, t_objectproperties: snap.t_objectproperties.rows.length,
        t_xref: tXref.rows.length, t_connectortag: snap.t_connectortag.rows.length
      }
    };
  }

  /* ================= Katalog-Auswahl lesen ================= */
  function treeOrder(byId, wanted) {
    function depth(pid) {
      var seen = {}, current = pid, level = 0;
      for (;;) {
        var p = byId[current] ? asInt(byId[current].parent_id) : 0;
        if (!byId[p] || seen[p] || p === current) return level;
        seen[current] = 1;
        level++;
        current = p;
      }
    }
    return wanted.slice().sort(function (a, b) {
      var da = depth(a), db = depth(b);
      return da !== db ? da - db : a - b;
    });
  }

  function readSource(katalog, rootIds) {
    var warnings = [], i, j, r, id, pid;
    var byId = {}, children = {};
    for (i = 0; i < katalog.packages.length; i++) {
      r = katalog.packages[i];
      id = asInt(r.package_id);
      if (id <= 0) continue;
      byId[id] = r;
    }
    if (!Object.keys(byId).length) throw new Error('Der Katalog enthält kein Paket (t_package ist leer).');
    for (i = 0; i < katalog.packages.length; i++) {
      r = katalog.packages[i];
      id = asInt(r.package_id);
      if (!byId[id]) continue;
      pid = asInt(r.parent_id);
      if (pid && byId[pid] && pid !== id) {
        if (!children[pid]) children[pid] = [];
        children[pid].push(id);
      }
    }
    var chosen = {}, stack = [], guard = 0;
    for (i = 0; i < rootIds.length; i++) if (byId[asInt(rootIds[i])]) stack.push(asInt(rootIds[i]));
    if (!stack.length) throw new Error('Keines der gewählten Katalogpakete ist im Katalog vorhanden.');
    while (stack.length && guard++ < 100000) {
      var cur = stack.pop();
      if (chosen[cur]) continue;
      chosen[cur] = 1;
      var kids = children[cur] || [];
      for (j = 0; j < kids.length; j++) if (!chosen[kids[j]]) stack.push(kids[j]);
    }
    var selected = treeOrder(byId, Object.keys(chosen).map(Number));
    var selectedGuids = {};
    for (i = 0; i < selected.length; i++) {
      var g = gkey(byId[selected[i]].ea_guid);
      if (g) selectedGuids[g] = 1;
    }

    var objectsByPackage = {}, packageObjects = {}, selectedObjects = {};
    var mirrors = 0;
    var objs = katalog.objects.slice().sort(function (a, b) { return asInt(a.object_id) - asInt(b.object_id); });
    for (i = 0; i < objs.length; i++) {
      r = objs[i];
      pid = asInt(r.package_id);
      if (!chosen[pid]) continue;
      var oid = asInt(r.object_id);
      selectedObjects[oid] = 1;
      if (asText(r.object_type).trim().toLowerCase() === 'package') {
        var mk = gkey(r.ea_guid);
        if (mk && selectedGuids[mk] && !has(packageObjects, mk)) packageObjects[mk] = r;
        mirrors++;
        continue;
      }
      if (!objectsByPackage[pid]) objectsByPackage[pid] = [];
      objectsByPackage[pid].push(r);
    }

    return {
      warnings: warnings,
      packages: katalog.packages,
      objects: katalog.objects,
      tags: lrows(katalog.db, 't_objectproperties'),
      xrefs: lrows(katalog.db, 't_xref'),
      attributes: lrows(katalog.db, 't_attribute'),
      attributeTags: lrows(katalog.db, 't_attributetag'),
      attributeConstraints: lrows(katalog.db, 't_attributeconstraints'),
      connectors: lrows(katalog.db, 't_connector'),
      connectorTags: lrows(katalog.db, 't_connectortag'),
      connectorConstraints: lrows(katalog.db, 't_connectorconstraint'),
      byId: byId,
      selected: selected,
      objectsByPackage: objectsByPackage,
      packageObjects: packageObjects,
      selectedObjects: selectedObjects,
      mirrors: mirrors
    };
  }

  function warnLostColumns(box, tgt) {
    var map = {
      t_package: box.packages, t_object: box.objects, t_objectproperties: box.tags,
      t_xref: box.xrefs, t_attribute: box.attributes, t_attributetag: box.attributeTags,
      t_attributeconstraints: box.attributeConstraints, t_connector: box.connectors,
      t_connectortag: box.connectorTags, t_connectorconstraint: box.connectorConstraints
    };
    for (var name in map) {
      if (!has(map, name)) continue;
      var dest = tgt.tables[name];
      if (!dest || !dest.columns.length) continue;
      var known = {}, i, lost = [];
      for (i = 0; i < dest.columns.length; i++) known[String(dest.columns[i]).toLowerCase()] = 1;
      /* Quellspalten stehen in den Zeilen; eine leere Quelltabelle hat keine. */
      var srcCols = {};
      var rows = map[name] || [];
      for (i = 0; i < rows.length; i++) for (var k in rows[i]) if (has(rows[i], k)) srcCols[k] = 1;
      for (var c in srcCols) if (has(srcCols, c) && !known[c] && !NEVER_COPY[c]) lost.push(c);
      if (lost.length) {
        lost.sort();
        var preview = lost.slice(0, 5).join(', ') + (lost.length > 5 ? ' …' : '');
        warn(box.warnings, name + ': Ziel kennt ' + lost.length + ' Quellspalten nicht (' + preview + ') — diese Werte werden nicht übernommen');
      }
    }
  }

  /* ================= Plan bauen (Port von _build_plan) ================= */
  function copyRow(row) {
    var o = {}, k;
    for (k in row) if (has(row, k) && !NEVER_COPY[k]) o[k] = row[k];
    return o;
  }
  function add(plan, table, row) {
    if (!plan[table]) plan[table] = [];
    plan[table].push(row);
  }

  function buildPlan(tgt, box, paketname) {
    var warnings = (box.warnings || []).slice();
    var plan = {}, counts = { pakete: 0, elemente: 0, kanten: 0, tags: 0, bereits_vorhanden: 0 };

    /* ---- t_xref nach Client (GUID) gruppieren ---- */
    var xrefsByClient = {};
    var xr = box.xrefs.slice().sort(function (a, b) { return asText(a.xrefid).localeCompare(asText(b.xrefid)); });
    for (var xi = 0; xi < xr.length; xi++) {
      var cl = gkey(xr[xi].client);
      if (!cl) continue;
      if (!xrefsByClient[cl]) xrefsByClient[cl] = [];
      xrefsByClient[cl].push(xr[xi]);
    }
    function addXrefs(guid) {
      var list = xrefsByClient[gkey(guid)] || [];
      for (var index = 0; index < list.length; index++) {
        var sourceRow = list[index];
        var xrefType = asText(sourceRow.type);
        var candidate = stableGuid('toolbox_merge|xref|' + gkey(guid) + '|' + xrefType + '|' + index);
        var suffix = 1;
        while (has(tgt.xrefIds, gkey(candidate))) {
          candidate = stableGuid('toolbox_merge|xref|' + gkey(guid) + '|' + xrefType + '|' + index + '|' + suffix);
          suffix++;
        }
        tgt.xrefIds[gkey(candidate)] = 1;
        var row = copyRow(sourceRow);
        row.xrefid = candidate;
        row.client = guid;
        add(plan, 't_xref', row);
        counts.tags++;
      }
    }

    /* ---- Dachpaket ---- */
    var wanted = asText(paketname).trim();
    if (!wanted) throw new Error('Dachpaket: Name darf nicht leer sein.');
    var cands = [], ids = Object.keys(tgt.packageIds).map(Number).sort(function (a, b) { return a - b; });
    for (var i = 0; i < ids.length; i++) {
      var pr = tgt.packageIds[ids[i]];
      if (asText(pr.name).trim().toLowerCase() === wanted.toLowerCase()) cands.push(ids[i]);
    }
    var containerId = null;
    for (i = 0; i < cands.length; i++) {
      if (asInt(tgt.packageIds[cands[i]].parent_id) === 0) { containerId = cands[i]; break; }
    }
    if (containerId == null && cands.length) {
      containerId = cands[0];
      warn(warnings, 'Dachpaket „' + wanted + '“ liegt im Ziel nicht auf Wurzelebene — verwendet wird Package_ID ' + containerId);
    }
    if (containerId == null) {
      containerId = tgt.nextPackageId;
      tgt.nextPackageId++;
      var cpos = has(tgt.nextTpos, 0) ? tgt.nextTpos[0] : 0;
      tgt.nextTpos[0] = cpos + 1;
      add(plan, 't_package', {
        package_id: containerId, name: wanted, parent_id: 0, notes: '',
        ea_guid: stableGuid('toolbox_merge|package|' + wanted.toLowerCase()),
        createddate: '', modifieddate: '', version: '1.0', tpos: cpos
      });
      /* Das Dach zählt nicht als Katalogpaket. */
    }
    var containerRow = tgt.packageIds[containerId] || null;
    containerId = containerRow ? asInt(containerRow.package_id, containerId) : containerId;

    /* ---- Paketbaum ---- */
    var packageMap = {};
    packageMap[containerId] = containerId;
    var packageObjectMap = {};
    var packagePositions = {};
    for (var pk in tgt.nextTpos) if (has(tgt.nextTpos, pk)) packagePositions[pk] = tgt.nextTpos[pk];

    for (var si = 0; si < box.selected.length; si++) {
      var sourceId = box.selected[si];
      var sourceRow = box.byId[sourceId];
      var parentSource = asInt(sourceRow.parent_id);
      var parentTarget = has(packageMap, parentSource) ? packageMap[parentSource] : containerId;
      var guid = asText(sourceRow.ea_guid).trim();
      var pname = asText(sourceRow.name);

      if (guid && has(tgt.packageGuids, gkey(guid))) {
        var existing = tgt.packageGuids[gkey(guid)];
        packageMap[sourceId] = existing;
        var existingParent = asInt((tgt.packageIds[existing] || {}).parent_id);
        if (existingParent !== parentTarget) {
          warn(warnings, 'Paket „' + pname + '“ existiert bereits (GUID ' + guid + ', Package_ID ' + existing +
            ') an anderer Stelle — wird nicht verschoben');
        }
        continue;
      }

      var newId = tgt.nextPackageId;
      tgt.nextPackageId++;
      var rowP = copyRow(sourceRow);
      rowP.package_id = newId;
      rowP.parent_id = parentTarget;
      if (!guid) {
        guid = stableGuid('toolbox_merge|package|' + wanted.toLowerCase() + '|' + sourceId + '|' + pname);
        warn(warnings, 'Paket „' + pname + '“ ohne ea_guid — deterministische GUID vergeben (' + guid + ')');
      }
      rowP.ea_guid = guid;
      var pos = has(packagePositions, parentTarget) ? packagePositions[parentTarget] : 0;
      packagePositions[parentTarget] = pos + 1;
      rowP.tpos = pos;
      add(plan, 't_package', rowP);
      packageMap[sourceId] = newId;
      tgt.packageGuids[gkey(guid)] = newId;
      counts.pakete++;

      /* Paketspiegel in t_object (EA-Konvention) */
      var mirrorId = tgt.nextObjectId;
      tgt.nextObjectId++;
      var sourceMirror = box.packageObjects[gkey(guid)];
      var mirror;
      if (sourceMirror) {
        mirror = copyRow(sourceMirror);
      } else {
        mirror = {
          object_type: 'Package', name: pname, alias: '', note: '',
          stereotype: 'Package', status: '', version: '1.0',
          createddate: '', modifieddate: ''
        };
      }
      mirror.object_id = mirrorId;
      mirror.package_id = parentTarget;
      if (has(mirror, 'diagram_id')) mirror.diagram_id = 0;
      mirror.ea_guid = guid;
      mirror.tpos = pos;
      add(plan, 't_object', mirror);
      tgt.objectGuids[gkey(guid)] = mirrorId;
      if (sourceMirror) packageObjectMap[asInt(sourceMirror.object_id)] = mirrorId;

      addXrefs(guid);
    }

    /* ---- Elemente ---- */
    var elementMap = {}, elementGuid = {};
    var objectPosition = {};
    for (var op in tgt.nextObjectTpos) if (has(tgt.nextObjectTpos, op)) objectPosition[op] = tgt.nextObjectTpos[op];
    var diagramBound = 0;
    for (var si2 = 0; si2 < box.selected.length; si2++) {
      var pkgId = box.selected[si2];
      var list = box.objectsByPackage[pkgId] || [];
      for (var ei = 0; ei < list.length; ei++) {
        var srcObj = list[ei];
        var oid = asInt(srcObj.object_id);
        var oguid = asText(srcObj.ea_guid).trim();
        var oname = asText(srcObj.name);
        if (asInt(srcObj.diagram_id) > 0) diagramBound++;
        if (oguid && has(tgt.objectGuids, gkey(oguid))) {
          counts.bereits_vorhanden++;
          continue;
        }
        var newOid = tgt.nextObjectId;
        tgt.nextObjectId++;
        var rowO = copyRow(srcObj);
        rowO.object_id = newOid;
        rowO.package_id = packageMap[pkgId];
        if (has(rowO, 'diagram_id')) rowO.diagram_id = 0;
        if (!oguid) {
          oguid = stableGuid('toolbox_merge|element|' + pkgId + '|' + oid + '|' + oname);
          warn(warnings, 'Element „' + oname + '“ (Object_ID ' + oid + ') ohne ea_guid — deterministische GUID vergeben (' + oguid + ')');
        }
        rowO.ea_guid = oguid;
        var opos = has(objectPosition, packageMap[pkgId]) ? objectPosition[packageMap[pkgId]] : 0;
        objectPosition[packageMap[pkgId]] = opos + 1;
        rowO.tpos = opos;
        add(plan, 't_object', rowO);
        elementMap[oid] = newOid;
        elementGuid[oid] = oguid;
        tgt.objectGuids[gkey(oguid)] = newOid;
        counts.elemente++;
      }
    }
    if (diagramBound) {
      warn(warnings, diagramBound + ' Katalog-Elemente waren auf Sichten platziert — Sichten/Layout werden nicht übernommen (Diagram_ID auf 0 gesetzt)');
    }

    /* ---- Tags aus t_objectproperties ---- */
    var tagOwnerMap = {};
    for (var tk in elementMap) if (has(elementMap, tk)) tagOwnerMap[tk] = elementMap[tk];
    for (var tk2 in packageObjectMap) if (has(packageObjectMap, tk2)) tagOwnerMap[tk2] = packageObjectMap[tk2];
    var tags = box.tags.slice().sort(function (a, b) { return asInt(a.propertyid) - asInt(b.propertyid); });
    for (var ti = 0; ti < tags.length; ti++) {
      var owner = asInt(tags[ti].object_id);
      if (!has(tagOwnerMap, owner)) continue;
      var rowT = copyRow(tags[ti]);
      rowT.propertyid = tgt.nextPropertyId++;
      rowT.object_id = tagOwnerMap[owner];
      add(plan, 't_objectproperties', rowT);
      counts.tags++;
    }

    /* ---- t_xref der Elemente ---- */
    var emIds = Object.keys(elementMap).map(Number).sort(function (a, b) { return a - b; });
    for (var xi2 = 0; xi2 < emIds.length; xi2++) addXrefs(elementGuid[emIds[xi2]]);

    /* ---- Attribute ---- */
    var attributeMap = {};
    var attrs = box.attributes.slice().sort(function (a, b) { return asInt(a.id) - asInt(b.id); });
    for (var ai = 0; ai < attrs.length; ai++) {
      var aowner = asInt(attrs[ai].object_id);
      if (!has(elementMap, aowner)) continue;
      var oldAttrId = asInt(attrs[ai].id);
      var rowA = copyRow(attrs[ai]);
      rowA.id = tgt.nextAttributeId++;
      rowA.object_id = elementMap[aowner];
      add(plan, 't_attribute', rowA);
      if (oldAttrId) attributeMap[oldAttrId] = asInt(rowA.id);
    }

    var atags = box.attributeTags.slice().sort(function (a, b) { return asInt(a.propertyid) - asInt(b.propertyid); });
    for (var ati = 0; ati < atags.length; ati++) {
      var atOwner = asInt(atags[ati].elementid);
      if (!has(attributeMap, atOwner)) continue;
      var rowAT = copyRow(atags[ati]);
      rowAT.propertyid = tgt.nextPropertyId++;
      rowAT.elementid = attributeMap[atOwner];
      add(plan, 't_attributetag', rowAT);
      counts.tags++;
    }

    var acs = box.attributeConstraints.slice().sort(function (a, b) {
      var d = asInt(a.object_id) - asInt(b.object_id);
      return d !== 0 ? d : asText(a.constraint).localeCompare(asText(b.constraint));
    });
    for (var aci = 0; aci < acs.length; aci++) {
      var acOwner = asInt(acs[aci].object_id);
      if (!has(elementMap, acOwner)) continue;
      var oldAcId = asInt(acs[aci].id);
      if (!has(attributeMap, oldAcId)) {
        warn(warnings, 'Attribut-Constraint „' + asText(acs[aci].constraint) + '“ ohne zugeordnetes Attribut — nicht übernommen');
        continue;
      }
      var keyAc = asText(acs[aci].constraint) + '\u0000' + attributeMap[oldAcId];
      if (has(tgt.attributeConstraints, keyAc)) {
        warn(warnings, 'Attribut-Constraint „' + asText(acs[aci].constraint) + '“ existiert bereits — übersprungen');
        continue;
      }
      tgt.attributeConstraints[keyAc] = 1;
      var rowAC = copyRow(acs[aci]);
      rowAC.object_id = elementMap[acOwner];
      rowAC.id = attributeMap[oldAcId];
      add(plan, 't_attributeconstraints', rowAC);
    }

    /* ---- Kanten ---- */
    var connectorMap = {};
    var endpointMap = {};
    for (var ek in elementMap) if (has(elementMap, ek)) endpointMap[ek] = elementMap[ek];
    for (var ek2 in packageObjectMap) if (has(packageObjectMap, ek2)) endpointMap[ek2] = packageObjectMap[ek2];
    var sourceGuids = {};
    for (var gi = 0; gi < box.objects.length; gi++) {
      var go = box.objects[gi];
      var goid = asInt(go.object_id);
      var gg = asText(go.ea_guid).trim();
      if (has(box.selectedObjects, goid) && gg && !has(sourceGuids, goid)) sourceGuids[goid] = gg;
    }
    function resolveEndpoint(objectId) {
      if (has(endpointMap, objectId)) return endpointMap[objectId];
      var g = sourceGuids[objectId];
      if (!g) return null;
      return has(tgt.objectGuids, gkey(g)) ? tgt.objectGuids[gkey(g)] : null;
    }

    var skippedEdges = [];
    var cons = box.connectors.slice().sort(function (a, b) { return asInt(a.connector_id) - asInt(b.connector_id); });
    for (var ci = 0; ci < cons.length; ci++) {
      var co = cons[ci];
      var start = asInt(co.start_object_id), end = asInt(co.end_object_id);
      if (!has(box.selectedObjects, start) || !has(box.selectedObjects, end)) continue;
      var cid = asInt(co.connector_id);
      var cguid = asText(co.ea_guid).trim();
      if (cguid && has(tgt.connectorGuids, gkey(cguid))) continue;
      var newStart = resolveEndpoint(start), newEnd = resolveEndpoint(end);
      if (newStart == null || newEnd == null) {
        skippedEdges.push('Connector_ID ' + cid + ' (' + asText(co.connector_type) + '): Endpunkt ist im Ziel nicht auflösbar ' +
          '(weder in diesem Lauf übernommen noch über ea_guid vorhanden), Kante fehlt im Ziel');
        continue;
      }
      if (!cguid) {
        cguid = stableGuid('toolbox_merge|connector|' + cid + '|' + start + '|' + end);
        warn(warnings, 'Kante Connector_ID ' + cid + ' ohne ea_guid — deterministische GUID vergeben (' + cguid + ')');
      }
      var rowC = copyRow(co);
      rowC.connector_id = tgt.nextConnectorId++;
      rowC.start_object_id = newStart;
      rowC.end_object_id = newEnd;
      rowC.ea_guid = cguid;
      add(plan, 't_connector', rowC);
      tgt.connectorGuids[gkey(cguid)] = asInt(rowC.connector_id);
      connectorMap[cid] = asInt(rowC.connector_id);
      counts.kanten++;
    }
    for (var sci = 0; sci < skippedEdges.length && sci < MAX_WARNINGS; sci++) warn(warnings, 'Kante nicht übernommen: ' + skippedEdges[sci]);
    if (skippedEdges.length > MAX_WARNINGS) warn(warnings, 'weitere ' + (skippedEdges.length - MAX_WARNINGS) + ' Kanten nicht übernommen');

    var ct = box.connectorTags.slice().sort(function (a, b) { return asInt(a.propertyid) - asInt(b.propertyid); });
    for (var cti = 0; cti < ct.length; cti++) {
      var ctOwner = asInt(ct[cti].elementid);
      if (!has(connectorMap, ctOwner)) continue;
      var rowCT = copyRow(ct[cti]);
      rowCT.propertyid = tgt.nextPropertyId++;
      rowCT.elementid = connectorMap[ctOwner];
      add(plan, 't_connectortag', rowCT);
      counts.tags++;
    }

    var cc = box.connectorConstraints.slice().sort(function (a, b) {
      var d = asInt(a.connectorid) - asInt(b.connectorid);
      return d !== 0 ? d : asText(a.constraint).localeCompare(asText(b.constraint));
    });
    for (var cci = 0; cci < cc.length; cci++) {
      var ccOwner = asInt(cc[cci].connectorid);
      if (!has(connectorMap, ccOwner)) continue;
      var rowCC = copyRow(cc[cci]);
      rowCC.connectorid = connectorMap[ccOwner];
      add(plan, 't_connectorconstraint', rowCC);
    }

    var tableRows = {};
    for (var tn in plan) if (has(plan, tn)) tableRows[tn] = plan[tn].length;

    return {
      rows: plan,
      tableRows: tableRows,
      report: {
        pakete: counts.pakete,
        elemente: counts.elemente,
        kanten: counts.kanten,
        tags: counts.tags,
        bereits_vorhanden: counts.bereits_vorhanden,
        warnungen: warnings
      }
    };
  }

  /* ================= Schreiben ================= */
  function insertRows(db, table, columns, rows) {
    if (!rows || !rows.length) return 0;
    var keys = {}, i, k;
    for (i = 0; i < rows.length; i++) for (k in rows[i]) if (has(rows[i], k)) keys[k] = 1;
    var cols = [], j;
    for (j = 0; j < columns.length; j++) {
      if (has(keys, String(columns[j]).toLowerCase())) cols.push(columns[j]);
    }
    if (!cols.length) throw new Error(table + ': keine gemeinsame Spalte zwischen Katalog und Ziel — Abbruch');
    var sql = 'INSERT INTO ' + quoteIdent(table) + ' (' + cols.map(quoteIdent).join(', ') + ') VALUES (' +
      cols.map(function () { return '?'; }).join(', ') + ')';
    var st = db.prepare(sql);
    try {
      for (i = 0; i < rows.length; i++) {
        var values = [];
        for (j = 0; j < cols.length; j++) {
          var v = rows[i][String(cols[j]).toLowerCase()];
          values.push(v === undefined ? null : v);
        }
        st.run(values);
      }
    } finally {
      st.free();
    }
    return rows.length;
  }

  function insertPlan(db, tgt, plan) {
    for (var i = 0; i < WRITE_ORDER.length; i++) {
      var name = WRITE_ORDER[i];
      var rows = plan.rows[name];
      if (!rows || !rows.length) continue;
      var t = tgt.tables[name];
      if (!t || !t.columns.length) throw new Error('Ziel: Tabelle ' + name + ' fehlt — Übernahme nicht möglich.');
      insertRows(db, t.name, t.columns, rows);
    }
  }

  function toArrayBuffer(u8) {
    if (u8.byteOffset === 0 && u8.byteLength === u8.buffer.byteLength) return u8.buffer;
    return u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength);
  }

  function outFileName(name) {
    var base = String(name || 'Modell').replace(/\.(qea|qeax|eapx|sqlite)$/i, '');
    if (!base) base = 'Modell';
    return base + '_standardelemente_' + stamp() + '.qea';
  }

  /* ================= Ablauf ================= */
  function run(write) {
    if (busy) return;
    if (!cat) { renderError('Bitte zuerst eine Katalog-.qea laden.'); return; }
    var ids = selection();
    if (!ids.length) { renderError('Bitte mindestens ein Katalogpaket auswählen.'); return; }
    if (typeof DB === 'undefined' || !DB) { renderError('Bitte zuerst eine Modell-.qea laden.'); return; }
    if (typeof MULTI_MODE !== 'undefined' && MULTI_MODE) {
      renderError('Der Standardelemente-Import ist nur im Einzelmodus möglich. Bitte den Mehrfach-Modus auflösen und die Ziel-.qea einzeln laden.');
      return;
    }
    var rootNameEl = elm('eh-std-root');
    var rootName = rootNameEl ? String(rootNameEl.value || '') : 'Standard';
    if (!rootName.trim()) { renderError('Dachpaket: Name darf nicht leer sein.'); return; }
    var info = (typeof EDIT !== 'undefined' && EDIT._srcInfo) ? EDIT._srcInfo() : null;
    if (!info || !info.bytes) { renderError('Für das geladene Modell liegen keine Originaldaten vor.'); return; }

    busy = true; updateButtons();
    var chkBtn = elm('eh-std-check'), appBtn = elm('eh-std-apply');
    if (chkBtn) chkBtn.textContent = write ? '🔍 Nur prüfen' : '⏳ Prüfe …';
    if (appBtn) appBtn.textContent = write ? '⏳ Übernehme …' : '⬇ Übernehmen';

    EDIT._loadSQL().then(function (SQL) {
      var db = null;
      try {
        db = new SQL.Database(info.bytes);
        var tgt = readTarget(db);
        var box = readSource(cat, selectionRoots(ids));
        warnLostColumns(box, tgt);
        var plan = buildPlan(tgt, box, rootName);

        lastReport = plan.report;
        lastTableRows = plan.tableRows;
        lastMode = write ? 'apply' : 'check';
        lastFile = '';

        if (!write) {
          try { db.close(); } catch (e0) { }
          db = null;
          busy = false;
          if (chkBtn) chkBtn.textContent = '🔍 Nur prüfen';
          if (appBtn) appBtn.textContent = '⬇ Übernehmen';
          updateButtons();
          renderReport(plan.report, false, '');
          toast('Vorschau: ' + fmt(plan.report.elemente) + ' Elemente, ' + fmt(plan.report.kanten) + ' Kanten — nichts geschrieben.');
          return;
        }

        insertPlan(db, tgt, plan);
        var chk = db.exec('PRAGMA integrity_check');
        var okv = (chk.length && chk[0].values.length) ? String(chk[0].values[0][0]) : '?';
        if (okv.toLowerCase() !== 'ok') throw new Error('SQLite-Integritätsprüfung meldet: ' + okv);
        var out = db.export();
        try { db.close(); } catch (e1) { }
        db = null;

        /* Selbsttest mit dem eingebauten Reader */
        var ab = toArrayBuffer(out);
        var probe = qeaOpen(ab);
        var probeObj = probe.rows('t_object').length;
        var needObj = tgt.counts.t_object + (plan.tableRows.t_object || 0);
        if (probeObj !== needObj) throw new Error('Selbsttest: Elementzahl weicht ab (' + probeObj + ' statt ' + needObj + ').');
        var probeCon = probe.rows('t_connector').length;
        var needCon = tgt.counts.t_connector + (plan.tableRows.t_connector || 0);
        if (probeCon !== needCon) throw new Error('Selbsttest: Kantenzahl weicht ab (' + probeCon + ' statt ' + needCon + ').');

        var fname = outFileName(info.name);
        lastFile = fname;
        /* Ansicht auf den übernommenen Stand umstellen (Original bleibt unverändert) */
        loadQea(ab, fname);
        if (typeof showView === 'function') showView('edit');
        if (typeof EDIT !== 'undefined' && EDIT._deliver) EDIT._deliver(out, fname);
        busy = false;
        if (chkBtn) chkBtn.textContent = '🔍 Nur prüfen';
        if (appBtn) appBtn.textContent = '⬇ Übernehmen';
        updateButtons();
        renderReport(plan.report, true, fname);
        toast('Standardelemente übernommen: ' + fmt(plan.report.elemente) + ' Elemente, ' + fmt(plan.report.kanten) + ' Kanten.');
      } catch (e) {
        if (db) { try { db.close(); } catch (e2) { } }
        busy = false;
        if (chkBtn) chkBtn.textContent = '🔍 Nur prüfen';
        if (appBtn) appBtn.textContent = '⬇ Übernehmen';
        updateButtons();
        renderError((e && e.message) ? e.message : String(e));
      }
    }, function (e) {
      busy = false;
      if (chkBtn) chkBtn.textContent = '🔍 Nur prüfen';
      if (appBtn) appBtn.textContent = '⬇ Übernehmen';
      updateButtons();
      renderError('SQLite-Engine konnte nicht geladen werden: ' + (e && e.message ? e.message : e));
    });
  }

  /* Startet ein neues Modell, das ausschliesslich aus dem Katalog besteht:
     dieselbe Datei wird ueber den normalen Ladeweg geoeffnet. */
  function openAsModel() {
    if (!catFile) { renderError('Bitte zuerst eine Katalog-.qea wählen.'); return; }
    if (typeof DB !== 'undefined' && DB &&
        !window.confirm('Das aktuelle Modell wird ersetzt. Fortfahren?')) return;
    var inp = document.getElementById('file');
    if (!inp) { renderError('Ladeweg nicht gefunden.'); return; }
    try {
      var dt = new DataTransfer();
      dt.items.add(catFile);
      inp.files = dt.files;
      window.__pickMode = false;
      inp.dispatchEvent(new Event('change'));
    } catch (e) {
      renderError('Katalog konnte nicht als Modell geöffnet werden: ' +
        (e && e.message ? e.message : e));
    }
  }

  function check() { run(false); }
  function apply() { run(true); }

  /* ================= Fassade ================= */
  return {
    version: 'v1.0',
    pickFile: pickFile,
    openAsModel: openAsModel,
    check: check,
    apply: apply,
    toggleAll: toggleAll,
    pkgToggle: pkgToggle,
    selection: selection,
    state: function () {
      return {
        catalog: cat ? cat.name : null,
        selected: selection(),
        busy: busy,
        mode: lastMode,
        file: lastFile
      };
    },
    _lastReport: function () { return lastReport; },
    _lastTableRows: function () { return lastTableRows; },
    _selectByName: function (name) {
      var list = document.querySelectorAll('.eh-stdpkg'), i, hit = null;
      for (i = 0; i < list.length; i++) {
        var id = asInt(list[i].getAttribute('data-id'));
        if (cat && cat.byId[id] && cat.byId[id].name.toLowerCase() === String(name).toLowerCase()) { hit = list[i]; break; }
      }
      if (hit) { hit.checked = true; updateButtons(); return true; }
      return false;
    }
  };
})();
