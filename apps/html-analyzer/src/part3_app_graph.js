/* ADMBw QEA Analyzer v4.0 — Teil 2: Globale Suche, Viewpoints, Steckbrief, Interaktives Diagramm & Prägnanter Graph */

/* ---------- Statistik pro ADMBw-Viewpoint ---------- */
function computeStats() {
  VPSTAT = {};
  var d = ADMBW_DATA, k, i;
  for (k in d.vp) {
    if (!d.vp.hasOwnProperty(k)) continue;
    VPSTAT[k] = { els: 0, rels: 0, diags: 0 };
  }
  var byvp = {};
  for (k in d.vp) {
    if (!d.vp.hasOwnProperty(k)) continue;
    var els = d.vp[k].els, j;
    for (j = 0; j < els.length; j++) {
      if (!byvp[els[j]]) byvp[els[j]] = [];
      byvp[els[j]].push(k);
    }
  }
  for (var oid in OBJS) {
    if (!OBJS.hasOwnProperty(oid)) continue;
    var st = OBJS[oid].st;
    if (!st || !byvp[st]) continue;
    var vlist = byvp[st];
    for (i = 0; i < vlist.length; i++) VPSTAT[vlist[i]].els++;
  }
  for (k in d.topo) {
    if (!d.topo.hasOwnProperty(k) || !VPSTAT[k]) continue;
    var rules = d.topo[k], relSet = {};
    for (i = 0; i < rules.length; i++) relSet[rules[i].rel] = 1;
    for (i = 0; i < CONS.length; i++) {
      if (relSet[CONS[i].st]) VPSTAT[k].rels++;
    }
  }
  for (i = 0; i < DIAGS.length; i++) {
    var p = DIAGS[i].prefix;
    if (p && VPSTAT[p]) VPSTAT[p].diags++;
  }
}

/* ---------- ADMBw-Referenz-Grid ---------- */
function renderGrid() {
  var d = ADMBW_DATA.grid;
  var onlyFilled = el('gridonlyfilled') ? el('gridonlyfilled').checked : false;
  var h = [];
  h.push('<table class="grid"><thead><tr><th class="corner">Schicht&nbsp;/&nbsp;Aspekt</th>');
  var c;
  for (c = 0; c < d.cols.length; c++) {
    h.push('<th>' + esc(d.cols[c]) + '<span>' + esc(d.col_de[c]) + '</span></th>');
  }
  h.push('</tr></thead><tbody>');
  for (var r = 0; r < d.rows.length; r++) {
    var row = d.rows[r];
    h.push('<tr' + (row.bridge ? ' class="bridge"' : '') + '>');
    h.push('<th class="rowhead"><b>' + esc(row.label) + '</b><span>' + esc(row.desc) + '</span></th>');
    for (c = 0; c < row.cells.length; c++) {
      var vp = row.cells[c];
      if (!vp) { h.push('<td class="empty"></td>'); continue; }
      var info = ADMBW_DATA.vp[vp] || { n: vp, els: [] };
      var st = VPSTAT[vp] || { els: 0, rels: 0, diags: 0 };
      var hasData = (st.els > 0 || st.diags > 0);
      var cls = !hasData ? 'cell nodata' : 'cell';
      var styleExtra = (onlyFilled && !hasData) ? ' style="opacity:0.25"' : '';
      h.push('<td class="' + cls + '"' + styleExtra + ' onclick="openVP(\'' + vp + '\')" title="' + esc(info.n) + ' (' + st.els + ' Elemente, ' + st.diags + ' Diagramme)">');
      h.push('<div class="vpcode">' + esc(vp) + '</div>');
      h.push('<div class="vpname">' + esc(info.n) + '</div>');
      h.push('<div class="badges">');
      if (st.diags) h.push('<span class="b b-diag">🖼️ ' + st.diags + ' Diagr.</span>');
      if (st.els) h.push('<span class="b b-els">' + st.els + ' El.</span>');
      if (st.rels) h.push('<span class="b b-rel">' + st.rels + ' Bez.</span>');
      if (!st.els && !st.rels && !st.diags) h.push('<span class="b b-none">keine Daten</span>');
      h.push('</div></td>');
    }
    h.push('</tr>');
  }
  h.push('</tbody></table>');
  el('gridbox').innerHTML = h.join('');
  el('legend').innerHTML = '<span class="b b-diag">🖼️ n Diagr.</span> Vorhandene Diagramme &nbsp; <span class="b b-els">n El.</span> Elemente &nbsp; <span class="b b-rel">n Bez.</span> Beziehungen &nbsp; <span class="b b-none">keine Daten</span> keine sichtkonformen Inhalte';
  renderOverview();
}

function renderOverview() {
  var ov = el('overview');
  if (!ov) return;
  var filled = 0, empty = 0, k;
  for (k in VPSTAT) {
    if (!VPSTAT.hasOwnProperty(k)) continue;
    if (VPSTAT[k].els || VPSTAT[k].diags) filled++; else empty++;
  }
  if (el('cnt-grid')) el('cnt-grid').textContent = filled + '/' + (filled + empty);
  ov.innerHTML = '<div class="ov-line"><b>' + filled + '</b> von ' + (filled + empty) + ' ADMBw-Referenzsichten sind mit Elementen oder Diagrammen befüllt. (Alle <b>' + DIAGS.length + '</b> real vorhandenen Diagramme finden Sie im Reiter <b>„🖼️ Sichten“</b> und im <b>„🧭 Erkunden“</b>-Bereich.)</div>';
  ov.style.display = 'block';
}

/* ---------- ADMBw-Viewpoint öffnen ---------- */
function openVP(id) {
  CURVP = id;
  var vp = ADMBW_DATA.vp[id];
  if (!vp) return;
  EXPCTX = { fname: 'Viewpoint_' + id, kind: 'ADMBw-Viewpoint', label: 'Sicht ' + id + ' – ' + vp.n };
  PRINTCTX = 'Sicht ' + id + ' – ' + vp.n;
  G.mode = 'vp'; G.root = null; G.built = false;
  var st = VPSTAT[id] || { els: 0, rels: 0, diags: 0 };
  var d = ADMBW_DATA;
  var h = [];
  h.push('<div class="crumb"><a href="javascript:showView(\'explorer\')">🧭 Erkunden</a> &nbsp;·&nbsp; <a href="javascript:showView(\'grid\')">📐 ADMBw-Grid</a> &nbsp;▸&nbsp; <b>' + esc(id) + '</b></div>');
  h.push('<h2>' + esc(id) + ' &ndash; ' + esc(vp.n) + '</h2>');
  h.push('<div class="kpis"><span><b>' + st.diags + '</b> Diagramme</span><span><b>' + st.els + '</b> Elemente</span><span><b>' + st.rels + '</b> Beziehungen</span></div>');
  if (vp.desc) h.push('<div class="purpose"><b>Zweck (ADMBw-Dokumentation):</b> ' + esc(vp.desc) + '</div>');

  h.push('<div class="vp-actions">');
  h.push('<span class="vswitch">Ansicht: <button id="btn-mode-list" class="on" onclick="setVPMode(\'list\')">☰ Diagramme &amp; Tabellen</button><button id="btn-mode-graph" onclick="setVPMode(\'graph\')">◉ Zusammenhänge (Graph)</button></span>');
  h.push('<span class="vexport">' +
    '<button class="exp-png" onclick="exportCurrentPNG()" title="Schaubild oder Graph dieser Sicht als PNG exportieren">📸 Als PNG exportieren</button>' +
    '<button class="exp-xls" onclick="exportCurrentXLSX()" title="Elemente &amp; Beziehungen dieser Sicht als Excel (.xlsx) exportieren">📊 Als Excel (.xlsx) exportieren</button>' +
    '<button onclick="exportElementsCSV()">⤓ Elemente (CSV)</button>' +
    '<button onclick="exportRelsCSV()">⤓ Beziehungen (CSV)</button>' +
    '<button onclick="exportPDF()">🖨 PDF</button></span>');
  h.push('</div>');

  h.push('<div class="vp-list" id="vp-list">');

  var diags = [], i;
  for (i = 0; i < DIAGS.length; i++) if (DIAGS[i].prefix === id) diags.push(DIAGS[i]);
  h.push('<h3>Vorhandene Diagramme zu dieser Sicht (' + diags.length + ')</h3>');
  if (!diags.length) {
    h.push('<div class="hint">Keine Diagramme mit dem Präfix „' + esc(id) + '“ im Modell gefunden. Tipp: Prüfen Sie den Reiter <b>„🧭 Erkunden“</b> für frei benannte Diagramme.</div>');
  } else {
    h.push('<div class="diaglist">');
    for (i = 0; i < diags.length; i++) {
      var dg = diags[i];
      h.push('<div class="diagbox">' +
        '<div class="diagbox-hdr">' +
          '<div><span class="diagtitle">🖼️ ' + esc(dg.name) + '</span><span class="diagsub">(📁 ' + esc(dg.pkgPath) + ')</span></div>' +
          '<div class="diagtools">' +
            '<button class="btn-sm pri" onclick="openDiagramView(' + dg.id + ')">🔍 Einzel-Sicht</button>' +
            '<button class="btn-sm" onclick="openDiagramView(' + dg.id + ', \'graph\')">◉ Graph</button>' +
            '<button class="btn-sm amber" onclick="exportDiagramPNG(' + dg.id + ')">📸 PNG</button>' +
            '<button class="btn-sm green" onclick="exportDiagramXLSX(' + dg.id + ')">📊 Excel (.xlsx)</button>' +
          '</div>' +
        '</div>' +
        '<div class="svgwrap" id="diag-' + dg.id + '"></div></div>');
    }
    h.push('</div>');
  }

  var els = [], want = {};
  for (i = 0; i < vp.els.length; i++) want[vp.els[i]] = 1;
  for (var oid in OBJS) {
    if (!OBJS.hasOwnProperty(oid)) continue;
    if (want[OBJS[oid].st]) els.push(OBJS[oid]);
  }
  els.sort(function (a, b) { return a.st === b.st ? a.name.localeCompare(b.name, 'de') : a.st.localeCompare(b.st, 'de'); });

  h.push(renderDistBar(els, 'vp-list'));
  h.push('<div class="vpfilterwrap"><input class="vpfilter" placeholder="🔍 Tabellen filtern (Name, Alias, Stereotype, Paket) …" oninput="filterRows(this)"></div>');
  h.push('<h3>Elemente im Modell (' + els.length + ')</h3>');
  if (!els.length) {
    h.push('<div class="hint">Keine Modell-Elemente dieser Sicht vorhanden.</div>');
  } else {
    h.push('<table class="data"><thead><tr><th>Name</th><th>Stereotype</th><th>Alias</th><th>Paketpfad</th><th>Sichten</th></tr></thead><tbody>');
    for (i = 0; i < els.length; i++) {
      var dc = (OBJ_DIAGS[String(els[i].id)] || []).length;
      h.push('<tr class="clickable" onclick="openElement(\'' + els[i].id + '\')"><td><b>' + esc(els[i].name) + '</b></td><td><code>' + esc(els[i].st) + '</code></td><td>' + esc(els[i].alias) + '</td><td class="dim">' + esc(els[i].pkg) + '</td><td>' + (dc ? '<span class="b b-diag">' + dc + '</span>' : '–') + '</td></tr>');
    }
    h.push('</tbody></table>');
  }

  var rules = d.topo[id] || [], relSet = {};
  for (i = 0; i < rules.length; i++) relSet[rules[i].rel] = 1;
  var rels = [];
  for (i = 0; i < CONS.length; i++) {
    if (relSet[CONS[i].st]) rels.push(CONS[i]);
  }
  h.push('<h3>Beziehungen im Modell (' + rels.length + ')</h3>');
  if (!rels.length) {
    h.push('<div class="hint">Keine Modell-Beziehungen dieser Sicht vorhanden.</div>');
  } else {
    h.push('<table class="data"><thead><tr><th>Quelle</th><th>Beziehung</th><th>Ziel</th></tr></thead><tbody>');
    var shown = 0;
    for (i = 0; i < rels.length && shown < 300; i++) {
      var a = OBJS[rels[i].a], b = OBJS[rels[i].b];
      h.push('<tr class="clickable" onclick="openElement(\'' + rels[i].a + '\')"><td>' + esc(a ? a.name : '?') + '</td><td><code>' + esc(rels[i].st) + '</code></td><td>' + esc(b ? b.name : '?') + '</td></tr>');
      shown++;
    }
    h.push('</tbody></table>');
    if (rels.length > 300) h.push('<div class="hint">… ' + (rels.length - 300) + ' weitere (vollständig im Excel-/CSV-Export).</div>');
  }

  h.push('<h3>ADMBw-Regelwerk dieser Sicht</h3>');
  h.push('<div class="rules"><div class="rulecol"><b>Erlaubte Meta-Modell-Elemente (' + vp.els.length + ')</b><div class="rulelist">');
  for (i = 0; i < vp.els.length; i++) h.push('<code>' + esc(vp.els[i]) + '</code> ');
  h.push('</div></div><div class="rulecol"><b>Erlaubte Topologie (' + rules.length + ' Regeln)</b><div class="rulelist">');
  for (i = 0; i < rules.length; i++) {
    h.push('<div class="rule"><span class="dim">' + esc(rules[i]['from'].join('; ')) + '</span> &rarr; <code>' + esc(rules[i].rel) + '</code> &rarr; <span class="dim">' + esc(rules[i].to.join('; ')) + '</span></div>');
  }
  if (!rules.length) h.push('<span class="dim">Keine Topologie-Regeln hinterlegt.</span>');
  h.push('</div></div></div>');

  h.push('</div>'); /* /vp-list */
  h.push('<div class="vp-graph" id="vp-graph" style="display:none"></div>');

  CURDATA = { els: els, rels: rels, diags: diags };
  VPMODE = 'list';
  el('vpbox').innerHTML = h.join('');
  showView('vp');

  for (i = 0; i < diags.length; i++) renderDiagram(diags[i], el('diag-' + diags[i].id));
}

