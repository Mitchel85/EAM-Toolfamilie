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

  // Nach dem Import passt sich die Ansicht dem Modell an. Bei einem sehr langen
  // Band landet sonst alles bei 0,12-facher Groesse in einer unlesbaren Reihe.
  function canvasUebersicht() {
    var canvas = modeler.get('canvas');
    try {
      // Ganzes Modell mit Rand: Pool-Rahmen und Lane-Beschriftung gehoeren ins
      // Bild. Links muss der Rand die Werkzeugleiste freihalten, sonst liegt
      // der Pool-Kopf darunter und das Diagramm wirkt rahmenlos.
      var vb = canvas.viewbox();
      var flaeche = document.querySelector('.djs-container');
      var breite = flaeche ? flaeche.clientWidth : 1200;
      var hoehe = flaeche ? flaeche.clientHeight : 800;
      var links = 90, rest = 25, oben = 25;
      var skala = Math.min((breite - links - rest) / Math.max(1, vb.inner.width),
                           (hoehe - oben - rest) / Math.max(1, vb.inner.height));
      if (!(skala > 0)) skala = vb.scale || 1;
      canvas.viewbox({
        x: vb.inner.x - links / skala,
        y: vb.inner.y - oben / skala,
        width: breite / skala,
        height: hoehe / skala
      });
    } catch (e) { /* Ansicht ist Beiwerk */ }
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
    ['unterzeichnen', ['unterzeichnet', 'unterzeichnen', 'unterzeichne']],
    ['schließen', ['geschlossen', 'schließt', 'schließen', 'abgeschlossen']],
    ['erfolgen', ['erfolgt', 'erfolgen']],
    ['informieren', ['informiert', 'informieren']],
    ['melden', ['meldet', 'melden', 'gemeldet']],
    ['veröffentlichen', ['veröffentlicht', 'veröffentlichen']],
    ['festlegen', ['festgelegt', 'festlegen', 'legt fest']],
    ['bewerten', ['bewertet', 'bewerten']],
    ['einleiten', ['eingeleitet', 'einleiten', 'leitet ein']],
    ['aufnehmen', ['aufgenommen', 'aufnehmen']],
    ['bilden', ['gebildet', 'bilden']],
    ['benennen', ['benannt', 'benennen']],
    ['unterrichten', ['unterrichtet', 'unterrichten']],
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
  // Rollen, die in Verfahrenstexten taugen. Ohne diese Liste erkennt die
  // Regelzerlegung nur Woerter auf -stelle/-amt und laesst "BAAINBw" oder
  // "Truppe" durchfallen — dann entsteht genau eine Lane "Bearbeitung".
  var ROLLEN_BEKANNT = ['BAAINBw', 'BMVg', 'Truppe', 'Bieter', 'Haushaltsausschuss',
    'Bundesrechnungshof', 'Bundesarchiv', 'NATO', 'Vergabestelle', 'Prüfstelle',
    'Nutzer', 'Industrie', 'Auftragnehmer', 'Auftraggeber', 'Bundesamt',
    'Referat', 'Abteilung', 'Qualitätssicherung', 'Projektlenkungsausschuss',
    'Projektbüro', 'Projektgruppe', 'Kommission', 'Ministerium', 'Dezernat',
    'Dienststelle', 'Bundesministerium', 'Prüfungsamt', 'Vergabekammer',
    'Projektmanager', 'Projektleiter', 'Projektleiterin', 'Teamleiter',
    'Sachbearbeiter', 'Sachbearbeiterin', 'Referent', 'Referentin'];

  function istRolle(wort) {
    var klein = wort.toLowerCase();
    if (ROLLEN_SET[klein]) return true;
    for (var i = 0; i < ROLLEN_BEKANNT.length; i++) {
      if (ROLLEN_BEKANNT[i].toLowerCase() === klein) return true;
    }
    // Abkuerzungen wie PSG, PLA, BWB sind Aufgabentraeger, auch wenn sie in
    // keiner Liste stehen.
    if (/^[A-ZÄÖÜ][A-ZÄÖÜ0-9]{2,7}$/.test(wort)) return true;
    return /(?:abteilung|behörde|behoerde|gesellschaft|verwaltung|werkstatt|service|stelle|zentrale|kasse|bank|team|amt|ausschuss|ministerium|truppe|bieter)$/.test(klein) && klein.length >= 5;
  }

  // Sucht eine bekannte Rolle im Satz — zuerst als Subjekt, dann nach
  // "durch/vom/seitens", zuletzt irgendwo im Satz.
  function bekannteRolle(satz) {
    var beste = '', bestePos = -1;
    ROLLEN_BEKANNT.forEach(function (r) {
      var re = new RegExp('(^|[^\\wÄÖÜäöüß])' + r.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '([^\\wÄÖÜäöüß]|$)', 'i');
      var m = satz.match(re);
      if (!m) return;
      var pos = m.index + m[1].length;
      if (bestePos < 0 || pos < bestePos) { beste = satz.substr(pos, r.length); bestePos = pos; }
    });
    return beste;
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
    var m;
    // 1. Subjekt am Satzanfang: "Der BAAINBw prueft ..."
    m = satz.match(/^(?:Der|Die|Das|Ein|Eine)\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]*)/);
    if (m && istRolle(m[1])) return m[1];
    // 2. Handelnde Stelle im Passiv: "… ist durch den BAAINBw zu pruefen"
    m = satz.match(/\b(?:durch|vom|von|seitens|beim)\s+(?:der|die|dem|den)?\s*([A-ZÄÖÜ][\wÄÖÜäöüß-]*)/);
    if (m && istRolle(m[1])) return m[1];
    // 3. Bekannte Rolle irgendwo im Satz
    m = bekannteRolle(satz);
    if (m) return m;
    // 4. Sonst: Artikel + Rollenwort irgendwo
    m = satz.match(/\b(?:der|die|das)\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]*)/);
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
    var text = w.slice(start, ende).join(' ')
      .replace(/^[,.;:!?]+|[,.;:!?]+$/g, '')
      .replace(/\s+(?:ist|sind|wird|werden|hat|haben)\s+zu\b.*$/i, '')
      .replace(/\s+(?:ist|sind)\s*$/i, '')
      .replace(/\s+zu$/i, '')
      .trim();
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
    // Kein Objekt nach dem Verb: das Subjekt davor ist das Objekt
    // ("Die Entscheidung erfolgt durch die PSG.").
    if (!text) {
      var vorn = verbIndex - 1;
      while (vorn >= 0 && (ARTIKEL[k[vorn]] || STOPP[k[vorn]])) vorn--;
      var anf = vorn;
      while (anf > 0 && !ARTIKEL[k[anf - 1]] && !STOPP[k[anf - 1]]) anf--;
      if (vorn >= anf) text = w.slice(anf, vorn + 1).join(' ');
    }
    // Auch der Rueckfallpfad ("Antrag ist zu") muss die Hilfsverbreste loswerden.
    text = text
      .replace(/\s+(?:ist|sind|wird|werden|hat|haben)\s+zu\b.*$/i, '')
      .replace(/\s+(?:ist|sind)\s*$/i, '')
      .replace(/\s+zu$/i, '')
      .trim();
    // Reine Hilfswoerter sind kein Objekt.
    if (/^(?:ist|sind|wird|werden|hat|haben|zu|der|die|das|dem|den)$/i.test(text)) text = '';
    return text;
  }
  function saetze(text) {
    var ergebnis = [];
    // Zeilen, die mitten im Satz umbrechen ("… Ablehnung (1\nWoche nach
    // Bericht)"), wieder zusammenziehen — sonst entstehen halbe Labels.
    var rohZeilen = text.replace(/\r\n?/g, '\n').split('\n');
    var zeilen = [];
    rohZeilen.forEach(function (z) {
      var vorher = zeilen.length ? zeilen[zeilen.length - 1] : '';
      var offen = (/[(,;:\-–]$/.test(vorher.trim())
        || vorher.split('(').length > vorher.split(')').length)
        && !/^\s*[•▪◦·\-–—*]/.test(z);
      if (offen && z.trim()) zeilen[zeilen.length - 1] = vorher + ' ' + z.trim();
      else zeilen.push(z);
    });
    zeilen.forEach(function (zeile) {
      var roh = zeile.trim();
      if (!roh || roh.charAt(0) === '#') return;
      var punkt = /^[•▪◦·\-–—*]\s+/.test(roh);
      // Aufzaehlungszeichen bleibt stehen: der Kopf der Aufzaehlung wird eine
      // Aufgabe, die Punkte darunter ihre Details. Nur numerierte Zeilen
      // werden entnummeriert, ihr Inhalt ist ein eigener Schritt.
      zeile = punkt ? roh : roh.replace(/^\d+[.)]\s+/, '');
      zeile.split(/(?<=[.!?])\s+|;\s*/).forEach(function (satz) {
        satz = satz.trim();
        if (!satz) return;
        if (punkt && ergebnis.length && (/^[a-zäöüß]/.test(satz) || /^[A-ZÄÖÜ]{2,}\.$/.test(satz))) {
          // "… zu pruefen. der Pruefbericht ist zu erstellen" ist ein Satz,
          // der an einer Abkuerzung oder Aufzaehlung haengt, kein neuer.
          ergebnis[ergebnis.length - 1] += ' ' + satz;
          return;
        }
        ergebnis.push(satz);
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
  var ZAEHLWOERTER = ['welcher', 'welche', 'welches', 'wer', 'was',
    'mehrere', 'zahlreiche', 'diverse', 'sämtliche', 'saemtliche',
    'alle', 'beide', 'einige', 'folgende', 'verschiedene', 'unterschiedliche',
    'weitere', 'einzelne', 'die', 'der', 'das', 'den', 'dem', 'des'];

  // Satzfragmente sind keine Aufgaben: "Jede Aktivität ist separat dokumentieren"
  // wird zu "Aktivität dokumentieren", "Werden können informieren" faellt weg.
  function bereinigeObjekt(objekt) {
    var t = String(objekt || '').trim();
    t = t.replace(/^(?:Wobei|Hierbei|Danach|Anschließend|Anschliessend|Zudem|Dabei|Dafür|Dafuer)\s+/i, '');
    t = t.replace(/^(.*?)\s+(?:ist|sind|hat|haben|wird|werden)\s+.*$/i, '$1');
    t = t.replace(/^(?:Jede|Jeder|Jedes|Alle|Sämtliche|Saemtliche|Die|Der|Das|Den|Dem|Ein|Eine|Einen|Einem)\s+/i, '');
    t = t.replace(/\s+/g, ' ').trim();
    if (!t) return '';
    // Satzreste ohne Sachbezug.
    if (/^(?:werden|koennen|können|haben|hat|ist|sind|wird)\b/i.test(t)) return '';
    if (/^(?:Gemäß|Gemaess|Nach|Laut|Aufgrund|Gem\.)(?:\s|$)/i.test(t)) return '';
    // Einzelnes Genitivwort ("Notars", "Personals") ist kein Objekt.
    if (/^[A-ZÄÖÜ][a-zäöüß]{3,}s$/.test(t)) return '';
    // Reine Zeit- oder Zahlenangaben sind kein Objekt.
    if (/^(?:\d+|einige|mehrere)\b/i.test(t)) return '';
    if (/^(?:woche|wochen|monat|monate|tag|tage|jahr|jahre)\b/i.test(t)) return '';
    return t;
  }

  // "Freigabe, Freigabe mit Auflagen oder Ablehnung" ist ein Entscheidungspunkt,
  // keine Aufgabe. Nur Ausgaenge mit Ergebnischarakter zaehlen — "PSG oder PLA"
  // ist eine Zustaendigkeit, kein Gateway.
  var ENTSCHEIDUNGS_WORTE = /(freigabe|abnahme|ablehnung|zuschlag|absage|genehmigung|zustimmung|auflagen)/i;

  function entscheidungsListe(satz) {
    if (!/\boder\b/i.test(satz)) return null;
    // Nur ein echter Kopf ("Entscheidung: ...") wird abgeschnitten; sonst
    // verliert der erste Ausgang seinen halben Namen ("ohne Auflagen").
    var teil = satz.replace(/^[^:–-]*[:–-]\s*/, '');
    var items = teil.replace(/[.;]\s*$/, '').split(/\s*,\s*|\s+oder\s+/i)
      .map(function (s) { return s.trim(); }).filter(Boolean);
    if (items.length < 2) return null;
    var treffer = items.filter(function (s) { return ENTSCHEIDUNGS_WORTE.test(s); });
    if (treffer.length < 2) return null;
    return items.slice(0, 4);
  }

  function zerlege(text) {
    var schritte = [];
    var letzteRolle = '';
    var letztesObjekt = '';
    var naechsteZeileStart = '';
    saetze(text).forEach(function (satz) {
      var bedingung = '';
      var m = satz.match(/^(?:Wenn|Falls|Sofern|Sobald)\s+(.+?),\s*(?:dann\s+)?(.+)$/i);
      var haupt = satz;
      if (m) { bedingung = m[1].trim(); haupt = m[2].trim(); }
      if (!m) {
        // "Bei Ablehnung ist der Vorgang zu schliessen."
        var mb = satz.match(/^Bei\s+(.+?)\s+(ist|sind|wird|werden|hat|haben)\s+(.+)$/i);
        if (mb) { bedingung = 'Bei ' + mb[1].trim(); haupt = mb[2] + ' ' + mb[3]; }
      }
      var istNaechsterSatz = typeof naechsteZeileStart === 'object' && !/^\s*[•▪◦·\-–—]/.test(satz);
      if (istNaechsterSatz) naechsteZeileStart = '';
      var punkt = /^\s*[•▪◦·\-–—]\s+(.+)$/.test(satz);
      if (punkt && naechsteZeileStart && typeof naechsteZeileStart === 'object') {
        naechsteZeileStart.teilschritte.push(satz.replace(/^\s*[•▪◦·\-–—]\s+/, '').replace(/[.;]\s*$/, '').trim());
        return;
      }
      klauseln(haupt).forEach(function (klausel) {
        var entscheidung = entscheidungsListe(klausel);
        if (entscheidung) {
          var rolleE = rolleImSatz(klausel) || letzteRolle;
          if (rolleE) letzteRolle = rolleE;
          var frage = 'Entscheidung treffen';
          if (/freigabe/i.test(entscheidung.join(' '))) frage = 'Freigabe entscheiden';
          else if (/abnahme/i.test(entscheidung.join(' '))) frage = 'Abnahme entscheiden';
          else if (/zuschlag|absage/i.test(entscheidung.join(' '))) frage = 'Zuschlag entscheiden';
          schritte.push({
            rolle: rolleE,
            aktion: 'entscheiden',
            objekt: 'Entscheidung',
            frage: frage,
            entscheidung: entscheidung,
            bedingung: bedingung
          });
          return;
        }
        var verb = findeVerb(klausel);
        if (!verb) return;
        var rolle = rolleImSatz(klausel);
        if (!rolle && letzteRolle) rolle = letzteRolle;
        if (rolle) letzteRolle = rolle;
        var objekt = objektImSatz(klausel, verb.index, rolle);

        // "folgende Stellen zu genehmigen" ist keine Aufgabe, sondern ein
        // Platzhalter fuer eine Aufzaehlung. Der Kopf der Aufzaehlung wird zur
        // Aufgabe, die Punkte darunter werden zu Details derselben Aufgabe.
        if (/^eine der/i.test(objekt) || /^einer der/i.test(objekt)) return;
        if (ZAEHLWOERTER.indexOf(objekt.trim().toLowerCase()) !== -1
            || /^(welche[rms]?|wer|was|folgende[nrs]?|mehrere[nrs]?|alle[nrs]?|beide[nrs]?|einige[nrs]?|sämtliche[nrs]?|saemtliche[nrs]?)\b/i.test(objekt.trim())) {
          if (!naechsteZeileStart) naechsteZeileStart = verb.inf;
          return;
        }
        objekt = bereinigeObjekt(objekt);
        if (!objekt) return;
        if (/^(ihn|sie|es|ihm|diesen|diese|dieses)$/i.test(objekt) && letztesObjekt) objekt = letztesObjekt;
        // Steht die Rolle im Objekt, gehoert sie in die Lane.
        // Objekt ist nur die eigene Rolle: keine Aufgabe.
        if (rolle && objekt.toLowerCase() === String(rolle).toLowerCase()) return;
        var erstes = objekt.split(/\s+/)[0];
        if (istRolle(erstes) && erstes.toLowerCase() !== String(rolle || '').toLowerCase()) {
          rolle = erstes;
          letzteRolle = rolle;
          objekt = bereinigeObjekt(objekt.split(/\s+/).slice(1).join(' '));
          if (!objekt) return;
        }
        // Letzte Kontrolle: Satzanlaeufe, die kein Objekt sind.
        // \b greift nach "ß" nicht (ASCII-Wortgrenze), daher \s|$.
        if (/^(?:Gemäß|Gemaess|Werden|Wobei|Hierbei|Danach)(?:\s|$)/i.test(objekt)) return;
        // "Bewertung erfolgen" heisst "Bewertung durchfuehren".
        if (verb.inf === 'erfolgen') verb = { inf: 'durchführen', index: verb.index, form: verb.form };
        letztesObjekt = objekt;
        var istKopf = !!naechsteZeileStart;
        var schritt = {
          rolle: rolle,
          aktion: verb.inf,
          objekt: objekt,
          bedingung: bedingung
        };
        if (istKopf) {
          schritt.teilschritte = [];
          naechsteZeileStart = schritt;
        }
        // Entscheidung ohne ausformulierte Ergebnisse: nach BPMN-Konvention
        // zwei Ausgaenge "ja"/"nein".
        if (verb.inf === 'entscheiden' && !bedingung) {
          schritt.entscheidung = ['ja', 'nein'];
        }
        schritte.push(schritt);
      });
    });
    // Rollenluecke schliessen: ein Schritt ohne Rollennennung gehoert fast immer
    // zum selben Aufgabentraeger wie der Schritt davor.
    schritte.forEach(function (s, i) {
      if (s.rolle) return;
      var r = '';
      for (var j = i - 1; j >= 0 && !r; j--) if (schritte[j].rolle) r = schritte[j].rolle;
      for (var k = i + 1; k < schritte.length && !r; k++) if (schritte[k].rolle) r = schritte[k].rolle;
      if (r) s.rolle = r;
    });
    return schritte;
  }

  function aktionsName(schritt) {
    var objekt = (schritt.objekt || '').trim();
    var aktion = (schritt.aktion || 'bearbeiten').trim();
    return (objekt ? objekt.charAt(0).toUpperCase() + objekt.slice(1) + ' ' : '') + aktion;
  }

  // Aus einer Antwort wird eine Aufgabe: "Ablehnung" -> "Ablehnung aussprechen",
  // "Freigabe" -> "Freigabe erteilen".
  function antwortAufgabe(antwort) {
    var a = String(antwort || '').trim().replace(/\s*\([^)]*\)\s*$/, '');
    if (!a) return 'Ergebnis bearbeiten';
    if (/^(ja|nein)$/i.test(a)) return a === 'ja' ? 'Ergebnis bestätigen' : 'Ergebnis verwerfen';
    if (/ablehnung|absage|verworfen/i.test(a)) return a + ' aussprechen';
    if (/freigabe|genehmigung|abnahme|zuschlag|zustimmung/i.test(a)) return a + ' erteilen';
    return a + ' bearbeiten';
  }

  // Rechtwinklige Fuehrung zwischen zwei Kaesten. Gleiche Reihe: gerade.
  // Sonst ueber einen Korridor zwischen den Reihen — eine Linie quer durch die
  // Reihe wuerde alle Kaesten dazwischen durchschneiden.
  function kantenRoute(q, z) {
    var qR = q.x + q.w, qC = q.x + q.w / 2, qB = q.y + q.h;
    var qy = q.y + q.h / 2, zy = z.y + z.h / 2;
    var zL = z.x, zC = z.x + z.w / 2, zT = z.y, zB = z.y + z.h;

    // Gleiche Reihe, Ziel rechts: gerade Linie.
    if (Math.abs(qy - zy) < 6 && zL >= qR) return [[qR, qy], [zL, zy]];

    // Gleiche Reihe, Ziel links: unter der Reihe herum.
    if (Math.abs(qy - zy) < 6) {
      var unten = qB + 14;
      return [[qC, qB], [qC, unten], [zC, unten], [zC, zB]];
    }

    // Senkrecht im Spaltengang neben der Quelle (dort ist in jeder Lane frei),
    // waagerecht erst im Rand der Zielreihe. Frueher lief die Waagerechte ueber
    // die halbe Diagrammbreite und sah wie eine Sammellinie aus.
    var gang = qR + 26;
    if (zT > q.y) {
      return [[qR, qy], [gang, qy], [gang, zT - 14], [zC, zT - 14], [zC, zT]];
    }
    return [[qR, qy], [gang, qy], [gang, zB + 14], [zC, zB + 14], [zC, zB]];
  }

  function prozessXml(nameWunsch, schritte, zusatzLanes) {
    var prozessName = (nameWunsch || '').trim() || 'Extrahierter Prozess';
    var lanes = [];
    var laneIndex = {};
    (zusatzLanes || []).forEach(function (l) {
      if (l && laneIndex[l] == null) { laneIndex[l] = lanes.length; lanes.push(l); }
    });
    schritte.forEach(function (s) {
      // Ohne erkannte Rolle bleibt die Lane sichtbar als offene Frage stehen.
      var rolle = s.rolle || 'Ungeklärt';
      if (laneIndex[rolle] == null) {
        laneIndex[rolle] = lanes.length;
        lanes.push(rolle);
      }
      s._lane = laneIndex[rolle];
    });
    // Reihenfolge = erste Erwaehnung. Eine Umsortierung wuerde den Startknoten
    // in eine Lane weiter unten setzen; der Leser faengt dann in der Mitte an.
    if (!lanes.length) { laneIndex['Ungeklärt'] = 0; lanes.push('Ungeklärt'); }

    var startY = 40;
    var kopfHoehe = 34;
    var zeileHoehe = 150;
    var xStart = 230;
    var spaltenBreite = 200;
    // Kein Zeilenumbruch: der Fluss läuft je Lane strikt von links nach rechts.
    var spaltenProZeile = Math.max(1, Number(window.BPMN_SCHRITTE_PRO_ZEILE) || 999);

    var laneSchritte = lanes.map(function () { return []; });
    schritte.forEach(function (s, i) { (laneSchritte[s._lane] || laneSchritte[0]).push(i); });

    // Zeitachse: die X-Position folgt der Prozessreihenfolge, die Y-Position der
    // Lane. Dadurch laeuft der Fluss immer nach rechts; ein Lane-Wechsel ist
    // nur ein Sprung nach unten, nie zurueck.
    var laneExtra = lanes.map(function () { return 0; });
    schritte.forEach(function (s) {
      if (s.entscheidung && s.entscheidung.length) {
        laneExtra[s._lane] = Math.max(laneExtra[s._lane], (s.entscheidung.length - 1) * 80);
      }
    });
    var laneHoehen = lanes.map(function (_, i) { return zeileHoehe + laneExtra[i]; });
    var laneTop = [];
    var summe = startY;
    lanes.forEach(function (_, i) { laneTop[i] = summe; summe += laneHoehen[i]; });
    var poolHoehe = summe - startY + 12;

    var pos = {};
    var xCursor = xStart;
    schritte.forEach(function (s, i) {
      pos[i] = { x: xCursor, y: laneTop[s._lane] + 40 };
      xCursor += (s.entscheidung && s.entscheidung.length) ? 4 * spaltenBreite : spaltenBreite;
    });
    var breite = Math.max(1000, xCursor + 120);

    var knoten = [];
    var kanten = [];
    var knotenLane = {};
    var taskNamen = {};
    var taskArt = {};
    var gwNamen = {};
    var gwDefault = {};
    var letzter = 'Start_Text';
    var erster = schritte.length ? pos[0] : { x: 230, y: laneTop[0] + kopfHoehe + 40 };
    knoten.push({ id: 'Start_Text', x: 140, y: erster.y + 16, w: 36, h: 36 });
    knotenLane['Start_Text'] = 0;

    var gwNr = 0;
    schritte.forEach(function (s, i) {
      var aufgabeId = 'Task_' + (i + 1);
      var p = pos[i];
      if (s.entscheidung && s.entscheidung.length) {
        // Konvention (Camunda/OMG): erst die Aufgabe, die die Entscheidung
        // verlangt, dann das Gateway, dann je Antwort eine Aufgabe.
        var n = s.entscheidung.length;
        var dSplit = 'Gateway_Split_' + (++gwNr);
        var dJoin = 'Gateway_Merge_' + gwNr;
        gwNamen[dSplit] = (s.frage || 'Entscheidung').replace(/\bentscheiden\b/i, 'entschieden') + '?';
        knoten.push({ id: aufgabeId, x: p.x, y: p.y, w: 120, h: 68 });
        knotenLane[aufgabeId] = s._lane;
        taskNamen[aufgabeId] = s.frage || 'Entscheidung treffen';
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: letzter, z: aufgabeId });
        knoten.push({ id: dSplit, x: p.x + spaltenBreite, y: p.y + 9, w: 50, h: 50 });
        knotenLane[dSplit] = s._lane;
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: aufgabeId, z: dSplit });
        s.entscheidung.forEach(function (antwort, k) {
          var zweigId = aufgabeId + '_' + (k + 1);
          knoten.push({ id: zweigId, x: p.x + 2 * spaltenBreite, y: p.y + k * 80, w: 120, h: 68 });
          knotenLane[zweigId] = s._lane;
          taskNamen[zweigId] = antwortAufgabe(antwort);
          var zweigFlow = 'Flow_' + (kanten.length + 1);
          if (/ablehnung|absage|verworfen/i.test(antwort)) gwDefault[dSplit] = zweigFlow;
          kanten.push({ id: zweigFlow, q: dSplit, z: zweigId, name: antwort });
          if (/ablehnung|absage|verworfen/i.test(antwort)) {
            // Eine Ablehnung beendet den Vorgang; sie laeuft nicht in die
            // normale Fortsetzung zurueck.
            var endAblehnung = 'End_Ablehnung_' + gwNr + '_' + (k + 1);
            knoten.push({ id: endAblehnung, x: p.x + 3 * spaltenBreite, y: p.y + k * 80 + 16, w: 36, h: 36 });
            knotenLane[endAblehnung] = s._lane;
            kanten.push({ id: 'Flow_' + (kanten.length + 1), q: zweigId, z: endAblehnung });
          } else {
            kanten.push({ id: 'Flow_' + (kanten.length + 1), q: zweigId, z: dJoin });
          }
        });
        knoten.push({ id: dJoin, x: p.x + 3 * spaltenBreite, y: p.y + 9 + (n - 1) * 40, w: 50, h: 50 });
        knotenLane[dJoin] = s._lane;
        letzter = dJoin;
        return;
      }
      if (s.bedingung) {
        var split = 'Gateway_Split_' + (++gwNr);
        var merge = 'Gateway_Merge_' + gwNr;
        knoten.push({ id: split, x: p.x - 85, y: p.y - 9, w: 50, h: 50 });
        knotenLane[split] = s._lane;
        knoten.push({ id: aufgabeId, x: p.x, y: p.y, w: 120, h: 68 });
        knotenLane[aufgabeId] = s._lane;
        taskNamen[aufgabeId] = aktionsName(s);
        knoten.push({ id: merge, x: p.x + 160, y: p.y - 9, w: 50, h: 50 });
        knotenLane[merge] = s._lane;
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: letzter, z: split });
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: split, z: aufgabeId, bedingung: s.bedingung });
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: split, z: merge, name: 'andernfalls' });
        kanten.push({ id: 'Flow_' + (kanten.length + 1), q: aufgabeId, z: merge });
        letzter = merge;
        return;
      }
      knoten.push({ id: aufgabeId, x: p.x, y: p.y, w: 120, h: 68 });
      knotenLane[aufgabeId] = s._lane;
      taskNamen[aufgabeId] = aktionsName(s);
      if (/^(erhalten|empfangen|entgegennehmen)$/i.test(s.aktion || '')) taskArt[aufgabeId] = 'receive';
      kanten.push({ id: 'Flow_' + (kanten.length + 1), q: letzter, z: aufgabeId });
      letzter = aufgabeId;
    });

    var letzterIdx = schritte.length - 1;
    var letzteLane = schritte.length ? schritte[letzterIdx]._lane : 0;
    var letzteP = schritte.length ? pos[letzterIdx] : { x: 230, y: laneTop[0] + kopfHoehe + 40, zeile: 0 };
    var endX = letzteP.x + 190;
    knoten.push({ id: 'End_Text', x: endX, y: letzteP.y + 16, w: 36, h: 36 });
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
    knoten.forEach(function (k) {
      if (!/^Task_/.test(k.id)) return;
      var tag = taskArt[k.id] === 'receive' ? 'bpmn:receiveTask' : 'bpmn:userTask';
      xml.push('<' + tag + ' id="' + k.id + '" name="' + esc(taskNamen[k.id] || 'Aufgabe') + '" />');
    });
    xml.push('<bpmn:endEvent id="End_Text" name="' + esc(prozessName) + ' abgeschlossen" />');
    knoten.forEach(function (k) {
      if (/^End_Ablehnung_/.test(k.id)) {
        xml.push('<bpmn:endEvent id="' + k.id + '" name="Antrag abgelehnt" />');
      }
    });
    // Ohne diesen Block existieren die Gateways nur als Zeichnung: die Fluesse
    // zeigen dann auf Elemente, die es im Modell nicht gibt.
    knoten.forEach(function (k) {
      if (/^Gateway_(Split|Merge)_/.test(k.id)) {
        var gName = gwNamen[k.id] ? ' name="' + esc(gwNamen[k.id]) + '"' : '';
        var gDef = gwDefault[k.id] ? ' default="' + gwDefault[k.id] + '"' : '';
        xml.push('<bpmn:exclusiveGateway id="' + k.id + '"' + gName + gDef + ' />');
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
    xml.push('<bpmndi:BPMNShape id="Participant_Text_di" bpmnElement="Participant_Text" isHorizontal="true"><dc:Bounds x="60" y="' +
      startY + '" width="' + breite + '" height="' + poolHoehe + '" /></bpmndi:BPMNShape>');
    // Die Lane beginnt erst hinter dem Pool-Band: sonst verdeckt sie die
    // Pool-Beschriftung und der Rahmen ist nicht mehr als Pool zu erkennen.
    var laneX = 90;
    lanes.forEach(function (lane, i) {
      xml.push('<bpmndi:BPMNShape id="Lane_Text_' + (i + 1) + '_di" bpmnElement="Lane_Text_' + (i + 1) +
        '" isHorizontal="true"><dc:Bounds x="' + laneX + '" y="' + laneTop[i] +
        '" width="' + (breite - 30) + '" height="' + laneHoehen[i] + '" /></bpmndi:BPMNShape>');
    });
    knoten.forEach(function (k) {
      xml.push('<bpmndi:BPMNShape id="' + k.id + '_di" bpmnElement="' + k.id + '"><dc:Bounds x="' + k.x +
        '" y="' + k.y + '" width="' + k.w + '" height="' + k.h + '" /></bpmndi:BPMNShape>');
    });
    kanten.forEach(function (k) {
      var q = knoten.filter(function (n) { return n.id === k.q; })[0];
      var z = knoten.filter(function (n) { return n.id === k.z; })[0];
      if (!q || !z) return;
      var punkte = kantenRoute(q, z);
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
      var rollen = new Set(schritte.map(function (s) { return s.rolle || 'Bearbeitung'; })).size;
      protokoll = [wahl.hinweis].concat(['Aus Text: ' + schritte.length + ' Schritt(e), ' + rollen + ' Rolle(n) als Lanes.']).filter(function (z) { return !!z; });
      protokolliere('Alle Elemente sind Vorschläge — bitte fachlich prüfen (Sicherheitsgrad "unsicher").');
      if (rollen === 1 && schritte.length > 20) {
        protokolliere('Nur eine Rolle erkannt: das Modell liegt in einer einzigen Lane ('
          + schritte.length + ' Schritte). Für mehrere Lanes je Schritt eine Rolle angeben '
          + 'oder die KI-Extraktion (Häkchen „KI") verwenden.');
      }
      zeichneProtokoll();
      $('reiter-protokoll').click();
      pruefe();
      canvasUebersicht();
    }).catch(function (fehler) {
      ausgabe('Der Text konnte nicht in BPMN übersetzt werden: ' + fehler.message, 'Extraktion fehlgeschlagen');
    });
  }

  function kiDialogOeffnen() {
    $('ki-status').hidden = true;
    // Im Serverbetrieb liegen Schlüssel und Modell beim Dienst — die Felder
    // würden nur verwirren.
    if ($('ki-zugang')) $('ki-zugang').hidden = !!window.BPMN_KI_DIENST;
    try {
      if (!$('ki-url').value) $('ki-url').value = localStorage.getItem('bpmn-ki-url') || '';
      if (!$('ki-modell').value) $('ki-modell').value = localStorage.getItem('bpmn-ki-modell') || '';
    } catch (e) { /* privater Modus: nichts gemerkt */ }
    $('ki-dialog').showModal();
  }

  // Aktuellen Stand als Schrittliste lesen — Grundlage für die Weiterarbeit.
  // Die Reihenfolge folgt den Sequenzflüssen ab dem Startereignis; nicht
  // erreichbare Aufgaben hängen hinten an, damit nichts verloren geht.
  function modellAlsSchritte() {
    var registry = modeler.get('elementRegistry');
    var alleElemente = registry.getAll();
    var participant = alleElemente.filter(function (e) { return e.type === 'bpmn:Participant'; })[0];
    var aufgaben = alleElemente.filter(istAufgabe);
    var start = alleElemente.filter(function (e) { return e.type === 'bpmn:StartEvent'; })[0];

    // Erste Lane als Rückfall: eine Aufgabe ohne Lane-Zuordnung soll keine
    // zusätzliche Lane "Bearbeitung" erzeugen.
    var ersteLane = (alleElemente.filter(function (e) { return e.type === 'bpmn:Lane'; })[0]);
    var rueckfall = ersteLane ? name(ersteLane) : 'Bearbeitung';

    var schritte = [];
    var besucht = {};
    var aktuell = start;
    while (aktuell && !besucht[aktuell.id]) {
      besucht[aktuell.id] = true;
      var laneJetzt = laneVon(aktuell);
      var rolleJetzt = laneJetzt ? name(laneJetzt) : rueckfall;
      if (istAufgabe(aktuell)) {
        schritte.push({ rolle: rolleJetzt, aktion: name(aktuell) || 'bearbeiten', objekt: '', bedingung: '' });
      } else if (aktuell.type === 'bpmn:ExclusiveGateway') {
        // Gateways muessen den Umbau ueberleben, sonst verschwinden sie beim
        // naechsten Weiterarbeiten.
        var aus = (aktuell.outgoing || []).filter(function (c) { return c.type === 'bpmn:SequenceFlow'; });
        if (aus.length > 1) {
          schritte.push({
            rolle: rolleJetzt, aktion: 'entscheiden', objekt: 'Entscheidung',
            entscheidung: aus.map(function (c) { return name(c) || 'Ausgang'; }),
            bedingung: ''
          });
        }
      }
      var kante = (aktuell.outgoing || []).filter(function (c) {
        return c.type === 'bpmn:SequenceFlow';
      })[0];
      aktuell = kante ? kante.target : null;
    }
    aufgaben.forEach(function (t) {
      var schon = schritte.some(function (s) { return s.aktion === (name(t) || 'bearbeiten'); });
      if (!schon) {
        var lane = laneVon(t);
        schritte.push({ rolle: lane ? name(lane) : rueckfall, aktion: name(t) || 'bearbeiten', objekt: '', bedingung: '' });
      }
    });

    // Lanes ohne Aufgabe mitgeben, damit sie beim Umbau nicht verloren gehen.
    var alleLanes = alleElemente.filter(function (e) { return e.type === 'bpmn:Lane'; })
      .map(function (l) { return name(l); });
    var benutzt = {};
    schritte.forEach(function (s) { benutzt[s.rolle.toLowerCase()] = true; });
    var leer = alleLanes.filter(function (l) { return l && !benutzt[l.toLowerCase()]; });

    return { prozess: participant ? name(participant) : '', schritte: schritte, leerLanes: leer };
  }

  // Operationen der KI auf den bestehenden Stand anwenden. Die KI liefert nur
  // Änderungsabsichten; ausgeführt wird hier — so kann sie nichts überschreiben,
  // was sie nicht ausdrücklich ändern soll.
  function schrittFinden(schritte, name) {
    var gesucht = String(name || '').trim().toLowerCase();
    if (!gesucht) return null;
    for (var i = 0; i < schritte.length; i++) {
      if (schritte[i].aktion.toLowerCase() === gesucht) return schritte[i];
    }
    for (var j = 0; j < schritte.length; j++) {
      if (schritte[j].aktion.toLowerCase().indexOf(gesucht) !== -1) return schritte[j];
    }
    return null;
  }

  function wendeOperationenAn(stand, antwort) {
    var schritte = stand.schritte.map(function (s) {
      return {
        rolle: s.rolle, aktion: s.aktion, objekt: s.objekt || '', bedingung: s.bedingung || '',
        entscheidung: s.entscheidung || null
      };
    });
    var leer = (stand.leerLanes || []).slice();
    var prozess = String(antwort.prozess || stand.prozess || '').trim();
    var bericht = [];

    (antwort.operationen || []).forEach(function (op) {
      var art = String(op.op || '').toLowerCase();
      if (art === 'lane_hinzufuegen' && op.name) {
        if (leer.indexOf(op.name) === -1) leer.push(op.name);
        bericht.push('Lane "' + op.name + '" ergänzt');
      } else if (art === 'lane_umbenennen' && op.lane && op.neu) {
        var alt = op.lane.toLowerCase();
        schritte.forEach(function (s) { if (s.rolle.toLowerCase() === alt) s.rolle = op.neu; });
        leer = leer.map(function (l) { return l.toLowerCase() === alt ? op.neu : l; });
        bericht.push('Lane "' + op.lane + '" → "' + op.neu + '"');
      } else if (art === 'pool_umbenennen' && op.name) {
        prozess = op.name;
        bericht.push('Pool → "' + op.name + '"');
      } else if (art === 'schritt_verschieben' && op.schritt && op.lane) {
        var ziel = schrittFinden(schritte, op.schritt);
        if (ziel) {
          ziel.rolle = op.lane;
          leer = leer.filter(function (l) { return l !== op.lane; });
          bericht.push('"' + ziel.aktion + '" → Lane "' + op.lane + '"');
        }
      } else if (art === 'schritt_umbenennen' && op.schritt && op.neu) {
        var um = schrittFinden(schritte, op.schritt);
        if (um) { bericht.push('"' + um.aktion + '" → "' + op.neu + '"'); um.aktion = op.neu; }
      } else if (art === 'schritt_loeschen' && op.schritt) {
        var weg = schrittFinden(schritte, op.schritt);
        if (weg) {
          schritte = schritte.filter(function (s) { return s !== weg; });
          bericht.push('"' + weg.aktion + '" entfernt');
        }
      } else if (art === 'gateway_hinzufuegen' && op.schritt) {
        var g = schrittFinden(schritte, op.schritt);
        if (g) {
          // Der Schritt bleibt bestehen; der Entscheidungspunkt kommt DAHINTER.
          // Ein Gateway ersetzt keine Aufgabe.
          var ausgaenge = (op.ausgaenge && op.ausgaenge.length ? op.ausgaenge : ['ja', 'nein']);
          schritte.splice(schritte.indexOf(g) + 1, 0, {
            rolle: g.rolle, aktion: 'entscheiden', objekt: 'Entscheidung',
            entscheidung: ausgaenge, bedingung: ''
          });
          bericht.push('Entscheidung nach "' + g.aktion + '": ' + ausgaenge.join(' / '));
        }
      } else if (art === 'gateway_entfernen' && op.schritt) {
        var ge = schrittFinden(schritte, op.schritt);
        if (ge && ge.entscheidung) {
          ge.entscheidung = null;
          bericht.push('Entscheidung bei "' + ge.aktion + '" entfernt');
        }
      } else if (art === 'schritt_hinzufuegen' && op.aktion) {
        var neu = { rolle: op.lane || 'Bearbeitung', aktion: op.aktion, objekt: op.objekt || '', bedingung: op.bedingung || '' };
        var anker = op.nach ? schrittFinden(schritte, op.nach) : null;
        var pos = anker ? schritte.indexOf(anker) + 1 : schritte.length;
        schritte.splice(pos, 0, neu);
        bericht.push('"' + op.aktion + '" eingefügt');
      }
    });

    return { prozess: prozess, schritte: schritte, leerLanes: leer, bericht: bericht };
  }

  var KI_REGELN = 'Antworte ausschließlich mit einem JSON-Objekt der Form '
    + '{"prozess":"...","schritte":[{"rolle":"...","aktion":"...","objekt":"...","bedingung":"..."}]}. '
    + 'Jeder Schritt braucht eine Rolle (Aufgabenträger) — sie bestimmt die Lane; '
    + 'ohne Rolle entsteht keine Lane. Aktion im Infinitiv. Kein Markdown, keine Erklärung.';

  function kiExtrahieren(weiter) {
    // Serverbetrieb: der Schluessel liegt beim Server, der Browser schickt nur Text.
    var dienst = window.BPMN_KI_DIENST || '';
    var basis = $('ki-url').value.trim().replace(/\/+$/, '');
    var modell = $('ki-modell').value.trim();
    var key = $('ki-key').value;
    var text = $('ki-eingabe').value.trim();
    var status = $('ki-status');
    if (!dienst) {
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
    }
    if (!text && !weiter) {
      status.hidden = false;
      status.className = 'warnung fehler';
      status.textContent = 'Bitte einen Text eingeben.';
      return;
    }
    var auftrag = $('ki-auftrag') ? $('ki-auftrag').value.trim() : '';
    var stand = null;
    var nachrichten;
    if (weiter) {
      stand = modellAlsSchritte();
      if (!stand.schritte.length) {
        status.hidden = false;
        status.className = 'warnung fehler';
        status.textContent = 'Es gibt noch keinen Prozess zum Weiterarbeiten. Bitte zuerst einen Text auswerten oder ein BPMN laden.';
        return;
      }
      if (!auftrag) {
        status.hidden = false;
        status.className = 'warnung fehler';
        status.textContent = 'Bitte den Änderungsauftrag eintragen — z. B. „Lane Poststelle ergänzen".';
        return;
      }
      nachrichten = [
        { role: 'system', content:
            'Du bist Prozessanalyst und änderst einen bestehenden Prozess. Antworte ausschließlich mit JSON dieser Form: '
            + '{"prozess":"Poolname","hinweis":"kurz, was du geändert hast","operationen":[ ... ]}. '
            + 'Erlaubte Operationen: '
            + '{"op":"lane_hinzufuegen","name":"..."} | '
            + '{"op":"lane_umbenennen","lane":"...","neu":"..."} | '
            + '{"op":"pool_umbenennen","name":"..."} | '
            + '{"op":"schritt_verschieben","schritt":"...","lane":"..."} | '
            + '{"op":"schritt_umbenennen","schritt":"...","neu":"..."} | '
            + '{"op":"schritt_loeschen","schritt":"..."} | '
            + '{"op":"schritt_hinzufuegen","lane":"...","aktion":"...","nach":"..."} | '
            + '{"op":"gateway_hinzufuegen","schritt":"...","ausgaenge":["ja","nein"]} | '
            + '{"op":"gateway_entfernen","schritt":"..."}. '
            + 'Führe nur aus, was der Auftrag verlangt; alles andere bleibt unangetastet. '
            + 'Nenne Schritte exakt so, wie sie im Stand stehen. Erfinde keine Schritte.' },
        { role: 'user', content: 'Bisheriger Stand:\n' + JSON.stringify(stand)
            + '\n\nÄnderungsauftrag: ' + auftrag }
      ];
    } else {
      var textStand = text;
      nachrichten = [
        { role: 'system', content: KI_REGELN + ' Du leitest den Prozess ausschließlich aus dem Text ab. '
            + 'Erfinde nichts, was nicht im Text steht.' },
        { role: 'user', content: textStand }
      ];
    }

    var endpoint = dienst || (/\/chat\/completions$/.test(basis) ? basis : basis + '/chat/completions');
    var anfrageKopf = { 'Content-Type': 'application/json' };
    if (!dienst) anfrageKopf['Authorization'] = 'Bearer ' + key;
    status.hidden = false;
    status.className = 'warnung';
    status.textContent = 'Anfrage läuft …';
    fetch(endpoint, {
      method: 'POST',
      headers: anfrageKopf,
      body: JSON.stringify({
        model: modell || undefined,
        temperature: 0,
        response_format: { type: 'json_object' },
        messages: nachrichten
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

      // Weiterarbeit: die KI liefert Operationen, ausgeführt wird lokal.
      if (weiter && Array.isArray(json.operationen)) {
        var ergebnis = wendeOperationenAn(stand, json);
        if (!ergebnis.schritte.length) throw new Error('Nach den Änderungen bliebe kein Schritt übrig');
        var neuerPool = String(json.prozess || '').trim() || $('ki-name').value.trim() || '';
        var xmlWeiter = prozessXml(neuerPool, ergebnis.schritte, ergebnis.leerLanes);
        $('ki-dialog').close();
        importieren(xmlWeiter).then(function () {
          protokoll = ['KI-Änderung: ' + (ergebnis.bericht.length ? ergebnis.bericht.join('; ') : 'keine Änderung erkannt')
            + (json.hinweis ? ' — ' + json.hinweis : '')];
          zeichneProtokoll();
          $('reiter-protokoll').click();
          pruefe();
        });
        return;
      }

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
      var eingabeName = $('ki-name') ? $('ki-name').value.trim() : '';
      var kiName = (json.prozess || '').trim();
      var poolName = (weiter ? [kiName, eingabeName] : [eingabeName, kiName])
        .concat([$('text-name') ? $('text-name').value.trim() : '']).filter(Boolean)[0] || '';
      var xml = prozessXml(poolName, schritte);
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
    $('ki-starten').addEventListener('click', function () { kiExtrahieren(false); });
    $('ki-weiter').addEventListener('click', function () { kiExtrahieren(true); });
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
    if (window.BPMN_KI_DIENST) {
      ['ki-url', 'ki-modell', 'ki-key'].forEach(function (id) {
        var feld = $(id);
        if (!feld) return;
        var huelle = feld.closest('.feld');
        if (huelle) huelle.hidden = true;
      });
      var hinweis = document.querySelector('#ki-dialog .warnung');
      if (hinweis) {
        hinweis.textContent = 'Diese Installation nutzt den Schlüssel des Servers. Der Browser sieht ihn nicht; '
          + 'jede Anfrage läuft über den angemeldeten Zugang. Keine dienstlichen oder personenbezogenen Daten senden.';
      }
    }

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
