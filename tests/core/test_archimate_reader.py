"""ArchiMate lesen: XML -> IR -- Felder, Identitaet und Rundlauf.

Der Vertrag: ``archimate_reader`` ist die Umkehrung von ``archimate_writer``.
Derselbe IR, dieselben Kennungen. Diese Tests belegen:

1. **Lesen** -- Elemente, Beziehungen, Properties und der Organisationsbaum
   werden zu IR-Feldern, die ``qea_reader`` genauso liefert.
2. **Identitaet** -- die XML-Kennung ueberlebt den Rueckweg, auch wenn sie
   nicht aus einer GUID ableitbar ist.
3. **Rundlauf** -- ``qea -> XML -> IR -> XML`` ist byte-identisch, und das IR
   ist nach dem zweiten Lesen gleich dem nach dem ersten.
4. **Laute Fehler** -- kaputtes XML, unbekannte Typen und haengende Endpunkte
   brechen ab; es gibt keinen stillen Teil-Erfolg.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import archimate_reader as ar
import archimate_writer as aw
from archimate_reader import ArchimateReaderError
from qea_reader import read_qea_ex

NS = "{http://www.opengroup.org/xsd/archimate/3.0/}"
CORE = Path(__file__).resolve().parents[2] / "packages" / "core"
FIXTURES = CORE / "fixtures"
MASC = FIXTURES / "Musterarchitektur_MASC.qea"
TESTARCHITEKTUR = Path("/root/hermes-workspace/admbw-qea-editor/Testarchitektur.qea")

FREMD = """<?xml version="1.0" encoding="utf-8"?>
<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       identifier="id-model-fremd" version="3.2">
  <name xml:lang="en">Fremdes Modell</name>
  <elements>
    <element identifier="id-11111111-1111-1111-1111-111111111111" xsi:type="BusinessActor">
      <name xml:lang="de">Kunde</name>
      <documentation xml:lang="de">Ein Kunde.</documentation>
      <properties>
        <property propertyDefinitionRef="prop-custom"><value xml:lang="de">Wert</value></property>
      </properties>
    </element>
    <element identifier="id-22222222-2222-2222-2222-222222222222" xsi:type="BusinessService">
      <name xml:lang="de">Service</name>
    </element>
    <element identifier="id-33333333-3333-3333-3333-333333333333" xsi:type="Grouping">
      <name xml:lang="de">Gruppe</name>
    </element>
  </elements>
  <relationships>
    <relationship identifier="id-44444444-4444-4444-4444-444444444444" xsi:type="Serving"
                  source="id-22222222-2222-2222-2222-222222222222"
                  target="id-11111111-1111-1111-1111-111111111111">
      <name xml:lang="de">bedient</name>
    </relationship>
  </relationships>
  <organizations>
    <item identifier="id-org-1">
      <label xml:lang="de">Fachlich</label>
      <item identifierRef="id-11111111-1111-1111-1111-111111111111"/>
      <item identifierRef="id-22222222-2222-2222-2222-222222222222"/>
    </item>
  </organizations>
  <propertyDefinitions>
    <propertyDefinition identifier="prop-custom" type="string"><name xml:lang="en">Quelle</name></propertyDefinition>
  </propertyDefinitions>
