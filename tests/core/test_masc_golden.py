"""Golden-Test gegen das echte Referenzmodell ``Musterarchitektur_MASC.qea``.

Was dieser Test beweist
----------------------
1. Der Reader verarbeitet ein echtes EA-Modell (226 Pakete, 1430 Elemente,
   1747 Kanten, 9236 Objekt-Tags, 949 Kanten-Tags) vollstaendig.
2. Der Writer schreibt daraus eine neue ``.qea``, die beim erneuten Lesen
   **null semantische Abweichungen** in Paketen, Elementen, Kanten, Namen,
   Stereotypen und Tags hat.
3. Dasselbe IR ergibt byte-identische Dateien (Determinismus).
4. Sichten werden bewusst nicht nachgebaut: 265 ``t_diagram`` gehen verloren.
   Der Report nennt diese und weitere bewusst nicht uebernommene Tabellen
   mit Quellzahl.

Was Byte-Identitaet hier *nicht* bedeutet
-----------------------------------------
Ein Build aus dem **re-gelesenen** IR ist nicht byte-gleich zum Build aus dem
Quell-IR: 38 Kantenpaare tragen eine andere ``#N``-Nummer, weil das IR keine
Objekt-GUID kennt und vollstaendig inhaltlich identische Duplikate
austauschbar sind. Der Test prueft deshalb beides getrennt:

* ``same_ir_builds_byte_identical``  -- gleiches IR, gleiche Bytes.
* ``semantic_equal``                -- Inhalt nach dem Neu-Schreiben identisch.
* ``literal ref changes``           -- jede Aenderung liegt in einer Gruppe
  inhaltlich identischer Duplikate.

Die Fixture ist lokal und wird nicht committet (siehe ``.gitignore``). Fehlt
sie, wird der Test mit klarer Begruendung uebersprungen -- nie stillschweigend
als Erfolg gewertet.

Aufruf als Skript (schreibt den Report, Exit 0 = PASS)::

    python3 tests/test_masc_golden.py
    python3 tests/test_masc_golden.py --report dist/masc_golden_report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qea_reader import ReadReport, read_qea_ex, semantic_equal, semantic_view
from qea_writer import render_bytes, write_qea

MASC = ROOT / "fixtures" / "Musterarchitektur_MASC.qea"
RUNTIME_LIMIT_SECONDS = 60.0

#: Am echten Modell validierte Sollzahlen. Aendert sich die Fixture, muss diese
#: Tabelle bewusst mitgezogen werden -- der Test schlaegt sonst laut fehl.
GOLDEN_REFERENCE: dict[str, Any] = {
    "packages": 226,
    "elements": 1430,          # ohne 225 Object_Type='Package'-Spiegel
    "connectors": 1747,
    "element_tags": 9157,
    "package_tags": 79,
    "object_tags": 9236,       # 9157 + 79 (9237 Zeilen, 1 identisches Duplikat)
    "connector_tags": 949,
    "diagrams": 265,           # bewusst nicht im IR
    "ignored_package_mirrors": 1,
    "technology_profile": "NAFv4-ADMBw",
    # Rohzahlen der Quelle (nur zur Erklaerung im Report):
    "t_object_rows": 1655,     # 1430 Elemente + 225 Spiegel
    "t_objectproperties_rows": 9237,
    "package_mirrors": 225,
    "root_packages": 2,
    "t_xref_rows": 3817,
    "stereo_rows": 2544,       # @STEREO-Zeilen
    "stereo_clients": 2523,    # Objekte mit Stereotyp
    "t_diagramobjects_rows": 2643,
    "t_diagramlinks_rows": 2660,
    "t_attribute_rows": 59,
}

#: Tabellen, die der Writer bewusst leer laesst, mit Grund: die Spalten stehen
#: (AAroN verlangt die Tabellen), aber ir_version 1 baut keine Inhalte dafuer.
LOST_TABLES: dict[str, str] = {
    "t_diagram": "Sichten sind bewusst nicht Teil des IR (Kartenentscheidung)",
    "t_diagramobjects": "Layout/Sichtinhalte werden nicht nachgebaut -- Tabelle existiert leer",
    "t_diagramlinks": "Layout/Sichtinhalte werden nicht nachgebaut -- Tabelle existiert leer",
    "t_attribute": "Attribute sind nicht Teil von ir_version 1 -- Tabelle existiert leer",
}

INTEGRITY_ZERO_CHECKS: tuple[str, ...] = (
    "dangling_connector_starts",
    "dangling_connector_ends",
    "mirrors_without_matching_package_guid",
    "duplicate_object_guids",
    "duplicate_package_guids",
    "orphan_object_tags",
    "orphan_connector_tags",
)


# --------------------------------------------------------------------------
# Kleine Helfer
# --------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(ir: Mapping[str, Any]) -> dict[str, int]:
    """Zaehlt die IR-Inhalte -- dieselbe Definition wie im Kartenauftrag."""
    element_tags = sum(len(e.get("tags", {})) for e in ir.get("elements", []))
    package_tags = sum(len(p.get("tags", {})) for p in ir.get("packages", []))
    connector_tags = sum(len(c.get("tags", {})) for c in ir.get("connectors", []))
    return {
        "packages": len(ir.get("packages", [])),
        "elements": len(ir.get("elements", [])),
        "connectors": len(ir.get("connectors", [])),
        "element_tags": element_tags,
        "package_tags": package_tags,
        "object_tags": element_tags + package_tags,
        "connector_tags": connector_tags,
    }


def _sqlite_stats(path: Path) -> dict[str, Any]:
    """Rohzahlen der Quelle: Tabellen, Doppel-Tags, Spiegel, Stereotype."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        wanted = (
            "t_package",
            "t_object",
            "t_objectproperties",
            "t_connector",
            "t_connectortag",
            "t_diagram",
            "t_diagramobjects",
            "t_diagramlinks",
            "t_attribute",
            "t_xref",
        )
        counts = {
            name: con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            if name in tables
            else None
            for name in wanted
        }
        details: dict[str, int] = {}
        if "t_objectproperties" in tables:
            details["tag_rows"] = counts["t_objectproperties"] or 0
            details["tag_pairs_distinct"] = con.execute(
                "SELECT COUNT(*) FROM "
                "(SELECT Object_ID, Property FROM t_objectproperties GROUP BY Object_ID, Property)"
            ).fetchone()[0]
        if "t_object" in tables:
            details["package_mirrors"] = con.execute(
                "SELECT COUNT(*) FROM t_object WHERE Object_Type='Package'"
            ).fetchone()[0]
            details["element_rows"] = con.execute(
                "SELECT COUNT(*) FROM t_object WHERE COALESCE(Object_Type,'')<>'Package'"
            ).fetchone()[0]
        if "t_package" in tables:
            details["root_packages"] = con.execute(
                "SELECT COUNT(*) FROM t_package WHERE Parent_ID=0"
            ).fetchone()[0]
        if "t_xref" in tables:
            details["xref_rows"] = counts["t_xref"] or 0
            details["stereo_rows"] = con.execute(
                "SELECT COUNT(*) FROM t_xref WHERE Description LIKE '@STEREO;%'"
            ).fetchone()[0]
            details["stereo_clients"] = con.execute(
                "SELECT COUNT(DISTINCT Client) FROM t_xref WHERE Description LIKE '@STEREO;%'"
            ).fetchone()[0]
        return {"counts": counts, "details": details}
    finally:
        con.close()


