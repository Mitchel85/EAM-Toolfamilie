"""Referenzbau fuer die Pipeline: zwei Laeufe, gleiche Bytes, ein Bericht.

Der Build-Job der Pipeline soll nicht nur "irgendwas bauen", sondern die harte
Vorgabe des Projekts belegen: **gleicher Input -> gleiche Bytes**. Dieses
Skript baut dasselbe Modell zweimal mit unterschiedlichem ``PYTHONHASHSEED``
und vergleicht die Ausgaben byteweise.

Erzeugt in ``--out``:

* ``modell.qea``        -- das Referenzmodell (aus Lauf 1),
* ``findings.json``     -- Pruefbefunde des Laufs (muss leer sein),
* ``quellen.json``      -- Belege des Laufs (muss gefuellt sein),
* ``build-report.json`` -- Eingaben, Seeds, Hashes, Urteil ``PASS``,
* ``SHA256SUMS``        -- Pruefsummen der Artefakte (sortiert, ohne Zeitstempel).

Kein Zeitstempel, keine Zufallswerte: derselbe Quellstand erzeugt identische
Bytes. Jede Abweichung endet mit Exit 1 und nennt Datei und Hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQLITE_MAGIC = b"SQLite format 3\x00"
ARTIFACTS = ("modell.qea", "findings.json", "quellen.json")


class BuildError(RuntimeError):
    """Referenzbau nicht reproduzierbar oder unvollstaendig."""


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _describe(path: Path) -> dict[str, object]:
    digest, size = sha256_file(path)
    return {"name": path.name, "sha256": digest, "bytes": size}


def _run_once(seed: str, mdg: Path, text: Path, antwort: Path, work: Path) -> dict[str, Path]:
    target = work / f"lauf-{seed}"
    target.mkdir(parents=True)
    qea = target / "modell.qea"
    findings = target / "findings.json"
    quellen = target / "quellen.json"
    environment = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
    command = [
        sys.executable,
        str(ROOT / "eam_ai.py"),
        "build",
        "--mdg",
        str(mdg),
        "--text",
        str(text),
        "--out",
        str(qea),
        "--backend",
        "datei",
        "--antwort",
        str(antwort),
        "--findings",
        str(findings),
        "--quellen",
        str(quellen),
        "-q",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
    if completed.returncode != 0:
        raise BuildError(
            f"Lauf mit PYTHONHASHSEED={seed} brach ab (Exit {completed.returncode}): "
            f"{(completed.stderr or completed.stdout).strip()[:800]}"
        )
    for path in (qea, findings, quellen):
        if not path.is_file():
            raise BuildError(f"Lauf mit PYTHONHASHSEED={seed} hat {path.name} nicht geschrieben")
    with qea.open("rb") as handle:
        if handle.read(len(SQLITE_MAGIC)) != SQLITE_MAGIC:
            raise BuildError("modell.qea ist keine SQLite-Datei (Kopf fehlt)")
    return {"modell.qea": qea, "findings.json": findings, "quellen.json": quellen}


def _check_findings(path: Path) -> list[object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"{path.name} nicht lesbar: {exc}") from exc
    if not isinstance(data, list):
        raise BuildError(f"{path.name}: Liste erwartet, gefunden {type(data).__name__}")
    if data:
        rendered = json.dumps(data, ensure_ascii=False, indent=2)[:800]
        raise BuildError(f"{path.name} enthaelt {len(data)} Befund(e); der Referenzbau muss fehlerfrei sein:\n{rendered}")
    return data


def build_reference(mdg: Path, text: Path, antwort: Path, out: Path, seeds: list[str]) -> dict[str, object]:
    for path in (mdg, text, antwort):
        if not path.is_file():
            raise BuildError(f"Eingabe fehlt: {path}")
    if len(seeds) < 2:
        raise BuildError("mindestens zwei Seeds noetig -- ein Lauf belegt keine Reproduzierbarkeit")

    with tempfile.TemporaryDirectory(prefix="eam-referenz-") as temporary:
        work = Path(temporary)
        runs = [(_run_once(seed, mdg, text, antwort, work), seed) for seed in seeds]

        first, first_seed = runs[0]
        _check_findings(first["findings.json"])
        quellen = json.loads(first["quellen.json"].read_text(encoding="utf-8"))
        if not quellen:
            raise BuildError("quellen.json ist leer -- ohne Beleg ist der Lauf kein Erfolg")

        reference = {name: sha256_file(path)[0] for name, path in first.items()}
        for run, seed in runs[1:]:
            for name, path in run.items():
                digest = sha256_file(path)[0]
                if digest != reference[name]:
                    raise BuildError(
                        f"{name}: Bytes unterscheiden sich zwischen PYTHONHASHSEED={first_seed} "
                        f"und PYTHONHASHSEED={seed} ({reference[name][:16]}... != {digest[:16]}...)"
                    )

        out.mkdir(parents=True, exist_ok=True)
        for name, source in first.items():
            shutil.copyfile(source, out / name)

    report: dict[str, object] = {
        "schema": 1,
        "verdict": "PASS",
        "inputs": {
            "mdg": _describe(mdg),
            "text": _describe(text),
            "antwort": _describe(antwort),
        },
        "seeds": seeds,
        "runs": [
            {"seed": seed, "artifacts": [_describe(out / name) for name in ARTIFACTS]}
            for seed in seeds
        ],
        "artifacts": [_describe(out / name) for name in ARTIFACTS],
    }
    (out / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = []
    for name in (*ARTIFACTS, "build-report.json"):
        digest, size = sha256_file(out / name)
        lines.append(f"{digest}  {name}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def standard_mdg() -> Path:
    """Echte MDG, wenn vorhanden; sonst der synthetische Auszug fuer die CI.

    Der interne Store ist optional: ohne ihn muss die Pipeline trotzdem
    laufen koennen. Der Auszug ist bewusst klein und synthetisch, damit
    nichts Vertrauliches im Repo landet.

    Der Dateiname steht in ``packages/rules/CURRENT``. Bewusst per Hand
    gelesen statt importiert: dieses Skript gehoert zum Kern und bleibt
    standardbibliothek-only (Regel aus ``ci/lint_core.py``).
    """
    regeln = ROOT.parents[0] / "rules"
    aktuell = regeln / "CURRENT"
    if aktuell.is_file():
        for zeile in aktuell.read_text(encoding="utf-8").splitlines():
            name = zeile.split("#", 1)[0].strip()
            if name and (regeln / name).is_file():
                return regeln / name
    return ROOT / "tests" / "fixtures" / "admbw_auszug.xml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ci.build_reference",
        description="Referenzmodell bauen und Byte-Gleichheit ueber zwei Seeds belegen.",
    )
    parser.add_argument(
        "--mdg",
        type=Path,
        default=None,
        help=(
            "Technologie; ohne Angabe die echte MDG aus fixtures/, sonst der "
            "synthetische Auszug tests/fixtures/admbw_auszug.xml"
        ),
    )
    parser.add_argument("--text", type=Path, default=ROOT / "ci" / "reference" / "prosa.txt")
    parser.add_argument("--antwort", type=Path, default=ROOT / "ci" / "reference" / "antwort.json")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "reference")
    parser.add_argument("--seeds", default="1,4242", help="Komma-Liste der PYTHONHASHSEED-Werte")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    seeds = [item.strip() for item in arguments.seeds.split(",") if item.strip()]
    try:
        mdg = (arguments.mdg or standard_mdg()).resolve()
        print(f"build_reference: Technologie {mdg.name}")
        report = build_reference(
            mdg,
            arguments.text.resolve(),
            arguments.antwort.resolve(),
            arguments.out.resolve(),
            seeds,
        )
    except BuildError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    qea = next(item for item in report["artifacts"] if item["name"] == "modell.qea")  # type: ignore[index]
    print(
        f"build_reference: PASS, modell.qea {qea['bytes']} Bytes, sha256 {str(qea['sha256'])[:16]}..., "
        f"identisch ueber {len(seeds)} Laeufe -> {arguments.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
