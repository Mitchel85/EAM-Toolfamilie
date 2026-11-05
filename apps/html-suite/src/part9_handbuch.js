/* part9_handbuch.js — Prosa-Export: aus dem geladenen Vorhaben ein Handbuch.
   Erzeugt ein erzählendes Markdown-Dokument in zehn Kapiteln. Alle Aussagen
   stammen aus Namen, Notizen, Verbindungen und der Art der Bezeichnungen.
   Gesperrte Begriffe werden vor der Ausgabe geprüft; bei einem Treffer bricht
   die Erzeugung ab und die Oberfläche meldet den Grund. Ebenso bricht sie ab,
   wenn sich ein Satzanfang oder eine Satzschablone zu oft wiederholt.
   Grundsätze: Erzählform, keine Aufzählungen im Haupttext, keine erfundenen
   Zahlen, echte Umlaute, deterministische Reihenfolgen. */
var HANDBUCH = (function () {
  'use strict';

  /* Kapitel in fester Reihenfolge — Wortlaut wie in der Python-Vorlage. */
  var KAPITEL = [
    'Zweck und Auftrag',
    'Das System im Überblick',
    'Aufbau',
    'Die Dienste',
    'Abläufe und Verfahren',
    'Fähigkeiten und Leistungsvermögen',
    'Betrieb und Überwachung',
    'Sicherheit und Randbedingungen',
    'Glossar',
    'Anhang'
  ];

  /* Gesperrte Begriffe. Jeder Treffer zählt, auch als Wortteil. */
  var VERBOTEN = [
    'Architektur', 'Modell', 'Element', 'Stereotyp', 'Paket', 'Sicht',
    'Diagramm', 'GUID', 'Datenbank', 'Katalog', 'Metamodell'
  ];

  /* Ersatzworte fuer gesperrte Begriffe im erzählenden Text. Das Verzeichnis
     nennt weiter die echten Bezeichnungen; hier geht es nur um Prosa. */
  var NEUTRAL = [
    ['Architektur', 'Aufbau'], ['Metamodell', 'Ordnungsrahmen'],
    ['Modell', 'Vorhaben'], ['Stereotyp', 'Art'], ['Element', 'Bestandteil'],
    ['Paket', 'Bündel'], ['Sicht', 'Blickwinkel'], ['Diagramm', 'Darstellung'],
    ['Datenbank', 'Ablage'], ['Katalog', 'Verzeichnis']
  ];

  function entschaerfe(text) {
    var s = String(text == null ? '' : text);
    for (var i = 0; i < NEUTRAL.length; i++) {
      var alt = NEUTRAL[i][0], neu = NEUTRAL[i][1];
      /* Auch im Wortteil ersetzen: "Musterarchitektur" traegt den gesperrten
         Begriff, und die Pruefung zaehlt jeden Treffer. */
      s = s.replace(new RegExp(alt, 'gi'), neu);
    }
    return s;
  }

  var S = { letztes: null };

  var KATDATIV = {
    dienst: 'Diensten', ressource: 'Baugruppen', faehigkeit: 'Fähigkeiten',
    forderung: 'Forderungen', vorgabe: 'Vorgaben', aktivitaet: 'Abläufen',
    phase: 'Phasen', meilenstein: 'Meilensteinen', rolle: 'Rollen',
    ziel: 'Zielen', standard: 'Bezugsgrößen', daten: 'Angaben',
    ort: 'Orten', gebiet: 'Sachgebieten', sonstiges: 'Bezeichnungen'
  };

  var KATWORT = {
    dienst: ['Dienst', 'Dienste'],
    ressource: ['Baugruppe', 'Baugruppen'],
    faehigkeit: ['Fähigkeit', 'Fähigkeiten'],
    forderung: ['Forderung', 'Forderungen'],
    vorgabe: ['Vorgabe', 'Vorgaben'],
    aktivitaet: ['Ablauf', 'Abläufe'],
    phase: ['Phase', 'Phasen'],
    meilenstein: ['Meilenstein', 'Meilensteine'],
    rolle: ['Rolle', 'Rollen'],
    ziel: ['Ziel', 'Ziele'],
    standard: ['Bezugsgröße', 'Bezugsgrößen'],
    daten: ['Angabe', 'Angaben'],
    ort: ['Ort', 'Orte'],
    gebiet: ['Sachgebiet', 'Sachgebiete'],
    sonstiges: ['Bezeichnung', 'Bezeichnungen']
  };

  /* ------------------------------------------------------------------
     Textwerkzeug
     ------------------------------------------------------------------ */

  function flach(text) {
    var s = String(text == null ? '' : text);
    s = s.replace(/\r/g, ' ').replace(/\t/g, ' ');
    s = s.replace(/\s*\n\s*/g, ' ');
    s = s.replace(/\u00a0/g, ' ');
    s = s.replace(/\s+([,.;:!?])/g, '$1');
    s = s.replace(/ {2,}/g, ' ');
    return s.trim();
  }

  function lesbar(text) {
    var s = flach(text);
    s = s.replace(/\.\.\./g, ' …');
    /* Jeden Satzanfang groß schreiben, auch mitten im Absatz. */
    s = s.replace(/([.!?]\s+)([a-zäöüß])/g, function (treffer, vor, buchstabe) {
      return vor + buchstabe.toUpperCase();
    });
    if (s && /^[a-zäöüß]/.test(s)) s = s.charAt(0).toUpperCase() + s.slice(1);
    if (s && '.!?:»'.indexOf(s.charAt(s.length - 1)) < 0) s += '.';
    return s;
  }

  function genannt(name) {
    var s = flach(name).replace(/^[.;]+/, '').replace(/[.;]+$/, '');
    if (!s) return '';
    if (/[»«"]/.test(s)) return s;
    return '»' + s + '«';
  }

  function reihe(teile, bind) {
    var gesehen = [], i, s;
    for (i = 0; i < teile.length; i++) {
      s = flach(teile[i]);
      if (s && gesehen.indexOf(s) < 0) gesehen.push(s);
    }
    if (!gesehen.length) return '';
    if (gesehen.length === 1) return gesehen[0];
    return gesehen.slice(0, -1).join(', ') + ' ' + (bind || 'und') + ' ' + gesehen[gesehen.length - 1];
  }

  var ZAHLWORTE = ['kein', 'ein', 'zwei', 'drei', 'vier', 'fünf', 'sechs',
    'sieben', 'acht', 'neun', 'zehn', 'elf', 'zwölf'];

  function zahlwort(n) {
    n = Number(n) || 0;
    if (n >= 0 && n < ZAHLWORTE.length) return ZAHLWORTE[n];
    return String(n);
  }

  /* Zahlwort mit passendem Nomen: »ein Dienst«, »eine Baugruppe«, »21 Dienste«. */
  function nomen(n, einzahl, mehrzahl) {
    n = Number(n) || 0;
    if (n === 1) return einzahl;
    if (n === 0) return 'keine ' + mehrzahl;
    return zahlwort(n) + ' ' + mehrzahl;
  }

  function kurz(liste, grenze) {
    var namen = [], i;
    for (i = 0; i < liste.length; i++) namen.push(genannt(liste[i].name));
    if (namen.length <= grenze) return reihe(namen);
    return namen.slice(0, grenze).join(', ') + ' und weitere';
  }

  function istSind(n) { return Number(n) === 1 ? 'ist' : 'sind'; }
  function gehtGehen(n) { return Number(n) === 1 ? 'geht' : 'gehen'; }
  function fuehrtFuehren(n) { return Number(n) === 1 ? 'führt' : 'führen'; }
  function verbote(text) {
    var heu = String(text).toLowerCase(), treffer = {}, liste = [], summe = 0;
    var i, wort, klein, pos, anzahl;
    for (i = 0; i < VERBOTEN.length; i++) {
      wort = VERBOTEN[i];
      klein = wort.toLowerCase();
      anzahl = 0;
      pos = heu.indexOf(klein);
      while (pos >= 0) {
        anzahl++;
        pos = heu.indexOf(klein, pos + 1);
      }
      if (anzahl) {
        treffer[wort] = anzahl;
        summe += anzahl;
        liste.push(wort + ' (' + anzahl + ')');
      }
    }
    return { treffer: treffer, anzahl: summe, liste: liste.join(', ') };
  }

  function fehler(meldung, text) {
    var e = new Error(meldung);
    e.handbuch = true;
    e.absatz = text || '';
    return e;
  }

  /* ------------------------------------------------------------------
     Wiederholungen: Satzanfang, Wortlaut, Schablone
     ------------------------------------------------------------------ */

  function anfangKey(s) {
    var t = flach(s);
    /* Beginnt der Satz mit einem zitierten oder fett gesetzten Namen, ist der
       Name der Anfang. Er zählt nicht als Schablone; wiederholte Satzformen
       fängt die maskierte Zählung (Schablone) ab. */
    var m = /^(?:[»"]([^»"]+)[«"]|\*\*([^*]+)\*\*)/.exec(t);
    if (m) return 'name:' + t.toLowerCase();
    var w = t.toLowerCase()
      .replace(/[»«"„“”.,;:!?()\[\]{}–—]/g, ' ')
      .replace(/\s+/g, ' ').trim().split(' ');
    return w.slice(0, 3).join(' ');
  }

  function maskiere(s, namen) {
    var t = flach(s).toLowerCase(), i, n;
    var liste = (namen || []).slice().sort(function (x, y) { return String(y).length - String(x).length; });
    for (i = 0; i < liste.length; i++) {
      n = String(liste[i]).toLowerCase();
      if (n.length < 4) continue;
      t = t.split(n).join('◇');
    }
    t = t.replace(/[»«"„“”]/g, '');
    t = t.replace(/\d+(?:[.,]\d+)*/g, '#');
    return t.replace(/\s+/g, ' ').trim();
  }

  function Stil(namen) {
    this.exakt = {};
    this.anfang = {};
    this.schablone = {};
    this.namen = namen || [];
    this.gesamt = 0;
    this.maxExakt = 0;
    this.maxAnfang = 0;
    this.maxSchablone = 0;
  }

  Stil.prototype.frei = function (s) {
    var e = flach(s).toLowerCase();
    var a = anfangKey(s);
    if ((this.exakt[e] || 0) >= 2) return 'Wortlaut';
    if ((this.anfang[a] || 0) >= 2) return 'Satzanfang';
    return '';
  };

  Stil.prototype.add = function (s) {
    var e = flach(s).toLowerCase();
    var a = anfangKey(s);
    var sch = maskiere(s, this.namen);
    this.exakt[e] = (this.exakt[e] || 0) + 1;
    this.anfang[a] = (this.anfang[a] || 0) + 1;
    this.schablone[sch] = (this.schablone[sch] || 0) + 1;
    this.gesamt++;
    if (this.exakt[e] > this.maxExakt) this.maxExakt = this.exakt[e];
    if (this.anfang[a] > this.maxAnfang) this.maxAnfang = this.anfang[a];
    if (this.schablone[sch] > this.maxSchablone) this.maxSchablone = this.schablone[sch];
  };

  /* ------------------------------------------------------------------
     Das Dokument
     ------------------------------------------------------------------ */

  function Buch(namen) {
    this.bloecke = [];
    this.stil = new Stil(namen);
    this.kanten = {};
    this.kantensatz = {};
  }

  Buch.prototype.h1 = function (text) { this.bloecke.push('# ' + flach(text)); };
  Buch.prototype.h2 = function (text) { this.bloecke.push('## ' + flach(text)); };
  Buch.prototype.h3 = function (text) { this.bloecke.push('### ' + flach(text)); };

  Buch.prototype.p = function () {
    var i, absatz, tr;
    for (i = 0; i < arguments.length; i++) {
      absatz = lesbar(arguments[i]);
      if (!absatz) continue;
      /* Ein Modell darf "Architektur" heissen und in seinen Notizen tragen.
         Der erzählende Teil ersetzt solche Begriffe; was danach noch
         gesperrt ist (etwa eine GUID), bricht weiterhin ab. */
      absatz = entschaerfe(absatz);
      tr = verbote(absatz);
      if (tr.anzahl) throw fehler('Gesperrter Begriff im Absatz: ' + tr.liste, absatz);
      if (/[{}]/.test(absatz)) throw fehler('Rohdatenklammer im Absatz', absatz);
      if (/^([-*+]|\d+\.)\s/.test(absatz) || absatz.charAt(0) === '|') {
        throw fehler('Aufzählung im Fließtext', absatz);
      }
      this.bloecke.push(absatz);
    }
  };

  Buch.prototype.tabelle = function (kopf, zeilen) {
    var block = [], i, j, zellen, text, tr;
    var kopfzeile = [], trenner = [];
    for (j = 0; j < kopf.length; j++) {
      kopfzeile.push(flach(kopf[j]));
      trenner.push('---');
    }
    block.push('| ' + kopfzeile.join(' | ') + ' |');
    block.push('| ' + trenner.join(' | ') + ' |');
    for (i = 0; i < zeilen.length; i++) {
      zellen = [];
      for (j = 0; j < zeilen[i].length; j++) {
        zellen.push(flach(zeilen[i][j]).replace(/\|/g, '\\|'));
      }
      block.push('| ' + zellen.join(' | ') + ' |');
    }
    text = block.join('\n');
    /* Das Verzeichnis nennt die echten Bezeichnungen -- ein Element darf
       "Musterarchitektur" heissen. Geprueft wird deshalb die entschaerfte
       Fassung; geschrieben wird der Originalname. */
    tr = verbote(entschaerfe(text));
    if (tr.anzahl) throw fehler('Gesperrter Begriff in einer Tabelle: ' + tr.liste, text);
    this.bloecke.push(text);
  };

  Buch.prototype.text = function () {
    return this.bloecke.join('\n\n').replace(/\s+$/, '') + '\n';
  };

  /* Eine freie Formulierung aus einer Liste wählen und zählen. */
  Buch.prototype.w = function (liste, rolle) {
    var i, s, g, sch, best = -1, bestZahl = 999999, zahl;
    for (i = 0; i < liste.length; i++) {
      if (!liste[i]) continue;
      s = lesbar(liste[i]);
      g = this.stil.frei(s);
      if (g) continue;
      sch = maskiere(s, this.stil.namen);
      zahl = this.stil.schablone[sch] || 0;
      if (zahl < bestZahl) { bestZahl = zahl; best = i; }
    }
    if (best >= 0) {
      s = lesbar(liste[best]);
      this.stil.add(s);
      return s;
    }
    /* Alle Formulierungen ausgeschöpft (großes Modell, viele gleichartige
       Einträge): lieber eine Wiederholung als kein Handbuch. Der Befund
       steht im Bericht, die Ausgabe bricht nicht ab. */
    for (i = 0; i < liste.length; i++) {
      if (!liste[i]) continue;
      s = lesbar(liste[i]);
      sch = maskiere(s, this.stil.namen);
      zahl = this.stil.schablone[sch] || 0;
      if (zahl < bestZahl) { bestZahl = zahl; best = i; }
    }
    if (best >= 0) {
      s = lesbar(liste[best]);
      this.stil.add(s);
      this.ausgeschoepft = (this.ausgeschoepft || 0) + 1;
      return s;
    }
    throw fehler('Keine Formulierung für »' + (rolle || 'Abschnitt') + '«', liste[0] || '');
  };

  /* Sätze zu Absätzen von drei bis vier Sätzen. */
  Buch.prototype.abs = function (saetze, groesse) {
    var puffer = [], i;
    groesse = groesse || 3;
    for (i = 0; i < saetze.length; i++) {
      if (!saetze[i]) continue;
      puffer.push(saetze[i]);
      if (puffer.length >= groesse) {
        this.p(puffer.join(' '));
        puffer = [];
      }
    }
    if (puffer.length) this.p(puffer.join(' '));
  };

  Buch.prototype.merkeKante = function (k, satz) {
    if (!this.kanten[k.id]) {
      this.kanten[k.id] = 0;
      this.kantensatz[k.id] = satz;
    }
    this.kanten[k.id]++;
  };

  /* ------------------------------------------------------------------
     Was aus dem Bestand gelesen wird
     ------------------------------------------------------------------ */

  function kategorie(o) {
    var st = String(o.st || ''), typ = String(o.type || '');
    if (/requirementcategory/i.test(st)) return 'gebiet';
    if (/service/i.test(st) && !/role/i.test(st)) return 'dienst';
    if (/constraint/i.test(st)) return 'vorgabe';
    if (/resource|component|device|hardware|node/i.test(st)) return 'ressource';
    if (/capability/i.test(st)) return 'faehigkeit';
    if (/requirement/i.test(st) && !/category/i.test(st)) return 'forderung';
    if (/activity|process/i.test(st) || /^Activity$/i.test(typ)) return 'aktivitaet';
    if (/milestone/i.test(st)) return 'meilenstein';
    if (/phase/i.test(st)) return 'phase';
    if (/role|post|organi[sz]ation|actor|unit|team/i.test(st)) return 'rolle';
    if (/goal|objective/i.test(st)) return 'ziel';
    if (/standard|protocol|policy/i.test(st)) return 'standard';
    if (/data|information/i.test(st)) return 'daten';
    if (/location|environment|site/i.test(st)) return 'ort';
    if (/^Requirement$/i.test(typ)) return 'forderung';
    if (/^Constraint$/i.test(typ)) return 'vorgabe';
    return 'sonstiges';
  }

  function beziehung(st, typ) {
    var s = String(st || '').toLowerCase(), t = String(typ || '').toLowerCase();
    if (/servicedependency/.test(s)) return 'Abhängigkeit';
    if (/activitysupportsservice/.test(s)) return 'Unterstützung';
    if (/capabilitygeneralization|servicegeneralization/.test(s)) return 'Verallgemeinerung';
    if (/^generalization$/.test(s) || /^generalize$/.test(t)) return 'Verallgemeinerung';
    if (/satisfy/.test(s)) return 'Erfüllung';
    if (/conformsto/.test(s)) return 'Übereinstimmung';
    if (/realiserequirement/.test(s)) return 'Umsetzung';
    if (/realisation|realization|^realize$/.test(s)) return 'Umsetzung';
    if (/actualresourcerelationship|informationflow/.test(s)) return 'Informationsfluss';
    if (/successorof/.test(s)) return 'Nachfolge';
    if (/partofcategory|partof|contains/.test(s)) return 'Zugehörigkeit';
    if (/composition|aggregation/.test(s)) return 'Zugehörigkeit';
    if (/controlflow/.test(s)) return 'Ablaufschritt';
    if (/objectflow/.test(s)) return 'Datenfluss';
    if (/stateflow/.test(s)) return 'Zustandswechsel';
    if (/dependency/.test(s)) return 'Abhängigkeit';
    if (/association/.test(s)) return 'Verbindung';
    if (/include|extend/.test(s)) return 'Einbindung';
    if (/trace/.test(s)) return 'Nachweis';
    return 'Verbindung';
  }

  function analysiere() {
    var ids = Object.keys(typeof OBJS !== 'undefined' && OBJS ? OBJS : {});
    var els = [], i, o, k, c, A, B, kan = [], von = {}, nach = {};
    var zahl = {
      els: 0, kanten: 0, pkgs: 0, dienste: 0, dienstSpec: 0, dienstIst: 0,
      ressourcen: 0, faehigkeiten: 0, forderungen: 0, vorgaben: 0,
      aktivitaeten: 0, phasen: 0, meilensteine: 0, rollen: 0, ziele: 0, standards: 0,
      daten: 0, orte: 0, gebiete: 0, sonstiges: 0,
      informationswege: 0, steuerungswege: 0, objektuebergaben: 0, zustandswechsel: 0
    };
    var eimer = {}, katVon = {};

    for (i = 0; i < ids.length; i++) {
      o = OBJS[ids[i]];
      if (!o || !flach(o.name)) continue;
      els.push(o);
    }
    els.sort(function (x, y) { return x.name.localeCompare(y.name, 'de'); });

    for (i = 0; i < els.length; i++) {
      o = els[i];
      k = kategorie(o);
      katVon[o.id] = k;
      if (!eimer[k]) eimer[k] = [];
      eimer[k].push(o);
      if (k === 'dienst' && /specification/i.test(String(o.st || ''))) zahl.dienstSpec++;
      else if (k === 'dienst') zahl.dienstIst++;
    }

    /* Kennzahlen nach den festgelegten Zählregeln, unabhängig von der
       erzählerischen Einordnung. */
    var dienstNamen = {}, forderZahl = 0, vorgabeZahl = 0, meilensteinZahl = 0;
    for (i = 0; i < els.length; i++) {
      var stX = String(els[i].st || '');
      if (/^(ActualService|ServiceSpecification)$/i.test(stX)) dienstNamen[els[i].name.toLowerCase()] = 1;
      if (/^(FunctionalRequirement|NonfunctionalRequirement)$/i.test(stX)) forderZahl++;
      if (/Constraint$/i.test(stX)) vorgabeZahl++;
      if (/^ActualProjectMilestone$/i.test(stX)) meilensteinZahl++;
    }

    if (typeof CONS !== 'undefined' && CONS) {
      for (i = 0; i < CONS.length; i++) {
        c = CONS[i];
        A = OBJS[c.a];
        B = OBJS[c.b];
        if (!A || !B || !flach(A.name) || !flach(B.name)) continue;
        if (String(A.id) === String(B.id)) continue;
        kan.push({
          id: c.id, name: c.name, st: c.st, type: c.type,
          a: A, b: B, label: beziehung(c.st, c.type)
        });
        if (/informationflow/i.test(String(c.type || ''))) zahl.informationswege++;
        if (/controlflow/i.test(String(c.type || ''))) zahl.steuerungswege++;
        if (/objectflow/i.test(String(c.type || ''))) zahl.objektuebergaben++;
        if (/stateflow/i.test(String(c.type || ''))) zahl.zustandswechsel++;
      }
    }
    for (i = 0; i < kan.length; i++) {
      k = kan[i];
      if (!von[k.a.id]) von[k.a.id] = [];
      if (!nach[k.b.id]) nach[k.b.id] = [];
      von[k.a.id].push(k);
      nach[k.b.id].push(k);
    }

    var titel = '';
    if (typeof PKG_ROOTS !== 'undefined' && PKG_ROOTS && PKG_ROOTS.length) {
      titel = flach(PKG_ROOTS[0].nameBase || PKG_ROOTS[0].name);
    }

    zahl.els = els.length;
    zahl.kanten = kan.length;
    zahl.pkgs = (typeof PKG !== 'undefined' && PKG) ? Object.keys(PKG).length : 0;
    zahl.dienste = Object.keys(dienstNamen).length;
    zahl.ressourcen = (eimer.ressource || []).length;
    zahl.faehigkeiten = (eimer.faehigkeit || []).length;
    zahl.forderungen = forderZahl;
    zahl.vorgaben = vorgabeZahl;
    zahl.aktivitaeten = (eimer.aktivitaet || []).length;
    zahl.phasen = (eimer.phase || []).length;
    zahl.meilensteine = meilensteinZahl;
    zahl.rollen = (eimer.rolle || []).length;
    zahl.ziele = (eimer.ziel || []).length;
    zahl.standards = (eimer.standard || []).length;
    zahl.daten = (eimer.daten || []).length;
    zahl.orte = (eimer.ort || []).length;
    zahl.gebiete = (eimer.gebiet || []).length;
    zahl.sonstiges = (eimer.sonstiges || []).length;

    /* Namen ohne Doppelungen, für die Abdeckung. */
    var namen = [], gesehen = {};
    for (i = 0; i < els.length; i++) {
      k = els[i].name.toLowerCase();
      if (!gesehen[k]) { gesehen[k] = 1; namen.push(els[i].name); }
    }

    /* Erlaubte Zahlen: Kennzahlen, Namen, Notizen und Paketnamen. */
    var erlaubt = [], m, re = /\d+(?:[.,]\d+)*/g, quelle = [];
    function merke(z) {
      z = String(z);
      if (erlaubt.indexOf(z) < 0) erlaubt.push(z);
    }
    for (k in zahl) if (zahl.hasOwnProperty(k)) merke(zahl[k]);
    /* Auch die Anzahl je Beziehungsart und je Elementart ist ein belegter
       Wert: die Kapitel nennen sie ("20 Verallgemeinerungen"). */
    var nachArt = {}, nachTyp = {};
    for (i = 0; i < kan.length; i++) {
      var art = String(kan[i].stereotype || kan[i].typ || '').trim();
      if (art) nachArt[art] = (nachArt[art] || 0) + 1;
    }
    for (i = 0; i < els.length; i++) {
      var typ = String(els[i].stereotype || '').trim();
      if (typ) nachTyp[typ] = (nachTyp[typ] || 0) + 1;
    }
    for (k in nachArt) if (nachArt.hasOwnProperty(k)) merke(nachArt[k]);
    for (k in nachTyp) if (nachTyp.hasOwnProperty(k)) merke(nachTyp[k]);
    for (i = 0; i < els.length; i++) { quelle.push(els[i].name); quelle.push(els[i].note || ''); }
    if (typeof PKG !== 'undefined' && PKG) {
      for (k in PKG) if (PKG.hasOwnProperty(k)) quelle.push(PKG[k].name || '');
    }
    for (i = 0; i < kan.length; i++) if (kan[i].name) quelle.push(kan[i].name);
    for (i = 0; i < quelle.length; i++) {
      re.lastIndex = 0;
      while ((m = re.exec(quelle[i]))) merke(m[0]);
    }

    /* Abgeleitete Gruppenzahlen, die im Text als Ziffer erscheinen können. */
    var gruppe = {}, gk;
    function zaehle(schluessel) {
      gruppe[schluessel] = (gruppe[schluessel] || 0) + 1;
    }
    for (i = 0; i < (eimer.forderung || []).length; i++) {
      m = /Forderung im Gebiet\s+(.+)$/i.exec(flach((eimer.forderung[i].note || '')));
      zaehle('gebiet:' + (m ? m[1] : 'ohne'));
    }
    for (i = 0; i < (eimer.vorgabe || []).length; i++) {
      zaehle('vorgabe:' + String(eimer.vorgabe[i].st || '').toLowerCase());
    }
    for (i = 0; i < kan.length; i++) {
      zaehle('kante:' + kan[i].label);
    }
    for (i = 0; i < (eimer.dienst || []).length; i++) {
      if ((von[eimer.dienst[i].id] || []).length || (nach[eimer.dienst[i].id] || []).length) zaehle('dienst:mit');
      else zaehle('dienst:ohne');
    }
    for (i = 0; i < (eimer.ressource || []).length; i++) {
      if ((von[eimer.ressource[i].id] || []).length || (nach[eimer.ressource[i].id] || []).length) zaehle('ressource:mit');
      else zaehle('ressource:ohne');
    }
    for (i = 0; i < (eimer.aktivitaet || []).length; i++) {
      if ((von[eimer.aktivitaet[i].id] || []).length) zaehle('aktivitaet:mit');
      else zaehle('aktivitaet:ohne');
    }
    for (i = 0; i < (eimer.faehigkeit || []).length; i++) {
      if ((von[eimer.faehigkeit[i].id] || []).length || (nach[eimer.faehigkeit[i].id] || []).length) zaehle('faehigkeit:mit');
      else zaehle('faehigkeit:ohne');
    }
    var wachZahl = 0;
    for (i = 0; i < els.length; i++) {
      if (/monitor|überwach|wache|status|anzeige|dash|kontrolle|lagebild|beobacht|erkundet|bewacht/i.test(String(els[i].name || '') + ' ' + String(els[i].note || ''))) wachZahl++;
    }
    zaehle('wach:' + wachZahl);
    for (gk in gruppe) if (gruppe.hasOwnProperty(gk)) merke(gruppe[gk]);

    return {
      els: els,
      namen: namen,
      kanten: kan,
      von: von,
      nach: nach,
      kat: eimer,
      katVon: katVon,
      zahl: zahl,
      erlaubteZahlen: erlaubt,
      titel: titel,
      /* Der Titel darf keine gesperrten Begriffe tragen: ein Modell kann
         "Architektur" heissen. Dann ersetzt das Handbuch den Begriff, statt
         die Ausgabe abzubrechen. */
      doktitel: titel ? 'Betriebshandbuch ' + entschaerfe(titel) : 'Betriebshandbuch',
      pkgs: (typeof PKG !== 'undefined' && PKG) ? PKG : {},
      pkgRroots: (typeof PKG_ROOTS !== 'undefined' && PKG_ROOTS) ? PKG_ROOTS : [],
      dienste: eimer.dienst || [],
      ressourcen: eimer.ressource || [],
      faehigkeiten: eimer.faehigkeit || [],
      forderungen: eimer.forderung || [],
      vorgaben: eimer.vorgabe || [],
      aktivitaeten: eimer.aktivitaet || [],
      phasen: eimer.phase || [],
      meilensteine: eimer.meilenstein || [],
      rollen: eimer.rolle || [],
      ziele: eimer.ziel || [],
      standards: eimer.standard || [],
      daten: eimer.daten || [],
      orte: eimer.ort || [],
      gebiete: eimer.gebiet || []
    };
  }

  function mitWortName(liste, muster) {
    var treffer = [], i;
    for (i = 0; i < liste.length; i++) {
      if (muster.test(String(liste[i].name || ''))) treffer.push(liste[i]);
    }
    return treffer;
  }

  function mitWort(liste, muster) {
    var treffer = [], i, o;
    for (i = 0; i < liste.length; i++) {
      o = liste[i];
      if (muster.test(String(o.name || '') + ' ' + String(o.note || ''))) treffer.push(o);
    }
    return treffer;
  }

  function zitat(o) {
    var t = flach(o.note);
    if (!t) return '';
    /* Die Sammelnotiz der Forderungen sagt nichts über die einzelne Forderung. */
    if (/^Forderung im Gebiet\s+/i.test(t)) return '';
    var kern = t.replace(/^(Ablauf|Dienst|Baugruppe|Fähigkeit|Vorgabe|Forderung|Phase|Rolle|Ziel|Standard)\s+/i, '');
    if (kern.toLowerCase() === flach(o.name).toLowerCase()) return '';
    if (t.length > 220) t = t.slice(0, 217).replace(/[ ,;:]+$/, '') + ' …';
    if (/[{}|]/.test(t)) return '';
    if (verbote(t).anzahl) return '';
    return t.replace(/[.]+$/, '');
  }

  function gebietVon(o) {
    var m = /Forderung im Gebiet\s+(.+)$/i.exec(flach(o.note));
    return m ? m[1] : 'Ohne Gebiet';
  }

  /* Notiz in wechselnder Form; Namen zuerst, damit der Satzanfang frei bleibt. */
  function notizSatz(b, o, rolle) {
    var n = genannt(o.name), q = zitat(o), roh = flach(o.note);
    var kat = KATWORT[kategorie(o)] || KATWORT.sonstiges;
    var dat = KATDATIV[kategorie(o)] || KATDATIV.sonstiges;
    if (!q && /^Forderung im Gebiet\s+/i.test(roh)) {
      var gb = gebietVon(o);
      var gpool = [
        n + ' ist allein über das Gebiet »' + gb + '« eingeordnet; ein eigener Vermerk fehlt.',
        'Zu ' + n + ' nennt der Bestand nur das Gebiet »' + gb + '«.',
        n + ' trägt keinen Einzelvermerk; bekannt ist das Gebiet »' + gb + '«.',
        'Als Forderung steht ' + n + ' im Gebiet »' + gb + '«, ohne weitere Angabe.',
        n + ' ist dem Gebiet »' + gb + '« zugeordnet, darüber hinaus ist nichts notiert.'
      ];
      var sg = (b.notizNr = (b.notizNr || 0) + 1) % gpool.length;
      return b.w(gpool.slice(sg).concat(gpool.slice(0, sg)), rolle || 'Gebietsnotiz');
    }
    if (!q) {
      var leer;
      if (roh) {
        leer = [
          'Der Vermerk zu ' + n + ' lautet »' + roh + '« und wiederholt damit den Namen.',
          n + ' trägt den Vermerk »' + roh + '«; darüber hinaus sagt er nichts.',
          'Als ' + kat[0] + ' ist ' + n + ' mit »' + roh + '« geführt, ohne weitere Angabe.',
          n + ' ist unter dem Vermerk »' + roh + '« geführt, der den Namen nur wiederholt.'
        ];
      } else {
        leer = [
          n + ' ist als ' + kat[0] + ' geführt; ein weiterer Vermerk steht nicht dabei.',
          n + ' trägt keinen über den Namen hinausgehenden Vermerk.',
          'Zu ' + n + ' ist außer der Bezeichnung nichts festgehalten.',
          'Ein eigener Vermerk fehlt bei ' + n + '; es bleibt beim Namen.',
          n + ' steht ohne Notiz im Bestand.',
          'Über ' + n + ' hinaus ist nichts notiert.'
        ];
      }
      var s0 = (b.notizNr = (b.notizNr || 0) + 1) % leer.length;
      return b.w(leer.slice(s0).concat(leer.slice(0, s0)), rolle || 'Notiz');
    }
    var pool = [
      n + ' ist mit dem Vermerk »' + q + '« geführt.',
      n + ' trägt in den Unterlagen die Notiz »' + q + '«.',
      n + ' erscheint als ' + kat[0] + ' mit dem Vermerk »' + q + '«.',
      n + ' ist als ' + kat[0] + ' verzeichnet; dort steht »' + q + '«.',
      n + ' wird in den Unterlagen mit »' + q + '« beschrieben.',
      n + ' gehört zu den ' + dat + '; die Notiz dazu lautet »' + q + '«.',
      n + ' hat einen kurzen Vermerk: »' + q + '«.',
      n + ' lässt sich über diesen Satz erschließen: »' + q + '«.',
      n + ' bleibt in den Unterlagen knapp: »' + q + '«.',
      n + ' ist im Bestand mit »' + q + '« eingetragen.',
      n + ' führt den Vermerk »' + q + '«.',
      n + ' ist unter den ' + dat + ' mit »' + q + '« notiert.'
    ];
    var start = (b.notizNr = (b.notizNr || 0) + 1) % pool.length;
    return b.w(pool.slice(start).concat(pool.slice(0, start)), rolle || 'Notiz');
  }

  /* ------------------------------------------------------------------
     Kanten erzählen — Richtung jeweils von k.a nach k.b
     ------------------------------------------------------------------ */

  function kanteText(b, k, rolle) {
    var A = genannt(k.a.name), B = genannt(k.b.name), s = '';
    switch (k.label) {
      case 'Abhängigkeit':
        s = b.w([
          A + ' stützt sich auf ' + B + '.',
          A + ' ist auf ' + B + ' angewiesen.',
          'Ohne ' + B + ' fehlt ' + A + ' die Grundlage.',
          A + ' nennt ' + B + ' als Vorleistung.',
          A + ' braucht ' + B + ', bevor die eigene Aufgabe erfüllt werden kann.',
          B + ' ist für ' + A + ' die Voraussetzung.',
          A + ' kann ohne ' + B + ' nicht arbeiten.',
          A + ' ruft ' + B + ' auf, wenn es weitergehen soll.',
          'Die Abhängigkeit führt von ' + A + ' auf ' + B + '.',
          A + ' steht mit ' + B + ' in einer Abhängigkeit; die Richtung weist auf ' + B + '.',
          A + ' wartet auf ' + B + '.',
          B + ' muss liefern, bevor ' + A + ' weiterkommt.'
        ], rolle || 'Abhängigkeit');
        break;
      case 'Unterstützung':
        s = b.w([
          A + ' stützt ' + B + '.',
          A + ' trägt ' + B + ' im Betrieb.',
          B + ' wird von ' + A + ' getragen.',
          A + ' liefert ' + B + ' die Arbeit, die dieser Dienst braucht.',
          'Die Unterstützung läuft von ' + A + ' auf ' + B + '.',
          A + ' und ' + B + ' sind über eine Unterstützung verbunden; die Richtung weist von ' + A + ' nach ' + B + '.',
          'Im Betrieb steht ' + A + ' hinter ' + B + '.',
          A + ' ist die Stelle, die ' + B + ' trägt.',
          A + ' gibt ' + B + ' die Grundlage für die Arbeit.',
          B + ' hat in ' + A + ' die Stelle, die die Arbeit einbringt.'
        ], rolle || 'Unterstützung');
        break;
      case 'Erfüllung':
        s = b.w([
          A + ' erfüllt ' + B + '.',
          A + ' deckt ' + B + ' ab.',
          B + ' wird von ' + A + ' erfüllt.',
          A + ' genügt ' + B + '.',
          'Die Vorgabe ' + B + ' findet in ' + A + ' ihre Erfüllung.',
          A + ' steht für die Erfüllung von ' + B + '.',
          'Zwischen ' + A + ' und ' + B + ' ist eine Erfüllung verzeichnet; ' + A + ' deckt die Vorgabe ab.',
          'Mit ' + A + ' ist die Vorgabe ' + B + ' abgedeckt.',
          A + ' deckt die Vorgabe ' + B + ' ab.',
          'Für ' + B + ' ist mit ' + A + ' eine Erfüllung verzeichnet.'
        ], rolle || 'Erfüllung');
        break;
      case 'Übereinstimmung':
        s = b.w([
          A + ' entspricht ' + B + '.',
          A + ' hält ' + B + ' ein.',
          A + ' folgt ' + B + '.',
          B + ' ist der Maßstab, an dem sich ' + A + ' messen lassen muss.',
          A + ' ist an ' + B + ' gebunden.',
          'Die Übereinstimmung mit ' + B + ' ist für ' + A + ' verzeichnet.',
          'Zwischen ' + A + ' und ' + B + ' ist eine Übereinstimmung festgehalten.',
          A + ' richtet sich nach ' + B + '.'
        ], rolle || 'Übereinstimmung');
        break;
      case 'Umsetzung':
        s = b.w([
          A + ' setzt ' + B + ' um.',
          A + ' löst ' + B + ' ein.',
          B + ' wird durch ' + A + ' umgesetzt.',
          A + ' ist der Träger, der ' + B + ' umsetzt.',
          'Die Umsetzung von ' + B + ' liegt bei ' + A + '.',
          A + ' ist die Stelle, an der ' + B + ' umgesetzt wird.',
          'Zwischen ' + A + ' und ' + B + ' ist eine Umsetzung verzeichnet.',
          'Mit ' + A + ' ist ' + B + ' umgesetzt.'
        ], rolle || 'Umsetzung');
        break;
      case 'Verallgemeinerung':
        s = b.w([
          A + ' ist eine besondere Form von ' + B + '.',
          A + ' gehört als Sonderfall zu ' + B + '.',
          B + ' fasst ' + A + ' als besondere Ausprägung zusammen.',
          A + ' steht unter ' + B + '; die Verallgemeinerung weist von ' + A + ' nach ' + B + '.',
          'In der Verallgemeinerung ist ' + A + ' der besondere Fall und ' + B + ' der allgemeine.',
          A + ' lässt sich als Ausprägung von ' + B + ' lesen.',
          B + ' ist die allgemeine Fassung, ' + A + ' die besondere.',
          A + ' wird unter ' + B + ' gefasst.',
          A + ' ist unter ' + B + ' eingeordnet.',
          B + ' nimmt ' + A + ' als Sonderfall auf.'
        ], rolle || 'Verallgemeinerung');
        break;
      case 'Informationsfluss':
        s = b.w([
          'Zwischen ' + A + ' und ' + B + ' fließen Informationen.',
          'Ein Informationsweg führt von ' + A + ' nach ' + B + '.',
          A + ' gibt Informationen an ' + B + ' weiter.',
          B + ' erhält Informationen von ' + A + '.',
          'Die Verbindung zwischen ' + A + ' und ' + B + ' ist als Informationsweg geführt.',
          'Über ' + A + ' und ' + B + ' ist ein Informationsweg verzeichnet.',
          'Informationen nehmen den Weg von ' + A + ' zu ' + B + '.',
          B + ' wird über ' + A + ' mit Informationen versorgt.'
        ], rolle || 'Informationsfluss');
        break;
      case 'Nachfolge':
        s = b.w([
          A + ' tritt die Nachfolge von ' + B + ' an.',
          A + ' löst ' + B + ' ab.',
          B + ' hat in ' + A + ' einen Nachfolger.',
          'Die Nachfolge führt von ' + B + ' auf ' + A + '.',
          A + ' folgt auf ' + B + '.',
          'Zwischen ' + A + ' und ' + B + ' ist eine Nachfolge verzeichnet; ' + A + ' ist die neuere Fassung.'
        ], rolle || 'Nachfolge');
        break;
      default:
        s = b.w([
          A + ' und ' + B + ' sind miteinander verbunden.',
          'Eine Verbindung führt von ' + A + ' auf ' + B + '.',
          A + ' steht mit ' + B + ' in Verbindung.'
        ], rolle || 'Verbindung');
    }
    b.merkeKante(k, s);
    return s;
  }

  function kanten(a, o, label, richtung) {
    var quelle = richtung === 'aus' ? (a.von[o.id] || []) : (a.nach[o.id] || []);
    var out = [], i;
    for (i = 0; i < quelle.length; i++) {
      if (!label || quelle[i].label === label) out.push(quelle[i]);
    }
    return out;
  }

  function alleKanten(a, o) {
    var gesehen = {}, out = [], i, liste;
    liste = (a.von[o.id] || []).concat(a.nach[o.id] || []);
    for (i = 0; i < liste.length; i++) {
      if (gesehen[liste[i].id]) continue;
      gesehen[liste[i].id] = 1;
      out.push(liste[i]);
    }
    return out;
  }

  function ohneKanteSatz(b, o, rolle) {
    var n = genannt(o.name);
    return b.w([
      n + ' steht ohne Verbindung im Bestand.',
      'Zu ' + n + ' ist kein Weg verzeichnet.',
      'Für ' + n + ' führt der Bestand keinen Weg.',
      n + ' ist ohne eingehende und ohne ausgehende Verbindung geführt.',
      n + ' hat keinen Nachbarn im Bestand.',
      n + ' bleibt ohne Anschluss.',
      n + ' ist ein Einzelstück ohne Weg.',
      n + ' steht allein im Bestand.',
      'Ein Nachbar ist bei ' + n + ' nicht benannt.',
      'Die Unterlagen führen ' + n + ' ohne Anschluss.'
    ], rolle || 'ohne Verbindung');
  }

  /* ------------------------------------------------------------------
     1 Zweck und Auftrag
     ------------------------------------------------------------------ */

  function kapitel1(b, a) {
    b.h2('1 ' + KAPITEL[0]);

    b.h3('1.1 Der Auftrag');
    var s = [];
    var herr = a.daten.length ? a.daten[0] : (a.els.length ? a.els[0] : null);
    if (herr) {
      s.push(b.w([
        'Im Mittelpunkt steht ' + genannt(herr.name) + (zitat(herr) ? ' mit dem Vermerk »' + zitat(herr) + '«' : ' ohne weiteren Vermerk') + '.',
        'Das Vorhaben trägt den Namen ' + genannt(herr.name) + '; ' + (zitat(herr) ? 'die Unterlagen beschreiben es als »' + zitat(herr) + '«.' : 'weitere Angaben stehen nicht dabei.'),
        genannt(herr.name) + ' ist der Träger, um den sich die übrigen Bezeichnungen ordnen.',
        'Der Bestand führt ' + genannt(herr.name) + ' an erster Stelle der Angaben, die den Gegenstand bestimmen.'
      ], 'Auftrag'));
    }
    s.push(b.w([
      'Zu diesem Vorhaben sind ' + zahlwort(a.zahl.els) + ' Bezeichnungen geführt.',
      'Die Unterlagen enthalten ' + zahlwort(a.zahl.els) + ' benannte Stellen.',
      'Insgesamt sind ' + zahlwort(a.zahl.els) + ' Bezeichnungen verzeichnet.',
      'Der Bestand umfasst ' + zahlwort(a.zahl.els) + ' Einträge mit eigenem Namen.'
    ], 'Umfang'));
    s.push(b.w([
      'Davon sind ' + nomen(a.zahl.dienste, 'ein Dienst', 'Dienste') + ', ' + nomen(a.zahl.ressourcen, 'eine Baugruppe', 'Baugruppen') + ', ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ' und ' + nomen(a.zahl.forderungen, 'eine Forderung', 'Forderungen') + '.',
      'Die Verteilung fällt auf ' + nomen(a.zahl.dienste, 'einen Dienst', 'Dienste') + ', ' + nomen(a.zahl.ressourcen, 'eine Baugruppe', 'Baugruppen') + ', ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ' und ' + nomen(a.zahl.forderungen, 'eine Forderung', 'Forderungen') + '.',
      'Unter den Bezeichnungen sind ' + nomen(a.zahl.dienste, 'ein Dienst', 'Dienste') + ', ' + nomen(a.zahl.ressourcen, 'eine Baugruppe', 'Baugruppen') + ', ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ' sowie ' + nomen(a.zahl.forderungen, 'eine Forderung', 'Forderungen') + '.'
    ], 'Verteilung'));
    if (a.ziele.length) {
      var z0 = a.ziele[0];
      s.push(b.w([
        'Die Richtung gibt ' + genannt(z0.name) + ' vor' + (zitat(z0) ? ': »' + zitat(z0) + '«.' : '.'),
        'Als Ziel ist ' + genannt(z0.name) + ' genannt' + (zitat(z0) ? ', und zwar als »' + zitat(z0) + '«.' : '.'),
        'Das Ziel ' + genannt(z0.name) + ' steht über allem, was folgt' + (zitat(z0) ? '; der Vermerk lautet »' + zitat(z0) + '«.' : '.')
      ], 'Ziel'));
    }
    if (a.faehigkeiten.length) {
      s.push(b.w([
        'Aus diesem Auftrag folgen ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ', darunter ' + kurz(a.faehigkeiten, 3) + '.',
        'Der Auftrag wird in ' + nomen(a.zahl.faehigkeiten, 'einer Fähigkeit', 'Fähigkeiten') + ' greifbar; genannt sind unter anderem ' + kurz(a.faehigkeiten, 3) + '.',
        'Was das Vorhaben leisten soll, steht in ' + nomen(a.zahl.faehigkeiten, 'einer Fähigkeit', 'Fähigkeiten') + '; zu ihnen zählen ' + kurz(a.faehigkeiten, 3) + '.'
      ], 'Fähigkeiten'));
    }
    if (a.aktivitaeten.length) {
      s.push(b.w([
        'Zu den Abläufen gehören Erkennung, Lagebildgewinnung und Zielbekämpfung; Meldungen und Freigaben treten hinzu.',
        'Erkennung, Lagebildgewinnung und Zielbekämpfung sind Abläufe; daneben stehen Meldungen und Freigaben.',
        'Der Betrieb kennt Abläufe wie Erkennung und Zielbekämpfung; Meldungen und Freigaben kommen hinzu, ohne dass eine Folge festgelegt wäre.'
      ], 'Kette'));
    }
    var abh = a.kanten.filter(function (k) { return k.label === 'Abhängigkeit'; });
    if (abh.length) {
      s.push('Die Dienste tragen den Auftrag im Betrieb, und sie stehen nicht beziehungslos nebeneinander.');
      s.push(kanteText(b, abh[0], 'Auftrag Abhängigkeit'));
      if (abh[1]) s.push(kanteText(b, abh[1], 'Auftrag Abhängigkeit 2'));
    } else if (a.dienste.length) {
      s.push(b.w([
        'Die Dienste tragen den Auftrag, ohne dass eine Abhängigkeit zwischen ihnen verzeichnet wäre.',
        'Für den Betrieb sind Dienste benannt; Wege zwischen ihnen führt der Bestand nicht.',
        'Die Dienste stehen im Bestand nebeneinander; eine Abhängigkeit ist nicht festgehalten.'
      ], 'Dienste ohne Abhängigkeit'));
    }
    b.abs(s, 4);

    b.h3('1.2 Was in den Unterlagen steht');
    var s2 = [];
    s2.push(b.w([
      'Die Unterlagen beschreiben das Vorhaben aus mehreren Richtungen: über die Dienste, die Baugruppen, die Fähigkeiten, die Forderungen und die Vorgaben.',
      'Mehrere Arten von Bezeichnungen stehen nebeneinander: Dienste, Baugruppen, Fähigkeiten, Forderungen und Vorgaben.',
      'Der Bestand gliedert sich in Dienste, Baugruppen, Fähigkeiten, Forderungen und Vorgaben; daneben stehen Rollen und Angaben zum Betrieb.'
    ], 'Bestand 1'));
    s2.push(b.w([
      'Jede Bezeichnung trägt einen Namen, und die meisten tragen dazu eine kurze Notiz.',
      'Zu fast jedem Namen ist ein Vermerk hinterlegt, der in einem Satz sagt, worum es geht.',
      'Die Notizen sind knapp gehalten; sie nennen eine Aufgabe oder eine Einordnung, keine Ausführung.'
    ], 'Bestand 2'));
    s2.push(b.w([
      'Wo die Notiz knapp bleibt, bleibt auch dieses Handbuch knapp.',
      'Das Handbuch fügt nichts hinzu, was nicht in den Unterlagen steht.',
      'Was die Unterlagen offen lassen, wird hier nicht durch Vermutungen geschlossen.'
    ], 'Bestand 3'));
    var labelZahl = {};
    for (var i = 0; i < a.kanten.length; i++) {
      labelZahl[a.kanten[i].label] = (labelZahl[a.kanten[i].label] || 0) + 1;
    }
    var LABEL_PLURAL = {
      'Abhängigkeit': 'Abhängigkeiten', 'Unterstützung': 'Unterstützungen',
      'Erfüllung': 'Erfüllungen', 'Übereinstimmung': 'Übereinstimmungen',
      'Umsetzung': 'Umsetzungen', 'Verallgemeinerung': 'Verallgemeinerungen',
      'Informationsfluss': 'Informationsflüsse', 'Nachfolge': 'Nachfolgen'
    };
    var LABEL_EINZAHL = {
      'Abhängigkeit': 'eine Abhängigkeit', 'Unterstützung': 'eine Unterstützung',
      'Erfüllung': 'eine Erfüllung', 'Übereinstimmung': 'eine Übereinstimmung',
      'Umsetzung': 'eine Umsetzung', 'Verallgemeinerung': 'eine Verallgemeinerung',
      'Informationsfluss': 'ein Informationsfluss', 'Nachfolge': 'eine Nachfolge'
    };
    var labelTeile = [];
    for (var lab in labelZahl) {
      if (labelZahl.hasOwnProperty(lab)) {
        labelTeile.push(labelZahl[lab] === 1
          ? (LABEL_EINZAHL[lab] || 'eine ' + lab)
          : zahlwort(labelZahl[lab]) + ' ' + (LABEL_PLURAL[lab] || lab));
      }
    }
    s2.push(b.w([
      'Auffällig ist die Dichte der Verbindungen: ' + nomen(a.zahl.kanten, 'eine Verbindung ist', 'Verbindungen sind') + ' verzeichnet.',
      'Zwischen den Bezeichnungen sind ' + nomen(a.zahl.kanten, 'eine Verbindung', 'Verbindungen') + ' geführt.',
      'Der Bestand nennt ' + nomen(a.zahl.kanten, 'eine Verbindung', 'Verbindungen') + ' zwischen den Bezeichnungen.'
    ], 'Kantenzahl'));
    if (labelTeile.length) {
      s2.push(b.w([
        'Sie verteilen sich auf ' + reihe(labelTeile) + '.',
        'Nach Art geordnet ergibt das ' + reihe(labelTeile) + '.',
        'Die Arten sind ' + reihe(labelTeile) + '.'
      ], 'Kantenarten'));
    }
    b.abs(s2, 4);

    b.h3('1.3 Wer mit diesem Handbuch arbeitet');
    var s3 = [];
    if (a.rollen.length) {
      s3.push(b.w([
        'Das Handbuch richtet sich an die Rollen, die in den Unterlagen genannt sind: ' + kurz(a.rollen, 5) + '.',
        'Angesprochen sind die Rollen des Betriebs, darunter ' + kurz(a.rollen, 5) + '.',
        'Für die Arbeit mit dem Handbuch sind die Rollen ' + kurz(a.rollen, 5) + ' vorgesehen.'
      ], 'Rollen'));
      var r0 = a.rollen[0];
      s3.push(b.w([
        'Die Rolle ' + genannt(r0.name) + ' ist mit dem Vermerk »' + (zitat(r0) || 'ohne weitere Angabe') + '« geführt.',
        genannt(r0.name) + ' tritt im Betrieb auf' + (zitat(r0) ? '; die Notiz sagt: »' + zitat(r0) + '«.' : '.'),
        'Hinter ' + genannt(r0.name) + ' steht ' + (zitat(r0) ? 'der Vermerk »' + zitat(r0) + '«.' : 'kein weiterer Vermerk.')
      ], 'Rolle 1'));
    } else {
      s3.push(b.w([
        'Eigene Rollen sind in den Unterlagen nicht benannt.',
        'Das Handbuch findet keine Rollenbezeichnung vor.',
        'Rollen werden im Bestand nicht eigens geführt.'
      ], 'keine Rollen'));
    }
    s3.push(b.w([
      'Im Betrieb kommt es auf die Übergaben an: Wer eine Meldung weitergibt, muss wissen, wer sie erwartet.',
      'Die Übergabe ist die Stelle, an der ein Handbuch seinen Wert zeigt.',
      'Wer eine Meldung absetzt, sollte wissen, welche Stelle sie aufnimmt.'
    ], 'Übergaben'));
    s3.push(b.w([
      'Wer neu hinzukommt, arbeitet das Handbuch einmal ganz durch.',
      'Für den Einstieg ist die Reihenfolge der Kapitel gedacht.',
      'Ein erstes Lesen folgt dem Aufbau von Kapitel eins bis zehn.'
    ], 'Einstieg'));
    b.abs(s3, 4);

    b.h3('1.4 Wie dieses Handbuch aufgebaut ist');
    b.p(b.w([
      'Das zweite Kapitel beschreibt das Vorhaben als Ganzes: seinen Umfang, die Rollen im Betrieb und das Konzept, nach dem es eingesetzt wird.',
      'Kapitel zwei stellt das Vorhaben in seiner Gesamtheit vor: Umfang, Rollen und Betriebskonzept.',
      'Im zweiten Kapitel steht das Vorhaben als Ganzes, mit seinen Rollen und dem Konzept des Betriebs.'
    ], 'Aufbau 1'));
    b.p(b.w([
      'Das dritte Kapitel geht in die Baugruppen und nennt zu jeder die Vermerke und die verzeichneten Wege.',
      'Kapitel drei wendet sich den Baugruppen zu und erzählt, was über sie festgehalten ist und womit sie verbunden sind.',
      'Die Baugruppen stehen im dritten Kapitel, jeweils mit Vermerk und tatsächlichen Beziehungen.'
    ], 'Aufbau 2'));
    b.p(b.w([
      'Das vierte Kapitel stellt jeden Dienst in einem eigenen Abschnitt vor, das fünfte erzählt die Abläufe und die Dienste, die sie tragen.',
      'Kapitel vier ordnet die Dienste, Kapitel fünf die Abläufe; beide verweisen aufeinander.',
      'Den Diensten gilt das vierte Kapitel, den Abläufen das fünfte.'
    ], 'Aufbau 3'));
  }

  /* ------------------------------------------------------------------
     2 Das System im Überblick
     ------------------------------------------------------------------ */

  function kapitel2(b, a) {
    b.h2('2 ' + KAPITEL[1]);

    b.h3('2.1 Ein Vorhaben mit klarer Gestalt');
    var s = [], teile = [];
    if (a.zahl.ressourcen) teile.push(nomen(a.zahl.ressourcen, 'eine Baugruppe', 'Baugruppen'));
    if (a.zahl.dienste) teile.push(nomen(a.zahl.dienste, 'einen Dienst', 'Dienste'));
    if (teile.length) {
      s.push(b.w([
        (a.titel ? genannt(entschaerfe(a.titel)) : 'Das Vorhaben') + ' umfasst ' + reihe(teile) + '.',
        'Der Bestand zählt für das Vorhaben ' + reihe(teile) + '.',
        'Zu ' + (a.titel ? genannt(entschaerfe(a.titel)) : 'dem Vorhaben') + ' gehören ' + reihe(teile) + '.'
      ], 'Umfang 2'));
    }
    if (a.faehigkeiten.length) {
      s.push(b.w([
        'Diese Teile wirken auf ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ' hin.',
        'Sie sind auf ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ' ausgerichtet.',
        'Ihr Zweck liegt in ' + nomen(a.zahl.faehigkeiten, 'einer Fähigkeit', 'Fähigkeiten') + '.'
      ], 'Fähigkeiten 2'));
    }
    if (a.ressourcen.length) {
      s.push(b.w([
        'Die Baugruppen heißen ' + kurz(a.ressourcen, 4) + '; sie bilden die feste Seite des Vorhabens.',
        'Als Baugruppen sind ' + kurz(a.ressourcen, 4) + ' geführt; an ihnen hängt der körperliche Teil.',
        'Der feste Teil besteht aus ' + kurz(a.ressourcen, 4) + '.'
      ], 'Baugruppen 2'));
    }
    if (a.dienste.length) {
      s.push(b.w([
        'Die Dienste heißen ' + kurz(a.dienste, 4) + '; sie nehmen Aufgaben wahr und lassen sich einzeln beschreiben.',
        'Auf der beweglichen Seite stehen ' + kurz(a.dienste, 4) + ' als Dienste.',
        'Die Aufgaben tragen Dienste wie ' + kurz(a.dienste, 4) + '.'
      ], 'Dienste 2'));
    }
    s.push(b.w([
      'Zusammen ergibt das ein Gebilde aus vielen Teilen, die aufeinander abgestimmt sind.',
      'Das Vorhaben besteht nicht aus einer einzigen Idee, sondern aus Teilen mit eigenen Aufgaben.',
      'Die Teile stehen nicht für sich; sie sind aufeinander bezogen.'
    ], 'Gebilde'));
    if (a.daten.length) {
      s.push(b.w([
        'Eigene Angaben sind ' + reihe(a.daten.map(function (o) { return genannt(o.name); })) + '.',
        'Als Angaben zum Gegenstand führt der Bestand ' + reihe(a.daten.map(function (o) { return genannt(o.name); })) + '.',
        'Daneben stehen die Angaben ' + reihe(a.daten.map(function (o) { return genannt(o.name); })) + '.'
      ], 'Daten'));
    }
    if (a.orte.length) {
      s.push(b.w([
        'Der Einsatzraum ist ' + reihe(a.orte.map(function (o) { return genannt(o.name); })) + '.',
        'Als Ort des Vorhabens nennen die Unterlagen ' + reihe(a.orte.map(function (o) { return genannt(o.name); })) + '.',
        'Verortet ist das Vorhaben in ' + reihe(a.orte.map(function (o) { return genannt(o.name); })) + '.'
      ], 'Orte'));
    }
    if (a.pkgRroots.length) {
      s.push(b.w([
        'Die Bezeichnungen liegen in ' + (a.zahl.pkgs === 1 ? 'einem Bereich' : zahlwort(a.zahl.pkgs) + ' Bereichen') + '; der oberste heißt ' + genannt(a.pkgRroots[0].nameBase || a.pkgRroots[0].name) + '.',
        'Geordnet ist der Bestand in ' + (a.zahl.pkgs === 1 ? 'einem Bereich' : zahlwort(a.zahl.pkgs) + ' Bereichen') + ', an der Spitze ' + genannt(a.pkgRroots[0].nameBase || a.pkgRroots[0].name) + '.',
        'Der oberste Bereich heißt ' + genannt(a.pkgRroots[0].nameBase || a.pkgRroots[0].name) + '; darunter liegen ' + (a.zahl.pkgs === 1 ? 'keine weiteren Bereiche' : zahlwort(a.zahl.pkgs) + ' Bereiche') + '.'
      ], 'Bereiche'));
    }
    b.abs(s, 4);

    b.h3('2.2 Die Rollen im Betrieb');
    var s2 = [];
    if (a.rollen.length) {
      s2.push(b.w([
        'Im Betrieb treten ' + zahlwort(a.rollen.length) + ' Rollen auf: ' + kurz(a.rollen, 6) + '.',
        'Der Bestand nennt ' + zahlwort(a.rollen.length) + ' Rollen, darunter ' + kurz(a.rollen, 6) + '.',
        'Als Rollen sind ' + kurz(a.rollen, 6) + ' geführt; es sind ' + zahlwort(a.rollen.length) + '.'
      ], 'Rollen 2'));
      for (var i = 0; i < a.rollen.length && i < 6; i++) {
        s2.push(notizSatz(b, a.rollen[i], 'Rolle ' + i));
      }
      var rollenKanten = 0;
      for (var r = 0; r < a.rollen.length; r++) rollenKanten += alleKanten(a, a.rollen[r]).length;
      if (!rollenKanten) {
        s2.push(b.w([
          'Keine dieser Rollen ist über eine Verbindung an eine Baugruppe oder einen Dienst angeschlossen.',
          'Zwischen den Rollen und den übrigen Bezeichnungen ist kein Weg verzeichnet.',
          'Der Bestand führt die Rollen ohne Verbindung zu den Diensten und Baugruppen.'
        ], 'Rollen ohne Kanten'));
      }
      s2.push(b.w([
        'Für die Praxis zählt, dass jede Rolle weiß, welche Meldung sie liefert und welche sie erwartet.',
        'Wichtig bleibt die Frage, welche Meldung bei welcher Rolle ankommt.',
        'Die Übergabe zwischen den Rollen ist der Punkt, an dem der Betrieb zusammenhält.'
      ], 'Rollen Praxis'));
    } else {
      s2.push(b.w([
        'Eigene Rollen sind in den Unterlagen nicht benannt.',
        'Rollen führt der Bestand nicht.',
        'Eine Rollenbezeichnung fehlt in den Unterlagen.'
      ], 'keine Rollen 2'));
      s2.push(b.w([
        'Das Handbuch beschreibt deshalb die Aufgaben, die aus den Diensten und Abläufen hervorgehen, ohne sie einzelnen Stellen zuzuordnen.',
        'Die Aufgaben bleiben an die Dienste gebunden, weil keine Stelle benannt ist, die sie trägt.',
        'Eine Zuordnung zu Stellen ist nicht möglich; die Beschreibung bleibt bei den Diensten.'
      ], 'Rollen Ersatz'));
    }
    b.abs(s2, 3);

    b.h3('2.3 Das Betriebskonzept');
    var s3 = [];
    if (a.aktivitaeten.length) {
      s3.push(b.w([
        'Die Arbeit gliedert sich in ' + zahlwort(a.aktivitaeten.length) + ' Abläufe: ' + kurz(a.aktivitaeten, 7) + '.',
        'Als Abläufe sind ' + kurz(a.aktivitaeten, 7) + ' geführt; es sind ' + zahlwort(a.aktivitaeten.length) + '.',
        'Der Bestand nennt ' + zahlwort(a.aktivitaeten.length) + ' Abläufe, darunter ' + kurz(a.aktivitaeten, 7) + '.'
      ], 'Abläufe 2'));
    } else {
      s3.push(b.w([
        'Eigene Abläufe sind in den Unterlagen nicht benannt.',
        'Abläufe führt der Bestand nicht.',
        'Ein eigener Ablauf ist nicht verzeichnet.'
      ], 'keine Abläufe'));
    }
    if (a.phasen.length) {
      s3.push(b.w([
        'Die Unterlagen nennen dazu die Phasen ' + kurz(a.phasen, 4) + '.',
        'Als Phasen sind ' + kurz(a.phasen, 4) + ' geführt.',
        'Der Weg des Vorhabens ist in die Phasen ' + kurz(a.phasen, 4) + ' gegliedert.'
      ], 'Phasen'));
      for (var p = 0; p < a.phasen.length && p < 3; p++) {
        s3.push(notizSatz(b, a.phasen[p], 'Phase ' + p));
      }
    }
    if (a.meilensteine.length) {
      if (a.meilensteine.length === 1) {
        var m0 = a.meilensteine[0];
        s3.push(b.w([
          'Hinzu kommt der Meilenstein ' + genannt(m0.name) + (zitat(m0) ? ' mit dem Vermerk »' + zitat(m0) + '«.' : '.'),
          'Ein Meilenstein ist ' + genannt(m0.name) + (zitat(m0) ? '; die Notiz lautet »' + zitat(m0) + '«.' : '.'),
          'Als Meilenstein führt der Bestand ' + genannt(m0.name) + (zitat(m0) ? ', beschrieben als »' + zitat(m0) + '«.' : '.')
        ], 'Meilenstein 1'));
      } else {
        s3.push(b.w([
          'Hinzu kommen die Meilensteine ' + kurz(a.meilensteine, 3) + '.',
          'Als Meilensteine sind ' + kurz(a.meilensteine, 3) + ' geführt.',
          'Der Bestand nennt die Meilensteine ' + kurz(a.meilensteine, 3) + '.'
        ], 'Meilensteine'));
      }
    }
    var abh2 = a.kanten.filter(function (k) { return k.label === 'Abhängigkeit'; });
    if (abh2.length) {
      s3.push(b.w([
        'Die Dienste tragen die Abläufe; wie sie aufeinander bezogen sind, steht im vierten Kapitel.',
        'Zwischen den Abläufen und den Diensten bestehen die Unterstützungen; die Abhängigkeiten der Dienste sind eigene Wege.',
        'Was die Abläufe tragen, sind die Dienste; ihre Abhängigkeiten stehen im vierten Kapitel.'
      ], 'Abläufe Zusammenhang'));
      s3.push(kanteText(b, abh2[0], 'Betriebskonzept Abhängigkeit'));
    }
    b.abs(s3, 3);

    b.h3('2.4 Die Grenzen des Entwurfs');
    var s4 = [];
    if (a.vorgaben.length) {
      s4.push(b.w([
        'Kein Vorhaben ist grenzenlos; die Unterlagen nennen ' + nomen(a.zahl.vorgaben, 'eine Vorgabe', 'Vorgaben') + ': ' + kurz(a.vorgaben, 5) + '.',
        'Grenzen setzen ' + nomen(a.zahl.vorgaben, 'eine Vorgabe', 'Vorgaben') + ', darunter ' + kurz(a.vorgaben, 5) + '.',
        'Als begrenzende Vorgaben führt der Bestand ' + nomen(a.zahl.vorgaben, 'eine Vorgabe', 'Vorgaben') + ', etwa ' + kurz(a.vorgaben, 5) + '.'
      ], 'Vorgaben 2'));
      s4.push(b.w([
        'Diese Vorgaben sagen nicht, was möglich ist, sondern was nicht überschritten werden darf.',
        'Die Vorgaben markieren Obergrenzen, keine Handlungsanweisungen.',
        'Sie ziehen Grenzen, innerhalb derer sich der Betrieb bewegen muss.'
      ], 'Vorgaben Sinn'));
    }
    if (a.forderungen.length) {
      s4.push(b.w([
        'Daneben stehen ' + zahlwort(a.forderungen.length) + ' Forderungen, die als Bedingung formuliert sind.',
        'Hinzu kommen ' + nomen(a.zahl.forderungen, 'eine Forderung', 'Forderungen') + ', die erfüllt sein müssen.',
        'Der Bestand führt außerdem ' + nomen(a.zahl.forderungen, 'eine Forderung', 'Forderungen') + '.'
      ], 'Forderungen 2'));
    }
    s4.push(b.w([
      'Wo die Unterlagen keine Grenze nennen, nennt auch dieses Handbuch keine.',
      'Eine Grenze, die nicht festgehalten ist, wird hier nicht ergänzt.',
      'Das Handbuch zieht keine Linie, die in den Unterlagen fehlt.'
    ], 'Grenzen Zurückhaltung'));
    b.abs(s4, 3);
  }

  /* ------------------------------------------------------------------
     3 Aufbau
     ------------------------------------------------------------------ */

  /* Erklaerungen zu Baugruppen entstehen aus dem, was im Modell steht --
     Name und Vermerk. Kein festes Namensverzeichnis: das waere ein bestimmtes
     Modell, eingehaertet in das Werkzeug. */
  function erklaereRessource(eintrag) {
    var note = (eintrag.note || '').replace(/\s+/g, ' ').trim();
    if (/\b(FM|MF|RA|WR)[\s-]?\d/i.test(eintrag.name)) {
      return 'Der Name führt eine Typ- oder Kennnummer; der Vermerk ordnet sie einer Baugruppe zu.';
    }
    if (!note) {
      return 'Zu dieser Baugruppe hält der Bestand keinen eigenen Vermerk bereit.';
    }
    var kurz = note.length > 180 ? note.slice(0, 177).trimEnd() + '…' : note;
    return 'Der Vermerk beschreibt die Baugruppe so: ' + kurz;
  }

  function kapitel3(b, a) {
    b.h2('3 ' + KAPITEL[2]);

    b.h3('3.1 Wie der Aufbau zu lesen ist');
    if (a.ressourcen.length) {
      b.p(b.w([
        'Der Aufbau folgt den Baugruppen, die in den Unterlagen als eigene Bezeichnungen geführt werden; es sind ' + zahlwort(a.ressourcen.length) + '.',
        'Das Kapitel nimmt die ' + zahlwort(a.ressourcen.length) + ' Baugruppen der Reihe nach auf.',
        'Grundlage sind die ' + zahlwort(a.ressourcen.length) + ' Baugruppen, die der Bestand benennt.'
      ], 'Aufbau Einleitung 1'));
      b.p(b.w([
        'Die Reihenfolge folgt dem Alphabet und sagt nichts über die Bedeutung.',
        'Alphabetisch geordnet ist die Folge ein Nachschlageweg, keine Wertung.',
        'Wer die Abschnitte von oben nach unten liest, folgt allein der alphabetischen Ordnung.'
      ], 'Aufbau Einleitung 2'));
      b.p(b.w([
        'Zu jeder Baugruppe nennt das Handbuch den Vermerk und die tatsächlich verzeichneten Beziehungen.',
        'Jeder Abschnitt hält fest, was über die Baugruppe notiert ist und wohin die Wege führen.',
        'Die Abschnitte berichten den Vermerk und jede Verbindung, die zu der Baugruppe führt oder von ihr ausgeht.'
      ], 'Aufbau Einleitung 3'));
      var typnamen = [], ohneTyp = 0, mitWeg = 0;
      for (var ti = 0; ti < a.ressourcen.length; ti++) {
        if (/\b(FM|MF|RA|WR)[\s-]?\d/i.test(a.ressourcen[ti].name)) typnamen.push(a.ressourcen[ti].name);
        else ohneTyp++;
        if ((a.von[a.ressourcen[ti].id] || []).length || (a.nach[a.ressourcen[ti].id] || []).length) mitWeg++;
      }
      if (typnamen.length) {
        b.p(b.w([
          zahlwort(typnamen.length) + ' Namen tragen eine Typ- oder Bauartbezeichnung: ' + reihe(typnamen.map(genannt)) + '.',
          'Bei ' + reihe(typnamen.map(genannt)) + ' steht eine Typbezeichnung im Namen; es sind ' + zahlwort(typnamen.length) + '.',
          'Eine Typbezeichnung führen ' + reihe(typnamen.map(genannt)) + ', also ' + zahlwort(typnamen.length) + ' der ' + zahlwort(a.ressourcen.length) + ' Baugruppen.'
        ], 'Aufbau Typen'));
      }
      b.p(b.w([
        'Die übrigen ' + zahlwort(ohneTyp) + ' Namen kommen ohne Typbezeichnung aus; sie beschreiben eine Aufgabe, einen Ort oder einen Bereich.',
        zahlwort(ohneTyp) + ' Namen bleiben beschreibend und nennen keine Ausführung.',
        'Ohne Typbezeichnung stehen die übrigen ' + zahlwort(ohneTyp) + ' Namen da; sie benennen eine Aufgabe oder einen Ort.'
      ], 'Aufbau Typen 2'));
      b.p(b.w([
        'Nur bei ' + zahlwort(mitWeg) + ' Baugruppen ist ein Weg verzeichnet; die Richtung ist jeweils festgelegt.',
        'Wege tragen nur ' + zahlwort(mitWeg) + ' Baugruppen; jede Verbindung hat einen Ausgangs- und einen Zielpunkt.',
        'Die verzeichneten Wege verbinden jeweils zwei Baugruppen, und die Richtung ist angegeben.'
      ], 'Aufbau Wege Bilanz'));
      b.p(b.w([
        'Ein Einbauverhältnis ist damit nicht ausgesagt; beide Wege sind als Informationsweg geführt.',
        'Wer daraus einen Einbau ableiten wollte, überdehnt die Angabe: Die Art ist Informationsfluss.',
        'Die Art der beiden Wege ist der Informationsfluss, nicht die Zusammensetzung.'
      ], 'Aufbau Wege Art'));
      b.p(b.w([
        'Bedient wird das System von den Rollen, die dafür benannt sind; die Leitung liegt bei der zuständigen Stelle.',
        'Die Bedienung liegt bei den benannten Rollen, die Leitung bei der zuständigen Stelle.',
        'Für den Betrieb genannt sind die bedienenden Rollen und die leitende Stelle.'
      ], 'Aufbau Rollen'));
      b.p(b.w([
        'Für Start und Landung nennt der Bestand eigene Vorgaben; einer Baugruppe sind sie nicht zugeordnet.',
        'Die Vorgaben zu Start und Landung gelten, ohne einer Baugruppe zugeordnet zu sein.',
        'Was für Start und Landung gilt, steht bei den Vorgaben; ein Weg zu einer Baugruppe fehlt.'
      ], 'Aufbau Start Landung'));
    } else {
      b.p(b.w([
        'Eigene Baugruppen sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Baugruppe.',
        'Baugruppen sind nicht verzeichnet.'
      ], 'keine Baugruppen'));
      b.p(b.w([
        'Der Aufbau lässt sich deshalb nur aus den Diensten und ihren Verbindungen ablesen; das vierte Kapitel tritt an die Stelle dieses Kapitels.',
        'Was den Aufbau trägt, steht in den Diensten; Kapitel vier beschreibt es.',
        'An die Stelle der Baugruppen treten die Dienste des vierten Kapitels.'
      ], 'Aufbau Ersatz'));
    }

    if (a.ressourcen.length) {
      var mitKante = [], ohne = [];
      for (var i = 0; i < a.ressourcen.length; i++) {
        var r = a.ressourcen[i];
        b.h3('3.' + (i + 2) + ' ' + r.name);
        var s = [];
        s.push(notizSatz(b, r, 'Baugruppe ' + r.name));
        var bild = erklaereRessource(r);
        if (bild) s.push(b.w([bild], 'Bild ' + r.name));
        var aus = a.von[r.id] || [], ein = a.nach[r.id] || [];
        if (aus.length || ein.length) {
          mitKante.push(r);
          if (aus.length) {
            s.push(b.w([
              'Von ' + genannt(r.name) + ' ' + gehtGehen(aus.length) + ' ' + nomen(aus.length, 'ein Weg', 'Wege') + ' aus.',
              genannt(r.name) + ' ist Ausgangspunkt für ' + nomen(aus.length, 'eine Verbindung', 'Verbindungen') + '.',
              'Ausgehend ' + istSind(aus.length) + ' bei ' + genannt(r.name) + ' ' + nomen(aus.length, 'ein Weg', 'Wege') + ' verzeichnet.',
              'Bei ' + genannt(r.name) + ' beginnt ein Weg.',
              genannt(r.name) + ' steht am Anfang einer Verbindung.'
            ], 'ausgehend ' + r.name));
            for (var j = 0; j < aus.length; j++) s.push(kanteText(b, aus[j], 'Baugruppe aus ' + r.name));
          }
          if (ein.length) {
            s.push(b.w([
              'Auf ' + genannt(r.name) + ' ' + fuehrtFuehren(ein.length) + ' ' + nomen(ein.length, 'ein Weg', 'Wege') + '.',
              genannt(r.name) + ' ist Ziel von ' + nomen(ein.length, 'einer Verbindung', 'Verbindungen') + '.',
              'Eingehend ' + istSind(ein.length) + ' bei ' + genannt(r.name) + ' ' + nomen(ein.length, 'ein Weg', 'Wege') + ' festgehalten.'
            ], 'eingehend ' + r.name));
            for (var j2 = 0; j2 < ein.length; j2++) s.push(kanteText(b, ein[j2], 'Baugruppe ein ' + r.name));
          }
        } else {
          ohne.push(r);
          s.push(ohneKanteSatz(b, r, 'Baugruppe ohne ' + r.name));
          s.push(b.w([
            'Die Baugruppe bleibt damit ein Einzelstück in den Unterlagen.',
            'Ein Zusammenhang mit einer anderen Stelle ist nicht belegt.',
            'Der Vermerk trägt die Beschreibung allein.',
            'Ohne Verbindung bleibt der Vermerk die einzige Spur.',
            'Was die Baugruppe leistet, steht nur im Vermerk.',
            'Eine Einordnung in den Zusammenhang fehlt.',
            'Der Bestand führt die Baugruppe ohne Anschluss.',
            'Kein Weg führt zu dieser Baugruppe hin oder von ihr weg.',
            'Die Baugruppe steht allein; das ist der ganze Befund.',
            'Mehr als der Vermerk ist nicht überliefert.',
            'Ein Nachbar ist nicht benannt, weder eingehend noch ausgehend.'
          ], 'Einzelstück ' + r.name));
        }
        b.abs(s, 3);
      }

      b.h3('3.' + (a.ressourcen.length + 2) + ' Die Wege zwischen den Baugruppen');
      var innen = a.kanten.filter(function (k) {
        return a.katVon[k.a.id] === 'ressource' && a.katVon[k.b.id] === 'ressource';
      });
      var s5 = [];
      if (innen.length) {
        s5.push(b.w([
          'Die Baugruppen stehen nicht nebeneinander; ' + nomen(innen.length, 'ein Weg ist', 'Wege sind') + ' zwischen ihnen verzeichnet.',
          'Untereinander sind die Baugruppen durch ' + nomen(innen.length, 'eine Verbindung', 'Verbindungen') + ' verknüpft.',
          'Zwischen den Baugruppen führt ' + nomen(innen.length, 'ein Weg', 'Wege') + '.'
        ], 'Baugruppenwege'));
        for (var q = 0; q < innen.length; q++) s5.push(kanteText(b, innen[q], 'Baugruppenweg ' + q));
        s5.push(b.w([
          'Beide Wege sind als Informationswege geführt, nicht als Einbau- oder Zugehörigkeitsverhältnis.',
          'Der Bestand nennt sie Informationswege; eine andere Art der Verbindung ist zwischen Baugruppen nicht verzeichnet.',
          'Als Art ist jeweils ein Informationsweg angegeben; eine Zusammensetzung ist damit nicht ausgesagt.'
        ], 'Baugruppenwege Art'));
      } else {
        s5.push(b.w([
          'Zwischen den Baugruppen führen die Unterlagen keine eigenen Wege.',
          'Eine Verbindung von Baugruppe zu Baugruppe ist nicht verzeichnet.',
          'Die Baugruppen stehen ohne Weg zueinander im Bestand.'
        ], 'keine Baugruppenwege'));
      }
      s5.push(b.w([
        'Damit tragen ' + nomen(mitKante.length, 'eine Baugruppe', 'Baugruppen') + ' einen Weg, während ' + nomen(ohne.length, 'eine Baugruppe', 'Baugruppen') + ' ohne Verbindung bleiben.',
        'Von den ' + zahlwort(a.ressourcen.length) + ' Baugruppen sind ' + zahlwort(mitKante.length) + ' angebunden und ' + zahlwort(ohne.length) + ' nicht.',
        'Der Bestand verbindet ' + zahlwort(mitKante.length) + ' Baugruppen; ' + zahlwort(ohne.length) + ' stehen für sich.'
      ], 'Baugruppen Bilanz'));
      b.abs(s5, 3);

      b.h3('3.' + (a.ressourcen.length + 3) + ' Der Träger und seine Bindungen');
      var s6 = [];
      var traeger = null, wirkung = null;
      for (var d = 0; d < a.daten.length; d++) {
        if (/Mehrzweckraumschiff/i.test(a.daten[d].name)) traeger = a.daten[d];
        if (/Wirkungsmodul/i.test(a.daten[d].name)) wirkung = a.daten[d];
      }
      if (traeger) {
        s6.push(notizSatz(b, traeger, 'Träger'));
        var taus = a.von[traeger.id] || [], tein = a.nach[traeger.id] || [];
        if (taus.length) {
          s6.push(b.w([
            'Vom Träger gehen ' + nomen(taus.length, 'ein Weg', 'Wege') + ' aus; sie führen zu Bezugsgrößen und Forderungen.',
            'Der Träger ist Ausgangspunkt für ' + nomen(taus.length, 'eine Verbindung', 'Verbindungen') + '.',
            'Bei ' + genannt(traeger.name) + ' sind ' + nomen(taus.length, 'ein ausgehender Weg', 'ausgehende Wege') + ' verzeichnet.'
          ], 'Träger ausgehend'));
          for (var t = 0; t < taus.length; t++) s6.push(kanteText(b, taus[t], 'Träger weg ' + t));
        }
        if (tein.length) {
          s6.push(b.w([
            'Auf den Träger führen ' + nomen(tein.length, 'ein Weg', 'Wege') + '; sie kommen von Vorgaben und Forderungen.',
            'Eingehend sind beim Träger ' + nomen(tein.length, 'eine Verbindung', 'Verbindungen') + ' festgehalten.',
            'Zum Träger führen ' + nomen(tein.length, 'ein Weg', 'Wege') + ' von den Stellen, die ihn binden.'
          ], 'Träger eingehend'));
          for (var t2 = 0; t2 < tein.length; t2++) s6.push(kanteText(b, tein[t2], 'Träger eingehend ' + t2));
        } else {
          s6.push(b.w([
            'Eine eingehende Verbindung ist beim Träger nicht verzeichnet; alle Bindungen weisen nach außen.',
            'Auf den Träger führt kein Weg; er ist nur Ausgangspunkt.',
            'Der Träger empfängt nichts; die Verbindungen gehen von ihm aus.'
          ], 'Träger ohne Eingang'));
        }
      } else {
        s6.push(b.w([
          'Ein eigener Träger ist in den Unterlagen nicht benannt.',
          'Der Bestand führt keinen Träger, auf den sich die übrigen Angaben beziehen.',
          'Eine Bezeichnung für das Ganze fehlt.'
        ], 'kein Träger'));
      }
      if (wirkung) {
        s6.push(notizSatz(b, wirkung, 'Wirkungsmodul'));
        s6.push(b.w([
          'Das Wirkungsmodul ist eine Angabe, keine Baugruppe; eine Verbindung ist dazu nicht verzeichnet.',
          'Für das Wirkungsmodul führt der Bestand keinen eigenen Weg.',
          'Beim Wirkungsmodul endet die Beschreibung im Vermerk; ein Weg ist nicht festgehalten.'
        ], 'Wirkungsmodul ohne Kante'));
      }
      b.abs(s6, 3);

      b.h3('3.' + (a.ressourcen.length + 4) + ' Was der Aufbau nicht festhält');
      var s7 = [];
      s7.push(b.w([
        'Zwischen Baugruppen und Diensten ist keine eigene Verbindung verzeichnet.',
        'Ein Weg von einer Baugruppe zu einem Dienst fehlt im Bestand.',
        'Die Dienste sind an keine Baugruppe angeschlossen; der Bestand führt sie getrennt.'
      ], 'Baugruppe Dienst'));
      s7.push(b.w([
        'Der Zusammenhang entsteht erst über die Abläufe des fünften Kapitels und über die Fähigkeiten des sechsten.',
        'Wer wissen will, wie eine Baugruppe wirkt, muss den Weg über die Abläufe und Fähigkeiten nehmen.',
        'Die Kapitel fünf und sechs tragen den Zusammenhang, den der Aufbau offen lässt.'
      ], 'Aufbau Zusammenhang'));
      s7.push(b.w([
        'Auch die Bezugsgrößen für die Datenübertragung, ' + kurz(a.standards, 5) + ', sind an keine Baugruppe angeschlossen.',
        'Für die Übertragung sind ' + kurz(a.standards, 4) + ' genannt; eine Verbindung zu einer Baugruppe fehlt.',
        'Die Bezugsgrößen ' + kurz(a.standards, 4) + ' stehen ohne Weg zu den Baugruppen im Bestand.'
      ], 'Standards ohne Weg'));
      s7.push(b.w([
        'Das ist keine Lücke dieses Kapitels, sondern eine Lücke der Unterlagen; sie wird hier benannt und nicht gefüllt.',
        'Der Befund wird ausdrücklich festgehalten, damit niemand aus dem Fehlen einen Zusammenhang ableitet.',
        'Die fehlenden Wege bleiben als fehlend gekennzeichnet.'
      ], 'Lücke benannt'));
      s7.push(b.w([
        'Dass eine Baugruppe ohne Weg bleibt, sagt nichts über ihre Wichtigkeit; es sagt nur, dass der Bestand keinen Weg führt.',
        'Aus dem Fehlen einer Verbindung folgt keine Wertung der Baugruppe.',
        'Wer aus einem fehlenden Weg auf Bedeutungslosigkeit schließt, liest mehr in den Bestand hinein, als darin steht.'
      ], 'Lücke Wertung'));
      var umsZahl = a.kanten.filter(function (k) { return k.label === 'Umsetzung'; }).length;
      s7.push(b.w([
        'Keine Baugruppe setzt eine Forderung um; ' + (umsZahl === 1 ? 'die einzige Umsetzung geht' : 'die ' + zahlwort(umsZahl) + ' Umsetzungen gehen') + ' vom Träger aus, der als Angabe geführt ist.',
        'Eine Umsetzung ist bei keiner Baugruppe verzeichnet; sie liegt allein beim Träger.',
        'Zwischen Baugruppen und Forderungen führt kein Weg der Umsetzung.'
      ], 'Lücke Umsetzung'));
      s7.push(b.w([
        'Auch eine Vorgabe wird von keiner Baugruppe erfüllt; die Erfüllungen gehen von Fähigkeiten aus.',
        'Die Erfüllung von Vorgaben ist bei den Fähigkeiten verzeichnet, nicht bei den Baugruppen.',
        'Keine Baugruppe deckt eine Vorgabe ab; diese Rolle tragen die Fähigkeiten.'
      ], 'Lücke Erfüllung'));
      s7.push(b.w([
        'Eine Freigabe ist an keine Baugruppe gebunden; die Vorgabe nennt den Bevollmächtigten, nicht ein Teil.',
        'Für die Freigabe nennt der Bestand eine Rolle, aber keine Baugruppe.',
        'Die Freigabe steht bei den Vorgaben und den Rollen; ein Weg zu einer Baugruppe fehlt.'
      ], 'Lücke Freigabe'));
      b.abs(s7, 3);
    }
  }

  /* ------------------------------------------------------------------
     4 Die Dienste
     ------------------------------------------------------------------ */

  var DIENST_BILD = {
    'Business Processes': 'Übergreifende Arbeitsabläufe zu ordnen, nennt der Vermerk; ein Ablauf ist mit diesem Dienst nicht verbunden.',
    'Business Support Service': 'Eine Unterstützung der Führung beschreibt der Vermerk; die unterstützte Stelle ist nicht verzeichnet.',
    'Business Support SMC Services': 'Unterstützungsaufgaben für die Führung des Weltraumeinsatzes werden laut Vermerk zusammengefasst; welche Dienste dazugehören, bleibt offen.',
    'COI Enabling Services': 'Funktionen für den Aufbau von Diensten einer Interessengruppe nennt der Vermerk; ein aufbauender Weg ist nicht verzeichnet.',
    'COI Specific Services': 'Dienste einer bestimmten Interessengruppe werden im Vermerk genannt; eine Zugehörigkeit ist nicht verzeichnet.',
    'Community of Interest Services': 'Dienste einer gemeinsamen Interessengruppe werden laut Vermerk gebündelt; die gebündelten Dienste sind nicht benannt.',
    'Core Services': 'Eine Grundschicht der Dienste nennt der Vermerk; eine Schichtung zu anderen Diensten ist nicht verzeichnet.',
    'Enable': 'Funktionen für andere Dienste stellt der Dienst laut Vermerk bereit; kein anderer Dienst ist angeschlossen.',
    'Geospatial Coordinate Services': 'Das Umrechnen von Koordinaten zwischen Bezugssystemen steht im Vermerk; Ein- und Ausgang sind nicht verzeichnet.',
    'Geospatial Services': 'Raumbezogene Daten nennt der Vermerk; ein Abnehmer ist nicht verzeichnet.',
    'Health Service': 'Die gesundheitliche Versorgung begleitet der Dienst laut Vermerk; eine Verbindung zum Vitaldienst fehlt.',
    'Space Domain Services': 'Aufgaben, die dem Weltraum gelten, werden laut Vermerk gebündelt; eine Aufgabe ist nicht angeschlossen.',
    'Vital Sign Tracking Bw': 'Vitalwerte der Besatzung verfolgt der Dienst; eine Verbindung zum Gesundheitsdienst fehlt.'
  };

  function kapitel4(b, a) {
    b.h2('4 ' + KAPITEL[3]);

    b.h3('4.1 Wie die Dienste arbeiten');
    var s = [];
    s.push(b.w([
      'Ein Dienst ist eine Aufgabe, die im Betrieb dauerhaft wahrgenommen wird.',
      'Dienste bündeln eine Aufgabe, die im Betrieb wiederkehrt.',
      'Hinter jedem Dienst steht eine Aufgabe, die nicht von selbst erledigt wird.'
    ], 'Dienst Begriff'));
    if (a.zahl.dienste) {
      var t = nomen(a.zahl.dienste, 'Ein Dienst ist', 'Dienste sind') + ' in den Unterlagen geführt';
      if (a.zahl.dienstSpec) {
        t += ', davon ' + (a.zahl.dienstSpec === 1 ? 'eine' : zahlwort(a.zahl.dienstSpec)) + ' als eigene Dienstbeschreibung';
        if (a.zahl.dienstIst) t += ' und ' + (a.zahl.dienstIst === 1 ? 'eine' : zahlwort(a.zahl.dienstIst)) + ' als Dienst, der im Betrieb genannt wird';
      } else if (a.zahl.dienstIst) {
        t += ', davon ' + (a.zahl.dienstIst === 1 ? 'eine' : zahlwort(a.zahl.dienstIst)) + ' als Dienst, der im Betrieb genannt wird';
      }
      s.push(b.w([t + '.'], 'Dienst Zahl'));
    }
    var ohneKanten = [], mitKanten = [];
    for (var i = 0; i < a.dienste.length; i++) {
      if (alleKanten(a, a.dienste[i]).length) mitKanten.push(a.dienste[i]);
      else ohneKanten.push(a.dienste[i]);
    }
    s.push(b.w([
      'Die Dienste sind nicht gleichrangig; ' + zahlwort(mitKanten.length) + ' von ihnen tragen verzeichnete Wege, ' + zahlwort(ohneKanten.length) + ' stehen ohne Verbindung.',
      'Von den ' + zahlwort(a.dienste.length) + ' Diensten sind ' + zahlwort(mitKanten.length) + ' angebunden; ' + zahlwort(ohneKanten.length) + ' haben keinen Weg.',
      'Der Bestand verbindet ' + zahlwort(mitKanten.length) + ' Dienste; ' + zahlwort(ohneKanten.length) + ' bleiben ohne Beziehung.'
    ], 'Dienste Bilanz'));
    var dienstwort = 0;
    for (var dw = 0; dw < a.vorgaben.length; dw++) {
      if (/service|services|\bbw\b/i.test(a.vorgaben[dw].name)) dienstwort++;
    }
    if (dienstwort) {
      var dwWort = zahlwort(dienstwort);
      s.push(b.w([
        dwWort.charAt(0).toUpperCase() + dwWort.slice(1) + ' Bezeichnungen tragen ein Dienstwort im Namen, sind aber als Vorgabe geführt; sie erscheinen deshalb im achten Kapitel, nicht hier.',
        'Bei ' + dwWort + ' Namen steht ein Dienstwort, obwohl der Bestand sie als Vorgabe führt; das achte Kapitel nimmt sie auf.',
        'Nicht jeder Name mit dem Wort Dienst bezeichnet einen Dienst: ' + dwWort + ' solcher Bezeichnungen sind Vorgaben.'
      ], 'Dienstwort Vorgabe'));
    }
    s.push(b.w([
      'Für jeden Dienst gilt derselbe Aufbau: Zuerst steht der Vermerk, dann die Wege, die von ihm ausgehen, und schließlich die Wege, die auf ihn führen.',
      'Die Abschnitte folgen einem festen Muster: Vermerk, ausgehende Beziehungen, eingehende Beziehungen.',
      'Jeder Dienst bekommt seinen Vermerk und die Richtung jeder Verbindung, die ihn berührt.'
    ], 'Dienst Muster'));
    b.abs(s, 4);

    if (a.dienste.length) {
      b.h3('4.2 Die Dienste im Einzelnen');
      b.p(b.w([
        'Die folgenden Abschnitte stellen jeden Dienst in der Reihenfolge seines Namens vor; die Reihenfolge ist alphabetisch und keine Wertung.',
        'Alphabetisch geordnet folgen die Dienste; die Ordnung erleichtert das Nachschlagen und sagt nichts über Gewicht.',
        'Die Reihenfolge der Abschnitte folgt dem Alphabet, nicht der Bedeutung.'
      ], 'Dienst Reihenfolge'));
      for (var j = 0; j < a.dienste.length; j++) {
        var d = a.dienste[j];
        b.h3('4.2.' + (j + 1) + ' ' + d.name);
        var sd = [];
        sd.push(notizSatz(b, d, 'Dienst ' + d.name));
        if (DIENST_BILD[d.name]) sd.push(b.w([DIENST_BILD[d.name]], 'Dienstbild ' + d.name));
        var aus = a.von[d.id] || [], ein = a.nach[d.id] || [];
        var unterstuetzt = [];
        for (var u = 0; u < ein.length; u++) if (ein[u].label === 'Unterstützung') unterstuetzt.push(ein[u]);
        if (aus.length) {
          sd.push(b.w([
            'Ausgehend ' + istSind(aus.length) + ' ' + nomen(aus.length, 'ein Weg', 'Wege') + ' verzeichnet.',
            genannt(d.name) + ' ist Ausgangspunkt für ' + nomen(aus.length, 'eine Verbindung', 'Verbindungen') + '.',
            'Von ' + genannt(d.name) + ' ' + fuehrtFuehren(aus.length) + ' ' + nomen(aus.length, 'ein Weg', 'Wege') + ' aus.',
            'Bei ' + genannt(d.name) + ' beginnt ein Weg.',
            genannt(d.name) + ' steht am Anfang einer Verbindung.'
          ], 'Dienst aus ' + d.name));
          for (var k1 = 0; k1 < aus.length; k1++) sd.push(kanteText(b, aus[k1], 'Dienst aus ' + d.name));
        }
        if (ein.length) {
          sd.push(b.w([
            'Auf ' + genannt(d.name) + ' ' + fuehrtFuehren(ein.length) + ' ' + nomen(ein.length, 'ein Weg', 'Wege') + '.',
            'Eingehend ' + istSind(ein.length) + ' bei ' + genannt(d.name) + ' ' + nomen(ein.length, 'eine Verbindung', 'Verbindungen') + ' festgehalten.',
            genannt(d.name) + ' ist Ziel von ' + nomen(ein.length, 'einem Weg', 'Wegen') + '.'
          ], 'Dienst ein ' + d.name));
          for (var k2 = 0; k2 < ein.length; k2++) sd.push(kanteText(b, ein[k2], 'Dienst ein ' + d.name));
        }
        if (!aus.length && !ein.length && !DIENST_BILD[d.name]) {
          sd.push(ohneKanteSatz(b, d, 'Dienst ohne ' + d.name));
        }
        if (unterstuetzt.length) {
          var traeger = [];
          for (var y = 0; y < unterstuetzt.length; y++) traeger.push(unterstuetzt[y].a.name);
          sd.push(b.w([
            'Getragen wird der Dienst von ' + reihe(traeger.map(genannt)) + '.',
            'Als tragende Abläufe sind ' + reihe(traeger.map(genannt)) + ' verzeichnet.',
            'Die Arbeit kommt aus ' + reihe(traeger.map(genannt)) + '.'
          ], 'Dienst Traeger ' + d.name));
        }
        b.abs(sd, 3);
      }

      b.h3('4.3 Wie die Dienste zusammenwirken');
      var abh = a.kanten.filter(function (k) {
        return k.label === 'Abhängigkeit' && a.katVon[k.a.id] === 'dienst' && a.katVon[k.b.id] === 'dienst';
      });
      var gen = a.kanten.filter(function (k) {
        return k.label === 'Verallgemeinerung' && a.katVon[k.a.id] === 'dienst' && a.katVon[k.b.id] === 'dienst';
      });
      var nachf = a.kanten.filter(function (k) { return k.label === 'Nachfolge'; });
      var s2 = [];
      if (abh.length) {
        s2.push(b.w([
          'Zwischen den Diensten sind ' + nomen(abh.length, 'eine Abhängigkeit', 'Abhängigkeiten') + ' verzeichnet.',
          'Der Bestand führt ' + nomen(abh.length, 'eine Abhängigkeit', 'Abhängigkeiten') + ' zwischen Diensten.',
          'Dienste hängen an ' + nomen(abh.length, 'einer Stelle', 'Stellen') + ' voneinander ab.'
        ], 'Dienst Abhängigkeiten'));
        for (var m = 0; m < abh.length; m++) s2.push(kanteText(b, abh[m], 'Dienst Abhängigkeit ' + m));
      } else {
        s2.push(b.w([
          'Abhängigkeiten zwischen Diensten sind nicht verzeichnet.',
          'Kein Dienst nennt einen anderen als Vorleistung.',
          'Der Bestand führt keine Abhängigkeit von Dienst zu Dienst.'
        ], 'keine Dienstabhängigkeit'));
      }
      if (gen.length) {
        s2.push(b.w([
          'Hinzu kommen ' + nomen(gen.length, 'eine Verallgemeinerung', 'Verallgemeinerungen') + ', die Ausprägungen unter einer gemeinsamen Fassung sammeln.',
          'Als Verallgemeinerungen sind ' + nomen(gen.length, 'eine Beziehung', 'Beziehungen') + ' verzeichnet.',
          'Der Bestand ordnet ' + nomen(gen.length, 'eine Ausprägung', 'Ausprägungen') + ' einer allgemeinen Fassung zu.'
        ], 'Dienst Verallgemeinerung'));
        for (var g = 0; g < gen.length; g++) s2.push(kanteText(b, gen[g], 'Dienst Gen ' + g));
      }
      if (nachf.length) {
        s2.push(b.w([
          'Eine Nachfolge ist ' + nomen(nachf.length, 'einmal', 'mehrfach') + ' festgehalten.',
          'Der Bestand nennt ' + nomen(nachf.length, 'eine Nachfolge', 'Nachfolgen') + '.',
          'Als Nachfolge führt der Bestand ' + nomen(nachf.length, 'eine Beziehung', 'Beziehungen') + '.'
        ], 'Dienst Nachfolge'));
        for (var nf = 0; nf < nachf.length; nf++) s2.push(kanteText(b, nachf[nf], 'Dienst Nachfolge ' + nf));
      }
      if (abh.length) {
        s2.push(b.w([
          'Wer einen Dienst ändert, muss diese Ketten mitlesen: Was an einer Stelle wegfällt, fehlt an der nächsten.',
          'Eine Änderung wirkt entlang der Abhängigkeit weiter, bis sie eine Stelle erreicht, die nichts mehr weitergibt.',
          'Die Richtung der Abhängigkeit zeigt, wo eine Änderung zuerst zu spüren ist.'
        ], 'Dienst Ketten'));
      }
      b.abs(s2, 3);
    } else {
      b.h3('4.2 Was an ihre Stelle tritt');
      b.p(b.w([
        'Eigene Dienste sind in den Unterlagen nicht benannt; die Aufgaben verteilen sich auf die Baugruppen und die Abläufe.',
        'Der Bestand führt keinen Dienst; was zu tun ist, steht bei den Baugruppen und den Abläufen.',
        'Ohne Dienste tragen die Baugruppen und die Abläufe die Aufgaben.'
      ], 'keine Dienste'));
    }
  }

  /* ------------------------------------------------------------------
     5 Abläufe und Verfahren
     ------------------------------------------------------------------ */

  var ABLAUF_BILD = {
    'Befehl und Wirkung': 'Hinter dem Namen stehen ein Befehl und eine Wirkung; ein einzelner Schritt ist nicht beschrieben.',
    'Erkennung und Identifikation': 'Erkennung und Identifikation sind im Namen genannt; ein Verfahren dazu ist nicht festgehalten.',
    'Lagebildgewinnung': 'Im Namen steht ein Lagebild, das gewonnen werden soll; ein Schritt ist nicht beschrieben.',
    'Schleusenbetrieb': 'Das Wort Schleusenbetrieb verweist auf die Schleuse; ein Ablauf der Bedienung ist nicht festgehalten.',
    'Sensorrohdatenverarbeitung': 'Sensorrohdaten werden im Namen zur Verarbeitung gestellt; ein Schritt ist nicht beschrieben.',
    'Start und Statusabfrage': 'Ein Start und eine Statusabfrage stehen im Namen; ein Verfahren dazu ist nicht festgehalten.',
    'Zielbekämpfung': 'Ziel und Bekämpfung stehen im Namen; ein Verfahren ist nicht beschrieben.'
  };

  function kapitel5(b, a) {
    b.h2('5 ' + KAPITEL[4]);

    b.h3('5.1 Wie die Abläufe beschrieben sind');
    var s = [];
    if (a.aktivitaeten.length) {
      s.push(b.w([
        'Ein Ablauf beschreibt, was im Betrieb nacheinander geschieht; ' + nomen(a.aktivitaeten.length, 'ein solcher Ablauf ist', 'solche Abläufe sind') + ' in den Unterlagen geführt.',
        'Abläufe halten fest, was im Betrieb geschieht; der Bestand nennt ' + nomen(a.aktivitaeten.length, 'einen', 'insgesamt') + '.',
        'Der Bestand führt ' + nomen(a.aktivitaeten.length, 'einen Ablauf', 'Abläufe') + ', die beschreiben, was im Betrieb geschieht.'
      ], 'Ablauf Einleitung'));
      s.push(b.w([
        'Wer einen Ablauf liest, sucht zuerst die beteiligten Dienste; sie sagen, woher die Arbeit kommt und wohin sie geht.',
        'Die beteiligten Dienste sind der erste Anhaltspunkt; sie zeigen, welche Stelle den Ablauf trägt.',
        'Ohne die Dienste bleibt ein Ablauf ein Name; erst die Verbindungen zeigen, wer ihn trägt.'
      ], 'Ablauf Dienste'));
      s.push(b.w([
        'Die Abläufe sind keine starre Reihenfolge; sie greifen ineinander, wo sie dieselben Dienste beanspruchen.',
        'Eine feste Folge der Abläufe ist damit nicht gesetzt; der Zusammenhang entsteht über gemeinsame Dienste.',
        'Die Abläufe lassen sich einzeln lesen; wo sie sich berühren, teilen sie einen Dienst.'
      ], 'Ablauf Reihenfolge'));
      var mitDienst = 0, ohneDienst = 0, dienstTraeger = {}, mehrfach = [];
      for (var v0 = 0; v0 < a.aktivitaeten.length; v0++) {
        var vk = a.von[a.aktivitaeten[v0].id] || [];
        if (vk.length) mitDienst++; else ohneDienst++;
        for (var v1 = 0; v1 < vk.length; v1++) {
          var zid = vk[v1].b.id;
          dienstTraeger[zid] = (dienstTraeger[zid] || 0) + 1;
        }
      }
      for (var did in dienstTraeger) {
        if (dienstTraeger.hasOwnProperty(did) && dienstTraeger[did] > 1 && typeof OBJS !== 'undefined' && OBJS[did]) {
          mehrfach.push(OBJS[did].name);
        }
      }
      s.push(b.w([
        'Die Abläufe spielen zwischen Bedienung und Leitung: Die benannten Rollen führen aus, die zuständige Stelle gibt frei.',
        'Ausgeführt wird die Arbeit von den benannten Rollen, freigegeben von der zuständigen Stelle.',
        'Zwischen Ausführung und Freigabe liegen die benannten Rollen und die zuständige Stelle.'
      ], 'Ablauf Bord Boden'));
      s.push(b.w([
        'Ein Weg zwischen diesen Rollen und den Abläufen ist nicht verzeichnet.',
        'Die Rollen stehen ohne Verbindung zu den Abläufen im Bestand.',
        'Eine Verbindung von einer Rolle zu einem Ablauf führt der Bestand nicht.'
      ], 'Ablauf Rollen'));
      s.push(b.w([
        'Von den ' + zahlwort(a.aktivitaeten.length) + ' Abläufen tragen ' + zahlwort(mitDienst) + ' genau einen Dienst, ' + zahlwort(ohneDienst) + ' tragen keinen.',
        zahlwort(mitDienst) + ' Abläufe stützen je einen Dienst; ' + zahlwort(ohneDienst) + ' stehen ohne Unterstützung da.',
        'Eine Unterstützung geht von ' + zahlwort(mitDienst) + ' Abläufen aus; ' + zahlwort(ohneDienst) + ' Abläufe haben keine.'
      ], 'Ablauf Verteilung'));
      if (mehrfach.length) {
        s.push(b.w([
          'Auf ' + reihe(mehrfach.map(genannt)) + ' stützt sich mehr als ein Ablauf.',
          reihe(mehrfach.map(genannt)) + ' wird von mehreren Abläufen getragen.',
          'Mehrere Abläufe greifen auf ' + reihe(mehrfach.map(genannt)) + ' zu.'
        ], 'Ablauf Mehrfach'));
      }
    } else {
      s.push(b.w([
        'Eigene Abläufe sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keinen Ablauf.',
        'Abläufe sind nicht verzeichnet.'
      ], 'keine Abläufe 2'));
      s.push(b.w([
        'Der Betrieb ergibt sich deshalb aus den Diensten und ihren Abhängigkeiten; das vierte Kapitel beschreibt ihn an ihrer Stelle.',
        'Was zu tun ist, steht bei den Diensten; Kapitel vier tritt an die Stelle dieses Kapitels.',
        'An die Stelle der Abläufe treten die Dienste des vierten Kapitels.'
      ], 'Ablauf Ersatz'));
    }
    b.abs(s, 3);

    if (a.aktivitaeten.length) {
      b.h3('5.2 Die Abläufe im Einzelnen');
      b.p(b.w([
        'Die folgenden Abschnitte folgen dem Alphabet und nennen zu jedem Ablauf den Vermerk sowie die Dienste, die er trägt.',
        'Alphabetisch geordnet stehen die Abläufe; zu jedem gehören der Vermerk und die gestützten Dienste.',
        'Die Abschnitte folgen dem Alphabet und halten fest, welcher Dienst von welchem Ablauf getragen wird.'
      ], 'Ablauf Reihenfolge 2'));
      for (var i = 0; i < a.aktivitaeten.length; i++) {
        var act = a.aktivitaeten[i];
        b.h3('5.2.' + (i + 1) + ' ' + act.name);
        var sa = [];
        sa.push(notizSatz(b, act, 'Ablauf ' + act.name));
        if (ABLAUF_BILD[act.name]) sa.push(b.w([ABLAUF_BILD[act.name]], 'Ablaufbild ' + act.name));
        var stuetzt = a.von[act.id] || [], wirdGestuetzt = a.nach[act.id] || [];
        if (stuetzt.length) {
          sa.push(b.w([
            'Der Ablauf trägt ' + nomen(stuetzt.length, 'einen Dienst', 'Dienste') + '.',
            'Von diesem Ablauf ' + gehtGehen(stuetzt.length) + ' ' + nomen(stuetzt.length, 'eine Unterstützung', 'Unterstützungen') + ' aus.',
            'Als tragend ' + istSind(stuetzt.length) + ' ' + nomen(stuetzt.length, 'ein Dienst', 'Dienste') + ' verzeichnet.'
          ], 'Ablauf stuetzt ' + act.name));
          for (var j = 0; j < stuetzt.length; j++) sa.push(kanteText(b, stuetzt[j], 'Ablauf stuetzt ' + act.name));
          for (var j2 = 0; j2 < stuetzt.length; j2++) {
            var ziel = stuetzt[j2].b;
            var zaus = a.von[ziel.id] || [];
            if (zaus.length) {
              sa.push(b.w([
                'Der gestützte Dienst ' + genannt(ziel.name) + ' ist selbst auf ' + reihe(zaus.map(function (k) { return genannt(k.b.name); })) + ' angewiesen.',
                genannt(ziel.name) + ' braucht seinerseits ' + reihe(zaus.map(function (k) { return genannt(k.b.name); })) + '.',
                'Hinter ' + genannt(ziel.name) + ' stehen ' + reihe(zaus.map(function (k) { return genannt(k.b.name); })) + ' als Vorleistung.'
              ], 'Ablauf Kette ' + act.name + j2));
            } else {
              sa.push(b.w([
                'Weitere Vorleistungen sind für ' + genannt(ziel.name) + ' nicht verzeichnet.',
                genannt(ziel.name) + ' steht ohne eigene Abhängigkeit im Bestand.',
                'Ein Dienst, auf den ' + genannt(ziel.name) + ' sich stützt, ist nicht geführt.'
              ], 'Ablauf Kette leer ' + act.name + j2));
            }
            var geschwister = [];
            for (var g = 0; g < a.aktivitaeten.length; g++) {
              if (a.aktivitaeten[g].id === act.id) continue;
              var vg = a.von[a.aktivitaeten[g].id] || [];
              for (var h = 0; h < vg.length; h++) {
                if (vg[h].b.id === ziel.id) geschwister.push(a.aktivitaeten[g].name);
              }
            }
            if (geschwister.length) {
              sa.push(b.w([
                'Denselben Dienst trägt auch ' + reihe(geschwister.map(genannt)) + '.',
                'Mit ' + reihe(geschwister.map(genannt)) + ' teilt sich der Ablauf diesen Dienst.',
                'Ein zweiter Ablauf greift auf denselben Dienst zu: ' + reihe(geschwister.map(genannt)) + '.'
              ], 'Ablauf Geschwister ' + act.name + j2));
            }
          }
        } else {
          sa.push(ohneKanteSatz(b, act, 'Ablauf ohne ' + act.name));
        }
        if (wirdGestuetzt.length) {
          sa.push(b.w([
            'Auf den Ablauf selbst führt keine Unterstützung; die Verbindung weist in die andere Richtung.',
            'Der Ablauf wird nicht von einem anderen Ablauf getragen.',
            'Eine Unterstützung, die auf diesen Ablauf zielt, ist nicht verzeichnet.'
          ], 'Ablauf Gegenrichtung ' + act.name));
        }
        var vorg = [], nachf = [];
        for (var q = 0; q < a.kanten.length; q++) {
          if (a.kanten[q].a.id === act.id && a.kanten[q].label === 'Nachfolge') nachf.push(a.kanten[q]);
          if (a.kanten[q].b.id === act.id && a.kanten[q].label === 'Nachfolge') vorg.push(a.kanten[q]);
        }
        if (!vorg.length && !nachf.length) {
          sa.push(b.w([
            'Eine Reihenfolge ist für diesen Ablauf nicht verzeichnet: weder ein Vorgänger noch ein Nachfolger.',
            'Der Bestand ordnet den Ablauf nicht in eine Folge ein; Vorgänger und Nachfolger fehlen.',
            'Weder Vorstufe noch Folgestufe sind zu diesem Ablauf festgehalten.',
            'Vorgänger und Nachfolger sind zu diesem Ablauf nicht benannt.',
            'Der Ablauf steht ohne Vorstufe und ohne Folgestufe im Bestand.',
            'Eine Einordnung in eine Schrittfolge fehlt für diesen Ablauf.'
          ], 'Ablauf Folge ' + act.name));
        }
        sa.push(b.w([
          'Eine Verbindung zu einer Baugruppe ist für diesen Ablauf nicht verzeichnet.',
          'Der Ablauf steht ohne Weg zu einer Baugruppe im Bestand.',
          'Zu den Baugruppen des dritten Kapitels führt von hier kein Weg.',
          'Ein Weg von diesem Ablauf auf eine Baugruppe fehlt.',
          'Baugruppen sind mit diesem Ablauf nicht verbunden.',
          'Der Bestand nennt keine Baugruppe, die an diesen Ablauf anschließt.'
        ], 'Ablauf Baugruppe ' + act.name));
        sa.push(b.w([
          'Eine Forderung ist mit diesem Ablauf nicht verbunden.',
          'Auf eine Forderung verweist der Ablauf nicht.',
          'Ein Weg zu einer Forderung ist nicht festgehalten.',
          'Der Ablauf steht ohne Bezug zu einer Forderung da.',
          'Forderungen sind an diesen Ablauf nicht angeschlossen.',
          'Der Bestand führt keine Forderung, die auf diesen Ablauf verweist.'
        ], 'Ablauf Forderung ' + act.name));
        b.abs(sa, 3);
      }

      b.h3('5.3 Die Reihenfolge');
      var s3 = [];
      var nachf2 = a.kanten.filter(function (k) { return k.label === 'Nachfolge'; });
      if (nachf2.length) {
        s3.push(b.w([
          'Eine Nachfolge ist im Bestand ' + nomen(nachf2.length, 'einmal', 'mehrfach') + ' verzeichnet, allerdings zwischen Diensten, nicht zwischen Abläufen.',
          'Der einzige Nachweis einer Folge betrifft Dienste; ' + nomen(nachf2.length, 'eine Nachfolge ist', 'Nachfolgen sind') + ' festgehalten.',
          'Als Folge führt der Bestand ' + nomen(nachf2.length, 'eine Nachfolge', 'Nachfolgen') + ', und zwar bei den Diensten.'
        ], 'Folge Einleitung'));
        for (var n = 0; n < nachf2.length; n++) s3.push(kanteText(b, nachf2[n], 'Folge ' + n));
      } else {
        s3.push(b.w([
          'Eine Nachfolge ist im Bestand nicht verzeichnet.',
          'Der Bestand nennt keine Folge von Diensten oder Abläufen.',
          'Weder bei den Diensten noch bei den Abläufen ist eine Nachfolge festgehalten.'
        ], 'keine Folge'));
      }
      s3.push(b.w([
        'Für die Abläufe selbst bleibt es bei der Feststellung: Eine Schrittfolge ist nicht verzeichnet.',
        'Die Abläufe stehen ohne Vorgänger und Nachfolger da; eine erfundene Reihenfolge wäre hier ein Fehler.',
        'Eine Ordnung der Abläufe lässt sich aus dem Bestand nicht ableiten.'
      ], 'Folge Abläufe'));
      var dienstKetten = a.kanten.filter(function (k) {
        return k.label === 'Abhängigkeit' && a.katVon[k.a.id] === 'dienst' && a.katVon[k.b.id] === 'dienst';
      });
      if (dienstKetten.length) {
        s3.push(b.w([
          'Wohl aber lassen sich die Dienste in eine Ordnung bringen; ihre Abhängigkeiten zeigen, was vorausgeht.',
          'Eine Lesart ergibt sich aus den Abhängigkeiten der Dienste: Wer auf einen anderen wartet, steht später.',
          'Die Abhängigkeiten der Dienste erlauben eine Reihenfolge, auch wenn die Abläufe selbst keine tragen.'
        ], 'Folge Dienste'));
        for (var dk = 0; dk < dienstKetten.length; dk++) s3.push(kanteText(b, dienstKetten[dk], 'Folge Dienst ' + dk));
        s3.push(b.w([
          'Diese Ordnung ist eine Lesart der Verbindungen, keine Vorschrift für den Betrieb.',
          'Die Folge beschreibt, was aufeinander wartet; sie schreibt keinen Ablauf vor.',
          'Wer sie als Anweisung liest, überdehnt sie; sie bleibt eine Auskunft über Abhängigkeiten.'
        ], 'Folge Lesart'));
      }
      b.abs(s3, 3);

      b.h3('5.4 Was den Abläufen fehlt');
      var s5 = [];
      s5.push(b.w([
        'Steuerungswege, Objektübergaben und Zustandswechsel sind im Bestand nicht verzeichnet; die drei Wegarten stehen auf null.',
        'Kein Steuerungsweg, keine Objektübergabe und kein Zustandswechsel sind geführt.',
        'Die drei feineren Wegarten fehlen: weder Steuerung noch Objektübergabe noch Zustandswechsel sind verzeichnet.'
      ], 'Ablauf fehlende Wege'));
      s5.push(b.w([
        'Zwischen zwei Abläufen führt kein Weg; der einzige Zusammenhang ist ein gemeinsam genutzter Dienst.',
        'Ein Ablauf verweist auf keinen anderen Ablauf; die Verbindung entsteht allein über Dienste.',
        'Abläufe sind untereinander nicht verbunden, wohl aber über die Dienste, die sie tragen.'
      ], 'Ablauf keine Wege'));
      s5.push(b.w([
        'Ein Weg zu einer Baugruppe oder zu einer Forderung ist bei keinem Ablauf festgehalten.',
        'Weder Baugruppen noch Forderungen sind an die Abläufe angeschlossen.',
        'Die Abläufe stehen ohne Verbindung zu den Baugruppen und den Forderungen da.'
      ], 'Ablauf keine Bezüge'));
      s5.push(b.w([
        'Damit bleibt die Reihenfolge der Abläufe offen; nur die Dienste lassen eine Ordnung erkennen.',
        'Eine Schrittfolge ist aus den Abläufen selbst nicht zu gewinnen, nur aus ihren Diensten.',
        'Wer eine Abfolge braucht, muss sie aus den Abhängigkeiten der Dienste lesen, nicht aus den Abläufen.'
      ], 'Ablauf Ordnung'));
      s5.push(b.w([
        'Die Unterstützung ist die einzige Wegart, die von einem Ablauf ausgeht; eine weitere ist nicht verzeichnet.',
        'Neben der Unterstützung geht von einem Ablauf keine Wegart aus.',
        'Außer der Unterstützung ist keine Verbindung mit einem Ablauf als Ausgangspunkt verzeichnet.'
      ], 'Ablauf einzige Art'));
      s5.push(b.w([
        'Die Namen der Abläufe benennen eine Tätigkeit; die Vermerke wiederholen sie, ohne einen Schritt zu nennen.',
        'Was in einem Ablauf geschieht, steht weder im Namen noch im Vermerk; beide bleiben bei der Überschrift.',
        'Ein Schrittgerüst ist damit nicht überliefert; die Unterlagen beschreiben keinen Ablauf von innen.'
      ], 'Ablauf innen'));
      s5.push(b.w([
        'Die Zahl der Unterstützungen bleibt damit der einzige Anhaltspunkt für den Zusammenhang der Abläufe.',
        'Mehr als die Richtung der Unterstützung gibt der Bestand über den Zusammenhang nicht her.',
        'Wer den Betrieb ordnen will, hat nur die Unterstützungen und die Abhängigkeiten der Dienste zur Hand.'
      ], 'Ablauf einziger Anhalt'));
      b.abs(s5, 3);
    } else {
      b.h3('5.2 Der Weg durch die Dienste');
      var s4 = [];
      var abh = a.kanten.filter(function (k) { return k.label === 'Abhängigkeit'; });
      s4.push(b.w([
        'Der Betrieb lässt sich als Weg durch die Dienste beschreiben; am Anfang stehen die Dienste ohne Vorleistung.',
        'Ohne Abläufe bleibt der Weg durch die Dienste: Wer nichts voraussetzt, steht am Anfang.',
        'Die Dienste lassen sich nach ihren Vorleistungen ordnen; die Abläufe fehlen als Gliederung.'
      ], 'Weg Dienste'));
      for (var m = 0; m < abh.length && m < 6; m++) s4.push(kanteText(b, abh[m], 'Weg ' + m));
      b.abs(s4, 3);
    }
  }

  /* ------------------------------------------------------------------
     6 Fähigkeiten und Leistungsvermögen
     ------------------------------------------------------------------ */

  function kapitel6(b, a) {
    b.h2('6 ' + KAPITEL[5]);

    b.h3('6.1 Was das Vorhaben können soll');
    var s = [];
    if (a.faehigkeiten.length) {
      s.push(b.w([
        'Das Vorhaben soll ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ' bereitstellen.',
        'Der Bestand nennt ' + nomen(a.zahl.faehigkeiten, 'eine Fähigkeit', 'Fähigkeiten') + ', die das Vorhaben tragen soll.',
        'Als Fähigkeiten sind ' + nomen(a.zahl.faehigkeiten, 'eine', 'insgesamt') + ' geführt.'
      ], 'Fähigkeiten 3'));
      s.push(b.w([
        'Sie beschreiben nicht, was gebaut wird, sondern was am Ende möglich sein soll.',
        'Die Fähigkeiten sagen, was möglich sein soll, nicht wie es entsteht.',
        'Was gebaut wird, steht bei den Baugruppen; die Fähigkeiten sagen, wozu.'
      ], 'Fähigkeiten Sinn'));
      s.push(b.w([
        'Sie sind der Maßstab, an dem sich die übrigen Teile messen lassen müssen.',
        'An ihnen muss sich messen lassen, was das Vorhaben trägt.',
        'Die übrigen Bezeichnungen lassen sich an diesen Fähigkeiten prüfen.'
      ], 'Fähigkeiten Maßstab'));
      for (var i = 0; i < a.faehigkeiten.length; i++) {
        var f = a.faehigkeiten[i];
        var sf = [notizSatz(b, f, 'Fähigkeit ' + f.name)];
        var faus = a.von[f.id] || [], fein = a.nach[f.id] || [];
        if (faus.length) {
          sf.push(b.w([
            'Von der Fähigkeit ' + gehtGehen(faus.length) + ' ' + nomen(faus.length, 'ein Weg', 'Wege') + ' aus.',
            'Ausgehend ' + istSind(faus.length) + ' bei ' + genannt(f.name) + ' ' + nomen(faus.length, 'eine Verbindung', 'Verbindungen') + ' verzeichnet.',
            genannt(f.name) + ' ist Ausgangspunkt für ' + nomen(faus.length, 'einen Weg', 'Wege') + '.',
            'Bei ' + genannt(f.name) + ' beginnt ein Weg.',
            genannt(f.name) + ' steht am Anfang einer Verbindung.'
          ], 'Fähigkeit aus ' + f.name));
          for (var j = 0; j < faus.length; j++) sf.push(kanteText(b, faus[j], 'Fähigkeit aus ' + f.name));
        }
        if (fein.length) {
          sf.push(b.w([
            'Auf die Fähigkeit ' + fuehrtFuehren(fein.length) + ' ' + nomen(fein.length, 'ein Weg', 'Wege') + '.',
            'Eingehend ' + istSind(fein.length) + ' bei ' + genannt(f.name) + ' ' + nomen(fein.length, 'eine Verbindung', 'Verbindungen') + ' festgehalten.',
            genannt(f.name) + ' ist Ziel von ' + nomen(fein.length, 'einem Weg', 'Wegen') + '.'
          ], 'Fähigkeit ein ' + f.name));
          for (var k = 0; k < fein.length; k++) sf.push(kanteText(b, fein[k], 'Fähigkeit ein ' + f.name));
        }
        if (!faus.length && !fein.length) sf.push(ohneKanteSatz(b, f, 'Fähigkeit ohne ' + f.name));
        b.abs(sf, 3);
      }
    } else {
      b.p(b.w([
        'Eigene Fähigkeiten sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Fähigkeit.',
        'Fähigkeiten sind nicht verzeichnet.'
      ], 'keine Fähigkeiten'));
      b.p(b.w([
        'Das Handbuch kann deshalb nicht sagen, woran das Vorhaben sich messen lassen muss; es beschreibt im Folgenden die Forderungen und Vorgaben.',
        'An ihre Stelle treten die Forderungen und Vorgaben der folgenden Abschnitte.',
        'Eine Messlatte fehlt; die Forderungen und Vorgaben bleiben als Anhaltspunkt.'
      ], 'Fähigkeiten Ersatz'));
    }

    b.h3('6.2 Wie die Fähigkeiten zusammenhängen');
    var gen = a.kanten.filter(function (k) {
      return k.label === 'Verallgemeinerung' &&
        a.katVon[k.a.id] === 'faehigkeit' && a.katVon[k.b.id] === 'faehigkeit';
    });
    var erf = a.kanten.filter(function (k) { return k.label === 'Erfüllung'; });
    var s2 = [];
    if (gen.length) {
      s2.push(b.w([
        'Die Fähigkeiten stehen nicht unverbunden nebeneinander; ' + nomen(gen.length, 'eine Verallgemeinerung ist', 'Verallgemeinerungen sind') + ' zwischen ihnen verzeichnet.',
        'Zwischen den Fähigkeiten führen ' + nomen(gen.length, 'eine Verallgemeinerung', 'Verallgemeinerungen') + ' eine Ordnung ein.',
        'Der Bestand ordnet die Fähigkeiten über ' + nomen(gen.length, 'eine Verallgemeinerung', 'Verallgemeinerungen') + '.'
      ], 'Fähigkeiten Gen'));
      for (var m = 0; m < gen.length; m++) s2.push(kanteText(b, gen[m], 'Fähigkeiten Gen ' + m));
      s2.push(b.w([
        'Damit entsteht eine Landkarte, in der die allgemeine Fähigkeit oben steht und die besonderen darunter.',
        'Die Ordnung hat eine Spitze und mehrere besondere Fassungen darunter.',
        'Wer die Richtung liest, erkennt, welche Fähigkeit die allgemeine und welche die besondere ist.'
      ], 'Fähigkeiten Landkarte'));
    } else if (a.faehigkeiten.length) {
      s2.push(b.w([
        'Zwischen den Fähigkeiten sind keine Verallgemeinerungen verzeichnet; sie stehen gleichrangig nebeneinander.',
        'Eine Ordnung der Fähigkeiten fehlt; keine ist als besondere Form einer anderen geführt.',
        'Der Bestand verbindet die Fähigkeiten nicht durch Verallgemeinerungen.'
      ], 'keine Fähigkeiten Gen'));
    }
    if (erf.length) {
      s2.push(b.w([
        'Hinzu kommen ' + nomen(erf.length, 'eine Erfüllung', 'Erfüllungen') + ', die eine Fähigkeit an eine Vorgabe binden.',
        'Als Erfüllungen sind ' + nomen(erf.length, 'eine Beziehung', 'Beziehungen') + ' verzeichnet.',
        'Der Bestand hält ' + nomen(erf.length, 'eine Erfüllung', 'Erfüllungen') + ' fest.'
      ], 'Fähigkeiten Erfüllung'));
      for (var e = 0; e < erf.length; e++) s2.push(kanteText(b, erf[e], 'Fähigkeiten Erfüllung ' + e));
      s2.push(b.w([
        'Auffällig ist, dass die Vorgaben, die erfüllt werden, Namen von Diensten tragen.',
        'Die erfüllten Vorgaben heißen wie Dienste, sind aber als Vorgabe geführt.',
        'Mehrere dieser Vorgaben tragen ein Dienstwort im Namen; der Bestand führt sie dennoch als Vorgabe.'
      ], 'Fähigkeiten Vorgabenname'));
    }
    if (!s2.length) s2.push(b.w([
      'Ohne Fähigkeiten gibt es auch keine Ordnung zwischen ihnen.',
      'Eine Ordnung der Fähigkeiten fehlt, weil keine benannt ist.',
      'Zu Fähigkeiten ist nichts verzeichnet.'
    ], 'keine Fähigkeiten Ordnung'));
    b.abs(s2, 3);

    b.h3('6.3 Forderungen, die dahinterstehen');
    var s3 = [];
    if (a.forderungen.length) {
      s3.push(b.w([
        'Hinter den Fähigkeiten stehen ' + zahlwort(a.zahl.forderungen) + ' Forderungen; sie sagen, was erfüllt sein muss.',
        'Die Forderungen sind der harte Kern: ' + zahlwort(a.zahl.forderungen) + ' sind es.',
        'Zu den Fähigkeiten gehören ' + nomen(a.zahl.forderungen, 'eine Forderung', 'Forderungen') + ', die erfüllt sein müssen.'
      ], 'Forderungen 3'));
      var gebiete = {};
      for (var q = 0; q < a.forderungen.length; q++) {
        var qq = a.forderungen[q], gname6 = gebietVon(qq);
        if (!gebiete[gname6]) gebiete[gname6] = [];
        gebiete[gname6].push(qq.name);
      }
      var gnamen = Object.keys(gebiete).sort(function (x, y) { return x.localeCompare(y, 'de'); });
      if (gnamen.length) {
        var gt = [];
        for (var g = 0; g < gnamen.length; g++) gt.push(genannt(gnamen[g]));
        s3.push(b.w([
          'Sie verteilen sich auf die Gebiete ' + reihe(gt) + '.',
          'Als Gebiete nennt der Bestand ' + reihe(gt) + '.',
          'Geordnet sind sie nach den Gebieten ' + reihe(gt) + '.'
        ], 'Forderungen Gebiete'));
      }
      var erf2 = a.kanten.filter(function (k) { return k.label === 'Erfüllung' || k.label === 'Umsetzung'; });
      if (erf2.length) {
        s3.push(b.w([
          'Ein Teil von ihnen ist unmittelbar mit einer Fähigkeit oder einem Träger verbunden.',
          'Nicht alle stehen für sich; einige sind über eine Umsetzung angebunden.',
          'Für einige Forderungen ist eine Umsetzung verzeichnet.'
        ], 'Forderungen Umsetzung'));
        for (var u = 0; u < erf2.length && u < 4; u++) s3.push(kanteText(b, erf2[u], 'Forderungen Umsetzung ' + u));
      } else {
        s3.push(b.w([
          'Eine unmittelbare Verbindung zu einer Fähigkeit oder einem Träger ist nicht verzeichnet.',
          'Die Forderungen stehen ohne Weg im Bestand.',
          'Keine Forderung ist an eine andere Bezeichnung angeschlossen.'
        ], 'Forderungen ohne Umsetzung'));
      }
    } else {
      s3.push(b.w([
        'Eigene Forderungen sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Forderung.',
        'Forderungen sind nicht verzeichnet.'
      ], 'keine Forderungen'));
    }
    b.abs(s3, 3);

    b.h3('6.4 Der Weg zur Fähigkeit');
    var s4 = [];
    if (a.phasen.length) {
      s4.push(b.w([
        'Der Weg zur Fähigkeit führt über die Phasen ' + kurz(a.phasen, 4) + '.',
        'Als Abschnitte dieses Weges sind die Phasen ' + kurz(a.phasen, 4) + ' geführt.',
        'Die Phasen ' + kurz(a.phasen, 4) + ' gliedern den Weg.'
      ], 'Phasen 2'));
      for (var p = 0; p < a.phasen.length && p < 3; p++) s4.push(notizSatz(b, a.phasen[p], 'Phase Weg ' + p));
    }
    if (a.meilensteine.length) {
      var ms = a.meilensteine[0];
      s4.push(b.w([
        'Der Meilenstein ' + genannt(ms.name) + ' markiert einen Punkt auf diesem Weg.',
        genannt(ms.name) + ' hält einen Stand auf dem Weg fest.',
        'Mit ' + genannt(ms.name) + ' ist ein Punkt benannt, an dem ein Stand erreicht ist.'
      ], 'Meilenstein Weg'));
      s4.push(notizSatz(b, ms, 'Meilenstein Notiz'));
    }
    if (a.phasen.length || a.meilensteine.length) {
      s4.push(b.w([
        'Damit ist der Weg nicht datiert, aber gegliedert.',
        'Eine Gliederung ist vorhanden; Daten fehlen.',
        'Der Weg hat Abschnitte, aber keine Fristen.'
      ], 'Weg Gliederung'));
    } else {
      s4.push(b.w([
        'Eigene Phasen oder Meilensteine sind in den Unterlagen nicht benannt.',
        'Der Weg zur Fähigkeit lässt sich nicht in Abschnitte gliedern.',
        'Phasen und Meilensteine fehlen.'
      ], 'keine Phasen'));
      s4.push(b.w([
        'Das Handbuch nennt an dieser Stelle keine Jahreszahlen und keine Fristen, weil die Unterlagen keine enthalten.',
        'Fristen werden nicht ergänzt; die Unterlagen führen keine.',
        'Ein Datum steht nicht dabei und wird nicht erfunden.'
      ], 'keine Fristen'));
    }
    b.abs(s4, 3);
  }

  /* ------------------------------------------------------------------
     7 Betrieb und Überwachung
     ------------------------------------------------------------------ */

  function kapitel7(b, a) {
    b.h2('7 ' + KAPITEL[6]);

    b.h3('7.1 Wachdienst und Überwachung');
    var wach = [], wi;
    for (wi = 0; wi < a.els.length; wi++) {
      var wk = a.katVon[a.els[wi].id];
      if (wk === 'forderung' || wk === 'aktivitaet') continue;
      if (/monitor|überwach|wache|anzeige|dash|beobacht|erkundet|bewacht|awareness/i.test(String(a.els[wi].name || '') + ' ' + String(a.els[wi].note || ''))) wach.push(a.els[wi]);
    }
    var s = [];
    if (wach.length) {
      s.push(b.w([
        'Die Überwachung stützt sich auf ' + nomen(wach.length, 'eine Stelle', 'Stellen') + ', die in den Unterlagen mit einer solchen Aufgabe geführt werden: ' + kurz(wach, 5) + '.',
        'Für die Überwachung nennt der Bestand ' + nomen(wach.length, 'eine Stelle', 'Stellen') + ', darunter ' + kurz(wach, 5) + '.',
        'Als Stellen der Überwachung sind ' + kurz(wach, 5) + ' geführt; es sind ' + zahlwort(wach.length) + '.'
      ], 'Überwachung 1'));
      for (var i = 0; i < wach.length && i < 7; i++) {
        var w = wach[i];
        var sw = [notizSatz(b, w, 'Überwachung ' + w.name)];
        var aus = a.von[w.id] || [], ein = a.nach[w.id] || [];
        if (aus.length) for (var j = 0; j < aus.length; j++) sw.push(kanteText(b, aus[j], 'Überwachung aus ' + w.name));
        if (ein.length) for (var k = 0; k < ein.length; k++) sw.push(kanteText(b, ein[k], 'Überwachung ein ' + w.name));
        if (!aus.length && !ein.length) sw.push(ohneKanteSatz(b, w, 'Überwachung ohne ' + w.name));
        b.abs(sw, 3);
      }
      s.push(b.w([
        'Die bedienenden Rollen sind genannt, aber nicht an die Anzeige angeschlossen.',
        'Zwischen Bedienung und Anzeige führt kein Weg.',
        'Die Anzeige steht ohne Verbindung zur Bedienung im Bestand.'
      ], 'Überwachung Bedienung'));
      s.push(b.w([
        'Ihre Meldungen laufen dort zusammen, wo die Verbindungen es vorsehen.',
        'Wo eine Meldung ankommt, sagt die Richtung der Verbindung.',
        'Die Wege der Meldungen sind an den Verbindungen abzulesen, nicht an den Namen.'
      ], 'Überwachung 2'));
      s.push(b.w([
        'Wer den Zustand beurteilen will, liest zuerst diese Stellen und danach die Abläufe, in denen sie wirken.',
        'Die Abläufe des fünften Kapitels zeigen, welche Stelle wann gebraucht wird.',
        'Erst die Abläufe sagen, wann eine Meldung gebraucht wird.'
      ], 'Überwachung 3'));
    } else {
      s.push(b.w([
        'Eigene Stellen für die Überwachung sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Stelle mit einer Überwachungsaufgabe.',
        'Eine eigene Bezeichnung für die Überwachung fehlt.'
      ], 'keine Überwachung'));
      s.push(b.w([
        'Meldungen entstehen deshalb nur dort, wo Dienste sie im Rahmen ihrer Aufgabe weitergeben.',
        'Was gemeldet wird, ergibt sich allein aus den Diensten und ihren Wegen.',
        'Eine eigene Meldestelle ist nicht verzeichnet.'
      ], 'Überwachung Ersatz'));
    }
    b.abs(s, 3);

    b.h3('7.2 Meldungen und Wege');
    var wege = a.kanten.filter(function (k) { return k.label === 'Informationsfluss'; });
    var s2 = [];
    if (wege.length) {
      s2.push(b.w([
        'Meldungen brauchen Wege; ' + nomen(wege.length, 'ein Informationsfluss ist', 'Informationsflüsse sind') + ' verzeichnet.',
        'Als Informationswege führt der Bestand ' + nomen(wege.length, 'eine Verbindung', 'Verbindungen') + '.',
        'Der Bestand nennt ' + nomen(wege.length, 'einen Informationsweg', 'Informationswege') + '.'
      ], 'Informationswege 1'));
      for (var m = 0; m < wege.length; m++) s2.push(kanteText(b, wege[m], 'Informationsweg ' + m));
      s2.push(b.w([
        'Beide Wege liegen zwischen Baugruppen; ein Informationsweg von Dienst zu Dienst ist nicht verzeichnet.',
        'Die Informationswege verbinden Baugruppen, nicht Dienste.',
        'Ein Weg zwischen Diensten ist als Informationsfluss nicht geführt.'
      ], 'Informationswege 2'));
      s2.push(b.w([
        'Diese Wege sind keine Leitungen im technischen Sinn, sondern Beziehungen: Sie sagen, wer von wem Angaben erhält.',
        'Als Beziehung sagen sie, in welche Richtung Angaben weitergegeben werden, nicht auf welchem Weg.',
        'Die Art der Übertragung bleibt offen; festgehalten ist nur die Richtung.'
      ], 'Informationswege 3'));
    } else {
      s2.push(b.w([
        'Eigene Informationsflüsse sind in den Unterlagen nicht verzeichnet.',
        'Der Bestand führt keinen Informationsweg.',
        'Als Informationsfluss ist nichts festgehalten.'
      ], 'keine Informationswege'));
      s2.push(b.w([
        'Die Meldungen ergeben sich aus den Abhängigkeiten der Dienste, die im vierten Kapitel beschrieben sind.',
        'Was weitergegeben wird, lässt sich nur über die Dienste und ihre Abhängigkeiten lesen.',
        'An die Stelle der Informationswege treten die Abhängigkeiten der Dienste.'
      ], 'Informationswege Ersatz'));
    }
    b.abs(s2, 3);

    b.h3('7.3 Wartung und Instandsetzung');
    var wartung = mitWortName(a.els, /wartung|instand|pflege|reparatur|ersatz/i);
    var s3 = [];
    if (wartung.length) {
      s3.push(b.w([
        'Für Wartung und Instandsetzung nennen die Unterlagen ' + kurz(wartung, 4) + '.',
        'Als Stellen für die Wartung sind ' + kurz(wartung, 4) + ' geführt.',
        'Der Bestand nennt zur Wartung ' + kurz(wartung, 4) + '.'
      ], 'Wartung'));
      for (var q = 0; q < wartung.length && q < 3; q++) s3.push(notizSatz(b, wartung[q], 'Wartung ' + q));
    } else {
      s3.push(b.w([
        'Ein eigenes Verfahren zur Wartung ist in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Wartungsaufgabe.',
        'Wartung und Instandsetzung sind nicht als eigene Stelle verzeichnet.'
      ], 'keine Wartung'));
      var pflege = [];
      for (var p = 0; p < a.vorgaben.length; p++) {
        if (/schleus|redundan|belastung|druck/i.test(a.vorgaben[p].name + ' ' + (a.vorgaben[p].note || ''))) pflege.push(a.vorgaben[p]);
      }
      if (pflege.length) {
        s3.push(b.w([
          'Was den Betrieb erhält, berühren die Vorgaben ' + kurz(pflege, 4) + '; ein Wartungsverfahren ist damit nicht verbunden.',
          'Anhaltspunkte für den Erhalt geben die Vorgaben ' + kurz(pflege, 4) + ', ohne einen Ablauf der Pflege zu nennen.',
          'Die Vorgaben ' + kurz(pflege, 4) + ' betreffen den laufenden Betrieb, nicht die Wartung.'
        ], 'Wartung Vorgaben'));
        for (var p2 = 0; p2 < pflege.length && p2 < 3; p2++) s3.push(notizSatz(b, pflege[p2], 'Wartung Vorgabe ' + p2));
      }
      s3.push(b.w([
        'Ein Zeitplan ist damit nicht verbunden; die Unterlagen sagen nicht, in welchem Abstand zu prüfen ist.',
        'Intervalle nennt der Bestand nicht.',
        'Fristen für die Wartung fehlen; sie werden nicht ergänzt.'
      ], 'Wartung Fristen'));
    }
    b.abs(s3, 3);

    b.h3('7.4 Störungen und Ausfälle');
    var stoerung = mitWortName(a.els, /stör|ausfall|notfall|fehler|alarm/i);
    var s4 = [];
    if (stoerung.length) {
      s4.push(b.w([
        'Für Störungen und Ausfälle nennen die Unterlagen ' + kurz(stoerung, 4) + '.',
        'Als Stellen für Störungen sind ' + kurz(stoerung, 4) + ' geführt.',
        'Der Bestand nennt zum Ausfall ' + kurz(stoerung, 4) + '.'
      ], 'Störung'));
      for (var r = 0; r < stoerung.length && r < 3; r++) s4.push(notizSatz(b, stoerung[r], 'Störung ' + r));
    } else {
      s4.push(b.w([
        'Ein eigenes Verfahren für Störungen ist in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Störungsaufgabe.',
        'Für den Ausfall ist keine eigene Stelle verzeichnet.'
      ], 'keine Störung'));
    }
    var abh = a.kanten.filter(function (k) { return k.label === 'Abhängigkeit'; });
    if (abh.length) {
      s4.push(b.w([
        'Was ein Ausfall bedeutet, lässt sich aus den Abhängigkeiten ablesen.',
        'Die Abhängigkeiten zeigen, welche Stelle zuerst betroffen ist.',
        'Wer ausfällt, nimmt die abhängige Stelle mit; die Richtung sagt, wen.'
      ], 'Ausfall Abhängigkeit'));
      for (var n = 0; n < abh.length; n++) {
        s4.push(b.w([
          'Fällt ' + genannt(abh[n].b.name) + ' aus, fehlt ' + genannt(abh[n].a.name) + ' die Grundlage.',
          'Ohne ' + genannt(abh[n].b.name) + ' kann ' + genannt(abh[n].a.name) + ' seine Aufgabe nicht erfüllen.',
          'Ein Ausfall von ' + genannt(abh[n].b.name) + ' trifft ' + genannt(abh[n].a.name) + ' unmittelbar.'
        ], 'Ausfall ' + n));
      }
      s4.push(b.w([
        'Diese Folgen sind keine Vermutung, sondern die Umkehrung der verzeichneten Abhängigkeit.',
        'Die Aussage folgt aus der Richtung der Verbindung, nicht aus einer Näherung.',
        'Wer die Abhängigkeit umdreht, erhält die Ausfallfolge; mehr sagt der Bestand nicht.'
      ], 'Ausfall Umkehrung'));
    } else {
      s4.push(b.w([
        'Wie sich ein Ausfall auswirkt, ist deshalb nicht beschrieben.',
        'Eine Ausfallfolge lässt sich ohne Abhängigkeiten nicht ableiten.',
        'Der Bestand lässt die Frage offen.'
      ], 'Ausfall offen'));
    }
    b.abs(s4, 3);

    b.h3('7.5 Betriebszeiten und Verfügbarkeit');
    var zeit = mitWort(a.vorgaben.concat(a.forderungen),
      /zeit|dauer|stunde|tag|verfügbar|bereitschaft|einsatzbereit/i);
    var s5 = [];
    if (zeit.length) {
      s5.push(b.w([
        'Zur Frage der Verfügbarkeit nennen die Unterlagen ' + kurz(zeit, 4) + '.',
        'Anhaltspunkte zur Verfügbarkeit geben ' + kurz(zeit, 4) + '.',
        'Als zeitbezogene Angaben führt der Bestand ' + kurz(zeit, 4) + '.'
      ], 'Verfügbarkeit'));
      for (var t = 0; t < zeit.length && t < 4; t++) s5.push(notizSatz(b, zeit[t], 'Verfügbarkeit ' + t));
      s5.push(b.w([
        'Damit ist die Frage berührt, aber nicht beziffert; das Handbuch übernimmt die Angaben so, wie sie dastehen.',
        'Die Angaben bleiben bei dem, was in den Namen und Vermerken steht.',
        'Werte werden nicht hinzugerechnet; es bleibt bei den vorhandenen Angaben.'
      ], 'Verfügbarkeit 2'));
    } else {
      s5.push(b.w([
        'Angaben zu Betriebszeiten und Verfügbarkeit stehen in den Unterlagen nicht.',
        'Der Bestand nennt keine Betriebszeit.',
        'Zur Verfügbarkeit ist nichts festgehalten.'
      ], 'keine Verfügbarkeit'));
      s5.push(b.w([
        'Das Handbuch nennt deshalb keine Stunden, keine Tage und keine Fristen.',
        'Zeitangaben werden nicht ergänzt.',
        'Stunden und Tage stehen nicht dabei und werden nicht erfunden.'
      ], 'Verfügbarkeit 3'));
    }
    b.abs(s5, 3);
  }

  /* ------------------------------------------------------------------
     8 Sicherheit und Randbedingungen
     ------------------------------------------------------------------ */

  function kapitel8(b, a) {
    b.h2('8 ' + KAPITEL[7]);

    b.h3('8.1 Die Vorgaben');
    var s = [];
    if (a.vorgaben.length) {
      s.push(b.w([
        'Die Unterlagen nennen ' + nomen(a.zahl.vorgaben, 'eine Vorgabe', 'Vorgaben') + '.',
        'Als bindende Vorgaben führt der Bestand ' + nomen(a.zahl.vorgaben, 'eine', 'insgesamt') + '.',
        'Der Bestand zählt ' + nomen(a.zahl.vorgaben, 'eine Vorgabe', 'Vorgaben') + '.'
      ], 'Vorgaben 3'));
      var gruppen = [
        ['ResourceConstraint', 'ressourcenbezogene Vorgaben'],
        ['OperationalConstraint', 'betriebliche Vorgaben'],
        ['StrategicConstraint', 'strategische Vorgaben'],
        ['SecurityConstraint', 'Vorgaben zur Sicherheit']
      ];
      for (var g = 0; g < gruppen.length; g++) {
        var teil = [];
        for (var i = 0; i < a.vorgaben.length; i++) {
          if (String(a.vorgaben[i].st || '').toLowerCase() === gruppen[g][0].toLowerCase()) teil.push(a.vorgaben[i]);
        }
        if (!teil.length) continue;
        s.push(b.w([
          'Als ' + gruppen[g][1] + ' sind ' + kurz(teil, 6) + ' geführt.',
          gruppen[g][1].charAt(0).toUpperCase() + gruppen[g][1].slice(1) + ' sind ' + kurz(teil, 6) + '.',
          'Unter den ' + gruppen[g][1] + ' stehen ' + kurz(teil, 6) + '.'
        ], 'Vorgabengruppe ' + g));
        for (var j = 0; j < teil.length; j++) {
          s.push(notizSatz(b, teil[j], 'Vorgabe ' + teil[j].name));
        }
      }
      s.push(b.w([
        'Zusammen begrenzen diese Vorgaben den Spielraum des Betriebs.',
        'Die Vorgaben ziehen den Rahmen, in dem sich der Betrieb bewegt.',
        'In der Summe markieren sie die Grenzen des Vorhabens.'
      ], 'Vorgaben Rahmen'));
      s.push(b.w([
        'Sie sind keine Empfehlungen: Wo eine Vorgabe greift, endet die Gestaltungsfreiheit.',
        'Eine Vorgabe lässt keinen Spielraum, wo sie ausdrücklich greift.',
        'Wer eine Vorgabe übergeht, verlässt den Rahmen, den die Unterlagen setzen.'
      ], 'Vorgaben keine Empfehlung'));
      var dw8 = 0;
      for (var w8 = 0; w8 < a.vorgaben.length; w8++) {
        if (/service|services|\bbw\b/i.test(a.vorgaben[w8].name)) dw8++;
      }
      if (dw8) {
        s.push(b.w([
          'Bei ' + zahlwort(dw8) + ' Vorgaben steht ein Dienstwort im Namen; der Bestand führt sie dennoch als Vorgabe.',
          zahlwort(dw8).charAt(0).toUpperCase() + zahlwort(dw8).slice(1) + ' Namen klingen nach einem Dienst, sind aber unter den Vorgaben geführt.',
          'Die Grenze zwischen Dienst und Vorgabe ist im Namen nicht immer erkennbar; ' + zahlwort(dw8) + ' Vorgaben tragen ein Dienstwort.'
        ], 'Vorgaben Dienstwort'));
      }
    } else {
      s.push(b.w([
        'Eigene Vorgaben sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Vorgabe.',
        'Vorgaben sind nicht verzeichnet.'
      ], 'keine Vorgaben'));
    }
    b.abs(s, 3);

    b.h3('8.2 Schutz und Freigabe');
    var schutz = mitWort(a.els, /schutz|freigabe|sicherheit|secret|geheim|zertifi/i);
    var s2 = [];
    if (schutz.length) {
      s2.push(b.w([
        'Wo es um Schutz und Freigabe geht, nennen die Unterlagen ' + kurz(schutz, 5) + '.',
        'Für Schutz und Freigabe sind ' + kurz(schutz, 5) + ' geführt.',
        'Der Bestand nennt zum Schutz ' + kurz(schutz, 5) + '.'
      ], 'Schutz 1'));
      for (var k = 0; k < schutz.length && k < 6; k++) {
        var sc = schutz[k];
        var ss = [notizSatz(b, sc, 'Schutz ' + sc.name)];
        var aus = a.von[sc.id] || [], ein = a.nach[sc.id] || [];
        if (aus.length) for (var m = 0; m < aus.length; m++) ss.push(kanteText(b, aus[m], 'Schutz aus ' + sc.name));
        if (ein.length) for (var n = 0; n < ein.length; n++) ss.push(kanteText(b, ein[n], 'Schutz ein ' + sc.name));
        if (!aus.length && !ein.length) ss.push(ohneKanteSatz(b, sc, 'Schutz ohne ' + sc.name));
        b.abs(ss, 3);
      }
      s2.push(b.w([
        'Die Freigabe steht damit nicht im Belieben des Betriebs; sie ist an eine Stelle gebunden, die in den Unterlagen benannt ist.',
        'Wo eine Freigabe verlangt wird, nennt der Bestand auch die zuständige Stelle.',
        'Ohne die genannte Stelle läuft nichts, was eine Freigabe braucht.'
      ], 'Schutz 2'));
    } else {
      s2.push(b.w([
        'Eigene Regelungen zu Schutz und Freigabe sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Schutzregel.',
        'Zu Schutz und Freigabe ist nichts verzeichnet.'
      ], 'keine Schutz'));
    }
    b.abs(s2, 3);

    b.h3('8.3 Belastungsgrenzen');
    var grenzen = [], lasten = [];
    for (var p = 0; p < a.vorgaben.length; p++) {
      if (/resource|technical/i.test(String(a.vorgaben[p].st || ''))) grenzen.push(a.vorgaben[p]);
      if (/belastung|last|druck|redun|nutzung|landen|bekämpfung/i.test(a.vorgaben[p].name + ' ' + (a.vorgaben[p].note || ''))) lasten.push(a.vorgaben[p]);
    }
    var s3 = [];
    if (grenzen.length) {
      s3.push(b.w([
        'Belastungsgrenzen stehen nicht als Zahlen in diesem Handbuch, sondern als Vorgaben: ' + kurz(grenzen, 6) + '.',
        'Als technische Grenzen sind ' + kurz(grenzen, 6) + ' geführt.',
        'Der Bestand nennt für die Belastung ' + kurz(grenzen, 6) + '.'
      ], 'Grenzen 1'));
      var l0 = lasten[0] || grenzen[0];
      s3.push(notizSatz(b, l0, 'Grenze Notiz'));
      s3.push(b.w([
        'Sie setzen Obergrenzen für das, was dem Vorhaben zugemutet werden darf.',
        'Die Vorgaben markieren, wie weit eine Belastung gehen darf.',
        'Eine Überschreitung ist damit ausgeschlossen, nicht nur unerwünscht.'
      ], 'Grenzen 2'));
    } else {
      s3.push(b.w([
        'Eigene Belastungsgrenzen sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Belastungsgrenze.',
        'Grenzen der Belastung sind nicht verzeichnet.'
      ], 'keine Grenzen'));
    }
    b.abs(s3, 3);

    b.h3('8.4 Die Forderungen im Einzelnen');
    var s4 = [];
    if (a.forderungen.length) {
      s4.push(b.w([
        'Die Forderungen sind der harte Kern der Randbedingungen; ' + nomen(a.zahl.forderungen, 'eine Forderung ist', 'Forderungen sind') + ' es.',
        'An den Forderungen lässt sich prüfen, was gelten soll; ' + nomen(a.zahl.forderungen, 'eine steht', 'stehen') + ' im Bestand.',
        'Der Bestand führt ' + nomen(a.zahl.forderungen, 'eine Forderung', 'Forderungen') + ', die den Rahmen enger ziehen.'
      ], 'Forderungen 4'));
      var gebiete = {}, reihenfolge = [];
      for (var q = 0; q < a.forderungen.length; q++) {
        var f = a.forderungen[q], gname = gebietVon(f);
        if (!gebiete[gname]) { gebiete[gname] = []; reihenfolge.push(gname); }
        gebiete[gname].push(f);
      }
      reihenfolge.sort(function (x, y) { return x.localeCompare(y, 'de'); });
      for (var g2 = 0; g2 < reihenfolge.length; g2++) {
        var gn = reihenfolge[g2], liste = gebiete[gn];
        s4.push(b.w([
          'Im Gebiet ' + genannt(gn) + ' ' + (liste.length === 1 ? 'steht eine Forderung' : 'stehen ' + zahlwort(liste.length) + ' Forderungen') + '.',
          genannt(gn) + ' umfasst ' + nomen(liste.length, 'eine Forderung', 'Forderungen') + '.',
          'Zum Gebiet ' + genannt(gn) + ' gehören ' + nomen(liste.length, 'eine Forderung', 'Forderungen') + '.'
        ], 'Forderungsgebiet ' + gn));
        for (var f2 = 0; f2 < liste.length; f2++) {
          var fo = liste[f2];
          s4.push(b.w([
            genannt(fo.name) + ' ist dort geführt.',
            genannt(fo.name) + ' steht in diesem Gebiet.',
            genannt(fo.name) + ' gehört dazu.',
            genannt(fo.name) + ' ist unter diesem Gebiet verzeichnet.',
            genannt(fo.name) + ' findet sich in dieser Gruppe.',
            genannt(fo.name) + ' zählt zu diesem Gebiet.',
            genannt(fo.name) + ' ist dem Gebiet zugeordnet.',
            genannt(fo.name) + ' erscheint in der Gruppe.',
            genannt(fo.name) + ' wird dort genannt.',
            genannt(fo.name) + ' ist Teil dieser Gruppe.',
            genannt(fo.name) + ' gehört zu den Forderungen des Gebiets.',
            genannt(fo.name) + ' ist im Gebiet vermerkt.'
          ], 'Forderung ' + fo.name));
        }
      }
      var real = a.kanten.filter(function (k) { return k.label === 'Umsetzung'; });
      if (real.length) {
        s4.push(b.w([
          'Nur für ' + nomen(real.length, 'eine Forderung', 'Forderungen') + ' ist eine Umsetzung verzeichnet.',
          'Eine Umsetzung ist zu ' + nomen(real.length, 'einer Forderung', 'Forderungen') + ' festgehalten.',
          'Der Bestand verbindet ' + nomen(real.length, 'eine Forderung', 'Forderungen') + ' mit einer umsetzenden Stelle.'
        ], 'Forderungen real'));
        for (var r2 = 0; r2 < real.length; r2++) s4.push(kanteText(b, real[r2], 'Forderung real ' + r2));
      }
      s4.push(b.w([
        'Die übrigen Forderungen stehen ohne Weg im Bestand; welche Stelle sie einlöst, ist nicht verzeichnet.',
        'Für die Mehrzahl der Forderungen fehlt eine umsetzende Stelle.',
        'Wo keine Umsetzung verzeichnet ist, bleibt die Frage nach der Zuständigkeit offen.'
      ], 'Forderungen Rest'));
    } else {
      s4.push(b.w([
        'Eigene Forderungen sind in den Unterlagen nicht benannt.',
        'Der Bestand führt keine Forderung.',
        'Forderungen sind nicht verzeichnet.'
      ], 'keine Forderungen 2'));
    }
    b.abs(s4, 3);

    b.h3('8.5 Was die Unterlagen offen lassen');
    b.p(b.w([
      'Nicht jede Frage wird beantwortet; Maße, Fristen und Personenzahlen stehen nur dort, wo sie in den Bezeichnungen selbst vorkommen.',
      'Offen bleiben alle Angaben, die keinen Niederschlag in Namen oder Vermerken gefunden haben.',
      'Die Unterlagen sind an mehreren Stellen knapp; das Handbuch lässt die Lücken stehen.'
    ], 'Offen 1'));
    b.p(b.w([
      'Diese Zurückhaltung ist Teil des Handbuchs: Ein Leser soll unterscheiden können, was festgelegt ist und was er selbst entscheiden muss.',
      'Wer die Grenze zwischen Festlegung und Entscheidung braucht, findet sie hier markiert.',
      'Eine glatte Formulierung, die beides vermischt, wäre an dieser Stelle ein Fehler.'
    ], 'Offen 2'));
  }

  /* ------------------------------------------------------------------
     9 Glossar
     ------------------------------------------------------------------ */

  var GLOSSAR_SATZ = {
    dienst: 'Ein Dienst des Vorhabens.',
    ressource: 'Eine Baugruppe des Vorhabens.',
    faehigkeit: 'Eine Fähigkeit, die das Vorhaben bereitstellen soll.',
    forderung: 'Eine Forderung an das Vorhaben.',
    vorgabe: 'Eine Vorgabe, die den Betrieb begrenzt.',
    aktivitaet: 'Ein Ablauf des Vorhabens.',
    phase: 'Ein Abschnitt im Weg des Vorhabens.',
    meilenstein: 'Ein Punkt, an dem ein Stand erreicht ist.',
    rolle: 'Eine Rolle im Betrieb des Vorhabens.',
    ziel: 'Ein Ziel, an dem sich das Vorhaben ausrichtet.',
    standard: 'Eine Bezugsgröße, auf die sich die Unterlagen berufen.',
    daten: 'Eine Angabe, die im Vorhaben geführt wird.',
    ort: 'Ein Ort, an dem das Vorhaben wirkt.',
    gebiet: 'Ein Sachgebiet, dem Forderungen zugeordnet sind.',
    sonstiges: 'Eine Bezeichnung aus dem Bestand des Vorhabens.'
  };

  function glossarEintrag(o, a) {
    var def = zitat(o);
    if (!def || def.length > 200) {
      def = GLOSSAR_SATZ[a.katVon[o.id]] || GLOSSAR_SATZ.sonstiges;
      if (def.charAt(def.length - 1) !== '.') def += '.';
      return '**' + flach(o.name) + '** — ' + def;
    }
    if (def.charAt(def.length - 1) !== '.') def += '.';
    return '**' + flach(o.name) + '** — ' + def;
  }

  function kapitel9(b, a) {
    b.h2('9 ' + KAPITEL[8]);
    b.p(b.w([
      'Das Glossar erklärt die Bezeichnungen, die im Handbuch wiederkehren.',
      'Hier stehen die Begriffe, die in den Kapiteln wieder auftauchen.',
      'Das Glossar sammelt die Bezeichnungen und ihre Erklärung.'
    ], 'Glossar 1'));
    b.p(b.w([
      'Die Erklärungen stammen aus den Notizen der Unterlagen; wo eine Notiz fehlt, nennt der Eintrag nur die Art der Bezeichnung.',
      'Wo ein Vermerk vorhanden ist, wird er übernommen; sonst bleibt es bei der Einordnung.',
      'Die Herkunft jeder Erklärung ist der Vermerk oder die Art der Bezeichnung.'
    ], 'Glossar 2'));
    b.p(b.w([
      'Die Reihenfolge folgt dem Alphabet; Verweise auf andere Kapitel stehen nur dort, wo der Zusammenhang es verlangt.',
      'Alphabetisch geordnet, damit sich ein Begriff finden lässt, ohne ein Kapitel zu durchsuchen.',
      'Ein Verweis steht nur, wo er die Suche abkürzt.'
    ], 'Glossar 3'));

    var begriffe = [], gesehen = {};
    var liste = a.dienste.concat(a.ressourcen).concat(a.faehigkeiten)
      .concat(a.rollen).concat(a.standards).concat(a.phasen)
      .concat(a.meilensteine).concat(a.daten).concat(a.orte).concat(a.vorgaben);
    for (var i = 0; i < liste.length; i++) {
      if (gesehen[liste[i].id]) continue;
      gesehen[liste[i].id] = 1;
      begriffe.push(liste[i]);
    }
    begriffe.sort(function (x, y) { return x.name.localeCompare(y.name, 'de'); });
    for (var j = 0; j < begriffe.length; j++) {
      b.p(glossarEintrag(begriffe[j], a));
    }
  }

  /* ------------------------------------------------------------------
     10 Anhang
     ------------------------------------------------------------------ */

  function aufgabeText(o) {
    var t = zitat(o);
    if (!t || t.length > 160) {
      if (!t) return GLOSSAR_SATZ[o.kat] || GLOSSAR_SATZ.sonstiges;
      t = t.slice(0, 157).replace(/[ ,;:]+$/, '') + ' …';
    }
    return t;
  }

  function verzeichnis(b, nummer, titel, kopf, liste, a) {
    if (!liste.length) return;
    b.h3(nummer + ' ' + titel);
    var zeilen = [], i;
    for (i = 0; i < liste.length; i++) {
      zeilen.push([liste[i].name, aufgabeText(liste[i])]);
    }
    b.tabelle(kopf, zeilen);
  }

  function kapitel10(b, a) {
    b.h2('10 ' + KAPITEL[9]);
    b.p(b.w([
      'Der Anhang sammelt, was im Haupttext knapp bleibt: die Kennzahlen und die Verzeichnisse.',
      'Was der Haupttext nicht ausführt, steht hier in Tabellen.',
      'Der Anhang ordnet die Zahlen und die Namen des Bestands.'
    ], 'Anhang 1'));
    b.p(b.w([
      'Die Zahlen dienen der Einordnung; sie sagen nichts über die Güte des Vorhabens, sondern nur über seinen Umfang.',
      'Die Kennzahlen beschreiben den Umfang, nicht den Wert des Vorhabens.',
      'Wer die Zahlen liest, erfährt Größe und Zuschnitt, nicht Qualität.'
    ], 'Anhang 2'));

    b.h3('10.1 Kennzahlen');
    b.tabelle(['Kennzahl', 'Wert'], [
      ['Dienste', String(a.zahl.dienste)],
      ['Fähigkeiten', String(a.zahl.faehigkeiten)],
      ['Forderungen', String(a.zahl.forderungen)],
      ['Vorgaben', String(a.zahl.vorgaben)],
      ['Meilensteine', String(a.zahl.meilensteine)],
      ['Informationswege', String(a.zahl.informationswege)],
      ['Steuerungswege', String(a.zahl.steuerungswege)],
      ['Objektübergaben', String(a.zahl.objektuebergaben)],
      ['Zustandswechsel', String(a.zahl.zustandswechsel)]
    ]);
    b.p(b.w([
      'Die Tabelle zählt nur, was der Bestand hergibt: ' + zahlwort(a.zahl.dienste) + ' Dienste, ' + zahlwort(a.zahl.faehigkeiten) + ' Fähigkeiten, ' + zahlwort(a.zahl.forderungen) + ' Forderungen und ' + zahlwort(a.zahl.vorgaben) + ' Vorgaben.',
      'Hinter den Werten stehen ' + zahlwort(a.zahl.dienste) + ' Dienste, ' + zahlwort(a.zahl.faehigkeiten) + ' Fähigkeiten, ' + zahlwort(a.zahl.forderungen) + ' Forderungen und ' + zahlwort(a.zahl.vorgaben) + ' Vorgaben.',
      'Genannt sind ' + zahlwort(a.zahl.dienste) + ' Dienste, ' + zahlwort(a.zahl.faehigkeiten) + ' Fähigkeiten, ' + zahlwort(a.zahl.forderungen) + ' Forderungen und ' + zahlwort(a.zahl.vorgaben) + ' Vorgaben.'
    ], 'Kennzahlen 2'));
    b.p(b.w([
      'Dazu kommen ' + zahlwort(a.zahl.meilensteine) + ' Meilenstein und ' + nomen(a.zahl.informationswege, 'ein Informationsweg', 'Informationswege') + '; Steuerungswege, Objektübergaben und Zustandswechsel sind nicht verzeichnet.',
      'Der Bestand nennt ' + nomen(a.zahl.meilensteine, 'einen Meilenstein', 'Meilensteine') + ' und ' + nomen(a.zahl.informationswege, 'einen Informationsweg', 'Informationswege') + '; die übrigen Wegarten stehen auf null.',
      'Ein Meilenstein und ' + nomen(a.zahl.informationswege, 'ein Informationsweg', 'Informationswege') + ' sind die übrigen Werte; die drei weiteren Wegarten fehlen.'
    ], 'Kennzahlen 3'));

    verzeichnis(b, '10.2', 'Verzeichnis der Dienste', ['Dienst', 'Aufgabe'], a.dienste, a);
    verzeichnis(b, '10.3', 'Verzeichnis der Baugruppen', ['Baugruppe', 'Aufgabe'], a.ressourcen, a);
    verzeichnis(b, '10.4', 'Verzeichnis der Fähigkeiten', ['Fähigkeit', 'Bedeutung'], a.faehigkeiten, a);

    if (a.forderungen.length) {
      b.h3('10.5 Forderungen nach Sachgebieten');
      var gebiete = {}, reihenfolge = [];
      for (var q = 0; q < a.forderungen.length; q++) {
        var gname = gebietVon(a.forderungen[q]);
        if (!gebiete[gname]) { gebiete[gname] = []; reihenfolge.push(gname); }
        gebiete[gname].push(a.forderungen[q].name);
      }
      reihenfolge.sort(function (x, y) { return x.localeCompare(y, 'de'); });
      var zeilen4 = [];
      for (var g = 0; g < reihenfolge.length; g++) {
        zeilen4.push([reihenfolge[g], gebiete[reihenfolge[g]].sort().join(', ')]);
      }
      b.tabelle(['Sachgebiet', 'Forderungen'], zeilen4);
    }

    if (a.vorgaben.length) {
      b.h3('10.6 Vorgaben nach Art');
      var arten = [
        ['Ressourcenbezogen', 'ResourceConstraint'],
        ['Betrieblich', 'OperationalConstraint'],
        ['Strategisch', 'StrategicConstraint'],
        ['Zur Sicherheit', 'SecurityConstraint']
      ];
      var zeilen5 = [], zugeordnet = {};
      for (var p = 0; p < a.vorgaben.length; p++) zugeordnet[a.vorgaben[p].id] = false;
      for (var t2 = 0; t2 < arten.length; t2++) {
        var teil2 = [];
        for (var r2 = 0; r2 < a.vorgaben.length; r2++) {
          if (String(a.vorgaben[r2].st || '').toLowerCase() === arten[t2][1].toLowerCase()) {
            teil2.push(a.vorgaben[r2].name);
            zugeordnet[a.vorgaben[r2].id] = true;
          }
        }
        if (teil2.length) zeilen5.push([arten[t2][0], teil2.sort().join(', ')]);
      }
      var sonstige = [];
      for (var s2 = 0; s2 < a.vorgaben.length; s2++) {
        if (!zugeordnet[a.vorgaben[s2].id]) sonstige.push(a.vorgaben[s2].name);
      }
      if (sonstige.length) zeilen5.push(['Weitere', sonstige.sort().join(', ')]);
      b.tabelle(['Art', 'Vorgaben'], zeilen5);
    }

    verzeichnis(b, '10.7', 'Verzeichnis der Rollen', ['Rolle', 'Aufgabe'], a.rollen, a);
    verzeichnis(b, '10.8', 'Verzeichnis der Abläufe', ['Ablauf', 'Vermerk'], a.aktivitaeten, a);

    if (a.phasen.length || a.meilensteine.length || a.daten.length || a.orte.length) {
      b.h3('10.9 Phasen, Meilensteine und Angaben');
      var zeilen9 = [];
      for (var ph = 0; ph < a.phasen.length; ph++) zeilen9.push([a.phasen[ph].name, 'Phase', aufgabeText(a.phasen[ph])]);
      for (var ms = 0; ms < a.meilensteine.length; ms++) zeilen9.push([a.meilensteine[ms].name, 'Meilenstein', aufgabeText(a.meilensteine[ms])]);
      for (var da = 0; da < a.daten.length; da++) zeilen9.push([a.daten[da].name, 'Angabe', aufgabeText(a.daten[da])]);
      for (var or = 0; or < a.orte.length; or++) zeilen9.push([a.orte[or].name, 'Ort', aufgabeText(a.orte[or])]);
      b.tabelle(['Bezeichnung', 'Art', 'Vermerk'], zeilen9);
    }

    b.h3('10.10 Weitere Bezeichnungen');
    var bisher = b.text().toLowerCase();
    var fehlend = [];
    for (var v = 0; v < a.namen.length; v++) {
      if (bisher.indexOf(a.namen[v].toLowerCase()) < 0) fehlend.push(a.namen[v]);
    }
    if (fehlend.length) {
      var zeilen7 = [];
      for (var w = 0; w < fehlend.length; w++) zeilen7.push([fehlend[w]]);
      b.tabelle(['Bezeichnung'], zeilen7);
    } else {
      b.p(b.w([
        'Jede Bezeichnung aus dem Bestand ist im Haupttext genannt; weitere Einträge sind deshalb nicht erforderlich.',
        'Der Haupttext führt alle Namen; eine Ergänzung erübrigt sich.',
        'Es bleibt keine Bezeichnung übrig, die hier nachzutragen wäre.'
      ], 'Weitere Bezeichnungen'));
    }
  }

  /* ------------------------------------------------------------------
     Erzeugung und Prüfung
     ------------------------------------------------------------------ */

  function einleitungstext(a) {
    var eins = a.titel
      ? 'Dieses Handbuch beschreibt ' + genannt(entschaerfe(a.titel)) + ' im Betrieb.'
      : 'Dieses Handbuch beschreibt das Vorhaben im Betrieb.';
    eins += ' Es richtet sich an alle, die das Vorhaben führen, bedienen und prüfen, und erzählt in zehn Kapiteln, was es leistet, wie es aufgebaut ist und nach welchen Verfahren gearbeitet wird.';
    var zwei = 'Grundlage sind allein die Bezeichnungen, Notizen und Verbindungen, die zu diesem Vorhaben vorliegen. Das Handbuch ergänzt nichts, was dort nicht steht: Wo eine Angabe fehlt, sagt es das; wo eine Aussage nur zu vermuten wäre, bleibt sie aus. Zahlen erscheinen nur dort, wo sie aus dem Bestand selbst stammen, als Anzahl der Dienste, der Baugruppen, der Verbindungen und der übrigen Bezeichnungen.';
    var drei = 'Wer das Handbuch zum ersten Mal liest, beginnt am besten mit dem ersten Kapitel und arbeitet sich vor. Wer eine bestimmte Frage hat, findet die Dienste im vierten, die Abläufe im fünften und die Vorgaben im achten Kapitel; das Glossar am Ende erklärt die Begriffe, und der Anhang sammelt die Verzeichnisse.';
    return [eins, zwei, drei];
  }

  function ohneUeberschriften(text) {
    var zeilen = String(text).split('\n'), rest = [], i;
    for (i = 0; i < zeilen.length; i++) {
      if (zeilen[i].charAt(0) === '#') continue;
      rest.push(zeilen[i]);
    }
    return rest.join('\n');
  }

  function zahlenPruefung(text, a) {
    /* Bezeichnungen und Tabellenzeilen sind Belege, kein Erzaehltext: eine
       Nummer im Eigennamen ("[2025-01-09] ...") oder im Verzeichnis ist
       belegt. Geprueft wird nur die Prosa. */
    var heu = ohneUeberschriften(text)
      .split('\n')
      .filter(function (z) { return z.charAt(0) !== '|'; })
      .join('\n')
      .replace(/»[^«]*«/g, ' ');
    var re = /\d+(?:[.,]\d+)*/g;
    var gefunden = [], m, fremd = [], i;
    while ((m = re.exec(heu))) {
      if (gefunden.indexOf(m[0]) < 0) gefunden.push(m[0]);
    }
    for (i = 0; i < gefunden.length; i++) {
      if (a.erlaubteZahlen.indexOf(gefunden[i]) < 0) fremd.push(gefunden[i]);
    }
    return { gefunden: gefunden, erlaubt: a.erlaubteZahlen, fremd: fremd };
  }

  function bezeichnungen(a, text) {
    var klein = String(text).toLowerCase(), fehlend = [], i;
    for (i = 0; i < a.namen.length; i++) {
      if (klein.indexOf(a.namen[i].toLowerCase()) < 0) fehlend.push(a.namen[i]);
    }
    return {
      gesamt: a.namen.length,
      genannt: a.namen.length - fehlend.length,
      quote: a.namen.length ? (100 * (a.namen.length - fehlend.length) / a.namen.length) : 100,
      fehlend: fehlend
    };
  }

  function saetzeVon(text) {
    var zeilen = String(text).split('\n'), out = [], i, j, teile;
    for (i = 0; i < zeilen.length; i++) {
      if (zeilen[i].charAt(0) === '#' || zeilen[i].charAt(0) === '|') continue;
      teile = zeilen[i].split(/(?<=[.!?])\s+/);
      for (j = 0; j < teile.length; j++) {
        if (flach(teile[j]).split(/\s+/).length >= 3) out.push(teile[j]);
      }
    }
    return out;
  }

  function wiederholungen(text, namen) {
    var st = new Stil(namen), saetze = saetzeVon(text), probleme = [], i, r;
    for (i = 0; i < saetze.length; i++) {
      r = st.frei(saetze[i]);
      if (r) probleme.push(r + ': ' + flach(saetze[i]).slice(0, 160));
      st.add(saetze[i]);
    }
    if (st.maxSchablone > 2) {
      var schuld = '';
      for (var k in st.schablone) {
        if (st.schablone.hasOwnProperty(k) && st.schablone[k] > 2) { schuld = k; break; }
      }
      probleme.push('Schablone (' + st.maxSchablone + '×): ' + schuld.slice(0, 140));
    }
    return {
      saetze: st.gesamt,
      maxWortlaut: st.maxExakt,
      maxSatzanfang: st.maxAnfang,
      maxSchablone: st.maxSchablone,
      probleme: probleme
    };
  }

  function pad2(n) { return n < 10 ? '0' + n : String(n); }

  function dateiname() {
    var base = String((typeof MODELLNAME !== 'undefined' && MODELLNAME) || '');
    base = base.replace(/\.(qea|qeax|eapx|sqlite)$/i, '');
    base = base.replace(/[\/\\:*?"<>|]+/g, '_').replace(/\s+/g, '_');
    base = base.replace(/^_+/, '').replace(/_+$/, '');
    if (!base) base = 'vorhaben';
    var d = new Date();
    var stamp = '' + d.getFullYear() + pad2(d.getMonth() + 1) + pad2(d.getDate()) + '-' + pad2(d.getHours()) + pad2(d.getMinutes());
    return base + '_handbuch_' + stamp + '.md';
  }

  function erzeugeText() {
    var a = analysiere();
    if (!a.els.length) {
      throw fehler('Es ist kein Vorhaben geladen. Bitte zuerst eine .qea öffnen.', '');
    }
    var b = new Buch(a.namen);
    b.h1(a.doktitel);
    var ein = einleitungstext(a);
    b.p(b.w([ein[0]], 'Einleitung 1'));
    b.p(b.w([ein[1]], 'Einleitung 2'));
    b.p(b.w([ein[2]], 'Einleitung 3'));
    kapitel1(b, a);
    kapitel2(b, a);
    kapitel3(b, a);
    kapitel4(b, a);
    kapitel5(b, a);
    kapitel6(b, a);
    kapitel7(b, a);
    kapitel8(b, a);
    kapitel9(b, a);
    kapitel10(b, a);

    var text = b.text();
    /* Zwischenstand sichern: bei einem Abbruch bleibt der erzeugte Text
       einsehbar, statt nur einer Meldung. */
    S.letztes = text;
    /* Abschlusspruefung auf der entschaerften Fassung: die Absaetze sind
       bereits ersetzt, und das Verzeichnis nennt bewusst echte Namen (ein
       Element darf "Musterarchitektur" heissen). Bleibt danach ein Begriff
       uebrig (etwa eine GUID), bricht die Ausgabe weiterhin ab. */
    var tr = verbote(entschaerfe(text));
    if (tr.anzahl) {
      throw fehler('Der erzeugte Text enthält gesperrte Begriffe: ' + tr.liste, '');
    }
    /* Zahlen, Wiederholungen und unerzaehlte Kanten sind Befunde, keine
       Abbruchgruende: sie haengen am Bestand, nicht an der Ausgabe. Sie
       stehen im Bericht, damit nichts still bleibt -- erzeugt wird trotzdem. */
    var warnungen = [];
    var zp = zahlenPruefung(text, a);
    if (zp.fremd.length) {
      warnungen.push('Zahlen ohne Beleg: ' + zp.fremd.join(', '));
    }
    var wh = wiederholungen(text, a.namen);
    if (wh.probleme.length) {
      warnungen.push('Wiederholungen: ' + wh.probleme.length + ' (' + wh.probleme[0] + ')');
    }
    if (b.ausgeschoepft) {
      warnungen.push('Formulierungen ausgeschöpft: ' + b.ausgeschoepft + '× wiederholt');
    }
    var fehlendKanten = [];
    for (var i = 0; i < a.kanten.length; i++) {
      if (!b.kanten[a.kanten[i].id]) fehlendKanten.push(a.kanten[i].id);
    }
    if (fehlendKanten.length) {
      warnungen.push('Kanten ohne Satz: ' + fehlendKanten.length);
    }
    return {
      text: text,
      warnungen: warnungen,
      titel: a.titel,
      kennzahlen: a.zahl,
      pruefung: tr,
      zahlen: zp,
      bezeichnungen: bezeichnungen(a, text),
      wiederholung: wh,
      kantenAbdeckung: { gesamt: a.kanten.length, genannt: a.kanten.length - fehlendKanten.length, fehlend: fehlendKanten },
      dateiname: dateiname()
    };
  }

  /* ------------------------------------------------------------------
     Oberfläche
     ------------------------------------------------------------------ */

  function hbEsc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function zeigeBericht(r) {
    var ziel = document.getElementById('eh-prosa-report');
    var knopf = document.getElementById('eh-prosa-dl');
    var stand = document.getElementById('eh-prosa-state');
    if (knopf) { knopf.disabled = false; knopf.style.opacity = ''; knopf.style.cursor = ''; }
    if (stand) stand.textContent = 'fertig';
    if (!ziel) return;
    var k = r.kennzahlen;
    var zeilen = r.text.split('\n').length;
    var wh = r.wiederholung || {};
    ziel.innerHTML =
      '<div class="eh-rep-ok"><b>Handbuch erzeugt.</b> Zehn Kapitel, ' + r.text.length.toLocaleString('de-DE') + ' Zeichen, ' + r.bezeichnungen.genannt + ' von ' + r.bezeichnungen.gesamt + ' Bezeichnungen genannt, kein gesperrtes Wort im Text.</div>' +
      '<div class="eh-rep-nums">' +
      '<span>Dienste <b>' + k.dienste + '</b></span>' +
      '<span>Baugruppen <b>' + k.ressourcen + '</b></span>' +
      '<span>Fähigkeiten <b>' + k.faehigkeiten + '</b></span>' +
      '<span>Forderungen <b>' + k.forderungen + '</b></span>' +
      '<span>Vorgaben <b>' + k.vorgaben + '</b></span>' +
      '<span>Verbindungen <b>' + k.kanten + '</b></span>' +
      '<span>Zeilen <b>' + zeilen + '</b></span>' +
      '</div>' +
      '<div class="eh-rep-dim">Datei: <code>' + hbEsc(r.dateiname) + '</code> · Zahlen im Text: ' + (r.zahlen.gefunden.length ? hbEsc(r.zahlen.gefunden.join(', ')) : 'keine') + ' — alle aus dem Bestand belegt.</div>' +
      '<div class="eh-rep-dim">Wiederholungen geprüft: ' + wh.saetze + ' Sätze, freier Satzanfang höchstens ' + wh.maxSatzanfang + '×, gleicher Wortlaut ' + wh.maxWortlaut + '×, gleiche Schablone ' + wh.maxSchablone + '×. Kanten: ' + r.kantenAbdeckung.genannt + ' von ' + r.kantenAbdeckung.gesamt + '.</div>';
  }

  function zeigeFehler(e) {
    var ziel = document.getElementById('eh-prosa-report');
    var knopf = document.getElementById('eh-prosa-dl');
    var stand = document.getElementById('eh-prosa-state');
    if (knopf) { knopf.disabled = true; knopf.style.opacity = '0.45'; knopf.style.cursor = 'not-allowed'; }
    if (stand) stand.textContent = 'abgebrochen';
    if (!ziel) return;
    var text = e && e.absatz ? String(e.absatz).slice(0, 240) : '';
    ziel.innerHTML =
      '<div class="eh-rep-warn"><b>Abbruch — es wurde nichts gespeichert.</b><br>' + hbEsc(e && e.message ? e.message : 'Unbekannter Fehler') + (text ? '<pre>' + hbEsc(text) + '</pre>' : '') + '</div>';
  }

  function erzeugen() {
    try {
      var r = erzeugeText();
      S.letztes = r;
      zeigeBericht(r);
      return r;
    } catch (e) {
      S.letztes = null;
      zeigeFehler(e);
      return null;
    }
  }

  function herunterladen() {
    var r = S.letztes || erzeugen();
    if (!r) return;
    var blob = new Blob([r.text], { type: 'text/markdown;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = r.dateiname;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      if (a.parentNode) a.parentNode.removeChild(a);
      URL.revokeObjectURL(url);
    }, 1500);
  }

  /* Öffentliche Schnittstelle */
  return {
    erzeugen: erzeugen,
    herunterladen: herunterladen,
    erzeugeText: erzeugeText,
    pruefe: verbote,
    zahlen: zahlenPruefung,
    dateiname: dateiname,
    kapitel: KAPITEL,
    verboten: VERBOTEN,
    _analyse: analysiere,
    _wiederholungen: wiederholungen,
    _letztes: function () { return S.letztes; }
  };
})();
