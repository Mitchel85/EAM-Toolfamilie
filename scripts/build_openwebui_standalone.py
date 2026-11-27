#!/usr/bin/env python3
"""Baut die autarken Standalone-Open-WebUI-Dateien (Zero-Container, Zero-pip).

    python3 scripts/build_openwebui_standalone.py --out dist --version 1.0.0

Erzeugt zwei selbstenthaltene Python-Dateien fuer Open WebUI-Hosts, auf denen
weder Docker-Container noch `pip install` moeglich sind:

  - ``eam_ai_suite_openwebui_standalone.py``  (Open WebUI Tool)
  - ``eam_ai_suite_pipe_standalone.py``       (Open WebUI Pipe-Funktion)

Beide Dateien betten `packages/core`, `packages/rules/mdg_parser.py`, das
aktuelle MDG-Regelwerk (`knowledge/regelwerk.json` + MDG-XML) sowie die
Offline-Beispiel-Assets als deterministisches, zlib-komprimiertes ZIP in Base64
ein. Beim ersten Aufruf entpacken sie die Laufzeitumgebung einmalig in ein
Cache-Verzeichnis und starten einen internen Loopback-Server
(`127.0.0.1:<ephemeral-port>`) im eigenen Python-Prozess.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "packages" / "core"
RULES_DIR = ROOT / "packages" / "rules"
KNOWLEDGE_DIR = ROOT / "knowledge"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def _sammlung_runtime_dateien() -> list[tuple[str, Path]]:
    """Liefert alle Dateien fuer das eingebettete Runtime-Archiv (sortiert)."""
    eintraege: list[tuple[str, Path]] = []

    for pfad in sorted(CORE_DIR.glob("*.py")):
        if pfad.name == "conftest.py":
            continue
        eintraege.append((f"packages/core/{pfad.name}", pfad))

    for name in ("rules.schema.json", "batch-schema.json"):
        pfad = CORE_DIR / name
        if pfad.is_file():
            eintraege.append((f"packages/core/{name}", pfad))

    offline_dir = CORE_DIR / "examples" / "offline"
    if offline_dir.is_dir():
        for pfad in sorted(offline_dir.iterdir()):
            if pfad.is_file():
                eintraege.append((f"packages/core/examples/offline/{pfad.name}", pfad))

    parser_pfad = RULES_DIR / "mdg_parser.py"
    if parser_pfad.is_file():
        eintraege.append(("packages/rules/mdg_parser.py", parser_pfad))

    current_pfad = RULES_DIR / "CURRENT"
    if current_pfad.is_file():
        eintraege.append(("packages/rules/CURRENT", current_pfad))
        aktuell = current_pfad.read_text(encoding="utf-8").strip()
        if aktuell:
            mdg_pfad = RULES_DIR / aktuell
            if mdg_pfad.is_file():
                eintraege.append((f"packages/rules/{mdg_pfad.name}", mdg_pfad))

    regelwerk = KNOWLEDGE_DIR / "regelwerk.json"
    if regelwerk.is_file():
        eintraege.append(("knowledge/regelwerk.json", regelwerk))

    eintraege.sort(key=lambda item: item[0])
    return eintraege


def baue_payload_zip() -> tuple[bytes, str]:
    """Packt den Python-Kern deterministisch in ein In-Memory-ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arcname, pfad in _sammlung_runtime_dateien():
            info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, pfad.read_bytes())
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def _format_b64(raw: bytes) -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    return "\n".join(textwrap.wrap(b64, 100))


