/* ADMBw QEA Analyzer v4.0 — Teil 1: Kern, Suche, Paket-Explorer, Sichten-Katalog, PNG- & XLSX-Export */
/* global qeaOpen, ADMBW_DATA */

var DB = null, OBJS = {}, CONS = [], PKG = {}, PKG_ROOTS = [], PKG_OPEN = {};
var DIAGS = [], DIAGMAP = {}, DIAGOBJ = {}, DIAGLINK = {}, OBJ_DIAGS = {};
var VPSTAT = {}, TAGS = {}, CONNCOUNT = {};
var CURVP = null, CURPKG = null, CURDIAG = null, CURVIEW = 'explorer', MODELLNAME = '';
var PKG_DEEP = true;
var CURDATA = { els: [], rels: [], diags: [] };
var VPMODE = 'list';
var SEARCH_SCOPE = 'all', GLOBHITS = [];
var DIAG_FILTER = { q: '', pkg: '', layer: 'all' };
var EXPCTX = null, PRINTCTX = '';
/* Mehrfach-Modell-Modus (v6): mehrere QEA-Dateien zu einer Landkarte verschmelzen */
var SINGLE = true;                /* true = Einzelmodell (Rückwärtskompatibilität, z. B. Test-Harness) */
var MULTI_MODE = false;           /* true, wenn der Nutzer den Mehrfach-Modus aktiviert hat */
var MODEL_N = 0;                  /* Zähler geladener Dateien */
var MODEL_FILES = [];             /* je Datei: {n, name, pkg, diag, obj, con} */
var MODEL_KEYMAP = {};            /* Fusion: "name\u0001stereo" -> globale Element-Kennung */
var MODEL_LOCAL2G = {};           /* Fusion: lokale ID -> {g, l} (Umleitung auf vorhandenes Element) */
var MULTI_SRC = {};               /* Fusion: lokale ID -> globale Kennung des Zielelements */
var MODEL_DBS = {};               /* je Datei: {n: DB-Objekt} */
var MODEL_DB = null, MODEL_OBJS = {}, MODEL_PKG = {}, MODEL_DIAGS = [], MODEL_TAGS = {};
var CONNMAP = {};                 /* Nachschlagetabelle: Beziehungs-Kennung -> Beziehung (alle Modelle) */
var PKG_CANDS = [];               /* Kandidaten-IDs der Pakete eines Aufbaus (Umrechnung) */
var ELEMFOCUS = null;             /* Mehrfach-Modus: Fokus auf Vorkommen eines Elements in Modell n */
var MERGE_CANDS = [];             /* offene Zusammenführungs-Vorschläge: {from, to, level} */
var G = {
  vp: null, built: false, baseNodes: [], baseLinks: [], viewNodes: [], viewLinks: [],
  nbr: {}, pos: {}, focus: null, fset: null, vb: null, simTimer: null,
  mode: 'vp', root: null, key: null, hops: 1, capped: false, keepFilters: false,
  layout: 'force', lblMode: 'auto', showEdgeLbl: false,
  f: { q: '', types: {}, rels: {}, only: true, maxN: 120, hops: 0 }
};

/* ---------- Basis-Helfer ---------- */
function el(id) { return document.getElementById(id); }
function decodeEntities(s) {
  s = String(s == null ? '' : s);
  if (s.indexOf('&') < 0) return s;
  var map = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', auml: 'ä', ouml: 'ö', uuml: 'ü', Auml: 'Ä', Ouml: 'Ö', Uuml: 'Ü', szlig: 'ß', ndash: '–', mdash: '—', bull: '•', euro: '€' };
  return s
    .replace(/&#(\d+);/g, function (_, d) { var c = parseInt(d, 10); return c ? String.fromCharCode(c) : ''; })
    .replace(/&#x([0-9a-fA-F]+);/g, function (_, h) { var c = parseInt(h, 16); return c ? String.fromCharCode(c) : ''; })
    .replace(/&([a-zA-Z]+);/g, function (m, k) { return map.hasOwnProperty(k) ? map[k] : m; });
}
function cleanNote(s) {
  s = decodeEntities(String(s == null ? '' : s));
  s = s.replace(/<br\s*\/?>/gi, '\n').replace(/<\/p>/gi, '\n').replace(/<[^>]+>/g, '');
  return decodeEntities(s).replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}
function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function norm(s) { return decodeEntities(String(s == null ? '' : s)).replace(/\s+/g, ' ').trim(); }
function fmt(n) { return String(n || 0).replace(/\B(?=(\d{3})+(?!\d))/g, '.'); }
function diagN(n) { return (Number(n) === 1) ? '1 Sicht' : fmt(n) + ' Sichten'; }
function elN(n) { return (Number(n) === 1) ? '1 Element' : fmt(n) + ' Elemente'; }
function pkgN(n) { return (Number(n) === 1) ? '1 Unterpaket' : fmt(n) + ' Unterpakete'; }
function relN(n) { return (Number(n) === 1) ? '1 Beziehung' : fmt(n) + ' Beziehungen'; }
function pad2(n) { return (n < 10 ? '0' : '') + n; }
function dateStamp() {
  var d = new Date();
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
}
function dateTimeDE() {
  var d = new Date();
  return pad2(d.getDate()) + '.' + pad2(d.getMonth() + 1) + '.' + d.getFullYear() + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}
function safeName(s) { return String(s || 'Export').replace(/\.[a-z0-9]+$/i, '').replace(/[^\wäöüÄÖÜß\-]+/g, '_').replace(/^_+|_+$/g, '').substring(0, 60) || 'Export'; }
function findUp(node, cls) {
  while (node && node !== document) {
    if (node.className && typeof node.className === 'string' && (' ' + node.className + ' ').indexOf(' ' + cls + ' ') >= 0) return node;
    if (node.getAttribute && node.getAttribute('class') && (' ' + node.getAttribute('class') + ' ').indexOf(' ' + cls + ' ') >= 0) return node;
    node = node.parentNode;
  }
  return null;
}
function shortLabel(s, max) {
  s = String(s || '');
  return s.length > max ? s.substring(0, max - 1) + '…' : s;
}
function qcol(row, name) {
  if (row == null) return undefined;
  var v = row[name];
  if (v !== undefined) return v;
  var ln = String(name).toLowerCase(), ln2 = ln.replace(/_/g, '');
  for (var k in row) {
    if (!Object.prototype.hasOwnProperty.call(row, k)) continue;
    var lk = String(k).toLowerCase();
    if (lk === ln || lk.replace(/_/g, '') === ln2) return row[k];
  }
  return undefined;
}

/* ---------- Architektur-Schicht & Farblogik (prägnante EAM-Farben) ---------- */
function archCategory(st) {
  var s = String(st || '').toLowerCase();
  if (!s) return 'other';
  if (/capability|vision|enterprise|goal|strategic|concept/.test(s)) return 'concept';
  if (/service/.test(s)) return 'service';
  if (/node|activity|process|logical|information|business|rule|state|exchange|role/.test(s)) return 'logical';
  if (/system|resource|physical|software|artifact|hardware|device|network|platform|protocol|data|application|port|interface/.test(s)) return 'physical';
  if (/project|milestone|workpackage|roadmap|configuration/.test(s)) return 'project';
  if (/requirement|constraint|standard|measurement|measurable|property|stakeholder|concern|viewpoint|architecture/.test(s)) return 'req';
  if (/organization|person|post|actor/.test(s)) return 'org';
  return 'other';
}
/* Farben gemäß ADMBw/NAFv4: color = Schichtfarbe (Header/Rand), fill = heller Elementton.
   Quellen: NAFv4.1 Fig. 18; Bw „Grundlagen Methode Architektur nach NAFv4“ Abb. 36 (S. 58);
   Bw „Verwendung des ADMBw im Sparx EA“ Abb. 35 (S. 42) — siehe docs/ADMBw-Farben.md */
var CAT_META = {
  concept:  { label: 'Konzepte & Fähigkeiten', color: '#C8D300', fill: '#F6FF5D', rank: 0 },
  service:  { label: 'Dienste (Services)',     color: '#CE8ABB', fill: '#E7C7DE', rank: 1 },
  logical:  { label: 'Logik & Prozesse',       color: '#66B2E4', fill: '#B2D8F1', rank: 2 },
  org:      { label: 'Organisation & Akteure', color: '#EF7D00', fill: '#FFCA90', rank: 3 },
  physical: { label: 'Systeme & Ressourcen',   color: '#EF7D00', fill: '#FFCA90', rank: 3 },
  project:  { label: 'Projekte & Roadmap',     color: '#66B2E4', fill: '#B2D8F1', rank: 4 },
  req:      { label: 'Anforderungen & Normen', color: '#C9C9C9', fill: '#EDEDED', rank: 4 },
  other:    { label: 'Weitere Elemente',       color: '#DADADA', fill: '#F2F2F2', rank: 3 }
};
function stColor(st) {
  var cat = archCategory(st);
  return (CAT_META[cat] && CAT_META[cat].color) || '#64748B';
}
function stFill(st) {
  var cat = archCategory(st);
  return (CAT_META[cat] && CAT_META[cat].fill) || '#F2F2F2';
}

/* ================================================================
   NATIVER EXCEL (.XLSX) GENERATOR (OpenXML ZIP, 100 % Offline)
   ================================================================ */
var _CRC_TABLE = null;
function crc32(u8) {
  if (!_CRC_TABLE) {
    _CRC_TABLE = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      _CRC_TABLE[n] = c >>> 0;
    }
  }
  var crc = 0xFFFFFFFF;
  for (var i = 0; i < u8.length; i++) crc = _CRC_TABLE[(crc ^ u8[i]) & 0xFF] ^ (crc >>> 8);
  return (crc ^ 0xFFFFFFFF) >>> 0;
}
function utf8Bytes(str) {
  if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(String(str));
  var s = unescape(encodeURIComponent(String(str))), arr = new Uint8Array(s.length);
  for (var i = 0; i < s.length; i++) arr[i] = s.charCodeAt(i);
  return arr;
}
function makeZipStore(files) {
  /* files: [{name: 'xl/workbook.xml', data: Uint8Array}] */
  var localParts = [], centralParts = [], offset = 0, i;
  for (i = 0; i < files.length; i++) {
    var nameBytes = utf8Bytes(files[i].name);
    var data = files[i].data;
    var crc = crc32(data);
    var lh = new Uint8Array(30 + nameBytes.length);
    var dv = new DataView(lh.buffer);
    dv.setUint32(0, 0x04034b50, true);
    dv.setUint16(4, 20, true);
    dv.setUint16(6, 0x0800, true); /* UTF-8 flag */
    dv.setUint16(8, 0, true);      /* STORE (0) */
    dv.setUint16(10, 0, true);
    dv.setUint16(12, 0x5421, true);
    dv.setUint32(14, crc, true);
    dv.setUint32(18, data.length, true);
    dv.setUint32(22, data.length, true);
    dv.setUint16(26, nameBytes.length, true);
    dv.setUint16(28, 0, true);
    lh.set(nameBytes, 30);
    localParts.push(lh, data);

    var ch = new Uint8Array(46 + nameBytes.length);
    var cdv = new DataView(ch.buffer);
    cdv.setUint32(0, 0x02014b50, true);
    cdv.setUint16(4, 20, true);
    cdv.setUint16(6, 20, true);
    cdv.setUint16(8, 0x0800, true);
    cdv.setUint16(10, 0, true);
    cdv.setUint16(12, 0, true);
    cdv.setUint16(14, 0x5421, true);
    cdv.setUint32(16, crc, true);
    cdv.setUint32(20, data.length, true);
    cdv.setUint32(24, data.length, true);
    cdv.setUint16(28, nameBytes.length, true);
    cdv.setUint16(30, 0, true);
    cdv.setUint16(32, 0, true);
    cdv.setUint16(34, 0, true);
    cdv.setUint16(36, 0, true);
    cdv.setUint32(38, 0, true);
    cdv.setUint32(42, offset, true);
    ch.set(nameBytes, 46);
    centralParts.push(ch);

    offset += lh.length + data.length;
  }
  var centralSize = 0;
  for (i = 0; i < centralParts.length; i++) centralSize += centralParts[i].length;
  var eocd = new Uint8Array(22);
  var edv = new DataView(eocd.buffer);
  edv.setUint32(0, 0x06054b50, true);
  edv.setUint16(4, 0, true);
  edv.setUint16(6, 0, true);
  edv.setUint16(8, files.length, true);
  edv.setUint16(10, files.length, true);
  edv.setUint32(12, centralSize, true);
  edv.setUint32(16, offset, true);
  edv.setUint16(20, 0, true);
  return new Blob(localParts.concat(centralParts, [eocd]), {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  });
}
function xmlEsc(s) {
  return String(s == null ? '' : s)
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function colLetters(idx) {
  var s = '', n = idx + 1;
  while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}
function buildWorksheetXml(rows, colWidths, hasHeader) {
  var xml = [];
  xml.push('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>');
  xml.push('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">');
  if (colWidths && colWidths.length) {
    xml.push('<cols>');
    for (var c = 0; c < colWidths.length; c++) {
      xml.push('<col min="' + (c + 1) + '" max="' + (c + 1) + '" width="' + colWidths[c] + '" customWidth="1"/>');
    }
    xml.push('</cols>');
  }
  xml.push('<sheetData>');
  for (var r = 0; r < rows.length; r++) {
    var row = rows[r];
    var rnum = r + 1;
    var ht = (r === 0 && hasHeader) ? ' ht="24" customHeight="1"' : '';
    xml.push('<row r="' + rnum + '"' + ht + '>');
    for (var j = 0; j < row.length; j++) {
      var val = row[j];
      var ref = colLetters(j) + rnum;
      var style = (r === 0 && hasHeader) ? 1 : (r % 2 === 1 ? 2 : 3);
      if (typeof val === 'number' && isFinite(val)) {
        xml.push('<c r="' + ref + '" s="' + style + '"><v>' + val + '</v></c>');
      } else {
        xml.push('<c r="' + ref + '" t="inlineStr" s="' + style + '"><is><t xml:space="preserve">' + xmlEsc(val) + '</t></is></c>');
      }
    }
    xml.push('</row>');
  }
  xml.push('</sheetData>');
  if (hasHeader && rows.length > 1 && rows[0].length > 0) {
    xml.push('<autoFilter ref="A1:' + colLetters(rows[0].length - 1) + rows.length + '"/>');
  }
  xml.push('</worksheet>');
  return xml.join('');
}
function downloadXLSX(filename, sheets) {
  /* sheets: [{name, rows, widths, hasHeader}] */
  var files = [];
  var ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
    '<Default Extension="xml" ContentType="application/xml"/>',
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'];
  var wbXml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'];
  var wbRels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'];

  for (var i = 0; i < sheets.length; i++) {
    var idx = i + 1;
    var sname = String(sheets[i].name || ('Blatt' + idx)).replace(/[\\/?*\[\]:]/g, '_').substring(0, 31);
    ct.push('<Override PartName="/xl/worksheets/sheet' + idx + '.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>');
    wbXml.push('<sheet name="' + xmlEsc(sname) + '" sheetId="' + idx + '" r:id="rId' + idx + '"/>');
    wbRels.push('<Relationship Id="rId' + idx + '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet' + idx + '.xml"/>');
    var wsStr = buildWorksheetXml(sheets[i].rows || [[]], sheets[i].widths || [], sheets[i].hasHeader !== false);
    files.push({ name: 'xl/worksheets/sheet' + idx + '.xml', data: utf8Bytes(wsStr) });
  }
  ct.push('</Types>');
  wbXml.push('</sheets></workbook>');
  wbRels.push('</Relationships>');

  var rootRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>';
  var stylesXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    '<fonts count="2">' +
      '<font><sz val="10"/><color rgb="FF1E293B"/><name val="Segoe UI"/></font>' +
      '<font><b/><sz val="10.5"/><color rgb="FFFFFFFF"/><name val="Segoe UI"/></font>' +
    '</fonts>' +
    '<fills count="4">' +
      '<fill><patternFill patternType="none"/></fill>' +
      '<fill><patternFill patternType="gray125"/></fill>' +
      '<fill><patternFill patternType="solid"><fgColor rgb="FF004471"/></patternFill></fill>' +
      '<fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/></patternFill></fill>' +
    '</fills>' +
    '<borders count="2">' +
      '<border><left/><right/><top/><bottom/><diagonal/></border>' +
      '<border><left style="thin"><color rgb="FFCBD5E1"/></left><right style="thin"><color rgb="FFCBD5E1"/></right><top style="thin"><color rgb="FFCBD5E1"/></top><bottom style="thin"><color rgb="FFCBD5E1"/></bottom><diagonal/></border>' +
    '</borders>' +
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
    '<cellXfs count="4">' +
      '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' +
      '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>' +
      '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>' +
      '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>' +
    '</cellXfs>' +
    '</styleSheet>';

  files.unshift(
    { name: '[Content_Types].xml', data: utf8Bytes(ct.join('')) },
    { name: '_rels/.rels', data: utf8Bytes(rootRels) },
    { name: 'xl/workbook.xml', data: utf8Bytes(wbXml.join('')) },
    { name: 'xl/_rels/workbook.xml.rels', data: utf8Bytes(wbRels.join('')) },
    { name: 'xl/styles.xml', data: utf8Bytes(stylesXml) }
  );

  var blob = makeZipStore(files);
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 250);
}

function exportDataAsXLSX(els, rels, contextLabel, contextKind, fnameBase) {
  var i, o, c;
  var ovRows = [
    ['Eigenschaft', 'Wert'],
    ['Anwendung', 'ADMBw QEA Analyzer v4.0'],
    ['Exportierte Sicht / Bereich', contextLabel || 'Architektur-Auswertung'],
    ['Art des Exports', contextKind || 'Sicht'],
    ['Geladenes Modell (.qea)', MODELLNAME || '—'],
    ['Export-Zeitpunkt', dateTimeDE()],
    ['Anzahl Elemente in dieser Sicht', els.length],
    ['Anzahl Beziehungen in dieser Sicht', rels.length]
  ];
  /* Verteilung der Elementtypen ergänzen */
  var tc = {}, types = [];
  for (i = 0; i < els.length; i++) {
    var st = els[i].st || '(ohne Stereotyp)';
    tc[st] = (tc[st] || 0) + 1;
  }
  for (var k in tc) if (tc.hasOwnProperty(k)) types.push(k);
  types.sort(function (a, b) { return tc[b] - tc[a]; });
  if (types.length) {
    ovRows.push(['', '']);
    ovRows.push(['Elementtyp (Stereotype)', 'Anzahl in dieser Sicht']);
    for (i = 0; i < types.length; i++) ovRows.push([types[i], tc[types[i]]]);
  }

  var elRows = [['Name', 'Stereotype', 'EA-Metatyp', 'Alias', 'Paketpfad', 'Verbindungen (Gesamt)', 'Auf Sichten (Diagrammen)', 'Beschreibung / Notiz']];
  var tagRows = [['Element-Name', 'Stereotype', 'Eigenschaft (Tagged Value)', 'Wert', 'Notiz']];
  for (i = 0; i < els.length; i++) {
    o = els[i];
    var dlist = OBJ_DIAGS[String(o.id)] || [];
    var dnames = [];
    for (var d = 0; d < dlist.length && d < 10; d++) {
      if (DIAGMAP[dlist[d]]) dnames.push(DIAGMAP[dlist[d]].name);
    }
    elRows.push([
      o.name || '', o.st || '', o.type || '', o.alias || '', o.pkg || '',
      CONNCOUNT[String(o.id)] || 0,
      dnames.join(' | ') + (dlist.length > 10 ? ' (+' + (dlist.length - 10) + ')' : ''),
      shortLabel(o.note || '', 500)
    ]);
    var tlist = TAGS[String(o.id)] || [];
    for (var t = 0; t < tlist.length; t++) {
      tagRows.push([o.name || '', o.st || '', tlist[t].p || '', tlist[t].v || '', tlist[t].n || '']);
    }
  }

  var relRows = [['Quelle (Start)', 'Quelle-Stereotype', 'Beziehung (Stereotype)', 'Beziehungsname', 'Ziel (Ende)', 'Ziel-Stereotype']];
  for (i = 0; i < rels.length; i++) {
    c = rels[i];
    var a = OBJS[c.a], b = OBJS[c.b];
    relRows.push([
      a ? a.name : '?', a ? a.st : '',
      c.st || '(Verbindung)', c.name || '',
      b ? b.name : '?', b ? b.st : ''
    ]);
  }

  var sheets = [
    { name: '1_Uebersicht', rows: ovRows, widths: [36, 68], hasHeader: true },
    { name: '2_Elemente (' + els.length + ')', rows: elRows, widths: [34, 24, 15, 18, 42, 16, 36, 48], hasHeader: true },
    { name: '3_Beziehungen (' + rels.length + ')', rows: relRows, widths: [34, 22, 24, 20, 34, 22], hasHeader: true }
  ];
  if (tagRows.length > 1) {
    sheets.push({ name: '4_Tagged_Values', rows: tagRows, widths: [32, 22, 28, 42, 32], hasHeader: true });
  }
  var fn = 'ADMBw_QEA-Analyzer_' + safeName(fnameBase || contextLabel) + '_' + safeName(MODELLNAME) + '_' + dateStamp() + '.xlsx';
  downloadXLSX(fn, sheets);
}

function exportCurrentXLSX() {
  if (VPMODE === 'graph' && G.built && G.viewNodes.length) {
    exportGraphXLSX();
    return;
  }
  var lbl = (EXPCTX && EXPCTX.label) || PRINTCTX || 'Architektur-Sicht';
  var knd = (EXPCTX && EXPCTX.kind) || 'Sicht';
  var fnb = (EXPCTX && EXPCTX.fname) || lbl;
  exportDataAsXLSX(CURDATA.els || [], CURDATA.rels || [], lbl, knd, fnb);
}

function exportGraphXLSX() {
  var els = [], i;
  for (i = 0; i < G.viewNodes.length; i++) {
    var o = OBJS[G.viewNodes[i].id];
    if (o) els.push(o);
  }
  var rels = [];
  for (i = 0; i < G.viewLinks.length; i++) {
    rels.push({ a: G.viewLinks[i].a, b: G.viewLinks[i].b, st: G.viewLinks[i].st, name: '' });
  }
  var lbl = ((EXPCTX && EXPCTX.label) || 'Graph') + ' (Gefilterter Graph: ' + els.length + ' Knoten)';
  exportDataAsXLSX(els, rels, lbl, 'Graph-Visualisierung', 'Graph_' + ((EXPCTX && EXPCTX.fname) || 'Ansicht'));
}

function exportDiagramXLSX(diagId) {
  var diag = DIAGMAP[diagId];
  if (!diag) return;
  var ddata = getDiagramData(diagId);
  exportDataAsXLSX(ddata.els, ddata.rels, 'Sicht: ' + diag.name + ' (' + diag.pkgPath + ')', 'Einzel-Sicht (Diagramm)', 'Sicht_' + diag.name);
}

/* ================================================================
   HOCHAUFLÖSENDER PNG-EXPORT FÜR JEDE SICHT & JEDEN GRAPHEN
   ================================================================ */
function exportSvgElementToPNG(svgEl, titleText, subText, filename) {
  if (!svgEl) {
    alert('In der aktuellen Ansicht ist kein Schaubild oder Graph zum PNG-Export sichtbar.\nTipp: Öffnen Sie eine Sicht mit Diagramm oder schalten Sie auf „◉ Zusammenhänge (Graph)“.');
    return;
  }
  var clone = svgEl.cloneNode(true);
  var vbAttr = clone.getAttribute('viewBox');
  var vb = [0, 0, 1200, 800];
  if (vbAttr) {
    var parts = vbAttr.trim().split(/[\s,]+/);
    if (parts.length === 4) vb = [parseFloat(parts[0]) || 0, parseFloat(parts[1]) || 0, parseFloat(parts[2]) || 1200, parseFloat(parts[3]) || 800];
  } else {
    vb = [0, 0, parseFloat(clone.getAttribute('width')) || 1200, parseFloat(clone.getAttribute('height')) || 800];
  }

  /* Inline-Styles für Standalone-SVG-Rendering im Image/Canvas einbetten */
  var styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
  styleEl.textContent =
    'text { font-family: "Segoe UI", Arial, Helvetica, sans-serif; } ' +
    '.gk { stroke:#94A3B8; stroke-width:1.4px; opacity:.82; } ' +
    '.gk.hi { stroke:#B45309; stroke-width:2.5px; opacity:1; } ' +
    '.gk-lbl { font-size:8.5px; fill:#475569; paint-order:stroke; stroke:#FFFFFF; stroke-width:3px; } ' +
    '.gn text.nlbl { font-size:11px; font-weight:600; fill:#0F172A; paint-order:stroke; stroke:#FFFFFF; stroke-width:3.2px; } ' +
    '.gn text.nst { font-size:8.5px; fill:#475569; paint-order:stroke; stroke:#FFFFFF; stroke-width:2.5px; } ' +
    '.gn .nshape { stroke-width:2px; } ' +
    '.gn.fdim { opacity:.15; } ' +
    '.gn.fsel .nshape { stroke:#B45309; stroke-width:3px; }';
  clone.insertBefore(styleEl, clone.firstChild);

  var targetW = Math.max(960, Math.min(2600, Math.round(vb[2] * 1.4)));
  var targetH = Math.max(540, Math.min(2200, Math.round(vb[3] * 1.4)));
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(targetW));
  clone.setAttribute('height', String(targetH));

  var xml = new XMLSerializer().serializeToString(clone);
  var svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
  var url = URL.createObjectURL(svgBlob);
  var img = new Image();
  img.onload = function () {
    var scale = 2; /* 2x Retina-Qualität */
    var headerH = 58;
    var pad = 20;
    var canvas = document.createElement('canvas');
    canvas.width = (targetW + pad * 2) * scale;
    canvas.height = (targetH + headerH + pad * 2) * scale;
    var ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);

    /* Weißer Hintergrund */
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, targetW + pad * 2, targetH + headerH + pad * 2);

    /* Kopfbalken im Bw-Design */
    ctx.fillStyle = '#004471';
    ctx.fillRect(0, 0, targetW + pad * 2, headerH - 4);
    ctx.fillStyle = '#B45309';
    ctx.fillRect(0, headerH - 4, targetW + pad * 2, 4);

    ctx.fillStyle = '#FFFFFF';
    ctx.font = 'bold 16px "Segoe UI", Arial, sans-serif';
    ctx.fillText(String(titleText || 'ADMBw Architektur-Sicht').substring(0, 110), 18, 24);

    ctx.fillStyle = '#D2E3EE';
    ctx.font = '12px "Segoe UI", Arial, sans-serif';
    var metaLine = (subText ? subText + '  ·  ' : '') + 'Modell: ' + (MODELLNAME || '—') + '  ·  Export: ' + dateTimeDE();
    ctx.fillText(metaLine.substring(0, 150), 18, 43);

    /* SVG-Grafik zeichnen */
    ctx.drawImage(img, pad, headerH + pad / 2, targetW, targetH);
    URL.revokeObjectURL(url);

    if (canvas.toBlob) {
      canvas.toBlob(function (pngBlob) {
        if (!pngBlob) return;
        var purl = URL.createObjectURL(pngBlob);
        var a = document.createElement('a');
        a.href = purl;
        a.download = filename || ('ADMBw_Sicht_' + dateStamp() + '.png');
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(purl); }, 250);
      }, 'image/png');
    } else {
      var durl = canvas.toDataURL('image/png');
      var a2 = document.createElement('a');
      a2.href = durl;
      a2.download = filename || ('ADMBw_Sicht_' + dateStamp() + '.png');
      document.body.appendChild(a2);
      a2.click();
      setTimeout(function () { document.body.removeChild(a2); }, 250);
    }
  };
  img.onerror = function () {
    URL.revokeObjectURL(url);
    alert('PNG-Rendering fehlgeschlagen.');
  };
  img.src = url;
}

