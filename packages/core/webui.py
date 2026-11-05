#!/usr/bin/env python3
"""webui.py -- Weboberflaeche fuer eam-ai: eine Seite, kein Framework.

Start::

    eam-ai serve --host 127.0.0.1 --port 8080

Der Kern bleibt unangetastet: jeder Bau laeuft als eigener Prozess mit genau
dem Aufruf der Kommandozeile (``python -m eam_ai build ...``). Damit gibt es
keine zweite Pipeline und keine zweite Wahrheit ueber ``.qea``.

Ablauf einer Anfrage
--------------------
1. ``POST /build`` nimmt das Formular (multipart/form-data) entgegen, prueft
   Grenzen und Felder, legt ein Arbeitsverzeichnis je Anfrage an und startet
   den Lauf in einem eigenen Thread. Antwort: ``202`` mit Auftrags-ID.
2. ``GET /api/jobs/<id>`` liefert Zustand und Protokollzeilen (Fortschritt).
3. ``GET /api/jobs/<id>/<datei>`` liefert ``.qea``, ``findings.json``,
   ``quellen.json`` oder das ZIP. Erlaubt sind nur die Namen aus dem
   Manifest des Auftrags -- nie ein Pfad aus der Anfrage.
4. ``GET /api/jobs/<id>/viewer`` (Alias ``/job/<id>/viewer``) baut aus der
   erzeugten ``.qea`` die grafische Modellansicht on the fly und liefert sie
   als eine selbsttragende HTML-Seite. Kein Netz, kein zweiter Build.

Betriebsgrenzen (alle einstellbar)
----------------------------------
* Upload-Grenze (Default 25 MB): groessere Anfragen werden mit ``413`` und
  Klartextmeldung abgelehnt, bevor der Rumpf gelesen wird.
* Zeitlimit je Lauf (Default 120 s): der Kindprozess wird danach beendet,
  das Arbeitsverzeichnis spaeter aufgeraeumt.
* Ein Arbeitsverzeichnis je Anfrage unter ``<workdir>/job-*``; es wird nach
  dem Download, spaetestens nach ``job_ttl`` Sekunden, geloescht.
* Hoechstens ``max_jobs`` Laeufe gleichzeitig, sonst ``429``.

Sicherheit
----------
* Kein Verzeichnis-Listing, kein Ausliefern von Dateien aus dem Baum: nur
  ``/``, ``/healthz``, ``/build`` und die Auftragspfade existieren.
* Hochgeladene Dateinamen werden sanitisiert und **nicht** als Pfad benutzt;
  auf Platte liegen feste Namen (``input/technologie.xml``, ``input/text.txt``).
* Zugangsdaten (API-Schluessel) gehen nur ueber die Umgebung an den
  Kindprozess, erscheinen nicht in Kommandozeile, Protokoll oder Antwort.
* Basis-URLs mit Benutzer/Passwort werden abgelehnt.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote, unquote, urlsplit

import viewer_html

__all__ = [
    "Config",
    "Job",
    "RequestError",
    "WebError",
    "WebServer",
    "make_server",
    "parse_multipart",
    "sanitize_filename",
]

DEFAULT_MAX_UPLOAD = 25 * 1024 * 1024
DEFAULT_MAX_SECONDS = 120.0
DEFAULT_MAX_JOBS = 2
DEFAULT_JOB_TTL = 600.0
MAX_LOG_LINES = 400
MAX_FINDINGS_SHOWN = 200
MAX_FIELD_CHARS = 2048
MAX_TEXT_CHARS = 4 * 1024 * 1024
MAX_API_KEY_CHARS = 512
ZIP_NAME = "ergebnis.zip"
# Die Modellansicht bringt Stil und Skript inline mit (eine Datei, kein Netz).
VIEWER_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
# Muss zu extract.DEFAULT_PACKAGE passen; tests/test_webui.py prueft das.
DEFAULT_PACKAGE_NAME = "Architektur"
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-()]{0,79}$")
MDG_SUFFIXES = (".xml", ".mdg")
TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".docx", ".pdf")
_RESULT_RE = re.compile(
    r"(?P<elements>\d+) Elemente, (?P<connectors>\d+) Beziehungen, "
    r"(?P<errors>\d+) Fehler, (?P<warnings>\d+) Warnungen"
)
_PROVENANCE_RE = re.compile(r"(\d+) Herkunfts-Tags")
_DIGEST_RE = re.compile(r"sha256 ([0-9a-f]{64})")
_STEP_RE = re.compile(r"^\[(\d)/6\]")
_ALLOWED_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_BOUNDARY = re.compile(r'(?:^|;)\s*boundary\s*=\s*"?([^";]+)"?', re.IGNORECASE)


class WebError(RuntimeError):
    """Server konnte nicht starten oder Arbeitsverzeichnis ist unbrauchbar."""


class RequestError(ValueError):
    """Ungueltige Anfrage. ``status`` bestimmt die HTTP-Antwort."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# Dateinamen
# --------------------------------------------------------------------------


def sanitize_filename(name: str | None, *, default: str = "upload.bin", max_length: int = 80) -> str:
    """Nur den Dateinamen behalten und auf ``[A-Za-z0-9._-]`` begrenzen.

    Pfadtrenner (``/``, ``\\``) fliegen samt allem davor weg, Umlaute werden
    transliteriert, Steuerzeichen und Sonderzeichen zu ``_``. Ein leerer Rest
    faellt auf ``default`` zurueck. Das Ergebnis ist nie absolut, beginnt nie
    mit ``.`` und enthaelt keinen Pfadtrenner.
    """
    raw = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = _ALLOWED_NAME.sub("_", raw)
    raw = re.sub(r"_{2,}", "_", raw).strip("._-")
    if not raw:
        return default
    if len(raw) > max_length:
        stem, dot, suffix = raw.rpartition(".")
        if dot and 0 < len(suffix) <= 10:
            keep = max(1, max_length - len(suffix) - 1)
            stem = stem[:keep].rstrip("._-") or "datei"
            raw = f"{stem}.{suffix}"
        else:
            raw = raw[:max_length].rstrip("._-")
        if not raw:
            return default
    return raw


