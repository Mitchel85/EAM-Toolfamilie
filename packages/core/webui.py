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
import sqlite3
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
DEFAULT_MAX_SECONDS = 1800.0
DEFAULT_HTTP_TIMEOUT = 120.0
DEFAULT_MAX_JOBS = 2
DEFAULT_JOB_TTL = 600.0
MAX_LOG_LINES = 400
MAX_FINDINGS_SHOWN = 200
MAX_FIELD_CHARS = 2048
MAX_TEXT_CHARS = 4 * 1024 * 1024
MAX_API_KEY_CHARS = 512
ZIP_NAME = "ergebnis.zip"
# Die Modellansicht bringt Stil und Skript inline mit (eine Datei, kein Netz).
# frame-ancestors 'self' erlaubt die direkte Vorschau-Einbettung auf der Hauptseite.
VIEWER_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)
# Muss zu extract.DEFAULT_PACKAGE passen; tests/test_webui.py prueft das.
DEFAULT_PACKAGE_NAME = "Architektur"
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-()]{0,79}$")
MDG_SUFFIXES = (".xml", ".mdg")
TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".docx", ".pdf", ".csv", ".tsv")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
QEA_SUFFIXES = (".qea",)
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
    format: str = "qea"
    answer_path: Path | None = None
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    startpaket_path: Path | None = None
    katalog_path: Path | None = None
    startpaket_note: str = ""
    image_paths: tuple[Path, ...] = ()
    text_paths: tuple[Path, ...] = ()
    sichten: str = "leitfaden"
    wizard_dir: Path | None = None
    context_tokens: int | None = None


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

    # -- Bilder ------------------------------------------------------------
    raw_bild_uploads = [
        p
        for name in ("bild", "bilddatei", "bilder")
        for p in parts.get(name, ())
        if p.filename
    ]
    for b_up in raw_bild_uploads:
        if not b_up.data:
            raise RequestError("Die hochgeladene Bilddatei ist leer.")
    image_paths: list[Path] = []
    bild_uploads = [p for p in raw_bild_uploads if p.data]
    for idx, b_up in enumerate(bild_uploads, start=1):
        b_name = sanitize_filename(b_up.filename, default=f"bild_{idx}.png")
        b_sfx = Path(b_name).suffix.lower()
        if b_sfx not in IMAGE_SUFFIXES:
            raise RequestError(
                f"Bilddatei: Endung {b_sfx or '(ohne)'} wird nicht gelesen "
                f"(erlaubt: {', '.join(sorted(IMAGE_SUFFIXES))})."
            )
        b_path = input_dir / f"bild_{idx}{b_sfx}"
        b_path.write_bytes(b_up.data)
        image_paths.append(b_path)

    # -- Text --------------------------------------------------------------
    text_value = _field(parts, "text", max_chars=MAX_TEXT_CHARS)
    raw_text_uploads = [
        p
        for name in ("textdatei", "texte")
        for p in parts.get(name, ())
        if p.filename
    ]
    for t_up in raw_text_uploads:
        if not t_up.data:
            raise RequestError("Die hochgeladene Textdatei ist leer.")
    text_uploads = [p for p in raw_text_uploads if p.data]
    text_paths: list[Path] = []
    stem = "modell"
    if text_uploads:
        for idx, t_up in enumerate(text_uploads, start=1):
            name = sanitize_filename(
                t_up.filename,
                default="text.txt" if len(text_uploads) == 1 else f"text_{idx}.txt",
            )
            suffix = Path(name).suffix.lower()
            if suffix not in TEXT_SUFFIXES:
                raise RequestError(
                    f"Textdatei: Endung {suffix or '(ohne)'} wird nicht gelesen "
                    f"(erlaubt: {', '.join(sorted(TEXT_SUFFIXES))})."
                )
            t_filename = f"text{suffix}" if len(text_uploads) == 1 else f"text_{idx}{suffix}"
            t_path = input_dir / t_filename
            t_path.write_bytes(t_up.data)
            text_paths.append(t_path)
            if idx == 1:
                stem = Path(name).stem or "modell"
        text_path = text_paths[0]
    elif text_value:
        suffix = ".txt"
        text_bytes = text_value.encode("utf-8")
        if not text_bytes.strip():
            raise RequestError("Der Text ist leer -- daraus entsteht kein Modell.")
        stem = "modell"
        text_path = input_dir / f"text{suffix}"
        text_path.write_bytes(text_bytes)
        text_paths.append(text_path)
    elif image_paths:
        text_path = input_dir / "text.txt"
        text_path.write_text("", encoding="utf-8")
        stem = image_paths[0].stem or "modell"
    else:
        raise RequestError(
            "Kein Text und kein Bild: bitte Prosa einfuegen oder eine Text-/Bilddatei hochladen."
        )

    format_choice = _field(parts, "format", "qea").lower()
    if format_choice not in ("qea", "xmi", "archimate", "xml", "json"):
        raise RequestError(
            f"Unbekanntes Ausgabeformat {format_choice!r} (erlaubt: qea, xmi, archimate, xml, json)."
        )
    ext_map = {"qea": ".qea", "xmi": ".xmi", "archimate": ".xml", "xml": ".xml", "json": ".json"}
    target_ext = ext_map[format_choice]

    out_name = sanitize_filename(f"{stem}{target_ext}", default=f"modell{target_ext}", max_length=90)
    if not out_name.endswith(target_ext):
        out_name = f"modell{target_ext}"

    # -- Startpaket --------------------------------------------------------
    # Ein Feld, ein Zweck: Das Startpaket traegt die Standardelemente
    # mit den von Enterprise Architect vergebenen Kennungen und den daran
    # haengenden Taxonomien (z. B. NATO-NC3-Mapping). Es wird nur gelesen --
    # nie als Modell kopiert -- und dient zugleich als Katalog, damit genannte
    # Standardelemente Kennung und Heimatpaket behalten.
    startpaket_path: Path | None = None
    katalog_path: Path | None = None
    startpaket_note = ""
    start_upload = _upload(parts, "startpaket")
    if start_upload is not None and start_upload.filename:
        if not start_upload.data:
            raise RequestError("Das hochgeladene Startpaket ist leer.")
        name = sanitize_filename(start_upload.filename, default="startpaket.qea")
        suffix = Path(name).suffix.lower()
        if suffix not in QEA_SUFFIXES:
            raise RequestError(
                f"Startpaket: Endung {suffix or '(ohne)'} wird nicht gelesen (erlaubt: .qea)."
            )
        startpaket_path = input_dir / "startpaket.qea"
        startpaket_path.write_bytes(start_upload.data)
        katalog_path = startpaket_path
        # Eine .qea ist eine SQLite-Datei. Laesst sie sich nicht oeffnen, ist
        # es keine gueltige Datei -- das faellt vor dem Lauf auf, nicht danach.
        try:
            con = sqlite3.connect(str(startpaket_path))
            con.execute("PRAGMA query_only = ON")
            try:
                con.execute("select count(*) from t_object").fetchone()
            finally:
                con.close()
        except sqlite3.Error as exc:
            raise RequestError(
                f"Startpaket nicht lesbar ({exc}). Erwartet wird eine .qea-Datei (SQLite)."
            ) from exc
        try:
            import catalog_index  # noqa: PLC0415 - nur bei Bedarf

            catalog_index.Catalog.from_qea(startpaket_path)
        except Exception as exc:  # noqa: BLE001 - Leseschwaeche wird zur Meldung
            if exc.__class__.__name__ != "CatalogError":
                raise RequestError(
                    f"Startpaket nicht lesbar ({exc.__class__.__name__}: {exc}). "
                    "Erwartet wird eine .qea-Datei (SQLite)."
                ) from exc
            startpaket_note = (
                "Startpaket ohne ea_guid: Kennungen werden aus Paket, Stereotyp "
                "und Name abgeleitet."
            )

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

    sichten = _field(parts, "sichten", "leitfaden").lower()
    if sichten not in ("aus", "mdg", "leitfaden", "wizard"):
        sichten = "leitfaden"

    raw_ctx = _field(parts, "context_tokens", "").strip()
    context_tokens: int | None = None
    if raw_ctx:
        try:
            ctx_val = int(raw_ctx)
        except ValueError as exc:
            raise RequestError("Kontextfenster muss eine ganze Zahl in Tokens sein.") from exc
        if ctx_val < 2048 or ctx_val > 2_000_000:
            raise RequestError("Kontextfenster muss zwischen 2048 und 2000000 Tokens liegen.")
        context_tokens = ctx_val

    return Prepared(
        backend=backend,
        package=package,
        mdg_path=mdg_path,
        text_path=text_path,
        out_name=out_name,
        format=format_choice,
        answer_path=answer_path,
        model=model,
        base_url=base_url,
        api_key=api_key,
        startpaket_path=startpaket_path,
        katalog_path=katalog_path,
        startpaket_note=startpaket_note,
        image_paths=tuple(image_paths),
        text_paths=tuple(text_paths),
        sichten=sichten,
        context_tokens=context_tokens,
    )


