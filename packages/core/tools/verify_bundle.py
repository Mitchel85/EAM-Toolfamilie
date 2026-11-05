"""Offline-Bundle pruefen: entpacken, installieren, Beispiel laufen lassen.

Das ist die ausfuehrbare Definition of Done fuer das Paket:

1. Archiv-Hash gegen die ``.sha256``-Datei pruefen (falls vorhanden),
2. ``SHA256SUMS.txt`` im Bundle gegen jede Datei pruefen,
3. frisches ``.venv`` ueber ``install.sh`` anlegen (ohne Netz),
4. ``eam-ai --version`` gegen ``BUILD-INFO.json`` pruefen,
5. Beispiel zweimal laufen lassen, Exit 0 und byte-identische ``.qea``,
6. ``findings.json`` muss ``[]`` sein, ``quellen.json`` drei Belege haben.

Aufruf::

    python3 tools/verify_bundle.py dist/offline/eam-ai-2.1.0-offline.tar.gz

Nur POSIX (Linux/macOS). Fuer Windows sind ``install.cmd``/``run-example.cmd``
die Entsprechung; sie werden hier nicht automatisiert geprueft.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

UTF8 = "utf-8"


class VerifyError(RuntimeError):
    """Pruefung fehlgeschlagen. Immer laut, nie ein stiller Teilerfolg."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_target(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise VerifyError(f"Archivpfad verlaesst das Ziel: {name}")
    return target


def extract(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise VerifyError(f"{archive}: Archiv fehlt")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                target = _safe_target(destination, entry.filename)
                package.extract(entry, destination)
                mode = (entry.external_attr >> 16) & 0o777
                if mode and not entry.is_dir():
                    target.chmod(mode)
    else:
        with tarfile.open(archive) as package:
            for member in package.getmembers():
                _safe_target(destination, member.name)
                if member.issym() or member.islnk():
                    raise VerifyError(f"{member.name}: Verknuepfungen sind im Bundle nicht erlaubt")
            package.extractall(destination)
    roots = [path for path in destination.iterdir() if path.is_dir() and path.name.endswith("-offline")]
    if len(roots) != 1:
        raise VerifyError(f"Bundle-Wurzel nicht eindeutig: {[p.name for p in destination.iterdir()]}")
    return roots[0]


def verify_sums(bundle: Path) -> int:
    sums = bundle / "SHA256SUMS.txt"
    if not sums.is_file():
        raise VerifyError("SHA256SUMS.txt fehlt")
    checked = 0
    for line in sums.read_text(encoding=UTF8).splitlines():
        digest, name = line.split("  ", 1)
        target = bundle / name
        if not target.is_file():
            raise VerifyError(f"{name}: in SHA256SUMS.txt genannt, aber nicht vorhanden")
        if sha256(target) != digest:
            raise VerifyError(f"{name}: SHA-256 stimmt nicht")
        checked += 1
    actual = {str(p.relative_to(bundle)) for p in bundle.rglob("*") if p.is_file()} - {"SHA256SUMS.txt"}
    listed = {line.split("  ", 1)[1] for line in sums.read_text(encoding=UTF8).splitlines()}
    if actual != listed:
        raise VerifyError(f"SHA256SUMS.txt deckt nicht alle Dateien ab: {sorted(actual ^ listed)}")
    return checked


def _run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if completed.returncode != 0:
        raise VerifyError(
            f"{' '.join(command)} -> Exit {completed.returncode}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    return completed


def verify(archive: Path) -> dict:
    archive = archive.resolve()
    sidecar = archive.with_name(archive.name + ".sha256")
    if sidecar.is_file():
        expected = sidecar.read_text(encoding=UTF8).split()[0]
        if sha256(archive) != expected:
            raise VerifyError(f"{archive.name}: Archiv-Hash stimmt nicht mit der .sha256-Datei")
        print(f"[1/6] Archiv-Hash OK: {expected}")

    environment = dict(os.environ)
    environment["PYTHON"] = sys.executable
    environment["PIP_NO_INDEX"] = "1"
    environment.pop("OPENAI_API_KEY", None)

    with tempfile.TemporaryDirectory(prefix="eam-verify-") as tmp:
        bundle = extract(archive, Path(tmp))
        info = json.loads((bundle / "BUILD-INFO.json").read_text(encoding=UTF8))

        count = verify_sums(bundle)
        print(f"[2/6] SHA256SUMS.txt OK: {count} Dateien")

        _run(["./install.sh"], bundle, environment)
        print("[3/6] Offline-Installation in .venv OK")

        version = _run(["./eam-ai.sh", "--version"], bundle, environment).stdout.strip()
        expected_version = f"eam-ai {info['version']}"
        if version != expected_version:
            raise VerifyError(f"Versionsausgabe {version!r}, erwartet {expected_version!r}")
        print(f"[4/6] Version OK: {version}")

        _run(["./run-example.sh"], bundle, environment)
        findings = json.loads((bundle / "out" / "findings.json").read_text(encoding=UTF8))
        if findings != []:
            raise VerifyError(f"findings.json ist nicht leer: {findings}")
        quellen = json.loads((bundle / "out" / "quellen.json").read_text(encoding=UTF8))
        if len(quellen) != 3:
            raise VerifyError(f"quellen.json hat {len(quellen)} Eintraege, erwartet 3")
        first = sha256(bundle / "out" / "beispiel.qea")
        print(f"[5/6] Beispiel OK: findings=[], quellen=3, qea sha256={first}")

        _run(["./run-example.sh"], bundle, environment)
        second = sha256(bundle / "out" / "beispiel.qea")
        if first != second:
            raise VerifyError("Beispiel ist nicht reproduzierbar: zwei Laeufe liefern verschiedene Bytes")
        print("[6/6] Wiederholung OK: byte-identisch")

    return {
        "version": info["version"],
        "build_id": info["build_id"],
        "wheel_sha256": info["wheel_sha256"],
        "files_checked": count,
        "qea_sha256": first,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_bundle",
        description="Offline-Bundle installieren und die Definition of Done pruefen.",
    )
    parser.add_argument("archive", type=Path, help=".tar.gz oder .zip des Bundles")
    args = parser.parse_args(argv)

    if os.name != "posix":
        print("FEHLER: verify_bundle prueft die POSIX-Skripte; unter Windows bitte install.cmd nutzen.", file=sys.stderr)
        return 1

    try:
        report = verify(args.archive)
    except (VerifyError, OSError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK: eam-ai {report['version']}, build_id {report['build_id']}, "
        f"{report['files_checked']} Dateien, qea sha256 {report['qea_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
