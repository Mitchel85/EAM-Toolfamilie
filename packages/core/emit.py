#!/usr/bin/env python3
"""emit.py -- IR zu .qea inklusive Herkunft.

Zweck
-----
Nimmt ein IR nach ``IR_SPEC.md`` (aus ``extract.py``, ``table_import.py`` oder
``qea_reader.py``) und schreibt daraus eine .qea. Neben der Datei entsteht die
Begleitdatei ``quellen.json``: Beleg-ID -> Absatztext.

Herkunft (Provenance)
---------------------
Ein KI-Objekt -- Element oder Beziehung -- traegt im IR genau drei Tagged
Values::

    source_ref         "D1-S14"   Absatz, in dem der Inhalt belegt ist
    source_doc         "D1"       Dokument des Belegs
    source_confidence  "0.85"     Sicherheit, zwei Nachkommastellen

Erkennungsmerkmal ist ``source_ref``. Objekte ohne diese drei Tags sind
importiert: sie bleiben unveraendert, dieses Modul legt keine Herkunft an und
entfernt auch keine fremden Tags.

Groessenbudget
--------------
Die Tags sind Verweise, kein Volltext: hoechstens ``MAX_TAG_VALUE_CHARS``
Zeichen je Wert. Der Satz selbst steht ausschliesslich in ``quellen.json``,
nie im Tag. Dadurch bleibt die .qea klein und die Belegkette eindeutig.

Laut statt still
----------------
Der Export bricht ab bei: halber Herkunft (ein oder zwei von drei Tags),
leerem oder zu langem Tagwert, Belegnummer ausserhalb ``D<n>-S<n>``,
``source_doc`` passt nicht zu ``source_ref``, ``source_confidence`` nicht
kanonisch ``0.00`` bis ``1.00``, Beleg-ID ohne Satz in ``meta.quellen`` oder
explizit angeforderter Begleitdatei ohne jede Herkunft. Nach dem Schreiben
wird die .qea zurueckgelesen und die Herkunft verglichen; jede Abweichung
bricht laut ab, bevor die Zieldatei an ihren Platz wandert.

Determinismus
-------------
Gleiches IR -> gleiche Bytes in .qea und ``quellen.json``. Keine Zeitstempel,
keine Zufalls-IDs; ``quellen.json`` ist UTF-8, LF, zwei Leerzeichen
Einrueckung und natuerlich sortiert (``D1-S2`` vor ``D1-S10``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, NoReturn, Sequence

from qea_reader import QeaReaderError, read_qea
from qea_writer import QeaWriterError, load_ir, write_qea

TAG_SOURCE_REF = "source_ref"
TAG_SOURCE_DOC = "source_doc"
TAG_CONFIDENCE = "source_confidence"
PROVENANCE_TAGS: tuple[str, ...] = (TAG_SOURCE_REF, TAG_SOURCE_DOC, TAG_CONFIDENCE)

#: Groessenbudget je Tagwert. Herkunft ist ein Verweis; der Satz steht in
#: ``quellen.json``. Ein Volltext-Tag wuerde die .qea aufblaehen.
MAX_TAG_VALUE_CHARS = 120

#: Belegnummer: Dokument D1..Dn, Absatz S1..Sn.
REF_PATTERN = re.compile(r"^(D[1-9][0-9]*)-(S[1-9][0-9]*)$")

#: Kanonische Sicherheit: zwei Nachkommastellen, 0.00 bis 1.00.
CONFIDENCE_PATTERN = re.compile(r"^(?:0\.[0-9]{2}|1\.00)$")

DEFAULT_QUELLEN_NAME = "quellen.json"


class EmitError(ValueError):
    """Herkunft oder Ausgabe verletzen den Vertrag -- Export bricht laut ab."""


@dataclass(frozen=True)
class Provenance:
    """Herkunft eines Objekts, wie sie im IR steht."""

    kind: str  # "Paket", "Element" oder "Beziehung"
    label: str
    tags: Mapping[str, str]


@dataclass(frozen=True)
class EmitReport:
    """Ergebnis eines Exports. Zahlen statt Vermutungen."""

    qea: Path
    quellen: Path | None
    packages: int
    elements: int
    connectors: int
    tagged_objects: int
    tagged_elements: int
    tagged_connectors: int
    provenance_tags: int
    refs: int
    unused_quellen: int
    digest: str
    verified: bool


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def _fail(message: str) -> NoReturn:
    raise EmitError(message)


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        _fail(f"{what}: Objekt erwartet, gefunden {type(value).__name__}")
    return value


def _iter_objects(ir: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """Alle Objekte mit Tags: Pakete, Elemente, Beziehungen.

    Defensiv: strukturell kaputte Eintraege werden uebersprungen; der Writer
    meldet sie anschliessend praezise. Hier geht es nur um die Herkunft.
    """
    for package in ir.get("packages") or ():
        if isinstance(package, Mapping):
            yield "Paket", str(package.get("path", "")), package
    for element in ir.get("elements") or ():
        if isinstance(element, Mapping):
            label = f"{element.get('package', '')}::{element.get('name', '')}"
            yield "Element", label, element
    for connector in ir.get("connectors") or ():
        if isinstance(connector, Mapping):
            label = f"{connector.get('source', '')} -> {connector.get('target', '')}"
            yield "Beziehung", label, connector


def _raw_provenance(obj: Mapping[str, Any]) -> dict[str, str]:
    """Nur die vorhandenen Herkunfts-Tags, ohne Pruefung (fuer den Vergleich)."""
    tags = obj.get("tags")
    if not isinstance(tags, Mapping):
        return {}
    return {name: str(tags[name]) for name in PROVENANCE_TAGS if name in tags}


def _ref_order(ref: str) -> tuple[int, int]:
    match = REF_PATTERN.fullmatch(ref)
    if match is None:
        _fail(f"Beleg {ref!r} ist keine Nummer D<n>-S<n>")
    return int(match.group(1)[1:]), int(match.group(2)[1:])


def _stamp(where: str, obj: Mapping[str, Any]) -> dict[str, str]:
    """Liest und prueft die drei Herkunfts-Tags eines Objekts.

    Rueckgabe: die drei Werte oder ``{}``, wenn das Objekt importiert ist.
    Jede halbe oder falsch geformte Herkunft ist ein lauter Fehler.
    """
    tags = obj.get("tags")
    if tags is None:
        return {}
    if not isinstance(tags, Mapping):
        _fail(f"{where}: tags muss ein Objekt sein, gefunden {type(tags).__name__}")
    present = [name for name in PROVENANCE_TAGS if name in tags]
    if not present:
        return {}
    missing = [name for name in PROVENANCE_TAGS if name not in tags]
    if missing:
        _fail(
            f"{where}: unvollstaendige Herkunft -- {present} gesetzt, "
            f"{missing} fehlen. Herkunft gilt komplett (drei Tags) oder gar nicht."
        )

    values: dict[str, str] = {}
    for name in PROVENANCE_TAGS:
        value = tags[name]
        if not isinstance(value, str):
            _fail(f"{where}: Tag {name!r} muss Zeichenkette sein, gefunden {type(value).__name__}")
        if not value:
            _fail(f"{where}: Tag {name!r} ist leer")
        if len(value) > MAX_TAG_VALUE_CHARS:
            _fail(
                f"{where}: Tag {name!r} hat {len(value)} Zeichen, "
                f"Budget {MAX_TAG_VALUE_CHARS} -- kein Volltext im Tag"
            )
        values[name] = value

    match = REF_PATTERN.fullmatch(values[TAG_SOURCE_REF])
    if match is None:
        _fail(
            f"{where}: source_ref {values[TAG_SOURCE_REF]!r} ist keine Belegnummer "
            "D<n>-S<n> -- der Tag traegt nur den Verweis, nie den Satz"
        )
    document = match.group(1)
    if values[TAG_SOURCE_DOC] != document:
        _fail(
            f"{where}: source_doc {values[TAG_SOURCE_DOC]!r} passt nicht zu "
            f"source_ref {values[TAG_SOURCE_REF]!r} (erwartet {document!r})"
        )
    if CONFIDENCE_PATTERN.fullmatch(values[TAG_CONFIDENCE]) is None:
        _fail(
            f"{where}: source_confidence {values[TAG_CONFIDENCE]!r} ist nicht "
            "kanonisch 0.00..1.00 mit genau zwei Nachkommastellen"
        )
    return values


def collect_provenance(
    ir: Mapping[str, Any],
) -> tuple[tuple[Provenance, ...], dict[str, str]]:
    """Prueft die Herkunft des ganzen IR und liefert (Objekte, Belegtexte).

    ``Belegtexte`` enthaelt nur tatsaechlich referenzierte IDs, in natuerlicher
    Reihenfolge. Fehlt ein referenzierter Satz, bricht der Export ab.
    """
    entries: list[Provenance] = []
    for kind, label, obj in _iter_objects(ir):
        stamps = _stamp(f"{kind} {label or '<ohne Namen>'}", obj)
        if stamps:
            entries.append(Provenance(kind=kind, label=label, tags=stamps))

    refs = {entry.tags[TAG_SOURCE_REF] for entry in entries}
    quellen = _quellen_from_meta(ir, refs) if refs else {}
    return tuple(entries), quellen


def _quellen_from_meta(ir: Mapping[str, Any], refs: set[str]) -> dict[str, str]:
    meta = _mapping(ir.get("meta"), "meta")
    table = _mapping(meta.get("quellen"), "meta.quellen")
    missing = sorted(refs - set(table), key=_ref_order)
    if missing:
        _fail(
            f"meta.quellen: kein Satz fuer {missing} -- die Belegkette waere "
            "unvollstaendig (quellen.json wuerde auf nichts zeigen)"
        )
    quellen: dict[str, str] = {}
    for ref in sorted(refs, key=_ref_order):
        text = table[ref]
        if not isinstance(text, str):
            _fail(f"meta.quellen[{ref!r}]: Zeichenkette erwartet, gefunden {type(text).__name__}")
        if not text.strip():
            _fail(f"meta.quellen[{ref!r}]: leerer Satz -- Beleg ohne Inhalt")
        quellen[ref] = text
    return quellen


def provenance_signature(
    ir: Mapping[str, Any],
) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    """Vergleichbare Herkunfts-Signatur: (Objektart, sortierte Tag-Paare)."""
    rows: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for kind, _label, obj in _iter_objects(ir):
        stamps = _raw_provenance(obj)
        if stamps:
            rows.append((kind, tuple(sorted(stamps.items()))))
    return sorted(rows)


def verify_qea_provenance(qea_path: str | os.PathLike[str], ir: Mapping[str, Any]) -> int:
    """Liest die .qea zurueck und vergleicht die Herkunft mit dem IR.

    Rueckgabe: Anzahl der Objekte mit Herkunft. Abweichung -> EmitError.
    """
    expected = provenance_signature(ir)
    try:
        written = read_qea(str(qea_path))
    except QeaReaderError as error:
        _fail(f"Ruecklesung: {error}")
    actual = provenance_signature(written)
    if expected != actual:
        fehlend = Counter(expected) - Counter(actual)
        zusaetzlich = Counter(actual) - Counter(expected)
        _fail(
            "Ruecklesung: Herkunft weicht ab -- "
            f"erwartet {len(expected)} Objekte, gefunden {len(actual)}; "
            f"fehlend {list(fehlend.elements())[:3]}, "
            f"zusaetzlich {list(zusaetzlich.elements())[:3]}"
        )
    return len(actual)


def render_quellen(quellen: Mapping[str, str]) -> str:
    """Kanonisches JSON: natuerlich sortiert, UTF-8, LF, zwei Leerzeichen."""
    ordered = {ref: quellen[ref] for ref in sorted(quellen, key=_ref_order)}
    return json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"


def write_quellen(quellen: Mapping[str, str], path: str | os.PathLike[str]) -> Path:
    """Schreibt die Begleitdatei atomar (temp + replace)."""
    target = Path(path)
    if not quellen:
        _fail("quellen: leere Begleitdatei wird nicht geschrieben (kein leerer Erfolg)")
    data = render_quellen(quellen)
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
        )
    except OSError as error:
        _fail(f"quellen: {str(target)!r} nicht schreibbar ({error})")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def _stage_path(target: Path) -> Path:
    """Frischer .qea-Pfad neben dem Ziel; erst nach der Pruefung wird getauscht."""
    try:
        fd, name = tempfile.mkstemp(prefix=target.name + ".",
                                    suffix=".qea", dir=str(target.parent))
    except OSError as error:
        _fail(f"Ziel {str(target)!r}: nicht schreibbar ({error})")
    os.close(fd)
    return Path(name)


def _count(ir: Mapping[str, Any], key: str) -> int:
    value = ir.get(key)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    return 0


def _quellen_total(ir: Mapping[str, Any]) -> int:
    """Anzahl Absaetze in ``meta.quellen``; defensiv, nur fuer den Report."""
    meta = ir.get("meta")
    if not isinstance(meta, Mapping):
        return 0
    table = meta.get("quellen")
    if not isinstance(table, Mapping):
        return 0
    return len(table)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def emit(
    ir: "Mapping[str, Any] | str | os.PathLike[str]",
    target: str | os.PathLike[str],
    *,
    quellen_path: str | os.PathLike[str] | None = None,
    sidecar: bool = True,
    verify: bool = True,
) -> EmitReport:
    """Schreibt eine .qea und (bei vorhandener Herkunft) ``quellen.json``.

    Reihenfolge: Herkunft pruefen -> .qea in eine Nachbardatei schreiben ->
    zuruecklesen und vergleichen -> Zieldatei ersetzen -> Begleitdatei
    schreiben. Bei einem Fehler bleibt die Zieldatei unberuehrt.
    """
    if isinstance(ir, (str, os.PathLike)):
        ir = load_ir(ir)
    if not isinstance(ir, Mapping):
        _fail(f"IR: Objekt erwartet, gefunden {type(ir).__name__}")

    entries, quellen = collect_provenance(ir)

    target_path = Path(target)
    if target_path.suffix.lower() != ".qea":
        _fail(f"Ziel {str(target_path)!r} hat nicht die Endung .qea")

    sidecar_target: Path | None = None
    if sidecar and quellen:
        sidecar_target = (
            Path(quellen_path)
            if quellen_path is not None
            else target_path.parent / DEFAULT_QUELLEN_NAME
        )
        if sidecar_target.resolve() == target_path.resolve():
            _fail("quellen: Begleitdatei und .qea sind derselbe Pfad")
        if sidecar_target.is_dir():
            _fail(f"quellen: Ziel {str(sidecar_target)!r} ist ein Verzeichnis")
    elif quellen_path is not None and not quellen:
        _fail(
            "quellen: Pfad explizit angegeben, aber das IR enthaelt keine "
            "Herkunft -- eine leere Begleitdatei waere kein Erfolg"
        )

    staging = _stage_path(target_path)
    try:
        try:
            write_qea(ir, staging)
        except QeaWriterError as error:
            raise EmitError(str(error)) from error
        if verify:
            verify_qea_provenance(staging, ir)
        try:
            os.replace(staging, target_path)
        except OSError as error:
            raise EmitError(f"Ziel {str(target_path)!r}: nicht ersetzbar ({error})") from error
    finally:
        staging.unlink(missing_ok=True)

    if sidecar_target is not None:
        try:
            write_quellen(quellen, sidecar_target)
        except EmitError:
            raise
        except OSError as error:
            _fail(
                f"quellen: {str(sidecar_target)!r} nicht schreibbar ({error}) -- "
                "die .qea wurde bereits geschrieben"
            )

    digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
    tagged_elements = sum(1 for entry in entries if entry.kind == "Element")
    tagged_connectors = sum(1 for entry in entries if entry.kind == "Beziehung")
    total_quellen = _quellen_total(ir)
    return EmitReport(
        qea=target_path,
        quellen=sidecar_target,
        packages=_count(ir, "packages"),
        elements=_count(ir, "elements"),
        connectors=_count(ir, "connectors"),
        tagged_objects=len(entries),
        tagged_elements=tagged_elements,
        tagged_connectors=tagged_connectors,
        provenance_tags=sum(len(entry.tags) for entry in entries),
        refs=len(quellen),
        unused_quellen=total_quellen - len(quellen),
        digest=digest,
        verified=bool(verify),
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emit.py",
        description="IR-JSON -> .qea inklusive Herkunft und quellen.json.",
    )
    parser.add_argument("ir", help="IR-JSON nach IR_SPEC.md")
    parser.add_argument("ziel", help="Zielpfad der .qea")
    parser.add_argument(
        "--quellen",
        metavar="PFAD",
        default=None,
        help=f"Begleitdatei (Default: {DEFAULT_QUELLEN_NAME} neben der .qea)",
    )
    parser.add_argument(
        "--no-quellen", action="store_true", help="keine Begleitdatei schreiben"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Ruecklesung und Herkunftsvergleich ueberspringen",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="keine Fortschrittsmeldungen auf stderr"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.quellen and args.no_quellen:
        parser.error("--quellen und --no-quellen schliessen sich aus")
    try:
        report = emit(
            args.ir,
            args.ziel,
            quellen_path=args.quellen,
            sidecar=not args.no_quellen,
            verify=not args.no_verify,
        )
    except (EmitError, QeaWriterError, QeaReaderError, OSError) as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            f"IR: {report.packages} Pakete, {report.elements} Elemente, "
            f"{report.connectors} Beziehungen",
            file=sys.stderr,
        )
        print(
            f"Herkunft: {report.tagged_objects} Objekte, "
            f"{report.provenance_tags} Tags, {report.refs} Belege",
            file=sys.stderr,
        )
    parts = [
        f"{report.qea}: geschrieben",
        f"{report.elements} Elemente",
        f"{report.connectors} Beziehungen",
        f"{report.provenance_tags} Herkunfts-Tags",
    ]
    if report.quellen is not None:
        parts.append(f"{report.quellen} ({report.refs} Belege)")
    else:
        parts.append("keine Begleitdatei (keine Herkunft im IR)")
    parts.append(f"sha256 {report.digest[:16]}")
    print(", ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