function exportDiagramPNG(diagId) {
  var diag = DIAGMAP[diagId];
  if (!diag) return;
  var host = el('diag-' + diagId);
  var svg = host ? host.querySelector('svg') : null;
  if (!svg) {
    var off = el('offscreen-render');
    off.innerHTML = '<div id="off-diag"></div>';
    renderDiagram(diag, el('off-diag'));
    svg = off.querySelector('svg');
  }
  if (!svg) {
    alert('Dieses Diagramm enthält keine darstellbaren Geometrie-Elemente.');
    return;
  }
  var fn = 'ADMBw_QEA-Analyzer_Sicht_' + safeName(diag.name) + '_' + dateStamp() + '.png';
  exportSvgElementToPNG(svg, 'Sicht: ' + diag.name, 'Paket: ' + (diag.pkgPath || '—'), fn);
}

function exportGraphPNG() {
  var svg = el('gsvg');
  if (!svg) {
    alert('Bitte zuerst die Graph-Ansicht öffnen.');
    return;
  }
  var lbl = (EXPCTX && EXPCTX.label) || PRINTCTX || 'Architektur-Graph';
  var fn = 'ADMBw_QEA-Analyzer_Graph_' + safeName(lbl) + '_' + dateStamp() + '.png';
  exportSvgElementToPNG(svg, 'Architektur-Graph: ' + lbl, G.viewNodes.length + ' Knoten · ' + G.viewLinks.length + ' Beziehungen', fn);
}

function exportCurrentPNG() {
  if (VPMODE === 'graph' && el('gsvg')) {
    exportGraphPNG();
    return;
  }
  /* Prüfen, ob in der aktuellen Ansicht ein Diagramm-SVG sichtbar ist */
  var visibleSvg = document.querySelector('#vp svg, #pkgmain svg');
  if (visibleSvg) {
    if (visibleSvg.id === 'gsvg') { exportGraphPNG(); return; }
    var lbl = (EXPCTX && EXPCTX.label) || PRINTCTX || 'Architektur-Sicht';
    exportSvgElementToPNG(visibleSvg, lbl, (EXPCTX && EXPCTX.kind) || '', 'ADMBw_QEA-Analyzer_' + safeName(lbl) + '_' + dateStamp() + '.png');
    return;
  }
  /* Wenn nicht im Graph-Modus und kein Diagramm offen: Graph kurz initialisieren oder Hinweis */
  if (CURDATA && CURDATA.els && CURDATA.els.length) {
    setVPMode('graph');
    setTimeout(function () {
      if (el('gsvg')) exportGraphPNG();
    }, 350);
  } else {
    alert('Bitte öffnen Sie eine Sicht (Diagramm) oder wechseln Sie in die Graph-Ansicht, um ein PNG zu exportieren.');
  }
}

