#!/usr/bin/env python3
"""Prüft den Auslieferungsgraphen: jeder Knoten existiert und wird wirklich gelesen.

    python3 scripts/verify_graph.py [--json bericht.json] [--md bericht.md]

Das Repo hat eine Quelle (`packages/rules`) und mehrere Auslieferungen. Die
`package.json`-Dateien beschreiben die Absicht; der native GitHub-Graph ist
hier nicht aktiv. Dieses Skript belegt, dass die Absicht im Arbeitsbaum gilt:

1. Jede Zelle hat eine `package.json` mit Namen und Version.
2. Jede deklarierte Abhängigkeit zeigt auf eine Zelle, die es gibt.
3. Die Wissensbasis-Symlinks der Apps zeigen auf `knowledge/` (keine Kopie).
4. Jedes erwartete Auslieferungsartefakt existiert und hat eine Größe.
5. Jedes Artefakt hat einen Eintrag in `dist/SHA256SUMS`, wenn `dist/` existiert.

Exit 0 = alles verbunden, Exit 1 = mindestens ein Befund.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

#: Zellen, die im Auslieferungsgraphen als Knoten erscheinen.
ZELLEN = {
    "packages/rules": "@mitchel85/eam-rules",
    "packages/core": "@mitchel85/eam-core",
    "vendor": "@mitchel85/eam-vendor",
    "apps/html-suite": "eam-ai-suite",
    "apps/html-analyzer": "eam-qea-analyzer",
    "apps/html-editor": "eam-suite",
    "apps/mdg-web": "eam-mdg-web",
    "apps/mcp": "eam-mcp",
    "apps/admbw-extractor": "eam-admbw-extractor",
    "apps/admbw-batch": "eam-admbw-batch",
    "apps/admbw-script-maker": "eam-admbw-script-maker",
    "apps/cli": "eam-ai-cli",
}

#: Erwartete Auslieferung: Datei -> Zelle, die sie erzeugt.
ARTEFAKTE = {
    "apps/html-suite/dist/EAM-AI-Suite.html": "apps/html-suite",
    "apps/html-suite/dist/EAM-AI-Suite.aspx": "apps/html-suite",
    "apps/html-analyzer/dist/EAM-QEA-Analyzer.html": "apps/html-analyzer",
    "apps/html-analyzer/dist/EAM-QEA-Analyzer.aspx": "apps/html-analyzer",
    "apps/html-editor/dist/EAM-Suite.html": "apps/html-editor",
    "apps/html-editor/dist/EAM-Suite.aspx": "apps/html-editor",
    "apps/mdg-web/dist/EAM-MDG-Parser.html": "apps/mdg-web",
}

#: Apps, die die Wissensbasis über Symlinks lesen müssen (keine Kopien).
WISSEN_APPS = ("apps/admbw-extractor", "apps/admbw-batch", "apps/admbw-script-maker")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pruefe() -> dict:
    befunde: list[str] = []
    knoten: list[dict] = []
    namen: dict[str, str] = {}

    for rel, erwartet in ZELLEN.items():
        datei = ROOT / rel / "package.json"
        if not datei.is_file():
            befunde.append(f"keine package.json: {rel}")
            continue
        try:
            daten = json.loads(datei.read_text(encoding="utf-8"))
        except json.JSONDecodeError as fehler:
            befunde.append(f"package.json nicht lesbar: {rel} ({fehler})")
            continue
        if daten.get("name") != erwartet:
            befunde.append(f"Name abweichend: {rel} -> {daten.get('name')} statt {erwartet}")
        if not daten.get("version"):
            befunde.append(f"keine Version: {rel}")
        namen[daten.get("name", rel)] = rel
        knoten.append(
            {
                "path": rel,
                "name": daten.get("name"),
                "version": daten.get("version"),
                "dependencies": daten.get("dependencies", {}),
                "devDependencies": daten.get("devDependencies", {}),
            }
        )

    for k in knoten:
        for feld in ("dependencies", "devDependencies"):
            for abhaengig in k[feld]:
                if abhaengig not in namen:
                    befunde.append(f"{feld}-Abhängigkeit ohne Zelle: {k['path']} -> {abhaengig}")

    # Vendor: kanonische Quelle und lokale Kopien müssen byte-gleich sein.
    from sync_vendor import ZUORDNUNG, unterschiede  # noqa: PLC0415

    for app in sorted(ZUORDNUNG):
        befunde.extend(f"Vendor: {b}" for b in unterschiede(app))

    # Wissensbasis: Symlinks, keine Kopien
    wissensbasis = {p.name for p in (ROOT / "knowledge").glob("*") if p.is_file()}
    for rel in WISSEN_APPS:
        ordner = ROOT / rel
        for datei in sorted(ordner.iterdir()):
            if datei.name not in wissensbasis:
                continue  # eigene Dateien der Zelle (README, Prompt, package.json)
            if not datei.is_symlink():
                befunde.append(f"Kopie statt Symlink: {datei.relative_to(ROOT)}")
                continue
            ziel = (datei.parent / datei.readlink()).resolve()
            if ziel.parent.name != "knowledge":
                befunde.append(f"Symlink zeigt nicht in die Wissensbasis: {datei.relative_to(ROOT)}")

    # Auslieferungen
    artefakte: list[dict] = []
    for rel, zelle in ARTEFAKTE.items():
        datei = ROOT / rel
        if not datei.is_file():
            befunde.append(f"Artefakt fehlt: {rel} (erzeugt von {zelle})")
            continue
        artefakte.append({"path": rel, "cell": zelle, "bytes": datei.stat().st_size, "sha256": sha256(datei)})

    sums = ROOT / "dist" / "SHA256SUMS"
    if sums.is_file():
        text = sums.read_text(encoding="utf-8")
        for a in artefakte:
            if Path(a["path"]).name not in text:
                befunde.append(f"nicht in dist/SHA256SUMS: {Path(a['path']).name}")

    return {"knoten": knoten, "artefakte": artefakte, "befunde": befunde, "ok": not befunde}


def als_markdown(bericht: dict) -> str:
    zeilen = ["# Auslieferungsgraph", ""]
    zeilen.append(f"Stand: {len(bericht['knoten'])} Zellen, {len(bericht['artefakte'])} Artefakte, "
                  f"{len(bericht['befunde'])} Befund(e).")
    zeilen += ["", "| Zelle | Name | Version | abhängig von |", "|---|---|---|---|"]
    for k in bericht["knoten"]:
        deps = [*k["dependencies"], *k.get("devDependencies", {})]
        deps_text = ", ".join(f"`{d}`" for d in deps) or "—"
        zeilen.append(f"| `{k['path']}` | {k['name']} | {k['version']} | {deps_text} |")
    zeilen += ["", "| Artefakt | Bytes | SHA-256 |", "|---|---|---|"]
    for a in bericht["artefakte"]:
        zeilen.append(f"| `{a['path']}` | {a['bytes']} | `{a['sha256'][:16]}…` |")
    if bericht["befunde"]:
        zeilen += ["", "## Befunde", ""] + [f"- {b}" for b in bericht["befunde"]]
    else:
        zeilen += ["", "Kein Befund: jede Zelle vorhanden, jede Kante aufgelöst, jede Auslieferung gebaut."]
    return "\n".join(zeilen) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Auslieferungsgraph prüfen.")
    ap.add_argument("--json", help="Bericht als JSON schreiben")
    ap.add_argument("--md", help="Bericht als Markdown schreiben")
    args = ap.parse_args()
    bericht = pruefe()
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(bericht, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(als_markdown(bericht), encoding="utf-8")
    for b in bericht["befunde"]:
        print(f"BEFUND: {b}")
    print(f"{len(bericht['knoten'])} Zellen, {len(bericht['artefakte'])} Artefakte, "
          f"{len(bericht['befunde'])} Befund(e)")
    return 0 if bericht["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
