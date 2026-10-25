#!/usr/bin/env python3
"""Deterministische Prüfungen für EAM-AI-ADMBw-Batch (ohne LLM).

Prüft ohne LLM-Aufruf:
 1. KB-Statistiken (Stereotypes/Topology/Viewpoints/Connectors) gegen die dokumentierten Zahlen
 2. SHA-256-Hashes der vier MDG-KB-Dateien (Stereotypes, Topology, Viewpoints, TagTypes)
 3. Schema im system_prompt.md (erstes ```json-Block) == examples/batch-schema.json
 4. examples/output-example.json gegen das Schema (jsonschema, Draft 2020-12): 0 Fehler
 5. metadata-Zähler == Array-Längen, IDs eindeutig, Referenzen gültig
 6. Jede Kante gegen die Topologie-KB (client = Quelle, supplier = Ziel, exakt oder konkreter Subtyp, kein 🔒)
 7. Node-Stereotype nutzbar (nicht 🔒/ToolboxPage), Metaklasse == AppliesTo, labels enthalten Stereotype

Exit-Code 0 = alle Checks PASS, 1 = mindestens ein FAIL.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))


def parse_stereotypes(text):
    """Return (rows, header_note_lines). rows: list of (name, metatype, vererbung, appliesto, desc)."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 6 or cells[1] == "Stereotype" or not cells[1]:
            continue
        rows.append((cells[1], cells[2], cells[3], cells[4], cells[5] if len(cells) > 5 else ""))
    return rows


