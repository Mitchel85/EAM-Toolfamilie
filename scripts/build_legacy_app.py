#!/usr/bin/env python3
"""Baut eine Altwerkzeug-App und legt die Auslieferung unter `apps/<app>/dist/` ab.

    python3 scripts/build_legacy_app.py apps/html-suite

Die App bringt ihren eigenen Build-Skript und ihre eigenen Quellen mit. Dieses
Skript ist nur die Klammer: es liest `app.json`, führt `buildScript` im
App-Verzeichnis aus, prüft die erwarteten Dateien und kopiert sie unter dem
Auslieferungsnamen nach `dist/`. Kein gemeinsamer UI-Kern, keine Generierung.
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
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def baue(app: Path) -> dict:
    manifest = json.loads((app / "app.json").read_text(encoding="utf-8"))
    build = app / manifest["buildScript"]
    if not build.is_file():
        raise SystemExit(f"Build-Skript fehlt: {build}")
    if shutil.which("node") is None:
        raise SystemExit("node fehlt (wird für node --check der HTML-Blöcke gebraucht)")

    from sync_vendor import schreibe  # noqa: PLC0415

    schreibe(app.relative_to(ROOT).as_posix())
    subprocess.run([sys.executable, str(build)], cwd=app, check=True)

    ziele = []
    for schluessel, ziel_name in (("sourceOutput", manifest["output"]), ("sourceAspx", manifest["aspx"])):
        quelle = app / "dist" / manifest[schluessel]
        if not quelle.is_file():
            raise SystemExit(f"Build-Ausgabe fehlt: {quelle}")
        ziel = app / "dist" / ziel_name
        if quelle.resolve() != ziel.resolve():
            shutil.copyfile(quelle, ziel)
        ziele.append(ziel)

    # Die Alt-Builds legen teilweise Zwischenfassungen (Edit-Edition, index.html,
    # docs-Spiegel) ab. Ausgeliefert wird ausschließlich das Manifest.
    erlaubt = {manifest["output"], manifest["aspx"]}
    for pfad in (app / "dist").iterdir():
        if pfad.name in erlaubt:
            continue
        if pfad.is_dir():
            shutil.rmtree(pfad)
        else:
            pfad.unlink()

    return {
        "app": app.name,
        "product": manifest["productName"],
        "version": manifest["version"],
        "sourceRepo": manifest["sourceRepo"],
        "sourceCommit": manifest["sourceCommit"],
        "files": [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in ziele],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Altwerkzeug bauen und ausliefern.")
    ap.add_argument("app", help="App-Verzeichnis, z. B. apps/html-suite")
    args = ap.parse_args()
    app = (ROOT / args.app).resolve()
    if ROOT not in app.parents:
        raise SystemExit(f"App liegt nicht im Repo: {app}")
    print(json.dumps(baue(app), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
