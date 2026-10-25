"""Prueft die Pipeline-Definitionen: Struktur, CE-Tauglichkeit, Paritaet.

Geprueft werden ``.gitlab-ci.yml`` und ``.github/workflows/ci.yml``:

* Stages in fester Reihenfolge ``lint -> test -> build -> release``,
* je Stage ein Job, Abhaengigkeiten (``needs``) nur rueckwaerts,
* nur Community-Edition-Bausteine: keine Merge-Trains, keine
  Ultimate-Security-Templates, keine SaaS-Includes,
* Cache fuer pip, Job-Artefakte fuer Test- und Build-Ergebnisse,
* Release nur auf ``vX.Y.Z``-Tags,
* kein ``git push``/``git commit`` in irgendeinem Schritt,
* identische Befehlsfolge in beiden Pipelines (Paritaet).

Der Parser ist ``ci.miniyaml`` (nur Standardbibliothek, kein Netz). Jede
Pruefung liefert eine Zeile; Exit 0 nur ohne Befund.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ci import miniyaml

STAGES = ["lint", "test", "build", "release"]
GITLAB = Path(".gitlab-ci.yml")
GITHUB = Path(".github/workflows/ci.yml")
RESERVED_GITLAB = {
    "stages",
    "variables",
    "default",
    "workflow",
    "include",
    "image",
    "services",
    "cache",
    "before_script",
    "after_script",
}
FORBIDDEN_KEYS = {
    "merge_train",
    "merge_trains",
    "sast",
    "dependency_scanning",
    "container_scanning",
    "secret_detection",
    "dast",
    "license_scanning",
    "license_management",
    "code_quality",
    "coverage_fuzzing",
    "api_fuzzing",
    "vulnerability_report",
}
FORBIDDEN_VALUES = ("Security/", "Jobs/SAST", "Jobs/Dependency-Scanning", "Jobs/Secret-Detection", "Jobs/DAST", "Auto-DevOps")
FORBIDDEN_COMMANDS = re.compile(r"\bgit\s+(push|commit|tag)\b")
REQUIRED_ARTIFACTS = {"test": "junit", "build": "dist"}
RELEASE_TAG_HINT = "$CI_COMMIT_TAG"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""

    def render(self) -> str:
        return f"{'ok  ' if self.ok else 'FAIL'} {self.name}: {self.detail}"


def _flatten(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield child, key
            yield from _flatten(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{path}[{index}]")


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _commands(job: dict[str, Any], *keys: str) -> list[str]:
    commands: list[str] = []
    for key in keys:
        for item in _as_list(job.get(key)):
            if isinstance(item, str):
                commands.append(" ".join(item.split()))
            else:
                raise ValueError(f"{key} enthaelt keinen Text: {item!r}")
    return commands


class Validator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.results: list[Result] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append(Result(name, bool(ok), detail))

    # -- GitLab ---------------------------------------------------------
    def check_gitlab(self) -> dict[str, Any] | None:
        path = self.root / GITLAB
        if not path.is_file():
            self.check("gitlab.datei", False, f"{GITLAB} fehlt")
            return None
        try:
            document = miniyaml.load_file(path)
        except (miniyaml.YamlError, OSError) as exc:
            self.check("gitlab.yaml", False, str(exc))
            return None
        self.check("gitlab.yaml", True, "syntaktisch lesbar")
        if not isinstance(document, dict):
            self.check("gitlab.wurzel", False, "Mapping erwartet")
            return None

        unknown = sorted(set(document) - RESERVED_GITLAB - set(self._gitlab_jobs(document)))
        self.check("gitlab.schluessel", not unknown, f"unbekannt: {unknown}" if unknown else "nur bekannte Bloecke")

        stages = document.get("stages")
        self.check("gitlab.stages", stages == STAGES, f"{stages}")

        jobs = self._gitlab_jobs(document)
        self.check("gitlab.jobs", sorted(jobs) == sorted(STAGES), f"{sorted(jobs)}")

        stage_of: dict[str, str] = {}
        for name, job in jobs.items():
            stage = job.get("stage") if isinstance(job, dict) else None
            self.check(f"gitlab.job.{name}.stage", stage in (stages or []), f"{stage!r}")
            if isinstance(stage, str):
                stage_of[name] = stage
        for stage in STAGES:
            members = [name for name, value in stage_of.items() if value == stage]
            self.check(f"gitlab.stage.{stage}.besetzt", bool(members), f"{members}")

        # Abhaengigkeiten nur rueckwaerts, Ziele muessen existieren.
        for name, job in jobs.items():
            for need in _as_list(job.get("needs") if isinstance(job, dict) else None):
                target = need.get("job") if isinstance(need, dict) else need
                self.check(f"gitlab.needs.{name}.{target}", target in stage_of, "Job existiert")
                if target in stage_of and name in stage_of and stages:
                    self.check(
                        f"gitlab.needs.{name}.{target}.richtung",
                        stages.index(stage_of[target]) < stages.index(stage_of[name]),
                        f"{stage_of[target]} -> {stage_of[name]}",
                    )

        self._check_forbidden_keys("gitlab", document)
        include = document.get("include")
        if include is not None:
            for entry in _as_list(include):
                self.check(
                    "gitlab.include",
                    isinstance(entry, dict) and set(entry) == {"local"},
                    f"nur lokale Includes erlaubt, gefunden {entry!r}",
                )
        self._check_no_push(document, "gitlab")

        default = document.get("default") or {}
        variables = document.get("variables") or {}
        image = default.get("image") if isinstance(default, dict) else None
        self.check("gitlab.image", image == "$PYTHON_IMAGE", f"{image!r}")
        version = str((variables or {}).get("PYTHON_IMAGE", ""))
        self.check("gitlab.python", version.startswith("python:3.11"), f"{version!r} (3.11+ noetig)")

        cache_jobs = [name for name, job in jobs.items() if isinstance(job, dict) and job.get("cache")]
        cache_ok = False
        for name in cache_jobs:
            paths = _as_list((jobs[name].get("cache") or {}).get("paths"))
            cache_ok = cache_ok or ".cache/pip" in paths
        self.check("gitlab.cache.pip", cache_ok, f"Jobs mit Cache: {cache_jobs}")

        for stage, needle in REQUIRED_ARTIFACTS.items():
            members = [name for name, value in stage_of.items() if value == stage]
            found = False
            for name in members:
                artifacts = jobs[name].get("artifacts") or {}
                if needle == "junit":
                    found = found or bool(((artifacts.get("reports") or {}).get("junit")))
                else:
                    paths = _as_list(artifacts.get("paths"))
                    found = found or any(str(item).startswith(needle) for item in paths)
            self.check(f"gitlab.artefakte.{stage}", found, f"{needle} in {members}")

        release = [name for name, value in stage_of.items() if value == "release"]
        self.check("gitlab.release.vorhanden", bool(release), f"{release}")
        for name in release:
            rules = _as_list(jobs[name].get("rules"))
            self.check("gitlab.release.rules", bool(rules), f"{name}: {len(rules)} Regel(n)")
            for rule in rules:
                condition = rule.get("if") if isinstance(rule, dict) else None
                self.check(
                    f"gitlab.release.{name}.nur_tag",
                    isinstance(condition, str) and RELEASE_TAG_HINT in condition,
                    f"{condition!r}",
                )
        return document

    def _gitlab_jobs(self, document: dict[str, Any]) -> dict[str, Any]:
        return {
            name: value
            for name, value in document.items()
            if name not in RESERVED_GITLAB and not str(name).startswith(".")
        }

    # -- GitHub ---------------------------------------------------------
    def check_github(self) -> dict[str, Any] | None:
        path = self.root / GITHUB
        if not path.is_file():
            self.check("github.datei", False, f"{GITHUB} fehlt")
            return None
        try:
            document = miniyaml.load_file(path)
        except (miniyaml.YamlError, OSError) as exc:
            self.check("github.yaml", False, str(exc))
            return None
        self.check("github.yaml", True, "syntaktisch lesbar")
        if not isinstance(document, dict):
            self.check("github.wurzel", False, "Mapping erwartet")
            return None

        triggers = document.get("on")
        self.check("github.trigger", isinstance(triggers, dict), f"{type(triggers).__name__}")
        if isinstance(triggers, dict):
            push = triggers.get("push") or {}
            branches = _as_list((push or {}).get("branches"))
            tags = _as_list((push or {}).get("tags"))
            self.check("github.trigger.push", bool(branches) and bool(tags), f"branches={branches} tags={tags}")
            self.check(
                "github.trigger.pr",
                "pull_request" in triggers,
                f"vorhanden: {'pull_request' in triggers}",
            )

        permissions = document.get("permissions") or {}
        self.check(
            "github.permissions",
            isinstance(permissions, dict) and permissions.get("contents") == "write",
            f"{permissions}",
        )

        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            self.check("github.jobs", False, "jobs fehlt")
            return document
        self.check("github.jobs", sorted(jobs) == sorted(STAGES), f"{sorted(jobs)}")

        for stage in STAGES:
            job = jobs.get(stage)
            if not isinstance(job, dict):
                continue
            self.check(f"github.job.{stage}.runs-on", bool(job.get("runs-on")), f"{job.get('runs-on')!r}")
            steps = _as_list(job.get("steps"))
            self.check(f"github.job.{stage}.steps", bool(steps), f"{len(steps)} Schritt(e)")
            uses = [str(step.get("uses", "")) for step in steps if isinstance(step, dict)]
            self.check(f"github.job.{stage}.checkout", any(item.startswith("actions/checkout") for item in uses), "")
            self.check(f"github.job.{stage}.python", any(item.startswith("actions/setup-python") for item in uses), "")
            for step in steps:
                if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/setup-python"):
                    version = str(((step.get("with") or {}).get("python-version")) or "")
                    self.check(f"github.job.{stage}.python-version", version.startswith("3.11"), f"{version!r}")

        chain = {"lint": None, "test": "lint", "build": "test", "release": "build"}
        for stage, expected in chain.items():
            job = jobs.get(stage) or {}
            needs = _as_list(job.get("needs"))
            self.check(f"github.needs.{stage}", (not needs and expected is None) or needs == [expected], f"{needs}")

        self._check_forbidden_keys("github", document)
        self._check_no_push(document, "github")

        release = jobs.get("release") or {}
        condition = str(release.get("if", ""))
        self.check("github.release.if", "refs/tags/v" in condition, f"{condition!r}")

        for stage in ("test", "build"):
            uses = [str(step.get("uses", "")) for step in _as_list((jobs.get(stage) or {}).get("steps")) if isinstance(step, dict)]
            self.check(
                f"github.artefakte.{stage}",
                any(item.startswith("actions/upload-artifact") for item in uses),
                "",
            )
        release_uses = [
            str(step.get("uses", "")) for step in _as_list(release.get("steps")) if isinstance(step, dict)
        ]
        self.check(
            "github.artefakte.release",
            any(item.startswith("actions/download-artifact") for item in release_uses),
            "",
        )
        return document

    # -- gemeinsame Pruefungen -----------------------------------------
    def _check_forbidden_keys(self, prefix: str, document: dict[str, Any]) -> None:
        keys = {str(key) for _, key in _flatten(document)}
        blocked = sorted(keys & FORBIDDEN_KEYS)
        self.check(f"{prefix}.ce", not blocked, f"Premium/Ultimate-Schluessel: {blocked}" if blocked else "nur CE-Bausteine")
        values = [value for value in _strings(document)]
        hits = sorted({marker for marker in FORBIDDEN_VALUES for value in values if marker in value})
        self.check(f"{prefix}.templates", not hits, f"verbotene Vorlagen: {hits}" if hits else "keine Ultimate-Vorlagen")

    def _check_no_push(self, document: dict[str, Any], prefix: str) -> None:
        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            jobs = {
                name: value
                for name, value in document.items()
                if name not in RESERVED_GITLAB and not str(name).startswith(".") and isinstance(value, dict)
            }
        for job_name, job in jobs.items():
            commands = _commands(job, "script", "before_script", "after_script")
            commands += [
                " ".join(str(step.get("run", "")).split())
                for step in _as_list(job.get("steps"))
                if isinstance(step, dict) and step.get("run")
            ]
            for command in commands:
                self.check(
                    f"{prefix}.kein_push.{job_name}",
                    not FORBIDDEN_COMMANDS.search(command),
                    command,
                )


def _parity_commands(document: dict[str, Any], stage: str, *, gitlab: bool) -> list[str]:
    if gitlab:
        job = (document or {}).get(stage) or {}
        return _commands(job, "before_script", "script") if isinstance(job, dict) else []
    job = ((document or {}).get("jobs") or {}).get(stage) or {}
    if not isinstance(job, dict):
        return []
    return [
        " ".join(str(step.get("run", "")).split())
        for step in _as_list(job.get("steps"))
        if isinstance(step, dict) and step.get("run")
    ]


def validate(root: Path) -> tuple[list[Result], dict[str, Any]]:
    validator = Validator(root)
    gitlab = validator.check_gitlab()
    github = validator.check_github()

    if gitlab is not None and github is not None:
        for stage in STAGES:
            left = _parity_commands(gitlab, stage, gitlab=True)
            right = _parity_commands(github, stage, gitlab=False)
            validator.check(f"paritaet.{stage}", left == right, f"gitlab={left} github={right}")
    summary = {
        "stages": STAGES,
        "checks": len(validator.results),
        "findings": [result.render() for result in validator.results if not result.ok],
    }
    return validator.results, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ci.validate_pipeline",
        description="GitLab- und GitHub-Pipeline auf Struktur, CE-Tauglichkeit und Paritaet pruefen.",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--json", type=Path, default=None, help="Ergebnis zusaetzlich als JSON schreiben")
    arguments = parser.parse_args(argv)

    results, summary = validate(arguments.root.resolve())
    for result in results:
        print(result.render())
    if arguments.json is not None:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    findings = sum(1 for result in results if not result.ok)
    if findings:
        print(f"validate_pipeline: {len(results)} Pruefungen, {findings} Befund(e)", file=sys.stderr)
        return 1
    print(f"validate_pipeline: {len(results)} Pruefungen, 0 Befunde")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
