/* ADMBw QEA Analyzer v4.0 — Teil 4: Verbindungs- und Pfadanalyse (experimentell)
   Inspiriert von ArAMIS Web (Architekturmanagement-Informationssystem der Bundeswehr).
   Findet die Verbindungskette zwischen zwei Elementen über t_connector-Beziehungen,
   visualisiert sie als Schritt-Kette, Tabelle und Graph und diagnostiziert fehlende
   Verbindungen (Komponenten, Erreichbarkeit, gemeinsame Nachbarn).
   100 % Vanilla-JS / ES5, keine Bibliotheken, offline. */

var PATH = { start: null, end: null, directed: false, maxHops: 5, mode: 'shortest', last: null, selPath: 0, ctx: false };
var PATH_ADJ = null, PATH_COMP = null;

/* ================================================================
   ALGORITHMEN: ADJAZENZLISTE, BFS (kürzester Pfad), BOUNDED DFS (Alternativpfade)
   ================================================================ */
function buildAdjacency() {
  var adj = {}, i, c, a, b;
  for (i = 0; i < CONS.length; i++) {
    c = CONS[i];
    a = String(c.a); b = String(c.b);
    if (a === b) continue;                       /* Selbstschlingen verwerfen */
    if (!OBJS[a] || !OBJS[b]) continue;          /* verwaiste Enden verwerfen */
    if (!adj[a]) adj[a] = [];
    if (!adj[b]) adj[b] = [];
    /* dir = +1: Kante läuft in Modellierungsrichtung (a -> b), -1: invers */
    adj[a].push({ to: b, cid: c.id, st: c.st || c.type || '', name: c.name || '', type: c.type || '', dir: 1 });
    adj[b].push({ to: a, cid: c.id, st: c.st || c.type || '', name: c.name || '', type: c.type || '', dir: -1 });
  }
  return adj;
}

function pathNowMs() {
  return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
}

/* Kürzester Pfad (BFS, O(V+E)) — liefert {steps, hops, ms} oder {steps:null} */
function findShortestPath(adj, startId, endId, directed, maxHops) {
  var t0 = pathNowMs();
  startId = String(startId); endId = String(endId);
  if (startId === endId) return { steps: [], hops: 0, ms: 0 };
  var queue = [startId], visited = {}, parent = {}, level = {}, i;
  visited[startId] = true; level[startId] = 0;
  var found = false;
  while (queue.length) {
    var cur = queue.shift();
    if (cur === endId) { found = true; break; }
    var edges = adj[cur] || [];
    for (i = 0; i < edges.length; i++) {
      var e = edges[i];
      if (directed && e.dir !== 1) continue;     /* Richtungsfilter */
      if (visited[e.to]) continue;
      if (level[cur] + 1 > maxHops) continue;    /* Hop-Begrenzung */
      visited[e.to] = true;
      level[e.to] = level[cur] + 1;
      parent[e.to] = { prev: cur, e: e };
      queue.push(e.to);
    }
  }
  if (!visited[endId]) return { steps: null, hops: -1, ms: pathNowMs() - t0 };
  /* Pfad rekonstruieren */
  var steps = [], curN = endId;
  while (curN !== startId) {
    var p = parent[curN];
    steps.push({ from: p.prev, to: curN, cid: p.e.cid, st: p.e.st, name: p.e.name, type: p.e.type, forward: (p.e.dir === 1) });
    curN = p.prev;
  }
  steps.reverse();
  return { steps: steps, hops: steps.length, ms: pathNowMs() - t0 };
}

/* Alternative Pfade: tiefenbeschränktes DFS mit Backtracking (Simple Paths).
   Budget: max. 50.000 DFS-Schritte oder 2.000 ms. Wird das Budget erreicht,
   liefert das Ergebnis capped=true — die UI meldet den Abbruch dann sichtbar
   (kein stillschweigend unvollständiges Ergebnis mehr). */
function findAltPaths(adj, startId, endId, directed, maxHops, maxPaths) {
  var t0 = pathNowMs();
  startId = String(startId); endId = String(endId);
  maxPaths = maxPaths || 5;
  var paths = [], stepsCount = 0;
  var maxSteps = 50000, maxMs = 2000, stopped = false;
  var inBranch = {};
  inBranch[startId] = true;

  function deg(id) { return adj[id] ? adj[id].length : 0; }

  function dfs(cur, curPath) {
    if (stopped || paths.length >= maxPaths) return;
    stepsCount++;
    if (stepsCount >= maxSteps) { stopped = true; return; }
    if ((stepsCount % 256) === 0 && (pathNowMs() - t0) > maxMs) { stopped = true; return; }
    if (cur === endId && curPath.length > 0) { paths.push(curPath.slice(0)); return; }
    if (curPath.length >= maxHops) return;
    var edges = (adj[cur] || []).slice(0);
    /* Hubs zuletzt traversieren (Verzweigungsexplosion eindämmen) */
    edges.sort(function (x, y) { return deg(x.to) - deg(y.to); });
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      if (directed && e.dir !== 1) continue;
      if (inBranch[e.to]) continue;              /* Zyklusvermeidung */
      inBranch[e.to] = true;
      curPath.push({ from: cur, to: e.to, cid: e.cid, st: e.st, name: e.name, type: e.type, forward: (e.dir === 1) });
      dfs(e.to, curPath);
      curPath.pop();
      delete inBranch[e.to];
      if (stopped || paths.length >= maxPaths) return;
    }
  }
  dfs(startId, []);

  /* Duplikate (gleiche Knotensequenz) entfernen */
  var seen = {}, uniq = [];
  for (var p = 0; p < paths.length; p++) {
    var key = [startId].concat(paths[p].map(function (s) { return s.to; })).join('>');
    if (!seen[key]) { seen[key] = 1; uniq.push(paths[p]); }
  }
  return { paths: uniq, ms: pathNowMs() - t0, capped: stopped, steps: stepsCount };
}