# --------------------------------------------------------------------------
# Kindprozess: derselbe Aufruf wie die Kommandozeile
# --------------------------------------------------------------------------


def build_command(prepared: Prepared, job_dir: Path, max_seconds: float) -> list[str]:
    """Kommandozeile des Laufs. Einziger Weg zum Kern, auch aus der Weboberflaeche."""
    # HTTP-Timeout gilt pro einzelner Charge (max. 120 s), entkoppelt vom Gesamt-Zeitlimit
    # fuer mehrstufige Chargenlaeufe (Default 1800 s).
    http_timeout = min(DEFAULT_HTTP_TIMEOUT, max(5.0, float(max_seconds) - 10.0))
    command = [
        sys.executable,
        "-m",
        "eam_ai",
        "build",
        "--mdg",
        str(prepared.mdg_path),
    ]
    t_list = prepared.text_paths or ([prepared.text_path] if prepared.text_path.is_file() and prepared.text_path.stat().st_size > 0 else [])
    for tp in t_list:
        command += ["--text", str(tp)]
    for ip in prepared.image_paths:
        command += ["--bild", str(ip)]
    command += [
        "--out",
        str(job_dir / prepared.out_name),
        "--format",
        prepared.format,
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
    # Startpaket und Katalog gelten fuer jedes Backend: sie bestimmen, welche
    # Standardelemente erkannt werden und welche Kennung sie behalten.
    # Das Startpaket wird ueber --katalog nur gelesen (nicht als Modell kopiert);
    # die EA-Tabellenhuelle kommt ueber EAM_EA_VORLAGE in build_environment().
    if prepared.katalog_path is not None and not prepared.startpaket_note:
        command += ["--katalog", str(prepared.katalog_path)]
    if prepared.sichten != "leitfaden":
        command += ["--sichten", prepared.sichten]
    if prepared.wizard_dir:
        command += ["--wizard-dir", str(prepared.wizard_dir)]
    if prepared.context_tokens is not None:
        command += ["--kontext-tokens", str(prepared.context_tokens)]
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
    if prepared.startpaket_path is not None and not environment.get("EAM_EA_VORLAGE"):
        environment["EAM_EA_VORLAGE"] = str(prepared.startpaket_path)
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
    mdg_path: Path | None = None
    package: str = DEFAULT_PACKAGE_NAME
    format: str = "qea"
    backend_model: str = ""
    base_url: str = ""
    startpaket_path: Path | None = None
    katalog_path: Path | None = None
    sichten: str = "leitfaden"
    project: str = ""
    revision: int = 1
    model_info: dict[str, Any] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    finished: float | None = None
    thread: threading.Thread | None = field(default=None, repr=False)
    _op_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def scrub(self, text: str, *, secret: str = "") -> str:
        """Interne Pfade und Geheimnisse aus einer Zeile entfernen."""
        for sep in ("/", "\\"):
            text = text.replace(f"{self.directory}{sep}", "")
        text = text.replace(str(self.directory), ".")
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

    def model_name(self) -> str | None:
        """Name des erzeugten Modells (.qea, .xmi, .xml, .json) im Manifest (oder None)."""
        valid_suffixes = (".qea", ".xmi", ".xml", ".json")
        for entry in self.files:
            name = str(entry.get("name", ""))
            if any(name.lower().endswith(sfx) for sfx in valid_suffixes):
                if name.lower() not in ("findings.json", "quellen.json"):
                    return name
        return None

    def qea_name(self) -> str | None:
        """Name der erzeugten .qea im Manifest (oder None, abwaertskompatibler Alias)."""
        return self.model_name()

    def ensure_qea(self) -> Path:
        """Liefert eine les- und bearbeitbare .qea fuer das aktuelle Auftragsmodell."""
        name = self.model_name()
        if not name:
            raise RequestError("Zu diesem Auftrag gibt es kein Modell.", status=404)
        model_path = self.directory / name
        if not model_path.is_file():
            raise RequestError("Modelldatei ist nicht mehr vorhanden.", status=410)
        if model_path.suffix.lower() == ".qea":
            return model_path
        work_qea = self.directory / "_work.qea"
        if not work_qea.is_file() or work_qea.stat().st_mtime < model_path.stat().st_mtime:
            import model_io  # noqa: PLC0415
            import qea_writer  # noqa: PLC0415

            ir = model_io.read_model(model_path)
            qea_writer.write_qea(ir, work_qea)
        return work_qea

    def refresh_model_info(self) -> None:
        """Pakete, Elemente und Kanten fuer Chat-Scope und Zusammenfassung einlesen."""
        name = self.model_name()
        if not name:
            self.model_info = {}
            return
        model_path = self.directory / name
        if not model_path.is_file():
            self.model_info = {}
            return
        try:
            import model_io  # noqa: PLC0415

            ir = model_io.read_model(model_path)
            packages = sorted({str(p.get("path") or "") for p in ir.get("packages", []) if p.get("path")})
            elements = sorted(
                {
                    f"{el.get('package')}::{el.get('name')}" if el.get("package") else str(el.get("name") or "")
                    for el in ir.get("elements", [])
                    if el.get("name")
                }
            )
            self.model_info = {
                "packages": packages[:200],
                "elements": elements[:400],
                "package_count": len(packages),
                "element_count": len(ir.get("elements", [])),
                "connector_count": len(ir.get("connectors", [])),
            }
            self.summary["elements"] = len(ir.get("elements", []))
            self.summary["connectors"] = len(ir.get("connectors", []))
        except Exception:  # noqa: BLE001
            self.model_info = {}

    def as_json(self) -> dict[str, Any]:
        links: dict[str, Any] = {"files": []}
        if self.zip_name is not None:
            links["zip"] = f"/api/jobs/{self.token}/{quote(self.zip_name)}"
        if self.state == "done" and self.model_name():
            links["viewer"] = f"/api/jobs/{self.token}/viewer"
            links["validate"] = f"/api/jobs/{self.token}/validate"
            links["qs"] = f"/api/jobs/{self.token}/qs"
            links["handbuch"] = f"/api/jobs/{self.token}/handbuch"
            links["chat"] = f"/api/jobs/{self.token}/chat"
            links["edit"] = f"/api/jobs/{self.token}/edit"
            links["extend"] = f"/api/jobs/{self.token}/extend"
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
            "revision": self.revision,
            "log": list(self.log),
            "error": self.error,
            "result_line": self.result_line,
            "summary": dict(self.summary),
            "model_info": dict(self.model_info),
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
            if job.thread is not None and job.thread.is_alive():
                job.thread.join(timeout=5)
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

        job = Job(
            token=token,
            directory=job_dir,
            backend=prepared.backend,
            mdg_path=prepared.mdg_path,
            package=prepared.package,
            format=prepared.format,
            backend_model=prepared.model,
            base_url=prepared.base_url,
            startpaket_path=prepared.startpaket_path,
            katalog_path=prepared.katalog_path,
            sichten=prepared.sichten,
            project=prepared.package,
        )
        with self._lock:
            self.jobs[token] = job
        thread = threading.Thread(
            target=self._run_job,
            args=(job, prepared),
            name=f"eam-ai-{token[:6]}",
            daemon=True,
        )
        job.thread = thread
        thread.start()
        return job

    def _run_job(self, job: Job, prepared: Prepared) -> None:
        secret = prepared.api_key

        def log(line: str) -> None:
            job.add_log(line, secret=secret)

        try:
            log(f"Lauf gestartet: Backend {prepared.backend}, Paket {prepared.package!r}")
            if prepared.startpaket_path is not None:
                log("Startpaket: wird als Standardelemente gelesen (nicht als Modell kopiert)")
            if prepared.startpaket_note:
                log(f"Hinweis: {prepared.startpaket_note}")
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
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
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
                    f"Lauf fehlgeschlagen (Exit {code or 'unbekannt'}), kein Modell erzeugt.",
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
            job.refresh_model_info()
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


def _run_cli_validate(model_path: Path, mdg_path: Path) -> dict[str, Any]:
    """Orchestriert die MDG-Validierung ueber die CLI (``eam-ai validate``)."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", prefix="eam-val-out-", delete=False) as handle:
        out_path = Path(handle.name)
    try:
        cmd = [
            sys.executable,
            "-m",
            "eam_ai",
            "validate",
            "--in",
            str(model_path),
            "--mdg",
            str(mdg_path),
            "--out",
            str(out_path),
            "-q",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode not in (0, 1):
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"Exit {proc.returncode}")
        findings = json.loads(out_path.read_text(encoding="utf-8"))
        summary = {
            "error": sum(1 for f in findings if f.get("severity") == "error"),
            "warning": sum(1 for f in findings if f.get("severity") == "warning"),
        }
        return {
            "ok": summary["error"] == 0,
            "summary": summary,
            "findings": findings,
        }
    finally:
        out_path.unlink(missing_ok=True)


def _run_cli_qs(model_path: Path, mdg_path: Path, project: str) -> dict[str, Any]:
    """Orchestriert den QS-Kombilauf ueber die CLI (``eam-ai qs``)."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", prefix="eam-qs-out-", delete=False) as handle:
        out_path = Path(handle.name)
    try:
        cmd = [
            sys.executable,
            "-m",
            "eam_ai",
            "qs",
            "--in",
            str(model_path),
            "--mdg",
            str(mdg_path),
            "--projekt",
            project or "",
            "--out",
            str(out_path),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode not in (0, 1):
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"Exit {proc.returncode}")
        return json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        out_path.unlink(missing_ok=True)


