"""PEP-517-Build-Backend fuer die EAM AI Suite Python (nur Standardbibliothek).

Warum ein eigenes Backend?
--------------------------
Das Paket hat keine Laufzeitabhaengigkeiten und muss in Umgebungen ohne Netz
baubar sein. Setuptools waere eine Build-Abhaengigkeit, die erst beschafft
werden muesste. Dieses Backend erzeugt das Wheel direkt mit ``zipfile`` und
``tomllib`` -- deterministisch:

* fester Zeitstempel (1980-01-01) fuer jeden Eintrag,
* sortierte Eintraege, feste Dateirechte,
* keine Kompression (ZIP_STORED), damit die Bytes nicht von der zlib-Version
  abhaengen,
* keine Build-IDs, keine Zeitangaben in METADATA/WHEEL/RECORD.

Gleicher Quellstand -> gleiche Wheel-Bytes. ``tools/build_bundle.py`` baut
darauf das Offline-Bundle.

Unterstuetzte Hooks: ``build_wheel``, ``prepare_metadata_for_build_wheel``,
``get_requires_for_build_wheel``. Eine sdist wird bewusst nicht erzeugt.
"""

from __future__ import annotations

import base64
import hashlib
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Der MDG-Leser ist der einzige seiner Art und liegt neben dem Kern, nicht darin.
RULES = ROOT.parent / "rules"
FIXED_DATE = (1980, 1, 1, 0, 0, 0)
GENERATOR = "eam-ai-build (deterministisch, stdlib)"
METADATA_VERSION = "2.1"


class BuildConfigError(RuntimeError):
    """Der Quellstand ist nicht baubar. Immer laut, nie ein halbes Wheel."""


def _read_pyproject() -> dict:
    path = ROOT / "pyproject.toml"
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        raise BuildConfigError(f"{path}: nicht lesbar ({exc})") from exc
    except tomllib.TOMLDecodeError as exc:
        raise BuildConfigError(f"{path}: kein gueltiges TOML ({exc})") from exc


def config() -> tuple[dict, list[str], list[str]]:
    """Projektmetadaten und Paketinhalt aus ``pyproject.toml`` lesen."""

    data = _read_pyproject()
    project = data.get("project")
    if not isinstance(project, dict):
        raise BuildConfigError("pyproject.toml: Abschnitt [project] fehlt")
    tool = data.get("tool", {}).get("eam-ai", {})
    modules = tool.get("modules")
    resources = tool.get("resources")
    if not modules or not isinstance(modules, list) or not all(isinstance(m, str) for m in modules):
        raise BuildConfigError("pyproject.toml: [tool.eam-ai].modules fehlt oder ist leer")
    if resources is None:
        resources = []
    if not isinstance(resources, list) or not all(isinstance(r, str) for r in resources):
        raise BuildConfigError("pyproject.toml: [tool.eam-ai].resources ist keine Liste")
    for module in modules:
        if not (ROOT / f"{module}.py").is_file() and not (RULES / f"{module}.py").is_file():
            raise BuildConfigError(f"Modul {module}.py fehlt im Quellverzeichnis")
    for resource in resources:
        if not (ROOT / resource).is_file():
            raise BuildConfigError(f"Ressource {resource} fehlt im Quellverzeichnis")
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise BuildConfigError("pyproject.toml: [project].version fehlt")
    if not project.get("name"):
        raise BuildConfigError("pyproject.toml: [project].name fehlt")
    return project, list(modules), list(resources)


def dist_name(project: dict) -> str:
    """Normalisierter Distributionsname (PEP 503): ``eam-ai`` -> ``eam_ai``."""

    return str(project["name"]).replace("-", "_").replace(".", "_").lower()


def wheel_filename(project: dict) -> str:
    return f"{dist_name(project)}-{project['version']}-py3-none-any.whl"


def _metadata(project: dict, readme: str) -> bytes:
    lines = [
        f"Metadata-Version: {METADATA_VERSION}",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {project.get('description', '')}",
        f"Requires-Python: {project.get('requires-python', '>=3.11')}",
        "Description-Content-Type: text/markdown",
    ]
    for classifier in project.get("classifiers", []):
        lines.append(f"Classifier: {classifier}")
    for keyword in project.get("keywords", []):
        lines.append(f"Keywords: {keyword}")
    body = "\n".join(lines) + "\n\n" + readme
    if not body.endswith("\n"):
        body += "\n"
    return body.encode("utf-8")


def _wheel_metadata() -> bytes:
    return (
        "Wheel-Version: 1.0\n"
        f"Generator: {GENERATOR}\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")


