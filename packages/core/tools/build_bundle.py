"""Offline-Bundle der EAM AI Suite Python bauen (nur Standardbibliothek).

Erzeugt ein Verzeichnis plus `.zip` und `.tar.gz` mit:

* deterministischem Wheel (siehe ``build_backend.py``),
* Installations- und Startskripten fuer Linux und Windows,
* Beispiel-Eingaben und einem lauffaehigen Beispiel,
* Quellstand zum Nachbau,
* ``BUILD-INFO.json`` mit Version, Mindeststand, Wheel-Hash und ``build_id``,
* ``SHA256SUMS.txt`` ueber jede Bundle-Datei.

Keine Zeitstempel, keine Zufallswerte: gleicher Quellstand -> gleiche Bytes.
Aufruf::

    python3 tools/build_bundle.py --out dist/offline
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # Aufruf aus dem Bundle heraus: source/tools/...
    sys.path.insert(0, str(ROOT))

import build_backend  # noqa: E402  (Pfad muss vor dem Import stehen)

BUNDLE_SCHEMA = 1
FIXED_DATE = build_backend.FIXED_DATE
UTF8 = "utf-8"

# Dateien des Quellstands, die im Bundle unter ``source/`` liegen. Die Module
# und Ressourcen kommen aus pyproject.toml, damit nichts auseinanderlaeuft.
SOURCE_STATIC = [
    "pyproject.toml",
    "build_backend.py",
    "README.md",
    "CHANGELOG.md",
    "PACKAGING.md",
    "tools/build_bundle.py",
    "tools/verify_bundle.py",
]
EXAMPLE_SUFFIX = "examples/offline"


class BundleError(RuntimeError):
    """Bundle unvollstaendig. Immer laut, nie ein halbes Artefakt."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


RULES = ROOT.parent / "rules"  # einziger MDG-Leser, neben dem Kern


def _read(rel: str) -> bytes:
    path = ROOT / rel
    if not path.is_file() and (RULES / rel).is_file():
        path = RULES / rel
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BundleError(f"{path}: nicht lesbar ({exc})") from exc


def _canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(UTF8)


README_OFFLINE = """# EAM AI Suite Python {version} -- Offline-Bundle

Technologie + Prosa zu `.qea`: Extraktion, Pruefung, Export. Dieses Bundle
laesst sich ohne Netz, ohne Docker und ohne Fremdpakete installieren.

## Mindeststand

- Python **3.11 oder neuer** (getestet mit 3.12), Linux oder Windows 10/11.
- Kein Docker, keine Adminrechte, kein Netzwerk fuer Installation und Beispiel.
- Laufzeit haengt nur an der Standardbibliothek (inklusive `sqlite3`).

## Linux

```sh
./install.sh
./eam-ai.sh --version
./run-example.sh
```

## Windows (Eingabeaufforderung)

```bat
install.cmd
eam-ai.cmd --version
run-example.cmd
```

`install.sh`/`install.cmd` legen `./.venv` an und installieren ausschliesslich
das mitgelieferte Wheel (`pip --no-index --no-deps`). Fehlt Python 3.11+,
brechen beide mit Exit 1 und klarer Meldung ab.

## Beispiel

```sh
./eam-ai.sh build --mdg example/mdg_admbw_auszug.xml --text example/prosa.txt \\
    --out out/beispiel.qea --backend datei --antwort example/antwort.json \\
    --findings out/findings.json --quellen out/quellen.json
```

Erwartung: Exit 0, `3 Elemente, 1 Beziehungen`, `findings.json` ist `[]`.
Ein zweiter Lauf erzeugt dieselbe `sha256` fuer die `.qea` (gleicher
Interpreter; die SQLite-Bibliothek bestimmt das Dateiformat).

## Integritaet

`SHA256SUMS.txt` enthaelt den Hash jeder Bundle-Datei. Der Hash des Archivs
steht in der `.sha256`-Datei daneben. Details: `PACKAGING.md`,
`BUILD-INFO.json`.

## KI

Das Bundle enthaelt kein Sprachmodell. Offline arbeitet `--backend datei`
(Antwortdatei) oder der Regelpfad `python -m eam_suite`. Mit KI:
`--backend openai` oder `--backend ollama` -- der einzige Pfad mit Netzzugriff.
"""

