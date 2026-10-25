#!/usr/bin/env python3
"""Deterministische Prüfungen für EAM-AI-ADMBw-Extractor (ohne LLM).

Prüft ohne LLM-Aufruf:
 1. KB-Statistiken (Stereotypes/Topology/Viewpoints/Connectors) gegen die dokumentierten Zahlen
 2. SHA-256-Hashes der vier MDG-KB-Dateien (Stereotypes, Topology, Viewpoints, TagTypes)
 2b. Maschinenlesbarer Katalog (ADMBw-Stereotypes.json) und Aliases (ADMBw-Aliases.json)
 3. Topologie-Lesart korrigiert (client = Quelle, supplier = Ziel)
 4. 🔒-Markierungen der 44 abstrakten Stereotype, Subtyp-Auflösung und Alias-Tabelle
 5. Prompt/README/ANLEITUNG enthalten die korrigierten Zahlen; keine 443/203/53-Altbehauptungen
 6. Prompt: maschinenprüfbare Kanten-Validierungstabelle + Few-Shot + Leerinput-Regel

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
    rows = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 5 or cells[1] in ("", "Stereotype"):
            continue
        rows.append((cells[1], cells[2], cells[3], cells[4] if len(cells) > 4 else ""))
    return rows


def main():
    st_text = (ROOT / "ADMBw-Knowledge-Stereotypes.md").read_text(encoding="utf-8")
    tp_text = (ROOT / "ADMBw-Knowledge-Topology.md").read_text(encoding="utf-8")
    vp_text = (ROOT / "ADMBw-Knowledge-Viewpoints.md").read_text(encoding="utf-8")
    tt_text = (ROOT / "ADMBw-Knowledge-TagTypes.md").read_text(encoding="utf-8")
    co_text = (ROOT / "ADMBw-Knowledge-Connectors.md").read_text(encoding="utf-8")

    # ---------- 1. KB-Statistiken ----------
    st = parse_stereotypes(st_text)
    toolbox = [r for r in st if r[3] == "ToolboxPage"]
    abstract = [r for r in st if "🔒" in r[4]]
    junk = [r for r in st if r[0] == "L2-Operational Constraints"]
    usable = [r for r in st if r[3] not in ("", "ToolboxPage")]
    check_zahl("Stereotypes: Tabellenzeilen", len(st), "stereotypes")
    check("Stereotypes: 0 ToolboxPage-Einträge", len(toolbox) == 0, f"ist {len(toolbox)}")
    check_zahl("Stereotypes: abstrakte Stereotype (🔒)", len(abstract), "abstract")
    check("Stereotypes: 0 Nicht-Stereotype/Artefakte", len(junk) == 0, f"ist {len(junk)}")
    check_zahl("Stereotypes: nutzbare", len(usable), "usable")
    _st, _ab = ERWARTET.get("stereotypes"), ERWARTET.get("abstract")
    if _st and _ab:
        check(f"Stereotypes: Header nennt {_st} und {_ab} abstrakt",
              f"{_st} Stereotype" in st_text and f"{_ab} abstrakt" in st_text)
    check("Stereotypes: KI-Hinweis zu abstrakten Typen vorhanden", "## Hinweis für KI-Werkzeuge" in st_text)
    check("Stereotypes: Eltern-Spalte vorhanden", "| Stereotype | Metatype | Eltern | AppliesTo | Abstrakt | Beschreibung |" in st_text)

    # ---------- 1b. Maschinenlesbarer Katalog & Auflösung ----------
    cat_path = ROOT / "ADMBw-Stereotypes.json"
    alias_path = ROOT / "ADMBw-Aliases.json"
    check("JSON: Stereotypes-Datei vorhanden", cat_path.is_file())
    check("JSON: Aliases-Datei vorhanden", alias_path.is_file())
    if cat_path.is_file():
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        checks_ = {s["name"]: s for s in cat["stereotypes"]}
        check_zahl("JSON: Einträge", len(checks_), "stereotypes")
        check_zahl("JSON: abstrakt", sum(1 for s in checks_.values() if s["abstract"]), "abstract")
        rp = checks_.get("ResourcePerformer", {})
        check("JSON: ResourcePerformer abstrakt mit konkreten Subtypen",
              rp.get("abstract") is True and len(rp.get("concreteDescendants", [])) >= 10,
              f"subtypen={len(rp.get('concreteDescendants', []))}")
        bw = checks_.get("BWRequirement", {})
        check("JSON: BWRequirement → FunctionalRequirement/NonfunctionalRequirement",
              bw.get("abstract") is True and
              {"FunctionalRequirement", "NonfunctionalRequirement"}.issubset(set(bw.get("concreteDescendants", []))))
        check("JSON: CapabilityConfiguration ist Subtyp von ResourcePerformer",
              "CapabilityConfiguration" in set(rp.get("concreteDescendants", [])))
    if alias_path.is_file():
        al = json.loads(alias_path.read_text(encoding="utf-8")).get("aliases", {})
        check("Aliases: PropertySetGeneralisation abgebildet",
              al.get("PropertySetGeneralisation") == "PropertySetGeneralization")
        check("Aliases: ServiceSpecificationGeneralization abgebildet",
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
    check("Topology: Spaltenköpfe Quelle/Ziel normalisiert",
          "| Stereotype | Erlaubte Quellen (client/source/end[0]) | Erlaubte Ziele (supplier/target/end[1]) | Weitere Rollen |" in tp_text)
    check("Topology: Abschnitt 'Abstrakte Endpunkte' vorhanden", "## Abstrakte Endpunkte" in tp_text)
    check("Topology: ResourcePerformer-Auflösung dokumentiert",
          "| 🔒 ResourcePerformer |" in tp_text and "CapabilityConfiguration" in tp_text)

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

    # ---------- 2. Hashes ----------
    hashes = {}
    for f in ["ADMBw-Knowledge-Stereotypes.md", "ADMBw-Knowledge-Topology.md",
              "ADMBw-Knowledge-Viewpoints.md", "ADMBw-Knowledge-TagTypes.md"]:
        data = (ROOT / f).read_bytes()
        hashes[f] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    check("Hashes: vier MDG-KB-Dateien berechnet", len(hashes) == 4)

    # ---------- 3.-6. Prompt & Doku ----------
    prompt = (ROOT / "system_prompt.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    anleitung = (ROOT / "ANLEITUNG.md").read_text(encoding="utf-8")

    docs = prompt + "\n" + readme + "\n" + anleitung
    check("Doku: keine Alt-Behauptung '443 eindeutige'", "443 eindeutige" not in docs)
    check("Doku: keine Alt-Behauptung '203 Beziehungsregeln'", "203 Beziehungsregeln" not in docs)
    check("Doku: keine Alt-Behauptung '53 Viewpoints'", "53 Viewpoints" not in docs)
    check("Doku: '8/8 ✓' entfernt", "8/8" not in prompt)
    check("Prompt: Topologie-Lesart dokumentiert", "Quelle = client/source/end[0].role/informationSource" in prompt)
    check("Prompt: Kanten-Validierungstabelle (source_stereotype/connector/target_stereotype/PASS/FAIL)",
          all(k in prompt for k in ["source_stereotype", "connector", "target_stereotype", "PASS/FAIL"]))
    check("Prompt: Zählung 'X/Y Kanten PASS' statt Pauschal-Claim",
          "Topologie-Prüfung: **X/Y Kanten PASS**" in prompt)
    check("Prompt: Few-Shot enthalten", "FEW-SHOT" in prompt and "Topologie-Prüfung: 4/4 Kanten PASS" in prompt)
    check("Prompt: Leerinput-Regel enthalten", "LEERER / UNLESBARER INPUT" in prompt)
    if "abstract" in ERWARTET:
        check(f"Prompt: nennt {ERWARTET['abstract']} abstrakte Typen und die Subtyp-Auflösung",
              str(ERWARTET["abstract"]) in prompt and "concreteDescendants" in prompt
              and "Subtyp" in prompt)
    check("Prompt: Auflösungsspalte in der Validierungstabelle", "Auflösung (falls Subtyp)" in prompt)
    check("Prompt: alte Fehlregel 'abstraktes Regel-Ende = FAIL' entfernt",
          "Regel-Ende ist ein 🔒-abstrakter Stereotyp" not in prompt)
    check("Prompt: Alias-Normalisierung dokumentiert", "ADMBw-Aliases.json" in prompt)
    if {"stereotypes", "usable", "rules_complete", "viewpoints"} <= set(ERWARTET):
        erwartete_texte = [
            f"{ERWARTET['stereotypes']} Katalog-Stereotype",
            f"{ERWARTET['usable']} nutzbar",
            f"{ERWARTET['rules_complete']} vollständige",
            f"{ERWARTET['viewpoints']} Viewpoints",
        ]
        check("README: nennt die Zahlen des aktuellen MDG-Stands",
              all(k in readme for k in erwartete_texte),
              "; ".join(k for k in erwartete_texte if k not in readme))
        check("ANLEITUNG: nennt die Zahlen des aktuellen MDG-Stands",
              f"{ERWARTET['rules_complete']} vollständige Topologie-Regeln, "
              f"{ERWARTET['viewpoints']} Viewpoints" in anleitung)
    check("Keine Bw-PDF im Repository", not list(ROOT.glob("*.pdf")))
    check("README: keine PDF-Referenz mehr", "Dokumentation-ADMBw" not in readme and ".pdf" not in readme.lower())
    check("README: Quelle der Wahrheit benannt", "Methode Architektur" in readme)
    check("README: KB-Sync auf Parserstand 2026-10-19", "KB-Sync-Status (2026-10-19): PENDING" not in readme)
    check("README: keine PENDING-Formulierung", "Parser-Nachlieferung ausstehend" not in (readme + anleitung + prompt))

    # ---------- Ergebnis ----------
    report = {
        "kb": {
            "stereotypes": {"rows": len(st), "toolbox": len(toolbox), "abstract": len(abstract),
                            "usable": len(usable), "junk": len(junk)},
            "topology": {"rows": len(tp), "complete_rules": len(complete), "roles_only": len(roles_only)},
            "viewpoints": len(vp_headings),
            "hashes": hashes,
        },
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