# --------------------------------------------------------------------------
# multipart/form-data (stdlib; cgi ist ab Python 3.13 entfernt)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadPart:
    name: str
    filename: str | None
    content_type: str
    data: bytes


def _disposition_param(header: str, parameter: str) -> str | None:
    pattern = re.compile(r'(?:^|;)\s*' + re.escape(parameter) + r'\s*=\s*"?([^";]*)"?', re.I)
    match = pattern.search(header)
    return match.group(1) if match else None


def parse_multipart(body: bytes, content_type: str) -> dict[str, list[UploadPart]]:
    """``multipart/form-data`` zerlegen. Bricht bei ungueltigem Aufbau laut ab."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise RequestError(
            "Content-Type muss multipart/form-data sein (Formular senden, nicht JSON).",
            status=415,
        )
    boundary_match = _BOUNDARY.search(content_type)
    if boundary_match is None:
        raise RequestError("multipart/form-data ohne boundary.")
    boundary = boundary_match.group(1).encode("latin-1", "replace")
    if not boundary:
        raise RequestError("multipart/form-data mit leerer boundary.")

    delimiter = b"--" + boundary
    if delimiter not in body:
        raise RequestError("Formulardaten ohne erkennbare Trennlinie (boundary).")

    parts: dict[str, list[UploadPart]] = {}
    for chunk in body.split(delimiter)[1:]:
        if chunk.startswith(b"--"):
            break
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]
        if not chunk:
            continue
        if b"\r\n\r\n" not in chunk:
            raise RequestError("Formularteil ohne Kopfzeilen-Ende.")
        head, data = chunk.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        elif data.endswith(b"\n"):
            data = data[:-1]

        headers: dict[str, str] = {}
        for line in head.decode("utf-8", "replace").split("\r\n"):
            if not line:
                continue
            if ":" not in line:
                raise RequestError("Formularteil mit unlesbarer Kopfzeile.")
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        disposition = headers.get("content-disposition", "")
        if "form-data" not in disposition.lower():
            raise RequestError("Formularteil ohne Content-Disposition: form-data.")
        name = _disposition_param(disposition, "name")
        if not name:
            raise RequestError("Formularteil ohne Feldnamen.")
        filename = _disposition_param(disposition, "filename")
        parts.setdefault(name, []).append(
            UploadPart(
                name=name,
                filename=filename,
                content_type=headers.get("content-type", "application/octet-stream"),
                data=data,
            )
        )
    if not parts:
        raise RequestError("Formular war leer.")
    return parts


def _field(
    parts: Mapping[str, Sequence[UploadPart]],
    name: str,
    default: str = "",
    *,
    max_chars: int = MAX_FIELD_CHARS,
) -> str:
    values = parts.get(name)
    if not values:
        return default
    try:
        text = values[0].data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RequestError(f"Feld {name}: kein UTF-8 ({exc})") from exc
    text = text.strip()
    if max_chars and len(text) > max_chars:
        raise RequestError(
            f"Feld {name}: zu lang ({len(text)} Zeichen, Grenze {max_chars})."
        )
    return text


def _upload(parts: Mapping[str, Sequence[UploadPart]], name: str) -> UploadPart | None:
    """Erste Datei des Feldes. Ein leeres Dateifeld des Browsers (filename="")
    zaehlt als "keine Datei"; eine wirklich leere Datei hat einen Namen."""
    for part in parts.get(name, ()):
        if part.filename:
            return part
    return None


# --------------------------------------------------------------------------
# Anfrage vorbereiten
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Prepared:
    backend: str
    package: str
    mdg_path: Path
    text_path: Path
    out_name: str
    answer_path: Path | None = None
    model: str = ""
    base_url: str = ""
    api_key: str = ""


def check_base_url(url: str) -> str:
    """Basis-URL pruefen: http(s), Host, keine Zugangsdaten in der URL."""
    if len(url) > 500:
        raise RequestError("Basis-URL ist zu lang (Grenze 500 Zeichen).")
    if any(char.isspace() for char in url):
        raise RequestError("Basis-URL enthaelt Leerzeichen.")
    split = urlsplit(url)
    if split.scheme not in ("http", "https"):
        raise RequestError("Basis-URL muss mit http:// oder https:// beginnen.")
    if not split.hostname:
        raise RequestError("Basis-URL ohne Host.")
    if split.username or split.password:
        raise RequestError(
            "Zugangsdaten in der Basis-URL sind nicht erlaubt -- "
            "bitte das Feld API-Schluessel benutzen."
        )
    return url.rstrip("/")


def prepare_request(
    parts: Mapping[str, Sequence[UploadPart]], job_dir: Path, assets: Path
) -> Prepared:
    """Formular pruefen und alle Eingaben unter ``job_dir/input`` ablegen.

    Auf Platte landen ausschliesslich feste Namen; der hochgeladene Dateiname
    wird nur sanitisiert und fuer den Download-Namen der ``.qea`` verwendet.
    """
    backend = _field(parts, "backend", "datei").lower()
    if backend not in ("datei", "openai", "ollama"):
        raise RequestError(f"Unbekanntes Backend {backend!r} (erlaubt: datei, openai, ollama).")

    package = _field(parts, "package", DEFAULT_PACKAGE_NAME) or DEFAULT_PACKAGE_NAME
    if not PACKAGE_RE.match(package):
        raise RequestError(
            "Paketname: erlaubt sind Buchstaben, Ziffern, Leerzeichen und . _ - ( ) "
            "mit hoechstens 80 Zeichen, beginnend mit Buchstabe oder Ziffer."
        )

    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # -- Technologie -------------------------------------------------------
    source = _field(parts, "mdg_source", "beispiel")
    if source == "beispiel":
        bundled = assets / "mdg_admbw_auszug.xml"
        if not bundled.is_file():
            raise RequestError(
                "Der mitgelieferte Technologie-Auszug fehlt in dieser Installation "
                "(examples/offline/mdg_admbw_auszug.xml). Bitte eigene XML hochladen.",
                status=500,
            )
        mdg_suffix = ".xml"
        mdg_bytes = bundled.read_bytes()
        mdg_path = input_dir / f"technologie{mdg_suffix}"
        mdg_path.write_bytes(mdg_bytes)
    elif source == "upload":
        upload = _upload(parts, "mdg")
        if upload is None:
            raise RequestError("mdg_source=upload, aber keine XML-Datei im Feld 'mdg'.")
        if not upload.data:
            raise RequestError("Die hochgeladene Technologie-Datei ist leer.")
        name = sanitize_filename(upload.filename, default="technologie.xml")
        suffix = Path(name).suffix.lower()
        if suffix not in MDG_SUFFIXES:
            raise RequestError(
                f"Technologie-Datei: Endung {suffix or '(ohne)'} wird nicht gelesen "
                f"(erlaubt: .xml, .mdg)."
            )
        mdg_path = input_dir / f"technologie{suffix}"
        mdg_path.write_bytes(upload.data)
    else:
        raise RequestError("mdg_source muss 'beispiel' oder 'upload' sein.")

    # -- Text --------------------------------------------------------------
    text_value = _field(parts, "text", max_chars=MAX_TEXT_CHARS)
    text_upload = _upload(parts, "textdatei")
    if text_upload is not None:
        if not text_upload.data:
            raise RequestError("Die hochgeladene Textdatei ist leer.")
        name = sanitize_filename(text_upload.filename, default="text.txt")
        suffix = Path(name).suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            raise RequestError(
                f"Textdatei: Endung {suffix or '(ohne)'} wird nicht gelesen "
                f"(erlaubt: .txt, .md, .docx, .pdf)."
            )
        text_bytes = text_upload.data
        stem = Path(name).stem or "modell"
        text_path = input_dir / f"text{suffix}"
        text_path.write_bytes(text_bytes)
    elif text_value:
        suffix = ".txt"
        text_bytes = text_value.encode("utf-8")
        stem = "modell"
        text_path = input_dir / f"text{suffix}"
        text_path.write_bytes(text_bytes)
    else:
        raise RequestError(
            "Kein Text: bitte Prosa einfuegen oder eine .txt/.md/.docx/.pdf-Datei hochladen."
        )
    if not text_bytes.strip():
        raise RequestError("Der Text ist leer -- daraus entsteht kein Modell.")

    out_name = sanitize_filename(f"{stem}.qea", default="modell.qea", max_length=90)
    if not out_name.endswith(".qea"):
        out_name = "modell.qea"

    # -- Extraktion --------------------------------------------------------
    answer_path: Path | None = None
    model = ""
    base_url = ""
    api_key = ""
    if backend == "datei":
        bundled_answer = assets / "antwort.json"
        if not bundled_answer.is_file():
            raise RequestError(
                "Das Datei-Backend braucht die mitgelieferte Beispielantwort "
                "(examples/offline/antwort.json); sie fehlt in dieser Installation. "
                "Bitte einen Modell-Endpunkt waehlen.",
                status=500,
            )
        answer_path = job_dir / "antwort.json"
        shutil.copyfile(bundled_answer, answer_path)
    else:
        model = _field(parts, "model")
        if not model:
            raise RequestError("Modell-Endpunkt gewaehlt, aber kein Modellname angegeben.")
        base_url = _field(parts, "base_url")
        if base_url:
            base_url = check_base_url(base_url)
        api_key = _field(parts, "api_key")
        if len(api_key) > MAX_API_KEY_CHARS:
            raise RequestError(f"API-Schluessel: zu lang (Grenze {MAX_API_KEY_CHARS} Zeichen).")
        if "\n" in api_key or "\r" in api_key:
            raise RequestError("API-Schluessel enthaelt einen Zeilenumbruch.")

    return Prepared(
        backend=backend,
        package=package,
        mdg_path=mdg_path,
        text_path=text_path,
        out_name=out_name,
        answer_path=answer_path,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )


# --------------------------------------------------------------------------
# Kindprozess: derselbe Aufruf wie die Kommandozeile
# --------------------------------------------------------------------------


def build_command(prepared: Prepared, job_dir: Path, max_seconds: float) -> list[str]:
    """Kommandozeile des Laufs. Einziger Weg zum Kern, auch aus der Weboberflaeche."""
    http_timeout = max(5.0, float(max_seconds) - 10.0)
    command = [
        sys.executable,
        "-m",
        "eam_ai",
        "build",
        "--mdg",
        str(prepared.mdg_path),
        "--text",
        str(prepared.text_path),
        "--out",
        str(job_dir / prepared.out_name),
        "--package",
        prepared.package,
        "--backend",
        prepared.backend,
        "--findings",
        str(job_dir / "findings.json"),
        "--quellen",
        str(job_dir / "quellen.json"),
        "--timeout",
        f"{http_timeout:g}",
    ]
    if prepared.backend == "datei":
        if prepared.answer_path is None:  # pragma: no cover - prepare_request sichert das
            raise WebError("Datei-Backend ohne Antwortdatei")
        command += ["--antwort", str(prepared.answer_path)]
    else:
        command += ["--model", prepared.model]
        if prepared.base_url:
            command += ["--base-url", prepared.base_url]
    return command


def build_environment(prepared: Prepared) -> dict[str, str]:
    """Umgebung des Kindprozesses. Zugangsdaten nur hier, nie in Argumenten."""
    environment = dict(os.environ)
    module_root = str(Path(__file__).resolve().parent)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = module_root + (os.pathsep + existing if existing else "")
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if prepared.backend == "datei":
        # Der Datei-Lauf braucht kein Netz und keinen Schluessel.
        environment.pop("OPENAI_API_KEY", None)
    elif prepared.api_key:
        environment["OPENAI_API_KEY"] = prepared.api_key
    return environment


def parse_result_line(line: str) -> dict[str, Any]:
    """Zahlen aus der kanonischen Ergebniszeile der CLI lesen."""
    match = _RESULT_RE.search(line or "")
    if match is None:
        return {}
    summary: dict[str, Any] = {key: int(value) for key, value in match.groupdict().items()}
    provenance = _PROVENANCE_RE.search(line)
    if provenance:
        summary["provenance_tags"] = int(provenance.group(1))
    digest = _DIGEST_RE.search(line)
    if digest:
        summary["sha256"] = digest.group(1)
    return summary


def _load_findings(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)][:MAX_FINDINGS_SHOWN]


def _write_zip(target: Path, paths: Sequence[Path]) -> Path:
    """ZIP mit festen Zeitstempeln -- derselbe Lauf ergibt dieselben Bytes."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths, key=lambda item: item.name):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return target