/* ---------- CSV & PDF Export (kompatibel zu v2) ---------- */
function downloadText(filename, text) {
  try {
    var blob = new Blob([text], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 120);
  } catch (e) {
    var enc = encodeURIComponent(text);
    window.open('data:text/csv;charset=utf-8,' + enc);
  }
}
function csvQ(v) {
  v = String(v == null ? '' : v);
  if (v.indexOf(';') >= 0 || v.indexOf('"') >= 0 || v.indexOf('\n') >= 0 || v.indexOf('\r') >= 0) {
    return '"' + v.replace(/"/g, '""') + '"';
  }
  return v;
}
function exportElementsCSV() {
  if (!EXPCTX) return;
  var rows = [], i, o;
  for (i = 0; i < CURDATA.els.length; i++) {
    o = CURDATA.els[i];
    rows.push([o.name, o.st, o.alias, o.pkg]);
  }
  var lines = [];
  lines.push('sep=;');
  lines.push('ADMBw QEA Analyzer — Elemente;' + csvQ(EXPCTX.label));
  lines.push('Umfang;' + csvQ(EXPCTX.kind));
  lines.push('Modell;' + csvQ(MODELLNAME));
  lines.push('Export;' + csvQ(dateTimeDE()));
  lines.push('');
  lines.push(['Name', 'Stereotype', 'Alias', 'Paketpfad'].join(';'));
  for (i = 0; i < rows.length; i++) {
    var r = rows[i], out = [];
    for (var j = 0; j < r.length; j++) out.push(csvQ(r[j]));
    lines.push(out.join(';'));
  }
  downloadText('ADMBw_QEA-Analyzer_' + safeName(EXPCTX.fname) + '_Elemente_' + safeName(MODELLNAME) + '_' + dateStamp() + '.csv', '\ufeff' + lines.join('\r\n'));
}
function exportRelsCSV() {
  if (!EXPCTX) return;
  var lines = [], i;
  lines.push('sep=;');
  lines.push('ADMBw QEA Analyzer — Beziehungen;' + csvQ(EXPCTX.label));
  lines.push('Umfang;' + csvQ(EXPCTX.kind));
  lines.push('Modell;' + csvQ(MODELLNAME));
  lines.push('Export;' + csvQ(dateTimeDE()));
  lines.push('');
  lines.push(['Quelle', 'Quelle-Stereotype', 'Beziehung', 'Ziel', 'Ziel-Stereotype'].join(';'));
  for (i = 0; i < CURDATA.rels.length; i++) {
    var c = CURDATA.rels[i];
    var a = OBJS[c.a], b = OBJS[c.b];
    lines.push([csvQ(a ? a.name : '?'), csvQ(a ? a.st : ''), csvQ(c.st), csvQ(b ? b.name : '?'), csvQ(b ? b.st : '')].join(';'));
  }
  downloadText('ADMBw_QEA-Analyzer_' + safeName(EXPCTX.fname) + '_Beziehungen_' + safeName(MODELLNAME) + '_' + dateStamp() + '.csv', '\ufeff' + lines.join('\r\n'));
}
function exportPDF() {
  updatePrintMeta();
  window.print();
}
function updatePrintMeta() {
  var m = el('printmeta');
  if (!m) return;
  m.innerHTML = '<div class="pm-title">ADMBw QEA Analyzer</div>' +
    '<div class="pm-sub">' + esc(PRINTCTX || '—') + ' &nbsp;·&nbsp; Modell: ' + esc(MODELLNAME) + ' &nbsp;·&nbsp; Stand: ' + esc(dateTimeDE()) + '</div>';
}

/* ================================================================
   MODELL LADEN & PAKET-/SICHTEN-STRUKTUR AUFBAUEN
   ================================================================ */
/* ================================================================
   MEHRFACH-MODELL-MODUS (ab v6)
   Mehrere .qea-Dateien gleichzeitig laden; alle werden zu EINER Landkarte
   verschmolzen. Elemente/Beziehungen erhalten ein Quell-Präfix (<<M2>>),
   gleichnamige Elemente desselben Typs werden über Dateigrenzen hinweg
   zusammengeführt — nur so werden Beziehungen zwischen Architekturen sichtbar.
   ================================================================ */

function stripPrefix(s) {
  return String(s == null ? '' : s).replace(/^\s*<<[^>]{1,40}>>\s*/, '');
}
function mergeKey(name, st) {
  return norm(name).toLowerCase() + '\u0001' + String(st == null ? '' : st).trim().toLowerCase();
}

/* ================================================================
   Mehrfach-Modus: Kennungsschema und Fusion
   Modell 1 behält seine Original-Kennungen (abwärtskompatibel, auch im
   Einzelmodus). Ab Modell 2 erhält jedes Objekt eine eigene Kennung:
   m2_o101 (Element), m2_p7 (Paket), m2_d5 (Sicht), m2_c33 (Beziehung).
   Elemente werden über Name + Stereotype über Dateigrenzen hinweg zu
   einem gemeinsamen Knoten fusioniert — nur so werden Beziehungen
   zwischen Architekturen sichtbar.
   ================================================================ */
function keyFor(kind, raw, n) {
  if (raw == null) return raw;
  if (!MULTI_MODE || !n || Number(n) <= 1) return String(raw);
  return 'm' + Number(n) + '_' + kind + String(raw);
}
function pkgKey(raw) { return keyFor('p', raw, MODEL_N); }
function objKey(raw) { return keyFor('o', raw, MODEL_N); }
function diagKey(raw) { return keyFor('d', raw, MODEL_N); }
function connKey(raw) { return keyFor('c', raw, MODEL_N); }

/* ================================================================
   Zusammenführungs-Kriterien (Match-Prinzipien)
   Der Benutzer wählt an-/ab, WIE Elemente zwischen Architekturen
   wiedererkannt werden. Jedes Kriterium kann einzeln ein- oder
   ausgeschaltet werden — allein oder kombiniert.
   ================================================================ */
var SEM_MODE = true;                 /* „Semantik einbeziehen" (Kontrollkästchen) */
var MATCH_PRINCIPLE = { guid: true, name: false, alias: false };  /* aktive Kriterien: Standard = nur GUID */

/* Text normalisieren: Akzente/Umlaute auflösen, Sonderzeichen zu Leerzeichen */
function semNorm(s) {
  s = String(s == null ? '' : s);
  if (s.normalize) {
    s = s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
  }
  s = s.replace(/ß/gi, 'ss').replace(/æ/gi, 'ae').replace(/ø/gi, 'o');
  s = s.toLowerCase().replace(/[^a-z0-9]+/g, ' ');
  return s.replace(/^\s+|\s+$/g, '').replace(/\s+/g, ' ');
}

/* Stufe 2: Schreibvarianten entfernen.
   Wichtig: Klammer-Zusätze und Präfixe MÜSSEN vor dem Normalisieren entfernt
   werden — semNorm wandelt „-“ und „:“ in Leerzeichen um, danach greifen die
   Muster nicht mehr. */
function semLoose(s) {
  var t = String(s == null ? '' : s);
  t = t.replace(/\s*\([^)]*\)/g, ' ');                     /* Klammerzusätze: „(Basisverfahren)“ */
  t = t.replace(/\s*\[[^\]]*\]/g, ' ');                    /* eckige Zusätze */
  t = t.replace(/^\s*[A-Za-z]{1,3}\s*\d+\s*[:.\-–—]\s*/, '');  /* Präfixe: „P1 : “, „C5 –“ */
  t = t.replace(/\s*[-–—]\s*(Entwurf|Draft|Neu|New|Alt|Old|V\d+)\b/gi, ' ');
  t = t.replace(/\s+\b(v|version)\s*\d+([.\d]*)\b/gi, ' ');
  t = t.replace(/\s*[-–—]\s*(20\d{2})[.\-/](0?\d{1,2})[.\-/]?(0?\d{1,2})?\s*$/, ' ');  /* Jahres-/Versionsanhängsel */
  return semNorm(t);
}

/* Mindestlänge, damit sehr kurze Namen nicht über Kurzformen zusammenfallen */
function semUsable(t) { return t && t.length >= 4; }

/* Zusatzmaterial eines Elements einsammeln (Tags, Alias, Notiz) */
/* ------------------------------------------------------------------
   SEMANTIK-CACHE & INDEX (Performance-Fix)
   Vorher: findMergeHost scante für JEDES Element alle Objekte linear
   (O(N²)) und rief semMatch/semNorm (teure Regex) millionenfach auf.
   Große Architekturen (2× 5000+ Elemente) → Browser-Freeze/„Absturz".
   Jetzt: invertierte Indizes (id/name/alias -> Objekt-Keys in
   Einfüge-Reihenfolge) → Kandidatenlookup in O(1) je Element.
   Die Wahl des Trägerknotens bleibt mit der alten Linearsuche
   identisch: erste Position in der OBJS-Reihenfolge gewinnt.
   ------------------------------------------------------------------ */
var SEMNORM_CACHE = {};
var SEM_IDX = null;   /* { id:{}, name:{}, alias:{} } + SEM_SEQ */
var SEM_SEQ = {};

function semNormC(s) {
  s = String(s == null ? '' : s);
  var v = SEMNORM_CACHE[s];
  if (v !== undefined) return v;
  v = semNorm(s);
  if (SEMNORM_CACHE._n == null) SEMNORM_CACHE._n = 0;
  if (SEMNORM_CACHE._n < 400000) { SEMNORM_CACHE[s] = v; SEMNORM_CACHE._n++; }
  return v;
}

/* Index über alle Trägerknoten (name vorhanden, kein Package) aufbauen.
   Einfüge-Reihenfolge = Object.keys(OBJS)-Reihenfolge → gleiche Trägerwahl
   wie die alte Linearsuche. */
function semBuildIdx() {
  SEM_IDX = { id: {}, name: {}, alias: {} };
  SEM_SEQ = {};
  var seq = 0, k, o, i, m, key;
  var keys = Object.keys(OBJS);
  for (i = 0; i < keys.length; i++) {
    k = keys[i];
    o = OBJS[k];
    if (!o || !o.name || o.type === 'Package') continue;
    if (!o.sem) o.sem = semMeta(k);
    m = o.sem;
    SEM_SEQ[k] = seq++;
    for (var j = 0; j < m.ids.length; j++) {
      if (!SEM_IDX.id[m.ids[j]]) SEM_IDX.id[m.ids[j]] = [];
      SEM_IDX.id[m.ids[j]].push(k);
    }
    key = semNormC(o.name);
    if (key) {
      if (!SEM_IDX.name[key]) SEM_IDX.name[key] = [];
      SEM_IDX.name[key].push(k);
    }
    if (m.alias) {
      if (!SEM_IDX.alias[m.alias]) SEM_IDX.alias[m.alias] = [];
      SEM_IDX.alias[m.alias].push(k);
    }
  }
}

/* Semantik-Invalidierung nach Fusion/Ladung/Reset */
function semInvalidate() {
  SEM_IDX = null;
  SEM_SEQ = {};
}

function semMeta(k) {
  var o = OBJS[k] || {};
  var out = { ids: [], name: '', alias: '', note: '' };
  out.name = String(o.name || '');
  out.alias = semNormC(o.alias || '');
  out.note = semNormC(o.note || '');
  /* Primär die echte EA-Identität (t_object.ea_guid), erst danach Tagged Values.
     AAroN-Referenz: EAObject.EA_GUID / ObjectProcessor (eaGuid). */
  if (o.guid) out.ids.push(semNormC(o.guid));
  var t = TAGS[k] || [];
  for (var i = 0; i < t.length; i++) {
    var p = semNormC(t[i].p), v = String(t[i].v == null ? '' : t[i].v).trim();
    if (!v) continue;
    /* Identität: URI/UUID/GUID-Kennungen (Referenzstandard-Stempel) */
    if (/uri|uuid|guid|identifier/.test(p) && v.length >= 6) out.ids.push(semNormC(v));
  }
  return out;
}

/* Schlüssel eines Elements für eine gegebene Stufe. null = kein Schlüssel */
function semKey(o, meta, level) {
  var nm = String(o.name || '');
  var st = semNorm(o.st || '');
  if (level === 1) {
    var t1 = semNorm(nm);
    return { k: t1 + '\u0001' + st, label: 'exakt', name: t1 };
  }
  /* Ab Stufe 2: Schreibvariante als Namensbasis; exakter Name bleibt zusätzlich gueltig */
  var tl = semLoose(nm);
  if (!semUsable(tl)) return null;
  if (level === 3) {
    /* Identität vor Namensvergleich */
    if (meta && meta.ids.length) return { k: '\u0001id\u0001' + meta.ids[0], label: 'identität', name: tl };
    return { k: tl + '\u0001' + st, label: 'schreibweise', name: tl };
  }
  if (level === 4) {
    if (meta && meta.ids.length) return { k: '\u0001id\u0001' + meta.ids[0], label: 'identität', name: tl };
    var al = meta && semUsable(meta.alias) ? meta.alias : '';
    if (al) return { k: al + '\u0001' + st, label: 'alias', name: al };
    return { k: tl + '\u0001' + st, label: 'schreibweise', name: tl };
  }
  return { k: tl + '\u0001' + st, label: 'schreibweise', name: tl };
}

/* Treffer zweier Elemente nach den AKTIVEN Kriterien.
   Jedes Kriterium (GUID, Name, Alias) kann einzeln an-/abgewählt werden.
   Ein Kriterium zählt nur, wenn es AKTIV ist UND beidseitig nicht-leer.
   Ein leerer Schlüssel darf NIE als Treffer gelten. */
function semMatch(a, b) {
  if (!a || !b) return false;
  var P = MATCH_PRINCIPLE;
  var i, j;

  /* 1. Über GUID (URI/UUID) — nur wenn aktiv und beidseitig vorhanden */
  if (P.guid) {
    var ai = a.ids || [], bi = b.ids || [];
    for (i = 0; i < ai.length; i++) {
      if (!ai[i]) continue;
      for (j = 0; j < bi.length; j++) { if (bi[j] && ai[i] === bi[j]) return true; }
    }
  }

  /* 2. Über den Namen — nur wenn aktiv */
  if (P.name) {
    var an = semNorm(a.name || ''), bn = semNorm(b.name || '');
    if (an && bn && an === bn) return true;
  }

  /* 3. Über den Alias — nur wenn aktiv und beidseitig brauchbar */
  if (P.alias) {
    var al = semNorm(a.alias || ''), bl = semNorm(b.alias || '');
    if (al && bl && al === bl) return true;
  }

  return false;
}

function semLevelLabel() {
  var P = MATCH_PRINCIPLE;
  if (!SEM_MODE) return 'ohne Zusammenführung';
  var parts = [];
  if (P.guid) parts.push('GUID');
  if (P.name) parts.push('Name');
  if (P.alias) parts.push('Alias');
  if (!parts.length) return 'keine Kriterien aktiv';
  return 'Über ' + parts.join(' + ');
}

function finalizeMerge(n) {
  var k, o, i;
  if (!MULTI_MODE) return;
  if (n <= 1) {
    /* Modell 1: Schlüsselregister für die Fusion aufbauen (alle Stufen vorbereiten) */
    for (k in OBJS) {
      if (!OBJS.hasOwnProperty(k)) continue;
      o = OBJS[k];
      o.m = 1;
      o.models = [1];
      o.sem = semMeta(k);
      if (o.name && o.type !== 'Package') MODEL_KEYMAP[mergeKey(o.name, o.st)] = k;
    }
    if (MODEL_FILES[0]) MODEL_FILES[0].obj = Object.keys(OBJS).length;
    return;
  }
  /* Modell 2+: Zusatzmaterial sammeln und Kandidatenpaare bestimmen.
     Die eigentliche Zusammenführung passiert in commitMerge() — vorher zeigt
     die Vorschau, was zusammengelegt würde. */
  var cands = [];
  for (k in OBJS) {
    if (!OBJS.hasOwnProperty(k)) continue;
    o = OBJS[k];
    if (Number(o.m) !== Number(n)) continue;
    if (!o.name || o.type === 'Package') continue;
    o.sem = semMeta(k);
  }
  var nHost = 0, nFresh = 0;
  /* Index einmal je Modell aufbauen — ersetzt die frühere O(N²)-Linearsuche */
  semBuildIdx();
  for (k in OBJS) {
    if (!OBJS.hasOwnProperty(k)) continue;
    o = OBJS[k];
    if (Number(o.m) !== Number(n)) continue;
    if (!o.name || o.type === 'Package') { nFresh++; continue; }
    var host = SEM_MODE ? findMergeHost(k, n) : null;
    if (host) cands.push({ from: k, to: host });
    else nFresh++;
  }
  MERGE_CANDS = MERGE_CANDS.concat(cands);
  var mf = MODEL_FILES[n - 1];
  if (mf) { mf.cands = cands.length; mf.fresh = nFresh; mf.merged = cands.length; }
  /* Vollzogene Fusionen der bereits festgeschriebenen Modelle nicht erneut anbieten */
  MERGE_CANDS = MERGE_CANDS.filter(function (c) { return OBJS[c.from] && OBJS[c.to]; });
  semInvalidate();
}

/* Sucht für ein Element des Modells n einen bereits vorhandenen Trägerknoten.
   Index-basiert (semBuildIdx): Kandidaten kommen aus den invertierten
   Indizes (GUID/Name/Alias), Trägerwahl = früheste OBJS-Einfüge-Reihenfolge
   (identisch zur früheren Linearsuche, aber O(1) statt O(N) je Element). */
function findMergeHost(k, n) {
  if (!SEM_IDX) semBuildIdx();
  var o = OBJS[k];
  if (!o || !o.sem) return null;
  var P = MATCH_PRINCIPLE;
  var candLists = [], i, j, key, lst;
  if (P.guid) {
    for (i = 0; i < o.sem.ids.length; i++) {
      lst = SEM_IDX.id[o.sem.ids[i]];
      if (lst) candLists.push(lst);
    }
  }
  if (P.name) {
    lst = SEM_IDX.name[semNormC(o.name)];
    if (lst) candLists.push(lst);
  }
  if (P.alias && o.sem.alias) {
    lst = SEM_IDX.alias[o.sem.alias];
    if (lst) candLists.push(lst);
  }
  var best = null, bestSeq = Infinity, seq;
  for (i = 0; i < candLists.length; i++) {
    lst = candLists[i];
    for (j = 0; j < lst.length; j++) {
      key = lst[j];
      if (key === k) continue;
      var c = OBJS[key];
      if (!c) continue;
      if (Number(c.m) === Number(n)) continue;
      seq = SEM_SEQ[key];
      if (seq == null) continue;
      if (seq < bestSeq) { bestSeq = seq; best = key; }
    }
  }
  return best;
}
/* Vorschau: wie viele Elemente würden zusammengelegt?
   Zählt Elemente, die in einem AKTIVEN Kriterium übereinstimmen. */
function semPreview(n) {
  var res = { total: 0, geteilt: 0 };
  var k;
  semBuildIdx();
  for (k in OBJS) {
    if (!OBJS.hasOwnProperty(k)) continue;
    var o = OBJS[k];
    if (Number(o.m) !== Number(n) || !o.name || o.type === 'Package') continue;
    res.total++;
    if (!o.sem) o.sem = semMeta(k);
    if (findMergeHost(k, n)) res.geteilt++;
  }
  semInvalidate();
  return res;
}

/* ================================================================
   commitMerge(n): vollzieht die Zusammenführung für Modell n.
   Ohne Argument werden alle offenen Vorschläge (MERGE_CANDS) umgesetzt.
   skip: Objekt {elementKey: true} — Elemente, die der Nutzer einzeln
   ausgenommen hat („einzeln behalten").
   ================================================================ */
