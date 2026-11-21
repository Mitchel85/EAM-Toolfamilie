/* eam-formats.js -- Format-Adapter fuer die HTML-Werkzeuge (XMI 2.1, JSON-Batch & ArchiMate-3.2-Bruecke).
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
    if (istUml13(doc)) return xmi13ToDb(doc);
    var wurzel = doc.documentElement;
    if (!wurzel || lokal(wurzel.nodeName) !== 'XMI') fail('Wurzel ist kein <xmi:XMI>');
    var model = kind(wurzel, 'Model');
    if (!model) {
      var alleM = doc.getElementsByTagName('*'), mi;
      for (mi = 0; mi < alleM.length; mi++) {
        if (lokal(alleM[mi].nodeName) === 'Model') { model = alleM[mi]; break; }
      }
    }
    if (!model) {
      /* Aeltere Exporte (UML 1.x) fuehren kein packagedElement: zweiter Versuch. */
      try { return xmi13ToDb(doc); } catch (e13) { /* unten laut melden */ }
      fail('kein <uml:Model> im Dokument (weder UML 2.x noch UML 1.3 erkannt)');
    }

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
      if (!quelle) {
        var qa = attr(el, 'client') || attr(el, 'specific') || attr(el, 'child');
        if (qa) quelle = { __direkt: qa };
      }
      if (!ziel) {
        var za = attr(el, 'supplier') || attr(el, 'general') || attr(el, 'parent');
        if (za) ziel = { __direkt: za };
      }
      if (!quelle && !ziel && typ === 'Association') {
        var enden21 = kinder(el, 'ownedEnd'), rr21 = [], ee21;
        for (ee21 = 0; ee21 < enden21.length; ee21++) {
          var tt21 = attr(enden21[ee21], 'type');
          if (tt21 && rr21.indexOf(tt21) < 0) rr21.push(tt21);
        }
        if (rr21.length >= 2) { quelle = { __direkt: rr21[0] }; ziel = { __direkt: rr21[1] }; }
      }

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
        var q = quelle ? (quelle.__direkt || attr(quelle, 'xmi:idref', 'idref')) : '';
        var z = ziel ? (ziel.__direkt || attr(ziel, 'xmi:idref', 'idref')) : '';
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

      /* UML 2.x: <generalization general="…"/> steht im Element selbst. */
      var genKinder = kinder(el, 'generalization'), gk;
      for (gk = 0; gk < genKinder.length; gk++) {
        var zielG = attr(genKinder[gk], 'general');
        if (!zielG) continue;
        cid++;
        cons.push({
          Connector_ID: cid, Name: '', Stereotype: '', Connector_Type: 'Generalization',
          Type: 'Generalization', Direction: '', Notes: '',
          Start_Object_ID: 0, End_Object_ID: 0, ea_guid: attr(genKinder[gk], 'xmi:id', 'id') || '',
          __q: guid, __z: zielG
        });
      }
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
      delete c.__q; delete c.__z;
      if (!a || !b) { c.__ungueltig = true; continue; }
      c.Start_Object_ID = a.id; c.End_Object_ID = b.id;
    }

    cons = cons.filter(function (x) { return !x.__ungueltig; });

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

    var db21 = makeDb({ t_package: pkgs, t_object: objs, t_connector: cons, t_objectproperties: tags, t_diagram: diags, t_diagramobjects: dObjs, t_diagramlinks: dLinks, x_technology: tech });
    db21.__x.format = 'XMI ' + (attr(doc.documentElement, 'xmi:version') || attr(doc.documentElement, 'xmi.version') || '2.x') + ' / UML 2.x';
    return db21;
  }

/* ================= XMI -> Zeilen (UML 1.3 / XMI 1.1) =================
 *
 * Sparx EA exportiert "XMI 1.1 (UML 1.3)" ohne xmi:type: die Metaklasse
 * steht im Elementnamen (UML:Class, UML:Package …), Container sind
 * <UML:Namespace.ownedElement>, Beziehungen tragen ihre Enden als
 * Attribute (child/parent) oder als <UML:Dependency.client>-Block.
 * Sichten liegen als <UML:Diagram> mit <UML:DiagramElement geometry=…
 * subject=…> vor. Der Zweig liest genau das und liefert dieselben Zeilen
 * wie der QEA-Reader, damit buildModel() unveraendert bleibt.
 */

var UML13_PKG = { Model: 1, Package: 1, Subsystem: 1, Profile: 1 };
var UML13_OBJ = {
  Class: 'Class', Interface: 'Interface', DataType: 'DataType', PrimitiveType: 'DataType',
  Enumeration: 'Enumeration', Actor: 'Actor', UseCase: 'UseCase', Component: 'Component',
  Node: 'Node', Artifact: 'Artifact', Object: 'Object', Signal: 'Signal', Exception: 'Class',
  Activity: 'Activity', StateMachine: 'StateMachine', State: 'State', ActionState: 'State',
  AssociationClass: 'Class', Collaboration: 'Collaboration'
};
var UML13_REL = {
  Association: 'Association', Generalization: 'Generalization', Dependency: 'Dependency',
  Realization: 'Realization', Abstraction: 'Abstraction', Usage: 'Dependency',
  Include: 'Dependency', Extend: 'Dependency'
};
var UML13_META = (function () {
  var m = {}, k;
  for (k in UML13_PKG) m[k] = 1;
  for (k in UML13_OBJ) m[k] = 1;
  for (k in UML13_REL) m[k] = 1;
  return m;
})();

