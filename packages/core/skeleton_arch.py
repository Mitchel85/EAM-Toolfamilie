#!/usr/bin/env python3
"""skeleton_arch.py -- Geruest-Modell in der MASC-Struktur.

Warum ein zweites Geruest?
--------------------------
``skeleton.py`` instanziiert das Regelwerk *nach Metaklasse*: ein Paket je
Element-Metaklasse (Class, Object, Part ...) und darin je Stereotyp ein
Element. Das ergibt 134 Elemente in 16 technischen Paketen. Es erklaert
Typelemente, aber es ist keine Architektur: die Pakete heissen wie
UML-Metaklassen, es gibt keinen Katalog, keine Viewpoints, keine Sichten.

Die Musterarchitektur MASC ordnet anders -- nach **Rollen im Modell**:

    <Wurzel>
    ├── Startseite <Wurzel>        (1 View, 1 ArchitectureMetadata)
    ├── <Wurzel> - Idealtypische Architektur
    │   ├── Architekturauftrag     A1..A8, Ar
    │   ├── Geschäftsarchitektur   C*, L*
    │   ├── Servicearchitektur     S*, C1-S1
    │   ├── Systemarchitektur      P*, L4-P4
    │   ├── Anforderungen          R2, R3, R7, R8, Rr
    │   └── Modellelementekatalog  je Element-Stereotyp ein Paket
    ├── Viewpoints (Gesamtgefüge)  je Viewpoint: ein Viewpoint + ein View
    └── <Wurzel> - Glossar         Abkürzungsverzeichnis

Dieses Modul baut genau diese Struktur -- vollstaendig aus dem Regelwerk
(MDG) und ohne Text, also offline und deterministisch. Es erfindet keine
Projektinhalte: Der Katalog enthaelt die Stereotyp-Definitionen des
Regelwerks, die Viewpoint-Sammlung die 53 Viewpoints der Technologie.

Oeffentliche API::

    from skeleton_arch import build_arch_skeleton
    ir = build_arch_skeleton(rules, package="Projekt")

CLI::

    python3 skeleton_arch.py technologie.xml --package Projekt -o geruest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import extract

#: Kennung im IR: Struktur aus dem Regelwerk, kein Sprachmodell.
ARCH_BACKEND = "regelwerk-architektur"

#: Art des Geruests -- von ``eam_ai.build`` ausgewertet.
ARCH_KIND = "architektur"

#: Volumes der Idealtypischen Architektur (Reihenfolge = MASC).
VOLUMES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Architekturauftrag", "Architecture Foundation Viewpoints",
     ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "Ar")),
    ("Geschäftsarchitektur", "Concept Viewpoints",
     ("C1", "C2", "C3", "C4", "C5", "C7", "C8", "Cr")),
    ("Geschäftsarchitektur", "Logical Specification Viewpoints",
     ("L1", "L2", "L2-L3", "L3", "L4", "L5", "L6", "L7", "L8", "Lr")),
    ("Servicearchitektur", "Service Specification Viewpoints",
     ("C1-S1", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "Sr")),
    ("Systemarchitektur", "Physical Resource Specification Viewpoints",
     ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "Pr", "L4-P4")),
    ("Anforderungen", "Requirement Viewpoints",
     ("R2", "R3", "R7", "R8", "Rr")),
)

#: Paketname im Katalog fuer Stereotype ohne Metaklasse.
OHNE_METAKLASSE = "ohne Metaklasse"


class ArchSkeletonError(ValueError):
    """Regelwerk oder Zielpaket taugen nicht. Immer laut."""


def _segment(value: str) -> str:
    text = " ".join(str(value).split())
    text = text.replace("\\", "\u2216").replace("/", "\u2215").replace("::", ":")
    return text or "Regelwerk"


def _root(rules: Mapping[str, Any], package: str | None) -> str:
    if package and package.strip():
        text = package.strip()
        if "\\" in text or "::" in text or text.startswith("/") or text.endswith("/"):
            raise ArchSkeletonError(f"package: ungueltiger Pfad {text!r}")
        return text
    source = rules.get("source")
    name = ""
    if isinstance(source, Mapping):
        name = str(source.get("technologyName") or source.get("technologyId") or "")
    return _segment(name) if name else extract.DEFAULT_PACKAGE


def _viewpoints(rules: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Viewpoints nach Kurzkennung (``A1``, ``C1-S1`` ...) indexieren."""
    out: dict[str, dict[str, Any]] = {}
    raw = rules.get("viewpoints")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return out
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        properties = entry.get("properties")
        code = ""
        if isinstance(properties, Mapping):
            code = str(properties.get("diagramID") or "").strip()
        if not code:
            name = str(entry.get("name") or "")
            code = name.split(" - ")[0].strip()
        if not code:
            continue
        out.setdefault(code, dict(entry))
    return out


