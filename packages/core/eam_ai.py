#!/usr/bin/env python3
"""eam_ai.py -- Gesamtlauf: Technologie + Prosa -> .qea.

Ein Aufruf, sechs Schritte, keine versteckten Nebenwege::

    eam-ai build --mdg technologie.xml --text architektur.pdf --out modell.qea
    eam-ai build --mdg technologie.xml --bild architektur.png --out modell.qea
    eam-ai build --mdg technologie.xml --out geruest.qea      # ohne Text, ohne KI

    1. Technologie laden      (MDG-XML -> Regelwerk im Speicher)
    2. Technologie pruefen    (Schema, nutzbare Stereotype)
    3. Quelle lesen           (.txt/.md/.docx/.pdf -> Absaetze; --bild -> Prosa)
    4. Extrahieren            (Sprachmodell -> Kandidaten-IR)
       oder Geruest bauen     (ohne --text/--bild und ohne Backend: nur Regelwerk)
    5. Validieren             (IR gegen Regelwerk -> findings.json)
    6. Emittieren             (IR -> .qea + quellen.json)

Der Geruest-Weg ruft kein Modell auf und ist vollstaendig offline. Bilder
werden base64 als multimodale Nachricht an ein OpenAI-kompatibles Backend
geschickt (``image_input``); die Beschreibung wird der Prosa vorangestellt.

Vertrag
-------
* Exit 0 nur bei **null Fehlern**. Warnungen blockieren nicht, mit ``--strict``
  schon. Jeder andere Ausgang ist Exit 1; argparse nutzt 2 fuer Aufruffehler.
* ``findings.json`` wird bei jedem Lauf geschrieben (auch leer). Bei einem
  technischen Abbruch vor der Pruefung enthaelt sie einen Lauf-Fehler.
* ``--dry-run`` schreibt keine ``.qea`` und keine ``quellen.json``. Geprueft
  wird trotzdem vollstaendig.
* Fortschritt geht nach stderr, das Ergebnis nach stdout.
* Kein Netzwerk ausser im ausdruecklich gewaehlten Backend. Der Kern ist
  deterministisch: gleiche Eingaben und gleiche Antwort -> gleiche Bytes.

Der Regelpfad ohne KI bleibt ``eam_suite.py`` (``--no-llm``). Dieses Modul
importiert ``eam_suite`` nicht und umgekehrt.

Weitere Unterbefehle
--------------------
    eam-ai merge --qea A.qea B.qea [...] --out ZIEL.qea [--bericht bericht.json]
    eam-ai edit  --qea MODELL.qea --ops ops.json --out NEU.qea [--mdg MDG.xml]

``merge`` fuehrt mehrere Modelle GUID-erhaltend zusammen (``model_merge``),
``edit`` wendet gezielte Aenderungen auf eine Kopie an (``model_edit``) und
prueft sie mit ``--mdg`` gegen das Regelwerk. Beide Unterbefehle schreiben nur
in die Zieldatei, nie in eine Eingabedatei.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import warnings
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Der MDG-Leser ist der einzige seiner Art und liegt in packages/rules.
_REGELN = Path(__file__).resolve().parent.parent / "rules"
if _REGELN.is_dir() and str(_REGELN) not in sys.path:
    sys.path.insert(0, str(_REGELN))

import emit as emit_module
import extract as extract_module
import image_input
import mdg_parser
import pdf_text
import relation_fill as relation_module
import repair_loop as repair_module
import rules_schema
import skeleton as skeleton_module
import validator
from emit import EmitError, EmitReport
from extract import ExtractionError, ExtractionResult
from mdg_parser import MdgParseError
from qea_reader import QeaReaderError
from qea_writer import QeaWriterError
from validator import ValidatorError

DEFAULT_PACKAGE = extract_module.DEFAULT_PACKAGE
DEFAULT_SCHEMA = Path(__file__).resolve().parent / "rules.schema.json"
FINDINGS_NAME = "findings.json"

# Eine Quelle fuer die Version: hier. pyproject.toml und CHANGELOG.md muessen
# dazu passen; tests/test_packaging.py prueft die drei Stellen gegeneinander.
__version__ = "3.2.5"

# DOCX ist eine ZIP-Datei mit genau diesem Pfad fuer den sichtbaren Text.
_DOCX_MAIN = "word/document.xml"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

Log = Callable[[str], None]


class BuildError(RuntimeError):
    """Gesamtlauf abgebrochen. Immer laut, nie ein stiller Teilerfolg."""


@dataclass(frozen=True)
class BuildReport:
    """Ergebnis eines Gesamtlaufs (fuer CLI, Tests und Einbettung)."""

    technology: Mapping[str, str]
    backend: str
    segments: int
    elements: int
    connectors: int
    dropped: tuple[Mapping[str, str], ...]
    attempts: int
    findings: tuple[Mapping[str, str], ...]
    findings_path: Path
    out: Path
    qea: Path | None
    quellen: Path | None
    digest: str
    provenance_tags: int
    exported: bool
    dry_run: bool
    strict: bool
    batches: int = 0

    @property
    def summary(self) -> dict[str, int]:
        return validator.summarize(self.findings)

    @property
    def blocked(self) -> bool:
        counts = self.summary
        return bool(counts["error"]) or (self.strict and bool(counts["warning"]))

    def result_line(self) -> str:
        """Eine kanonische Ergebniszeile fuer stdout."""
        counts = self.summary
        common = (
            f"{self.elements} Elemente, {self.connectors} Beziehungen, "
            f"{counts['error']} Fehler, {counts['warning']} Warnungen"
        )
        if self.dry_run:
            return f"Trockenlauf: {self.out} nicht geschrieben, {common}"
        if not self.exported:
            return f"{self.out}: nicht geschrieben, {common}"
        parts = [
            f"{self.out}: geschrieben",
            common,
            f"{self.provenance_tags} Herkunfts-Tags",
            f"sha256 {self.digest}",
        ]
        if self.quellen is not None:
            parts.append(f"{self.quellen}")
        return ", ".join(parts)


# --------------------------------------------------------------------------
# Technologie
# --------------------------------------------------------------------------


def load_technology(mdg: str | Path, *, schema_path: str | Path | None = None) -> dict[str, Any]:
    """MDG-XML lesen und gegen ``rules.schema.json`` pruefen.

    Liefert das geparste Regelwerk. Ein kaputtes XML, eine fremde Wurzel oder
    ein Schemaverstoss brechen laut ab -- es gibt keinen Teil-Erfolg.
    """
    source = Path(mdg)
    try:
        rules = mdg_parser.parse_mdg(source)
    except MdgParseError as exc:
        raise BuildError(f"Technologie: {exc}") from exc

    schema = Path(schema_path) if schema_path is not None else DEFAULT_SCHEMA
    try:
        rules_schema.validate(rules, rules_schema.load_schema(schema))
    except rules_schema.SchemaError as exc:
        raise BuildError(
            f"Technologie {source}: Regelwerk verletzt das Schema {schema}: {exc}"
        ) from exc

    stats = rules.get("stats")
    if not isinstance(stats, Mapping):
        raise BuildError(f"Technologie {source}: Regelwerk ohne stats -- kein belastbarer Lauf")
    if int(stats.get("elementStereotypes", 0)) <= 0:
        raise BuildError(
            f"Technologie {source}: keine Element-Stereotype im Regelwerk "
            f"-- ohne Technologie keine Extraktion"
        )
    return rules


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------


def _read_plain(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BuildError(f"Text {path}: keine UTF-8-Datei ({exc})") from exc
    except OSError as exc:
        raise BuildError(f"Text {path}: nicht lesbar ({exc})") from exc


def _docx_run_text(element: ET.Element) -> str:
    """Sichtbaren Text eines WordprocessingML-Knotens in Dokumentreihenfolge."""
    tag = element.tag
    if tag == _W + "t":
        return element.text or ""
    if tag == _W + "tab":
        return "\t"
    if tag in (_W + "br", _W + "cr"):
        return "\n"
    if tag == _W + "noBreakHyphen":
        return "-"
    parts: list[str] = []
    for child in element:
        parts.append(_docx_run_text(child))
    return "".join(parts)


def _docx_paragraphs(container: ET.Element) -> list[str]:
    """Absaetze aus dem Dokumentbaum, ohne verschachtelte Absaetze zu doppeln.

    Ein ``w:p`` wird als Ganzes gelesen (inklusive Textboxen darin) und nicht
    weiter durchsucht. Tabellen werden zeilen-/zellenweise durchlaufen, damit
    die Reihenfolge der sichtbare Lesefluss bleibt.
    """
    paragraphs: list[str] = []
    for child in container:
        tag = child.tag
        if tag == _W + "p":
            text = _docx_run_text(child)
            if text.strip():
                paragraphs.append(text.strip())
        elif tag in (_W + "tbl", _W + "tr", _W + "tc", _W + "sdt", _W + "sdtContent", _W + "body"):
            paragraphs.extend(_docx_paragraphs(child))
        # Kopf-/Fusszeilen, Felder und Eigenschaften liefern keinen Fliesstext.
    return paragraphs


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                payload = archive.read(_DOCX_MAIN)
            except KeyError as exc:
                raise BuildError(
                    f"Text {path}: {_DOCX_MAIN} fehlt -- keine Word-Datei"
                ) from exc
    except zipfile.BadZipFile as exc:
        raise BuildError(f"Text {path}: kein gueltiges DOCX (ZIP): {exc}") from exc
    except OSError as exc:
        raise BuildError(f"Text {path}: nicht lesbar ({exc})") from exc

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise BuildError(f"Text {path}: {_DOCX_MAIN} ist kein gueltiges XML: {exc}") from exc

    paragraphs = _docx_paragraphs(root)
    if not paragraphs:
        raise BuildError(f"Text {path}: kein Absatz mit Text -- leerer Text ist kein Ergebnis")
    return "\n\n".join(paragraphs)


def _read_pdf(path: Path) -> str:
    """PDF ueber den stdlib-Leser auslesen; Fehler als BuildError melden."""
    try:
        result = pdf_text.extract_text(path)
    except pdf_text.PdfError as exc:
        raise BuildError(str(exc)) from exc
    if result.warnings:
        for warning in result.warnings:
            warnings.warn(warning)
    return result.text


def read_text_source(path: str | Path) -> str:
    """Quelltext lesen. Unterstuetzt ``.txt``, ``.md``, ``.docx`` und ``.pdf``.

    DOCX wird ohne Fremdbibliothek gelesen: ZIP oeffnen, ``word/document.xml``
    parsen, Absaetze in Dokumentreihenfolge einsammeln. PDF ebenfalls ohne
    Fremdbibliothek (``pdf_text``): Inhaltsstroeme entpacken, Textoperatoren
    auswerten, ``/ToUnicode``-Tabellen fuer Umlaute beachten. Leerer Text
    bricht ab -- ein Scan ohne Textebene ist kein Ergebnis.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".docx":
        text = _read_docx(source)
    elif suffix == ".pdf":
        text = _read_pdf(source)
    elif suffix in (".txt", ".md", ".markdown", ".text"):
        text = _read_plain(source)
    else:
        raise BuildError(
            f"Text {source}: Endung {suffix or '(ohne)'} wird nicht gelesen "
            f"(erlaubt: .txt, .md, .docx, .pdf)"
        )
    if not text.strip():
        raise BuildError(f"Text {source}: leerer Text ist kein Ergebnis")
    return text


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def resolve_findings_path(out: str | Path, findings: str | Path | None) -> Path:
    """Findings-Ziel: explizit oder ``findings.json`` neben der .qea."""
    if findings is not None:
        return Path(findings)
    return Path(out).parent / FINDINGS_NAME


