"""skeleton.py -- Geruest-Modell allein aus dem MDG-Regelwerk.

Der Weg ohne Prosa: statt Saetze zu extrahieren, wird das Regelwerk selbst
instanziiert. Je Element-Metaklasse entsteht ein Paket, darin je
instanziierbarem Element-Stereotyp genau ein Element. Namen und
Beschreibungen stammen ausschliesslich aus dem Regelwerk (``notes`` des
Stereotyps); fehlt dort eine Beschreibung, wird sie aus dem Stereotyp-Namen
gebildet und als solche gekennzeichnet. Es wird nichts erfunden, was nicht im
Regelwerk steht.

Beziehungen: eine Konnektor-Regel wird nur dann instanziiert, wenn *beide*
Enden als Element-Stereotyp im Geruest stehen. Regeln mit Platzhalter (``*``)
oder mit Metaklassen-Endpunkten werden uebersprungen und im ``meta``-Block
gezaehlt -- eine Kante zwischen geratenen Endpunkten waere eine Erfindung.

Oeffentliche API::

    from skeleton import build_skeleton

    ir = build_skeleton(rules)          # rules = mdg_parser.parse_mdg(...)

Das IR hat dasselbe Format wie ``extract.answer_to_ir`` (``ir_version`` 1,
Kanten-Referenzen ``<paket>::<element>``), damit Pruefung und Export
unveraendert laufen. Ohne ``backend`` und ohne Text gibt es keinen
Modellaufruf; der Lauf ist vollstaendig offline.

CLI (nur zur Sichtpruefung des Geruests)::

    python3 skeleton.py technologie.xml [-o geruest.json] [--package Wurzel]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import extract

#: Kennung im IR: das Modell kam aus dem Regelwerk, nicht aus einem Sprachmodell.
SKELETON_BACKEND = "regelwerk"

#: Paketname fuer Element-Stereotype ohne eigene Metaklasse. Kein erfundener
#: Metaklassenname, sondern die ehrliche Bezeichnung der Luecke.
OHNE_METAKLASSE = "ohne Metaklasse"

#: Wurzelpaket, wenn weder Argument noch Technologie einen Namen liefern.
FALLBACK_PACKAGE = extract.DEFAULT_PACKAGE


class SkeletonError(ValueError):
    """Regelwerk oder Zielpaket taugen nicht fuer ein Geruest. Immer laut."""


# --------------------------------------------------------------------------
# Namen und Pfade
# --------------------------------------------------------------------------


def _segment(value: str) -> str:
    """Ein Paketname als Pfadsegment (IR-Regeln: kein '/', kein '::')."""
    text = " ".join(str(value).split())
    text = text.replace("\\", "\u2216").replace("/", "\u2215").replace("::", ":")
    if text in ("", ".", ".."):
        return "Regelwerk"
    return text


def _normalize_package(path: str | None) -> str | None:
    """Zielpaket wie ``extract._normalize_package`` pruefen.

    ``None`` bedeutet: Wurzel aus der Technologie ableiten.
    """
    if path is None:
        return None
    if not isinstance(path, str) or not path.strip():
        raise SkeletonError("package: Zielpaket darf nicht leer sein")
    text = path.strip()
    if "\\" in text:
        raise SkeletonError(f"package: Backslash in {text!r} -- Trenner ist '/'")
    if "::" in text:
        raise SkeletonError(f"package: '::' ist fuer Element-Referenzen reserviert ({text!r})")
    if text.startswith("/") or text.endswith("/") or "//" in text:
        raise SkeletonError(f"package: ungueltiger Pfad {text!r}")
    for part in text.split("/"):
        if part in ("", ".", ".."):
            raise SkeletonError(f"package: ungueltiges Pfadsegment {part!r} in {text!r}")
    return text


def _ancestors(path: str) -> list[str]:
    """Alle Elternpfade inklusive des Pfads selbst, von der Wurzel an."""
    parts = path.split("/")
    return ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]


def _technology(rules: Mapping[str, Any]) -> dict[str, str]:
    """Technologie-Kopf wie im Extraktions-IR (nur vorhandene Werte)."""
    technology: dict[str, str] = {}
    source = rules.get("source")
    if isinstance(source, Mapping):
        if source.get("technologyId"):
            technology["profile"] = str(source["technologyId"])
        if source.get("technologyName"):
            technology["name"] = str(source["technologyName"])
        if source.get("technologyVersion"):
            technology["version"] = str(source["technologyVersion"])
    return technology


def _root_package(rules: Mapping[str, Any], package: str | None) -> str:
    """Wurzelpaket: explizites Ziel, sonst der Name der Technologie."""
    explicit = _normalize_package(package)
    if explicit:
        return explicit
    technology = _technology(rules)
    for key in ("name", "profile"):
        value = technology.get(key, "").strip()
        if value:
            return _segment(value)
    return FALLBACK_PACKAGE


# --------------------------------------------------------------------------
# Geruest
# --------------------------------------------------------------------------


def _primary_metaclass(rule: extract.ElementStereotype) -> str:
    """Erste Nicht-Paket-Metaklasse einer Element-Regel (leer, wenn keine)."""
    for metaclass in rule.metaclasses:
        if metaclass.strip().lower() != "package":
            return metaclass
    return ""


def _note(rule: extract.ElementStereotype, technology: Mapping[str, str]) -> str:
    """Beschreibung aus dem Stereotyp-Namen, wenn das Regelwerk keine hat.

    ``notes`` steht im geparsten Regelwerk, nicht in ``ElementStereotype``;
    der Aufrufer bevorzugt sie. Dieser Text ist die ehrliche Rueckfallebene
    und nennt seine Herkunft.
    """
    technology_name = technology.get("name") or technology.get("profile") or "Regelwerk"
    return (
        f"Element-Stereotyp '{rule.name}' aus dem Regelwerk {technology_name} "
        f"(Metaklasse: {_primary_metaclass(rule) or 'ohne Angabe'})."
    )


def _connector_plan(
    rulebook: extract.RuleBook,
    package_by_stereotype: Mapping[str, str],
) -> tuple[list[dict[str, Any]], int]:
    """Kanten aus Konnektor-Regeln, deren beide Enden im Geruest stehen.

    Rueckgabe: (IR-Kanten, Anzahl uebersprungener Regeln). Endpunkte werden
    nicht geraten: nur exakte Element-Stereotyp-Namen aus dem Regelwerk.
    """
    connectors: list[dict[str, Any]] = []
    skipped = 0
    for name in sorted(rulebook.connectors, key=lambda item: (item.casefold(), item)):
        rule = rulebook.connectors[name]
        sources = [item for item in rule.source if item in package_by_stereotype]
        targets = [item for item in rule.target if item in package_by_stereotype]
        if not sources or not targets:
            skipped += 1
            continue
        source = sources[0]
        target = targets[0]
        connectors.append(
            {
                "source": f"{package_by_stereotype[source]}::{source}",
                "target": f"{package_by_stereotype[target]}::{target}",
                "stereotype": name,
                "ea_type": rulebook.connector_ea_type(name),
                "name": "",
                "direction": rulebook.connector_direction(name),
                "notes": "",
            }
        )
    return connectors, skipped


def build_skeleton(
    rules: Mapping[str, Any],
    *,
    package: str | None = None,
) -> dict[str, Any]:
    """IR-Geruest aus einem geparsten MDG-Regelwerk bauen.

    ``rules`` ist das Ergebnis von ``mdg_parser.parse_mdg`` (oder eine
    gleichwertige Zuordnung). ``package`` setzt das Wurzelpaket; ohne Angabe
    wird der Technologie-Name verwendet.
    """
    if not isinstance(rules, Mapping):
        raise SkeletonError(
            f"rules: Regelwerk (Mapping) erwartet, gefunden {type(rules).__name__}"
        )
    try:
        rulebook = extract.load_rules(rules)
    except extract.ExtractionError as exc:
        raise SkeletonError(f"Regelwerk: {exc}") from exc

    technology = _technology(rules)
    root = _root_package(rules, package)

    # Beschreibungen je Stereotyp: das geparste Regelwerk traegt sie unter
    # ``notes``; extract.ElementStereotype bewusst nicht (nur Extraktion).
    raw_elements = rules.get("elementStereotypes")
    notes_by_name: dict[str, str] = {}
    if isinstance(raw_elements, Sequence) and not isinstance(raw_elements, (str, bytes)):
        for entry in raw_elements:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("name")
            note = entry.get("notes")
            if isinstance(name, str) and isinstance(note, str) and note.strip():
                notes_by_name[name] = note.strip()

    groups: dict[str, list[extract.ElementStereotype]] = {}
    for name in sorted(rulebook.elements, key=lambda item: (item.casefold(), item)):
        rule = rulebook.elements[name]
        metaclass = _primary_metaclass(rule) or OHNE_METAKLASSE
        groups.setdefault(metaclass, []).append(rule)

    package_by_stereotype: dict[str, str] = {}
    elements: list[dict[str, Any]] = []
    for metaclass in sorted(groups, key=lambda item: (item.casefold(), item)):
        package_path = f"{root}/{_segment(metaclass)}"
        for rule in groups[metaclass]:
            package_by_stereotype[rule.name] = package_path
            note = notes_by_name.get(rule.name) or _note(rule, technology)
            elements.append(
                {
                    "package": package_path,
                    "name": rule.name,
                    "stereotype": rule.name,
                    "ea_type": (
                        _primary_metaclass(rule) or extract.DEFAULT_ELEMENT_METACLASS
                    ),
                    "notes": note,
                }
            )

    connectors, skipped = _connector_plan(rulebook, package_by_stereotype)

    packages: list[dict[str, Any]] = [{"path": path} for path in _ancestors(root)]
    packages.extend(
        {"path": f"{root}/{_segment(metaclass)}"}
        for metaclass in sorted(groups, key=lambda item: (item.casefold(), item))
    )

    ir: dict[str, Any] = {
        "ir_version": extract.IR_VERSION,
        "packages": packages,
        "elements": elements,
        "connectors": connectors,
        "diagrams": [],
        "meta": {
            "quellen": {},
            "extraction": {
                "backend": SKELETON_BACKEND,
                "attempts": 0,
                "segments": 0,
                "documents": [],
                "dropped": [],
            },
            "skeleton": {
                "root": root,
                "metaclasses": len(groups),
                "elements": len(elements),
                "connectors": len(connectors),
                "connectorRulesSkipped": skipped,
                "source": technology,
            },
        },
    }
    if technology:
        ir["technology"] = technology
    return ir


# --------------------------------------------------------------------------
# CLI (nur Sichtpruefung; der Weg in die .qea ist ``eam-ai build``)
# --------------------------------------------------------------------------


def dumps_ir(ir: Mapping[str, Any]) -> str:
    """Kanonischer Text: sortierte Schluessel, zwei Leerzeichen, LF."""
    return json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    import mdg_parser

    parser = argparse.ArgumentParser(
        prog="skeleton.py",
        description="Geruest-IR allein aus einem MDG-Regelwerk bauen (ohne Text, ohne KI).",
    )
    parser.add_argument("mdg", type=Path, help="MDG-/Technologie-XML")
    parser.add_argument("-o", "--out", type=Path, help="Ziel-JSON (sonst stdout)")
    parser.add_argument("--package", default=None, help="Wurzelpaket (Default: Technologie-Name)")
    args = parser.parse_args(argv)

    try:
        rules = mdg_parser.parse_mdg(args.mdg)
        ir = build_skeleton(rules, package=args.package)
    except (mdg_parser.MdgParseError, SkeletonError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    text = dumps_ir(ir)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        skeleton = ir["meta"]["skeleton"]
        print(
            f"{args.out}: {skeleton['elements']} Elemente in "
            f"{skeleton['metaclasses']} Paketen, {skeleton['connectors']} Beziehungen",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