def _integrity(path: Path) -> dict[str, Any]:
    """Strukturpruefung der neu geschriebenen Datei (nicht nur Semantik)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        checks: dict[str, Any] = {
            "quick_check": con.execute("PRAGMA quick_check").fetchone()[0],
            "t_diagram_rows": con.execute("SELECT COUNT(*) FROM t_diagram").fetchone()[0],
            "dangling_connector_starts": con.execute(
                "SELECT COUNT(*) FROM t_connector c WHERE NOT EXISTS "
                "(SELECT 1 FROM t_object o WHERE o.Object_ID=c.Start_Object_ID)"
            ).fetchone()[0],
            "dangling_connector_ends": con.execute(
                "SELECT COUNT(*) FROM t_connector c WHERE NOT EXISTS "
                "(SELECT 1 FROM t_object o WHERE o.Object_ID=c.End_Object_ID)"
            ).fetchone()[0],
            "mirrors_without_matching_package_guid": con.execute(
                "SELECT COUNT(*) FROM t_object o WHERE o.Object_Type='Package' "
                "AND NOT EXISTS (SELECT 1 FROM t_package p WHERE p.ea_guid=o.ea_guid)"
            ).fetchone()[0],
            "duplicate_object_guids": con.execute(
                "SELECT COUNT(*) FROM (SELECT ea_guid FROM t_object GROUP BY ea_guid HAVING COUNT(*)>1)"
            ).fetchone()[0],
            "duplicate_package_guids": con.execute(
                "SELECT COUNT(*) FROM (SELECT ea_guid FROM t_package GROUP BY ea_guid HAVING COUNT(*)>1)"
            ).fetchone()[0],
            "orphan_object_tags": con.execute(
                "SELECT COUNT(*) FROM t_objectproperties t WHERE NOT EXISTS "
                "(SELECT 1 FROM t_object o WHERE o.Object_ID=t.Object_ID)"
            ).fetchone()[0],
            "orphan_connector_tags": con.execute(
                "SELECT COUNT(*) FROM t_connectortag t WHERE NOT EXISTS "
                "(SELECT 1 FROM t_connector c WHERE c.Connector_ID=t.ElementID)"
            ).fetchone()[0],
        }
        return checks
    finally:
        con.close()


# --------------------------------------------------------------------------
# Semantischer Vergleich (identitaetsfrei, ueber semantic_view)
# --------------------------------------------------------------------------


def _derive(view: Mapping[str, Any]) -> dict[str, Counter]:
    """Leitet aus der semantischen Sicht vergleichbare Multimengen ab.

    ``semantic_view`` normalisiert Defaults und loest Kanten-Referenzen auf den
    Elementinhalt auf. Genau deshalb ist es der richtige Massstab: eine
    ``#N``-Umnummerierung unter identischen Duplikaten erzeugt hier keine
    Abweichung, ein echter Datenverlust schon.
    """
    packages = view["packages"]
    elements = view["elements"]
    connectors = view["connectors"]
    # Layout von semantic_view: Paket 5 Felder (Tags an 4), Element/Kante 8
    # Felder (Tags an 7). Aendert der Reader das, soll der Test laut brechen.
    if packages and len(packages[0]) != 5:
        raise AssertionError("semantic_view: Paket-Token hat nicht 5 Felder")
    if elements and len(elements[0]) != 8:
        raise AssertionError("semantic_view: Element-Token hat nicht 8 Felder")
    if connectors and len(connectors[0]) != 8:
        raise AssertionError("semantic_view: Kanten-Token hat nicht 8 Felder")

    package_tags: Counter = Counter()
    for package in packages:
        for prop, value in package[4]:
            package_tags[(package[:4], prop, value)] += 1

    element_tags: Counter = Counter()
    for element in elements:
        for prop, value in element[7]:
            element_tags[(element[:7], prop, value)] += 1

    connector_tags: Counter = Counter()
    for connector in connectors:
        for prop, value in connector[7]:
            connector_tags[(connector[:7], prop, value)] += 1

    return {
        "packages": Counter(packages),
        "package_names": Counter(p[1] for p in packages),
        "package_stereotypes": Counter(p[3] for p in packages),
        "package_tags": package_tags,
        "elements": Counter(elements),
        "element_names": Counter(e[1] for e in elements),
        "element_stereotypes": Counter(e[2] for e in elements),
        "element_tags": element_tags,
        "connectors": Counter(connectors),
        "connections": Counter((c[0], c[1], c[2]) for c in connectors),
        "connector_stereotypes": Counter(c[2] for c in connectors),
        "connector_tags": connector_tags,
    }


def _deviation(left: Counter, right: Counter) -> dict[str, int]:
    only_left = left - right
    only_right = right - left
    missing = sum(only_left.values())
    extra = sum(only_right.values())
    return {"source_only": missing, "rebuilt_only": extra, "total": missing + extra}


def _compare(view_source: Mapping[str, Any], view_rebuilt: Mapping[str, Any]) -> dict[str, Any]:
    left = _derive(view_source)
    right = _derive(view_rebuilt)
    deviations: dict[str, Any] = {
        key: _deviation(left[key], right[key]) for key in sorted(left)
    }
    deviations["total"] = sum(item["total"] for item in deviations.values())
    return deviations


# --------------------------------------------------------------------------
# #N-Referenzen: nur unter inhaltlich identischen Duplikaten austauschbar
# --------------------------------------------------------------------------


def _content_key(element: Mapping[str, Any]) -> tuple[Any, ...]:
    """Exakt die kanonische Inhaltsreihenfolge aus ``qea_writer._element_index``."""
    return (
        element.get("ea_type", "Class"),
        element.get("notes", ""),
        element.get("alias", ""),
        element.get("status", ""),
        tuple(sorted(element.get("tags", {}).items())),
    )


def _element_groups(ir: Mapping[str, Any]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for element in ir.get("elements", []):
        groups[(element.get("package", ""), element.get("name", ""))].append(element)
    for members in groups.values():
        members.sort(key=_content_key)
    return dict(groups)


def _occurrence_info(
    ref: str, groups: Mapping[tuple[str, str], list[Mapping[str, Any]]]
) -> dict[str, Any] | None:
    """Beschreibt eine Element-Referenz mit ``#N``; ``None`` = keine Nummer."""
    if "::" not in ref:
        return None  # Kante am Paketspiegel
    package, rest = ref.rsplit("::", 1)
    name, occurrence = rest, None
    if (package, rest) not in groups:
        base, separator, number = rest.rpartition("#")
        if separator and number.isdigit():
            name, occurrence = base, int(number)
    if occurrence is None:
        return None
    members = groups.get((package, name))
    if not members:
        raise AssertionError(f"Referenz {ref!r} zeigt auf kein Element")
    if not 1 <= occurrence <= len(members):
        raise AssertionError(
            f"Referenz {ref!r}: Vorkommen {occurrence} fehlt (Gruppe hat {len(members)})"
        )
    token = _content_key(members[occurrence - 1])
    same_content = sum(1 for member in members if _content_key(member) == token)
    return {
        "package": package,
        "name": name,
        "occurrence": occurrence,
        "group_size": len(members),
        "same_content": same_content,
    }