_SHARED_RUNTIME_BLOCK = '''
_RUNTIME_LOCK = threading.Lock()
_EMBEDDED_SERVERS: dict[str, tuple[Any, str, Path]] = {}


def _ensure_runtime(cache_dir: str = "") -> Path:
    """Entpackt den eingebetteten Python-Kern einmalig und atomar ins Cache-Verzeichnis."""
    base = Path(cache_dir).expanduser() if cache_dir else (Path(tempfile.gettempdir()) / "eam_ai_suite_standalone")
    target = base / f"runtime_{PAYLOAD_SHA256[:12]}"
    marker = target / ".ready"
    if marker.is_file():
        return target
    with _RUNTIME_LOCK:
        if marker.is_file():
            return target
        base.mkdir(parents=True, exist_ok=True)
        staging = base / f".staging_{PAYLOAD_SHA256[:12]}_{uuid.uuid4().hex[:8]}"
        staging.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(PAYLOAD_B64)
        with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
            zf.extractall(staging)
        (staging / ".ready").write_text(PAYLOAD_SHA256 + "\\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(staging, ignore_errors=True)
        else:
            staging.replace(target)
        return target


def _ensure_embedded_server(cache_dir: str = "", max_seconds: int = 600) -> tuple[str, Path]:
    """Startet genau einen internen Loopback-WebUI-Server (127.0.0.1:0) im Prozess."""
    runtime = _ensure_runtime(cache_dir)
    key = str(runtime.resolve())
    existing = _EMBEDDED_SERVERS.get(key)
    if existing is not None:
        return existing[1], existing[2]

    with _RUNTIME_LOCK:
        existing = _EMBEDDED_SERVERS.get(key)
        if existing is not None:
            return existing[1], existing[2]

        core_dir = runtime / "packages" / "core"
        rules_dir = runtime / "packages" / "rules"
        for p in (str(core_dir), str(rules_dir)):
            if p not in sys.path:
                sys.path.insert(0, p)

        existing_pp = os.environ.get("PYTHONPATH", "")
        needed_pp = os.pathsep.join([str(core_dir), str(rules_dir)])
        if str(core_dir) not in existing_pp.split(os.pathsep):
            os.environ["PYTHONPATH"] = needed_pp + (os.pathsep + existing_pp if existing_pp else "")

        regelwerk = runtime / "knowledge" / "regelwerk.json"
        if regelwerk.is_file():
            os.environ["EAM_REGELWERK"] = str(regelwerk)

        import webui  # type: ignore[import-not-found]

        workdir = runtime.parent / "workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        assets = core_dir / "examples" / "offline"
        server = webui.make_server(
            host="127.0.0.1",
            port=0,
            assets=assets,
            workdir=workdir,
            max_upload=25 * 1024 * 1024,
            max_seconds=max(60, int(max_seconds)),
            max_jobs=4,
            job_ttl=3600,
            version=SUITE_VERSION,
            log=lambda _msg: None,
        )
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
            name="eam-ai-standalone-webui",
        )
        thread.start()
        host, port = server.server_address[:2]
        base_url = f"http://{host}:{port}"
        _EMBEDDED_SERVERS[key] = (server, base_url, workdir)
        return base_url, workdir


def _encode_multipart(
    fields: dict[str, str],
    files: list[tuple[str, str, bytes, str]] | None = None,
) -> tuple[bytes, str]:
    boundary = f"----eam-standalone-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        parts.append(
            (
                f"--{boundary}\\r\\n"
                f'Content-Disposition: form-data; name="{key}"\\r\\n\\r\\n'
                f"{value}\\r\\n"
            ).encode("utf-8")
        )
    for field_name, filename, data, content_type in files or []:
        ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(
            (
                f"--{boundary}\\r\\n"
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\\r\\n'
                f"Content-Type: {ctype}\\r\\n\\r\\n"
            ).encode("utf-8")
            + data
            + b"\\r\\n"
        )
    parts.append(f"--{boundary}--\\r\\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _http_bytes(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> tuple[bytes, str]:
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("error") or detail
        except Exception:  # noqa: BLE001
            msg = detail or str(exc)
        raise RuntimeError(f"HTTP {exc.code} von {url}: {msg}") from exc


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    raw, _ = _http_bytes(url, method=method, body=body, content_type=content_type, timeout=timeout)
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text) if text.strip() else {"ok": True}
'''


