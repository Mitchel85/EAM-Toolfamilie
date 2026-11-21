/* QEA-Reader: nativer SQLite-Parser fuer .qea-Dateien.
   Vanilla-JS, kein WASM/CDN. Liest Tabellen-B-Trees inkl. Overflow-Seiten.
   Danach Abbildung ERB -> gemeinsames Datenmodell (Projekte, Meilensteine, Orgs, Kanten). */
'use strict';

/* ================= SQLite-Parser ================= */
function qeaOpen(buffer) {
  const u8 = new Uint8Array(buffer);
  const dv = new DataView(buffer);
  let magic = '';
  for (let i = 0; i < 16; i++) magic += String.fromCharCode(u8[i]);
  if (magic.indexOf('SQLite format 3') !== 0) throw new Error('Kein SQLite-Format erkannt. Unterstützt werden .qea/.qeax/.eapx im SQLite-Format (ab Werkzeugversion 13). Ältere .eap-Dateien (MS Access/Jet) oder anders formatierte Dateien bitte in Enterprise Architect als SQLite-Projekt exportieren.');
  const psRaw = dv.getUint16(16, false);
  const pageSize = psRaw === 1 ? 65536 : psRaw;
  const reserved = u8[20];
  const usable = pageSize - reserved;
  const enc = dv.getUint32(56, false); // 1=utf8 2=utf16le 3=utf16be

  function varint(off) {
    let v = 0, i = 0, b;
    for (; i < 8; i++) {
      b = u8[off + i];
      v = v * 128 + (b & 0x7f);
      if (!(b & 0x80)) return [v, off + i + 1];
    }
    b = u8[off + 8];
    return [v * 256 + b, off + 9];
  }

  function decodeText(bytes) {
    if (enc === 2) return new TextDecoder('utf-16le').decode(bytes);
    if (enc === 3) return new TextDecoder('utf-16be').decode(bytes);
    return new TextDecoder('utf-8').decode(bytes);
  }

  function readPayload(cellOff) {
    const [pLen, o1] = varint(cellOff);
    const [rowid, o2] = varint(o1);
    let local = pLen;
    let overflowPage = 0;
    if (pLen > maxLocal) {
      const minLocal = Math.floor((usable - 12) * 32 / 255) - 23;
      local = minLocal + ((pLen - minLocal) % (usable - 4));
      if (local > maxLocal) local = minLocal;
      overflowPage = dv.getUint32(o2 + local, false);
    }
    const out = new Uint8Array(pLen);
    out.set(u8.subarray(o2, o2 + local), 0);
    let filled = local;
    let pg = overflowPage;
    while (pg !== 0 && filled < pLen) {
      const base = (pg - 1) * pageSize;
      const next = dv.getUint32(base, false);
      const take = Math.min(usable - 4, pLen - filled);
      out.set(u8.subarray(base + 4, base + 4 + take), filled);
      filled += take;
      pg = next;
    }
    return [out, rowid];
  }

  function decodeRecord(bytes) {
    const dvb = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const [hdrSize, p0] = varintBuf(bytes, 0);
    const serials = [];
    let q = p0;
    while (q < hdrSize) {
      const [s, nq] = varintBuf(bytes, q);
      serials.push(s);
      q = nq;
    }
    const vals = [];
    let r = q;
    for (let i = 0; i < serials.length; i++) {
      const s = serials[i];
      if (s === 0) { vals.push(null); }
      else if (s >= 1 && s <= 6) {
        const sizes = [0, 1, 2, 3, 4, 6, 8];
        const n = sizes[s];
        let v = 0;
        for (let k = 0; k < n; k++) v = v * 256 + bytes[r + k];
        if (bytes[r] & 0x80) v -= Math.pow(2, n * 8); // signed BE
        vals.push(v);
        r += n;
      }
      else if (s === 7) { vals.push(dvb.getFloat64(r, false)); r += 8; }
      else if (s === 8) { vals.push(0); }
      else if (s === 9) { vals.push(1); }
      else if (s >= 12) {
        const even = (s % 2) === 0;
        const n = even ? (s - 12) / 2 : (s - 13) / 2;
        const raw = bytes.subarray(r, r + n);
        vals.push(even ? raw : decodeText(raw));
        r += n;
      }
    }
    return vals;
  }

  function varintBuf(bytes, off) {
    let v = 0, i = 0, b;
    for (; i < 8; i++) {
      b = bytes[off + i];
      v = v * 128 + (b & 0x7f);
      if (!(b & 0x80)) return [v, off + i + 1];
    }
    b = bytes[off + 8];
    return [v * 256 + b, off + 9];
  }

  const maxLocal = usable - 35;

  function walkTable(rootPage, sink) {
    const stack = [rootPage];
    while (stack.length) {
      const pg = stack.pop();
      const base = (pg - 1) * pageSize;
      const hdr = pg === 1 ? base + 100 : base;
      const type = u8[hdr];
      const cellCount = dv.getUint16(hdr + 3, false);
      const ptrStart = (type === 2 || type === 5) ? hdr + 12 : hdr + 8;
      if (type === 5 || type === 2) {
        const rightmost = dv.getUint32(hdr + 8, false);
        for (let i = 0; i < cellCount; i++) {
          const cell = dv.getUint16(ptrStart + i * 2, false);
          stack.push(dv.getUint32(base + cell, false));
        }
        if (rightmost) stack.push(rightmost);
      } else if (type === 13 || type === 10) {
        for (let i = 0; i < cellCount; i++) {
          const cell = dv.getUint16(ptrStart + i * 2, false);
          const [payload, rowid] = readPayload(base + cell);
          sink(decodeRecord(payload), rowid);
        }
      } else {
        throw new Error('Unbekannter B-Tree-Seitentyp ' + type + ' (Seite ' + pg + ')');
      }
    }
  }

  /* sqlite_master */
  const master = [];
  walkTable(1, function (rec) { master.push(rec); });

  const tables = {};
  master.forEach(function (rec) {
    const [type, name, tbl, root, sql] = rec;
    if (type !== 'table') return;
    const pc = parseCols(sql);
    tables[name] = { root: root, sql: sql, cols: pc.cols, pk: pc.pk };
  });

  function parseCols(sql) {
    const cols = [];
    let pk = -1;
    if (!sql) return { cols: cols, pk: pk };
    sql = String(sql).replace(/--[\s\S]*?(?:\r|$)/g, ''); // EA-DDL: Zeilenkommentare hinter jedem Feld
    const start = sql.indexOf('(');
    if (start < 0) return { cols: cols, pk: pk };
    let depth = 0, cur = '', inQ = false;
    for (let i = start + 1; i < sql.length; i++) {
      const ch = sql[i];
      if (ch === '"') { inQ = !inQ; cur += ch; continue; }
      if (inQ) { cur += ch; continue; }
      if (ch === '(') { depth++; cur += ch; continue; }
      if (ch === ')') {
        if (depth === 0) { if (cur.trim()) { if (/PRIMARY\s+KEY/i.test(cur) && pk < 0) pk = cols.length; cols.push(colName(cur)); } break; }
        depth--; cur += ch; continue;
      }
      if (ch === ',' && depth === 0) {
        if (/PRIMARY\s+KEY/i.test(cur) && pk < 0) pk = cols.length;
        cols.push(colName(cur)); cur = ''; continue;
      }
      cur += ch;
    }
    return { cols: cols, pk: pk };
  }
  function colName(part) {
    let t = part.trim();
    const m = t.match(/^["'\[]?([^"'\[\] (]+)["'\]]?/);
    return m ? m[1] : t;
  }

  return {
    pageSize: pageSize,
    tables: tables,
    tableNames: Object.keys(tables),
    hasTable: function (name) {
      if (tables[name]) return true;
      const ln = String(name).toLowerCase();
      for (const k in tables) { if (k.toLowerCase() === ln) return true; }
      return false;
    },
    rows: function (name) {
      let t = tables[name];
      if (!t) {
        const ln = String(name).toLowerCase();
        for (const k in tables) { if (k.toLowerCase() === ln) { t = tables[k]; break; } }
      }
      if (!t) return [];
      const out = [];
      walkTable(t.root, function (rec, rowid) {
        if (t.pk >= 0 && (rec[t.pk] === null || rec[t.pk] === undefined)) rec[t.pk] = rowid; // INTEGER PRIMARY KEY = rowid-Alias
        const o = {};
        for (let i = 0; i < t.cols.length; i++) o[t.cols[i]] = i < rec.length ? rec[i] : null;
        out.push(o);
      });
      return out;
    }
  };
}

