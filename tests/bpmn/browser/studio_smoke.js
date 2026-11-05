#!/usr/bin/env node
/*
 * Rauchtest fuer die HTML-Auslieferung (nicht Teil von pytest/CI).
 *
 *   NODE_PATH=/usr/lib/node_modules node tests/bpmn/browser/studio_smoke.js \
 *       apps/bpmn-studio/dist/BPMN-Studio.html /tmp/probe.bpmn
 *
 * Voraussetzungen: node, puppeteer, ein Chromium-Binary. Im CI fehlen diese;
 * die Pruefung laeuft deshalb von Hand und schreibt ihr Ergebnis in den Bericht.
 *
 * Geprueft wird, was pytest nicht pruefen kann:
 *   1. Die Einzeldatei oeffnet offline -- keine Anfrage verlaesst file:/data:.
 *   2. bpmn-js (dieselbe Engine wie bpmn.io) liest das erzeugte BPMN-XML.
 *   3. Der Editor gibt XML und SVG wieder heraus (Promise-API von bpmn-js 18).
 *   4. Das Pruefpanel laeuft ohne Ausnahme.
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_BIN
  || '/root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome';

(async () => {
  const seite = process.argv[2];
  const bpmn = process.argv[3];
  if (!seite || !bpmn) {
    console.error('Aufruf: node studio_smoke.js <BPMN-Studio.html> <modell.bpmn>');
    process.exit(2);
  }
  const xml = fs.readFileSync(bpmn, 'utf8');

  const browser = await puppeteer.launch({
    headless: true,
    executablePath: CHROME,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  });
  const page = await browser.newPage();
  const aussen = [];
  const fehler = [];
  page.on('request', (r) => {
    const u = r.url();
    if (!/^(data:|file:|about:|blob:)/.test(u)) aussen.push(u);
  });
  page.on('pageerror', (e) => fehler.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') fehler.push('console: ' + m.text()); });

  await page.goto('file://' + path.resolve(seite), { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForFunction('window.BPMNStudio && window.BPMNStudio.modeler', { timeout: 30000 });

  const ergebnis = await page.evaluate(async (xml) => {
    const modeler = window.BPMNStudio.modeler();
    const aus = {};
    await modeler.importXML(xml);
    const alle = modeler.get('elementRegistry').getAll();
    aus.elemente = alle.length;
    aus.typen = alle.reduce((a, e) => { a[e.type] = (a[e.type] || 0) + 1; return a; }, {});
    const gespeichert = await modeler.saveXML({ format: true });
    aus.xml = gespeichert.xml;
    const svg = await modeler.saveSVG();
    aus.svgBytes = svg.svg.length;
    try { aus.befunde = window.BPMNStudio.pruefe().length; }
    catch (e) { aus.pruefFehler = String(e); }
    aus.version = window.BPMNStudio.version;
    return aus;
  }, xml);

  const { xml: exportiert, ...rest } = ergebnis;
  fs.writeFileSync('/tmp/studio_export.bpmn', exportiert);
  await browser.close();

  console.log(JSON.stringify({
    ...rest,
    exportBytes: exportiert.length,
    externeAnfragen: aussen,
    seitenfehler: fehler,
  }, null, 1));
})().catch((e) => { console.error('FEHLER', e); process.exit(1); });