def _baue_tool_quelltext(version: str, payload_b64: str, payload_sha: str) -> str:
    return f'''"""
title: EAM AI Suite Python — Open WebUI Tool (Standalone, ohne Container)
author: Michael Estel (EAM Toolfamilie)
author_url: https://github.com/Mitchel85/EAM-Toolfamilie
version: {version}
license: MIT
description: >-
  Vollstaendig autarke Open-WebUI-Variante der EAM AI Suite Python ohne Docker,
  ohne externen Server und ohne pip-Abhaengigkeiten (air-gapped faehig).
  Baut MDG-konforme Architekturen aus Prosa, prueft gegen MDG & ArchiMate 3.2,
  fuehrt NL-Edit, Diff, Auto-Repair, Chat with Data & Undo aus und exportiert
  .qea/.xmi/.xml/.json/HTML-Viewer direkt aus dem Open-WebUI-Prozess.
requirements:
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            for cls in reversed(type(self).__mro__):
                for name in getattr(cls, "__annotations__", {{}}):
                    if name in kwargs:
                        setattr(self, name, kwargs[name])
                    elif hasattr(cls, name):
                        setattr(self, name, getattr(cls, name))

    def Field(default: Any = None, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return default


SUITE_VERSION = "{version}"
PAYLOAD_SHA256 = "{payload_sha}"
PAYLOAD_B64 = """\\
{payload_b64}
"""

Emitter = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit_status(
    emitter: Emitter | None, description: str, *, done: bool = False
) -> None:
    if emitter is None:
        return
    try:
        await emitter({{"type": "status", "data": {{"description": description, "done": done}}}})
    except Exception:  # noqa: BLE001
        pass

{_SHARED_RUNTIME_BLOCK}


class Tools:
    """Open-WebUI-Werkzeug fuer die autarke EAM AI Suite Python (Zero-Container)."""

    class Valves(BaseModel):
        llm_backend: str = Field(
            default="openai",
            description="LLM-Backend fuer `eam-ai build`: 'openai' (auch Ollama/vLLM/Open-WebUI) oder 'datei' (Offline-Demo).",
        )
        llm_base_url: str = Field(
            default="",
            description="OpenAI-kompatible Basis-URL (z. B. http://localhost:11434/v1 oder Open-WebUI-API).",
        )
        llm_model: str = Field(
            default="",
            description="Modellname fuer das LLM-Backend (z. B. qwen2.5:14b, gpt-4.1-mini).",
        )
        llm_api_key: str = Field(
            default="",
            description="API-Key fuer das LLM-Backend (falls erforderlich).",
        )
        cache_dir: str = Field(
            default="",
            description="Optionales Cache-Verzeichnis fuer die entpackte Runtime (leer = System-Temp).",
        )
        export_dir: str = Field(
            default="",
            description="Optionales Ausgabeverzeichnis auf dem Host fuer export_artifact().",
        )
        timeout_seconds: int = Field(
            default=600,
            description="Maximale Laufzeit pro Architektur-Build in Sekunden.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def _server_url(self) -> str:
        url, _ = _ensure_embedded_server(
            cache_dir=self.valves.cache_dir,
            max_seconds=self.valves.timeout_seconds,
        )
        return url

    def _poll_job(self, base: str, status_path: str) -> dict[str, Any]:
        url = base + status_path if status_path.startswith("/") else f"{{base}}/api/jobs/{{status_path}}"
        deadline = time.monotonic() + max(30, int(self.valves.timeout_seconds))
        while time.monotonic() < deadline:
            data = _http_json(url, timeout=30.0)
            if data.get("state") in ("done", "error"):
                return data
            time.sleep(0.35)
        raise TimeoutError(f"Job {{status_path}} hat das Zeitlimit von {{self.valves.timeout_seconds}}s ueberschritten.")

    async def build_architecture(
        self,
        prosa_text: str,
        package_name: str = "Architektur",
        mdg_xml_path: str = "",
        with_views: bool = False,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Baut aus Prosa ein MDG-konformes Architekturmodell (.qea, .xmi, .json, ArchiMate) komplett ohne Container.

        :param prosa_text: Fachliche Beschreibung / Prosa fuer die Architektur.
        :param package_name: Zielpaketname im Modell (Standard: 'Architektur').
        :param mdg_xml_path: Optionaler Pfad zu einer eigenen MDG-XML auf dem Host (leer = mitgelieferte MDG).
        :param with_views: Wenn True, erzeugt zusaetzlich EA-Diagrammsichten.
        :return: JSON-Bericht mit job_id, Kennzahlen, Befunden und verfuegbaren Artefakten.
        """
        await _emit_status(__event_emitter__, "Starte autarke EAM AI Suite Runtime...")
        base = self._server_url()

        has_mdg = bool(mdg_xml_path and Path(mdg_xml_path).is_file())
        fields: dict[str, str] = {{
            "mdg_source": "upload" if has_mdg else "beispiel",
            "text": prosa_text,
            "package": package_name or "Architektur",
            "backend": self.valves.llm_backend or "openai",
            "format": "qea",
            "sichten": "leitfaden" if with_views else "aus",
        }}
        if self.valves.llm_base_url:
            fields["base_url"] = self.valves.llm_base_url
        if self.valves.llm_model:
            fields["model"] = self.valves.llm_model
        if self.valves.llm_api_key:
            fields["api_key"] = self.valves.llm_api_key

        files: list[tuple[str, str, bytes, str]] = []
        if has_mdg:
            mdg_file = Path(mdg_xml_path)
            files.append(("mdg", mdg_file.name, mdg_file.read_bytes(), "application/xml"))

        await _emit_status(__event_emitter__, "Starte 7-Stufen-Pipeline (Standalone)...")
        body, ctype = _encode_multipart(fields, files)
        started = _http_json(f"{{base}}/build", method="POST", body=body, content_type=ctype, timeout=60.0)
        job_id = started.get("job") or started.get("id") or started.get("job_id")
        status_path = started.get("status") or (f"/api/jobs/{{job_id}}" if job_id else "")
        if not job_id:
            return json.dumps({{"ok": False, "error": "Keine job_id erhalten", "raw": started}}, ensure_ascii=False)

        result = self._poll_job(base, status_path)
        ok = result.get("state") == "done"
        await _emit_status(
            __event_emitter__,
            f"Fertig (Job {{job_id}})" if ok else f"Fehler (Job {{job_id}})",
            done=True,
        )
        links = result.get("links") or {{}}
        file_names = [f.get("name") for f in (links.get("files") or []) if f.get("name")]
        return json.dumps(
            {{
                "ok": ok,
                "mode": "standalone",
                "job_id": job_id,
                "state": result.get("state"),
                "summary": result.get("summary") or {{}},
                "artifacts": file_names or ["ergebnis.zip", "modell.qea", "findings.json", "viewer"],
                "hint": "Mit export_artifact(job_id, filename) koennen Dateien (z. B. 'findings.json', 'modell.qea', 'ergebnis.zip', 'viewer') ausgelesen oder als Base64 exportiert werden.",
                "error": result.get("error"),
            }},
            ensure_ascii=False,
        )

    async def validate_and_qs(
        self,
        job_id: str,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Fuehrt Qualitaetssicherung (MDG-Konformitaet, ArchiMate-Matrix, Waisen, Textabdeckung) fuer einen Job aus."""
        await _emit_status(__event_emitter__, f"Pruefe QS fuer Job {{job_id}}...")
        base = self._server_url()
        res = _http_json(f"{{base}}/api/jobs/{{job_id}}/qs", timeout=60.0)
        await _emit_status(__event_emitter__, "QS abgeschlossen.", done=True)
        return json.dumps(res, ensure_ascii=False)

    async def nl_edit(
        self,
        job_id: str,
        instruction: str,
        apply: bool = False,
        confirm_delete: bool = False,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Aendert oder erweitert das Modell per natuerlicher Sprache (Vorschau oder direkt anwenden)."""
        await _emit_status(
            __event_emitter__,
            f"NL-Edit ({{'anwenden' if apply else 'Vorschau'}}) fuer Job {{job_id}}...",
        )
        base = self._server_url()
        payload_dict: dict[str, Any] = {{
            "action": "apply" if apply else "propose",
            "instruction": instruction,
            "confirm": bool(confirm_delete),
            "use_ki": (self.valves.llm_backend or "datei") != "datei",
        }}
        if self.valves.llm_backend and self.valves.llm_backend != "datei":
            payload_dict["backend"] = self.valves.llm_backend
        if self.valves.llm_model:
            payload_dict["model"] = self.valves.llm_model
        if self.valves.llm_base_url:
            payload_dict["base_url"] = self.valves.llm_base_url
        if self.valves.llm_api_key:
            payload_dict["api_key"] = self.valves.llm_api_key
        res = _http_json(
            f"{{base}}/api/jobs/{{job_id}}/edit",
            method="POST",
            body=json.dumps(payload_dict).encode("utf-8"),
            content_type="application/json",
            timeout=120.0,
        )
        await _emit_status(__event_emitter__, "NL-Edit abgeschlossen.", done=True)
        return json.dumps(res, ensure_ascii=False)

    async def diff_versions(
        self,
        job_id: str,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Vergleicht die aktuelle Modellversion mit dem vorherigen Stand (Modell-Diff)."""
        await _emit_status(__event_emitter__, f"Berechne Diff fuer Job {{job_id}}...")
        base = self._server_url()
        res = _http_json(f"{{base}}/api/jobs/{{job_id}}/diff", timeout=60.0)
        await _emit_status(__event_emitter__, "Diff erstellt.", done=True)
        return json.dumps(res, ensure_ascii=False)

    async def repair_preview(
        self,
        job_id: str,
        apply: bool = False,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Regelbasierte Reparatur ohne KI (Vorschau oder direkt anwenden)."""
        await _emit_status(
            __event_emitter__,
            f"Auto-Repair ({{'anwenden' if apply else 'Vorschau'}}) fuer Job {{job_id}}...",
        )
        base = self._server_url()
        res = _http_json(
            f"{{base}}/api/jobs/{{job_id}}/repair",
            method="POST",
            body=json.dumps({{"apply": bool(apply)}}).encode("utf-8"),
            content_type="application/json",
            timeout=60.0,
        )
        await _emit_status(__event_emitter__, "Auto-Repair abgeschlossen.", done=True)
        return json.dumps(res, ensure_ascii=False)

    async def ask_model(
        self,
        job_id: str,
        question: str,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Befragt das erzeugte Modell per Chat with Data (Fakten direkt aus dem Modell)."""
        await _emit_status(__event_emitter__, f"Befrage Modell (Job {{job_id}})...")
        base = self._server_url()
        payload = json.dumps(
            {{
                "question": question,
                "scope_kind": "model",
                "scope_value": "",
                "use_ki": (self.valves.llm_backend or "datei") != "datei",
            }}
        ).encode("utf-8")
        res = _http_json(
            f"{{base}}/api/jobs/{{job_id}}/chat",
            method="POST",
            body=payload,
            content_type="application/json",
            timeout=60.0,
        )
        await _emit_status(__event_emitter__, "Antwort ermittelt.", done=True)
        return json.dumps(res, ensure_ascii=False)

    async def undo_version(
        self,
        job_id: str,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Macht die letzte Aenderung am Modell rueckgaengig (Undo)."""
        await _emit_status(__event_emitter__, f"Undo fuer Job {{job_id}}...")
        base = self._server_url()
        res = _http_json(
            f"{{base}}/api/jobs/{{job_id}}/undo",
            method="POST",
            body=b"{{}}",
            content_type="application/json",
            timeout=60.0,
        )
        await _emit_status(__event_emitter__, "Undo ausgefuehrt.", done=True)
        return json.dumps(res, ensure_ascii=False)

    async def export_artifact(
        self,
        job_id: str,
        filename: str = "ergebnis.zip",
        as_base64: bool = False,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Exportiert ein erzeugtes Artefakt (z. B. 'ergebnis.zip', 'modell.qea', 'findings.json', 'viewer').

        Wenn `export_dir` in den Valves gesetzt ist, wird die Datei dort gespeichert.
        Bei `as_base64=True` (oder fuer Text-/JSON-Dateien) wird der Inhalt direkt geliefert.
        """
        await _emit_status(__event_emitter__, f"Exportiere {{filename}} (Job {{job_id}})...")
        base = self._server_url()
        if filename == "viewer":
            url = f"{{base}}/api/jobs/{{job_id}}/viewer"
            out_name = f"{{job_id}}_viewer.html"
        else:
            safe = urllib.parse.quote(filename, safe="")
            url = f"{{base}}/api/jobs/{{job_id}}/{{safe}}"
            out_name = Path(filename).name

        raw, ctype = _http_bytes(url, timeout=60.0)
        saved_path = ""
        if self.valves.export_dir:
            dest_dir = Path(self.valves.export_dir).expanduser()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{{job_id}}_{{out_name}}"
            dest.write_bytes(raw)
            saved_path = str(dest)

        result: dict[str, Any] = {{
            "ok": True,
            "job_id": job_id,
            "filename": out_name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content_type": ctype,
        }}
        if saved_path:
            result["saved_path"] = saved_path

        is_text = ctype.startswith("text/") or "json" in ctype or out_name.endswith((".json", ".txt", ".md"))
        if as_base64:
            result["base64"] = base64.b64encode(raw).decode("ascii")
        elif is_text and len(raw) <= 65536:
            result["text"] = raw.decode("utf-8", errors="replace")

        await _emit_status(__event_emitter__, f"Export fertig ({{len(raw)}} B).", done=True)
        return json.dumps(result, ensure_ascii=False)
'''