VENDOR_README = """Keine Vendored Dependencies.

Der Kern der EAM AI Suite Python nutzt ausschliesslich die Python-Standardbibliothek
(inklusive sqlite3, zipfile, xml.etree, csv). Deshalb gibt es hier bewusst
nichts zu vendorn: `dependencies = []` in pyproject.toml, keine
`site-packages`-Kopien, kein Nachladen. Das haelt das Bundle klein und in
Bw-Umgebungen ohne Netz pruefbar.
"""

INSTALL_SH = """#!/bin/sh
# Offline-Installation in ./.venv -- kein Netz, kein Docker, keine Adminrechte.
set -eu
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "FEHLER: Python 3.11 oder neuer nicht gefunden (PYTHON=$PYTHON)." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    if ! "$PYTHON" -m venv .venv; then
        echo "FEHLER: .venv konnte nicht angelegt werden (python3-venv vorhanden?)." >&2
        exit 1
    fi
fi

if ! ./.venv/bin/python -m pip --version >/dev/null 2>&1; then
    echo "FEHLER: pip fehlt in .venv (ensurepip/python3-venv nachinstallieren)." >&2
    exit 1
fi

./.venv/bin/python -m pip install --no-index --no-deps --disable-pip-version-check \\
    "./__WHEEL__"

echo "Installiert: ./.venv  --  Aufruf: ./eam-ai.sh --version"
"""

EAM_AI_SH = """#!/bin/sh
# Startet das installierte eam-ai aus dem Bundle-Ordner.
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/eam-ai ]; then
    echo "FEHLER: nicht installiert. Zuerst ./install.sh ausfuehren." >&2
    exit 1
fi

exec .venv/bin/eam-ai "$@"
"""

RUN_EXAMPLE_SH = """#!/bin/sh
# Beispiel-Lauf ohne Netz: MDG-Auszug + Prosa + vorbereitete Antwortdatei.
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/eam-ai ]; then
    echo "FEHLER: nicht installiert. Zuerst ./install.sh ausfuehren." >&2
    exit 1
fi

mkdir -p out
./.venv/bin/eam-ai build \\
    --mdg example/mdg_admbw_auszug.xml \\
    --text example/prosa.txt \\
    --out out/beispiel.qea \\
    --backend datei \\
    --antwort example/antwort.json \\
    --findings out/findings.json \\
    --quellen out/quellen.json

echo "Ergebnis: out/beispiel.qea, out/quellen.json, out/findings.json"
"""

INSTALL_CMD = """@echo off
rem Offline-Installation in .\\.venv -- kein Netz, kein Docker, keine Adminrechte.
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python 3.11 oder neuer nicht gefunden. 1>&2
    exit /b 1
)

if not exist ".venv\\Scripts\\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo FEHLER: .venv konnte nicht angelegt werden. 1>&2
        exit /b 1
    )
)

".venv\\Scripts\\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: pip fehlt in .venv. 1>&2
    exit /b 1
)

".venv\\Scripts\\python.exe" -m pip install --no-index --no-deps --disable-pip-version-check "__WHEEL__"
if errorlevel 1 (
    echo FEHLER: Installation fehlgeschlagen. 1>&2
    exit /b 1
)

echo Installiert: .\\.venv  --  Aufruf: eam-ai.cmd --version
exit /b 0
"""

EAM_AI_CMD = """@echo off
rem Startet das installierte eam-ai aus dem Bundle-Ordner.
setlocal
cd /d "%~dp0"

if not exist ".venv\\Scripts\\eam-ai.exe" (
    echo FEHLER: nicht installiert. Zuerst install.cmd ausfuehren. 1>&2
    exit /b 1
)

".venv\\Scripts\\eam-ai.exe" %*
exit /b %ERRORLEVEL%
"""