/* Erreichbarkeit: Wie viele Knoten erreicht id innerhalb maxHops? */
function pathReachCount(adj, id, maxHops, directed) {
  var seen = {}, queue = [id], level = {}, i;
  seen[id] = true; level[id] = 0;
  while (queue.length) {
    var cur = queue.shift();
    if (level[cur] >= maxHops) continue;
    var edges = adj[cur] || [];
    for (i = 0; i < edges.length; i++) {
      var e = edges[i];
      if (directed && e.dir !== 1) continue;
      if (seen[e.to]) continue;
      seen[e.to] = true; level[e.to] = level[cur] + 1;
      queue.push(e.to);
    }
  }
  var n = 0, k;
  for (k in seen) if (seen.hasOwnProperty(k)) n++;
  return n - 1; /* ohne den Startknoten selbst */
}

/* Zusammenhangskomponenten (ungerichtet) — gecacht */
function ensureComponents() {
  if (PATH_COMP) return;
  if (!PATH_ADJ) PATH_ADJ = buildAdjacency();
  var compOf = {}, sizes = {}, comp = 0, seen = {}, i, j;
  var ids = [];
  for (var k in OBJS) if (OBJS.hasOwnProperty(k)) ids.push(k);
  for (i = 0; i < ids.length; i++) {
    var id = ids[i];
    if (seen[id]) continue;
    comp++;
    var queue = [id], cnt = 0;
    seen[id] = true;
    while (queue.length) {
      var cur = queue.shift();
      cnt++;
      compOf[cur] = comp;
      var edges = (PATH_ADJ[cur] || []);
      for (j = 0; j < edges.length; j++) {
        if (!seen[edges[j].to]) { seen[edges[j].to] = true; queue.push(edges[j].to); }
      }
    }
    sizes[comp] = cnt;
  }
  PATH_COMP = { compOf: compOf, sizes: sizes, count: comp };
}

/* ================================================================
   UI: STEUERPANEL, TYPEAHEAD-AUSWAHL, ERGEBNISDARSTELLUNG
   ================================================================ */
function pathRenderTab() {
  var box = el('pathbox');
  if (!box) return;
  /* Klick außerhalb schließt die Typeahead-Dropdowns */
  if (!window._pathDocClickBound) {
    window._pathDocClickBound = true;
    document.addEventListener('click', function (e) {
      if (!findUp(e.target, 'pfield')) {
        var a = el('pstartlist'); if (a) a.style.display = 'none';
        var b = el('pendlist'); if (b) b.style.display = 'none';
      }
    });
  }
  var h = [];
  h.push('<h2>🔗 Verbindung zweier Elemente finden <span class="dim" style="font-size:13px;font-weight:400">(Pfadanalyse – experimentell, inspiriert von ArAMIS Web)</span></h2>');
  h.push('<div class="purpose">Wie hängt <b>Element A</b> mit <b>Element B</b> zusammen? Wählen Sie Start- und Ziel-Element — der Analyzer findet die <b>Verbindungskette</b> durch das Modell, zeigt sie als Schrittfolge, Tabelle und Graph und erklärt nachvollziehbar, <b>wenn keine Verbindung existiert</b> (z.&nbsp;B. getrennte Teilarchitekturen).</div>');
  h.push('<div class="pathgrid">');

  /* Steuerpanel */
  h.push('<div class="pathpanel pcontrols-hide">');
  h.push('<div class="pfield"><label>🚩 Start-Element</label>' +
    '<input id="pstartinp" placeholder="Suchen: Name, Alias oder Stereotyp …" autocomplete="off" oninput="pathTypeahead(\'start\')" onkeydown="pathKey(event)">' +
    '<div class="ptypeahead" id="pstartlist" style="display:none"></div>' +
    '<div id="pstartchosen"></div></div>');
  h.push('<div style="text-align:center;margin:0 0 8px"><button class="btn-sm" onclick="pathSwap()" title="Start- und Ziel-Element tauschen">⇄ Tauschen</button></div>');
  h.push('<div class="pfield"><label>🎯 Ziel-Element</label>' +
    '<input id="pendinp" placeholder="Suchen: Name, Alias oder Stereotyp …" autocomplete="off" oninput="pathTypeahead(\'end\')" onkeydown="pathKey(event)">' +
    '<div class="ptypeahead" id="pendlist" style="display:none"></div>' +
    '<div id="pendchosen"></div></div>');

  h.push('<div class="pcontrols">');
  h.push('<div class="pc-row"><b>Richtung:</b><br>' +
    '<button id="pdir-u" class="on" onclick="pathSetDir(false)" title="Alle Verbindungen unabhängig von der Pfeilrichtung (Architektur-Gesamtzusammenhang)">↔ Ungerichtet</button> ' +
    '<button id="pdir-d" onclick="pathSetDir(true)" title="Nur Kanten in Modellierungsrichtung (Nutzungs-/Kausalfluss)">⇶ Gerichtet (A ➜ B)</button></div>');
  h.push('<div class="pc-row"><b>Max. Hops:</b><br>' +
    '<input type="range" id="phops" min="1" max="10" step="1" value="5" style="width:100%;accent-color:var(--bw-blue);cursor:pointer" oninput="pathSlideHops(this.value,\'slider\')">' +
    '<div style="display:flex;align-items:center;gap:6px;margin-top:4px"><input type="number" id="phopsnum" min="1" max="10" step="1" value="5" style="width:64px;padding:3px 6px;border:1px solid var(--bw-blue);border-radius:6px;font-size:12.5px;text-align:right" oninput="pathSlideHops(this.value,\'number\')"> <span class="dim">Hops (Zwischenschritte)</span></div></div>');
  h.push('<div class="pc-row"><b>Suchmodus:</b><br>' +
    '<button id="pmode-s" class="on" onclick="pathSetPathMode(\'shortest\')" title="Minimale Anzahl Zwischenschritte (BFS)">Kürzester Pfad</button> ' +
    '<button id="pmode-m" onclick="pathSetPathMode(\'multi\')" title="Bis zu 5 alternative Verbindungsketten">Alternative Pfade (bis 5)</button></div>');
  h.push('</div>');
  h.push('<button class="pfind" onclick="pathFind()">🔎 Verbindung suchen</button>');
  h.push('<div class="dim" style="margin-top:9px">💡 Tipp: In Element-Steckbriefen (📦), Graph-Infos und Tabellen gibt es „🔗 Als Start/Ziel setzen“-Buttons. Die Suche reagiert in Millisekunden — auch im Gesamtmodell.</div>');
  h.push('</div>'); /* /pathpanel */

  h.push('<div id="pathresults" style="min-width:0"><div class="pnote">Wählen Sie links <b>Start- und Ziel-Element</b>, dann „🔎 Verbindung suchen“ (oder direkt aus einem Steckbrief übernehmen).</div></div>');
  h.push('</div>'); /* /pathgrid */
  box.innerHTML = h.join('');
  pathSyncControls();
  pathRenderChosen();
}