def _baue_pipe_quelltext(version: str, payload_b64: str, payload_sha: str) -> str:
    return f'''"""
title: EAM AI Suite Python — 7-Stufen-Architekt (Standalone, ohne Container)
author: Michael Estel (EAM Toolfamilie)
author_url: https://github.com/Mitchel85/EAM-Toolfamilie
version: {version}
license: MIT
description: >-
  Vollstaendig autarke Open-WebUI-Pipe-Funktion ohne Docker und ohne externen
  Server. Erscheint als eigenes Modell ("EAM AI Suite Standalone") und fuehrt
  die komplette 7-Stufen-Pipeline inkl. QS, Chat with Data, NL-Edit, Diff,
  Auto-Repair, Undo und Export direkt im Open-WebUI-Prozess aus.
requirements:
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            for cls in reversed(type(self).__mro__):
                for name in getattr(cls, "__annotations__", {{}}):
                    if name in kwargs:
                        setattr(self, name, kwargs[name])
                    elif hasattr(cls, name):
                        setattr(self, name, getattr(cls, name))

    def Field(default: Any = None, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return default


SUITE_VERSION = "{version}"
PAYLOAD_SHA256 = "{payload_sha}"
PAYLOAD_B64 = """\\
{payload_b64}
"""

Emitter = Callable[[dict[str, Any]], Awaitable[None]]
_JOB_TAG_RE = re.compile(r"\\[eam-job:([A-Za-z0-9_-]+)\\]")


async def _emit_status(
    emitter: Emitter | None, description: str, *, done: bool = False
) -> None:
    if emitter is None:
        return
    try:
        await emitter({{"type": "status", "data": {{"description": description, "done": done}}}})
    except Exception:  # noqa: BLE001
        pass

{_SHARED_RUNTIME_BLOCK}


class Pipe:
    """Open-WebUI-Pipe-Funktion fuer die autarke EAM AI Suite Python (Zero-Container)."""

    class Valves(BaseModel):
        llm_backend: str = Field(
            default="openai",
            description="LLM-Backend: 'openai' (auch Ollama/vLLM/Open-WebUI) oder 'datei' (Offline-Demo).",
        )
        llm_base_url: str = Field(
            default="",
            description="OpenAI-kompatible Basis-URL (z. B. http://localhost:11434/v1).",
        )
        llm_model: str = Field(
            default="",
            description="Modellname fuer das LLM-Backend.",
        )
        llm_api_key: str = Field(
            default="",
            description="API-Key fuer das LLM-Backend (falls noetig).",
        )
        package_name: str = Field(
            default="Architektur",
            description="Standard-Paketname im erzeugten Modell.",
        )
        with_views: bool = Field(
            default=False,
            description="Zusaetzlich EA-Diagrammsichten erzeugen.",
        )
        cache_dir: str = Field(
            default="",
            description="Optionales Cache-Verzeichnis fuer die entpackte Runtime.",
        )
        export_dir: str = Field(
            default="",
            description="Optionales Ausgabeverzeichnis fuer fertige Dateien.",
        )
        timeout_seconds: int = Field(
            default=600,
            description="Maximale Laufzeit pro Architektur-Build in Sekunden.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [
            {{
                "id": "eam-ai-suite-standalone",
                "name": "EAM AI Suite Standalone (7-Stufen-Architekt, ohne Container)",
            }}
        ]

    def _find_last_job_id(self, messages: list[dict[str, Any]]) -> str | None:
        for msg in reversed(messages):
            content = msg.get("content")
            if isinstance(content, str):
                match = _JOB_TAG_RE.search(content)
                if match:
                    return match.group(1)
        return None

    async def pipe(
        self,
        body: dict[str, Any],
        __event_emitter__: Emitter | None = None,
    ) -> str:
        messages = body.get("messages") or []
        if not messages:
            return "Bitte Architektur-Prosa eingeben oder ein Folgekommando (`frage ...`, `aendere ...`, `diff`, `repair`, `undo`, `export <datei>`) senden."

        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                last_user = content if isinstance(content, str) else str(content)
                break
        text = last_user.strip()
        if not text:
            return "Leere Eingabe — bitte Prosa oder Kommando senden."

        await _emit_status(__event_emitter__, "Starte autarke EAM AI Suite Runtime...")
        base, _ = _ensure_embedded_server(
            cache_dir=self.valves.cache_dir,
            max_seconds=self.valves.timeout_seconds,
        )
        last_job = self._find_last_job_id(messages)
        lower = text.lower()

        if last_job:
            if lower.startswith("frage "):
                frage = text[6:].strip()
                res = _http_json(
                    f"{{base}}/api/jobs/{{last_job}}/chat",
                    method="POST",
                    body=json.dumps(
                        {{
                            "question": frage,
                            "scope_kind": "model",
                            "scope_value": "",
                            "use_ki": (self.valves.llm_backend or "datei") != "datei",
                        }}
                    ).encode("utf-8"),
                    content_type="application/json",
                )
                await _emit_status(__event_emitter__, "Antwort bereit.", done=True)
                antwort = res.get("answer") or json.dumps(res, ensure_ascii=False, indent=2)
                return f"{{antwort}}\\n\\n<!-- [eam-job:{{last_job}}] -->"

            if lower.startswith("aendere ") or lower.startswith("ändere "):
                anweisung = text.split(" ", 1)[1].strip()
                res = _http_json(
                    f"{{base}}/api/jobs/{{last_job}}/edit",
                    method="POST",
                    body=json.dumps(
                        {{
                            "action": "apply",
                            "instruction": anweisung,
                            "confirm": False,
                            "use_ki": (self.valves.llm_backend or "datei") != "datei",
                        }}
                    ).encode("utf-8"),
                    content_type="application/json",
                    timeout=120.0,
                )
                await _emit_status(__event_emitter__, "Aenderung angewendet.", done=True)
                return f"**NL-Edit angewendet**\\n\\n```json\\n{{json.dumps(res, ensure_ascii=False, indent=2)}}\\n```\\n\\n<!-- [eam-job:{{last_job}}] -->"

            if lower == "diff":
                res = _http_json(f"{{base}}/api/jobs/{{last_job}}/diff")
                await _emit_status(__event_emitter__, "Diff erstellt.", done=True)
                return f"**Modell-Diff**\\n\\n```json\\n{{json.dumps(res, ensure_ascii=False, indent=2)}}\\n```\\n\\n<!-- [eam-job:{{last_job}}] -->"

            if lower.startswith("repair"):
                apply = "apply" in lower or "anwenden" in lower
                res = _http_json(
                    f"{{base}}/api/jobs/{{last_job}}/repair",
                    method="POST",
                    body=json.dumps({{"apply": bool(apply)}}).encode("utf-8"),
                    content_type="application/json",
                )
                await _emit_status(__event_emitter__, "Auto-Repair fertig.", done=True)
                return f"**Auto-Repair ({{'angewendet' if apply else 'Vorschau'}})**\\n\\n```json\\n{{json.dumps(res, ensure_ascii=False, indent=2)}}\\n```\\n\\n<!-- [eam-job:{{last_job}}] -->"

            if lower == "undo":
                res = _http_json(
                    f"{{base}}/api/jobs/{{last_job}}/undo",
                    method="POST",
                    body=b"{{}}",
                    content_type="application/json",
                )
                await _emit_status(__event_emitter__, "Undo ausgefuehrt.", done=True)
                return f"**Undo ausgefuehrt**\\n\\n```json\\n{{json.dumps(res, ensure_ascii=False, indent=2)}}\\n```\\n\\n<!-- [eam-job:{{last_job}}] -->"

            if lower.startswith("export"):
                parts = text.split(None, 1)
                fname = parts[1].strip() if len(parts) > 1 else "ergebnis.zip"
                url = f"{{base}}/api/jobs/{{last_job}}/viewer" if fname == "viewer" else f"{{base}}/api/jobs/{{last_job}}/{{urllib.parse.quote(fname, safe='')}}"
                raw, _ = _http_bytes(url, timeout=60.0)
                saved = ""
                if self.valves.export_dir:
                    dest = Path(self.valves.export_dir).expanduser() / f"{{last_job}}_{{Path(fname).name}}"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(raw)
                    saved = f"\\n- Gespeichert unter: `{{dest}}`"
                await _emit_status(__event_emitter__, "Export abgeschlossen.", done=True)
                return (
                    f"**Export `{{fname}}`** ({{len(raw)}} B, SHA-256 `{{hashlib.sha256(raw).hexdigest()[:16]}}...`){{saved}}\\n\\n"
                    f"<!-- [eam-job:{{last_job}}] -->"
                )

        # Neuer 7-Stufen-Build
        await _emit_status(__event_emitter__, "Starte 7-Stufen-Architektur-Build (Standalone)...")
        fields: dict[str, str] = {{
            "mdg_source": "beispiel",
            "text": text,
            "package": self.valves.package_name or "Architektur",
            "backend": self.valves.llm_backend or "openai",
            "format": "qea",
            "sichten": "leitfaden" if self.valves.with_views else "aus",
        }}
        if self.valves.llm_base_url:
            fields["base_url"] = self.valves.llm_base_url
        if self.valves.llm_model:
            fields["model"] = self.valves.llm_model
        if self.valves.llm_api_key:
            fields["api_key"] = self.valves.llm_api_key

        body_bytes, ctype = _encode_multipart(fields)
        started = _http_json(f"{{base}}/build", method="POST", body=body_bytes, content_type=ctype, timeout=60.0)
        job_id = started.get("job") or started.get("id") or started.get("job_id")
        status_path = started.get("status") or (f"/api/jobs/{{job_id}}" if job_id else "")
        if not job_id:
            await _emit_status(__event_emitter__, "Build fehlgeschlagen.", done=True)
            return f"Fehler beim Start: `{{json.dumps(started, ensure_ascii=False)}}`"

        deadline = time.monotonic() + max(30, int(self.valves.timeout_seconds))
        result: dict[str, Any] = {{}}
        while time.monotonic() < deadline:
            poll_url = base + status_path if status_path.startswith("/") else f"{{base}}/api/jobs/{{job_id}}"
            result = _http_json(poll_url, timeout=30.0)
            if result.get("state") in ("done", "error"):
                break
            time.sleep(0.35)

        if result.get("state") != "done":
            await _emit_status(__event_emitter__, "Build mit Fehler beendet.", done=True)
            return f"**Build fehlgeschlagen** (Job `{{job_id}}`): {{result.get('error') or result.get('state')}}"

        qs = _http_json(f"{{base}}/api/jobs/{{job_id}}/qs", timeout=60.0)
        await _emit_status(__event_emitter__, f"Architektur fertig (Job {{job_id}}).", done=True)

        summary = result.get("summary") or result.get("result") or {{}}
        qs_sum = qs.get("summary") or {{}}
        lines = [
            f"### Architektur erstellt (Standalone, Job `{{job_id}}`)",
            "",
            f"- **Elemente:** {{summary.get('elements', qs_sum.get('elements', '–'))}}",
            f"- **Beziehungen:** {{summary.get('connectors', qs_sum.get('connectors', '–'))}}",
            f"- **QS-Befunde:** {{summary.get('errors', qs_sum.get('errors', 0))}} Fehler, {{summary.get('warnings', qs_sum.get('warnings', 0))}} Warnungen",
            "",
            "**Folgekommandos in diesem Chat:**",
            "- `frage <Frage an das Modell>`",
            "- `aendere <Aenderungsanweisung in Prosa>`",
            "- `diff` | `repair` | `repair apply` | `undo` | `export ergebnis.zip`",
            "",
            f"<!-- [eam-job:{{job_id}}] -->",
        ]
        return "\\n".join(lines)
'''