function commitMerge(n, skip) {
  if (!MULTI_MODE) return { merged: 0, fresh: 0 };
  var k, o, i;
  var list = MERGE_CANDS;
  if (n != null) list = MERGE_CANDS.filter(function (c) {
    var f = OBJS[c.from];
    return f && Number(f.m) === Number(n);
  });
  var oMap = {}, gO = {}, cntMerged = 0, cntFresh = 0;

  /* Alle vorhandenen Knoten übernehmen */
  for (k in OBJS) { if (OBJS.hasOwnProperty(k)) gO[k] = OBJS[k]; }

  var map = {};
  for (i = 0; i < list.length; i++) map[list[i].from] = list[i];

  var nModel = (n != null) ? Number(n) : (MODEL_N || 1);
  for (k in gO) {
    if (!gO.hasOwnProperty(k)) continue;
    o = gO[k];
    if (Number(o.m) !== nModel) continue;
    var c = map[k];
    /* Mehrere Elemente dieses Modells dürfen denselben Trägerknoten belegen
       (z. B. drei Projekte, die in der anderen Architektur ein Element bilden).
       Jedes Quell-Element wird genau einmal verarbeitet. */
    if (c && !(skip && skip[k])) {
      var ex = c.to;
      if (!gO[ex]) continue;
      oMap[k] = ex;
      MULTI_SRC[k] = ex;
      cntMerged++;
      var host = gO[ex];
      host.models = host.models || [1];
      if (host.models.indexOf(nModel) < 0) host.models.push(nModel);
      if (TAGS[k]) { TAGS[ex] = (TAGS[ex] || []).concat(TAGS[k]); delete TAGS[k]; }
      host.srcs = host.srcs || {};
      if (host.srcs[1] == null && host.localId != null) host.srcs[1] = String(host.localId);
      host.srcs[nModel] = String(o.localId != null ? o.localId : '');
      host.mnames = host.mnames || {};
      var mf = MODEL_FILES[nModel - 1];
      if (mf) host.mnames[nModel] = mf.name;
      /* Welches Kriterium hat den Treffer erbracht? Am Trägerknoten dokumentieren */
      host.matchkind = host.matchkind || 'name';
      if (o.sem && o.sem.kind) host.matchkind = o.sem.kind;
      if (host.matchkind !== 'name' && o.name) host.altname = String(o.name);
      delete gO[k];
    } else {
      o.models = [nModel];
      cntFresh++;
    }
  }

  /* Beziehungen, Sicht-Platzierungen und Sicht-Zuordnungen nachziehen */
  for (i = 0; i < CONS.length; i++) {
    if (oMap[CONS[i].a] != null) CONS[i].a = oMap[CONS[i].a];
    if (oMap[CONS[i].b] != null) CONS[i].b = oMap[CONS[i].b];
  }
  for (k in DIAGOBJ) {
    if (!DIAGOBJ.hasOwnProperty(k)) continue;
    for (i = 0; i < DIAGOBJ[k].length; i++) {
      if (oMap[DIAGOBJ[k][i].oid] != null) DIAGOBJ[k][i].oid = oMap[DIAGOBJ[k][i].oid];
    }
  }
  for (k in OBJ_DIAGS) {
    if (!OBJ_DIAGS.hasOwnProperty(k)) continue;
    if (oMap[k] != null) {
      OBJ_DIAGS[oMap[k]] = (OBJ_DIAGS[oMap[k]] || []).concat(OBJ_DIAGS[k]);
      delete OBJ_DIAGS[k];
    }
  }
  /* Paket-Listen dieses Modells bereinigen (fusionierte Elemente auf den Zielknoten umbiegen) */
  for (k in PKG) {
    if (!PKG.hasOwnProperty(k) || Number(PKG[k].m) !== nModel) continue;
    var lst = PKG[k].objs, nw = [], seen = {};
    for (i = 0; i < lst.length; i++) {
      var oid2 = String(lst[i].id);
      if (oMap[oid2] != null) oid2 = oMap[oid2];
      if (seen[oid2]) continue;
      seen[oid2] = 1;
      nw.push(OBJS[oid2] || lst[i]);
    }
    PKG[k].objs = nw;
  }
  /* Verworfene Kennungen auch aus dem Schlüsselregister entfernen */
  for (k in oMap) {
    if (!oMap.hasOwnProperty(k)) continue;
    var oo = OBJS[k];
    if (oo && oo.name) delete MODEL_KEYMAP[mergeKey(oo.name, oo.st)];
  }
  OBJS = gO;
  semInvalidate();
  recountPkgs();
  return { merged: cntMerged, fresh: cntFresh };
}


function loadQea(buffer, name) {
  if (SINGLE && !MULTI_MODE) {
    try { DB = qeaOpen(buffer); }
    catch (e) { alert('Datei konnte nicht gelesen werden:\n\n' + e.message + '\n\nUnterstützt werden QEA-/EAPX-Dateien im SQLite-Format (Sparx Enterprise Architect).'); return; }
    MODELLNAME = name;
    G.built = false;
    resetModelData();
    MODEL_DBS = {}; MODEL_DBS[1] = DB;
    MODEL_DB = DB; MODEL_OBJS = OBJS; MODEL_PKG = PKG; MODEL_DIAGS = DIAGS; MODEL_TAGS = TAGS;
    buildModel();
    if (!Object.keys(OBJS).length && !DIAGS.length && !Object.keys(PKG).length) {
      alert('In der Datei wurde keine Sparx-EA-Struktur gefunden (Kern-Tabelle t_object fehlt oder ist leer).');
      return;
    }
    if (typeof EDIT !== 'undefined' && EDIT.setSource) { EDIT.setSource(buffer, name, 1); if (EDIT.setSourceCount) EDIT.setSourceCount(1); }
    var nObj = Object.keys(OBJS).length, nDiag = DIAGS.length, nPkg = Object.keys(PKG).length, nCon = CONS.length;
    el('upload').style.display = 'none';
    el('workspace').style.display = 'block';
    el('modellname').textContent = name;
    renderModelStats(nPkg, nDiag, nObj, nCon);
    renderWarnbar();
    computeStats();
    renderQuickBar();
    renderGrid();
    renderDiagsCatalog();
    if (el('cnt-path')) el('cnt-path').textContent = fmt(nCon);
    PATH = { start: null, end: null, directed: false, maxHops: 5, mode: 'shortest', last: null, selPath: 0, ctx: false };
    PATH_ADJ = null; PATH_COMP = null;
    pathRenderTab();
    var startPkg = PKG_ROOTS.length ? PKG_ROOTS[0].id : null;
    if (startPkg != null) {
      PKG_OPEN[startPkg] = true;
      for (var j = 0; j < PKG_ROOTS[0].children.length; j++) PKG_OPEN[PKG_ROOTS[0].children[j].id] = true;
    }
    renderPkgTree();
    showView('explorer');
    if (startPkg != null) openPackage(startPkg, true);
  } else {
    addModelToMerge(buffer, name);
  }
}

function renderModelStats(nPkg, nDiag, nObj, nCon) {
  var s = el('stats');
  if (!s) return;
  s.innerHTML =
    '<b>' + fmt(nPkg) + '</b> Pakete &nbsp;·&nbsp; ' +
    '<b>' + fmt(nDiag) + '</b> Sichten (Diagramme) &nbsp;·&nbsp; ' +
    '<b>' + fmt(nObj) + '</b> Elemente &nbsp;·&nbsp; ' +
    '<b>' + fmt(nCon) + '</b> Beziehungen';
  if (el('cnt-pkg')) el('cnt-pkg').textContent = fmt(nPkg);
  if (el('cnt-diag')) el('cnt-diag').textContent = fmt(nDiag);
  if (el('cnt-path')) el('cnt-path').textContent = fmt(nCon);
}

function shortFileName(nm) {
  var s = String(nm || '').replace(/\.(qea|qeax|eapx|sqlite)$/i, '');
  return s.length > 34 ? s.substring(0, 32) + '…' : s;
}

/* Datenstrukturen leeren (Einzelmodus: frischer Aufbau; vor dem Verschmelzen
   wird NICHT geleert, weil die Landkarte wachsen soll) */
function resetModelData() {
  OBJS = {}; CONS = []; PKG = {}; PKG_ROOTS = []; PKG_OPEN = {};
  DIAGS = []; DIAGMAP = {}; DIAGOBJ = {}; DIAGLINK = {}; OBJ_DIAGS = {}; TAGS = {};
  MULTI_SRC = {};
  MERGE_CANDS = [];
  MODEL_N = 0; MODEL_FILES = []; MODEL_KEYMAP = {}; CONNMAP = {};
  MODEL_DBS = {}; MODEL_DB = null; MODEL_OBJS = {}; MODEL_PKG = {}; MODEL_DIAGS = []; MODEL_TAGS = {};
  SEMNORM_CACHE = {}; SEM_IDX = null; SEM_SEQ = {};
}

/* Ein Modell in die verschmolzene Landkarte einarbeiten */
function addModelToMerge(buffer, name) {
  var myDb;
  try { myDb = qeaOpen(buffer); }
  catch (e) { alert('Datei „' + name + '“ konnte nicht gelesen werden:\n\n' + e.message); return; }

  /* Prüfen, ob überhaupt eine Sparx-EA-Struktur enthalten ist (vor dem Einarbeiten) */
  var probe = null;
  try { probe = myDb.rows('t_object'); } catch (e2) { probe = null; }
  if (!probe || !probe.length) {
    alert('In der Datei „' + name + '“ wurde keine Sparx-EA-Struktur gefunden (Kern-Tabelle t_object fehlt oder ist leer).');
    return;
  }

  MODEL_N++;
  var n = MODEL_N;
  MODEL_FILES.push({ n: n, name: name, pkg: 0, diag: 0, obj: 0, con: 0 });
  var mi = MODEL_FILES[MODEL_FILES.length - 1];

  /* Dieses Modell regulär aufbauen; die Fusion erledigt finalizeMerge (in buildModel) */
  DB = myDb; MODELLNAME = name; G.built = false;
  MODEL_DBS[n] = myDb;
  var prePkg = Object.keys(PKG).length, preObj = Object.keys(OBJS).length,
      preDiag = DIAGS.length, preCon = CONS.length;
  buildModel();
  mi.pkg = Object.keys(PKG).length - prePkg;
  mi.diag = DIAGS.length - preDiag;
  mi.con = CONS.length - preCon;
  /* Achtung: mi.obj ist mit 0 initialisiert — ein Guard `mi.obj == null`
     griffe nie (0 == null ist in JS false) → M2 zeigte „0 Elemente“. */
  mi.obj = Object.keys(OBJS).length - preObj;

  var i;
  /* Paket-Sichtbarkeit über den Explorer (neue Wurzelpakete einklappen) */
  for (i = 0; i < PKG_ROOTS.length; i++) {
    if (Number(PKG_ROOTS[i].m) === Number(n)) PKG_OPEN[PKG_ROOTS[i].id] = false;
  }

  /* Globale Referenzen für Fallbacks (Edit-Modul, Graph) aktualisieren */
  MODEL_DB = DB; MODEL_OBJS = OBJS; MODEL_PKG = PKG; MODEL_DIAGS = DIAGS; MODEL_TAGS = TAGS;

  /* Quellwechsel im Edit-Modus (Mehrfach-Modus: je Datei eigener Satz Originaldaten) */
  if (typeof EDIT !== 'undefined') {
    if (EDIT.addSource) EDIT.addSource(buffer, name, n);
    if (EDIT.setSourceCount) EDIT.setSourceCount(MODEL_FILES.length);
  }

  /* Ansicht aktualisieren */
  var totPkg = Object.keys(PKG).length, totObj = Object.keys(OBJS).length, totDiag = DIAGS.length, totCon = CONS.length;
  el('upload').style.display = 'none';
  el('workspace').style.display = 'block';
  var mm = '';
  for (i = 0; i < MODEL_FILES.length; i++) {
    mm += (i ? ' &nbsp;+&nbsp; ' : '') + '<b>M' + MODEL_FILES[i].n + '</b> ' + esc(shortFileName(MODEL_FILES[i].name));
  }
  el('modellname').innerHTML = mm;
  renderModelStats(totPkg, totDiag, totObj, totCon);
  MODELLNAME = MODEL_FILES.length + ' Modelle: ' + MODEL_FILES.map(function (f) { return f.name; }).join(' + ');

  renderWarnbar();
  computeStats();
  renderQuickBar();
  renderGrid();
  renderDiagsCatalog();
  PATH = { start: null, end: null, directed: false, maxHops: 5, mode: 'shortest', last: null, selPath: 0, ctx: false };
  PATH_ADJ = null; PATH_COMP = null;
  pathRenderTab();
  renderMergeBar();

  /* Erstes Modell: Explorer öffnen wie bisher; weitere: Übersicht der Sichten */
  if (MODEL_FILES.length === 1) {
    var startPkg = PKG_ROOTS.length ? PKG_ROOTS[0].id : null;
    if (startPkg != null) { PKG_OPEN[startPkg] = true; for (var j2 = 0; j2 < PKG_ROOTS[0].children.length; j2++) PKG_OPEN[PKG_ROOTS[0].children[j2].id] = true; }
    renderPkgTree();
    showView('explorer');
    if (startPkg != null) openPackage(startPkg, true);
  } else {
    renderPkgTree();
    showView('diags');
    /* Neu erkannte Zusammenführungen zur Prüfung anbieten */
    var offen = MERGE_CANDS.filter(function (c) { return OBJS[c.from] && OBJS[c.to]; });
    if (SEM_MODE && offen.length) {
      openMergePreview();
    } else {
      toast('Modell ' + n + ' geladen: ' + esc(shortFileName(name)) + ' · ' + MODEL_FILES.length + ' Architekturen'
        + (SEM_MODE ? ' (keine Zusammenführungen erkannt)' : ' (ohne Zusammenführung)'));
    }
  }
}

/* Kleine Rückmeldung (eigener Toast, unabhängig vom Edit-Modus) */
function toast(msg) {
  var t = el('mttoast');
  if (!t) { return; }
  t.innerHTML = msg;
  t.removeAttribute('hidden');
  if (toast._tm) clearTimeout(toast._tm);
  toast._tm = setTimeout(function () { t.setAttribute('hidden', ''); }, 4200);
}

/* Analyse-Dialoge nutzen das Edit-Modal; fehlt der Edit-Modus, greift ein Minimalfenster. */
function modalClose() {
  if (typeof EDIT !== 'undefined' && EDIT.modalClose) { EDIT.modalClose(); return; }
  var m = el('editmodal');
  if (m) { m.setAttribute('hidden', ''); m.innerHTML = ''; }
}
function openModal(title, bodyHtml, footHtml) {
  if (typeof EDIT !== 'undefined' && EDIT.openModal) { EDIT.openModal(title, bodyHtml, footHtml); return; }
  var m = el('editmodal');
  if (!m) { toast('<b>' + title + '</b>'); return; }
  m.innerHTML = '<div class="em-back" onclick="modalClose()"></div><div class="em-box">' +
    '<div class="em-head"><b>' + title + '</b><button onclick="modalClose()" title="Schließen">✕</button></div>' +
    '<div class="em-body">' + bodyHtml + '</div>' +
    '<div class="em-foot">' + (footHtml || '<button class="btn-sm" onclick="modalClose()">Schließen</button>') + '</div>' +
    '</div>';
  m.removeAttribute('hidden');
}

/* Steuerleiste für den Mehrfach-Modus */
function renderMergeBar() {
  var bar = el('mergebar');
  if (!bar) return;
  if (!MULTI_MODE) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  var i;
  var offen = MERGE_CANDS.filter(function (c) { return OBJS[c.from] && OBJS[c.to]; });

  var h = ['<div class="mg-inner">'];
  h.push('<span class="mg-lead">🗂️ <b>' + MODEL_FILES.length + ' Architekturen</b> geladen'
    + (SEM_MODE ? ' · Zusammenführung: <b>' + esc(semLevelLabel()) + '</b>' : ' · <b>ohne Zusammenführung</b>') + '</span>');
  h.push('<span class="mg-files">');
  for (i = 0; i < MODEL_FILES.length; i++) {
    var f = MODEL_FILES[i];
    h.push('<span class="mg-file" title="' + esc(f.name) + '"><b>M' + f.n + '</b> ' + esc(shortFileName(f.name)) +
      '<em>' + f.pkg + ' Pakete · ' + f.diag + ' Sichten · ' + f.obj + ' Elemente · ' + f.con + ' Beziehungen</em></span>');
  }
  h.push('</span>');
  h.push('<span class="mg-act">');
  h.push('<button class="btn-sm" onclick="pickFiles(true)">＋ Weitere Datei laden</button>');
  if (offen.length) h.push('<button class="btn-sm pri" onclick="openMergePreview()" title="Vorschau: welche Elemente werden zusammengelegt?">👁 ' + fmt(offen.length) + ' Zusammenführungen prüfen</button>');
  h.push('<button class="btn-sm" onclick="openMergeReport()" title="Was wurde zusammengeführt?">🔍 Fusionsbericht</button>');
  h.push('<button class="btn-sm amber" onclick="exitMultiMode()" title="Verschmelzung auflösen, nur das erste Modell behalten">✕ Auflösen</button>');
  h.push('</span></div>');

  if (offen.length) {
    h.push('<div class="mg-preview"><b>' + fmt(offen.length) + '</b> Element(e) wurden über die Dateigrenzen hinweg erkannt '
      + '(Kriterien: ' + esc(semLevelLabel()) + ') &nbsp;<span class="dim">— noch nicht zusammengelegt. Prüfen und dann bestätigen.</span></div>');
  } else if (MODEL_FILES.length > 1) {
    h.push('<div class="mg-preview dim">Keine weiteren Zusammenführungen erkannt. '
      + (SEM_MODE ? 'Prüfen Sie, ob weitere Kriterien aktiviert sind.' : 'Es ist „ohne Zusammenführung" gewählt.') + '</div>');
  }

  /* Kriterien dauerhaft zugänglich machen (auch nach dem Laden) */
  var P = MATCH_PRINCIPLE;
  h.push('<div class="mg-crit"><b>Kriterien:</b> '
    + '<label class="critbox"><input type="checkbox" ' + (P.guid ? 'checked' : '') + ' onchange="setMatchPrinciple(\'guid\', this.checked)"> GUID</label>'
    + '<label class="critbox"><input type="checkbox" ' + (P.name ? 'checked' : '') + ' onchange="setMatchPrinciple(\'name\', this.checked)"> Name</label>'
    + '<label class="critbox"><input type="checkbox" ' + (P.alias ? 'checked' : '') + ' onchange="setMatchPrinciple(\'alias\', this.checked)"> Alias</label>'
    + ' &nbsp;<span class="dim">Elemente werden zusammengelegt, wenn sie in einem der aktivierten Merkmale übereinstimmen.</span></div>');

  bar.innerHTML = h.join('');
  bar.style.display = 'block';
}