def _catalog(rules: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    """Katalog-Eintraege: (Paketname, Stereotyp, ea_type, notes).

    Je instanziierbarem Element-Stereotyp ein Paket. Abstrakte Stereotype und
    reine Paket-Stereotype entfallen: sie sind nicht instanziierbar. Note-Only-
    Stereotype (``Information``, ``ArchitectureMetadata`` ...) bleiben: MASC
    fuehrt sie ebenfalls im Katalog.
    """
    raw = rules.get("elementStereotypes")
    entries: list[tuple[str, str, str, str]] = []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return entries
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        metaclasses = [m for m in entry.get("metaclasses") or [] if str(m).strip().lower() != "package"]
        if not metaclasses:
            continue
        # Abstrakte Stereotype sind nicht instanziierbar -- auch im Katalog
        # nicht. Der Pruefer (validator) meldet sie zu Recht als Warnung.
        if entry.get("abstract") is True:
            continue
        ea_type = str(metaclasses[0]).strip()
        note = str(entry.get("notes") or "").strip()
        if not note:
            note = (
                f"Element-Stereotyp '{name}' aus dem Regelwerk "
                f"(Metaklasse: {ea_type})."
            )
        entries.append((name, name, ea_type, note))
    return sorted(entries, key=lambda item: (item[0].casefold(), item[0]))


def build_arch_skeleton(
    rules: Mapping[str, Any],
    *,
    package: str | None = None,
    viewpoints_per_code: bool = True,
) -> dict[str, Any]:
    """IR-Geruest in MASC-Struktur aus einem geparsten MDG-Regelwerk."""
    if not isinstance(rules, Mapping):
        raise ArchSkeletonError(f"rules: Regelwerk (Mapping) erwartet, gefunden {type(rules).__name__}")

    root = _root(rules, package)
    viewpoints = _viewpoints(rules)
    catalog = _catalog(rules)

    packages: list[dict[str, Any]] = [{"path": root, "notes": f"Architekturmodell nach NAFv4-ADMBw (Geruest)."}]
    elements: list[dict[str, Any]] = []

    # 1 Startseite
    start = f"{root}/Startseite {root}"
    packages.append({"path": start, "notes": "Einstiegsseite des Modells."})
    elements.append({
        "package": start,
        "name": "Beispielarchitektur",
        "stereotype": "ArchitectureMetadata",
        "ea_type": "Note",
        "notes": f"Architektur {root} -- aus dem Regelwerk erzeugtes Geruest.",
    })
    elements.append({
        "package": start,
        "name": f"Startseite {root}",
        "stereotype": "View",
        "ea_type": "Class",
        "notes": "Startansicht des Modells.",
    })

    # 2 Idealtypische Architektur mit fuenf Volumes und den Viewpoint-Paketen
    ideal = f"{root}/{root} - Idealtypische Architektur"
    packages.append({"path": ideal, "notes": "Projektarchitektur, nach Viewpoint-Familien geordnet."})
    used_codes: set[str] = set()
    for volume, _group, codes in VOLUMES:
        volume_path = f"{ideal}/{volume}"
        if not any(p["path"] == volume_path for p in packages):
            packages.append({"path": volume_path, "notes": f"Viewpoint-Familie {volume}."})
        for code in codes:
            vp = viewpoints.get(code)
            if vp is None:
                continue
            used_codes.add(code)
            name = str(vp.get("name") or code)
            vp_path = f"{volume_path}/{code}"
            packages.append({"path": vp_path, "notes": name})
            elements.append({
                "package": vp_path,
                "name": name,
                "stereotype": "Viewpoint",
                "ea_type": "Class",
                "notes": str(vp.get("notes") or name),
            })
            if viewpoints_per_code:
                elements.append({
                    "package": vp_path,
                    "name": name.split(" - ", 1)[-1],
                    "stereotype": "View",
                    "ea_type": "Class",
                    "notes": f"Sicht {name}.",
                })

    # 3 Modellelementekatalog
    katalog = f"{ideal}/Modellelementekatalog"
    packages.append({"path": katalog, "notes": "Je Element-Stereotyp ein Paket mit dessen Definition."})
    for name, stereotype, ea_type, note in catalog:
        pkg_path = f"{katalog}/{_segment(name)}"
        packages.append({"path": pkg_path, "notes": f"Stereotyp {stereotype} ({ea_type})."})
        elements.append({
            "package": pkg_path,
            "name": name,
            "stereotype": stereotype,
            "ea_type": ea_type,
            "notes": note,
        })

    # 4 Viewpoints (Gesamtgefuege): alle Viewpoints, auch jene ohne Volume
    gesamt = f"{root}/Viewpoints (Gesamtgefüge)"
    packages.append({"path": gesamt, "notes": "Alle Viewpoints der Technologie."})
    for code in sorted(viewpoints, key=lambda item: (item.casefold(), item)):
        vp = viewpoints[code]
        name = str(vp.get("name") or code)
        vp_path = f"{gesamt}/{_segment(code)}"
        packages.append({"path": vp_path, "notes": name})
        elements.append({
            "package": vp_path,
            "name": name,
            "stereotype": "Viewpoint",
            "ea_type": "Class",
            "notes": str(vp.get("notes") or name),
        })
        elements.append({
            "package": vp_path,
            "name": name.split(" - ", 1)[-1],
            "stereotype": "View",
            "ea_type": "Class",
            "notes": f"Sicht {name}.",
        })

    # 5 Glossar
    glossar = f"{root}/{root} - Glossar"
    abk = f"{glossar}/Abkürzungsverzeichnis"
    packages.append({"path": glossar, "notes": "Begriffe des Modells."})
    packages.append({"path": abk, "notes": "Abkuerzungen."})
    elements.append({
        "package": abk,
        "name": root,
        "stereotype": "DocumentReference",
        "ea_type": "Class",
        "notes": f"Abkuerzung fuer das Projekt {root}.",
    })

    ir: dict[str, Any] = {
        "ir_version": extract.IR_VERSION,
        "packages": packages,
        "elements": elements,
        "connectors": [],
        "diagrams": [],
        "meta": {
            "skeleton": {
                "kind": "masc-struktur",
                "backend": ARCH_BACKEND,
                "root": root,
                "packages": len(packages),
                "elements": len(elements),
                "catalogStereotypes": len(catalog),
                "viewpoints": len(viewpoints),
                "viewpointsMitVolume": len(used_codes),
            }
        },
    }
    source = rules.get("source")
    if isinstance(source, Mapping):
        technology = {}
        if source.get("technologyId"):
            technology["profile"] = str(source["technologyId"])
        if source.get("technologyName"):
            technology["name"] = str(source["technologyName"])
        if source.get("technologyVersion"):
            technology["version"] = str(source["technologyVersion"])
        if technology:
            ir["technology"] = technology
    return ir


def main(argv: Sequence[str] | None = None) -> int:
    import mdg_parser

    parser = argparse.ArgumentParser(
        prog="skeleton_arch.py",
        description="Geruest-IR in MASC-Struktur aus einem MDG-Regelwerk (ohne Text, ohne KI).",
    )
    parser.add_argument("mdg", type=Path, help="MDG-/Technologie-XML")
    parser.add_argument("-o", "--out", type=Path, help="Ziel-JSON (sonst stdout)")
    parser.add_argument("--package", default=None, help="Wurzelpaket (Default: Technologie-Name)")
    args = parser.parse_args(argv)

    try:
        rules = mdg_parser.parse_mdg(args.mdg)
        ir = build_arch_skeleton(rules, package=args.package)
    except (mdg_parser.MdgParseError, ArchSkeletonError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        meta = ir["meta"]["skeleton"]
        print(
            f"{args.out}: {meta['elements']} Elemente in {meta['packages']} Paketen, "
            f"{meta['catalogStereotypes']} Katalogeintraege, {meta['viewpoints']} Viewpoints",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