/* ================= ERB -> Datenmodell ================= */
const QEA_FAMILY = {
  'SameAs': 'alias', 'IsResponsibleFor': 'resp', 'IsAccountableFor': 'acct',
  'NeedsResource': 'needs', 'Satisfy': 'satisfy', 'OwnedMilestone': 'owns',
  'MilestoneDependency': 'milestone'
};
const QEA_ORGKIND = /(Organization|Post)$/;

function qeaToModel(db) {
  const objRows = db.rows('t_object');
  const conRows = db.rows('t_connector');
  const tagRows = db.rows('t_objectproperties');
  const pkgRows = db.rows('t_package');

  const objects = {};
  objRows.forEach(function (r) {
    objects[r.Object_ID] = {
      id: r.Object_ID, name: String(r.Name || '').trim(), alias: String(r.Alias || ''),
      objectType: String(r.Object_Type || ''), stereotype: String(r.Stereotype || ''),
      status: String(r.Status || ''), note: String(r.Note || ''),
      packageId: r.Package_ID, parentId: r.ParentID || 0,
      author: String(r.Author || ''), version: String(r.Version || ''),
      created: String(r.CreatedDate || ''), modified: String(r.ModifiedDate || '')
    };
  });
  const tags = {};
  tagRows.forEach(function (r) {
    if (!tags[r.Object_ID]) tags[r.Object_ID] = {};
    tags[r.Object_ID][String(r.Property || '')] = String(r.Value == null ? '' : r.Value);
  });
  const pkgName = {};
  pkgRows.forEach(function (r) { pkgName[r.Package_ID] = String(r.Name || ''); });
  const pkgParent = {};
  pkgRows.forEach(function (r) { pkgParent[r.Package_ID] = r.Parent_ID || 0; });

  /* Paketfilter: Standardelemente-/Werkzeugkoffer-Pakete (Toolbox-Repertoire)
     sind KEINE Projektinhalte und werden aus Projekten/Kanten ausgeschlossen.
     Stark: "Standardelemente", "Standard Elements", "MDG Toolbox", "Werkzeugkoffer".
     Paar-Regel: (standard|repertoire|vorlage|template) + (element|katalog|modell). */
  const CATALOG_STRONG = /(standardelement|standard.?elem|werkzeug.?koffer|toolbox|stencil|mdg.?tech)/i;
  const CATALOG_A = /(standard|repertoire|vorlage|template)/i;
  const CATALOG_B = /(element|katalog|catalog|modell|sammlung)/i;
  function isCatalogName(nm) {
    return CATALOG_STRONG.test(nm) || (CATALOG_A.test(nm) && CATALOG_B.test(nm));
  }
  function pkgInCatalog(pid) {
    let cur = pid, guard = 0;
    while (cur && guard++ < 60) {
      if (isCatalogName(pkgName[cur] || '')) return true;
      cur = pkgParent[cur];
    }
    return false;
  }
  function objExcluded(o) {
    return !o || !o.packageId || pkgInCatalog(o.packageId);
  }

  /* Projekte + gleichnamige Layer-Zwillinge */
  const projects = [];
  const projBy = {};
  for (const id in objects) {
    const o = objects[id];
    if (o.stereotype === 'ActualProject' && !objExcluded(o)) {
      projBy[id] = projects.length;
      projects.push(o);
    }
  }
  const twinOf = {};
  for (const id in objects) {
    if (projBy[id] !== undefined) continue;
    const o = objects[id];
    if (!o.name || objExcluded(o)) continue;
    for (let pid in projBy) {
      if (norm(o.name) === norm(objects[pid].name)) { twinOf[id] = Number(pid); break; }
    }
  }
  function anchor(id) { return twinOf[id] !== undefined ? twinOf[id] : id; }

  /* Knotenverwaltung (fuer Stats + Graph-Shapes) */
  const nodes = {};   // key -> {label, kind: project|org|milestone|alias|other, stereotype}
  const orgKeys = new Set();
  const aliases = [];
  const edges = [];
  const relByProject = {};
  projects.forEach(function (p, idx) {
    const key = 'p' + idx;
    nodes[key] = { label: p.name, kind: 'project', stereotype: p.stereotype, projectRef: idx };
    relByProject[key] = [];
    p.key = key;
    p.qea = {
      key: key, tags: tags[p.id] || {}, twins: [],
      kind: (tags[p.id] || {})['projectKind'] || '', conf: { ebenen: [], domaenen: [], kategorien: [], standards: [], sonstige: [] }
    };
    p.measurements = []; p.milestones = []; p.degree = 0;
    p.resp = []; p.acct = []; p.needs = []; p.satisfy = []; p.aliases = [];
  });

  /* Zwillinge registrieren */
  for (const tid in twinOf) {
    const pk = 'p' + projBy[twinOf[tid]];
    projects[projBy[twinOf[tid]]].qea.twins.push({ id: Number(tid), name: objects[tid].name, stereotype: objects[tid].stereotype });
    nodes['x' + tid] = { label: objects[tid].name, kind: 'other', stereotype: objects[tid].stereotype, twinOf: pk };
  }

  function nodeKey(id) {
    const a = anchor(id);
    if (projBy[a] !== undefined) return 'p' + projBy[a];
    const o = objects[id];
    if (o.stereotype === 'ActualProjectMilestone') {
      const k = 'm:' + norm(o.name);
      if (!nodes[k]) nodes[k] = { label: o.name, kind: 'milestone', stereotype: o.stereotype, objectId: id, tags: tags[id] || {}, status: o.status };
      return k;
    }
    const k = 'x' + id;
    if (!nodes[k]) {
      const kind = QEA_ORGKIND.test(o.stereotype) ? 'org' : (o.stereotype === 'SameAs' ? 'other' : 'other');
      nodes[k] = { label: o.name, kind: kind, stereotype: o.stereotype || o.objectType, objectId: id, tags: tags[id] || {}, status: o.status };
      if (kind === 'org') orgKeys.add(k);
    }
    return k;
  }

  let eid = 0;
  function pushEdge(c, sObj, eObj, fam, orig) {
    const from = nodeKey(c.Start_Object_ID), to = nodeKey(c.End_Object_ID);
    edges.push({
      id: 'e' + (eid++), type: fam, origType: orig, connectorType: String(c.Type || ''),
      from: from, to: to,
      fromLabel: sObj.name, toLabel: eObj.name,
      fromKind: nodes[from] ? nodes[from].kind : 'other',
      toKind: nodes[to] ? nodes[to].kind : 'other',
      toStereo: eObj.stereotype || eObj.objectType,
      label: orig
    });
    return [from, to];
  }
  function peekKey(id) {
    const a = anchor(id);
    if (projBy[a] !== undefined) return 'p' + projBy[a];
    const o = objects[id];
    if (o.stereotype === 'ActualProjectMilestone') return 'm:' + norm(o.name);
    return 'x' + id;
  }
  /* Durchlauf 1: alles, was am Projektuniversum haengt */
  conRows.forEach(function (c) {
    const sObj = objects[c.Start_Object_ID], eObj = objects[c.End_Object_ID];
    if (!sObj || !eObj || objExcluded(sObj) || objExcluded(eObj)) return;
    const a = anchor(c.Start_Object_ID), b = anchor(c.End_Object_ID);
    const aIn = projBy[a] !== undefined, bIn = projBy[b] !== undefined;
    if (!aIn && !bIn) return;
    const orig = String(c.Stereotype || '') || String(c.Type || '');
    const fam = QEA_FAMILY[orig] || orig;
    pushEdge(c, sObj, eObj, fam, orig);
    /* Projekt-Anker: unabhaengig von der Richtung der Relation */
    const projIdx = aIn ? projBy[a] : projBy[b];
    const p = projects[projIdx];
    const other = aIn ? eObj : sObj;
    const otherName = other.name;
    relByProject[p.qea.key].push({ st: orig, dir: aIn ? 'out' : 'in', other: otherName, otherStereo: other.stereotype || other.objectType, name: String(c.Name || '') });
    if (fam === 'resp' && p.resp.indexOf(otherName) < 0) p.resp.push(otherName);
    if (fam === 'acct' && p.acct.indexOf(otherName) < 0) p.acct.push(otherName);
    if (fam === 'needs' && p.needs.indexOf(otherName) < 0) p.needs.push(otherName);
    if (fam === 'satisfy' && p.satisfy.indexOf(otherName) < 0) p.satisfy.push(otherName);
    if (fam === 'alias' && p.aliases.indexOf(otherName) < 0) { p.aliases.push(otherName); aliases.push({ project: p.name, alias: otherName }); }
    p.degree++;
    if (aIn && bIn) projects[projBy[b]].degree++;
  });
  /* Durchlauf 2: Ketten zwischen bereits registrierten Knoten (Meilenstein-Abhaengigkeiten etc.) */
  conRows.forEach(function (c) {
    const sObj = objects[c.Start_Object_ID], eObj = objects[c.End_Object_ID];
    if (!sObj || !eObj || objExcluded(sObj) || objExcluded(eObj)) return;
    const a = anchor(c.Start_Object_ID), b = anchor(c.End_Object_ID);
    if (projBy[a] !== undefined || projBy[b] !== undefined) return; // schon in Durchlauf 1
    const kf = peekKey(c.Start_Object_ID), kt = peekKey(c.End_Object_ID);
    if (!nodes[kf] || !nodes[kt]) return;
    const orig = String(c.Stereotype || '') || String(c.Type || '');
    const fam = QEA_FAMILY[orig] || orig;
    pushEdge(c, sObj, eObj, fam, orig);
  });

  /* Meilensteine je Projekt (OwnedMilestone + MilestoneDependency) */
  edges.forEach(function (e) {
    if (e.type === 'owns') {
      const pk = e.from.charAt(0) === 'p' ? e.from : (e.to.charAt(0) === 'p' ? e.to : null);
      const mk = e.to.indexOf('m:') === 0 ? e.to : (e.from.indexOf('m:') === 0 ? e.from : null);
      if (pk && mk && nodes[mk]) {
        const p = projects[Number(pk.slice(1))];
        if (p && !p.milestones.some(function (m) { return m.name === nodes[mk].label; })) {
          p.milestones.push({ name: nodes[mk].label, dep: '' });
        }
      }
    }
    if (e.type === 'milestone') {
      const mk = e.from.indexOf('m:') === 0 ? e.from : e.to;
      const dk = e.to.indexOf('m:') === 0 ? e.to : e.from;
      for (let i = 0; i < projects.length; i++) {
        const p = projects[i];
        for (let j = 0; j < p.milestones.length; j++) {
          if (norm(p.milestones[j].name) === mk.replace(/^m:/, '') && nodes[dk]) {
            p.milestones[j].dep = nodes[dk].label;
          }
        }
      }
    }
  });

  /* Klassifikation: ConformsTo-Abbildung aus ALLEN Roh-Connectoren (reihenfolgeunabhaengig) */
  const confBy = {};
  conRows.forEach(function (c) {
    if (String(c.Stereotype || '') !== 'ConformsTo') return;
    const s = objects[c.Start_Object_ID], e = objects[c.End_Object_ID];
    if (!s || !e) return;
    const k = norm(s.name);
    if (!confBy[k]) confBy[k] = [];
    confBy[k].push(e.name);
  });
  projects.forEach(function (p, idx) {
    const key = 'p' + idx;
    const keys = [key];
    p.milestones.forEach(function (m) { keys.push('m:' + norm(m.name)); });
    const labels = [p.name].concat(p.milestones.map(function (m) { return m.name; }));
    edges.forEach(function (e) {
      if ((keys.indexOf(e.from) >= 0 || keys.indexOf(e.to) >= 0) && /Arch/i.test(e.origType) && e.origType !== 'ConformsTo') {
        if (nodes[e.from]) labels.push(nodes[e.from].label);
        if (nodes[e.to]) labels.push(nodes[e.to].label);
      }
    });
    const vals = [];
    labels.forEach(function (l) {
      (confBy[norm(l)] || []).forEach(function (v) { vals.push(v); });
    });
    p.qea.conf = classifyConforms([...new Set(vals)]);
    p.conf = p.qea.conf;
    p.status = p.qea.tags.projectStatus || p.status;
    p.projectId = p.qea.tags['project-ID'] || '';
    p.shortTitle = p.qea.tags.projectShortTitle || '';
    p.parentPackage = pkgName[p.packageId] || '';
    p.startDate = p.qea.tags.startDate || '';
    p.endDate = p.qea.tags.endDate || '';
    p.notes = p.note;
    p.rels = relByProject[key];
    nodes[key].tags = p.qea.tags;
    nodes[key].status = p.status;
  });

  /* Orgs auch aus resp/acct-Namen als Knoten (falls nur als Text) — dedupliziert */
  projects.forEach(function (p, idx) {
    p.resp.concat(p.acct).forEach(function (nm) {
      const k = 'o:' + norm(nm);
      if (nodes[k]) return;
      for (const nk in nodes) {
        if (nodes[nk].kind === 'org' && norm(nodes[nk].label) === norm(nm)) return;
      }
      nodes[k] = { label: nm, kind: 'org', stereotype: 'ActualOrganization' };
      orgKeys.add(k);
    });
  });

  return {
    projects: projects, edges: edges, aliases: aliases,
    nodes: nodes, orgKeys: orgKeys,
    counts: { projects: projects.length, edges: edges.length, milestones: edges.filter(function (e) { return e.type === 'owns'; }).length, obj: objRows.length, con: conRows.length }
  };
}

