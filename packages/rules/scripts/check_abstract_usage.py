#!/usr/bin/env python3
"""Prüft ein Sparx-EA-Modell (.qea) auf unzulässige abstrakte Stereotype.

Abstrakte Stereotype sind Platzhalter (z. B. ResourcePerformer, UAFElement,
BWRequirement). Die BMVg-Methode verlangt, sie bei der Modellierung durch einen
konkreten Subtyp zu ersetzen — {REQUIREMENT} wird zu FunctionalRequirement oder
NonfunctionalRequirement. Dieses Skript meldet jedes Element und jede Beziehung,
die ein abstraktes Stereotyp trägt.

Aufruf:
    python3 scripts/check_abstract_usage.py modell.qea [--catalog output/admbw-stereotypes.json]

Exit-Codes: 0 = sauber · 1 = Treffer · 2 = Aufruffehler (Datei/Katalog fehlt).
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "output" / "admbw-stereotypes.json"
DEFAULT_ALIASES = ROOT / "output" / "admbw-aliases.json"


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        print(f"FEHLER: {path} nicht lesbar ({e}).", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"FEHLER: {path} ist kein gültiges JSON ({e}).", file=sys.stderr)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description="Abstrakte Stereotype in einem .qea-Modell finden")
    ap.add_argument("qea", help="Pfad zur Sparx-EA-Datei")
    ap.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    ap.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    args = ap.parse_args()

    if not os.path.isfile(args.qea):
        print(f"FEHLER: Datei nicht gefunden: {args.qea}", file=sys.stderr)
        sys.exit(2)

    catalog = load_json(args.catalog)
    aliases = {}
    if os.path.isfile(args.aliases):
        aliases = load_json(args.aliases).get("aliases", {})

    abstract = {s["name"] for s in catalog["stereotypes"] if s.get("abstract")}
    concrete_of = {s["name"]: s.get("concreteDescendants", [])
                   for s in catalog["stereotypes"] if s.get("abstract")}

    def canonical(name):
        return aliases.get(name, name)

    try:
        con = sqlite3.connect(f"file:{args.qea}?mode=ro", uri=True)
        con.text_factory = lambda b: b.decode("utf-8", "replace")
        cur = con.cursor()
        objects = cur.execute(
            "SELECT Object_ID, Name, Stereotype FROM t_object "
            "WHERE Stereotype IS NOT NULL AND Stereotype <> ''"
        ).fetchall()
        connectors = cur.execute(
            "SELECT Connector_ID, Name, Stereotype FROM t_connector "
            "WHERE Stereotype IS NOT NULL AND Stereotype <> ''"
        ).fetchall()
        con.close()
    except sqlite3.DatabaseError as e:
        print(f"FEHLER: {args.qea} ist keine lesbare .qea-Datenbank ({e}).", file=sys.stderr)
        sys.exit(2)

    hits = []
    for oid, name, st in objects:
        s = canonical(st)
        if s in abstract:
            hits.append(("Element", oid, name or "", st))
    for cid, name, st in connectors:
        s = canonical(st)
        if s in abstract:
            hits.append(("Beziehung", cid, name or "", st))

    print(f"Modell: {args.qea}")
    print(f"Katalog: {catalog.get('release', '?')} · {len(abstract)} abstrakte Stereotype")
    print(f"Geprüft: {len(objects)} Elemente, {len(connectors)} Beziehungen")
    print()

    if not hits:
        print("OK — kein Element und keine Beziehung trägt ein abstraktes Stereotyp.")
        return 0

    print(f"{len(hits)} Treffer — abstrakte Stereotype dürfen nicht instanziiert werden:")
    for kind, rid, name, st in hits[:40]:
        print(f"  {kind:10s} #{rid:<7d} «{st}»  {name[:70]}")
        options = concrete_of.get(canonical(st), [])
        if options:
            print(f"             zulässig stattdessen: {', '.join(options[:8])}"
                  + (" …" if len(options) > 8 else ""))
    if len(hits) > 40:
        print(f"  … und {len(hits) - 40} weitere")
    return 1


if __name__ == "__main__":
    sys.exit(main())