function istUml13(doc) {
  var alle = doc.getElementsByTagName('*'), i, owned = false, packed = false, praefix = false;
  for (i = 0; i < alle.length; i++) {
    var ln = lokal(alle[i].nodeName);
    if (ln === 'Namespace.ownedElement') owned = true;
    else if (ln === 'packagedElement') packed = true;
    if (String(alle[i].nodeName).indexOf('UML:') === 0) praefix = true;
  }
  return !packed && (owned || praefix);
}

function xmi13ToDb(doc) {
  var pkgs = [], objs = [], cons = [], tags = [], diags = [], dObjs = [], dLinks = [];
  var pkgByPath = {}, byGuid = {}, stereo = {};
  var pid = 0, oid = 0, cid = 0, tid = 0;
  var offeneKanten = [];
  var alle = doc.getElementsByTagName('*'), i;

  /* Stereotyp-Namen zuerst: sie werden an Elementen nur referenziert. */
  for (i = 0; i < alle.length; i++) {
    if (lokal(alle[i].nodeName) !== 'Stereotype') continue;
    var sid = attr(alle[i], 'xmi.id', 'xmi:id', 'id');
    if (sid) stereo[sid] = attr(alle[i], 'name') || text(alle[i]).replace(/\s+/g, ' ').trim();
  }

  function stereotypeVon(el) {
    var block = kind(el, 'ModelElement.stereotype');
    if (block) {
      var s = kind(block, 'Stereotype');
      if (s) {
        var ref = attr(s, 'xmi.idref', 'idref', 'href');
        if (ref && stereo[ref]) return stereo[ref];
        var nm = attr(s, 'name');
        if (nm) return nm;
      }
    }
    return attr(el, 'stereotype');
  }

  function notizVon(el) {
    var blk = kind(el, 'ModelElement.comment');
    if (blk) {
      var c = kind(blk, 'Comment');
      if (c) return attr(c, 'body') || text(c).trim();
    }
    return '';
  }

  function tagsVon(el, objId) {
    var blk = kind(el, 'ModelElement.taggedValue');
    if (!blk) return;
    var tv = kinder(blk, 'TaggedValue'), t;
    for (t = 0; t < tv.length; t++) {
      var name = attr(tv[t], 'tag', 'name');
      if (!name) continue;
      tid++;
      tags.push({
        PropertyID: tid, Object_ID: objId, Property: name,
        Value: attr(tv[t], 'value'), Notes: null, ea_guid: ''
      });
    }
  }

  /* Modellkinder: durch Container hindurch, aber nicht in Klassifikatoren hinein. */
  function sammleKinder(el, out) {
    var c = el && el.firstChild;
    for (; c; c = c.nextSibling) {
      if (c.nodeType !== 1) continue;
      var ln = lokal(c.nodeName);
      if (ln === 'Namespace.ownedElement' || ln === 'ownedElement' || ln === 'packagedElement') {
        sammleKinder(c, out);
      } else if (UML13_META[ln]) {
        out.push(c);
      }
    }
    return out;
  }

  function pfadFuer(elternPfad, name) {
    var pfad = elternPfad ? elternPfad + '/' + name : name;
    var kandidat = pfad, z = 2;
    while (pkgByPath[kandidat]) { kandidat = pfad + '#' + z; z++; }
    return kandidat;
  }

  function liest(el, elternId, elternPfad) {
    var typ = lokal(el.nodeName);
    var name = attr(el, 'name');
    var guid = attr(el, 'xmi.id', 'xmi:id', 'id');

    if (UML13_PKG[typ]) {
      var pfad = pfadFuer(elternPfad, name || ('Paket' + (pid + 1)));
      pid++;
      pkgs.push({
        Package_ID: pid, Name: name, Parent_ID: elternId || 0, TPos: pkgs.length,
        Notes: notizVon(el), Stereotype: stereotypeVon(el), ea_guid: guid || '', x_path: pfad
      });
      pkgByPath[pfad] = pid;
      if (guid) byGuid[guid] = { art: 'paket', id: pid };
      var unter = sammleKinder(el, []), u;
      for (u = 0; u < unter.length; u++) liest(unter[u], pid, pfad);
      return;
    }

    if (UML13_REL[typ]) {
      var q = attr(el, 'child', 'client', 'dependent');
      var z = attr(el, 'parent', 'supplier', 'independent');
      if (!q && !z) {
        var cb = kind(el, 'Dependency.client') || kind(el, 'GeneralizableElement.generalization');
        var sb = kind(el, 'Dependency.supplier');
        if (cb) { var cq = erstesElement(cb); q = cq ? attr(cq, 'xmi.idref', 'idref') : ''; }
        if (sb) { var cz = erstesElement(sb); z = cz ? attr(cz, 'xmi.idref', 'idref') : ''; }
      }
      if (typ === 'Association') {
        var verb = kind(el, 'Association.connection');
        var enden = verb ? kinder(verb, 'AssociationEnd') : [];
        var refs = [], e;
        for (e = 0; e < enden.length; e++) {
          var tr = attr(enden[e], 'type');
          if (tr && refs.indexOf(tr) < 0) refs.push(tr);
        }
        if (refs.length >= 2) { q = refs[0]; z = refs[1]; }
        else if (refs.length === 1) { q = refs[0]; z = refs[0]; }
      }
      cid++;
      var c = {
        Connector_ID: cid, Name: name || '', Stereotype: stereotypeVon(el),
        Connector_Type: UML13_REL[typ], Type: UML13_REL[typ],
        Direction: attr(el, 'direction'), Notes: notizVon(el),
        Start_Object_ID: 0, End_Object_ID: 0, ea_guid: guid || '', __q: q, __z: z
      };
      cons.push(c);
      if (guid) byGuid[guid] = { art: 'beziehung', id: cid };
      offeneKanten.push(c);
      return;
    }

    /* Element */
    oid++;
    objs.push({
      Object_ID: oid, Name: name || ('Element ' + oid), Package_ID: elternId || 0, ParentID: 0,
      Object_Type: UML13_OBJ[typ] || 'Class', Stereotype: stereotypeVon(el),
      Notes: notizVon(el), Alias: attr(el, 'alias'), Status: attr(el, 'status'),
      Hidden: 0, ea_guid: guid || ''
    });
    if (guid) byGuid[guid] = { art: 'element', id: oid };
    tagsVon(el, oid);
  }

  /* Start: Modell im XMI.content */
  var model = null;
  for (i = 0; i < alle.length; i++) {
    if (lokal(alle[i].nodeName) === 'Model') { model = alle[i]; break; }
  }
  if (!model) fail('kein <UML:Model> im Dokument');
  var oben = sammleKinder(model, []), o;
  for (o = 0; o < oben.length; o++) liest(oben[o], 0, '');

  /* Endpunkte aufloesen */
  var gueltig = [];
  for (i = 0; i < offeneKanten.length; i++) {
    var k = offeneKanten[i];
    var a = byGuid[k.__q], b = byGuid[k.__z];
    delete k.__q; delete k.__z;
    if (!a || !b) continue;   // Verweis ohne eigenstaendige Beziehung
    k.Start_Object_ID = a.id; k.End_Object_ID = b.id;
    gueltig.push(k);
  }
  cons = gueltig;

  /* Sichten: <UML:Diagram> mit <UML:DiagramElement geometry subject> */
  for (i = 0; i < alle.length; i++) {
    var de = alle[i];
    if (String(lokal(de.nodeName)).toLowerCase() !== 'diagram') continue;
    var dn = attr(de, 'name');
    if (!dn) continue;
    var dId = diags.length + 1;
    diags.push({
      Diagram_ID: dId, Name: dn, Diagram_Type: attr(de, 'diagramType', 'type') || 'Custom',
      Package_ID: 0, Notes: notizVon(de), TPos: diags.length,
      ea_guid: attr(de, 'xmi.id', 'xmi:id', 'id') || ''
    });
    var blockE = kind(de, 'Diagram.element');
    var teile = blockE ? kinder(blockE, 'DiagramElement') : [];
    var t, seq = 0;
    for (t = 0; t < teile.length; t++) {
      var subj = attr(teile[t], 'subject');
      if (!subj) continue;
      var ziel = byGuid[subj];
      if (!ziel || ziel.art !== 'element') continue;
      var geo = attr(teile[t], 'geometry');
      dObjs.push({
        DiagramID: dId, ObjectID: ziel.id,
        RectLeft: zahlAus(geo, 'Left'), RectTop: zahlAus(geo, 'Top'),
        RectRight: zahlAus(geo, 'Right'), RectBottom: zahlAus(geo, 'Bottom'),
        Sequence: seq++, Hidden: 0, x_path: ''
      });
    }

    /* Umbrello: <widgets><classwidget x y width height xmi.id=…/> */
    var widgets = [];
    (function sammleWidgets(el) {
      var w = el && el.firstChild;
      for (; w; w = w.nextSibling) {
        if (w.nodeType !== 1) continue;
        if (/widget$/i.test(lokal(w.nodeName))) widgets.push(w);
        sammleWidgets(w);
      }
    })(de);
    for (t = 0; t < widgets.length; t++) {
      var wid = attr(widgets[t], 'xmi.id', 'xmi:id', 'subject');
      var wz = wid ? byGuid[wid] : null;
      if (!wz || wz.art !== 'element') continue;
      var wx = parseFloat(attr(widgets[t], 'x')) || 0;
      var wy = parseFloat(attr(widgets[t], 'y')) || 0;
      var ww = parseFloat(attr(widgets[t], 'width')) || 0;
      var wh = parseFloat(attr(widgets[t], 'height')) || 0;
      dObjs.push({
        DiagramID: dId, ObjectID: wz.id,
        RectLeft: Math.round(wx), RectTop: -Math.round(wy),
        RectRight: Math.round(wx + ww), RectBottom: -Math.round(wy + wh),
        Sequence: seq++, Hidden: 0, x_path: ''
      });
    }
  }

  /* Sichten ohne Kantenliste: Beziehungen zeigen, deren Enden aufliegen. */
  for (i = 0; i < diags.length; i++) {
    var did = diags[i].Diagram_ID, aufSicht = {}, j, hat = false;
    for (j = 0; j < dObjs.length; j++) if (dObjs[j].DiagramID === did) aufSicht[dObjs[j].ObjectID] = true;
    for (j = 0; j < cons.length; j++) {
      if (aufSicht[cons[j].Start_Object_ID] && aufSicht[cons[j].End_Object_ID]) {
        dLinks.push({ DiagramID: did, ConnectorID: cons[j].Connector_ID, Hidden: 0 });
        hat = true;
      }
    }
    if (!hat) { /* Sicht ohne Beziehungen ist zulaessig */ }
  }

  /* Elemente ohne Paket (flache Exporte) bekommen ein Wurzelpaket mit dem
     Modellnamen, sonst zeigt der Explorer sie nirgends an. */
  var hatWaisen = false, wi;
  for (wi = 0; wi < objs.length; wi++) if (!objs[wi].Package_ID) { hatWaisen = true; break; }
  if (hatWaisen) {
    pid++;
    var wurzelName = attr(model, 'name') || 'Modell';
    pkgs.unshift({
      Package_ID: pid, Name: wurzelName, Parent_ID: 0, TPos: -1,
      Notes: '', Stereotype: '', ea_guid: attr(model, 'xmi.id', 'xmi:id', 'id') || '',
      x_path: wurzelName
    });
    for (wi = 0; wi < objs.length; wi++) if (!objs[wi].Package_ID) objs[wi].Package_ID = pid;
  }

  var db13 = makeDb({
    t_package: pkgs, t_object: objs, t_connector: cons, t_objectproperties: tags,
    t_diagram: diags, t_diagramobjects: dObjs, t_diagramlinks: dLinks,
    x_technology: ''
  });
  var v13 = attr(doc.documentElement, 'xmi.version') || '1.1';
  db13.__x.format = 'XMI ' + v13 + ' / UML 1.3';
  return db13;
}