var ADMBW_DATA = {"grid":{"cols":["taxonomy","structure","connectivity","processes","states","sequences","information","constraints","roadmap"],"col_de":["Taxonomie","Struktur","Konnektivität","Prozesse","Zustände","Sequenzen","Information","Restriktionen","Roadmap"],"rows":[{"layer":"Concept","label":"Konzepte","desc":"Strategischer Kontext: Fähigkeiten, Vision, Abhängigkeiten","cells":["C1","C2","C3","C4","C5",null,"C7","C8","Cr"]},{"layer":"Service","label":"Dienste","desc":"Service-Spezifikation: Dienste, Schnittstellen, Funktionen","cells":["S1","S2","S3","S4","S5","S6","S7","S8","Sr"]},{"layer":"Logical","label":"Logisch","desc":"Logische Spezifikation: Knoten, Aktivitäten, Informationsmodell","cells":["L1","L2","L3","L4","L5","L6","L7","L8","Lr"]},{"layer":"Physical","label":"Physisch","desc":"Physische Ressourcen: Typen, Struktur, Konnektivität","cells":["P1","P2","P3","P4","P5","P6","P7","P8","Pr"]},{"layer":"ArchFdn","label":"Architektur-Grundlagen","desc":"Architekturgrundlagen: Metadaten, Produkte, Standards","cells":["A1","A2","A3","A4","A5","A6","A7","A8","Ar"]},{"layer":"Req","label":"Anforderungen","desc":"Anforderungs-Viewpoints: Katalog, Abhängigkeiten, Erfüllung","cells":[null,"R2","R3","R7","R8",null,null,null,"Rr"]},{"layer":"Mapping","label":"Bridge/Mapping","desc":"Brücken-Sichten zwischen Bereichen","cells":["C1-S1","L2-L3","L4-P4",null,null,null,null,null,null],"bridge":true}]},"vp":{"A1":{"n":"Meta-Data Definitions","layer":"Architecture Foundation Viewpoints","cnt":16,"els":["ActualProject","ActualProjectMilestone","ArchitecturalDescription","ArchitectureForProject","ArchitectureMetadata","Classification","Classified","ConformsTo","DescribedBy","Expresses","Finding","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The A1 Viewpoint presents meta-data tags to aid with searching and discovery."},"A2":{"n":"Architecture Products","layer":"Architecture Foundation Viewpoints","cnt":27,"els":["ActualEnterprisePhase","ActualOrganization","ActualPerson","ActualPost","CompliesViewpoint","Concern","ConcernForView","ConcernForViewpoint","ConformsTo","EnterprisePhase","Finding","Organization","Person","Post","RealizesRecommendation","Recommendation","RefersTo","Responsibility","ResultsFrom","StakeholderConcern","Standard","View","Viewpoint","ViewpointToStakeholder","ViewpointsInArchitecturalDescription","ViewsInArchitecturalDescription","WholeLifeEnterprise"],"desc":"The A2 Viewpoint specifies the structure of an architecture, and the products that describe the architecture. Each product may correspond to an architecture view."},"A3":{"n":"Architecture Correspondence","layer":"Architecture Foundation Viewpoints","cnt":9,"els":["ArchitecturalDescription","ArchitecturalReference","ConformsTo","Finding","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The A3 Viewpoint presents correspondence relations between elements of Architecture Descriptions. ISO/IEC/IEEE42010 introduces the idea of architecture correspondence and correspondence rules. Quoting from ISO/IEC/IEEE 42010: \"A correspondence defines a relation between AD (Architecture Description) elements. Correspondences are used to express architecture relations of interest within an architecture description (or between architecture descriptions). Correspondences can be governed by correspondence rules. Correspondence rules are used to enforce relations within an architecture description (or between architecture descriptions).\""},"A4":{"n":"Methodology Used","layer":"Architecture Foundation Viewpoints","cnt":16,"els":["ActualProject","ActualProjectMilestone","ArchitecturalDescription","ArchitectureForProject","ArchitectureMetadata","Classification","Classified","ConformsTo","DescribedBy","Expresses","Finding","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The A4 Viewpoint specifies the methodology used for the architecting activities."},"A5":{"n":"Architecture Status","layer":"Architecture Foundation Viewpoints","cnt":16,"els":["ActualProject","ActualProjectMilestone","ArchitecturalDescription","ArchitectureForProject","ArchitectureMetadata","Classification","Classified","ConformsTo","DescribedBy","Expresses","Finding","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The A5 Viewpoint shows the current version number and approval status for the architecture."},"A6":{"n":"Architecture Version","layer":"Architecture Foundation Viewpoints","cnt":9,"els":["ArchitecturalDescription","ArchitecturalSequence","ConformsTo","Finding","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The A6 Viewpoint shows the complete history of the architecture."},"A7":{"n":"Architecture Compliance","layer":"Architecture Foundation Viewpoints","cnt":9,"els":["ConformsTo","Finding","Information","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","SameAs","Standard"],"desc":"The A7 Viewpoint gives the overall specification of architecture meta-data."},"A8":{"n":"Standards","layer":"Architecture Foundation Viewpoints","cnt":12,"els":["ActualOrganization","ConformsTo","Finding","Protocol","ProtocolLayer","Protocolstack","RatifiedStandards","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The A8 Viewpoint encompasses both technical and non-technical standards. The standards specified in the A8 view can be applied across the architecture to a variety of structural and behavioural elements. Standards are essential to the coherent running of businesses and to the delivery of reliable, interoperable systems."},"Ar":{"n":"Architecture Roadmap","layer":"Architecture Foundation Viewpoints","cnt":9,"els":["ArchitecturalDescription","ArchitecturalSequence","ConformsTo","Finding","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The Ar Viewpoint shows the history of the architecture project as well as its future direction."},"C1":{"n":"Capability Taxonomy","layer":"Concept Viewpoints","cnt":25,"els":["ActualCondition","ActualEnvironment","ActualLocation","Capability","CapabilityGeneralization","Classification","Classified","ConformsTo","DocumentReference","EnvironmentalContext","Finding","JustifiedBy","Measurement","MeasurementType","OriginatesFrom","OwnsMeasurement","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","Standard","StrategicConstraint"],"desc":"The C1 Viewpoint specifies all the capabilities that are referenced throughout one or more architectures – i.e. one C1 may provide the definitive list of capabilities for a number of logical and resource architectures. The capabilities may be organised into specialisation hierarchies (taxonomies). Measures of Effectiveness (MoE) may be specified for each capability. Note that MoEs are inherited down a capability taxonomy."},"C1-S1":{"n":"Capability to Service Mapping","layer":"Service Specification Viewpoints","cnt":12,"els":["Capability","ConformsTo","Environment","EnvironmentalCondition","Exhibits","Finding","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","ServiceSpecification","Standard"],"desc":"A C1-S1 Viewpoint presents a simple mapping of services to capabilities, showing which services contribute to which capability."},"C2":{"n":"Enterprise Vision","layer":"Concept Viewpoints","cnt":35,"els":["ActualEnduringTask","ActualEnterprisePhase","Capability","CapabilityForTask","Classification","Classified","ConformsTo","DocumentReference","EnduringTask","EnterpriseGoal","EnterprisePhase","EnterpriseVision","Environment","EnvironmentalCondition","Exhibits","Finding","GoalForActualEnterprisePhase","JustifiedBy","OperationalArchitecture","OperationalArchitectureOfEnterprisePhase","OriginatesFrom","PhysicalArchitectureOfEnterprisePhase","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","Standard","StatementTask","StrategicConstraint","TemporalPart","VisionForActualEnterprisePhase","WholeLifeEnterprise"],"desc":"The purpose of the C2 Viewpoint is to provide a strategic context for the capabilities described in the architecture and to specify the scope for the architecture. The C2 Viewpoint is high-level and describes the vision, goals, enduring tasks and capabilities using terminology that is easily understood by non-technical readers."},"C3":{"n":"Capability Dependencies","layer":"Concept Viewpoints","cnt":20,"els":["Capability","CapabilityDependency","CapabilityRole","CapabilityRoleDependency","Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","Standard","StrategicConstraint"],"desc":"The C3 Viewpoint is intended to provide a means of analysing the dependencies between capabilities and between capability clusters. The composition of capabilities (into clusters) is logical and the purpose of the clusters is to guide enterprise management."},"C4":{"n":"Standard Processes","layer":"Concept Viewpoints","cnt":22,"els":["ActualEnduringTask","Capability","CapabilityForTask","Classification","Classified","ConformsTo","DocumentReference","EnduringTask","Finding","JustifiedBy","MapsToCapability","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","Standard","StandardOperationalActivity","StrategicConstraint"],"desc":"The C4 Viewpoint specifies Standard Operational Activities that can be re-used across multiple logical architectures (e.g. in L4, Logical Activities)."},"C5":{"n":"Effects","layer":"Concept Viewpoints","cnt":41,"els":["AchievedEffect","ActualCondition","ActualEnduringTask","ActualEnterprisePhase","ActualMeasurementSet","ActualOrganization","ActualPerson","ActualPost","ActualProjectMilestone","ActualPropertySet","ActualResource","Capability","CapabilityConfiguration","Classification","Classified","ConformsTo","DesiredEffect","DocumentReference","Environment","EnvironmentalCondition","Exhibits","FieldedCapability","Finding","JustifiedBy","Organization","OriginatesFrom","Person","Post","RealizedDesiredEffect","RealizesRecommendation","RealizingAchievedEffect","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","ServiceSpecification","Standard","StandardOperationalActivity","StrategicConstraint"],"desc":"The purpose of the C5 Viewpoint is to describe the operational effect of the capabilities, activities and services according to the expected goals. The C5 Viewpoint is high-level description that should be easily understood by non-technical readers."},"C7":{"n":"Performance Parameters","layer":"Concept Viewpoints","cnt":24,"els":["ActualCondition","ActualEnvironment","ActualLocation","Capability","Classification","Classified","ConformsTo","DocumentReference","EnvironmentalContext","Finding","JustifiedBy","Measurement","MeasurementType","OriginatesFrom","OwnsMeasurement","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","Standard","StrategicConstraint"],"desc":"In the C7 Viewpoint the capability requirements (and existing capabilities) can be expressed in terms of Measures of Effectiveness (MoEs). These are high-level metrics used to judge the level of capability."},"C8":{"n":"Planning Assumptions","layer":"Concept Viewpoints","cnt":20,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","Implements","JustifiedBy","OperationalConstraint","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","ServicePolicy","Standard","StrategicConstraint"],"desc":"The C8 Viewpoint is concerned with identification and description of assumptions that have been made for the implementation of capabilities. Assumptions can be expressed by means of requirements."},"Cr":{"n":"Capability Roadmap","layer":"Concept Viewpoints","cnt":28,"els":["ActualProject","ActualProjectDependency","ActualProjectMilestone","ActualResourceNeededByActualProjectMilestone","ActualResourceToActualProjectMilestone","Capability","CapabilityConfiguration","ConformsTo","Environment","EnvironmentalCondition","Exhibits","FieldedCapability","Finding","MilestoneDependency","OwnedMilestone","Project","ProjectMilestone","ProjectMilestoneRole","ProjectMilestoneToProjectTheme","ProjectSequence","RealizesRecommendation","Recommendation","RefersTo","RequiredResource","ResultsFrom","Standard","VersionReleased","VersionWithdrawn"],"desc":"The Cr Viewpoint supports the Capability Audit process by providing a method to identify gaps or duplications in capability provision. Cr indicates capability increments, which are derived from delivery milestones within acquisition projects."},"L1":{"n":"Node Types","layer":"Logical Specification Viewpoints","cnt":32,"els":["ActualCondition","ActualEnvironment","ActualLocation","Classification","Classified","ConformsTo","DocumentReference","Environment","EnvironmentalCondition","EnvironmentalContext","Exhibits","Finding","JustifiedBy","MapsToCapability","Measurement","MeasurementType","OperationalActivity","OperationalActivityAction","OperationalConstraint","OperationalPerformer","OperationalRole","OriginatesFrom","OwnsMeasurement","PropertySetGeneralization","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","Standard"],"desc":"The L1 Viewpoint defines all of the Nodes that will appear in a Logical Architecture. Nodes are elements of capability assembled and orchestrated in the Logical Architecture (see L2 - Logical Scenario and L4 - Logical Activities views). The levels of capability provided by each node are expressed as Measures of Performance (MoPs) and these may be dependent on the environments in which the Node is required to operate."},"L2":{"n":"Logical Scenario","layer":"Logical Specification Viewpoints","cnt":50,"els":["ActualCondition","ActualEnvironment","ActualLocation","Classification","Classified","Condition","ConformsTo","DocumentReference","Energy","Environment","EnvironmentalContext","Finding","GeoPoliticalExtentType","InformationElement","JustifiedBy","KnownResource","Location","LocationType","Measurement","MeasurementType","NaturalResource","OperationalArchitecture","OperationalConnector","OperationalConstraint","OperationalExchange","OperationalInterface","OperationalPerformer","OperationalPort","OperationalRole","OperationalSignal","Organization","OriginatesFrom","OwnsMeasurement","Person","PhysicalLocation","Post","ProblemDomain","Project","RealizesRecommendation","Recommendation","Reference","RefersTo","RequiredEnvironment","ResourceArchitecture","ResourceArtifact","Responsibility","ResultsFrom","SMEReference","Satisfy","Standard"],"desc":"The L2 Viewpoint specifies Nodes (elements of capability) in context of each other. The context is usually expressed in terms of the information that flows between the nodes (e.g. the information flow requirements between capabilities in a given scenario) but may also be flows of materiel, human resource or energy."},"L2-L3":{"n":"Logical Concept","layer":"Logical Specification Viewpoints","cnt":39,"els":["ActualCondition","ActualEnvironment","ActualLocation","ArbitraryConnector","CapabilityConfiguration","Classification","Classified","ConceptRole","ConformsTo","DataElement","DocumentReference","EnvironmentalContext","Finding","HighLevelOperationalConcept","InformationElement","JustifiedBy","Location","Measurement","MeasurementType","NaturalResource","OperationalArchitecture","OperationalConstraint","OperationalPerformer","Organization","OriginatesFrom","OwnsMeasurement","Person","Post","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceArchitecture","ResultsFrom","SMEReference","Satisfy","Software","Standard","System"],"desc":"The L2-L3 Viewpoint is concerned with providing an executive level, scenario-based communication of the architecture purpose, scope and content."},"L3":{"n":"Node Interactions","layer":"Logical Specification Viewpoints","cnt":60,"els":["ActualCondition","ActualEnvironment","ActualLocation","CapabilityConfiguration","Classification","Classified","Condition","ConformsTo","ConsumedBy","DocumentReference","Energy","Environment","EnvironmentalContext","Finding","GeoPoliticalExtentType","InformationElement","InformationRole","IsCapableToPerform","JustifiedBy","KnownResource","Location","LocationType","Measurement","MeasurementType","NaturalResource","OperationalArchitecture","OperationalConnector","OperationalConstraint","OperationalExchange","OperationalInterface","OperationalPerformer","OperationalPort","OperationalRole","OperationalSignal","Organization","OriginatesFrom","OwnsMeasurement","PerformsInContext","Person","PhysicalLocation","Post","PostRole","ProblemDomain","Project","Provides","RealizesRecommendation","Recommendation","Reference","RefersTo","RequiredEnvironment","ResourceArchitecture","ResourceArtifact","Responsibility","ResultsFrom","SMEReference","Satisfy","ServiceSpecification","ServiceSpecificationRole","Standard","SubOrganization"],"desc":"L3 is used to provide further detail of the interoperability requirements associated with the operational capability of interest. The focus is on logical flows that cross the capability boundary. Although the primary purpose of the L3 Viewpoint is to specify information exchanges, the L3 may also list flows of materiel, energy and human resources."},"L4":{"n":"Logical Activities","layer":"Logical Specification Viewpoints","cnt":50,"els":["ActivityPerformableUnderCondition","ActivitySupportsService","ActsUpon","ActualCondition","ActualService","AffectedActivity","AffectedResource","Classification","Classified","ConformsTo","Consumes","DocumentReference","Finding","GeoPoliticalExtentType","Implements","InformationElement","InformationRole","IsCapableToPerform","JustifiedBy","KnownResource","NaturalResource","OperationalActivity","OperationalActivityAction","OperationalConstraint","OperationalExchange","OperationalPerformer","OperationalRole","OperationalSignal","Organization","OriginatesFrom","PaperForm","PerformsInContext","Person","Post","ProcessGeneralization","Project","RealizesRecommendation","Recommendation","Reference","RefersTo","RequiredServiceLevel","ResourceArchitecture","ResourceArtifact","Responsibility","ResultsFrom","SMEReference","Satisfy","ServiceSpecification","Standard","StandardOperationalActivity"],"desc":"The L4 Viewpoint describes the operational activities that are being conducted within the mission or scenario. These activities are defined at a logical, solution-neutral level so as to enable different solutions in the physical layer. The L4 Viewpoint describes the activities associated with the logical architecture."},"L4-P4":{"n":"Activity To Function Mapping","layer":"Physical Resource Specification Viewpoints","cnt":20,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","Implements","IsCapableToPerform","JustifiedBy","OriginatesFrom","PerformsInContext","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","ServiceProvision","Standard"],"desc":""},"L5":{"n":"Logical States","layer":"Logical Specification Viewpoints","cnt":19,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","OperationalArchitecture","OperationalConstraint","OperationalPerformer","OperationalStateDescription","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","Standard"],"desc":"The L5 Viewpoint specifies the typical states a node may have and the possible transitions between those states (i.e. changes of state). Triggers for state changes may also be defined. Actions may be associated with a given state or with the transition between states in response to stimuli (e.g. triggers and events)."},"L6":{"n":"Logical Sequence","layer":"Logical Specification Viewpoints","cnt":20,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","OperationalConstraint","OperationalMessage","OperationalRole","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","ServiceMessage","ServiceSpecificationRole","Standard"],"desc":"Operational Event-Trace Descriptions, sometimes called sequence diagrams, event scenarios or timing diagrams, allow the tracing of interactions between nodes in a scenario or critical sequence of events. The node interactions usually correspond to flows of information but may describe flows of energy, materiel or people specified in the L2, Logical Scenario."},"L7":{"n":"Information Model","layer":"Logical Specification Viewpoints","cnt":21,"els":["Classification","Classified","ConformsTo","DataModel","DocumentReference","Finding","Implements","InformationElement","InformationRole","JustifiedBy","OperationalConstraint","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","Standard"],"desc":"The L7 Viewpoint is used to document the business information. It describes the information that can be exchanged along the logical flows in the architecture, specified in L2, L3 and L4."},"L8":{"n":"Logical Constraints","layer":"Logical Specification Viewpoints","cnt":20,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","Implements","JustifiedBy","OperationalConstraint","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","ServicePolicy","Standard","StrategicConstraint"],"desc":"The L8 Viewpoint is used to constrain the logical architecture without forcing a particular solution. L8 is used for rules which are not expressed as behavioural models, interactions or measures of effectiveness, i.e. they are textual statements of requirements that constrain the architecture."},"Lr":{"n":"Lines of Development","layer":"Logical Specification Viewpoints","cnt":40,"els":["ActualProject","ActualProjectConsults","ActualProjectDependency","ActualProjectInforms","ActualProjectMilestone","ActualResourceRelationship","ArchitecturalDescription","ArchitectureForProject","CapabilityConfiguration","Classification","Classified","ConformsTo","DocumentReference","EnterprisePhase","Finding","IsAccountableFor","IsResponsibleFor","JustifiedBy","MilestoneDependency","OperationalConstraint","OriginatesFrom","OwnedMilestone","Project","ProjectMilestone","ProjectMilestoneRole","ProjectMilestoneToProjectTheme","ProjectSequence","ProjectTheme","RealizesRecommendation","Recommendation","Reference","RefersTo","RequiredResource","ResultsFrom","SMEReference","Satisfy","ServiceSpecification","Standard","VersionReleased","VersionWithdrawn"],"desc":"The Lr Viewpoint is primarily intended to support the acquisition process across multiple projects or programmes, highlighting dependencies the logical dependencies between capabilities, projects and the integration of all lines of development to achieve a successfully integrated military capability. Use of the Lr Viewpoint should support the management of capability delivery and be aligned with Cr, Capability Roadmap."},"P1":{"n":"Resource Types","layer":"Physical Resource Specification Viewpoints","cnt":53,"els":["ActualCondition","ActualEnterprisePhase","ActualEnvironment","ActualLocation","ActualResource","ActualService","CapabilityConfiguration","Classification","Classified","Competence","ConformsTo","DataElement","DataElementStoredIn","DocumentReference","Energy","EnterprisePhase","EnvironmentalContext","Finding","Forecast","ForecastPeriod","FormStoredIn","Implements","JustifiedBy","Measurement","MeasurementType","NaturalResource","Organization","OriginatesFrom","OwnsMeasurement","PaperForm","Person","Post","PropertySetGeneralization","ProvidedServiceLevel","RealizesRecommendation","Recommendation","Reference","RefersTo","RequiredServiceLevel","RequiresCompetence","ResourceArchitecture","ResourceArtifact","ResourceConstraint","ResourceInterface","ResultsFrom","SMEReference","Satisfy","ServiceProvision","ServiceSpecification","Software","Standard","System","Technology"],"desc":"The P1 Viewpoint collects together all the Resource Types in the architecture together with a depiction of their performance characteristics. P1 also provides a summary of the technologies and competencies that impact on the Resources that constitute the architecture."},"P2":{"n":"Resource Structure","layer":"Physical Resource Specification Viewpoints","cnt":67,"els":["ActualCondition","ActualEnvironment","ActualLocation","ActualProject","ActualProjectConsults","ActualProjectInforms","CapabilityConfiguration","Classification","Classified","Command","Competence","CompetenceForRole","ConformsTo","Control","DataElement","DataRole","DocumentReference","Energy","Environment","EnvironmentalContext","Finding","Function","GeoPoliticalExtentType","HostedOn","Implements","IsAccountableFor","IsResponsibleFor","JustifiedBy","Location","LocationType","Measurement","MeasurementType","NaturalResource","NeedsModificationOf","NeedsResource","Organization","OriginatesFrom","OwnsMeasurement","Person","PhysicalLocation","Post","PostRole","ProjectProvidesFunction","ProjectSupportActivity","RealizesRecommendation","Recommendation","Reference","RefersTo","RequiredEnvironment","ResourceArchitecture","ResourceArtifact","ResourceConstraint","ResourceDependency","ResourceExchange","ResourceRole","ResourceToServiceDependency","Responsible","ResultsFrom","SMEReference","Satisfy","ServiceProvision","ServiceSpecification","ServiceSpecificationRole","Software","Standard","SubOrganization","System"],"desc":"The P2 Viewpoint links together the operational and physical architecture viewpoints by depicting how types of Resource are structured and interact to realize the logical architecture specified in L2, Logical Scenario. The P2 Viewpoint may represent the realization of a requirement specified in a L2 (i.e. in a “to-be” architecture) and so there may be many alternative Resource viewpoint suites that could realize the operational requirement. Alternatively, in an “as-is” architecture, a L2 may just be a simplified, logical representation of the P2 Viewpoint to allow communication of key information flows to non-technical stakeholders."},"P3":{"n":"Resource Connectivity","layer":"Physical Resource Specification Viewpoints","cnt":43,"els":["ActualCondition","ActualEnvironment","ActualLocation","BoundaryCondition","CapabilityConfiguration","Classification","Classified","ConformsTo","Control","DataElement","DataRole","DocumentReference","EnvironmentalContext","Finding","ImplementsProtocol","JustifiedBy","Measurement","MeasurementType","OriginatesFrom","OwnsMeasurement","Protocol","ProtocolLayer","Protocolstack","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceArchitecture","ResourceArtifact","ResourceConnector","ResourceConstraint","ResourceDependency","ResourceExchange","ResourceInterface","ResourcePort","ResourceRole","ResourceSignal","ResultsFrom","SMEReference","Satisfy","Software","Standard","System"],"desc":"The networks and pathways documented in a P3 Viewpoint represent the physical implementation of the logical flows identified in a L2, Logical Scenario, or L3, Node Interactions View."},"P4":{"n":"Resource Functions","layer":"Physical Resource Specification Viewpoints","cnt":32,"els":["ActualCondition","ActualEnvironment","ActualLocation","AffectedFunctions","Classification","Classified","ConformsTo","DataElement","DocumentReference","EnvironmentalContext","Finding","Function","FunctionAction","FunctionControlFlow","FunctionObjectFlow","FunctionSubject","IsCapableToPerform","JustifiedBy","Measurement","MeasurementType","OriginatesFrom","OwnsMeasurement","PerformsInContext","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","Standard"],"desc":"The Functionality Description provides detailed information regarding the allocation of functions to resources, and flows between Resource Functions. The P4 Viewpoint is the Physical Resource counterpart to the L4 Logical Activities Viewpoint."},"P5":{"n":"Resource States","layer":"Physical Resource Specification Viewpoints","cnt":17,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResourceStateDescription","ResultsFrom","SMEReference","Satisfy","Standard"],"desc":"The P5 Viewpoint identifies the states a Resource can be, the allowable changes between those states, and the stimuli (e.g. triggers and events) that cause the state changes."},"P6":{"n":"Resource Sequence","layer":"Physical Resource Specification Viewpoints","cnt":20,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResourceMessage","ResourceRole","ResultsFrom","SMEReference","Satisfy","ServiceMessage","ServiceSpecificationRole","Standard"],"desc":"The P6 Viewpoint is valuable for moving to the next level of detail from the initial solution design, to help define a sequence of functions and Resource Interactions, and to ensure that each participating Resource or Port has the necessary information, at the right time, in order to perform its assigned functionality."},"P7":{"n":"Data Model","layer":"Physical Resource Specification Viewpoints","cnt":20,"els":["Classification","Classified","ConformsTo","DataElement","DataModel","DataRole","DocumentReference","Finding","Implements","JustifiedBy","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","Standard"],"desc":"The P7 Viewpoint is one of the architectural products closest to actual system design in the NAF. It is used to describe how the information represented in the L7 Logical Data Model Viewpoint is implemented."},"P8":{"n":"Resource Constraints","layer":"Physical Resource Specification Viewpoints","cnt":23,"els":["ActualPerson","ActualPost","Classification","Classified","ConformsTo","DocumentReference","FillsPost","Finding","Implements","JustifiedBy","OperationalConstraint","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","ServicePolicy","Standard","StrategicConstraint"],"desc":"The P8 Viewpoint describes constraints on the Resources, Resource Functions, data and communications that make up a Physical Architecture."},"Pr":{"n":"Configuration Management","layer":"Physical Resource Specification Viewpoints","cnt":33,"els":["ActualProject","ActualProjectDependency","ActualProjectMilestone","Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","MilestoneDependency","OriginatesFrom","OwnedMilestone","Project","ProjectMilestone","ProjectMilestoneRole","ProjectMilestoneToProjectTheme","ProjectSequence","RealizesRecommendation","Recommendation","Reference","RefersTo","RequiredResource","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","Standard","SuccessorOf","VersionOfConfiguration","VersionReleased","VersionSuccession","VersionWithdrawn","WholeLifeConfiguration"],"desc":"The Pr Viewpoint provides an overview of how Resource Assets change over time (note that NAF v3.1 only allowed for Capability Configurations whereas now this is opened up to all Resource Types). It shows the structure of different versions of Resource Assets (usually Capability Configurations or Service Implementations) mapped against a timeline."},"R2":{"n":"Requirement Catalogue","layer":"Requirement Viewpoints","cnt":13,"els":["ConformsTo","Finding","FunctionalRequirement","NonfunctionalRequirement","PartOfCatalogue","PartOfCategory","RealizesRecommendation","Recommendation","RefersTo","RequirementCatalogue","RequirementCategory","ResultsFrom","Standard"],"desc":"The R2 represents a catalog of requirements in the architectural model. For this purpose, categories can be created in which the functional and non-functional requirements can be grouped."},"R3":{"n":"Requirement Dependencies","layer":"Requirement Viewpoints","cnt":15,"els":["ConflictsWith","ConformsTo","Finding","FunctionalRequirement","IsDuplicateOf","NonfunctionalRequirement","RealizesRecommendation","Recommendation","RefersTo","Refines","Replaces","Requires","ResultsFrom","Standard","StemsFrom"],"desc":"The R3 is used to show dependencies between different requirements."},"R7":{"n":"Requirement Derivation","layer":"Requirement Viewpoints","cnt":25,"els":["Classification","Classified","ConformsTo","DerivedFrom","DocumentReference","Finding","FunctionalRequirement","Implements","JustifiedBy","NonfunctionalRequirement","OperationalConstraint","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","Refines","Requires","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","ServicePolicy","Standard","ToBeRealizedBy"],"desc":"The R7 assigns functional and non-functional requirements to the demanding architectural elements. In addition, information about the planned realization can be shown."},"R8":{"n":"Requirement Fulfilment","layer":"Requirement Viewpoints","cnt":11,"els":["Checks","ConformsTo","Evaluates","Finding","FitCriterion","FulfilmentCriterion","RealizesRecommendation","Recommendation","RefersTo","ResultsFrom","Standard"],"desc":"The R8 is used to determine and map acceptance and evaluation criteria for the individual functional and non- functional requirements."},"Rr":{"n":"Requirement Realization","layer":"Requirement Viewpoints","cnt":27,"els":["CapabilityConfiguration","ConformsTo","Finding","Function","Measurement","MeasurementType","NaturalResource","Organization","Person","Post","Protocol","Protocolstack","RealiseRequirement","RealizesRecommendation","Recommendation","RefersTo","ResourceArchitecture","ResourceArtifact","ResourceInterface","ResultsFrom","ServiceFunction","ServiceInterface","ServiceSpecification","ServiceSpecificationRole","Software","Standard","System"],"desc":"In the Rr, requirements are assigned to the realizing architectural elements."},"S1":{"n":"Service Taxonomy","layer":"Service Specification Viewpoints","cnt":25,"els":["ActualCondition","ActualEnvironment","ActualLocation","Classification","Classified","ConformsTo","DocumentReference","EnvironmentalContext","Finding","JustifiedBy","Measurement","MeasurementType","OriginatesFrom","OwnsMeasurement","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","ServiceGeneralization","ServicePolicy","ServiceSpecification","Standard"],"desc":"The purpose of the S1 Viewpoint is to provide a governance structure for a Service-Oriented Architecture. Along with S3, Service Interfaces, it specifies a standard library of service specifications for an enterprise, to which service implementers are expected to conform."},"S2":{"n":"Service Structure","layer":"Service Specification Viewpoints","cnt":44,"els":["ActualCondition","ActualEnvironment","ActualLocation","CapabilityConfiguration","Classification","Classified","ConformsTo","DocumentReference","EnvironmentalContext","Finding","IsAccountableFor","IsCapableToPerform","IsResponsibleFor","JustifiedBy","Measurement","MeasurementType","NaturalResource","OperationalPerformer","Organization","OriginatesFrom","OwnsMeasurement","Person","Post","ProvidesServiceFunction","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceArchitecture","ResourceArtifact","ResourceInterface","ResultsFrom","SMEReference","Satisfy","ServiceDependency","ServiceFunction","ServiceInterface","ServicePolicy","ServicePort","ServiceSpecification","ServiceSpecificationRole","Software","Standard","System"],"desc":"The S2 Viewpoint is concerned with identification and description of how services are structured to create a higher-aggregated service. To provide highlevel views, dependencies to other services, nodes and resources as well as service interfaces and service functions can be represented."},"S3":{"n":"Service Interfaces","layer":"Service Specification Viewpoints","cnt":23,"els":["Classification","Classified","ConformsTo","DataElement","DataRole","DocumentReference","Finding","JustifiedBy","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","ServiceConnector","ServiceExchange","ServiceInterface","ServicePolicy","ServicePort","ServiceSpecification","Standard"],"desc":"The S3 Viewpoint is concerned with the identification and definition of service interfaces."},"S4":{"n":"Service Functions","layer":"Service Specification Viewpoints","cnt":23,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","IsCapableToPerform","JustifiedBy","OriginatesFrom","PerformsInContext","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","ServiceExchange","ServiceFunction","ServiceFunctionAction","ServicePolicy","ServiceSpecification","ServiceSpecificationRole","Standard"],"desc":"The S4 Viewpoint is the key behavioural specification for services. Equivalent in nature to L4, Logical Activities and P4, Resources Functions, it specifies a set of functions that a service implementation is expected to perform. Implementation of that behaviour is represented in P4, Resource Functions, and L4-P4, Activity to Function Mapping."},"S5":{"n":"Service States","layer":"Service Specification Viewpoints","cnt":18,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","OriginatesFrom","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","ServicePolicy","ServiceSpecification","ServiceStateDescription","Standard"],"desc":"The S5 Viewpoint is a specification of the allowable states of a service, and the possible transitions between them. This specification constrains how implementations of the service will behave. It is, though, generally considered a good practice to make services stateless - i.e. consumers of a service are not aware of what state the service is in."},"S6":{"n":"Service Interactions","layer":"Service Specification Viewpoints","cnt":14,"els":["ConformsTo","Finding","OperationalMessage","OperationalRole","RealizesRecommendation","Recommendation","RefersTo","ResourceMessage","ResourceRole","ResultsFrom","ServiceExchange","ServiceMessage","ServiceSpecificationRole","Standard"],"desc":"Service Interaction Descriptions, sometimes called sequence diagrams, event scenarios or timing diagrams, allow the tracing of interactions between services in a composition or critical sequence of events."},"S7":{"n":"Service Interface Parameters","layer":"Service Specification Viewpoints","cnt":20,"els":["Classification","Classified","ConformsTo","DocumentReference","Finding","JustifiedBy","OriginatesFrom","ProvidesServiceFunction","RealizesRecommendation","Recommendation","Reference","RefersTo","ResultsFrom","SMEReference","Satisfy","ServiceFunction","ServiceInterface","ServicePolicy","ServiceSpecification","Standard"],"desc":"Specifies the interfaces that a service provides and uses, defines which services are compatible with which other services."},"S8":{"n":"Service Policy","layer":"Service Specification Viewpoints","cnt":27,"els":["ActualCondition","ActualEnvironment","ActualLocation","Classification","Classified","ConformsTo","DocumentReference","EnvironmentalContext","Finding","Implements","JustifiedBy","Measurement","MeasurementType","OperationalConstraint","OriginatesFrom","OwnsMeasurement","RealizesRecommendation","Recommendation","Reference","RefersTo","ResourceConstraint","ResultsFrom","SMEReference","Satisfy","ServicePolicy","Standard","StrategicConstraint"],"desc":"The S8 Viewpoint specifies constraints against services to which implementations must conform."},"Sr":{"n":"Service Roadmap","layer":"Service Specification Viewpoints","cnt":27,"els":["ActualProject","ActualProjectDependency","ActualProjectMilestone","ActualService","ConformsTo","Finding","IsAccountableFor","IsResponsibleFor","MilestoneDependency","NeedsService","OwnedMilestone","Project","ProjectMilestone","ProjectMilestoneRole","ProjectMilestoneToProjectTheme","ProjectSequence","ProvidedServiceLevel","RealizesRecommendation","Recommendation","RefersTo","RequiredResource","RequiredServiceLevel","ResultsFrom","ServiceSpecification","Standard","VersionReleased","VersionWithdrawn"],"desc":"The Sr Viewpoint supports the Service Audit process by providing a method to identify gaps or duplications in service provision. Sr indicates service lifetime evolutions, which are derived from delivery milestones within acquisition projects."}},"topo":{"A1":[{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"ArchitecturalReference","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitecturalSequence","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitectureForProject","from":["ActualProject"],"to":["ArchitecturalDescription"]},{"rel":"Classified","from":["ArchitecturalDescription"],"to":["Classification"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"OwnedMilestone","from":["ActualProject"],"to":["ActualProjectMilestone"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"A2":[{"rel":"CompliesViewpoint","from":["View"],"to":["Viewpoint"]},{"rel":"ConcernForActualEnterprisePhase","from":["ActualEnterprisePhase"],"to":["Concern"]},{"rel":"ConcernForView","from":["View"],"to":["Concern"]},{"rel":"ConcernForViewpoint","from":["Viewpoint"],"to":["Concern"]},{"rel":"FillsPost","from":["ActualPerson"],"to":["ActualPost"]},{"rel":"RatifiedStandards","from":["ActualOrganization"],"to":["Standard"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"A3":[{"rel":"ArchitecturalReference","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitecturalSequence","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"A4":[{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"ArchitecturalReference","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitecturalSequence","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitectureForProject","from":["ActualProject"],"to":["ArchitecturalDescription"]},{"rel":"Classified","from":["ArchitecturalDescription"],"to":["Classification"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"OwnedMilestone","from":["ActualProject"],"to":["ActualProjectMilestone"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"A5":[{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"ArchitecturalReference","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitecturalSequence","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitectureForProject","from":["ActualProject"],"to":["ArchitecturalDescription"]},{"rel":"Classified","from":["ArchitecturalDescription"],"to":["Classification"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"OwnedMilestone","from":["ActualProject"],"to":["ActualProjectMilestone"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"A6":[{"rel":"ArchitecturalReference","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitecturalSequence","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"A7":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"A8":[{"rel":"RatifiedStandards","from":["ActualOrganization"],"to":["Standard"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"Ar":[{"rel":"ArchitecturalReference","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitecturalSequence","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"C1":[{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"C1-S1":[{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"EnvironmentalCondition","from":["Exhibits"],"to":["Environment"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"C2":[{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityForTask","from":["Capability"],"to":["ActualEnduringTask"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"EnvironmentalCondition","from":["Exhibits"],"to":["Environment"]},{"rel":"GoalForActualEnterprisePhase","from":["ActualEnterprisePhase"],"to":["EnterpriseGoal"]},{"rel":"OperationalArchitectureOfEnterprisePhase","from":["ActualEnterprisePhase"],"to":["OperationalArchitecture"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"StatementTask","from":["ActualEnterprisePhase"],"to":["ActualEnduringTask"]},{"rel":"VisionForActualEnterprisePhase","from":["ActualEnterprisePhase"],"to":["EnterpriseVision"]}],"C3":[{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityRoleDependency","from":["CapabilityRole"],"to":["CapabilityRole"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"C4":[{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityForTask","from":["Capability"],"to":["ActualEnduringTask"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"C5":[{"rel":"ActualConditionToActualResource","from":["ActualResource"],"to":["ActualCondition"]},{"rel":"ActualResourceNeededByActualProjectMilestone","from":["ActualResource"],"to":["ActualProjectMilestone"]},{"rel":"ActualResourceRelationship","from":["ActualResource"],"to":["ActualResource"]},{"rel":"ActualResourceToActualProjectMilestone","from":["ActualResource"],"to":["ActualProjectMilestone"]},{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityForTask","from":["Capability"],"to":["ActualEnduringTask"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"EnvironmentalCondition","from":["Exhibits"],"to":["Environment"]},{"rel":"FillsPost","from":["ActualPerson"],"to":["ActualPost"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"RatifiedStandards","from":["ActualOrganization"],"to":["Standard"]},{"rel":"RealizedDesiredEffect","from":["AchievedEffect"],"to":["DesiredEffect"]},{"rel":"RealizingAchievedEffect","from":["DesiredEffect"],"to":["AchievedEffect"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"StatementTask","from":["ActualEnterprisePhase"],"to":["ActualEnduringTask"]}],"C7":[{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"C8":[{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"Cr":[{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"CapabilityDependency","from":["Capability"],"to":["Capability"]},{"rel":"CapabilityGeneralization","from":["Capability"],"to":["Capability"]},{"rel":"EnvironmentalCondition","from":["Exhibits"],"to":["Environment"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"OwnedMilestone","from":["ActualProject"],"to":["ActualProjectMilestone"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"L1":[{"rel":"EnvironmentalCondition","from":["Exhibits"],"to":["Environment"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"OperationalExchange","from":["OperationalActivity"],"to":["OperationalActivity"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"L2":[{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"OperationalConnector","from":["OperationalPort"],"to":["OperationalPort"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"L2-L3":[{"rel":"ArbitraryConnector","from":["ConceptRole"],"to":["ConceptRole"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"SameAs","from":["Software"],"to":["Software"]}],"L3":[{"rel":"ConsumedBy","from":["ServiceSpecification"],"to":["OperationalPerformer"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"OperationalConnector","from":["OperationalPort"],"to":["OperationalPort"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"Provides","from":["OperationalPerformer"],"to":["ServiceSpecification"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"L4":[{"rel":"ActivitySupportsService","from":["OperationalActivity"],"to":["ServiceSpecification"]},{"rel":"ConsumedBy","from":["ServiceSpecification"],"to":["OperationalPerformer"]},{"rel":"Consumes","from":["OperationalActivity"],"to":["ActualService"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"OperationalExchange","from":["OperationalActivity"],"to":["OperationalActivity"]},{"rel":"Provides","from":["OperationalPerformer"],"to":["ServiceSpecification"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"L4-P4":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"L5":[{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"L6":[{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"L7":[{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"L8":[{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"Lr":[{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"ArchitecturalReference","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitecturalSequence","from":["ArchitecturalDescription"],"to":["ArchitecturalDescription"]},{"rel":"ArchitectureForProject","from":["ActualProject"],"to":["ArchitecturalDescription"]},{"rel":"Classified","from":["ArchitecturalDescription"],"to":["Classification"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"NeedsService","from":["ActualProject"],"to":["ServiceSpecification"]},{"rel":"OwnedMilestone","from":["ActualProject"],"to":["ActualProjectMilestone"]},{"rel":"ProjectMilestoneToProjectTheme","from":["ProjectMilestone"],"to":["ProjectTheme"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"P1":[{"rel":"ActualConditionToActualResource","from":["ActualResource"],"to":["ActualCondition"]},{"rel":"ActualResourceRelationship","from":["ActualResource"],"to":["ActualResource"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"ForecastPeriod","from":["Forecast"],"to":["ActualEnterprisePhase"]},{"rel":"FormStoredIn","from":["PaperForm"],"to":["Software"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"PhysicalArchitectureOfEnterprisePhase","from":["ActualEnterprisePhase"],"to":["ResourceArchitecture"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"SameAs","from":["Software"],"to":["Software"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceProvision","from":["ActualResource"],"to":["ActualService"]}],"P2":[{"rel":"ActualProjectConsults","from":["ActualProject"],"to":["Organization"]},{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"ActualProjectInforms","from":["ActualProject"],"to":["Organization"]},{"rel":"CompetenceForRole","from":["ResourceRole"],"to":["Competence"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"IsAccountableFor","from":["Organization"],"to":["ActualProject"]},{"rel":"IsResponsibleFor","from":["Organization"],"to":["ActualProject"]},{"rel":"NeedsService","from":["ActualProject"],"to":["ServiceSpecification"]},{"rel":"ProjectProvidesFunction","from":["ActualProject"],"to":["Function"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"SameAs","from":["Software"],"to":["Software"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"P3":[{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ResourceConnector","from":["ResourcePort"],"to":["ResourcePort"]},{"rel":"SameAs","from":["Software"],"to":["Software"]}],"P4":[{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"P5":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"P6":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"P7":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"P8":[{"rel":"FillsPost","from":["ActualPerson"],"to":["ActualPost"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"Pr":[{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"OwnedMilestone","from":["ActualProject"],"to":["ActualProjectMilestone"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"VersionSuccession","from":["VersionOfConfiguration"],"to":["VersionOfConfiguration"]}],"R2":[{"rel":"PartOfCatalogue","from":["RequirementCategory"],"to":["RequirementCatalogue"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"R3":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"R7":[{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"R8":[{"rel":"Evaluates","from":["FulfilmentCriterion"],"to":["FitCriterion"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"Rr":[{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"ProvidesServiceFunction","from":["ServiceInterface"],"to":["ServiceFunction"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"SameAs","from":["Software"],"to":["Software"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"S1":[{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"S2":[{"rel":"ConsumedBy","from":["ServiceSpecification"],"to":["OperationalPerformer"]},{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"HostedOn","from":["ResourceArchitecture"],"to":["ResourceArchitecture"]},{"rel":"PropertySetGeneralization","from":["CapabilityConfiguration"],"to":["CapabilityConfiguration"]},{"rel":"Provides","from":["OperationalPerformer"],"to":["ServiceSpecification"]},{"rel":"ProvidesServiceFunction","from":["ServiceInterface"],"to":["ServiceFunction"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"SameAs","from":["Software"],"to":["Software"]},{"rel":"ServiceConnector","from":["ServicePort"],"to":["ServicePort"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"S3":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceConnector","from":["ServicePort"],"to":["ServicePort"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"S4":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"S5":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"S6":[{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]}],"S7":[{"rel":"ProvidesServiceFunction","from":["ServiceInterface"],"to":["ServiceFunction"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}],"S8":[{"rel":"EnvironmentalContext","from":["Measurement"],"to":["ActualCondition"]},{"rel":"JustifiedBy","from":["OperationalConstraint"],"to":["Reference"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ReplaceStandardElement","from":["Reference"],"to":["Reference"]}],"Sr":[{"rel":"ActualProjectDependency","from":["ActualProject"],"to":["ActualProject"]},{"rel":"MilestoneDependency","from":["ActualProjectMilestone"],"to":["ActualProjectMilestone"]},{"rel":"NeedsService","from":["ActualProject"],"to":["ServiceSpecification"]},{"rel":"OwnedMilestone","from":["ActualProject"],"to":["ActualProjectMilestone"]},{"rel":"ProjectSequence","from":["ActualProject"],"to":["ActualProject"]},{"rel":"RefersTo","from":["Recommendation"],"to":["Finding"]},{"rel":"ServiceExchange","from":["ServiceSpecification"],"to":["ServiceSpecification"]},{"rel":"ServiceGeneralization","from":["ServiceSpecification"],"to":["ServiceSpecification"]}]}};