/* ================================================================
   SEARCH-FIRST: GLOBALE SUCHE ÜBER SICHTEN, PAKETE & ELEMENTE
   ================================================================ */
function setSearchScope(sc) {
  SEARCH_SCOPE = sc;
  var btns = document.querySelectorAll('#searchscopes .scope-btn');
  for (var i = 0; i < btns.length; i++) {
    btns[i].className = 'scope-btn' + (btns[i].getAttribute('data-scope') === sc ? ' on' : '');
  }
  globalSearch();
}

function clearGlobalSearch() {
  var inp = el('globalsearch'), box = el('gsres'), clr = el('gsclear');
  if (inp) inp.value = '';
  if (box) { box.style.display = 'none'; box.innerHTML = ''; }
  if (clr) clr.style.display = 'none';
  GLOBHITS = [];
}

function fillSearch(q) {
  var si = el('globalsearch');
  if (!si) return;
  si.value = q;
  globalSearch();
  si.focus();
}

function collectSearchHits(q) {
  var diagHits = [], pkgHits = [], elHits = [], i, k;
  if (SEARCH_SCOPE === 'all' || SEARCH_SCOPE === 'diag') {
    for (i = 0; i < DIAGS.length; i++) {
      var d = DIAGS[i];
      if ((d.name + ' ' + d.pkgFull + ' ' + d.prefix + ' ' + d.type + ' ' + d.notes).toLowerCase().indexOf(q) >= 0) {
        diagHits.push(d);
      }
    }
  }
  if (SEARCH_SCOPE === 'all' || SEARCH_SCOPE === 'pkg') {
    for (k in PKG) {
      if (!PKG.hasOwnProperty(k)) continue;
      var p = PKG[k];
      if ((p.name + ' ' + p.path + ' ' + p.notes).toLowerCase().indexOf(q) >= 0) {
        pkgHits.push(p);
      }
    }
  }
  if (SEARCH_SCOPE === 'all' || SEARCH_SCOPE === 'el') {
    for (k in OBJS) {
      if (!OBJS.hasOwnProperty(k)) continue;
      var o = OBJS[k];
      if (o.type === 'Boundary' || /^proxyconn?ector$/i.test(o.st)) continue;
      if ((o.name + ' ' + o.alias + ' ' + o.st + ' ' + o.pkg + ' ' + o.note).toLowerCase().indexOf(q) >= 0) {
        elHits.push(o);
      }
    }
    elHits.sort(function (a, b) { return (CONNCOUNT[b.id] || 0) - (CONNCOUNT[a.id] || 0); });
  }
  return { diags: diagHits, pkgs: pkgHits, els: elHits };
}

function globalSearch() {
  var inp = el('globalsearch'), box = el('gsres'), clr = el('gsclear');
  if (!inp || !box) return;
  var q = (inp.value || '').trim().toLowerCase();
  if (clr) clr.style.display = q.length ? 'block' : 'none';
  if (q.length < 2) { box.style.display = 'none'; box.innerHTML = ''; GLOBHITS = []; return; }

  var res = collectSearchHits(q);
  var total = res.diags.length + res.pkgs.length + res.els.length;
  GLOBHITS = res.els;

  if (!total) {
    box.innerHTML = '<div class="gsrow dim">Keine Treffer für „' + esc(q) + '“</div>';
    box.style.display = 'block';
    return;
  }

  var h = [], i;
  h.push('<div class="gs-hdr">' +
    '<span>Treffer für „' + esc(q) + '“: ' + res.diags.length + ' Sichten · ' + res.pkgs.length + ' Pakete · ' + res.els.length + ' Elemente</span>' +
    '<button class="gs-btn" onclick="openSearchResultsView()">🔎 Alle als Sicht öffnen &amp; exportieren</button>' +
  '</div>');

  /* 1. Sichten / Diagramme */
  var maxD = SEARCH_SCOPE === 'diag' ? 30 : 8;
  for (i = 0; i < res.diags.length && i < maxD; i++) {
    var d = res.diags[i];
    h.push('<div class="gsrow">' +
      '<span class="gs-kind k-diag">🖼️ Sicht</span>' +
      '<span class="gs-name" onclick="openDiagramView(' + d.id + ')"><b>' + esc(d.name) + '</b> <span class="gs-meta">📁 ' + esc(d.pkgPath) + ' (' + d.objCount + ' El.)</span></span>' +
      '<button class="gs-btn" onclick="event.stopPropagation();openDiagramView(' + d.id + ', \'graph\')">◉ Graph</button>' +
      '<button class="gs-btn" onclick="event.stopPropagation();exportDiagramPNG(' + d.id + ')">📸 PNG</button>' +
      '<button class="gs-btn" onclick="event.stopPropagation();exportDiagramXLSX(' + d.id + ')">📊 Excel</button>' +
    '</div>');
  }

  /* 2. Pakete */
  var maxP = SEARCH_SCOPE === 'pkg' ? 30 : 6;
  for (i = 0; i < res.pkgs.length && i < maxP; i++) {
    var p = res.pkgs[i];
    h.push('<div class="gsrow">' +
      '<span class="gs-kind k-pkg">📁 Paket</span>' +
      '<span class="gs-name" onclick="openPackage(' + p.id + ')"><b>' + esc(p.name) + '</b> <span class="gs-meta">' + esc(p.path) + ' (' + p.allDiagsCount + ' Sichten · ' + p.allObjsCount + ' El.)</span></span>' +
      '<button class="gs-btn" onclick="event.stopPropagation();openPackage(' + p.id + ')">🧭 Im Explorer</button>' +
    '</div>');
  }

  /* 3. Elemente */
  var maxE = SEARCH_SCOPE === 'el' ? 40 : 20;
  for (i = 0; i < res.els.length && i < maxE; i++) {
    var o = res.els[i];
    var n = CONNCOUNT[o.id] || 0;
    h.push('<div class="gsrow">' +
      '<span class="gs-kind k-el">📦 Element</span>' +
      '<span class="gs-name" onclick="openElement(\'' + o.id + '\')"><b>' + esc(o.name || '(ohne Name)') + '</b> <code>' + esc(o.st) + '</code><span class="gs-meta">' + esc(shortLabel(o.pkg || '', 42)) + '</span></span>' +
      '<span class="gs-conn">' + n + ' Verb.</span>' +
      '<button class="gs-btn" onclick="event.stopPropagation();openElement(\'' + o.id + '\', \'graph\')">◉ Umfeld-Graph</button>' +
    '</div>');
  }

  box.innerHTML = h.join('');
  box.style.display = 'block';
}

function globalSearchKey(e) {
  if (e.keyCode === 13) {
    e.preventDefault();
    openSearchResultsView();
  } else if (e.keyCode === 27) {
    var box = el('gsres'); if (box) box.style.display = 'none';
  }
}

/* Öffnet alle Suchergebnisse als vollwertige, im Graphen visualisierbare & als Excel/PNG exportierbare Sicht! */
function openSearchResultsView() {
  var inp = el('globalsearch');
  var q = (inp ? inp.value : '').trim();
  if (!q) {
    alert('Bitte geben Sie zuerst einen Suchbegriff in das Suchfeld ein.');
    return;
  }
  var box = el('gsres'); if (box) box.style.display = 'none';
  var res = collectSearchHits(q.toLowerCase());
  var elSet = {}, i;
  for (i = 0; i < res.els.length; i++) elSet[res.els[i].id] = true;
  var rels = [];
  for (i = 0; i < CONS.length; i++) {
    if (elSet[CONS[i].a] || elSet[CONS[i].b]) rels.push(CONS[i]);
  }

  CURDATA = { els: res.els, rels: rels, diags: res.diags };
  EXPCTX = { fname: 'Suche_' + q, kind: 'Suchergebnis', label: 'Suchergebnis: „' + q + '“' };
  PRINTCTX = 'Suchergebnis für „' + q + '“';
  G.mode = 'search'; G.root = null; G.built = false;

  var h = [];
  h.push('<div class="crumb"><a href="javascript:showView(\'explorer\')">🧭 Erkunden</a> &nbsp;▸&nbsp; <b>🔎 Suchergebnisse für „' + esc(q) + '“</b></div>');
  h.push('<h2>🔎 Suchergebnisse für „' + esc(q) + '“</h2>');
  h.push('<div class="kpis">' +
    '<span><b>' + res.diags.length + '</b> gefundene Sichten (Diagramme)</span>' +
    '<span><b>' + res.pkgs.length + '</b> gefundene Pakete</span>' +
    '<span><b>' + res.els.length + '</b> gefundene Elemente</span>' +
    '<span><b>' + rels.length + '</b> verknüpfte Beziehungen</span>' +
  '</div>');

  h.push('<div class="vp-actions">');
  h.push('<span class="vswitch">Ansicht: ' +
    '<button id="btn-mode-list" class="on" onclick="setVPMode(\'list\')">☰ Trefferliste (Sichten, Pakete &amp; Elemente)</button>' +
    '<button id="btn-mode-graph" onclick="setVPMode(\'graph\')">◉ Gefundene Elemente im Graph visualisieren</button>' +
  '</span>');
  h.push('<span class="vexport">' +
    '<button class="exp-xls" onclick="exportCurrentXLSX()">📊 Treffer als Excel (.xlsx) exportieren</button>' +
    '<button class="exp-png" onclick="exportCurrentPNG()">📸 Graph als PNG exportieren</button>' +
    '<button onclick="exportElementsCSV()">⤓ CSV</button>' +
    '<button onclick="exportPDF()">🖨 PDF</button>' +
  '</span>');
  h.push('</div>');

  h.push('<div id="vp-list">');
  if (res.diags.length) {
    h.push('<h3>Gefundene Sichten / Diagramme (' + res.diags.length + ')</h3>');
    h.push('<div class="diag-cards">');
    for (i = 0; i < res.diags.length && i < 24; i++) {
      var d = res.diags[i];
      h.push('<div class="dcard">' +
        '<div><div class="dcard-title" onclick="openDiagramView(' + d.id + ')">🖼️ ' + esc(d.name) + '</div>' +
        '<div class="dcard-path">📁 ' + esc(d.pkgPath) + '</div>' +
        '<div class="dcard-badges"><span class="b b-els">' + d.objCount + ' El.</span><span class="b b-rel">' + d.linkCount + ' Kanten</span></div></div>' +
        '<div class="dcard-acts">' +
          '<button class="btn-sm pri" onclick="openDiagramView(' + d.id + ')">🔍 Öffnen</button>' +
          '<button class="btn-sm amber" onclick="exportDiagramPNG(' + d.id + ')">📸 PNG</button>' +
          '<button class="btn-sm green" onclick="exportDiagramXLSX(' + d.id + ')">📊 Excel</button>' +
        '</div></div>');
    }
    h.push('</div>');
  }
  if (res.pkgs.length) {
    h.push('<h3>Gefundene Pakete (' + res.pkgs.length + ')</h3>');
    h.push('<div class="subpkg-grid">');
    for (i = 0; i < res.pkgs.length && i < 16; i++) {
      var p = res.pkgs[i];
      h.push('<div class="pkg-card" onclick="openPackage(' + p.id + ')"><div class="pkg-card-title">📁 ' + esc(p.name) + '</div><div class="pkg-card-meta">' + esc(p.path) + '<br><b>' + p.allDiagsCount + '</b> Sichten · <b>' + p.allObjsCount + '</b> Elemente</div></div>');
    }
    h.push('</div>');
  }
  h.push(renderDistBar(res.els, 'vp-list'));
  h.push('<h3>Gefundene Elemente (' + res.els.length + ')</h3>');
  if (!res.els.length) {
    h.push('<div class="hint">Keine Elemente gefunden.</div>');
  } else {
    h.push('<table class="data"><thead><tr><th>Name</th><th>Stereotype</th><th>Alias</th><th>Paketpfad</th><th>Sichten</th><th>Verb.</th></tr></thead><tbody>');
    for (i = 0; i < res.els.length && i < 200; i++) {
      var o = res.els[i];
      var dc = (OBJ_DIAGS[String(o.id)] || []).length;
      h.push('<tr class="clickable" onclick="openElement(\'' + o.id + '\')">' +
        '<td><b>' + esc(o.name) + '</b></td>' +
        '<td><code>' + esc(o.st) + '</code></td>' +
        '<td>' + esc(o.alias) + '</td>' +
        '<td class="dim">' + esc(o.pkg) + '</td>' +
        '<td>' + (dc ? '<span class="b b-diag">' + dc + '</span>' : '–') + '</td>' +
        '<td><span class="b b-rel">' + (CONNCOUNT[String(o.id)] || 0) + '</span></td>' +
      '</tr>');
    }
    h.push('</tbody></table>');
  }
  h.push('</div>');
  h.push('<div class="vp-graph" id="vp-graph" style="display:none"></div>');

  el('vpbox').innerHTML = h.join('');
  showView('vp');
}