def _element_token(element: Mapping[str, Any]) -> tuple[Any, ...]:
    """Normalisierter Elementinhalt -- exakt wie ``qea_reader.semantic_view``."""
    return (
        element.get("package", ""),
        element.get("name", ""),
        element.get("stereotype", ""),
        element.get("ea_type", "Class"),
        element.get("notes", ""),
        element.get("alias", ""),
        element.get("status", ""),
        tuple(sorted(element.get("tags", {}).items())),
    )


def _resolve_token(
    ref: str, groups: Mapping[tuple[str, str], list[Mapping[str, Any]]]
) -> tuple[str, Any]:
    """Loest eine Kanten-Referenz auf ihren Elementinhalt auf (wie semantic_view)."""
    if "::" not in ref:
        return ("package", ref)
    package, rest = ref.rsplit("::", 1)
    name, occurrence = rest, None
    if (package, rest) not in groups:
        base, separator, number = rest.rpartition("#")
        if separator and number.isdigit():
            name, occurrence = base, int(number)
    members = groups.get((package, name))
    if not members:
        raise AssertionError(f"Referenz {ref!r} zeigt auf kein Element")
    if occurrence is None:
        if len(members) != 1:
            raise AssertionError(f"Referenz {ref!r} ist mehrdeutig")
        element = members[0]
    else:
        if not 1 <= occurrence <= len(members):
            raise AssertionError(f"Referenz {ref!r}: Vorkommen {occurrence} fehlt")
        element = members[occurrence - 1]
    return ("element", _element_token(element))


