/* ============================================================================
   EAM Suite — Teil 6: SICHT-RENDERER + BEFUNDE (Issues)
   ----------------------------------------------------------------------------
   Der Renderer zeichnet eine Sicht so, wie sie im Modell liegt:
     * Positionen aus t_diagramobjects (RectLeft/RectTop/RectRight/RectBottom)
     * sichtbare Verbindungen aus t_diagramlinks (Hidden=1 wird ausgelassen)
     * Linienfuehrung aus Geometry: EDGE=1..4 und Ankerpunkte LLB/LLT/LMB/LMT/LRT/LRB
     * Buendelung aus Style: TREE=LH/LV/V/OS/OR (Baumkanten)
   Nichts wird ergaenzt: Liegen fuer eine Sicht keine Link-Eintraege vor, wird
   das gesagt. Optional lassen sich die nicht belegten Verbindungen grau und
   gestrichelt einblenden (Schalter, Standard aus).

   Befunde: Eine Notiz je Sicht oder je Element, lokal gespeichert, als
   JSON-Batch exportierbar und als eigene .qea mit Stereotyp «Issue».
   ============================================================================ */

/* ---------------------------------------------------------------- Geometrie */
function eaFields(str) {
  var out = {};
  if (!str) return out;
  var parts = String(str).split(';');
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i];
    if (p.indexOf('=') < 0) continue;
    var k = p.substring(0, p.indexOf('='));
    var v = p.substring(p.indexOf('=') + 1);
    if (k.charAt(0) === '$') k = k.substring(1);
    out[k] = v;
  }
  return out;
}

function eaAnchor(str) {
  /* "CX=7:CY=14:OX=0:..." -> {cx:7, cy:14} */
  var out = { cx: 0, cy: 0 };
  if (!str) return out;
  var parts = String(str).split(':');
  for (var i = 0; i < parts.length; i++) {
    var kv = parts[i].split('=');
    if (kv.length !== 2) continue;
    if (kv[0] === 'CX') out.cx = parseFloat(kv[1]) || 0;
    if (kv[0] === 'CY') out.cy = parseFloat(kv[1]) || 0;
  }
  return out;
}

function eaGeometry(str) {
  var f = eaFields(str);
  var g = { edge: parseInt(f.EDGE, 10), tree: '', anchors: {} };
  var keys = ['LLB', 'LLT', 'LMB', 'LMT', 'LRT', 'LRB'];
  for (var i = 0; i < keys.length; i++) {
    var v = f[keys[i]];
    if (v) g.anchors[keys[i]] = eaAnchor(v);
  }
  return g;
}

function eaStyle(str) {
  var f = eaFields(str);
  return {
    mode: parseInt(f.Mode, 10),
    tree: f.TREE || '',
    color: (f.Color != null && f.Color !== '') ? parseInt(f.Color, 10) : null,
    lwidth: (f.LWidth != null && f.LWidth !== '') ? parseInt(f.LWidth, 10) : null
  };
}

/* ------------------------------------------------------------- Zeichenhilfe */
function diagEsc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function anchorPoint(rect, code, val) {
  var L = rect.x, R = rect.x + rect.w, T = rect.y, B = rect.y + rect.h;
  var cx = val ? val.cx : 0, cy = val ? val.cy : 0;
  if (code === 'LLB') return { x: L, y: B - cy };
  if (code === 'LLT') return { x: L, y: T + cy };
  if (code === 'LRT') return { x: R, y: T + cy };
  if (code === 'LRB') return { x: R, y: B - cy };
  if (code === 'LMT') return { x: L + cx, y: T };
  if (code === 'LMB') return { x: L + cx, y: B };
  return null;
}

function sidePoint(rect, side) {
  if (side === 'top') return { x: rect.x + rect.w / 2, y: rect.y };
  if (side === 'bottom') return { x: rect.x + rect.w / 2, y: rect.y + rect.h };
  if (side === 'left') return { x: rect.x, y: rect.y + rect.h / 2 };
  return { x: rect.x + rect.w, y: rect.y + rect.h / 2 };
}

/* Kante eines Rechtecks in Richtung eines Punktes schneiden */
function clipToRect(rect, px, py, fromX, fromY) {
  var cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2;
  var dx = px - cx, dy = py - cy;
  if (!dx && !dy) return { x: cx, y: cy };
  var sx = dx === 0 ? Infinity : (rect.w / 2) / Math.abs(dx);
  var sy = dy === 0 ? Infinity : (rect.h / 2) / Math.abs(dy);
  var s = Math.min(sx, sy);
  return { x: cx + dx * s, y: cy + dy * s };
}

function polyPath(points, radius) {
  if (!points.length) return '';
  if (points.length === 1) return 'M ' + points[0].x.toFixed(1) + ' ' + points[0].y.toFixed(1);
  var r = radius || 0;
  var d = 'M ' + points[0].x.toFixed(1) + ' ' + points[0].y.toFixed(1);
  for (var i = 1; i < points.length; i++) {
    var prev = points[i - 1], cur = points[i];
    if (r > 0 && i < points.length - 1) {
      var nxt = points[i + 1];
      var v1 = { x: cur.x - prev.x, y: cur.y - prev.y };
      var v2 = { x: nxt.x - cur.x, y: nxt.y - cur.y };
      var l1 = Math.sqrt(v1.x * v1.x + v1.y * v1.y);
      var l2 = Math.sqrt(v2.x * v2.x + v2.y * v2.y);
      var rr = Math.min(r, l1 / 2, l2 / 2);
      if (l1 > 0.5 && l2 > 0.5) {
        var p1 = { x: cur.x - (v1.x / l1) * rr, y: cur.y - (v1.y / l1) * rr };
        var p2 = { x: cur.x + (v2.x / l2) * rr, y: cur.y + (v2.y / l2) * rr };
        d += ' L ' + p1.x.toFixed(1) + ' ' + p1.y.toFixed(1);
        d += ' Q ' + cur.x.toFixed(1) + ' ' + cur.y.toFixed(1) + ' ' + p2.x.toFixed(1) + ' ' + p2.y.toFixed(1);
        continue;
      }
    }
    d += ' L ' + cur.x.toFixed(1) + ' ' + cur.y.toFixed(1);
  }
  return d;
}