/* ================================================================
   ELEMENT-STECKBRIEF & NACHBARSCHAFT
   ================================================================ */
function elementNeighborhood(oid, hops, cap) {
  oid = String(oid); cap = cap || 600;
  var set = {}, order = [oid], frontier = [oid], capped = false;
  var i, j, s, c, other;
  set[oid] = 1;
  for (s = 0; s < hops && !capped; s++) {
    var nf = [];
    for (i = 0; i < frontier.length; i++) {
      var fid = frontier[i];
      for (j = 0; j < CONS.length; j++) {
        c = CONS[j];
        var ca = String(c.a), cb = String(c.b);
        other = null;
        if (ca === fid) other = cb; else if (cb === fid) other = ca;
        if (other && !set[other]) {
          if (order.length >= cap) { capped = true; break; }
          set[other] = 1; order.push(other); nf.push(other);
        }
      }
      if (capped) break;
    }
    frontier = nf;
  }
  var els = [], rels = [];
  for (i = 0; i < order.length; i++) { if (OBJS[order[i]]) els.push(OBJS[order[i]]); }
  for (i = 0; i < CONS.length; i++) {
    c = CONS[i];
    if (set[String(c.a)] && set[String(c.b)]) rels.push(c);
  }
  return { els: els, rels: rels, capped: capped, count: order.length };
}

function vpsForStereotype(st) {
  var out = [], k;
  for (k in ADMBW_DATA.vp) {
    if (!ADMBW_DATA.vp.hasOwnProperty(k)) continue;
    if (ADMBW_DATA.vp[k].els && ADMBW_DATA.vp[k].els.indexOf(st) >= 0) out.push(k);
  }
  return out;
}

function openElement(oid, mode) {
  oid = String(oid);
  var o = OBJS[oid];
  if (!o) return;
  var d = el('gsres'); if (d) d.style.display = 'none';
  var i, c, other;
  var outgoing = [], incoming = [];
  for (i = 0; i < CONS.length; i++) {
    c = CONS[i];
    if (String(c.a) === oid) outgoing.push(c);
    else if (String(c.b) === oid) incoming.push(c);
  }
  var nb = elementNeighborhood(oid, 1, 500);
  CURDATA = { els: nb.els, rels: nb.rels, diags: [] };
  G.mode = 'elem'; G.root = oid; G.hops = 1; G.capped = nb.capped; G.built = false;
  EXPCTX = { fname: 'Element_' + (o.name || 'Steckbrief'), kind: 'Element-Umfeld (1 Ebene)', label: 'Element: ' + (o.name || '(ohne Name)') };
  PRINTCTX = 'Element – ' + (o.name || '') + ' «' + (o.st || '') + '»';

  var usedDiagIds = OBJ_DIAGS[oid] || [];
  var h = [];
  h.push('<div class="crumb"><a href="javascript:showView(\'explorer\')">🧭 Erkunden</a>' +
    (o.pkgId && PKG[o.pkgId] ? ' &nbsp;·&nbsp; 📁 <a href="javascript:openPackage(' + o.pkgId + ')">' + esc(o.pkg) + '</a>' : '') +
    ' &nbsp;▸&nbsp; <b>📦 ' + esc(o.name || '(ohne Name)') + '</b></div>');

  h.push('<h2>📦 ' + esc(o.name || '(ohne Name)') + '</h2>');
  h.push('<div class="kpis">' +
    '<span>Stereotype: <code>' + esc(o.st || '–') + '</code></span>' +
    '<span><b>' + (CONNCOUNT[oid] || 0) + '</b> Verbindungen</span>' +
    '<span><b>' + usedDiagIds.length + '</b> vorhandene Sicht(en)</span>' +
    '<span class="dim">📁 ' + esc(o.pkg || '') + '</span>' +
  '</div>');
  if (o.alias) h.push('<div class="purpose"><b>Alias:</b> ' + esc(o.alias) + '</div>');
  if (o.note) h.push('<div class="purpose"><b>Beschreibung / Notiz:</b> ' + esc(o.note) + '</div>');

  h.push('<div class="vp-actions">');
  h.push('<span class="vswitch">Ansicht: ' +
    '<button id="btn-mode-list" class="' + (mode === 'graph' ? '' : 'on') + '" onclick="setVPMode(\'list\')">☰ Steckbrief &amp; Verwendung</button>' +
    '<button id="btn-mode-graph" class="' + (mode === 'graph' ? 'on' : '') + '" onclick="setVPMode(\'graph\')">◉ Umfeld im Graph visualisieren</button>' +
  '</span>');
  h.push('<span class="vswitch" style="margin-left:6px">🔗 Pfadanalyse: ' +
    '<button onclick="pathSetEndpoint(\'start\',\'' + oid + '\')" title="Dieses Element als Start der Verbindungsanalyse setzen">als Start setzen</button>' +
    '<button onclick="pathSetEndpoint(\'end\',\'' + oid + '\')" title="Dieses Element als Ziel der Verbindungsanalyse setzen">als Ziel setzen</button>' +
  '</span>');
  var veditBtns = (typeof EDIT === 'undefined') ? '' : ((o.type === 'Package')
    ? '<button onclick="EDIT.pkgEdit(EDIT.pkgIdForObject(\'' + oid + '\'))">✏️ Paket bearbeiten</button>'
    : '<button onclick="EDIT.elEdit(\'' + oid + '\')">✏️ Element bearbeiten</button>' +
      '<button onclick="EDIT.connNew(\'' + oid + '\')">＋ Beziehung</button>' +
      '<button class="delbtn" onclick="EDIT.elDel(\'' + oid + '\')">🗑 Löschen</button>');
  if (veditBtns) h.push('<span class="vedit">✏️ ' + veditBtns + '</span>');
  h.push('<span class="vexport">' +
    '<button class="exp-xls" onclick="exportCurrentXLSX()">📊 Umfeld als Excel (.xlsx)</button>' +
    '<button class="exp-png" onclick="exportCurrentPNG()">📸 Graph als PNG</button>' +
    '<button onclick="exportElementsCSV()">⤓ Elemente (CSV)</button>' +
    '<button onclick="exportRelsCSV()">⤓ Beziehungen (CSV)</button>' +
    '<button onclick="exportPDF()">🖨 PDF</button>' +
  '</span>');
  h.push('</div>');

  h.push('<div class="vp-list" id="vp-list">');

  /* NEU: Tatsächlich vorhandene Sichten (Diagramme), auf denen dieses Element vorkommt! */
  h.push('<h3>🖼️ Dargestellt auf vorhandenen Sichten / Diagrammen (' + usedDiagIds.length + ')</h3>');
  if (!usedDiagIds.length) {
    h.push('<div class="hint">Dieses Element ist auf keinem Diagramm direkt platziert (nur im Paketbaum/Modellkatalog geführt).</div>');
  } else {
    h.push('<div class="diag-cards">');
    for (i = 0; i < usedDiagIds.length; i++) {
      var dg = DIAGMAP[usedDiagIds[i]];
      if (!dg) continue;
      h.push('<div class="dcard">' +
        '<div><div class="dcard-title" onclick="openDiagramView(' + dg.id + ')">🖼️ ' + esc(dg.name) + '</div>' +
        '<div class="dcard-path">📁 ' + esc(dg.pkgPath) + '</div>' +
        '<div class="dcard-badges"><span class="b b-els">' + dg.objCount + ' El.</span><span class="b b-rel">' + dg.linkCount + ' Kanten</span></div></div>' +
        '<div class="dcard-acts">' +
          '<button class="btn-sm pri" onclick="openDiagramView(' + dg.id + ')">🔍 Sicht öffnen</button>' +
          '<button class="btn-sm amber" onclick="exportDiagramPNG(' + dg.id + ')">📸 PNG</button>' +
          '<button class="btn-sm green" onclick="exportDiagramXLSX(' + dg.id + ')">📊 Excel</button>' +
        '</div></div>');
    }
    h.push('</div>');
  }

  h.push('<div class="vpfilterwrap"><input class="vpfilter" placeholder="🔍 Beziehungen &amp; Eigenschaften filtern …" oninput="filterRows(this)"></div>');
  h.push('<h3>Ausgehende Beziehungen (' + outgoing.length + ')</h3>');
  if (!outgoing.length) h.push('<div class="hint">Keine ausgehenden Beziehungen.</div>');
  else {
    h.push('<table class="data"><thead><tr><th>Ziel</th><th>Beziehung</th><th>Ziel-Stereotype</th><th>Paket</th><th style="width:36px"></th></tr></thead><tbody>');
    for (i = 0; i < outgoing.length && i < 300; i++) {
      c = outgoing[i];
      other = OBJS[String(c.b)];
      h.push('<tr class="clickable" onclick="openElement(\'' + String(c.b) + '\')"><td><b>' + esc(other ? other.name : '?') + '</b></td><td><code>' + esc(c.st || c.type || '→') + '</code></td><td>' + esc(other ? other.st : '') + '</td><td class="dim">' + esc(other ? other.pkg : '') + '</td><td>' + (typeof EDIT !== 'undefined' ? '<button class="btn-sm" style="padding:2px 7px;font-size:11px" onclick="event.stopPropagation();EDIT.connEdit(' + c.id + ')" title="Diese Beziehung bearbeiten">✏️</button>' : '') + '</td></tr>');
    }
    h.push('</tbody></table>');
  }

  h.push('<h3>Eingehende Beziehungen (' + incoming.length + ')</h3>');
  if (!incoming.length) h.push('<div class="hint">Keine eingehenden Beziehungen.</div>');
  else {
    h.push('<table class="data"><thead><tr><th>Quelle</th><th>Beziehung</th><th>Quelle-Stereotype</th><th>Paket</th><th style="width:36px"></th></tr></thead><tbody>');
    for (i = 0; i < incoming.length && i < 300; i++) {
      c = incoming[i];
      other = OBJS[String(c.a)];
      h.push('<tr class="clickable" onclick="openElement(\'' + String(c.a) + '\')"><td><b>' + esc(other ? other.name : '?') + '</b></td><td><code>' + esc(c.st || c.type || '→') + '</code></td><td>' + esc(other ? other.st : '') + '</td><td class="dim">' + esc(other ? other.pkg : '') + '</td><td>' + (typeof EDIT !== 'undefined' ? '<button class="btn-sm" style="padding:2px 7px;font-size:11px" onclick="event.stopPropagation();EDIT.connEdit(' + c.id + ')" title="Diese Beziehung bearbeiten">✏️</button>' : '') + '</td></tr>');
    }
    h.push('</tbody></table>');
  }

  var tags = TAGS[oid] || [];
  h.push('<h3>Tagged Values / Eigenschaften (' + tags.length + ')' + (typeof EDIT !== 'undefined' ? ' <button class="btn-sm" style="margin-left:8px;vertical-align:middle" onclick="EDIT.tagOpen(\'' + oid + '\')" title="Tags dieses Elements bearbeiten (ändern, ergänzen, entfernen)">🏷️ Bearbeiten</button>' : '') + '</h3>');
  if (!tags.length) h.push('<div class="hint">Keine Tagged Values zu diesem Element erfasst.</div>');
  else {
    h.push('<table class="data"><thead><tr><th>Eigenschaft</th><th>Wert</th><th>Notiz</th></tr></thead><tbody>');
    for (i = 0; i < tags.length && i < 150; i++) {
      h.push('<tr><td><b>' + esc(tags[i].p) + '</b></td><td>' + esc(shortLabel(tags[i].v, 140)) + '</td><td class="dim">' + esc(shortLabel(tags[i].n, 90)) + '</td></tr>');
    }
    h.push('</tbody></table>');
  }

  var vps = vpsForStereotype(o.st);
  h.push('<h3>Theoretische Zuordnung im ADMBw-Referenz-Grid (' + vps.length + ')</h3>');
  if (!vps.length) h.push('<div class="hint">Kein Standard-ADMBw-Viewpoint für Stereotyp „' + esc(o.st) + '“.</div>');
  else {
    h.push('<div class="rulelist">');
    for (i = 0; i < vps.length; i++) {
      var vp = ADMBW_DATA.vp[vps[i]];
      h.push('<span class="gchip vpchip" onclick="openVP(\'' + vps[i] + '\')" title="' + esc(vp.n) + '">' + esc(vps[i]) + ' <em>' + esc(shortLabel(vp.n, 34)) + '</em></span> ');
    }
    h.push('</div>');
  }
  h.push('</div>');
  h.push('<div class="vp-graph" id="vp-graph" style="display:none"></div>');

  el('vpbox').innerHTML = h.join('');
  showView('vp');
  setVPMode(mode === 'graph' ? 'graph' : 'list');
}