/* Vorschau-Dialog: welche Elemente würden zusammengelegt, mit Einzelabwahl.
   Gruppiert nach dem Kriterium, das den Treffer erbracht hat. */
function openMergePreview() {
  var offen = MERGE_CANDS.filter(function (c) { return OBJS[c.from] && OBJS[c.to]; });
  if (!offen.length) { toast('Keine offenen Zusammenführungen.'); return; }
  var by = { guid: [], name: [], alias: [] }, i;
  for (i = 0; i < offen.length; i++) {
    var c = offen[i], f = OBJS[c.from], t = OBJS[c.to];
    if (!f || !t) continue;
    var kind = 'name';
    if (MATCH_PRINCIPLE.guid && f.sem && t.sem) {
      var fi = f.sem.ids || [], ti = t.sem.ids || [], found = false;
      for (var x = 0; x < fi.length && !found; x++) for (var y = 0; y < ti.length && !found; y++) if (fi[x] && fi[x] === ti[y]) found = true;
      if (found) kind = 'guid';
    }
    if (kind === 'name' && MATCH_PRINCIPLE.alias && f.sem && t.sem && f.sem.alias && t.sem.alias && semNorm(f.sem.alias) === semNorm(t.sem.alias)) kind = 'alias';
    by[kind].push(c);
  }
  var h = ['<div style="font-size:12.5px">'];
  h.push('<p style="margin:0 0 10px 0">Diese Elemente aus den neu geladenen Architekturen wurden in bereits vorhandenen Architekturen <b>wiedererkannt</b>. '
    + 'Bestätigen Sie die Zusammenführung, damit sie sich einen Knoten teilen — dann werden auch <b>Beziehungen über die Architekturgrenze</b> sichtbar. '
    + 'Nehmen Sie Häkchen heraus, wenn ein Element bewusst eigenständig bleiben soll.</p>');
  var titel = { guid: 'Erkannt über die GUID', name: 'Erkannt über den Namen', alias: 'Erkannt über den Alias' };
  ['guid', 'name', 'alias'].forEach(function (kind) {
    var list = by[kind];
    if (!list.length) return;
    h.push('<h3 style="margin:14px 0 6px 0">' + esc(titel[kind]) + ' (' + list.length + ')</h3>');
    h.push('<table class="data"><thead><tr><th style="width:34px"><input type="checkbox" checked onchange="mergePreviewAll(this)"></th><th>Element in der neuen Architektur</th><th>zusammengelegt mit</th><th>Architekturen</th></tr></thead><tbody>');
    for (i = 0; i < list.length && i < 500; i++) {
      var c2 = list[i], f2 = OBJS[c2.from], t2 = OBJS[c2.to];
      if (!f2 || !t2) continue;
      h.push('<tr><td><input type="checkbox" class="mp-ck" data-k="' + esc(c2.from) + '" checked></td>'
        + '<td><b>' + esc(f2.name || '') + '</b>' + (semNorm(f2.name) !== semNorm(t2.name) ? ' <span class="gs-meta">(neu)</span>' : '') + '</td>'
        + '<td>' + esc(t2.name || '') + (semNorm(f2.name) !== semNorm(t2.name) ? ' <span class="gs-meta">(vorhanden)</span>' : '') + '</td>'
        + '<td><span class="mchip mchip-m' + (f2.m || 2) + '">M' + (f2.m || 2) + '</span> → <span class="mchip mchip-m' + (t2.m || 1) + '">M' + (t2.m || 1) + '</span></td></tr>');
    }
    h.push('</tbody></table>');
    if (list.length > 500) h.push('<div class="hint">… ' + (list.length - 500) + ' weitere.</div>');
  });
  h.push('</div>');
  openModal('👁 Zusammenführungen prüfen (' + offen.length + ')',
    h.join(''),
    '<button class="btn-sm pri" onclick="applyMergePreview()">✔ Ausgewählte zusammenlegen</button>'
    + ' <button class="btn-sm" onclick="skipAllMerge()">Ohne Zusammenführung fortfahren</button>'
    + ' <button class="btn-sm" onclick="modalClose()">Abbrechen</button>');
}

function mergePreviewAll(src) {
  var cks = document.querySelectorAll('#editmodal .mp-ck');
  for (var i = 0; i < cks.length; i++) cks[i].checked = !!src.checked;
}

/* Auswahl aus dem Vorschau-Dialog anwenden */
function applyMergePreview() {
  var cks = document.querySelectorAll('#editmodal .mp-ck');
  var skip = {}, n = 0;
  for (var i = 0; i < cks.length; i++) {
    if (!cks[i].checked) { skip[cks[i].getAttribute('data-k')] = true; n++; }
  }
  modalClose();
  var res = commitMerge(null, skip);
  renderMergeBar();
  renderAfterMerge();
  toast('✅ <b>' + fmt(res.merged) + '</b> Element(e) zusammengelegt'
    + (n ? ', <b>' + n + '</b> bewusst getrennt gehalten' : '') + '.');
}

function skipAllMerge() {
  modalClose();
  MERGE_CANDS = [];
  renderMergeBar();
  toast('Ohne Zusammenführung fortgefahren. Die Architekturen stehen nebeneinander zur Verfügung — Verbindungen über die Grenze bleiben unsichtbar.');
}

/* Nach einer Änderung der Landkarte alles neu zeichnen */
function renderAfterMerge() {
  try { computeStats(); } catch (e) { }
  try { renderGrid(); } catch (e) { }
  try { renderDiagsCatalog(); } catch (e) { }
  try { renderQuickBar(); } catch (e) { }
  try { renderPkgTree(); } catch (e) { }
  var totPkg = Object.keys(PKG).length, totObj = Object.keys(OBJS).length, totDiag = DIAGS.length, totCon = CONS.length;
  try { renderModelStats(totPkg, totDiag, totObj, totCon); } catch (e) { }
  if (el('cnt-path')) el('cnt-path').textContent = fmt(totCon);
  PATH_ADJ = null; PATH_COMP = null;
}

function openMergeReport() {
  if (!MULTI_MODE) { toast('Es ist nur ein Modell geladen.'); return; }
  var h = ['<div style="font-size:12.5px">'];
  h.push('<p style="margin:0 0 8px 0">In einer <b>verschmolzenen Landkarte</b> stehen alle Elemente, Pakete und Sichten aller geladenen Dateien gemeinsam zur Verfügung. '
    + 'Elemente werden über <b>Name + Stereotype</b> zusammengeführt — nur so werden Beziehungen zwischen zwei Architekturen sichtbar. '
    + 'Das Kürzel <code>&lt;&lt;M2&gt;&gt;</code> im Namen kennzeichnet die Herkunft, wenn Namen doppelt vorkommen.</p>');
  h.push('<table class="data"><thead><tr><th>Kürzel</th><th>Datei</th><th>Pakete</th><th>Sichten</th><th>Elemente</th><th>Beziehungen</th></tr></thead><tbody>');
  for (var i = 0; i < MODEL_FILES.length; i++) {
    var f = MODEL_FILES[i];
    h.push('<tr><td><b>M' + f.n + '</b></td><td>' + esc(f.name) + '</td><td>' + f.pkg + '</td><td>' + f.diag + '</td><td>' + f.obj + '</td><td>' + f.con + '</td></tr>');
  }
  h.push('<tr style="background:#F1F5F9"><td colspan="2"><b>Summe geladen</b></td><td>' + Object.keys(PKG).length + '</td><td>' + DIAGS.length + '</td><td>' + Object.keys(OBJS).length + '</td><td>' + CONS.length + '</td></tr>');
  h.push('</tbody></table>');
  var merged = 0, k;
  for (k in MULTI_SRC) if (MULTI_SRC.hasOwnProperty(k)) merged++;
  h.push('<p style="margin:10px 0 4px 0"><b>' + fmt(merged) + '</b> Element(e) wurden über Dateigrenzen hinweg zusammengeführt (gleicher Name + Stereotype).</p>');
  h.push('<p class="dim" style="margin:0">Hinweis: Sicht-Diagramme bleiben je Datei getrennt. Beim Bearbeiten und Speichern gilt: es wird immer in die Datei der jeweiligen Herkunft geschrieben.</p>');
  h.push('</div>');
  openModal('🗂️ Fusionsbericht', h.join(''), '<button class="btn-sm" onclick="modalClose()">Schließen</button>');
}

/* „✕ Auflösen“: Landkarte zurücknehmen und das erste Modell wieder als
   Einzelmodell anzeigen (README: „nimmt die Fusion zurück“).
   Sichere Umsetzung: kompletter Neuaufbau aus der Datenbank des ersten
   Modells (MODEL_DBS[1]) — identischer Pfad wie ein frisches Einzelladen.
   Vorgemerkte Änderungen (ggf. aus mehreren Dateien) werden dabei verworfen;
   existieren welche, wird vorher nachgefragt. */
function exitMultiMode() {
  if (!MULTI_MODE) { toast('Es ist nur ein Modell geladen.'); return; }
  var first = MODEL_FILES.length ? MODEL_FILES[0] : null;
  var db1 = (first && MODEL_DBS[first.n]) ? MODEL_DBS[first.n] : (MODEL_DBS[1] || MODEL_DB);
  if (!db1) { toast('Es ist kein erstes Modell verfügbar — bitte die Seite neu laden.'); return; }
  var pending = 0;
  try { if (typeof EDIT !== 'undefined' && EDIT._internal && EDIT._internal.count) pending = EDIT._internal.count(); } catch (e) { }

  if (pending > 0) {
    if (!confirm('Zusammenführung auflösen?\n\nDie Landkarte wird entfernt — nur „' + shortFileName(first ? first.name : '') + '“ bleibt als Einzelmodell geladen.\n\n⚠ Dabei gehen ' + pending + ' vorgemerkte Änderung(en) verloren.')) return;
  }

  var name1 = first ? first.name : (MODELLNAME || 'Modell 1');
  SINGLE = true;
  MULTI_MODE = false;
  DB = db1;
  MODELLNAME = name1;
  G.built = false;
  resetModelData();                       /* leert OBJS/PKG/DIAGS/…, MODEL_N=0, MULTI_SRC, MERGE_CANDS, SEM-Index */
  MODEL_DBS = {}; MODEL_DBS[1] = DB;
  MODEL_DB = DB;
  buildModel();
  MODEL_OBJS = OBJS; MODEL_PKG = PKG; MODEL_DIAGS = DIAGS; MODEL_TAGS = TAGS;

  /* Edit-Modul: nur noch Quelle 1; Vormerkungen (u. a. für Datei 2) verwerfen */
  if (typeof EDIT !== 'undefined') {
    if (first && first.bytes && EDIT.setSource) { EDIT.setSource(first.bytes, name1, 1); }
    else if (EDIT.clearAll) { try { EDIT.clearAll(true); } catch (e2) { } }
    if (EDIT.setSourceCount) EDIT.setSourceCount(1);
  }

  var nPkg = Object.keys(PKG).length, nDiag = DIAGS.length, nObj = Object.keys(OBJS).length, nCon = CONS.length;
  el('upload').style.display = 'none';
  el('workspace').style.display = 'block';
  el('modellname').textContent = name1;
  renderModelStats(nPkg, nDiag, nObj, nCon);
  renderWarnbar();
  computeStats();
  renderQuickBar();
  renderGrid();
  renderDiagsCatalog();
  if (el('cnt-path')) el('cnt-path').textContent = fmt(nCon);
  PATH = { start: null, end: null, directed: false, maxHops: 5, mode: 'shortest', last: null, selPath: 0, ctx: false };
  PATH_ADJ = null; PATH_COMP = null;
  pathRenderTab();
  renderMergeBar();                       /* versteckt die Landkarten-Leiste (MULTI_MODE=false) */
  var lab = el('multilabel'); if (lab) lab.className = 'mmode';
  var chk = el('multichk'); if (chk) chk.checked = false;
  var startPkg = PKG_ROOTS.length ? PKG_ROOTS[0].id : null;
  if (startPkg != null) {
    PKG_OPEN[startPkg] = true;
    for (var j = 0; j < PKG_ROOTS[0].children.length; j++) PKG_OPEN[PKG_ROOTS[0].children[j].id] = true;
  }
  renderPkgTree();
  showView('explorer');
  if (startPkg != null) openPackage(startPkg, true);
  toast('✅ Landkarte aufgelöst: „' + shortFileName(name1) + '“ ist wieder das einzige geladene Modell.'
    + (pending > 0 ? ' Die ' + pending + ' vorgemerkte(n) Änderung(en) wurden verworfen.' : ''));
}

/* Umschalter Einzel-/Mehrfach-Modus */
function toggleMultiMode(on) {
  MULTI_MODE = !!on;
  var lab = el('multilabel');
  if (lab) lab.className = 'mmode' + (MULTI_MODE ? ' on' : '');
  var chk = el('multichk');
  if (chk) chk.checked = MULTI_MODE;
  /* Wurde zuvor ein Einzelmodell geladen, wird es Modell 1 der Landkarte */
  if (MULTI_MODE && DB && MODEL_N === 0) {
    MODEL_N = 1;
    MODEL_DBS[1] = DB;
    MODEL_FILES.push({ n: 1, name: (MODELLNAME || 'Modell 1'), pkg: Object.keys(PKG).length, diag: DIAGS.length, obj: Object.keys(OBJS).length, con: CONS.length });
    finalizeMerge(1);
    toast('Mehrfach-Modus aktiv: Das geladene Modell ist jetzt <b>M1</b>. Weitere Dateien werden zu einer gemeinsamen Landkarte verschmolzen.');
    renderMergeBar();
    return;
  }
  renderMergeBar();
  if (MULTI_MODE) {
    toast('Mehrfach-Modus aktiv. Wählen Sie mit <b>📂 Mehrere Architekturen verschmelzen</b> zwei oder mehr .qea-Dateien aus (oder ziehen Sie sie in das Feld). Gleichnamige Elemente gleichen Stereotyps werden zusammengeführt — so werden <b>modellübergreifende Zusammenhänge</b> sichtbar.');
    showUpHint('Mehrfach-Modus aktiv. Wählen Sie jetzt die Architekturdateien aus.');
    return;
  }
  if (!DB) return;
  toast('Mehrfach-Modus aus: Es wird wieder nur eine Datei geladen.');
}

function renderWarnbar() {
  var wb = el('warnbar');
  if (!wb) return;
  var need = ['t_object', 't_connector', 't_package', 't_diagram', 't_diagramobjects', 't_diagramlinks'];
  var labels = { t_object: 'Elemente (t_object)', t_connector: 'Beziehungen (t_connector)', t_package: 'Pakete (t_package)', t_diagram: 'Diagramme (t_diagram)', t_diagramobjects: 'Diagramm-Inhalte (t_diagramobjects)', t_diagramlinks: 'Diagramm-Links (t_diagramlinks)' };
  var missing = [], i, j;
  for (i = 0; i < MODEL_FILES.length; i++) {
    var db = MODEL_DBS[MODEL_FILES[i].n];
    if (!db) continue;
    for (j = 0; j < need.length; j++) {
      if (!db.hasTable(need[j])) { var s = labels[need[j]] + ' [M' + MODEL_FILES[i].n + ']'; if (missing.indexOf(s) < 0) missing.push(s); }
    }
  }
  if (!missing.length) { wb.style.display = 'none'; wb.innerHTML = ''; return; }
  wb.innerHTML = '⚠ Hinweis: In mindestens einer Datei fehlen EA-Kerntabellen — fehlend: ' + esc(missing.join(', ')) + '. Die Auswertung läuft; einzelne Bereiche können eingeschränkt sein.';
  wb.style.display = 'block';
}

function detectViewpointPrefix(nm) {
  /* Erkennt sowohl "C1 : ...", "C1:S1 : ..." (-> C1-S1), "L4-P4 : ..." als auch Paketnamen */
  var m = String(nm || '').match(/^([A-Za-z]+[0-9]*(?:[\-:][A-Za-z]+[0-9]+)?)\s*:/);
  if (!m) return '';
  var p = m[1].replace(':', '-');
  if (ADMBW_DATA && ADMBW_DATA.vp && ADMBW_DATA.vp[p]) return p;
  /* Case-insensitive Abgleich gegen ADMBW_DATA.vp */
  for (var k in ADMBW_DATA.vp) {
    if (ADMBW_DATA.vp.hasOwnProperty(k) && k.toLowerCase() === p.toLowerCase()) return k;
  }
  return m[1];
}

