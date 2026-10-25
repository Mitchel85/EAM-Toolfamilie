# Vendor

Kanonische Kopien der Browser-Bibliotheken, die die HTML-Werkzeuge einbetten.
Die Apps führen eigene Kopien, weil ihre Builds offline und ohne Paketmanager
laufen; `scripts/sync_vendor.py` hält sie byte-gleich.

| Datei | Verbraucher |
|---|---|
| `sql-wasm.js`, `sql-wasm.wasm` | AI Suite, QEA Analyzer, EAM Suite |
| `pdf.min.js`, `pdf.worker.min.js` | AI Suite |
| `jszip.min.js` | AI Suite |
| `LICENSE-sql.js` | alle drei Apps |

Änderung hier: `python3 scripts/sync_vendor.py --write`, danach die drei
HTML-Werkzeuge neu bauen. `python3 scripts/sync_vendor.py --check` meldet jede
Abweichung; die CI führt diesen Schritt aus.