def _connector_token(
    connector: Mapping[str, Any],
    groups: Mapping[tuple[str, str], list[Mapping[str, Any]]],
) -> tuple[Any, ...]:
    return (
        _resolve_token(connector["source"], groups),
        _resolve_token(connector["target"], groups),
        connector.get("stereotype", ""),
        connector.get("name", ""),
        connector.get("ea_type", "Dependency"),
        connector.get("direction", "Source -> Destination"),
        connector.get("notes", ""),
        tuple(sorted(connector.get("tags", {}).items())),
    )


def _connector_classes(
    ir: Mapping[str, Any],
    view: Mapping[str, Any],
    groups: Mapping[tuple[str, str], list[Mapping[str, Any]]],
) -> dict[tuple[Any, ...], list[tuple[str, str]]]:
    """Kanten nach aufgeloester Semantik gruppieren, literale Paare sammeln.

    ``semantic_view`` sortiert die Kanten; fuer die Zuordnung Literal<->Semantik
    wird der Token deshalb je Kante neu gebildet und gegen die Sicht geprueft.
    """
    classes: dict[tuple[Any, ...], list[tuple[str, str]]] = defaultdict(list)
    for connector in ir["connectors"]:
        token = _connector_token(connector, groups)
        classes[token].append((connector["source"], connector["target"]))
    if Counter({token: len(pairs) for token, pairs in classes.items()}) != Counter(
        view["connectors"]
    ):
        raise AssertionError("Kanten-Tokens weichen von semantic_view ab")
    return dict(classes)


def _check_renumbering(
    ir_source: Mapping[str, Any],
    ir_rebuilt: Mapping[str, Any],
    view_source: Mapping[str, Any],
    view_rebuilt: Mapping[str, Any],
) -> dict[str, Any]:
    """Prueft, dass jede literale Ref-Aenderung in einer Duplikatgruppe liegt.

    Innerhalb einer semantischen Kantenklasse (alle Attribute und aufgeloesten
    Endpunkte gleich) werden die literalen Paare verglichen. Nur Endpunkte, deren
    Vorkommen sich dadurch netto aendert, werden bewertet -- unveraenderte
    Endpunkte eines geaenderten Paares sind kein Renumbering.
    """
    groups_source = _element_groups(ir_source)
    groups_rebuilt = _element_groups(ir_rebuilt)
    classes_source = _connector_classes(ir_source, view_source, groups_source)
    classes_rebuilt = _connector_classes(ir_rebuilt, view_rebuilt, groups_rebuilt)
    if set(classes_source) != set(classes_rebuilt):
        raise AssertionError("semantische Kantenklassen unterscheiden sich bereits")

    changed_before: Counter = Counter()
    changed_after: Counter = Counter()
    endpoint_delta: Counter = Counter()
    for token, before_pairs in classes_source.items():
        after_pairs = classes_rebuilt[token]
        only_before = Counter(before_pairs) - Counter(after_pairs)
        only_after = Counter(after_pairs) - Counter(before_pairs)
        changed_before.update(only_before)
        changed_after.update(only_after)
        for pair, count in only_before.items():
            for ref in pair:
                endpoint_delta[ref] += count
        for pair, count in only_after.items():
            for ref in pair:
                endpoint_delta[ref] -= count

    unexplained: list[dict[str, Any]] = []
    checked = 0
    changed_texts = 0
    for ref, delta in endpoint_delta.items():
        if not delta:
            continue
        changed_texts += 1
        side = "source" if delta > 0 else "rebuilt"
        groups = groups_source if delta > 0 else groups_rebuilt
        info = _occurrence_info(ref, groups)
        if info is None:
            unexplained.append({"side": side, "ref": ref, "reason": "ohne #N"})
            continue
        checked += 1
        if info["same_content"] < 2:
            unexplained.append({"side": side, "ref": ref, **info})
    return {
        "changed_connector_ref_pairs": sum(changed_before.values()),
        "changed_connector_ref_pairs_rebuilt": sum(changed_after.values()),
        "changed_ref_texts": changed_texts,
        "numbered_refs_checked": checked,
        "unexplained_ref_changes": unexplained,
        "all_changes_between_identical_duplicates": not unexplained,
    }


