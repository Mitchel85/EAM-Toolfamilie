"""Prüft: steht irgendwo im Anwendungscode ein Element aus einem Testmodell?

Quelle der Namen ist ein Modell (.qea), das nur als Prüfgrundlage dient.
Geprüft wird ausschließlich Anwendungscode -- keine Fixtures, keine Tests,
keine gebauten Dateien.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

QUELLE = Path(sys.argv[1] if len(sys.argv) > 1 else '/root/hermes-workspace/admbw-qea-editor/Musterarchitektur_MASC.qea')
WURZEL = Path('/root/hermes-workspace/eam-platform')
AUSGABE = Path(sys.argv[2] if len(sys.argv) > 2 else '/root/.hermes/cache/scratch/leak_report.json')

#: Sprechende Namen des Testmodells: mehr als ein Wort oder ein Kunstwort.
#: Fachbegriffe des Metamodells (Stereotypen, EA-Spalten) zaehlen nicht --
#: sie stammen aus der Technologie, nicht aus dem Modell.
TECHNISCH = {
    'Software', 'Information', 'Organisation', 'Organization', 'Functions',
    'Capabilities', 'Dimension', 'Transport', 'Position', 'Struktur', 'Architekt',
    'Viewpoints', 'Standards', 'Protocols', 'Framework', 'EnterpriseGoal',
    'EnterpriseVision', 'MeasurandType', 'MeasurementType', 'OperationalPerformer',
    'Modellelementekatalog', 'Referenzarchitektur', 'Systemarchitektur',
    'Bundeswehr', 'required', 'provided', 'gespeichert', 'vergleichen', 'Meldung',
    'Bericht', 'Katalog', 'Einheit', 'Fähigkeit', 'Wirkung', 'Betrieb', 'Nachricht',
    'Spezialist', 'Ebene 1', 'Antriebsmodul', 'Antriebsmodule',
}

con = sqlite3.connect(f'file:{QUELLE}?mode=ro', uri=True)
namen = sorted({
    str(name).strip()
    for (name,) in con.execute(
        "select Name from t_object where Name is not null and length(trim(Name)) >= 6"
    )
})
spezifisch = [
    n for n in namen
    if n not in TECHNISCH
    and (' ' in n or re.search(r'[a-zäöüß]', n))
    and not re.fullmatch(r'[\d\s.,:/%GBit\-\+a-zA-Z]*', n)
]
print(f'Prüfnamen aus {QUELLE.name}: {len(spezifisch)}')

MUSTER = re.compile('|'.join(re.escape(n) for n in sorted(spezifisch, key=len, reverse=True)))
DATEIENDUNGEN = {'.py', '.js', '.html', '.css', '.json', '.toml', '.ys', '.txt', '.md'}
AUSGESCHLOSSEN = ('/fixtures/', '/dist/', '/node_modules/', '/.git/', '/tests/',
                  '/build/', '/vendor/', '/__pycache__/', '/CHANGELOG')

treffer: dict[str, list[str]] = {}
for pfad in sorted(WURZEL.rglob('*')):
    if not pfad.is_file() or pfad.suffix not in DATEIENDUNGEN:
        continue
    text_p = str(pfad)
    if any(teil in text_p for teil in AUSGESCHLOSSEN):
        continue
    if pfad.name.startswith(('Musterarchitektur', 'MASC')):
        continue
    try:
        inhalt = pfad.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        continue
    gefunden = sorted(set(MUSTER.findall(inhalt)))
    if gefunden:
        treffer[str(pfad.relative_to(WURZEL))] = gefunden[:12]

AUSGABE.parent.mkdir(parents=True, exist_ok=True)
AUSGABE.write_text(json.dumps(treffer, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'Dateien mit Treffern: {len(treffer)}')
for datei, namen_gefunden in list(treffer.items())[:10]:
    print(f'  {datei}: {namen_gefunden}')
print(f'Bericht: {AUSGABE}')