def _write_findings(findings: Sequence[Mapping[str, str]], path: Path) -> Path:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return validator.write_findings(findings, path)
    except OSError as exc:
        raise BuildError(f"findings: {path} nicht schreibbar ({exc})") from exc


def _failure_findings(message: str) -> list[dict[str, str]]:
    return [
        {
            "severity": "error",
            "object": "(Lauf)",
            "rule": "build",
            "check": "lauf",
            "message": message,
        }
    ]


# --------------------------------------------------------------------------
# Gesamtlauf
# --------------------------------------------------------------------------


def build(
    *,
    mdg: str | Path,
    text: str | Path | None = None,
    out: str | Path,
    images: Sequence[str | Path] = (),
    package: str = DEFAULT_PACKAGE,
    backend: extract_module.Backend | None = None,
    backend_kind: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    answer_file: str | Path | None = None,
    timeout: float = 120.0,
    schema_path: str | Path | None = None,
    findings_path: str | Path | None = None,
    dry_run: bool = False,
    strict: bool = False,
    sidecar: bool = True,
    quellen_path: str | Path | None = None,
    repair: bool = False,
    repair_rounds: int = 6,
    batch_chars: int | None = None,
    batch_threshold: int | None = None,
    startpaket: str | Path | None = None,
    katalog: str | Path | None = None,
    modell: str | Path | None = None,
    ai_backend: object | None = None,
    repair_bericht: str | Path | None = None,
    repair_ir_path: str | Path | None = None,
    log: Log | None = None,
) -> BuildReport:
    """Technologie + Prosa -> .qea. Liefert den Bericht, bricht laut ab.

    ``backend`` ist ein vorbereitetes Backend (Tests, Einbettung). Ohne Backend
    wird eines aus ``backend_kind`` gebaut; nur dieses spricht HTTP.

    Ohne ``text`` und ohne ``images`` wird kein Backend gebaut: dann entsteht
    ein Geruest allein aus dem Regelwerk (``skeleton``). Ein ausdruecklich
    gesetztes Backend ohne Quelle ist ein Aufruffehler, kein leerer Lauf.
    """
    out_path = Path(out)
    target_findings = resolve_findings_path(out_path, findings_path)
    if target_findings.resolve() == out_path.resolve():
        raise BuildError("findings und .qea sind derselbe Pfad")

    say: Log = log if log is not None else (lambda _message: None)
    image_paths = tuple(Path(item) for item in images)

    findings: list[dict[str, str]] = []
    try:
        if out_path.suffix.lower() != ".qea":
            raise BuildError(f"Ziel {out_path}: Endung muss .qea sein")
        if quellen_path is not None and Path(quellen_path).resolve() == out_path.resolve():
            raise BuildError("quellen und .qea sind derselbe Pfad")
        if quellen_path is not None and not sidecar:
            raise BuildError("--quellen und --no-quellen schliessen sich aus")

        # 1/6 Technologie laden
        rules = load_technology(mdg, schema_path=schema_path)
        source = rules.get("source", {})
        if not isinstance(source, Mapping):
            source = {}
        technique = {
            "name": str(source.get("technologyName", "")),
            "version": str(source.get("technologyVersion", "")),
            "id": str(source.get("technologyId", "")),
            "file": str(source.get("file", Path(mdg).name)),
            "sha256": str(source.get("sha256", "")),
        }
        stats = rules.get("stats", {})
        say(
            f"[1/6] Technologie: {technique['name']} {technique['version']}".rstrip()
            + f" ({stats.get('elementStereotypes', 0)} Element-Stereotypen,"
            + f" {stats.get('connectorRules', 0)} Konnektor-Regeln)"
        )

        # 2/6 Technologie pruefen: Schema ist bereits geprueft; zusaetzlich
        # muss die Extraktion mindestens ein instanziierbares Stereotyp sehen.
        try:
            rulebook = extract_module.load_rules(rules)
        except ExtractionError as exc:
            raise BuildError(f"Technologie: {exc}") from exc
        say(
            f"[2/6] Regelwerk: schema-konform, {len(rulebook.elements)} nutzbare "
            f"Element-Stereotype, {len(rulebook.connectors)} Beziehungs-Stereotype"
        )

        # 3/6 Quelle lesen -- Text und/oder Bilder. Ohne beides: Geruest.
        chosen = backend
        skeleton_mode = text is None and not image_paths
        if skeleton_mode and (backend is not None or backend_kind):
            raise BuildError(
                "Ohne --text und ohne --bild kein Modellaufruf: Backend angegeben, "
                "aber keine Quelle -- Abbruch statt leerem Lauf"
            )

        # Bestand und Startpaket gelten fuer Extraktion UND Export. Hier
        # initialisieren: der Geruestpfad (ohne Modellaufruf) laeuft sonst in
        # einen UnboundLocalError beim Export.
        bestand: list[tuple[str, str]] = []
        bestand_qea: Path | None = None
        katalog_obj = None

        if skeleton_mode:
            say("[3/6] Kein Text, kein Bild: Geruest aus dem Regelwerk (kein Modellaufruf)")
            try:
                skeleton_ir = skeleton_module.build_skeleton(rules, package=package)
            except skeleton_module.SkeletonError as exc:
                raise BuildError(f"Geruest: {exc}") from exc
            result: ExtractionResult = ExtractionResult(
                ir=skeleton_ir,
                segments=(),
                dropped=(),
                attempts=0,
                backend=skeleton_module.SKELETON_BACKEND,
            )
            say(
                f"[4/6] Geruest: {len(result.elements)} Element(e), "
                f"{len(result.connectors)} Beziehung(en), 0 Modellaufrufe"
            )
        else:
            if chosen is None:
                try:
                    chosen = extract_module.make_backend(
                        backend_kind or "openai",
                        model=model,
                        base_url=base_url,
                        answer_file=answer_file,
                        timeout=timeout,
                    )
                except ExtractionError as exc:
                    raise BuildError(f"Backend: {exc}") from exc

            document = ""
            text_path: Path | None = None
            if text is not None:
                text_path = Path(text)
                document = read_text_source(text_path)
            bildbloecke: list[str] = []
            for image_path in image_paths:
                try:
                    description = image_input.describe_image(image_path, chosen)
                except image_input.ImageInputError as exc:
                    raise BuildError(f"Bild {image_path}: {exc}") from exc
                bildbloecke.append(f"[Bildquelle: {image_path.name}]\n{description}")
            if bildbloecke:
                if document.strip():
                    bildbloecke.append(document)
                document = "\n\n".join(bildbloecke)

            documents = extract_module.split_documents(document)
            text_label = str(text_path) if text_path is not None else ""
            if image_paths and text_path is not None:
                quellen_text = f"{text_label}: {len(documents)} Absaetze"
                quellen_text += f", {len(image_paths)} Bild(er) vorangestellt"
            elif image_paths:
                quellen_text = (
                    f"{len(image_paths)} Bild(er) als Prosa, {len(documents)} Absaetze"
                )
            else:
                quellen_text = f"{text_label}: {len(documents)} Absaetze"
            say(f"[3/6] Quelle: {quellen_text} (D1-S1..{documents[-1].ref})")

            # 4/6 Extrahieren. Ein Startpaket (StEKa) wird vorab gelesen und in
            # den Prompt gelegt: Seine Elemente sind bereits im Modell, die
            # Extraktion soll sie mit exaktem Namen wiederverwenden statt
            # Dubletten zu erfinden. Die Kennungen bleiben beim Export erhalten.
            if modell is not None:
                bestand_qea = Path(modell)
                if not bestand_qea.exists():
                    raise BuildError(f"Modell {bestand_qea}: Datei nicht gefunden")
                try:
                    bestand = _modell_inventar(bestand_qea)
                except (OSError, sqlite3.Error) as exc:
                    raise BuildError(f"Modell {bestand_qea}: {exc}") from exc
                say(f"        Bestand: {len(bestand)} vorhandene Element(e) im Prompt")
            katalog_obj = None
            katalog_bekannte: list[tuple[str, str]] = []
            if katalog is not None:
                try:
                    import catalog_index

                    katalog_obj = catalog_index.Catalog.from_qea(katalog)
                except Exception as exc:  # noqa: BLE001 - Meldung reicht dem Nutzer
                    raise BuildError(f"Katalog {katalog}: {exc}") from exc
                katalog_bekannte = [
                    (eintrag.name, eintrag.stereotype)
                    for eintrag in sorted(katalog_obj.entries, key=lambda e: (e.stereotype, e.name))[:400]
                ]
                say(f"        Katalog: {len(katalog_obj)} Standardelement(e) im Prompt")
            standard: list[tuple[str, str]] = []
            if startpaket is not None:
                try:
                    standard = _startpaket_inventar(Path(startpaket))
                except (OSError, sqlite3.Error) as exc:
                    raise BuildError(f"Startpaket {startpaket}: {exc}") from exc
                if not standard:
                    raise BuildError(
                        f"Startpaket {startpaket}: keine Elemente gefunden -- "
                        "das ist kein Startpaket"
                    )
                say(f"        Startpaket: {len(standard)} Standardelement(e) im Prompt")
            # Bestand zuerst: Vorhandenes vor Standardelementen. Beides zusammen
            # ist der Wiederverwendungs-Block im Prompt.
            bekannte = list(dict.fromkeys(katalog_bekannte + bestand + standard))
            try:
                result = extract_module.extract_batched(
                    [document],
                    rules=rulebook,
                    backend=chosen,
                    package=package,
                    known=tuple(bekannte),
                    **(
                        {"budget_chars": batch_chars}
                        if batch_chars is not None
                        else {}
                    ),
                    **(
                        {"threshold_chars": batch_threshold}
                        if batch_threshold is not None
                        else {}
                    ),
                )
            except ExtractionError as exc:
                raise BuildError(f"Extraktion: {exc}") from exc
            # Eindeutige Handlungssaetze nachziehen, bevor die MDG prueft:
            # Der Modellaufruf findet Elemente und Notizen, laesst aber Kanten
            # liegen, deren beide Endpunkte im selben Satz stehen.
            nachtraege: list[Any] = []
            try:
                kantenregeln = validator.build_rules(rules)
                nachtraege = relation_module.ergaenze(result.ir, documents, kantenregeln)
            except validator.ValidatorError:
                nachtraege = []
            chargen = result.ir.get("meta", {}).get("extraction", {}).get("chargen", [])
            say(
                f"[4/6] Extraktion: {result.backend}: {len(result.elements)} Element(e), "
                f"{len(result.connectors)} Beziehung(en), {result.attempts} Versuch(e), "
                f"{len(result.dropped)} verworfen"
                + (f", {len(chargen)} Chargen" if chargen else "")
            )
            bestand_endpunkte = (
                result.ir.get("meta", {}).get("extraction", {}).get("bekannte_endpunkte", [])
            )
            if bestand_endpunkte:
                say(f"        Endpunkte aus dem Bestand: {len(bestand_endpunkte)}")
            if nachtraege:
                say(f"        Kanten nachgetragen: {len(nachtraege)}")
                for nachtrag in nachtraege:
                    say(
                        f"        + {nachtrag.quelle} -> {nachtrag.ziel} "
                        f"[{nachtrag.stereotyp}] ({nachtrag.ref})"
                    )
            for drop in result.dropped:
                say(f"        verworfen: {drop.kind} {drop.name!r}: {drop.reason}")

        # 5/6 Validieren -- und mit --repair selbsttaetig gegen die MDG geraderuecken
        try:
            ruleset = validator.build_rules(rules)
            findings = validator.validate_model(result.ir, ruleset)
            if (
                repair
                and chosen is not None
                and any(f["severity"] == validator.ERROR for f in findings)
            ):
                outcome = repair_module.repair(
                    result.ir,
                    ruleset,
                    max_rounds=repair_rounds,
                    ai_fix=repair_module.make_ai_fix(chosen, rulebook),
                )
                result = replace(result, ir=outcome.ir)
                findings = outcome.findings
                for runde in outcome.rounds:
                    say(
                        f"        Reparatur Runde {runde.number}: "
                        f"{runde.errors_before} -> {runde.errors_after} Fehler, "
                        f"{len(runde.changes)} Aenderung(en)"
                    )
                if repair_bericht:
                    Path(repair_bericht).write_text(
                        json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
        except ValidatorError as exc:
            raise BuildError(f"Pruefung: {exc}") from exc
        counts = validator.summarize(findings)
        try:
            _write_findings(findings, target_findings)
        except BuildError as exc:
            raise BuildError(f"{exc} -- der Lauf ist damit nicht belegt") from exc
        say(
            f"[5/6] Pruefung: {counts['total']} Findings: {counts['error']} Fehler, "
            f"{counts['warning']} Warnungen -> {target_findings}"
        )

        if repair_ir_path:
            # Zwischenstand sichern: zeigt, was die KI gebaut hat, bevor der
            # Export blockiert -- sonst ist ein gescheiterter Lauf nicht pruefbar.
            Path(repair_ir_path).write_text(
                json.dumps(result.ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        blocked = bool(counts["error"]) or (strict and bool(counts["warning"]))
        if blocked:
            reason = (
                "Warnungen blockieren (--strict)"
                if counts["error"] == 0 and strict
                else "Fehler im Modell"
            )
            say(f"[6/6] Kein Export: {reason}")
            return _report(
                technique, result, findings, target_findings, out_path,
                qea=None, quellen=None, digest="", provenance_tags=0, exported=False,
                dry_run=dry_run, strict=strict,
            )

        # 6/6 Emittieren
        if dry_run:
            say("[6/6] Trockenlauf: keine .qea, keine quellen.json geschrieben")
            return _report(
                technique, result, findings, target_findings, out_path,
                qea=None, quellen=None, digest="", provenance_tags=0, exported=False,
                dry_run=True, strict=strict,
            )

        # Standardelemente: Namen aus dem Katalog bekommen dessen Kennung und
        # Heimatpaket. Das geschieht vor dem Schreiben, damit die Datei von
        # Anfang an die Katalog-GUIDs traegt (und nicht erst ein Merge sie biegt).
        if katalog_obj is not None:
            zaehler = katalog_obj.apply(result.ir)
            say(
                f"        Katalog: {zaehler['katalog']} Element(e) wiedererkannt, "
                f"{zaehler['neu']} neu"
            )

        emit_target = out_path
        zwischen: Path | None = None
        basis = bestand_qea
        if basis is not None and startpaket is None:
            # Fortsetzen: der Bestand ist die Basis, das neue Teilmodell kommt
            # dazu. Kollidierende Kennungen bleiben eine Zeile (merge_models).
            zwischen = out_path.with_name(out_path.stem + ".neu.qea")
            emit_target = zwischen
        if startpaket is not None or basis is not None:
            # Erst in eine Zwischendatei schreiben, dann den Katalog mit
            # unveraenderten ea_guid uebernehmen (toolbox_merge ist der
            # geprüfte Weg dafuer). So bleibt der Export atomar.
            zwischen = zwischen or out_path.with_name(out_path.stem + ".ohne-startpaket.qea")
            emit_target = zwischen
        try:
            emitted: EmitReport = emit_module.emit(
                result.ir,
                emit_target,
                quellen_path=quellen_path,
                sidecar=sidecar,
                verify=True,
            )
        except (EmitError, QeaWriterError, QeaReaderError, OSError) as exc:
            raise BuildError(f"Export: {exc}") from exc
        standard_report: dict[str, Any] | None = None
        if zwischen is not None and (startpaket is not None or basis is not None):
            try:
                import model_merge
                import toolbox_merge

                # Reihenfolge: erst das Startpaket, dann der vorhandene Bestand.
                # Umgekehrt zoege der Bestand seine eigenen (umgehaengten)
                # Katalogkopien mit herein, und dieselbe Sache stuende zweimal
                # in der Datei -- sowie unter zwei verschiedenen Elternpaketen.
                # model_merge legt danach ueber ea_guid UND Name zusammen.
                schritt = zwischen
                if startpaket is not None:
                    # Das Startpaket ist die Basis, nicht der Zusatz: so bleiben
                    # seine ea_guid woertlich erhalten, und gleiche Elemente aus
                    # dem Lauf werden ueber Name + Stereotyp auf die vorhandene
                    # Zeile gebogen -- auch ueber Paketgrenzen hinweg.
                    mit_start = out_path.with_name(out_path.stem + ".mit-startpaket.qea")
                    startbasis = out_path.with_name(out_path.stem + ".startbasis.qea")
                    shutil.copyfile(Path(startpaket), startbasis)
                    rep = model_merge.merge_models(
                        [startbasis, schritt], mit_start, per_name=True
                    )
                    standard_report = {
                        "elemente": rep.elements,
                        "kanten": rep.connections,
                        "bereits_vorhanden": rep.merged,
                        "warnungen": list(rep.warnings),
                    }
                    startbasis.unlink(missing_ok=True)
                    schritt.unlink(missing_ok=True)
                    schritt = mit_start
                if basis is not None:
                    mit_bestand = out_path.with_name(out_path.stem + ".mit-bestand.qea")
                    model_merge.merge_models([schritt, basis], mit_bestand, per_name=True)
                    schritt.unlink(missing_ok=True)
                    schritt = mit_bestand
                schritt.replace(out_path)
            except Exception as exc:  # noqa: BLE001 - Fehlerabbildung unten
                zwischen.unlink(missing_ok=True)
                raise BuildError(f"Zusammenfuehrung: {exc}") from exc
            zwischen.unlink(missing_ok=True)
            # Bericht auf die tatsaechliche Zieldatei ziehen: Zahlen und
            # Pruefsumme stammen sonst von der Zwischendatei ohne Katalog.
            import hashlib
            from dataclasses import replace as _replace

            con = sqlite3.connect(str(out_path))
            try:
                # Elemente sind alle Objekte ausser Paketspiegeln -- der
                # Reader zaehlt genauso. Ein Filter auf 'Class' unterschlaegt
                # Ports und Objects und meldet zu kleine Zahlen.
                elements_final = con.execute(
                    "select count(*) from t_object where Object_Type <> 'Package'"
                ).fetchone()[0]
                connectors_final = con.execute(
                    "select count(*) from t_connector"
                ).fetchone()[0]
            finally:
                con.close()
            emitted = _replace(
                emitted,
                qea=out_path,
                elements=int(elements_final),
                connectors=int(connectors_final),
                digest=hashlib.sha256(out_path.read_bytes()).hexdigest(),
            )
            if standard_report is not None:
                say(
                    f"        Startpaket uebernommen: {standard_report['elemente']} Element(e), "
                    f"{standard_report['kanten']} Kante(n), "
                    f"{standard_report['bereits_vorhanden']} bereits vorhanden"
                )
            if basis is not None:
                say(f"        Bestand zusammengefuehrt: {basis}")
        say(
            f"[6/6] Export: {emitted.qea}: {emitted.elements} Elemente, "
            f"{emitted.connectors} Beziehungen, {emitted.provenance_tags} Herkunfts-Tags, "
            f"sha256 {emitted.digest[:16]}"
        )
        if basis is not None:
            # Der Bericht nennt den Gesamtstand (Datei), die Extraktion den
            # Zuwachs dieses Laufs. Zwei Zahlen, zwei Aussagen.
            say(
                f"        Neu in diesem Lauf: {len(result.elements)} Element(e), "
                f"{len(result.connectors)} Beziehung(en)"
            )
        return _report(
            technique, result, findings, target_findings, out_path,
            qea=emitted.qea, quellen=emitted.quellen, digest=emitted.digest,
            provenance_tags=emitted.provenance_tags,
            exported=True, dry_run=False, strict=strict,
            elements=emitted.elements, connectors=emitted.connectors,
        )
    except BuildError as exc:
        # Auch ein technischer Abbruch hinterlaesst eine belastbare Spur.
        # Bereits ermittelte Findings bleiben erhalten.
        try:
            _write_findings(list(findings) + _failure_findings(str(exc)), target_findings)
        except BuildError as write_error:
            raise BuildError(f"{exc}; {write_error}") from exc
        raise


def _report(
    technique: Mapping[str, str],
    result: ExtractionResult,
    findings: Sequence[Mapping[str, str]],
    findings_path: Path,
    out: Path,
    *,
    qea: Path | None,
    quellen: Path | None,
    digest: str,
    provenance_tags: int,
    exported: bool,
    dry_run: bool,
    strict: bool,
    elements: int | None = None,
    connectors: int | None = None,
) -> BuildReport:
    chargen = result.ir.get("meta", {}).get("extraction", {}).get("chargen", [])
    return BuildReport(
        technology=dict(technique),
        backend=result.backend,
        batches=len(chargen),
        segments=len(result.segments),
        elements=len(result.elements) if elements is None else elements,
        connectors=len(result.connectors) if connectors is None else connectors,
        dropped=tuple(drop.as_json() for drop in result.dropped),
        attempts=result.attempts,
        findings=tuple(dict(finding) for finding in findings),
        findings_path=findings_path,
        out=out,
        qea=qea,
        quellen=quellen,
        digest=digest,
        provenance_tags=provenance_tags,
        exported=exported,
        dry_run=dry_run,
        strict=strict,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eam-ai",
        description="Technologie + Prosa -> .qea (Extraktion, Pruefung, Export).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"eam-ai {__version__}",
        help="Version ausgeben und beenden",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser(
        "build",
        help="MDG laden, Quelle extrahieren (oder Geruest bauen), pruefen, .qea schreiben",
    )
    p_build.add_argument("--mdg", required=True, type=Path, help="MDG-/Technologie-XML")
    p_build.add_argument(
        "--text",
        type=Path,
        default=None,
        help="Quelltext (.txt, .md, .docx, .pdf); ohne --text/--bild entsteht ein Geruest",
    )
    p_build.add_argument(
        "--bild",
        type=Path,
        action="append",
        default=[],
        metavar="PFAD",
        help="Bild (PNG/JPG), mehrfach; Beschreibung wird der Prosa vorangestellt (nur --backend openai)",
    )
    p_build.add_argument("--out", "-o", required=True, type=Path, help="Ziel .qea")
    p_build.add_argument(
        "--package", default=DEFAULT_PACKAGE, help=f"Zielpaket (Default: {DEFAULT_PACKAGE})"
    )
    p_build.add_argument(
        "--backend",
        default=None,
        help="openai, ollama oder datei; ohne --text/--bild kein Modellaufruf",
    )
    p_build.add_argument(
        "--model", default=None, help="Modellname (Default aus EXTRACT_MODEL/OPENAI_MODEL/OLLAMA_MODEL)"
    )
    p_build.add_argument("--base-url", default=None, help="Basis-URL des Endpunkts")
    p_build.add_argument(
        "--antwort", type=Path, default=None, help="Antwortdatei fuer --backend datei (offline)"
    )
    p_build.add_argument("--timeout", type=float, default=120.0, help="HTTP-Zeitueberschreitung in s")
    p_build.add_argument(
        "--schema", type=Path, default=DEFAULT_SCHEMA, help="Schema fuer das Regelwerk"
    )
    p_build.add_argument(
        "--findings",
        type=Path,
        default=None,
        help=f"Findings-Ziel (Default: {FINDINGS_NAME} neben der .qea)",
    )
    p_build.add_argument(
        "--dry-run", action="store_true", help="alles pruefen, aber keine .qea schreiben"
    )
    p_build.add_argument(
        "--strict", action="store_true", help="Warnungen zaehlen wie Fehler"
    )
    p_build.add_argument(
        "--repair",
        action="store_true",
        help="MDG-Fehler selbsttaetig beheben und erneut pruefen (ohne KI)",
    )
    p_build.add_argument(
        "--repair-runden",
        type=int,
        default=6,
        help="Hochstzahl der Reparaturrunden (Default: 6)",
    )
    p_build.add_argument(
        "--repair-ir",
        type=Path,
        default=None,
        help="Zwischenstand der IR als JSON (auch wenn der Export blockiert wird)",
    )
    p_build.add_argument(
        "--repair-bericht",
        type=Path,
        default=None,
        help="Bericht der Reparatur als JSON",
    )
    p_build.add_argument(
        "--chargen-zeichen",
        type=int,
        default=None,
        help=(
            "Quelltext je Charge in Zeichen (Default: 12000). Gilt nur, wenn der "
            "Quelltext die Schwelle ueberschreitet"
        ),
    )
    p_build.add_argument(
        "--chargen-schwelle",
        type=int,
        default=None,
        help="ab dieser Quelltextlaenge wird geteilt (Default: 16000 Zeichen)",
    )
    p_build.add_argument(
        "--modell",
        type=Path,
        default=None,
        help=(
            "bestehendes Modell (.qea), an das dieser Lauf anknuepft: seine "
            "Elemente kommen in den Prompt, das Ergebnis enthaelt Bestand und Neues"
        ),
    )
    p_build.add_argument(
        "--startpaket",
        type=Path,
        default=None,
        help=(
            "Startpaket (StEKa) als .qea: Elemente kommen in den Prompt und mit "
            "unveraenderten Kennungen ins Ergebnis"
        ),
    )
    p_build.add_argument(
        "--katalog",
        type=Path,
        default=None,
        help=(
            "Standard-Elementekatalog (.qea, z. B. Modellelementekatalog der MASC): "
            "genannte Elemente uebernehmen Kennung und Heimatpaket des Katalogs"
        ),
    )
    p_build.add_argument("--quellen", type=Path, default=None, help="Pfad der quellen.json")
    p_build.add_argument(
        "--no-quellen", action="store_true", help="keine quellen.json schreiben"
    )
    p_build.add_argument("-q", "--quiet", action="store_true", help="keine Fortschrittsmeldungen")
    p_build.set_defaults(func=cmd_build)

    p_frage = sub.add_parser(
        "frage",
        help="Frage zu einer vorhandenen .qea beantworten (ohne --backend ohne KI)",
    )
    p_frage.add_argument("--qea", required=True, type=Path, help="Modell (.qea)")
    p_frage.add_argument("--frage", required=True, help="Frage in natuerlicher Sprache")
    scope_group = p_frage.add_mutually_exclusive_group()
    scope_group.add_argument("--paket", default=None, help="nur dieses Paket (mit Unterpaketen)")
    scope_group.add_argument("--element", default=None, help="nur dieses Element (Paket::Name)")
    p_frage.add_argument("--out", type=Path, default=None, help="Antwort als Markdown schreiben")
    p_frage.add_argument(
        "--backend", default=None, help="openai (ohne Angabe: nur Beschreibung, ohne KI)"
    )
    p_frage.add_argument("--model", default=None, help="Modellname (Default aus der Umgebung)")
    p_frage.add_argument("--base-url", default=None, help="Basis-URL des Endpunkts")
    p_frage.add_argument("--timeout", type=float, default=120.0, help="HTTP-Zeitueberschreitung in s")
    p_frage.set_defaults(func=cmd_frage)

    p_serve = sub.add_parser(
        "serve",
        help="Weboberflaeche starten (stdlib, eine Seite, gleicher Kern)",
    )
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bindeadresse (Default: 127.0.0.1; im Container 0.0.0.0)",
    )
    p_serve.add_argument("--port", type=int, default=8080, help="Port (Default: 8080)")
    p_serve.add_argument(
        "--max-upload-mb",
        type=int,
        default=25,
        help="Upload-Grenze in MB (Default: 25)",
    )
    p_serve.add_argument(
        "--max-seconds",
        type=float,
        default=120.0,
        help="Zeitlimit je Lauf in Sekunden (Default: 120)",
    )
    p_serve.add_argument(
        "--jobs", type=int, default=2, help="gleichzeitige Laeufe (Default: 2)"
    )
    p_serve.add_argument(
        "--job-ttl",
        type=float,
        default=600.0,
        help="Aufbewahrung der Ergebnisse in Sekunden (Default: 600)",
    )
    p_serve.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Basis fuer Arbeitsverzeichnisse (Default: System-Temp)",
    )
    p_serve.add_argument(
        "--assets",
        type=Path,
        default=None,
        help="Verzeichnis mit Beispiel-Technologie und Beispielantwort",
    )
    p_serve.set_defaults(func=cmd_serve)

    p_merge = sub.add_parser(
        "merge",
        help="mehrere .qea zu einem Modell zusammenfuehren (GUID-erhaltend)",
    )
    p_merge.add_argument(
        "--qea",
        action="append",
        nargs="+",
        required=True,
        metavar="QEA",
        help="Modelle in Einfuegereihenfolge; das erste ist die Basis (mehrfach angebbar)",
    )
    p_merge.add_argument("--out", "-o", required=True, type=Path, help="Ziel .qea")
    p_merge.add_argument(
        "--paket",
        default=None,
        metavar="NAME",
        help="optionales Sammelpaket fuer die Wurzelpakete der weiteren Modelle",
    )
    p_merge.add_argument(
        "--bericht",
        type=Path,
        default=None,
        help="Bericht (JSON) zusaetzlich in diese Datei schreiben",
    )
    p_merge.add_argument(
        "--per-name",
        action="store_true",
        help=(
            "Elemente zusaetzlich ueber Name und Stereotyp zusammenlegen: noetig, "
            "wenn zwei getrennte Laeufe dasselbe Element neu angelegt haben"
        ),
    )
    p_merge.set_defaults(func=cmd_merge)

    p_edit = sub.add_parser(
        "edit",
        help="gezielte Aenderungen an einer .qea anwenden (Original bleibt unberuehrt)",
    )
    p_edit.add_argument("--qea", required=True, type=Path, help="Quellmodell .qea")
    p_edit.add_argument("--ops", required=True, type=Path, help="Operationen (JSON-Liste)")
    p_edit.add_argument("--out", "-o", required=True, type=Path, help="Ziel .qea")
    p_edit.add_argument(
        "--mdg",
        type=Path,
        default=None,
        help="MDG-/Technologie-XML: jede Operation wird gegen das Regelwerk geprueft",
    )
    p_edit.set_defaults(func=cmd_edit)

    p_korr = sub.add_parser(
        "korrigiere",
        help="Korrektur in natuerlicher Sprache vorschlagen (und mit --apply schreiben)",
    )
    p_korr.add_argument("--qea", required=True, type=Path, help="Quellmodell .qea")
    source = p_korr.add_mutually_exclusive_group(required=True)
    source.add_argument("--anweisung", help="Korrektur in natuerlicher Sprache")
    source.add_argument(
        "--anweisung-datei", type=Path, help="Textdatei mit der Korrektur"
    )
    p_korr.add_argument(
        "--out", "-o", type=Path, default=None, help="Ziel .qea (nur mit --apply)"
    )
    p_korr.add_argument(
        "--apply", action="store_true", help="Vorschlag wirklich schreiben (sonst nur Vorschau)"
    )
    p_korr.add_argument(
        "--ja",
        action="store_true",
        help="Loeschoperationen ausdruecklich bestaetigen (confirm-before-destroy)",
    )
    p_korr.add_argument(
        "--mdg", type=Path, default=None, help="MDG-/Technologie-XML fuer die Pruefung"
    )
    p_korr.add_argument(
        "--backend",
        default=None,
        help="openai oder ollama; ohne Angabe arbeitet die feste Befehlsgrammatik",
    )
    p_korr.add_argument("--model", default=None, help="Modellname fuer das Backend")
    p_korr.add_argument("--base-url", default=None, help="Basis-URL des Backends")
    p_korr.add_argument(
        "--antwort", type=Path, default=None, help="Antwortdatei fuer --backend datei"
    )
    p_korr.add_argument("--timeout", type=float, default=120.0, help="HTTP-Zeitueberschreitung in s")
    p_korr.add_argument("--json", action="store_true", help="Vorschlag als JSON ausgeben")
    p_korr.set_defaults(func=cmd_korrigiere)

    p_toolbox = sub.add_parser(
        "toolbox",
        help="Standardelemente aus einem Katalog uebernehmen (GUID-erhaltend)",
    )
    p_toolbox.add_argument(
        "--kasten",
        required=True,
        type=Path,
        metavar="QEA",
        help="Katalog-/Startpaket-Datei mit den Standardelementen (wird nur gelesen)",
    )
    p_toolbox.add_argument(
        "--modell",
        type=Path,
        default=None,
        metavar="QEA",
        help="bestehendes Modell harmonisieren; ohne Angabe startet ein leeres Modell",
    )
    p_toolbox.add_argument("--out", "-o", required=True, type=Path, help="Ziel .qea")
    p_toolbox.add_argument(
        "--paket",
        default="Standard",
        metavar="NAME",
        help="Dachpaket im Ziel, unter dem der Katalog haengt (Default: Standard)",
    )
    p_toolbox.add_argument(
        "--startpaket",
        default="Architektur",
        metavar="NAME",
        help="Wurzelpaket, wenn ohne --modell begonnen wird (Default: Architektur)",
    )
    p_toolbox.add_argument(
        "--nur",
        action="append",
        default=None,
        metavar="PAKET",
        help="nur diese Katalogpakete uebernehmen (mehrfach angebbar, samt Unterpaketen)",
    )
    p_toolbox.add_argument(
        "--bericht",
        type=Path,
        default=None,
        help="Bericht (JSON) zusaetzlich in diese Datei schreiben",
    )
    p_toolbox.add_argument(
        "--nur-bericht",
        action="store_true",
        help="nur pruefen und Bericht zeigen, keine .qea schreiben",
    )
    p_toolbox.set_defaults(func=cmd_toolbox)
    return parser


def cmd_build(args: argparse.Namespace) -> int:
    def say(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    # EXTRACT_BACKEND nur lesen, wenn tatsaechlich eine Quelle extrahiert wird.
    # Ohne Quelle bleibt das Backend leer -- dann ist der Lauf ein Geruest.
    backend_kind = args.backend
    if backend_kind is None and (args.text is not None or args.bild):
        backend_kind = os.environ.get("EXTRACT_BACKEND") or None

    try:
        report = build(
            mdg=args.mdg,
            text=args.text,
            images=args.bild,
            out=args.out,
            package=args.package,
            backend_kind=backend_kind,
            model=args.model,
            base_url=args.base_url,
            answer_file=args.antwort,
            timeout=args.timeout,
            schema_path=args.schema,
            findings_path=args.findings,
            dry_run=args.dry_run,
            strict=args.strict,
            repair=args.repair,
            repair_rounds=args.repair_runden,
            repair_bericht=args.repair_bericht,
            repair_ir_path=args.repair_ir,
            batch_chars=args.chargen_zeichen,
            batch_threshold=args.chargen_schwelle,
            startpaket=args.startpaket,
            katalog=args.katalog,
            modell=args.modell,
            sidecar=not args.no_quellen,
            quellen_path=args.quellen,
            log=say,
        )
    except BuildError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    counts = report.summary
    print(report.result_line())
    if report.blocked:
        print(
            f"FEHLER: {counts['error']} Fehler"
            + (f", {counts['warning']} Warnungen (--strict)" if report.strict and counts["warning"] else "")
            + f"; keine .qea geschrieben. Findings: {report.findings_path}",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_frage(args: argparse.Namespace) -> int:
    """Frage zu einer .qea. Ohne --backend bleibt der Lauf offline (ohne KI)."""
    import qea_chat  # lokal: der Bau-Pfad importiert den Frage-Weg nicht

    scope: dict[str, str] | None = None
    if args.paket:
        scope = {"package": args.paket}
    elif args.element:
        scope = {"element": args.element}

    backend = None
    if args.backend:
        try:
            backend = extract_module.make_backend(
                args.backend,
                model=args.model,
                base_url=args.base_url,
                timeout=args.timeout,
            )
        except ExtractionError as exc:
            print(f"FEHLER: Backend: {exc}", file=sys.stderr)
            return 1
        # Eine Frage wird in Prosa beantwortet, nicht als JSON-Objekt. Der
        # Extraktionspfad erzwingt JSON; hier wird das ausdruecklich abgeschaltet.
        if (
            isinstance(backend, extract_module.OpenAICompatibleBackend)
            and backend.json_mode
        ):
            backend = replace(backend, json_mode=False)

    try:
        answer = qea_chat.ask_qea(args.qea, args.frage, backend=backend, scope=scope)
    except qea_chat.QeaChatError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(answer.text)
    if args.out is not None:
        try:
            target = qea_chat.export_answer(answer, args.out)
        except qea_chat.QeaChatError as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 1
        print(f"Antwort: {target}", file=sys.stderr)
    return 0


def cmd_korrigiere(args: argparse.Namespace) -> int:
    """Korrektur in natuerlicher Sprache: erst Vorschlag, dann auf Wunsch schreiben."""
    import model_edit
    import nl_edit  # lokal: der Bau-Pfad braucht den Korrektur-Weg nicht

    if args.anweisung_datei is not None:
        try:
            instruction = args.anweisung_datei.read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"FEHLER: {args.anweisung_datei}: nicht lesbar ({exc})", file=sys.stderr)
            return 1
    else:
        instruction = args.anweisung or ""

    backend = None
    if args.backend:
        try:
            backend = extract_module.make_backend(
                args.backend,
                model=args.model,
                base_url=args.base_url,
                answer_file=args.antwort,
                timeout=args.timeout,
            )
        except ExtractionError as exc:
            print(f"FEHLER: Backend: {exc}", file=sys.stderr)
            return 1

    try:
        proposal = nl_edit.propose(args.qea, instruction, backend=backend)
    except nl_edit.NlEditError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(proposal.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Vorschlag ({proposal.backend}, {len(proposal.ops)} Operation(en)):")
        if proposal.reply:
            print(f"  {proposal.reply}")
        for line in nl_edit.preview_lines(proposal):
            print(f"  {line}")
        for warning in proposal.warnings:
            print(f"  HINWEIS: {warning}")
        if proposal.destructive:
            print("  ACHTUNG: Loeschoperation enthalten.")

    if not args.apply:
        print(
            "Vorschau — nichts geschrieben. Mit --out ZIEL.qea --apply "
            + ("--ja " if proposal.destructive else "")
            + "ausfuehren.",
            file=sys.stderr,
        )
        return 0

    if args.out is None:
        print("FEHLER: --apply verlangt --out", file=sys.stderr)
        return 1
    try:
        result = nl_edit.apply(
            proposal, args.out, mdg=args.mdg, confirm=bool(args.ja)
        )
    except (nl_edit.NlEditError, model_edit.EditError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if not args.json:
        print(
            f"{result.written}: {result.applied} von {result.ops} Operation(en) angewendet"
            + (f", MDG: {result.mdg}" if result.mdg else "")
        )
        for change in result.changes:
            print(f"  - {change}")
        for warning in result.warnings:
            print(f"  HINWEIS: {warning}")
        for rejection in result.rejected:
            print(
                "  ABGELEHNT: " + str(rejection.get("op")) + ": " + str(rejection.get("grund")),
                file=sys.stderr,
            )
    return 0 if not result.rejected else 1


def cmd_serve(args: argparse.Namespace) -> int:
    """Weboberflaeche starten. Grenzen kommen aus den CLI-Optionen."""
    import webui  # lokal: der Regelpfad und ``build`` importieren keine Netzmodule

    try:
        server = webui.make_server(
            host=args.host,
            port=args.port,
            max_upload=max(1, args.max_upload_mb) * 1024 * 1024,
            max_seconds=args.max_seconds,
            max_jobs=args.jobs,
            job_ttl=args.job_ttl,
            workdir=args.workdir,
            assets=args.assets,
            version=__version__,
        )
    except webui.WebError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[0], server.server_address[1]
    print(f"eam-ai {__version__}: http://{host}:{port}/", file=sys.stderr, flush=True)
    print(
        f"Grenzen: {args.max_upload_mb} MB Upload, {args.max_seconds:g} s je Lauf, "
        f"{args.jobs} Laeufe parallel, Ergebnisse {args.job_ttl:g} s",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:  # pragma: no cover - Bedienung
        print("Beendet.", file=sys.stderr)
    finally:
        server.stop()
    return 0


#: Platzhalter im leeren Startmodell; wird nach dem Katalog-Merge entfernt.
_PLATZHALTER = "{00000000-0000-4000-8000-00000000AAAA}"


def _drop_element(path: Path, guid: str) -> None:
    """Entfernt ein einzelnes Element samt Anhang; nur fuer den Platzhalter gedacht."""
    import sqlite3

    con = sqlite3.connect(str(path))
    try:
        con.execute("delete from t_object where ea_guid = ?", (guid,))
        con.execute("delete from t_objectproperties where Object_ID not in (select Object_ID from t_object)")
        con.execute("delete from t_xref where Client = ?", (guid,))
        con.commit()
    finally:
        con.close()


def _modell_inventar(path: Path, limit: int = 400) -> list[tuple[str, str]]:
    """Elemente eines bestehenden Modells (Name, Stereotyp) fuer den Prompt."""
    return _startpaket_inventar(path, limit=limit)


def _startpaket_inventar(path: Path, limit: int = 400) -> list[tuple[str, str]]:
    """Elemente eines Startpakets (Name, Stereotyp) fuer den Prompt lesen.

    Lesend und ohne Schreiben: Das Startpaket bleibt unangetastet. Nur
    Klassen zaehlen; Pakete und Diagramme sind keine Standardelemente.
    """
    if not path.exists():
        raise OSError(f"{path}: Datei nicht gefunden")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select Name, ifnull(Stereotype, '') from t_object "
            "where Object_Type = 'Class' and Name is not null and Name <> '' "
            "order by Name limit ?",
            (limit,),
        ).fetchall()
    finally:
        con.close()
    return [(str(name), str(stereotype)) for name, stereotype in rows]


def cmd_toolbox(args: argparse.Namespace) -> int:
    """Standardelemente aus einem Katalog uebernehmen oder ein Modell harmonisieren."""
    import sqlite3
    import tempfile

    import qea_writer
    import toolbox_merge

    try:
        if args.modell is not None:
            base = args.modell
        else:
            # Ohne Bestand beginnt das Modell mit einem leeren Traegerpaket;
            # der Katalog wird hineinkopiert, statt ein Modell zu erfinden.
            base = Path(tempfile.mkdtemp(prefix="eam-toolbox-")) / "basis.qea"
            # Der Writer lehnt ein Modell ohne Element ab. Fuer den Start aus
            # dem Katalog dient daher ein Platzhalter, der nach dem Merge
            # wieder entfernt wird -- er gehoert nicht zum Ergebnis.
            qea_writer.write_qea(
                {
                    "ir_version": 1,
                    "technology": {"profile": ""},
                    "packages": [{"path": args.startpaket}],
                    "elements": [
                        {
                            "package": args.startpaket,
                            "name": "__startpaket_platzhalter__",
                            "stereotype": "",
                            "guid": _PLATZHALTER,
                        }
                    ],
                    "connectors": [],
                },
                base,
            )
        report = toolbox_merge.merge_toolbox(
            base,
            args.kasten,
            args.out,
            paketname=args.paket,
            nur=args.nur,
            dry_run=args.nur_bericht,
        )
    except (toolbox_merge.ToolboxMergeError, qea_writer.QeaWriterError, OSError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if args.bericht is not None:
        args.bericht.parent.mkdir(parents=True, exist_ok=True)
        args.bericht.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if args.modell is None and not args.nur_bericht:
        _drop_element(args.out, _PLATZHALTER)

    if args.nur_bericht:
        print(
            f"Vorschau: {report['elemente']} Elemente, {report['kanten']} Kanten, "
            f"{report['pakete']} Pakete, {report['bereits_vorhanden']} bereits vorhanden "
            f"-- nichts geschrieben"
        )
        return 0
    print(
        f"{args.out}: geschrieben, {report['elemente']} Elemente, "
        f"{report['kanten']} Kanten, {report['pakete']} Pakete, "
        f"{report['bereits_vorhanden']} bereits vorhanden, {report['tags']} Tags"
    )
    for warning in report.get("warnungen", []):
        print(f"HINWEIS: {warning}", file=sys.stderr)
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Mehrere .qea zu einem Modell zusammenfuehren (GUID-erhaltend)."""
    import sqlite3

    import model_merge  # lokal: der Bau-Pfad braucht den Merge nicht

    paths = [str(item) for group in args.qea for item in group]
    try:
        result = model_merge.merge_models(
            paths, args.out, package=args.paket, per_name=args.per_name
        )
    except (model_merge.MergeError, OSError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    report = result.as_dict()
    if args.bericht is not None:
        args.bericht.parent.mkdir(parents=True, exist_ok=True)
        args.bericht.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(
        f"{result.written}: geschrieben, {result.elements} Elemente, "
        f"{result.connections} Kanten, {result.packages} Pakete, "
        f"{result.merged} zusammengefuehrt, {len(result.conflicts)} Konflikte "
        f"aus {result.models} Modellen"
    )
    for conflict in result.conflicts:
        print(
            f"KONFLIKT: {conflict.get('art')} {conflict.get('paket')}::"
            f"{conflict.get('name')} ({conflict.get('datei')})",
            file=sys.stderr,
        )
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    """Gezielte Aenderungen an einer .qea anwenden (Original bleibt unberuehrt)."""
    import sqlite3

    import model_edit  # lokal: der Bau-Pfad braucht den Editor nicht

    try:
        payload = json.loads(args.ops.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FEHLER: {args.ops}: nicht lesbar ({exc})", file=sys.stderr)
        return 1

    try:
        result = model_edit.edit_model(args.qea, payload, args.out, mdg=args.mdg)
    except (model_edit.EditError, OSError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(
        f"{result.written}: geschrieben, {result.applied} von {result.ops} "
        f"Operationen angewendet, {len(result.rejected)} abgelehnt"
        + (f" (MDG: {result.mdg})" if result.mdg else "")
    )
    for rejection in result.rejected:
        print(
            f"ABGELEHNT: op {rejection.get('op')} {rejection.get('typ')}: "
            f"{rejection.get('grund')}",
            file=sys.stderr,
        )
    return 0 if not result.rejected else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover - Bedienung
        print("FEHLER: abgebrochen", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
