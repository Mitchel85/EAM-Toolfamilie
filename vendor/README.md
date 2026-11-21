# Vendor

Kanonische Kopien der Browser-Bibliotheken, die die HTML-Werkzeuge einbetten.
Die Apps führen eigene Kopien, weil ihre Builds offline und ohne Paketmanager
laufen; `scripts/sync_vendor.py` hält sie byte-gleich.

| Datei | Verbraucher |
|---|---|
| `sql-wasm.js`, `sql-wasm.wasm`, `LICENSE-sql.js` | EAM AI Suite, EAM Suite, Sichten-Archiv |
| `eam-formats.js` | EAM AI Suite, EAM Suite |
| `pdf.min.js`, `pdf.worker.min.js`, `LICENSE-pdfjs.txt` | EAM AI Suite, BPMN Studio |
| `jszip.min.js` | EAM AI Suite |
| `bpmn-js/` | BPMN Studio |

Änderung hier: `python3 scripts/sync_vendor.py --write`, danach die
HTML-Werkzeuge neu bauen. `python3 scripts/sync_vendor.py --check` meldet jede
Abweichung; die CI führt diesen Schritt aus.