function elementExpand(hops) {
  if (!G.root) return;
  var res = elementNeighborhood(G.root, hops, 600);
  G.hops = hops;
  G.capped = res.capped;
  CURDATA = { els: res.els, rels: res.rels, diags: [] };
  G.keepFilters = true;
  G.built = false;
  initGraph();
}

function filterRows(inp) {
  var q = (inp.value || '').toLowerCase();
  var wrap = findUp(inp, 'vp-list') || el('vp-list') || document;
  var tables = wrap.querySelectorAll('table.data');
  for (var t = 0; t < tables.length; t++) {
    var tb = tables[t].getElementsByTagName('tbody')[0];
    if (!tb) continue;
    var rows = tb.getElementsByTagName('tr');
    for (var r = 0; r < rows.length; r++) {
      rows[r].style.display = (!q || rows[r].textContent.toLowerCase().indexOf(q) >= 0) ? '' : 'none';
    }
  }
}

/* ---------- Ansicht Umschalten (Liste / Graph) ---------- */
function setVPMode(m) {
  VPMODE = m;
  var scope = (CURVIEW === 'explorer') ? el('pkgmain') : el('vpbox');
  if (!scope) scope = document;
  var l = scope.querySelector('#vp-list, .vp-list'), g = scope.querySelector('#vp-graph, .vp-graph');
  if (l) { l.id = 'vp-list'; l.style.display = m === 'list' ? 'block' : 'none'; }
  if (g) { g.id = 'vp-graph'; g.style.display = m === 'graph' ? 'block' : 'none'; }
  var bl = scope.querySelector('#btn-mode-list'), bg = scope.querySelector('#btn-mode-graph');
  if (bl) bl.className = m === 'list' ? 'on' : '';
  if (bg) bg.className = m === 'graph' ? 'on' : '';
  if (m === 'graph' && g) initGraph(g);
}

/* ---------- Klickbares EA-Diagramm als SVG rendern ---------- */
function renderDiagram(diag, host) {
  if (!host) return;
  var objs = DIAGOBJ[diag.id] || [];
  var links = DIAGLINK[diag.id] || [];
  if (!objs.length) { host.innerHTML = '<div class="hint">Leeres Diagramm (keine platzierten Elemente).</div>'; return; }

  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  var i, o, rects = {};
  for (i = 0; i < objs.length; i++) {
    o = objs[i];
    var obj = OBJS[o.oid];
    if (!obj) continue;
    var x = o.l, y = -o.t, w = o.r - o.l, hgt = o.t - o.b;
    rects[o.oid] = { oid: o.oid, x: x, y: y, w: w, h: hgt, name: obj.name, st: obj.st, seq: o.seq || 0, type: obj.type };
    if (x < minX) minX = x;
    if (x + w > maxX) maxX = x + w;
    if (y < minY) minY = y;
    if (y + hgt > maxY) maxY = y + hgt;
  }
  if (minX === Infinity) { host.innerHTML = '<div class="hint">Leeres Diagramm.</div>'; return; }
  var pad = 20;
  var W = maxX - minX + 2 * pad, H = maxY - minY + 2 * pad;
  var fs = 11;
  var ox = -minX + pad, oy = -minY + pad;

  function clipseg(x1, y1, x2, y2, rx, ry, rw, rh) {
    var dx = x2 - x1, dy = y2 - y1, t = 1;
    if (dx > 0) t = Math.min(t, (rx + rw - x1) / dx); else if (dx < 0) t = Math.min(t, (rx - x1) / dx);
    if (dy > 0) t = Math.min(t, (ry + rh - y1) / dy); else if (dy < 0) t = Math.min(t, (ry - y1) / dy);
    return { x: x1 + dx * t, y: y1 + dy * t };
  }

  var parts = [];
  parts.push('<svg xmlns="http://www.w3.org/2000/svg" width="' + Math.round(W) + '" height="' + Math.round(H) + '" viewBox="0 0 ' + W + ' ' + H + '">');
  parts.push('<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#004471"/></marker></defs>');

  var cmap = DB._cmap || {};
  for (i = 0; i < links.length; i++) {
    var cn = cmap[links[i].cid];
    if (!cn) continue;
    var ra = rects[cn.a], rb = rects[cn.b];
    if (!ra || !rb || ra === rb) continue;
    var x1 = ra.x + ra.w / 2, y1 = ra.y + ra.h / 2, x2 = rb.x + rb.w / 2, y2 = rb.y + rb.h / 2;
    var p1 = clipseg(x1, y1, x2, y2, ra.x, ra.y, ra.w, ra.h);
    var p2 = clipseg(x2, y2, x1, y1, rb.x, rb.y, rb.w, rb.h);
    var mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
    parts.push('<line x1="' + (p1.x + ox).toFixed(1) + '" y1="' + (p1.y + oy).toFixed(1) + '" x2="' + (p2.x + ox).toFixed(1) + '" y2="' + (p2.y + oy).toFixed(1) + '" stroke="#004471" stroke-width="1.3" marker-end="url(#arr)"/>');
    var llen = Math.sqrt((p2.x - p1.x) * (p2.x - p1.x) + (p2.y - p1.y) * (p2.y - p1.y));
    if (cn.st && llen > 85) {
      parts.push('<text x="' + (mx + ox).toFixed(1) + '" y="' + ((my + oy) - 3).toFixed(1) + '" font-size="8.5" fill="#475569" text-anchor="middle" style="paint-order:stroke;stroke:#FFFFFF;stroke-width:2.5px">' + esc(cn.st.length > 28 ? cn.st.substring(0, 26) + '…' : cn.st) + '</text>');
    }
  }

  var list = [];
  for (var key in rects) { if (rects.hasOwnProperty(key)) list.push(rects[key]); }
  list.sort(function (a, b) { return a.seq - b.seq; });
  for (var bi = 0; bi < list.length; bi++) {
    var rc = list[bi];
    if (!rc.name && !rc.st) continue;
    if (/^proxyconn?ector$/i.test(rc.st)) continue;
    var isBoundary = (rc.type === 'Boundary');
    var isLane = /^(pool|lane)$/i.test(rc.st);
    var fill = stFill(rc.st), dash = '', stroke = stColor(rc.st);
    if (isBoundary) { fill = 'none'; dash = ' stroke-dasharray="5 4"'; stroke = '#8AA0B0'; }
    else if (isLane) { fill = '#EEF4F8'; stroke = '#004471'; }
    var clickAttr = (!isBoundary && rc.oid) ? ' class="diag-node" onclick="openElement(\'' + rc.oid + '\')"' : '';
    parts.push('<g' + clickAttr + '><title>' + esc(rc.name + (rc.st ? '  «' + rc.st + '»' : '') + ' — Klick öffnet Element-Steckbrief') + '</title>');
    parts.push('<rect x="' + (rc.x + ox).toFixed(1) + '" y="' + (rc.y + oy).toFixed(1) + '" width="' + rc.w.toFixed(1) + '" height="' + rc.h.toFixed(1) + '" rx="4" fill="' + fill + '" stroke="' + stroke + '" stroke-width="1.4"' + dash + '/>');
    var nm = rc.name.replace(/\r?\n/g, ' ');
    if (rc.st && !isBoundary && rc.w >= 58) {
      var bandTxt = '«' + rc.st + '»';
      if (isLane && nm) bandTxt = '«' + rc.st + '» ' + nm;
      var maxB = Math.max(6, Math.floor((rc.w - 10) / 4.6));
      if (bandTxt.length > maxB) bandTxt = bandTxt.substring(0, Math.max(5, maxB - 1)) + '…';
      parts.push('<rect x="' + (rc.x + ox).toFixed(1) + '" y="' + (rc.y + oy).toFixed(1) + '" width="' + rc.w.toFixed(1) + '" height="13" rx="3" fill="' + stroke + '" opacity="0.14"/>');
      parts.push('<text x="' + (rc.x + ox + rc.w / 2).toFixed(1) + '" y="' + (rc.y + oy + 9.5).toFixed(1) + '" font-size="7.5" font-weight="600" fill="' + stroke + '" text-anchor="middle">' + esc(bandTxt) + '</text>');
    }
    if (isBoundary) {
      var maxL = Math.max(6, Math.floor((rc.w - 10) / (fs * 0.66)));
      var lab = nm.length > maxL ? nm.substring(0, Math.max(3, maxL - 1)) + '…' : nm;
      parts.push('<text x="' + (rc.x + ox + 6).toFixed(1) + '" y="' + (rc.y + oy + 12).toFixed(1) + '" font-size="' + fs.toFixed(1) + '" font-weight="600" fill="#5A7285" text-anchor="start">' + esc(lab) + '</text>');
    } else if (isLane) {
      /* Name im Band */
    } else if (rc.w < 72) {
      var shortN = nm.length > 24 ? nm.substring(0, 22) + '…' : nm;
      parts.push('<text x="' + (rc.x + ox + rc.w + 4).toFixed(1) + '" y="' + (rc.y + oy + rc.h / 2 + 3).toFixed(1) + '" font-size="8.5" fill="#1A1A1A" text-anchor="start">' + esc(shortN) + '</text>');
    } else {
      var lines = [];
      var maxc = Math.max(6, Math.floor((rc.w - 8) / (fs * 0.66)));
      if (nm.length <= maxc) { lines.push(nm); }
      else {
        var cut = nm.lastIndexOf(' ', maxc);
        if (cut < 4) cut = maxc;
        lines.push(nm.substring(0, cut));
        var rest = nm.substring(cut + 1);
        if (rest.length > maxc) rest = rest.substring(0, Math.max(1, maxc - 1)) + '…';
        lines.push(rest);
      }
      var ty = rc.y + oy + 13 + (rc.h - 15) / 2 - (lines.length - 1) * (fs * 0.62);
      for (var li = 0; li < lines.length; li++) {
        parts.push('<text x="' + (rc.x + ox + rc.w / 2).toFixed(1) + '" y="' + (ty + li * fs * 1.2).toFixed(1) + '" font-size="' + fs.toFixed(1) + '" font-weight="600" fill="#1A1A1A" text-anchor="middle">' + esc(lines[li]) + '</text>');
      }
    }
    parts.push('</g>');
  }
  parts.push('</svg>');
  host.innerHTML = parts.join('');
}