</model>
"""


def _schreiben(tmp_path: Path, text: str, name: str = "modell.xml") -> Path:
    ziel = tmp_path / name
    ziel.write_text(text, encoding="utf-8")
    return ziel


def _admbw_element(identifier: str, typ: str, name: str, **properties: str) -> str:
    """Kleines Element im Zuschnitt des Writers (Properties als Bloecke)."""
    bloecke = "".join(
        f'<property propertyDefinitionRef="{ref}"><value xml:lang="de">{wert}</value></property>'
        for ref, wert in properties.items()
    )
    return (
        f'<element identifier="{identifier}" xsi:type="{typ}">'
        f'<name xml:lang="de">{name}</name><properties>{bloecke}</properties></element>'
    )


# --------------------------------------------------------------------------
# 1. Lesen
# --------------------------------------------------------------------------
def test_liest_elemente_beziehungen_und_properties(tmp_path: Path):
    ir, report = ar.read_archimate_ex(_schreiben(tmp_path, FREMD))

    assert [e["name"] for e in ir["elements"]] == ["Kunde", "Service", "Gruppe"]
    assert ir["elements"][0]["notes"] == "Ein Kunde."
    assert ir["elements"][0]["ea_type"] == "BusinessActor"
    assert ir["elements"][0]["tags"] == {"Quelle": "Wert"}
    assert report.imported_elements == 3
    assert report.property_definitions == 1

    (connector,) = ir["connectors"]
    assert connector["ea_type"] == "Serving"
    assert connector["name"] == "bedient"
    assert connector["source"] == "Fachlich::Service"
    assert connector["target"] == "Fachlich::Kunde"
    # Die Kennung ist aus der GUID-Form ableitbar -- kein Sonderfeld noetig.
    assert connector["guid"] == "44444444-4444-4444-4444-444444444444"
    assert "identifier" not in connector

    assert ir["meta"]["archimate"]["name"] == "Fremdes Modell"
    assert ir["meta"]["archimate"]["identifier"] == "id-model-fremd"


def test_dokumentreihenfolge_bleibt_erhalten(tmp_path: Path):
    """Der Writer schreibt in IR-Reihenfolge -- Lesen darf nicht sortieren."""
    ir = ar.read_archimate(_schreiben(tmp_path, FREMD))
    assert [e["name"] for e in ir["elements"]] == ["Kunde", "Service", "Gruppe"]


def test_paketpfad_aus_property(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m" version="3.2">'
        "<name>M</name><elements>"
        + _admbw_element(
            "id-aaaaaaaa-1111-1111-1111-111111111111", "Capability", "Faehigkeit",
            **{"prop-admbw-stereotype": "Capability", "prop-admbw-metatype": "Class",
               "prop-paketpfad": "A/B"},
        )
        + "</elements></model>"
    )
    ir, report = ar.read_archimate_ex(_schreiben(tmp_path, xml))
    (element,) = ir["elements"]
    assert element["package"] == "A/B"
    assert element["stereotype"] == "Capability"
    assert element["ref"] == "A/B::Faehigkeit"
    assert report.imported_elements == 0
    # Elternpakete werden deklariert, damit der IR-Vertrag vollstaendig ist.
    assert [p["path"] for p in ir["packages"]] == ["A", "A/B"]


def test_organisation_liefert_paketpfad(tmp_path: Path):
    ir = ar.read_archimate(_schreiben(tmp_path, FREMD))
    pfade = {e["name"]: e["package"] for e in ir["elements"]}
    assert pfade == {"Kunde": "Fachlich", "Service": "Fachlich", "Gruppe": ""}


def test_gleiche_namen_bekommen_vorkommensnummer(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m" version="3.2">'
        "<name>M</name><elements>"
        + _admbw_element("id-aaaaaaaa-1111-1111-1111-111111111111", "Grouping", "Doppelt",
                         **{"prop-admbw-metatype": "Class", "prop-paketpfad": "P"})
        + _admbw_element("id-bbbbbbbb-2222-2222-2222-222222222222", "Grouping", "Doppelt",
                         **{"prop-admbw-metatype": "Object", "prop-paketpfad": "P"})
        + "</elements></model>"
    )
    ir = ar.read_archimate(_schreiben(tmp_path, xml))
    refs = [e["ref"] for e in ir["elements"]]
    assert refs == ["P::Doppelt#1", "P::Doppelt#2"]  # Object vor Class (ea_type)
    assert len(set(refs)) == 2


def test_leeres_modell_ist_lesbar(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" identifier="id-m" version="3.2">'
        "<name>Leer</name></model>"
    )
    ir, report = ar.read_archimate_ex(_schreiben(tmp_path, xml))
    assert ir["elements"] == [] and ir["connectors"] == []
    assert report.elements == 0


# --------------------------------------------------------------------------
# 2. Laute Fehler
# --------------------------------------------------------------------------
def test_kaputtes_xml_bricht_ab(tmp_path: Path):
    with pytest.raises(ArchimateReaderError, match="nicht parsebar"):
        ar.read_archimate(_schreiben(tmp_path, "<model><elements>"))


def test_falsches_wurzelelement_bricht_ab(tmp_path: Path):
    with pytest.raises(ArchimateReaderError, match="<model>"):
        ar.read_archimate(_schreiben(tmp_path, '<xmi xmlns="http://x"/>'))


def test_falscher_namensraum_bricht_ab(tmp_path: Path):
    with pytest.raises(ArchimateReaderError, match="Namensraum"):
        ar.read_archimate(_schreiben(
            tmp_path, '<model xmlns="http://example.org/irgendwas" identifier="id-m"/>'
        ))


def test_fehlende_kennung_bricht_ab(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m">'
        '<elements><element xsi:type="BusinessActor"><name>A</name></element></elements></model>'
    )
    with pytest.raises(ArchimateReaderError, match="identifier fehlt"):
        ar.read_archimate(_schreiben(tmp_path, xml))


def test_fehlender_typ_bricht_ab(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" identifier="id-m">'
        '<elements><element identifier="id-1"><name>A</name></element></elements></model>'
    )
    with pytest.raises(ArchimateReaderError, match="xsi:type fehlt"):
        ar.read_archimate(_schreiben(tmp_path, xml))


def test_unbekannter_typ_bricht_ab(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m">'
        '<elements><element identifier="id-1" xsi:type="Kaffeetasse"/></elements></model>'
    )
    with pytest.raises(ArchimateReaderError, match="unbekannter ArchiMate-Typ"):
        ar.read_archimate(_schreiben(tmp_path, xml))


def test_beziehungstyp_als_element_bricht_ab(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m">'
        '<elements><element identifier="id-1" xsi:type="Serving"/></elements></model>'
    )
    with pytest.raises(ArchimateReaderError, match="Beziehungstyp"):
        ar.read_archimate(_schreiben(tmp_path, xml))


def test_haengender_endpunkt_bricht_ab(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m">'
        '<elements><element identifier="id-1" xsi:type="BusinessActor"/></elements>'
        '<relationships><relationship identifier="id-r" xsi:type="Serving" '
        'source="id-1" target="id-fehlt"/></relationships></model>'
    )
    with pytest.raises(ArchimateReaderError, match="Ziel"):
        ar.read_archimate(_schreiben(tmp_path, xml))


def test_doppelte_kennung_bricht_ab(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m">'
        '<elements><element identifier="id-1" xsi:type="BusinessActor"/>'
        '<element identifier="id-1" xsi:type="BusinessRole"/></elements></model>'
    )
    with pytest.raises(ArchimateReaderError, match="doppelte Element-Kennung"):
        ar.read_archimate(_schreiben(tmp_path, xml))


def test_strikter_modus_macht_warnungen_zu_fehlern(tmp_path: Path):
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m">'
        '<elements><element identifier="id-1" xsi:type="BusinessActor"/></elements></model>'
    )
    datei = _schreiben(tmp_path, xml)
    ir, report = ar.read_archimate_ex(datei)
    assert report.warnings and ir["elements"][0]["name"] == ""
    with pytest.raises(ArchimateReaderError, match="strikter Modus"):
        ar.read_archimate_ex(datei, strict=True)


# --------------------------------------------------------------------------
# 3. Rundlauf
# --------------------------------------------------------------------------
def test_rundlauf_masc_ist_byte_identisch(tmp_path: Path):
    """qea -> XML -> IR -> XML: gleiche Bytes, gleiches IR."""
    ir0, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    xml1 = tmp_path / "masc1.xml"
    bericht = aw.write_archimate(ir0, xml1, modellname="MASC")

    ir1, gelesen = ar.read_archimate_ex(xml1)
    # Keine Magic Numbers: der Reader muss genau das sehen, was der Writer
    # gemeldet hat. Wie viele Elemente der Konverter bewusst auslaesst
    # (Darstellung, BPMN-Mechanik, Ports), steht in seinem Report -- nicht hier.
    assert gelesen.elements == bericht.elements
    assert gelesen.relationships == bericht.relationships
    assert gelesen.model_name == "MASC"
    assert gelesen.imported_elements == 0

    # Ohne modellname: der Name kommt aus meta.archimate -- der Rundlauf
    # braucht keine Zusatzangabe.
    xml2 = tmp_path / "masc2.xml"
    aw.write_archimate(ir1, xml2)
    assert xml1.read_bytes() == xml2.read_bytes()

    ir2, _ = ar.read_archimate_ex(xml2)
    assert ir1 == ir2
    assert json.dumps(ir1, sort_keys=True) == json.dumps(ir2, sort_keys=True)

    root = ET.fromstring(xml1.read_bytes())
    ids = {e.get("identifier") for e in root.iter(f"{NS}element")}
    assert len(ids) == gelesen.elements
    for rel in root.iter(f"{NS}relationship"):
        assert rel.get("source") in ids and rel.get("target") in ids


@pytest.mark.skipif(not TESTARCHITEKTUR.is_file(), reason="Testarchitektur.qea fehlt")
def test_rundlauf_testarchitektur_ist_byte_identisch(tmp_path: Path):
    ir0, _ = read_qea_ex(TESTARCHITEKTUR, with_refs=True, with_owners=True)
    xml1 = tmp_path / "test1.xml"
    bericht = aw.write_archimate(ir0, xml1, modellname="Testarchitektur")
    ir1, gelesen = ar.read_archimate_ex(xml1)
    xml2 = tmp_path / "test2.xml"
    aw.write_archimate(ir1, xml2)
    assert xml1.read_bytes() == xml2.read_bytes()
    assert ar.read_archimate(xml2) == ir1
    assert gelesen.elements == bericht.elements
    assert gelesen.relationships == bericht.relationships


def test_junction_behaelt_seine_beziehung(tmp_path: Path):
    """AndJunction/OrJunction sind fuer die Matrix ein ``Junction``.

    Ohne die Normalisierung faellt jede Kante an einer Verzweigung auf
    ``Association`` zurueck -- ein stiller Bedeutungsverlust.
    """
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-m" version="3.2">'
        "<name>J</name><elements>"
        '<element identifier="id-j" xsi:type="AndJunction"><name>und</name></element>'
        '<element identifier="id-a" xsi:type="BusinessActor"><name>Akteur</name></element>'
        "</elements><relationships>"
        '<relationship identifier="id-r" xsi:type="Triggering" source="id-j" target="id-a"/>'
        "</relationships></model>"
    )
    ir = ar.read_archimate(_schreiben(tmp_path, xml))
    ziel = tmp_path / "j.xml"
    aw.write_archimate(ir, ziel)
    root = ET.fromstring(ziel.read_bytes())
    typen = [r.get(f"{{http://www.w3.org/2001/XMLSchema-instance}}type")
             for r in root.iter(f"{NS}relationship")]
    assert typen == ["Triggering"]


def test_rundlauf_fremdes_modell_ist_fixpunkt(tmp_path: Path):
    """Ein fremdes Modell wird beim ersten Export normalisiert, danach stabil.

    Erwartete Normalisierung: der Writer schreibt seine vier Haus-Properties
    (Metaklasse, Paketpfad) und laesst eigene Properties/Organisationen weg.
    Ab dem ersten eigenen Export ist die Datei ein Fixpunkt.
    """
    ir1, report = ar.read_archimate_ex(_schreiben(tmp_path, FREMD))
    assert report.imported_elements == 3
    xml1 = tmp_path / "fremd1.xml"
    aw.write_archimate(ir1, xml1)

    ir2, _ = ar.read_archimate_ex(xml1)
    xml2 = tmp_path / "fremd2.xml"
    aw.write_archimate(ir2, xml2)
    assert xml1.read_bytes() == xml2.read_bytes()
    assert ar.read_archimate(xml2) == ir2

    # Typen und Kennungen haben den Weg ueberlebt.
    root = ET.fromstring(xml1.read_bytes())
    typen = sorted(e.get(f"{{http://www.w3.org/2001/XMLSchema-instance}}type")
                   for e in root.iter(f"{NS}element"))
    assert typen == ["BusinessActor", "BusinessService", "Grouping"]
    assert [e.get("identifier") for e in root.iter(f"{NS}element")] == [
        "id-11111111-1111-1111-1111-111111111111",
        "id-22222222-2222-2222-2222-222222222222",
        "id-33333333-3333-3333-3333-333333333333",
    ]


@pytest.mark.skipif(not MASC.is_file(), reason="Musterarchitektur_MASC.qea fehlt")
def test_gelesenes_ir_ist_fuer_den_qea_writer_gueltig(tmp_path: Path):
    """IR-Kompatibilitaet heisst: die uebrigen Werkzeuge lesen es ohne Umbau."""
    from qea_writer import plan_model, write_qea

    ir0, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    xml = tmp_path / "masc.xml"
    aw.write_archimate(ir0, xml, modellname="MASC")
    ir1 = ar.read_archimate(xml)

    plan = plan_model(ir1)
    assert len(plan.elements) == len(ir1["elements"])
    assert len(plan.connectors) == len(ir1["connectors"])
    ziel = tmp_path / "rueck.qea"
    write_qea(ir1, ziel)
    assert ziel.stat().st_size > 0


@pytest.mark.skipif(not MASC.is_file(), reason="Musterarchitektur_MASC.qea fehlt")
def test_gelesenes_ir_laeuft_durch_den_validator(tmp_path: Path):
    """IR-Kompatibilitaet heisst auch: die Pruefung liest es ohne Umbau.

    ``validate_model`` baut aus dem IR ein ``Model`` (Pakete, Elemente,
    Endpunkte). Ein Strukturbruch -- fehlende Pflichtfelder, unbekannte
    Referenzen -- wuerde dort als ``ValidatorError`` auffallen, nicht als
    Befund. Geprueft wird darum: kein Abbruch, wohlgeformte Befunde,
    wiederholbar.
    """
    import mdg_parser
    import validator

    ir0, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    xml = tmp_path / "masc.xml"
    aw.write_archimate(ir0, xml, modellname="MASC")
    ir1 = ar.read_archimate(xml)

    rules = validator.build_rules(mdg_parser.parse_mdg(FIXTURES / "admbw_auszug.xml"))
    findings = validator.validate_model(ir1, rules)

    assert all({"severity", "object", "check", "message"} <= set(f) for f in findings)
    assert validator.validate_model(ir1, rules) == findings


def test_lesen_ist_deterministisch(tmp_path: Path):
    ir0, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    xml = tmp_path / "masc.xml"
    aw.write_archimate(ir0, xml)
    assert ar.render_json(ar.read_archimate(xml)) == ar.render_json(ar.read_archimate(xml))


# --------------------------------------------------------------------------
# 4. CLI
# --------------------------------------------------------------------------
def test_cli_schreibt_ir_json(tmp_path: Path):
    quelle = _schreiben(tmp_path, FREMD)
    ziel = tmp_path / "ir.json"
    assert ar.main(["--in", str(quelle), "--out", str(ziel)]) == 0
    daten = json.loads(ziel.read_text(encoding="utf-8"))
    assert daten["ir_version"] == 1
    assert len(daten["elements"]) == 3


def test_cli_meldet_fehler(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    quelle = _schreiben(tmp_path, "<kaputt>")
    assert ar.main(["--in", str(quelle)]) == 1
    assert "FEHLER" in capsys.readouterr().err


@pytest.mark.skipif(not MASC.is_file(), reason="Fixture Musterarchitektur fehlt")
def test_cli_rundlauf_ohne_name_ist_byte_identisch(tmp_path: Path):
    """Der Modulaufruf darf den Modellkopf nicht durch den Dateinamen ersetzen.

    Sonst haengt die Byte-Identitaet am Dateinamen des Zwischen-IR -- die
    dokumentierte Strecke ``XML -> IR -> XML`` waere nur zufaellig stabil.
    """
    ir0, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    xml1 = tmp_path / "masc.xml"
    aw.write_archimate(ir0, xml1, modellname="Musterarchitektur_MASC")

    zwischen = tmp_path / "ir.json"
    assert ar.main(["--in", str(xml1), "--out", str(zwischen)]) == 0

    xml2 = tmp_path / "masc2.xml"
    assert aw.main(["--ir", str(zwischen), "--out", str(xml2)]) == 0
    assert xml1.read_bytes() == xml2.read_bytes()


@pytest.mark.skipif(not MASC.is_file(), reason="Fixture Musterarchitektur fehlt")
def test_eam_ai_cli_rundlauf_ohne_name(tmp_path: Path):
    """Die dokumentierte Strecke: ``eam-ai archimate-read`` dann ``archimate``."""
    import eam_ai

    ir0, _ = read_qea_ex(MASC, with_refs=True, with_owners=True)
    xml1 = tmp_path / "masc.xml"
    aw.write_archimate(ir0, xml1, modellname="Musterarchitektur_MASC")

    zwischen = tmp_path / "ir.json"
    assert eam_ai.main(["archimate-read", "--in", str(xml1), "--out", str(zwischen)]) == 0

    xml2 = tmp_path / "masc2.xml"
    assert eam_ai.main(["archimate", "--ir", str(zwischen), "--out", str(xml2)]) == 0
    assert xml1.read_bytes() == xml2.read_bytes()
