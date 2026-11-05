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
