#!/usr/bin/env python3
"""Baut das eine Regelwerk-Artefakt der EAM-Tool-Familie.

Warum
-----
Bisher lagen die Vorgaben in drei getrennten Welten:

* **MDG** -- was ueberhaupt gebaut werden darf (Stereotype, Konnektoren,
  Viewpoints, Werkzeugkaesten). Wird vom einzigen MDG-Leser gelesen.
* **Leitfaeden** -- was fuer FFFmLV und fuer Projektarchitekturen (PBN) je
  Sicht verlangt wird. Zwei Dokumente, zwei Konventionssaetze.
* **Model Wizard** -- wie eine Sicht als Muster aussieht (52 Vorlagen).

Dieses Skript fuehrt sie zusammen, ohne sie zu vermischen: jede Aussage behaelt
ihre Herkunft. Widersprueche werden nicht stillschweigend aufgeloest, sondern
in ``konflikte`` gemeldet.

Aufruf
------
    python3 scripts/build_regelwerk.py [--check]

``--check`` vergleicht nur und schreibt nichts (Exit 1 bei Abweichung).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "rules"))
sys.path.insert(0, str(ROOT / "packages" / "core"))

ZIEL = ROOT / "knowledge" / "regelwerk.json"
LEITFADEN = ROOT / "knowledge" / "leitfaden"
WIZARD = ROOT / "knowledge" / "modelwizard"

QUELLEN = {
    "ffmlv": {
        "id": "ffmlv",
        "titel": "Leitfaden Architekturen fuer FFFmLV",
        "version": "2.0",
        "stand": "2026-04-17",
        "datei": "knowledge/leitfaden/konventionen.json",
    },
    "pbn": {
        "id": "pbn",
        "titel": "Leitfaden Projektarchitekturen (PBN) - Anteil Service und System",
        "version": "2.1",
        "stand": "2026-04-17",
        "datei": "knowledge/leitfaden/konventionen-pbn.json",
    },
}


def _sha256(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


#: Ein Viewpoint-Kuerzel ist kurz: A1, C1-S1, L4-P4, St, Ar.
KURZ = __import__("re").compile(r"^[A-ZÄÖÜ][A-Za-z0-9]{0,3}(?:-[A-ZÄÖÜ0-9][A-Za-z0-9]{0,3})?$")


def _code(name: str) -> str:
    """Viewpoint-Kuerzel aus einem Vorlagen- oder Sichtnamen.

    Die MDG fuehrt neben den Kuerzeln auch benannte ViewDefinitions
    ("Business Process ..."). Die sind keine Sichten und bekommen kein Kuerzel.
    """
    kopf = name.split(":")[0].strip()
    kandidat = kopf.split(" - ")[0].strip()
    return kandidat if KURZ.match(kandidat) else ""


def _konventionen(pfad: Path) -> list[dict[str, str]]:
    return json.loads(pfad.read_text(encoding="utf-8"))


def _mdg() -> dict[str, Any]:
    import mdg_parser  # noqa: PLC0415

    mdg_datei = ROOT / "packages" / "rules" / "NAFv4-ADMBw-MDG-2026.05.xml"
    rules = mdg_parser.parse_mdg(mdg_datei)
    toolbox_nach_name = {box["name"]: box for box in rules.get("toolboxes", [])}
    return {
        "datei": mdg_datei.relative_to(ROOT).as_posix(),
        "sha256": _sha256(mdg_datei),
        "version": rules["source"].get("technologyVersion"),
        "viewpoints": rules["viewpoints"],
        "stereotypes": rules["elementStereotypes"],
        "konnektoren": rules["connectorRules"],
        "toolboxen": toolbox_nach_name,
    }


def _wizard() -> dict[str, Any]:
    import wizard  # noqa: PLC0415

    return wizard.lade_alle(WIZARD)


def baue() -> dict[str, Any]:
    mdg = _mdg()
    vorlagen = _wizard()
    pruefung_datei = ROOT / "knowledge" / "leitfaden" / "pruefung.json"
    pruefung = json.loads(pruefung_datei.read_text(encoding="utf-8"))
    leit = {key: _konventionen(ROOT / wert["datei"]) for key, wert in QUELLEN.items()}

    # --- Viewpoints sammeln: MDG ist die Klammer, alles andere haengt sich an
    codes: set[str] = set()
    titel: dict[str, str] = {}
    gruppe: dict[str, str] = {}
    toolbox_je_code: dict[str, str] = {}

    for viewpoint in mdg["viewpoints"]:
        name = viewpoint["name"]
        code = _code(name)
        if not code:
            continue
        codes.add(code)
        titel.setdefault(code, name)
        gruppe.setdefault(code, (viewpoint.get("group") or "").replace("NAFv4-ADMBw ", ""))
        kasten = (viewpoint.get("properties") or {}).get("toolbox")
        if kasten:
            toolbox_je_code.setdefault(code, kasten)

    for name in vorlagen:
        code = _code(name)
        codes.add(code)
        titel.setdefault(code, name)

    for key, eintraege in leit.items():
        for eintrag in eintraege:
            code = eintrag["viewpoint"]
            codes.add(code)
            titel.setdefault(code, code)
    titel["VÜ"] = "Viewpoint-übergreifend"
    gruppe["VÜ"] = "Übergreifend"

    # --- Schichten je Viewpoint
    viewpoints: dict[str, Any] = {}
    konflikte: list[dict[str, str]] = []

    konventionen_je_code: dict[str, dict[str, list[str]]] = {}
    for key, eintraege in leit.items():
        for eintrag in eintraege:
            code = eintrag["viewpoint"]
            konventionen_je_code.setdefault(code, {}).setdefault(key, []).append(eintrag["id"])

    mdg_stereo = {e["name"] for e in mdg["stereotypes"]}

    for code in sorted(codes):
        kasten = toolbox_je_code.get(code)
        box = mdg["toolboxen"].get(kasten or "", {"items": []})

        elemente_mdg = sorted({i["stereotype"] for i in box["items"]})
        elemente_set = set(elemente_mdg)

        konnektoren = [
            [r["stereotype"], r["source"][0], r["target"][0]]
            for r in mdg["konnektoren"]
            if r["source"] and r["target"]
            and r["source"][0] in elemente_set
            and r["target"][0] in elemente_set
        ]

        vorlage = next((v for name, v in vorlagen.items() if _code(name) == code), None)
        wz = None
        if vorlage is not None:
            wz = {
                "vorlage": vorlage.name,
                "elemente": list(vorlage.stereotype),
                "beziehungen": [list(b) for b in vorlage.beziehungen],
                "assoziationen": vorlage.assoziationen,
                "rtf": vorlage.rtf,
            }
            fremd = sorted(set(vorlage.stereotype) - mdg_stereo)
            if fremd:
                konflikte.append(
                    {
                        "viewpoint": code,
                        "typ": "stereotyp_nicht_in_mdg",
                        "quelle": "model-wizard",
                        "werte": ", ".join(fremd),
                    }
                )

        lf = {}
        for key in leit:
            ids = sorted(konventionen_je_code.get(code, {}).get(key, []))
            lf[key] = {"konventionen": len(ids), "ids": ids}

        fehlend = []
        if not elemente_mdg:
            fehlend.append("mdg")
        if lf["ffmlv"]["konventionen"] == 0:
            fehlend.append("ffmlv")
        if lf["pbn"]["konventionen"] == 0 and code not in {"St"}:
            fehlend.append("pbn")
        if vorlage is None:
            fehlend.append("model-wizard")

        if "mdg" in fehlend and vorlage is not None:
            konflikte.append(
                {
                    "viewpoint": code,
                    "typ": "sicht_ohne_mdg_toolbox",
                    "quelle": "model-wizard",
                    "werte": "Vorlage vorhanden, MDG kennt keinen Werkzeugkasten",
                }
            )

        viewpoints[code] = {
            "titel": titel.get(code, code),
            "gruppe": gruppe.get(code, ""),
            "mdg": {
                "toolbox": kasten,
                "elemente": elemente_mdg,
                "konnektoren": konnektoren,
            },
            "leitfaeden": lf,
            "model_wizard": wz,
            "luecken": fehlend,
        }

    # --- Kennzahlen
    alle = len(viewpoints)
    summary = {
        "viewpoints": alle,
        "mit_mdg": sum(1 for v in viewpoints.values() if v["mdg"]["elemente"]),
        "mit_ffmlv": sum(1 for v in viewpoints.values() if v["leitfaeden"]["ffmlv"]["konventionen"]),
        "mit_pbn": sum(1 for v in viewpoints.values() if v["leitfaeden"]["pbn"]["konventionen"]),
        "mit_model_wizard": sum(1 for v in viewpoints.values() if v["model_wizard"]),
        "nur_im_wizard": sum(
            1
            for v in viewpoints.values()
            if v["model_wizard"]
            and not v["leitfaeden"]["ffmlv"]["konventionen"]
            and not v["leitfaeden"]["pbn"]["konventionen"]
        ),
        "konflikte": len(konflikte),
        "konventionen_ffmlv": len(leit["ffmlv"]),
        "konventionen_pbn": len(leit["pbn"]),
        "mdg_stereotype": len(mdg["stereotypes"]),
        "mdg_konnektoren": len(mdg["konnektoren"]),
        "mdg_toolboxen": len(mdg["toolboxen"]),
        "wizard_vorlagen": len(vorlagen),
    }

    return {
        "schemaVersion": 1,
        "zweck": (
            "Ein Artefakt fuer alle Pipelines: erlaubt (MDG), gefordert (Leitfaeden), "
            "gemustert (Model Wizard) -- je Viewpoint, mit Herkunft."
        ),
        "quellen": {
            "mdg": {
                "datei": mdg["datei"],
                "sha256": mdg["sha256"],
                "version": mdg["version"],
            },
            "leitfaeden": {
                key: {
                    **{k: v for k, v in wert.items() if k != "datei"},
                    "datei": wert["datei"],
                    "sha256": _sha256(ROOT / wert["datei"]),
                    "eintraege": len(leit[key]),
                }
                for key, wert in QUELLEN.items()
            },
            "model_wizard": {
                "ordner": "knowledge/modelwizard",
                "vorlagen": len(vorlagen),
            },
            "pruefung": {
                "datei": "knowledge/leitfaden/pruefung.json",
                "sha256": _sha256(pruefung_datei),
                "pakete": len(pruefung["packages"]),
                "sichten": len(pruefung["diagrams"]),
                "pflicht": len(pruefung["pflicht"]),
            },
        },
        "summary": summary,
        "viewpoints": viewpoints,
        # Pakete, Sichten und Pflichtstereotype je Viewpoint. Das ist die
        # Ebene, gegen die struktur.py prueft -- ohne sie kennt das Artefakt
        # zwar die Bausteine, aber nicht die geforderte Form.
        "pruefung": {
            "packages": pruefung["packages"],
            "diagrams": pruefung["diagrams"],
            "pflicht": pruefung["pflicht"],
        },
        "konflikte": sorted(konflikte, key=lambda k: (k["viewpoint"], k["typ"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Regelwerk-Artefakt bauen")
    parser.add_argument("--check", action="store_true", help="nur pruefen")
    args = parser.parse_args()

    daten = baue()
    text = json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=False) + "\n"

    if args.check:
        if not ZIEL.is_file():
            print(f"fehlt: {ZIEL}")
            return 1
        if ZIEL.read_text(encoding="utf-8") != text:
            print("Regelwerk weicht ab -- neu bauen mit scripts/build_regelwerk.py")
            return 1
        print("Regelwerk unveraendert")
        return 0

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=ZIEL.parent) as tmp:
        tmp.write(text)
        name = tmp.name
    Path(name).replace(ZIEL)

    s = daten["summary"]
    print(f"geschrieben: {ZIEL.relative_to(ROOT)}  ({len(text):,} Zeichen)")
    print(
        f"Viewpoints {s['viewpoints']} | MDG {s['mit_mdg']} | FFFmLV {s['mit_ffmlv']} | "
        f"PBN {s['mit_pbn']} | Wizard {s['mit_model_wizard']}"
    )
    print(f"nur im Wizard: {s['nur_im_wizard']} | Konflikte: {s['konflikte']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