function pathMidpoint(points) {
  if (!points.length) return null;
  if (points.length === 1) return points[0];
  var total = 0, i, segs = [];
  for (i = 1; i < points.length; i++) {
    var dx = points[i].x - points[i - 1].x, dy = points[i].y - points[i - 1].y;
    var len = Math.sqrt(dx * dx + dy * dy);
    segs.push(len);
    total += len;
  }
  var half = total / 2, acc = 0;
  for (i = 0; i < segs.length; i++) {
    if (acc + segs[i] >= half) {
      var t = segs[i] ? (half - acc) / segs[i] : 0;
      return {
        x: points[i].x + (points[i + 1].x - points[i].x) * t,
        y: points[i].y + (points[i + 1].y - points[i].y) * t
      };
    }
    acc += segs[i];
  }
  return points[points.length - 1];
}

/* ------------------------------------------------------------------ Renderer */

/* ------------------------------------------------- Rechtwinklige Linienfuehrung
   Nach den BPMN-Gestaltungsregeln: keine schraegen Linien, Anschluesse exakt
   auf dem Rand, Kreuzungen moeglichst vermeiden. ------------------------------------ */

function seiteAusAnker(code) {
  var c = String(code || '').charAt(0).toUpperCase();
  return c === 'L' ? 'l' : c === 'R' ? 'r' : c === 'T' ? 't' : c === 'B' ? 'b' : null;
}

/* Zugewandte Seite: horizontale Richtung hat Vorrang, damit Fluesse von links
   nach rechts laufen (BPMN-Grundsatz). */
function seiteNachLage(ra, rb) {
  var dx = (rb.x + rb.w / 2) - (ra.x + ra.w / 2);
  var dy = (rb.y + rb.h / 2) - (ra.y + ra.h / 2);
  if (Math.abs(dx) >= Math.abs(dy) * 0.7) return dx >= 0 ? 'r' : 'l';
  return dy >= 0 ? 'b' : 't';
}

function richtung(seite) {
  if (seite === 'l') return { x: -1, y: 0 };
  if (seite === 'r') return { x: 1, y: 0 };
  if (seite === 't') return { x: 0, y: -1 };
  return { x: 0, y: 1 };
}

/* Punkt exakt auf dem Rand; Lage entlang der Kante aus dem Ziel abgeleitet. */
function randPunkt(rc, seite, ziel, versatz) {
  var v = versatz || 0;
  /* Randabstand darf die Form nicht ueberschreiten (Pins sind nur 16 px gross). */
  var my = Math.max(2, Math.min(12, rc.h / 2 - 1));
  var mx = Math.max(2, Math.min(12, rc.w / 2 - 1));
  if (seite === 'l' || seite === 'r') {
    var y = Math.max(rc.y + my, Math.min(rc.y + rc.h - my, ziel.y + v));
    return { x: (seite === 'l' ? rc.x : rc.x + rc.w), y: y };
  }
  var x = Math.max(rc.x + mx, Math.min(rc.x + rc.w - mx, ziel.x + v));
  return { x: x, y: (seite === 't' ? rc.y : rc.y + rc.h) };
}

/* Ankerpunkt aus der Modelldatei auf den Rand ziehen (kein Ende im Nichts). */
/* Ereignisse sind Kreise, Gateways Rauten: Der Rand liegt nur in der Mitte der
   Bounding-Box an. Andernfalls endet die Linie neben der Form statt an ihr. */
/* Wird das Element im Bild gezeichnet? Sonst darf keine Linie dorthin laufen. */
/* Liegt das Element in einem Pool? Dann ist der Pool das Ziel eines
   Nachrichtenflusses ueber die Poolgrenze (Blackbox). */
function poolVonBauen(order) {
  var pools = [];
  for (var i = 0; i < order.length; i++) if (/^pool$/i.test(order[i].st || '')) pools.push(order[i]);
  var map = {};
  for (var j = 0; j < order.length; j++) {
    var r = order[j], treffer = null;
    for (var k = 0; k < pools.length; k++) {
      var p = pools[k];
      if (p === r) continue;
      var cx = r.x + r.w / 2, cy = r.y + r.h / 2;
      if (cx > p.x && cx < p.x + p.w && cy > p.y && cy < p.y + p.h) {
        if (!treffer || p.w * p.h < treffer.w * treffer.h) treffer = p;
      }
    }
    map[r.oid] = treffer;
  }
  return map;
}

function elternRechteck(rc, rects) {
  var o = (typeof OBJS !== 'undefined') ? OBJS[rc.oid] : null;
  if (!o || o.parent == null) return null;
  return rects[String(o.parent)] || null;
}

function wirdGezeichnet(rc, bpmn) {
  if (!rc) return false;
  if (bpmn && /^actionpin$/i.test(rc.type || '')) return true;
  if (!rc.name && !rc.st) return false;
  if (/^proxyconn?ector$/i.test(rc.st || '')) return false;
  return true;
}

/* Punkt auf die tatsaechliche Form ziehen: Kreis oder Raute. Die Bounding-Box
   ist bei beiden groesser als die Form, sonst bleibt ein Spalt. */
function aufForm(rc, pt) {
  if (!pt) return pt;
  var s = (String(rc.st || '') + ' ' + String(rc.type || '')).toLowerCase();
  var cx = rc.x + rc.w / 2, cy = rc.y + rc.h / 2;
  var dx = pt.x - cx, dy = pt.y - cy;
  var d = Math.sqrt(dx * dx + dy * dy) || 1;
  if (/startevent|endevent|intermediateevent|^event /.test(s)) {
    var r = Math.max(6, Math.min(rc.w, rc.h) / 2 - 1);
    return { x: cx + dx / d * r, y: cy + dy / d * r };
  }
  if (/gateway|decision/.test(s)) {
    var nenner = Math.abs(dx) / (rc.w / 2) + Math.abs(dy) / (rc.h / 2);
    var k = nenner ? 1 / nenner : 1;
    return { x: cx + dx * k, y: cy + dy * k };
  }
  return pt;
}

function istPunktform(rc) {
  var s = (String(rc.st || '') + ' ' + String(rc.type || '')).toLowerCase();
  return /startevent|endevent|intermediateevent|gateway|decision|^event /.test(s);
}

function seitenMitte(rc, seite) {
  if (seite === 'l') return { x: rc.x, y: rc.y + rc.h / 2 };
  if (seite === 'r') return { x: rc.x + rc.w, y: rc.y + rc.h / 2 };
  if (seite === 't') return { x: rc.x + rc.w / 2, y: rc.y };
  return { x: rc.x + rc.w / 2, y: rc.y + rc.h };
}

