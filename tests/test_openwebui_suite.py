"""End-to-End-Tests fuer das Open-WebUI-Tool und die Pipe-Funktion der EAM AI Suite Python."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "packages" / "core"
RULES = ROOT / "packages" / "rules"
for p in (CORE, RULES):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import webui  # noqa: E402

OWUI_DIR = ROOT / "apps" / "cli" / "openwebui"
EXAMPLE = CORE / "examples" / "offline"
TEXT = (EXAMPLE / "prosa.txt").read_text(encoding="utf-8")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def live_webui(tmp_path: Path):
    server = webui.make_server(
        host="127.0.0.1",
        port=0,
        assets=EXAMPLE,
        workdir=tmp_path / "work",
        max_upload=5 * 1024 * 1024,
        max_seconds=120,
        max_jobs=2,
        job_ttl=300,
        version="test",
        log=lambda _message: None,
    )
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.stop()
        thread.join(timeout=5)


def test_openwebui_tool_http_end_to_end(live_webui: str) -> None:
    mod = _load_module("eam_ai_suite_openwebui", OWUI_DIR / "eam_ai_suite_openwebui.py")
    tools = mod.Tools()
    tools.valves.mode = "http"
    tools.valves.eam_api_url = live_webui
    tools.valves.public_api_url = live_webui
    tools.valves.llm_backend = "datei"

    # 1. Build
    built = json.loads(asyncio.run(tools.build_architecture(TEXT, package_name="Architektur")))
    assert built["ok"] is True, built
    job_id = built["job_id"]
    assert job_id
    assert built["downloads"]["viewer"].startswith(live_webui)
    assert built["downloads"]["zip"].startswith(live_webui)

    # 2. QS
    qs = json.loads(asyncio.run(tools.validate_and_qs(job_id)))
    assert "summary" in qs or "findings" in qs

    # 3. NL-Edit (apply) + Diff + Repair Preview + Chat + Undo
    edited = json.loads(
        asyncio.run(
            tools.edit_architecture(
                job_id,
                'Erstelle Element "Lagebilddienst" als ServiceSpecification in Paket "Architektur".',
                apply=True,
            )
        )
    )
    assert edited["ok"] is True
    assert edited["applied"] == 1

    diff = json.loads(asyncio.run(tools.diff_architectures(job_id)))
    assert diff["identical"] is False
    assert any(e["name"] == "Lagebilddienst" for e in diff["elements"]["added"])

    rep = json.loads(asyncio.run(tools.repair_architecture(job_id, apply=False)))
    assert rep["ok"] is True
    assert "changes" in rep

    chat = json.loads(asyncio.run(tools.ask_architecture(job_id, "Welche Elemente gibt es?")))
    assert chat["ok"] is True
    assert "Lagebilddienst" in chat["answer"]

    undone = json.loads(asyncio.run(tools.undo_architecture(job_id)))
    assert undone["ok"] is True


def test_openwebui_pipe_end_to_end(live_webui: str) -> None:
    mod = _load_module("eam_ai_suite_pipe", OWUI_DIR / "eam_ai_suite_pipe.py")
    pipe = mod.Pipe()
    pipe.valves.eam_api_url = live_webui
    pipe.valves.public_api_url = live_webui
    pipe.valves.llm_backend = "datei"

    assert pipe.pipes()[0]["id"] == "eam-ai-suite"

    reply = asyncio.run(pipe.pipe({"messages": [{"role": "user", "content": TEXT}]}))
    assert "Architektur erstellt" in reply
    assert live_webui in reply

    # Job-ID aus Antwort extrahieren und Folgekommando `frage` ausfuehren
    import re

    m = re.search(r"Job `([^`]+)`", reply)
    assert m, reply
    job_id = m.group(1)

    ans = asyncio.run(pipe.pipe({"messages": [{"role": "user", "content": f"frage {job_id}: Welche Elemente gibt es?"}]}))
    assert "Quellen:" in ans


def test_openwebui_begleitdateien_vorhanden() -> None:
    skill = (OWUI_DIR / "eam_ai_suite_skill.md").read_text(encoding="utf-8")
    compose = (OWUI_DIR / "docker-compose.openwebui.yml").read_text(encoding="utf-8")
    standalone_readme = (OWUI_DIR / "README-STANDALONE.md").read_text(encoding="utf-8")
    assert "eam_ai_suite_openwebui.py" in skill
    assert "ghcr.io/mitchel85/eam-toolfamilie:latest" in compose
    assert "eam_ai_suite_openwebui_standalone.py" in standalone_readme


def test_openwebui_standalone_zero_container_end_to_end(tmp_path: Path) -> None:
    """Generiert die autarken Standalone-Dateien und testet Tool + Pipe komplett ohne externen Server."""
    builder = _load_module("build_openwebui_standalone", ROOT / "scripts" / "build_openwebui_standalone.py")
    out_dir = tmp_path / "standalone_out"
    tool_path, pipe_path = builder.build_all(out_dir, version="1.0.0")
    assert tool_path.is_file()
    assert pipe_path.is_file()

    # 1. Standalone Tool testen (inkl. export_artifact in export_dir + Base64)
    tool_mod = _load_module("eam_ai_suite_openwebui_standalone", tool_path)
    tools = tool_mod.Tools()
    tools.valves.llm_backend = "datei"
    tools.valves.cache_dir = str(tmp_path / "cache_tool")
    tools.valves.export_dir = str(tmp_path / "exports")

    built = json.loads(asyncio.run(tools.build_architecture(TEXT, package_name="Architektur")))
    assert built["ok"] is True, built
    assert built["mode"] == "standalone"
    job_id = built["job_id"]

    qs = json.loads(asyncio.run(tools.validate_and_qs(job_id)))
    assert "summary" in qs or "findings" in qs

    edited = json.loads(
        asyncio.run(
            tools.nl_edit(
                job_id,
                'Erstelle Element "Lagebilddienst" als ServiceSpecification in Paket "Architektur".',
                apply=True,
            )
        )
    )
    assert edited["ok"] is True

    diff = json.loads(asyncio.run(tools.diff_versions(job_id)))
    assert diff["identical"] is False

    rep = json.loads(asyncio.run(tools.repair_preview(job_id, apply=False)))
    assert rep["ok"] is True

    chat = json.loads(asyncio.run(tools.ask_model(job_id, "Welche Elemente gibt es?")))
    assert chat["ok"] is True
    assert "Lagebilddienst" in chat["answer"]

    exported = json.loads(asyncio.run(tools.export_artifact(job_id, "ergebnis.zip", as_base64=True)))
    assert exported["ok"] is True
    assert exported["bytes"] > 100
    assert exported["base64"]
    assert Path(exported["saved_path"]).is_file()

    undone = json.loads(asyncio.run(tools.undo_version(job_id)))
    assert undone["ok"] is True

    # 2. Standalone Pipe testen (Build + Folgekommando `frage`)
    pipe_mod = _load_module("eam_ai_suite_pipe_standalone", pipe_path)
    pipe = pipe_mod.Pipe()
    pipe.valves.llm_backend = "datei"
    pipe.valves.cache_dir = str(tmp_path / "cache_pipe")
    assert pipe.pipes()[0]["id"] == "eam-ai-suite-standalone"

    reply = asyncio.run(pipe.pipe({"messages": [{"role": "user", "content": TEXT}]}))
    assert "Architektur erstellt (Standalone" in reply
    assert "[eam-job:" in reply

    ans = asyncio.run(
        pipe.pipe(
            {
                "messages": [
                    {"role": "user", "content": TEXT},
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": "frage Welche Elemente gibt es?"},
                ]
            }
        )
    )
    assert "[eam-job:" in ans