function pathSyncControls() {
  var sl = el('phops'), num = el('phopsnum');
  if (sl) sl.value = PATH.maxHops;
  if (num) num.value = PATH.maxHops;
  var du = el('pdir-u'), dd = el('pdir-d');
  if (du) du.className = PATH.directed ? '' : 'on';
  if (dd) dd.className = PATH.directed ? 'on' : '';
  var ms = el('pmode-s'), mm = el('pmode-m');
  if (ms) ms.className = PATH.mode === 'shortest' ? 'on' : '';
  if (mm) mm.className = PATH.mode === 'multi' ? 'on' : '';
}

function pathRenderChosen() {
  var sBox = el('pstartchosen'), eBox = el('pendchosen');
  function chip(which) {
    var oid = which === 'start' ? PATH.start : PATH.end;
    if (!oid || !OBJS[oid]) return '';
    var o = OBJS[oid];
    return '<span class="pchipsel"><span class="ptdot" style="background:' + stColor(o.st) + '"></span><b>' + esc(shortLabel(o.name, 34)) + '</b> <code>' + esc(o.st) + '</code> <span class="dim">🔗 ' + (CONNCOUNT[oid] || 0) + '</span> <a href="javascript:void(0)" onclick="pathClear(\'' + which + '\')" title="Auswahl löschen">✕</a></span>';
  }
  if (sBox) sBox.innerHTML = chip('start');
  if (eBox) eBox.innerHTML = chip('end');
}

function pathClear(which) {
  if (which === 'start') { PATH.start = null; var a = el('pstartinp'); if (a) a.value = ''; }
  else { PATH.end = null; var b = el('pendinp'); if (b) b.value = ''; }
  PATH.last = null;
  pathRenderChosen();
  var res = el('pathresults');
  if (res) res.innerHTML = '<div class="pnote">Wählen Sie links <b>Start- und Ziel-Element</b>, dann „🔎 Verbindung suchen“.</div>';
}

function pathSwap() {
  var t = PATH.start; PATH.start = PATH.end; PATH.end = t;
  var ai = el('pstartinp'), bi = el('pendinp');
  if (ai) ai.value = (PATH.start && OBJS[PATH.start]) ? OBJS[PATH.start].name : '';
  if (bi) bi.value = (PATH.end && OBJS[PATH.end]) ? OBJS[PATH.end].name : '';
  pathRenderChosen();
  if (PATH.start && PATH.end && PATH.last) pathFind();
}

function pathSetDir(dir) {
  PATH.directed = !!dir;
  pathSyncControls();
  if (PATH.start && PATH.end && PATH.last) pathFind();
}

function pathSetPathMode(m) {
  PATH.mode = m === 'multi' ? 'multi' : 'shortest';
  pathSyncControls();
  if (PATH.start && PATH.end && PATH.last) pathFind();
}

function pathSlideHops(v, from) {
  var n = parseInt(v, 10);
  if (isNaN(n)) n = 5;
  if (n < 1) n = 1;
  if (n > 10) n = 10;
  PATH.maxHops = n;
  var sl = el('phops'), num = el('phopsnum');
  if (sl && from !== 'slider') sl.value = n;
  if (num && from !== 'number') num.value = n;
  if (PATH.start && PATH.end && PATH.last) pathFind();
}

function pathKey(e) {
  if (e.keyCode === 13) { e.preventDefault(); pathFind(); }
  else if (e.keyCode === 27) {
    var a = el('pstartlist'); if (a) a.style.display = 'none';
    var b = el('pendlist'); if (b) b.style.display = 'none';
  }
}

/* Typeahead-Sofortsuche für Start/Ziel */
function pathTypeahead(which) {
  var inp = el(which === 'start' ? 'pstartinp' : 'pendinp');
  var box = el(which === 'start' ? 'pstartlist' : 'pendlist');
  if (!inp || !box) return;
  var q = (inp.value || '').trim().toLowerCase();
  if (q.length < 2) { box.style.display = 'none'; box.innerHTML = ''; return; }
  var hits = [], k, o;
  for (k in OBJS) {
    if (!OBJS.hasOwnProperty(k)) continue;
    o = OBJS[k];
    if (o.type === 'Boundary' || /^proxyconn?ector$/i.test(o.st)) continue;
    if ((o.name + ' ' + o.alias + ' ' + o.st).toLowerCase().indexOf(q) >= 0) hits.push(o);
  }
  hits.sort(function (a, b) { return (CONNCOUNT[b.id] || 0) - (CONNCOUNT[a.id] || 0); });
  hits = hits.slice(0, 30);
  var h = [];
  for (var i = 0; i < hits.length; i++) {
    o = hits[i];
    h.push('<div class="ptrow" onclick="pathChoose(\'' + which + '\',\'' + o.id + '\')">' +
      '<span class="ptdot" style="background:' + stColor(o.st) + '"></span>' +
      '<span><b>' + esc(shortLabel(o.name || '(ohne Name)', 46)) + '</b> <code>' + esc(o.st) + '</code></span>' +
      '<span class="ptmeta">📁 ' + esc(shortLabel(o.pkg || '—', 30)) + ' · 🔗 ' + (CONNCOUNT[o.id] || 0) + '</span>' +
    '</div>');
  }
  box.innerHTML = h.join('') || '<div class="ptrow dim">Keine Treffer</div>';
  box.style.display = 'block';
}