RUN_EXAMPLE_CMD = """@echo off
rem Beispiel-Lauf ohne Netz: MDG-Auszug + Prosa + vorbereitete Antwortdatei.
setlocal
cd /d "%~dp0"

if not exist ".venv\\Scripts\\eam-ai.exe" (
    echo FEHLER: nicht installiert. Zuerst install.cmd ausfuehren. 1>&2
    exit /b 1
)

if not exist "out" mkdir "out"
".venv\\Scripts\\eam-ai.exe" build ^
    --mdg example\\mdg_admbw_auszug.xml ^
    --text example\\prosa.txt ^
    --out out\\beispiel.qea ^
    --backend datei ^
    --antwort example\\antwort.json ^
    --findings out\\findings.json ^
    --quellen out\\quellen.json
if errorlevel 1 exit /b %ERRORLEVEL%
echo Ergebnis: out\\beispiel.qea, out\\quellen.json, out\\findings.json
exit /b 0
"""


def _crlf(text: str) -> bytes:
    return text.replace("\n", "\r\n").encode("cp1252", errors="strict")


def _lf(text: str) -> bytes:
    return text.encode(UTF8)


def _scripts(version: str, wheel: str) -> dict[str, tuple[bytes, int]]:
    return {
        "install.sh": (_lf(INSTALL_SH.replace("__WHEEL__", wheel)), 0o755),
        "eam-ai.sh": (_lf(EAM_AI_SH), 0o755),
        "run-example.sh": (_lf(RUN_EXAMPLE_SH), 0o755),
        "install.cmd": (_crlf(INSTALL_CMD.replace("__WHEEL__", wheel)), 0o644),
        "eam-ai.cmd": (_crlf(EAM_AI_CMD), 0o644),
        "run-example.cmd": (_crlf(RUN_EXAMPLE_CMD), 0o644),
        "vendor/README.txt": (_lf(VENDOR_README), 0o644),
        "README-OFFLINE.md": (_lf(README_OFFLINE.format(version=version)), 0o644),
    }


def _payload() -> tuple[dict, dict[str, tuple[bytes, int]]]:
    """Alle Bundle-Dateien ausser BUILD-INFO/SHA256SUMS, Wheel frisch gebaut."""

    project, modules, resources = build_backend.config()
    version = str(project["version"])
    wheel_name = build_backend.wheel_filename(project)

    with tempfile.TemporaryDirectory(prefix="eam-wheel-") as tmp:
        wheel_built = Path(tmp) / build_backend.build_wheel(tmp)
        wheel_bytes = wheel_built.read_bytes()
        if wheel_built.name != wheel_name:
            raise BundleError(f"Backend lieferte {wheel_built.name}, erwartet {wheel_name}")

    files: dict[str, tuple[bytes, int]] = {wheel_name: (wheel_bytes, 0o644)}
    files.update(_scripts(version, wheel_name))

    files["CHANGELOG.md"] = (_read("CHANGELOG.md"), 0o644)
    files["PACKAGING.md"] = (_read("PACKAGING.md"), 0o644)

    for name in ("antwort.json", "mdg_admbw_auszug.xml", "prosa.txt"):
        files[f"example/{name}"] = (_read(f"{EXAMPLE_SUFFIX}/{name}"), 0o644)

    for name in SOURCE_STATIC:
        files[f"source/{name}"] = (_read(name), 0o644)
    for module in modules:
        files[f"source/{module}.py"] = (_read(f"{module}.py"), 0o644)
    for resource in resources:
        files[f"source/{resource}"] = (_read(resource), 0o644)
    for name in ("antwort.json", "mdg_admbw_auszug.xml", "prosa.txt"):
        files[f"source/{EXAMPLE_SUFFIX}/{name}"] = (_read(f"{EXAMPLE_SUFFIX}/{name}"), 0o644)

    return project, files


