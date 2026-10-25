"""Die Vendor-Kopien sind aus der kanonischen Quelle abgeleitet."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sync_vendor  # noqa: E402


def test_alle_kanonischen_dateien_sind_zugeordnet() -> None:
    dateien = {
        p.name for p in (ROOT / "vendor").iterdir()
        if p.is_file() and p.name not in {"package.json", "README.md", "LICENSE-pdfjs.txt"}
    }
    zugeordnet = {name for namen in sync_vendor.ZUORDNUNG.values() for name in namen}
    assert dateien == zugeordnet


def test_app_kopien_sind_byte_gleich() -> None:
    for app in sync_vendor.ZUORDNUNG:
        assert sync_vendor.unterschiede(app) == [], app


def test_check_laeuft_ohne_befund() -> None:
    import subprocess

    ergebnis = subprocess.run(
        [sys.executable, "scripts/sync_vendor.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
