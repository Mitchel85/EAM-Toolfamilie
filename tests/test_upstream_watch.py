"""Tests für scripts/upstream_watch.py (hermetisch, ohne Netz)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKRIPT = ROOT / "scripts" / "upstream_watch.py"


def _modul():
    spec = importlib.util.spec_from_file_location("upstream_watch", SKRIPT)
    assert spec and spec.loader
    modul = importlib.util.module_from_spec(spec)
    sys.modules["upstream_watch"] = modul
    spec.loader.exec_module(modul)
    return modul


BW_HTML = """
<html><body>
<a href="/resource/blob/5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip">MDG</a>
<a href="/resource/blob/6117920/173e5ae1cba4a5fca196742440899a79/release-notes-admbw--data.pdf">Notizen</a>
</body></html>
"""

NATO_HTML = """
<html><body>
<a href="/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-v4-1-en.pdf">NAFv4.1</a>
<a href="/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-ArchiMate-v4-1-en.pdf">ArchiMate</a>
</body></html>
"""


def test_erkennt_bw_und_nato_ohne_aenderung(tmp_path: Path) -> None:
    m = _modul()
    fetch = tmp_path / "fetch_quellen.py"
    fetch.write_text(
        'DATEIEN = [\n'
        '    ("admbw-mdg.zip", "5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip"),\n'
        '    ("rn.pdf", "6117920/173e5ae1cba4a5fca196742440899a79/release-notes-admbw--data.pdf"),\n'
        ']\n',
        encoding="utf-8",
    )
    nato_meta = {
        "https://www.nato.int/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-v4-1-en.pdf": {
            "etag": '"e1"', "last_modified": "Mon, 16 Mar 2026 15:16:57 GMT", "content_length": "100",
        },
        "https://www.nato.int/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-ArchiMate-v4-1-en.pdf": {
            "etag": '"e2"', "last_modified": "Mon, 29 Jun 2026 08:09:38 GMT", "content_length": "200",
        },
    }
    snap_alt = {
        "bw": m.bw_baseline_aus_fetch(fetch),
        "nato": {
            k.removeprefix("https://www.nato.int"): v for k, v in nato_meta.items()
        },
    }

    def fake_get(url: str) -> str:
        return BW_HTML if "bundeswehr.de" in url else NATO_HTML

    code, bericht, _snap = m.pruefe_alle(
        letzter_snapshot=snap_alt,
        lade_text_fn=fake_get,
        head_fn=lambda u: nato_meta[u],
        fetch_path=fetch,
    )
    assert code == 0
    assert bericht == ""


def test_pingt_bei_neuer_mdg_und_neuem_nato_pdf_und_dedupliziert(tmp_path: Path) -> None:
    m = _modul()
    fetch = tmp_path / "fetch_quellen.py"
    fetch.write_text(
        'DATEIEN = [\n'
        '    ("admbw-mdg.zip", "5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip"),\n'
        '    ("rn.pdf", "6117920/173e5ae1cba4a5fca196742440899a79/release-notes-admbw--data.pdf"),\n'
        ']\n',
        encoding="utf-8",
    )
    bw_neu = BW_HTML.replace("86b87446ff3b144de324f1dde2d85521", "1" * 32)
    nato_neu = NATO_HTML + '<a href="/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-v4-2-en.pdf">v4.2</a>'

    def fake_get(url: str) -> str:
        return bw_neu if "bundeswehr.de" in url else nato_neu

    def fake_head(url: str) -> dict[str, str]:
        return {"etag": '"new"', "last_modified": "Mon, 01 Dec 2026 09:00:00 GMT", "content_length": "999"}

    code, bericht, _snap = m.pruefe_alle(
        letzter_snapshot={},
        lade_text_fn=fake_get,
        head_fn=fake_head,
        fetch_path=fetch,
    )
    assert code == 2
    assert "@Mitchel85" in bericht
    assert "admbw-mdg-nafv4--data.zip" in bericht
    assert "mdg-uebernehmen" in bericht
    assert "NATO-Architecture-Framework-v4-2-en.pdf" in bericht

    # Zweiter Lauf mit dem Snapshot aus dem ersten Issue-Body darf nicht erneut pingen!
    extr = m.extrahiere_snapshot(bericht)
    assert "bw" in extr and "nato" in extr
    code2, bericht2, _snap2 = m.pruefe_alle(
        letzter_snapshot=extr,
        lade_text_fn=fake_get,
        head_fn=fake_head,
        fetch_path=fetch,
    )
    assert code2 == 0
    assert bericht2 == ""


def test_keine_falschmeldungen_bei_teilweisem_netzausfall(tmp_path: Path) -> None:
    m = _modul()
    fetch = tmp_path / "fetch_quellen.py"
    fetch.write_text(
        'DATEIEN = [\n'
        '    ("admbw-mdg.zip", "5570648/86b87446ff3b144de324f1dde2d85521/admbw-mdg-nafv4--data.zip"),\n'
        '    ("rn.pdf", "6117920/173e5ae1cba4a5fca196742440899a79/release-notes-admbw--data.pdf"),\n'
        ']\n',
        encoding="utf-8",
    )

    def fake_get(url: str) -> str:
        if "nato.int" in url:
            raise OSError("timeout")
        return BW_HTML

    code, bericht, _snap = m.pruefe_alle(
        letzter_snapshot={},
        lade_text_fn=fake_get,
        fetch_path=fetch,
    )
    assert code == 0
    assert bericht == ""
