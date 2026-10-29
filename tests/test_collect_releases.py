"""Release-Manifest: nur ausgelieferte Dateien, Quellstand als Archiv.

Der Fehler, den dieser Test festhält: `SHA256SUMS` listete Dateien, die im
Release gar nicht liegen (README.md, GRAPH.md, der alte Quellordner). Ein
`sha256sum -c` im Download-Ordner scheiterte dadurch. Geprüft wird die
Abdeckung, nicht die Richtigkeit der Hashes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect_releases.py"


def _modul():
    spec = importlib.util.spec_from_file_location("collect_releases", SCRIPT)
    assert spec and spec.loader
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _sums(dist: Path) -> dict[str, str]:
    eintraege: dict[str, str] = {}
    for zeile in (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if zeile.strip():
            digest, name = zeile.split("  ", 1)
            eintraege[name] = digest
    return eintraege


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_nennt_nur_ausgelieferte_dateien(tmp_path: Path) -> None:
    modul = _modul()
    fehlend = [rel for rel, *_ in modul.AUSLIEFERUNGEN if not (ROOT / rel).is_file()]
    if fehlend:
        pytest.skip("Auslieferungen nicht gebaut: " + ", ".join(fehlend))

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "offline").mkdir()
    (dist / "offline" / "eam-ai-2.4.0.zip").write_bytes(b"alt")
    (dist / "wheel").mkdir()
    (dist / "wheel" / "eam_ai-2.4.0-py3-none-any.whl").write_bytes(b"alt")
    (dist / "eam-ai-suite-python").mkdir()
    (dist / "eam-ai-suite-python" / "eam_ai.py").write_bytes(b"alt")
    (dist / "eam-ai-suite-python-2.4.0.zip").write_bytes(b"alt")
    (dist / "README.md").write_text("alter Katalog\n", encoding="utf-8")
    (dist / "GRAPH.md").write_text("alter Graph\n", encoding="utf-8")

    befehl = [sys.executable, str(SCRIPT), "--dist", str(dist), "--version", "9.9.9"]
    subprocess.run(befehl, cwd=ROOT, check=True, capture_output=True, text=True)

    archiv = dist / "eam-ai-suite-python-9.9.9.zip"
    erwartet = {name for _, name, *_ in modul.AUSLIEFERUNGEN} | {
        archiv.name,
        "eam-ai-suite-python.zip",
        "START-HIER.html",
    }
    sums = _sums(dist)
    assert set(sums) == erwartet
    assert "README.md" not in sums and "GRAPH.md" not in sums
    assert len(sums) == len(erwartet)

    # Stabile Kopie für direkte Links; identisch mit dem versionierten Archiv.
    stabil = dist / "eam-ai-suite-python.zip"
    assert stabil.is_file()
    assert _sha256(stabil) == _sha256(archiv)

    # Einstiegsseite: Karten, direkte Links, keine externen Ressourcen.
    start = dist / "START-HIER.html"
    assert start.is_file()
    seite = start.read_text(encoding="utf-8")
    assert seite.count('class="card') == 6
    for datei in (
        "EAM-AI-Suite.html",
        "EAM-Suite.html",
        "EAM-MDG-Parser.html",
        "eam_qea_analyzer_openwebui.py",
        "eam-qea-mcp-server.py",
        "eam-mdg-parser.py",
        "eam-ai-suite-python.zip",
    ):
        assert f"releases/latest/download/{datei}" in seite, datei
    assert "Schnellwahl" in seite

    # Altbestand ist weg, das Manifest kann nicht wieder 84 Einträge erzeugen.
    assert not (dist / "offline").exists()
    assert not (dist / "wheel").exists()
    assert not (dist / "eam-ai-suite-python").exists()
    assert not (dist / "eam-ai-suite-python-2.4.0.zip").exists()

    # Archiv: Quellstand an der Wurzel, installierbar, ohne Zeitstempel.
    with zipfile.ZipFile(archiv) as gepackt:
        namen = gepackt.namelist()
        assert "eam-ai-suite-python/pyproject.toml" in namen
        assert "eam-ai-suite-python/rules.schema.json" in namen
        assert "eam-ai-suite-python/mdg_parser.py" in namen
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in gepackt.infolist())

    # Derselbe Quellstand ergibt dieselben Bytes.
    erst = _sha256(archiv)
    subprocess.run(befehl, cwd=ROOT, check=True, capture_output=True, text=True)
    assert _sha256(archiv) == erst

    # Katalogzeile nennt Archiv, Größe und Hash-Anfang wie die anderen Zeilen.
    katalog = (dist / "README.md").read_text(encoding="utf-8")
    zeile = next(z for z in katalog.splitlines() if z.startswith(f"| `{archiv.name}`"))
    assert f"{archiv.stat().st_size:,}".replace(",", ".") in zeile
    assert f"`{erst[:16]}…`" in zeile