# --------------------------------------------------------------------------
# Golden-Lauf
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GoldenRun:
    """Ergebnis eines vollstaendigen Lese-/Schreib-/Vergleichszyklus."""

    report: dict[str, Any]
    ir_source: dict[str, Any]
    ir_rebuilt: dict[str, Any]
    report_source: ReadReport
    report_rebuilt: ReadReport
    rebuilt_path: Path
    rebuilt_bytes: bytes
    reread_bytes: bytes


def run_golden(masc: Path | str = MASC, workdir: Path | str | None = None) -> GoldenRun:
    """Fuehrt den kompletten Golden-Zyklus aus und liefert Report + IRs.

    Der Quell-Fixture wird ausschliesslich lesend geoeffnet (Reader: ``mode=ro``,
    ``query_only``); seine sha256 wird vor und nach dem Lauf verglichen.
    """
    masc_path = Path(masc)
    if not masc_path.is_file():
        raise FileNotFoundError(
            f"Golden-Fixture fehlt: {masc_path} -- die Datei ist lokal zu halten "
            "und wird nicht committet (siehe .gitignore)"
        )
    workdir_path = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="masc_golden_"))
    workdir_path.mkdir(parents=True, exist_ok=True)
    rebuilt_path = workdir_path / "Musterarchitektur_MASC_rebuilt.qea"
    reread_path = workdir_path / "Musterarchitektur_MASC_rebuilt_from_reread.qea"

    started = time.perf_counter()
    source_hash_before = _sha256_file(masc_path)
    source_bytes = masc_path.stat().st_size

    clock = time.perf_counter()
    ir_source, report_source = read_qea_ex(masc_path)
    read_s = time.perf_counter() - clock

    clock = time.perf_counter()
    write_qea(ir_source, rebuilt_path)
    rebuilt_bytes = rebuilt_path.read_bytes()
    write_s = time.perf_counter() - clock

    clock = time.perf_counter()
    ir_rebuilt, report_rebuilt = read_qea_ex(rebuilt_path)
    reread_s = time.perf_counter() - clock

    clock = time.perf_counter()
    render_first = render_bytes(ir_source)
    render_second = render_bytes(ir_source)
    render_s = time.perf_counter() - clock

    write_qea(ir_rebuilt, reread_path)
    reread_bytes = reread_path.read_bytes()

    source_hash_after = _sha256_file(masc_path)

    view_source = semantic_view(ir_source)
    view_rebuilt = semantic_view(ir_rebuilt)
    source_equals_rebuilt = view_source == view_rebuilt
    deviations = _compare(view_source, view_rebuilt)
    renumbering = _check_renumbering(ir_source, ir_rebuilt, view_source, view_rebuilt)

    integrity = _integrity(rebuilt_path)
    source_stats = _sqlite_stats(masc_path)
    rebuilt_stats = _sqlite_stats(rebuilt_path)

    counts_source = _counts(ir_source)
    counts_rebuilt = _counts(ir_rebuilt)
    source_diagrams = report_source.diagrams

    losses = {
        table: {
            "source": source_stats["counts"].get(table),
            "rebuilt": rebuilt_stats["counts"].get(table),
            "reason": reason,
        }
        for table, reason in LOST_TABLES.items()
    }
    losses["t_diagram"]["lost"] = source_diagrams

    # t_object: 1430 Elemente + 224 schreibbare Spiegel = 1654; die Quelle hat
    # 225 Spiegel, davon 1 Waise ohne zuordenbares t_package.
    expected_mirrors = GOLDEN_REFERENCE["packages"] - source_stats["details"]["root_packages"]
    losses["package_mirror_orphans"] = {
        "source_mirrors": source_stats["details"].get("package_mirrors"),
        "expected_writable_mirrors": expected_mirrors,
        "rebuilt_mirrors": rebuilt_stats["details"].get("package_mirrors"),
        "lost": (source_stats["details"].get("package_mirrors") or 0) - expected_mirrors,
        "reason": (
            "Waisen-Paketspiegel (Object_ID 2048, 'TestArchitektur_Verbindungstest', "
            "PDATA1 leer, GUID nicht in t_package) wird bewusst nicht als Element "
            "gefuehrt; kein Elementverlust"
        ),
    }

    tag_rows = source_stats["details"]["tag_rows"]
    tag_pairs = source_stats["details"]["tag_pairs_distinct"]
    losses["duplicate_tag_rows"] = {
        "source_rows": tag_rows,
        "rebuilt_rows": rebuilt_stats["counts"]["t_objectproperties"],
        "collapsed": tag_rows - tag_pairs,
        "reason": (
            "identische Doppelzeile (Object_ID 1901, Property 'URI', Wert NULL) "
            "kollabiert im IR-Dict verlustfrei zu einem Tag"
        ),
    }

    stereo_rows = source_stats["details"]["stereo_rows"]
    stereo_clients = source_stats["details"]["stereo_clients"]
    losses["t_xref"] = {
        "source_rows": source_stats["details"]["xref_rows"],
        "rebuilt_rows": rebuilt_stats["counts"]["t_xref"],
        "stereotype_rows_source": stereo_rows,
        "stereotype_clients": stereo_clients,
        "multi_stereotype_extra_rows": stereo_rows - stereo_clients,
        "non_stereotype_rows": source_stats["details"]["xref_rows"] - stereo_rows,
        "reason": (
            "IR fuehrt genau einen Stereotyp je Objekt (t_object.Stereotype); "
            "Mehrfachstereotype und Nicht-Stereotyp-xrefs (Eigenschaften, "
            "Diagramm, DGS) sind nicht Teil von ir_version 1"
        ),
    }

    # Alles, was der Golden-Test tut, zaehlt in die Laufzeit -- inklusive
    # semantischem Vergleich, Renumbering-Pruefung, Integritaet und Report.
    total_s = time.perf_counter() - started
    runtime = {
        "read_s": round(read_s, 3),
        "write_s": round(write_s, 3),
        "reread_s": round(reread_s, 3),
        "render_s": round(render_s, 3),
        "total_s": round(total_s, 3),
        "limit_s": RUNTIME_LIMIT_SECONDS,
        "within_limit": total_s < RUNTIME_LIMIT_SECONDS,
    }

    identity = {
        "source_sha256": source_hash_before,
        "source_bytes": source_bytes,
        "source_unchanged": source_hash_before == source_hash_after,
        "rebuilt_bytes": len(rebuilt_bytes),
        "rebuilt_sha256": _sha256_bytes(rebuilt_bytes),
        "same_ir_builds_byte_identical": render_first == render_second == rebuilt_bytes,
        "written_file_equals_render_bytes": rebuilt_bytes == render_first,
        "build_from_reread_byte_identical": rebuilt_bytes == reread_bytes,
        "build_from_reread_semantic_equal": source_equals_rebuilt,
        **renumbering,
    }

    integrity_ok = integrity["quick_check"] == "ok" and all(
        integrity[key] == 0 for key in INTEGRITY_ZERO_CHECKS
    )
    verdict = "PASS" if (
        deviations["total"] == 0
        and source_equals_rebuilt
        and identity["same_ir_builds_byte_identical"]
        and identity["written_file_equals_render_bytes"]
        and identity["source_unchanged"]
        and renumbering["all_changes_between_identical_duplicates"]
        and integrity_ok
        and runtime["within_limit"]
    ) else "FAIL"

    report: dict[str, Any] = {
        "schema": {"name": "masc-golden-report", "version": 1},
        "fixture": {
            "path": str(masc_path),
            "bytes": source_bytes,
            "sha256": source_hash_before,
        },
        "golden_reference": GOLDEN_REFERENCE,
        "source": {
            "counts": counts_source,
            "read_report": report_source.as_dict(),
            "sqlite": source_stats,
        },
        "rebuilt": {
            "counts": counts_rebuilt,
            "read_report": report_rebuilt.as_dict(),
            "sqlite": rebuilt_stats,
            "path": str(rebuilt_path),
            "integrity": integrity,
        },
        "deviations": deviations,
        "losses": losses,
        "identity": identity,
        "runtime": runtime,
        "verdict": verdict,
    }
    return GoldenRun(
        report=report,
        ir_source=ir_source,
        ir_rebuilt=ir_rebuilt,
        report_source=report_source,
        report_rebuilt=report_rebuilt,
        rebuilt_path=rebuilt_path,
        rebuilt_bytes=rebuilt_bytes,
        reread_bytes=reread_bytes,
    )


