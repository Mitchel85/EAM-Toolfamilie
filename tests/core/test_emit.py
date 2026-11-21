"""Tests fuer emit.py -- IR zu .qea inklusive Herkunft.

Kein Netz, ausschliesslich synthetische Daten (keine echten Modelle, keine
Personendaten). DoD: ``pytest tests/test_emit.py`` gruen. Die Tests lesen die
Herkunfts-Tags aus der erzeugten .qea zurueck -- ueber ``qea_reader`` und
zusaetzlich direkt per SQLite, damit die Ablage in der Datei belegt ist.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

import emit as em
import extract as ex
from qea_reader import read_qea

FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"  # Monorepo
RULES_PATH = FIXTURES / "rules_validator.json"
PROVENANCE_NAMES = ("source_ref", "source_doc", "source_confidence")


def build_ir() -> dict:
    """Synthetisches IR: zwei KI-Elemente, eine KI-Beziehung, ein Import."""
    return {
        "ir_version": 1,
        "technology": {
            "profile": "TESTPROFIL",
            "name": "Synthetisches Modell",
            "version": "1.0",
        },
        "packages": [{"path": "Architektur"}, {"path": "Architektur/Ressourcen"}],
        "elements": [
            {
                "package": "Architektur/Ressourcen",
                "name": "System A",
                "stereotype": "System",
                "ea_type": "Class",
                "notes": "synthetisch",
                "tags": {
                    "source_ref": "D1-S1",
                    "source_doc": "D1",
                    "source_confidence": "0.90",
                },
            },
            {
                "package": "Architektur/Ressourcen",
                "name": "Dienst B",
                "stereotype": "ServicePort",
                "ea_type": "Class",
                "tags": {
                    "source_ref": "D1-S2",
                    "source_doc": "D1",
                    "source_confidence": "0.75",
                },
            },
            {
                "package": "Architektur/Ressourcen",
                "name": "Import C",
                "stereotype": "Capability",
                "ea_type": "Class",
                "notes": "aus Tabelle importiert",
                "tags": {"Reifegrad": "2"},
            },
        ],
        "connectors": [
            {
                "source": "Architektur/Ressourcen::System A",
                "target": "Architektur/Ressourcen::Dienst B",
                "stereotype": "Provides",
                "ea_type": "Dependency",
                "direction": "Source -> Destination",
                "tags": {
                    "source_ref": "D1-S1",
                    "source_doc": "D1",
                    "source_confidence": "0.80",
                },
            }
        ],
        "diagrams": [],
        "meta": {
            "quellen": {
                "D1-S1": "Satz eins mit Umlaut: Prüfung.",
                "D1-S2": "Satz zwei.",
                "D1-S9": "Nicht referenzierter Absatz.",
            }
        },
    }


def import_only_ir() -> dict:
    """IR wie aus dem Regelpfad: ein Element, keine Herkunft."""
    ir = build_ir()
    ir["elements"] = [{"package": "Architektur/Ressourcen", "name": "Import C",
                       "stereotype": "Capability", "ea_type": "Class",
                       "tags": {"Reifegrad": "2"}}]
    ir["connectors"] = []
    ir["meta"] = {}
    return ir


def by_name(ir: dict, name: str) -> dict:
    return next(element for element in ir["elements"] if element["name"] == name)


def sidecar_of(report: em.EmitReport) -> Path:
    """Begleitdatei als Pfad; ein fehlender Sidecar ist im Test ein Fehler."""
    assert report.quellen is not None
    return report.quellen


def write_ir(path: Path, ir: dict) -> Path:
    path.write_text(json.dumps(ir, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Erfolgsfall: Tags und Begleitdatei
# --------------------------------------------------------------------------


def test_emit_schreibt_qea_und_herkunft(tmp_path: Path) -> None:
    report = em.emit(build_ir(), tmp_path / "modell.qea")

    assert report.qea == tmp_path / "modell.qea" and report.qea.is_file()
    assert report.quellen == tmp_path / "quellen.json" and sidecar_of(report).is_file()
    assert (report.packages, report.elements, report.connectors) == (2, 3, 1)
    assert report.tagged_objects == 3
    assert report.tagged_elements == 2
    assert report.tagged_connectors == 1
    assert report.provenance_tags == 9
    assert report.refs == 2
    assert report.unused_quellen == 1
    assert report.verified is True
    assert len(report.digest) == 64

    back = read_qea(report.qea)
    assert by_name(back, "System A")["tags"] == {
        "source_ref": "D1-S1",
        "source_doc": "D1",
        "source_confidence": "0.90",
    }
    assert by_name(back, "Dienst B")["tags"] == {
        "source_ref": "D1-S2",
        "source_doc": "D1",
        "source_confidence": "0.75",
    }
    assert back["connectors"][0]["tags"] == {
        "source_ref": "D1-S1",
        "source_doc": "D1",
        "source_confidence": "0.80",
    }


def test_importiertes_element_bleibt_ohne_herkunft(tmp_path: Path) -> None:
    report = em.emit(build_ir(), tmp_path / "modell.qea")
    back = read_qea(report.qea)

    imported = by_name(back, "Import C")
    assert imported["tags"] == {"Reifegrad": "2"}
    assert not set(PROVENANCE_NAMES) & set(imported["tags"])


def test_tags_stehen_direkt_in_der_qea(tmp_path: Path) -> None:
    report = em.emit(build_ir(), tmp_path / "modell.qea")

    with sqlite3.connect(str(report.qea)) as con:
        con.row_factory = sqlite3.Row
        object_rows = con.execute(
            "SELECT o.Name, p.Property, p.Value FROM t_objectproperties p "
            "JOIN t_object o ON o.Object_ID = p.Object_ID "
            "WHERE p.Property IN (?, ?, ?) ORDER BY o.Name, p.Property",
            PROVENANCE_NAMES,
        ).fetchall()
        connector_rows = con.execute(
            "SELECT Property, Value FROM t_connectortag WHERE Property IN (?, ?, ?)",
            PROVENANCE_NAMES,
        ).fetchall()

    assert [(row["Name"], row["Property"], row["Value"]) for row in object_rows] == [
        ("Dienst B", "source_confidence", "0.75"),
        ("Dienst B", "source_doc", "D1"),
        ("Dienst B", "source_ref", "D1-S2"),
        ("System A", "source_confidence", "0.90"),
        ("System A", "source_doc", "D1"),
        ("System A", "source_ref", "D1-S1"),
    ]
    assert Counter(row["Property"] for row in connector_rows) == {
        "source_ref": 1,
        "source_doc": 1,
        "source_confidence": 1,
    }
    # Groessenbudget: kein Volltext im Tag -- die Saetze stehen nur in quellen.json.
    alle_werte = [row["Value"] for row in object_rows] + [row["Value"] for row in connector_rows]
    assert all(len(value) <= em.MAX_TAG_VALUE_CHARS for value in alle_werte)
    assert not any("Satz" in value for value in alle_werte)


def test_quellen_json_enthaelt_nur_referenzierte_saetze(tmp_path: Path) -> None:
    report = em.emit(build_ir(), tmp_path / "modell.qea")
    text = sidecar_of(report).read_text(encoding="utf-8")
    data = json.loads(text)

    assert data == {
        "D1-S1": "Satz eins mit Umlaut: Prüfung.",
        "D1-S2": "Satz zwei.",
    }
    assert "D1-S9" not in data
    assert "Prüfung" in text and "\\u" not in text
    assert text.endswith("\n")


def test_quellen_json_natuerlich_sortiert(tmp_path: Path) -> None:
    ir = build_ir()
    ir["elements"][0]["tags"].update({"source_ref": "D1-S10", "source_doc": "D1"})
    ir["elements"][1]["tags"].update({"source_ref": "D1-S2", "source_doc": "D1"})
    ir["elements"][2]["tags"] = {
        "source_ref": "D2-S1",
        "source_doc": "D2",
        "source_confidence": "0.60",
    }
    ir["connectors"][0]["tags"].update({"source_ref": "D2-S1", "source_doc": "D2"})
    ir["meta"]["quellen"] = {
        "D1-S2": "zwei",
        "D1-S10": "zehn",
        "D2-S1": "dokument zwei",
    }

    report = em.emit(ir, tmp_path / "modell.qea")
    data = json.loads(sidecar_of(report).read_text(encoding="utf-8"))
    assert list(data) == ["D1-S2", "D1-S10", "D2-S1"]


def test_emit_ist_deterministisch(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = em.emit(build_ir(), tmp_path / "a" / "modell.qea")
    second = em.emit(build_ir(), tmp_path / "b" / "modell.qea")

    assert first.qea.read_bytes() == second.qea.read_bytes()
    assert sidecar_of(first).read_bytes() == sidecar_of(second).read_bytes()
    assert first.digest == second.digest

    repeated = em.emit(build_ir(), tmp_path / "a" / "modell.qea")
    assert repeated.digest == first.digest


def test_begleitdatei_pfad_ueberschreibbar(tmp_path: Path) -> None:
    ziel = tmp_path / "modell.qea"
    report = em.emit(build_ir(), ziel, quellen_path=tmp_path / "belege.json")

    assert report.quellen == tmp_path / "belege.json"
    assert sidecar_of(report).is_file()
    assert not (tmp_path / "quellen.json").exists()


def test_no_quellen_unterdrueckt_begleitdatei(tmp_path: Path) -> None:
    report = em.emit(build_ir(), tmp_path / "modell.qea", sidecar=False)

    assert report.quellen is None
    assert not (tmp_path / "quellen.json").exists()
    assert report.provenance_tags == 9
    assert by_name(read_qea(report.qea), "System A")["tags"]["source_ref"] == "D1-S1"


def test_no_verify_schaltet_ruecklesung_ab(tmp_path: Path) -> None:
    report = em.emit(build_ir(), tmp_path / "modell.qea", verify=False)
    assert report.verified is False
    assert report.qea.is_file()


# --------------------------------------------------------------------------
# Import ohne Herkunft
# --------------------------------------------------------------------------


def test_importmodell_ohne_herkunft_schreibt_keine_begleitdatei(tmp_path: Path) -> None:
    report = em.emit(import_only_ir(), tmp_path / "modell.qea")

    assert report.quellen is None
    assert report.tagged_objects == 0
    assert report.provenance_tags == 0
    assert report.refs == 0
    assert not (tmp_path / "quellen.json").exists()
    assert by_name(read_qea(report.qea), "Import C")["tags"] == {"Reifegrad": "2"}


def test_meta_ist_ohne_herkunft_frei(tmp_path: Path) -> None:
    """IR_SPEC: meta ist freier Inhalt; ohne Herkunft wird es nicht ausgewertet."""
    ir = import_only_ir()
    ir["meta"] = ["frei"]

    report = em.emit(ir, tmp_path / "modell.qea")
    assert report.quellen is None
    assert report.unused_quellen == 0


def test_explizite_begleitdatei_ohne_herkunft_ist_ein_fehler(tmp_path: Path) -> None:
    ziel = tmp_path / "modell.qea"
    with pytest.raises(em.EmitError, match="keine Herkunft"):
        em.emit(import_only_ir(), ziel, quellen_path=tmp_path / "quellen.json")
    assert not ziel.exists()
    assert not (tmp_path / "quellen.json").exists()


# --------------------------------------------------------------------------
# Kaputte Herkunft: laut, ohne Ausgabe
# --------------------------------------------------------------------------


def _half_provenance(ir: dict) -> None:
    ir["elements"][0]["tags"].pop("source_confidence")


def _only_two_tags(ir: dict) -> None:
    ir["elements"][0]["tags"] = {"source_doc": "D1", "source_confidence": "0.90"}


def _numeric_confidence(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_confidence"] = 0.9


def _empty_value(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_doc"] = ""


def _overlong_value(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_ref"] = "D1-S1 " + "x" * em.MAX_TAG_VALUE_CHARS


def _fulltext_as_ref(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_ref"] = "Das System A erbringt den Dienst B."


def _doc_mismatch(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_doc"] = "D2"


def _confidence_short(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_confidence"] = "0.8"


def _confidence_integer(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_confidence"] = "1"


def _confidence_three_decimals(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_confidence"] = "0.855"


def _confidence_out_of_range(ir: dict) -> None:
    ir["elements"][0]["tags"]["source_confidence"] = "1.01"


def _tags_not_mapping(ir: dict) -> None:
    ir["elements"][0]["tags"] = ["source_ref"]


def _meta_not_mapping(ir: dict) -> None:
    ir["meta"] = []


def _quellen_not_mapping(ir: dict) -> None:
    ir["meta"]["quellen"] = []


def _missing_sentence(ir: dict) -> None:
    ir["elements"][0]["tags"].update({"source_ref": "D1-S3", "source_doc": "D1"})


def _empty_sentence(ir: dict) -> None:
    ir["meta"]["quellen"]["D1-S1"] = "   "


def _sentence_not_string(ir: dict) -> None:
    ir["meta"]["quellen"]["D1-S1"] = 42


@pytest.mark.parametrize(
    ("tweak", "muster"),
    [
        (_half_provenance, "unvollstaendige Herkunft"),
        (_only_two_tags, "unvollstaendige Herkunft"),
        (_numeric_confidence, "Zeichenkette"),
        (_empty_value, "ist leer"),
        (_overlong_value, "Budget"),
        (_fulltext_as_ref, "Belegnummer"),
        (_doc_mismatch, "passt nicht"),
        (_confidence_short, "kanonisch"),
        (_confidence_integer, "kanonisch"),
        (_confidence_three_decimals, "kanonisch"),
        (_confidence_out_of_range, "kanonisch"),
        (_tags_not_mapping, "tags muss ein Objekt sein"),
        (_meta_not_mapping, "meta: Objekt erwartet"),
        (_quellen_not_mapping, "meta.quellen: Objekt erwartet"),
        (_missing_sentence, "kein Satz"),
        (_empty_sentence, "leerer Satz"),
        (_sentence_not_string, "Zeichenkette erwartet"),
    ],
)
def test_kaputte_herkunft_bricht_laut_ab(
    tmp_path: Path, tweak, muster: str
) -> None:
    ir = build_ir()
    tweak(ir)

    with pytest.raises(em.EmitError, match=muster):
        em.emit(ir, tmp_path / "modell.qea")

    assert not (tmp_path / "modell.qea").exists()
    assert not (tmp_path / "quellen.json").exists()


def test_fehler_laesst_bestehende_zieldatei_unberuehrt(tmp_path: Path) -> None:
    ziel = tmp_path / "modell.qea"
    ziel.write_bytes(b"ALT")
    ir = build_ir()
    _half_provenance(ir)

    with pytest.raises(em.EmitError):
        em.emit(ir, ziel)

    assert ziel.read_bytes() == b"ALT"


def test_leeres_modell_ist_ein_lauter_fehler(tmp_path: Path) -> None:
    ir = build_ir()
    ir["elements"] = []
    ir["connectors"] = []

    with pytest.raises(em.EmitError, match="kein Element"):
        em.emit(ir, tmp_path / "modell.qea")
    assert not (tmp_path / "modell.qea").exists()


def test_begleitdatei_darf_nicht_die_qea_sein(tmp_path: Path) -> None:
    ziel = tmp_path / "modell.qea"
    with pytest.raises(em.EmitError, match="selbe Pfad"):
        em.emit(build_ir(), ziel, quellen_path=ziel)
    assert not ziel.exists()


def test_ruecklesung_erkennt_abweichung(tmp_path: Path, monkeypatch) -> None:
    """Die Verifikation muss wirklich laufen -- ein Writer ohne Tags faellt auf."""
    real = em.write_qea

    def without_confidence(ir, target):
        stripped = copy.deepcopy(ir)
        for element in stripped["elements"]:
            element.get("tags", {}).pop("source_confidence", None)
        return real(stripped, target)

    monkeypatch.setattr(em, "write_qea", without_confidence)

    with pytest.raises(em.EmitError, match="Ruecklesung"):
        em.emit(build_ir(), tmp_path / "modell.qea")
    assert not (tmp_path / "modell.qea").exists()
    assert not (tmp_path / "quellen.json").exists()


def test_verify_funktion_meldet_unterschied(tmp_path: Path) -> None:
    report = em.emit(build_ir(), tmp_path / "modell.qea")
    tampered = build_ir()
    tampered["elements"][0]["tags"].pop("source_confidence")

    with pytest.raises(em.EmitError, match="Ruecklesung"):
        em.verify_qea_provenance(report.qea, tampered)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_schreibt_und_meldet(tmp_path: Path, capsys) -> None:
    ir_path = write_ir(tmp_path / "ir.json", build_ir())
    ziel = tmp_path / "modell.qea"

    code = em.main([str(ir_path), str(ziel)])

    captured = capsys.readouterr()
    assert code == 0
    assert "geschrieben" in captured.out
    assert "9 Herkunfts-Tags" in captured.out
    assert "quellen.json" in captured.out
    assert "Herkunft:" in captured.err
    assert ziel.is_file()
    assert (tmp_path / "quellen.json").is_file()


def test_cli_quiet_unterdrueckt_fortschritt(tmp_path: Path, capsys) -> None:
    ir_path = write_ir(tmp_path / "ir.json", build_ir())
    code = em.main([str(ir_path), str(tmp_path / "modell.qea"), "-q"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert "geschrieben" in captured.out


def test_cli_fehler_exitcode_1(tmp_path: Path, capsys) -> None:
    ir = build_ir()
    _half_provenance(ir)
    ir_path = write_ir(tmp_path / "ir.json", ir)

    code = em.main([str(ir_path), str(tmp_path / "modell.qea")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "FEHLER:" in captured.err
    assert "unvollstaendige Herkunft" in captured.err
    assert not (tmp_path / "modell.qea").exists()


def test_cli_quellen_optionen_schliessen_sich_aus(tmp_path: Path) -> None:
    ir_path = write_ir(tmp_path / "ir.json", build_ir())
    with pytest.raises(SystemExit) as excinfo:
        em.main([
            str(ir_path),
            str(tmp_path / "modell.qea"),
            "--quellen",
            str(tmp_path / "q.json"),
            "--no-quellen",
        ])
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------
# Zusammenspiel mit extract.py
# --------------------------------------------------------------------------

PROSE = (
    "Das Lagebildsystem ist ein System der Lagebearbeitung.\n"
    "Es stellt den Dienst Lagebild bereit.\n"
    "\n"
    "Der Dienst Lagebild ist ein ServicePort des Lagebildsystems.\n"
)


def test_ir_aus_extract_laesst_sich_emittieren(tmp_path: Path) -> None:
    rules = ex.load_rules(RULES_PATH)
    segments = ex.split_documents(PROSE)
    answer = {
        "elements": [
            {
                "name": "Lagebildsystem",
                "stereotype": "System",
                "notes": "System der Lagebearbeitung",
                "source_ref": "D1-S1",
                "confidence": 0.9,
            },
            {
                "name": "Dienst Lagebild",
                "stereotype": "ServicePort",
                "source_ref": "D1-S2",
                "confidence": 0.8,
            },
        ],
        "connectors": [
            {
                "source": "Lagebildsystem",
                "target": "Dienst Lagebild",
                "stereotype": "Provides",
                "source_ref": "D1-S1",
                "confidence": 0.7,
            }
        ],
    }
    result = ex.answer_to_ir(answer, segments, rules)

    report = em.emit(result.ir, tmp_path / "modell.qea")

    back = read_qea(report.qea)
    assert by_name(back, "Lagebildsystem")["tags"] == {
        "source_ref": "D1-S1",
        "source_doc": "D1",
        "source_confidence": "0.90",
    }
    assert by_name(back, "Dienst Lagebild")["tags"]["source_confidence"] == "0.80"
    assert back["connectors"][0]["tags"]["source_confidence"] == "0.70"

    data = json.loads(sidecar_of(report).read_text(encoding="utf-8"))
    assert set(data) == {"D1-S1", "D1-S2"}
    assert data["D1-S1"].startswith("Das Lagebildsystem")
    assert report.unused_quellen == 0
