/* eam-formats.js -- Format-Adapter fuer die HTML-Werkzeuge (XMI 2.1 + JSON-Batch).
 *
 * Eine Quelle fuer alle drei HTML-Apps: Datei -> Modell (DB-Interface mit
 * rows('t_*') im EA-Schema) und Modell -> Datei. Der XMI-Dialekt ist
 * derselbe wie in packages/core/xmi_writer.py / xmi_reader.py:
 *
 *   <xmi:XMI xmi:version="2.1">
 *     <uml:Model xmi:type="uml:Model" ...>          Pakete/Elemente/Beziehungen
 *     <xmi:Extension extender="Enterprise Architect">
 *       <technology .../> <connectors/> <diagrams/>
 *     </xmi:Extension>
 *   </xmi:XMI>
 *
 * Stereotypen, Tagged Values und Notizen stehen in <xmi:Extension>-Bloecken
 * (stereotype/properties/notes/tags/xrefs); Sichten in <diagrams> mit
 * Mitgliedern und Geometrie. Der JSON-Batch (nodes/edges) folgt
 * packages/core/batch-schema.json.
 *
 * Vertrag: gleiche Datei -> gleiche Zeilen wie der SQLite-Reader
 * (qeaOpen); damit laeuft buildModel() fuer .qea, .xmi und .json
 * unveraendert. Fehler sind laut (Ausnahme mit Klartext), nie still.
 */