function erstesElement(el) {
  var c = el && el.firstChild;
  for (; c; c = c.nextSibling) if (c.nodeType === 1) return c;
  return null;
}

function zahlAus(text, schluessel) {
  var m = new RegExp(schluessel + '=(-?\\d+)', 'i').exec(String(text || ''));
  return m ? parseInt(m[1], 10) : 0;
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
        Hidden: 0, ea_guid: String(n.ea_guid || props.ea_guid || ''), x_origin: props.origin != null ? String(props.origin) : '',
        x_xrefs: ''
      };
      objs.push(o);
      idMap[n.id] = { art: 'element', id: oid };
      for (var k in props) {
        if (!Object.prototype.hasOwnProperty.call(props, k)) continue;
        if (k === 'notes' || k === 'alias' || k === 'status' || k === 'origin' || k === 'ea_guid') continue;
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
        Start_Object_ID: a.id, End_Object_ID: b.id, ea_guid: String(ed.ea_guid || ep.ea_guid || ''), x_tags: ''
      });
    }

    var diags = [], dobjs = [], dlinks = [];
    if (Array.isArray(daten.diagrams)) {
      for (var dxi = 0; dxi < daten.diagrams.length; dxi++) {
        var dg = daten.diagrams[dxi];
        var dId = dxi + 1;
        var pIdD = sichertPfad(String(dg.package || ''));
        diags.push({
          Diagram_ID: dId,
          Package_ID: pIdD || (pkgs.length ? pkgs[0].Package_ID : 1),
          Name: String(dg.name || ('Diagramm ' + dId)),
          Diagram_Type: String(dg.type || 'Custom'),
          Notes: String(dg.notes || ''),
          ea_guid: String(dg.ea_guid || ''),
          x_path: String(dg.package || ''),
          x_stereotype: String(dg.stereotype || ''),
          x_parent: '',
          x_default: dxi === 0 ? 1 : 0,
          x_viewpoint: ''
        });
        if (Array.isArray(dg.elements)) {
          for (var dei = 0; dei < dg.elements.length; dei++) {
            var del = dg.elements[dei];
            var matchO = objs.filter(function (x) {
              return (del.ea_guid && x.ea_guid && x.ea_guid === del.ea_guid) || (x.Name === del.name);
            })[0];
            if (matchO) {
              dobjs.push({
                DiagramID: dId,
                ObjectID: matchO.Object_ID,
                RectLeft: del.left || 0,
                RectTop: del.top || 0,
                RectRight: del.right || 0,
                RectBottom: del.bottom || 0,
                Sequence: dei + 1
              });
            }
          }
        }
      }
    }

    var meta = daten.metadata || {};
    return makeDb({ t_package: pkgs, t_object: objs, t_connector: cons, t_objectproperties: tags, t_diagram: diags, t_diagramobjects: dobjs, t_diagramlinks: dlinks, x_technology: String(meta.standard || '') });
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
      if (o.x_origin) props.origin = String(o.x_origin);
      if (o.ea_guid) {
        props.ea_guid = String(o.ea_guid);
      }
      var knoten = {
        id: nid2, name: String(o.Name || ''), metaclass: String(o.Object_Type || 'Class'),
        labels: [String(o.Stereotype || o.Object_Type || 'Class')], package: pfadVon2(pkgs.filter(function (x) { return Number(x.Package_ID) === Number(o.Package_ID); })[0])
      };
      if (o.ea_guid) knoten.ea_guid = String(o.ea_guid);
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
      if (c.ea_guid) e.ea_guid = String(c.ea_guid);
      if (c.Name) e.name = String(c.Name);
      var eProps = {};
      if (c.ea_guid) eProps.ea_guid = String(c.ea_guid);
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

    var diagsOut = [];
    var dRows = rowsOf(db, 't_diagram');
    var doRows = rowsOf(db, 't_diagramobjects');
    for (i = 0; i < dRows.length; i++) {
      var d = dRows[i];
      var pObj = pkgs.filter(function (x) { return Number(x.Package_ID) === Number(d.Package_ID); })[0];
      var dObj = {
        name: String(d.Name || ''),
        package: String(d.x_path || pfadVon2(pObj) || ''),
        type: String(d.Diagram_Type || 'Custom'),
        ea_guid: String(d.ea_guid || ''),
        elements: []
      };
      for (j = 0; j < doRows.length; j++) {
        if (Number(doRows[j].DiagramID) === Number(d.Diagram_ID)) {
          var oMember = objs.filter(function (x) { return Number(x.Object_ID) === Number(doRows[j].ObjectID); })[0];
          if (oMember && !istSpiegel(oMember)) {
            var oPkg = pkgs.filter(function (x) { return Number(x.Package_ID) === Number(oMember.Package_ID); })[0];
            dObj.elements.push({
              name: String(oMember.Name || ''),
              package: pfadVon2(oPkg),
              ea_guid: String(oMember.ea_guid || ''),
              left: doRows[j].RectLeft || 0,
              top: doRows[j].RectTop || 0,
              right: doRows[j].RectRight || 0,
              bottom: doRows[j].RectBottom || 0
            });
          }
        }
      }
      diagsOut.push(dObj);
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
    if (diagsOut.length) daten.diagrams = diagsOut;
    return JSON.stringify(daten, null, 2) + '\n';
  }

  /* ================= ArchiMate 3.2 Exchange Format ================= */

  var ARCHIMATE_ELEMENT_MAP = {
    Capability: 'Capability', FieldedCapability: 'Capability', CapabilityConfiguration: 'Grouping',
    CapabilityRole: 'BusinessRole', EnterpriseGoal: 'Goal', EnterpriseVision: 'Goal',
    HighLevelOperationalConcept: 'BusinessObject', EnduringTask: 'Capability', ActualEnduringTask: 'Capability',
    StrategicConstraint: 'Requirement', OperationalConstraint: 'Requirement', ResourceConstraint: 'Requirement',
    Constraint: 'Requirement', ServicePolicy: 'Requirement', Principle: 'Principle', Driver: 'Driver',
    Goal: 'Goal', Outcome: 'Outcome', Value: 'Value', CourseOfAction: 'CourseOfAction',
    OperationalPerformer: 'BusinessActor', OperationalRole: 'BusinessRole', OperationalActivity: 'BusinessProcess',
    OperationalActivityAction: 'BusinessProcess', StandardOperationalActivity: 'BusinessProcess',
    OperationalArchitecture: 'Grouping', OperationalStateDescription: 'Grouping', Organization: 'BusinessActor',
    ActualOrganization: 'BusinessActor', Post: 'BusinessRole', ActualPost: 'BusinessRole',
    ActualPerson: 'BusinessActor', Location: 'Location', ActualLocation: 'Location', Environment: 'Grouping',
    ActualEnvironment: 'Grouping', WholeLifeEnterprise: 'Grouping', WholeLifeConfiguration: 'Grouping',
    System: 'ApplicationComponent', Subsystem: 'ApplicationComponent', Software: 'ApplicationComponent',
    Application: 'ApplicationComponent', Service: 'ApplicationService', ServiceSpecification: 'ApplicationService',
    Interface: 'ApplicationInterface', Node: 'Node', Device: 'Device', Artifact: 'Artifact',
    DataObject: 'DataObject', InformationElement: 'DataObject', Document: 'Representation',
    BusinessProcess: 'BusinessProcess'
  };

  var ARCHIMATE_RELATION_MAP = {
    Composition: 'Composition', Aggregation: 'Aggregation', Assignment: 'Assignment',
    Realization: 'Realization', Serving: 'Serving', Access: 'Access', Influence: 'Influence',
    Triggering: 'Triggering', Flow: 'Flow', Specialization: 'Specialization', Association: 'Association',
    OperationalExchange: 'Flow', OperationalControlFlow: 'Triggering', OperationalMessageFlow: 'Flow',
    ResourceExchange: 'Flow', Dependency: 'Association'
  };

  function dbToArchimate(db, opts) {
    opts = opts || {};
    var pkgs = rowsOf(db, 't_package'), objs = rowsOf(db, 't_object'), cons = rowsOf(db, 't_connector');
    var tags = rowsOf(db, 't_objectproperties');
    var diags = rowsOf(db, 't_diagram'), dobjs = rowsOf(db, 't_diagramobjects');
    var mName = opts.modelName || 'Modell';
    var mGuid = 'id-' + fnv1a(mName);

    var lines = [];
    lines.push('<?xml version="1.0" encoding="UTF-8"?>');
    lines.push('<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/"');
    lines.push('       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"');
    lines.push('       xsi:schemaLocation="http://www.opengroup.org/xsd/archimate/3.0/ http://www.opengroup.org/xsd/archimate/3.0/archimate3_Diagram.xsd"');
    lines.push('       identifier="' + mGuid + '">');
    lines.push('  <name>' + esc(mName) + '</name>');

    var propNames = ['ADMBw_Stereotyp', 'ADMBw_Metaklasse', 'Sparx_EA_GUID', 'Paketpfad'];
    var tagsByObj = {};
    for (var ti = 0; ti < tags.length; ti++) {
      var t = tags[ti];
      var ok = t.Object_ID != null ? t.Object_ID : t.ObjectID;
      if (ok == null) continue;
      if (!tagsByObj[ok]) tagsByObj[ok] = [];
      var pName = String(t.Property || '');
      tagsByObj[ok].push({ name: pName, value: String(t.Value == null ? '' : t.Value) });
      if (propNames.indexOf(pName) === -1) propNames.push(pName);
    }

    var propDefId = {};
    lines.push('  <propertyDefinitions>');
    for (var pi = 0; pi < propNames.length; pi++) {
      var pId = 'propref-' + (pi + 1);
      propDefId[propNames[pi]] = pId;
      lines.push('    <propertyDefinition identifier="' + pId + '" type="string">');
      lines.push('      <name>' + esc(propNames[pi]) + '</name>');
      lines.push('    </propertyDefinition>');
    }
    lines.push('  </propertyDefinitions>');

    lines.push('  <elements>');
    var allePfade = pfadeBauen(pkgs);
    var elemGuidMap = {};
    for (var oi = 0; oi < objs.length; oi++) {
      var o = objs[oi];
      if (istSpiegel(o)) continue;
      var st = String(o.Stereotype || '');
      var archType = ARCHIMATE_ELEMENT_MAP[st] || 'ApplicationComponent';
      var oGuid = o.ea_guid ? String(o.ea_guid) : ('id-' + fnv1a(o.Name + '|' + st + '|' + o.Object_ID));
      elemGuidMap[o.Object_ID] = oGuid;
      var pkgPath = allePfade[o.Package_ID] || '';

      lines.push('    <element identifier="' + oGuid + '" xsi:type="' + archType + '">');
      lines.push('      <name>' + esc(o.Name || '') + '</name>');
      if (o.Notes) lines.push('      <documentation>' + esc(o.Notes) + '</documentation>');
      lines.push('      <properties>');
      if (st) lines.push('        <property propertyDefinitionRef="' + propDefId['ADMBw_Stereotyp'] + '"><value>' + esc(st) + '</value></property>');
      if (o.Object_Type) lines.push('        <property propertyDefinitionRef="' + propDefId['ADMBw_Metaklasse'] + '"><value>' + esc(o.Object_Type) + '</value></property>');
      if (o.ea_guid) lines.push('        <property propertyDefinitionRef="' + propDefId['Sparx_EA_GUID'] + '"><value>' + esc(o.ea_guid) + '</value></property>');
      if (pkgPath) lines.push('        <property propertyDefinitionRef="' + propDefId['Paketpfad'] + '"><value>' + esc(pkgPath) + '</value></property>');
      var oTags = tagsByObj[o.Object_ID] || [];
      for (var oti = 0; oti < oTags.length; oti++) {
        var pdId = propDefId[oTags[oti].name];
        if (pdId) lines.push('        <property propertyDefinitionRef="' + pdId + '"><value>' + esc(oTags[oti].value) + '</value></property>');
      }
      lines.push('      </properties>');
      lines.push('    </element>');
    }
    lines.push('  </elements>');

    lines.push('  <relationships>');
    for (var ci = 0; ci < cons.length; ci++) {
      var c = cons[ci];
      var cSt = String(c.Stereotype || c.Connector_Type || 'Association');
      var archRel = ARCHIMATE_RELATION_MAP[cSt] || 'Association';
      var srcGuid = elemGuidMap[c.Start_Object_ID];
      var tgtGuid = elemGuidMap[c.End_Object_ID];
      if (!srcGuid || !tgtGuid) continue;
      var cGuid = c.ea_guid ? String(c.ea_guid) : ('rel-' + fnv1a(c.Name + '|' + cSt + '|' + c.Connector_ID));
      lines.push('    <relationship identifier="' + cGuid + '" xsi:type="' + archRel + '" source="' + srcGuid + '" target="' + tgtGuid + '">');
      if (c.Name) lines.push('      <name>' + esc(c.Name) + '</name>');
      if (c.Notes) lines.push('      <documentation>' + esc(c.Notes) + '</documentation>');
      lines.push('    </relationship>');
    }
    lines.push('  </relationships>');

    lines.push('  <organizations>');
    for (var pki = 0; pki < pkgs.length; pki++) {
      var pk = pkgs[pki];
      lines.push('    <item>');
      lines.push('      <label>' + esc(pk.Name || '') + '</label>');
      for (var eoi = 0; eoi < objs.length; eoi++) {
        if (Number(objs[eoi].Package_ID) === Number(pk.Package_ID) && !istSpiegel(objs[eoi])) {
          var eg = elemGuidMap[objs[eoi].Object_ID];
          if (eg) lines.push('      <item identifierRef="' + eg + '"/>');
        }
      }
      lines.push('    </item>');
    }
    lines.push('  </organizations>');

    if (diags.length) {
      lines.push('  <views>');
      lines.push('    <diagrams>');
      for (var di = 0; di < diags.length; di++) {
        var d = diags[di];
        var dGuid = d.ea_guid ? String(d.ea_guid) : ('view-' + fnv1a(d.Name + '|' + d.Diagram_ID));
        lines.push('      <view identifier="' + dGuid + '">');
        lines.push('        <name>' + esc(d.Name || '') + '</name>');
        var dMembers = dobjs.filter(function (x) { return Number(x.DiagramID) === Number(d.Diagram_ID); });
        for (var dmi = 0; dmi < dMembers.length; dmi++) {
          var dm = dMembers[dmi];
          var elGuid = elemGuidMap[dm.ObjectID];
          if (!elGuid) continue;
          var nGuid = 'node-' + fnv1a(dGuid + '|' + elGuid);
          var x = dm.RectLeft || 0;
          var y = dm.RectTop ? Math.abs(dm.RectTop) : 0;
          var w = (dm.RectRight && dm.RectLeft) ? Math.abs(dm.RectRight - dm.RectLeft) : 120;
          var h = (dm.RectBottom && dm.RectTop) ? Math.abs(dm.RectBottom - dm.RectTop) : 80;
          lines.push('        <node identifier="' + nGuid + '" elementRef="' + elGuid + '" x="' + x + '" y="' + y + '" w="' + w + '" h="' + h + '"/>');
        }
        lines.push('      </view>');
      }
      lines.push('    </diagrams>');
      lines.push('  </views>');
    }

    lines.push('</model>');
    return lines.join('\n') + '\n';
  }

  function archimateToDb(xmlText) {
    if (typeof DOMParser === 'undefined') fail('DOMParser fehlt in dieser Umgebung');
    var doc = new DOMParser().parseFromString(String(xmlText || ''), 'application/xml');
    var parserErr = doc.getElementsByTagName('parsererror')[0];
    if (parserErr) fail('ArchiMate-XML fehlerhaft: ' + parserErr.textContent);

    var root = doc.documentElement;
    var modelName = '';
    var nameEl = kind(root, 'name');
    if (nameEl) modelName = text(nameEl);

    var propDefs = {};
    var pdefEls = root.getElementsByTagName('propertyDefinition');
    for (var pdi = 0; pdi < pdefEls.length; pdi++) {
      var pEl = pdefEls[pdi];
      var pid = attr(pEl, 'identifier');
      var pnEl = kind(pEl, 'name');
      var pname = pnEl ? text(pnEl) : pid;
      if (pid) propDefs[pid] = pname;
    }

    var pkgs = [], objs = [], cons = [], tags = [], diags = [], dobjs = [];
    var pid = 0, oid = 0, cid = 0, tid = 0, did = 0;
    var elemIdToOid = {};
    var pkgPathMap = {};

    function sichertPaket(pfad) {
      if (!pfad) return 0;
      if (pkgPathMap[pfad]) return pkgPathMap[pfad];
      var teile = pfad.split('/'), bisher = '', id = 0;
      for (var i = 0; i < teile.length; i++) {
        bisher = bisher ? bisher + '/' + teile[i] : teile[i];
        if (!pkgPathMap[bisher]) {
          pid++;
          pkgs.push({ Package_ID: pid, Name: teile[i], Parent_ID: id, TPos: pkgs.length, Notes: '', Stereotype: '', ea_guid: '', x_path: bisher, x_tags: '' });
          pkgPathMap[bisher] = pid;
        }
        id = pkgPathMap[bisher];
      }
      return pkgPathMap[pfad];
    }

    var orgEls = root.getElementsByTagName('item');
    var elemToPkg = {};
    for (var oi = 0; oi < orgEls.length; oi++) {
      var itemEl = orgEls[oi];
      var lblEl = kind(itemEl, 'label');
      if (lblEl) {
        var pName = text(lblEl);
        var subItems = itemEl.getElementsByTagName('item');
        for (var si = 0; si < subItems.length; si++) {
          var idRef = attr(subItems[si], 'identifierRef');
          if (idRef) elemToPkg[idRef] = pName;
        }
      }
    }

    var elemEls = root.getElementsByTagName('element');
    var admbwCount = 0;
    for (var ei = 0; ei < elemEls.length; ei++) {
      var el = elemEls[ei];
      var eId = attr(el, 'identifier');
      var xsiType = attr(el, 'xsi:type', 'type') || 'ApplicationComponent';
      if (xsiType.indexOf(':') !== -1) xsiType = xsiType.split(':').pop();

      var ename = '';
      var enEl = kind(el, 'name');
      if (enEl) ename = text(enEl);

      var edoc = '';
      var edEl = kind(el, 'documentation');
      if (edEl) edoc = text(edEl);

      var pList = el.getElementsByTagName('property');
      var eProps = {};
      for (var pri = 0; pri < pList.length; pri++) {
        var pr = pList[pri];
        var prRef = attr(pr, 'propertyDefinitionRef');
        var pDefName = propDefs[prRef] || prRef;
        var valEl = kind(pr, 'value');
        var val = valEl ? text(valEl) : '';
        if (pDefName) eProps[pDefName] = val;
      }

      if (eProps['ADMBw_Stereotyp'] || eProps['prop-admbw-stereotype']) admbwCount++;
      var st = eProps['ADMBw_Stereotyp'] || eProps['prop-admbw-stereotype'] || xsiType;
      var eaType = eProps['ADMBw_Metaklasse'] || eProps['prop-admbw-metatype'] || 'Class';
      var eaGuid = eProps['Sparx_EA_GUID'] || eProps['prop-ea-guid'] || (eId && eId.indexOf('-') !== -1 ? eId : '');
      var pkgPath = eProps['Paketpfad'] || eProps['prop-paketpfad'] || elemToPkg[eId] || 'Architektur';

      oid++;
      elemIdToOid[eId] = oid;
      var pkgId = sichertPaket(pkgPath);

      objs.push({
        Object_ID: oid, Name: ename, Package_ID: pkgId, ParentID: 0,
        Object_Type: eaType, Stereotype: st, Notes: edoc, Alias: '', Status: 'Proposed',
        Hidden: 0, ea_guid: eaGuid, x_origin: '', x_xrefs: ''
      });

      for (var k in eProps) {
        if (!Object.prototype.hasOwnProperty.call(eProps, k)) continue;
        if (k === 'ADMBw_Stereotyp' || k === 'ADMBw_Metaklasse' || k === 'Sparx_EA_GUID' || k === 'Paketpfad' ||
            k === 'prop-admbw-stereotype' || k === 'prop-admbw-metatype' || k === 'prop-ea-guid' || k === 'prop-paketpfad') continue;
        tid++;
        tags.push({ PropertyID: tid, Object_ID: oid, Property: k, Value: eProps[k], Notes: null, ea_guid: '' });
      }
    }

    var relEls = root.getElementsByTagName('relationship');
    for (var ri = 0; ri < relEls.length; ri++) {
      var rel = relEls[ri];
      var relId = attr(rel, 'identifier');
      var rType = attr(rel, 'xsi:type', 'type') || 'Association';
      if (rType.indexOf(':') !== -1) rType = rType.split(':').pop();

      var srcRef = attr(rel, 'source');
      var tgtRef = attr(rel, 'target');
      var srcOid = elemIdToOid[srcRef];
      var tgtOid = elemIdToOid[tgtRef];
      if (!srcOid || !tgtOid) continue;

      var rname = '';
      var rnEl = kind(rel, 'name');
      if (rnEl) rname = text(rnEl);

      var rdoc = '';
      var rdEl = kind(rel, 'documentation');
      if (rdEl) rdoc = text(rdEl);

      cid++;
      cons.push({
        Connector_ID: cid, Name: rname, Stereotype: rType, Connector_Type: 'Dependency',
        Type: 'Dependency', Direction: 'Source -> Destination', Notes: rdoc,
        Start_Object_ID: srcOid, End_Object_ID: tgtOid, ea_guid: relId || '', x_tags: ''
      });
    }

    var viewEls = root.getElementsByTagName('view');
    for (var vi = 0; vi < viewEls.length; vi++) {
      var vw = viewEls[vi];
      var vName = '';
      var vnEl = kind(vw, 'name');
      if (vnEl) vName = text(vnEl);

      did++;
      diags.push({
        Diagram_ID: did, Package_ID: pkgs.length ? pkgs[0].Package_ID : 1,
        Name: vName || ('Sicht ' + did), Diagram_Type: 'Custom', Notes: '',
        ea_guid: attr(vw, 'identifier') || '', x_path: pkgs.length ? pkgs[0].x_path : 'Architektur',
        x_stereotype: '', x_parent: '', x_default: vi === 0 ? 1 : 0, x_viewpoint: ''
      });

      var nodeEls = vw.getElementsByTagName('node');
      for (var ni = 0; ni < nodeEls.length; ni++) {
        var nd = nodeEls[ni];
        var elRef = attr(nd, 'elementRef');
        var oRef = elemIdToOid[elRef];
        if (!oRef) continue;
        var nx = parseInt(attr(nd, 'x') || '0', 10);
        var ny = parseInt(attr(nd, 'y') || '0', 10);
        var nw = parseInt(attr(nd, 'w') || '120', 10);
        var nh = parseInt(attr(nd, 'h') || '80', 10);
        dobjs.push({
          DiagramID: did, ObjectID: oRef, RectLeft: nx, RectTop: -ny,
          RectRight: nx + nw, RectBottom: -(ny + nh), Sequence: ni + 1
        });
      }
    }

    var isNativeArchimate = (objs.length > 0 && admbwCount === 0);
    var dbArch = makeDb({
      t_package: pkgs, t_object: objs, t_connector: cons, t_objectproperties: tags,
      t_diagram: diags, t_diagramobjects: dobjs, t_diagramlinks: [],
      x_technology: isNativeArchimate ? 'ArchiMate 3.2' : 'ADMBw (aus ArchiMate Exchange)'
    });
    dbArch.__x.format = isNativeArchimate ? 'ArchiMate 3.2 (nativ)' : 'ArchiMate 3.2 Exchange (NAFv4/UAF-Rückweg)';
    dbArch.__x.nativeArchimate = isNativeArchimate;
    return dbArch;
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
    var kopf = s.slice(0, 800).replace(/^\uFEFF/, '').trim();
    if (kopf.indexOf('<model') >= 0 && (kopf.indexOf('archimate') >= 0 || kopf.indexOf('http://www.opengroup.org') >= 0)) return archimateToDb(s);
    if (kopf.indexOf('<archimate:model') >= 0) return archimateToDb(s);
    if (kopf.charAt(0) === '<' || kopf.indexOf('<xmi:XMI') >= 0 || kopf.indexOf('<uml:Model') >= 0) return xmiToDb(s);
    if (kopf.charAt(0) === '{') return jsonToDb(s);
    fail('Unbekanntes Format in ' + (name || 'Datei') + ': weder SQLite (.qea), noch XMI, noch ArchiMate (.xml), noch JSON-Batch');
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
    archimateToDb: archimateToDb,
    dbToXmi: dbToXmi,
    dbToJson: dbToJson,
    dbToArchimate: dbToArchimate,
    download: download
  };
})(typeof window !== 'undefined' ? window : this);