function buildModel() {
  /* Pakete werden vom Aufrufer geleert (Einzelmodus: resetModelData();
     Mehrfach-Modus: die Landkarte der bereits geladenen Dateien bleibt bestehen). */

  var rows = DB.rows('t_package');
  var i, r;
  for (i = 0; i < rows.length; i++) {
    r = rows[i];
    var pidRaw = qcol(r, 'Package_ID');
    if (pidRaw == null) continue;
    var pid = pkgKey(pidRaw);
    var pnm = norm(qcol(r, 'Name')) || ('Paket ' + pidRaw);
    PKG[pid] = {
      id: pid,
      localId: pidRaw,
      m: MODEL_N,
      nameBase: pnm,
      name: (MULTI_MODE && MODEL_N > 1 ? '<<M' + MODEL_N + '>> ' + pnm : pnm),
      parent: (qcol(r, 'Parent_ID') || 0) ? pkgKey(qcol(r, 'Parent_ID')) : 0,
      tpos: parseInt(qcol(r, 'TPos'), 10) || 0,
      notes: cleanNote(qcol(r, 'Notes')),
      children: [],
      diags: [],
      objs: [],
      allDiagsCount: 0,
      allObjsCount: 0,
      path: '',
      pathIds: []
    };
  }

  /* Baum verknüpfen — children/roots werden bei JEDEM Aufruf frisch aufgebaut.
     Im Mehrfach-Modus wächst die Landkarte (PKG/OBJS akkumulieren), aber der
     Baum darf nicht doppelt verknüpft werden (alte children/roots sonst verwaist). */
  for (var kk in PKG) {
    if (PKG.hasOwnProperty(kk)) PKG[kk].children = [];
  }
  PKG_ROOTS.length = 0;
  for (var k in PKG) {
    if (!PKG.hasOwnProperty(k)) continue;
    var pk = PKG[k];
    if (pk.parent && PKG[pk.parent] && pk.parent !== pk.id) {
      PKG[pk.parent].children.push(pk);
    } else {
      PKG_ROOTS.push(pk);
    }
  }
  function sortPkgs(list) {
    list.sort(function (a, b) {
      if (a.tpos !== b.tpos) return a.tpos - b.tpos;
      return a.name.localeCompare(b.name, 'de');
    });
    for (var j = 0; j < list.length; j++) sortPkgs(list[j].children);
  }
  sortPkgs(PKG_ROOTS);

  function buildPkgPaths(node, ancestryNames, ancestryIds) {
    var names = ancestryNames.concat([node.nameBase || node.name]);
    var ids = ancestryIds.concat([node.id]);
    node.path = names.join(' / ');
    node.shortPath = names.slice(-3).join(' / ');
    node.pathIds = ids;
    for (var j = 0; j < node.children.length; j++) {
      buildPkgPaths(node.children[j], names, ids);
    }
  }
  for (i = 0; i < PKG_ROOTS.length; i++) buildPkgPaths(PKG_ROOTS[i], [], []);

  /* Elemente aufbauen (Kennungen ab Modell 2 eindeutig, siehe keyFor) */
  rows = DB.rows('t_object');
  for (i = 0; i < rows.length; i++) {
    r = rows[i];
    var oidRaw = qcol(r, 'Object_ID');
    if (oidRaw == null) continue;
    var oidV = objKey(oidRaw);
    var opkg = pkgKey(qcol(r, 'Package_ID'));
    var pObj = PKG[opkg];
    var oItem = {
      id: oidV,
      localId: oidRaw,
      guid: norm(qcol(r, 'ea_guid')),
      name: norm(qcol(r, 'Name')),
      st: norm(qcol(r, 'Stereotype')),
      alias: norm(qcol(r, 'Alias')),
      note: cleanNote(qcol(r, 'Note')),
      pkgId: opkg,
      pkg: pObj ? (pObj.shortPath || pObj.path) : '',
      pkgFull: pObj ? pObj.path : '',
      type: qcol(r, 'Object_Type'),
      m: MODEL_N
    };
    OBJS[oidV] = oItem;
    if (pObj && oItem.type !== 'Boundary' && !/^proxyconn?ector$/i.test(oItem.st)) {
      pObj.objs.push(oItem);
    }
  }

  rows = DB.rows('t_connector');
  for (i = 0; i < rows.length; i++) {
    r = rows[i];
    var cidRaw = qcol(r, 'Connector_ID');
    CONS.push({
      id: connKey(cidRaw),
      localId: cidRaw,
      name: norm(qcol(r, 'Name')),
      st: norm(qcol(r, 'Stereotype')),
      type: norm(qcol(r, 'Connector_Type')),
      a: objKey(qcol(r, 'Start_Object_ID')),
      b: objKey(qcol(r, 'End_Object_ID'))
    });
  }

  rows = DB.rows('t_diagramobjects');
  for (i = 0; i < rows.length; i++) {
    r = rows[i];
    var didRaw = qcol(r, 'Diagram_ID');
    var doidRaw = qcol(r, 'Object_ID');
    if (didRaw == null) continue;
    var dk = diagKey(didRaw);
    if (!DIAGOBJ[dk]) DIAGOBJ[dk] = [];
    DIAGOBJ[dk].push({
      oid: objKey(doidRaw),
      l: qcol(r, 'RectLeft'),
      t: qcol(r, 'RectTop'),
      r: qcol(r, 'RectRight'),
      b: qcol(r, 'RectBottom'),
      seq: qcol(r, 'Sequence') || 0
    });
    if (doidRaw != null) {
      var sk = objKey(doidRaw);
      if (!OBJ_DIAGS[sk]) OBJ_DIAGS[sk] = [];
      if (OBJ_DIAGS[sk].indexOf(dk) < 0) OBJ_DIAGS[sk].push(dk);
    }
  }

  rows = DB.rows('t_diagramlinks');
  for (i = 0; i < rows.length; i++) {
    r = rows[i];
    var hid = qcol(r, 'Hidden');
    if (hid === 1 || hid === '1') continue;
    var dgid = qcol(r, 'DiagramID');
    if (dgid == null) dgid = qcol(r, 'Diagram_ID');
    if (dgid == null) continue;
    var clid = qcol(r, 'ConnectorID');
    if (clid == null) clid = qcol(r, 'Connector_ID');
    var dlk = diagKey(dgid);
    if (!DIAGLINK[dlk]) DIAGLINK[dlk] = [];
    DIAGLINK[dlk].push({ cid: connKey(clid) });
  }

  rows = DB.rows('t_diagram');
  for (i = 0; i < rows.length; i++) {
    r = rows[i];
    var dIdRaw = qcol(r, 'Diagram_ID');
    var dId = diagKey(dIdRaw);
    var nm = norm(qcol(r, 'Name'));
    var dpkgId = pkgKey(qcol(r, 'Package_ID'));
    var dpkg = PKG[dpkgId];
    var pref = detectViewpointPrefix(nm);
    /* Falls kein Präfix im Namen, prüfen ob das Elternpaket exakt wie ein Viewpoint heißt (z. B. "P2", "L4-P4") */
    if (!pref && dpkg && ADMBW_DATA.vp[dpkg.nameBase || dpkg.name]) pref = dpkg.nameBase || dpkg.name;
    var dobjs = DIAGOBJ[dId] || [];
    var dlinks = DIAGLINK[dId] || [];
    var dItem = {
      id: dId,
      localId: dIdRaw,
      name: (MULTI_MODE && MODEL_N > 1 ? '<<M' + MODEL_N + '>> ' : '') + (nm || ('Diagramm ' + dIdRaw)),
      nameBase: nm || ('Diagramm ' + dIdRaw),
      pkgId: dpkgId,
      m: MODEL_N,
      pkgPath: dpkg ? (dpkg.shortPath || dpkg.path) : '',
      pkgFull: dpkg ? dpkg.path : '',
      rootPkgName: (dpkg && dpkg.pathIds && dpkg.pathIds.length > 1 && PKG[dpkg.pathIds[1]]) ? PKG[dpkg.pathIds[1]].name : (dpkg ? dpkg.name : ''),
      type: norm(qcol(r, 'Diagram_Type')) || 'Custom',
      notes: cleanNote(qcol(r, 'Notes')),
      prefix: pref,
      objCount: dobjs.length,
      linkCount: dlinks.length
    };
    DIAGS.push(dItem);
    DIAGMAP[dId] = dItem;
    if (dpkg) dpkg.diags.push(dItem);
  }

  /* Merken des Sicht-Diagramms (Mehrfach-Modus: globales ID wird auf <<M n>>-ID umgestellt) */
  G.built = false;

  rows = DB.rows('t_objectproperties');
  for (i = 0; i < rows.length; i++) {
    r = rows[i];
    var toid = qcol(r, 'Object_ID');
    if (toid == null) continue;
    var key = objKey(toid);
    if (!TAGS[key]) TAGS[key] = [];
    TAGS[key].push({
      p: norm(qcol(r, 'Property')),
      v: cleanNote(qcol(r, 'Value')),
      n: cleanNote(qcol(r, 'Notes'))
    });
  }

  var cmap = {};
  for (i = 0; i < CONS.length; i++) cmap[String(CONS[i].id)] = CONS[i];
  DB._cmap = cmap;
  CONNMAP = cmap;   /* Nachschlagetabelle global über alle geladenen Modelle */

  CONNCOUNT = {};
  for (i = 0; i < CONS.length; i++) {
    var ca = String(CONS[i].a), cb = String(CONS[i].b);
    CONNCOUNT[ca] = (CONNCOUNT[ca] || 0) + 1;
    CONNCOUNT[cb] = (CONNCOUNT[cb] || 0) + 1;
  }

  /* Mehrfach-Modus: Elemente fusionieren (Name + Stereotype) und Referenzen umbiegen */
  if (MULTI_MODE) finalizeMerge(MODEL_N);
  recountPkgs();
}

/* ================================================================
   Kennungen im Mehrfach-Modus (siehe keyFor oben):
   m2_o101 (Element), m2_p7 (Paket), m2_d5 (Sicht), m2_c33 (Beziehung).
   Modell 1 behält seine Original-Kennungen unverändert.
   ================================================================ */
function P_G(id) { return id; }   /* Kompatibilitätshülle: Kennungen sind bereits endgültig */
function P_LOCAL(g) {
  var p = parseG(g);
  return p ? String(p.l) : String(g);
}
function parseG(g) {
  var m = /^m(\d+)_([opdc])(\d+)$/.exec(String(g));
  return m ? { n: Number(m[1]), t: m[2], l: Number(m[3]) } : null;
}
/* Kennungen für eine Anzeige entschlüsseln */
function dName(oid) {
  oid = String(oid || '');
  var p = parseG(oid);
  if (!p) return oid;
  var o = OBJS[oid];
  return (o && o.name) ? o.name : ('<<M' + p.n + '>> #' + p.l);
}
function dKey(oid) {
  var o = OBJS[String(oid || '')];
  return o ? (o.nameBase || o.name) : String(oid || '');
}

/* Zählwerte der Paketbäume neu aufbauen (nach jedem Aufbau und nach der Fusion) */
function recountPkgs() {
  function recount(node) {
    var dc = node.diags.length, oc = node.objs.length, z;
    for (z = 0; z < node.children.length; z++) { recount(node.children[z]); dc += node.children[z].allDiagsCount; oc += node.children[z].allObjsCount; }
    node.allDiagsCount = dc; node.allObjsCount = oc;
  }
  for (var i = 0; i < PKG_ROOTS.length; i++) recount(PKG_ROOTS[i]);
}

/* Hilfsfunktion: Alle Elemente und Beziehungen einer einzelnen Sicht (Diagramm) ermitteln */
function getDiagramData(diagId) {
  var dobjs = DIAGOBJ[diagId] || [];
  var dlinks = DIAGLINK[diagId] || [];
  var elSet = {}, els = [], rels = [], relAdded = {}, i;
  for (i = 0; i < dobjs.length; i++) {
    var o = OBJS[dobjs[i].oid];
    if (!o || o.type === 'Boundary' || /^proxyconn?ector$/i.test(o.st)) continue;
    if (!elSet[o.id]) { elSet[o.id] = true; els.push(o); }
  }
  var cmap = CONNMAP;
  for (i = 0; i < dlinks.length; i++) {
    var cn = cmap[dlinks[i].cid];
    if (cn && !relAdded[cn.id]) {
      relAdded[cn.id] = true;
      rels.push(cn);
    }
  }
  /* Falls t_diagramlinks leer ist, alle Beziehungen zwischen den platzierten Elementen ergänzen */
  for (i = 0; i < CONS.length; i++) {
    var c = CONS[i];
    if (!relAdded[c.id] && elSet[c.a] && elSet[c.b]) {
      relAdded[c.id] = true;
      rels.push(c);
    }
  }
  els.sort(function (a, b) { return (a.st || '').localeCompare(b.st || '', 'de') || (a.name || '').localeCompare(b.name || '', 'de'); });
  return { els: els, rels: rels };
}

/* Hilfsfunktion: Alle Diagramme, Elemente & Beziehungen eines Pakets (wahlweise inkl. Unterpakete) */
function getPackageData(pkgId, includeSub) {
  var root = PKG[pkgId];
  if (!root) return { diags: [], els: [], rels: [] };
  var diags = [], els = [], elSet = {}, i;
  function walk(node) {
    for (var d = 0; d < node.diags.length; d++) diags.push(node.diags[d]);
    for (var o = 0; o < node.objs.length; o++) {
      var obj = node.objs[o];
      if (!elSet[obj.id]) { elSet[obj.id] = true; els.push(obj); }
    }
    if (includeSub) {
      for (var c = 0; c < node.children.length; c++) walk(node.children[c]);
    }
  }
  walk(root);
  /* Auch Elemente hinzunehmen, die auf den Diagrammen dieses Pakets platziert sind */
  for (i = 0; i < diags.length; i++) {
    var dobjs = DIAGOBJ[diags[i].id] || [];
    for (var j = 0; j < dobjs.length; j++) {
      var xo = OBJS[dobjs[j].oid];
      if (xo && xo.type !== 'Boundary' && !/^proxyconn?ector$/i.test(xo.st) && !elSet[xo.id]) {
        elSet[xo.id] = true;
        els.push(xo);
      }
    }
  }
  var rels = [];
  for (i = 0; i < CONS.length; i++) {
    var cn = CONS[i];
    if (elSet[cn.a] || elSet[cn.b]) rels.push(cn);
  }
  els.sort(function (a, b) { return (a.st || '').localeCompare(b.st || '', 'de') || (a.name || '').localeCompare(b.name || '', 'de'); });
  return { diags: diags, els: els, rels: rels };
}

