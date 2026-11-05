"""Release-Job: Pruefsummen, Release-Bericht und Anlage der Freigabe.

Der Job laeuft **nur** fuer Tags ``vX.Y.Z`` und legt daraus eine Freigabe an.
Er committet und pusht nichts -- die Pipeline veroeffentlicht ausschliesslich
Artefakte, die im Build-Job entstanden sind.

Ablauf:

1. Tag pruefen (``vMAJOR.MINOR.PATCH``), Commit und Artefaktverzeichnis pruefen.
2. ``SHA256SUMS``, ``release.json`` und ``notes.md`` schreiben -- ohne
   Zeitstempel, damit derselbe Stand dieselben Bytes ergibt.
3. Freigabe anlegen: GitLab (``CI_API_V4_URL``, ``CI_JOB_TOKEN``) oder GitHub
   (``GITHUB_REPOSITORY``, ``GITHUB_TOKEN``). ``--dry-run`` schreibt nur den
   Aufruf nach ``request.json`` und spricht kein Netz.

Fehler sind laut: fehlende Umgebung, leerer Artefaktordner, HTTP-Fehler mit
Status und Antworttext (ohne Token).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")
PROVIDERS = ("none", "gitlab", "github")


class ReleaseError(RuntimeError):
    """Freigabe nicht moeglich -- laut abbrechen."""


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _infer_provider(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("EAM_RELEASE_PROVIDER", "")
    if from_env:
        return from_env
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github"
    if os.environ.get("CI_API_V4_URL"):
        return "gitlab"
    return "none"


def collect(dist: Path) -> list[dict[str, object]]:
    if not dist.is_dir():
        raise ReleaseError(f"Artefaktverzeichnis fehlt: {dist}")
    files = sorted((path for path in dist.rglob("*") if path.is_file()), key=lambda p: p.as_posix())
    if not files:
        raise ReleaseError(f"Artefaktverzeichnis ist leer: {dist} -- ohne Artefakt keine Freigabe")
    artifacts = []
    for path in files:
        if path.name == "SHA256SUMS":
            # Die Pruefsummenliste des Build-Jobs wird durch die des Release-Jobs
            # ersetzt; sie zweimal zu veroeffentlichen waere irrefuehrend.
            print(f"release: {path.name} aus dem Build wird durch die neue Liste ersetzt")
            continue
        digest, size = sha256_file(path)
        artifacts.append(
            {"path": path.relative_to(dist).as_posix(), "sha256": digest, "bytes": size}
        )
    if not artifacts:
        raise ReleaseError(f"Artefaktverzeichnis enthaelt nur Pruefsummen: {dist}")
    return artifacts


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def gitlab_context(tag: str, job_name: str) -> dict[str, str]:
    api = _env("CI_API_V4_URL")
    project = _env("CI_PROJECT_ID")
    project_url = _env("CI_PROJECT_URL")
    token = _env("CI_JOB_TOKEN")
    missing = [
        name
        for name, value in (
            ("CI_API_V4_URL", api),
            ("CI_PROJECT_ID", project),
            ("CI_PROJECT_URL", project_url),
            ("CI_JOB_TOKEN", token),
        )
        if not value
    ]
    if missing:
        raise ReleaseError(
            "GitLab-Freigabe braucht " + ", ".join(missing) + " -- im CI-Lauf gesetzt, lokal nicht"
        )
    return {"api": api.rstrip("/"), "project": project, "project_url": project_url.rstrip("/"), "token": token, "job": job_name}


def github_context() -> dict[str, str]:
    repository = _env("GITHUB_REPOSITORY")
    token = _env("GITHUB_TOKEN")
    api = _env("EAM_GITHUB_API") or "https://api.github.com"
    missing = [name for name, value in (("GITHUB_REPOSITORY", repository), ("GITHUB_TOKEN", token)) if not value]
    if missing:
        raise ReleaseError("GitHub-Freigabe braucht " + ", ".join(missing))
    return {"api": api.rstrip("/"), "repository": repository, "token": token}


def _post(url: str, payload: dict[str, object] | None, headers: dict[str, str], method: str) -> tuple[int, bytes]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        return exc.code, detail.encode("utf-8")
    except OSError as exc:
        raise ReleaseError(f"{method} {url} fehlgeschlagen: {exc}") from exc


def write_reports(tag: str, version: str, commit: str, provider: str, artifacts: list[dict[str, object]], out: Path) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"{item['sha256']}  {item['path']}" for item in artifacts]
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    notes = [f"# EAM AI Suite Python {tag}", "", "Artefakte des Referenzbaus (Modell, Befunde, Belege).", ""]
    notes.append("## Artefakte")
    for item in artifacts:
        notes.append(f"- `{item['path']}` -- {item['bytes']} Bytes, sha256 `{item['sha256']}`")
    notes.extend(
        [
            "",
            "## Pruefsummen",
            "`SHA256SUMS` liegt neben diesem Bericht.",
            "",
            "## Reproduzierbarkeit",
            "Der Build-Job baut das Modell zweimal mit unterschiedlichem PYTHONHASHSEED;",
            "die Bytes sind identisch (siehe `build-report.json`).",
        ]
    )
    (out / "notes.md").write_text("\n".join(notes) + "\n", encoding="utf-8")

    report = {
        "schema": 1,
        "tag": tag,
        "version": version,
        "commit": commit,
        "provider": provider,
        "artifacts": artifacts,
    }
    (out / "release.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def publish_gitlab(
    tag: str,
    notes: str,
    artifacts: list[dict[str, object]],
    context: dict[str, str],
    out: Path,
    dry_run: bool,
) -> str:
    links = [
        {
            "name": str(item["path"]),
            "url": f"{context['project_url']}/-/jobs/artifacts/{urllib.parse.quote(tag, safe='')}"
            f"/raw/dist/reference/{urllib.parse.quote(str(item['path']))}?job={urllib.parse.quote(context['job'])}",
            "link_type": "other",
        }
        for item in artifacts
    ]
    payload = {"tag_name": tag, "name": tag, "description": notes, "assets": {"links": links}}
    url = f"{context['api']}/projects/{context['project']}/releases"
    if dry_run:
        out.mkdir(parents=True, exist_ok=True)
        (out / "request.json").write_text(
            json.dumps(
                {"provider": "gitlab", "method": "POST", "url": url, "payload": payload},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return f"dry-run: POST {url} ({len(links)} Asset-Link(s)) -> {out / 'request.json'}"

    status, body = _post(url, payload, {"JOB-TOKEN": context["token"], "Content-Type": "application/json"}, "POST")
    if status == 409:
        update = f"{url}/{urllib.parse.quote(tag, safe='')}"
        status, body = _post(update, payload, {"JOB-TOKEN": context["token"], "Content-Type": "application/json"}, "PUT")
        if status >= 300:
            raise ReleaseError(f"GitLab-Freigabe aktualisieren fehlgeschlagen ({status}): {body[:600]!r}")
        return f"GitLab-Release {tag} aktualisiert ({status})"
    if status >= 300:
        raise ReleaseError(f"GitLab-Freigabe anlegen fehlgeschlagen ({status}): {body[:600]!r}")
    return f"GitLab-Release {tag} angelegt ({status})"


def publish_github(
    tag: str,
    notes: str,
    artifacts: list[dict[str, object]],
    context: dict[str, str],
    dist: Path,
    out: Path,
    dry_run: bool,
) -> str:
    api = f"{context['api']}/repos/{context['repository']}/releases"
    payload = {"tag_name": tag, "name": tag, "body": notes, "draft": False, "prerelease": False}
    if dry_run:
        out.mkdir(parents=True, exist_ok=True)
        (out / "request.json").write_text(
            json.dumps(
                {"provider": "github", "method": "POST", "url": api, "payload": payload},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return f"dry-run: POST {api} + {len(artifacts)} Asset-Upload(s) -> {out / 'request.json'}"

    headers = {"Authorization": f"Bearer {context['token']}", "Content-Type": "application/json"}
    status, body = _post(api, payload, headers, "POST")
    if status == 422:
        existing = f"{api}/tags/{urllib.parse.quote(tag, safe='')}"
        status, body = _post(existing, None, headers, "GET")
        if status >= 300:
            raise ReleaseError(f"GitHub-Release {tag} nicht gefunden ({status}): {body[:600]!r}")
    elif status >= 300:
        raise ReleaseError(f"GitHub-Release anlegen fehlgeschlagen ({status}): {body[:600]!r}")

    try:
        release = json.loads(body.decode("utf-8"))
        upload_url = re.sub(r"\{[^}]*\}$", "", str(release["upload_url"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise ReleaseError(f"GitHub-Antwort ohne upload_url: {exc}") from exc

    uploaded = 0
    for item in artifacts:
        path = dist / str(item["path"])
        data = path.read_bytes()
        target = f"{upload_url}?name={urllib.parse.quote(str(item['path']))}"
        request = urllib.request.Request(
            target,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {context['token']}",
                "Content-Type": "application/octet-stream",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status >= 300:
                    raise ReleaseError(f"Upload {item['path']} fehlgeschlagen ({response.status})")
                uploaded += 1
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 422 and "already_exists" in detail:
                print(f"release: {item['path']} existiert bereits, unveraendert")
                continue
            raise ReleaseError(f"Upload {item['path']} fehlgeschlagen ({exc.code}): {detail!r}") from exc
        except OSError as exc:
            raise ReleaseError(f"Upload {item['path']} fehlgeschlagen: {exc}") from exc
    return f"GitHub-Release {tag} bereit, {uploaded} Asset(s) hochgeladen"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ci.release",
        description="Freigabe aus den Build-Artefakten vorbereiten und anlegen.",
    )
    parser.add_argument("--provider", choices=PROVIDERS, default=None)
    parser.add_argument("--tag", default=None, help="Freigabe-Tag (Default: EAM_RELEASE_TAG, CI_COMMIT_TAG, GITHUB_REF_NAME)")
    parser.add_argument("--commit", default=None, help="Commit (Default: EAM_RELEASE_COMMIT, CI_COMMIT_SHA, GITHUB_SHA)")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "reference")
    parser.add_argument("--out", type=Path, default=ROOT / "release")
    parser.add_argument("--job-name", default="build", help="GitLab-Jobname fuer die Asset-Links")
    parser.add_argument("--dry-run", action="store_true", help="nur Berichte schreiben, kein Netz")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    provider = _infer_provider(arguments.provider)
    tag = (arguments.tag or _env("EAM_RELEASE_TAG") or _env("CI_COMMIT_TAG") or _env("GITHUB_REF_NAME")).strip()
    commit = (arguments.commit or _env("EAM_RELEASE_COMMIT") or _env("CI_COMMIT_SHA") or _env("GITHUB_SHA")).strip()
    if not tag:
        print("FEHLER: kein Tag -- --tag setzen oder EAM_RELEASE_TAG/CI_COMMIT_TAG/GITHUB_REF_NAME", file=sys.stderr)
        return 2
    match = TAG_RE.match(tag)
    if not match:
        print(f"FEHLER: Tag {tag!r} passt nicht auf vMAJOR.MINOR.PATCH", file=sys.stderr)
        return 2
    if not commit:
        print("FEHLER: kein Commit -- --commit setzen oder EAM_RELEASE_COMMIT/CI_COMMIT_SHA/GITHUB_SHA", file=sys.stderr)
        return 2
    if provider not in PROVIDERS:
        print(f"FEHLER: unbekannter Provider {provider!r}", file=sys.stderr)
        return 2

    try:
        artifacts = collect(arguments.dist.resolve())
        version = ".".join(match.groups())
        report = write_reports(tag, version, commit, provider, artifacts, arguments.out.resolve())
        notes = (arguments.out.resolve() / "notes.md").read_text(encoding="utf-8")
        if provider == "none":
            print(f"release: {len(artifacts)} Artefakt(e), Pruefsummen und Bericht in {arguments.out} (kein Upload)")
        elif provider == "gitlab":
            context = gitlab_context(tag, arguments.job_name)
            print(
                "release: "
                + publish_gitlab(tag, notes, artifacts, context, arguments.out.resolve(), arguments.dry_run)
            )
        else:
            context = github_context()
            print(
                "release: "
                + publish_github(
                    tag, notes, artifacts, context, arguments.dist.resolve(), arguments.out.resolve(), arguments.dry_run
                )
            )
    except ReleaseError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if arguments.out.resolve().joinpath("release.json").is_file():
        print(f"release: {report['version']} / {tag} vorbereitet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