def _resolve_job_mdg(job: Job) -> Path | None:
    """Liefert die MDG-Datei des Auftrags (oder die mitgelieferte Standard-MDG)."""
    if job.mdg_path and job.mdg_path.is_file():
        return job.mdg_path
    for candidate in (
        job.directory / "input" / "technologie.xml",
        job.directory / "input" / "technologie.mdg",
        job.directory / "technologie.xml",
        Path(__file__).resolve().parents[1] / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml",
    ):
        if candidate.is_file():
            return candidate
    return None


def _build_optional_backend(
    payload: Mapping[str, Any], job: Job, *, max_seconds: float
) -> Any:
    """Erstellt bei Bedarf ein Sprachmodell-Backend fuer Chat/NL-Edit (sonst None = ohne KI)."""
    use_ki = payload.get("use_ki", True)
    if use_ki is False:
        return None
    kind = str(payload.get("backend") or job.backend or "datei").strip().lower()
    if kind in ("", "datei", "offline", "none"):
        return None
    api_key = str(payload.get("api_key") or "").strip()
    if len(api_key) > MAX_API_KEY_CHARS or "\n" in api_key or "\r" in api_key:
        raise RequestError("API-Schluessel ungueltig.")
    if kind == "openai" and not api_key and not (
        os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    ):
        return None
    model = str(payload.get("model") or job.backend_model or "").strip()
    base_url = str(payload.get("base_url") or job.base_url or "").strip()
    if base_url:
        base_url = check_base_url(base_url)
    import extract  # noqa: PLC0415

    try:
        return extract.make_backend(
            kind,
            model=model or None,
            base_url=base_url or None,
            api_key=api_key or None,
            timeout=max(10.0, float(max_seconds) - 5.0),
        )
    except extract.ExtractionError as exc:
        raise RequestError(str(exc), status=400) from exc


def _refresh_job_after_mutation(job: Job, qea_path: Path) -> None:
    """Synchronisiert Zielformat, ZIP, Manifest, Viewer-Cache und Modell-Info nach Aenderungen."""
    model_name = job.model_name()
    if not model_name:
        return
    out_path = job.directory / model_name
    if out_path.resolve() != qea_path.resolve():
        import model_io  # noqa: PLC0415
        import qea_reader  # noqa: PLC0415

        ir = qea_reader.read_qea(qea_path)
        model_io.write_model(ir, out_path, fmt=job.format)
    job.viewer_page = None
    (job.directory / "handbuch.md").unlink(missing_ok=True)
    findings_path = job.directory / "findings.json"
    quellen_path = job.directory / "quellen.json"
    zip_path = _write_zip(job.directory / ZIP_NAME, [out_path, findings_path, quellen_path])
    job.files = _manifest([out_path, findings_path, quellen_path])
    job.zip_name = zip_path.name
    job.revision += 1
    job.refresh_model_info()
    job.finished = time.time()