function pathChoose(which, oid) {
  oid = String(oid);
  if (!OBJS[oid]) return;
  if (which === 'start') PATH.start = oid; else PATH.end = oid;
  var inp = el(which === 'start' ? 'pstartinp' : 'pendinp');
  var box = el(which === 'start' ? 'pstartlist' : 'pendlist');
  if (inp) inp.value = OBJS[oid].name;
  if (box) box.style.display = 'none';
  pathRenderChosen();
  if (PATH.start && PATH.end) pathFind();   /* beide gewählt -> sofort suchen */
}

/* Aus Steckbrief / Graph heraus als Start oder Ziel übernehmen */
function pathSetEndpoint(which, oid) {
  oid = String(oid);
  if (!OBJS[oid]) return;
  if (which === 'start') PATH.start = oid; else PATH.end = oid;
  var inp = el(which === 'start' ? 'pstartinp' : 'pendinp');
  if (inp) inp.value = OBJS[oid].name;
  pathRenderChosen();
  showView('path');
  var res = el('pathresults');
  if (res) res.innerHTML = '<div class="pnote">„' + esc(OBJS[oid].name) + '“ als <b>' + (which === 'start' ? 'Start' : 'Ziel') + '</b> übernommen — ' + (PATH.start && PATH.end ? 'Suche läuft …' : 'bitte noch das ' + (which === 'start' ? 'Ziel' : 'Start') + ' wählen.') + '</div>';
  if (PATH.start && PATH.end) pathFind();
}

/* ================================================================
   SUCHE AUSFÜHREN & ERGEBNISSE DARSTELLEN
   ================================================================ */
function pathFind() {
  var res = el('pathresults');
  if (!res) return;
  if (!PATH.start || !PATH.end) {
    res.innerHTML = '<div class="pnote">⚠ Bitte erst <b>Start- und Ziel-Element</b> wählen (Suchfelder links).</div>';
    return;
  }
  if (!PATH_ADJ) { PATH_ADJ = buildAdjacency(); PATH_COMP = null; }
  var s = OBJS[PATH.start], e = OBJS[PATH.end];
  var out = { s: s, e: e, mode: PATH.mode, directed: PATH.directed, maxHops: PATH.maxHops, none: false };
  PATH.last = out;
  PATH.selPath = 0;

  if (PATH.start === PATH.end) { out.trivial = true; pathRenderResults(); return; }
  var sDeg = (PATH_ADJ[PATH.start] || []).length;
  var eDeg = (PATH_ADJ[PATH.end] || []).length;
  if (!sDeg || !eDeg) { out.isolated = { s: !sDeg, e: !eDeg }; pathRenderResults(); return; }

  if (PATH.mode === 'multi') {
    var r = findAltPaths(PATH_ADJ, PATH.start, PATH.end, PATH.directed, PATH.maxHops, 5);
    out.paths = r.paths; out.ms = r.ms; out.capped = r.capped;
    out.none = !r.paths.length;
  } else {
    var r2 = findShortestPath(PATH_ADJ, PATH.start, PATH.end, PATH.directed, PATH.maxHops);
    out.steps = r2.steps; out.ms = r2.ms;
    out.none = !r2.steps;
  }
  pathRenderResults();
}

