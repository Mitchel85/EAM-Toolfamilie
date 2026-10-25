"""Waechter der Ein-Quellen-Regel.

Der Test ruft dasselbe Pruefskript auf, das auch die CI ausfuehrt. Damit kann
die Regel nicht nur in der Pipeline, sondern auch lokal nicht umgangen werden.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKRIPT = ROOT / "scripts" / "check_single_source.py"


def test_ein_leser_eine_wissensbasis() -> None:
    ergebnis = subprocess.run(
        [sys.executable, str(SKRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr


def test_parser_liegt_am_kanonischen_ort() -> None:
    assert (ROOT / "packages" / "rules" / "mdg_parser.py").is_file()
    assert not (ROOT / "packages" / "core" / "mdg_parser.py").exists()


def test_dokumente_lesen_kein_xml() -> None:
    text = (ROOT / "packages" / "rules" / "documents.py").read_text(encoding="utf-8")
    for verboten in ("import xml", "from xml", "lxml", "ElementTree"):
        assert verboten not in text, verboten
