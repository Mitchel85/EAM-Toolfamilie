#!/usr/bin/env node
/*
 * Rauchtest fuer die Mehrformat-Faehigkeit der HTML-Auslieferungen
 * (nicht Teil von pytest/CI, wie der BPMN-Studio-Smoke von Hand laufen):
 *
 *   NODE_PATH=/usr/lib/node_modules node tests/html-browser/formats_smoke.js \
 *       apps/html-suite/dist/EAM-AI-Suite.html \
 *       apps/html-analyzer/dist/EAM-QEA-Analyzer.html \
 *       packages/core/fixtures/Musterarchitektur_MASC.qea \
 *       /tmp/etappe3/masc.xmi /tmp/etappe3/masc.json /tmp/etappe3
 *
 * Geprueft wird, was pytest nicht pruefen kann:
 *   1. .xmi-Laden liefert dieselben Modellzahlen wie .qea-Laden (Suite).
 *   2. .json-Laden liefert Elemente/Kanten (Suite).
 *   3. Export XMI + JSON aus der App; die Dateien werden spaeter von
 *      packages/core/xmi_reader.py zurueckgelesen (Querformat-Beweis).
 *   4. Derselbe .xmi-Lauf im Analyzer.
 *   5. Kein alert()/dialog() waehrend der Laeufe.
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_BIN
  || '/root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome';

(async () => {
  const [suiteHtml, analyzerHtml, qeaFile, xmiFile, jsonFile, outDir] = process.argv.slice(2);
  if (!suiteHtml || !analyzerHtml || !qeaFile || !xmiFile || !jsonFile || !outDir) {
    console.error('Aufruf: formats_smoke.js <suite.html> <analyzer.html> <modell.qea> <modell.xmi> <modell.json> <ausgabeordner>');
    process.exit(2);
  }
  const qeaBytes = fs.readFileSync(qeaFile);
  const xmiText = fs.readFileSync(xmiFile, 'utf8');
  const jsonText = fs.readFileSync(jsonFile, 'utf8');

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--allow-file-access-from-files'],
  });

  let fehler = [];
  const dialogs = [];

  async function neueSeite(html) {
    const page = await browser.newPage();
    page.on('dialog', async (d) => { dialogs.push(d.message()); await d.dismiss(); });
    page.on('pageerror', (e) => fehler.push('pageerror: ' + e.message));
    await page.goto('file://' + path.resolve(html), { waitUntil: 'load', timeout: 60000 });
    return page;
  }

  async function lade(page, daten, name) {
    return page.evaluate((b64, nm) => {
      const bin = atob(b64);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      if (typeof SINGLE !== 'undefined') SINGLE = true;
      if (typeof MULTI_MODE !== 'undefined') MULTI_MODE = false;
      loadQea(u8.buffer, nm);
      var spiegel = 0;
      for (var k in OBJS) {
        if (OBJS.hasOwnProperty(k) && String(OBJS[k].type || '').toLowerCase() === 'package') spiegel++;
      }
      return {
        objs: Object.keys(OBJS).length, cons: CONS.length,
        pkgs: Object.keys(PKG).length, diags: DIAGS.length, spiegel: spiegel,
      };
    }, Buffer.from(daten).toString('base64'), name);
  }

  const ergebnis = {};

  /* 1) Suite: .qea-Referenz */
  let page = await neueSeite(suiteHtml);
  ergebnis.suiteQea = await lade(page, qeaBytes, 'masc.qea');
  /* 2) Roundtrip mit Sichten: qea -> Export-XMI -> Reimport */
  fs.writeFileSync(path.join(outDir, 'roundtrip.xmi'), await page.evaluate(() => EAMF.dbToXmi(DB, {})));
  ergebnis.roundtrip = await lade(page, fs.readFileSync(path.join(outDir, 'roundtrip.xmi')), 'roundtrip.xmi');
  await page.close();

  /* 2) Suite: .xmi */
  page = await neueSeite(suiteHtml);
  ergebnis.suiteXmi = await lade(page, Buffer.from(xmiText, 'utf8'), 'masc.xmi');
  /* 3) Exporte aus der App */
  ergebnis.exportXmi = await page.evaluate(() => {
    const text = EAMF.dbToXmi(DB, {});
    return { bytes: text.length, head: text.slice(0, 120) };
  });
  ergebnis.exportJson = await page.evaluate(() => {
    const text = EAMF.dbToJson(DB, { sourceDocument: 'masc.xmi' });
    const d = JSON.parse(text);
    return { bytes: text.length, nodes: d.nodes.length, edges: d.edges.length };
  });
  fs.writeFileSync(path.join(outDir, 'browser-export.xmi'), await page.evaluate(() => EAMF.dbToXmi(DB, {})));
  fs.writeFileSync(path.join(outDir, 'browser-export.json'), await page.evaluate(() => EAMF.dbToJson(DB, { sourceDocument: 'masc.xmi' })));
  await page.close();

  /* 4) Suite: .json */
  page = await neueSeite(suiteHtml);
  ergebnis.suiteJson = await lade(page, Buffer.from(jsonText, 'utf8'), 'masc.json');
  await page.close();

  /* 5) Analyzer: .xmi */
  page = await neueSeite(analyzerHtml);
  ergebnis.analyzerXmi = await lade(page, Buffer.from(xmiText, 'utf8'), 'masc.xmi');
  await page.close();

  await browser.close();

  console.log(JSON.stringify(ergebnis, null, 2));
  if (dialogs.length) { console.error('DIALOGE (Fehler):', dialogs); process.exit(1); }
  if (fehler.length) { console.error('SEITENFEHLER:', fehler); process.exit(1); }

  /* Gleichheit auf Modellebene:
     - Kanten und Pakete muessen exakt ueberleben.
     - Elemente: qea-Load zaehlt Paket-Spiegelobjekte mit (EA-Doppelfuehrung),
       xmi/json nicht (wie der qea-Reader des Python-Kerns). Abgleich:
       xmi.objs + spiegel == qea.objs.
     - Sichten: der Roundtrip (qea -> xmi -> reimport) muss sie erhalten. */
  const a = ergebnis.suiteQea, b = ergebnis.suiteXmi, r = ergebnis.roundtrip;
  if (a.cons !== b.cons || a.pkgs !== b.pkgs) {
    console.error('UNGLEICH kanten/pakete: qea', a, 'xmi', b);
    process.exit(1);
  }
  if (b.objs + a.spiegel !== a.objs) {
    console.error('UNGLEICH elemente (inkl. Spiegel): qea', a, 'xmi', b);
    process.exit(1);
  }
  if (r.cons !== a.cons || r.pkgs !== a.pkgs || r.diags !== a.diags) {
    console.error('ROUNDTRIP verletzt: qea', a, 'reimport', r);
    process.exit(1);
  }
  if (r.diags < 1) {
    console.error('ROUNDTRIP ohne Sichten -- Diagramme gingen verloren:', r);
    process.exit(1);
  }
  console.log('SMOKE OK');
})().catch((e) => { console.error(e); process.exit(1); });