def _entry_points(project: dict) -> bytes:
    scripts = project.get("scripts") or {}
    if not scripts:
        raise BuildConfigError("pyproject.toml: [project.scripts] fehlt (Entry-Point eam-ai)")
    lines = ["[console_scripts]"]
    for name in sorted(scripts):
        lines.append(f"{name} = {scripts[name]}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _top_level(modules: list[str]) -> bytes:
    return ("\n".join(sorted(modules)) + "\n").encode("utf-8")


def _dist_info(project: dict) -> str:
    return f"{dist_name(project)}-{project['version']}.dist-info"


def _payload(project: dict, modules: list[str], resources: list[str]) -> list[tuple[str, bytes]]:
    """Alle Dateien des Wheels ausser RECORD, deterministisch sortiert."""

    files: list[tuple[str, bytes]] = []
    for module in modules:
        quelle = ROOT / f"{module}.py"
        if not quelle.is_file():
            quelle = RULES / f"{module}.py"
        files.append((f"{module}.py", quelle.read_bytes()))
    for resource in resources:
        files.append((resource, (ROOT / resource).read_bytes()))
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    info = _dist_info(project)
    files.append((f"{info}/METADATA", _metadata(project, readme)))
    files.append((f"{info}/WHEEL", _wheel_metadata()))
    files.append((f"{info}/entry_points.txt", _entry_points(project)))
    files.append((f"{info}/top_level.txt", _top_level(modules)))
    files.sort(key=lambda item: item[0])
    return files


def _record(entries: list[tuple[str, bytes]], info: str) -> bytes:
    lines: list[str] = []
    for name, data in entries:
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        lines.append(f"{name},sha256={digest},{len(data)}")
    lines.append(f"{info}/RECORD,,")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_zip(target: Path, entries: list[tuple[str, bytes, int]]) -> None:
    """ZIP mit festen Zeitstempeln, sortierten Eintraegen und festen Rechten."""

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data, mode in sorted(entries, key=lambda item: item[0]):
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
            info.create_system = 3  # Unix, damit die Rechte eindeutig sind
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)


def wheel_entries(project: dict | None = None) -> list[tuple[str, bytes, int]]:
    """Inhalt des Wheels als (Name, Bytes, Modus) -- auch fuer Pruefungen."""

    if project is None:
        project, modules, resources = config()
    else:
        _, modules, resources = config()
    payload = _payload(project, modules, resources)
    entries = [(name, data, 0o644) for name, data in payload]
    record = _record(payload, _dist_info(project))
    entries.append((f"{_dist_info(project)}/RECORD", record, 0o644))
    return entries


def build_wheel(
    wheel_directory: str,
    config_settings: dict | None = None,
    metadata_directory: str | None = None,
) -> str:
    """PEP 517: Wheel schreiben und den Dateinamen zurueckgeben."""

    del config_settings, metadata_directory  # bewusst ohne Wirkung: ein Ergebnis
    project, _, _ = config()
    target_dir = Path(wheel_directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / wheel_filename(project)
    _write_zip(target, wheel_entries(project))
    return target.name


def prepare_metadata_for_build_wheel(
    metadata_directory: str, config_settings: dict | None = None
) -> str:
    """PEP 517: ``.dist-info`` fuer die Aufloesung vorab schreiben."""

    del config_settings
    project, modules, _ = config()
    info = _dist_info(project)
    target = Path(metadata_directory) / info
    target.mkdir(parents=True, exist_ok=True)
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    (target / "METADATA").write_bytes(_metadata(project, readme))
    (target / "WHEEL").write_bytes(_wheel_metadata())
    (target / "entry_points.txt").write_bytes(_entry_points(project))
    (target / "top_level.txt").write_bytes(_top_level(modules))
    return info


def get_requires_for_build_wheel(config_settings: dict | None = None) -> list[str]:
    """Keine Build-Abhaengigkeiten -- deshalb ist der Build offline moeglich."""

    del config_settings
    return []


def get_requires_for_build_sdist(config_settings: dict | None = None) -> list[str]:
    del config_settings
    return []


def build_sdist(sdist_directory: str, config_settings: dict | None = None) -> str:
    """Nicht unterstuetzt: ausgeliefert wird ausschliesslich das Wheel."""

    del sdist_directory, config_settings
    raise BuildConfigError(
        "sdist ist nicht Teil des Lieferumfangs; bitte das Wheel bauen "
        "(python -m pip wheel . oder python tools/build_bundle.py)"
    )
