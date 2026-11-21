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

  /* ================= Export ================= */

  var api = {
    parseMdg: parseMdg,
    validateModel: validateModel,
    summarize: summarize
  };

  global.EAMMDG = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : this);