# --------------------------------------------------------------------------
# Auftrag
# --------------------------------------------------------------------------


@dataclass
class Job:
    token: str
    directory: Path
    backend: str = ""
    state: str = "running"  # running | done | failed | expired
    log: list[str] = field(default_factory=list)
    error: str | None = None
    result_line: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    zip_name: str | None = None
    viewer_page: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def scrub(self, text: str, *, secret: str = "") -> str:
        """Interne Pfade und Geheimnisse aus einer Zeile entfernen."""
        text = text.replace(f"{self.directory}/", "").replace(str(self.directory), ".")
        if secret:
            text = text.replace(secret, "***")
        return text

    def add_log(self, line: str, *, secret: str = "") -> None:
        text = line.rstrip()
        if not text:
            return
        # Interne Pfade nicht in die Oberflaeche tragen: der Nutzer sieht nur
        # Dateinamen, keine Serverstruktur.
        text = self.scrub(text, secret=secret)
        self.log.append(text[:2000])
        if len(self.log) > MAX_LOG_LINES:
            del self.log[: len(self.log) - MAX_LOG_LINES]

    def qea_name(self) -> str | None:
        """Name der erzeugten .qea im Manifest (oder None)."""
        for entry in self.files:
            name = str(entry.get("name", ""))
            if name.lower().endswith(".qea"):
                return name
        return None

    def as_json(self) -> dict[str, Any]:
        links: dict[str, Any] = {"files": []}
        if self.zip_name is not None:
            links["zip"] = f"/api/jobs/{self.token}/{quote(self.zip_name)}"
        if self.state == "done" and self.qea_name():
            links["viewer"] = f"/api/jobs/{self.token}/viewer"
        links["files"] = [
            {
                "name": entry["name"],
                "size": entry["size"],
                "href": f"/api/jobs/{self.token}/{quote(entry['name'])}",
            }
            for entry in self.files
        ]
        return {
            "job": self.token,
            "state": self.state,
            "backend": self.backend,
            "log": list(self.log),
            "error": self.error,
            "result_line": self.result_line,
            "summary": dict(self.summary),
            "findings": list(self.findings),
            "files": list(self.files),
            "links": links,
            "elapsed": round((self.finished or time.time()) - self.created, 2),
        }


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------