function aufRand(rc, pt, seite) {
  if (!pt) return null;
  if (seite === 'l' || seite === 'r') {
    return { x: (seite === 'l' ? rc.x : rc.x + rc.w),
             y: Math.max(rc.y + 2, Math.min(rc.y + rc.h - 2, pt.y)) };
  }
  return { x: Math.max(rc.x + 2, Math.min(rc.x + rc.w - 2, pt.x)),
           y: (seite === 't' ? rc.y : rc.y + rc.h) };
}

function streckeFrei(a, b, hindernisse) {
  var x1 = Math.min(a.x, b.x) - 2, x2 = Math.max(a.x, b.x) + 2;
  var y1 = Math.min(a.y, b.y) - 2, y2 = Math.max(a.y, b.y) + 2;
  for (var i = 0; i < hindernisse.length; i++) {
    var r = hindernisse[i];
    if (x2 <= r.x || x1 >= r.x + r.w || y2 <= r.y || y1 >= r.y + r.h) continue;
    return false;
  }
  return true;
}

/* Punkte entdoppeln und Zwischenpunkte auf gerader Linie entfernen. */
function vereinfache(pts) {
  var out = [];
  for (var i = 0; i < pts.length; i++) {
    var p = pts[i];
    if (!p) continue;
    if (out.length && Math.abs(out[out.length - 1].x - p.x) < 0.6 &&
        Math.abs(out[out.length - 1].y - p.y) < 0.6) continue;
    out.push(p);
  }
  for (var j = out.length - 2; j >= 1; j--) {
    var a = out[j - 1], b = out[j], c = out[j + 1];
    if ((Math.abs(a.x - b.x) < 0.6 && Math.abs(b.x - c.x) < 0.6) ||
        (Math.abs(a.y - b.y) < 0.6 && Math.abs(b.y - c.y) < 0.6)) out.splice(j, 1);
  }
  return out;
}

/* Rechtwinkliger Weg von p1 nach p2, mit Stummel, Kanal und Hindernisprüfung. */
function routeOrtho(p1, s1, p2, s2, hindernisse) {
  var stub = 16;
  var d1 = richtung(s1), d2 = richtung(s2);
  var q1 = { x: p1.x + d1.x * stub, y: p1.y + d1.y * stub };
  var q2 = { x: p2.x + d2.x * stub, y: p2.y + d2.y * stub };
  var h1 = (s1 === 'l' || s1 === 'r'), h2 = (s2 === 'l' || s2 === 'r');
  var pts = [];

  if (h1 && h2) {
    if (Math.abs(q1.y - q2.y) < 1.5) {
      pts = [p1, q1, q2, p2];
    } else {
      var mitte = (q1.x + q2.x) / 2;
      var kan = [mitte, mitte + 24, mitte - 24, mitte + 52, mitte - 52, mitte + 90, mitte - 90];
      var wahl = mitte;
      for (var i = 0; i < kan.length; i++) {
        var mx = kan[i];
        if (streckeFrei(q1, { x: mx, y: q1.y }, hindernisse) &&
            streckeFrei({ x: mx, y: q1.y }, { x: mx, y: q2.y }, hindernisse) &&
            streckeFrei({ x: mx, y: q2.y }, q2, hindernisse)) { wahl = mx; break; }
      }
      pts = [p1, q1, { x: wahl, y: q1.y }, { x: wahl, y: q2.y }, q2, p2];
    }
  } else if (!h1 && !h2) {
    if (Math.abs(q1.x - q2.x) < 1.5) {
      pts = [p1, q1, q2, p2];
    } else {
      var m2 = (q1.y + q2.y) / 2;
      var kan2 = [m2, m2 + 24, m2 - 24, m2 + 52, m2 - 52, m2 + 90, m2 - 90];
      var wahl2 = m2;
      for (var k = 0; k < kan2.length; k++) {
        var my = kan2[k];
        if (streckeFrei(q1, { x: q1.x, y: my }, hindernisse) &&
            streckeFrei({ x: q1.x, y: my }, { x: q2.x, y: my }, hindernisse) &&
            streckeFrei({ x: q2.x, y: my }, q2, hindernisse)) { wahl2 = my; break; }
      }
      pts = [p1, q1, { x: q1.x, y: wahl2 }, { x: q2.x, y: wahl2 }, q2, p2];
    }
  } else {
    /* gemischt: ein Knick */
    var eck = h1 ? { x: q2.x, y: q1.y } : { x: q1.x, y: q2.y };
    pts = [p1, q1, eck, q2, p2];
  }
  return vereinfache(pts);
}