function pathRenderResults() {
  var host = el('pathresults');
  if (!host || !PATH.last) return;
  var o = PATH.last, s = o.s, e = o.e;
  var h = [];

  /* ---- Status-Banner ---- */
  var dirTxt = o.directed ? 'gerichtet' : 'ungerichtet';
  if (o.trivial) {
    h.push('<div class="pbanner info">ℹ️ Start und Ziel sind identisch — <b>0 Hops</b>. Bitte zwei verschiedene Elemente wählen.</div>');
  } else if (o.isolated) {
    var parts = [];
    if (o.isolated.s) parts.push('das <b>Start-Element</b>');
    if (o.isolated.e) parts.push('das <b>Ziel-Element</b>');
    h.push('<div class="pbanner warn">⚠ ' + parts.join(' und ') + ' besitzt im Modell <b>keine einzige Beziehung</b> (isolierter Knoten, Grad 0) — eine Pfadsuche ist nicht möglich.</div>');
    h.push(pathDiagHtml(s, e));
  } else if (o.none) {
    h.push('<div class="pbanner warn">⚠ <b>Keine Verbindung</b> zwischen „' + esc(shortLabel(s.name, 40)) + '“ und „' + esc(shortLabel(e.name, 40)) + '“ innerhalb von <b>' + o.maxHops + ' Hops</b> gefunden (' + dirTxt + ').</div>');
    h.push(pathDiagHtml(s, e));
  } else {
    var steps = o.mode === 'multi' ? o.paths[PATH.selPath] : o.steps;
    var hops = steps.length;
    h.push('<div class="pbanner ok">✔ <b>Verbindung gefunden:</b> ' + hops + ' Hop' + (hops === 1 ? '' : 's') + ' · ' + (hops + 1) + ' Elemente · ' + hops + ' Beziehung' + (hops === 1 ? '' : 'en') + ' · Modus: ' + (o.mode === 'multi' ? 'Alternativpfade' : 'kürzester Pfad') + ' (' + dirTxt + ') · Berechnung: ' + (Math.round(o.ms * 100) / 100) + ' ms</div>');
  }

  /* Sichtbarer Hinweis, wenn die Alternativpfad-Suche das interne Budget
     erreicht hat — das Ergebnis ist dann möglicherweise unvollständig. */
  if (o.mode === 'multi' && o.capped && !o.trivial && !o.isolated) {
    h.push('<div class="pbanner warn">⚠ <b>Suche limitiert:</b> Die Alternativpfad-Suche wurde wegen des internen Suchlimits vorzeitig abgebrochen — '
      + (o.none
        ? '„Keine Verbindung“ ist deshalb nicht abschließend; es können trotzdem Pfade existieren (Hops erhöhen oder erneut suchen).'
        : 'es können <b>weitere alternative Pfade</b> existieren (angezeigt: ' + o.paths.length + ' von max. 5).')
      + '</div>');
  }

  var showResult = !o.none && !o.trivial && !o.isolated;

  /* ---- Alternativpfad-Auswahl ---- */
  if (showResult && o.mode === 'multi' && o.paths.length > 1) {
    h.push('<div class="ppaths"><span class="dim" style="align-self:center">' + o.paths.length + ' Pfade gefunden:</span>');
    for (var pi = 0; pi < o.paths.length; pi++) {
      h.push('<button class="ppathbtn' + (pi === PATH.selPath ? ' on' : '') + '" onclick="pathSelectPath(' + pi + ')">Pfad ' + (pi + 1) + ' · ' + o.paths[pi].length + ' Hops</button>');
    }
    h.push('</div>');
  }

  if (showResult) {
    var cur = o.mode === 'multi' ? o.paths[PATH.selPath] : o.steps;
    h.push('<div class="pathgrid2">');
    /* Schritt-Kette */
    h.push('<div class="pcard"><h3 style="margin-top:0">Verbindungskette (Schritt für Schritt)</h3>');
    h.push(pathChainHtml(cur, PATH.start));
    h.push('</div>');
    /* Graph */
    h.push('<div class="pcard"><h3 style="margin-top:0">Graph-Ausschnitt</h3>' +
      '<label style="font-size:12px;cursor:pointer;display:inline-block;margin-bottom:6px"><input type="checkbox" ' + (PATH.ctx ? 'checked ' : '') + ' onchange="pathToggleCtx(this)"> Auch direkte Nachbarn der Pfad-Elemente anzeigen (Kontext)</label>' +
      '<div class="pathgraphbox" id="pathgraph"></div></div>');
    h.push('</div>');
    /* Tabelle */
    h.push('<div class="pcard"><h3 style="margin-top:0">Detail-Tabelle der Verbindung (' + cur.length + ' Schritte)</h3>');
    h.push(pathTableHtml(cur));
    h.push('</div>');
    /* Exporte */
    h.push('<div class="vp-actions" style="margin-top:12px"><span class="vexport">' +
      '<button class="exp-xls" onclick="pathExportXLSX()">📊 Pfad als Excel (.xlsx)</button>' +
      '<button class="exp-png" onclick="pathExportPNG()">📸 Pfad-Graph als PNG</button>' +
      '</span></div>');
  }

  host.innerHTML = h.join('');
  if (showResult) {
    var cur2 = o.mode === 'multi' ? o.paths[PATH.selPath] : o.steps;
    pathDrawSVG(cur2, PATH.start);
  }
}

function pathSelectPath(i) {
  PATH.selPath = i;
  pathRenderResults();
}

function pathToggleCtx(cb) {
  PATH.ctx = !!cb.checked;
  var o = PATH.last;
  if (o && o.paths || o && o.steps) {
    var cur = o.mode === 'multi' ? o.paths[PATH.selPath] : o.steps;
    if (cur) pathDrawSVG(cur, PATH.start);
  }
}

