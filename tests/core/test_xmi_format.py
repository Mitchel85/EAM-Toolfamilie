"""XMI 2.1 als Zielformat: Roundtrip, Querformat, Determinismus.

Der Vertrag: ``.xmi`` ist ein Ausgabeformat wie ``.qea`` -- dasselbe IR,
dieselbe Pruefung, dasselbe Governance-Gate. Diese Tests belegen:

1. Determinismus: gleiches IR -> gleiche Bytes.
2. Fixpoint: ``write(read(write(ir))) == write(ir)`` auf allen Fixtures.
3. Querformat: qea -> IR -> xmi -> IR ist inhaltsgleich zum qea-IR.
4. Laut statt still: kaputtes XML, doppelte IDs, haengende Verweise brechen ab.
5. Sonderfaelle: unbenannte Elemente, Namensgruppen, CR/LF in Notizen,
   Sichten mit Mitgliedern.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import xmi_reader
import xmi_writer
from qea_reader import read_qea

CORE = Path(__file__).resolve().parents[2] / "packages" / "core"
FIXTURES = CORE / "fixtures"

IR_FIXTURES = (
    "ir_roundtrip_mini.json",
    "ir_synthetic_mini.json",
    "ir_skeleton_arch_mini.json",
)


def _lade(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _rund(ir: dict, tmp_path: Path) -> tuple[dict, xmi_reader.ReadReport]:
    """IR schreiben und zuruecklesen."""
    daten = xmi_writer.render_bytes(ir)
    pfad = tmp_path / "modell.xmi"
    pfad.write_bytes(daten)
    zurueck, report = xmi_reader.read_xmi_ex(pfad)
    return zurueck, report


# --------------------------------------------------------------------------
# 1 + 2: Determinismus und Fixpoint
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", IR_FIXTURES)
def test_render_ist_deterministisch(name: str) -> None:
    ir = _lade(name)
    assert xmi_writer.render_bytes(ir) == xmi_writer.render_bytes(ir)


@pytest.mark.parametrize("name", IR_FIXTURES)
def test_fixpoint_ueber_roundtrip(name: str, tmp_path: Path) -> None:
    ir = _lade(name)
    daten = xmi_writer.render_bytes(ir)
    pfad = tmp_path / "modell.xmi"
    pfad.write_bytes(daten)
    zurueck, report = xmi_reader.read_xmi_ex(pfad)
    assert xmi_writer.render_bytes(zurueck) == daten
    assert report.warnings == ()


def test_zaehlt_wie_der_reader(tmp_path: Path) -> None:
    ir = _lade("ir_synthetic_mini.json")
    zurueck, report = _rund(ir, tmp_path)
    assert report.packages == len(ir["packages"])
    assert report.elements == len(ir["elements"])
    assert report.connectors == len(ir["connectors"])


# --------------------------------------------------------------------------
# 3: Querformat qea -> xmi -> IR
# --------------------------------------------------------------------------


def test_querformat_masc_ist_inhaltsgleich(tmp_path: Path) -> None:
    qea_pfad = FIXTURES / "Musterarchitektur_MASC.qea"
    if not qea_pfad.is_file():
        pytest.skip("MASC-Fixture fehlt")
    ir_qea = read_qea(qea_pfad)
    daten = xmi_writer.render_bytes(ir_qea)
    pfad = tmp_path / "masc.xmi"
    pfad.write_bytes(daten)
    ir_xmi, report = xmi_reader.read_xmi_ex(pfad)
    assert report.warnings == ()

    def signatur(ir: dict, schluessel: str, felder: tuple[str, ...]) -> list:
        return sorted(
            tuple(e.get(f, "") for f in felder) for e in ir[schluessel]
        )

    for schluessel, felder in (
        ("packages", ("path", "name", "stereotype", "notes")),
        (
            "elements",
            ("package", "name", "stereotype", "ea_type", "notes", "alias", "status"),
        ),
        (
            "connectors",
            ("source", "target", "stereotype", "ea_type", "name", "direction"),
        ),
    ):
        assert signatur(ir_qea, schluessel, felder) == signatur(
            ir_xmi, schluessel, felder
        ), f"{schluessel} weicht ab"

    def tags(ir: dict) -> list:
        aus = []
        for schluessel in ("packages", "elements", "connectors"):
            for e in ir[schluessel]:
                if e.get("tags"):
                    aus.append(
                        (schluessel, str(e.get("path") or e.get("name")), tuple(sorted(e["tags"].items())))
                    )
        return sorted(aus)

    assert tags(ir_qea) == tags(ir_xmi)


# --------------------------------------------------------------------------
# 4: Laut statt still
# --------------------------------------------------------------------------


def test_kaputtes_xml_bricht_ab(tmp_path: Path) -> None:
    pfad = tmp_path / "kaputt.xmi"
    pfad.write_text("<xmi:XMI><uml:Model>", encoding="utf-8")
    with pytest.raises(xmi_reader.XmiReaderError):
        xmi_reader.read_xmi(pfad)


def test_doppelte_id_bricht_ab(tmp_path: Path) -> None:
    inhalt = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xmi:XMI xmi:version="2.1">'
        '<uml:Model xmi:type="uml:Model" name="M">'
        '<packagedElement xmi:type="uml:Class" xmi:id="ID1" name="A"/>'
        '<packagedElement xmi:type="uml:Class" xmi:id="ID1" name="B"/>'
        "</uml:Model></xmi:XMI>"
    )
    pfad = tmp_path / "doppelt.xmi"
    pfad.write_text(inhalt, encoding="utf-8")
    with pytest.raises(xmi_reader.XmiReaderError):
        xmi_reader.read_xmi(pfad)


def test_haengende_idref_bricht_ab(tmp_path: Path) -> None:
    inhalt = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xmi:XMI xmi:version="2.1">'
        '<uml:Model xmi:type="uml:Model" name="M">'
        '<packagedElement xmi:type="uml:Class" xmi:id="ID1" name="A"/>'
        '<packagedElement xmi:type="uml:Dependency" xmi:id="ID2">'
        '<client xmi:idref="ID1"/><supplier xmi:idref="FEHLT"/>'
        "</packagedElement></uml:Model></xmi:XMI>"
    )
    pfad = tmp_path / "haengend.xmi"
    pfad.write_text(inhalt, encoding="utf-8")
    with pytest.raises(xmi_reader.XmiReaderError):
        xmi_reader.read_xmi(pfad)


def test_leeres_source_document_fuer_json_bricht_ab() -> None:
    import json_batch

    with pytest.raises(json_batch.JsonBatchError):
        json_batch.render_text(_lade("ir_roundtrip_mini.json"), source_document="")


# --------------------------------------------------------------------------
# 5: Sonderfaelle
# --------------------------------------------------------------------------


def test_unbenannte_und_gleichnamige_elemente(tmp_path: Path) -> None:
    ir = _lade("ir_roundtrip_mini.json")
    zurueck, _ = _rund(ir, tmp_path)
    # Unbenannte Elemente tragen ::#N, Namensgruppen ::name#N -- beide muessen
    # beim Schreiben wieder aufloesbar sein (plan_model ist der Beweis).
    daten = xmi_writer.render_bytes(zurueck)
    assert daten  # plan_model akzeptiert die Referenzen
    refs = [c["source"] for c in zurueck["connectors"]] + [
        c["target"] for c in zurueck["connectors"]
    ]
    assert any("::" in r for r in refs)


def test_notizen_mit_und_ohne_crlf_ueberleben(tmp_path: Path) -> None:
    ir = _lade("ir_roundtrip_mini.json")
    for element in ir["elements"]:
        if element.get("name") == "Knoten A":
            element["notes"] = "Zeile 1\r\nZeile 2\rZeile 3\nZeile 4"
    ir["elements"][0]["tags"] = {"mehrzeilig": "a\r\nb"}
    zurueck, _ = _rund(ir, tmp_path)
    wieder = {
        (e["package"], e["name"]): e.get("notes", "") for e in zurueck["elements"]
    }
    assert any("\r\n" in wert for wert in wieder.values())
    knoten_a = next(
        e for e in zurueck["elements"] if e.get("name") == "Knoten A"
    )
    assert knoten_a["notes"] == "Zeile 1\r\nZeile 2\rZeile 3\nZeile 4"
    tag_wert = next(
        e for e in zurueck["elements"] if e.get("tags", {}).get("mehrzeilig")
    )
    assert tag_wert["tags"]["mehrzeilig"] == "a\r\nb"


def test_technologie_wird_mitgefuehrt(tmp_path: Path) -> None:
    ir = _lade("ir_roundtrip_mini.json")
    assert ir.get("technology", {}).get("profile") == "MiniProfil"
    zurueck, _ = _rund(ir, tmp_path)
    assert zurueck.get("technology", {}).get("profile") == "MiniProfil"


def test_sichten_mit_mitgliedern_und_geometrie(tmp_path: Path) -> None:
    ir = _lade("ir_roundtrip_mini.json")
    element = ir["elements"][0]
    ref = f"{element['package']}::{element['name']}"
    ir["diagrams"] = [
        {
            "name": "Uebersicht",
            "package": ir["packages"][0]["path"],
            "type": "Custom",
            "members": [
                {
                    "element": ref,
                    "left": 10,
                    "top": 20,
                    "right": 210,
                    "bottom": 100,
                    "sequence": 0,
                }
            ],
        }
    ]
    zurueck, report = _rund(ir, tmp_path)
    assert report.diagrams == 1
    sicht = zurueck["diagrams"][0]
    assert sicht["name"] == "Uebersicht"
    assert sicht["package"] == ir["packages"][0]["path"]
    assert sicht["members"][0]["left"] == 10
    assert sicht["members"][0]["bottom"] == 100
