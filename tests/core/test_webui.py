"""Tests fuer webui.py -- Weboberflaeche mit demselben Kern wie die CLI.

Geprueft wird, was die Karte fordert und was still kaputtgehen kann:
* HTTP-Endpunkt baut aus Beispiel-Text eine .qea, die ``qea_reader`` liest
  (Datei-Backend, kein Netz),
* Upload ueber der Grenze wird mit 413 und Klartext abgelehnt,
* Dateinamen werden sanitisiert und nie als Pfad benutzt,
* Zeitlimit und Aufraeumen greifen,
* fehlende Beispiel-Assets und unbekannte Pfade liefern klare Fehler.

Kein Netz ausser Loopback, keine echten Modelle, keine Personendaten.
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

import eam_ai
import webui
from qea_reader import read_qea

ROOT = Path(__file__).resolve().parents[2] / "packages" / "core"  # Monorepo: Kernpaket
EXAMPLE = ROOT / "examples" / "offline"
TEXT = (EXAMPLE / "prosa.txt").read_text(encoding="utf-8")
BOUNDARY = "----eamai-test"


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def build_body(
    fields: dict[str, str], files: tuple[tuple[str, str, bytes, str], ...] = ()
) -> tuple[bytes, str]:
    out = bytearray()
    for name, value in fields.items():
        out += f"--{BOUNDARY}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    for name, filename, data, content_type in files:
        out += f"--{BOUNDARY}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        ).encode()
        out += f"Content-Type: {content_type}\r\n\r\n".encode()
        out += data + b"\r\n"
    out += f"--{BOUNDARY}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={BOUNDARY}"


def base_url(server: webui.WebServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def get(url: str) -> tuple[int, bytes, dict[str, str]]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def post_build(server: webui.WebServer, fields, files=()) -> tuple[int, dict]:
    body, content_type = build_body(fields, files)
    request = urllib.request.Request(
        base_url(server) + "/build",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_for(server: webui.WebServer, payload: dict, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body, _ = get(base_url(server) + payload["status"])
        assert status == 200, body
        state = json.loads(body.decode("utf-8"))
        if state["state"] != "running":
            return state
        time.sleep(0.1)
    raise AssertionError("Lauf wurde nicht fertig")


def start_server(tmp_path: Path, **options) -> tuple[webui.WebServer, threading.Thread]:
    parameters = {
        "host": "127.0.0.1",
        "port": 0,
        "max_upload": 4 * 1024 * 1024,
        "max_seconds": 90,
        "max_jobs": 2,
        "job_ttl": 120,
        "workdir": tmp_path / "arbeit",
        "assets": EXAMPLE,
        "version": "test",
        "log": lambda _message: None,
    }
    parameters.update(options)
    server = webui.make_server(**parameters)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    return server, thread


@pytest.fixture
def server(tmp_path: Path):
    instance, thread = start_server(tmp_path)
    yield instance
    instance.shutdown()
    instance.stop()
    thread.join(timeout=5)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_seite_und_healthz(server: webui.WebServer) -> None:
    status, body, headers = get(base_url(server) + "/healthz")
    assert status == 200
    info = json.loads(body.decode("utf-8"))
    assert info["status"] == "ok"
    assert info["beispiel"] is True
    assert info["max_upload_bytes"] == 4 * 1024 * 1024
    assert headers["X-Content-Type-Options"] == "nosniff"

    status, body, headers = get(base_url(server) + "/")
    assert status == 200
    page = body.decode("utf-8")
    assert "EAM AI Suite Python" in page
    assert "Bauen" in page
    assert headers["Content-Type"].startswith("text/html")
    assert "script-src 'unsafe-inline'" in headers["Content-Security-Policy"]

    status, body, _ = get(base_url(server) + "/gibt-es-nicht")
    assert status == 404
    assert "Nicht gefunden" in json.loads(body.decode("utf-8"))["error"]


def test_build_aus_beispiel_erzeugt_lesbare_qea(server: webui.WebServer, tmp_path: Path) -> None:
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei", "package": "Architektur", "text": TEXT},
    )
    assert status == 202, payload
    state = wait_for(server, payload)

    assert state["state"] == "done", state["error"]
    # Struktur + Inhalt: die drei Elemente aus dem Text sind enthalten,
    # dazu kommen die Geruestelemente des Regelwerks.
    assert state["summary"]["elements"] >= 3
    assert state["summary"]["connectors"] >= 1
    assert state["summary"]["errors"] == 0
    assert any(line.startswith("[1/6]") for line in state["log"])
    assert any(line.startswith("[6/6]") for line in state["log"])
    assert state["result_line"].startswith("modell.qea: geschrieben")
    assert "sitzung-" not in state["result_line"]

    names = {entry["name"] for entry in state["files"]}
    assert any(name.endswith(".qea") for name in names)
    assert {"findings.json", "quellen.json"} <= names
    assert state["links"]["zip"].endswith("/ergebnis.zip")

    status, zipped, headers = get(base_url(server) + state["links"]["zip"])
    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        inside = set(archive.namelist())
        assert inside == names
        qea_name = next(name for name in inside if name.endswith(".qea"))
        qea_bytes = archive.read(qea_name)
        findings = json.loads(archive.read("findings.json").decode("utf-8"))
        quellen = json.loads(archive.read("quellen.json").decode("utf-8"))

    assert findings == []
    assert sorted(quellen) == ["D1-S1", "D1-S2", "D1-S3"]

    # Einzeldownload liefert dieselben Bytes wie das ZIP.
    status, single, headers = get(base_url(server) + state["links"]["files"][0]["href"])
    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    if state["links"]["files"][0]["name"] == qea_name:
        assert single == qea_bytes

    target = tmp_path / "download.qea"
    target.write_bytes(qea_bytes)
    ir = read_qea(target)
    assert len(ir["elements"]) >= 3
    assert len(ir["connectors"]) >= 1
    assert {"Ablauf A", "Faehigkeit B", "Dienst C"} <= {
        element["name"] for element in ir["elements"]
    }
    assert ir["technology"]["profile"] == "NAFv4-ADMBw"


def test_textdatei_und_sanitierter_name(server: webui.WebServer, tmp_path: Path) -> None:
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei"},
        files=(("textdatei", "../../böse.txt", TEXT.encode("utf-8"), "text/plain"),),
    )
    assert status == 202, payload
    state = wait_for(server, payload)
    assert state["state"] == "done", state["error"]
    assert any(entry["name"] == "bose.qea" for entry in state["files"])

    job = server.get_job(payload["job"])
    assert job is not None
    # Nur feste Namen auf Platte, nichts ausserhalb des Arbeitsverzeichnisses.
    stored = {path.name for path in job.directory.rglob("*") if path.is_file()}
    assert "text.txt" in stored
    assert "bose.qea" in stored
    assert not any(name in {"passwd", "böse.txt"} for name in stored)
    for path in job.directory.rglob("*"):
        assert path.resolve().is_relative_to(job.directory.resolve())


def test_upload_ueber_limit_wird_abgelehnt(tmp_path: Path) -> None:
    server, thread = start_server(tmp_path, max_upload=4096)
    try:
        status, payload = post_build(
            server,
            {"mdg_source": "beispiel", "backend": "datei", "text": "x" * 6000},
        )
        assert status == 413
        assert payload["ok"] is False
        assert "Upload zu gross" in payload["error"]
        assert "MB" in payload["error"]
        # Nichts wurde angelegt.
        assert server.jobs == {}
    finally:
        server.shutdown()
        server.stop()
        thread.join(timeout=5)


def test_zeitlimit_bricht_lauf_ab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def langsam(_prepared, _job_dir, _seconds):  # noqa: ANN001 - Testdouble
        return [sys.executable, "-c", "import time; time.sleep(5)"]

    monkeypatch.setattr(webui, "build_command", langsam)
    server, thread = start_server(tmp_path, max_seconds=0.4)
    try:
        started = time.time()
        status, payload = post_build(
            server, {"mdg_source": "beispiel", "backend": "datei", "text": TEXT}
        )
        assert status == 202, payload
        state = wait_for(server, payload, timeout=20)
        assert state["state"] == "failed"
        assert "Zeitlimit" in state["error"]
        assert time.time() - started < 15
    finally:
        server.shutdown()
        server.stop()
        thread.join(timeout=5)


def test_arbeitsverzeichnis_wird_aufgeraeumt(tmp_path: Path) -> None:
    server, thread = start_server(tmp_path, job_ttl=0.2)
    try:
        status, payload = post_build(
            server, {"mdg_source": "beispiel", "backend": "datei", "text": TEXT}
        )
        assert status == 202, payload
        state = wait_for(server, payload)
        assert state["state"] == "done", state["error"]
        job = server.get_job(payload["job"])
        assert job is not None and job.directory.is_dir()
        time.sleep(0.3)
        assert server.purge_expired() == 1
        assert not job.directory.exists()
        assert server.get_job(payload["job"]) is None
    finally:
        server.shutdown()
        server.stop()
        thread.join(timeout=5)


def test_fehlende_beispiele_klare_meldung(tmp_path: Path) -> None:
    server, thread = start_server(tmp_path, assets=tmp_path / "leer")
    try:
        status, payload = post_build(
            server, {"mdg_source": "beispiel", "backend": "datei", "text": TEXT}
        )
        assert status == 500
        assert "fehlt" in payload["error"]
    finally:
        server.shutdown()
        server.stop()
        thread.join(timeout=5)


def test_unbekannter_auftrag_und_pfad_traversal(server: webui.WebServer) -> None:
    status, body, _ = get(base_url(server) + "/api/jobs/gibtsnicht")
    assert status == 404
    assert "Unbekannter Auftrag" in json.loads(body.decode("utf-8"))["error"]

    status, body, _ = get(base_url(server) + "/api/jobs/gibtsnicht/../../etc/passwd")
    assert status == 404


def test_leere_hochladungen_klare_meldung(server: webui.WebServer) -> None:
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei", "text": TEXT},
        files=(("textdatei", "leer.txt", b"", "text/plain"),),
    )
    assert status == 400
    assert "leer" in payload["error"]

    status, payload = post_build(
        server,
        {"mdg_source": "upload", "backend": "datei", "text": TEXT},
        files=(("mdg", "leer.xml", b"", "application/xml"),),
    )
    assert status == 400
    assert "leer" in payload["error"]

    # Ein leeres Dateifeld des Browsers (filename="") ist "keine Datei";
    # der eingefuegte Text gilt und der Lauf startet.
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei", "text": TEXT},
        files=(("textdatei", "", b"", "application/octet-stream"),),
    )
    assert status == 202, payload
    assert wait_for(server, payload)["state"] == "done"


def test_langer_text_wird_angenommen(server: webui.WebServer) -> None:
    """Mehr als MAX_FIELD_CHARS Zeichen sind fuer das Textfeld normal."""
    text = "\n\n".join(
        f"Absatz {index}: Der Ablauf A steuert die Faehigkeit B." for index in range(200)
    )
    assert len(text) > 5000
    status, payload = post_build(
        server, {"mdg_source": "beispiel", "backend": "datei", "text": text}
    )
    assert status == 202, payload
    state = wait_for(server, payload)
    assert state["state"] != "running"
    assert "zu lang" not in (state["error"] or "")


def test_sanitize_filename() -> None:
    assert webui.sanitize_filename("../../etc/passwd") == "passwd"
    assert webui.sanitize_filename("..\\..\\windows\\evil.txt") == "evil.txt"
    assert webui.sanitize_filename("Prüfung 2026.xml") == "Prufung_2026.xml"
    assert webui.sanitize_filename("") == "upload.bin"
    assert webui.sanitize_filename(None) == "upload.bin"
    assert webui.sanitize_filename("....") == "upload.bin"
    assert webui.sanitize_filename("/absolute/pfad/modell.qea") == "modell.qea"

    lang = webui.sanitize_filename("a" * 200 + ".qea")
    assert len(lang) <= 80
    assert lang.endswith(".qea")
    assert "/" not in lang and "\\" not in lang


def test_default_package_passt_zum_kern() -> None:
    assert webui.DEFAULT_PACKAGE_NAME == eam_ai.DEFAULT_PACKAGE


def test_modell_ansehen_liefert_selbsttragende_ansicht(server: webui.WebServer) -> None:
    """Nach dem Bau: 'Modell ansehen' liefert die grafische Ansicht derselben .qea.

    Geprueft werden Link, Inhalt, Selbsttragung (kein Netz) und der Alias-Pfad
    ``/job/<id>/viewer``; ein unbekannter Auftrag bleibt ein 404.
    """
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei", "package": "Architektur", "text": TEXT},
    )
    assert status == 202, payload
    state = wait_for(server, payload)
    assert state["state"] == "done", state["error"]

    assert state["links"]["viewer"] == f"/api/jobs/{state['job']}/viewer"

    status, body, headers = get(base_url(server) + state["links"]["viewer"])
    assert status == 200, body[:200]
    page = body.decode("utf-8")
    assert page.startswith("<!doctype html>")
    assert "Ablauf A" in page
    assert "Faehigkeit B" in page
    assert "http://" not in page.lower()
    assert "https://" not in page.lower()
    assert "<script src" not in page.lower()
    assert headers["Content-Type"].startswith("text/html")
    assert "script-src 'unsafe-inline'" in headers["Content-Security-Policy"]

    status, alias, _ = get(base_url(server) + f"/job/{state['job']}/viewer")
    assert status == 200
    assert alias == body

    status, body, _ = get(base_url(server) + "/api/jobs/gibtsnicht/viewer")
    assert status == 404
    assert "Unbekannter Auftrag" in json.loads(body.decode("utf-8"))["error"]

# --------------------------------------------------------------------------
# Startpaket und Katalog
# --------------------------------------------------------------------------

STARTPAKET = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"


def test_seite_bietet_startpaket_upload(server: webui.WebServer) -> None:
    status, body, _ = get(base_url(server) + "/")
    assert status == 200
    page = body.decode("utf-8")
    assert 'name="startpaket"' in page
    assert 'name="katalog"' not in page  # ein Feld, ein Zweck
    assert "Startpaket &ndash; .qea" in page
    assert "StEKa" not in page  # nur "Startpaket" nennen
    assert "nicht als Modell kopiert" in page
    status, body, _ = get(base_url(server) + "/healthz")
    assert json.loads(body.decode("utf-8"))["startpaket_upload"] is True


def test_startpaket_wird_gelesen_und_nicht_kopiert(tmp_path: Path) -> None:
    """Ein grosses Startpaket sprengt die 25-MB-Grenze -- hier mit eigenem Limit."""
    if not STARTPAKET.is_file():  # pragma: no cover - Fixture fehlt
        pytest.skip("Musterarchitektur_MASC.qea fehlt")
    server, thread = start_server(tmp_path, max_upload=64 * 1024 * 1024)
    try:
        status, payload = post_build(
            server,
            {"mdg_source": "beispiel", "backend": "datei", "package": "Architektur", "text": TEXT},
            files=(("startpaket", "StEKa.qea", STARTPAKET.read_bytes(), "application/octet-stream"),),
        )
        assert status == 202, payload
        state = wait_for(server, payload)
        assert state["state"] == "done", state["error"]
        assert any(line.startswith("Startpaket:") for line in state["log"])

        job = server.get_job(payload["job"])
        assert job is not None
        assert (job.directory / "input" / "startpaket.qea").is_file()

        ziel = job.directory / next(
            name for name in (j["name"] for j in state["files"]) if name.endswith(".qea")
        )
        con = sqlite3.connect(str(ziel))
        con.execute("PRAGMA query_only = ON")
        try:
            wurzeln = {name for (name,) in con.execute("SELECT Name FROM t_package WHERE Parent_ID=0")}
        finally:
            con.close()
        assert "StEKa" in wurzeln
        assert "MASC" not in wurzeln
    finally:
        server.shutdown()
        server.stop()
        thread.join(timeout=5)


def test_startpaket_mit_falscher_endung_wird_abgelehnt(server: webui.WebServer) -> None:
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei", "text": TEXT},
        files=(("startpaket", "StEKa.qea", b"<xml/>", "application/octet-stream"),),
    )
    assert status == 400, payload
    assert "Startpaket" in payload["error"]


def test_kaputtes_startpaket_klare_meldung(server: webui.WebServer) -> None:
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei", "text": TEXT},
        files=(("startpaket", "start.qea", b"kein sqlite", "application/octet-stream"),),
    )
    assert status == 400, payload
    assert "Startpaket nicht lesbar" in payload["error"]


@pytest.mark.parametrize("fmt,ext", [
    ("xmi", ".xmi"),
    ("archimate", ".xml"),
    ("json", ".json"),
])
def test_build_alternative_formate_und_viewer(server: webui.WebServer, fmt: str, ext: str) -> None:
    status, payload = post_build(
        server,
        {
            "mdg_source": "beispiel",
            "backend": "datei",
            "package": "Architektur",
            "format": fmt,
            "text": TEXT,
        },
    )
    assert status == 202, payload
    state = wait_for(server, payload)
    assert state["state"] == "done", state["error"]

    names = {entry["name"] for entry in state["files"]}
    assert any(name.endswith(ext) for name in names), f"Keine Datei mit Endung {ext} gefunden in {names}"

    # Viewer-Link muss vorhanden sein und 200 liefern
    assert "viewer" in state["links"]
    v_status, v_body, v_headers = get(base_url(server) + state["links"]["viewer"])
    assert v_status == 200
    assert "Modellansicht" in v_body.decode("utf-8")


def test_job_validate_endpoint(server: webui.WebServer) -> None:
    status, payload = post_build(
        server,
        {
            "mdg_source": "beispiel",
            "backend": "datei",
            "package": "Architektur",
            "text": TEXT,
        },
    )
    assert status == 202, payload
    state = wait_for(server, payload)
    assert state["state"] == "done", state["error"]

    val_url = base_url(server) + f"/api/jobs/{payload['job']}/validate"
    val_status, val_body, _ = get(val_url)
    assert val_status == 200
    res = json.loads(val_body.decode("utf-8"))
    assert "ok" in res
    assert "summary" in res
    assert "findings" in res


def test_direct_validate_endpoint(server: webui.WebServer, tmp_path: Path) -> None:
    ir = {
        "ir_version": 1,
        "technology": {"profile": "Synthetisch"},
        "packages": [{"path": "Root"}],
        "elements": [
            {"package": "Root", "name": "System A", "stereotype": "System", "ea_type": "Class"}
        ],
        "connectors": [],
    }
    model_data = json.dumps(ir).encode("utf-8")
    body, content_type = build_body({}, [("model", "model.json", model_data, "application/json")])

    request = urllib.request.Request(
        base_url(server) + "/validate",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200
        res = json.loads(response.read().decode("utf-8"))
        assert "ok" in res
        assert "summary" in res
        assert "findings" in res


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_post_build_chat_edit_extend_und_live_viewer(server: webui.WebServer) -> None:
    """Nach dem Bau: Viewer-Vorschau, Chat with Data, NL-Weiterbau und Prosa-Extend."""
    # Startseite bietet die neuen Bereiche und erlaubt same-origin iframe fuer den Viewer.
    status, body, headers = get(base_url(server) + "/")
    assert status == 200
    page = body.decode("utf-8")
    assert "Chat with Data" in page
    assert "Architektur weiterbauen" in page
    assert 'id="viewer-frame"' in page
    assert "frame-src 'self'" in headers["Content-Security-Policy"]

    # 1. Modell bauen
    status, payload = post_build(
        server,
        {"mdg_source": "beispiel", "backend": "datei", "package": "Architektur", "text": TEXT},
    )
    assert status == 202, payload
    state = wait_for(server, payload)
    assert state["state"] == "done", state["error"]
    for key in ("viewer", "validate", "qs", "handbuch", "chat", "edit", "extend"):
        assert key in state["links"], f"Link {key!r} fehlt"
    assert state["model_info"]["elements"]

    # Viewer erlaubt Einbettung im selben Origin
    v_status, _, v_headers = get(base_url(server) + state["links"]["viewer"])
    assert v_status == 200
    assert "frame-ancestors 'self'" in v_headers["Content-Security-Policy"]

    # 2. Chat with Data (offline ohne KI -> strukturierter Auszug + Quellen)
    c_status, chat = _post_json(
        base_url(server) + state["links"]["chat"],
        {"question": "Welche Elemente enthaelt das Modell?", "use_ki": False},
    )
    assert c_status == 200, chat
    assert chat["ok"] is True
    assert chat["model"] == "ohne KI"
    assert "Faehigkeit B" in chat["answer"]
    assert chat["sources"]

    # 3. NL-Edit: neues Paket + Element + Beziehung vorschlagen & anwenden
    inst = (
        'Lege Paket "Architektur/Erweiterung" an und '
        'erstelle Element "Wetterdienst" als ServiceSpecification in Paket "Architektur/Erweiterung" und '
        'verbinde "Faehigkeit B" mit "Wetterdienst" ueber Exhibits.'
    )
    p_status, prop = _post_json(
        base_url(server) + state["links"]["edit"],
        {"action": "propose", "instruction": inst, "use_ki": False},
    )
    assert p_status == 200, prop
    assert [op["op"] for op in prop["ops"]] == ["add_package", "add_element", "add_connector"]

    a_status, applied = _post_json(
        base_url(server) + state["links"]["edit"],
        {"action": "apply", "ops": prop["ops"]},
    )
    assert a_status == 200, applied
    assert applied["ok"] is True
    assert applied["applied"] == 3
    assert applied["job"]["revision"] == state["revision"] + 1
    assert any("Wetterdienst" in el for el in applied["job"]["model_info"]["elements"])

    # Viewer wurde invalidiert und enthaelt das neue Element sofort
    v2_status, v2_body, _ = get(base_url(server) + state["links"]["viewer"])
    assert v2_status == 200
    assert "Wetterdienst" in v2_body.decode("utf-8")

    # 4. Weiterbau mit zusaetzlicher Prosa ueber --modell (offline Datei-Backend)
    e_status, ext = _post_json(
        base_url(server) + state["links"]["extend"],
        {"text": "Ergaenzende Beschreibung fuer den Dienst C.", "backend": "datei"},
    )
    assert e_status == 200, ext
    assert ext["ok"] is True
    assert ext["job"]["revision"] == applied["job"]["revision"] + 1
    assert any("Wetterdienst" in el for el in ext["job"]["model_info"]["elements"])


def test_webui_defaults_und_context_tokens(tmp_path: Path) -> None:
    """WebUI bricht mehrstufige Laeufe nicht nach 120 s ab und reicht --kontext-tokens durch."""
    assert webui.DEFAULT_MAX_SECONDS >= 1800.0
    assert webui.DEFAULT_HTTP_TIMEOUT == 120.0
    parts = {
        "mdg_source": [webui.UploadPart("mdg_source", None, "", b"beispiel")],
        "backend": [webui.UploadPart("backend", None, "", b"datei")],
        "text": [webui.UploadPart("text", None, "", TEXT.encode("utf-8"))],
        "context_tokens": [webui.UploadPart("context_tokens", None, "", b"8192")],
    }
    prepared = webui.prepare_request(parts, tmp_path, EXAMPLE)
    assert prepared.context_tokens == 8192
    cmd = webui.build_command(prepared, tmp_path, 1800.0)
    assert "--kontext-tokens" in cmd
    assert cmd[cmd.index("--kontext-tokens") + 1] == "8192"
    # HTTP-Timeout je Charge bleibt auf 120 s gedeckelt, auch bei 1800 s Gesamtlimit.
    assert float(cmd[cmd.index("--timeout") + 1]) == 120.0

