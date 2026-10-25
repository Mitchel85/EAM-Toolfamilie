/* =====================================================================
   EAM AI Suite KI — part6_ki.js
   KI-Architekt: multimodaler Input (Text, docx/pdf, Bilder, optional Audio)
   -> ADMBw/NAFv4-konformes Modell -> .qea-Erzeugung (sql.js) + In-App-Analyse
   ===================================================================== */
(function () {
  'use strict';

  /* ---------- Canonical ADMBw/NAFv4-Zuordnung Stereotyp -> EA Object_Type
     (aus der Musterarchitektur MASC gelernt; Quelle der Wahrheit fuer Konformitaet) */
  var STEOTYPE_TO_TYPE = {
    ServiceSpecification: 'Class', FunctionalRequirement: 'Requirement', NonfunctionalRequirement: 'Requirement',
    BWRequirement: 'Requirement', Capability: 'Class', CapabilityConfiguration: 'Class', System: 'Class',
    Software: 'Class', Organization: 'Class', Person: 'Class', Post: 'Class',
    ActualOrganization: 'Object', ActualPerson: 'Object', ActualPost: 'Object', ActualResource: 'Object',
    ActualProject: 'Object', ActualProjectMilestone: 'Object', Project: 'Class', ProjectMilestone: 'Class',
    OperationalActivity: 'Activity', StandardOperationalActivity: 'Activity', BusinessProcess: 'Activity',
    FunctionAction: 'Action', OperationalRole: 'Part', ResourceRole: 'Part', Measurement: 'Part',
    InformationElement: 'Class', DataElement: 'Class', ResourceArtifact: 'Class', FulfilmentCriterion: 'Class',
    FitCriterion: 'Class', MeasurementType: 'Class', Standard: 'Class', DocumentReference: 'Class',
    ResourcePort: 'Port', ServicePort: 'Port', OperationalPort: 'Port',
    Location: 'Object', ActualLocation: 'Object', Environment: 'Object', ActualEnvironment: 'Object',
    OperationalConstraint: 'Class', ResourceConstraint: 'Class', StrategicConstraint: 'Class', ServicePolicy: 'Class',
    OperationalStateDescription: 'Class', ResourceStateDescription: 'Class', StateDescription: 'Class',
    ServiceFunction: 'Class', ServiceInterface: 'Class', ServiceMethod: 'Class', ServiceParameter: 'Class',
    OperationalInterface: 'Class', OperationalConnector: 'Class', ServiceConnector: 'Class', ResourceInterface: 'Class',
    OperationalExchange: 'Class', ResourceExchange: 'Class', ServiceMessage: 'Class', OperationalMessage: 'Class',
    OperationalExchangeItem: 'Class', ResourceExchangeItem: 'Class', OperationalPerformer: 'Class', ResourcePerformer: 'Class',
    Node: 'Node', PhysicalResource: 'Class', NaturalResource: 'Class', OrganizationalResource: 'Class',
    ArchitecturalDescription: 'Package', EnterpriseVision: 'Class', EnterpriseGoal: 'Class', EnduringTask: 'Class',
    ActualEnduringTask: 'Object', CapabilityDependency: 'Class', Protocol: 'Class', Protocolstack: 'Class',
    RequirementCategory: 'Class', RequirementCatalogue: 'Class', Reference: 'Class', PropertySet: 'Class',
    MeasurableElement: 'Class', OperationalAgent: 'Class', ProblemDomain: 'Class', HighLevelOperationalConcept: 'Class',
    Concern: 'Class', Viewpoint: 'Class', View: 'Class', Stakeholder: 'Class', Classification: 'Class'
  };

  /* Beziehungs-Stereotypen -> EA Connector_Type (NAF/ADMBw-Metamodell) */
  var REL_TO_CONNECTOR = {
    CapabilityGeneralization: 'Generalization', ServiceGeneralization: 'Generalization',
    Satisfy: 'Dependency', Implements: 'Abstraction', RealiseRequirement: 'Realization',
    Exhibits: 'Dependency', CapabilityForTask: 'Dependency', MapsToCapability: 'Dependency',
    OwnsMeasurement: 'Dependency', JustifiedBy: 'Dependency', ServiceDependency: 'Dependency',
    ServiceExchange: 'InformationFlow', ServiceConnector: 'Connector', ProvidesServiceFunction: 'Dependency',
    Provides: 'Dependency', Consumes: 'Dependency', ConsumedBy: 'Dependency',
    ActivitySupportsService: 'Realization', IsCapableToPerform: 'Dependency',
    IsResponsibleFor: 'Dependency', IsAccountableFor: 'Dependency',
    OperationalExchange: 'InformationFlow', ResourceExchange: 'InformationFlow',
    ServiceProvision: 'Dependency', ResourceDependency: 'Dependency', ResourceToServiceDependency: 'Dependency',
    HostedOn: 'Dependency', Responsible: 'Dependency', RequiredResource: 'Dependency',
    NeedsResource: 'Dependency', NeedsService: 'Dependency', Classified: 'Dependency',
    DataElementStoredIn: 'Dependency', DerivedFrom: 'Dependency', ToBeRealizedBy: 'Dependency',
    Requires: 'Dependency', Refines: 'Dependency', Replaces: 'Dependency',
    ConflictsWith: 'Dependency', StemsFrom: 'Dependency', IsDuplicateOf: 'Dependency',
    ArchitectureForProject: 'Dependency', DescribedBy: 'Dependency', Expresses: 'Dependency',
    CompliesViewpoint: 'Dependency', ConcernForView: 'Dependency', ViewpointToStakeholder: 'Dependency',
    LocationHolder: 'Dependency', PhysicalLocation: 'Dependency', RequiredEnvironment: 'Dependency',
    AchievedEffect: 'Dependency', DesiredEffect: 'Dependency', ProjectSequence: 'Dependency',
    MilestoneDependency: 'Dependency', OwnedMilestone: 'Dependency', Evaluates: 'Realization',
    SuccessorOf: 'Dependency', VersionReleased: 'Dependency', VersionWithdrawn: 'Dependency',
    RealizesRecommendation: 'Realization',
    FunctionControlFlow: 'ControlFlow', FunctionObjectFlow: 'ObjectFlow',
    OperationalControlFlow: 'ControlFlow', OperationalMessageFlow: 'ControlFlow', OperationalObjectFlow: 'ObjectFlow',
    Generalization: 'Generalization', Aggregation: 'Aggregation', Composition: 'Composite',
    Association: 'Association', Dependency: 'Dependency', Realization: 'Realization',
    Abstraction: 'Abstraction', InformationFlow: 'InformationFlow'
  };

  var S = { template: null, templateName: null, templateInfo: null, model: null, bytes: null, modelName: null, busy: false, mdg: null, chat: [] };

  /* ---------- MDG-Regelbasis (ersetzt hartkodierte ADMBW_DATA) ---------- */
  function loadMdg(buffer, name) {
    // XML parsen -> gleiche Struktur wie tools/mdg_parser.py (admbw_rules.json)
    // Encoding aus der XML-Deklaration lesen (die offizielle MDG ist windows-1252).
    var bytes = new Uint8Array(buffer);
    var probe = new TextDecoder('latin1').decode(bytes.subarray(0, Math.min(bytes.length, 300)));
    var encMatch = /encoding\s*=\s*["']([^"']+)/i.exec(probe);
    var enc = (encMatch ? encMatch[1] : 'utf-8').toLowerCase();
    if (enc === 'cp1252') enc = 'windows-1252';
    var xml = new DOMParser().parseFromString(new TextDecoder(enc).decode(bytes), 'application/xml');
    if (xml.getElementsByTagName('parsererror').length) throw new Error('MDG-XML konnte nicht geparst werden.');
    var rules = { profileName: name || '', version: '', elementStereo: {}, connectorStereo: {}, viewpoints: [], viewpointInfo: {}, toolbox: {} };
    var CONN = { 'Connector': 1, 'Package': 1, 'Dependency': 1, 'Abstraction': 1, 'Realization': 1, 'Realisation': 1, 'Generalization': 1, 'Association': 1, 'Aggregation': 1, 'Composition': 1, 'InformationFlow': 1, 'ControlFlow': 1, 'ObjectFlow': 1, 'Usage': 1, 'Trace': 1, 'AssociationClass': 1 };
    var root = xml.documentElement;
    rules.version = root.getAttribute('version') || '';

    // Stereotypen aus UMLProfiles/Content/Stereotypes
    var profiles = root.getElementsByTagName('UMLProfiles');
    if (profiles.length) {
      var profList = profiles[0].getElementsByTagName('UMLProfile');
      for (var i = 0; i < profList.length; i++) {
        var contents = profList[i].getElementsByTagName('Content');
        if (!contents.length) continue;
        var stereos = contents[0].getElementsByTagName('Stereotype');
        for (var j = 0; j < stereos.length; j++) {
          var s = stereos[j];
          var nm = s.getAttribute('name');
          if (!nm) continue;
          var info = { metatype: s.getAttribute('metatype') || '', abstract: s.getAttribute('isAbstract') === 'true', generalizes: s.getAttribute('generalizes') || '', base: s.getAttribute('baseStereotypes') || '', appliesTo: [], metaconstraints: [] };
          var at = s.getElementsByTagName('AppliesTo');
          if (at.length) {
            var applies = at[0].getElementsByTagName('Apply');
            for (var a = 0; a < applies.length; a++) if (applies[a].getAttribute('type')) info.appliesTo.push(applies[a].getAttribute('type'));
          }
          var mcs = s.getElementsByTagName('metaconstraint');
          for (var m = 0; m < mcs.length; m++) {
            var role = mcs[m].getAttribute('umlRole');
            var raw = mcs[m].getAttribute('constraint') || '';
            var parts = raw.split(';');
            for (var pi = 0; pi < parts.length; pi++) {
              var cst = parts[pi].split('::').pop().trim();
              if (role && cst) info.metaconstraints.push({ role: role, constraint: cst });
            }
          }
          var isConn = false;
          for (var k = 0; k < info.appliesTo.length; k++) if (CONN[info.appliesTo[k]]) { isConn = true; break; }
          /* baseStereotypes sind leerzeichen-/komma-getrennte Listen — normalisieren */
          info.bases = (info.base || '').split(/[,\s]+/).filter(Boolean);
          if (info.generalizes) info.bases.unshift(info.generalizes);
          rules[isConn ? 'connectorStereo' : 'elementStereo'][nm] = info;
        }
      }
    }
    // Verbindungehrefinitionen/-Norm (fürs Prompt): erlaubte Element-/Connector-Sets
    rules.elementNames = Object.keys(rules.elementStereo);
    rules.connectorNames = Object.keys(rules.connectorStereo);
    // UIToolboxes: Viewpoint -> erlaubte Stereotypen
    rules.toolbox = {};
    var tbs = root.getElementsByTagName('UIToolboxes');
    if (tbs.length) {
      var tbProfs = tbs[0].getElementsByTagName('UMLProfile');
      for (var t = 0; t < tbProfs.length; t++) {
        var tdoc = tbProfs[t].getElementsByTagName('Documentation');
        var tname = tdoc.length && tdoc[0].getAttribute('name') ? tdoc[0].getAttribute('name') : '';
        var used = [];
        var tcontent = tbProfs[t].getElementsByTagName('Content');
        if (tcontent.length) {
          var tstereos = tcontent[0].getElementsByTagName('Stereotype');
          for (var ts = 0; ts < tstereos.length; ts++) {
            var tn = tstereos[ts].getAttribute('name');
            if (tn && used.indexOf(tn) < 0) used.push(tn);
          }
        }
        if (tname) rules.toolbox[tname] = used;
      }
    }
    // DiagramProfile: Viewpoint-Namen aus den Diagram_Custom-Stereotypen
    rules.viewpoints = [];
    var dp = root.getElementsByTagName('DiagramProfile');
    if (dp.length) {
      var dpProfs = dp[0].getElementsByTagName('UMLProfile');
      for (var p = 0; p < dpProfs.length; p++) {
        var dpStereo = dpProfs[p].getElementsByTagName('Stereotype');
        for (var ps = 0; ps < dpStereo.length; ps++) {
          var vn = (dpStereo[ps].getAttribute('name') || '').trim();
          if (!vn || vn === 'Business Process') continue;
          if (rules.viewpoints.indexOf(vn) < 0) rules.viewpoints.push(vn);
          var props = {};
          var applies = dpStereo[ps].getElementsByTagName('Apply');
          for (var pa = 0; pa < applies.length; pa++) {
            var pprops = applies[pa].getElementsByTagName('Property');
            for (var pp = 0; pp < pprops.length; pp++) {
              var pn = pprops[pp].getAttribute('name');
              if (pn) props[pn] = pprops[pp].getAttribute('value') || '';
            }
          }
          rules.viewpointInfo[vn] = props;
        }
      }
    }
    S.mdg = rules;
    return rules;
  }
  function mdgVocab() {
    if (S.mdg && S.mdg.elementNames && S.mdg.elementNames.length) {
      return { els: S.mdg.elementNames, rels: S.mdg.connectorNames };
    }
    return collectVocabulary();
  }

  /* ---------- MDG-Vererbung + Validierung ---------- */
  function mdgAncestors(n) {
    if (!S.mdg) return {};
    var memo = S.mdg._ancMemo || (S.mdg._ancMemo = {});
    if (memo[n]) return memo[n];
    var res = {}, stack = [], es = S.mdg.elementStereo || {};
    var info = es[n];
    if (info) {
      (info.bases || []).forEach(function (b) { stack.push(b); });
    }
    while (stack.length) {
      var b = stack.pop();
      if (!b || res[b]) continue;
      res[b] = 1;
      var bi = es[b];
      if (bi) (bi.bases || []).forEach(function (x) { stack.push(x); });
    }
    memo[n] = res;
    return res;
  }
  function mdgMatches(stereo, constraint) {
    if (stereo === constraint) return true;
    return !!mdgAncestors(stereo)[constraint];
  }
  /* Validiert alle Beziehungen eines Modells gegen die MDG-Metaconstraints.
     Liefert { total, ok, free, unknown, viol: [{from,to,stereotype,why}] } */
  function validateModel(ir) {
    var v = { total: 0, ok: 0, free: 0, unknown: 0, viol: [] };
    if (!S.mdg || !S.mdg.connectorStereo) { v.noMdg = true; return v; }
    var cs = S.mdg.connectorStereo;
    var byName = {};
    (ir.elements || []).forEach(function (e) { byName[e.name] = e.stereotype; });
    (ir.connectors || []).forEach(function (c) {
      v.total++;
      var def = cs[c.stereotype];
      if (!def) { v.unknown++; c.__mdg = { ok: false, why: 'Stereotyp nicht in der MDG' }; v.viol.push({ from: c.from, to: c.to, stereotype: c.stereotype, why: 'Beziehungs-Stereotyp „' + c.stereotype + '“ ist nicht in der MDG definiert' }); return; }
      var mc = def.metaconstraints || [];
      if (!mc.length) { v.free++; c.__mdg = { ok: true, free: true }; return; }
      var fromAllowed = [], toAllowed = [], fromOK = null, toOK = null;
      mc.forEach(function (m) {
        if (m.role === 'client' || m.role === 'source' || m.role === 'end[0].role' || m.role === 'informationSource') { fromAllowed.push(m.constraint); }
        else if (m.role === 'supplier' || m.role === 'target' || m.role === 'end[1].role' || m.role === 'informationTarget') { toAllowed.push(m.constraint); }
      });
      var srcSt = byName[c.from], tgtSt = byName[c.to];
      if (fromAllowed.length) {
        fromOK = fromAllowed.some(function (a) { return mdgMatches(srcSt, a); });
      }
      if (toAllowed.length) {
        toOK = toAllowed.some(function (a) { return mdgMatches(tgtSt, a); });
      }
      if (fromOK !== false && toOK !== false) {
        v.ok++;
        c.__mdg = { ok: true, fromAllowed: fromAllowed, toAllowed: toAllowed };
      } else {
        var why = [];
        if (fromOK === false) why.push('Quelle „' + c.from + '“ («' + srcSt + '») darf nicht «' + c.stereotype + '» sein (erlaubt: ' + fromAllowed.join(', ') + ')');
        if (toOK === false) why.push('Ziel „' + c.to + '“ («' + tgtSt + '») darf nicht Ziel von «' + c.stereotype + '» sein (erlaubt: ' + toAllowed.join(', ') + ')');
        c.__mdg = { ok: false, why: why.join('; ') };
        v.viol.push({ from: c.from, to: c.to, stereotype: c.stereotype, why: why.join('; ') });
      }
    });
    return v;
  }
  /* Viewpoint-Abdeckung aus MDG-Toolbox (stereotype -> Codes) */
  function mdgCoverage(ir) {
    if (!S.mdg || !S.mdg.toolbox) return null;
    var inv = {};
    for (var k in S.mdg.toolbox) {
      var m = String(k).match(/([CSLPA]R?\d+)/);
      var code = m ? m[1] : null;
      if (!code) continue;
      S.mdg.toolbox[k].forEach(function (sname) { (inv[sname] = inv[sname] || []); if (inv[sname].indexOf(code) < 0) inv[sname].push(code); });
    }
    var cov = {};
    (ir.elements || []).forEach(function (e) {
      (inv[e.stereotype] || []).forEach(function (code) { cov[code] = (cov[code] || 0) + 1; });
    });
    return cov;
  }

  /* ---------- Einstellungen ---------- */
  function loadSettings() {
    var d = { base: 'https://api.deepseek.com/v1', model: 'deepseek-flash', vision: '', stt: '', key: '' };
    try {
      var raw = localStorage.getItem('amki_settings');
      if (raw) { var s = JSON.parse(raw); for (var k in d) if (typeof s[k] === 'string') d[k] = s[k]; }
    } catch (e) { }
    return d;
  }
  function saveSettings() {
    var d = { base: el('ki-base').value.trim() || 'https://api.deepseek.com/v1', model: el('ki-model').value.trim() || 'deepseek-flash', vision: el('ki-vision').value.trim(), stt: el('ki-stt').value.trim(), key: el('ki-key').value.trim() };
    try { localStorage.setItem('amki_settings', JSON.stringify(d)); } catch (e) { }
    return d;
  }

  /* ---------- ADMBw-Vokabular aus Referenz-Grid (runtime) ---------- */
  function collectVocabulary() {
    var els = {}, rels = {};
    var vp = (window.ADMBW_DATA && ADMBW_DATA.vp) || {};
    for (var code in vp) {
      if (!vp.hasOwnProperty(code)) continue;
      (vp[code].els || []).forEach(function (s) { els[s] = true; });
    }
    var topo = (window.ADMBW_DATA && ADMBW_DATA.topo) || {};
    for (var c2 in topo) {
      if (!topo.hasOwnProperty(c2)) continue;
      topo[c2].forEach(function (t) { if (t.rel) rels[t.rel] = true; });
    }
    /* eigene Kern-Vokabeln ergaenzen (im NAF-Katalog, aber sicherstellen) */
    ['Capability', 'CapabilityConfiguration', 'ServiceSpecification', 'ServiceFunction', 'ServiceInterface',
      'System', 'Software', 'Organization', 'Person', 'Post', 'OperationalActivity', 'StandardOperationalActivity',
      'BusinessProcess', 'InformationElement', 'DataElement', 'ResourceArtifact', 'ResourcePerformer',
      'OperationalPerformer', 'ResourcePort', 'ServicePort', 'FunctionalRequirement', 'NonfunctionalRequirement',
      'BWRequirement', 'OperationalConstraint', 'ResourceConstraint', 'StrategicConstraint', 'ServicePolicy',
      'Measurement', 'MeasurementType', 'FulfilmentCriterion', 'Protocol', 'Standard', 'Location', 'Environment',
      'Project', 'ActualProject', 'ActualProjectMilestone', 'OperationalExchange', 'ResourceExchange',
      'ArchitecturalDescription', 'EnterpriseVision', 'EnterpriseGoal', 'Classification', 'DocumentReference']
      .forEach(function (s) { els[s] = true; });
    ['Satisfy', 'Implements', 'Exhibits', 'CapabilityForTask', 'MapsToCapability', 'OwnsMeasurement', 'JustifiedBy',
      'ServiceDependency', 'ProvidesServiceFunction', 'Provides', 'Consumes', 'ConsumedBy', 'ActivitySupportsService',
      'IsCapableToPerform', 'IsResponsibleFor', 'IsAccountableFor', 'OperationalExchange', 'ResourceExchange',
      'ServiceProvision', 'ResourceDependency', 'HostedOn', 'Responsible', 'RequiredResource', 'NeedsResource',
      'Classified', 'DataElementStoredIn', 'DerivedFrom', 'ToBeRealizedBy', 'Requires', 'Refines', 'Replaces',
      'ConflictsWith', 'StemsFrom', 'IsDuplicateOf', 'ArchitectureForProject', 'CompliesViewpoint',
      'LocationHolder', 'PhysicalLocation', 'RequiredEnvironment', 'AchievedEffect', 'DesiredEffect',
      'CapabilityGeneralization', 'ServiceGeneralization', 'ProjectSequence', 'MilestoneDependency',
      'OwnedMilestone', 'Evaluates', 'RealiseRequirement', 'RealizesRecommendation',
      'FunctionControlFlow', 'FunctionObjectFlow', 'OperationalControlFlow', 'OperationalMessageFlow', 'OperationalObjectFlow']
      .forEach(function (s) { rels[s] = true; });
    return { els: Object.keys(els), rels: Object.keys(rels) };
  }

  /* ---------- System-Prompt ---------- */
  function systemPrompt(voc, ruleText) {
    var base = [
      'Du bist ein Enterprise-Architekt fuer die Bundeswehr-Domäne ADMBw (NAFv4/ADMBw-Metamodell).',
      'Deine Aufgabe: Extrahiere aus der bereitgestellten Beschreibung (Text und/oder Bild) ein vollstaendiges Architekturmodell als JSON.',
      '',
      'ANTWORTE AUSSCHLIESSLICH MIT JSON (kein Kommentar, kein Markdown). Format:',
      '{"name": "<Modellname>", "beschreibung": "<1-2 Saetze>",',
      ' "packages": [{"name": "...", "parent": null|<Name>}],',
      ' "elements": [{"name": "...", "stereotype": "...", "package": "<Name>", "note": "..."}],',
      ' "connectors": [{"from": "<Elementname>", "to": "<Elementname>", "stereotype": "...", "name": ""}],',
      ' "diagrams": [{"name": "...", "package": "<Name>", "elements": ["<Name>", "..."], "code": "<C1|S1|L2|P2|...>"}]}',
      '',
      'ERLAUBTE ELEMENT-STEREOTYPEN (NAFv4/ADMBw) — NUR diese verwenden:',
      voc.els.join(', '),
      '',
      'ERLAUBTE BEZIEHUNGS-STEREOTYPEN — NUR diese verwenden:',
      voc.rels.join(', '),
      '',
      'REGELN:',
      '1. Namen auf Deutsch (Substantive), Stereotypen exakt wie oben (englisch).',
      '2. Jede Beziehung verbindet genau zwei Elemente, die in "elements" existieren (exakte Namen).',
      '3. Fähigkeiten mit "Capability", Dienste mit "ServiceSpecification", Systeme/Software mit "System"/"Software",',
      '   Aktivitäten mit "OperationalActivity", Informationen mit "InformationElement"/"DataElement",',
      '   Anforderungen mit "FunctionalRequirement"/"NonfunctionalRequirement"/"BWRequirement",',
      '   Organisationen mit "Organization", Personen mit "Person", Standorte mit "Location" —',
      '   die "Actual..."-Varianten (z. B. ActualOrganization) NUR, wenn die Beschreibung ausdrücklich ein konkretes Individuum benennt.',
      '4. Beziehungen NUR mit MDG-konformen Endpunkten bilden (Quelle → Ziel):',
      '   "ist verantwortlich für" -> IsResponsibleFor (Organization → ServiceSpecification);',
      '   "umfasst"/"ist Unterfähigkeit von" -> CapabilityGeneralization (Capability → Capability);',
      '   "erfüllt die (strategische) Vorgabe"/"unterliegt" -> Satisfy (System/Organisation/Ressource → StrategicConstraint);',
      '   "weist die Fähigkeit ... nach" -> Exhibits (System/Organisation → Capability);',
      '   "tauscht Daten aus" zwischen Diensten -> ServiceExchange (ServiceSpecification → ServiceSpecification);',
      '   "tauscht Informationen aus" zwischen Prozessen -> OperationalExchange (OperationalActivity → OperationalActivity);',
      '   "verändert die Information" -> AffectedResource (OperationalActivity → InformationElement);',
      '   "setzt ... voraus" bei Anforderungen -> Requires (BWRequirement → BWRequirement);',
      '   "realisiert" nur zwischen strategischen Vorgaben -> Implements (StrategicConstraint → StrategicConstraint);',
      '   "nutzt den Dienst" bei Prozessschritten -> Consumes (OperationalActivityAction → ServiceSpecification).',
      '   WICHTIG: Anforderung → Fähigkeit (z. B. per Satisfy) ist in der MDG NICHT erlaubt;',
      '   "stellt bereit" nur Agent→Dienst (Provides: OperationalRole → ServiceSpecificationRole).',
      '5. Pakete logisch gruppieren (z.B. "Fähigkeiten", "Dienste", "Systeme", "Anforderungen");',
      '   Element ohne "package" landet im Stammpaket.',
      '6. Sichten ("diagrams"): gruppiere Elemente inhaltlich; "code" = NAF-Viewpoint-Code (C1, C2, C3, C4, C5, C7, C8, S1, S2, S3, S4, S5, S6, S7, S8, L1, L2, L3, L4, L5, L6, L7, L8, P1, P2, P3, P4, P5, P6, P7, P8, A1, A2, A3, R2, R3, R7, R8) oder null.',
      '7. Fehlende Information NICHT erfinden — nur aus der Beschreibung modellieren.',
      '8. "connectors": "name" leer lassen, wenn die Beziehung keine eigene Beschriftung braucht.'
    ];
    if (ruleText) {
      base.push('', 'OFFIZIELLE VERBINDUNGSREGELN (ADMBw-MDG). Format: Beziehungsstereotyp: Quelle → Ziel. Nutze NUR diese Kombinationen; Quelle/Ziel dürfen auch Untertypen (Spezialisierungen) der genannten Stereotypen sein:', ruleText);
    }
    return base.join('\n');
  }
  /* Kompakte Verbindungsregeln aus der MDG fürs Prompt */
  function mdgRuleText() {
    if (!S.mdg || !S.mdg.connectorStereo) return '';
    var lines = [];
    for (var k in S.mdg.connectorStereo) {
      var mc = S.mdg.connectorStereo[k].metaconstraints || [];
      if (mc.length < 2) continue;
      var fr = [], to = [];
      mc.forEach(function (m) {
        if (m.role === 'client' || m.role === 'source' || m.role === 'end[0].role' || m.role === 'informationSource') fr.push(m.constraint);
        else if (m.role === 'supplier' || m.role === 'target' || m.role === 'end[1].role' || m.role === 'informationTarget') to.push(m.constraint);
      });
      if (fr.length && to.length) lines.push(k + ': ' + fr.join('/') + ' → ' + to.join('/'));
    }
    return lines.join('\n');
  }

  /* ============================================================
     OPERATIONS-SPRACHE: Die KI ist Gehilfe, NICHT Modellträger.
     Sie liefert deterministische Operationen (bis), die die App
     auf das Modell anwendet. Damit skaliert die KI auch bei
     .qea-Dateien mit mehreren GB — nie das ganze Modell im Kontext.
     ============================================================ */
  var Op = {
    /* Operationen ausführen (Mutieren des Modells) */
    exec: function (model, op) {
      var typ = op && op.op;
      if (!typ) return { err: 'Operation ohne "op"-Feld' };
      var m = model;
      if (!m.elements) m.elements = [];
      if (!m.connectors) m.connectors = [];
      if (!m.packages) m.packages = [];
      if (!m.diagrams) m.diagrams = [];
      function byName(name) {
        for (var i = 0; i < m.elements.length; i++) if (m.elements[i].name === name) return m.elements[i];
        return null;
      }
      function pkgByName(name) {
        for (var i = 0; i < m.packages.length; i++) if (m.packages[i].name === name) return m.packages[i];
        return null;
      }
      function dup(prefix) { var n = prefix || 'Element'; var i = 2; while (byName(n)) n = (prefix || 'Element') + i++; return n; }
      switch (typ) {
        case 'addElement': {
          var nm = dup(op.name);
          m.elements.push({ name: nm, stereotype: op.stereotype || 'Class', type: stereotypeType(op.stereotype || 'Class'), package: op.package || (m.packages[0] && m.packages[0].name || ''), note: op.note || '' });
          if (op.package && !pkgByName(op.package)) { m.packages.push({ name: op.package, parent: null }); m.elements[m.elements.length - 1].package = op.package; }
          return { ok: true, name: nm, summary: 'Element „' + nm + '«' + (op.stereotype || 'Class') + '»" hinzugefügt.' };
        }
        case 'addConnector': {
          if (!byName(op.from)) return { err: 'Quelle „' + op.from + '" existiert nicht.' };
          if (!byName(op.to)) return { err: 'Ziel „' + op.to + '" existiert nicht.' };
          var st = op.stereotype || 'Dependency';
          var dupConn = m.connectors.some(function (c) { return c.from === op.from && c.to === op.to && c.stereotype === st; });
          if (dupConn) return { err: 'Beziehung ' + op.from + ' -«' + st + '»→ ' + op.to + ' existiert bereits.' };
          m.connectors.push({ from: op.from, to: op.to, stereotype: st, name: op.name || '' });
          return { ok: true, summary: 'Beziehung ' + op.from + ' -«' + st + '»→ ' + op.to + ' hinzugefügt.' };
        }
        case 'removeElement': {
          var idx = -1; for (var i = 0; i < m.elements.length; i++) if (m.elements[i].name === op.name) { idx = i; break; }
          if (idx < 0) return { err: 'Element „' + op.name + '" nicht gefunden.' };
          var removedName = m.elements[idx].name;
          m.elements.splice(idx, 1);
          m.connectors = m.connectors.filter(function (c) { return c.from !== removedName && c.to !== removedName; });
          return { ok: true, summary: 'Element „' + removedName + '" (und seine Beziehungen) entfernt.' };
        }
        case 'removeConnector': {
          var ri = -1; for (var i = 0; i < m.connectors.length; i++) if (m.connectors[i].from === op.from && m.connectors[i].to === op.to && (m.connectors[i].stereotype === op.stereotype)) { ri = i; break; }
          if (ri < 0) return { err: 'Beziehung ' + op.from + ' → ' + op.to + ' nicht gefunden.' };
          m.connectors.splice(ri, 1);
          return { ok: true, summary: 'Beziehung ' + op.from + ' → ' + op.to + ' entfernt.' };
        }
        case 'renameElement': {
          var re = byName(op.name); if (!re) return { err: 'Element „' + op.name + '" nicht gefunden.' };
          var oldName = re.name, newName = dup(op.to);
          re.name = newName;
          m.connectors.forEach(function (c) { if (c.from === oldName) c.from = newName; if (c.to === oldName) c.to = newName; });
          return { ok: true, summary: 'Element „' + oldName + '" → „' + newName + '" umbenannt.' };
        }
        case 'setStereotype': {
          var se = byName(op.name); if (!se) return { err: 'Element „' + op.name + '" nicht gefunden.' };
          se.stereotype = op.stereotype;
          se.type = stereotypeType(op.stereotype);
          return { ok: true, summary: 'Stereotyp von „' + op.name + '" auf «' + op.stereotype + '» gesetzt.' };
        }
        default:
          return { err: 'Unbekannte Operation „' + typ + '".' };
      }
    }
  };
  function chatAdd(role, html, marker) {
    var box = el('ki-chat-log');
    if (!box) return;
    var d = document.createElement('div');
    d.className = 'ki-chat-msg ' + (role === 'user' ? 'user' : (role === 'sys' ? 'sys' : 'ai'));
    if (marker) d.style.borderLeft = '3px solid ' + (marker === 'ok' ? '#1b7a2c' : marker === 'warn' ? '#e6a700' : '#c62828');
    d.innerHTML = html;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
  }
  function chatClear() {
    var box = el('ki-chat-log');
    if (box) box.innerHTML = '';
  }
  /* Das aktuelle Modell kompakt serialisieren (fürs Prompt als Kontext) */
  function modelToText() {
    var ir = S.model;
    if (!ir) return '(noch kein Modell)';
    var parts = [];
    parts.push('Aktuelles Modell „' + ir.name + '":');
    parts.push('  Elemente: ' + ir.elements.map(function (e) { return e.name + ' «' + e.stereotype + '»'; }).join('; '));
    parts.push('  Beziehungen: ' + ir.connectors.map(function (c) { return c.from + ' -«' + c.stereotype + '»→ ' + c.to; }).join('; '));
    if (ir.diagrams && ir.diagrams.length) parts.push('  Sichten: ' + ir.diagrams.map(function (d) { return d.name; }).join('; '));
    return parts.join('\n');
  }
  /* Nachricht senden -> KI liefert Ops, App führt sie aus (skalierbar) */
  function chatSend() {
    if (S.busy) return;
    var inp = el('ki-chat-input');
    var txt = inp.value.trim();
    if (!txt) return;
    var set = saveSettings();
    if (!set.key) { statusMsg('⚠ Bitte API-Schlüssel eintragen (Abschnitt 3).'); return; }
    chatAdd('user', esc(txt));
    inp.value = '';
    S.busy = true;
    el('ki-chat-send').disabled = true;
    statusMsg('⏳ KI formuliert Operationen …');
    var voc = mdgVocab();
    var ruleText = mdgRuleText();
    var inv = modelInventory(400);
    var msgs = [
      { role: 'system', content: opSystemPrompt(voc, ruleText) },
      { role: 'user', content: 'Aktuelle Inventar-Übersicht des Modells:\n' + inv },
      { role: 'user', content: 'Nutzeranweisung: ' + txt + '\n\nBitte antworte mit {"reply":"...","ops":[...]}, um diese Anweisung umzusetzen.' }
    ];
    chatComplete(set, msgs).then(function (content) {
      var parsed;
      try { parsed = JSON.parse(content); }
      catch (e) { throw new Error('KI-Antwort war kein gültiges JSON.'); }
      var reply = parsed.reply || '';
      var ops = parsed.ops || [];
      var ir = S.model;
      var results = runOps(ir, ops);
      var okCount = results.filter(function (r) { return r.ok; }).length;
      var errCount = results.length - okCount;
      ir.validation = validateModel(ir);
      ir.mdgCoverage = mdgCoverage(ir);
      renderResult(ir, voc);
      // Chat-Feedback
      chatAdd('ai', '<b>' + esc(reply) + '</b>');
      if (results.length) {
        var html = results.map(function (r) {
          return '<div style="color:' + (r.ok ? '#1b7a2c' : '#c62828') + '">' + (r.ok ? '✓ ' : '✗ ') + esc(r.msg) + '</div>';
        }).join('');
        chatAdd('sys', html);
      }
      var viol = ir.validation && ir.validation.viol ? ir.validation.viol.length : 0;
      var ack = okCount + '/' + results.length + ' Operationen ok' + (errCount ? ' · ' + errCount + ' fehlgeschlagen' : '') + (viol ? ' · ⚠ ' + viol + ' MDG-Verstoß' : ' · ✅ konform');
      statusMsg('✔ ' + ack);
    }).catch(function (e) {
      chatAdd('ai', '<span class="ki-bad">⚠ ' + esc(e.message) + '</span>');
      statusMsg('⚠ ' + e.message);
    }).then(function () {
      S.busy = false;
      el('ki-chat-send').disabled = false;
      inp.focus();
    });
  }
  function chatSystemPrompt(voc, ruleText) {
    var base = [
      'Du bist Enterprise-Architekt für ADMBw (NAFv4). Der Nutzer baut iterativ mit dir eine Architektur auf.',
      'Du hältst das aktuelle Modell im Blick und verfeinerst es anhand seiner Anweisungen im Dialog.',
      'Nach JEDER Nutzernachricht antwortest du mit dem VOLLSTÄNDIGEN aktualisierten Modell als JSON.',
      'Antworte NUR mit JSON. Format wie gehabt: {"name","beschreibung","packages","elements","connectors","diagrams"}.',
      'Erhalte unveränderte Teile, ändere nur das, was der Nutzer verlangt.',
      'ERLAUBTE ELEMENT-STEREOTYPEN: ' + voc.els.join(', '),
      'ERLAUBTE BEZIEHUNGS-STEREOTYPEN: ' + voc.rels.join(', ')
    ];
    if (ruleText) base.push('VERBINDUNGSREGELN (Quelle → Ziel):\n' + ruleText);
    return base.join('\n');
  }
  /* ---------- OPERATIONS-MODUS: KI als Gehilfe (skalierbar) ---------- */
  /* Inventar des Modells: NUR Namen + Stereotypen (kompakt), nie alle Daten.
     Bei sehr großen Modelle zusätzlich kappen (LIMIT). */
  function modelInventory(limit) {
    var ir = S.model;
    if (arguments.length > 1 && arguments[1]) ir = arguments[1];
    if (!ir) return '(kein Modell)';
    var els = ir.elements || [], lim = limit || 400;
    var head = [];
    for (var i = 0; i < Math.min(els.length, lim); i++) head.push(els[i].name + ' «' + els[i].stereotype + '»');
    var tail = els.length > lim ? '… (+' + (els.length - lim) + ' weitere Elemente) ' : '.';
    var conns = ir.connectors || [];
    return 'Modell „' + ir.name + '": ' + els.length + ' Elemente, ' + conns.length + ' Beziehungen.\n' +
      'Elemente: ' + head.join(', ') + tail + '\n' +
      'Vorhandene Beziehungen (Beispiele, max 80): ' + conns.slice(0, 80).map(function (c) { return c.from + ' -«' + c.stereotype + '»→ ' + c.to; }).join(', ') + (conns.length > 80 ? ' …' : '');
  }
  /* Operations-Systemprompt: KI antwortet mit Ops, App führt aus */
  function opSystemPrompt(voc, ruleText) {
    var base = [
      'Du bist Enterprise-Architekt für ADMBw (NAFv4). Du arbeitest als GEHILFE: Du formulierst präzise Operationen, die Anwendung führt sie deterministisch auf dem Modell aus.',
      'Du trägst NIE das ganze Modell im Kontext — du bekommst nur eine kompakte Inventar-Übersicht und antwortest mit Operationen.',
      '',
      'ANTWORTE NUR MIT JSON. Format:',
      '{"reply": "<kurze Antwort an den Nutzer>", "ops": [ {"op": "...", "..."}, ... ]}',
      '',
      'ERLAUBTE OPERATIONEN (op-Feld):',
      '  addElement:    {"op":"addElement","name":"...","stereotype":"...","package":"...","note":"..."}',
      '  addConnector:  {"op":"addConnector","from":"A","to":"B","stereotype":"...","name":""}',
      '  removeElement: {"op":"removeElement","name":"..."}',
      '  removeConnector:{"op":"removeConnector","from":"A","to":"B","stereotype":"..."}',
      '  renameElement: {"op":"renameElement","name":"alt","to":"neu"}',
      '  setStereotype: {"op":"setStereotype","name":"...","stereotype":"..."}',
      '',
      'ERLAUBTE ELEMENT-STEREOTYPEN: ' + voc.els.join(', '),
      'ERLAUBTE BEZIEHUNGS-STEREOTYPEN: ' + voc.rels.join(', ')
    ];
    if (ruleText) base.push('VERBINDUNGSREGELN (Quelle → Ziel):\n' + ruleText);
    base.push('', 'REGELN:', '1. "reply" ist eine kurze Antwort (1-2 Sätze) an den Nutzer, kein Markdown.', '2. "ops" ist eine Liste der auszuführenden Operationen (kann leer sein, wenn du nur antwortest).', '3. Für jede gewünschte Änderung EINE Operation. Verbinde neue Elemente gleich mit addConnector.', '4. Nutze die Namen exakt wie in der Inventar-Übersicht; neue Namen eindeutig.');
    return base.join('\n');
  }
  /* Ops ausführen + Ergebnis sammeln (deterministisch, kein LLM) */
  function runOps(ir, ops) {
    var results = [];
    (ops || []).forEach(function (op) {
      var r = Op.exec(ir, op);
      results.push({ op: op.op, ok: !!r.ok, msg: r.ok ? r.summary : r.err });
    });
    return results;
  }
  /* Nach der Generierung: Chat mit Modell-Kontext initialisieren */
  function startChat(ir, voc) {
    S.chat = [
      { role: 'system', content: chatSystemPrompt(voc || mdgVocab(), mdgRuleText()) },
      { role: 'user', content: 'Erstelle folgendes Architekturmodell:\n' + (S.lastPrompt || '') },
      { role: 'assistant', content: JSON.stringify({ name: ir.name, elements: ir.elements, connectors: ir.connectors, packages: ir.packages, diagrams: ir.diagrams }) }
    ];
  }
  function chatComplete(set, messages, opts) {
    opts = opts || {};
    var url = set.base.replace(/\/+$/, '') + '/chat/completions';
    var maxTok = opts.maxTokens || 12000;
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + set.key },
      body: JSON.stringify({ model: opts.model || set.model, messages: messages, response_format: { type: 'json_object' }, temperature: 0.2, max_tokens: maxTok, stream: false })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error('API-Fehler ' + r.status + ': ' + ((j.error && j.error.message) || JSON.stringify(j).substring(0, 200)));
        if (!j.choices || !j.choices.length) throw new Error('Leere API-Antwort.');
        var ch = j.choices[0];
        var content = ch.message && ch.message.content;
        if (ch.finish_reason === 'length') {
          throw new Error('Antwort durch Tokenlimit abgeschnitten (finish_reason=length, max_tokens=' + maxTok + '). Bitte max_tokens erhöhen oder Eingabe kürzen.');
        }
        if (!content) {
          throw new Error('Leere KI-Antwort (finish_reason=' + (ch.finish_reason || 'unbekannt') + ').');
        }
        return content;
      });
    });
  }

  function statusMsg(t) { el('ki-status').textContent = t; }

  /* Muss eine MDG geladen sein, bevor gebaut wird? (harte Erzwingung,
     abschaltbar über Checkbox 'ki-mdg-enforce') */
  function mdgEnforced() {
    var chk = el('ki-mdg-enforce');
    return chk ? chk.checked : true;
  }
  /* Prüft ob MDG geladen; liefert true wenn OK oder nicht erzwungen */
  function requireMdg() {
    if (!mdgEnforced()) return true;
    if (!S.mdg || !S.mdg.elementNames || !S.mdg.elementNames.length) {
      statusMsg('⚠ MDG erforderlich: Bitte zuerst im Abschnitt „2 · Regeln (MDG)“ die offizielle MDG-Datei laden — oder Konformitätssperre deaktivieren.');
      return false;
    }
    return true;
  }

  /* ---------- Neu bauen: leeres Modell ohne Datei anlegen ---------- */
  function newArchitecture() {
    // Wechselt in den KI-Tab und setzt S.model auf ein leeres Modell
    S.model = { name: 'Neue Architektur', beschreibung: '', packages: [{ name: 'Modell', parent: null }], elements: [], connectors: [], diagrams: [] };
    // Startseite ausblenden, Arbeitsbereich + Tab-Leiste einblenden
    el('upload').style.display = 'none';
    el('workspace').style.display = 'block';
    var mn = el('modellname'); if (mn) mn.textContent = 'Neue Architektur (leer)';
    // Direkt in den KI-Tab wechseln (showView blendet alle Views + Tabs korrekt)
    try { showView('ki'); } catch (e) { }
    statusMsg('✔ Leeres Modell angelegt — im KI-Tab beschreiben oder MDG laden.');
  }

  /* ---------- Datei-Anhänge verarbeiten ---------- */
  function readFileText(f) {
    return new Promise(function (res, rej) {
      var rd = new FileReader();
      rd.onload = function () { res(rd.result); };
      rd.onerror = function () { rej(new Error('Lesefehler: ' + f.name)); };
      rd.readAsText(f);
    });
  }
  function readFileB64(f) {
    return new Promise(function (res, rej) {
      var rd = new FileReader();
      rd.onload = function () { res(String(rd.result).split(',')[1] || String(rd.result)); };
      rd.onerror = function () { rej(new Error('Lesefehler: ' + f.name)); };
      rd.readAsDataURL(f);
    });
  }
  function extractDocx(buf) {
    return new Promise(function (res, rej) {
      if (typeof JSZip === 'undefined') { rej(new Error('JSZip fehlt — Word-Auswertung nicht verfügbar.')); return; }
      JSZip.loadAsync(buf).then(function (zip) {
        var f = zip.file('word/document.xml');
        if (!f) { rej(new Error('Keine word/document.xml in ' + f.name)); return; }
        f.async('string').then(function (xml) {
          var txt = xml.replace(/<w:p[ >]/g, '\n').replace(/<[^>]+>/g, '');
          var doc = new DOMParser().parseFromString('<!doctype html><body>' + txt, 'text/html');
          res(doc.body.textContent.replace(/\n{3,}/g, '\n\n'));
        }, rej);
      }, rej);
    });
  }
  function extractPdf(buf) {
    return new Promise(function (res, rej) {
      if (typeof pdfjsLib === 'undefined') { rej(new Error('pdf.js fehlt — PDF-Auswertung nicht verfügbar.')); return; }
      try {
        if (window.PDFJS_WORKER_B64) {
          var raw = atob(window.PDFJS_WORKER_B64);
          var bytes = new Uint8Array(raw.length);
          for (var bi = 0; bi < raw.length; bi++) bytes[bi] = raw.charCodeAt(bi);
          pdfjsLib.GlobalWorkerOptions.workerSrc = URL.createObjectURL(new Blob([bytes], { type: 'application/javascript' }));
        }
      } catch (e) { }
      pdfjsLib.getDocument({ data: buf }).promise.then(function (pdf) {
        var pages = [], i;
        for (i = 1; i <= pdf.numPages; i++) pages.push(pdf.getPage(i));
        Promise.all(pages).then(function (pl) {
          Promise.all(pl.map(function (p) { return p.getTextContent(); })).then(function (tcs) {
            var out = tcs.map(function (tc) { return tc.items.map(function (it) { return it.str; }).join(' '); }).join('\n\n');
            res(out.substring(0, 120000));
          }, rej);
        }, rej);
      }, rej);
    });
  }

  /* ---------- Multimodale Eingabe sammeln ---------- */
  function collectParts(files) {
    var tasks = [];
    for (var i = 0; i < files.length; i++) (function (f) {
      var ext = (f.name.match(/\.([a-z0-9]+)$/i) || [])[1] ? f.name.toLowerCase() : '';
      if (/\.(txt|md|markdown|log|csv|json)$/i.test(f.name)) {
        tasks.push(readFileText(f).then(function (t) {
          return { type: 'text', text: '=== DOKUMENT: ' + f.name + ' ===\n' + t.substring(0, 120000) };
        }));
      } else if (/\.docx$/i.test(f.name)) {
        tasks.push(f.arrayBuffer().then(function (ab) {
          return extractDocx(ab).then(function (t) {
            return { type: 'text', text: '=== WORD-DOKUMENT: ' + f.name + ' ===\n' + t.substring(0, 120000) };
          }).catch(function (e) { return { type: 'text', text: '=== WORD-DOKUMENT: ' + f.name + ' (NICHT LESBAR: ' + e.message + ') ===' }; });
        }));
      } else if (/\.pdf$/i.test(f.name)) {
        tasks.push(f.arrayBuffer().then(function (ab) {
          return extractPdf(ab).then(function (t) {
            return { type: 'text', text: '=== PDF: ' + f.name + ' ===\n' + t.substring(0, 120000) };
          }).catch(function (e) { return { type: 'text', text: '=== PDF: ' + f.name + ' (NICHT LESBAR: ' + e.message + ') ===' }; });
        }));
      } else if (/\.(png|jpe?g|webp|gif)$/i.test(f.name)) {
        tasks.push(readFileB64(f).then(function (b64) {
          var mime = /\.png$/i.test(f.name) ? 'image/png' : (/\.webp$/i.test(f.name) ? 'image/webp' : (/\.gif$/i.test(f.name) ? 'image/gif' : 'image/jpeg'));
          return { type: 'image', mime: mime, b64: b64, name: f.name };
        }));
      } else if (/\.(m4a|mp3|wav|ogg|aac)$/i.test(f.name)) {
        tasks.push(Promise.resolve({ type: 'audio', file: f, name: f.name }));
      } else {
        tasks.push(Promise.resolve({ type: 'text', text: '=== DATEI ' + f.name + ' (unbekanntes Format, übersprungen) ===' }));
      }
    })(files[i]);
    return Promise.all(tasks);
  }

  /* ---------- Text-Extraktion aus Bildern erfolgt durch das Vision-Modell (image_url) ---------- */

  /* ---------- KI.generate ---------- */
  function generate() {
    if (S.busy) return;
    var set = saveSettings();
    if (!set.key) { statusMsg('⚠ Bitte API-Schlüssel eintragen (Abschnitt 3).'); return; }
    if (!requireMdg()) return;
    var promptText = el('ki-prompt').value.trim();
    var files = el('ki-files').files || [];
    if (!promptText && !files.length) { statusMsg('⚠ Beschreibung eingeben und/oder Dateien anhängen.'); return; }
    S.lastPrompt = promptText;
    S.busy = true;
    el('ki-gen-btn').disabled = true;
    statusMsg('⏳ Modell wird generiert …');
    var voc = mdgVocab();
    var ruleText = mdgRuleText();
    var sysMsg = systemPrompt(voc, ruleText);
    var userParts = [{ type: 'text', text: promptText || 'Bitte extrahiere das Architekturmodell aus den beigefügten Dokumenten/Bildern.' }];
    collectParts(files).then(function (parts) {
      var images = parts.filter(function (p) { return p.type === 'image'; });
      var audios = parts.filter(function (p) { return p.type === 'audio'; });
      var texts = parts.filter(function (p) { return p.type === 'text'; });
      texts.forEach(function (t) { userParts.push({ type: 'text', text: t.text }); });
      /* Audio: transkribieren (optionales STT) */
      var audioChain = Promise.resolve();
      if (audios.length) {
        if (!set.stt) { userParts.push({ type: 'text', text: '=== AUDIO: ' + audios.map(function (a) { return a.name; }).join(', ') + ' (STT nicht konfiguriert — übergangen) ===' }); }
        else {
          audios.forEach(function (a) {
            audioChain = audioChain.then(function () {
              var fd = new FormData();
              fd.append('file', a.file);
              fd.append('model', set.stt);
              return fetch(set.base.replace(/\/+$/, '') + '/audio/transcriptions', { method: 'POST', headers: { 'Authorization': 'Bearer ' + set.key }, body: fd })
                .then(function (r) { return r.json(); })
                .then(function (j) {
                  var t = j.text || (j.error && j.error.message) || '';
                  userParts.push({ type: 'text', text: '=== SPRACHNOTIZ ' + a.name + ' ===\n' + t });
                }).catch(function () { userParts.push({ type: 'text', text: '=== SPRACHNOTIZ ' + a.name + ' (STT fehlgeschlagen) ===' }); });
            });
          });
        }
      }
      return audioChain.then(function () {
        if (images.length) {
          if (!set.vision) { statusMsg('⚠ Bilder angehängt — bitte Vision-Modell konfigurieren (Abschnitt 2).'); throw new Error('vision-needed'); }
          userParts.push({ type: 'text', text: 'Zusätzlich sind Bilder beigefügt (Whiteboard/Diagramm). Binde deren Inhalte in das Modell ein.' });
          images.forEach(function (im) { userParts.push({ type: 'image_url', image_url: { url: 'data:' + im.mime + ';base64,' + im.b64 } }); });
          return chatComplete(set, [{ role: 'system', content: sysMsg }, { role: 'user', content: userParts }], { model: set.vision || set.model });
        }
        return chatComplete(set, [{ role: 'system', content: sysMsg }, { role: 'user', content: userParts.join ? userParts.map(function (p) { return p.text; }).join('\n\n') : userParts }]);
      });
    }).then(function (content) {
      var ir = parseAndNormalize(content, voc);
      ir.validation = validateModel(ir);
      ir.mdgCoverage = mdgCoverage(ir);
      S.model = ir;
      startChat(ir, voc);
      renderResult(ir, voc);
      var vn = (ir.validation && ir.validation.viol) ? ir.validation.viol.length : 0;
      statusMsg('✔ Modell erstellt: ' + ir.elements.length + ' Elemente, ' + ir.connectors.length + ' Beziehungen.' +
        (vn ? ' ⛔ ' + vn + ' MDG-Verstoß/Verstöße — Export gesperrt (korrigieren oder „Trotzdem exportieren“).' : ' ✅ Alle Beziehungen MDG-konform — Export frei.'));
    }).catch(function (e) {
      if (e.message !== 'vision-needed') statusMsg('⚠ ' + e.message);
    }).then(function () {
      S.busy = false;
      el('ki-gen-btn').disabled = false;
    });
  }

  /* ---------- JSON parsen + normalisieren + ADMBw-Konformitaet ---------- */
  function parseAndNormalize(content, voc) {
    var j;
    try { j = JSON.parse(content); }
    catch (e) {
      var m = String(content).match(/\{[\s\S]*\}/);
      if (!m) throw new Error('KI-Antwort enthielt kein JSON.');
      try { j = JSON.parse(m[0]); } catch (e2) { throw new Error('KI-Antwort war kein gültiges JSON.'); }
    }
    j = j || {};
    var ir = { name: String(j.name || 'KI-Architektur').substring(0, 120), beschreibung: String(j.beschreibung || ''), packages: [], elements: [], connectors: [], diagrams: [], warnings: [] };

    /* Pakete */
    var pkgNames = [];
    (j.packages || []).forEach(function (p) {
      var n = String(p && p.name || '').trim();
      if (n && pkgNames.indexOf(n) < 0) { pkgNames.push(n); ir.packages.push({ name: n, parent: String(p.parent || '').trim() || null }); }
    });
    if (ir.packages.length === 0) ir.packages.push({ name: ir.name, parent: null });

    /* Elemente */
    var nameIdx = {}, allowed = voc.els;
    (j.elements || []).forEach(function (e) {
      var n = String(e && e.name || '').trim();
      var st = String(e && e.stereotype || '').trim();
      if (!n) return;
      if (nameIdx[n] != null) { ir.warnings.push('Doppelter Elementname „' + n + '“ — zusammengefasst.'); return; }
      if (st && allowed.indexOf(st) < 0) { ir.warnings.push('„' + n + '“: Stereotyp „' + st + '“ ist nicht im ADMBw-Katalog — wird trotzdem übernommen.'); }
      var pkg = String(e.package || '').trim() || ir.packages[0].name;
      nameIdx[n] = ir.elements.length;
      ir.elements.push({ name: n, stereotype: st || 'Class', type: stereotypeType(st || 'Class'), package: pkg, note: String(e.note || '').substring(0, 2000) });
    });
    if (!ir.elements.length) throw new Error('Die KI hat keine Elemente extrahiert — bitte Beschreibung präzisieren.');

    /* Beziehungen */
    (j.connectors || []).forEach(function (c) {
      var a = String(c && c.from || '').trim(), b = String(c && c.to || '').trim();
      if (a === b) return;
      if (nameIdx[a] == null || nameIdx[b] == null) { ir.warnings.push('Beziehung „' + a + ' → ' + b + '“: Element nicht gefunden — übersprungen.'); return; }
      var st = String(c && c.stereotype || 'Association').trim();
      if (st && voc.rels.indexOf(st) < 0) ir.warnings.push('Beziehungsstereotyp „' + st + '“ ist nicht im ADMBw-Katalog.');
      ir.connectors.push({ from: a, to: b, stereotype: st || 'Association', type: REL_TO_CONNECTOR[st] || 'Association', name: String(c && c.name || '').substring(0, 255) });
    });

    /* Sichten */
    (j.diagrams || []).forEach(function (d) {
      var nm = String(d && d.name || '').trim();
      var els = (d && d.elements || []).map(function (x) { return String(x).trim(); }).filter(function (x) { return x && nameIdx[x] != null; });
      if (!nm) return;
      ir.diagrams.push({ name: nm.substring(0, 255), package: String(d.package || '').trim() || ir.packages[0].name, elements: els, code: (String(d.code || '').match(/^[CSLPA]R?\d/)) ? String(d.code).trim() : null });
    });

    /* ADMBw-Abdeckung berechnen */
    var vp = (window.ADMBW_DATA && ADMBW_DATA.vp) || {};
    var coverage = {};
    ir.elements.forEach(function (e) {
      for (var code in vp) {
        if (!vp.hasOwnProperty(code)) continue;
        if ((vp[code].els || []).indexOf(e.stereotype) >= 0) coverage[code] = (coverage[code] || 0) + 1;
      }
    });
    ir.coverage = coverage;
    return ir;
  }

  /* ---------- Ergebnis-Rendering ---------- */
  function renderResult(ir, voc) {
    el('ki-output').style.display = 'block';
    var coverage = ir.mdgCoverage || ir.coverage;
    var codes = Object.keys(coverage || {}).sort();
    var covLabel = ir.mdgCoverage ? 'MDG-Viewpoints' : 'ADMBw-Abdeckung';
    var statHtml = '<b>' + esc(ir.name) + '</b> · ' + ir.elements.length + ' Elemente · ' + ir.connectors.length + ' Beziehungen · ' + ir.packages.length + ' Pakete · ' + ir.diagrams.length + ' Sichten' +
      '<br><span class="dim">' + covLabel + ': ' + codes.length + ' Viewpoints angesprochen (' + (codes.length ? codes.join(', ') : 'keine') + ')</span>';
    if (ir.validation && !ir.validation.noMdg) {
      var v = ir.validation;
      statHtml += '<br><span class="' + (v.viol.length ? 'ki-bad' : 'ki-good') + '">🔍 MDG-Validierung: ' + v.ok + '/' + v.total + ' Beziehungen konform' +
        (v.free ? ' · ' + v.free + ' ohne Regel' : '') +
        (v.unknown ? ' · ' + v.unknown + ' unbekannt' : '') +
        (v.viol.length ? ' · 🚫 ' + v.viol.length + ' VERSTOSS' : ' · ✅ alle geprüften Beziehungen regelkonform') + '</span>';
    }
    if (ir.beschreibung) statHtml += '<br><span class="dim">' + esc(ir.beschreibung) + '</span>';
    el('ki-stats').innerHTML = statHtml;

    var list = [];
    ir.packages.forEach(function (p) {
      var els = ir.elements.filter(function (e) { return e.package === p.name; });
      if (!els.length) return;
      list.push('<div class="ki-pkg"><b>📦 ' + esc(p.name) + '</b> <span class="dim">(' + els.length + ')</span></div>');
      list.push('<div class="ki-els">' + els.map(function (e) {
        return '<span class="ki-el" title="' + esc(e.stereotype) + '">' + esc(e.name) + ' <span class="dim">«' + esc(e.stereotype) + '»</span></span>';
      }).join('') + '</div>');
    });
    if (ir.connectors.length) {
      list.push('<div class="ki-pkg"><b>🔗 Beziehungen (' + ir.connectors.length + ')</b></div>');
      list.push('<div class="ki-els">' + ir.connectors.slice(0, 40).map(function (c) {
        return '<span class="ki-el dim">' + esc(c.from) + ' → ' + esc(c.to) + ' «' + esc(c.stereotype) + '»</span>';
      }).join('') + (ir.connectors.length > 40 ? ' <span class="dim">…</span>' : '') + '</div>');
    }
    if (ir.validation && ir.validation.viol && ir.validation.viol.length) {
      list.push('<div class="ki-pkg"><b>🚫 MDG-Verstöße (' + ir.validation.viol.length + ')</b></div>');
      list.push('<div class="ki-els">' + ir.validation.viol.map(function (x) {
        return '<span class="ki-el bad">' + esc(x.from) + ' -«' + esc(x.stereotype) + '»→ ' + esc(x.to) + '<br><span class="dim">' + esc(x.why) + '</span></span>';
      }).join('') + '</div>');
    }
    /* Export-Sperre: Warnbox + Override-Checkbox nur bei Verstößen zeigen */
    var violN = (ir.validation && ir.validation.viol) ? ir.validation.viol.length : 0;
    var expWarn = el('ki-export-warn');
    if (expWarn) {
      if (violN) {
        expWarn.style.display = 'block';
        expWarn.innerHTML = '<b>⛔ ' + violN + ' MDG-Verstoß/Verstöße — der .qea-Export ist gesperrt</b>, bis das Modell korrigiert ist (Dialog „Verfeinern“) oder „Trotzdem exportieren“ aktiviert wird.';
      } else {
        expWarn.style.display = 'none';
        expWarn.innerHTML = '';
      }
    }
    var expLbl = el('ki-export-override-lbl');
    if (expLbl) expLbl.style.display = violN ? 'inline-block' : 'none';
    if (ir.warnings.length) {
      list.push('<div class="ki-pkg"><b>⚠ Hinweise (' + ir.warnings.length + ')</b></div>');
      list.push('<div class="ki-els">' + ir.warnings.slice(0, 12).map(function (w) { return '<span class="ki-el warn">' + esc(w) + '</span>'; }).join('') + '</div>');
    }
    el('ki-list').innerHTML = list.join('');
    el('ki-report-out').style.display = 'none';
    el('ki-report-out').innerHTML = '';
  }

  /* ---------- Export: .qea bauen (sql.js) ---------- */
  function ensureSql() {
    if (S.sqlP) return S.sqlP;
    S.sqlP = new Promise(function (resolve, reject) {
      if (typeof initSqlJs !== 'function') { reject(new Error('SQLite-Engine fehlt im Build.')); return; }
      var b64 = window.SQLJS_WASM_B64 || '';
      var bin = atob(b64), n = bin.length, u8 = new Uint8Array(n), i;
      for (i = 0; i < n; i++) u8[i] = bin.charCodeAt(i);
      initSqlJs({ wasmBinary: u8.buffer }).then(resolve, function () {
        var url = URL.createObjectURL(new Blob([u8], { type: 'application/wasm' }));
        initSqlJs({ locateFile: function () { return url; } }).then(resolve, reject);
      });
    });
    return S.sqlP;
  }
  function newGuid() {
    var h = '0123456789ABCDEF', g = '';
    for (var i = 0; i < 32; i++) g += h[Math.floor(Math.random() * 16)];
    return '{' + g.substring(0, 8) + '-' + g.substring(8, 12) + '-' + g.substring(12, 16) + '-' + g.substring(16, 20) + '-' + g.substring(20) + '}';
  }
  function nowStr() {
    var d = new Date();
    function p(x) { return (x < 10 ? '0' : '') + x; }
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  function escSql(db, s) {
    /* Parameter über prepare/bind statt String-Escaping */
    return s;
  }

  function buildQea() {
    return ensureSql().then(function (SQL) {
      var ir = S.model;
      if (!ir) throw new Error('Zuerst Modell generieren (Schritt 3).');
      if (!S.template) throw new Error('Bitte zuerst EABase-Grundgerüst wählen (Schritt 1).');
      var db = new SQL.Database(new Uint8Array(S.template));
      var st, r;
      var clear = el('ki-clearmodel').checked;

      function maxId(tbl, col) {
        st = db.prepare('SELECT COALESCE(MAX(' + col + '),0) AS m FROM ' + tbl);
        var m = 0;
        if (st.step()) m = st.getAsObject().m;
        st.free();
        return m;
      }
      function ins(tbl, cols, vals) {
        db.run('INSERT INTO ' + tbl + ' (' + cols.join(',') + ') VALUES (' + cols.map(function () { return '?'; }).join(',') + ')', vals);
      }

      if (clear) {
        ['t_diagramlinks', 't_diagramobjects', 't_objectproperties', 't_connector', 't_object', 't_diagram', 't_package'].forEach(function (t) {
          try { db.run('DELETE FROM ' + t); } catch (e) { }
        });
        try { db.run("DELETE FROM t_xref WHERE Client IN (SELECT ea_guid FROM t_object)"); } catch (e) { }
      }

      var oid = maxId('t_object', 'Object_ID'), pid = maxId('t_package', 'Package_ID'),
        cid = maxId('t_connector', 'Connector_ID'), did = maxId('t_diagram', 'Diagram_ID'),
        iid = maxId('t_diagramobjects', 'Instance_ID'), prpid = maxId('t_objectproperties', 'PropertyID'),
        lid = maxId('t_diagramlinks', 'Instance_ID');
      var ts = nowStr();

      /* 1) Root-Modell + Pakete */
      var rootPkg = ++pid;
      ins('t_package', ['Package_ID', 'Name', 'Parent_ID', 'CreatedDate', 'ModifiedDate', 'ea_guid'],
        [rootPkg, ir.name, 0, ts, ts, newGuid()]);
      var pkgId = {}, pkgIds = {};
      pkgIds[ir.packages[0].name] = rootPkg;
      ir.packages.forEach(function (p) {
        if (p.name === ir.packages[0].name) return;
        var parent = p.parent && pkgIds[p.parent] != null ? pkgIds[p.parent] : rootPkg;
        var id = ++pid;
        pkgIds[p.name] = id;
        ins('t_package', ['Package_ID', 'Name', 'Parent_ID', 'CreatedDate', 'ModifiedDate', 'ea_guid'],
          [id, p.name, parent, ts, ts, newGuid()]);
        /* Package-Objekt (EA-Konvention: sitzt im Elternpaket, PDATA1 = eigene Paket-ID) */
        var o = ++oid;
        ins('t_object', ['Object_ID', 'Object_Type', 'Name', 'Package_ID', 'PDATA1', 'NType', 'ea_guid', 'Author', 'Version', 'CreatedDate', 'ModifiedDate'],
          [o, 'Package', p.name, parent, String(id), 0, newGuid(), 'EAM AI Suite KI', '1.0', ts, ts]);
      });

      /* 2) Elemente */
      var objId = {};
      ir.elements.forEach(function (e) {
        var o = ++oid;
        objId[e.name] = o;
        var pkg = pkgIds[e.package] != null ? pkgIds[e.package] : rootPkg;
        ins('t_object', ['Object_ID', 'Object_Type', 'Name', 'Note', 'Package_ID', 'ea_guid', 'Author', 'Version', 'Stereotype', 'CreatedDate', 'ModifiedDate', 'Status', 'Abstract'],
          [o, e.type || 'Class', e.name, e.note || '', pkg, newGuid(), 'EAM AI Suite KI', '1.0', e.stereotype || '', ts, ts, 'Proposed', 0]);
      });

      /* 3) Beziehungen */
      ir.connectors.forEach(function (c) {
        var a = objId[c.from], b = objId[c.to];
        if (a == null || b == null) return;
        var id = ++cid;
        c.__cid = id;
        ins('t_connector', ['Connector_ID', 'Connector_Type', 'Name', 'Direction', 'Start_Object_ID', 'End_Object_ID', 'ea_guid', 'Stereotype', 'SourceAccess', 'DestAccess', 'RouteStyle'],
          [id, c.type || 'Association', c.name || '', 'Source -> Destination', a, b, newGuid(), c.stereotype || '', 'Public', 'Public', 3]);
      });

      /* 4) Sichten (fehlen sie -> automatisch je Viewpoint-Code gruppieren) */
      var diagrams = ir.diagrams.slice();
      if (!diagrams.length) {
        var vp = (window.ADMBW_DATA && ADMBW_DATA.vp) || {};
        var order = ['C1', 'C2', 'C3', 'C4', 'C5', 'C7', 'C8', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'A1', 'A2', 'A3', 'R2', 'R3', 'R7', 'R8'];
        order.forEach(function (code) {
          if (!vp[code]) return;
          var els = ir.elements.filter(function (e) { return (vp[code].els || []).indexOf(e.stereotype) >= 0; });
          if (els.length) diagrams.push({ name: code + ' : ' + ir.name + ' : ' + vp[code].n, package: ir.packages[0].name, elements: els.map(function (e) { return e.name; }), code: code });
        });
      }
      var dgId = {};
      diagrams.forEach(function (d, di) {
        var id = ++did;
        dgId[d.name + '|' + di] = id;
        var pkg = pkgIds[d.package] != null ? pkgIds[d.package] : rootPkg;
        var vpInfo = null, code = d.code;
        var vp = (window.ADMBW_DATA && ADMBW_DATA.vp) || {};
        if (code && vp[code]) vpInfo = vp[code];
        var mdg = vpInfo ? 'NAFv4-ADMBw ' + vpInfo.layer + '::' + code + ' - ' + vpInfo.n : '';
        var styleEx = 'SaveTag=' + newGuid().replace(/[{}]/g, '').substring(0, 8) + ';ExcludeRTF=0;DocAll=0;HideQuals=0;AttPkg=1;ShowTests=0;ShowMaint=0;SuppressFOC=1;' + (mdg ? 'MDGDgm=' + mdg + ';' : '');
        ins('t_diagram', ['Diagram_ID', 'Package_ID', 'Name', 'ParentID', 'Diagram_Type', 'ea_guid', 'Version', 'Author', 'CreatedDate', 'ModifiedDate', 'StyleEx', 'ShowForeign', 'ShowPackageContents', 'Orientation', 'Scale'],
          [id, pkg, d.name, 0, 'Custom', newGuid(), '1.0', 'EAM AI Suite KI', ts, ts, styleEx, 1, 1, 'P', 100]);
        /* Layout: 3 Spalten */
        var i, n = d.elements.length, dx = 0, dy = 0;
        for (i = 0; i < n; i++) {
          var o = objId[d.elements[i]];
          if (o == null) continue;
          var col = i % 3, row = Math.floor(i / 3);
          var x = 30 + col * 420, y = 30 + row * 130;
          var oi = ++iid;
          ins('t_diagramobjects', ['Instance_ID', 'Diagram_ID', 'Object_ID', 'RectTop', 'RectLeft', 'RectRight', 'RectBottom', 'Sequence', 'ObjectStyle'],
            [oi, id, o, -y, x, x + 380, -y - 90, i + 1, 'HideIcon=0;DUID=' + newGuid().replace(/[{}]/g, '').substring(0, 8) + ';']);
        }
        /* Diagrammlinks fuer Beziehungen zwischen Elementen dieser Sicht */
        ir.connectors.forEach(function (c) {
          var a = objId[c.from], b = objId[c.to];
          if (a == null || b == null) return;
          if (d.elements.indexOf(c.from) >= 0 && d.elements.indexOf(c.to) >= 0) {
            ins('t_diagramlinks', ['Instance_ID', 'DiagramID', 'ConnectorID', 'Geometry'],
              [++lid, id, c.__cid, '']);
          }
        });
      });

      var out = db.export();
      db.close();
      /* ArrayBuffer mit exakter Länge (nicht die Sicht) — qeaOpen erwartet ArrayBuffer */
      return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);
    });
  }

  /* MDG-Prüfung vor dem Export: liefert die aktuelle Validierung oder null,
     wenn keine Verstöße bekannt sind (bzw. keine MDG geladen ist). */
  function mdgExportGate() {
    var ir = S.model;
    if (!ir || !S.mdg || !S.mdg.connectorStereo) return null;
    var v = validateModel(ir);
    ir.validation = v;
    return (v.viol && v.viol.length) ? v : null;
  }

  function exportQea() {
    if (S.busy) return;
    var v = mdgExportGate();
    var force = el('ki-export-override') && el('ki-export-override').checked;
    if (v && !force) {
      var n = v.viol.length;
      var warn = el('ki-export-warn');
      if (warn) {
        warn.style.display = 'block';
        warn.innerHTML = '<b>⛔ Export blockiert: ' + n + ' MDG-Verstoß/Verstöße.</b> Korrigieren Sie die Beziehungen im Dialog „Verfeinern“ — oder aktivieren Sie unten „Trotzdem exportieren“.';
      }
      var lbl = el('ki-export-override-lbl');
      if (lbl) lbl.style.display = 'inline-block';
      statusMsg('⛔ Export blockiert: ' + n + ' MDG-Verstoß/Verstöße — Modell korrigieren oder „Trotzdem exportieren“ aktivieren.');
      return;
    }
    if (v) statusMsg('⚠ Export trotz ' + v.viol.length + ' MDG-Verstößen (Override aktiv) — wird erzeugt …');
    else statusMsg('⏳ .qea wird erzeugt …');
    S.busy = true;
    buildQea().then(function (bytes) {
      S.bytes = bytes;
      S.modelName = (S.model && S.model.name) || 'Modell';
      var fname = safeName(S.modelName) + '_KI_' + new Date().toISOString().replace(/[-:T]/g, '').substring(0, 12) + '.qea';
      var blob = new Blob([bytes], { type: 'application/octet-stream' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = fname;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      statusMsg('✔ ' + fname + ' exportiert.');
      S.busy = false;
    }).catch(function (e) {
      statusMsg('⚠ ' + e.message);
      S.busy = false;
    });
  }

  /* ---------- In der App analysieren (Roundtrip durch den nativen Reader) ---------- */
  function analyzeInApp() {
    if (S.bytes) {
      SINGLE = true; MULTI_MODE = false;
      try {
        loadQea(S.bytes, (S.model && S.model.name) || 'KI-Architektur');
        statusMsg('✔ Modell geladen — erkunden Sie es in den Tabs.');
        return;
      } catch (e) { statusMsg('⚠ Laden fehlgeschlagen: ' + e.message); }
    }
    buildQea().then(function (bytes) {
      S.bytes = bytes;
      SINGLE = true; MULTI_MODE = false;
      try {
        loadQea(bytes, (S.model && S.model.name) || 'KI-Architektur');
        statusMsg('✔ Modell geladen — erkunden Sie es in den Tabs.');
      } catch (e) { statusMsg('⚠ Laden fehlgeschlagen: ' + e.message); }
    }).catch(function (e) { statusMsg('⚠ ' + e.message); });
  }

  /* ---------- KI-Analysebericht ---------- */
  function report() {
    var set = saveSettings();
    if (!set.key || !S.model) { statusMsg('⚠ Erst Modell generieren.'); return; }
    statusMsg('⏳ Analysebericht wird erstellt …');
    var ir = S.model;
    var cover = Object.keys(ir.coverage).sort();
    var summary = JSON.stringify({
      name: ir.name,
      packages: ir.packages.length,
      elements: ir.elements.map(function (e) { return e.name + ' «' + e.stereotype + '»'; }),
      connectors: ir.connectors.map(function (c) { return c.from + ' -«' + c.stereotype + '»-> ' + c.to; }),
      diagrams: ir.diagrams.map(function (d) { return d.name + ' (' + d.elements.length + ' Elemente)'; }),
      admbw_coverage: cover
    });
    var msgs = [
      { role: 'system', content: 'Du bist Enterprise-Architekt. Erstelle einen kompakten Analysebericht (Deutsch) zu dem Architekturmodell: 1) Zweck & Schichten, 2) ADMBw/NAFv4-Abdeckung & Lücken, 3) Risiken/Unstimmigkeiten, 4) konkrete nächste Modellierungsschritte. Antwort als JSON: {"bericht": "..."} (Markdown erlaubt im Text).' },
      { role: 'user', content: 'Modell:\n' + summary }
    ];
    chatComplete(set, msgs).then(function (c) {
      var j = {};
      try { j = JSON.parse(c); } catch (e) { var m = String(c).match(/\{[\s\S]*\}/); if (m) try { j = JSON.parse(m[0]); } catch (e2) { } }
      var txt = j.bericht || c;
      el('ki-report-out').style.display = 'block';
      el('ki-report-out').innerHTML = '<b>📋 KI-Analysebericht</b><br>' + String(txt)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>').replace(/^### (.*)$/gm, '<b>$1</b>').replace(/^## (.*)$/gm, '<b>$1</b>');
      statusMsg('✔ Bericht fertig.');
    }).catch(function (e) { statusMsg('⚠ ' + e.message); });
  }

  /* ---------- UI-Verdrahtung ---------- */
  function init() {
    var s = loadSettings();
    el('ki-base').value = s.base;
    el('ki-model').value = s.model;
    if (el('ki-vision')) el('ki-vision').value = s.vision;
    if (el('ki-stt')) el('ki-stt').value = s.stt;
    el('ki-key').value = s.key;
    ['ki-base', 'ki-model', 'ki-vision', 'ki-stt', 'ki-key'].forEach(function (id) {
      var e = el(id);
      if (e) e.addEventListener('change', saveSettings);
    });
    if (el('ki-files')) el('ki-files').addEventListener('change', function () {
      var n = (el('ki-files').files || []).length;
      el('ki-files-info').textContent = n ? n + ' Anhang/Anhänge' : '';
    });
  }

  /* ---------- Stereotyp -> Object_Type: MDG zuerst, sonst Fallback ---------- */
  function stereotypeType(st) {
    if (S.mdg && S.mdg.elementStereo && S.mdg.elementStereo[st]) {
      var a = S.mdg.elementStereo[st].appliesTo || [];
      if (a.length) return a[0];
    }
    return STEOTYPE_TO_TYPE[st] || 'Class';
  }

  /* ---------- MDG-Datei wählen ---------- */
  function setMdgFromBytes(buffer, name) {
    var rules = loadMdg(buffer, name);
    el('ki-mdg-info').textContent = (rules.profileName || name) + ' · ' + rules.elementNames.length + ' Stereotypen / ' + rules.connectorNames.length + ' Beziehungen ✓';
    return rules;
  }
  function pickMdg() {
    var inp = el('ki-mdg-file');
    if (!inp) {
      inp = document.createElement('input');
      inp.type = 'file';
      inp.id = 'ki-mdg-file';
      inp.accept = '.xml,.mdgts,.mdg,.technology';
      inp.style.display = 'none';
      document.body.appendChild(inp);
      inp.addEventListener('change', function () {
        var f = inp.files && inp.files[0];
        if (!f) return;
        var rd = new FileReader();
        rd.onload = function () {
          try { setMdgFromBytes(rd.result, f.name); }
          catch (e) { el('ki-mdg-info').textContent = '⚠ ' + e.message; }
        };
        rd.onerror = function () { el('ki-mdg-info').textContent = 'Lesefehler.'; };
        rd.readAsArrayBuffer(f);
      });
    }
    inp.click();
  }

  /* ---------- Template wählen ---------- */
  function setTemplate(buffer, name) {
    S.template = buffer;
    S.templateName = name || 'EABase.qea';
    el('ki-template-info').textContent = S.templateName + ' (' + Math.round((buffer.byteLength || 0) / 1024) + ' KB) ✓';
  }
  function pickTemplate() {
    var inp = el('ki-template-file');
    if (!inp) {
      inp = document.createElement('input');
      inp.type = 'file';
      inp.id = 'ki-template-file';
      inp.accept = '.qea,.eapx,.qeax,.sqlite';
      inp.style.display = 'none';
      document.body.appendChild(inp);
      inp.addEventListener('change', function () {
        var f = inp.files && inp.files[0];
        if (!f) return;
        var rd = new FileReader();
        rd.onload = function () {
          S.template = rd.result;
          S.templateName = f.name;
          el('ki-template-info').textContent = f.name + ' (' + Math.round(f.size / 1024) + ' KB) ✓';
        };        rd.onerror = function () { el('ki-template-info').textContent = 'Lesefehler.'; };
        rd.readAsArrayBuffer(f);
      });
    }
    inp.click();
  }

  /* ---------- Beispiel ---------- */
  /* MDG-konformes Beispiel (Nachtlauf 19.10.2026): jede Beziehung entspricht
     den Metaconstraints der offiziellen MDG 2026.05. Insbesondere:
     Satisfy = Subjekt (System/Organisation/Ressource) -> StrategicConstraint;
     Anforderung -> Fähigkeit ist NICHT modellierbar (keine MDG-Regel) —
     Anforderungen verbinden sich per Requires (BWRequirement -> BWRequirement). */
  function fillExample() {
    el('ki-prompt').value = 'Wir entwickeln die mobile Lagebild-Anwendung "Führungsunterstützung Mobil" (FuUMobil).\n' +
      'Die Organisation Kommando Aufklärung ist verantwortlich für den Dienst Lagedienst.\n' +
      'Die Fähigkeit Kartendarstellung ist eine Unterfähigkeit der Fähigkeit Lagebildbereitstellung.\n' +
      'Das System Lagebild-Server erfüllt die strategische Vorgabe Ausfallsicherheit gewährleisten.\n' +
      'Das System Endgerät Tablet weist die Fähigkeit Kartendarstellung nach.\n' +
      'Der Prozess Lagebild erstellen tauscht Informationen aus mit dem Prozess Alarmierung durchführen.\n' +
      'Der Prozess Lagebild erstellen verändert die Information Lagedaten.\n' +
      'Der Dienst Lagedienst tauscht Daten aus mit dem Dienst Alarmierungsdienst.\n' +
      'Die Anforderung Sturmalarm setzt die Anforderung Schnelle Warnausgabe voraus.';
  }

  window.KI = { init: init, pickTemplate: pickTemplate, setTemplate: setTemplate, pickMdg: pickMdg, setMdgFromBytes: setMdgFromBytes, loadMdg: loadMdg, validateModel: validateModel, getModel: function () { return S.model; }, newArchitecture: newArchitecture, requireMdg: requireMdg, fillExample: fillExample, generate: generate, exportQea: exportQea, analyzeInApp: analyzeInApp, report: report, chatSend: chatSend, chatAdd: chatAdd, modelToText: modelToText, modelInventory: modelInventory, runOps: runOps, Op: Op, buildBytes: function () { return buildQea(); },
    /* Nur LESENDER Zugriff auf die bestehende KI-Konfiguration (Felder des KI-Tabs,
       Fallback: zuletzt gespeicherte Einstellungen). Wird vom Rückweg (Teil 7)
       genutzt, damit es KEINE zweite Konfiguration gibt. Kein Schreiben. */
    cfg: function () {
      var d = loadSettings();
      try {
        if (el('ki-base')) d.base = el('ki-base').value.trim() || d.base;
        if (el('ki-model')) d.model = el('ki-model').value.trim() || d.model;
        if (el('ki-key')) d.key = el('ki-key').value.trim();
      } catch (e) { }
      return d;
    }
  };
  window.newArchitecture = newArchitecture;
  try { init(); } catch (e) { if (window.console) console.error('KI.init:', e); }
})();