var DIAG = (function () {
  var ghostOn = {};

  function stats(diagId) {
    var links = DIAGLINK[diagId] || [];
    var s = { total: links.length, visible: 0, hidden: 0, routed: 0 };
    for (var i = 0; i < links.length; i++) {
      if (links[i].hidden) { s.hidden++; continue; }
      s.visible++;
      var g = eaGeometry(links[i].geo);
      if (g.edge || g.anchors.LMT || g.anchors.LMB || g.anchors.LLB) s.routed++;
    }
    return s;
  }

  function render(diag, host) {
    if (!host) return;
    var objs = DIAGOBJ[diag.id] || [];
    if (!objs.length) {
      host.innerHTML = '<div class="hint">Leere Sicht — es sind keine Elemente platziert.</div>';
      return;
    }

    var rects = {}, order = [], minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (var i = 0; i < objs.length; i++) {
      var o = objs[i], obj = OBJS[o.oid];
      if (!obj) continue;
      var w = o.r - o.l, h = o.t - o.b;
      if (w <= 0 || h <= 0) continue;
      var rc = {
        oid: o.oid, x: o.l, y: -o.t, w: w, h: h,
        name: obj.name, st: obj.st, type: obj.type, seq: o.seq || 0
      };
      rects[o.oid] = rc;
      order.push(rc);
      if (rc.x < minX) minX = rc.x;
      if (rc.x + rc.w > maxX) maxX = rc.x + rc.w;
      if (rc.y < minY) minY = rc.y;
      if (rc.y + rc.h > maxY) maxY = rc.y + rc.h;
    }
    if (minX === Infinity) {
      host.innerHTML = '<div class="hint">Leere Sicht — keine darstellbaren Elemente.</div>';
      return;
    }

    var bpmn = (typeof BPMN !== 'undefined') && BPMN.modus(diag.id) === 'bpmn';
    var pad = 30;
    var ox = -minX + pad, oy = -minY + pad;
    var W = Math.round(maxX - minX + 2 * pad + (bpmn ? 240 : 0)), H = Math.round(maxY - minY + 2 * pad);

    var issues = (typeof ISSUE !== 'undefined' && ISSUE.idsFor) ? ISSUE.idsFor(diag.id) : {};
    var links = DIAGLINK[diag.id] || [];
    var st = stats(diag.id);

    var parts = [];
    parts.push('<div class="diag-tools">' +
      '<span class="diag-stat">' + st.visible + ' sichtbare Verbindung(en)' +
      (st.hidden ? ' · ' + st.hidden + ' unterdrückt' : '') + '</span>' +
      '<label class="diag-ghost"><input type="checkbox" ' + (ghostOn[diag.id] ? 'checked' : '') +
      ' onchange="DIAG.toggleGhost(' + diag.id + ')"> nicht belegte Verbindungen grau zeigen</label>' +
      (bpmn ? '<span class="diag-legend">' +
        '<i class="lg lg-seq"></i>Steuerfluss' +
        '<i class="lg lg-obj"></i>Objekt' +
        '<i class="lg lg-msg"></i>Nachricht' +
        '<i class="lg lg-info"></i>Information</span>' : '') +
      '<label class="diag-ghost">Darstellung <select onchange="DIAG.setModus(' + diag.id + ',this.value)">' +
      '<option value="auto"' + (bpmnModus(diag.id) === 'auto' ? ' selected' : '') + '>automatisch' + (bpmn ? ' (BPMN)' : ' (UML)') + '</option>' +
      '<option value="bpmn"' + (bpmnModus(diag.id) === 'bpmn' ? ' selected' : '') + '>BPMN</option>' +
      '<option value="uml"' + (bpmnModus(diag.id) === 'uml' ? ' selected' : '') + '>UML</option>' +
      '</select></label>' +
      '</div>');

    if (!st.visible) {
      parts.push('<div class="hint">Für diese Sicht sind keine Verbindungen modelliert' +
        (st.hidden ? ' (' + st.hidden + ' unterdrückt)' : '') + '.</div>');
    }

    parts.push('<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H +
      '" viewBox="0 0 ' + W + ' ' + H + '" data-base-w="' + W + '" data-base-h="' + H + '">');
    parts.push('<defs>' +
      '<marker id="arr6" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="13" markerHeight="13" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#004471"/></marker>' +
      '<marker id="arr6g" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="13" markerHeight="13" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#B8C4CE"/></marker>' +
      '<filter id="agShadow" x="-25%" y="-25%" width="150%" height="150%">' +
      '<feDropShadow dx="0" dy="1.5" stdDeviation="1.6" flood-color="#32325d" flood-opacity="0.14"/></filter>' +
      '</defs>');

    var connStart = parts.length;

    /* --- nicht belegte Verbindungen (optional, gestrichelt) --- */
    if (ghostOn[diag.id]) {
      var belegt = {};
      for (i = 0; i < links.length; i++) {
        if (links[i].hidden) continue;
        belegt[String(links[i].cid)] = true;
      }
      for (i = 0; i < CONS.length; i++) {
        var gc = CONS[i];
        if (belegt[String(gc.id)]) continue;
        var gra = rects[gc.a], grb = rects[gc.b];
        if (!gra || !grb || gra === grb) continue;
        var gp1 = clipToRect(gra, grb.x + grb.w / 2, grb.y + grb.h / 2);
        var gp2 = clipToRect(grb, gra.x + gra.w / 2, gra.y + gra.h / 2);
        parts.push('<line x1="' + (gp1.x + ox).toFixed(1) + '" y1="' + (gp1.y + oy).toFixed(1) +
          '" x2="' + (gp2.x + ox).toFixed(1) + '" y2="' + (gp2.y + oy).toFixed(1) +
          '" stroke="#C3CDD6" stroke-width="1" stroke-dasharray="4 4" marker-end="url(#arr6g)"/>');
      }
    }

    /* --- belegte Verbindungen --- */
    var treeCount = {}, drawn = 0, missing = 0, labels = [], arrows = [], portZaehler = {};
    var hindernisse = order.filter(function (r) { return !/^(pool|lane)$/i.test(r.st || ''); });
    var poolVon = bpmn ? poolVonBauen(order) : {};
    for (i = 0; i < links.length; i++) {
      var link = links[i];
      if (link.hidden) continue;
      var cn = CONNMAP[String(link.cid)];
      if (!cn) continue;
      var ra = rects[cn.a], rb = rects[cn.b];
      if (!ra || !rb || ra === rb) { missing++; continue; }

      /* Pins sind Anschlussklemmen: Die Linie gehoert an die Aufgabe, nicht an
         die 16-px-Klemme. */
      if (bpmn && /^actionpin$/i.test(ra.type || '')) ra = elternRechteck(ra, rects) || ra;
      if (bpmn && /^actionpin$/i.test(rb.type || '')) rb = elternRechteck(rb, rects) || rb;
      if (ra === rb) { missing++; continue; }

      /* Nachrichtenfluss ueber die Poolgrenze endet am Pool, nicht im Leeren. */
      if (bpmn) {
        var pa = poolVon[ra.oid], pb = poolVon[rb.oid];
        if (pb && pa !== pb) rb = pb;
        if (ra === rb) { missing++; continue; }
      }
      /* Elemente ohne Namen und ohne Stereotyp werden nicht gezeichnet; eine
         Linie dorthin haette kein Ziel. Pins sind davon ausgenommen. */
      if (!wirdGezeichnet(ra, bpmn) || !wirdGezeichnet(rb, bpmn)) { missing++; continue; }

      var geo = eaGeometry(link.geo);
      var sty = eaStyle(link.sty);
      var isTree = !!sty.tree && sty.tree !== '-';

      /* Anschlussseiten: gespeicherte Anker haben Vorrang, sonst die zugewandte
         Seite. Damit laufen Fluesse von Kante zu Kante statt schraeg durch den
         Raum, und die Spitze sitzt exakt auf dem Rand. */
      var srcCode = null, dstCode = null;
      if (geo.anchors.LLB || geo.anchors.LLT) srcCode = geo.anchors.LLB ? 'LLB' : 'LLT';
      else if (geo.anchors.LMB) srcCode = 'LMB';
      if (geo.anchors.LRT || geo.anchors.LRB) dstCode = geo.anchors.LRB ? 'LRB' : 'LRT';
      else if (geo.anchors.LMT) dstCode = 'LMT';

      var s1 = (srcCode && seiteAusAnker(srcCode)) || seiteNachLage(ra, rb);
      var s2 = (dstCode && seiteAusAnker(dstCode)) || seiteNachLage(rb, ra);

      /* Mehrere Kanten an derselben Seite auffaechern, sonst liegen sie uebereinander. */
      var pKey1 = ra.oid + ':' + s1, pKey2 = rb.oid + ':' + s2;
      var n1 = (portZaehler[pKey1] = (portZaehler[pKey1] || 0) + 1) - 1;
      var n2 = (portZaehler[pKey2] = (portZaehler[pKey2] || 0) + 1) - 1;
      var v1 = (n1 % 2 ? -1 : 1) * Math.ceil(n1 / 2) * 12;
      var v2 = (n2 % 2 ? -1 : 1) * Math.ceil(n2 / 2) * 12;

      var mzA = { x: rb.x + rb.w / 2, y: rb.y + rb.h / 2 };
      var p1, p2;
      if (srcCode) p1 = aufRand(ra, anchorPoint(ra, srcCode, geo.anchors[srcCode]), s1);
      else if (bpmn && istPunktform(ra)) p1 = seitenMitte(ra, s1);
      else p1 = randPunkt(ra, s1, mzA, v1);

      if (dstCode) p2 = aufRand(rb, anchorPoint(rb, dstCode, geo.anchors[dstCode]), s2);
      else if (bpmn && istPunktform(rb)) p2 = seitenMitte(rb, s2);
      else p2 = randPunkt(rb, s2, p1, v2);

      if (bpmn && istPunktform(ra)) p1 = aufForm(ra, p1);
      if (bpmn && istPunktform(rb)) p2 = aufForm(rb, p2);

      var pts;
      if (isTree) {
        var count = treeCount[cn.a] || 0;
        treeCount[cn.a] = count + 1;
        var busY;
        if (rb.y > ra.y) busY = ra.y + ra.h + 22 + count * 9;
        else busY = rb.y + rb.h + 22 + count * 9;
        pts = [p1, { x: p1.x, y: busY }, { x: p2.x, y: busY }, p2];
      } else {
        pts = routeOrtho(p1, s1, p2, s2, hindernisse);
      }
      pts = vereinfache(pts);

      var d = polyPath(
        [{ x: pts[0].x + ox, y: pts[0].y + oy }].concat(
          pts.slice(1).map(function (p) { return { x: p.x + ox, y: p.y + oy }; })),
        geo.edge === 4 ? 9 : (isTree ? 7 : 0)
      );
      var fl = bpmn ? BPMN.fluss(cn) : { dash: '', offen: false, breite: 1.3, farbe: null };
      var col = (sty.color != null && sty.color >= 0) ? '#' + ('000000' + sty.color.toString(16)).slice(-6)
                : (fl.farbe || '#004471');

      /* Pfeilspitze separat merken: Sie wird nach den Kaesten gezeichnet,
         damit sie nicht von der Zielflaeche verdeckt wird. */
      var lastI = pts.length - 1;
      var segX = pts[lastI].x - pts[lastI - 1].x, segY = pts[lastI].y - pts[lastI - 1].y;
      arrows.push({
        x: pts[lastI].x + ox, y: pts[lastI].y + oy,
        a: Math.atan2(segY, segX),
        len: Math.sqrt(segX * segX + segY * segY),
        color: col,
        offen: !!fl.offen
      });
      if (fl.offen) arrows[arrows.length - 1].offen = true;
      parts.push('<path d="' + d + '" fill="none" stroke="' + col + '" stroke-width="' +
        ((sty.lwidth && sty.lwidth > 0) ? sty.lwidth : fl.breite) +
        (fl.dash ? '" stroke-dasharray="' + fl.dash : '') +
        '" marker-end="url(#arr6)"><title>' + diagEsc(cn.st || cn.type || '') + '</title></path>');

      var mid = pathMidpoint(pts.map(function (p) { return { x: p.x + ox, y: p.y + oy }; }));
      var labTxt = bpmn ? ((typeof BPMN !== 'undefined') ? BPMN.beschriftung(cn) : '') : cn.st;
      if (labTxt && mid) {
        labels.push({ x: mid.x, y: mid.y - 4, text: labTxt });
      }
      drawn++;
    }

    /* Verbindungen werden spaeter gezeichnet: Container (Rahmen, Pools,
       Lanes) zuerst, dann die Linien, dann die Elemente. Sonst deckt die
       Fuellung eines Rahmens die Verbindungen zu. */
    var connParts = parts.splice(connStart);

    /* --- Elemente --- */
    /* Hoher Sequence-Wert liegt in EA hinten. Aufsteigend gezeichnet wuerde
       ein Rahmen (Seq 13) die Zustandskoerper (Seq 1..12) verdecken. */
    order.sort(function (a, b) { return (b.seq || 0) - (a.seq || 0); });

    /* Container erkennen: Rechteck umschliesst mindestens zwei andere. */
    var cont = {};
    for (var ci = 0; ci < order.length; ci++) {
      var cr = order[ci], innen = 0;
      for (var cj = 0; cj < order.length; cj++) {
        if (ci === cj) continue;
        var cq = order[cj];
        if (cq.x >= cr.x - 1 && cq.y >= cr.y - 1 &&
            cq.x + cq.w <= cr.x + cr.w + 1 && cq.y + cq.h <= cr.y + cr.h + 1) innen++;
      }
      if (innen >= 2) cont[cr.oid] = true;
    }

    for (var pass = 0; pass < 2; pass++) {
      if (pass === 1) { for (var cp = 0; cp < connParts.length; cp++) parts.push(connParts[cp]); }
      for (var bi = 0; bi < order.length; bi++) {
        var rc = order[bi];
        if ((!!cont[rc.oid]) !== (pass === 0)) continue;
      if (bpmn && /^actionpin$/i.test(rc.type || '')) continue;   /* Klemmen nicht zeichnen */
      if (!rc.name && !rc.st) continue;
      if (/^proxyconn?ector$/i.test(rc.st)) continue;
      var isBoundary = (rc.type === 'Boundary');
      var isText = (rc.type === 'Text');
      var isLane = /^(pool|lane)$/i.test(rc.st);
      var fill = (typeof stFill === 'function') ? stFill(rc.st) : '#EAF2F8';
      var stroke = (typeof stColor === 'function') ? stColor(rc.st) : '#004471';
      var dash = '';
      if (isBoundary) { fill = 'none'; dash = ' stroke-dasharray="5 4"'; stroke = '#8AA0B0'; }
      else if (isLane) { fill = '#EEF4F8'; stroke = '#004471'; }

      var flagged = issues[rc.oid];
      var click = (!isBoundary && rc.oid) ? ' class="diag-node" onclick="openElement(\'' + rc.oid + '\')"' : '';
      if (bpmn) {
        parts.push('<g' + click + '><title>' + diagEsc(rc.name + (rc.st ? '  «' + rc.st + '»' : '')) + '</title>' +
          BPMN.shape(rc, ox, oy, flagged) + '</g>');
        continue;
      }
      parts.push('<g' + click + '><title>' + diagEsc(rc.name + (rc.st ? '  «' + rc.st + '»' : '')) + '</title>');
      if (!isText) parts.push('<rect x="' + (rc.x + ox).toFixed(1) + '" y="' + (rc.y + oy).toFixed(1) +
        '" width="' + rc.w.toFixed(1) + '" height="' + rc.h.toFixed(1) + '" rx="4" fill="' + fill +
        '" stroke="' + (flagged ? '#B45309' : stroke) + '" stroke-width="' + (flagged ? '2.4' : '1.4') + '"' + dash + '/>');
      if (flagged) {
        parts.push('<circle cx="' + (rc.x + ox + rc.w - 7).toFixed(1) + '" cy="' + (rc.y + oy + 7).toFixed(1) +
          '" r="4.5" fill="#B45309"><title>' + diagEsc(flagged + ' Befund(e)') + '</title></circle>');
      }

      var nm = String(rc.name || '').replace(/\r?\n/g, ' ');
      var fs = 11;
      if (rc.st && !isBoundary && rc.w >= 58) {
        var band = '«' + rc.st + '»';
        if (isLane && nm) band = '«' + rc.st + '» ' + nm;
        var maxB = Math.max(6, Math.floor((rc.w - 10) / 4.6));
        if (band.length > maxB) band = band.substring(0, Math.max(5, maxB - 1)) + '…';
        parts.push('<rect x="' + (rc.x + ox).toFixed(1) + '" y="' + (rc.y + oy).toFixed(1) +
          '" width="' + rc.w.toFixed(1) + '" height="13" rx="3" fill="' + stroke + '" opacity="0.14"/>');
        parts.push('<text x="' + (rc.x + ox + rc.w / 2).toFixed(1) + '" y="' + (rc.y + oy + 9.5).toFixed(1) +
          '" font-size="7.5" font-weight="600" fill="' + stroke + '" text-anchor="middle">' + diagEsc(band) + '</text>');
      }
      if (isBoundary) {
        var maxL = Math.max(6, Math.floor((rc.w - 10) / (fs * 0.66)));
        var lab = nm.length > maxL ? nm.substring(0, Math.max(3, maxL - 1)) + '…' : nm;
        parts.push('<text x="' + (rc.x + ox + 6).toFixed(1) + '" y="' + (rc.y + oy + 12).toFixed(1) +
          '" font-size="' + fs + '" font-weight="600" fill="#5A7285" text-anchor="start">' + diagEsc(lab) + '</text>');
      } else if (isLane) {
        /* Name steht im Band */
      } else if (rc.w < 72) {
        var shortN = nm.length > 24 ? nm.substring(0, 22) + '…' : nm;
        parts.push('<text x="' + (rc.x + ox + rc.w + 4).toFixed(1) + '" y="' + (rc.y + oy + rc.h / 2 + 3).toFixed(1) +
          '" font-size="8.5" fill="#1A1A1A" text-anchor="start">' + diagEsc(shortN) + '</text>');
      } else {
        /* So viele Zeilen wie in die Hoehe passen; Schrift bei Bedarf kleiner. */
        var fs0 = 11;
        if (rc.h < 30 || rc.w < 90) fs0 = 9.5;
        var maxZeilen = Math.max(1, Math.min(4, Math.floor((rc.h - 8) / (fs0 * 1.15))));
        var lines = [], rest0 = nm;
        var maxc0 = Math.max(6, Math.floor((rc.w - 8) / (fs0 * 0.62)));
        while (rest0.length && lines.length < maxZeilen) {
          if (rest0.length <= maxc0) { lines.push(rest0); rest0 = ''; break; }
          var c0 = rest0.lastIndexOf(' ', maxc0);
          if (c0 < 4) c0 = maxc0;
          lines.push(rest0.substring(0, c0));
          rest0 = rest0.substring(c0 + 1);
        }
        if (rest0.length) {
          var last = lines[lines.length - 1];
          var keep = Math.max(3, maxc0 - 1);
          lines[lines.length - 1] = (last.length > keep ? last.substring(0, keep) : last) + '…';
        }
        fs = fs0;
        var ty = rc.y + oy + 13 + (rc.h - 15) / 2 - (lines.length - 1) * (fs * 0.62);
        for (var li = 0; li < lines.length; li++) {
          parts.push('<text x="' + (rc.x + ox + rc.w / 2).toFixed(1) + '" y="' + (ty + li * fs * 1.2).toFixed(1) +
            '" font-size="' + fs + '" font-weight="600" fill="#1A1A1A" text-anchor="middle">' + diagEsc(lines[li]) + '</text>');
        }
      }
      parts.push('</g>');
      }
    }

    /* Pfeilspitzen nach den Kaesten: garantierte Sichtbarkeit. */
    for (var ai = 0; ai < arrows.length; ai++) {
      var ar = arrows[ai];
      /* Kurze Stuecke brauchen kleine Pfeile, sonst bleibt von der Linie nichts uebrig. */
      var alen = Math.max(4, Math.min(11, (ar.len || 20) * 0.30));
      var awid = alen * 0.5;
      var ax = ar.x, ay = ar.y, ang = ar.a;
      var tip = { x: ax, y: ay };
      var b1 = { x: ax - Math.cos(ang) * alen + Math.cos(ang + Math.PI / 2) * awid,
                 y: ay - Math.sin(ang) * alen + Math.sin(ang + Math.PI / 2) * awid };
      var b2 = { x: ax - Math.cos(ang) * alen - Math.cos(ang + Math.PI / 2) * awid,
                 y: ay - Math.sin(ang) * alen - Math.sin(ang + Math.PI / 2) * awid };
      if (ar.offen) {
        /* Nachricht und Objektfluss: offene Spitze, kein gefuelltes Dreieck. */
        parts.push('<path d="M ' + b1.x.toFixed(1) + ' ' + b1.y.toFixed(1) +
          ' L ' + tip.x.toFixed(1) + ' ' + tip.y.toFixed(1) +
          ' L ' + b2.x.toFixed(1) + ' ' + b2.y.toFixed(1) +
          '" fill="none" stroke="' + ar.color + '" stroke-width="1.3"/>');
      } else {
        parts.push('<path d="M ' + tip.x.toFixed(1) + ' ' + tip.y.toFixed(1) +
          ' L ' + b1.x.toFixed(1) + ' ' + b1.y.toFixed(1) +
          ' L ' + b2.x.toFixed(1) + ' ' + b2.y.toFixed(1) + ' z" fill="' + ar.color + '"/>');
      }
    }

    /* Beschriftungen zuletzt: sonst liegen sie unter den Kaesten. */
    var gezeichnet = [];
    for (var li2 = 0; li2 < labels.length; li2++) {
      var lb = labels[li2];
      var doppelt = false;
      for (var gi = 0; gi < gezeichnet.length; gi++) {
        var g = gezeichnet[gi];
        /* gleiche Stelle oder gleicher Text in der Naehe: nur einmal zeichnen */
        if (Math.abs(g.x - lb.x) < 34 && Math.abs(g.y - lb.y) < 11) { doppelt = true; break; }
        if (g.text === lb.text && Math.abs(g.x - lb.x) < 150 && Math.abs(g.y - lb.y) < 60) { doppelt = true; break; }
      }
      if (doppelt) continue;
      gezeichnet.push(lb);
      var lt = lb.text.length > 30 ? lb.text.substring(0, 28) + '…' : lb.text;
      if (bpmn) {
        /* Argon: weisse Plakette, damit die Beschriftung auf jeder Linie lesbar bleibt. */
        var bw = Math.min(240, lt.length * 4.9 + 12);
        parts.push('<rect x="' + (lb.x - bw / 2).toFixed(1) + '" y="' + (lb.y - 10).toFixed(1) +
          '" width="' + bw.toFixed(1) + '" height="13.5" rx="6.7" fill="#FFFFFF" stroke="#e9ecef" stroke-width="1"/>');
        parts.push('<text x="' + lb.x.toFixed(1) + '" y="' + (lb.y + 0.5).toFixed(1) +
          '" font-family="\u0027Open Sans\u0027, system-ui, sans-serif" font-size="8.5" font-weight="600" ' +
          'fill="#5e72e4" text-anchor="middle">' + diagEsc(lt) + '</text>');
      } else {
        parts.push('<text x="' + lb.x.toFixed(1) + '" y="' + lb.y.toFixed(1) +
          '" font-size="8.5" fill="#334155" text-anchor="middle" style="paint-order:stroke;stroke:#FFFFFF;stroke-width:3px">' +
          diagEsc(lt) + '</text>');
      }
    }

    parts.push('</svg>');
    host.innerHTML = parts.join('');
  }

  function bpmnModus(diagId) {
    var w = null;
    try { w = localStorage.getItem('diagmodus_' + diagId); } catch (e) { }
    return (w === 'bpmn' || w === 'uml') ? w : 'auto';
  }

  function setModus(diagId, m) {
    if (typeof BPMN !== 'undefined') BPMN.setzeModus(diagId, m);
    var diag = DIAGMAP[diagId], host = null;
    var nodes = document.querySelectorAll('.svgwrap');
    for (var i = 0; i < nodes.length; i++) if (nodes[i].id === 'diag-' + diagId) host = nodes[i];
    if (diag && host) render(diag, host);
  }

  function toggleGhost(diagId) {
    ghostOn[diagId] = !ghostOn[diagId];
    var diag = DIAGMAP[diagId];
    var host = null;
    var nodes = document.querySelectorAll('.svgwrap');
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === 'diag-' + diagId) host = nodes[i];
    }
    if (diag && host) render(diag, host);
  }

  return { render: render, stats: stats, toggleGhost: toggleGhost, setModus: setModus, _ghost: ghostOn };
})();