/* Diagnose bei fehlender Verbindung */
function pathDiagHtml(s, e) {
  ensureComponents();
  var adj = PATH_ADJ;
  var cs = PATH_COMP.compOf[s.id], ce = PATH_COMP.compOf[e.id];
  var sizeS = PATH_COMP.sizes[cs] || 0, sizeE = PATH_COMP.sizes[ce] || 0;
  var h = [];
  h.push('<div class="pcard"><h3 style="margin-top:0">🔬 Architektur-Diagnose: Warum gibt es keine Verbindung?</h3>');

  h.push('<div class="diag-row"><b>1. Teilarchitekturen (Zusammenhangskomponenten):</b> ');
  if (cs === ce) {
    h.push('Beide Elemente liegen in <b>derselben</b> Komponente (' + fmt(sizeS) + ' Elemente) — die Verbindung existiert also nur über mehr als ' + PATH.maxHops + ' Hops oder verläuft über ausgeblendete Richtungen. Tipp: <b>Max. Hops erhöhen</b> oder Richtung auf <b>ungerichtet</b> stellen.</div>');
  } else {
    h.push('„' + esc(shortLabel(s.name, 34)) + '“ liegt in einer Komponente mit <b>' + fmt(sizeS) + '</b> Elementen, „' + esc(shortLabel(e.name, 34)) + '“ in einer anderen mit <b>' + fmt(sizeE) + '</b> Elementen. Diese Teilarchitekturen sind <b>vollständig voneinander getrennt</b> — es fehlt eine verbindende Beziehung (z.&nbsp;B. Realization, Dependency oder Traceability) zwischen den Fachpaketen.</div>');
  }

  var reachS = pathReachCount(adj, s.id, PATH.maxHops, PATH.directed);
  var reachE = pathReachCount(adj, e.id, PATH.maxHops, PATH.directed);
  h.push('<div class="diag-row"><b>2. Erreichbarkeits-Horizont (± ' + PATH.maxHops + ' Hops):</b> Das Start-Element kann <b>' + fmt(reachS) + '</b> Elemente erreichen, das Ziel-Element <b>' + fmt(reachE) + '</b> Elemente — gegenseitig aber keines.</div>');

  /* Gemeinsame Nachbarn (1 Hop, ungerichtet) */
  var nbS = {}, nbE = {}, common = [], i;
  var es = adj[s.id] || [], ee = adj[e.id] || [];
  for (i = 0; i < es.length; i++) nbS[es[i].to] = true;
  for (i = 0; i < ee.length; i++) nbE[ee[i].to] = true;
  for (var k in nbS) if (nbS.hasOwnProperty(k) && nbE[k]) common.push(k);
  h.push('<div class="diag-row"><b>3. Gemeinsame Nachbarn (Brücken-Kandidaten):</b> ');
  if (common.length) {
    h.push('<b>' + common.length + '</b> Element(e) stehen mit beiden in direkter Beziehung: ');
    for (i = 0; i < common.length && i < 8; i++) {
      var co = OBJS[common[i]];
      h.push('<span class="gchip" onclick="openElement(\'' + common[i] + '\')"><i style="background:' + stColor(co ? co.st : '') + '"></i>' + esc(shortLabel(co ? co.name : '?', 30)) + '</span> ');
    }
    if (common.length > 8) h.push('<span class="dim">… +' + (common.length - 8) + ' weitere</span>');
  } else {
    h.push('Keine gemeinsamen direkten Nachbarn vorhanden.</div>');
  }

  /* Gemeinsames Paket & gemeinsame Sichten */
  var samePkg = s.pkgFull && s.pkgFull === e.pkgFull;
  h.push('<div class="diag-row"><b>4. Kontext:</b> ');
  h.push(samePkg ? 'Beide Elemente liegen im <b>selben Paket</b> (' + esc(shortLabel(s.pkgFull, 60)) + '). ' : 'Beide liegen in <b>unterschiedlichen Paketen</b>. ');
  var ds = OBJ_DIAGS[s.id] || [], de = OBJ_DIAGS[e.id] || [];
  var shared = [];
  for (i = 0; i < ds.length; i++) if (de.indexOf(ds[i]) >= 0) shared.push(ds[i]);
  if (shared.length) {
    h.push('Sie erscheinen gemeinsam auf <b>' + shared.length + '</b> Sicht(en): ');
    for (i = 0; i < shared.length && i < 5; i++) {
      var dg = DIAGMAP[shared[i]];
      if (dg) h.push('<a href="javascript:openDiagramView(' + dg.id + ')" class="dim">🖼️ ' + esc(shortLabel(dg.name, 34)) + '</a> ');
    }
  } else {
    h.push('Sie erscheinen auf <b>keiner gemeinsamen</b> Sicht.');
  }
  h.push('</div>');

  h.push('<div class="diag-row dim">💡 <b>Handlungsempfehlung für Modellierer:</b> Prüfen Sie, ob zwischen den beteiligten Paketen eine fachliche oder methodische Beziehung fehlt (z.&nbsp;B. «realizes», «implements», «dependency»), um den Schichtenübergang herzustellen — oder erhöhen Sie die Hop-Grenze bzw. stellen Sie auf ungerichtete Suche um.</div>');
  h.push('</div>');
  return h.join('');
}

function pathChainHtml(steps, sOid) {
  var h = [], i;
  h.push('<div class="pchain">');
  var nodes = [String(sOid)];
  for (i = 0; i < steps.length; i++) nodes.push(String(steps[i].to));
  for (i = 0; i < nodes.length; i++) {
    var oid = nodes[i], oo = OBJS[oid];
    if (!oo) continue;
    h.push('<div class="pnode" onclick="openElement(\'' + oid + '\')" title="Element-Steckbrief öffnen">' +
      '<span class="ptdot" style="background:' + stColor(oo.st) + '"></span>' +
      '<b>' + esc(shortLabel(oo.name || '(ohne Name)', 52)) + '</b> <code>' + esc(oo.st) + '</code>' +
      '<span class="dim" style="margin-left:6px">📁 ' + esc(shortLabel(oo.pkg || '', 30)) + '</span></div>');
    if (i < steps.length) {
      var st = steps[i];
      h.push('<div class="plink"><code>' + esc(st.st || st.type || 'Verbindung') + '</code> ' + (st.forward ? '➔ in Modellrichtung' : '◄ invers modelliert') + (st.name ? ' · „' + esc(shortLabel(st.name, 40)) + '“' : '') + '</div>');
    }
  }
  h.push('</div>');
  return h.join('');
}

function pathTableHtml(steps) {
  var h = [], i;
  h.push('<div style="overflow:auto"><table class="data"><thead><tr><th>#</th><th>Quell-Element</th><th>Quell-Stereotyp</th><th>Beziehung</th><th>Richtung</th><th>Ziel-Element</th><th>Ziel-Stereotyp</th><th>Ziel-Paket</th></tr></thead><tbody>');
  for (i = 0; i < steps.length; i++) {
    var st = steps[i];
    var a = OBJS[st.from], b = OBJS[st.to];
    h.push('<tr class="clickable" onclick="openElement(\'' + st.from + '\')">' +
      '<td><b>' + (i + 1) + '</b></td>' +
      '<td>' + esc(shortLabel(a ? a.name : '?', 34)) + '</td>' +
      '<td><code>' + esc(a ? a.st : '') + '</code></td>' +
      '<td><code>' + esc(st.st || st.type || '→') + '</code>' + (st.name ? ' <span class="dim">„' + esc(shortLabel(st.name, 24)) + '“</span>' : '') + '</td>' +
      '<td>' + (st.forward ? '➔ vorwärts' : '◄ invers') + '</td>' +
      '<td>' + esc(shortLabel(b ? b.name : '?', 34)) + '</td>' +
      '<td><code>' + esc(b ? b.st : '') + '</code></td>' +
      '<td class="dim">' + esc(shortLabel(b ? (b.pkg || '') : '', 30)) + '</td>' +
    '</tr>');
  }
  h.push('</tbody></table></div>');
  return h.join('');
}

