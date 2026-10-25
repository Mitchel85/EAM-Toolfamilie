"""Entscheidungshilfe: welcher der beiden MDG-Leser wird der kanonische?

Beide lesen dieselbe XML, liefern aber unterschiedliche Dinge. Verglichen wird
deshalb nicht Zeilenzahl, sondern Verhalten an denselben Eingaben:

* echte MDG (NAFv4-ADMBw-2026.05)
* ein zweiter, fremder Technologie-Auszug (kein ADMBw)
* kaputte Eingaben (leer, kein XML, fremde Wurzel, abgeschnitten)

Wer mehr Eingaben sicher verarbeitet und bei Fehlern sauber meldet, gewinnt.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "packages" / "rules" / "mdg_parser.py"
CORE = ROOT / "packages" / "core" / "mdg_parser.py"
if str(ROOT / "packages" / "rules") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "rules"))
import mdg_source  # noqa: E402  (bewusst nach dem Pfad-Aufbau)

MDG = mdg_source.path()
FREMD = ROOT / "packages" / "core" / "fixtures" / "fremd_klein.xml"


def lauf(parser: Path, eingabe: Path, out: Path) -> tuple[int, str, list[str]]:
    cmd = [sys.executable, str(parser), str(eingabe), "-o", str(out), "--no-timestamp"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dateien = sorted(p.name for p in out.iterdir()) if out.is_dir() else []
    return proc.returncode, (proc.stdout + proc.stderr).strip()[:200], dateien


def kern_lauf(eingabe: Path, out: Path) -> tuple[int, str, int]:
    """Der Kern-Parser gibt JSON aus; hier zaehlen wir Stereotype."""
    sys.path.insert(0, str(ROOT / "packages" / "core"))
    import importlib

    modul = importlib.import_module("mdg_parser")
    try:
        rules = modul.parse_mdg(eingabe)
    except Exception as exc:  # noqa: BLE001 - Fehlerarten sind Teil des Vergleichs
        return 2, f"{type(exc).__name__}: {exc}"[:200], 0
    anzahl = len(rules.get("elementStereotypes") or [])
    return 0, "ok", anzahl


def main() -> int:
    faelle = [("echte MDG", MDG), ("fremde Technologie", FREMD)]
    print(f"{'Fall':22s} {'Dokumente':>26s} {'Regelmodell':>28s}")
    for name, eingabe in faelle:
        with tempfile.TemporaryDirectory() as tmp:
            code, meldung, dateien = lauf(RULES, eingabe, Path(tmp) / "out")
            doku = f"{code} · {len(dateien)} Dateien" if code == 0 else f"{code} · Fehler"
        code2, meldung2, anzahl = kern_lauf(eingabe, Path("/tmp"))
        modell = f"{code2} · {anzahl} Stereotype" if code2 == 0 else f"{code2} · Fehler"
        print(f"{name:22s} {doku:>26s} {modell:>28s}")

    # Fehlerfaelle
    print("\nFehlerverhalten:")
    kaputt = {
        "leere Datei": b"",
        "kein XML": b"das ist kein xml",
        "fremde Wurzel": b"<root><x/></root>",
        "abgeschnitten": MDG.read_bytes()[:5000],
    }
    for name, daten in kaputt.items():
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "in.xml"
            p.write_bytes(daten)
            code, meldung, dateien = lauf(RULES, p, Path(tmp) / "out")
            code2, meldung2, _ = kern_lauf(p, Path("/tmp"))
        print(f"  {name:16s} Dokumente: exit {code}, {len(dateien)} Dateien, {meldung.splitlines()[-1][:60]!r}")
        print(f"  {'':16s} Modell:    exit {code2}, {meldung2[:70]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
