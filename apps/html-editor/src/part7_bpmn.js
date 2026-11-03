/* ============================================================================
   EAM Suite — Teil 7: BPMN-Darstellung fuer Prozesssichten
   ----------------------------------------------------------------------------
   Gestaltung nach dem Argon Design System (Creative Tim):
     Primaer #5e72e4 · Text #32325d · Ueberschrift #172b4d · gedaempft #8898aa
     Rahmen #e9ecef · Flaeche #f6f9fc · Schatten 0 4px 6px rgba(50,50,93,.11)

   Die Positionen kommen weiterhin aus t_diagramobjects. Geaendert wird nur die
   Form: Pools mit Kopfband, Lanes als Bahnen, Aufgaben gerundet, Ereignisse als
   Kreis (Start duenn, Ende dick, Zwischenereignis doppelt), Gateways als Raute,
   Pins als kleine Quadrate.
   ============================================================================ */

var BPMN = (function () {

  var POOL_TAB = 24;
  var C = {
    primary: '#5e72e4', heading: '#172b4d', body: '#32325d', muted: '#8898aa',
    border: '#e9ecef', soft: '#f6f9fc', warning: '#fb6340', white: '#ffffff',
    font: "'Open Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"
  };

  function stil(s) {
    var st = String(s || '').toLowerCase();
    if (/^(pool)$/.test(st)) return 'pool';
    if (/^(lane)$/.test(st)) return 'lane';
    if (/startevent|^initial$/.test(st)) return 'start';
    if (/endevent|final/.test(st)) return 'ende';
    if (/intermediateevent/.test(st)) return 'zwischen';
    if (/gateway|decision/.test(st)) return 'gateway';
    return '';
  }

  /* Erkennt Prozesssichten am Inhalt, nicht am Paketpfad. */
  function istProzess(diagId) {
    var objs = (typeof DIAGOBJ !== 'undefined' && DIAGOBJ[diagId]) ? DIAGOBJ[diagId] : [];
    var i, o;
    for (i = 0; i < objs.length; i++) {
      o = (typeof OBJS !== 'undefined') ? OBJS[objs[i].oid] : null;
      if (!o) continue;
      if (stil(o.st)) return true;
      if (/^(ActivityPartition|Decision|Event|ActionPin)$/i.test(o.type || '')) return true;
    }
    var links = (typeof DIAGLINK !== 'undefined' && DIAGLINK[diagId]) ? DIAGLINK[diagId] : [];
    for (i = 0; i < links.length; i++) {
      var cn = (typeof CONNMAP !== 'undefined') ? CONNMAP[String(links[i].cid)] : null;
      if (cn && /(ControlFlow|ObjectFlow|MessageFlow)/i.test((cn.type || '') + ' ' + (cn.st || ''))) return true;
    }
    return false;
  }

  /* auto | bpmn | uml — die Wahl des Betrachters hat Vorrang. */
  function modus(diagId) {
    var w = null;
    try { w = localStorage.getItem('diagmodus_' + diagId); } catch (e) { }
    if (w === 'bpmn' || w === 'uml') return w;
    return istProzess(diagId) ? 'bpmn' : 'uml';
  }

  function setzeModus(diagId, m) {
    try {
      if (m === 'auto') localStorage.removeItem('diagmodus_' + diagId);
      else localStorage.setItem('diagmodus_' + diagId, m);
    } catch (e) { }
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function textFit(nm, w, fs) {
    var maxc = Math.max(4, Math.floor((w - 12) / (fs * 0.56)));
    if (nm.length <= maxc) return [nm];
    var lines = [], rest = nm;
    while (rest.length && lines.length < 3) {
      if (rest.length <= maxc) { lines.push(rest); rest = ''; break; }
      var c = rest.lastIndexOf(' ', maxc);
      if (c < 4) c = maxc;
      lines.push(rest.substring(0, c));
      rest = rest.substring(c + 1);
    }
    if (rest.length) lines[lines.length - 1] = lines[lines.length - 1].substring(0, Math.max(3, maxc - 1)) + '…';
    return lines;
  }

  /* Liefert das fertige SVG fuer ein Element (inkl. Beschriftung). */
  function shape(rc, ox, oy, flagged) {
    var x = rc.x + ox, y = rc.y + oy, w = rc.w, h = rc.h;
    var art = stil(rc.st);
    var nm = String(rc.name || '').replace(/\r?\n/g, ' ').trim();
    var out = [];

    if (art === 'pool') {
      /* Karte statt Kasten: weisser Grund, weiches Kopfband, rotierter Name. */
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="' + h.toFixed(1) + '" rx="12" fill="' + C.white + '" stroke="' + C.border +
        '" stroke-width="1.4" filter="url(#agShadow)"/>');
      out.push('<path d="M ' + x.toFixed(1) + ' ' + (y + h - 13).toFixed(1) +
        ' v -' + (h - 25).toFixed(1) + ' a 12 12 0 0 1 12 -12 h ' + (POOL_TAB - 12).toFixed(1) +
        ' v ' + h.toFixed(1) + ' z" fill="' + C.soft + '"/>');
      out.push('<line x1="' + (x + POOL_TAB).toFixed(1) + '" y1="' + (y + 1).toFixed(1) +
        '" x2="' + (x + POOL_TAB).toFixed(1) + '" y2="' + (y + h - 1).toFixed(1) +
        '" stroke="' + C.border + '" stroke-width="1.2"/>');
      var cx = x + POOL_TAB / 2, cy = y + h / 2;
      out.push('<text x="' + cx.toFixed(1) + '" y="' + cy.toFixed(1) + '" transform="rotate(-90 ' +
        cx.toFixed(1) + ' ' + cy.toFixed(1) + ')" font-family="' + C.font + '" font-size="11" ' +
        'font-weight="700" fill="' + C.heading + '" letter-spacing="0.4" text-anchor="middle">' +
        esc(nm.length > 44 ? nm.substring(0, 42) + '…' : nm) + '</text>');
      return out.join('');
    }

    if (art === 'lane') {
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="' + h.toFixed(1) + '" fill="#fbfcfe" stroke="' + C.border + '" stroke-width="1"/>');
      var lab = textFit(nm, w, 9)[0] || '';
      out.push('<line x1="' + x.toFixed(1) + '" y1="' + y.toFixed(1) + '" x2="' + (x + w).toFixed(1) +
        '" y2="' + y.toFixed(1) + '" stroke="#dfe4ee" stroke-width="1.4"/>');
      out.push('<text x="' + (x + 10).toFixed(1) + '" y="' + (y + 15).toFixed(1) +
        '" font-family="' + C.font + '" font-size="9.5" font-weight="700" fill="' + C.heading +
        '" letter-spacing="0.5">' + esc(lab.toUpperCase()) + '</text>');
      return out.join('');
    }

    if (art === 'start' || art === 'ende' || art === 'zwischen') {
      var r = Math.max(6, Math.min(w, h) / 2 - 1);
      var ccx = x + w / 2, ccy = y + h / 2;
      var farbe = (art === 'ende') ? C.heading : C.primary;
      var fw = (art === 'ende') ? 3.6 : 2;
      out.push('<circle cx="' + ccx.toFixed(1) + '" cy="' + ccy.toFixed(1) + '" r="' + r.toFixed(1) +
        '" fill="' + C.white + '" stroke="' + farbe + '" stroke-width="' + fw + '"/>');
      if (art === 'zwischen') {
        out.push('<circle cx="' + ccx.toFixed(1) + '" cy="' + ccy.toFixed(1) + '" r="' + Math.max(3, r - 3.5).toFixed(1) +
          '" fill="none" stroke="' + farbe + '" stroke-width="1.4"/>');
      }
      if (nm) {
        out.push('<text x="' + (x + w + 7).toFixed(1) + '" y="' + (ccy + 3.5).toFixed(1) +
          '" font-family="' + C.font + '" font-size="9.5" font-weight="600" fill="' + C.body + '">' +
          esc(nm.length > 42 ? nm.substring(0, 40) + '…' : nm) + '</text>');
      }
      return out.join('');
    }

    if (art === 'gateway') {
      var gx = x + w / 2, gy = y + h / 2;
      out.push('<path d="M ' + gx.toFixed(1) + ' ' + y.toFixed(1) +
        ' L ' + (x + w).toFixed(1) + ' ' + gy.toFixed(1) +
        ' L ' + gx.toFixed(1) + ' ' + (y + h).toFixed(1) +
        ' L ' + x.toFixed(1) + ' ' + gy.toFixed(1) + ' z" fill="' + C.white +
        '" stroke="' + C.primary + '" stroke-width="1.8"/>');
      var m = String(nm).toLowerCase(), marker = '';
      if (/\bund\b|and|parallel/.test(m)) marker = '+';
      else if (/oder|xor|exklusiv/.test(m)) marker = 'X';
      if (marker) {
        out.push('<text x="' + gx.toFixed(1) + '" y="' + (gy + 4.5).toFixed(1) +
          '" font-family="' + C.font + '" font-size="12" font-weight="700" fill="' + C.primary +
          '" text-anchor="middle">' + marker + '</text>');
      } else if (nm) {
        out.push('<text x="' + (x + w + 7).toFixed(1) + '" y="' + (gy + 3.5).toFixed(1) +
          '" font-family="' + C.font + '" font-size="9.5" font-weight="600" fill="' + C.body + '">' +
          esc(nm.length > 32 ? nm.substring(0, 30) + '…' : nm) + '</text>');
      }
      return out.join('');
    }

    if (/^actionpin$/i.test(rc.type || '')) {
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="' + h.toFixed(1) + '" rx="2" fill="' + C.white + '" stroke="' + C.muted + '" stroke-width="1"/>');
      return out.join('');
    }

    /* Aufgabe */
    out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
      '" height="' + h.toFixed(1) + '" rx="10" fill="' + C.white + '" stroke="' +
      (flagged ? C.warning : '#dfe4ee') + '" stroke-width="' + (flagged ? 2 : 1.3) +
      '" filter="url(#agShadow)"/>');
    var fs = (h < 30 || w < 90) ? 9 : 10.5;
    /* Laengstes Wort bestimmt die Schriftgroesse: lieber kleiner setzen als
       mitten im Wort abschneiden. */
    var woerter = nm.split(/\s+/), laengstes = 1;
    for (var wi = 0; wi < woerter.length; wi++) laengstes = Math.max(laengstes, woerter[wi].length);
    var passt = (w - 12) / (laengstes * 0.56);
    if (passt < fs) fs = Math.max(7.5, passt);
    var lines = textFit(nm, w, fs);
    var ty = y + 6 + (h - 12) / 2 - (lines.length - 1) * (fs * 0.6);
    for (var i = 0; i < lines.length; i++) {
      out.push('<text x="' + (x + w / 2).toFixed(1) + '" y="' + (ty + i * fs * 1.25).toFixed(1) +
        '" font-family="' + C.font + '" font-size="' + fs + '" font-weight="600" fill="' + C.body +
        '" text-anchor="middle">' + esc(lines[i]) + '</text>');
    }
    if (flagged) {
      out.push('<circle cx="' + (x + w - 8).toFixed(1) + '" cy="' + (y + 8).toFixed(1) +
        '" r="5" fill="' + C.warning + '"/>');
    }
    return out.join('');
  }

  /* Strichbild, Farbe und Spitze je Flussart. */
  function fluss(cn) {
    var s = ((cn.type || '') + ' ' + (cn.st || '')).toLowerCase();
    if (/messageflow|message/.test(s)) return { dash: '6 4', offen: true, breite: 1.5, farbe: C.primary };
    if (/objectflow|object/.test(s)) return { dash: '5 4', offen: true, breite: 1.5, farbe: C.warning };
    if (/informationflow|information/.test(s)) return { dash: '2 4', offen: true, breite: 1.3, farbe: '#a7b1c2' };
    return { dash: '', offen: false, breite: 1.6, farbe: C.muted };
  }

  function beschriftung(cn) {
    /* In Prozesssichten traegt der Name die Bedeutung, nicht der Stereotyp. */
    var n = String(cn.name || '').trim();
    if (!n) return '';
    if (/flow$/i.test(n)) return '';
    return n;
  }

  return {
    istProzess: istProzess, modus: modus, setzeModus: setzeModus,
    shape: shape, fluss: fluss, beschriftung: beschriftung, farben: C
  };
})();
