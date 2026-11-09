/* BPMN Studio — offline, ohne Netz. Editor auf Basis von bpmn-js (MIT). */
(function () {
  'use strict';

  var REGELN = (window.BPMN_REGELN && window.BPMN_REGELN.pruefregeln) || [];
  var REGEL_MAP = {};
  REGELN.forEach(function (r) { REGEL_MAP[r.id] = r; });

  var AUFGABEN = {
    'bpmn:Task': 1, 'bpmn:UserTask': 1, 'bpmn:ServiceTask': 1, 'bpmn:SendTask': 1,
    'bpmn:ReceiveTask': 1, 'bpmn:ScriptTask': 1, 'bpmn:ManualTask': 1, 'bpmn:BusinessRuleTask': 1
  };
  var GATEWAYS = {
    'bpmn:ExclusiveGateway': 1, 'bpmn:ParallelGateway': 1, 'bpmn:InclusiveGateway': 1,
    'bpmn:EventBasedGateway': 1, 'bpmn:ComplexGateway': 1
  };
  var SEVERITY = { fehler: 0, warnung: 1, hinweis: 2 };

  var LEER_XML = '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" ' +
    'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" ' +
    'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" ' +
    'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" ' +
    'id="Definitions_1" targetNamespace="https://eam-platform.local/bpmn">\n' +
    '  <bpmn:collaboration id="Collaboration_1"><bpmn:participant id="Participant_1" name="Neuer Prozess" processRef="Process_1" /></bpmn:collaboration>\n' +
    '  <bpmn:process id="Process_1" name="Neuer Prozess" isExecutable="false">\n' +
    '    <bpmn:laneSet id="LaneSet_1"><bpmn:lane id="Lane_1" name="Bearbeitung" /></bpmn:laneSet>\n' +
    '  </bpmn:process>\n' +
    '  <bpmndi:BPMNDiagram id="BPMNDiagram_1"><bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Collaboration_1">\n' +
    '    <bpmndi:BPMNShape id="Participant_1_di" bpmnElement="Participant_1" isHorizontal="true"><dc:Bounds x="40" y="40" width="900" height="180" /></bpmndi:BPMNShape>\n' +
    '    <bpmndi:BPMNShape id="Lane_1_di" bpmnElement="Lane_1" isHorizontal="true"><dc:Bounds x="40" y="40" width="900" height="180" /></bpmndi:BPMNShape>\n' +
    '  </bpmndi:BPMNPlane></bpmndi:BPMNDiagram>\n' +
    '</bpmn:definitions>';

  var modeler = null;
  var befunde = [];
  var protokoll = [];
  var naechsteId = 1;

  function $(id) { return document.getElementById(id); }
  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
  }
  function id(praefix) { return praefix + '_' + (naechsteId++); }
  function alle() { return modeler.get('elementRegistry').getAll(); }
  function istAufgabe(el) { return !!(el && AUFGABEN[el.type]); }
  function istGateway(el) { return !!(el && GATEWAYS[el.type]); }
  function istStart(el) { return !!(el && el.type === 'bpmn:StartEvent'); }
  function istEnde(el) { return !!(el && el.type === 'bpmn:EndEvent'); }
  function istEreignis(el) { return !!(el && /Event$/.test(el.type)); }
  function name(el) { return (el && el.businessObject && el.businessObject.name) || ''; }
  function seq(el) {
    return (el && el.outgoing ? el.outgoing : []).filter(function (f) { return f.type === 'bpmn:SequenceFlow'; });
  }
  function eingehend(el) {
    return (el && el.incoming ? el.incoming : []).filter(function (f) { return f.type === 'bpmn:SequenceFlow'; });
  }
  function laneVon(el) {
    var p = el && el.parent;
    while (p) { if (p.type === 'bpmn:Lane') return p; p = p.parent; }
    return null;
  }
  function participantVon(el) {
    var p = el && el.parent;
    while (p) { if (p.type === 'bpmn:Participant') return p; p = p.parent; }
    return null;
  }

  function meta(regel) {
    return REGEL_MAP[regel] || { schwere: 'warnung', titel: regel, konvention: '' };
  }
  function befund(regel, objekt, objektName, hinweis) {
    var m = meta(regel);
    return {
      regel: regel,
      schwere: m.schwere || 'warnung',
      titel: m.titel || regel,
      konvention: m.konvention || '',
      objekt: objekt,
      name: objektName || objekt,
      hinweis: hinweis
    };
  }

  function ausgabe(text, titel) {
    $('meldung-titel').textContent = titel || 'Hinweis';
    $('meldung-text').textContent = text;
    var dialog = $('meldung');
    if (dialog.showModal) dialog.showModal();
  }

  function herunterladen(dateiname, blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = dateiname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  function dateiname(art) {
    var process = alle().filter(function (el) { return el.type === 'bpmn:Process'; });
    var basis = 'prozess';
    var participants = alle().filter(function (el) { return el.type === 'bpmn:Participant'; });
    if (participants.length && name(participants[0])) {
      basis = name(participants[0]).toLowerCase().replace(/[^a-z0-9äöüß]+/g, '-').replace(/^-|-$/g, '') || 'prozess';
    }
    return basis + '.' + art;
  }

  // ------------------------------------------------------------------
  // Laden / Speichern / Export
  // ------------------------------------------------------------------

  function importieren(xml) {
    return modeler.importXML(xml).then(function () {
      var canvas = modeler.get('canvas');
      canvas.zoom('fit-viewport');
      $('hinweis-start').hidden = true;
      befunde = [];
      zeichneBefunde();
      protokoll = [];
      zeichneProtokoll();
    });
  }

  function istPdf(datei) {
    return /\.pdf$/i.test(datei.name || '') || datei.type === 'application/pdf';
  }

  // pdf.js bringt seinen Worker mit; er steckt als Textblock in der Datei und
  // wird erst beim ersten Bedarf als Blob-URL bereitgestellt. So bleibt das
  // Studio eine einzige Datei ohne externen Ladevorgang.
  function pdfVorbereiten() {
    if (!window.pdfjsLib) return false;
    if (!window.pdfjsLib.GlobalWorkerOptions.workerSrc) {
      var quelle = document.getElementById('pdf-worker-quelle');
      if (quelle && quelle.textContent) {
        var blob = new Blob([quelle.textContent], { type: 'text/javascript' });
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = URL.createObjectURL(blob);
      }
    }
    return true;
  }

  function pdfLesen(datei) {
    return new Promise(function (fertig, scheitern) {
      if (!pdfVorbereiten()) {
        scheitern(new Error('PDF-Komponente fehlt in dieser Datei'));
        return;
      }
      datei.arrayBuffer().then(function (puffer) {
        return window.pdfjsLib.getDocument({ data: new Uint8Array(puffer) }).promise;
      }).then(function (dokument) {
        var seiten = [];
        var kette = Promise.resolve();
        var nummern = [];
        for (var n = 1; n <= dokument.numPages; n++) nummern.push(n);
        nummern.forEach(function (nummer) {
          kette = kette.then(function () {
            return dokument.getPage(nummer).then(function (seite) {
              return seite.getTextContent().then(function (inhalt) {
                var zeilen = [];
                var zeile = '';
                inhalt.items.forEach(function (stueck) {
                  if (!stueck || typeof stueck.str !== 'string') return;
                  zeile += stueck.str;
                  if (stueck.hasEOL) { zeilen.push(zeile); zeile = ''; }
                });
                if (zeile.trim()) zeilen.push(zeile);
                seiten.push(zeilen.join('\n'));
              });
            });
          });
        });
        return kette.then(function () { return { seiten: seiten, anzahl: dokument.numPages }; });
      }).then(fertig).catch(scheitern);
    });
  }

  function textLaden(datei) {
    if (!datei) return;
    if (istPdf(datei)) {
      pdfLesen(datei).then(function (ergebnis) {
        var text = ergebnis.seiten.join('\n\n')
          .replace(/[ \t]+\n/g, '\n')
          .replace(/\n{3,}/g, '\n\n')
          .trim();
        if (!text) {
          ausgabe('Die PDF enthält keinen extrahierbaren Text — vermutlich ein Scan ohne Textebene.', 'PDF ohne Text');
          return;
        }
        $('text-eingabe').value = text;
        if (!$('text-name').value.trim()) $('text-name').value = (datei.name || '').replace(/\.pdf$/i, '');
        var warnung = $('text-warnung');
        warnung.hidden = false;
        warnung.className = 'warnung';
        warnung.textContent = 'PDF gelesen: ' + ergebnis.anzahl + ' Seite(n), ' + text.length
          + ' Zeichen. Text prüfen, dann „Extrahieren“ — oder den Abschnitt über den Auftrag eingrenzen.';
        textDialogOeffnen();
      }).catch(function (fehler) {
        ausgabe('Die PDF konnte nicht gelesen werden: ' + fehler.message, 'PDF-Laden fehlgeschlagen');
      });
      return;
    }
    var leser = new FileReader();
    leser.onload = function () {
      importieren(String(leser.result)).catch(function (fehler) {
        ausgabe('Die Datei ist kein lesbares BPMN 2.0 XML: ' + fehler.message, 'Laden fehlgeschlagen');
      });
    };
    leser.readAsText(datei, 'utf-8');
  }

  function speichern() {
    modeler.saveXML({ format: true }).then(function (ergebnis) {
      herunterladen(dateiname('bpmn'), new Blob([ergebnis.xml], { type: 'application/xml' }));
    }).catch(function (fehler) { ausgabe('Speichern fehlgeschlagen: ' + fehler.message); });
  }

  function exportSvg() {
    modeler.saveSVG().then(function (ergebnis) {
      herunterladen(dateiname('svg'), new Blob([ergebnis.svg], { type: 'image/svg+xml' }));
    }).catch(function (fehler) { ausgabe('SVG-Export fehlgeschlagen: ' + fehler.message); });
  }

  function exportPng() {
    modeler.saveSVG().then(function (ergebnis) {
      var svg = ergebnis.svg;
      var blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var bild = new Image();
      bild.onload = function () {
        var skala = 2;
        var flaeche = document.createElement('canvas');
        flaeche.width = Math.max(1, Math.ceil(bild.width * skala));
        flaeche.height = Math.max(1, Math.ceil(bild.height * skala));
        var stift = flaeche.getContext('2d');
        stift.fillStyle = '#ffffff';
        stift.fillRect(0, 0, flaeche.width, flaeche.height);
        stift.setTransform(skala, 0, 0, skala, 0, 0);
        stift.drawImage(bild, 0, 0);
        URL.revokeObjectURL(url);
        flaeche.toBlob(function (png) {
          if (png) herunterladen(dateiname('png'), png);
          else ausgabe('PNG konnte nicht erzeugt werden.');
        }, 'image/png');
      };
      bild.onerror = function () {
        URL.revokeObjectURL(url);
        ausgabe('PNG-Export fehlgeschlagen: SVG nicht lesbar.');
      };
      bild.src = url;
    }).catch(function (fehler) { ausgabe('PNG-Export fehlgeschlagen: ' + fehler.message); });
  }

  // ------------------------------------------------------------------
  // ADMBw-Prüfung
  // ------------------------------------------------------------------

  function datenbezug(el) {
    var kanten = alle().filter(function (k) { return k.type === 'bpmn:Association'; });
    var flussIds = {};
    eingehend(el).concat(seq(el)).forEach(function (f) { flussIds[f.id] = 1; });
    return kanten.some(function (k) {
      var b = k.businessObject;
      var quelle = b.sourceRef && b.sourceRef.id;
      var ziel = b.targetRef && b.targetRef.id;
      var einer = quelle === el.id || ziel === el.id || flussIds[quelle] || flussIds[ziel];
      if (!einer) return false;
      var anderer = quelle === el.id || flussIds[quelle] ? b.targetRef : b.sourceRef;
      return !!(anderer && /^bpmn:(DataObject|DataObjectReference|DataStoreReference)$/.test(anderer.$type));
    });
  }

  function vorgaengerGateway(el) {
    var gesehen = {};
    var rand = [el];
    while (rand.length) {
      var naechste = [];
      for (var i = 0; i < rand.length; i++) {
        var knoten = rand[i];
        var ein = eingehend(knoten);
        for (var j = 0; j < ein.length; j++) {
          var quelle = ein[j].source;
          if (!quelle || gesehen[quelle.id]) continue;
          gesehen[quelle.id] = 1;
          if (istGateway(quelle) && seq(quelle).length > 1) return quelle;
          naechste.push(quelle);
        }
      }
      rand = naechste;
    }
    return null;
  }

  function pruefe() {
    var liste = [];
    var alleElemente = alle();
    var participants = alleElemente.filter(function (el) { return el.type === 'bpmn:Participant'; });
    var lanes = alleElemente.filter(function (el) { return el.type === 'bpmn:Lane'; });
    var aufgaben = alleElemente.filter(istAufgabe);
    var startEvents = alleElemente.filter(istStart);
    var endEvents = alleElemente.filter(istEnde);

    if (!participants.length) {
      liste.push(befund('BPMN-L4-01', 'Definitions_1', 'Modell',
        'Keine Kollaboration mit Pool — L4-MK08 verlangt ein BPMN-Kollaborationsdiagramm.'));
    }
    participants.forEach(function (p) {
      if (!p.businessObject.processRef) {
        liste.push(befund('BPMN-L4-01', p.id, name(p) || p.id, 'Pool zeigt auf keinen Prozess.'));
      }
      if (!name(p).trim()) {
        liste.push(befund('BPMN-L4-02', p.id, p.id, 'Pool ohne Namen — L4-MK09 verlangt Benennung.'));
      }
    });
    lanes.forEach(function (l) {
      if (!name(l).trim()) {
        liste.push(befund('BPMN-L4-02', l.id, l.id, 'Lane ohne Namen — L4-MK09 verlangt Benennung nach dem Aufgabenträger.'));
      }
    });

    if (!startEvents.length) {
      liste.push(befund('BPMN-L4-10', 'Process_1', 'Prozess', 'Prozess ohne Startereignis.'));
    }
    if (!endEvents.length) {
      liste.push(befund('BPMN-L4-10', 'Process_1', 'Prozess', 'Prozess ohne Endereignis.'));
    }

    aufgaben.forEach(function (t) {
      var n = name(t).trim();
      if (n.length < 3 || /^(aktion|task|aufgabe)\s/i.test(n)) {
        liste.push(befund('BPMN-L4-06', t.id, n || t.id, 'Aktion ohne aussagekräftigen Namen (L4-MK14).'));
      }
      var ein = eingehend(t);
      var aus = seq(t);
      if ((ein.length > 1 || aus.length > 1)) {
        liste.push(befund('BPMN-L4-08', t.id, n || t.id,
          'Verzweigung/Zusammenführung an einer Aktion (' + ein.length + ' ein, ' + aus.length + ' aus) — zulässig nur an Gateways.'));
      }
      if ((ein.length && !datenbezug(t)) || (aus.length && !datenbezug(t))) {
        liste.push(befund('BPMN-L4-11', t.id, n || t.id,
          'Kein Conveyed Item an der Aktion bzw. ihren Sequenzflüssen (L4-MK17).'));
      }
    });

    if (lanes.length) {
      aufgaben.concat(startEvents, endEvents,
        alleElemente.filter(istGateway)).forEach(function (el) {
          if (!laneVon(el)) {
            liste.push(befund('BPMN-L4-04', el.id, name(el) || el.id,
              'Knoten liegt in keiner Lane (L4-MK12).'));
          }
        });
    }

    alleElemente.filter(istGateway).forEach(function (g) {
      if (eingehend(g).length > 1) {
        var quelle = vorgaengerGateway(g);
        if (quelle && quelle.type !== g.type) {
          liste.push(befund('BPMN-L4-09', g.id, name(g) || g.id,
            'Zusammenführung ist ' + g.type + ', Verzweigung war ' + quelle.type + ' (L4-MK15).'));
        }
      }
    });

    alleElemente.filter(function (el) { return el.type === 'bpmn:SequenceFlow'; }).forEach(function (f) {
      var b = f.businessObject;
      if (b.conditionExpression && f.source && istAufgabe(f.source)) {
        liste.push(befund('BPMN-L4-12', f.id, name(f) || f.id,
          'Bedingter Fluss geht von einer Aktion aus — Vorbedingung als Zwischenereignis modellieren (L4-MK18).'));
      }
    });

    alleElemente.filter(function (el) { return el.type === 'bpmn:MessageFlow'; }).forEach(function (f) {
      var q = f.source && participantVon(f.source);
      var z = f.target && participantVon(f.target);
      if (q && z && q.id === z.id) {
        liste.push(befund('BPMN-L4-13', f.id, name(f) || f.id,
          'Nachrichtenfluss innerhalb eines Pools — L4-MK20 verlangt Austausch zwischen Pools.'));
      }
      var b = f.businessObject;
      var hatDaten = alle().some(function (k) {
        if (k.type !== 'bpmn:Association') return false;
        var kb = k.businessObject;
        var beteiligt = (kb.sourceRef && kb.sourceRef.id === f.id) || (kb.targetRef && kb.targetRef.id === f.id);
        if (!beteiligt) return false;
        var anderer = kb.sourceRef && kb.sourceRef.id === f.id ? kb.targetRef : kb.sourceRef;
        return !!(anderer && /^bpmn:(DataObject|DataObjectReference)$/.test(anderer.$type));
      });
      if (!hatDaten) {
        liste.push(befund('BPMN-L4-13', f.id, name(f) || f.id,
          'Nachrichtenfluss ohne Conveyed Item (L4-MK17/L4-MK20).'));
      }
    });

    var gesehen = {};
    liste = liste.filter(function (b) {
      var schluessel = b.regel + '|' + b.objekt + '|' + b.hinweis;
      if (gesehen[schluessel]) return false;
      gesehen[schluessel] = 1;
      return true;
    });
    liste.sort(function (a, b) {
      var s = (SEVERITY[a.schwere] || 9) - (SEVERITY[b.schwere] || 9);
      return s !== 0 ? s : (a.regel + a.objekt).localeCompare(b.regel + b.objekt);
    });
    befunde = liste;
    zeichneBefunde();
    return liste;
  }

  function zeichneBefunde() {
    var zaehler = { fehler: 0, warnung: 0, hinweis: 0 };
    befunde.forEach(function (b) { zaehler[b.schwere] = (zaehler[b.schwere] || 0) + 1; });
    $('zahl-fehler').textContent = zaehler.fehler;
    $('zahl-warnung').textContent = zaehler.warnung;
    $('zahl-hinweis').textContent = zaehler.hinweis;

    var liste = $('befunde');
    liste.innerHTML = '';
    befunde.forEach(function (b) {
      var li = document.createElement('li');
      li.className = 'befund ' + b.schwere;
      li.innerHTML =
        '<div class="kopfzeile"><span class="titel">' + esc(b.titel) + '</span>' +
        '<span class="regel">' + esc(b.regel) + (b.konvention ? ' · ' + esc(b.konvention) : '') + '</span></div>' +
        '<div class="hinweis">' + esc(b.hinweis) + '</div>' +
        '<div class="objekt">' + esc(b.objekt) + ' · ' + esc(b.name) + '</div>';
      li.addEventListener('click', function () {
        var el = modeler.get('elementRegistry').get(b.objekt);
        if (!el) return;
        modeler.get('selection').select(el);
        modeler.get('canvas').scrollToElement(el);
      });
      liste.appendChild(li);
    });
    $('befunde-leer').hidden = befunde.length > 0;
  }

  function zeichneProtokoll() {
    var liste = $('protokoll');
    liste.innerHTML = '';
    protokoll.forEach(function (text) {
      var li = document.createElement('li');
      li.textContent = text;
      liste.appendChild(li);
    });
    $('protokoll-leer').hidden = protokoll.length > 0;
  }

  function protokolliere(text) {
    protokoll.push(text);
  }

  // ------------------------------------------------------------------
  // "ADMBw-konform machen" — nur was mechanisch sicher ist
  // ------------------------------------------------------------------

  function konformMachen() {
    var modeling = modeler.get('modeling');
    var factory = modeler.get('elementFactory');
    var registry = modeler.get('elementRegistry');
    var geaendert = 0;
    protokoll = [];

    var aufgaben = alle().filter(istAufgabe);
    aufgaben.forEach(function (t) {
      var n = name(t).trim();
      if (!n || n.length < 3) {
        modeling.updateProperties(t, { name: 'Aktion (benennen)' });
        protokolliere('BPMN-L4-06: ' + t.id + ' benannt (Platzhalter)');
        geaendert++;
      }
    });

    // Fehlende Start-/Endereignisse je Prozess ergänzen.
    var processe = {};
    alle().forEach(function (el) {
      var p = el.businessObject && el.businessObject.$parent;
      while (p && p.$type !== 'bpmn:Process') p = p.$parent;
      if (p) processe[p.id] = p;
    });
    if (!Object.keys(processe).length && alle().some(function (el) { return el.type === 'bpmn:Process'; })) {
      alle().forEach(function (el) { if (el.type === 'bpmn:Process') processe[el.id] = el.businessObject; });
    }

    var startEvents = alle().filter(istStart);
    var endEvents = alle().filter(istEnde);
    if (!startEvents.length && aufgaben.length) {
      var erste = aufgaben.filter(function (t) { return eingehend(t).length === 0; })[0] || aufgaben[0];
      var parent = erste.parent;
      var start = factory.createShape({ type: 'bpmn:StartEvent' });
      modeling.createShape(start, { x: Math.max(80, erste.x - 120), y: erste.y + 22 }, parent);
      try { modeling.connect(start, erste); } catch (e) { /* Verbindung bleibt offen */ }
      protokolliere('BPMN-L4-10: Startereignis ergänzt und mit ' + (name(erste) || erste.id) + ' verbunden');
      geaendert++;
    }
    if (!endEvents.length && aufgaben.length) {
      var letzte = aufgaben.filter(function (t) { return seq(t).length === 0; }).slice(-1)[0] || aufgaben[aufgaben.length - 1];
      var parentEnde = letzte.parent;
      var ende = factory.createShape({ type: 'bpmn:EndEvent' });
      modeling.createShape(ende, { x: letzte.x + letzte.width + 80, y: letzte.y + 22 }, parentEnde);
      try { modeling.connect(letzte, ende); } catch (e) { /* Verbindung bleibt offen */ }
      protokolliere('BPMN-L4-10: Endereignis ergänzt und mit ' + (name(letzte) || letzte.id) + ' verbunden');
      geaendert++;
    }

    // Mehr als ein Ausgang an einer Aktion: Gateway dazwischen.
    aufgaben.forEach(function (t) {
      var aus = seq(t);
      if (aus.length < 2) return;
      var parent = t.parent;
      var gateway = factory.createShape({ type: 'bpmn:ExclusiveGateway' });
      modeling.createShape(gateway, { x: t.x + t.width + 50, y: t.y + 12 }, parent);
      var verschoben = 0;
      aus.slice().forEach(function (f) {
        try { modeling.reconnectStart(f, gateway); verschoben++; } catch (e) { /* Kante bleibt */ }
      });
      try { modeling.connect(t, gateway); } catch (e) { /* Kante bleibt */ }
      protokolliere('BPMN-L4-08: Gateway vor ' + (name(t) || t.id) + ' gesetzt (' + verschoben + ' Kanten umgehängt)');
      if (verschoben) geaendert++;
    });

    // Mehr als ein Eingang an einer Aktion: Zusammenführung davor.
    aufgaben.forEach(function (t) {
      var ein = eingehend(t);
      if (ein.length < 2) return;
      var parent = t.parent;
      var gateway = factory.createShape({ type: 'bpmn:ExclusiveGateway' });
      modeling.createShape(gateway, { x: t.x - 70, y: t.y + 12 }, parent);
      var verschoben = 0;
      ein.slice().forEach(function (f) {
        try { modeling.reconnectEnd(f, gateway); verschoben++; } catch (e) { /* Kante bleibt */ }
      });
      try { modeling.connect(gateway, t); } catch (e) { /* Kante bleibt */ }
      protokolliere('BPMN-L4-08: Zusammenführung vor ' + (name(t) || t.id) + ' gesetzt (' + verschoben + ' Kanten umgehängt)');
      if (verschoben) geaendert++;
    });

    $('reiter-protokoll').click();
    zeichneProtokoll();
    pruefe();
    if (!geaendert) {
      protokolliere('Keine mechanisch behebbare Änderung gefunden.');
      zeichneProtokoll();
    }
    protokolliere('Offen bleiben Befunde, die eine fachliche Entscheidung brauchen (z. B. Conveyed Items, Pool-Typisierung).');
    zeichneProtokoll();
    ausgabe(geaendert + ' Änderung(en) vorgenommen. Die Prüfung wurde erneut ausgeführt; offene Befunde stehen im Panel.',
      'ADMBw-konform machen');
  }

  // ------------------------------------------------------------------
  // Prosa-Extraktion (JavaScript-Port der Regeln aus packages/bpmn/extraktion.py)
  // ------------------------------------------------------------------

  var ROLLEN = [
    'antragsteller', 'sachbearbeiter', 'bearbeiter', 'mitarbeiter', 'buchhaltung',
    'personalabteilung', 'rechtsabteilung', 'vertrieb', 'einkauf', 'disposition',
    'werkstatt', 'techniker', 'kunde', 'kundin', 'lieferant', 'leasinggesellschaft',
    'leasingnehmer', 'leasinggeber', 'versicherung', 'zulassungsstelle', 'behörde',
    'bauamt', 'ordnungsamt', 'standesamt', 'prüfstelle', 'prüfer', 'antragsbearbeitung',
    'abteilung', 'team', 'leitung', 'geschäftsführung', 'vorstand', 'empfang', 'lager',
    'logistik', 'produktion', 'qualitätssicherung', 'system', 'fachanwendung',
    'helpdesk', 'servicedesk', 'servicecenter', 'support', 'kundenservice', 'bank',
    'kasse', 'poststelle', 'hausverwaltung', 'verwaltung', 'amt', 'referat', 'dezernat'
  ];
  var ROLLEN_SET = {};
  ROLLEN.forEach(function (r) { ROLLEN_SET[r] = 1; });

  var VERB_TABELLE = [
    ['prüfen', ['prüft', 'prüfen', 'geprüft']],
    ['erfassen', ['erfasst', 'erfassen']],
    ['bearbeiten', ['bearbeitet', 'bearbeiten']],
    ['senden', ['sendet', 'senden', 'geschickt', 'schickt', 'schicken']],
    ['übermitteln', ['übermittelt', 'übermitteln']],
    ['weiterleiten', ['weiterleiten', 'weitergeleitet']],
    ['empfangen', ['empfängt', 'empfangen']],
    ['erhalten', ['erhält', 'erhalten']],
    ['entgegennehmen', ['entgegennehmen', 'entgegengenommen']],
    ['genehmigen', ['genehmigt', 'genehmigen']],
    ['freigeben', ['freigeben', 'freigegeben']],
    ['ablehnen', ['ablehnen', 'abgelehnt']],
    ['entscheiden', ['entscheidet', 'entscheiden', 'entschieden']],
    ['buchen', ['bucht', 'buchen', 'gebucht']],
    ['zahlen', ['zahlt', 'zahlen', 'gezahlt']],
    ['ausstellen', ['ausstellen', 'ausgestellt']],
    ['erstellen', ['erstellt', 'erstellen']],
    ['dokumentieren', ['dokumentiert', 'dokumentieren']],
    ['archivieren', ['archiviert', 'archivieren']],
    ['unterschreiben', ['unterschreibt', 'unterschreiben', 'unterschrieben']],
    ['melden', ['meldet', 'melden', 'gemeldet']],
    ['beauftragen', ['beauftragt', 'beauftragen']],
    ['liefern', ['liefert', 'liefern', 'geliefert']],
    ['montieren', ['montiert', 'montieren']],
    ['reparieren', ['repariert', 'reparieren']],
    ['warten', ['wartet', 'warten', 'gewartet']],
    ['bestellen', ['bestellt', 'bestellen']],
    ['versenden', ['versendet', 'versenden', 'versandt']],
    ['kontrollieren', ['kontrolliert', 'kontrollieren']],
    ['berechnen', ['berechnet', 'berechnen']],
    ['ausfüllen', ['ausfüllen', 'ausgefüllt']],
    ['einreichen', ['einreichen', 'eingereicht']],
    ['beantragen', ['beantragt', 'beantragen']],
    ['vermerken', ['vermerkt', 'vermerken']],
    ['protokollieren', ['protokolliert', 'protokollieren']],
    ['klären', ['klärt', 'klären']],
    ['abstimmen', ['abstimmen', 'abgestimmt']],
    ['übergeben', ['übergibt', 'übergeben']],
    ['übernehmen', ['übernimmt', 'übernehmen']],
    ['hinterlegen', ['hinterlegt', 'hinterlegen']],
    ['löschen', ['löscht', 'löschen', 'gelöscht']],
    ['sperren', ['sperrt', 'sperren', 'gesperrt']],
    ['installieren', ['installiert', 'installieren']],
    ['konfigurieren', ['konfiguriert', 'konfigurieren']],
    ['informieren', ['informiert', 'informieren']],
    ['benachrichtigen', ['benachrichtigt', 'benachrichtigen']],
    ['anfordern', ['anfordern', 'angefordert']],
    ['zuweisen', ['zuweisen', 'zugewiesen']]
  ];
  var VERBEN = {};
  VERB_TABELLE.forEach(function (paar) {
    paar[1].forEach(function (form) { VERBEN[form.toLowerCase()] = paar[0]; });
  });
  // Trennbare Verben: konjugierte Form + Partikel -> Infinitiv.
  var SEPARABEL = {};
  [
    ['legt', 'an', 'anlegen'], ['füllt', 'aus', 'ausfüllen'], ['reicht', 'ein', 'einreichen'],
    ['stellt', 'aus', 'ausstellen'], ['gibt', 'frei', 'freigeben'], ['schickt', 'weiter', 'weiterleiten'],
    ['nimmt', 'entgegen', 'entgegennehmen'], ['lehnt', 'ab', 'ablehnen'], ['ruft', 'ab', 'abrufen'],
    ['gibt', 'ein', 'eingeben'], ['rechnet', 'ab', 'abrechnen'], ['fordert', 'an', 'anfordern'],
    ['fragt', 'an', 'anfragen'], ['setzt', 'fest', 'festsetzen'], ['weist', 'zu', 'zuweisen'],
    ['schließt', 'ab', 'abschließen'], ['nimmt', 'auf', 'aufnehmen'], ['greift', 'auf', 'aufgreifen'],
    ['trägt', 'ein', 'eintragen'], ['stimmt', 'ab', 'abstimmen'], ['meldet', 'an', 'anmelden'],
    ['reicht', 'ein', 'einreichen']
  ].forEach(function (eintrag) {
    if (!SEPARABEL[eintrag[0]]) SEPARABEL[eintrag[0]] = [];
    SEPARABEL[eintrag[0]].push([eintrag[1], eintrag[2]]);
  });
  var ARTIKEL = {
    der: 1, die: 1, das: 1, den: 1, dem: 1, des: 1, ein: 1, eine: 1,
    einen: 1, einem: 1, einer: 1, eines: 1, keinen: 1, keine: 1, kein: 1
  };
  var STOPP = {
    an: 1, am: 1, auf: 1, aus: 1, bei: 1, beim: 1, bis: 1, durch: 1, für: 1,
    fuer: 1, gegen: 1, im: 1, in: 1, mit: 1, nach: 1, ohne: 1, seit: 1, über: 1,
    ueber: 1, um: 1, unter: 1, vom: 1, von: 1, vor: 1, zu: 1, zum: 1, zur: 1,
    des: 1, während: 1, waehrend: 1
  };

  function woerter(satz) {
    var treffer = satz.match(/[\wÄÖÜäöüß-]+/g);
    return treffer || [];
  }
  function istRolle(wort) {
    var klein = wort.toLowerCase();
    if (ROLLEN_SET[klein]) return true;
    return /(?:abteilung|behörde|behoerde|gesellschaft|verwaltung|werkstatt|service|stelle|zentrale|kasse|bank|team|amt)$/.test(klein) && klein.length >= 6;
  }
  function findeVerb(satz) {
    var w = woerter(satz);
    for (var i = 0; i < w.length; i++) {
      var form = w[i].toLowerCase();
      if (VERBEN[form]) return { inf: VERBEN[form], index: i, form: w[i] };
      var trennbar = SEPARABEL[form];
      if (trennbar) {
        for (var j = 0; j < trennbar.length; j++) {
          for (var d = 1; d <= 5; d++) {
            if (i + d < w.length && w[i + d].toLowerCase() === trennbar[j][0]) {
              return { inf: trennbar[j][1], index: i, form: w[i] + ' … ' + w[i + d] };
            }
          }
        }
      }
    }
    return null;
  }
  function rolleImSatz(satz) {
    var m = satz.match(/^(?:Der|Die|Das|Ein|Eine)\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]*)/);
    if (m && istRolle(m[1])) return m[1];
    m = satz.match(/\b(?:der|die|das)\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]*)/);
    if (m && istRolle(m[1])) return m[1];
    m = satz.match(/\b(?:von|vom|durch)\s+(?:der|die|dem|den)?\s*([A-ZÄÖÜ][\wÄÖÜäöüß-]*)/);
    if (m && istRolle(m[1])) return m[1];
    return '';
  }
  function objektImSatz(satz, verbIndex, rolle) {
    var w = woerter(satz);
    var k = w.map(function (x) { return x.toLowerCase(); });
    var rollenTeile = rolle ? woerter(rolle).map(function (x) { return x.toLowerCase(); }) : [];
    var start = verbIndex + 1;
    // Inversion: "Danach sendet sie die Rechnung." -- Pronomen ist Subjekt.
    if (start + 1 < k.length && ['er', 'sie', 'es', 'wir', 'ich'].indexOf(k[start]) >= 0 && ARTIKEL[k[start + 1]]) {
      start++;
    }
    var weitergesucht = true;
    while (weitergesucht && start < w.length) {
      weitergesucht = false;
      while (start < w.length && ARTIKEL[k[start]]) { start++; weitergesucht = true; }
      if (rollenTeile.length && k.slice(start, start + rollenTeile.length).join(' ') === rollenTeile.join(' ')) {
        start += rollenTeile.length;
        weitergesucht = true;
      }
    }
    var ende = start;
    while (ende < w.length && !STOPP[k[ende]]) {
      if (['und', 'oder', 'sowie', 'danach', 'anschließend', 'dann', 'zuerst'].indexOf(k[ende]) >= 0) break;
      ende++;
    }
    var text = w.slice(start, ende).join(' ').replace(/^[,.;:!?]+|[,.;:!?]+$/g, '');
    if (!text && verbIndex === w.length - 1) {
      // Imperativ/Infinitiv am Ende: "Antrag erfassen"
      var beginn = verbIndex;
      while (beginn > 0 && !ARTIKEL[k[beginn - 1]]) beginn--;
      text = w.slice(beginn, verbIndex).join(' ');
    }
    if (!text && start < w.length && ['über', 'ueber', 'zu', 'zum', 'zur', 'für', 'fuer', 'auf', 'gegen'].indexOf(k[start]) >= 0) {
      var nach = start + 1;
      while (nach < w.length && ARTIKEL[k[nach]]) nach++;
      var b = nach;
      while (nach < w.length && !STOPP[k[nach]]) nach++;
      text = w.slice(b, nach).join(' ');
    }
    return text;
  }
  function saetze(text) {
    var ergebnis = [];
    text.replace(/\r\n?/g, '\n').split('\n').forEach(function (zeile) {
      zeile = zeile.trim();
      if (!zeile || zeile.charAt(0) === '#') return;
      zeile = zeile.replace(/^(?:[-–—*]|\d+[.)])\s+/, '');
      zeile.split(/(?<=[.!?])\s+|;\s*/).forEach(function (satz) {
        satz = satz.trim();
        if (satz) ergebnis.push(satz);
      });
    });
    return ergebnis;
  }
  function klauseln(satz) {
    var teile = satz.split(/\s+und\s+/);
    var ergebnis = [];
    teile.forEach(function (teil) {
      teil = teil.trim();
      if (!teil) return;
      if (ergebnis.length && !findeVerb(teil)) ergebnis[ergebnis.length - 1] += ' und ' + teil;
      else ergebnis.push(teil);
    });
    return ergebnis.length ? ergebnis : [satz];
  }
  function zerlege(text) {
    var schritte = [];
    var letzteRolle = '';
    var letztesObjekt = '';
    saetze(text).forEach(function (satz) {
      var bedingung = '';
      var m = satz.match(/^(?:Wenn|Falls|Sofern|Sobald)\s+(.+?),\s*(?:dann\s+)?(.+)$/i);
      var haupt = satz;
      if (m) { bedingung = m[1].trim(); haupt = m[2].trim(); }
      klauseln(haupt).forEach(function (klausel) {
        var verb = findeVerb(klausel);
        if (!verb) return;
        var rolle = rolleImSatz(klausel);
        if (!rolle && letzteRolle) rolle = letzteRolle;
        if (rolle) letzteRolle = rolle;
        var objekt = objektImSatz(klausel, verb.index, rolle);
        if (!objekt) return;
        if (/^(ihn|sie|es|ihm|diesen|diese|dieses)$/i.test(objekt) && letztesObjekt) objekt = letztesObjekt;
        letztesObjekt = objekt;
        schritte.push({
          rolle: rolle,
          aktion: verb.inf,
          objekt: objekt,
          bedingung: bedingung
        });
      });
    });
    return schritte;
  }

  function aktionsName(schritt) {
    var objekt = (schritt.objekt || '').trim();
    var aktion = (schritt.aktion || 'bearbeiten').trim();
    return (objekt ? objekt.charAt(0).toUpperCase() + objekt.slice(1) + ' ' : '') + aktion;
  }

  function prozessXml(nameWunsch, schritte) {
    var prozessName = (nameWunsch || '').trim() || 'Extrahierter Prozess';
    var lanes = [];
    var laneIndex = {};
    schritte.forEach(function (s) {
      var rolle = s.rolle || 'Bearbeitung';
      if (laneIndex[rolle] == null) {
        laneIndex[rolle] = lanes.length;
        lanes.push(rolle);
      }
      s._lane = laneIndex[rolle];
    });
    if (!lanes.length) lanes.push('Bearbeitung');

    var laneHoehe = 130;
    var startY = 40;
    var breite = Math.max(1000, 300 + schritte.length * 170);
    var poolHoehe = Math.max(laneHoehe, lanes.length * laneHoehe);
    var y = function (lane) { return startY + lane * laneHoehe + 42; };
    var xTask = function (i) { return 230 + i * 170; };

    var knoten = [];
    var kanten = [];
    var knotenLane = {};
    var letzter = 'Start_Text';
    var startKnoten = { id: 'Start_Text', x: 140, y: y(0), w: 36, h: 36 };
    knoten.push(startKnoten);
    knotenLane['Start_Text'] = 0;

    var gwNr = 0;
    schritte.forEach(function (s, i) {
      var aufgabeId = 'Task_' + (i + 1);
      var aufgabeX = xTask(i);
      if (s.bedingung) {
        var split = 'Gateway_Split_' + (++gwNr);
        var merge = 'Gateway_Merge_' + gwNr;
        knoten.push({ id: split, x: aufgabeX - 80, y: y(s._lane), w: 50, h: 50 });
        knotenLane[split] = s._lane;
        knoten.push({ id: aufgabeId, x: aufgabeX, y: y(s._lane) + 7, w: 120, h: 68 });
        knotenLane[aufgabeId] = s._lane;
        knoten.push({ id: merge, x: aufgabeX + 160, y: y(s._lane), w: 50, h: 50 });
        knotenLane[merge] = s._lane;
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: letzter, z: split });
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: split, z: aufgabeId, bedingung: s.bedingung });
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: split, z: merge, name: 'andernfalls' });
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: aufgabeId, z: merge });
        letzter = merge;
        return;
      }
      knoten.push({ id: aufgabeId, x: aufgabeX, y: y(s._lane) + 7, w: 120, h: 68 });
      knotenLane[aufgabeId] = s._lane;
      kanten.push({ id: 'Flow_' + (kanten.length + 1), q: letzter, z: aufgabeId });
      letzter = aufgabeId;
    });
    var letzteLane = schritte.length ? schritte[schritte.length - 1]._lane : 0;
    var endX = xTask(schritte.length) + 60;
    knoten.push({ id: 'End_Text', x: endX, y: y(letzteLane), w: 36, h: 36 });
    knotenLane['End_Text'] = letzteLane;
    kanten.push({ id: 'Flow_' + (kanten.length + 1), q: letzter, z: 'End_Text' });

    var xml = [];
    xml.push('<?xml version="1.0" encoding="UTF-8"?>');
    xml.push('<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" ' +
      'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" ' +
      'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" ' +
      'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" ' +
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ' +
      'id="Definitions_Text" targetNamespace="https://eam-platform.local/bpmn">');
    xml.push('<bpmn:collaboration id="Collaboration_Text"><bpmn:participant id="Participant_Text" name="' +
      esc(prozessName) + '" processRef="Process_Text" /></bpmn:collaboration>');
    xml.push('<bpmn:process id="Process_Text" name="' + esc(prozessName) + '" isExecutable="false">');
    xml.push('<bpmn:laneSet id="LaneSet_Text">');
    lanes.forEach(function (lane, i) {
      var refs = [];
      knoten.forEach(function (k) {
        if (knotenLane[k.id] === i) refs.push('<bpmn:flowNodeRef>' + k.id + '</bpmn:flowNodeRef>');
      });
      xml.push('<bpmn:lane id="Lane_Text_' + (i + 1) + '" name="' + esc(lane) + '">' + refs.join('') + '</bpmn:lane>');
    });
    xml.push('</bpmn:laneSet>');
    xml.push('<bpmn:startEvent id="Start_Text" name="' + esc(prozessName) + ' gestartet" />');
    schritte.forEach(function (s, i) {
      xml.push('<bpmn:userTask id="Task_' + (i + 1) + '" name="' + esc(aktionsName(s)) + '" />');
    });
    xml.push('<bpmn:endEvent id="End_Text" name="' + esc(prozessName) + ' abgeschlossen" />');
    // Ohne diesen Block existieren die Gateways nur als Zeichnung: die Fluesse
    // zeigen dann auf Elemente, die es im Modell nicht gibt.
    knoten.forEach(function (k) {
      if (/^Gateway_(Split|Merge)_/.test(k.id)) {
        xml.push('<bpmn:exclusiveGateway id="' + k.id + '" />');
      }
    });
    kanten.forEach(function (k) {
      var nameAttr = k.name ? ' name="' + esc(k.name) + '"' : '';
      xml.push('<bpmn:sequenceFlow id="' + k.id + '" sourceRef="' + k.q + '" targetRef="' + k.z + '"' + nameAttr + '>' +
        (k.bedingung ? '<bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">' +
          esc(k.bedingung) + '</bpmn:conditionExpression>' : '') + '</bpmn:sequenceFlow>');
    });
    xml.push('</bpmn:process>');

    xml.push('<bpmndi:BPMNDiagram id="BPMNDiagram_Text"><bpmndi:BPMNPlane id="BPMNPlane_Text" bpmnElement="Collaboration_Text">');
    xml.push('<bpmndi:BPMNShape id="Participant_Text_di" bpmnElement="Participant_Text" isHorizontal="true"><dc:Bounds x="40" y="' +
      startY + '" width="' + breite + '" height="' + poolHoehe + '" /></bpmndi:BPMNShape>');
    lanes.forEach(function (lane, i) {
      xml.push('<bpmndi:BPMNShape id="Lane_Text_' + (i + 1) + '_di" bpmnElement="Lane_Text_' + (i + 1) +
        '" isHorizontal="true"><dc:Bounds x="40" y="' + (startY + i * laneHoehe) + '" width="' + breite +
        '" height="' + laneHoehe + '" /></bpmndi:BPMNShape>');
    });
    knoten.forEach(function (k) {
      xml.push('<bpmndi:BPMNShape id="' + k.id + '_di" bpmnElement="' + k.id + '"><dc:Bounds x="' + k.x +
        '" y="' + k.y + '" width="' + k.w + '" height="' + k.h + '" /></bpmndi:BPMNShape>');
    });
    kanten.forEach(function (k) {
      var q = knoten.filter(function (n) { return n.id === k.q; })[0];
      var z = knoten.filter(function (n) { return n.id === k.z; })[0];
      if (!q || !z) return;
      var qx = q.x + q.w, qy = q.y + q.h / 2, zx = z.x, zy = z.y + z.h / 2;
      var punkte = Math.abs(qy - zy) < 0.5
        ? [[qx, qy], [zx, zy]]
        : [[qx, qy], [qx + 25, qy], [qx + 25, zy], [zx, zy]];
      xml.push('<bpmndi:BPMNEdge id="' + k.id + '_di" bpmnElement="' + k.id + '">' +
        punkte.map(function (p) { return '<di:waypoint x="' + p[0] + '" y="' + p[1] + '" />'; }).join('') +
        '</bpmndi:BPMNEdge>');
    });
    xml.push('</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>');
    xml.push('</bpmn:definitions>');
    return xml.join('\n');
  }

  // ------------------------------------------------------------------
  // Dialoge
  // ------------------------------------------------------------------

  function textDialogOeffnen() {
    $('text-warnung').hidden = true;
    $('text-dialog').showModal();
  }

  // Auftrag auswerten: "extrahiere den Prozess Rechnungslauf" -> Abschnitt.
  function abschnittFuerAuftrag(text, auftrag) {
    var ergebnis = { text: text, name: '', hinweis: '' };
    if (!auftrag) return ergebnis;
    var name = '';
    var zitat = auftrag.match(/["„“']([^"“”']{3,80})["“”']/);
    if (zitat) name = zitat[1].trim();
    if (!name) {
      var form = auftrag.match(/\b(?:prozess|vorgang|verfahren)\s+([A-Za-zÄÖÜäöüß0-9][\w\-äöüß ]{2,60})/i);
      if (form) name = form[1].replace(/\s+(aus|bitte|und|sowie)\b.*$/i, '').trim();
    }
    if (!name) {
      ergebnis.hinweis = 'Auftrag ohne Prozessnamen — ganzer Text ausgewertet.';
      return ergebnis;
    }
    ergebnis.name = name;
    var zeilen = text.split('\n');
    var klein = name.toLowerCase();
    for (var i = 0; i < zeilen.length; i++) {
      var roh = zeilen[i].trim().replace(/^[#*=\-–— ]+|[#*=\-–— ]+$/g, '');
      if (!roh || roh.length > 90 || /[.!?;]$/.test(roh)) continue;
      if (roh.toLowerCase().indexOf(klein) === -1) continue;
      var grenze = zeilen.length;
      for (var j = i + 1; j < zeilen.length; j++) {
        var kandidat = zeilen[j].trim().replace(/^[#*=\-–— ]+|[#*=\-–— ]+$/g, '');
        if (!kandidat || kandidat.length > 90 || /[.!?;]$/.test(kandidat)) continue;
        if (Math.abs(kandidat.length - roh.length) <= Math.max(25, roh.length / 2)) { grenze = j; break; }
      }
      var block = zeilen.slice(i, grenze).filter(function (z) { return z.trim(); });
      if (block.length >= 2) {
        ergebnis.text = block.join('\n');
        ergebnis.hinweis = 'Auftrag: Abschnitt "' + name + '" gewählt (' + block.length + ' Zeilen); der übrige Text wurde nicht ausgewertet.';
        return ergebnis;
      }
    }
    ergebnis.hinweis = 'Auftrag nennt "' + name + '", im Text aber kein passender Abschnitt — ganzer Text ausgewertet.';
    return ergebnis;
  }

  function textExtrahieren() {
    var text = $('text-eingabe').value.trim();
    if (!text) { $('text-warnung').hidden = false; $('text-warnung').textContent = 'Bitte einen Prozesstext eingeben.'; return; }
    var auftrag = $('text-auftrag') ? $('text-auftrag').value.trim() : '';
    var wahl = abschnittFuerAuftrag(text, auftrag);
    if (wahl.name && !$('text-name').value.trim()) $('text-name').value = wahl.name;
    text = wahl.text;
    var schritte = zerlege(text);
    if (!schritte.length) {
      $('text-warnung').hidden = false;
      $('text-warnung').textContent = 'Kein Schritt erkannt. Sätze mit Handlung (Verb + Objekt) oder nummerierte Listen verwenden.';
      return;
    }
    var xml = prozessXml($('text-name').value, schritte);
    $('text-dialog').close();
    importieren(xml).then(function () {
      protokoll = [wahl.hinweis].concat(['Aus Text: ' + schritte.length + ' Schritt(e), ' + new Set(schritte.map(function (s) { return s.rolle || 'Bearbeitung'; })).size + ' Rolle(n) als Lanes.']).filter(function (z) { return !!z; });
      protokolliere('Alle Elemente sind Vorschläge — bitte fachlich prüfen (Sicherheitsgrad "unsicher").');
      zeichneProtokoll();
      $('reiter-protokoll').click();
      pruefe();
    }).catch(function (fehler) {
      ausgabe('Der Text konnte nicht in BPMN übersetzt werden: ' + fehler.message, 'Extraktion fehlgeschlagen');
    });
  }

  function kiDialogOeffnen() {
    $('ki-status').hidden = true;
    try {
      if (!$('ki-url').value) $('ki-url').value = localStorage.getItem('bpmn-ki-url') || '';
      if (!$('ki-modell').value) $('ki-modell').value = localStorage.getItem('bpmn-ki-modell') || '';
    } catch (e) { /* privater Modus: nichts gemerkt */ }
    $('ki-dialog').showModal();
  }

  function kiExtrahieren() {
    var basis = $('ki-url').value.trim().replace(/\/+$/, '');
    var modell = $('ki-modell').value.trim();
    var key = $('ki-key').value;
    var text = $('ki-eingabe').value.trim();
    var status = $('ki-status');
    try {
      localStorage.setItem('bpmn-ki-url', basis);
      localStorage.setItem('bpmn-ki-modell', modell);
    } catch (e) { /* privater Modus: nichts gemerkt */ }
    if (!basis || !modell || !key) {
      status.hidden = false;
      status.className = 'warnung fehler';
      status.textContent = 'Basis-URL, Modell und Schlüssel sind erforderlich. Es wird nichts gesendet.';
      return;
    }
    if (!text) {
      status.hidden = false;
      status.className = 'warnung fehler';
      status.textContent = 'Bitte einen Text eingeben.';
      return;
    }
    var endpoint = /\/chat\/completions$/.test(basis) ? basis : basis + '/chat/completions';
    status.hidden = false;
    status.className = 'warnung';
    status.textContent = 'Anfrage läuft …';
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
      body: JSON.stringify({
        model: modell,
        temperature: 0,
        response_format: { type: 'json_object' },
        messages: [
          { role: 'system', content: 'Du bist Prozessanalyst. Antworte ausschließlich mit einem JSON-Objekt dieser Form: {"schritte":[{"rolle":"...","aktion":"...","objekt":"...","bedingung":"..."}]}. Aktion im Infinitiv. Erfinde nichts, was nicht im Text steht. Kein Markdown, keine Erklärung.' },
          { role: 'user', content: text }
        ]
      })
    }).then(function (antwort) {
      if (!antwort.ok) {
        // Die Gegenstelle sagt meist genau, was fehlt (Schluessel, Guthaben, Modell).
        return antwort.text().then(function (roh) {
          var meldung = '';
          try {
            var fehler = JSON.parse(roh);
            meldung = (fehler && fehler.error && (fehler.error.message || fehler.error)) || '';
          } catch (e) {
            meldung = String(roh || '').slice(0, 200);
          }
          throw new Error('HTTP ' + antwort.status + (meldung ? ' — ' + meldung : ''));
        });
      }
      return antwort.json();
    }).then(function (daten) {
      var inhalt = daten && daten.choices && daten.choices[0] && daten.choices[0].message && daten.choices[0].message.content;
      if (!inhalt) throw new Error('Antwort ohne Inhalt');
      var bereinigt = String(inhalt).trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
      var json = JSON.parse(bereinigt);
      var liste = json.schritte || json.steps || (Array.isArray(json) ? json : null);
      if (!liste || !liste.length) throw new Error('Antwort enthält keine Schritte (erwartet: {"schritte": [...]})');
      var zeitwort = /^(danach|anschließend|anschliessend|daraufhin|darauf|zuerst|zunächst|zunaechst|schließlich|schliesslich|abschließend|abschliessend|im anschluss|zum schluss|anschließend)\b[\s,.]*$/i;
      var schritte = liste.map(function (s) {
        var bedingung = String(s.bedingung || s.condition || '').trim();
        if (zeitwort.test(bedingung)) bedingung = '';
        return {
          rolle: String(s.rolle || s.role || '').trim(),
          aktion: String(s.aktion || s.action || 'bearbeiten').trim().toLowerCase(),
          objekt: String(s.objekt || s.object || '').trim(),
          bedingung: bedingung
        };
      });
      var xml = prozessXml($('text-name') ? $('text-name').value : '', schritte);
      $('ki-dialog').close();
      importieren(xml).then(function () {
        protokoll = ['KI-Ausgabe: ' + schritte.length + ' Schritt(e). Alle Elemente sind Vorschläge und fachlich zu prüfen.'];
        zeichneProtokoll();
        $('reiter-protokoll').click();
        pruefe();
      });
    }).catch(function (fehler) {
      status.hidden = false;
      status.className = 'warnung fehler';
      status.textContent = 'KI-Aufruf fehlgeschlagen: ' + fehler.message + '. Es wurde nichts übernommen.';
    });
  }

  // ------------------------------------------------------------------
  // Start
  // ------------------------------------------------------------------

  function verbinden() {
    $('datei-laden').addEventListener('change', function (e) {
      textLaden(e.target.files && e.target.files[0]);
      e.target.value = '';
    });
    $('btn-neu').addEventListener('click', function () { importieren(LEER_XML); });
    $('btn-speichern').addEventListener('click', speichern);
    $('btn-xml').addEventListener('click', speichern);
    $('btn-svg').addEventListener('click', exportSvg);
    $('btn-png').addEventListener('click', exportPng);
    $('btn-pruefen').addEventListener('click', function () { pruefe(); $('reiter-befunde').click(); });
    $('btn-konform').addEventListener('click', konformMachen);
    $('btn-text').addEventListener('click', textDialogOeffnen);
    $('text-abweisen').addEventListener('click', function () { $('text-dialog').close(); });
    $('text-starten').addEventListener('click', textExtrahieren);
    $('ki-aktiv').addEventListener('change', function () {
      if (this.checked) kiDialogOeffnen();
    });
    $('ki-abweisen').addEventListener('click', function () { $('ki-dialog').close(); });
    $('ki-starten').addEventListener('click', kiExtrahieren);
    $('reiter-befunde').addEventListener('click', function () {
      this.classList.add('aktiv'); this.setAttribute('aria-selected', 'true');
      $('reiter-protokoll').classList.remove('aktiv'); $('reiter-protokoll').setAttribute('aria-selected', 'false');
      $('bereich-befunde').hidden = false; $('bereich-protokoll').hidden = true;
    });
    $('reiter-protokoll').addEventListener('click', function () {
      this.classList.add('aktiv'); this.setAttribute('aria-selected', 'true');
      $('reiter-befunde').classList.remove('aktiv'); $('reiter-befunde').setAttribute('aria-selected', 'false');
      $('bereich-protokoll').hidden = false; $('bereich-befunde').hidden = true;
    });

    var leinwand = $('leinwand');
    ['dragenter', 'dragover'].forEach(function (art) {
      leinwand.addEventListener(art, function (e) { e.preventDefault(); });
    });
    leinwand.addEventListener('drop', function (e) {
      e.preventDefault();
      var datei = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (datei) textLaden(datei);
    });
  }

  function start() {
    modeler = new window.BpmnJS({ container: '#canvas' });
    modeler.on('import.done', function () {
      $('hinweis-start').hidden = true;
    });
    verbinden();
    importieren(LEER_XML).catch(function (fehler) {
      ausgabe('Startmodell nicht lesbar: ' + fehler.message);
    });
    // Kleine, dokumentierte Schnittstelle fuer Tests und Integratoren.
    window.BPMNStudio = {
      modeler: function () { return modeler; },
      pruefe: pruefe,
      zerlege: zerlege,
      prozessXml: prozessXml,
      version: '{{VERSION}}'
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
