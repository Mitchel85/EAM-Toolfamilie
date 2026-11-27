"""
title: EAM AI Suite (7-Stufen-Architekt) — Open WebUI Pipe
author: Michael Estel (EAM Toolfamilie)
author_url: https://github.com/Mitchel85/EAM-Toolfamilie
version: 1.0.0
license: MIT
description: >-
  Erscheint in Open WebUI als eigenes Modell ('EAM AI Suite'). Verarbeitet Prosa
  direkt ueber den laufenden EAM-AI-Suite-Container (`eam-ai serve`), liefert
  Fortschrittsstatus, QS-Zusammenfassung, Live-Viewer- und Download-Links und
  unterstuetzt Folgekommandos (`frage <job>: ...`, `aendere <job>: ...`,
  `diff <job>`, `repair <job>`, `undo <job>`).
requirements:
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Awaitable, Callable

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
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


async def _status(emitter: Emitter | None, text: str, *, done: bool = False) -> None:
    if emitter is None:
        return
    try:
        await emitter({"type": "status", "data": {"description": text, "done": done}})
    except Exception:  # noqa: BLE001
        pass


def _multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----eam-pipe-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for k, v in fields.items():
        if v:
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                    f"{v}\r\n"
                ).encode("utf-8")
            )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _req_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {"ok": True}


class Pipe:
    """Open WebUI Pipe-Funktion fuer den direkten 7-Stufen-Architekturbau ueber eam-ai serve."""

    class Valves(BaseModel):
        eam_api_url: str = Field(
            default="http://eam-toolfamilie:8080",
            description="Interne URL des EAM-AI-Suite-Containers (z. B. http://eam-toolfamilie:8080).",
        )
        public_api_url: str = Field(
            default="http://localhost:8080",
            description="Fuer den Nutzer im Browser erreichbare URL fuer Viewer- und Download-Links.",
        )
        llm_backend: str = Field(
            default="datei",
            description="Backend im Container: 'datei' (offline/Beispiel), 'openai' oder 'ollama'.",
        )
        llm_model: str = Field(default="", description="Modellname fuer openai/ollama.")
        llm_base_url: str = Field(default="", description="Optionale Endpunkt-URL fuer openai/ollama.")
        llm_api_key: str = Field(default="", description="Optionaler API-Schluessel.")
        default_format: str = Field(default="qea", description="Standard-Zielformat: qea, xmi, archimate, json.")
        default_sichten: str = Field(default="leitfaden", description="Standard-Sichten: leitfaden, mdg, aus.")
        context_tokens: int = Field(default=0, description="Kontextlimit fuer kleine LLMs (0 = Standard).")

    def __init__(self) -> None:
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [{"id": "eam-ai-suite", "name": "EAM AI Suite (7-Stufen-Architekt)"}]

    def _base(self) -> str:
        return str(self.valves.eam_api_url or "http://eam-toolfamilie:8080").rstrip("/")

    def _pub(self, path: str) -> str:
        base = str(self.valves.public_api_url or "").strip().rstrip("/") or self._base()
        return f"{base}{path if path.startswith('/') else '/' + path}" if path else ""

    async def pipe(
        self,
        body: dict[str, Any],
        __event_emitter__: Emitter | None = None,
    ) -> str:
        messages = body.get("messages") or []
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_msg = content.strip()
                elif isinstance(content, list):
                    user_msg = "\n".join(
                        str(p.get("text") or "") for p in content if isinstance(p, dict)
                    ).strip()
                break
        if not user_msg:
            return "Bitte Architekturprosa eingeben oder ein Kommando nutzen (`frage <job>: ...`, `aendere <job>: ...`, `diff <job>`, `repair <job>`, `undo <job>`)."

        # Folgekommandos auf bestehenden Jobs
        m_ask = re.match(r"^(?:frage|ask)\s+([A-Za-z0-9_-]+)\s*:\s*(.+)$", user_msg, re.IGNORECASE | re.DOTALL)
        if m_ask:
            job_id, question = m_ask.group(1), m_ask.group(2).strip()
            await _status(__event_emitter__, f"Chat with Data fuer Job {job_id} ...")
            res = _req_json(
                f"{self._base()}/api/jobs/{urllib.parse.quote(job_id)}/chat",
                method="POST",
                body=json.dumps({"question": question, "use_ki": self.valves.llm_backend != "datei"}).encode("utf-8"),
                content_type="application/json",
            )
            await _status(__event_emitter__, "Fertig.", done=True)
            srcs = ", ".join(f"`{s}`" for s in (res.get("sources") or [])[:15])
            return f"{res.get('answer', '')}\n\n**Quellen:** {srcs or '—'}"

        m_edit = re.match(r"^(?:aendere|ändere|edit)\s+([A-Za-z0-9_-]+)\s*:\s*(.+)$", user_msg, re.IGNORECASE | re.DOTALL)
        if m_edit:
            job_id, inst = m_edit.group(1), m_edit.group(2).strip()
            await _status(__event_emitter__, f"Wende Aenderung auf Job {job_id} an ...")
            res = _req_json(
                f"{self._base()}/api/jobs/{urllib.parse.quote(job_id)}/edit",
                method="POST",
                body=json.dumps({"action": "apply", "instruction": inst, "use_ki": self.valves.llm_backend != "datei"}).encode("utf-8"),
                content_type="application/json",
            )
            await _status(__event_emitter__, "Aenderung angewendet.", done=True)
            changes = "\n".join(f"- {c}" for c in (res.get("changes") or []))
            return f"**Aenderung angewendet** ({res.get('applied', 0)}/{res.get('total', 0)} Operationen):\n{changes or '- keine'}"

        m_cmd = re.match(r"^(diff|repair|undo)\s+([A-Za-z0-9_-]+)\s*$", user_msg, re.IGNORECASE)
        if m_cmd:
            cmd, job_id = m_cmd.group(1).lower(), m_cmd.group(2)
            await _status(__event_emitter__, f"Fuehre `{cmd}` fuer Job {job_id} aus ...")
            if cmd == "diff":
                res = _req_json(f"{self._base()}/api/jobs/{urllib.parse.quote(job_id)}/diff")
            elif cmd == "repair":
                res = _req_json(
                    f"{self._base()}/api/jobs/{urllib.parse.quote(job_id)}/repair",
                    method="POST",
                    body=b'{"action":"propose"}',
                    content_type="application/json",
                )
            else:
                res = _req_json(
                    f"{self._base()}/api/jobs/{urllib.parse.quote(job_id)}/undo",
                    method="POST",
                    body=b"{}",
                    content_type="application/json",
                )
            await _status(__event_emitter__, "Fertig.", done=True)
            return f"```json\n{json.dumps(res, indent=2, ensure_ascii=False)}\n```"

        # Standardpfad: Prosa -> Architekturbau ueber /build
        await _status(__event_emitter__, "1/3 Auftrag an EAM AI Suite senden ...")
        fields = {
            "mdg_source": "beispiel",
            "backend": self.valves.llm_backend or "datei",
            "package": "Architektur",
            "format": self.valves.default_format or "qea",
            "sichten": self.valves.default_sichten or "leitfaden",
            "text": user_msg,
            "model": self.valves.llm_model or "",
            "base_url": self.valves.llm_base_url or "",
            "api_key": self.valves.llm_api_key or "",
            "context_tokens": str(self.valves.context_tokens) if self.valves.context_tokens else "",
        }
        payload, ctype = _multipart(fields)
        try:
            started = _req_json(f"{self._base()}/build", method="POST", body=payload, content_type=ctype)
        except urllib.error.URLError as exc:
            await _status(__event_emitter__, "Container nicht erreichbar.", done=True)
            return f"**Fehler:** EAM-Container unter `{self._base()}` nicht erreichbar ({exc.reason})."

        job_id = started.get("job", "")
        status_path = started.get("status", "")
        await _status(__event_emitter__, f"2/3 Modell wird gebaut & MDG-geprueft (Job {job_id}) ...")
        deadline = time.monotonic() + 600
        state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            state = _req_json(self._base() + status_path)
            if state.get("state") in ("done", "error"):
                break
            time.sleep(1.5)

        if state.get("state") != "done":
            await _status(__event_emitter__, "Bau fehlgeschlagen.", done=True)
            return f"**Bau fehlgeschlagen** (Job `{job_id}`): {state.get('error') or 'Unbekannter Fehler'}"

        await _status(__event_emitter__, "3/3 Fertig.", done=True)
        links = state.get("links") or {}
        info = state.get("model_info") or {}
        findings = state.get("findings") or []
        lines = [
            f"### Architektur erstellt (Job `{job_id}`)",
            f"- **Elemente:** {info.get('element_count', '?')} · **Beziehungen:** {info.get('connector_count', '?')} · **Pakete:** {info.get('package_count', '?')} · **MDG-Befunde:** {len(findings)}",
        ]
        if links.get("viewer"):
            lines.append(f"- **Live-Viewer:** {self._pub(links['viewer'])}")
        if links.get("zip"):
            lines.append(f"- **Ergebnis-ZIP (.qea/Befunde/Quellen):** {self._pub(links['zip'])}")
        if links.get("handbuch"):
            lines.append(f"- **Betriebshandbuch:** {self._pub(links['handbuch'])}")
        lines += [
            "",
            "**Naechste Schritte direkt im Chat:**",
            f"- `frage {job_id}: Welche Systeme und Dienste sind enthalten?`",
            f"- `aendere {job_id}: Erstelle Element \"Wetterdienst\" als ServiceSpecification in Paket \"Architektur\".`",
            f"- `repair {job_id}` · `diff {job_id}` · `undo {job_id}`",
        ]
        return "\n".join(lines)