def parse_topology(text):
    """Return list of (name, client, supplier, roles)."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 5 or cells[1] in ("", "Stereotype"):
            continue
        rows.append((cells[1], cells[2], cells[3], cells[4] if len(cells) > 4 else ""))
    return rows


def snake_upper(camel):
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", camel)
    return s.upper()


def main():
    # ---------- 1. KB laden ----------
    st_text = (ROOT / "ADMBw-Knowledge-Stereotypes.md").read_text(encoding="utf-8")
    tp_text = (ROOT / "ADMBw-Knowledge-Topology.md").read_text(encoding="utf-8")
    vp_text = (ROOT / "ADMBw-Knowledge-Viewpoints.md").read_text(encoding="utf-8")
    tt_text = (ROOT / "ADMBw-Knowledge-TagTypes.md").read_text(encoding="utf-8")
    co_text = (ROOT / "ADMBw-Knowledge-Connectors.md").read_text(encoding="utf-8")

    st = parse_stereotypes(st_text)
    toolbox = [r for r in st if r[3] == "ToolboxPage"]
    no_appl = [r for r in st if r[3] == ""]
    abstract = [r for r in st if "🔒" in r[4]]
    junk = [r for r in st if r[0] == "L2-Operational Constraints"]
    usable = [r for r in st if r[3] not in ("", "ToolboxPage")]
    catalog = [r for r in st if r[3] != "ToolboxPage" and r[0] != "L2-Operational Constraints"]

    check("Stereotypes: 318 Tabellenzeilen", len(st) == 318, f"ist {len(st)}")
    check("Stereotypes: 0 ToolboxPage-Einträge", len(toolbox) == 0, f"ist {len(toolbox)}")
    check("Stereotypes: 44 abstrakte Stereotype (🔒)", len(abstract) == 44, f"ist {len(abstract)}")
    check("Stereotypes: 0 Nicht-Stereotype/Artefakte", len(junk) == 0, f"ist {len(junk)}")
    check("Stereotypes: 293 nutzbare", len(usable) == 293, f"ist {len(usable)}")
    check("Stereotypes: 318 Katalog (ohne ToolboxPage/Artefakt)", len(catalog) == 318, f"ist {len(catalog)}")
    check("Stereotypes: Header nennt 318 und 44 abstrakt", "318 Stereotype" in st_text and "44 abstrakt" in st_text)

    # ---------- 1b. Maschinenlesbarer Katalog (Subtyp-Auflösung) ----------
    cat_path = ROOT / "ADMBw-Stereotypes.json"
    alias_path = ROOT / "ADMBw-Aliases.json"
    check("JSON: Stereotypes-Datei vorhanden", cat_path.is_file())
    check("JSON: Aliases-Datei vorhanden", alias_path.is_file())
    desc = {}
    if cat_path.is_file():
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        cat_by = {s["name"]: s for s in cat["stereotypes"]}
        check("JSON: 318 Einträge", len(cat_by) == 318, f"ist {len(cat_by)}")
        check("JSON: 44 abstrakt", sum(1 for s in cat_by.values() if s["abstract"]) == 44,
              f"ist {sum(1 for s in cat_by.values() if s['abstract'])}")
        desc = {n: set(s.get("concreteDescendants", [])) for n, s in cat_by.items()}
        check("JSON: CapabilityConfiguration ist Subtyp von ResourcePerformer",
              "CapabilityConfiguration" in desc.get("ResourcePerformer", set()))
        check("JSON: BWRequirement → Functional/NonfunctionalRequirement",
              {"FunctionalRequirement", "NonfunctionalRequirement"}.issubset(desc.get("BWRequirement", set())))
    if alias_path.is_file():
        al = json.loads(alias_path.read_text(encoding="utf-8")).get("aliases", {})
        check("Aliases: beide Schreibvarianten abgebildet",
              al.get("PropertySetGeneralisation") == "PropertySetGeneralization" and
              al.get("ServiceSpecificationGeneralization") == "ServiceGeneralization")

    tp = parse_topology(tp_text)
    complete = [r for r in tp if r[1] and r[2]]
    roles_only = [r for r in tp if not (r[1] and r[2])]
    check("Topology: 203 Zeilen", len(tp) == 203, f"ist {len(tp)}")
    check("Topology: 133 Regeln mit beiden Enden", len(complete) == 133, f"ist {len(complete)}")
    check("Topology: 70 reine Rollen-Zeilen", len(roles_only) == 70, f"ist {len(roles_only)}")
    check("Topology: Lesart 'Quelle = client/source/end[0]/informationSource'",
          "client, source, end[0].role oder informationSource" in tp_text)

    vp_headings = [l for l in vp_text.splitlines() if l.startswith("## ")]
    check("Viewpoints: 52 Überschriften", len(vp_headings) == 52, f"ist {len(vp_headings)}")
    check("Viewpoints: 'Business Process'-Artefakt entfernt",
          not any("Business Process" in h for h in vp_headings))

    tt_rows = [l for l in tt_text.splitlines() if l.startswith("|")][2:]
    check("TagTypes: 27 Property-Typen", len(tt_rows) == 27, f"ist {len(tt_rows)}")
    check("TagTypes: Header nennt 27 Property-Typen", "27 Property-Typen" in tt_text)

    check("Connectors: Dependency (100)", "**Dependency** (100)" in co_text)
    check("Connectors: Class (68)", "**Class** (68)" in co_text)
    check("Connectors: Activity (6)", "**Activity** (6)" in co_text)
    check("Connectors: Connector (3)", "**Connector** (3)" in co_text)
    check("Connectors: 52 Viewpoints", "52 Viewpoints" in co_text)

    # ---------- 2. Hashes ----------
    hashes = {}
    for f in ["ADMBw-Knowledge-Stereotypes.md", "ADMBw-Knowledge-Topology.md",
              "ADMBw-Knowledge-Viewpoints.md", "ADMBw-Knowledge-TagTypes.md"]:
        data = (ROOT / f).read_bytes()
        hashes[f] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    check("Hashes: vier MDG-KB-Dateien berechnet", len(hashes) == 4)

    # ---------- 3. Schema: Prompt == Datei ----------
    prompt = (ROOT / "system_prompt.md").read_text(encoding="utf-8")
    m = re.search(r"```json\s*\n(.*?)\n```", prompt, re.DOTALL)
    check("Schema: erstes ```json-Block im Prompt gefunden", m is not None)
    schema_prompt = json.loads(m.group(1)) if m else None
    schema_file = json.loads((ROOT / "examples" / "batch-schema.json").read_text(encoding="utf-8"))
    check("Schema: Prompt-Block == examples/batch-schema.json", schema_prompt == schema_file)

    # ---------- 4. Beispiel gegen Schema ----------
    example = json.loads((ROOT / "examples" / "output-example.json").read_text(encoding="utf-8"))
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        sys.exit("jsonschema nicht installiert: pip install jsonschema")
    errors = [e.message for e in Draft202012Validator(schema_file).iter_errors(example)]
    check("Beispiel: 0 jsonschema-Fehler", len(errors) == 0, "; ".join(errors))

    # ---------- 5. Metadaten/Zähler/Referenzen ----------
    nodes, edges = example.get("nodes", []), example.get("edges", [])
    meta = example.get("metadata", {})
    check("metadata.node_count == len(nodes)", meta.get("node_count") == len(nodes),
          f"{meta.get('node_count')} != {len(nodes)}")
    check("metadata.edge_count == len(edges)", meta.get("edge_count") == len(edges),
          f"{meta.get('edge_count')} != {len(edges)}")
    node_ids = [n["id"] for n in nodes]
    check("Node-IDs eindeutig", len(node_ids) == len(set(node_ids)))
    check("Edge-IDs eindeutig", len([e["id"] for e in edges]) == len({e["id"] for e in edges}))
    check("Alle source_id/target_id referenzieren Nodes",
          all(e["source_id"] in node_ids and e["target_id"] in node_ids for e in edges))
    check("metadata.generator korrekt", meta.get("generator") == "ADMBw-Batch-Generator v2.1")
    check("metadata.standard korrekt", meta.get("standard") == "ADMBw v2026.05")

    # ---------- 6. Nodes gegen Stereotype-KB ----------
    st_by_name = {}
    for r in st:
        st_by_name.setdefault(r[0], []).append(r)
    abstract_names = {r[0] for r in abstract}
    node_ok = True
    node_detail = []
    for n in nodes:
        rows = st_by_name.get(n["stereotype"], [])
        good = [r for r in rows if r[3] not in ("", "ToolboxPage") and r[3] == n["metaclass"]]
        if not good or n["stereotype"] in abstract_names or n["stereotype"] not in n["labels"]:
            node_ok = False
            node_detail.append(f"{n['id']}: {n['stereotype']}/{n['metaclass']} nicht KB-konform")
    check("Beispiel: alle Nodes KB-konform (nutzbar, AppliesTo==metaclass, label)", node_ok,
          "; ".join(node_detail))

    # ---------- 7. Edges gegen Topologie-KB ----------
    tp_by_name = {r[0]: r for r in tp}
    edge_pass = 0
    edge_fail = []
    for e in edges:
        rule = tp_by_name.get(e["connector"])
        if rule is None or not (rule[1] and rule[2]):
            edge_fail.append(f"{e['id']}: Connector {e['connector']} ohne vollständige Regel")
            continue
        src = next(n for n in nodes if n["id"] == e["source_id"])
        tgt = next(n for n in nodes if n["id"] == e["target_id"])
        src_allowed = [x.strip() for x in rule[1].split(",") if x.strip()]
        tgt_allowed = [x.strip() for x in rule[2].split(",") if x.strip()]
        src_closure = set(src_allowed) | {d for a in src_allowed for d in desc.get(a, set())}
        tgt_closure = set(tgt_allowed) | {d for a in tgt_allowed for d in desc.get(a, set())}
        if src["stereotype"] not in src_closure or tgt["stereotype"] not in tgt_closure:
            edge_fail.append(
                f"{e['id']}: {src['stereotype']}→{e['connector']}→{tgt['stereotype']} "
                f"vs. Regel {rule[1]}→{rule[0]}→{rule[2]}")
            continue
        if e["connector"] in abstract_names:
            edge_fail.append(f"{e['id']}: Connector {e['connector']} ist abstrakt (🔒)")
            continue
        crows = [r for r in st_by_name.get(e["connector"], []) if r[3] == e["metaclass"]]
        if not crows:
            edge_fail.append(f"{e['id']}: Metaklasse {e['metaclass']} passt nicht zu {e['connector']}")
            continue
        if "type" in e and e["type"]:
            expected = snake_upper(e["connector"])
            if e["type"] != expected:
                edge_fail.append(f"{e['id']}: type {e['type']} != {expected}")
                continue
        edge_pass += 1
    check(f"Beispiel: alle {len(edges)} Kanten Topologie-PASS (exakt oder Subtyp)", edge_pass == len(edges),
          "; ".join(edge_fail))

    # ---------- Ergebnis schreiben ----------
    report = {
        "kb": {
            "stereotypes": {"rows": len(st), "toolbox": len(toolbox), "abstract": len(abstract),
                            "usable": len(usable), "catalog": len(catalog), "junk": len(junk)},
            "topology": {"rows": len(tp), "complete_rules": len(complete), "roles_only": len(roles_only)},
            "viewpoints": len(vp_headings),
            "hashes": hashes,
        },
        "schema": {"prompt_matches_file": schema_prompt == schema_file,
                   "example_errors": errors},
        "example": {"nodes": len(nodes), "edges": len(edges), "edges_kb_pass": edge_pass,
                    "metadata_node_count": meta.get("node_count"),
                    "metadata_edge_count": meta.get("edge_count")},
        "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in results],
        "all_pass": all(o for _, o, _ in results),
    }
    out = ROOT / "checks" / "deterministic-checks.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nReport: {out}")
    print(f"Gesamt: {sum(1 for _, o, _ in results if o)}/{len(results)} PASS")
    sys.exit(0 if report["all_pass"] else 1)


if __name__ == "__main__":
    main()
