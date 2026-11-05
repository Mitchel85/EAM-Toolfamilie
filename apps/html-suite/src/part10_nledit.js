/* ============================================================================
   EAM AI Suite -- Teil 10: Natuerlichsprachliche Korrektur (geladene .qea)
   ----------------------------------------------------------------------------
   Der Nutzer beschreibt eine Aenderung in Worten. Daraus entsteht eine
   Vorschlagsliste; erst "In Änderungsliste vormerken" uebernimmt sie in den
   bestehenden Bearbeiten-Pfad (EDIT). Gespeichert wird weiterhin nur ueber
   "Als neue .qea speichern" -- das Original bleibt unberuehrt.

   Mit API-Schluessel formuliert ein Sprachmodell die Operationen. Ohne
   Schluessel (oder mit gesetztem Haken "ohne KI") arbeitet eine kleine,
   feste deutsche Befehlsgrammatik. Jedes Ziel wird gegen das geladene Modell
   aufgeloest; erfundene Namen werden abgelehnt.

   Es gibt KEINE zweite Schreibpipeline: EDIT.applyNlOps erzeugt dieselben
   Vormerkungen wie die Formulare.
   ============================================================================ */

var NL = (function () {
  var proposal = null;
  var busy = false;

  function el(id) { return document.getElementById(id); }
  function s0(v) { return v == null ? '' : String(v); }
  function esc(s) { return s0(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function status(msg, kind) {
    var s = el('nl-status');
    if (!s) return;
    s.textContent = msg || '';
    s.className = 'qa-status' + (kind ? ' nl-' + kind : '');
  }
  function norm(v) { return s0(v).trim().replace(/^["'„“”‚‘«»]+|["'„“”‚‘«»]+$/g, '').replace(/\s+/g, ' ').toLowerCase(); }
  function cleanRef(v) {
    var t = s0(v).trim().replace(/^["'„“”‚‘«»]+|["'„“”‚‘«»]+$/g, '');
    t = t.replace(/^(?:das|der|die|den)\s+(?:element|paket)\s+/i, '').replace(/^(?:element|paket)\s+/i, '');
    return t.replace(/[.,;:!?]+$/g, '').trim();
  }

  /* ---------- Inventar aus dem geladenen Modell ---------- */
  function inventoryText(limit) {
    limit = limit || 400;
    var keys = Object.keys(OBJS), lines = [], i, o, pkg, n = 0;
    var dirs = [];
    for (var pk in PKG) if (Object.prototype.hasOwnProperty.call(PKG, pk)) dirs.push(PKG[pk].path);
    dirs.sort();
    lines.push('Pakete (' + dirs.length + '): ' + dirs.slice(0, 80).join(', '));
    lines.push('Elemente (' + keys.length + '):');
    for (i = 0; i < keys.length && n < limit; i++) {
      o = OBJS[keys[i]];
      if (!o || o.type === 'Package') continue;
      pkg = o.pkgFull || o.pkg || '';
      lines.push('- ' + pkg + '::' + o.name + ' «' + (o.st || '') + '»' + (o.alias ? ' (Alias: ' + o.alias + ')' : ''));
      n++;
    }
    if (keys.length > limit) lines.push('- … ' + (keys.length - limit) + ' weitere Elemente (nicht gelistet)');
    if (CONS.length) {
      lines.push('Beziehungen (' + CONS.length + '), erste 80:');
      for (i = 0; i < CONS.length && i < 80; i++) {
        var a = OBJS[CONS[i].a], b = OBJS[CONS[i].b];
        lines.push('- ' + (a ? a.name : CONS[i].a) + ' -«' + (CONS[i].st || CONS[i].type || '') + '»→ ' + (b ? b.name : CONS[i].b));
      }
    }
    return lines.join('\n');
  }

  function findElements(name, pkg) {
    var hits = [], keys = Object.keys(OBJS), i, o;
    var wanted = norm(name);
    for (i = 0; i < keys.length; i++) {
      o = OBJS[keys[i]];
      if (!o || o.type === 'Package') continue;
      if (norm(o.name) !== wanted) continue;
      if (pkg) {
        var actual = norm(o.pkgFull || o.pkg || ''), wish = norm(pkg);
        if (actual !== wish && actual.slice(-wish.length - 1) !== '/' + wish) continue;
      }
      hits.push(o);
    }
    return hits;
  }

  function resolveElement(name, pkg) {
    var hits = findElements(name, pkg);
    if (hits.length === 1) return hits[0];
    if (hits.length > 1) {
      throw new Error('Element „' + name + '“ ist nicht eindeutig (' + hits.length + ' Treffer) — bitte Paket angeben.');
    }
    throw new Error('Kein Element „' + name + '“ im geladenen Modell gefunden.');
  }

  function resolveRef(ref) {
    var text = s0(ref).trim();
    var cut = text.lastIndexOf('::');
    if (cut >= 0) return resolveElement(text.slice(cut + 2), text.slice(0, cut));
    return resolveElement(text, '');
  }

  function findConnector(source, target, stereotype) {
    var s = source ? resolveRef(source) : null;
    var t = target ? resolveRef(target) : null;
    var hits = [];
    for (var i = 0; i < CONS.length; i++) {
      var c = CONS[i];
      if (s && String(c.a) !== String(s.id)) continue;
      if (t && String(c.b) !== String(t.id)) continue;
      if (stereotype && norm(c.st) !== norm(stereotype)) continue;
      hits.push(c);
    }
    if (hits.length === 1) return hits[0];
    if (!hits.length) throw new Error('Keine passende Beziehung gefunden.');
    throw new Error('Beziehung ist nicht eindeutig (' + hits.length + ' Treffer) — Stereotyp angeben.');
  }

  /* ---------- Deutsche Befehlsgrammatik (ohne KI) ---------- */
  function splitClauses(text) {
    var verbs = 'benenne|nenne|umbenennen|umbenenne|setze|ändere|aendere|ergänze|ergaenze|loesche|lösche|entferne|verbinde|verknüpfe|verknuepfe|trenne|loese|löse';
    var parts = text.split(/\s*;\s*/), out = [], i, chunks;
    for (i = 0; i < parts.length; i++) {
      chunks = parts[i].split(new RegExp('\\s+und\\s+(?=(?:' + verbs + ')\\b)', 'i'));
      for (var j = 0; j < chunks.length; j++) if (chunks[j].trim()) out.push(chunks[j].trim());
    }
    return out;
  }

  function parseClause(text) {
    text = s0(text).trim().replace(/[.!]+$/, '');
    text = text.replace(/[„“]/g, '"').replace(/[‚‘]/g, "'").replace(/[«»]/g, '"');
    text = text.replace(/^(?:bitte\s+|kannst\s+du\s+(?:bitte\s+)?)/i, '');
    if (/^(?:benenne|nenne|umbenennen|umbenenne)\b/i.test(text)) text = text.replace(/\s+um$/i, '');

    var m = text.match(/^(?:trenne|loese|löse|entferne)\s+(?:die\s+)?(?:beziehung|verbindung|kante)\s+(?:zwischen\s+)?(.+?)\s+(?:und|von)\s+(.+?)(?:\s+(?:mit|ueber|über)\s+(.+))?$/i);
    if (m) {
      return [{ op: 'delete_connector', source: cleanRef(m[1]), target: cleanRef(m[2]), stereotype: cleanRef(m[3] || '') }];
    }

    m = text.match(/^(?:verbinde|verknuepfe|verknüpfe)\s+(.+?)\s+mit\s+(.+?)(?:\s+(?:ueber|über|via|als)\s+(.+))?$/i);
    if (!m) m = text.match(/^(?:erstelle|fuege|füge)\s+(?:eine\s+)?(?:beziehung|verbindung|kante)\s+(?:von\s+)?(.+?)\s+(?:nach|zu|mit)\s+(.+?)(?:\s+(?:ueber|über|via|als)\s+(.+))?$/i);
    if (m) {
      return [{ op: 'add_connector', source: cleanRef(m[1]), target: cleanRef(m[2]), stereotype: cleanRef(m[3] || 'Dependency'), ea_type: 'Dependency' }];
    }

    var fields = [
      ['notiz|beschreibung', 'set_note'],
      ['status', 'set_status'],
      ['alias|kurzname', 'set_alias'],
      ['stereotyp(?:en)?', 'set_stereotype']
    ];
    for (var i = 0; i < fields.length; i++) {
      m = text.match(new RegExp('^(?:setze|ändere|aendere|ergänze|ergaenze|ueberschreibe|überschreibe)\\s+(?:die\\s+|den\\s+)?(?:' + fields[i][0] + ')\\s+(?:von|bei|für|fuer|des\\s+elements|der)\\s+(.+?)\\s+(?:auf|zu)\\s+(.+)$', 'i'));
      if (m) return [{ op: fields[i][1], name: cleanRef(m[1]), value: cleanRef(m[2]) }];
    }

    m = text.match(/^(?:benenne|umbenennen|umbenenne|nenne)\s+(?:das\s+)?(?:element\s+)?(.+?)\s+(?:in|zu)\s+(.+)$/i);
    if (m) return [{ op: 'set_name', name: cleanRef(m[1]), value: cleanRef(m[2]) }];

    m = text.match(/^(?:loesche|lösche|entferne)\s+(?:das\s+)?(?:element\s+)?(.+)$/i);
    if (m) return [{ op: 'delete_element', name: cleanRef(m[1]) }];

    throw new Error('Anweisung nicht verstanden: „' + text + '“');
  }

  function parseLocal(text) {
    var clauses = splitClauses(text), ops = [], i;
    for (i = 0; i < clauses.length; i++) ops = ops.concat(parseClause(clauses[i]));
    return ops;
  }

  /* ---------- Vorschlag pruefen und an das Modell binden ---------- */
  function normalizeOp(raw) {
    var map = {
      rename: 'set_name', renameElement: 'set_name', umbenennen: 'set_name', set_name: 'set_name',
      set_note: 'set_note', setNote: 'set_note', notiz: 'set_note',
      set_status: 'set_status', setStatus: 'set_status', status: 'set_status',
      set_alias: 'set_alias', setAlias: 'set_alias', alias: 'set_alias',
      set_stereotype: 'set_stereotype', setStereotype: 'set_stereotype', stereotype: 'set_stereotype',
      delete_element: 'delete_element', removeElement: 'delete_element', deleteElement: 'delete_element',
      add_connector: 'add_connector', addConnector: 'add_connector',
      delete_connector: 'delete_connector', removeConnector: 'delete_connector', deleteConnector: 'delete_connector'
    };
    var op = JSON.parse(JSON.stringify(raw || {}));
    var name = op.op || op.operation || '';
    op.op = map[name] || name;
    if (!op.op) throw new Error('Operation ohne „op“');
    if (op.op === 'set_name' && op.value == null) op.value = op.to != null ? op.to : op.new;
    if (['set_note', 'set_status', 'set_alias', 'set_stereotype'].indexOf(op.op) >= 0 && op.value == null) {
      op.value = op.to != null ? op.to : (op.text != null ? op.text : op.new);
    }
    if (op.op === 'add_connector' || op.op === 'delete_connector') {
      if (op.source == null) op.source = op.from || op.quelle || '';
      if (op.target == null) op.target = op.to || op.ziel || '';
    }
    return op;
  }

  function prepare(rawOps) {
    var ops = [], i, op, target, source, dest;
    for (i = 0; i < rawOps.length; i++) {
      op = normalizeOp(rawOps[i]);
      if (['set_name', 'set_note', 'set_status', 'set_alias', 'set_stereotype', 'delete_element'].indexOf(op.op) >= 0) {
        var ref = op.name || (op.target && op.target.name) || '';
        target = (ref.indexOf('::') >= 0 && !op.package) ? resolveRef(ref) : resolveElement(ref, op.package || (op.target && op.target.package) || '');
        if (['set_name', 'set_note', 'set_status', 'set_alias', 'set_stereotype'].indexOf(op.op) >= 0) {
          if (typeof op.value !== 'string') throw new Error('Operation „' + op.op + '“ ohne Textwert.');
          if (op.op === 'set_name' && !op.value.trim()) throw new Error('Neuer Name darf nicht leer sein.');
          if (op.op === 'set_name' && op.value === target.name) throw new Error('Element heißt bereits „' + target.name + '“.');
        }
        ops.push({
          op: op.op, name: target.name, package: target.pkgFull || target.pkg || '',
          value: op.value, oid: target.id,
          label: target.name
        });
      } else if (op.op === 'add_connector') {
        source = resolveRef(op.source);
        dest = resolveRef(op.target);
        if (String(source.id) === String(dest.id)) throw new Error('Quelle und Ziel sind dasselbe Element.');
        ops.push({
          op: 'add_connector', source_name: source.name, target_name: dest.name,
          source_oid: source.id, target_oid: dest.id,
          stereotype: op.stereotype || 'Dependency', ea_type: op.ea_type || 'Dependency',
          name: op.name || '', direction: op.direction || 'Source -> Destination'
        });
      } else if (op.op === 'delete_connector') {
        var c = findConnector(op.source || '', op.target || '', op.stereotype || '');
        ops.push({
          op: 'delete_connector', cid: c.id, stereotype: c.st || c.type || '',
          source_name: (OBJS[c.a] || {}).name || c.a, target_name: (OBJS[c.b] || {}).name || c.b
        });
      } else {
        throw new Error('Unbekannte Operation „' + op.op + '“');
      }
    }
    return ops;
  }

  function describe(op) {
    var q = function (v) { return '„' + esc(v) + '“'; };
    if (op.op === 'set_name') return 'Umbenennen: ' + q(op.name) + ' → ' + q(op.value);
    if (op.op === 'set_note') return 'Notiz ändern: ' + q(op.name) + ' → ' + q(op.value);
    if (op.op === 'set_status') return 'Status setzen: ' + q(op.name) + ' → ' + q(op.value);
    if (op.op === 'set_alias') return 'Alias setzen: ' + q(op.name) + ' → ' + q(op.value);
    if (op.op === 'set_stereotype') return 'Stereotyp setzen: ' + q(op.name) + ' → ' + q(op.value);
    if (op.op === 'delete_element') return 'LÖSCHEN: ' + q(op.name) + ' samt Beziehungen';
    if (op.op === 'add_connector') return 'Beziehung anlegen: ' + q(op.source_name) + ' → ' + q(op.target_name) + ' «' + esc(op.stereotype) + '»';
    if (op.op === 'delete_connector') return 'Beziehung löschen: ' + q(op.source_name) + ' → ' + q(op.target_name) + ' «' + esc(op.stereotype) + '»';
    return op.op;
  }

  function render() {
    var box = el('nl-preview'), acts = el('nl-actions');
    if (!box || !acts) return;
    if (!proposal || !proposal.ops.length) {
      box.hidden = true; acts.hidden = true; box.innerHTML = '';
      return;
    }
    var html = ['<div class="nl-result-head"><b>' + proposal.ops.length + ' ' + (proposal.ops.length === 1 ? 'Vorschlag' : 'Vorschläge') + '</b>' +
      '<span class="dim">' + esc(proposal.backend) + '</span></div>'];
    if (proposal.reply) html.push('<p class="nl-reply">' + esc(proposal.reply) + '</p>');
    html.push('<ol class="nl-ops">');
    for (var i = 0; i < proposal.ops.length; i++) {
      var danger = proposal.ops[i].op === 'delete_element' || proposal.ops[i].op === 'delete_connector';
      html.push('<li class="' + (danger ? 'danger' : '') + '">' + describe(proposal.ops[i]) +
        '<span class="dim"> · ' + esc(proposal.ops[i].package || '') + '</span></li>');
    }
    html.push('</ol>');
    if (proposal.warnings.length) {
      html.push('<div class="nl-warn">' + proposal.warnings.map(esc).join('<br>') + '</div>');
    }
    if (proposal.ops.some(function (op) { return op.op === 'delete_element' || op.op === 'delete_connector'; })) {
      html.push('<label class="nl-check" style="margin-top:7px;color:#B91C1C"><input type="checkbox" id="nl-confirm-del"> Löschvorgänge ausdrücklich bestätigen</label>');
    }
    html.push('<div class="dim nl-hint">Übernommen wird erst mit „In Änderungsliste vormerken“; gespeichert mit „Als neue .qea speichern“.</div>');
    box.innerHTML = html.join('');
    box.hidden = false;
    acts.hidden = false;
  }

  /* ---------- Sprachmodell ---------- */
  function systemPrompt() {
    return [
      'Du bist ein Assistent fuer Enterprise-Architekturmodelle.',
      'Der Nutzer will ein vorhandenes Modell in natuerlicher Sprache korrigieren.',
      'Du erfindest keine Elemente, Pakete oder Beziehungen. Du verwendest ausschliesslich Namen aus dem Inventar.',
      '',
      'Antworte NUR mit gueltigem JSON:',
      '{"reply":"kurze Antwort auf Deutsch","ops":[{...}]}',
      '',
      'Erlaubte Operationen:',
      '- set_name:        {"op":"set_name","package":"Paket/Pfad","name":"Alt","value":"Neu"}',
      '- set_note:        {"op":"set_note","package":"Paket/Pfad","name":"Element","value":"Neuer Text"}',
      '- set_status:      {"op":"set_status","package":"Paket/Pfad","name":"Element","value":"Proposed"}',
      '- set_alias:       {"op":"set_alias","package":"Paket/Pfad","name":"Element","value":"Kurzname"}',
      '- set_stereotype:  {"op":"set_stereotype","package":"Paket/Pfad","name":"Element","value":"Capability"}',
      '- delete_element:  {"op":"delete_element","package":"Paket/Pfad","name":"Element"}',
      '- add_connector:   {"op":"add_connector","source":"Paket/Pfad::Name","target":"Paket/Pfad::Name","stereotype":"Dependency"}',
      '- delete_connector:{"op":"delete_connector","source":"Paket/Pfad::Name","target":"Paket/Pfad::Name","stereotype":"Dependency"}',
      '',
      'Regeln:',
      '1. "package" ist der vollstaendige Paketpfad mit "/" als Trenner.',
      '2. Bei mehrdeutigen Namen den Paketpfad mitgeben.',
      '3. Löschen nur, wenn der Nutzer es ausdrücklich verlangt.',
      '4. Lieber eine leere ops-Liste und eine erklärende reply als eine Operation erfinden.',
      '5. Deutsch, kein Markdown.'
    ].join('\n');
  }

  function chatComplete(text) {
    var cfg = KI.cfg();
    if (!cfg.key) throw new Error('Kein API-Schlüssel hinterlegt — Haken „ohne KI“ verwenden oder Schlüssel im KI-Tab eintragen.');
    var url = s0(cfg.base).replace(/\/+$/, '') + '/chat/completions';
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg.key },
      body: JSON.stringify({
        model: cfg.model,
        messages: [
          { role: 'system', content: systemPrompt() },
          { role: 'user', content: 'INVENTAR DES MODELLS:\n' + inventoryText(400) },
          { role: 'user', content: 'ANWEISUNG DES NUTZERS:\n' + text }
        ],
        response_format: { type: 'json_object' },
        temperature: 0,
        stream: false
      })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error('API-Fehler ' + r.status + ': ' + ((j.error && j.error.message) || ''));
        if (!j.choices || !j.choices.length) throw new Error('Leere API-Antwort.');
        var content = j.choices[0].message && j.choices[0].message.content;
        if (!content) throw new Error('Leere KI-Antwort.');
        return content;
      });
    });
  }

  function parseAnswer(content) {
    var text = s0(content).trim();
    if (text.indexOf('```') === 0) text = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
    var obj = JSON.parse(text);
    if (!obj || typeof obj !== 'object') throw new Error('KI-Antwort ist kein JSON-Objekt.');
    var ops = obj.ops || obj.operationen || [];
    if (!Array.isArray(ops)) throw new Error('KI-Antwort: „ops“ ist keine Liste.');
    return { reply: obj.reply || '', ops: ops };
  }

  /* ---------- Ablauf ---------- */
  function propose() {
    if (busy) return;
    var input = el('nl-input'), text = input ? input.value.trim() : '';
    if (!text) { status('Bitte eine Anweisung eingeben.', 'bad'); return; }
    if (!OBJS || !Object.keys(OBJS).length) { status('Bitte zuerst eine .qea laden.', 'bad'); return; }
    var noKi = el('nl-no-ki') && el('nl-no-ki').checked;
    var cfg = KI.cfg();
    var useKi = !noKi && !!s0(cfg.key);
    busy = true;
    proposal = null;
    render();
    if (el('nl-propose')) el('nl-propose').disabled = true;
    status(useKi ? '⏳ KI formuliert den Vorschlag …' : '⏳ Vorschlag wird geprüft …');

    var work;
    if (useKi) {
      work = chatComplete(text).then(function (content) {
        var answer = parseAnswer(content);
        var prepared = prepare(answer.ops || []);
        if (!prepared.length) throw new Error(answer.reply || 'Die KI hat keine Operation geliefert.');
        return { ops: prepared, reply: answer.reply, backend: 'KI · ' + cfg.model, warnings: [] };
      });
    } else {
      work = new Promise(function (resolve) {
        var ops = prepare(parseLocal(text));
        resolve({ ops: ops, reply: '', backend: 'ohne KI (Befehlsgrammatik)', warnings: [] });
      });
    }

    work.then(function (result) {
      proposal = result;
      render();
      status('✓ Vorschlag geprüft — noch nichts geändert.', 'ok');
    }).catch(function (e) {
      proposal = null;
      render();
      status('⚠ ' + (e && e.message ? e.message : String(e)), 'bad');
    }).then(function () {
      busy = false;
      if (el('nl-propose')) el('nl-propose').disabled = false;
    });
  }

  function applyProposal() {
    if (!proposal || !proposal.ops.length) return;
    var destructive = proposal.ops.some(function (op) { return op.op === 'delete_element' || op.op === 'delete_connector'; });
    var confirmBox = el('nl-confirm-del');
    if (destructive && !(confirmBox && confirmBox.checked)) {
      status('⚠ Löschvorgänge zuerst ausdrücklich bestätigen.', 'bad');
      return;
    }
    var results = EDIT.applyNlOps(proposal.ops);
    var ok = results.filter(function (r) { return r.ok; }).length;
    var bad = results.length - ok;
    status('✓ ' + ok + ' Änderung(en) vorgemerkt' + (bad ? ' · ' + bad + ' abgelehnt' : '') + ' — jetzt „Als neue .qea speichern“.', bad ? 'bad' : 'ok');
    proposal = null;
    render();
    if (el('nl-input')) el('nl-input').value = '';
  }

  function reset() {
    proposal = null;
    render();
    status('');
  }

  return { propose: propose, apply: applyProposal, reset: reset, _parseLocal: parseLocal, _inventoryText: inventoryText };
})();