/* ---------- Schnell-Einstieg / Kompass unter dem Suchfeld ---------- */
function renderQuickBar() {
  var qb = el('quickbar');
  if (!qb) return;
  var h = [], i;

  /* 1. Einstiegs-/Übersichts-Diagramme finden */
  var heroDiags = [];
  for (i = 0; i < DIAGS.length; i++) {
    var d = DIAGS[i];
    if (/startseite|overview|übersicht|introduction|gesamtgefüge|projects|architekturauftrag/i.test(d.name)) {
      heroDiags.push(d);
    }
  }
  if (!heroDiags.length) heroDiags = DIAGS.slice(0, 5);
  else heroDiags = heroDiags.slice(0, 6);

  if (heroDiags.length) {
    h.push('<div class="qb-row"><span class="qb-lbl">🌟 Einstiegs-Sichten:</span>');
    for (i = 0; i < heroDiags.length; i++) {
      h.push('<span class="gchip" style="background:#FEF3C7;color:#92400E;border-color:#FCD34D" onclick="openDiagramView(' + heroDiags[i].id + ')" title="Sicht direkt öffnen: ' + esc(heroDiags[i].pkgFull) + '">🖼️ ' + esc(shortLabel(heroDiags[i].name, 38)) + '</span>');
    }
    h.push('</div>');
  }

  /* 2. Hauptpakete (Kinder des Root-Pakets oder Root-Pakete) */
  var topPkgs = (PKG_ROOTS.length === 1 && PKG_ROOTS[0].children.length) ? PKG_ROOTS[0].children : PKG_ROOTS;
  if (topPkgs.length) {
    h.push('<div class="qb-row"><span class="qb-lbl">📁 Hauptbereiche (Pakete):</span>');
    for (i = 0; i < topPkgs.length && i < 8; i++) {
      var p = topPkgs[i];
      h.push('<span class="gchip" onclick="showView(\'explorer\');openPackage(' + p.id + ')" title="Paket im Explorer öffnen">' + esc(p.name) + ' <em>(' + diagN(p.allDiagsCount) + ' · ' + elN(p.allObjsCount) + ')</em></span>');
    }
    h.push('</div>');
  }

  /* 3. Häufigste Elementtypen */
  var tc = {}, types = [];
  for (var oid in OBJS) {
    if (!OBJS.hasOwnProperty(oid)) continue;
    var st = OBJS[oid].st;
    if (!st || /^proxyconn?ector$/i.test(st)) continue;
    tc[st] = (tc[st] || 0) + 1;
  }
  for (var k in tc) if (tc.hasOwnProperty(k)) types.push(k);
  types.sort(function (a, b) { return tc[b] - tc[a]; });
  if (types.length) {
    h.push('<div class="qb-row"><span class="qb-lbl">🏷️ Häufigste Elementtypen:</span>');
    for (i = 0; i < types.length && i < 10; i++) {
      var t = types[i];
      h.push('<span class="gchip" onclick="fillSearch(\'' + esc(t).replace(/'/g, '&#39;') + '\')" title="Nach «' + esc(t) + '» suchen"><i style="background:' + stColor(t) + '"></i>' + esc(t) + ' <em>' + tc[t] + '</em></span>');
    }
    h.push('</div>');
  }

  qb.innerHTML = '<summary>ℹ️ Hilfe &amp; Schnell-Einstieg — Einstiegs-Sichten, Hauptpakete, häufigste Elementtypen &amp; Kurzanleitung</summary><div style="margin-top:7px;display:flex;flex-direction:column;gap:6px">' + h.join('') +
    '<ol>' +
    '<li><b>Direkt suchen (oben):</b> Begriff eingeben → sofort Treffer in <b>🖼️ Sichten</b>, <b>📁 Paketen</b> und <b>📦 Elementen</b>.</li>' +
    '<li><b>Durch Pakete &amp; Sichten klicken:</b> Im Reiter <b>„🧭 Erkunden“</b> links durch den Ordnerbaum navigieren — rechts erscheinen Unterpakete, Sichten (Diagramme) und Elemente.</li>' +
    '<li><b>Analysieren:</b> Sichten im Reiter <b>„🕸️ Graph“</b> als Netzwerk erkunden; im Reiter <b>„🔗 Verbindungen“</b> nachweisen, wie zwei Elemente zusammenhängen (Pfadanalyse).</li>' +
    '<li><b>Exportieren:</b> Jede Sicht, jedes Paket und jeden Pfad mit einem Klick als <b>📸 PNG</b> oder <b>📊 Excel (.xlsx)</b> sichern — die Buttons stehen direkt an der jeweiligen Ansicht.</li>' +
    '</ol></div>';
}

/* ================================================================
   ANSICHT 1: INTERAKTIVER PAKET- & STRUKTUR-EXPLORER
   ================================================================ */
function renderPkgTree() {
  var host = el('pkgtree');
  if (!host) return;
  var q = (el('treefilter') ? el('treefilter').value : '').trim().toLowerCase();

  function matchesFilter(node) {
    if (!q) return true;
    if (node.name.toLowerCase().indexOf(q) >= 0) return true;
    for (var d = 0; d < node.diags.length; d++) {
      if (node.diags[d].name.toLowerCase().indexOf(q) >= 0) return true;
    }
    for (var i = 0; i < node.children.length; i++) {
      if (matchesFilter(node.children[i])) return true;
    }
    return false;
  }

  var h = [];
  function renderNode(node) {
    if (!matchesFilter(node)) return;
    var hasKids = node.children.length > 0;
    var isOpen = q ? true : !!PKG_OPEN[node.id];
    var isAct = (CURPKG === node.id && CURVIEW === 'explorer');
    h.push('<div class="tnode">');
    h.push('<div class="trow' + (isAct ? ' active' : '') + '" onclick="openPackage(' + node.id + ')">');
    if (hasKids) {
      h.push('<span class="ttog" onclick="event.stopPropagation();togglePkgNode(' + node.id + ')">' + (isOpen ? '▾' : '▸') + '</span>');
    } else {
      h.push('<span class="ttog">·</span>');
    }
    h.push('<span class="tname" title="' + esc(node.path) + '">📁 ' + esc(node.name) + '</span>');
    if (node.allDiagsCount > 0) h.push('<span class="tbadge diag" title="Enthaltene Sichten / Diagramme">🖼️ ' + fmt(node.allDiagsCount) + '</span>');
    if (node.allObjsCount > 0) h.push('<span class="tbadge" title="Enthaltene Elemente">' + fmt(node.allObjsCount) + '</span>');
    h.push('</div>');
    if (hasKids && isOpen) {
      h.push('<div class="tchildren">');
      for (var i = 0; i < node.children.length; i++) renderNode(node.children[i]);
      h.push('</div>');
    }
    h.push('</div>');
  }
  for (var r = 0; r < PKG_ROOTS.length; r++) renderNode(PKG_ROOTS[r]);
  host.innerHTML = h.join('') || '<div class="hint">Keine passenden Pakete gefunden.</div>';
}

function togglePkgNode(pid) {
  PKG_OPEN[pid] = !PKG_OPEN[pid];
  renderPkgTree();
}

function expandAllPkgs(open) {
  for (var k in PKG) {
    if (PKG.hasOwnProperty(k)) PKG_OPEN[k] = !!open;
  }
  if (!open && PKG_ROOTS.length) PKG_OPEN[PKG_ROOTS[0].id] = true;
  renderPkgTree();
}

function togglePkgDeep(cb) {
  PKG_DEEP = !!cb.checked;
  if (CURPKG != null) openPackage(CURPKG, true);
}

function renderDistBar(els, targetContainerId) {
  if (!els || !els.length) return '';
  var tc = {}, types = [], i;
  for (i = 0; i < els.length; i++) {
    var st = els[i].st || '(ohne Stereotyp)';
    tc[st] = (tc[st] || 0) + 1;
  }
  for (var k in tc) if (tc.hasOwnProperty(k)) types.push(k);
  types.sort(function (a, b) { return tc[b] - tc[a]; });
  var maxC = tc[types[0]] || 1;
  var h = [];
  h.push('<div class="dist-bar"><div class="dist-title"><span>📊 Verteilung der genutzten Elemente (' + types.length + ' Typen, ' + els.length + ' gesamt — Klick filtert Tabelle):</span><a href="javascript:void(0)" onclick="filterByStereotype(\'\',\'' + targetContainerId + '\')" style="color:var(--bw-blue);text-decoration:none;font-weight:600">Alle zeigen</a></div><div class="dist-chips">');
  for (i = 0; i < types.length && i < 16; i++) {
    var t = types[i];
    var pct = Math.max(12, Math.round((tc[t] / maxC) * 100));
    h.push('<span class="dchip" onclick="filterByStereotype(\'' + esc(t).replace(/'/g, '&#39;') + '\',\'' + targetContainerId + '\')">');
    h.push('<i style="width:8px;height:8px;border-radius:50%;background:' + stColor(t) + ';display:inline-block"></i>');
    h.push('<span>' + esc(t) + '</span> <b>' + tc[t] + '</b>');
    h.push('<span class="dchip-bar"><span class="dchip-fill" style="width:' + pct + '%;background:' + stColor(t) + '"></span></span>');
    h.push('</span>');
  }
  h.push('</div></div>');
  return h.join('');
}

function filterByStereotype(st, containerId) {
  var wrap = el(containerId || 'vp-list') || document;
  var inp = wrap.querySelector('.vpfilter');
  if (inp) {
    inp.value = st === '(ohne Stereotyp)' ? '' : st;
    filterRows(inp);
  }
}

function openPackage(pid, stayInExplorer) {
  var pkg = PKG[pid];
  if (!pkg) return;
  CURPKG = pid;
  /* Pfad im Baum aufklappen */
  for (var i = 0; i < pkg.pathIds.length; i++) PKG_OPEN[pkg.pathIds[i]] = true;
  if (!stayInExplorer) showView('explorer');
  renderPkgTree();

  var pdata = getPackageData(pid, PKG_DEEP);
  CURDATA = { els: pdata.els, rels: pdata.rels, diags: pdata.diags };
  EXPCTX = { fname: 'Paket_' + pkg.name, kind: 'Paket (' + (PKG_DEEP ? 'inkl. Unterpakete' : 'nur direkt') + ')', label: 'Paket: ' + pkg.path };
  PRINTCTX = 'Paket: ' + pkg.path;
  G.mode = 'pkg'; G.root = null; G.built = false;
  VPMODE = 'list';

  var host = el('pkgmain');
  if (!host) return;
  if (el('vpbox')) el('vpbox').innerHTML = '';
  var h = [];

  /* Breadcrumb */
  h.push('<div class="crumb">');
  for (i = 0; i < pkg.pathIds.length; i++) {
    var anc = PKG[pkg.pathIds[i]];
    if (!anc) continue;
    if (i > 0) h.push(' <span>▸</span> ');
    if (i === pkg.pathIds.length - 1) h.push('<b>📁 ' + esc(anc.name) + '</b>');
    else h.push('<a href="javascript:openPackage(' + anc.id + ')">' + esc(anc.name) + '</a>');
  }
  h.push('</div>');

  h.push('<div class="kpis">' +
    '<span><b>' + pkgN(pkg.children.length) + '</b></span>' +
    '<span><b>' + diagN(pdata.diags.length) + '</b> (Diagramme)</span>' +
    '<span><b>' + elN(pdata.els.length) + '</b></span>' +
    '<span><b>' + relN(pdata.rels.length) + '</b></span>' +
    '</div>');
  if (pkg.notes) {
    if (pkg.notes.length > 180) {
      h.push('<details class="purpose" style="cursor:pointer"><summary><b>Paket-Beschreibung:</b> ' + esc(shortLabel(pkg.notes.replace(/\n+/g, ' '), 150)) + ' <span class="dim">(aufklappen)</span></summary><div style="margin-top:6px;white-space:pre-line">' + esc(pkg.notes) + '</div></details>');
    } else {
      h.push('<div class="purpose"><b>Paket-Beschreibung:</b> ' + esc(pkg.notes) + '</div>');
    }
  }

  /* Aktions- & Exportleiste */
  h.push('<div class="vp-actions">');
  h.push('<span class="vswitch">' +
    '<button id="btn-mode-list" class="on" onclick="setVPMode(\'list\')">☰ Paket-Inhalt (Sichten &amp; Elemente)</button>' +
    '<button id="btn-mode-graph" onclick="setVPMode(\'graph\')">◉ Paket im Graph visualisieren</button>' +
    '<label style="margin-left:8px;cursor:pointer;color:var(--ink);font-weight:600"><input type="checkbox" ' + (PKG_DEEP ? 'checked ' : '') + 'onchange="togglePkgDeep(this)"> Inkl. Unterpakete</label>' +
    '</span>');
  h.push('<span class="vedit">✏️ Bearbeiten: ' +
    '<button onclick="EDIT.pkgEdit(' + pid + ')" title="Paketname &amp; Beschreibung ändern">Paket</button>' +
    '<button onclick="EDIT.elNew(' + pid + ')" title="Neues Element in diesem Paket anlegen">＋ Element</button>' +
    '</span>');
  h.push('<span class="vexport">' +
    '<button class="exp-xls" onclick="exportCurrentXLSX()" title="Dieses Paket inkl. Elementen, Beziehungen &amp; Tagged Values als Excel (.xlsx) exportieren">📊 Excel (.xlsx)</button>' +
    '<button class="exp-png" onclick="exportCurrentPNG()" title="Schaubild oder Graph als PNG exportieren">📸 PNG</button>' +
    '<button onclick="exportElementsCSV()">⤓ CSV</button>' +
    '<button onclick="exportPDF()">🖨 PDF</button>' +
    '</span>');
  h.push('</div>');

  h.push('<div id="vp-list">');

  /* 1. Unterpakete als Ordner-Kacheln */
  if (pkg.children.length) {
    h.push('<h3>Unterpakete (' + pkg.children.length + ')</h3>');
    h.push('<div class="subpkg-grid">');
    for (i = 0; i < pkg.children.length; i++) {
      var ch = pkg.children[i];
      h.push('<div class="pkg-card" onclick="openPackage(' + ch.id + ')">');
      h.push('<div class="pkg-card-title">📁 ' + esc(ch.name) + '</div>');
      h.push('<div class="pkg-card-meta"><b>' + diagN(ch.allDiagsCount) + '</b> &nbsp;·&nbsp; <b>' + elN(ch.allObjsCount) + '</b>' + (ch.children.length ? ' &nbsp;·&nbsp; ' + pkgN(ch.children.length) : '') + '</div>');
      h.push('</div>');
    }
    h.push('</div>');
  }

  /* 2. Vorhandene Sichten (Diagramme) in diesem Paket */
  h.push('<h3>Vorhandene Sichten / Diagramme in diesem Bereich (' + pdata.diags.length + ')</h3>');
  if (!pdata.diags.length) {
    h.push('<div class="hint">Keine Diagramme in diesem Paket vorhanden.</div>');
  } else if (pdata.diags.length <= 4) {
    /* Direkt interaktive Schaubilder mit Einzel-Export (PNG & Excel) rendern! */
    h.push('<div class="diaglist">');
    for (i = 0; i < pdata.diags.length; i++) {
      var dg = pdata.diags[i];
      h.push('<div class="diagbox">');
      h.push('<div class="diagbox-hdr">' +
        '<div><span class="diagtitle">🖼️ ' + esc(dg.name) + '</span><span class="diagsub">(' + esc(dg.pkgPath) + ' · ' + dg.objCount + ' Elemente)</span></div>' +
        '<div class="diagtools">' +
          '<button class="btn-sm pri" onclick="openDiagramView(' + dg.id + ')">🔍 Einzel-Sicht öffnen</button>' +
          '<button class="btn-sm" onclick="openDiagramView(' + dg.id + ', \'graph\')">◉ Im Graph</button>' +
          '<button class="btn-sm amber" onclick="exportDiagramPNG(' + dg.id + ')">📸 Sicht als PNG</button>' +
          '<button class="btn-sm green" onclick="exportDiagramXLSX(' + dg.id + ')">📊 Sicht als Excel (.xlsx)</button>' +
        '</div></div>');
      h.push('<div class="svgwrap" id="diag-' + dg.id + '"></div>');
      h.push('</div>');
    }
    h.push('</div>');
  } else {
    /* Übersichtliche Sichten-Karten-Galerie (mit Direkt-Export pro Sicht!) */
    h.push('<div class="diag-cards">');
    for (i = 0; i < pdata.diags.length && i < 60; i++) {
      var d2 = pdata.diags[i];
      h.push('<div class="dcard">');
      h.push('<div>');
      h.push('<div class="dcard-title" onclick="openDiagramView(' + d2.id + ')">🖼️ ' + esc(d2.name) + '</div>');
      h.push('<div class="dcard-path">📁 ' + esc(d2.pkgPath) + '</div>');
      h.push('<div class="dcard-badges">' +
        '<span class="b b-els">' + d2.objCount + ' Elemente</span>' +
        '<span class="b b-rel">' + d2.linkCount + ' Kanten</span>' +
        (d2.prefix ? '<span class="b b-diag">' + esc(d2.prefix) + '</span>' : '<span class="b b-none">' + esc(d2.type) + '</span>') +
        '</div>');
      h.push('</div>');
      h.push('<div class="dcard-acts">' +
        '<button class="btn-sm pri" onclick="openDiagramView(' + d2.id + ')">🔍 Sicht öffnen</button>' +
        '<button class="btn-sm" onclick="openDiagramView(' + d2.id + ', \'graph\')" title="Diese Sicht als Graph visualisieren">◉ Graph</button>' +
        '<button class="btn-sm amber" onclick="exportDiagramPNG(' + d2.id + ')" title="Diese Sicht direkt als PNG herunterladen">📸 PNG</button>' +
        '<button class="btn-sm green" onclick="exportDiagramXLSX(' + d2.id + ')" title="Diese Sicht direkt als Excel (.xlsx) herunterladen">📊 Excel</button>' +
        '</div>');
      h.push('</div>');
    }
    h.push('</div>');
    if (pdata.diags.length > 60) {
      h.push('<div class="hint">… ' + (pdata.diags.length - 60) + ' weitere Sichten in Unterpaketen — klicken Sie links im Baum auf ein Unterpaket oder nutzen Sie den Reiter „🖼️ Sichten“.</div>');
    }
  }

  /* 3. Verteilung der genutzten Elementtypen */
  h.push(renderDistBar(pdata.els, 'vp-list'));

  /* 4. Elemente- & Beziehungstabellen */
  h.push('<div class="vpfilterwrap"><input class="vpfilter" placeholder="🔍 Elemente &amp; Beziehungen in diesem Paket filtern (Name, Alias, Stereotype) …" oninput="filterRows(this)"></div>');
  h.push('<h3>Elemente in diesem Paket (' + pdata.els.length + ')</h3>');
  if (!pdata.els.length) {
    h.push('<div class="hint">Keine Elemente in diesem Paket.</div>');
  } else {
    h.push('<table class="data"><thead><tr><th>Name</th><th>Stereotype</th><th>Alias</th><th>Paketpfad</th><th>Sichten</th><th>Verb.</th></tr></thead><tbody>');
    for (i = 0; i < pdata.els.length && i < 250; i++) {
      var o = pdata.els[i];
      var dc = (OBJ_DIAGS[String(o.id)] || []).length;
      h.push('<tr class="clickable" onclick="openElement(\'' + o.id + '\')">' +
        '<td><b>' + esc(o.name || '(ohne Name)') + '</b></td>' +
        '<td><code>' + esc(o.st || '–') + '</code></td>' +
        '<td>' + esc(o.alias) + '</td>' +
        '<td class="dim">' + esc(o.pkg) + '</td>' +
        '<td>' + (dc ? '<span class="b b-diag">' + dc + ' Sicht(en)</span>' : '–') + '</td>' +
        '<td><span class="b b-rel">' + (CONNCOUNT[String(o.id)] || 0) + '</span></td>' +
        '</tr>');
    }
    h.push('</tbody></table>');
    if (pdata.els.length > 250) h.push('<div class="hint">… ' + (pdata.els.length - 250) + ' weitere Elemente (vollständig im Excel-/CSV-Export).</div>');
  }

  h.push('</div>'); /* /vp-list */
  h.push('<div class="vp-graph" id="vp-graph" style="display:none"></div>');

  host.innerHTML = h.join('');
  if (pdata.diags.length > 0 && pdata.diags.length <= 4) {
    for (i = 0; i < pdata.diags.length; i++) {
      renderDiagram(pdata.diags[i], el('diag-' + pdata.diags[i].id));
    }
  }
}

/* ================================================================
   ANSICHT 2: KATALOG ALLER VORHANDENEN SICHTEN (DIAGRAMME)
   ================================================================ */
function renderDiagsCatalog() {
  var host = el('diagsbox');
  if (!host) return;
  var i, d;
  var rootNames = {}, rlist = [];
  for (i = 0; i < DIAGS.length; i++) {
    var rn = DIAGS[i].rootPkgName || 'Allgemein';
    rootNames[rn] = (rootNames[rn] || 0) + 1;
  }
  for (var k in rootNames) if (rootNames.hasOwnProperty(k)) rlist.push(k);
  rlist.sort();

  var h = [];
  h.push('<h2>🖼️ Alle vorhandenen Sichten (Diagramme) im Modell (' + DIAGS.length + ')</h2>');
  h.push('<div class="purpose">Hier sehen Sie <b>alle tatsächlich in der QEA-Datei modellierten Sichten (Diagramme)</b> — unabhängig davon, ob sie nach dem generischen ADMBw-Schema benannt sind oder projektspezifische Namen tragen. Jede Sicht kann direkt geöffnet, im Graphen analysiert oder als <b>PNG / Excel (.xlsx)</b> exportiert werden.</div>');

  h.push('<div class="vp-actions" style="justify-content:flex-start;gap:10px">');
  h.push('<input id="df-q" class="vpfilter" style="max-width:360px" placeholder="🔍 Sicht suchen (Name, Paket, Präfix) …" value="' + esc(DIAG_FILTER.q) + '" oninput="updateDiagCatalogFilter()">');
  h.push('<select id="df-pkg" style="padding:7px 10px;border:1px solid #C6D2DA;border-radius:6px;font-size:12.5px" onchange="updateDiagCatalogFilter()">');
  h.push('<option value="">📁 Alle Hauptpakete (' + DIAGS.length + ')</option>');
  for (i = 0; i < rlist.length; i++) {
    var sel = DIAG_FILTER.pkg === rlist[i] ? ' selected' : '';
    h.push('<option value="' + esc(rlist[i]) + '"' + sel + '>' + esc(rlist[i]) + ' (' + rootNames[rlist[i]] + ')</option>');
  }
  h.push('</select>');

  var layers = [
    ['all', 'Alle Schichten'],
    ['custom', 'Ohne Standard-Präfix / Frei benannt'],
    ['C', 'Konzepte (C)'],
    ['S', 'Dienste (S)'],
    ['L', 'Logisch (L)'],
    ['P', 'Physisch (P)'],
    ['A', 'Grundlagen (A)'],
    ['R', 'Anforderungen (R)'],
    ['B', 'Brücken (C1-S1 / L4-P4)']
  ];
  h.push('<select id="df-layer" style="padding:7px 10px;border:1px solid #C6D2DA;border-radius:6px;font-size:12.5px" onchange="updateDiagCatalogFilter()">');
  for (i = 0; i < layers.length; i++) {
    var lsel = DIAG_FILTER.layer === layers[i][0] ? ' selected' : '';
    h.push('<option value="' + layers[i][0] + '"' + lsel + '>📐 ' + layers[i][1] + '</option>');
  }
  h.push('</select>');
  h.push('</div>');

  h.push('<div id="diags-grid-list"></div>');
  host.innerHTML = h.join('');
  updateDiagCatalogFilter();
}

function updateDiagCatalogFilter() {
  var qEl = el('df-q'), pEl = el('df-pkg'), lEl = el('df-layer');
  if (qEl) DIAG_FILTER.q = qEl.value.trim().toLowerCase();
  if (pEl) DIAG_FILTER.pkg = pEl.value;
  if (lEl) DIAG_FILTER.layer = lEl.value;

  var filtered = [], i, d;
  for (i = 0; i < DIAGS.length; i++) {
    d = DIAGS[i];
    if (DIAG_FILTER.pkg && d.rootPkgName !== DIAG_FILTER.pkg) continue;
    if (DIAG_FILTER.layer !== 'all') {
      var pr = d.prefix || '';
      if (DIAG_FILTER.layer === 'custom') {
        if (pr && ADMBW_DATA.vp[pr]) continue;
      } else if (DIAG_FILTER.layer === 'B') {
        if (pr.indexOf('-') < 0) continue;
      } else {
        if (pr.indexOf('-') >= 0 || pr.charAt(0).toUpperCase() !== DIAG_FILTER.layer) continue;
      }
    }
    if (DIAG_FILTER.q && (d.name + ' ' + d.pkgFull + ' ' + d.prefix + ' ' + d.type).toLowerCase().indexOf(DIAG_FILTER.q) < 0) continue;
    filtered.push(d);
  }

  var box = el('diags-grid-list');
  if (!box) return;
  if (!filtered.length) {
    box.innerHTML = '<div class="hint">Keine Sichten für diese Filterkombination gefunden.</div>';
    return;
  }
  var h = [];
  h.push('<div class="dim" style="margin-bottom:8px">Zeige <b>' + filtered.length + '</b> von ' + DIAGS.length + ' vorhandenen Sichten:</div>');
  h.push('<div class="diag-cards">');
  for (i = 0; i < filtered.length; i++) {
    d = filtered[i];
    h.push('<div class="dcard">');
    h.push('<div>');
    h.push('<div class="dcard-title" onclick="openDiagramView(' + d.id + ')">🖼️ ' + esc(d.name) + '</div>');
    h.push('<div class="dcard-path">📁 <a href="javascript:openPackage(' + d.pkgId + ')" style="color:var(--bw-mid);text-decoration:none">' + esc(d.pkgFull || d.pkgPath) + '</a></div>');
    h.push('<div class="dcard-badges">' +
      '<span class="b b-els">' + d.objCount + ' Elemente</span>' +
      '<span class="b b-rel">' + d.linkCount + ' Kanten</span>' +
      (d.prefix ? '<span class="b b-diag">Viewpoint ' + esc(d.prefix) + '</span>' : '<span class="b b-none">Typ: ' + esc(d.type) + '</span>') +
      '</div>');
    h.push('</div>');
    h.push('<div class="dcard-acts">' +
      '<button class="btn-sm pri" onclick="openDiagramView(' + d.id + ')">🔍 Sicht öffnen</button>' +
      '<button class="btn-sm" onclick="openDiagramView(' + d.id + ', \'graph\')">◉ Graph</button>' +
      '<button class="btn-sm amber" onclick="exportDiagramPNG(' + d.id + ')">📸 PNG</button>' +
      '<button class="btn-sm green" onclick="exportDiagramXLSX(' + d.id + ')">📊 Excel</button>' +
      '</div>');
    h.push('</div>');
  }
  h.push('</div>');
  box.innerHTML = h.join('');
}

/* ================================================================
   EINZEL-SICHT-ANSICHT (openDiagramView) — Diagramm + Graph + PNG/Excel
   ================================================================ */
function openDiagramView(diagId, mode) {
  var diag = DIAGMAP[diagId];
  if (!diag) return;
  CURDIAG = diagId;
  var d = el('gsres'); if (d) d.style.display = 'none';

  var ddata = getDiagramData(diagId);
  CURDATA = { els: ddata.els, rels: ddata.rels, diags: [diag] };
  EXPCTX = { fname: 'Sicht_' + diag.name, kind: 'Einzel-Sicht (Diagramm)', label: 'Sicht: ' + diag.name };
  PRINTCTX = 'Sicht: ' + diag.name + ' (' + diag.pkgPath + ')';
  G.mode = 'diag'; G.root = null; G.built = false;

  var h = [];
  h.push('<div class="crumb">' +
    '<a href="javascript:showView(\'explorer\')">🧭 Erkunden</a> &nbsp;·&nbsp; ' +
    '<a href="javascript:showView(\'diags\')">🖼️ Sichten</a>' +
    (diag.pkgId && PKG[diag.pkgId] ? ' &nbsp;·&nbsp; 📁 <a href="javascript:openPackage(' + diag.pkgId + ')">' + esc(diag.pkgPath) + '</a>' : '') +
    ' &nbsp;▸&nbsp; <b>🖼️ ' + esc(diag.name) + '</b></div>');

  h.push('<h2>🖼️ ' + esc(diag.name) + '</h2>');
  h.push('<div class="kpis">' +
    '<span><b>' + ddata.els.length + '</b> Elemente auf dieser Sicht</span>' +
    '<span><b>' + ddata.rels.length + '</b> Beziehungen</span>' +
    '<span>Diagrammtyp: <b>' + esc(diag.type) + '</b></span>' +
    (diag.prefix && ADMBW_DATA.vp[diag.prefix] ? '<span style="cursor:pointer" onclick="openVP(\'' + diag.prefix + '\')">ADMBw-Sicht: <b>' + esc(diag.prefix) + '</b></span>' : '') +
    '</div>');
  if (diag.notes) h.push('<div class="purpose"><b>Sicht-Beschreibung:</b> ' + esc(diag.notes) + '</div>');

  /* Prominente Aktions- & Exportleiste für diese Sicht */
  h.push('<div class="vp-actions">');
  h.push('<span class="vswitch">Ansicht: ' +
    '<button id="btn-mode-list" class="' + (mode === 'graph' ? '' : 'on') + '" onclick="setVPMode(\'list\')">🖼️ Original-Schaubild &amp; Tabellen</button>' +
    '<button id="btn-mode-graph" class="' + (mode === 'graph' ? 'on' : '') + '" onclick="setVPMode(\'graph\')">◉ Sicht im interaktiven Graph erkunden</button>' +
    '</span>');
  h.push('<span class="vedit">✏️ ' +
    '<button onclick="EDIT.diagEdit(' + diag.id + ')" title="Sicht-/Diagrammnamen &amp; Beschreibung ändern">Sicht bearbeiten</button>' +
    '</span>');
  h.push('<span class="vexport">' +
    '<button class="exp-png" onclick="exportCurrentPNG()" title="Diese Sicht (Schaubild oder Graph) als hochauflösendes PNG exportieren">📸 PNG</button>' +
    '<button class="exp-xls" onclick="exportCurrentXLSX()" title="Alle Elemente, Beziehungen &amp; Tagged Values dieser Sicht als Excel (.xlsx) exportieren">📊 Excel (.xlsx)</button>' +
    '<button onclick="exportElementsCSV()">⤓ Elemente (CSV)</button>' +
    '<button onclick="exportRelsCSV()">⤓ Beziehungen (CSV)</button>' +
    '<button onclick="exportPDF()">🖨 PDF</button>' +
    '</span>');
  h.push('</div>');

  h.push('<div class="vp-list" id="vp-list">');
  h.push('<div class="diagbox">' +
    '<div class="diagbox-hdr">' +
      '<div><span class="diagtitle">Original-Schaubild aus Sparx EA</span><span class="diagsub">💡 Tipp: Klicken Sie direkt auf ein Kästchen im Schaubild, um dessen Steckbrief &amp; Umfeld zu öffnen!</span></div>' +
      '<div class="diagtools">' +
        '<button class="btn-sm" onclick="zoomDiagSvg(' + diag.id + ', 0.85)">🔍－</button>' +
        '<button class="btn-sm" onclick="zoomDiagSvg(' + diag.id + ', 1.0, true)">100%</button>' +
        '<button class="btn-sm" onclick="zoomDiagSvg(' + diag.id + ', 1.18)">🔍＋</button>' +
      '</div>' +
    '</div>' +
    '<div class="svgwrap" id="diag-' + diag.id + '"></div>' +
  '</div>');

  h.push(renderDistBar(ddata.els, 'vp-list'));

  h.push('<div class="vpfilterwrap"><input class="vpfilter" placeholder="🔍 Tabellen dieser Sicht filtern (Name, Alias, Stereotype) …" oninput="filterRows(this)"></div>');
  h.push('<h3>Elemente auf dieser Sicht (' + ddata.els.length + ')</h3>');
  if (!ddata.els.length) {
    h.push('<div class="hint">Keine Modell-Elemente auf dieser Sicht platziert.</div>');
  } else {
    h.push('<table class="data"><thead><tr><th>Name</th><th>Stereotype</th><th>Alias</th><th>Paketpfad</th><th>Verb.</th></tr></thead><tbody>');
    for (var i = 0; i < ddata.els.length; i++) {
      var o = ddata.els[i];
      h.push('<tr class="clickable" onclick="openElement(\'' + o.id + '\')">' +
        '<td><b>' + esc(o.name) + '</b></td>' +
        '<td><code>' + esc(o.st) + '</code></td>' +
        '<td>' + esc(o.alias) + '</td>' +
        '<td class="dim">' + esc(o.pkg) + '</td>' +
        '<td><span class="b b-rel">' + (CONNCOUNT[String(o.id)] || 0) + '</span></td>' +
      '</tr>');
    }
    h.push('</tbody></table>');
  }

  h.push('<h3>Beziehungen auf dieser Sicht (' + ddata.rels.length + ')</h3>');
  if (!ddata.rels.length) {
    h.push('<div class="hint">Keine Beziehungen auf dieser Sicht.</div>');
  } else {
    h.push('<table class="data"><thead><tr><th>Quelle</th><th>Beziehung</th><th>Ziel</th></tr></thead><tbody>');
    for (i = 0; i < ddata.rels.length; i++) {
      var c = ddata.rels[i];
      var a = OBJS[c.a], b = OBJS[c.b];
      h.push('<tr class="clickable" onclick="openElement(\'' + c.a + '\')">' +
        '<td>' + esc(a ? a.name : '?') + ' <span class="dim">«' + esc(a ? a.st : '') + '»</span></td>' +
        '<td><code>' + esc(c.st || c.type || '→') + '</code></td>' +
        '<td>' + esc(b ? b.name : '?') + ' <span class="dim">«' + esc(b ? b.st : '') + '»</span></td>' +
      '</tr>');
    }
    h.push('</tbody></table>');
  }

  h.push('</div>'); /* /vp-list */
  h.push('<div class="vp-graph" id="vp-graph" style="display:none"></div>');

  el('vpbox').innerHTML = h.join('');
  showView('vp');
  renderDiagram(diag, el('diag-' + diag.id));
  setVPMode(mode === 'graph' ? 'graph' : 'list');
}

function zoomDiagSvg(diagId, factor, reset) {
  var wrap = el('diag-' + diagId);
  if (!wrap) return;
  var svg = wrap.querySelector('svg');
  if (!svg) return;
  var baseW = parseFloat(svg.getAttribute('data-base-w')) || parseFloat(svg.getAttribute('width')) || 800;
  var baseH = parseFloat(svg.getAttribute('data-base-h')) || parseFloat(svg.getAttribute('height')) || 600;
  if (!svg.getAttribute('data-base-w')) {
    svg.setAttribute('data-base-w', String(baseW));
    svg.setAttribute('data-base-h', String(baseH));
  }
  var curW = reset ? baseW : (parseFloat(svg.getAttribute('width')) || baseW) * factor;
  var curH = reset ? baseH : (parseFloat(svg.getAttribute('height')) || baseH) * factor;
  svg.setAttribute('width', String(Math.round(curW)));
  svg.setAttribute('height', String(Math.round(curH)));
}

/* ---------- Designumschaltung: Standard hell, Dunkel nur per Button ---------- */
/* Designumschaltung: Standard hell, Wahl wird gespeichert (kein System-Dark mehr) */
(function () {
  try {
    if (localStorage.getItem('eam-theme') === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  } catch (e) {}
  function sync() {
    var b = document.getElementById('themeBtn');
    if (!b) return;
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    b.textContent = dark ? '\u2600\uFE0F Helles Design' : '\u{1F319} Dunkles Design';
    b.setAttribute('aria-pressed', dark ? 'true' : 'false');
    b.title = dark ? 'Zur hellen Ansicht wechseln' : 'Zur dunklen Ansicht wechseln';
  }
  window.toggleTheme = function () {
    var root = document.documentElement;
    if (root.getAttribute('data-theme') === 'dark') {
      root.removeAttribute('data-theme');
      try { localStorage.setItem('eam-theme', 'light'); } catch (e) {}
    } else {
      root.setAttribute('data-theme', 'dark');
      try { localStorage.setItem('eam-theme', 'dark'); } catch (e) {}
    }
    sync();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sync);
  else sync();
})();
