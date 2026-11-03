/* ============================================================================
   EAM Suite — Teil 7: BPMN-Darstellung fuer Prozesssichten
   ----------------------------------------------------------------------------
   Wird von Teil 6 benutzt, wenn eine Sicht Prozessinhalt enthaelt (Pool, Lane,
   Ereignis, Gateway, Aktivitaet) oder wenn der Betrachter BPMN erzwingt.

   Die Positionen kommen weiterhin aus t_diagramobjects. Geaendert wird nur die
   Form: Pools mit Kopfband, Lanes als Bahnen, Aufgaben gerundet, Ereignisse als
   Kreis (Start duenn, Ende dick, Zwischenereignis doppelt), Gateways als Raute,
   Pins als kleine Quadrate. Fluesse: Steuerfluss durchgezogen, Objekt- und
   Nachrichtenfluss gestrichelt mit offener Spitze.
   ============================================================================ */

var BPMN = (function () {

  var POOL_TAB = 20;

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
    var maxc = Math.max(4, Math.floor((w - 8) / (fs * 0.6)));
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
    var stroke = flagged ? '#B45309' : '#004471';
    var sw = flagged ? 2.4 : 1.4;
    var nm = String(rc.name || '').replace(/\r?\n/g, ' ').trim();
    var out = [];

    if (art === 'pool') {
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="' + h.toFixed(1) + '" fill="#FFFFFF" stroke="' + stroke + '" stroke-width="' + sw + '"/>');
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + POOL_TAB +
        '" height="' + h.toFixed(1) + '" fill="#EEF4F8" stroke="' + stroke + '" stroke-width="' + sw + '"/>');
      var cx = x + POOL_TAB / 2, cy = y + h / 2;
      out.push('<text x="' + cx.toFixed(1) + '" y="' + cy.toFixed(1) + '" transform="rotate(-90 ' +
        cx.toFixed(1) + ' ' + cy.toFixed(1) + ')" font-size="10" font-weight="700" fill="#004471" text-anchor="middle">' +
        esc(nm.length > 40 ? nm.substring(0, 38) + '…' : nm) + '</text>');
      return out.join('');
    }

    if (art === 'lane') {
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="' + h.toFixed(1) + '" fill="#FAFCFF" stroke="' + stroke + '" stroke-width="1.1"/>');
      var lab = textFit(nm, w, 8.5)[0] || '';
      out.push('<text x="' + (x + 6).toFixed(1) + '" y="' + (y + 12).toFixed(1) +
        '" font-size="8.5" font-weight="700" fill="#5A7285">' + esc(lab) + '</text>');
      return out.join('');
    }

    if (art === 'start' || art === 'ende' || art === 'zwischen') {
      var r = Math.max(6, Math.min(w, h) / 2 - 1);
      var ccx = x + w / 2, ccy = y + h / 2;
      var fw = (art === 'ende') ? 3.2 : 1.6;
      out.push('<circle cx="' + ccx.toFixed(1) + '" cy="' + ccy.toFixed(1) + '" r="' + r.toFixed(1) +
        '" fill="#FFFFFF" stroke="' + stroke + '" stroke-width="' + fw + '"/>');
      if (art === 'zwischen') {
        out.push('<circle cx="' + ccx.toFixed(1) + '" cy="' + ccy.toFixed(1) + '" r="' + Math.max(3, r - 3).toFixed(1) +
          '" fill="none" stroke="' + stroke + '" stroke-width="1.2"/>');
      }
      if (nm) {
        out.push('<text x="' + (x + w + 5).toFixed(1) + '" y="' + (ccy + 3).toFixed(1) +
          '" font-size="8.5" fill="#1A1A1A" text-anchor="start">' + esc(nm.length > 26 ? nm.substring(0, 24) + '…' : nm) + '</text>');
      }
      return out.join('');
    }

    if (art === 'gateway') {
      var gx = x + w / 2, gy = y + h / 2;
      out.push('<path d="M ' + gx.toFixed(1) + ' ' + y.toFixed(1) +
        ' L ' + (x + w).toFixed(1) + ' ' + gy.toFixed(1) +
        ' L ' + gx.toFixed(1) + ' ' + (y + h).toFixed(1) +
        ' L ' + x.toFixed(1) + ' ' + gy.toFixed(1) + ' z" fill="#FFFFFF" stroke="' + stroke +
        '" stroke-width="' + sw + '"/>');
      /* BPMN-Marker im Gateway: + fuer UND, X fuer ODER; ohne Marker = exklusiv. */
      var m = String(nm).toLowerCase();
      var marker = '';
      if (/\bund\b|^und$|and|parallel|\+/.test(m)) marker = '+';
      else if (/oder|xor|exklusiv/.test(m)) marker = 'X';
      if (marker) {
        out.push('<text x="' + gx.toFixed(1) + '" y="' + (gy + 4).toFixed(1) +
          '" font-size="11" font-weight="700" fill="#004471" text-anchor="middle">' + marker + '</text>');
      }
      if (nm && !marker) {
        out.push('<text x="' + (x + w + 5).toFixed(1) + '" y="' + (gy + 3).toFixed(1) +
          '" font-size="8.5" fill="#1A1A1A" text-anchor="start">' + esc(nm.length > 22 ? nm.substring(0, 20) + '…' : nm) + '</text>');
      }
      return out.join('');
    }

    if (/^actionpin$/i.test(rc.type || '')) {
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="' + h.toFixed(1) + '" fill="#FFFFFF" stroke="' + stroke + '" stroke-width="1"/>');
      return out.join('');
    }

    /* Aufgabe / Aktivitaet / sonstiges Element */
    var r2 = 10;
    out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) +
      '" height="' + h.toFixed(1) + '" rx="' + r2 + '" fill="#EAF2F8" stroke="' + stroke + '" stroke-width="' + sw + '"/>');
    var fs = (h < 30 || w < 90) ? 9 : 10.5;
    var lines = textFit(nm, w, fs);
    var ty = y + 6 + (h - 12) / 2 - (lines.length - 1) * (fs * 0.62);
    for (var i = 0; i < lines.length; i++) {
      out.push('<text x="' + (x + w / 2).toFixed(1) + '" y="' + (ty + i * fs * 1.2).toFixed(1) +
        '" font-size="' + fs + '" font-weight="600" fill="#1A1A1A" text-anchor="middle">' + esc(lines[i]) + '</text>');
    }
    if (flagged) {
      out.push('<circle cx="' + (x + w - 7).toFixed(1) + '" cy="' + (y + 7).toFixed(1) +
        '" r="4.5" fill="#B45309"/>');
    }
    return out.join('');
  }

  /* Strichbild und Spitze je Flussart. */
  function fluss(cn) {
    var s = ((cn.type || '') + ' ' + (cn.st || '')).toLowerCase();
    if (/messageflow|message/.test(s)) return { dash: '6 4', offen: true, breite: 1.2 };
    if (/objectflow|object/.test(s)) return { dash: '4 3', offen: true, breite: 1.2 };
    if (/informationflow|information/.test(s)) return { dash: '1 3', offen: true, breite: 1.1 };
    return { dash: '', offen: false, breite: 1.4 };
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
    shape: shape, fluss: fluss, beschriftung: beschriftung
  };
})();