(function (global) {
  'use strict';

  var XMI_NS = 'http://www.omg.org/spec/XMI/20131001';
  var UML_NS = 'http://www.omg.org/spec/UML/20131001';

  function fail(msg) { throw new Error('Format: ' + msg); }

  /* ================= Erkennung ================= */

  function isSqliteBytes(u8) {
    if (!u8 || u8.length < 16) return false;
    var sig = 'SQLite format 3';
    for (var i = 0; i < sig.length; i++) if (u8[i] !== sig.charCodeAt(i)) return false;
    return u8[sig.length] === 0;
  }

  function decodeText(u8) {
    if (typeof TextDecoder !== 'undefined') return new TextDecoder('utf-8').decode(u8);
    var s = '';
    for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
    try { return decodeURIComponent(escape(s)); } catch (e) { return s; }
  }

  /* ================= Hilfen ================= */

  function lokal(tag) {
    var t = String(tag || '');
    var k = t.lastIndexOf('}');
    if (k >= 0) t = t.slice(k + 1);
    var d = t.lastIndexOf(':');
    return d >= 0 ? t.slice(d + 1) : t;
  }

  function kinder(el, name) {
    var out = [], c = el && el.firstChild;
    for (; c; c = c.nextSibling) if (c.nodeType === 1 && lokal(c.nodeName) === name) out.push(c);
    return out;
  }

  function kind(el, name) {
    var c = el && el.firstChild;
    for (; c; c = c.nextSibling) if (c.nodeType === 1 && lokal(c.nodeName) === name) return c;
    return null;
  }

  function attr(el, n1, n2) {
    if (!el) return '';
    if (el.hasAttribute(n1)) return el.getAttribute(n1) || '';
    if (n2 && el.hasAttribute(n2)) return el.getAttribute(n2) || '';
    if (n2 || el.namespaceURI) {
      var as = el.attributes;
      for (var i = 0; i < as.length; i++) {
        var ln = lokal(as[i].name);
        if (ln === n1 || (n2 && ln === n2)) return as[i].value || '';
      }
    }
    return '';
  }

  function text(el) {
    if (!el) return '';
    return (el.textContent || '').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '');
  }

  /* Deterministische GUID wie im Python-Kern: "{8-4-4-4-12}" aus FNV-1a
     ueber Pfad|Stereotyp|Name (16 Byte, zu Hex verbreitert). */
  function fnv1a(str) {
    var h1 = 0x811c9dc5 | 0, h2 = 0x01000193 | 0;
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      h1 = (h1 ^ c) >>> 0; h1 = (h1 * 0x01000193) >>> 0;
      h2 = (h2 + c * 0x9e3779b1) >>> 0; h2 = (h2 ^ (h2 >>> 15)) >>> 0;
    }
    return (h1 >>> 0).toString(16).padStart(8, '0') + (h2 >>> 0).toString(16).padStart(8, '0');
  }

  function guidFor(pkgPath, st, name) {
    var hex = (fnv1a((pkgPath || '') + '|' + (st || '') + '|' + (name || '')) +
      fnv1a((name || '') + '|' + (pkgPath || '') + '|' + (st || '')));
    hex = hex.slice(0, 32);
    return ('{' + hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) +
      '-' + hex.slice(16, 20) + '-' + hex.slice(20, 32) + '}').toUpperCase();
  }

  /* ================= XMI -> Zeilen ================= */

  function extFelder(el) {
    /* <xmi:Extension> eines Elements: stereotype/properties/notes/tags/xrefs */
    var f = { stereotype: '', ea_type: '', alias: '', status: '', origin: '', notes: '', tags: [], xrefs: [] };
    var ext = kind(el, 'Extension');
    if (!ext) return f;
    var s = kind(ext, 'stereotype'); if (s) f.stereotype = text(s).trim();
    var n = kind(ext, 'notes'); if (n) f.notes = text(n);
    var p = kind(ext, 'properties');
    if (p) {
      f.ea_type = attr(p, 'ea_type');
      f.alias = attr(p, 'alias');
      f.status = attr(p, 'status');
      f.origin = attr(p, 'origin');
    }
    var bl, i, j, tg;
    var blks = kinder(ext, 'tags');
    for (i = 0; i < blks.length; i++) {
      tg = kinder(blks[i], 'tag');
      for (j = 0; j < tg.length; j++) f.tags.push({ name: attr(tg[j], 'name'), value: attr(tg[j], 'value') });
    }
    blks = kinder(ext, 'xrefs');
    for (i = 0; i < blks.length; i++) {
      tg = kinder(blks[i], 'tag');
      for (j = 0; j < tg.length; j++) f.xrefs.push({ name: attr(tg[j], 'name'), value: attr(tg[j], 'value') });
    }
    return f;
  }

  var UML_ZU_TYP = {
    Activity: 'Activity', Actor: 'Actor', Artifact: 'Artifact', Class: 'Class',
    Component: 'Component', Constraint: 'Constraint', DataType: 'DataType',
    Enumeration: 'Enumeration', Interaction: 'Interaction', Interface: 'Interface',
    Comment: 'Note', InstanceSpecification: 'Object', Node: 'Node', Signal: 'Signal',
    State: 'State', StateMachine: 'StateMachine', UseCase: 'UseCase'
  };
  var UML_ZU_CON = {
    Abstraction: 'Abstraction', Association: 'Association', Dependency: 'Dependency',
    Generalization: 'Generalization', InformationFlow: 'InformationFlow', Realization: 'Realization'
  };

  function xmiToDb(textInput) {
    if (typeof DOMParser === 'undefined') fail('DOMParser fehlt in dieser Umgebung');
    var doc = new DOMParser().parseFromString(String(textInput), 'application/xml');
    if (doc.getElementsByTagName('parsererror').length) fail('XML nicht parsebar');
    var wurzel = doc.documentElement;
    if (!wurzel || lokal(wurzel.nodeName) !== 'XMI') fail('Wurzel ist kein <xmi:XMI>');
    var model = kind(wurzel, 'Model');
    if (!model) fail('kein <uml:Model> im Dokument');

    var pkgs = [], objs = [], cons = [], tags = [];
    var byGuid = {};          // xmi:id -> {art:'paket'|'element', id:Number}
    var pkgByPath = {};       // 'A/B' -> Package_ID
    var pid = 0, oid = 0, cid = 0, tid = 0;

    function pfade(pfadEltern, name) {
      var pfad = pfadEltern ? pfadEltern + '/' + name : name;
      var kandidat = pfad, z = 2;
      while (pkgByPath[kandidat]) { kandidat = pfad + '#' + z; z++; }
      return kandidat;
    }

    function liestKnoten(el, elternId, elternPfad) {
      var art = attr(el, 'xmi:type', 'type');
      var typ = art.split(':').pop();
      var name = attr(el, 'name');
      var guid = attr(el, 'xmi:id', 'id');
      var quelle = kind(el, 'client'), ziel = kind(el, 'supplier');
      if (!quelle && !ziel) { quelle = kind(el, 'specific'); ziel = kind(el, 'general'); }

      if (typ === 'Package' && !quelle) {
        var pfad = pfade(elternPfad, name || ('Paket' + (pid + 1)));
        pid++;
        var f = extFelder(el);
        var pk = {
          Package_ID: pid, Name: name, Parent_ID: elternId || 0,
          TPos: pkgs.length, Notes: f.notes, Stereotype: f.stereotype,
          ea_guid: guid || '', x_path: pfad,
          x_tags: f.tags.length ? JSON.stringify(f.tags) : ''
        };
        pkgs.push(pk);
        pkgByPath[pfad] = pid;
        if (guid) byGuid[guid] = { art: 'paket', id: pid };
        var unter = kinder(el, 'packagedElement'), i;
        for (i = 0; i < unter.length; i++) liestKnoten(unter[i], pid, pfad);
        return;
      }

      if (quelle || ziel || UML_ZU_CON[typ]) {
        cid++;
        var cf = extFelder(el);
        var c = {
          Connector_ID: cid, Name: name, Stereotype: cf.stereotype,
          Connector_Type: cf.ea_type || UML_ZU_CON[typ] || 'Dependency',
          Type: cf.ea_type || UML_ZU_CON[typ] || 'Dependency',
          Direction: attr(el, 'direction'), Notes: cf.notes,
          Start_Object_ID: 0, End_Object_ID: 0, ea_guid: guid || '',
          x_tags: cf.tags.length ? JSON.stringify(cf.tags) : ''
        };
        var q = quelle ? attr(quelle, 'xmi:idref', 'idref') : '';
        var z = ziel ? attr(ziel, 'xmi:idref', 'idref') : '';
        c.__q = q; c.__z = z;   // wird nach dem Baum-Durchlauf aufgeloest
        cons.push(c);
        if (guid) byGuid[guid] = { art: 'beziehung', id: cid };
        return;
      }

      oid++;
      var ef = extFelder(el);
      var o = {
        Object_ID: oid, Name: name, Package_ID: elternId || 0, ParentID: 0,
        Object_Type: ef.ea_type || UML_ZU_TYP[typ] || 'Class',
        Stereotype: ef.stereotype, Notes: ef.notes,
        Alias: ef.alias, Status: ef.status, Hidden: 0,
        ea_guid: guid || '', x_origin: ef.origin || '',
        x_xrefs: ef.xrefs.length ? JSON.stringify(ef.xrefs) : ''
      };
      objs.push(o);
      if (guid) byGuid[guid] = { art: 'element', id: oid };
      for (var t = 0; t < ef.tags.length; t++) {
        tid++;
        tags.push({ PropertyID: tid, Object_ID: oid, Property: ef.tags[t].name, Value: ef.tags[t].value, Notes: null, ea_guid: '' });
      }
    }

    var top = kinder(model, 'packagedElement'), i;
    for (i = 0; i < top.length; i++) liestKnoten(top[i], 0, '');

    /* Endpunkte aufloesen (xmi:idref -> numerische EA-IDs) */
    for (i = 0; i < cons.length; i++) {
      var c = cons[i];
      var a = byGuid[c.__q], b = byGuid[c.__z];
      if (!a || !b) fail('Beziehung ' + (c.ea_guid || c.Name) + ': Endpunkt zeigt auf nichts');
      c.Start_Object_ID = a.id; c.End_Object_ID = b.id;
      delete c.__q; delete c.__z;
    }

    /* Technologie + Sichten aus dem globalen Extension-Block */
    var diags = [], dObjs = [], dLinks = [], tech = '';
    var exts = doc.getElementsByTagName('*'), e;
    for (e = 0; e < exts.length; e++) {
      if (lokal(exts[e].nodeName) !== 'Extension') continue;
      var tch = kind(exts[e], 'technology');
      if (tch && !tech) tech = attr(tch, 'profile');
      var dblk = kinder(exts[e], 'diagrams'), di, dj;
      for (di = 0; di < dblk.length; di++) {
        var ds = kinder(dblk[di], 'diagram');
        for (dj = 0; dj < ds.length; dj++) {
          var d = ds[dj];
          var dn = attr(d, 'name');
          if (!dn) fail('Sicht ohne Namen');
          var dpfad = attr(d, 'package');
          var dId = diags.length + 1;
          var dTags = { pid: pkgByPath[dpfad] || 0 };
          diags.push({
            Diagram_ID: dId, Name: dn, Diagram_Type: attr(d, 'type') || 'Custom',
            Package_ID: dTags.pid, Notes: text(kind(d, 'notes')),
            TPos: diags.length, ea_guid: attr(d, 'xmi:id', 'id') || '',
            x_path: dpfad, x_viewpoint: attr(d, 'viewpoint'),
            x_parent: attr(d, 'parent'),
            x_stereotype: text(kind(d, 'stereotype')).trim(),
            x_default: attr(d, 'default') ? 1 : 0
          });
          var mb = kinder(d, 'elements'), mi;
          for (mi = 0; mi < mb.length; mi++) {
            var ms = kinder(mb[mi], 'element'), mj;
            for (mj = 0; mj < ms.length; mj++) {
              var m = ms[mj];
              var ziel2 = byGuid[attr(m, 'xmi:idref', 'idref')];
              if (!ziel2 || ziel2.art !== 'element') fail('Sicht ' + dn + ': Mitglied zeigt auf kein Element');
              dObjs.push({
                DiagramID: dId, ObjectID: ziel2.id,
                RectLeft: num(attr(m, 'left')), RectTop: num(attr(m, 'top')),
                RectRight: num(attr(m, 'right')), RectBottom: num(attr(m, 'bottom')),
                Sequence: num(attr(m, 'sequence')), Hidden: 0, x_path: ''
              });
            }
          }
        }
      }
    }

    return makeDb({ t_package: pkgs, t_object: objs, t_connector: cons, t_objectproperties: tags, t_diagram: diags, t_diagramobjects: dObjs, t_diagramlinks: dLinks, x_technology: tech });
  }

  function num(v) { var n = parseInt(v, 10); return isNaN(n) ? 0 : n; }

  /* ================= JSON-Batch -> Zeilen ================= */

  function jsonToDb(textInput) {
    var daten;
    try { daten = JSON.parse(String(textInput)); }
    catch (e) { fail('JSON nicht parsebar: ' + e.message); }
    if (!daten || typeof daten !== 'object' || !Array.isArray(daten.nodes) || !Array.isArray(daten.edges))
      fail('Batch braucht nodes[] und edges[]');

    var pkgs = [], objs = [], cons = [], tags = [];
    var pkgByPath = {}, idMap = {};
    var pid = 0, oid = 0, cid = 0, tid = 0;

    function sichertPfad(pfad) {
      if (!pfad) return 0;
      if (pkgByPath[pfad]) return pkgByPath[pfad];
      var teile = pfad.split('/'), bisher = '', id = 0;
      for (var i = 0; i < teile.length; i++) {
        bisher = bisher ? bisher + '/' + teile[i] : teile[i];
        if (!pkgByPath[bisher]) {
          pid++;
          pkgs.push({ Package_ID: pid, Name: teile[i], Parent_ID: id, TPos: pkgs.length, Notes: '', Stereotype: '', ea_guid: '', x_path: bisher, x_tags: '' });
          pkgByPath[bisher] = pid;
        }
        id = pkgByPath[bisher];
      }
      return pkgByPath[pfad];
    }

    var i, n;
    for (i = 0; i < daten.nodes.length; i++) {
      n = daten.nodes[i];
      if (!n || typeof n.id !== 'string') fail('Knoten ' + i + ' ohne id');
      if (n.metaclass === 'Package') {
        var pfad = String(n.name || '');
        var pId = sichertPfad(pfad);
        idMap[n.id] = { art: 'paket', id: pId };
        if (pId && pkgs.length && pkgs[pkgs.length - 1].Package_ID === pId) {
          pkgs[pkgs.length - 1].Stereotype = n.stereotype || '';
          if (n.properties && n.properties.notes) pkgs[pkgs.length - 1].Notes = String(n.properties.notes);
        }
        continue;
      }
      oid++;
      var props = (n.properties && typeof n.properties === 'object') ? n.properties : {};
      var o = {
        Object_ID: oid, Name: String(n.name || ''), Package_ID: sichertPfad(String(n.package || '')),
        ParentID: 0, Object_Type: String(n.metaclass || 'Class'), Stereotype: String(n.stereotype || ''),
        Notes: props.notes != null ? String(props.notes) : '',
        Alias: props.alias != null ? String(props.alias) : '', Status: props.status != null ? String(props.status) : '',
        Hidden: 0, ea_guid: '', x_origin: props.origin != null ? String(props.origin) : '',
        x_xrefs: ''
      };
      objs.push(o);
      idMap[n.id] = { art: 'element', id: oid };
      for (var k in props) {
        if (!Object.prototype.hasOwnProperty.call(props, k)) continue;
        if (k === 'notes' || k === 'alias' || k === 'status' || k === 'origin') continue;
        tid++;
        tags.push({ PropertyID: tid, Object_ID: oid, Property: String(k), Value: String(props[k] == null ? '' : props[k]), Notes: null, ea_guid: '' });
      }
    }

    for (i = 0; i < daten.edges.length; i++) {
      var ed = daten.edges[i];
      if (!ed) continue;
      var a = idMap[ed.source_id], b = idMap[ed.target_id];
      if (!a || !b) fail('Kante ' + (ed.id || i) + ': Endpunkt zeigt auf keinen Knoten');
      cid++;
      var ep = (ed.properties && typeof ed.properties === 'object') ? ed.properties : {};
      cons.push({
        Connector_ID: cid, Name: ed.name != null ? String(ed.name) : '',
        Stereotype: String(ed.connector || ''), Connector_Type: String(ed.metaclass || 'Dependency'),
        Type: String(ed.metaclass || 'Dependency'), Direction: '', Notes: ep.notes != null ? String(ep.notes) : '',
        Start_Object_ID: a.id, End_Object_ID: b.id, ea_guid: '', x_tags: ''
      });
    }

    var meta = daten.metadata || {};
    return makeDb({ t_package: pkgs, t_object: objs, t_connector: cons, t_objectproperties: tags, t_diagram: [], t_diagramobjects: [], t_diagramlinks: [], x_technology: String(meta.standard || '') });
  }

  /* ================= DB-Interface ================= */

  function makeDb(tables) {
    return {
      tables: tables,
      tableNames: Object.keys(tables).filter(function (k) { return k.indexOf('x_') !== 0; }),
      hasTable: function (name) { return !!tables[name]; },
      rows: function (name) {
        var t = tables[name];
        return t ? t.slice() : [];
      },
      __x: { technology: tables.x_technology || '' }
    };
  }

  /* ================= Zeilen -> XMI / JSON ================= */

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\r/g, '&#13;');
  }

  function escAttr(s) {
    return esc(s).replace(/\r/g, '&#13;').replace(/\n/g, '&#10;').replace(/\t/g, '&#9;')
      .replace(/"/g, '&quot;');
  }

  function ind(n) { var s = ''; for (var i = 0; i < n; i++) s += '  '; return s; }

  function tagListe(jsonStr, tiefe, block) {
    if (!jsonStr) return [];
    var arr;
    try { arr = JSON.parse(jsonStr); } catch (e) { return []; }
    if (!arr || !arr.length) return [];
    var out = [ind(tiefe) + '<' + block + '>'];
    for (var i = 0; i < arr.length; i++) {
      out.push(ind(tiefe + 1) + '<tag name="' + escAttr(arr[i].name) + '" value="' + escAttr(arr[i].value) + '"/>');
    }
    out.push(ind(tiefe) + '</' + block + '>');
    return out;
  }

  function rowsOf(db, name) {
    try { return db.rows(name) || []; } catch (e) { return []; }
  }

  /* Paket-Spiegelobjekte (EA haelt Pakete zusaetzlich als t_object-Zeile mit
     Object_Type='Package') sind keine Elemente -- der qea-Reader des Python-
     Kerns behandelt sie genauso. Export: ueberspringen; Endpunkte auf das
     gespiegelte Paket aufloesen. */
  function istSpiegel(o) {
    return String(o.Object_Type || '').toLowerCase() === 'package';
  }

  /* Paketpfade mit der Konvention des qea-Readers (Python-Kern):
     gleichnamige Geschwister erhalten '#2', '#3' ... in der Reihenfolge
     (TPos, Package_ID). Ohne diese Nummerierung wuerden Pfadangaben des
     Browser-Exports von denen des Kerns abweichen. */
  function pfadeBauen(pkgs) {
    var byId = {}, kinder = {}, wurzel = [], i;
    for (i = 0; i < pkgs.length; i++) byId[pkgs[i].Package_ID] = pkgs[i];
    for (i = 0; i < pkgs.length; i++) {
      var par = Number(pkgs[i].Parent_ID || 0);
      if (par && byId[par]) {
        if (!kinder[par]) kinder[par] = [];
        kinder[par].push(pkgs[i]);
      } else wurzel.push(pkgs[i]);
    }
    function reihenfolge(list) {
      return list.slice().sort(function (a, b) {
        return (Number(a.TPos || 0) - Number(b.TPos || 0))
          || (Number(a.Package_ID || 0) - Number(b.Package_ID || 0));
      });
    }
    var pfade = {};
    function walk(list, basis) {
      var benutzt = {}, geordnet = reihenfolge(list), k;
      for (k = 0; k < geordnet.length; k++) {
        var name = String(geordnet[k].Name || 'Paket');
        var seg = name, z = 2;
        while (benutzt[seg]) { seg = name + '#' + z; z++; }
        benutzt[seg] = 1;
        var pfad = basis ? basis + '/' + seg : seg;
        pfade[geordnet[k].Package_ID] = pfad;
        walk(kinder[geordnet[k].Package_ID] || [], pfad);
      }
    }
    walk(wurzel, '');
    return pfade;
  }

  function dbToXmi(db, opts) {
    opts = opts || {};
    var pkgs = rowsOf(db, 't_package'), objs = rowsOf(db, 't_object'), cons = rowsOf(db, 't_connector');
    var diags = rowsOf(db, 't_diagram'), dobjs = rowsOf(db, 't_diagramobjects');
    var tags = rowsOf(db, 't_objectproperties');
    var tech = (db.__x && db.__x.technology) ? String(db.__x.technology) : '';

    /* Tagged Values je Element (auch aus t_connectortag fuer Beziehungen) */
    var tagsByObj = {}, i, j;
    for (i = 0; i < tags.length; i++) {
      var t = tags[i];
      var ok = t.Object_ID != null ? t.Object_ID : t.ObjectID;
      if (ok == null) continue;
      if (!tagsByObj[ok]) tagsByObj[ok] = [];
      tagsByObj[ok].push({ name: String(t.Property || ''), value: String(t.Value == null ? '' : t.Value) });
    }
    var oMap = {};
    for (i = 0; i < objs.length; i++) oMap[objs[i].Object_ID] = objs[i];
    /* Beziehungs-Tags (EA: t_connectortag mit ElementID = Connector_ID;
       die Spalten VALUE/NOTES stehen je nach Datei in anderer Schreibweise) */
    var alleCTags = {};
    var cTagRows = rowsOf(db, 't_connectortag');
    for (i = 0; i < cTagRows.length; i++) {
      var ct = cTagRows[i];
      var cKey = ct.ElementID != null ? ct.ElementID : ct.Connector_ID;
      if (cKey == null) continue;
      var cVal = ct.Value != null ? ct.Value : (ct.VALUE != null ? ct.VALUE : '');
      if (!alleCTags[cKey]) alleCTags[cKey] = [];
      alleCTags[cKey].push({ name: String(ct.Property || ''), value: String(cVal == null ? '' : cVal) });
    }
    function conTags(c) {
      return c.x_tags || JSON.stringify(alleCTags[c.Connector_ID] || []);
    }

    /* Paketbaum + Pfadauflösung */
    var byId = {}, kinderMap = {}, wurzel = [];
    var allePfade = pfadeBauen(pkgs);
    for (i = 0; i < pkgs.length; i++) {
      var p = pkgs[i];
      byId[p.Package_ID] = p;
    }
    for (i = 0; i < pkgs.length; i++) {
      var p2 = pkgs[i];
      var par = Number(p2.Parent_ID || 0);
      if (par && byId[par]) {
        if (!kinderMap[par]) kinderMap[par] = [];
        kinderMap[par].push(p2);
      } else wurzel.push(p2);
    }
    function pfadVon(p) {
      if (p && p.x_path) return String(p.x_path);
      return (p && allePfade[p.Package_ID]) ? allePfade[p.Package_ID] : '';
    }

    var objsByPkg = {};
    for (i = 0; i < objs.length; i++) {
      var o = objs[i];
      if (istSpiegel(o)) continue;
      var pid2 = Number(o.Package_ID || 0);
      if (!objsByPkg[pid2]) objsByPkg[pid2] = [];
      objsByPkg[pid2].push(o);
    }
    var consByPkg = {};
    for (i = 0; i < cons.length; i++) {
      var c = cons[i];
      var start = objs.filter(function (x) { return Number(x.Object_ID) === Number(c.Start_Object_ID); })[0];
      var key = start ? Number(start.Package_ID || 0) : 0;
      if (!consByPkg[key]) consByPkg[key] = [];
      consByPkg[key].push(c);
    }

    /* Spiegel -> gespiegeltes Paket (per ea_guid) fuer Endpunkte; der Spiegel
       traegt zudem Stereotyp und Tags des Pakets (EA fuehrt sie dort, nicht
       in t_package). */
    var pkgByGuid = {};
    for (i = 0; i < pkgs.length; i++) {
      if (pkgs[i].ea_guid) pkgByGuid[String(pkgs[i].ea_guid).toUpperCase()] = pkgs[i];
    }
    var spiegelByGuid = {};
    for (i = 0; i < objs.length; i++) {
      if (istSpiegel(objs[i]) && objs[i].ea_guid) {
        spiegelByGuid[String(objs[i].ea_guid).toUpperCase()] = objs[i];
      }
    }
    function spiegelVon(p) {
      return (p && p.ea_guid) ? spiegelByGuid[String(p.ea_guid).toUpperCase()] : null;
    }
    function paketStereotyp(p) {
      if (p && p.Stereotype) return p.Stereotype;
      var m = spiegelVon(p);
      return m ? String(m.Stereotype || '') : '';
    }
    function paketTags(p) {
      if (p && p.x_tags) return p.x_tags;
      var m = spiegelVon(p);
      return m ? JSON.stringify(tagsByObj[m.Object_ID] || []) : '';
    }
    function zielGuid(row) {
      if (!row) return guidOf({ ea_guid: '' }, '');
      if (istSpiegel(row)) {
        var p3 = row.ea_guid ? pkgByGuid[String(row.ea_guid).toUpperCase()] : null;
        if (p3) return guidOf(p3, pfadVon(p3));
      }
      return guidOf(row, pfadVon(byId[row.Package_ID] || { Name: '', Parent_ID: 0 }));
    }

    function guidOf(row, pfad) {
      if (row.ea_guid) return String(row.ea_guid).toUpperCase();
      return guidFor(pfad, row.Stereotype || '', row.Name || '');
    }

    var zeilen = [];
    zeilen.push('<?xml version="1.0" encoding="UTF-8"?>');
    zeilen.push('<xmi:XMI xmi:version="2.1" xmlns:xmi="' + XMI_NS + '" xmlns:uml="' + UML_NS + '">');
    zeilen.push(ind(1) + '<uml:Model xmi:type="uml:Model" xmi:id="' + guidFor('', '', 'Model') + '" name="Model">');

    function elementBlock(o, tiefe, pfad) {
      var out = [];
      var typMap = { Class: 'uml:Class', Interface: 'uml:Interface', Actor: 'uml:Actor', UseCase: 'uml:UseCase', Component: 'uml:Component', Node: 'uml:Node', Artifact: 'uml:Artifact', Enumeration: 'uml:Enumeration', DataType: 'uml:DataType', Signal: 'uml:Signal', Activity: 'uml:Activity', State: 'uml:State', StateMachine: 'uml:StateMachine', Interaction: 'uml:Interaction', Note: 'uml:Comment', Object: 'uml:InstanceSpecification' };
      var uml = typMap[o.Object_Type] || 'uml:Class';
      /* Notiz-Spalten wie der qea-Reader des Kerns: 'Note' vor 'Notes',
         nach Spaltenexistenz (EA fuehrt beide Spalten). */
      var noteWert = ('Note' in o) ? o.Note : o.Notes;
      out.push(ind(tiefe) + '<packagedElement xmi:type="' + uml + '" xmi:id="' + guidOf(o, pfad) + '" name="' + escAttr(o.Name || '') + '">');
      var ext = [];
      if (o.Stereotype) ext.push(ind(tiefe + 2) + '<stereotype>' + esc(o.Stereotype) + '</stereotype>');
      var props = ' ea_type="' + escAttr(o.Object_Type || 'Class') + '"';
      if (o.Alias) props += ' alias="' + escAttr(o.Alias) + '"';
      if (o.Status) props += ' status="' + escAttr(o.Status) + '"';
      if (o.x_origin) props += ' origin="' + escAttr(o.x_origin) + '"';
      ext.push(ind(tiefe + 2) + '<properties' + props + '/>');
      if (noteWert) ext.push(ind(tiefe + 2) + '<notes>' + esc(noteWert) + '</notes>');
      ext = ext.concat(tagListe(JSON.stringify(tagsByObj[o.Object_ID] || []), tiefe + 2, 'tags'));
      ext = ext.concat(tagListe(o.x_xrefs, tiefe + 2, 'xrefs'));
      out.push(ind(tiefe + 1) + '<xmi:Extension extender="Enterprise Architect">');
      out = out.concat(ext);
      out.push(ind(tiefe + 1) + '</xmi:Extension>');
      out.push(ind(tiefe) + '</packagedElement>');
      return out;
    }

    function connectorBlock(c, tiefe, pfad) {
      var out = [];
      var map = { Generalization: 'uml:Generalization', Realization: 'uml:Realization', Association: 'uml:Association', Aggregation: 'uml:Association', Composition: 'uml:Association', InformationFlow: 'uml:InformationFlow' };
      var uml = map[c.Connector_Type] || 'uml:Dependency';
      var gid = c.ea_guid ? String(c.ea_guid).toUpperCase() : guidFor('connector', c.Stereotype || '', (c.Start_Object_ID || '') + '|' + (c.End_Object_ID || ''));
      var a = '<packagedElement xmi:type="' + uml + '" xmi:id="' + gid + '"';
      if (c.Name) a += ' name="' + escAttr(c.Name) + '"';
      if (c.Direction && c.Direction !== 'Source -> Destination') a += ' direction="' + escAttr(c.Direction) + '"';
      out.push(ind(tiefe) + a + '>');
      var sg = guidOf({ ea_guid: '' }, '');
      var srcObj = oMap[c.Start_Object_ID], tgtObj = oMap[c.End_Object_ID];
      var src = zielGuid(srcObj);
      var tgt = zielGuid(tgtObj);
      if (uml === 'uml:Generalization') {
        out.push(ind(tiefe + 1) + '<specific xmi:idref="' + src + '"/>');
        out.push(ind(tiefe + 1) + '<general xmi:idref="' + tgt + '"/>');
      } else {
        out.push(ind(tiefe + 1) + '<client xmi:idref="' + src + '"/>');
        out.push(ind(tiefe + 1) + '<supplier xmi:idref="' + tgt + '"/>');
      }
      var ext = [ind(tiefe + 2) + '<properties ea_type="' + escAttr(c.Connector_Type || 'Dependency') + '"/>'];
      if (c.Stereotype) ext.splice(0, 0, ind(tiefe + 2) + '<stereotype>' + esc(c.Stereotype) + '</stereotype>');
      if (c.Notes) ext.push(ind(tiefe + 2) + '<notes>' + esc(c.Notes) + '</notes>');
      ext = ext.concat(tagListe(conTags(c), tiefe + 2, 'tags'));
      out.push(ind(tiefe + 1) + '<xmi:Extension extender="Enterprise Architect">');
      out = out.concat(ext);
      out.push(ind(tiefe + 1) + '</xmi:Extension>');
      out.push(ind(tiefe) + '</packagedElement>');
      return out;
    }

    function pkgBlock(p, tiefe) {
      var out = [];
      var pfad = pfadVon(p);
      out.push(ind(tiefe) + '<packagedElement xmi:type="uml:Package" xmi:id="' + guidOf(p, pfad) + '" name="' + escAttr(p.Name || '') + '">');
      var ext = [];
      var pSt = paketStereotyp(p);
      if (pSt) ext.push(ind(tiefe + 2) + '<stereotype>' + esc(pSt) + '</stereotype>');
      if (p.Notes) ext.push(ind(tiefe + 2) + '<notes>' + esc(p.Notes) + '</notes>');
      ext = ext.concat(tagListe(paketTags(p), tiefe + 2, 'tags'));
      if (ext.length) {
        out.push(ind(tiefe + 1) + '<xmi:Extension extender="Enterprise Architect">');
        out = out.concat(ext);
        out.push(ind(tiefe + 1) + '</xmi:Extension>');
      }
      var ks = kinderMap[p.Package_ID] || [];
      ks.sort(function (a, b) { return (Number(a.TPos || 0) - Number(b.TPos || 0)) || (Number(a.Package_ID || 0) - Number(b.Package_ID || 0)); });
      for (var i3 = 0; i3 < ks.length; i3++) out = out.concat(pkgBlock(ks[i3], tiefe + 1));
      var os = objsByPkg[p.Package_ID] || [];
      for (var i4 = 0; i4 < os.length; i4++) out = out.concat(elementBlock(os[i4], tiefe + 1, pfad));
      var cs = consByPkg[p.Package_ID] || [];
      for (var i5 = 0; i5 < cs.length; i5++) out = out.concat(connectorBlock(cs[i5], tiefe + 1, pfad));
      out.push(ind(tiefe) + '</packagedElement>');
      return out;
    }

    wurzel.sort(function (a, b) { return (Number(a.TPos || 0) - Number(b.TPos || 0)) || (Number(a.Package_ID || 0) - Number(b.Package_ID || 0)); });
    for (i = 0; i < wurzel.length; i++) zeilen = zeilen.concat(pkgBlock(wurzel[i], 2));
    /* Elemente ohne Paket (Wurzel) und Beziehungen ohne Paketanker */
    var frei = objsByPkg[0] || [];
    for (i = 0; i < frei.length; i++) zeilen = zeilen.concat(elementBlock(frei[i], 2, ''));
    var freiC = consByPkg[0] || [];
    for (i = 0; i < freiC.length; i++) zeilen = zeilen.concat(connectorBlock(freiC[i], 2, ''));

    zeilen.push(ind(1) + '</uml:Model>');
    zeilen.push(ind(1) + '<xmi:Extension extender="Enterprise Architect">');
    if (tech) zeilen.push(ind(2) + '<technology profile="' + escAttr(tech) + '"/>');
    if (cons.length) {
      zeilen.push(ind(2) + '<connectors>');
      for (i = 0; i < cons.length; i++) {
        var g2 = cons[i].ea_guid ? String(cons[i].ea_guid).toUpperCase() : guidFor('connector', cons[i].Stereotype || '', (cons[i].Start_Object_ID || '') + '|' + (cons[i].End_Object_ID || ''));
        zeilen.push(ind(3) + '<ref xmi:idref="' + g2 + '"/>');
      }
      zeilen.push(ind(2) + '</connectors>');
    }
    if (diags.length) {
      zeilen.push(ind(2) + '<diagrams>');
      for (i = 0; i < diags.length; i++) {
        var d3 = diags[i];
        var dAttrs = ' name="' + escAttr(d3.Name || '') + '" type="' + escAttr(d3.Diagram_Type || 'Custom') + '"';
        dAttrs += ' package="' + escAttr(d3.x_path || pfadVon(byId[d3.Package_ID] || { Name: '', Parent_ID: 0 })) + '"';
        if (d3.x_parent) dAttrs += ' parent="' + escAttr(d3.x_parent) + '"';
        if (Number(d3.x_default || 0)) dAttrs += ' default="1"';
        if (d3.x_viewpoint) dAttrs += ' viewpoint="' + escAttr(d3.x_viewpoint) + '"';
        var dGuid = d3.ea_guid ? String(d3.ea_guid).toUpperCase() : guidFor('diagram', d3.x_stereotype || '', (d3.x_path || '') + '|' + (d3.Name || ''));
        zeilen.push(ind(3) + '<diagram xmi:id="' + dGuid + '"' + dAttrs + '>');
        if (d3.x_stereotype) zeilen.push(ind(4) + '<stereotype>' + esc(d3.x_stereotype) + '</stereotype>');
        if (d3.Notes) zeilen.push(ind(4) + '<notes>' + esc(d3.Notes) + '</notes>');
        var mit = [];
        for (j = 0; j < dobjs.length; j++) {
          if (Number(dobjs[j].DiagramID) !== Number(d3.Diagram_ID)) continue;
          mit.push(dobjs[j]);
        }
        if (mit.length) {
          zeilen.push(ind(4) + '<elements>');
          for (j = 0; j < mit.length; j++) {
            var mm = mit[j];
            var mo = oMap[mm.ObjectID];
            /* Spiegelobjekte (Pakete) sind keine Sichtmitglieder -- der
               xmi_reader des Kerns erwartet Elemente. */
            if (!mo || istSpiegel(mo)) continue;
            var mg = zielGuid(mo);
            zeilen.push(ind(5) + '<element xmi:idref="' + mg + '" left="' + (mm.RectLeft || 0) + '" top="' + (mm.RectTop || 0) + '" right="' + (mm.RectRight || 0) + '" bottom="' + (mm.RectBottom || 0) + '" sequence="' + (mm.Sequence || 0) + '"/>');
          }
          zeilen.push(ind(4) + '</elements>');
        }
        zeilen.push(ind(3) + '</diagram>');
      }
      zeilen.push(ind(2) + '</diagrams>');
    }
    zeilen.push(ind(1) + '</xmi:Extension>');
    zeilen.push('</xmi:XMI>');
    return zeilen.join('\n') + '\n';
  }

  function upperSnake(s) {
    var t = String(s || '').replace(/([a-z0-9])([A-Z])/g, '$1_$2');
    t = t.replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '').toUpperCase();
    return t || 'RELATION';
  }

  function dbToJson(db, opts) {
    opts = opts || {};
    var pkgs = rowsOf(db, 't_package'), objs = rowsOf(db, 't_object'), cons = rowsOf(db, 't_connector');
    var tags = rowsOf(db, 't_objectproperties');
    var tech = (db.__x && db.__x.technology) ? String(db.__x.technology) : '';
    var i, j;

    function pfadVon2(p) {
      if (!p) return '';
      if (p.x_path) return String(p.x_path);
      return allePfade2[p.Package_ID] || '';
    }
    var allePfade2 = pfadeBauen(pkgs);

    var nodes = [], edges = [], idOf = {};
    /* Spiegelobjekte tragen Stereotyp und Tags der Paketknoten */
    var spiegelInfo = {};
    for (i = 0; i < objs.length; i++) {
      if (istSpiegel(objs[i]) && objs[i].ea_guid) {
        spiegelInfo[String(objs[i].ea_guid).toUpperCase()] = objs[i];
      }
    }
    var paketKnoten = [];
    for (i = 0; i < pkgs.length; i++) {
      var p = pkgs[i];
      var nid = 'n' + (nodes.length + 1);
      idOf['p' + p.Package_ID] = nid;
      var stP = String(p.Stereotype || '');
      var zusatz = spiegelInfo[String(p.ea_guid || '').toUpperCase()];
      if (!stP && zusatz) stP = String(zusatz.Stereotype || '');
      var knotenP = { id: nid, name: pfadVon2(p), metaclass: 'Package', labels: [stP || 'Package'], package: pfadVon2(p) };
      if (stP) knotenP.stereotype = stP;
      nodes.push(knotenP);
      paketKnoten.push({ knoten: knotenP, pkg: p, spiegel: zusatz || null });
    }
    var tagsBy = {};
    for (i = 0; i < tags.length; i++) {
      var t = tags[i];
      var ok = t.Object_ID != null ? t.Object_ID : t.ObjectID;
      if (ok == null) continue;
      if (!tagsBy[ok]) tagsBy[ok] = {};
      tagsBy[ok][String(t.Property || '')] = String(t.Value == null ? '' : t.Value);
    }
    for (i = 0; i < objs.length; i++) {
      var o = objs[i];
      if (istSpiegel(o)) continue;
      var nid2 = 'n' + (nodes.length + 1);
      idOf['o' + o.Object_ID] = nid2;
      var props = {};
      for (j in (tagsBy[o.Object_ID] || {})) if (Object.prototype.hasOwnProperty.call(tagsBy[o.Object_ID], j)) props[j] = tagsBy[o.Object_ID][j];
      if (o.Notes) props.notes = String(o.Notes);
      if (o.Alias) props.alias = String(o.Alias);
      if (o.Status) props.status = String(o.Status);
      var knoten = {
        id: nid2, name: String(o.Name || ''), metaclass: String(o.Object_Type || 'Class'),
        labels: [String(o.Stereotype || o.Object_Type || 'Class')], package: pfadVon2(pkgs.filter(function (x) { return Number(x.Package_ID) === Number(o.Package_ID); })[0])
      };
      if (o.Stereotype) knoten.stereotype = String(o.Stereotype);
      var keys = Object.keys(props).sort();
      if (keys.length) {
        knoten.properties = {};
        for (j = 0; j < keys.length; j++) knoten.properties[keys[j]] = props[keys[j]];
      }
      nodes.push(knoten);
    }
    /* Spiegel -> Paketknoten fuer Kanten-Endpunkte */
    var spiegelPkg = {};
    for (i = 0; i < objs.length; i++) {
      if (!istSpiegel(objs[i])) continue;
      var gk = String(objs[i].ea_guid || '').toUpperCase();
      for (j = 0; j < pkgs.length; j++) {
        if (String(pkgs[j].ea_guid || '').toUpperCase() === gk) {
          spiegelPkg[objs[i].Object_ID] = pkgs[j].Package_ID;
          break;
        }
      }
    }
    function knotenIdVon(oid) {
      var direkt = idOf['o' + oid];
      if (direkt) return direkt;
      var pid3 = spiegelPkg[oid];
      return pid3 != null ? (idOf['p' + pid3] || '') : '';
    }
    for (i = 0; i < cons.length; i++) {
      var c = cons[i];
      var eid = 'e' + (edges.length + 1);
      var cn = String(c.Stereotype || c.Connector_Type || 'Dependency');
      var e = {
        id: eid, source_id: knotenIdVon(c.Start_Object_ID),
        target_id: knotenIdVon(c.End_Object_ID),
        connector: cn, type: upperSnake(cn), metaclass: String(c.Connector_Type || 'Dependency')
      };
      if (c.Name) e.name = String(c.Name);
      var eProps = {};
      var cTagAlt = c.x_tags;
      if (!cTagAlt) {
        var cRows = rowsOf(db, 't_connectortag');
        var ges = [];
        for (var ci = 0; ci < cRows.length; ci++) {
          var cTr = cRows[ci];
          var cId2 = cTr.ElementID != null ? cTr.ElementID : cTr.Connector_ID;
          if (Number(cId2) === Number(c.Connector_ID)) {
            var cVal2 = cTr.Value != null ? cTr.Value : (cTr.VALUE != null ? cTr.VALUE : '');
            ges.push({ name: String(cTr.Property || ''), value: String(cVal2 == null ? '' : cVal2) });
          }
        }
        cTagAlt = JSON.stringify(ges);
      }
      try {
        var cArr = JSON.parse(cTagAlt || '[]');
        for (var cix = 0; cix < cArr.length; cix++) eProps[String(cArr[cix].name)] = String(cArr[cix].value);
      } catch (e0) { /* keine Tags */ }
      if (c.Notes) eProps.notes = String(c.Notes);
      if (Object.keys(eProps).length) e.properties = eProps;
      edges.push(e);
    }

    var daten = {
      metadata: {
        generator: 'eam-formats-json',
        standard: tech,
        source_document: String(opts.sourceDocument || opts.name || 'Modell'),
        node_count: nodes.length,
        edge_count: edges.length
      },
      nodes: nodes,
      edges: edges
    };
    return JSON.stringify(daten, null, 2) + '\n';
  }

  /* ================= Oeffentliche Schnittstelle ================= */

  function toDb(input, name) {
    /* input: ArrayBuffer|Uint8Array|String. Liefert DB oder null (dann ist
       die Datei SQLite und qeaOpen ist zustaendig). */
    var u8 = null, s = null;
    if (typeof input === 'string') { s = input; }
    else if (input && input.buffer && input.BYTES_PER_ELEMENT !== undefined) { u8 = input; }
    else if (input instanceof ArrayBuffer) { u8 = new Uint8Array(input); }
    else if (input && input.byteLength !== undefined) { u8 = new Uint8Array(input); }
    if (u8) {
      if (isSqliteBytes(u8)) return null;
      s = decodeText(u8);
    }
    if (s == null) fail('Eingabe nicht lesbar');
    var kopf = s.slice(0, 600).replace(/^\uFEFF/, '').trim();
    if (kopf.charAt(0) === '<' || kopf.indexOf('<xmi:XMI') >= 0 || kopf.indexOf('<uml:Model') >= 0) return xmiToDb(s);
    if (kopf.charAt(0) === '{') return jsonToDb(s);
    fail('Unbekanntes Format in ' + (name || 'Datei') + ': weder SQLite (.qea), noch XMI, noch JSON-Batch');
  }

  function download(textInhalt, dateiname, mime) {
    var blob = new Blob([textInhalt], { type: mime || 'application/octet-stream' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = dateiname || 'export.dat';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 200);
  }

  global.EAMF = {
    isSqliteBytes: isSqliteBytes,
    decodeText: decodeText,
    toDb: toDb,
    xmiToDb: xmiToDb,
    jsonToDb: jsonToDb,
    dbToXmi: dbToXmi,
    dbToJson: dbToJson,
    download: download
  };
})(typeof window !== 'undefined' ? window : this);