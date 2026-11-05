# bpmn-js — gebündelte Fremdbibliothek

- **Paket:** `bpmn-js` (Modellierer-Auslieferung)
- **Version:** 18.31.1
- **Bezug:** `https://registry.npmjs.org/bpmn-js/-/bpmn-js-18.31.1.tgz`, entpackt am 04.11.2026
- **Dateien:** `bpmn-modeler.production.min.js`, `assets/bpmn-js.css`, `assets/diagram-js.css`, `assets/bpmn-font/*`
- **Lizenz:** MIT, siehe `LICENSE` (Copyright © 2014–present Camunda Services GmbH)

Die Auslieferung bündelt folgende MIT-Komponenten, die im Modellierer-Bundle
enthalten sind: `diagram-js`, `bpmn-moddle`, `moddle`, `moddle-xml`,
`bpmn-js` sowie die Zeichen- und Fontbestandteile von bpmn.io. Die
Lizenzhinweise der bpmn-js-Auslieferung gelten für das Gesamtbundle.

Der Wasserzeichen-Hinweis „bpmn.io“ im Modellierer bleibt sichtbar und
unverändert; das verlangt die Lizenz. Er ist der einzige externe Verweis im
fertigen HTML und wird nicht nachgeladen.

Das fertige `apps/bpmn-studio/index.html` lädt zur Laufzeit **keine** Datei
aus diesem Ordner und **keine** Ressource aus dem Netz: JavaScript, CSS und
Schriften werden beim Bauen eingebettet.