def build_all(out_dir: Path, version: str = "1.0.0") -> tuple[Path, Path]:
    """Erzeugt Tool- und Pipe-Standalone-Dateien in `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_zip, payload_sha = baue_payload_zip()
    payload_b64 = _format_b64(raw_zip)

    tool_path = out_dir / "eam_ai_suite_openwebui_standalone.py"
    pipe_path = out_dir / "eam_ai_suite_pipe_standalone.py"

    tool_path.write_text(
        _baue_tool_quelltext(version, payload_b64, payload_sha),
        encoding="utf-8",
        newline="\n",
    )
    pipe_path.write_text(
        _baue_pipe_quelltext(version, payload_b64, payload_sha),
        encoding="utf-8",
        newline="\n",
    )
    return tool_path, pipe_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Baut die autarken Standalone-Open-WebUI-Dateien.")
    ap.add_argument("--out", default="dist", help="Ausgabeverzeichnis")
    ap.add_argument("--version", default="1.0.0", help="Versionsnummer")
    args = ap.parse_args()
    tool_path, pipe_path = build_all((ROOT / args.out).resolve(), args.version)
    print(f"Standalone Tool: {tool_path} ({tool_path.stat().st_size:,} B)")
    print(f"Standalone Pipe: {pipe_path} ({pipe_path.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
