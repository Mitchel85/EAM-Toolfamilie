"""Keine dienstlichen E-Mail-Adressen im Repository.

Festgehalten wird die Regel, die für die Veröffentlichung gilt: die
dienstliche Absenderadresse der Quelldokumente darf nirgends im Repository
stehen — auch nicht in Tests oder Dokumentation. Ersetzt wird sie durch den
Neutralwert `support@example.invalid` (siehe `scripts/regelwerk_update.py`).

Geprüft werden nur getrackte Textdateien; die Quell-PDFs liegen ohnehin nicht
im Repository (`.gitignore: knowledge/leitfaden/*.pdf`).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: E-Mail-Muster mit dem Domain-Anteil der Dienststelle.
DIENSTLICH = re.compile(r"[\w.+-]+@[\w.-]*bundeswehr\.(de|org)")


def test_keine_dienstlichen_adressen_im_arbeitsbaum() -> None:
    ergebnis = subprocess.run(
        ["git", "grep", "-nI", "-E", r"[\w.+-]+@[\w.-]*bundeswehr\.(de|org)"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    treffer = [z for z in ergebnis.stdout.splitlines() if z.strip()]
    assert treffer == [], "dienstliche Adressen gefunden:\n" + "\n".join(treffer)