def _build_info(project: dict, files: dict[str, tuple[bytes, int]]) -> tuple[dict, str]:
    wheel_name = build_backend.wheel_filename(project)
    sources = {
        rel: sha256_bytes(data)
        for rel, (data, _) in sorted(files.items())
        if rel.startswith("source/")
    }
    core = {
        "bundle_schema": BUNDLE_SCHEMA,
        "name": project["name"],
        "version": project["version"],
        "python_requires": project.get("requires-python", ">=3.11"),
        "runtime_dependencies": list(project.get("dependencies") or []),
        "wheel": wheel_name,
        "wheel_sha256": sha256_bytes(files[wheel_name][0]),
        "sources": sources,
    }
    build_id = sha256_bytes(_canonical(core))
    info = dict(core)
    info["build_id"] = build_id
    return info, build_id


def _sums(files: dict[str, tuple[bytes, int]]) -> bytes:
    lines = [f"{sha256_bytes(data)}  {rel}" for rel, (data, _) in sorted(files.items())]
    return ("\n".join(lines) + "\n").encode(UTF8)


def _write_tree(root: Path, files: dict[str, tuple[bytes, int]]) -> None:
    if root.exists():
        if not root.name.endswith("-offline"):
            raise BundleError(f"{root}: vorhandenes Ziel ist kein Bundle-Ordner -- Abbruch")
        shutil.rmtree(root)
    for rel, (data, mode) in sorted(files.items()):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(mode)


def _zip_bytes(prefix: str, files: dict[str, tuple[bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for rel, (data, mode) in sorted(files.items()):
            info = zipfile.ZipInfo(f"{prefix}/{rel}", date_time=FIXED_DATE)
            info.create_system = 3
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def _tar_gz_bytes(prefix: str, files: dict[str, tuple[bytes, int]]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for rel, (data, mode) in sorted(files.items()):
            info = tarfile.TarInfo(f"{prefix}/{rel}")
            info.size = len(data)
            info.mode = mode
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    packed = io.BytesIO()
    with gzip.GzipFile(fileobj=packed, mode="wb", compresslevel=9, mtime=0) as gzip_file:
        gzip_file.write(raw.getvalue())
    return packed.getvalue()


def build_bundle(out: str | Path, *, archives: bool = True) -> dict:
    """Bundle bauen und einen Bericht mit allen Hashes zurueckgeben."""

    out_dir = Path(out).resolve()
    project, files = _payload()
    version = str(project["version"])
    prefix = f"eam-ai-{version}-offline"

    info, build_id = _build_info(project, files)
    files["BUILD-INFO.json"] = (
        (json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(UTF8),
        0o644,
    )
    files["SHA256SUMS.txt"] = (_sums(files), 0o644)

    out_dir.mkdir(parents=True, exist_ok=True)
    root = out_dir / prefix
    _write_tree(root, files)

    report: dict = {
        "bundle_dir": str(root),
        "version": version,
        "build_id": build_id,
        "wheel": {
            "file": build_backend.wheel_filename(project),
            "sha256": info["wheel_sha256"],
        },
        "archives": [],
    }

    if archives:
        zip_name = f"{prefix}.zip"
        tar_name = f"{prefix}.tar.gz"
        zip_data = _zip_bytes(prefix, files)
        tar_data = _tar_gz_bytes(prefix, files)
        for name, data in ((zip_name, zip_data), (tar_name, tar_data)):
            target = out_dir / name
            target.write_bytes(data)
            digest = sha256_bytes(data)
            (out_dir / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding=UTF8)
            report["archives"].append({"file": str(target), "sha256": digest})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_bundle",
        description="Offline-Bundle der EAM AI Suite Python bauen (deterministisch).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dist/offline"),
        help="Zielordner (Default: dist/offline)",
    )
    parser.add_argument("--no-archives", action="store_true", help="nur den Ordner, kein .zip/.tar.gz")
    args = parser.parse_args(argv)

    try:
        report = build_bundle(args.out, archives=not args.no_archives)
    except (BundleError, build_backend.BuildConfigError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(f"Bundle:  {report['bundle_dir']}")
    print(f"Version: {report['version']}")
    print(f"Wheel:   {report['wheel']['file']} sha256={report['wheel']['sha256']}")
    print(f"build_id: {report['build_id']}")
    for archive in report["archives"]:
        print(f"Archiv:  {archive['file']} sha256={archive['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
