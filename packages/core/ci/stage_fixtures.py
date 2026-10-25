"""Stellt die internen Fixtures (MDG, MASC) fuer Tests und Build bereit.

Die Fixtures selbst liegen **nicht** im Repo (siehe ``.gitignore``). Im Repo
steht nur ``ci/fixtures_manifest.json`` mit Dateiname, Groesse und SHA-256.
Dieses Skript kopiert die Dateien aus dem internen Fixture-Store nach
``fixtures/`` und prueft jede Datei gegen das Manifest.

Regeln:

* Kein stiller Erfolg: fehlt eine Datei, weicht Groesse oder Hash ab, endet
  der Lauf mit Exit 1 und nennt Datei und Erwartung.
* Kopiert wird atomar (Temp-Datei im Zielverzeichnis, dann ``os.replace``),
  damit ein Abbruch nie eine halbe Fixture hinterlaesst.
* ``--check`` prueft nur die bereits abgelegten Dateien, ohne Store-Zugriff.

Aufruf (aus der Repo-Wurzel)::

    python -m ci.stage_fixtures                 # Store -> fixtures/
    python -m ci.stage_fixtures --check         # nur pruefen
    python -m ci.stage_fixtures --store /srv/eam-fixtures
    python -m ci.stage_fixtures --store-url https://intern.example/eam-fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "ci" / "fixtures_manifest.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1024 * 1024


class FixtureError(RuntimeError):
    """Fixture-Store oder Manifest passt nicht -- immer laut."""


@dataclass(frozen=True)
class Fixture:
    name: str
    target: str
    sha256: str
    bytes: int


def _fail(message: str) -> NoReturn:
    raise FixtureError(message)


def load_manifest(path: Path) -> list[Fixture]:
    """Manifest lesen und vollstaendig pruefen (kein Tolerieren von Luecken)."""
    if not path.is_file():
        _fail(f"Manifest fehlt: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail(f"Manifest nicht lesbar ({path}): {exc}")

    if not isinstance(data, dict):
        _fail(f"Manifest {path}: Objekt erwartet, gefunden {type(data).__name__}")
    if data.get("schema") != 1:
        _fail(f"Manifest {path}: schema 1 erwartet, gefunden {data.get('schema')!r}")

    raw = data.get("fixtures")
    if not isinstance(raw, list) or not raw:
        _fail(f"Manifest {path}: 'fixtures' ist leer -- ohne Fixture gibt es nichts zu pruefen")

    fixtures: list[Fixture] = []
    seen_names: set[str] = set()
    seen_targets: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"Manifest {path}: fixtures[{index}]"
        if not isinstance(entry, dict):
            _fail(f"{where}: Objekt erwartet")
        name = entry.get("name")
        target = entry.get("target")
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            _fail(f"{where}: 'name' muss ein reiner Dateiname sein, gefunden {name!r}")
        if not isinstance(target, str) or not target or target.startswith("/"):
            _fail(f"{where}: 'target' muss ein relativer Pfad sein, gefunden {target!r}")
        if Path(target).is_absolute() or ".." in Path(target).parts:
            _fail(f"{where}: 'target' darf das Repo nicht verlassen: {target!r}")
        if not isinstance(digest, str) or not SHA256_RE.match(digest):
            _fail(f"{where}: 'sha256' muss 64 Hex-Zeichen haben, gefunden {digest!r}")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            _fail(f"{where}: 'bytes' muss eine positive Ganzzahl sein, gefunden {size!r}")
        if name in seen_names:
            _fail(f"{where}: Dateiname {name!r} ist doppelt")
        if target in seen_targets:
            _fail(f"{where}: Ziel {target!r} ist doppelt")
        seen_names.add(name)
        seen_targets.add(target)
        fixtures.append(Fixture(name=name, target=target, sha256=digest, bytes=size))
    return fixtures


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _verify(path: Path, fixture: Fixture, origin: str) -> None:
    try:
        digest, size = sha256_file(path)
    except OSError as exc:
        _fail(f"{fixture.name}: nicht lesbar ({origin}): {exc}")
    if size != fixture.bytes:
        _fail(
            f"{fixture.name}: Groesse weicht ab ({origin}): "
            f"erwartet {fixture.bytes} Bytes, gefunden {size}"
        )
    if digest != fixture.sha256:
        _fail(
            f"{fixture.name}: SHA-256 weicht ab ({origin}): "
            f"erwartet {fixture.sha256}, gefunden {digest}"
        )


def _place(source: Path, fixture: Fixture) -> str:
    """Datei atomar ins Ziel kopieren und das Ergebnis erneut pruefen."""
    destination = ROOT / fixture.target
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle, source.open("rb") as reader:
            while True:
                block = reader.read(CHUNK)
                if not block:
                    break
                handle.write(block)
        _verify(temporary, fixture, f"Kopie aus {source}")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _verify(destination, fixture, "Ziel nach dem Kopieren")
    return fixture.target


def _fetch_url(url: str, fixture: Fixture) -> Path:
    """Datei aus dem internen HTTP-Store laden und dabei hashen."""
    destination_dir = (ROOT / fixture.target).parent
    destination_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=destination_dir, prefix=f".{fixture.name}.", suffix=".part", delete=False
    )
    temporary = Path(handle.name)
    digest = hashlib.sha256()
    size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "eam-ai-ci/1"})
        try:
            with handle, urllib.request.urlopen(request, timeout=120) as response:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    size += len(block)
                    handle.write(block)
        except OSError as exc:
            _fail(f"{fixture.name}: Abruf von {url} fehlgeschlagen: {exc}")
        if size != fixture.bytes:
            _fail(
                f"{fixture.name}: Groesse weicht ab (Abruf): "
                f"erwartet {fixture.bytes} Bytes, gefunden {size}"
            )
        found = digest.hexdigest()
        if found != fixture.sha256:
            _fail(
                f"{fixture.name}: SHA-256 weicht ab (Abruf): "
                f"erwartet {fixture.sha256}, gefunden {found}"
            )
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _store_path(arguments: argparse.Namespace) -> Path:
    candidate = arguments.store or os.environ.get("EAM_FIXTURE_STORE", "")
    if not candidate:
        _fail(
            "Fixture-Store fehlt: --store PFAD setzen oder EAM_FIXTURE_STORE "
            "auf das interne Verzeichnis mit MDG/MASC zeigen lassen"
        )
    store = Path(candidate).expanduser()
    if not store.is_dir():
        _fail(f"Fixture-Store ist kein Verzeichnis: {store}")
    return store


def stage(arguments: argparse.Namespace) -> int:
    fixtures = load_manifest(arguments.manifest)
    store_url = arguments.store_url or os.environ.get("EAM_FIXTURE_STORE_URL", "")
    if store_url:
        base = store_url.rstrip("/")
        for fixture in fixtures:
            url = f"{base}/{urllib.parse.quote(fixture.name)}"
            print(f"lade {fixture.name} von {base}")
            temporary = _fetch_url(url, fixture)
            destination = ROOT / fixture.target
            os.replace(temporary, destination)
            _verify(destination, fixture, "Ziel nach dem Kopieren")
            print(f"ok  {fixture.target} ({fixture.bytes} Bytes, sha256 {fixture.sha256[:12]}...)")
    else:
        store = _store_path(arguments)
        for fixture in fixtures:
            source = store / fixture.name
            if not source.is_file():
                _fail(
                    f"{fixture.name}: fehlt im Store {store} "
                    f"(erwartet {fixture.bytes} Bytes, sha256 {fixture.sha256})"
                )
            _verify(source, fixture, f"Store {store}")
            _place(source, fixture)
            print(f"ok  {fixture.target} ({fixture.bytes} Bytes, sha256 {fixture.sha256[:12]}...)")
    print(f"stage_fixtures: {len(fixtures)} Fixture(s) bereitgestellt und geprueft")
    return 0


def check(arguments: argparse.Namespace) -> int:
    fixtures = load_manifest(arguments.manifest)
    for fixture in fixtures:
        destination = ROOT / fixture.target
        if not destination.is_file():
            _fail(
                f"{fixture.target}: fehlt -- zuerst 'python -m ci.stage_fixtures' laufen lassen"
            )
        _verify(destination, fixture, "Arbeitskopie")
        print(f"ok  {fixture.target} ({fixture.bytes} Bytes, sha256 {fixture.sha256[:12]}...)")
    print(f"stage_fixtures --check: {len(fixtures)} Fixture(s) geprueft")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ci.stage_fixtures",
        description="Interne Fixtures aus dem Store in fixtures/ bereitstellen und pruefen.",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Fixture-Manifest")
    parser.add_argument("--store", type=Path, default=None, help="Store-Verzeichnis (sonst EAM_FIXTURE_STORE)")
    parser.add_argument("--store-url", default=None, help="Interner HTTP-Store (sonst EAM_FIXTURE_STORE_URL)")
    parser.add_argument("--check", action="store_true", help="nur die Arbeitskopie pruefen, nichts kopieren")
    parser.add_argument(
        "--optional",
        action="store_true",
        help=(
            "ohne konfigurierten Store nicht abbrechen, sondern die synthetischen "
            "Repo-Fixtures nutzen (Pipeline ohne internen Store)"
        ),
    )
    return parser


def _store_konfiguriert(arguments: argparse.Namespace) -> bool:
    return bool(
        arguments.store
        or os.environ.get("EAM_FIXTURE_STORE", "")
        or arguments.store_url
        or os.environ.get("EAM_FIXTURE_STORE_URL", "")
    )


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.optional and not _store_konfiguriert(arguments):
        print(
            "stage_fixtures: kein Fixture-Store konfiguriert -- "
            "es gelten die synthetischen Repo-Fixtures (tests/fixtures)."
        )
        return 0
    try:
        return check(arguments) if arguments.check else stage(arguments)
    except FixtureError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
