/* eam-mdg.js -- MDG-Technologie-Parser und Modell-Validator fuer Web & Node.
 *
 * Eine Quelle fuer:
 *   - apps/html-suite (EAM-AI-Suite)
 *   - apps/html-editor (EAM-Suite, Offline-Fassung ohne KI)
 *   - apps/html-sichten-archiv
 *   - node-basierte Tests und CLI-Werkzeuge
 *
 * Funktionen:
 *   - EAMMDG.parseMdg(xmlText): Parst MDG-XML in ein kanonisches Regelwerk.
 *   - EAMMDG.validateModel(dbOrIr, mdgXmlOrRules): Prueft Modell (IR oder DB-Interface) gegen MDG.
 *   - EAMMDG.summarize(findings): Zaehlt Gesamt, Fehler, Warnungen.
 */
(function (global) {
  'use strict';

  var CONNECTOR_METACLASSES = {
    abstraction: true,
    aggregation: true,
    association: true,
    composition: true,
    connector: true,
    controlflow: true,
    dependency: true,
    deployment: true,
    extend: true,
    generalization: true,
    include: true,
    informationflow: true,
    manifestation: true,
    message: true,
    objectflow: true,
    realisation: true,
    realization: true,
    substitution: true,
    usage: true
  };

  var SOURCE_ROLES = {
    client: true,
    source: true,
    informationsource: true,
    'end[0]': true,
    'end[0].role': true
  };

  var TARGET_ROLES = {
    supplier: true,
    target: true,
    informationtarget: true,
    'end[1]': true,
    'end[1].role': true
  };

  /* ================= XML-Hilfen (Browser & Node Fallback) ================= */

  function parseXml(xmlText) {
    if (typeof DOMParser !== 'undefined') {
      var doc = new DOMParser().parseFromString(String(xmlText || ''), 'application/xml');
      var err = doc.getElementsByTagName('parsererror')[0];
      if (err) throw new Error('MDG-XML fehlerhaft: ' + (err.textContent || 'Parserfehler'));
      return doc;
    }
    // Node.js fallback parser (einfacher DOM-Tree)
    return simpleXmlParse(String(xmlText || ''));
  }

  function simpleXmlParse(text) {
    // Einfacher rekursiver XML-Parser fuer Standard-Node-Umgebungen ohne xmldom
    var pos = 0;
    var len = text.length;

    function skipWhitespace() {
      while (pos < len && /\s/.test(text.charAt(pos))) pos++;
    }

    function parseElement() {
      skipWhitespace();
      if (pos >= len || text.charAt(pos) !== '<') return null;

      // Processing instructions or comments
      if (text.substr(pos, 4) === '<!--') {
        var endComment = text.indexOf('-->', pos + 4);
        pos = (endComment >= 0) ? endComment + 3 : len;
        return parseElement();
      }
      if (text.substr(pos, 2) === '<?') {
        var endPi = text.indexOf('?>', pos + 2);
        pos = (endPi >= 0) ? endPi + 2 : len;
        return parseElement();
      }
      if (text.substr(pos, 9) === '<![CDATA[') {
        var endCdata = text.indexOf(']]>', pos + 9);
        var cdText = (endCdata >= 0) ? text.substring(pos + 9, endCdata) : text.substring(pos + 9);
        pos = (endCdata >= 0) ? endCdata + 3 : len;
        return { nodeType: 3, textContent: cdText, nodeName: '#text', childNodes: [] };
      }

      pos++; // skip '<'
      var nameMatch = text.substr(pos).match(/^([a-zA-Z0-9_\-.:]+)/);
      if (!nameMatch) return null;
      var tag = nameMatch[1];
      pos += tag.length;

      var attrs = {};
      while (pos < len) {
        skipWhitespace();
        if (text.charAt(pos) === '/' && text.charAt(pos + 1) === '>') {
          pos += 2;
          return {
            nodeType: 1,
            nodeName: tag,
            attributes: attrs,
            getAttribute: function (k) { return attrs[k] !== undefined ? attrs[k] : null; },
            childNodes: [],
            textContent: ''
          };
        }
        if (text.charAt(pos) === '>') {
          pos++;
          break;
        }
        var attrMatch = text.substr(pos).match(/^([a-zA-Z0-9_\-.:]+)\s*=\s*(["'])(.*?)\2/);
        if (attrMatch) {
          attrs[attrMatch[1]] = unescapeXml(attrMatch[3]);
          pos += attrMatch[0].length;
        } else {
          pos++;
        }
      }

      var children = [];
      var textContent = '';
      var closeTag = '</' + tag + '>';

      while (pos < len) {
        skipWhitespace();
        if (text.substr(pos, closeTag.length) === closeTag) {
          pos += closeTag.length;
          break;
        }
        if (text.charAt(pos) === '<') {
          if (text.substr(pos, 2) === '</') {
            // Unmatched or outer closing tag
            var endClose = text.indexOf('>', pos);
            pos = (endClose >= 0) ? endClose + 1 : len;
            break;
          }
          var child = parseElement();
          if (child) {
            children.push(child);
            if (child.textContent) textContent += child.textContent;
          }
        } else {
          var nextAngle = text.indexOf('<', pos);
          if (nextAngle < 0) nextAngle = len;
          var chunk = unescapeXml(text.substring(pos, nextAngle));
          textContent += chunk;
          pos = nextAngle;
        }
      }

      return {
        nodeType: 1,
        nodeName: tag,
        attributes: attrs,
        getAttribute: function (k) { return attrs[k] !== undefined ? attrs[k] : null; },
        childNodes: children,
        textContent: textContent
      };
    }

    var root = null;
    while (pos < len) {
      var el = parseElement();
      if (el && el.nodeType === 1) {
        root = el;
        break;
      }
    }

    return {
      documentElement: root,
      getElementsByTagName: function (t) {
        var out = [];
        function walk(node) {
          if (!node || node.nodeType !== 1) return;
          if (localTag(node.nodeName) === localTag(t) || t === '*') out.push(node);
          var ch = node.childNodes || [];
          for (var i = 0; i < ch.length; i++) walk(ch[i]);
        }
        if (root) walk(root);
        return out;
      }
    };
  }

  function unescapeXml(s) {
    if (!s) return '';
    return String(s)
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&apos;/g, "'");
  }

  function localTag(tag) {
    var t = String(tag || '');
    var idx = t.lastIndexOf(':');
    return idx >= 0 ? t.slice(idx + 1) : t;
  }

  function getAttr(elem, name) {
    if (!elem) return '';
    if (elem.getAttribute) {
      var val = elem.getAttribute(name);
      if (val !== null && val !== undefined) return String(val).trim();
    }
    if (elem.attributes && elem.attributes[name] !== undefined) {
      return String(elem.attributes[name]).trim();
    }
    return '';
  }

  function getKids(elem, name) {
    var out = [];
    if (!elem) return out;
    var ch = elem.childNodes || [];
    for (var i = 0; i < ch.length; i++) {
      if (ch[i].nodeType === 1 && localTag(ch[i].nodeName) === name) {
        out.push(ch[i]);
      }
    }
    return out;
  }

  function getKid(elem, name) {
    var list = getKids(elem, name);
    return list.length ? list[0] : null;
  }

  /* ================= MDG-XML Parser ================= */

  function parseMdg(xmlText) {
    var doc = parseXml(xmlText);
    var root = doc.documentElement;
    if (!root) throw new Error('MDG-XML enthaelt kein Wurzelelement');

    var profileId = getAttr(root, 'id') || getAttr(root, 'name') || 'MDG';

    // Stereotype nach Elementen und Konnektoren aufteilen
    var elementStereotypes = [];
    var connectorRules = [];
    var taggedValueTypes = [];

    // TaggedValueTypes einlesen
    var allDataSets = doc.getElementsByTagName ? doc.getElementsByTagName('DataSet') : [];
    for (var d = 0; d < allDataSets.length; d++) {
      var ds = allDataSets[d];
      if (getAttr(ds, 'name') === 'Property Types') {
        var rows = getKids(ds, 'DataRow');
        for (var r = 0; r < rows.length; r++) {
          var cols = getKids(rows[r], 'Column');
          var propData = {};
          for (var c = 0; c < cols.length; c++) {
            var colName = getAttr(cols[c], 'name');
            var colVal = getAttr(cols[c], 'value');
            if (colName) propData[colName] = colVal;
          }
          if (propData.Property) {
            taggedValueTypes.push({
              name: propData.Property,
              description: propData.Description || '',
              notes: propData.Notes || ''
            });
          }
        }
      }
    }

    // Stereotype einlesen
    var allStereotypes = doc.getElementsByTagName ? doc.getElementsByTagName('Stereotype') : [];
    for (var s = 0; s < allStereotypes.length; s++) {
      var stElem = allStereotypes[s];
      var name = getAttr(stElem, 'name');
      if (!name) continue;

      var metaclassAttr = getAttr(stElem, 'metaclass') || getAttr(stElem, 'metatype');
      var metaclasses = metaclassAttr ? [metaclassAttr] : [];

      // Falls untergeordnete <metaclass>-Tags vorhanden sind
      var mcKids = getKids(stElem, 'metaclass');
      for (var m = 0; m < mcKids.length; m++) {
        var mcName = getAttr(mcKids[m], 'name');
        if (mcName && metaclasses.indexOf(mcName) < 0) metaclasses.push(mcName);
      }

      var isConnector = false;
      for (var mi = 0; mi < metaclasses.length; mi++) {
        if (CONNECTOR_METACLASSES[metaclasses[mi].toLowerCase()]) {
          isConnector = true;
          break;
        }
      }

      // TaggedValues
      var tagDefs = [];
      var tvBox = getKid(stElem, 'TaggedValues');
      if (tvBox) {
        var tagKids = getKids(tvBox, 'Tag');
        for (var tk = 0; tk < tagKids.length; tk++) {
          var tElem = tagKids[tk];
          var tName = getAttr(tElem, 'name');
          if (tName) {
            var tVals = getAttr(tElem, 'values');
            tagDefs.push({
              name: tName,
              type: getAttr(tElem, 'type') || '',
              description: getAttr(tElem, 'description') || '',
              values: tVals ? tVals.split(',').map(function (v) { return v.trim(); }) : [],
              default: getAttr(tElem, 'default') || ''
            });
          }
        }
      }

      // Vererbung
      var generalizes = [];
      var genBox = getKid(stElem, 'Generalizes');
      if (genBox) {
        var genKids = getKids(genBox, 'Generalize');
        for (var gk = 0; gk < genKids.length; gk++) {
          var gName = getAttr(genKids[gk], 'name');
          if (gName) generalizes.push(gName);
        }
      }

      // Connector Metaconstraints & Metarelationships
      var metaconstraints = [];
      var mcBox = getKid(stElem, 'metaconstraints');
      if (mcBox) {
        var constrKids = getKids(mcBox, 'metaconstraint');
        var grouped = {};
        for (var ck = 0; ck < constrKids.length; ck++) {
          var role = getAttr(constrKids[ck], 'umlRole');
          var cVal = getAttr(constrKids[ck], 'constraint');
          if (role && cVal) {
            grouped[role] = grouped[role] || [];
            var tokens = cVal.split(',').map(function (t) { return t.trim(); });
            for (var ti = 0; ti < tokens.length; ti++) {
              if (grouped[role].indexOf(tokens[ti]) < 0) grouped[role].push(tokens[ti]);
            }
          }
        }
        for (var rk in grouped) {
          metaconstraints.push({ role: rk, constraints: grouped[rk].sort() });
        }
      }

      if (isConnector) {
        connectorRules.push({
          id: 'cr:' + name,
          name: name,
          metaclasses: metaclasses,
          metaconstraints: metaconstraints,
          generalizes: generalizes,
          taggedValues: tagDefs
        });
      } else {
        elementStereotypes.push({
          name: name,
          metaclasses: metaclasses.length ? metaclasses : ['Class'],
          generalizes: generalizes,
          taggedValues: tagDefs
        });
      }
    }

    return {
      schemaVersion: 1,
      profile: profileId,
      elementStereotypes: elementStereotypes,
      connectorRules: connectorRules,
      taggedValueTypes: taggedValueTypes
    };
  }

  /* ================= Validator ================= */

  function validateModel(dbOrIr, mdgXmlOrRules) {
    var rules = null;
    if (typeof mdgXmlOrRules === 'string') {
      rules = parseMdg(mdgXmlOrRules);
    } else if (mdgXmlOrRules && typeof mdgXmlOrRules === 'object') {
      rules = mdgXmlOrRules;
    } else {
      throw new Error('Regelwerk fehlt (MDG-XML oder Rules-Objekt uebergeben)');
    }

    // Lookup-Maps erstellen
    var elemRules = {};
    var connRules = {};
    var tvTypes = {};

    var elList = rules.elementStereotypes || [];
    for (var i = 0; i < elList.length; i++) {
      var er = elList[i];
      if (er && er.name) elemRules[er.name.toLowerCase()] = er;
    }

    var crList = rules.connectorRules || [];
    for (var j = 0; j < crList.length; j++) {
      var cr = crList[j];
      if (cr && cr.name) connRules[cr.name.toLowerCase()] = cr;
    }

    var tvList = rules.taggedValueTypes || [];
    for (var k = 0; k < tvList.length; k++) {
      var tvt = tvList[k];
      if (tvt && tvt.name) tvTypes[tvt.name.toLowerCase()] = tvt;
    }

    // Elemente und Beziehungen extrahieren
    var elements = [];
    var connectors = [];
    var idToElement = {};

    if (dbOrIr && typeof dbOrIr.rows === 'function') {
      // DB-Interface (SQLite oder eam-formats)
      var tObj = dbOrIr.rows('t_object') || [];
      var tProp = dbOrIr.rows('t_objectproperties') || [];
      var tagsByObj = {};
      for (var p = 0; p < tProp.length; p++) {
        var tp = tProp[p];
        var oid = tp.Object_ID;
        if (!tagsByObj[oid]) tagsByObj[oid] = {};
        if (tp.Property) tagsByObj[oid][tp.Property] = tp.Value || '';
      }
      for (var e = 0; e < tObj.length; e++) {
        var ob = tObj[e];
        var elItem = {
          id: ob.Object_ID,
          ea_guid: ob.ea_guid,
          name: ob.Name || '',
          stereotype: ob.Stereotype || '',
          ea_type: ob.Object_Type || '',
          tags: tagsByObj[ob.Object_ID] || {}
        };
        elements.push(elItem);
        idToElement[ob.Object_ID] = elItem;
      }
      var tConn = dbOrIr.rows('t_connector') || [];
      for (var cn = 0; cn < tConn.length; cn++) {
        var tc = tConn[cn];
        connectors.push({
          id: tc.Connector_ID,
          ea_guid: tc.ea_guid,
          name: tc.Name || '',
          stereotype: tc.Stereotype || '',
          connector_type: tc.Connector_Type || '',
          start_id: tc.Start_Object_ID,
          end_id: tc.End_Object_ID
        });
      }
    } else if (dbOrIr && typeof dbOrIr === 'object') {
      // IR-Format
      var irElements = dbOrIr.elements || [];
      for (var ie = 0; ie < irElements.length; ie++) {
        var iel = irElements[ie];
        var elObj = {
          id: iel.guid || iel.ea_guid || ('elem_' + ie),
          ea_guid: iel.ea_guid || iel.guid,
          name: iel.name || '',
          stereotype: iel.stereotype || '',
          ea_type: iel.ea_type || iel.metaclass || 'Class',
          tags: iel.tags || {}
        };
        elements.push(elObj);
        idToElement[elObj.id] = elObj;
        idToElement[elObj.name] = elObj;
      }
      var irConns = dbOrIr.connectors || [];
      for (var ic = 0; ic < irConns.length; ic++) {
        var iconn = irConns[ic];
        connectors.push({
          id: iconn.guid || iconn.ea_guid || ('conn_' + ic),
          ea_guid: iconn.ea_guid || iconn.guid,
          name: iconn.name || '',
          stereotype: iconn.stereotype || '',
          connector_type: iconn.ea_type || 'Association',
          source: iconn.source,
          target: iconn.target
        });
      }
    }

    var findings = [];

    function addFinding(severity, objectLabel, rule, check, message) {
      findings.push({
        severity: severity,
        object_label: objectLabel || '',
        rule: rule || '',
        check: check || '',
        message: message || ''
      });
    }

    // 1. Element-Pruefung
    for (var ei = 0; ei < elements.length; ei++) {
      var el = elements[ei];
      var elLabel = el.name || el.ea_guid || ('Element #' + el.id);

      if (el.stereotype) {
        var stTokens = el.stereotype.split(',').map(function (s) { return s.trim(); });
        for (var sti = 0; sti < stTokens.length; sti++) {
          var token = stTokens[sti];
          if (!token) continue;
          var rule = elemRules[token.toLowerCase()];
          if (!rule) {
            addFinding(
              'error',
              elLabel,
              '',
              'unknownElementStereotype',
              "Element '" + elLabel + "': Stereotyp '" + token + "' ist im Technologie-Regelwerk nicht definiert."
            );
          } else {
            // Metaklassen-Abgleich (Warnung)
            if (rule.metaclasses && rule.metaclasses.length && el.ea_type) {
              var mcMatch = false;
              for (var mci = 0; mci < rule.metaclasses.length; mci++) {
                if (rule.metaclasses[mci].toLowerCase() === el.ea_type.toLowerCase()) {
                  mcMatch = true;
                  break;
                }
              }
              if (!mcMatch) {
                addFinding(
                  'warning',
                  elLabel,
                  '',
                  'elementMetaclassMismatch',
                  "Element '" + elLabel + "': Metaklasse '" + el.ea_type + "' weicht von Regelwerk-Vorgabe ab."
                );
              }
            }

            // Tagged Value Definitionen pruefen
            var tagMap = {};
            if (rule.taggedValues) {
              for (var tvi = 0; tvi < rule.taggedValues.length; tvi++) {
                tagMap[rule.taggedValues[tvi].name.toLowerCase()] = rule.taggedValues[tvi];
              }
            }
            if (el.tags) {
              for (var tagName in el.tags) {
                var tagVal = String(el.tags[tagName] || '').trim();
                var tdef = tagMap[tagName.toLowerCase()];
                if (tdef && tdef.values && tdef.values.length && tagVal) {
                  var valMatch = false;
                  for (var vi = 0; vi < tdef.values.length; vi++) {
                    if (tdef.values[vi].toLowerCase() === tagVal.toLowerCase()) {
                      valMatch = true;
                      break;
                    }
                  }
                  if (!valMatch) {
                    addFinding(
                      'error',
                      elLabel,
                      'tag:enum',
                      'invalidTaggedValueEnum',
                      "Element '" + elLabel + "': Wert '" + tagVal + "' fuer Eigenschaft '" + tagName + "' ist nicht zulaessig."
                    );
                  }
                }
              }
            }
          }
        }
      }

      // NATO GUID Pruefung
      if (el.tags) {
        for (var tName in el.tags) {
          var lowName = tName.toLowerCase();
          if (lowName === 'originalguid' || lowName === 'standardelementguid') {
            var gVal = String(el.tags[tName] || '').trim();
            if (!gVal) {
              addFinding(
                'error',
                elLabel,
                'nato:guid',
                'emptyNatoGuid',
                "Element '" + elLabel + "': Tag '" + tName + "' darf nicht leer sein."
              );
            } else {
              var isGuid = (gVal.charAt(0) === '{' && gVal.charAt(gVal.length - 1) === '}' && gVal.length >= 36) ||
                           (gVal.length === 36 && gVal.indexOf('-') > 0) ||
                           gVal.indexOf('urn:') === 0 ||
                           gVal.indexOf('http') === 0 ||
                           gVal.indexOf('NC3-') === 0;
              if (!isGuid) {
                addFinding(
                  'warning',
                  elLabel,
                  'nato:guid',
                  'malformedNatoGuid',
                  "Element '" + elLabel + "': Tag '" + tName + "' hat auffaelliges Format '" + gVal + "'."
                );
              }
            }
          }
        }
      }
    }

    // 2. Connector-Pruefung
    for (var ci = 0; ci < connectors.length; ci++) {
      var c = connectors[ci];
      var srcEl = c.start_id ? idToElement[c.start_id] : idToElement[c.source];
      var tgtEl = c.end_id ? idToElement[c.end_id] : idToElement[c.target];
      var cLabel = (srcEl ? srcEl.name : '?') + ' -> ' + (tgtEl ? tgtEl.name : '?');

      if (c.stereotype) {
        var cst = c.stereotype.toLowerCase();
        var cRule = connRules[cst];
        if (cRule) {
          if (cRule.metaconstraints && cRule.metaconstraints.length) {
            for (var mci2 = 0; mci2 < cRule.metaconstraints.length; mci2++) {
              var mcDef = cRule.metaconstraints[mci2];
              var role = (mcDef.role || '').toLowerCase();
              var allowed = mcDef.constraints || [];
              var testEl = null;

              if (SOURCE_ROLES[role]) testEl = srcEl;
              else if (TARGET_ROLES[role]) testEl = tgtEl;

              if (testEl && allowed.length && allowed.indexOf('*') < 0) {
                var allowedMatch = false;
                var testSt = (testEl.stereotype || '').toLowerCase();
                var testType = (testEl.ea_type || '').toLowerCase();
                for (var ai = 0; ai < allowed.length; ai++) {
                  var aLow = allowed[ai].toLowerCase();
                  if (aLow === testSt || aLow === testType) {
                    allowedMatch = true;
                    break;
                  }
                }
                if (!allowedMatch) {
                  addFinding(
                    'error',
                    cLabel,
                    cRule.id || cRule.name,
                    'forbiddenConnectorEnd',
                    "Konnektor '" + cLabel + "' (" + c.stereotype + "): Endpunkt '" + testEl.name + "' (" + (testEl.stereotype || testEl.ea_type) + ") entspricht nicht den Metaconstraints fuer Rolle '" + mcDef.role + "'."
                  );
                }
              }
            }
          }
        }
      }
    }

    // Deterministische Sortierung nach Schweregrad und Objekt
    findings.sort(function (a, b) {
      if (a.severity !== b.severity) return a.severity === 'error' ? -1 : 1;
      if (a.object_label !== b.object_label) return a.object_label < b.object_label ? -1 : 1;
      return a.check < b.check ? -1 : (a.check > b.check ? 1 : 0);
    });

    return findings;
  }

  function summarize(findings) {
    var err = 0;
    var warn = 0;
    var list = findings || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].severity === 'error') err++;
      else if (list[i].severity === 'warning') warn++;
    }
    return {
      total: list.length,
      error: err,
      warning: warn
    };
  }

  /* ================= ArchiMate 3.2 Matrix-Pruefung (Archi EPL-2.0) ================= */

  var ARCHIMATE_CONCEPTS = ["ApplicationCollaboration","ApplicationComponent","ApplicationEvent","ApplicationFunction","ApplicationInteraction","ApplicationInterface","ApplicationProcess","ApplicationService","Artifact","Assessment","BusinessActor","BusinessCollaboration","BusinessEvent","BusinessFunction","BusinessInteraction","BusinessInterface","BusinessObject","BusinessProcess","BusinessRole","BusinessService","Capability","CommunicationNetwork","Constraint","Contract","CourseOfAction","DataObject","Deliverable","Device","DistributionNetwork","Driver","Equipment","Facility","Gap","Goal","Grouping","ImplementationEvent","Junction","Location","Material","Meaning","Node","Outcome","Path","Plateau","Principle","Product","Representation","Requirement","Resource","Stakeholder","SystemSoftware","TechnologyCollaboration","TechnologyEvent","TechnologyFunction","TechnologyInteraction","TechnologyInterface","TechnologyProcess","TechnologyService","Value","ValueStream","WorkPackage"];
  var ARCHIMATE_MATRIX_B64 = "dObMbUbUbUbObUbUBBBgZEZEbEbEbEbEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgf/BAf/ZEBBBgZEDgZEBADgZEBBDgDABgZEZEZEZEZEZEZEZEBgDABAZEfObUbUbUbObUbUBBBgZEZEbEbEbEbEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgf/BAf/ZEBBBgZEDgZEBADgZEBBDgDABgZEZEZEZEZEZEZEZEBgDABAZEZEdOZEZEZEZEZEBBBgZEZEbEZEZEZEBBZEZEZEBAZEDgBBBABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgBABAZEZEZEdOZOZEZObEBBBgZEZEZEbEbEZEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABAZEZEZEZOdOZEZObEBBBgZEZEZEbEbEZEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABAZEZEZEZEZEdOZEZUBBBgZEZEZEZEZEbEBBZEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgf/BAf/ZEBBBgZEDgZEBADgZEBBDgDABgZEZEZEZEZEZEZEZEBgDABAZEZEZEZOZOZEdObEBBBgZEZEZEbEbEZEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABAZEZEZEZEZEZEZEdOBBBgZEZEZEZEZEZEBBZEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABADADADADADADADADAHKBgBABADADADADADADABADADABADgDADADABABABABgBABABADgHqBAf/BABABgBADgBABADgBABADgDABgDABADADADADADADABgDABABABABABABABABABABABAFqBABABABABABABABABABABABABgBABABABABABABgBABABABgFqBAf/BABABgBABgBABABgBABABgBABgBABABABABABABABABgBABAZEZEZEZEZEZEZEZEBBBgdOZEZUZUZUZeBBZUZUbUDAZEDgBBDABBBAZEZEBgZEZEBADgf/BQf/ZEBBBgZEDgZEBADgZEBBDgDABwZEZEZEZEZEZEZEZEBgDABQZEZEZEZEZEZEZEZEBBBgZMdOZUZUZUZeBBZUZcbUDAZEDgBBDABBBAZEZEBgZEZEBADgf/BQf/ZEBBBgZEDgZEBADgZEBBDgDABwZEZEZEZEZEZEZEZEBgDABQZEZEZEZEZEZEZEZEBBBgZEZEdOZEZEZEBBZEZEZEBAZEDgBBBABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgBABAZEZEZEZEZEZEZEZEBBBgZEZEZEdOZOZEBBZOZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABAZEZEZEZEZEZEZEZEBBBgZEZEZEZOdOZEBBZOZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABAZEZEZEZEZEZEZEZEBBBgZEZEZEZEZEdOBBZEZEZUDAZEDgBBDABBBAZEZEBgZEZEBADgf/BAf/ZEBBBgZEDgZEBADgZEBBDgDABgZEZEZEZEZEZEZEZEBgDABABABABABABABABABABABgBABABABABABAFKBABABADABADgFKDABABABABABgBABABADgHqBAf/BABABgBADgBABADgBABADgDABgBABABABABABABABABgDABAZEZEZEZEZEZEZEZEBBBgZEZEZEZOZOZEBBdOZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABAZEZEZEZEZEZEZEZEBBBgZEZEZUZUZUZOBBZUdObUDAZEDgBBDABBBAZEZEBgZEZEBADgf/BQf/ZEBBBgZEDgZEBADgZEBBDgDABwZEZEZEZEZEZEZEZEBgDABQZEZEZEZEZEZEZEZEBBBgZEZEZEZEZEZEBBZEZEdODAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEZEBgDABABABABABABABABABABABgBABABABABABABABABABAdOBADgBAbEBABABABABgBABABADgfuBAf/BABABgBADgBABADgBABADgZEBgBABABABABABABABABgZEBAbEbEbEbEbEbEbEbEBRBgbEbEbEbEbEbEBBbEbEbEDAdODgBBDABBBAbMZEBgbEbEBADgf/BAf/ZEBBBgbEDgbEBADgZEBBDgDADgbcbEbUbUbUbcbUbUBgDABABABABABABABABABABABgBABABABABABABABABABABABAFqBABABABABABABgBABABADgHqBAf/BABABgBADgBABADgBABAFqBABgBABABABABABABABABgBABABABABABABABABABABABgBABABABABABAFKBABABADABADgFKDABABABABABgBABABADgHqBAf/BABABgBADgBABADgBABADgDABgBABABABABABABABABgDABABABABABABABABABABABgBABABABABABABABABABAZEBADgBAdOBABABABABgBABABADgfuBAf/BABABgBADgBABADgBABADgZEBgBABABABABABABABABgZEBABABABABABABABABABABgBABABABABABADABABABADABADgDADAFKBABABABgBABABADgHqBAf/BABABgBADgBABADgBABADgDABgBABABABABABABABABgDABADADADADADADADADADABgDADADADADADADADADADADADADgDADADAFKDADABgDADABADgHqBAf/DADABgDADgDADADgDADADgDADgDADADADADADADADABgDABAbEbEbEbEbEbEbEbEBRBgZEZEbEbEbEbEBBbEZEbEDAZEDgBBDABBBAdOZEBgZEZEBADgf/BAf/ZEBBBgZEDgZEBADgZEBBDgDABgbeZEbUbUbUbebUbUBgDABAbEbEbEbEbEbEbEbEBRBgbUbUbUbUbUbUBBbUbUbUDAZEDgBBDABBBAbcdOBgbcbcBADgf/BQf/ZEBRBgbcDgbEBADgZEBBDgDADwbcbEbUbUbUbcbUbUBgDABQBABABABABABABABABABgBABABABABABABABABABABABABgBABABABABABAFqBABABABgFqBAf/BABABgBABgBABABgBABABgBABgBABABABABABABABABgBABAbEbEbEbEbEbEbEbEBRBgZEZEbEbEbEbEBBbEZEbEDAZEDgBBDABBBAbOZEBgfOZEBADgf/BAf/ZEBRBgZEDgZEBADgZEBBDgDABgbeZEbUbUbUbebUbUBgDABAbEbEbEbEbEbEbEbEBRBgZUZUbUbUbUbUBBbUZUbUDAZEDgBBDABBBAbeZEBgbedeBADgf/BQf/ZEBRBgZeDgZEBADgZEBBDgDABwbeZEbUbUbUbebUbUBgDABQBABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABAFKBAFKBAf/BABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABgBABABABABABABABABABABABABgBABABABABABABgBABABAFqFqBAf/BABABgBABgBABABgBABABgBABgBABABABABABABABABgBABAfOfOfefefefOfefeHbFqfefefefefefeHLfefefefefOHqHLfOHLHLfefOFqfefeFKHqf/Nef/fOHbFqfeHqfOPOHqfOHLHqfOH6fefOfefefefefefeFqfeNeBABABABABABABABABABgBABABABABABABABABABABABABgBABABABBBABABgBABABABgNvNOf/BABABgBABgBAJEBgBABABgBABgBABABABABABABABABgBAJEbEbEbUbUbUbEbUbUDRBgbUbUbUbUbUbUDBbUbUbUbUbEDgDBbEDBDBbUbEBgbUbUBADgb1JUf/bEDRBgbUDgbELEDgbEDBDgbEDwbUbEbUbUbUbUbUbUBgbUJUbObObebebebObebeBbBqbebebebebebeBLbebebeDKZODqBLDKBLBKbeZOBqbebeBKDqf/Baf/dOBbBqbeDqbOBKDqZOBLDqDKD6bebObebebebebebeBqDKBaDADADADADADADADADABgBABADADADADADADABADADABADgDADADABADABABgDABABADgHqBAf/BAHKBgBADgBABADgBABADgDABgDABADADADADADADABgDABABABABABABABABABABABgBABABABABABABABABABABABABgBABABABABABABgBABABABgFqBAf/BABAFqBABgBABABgBABABgBABgBABABABABABABABABgBABAbEbEbEbEbEbEbEbEBRBgZUZUbUbUbUbUBBbUZUbUDAZEDgBBDABBBAbeZEBgbeZeBADgf/BQf/ZEBRBgdeDgZEBADgZEBBDgDABwbeZEbUbUbUbebUbUBgDABQBABABABABABABABABABgBABABABABABABABABABABABABgBABABABABABABgBABABADgHqBAf/BABABgBAFqBABABgBABABgBABgBABABABABABABABABgBABAbEbEbEbEbEbEbEbEBRBgZUZUbUbUbUbUBBbUZUbUDAZEDgBBDABBBAbcZEBgbcZcBADgf/BQf/ZEBRBgZcDgdOBADgZEBBDgDABwbcZMbUbUbUbcbUbUBgDABQDKDKDKDKDKDKDKDKDKBgDKDKDKDKDKDKDKDKDKDKDKDKDqDKDKDKBBDKDKBgDKDKBADqP/JEf/DKDKBgDKDqDKNODgDKDKDqDKDwDKDKDKDKDKDKDKDKBgDKJEBABABABABABABABABABgBABABABABABABABABABABABABgBABABABABABABgBABABADgHqBAf/BABABgBADgBABAFqBABABgBABgBABABABABABABABABgBABAbEbEbEbEbEbEbEbOBLBgZEZEbEbEbEbEBLbEZEbODAZEDgBLDABLBAbEZEBgbEZEBADgfvBAf/ZEBLBgZEDgZEBADgdOBLDgDABgbEZEbEbEbEbEbEbOBgDABABABABABABABABABABABgBABABABABABADABABABADABADgDADABABABABABgBABABADgHqBAf/BABABgBADgBABADgBAFKDgDABgBABABABABABABABABgDABABABABABABABABABABABgBABABABABABABABABABABABAFqBABABABABABABgBABABADgHqBAf/BABABgBADgBABADgBABAFqBABgBABABABABABABABABgBABABABABABABABABABABABgBABABABABABABABABABAZUBADgBAbEBABABABABgBABABADgf+BAf/BABABgBADgBABADgBABADgdOBgBABABABABABABABABgZUBABABABABABABABABABABgBABABABABABABABABABABABABgBABABABABABABgBABABABgFqBAf/BABABgBABgBABABgBABABgBAFqBABABABABABABABABgBABAbEbEbEbEbEbEbEbEBRBgZEZEbEbEbEbEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgf/BAf/ZEBBBgZEDgZEBADgZEBBDgDABgfeZEbUbUbUbebUbUBgDABAbEbEbEbEbEbEbEbEBRBgZUZUbUbUbUbUBBbUZUbUDAZEDgBBDABBBAbcZEBgbcZcBADgf/BQf/ZEBRBgZcDgZEBADgZEBBDgDABwbcdObUbUbUbebUbUBgDABQZEZEbEZEZEZEZEZEBBBgZEZEbEZEZEZEBBZEZEZEBAZEDgBBBABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEdOZEZEZEZEZEBgBABAZEZEZEbEbEZEbEbEBBBgZEZEZEbEbEZEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEdOZOZEZObEBgDABAZEZEZEbEbEZEbEbEBBBgZEZEZEbEbEZEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZOdOZEZObEBgDABAZEZEZEZEZEbEZEbEBBBgZEZEZEZEZEbEBBZEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgf/BAf/ZEBBBgZEDgZEBADgZEBBDgDABgZEZEZEZEZEdOZEZUBgDABAZEZEZEbEbEZEbEbEBBBgZEZEZEbEbEZEBBbEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZOZOZEdObEBgDABAZEZEZEZEZEZEZEbEBBBgZEZEZEZEZEZEBBZEZEbEDAZEDgBBDABBBAZEZEBgZEZEBADgfvBAf/ZEBBBgZEDgZEBADgZEBBDgBABgZEZEZEZEZEZEZEdOBgDABABABABABABABABABABABgBABABABABABABABABABABABABgBABABABABABABgBABABABgFqBAf/BABABgBABgBABABgBABABgBABgBABABABABABABABAFqBABABABABABABABABABABABgBABABABABABABABABABAZEBADgBAbEBABABABABgBABABADgfuBAf/BABABgBADgBABADgBABADgZEBgBABABABABABABABABgdOBADADADADADADADADADABgDADADADADADADADADADADADADgDADADADBDADABgDADABADgPvJEf/DADABgDADgDALEDgDADADgDADgDADADADADADADADABgDANO";
  var ARCHIMATE_REL_BITS = 'acfginorstv';
  var ARCHIMATE_REL_NAMES = [
    'Access', 'Composition', 'Flow', 'Aggregation', 'Assignment',
    'Influence', 'Association', 'Realization', 'Specialization', 'Triggering', 'Serving'
  ];
  var ARCHIMATE_B64_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

  var ARCHIMATE_CONCEPT_MAP = (function () {
    var m = {};
    for (var i = 0; i < ARCHIMATE_CONCEPTS.length; i++) {
      m[ARCHIMATE_CONCEPTS[i].toLowerCase()] = { name: ARCHIMATE_CONCEPTS[i], idx: i };
    }
    m['andjunction'] = { name: 'Junction', idx: m['junction'].idx };
    m['orjunction'] = { name: 'Junction', idx: m['junction'].idx };
    return m;
  })();

  var ARCHIMATE_REL_MAP = (function () {
    var m = {};
    for (var i = 0; i < ARCHIMATE_REL_NAMES.length; i++) {
      var n = ARCHIMATE_REL_NAMES[i].toLowerCase();
      m[n] = { name: ARCHIMATE_REL_NAMES[i], bit: i };
      m[n + 'relationship'] = { name: ARCHIMATE_REL_NAMES[i], bit: i };
    }
    m['realisation'] = m['realization'];
    m['realisationrelationship'] = m['realization'];
    m['specialisation'] = m['specialization'];
    m['specialisationrelationship'] = m['specialization'];
    m['usedby'] = m['serving'];
    m['usedbyrelationship'] = m['serving'];
    return m;
  })();

  function archimateCellMask(sIdx, tIdx) {
    var n = ARCHIMATE_CONCEPTS.length;
    var pos = (sIdx * n + tIdx) * 2;
    var hi = ARCHIMATE_B64_CHARS.indexOf(ARCHIMATE_MATRIX_B64.charAt(pos));
    var lo = ARCHIMATE_B64_CHARS.indexOf(ARCHIMATE_MATRIX_B64.charAt(pos + 1));
    if (hi < 0 || lo < 0) return 0;
    return (hi << 6) | lo;
  }

  function archimateAllowedNames(mask) {
    var out = [];
    for (var i = 0; i < ARCHIMATE_REL_NAMES.length; i++) {
      if (mask & (1 << i)) out.push(ARCHIMATE_REL_NAMES[i]);
    }
    return out;
  }

  function extractModelItems(dbOrIr) {
    var packages = [];
    var elements = [];
    var connectors = [];
    var idToElement = {};
    var pkgById = {};

    if (dbOrIr && typeof dbOrIr.rows === 'function') {
      var tPkg = dbOrIr.rows('t_package') || [];
      var rawPkg = {};
      for (var pi = 0; pi < tPkg.length; pi++) {
        rawPkg[tPkg[pi].Package_ID] = tPkg[pi];
      }
      function buildPkgPath(pid) {
        var cur = rawPkg[pid], parts = [], guard = 0;
        while (cur && guard++ < 40) {
          if (cur.x_path) { parts.unshift(cur.x_path); break; }
          if (cur.Name) parts.unshift(cur.Name);
          cur = cur.Parent_ID ? rawPkg[cur.Parent_ID] : null;
        }
        return parts.join('/');
      }
      for (var pj = 0; pj < tPkg.length; pj++) {
        var pk = tPkg[pj];
        var pPath = buildPkgPath(pk.Package_ID);
        pkgById[pk.Package_ID] = pPath;
        packages.push({ id: pk.Package_ID, path: pPath, name: pk.Name || '', stereotype: pk.Stereotype || '' });
      }
      var tProp = dbOrIr.rows('t_objectproperties') || [];
      var tagsByObj = {};
      for (var p = 0; p < tProp.length; p++) {
        var tp = tProp[p];
        if (!tagsByObj[tp.Object_ID]) tagsByObj[tp.Object_ID] = {};
        if (tp.Property) tagsByObj[tp.Object_ID][tp.Property] = String(tp.Value == null ? '' : tp.Value);
      }
      var tObj = dbOrIr.rows('t_object') || [];
      for (var e = 0; e < tObj.length; e++) {
        var ob = tObj[e];
        if (String(ob.Object_Type || '') === 'Package') continue;
        var elItem = {
          id: ob.Object_ID,
          ea_guid: String(ob.ea_guid || ''),
          package: pkgById[ob.Package_ID] || '',
          name: String(ob.Name || ''),
          stereotype: String(ob.Stereotype || ''),
          ea_type: String(ob.Object_Type || 'Class'),
          notes: String(ob.Note != null ? ob.Note : (ob.Notes || '')),
          status: String(ob.Status || ''),
          alias: String(ob.Alias || ''),
          tags: tagsByObj[ob.Object_ID] || {}
        };
        elements.push(elItem);
        idToElement[ob.Object_ID] = elItem;
      }
      var tConn = dbOrIr.rows('t_connector') || [];
      for (var cn = 0; cn < tConn.length; cn++) {
        var tc = tConn[cn];
        connectors.push({
          id: tc.Connector_ID,
          ea_guid: String(tc.ea_guid || ''),
          name: String(tc.Name || ''),
          stereotype: String(tc.Stereotype || ''),
          connector_type: String(tc.Connector_Type || tc.Type || ''),
          start_id: tc.Start_Object_ID,
          end_id: tc.End_Object_ID
        });
      }
    } else if (dbOrIr && typeof dbOrIr === 'object') {
      var irPkgs = dbOrIr.packages || [];
      for (var ip = 0; ip < irPkgs.length; ip++) {
        packages.push({ id: ip + 1, path: String(irPkgs[ip].path || ''), name: String(irPkgs[ip].name || irPkgs[ip].path || ''), stereotype: String(irPkgs[ip].stereotype || '') });
      }
      var irElements = dbOrIr.elements || [];
      for (var ie = 0; ie < irElements.length; ie++) {
        var iel = irElements[ie];
        var elObj = {
          id: iel.ref || iel.guid || iel.ea_guid || ('elem_' + ie),
          ea_guid: String(iel.ea_guid || iel.guid || ''),
          package: String(iel.package || ''),
          name: String(iel.name || ''),
          stereotype: String(iel.stereotype || ''),
          ea_type: String(iel.ea_type || iel.metaclass || 'Class'),
          notes: String(iel.notes || ''),
          status: String(iel.status || ''),
          alias: String(iel.alias || ''),
          tags: iel.tags || {}
        };
        elements.push(elObj);
        idToElement[elObj.id] = elObj;
        if (elObj.name) idToElement[elObj.name] = elObj;
        if (elObj.package && elObj.name) idToElement[elObj.package + '::' + elObj.name] = elObj;
      }
      var irConns = dbOrIr.connectors || [];
      for (var ic = 0; ic < irConns.length; ic++) {
        var iconn = irConns[ic];
        connectors.push({
          id: iconn.guid || iconn.ea_guid || ('conn_' + ic),
          ea_guid: String(iconn.ea_guid || iconn.guid || ''),
          name: String(iconn.name || ''),
          stereotype: String(iconn.stereotype || ''),
          connector_type: String(iconn.ea_type || 'Association'),
          source: iconn.source,
          target: iconn.target
        });
      }
    }
    return { packages: packages, elements: elements, connectors: connectors, idToElement: idToElement };
  }

  function validateArchimate(dbOrIr) {
    var m = extractModelItems(dbOrIr);
    var findings = [];
    function add(sev, lbl, rule, chk, msg) {
      findings.push({ severity: sev, object_label: lbl || '', rule: rule || '', check: chk || '', message: msg || '' });
    }
    var elConcept = {};
    for (var i = 0; i < m.elements.length; i++) {
      var el = m.elements[i];
      var lbl = el.name || el.ea_guid || ('Element #' + el.id);
      if (!String(el.name || '').trim()) {
        add('warning', lbl, 'archimate:name', 'unnamedElement', "Element '" + lbl + "' hat keinen Namen.");
      }
      var rawConcept = String(el.stereotype || el.ea_type || '').split(':').pop().trim();
      var cEntry = ARCHIMATE_CONCEPT_MAP[rawConcept.toLowerCase()];
      if (!cEntry) {
        add('error', lbl, 'archimate:concept', 'unknownArchimateConcept', "Element '" + lbl + "': unbekanntes ArchiMate-3.2-Konzept '" + rawConcept + "'.");
      } else {
        elConcept[el.id] = cEntry;
      }
    }
    for (var j = 0; j < m.connectors.length; j++) {
      var c = m.connectors[j];
      var src = c.start_id != null ? m.idToElement[c.start_id] : m.idToElement[c.source];
      var tgt = c.end_id != null ? m.idToElement[c.end_id] : m.idToElement[c.target];
      var cLbl = (src ? (src.name || src.id) : String(c.source || c.start_id || '?')) + ' -> ' + (tgt ? (tgt.name || tgt.id) : String(c.target || c.end_id || '?'));
      if (!src || !tgt) {
        add('error', cLbl, 'archimate:ref', 'unresolvedConnectorEndpoint', "Beziehung '" + cLbl + "': Quell- oder Ziel-Element konnte nicht aufgeloest werden.");
        continue;
      }
      var rawRel = String(c.stereotype || c.connector_type || 'Association').split(':').pop().trim();
      var rEntry = ARCHIMATE_REL_MAP[rawRel.toLowerCase()];
      if (!rEntry) {
        add('error', cLbl, 'archimate:rel', 'unknownArchimateRelationship', "Beziehung '" + cLbl + "': unbekannte ArchiMate-3.2-Beziehungsart '" + rawRel + "'.");
        continue;
      }
      var sc = elConcept[src.id], tc = elConcept[tgt.id];
      if (!sc || !tc) continue;
      var mask = archimateCellMask(sc.idx, tc.idx);
      if (!(mask & (1 << rEntry.bit))) {
        var allowed = archimateAllowedNames(mask);
        add(
          'error',
          cLbl,
          'archimate:matrix',
          'archimateMatrixViolation',
          "Beziehung '" + cLbl + "' (" + rEntry.name + "): laut ArchiMate-3.2-Matrix zwischen '" + sc.name + "' und '" + tc.name + "' nicht erlaubt" +
          (allowed.length ? ' (erlaubt: ' + allowed.join(', ') + ').' : ' (keine direkte Beziehung erlaubt).')
        );
      }
    }
    findings.sort(function (a, b) {
      if (a.severity !== b.severity) return a.severity === 'error' ? -1 : 1;
      return a.object_label < b.object_label ? -1 : (a.object_label > b.object_label ? 1 : 0);
    });
    return findings;
  }

  /* ================= Deterministische Regel-Reparatur (ohne KI) ================= */

  function proposeRepairs(dbOrIr, mdgXmlOrRules) {
    var rules = typeof mdgXmlOrRules === 'string' ? parseMdg(mdgXmlOrRules) : (mdgXmlOrRules || {});
    var m = extractModelItems(dbOrIr);
    var elemRules = {}, elList = rules.elementStereotypes || [];
    for (var i = 0; i < elList.length; i++) {
      if (elList[i] && elList[i].name) elemRules[elList[i].name.toLowerCase()] = elList[i];
    }
    var connRules = {}, crList = rules.connectorRules || [];
    for (var j = 0; j < crList.length; j++) {
      if (crList[j] && crList[j].name) connRules[crList[j].name.toLowerCase()] = crList[j];
    }

    function connAllows(cRule, srcEl, tgtEl) {
      var mcs = cRule.metaconstraints || [];
      for (var k = 0; k < mcs.length; k++) {
        var mc = mcs[k], role = String(mc.role || '').toLowerCase(), allowed = mc.constraints || [];
        var testEl = SOURCE_ROLES[role] ? srcEl : (TARGET_ROLES[role] ? tgtEl : null);
        if (testEl && allowed.length && allowed.indexOf('*') < 0) {
          var stLow = String(testEl.stereotype || '').toLowerCase();
          var tyLow = String(testEl.ea_type || '').toLowerCase();
          var hit = false;
          for (var a = 0; a < allowed.length; a++) {
            var al = String(allowed[a] || '').toLowerCase();
            if (al === stLow || al === tyLow) { hit = true; break; }
          }
          if (!hit) return false;
        }
      }
      return true;
    }

    var changes = [], ops = [];
    for (var ei = 0; ei < m.elements.length; ei++) {
      var el = m.elements[ei];
      if (!el.stereotype) continue;
      var stLow = el.stereotype.trim().toLowerCase();
      var er = elemRules[stLow];
      if (!er) {
        changes.push({
          kind: 'stereotype_removed',
          target: (el.package ? el.package + '::' : '') + el.name,
          before: el.stereotype,
          after: '',
          reason: 'unknownElementStereotype'
        });
        ops.push({ op: 'set_stereotype', oid: el.id, package: el.package, name: el.name, value: '' });
      } else if (er.name !== el.stereotype.trim()) {
        changes.push({
          kind: 'stereotype_changed',
          target: (el.package ? el.package + '::' : '') + el.name,
          before: el.stereotype,
          after: er.name,
          reason: 'stereotypeCaseMismatch'
        });
        ops.push({ op: 'set_stereotype', oid: el.id, package: el.package, name: el.name, value: er.name });
      }
    }

    for (var ci = 0; ci < m.connectors.length; ci++) {
      var c = m.connectors[ci];
      if (!c.stereotype) continue;
      var src = c.start_id != null ? m.idToElement[c.start_id] : m.idToElement[c.source];
      var tgt = c.end_id != null ? m.idToElement[c.end_id] : m.idToElement[c.target];
      if (!src || !tgt) continue;
      var cLbl = (src.name || src.id) + ' -> ' + (tgt.name || tgt.id);
      var cRule = connRules[c.stereotype.toLowerCase()];
      var validNow = cRule ? connAllows(cRule, src, tgt) : false;
      if (validNow) continue;

      // Suche deterministisch nach passendem Kantenstereotyp fuer (src, tgt)
      var candidates = [];
      for (var rk in connRules) {
        if (!Object.prototype.hasOwnProperty.call(connRules, rk)) continue;
        var cand = connRules[rk];
        if (connAllows(cand, src, tgt)) candidates.push(cand);
      }
      candidates.sort(function (a, b) { return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0); });

      if (candidates.length === 1) {
        changes.push({
          kind: 'connector_retyped',
          target: cLbl,
          before: c.stereotype,
          after: candidates[0].name,
          reason: cRule ? 'forbiddenConnectorEnd' : 'unknownConnectorStereotype'
        });
        ops.push({ op: 'set_connector_stereotype', cid: c.id, source: src.name, target: tgt.name, oldStereotype: c.stereotype, value: candidates[0].name });
      } else if (!cRule) {
        changes.push({
          kind: 'connector_removed',
          target: cLbl,
          before: c.stereotype,
          after: '(entfernt)',
          reason: 'unknownConnectorStereotype'
        });
        ops.push({ op: 'delete_connector', cid: c.id, source: src.name, target: tgt.name, stereotype: c.stereotype });
      }
    }
    return { changes: changes, ops: ops };
  }

  /* ================= Modell-Diff (Vorher/Nachher & Datei-Vergleich) ================= */

  function diffModels(altDbOrIr, neuDbOrIr) {
    var a = extractModelItems(altDbOrIr);
    var b = extractModelItems(neuDbOrIr);

    function elGuid(e) {
      if (e.ea_guid) return e.ea_guid.toLowerCase();
      var t = e.tags || {};
      var og = t.OriginalGUID || t.originalguid || t.StandardElementGUID || '';
      return String(og).trim().toLowerCase();
    }

    var pAlt = {}, pNeu = {}, pAdded = [], pRemoved = [];
    for (var i = 0; i < a.packages.length; i++) if (a.packages[i].path) pAlt[a.packages[i].path] = a.packages[i];
    for (var j = 0; j < b.packages.length; j++) if (b.packages[j].path) pNeu[b.packages[j].path] = b.packages[j];
    for (var pk in pNeu) if (Object.prototype.hasOwnProperty.call(pNeu, pk) && !pAlt[pk]) pAdded.push(pk);
    for (var pk2 in pAlt) if (Object.prototype.hasOwnProperty.call(pAlt, pk2) && !pNeu[pk2]) pRemoved.push(pk2);
    pAdded.sort(); pRemoved.sort();

    var matchA2B = {}, usedB = {}, bByGuid = {}, bByPkgName = {};
    for (var bi = 0; bi < b.elements.length; bi++) {
      var bg = elGuid(b.elements[bi]);
      if (bg) { if (!bByGuid[bg]) bByGuid[bg] = []; bByGuid[bg].push(bi); }
    }
    for (var ai = 0; ai < a.elements.length; ai++) {
      var ag = elGuid(a.elements[ai]);
      if (ag && bByGuid[ag]) {
        for (var x = 0; x < bByGuid[ag].length; x++) {
          var candIdx = bByGuid[ag][x];
          if (!usedB[candIdx]) { matchA2B[ai] = candIdx; usedB[candIdx] = true; break; }
        }
      }
    }
    for (var bi2 = 0; bi2 < b.elements.length; bi2++) {
      if (usedB[bi2]) continue;
      var kpn = (b.elements[bi2].package + '::' + b.elements[bi2].name).toLowerCase();
      if (!bByPkgName[kpn]) bByPkgName[kpn] = [];
      bByPkgName[kpn].push(bi2);
    }
    for (var ai2 = 0; ai2 < a.elements.length; ai2++) {
      if (matchA2B[ai2] !== undefined) continue;
      var kpnA = (a.elements[ai2].package + '::' + a.elements[ai2].name).toLowerCase();
      var list = bByPkgName[kpnA] || [];
      for (var y = 0; y < list.length; y++) {
        if (!usedB[list[y]]) { matchA2B[ai2] = list[y]; usedB[list[y]] = true; break; }
      }
    }

    var elAdded = [], elRemoved = [], elChanged = [];
    var canonA = {}, canonB = {}, canonLbl = {};
    for (var ai3 = 0; ai3 < a.elements.length; ai3++) {
      var ea = a.elements[ai3];
      if (matchA2B[ai3] === undefined) {
        elRemoved.push({ package: ea.package, name: ea.name, stereotype: ea.stereotype });
        canonA[ea.id] = 'A#' + ai3;
        canonLbl['A#' + ai3] = (ea.package ? ea.package + '::' : '') + ea.name;
      } else {
        var bj = matchA2B[ai3], eb = b.elements[bj];
        var cid = 'M#' + ai3;
        canonA[ea.id] = cid; canonB[eb.id] = cid;
        canonLbl[cid] = (eb.package ? eb.package + '::' : '') + eb.name;
        var diffs = [];
        if (ea.name !== eb.name) diffs.push('Name: „' + ea.name + '“ -> „' + eb.name + '“');
        if (ea.package !== eb.package) diffs.push('Paket: „' + ea.package + '“ -> „' + eb.package + '“');
        if (ea.stereotype !== eb.stereotype) diffs.push('Stereotyp: «' + ea.stereotype + '» -> «' + eb.stereotype + '»');
        if (String(ea.notes || '').trim() !== String(eb.notes || '').trim()) diffs.push('Notiz geändert');
        if (diffs.length) {
          elChanged.push({ package: eb.package || ea.package, name: eb.name || ea.name, stereotype: eb.stereotype, diffs: diffs });
        }
      }
    }
    for (var bi3 = 0; bi3 < b.elements.length; bi3++) {
      if (!usedB[bi3]) {
        var en = b.elements[bi3];
        elAdded.push({ package: en.package, name: en.name, stereotype: en.stereotype });
        canonB[en.id] = 'B#' + bi3;
        canonLbl['B#' + bi3] = (en.package ? en.package + '::' : '') + en.name;
      }
    }

    function connMap(items, canonMap) {
      var out = {};
      for (var cIdx = 0; cIdx < items.connectors.length; cIdx++) {
        var c = items.connectors[cIdx];
        var sEl = c.start_id != null ? items.idToElement[c.start_id] : items.idToElement[c.source];
        var tEl = c.end_id != null ? items.idToElement[c.end_id] : items.idToElement[c.target];
        var sKey = sEl ? canonMap[sEl.id] : String(c.source || c.start_id || '');
        var tKey = tEl ? canonMap[tEl.id] : String(c.target || c.end_id || '');
        var st = String(c.stereotype || c.connector_type || '');
        var key = sKey + '->' + tKey + '|' + st.toLowerCase();
        out[key] = { source: canonLbl[sKey] || sKey, target: canonLbl[tKey] || tKey, stereotype: st };
      }
      return out;
    }

    var cmA = connMap(a, canonA), cmB = connMap(b, canonB);
    var cAdded = [], cRemoved = [];
    for (var ck in cmB) if (Object.prototype.hasOwnProperty.call(cmB, ck) && !cmA[ck]) cAdded.push(cmB[ck]);
    for (var ck2 in cmA) if (Object.prototype.hasOwnProperty.call(cmA, ck2) && !cmB[ck2]) cRemoved.push(cmA[ck2]);

    var summary = {
      packages_added: pAdded.length,
      packages_removed: pRemoved.length,
      elements_added: elAdded.length,
      elements_removed: elRemoved.length,
      elements_changed: elChanged.length,
      connectors_added: cAdded.length,
      connectors_removed: cRemoved.length
    };
    var identical = !pAdded.length && !pRemoved.length && !elAdded.length && !elRemoved.length && !elChanged.length && !cAdded.length && !cRemoved.length;
    return {
      identical: identical,
      summary: summary,
      packages: { added: pAdded, removed: pRemoved },
      elements: { added: elAdded, removed: elRemoved, changed: elChanged },
      connectors: { added: cAdded, removed: cRemoved }
    };
  }

  /* ================= Textabdeckungs-Pruefung (ohne KI) ================= */

  function evaluateCoverage(dbOrIr, textOrQuellen) {
    var m = extractModelItems(dbOrIr);
    var modelRefs = {};
    function recordRef(raw, label) {
      if (!raw) return;
      var parts = String(raw).trim().split(/[,;\s]+/);
      for (var i = 0; i < parts.length; i++) {
        var r = parts[i].replace(/^\[|\]$/g, '').toUpperCase();
        if (/^D\d+-S\d+$/.test(r)) {
          if (!modelRefs[r]) modelRefs[r] = [];
          if (modelRefs[r].indexOf(label) < 0) modelRefs[r].push(label);
        }
      }
    }
    for (var ei = 0; ei < m.elements.length; ei++) {
      var el = m.elements[ei], t = el.tags || {};
      recordRef(t.source_ref || t.herkunft || t.quellbeleg, el.name);
    }

    var segments = [], quellen = {};
    if (typeof textOrQuellen === 'string' && textOrQuellen.trim()) {
      var paras = textOrQuellen.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split(/\n\s*\n+/);
      var sNo = 0, chap = '(Einleitung)';
      for (var pi = 0; pi < paras.length; pi++) {
        var p = paras[pi].trim();
        if (!p) continue;
        sNo++;
        var first = p.split('\n')[0].trim();
        var hm = first.match(/^#{1,6}\s+(.+)$/);
        var isH = !!(hm && p.indexOf('\n') < 0);
        if (hm) chap = hm[1].trim();
        var ref = 'D1-S' + sNo;
        quellen[ref] = p;
        segments.push({ ref: ref, chapter: chap, isHeading: isH, text: p });
      }
    } else if (textOrQuellen && typeof textOrQuellen === 'object') {
      var keys = Object.keys(textOrQuellen).sort(function (x, y) {
        var mx = x.match(/^D(\d+)-S(\d+)$/i), my = y.match(/^D(\d+)-S(\d+)$/i);
        if (mx && my) return (Number(mx[1]) - Number(my[1])) || (Number(mx[2]) - Number(my[2]));
        return x < y ? -1 : 1;
      });
      var chap2 = '(Quellbelege)';
      for (var ki = 0; ki < keys.length; ki++) {
        var rk = keys[ki].toUpperCase(), txt = String(textOrQuellen[keys[ki]] || '').trim();
        if (!txt) continue;
        var hm2 = txt.split('\n')[0].trim().match(/^#{1,6}\s+(.+)$/);
        var isH2 = !!(hm2 && txt.indexOf('\n') < 0);
        if (hm2) chap2 = hm2[1].trim();
        quellen[rk] = txt;
        segments.push({ ref: rk, chapter: chap2, isHeading: isH2, text: txt });
      }
    }
    if (!segments.length) return null;

    var content = segments.filter(function (s) { return !s.isHeading; });
    var basis = content.length ? content : segments;
    var covered = 0, uncovered = [];
    for (var si = 0; si < basis.length; si++) {
      var seg = basis[si];
      if (modelRefs[seg.ref]) covered++;
      else uncovered.push({ ref: seg.ref, chapter: seg.chapter, preview: seg.text.length > 160 ? seg.text.slice(0, 160) + '…' : seg.text });
    }
    var pct = Math.round((1000 * covered) / Math.max(1, basis.length)) / 10;
    return {
      total_segments: segments.length,
      content_segments: basis.length,
      covered_segments: covered,
      uncovered_segments: uncovered.length,
      coverage_pct: pct,
      uncovered: uncovered,
      quellen: quellen
    };
  }

  /* ================= Export ================= */

  var api = {
    parseMdg: parseMdg,
    validateModel: validateModel,
    validateArchimate: validateArchimate,
    proposeRepairs: proposeRepairs,
    diffModels: diffModels,
    evaluateCoverage: evaluateCoverage,
    summarize: summarize
  };

  global.EAMMDG = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : this);