# --------------------------------------------------------------------------
# Report schreiben / formatieren
# --------------------------------------------------------------------------


def write_report(report: Mapping[str, Any], path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def format_summary(report: Mapping[str, Any]) -> str:
    source = report["source"]["counts"]
    rebuilt = report["rebuilt"]["counts"]
    deviations = report["deviations"]
    losses = report["losses"]
    identity = report["identity"]
    runtime = report["runtime"]

    def dev(*keys: str) -> int:
        return sum(deviations[key]["total"] for key in keys)

    lines = [
        "MASC Golden-Test (echtes Referenzmodell)",
        f"Fixture: {report['fixture']['path']} "
        f"({report['fixture']['bytes']:,} B, sha256 {report['fixture']['sha256'][:16]}...)",
        "",
        f"Quelle:  {source['packages']} Pakete, {source['elements']} Elemente, "
        f"{source['connectors']} Kanten, {source['object_tags']} Objekt-Tags, "
        f"{source['connector_tags']} Kanten-Tags, {report['source']['read_report']['diagrams']} Sichten",
        f"Neu:     {rebuilt['packages']} Pakete, {rebuilt['elements']} Elemente, "
        f"{rebuilt['connectors']} Kanten, {rebuilt['object_tags']} Objekt-Tags, "
        f"{rebuilt['connector_tags']} Kanten-Tags, "
        f"{report['rebuilt']['read_report']['diagrams']} Sichten",
        "",
        f"Abweichungen: {deviations['total']} "
        f"(Pakete {dev('packages')}, Elemente {dev('elements')}, Kanten {dev('connectors')}, "
        f"Namen {dev('package_names', 'element_names')}, "
        f"Stereotype {dev('package_stereotypes', 'element_stereotypes', 'connector_stereotypes')}, "
        f"Tags {dev('package_tags', 'element_tags', 'connector_tags')})",
        f"Verbindungen (Quelle->Ziel+Stereotyp): {dev('connections')} Abweichungen",
        "",
        f"Bewusst nicht im IR: {losses['t_diagram']['source']} t_diagram, "
        f"{losses['t_diagramobjects']['source']} t_diagramobjects, "
        f"{losses['t_diagramlinks']['source']} t_diagramlinks, "
        f"{losses['t_attribute']['source']} t_attribute, "
        f"{losses['package_mirror_orphans']['lost']} Waisen-Spiegel, "
        f"{losses['duplicate_tag_rows']['collapsed']} identische Doppel-Tag-Zeile",
        "",
        f"Byte-Identitaet: gleiches IR -> gleiche Bytes "
        f"({identity['same_ir_builds_byte_identical']}), "
        f"Datei == render_bytes: {identity['written_file_equals_render_bytes']}",
        f"Build aus re-gelesenem IR: byte-gleich "
        f"{identity['build_from_reread_byte_identical']}, "
        f"{identity['changed_connector_ref_pairs']} Kantenpaare mit anderer #N-Referenz, "
        f"alle in identischen Duplikaten: "
        f"{identity['all_changes_between_identical_duplicates']}",
        f"Semantisch gleich: {identity['build_from_reread_semantic_equal']}",
        "",
        f"Integritaet: {report['rebuilt']['integrity']['quick_check']}, "
        f"t_diagram={report['rebuilt']['integrity']['t_diagram_rows']}",
        f"Laufzeit: {runtime['total_s']} s (Grenze {runtime['limit_s']:.0f} s)",
        "",
        f"Ergebnis: {report['verdict']}",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden-Test gegen Musterarchitektur_MASC.qea")
    parser.add_argument("--fixture", default=str(MASC), help="Pfad zur .qea-Fixture")
    parser.add_argument(
        "--report",
        default=str(ROOT / "dist" / "masc_golden_report.json"),
        help="Zielpfad des JSON-Reports",
    )
    args = parser.parse_args(argv)
    try:
        run = run_golden(Path(args.fixture))
    except FileNotFoundError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    write_report(run.report, Path(args.report))
    print(format_summary(run.report))
    print(f"\nReport: {Path(args.report).resolve()}")
    print(f"Neu geschrieben: {run.rebuilt_path}")
    return 0 if run.report["verdict"] == "PASS" else 1


# --------------------------------------------------------------------------
# pytest
# --------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not MASC.is_file(),
    reason=(
        f"Golden-Fixture {MASC} fehlt -- sie ist lokal zu halten und wird "
        "bewusst nicht committet (siehe .gitignore)"
    ),
)


@pytest.fixture(scope="session")
def golden(tmp_path_factory: pytest.TempPathFactory) -> GoldenRun:
    return run_golden(MASC, tmp_path_factory.mktemp("masc_golden"))


def test_fixture_is_present_and_unmodified(golden: GoldenRun) -> None:
    report = golden.report
    assert report["fixture"]["bytes"] > 0
    assert report["fixture"]["sha256"] == _sha256_file(MASC)
    assert report["identity"]["source_unchanged"] is True


def test_source_matches_documented_golden_reference(golden: GoldenRun) -> None:
    source = golden.report["source"]
    counts = source["counts"]
    for key in (
        "packages",
        "elements",
        "connectors",
        "element_tags",
        "package_tags",
        "object_tags",
        "connector_tags",
    ):
        assert counts[key] == GOLDEN_REFERENCE[key], f"{key}: {counts[key]}"
    read_report = source["read_report"]
    assert read_report["diagrams"] == GOLDEN_REFERENCE["diagrams"]
    assert read_report["ignored_package_mirrors"] == GOLDEN_REFERENCE["ignored_package_mirrors"]
    assert read_report["technology_profile"] == GOLDEN_REFERENCE["technology_profile"]
    sqlite_counts = source["sqlite"]["counts"]
    assert sqlite_counts["t_object"] == GOLDEN_REFERENCE["t_object_rows"]
    assert sqlite_counts["t_objectproperties"] == GOLDEN_REFERENCE["t_objectproperties_rows"]
    assert sqlite_counts["t_diagramobjects"] == GOLDEN_REFERENCE["t_diagramobjects_rows"]
    assert sqlite_counts["t_diagramlinks"] == GOLDEN_REFERENCE["t_diagramlinks_rows"]
    assert sqlite_counts["t_attribute"] == GOLDEN_REFERENCE["t_attribute_rows"]
    assert sqlite_counts["t_xref"] == GOLDEN_REFERENCE["t_xref_rows"]
    assert source["sqlite"]["details"]["package_mirrors"] == GOLDEN_REFERENCE["package_mirrors"]
    assert source["sqlite"]["details"]["root_packages"] == GOLDEN_REFERENCE["root_packages"]
    assert source["sqlite"]["details"]["stereo_rows"] == GOLDEN_REFERENCE["stereo_rows"]
    assert source["sqlite"]["details"]["stereo_clients"] == GOLDEN_REFERENCE["stereo_clients"]


def test_roundtrip_has_zero_deviations(golden: GoldenRun) -> None:
    deviations = golden.report["deviations"]
    assert deviations["total"] == 0, json.dumps(deviations, indent=2, ensure_ascii=False)
    for key, item in deviations.items():
        if key == "total":
            continue
        assert item["total"] == 0, f"{key}: {item}"
    assert golden.report["identity"]["build_from_reread_semantic_equal"] is True
    assert semantic_equal(golden.ir_source, golden.ir_rebuilt) is True


def test_rebuilt_counts_and_integrity(golden: GoldenRun) -> None:
    source = golden.report["source"]["counts"]
    rebuilt = golden.report["rebuilt"]["counts"]
    for key in ("packages", "elements", "connectors", "element_tags", "package_tags", "object_tags", "connector_tags"):
        assert rebuilt[key] == source[key], f"{key}: {rebuilt[key]} != {source[key]}"
    integrity = golden.report["rebuilt"]["integrity"]
    assert integrity["quick_check"] == "ok"
    for key in INTEGRITY_ZERO_CHECKS:
        assert integrity[key] == 0, f"{key}={integrity[key]}"
    assert integrity["t_diagram_rows"] == 0
    assert golden.report["rebuilt"]["read_report"]["diagrams"] == 0


def test_diagrams_are_reported_as_lost(golden: GoldenRun) -> None:
    losses = golden.report["losses"]
    assert losses["t_diagram"]["source"] == GOLDEN_REFERENCE["diagrams"] == 265
    assert losses["t_diagram"]["rebuilt"] == 0
    assert losses["t_diagram"]["lost"] == 265
    assert "bewusst" in losses["t_diagram"]["reason"].lower()
    assert losses["t_diagramobjects"]["source"] == GOLDEN_REFERENCE["t_diagramobjects_rows"]
    # Die Tabelle existiert (AAroN-Pflicht), bleibt aber leer: kein Layout im IR.
    assert losses["t_diagramobjects"]["rebuilt"] == 0
    assert losses["t_diagramlinks"]["source"] == GOLDEN_REFERENCE["t_diagramlinks_rows"]
    assert losses["t_diagramlinks"]["rebuilt"] == 0
    assert losses["t_attribute"]["source"] == GOLDEN_REFERENCE["t_attribute_rows"]
    assert losses["t_attribute"]["rebuilt"] == 0
    assert losses["package_mirror_orphans"]["lost"] == 1
    assert losses["duplicate_tag_rows"]["collapsed"] == 1
    assert losses["t_xref"]["multi_stereotype_extra_rows"] == 21
    assert losses["t_xref"]["non_stereotype_rows"] == 1273


def test_byte_determinism_and_documented_limit(golden: GoldenRun) -> None:
    identity = golden.report["identity"]
    assert identity["same_ir_builds_byte_identical"] is True
    assert identity["written_file_equals_render_bytes"] is True
    assert identity["rebuilt_bytes"] == len(golden.rebuilt_bytes)
    assert identity["rebuilt_sha256"] == _sha256_bytes(golden.rebuilt_bytes)
    # Dokumentierte Grenze: das IR kennt keine Objekt-GUID, daher tragen beim
    # Neu-Schreiben 38 Kantenpaare eine andere #N-Nummer -- semantisch folgenlos.
    assert identity["build_from_reread_byte_identical"] is False
    assert identity["changed_connector_ref_pairs"] == 38
    assert identity["changed_connector_ref_pairs_rebuilt"] == 38
    assert identity["build_from_reread_semantic_equal"] is True


def test_literal_ref_changes_only_between_identical_duplicates(golden: GoldenRun) -> None:
    identity = golden.report["identity"]
    assert identity["unexplained_ref_changes"] == []
    assert identity["all_changes_between_identical_duplicates"] is True
    assert identity["numbered_refs_checked"] > 0


def test_runtime_under_60_seconds(golden: GoldenRun) -> None:
    runtime = golden.report["runtime"]
    assert runtime["within_limit"] is True
    assert runtime["total_s"] < RUNTIME_LIMIT_SECONDS
    # Kein 0-Sekunden-"Erfolg": alle Phasen muessen tatsaechlich gelaufen sein.
    for key in ("read_s", "write_s", "reread_s", "render_s"):
        assert runtime[key] > 0.0, f"{key} wurde nicht gemessen"


def test_report_contract(golden: GoldenRun, tmp_path: Path) -> None:
    report = golden.report
    assert report["verdict"] == "PASS"
    assert report["deviations"]["total"] == 0
    text = format_summary(report)
    assert "Abweichungen: 0" in text
    assert "265 t_diagram" in text
    assert "Ergebnis: PASS" in text
    target = write_report(report, tmp_path / "report.json")
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == json.loads(json.dumps(report, ensure_ascii=False))
    assert loaded["schema"]["name"] == "masc-golden-report"


def test_main_via_cli(tmp_path: Path) -> None:
    """Der Skript-Pfad (``python3 tests/test_masc_golden.py``) liefert Exit 0."""
    report_path = tmp_path / "cli_report.json"
    assert main(["--fixture", str(MASC), "--report", str(report_path)]) == 0
    assert report_path.is_file()
    loaded = json.loads(report_path.read_text(encoding="utf-8"))
    assert loaded["verdict"] == "PASS"
    assert loaded["deviations"]["total"] == 0


if __name__ == "__main__":  # pragma: no cover - Skriptpfad
    sys.exit(main())
