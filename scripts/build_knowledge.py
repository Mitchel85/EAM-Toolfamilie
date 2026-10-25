#!/usr/bin/env python3
"""Erzeugt die Wissensbasis aus der MDG — ueber den EINEN MDG-Leser.

Drei Modi:

  python3 scripts/build_knowledge.py --mdg DATEI         # schreiben
  python3 scripts/build_knowledge.py --mdg DATEI --check # nur pruefen (Exit 1 bei Drift)
  python3 scripts/build_knowledge.py --mdg DATEI --check --check-provenance

Warum es diese Datei gibt
-------------------------
Die Wissensbasis wurde frueher in vier Repositories byte-identisch
herumgetragen und bei jedem MDG-Update viermal nachgezogen. Hier entsteht sie
an genau einer Stelle, aus einer Quelle, mit Provenienz.

Es gibt keinen zweiten XML-Leser: das Regelwerk kommt aus
``packages/rules/mdg_parser.py``, die Dokumente daraus aus
``packages/rules/documents.py``.

Was normalisiert wird
---------------------
Der Aufrufpfad ist kein Inhalt: steht er in einer Datei, wird er vor dem
Vergleich auf den reinen Dateinamen gekuerzt. Alle anderen Dateien werden
byte-genau verglichen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
RULES = ROOT / "packages" / "rules"
PARSER = RULES / "mdg_parser.py"
PROVENANCE = KNOWLEDGE / "PROVENANCE.json"

# Zeile in admbw-meta.md, die den Aufrufpfad statt des Dateinamens enthaelt.
MDG_PATH_LINE = re.compile(r"^(- \*\*MDG-Datei:\*\* `)(.+?)(`\s*)$", re.M)


def _normalize(name: str, text: str) -> str:
    """Entfernt Aufrufartefakte, die nichts ueber den Inhalt aussagen."""
    if name == "admbw-meta.md":
        text = MDG_PATH_LINE.sub(lambda m: m.group(1) + Path(m.group(2)).name + m.group(3), text)
    return text


def build(mdg: Path, out: Path) -> list[Path]:
    """Liest die MDG einmal und schreibt die Dokumente in den Zielordner."""
    if str(RULES) not in sys.path:
        sys.path.insert(0, str(RULES))
    import documents  # noqa: PLC0415 - Suchpfad muss vorher stehen
    import mdg_parser  # noqa: PLC0415

    out.mkdir(parents=True, exist_ok=True)
    rules = mdg_parser.parse_mdg(mdg)
    return documents.schreibe(rules, mdg.name, out)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(mdg: Path) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        generated = build(mdg, Path(tmp))
        for path in generated:
            target = KNOWLEDGE / path.name
            text = _normalize(path.name, path.read_text(encoding="utf-8"))
            target.write_text(text, encoding="utf-8")
            print(f"geschrieben: {path.name}")
    provenance = {
        "mdg": mdg.name,
        "mdg_sha256": sha256(mdg),
        "parser": "packages/rules/mdg_parser.py",
        "parser_sha256": sha256(PARSER),
        "files": {p.name: sha256(p) for p in sorted(KNOWLEDGE.glob("admbw-*"))},
    }
    PROVENANCE.write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"geschrieben: PROVENANCE.json ({len(provenance['files'])} Dateien)")
    return 0


def check(mdg: Path, check_provenance: bool) -> int:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        generated = build(mdg, Path(tmp))
        names = {p.name for p in generated}
        for path in generated:
            target = KNOWLEDGE / path.name
            if not target.is_file():
                problems.append(f"fehlt im Repo: {path.name}")
                continue
            fresh = _normalize(path.name, path.read_text(encoding="utf-8"))
            kept = target.read_text(encoding="utf-8")
            if fresh != kept:
                problems.append(f"weicht ab: {path.name}")
        for target in sorted(KNOWLEDGE.glob("admbw-*")):
            if target.name not in names:
                problems.append(f"nicht mehr erzeugt: {target.name}")

    if check_provenance:
        if not PROVENANCE.is_file():
            problems.append("PROVENANCE.json fehlt")
        else:
            data = json.loads(PROVENANCE.read_text(encoding="utf-8"))
            if data.get("mdg_sha256") != sha256(mdg):
                problems.append("PROVENANCE: MDG-Hash passt nicht zur uebergebenen Datei")
            if data.get("parser_sha256") != sha256(PARSER):
                problems.append("PROVENANCE: Parser wurde geaendert, Wissensbasis nicht neu erzeugt")
            for name, digest in (data.get("files") or {}).items():
                target = KNOWLEDGE / name
                if not target.is_file():
                    problems.append(f"PROVENANCE nennt fehlende Datei: {name}")
                elif sha256(target) != digest:
                    problems.append(f"PROVENANCE-Hash falsch: {name}")

    if problems:
        print("Wissensbasis passt NICHT zur Quelle:")
        for item in problems:
            print("  -", item)
        print("\nAbhilfe: python3 scripts/build_knowledge.py --mdg", mdg)
        return 1
    print(f"Wissensbasis passt zur Quelle ({len(names)} Dateien).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Wissensbasis aus der MDG erzeugen oder pruefen.")
    ap.add_argument("--mdg", required=True, help="Pfad zur MDG-XML")
    ap.add_argument("--check", action="store_true", help="nur pruefen, nichts schreiben")
    ap.add_argument("--check-provenance", action="store_true", help="zusaetzlich PROVENANCE.json pruefen")
    args = ap.parse_args()
    mdg = Path(args.mdg)
    if not mdg.is_file():
        raise SystemExit(f"MDG nicht gefunden: {mdg}")
    return check(mdg, args.check_provenance) if args.check else write(mdg)


if __name__ == "__main__":
    raise SystemExit(main())
