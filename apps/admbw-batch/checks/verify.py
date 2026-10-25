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


def _baseline_counts():
    """Erwartete Zählwerte aus der MDG-Baseline (packages/rules/schemas).

    Die Zahlen stehen bewusst NICHT im Code. Die MDG wird fortgeschrieben:
    Stereotype, Topologie-Regeln, Viewpoints und Tag-Typen kommen hinzu oder
    fallen weg. Eine eingetippte Zahl macht daraus entweder einen falschen
    Fehlalarm oder — schlimmer — eine Prüfung, die grün bleibt, obwohl der
    Parser kaputt ist.

    Quelle ist die Baseline des Release, das ``packages/rules/CURRENT`` nennt.
    Fehlt sie, wird der Wert nur gemeldet (INFO), nicht geprüft.
    """
    for wurzel in Path(__file__).resolve().parents:
        regeln = wurzel / "packages" / "rules"
        if (regeln / "CURRENT").is_file():
            if str(regeln) not in sys.path:
                sys.path.insert(0, str(regeln))
            import mdg_source  # noqa: PLC0415

            return mdg_source.counts()
    return {}


ERWARTET = _baseline_counts()


def check_zahl(name, wert, schluessel):
    """Prüft eine Zahl gegen die Baseline; ohne Baseline wird sie nur gemeldet."""
    erwartung = ERWARTET.get(schluessel)
    if erwartung is None:
        print(f"INFO  {name}: {wert} — keine Baseline zu '{schluessel}', nicht geprüft")
        results.append((f"{name} (ohne Baseline nur gemeldet)", True, ""))
        return
    check(f"{name}: {erwartung}", wert == erwartung, f"ist {wert}")


def check_metatyp_tabelle(text):
    """Prüft die Metatyp-Tabellen der Konnektor-KB in sich selbst.

    Die Zahl in der Kopfzelle, die Spalte ``Anzahl`` und die tatsächlich
    genannten Stereotype (inklusive ``+N weitere``) müssen zusammenpassen.
    Das ist unabhängig von jedem MDG-Stand und deckt abgeschnittene Listen auf.
    """
    zeilen = [z for z in text.splitlines() if z.startswith("| **")]
    fehler = []
    for zeile in zeilen:
        zellen = [c.strip() for c in zeile.split("|")[1:-1]]
        if len(zellen) < 3:
            continue
        kopf = re.match(r"\*\*(.+?)\*\*\s*\((\d+)\)", zellen[0])
        if not kopf:
            continue
        name, klammer = kopf.group(1), int(kopf.group(2))
        try:
            anzahl = int(zellen[1])
        except ValueError:
            fehler.append(f"{name}: Anzahl unlesbar ({zellen[1]!r})")
            continue
        if klammer != anzahl:
            fehler.append(f"{name}: Klammer {klammer} != Anzahl {anzahl}")
        genannt = len(re.findall(r"`([^`]+)`", zellen[2]))
        weitere = re.search(r"\+(\d+) weitere", zellen[2])
        summe = genannt + (int(weitere.group(1)) if weitere else 0)
        if summe != anzahl:
            fehler.append(f"{name}: {summe} Namen (inkl. '+N weitere') != Anzahl {anzahl}")
    return zeilen, fehler


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

    check_zahl("Stereotypes: Tabellenzeilen", len(st), "stereotypes")
    check("Stereotypes: 0 ToolboxPage-Einträge", len(toolbox) == 0, f"ist {len(toolbox)}")
    check_zahl("Stereotypes: abstrakte Stereotype (🔒)", len(abstract), "abstract")
    check("Stereotypes: 0 Nicht-Stereotype/Artefakte", len(junk) == 0, f"ist {len(junk)}")
    check_zahl("Stereotypes: nutzbare", len(usable), "usable")
    check("Stereotypes: Katalog = Tabellenzeilen ohne Artefakte",
          len(catalog) == len(st) - len(toolbox) - len(junk),
          f"{len(catalog)} != {len(st)} - {len(toolbox)} - {len(junk)}")
    _st, _ab = ERWARTET.get("stereotypes"), ERWARTET.get("abstract")
    if _st and _ab:
        check(f"Stereotypes: Header nennt {_st} und {_ab} abstrakt",
              f"{_st} Stereotype" in st_text and f"{_ab} abstrakt" in st_text)

    # ---------- 1b. Maschinenlesbarer Katalog (Subtyp-Auflösung) ----------
    cat_path = ROOT / "ADMBw-Stereotypes.json"
    alias_path = ROOT / "ADMBw-Aliases.json"
    check("JSON: Stereotypes-Datei vorhanden", cat_path.is_file())
    check("JSON: Aliases-Datei vorhanden", alias_path.is_file())
    desc = {}
    if cat_path.is_file():
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        cat_by = {s["name"]: s for s in cat["stereotypes"]}
        check_zahl("JSON: Einträge", len(cat_by), "stereotypes")
        check_zahl("JSON: abstrakt", sum(1 for s in cat_by.values() if s["abstract"]), "abstract")
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
    check_zahl("Topology: Zeilen", len(tp), "topology")
    check_zahl("Topology: Regeln mit beiden Enden", len(complete), "rules_complete")
    if "topology" in ERWARTET and "rules_complete" in ERWARTET:
        rest = ERWARTET["topology"] - ERWARTET["rules_complete"]
        check(f"Topology: reine Rollen-Zeilen: {rest}", len(roles_only) == rest, f"ist {len(roles_only)}")
    check("Topology: Lesart 'Quelle = client/source/end[0]/informationSource'",
          "client, source, end[0].role oder informationSource" in tp_text)

    vp_headings = [l for l in vp_text.splitlines() if l.startswith("## ")]
    check_zahl("Viewpoints: Überschriften", len(vp_headings), "viewpoints")
    check("Viewpoints: 'Business Process'-Artefakt entfernt",
          not any("Business Process" in h for h in vp_headings))

    tt_rows = [l for l in tt_text.splitlines() if l.startswith("|")][2:]
    check_zahl("TagTypes: Property-Typen", len(tt_rows), "tag_types")
    if "tag_types" in ERWARTET:
        check(f"TagTypes: Header nennt {ERWARTET['tag_types']} Property-Typen",
              f"{ERWARTET['tag_types']} Property-Typen" in tt_text)

    _zeilen, _fehler = check_metatyp_tabelle(co_text)
    check(f"Connectors: {len(_zeilen)} Metatyp-Zeilen in sich stimmig",
          bool(_zeilen) and not _fehler, "; ".join(_fehler))
    if "viewpoints" in ERWARTET:
        check(f"Connectors: nennt {ERWARTET['viewpoints']} Viewpoints",
              f"{ERWARTET['viewpoints']} Viewpoints" in co_text)

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
