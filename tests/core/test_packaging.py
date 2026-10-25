"""Tests fuer das verteilbare Paket: Version, Wheel, Offline-Bundle.

Geprueft wird, was die Definition of Done fordert und was still kaputtgehen
kann: eine auseinandergelaufene Version, ein fehlendes Modul im Wheel, ein
nicht reproduzierbarer Build oder ein Bundle ohne Startskripte.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

import build_backend
import eam_ai
from tools import build_bundle

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
EXAMPLE = ROOT / "examples" / "offline"


def pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_version_has_one_source() -> None:
    project = pyproject()["project"]
    assert eam_ai.__version__ == project["version"], "eam_ai.__version__ und pyproject.toml laufen auseinander"
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(
        rf"^## {re.escape(eam_ai.__version__)} - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE
    )
    assert heading, f"CHANGELOG.md hat keinen Abschnitt fuer {eam_ai.__version__}"


def test_cli_version(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        eam_ai.main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"eam-ai {eam_ai.__version__}"


def test_pyproject_declares_every_core_module() -> None:
    listed = set(pyproject()["tool"]["eam-ai"]["modules"])
    present = {path.stem for path in ROOT.glob("*.py")} - {"conftest", "build_backend"}
    missing = present - listed
    assert not missing, f"Module fehlen in [tool.eam-ai].modules: {sorted(missing)}"
    assert "eam_ai" in listed
    assert pyproject()["project"]["scripts"]["eam-ai"] == "eam_ai:main"
    assert pyproject()["project"]["dependencies"] == []
    assert pyproject()["project"]["requires-python"].startswith(">=3.11")


def test_wheel_contents_and_record(tmp_path: Path) -> None:
    project = pyproject()["project"]
    first = tmp_path / "first"
    second = tmp_path / "second"
    name = build_backend.build_wheel(str(first))
    assert build_backend.build_wheel(str(second)) == name
    wheel = first / name
    assert wheel.read_bytes() == (second / name).read_bytes(), "Wheel ist nicht reproduzierbar"

    modules = pyproject()["tool"]["eam-ai"]["modules"]
    resources = pyproject()["tool"]["eam-ai"]["resources"]
    info = f"{build_backend.dist_name(project)}-{project['version']}.dist-info"

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for module in modules:
            assert f"{module}.py" in names, f"{module}.py fehlt im Wheel"
        for resource in resources:
            assert resource in names, f"{resource} fehlt im Wheel"
        assert f"{info}/entry_points.txt" in names
        entry_points = archive.read(f"{info}/entry_points.txt").decode("utf-8")
        assert "eam-ai = eam_ai:main" in entry_points
        assert f"{info}/METADATA" in names
        assert b"Requires-Python: >=3.11" in archive.read(f"{info}/METADATA")

        record_lines = archive.read(f"{info}/RECORD").decode("utf-8").splitlines()
        recorded: dict[str, tuple[str, str]] = {}
        for line in record_lines:
            path, digest, size = line.rsplit(",", 2)
            recorded[path] = (digest, size)
        assert set(recorded) == names, "RECORD deckt nicht jede Wheel-Datei ab"
        for path, (digest, size) in recorded.items():
            data = archive.read(path)
            if digest:
                algorithm, _, value = digest.partition("=")
                assert algorithm == "sha256"
                expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                assert value == expected, f"RECORD-Hash falsch: {path}"
                assert size == str(len(data)), f"RECORD-Groesse falsch: {path}"
            else:
                assert path.endswith("/RECORD")

        for entry in archive.infolist():
            assert entry.date_time == (1980, 1, 1, 0, 0, 0), "Wheel enthaelt einen Zeitstempel"
            assert entry.compress_type == zipfile.ZIP_STORED


def _read_sums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        result[name] = digest
    return result


def test_bundle_is_reproducible_and_complete(tmp_path: Path) -> None:
    first = build_bundle.build_bundle(tmp_path / "bau1")
    second = build_bundle.build_bundle(tmp_path / "bau2")

    assert first["build_id"] == second["build_id"]
    assert first["wheel"]["sha256"] == second["wheel"]["sha256"]
    assert [a["sha256"] for a in first["archives"]] == [a["sha256"] for a in second["archives"]]

    root = Path(first["bundle_dir"])
    project = pyproject()["project"]
    wheel = build_backend.wheel_filename(project)

    expected = [
        wheel,
        "install.sh",
        "install.cmd",
        "eam-ai.sh",
        "eam-ai.cmd",
        "run-example.sh",
        "run-example.cmd",
        "README-OFFLINE.md",
        "CHANGELOG.md",
        "PACKAGING.md",
        "BUILD-INFO.json",
        "SHA256SUMS.txt",
        "vendor/README.txt",
        "example/mdg_admbw_auszug.xml",
        "example/prosa.txt",
        "example/antwort.json",
        "source/pyproject.toml",
        "source/build_backend.py",
        "source/tools/build_bundle.py",
        "source/tools/verify_bundle.py",
    ]
    for rel in expected:
        assert (root / rel).is_file(), f"{rel} fehlt im Bundle"
    assert (root / "install.sh").stat().st_mode & 0o777 == 0o755
    assert (root / "eam-ai.sh").stat().st_mode & 0o777 == 0o755
    assert (root / "install.cmd").read_bytes().count(b"\r\n") > 1
    assert b"\n" not in (root / "install.cmd").read_bytes().replace(b"\r\n", b"")

    info = json.loads((root / "BUILD-INFO.json").read_text(encoding="utf-8"))
    assert info["build_id"] == first["build_id"]
    assert info["wheel_sha256"] == sha256(root / wheel)
    assert info["version"] == project["version"]
    assert info["python_requires"] == ">=3.11"
    assert info["runtime_dependencies"] == []
    assert not {"date", "time", "timestamp", "created"} & set(info)
    assert all(not key.startswith("source/") or len(value) == 64 for key, value in info["sources"].items())

    sums = _read_sums(root / "SHA256SUMS.txt")
    bundle_files = {
        str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()
    } - {"SHA256SUMS.txt"}
    assert set(sums) == bundle_files, "SHA256SUMS.txt deckt nicht jede Bundle-Datei ab"
    for rel, digest in sums.items():
        assert sha256(root / rel) == digest, f"Hash falsch: {rel}"

    for archive in first["archives"]:
        path = Path(archive["file"])
        assert path.is_file()
        assert sha256(path) == archive["sha256"]
        sidecar = path.with_name(path.name + ".sha256")
        assert sidecar.read_text(encoding="utf-8") == f"{archive['sha256']}  {path.name}\n"

    with zipfile.ZipFile(first["archives"][0]["file"]) as archive:
        names = set(archive.namelist())
        prefix = f"eam-ai-{project['version']}-offline"
        assert all(name.startswith(f"{prefix}/") for name in names)
        assert f"{prefix}/eam_ai-{project['version']}-py3-none-any.whl" in names
        assert f"{prefix}/install.cmd" in names


def test_example_runs_offline_and_deterministically(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("EXTRACT_MODEL", None)
    targets = []
    for index in (1, 2):
        target = tmp_path / f"lauf{index}.qea"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "eam_ai",
                "build",
                "--mdg",
                str(EXAMPLE / "mdg_admbw_auszug.xml"),
                "--text",
                str(EXAMPLE / "prosa.txt"),
                "--out",
                str(target),
                "--backend",
                "datei",
                "--antwort",
                str(EXAMPLE / "antwort.json"),
                "--findings",
                str(tmp_path / f"findings{index}.json"),
                "--quellen",
                str(tmp_path / f"quellen{index}.json"),
                "-q",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert "3 Elemente" in completed.stdout
        targets.append(target.read_bytes())

    assert targets[0] == targets[1], "Beispiel-Lauf ist nicht byte-identisch"
    assert json.loads((tmp_path / "findings1.json").read_text(encoding="utf-8")) == []
    quellen = json.loads((tmp_path / "quellen1.json").read_text(encoding="utf-8"))
    assert len(quellen) == 3