@dataclass(kw_only=True)
class Config:
    workdir: Path
    assets: Path
    max_upload: int = DEFAULT_MAX_UPLOAD
    max_seconds: float = DEFAULT_MAX_SECONDS
    max_jobs: int = DEFAULT_MAX_JOBS
    job_ttl: float = DEFAULT_JOB_TTL
    version: str = ""
    log: Callable[[str], None] | None = None


class WebServer(ThreadingHTTPServer):
    """HTTP-Server mit Auftragsverwaltung. ``stop()`` nach ``shutdown()`` rufen."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], config: Config) -> None:
        self.config = config
        self.jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(config.max_jobs)
        self._stop = threading.Event()
        config.workdir.mkdir(parents=True, exist_ok=True)
        super().__init__(address, Handler)
        # Erst nach erfolgreichem bind() ein Verzeichnis anlegen: ein belegter
        # Port hinterlaesst so keine Reste.
        self.workdir = Path(tempfile.mkdtemp(prefix="sitzung-", dir=str(config.workdir)))
        self._sweeper = threading.Thread(
            target=self._sweep_loop, name="eam-ai-aufraeumen", daemon=True
        )
        self._sweeper.start()

    # -- Betrieb -----------------------------------------------------------
    def log(self, message: str) -> None:
        if self.config.log is not None:
            self.config.log(message)
        else:
            print(message, file=sys.stderr, flush=True)

    def handle_error(self, request: Any, client_address: Any) -> None:
        error = sys.exc_info()[1]
        host = client_address[0] if isinstance(client_address, tuple) else client_address
        if isinstance(error, (ConnectionResetError, BrokenPipeError)):
            self.log(f"Verbindung von {host} abgebrochen")
            return
        self.log(f"Fehler bei {host}: {error!r}")

    def stop(self) -> None:
        """Aufraeumen nach ``serve_forever()``/``shutdown()``. Idempotent."""
        self._stop.set()
        try:
            self.server_close()
        except OSError:
            pass
        with self._lock:
            jobs = list(self.jobs.values())
            self.jobs.clear()
        for job in jobs:
            shutil.rmtree(job.directory, ignore_errors=True)
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _sweep_loop(self) -> None:
        while not self._stop.wait(10.0):
            self.purge_expired()

    def purge_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            for token, job in list(self.jobs.items()):
                if job.finished is None or now - job.finished < self.config.job_ttl:
                    continue
                shutil.rmtree(job.directory, ignore_errors=True)
                job.state = "expired"
                del self.jobs[token]
                removed += 1
        return removed

    # -- Auftraege ---------------------------------------------------------
    def get_job(self, token: str) -> Job | None:
        with self._lock:
            return self.jobs.get(token)

    def start_job(self, parts: Mapping[str, Sequence[UploadPart]]) -> Job:
        if not self._slots.acquire(blocking=False):
            raise RequestError(
                f"Zu viele Laeufe gleichzeitig (Grenze {self.config.max_jobs}). "
                "Bitte kurz warten und erneut starten.",
                status=429,
            )
        token = secrets.token_urlsafe(12)
        try:
            job_dir = Path(tempfile.mkdtemp(prefix=f"job-{token[:6]}-", dir=str(self.workdir)))
            try:
                prepared = prepare_request(parts, job_dir, self.config.assets)
            except BaseException:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise
        except BaseException:
            self._slots.release()
            raise

        job = Job(token=token, directory=job_dir, backend=prepared.backend)
        with self._lock:
            self.jobs[token] = job
        thread = threading.Thread(
            target=self._run_job,
            args=(job, prepared),
            name=f"eam-ai-{token[:6]}",
            daemon=True,
        )
        thread.start()
        return job

    def _run_job(self, job: Job, prepared: Prepared) -> None:
        secret = prepared.api_key

        def log(line: str) -> None:
            job.add_log(line, secret=secret)

        try:
            log(f"Lauf gestartet: Backend {prepared.backend}, Paket {prepared.package!r}")
            command = build_command(prepared, job.directory, self.config.max_seconds)
            environment = build_environment(prepared)
            process = subprocess.Popen(
                command,
                cwd=str(job.directory),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            stdout_lines: list[str] = []

            def read_stdout() -> None:
                assert process.stdout is not None
                for line in process.stdout:
                    stdout_lines.append(line.rstrip("\n"))

            def read_stderr() -> None:
                assert process.stderr is not None
                for line in process.stderr:
                    log(line)

            readers = [
                threading.Thread(target=read_stdout, name="eam-ai-stdout", daemon=True),
                threading.Thread(target=read_stderr, name="eam-ai-stderr", daemon=True),
            ]
            for reader in readers:
                reader.start()

            timed_out = False
            try:
                process.wait(timeout=self.config.max_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover - sehr selten
                    pass
            for reader in readers:
                reader.join(timeout=5)

            if timed_out:
                self._fail(
                    job,
                    f"Zeitlimit von {self.config.max_seconds:g} s ueberschritten -- "
                    "der Lauf wurde abgebrochen. Kuerzeren Text oder schnelleres Modell waehlen.",
                )
                return

            code = process.returncode
            job.result_line = job.scrub(
                next((line.strip() for line in reversed(stdout_lines) if line.strip()), ""),
                secret=secret,
            )
            job.summary = parse_result_line(job.result_line)
            job.findings = _load_findings(job.directory / "findings.json")
            out_path = job.directory / prepared.out_name
            quellen_path = job.directory / "quellen.json"
            findings_path = job.directory / "findings.json"

            if code != 0 or not out_path.is_file():
                message = next(
                    (line for line in reversed(job.log) if line.lstrip().startswith("FEHLER:")),
                    f"Lauf fehlgeschlagen (Exit {code or 'unbekannt'}), keine .qea erzeugt.",
                )
                files = [findings_path] if findings_path.is_file() else []
                self._fail(job, message, files=files)
                return

            zip_path = _write_zip(
                job.directory / ZIP_NAME,
                [out_path, findings_path, quellen_path],
            )
            job.files = _manifest([out_path, findings_path, quellen_path])
            job.zip_name = zip_path.name
            job.state = "done"
            job.finished = time.time()
            log(f"Fertig: {job.result_line}")
        except (OSError, WebError) as exc:
            self._fail(job, f"Lauf konnte nicht gestartet werden: {exc}")
        except Exception as exc:  # pragma: no cover - letzte Sicherung, nie still
            self._fail(job, f"Unerwarteter Fehler im Lauf: {type(exc).__name__}: {exc}")
        finally:
            if job.finished is None:
                job.finished = time.time()
            self._slots.release()

    def _fail(self, job: Job, message: str, *, files: Sequence[Path] = ()) -> None:
        job.state = "failed"
        job.error = message
        job.finished = time.time()
        if files:
            job.files = _manifest(files)
        job.add_log(f"FEHLER: {message}")


def _manifest(paths: Sequence[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        data = path.read_bytes()
        entries.append(
            {
                "name": path.name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return entries


def make_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    max_upload: int | None = None,
    max_seconds: float | None = None,
    max_jobs: int | None = None,
    job_ttl: float | None = None,
    workdir: str | Path | None = None,
    assets: str | Path | None = None,
    version: str = "",
    log: Callable[[str], None] | None = None,
) -> WebServer:
    """Server bauen (nicht starten). ``port=0`` waehlt einen freien Port."""
    upload = DEFAULT_MAX_UPLOAD if max_upload is None else int(max_upload)
    seconds = DEFAULT_MAX_SECONDS if max_seconds is None else float(max_seconds)
    jobs = DEFAULT_MAX_JOBS if max_jobs is None else int(max_jobs)
    ttl = DEFAULT_JOB_TTL if job_ttl is None else float(job_ttl)
    if upload <= 0:
        raise WebError("max_upload muss groesser als 0 sein")
    if seconds <= 0:
        raise WebError("max_seconds muss groesser als 0 sein")
    if jobs <= 0:
        raise WebError("max_jobs muss groesser als 0 sein")
    if ttl <= 0:
        raise WebError("job_ttl muss groesser als 0 sein")

    root = Path(workdir) if workdir is not None else Path(tempfile.gettempdir()) / "eam-ai-web"
    asset_dir = Path(assets) if assets is not None else Path(__file__).resolve().parent / "examples" / "offline"

    config = Config(
        workdir=root,
        assets=asset_dir,
        max_upload=upload,
        max_seconds=seconds,
        max_jobs=jobs,
        job_ttl=ttl,
        version=version,
        log=log,
    )
    try:
        return WebServer((host, port), config)
    except OSError as exc:
        raise WebError(f"Server kann nicht auf {host}:{port} starten: {exc}") from exc


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server: WebServer
    server_version = "eam-ai-web"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- Hilfen ------------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        self.server.log(f"{self.address_string()} {format % args}")

    def _common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")

    def _send_bytes(
        self,
        status: int,
        data: bytes,
        content_type: str,
        *,
        extra: Mapping[str, str] | None = None,
        close: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._common_headers()
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        if close:
            self.close_connection = True
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    def _send_json(self, status: int, payload: Mapping[str, Any], *, close: bool = False) -> None:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._send_bytes(status, data, "application/json; charset=utf-8", close=close)

    def _error(self, status: int, message: str, *, close: bool = False) -> None:
        self._send_json(status, {"ok": False, "error": message}, close=close)

    # -- GET ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - Vorgabe von http.server
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            page = PAGE.replace("{{VERSION}}", html.escape(self.server.config.version))
            self._send_bytes(
                HTTPStatus.OK,
                page.encode("utf-8"),
                "text/html; charset=utf-8",
                extra={
                    "Content-Security-Policy": (
                        "default-src 'none'; style-src 'unsafe-inline'; "
                        "script-src 'unsafe-inline'; connect-src 'self'; "
                        "form-action 'self'; img-src data:; base-uri 'none'"
                    )
                },
            )
            return
        if path == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "version": self.server.config.version,
                    "beispiel": (self.server.config.assets / "mdg_admbw_auszug.xml").is_file(),
                    "max_upload_bytes": self.server.config.max_upload,
                    "max_seconds": self.server.config.max_seconds,
                    "max_jobs": self.server.config.max_jobs,
                },
            )
            return
        if path.startswith("/job/"):
            rest = [segment for segment in path[len("/job/") :].split("/") if segment]
            if len(rest) == 2 and rest[1] == "viewer":
                self._job_viewer(unquote(rest[0]))
                return
        if path.startswith("/api/jobs/"):
            rest = [segment for segment in path[len("/api/jobs/") :].split("/") if segment]
            if len(rest) == 1:
                self._job_status(unquote(rest[0]))
                return
            if len(rest) == 2:
                if rest[1] == "viewer":
                    self._job_viewer(unquote(rest[0]))
                else:
                    self._job_file(unquote(rest[0]), unquote(rest[1]))
                return
        self._error(
            HTTPStatus.NOT_FOUND,
            "Nicht gefunden. Erlaubt sind /, /healthz, /build, /api/jobs/<id>, "
            "/api/jobs/<id>/<datei> und /api/jobs/<id>/viewer.",
        )

    def _job_status(self, token: str) -> None:
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        self._send_json(HTTPStatus.OK, job.as_json())

    def _job_viewer(self, token: str) -> None:
        """Modellansicht aus der erzeugten .qea -- eine HTML-Datei, kein Netz."""
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        if job.state == "running":
            self._error(HTTPStatus.CONFLICT, "Der Lauf ist noch nicht fertig.")
            return
        name = job.qea_name()
        if job.state != "done" or name is None:
            self._error(HTTPStatus.NOT_FOUND, "Zu diesem Auftrag gibt es kein Modell.")
            return
        page = job.viewer_page
        if page is None:
            try:
                page = viewer_html.build_html(job.directory / name)
            except viewer_html.ViewerError as exc:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Modellansicht nicht lesbar: {exc}")
                return
            job.viewer_page = page
        self._send_bytes(
            HTTPStatus.OK,
            page.encode("utf-8"),
            "text/html; charset=utf-8",
            extra={"Content-Security-Policy": VIEWER_CSP},
        )

    def _job_file(self, token: str, name: str) -> None:
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        if job.state == "running":
            self._error(HTTPStatus.CONFLICT, "Der Lauf ist noch nicht fertig.")
            return
        allowed = {entry["name"] for entry in job.files}
        if job.zip_name is not None:
            allowed.add(job.zip_name)
        # Nur Namen aus dem Manifest: kein Pfad aus der Anfrage erreicht das Dateisystem.
        if name not in allowed:
            self._error(HTTPStatus.NOT_FOUND, "Diese Datei gehoert nicht zu diesem Auftrag.")
            return
        target = job.directory / name
        try:
            data = target.read_bytes()
        except OSError as exc:
            self._error(HTTPStatus.GONE, f"Datei nicht mehr vorhanden: {exc}")
            return
        self._send_bytes(
            HTTPStatus.OK,
            data,
            "application/octet-stream",
            extra={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    # -- POST --------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - Vorgabe von http.server
        path = urlsplit(self.path).path
        if path != "/build":
            self._error(HTTPStatus.NOT_FOUND, "Nur /build nimmt Daten an.")
            return
        try:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length fehlt -- Formular ohne Groesse wird abgelehnt.")
                return
            try:
                length = int(raw_length)
            except ValueError:
                self._error(HTTPStatus.BAD_REQUEST, "Content-Length ist keine Zahl.")
                return
            if length <= 0:
                self._error(HTTPStatus.BAD_REQUEST, "Leerer Anfragekoerper.")
                return
            if length > self.server.config.max_upload:
                limit_mb = self.server.config.max_upload / (1024 * 1024)
                self._error(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    f"Upload zu gross: {length / (1024 * 1024):.1f} MB. "
                    f"Grenze: {limit_mb:.0f} MB. Bitte Technologie oder Text kuerzen.",
                    close=True,
                )
                return
            body = self._read_body(length)
            parts = parse_multipart(body, self.headers.get("Content-Type", ""))
            job = self.server.start_job(parts)
        except RequestError as exc:
            self._error(exc.status, str(exc))
            return
        except OSError as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Arbeitsverzeichnis nicht nutzbar: {exc}")
            return
        self._send_json(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "job": job.token,
                "status": f"/api/jobs/{job.token}",
                "backend": job.backend,
            },
        )

    def _read_body(self, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            block = self.rfile.read(min(65536, remaining))
            if not block:
                raise RequestError("Verbindung beim Upload abgebrochen.", status=400)
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks)


# --------------------------------------------------------------------------
# Seite
# --------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EAM AI Suite Python &mdash; Prosa + Technologie zu .qea</title>
<style>
:root {
  --bg: #0f172a; --card: #16213b; --line: #26324e; --text: #e6edf7;
  --muted: #9aa8c0; --accent: #3b82f6; --ok: #22c55e; --bad: #ef4444;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 1.8rem; margin: 0 0 6px; letter-spacing: -0.02em; }
h2 { font-size: 1.05rem; margin: 0 0 14px; color: var(--text); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.lead { color: var(--muted); margin: 0 0 26px; }
.lead code { color: #c7d6ee; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 20px; margin-bottom: 18px; }
label { display: block; margin: 10px 0; color: var(--text); }
label.row { display: flex; gap: 10px; align-items: center; cursor: pointer; }
label.file { color: var(--muted); }
input[type=text], input[type=password], input[type=file], select, textarea {
  width: 100%; margin-top: 6px; padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--line); background: #0d1629; color: var(--text);
  font: inherit; }
textarea { resize: vertical; min-height: 150px; font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 14px; }
input:focus, select:focus, textarea:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
input[type=radio] { width: auto; margin: 0; }
.hint { color: var(--muted); font-size: 0.9rem; margin: 6px 0 12px; }
button { font: inherit; font-weight: 600; border: 0; border-radius: 9px;
  padding: 12px 22px; background: var(--accent); color: white; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: progress; }
button.link { background: none; color: var(--accent); padding: 0; font-weight: 500;
  text-decoration: underline; }
.actions { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.limits { color: var(--muted); font-size: 0.85rem; }
.bar { height: 8px; background: #0d1629; border-radius: 99px; overflow: hidden; margin-bottom: 14px; }
#bar { height: 100%; width: 0; background: var(--accent); transition: width 0.4s ease; }
#log, #result-log, #error-log { margin: 0; padding-left: 22px; color: var(--muted);
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; max-height: 220px;
  overflow: auto; }
#log li, #result-log li, #error-log li { margin: 2px 0; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; color: var(--muted);
  overflow-wrap: anywhere; }
.downloads { display: flex; gap: 10px; flex-wrap: wrap; margin: 16px 0; }
.downloads a { display: inline-block; text-decoration: none; color: var(--text);
  border: 1px solid var(--line); background: #0d1629; border-radius: 9px; padding: 10px 14px; }
.downloads a.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.error { border-color: var(--bad); }
.error h2 { color: var(--bad); }
details { margin-top: 14px; }
summary { cursor: pointer; color: var(--muted); }
#findings { margin: 10px 0 0; padding-left: 20px; font-size: 13px; color: var(--muted);
  max-height: 260px; overflow: auto; }
#findings li { margin: 3px 0; }
.badge { display: inline-block; font-size: 12px; color: var(--muted); margin-left: 8px; }
</style>
</head>
<body>
<main>
<h1>EAM AI Suite Python <span class="badge">{{VERSION}}</span></h1>
<p class="lead">Prosa und Technologie hinein, eine gepr&uuml;fte <code>.qea</code> heraus.
Gleicher Kern wie die Kommandozeile: Technologie laden, Text lesen, extrahieren,
validieren, exportieren.</p>

<form id="f" autocomplete="off">
  <section class="card">
    <h2>1. Technologie</h2>
    <label class="row"><input type="radio" name="mdg_source" value="beispiel" checked>
      Mitgelieferter Auszug (NAFv4-ADMBw, synthetisch)</label>
    <label class="row"><input type="radio" name="mdg_source" value="upload">
      Eigene MDG-/Technologie-XML</label>
    <label id="mdg-wrap" class="file" hidden>XML-Datei
      <input type="file" name="mdg" accept=".xml,.mdg,application/xml"></label>
  </section>

  <section class="card">
    <h2>2. Text</h2>
    <textarea id="text" name="text" rows="8"
      placeholder="Architektur-Prosa hier einf&uuml;gen &hellip;"></textarea>
    <p class="hint">Oder Datei (.txt, .md, .docx, .pdf) &ndash; die Datei hat Vorrang.
      <button type="button" id="sample" class="link">Beispieltext einsetzen</button></p>
    <label class="file">Textdatei
      <input type="file" name="textdatei" accept=".txt,.md,.docx,.pdf,text/plain,application/pdf"></label>
  </section>

  <section class="card">
    <h2>3. Sprachextraktion</h2>
    <label>Backend
      <select name="backend" id="backend">
        <option value="datei">Datei (offline, mitgelieferte Beispielantwort)</option>
        <option value="openai" selected>OpenAI-kompatibler Endpunkt (DeepSeek)</option>
        <option value="ollama">Ollama</option>
      </select>
    </label>
    <div id="model-fields" hidden>
      <label>Basis-URL
        <input type="text" name="base_url" value="https://api.deepseek.com/v1"
               placeholder="https://api.deepseek.com/v1"></label>
      <label>Modell
        <input type="text" name="model" value="deepseek-flash"
               placeholder="deepseek-flash"></label>
      <label>API-Schl&uuml;ssel (optional, wird nicht gespeichert)
        <input type="password" name="api_key" autocomplete="new-password"></label>
      <p class="hint">Der Schl&uuml;ssel geht nur an den Lauf, steht weder im Protokoll
        noch in der Antwort.</p>
    </div>
    <label>Zielpaket
      <input type="text" name="package" value="Architektur"></label>
  </section>

  <div class="actions">
    <button id="go" type="submit">Bauen</button>
    <span class="limits" id="limits">Grenzen werden geladen &hellip;</span>
  </div>
</form>

<section id="progress" class="card" hidden>
  <h2>Fortschritt</h2>
  <div class="bar"><div id="bar"></div></div>
  <ol id="log"></ol>
</section>

<section id="result" class="card" hidden>
  <h2>Ergebnis</h2>
  <p id="summary"></p>
  <p id="result-line" class="mono"></p>
  <div id="downloads" class="downloads"></div>
  <details id="findings-box" hidden>
    <summary>Findings</summary>
    <ul id="findings"></ul>
  </details>
  <details>
    <summary>Protokoll</summary>
    <ol id="result-log"></ol>
  </details>
</section>

<section id="error" class="card error" hidden>
  <h2>Fehler</h2>
  <p id="error-text"></p>
  <details id="error-log-box" hidden>
    <summary>Protokoll</summary>
    <ol id="error-log"></ol>
  </details>
</section>
</main>

<script>
const $ = (id) => document.getElementById(id);
const SAMPLE = "Der Ablauf A steuert die Faehigkeit B.\\n\\n" +
  "Die Faehigkeit B wird durch den Dienst C erbracht.\\n\\n" +
  "Der Dienst C ist ein Service.\\n";
const form = $("f");
const backend = $("backend");
let timer = null;

function show(id) { $(id).hidden = false; }
function hide(id) { $(id).hidden = true; }
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function syncBackend() {
  $("model-fields").hidden = backend.value === "datei";
}
backend.addEventListener("change", syncBackend);
syncBackend();

document.querySelectorAll("input[name=mdg_source]").forEach((radio) => {
  radio.addEventListener("change", () => {
    const chosen = document.querySelector("input[name=mdg_source]:checked").value;
    $("mdg-wrap").hidden = chosen !== "upload";
  });
});

$("sample").addEventListener("click", () => { $("text").value = SAMPLE; });

function addLog(list, text) {
  const item = document.createElement("li");
  item.textContent = text;
  list.appendChild(item);
  list.scrollTop = list.scrollHeight;
}

function renderLog(lines) {
  const list = $("log");
  list.innerHTML = "";
  let step = 0;
  (lines || []).forEach((line) => {
    addLog(list, line);
    const match = /^\\[(\\d)\\/6\\]/.exec(line);
    if (match) step = Math.max(step, Number(match[1]));
  });
  $("bar").style.width = Math.max(4, (step / 6) * 100) + "%";
}

async function poll(url) {
  for (;;) {
    let state;
    try {
      const response = await fetch(url, { cache: "no-store" });
      state = await response.json();
      if (!response.ok) throw new Error(state.error || ("HTTP " + response.status));
    } catch (error) {
      return fail(error.message);
    }
    renderLog(state.log);
    if (state.state === "done") return done(state);
    if (state.state === "failed") return fail(state.error || "Der Lauf ist fehlgeschlagen.", state);
    if (state.state === "expired") return fail("Der Auftrag ist abgelaufen. Bitte neu bauen.", state);
    await sleep(700);
  }
}

function link(href, label, primary) {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.textContent = label;
  if (primary) anchor.className = "primary";
  return anchor;
}

function size(size) {
  if (size > 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + " MB";
  if (size > 1024) return Math.round(size / 1024) + " kB";
  return size + " B";
}

function done(state) {
  $("bar").style.width = "100%";
  show("result");
  const s = state.summary || {};
  const parts = [];
  if (s.elements !== undefined) parts.push(s.elements + " Elemente");
  if (s.connectors !== undefined) parts.push(s.connectors + " Beziehungen");
  if (s.errors !== undefined) parts.push(s.errors + " Fehler");
  if (s.warnings !== undefined) parts.push(s.warnings + " Warnungen");
  if (s.provenance_tags !== undefined) parts.push(s.provenance_tags + " Herkunfts-Tags");
  $("summary").textContent = parts.length ? parts.join(", ") : "Lauf abgeschlossen.";
  $("result-line").textContent = state.result_line || "";

  const box = $("downloads");
  box.innerHTML = "";
  if (state.links && state.links.viewer) {
    const viewer = link(state.links.viewer, "Modell ansehen", true);
    viewer.target = "_blank";
    viewer.rel = "noopener";
    box.appendChild(viewer);
  }
  if (state.links && state.links.zip) {
    box.appendChild(link(state.links.zip, "Alles als ZIP", !(state.links && state.links.viewer)));
  }
  ((state.links && state.links.files) || []).forEach((file) => {
    box.appendChild(link(file.href, file.name + " (" + size(file.size) + ")"));
  });

  const findings = $("findings");
  findings.innerHTML = "";
  (state.findings || []).forEach((finding) => {
    addLog(findings, [finding.severity, finding.object, finding.message].filter(Boolean).join(" | "));
  });
  $("findings-box").hidden = !(state.findings || []).length;

  const log = $("result-log");
  log.innerHTML = "";
  (state.log || []).forEach((line) => addLog(log, line));
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function fail(message, state) {
  hide("result");
  show("error");
  $("bar").style.width = "100%";
  $("bar").style.background = "var(--bad)";
  $("error-text").textContent = message;
  const log = $("error-log");
  log.innerHTML = "";
  ((state && state.log) || []).forEach((line) => addLog(log, line));
  $("error-log-box").hidden = !(state && (state.log || []).length);
  $("error").scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hide("result");
  hide("error");
  show("progress");
  $("bar").style.width = "4%";
  $("bar").style.background = "var(--accent)";
  $("log").innerHTML = "";
  $("go").disabled = true;
  addLog($("log"), "Upload wird gesendet ...");
  try {
    const data = new FormData(form);
    const response = await fetch("/build", { method: "POST", body: data });
    const payload = await response.json().catch(() => ({ error: "Der Server hat kein JSON geliefert (HTTP " + response.status + ")." }));
    if (!response.ok) throw new Error(payload.error || ("HTTP " + response.status));
    await poll(payload.status);
  } catch (error) {
    fail(error.message);
  } finally {
    $("go").disabled = false;
  }
});

fetch("/healthz", { cache: "no-store" }).then((response) => response.json()).then((info) => {
  const mb = Math.round(info.max_upload_bytes / (1024 * 1024));
  $("limits").textContent = "Grenzen: " + mb + " MB Upload, " + info.max_seconds +
    " s je Lauf, " + info.max_jobs + " Laeufe parallel.";
  if (!info.beispiel) {
    const radio = document.querySelector("input[name=mdg_source][value=beispiel]");
    radio.disabled = true;
    radio.checked = false;
    document.querySelector("input[name=mdg_source][value=upload]").checked = true;
    $("mdg-wrap").hidden = false;
  }
}).catch(() => { $("limits").textContent = ""; });
</script>
</body>
</html>
"""
