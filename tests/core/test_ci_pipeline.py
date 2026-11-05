"""Tests fuer die Pipeline-Bausteine unter ``ci/``.

Geprueft wird, was die Pipeline verspricht:

* Fixtures kommen aus dem internen Store, werden gegen das Manifest geprueft
  und bei Abweichung laut abgelehnt,
* beide Pipeline-Dateien sind syntaktisch lesbar, haben die Stages
  ``lint/test/build/release``, nutzen nur CE-Bausteine und rufen dieselben
  Befehle auf,
* der Kernlint findet Fremdpakete, Netz und Zeit/Zufall,
* der Testlauf sperrt das Netz (auch in Unterprozessen),
* der Release-Job erzeugt reproduzierbare Berichte und spricht die richtige
  API an (Stub, kein echtes Netz),
* der Referenzbau ist byte-identisch ueber zwei Seeds (nur mit Fixture).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ci import build_reference, lint_core, miniyaml, release, stage_fixtures, validate_pipeline

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
MANIFEST = ROOT / "ci" / "fixtures_manifest.json"
import mdg_source  # noqa: E402

REAL_MDG = mdg_source.path()


# --------------------------------------------------------------------------
# Fixture-Store
# --------------------------------------------------------------------------


def _manifest(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 1, "fixtures": entries}), encoding="utf-8")
    return path


def _kleine_fixture(tmp_path: Path, content: bytes = b"inhalt-1") -> tuple[Path, dict[str, object]]:
    import hashlib

    store = tmp_path / "store"
    store.mkdir()
    source = store / "klein.bin"
    source.write_bytes(content)
    entry = {
        "name": "klein.bin",
        "target": "fixtures/klein.bin",
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }
    return store, entry


def test_manifest_der_internen_fixtures_ist_vollstaendig() -> None:
    fixtures = stage_fixtures.load_manifest(MANIFEST)
    namen = [item.name for item in fixtures]
    assert "Musterarchitektur_MASC.qea" in namen
    # Die MDG ist kein Fixture: sie steht in packages/rules und wird dort
    # über CURRENT gefunden, nicht über den Fixture-Store.
    assert mdg_source.name() not in namen
    for item in fixtures:
        assert item.bytes > 0
        assert len(item.sha256) == 64
        assert not Path(item.target).is_absolute()


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "a.qea", "target": "/abs/a.qea", "sha256": "0" * 64, "bytes": 1},
        {"name": "a.qea", "target": "../a.qea", "sha256": "0" * 64, "bytes": 1},
        {"name": "a.qea", "target": "fixtures/a.qea", "sha256": "zu-kurz", "bytes": 1},
        {"name": "a.qea", "target": "fixtures/a.qea", "sha256": "0" * 64, "bytes": 0},
    ],
)
def test_manifest_lehnt_kaputte_eintraege_ab(tmp_path: Path, entry: dict[str, object]) -> None:
    path = _manifest(tmp_path, [entry])
    with pytest.raises(stage_fixtures.FixtureError):
        stage_fixtures.load_manifest(path)


def test_manifest_ohne_fixtures_ist_ein_fehler(tmp_path: Path) -> None:
    path = _manifest(tmp_path, [])
    with pytest.raises(stage_fixtures.FixtureError, match="leer"):
        stage_fixtures.load_manifest(path)


def test_stage_fixtures_kopiert_und_prueft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    store, entry = _kleine_fixture(tmp_path)
    manifest = _manifest(tmp_path, [entry])
    monkeypatch.setattr(stage_fixtures, "ROOT", tmp_path)

    assert stage_fixtures.main(["--manifest", str(manifest), "--store", str(store)]) == 0
    target = tmp_path / "fixtures" / "klein.bin"
    assert target.read_bytes() == b"inhalt-1"
    assert "bereitgestellt und geprueft" in capsys.readouterr().out


def test_stage_fixtures_meldet_hashabweichung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    store, entry = _kleine_fixture(tmp_path)
    (store / entry["name"]).write_bytes(b"inhalt-X")  # gleiche Laenge, anderer Inhalt
    manifest = _manifest(tmp_path, [entry])
    monkeypatch.setattr(stage_fixtures, "ROOT", tmp_path)

    assert stage_fixtures.main(["--manifest", str(manifest), "--store", str(store)]) == 1
    assert "SHA-256 weicht ab" in capsys.readouterr().err
    assert not (tmp_path / "fixtures" / "klein.bin").exists()


def test_stage_fixtures_meldet_fehlende_datei(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    store, entry = _kleine_fixture(tmp_path)
    (store / entry["name"]).unlink()
    manifest = _manifest(tmp_path, [entry])
    monkeypatch.setattr(stage_fixtures, "ROOT", tmp_path)

    assert stage_fixtures.main(["--manifest", str(manifest), "--store", str(store)]) == 1
    assert "fehlt im Store" in capsys.readouterr().err


def test_stage_fixtures_check_ohne_arbeitskopie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    store, entry = _kleine_fixture(tmp_path)
    manifest = _manifest(tmp_path, [entry])
    monkeypatch.setattr(stage_fixtures, "ROOT", tmp_path)

    assert stage_fixtures.main(["--manifest", str(manifest), "--check"]) == 1
    assert "zuerst" in capsys.readouterr().err


def test_stage_fixtures_ohne_store_ist_laut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    store, entry = _kleine_fixture(tmp_path)
    manifest = _manifest(tmp_path, [entry])
    monkeypatch.setattr(stage_fixtures, "ROOT", tmp_path)
    monkeypatch.delenv("EAM_FIXTURE_STORE", raising=False)

    assert stage_fixtures.main(["--manifest", str(manifest)]) == 1
    assert "Fixture-Store fehlt" in capsys.readouterr().err


# --------------------------------------------------------------------------
# YAML-Teilmenge
# --------------------------------------------------------------------------


def test_miniyaml_liest_beide_pipeline_dateien() -> None:
    gitlab = miniyaml.load_file(ROOT / ".gitlab-ci.yml")
    assert gitlab["stages"] == ["lint", "test", "build", "release"]
    assert gitlab["test"]["needs"] == ["lint"]
    assert gitlab["release"]["needs"] == [{"job": "build", "artifacts": True}]
    assert gitlab["release"]["rules"] == [{"if": "$CI_COMMIT_TAG =~ /^v[0-9]+\\.[0-9]+\\.[0-9]+$/"}]

    github = miniyaml.load_file(ROOT / ".github" / "workflows" / "ci.yml")
    assert github["name"] == "CI"
    assert sorted(github["jobs"]) == ["build", "lint", "release", "test"]
    steps = github["jobs"]["lint"]["steps"]
    assert steps[0]["uses"] == "actions/checkout@v4"


@pytest.mark.parametrize(
    "text, meldung",
    [
        ("a: &anker 1\nb: *anker\n", "Anker"),
        ("a:\n\tb: 1\n", "Tabulator"),
        ("a: |\n  text\n", "Block-Skalare"),
        ("a: 1\na: 2\n", "doppelt"),
        ('a: "offen\n', "Anfuehrungszeichen"),
        ("a: {b: 1}\n", "Fluss-Mappings"),
    ],
)
def test_miniyaml_lehnt_nicht_unterstuetzte_syntax_ab(text: str, meldung: str) -> None:
    with pytest.raises(miniyaml.YamlError, match=meldung):
        miniyaml.loads(text)


def test_miniyaml_liest_sequenz_mit_folgezeilen() -> None:
    document = miniyaml.loads(
        "needs:\n  - job: build\n    artifacts: true\n  - test\n"
    )
    assert document == {"needs": [{"job": "build", "artifacts": True}, "test"]}


# --------------------------------------------------------------------------
# Pipeline-Pruefung
# --------------------------------------------------------------------------


def test_pipeline_pruefung_ist_gruen() -> None:
    results, summary = validate_pipeline.validate(ROOT)
    findings = [result.render() for result in results if not result.ok]
    assert findings == []
    assert summary["findings"] == []
    names = {result.name for result in results}
    assert {"gitlab.stages", "github.jobs", "paritaet.lint", "paritaet.release"} <= names
    assert len(results) > 40


def _kopie_beider_pipelines(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True)
    shutil.copyfile(ROOT / ".gitlab-ci.yml", root / ".gitlab-ci.yml")
    shutil.copyfile(ROOT / ".github" / "workflows" / "ci.yml", root / ".github" / "workflows" / "ci.yml")
    return root


def test_pipeline_pruefung_faengt_merge_train(tmp_path: Path) -> None:
    root = _kopie_beider_pipelines(tmp_path)
    with (root / ".gitlab-ci.yml").open("a", encoding="utf-8") as handle:
        handle.write("\nmerge_train:\n  enabled: true\n")
    results, _ = validate_pipeline.validate(root)
    assert any(not result.ok and "merge_train" in result.detail for result in results)


def test_pipeline_pruefung_faengt_ultimate_template(tmp_path: Path) -> None:
    root = _kopie_beider_pipelines(tmp_path)
    text = (root / ".gitlab-ci.yml").read_text(encoding="utf-8")
    text = text.replace(
        "stages:\n", "include:\n  - template: Security/SAST.gitlab-ci.yml\n\nstages:\n", 1
    )
    (root / ".gitlab-ci.yml").write_text(text, encoding="utf-8")
    results, _ = validate_pipeline.validate(root)
    assert any(not result.ok and ("include" in result.name or "templates" in result.name) for result in results)


def test_pipeline_pruefung_faengt_fehlernde_paritaet(tmp_path: Path) -> None:
    root = _kopie_beider_pipelines(tmp_path)
    path = root / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "run: python -m ci.lint_core", "run: python -m ci.lint_core --streng"
        ),
        encoding="utf-8",
    )
    results, _ = validate_pipeline.validate(root)
    assert any(not result.ok and result.name == "paritaet.lint" for result in results)


def test_pipeline_pruefung_faengt_push_im_skript(tmp_path: Path) -> None:
    root = _kopie_beider_pipelines(tmp_path)
    path = root / ".gitlab-ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    - python -m ci.release\n", "    - python -m ci.release\n    - git push origin main\n"
        ),
        encoding="utf-8",
    )
    results, _ = validate_pipeline.validate(root)
    assert any(not result.ok and "kein_push.release" in result.name for result in results)


# --------------------------------------------------------------------------
# Kernlint
# --------------------------------------------------------------------------


def test_kernlint_ist_gruen() -> None:
    assert lint_core.run(ROOT) == []


def test_kernlint_weboberflaeche_ist_benannte_ausnahme(tmp_path: Path) -> None:
    (tmp_path / "webui.py").write_text(
        "import time\nimport http.server\nimport secrets\n", encoding="utf-8"
    )
    (tmp_path / "ci").mkdir()
    assert lint_core.run(tmp_path) == []


def test_kernlint_weboberflaeche_darf_kern_nicht_importieren(tmp_path: Path) -> None:
    (tmp_path / "webui.py").write_text("import qea_writer\n", encoding="utf-8")
    (tmp_path / "ci").mkdir()
    findings = lint_core.run(tmp_path)
    rules = {(finding.rule, finding.message.split(" -- ")[0]) for finding in findings}
    assert rules == {("kern", "qea_writer")}
    assert "Weboberflaeche" in findings[0].message


def test_kernlint_faengt_fremdpaket_und_zeit(tmp_path: Path) -> None:
    (tmp_path / "modul.py").write_text(
        "import yaml\nimport datetime\n\n\ndef stamp():\n    return datetime.datetime.now()\n",
        encoding="utf-8",
    )
    (tmp_path / "ci").mkdir()
    findings = lint_core.run(tmp_path)
    rules = {(finding.rule, finding.message.split(" -- ")[0]) for finding in findings}
    assert ("fremdpaket", "yaml") in rules
    assert ("determinismus", "datetime") in rules


def test_kernlint_faengt_netz_im_kern(tmp_path: Path) -> None:
    (tmp_path / "modul.py").write_text("import urllib.request\n", encoding="utf-8")
    (tmp_path / "ci").mkdir()
    findings = lint_core.run(tmp_path)
    assert [finding.rule for finding in findings] == ["netz"]


def test_netzsperre_greift_auch_im_unterprozess() -> None:
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "ci"), EAM_NET_GUARD="1")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import socket; socket.create_connection(('192.0.2.1', 9), timeout=0.1)",
        ],
        capture_output=True,
        text=True,
        env=environment,
        cwd=ROOT,
        timeout=30,
    )
    assert completed.returncode != 0
    assert "EAM_NET_GUARD" in completed.stderr


def test_run_tests_setzt_sperre_und_junit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    from ci import run_tests

    captured: dict[str, object] = {}

    class Ergebnis:
        returncode = 0

    def fake_run(command, cwd=None, env=None):  # noqa: ANN001
        captured["command"] = list(command)
        captured["env"] = dict(env or {})
        return Ergebnis()

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    report = tmp_path / "reports" / "junit.xml"
    assert run_tests.main([f"--junitxml={report}"]) == 0
    assert captured["env"]["EAM_NET_GUARD"] == "1"
    assert str(ROOT / "ci") in captured["env"]["PYTHONPATH"].split(os.pathsep)
    assert f"--junitxml={report}" in captured["command"]
    assert "Netz gesperrt" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Release
# --------------------------------------------------------------------------


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "modell.qea").write_bytes(b"SQLite format 3\x00" + b"x" * 32)
    (dist / "findings.json").write_text("[]\n", encoding="utf-8")
    (dist / "quellen.json").write_text('{"quellen": []}\n', encoding="utf-8")
    (dist / "SHA256SUMS").write_text("alte liste\n", encoding="utf-8")
    return dist


def test_release_berichte_sind_reproduzierbar(tmp_path: Path, capsys) -> None:
    dist = _dist(tmp_path)
    first = tmp_path / "release-1"
    second = tmp_path / "release-2"
    for out in (first, second):
        assert release.main(
            ["--provider", "none", "--tag", "v2.1.0", "--commit", "abc1234", "--dist", str(dist), "--out", str(out)]
        ) == 0
    for name in ("release.json", "SHA256SUMS", "notes.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    report = json.loads((first / "release.json").read_text(encoding="utf-8"))
    assert report["tag"] == "v2.1.0"
    assert report["version"] == "2.1.0"
    assert report["commit"] == "abc1234"
    assert [item["path"] for item in report["artifacts"]] == [
        "findings.json",
        "modell.qea",
        "quellen.json",
    ]
    assert "SHA256SUMS aus dem Build wird durch die neue Liste ersetzt" in capsys.readouterr().out


def test_release_lehnt_falschen_tag_ab(tmp_path: Path, capsys) -> None:
    dist = _dist(tmp_path)
    assert release.main(
        ["--provider", "none", "--tag", "2.1.0", "--commit", "abc", "--dist", str(dist), "--out", str(tmp_path / "r")]
    ) == 2
    assert "vMAJOR.MINOR.PATCH" in capsys.readouterr().err


def test_release_lehnt_leeren_ordner_ab(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "leer"
    empty.mkdir()
    assert release.main(
        ["--provider", "none", "--tag", "v1.0.0", "--commit", "abc", "--dist", str(empty), "--out", str(tmp_path / "r")]
    ) == 1
    assert "leer" in capsys.readouterr().err


def test_release_ohne_commit_ist_laut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    dist = _dist(tmp_path)
    for name in ("EAM_RELEASE_COMMIT", "CI_COMMIT_SHA", "GITHUB_SHA"):
        monkeypatch.delenv(name, raising=False)
    assert release.main(["--provider", "none", "--tag", "v1.0.0", "--dist", str(dist), "--out", str(tmp_path / "r")]) == 2
    assert "kein Commit" in capsys.readouterr().err


class _Stub(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    uploads: list[str] = []

    def log_message(self, *args: object) -> None:
        pass

    def _payload(self) -> object:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            return None

    def do_POST(self) -> None:  # noqa: N802
        payload = self._payload()
        type(self).requests.append(
            {
                "path": self.path,
                "job_token": bool(self.headers.get("JOB-TOKEN")),
                "payload": payload,
            }
        )
        if self.path.endswith("/releases"):
            self._send(201, {"tag_name": "v2.1.0", "upload_url": f"http://127.0.0.1:{self.server.server_port}/upload{{?name}}"})
        elif self.path.startswith("/upload"):
            type(self).uploads.append(self.path)
            self._send(201, {"ok": True})
        else:
            self._send(404, {"error": "unbekannt"})

    def _send(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def stub_server():
    _Stub.requests = []
    _Stub.uploads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def test_release_gitlab_nutzt_releases_api(tmp_path: Path, stub_server, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _dist(tmp_path)
    base = f"http://127.0.0.1:{stub_server.server_port}"
    monkeypatch.setenv("CI_API_V4_URL", f"{base}/api/v4")
    monkeypatch.setenv("CI_PROJECT_ID", "42")
    monkeypatch.setenv("CI_PROJECT_URL", "https://git.intern.example/eam/suite")
    monkeypatch.setenv("CI_JOB_TOKEN", "geheim")

    assert release.main(
        ["--provider", "gitlab", "--tag", "v2.1.0", "--commit", "abc1234", "--dist", str(dist), "--out", str(tmp_path / "rel")]
    ) == 0
    assert len(_Stub.requests) == 1
    call = _Stub.requests[0]
    assert call["path"] == "/api/v4/projects/42/releases"
    assert call["job_token"] is True
    payload = call["payload"]
    assert payload["tag_name"] == "v2.1.0"
    links = payload["assets"]["links"]
    assert len(links) == 3
    assert links[0]["url"].startswith("https://git.intern.example/eam/suite/-/jobs/artifacts/v2.1.0/")
    request_file = (tmp_path / "rel" / "request.json")
    assert not request_file.exists()  # nur im Trockenlauf


def test_release_github_laedt_assets_hoch(tmp_path: Path, stub_server, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _dist(tmp_path)
    base = f"http://127.0.0.1:{stub_server.server_port}"
    monkeypatch.setenv("EAM_GITHUB_API", base)
    monkeypatch.setenv("GITHUB_REPOSITORY", "mitch/eam-ai")
    monkeypatch.setenv("GITHUB_TOKEN", "geheim")

    assert release.main(
        ["--provider", "github", "--tag", "v2.1.0", "--commit", "abc1234", "--dist", str(dist), "--out", str(tmp_path / "rel")]
    ) == 0
    assert _Stub.requests[0]["path"] == "/repos/mitch/eam-ai/releases"
    assert len(_Stub.uploads) == 3


def test_release_trockenlauf_schreibt_aufruf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _dist(tmp_path)
    monkeypatch.setenv("CI_API_V4_URL", "https://git.intern.example/api/v4")
    monkeypatch.setenv("CI_PROJECT_ID", "42")
    monkeypatch.setenv("CI_PROJECT_URL", "https://git.intern.example/eam/suite")
    monkeypatch.setenv("CI_JOB_TOKEN", "streng-geheim")
    out = tmp_path / "rel"

    assert release.main(
        ["--provider", "gitlab", "--dry-run", "--tag", "v2.1.0", "--commit", "abc1234", "--dist", str(dist), "--out", str(out)]
    ) == 0
    request = json.loads((out / "request.json").read_text(encoding="utf-8"))
    assert request["method"] == "POST"
    assert request["url"].endswith("/projects/42/releases")
    assert len(request["payload"]["assets"]["links"]) == 3
    assert "streng-geheim" not in (out / "request.json").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Referenzbau (braucht die interne MDG-Fixture)
# --------------------------------------------------------------------------


@pytest.mark.skipif(not REAL_MDG.is_file(), reason="interne MDG-Fixture fehlt (gitignored)")
def test_referenzbau_ist_byte_identisch(tmp_path: Path) -> None:
    out = tmp_path / "reference"
    report = build_reference.build_reference(
        REAL_MDG,
        ROOT / "ci" / "reference" / "prosa.txt",
        ROOT / "ci" / "reference" / "antwort.json",
        out,
        ["1", "4242"],
    )
    assert report["verdict"] == "PASS"
    assert report["seeds"] == ["1", "4242"]
    assert (out / "modell.qea").read_bytes()[:16] == b"SQLite format 3\x00"
    sums = (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(sums) == 4
    assert all(len(line.split("  ")[0]) == 64 for line in sums)
    assert json.loads((out / "findings.json").read_text(encoding="utf-8")) == []
    assert json.loads((out / "quellen.json").read_text(encoding="utf-8"))
