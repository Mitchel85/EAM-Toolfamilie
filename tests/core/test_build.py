"""Tests fuer eam_ai.py -- Gesamtlauf von der Technologie bis zur .qea.

DoD: End-to-End-Test mit synthetischem Text und gemocktem LLM (``StaticBackend``
bzw. ``--backend datei``). Kein Netz, keine echten Modelle, keine Personendaten.
Die Tests pruefen Exit-Codes, Findings, Trockenlauf, DOCX-Lesen und dass
gleicher Input byte-identische Ausgaben liefert.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import eam_ai
import extract as ex
import validator
from qea_reader import read_qea

FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"  # Monorepo
MDG = FIXTURES / "admbw_auszug.xml"

TEXT = (
    "Der Ablauf A steuert die Faehigkeit B.\n"
    "\n"
    "Die Faehigkeit B wird durch den Dienst C erbracht.\n"
    "\n"
    "Der Dienst C ist ein Service.\n"
)

ANSWER = {
    "elements": [
        {
            "name": "Ablauf A",
            "stereotype": "Process",
            "notes": "synthetisch",
            "source_ref": "D1-S1",
            "confidence": 0.9,
        },
        {
            "name": "Faehigkeit B",
            "stereotype": "Capability",
            "notes": "synthetisch",
            "source_ref": "D1-S2",
            "confidence": 0.85,
        },
        {
            "name": "Dienst C",
            "stereotype": "ServiceSpecification",
            "notes": "synthetisch",
            "source_ref": "D1-S3",
            "confidence": 0.8,
        },
    ],
    "connectors": [
        {
            "source": "Faehigkeit B",
            "target": "Dienst C",
            "stereotype": "Exhibits",
            "notes": "synthetisch",
            "source_ref": "D1-S2",
            "confidence": 0.8,
        }
    ],
}

BAD_ANSWER = {
    "elements": [
        {
            "name": "Dienst C",
            "stereotype": "ServiceSpecification",
            "notes": "",
            "source_ref": "D1-S3",
            "confidence": 0.8,
        },
        {
            "name": "Faehigkeit B",
            "stereotype": "Capability",
            "notes": "",
            "source_ref": "D1-S2",
            "confidence": 0.85,
        },
    ],
    "connectors": [
        {
            "source": "Dienst C",
            "target": "Faehigkeit B",
            "stereotype": "CapabilityDependency",
            "notes": "",
            "source_ref": "D1-S2",
            "confidence": 0.8,
        }
    ],
}


def write_docx(path: Path, paragraphs: list[str]) -> Path:
    """Minimales, gueltiges DOCX ohne Fremdbibliothek erzeugen."""
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr("word/document.xml", document)
    return path


def write_answer(path: Path, answer: dict) -> Path:
    path.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    return path


def make_backend(answer: dict = ANSWER, *weitere: str) -> ex.StaticBackend:
    """Statische Antworten in Reihenfolge; ``weitere`` sind fertige JSON-Texte."""
    return ex.StaticBackend(
        [json.dumps(answer, ensure_ascii=False), *weitere], name="test"
    )


def run_cli(capsys, *arguments: str) -> tuple[int, str, str]:
    code = eam_ai.main(["build", *arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --------------------------------------------------------------------------
# End-to-End
# --------------------------------------------------------------------------


def test_end_to_end_txt_writes_qea_and_findings(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    target = tmp_path / "modell.qea"

    report = eam_ai.build(
        mdg=MDG,
        text=source,
        out=target,
        backend=make_backend(),
        findings_path=tmp_path / "findings.json",
    )

    assert report.exported is True
    assert report.blocked is False
    assert target.is_file()
    assert report.qea == target
    assert report.quellen is not None
    assert report.quellen == tmp_path / "quellen.json"
    assert report.quellen.is_file()
    assert report.elements == 3
    assert report.connectors == 1
    assert report.provenance_tags == 12
    assert report.digest == report.digest.lower() and len(report.digest) == 64
    assert json.loads((tmp_path / "findings.json").read_text(encoding="utf-8")) == []

    ir = read_qea(target)
    assert len(ir["elements"]) == 3
    assert len(ir["connectors"]) == 1
    assert ir["technology"]["profile"] == "NAFv4-ADMBw"
    names = {element["name"] for element in ir["elements"]}
    assert names == {"Ablauf A", "Faehigkeit B", "Dienst C"}
    for element in ir["elements"]:
        assert set(element["tags"]) >= {"source_ref", "source_doc", "source_confidence"}
    assert ir["connectors"][0]["tags"]["source_ref"] == "D1-S2"

    assert report.quellen is not None
    quellen = json.loads(report.quellen.read_text(encoding="utf-8"))
    assert sorted(quellen) == ["D1-S1", "D1-S2", "D1-S3"]


def test_docx_matches_txt_and_two_runs_are_byte_identical(tmp_path: Path) -> None:
    source_txt = tmp_path / "text.txt"
    source_txt.write_text(TEXT, encoding="utf-8")
    source_docx = write_docx(
        tmp_path / "text.docx",
        [
            "Der Ablauf A steuert die Faehigkeit B.",
            "Die Faehigkeit B wird durch den Dienst C erbracht.",
            "Der Dienst C ist ein Service.",
        ],
    )

    reports = []
    for index, source in enumerate((source_txt, source_docx), start=1):
        report = eam_ai.build(
            mdg=MDG,
            text=source,
            out=tmp_path / f"modell{index}.qea",
            backend=make_backend(),
            findings_path=tmp_path / f"findings{index}.json",
        )
        assert report.exported is True
        reports.append(report)

    assert reports[0].digest == reports[1].digest
    assert (tmp_path / "modell1.qea").read_bytes() == (tmp_path / "modell2.qea").read_bytes()
    assert reports[0].findings_path.read_bytes() == reports[1].findings_path.read_bytes()


def test_two_processes_produce_identical_bytes(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    answer = write_answer(tmp_path / "answer.json", ANSWER)
    digests = []
    for index, seed in enumerate(("1", "4242"), start=1):
        target = tmp_path / f"proc{index}.qea"
        environment = dict(os.environ, PYTHONHASHSEED=seed)
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(eam_ai.__file__).resolve().parent / "eam-ai"),
                "build",
                "--mdg",
                str(MDG),
                "--text",
                str(source),
                "--out",
                str(target),
                "--backend",
                "datei",
                "--antwort",
                str(answer),
                "--findings",
                str(tmp_path / f"findings{index}.json"),
                "-q",
            ],
            cwd=Path(eam_ai.__file__).resolve().parent,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        digests.append(target.read_bytes())
    assert digests[0] == digests[1]


# --------------------------------------------------------------------------
# Trockenlauf und CLI
# --------------------------------------------------------------------------


def test_cli_end_to_end_reports_progress_on_stderr(tmp_path: Path, capsys) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    answer = write_answer(tmp_path / "answer.json", ANSWER)
    target = tmp_path / "modell.qea"

    code, out, err = run_cli(
        capsys,
        "--mdg",
        str(MDG),
        "--text",
        str(source),
        "--out",
        str(target),
        "--backend",
        "datei",
        "--antwort",
        str(answer),
        "--findings",
        str(tmp_path / "findings.json"),
    )

    assert code == 0
    assert "geschrieben" in out
    assert "3 Elemente" in out
    assert "sha256" in out
    assert "[1/6] Technologie" in err
    assert "[6/6] Export" in err
    assert target.is_file()


def test_cli_dry_run_writes_no_qea(tmp_path: Path, capsys) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    answer = write_answer(tmp_path / "answer.json", ANSWER)
    target = tmp_path / "modell.qea"

    code, out, err = run_cli(
        capsys,
        "--mdg",
        str(MDG),
        "--text",
        str(source),
        "--out",
        str(target),
        "--backend",
        "datei",
        "--antwort",
        str(answer),
        "--dry-run",
        "--findings",
        str(tmp_path / "findings.json"),
    )

    assert code == 0
    assert "Trockenlauf" in out
    assert target.exists() is False
    assert (tmp_path / "quellen.json").exists() is False
    assert json.loads((tmp_path / "findings.json").read_text(encoding="utf-8")) == []
    assert "Trockenlauf" in err


# --------------------------------------------------------------------------
# Laute Fehler
# --------------------------------------------------------------------------


def test_validation_error_blocks_export_and_keeps_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    target = tmp_path / "modell.qea"
    target.write_bytes(b"alter stand, nicht ueberschreiben")

    report = eam_ai.build(
        mdg=MDG,
        text=source,
        out=target,
        backend=make_backend(BAD_ANSWER),
        findings_path=tmp_path / "findings.json",
    )

    assert report.exported is False
    assert report.qea is None
    assert report.blocked is True
    assert report.summary["error"] == 1
    assert target.read_bytes() == b"alter stand, nicht ueberschreiben"
    findings = json.loads((tmp_path / "findings.json").read_text(encoding="utf-8"))
    assert findings[0]["severity"] == "error"
    assert findings[0]["check"] == "forbiddenConnectorEndpoints"


def test_cli_validation_error_exits_1_with_findings(tmp_path: Path, capsys) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    answer = write_answer(tmp_path / "answer.json", BAD_ANSWER)
    target = tmp_path / "modell.qea"
    findings = tmp_path / "findings.json"

    code, out, err = run_cli(
        capsys,
        "--mdg",
        str(MDG),
        "--text",
        str(source),
        "--out",
        str(target),
        "--backend",
        "datei",
        "--antwort",
        str(answer),
        "--findings",
        str(findings),
    )

    assert code == 1
    assert "nicht geschrieben" in out
    assert "FEHLER" in err
    assert target.exists() is False
    assert json.loads(findings.read_text(encoding="utf-8"))[0]["severity"] == "error"


def test_strict_treats_warning_as_blocker(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    warning = {
        "severity": "warning",
        "object": "Architektur",
        "rule": "",
        "check": "testWarnung",
        "message": "synthetische Warnung",
    }
    monkeypatch.setattr(
        eam_ai.validator, "validate_model", lambda ir, rules: [warning]
    )

    strict = eam_ai.build(
        mdg=MDG,
        text=source,
        out=tmp_path / "strict.qea",
        backend=make_backend(),
        findings_path=tmp_path / "strict_findings.json",
        strict=True,
    )
    assert strict.exported is False
    assert strict.blocked is True

    mild = eam_ai.build(
        mdg=MDG,
        text=source,
        out=tmp_path / "mild.qea",
        backend=make_backend(),
        findings_path=tmp_path / "mild_findings.json",
        strict=False,
    )
    assert mild.exported is True
    assert mild.blocked is False
    assert (tmp_path / "mild.qea").is_file()


def test_broken_technology_exits_1_and_writes_failure_findings(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "kaputt.xml"
    broken.write_text("<MDG.Technology><UMLProfiles>", encoding="utf-8")
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    answer = write_answer(tmp_path / "answer.json", ANSWER)
    target = tmp_path / "modell.qea"
    findings = tmp_path / "findings.json"

    code, _out, err = run_cli(
        capsys,
        "--mdg",
        str(broken),
        "--text",
        str(source),
        "--out",
        str(target),
        "--backend",
        "datei",
        "--antwort",
        str(answer),
        "--findings",
        str(findings),
    )

    assert code == 1
    assert "FEHLER" in err
    assert target.exists() is False
    payload = json.loads(findings.read_text(encoding="utf-8"))
    assert payload[0]["severity"] == "error"
    assert payload[0]["rule"] == "build"


def test_empty_text_is_loud(tmp_path: Path) -> None:
    source = tmp_path / "leer.txt"
    source.write_text("   \n\n  \n", encoding="utf-8")
    with pytest.raises(eam_ai.BuildError, match="leerer Text"):
        eam_ai.build(
            mdg=MDG,
            text=source,
            out=tmp_path / "modell.qea",
            backend=make_backend(),
            findings_path=tmp_path / "findings.json",
        )
    assert (tmp_path / "findings.json").is_file()


def test_unsupported_text_suffix_is_loud(tmp_path: Path) -> None:
    source = tmp_path / "text.rtf"
    source.write_bytes(b"{\\rtf1 kein unterstuetztes Format}")
    with pytest.raises(eam_ai.BuildError, match="Endung"):
        eam_ai.read_text_source(source)


def test_docx_without_document_xml_is_loud(tmp_path: Path) -> None:
    broken = tmp_path / "kaputt.docx"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("word/other.xml", "<x/>")
    with pytest.raises(eam_ai.BuildError, match="word/document.xml"):
        eam_ai.read_text_source(broken)


def test_output_must_be_qea(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    with pytest.raises(eam_ai.BuildError, match="Endung muss .qea sein"):
        eam_ai.build(
            mdg=MDG,
            text=source,
            out=tmp_path / "modell.json",
            backend=make_backend(),
        )


def test_findings_and_qea_cannot_be_same_path(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    with pytest.raises(eam_ai.BuildError, match="derselbe Pfad"):
        eam_ai.build(
            mdg=MDG,
            text=source,
            out=tmp_path / "modell.qea",
            backend=make_backend(),
            findings_path=tmp_path / "modell.qea",
        )


def test_quellen_and_no_quellen_are_exclusive(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    with pytest.raises(eam_ai.BuildError, match="schliessen sich aus"):
        eam_ai.build(
            mdg=MDG,
            text=source,
            out=tmp_path / "modell.qea",
            backend=make_backend(),
            sidecar=False,
            quellen_path=tmp_path / "q.json",
        )


def test_no_quellen_writes_only_qea(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    report = eam_ai.build(
        mdg=MDG,
        text=source,
        out=tmp_path / "modell.qea",
        backend=make_backend(),
        findings_path=tmp_path / "findings.json",
        sidecar=False,
    )
    assert report.exported is True
    assert report.quellen is None
    assert (tmp_path / "modell.qea").is_file()
    assert (tmp_path / "quellen.json").exists() is False


# --------------------------------------------------------------------------
# Startpaket und Chargen
# --------------------------------------------------------------------------


def _write_katalog(path: Path) -> Path:
    import qea_writer

    return qea_writer.write_qea(
        {
            "ir_version": 1,
            "technology": {"profile": ""},
            "packages": [{"path": "Standards"}],
            "elements": [
                {"package": "Standards", "name": "Standard A", "stereotype": "System"},
                {"package": "Standards", "name": "Standard B", "stereotype": "ServiceSpecification"},
            ],
            "connectors": [],
            "diagrams": [],
        },
        path,
    )


def test_startpaket_inventar_lists_classes(tmp_path: Path) -> None:
    katalog = _write_katalog(tmp_path / "katalog.qea")
    inventar = eam_ai._startpaket_inventar(katalog)
    assert [name for name, _ in inventar] == ["Standard A", "Standard B"]
    assert dict(inventar)["Standard B"] == "ServiceSpecification"


def test_build_merges_startpaket_with_unchanged_ids(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    katalog = _write_katalog(tmp_path / "katalog.qea")
    vorher = {e["name"]: e.get("guid") for e in read_qea(katalog)["elements"]}
    report = eam_ai.build(
        mdg=MDG,
        text=source,
        out=tmp_path / "modell.qea",
        backend=make_backend(),
        findings_path=tmp_path / "findings.json",
        startpaket=katalog,
        sidecar=False,
    )
    assert report.exported is True
    nachher = read_qea(tmp_path / "modell.qea")
    nachher_namen = {e["name"]: e.get("guid") for e in nachher["elements"]}
    assert set(vorher) <= set(nachher_namen), "Standardelemente fehlen im Ergebnis"
    for name, guid in vorher.items():
        if guid:
            assert nachher_namen[name] == guid, f"{name}: Kennung wurde geaendert"
    assert report.elements == len(nachher["elements"])
    assert report.elements >= 2


def test_build_rejects_empty_startpaket(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    leer = _write_katalog(tmp_path / "leer.qea")
    import sqlite3

    con = sqlite3.connect(leer)
    con.execute("delete from t_object")
    con.commit()
    con.close()
    with pytest.raises(eam_ai.BuildError, match="keine Elemente"):
        eam_ai.build(
            mdg=MDG,
            text=source,
            out=tmp_path / "modell.qea",
            backend=make_backend(),
            findings_path=tmp_path / "findings.json",
            startpaket=leer,
            sidecar=False,
        )


def test_build_continues_existing_model(tmp_path: Path) -> None:
    """Zweiter Lauf knuepft an ein Modell an: Bestand bleibt, Neues kommt dazu."""
    erst = tmp_path / "erst.txt"
    erst.write_text("Der Dienst Lagebild ist ein ServicePort.\n", encoding="utf-8")
    erstes = eam_ai.build(
        mdg=MDG, text=erst, out=tmp_path / "teil1.qea",
        backend=make_backend({"elements": [
            {"name": "Dienst Lagebild", "stereotype": "ServiceSpecification",
             "notes": "A", "source_ref": "D1-S1", "confidence": 0.9}]}),
        findings_path=tmp_path / "f1.json", sidecar=False,
    )
    assert erstes.elements == 1

    zweit = tmp_path / "zweit.txt"
    zweit.write_text("Der Dienst Wetterbild ist ein ServicePort.\n", encoding="utf-8")
    zweites = eam_ai.build(
        mdg=MDG, text=zweit, out=tmp_path / "gesamt.qea",
        backend=make_backend({"elements": [
            {"name": "Dienst Wetterbild", "stereotype": "ServiceSpecification",
             "notes": "B", "source_ref": "D1-S1", "confidence": 0.9}]}),
        findings_path=tmp_path / "f2.json",
        modell=tmp_path / "teil1.qea",
        sidecar=False,
    )
    daten = read_qea(tmp_path / "gesamt.qea")
    namen = sorted(e["name"] for e in daten["elements"])
    assert namen == ["Dienst Lagebild", "Dienst Wetterbild"]
    assert zweites.elements == 2, "Bericht nennt den Gesamtstand"


def test_build_reuses_names_of_existing_model_in_prompt(tmp_path: Path) -> None:
    """Das Modell kennt den Bestand: der Prompt nennt die vorhandenen Namen."""
    erst = tmp_path / "erst.txt"
    erst.write_text(TEXT, encoding="utf-8")
    eam_ai.build(
        mdg=MDG, text=erst, out=tmp_path / "teil.qea",
        backend=make_backend(), findings_path=tmp_path / "f1.json", sidecar=False,
    )
    backend = make_backend()
    eam_ai.build(
        mdg=MDG, text=erst, out=tmp_path / "gesamt.qea", backend=backend,
        findings_path=tmp_path / "f2.json", modell=tmp_path / "teil.qea", sidecar=False,
    )
    prompt = backend.prompts[0]
    assert "Bereits erfasste Elemente" in prompt
    for name in ("Ablauf A", "Faehigkeit B", "Dienst C"):
        assert name in prompt


def test_build_rejects_missing_model(tmp_path: Path) -> None:
    source = tmp_path / "text.txt"
    source.write_text(TEXT, encoding="utf-8")
    with pytest.raises(eam_ai.BuildError, match="nicht gefunden"):
        eam_ai.build(
            mdg=MDG, text=source, out=tmp_path / "x.qea", backend=make_backend(),
            findings_path=tmp_path / "f.json",
            modell=tmp_path / "gibtsnicht.qea", sidecar=False,
        )


def test_build_keeps_ids_when_continuing(tmp_path: Path) -> None:
    """Fortsetzen aendert keine Kennung des Bestands."""
    erst = tmp_path / "erst.txt"
    erst.write_text(TEXT, encoding="utf-8")
    eam_ai.build(
        mdg=MDG, text=erst, out=tmp_path / "teil.qea",
        backend=make_backend(), findings_path=tmp_path / "f1.json", sidecar=False,
    )
    vorher = {e["name"]: e.get("guid") for e in read_qea(tmp_path / "teil.qea")["elements"]}
    eam_ai.build(
        mdg=MDG, text=erst, out=tmp_path / "gesamt.qea",
        backend=make_backend({"elements": [
            {"name": "Neues Element", "stereotype": "ServiceSpecification",
             "notes": "neu", "source_ref": "D1-S1", "confidence": 0.8}]}),
        findings_path=tmp_path / "f2.json", modell=tmp_path / "teil.qea", sidecar=False,
    )
    nachher = {e["name"]: e.get("guid") for e in read_qea(tmp_path / "gesamt.qea")["elements"]}
    for name, guid in vorher.items():
        if guid:
            assert nachher.get(name) == guid, f"{name}: Kennung geaendert"
    assert "Neues Element" in nachher


def test_build_counts_all_object_types(tmp_path: Path) -> None:
    """Ports und Objects zaehlen als Elemente -- nur Paketspiegel nicht."""
    import qea_writer

    basis = qea_writer.write_qea(
        {
            "ir_version": 1,
            "technology": {"profile": ""},
            "packages": [{"path": "Architektur"}],
            "elements": [
                {"package": "Architektur", "name": "Hafen", "stereotype": "Hafen",
                 "ea_type": "Port"},
                {"package": "Architektur", "name": "Behoerde", "stereotype": "Behoerde",
                 "ea_type": "Object"},
            ],
            "connectors": [],
            "diagrams": [],
        },
        tmp_path / "basis.qea",
    )
    quelle = tmp_path / "text.txt"
    quelle.write_text(TEXT, encoding="utf-8")
    report = eam_ai.build(
        mdg=MDG, text=quelle, out=tmp_path / "gesamt.qea", backend=make_backend(),
        findings_path=tmp_path / "f.json", modell=basis, sidecar=False,
    )
    gelesen = read_qea(tmp_path / "gesamt.qea")["elements"]
    assert len(gelesen) == 5, "2 aus der Basis + 3 aus dem Text"
    assert report.elements == 5, "Bericht zaehlt wie der Reader, nicht nur Class"
