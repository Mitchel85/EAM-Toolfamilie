/* ============================================================================
   Teil 5b: Befunde als Elemente «Issue» schreiben
   ----------------------------------------------------------------------------
   Wird von Teil 6 (ISSUE.exportQea) aufgerufen. Die Befunde werden als
   vorgemerkte Aenderung in die Warteschlange gelegt und beim Speichern in eine
   NEUE .qea geschrieben. Die geoeffnete Datei bleibt unveraendert.

   Ablage:
     Qualitaetssicherung/<Sichtname>/<Befund>
     Element  : Object_Type=Class, Stereotype=Issue
     Beziehung: Dependency «betrifft» -> betroffenes Element (falls vorhanden)
   ============================================================================ */

(function () {
  if (typeof EDIT === 'undefined' || !EDIT.q) return;

  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  /* Paket anlegen: t_package + Spiegel in t_object, verknuepft ueber ea_guid */
  function makePackage(db, name, parentId, note, guid, stamp, encNote, one, colNames) {
    var pcols = colNames(db, 't_package');
    var prow = {};
    for (var i = 0; i < pcols.length; i++) prow[pcols[i]] = null;
    prow.Name = name;
    prow.Parent_ID = parentId;
    prow.CreatedDate = stamp;
    prow.ModifiedDate = stamp;
    prow.Notes = note || '';
    prow.ea_guid = guid;
    if (has(prow, 'TPos')) prow.TPos = 0;
    if (has(prow, 'Version')) prow.Version = '1.0';
    if (has(prow, 'Protected')) prow.Protected = 0;
    if (has(prow, 'IsControlled')) prow.IsControlled = 0;
    if (has(prow, 'UseDTD')) prow.UseDTD = 0;
    if (has(prow, 'LogXML')) prow.LogXML = 0;
    if (has(prow, 'BatchSave')) prow.BatchSave = 0;
    if (has(prow, 'BatchLoad')) prow.BatchLoad = 0;
    var ic = [], ph = [], iv = [];
    for (var k in prow) if (has(prow, k)) { ic.push(k); ph.push('?'); iv.push(prow[k]); }
    db.run('INSERT INTO t_package (' + ic.join(',') + ') VALUES (' + ph.join(',') + ')', iv);

    var got = one(db, 'SELECT Package_ID FROM t_package WHERE ea_guid=?', [guid]);
    var pid = got ? got.Package_ID : null;

    var ocols = colNames(db, 't_object');
    var tmpl = one(db, 'SELECT * FROM t_object WHERE Object_Type=? LIMIT 1', ['Package']) || {};
    var orow = {};
    for (var j = 0; j < ocols.length; j++) orow[ocols[j]] = has(tmpl, ocols[j]) ? tmpl[ocols[j]] : null;
    orow.Object_Type = 'Package';
    orow.Name = name;
    orow.Note = note ? encNote(note) : null;
    orow.Package_ID = parentId;
    orow.ea_guid = guid;
    if (has(orow, 'Object_ID')) delete orow.Object_ID;
    if (has(orow, 'CreatedDate')) orow.CreatedDate = stamp;
    if (has(orow, 'ModifiedDate')) orow.ModifiedDate = stamp;
    var ic2 = [], ph2 = [], iv2 = [];
    for (var k2 in orow) if (has(orow, k2)) { ic2.push(k2); ph2.push('?'); iv2.push(orow[k2] === undefined ? null : orow[k2]); }
    db.run('INSERT INTO t_object (' + ic2.join(',') + ') VALUES (' + ph2.join(',') + ')', iv2);
    return pid;
  }

  /* Wird im Anwenden-Block von Teil 5 aufgerufen. */
  window.applyIssueBatch = function (db, ch, helpers) {
    var now = helpers.now, encNote = helpers.encNote, one = helpers.one, colNames = helpers.colNames;
    var newGuid = helpers.newGuid, stereoXrefSync = helpers.stereoXrefSync, shortLabel = helpers.shortLabel;

    var root = one(db, 'SELECT Package_ID FROM t_package WHERE Parent_ID=0 AND Name=? LIMIT 1', [ch.paket]);
    var rootId;
    if (root) rootId = root.Package_ID;
    else rootId = makePackage(db, ch.paket, 0,
      'Befunde aus der Qualitaetspruefung (ERM QEA Viewer).', newGuid(), now, encNote, one, colNames);

    var subId = makePackage(db, ch.sicht, rootId,
      'Befunde zur Sicht «' + ch.sicht + '».', newGuid(), now, encNote, one, colNames);

    var created = [];
    for (var i = 0; i < ch.befunde.length; i++) {
      var b = ch.befunde[i];
      var sev = b.severity === 'kritisch' ? 'Kritisch' : (b.severity === 'hinweis' ? 'Hinweis' : 'Befund');
      var name = '[' + sev + '] ' + (b.elementName ? b.elementName + ': ' : '') + shortLabel(b.text, 70);
      var ocols = colNames(db, 't_object');
      var tmpl = one(db, 'SELECT * FROM t_object WHERE Object_Type=? LIMIT 1', ['Class']) || {};
      var row = {};
      for (var c = 0; c < ocols.length; c++) row[ocols[c]] = has(tmpl, ocols[c]) ? tmpl[ocols[c]] : null;
      row.Object_Type = 'Class';
      row.Name = name;
      row.Stereotype = 'Issue';
      row.Note = encNote(b.text + (b.elementName ? '\n\nBetroffenes Element: ' + b.elementName : '') +
        '\nSicht: ' + ch.sicht + '\nAufgenommen: ' + (b.ts || now));
      row.Package_ID = subId;
      row.ea_guid = newGuid();
      row.Status = 'Proposed';
      if (has(row, 'Object_ID')) delete row.Object_ID;
      if (has(row, 'CreatedDate')) row.CreatedDate = now;
      if (has(row, 'ModifiedDate')) row.ModifiedDate = now;
      var ic = [], ph = [], iv = [];
      for (var k in row) if (has(row, k)) { ic.push(k); ph.push('?'); iv.push(row[k] === undefined ? null : row[k]); }
      db.run('INSERT INTO t_object (' + ic.join(',') + ') VALUES (' + ph.join(',') + ')', iv);
      stereoXrefSync(db, row.ea_guid, 'element property', 'Issue');

      var got = one(db, 'SELECT Object_ID FROM t_object WHERE ea_guid=?', [row.ea_guid]);
      created.push(got ? got.Object_ID : null);

      /* Beziehung zum betroffenen Element, wenn es lokal auffindbar ist */
      if (b.elementId) {
        var localId = null;
        var raw = String(b.elementId);
        if (raw.indexOf(':') >= 0) raw = raw.substring(raw.lastIndexOf(':') + 1);
        var num = parseInt(raw, 10);
        if (!isNaN(num)) {
          var t = one(db, 'SELECT Object_ID FROM t_object WHERE Object_ID=? LIMIT 1', [num]);
          if (t) localId = t.Object_ID;
        }
        if (!localId && b.elementName) {
          var tn = one(db, 'SELECT Object_ID FROM t_object WHERE Name=? LIMIT 1', [b.elementName]);
          if (tn) localId = tn.Object_ID;
        }
        if (localId && got) {
          var ccols = colNames(db, 't_connector');
          var ctmpl = one(db, 'SELECT * FROM t_connector WHERE Connector_Type=? LIMIT 1', ['Dependency']) ||
                      one(db, 'SELECT * FROM t_connector LIMIT 1') || {};
          var crow = {};
          for (var cc = 0; cc < ccols.length; cc++) crow[ccols[cc]] = has(ctmpl, ccols[cc]) ? ctmpl[ccols[cc]] : null;
          crow.Connector_Type = 'Dependency';
          crow.Start_Object_ID = got.Object_ID;
          crow.End_Object_ID = localId;
          crow.Name = 'betrifft';
          crow.Stereotype = null;
          crow.Direction = 'Source -> Destination';
          crow.ea_guid = newGuid();
          crow.DiagramID = 0;
          if (has(crow, 'Connector_ID')) delete crow.Connector_ID;
          var nulls = ['Top_Start_Label', 'Top_Mid_Label', 'Top_End_Label', 'Btm_Start_Label',
                       'Btm_Mid_Label', 'Btm_End_Label', 'PDATA1', 'PDATA2', 'PDATA3', 'PDATA4', 'PDATA5',
                       'StyleEx', 'StateFlags', 'ActionFlags', 'EventFlags'];
          for (var n = 0; n < nulls.length; n++) if (has(crow, nulls[n])) crow[nulls[n]] = null;
          var ic3 = [], ph3 = [], iv3 = [];
          for (var k3 in crow) if (has(crow, k3)) { ic3.push(k3); ph3.push('?'); iv3.push(crow[k3] === undefined ? null : crow[k3]); }
          db.run('INSERT INTO t_connector (' + ic3.join(',') + ') VALUES (' + ph3.join(',') + ')', iv3);
        }
      }
    }
    return created.length;
  };
})();
