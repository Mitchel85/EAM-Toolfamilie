"""
title: EAM AI Suite Python — Open WebUI Tool
author: Michael Estel (EAM Toolfamilie)
author_url: https://github.com/Mitchel85/EAM-Toolfamilie
version: 1.0.0
license: MIT
description: >-
  Bindet die EAM AI Suite Python (CLI, WebUI & Container) direkt in Open WebUI ein:
  Architekturen aus Prosa bauen, gegen MDG & ArchiMate-3.2-Matrix pruefen,
  Textabdeckung & Modell-Diff fahren, regelbasiert reparieren, per Sprache
  aendern/erweitern, per Chat with Data befragen und zwischen .qea/.xmi/.xml/.json
  konvertieren. Dual-Modus: HTTP-API (GHCR-Container) oder lokales `eam-ai`.
requirements:
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - Fallback fuer Tests ohne pydantic
    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            for cls in reversed(type(self).__mro__):
                for name in getattr(cls, "__annotations__", {}):
                    if name in kwargs:
                        setattr(self, name, kwargs[name])
                    elif hasattr(cls, name):
                        setattr(self, name, getattr(cls, name))

    def Field(default: Any = None, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return default


Emitter = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit_status(
    emitter: Emitter | None, description: str, *, done: bool = False
) -> None:
    if emitter is None:
        return
    try:
        await emitter(
            {
                "type": "status",
                "data": {"description": description, "done": done},
            }
        )
    except Exception:  # noqa: BLE001
        pass


def _encode_multipart(
    fields: dict[str, str],
    files: list[tuple[str, str, bytes, str]] | None = None,
) -> tuple[bytes, str]:
    boundary = f"----eam-openwebui-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for field_name, filename, data, content_type in files or []:
        ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode("utf-8")
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {"ok": True}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("error") or detail
        except Exception:  # noqa: BLE001
            msg = detail or str(exc)
        raise RuntimeError(f"HTTP {exc.code} von {url}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"EAM-Container unter {url} nicht erreichbar ({exc.reason}). "
            "Pruefe Valve `eam_api_url` oder starte ghcr.io/mitchel85/eam-toolfamilie:latest."
        ) from exc


class Tools:
    """Open WebUI Tool fuer die EAM AI Suite Python (HTTP-Container oder lokales eam-ai)."""

    class Valves(BaseModel):
        mode: str = Field(
            default="http",
            description="Betriebsmodus: 'http' (spricht eam-ai serve / GHCR-Container an) oder 'local' (lokal installiertes eam-ai).",
        )
        eam_api_url: str = Field(
            default="http://eam-toolfamilie:8080",
            description="Interne Basis-URL des EAM-AI-Suite-Containers (z. B. http://eam-toolfamilie:8080 oder http://127.0.0.1:8080).",
        )
        public_api_url: str = Field(
            default="http://localhost:8080",
            description="Fuer den Nutzer im Browser klickbare URL fuer Download- und Live-Viewer-Links.",
        )
        llm_backend: str = Field(
            default="datei",
            description="KI-Backend fuer den Bau in der Pipeline: 'datei' (offline/Beispiel), 'openai' oder 'ollama'.",
        )
        llm_model: str = Field(
            default="",
            description="Optionaler Modellname fuer openai/ollama (z. B. gpt-4o-mini, qwen2.5:14b).",
        )
        llm_base_url: str = Field(
            default="",
            description="Optionale API-Basis-URL fuer OpenAI-kompatiblen Endpunkt oder Ollama.",
        )
        llm_api_key: str = Field(
            default="",
            description="Optionaler API-Schluessel fuer OpenAI-kompatible Endpunkte (wird nicht protokolliert).",
        )
        default_context_tokens: int = Field(
            default=0,
            description="Optionales Kontextlimit fuer kleine lokale LLMs (z. B. 4096, 8192, 16384; 0 = Standard).",
        )
        default_mdg_path: str = Field(
            default="",
            description="Optionaler Pfad zu einer lokalen MDG-XML (leer = mitgelieferte Standard-MDG).",
        )
        python_executable: str = Field(
            default="",
            description="Nur fuer mode='local': Pfad zu Python mit installiertem `eam_ai` (leer = aktueller Interpreter).",
        )
        eam_core_dir: str = Field(
            default="",
            description="Nur fuer mode='local': Optionaler Ordner mit `eam_ai.py` (z. B. entpacktes eam-ai-suite-python).",
        )
        http_timeout_seconds: int = Field(
            default=120,
            description="HTTP-Timeout je Einzelanfrage an eam-ai serve in Sekunden.",
        )
        max_poll_seconds: int = Field(
            default=600,
            description="Maximale Wartezeit auf einen asynchronen Bau-Job in Sekunden.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def _api_base(self) -> str:
        return str(self.valves.eam_api_url or "http://eam-toolfamilie:8080").rstrip("/")

    def _public_base(self) -> str:
        pub = str(self.valves.public_api_url or "").strip().rstrip("/")
        return pub or self._api_base()

    def _public_link(self, path: str) -> str:
        if not path:
            return ""
        if path.startswith(("http://", "https://")):
            return path
        return f"{self._public_base()}{path if path.startswith('/') else '/' + path}"

    def _run_local_cli(self, args: list[str], *, timeout: int = 300) -> dict[str, Any]:
        py = str(self.valves.python_executable or "").strip() or sys.executable
        env = dict(os.environ)
        core_dir = str(self.valves.eam_core_dir or "").strip()
        if core_dir:
            prev = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = core_dir + (os.pathsep + prev if prev else "")
        proc = subprocess.run(
            [py, "-m", "eam_ai", *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }

    def _poll_job(self, status_path: str) -> dict[str, Any]:
        url = self._api_base() + status_path
        deadline = time.monotonic() + max(10, int(self.valves.max_poll_seconds or 600))
        while time.monotonic() < deadline:
            state = _http_json(url, timeout=float(self.valves.http_timeout_seconds or 120))
            if state.get("state") in ("done", "error"):
                return state
            time.sleep(1.5)
        raise RuntimeError(f"Zeitlimit beim Warten auf Job {status_path} ueberschritten.")

    def _format_job_result(self, state: dict[str, Any]) -> str:
        links = state.get("links") or {}
        summary = state.get("summary") or {}
        job_id = state.get("job", "")
        out = {
            "ok": state.get("state") == "done",
            "job_id": job_id,
            "state": state.get("state"),
            "revision": state.get("revision", 0),
            "can_undo": state.get("can_undo", False),
            "error": state.get("error"),
            "summary": summary,
            "model_info": state.get("model_info") or {},
            "findings_count": len(state.get("findings") or []),
            "downloads": {
                "zip": self._public_link(links.get("zip", "")),
                "viewer": self._public_link(links.get("viewer", "")),
                "handbuch": self._public_link(links.get("handbuch", "")),
                "files": [
                    {
                        "name": f.get("name"),
                        "size": f.get("size"),
                        "url": self._public_link(f.get("href", "")),
                    }
                    for f in (links.get("files") or [])
                ],
            },
        }
        return json.dumps(out, indent=2, ensure_ascii=False)

    async def build_architecture(
        self,
        prose_text: str,
        package_name: str = "Architektur",
        output_format: str = "qea",
        views_mode: str = "leitfaden",
        context_tokens: int = 0,
        mdg_path: str = "",
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Baut aus Prosa ein MDG-geprueftes Architekturmodell (.qea, .xmi, ArchiMate .xml oder .json).

        :param prose_text: Architekturbeschreibung, Pflichtenheft-Auszug oder Fachprosa.
        :param package_name: Wurzelpaketname (Default: Architektur).
        :param output_format: Zielformat: qea, xmi, archimate oder json.
        :param views_mode: Sichten-Modus: leitfaden, mdg oder aus.
        :param context_tokens: Optionales Kontextfenster fuer kleine LLMs (z. B. 4096, 8192, 16384; 0 = Standard).
        :param mdg_path: Optionaler Pfad zu einer eigenen MDG-XML (leer = Standard-MDG).
        """
        if not prose_text or not prose_text.strip():
            return json.dumps({"ok": False, "error": "prose_text darf nicht leer sein."}, ensure_ascii=False)

        await _emit_status(__event_emitter__, "Starte Architekturbau in EAM AI Suite Python ...")
        ctx = int(context_tokens or self.valves.default_context_tokens or 0)
        mdg = (mdg_path or self.valves.default_mdg_path or "").strip()

        if str(self.valves.mode).lower() == "local":
            import tempfile

            with tempfile.TemporaryDirectory(prefix="eam-owui-") as td:
                tdir = Path(td)
                txt_p = tdir / "prosa.md"
                txt_p.write_text(prose_text, encoding="utf-8")
                ext_map = {"qea": ".qea", "xmi": ".xmi", "archimate": ".xml", "json": ".json"}
                out_p = tdir / f"modell{ext_map.get(output_format, '.qea')}"
                cli_args = [
                    "build",
                    "--text",
                    str(txt_p),
                    "--paket",
                    package_name or "Architektur",
                    "--out",
                    str(out_p),
                    "--format",
                    output_format,
                    "--sichten",
                    views_mode,
                    "--backend",
                    self.valves.llm_backend or "datei",
                ]
                if mdg:
                    cli_args += ["--mdg", mdg]
                if ctx > 0:
                    cli_args += ["--kontext-tokens", str(ctx)]
                if self.valves.llm_model:
                    cli_args += ["--model", self.valves.llm_model]
                if self.valves.llm_base_url:
                    cli_args += ["--base-url", self.valves.llm_base_url]
                res = self._run_local_cli(cli_args, timeout=int(self.valves.max_poll_seconds or 600))
                await _emit_status(__event_emitter__, "Architekturbau abgeschlossen.", done=True)
                return json.dumps(res, indent=2, ensure_ascii=False)

        fields: dict[str, str] = {
            "mdg_source": "upload" if mdg and Path(mdg).is_file() else "beispiel",
            "backend": self.valves.llm_backend or "datei",
            "package": package_name or "Architektur",
            "format": output_format or "qea",
            "sichten": views_mode or "leitfaden",
            "text": prose_text,
        }
        if ctx > 0:
            fields["context_tokens"] = str(ctx)
        if self.valves.llm_model:
            fields["model"] = self.valves.llm_model
        if self.valves.llm_base_url:
            fields["base_url"] = self.valves.llm_base_url
        if self.valves.llm_api_key:
            fields["api_key"] = self.valves.llm_api_key

        files: list[tuple[str, str, bytes, str]] = []
        if mdg and Path(mdg).is_file():
            mp = Path(mdg)
            files.append(("mdg", mp.name, mp.read_bytes(), "application/xml"))

        body, ctype = _encode_multipart(fields, files)
        started = _http_json(
            f"{self._api_base()}/build",
            method="POST",
            body=body,
            content_type=ctype,
            timeout=float(self.valves.http_timeout_seconds or 120),
        )
        status_path = started.get("status")
        if not status_path:
            await _emit_status(__event_emitter__, "Unerwartete Antwort von /build.", done=True)
            return json.dumps(started, indent=2, ensure_ascii=False)

        await _emit_status(__event_emitter__, f"Job {started.get('job')} laeuft — pruefe Fortschritt ...")
        final = self._poll_job(status_path)
        await _emit_status(__event_emitter__, "Architekturbau abgeschlossen.", done=True)
        return self._format_job_result(final)

    async def validate_and_qs(
        self,
        model_path_or_job_id: str,
        mdg_path: str = "",
        requirements_text_path: str = "",
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Prueft ein Modell (Job-ID oder Dateipfad) gegen MDG/ArchiMate-Matrix, Waisen & optional Textabdeckung.

        :param model_path_or_job_id: Job-ID aus `build_architecture` oder Dateipfad (.qea, .xmi, .xml, .json).
        :param mdg_path: Optionaler Pfad zu einer MDG-XML.
        :param requirements_text_path: Optionaler Pfad zu Prosa/DOCX fuer die Pflichtenheft-Textabdeckung.
        """
        await _emit_status(__event_emitter__, "Fuehre MDG-Validierung & QS-Pruefung aus ...")
        target = model_path_or_job_id.strip()
        is_file = len(target) < 300 and Path(target).is_file()

        if str(self.valves.mode).lower() == "local" or (is_file and requirements_text_path):
            cli_args = ["qs", "--in", target]
            if mdg_path or self.valves.default_mdg_path:
                cli_args += ["--mdg", mdg_path or self.valves.default_mdg_path]
            if requirements_text_path:
                cli_args += ["--text", requirements_text_path]
            res = self._run_local_cli(cli_args)
            await _emit_status(__event_emitter__, "QS-Pruefung abgeschlossen.", done=True)
            return json.dumps(res, indent=2, ensure_ascii=False)

        if not is_file:
            res = _http_json(
                f"{self._api_base()}/api/jobs/{urllib.parse.quote(target)}/qs",
                timeout=float(self.valves.http_timeout_seconds or 120),
            )
            await _emit_status(__event_emitter__, "QS-Pruefung abgeschlossen.", done=True)
            return json.dumps(res, indent=2, ensure_ascii=False)

        mp = Path(target)
        files = [("model", mp.name, mp.read_bytes(), "application/octet-stream")]
        mdg = (mdg_path or self.valves.default_mdg_path or "").strip()
        if mdg and Path(mdg).is_file():
            gp = Path(mdg)
            files.append(("mdg", gp.name, gp.read_bytes(), "application/xml"))
        body, ctype = _encode_multipart({}, files)
        res = _http_json(
            f"{self._api_base()}/validate",
            method="POST",
            body=body,
            content_type=ctype,
            timeout=float(self.valves.http_timeout_seconds or 120),
        )
        await _emit_status(__event_emitter__, "Validierung abgeschlossen.", done=True)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def diff_architectures(
        self,
        old_model_or_job_id: str,
        new_model_path: str = "",
        mdg_path: str = "",
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Vergleicht zwei Architekturstaende semantisch (oder zeigt das Vorher-Nachher-Diff einer Job-ID).

        :param old_model_or_job_id: Entweder Job-ID (Diff gegen vorherige Revision) oder Pfad zur aelteren Datei.
        :param new_model_path: Nur bei Dateivergleich: Pfad zur neueren Datei (.qea, .xmi, .xml, .json).
        :param mdg_path: Optionaler Pfad zur MDG-XML fuer Befund-Delta.
        """
        await _emit_status(__event_emitter__, "Berechne semantischen Modell-Diff ...")
        if not new_model_path and str(self.valves.mode).lower() == "http":
            res = _http_json(
                f"{self._api_base()}/api/jobs/{urllib.parse.quote(old_model_or_job_id.strip())}/diff",
                timeout=float(self.valves.http_timeout_seconds or 120),
            )
            await _emit_status(__event_emitter__, "Modell-Diff fertig.", done=True)
            return json.dumps(res, indent=2, ensure_ascii=False)

        cli_args = ["diff", "--alt", old_model_or_job_id, "--neu", new_model_path, "--format", "json"]
        if mdg_path or self.valves.default_mdg_path:
            cli_args += ["--mdg", mdg_path or self.valves.default_mdg_path]
        res = self._run_local_cli(cli_args)
        await _emit_status(__event_emitter__, "Modell-Diff fertig.", done=True)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def repair_architecture(
        self,
        model_path_or_job_id: str,
        apply: bool = False,
        mdg_path: str = "",
        out_path: str = "",
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Regelbasierte MDG-Reparatur ohne KI (standardmaessig Vorschau; apply=True wendet Korrekturen an).

        :param model_path_or_job_id: Job-ID aus `build_architecture` oder Dateipfad.
        :param apply: False = nur Vorschau (Default), True = Korrekturen anwenden.
        :param mdg_path: Optionaler Pfad zur MDG-XML.
        :param out_path: Nur im local-Modus bei apply=True: Ausgabepfad fuer die reparierte Datei.
        """
        await _emit_status(__event_emitter__, "Pruefe regelbasierte MDG-Reparatur ...")
        target = model_path_or_job_id.strip()
        is_file = len(target) < 300 and Path(target).is_file()

        if not is_file and str(self.valves.mode).lower() == "http":
            payload = json.dumps({"action": "apply" if apply else "propose"}).encode("utf-8")
            res = _http_json(
                f"{self._api_base()}/api/jobs/{urllib.parse.quote(target)}/repair",
                method="POST",
                body=payload,
                content_type="application/json",
                timeout=float(self.valves.http_timeout_seconds or 120),
            )
            await _emit_status(__event_emitter__, "MDG-Reparatur abgeschlossen.", done=True)
            return json.dumps(res, indent=2, ensure_ascii=False)

        cli_args = ["repair", "--in", target, "--json"]
        if mdg_path or self.valves.default_mdg_path:
            cli_args += ["--mdg", mdg_path or self.valves.default_mdg_path]
        if apply and out_path:
            cli_args += ["--out", out_path, "--apply"]
        res = self._run_local_cli(cli_args)
        await _emit_status(__event_emitter__, "MDG-Reparatur abgeschlossen.", done=True)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def edit_architecture(
        self,
        job_id_or_qea_path: str,
        instruction: str,
        apply: bool = False,
        confirm_delete: bool = False,
        out_path: str = "",
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Aendert oder erweitert ein bestehendes Modell in natuerlicher Sprache (Vorschau oder direkt anwenden).

        :param job_id_or_qea_path: Job-ID aus `build_architecture` oder Pfad zu einer `.qea`.
        :param instruction: Deutsche Aenderungsanweisung (z. B. 'Erstelle Element "Wetterdienst" als ServiceSpecification in Paket "Architektur"').
        :param apply: False = nur Operationsvorschau (Default), True = direkt anwenden.
        :param confirm_delete: Nur bei Loeschoperationen auf True setzen.
        :param out_path: Nur im local-Modus bei apply=True: Zieldatei.
        """
        await _emit_status(__event_emitter__, "Bearbeite Architekturmodell ...")
        target = job_id_or_qea_path.strip()
        is_file = len(target) < 300 and Path(target).is_file()

        if not is_file and str(self.valves.mode).lower() == "http":
            payload_dict: dict[str, Any] = {
                "action": "apply" if apply else "propose",
                "instruction": instruction,
                "confirm": bool(confirm_delete),
                "use_ki": (self.valves.llm_backend or "datei") != "datei",
            }
            if self.valves.llm_backend and self.valves.llm_backend != "datei":
                payload_dict["backend"] = self.valves.llm_backend
            if self.valves.llm_model:
                payload_dict["model"] = self.valves.llm_model
            if self.valves.llm_base_url:
                payload_dict["base_url"] = self.valves.llm_base_url
            if self.valves.llm_api_key:
                payload_dict["api_key"] = self.valves.llm_api_key

            res = _http_json(
                f"{self._api_base()}/api/jobs/{urllib.parse.quote(target)}/edit",
                method="POST",
                body=json.dumps(payload_dict).encode("utf-8"),
                content_type="application/json",
                timeout=float(self.valves.http_timeout_seconds or 120),
            )
            await _emit_status(__event_emitter__, "Aenderung abgeschlossen.", done=True)
            return json.dumps(res, indent=2, ensure_ascii=False)

        cli_args = ["korrigiere", "--qea", target, "--anweisung", instruction, "--json"]
        if apply and out_path:
            cli_args += ["--out", out_path, "--apply"]
            if confirm_delete:
                cli_args.append("--ja")
        res = self._run_local_cli(cli_args)
        await _emit_status(__event_emitter__, "Aenderung abgeschlossen.", done=True)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def undo_architecture(
        self,
        job_id: str,
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Macht die letzte Aenderung an einem WebUI-/Container-Job rueckgaengig (1-Klick-Undo).

        :param job_id: Job-ID aus `build_architecture`.
        """
        await _emit_status(__event_emitter__, "Stelle vorherige Modell-Revision wieder her ...")
        res = _http_json(
            f"{self._api_base()}/api/jobs/{urllib.parse.quote(job_id.strip())}/undo",
            method="POST",
            body=b"{}",
            content_type="application/json",
            timeout=float(self.valves.http_timeout_seconds or 120),
        )
        await _emit_status(__event_emitter__, "Vorheriger Stand wiederhergestellt.", done=True)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def ask_architecture(
        self,
        job_id_or_qea_path: str,
        question: str,
        scope_kind: str = "model",
        scope_value: str = "",
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Chat with Data: beantwortet Fragen strikt anhand des geladenen Modells inkl. Quellbelegen.

        :param job_id_or_qea_path: Job-ID aus `build_architecture` oder Dateipfad zu einer `.qea`.
        :param question: Frage an das Architekturmodell.
        :param scope_kind: Ausschnitt: 'model', 'package' oder 'element'.
        :param scope_value: Paketpfad oder Elementname (falls scope_kind != 'model').
        """
        await _emit_status(__event_emitter__, "Frage Architekturmodell ab (Chat with Data) ...")
        target = job_id_or_qea_path.strip()
        is_file = len(target) < 300 and Path(target).is_file()

        if not is_file and str(self.valves.mode).lower() == "http":
            payload_dict: dict[str, Any] = {
                "question": question,
                "scope_kind": scope_kind or "model",
                "scope_value": scope_value or "",
                "use_ki": (self.valves.llm_backend or "datei") != "datei",
            }
            res = _http_json(
                f"{self._api_base()}/api/jobs/{urllib.parse.quote(target)}/chat",
                method="POST",
                body=json.dumps(payload_dict).encode("utf-8"),
                content_type="application/json",
                timeout=float(self.valves.http_timeout_seconds or 120),
            )
            await _emit_status(__event_emitter__, "Antwort liegt vor.", done=True)
            return json.dumps(res, indent=2, ensure_ascii=False)

        cli_args = ["frage", "--qea", target, "--frage", question]
        if scope_kind == "package" and scope_value:
            cli_args += ["--paket", scope_value]
        elif scope_kind == "element" and scope_value:
            cli_args += ["--element", scope_value]
        res = self._run_local_cli(cli_args)
        await _emit_status(__event_emitter__, "Antwort liegt vor.", done=True)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def convert_architecture(
        self,
        source_path: str,
        target_path: str,
        target_format: str = "",
        __event_emitter__: Emitter | None = None,
    ) -> str:
        """Konvertiert Modelle zwischen .qea, .xmi, ArchiMate .xml und .json (im lokalen Modus).

        :param source_path: Quelldatei (.qea, .xmi, .xml oder .json).
        :param target_path: Zieldatei.
        :param target_format: Optionales Zielformat (qea, xmi, archimate, json).
        """
        await _emit_status(__event_emitter__, "Konvertiere Architekturmodell ...")
        cli_args = ["convert", "--in", source_path, "--out", target_path]
        if target_format:
            cli_args += ["--format", target_format]
        res = self._run_local_cli(cli_args)
        await _emit_status(__event_emitter__, "Konvertierung abgeschlossen.", done=True)
        return json.dumps(res, indent=2, ensure_ascii=False)