/* ------------------------------------------------------------------ Befunde */
var ISSUE = (function () {
  var PREFIX = 'ermqs_issues_';
  var SEV = {
    hinweis: { label: 'Hinweis', color: '#0369A1' },
    befund: { label: 'Befund', color: '#B45309' },
    kritisch: { label: 'Kritisch', color: '#B91C1C' }
  };

  function modelKey() {
    return (typeof MODELLNAME !== 'undefined' && MODELLNAME) ? MODELLNAME : 'modell';
  }
  function storeKey(diagId) { return PREFIX + modelKey() + '_' + diagId; }

  function list(diagId) {
    try {
      var raw = localStorage.getItem(storeKey(diagId));
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }

  function save(diagId, arr) {
    try { localStorage.setItem(storeKey(diagId), JSON.stringify(arr)); } catch (e) { }
    if (typeof renderIssuePanel === 'function') renderIssuePanel(diagId);
  }

  function add(diagId, issue) {
    var arr = list(diagId);
    issue.id = 'I' + Date.now().toString(36) + Math.random().toString(36).substring(2, 5);
    issue.ts = new Date().toISOString();
    arr.push(issue);
    save(diagId, arr);
    var diag = DIAGMAP[diagId];
    var host = document.getElementById('diag-' + diagId);
    if (diag && host) DIAG.render(diag, host);
  }

  function remove(diagId, id) {
    var arr = list(diagId).filter(function (x) { return x.id !== id; });
    save(diagId, arr);
    var diag = DIAGMAP[diagId];
    var host = document.getElementById('diag-' + diagId);
    if (diag && host) DIAG.render(diag, host);
  }

  function idsFor(diagId) {
    var out = {}, arr = list(diagId);
    for (var i = 0; i < arr.length; i++) {
      var e = arr[i].elementId;
      if (!e) continue;
      out[e] = (out[e] || 0) + 1;
    }
    return out;
  }

  function count(diagId) { return list(diagId).length; }

  function all() {
    var out = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (!k || k.indexOf(PREFIX) !== 0) continue;
        var arr = JSON.parse(localStorage.getItem(k) || '[]');
        for (var j = 0; j < arr.length; j++) out.push(arr[j]);
      }
    } catch (e) { }
    return out;
  }

  function panelHtml(diag) {
    var arr = list(diag.id);
    var h = [];
    h.push('<div class="issue-panel" id="issue-panel-' + diag.id + '">');
    h.push('<div class="issue-head"><b>🔎 Befunde zu dieser Sicht</b> <span class="issue-count">' + arr.length + '</span>' +
      '<span class="issue-actions">' +
      '<button class="btn-sm" onclick="ISSUE.openForm(' + diag.id + ')">+ Befund</button>' +
      '<button class="btn-sm" onclick="ISSUE.exportJson(' + diag.id + ')">⤓ JSON</button>' +
      '<button class="btn-sm" onclick="ISSUE.exportQea(' + diag.id + ')" title="Schreibt die Befunde als Elemente «Issue» in eine neue .qea">💾 Issue-.qea</button>' +
      '</span></div>');
    h.push('<div class="issue-form" id="issue-form-' + diag.id + '" style="display:none"></div>');
    h.push('<div class="issue-list" id="issue-list-' + diag.id + '">');
    if (!arr.length) {
      h.push('<div class="issue-empty">Noch kein Befund. „+ Befund“ öffnet die Eingabe.</div>');
    } else {
      for (var i = 0; i < arr.length; i++) {
        var it = arr[i], sev = SEV[it.severity] || SEV.hinweis;
        h.push('<div class="issue-item">' +
          '<span class="issue-sev" style="background:' + sev.color + '">' + sev.label + '</span>' +
          '<span class="issue-txt">' + diagEsc(it.text) +
          (it.elementName ? ' <span class="issue-elem">→ ' + diagEsc(it.elementName) + '</span>' : '') + '</span>' +
          '<button class="issue-del" onclick="ISSUE.remove(' + diag.id + ',\'' + it.id + '\')" title="Befund löschen">✕</button>' +
          '</div>');
      }
    }
    h.push('</div></div>');
    return h.join('');
  }

  function openForm(diagId) {
    var box = document.getElementById('issue-form-' + diagId);
    if (!box) return;
    if (box.style.display !== 'none') { box.style.display = 'none'; return; }
    var objs = DIAGOBJ[diagId] || [], opts = ['<option value="">— Sicht allgemein —</option>'];
    var seen = {};
    for (var i = 0; i < objs.length; i++) {
      var o = OBJS[objs[i].oid];
      if (!o || seen[o.id]) continue;
      seen[o.id] = true;
      opts.push('<option value="' + diagEsc(o.id) + '">' + diagEsc((o.name || '') + ' «' + (o.st || '') + '»') + '</option>');
    }
    box.innerHTML =
      '<div class="issue-row">' +
      '<select id="issue-elem-' + diagId + '">' + opts.join('') + '</select>' +
      '<select id="issue-sev-' + diagId + '">' +
      '<option value="hinweis">Hinweis</option>' +
      '<option value="befund" selected>Befund</option>' +
      '<option value="kritisch">Kritisch</option>' +
      '</select>' +
      '</div>' +
      '<textarea id="issue-txt-' + diagId + '" rows="3" placeholder="Was ist unklar oder falsch? Kurz und konkret."></textarea>' +
      '<div class="issue-row"><button class="btn-sm" onclick="ISSUE.submit(' + diagId + ')">Befund speichern</button>' +
      '<button class="btn-sm" onclick="ISSUE.openForm(' + diagId + ')">Abbrechen</button></div>';
    box.style.display = '';
    var ta = document.getElementById('issue-txt-' + diagId);
    if (ta) ta.focus();
  }

  function submit(diagId) {
    var sel = document.getElementById('issue-elem-' + diagId);
    var sev = document.getElementById('issue-sev-' + diagId);
    var txt = document.getElementById('issue-txt-' + diagId);
    var text = txt ? String(txt.value || '').trim() : '';
    if (!text) { if (txt) txt.focus(); return; }
    var elementId = sel ? sel.value : '';
    var elementName = '';
    if (elementId) {
      var o = null;
      for (var oid in OBJS) { if (OBJS.hasOwnProperty(oid) && String(OBJS[oid].id) === String(elementId)) { o = OBJS[oid]; break; } }
      elementName = o ? o.name : '';
    }
    add(diagId, {
      diagId: diagId,
      diagramName: (DIAGMAP[diagId] || {}).name || '',
      elementId: elementId,
      elementName: elementName,
      severity: sev ? sev.value : 'befund',
      text: text,
      model: modelKey()
    });
    openForm(diagId);
  }

  function exportJson(diagId) {
    var arr = list(diagId);
    if (!arr.length) { alert('Keine Befunde vorhanden.'); return; }
    var diag = DIAGMAP[diagId] || {};
    var payload = {
      format: 'erm-qea-review',
      version: 1,
      model: modelKey(),
      erstellt: new Date().toISOString(),
      sicht: { id: diag.localId || diagId, name: diag.name || '', paket: diag.pkgPath || '', typ: diag.type || '' },
      befunde: arr
    };
    var name = 'Befunde_' + safeName(diag.name || 'Sicht') + '_' + dateStamp() + '.json';
    downloadText(name, JSON.stringify(payload, null, 2));
  }

  function exportQea(diagId) {
    var arr = list(diagId);
    if (!arr.length) { alert('Keine Befunde vorhanden.'); return; }
    if (typeof EDIT === 'undefined' || !EDIT.addIssueBatch) {
      alert('Der Schreiber ist nicht verfügbar. Bitte die Befunde als JSON exportieren.');
      return;
    }
    var diag = DIAGMAP[diagId] || {};
    EDIT.addIssueBatch({
      sicht: diag.name || ('Sicht ' + diagId),
      paket: 'Qualitätssicherung',
      befunde: arr.map(function (x) {
        return {
          severity: x.severity,
          text: x.text,
          elementId: x.elementId || '',
          elementName: x.elementName || '',
          ts: x.ts || ''
        };
      })
    });
    alert(arr.length + ' Befund(e) vorgemerkt.\n\nJetzt „Als neue .qea speichern“ wählen — ' +
      'die Originaldatei bleibt unverändert.');
    if (EDIT.openPanel) EDIT.openPanel();
  }

  return {
    list: list, add: add, remove: remove, idsFor: idsFor, count: count, all: all,
    panelHtml: panelHtml, openForm: openForm, submit: submit,
    exportJson: exportJson, exportQea: exportQea
  };
})();

/* Neuzeichnen der Befundliste nach Aenderungen */
function renderIssuePanel(diagId) {
  var old = document.getElementById('issue-panel-' + diagId);
  if (!old) return;
  var diag = DIAGMAP[diagId];
  if (!diag) return;
  var wrap = document.createElement('div');
  wrap.innerHTML = ISSUE.panelHtml(diag);
  var neu = wrap.firstChild;
  old.parentNode.replaceChild(neu, old);
}
