#!/usr/bin/env python3
"""Baut alle Auslieferungen aus ihren jeweiligen Quellen.

    python3 scripts/build_all.py [--dist dist]

Erzeugt:

  dist/html/EAM-AI-Suite.html/.aspx
  dist/html/EAM-QEA-Analyzer.html/.aspx
  dist/html/EAM-Suite.html/.aspx
  dist/wheel/eam_ai-<version>-py3-none-any.whl
  dist/offline/... (Ordner + .zip + .tar.gz)
  dist/SHA256SUMS

Die drei HTML-Dateien sind eigenständige Altwerkzeuge, keine Varianten eines
gemeinsamen UI-Kerns. Keine Zeitstempel, keine Zufallswerte: gleicher
Quellstand -> gleiche Bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "packages" / "core"
APPS = ["html-suite", "html-analyzer", "html-editor"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Alle EAM-Auslieferungen bauen.")
    ap.add_argument("--dist", default="dist", help="Zielordner (Default: dist)")
    args = ap.parse_args()
    dist = (ROOT / args.dist).resolve()
    if dist.exists():
        # Nur den Build-Ordner leeren, nie das Quellverzeichnis.
        assert dist != ROOT and dist.name == "dist"
        shutil.rmtree(dist)
    (dist / "html").mkdir(parents=True)
    (dist / "wheel").mkdir(parents=True)

    # Erst die Quellen weiterreichen (MDG -> Wissensbasis, vendor -> Apps),
    # dann bauen. Sonst würde build_all auf einem alten Stand aufsetzen.
    run(sys.executable, "scripts/propagate.py", "--write")

    for app in APPS:
        run(sys.executable, "scripts/build_legacy_app.py", f"apps/{app}")
        manifest = json.loads((ROOT / "apps" / app / "app.json").read_text(encoding="utf-8"))
        for name in (manifest["output"], manifest["aspx"]):
            shutil.copyfile(ROOT / "apps" / app / "dist" / name, dist / "html" / name)

    # Der MDG-Parser ist ein eigenstaendiges Werkzeug mit eigenem Build-Skript.
    # Er muss in denselben Auslieferungsordner, sonst findet verify_graph.py
    # die in dist/SHA256SUMS erwartete Datei nicht.
    run(sys.executable, "apps/mdg-web/build.py")
    mdg_manifest = json.loads(
        (ROOT / "apps" / "mdg-web" / "app.json").read_text(encoding="utf-8")
    )
    shutil.copyfile(
        ROOT / "apps" / "mdg-web" / "dist" / mdg_manifest["output"],
        dist / "html" / mdg_manifest["output"],
    )

    sys.path.insert(0, str(CORE))
    import build_backend  # noqa: E402

    wheel = build_backend.build_wheel(str(dist / "wheel"))

    run(sys.executable, "packages/core/tools/build_bundle.py", "--out", str(dist / "offline"))

    sums = []
    for path in sorted(p for p in dist.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        sums.append(f"{sha256(path)}  {path.relative_to(dist)}\n")
    (dist / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    print(f"fertig: {dist}")
    print(f"  HTML:  {len(APPS) + 1} eigenständige Werkzeuge")
    print(f"  Wheel: {wheel}")
    print(f"  Dateien: {len(sums)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