/* ================================================================
   PRÄGNANTE GRAPH-VISUALISIERUNG v3.0
   (Manuelle Knotenzahl + Schieberegler step=1 + 3 Layouts + PNG/Excel)
   ================================================================ */
function openGlobalGraph() {
  /* Wenn noch keine spezifische Sicht geladen oder der Nutzer auf den Graph-Reiter klickt:
     Aktuelle Auswahl (oder das gesamte Modell) im großen Graph-Modus öffnen */
  if (!CURDATA || !CURDATA.els || !CURDATA.els.length) {
    var allEls = [];
    for (var oid in OBJS) {
      if (!OBJS.hasOwnProperty(oid)) continue;
      var o = OBJS[oid];
      if (o.type === 'Boundary' || /^proxyconn?ector$/i.test(o.st)) continue;
      allEls.push(o);
    }
    CURDATA = { els: allEls, rels: CONS.slice(0), diags: DIAGS };
    EXPCTX = { fname: 'Gesamtmodell_Graph', kind: 'Gesamtmodell', label: 'Gesamtarchitektur: ' + MODELLNAME };
    PRINTCTX = 'Gesamtarchitektur-Graph: ' + MODELLNAME;
    G.mode = 'all'; G.root = null; G.built = false;
  }
  var h = [];
  h.push('<div class="crumb"><a href="javascript:showView(\'explorer\')">🧭 Erkunden</a> &nbsp;·&nbsp; <a href="javascript:showView(\'diags\')">🖼️ Sichten</a> &nbsp;▸&nbsp; <b>🕸️ Interaktiver Architektur-Graph</b></div>');
  h.push('<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px">' +
    '<h2>🕸️ Architektur-Graph: ' + esc((EXPCTX && EXPCTX.label) || MODELLNAME) + '</h2>' +
    '<div>' +
      '<button class="btn-sm" onclick="loadFullModelIntoGraph()">🌐 Gesamtes Modell in den Graph laden (' + Object.keys(OBJS).length + ' Elemente)</button> ' +
      '<button class="btn-sm amber" onclick="exportGraphPNG()">📸 Graph als PNG</button> ' +
      '<button class="btn-sm green" onclick="exportGraphXLSX()">📊 Graph als Excel (.xlsx)</button>' +
    '</div></div>');
  h.push('<div class="vp-graph" id="vp-graph" style="display:block"></div>');
  el('vpbox').innerHTML = h.join('');
  showView('vp', 'graphhub');
  VPMODE = 'graph';
  G.built = false;
  initGraph(el('vp-graph'));
}

function loadFullModelIntoGraph() {
  var allEls = [];
  for (var oid in OBJS) {
    if (!OBJS.hasOwnProperty(oid)) continue;
    var o = OBJS[oid];
    if (o.type === 'Boundary' || /^proxyconn?ector$/i.test(o.st)) continue;
    allEls.push(o);
  }
  CURDATA = { els: allEls, rels: CONS.slice(0), diags: DIAGS };
  EXPCTX = { fname: 'Gesamtmodell_Graph', kind: 'Gesamtmodell', label: 'Gesamtarchitektur: ' + MODELLNAME };
  PRINTCTX = 'Gesamtarchitektur-Graph: ' + MODELLNAME;
  G.mode = 'all'; G.root = null; G.built = false;
  openGlobalGraph();
}

function getActiveGraphHost() {
  if (CURVIEW === 'explorer' && el('pkgmain')) {
    var g1 = el('pkgmain').querySelector('#vp-graph');
    if (g1) return g1;
  }
  return el('vp-graph');
}

function initGraph(hostOverride) {
  var host = hostOverride || getActiveGraphHost();
  if (!host) return;
  G.hostEl = host;

  var i;
  var nodes = [], byId = {};
  for (i = 0; i < CURDATA.els.length; i++) {
    var o = CURDATA.els[i];
    if (o.type === 'Boundary' || /^proxyconn?ector$/i.test(o.st)) continue;
    var n = { id: String(o.id), name: o.name, st: o.st, alias: o.alias, pkg: o.pkg, deg: 0, x: 0, y: 0, dx: 0, dy: 0 };
    nodes.push(n); byId[String(o.id)] = n;
    if (!G.keepFilters || !G.f.types.hasOwnProperty(o.st)) G.f.types[o.st] = true;
  }
  var links = [], relTypes = {};
  for (i = 0; i < CURDATA.rels.length; i++) {
    var c = CURDATA.rels[i];
    var na = byId[String(c.a)], nb = byId[String(c.b)];
    if (!na || !nb || na === nb) continue;
    var rst = c.st || c.type || 'Verbindung';
    links.push({ a: String(c.a), b: String(c.b), st: rst, na: na, nb: nb });
    relTypes[rst] = (relTypes[rst] || 0) + 1;
  }
  for (i = 0; i < links.length; i++) { links[i].na.deg++; links[i].nb.deg++; }

  var typeCount = {};
  for (i = 0; i < nodes.length; i++) typeCount[nodes[i].st] = (typeCount[nodes[i].st] || 0) + 1;

  G.baseNodes = nodes;
  G.baseLinks = links;
  G.typeCount = typeCount;
  G.relTypes = relTypes;

  if (!G.keepFilters) {
    G.pos = {};
    var defMax = Math.min(Math.max(nodes.length, 10), 120);
    G.f = { q: '', types: {}, rels: {}, only: links.length > 0, maxN: defMax, hops: 0 };
    for (var tk in typeCount) if (typeCount.hasOwnProperty(tk)) G.f.types[tk] = true;
    for (var rk in relTypes) if (relTypes.hasOwnProperty(rk)) G.f.rels[rk] = true;
  }
  G.keepFilters = false;
  G.built = true;

  G.nbr = {};
  for (i = 0; i < links.length; i++) {
    var l = links[i];
    if (!G.nbr[l.a]) G.nbr[l.a] = [];
    if (!G.nbr[l.b]) G.nbr[l.b] = [];
    G.nbr[l.a].push({ id: l.b, st: l.st, dir: 1 });
    G.nbr[l.b].push({ id: l.a, st: l.st, dir: -1 });
  }

  if (G.mode === 'elem' && G.root && byId[String(G.root)]) {
    G.focus = String(G.root);
    var fset0 = {}; fset0[String(G.root)] = true;
    var rn0 = G.nbr[String(G.root)] || [];
    for (i = 0; i < rn0.length; i++) fset0[rn0[i].id] = true;
    G.fset = fset0;
  } else {
    G.focus = null; G.fset = null;
  }

  buildGraphPanel(host);
  syncGraphPanelUI();
  applyGraphFilters(true);
}

function syncGraphPanelUI() {
  var slider = el('gmax'), numInp = el('gmaxnum');
  if (slider) slider.value = G.f.maxN;
  if (numInp) numInp.value = G.f.maxN;
  if (el('gq')) el('gq').value = G.f.q;
  if (el('gonly')) el('gonly').checked = G.f.only;
}

/* Synchronisierte Steuerung: Schieberegler + Manuelles Zahlenfeld + Schnellwahl-Pills! */
function graphSetMaxN(val, fromInput) {
  var total = Math.max(1, G.baseNodes.length || 500);
  var n = parseInt(val, 10);
  if (isNaN(n) || n < 1) n = 1;
  if (n > 5000) n = 5000;
  G.f.maxN = n;
  G.pos = {};
  var slider = el('gmax'), numInp = el('gmaxnum');
  if (slider) {
    if (n > parseInt(slider.max, 10)) slider.max = String(n);
    if (fromInput !== 'slider') slider.value = String(n);
  }
  if (numInp && String(numInp.value) !== String(n)) {
    numInp.value = String(n);
  }
  var pills = document.querySelectorAll('.gpill');
  for (var i = 0; i < pills.length; i++) {
    var pv = parseInt(pills[i].getAttribute('data-n'), 10);
    pills[i].className = 'gpill' + (pv === n ? ' on' : '');
  }
  applyGraphFilters(true);
}

function graphSetLayout(lay) {
  G.layout = lay;
  G.pos = {};
  var btns = document.querySelectorAll('.glay-btn');
  for (var i = 0; i < btns.length; i++) {
    btns[i].className = (btns[i].getAttribute('data-lay') === lay) ? 'on' : '';
  }
  graphSim();
}

function graphSetLblMode(m) {
  G.lblMode = m;
  drawGraph(true);
}

function graphToggleEdgeLbl(cb) {
  G.showEdgeLbl = !!cb.checked;
  drawGraph(true);
}

