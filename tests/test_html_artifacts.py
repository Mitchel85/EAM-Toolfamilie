"""Die beiden HTML-Auslieferungen sind eigenständige Altwerkzeuge.

Kein gemeinsamer UI-Kern, keine per CSS versteckten Reiter: Jede Datei hat
ihren eigenen Quellstand, ihre eigene Größe, ihren eigenen Titel und ihre
eigenen Funktionsmarker. Der Test baut beide aus den Quellen und prüft
genau das.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    "html-suite": {
        "product": "EAM AI Suite",
        "version": "v9.1",
        "title": "EAM AI Suite — QEA-Architekturen analysieren, erkunden, bearbeiten &amp; exportieren",
        "bytes": 3_708_273,
        "min_size": 3_000_000,
        "max_size": 4_000_000,
        "markers": ("window.KI", "var EDIT =", "var MERGE", "var STDIMPORT =", "function openAny(", "function exportXmi(", "syncToApp", "applyLive"),
        "forbidden": (),
    },
    "html-editor": {
        "product": "EAM Suite",
        "version": "v8.6",
        "title": "EAM Suite — QEA-Architekturen analysieren, erkunden, bearbeiten &amp; exportieren",
        "bytes": 1_553_338,
        "min_size": 1_000_000,
        "max_size": 2_000_000,
        "markers": ("var EDIT =", "var MERGE", "var ISSUE =", "var STDIMPORT =", "function openAny(", "function exportXmi("),
        "forbidden": ("window.KI", "var DIAG =", "BPMN.modus", "part7_bpmn", "buildArchitectureWithViews"),
    },
    "html-sichten-archiv": {
        "product": "Sichten-Archiv",
        "version": "v1.0",
        "title": "Sichten-Archiv — QEA verkleinern ohne Datenverlust",
        "bytes": 952_631,
        "min_size": 700_000,
        "max_size": 1_500_000,
        "markers": ("Sichten-Archiv", "t_diagram", "t_diagramobjects", "t_diagramlinks"),
        "forbidden": ("window.KI",),
    },
}


def _manifest(app: str) -> dict:
    return json.loads((ROOT / "apps" / app / "app.json").read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def gebaut() -> dict[str, dict]:
    ergebnis: dict[str, dict] = {}
    for app in APPS:
        subprocess.run(
            [sys.executable, "scripts/build_legacy_app.py", f"apps/{app}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        manifest = _manifest(app)
        html = ROOT / "apps" / app / "dist" / manifest["output"]
        aspx = ROOT / "apps" / app / "dist" / manifest["aspx"]
        ergebnis[app] = {"html": html, "aspx": aspx, "manifest": manifest}
    # Die englische Fassung gehört zum Manifest und wird wie in der CI
    # mitgebaut; der danach erneute Alt-Bau stellt den deutschen Stand her
    # und räumt die Arbeitsdateien des Übersetzungslaufs auf.
    subprocess.run(
        [sys.executable, "apps/html-editor/build_english.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "scripts/build_legacy_app.py", "apps/html-editor"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return ergebnis


def test_bau_ist_deterministisch(gebaut: dict[str, dict]) -> None:
    for app, dateien in gebaut.items():
        vorher = _sha(dateien["html"])
        subprocess.run(
            [sys.executable, "scripts/build_legacy_app.py", f"apps/{app}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert _sha(dateien["html"]) == vorher, f"{app}: zwei Bauten unterscheiden sich"


def test_zwei_verschiedene_werkzeuge(gebaut: dict[str, dict]) -> None:
    groessen = {app: d["html"].stat().st_size for app, d in gebaut.items()}
    hashes = {app: _sha(d["html"]) for app, d in gebaut.items()}
    assert len(set(hashes.values())) == len(APPS)
    assert max(groessen.values()) > 2 * min(groessen.values())
    for app, regeln in APPS.items():
        assert regeln["min_size"] <= groessen[app] <= regeln["max_size"], app
    assert groessen["html-sichten-archiv"] < groessen["html-editor"] < groessen["html-suite"]


def test_titel_und_versionen(gebaut: dict[str, dict]) -> None:
    for app, regeln in APPS.items():
        text = gebaut[app]["html"].read_text(encoding="utf-8")
        assert f"<title>{regeln['title']}</title>" in text, app
        assert regeln["version"] in text, app
        assert "(EXPERIMENTELL)" not in text.split("</h1>", 1)[0], app


def test_groessen_sind_festgehalten(gebaut: dict[str, dict]) -> None:
    for app, regeln in APPS.items():
        assert gebaut[app]["html"].stat().st_size == regeln["bytes"], app


def test_funktionsmarker_sind_getrennt(gebaut: dict[str, dict]) -> None:
    for app, regeln in APPS.items():
        text = gebaut[app]["html"].read_text(encoding="utf-8")
        for marker in regeln["markers"]:
            assert marker in text, f"{app}: Marker fehlt: {marker}"
        for marker in regeln["forbidden"]:
            assert marker not in text, f"{app}: verbotener Marker vorhanden: {marker}"


def test_suite_legt_modelle_zusammen(gebaut: dict[str, dict]) -> None:
    """Die Suite kann an ein vorhandenes Modell anknuepfen (Name + Stereotyp)."""
    text = gebaut["html-suite"]["html"].read_text(encoding="utf-8")
    assert "function mergeModels(" in text
    assert "mergeModels: mergeModels" in text
    assert 'id="ki-continue"' in text
    assert "An vorhandenes Modell anknüpfen" in text


def test_aspx_hat_bom_und_gleichen_inhalt(gebaut: dict[str, dict]) -> None:
    for app, dateien in gebaut.items():
        roh = dateien["aspx"].read_bytes()
        assert roh[:3] == b"\xef\xbb\xbf", app
        assert roh[3:] == dateien["html"].read_bytes(), app


def test_keine_externen_ressourcen(gebaut: dict[str, dict]) -> None:
    for app, dateien in gebaut.items():
        text = dateien["html"].read_text(encoding="utf-8")
        assert not re.search(r"""(?:src|href)\s*=\s*['"]?https?://""", text, re.I), app
        assert not re.search(r"url\(\s*https?://", text, re.I), app


def test_herkunft_steht_im_manifest() -> None:
    for app in APPS:
        manifest = _manifest(app)
        assert manifest["sourceRepo"].startswith("Mitchel85/")
        assert len(manifest["sourceCommit"]) == 7
        assert manifest["kind"] == "standalone"
        assert manifest["sourceNote"], app


def test_quellbaum_ist_unveraendert() -> None:
    for app in APPS:
        manifest = _manifest(app)
        digest = hashlib.sha256()
        dateien = sorted(
            p for p in (ROOT / "apps" / app / "src").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        for pfad in dateien:
            digest.update(pfad.relative_to(ROOT / "apps" / app).as_posix().encode())
            digest.update(b"\0")
            digest.update(pfad.read_bytes())
        assert digest.hexdigest() == manifest["sourceTreeSha256"], app


def test_kein_gemeinsamer_ui_kern_mehr() -> None:
    assert not (ROOT / "packages" / "ui").exists()
    for app in APPS:
        manifest = _manifest(app)
        assert "tabs" not in manifest
        assert "allowCreate" not in manifest
        assert manifest["output"] != manifest["aspx"]


def test_app_dist_enthaelt_nur_das_manifest(gebaut: dict[str, dict]) -> None:
    for app, dateien in gebaut.items():
        extra = set(dateien["manifest"].get("extra", []))
        erlaubt = {dateien["html"].name, dateien["aspx"].name} | extra
        vorhanden = {p.name for p in (ROOT / "apps" / app / "dist").iterdir()}
        assert vorhanden == erlaubt, f"{app}: {sorted(vorhanden - erlaubt)}"


def test_suite_laedt_standardelemente(gebaut: dict[str, dict]) -> None:
    """Katalog laden und zuordnen: die Kennung kommt aus dem Katalog, nie berechnet."""
    html = gebaut["html-suite"]["html"].read_text(encoding="utf-8")
    assert "function loadCatalogBytes(" in html
    assert "loadCatalogBytes: loadCatalogBytes" in html
    assert 'id="ki-katalog-file"' in html
    assert "Katalog laden" in html
    assert "STANDARDELEMENTE AUS DEM KATALOG" in html


def test_suite_arbeitet_iterativ_mit_pause_und_fortsetzung(gebaut: dict[str, dict]) -> None:
    """Lange Texte laufen abschnittsweise, mit Pause und gespeichertem Laufstand."""
    html = gebaut["html-suite"]["html"].read_text(encoding="utf-8")
    for marker in (
        'id="ki-pause"',
        'id="ki-charge"',
        "function pauseSekunden()",
        "function inTeilenHolen(set, sysMsg, text, grenze, pause)",
        "function runSpeichern(",
        "function runLaden(",
        "Zugriffslimit/Serverfehler",
        "resetRun: resetRun",
    ):
        assert marker in html, marker


def test_editor_issue_writer_schreibt_befunde_in_qea(gebaut: dict[str, dict], tmp_path: Path) -> None:
    """Der Befund-Schreiber (part5b_issue.js) legt Issue-Elemente und betrifft-Kanten an."""
    import os

    env = dict(os.environ, ISSUE_TEST_OUT_DIR=str(tmp_path))
    ergebnis = subprocess.run(
        ["node", "apps/html-editor/test_issue_writer.js"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    daten = json.loads(ergebnis.stdout.strip().splitlines()[-1])
    assert daten["angelegt"] == 2
    assert Path(daten["datei"]).is_file()


def test_natives_archimate_vermeidet_mdg_fehlalarme(gebaut: dict[str, dict]) -> None:
    """Native ArchiMate-3.2-Modelle werden erkannt und nicht gegen ADMBw/UAF-MDG geprüft."""
    for app in ("html-suite", "html-editor"):
        html = gebaut[app]["html"].read_text(encoding="utf-8")
        assert "dbArch.__x.nativeArchimate = isNativeArchimate;" in html, app
        assert "var isNativeArchimate =" in html, app
        assert "eam-ai archimate-check" in html, app


def test_suite_chat_live_sync_und_nl_ausbau(gebaut: dict[str, dict]) -> None:
    """Nach dem KI-Bau: Live-Sync in die App, Direkt-Buttons, Chat with Data & NL-Ausbau."""
    html = gebaut["html-suite"]["html"].read_text(encoding="utf-8")
    for marker in (
        "function syncToApp(",
        "function openInTab(",
        "KI.openInTab('qa')",
        "KI.openInTab('graph')",
        "KI.openInTab('qs')",
        "function applyLive(",
        "NL.applyLive()",
        "op.op === 'add_package'",
        "op.op === 'add_element'",
    ):
        assert marker in html, f"Suite-Marker fehlt: {marker}"