class Handler(BaseHTTPRequestHandler):
    server: WebServer
    server_version = "eam-ai-web"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    # -- Hilfen ------------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        self.server.log(f"{self.address_string()} {format % args}")

    def _common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
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
                        "frame-src 'self'; form-action 'self'; img-src data:; base-uri 'none'"
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
                    "startpaket_upload": True,
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
                elif rest[1] == "validate":
                    self._job_validate(unquote(rest[0]))
                elif rest[1] == "handbuch":
                    self._job_handbuch(unquote(rest[0]))
                elif rest[1] == "qs":
                    self._job_qs(unquote(rest[0]))
                else:
                    self._job_file(unquote(rest[0]), unquote(rest[1]))
                return
        self._error(
            HTTPStatus.NOT_FOUND,
            "Nicht gefunden. Erlaubt sind /, /healthz, /build, /api/jobs/<id>, "
            "/api/jobs/<id>/<datei>, /api/jobs/<id>/viewer und /api/jobs/<id>/validate.",
        )

    def _job_status(self, token: str) -> None:
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        self._send_json(HTTPStatus.OK, job.as_json())

    def _job_viewer(self, token: str) -> None:
        """Modellansicht aus dem erzeugten Modell (.qea, .xmi, .xml, .json) -- eine HTML-Datei, kein Netz."""
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        if job.state == "running":
            self._error(HTTPStatus.CONFLICT, "Der Lauf ist noch nicht fertig.")
            return
        name = job.model_name()
        if job.state != "done" or name is None:
            self._error(HTTPStatus.NOT_FOUND, "Zu diesem Auftrag gibt es kein Modell.")
            return
        page = job.viewer_page
        if page is None:
            try:
                page = viewer_html.build_html(job.directory / name)
            except Exception as exc:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Modellansicht nicht lesbar: {exc}")
                return
            job.viewer_page = page
        self._send_bytes(
            HTTPStatus.OK,
            page.encode("utf-8"),
            "text/html; charset=utf-8",
            extra={"Content-Security-Policy": VIEWER_CSP},
        )

    def _job_validate(self, token: str) -> None:
        """Validiert das erzeugte Modell des Auftrags gegen die MDG-Technologie."""
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        if job.state == "running":
            self._error(HTTPStatus.CONFLICT, "Der Lauf ist noch nicht fertig.")
            return
        name = job.model_name()
        if job.state != "done" or name is None:
            self._error(HTTPStatus.NOT_FOUND, "Zu diesem Auftrag gibt es kein Modell.")
            return
        model_path = job.directory / name
        mdg_path = _resolve_job_mdg(job)
        if mdg_path is None:
            self._error(HTTPStatus.NOT_FOUND, "Keine MDG-Datei fuer die Validierung verfuegbar.")
            return
        try:
            payload = _run_cli_validate(model_path, mdg_path)
            self._send_json(HTTPStatus.OK, payload)
        except Exception as exc:  # noqa: BLE001
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Validierungsfehler: {exc}")

    def _job_handbuch(self, token: str) -> None:
        """Generiert das Betriebshandbuch fuer das erzeugte Modell als Markdown."""
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        if job.state == "running":
            self._error(HTTPStatus.CONFLICT, "Der Lauf ist noch nicht fertig.")
            return
        name = job.model_name()
        if job.state != "done" or name is None:
            self._error(HTTPStatus.NOT_FOUND, "Zu diesem Auftrag gibt es kein Modell.")
            return
        model_path = job.directory / name
        target_md = job.directory / "handbuch.md"
        try:
            import handbuch_generator

            if not target_md.is_file():
                handbuch_generator.generate_handbook(model_path, target_md)
            data = target_md.read_bytes()
            self._send_bytes(
                HTTPStatus.OK,
                data,
                "text/markdown; charset=utf-8",
                extra={"Content-Disposition": 'attachment; filename="handbuch.md"'},
            )
        except Exception as exc:  # noqa: BLE001
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Handbuch-Fehler: {exc}")

    def _job_qs(self, token: str) -> None:
        """Erzeugt einen vollstaendigen Qualitaetssicherungsbericht fuer den Auftrag."""
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return
        if job.state == "running":
            self._error(HTTPStatus.CONFLICT, "Der Lauf ist noch nicht fertig.")
            return
        name = job.model_name()
        if job.state != "done" or name is None:
            self._error(HTTPStatus.NOT_FOUND, "Zu diesem Auftrag gibt es kein Modell.")
            return
        model_path = job.directory / name
        mdg_path = _resolve_job_mdg(job)
        if mdg_path is None:
            self._error(HTTPStatus.NOT_FOUND, "Keine MDG-Datei fuer die QS-Pruefung verfuegbar.")
            return
        try:
            payload = _run_cli_qs(model_path, mdg_path, job.project)
            self._send_json(HTTPStatus.OK, payload)
        except Exception as exc:  # noqa: BLE001
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"QS-Fehler: {exc}")

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
    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestError("Content-Length fehlt.", status=411)
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise RequestError("Content-Length ist keine Zahl.", status=400) from exc
        if length <= 0:
            raise RequestError("Leerer Anfragekoerper.", status=400)
        if length > self.server.config.max_upload:
            raise RequestError("Anfrage zu gross.", status=413)
        body = self._read_body(length)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RequestError("Anfragekoerper ist kein gueltiges JSON.", status=400) from exc
        if not isinstance(parsed, dict):
            raise RequestError("JSON-Objekt erwartet.", status=400)
        return parsed

    def _require_done_job(self, token: str) -> Job | None:
        job = self.server.get_job(token)
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannter Auftrag (abgelaufen oder falsche ID).")
            return None
        if job.state == "running":
            self._error(HTTPStatus.CONFLICT, "Der Lauf ist noch nicht fertig.")
            return None
        if job.state != "done" or job.model_name() is None:
            self._error(HTTPStatus.NOT_FOUND, "Zu diesem Auftrag gibt es kein fertiges Modell.")
            return None
        return job

    def _job_chat(self, token: str) -> None:
        """Chat with Data: lesende Frage an das erzeugte Modell stellen."""
        job = self._require_done_job(token)
        if job is None:
            return
        try:
            payload = self._read_json_body()
            question = str(payload.get("question") or "").strip()
            if not question:
                raise RequestError("Bitte eine Frage eingeben.", status=400)
            scope_kind = str(payload.get("scope_kind") or "model").strip().lower()
            scope_value = str(payload.get("scope_value") or "").strip()
            scope: dict[str, str] | None = None
            if scope_kind == "package" and scope_value:
                scope = {"package": scope_value}
            elif scope_kind == "element" and scope_value:
                scope = {"element": scope_value}

            import qea_chat  # noqa: PLC0415

            backend = _build_optional_backend(
                payload, job, max_seconds=self.server.config.max_seconds
            )
            with job._op_lock:
                qea_path = job.ensure_qea()
                answer = qea_chat.ask_qea(qea_path, question, backend=backend, scope=scope)
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "answer": answer.text,
                    "sources": answer.sources,
                    "scope": answer.scope_label,
                    "model": answer.model,
                    "question": answer.question,
                },
            )
        except RequestError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(HTTPStatus.BAD_REQUEST, f"Chat-Fehler: {exc}")

    def _job_edit(self, token: str) -> None:
        """Natuerlichsprachliche Aenderung/Erweiterung am fertigen Modell (propose/apply)."""
        job = self._require_done_job(token)
        if job is None:
            return
        try:
            payload = self._read_json_body()
            action = str(payload.get("action") or "propose").strip().lower()
            if action not in ("propose", "apply"):
                raise RequestError("action muss 'propose' oder 'apply' sein.", status=400)

            import model_edit  # noqa: PLC0415
            import nl_edit  # noqa: PLC0415

            if action == "propose":
                instruction = str(payload.get("instruction") or "").strip()
                if not instruction:
                    raise RequestError("Bitte eine Aenderungsanweisung eingeben.", status=400)
                backend = _build_optional_backend(
                    payload, job, max_seconds=self.server.config.max_seconds
                )
                with job._op_lock:
                    qea_path = job.ensure_qea()
                    proposal = nl_edit.propose(qea_path, instruction, backend=backend)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "action": "propose",
                        "ops": proposal.ops,
                        "preview": nl_edit.preview_lines(proposal),
                        "reply": proposal.reply,
                        "backend": proposal.backend,
                        "warnings": proposal.warnings,
                        "destructive": proposal.destructive,
                    },
                )
                return

            # action == "apply"
            ops = payload.get("ops")
            confirm = bool(payload.get("confirm", False))
            mdg_check = bool(payload.get("mdg_check", True))
            if ops is None:
                instruction = str(payload.get("instruction") or "").strip()
                if not instruction:
                    raise RequestError("Weder 'ops' noch 'instruction' angegeben.", status=400)
                backend = _build_optional_backend(
                    payload, job, max_seconds=self.server.config.max_seconds
                )
                with job._op_lock:
                    qea_path = job.ensure_qea()
                    proposal = nl_edit.propose(qea_path, instruction, backend=backend)
                    ops = proposal.ops
            if not isinstance(ops, list) or not ops:
                raise RequestError("Keine gueltigen Operationen zum Anwenden.", status=400)
            if any(isinstance(op, dict) and op.get("op") in nl_edit.DESTRUCTIVE for op in ops) and not confirm:
                raise RequestError(
                    "Loeschoperationen muessen ausdruecklich bestaetigt werden (confirm=true).",
                    status=400,
                )

            mdg_path = _resolve_job_mdg(job) if mdg_check else None
            with job._op_lock:
                qea_path = job.ensure_qea()
                tmp_out = job.directory / f"_edit_{job.revision + 1}.qea"
                try:
                    result = model_edit.edit_model(qea_path, ops, tmp_out, mdg=mdg_path)
                    if result.applied > 0:
                        os.replace(tmp_out, qea_path)
                        _refresh_job_after_mutation(job, qea_path)
                        job.add_log(
                            f"Modell geaendert (Rev {job.revision}): {result.applied} von {len(ops)} Operationen angewendet"
                        )
                    else:
                        tmp_out.unlink(missing_ok=True)
                except BaseException:
                    tmp_out.unlink(missing_ok=True)
                    raise

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": result.applied > 0 or not result.rejected,
                    "action": "apply",
                    "applied": result.applied,
                    "total": len(ops),
                    "changes": result.changes,
                    "rejected": result.rejected,
                    "job": job.as_json(),
                },
            )
        except RequestError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(HTTPStatus.BAD_REQUEST, f"Bearbeitungsfehler: {exc}")

    def _job_extend(self, token: str) -> None:
        """Bestehende Architektur per weiterer Prosa ueber `eam_ai build --modell` weiterbauen."""
        job = self._require_done_job(token)
        if job is None:
            return
        try:
            payload = self._read_json_body()
            text = str(payload.get("text") or "").strip()
            if not text:
                raise RequestError("Bitte weiteren Architektur-Text zum Weiterbauen eingeben.", status=400)
            if len(text) > MAX_TEXT_CHARS:
                raise RequestError("Text ist zu lang.", status=413)

            kind = str(payload.get("backend") or job.backend or "datei").strip().lower()
            if kind not in ("datei", "openai", "ollama"):
                raise RequestError(f"Unbekanntes Backend {kind!r}.", status=400)
            api_key = str(payload.get("api_key") or "").strip()
            if len(api_key) > MAX_API_KEY_CHARS or "\n" in api_key or "\r" in api_key:
                raise RequestError("API-Schluessel ungueltig.", status=400)
            model = str(payload.get("model") or job.backend_model or "").strip()
            base_url = str(payload.get("base_url") or job.base_url or "").strip()
            if base_url:
                base_url = check_base_url(base_url)

            mdg_path = _resolve_job_mdg(job)
            if mdg_path is None:
                raise RequestError("Keine MDG-Datei fuer den Weiterbau vorhanden.", status=400)

            with job._op_lock:
                qea_path = job.ensure_qea()
                ext_txt = job.directory / "input" / f"extend_{job.revision + 1}.txt"
                ext_txt.parent.mkdir(parents=True, exist_ok=True)
                ext_txt.write_text(text, encoding="utf-8")

                tmp_out = job.directory / f"_extend_{job.revision + 1}.qea"
                findings_tmp = job.directory / "findings.json"
                quellen_tmp = job.directory / "quellen.json"
                http_timeout = max(5.0, float(self.server.config.max_seconds) - 10.0)
                cmd = [
                    sys.executable,
                    "-m",
                    "eam_ai",
                    "build",
                    "--mdg",
                    str(mdg_path),
                    "--text",
                    str(ext_txt),
                    "--modell",
                    str(qea_path),
                    "--out",
                    str(tmp_out),
                    "--format",
                    "qea",
                    "--package",
                    job.package or DEFAULT_PACKAGE_NAME,
                    "--backend",
                    kind,
                    "--findings",
                    str(findings_tmp),
                    "--quellen",
                    str(quellen_tmp),
                    "--timeout",
                    f"{http_timeout:g}",
                ]
                if kind == "datei":
                    ans = job.directory / "antwort.json"
                    if not ans.is_file():
                        bundled = self.server.config.assets / "antwort.json"
                        if not bundled.is_file():
                            raise RequestError("Beispielantwort fehlt fuer Datei-Backend.", status=500)
                        shutil.copyfile(bundled, ans)
                    cmd += ["--antwort", str(ans)]
                else:
                    if not model:
                        raise RequestError("Modellname fehlt fuer den Weiterbau.", status=400)
                    cmd += ["--model", model]
                    if base_url:
                        cmd += ["--base-url", base_url]
                if job.katalog_path and job.katalog_path.is_file():
                    cmd += ["--katalog", str(job.katalog_path)]
                if job.sichten and job.sichten != "leitfaden":
                    cmd += ["--sichten", job.sichten]

                env = dict(os.environ)
                module_root = str(Path(__file__).resolve().parent)
                existing_pp = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = module_root + (os.pathsep + existing_pp if existing_pp else "")
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                if kind == "datei":
                    env.pop("OPENAI_API_KEY", None)
                elif api_key:
                    env["OPENAI_API_KEY"] = api_key

                try:
                    proc = subprocess.run(
                        cmd,
                        cwd=str(job.directory),
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.server.config.max_seconds,
                        check=False,
                    )
                    for line in (proc.stderr or "").splitlines():
                        job.add_log(line, secret=api_key)
                    if proc.returncode != 0 or not tmp_out.is_file():
                        err_line = next(
                            (l for l in reversed((proc.stderr or "").splitlines()) if "FEHLER:" in l),
                            f"Weiterbau fehlgeschlagen (Exit {proc.returncode}).",
                        )
                        raise RequestError(job.scrub(err_line, secret=api_key), status=400)

                    res_line = next(
                        (l.strip() for l in reversed((proc.stdout or "").splitlines()) if l.strip()),
                        "",
                    )
                    if res_line:
                        job.result_line = job.scrub(res_line, secret=api_key)
                        job.summary = parse_result_line(job.result_line)
                    job.findings = _load_findings(findings_tmp)
                    os.replace(tmp_out, qea_path)
                    _refresh_job_after_mutation(job, qea_path)
                    job.add_log(f"Architektur erweitert (Rev {job.revision})")
                finally:
                    tmp_out.unlink(missing_ok=True)

            self._send_json(HTTPStatus.OK, {"ok": True, "job": job.as_json()})
        except subprocess.TimeoutExpired:
            self._error(HTTPStatus.GATEWAY_TIMEOUT, "Zeitlimit beim Weiterbau ueberschritten.")
        except RequestError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Weiterbau-Fehler: {exc}")

    def do_POST(self) -> None:  # noqa: N802 - Vorgabe von http.server
        path = urlsplit(self.path).path
        if path.startswith("/api/jobs/"):
            rest = [segment for segment in path[len("/api/jobs/") :].split("/") if segment]
            if len(rest) == 2 and rest[1] in ("chat", "edit", "extend"):
                token = unquote(rest[0])
                if rest[1] == "chat":
                    self._job_chat(token)
                elif rest[1] == "edit":
                    self._job_edit(token)
                else:
                    self._job_extend(token)
                return
        if path not in ("/build", "/validate"):
            self._error(
                HTTPStatus.NOT_FOUND,
                "Erlaubt sind /build, /validate sowie /api/jobs/<id>/(chat|edit|extend).",
            )
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
                try:
                    self.rfile.read(min(length, 65536))
                except OSError:
                    pass
                self._error(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    f"Upload zu gross: {length / (1024 * 1024):.1f} MB. "
                    f"Grenze: {limit_mb:.0f} MB. Bitte Technologie oder Text kuerzen.",
                    close=True,
                )
                return
            body = self._read_body(length)
            parts = parse_multipart(body, self.headers.get("Content-Type", ""))

            if path == "/validate":
                import tempfile

                model_part = parts.get("model") or parts.get("file")
                if not model_part or not model_part[0].data:
                    self._error(HTTPStatus.BAD_REQUEST, "Modell-Datei ('model' oder 'file') fehlt.")
                    return
                m_fname = model_part[0].filename or "model.qea"
                m_ext = Path(m_fname).suffix or ".qea"
                with tempfile.NamedTemporaryFile(suffix=m_ext, prefix="eam-val-", delete=False) as h_m:
                    h_m.write(model_part[0].data)
                    tmp_model = Path(h_m.name)

                tmp_mdg = None
                mdg_part = parts.get("mdg") or parts.get("rules")
                if mdg_part and mdg_part[0].data:
                    g_fname = mdg_part[0].filename or "technologie.xml"
                    g_ext = Path(g_fname).suffix or ".xml"
                    with tempfile.NamedTemporaryFile(suffix=g_ext, prefix="eam-mdg-", delete=False) as h_g:
                        h_g.write(mdg_part[0].data)
                        tmp_mdg = Path(h_g.name)
                else:
                    tmp_mdg = Path(__file__).resolve().parents[1] / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml"

                try:
                    payload = _run_cli_validate(tmp_model, tmp_mdg)
                finally:
                    tmp_model.unlink(missing_ok=True)
                    if mdg_part and mdg_part[0].data and tmp_mdg:
                        tmp_mdg.unlink(missing_ok=True)

                self._send_json(HTTPStatus.OK, payload)
                return

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
<title>EAM AI Suite Python &mdash; Prosa + Technologie zu Architektur-Modell</title>
<style>
:root {
  --bg: #0f172a; --card: #16213b; --line: #26324e; --text: #e6edf7;
  --muted: #9aa8c0; --accent: #3b82f6; --ok: #22c55e; --bad: #ef4444;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding: 20px 20px 40px; }
h1 { font-size: 1.8rem; margin: 0 0 6px; letter-spacing: -0.02em; }
h2 { font-size: 1.02rem; margin: 0 0 10px; color: var(--text); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.lead { color: var(--muted); margin: 0 0 26px; }
.lead code { color: #c7d6ee; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 18px; margin-bottom: 14px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
.grid .card { margin-bottom: 0; }
.grid + .card, .grid + .actions { margin-top: 16px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
label { display: block; margin: 8px 0; color: var(--text); }
label.row { display: flex; gap: 10px; align-items: center; cursor: pointer; }
label.file { color: var(--muted); }
input[type=text], input[type=password], input[type=file], select, textarea {
  width: 100%; margin-top: 4px; padding: 8px 12px; border-radius: 8px;
  border: 1px solid var(--line); background: #0d1629; color: var(--text);
  font: inherit; }
textarea { resize: vertical; min-height: 70px; font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 13px; }
input:focus, select:focus, textarea:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
input[type=radio] { width: auto; margin: 0; }
.hint { color: var(--muted); font-size: 0.86rem; margin: 4px 0 8px; }
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
.downloads button { padding: 10px 14px; font-size: 0.92rem; border-radius: 9px;
  border: 1px solid var(--line); background: #0d1629; color: var(--text); font-weight: 500; }
.downloads button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.viewer-wrap { margin: 14px 0; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: #0b1222; }
.viewer-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 12px; background: #101a30; border-bottom: 1px solid var(--line); font-size: 0.9rem; }
.viewer-bar button, .sub-actions button { padding: 6px 12px; font-size: 0.86rem; border-radius: 7px; }
.viewer-frame { width: 100%; height: 620px; border: 0; background: #fff; display: block; }
.post-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 16px; align-items: start; }
@media (max-width: 960px) { .post-grid { grid-template-columns: 1fr; } }
.subcard { background: #101a30; border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
.subcard h3 { margin: 0 0 8px; font-size: 0.98rem; color: var(--text); }
.sub-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.out-box { margin-top: 10px; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--line);
  background: #0b1222; font-size: 0.9rem; white-space: pre-wrap; max-height: 320px; overflow: auto; }
.out-box.ok { border-color: #166534; }
.out-box.bad { border-color: var(--bad); color: #fecaca; }
.sources { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.src-pill { font-size: 12px; padding: 2px 8px; border-radius: 99px; background: #1e293b; color: #cbd5e1;
  border: 1px solid var(--line); font-family: ui-monospace, Menlo, Consolas, monospace; }
.mode-tabs { display: flex; gap: 6px; margin-bottom: 10px; }
.mode-tabs button { padding: 6px 12px; font-size: 0.85rem; background: #0d1629; border: 1px solid var(--line); color: var(--muted); }
.mode-tabs button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.preview-list { margin: 8px 0; padding-left: 20px; font-size: 0.88rem; }
.preview-list li.danger { color: #fca5a5; font-weight: 600; }
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
<p class="lead">Prosa rein, gepr&uuml;ftes Architektur-Modell (<code>.qea</code>, <code>.xmi</code>, <code>.xml</code>, <code>.json</code>) raus &ndash; mit den Kennungen
aus dem Startpaket. Gleicher Kern wie die Kommandozeile.</p>

<form id="f" autocomplete="off">
<div class="grid">
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
    <h2>2. Startpaket <span class="badge">optional &middot; empfohlen</span></h2>
    <p class="hint">Standardelemente mit EA-Kennung, Heimatpaket und Taxonomien
      (NATO-NC3). Wird nur gelesen, nicht als Modell kopiert.</p>
    <label class="file">Startpaket &ndash; .qea
      <input type="file" name="startpaket" accept=".qea,application/octet-stream"></label>
    <p class="hint" id="startpaket-note" hidden></p>
  </section>



  <section class="card">
    <h2>3. Text <button type="button" id="sample" class="link" style="float:right;font-weight:500">Beispieltext</button></h2>
    <textarea id="text" name="text" rows="5"
      placeholder="Architektur-Prosa hier einf&uuml;gen &hellip;"></textarea>
    <label class="file">Oder Textdatei (.txt, .md, .docx, .pdf) &ndash; hat Vorrang
      <input type="file" name="textdatei" accept=".txt,.md,.docx,.pdf,text/plain,application/pdf"></label>
  </section>

  <section class="card">
    <h2>4. Sprachextraktion &amp; Ausgabe</h2>
    <div class="two">
      <label>Backend
        <select name="backend" id="backend">
          <option value="datei">Datei (offline, mitgelieferte Beispielantwort)</option>
          <option value="openai" selected>OpenAI-kompatibler Endpunkt (DeepSeek)</option>
          <option value="ollama">Ollama</option>
        </select>
      </label>
      <label>Ausgabeformat
        <select name="format" id="format">
          <option value="qea" selected>Sparx Enterprise Architect (.qea)</option>
          <option value="xmi">XMI 2.1 (.xmi)</option>
          <option value="archimate">ArchiMate 3.2 Exchange (.xml)</option>
          <option value="json">EAM IR / JSON-Batch (.json)</option>
        </select>
      </label>
    </div>
    <div id="model-fields" hidden>
      <div class="two">
        <label>Basis-URL
          <input type="text" name="base_url" value="https://api.deepseek.com/v1"
                 placeholder="https://api.deepseek.com/v1"></label>
        <label>Modell
          <input type="text" name="model" value="deepseek-flash"
                 placeholder="deepseek-flash"></label>
      </div>
      <div class="two">
        <label>API-Schl&uuml;ssel (nur f&uuml;r diesen Lauf)
          <input type="password" name="api_key" autocomplete="new-password"></label>
        <label>Zielpaket
          <input type="text" name="package" value="Architektur"></label>
      </div>
      <label>Kontextfenster des Sprachmodells
        <select name="context_tokens" id="context_tokens">
          <option value="" selected>Standard (gro&szlig;, z.B. 64k+ Tokens &ndash; automatisches Chunking &amp; Halbierung)</option>
          <option value="16384">Mittel (16k Tokens &ndash; kompaktes Regelwerk, kleinere Chargen)</option>
          <option value="8192">Klein (8k Tokens &ndash; z.B. lokales Ollama / kleines LLM)</option>
          <option value="4096">Sehr klein (4k Tokens &ndash; Mini-Chargen, kompaktes Regelwerk)</option>
        </select>
      </label>
    </div>
  </section>

</div>

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
  <h2>Ergebnis <span id="rev-badge" class="badge"></span></h2>
  <p id="summary"></p>
  <p id="result-line" class="mono"></p>
  <div id="downloads" class="downloads"></div>
  <div id="inspect-out" class="out-box" hidden></div>

  <div id="viewer-wrap" class="viewer-wrap" hidden>
    <div class="viewer-bar">
      <strong>Architektur-Ansicht (live)</strong>
      <div style="display:flex;gap:8px;align-items:center">
        <button type="button" id="viewer-reload">Aktualisieren</button>
        <button type="button" id="viewer-toggle">Einklappen</button>
      </div>
    </div>
    <iframe id="viewer-frame" class="viewer-frame" title="Architektur-Ansicht"></iframe>
  </div>

  <div id="post-tools" class="post-grid" hidden>
    <div class="subcard">
      <h3>Chat with Data &mdash; Fragen an das Modell</h3>
      <p class="hint">Liest ausschlie&szlig;lich das aktuelle Modell. Ohne API-Schl&uuml;ssel wird der Ausschnitt lokal als Text ausgegeben.</p>
      <div class="two">
        <label>Ausschnitt
          <select id="chat-scope">
            <option value="model">Ganzes Modell</option>
            <option value="package">Paket</option>
            <option value="element">Element</option>
          </select>
        </label>
        <label id="chat-val-wrap" hidden>Auswahl
          <select id="chat-scope-val"></select>
        </label>
      </div>
      <textarea id="chat-q" rows="3" placeholder="z.B. Welche Dienste unterst&uuml;tzen welche F&auml;higkeiten und wo fehlen Beziehungen?"></textarea>
      <div class="sub-actions">
        <button type="button" id="chat-send">Fragen</button>
        <label class="row" style="margin:0;font-size:0.86rem;color:var(--muted)"><input type="checkbox" id="chat-no-ki"> ohne KI (nur Auszug)</label>
        <span id="chat-status" class="limits"></span>
      </div>
      <div id="chat-answer" class="out-box" hidden></div>
      <div id="chat-sources" class="sources"></div>
    </div>

    <div class="subcard">
      <h3>Architektur weiterbauen &amp; ver&auml;ndern</h3>
      <div class="mode-tabs">
        <button type="button" id="tab-nl" class="active">Per Anweisung &auml;ndern / erg&auml;nzen</button>
        <button type="button" id="tab-ext">Mit weiterer Prosa weiterbauen</button>
      </div>

      <div id="panel-nl">
        <p class="hint">Elemente/Pakete anlegen, verbinden, umbenennen, Notizen/Stereotypen &auml;ndern oder l&ouml;schen &mdash; erst Vorschau, dann MDG-gepr&uuml;ft anwenden.</p>
        <textarea id="nl-inst" rows="3" placeholder="z.B. Lege Element &quot;Wetterdienst&quot; als ServiceSpecification an und verbinde &quot;Faehigkeit B&quot; mit &quot;Wetterdienst&quot; ueber Exhibits."></textarea>
        <div class="sub-actions">
          <button type="button" id="nl-propose">Vorschau pr&uuml;fen</button>
          <label class="row" style="margin:0;font-size:0.86rem;color:var(--muted)"><input type="checkbox" id="nl-no-ki"> ohne KI</label>
          <span id="nl-status" class="limits"></span>
        </div>
        <div id="nl-preview" class="out-box" hidden></div>
        <div id="nl-apply-row" class="sub-actions" hidden>
          <label id="nl-confirm-wrap" class="row" hidden style="margin:0;font-size:0.86rem;color:#fca5a5"><input type="checkbox" id="nl-confirm"> L&ouml;schen best&auml;tigen</label>
          <button type="button" id="nl-apply">Anwenden &amp; Ansicht aktualisieren</button>
        </div>
      </div>

      <div id="panel-ext" hidden>
        <p class="hint">Erg&auml;nzt das bestehende Modell um weitere Prosa (<code>--modell</code>). Vorhandene Elemente &amp; Kennungen bleiben erhalten.</p>
        <textarea id="ext-text" rows="4" placeholder="Weitere Fachbeschreibung oder neue Anforderungen einf&uuml;gen &hellip;"></textarea>
        <div class="sub-actions">
          <button type="button" id="ext-go">Architektur erweitern</button>
          <span id="ext-status" class="limits"></span>
        </div>
      </div>
    </div>
  </div>

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
let currentJob = null;
let pendingOps = null;
let pendingDestructive = false;

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

function qeaNote(input, noteId) {
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    const note = $(noteId);
    if (!file) { note.hidden = true; note.textContent = ""; return; }
    note.hidden = false;
    note.textContent = file.name + " — " + size(file.size) +
      " (wird nur gelesen, nicht als Modell übernommen)";
  });
}
qeaNote(document.querySelector('input[name=startpaket]'), "startpaket-note");

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

function btn(label, onClick, primary) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  if (primary) b.className = "primary";
  b.addEventListener("click", onClick);
  return b;
}

function kiPayload(noKiChecked) {
  const fd = new FormData(form);
  return {
    use_ki: !noKiChecked,
    backend: fd.get("backend") || "datei",
    base_url: fd.get("base_url") || "",
    model: fd.get("model") || "",
    api_key: fd.get("api_key") || ""
  };
}

function refreshScopeOptions(info) {
  const kind = $("chat-scope").value;
  const wrap = $("chat-val-wrap");
  const sel = $("chat-scope-val");
  sel.innerHTML = "";
  const items = kind === "package" ? ((info && info.packages) || [])
    : kind === "element" ? ((info && info.elements) || []) : [];
  wrap.hidden = kind === "model";
  items.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item;
    opt.textContent = item;
    sel.appendChild(opt);
  });
}

function loadViewerFrame(state) {
  if (!(state && state.links && state.links.viewer)) {
    $("viewer-wrap").hidden = true;
    return;
  }
  $("viewer-wrap").hidden = false;
  const frame = $("viewer-frame");
  frame.hidden = false;
  $("viewer-toggle").textContent = "Einklappen";
  frame.src = state.links.viewer + "?rev=" + encodeURIComponent(String(state.revision || 1));
}

async function runInspect(url, label) {
  const out = $("inspect-out");
  out.hidden = false;
  out.className = "out-box";
  out.textContent = label + " laeuft ...";
  try {
    const r = await fetch(url, { cache: "no-store" });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    out.className = "out-box " + (data.ok === false ? "bad" : "ok");
    out.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    out.className = "out-box bad";
    out.textContent = "Fehler: " + err.message;
  }
}

function done(state, keepScroll) {
  currentJob = state;
  $("bar").style.width = "100%";
  show("result");
  $("rev-badge").textContent = state.revision ? ("Stand #" + state.revision) : "";
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
    const viewer = link(state.links.viewer, "Modell ansehen (neuer Tab)", true);
    viewer.target = "_blank";
    viewer.rel = "noopener";
    box.appendChild(viewer);
  }
  if (state.links && state.links.validate) {
    box.appendChild(btn("MDG pruefen", () => runInspect(state.links.validate, "MDG-Validierung")));
  }
  if (state.links && state.links.qs) {
    box.appendChild(btn("QS-Bericht", () => runInspect(state.links.qs, "QS-Pruefung")));
  }
  if (state.links && state.links.handbuch) {
    box.appendChild(link(state.links.handbuch, "Handbuch (.md)"));
  }
  if (state.links && state.links.zip) {
    box.appendChild(link(state.links.zip, "Alles als ZIP", !(state.links && state.links.viewer)));
  }
  ((state.links && state.links.files) || []).forEach((file) => {
    box.appendChild(link(file.href, file.name + " (" + size(file.size) + ")"));
  });

  loadViewerFrame(state);
  $("post-tools").hidden = !(state.links && state.links.chat);
  refreshScopeOptions(state.model_info || {});

  const findings = $("findings");
  findings.innerHTML = "";
  (state.findings || []).forEach((finding) => {
    addLog(findings, [finding.severity, finding.object, finding.message].filter(Boolean).join(" | "));
  });
  $("findings-box").hidden = !(state.findings || []).length;

  const log = $("result-log");
  log.innerHTML = "";
  (state.log || []).forEach((line) => addLog(log, line));
  if (!keepScroll) $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("viewer-reload").addEventListener("click", () => { if (currentJob) loadViewerFrame(currentJob); });
$("viewer-toggle").addEventListener("click", () => {
  const frame = $("viewer-frame");
  frame.hidden = !frame.hidden;
  $("viewer-toggle").textContent = frame.hidden ? "Einblenden" : "Einklappen";
});
$("chat-scope").addEventListener("change", () => refreshScopeOptions(currentJob && currentJob.model_info));

$("tab-nl").addEventListener("click", () => {
  $("tab-nl").classList.add("active");
  $("tab-ext").classList.remove("active");
  $("panel-nl").hidden = false;
  $("panel-ext").hidden = true;
});
$("tab-ext").addEventListener("click", () => {
  $("tab-ext").classList.add("active");
  $("tab-nl").classList.remove("active");
  $("panel-ext").hidden = false;
  $("panel-nl").hidden = true;
});

$("chat-send").addEventListener("click", async () => {
  if (!(currentJob && currentJob.links && currentJob.links.chat)) return;
  const q = $("chat-q").value.trim();
  if (!q) { $("chat-status").textContent = "Bitte eine Frage eingeben."; return; }
  $("chat-send").disabled = true;
  $("chat-status").textContent = "Antwort wird ermittelt ...";
  try {
    const body = Object.assign(kiPayload($("chat-no-ki").checked), {
      question: q,
      scope_kind: $("chat-scope").value,
      scope_value: $("chat-scope-val").value
    });
    const r = await fetch(currentJob.links.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    const ans = $("chat-answer");
    ans.hidden = false;
    ans.className = "out-box ok";
    ans.textContent = data.answer || "";
    $("chat-status").textContent = (data.model || "") + " · " + (data.scope || "");
    const srcBox = $("chat-sources");
    srcBox.innerHTML = "";
    (data.sources || []).slice(0, 30).forEach((s) => {
      const span = document.createElement("span");
      span.className = "src-pill";
      span.textContent = s;
      srcBox.appendChild(span);
    });
  } catch (err) {
    const ans = $("chat-answer");
    ans.hidden = false;
    ans.className = "out-box bad";
    ans.textContent = err.message;
    $("chat-status").textContent = "Fehler";
  } finally {
    $("chat-send").disabled = false;
  }
});

$("nl-propose").addEventListener("click", async () => {
  if (!(currentJob && currentJob.links && currentJob.links.edit)) return;
  const inst = $("nl-inst").value.trim();
  if (!inst) { $("nl-status").textContent = "Bitte Anweisung eingeben."; return; }
  $("nl-propose").disabled = true;
  $("nl-status").textContent = "Vorschlag wird geprueft ...";
  pendingOps = null;
  $("nl-apply-row").hidden = true;
  try {
    const body = Object.assign(kiPayload($("nl-no-ki").checked), {
      action: "propose",
      instruction: inst
    });
    const r = await fetch(currentJob.links.edit, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    pendingOps = data.ops || [];
    pendingDestructive = !!data.destructive;
    const prev = $("nl-preview");
    prev.hidden = false;
    prev.className = "out-box ok";
    const lines = [];
    if (data.reply) lines.push(data.reply, "");
    (data.preview || []).forEach((l) => lines.push(l));
    if ((data.warnings || []).length) lines.push("", "Hinweise:", ...data.warnings);
    prev.textContent = lines.join("\\n") || "Keine Operationen erkannt.";
    $("nl-status").textContent = (data.backend || "") + " · " + pendingOps.length + " Operation(en)";
    $("nl-confirm").checked = false;
    $("nl-confirm-wrap").hidden = !pendingDestructive;
    $("nl-apply-row").hidden = !pendingOps.length;
  } catch (err) {
    const prev = $("nl-preview");
    prev.hidden = false;
    prev.className = "out-box bad";
    prev.textContent = err.message;
    $("nl-status").textContent = "Fehler";
  } finally {
    $("nl-propose").disabled = false;
  }
});

$("nl-apply").addEventListener("click", async () => {
  if (!(currentJob && currentJob.links && currentJob.links.edit) || !pendingOps) return;
  if (pendingDestructive && !$("nl-confirm").checked) {
    $("nl-status").textContent = "Bitte Loeschvorgang bestaetigen.";
    return;
  }
  $("nl-apply").disabled = true;
  $("nl-status").textContent = "Wird angewendet ...";
  try {
    const r = await fetch(currentJob.links.edit, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "apply", ops: pendingOps, confirm: $("nl-confirm").checked })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    const prev = $("nl-preview");
    prev.hidden = false;
    const msg = [data.applied + " von " + data.total + " Operation(en) angewendet."];
    (data.changes || []).forEach((c) => msg.push("  + " + c));
    (data.rejected || []).forEach((rej) => msg.push("  ! Abgelehnt: " + (rej.grund || JSON.stringify(rej))));
    prev.className = "out-box " + ((data.rejected || []).length ? "bad" : "ok");
    prev.textContent = msg.join("\\n");
    $("nl-status").textContent = data.applied ? "Modell & Ansicht aktualisiert." : "Keine Aenderung uebernommen.";
    pendingOps = null;
    $("nl-apply-row").hidden = true;
    if (data.applied && data.job) {
      $("nl-inst").value = "";
      done(data.job, true);
    }
  } catch (err) {
    $("nl-status").textContent = "Fehler: " + err.message;
  } finally {
    $("nl-apply").disabled = false;
  }
});

$("ext-go").addEventListener("click", async () => {
  if (!(currentJob && currentJob.links && currentJob.links.extend)) return;
  const txt = $("ext-text").value.trim();
  if (!txt) { $("ext-status").textContent = "Bitte Text zum Weiterbauen eingeben."; return; }
  $("ext-go").disabled = true;
  $("ext-status").textContent = "Architektur wird erweitert ...";
  try {
    const body = Object.assign(kiPayload(false), { text: txt });
    const r = await fetch(currentJob.links.extend, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    $("ext-status").textContent = "Erweitert & Ansicht aktualisiert.";
    $("ext-text").value = "";
    if (data.job) done(data.job, true);
  } catch (err) {
    $("ext-status").textContent = "Fehler: " + err.message;
  } finally {
    $("ext-go").disabled = false;
  }
});

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