function buildGraphPanel(host) {
  host = host || getActiveGraphHost();
  if (!host) return;
  var maxSlider = Math.max(50, G.baseNodes.length || 300);
  var i, k, h = [];
  h.push('<div class="gwrap">');
  h.push('<div class="gpanel">');
  h.push('<div class="ghead">🎛️ Graph-Steuerung &amp; Filter</div>');

  h.push('<div class="grow"><input id="gq" class="gq" placeholder="🔍 Knoten im Graph filtern …" oninput="graphQuickChange()"></div>');
  h.push('<div class="grow"><label class="gcb"><input type="checkbox" id="gonly" ' + (G.f.only ? 'checked ' : '') + 'onchange="applyGraphFilters(true)"> Nur verbundene Knoten zeigen</label></div>');

  /* FEINGRANULARE KNOTENANZAHL: Manuelles Zahlenfeld + Schieberegler (step=1) + Schnellwahl */
  h.push('<div class="grow" style="background:#F8FAFC;border:1px solid var(--border);border-radius:8px;padding:8px 10px">');
  h.push('<div class="g-num-row">' +
    '<label for="gmaxnum" style="font-weight:700;color:var(--bw-blue);font-size:12px">Max. Knotenanzahl:</label>' +
    '<input type="number" id="gmaxnum" class="g-num-inp" min="1" max="5000" step="1" value="' + G.f.maxN + '" title="Knotenanzahl manuell eingeben" oninput="graphSetMaxN(this.value, \'number\')">' +
  '</div>');
  h.push('<input type="range" id="gmax" style="width:100%;accent-color:var(--bw-blue);cursor:pointer" min="1" max="' + maxSlider + '" step="1" value="' + G.f.maxN + '" oninput="graphSetMaxN(this.value, \'slider\')">');
  var allN = Math.max(1, G.baseNodes.length);
  h.push('<div class="g-quick-pills">' +
    '<span class="gpill" data-n="15" onclick="graphSetMaxN(15)">15</span>' +
    '<span class="gpill" data-n="30" onclick="graphSetMaxN(30)">30</span>' +
    '<span class="gpill" data-n="50" onclick="graphSetMaxN(50)">50</span>' +
    '<span class="gpill" data-n="100" onclick="graphSetMaxN(100)">100</span>' +
    '<span class="gpill" data-n="250" onclick="graphSetMaxN(250)">250</span>' +
    '<span class="gpill" data-n="' + allN + '" onclick="graphSetMaxN(' + allN + ')">Alle (' + allN + ')</span>' +
  '</div>');
  h.push('</div>');

  /* Layout-Wahl */
  h.push('<div class="gsect"><b>Darstellungs-Layout</b>' +
    '<div class="gbtns" style="margin-top:4px">' +
      '<button class="glay-btn' + (G.layout === 'force' ? ' on' : '') + '" data-lay="force" onclick="graphSetLayout(\'force\')" title="Kraftbasiertes Cluster-Netzwerk">⚡ Netzwerk</button>' +
      '<button class="glay-btn' + (G.layout === 'layered' ? ' on' : '') + '" data-lay="layered" onclick="graphSetLayout(\'layered\')" title="Geordnet nach Architektur-Schichten (Konzept → Service → Logisch → Technik)">🏛️ Schichten</button>' +
      '<button class="glay-btn' + (G.layout === 'radial' ? ' on' : '') + '" data-lay="radial" onclick="graphSetLayout(\'radial\')" title="Konzentrische Ringe um das zentrale Element">🎯 Radial</button>' +
    '</div></div>');

  if (G.mode === 'elem' && G.root) {
    var rn = OBJS[String(G.root)];
    h.push('<div class="gsect"><b>Umfeld-Tiefe von:</b><div class="dim">' + esc(rn ? rn.name : '') + '</div>');
    h.push('<div class="gbtns" style="margin-top:4px">Ebenen: ' +
      '<button class="' + (G.hops === 1 ? 'on' : '') + '" onclick="elementExpand(1)">1 Ebene</button>' +
      '<button class="' + (G.hops === 2 ? 'on' : '') + '" onclick="elementExpand(2)">2 Ebenen</button>' +
      '<button class="' + (G.hops === 3 ? 'on' : '') + '" onclick="elementExpand(3)">3 Ebenen</button>' +
    '</div>');
    h.push('<div class="dim" id="glvl">aktuell: ' + G.hops + ' Ebene(n) · ' + G.baseNodes.length + ' Knoten</div></div>');
  }

  h.push('<div class="gsect"><b>Elementtypen</b> <span class="dim">(Klick = ein/aus)</span>' +
    '<div style="margin:3px 0"><a href="javascript:graphAllTypes(true)" style="font-size:11px;color:var(--bw-blue)">Alle an</a> · <a href="javascript:graphAllTypes(false)" style="font-size:11px;color:var(--bw-blue)">Alle aus</a></div>' +
    '<div class="gchips" id="gtypes"></div></div>');
  h.push('<div class="gsect"><b>Beziehungstypen</b><div class="gchips" id="grels"></div></div>');

  h.push('<div class="gsect"><b>Fokus &amp; Isolation</b><div class="dim" id="gfocus">Knoten anklicken für Details (Doppelklick = Nachbarschaft isolieren)</div>' +
    '<div class="grow" id="ghops" style="display:' + (G.focus ? 'block' : 'none') + '">Nachbarschaft isolieren: <select id="ghopsel" onchange="applyGraphFilters(true)"><option value="0">Aus (alle zeigen)</option><option value="1">1 Ebene um Fokus</option><option value="2">2 Ebenen um Fokus</option><option value="3">3 Ebenen um Fokus</option></select></div></div>');
  h.push('<div class="gsect dim" id="gstat"></div>');
  h.push('</div>'); /* /gpanel */

  /* Rechte Hauptspalte: Toolbar + Farblegende + Großer Canvas + Info-Steckbrief */
  h.push('<div class="gmain">');
  h.push('<div class="gtoolbar">' +
    '<div class="gbtns">' +
      '<b>Zoom &amp; Beschriftung:</b> ' +
      '<button onclick="graphZoom(0.5, 0.5, 0.82)">🔍＋</button>' +
      '<button onclick="graphZoom(0.5, 0.5, 1.22)">🔍－</button>' +
      '<button onclick="graphResetView()">⛶ Einpassen</button>' +
      '<button onclick="graphRelayout()">🔄 Neu berechnen</button>' +
      '<span style="margin-left:6px">Labels: ' +
        '<select onchange="graphSetLblMode(this.value)" style="padding:3px 6px;border:1px solid #C6D2DA;border-radius:5px;font-size:11.5px">' +
          '<option value="auto"' + (G.lblMode === 'auto' ? ' selected' : '') + '>Automatisch</option>' +
          '<option value="all"' + (G.lblMode === 'all' ? ' selected' : '') + '>Alle Knoten beschriften</option>' +
          '<option value="hubs"' + (G.lblMode === 'hubs' ? ' selected' : '') + '>Nur Hauptknoten</option>' +
        '</select>' +
      '</span> ' +
      '<label style="margin-left:6px;cursor:pointer"><input type="checkbox" ' + (G.showEdgeLbl ? 'checked ' : '') + 'onchange="graphToggleEdgeLbl(this)"> Beziehungsnamen an Pfeilen</label>' +
    '</div>' +
    '<div class="gbtns">' +
      '<button style="background:#FEF3C7;color:#92400E;border-color:#F59E0B" onclick="exportGraphPNG()">📸 Graph als PNG</button>' +
      '<button style="background:#E6F4F1;color:#065F46;border-color:#10B981" onclick="exportGraphXLSX()">📊 Graph als Excel (.xlsx)</button>' +
    '</div>' +
  '</div>');

  /* Farblegende der Architekturschichten */
  h.push('<div class="glegend"><span title="Farben gemäß ADMBw/NAFv4: hell = Elementfüllung, Rand = Schichtfarbe"><b>Schicht-Farben (ADMBw/NAFv4):</b></span>');
  for (var ck in CAT_META) {
    if (!CAT_META.hasOwnProperty(ck)) continue;
    h.push('<span class="gleg-item"><i class="gleg-dot" style="background:' + CAT_META[ck].fill + ';border:2px solid ' + CAT_META[ck].color + ';border-radius:50%"></i>' + esc(CAT_META[ck].label) + '</span>');
  }
  h.push('</div>');

  h.push('<div class="gcanvas" id="gcanvas"><div class="hint" style="padding:24px">Graph-Layout wird berechnet …</div></div>');
  h.push('<div class="ginfo" id="ginfo" style="display:none"></div>');
  h.push('</div>'); /* /gmain */
  h.push('</div>'); /* /gwrap */
  host.innerHTML = h.join('');

  var tc = [], t, types = [];
  for (k in G.typeCount) { if (G.typeCount.hasOwnProperty(k)) types.push(k); }
  types.sort(function (a, b) { return G.typeCount[b] - G.typeCount[a]; });
  for (i = 0; i < types.length; i++) {
    t = types[i];
    tc.push('<span class="gchip' + (G.f.types[t] ? '' : ' off') + '" onclick="graphToggleType(\'' + esc(t).replace(/'/g, '&#39;') + '\')"><i style="background:' + stColor(t) + '"></i>' + esc(t || '(ohne)') + ' <em>' + G.typeCount[t] + '</em></span>');
  }
  if (el('gtypes')) el('gtypes').innerHTML = tc.join('') || '<span class="dim">—</span>';

  var rc = [], rels = [];
  for (k in G.relTypes) { if (G.relTypes.hasOwnProperty(k)) rels.push(k); }
  rels.sort(function (a, b) { return G.relTypes[b] - G.relTypes[a]; });
  for (i = 0; i < rels.length; i++) {
    t = rels[i];
    if (!G.f.rels.hasOwnProperty(t)) G.f.rels[t] = true;
    rc.push('<span class="gchip rel' + (G.f.rels[t] ? '' : ' off') + '" onclick="graphToggleRel(\'' + esc(t).replace(/'/g, '&#39;') + '\')">' + esc(t) + ' <em>' + G.relTypes[t] + '</em></span>');
  }
  if (el('grels')) el('grels').innerHTML = rc.join('') || '<span class="dim">—</span>';
}

function graphAllTypes(on) {
  for (var k in G.typeCount) {
    if (G.typeCount.hasOwnProperty(k)) G.f.types[k] = !!on;
  }
  buildGraphPanel(G.hostEl);
  syncGraphPanelUI();
  applyGraphFilters(true);
}

function graphQuickChange() {
  var q = el('gq'); if (q) G.f.q = q.value;
  applyGraphFilters(false);
}
function graphToggleType(t) {
  G.f.types[t] = !G.f.types[t];
  buildGraphPanel(G.hostEl);
  syncGraphPanelUI();
  applyGraphFilters(false);
}
function graphToggleRel(t) {
  G.f.rels[t] = !G.f.rels[t];
  buildGraphPanel(G.hostEl);
  syncGraphPanelUI();
  applyGraphFilters(false);
}

function applyGraphFilters(doLayout) {
  var i, j;
  var only = el('gonly') ? el('gonly').checked : G.f.only;
  G.f.only = only;
  var q = (el('gq') ? el('gq').value : G.f.q) || '';
  G.f.q = q;
  var ql = q.toLowerCase();

  var links = [];
  for (i = 0; i < G.baseLinks.length; i++) {
    if (G.f.rels[G.baseLinks[i].st] === false) continue;
    links.push(G.baseLinks[i]);
  }
  var nodeSet = {}, keep = [];
  for (i = 0; i < G.baseNodes.length; i++) {
    var n = G.baseNodes[i];
    if (!G.f.types[n.st]) continue;
    if (ql && (n.name + ' ' + n.alias + ' ' + n.st).toLowerCase().indexOf(ql) < 0) continue;
    nodeSet[n.id] = n;
    keep.push(n);
  }
  var flinks = [];
  for (i = 0; i < links.length; i++) {
    if (nodeSet[links[i].a] && nodeSet[links[i].b]) flinks.push(links[i]);
  }
  if (G.f.only && flinks.length > 0) {
    var deg = {};
    for (i = 0; i < flinks.length; i++) { deg[flinks[i].a] = (deg[flinks[i].a] || 0) + 1; deg[flinks[i].b] = (deg[flinks[i].b] || 0) + 1; }
    var keep2 = [];
    for (i = 0; i < keep.length; i++) {
      if (deg[keep[i].id]) keep2.push(keep[i]);
    }
    keep = keep2;
  }

  var hops = el('ghopsel') ? parseInt(el('ghopsel').value, 10) || 0 : G.f.hops;
  G.f.hops = hops;
  if (hops > 0 && G.focus) {
    var allowed = {}, frontier = [G.focus];
    allowed[G.focus] = true;
    for (var s = 0; s < hops; s++) {
      var nf = [];
      for (i = 0; i < frontier.length; i++) {
        var nb = G.nbr[frontier[i]] || [];
        for (j = 0; j < nb.length; j++) {
          if (!allowed[nb[j].id]) { allowed[nb[j].id] = true; nf.push(nb[j].id); }
        }
      }
      frontier = nf;
    }
    var keep3 = [];
    for (i = 0; i < keep.length; i++) { if (allowed[keep[i].id]) keep3.push(keep[i]); }
    keep = keep3;
    var fl2 = [];
    for (i = 0; i < flinks.length; i++) { if (allowed[flinks[i].a] && allowed[flinks[i].b]) fl2.push(flinks[i]); }
    flinks = fl2;
  }

  /* Max. Knoten (Top nach Verbindungsgrad + verbundene Nachbarn bevorzugen) */
  if (keep.length > G.f.maxN) {
    var sorted = keep.slice(0);
    sorted.sort(function (a, b) {
      if (G.focus) {
        if (a.id === G.focus) return -1;
        if (b.id === G.focus) return 1;
      }
      return b.deg - a.deg;
    });
    var adjMap = {};
    for (i = 0; i < flinks.length; i++) {
      if (!adjMap[flinks[i].a]) adjMap[flinks[i].a] = [];
      if (!adjMap[flinks[i].b]) adjMap[flinks[i].b] = [];
      adjMap[flinks[i].a].push(nodeSet[flinks[i].b]);
      adjMap[flinks[i].b].push(nodeSet[flinks[i].a]);
    }
    var cut = {}, fin = [];
    for (i = 0; i < sorted.length && fin.length < G.f.maxN; i++) {
      var seed = sorted[i];
      if (!cut[seed.id]) {
        cut[seed.id] = seed;
        fin.push(seed);
      }
      if (G.f.only && adjMap[seed.id]) {
        var nbs = adjMap[seed.id].slice(0).sort(function (x, y) { return y.deg - x.deg; });
        for (j = 0; j < nbs.length && fin.length < G.f.maxN && j < 5; j++) {
          if (nbs[j] && !cut[nbs[j].id]) {
            cut[nbs[j].id] = nbs[j];
            fin.push(nbs[j]);
          }
        }
      }
    }
    keep = fin;
    var fl3 = [];
    for (i = 0; i < flinks.length; i++) { if (cut[flinks[i].a] && cut[flinks[i].b]) fl3.push(flinks[i]); }
    flinks = fl3;
  }

  /* Aktuellen Sicht-Grad je Knoten aktualisieren */
  var vdeg = {};
  for (i = 0; i < flinks.length; i++) {
    vdeg[flinks[i].a] = (vdeg[flinks[i].a] || 0) + 1;
    vdeg[flinks[i].b] = (vdeg[flinks[i].b] || 0) + 1;
  }
  for (i = 0; i < keep.length; i++) keep[i].vdeg = vdeg[keep[i].id] || 0;

  G.viewNodes = keep;
  G.viewLinks = flinks;

  var stat = el('gstat');
  if (stat) stat.innerHTML = 'Angezeigt: <b>' + keep.length + '</b> von ' + G.baseNodes.length + ' Knoten · <b>' + flinks.length + '</b> von ' + G.baseLinks.length + ' Beziehungen';

  graphSim();
}

function layoutLayered(nodes) {
  /* Ordnet Knoten in 5 klaren horizontalen Architektur-Schichten (Top-Down) an */
  var bands = [[], [], [], [], []], i;
  for (i = 0; i < nodes.length; i++) {
    var cat = archCategory(nodes[i].st);
    var r = (CAT_META[cat] && CAT_META[cat].rank != null) ? CAT_META[cat].rank : 3;
    bands[r].push(nodes[i]);
  }
  var yStep = 145;
  var curY = -220;
  for (var b = 0; b < bands.length; b++) {
    var row = bands[b];
    if (!row.length) continue;
    row.sort(function (x, y) { return (y.vdeg || y.deg) - (x.vdeg || x.deg); });
    var cols = Math.min(row.length, Math.max(6, Math.ceil(Math.sqrt(row.length) * 2.2)));
    var xStep = 145;
    for (i = 0; i < row.length; i++) {
      var rIdx = Math.floor(i / cols);
      var cIdx = i % cols;
      var rowCount = Math.min(cols, row.length - rIdx * cols);
      row[i].x = (cIdx - (rowCount - 1) / 2) * xStep;
      row[i].y = curY + rIdx * 68;
      G.pos[row[i].id] = { x: row[i].x, y: row[i].y };
    }
    curY += yStep + Math.floor((row.length - 1) / cols) * 68;
  }
}

function layoutRadial(nodes, links) {
  /* Konzentrische Ringe um das Fokus-Element bzw. den stärksten Hub */
  var centerId = G.focus;
  var i, j;
  if (!centerId || ! nodes.some(function (n) { return n.id === centerId; })) {
    var best = nodes[0];
    for (i = 1; i < nodes.length; i++) if ((nodes[i].vdeg || nodes[i].deg) > (best.vdeg || best.deg)) best = nodes[i];
    centerId = best ? best.id : null;
  }
  var dist = {}, adj = {};
  for (i = 0; i < nodes.length; i++) adj[nodes[i].id] = [];
  for (i = 0; i < links.length; i++) {
    if (adj[links[i].a] && adj[links[i].b]) {
      adj[links[i].a].push(links[i].b);
      adj[links[i].b].push(links[i].a);
    }
  }
  if (centerId) {
    dist[centerId] = 0;
    var q = [centerId];
    while (q.length) {
      var cur = q.shift();
      var nbs = adj[cur] || [];
      for (i = 0; i < nbs.length; i++) {
        if (dist[nbs[i]] === undefined) {
          dist[nbs[i]] = dist[cur] + 1;
          q.push(nbs[i]);
        }
      }
    }
  }
  var rings = [[], [], [], [], []];
  for (i = 0; i < nodes.length; i++) {
    var d = dist[nodes[i].id];
    if (d === undefined || d > 4) d = 4;
    rings[d].push(nodes[i]);
  }
  for (var r = 0; r < rings.length; r++) {
    var list = rings[r];
    if (!list.length) continue;
    if (r === 0) {
      list[0].x = 0; list[0].y = 0;
      G.pos[list[0].id] = { x: 0, y: 0 };
    } else {
      var rad = r * 145 + Math.max(0, list.length - 12) * 3.5;
      for (j = 0; j < list.length; j++) {
        var ang = (j / list.length) * Math.PI * 2 - Math.PI / 2;
        list[j].x = Math.cos(ang) * rad;
        list[j].y = Math.sin(ang) * rad;
        G.pos[list[j].id] = { x: list[j].x, y: list[j].y };
      }
    }
  }
}

function graphSim() {
  var nodes = G.viewNodes;
  if (G.simTimer) { clearTimeout(G.simTimer); G.simTimer = null; }
  if (!nodes.length) { drawGraph(true); return; }

  if (G.layout === 'layered') {
    layoutLayered(nodes);
    G._autoFit = true;
    drawGraph(true);
    return;
  }
  if (G.layout === 'radial') {
    layoutRadial(nodes, G.viewLinks);
    G._autoFit = true;
    drawGraph(true);
    return;
  }

  var i;
  var R = Math.max(120, 28 * Math.sqrt(nodes.length));
  for (i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    if (G.pos[n.id]) { n.x = G.pos[n.id].x; n.y = G.pos[n.id].y; }
    else {
      var ang = (i / nodes.length) * Math.PI * 2;
      var jit = ((i * 2654435761) % 1000) / 1000 - 0.5;
      n.x = Math.cos(ang) * R * (1 + jit * 0.15);
      n.y = Math.sin(ang) * R * (1 + jit * 0.15);
    }
  }
  var iters = nodes.length > 260 ? 150 : (nodes.length > 120 ? 200 : 280);
  var k = 96;
  var t0 = k * 1.3;
  var iter = 0;
  function stepSim() {
    var chunk = Math.max(6, Math.round(3000 / Math.max(1, nodes.length)));
    var temp;
    for (var s = 0; s < chunk && iter < iters; s++, iter++) {
      temp = t0 * (1 - iter / iters) + 0.3;
      simulateOnce(nodes, G.viewLinks, k, temp);
    }
    drawGraph(false);
    if (iter < iters) { G.simTimer = setTimeout(stepSim, 6); }
    else {
      G.simTimer = null;
      /* Ausreißer sanft begrenzen + Mindestabstand (Collision-Push) gegen Label-Überlappung */
      var maxR = Math.max(260, 62 * Math.sqrt(nodes.length)), q, p2;
      for (q = 0; q < nodes.length; q++) {
        var dist0 = Math.sqrt(nodes[q].x * nodes[q].x + nodes[q].y * nodes[q].y);
        if (dist0 > maxR) {
          nodes[q].x = (nodes[q].x / dist0) * maxR;
          nodes[q].y = (nodes[q].y / dist0) * maxR;
        }
      }
      var boxW = 165, boxH = 38;
      for (var pass = 0; pass < 14; pass++) {
        for (q = 0; q < nodes.length; q++) {
          for (p2 = q + 1; p2 < nodes.length; p2++) {
            var dx = nodes[q].x - nodes[p2].x, dy = nodes[q].y - nodes[p2].y;
            var adx = Math.abs(dx), ady = Math.abs(dy);
            if (adx < boxW && ady < boxH) {
              var ox = (boxW - adx) * 0.52, oy = (boxH - ady) * 0.52;
              if (ox < oy) {
                var sx = dx >= 0 ? 1 : -1;
                nodes[q].x += sx * ox * 0.5; nodes[p2].x -= sx * ox * 0.5;
              } else {
                var sy = dy >= 0 ? 1 : -1;
                nodes[q].y += sy * oy * 0.5; nodes[p2].y -= sy * oy * 0.5;
              }
            }
          }
        }
      }
      for (q = 0; q < nodes.length; q++) {
        G.pos[nodes[q].id] = { x: nodes[q].x, y: nodes[q].y };
      }
      G._autoFit = true;
      drawGraph(true);
    }
  }
  stepSim();
}

function simulateOnce(nodes, links, k, temp) {
  var i, j, dx, dy, d2, d, f, ux, uy, len, lim;
  var n = nodes.length;
  for (i = 0; i < n; i++) { nodes[i].dx = 0; nodes[i].dy = 0; }
  for (i = 0; i < n; i++) {
    var a = nodes[i];
    for (j = i + 1; j < n; j++) {
      var b = nodes[j];
      dx = a.x - b.x; dy = a.y - b.y;
      d2 = dx * dx + dy * dy;
      if (d2 < 1) { d2 = 1; dx = 0.05 + (i - j) * 0.01; dy = 0.05; }
      d = Math.sqrt(d2);
      f = (k * k * 1.1) / d;
      ux = dx / d; uy = dy / d;
      a.dx += ux * f; a.dy += uy * f;
      b.dx -= ux * f; b.dy -= uy * f;
    }
  }
  for (i = 0; i < links.length; i++) {
    var l = links[i];
    if (!l.na || !l.nb) continue;
    dx = l.nb.x - l.na.x; dy = l.nb.y - l.na.y;
    d2 = dx * dx + dy * dy; if (d2 < 1) d2 = 1;
    d = Math.sqrt(d2);
    f = d2 / k;
    ux = dx / d; uy = dy / d;
    l.na.dx += ux * f; l.na.dy += uy * f;
    l.nb.dx -= ux * f; l.nb.dy -= uy * f;
  }
  for (i = 0; i < n; i++) {
    var m = nodes[i];
    var grav = (m.vdeg && m.vdeg > 0) ? 0.14 : 0.42;
    m.dx += -m.x * grav;
    m.dy += -m.y * grav;
    len = Math.sqrt(m.dx * m.dx + m.dy * m.dy);
    if (len > 0) {
      lim = Math.min(len, temp);
      m.x += (m.dx / len) * lim;
      m.y += (m.dy / len) * lim;
    }
  }
}

function applyViewBox(svg) {
  if (!svg || !G.vb) return;
  svg.setAttribute('viewBox', G.vb.x.toFixed(1) + ' ' + G.vb.y.toFixed(1) + ' ' + G.vb.w.toFixed(1) + ' ' + G.vb.h.toFixed(1));
}
function graphFit() {
  var nodes = G.viewNodes;
  if (!nodes.length) { G.vb = { x: -100, y: -100, w: 200, h: 200 }; return; }
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    if (n.x < minX) minX = n.x; if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y; if (n.y > maxY) maxY = n.y;
  }
  var pad = 85;
  var w = maxX - minX + 2 * pad, h = maxY - minY + 2 * pad;
  if (w < 240) w = 240;
  if (h < 180) h = 180;
  G.vb = { x: minX - pad, y: minY - pad, w: w, h: h };
}
function graphResetView() {
  graphFit();
  applyViewBox(el('gsvg'));
}
function graphRelayout() {
  G.pos = {};
  graphSim();
}
function graphZoom(fx, fy, factor) {
  if (!G.vb) return;
  var vb = G.vb;
  var mx = vb.x + fx * vb.w, my = vb.y + fy * vb.h;
  var nw = vb.w * factor, nh = vb.h * factor;
  if (nw < 60 || nw > 25000) return;
  vb.x = mx - (mx - vb.x) * factor;
  vb.y = my - (my - vb.y) * factor;
  vb.w = nw; vb.h = nh;
  applyViewBox(el('gsvg'));
}

function drawGraph(final) {
  var host = el('gcanvas');
  if (!host) return;
  var nodes = G.viewNodes, links = G.viewLinks;
  if (!nodes.length) {
    host.innerHTML = '<div class="hint" style="padding:30px">Keine Knoten mit den aktuellen Filtern — bitte Filter anpassen oder „Nur verbundene Knoten“ deaktivieren.</div>';
    return;
  }
  var i;
  var showAll = (G.lblMode === 'all') || (G.lblMode === 'auto' && nodes.length <= 65);
  var degMin = G.lblMode === 'hubs' ? 4 : (nodes.length > 140 ? 5 : (nodes.length > 75 ? 3 : 2));
  var parts = [];
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    if (n.x < minX) minX = n.x; if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y; if (n.y > maxY) maxY = n.y;
  }
  var pad = 85;
  var bx = minX - pad, by = minY - pad, bw = (maxX - minX) + 2 * pad, bh = (maxY - minY) + 2 * pad;
  if (!G.vb || G._autoFit) { G.vb = { x: bx, y: by, w: Math.max(bw, 240), h: Math.max(bh, 180) }; G._autoFit = false; }

  parts.push('<svg id="gsvg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" viewBox="' + G.vb.x.toFixed(1) + ' ' + G.vb.y.toFixed(1) + ' ' + G.vb.w.toFixed(1) + ' ' + G.vb.h.toFixed(1) + '">');
  parts.push('<defs>' +
    '<marker id="garr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#94A3B8"/></marker>' +
    '<marker id="garrH" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#B45309"/></marker>' +
  '</defs>');

  /* Kanten */
  for (i = 0; i < links.length; i++) {
    var l = links[i];
    var hi = G.fset && G.fset[l.a] && G.fset[l.b];
    parts.push('<line class="gk' + (hi ? ' hi' : '') + '" x1="' + l.na.x.toFixed(1) + '" y1="' + l.na.y.toFixed(1) + '" x2="' + l.nb.x.toFixed(1) + '" y2="' + l.nb.y.toFixed(1) + '" marker-end="' + (hi ? 'url(#garrH)' : 'url(#garr)') + '"/>');
    if ((G.showEdgeLbl || hi) && l.st) {
      var mx = (l.na.x + l.nb.x) / 2, my = (l.na.y + l.nb.y) / 2;
      parts.push('<text class="gk-lbl" x="' + mx.toFixed(1) + '" y="' + (my - 3).toFixed(1) + '" text-anchor="middle">' + esc(shortLabel(l.st, 22)) + '</text>');
    }
  }

  /* Knoten (prägnant, mit Halo, Farb-Dot und Verbindungszahl) */
  for (i = 0; i < nodes.length; i++) {
    var nd = nodes[i];
    var degVal = nd.vdeg != null ? nd.vdeg : nd.deg;
    var r = 9 + Math.min(11, Math.sqrt(degVal) * 2.5);
    var dim = G.fset && !G.fset[nd.id];
    var sel = G.focus === nd.id;
    var col = stColor(nd.st), fl = stFill(nd.st);
    var showLbl = showAll || degVal >= degMin || sel || (G.fset && G.fset[nd.id]);
    var lbl = showLbl ? shortLabel(nd.name || '(ohne Name)', 28) : '';
    parts.push('<g class="gn' + (dim ? ' fdim' : '') + (sel ? ' fsel' : '') + '" data-oid="' + nd.id + '" transform="translate(' + nd.x.toFixed(1) + ',' + nd.y.toFixed(1) + ')">');
    if (sel) parts.push('<circle r="' + (r + 7).toFixed(1) + '" fill="none" stroke="#B45309" stroke-width="2.5" stroke-dasharray="4 2"/>');
    parts.push('<circle class="nshape" r="' + r.toFixed(1) + '" fill="' + fl + '" stroke="' + col + '"/>');
    if (degVal >= 1) {
      parts.push('<text y="3.5" text-anchor="middle" font-size="9" font-weight="700" fill="#1F2937" style="pointer-events:none">' + degVal + '</text>');
    }
    if (lbl) {
      parts.push('<text class="nlbl" y="' + (-r - 5).toFixed(1) + '" text-anchor="middle">' + esc(lbl) + '</text>');
      if ((sel || (G.fset && G.fset[nd.id])) && nd.st) {
        parts.push('<text class="nst" y="' + (r + 12).toFixed(1) + '" text-anchor="middle">«' + esc(shortLabel(nd.st, 22)) + '»</text>');
      }
    }
    parts.push('<title>' + esc(nd.name + (nd.st ? '  «' + nd.st + '»' : '') + ' (' + degVal + ' Verbindungen) — Klick: Fokus, Doppelklick: Nachbarschaft isolieren') + '</title>');
    parts.push('</g>');
  }
  parts.push('</svg>');
  host.innerHTML = parts.join('');

  var svg = el('gsvg');
  if (!svg) return;
  svg.addEventListener('mousedown', graphPanStart);
  svg.addEventListener('wheel', graphWheel, false);
  svg.addEventListener('click', graphClick);
  svg.addEventListener('dblclick', function (e) {
    var g = findUp(e.target, 'gn');
    if (!g) return;
    var oid = g.getAttribute('data-oid');
    G.focus = oid;
    var sel = el('ghopsel');
    if (sel && sel.value === '0') sel.value = '1';
    G._autoFit = true;
    applyGraphFilters(true);
  });
  if (final) renderGraphInfo();
}

var _pan = null, _panned = false;
function graphPanStart(e) {
  var svg = el('gsvg');
  if (!svg || !G.vb) return;
  var rect = svg.getBoundingClientRect();
  if (!rect.width) return;
  _panned = false;
  _pan = { sx: e.clientX, sy: e.clientY, vx: G.vb.x, vy: G.vb.y, kx: G.vb.w / rect.width, ky: G.vb.h / rect.height };
  window.addEventListener('mousemove', graphPanMove);
  window.addEventListener('mouseup', graphPanEnd);
}
function graphPanMove(e) {
  if (!_pan || !G.vb) return;
  if (Math.abs(e.clientX - _pan.sx) + Math.abs(e.clientY - _pan.sy) > 5) _panned = true;
  G.vb.x = _pan.vx - (e.clientX - _pan.sx) * _pan.kx;
  G.vb.y = _pan.vy - (e.clientY - _pan.sy) * _pan.ky;
  applyViewBox(el('gsvg'));
}
function graphPanEnd() {
  _pan = null;
  window.removeEventListener('mousemove', graphPanMove);
  window.removeEventListener('mouseup', graphPanEnd);
}
function graphWheel(e) {
  e.preventDefault();
  var svg = el('gsvg');
  if (!svg || !G.vb) return;
  var rect = svg.getBoundingClientRect();
  if (!rect.width) return;
  var fx = (e.clientX - rect.left) / rect.width;
  var fy = (e.clientY - rect.top) / rect.height;
  graphZoom(fx, fy, e.deltaY < 0 ? 0.85 : 1.18);
}
function graphClick(e) {
  if (_panned) { _panned = false; return; }
  var g = findUp(e.target, 'gn');
  if (g) {
    var oid = g.getAttribute('data-oid');
    graphFocus(oid);
  } else {
    G.focus = null; G.fset = null;
    var sel = el('ghopsel'); if (sel) sel.value = '0'; G.f.hops = 0;
    drawGraph(true);
    var fdiv = el('gfocus'); if (fdiv) fdiv.textContent = 'Knoten anklicken für Details (Doppelklick = Nachbarschaft isolieren)';
    var hops = el('ghops'); if (hops) hops.style.display = 'none';
  }
}
function graphFocus(oid) {
  var node = null, i;
  for (i = 0; i < G.baseNodes.length; i++) if (G.baseNodes[i].id === oid) { node = G.baseNodes[i]; break; }
  if (!node) return;
  G.focus = oid;
  var fs = {}; fs[oid] = true;
  var nb = G.nbr[oid] || [];
  for (i = 0; i < nb.length; i++) fs[nb[i].id] = true;
  G.fset = fs;
  drawGraph(true);
  var fdiv = el('gfocus');
  if (fdiv) fdiv.textContent = 'Fokus: ' + node.name;
  var hops = el('ghops');
  if (hops) hops.style.display = 'block';
}
function renderGraphInfo() {
  var box = el('ginfo');
  if (!box) return;
  if (!G.focus) { box.style.display = 'none'; return; }
  var node = null, i;
  for (i = 0; i < G.baseNodes.length; i++) if (G.baseNodes[i].id === G.focus) { node = G.baseNodes[i]; break; }
  if (!node) { box.style.display = 'none'; return; }
  var nb = G.nbr[G.focus] || [];
  var h = [];
  h.push('<div class="gi-head">' +
    '<span><span class="gi-dot" style="background:' + stColor(node.st) + '"></span><b>' + esc(node.name) + '</b> <code>' + esc(node.st) + '</code></span>' +
    '<span>' +
      '<button class="btn-sm pri" onclick="openElement(\'' + node.id + '\')">📋 Vollständigen Steckbrief öffnen</button> ' +
      '<button class="btn-sm" onclick="openElement(\'' + node.id + '\', \'graph\')">🎯 Als Umfeld-Zentrum öffnen</button> ' +
      '<button class="btn-sm" onclick="pathSetEndpoint(\'start\',\'' + node.id + '\')" title="Als Start der Verbindungsanalyse setzen">🔗 Als Start</button> ' +
      '<button class="btn-sm" onclick="pathSetEndpoint(\'end\',\'' + node.id + '\')" title="Als Ziel der Verbindungsanalyse setzen">🔗 Als Ziel</button>' +
    '</span>' +
  '</div>');
  h.push('<div class="gi-meta">' + (node.alias ? 'Alias: <b>' + esc(node.alias) + '</b> · ' : '') + '📁 Paket: ' + esc(node.pkg || '—') + ' · Vernetzung in dieser Sicht: <b>' + nb.length + '</b> Beziehungen</div>');
  if (nb.length) {
    h.push('<div class="gi-nbs">');
    for (i = 0; i < nb.length && i < 45; i++) {
      var x = OBJS[nb[i].id];
      if (!x) continue;
      var arrow = nb[i].dir > 0 ? '→' : '←';
      h.push('<div class="gi-nb" onclick="graphFocus(\'' + nb[i].id + '\')">' +
        '<span class="dim">' + arrow + ' <code>' + esc(shortLabel(nb[i].st, 26)) + '</code></span> ' +
        '<b>' + esc(x.name) + '</b> <span class="dim">«' + esc(x.st) + '»</span>' +
      '</div>');
    }
    if (nb.length > 45) h.push('<div class="dim">… ' + (nb.length - 45) + ' weitere Verbindungen</div>');
    h.push('</div>');
  }
  box.innerHTML = h.join('');
  box.style.display = 'block';
}

/* ---------- Hauptansicht wechseln ---------- */
function showView(v, activeTabOverride) {
  CURVIEW = v;
  if (v === 'vp' && el('pkgmain')) {
    var oldG = el('pkgmain').querySelector('#vp-graph');
    if (oldG) { oldG.innerHTML = ''; oldG.removeAttribute('id'); }
    var oldL = el('pkgmain').querySelector('#vp-list');
    if (oldL) { oldL.removeAttribute('id'); }
  } else if (v === 'explorer' && el('vpbox')) {
    el('vpbox').innerHTML = '';
  }
  var views = {
    explorer: el('view-explorer'),
    diags: el('view-diags'),
    grid: el('grid'),
    path: el('view-path'),
    vp: el('vp')
  };
  for (var k in views) {
    if (views.hasOwnProperty(k) && views[k]) {
      views[k].style.display = (k === v) ? 'block' : 'none';
    }
  }
  var tabKey = activeTabOverride || (v === 'vp' ? '' : v);
  var tabs = ['explorer', 'diags', 'graphhub', 'path', 'grid'];
  for (var i = 0; i < tabs.length; i++) {
    var tb = el('tab-' + tabs[i]);
    if (tb) tb.className = 'mtab' + (tabs[i] === tabKey ? ' on' : '');
  }
  updatePrintMeta();
}

/* ---------- Upload-Verdrahtung ---------- */
function wireUpload() {
  var zone = el('dropzone'), input = el('file');
  zone.onclick = function () { input.click(); };
  input.onchange = function () {
    if (input.files && input.files[0]) {
      var f = input.files[0];
      var rd = new FileReader();
      rd.onload = function () { loadQea(rd.result, f.name); };
      rd.readAsArrayBuffer(f);
    }
  };
  function handleFiles(files) {
    if (files && files[0]) {
      var f = files[0];
      var rd = new FileReader();
      rd.onload = function () { loadQea(rd.result, f.name); };
      rd.readAsArrayBuffer(f);
    }
  }
  zone.addEventListener('dragenter', function (e) { e.preventDefault(); zone.className = 'drop over'; });
  zone.addEventListener('dragover', function (e) { e.preventDefault(); zone.className = 'drop over'; });
  zone.addEventListener('dragleave', function (e) { e.preventDefault(); zone.className = 'drop'; });
  zone.addEventListener('drop', function (e) {
    e.preventDefault(); zone.className = 'drop';
    if (e.dataTransfer && e.dataTransfer.files) handleFiles(e.dataTransfer.files);
  });
  document.addEventListener('click', function (e) {
    var d = el('gsres');
    if (d && d.style.display === 'block' && !findUp(e.target, 'mbsearch')) d.style.display = 'none';
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', wireUpload);
} else { wireUpload(); }