/* SVG-Ausschnitt des Pfades (horizontal, optional mit 1-Hop-Kontext) */
function pathDrawSVG(steps, sOid) {
  var host = el('pathgraph');
  if (!host) return;
  var i, j;
  var nodes = [String(sOid)];
  for (i = 0; i < steps.length; i++) nodes.push(String(steps[i].to));
  var n = nodes.length;
  var gapX = 235, cx = 90;
  var pts = [];
  for (i = 0; i < n; i++) pts.push({ x: cx + i * gapX, y: 0 });

  var parts = [];
  var padL = 80, padR = 80, padT = 130, padB = 130;
  var W = pts[n - 1].x + padR;
  var H = padT + padB;
  var vbX = -padL + 40, vbY = -padT, vbW = W + padL - 40 + 40, vbH = H;

  parts.push('<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + vbX + ' ' + vbY + ' ' + vbW + ' ' + vbH + '" style="width:100%;max-width:' + Math.round(vbW) + 'px;height:auto;display:block;margin:0 auto" preserveAspectRatio="xMidYMid meet">');
  parts.push('<defs>' +
    '<marker id="parr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7.5" markerHeight="7.5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#004471"/></marker>' +
  '</defs>');

  /* Kontext-Nachbarn (1 Hop) */
  var ctxSet = {};
  if (PATH.ctx && PATH_ADJ) {
    var pathSet = {};
    for (i = 0; i < n; i++) pathSet[nodes[i]] = true;
    for (i = 0; i < n; i++) {
      var es = PATH_ADJ[nodes[i]] || [];
      var upDown = 1, added = 0;
      for (j = 0; j < es.length; j++) {
        var nid = es[j].to;
        if (pathSet[nid] || ctxSet[nid]) continue;
        if (added >= 6) break;
        var cy = upDown * (108 + Math.floor(added / 2) * 52);
        var cxo = pts[i].x;
        parts.push('<line x1="' + pts[i].x + '" y1="' + pts[i].y + '" x2="' + cxo + '" y2="' + cy + '" stroke="#CBD5E1" stroke-width="1" stroke-dasharray="4 4"/>');
        var co = OBJS[nid];
        var ccol = stColor(co ? co.st : '');
        parts.push('<g class="pgn" data-oid="' + nid + '" transform="translate(' + cxo + ',' + cy + ')" style="cursor:pointer">' +
          '<circle r="9" fill="' + stFill(co ? co.st : '') + '" stroke="' + ccol + '" stroke-width="1.6" opacity="0.85"/>' +
          '<text y="24" text-anchor="middle" font-size="9" fill="#64748B">' + esc(shortLabel(co ? co.name : '?', 22)) + '</text>' +
          '<title>' + esc((co ? co.name : '') + ' «' + (co ? co.st : '') + '» (Kontext)') + '</title></g>');
        ctxSet[nid] = true;
        upDown = -upDown; added++;
      }
    }
  }

  /* Kanten des Pfades */
  for (i = 0; i < steps.length; i++) {
    var p1 = pts[i], p2 = pts[i + 1];
    parts.push('<line x1="' + p1.x + '" y1="' + p1.y + '" x2="' + p2.x + '" y2="' + p2.y + '" stroke="#004471" stroke-width="2.4" marker-end="url(#parr)"/>');
    var mx = (p1.x + p2.x) / 2, my = -16;
    var st = steps[i];
    parts.push('<text x="' + mx + '" y="' + my + '" text-anchor="middle" font-size="10.5" font-weight="600" fill="#0F172A" style="paint-order:stroke;stroke:#FFFFFF;stroke-width:3px">' + esc(shortLabel(st.st || st.type || '→', 26)) + ' ' + (st.forward ? '➔' : '◄') + '</text>');
  }

  /* Pfad-Knoten */
  for (i = 0; i < n; i++) {
    var oo = OBJS[nodes[i]];
    var col = stColor(oo ? oo.st : ''), fl = stFill(oo ? oo.st : '');
    parts.push('<g class="pgn" data-oid="' + nodes[i] + '" transform="translate(' + pts[i].x + ',' + pts[i].y + ')" style="cursor:pointer">' +
      '<circle r="19" fill="' + fl + '" stroke="' + col + '" stroke-width="2.6"/>' +
      '<text y="4" text-anchor="middle" font-size="10.5" font-weight="700" fill="#1F2937" style="pointer-events:none">' + (i + 1) + '</text>' +
      '<text y="-30" text-anchor="middle" font-size="11" font-weight="600" fill="#0F172A" style="paint-order:stroke;stroke:#FFFFFF;stroke-width:3.2px">' + esc(shortLabel(oo ? oo.name : '?', 28)) + '</text>' +
      '<text y="37" text-anchor="middle" font-size="9" fill="#475569" style="paint-order:stroke;stroke:#FFFFFF;stroke-width:2.5px">«' + esc(shortLabel(oo ? oo.st : '', 24)) + '»</text>' +
      '<title>' + esc((oo ? oo.name : '') + ' «' + (oo ? oo.st : '') + '» — Klick: Steckbrief') + '</title></g>');
  }
  parts.push('</svg>');
  host.innerHTML = parts.join('');

  var gs = host.querySelectorAll('.pgn');
  for (i = 0; i < gs.length; i++) {
    gs[i].addEventListener('click', function (ev) {
      var oid = ev.currentTarget.getAttribute('data-oid');
      if (oid) openElement(oid);
    });
  }
}

/* ================================================================
   EXPORTE DER PFADANALYSE (Excel & PNG)
   ================================================================ */
function pathExportXLSX() {
  var o = PATH.last;
  if (!o) { alert('Bitte zuerst eine Verbindung suchen.'); return; }
  var showResult = !o.none && !o.trivial && !o.isolated;
  var cur = showResult ? (o.mode === 'multi' ? o.paths[PATH.selPath] : o.steps) : [];
  var i;

  var ovRows = [
    ['Eigenschaft', 'Wert'],
    ['Anwendung', 'ADMBw QEA Analyzer v4.0'],
    ['Funktion', 'Verbindungs-/Pfadanalyse (ArAMIS-inspiriert)'],
    ['Start-Element', o.s ? o.s.name : '—'],
    ['Start-Stereotype', o.s ? o.s.st : ''],
    ['Ziel-Element', o.e ? o.e.name : '—'],
    ['Ziel-Stereotype', o.e ? o.e.st : ''],
    ['Suchmodus', o.mode === 'multi' ? 'Alternative Pfade (bis 5)' : 'Kürzester Pfad'],
    ['Richtung', o.directed ? 'gerichtet (A ➜ B)' : 'ungerichtet'],
    ['Max. Hops', o.maxHops],
    ['Ergebnis', o.trivial ? 'Start = Ziel (0 Hops)' : (o.isolated ? 'Isoliertes Element (Grad 0)' : (o.none ? 'Keine Verbindung gefunden' : cur.length + ' Hops, ' + (cur.length + 1) + ' Elemente'))],
    ['Berechnung (ms)', Math.round((o.ms || 0) * 100) / 100],
    ['Geladenes Modell (.qea)', MODELLNAME || '—'],
    ['Export-Zeitpunkt', dateTimeDE()]
  ];

  var stepRows = [['#', 'Quelle', 'Quelle-Stereotype', 'Beziehung', 'Beziehungsname', 'Richtung', 'Ziel', 'Ziel-Stereotype', 'Ziel-Paket']];
  var relRows = [['EA-Connector-ID', 'Quelle', 'Quelle-Stereotype', 'Connector-Typ', 'Stereotype', 'Name', 'Ziel', 'Ziel-Stereotype']];
  var elSeen = {}, elRows = [['Name', 'Stereotype', 'Alias', 'Paketpfad', 'Verbindungen (Gesamt)', 'Beschreibung / Notiz']];
  function addEl(oid) {
    if (elSeen[oid]) return;
    elSeen[oid] = true;
    var x = OBJS[oid];
    if (!x) return;
    elRows.push([x.name || '', x.st || '', x.alias || '', x.pkgFull || x.pkg || '', CONNCOUNT[oid] || 0, shortLabel(x.note || '', 400)]);
  }
  if (o.s) addEl(PATH.start);
  if (o.e) addEl(PATH.end);
  for (i = 0; i < cur.length; i++) {
    var st = cur[i];
    var a = OBJS[st.from], b = OBJS[st.to];
    addEl(st.from); addEl(st.to);
    stepRows.push([i + 1, a ? a.name : '?', a ? a.st : '', st.st || st.type || '', st.name || '', st.forward ? '➜ vorwärts' : '◄ invers', b ? b.name : '?', b ? b.st : '', b ? b.pkgFull : '']);
    relRows.push([st.cid, a ? a.name : '?', a ? a.st : '', st.type || '', st.st || '', st.name || '', b ? b.name : '?', b ? b.st : '']);
  }

  var sheets = [
    { name: '1_Uebersicht', rows: ovRows, widths: [30, 80], hasHeader: true },
    { name: '2_Schrittkette (' + cur.length + ')', rows: stepRows, widths: [5, 34, 20, 22, 22, 12, 34, 20, 40], hasHeader: true },
    { name: '3_Elemente (' + (elRows.length - 1) + ')', rows: elRows, widths: [36, 22, 18, 44, 16, 52], hasHeader: true }
  ];
  if (relRows.length > 1) sheets.push({ name: '4_Beziehungen', rows: relRows, widths: [12, 34, 20, 18, 20, 22, 34, 20], hasHeader: true });
  var fn = 'ADMBw_QEA-Analyzer_Pfad_' + safeName(o.s ? o.s.name : 'Start') + '_' + safeName(o.e ? o.e.name : 'Ziel') + '_' + safeName(MODELLNAME) + '_' + dateStamp() + '.xlsx';
  downloadXLSX(fn, sheets);
}

function pathExportPNG() {
  var svg = document.querySelector('#pathgraph svg');
  if (!svg) { alert('Bitte zuerst eine Verbindung suchen (der Pfad-Graph wird dann angezeigt).'); return; }
  var o = PATH.last;
  var title = 'Pfadanalyse: ' + (o && o.s ? shortLabel(o.s.name, 44) : '') + ' ➜ ' + (o && o.e ? shortLabel(o.e.name, 44) : '');
  var cur = o ? (o.mode === 'multi' ? o.paths[PATH.selPath] : o.steps) : null;
  var sub = cur ? (cur.length + ' Hops · ' + (o.directed ? 'gerichtet' : 'ungerichtet') + ' · ' + (o.mode === 'multi' ? 'Alternativpfad ' + (PATH.selPath + 1) : 'kürzester Pfad')) : '';
  var fn = 'ADMBw_QEA-Analyzer_Pfad_' + safeName(o && o.s ? o.s.name : 'Start') + '_' + safeName(o && o.e ? o.e.name : 'Ziel') + '_' + dateStamp() + '.png';
  exportSvgElementToPNG(svg, title, sub, fn);
}
