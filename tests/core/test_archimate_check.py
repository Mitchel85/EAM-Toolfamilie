"""Tests fuer ``archimate_check`` -- Modell lesen, zusammenfassen, pruefen.

Der Vertrag: Die Pruefung urteilt nur ueber das, was im Modell steht, und
benutzt fuer die Zuordnung dieselbe Kette wie der Writer. Diese Tests belegen:

1. **Lesen** -- XML, IR-JSON und ``.qea`` ergeben denselben Befund; offene
   Verweise werden gelesen (und gemeldet), nicht verschluckt.
2. **Pruefen** -- offene Referenzen, Matrixverstoesse und verwaiste Elemente
   werden erkannt; Darstellungselemente erzeugen kein Rauschen.
3. **Zaehlen** -- die Zusammenfassung stimmt mit dem Modell ueberein.
4. **Ausgeben** -- Text, Markdown, JSON und Prompt sind vollstaendig und
   deterministisch; der Beispielbericht ist der echte Bericht.
5. **Zusammenpassen** -- Pruefer und Writer urteilen gleich: was der Writer
   schreibt, ist matrix-konform.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import archimate_check as ac
import archimate_reader as ar
import archimate_writer as aw
import qea_chat
import qea_reader

CORE = Path(__file__).resolve().parents[2] / "packages" / "core"
FIXTURES = CORE / "fixtures"
BEISPIEL = CORE / "examples" / "archimate" / "beispiel_fehlermodell.xml"
BEISPIELBERICHT = CORE / "examples" / "archimate" / "BEISPIELBERICHT.md"
MASC = FIXTURES / "Musterarchitektur_MASC.qea"
MASCBERICHT = CORE / "examples" / "archimate" / "BEISPIELBERICHT-MASC.md"

NS = "http://www.opengroup.org/xsd/archimate/3.0/"


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------
def _ir(elemente, kanten=(), pakete=(), name="Testmodell", kennung="id-test") -> dict:
    """Kleines IR im Vertrag der Reader."""
    return {
        "ir_version": 1,
        "packages": [{"path": pfad} for pfad in pakete],
        "elements": list(elemente),
        "connectors": list(kanten),
        "diagrams": [],
        "meta": {"archimate": {"name": name, "identifier": kennung, "namespace": NS}},
    }


def _element(paket: str, name: str, ea_type: str, stereotype: str = "") -> dict:
    eintrag = {"package": paket, "name": name, "ea_type": ea_type}
    if stereotype:
        eintrag["stereotype"] = stereotype
    return eintrag


def _kante(quelle: str, ziel: str, ea_type: str, name: str = "") -> dict:
    eintrag = {"source": quelle, "target": ziel, "ea_type": ea_type}
    if name:
        eintrag["name"] = name
    return eintrag


def _checks(befund: ac.Befund) -> list[str]:
    return [finding.check for finding in befund.findings]


def _xml(tmp_path: Path, rumpf: str, name: str = "modell.xml") -> Path:
    ziel = tmp_path / name
    ziel.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<model xmlns="{NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'identifier="id-m" version="3.2"><name xml:lang="de">M</name>'
        f"{rumpf}</model>",
        encoding="utf-8",
    )
    return ziel


# --------------------------------------------------------------------------
# 1. Zuordnung: eine Kette fuer Writer und Pruefer
# --------------------------------------------------------------------------
def test_schichttabelle_ist_vollstaendig():
    """Jedes ArchiMate-Konzept hat eine Schicht -- sonst faellt es hier auf."""
    fehlend = set(aw.ARCHIMATE_ELEMENT_TYPES) - set(ac.SCHICHT_VON)
    assert not fehlend, f"Konzepte ohne Schicht: {sorted(fehlend)}"
    # "Junction" ist ein Matrixbegriff, kein Austauschformat-Typ.
    ueberzaehlig = set(ac.SCHICHT_VON) - set(aw.ARCHIMATE_ELEMENT_TYPES) - {"Junction"}
    assert not ueberzaehlig, f"Schichttabelle kennt unbekannte Konzepte: {sorted(ueberzaehlig)}"


def test_konzept_stereotype_vor_metaklasse():
    """Der Guide-Stereotyp gewinnt gegen die UML-Metaklasse."""
    konzept = aw.archimate_konzept("System", "Class")
    assert (konzept.typ, konzept.herkunft) == ("ApplicationComponent", "stereotype")


def test_konzept_metaklasse_und_rueckfall_und_import():
    assert aw.archimate_konzept("", "State").herkunft == "metaklasse"
    assert aw.archimate_konzept("", "Class") == aw.Konzept("Grouping", "rueckfall")
    assert aw.archimate_konzept("", "BusinessActor") == aw.Konzept("BusinessActor", "import")
    assert aw.archimate_konzept("", "Text") == aw.Konzept(None, "keine")


def test_beziehung_aus_stereotyp_und_metaklasse():
    assert aw.archimate_beziehung("Satisfy", "Dependency") == "Realization"
    assert aw.archimate_beziehung("", "Aggregation") == "Aggregation"
    assert aw.archimate_beziehung("", "NoteLink") is None


def test_matrix_association_ist_immer_erlaubt():
    matrix = aw.load_matrix()
    assert aw.matrix_erlaubt(matrix, "BusinessActor", "Association", "Artifact")
    assert not aw.matrix_erlaubt(matrix, "BusinessActor", "Composition", "BusinessService")


# --------------------------------------------------------------------------
# 2. Pruefen: die drei geforderten Faelle
# --------------------------------------------------------------------------
def test_sauberes_modell_hat_keine_meldungen():
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Antrag bearbeiten", "BusinessService"),
        ],
        [_kante("A::Sachbearbeiter", "A::Antrag bearbeiten", "Serving")],
        pakete=["A"],
    )
    befund = ac.pruefe(ir)
    assert befund.findings == ()
    assert befund.summary() == {"total": 0, "error": 0, "warning": 0, "info": 0}
    assert befund.zusammenfassung.elemente == 2
    assert befund.zusammenfassung.beziehungen == 1


def test_offene_referenz_wird_gemeldet():
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Dienst", "BusinessService"),
        ],
        [_kante("A::Sachbearbeiter", "A::gibt es nicht", "Serving")],
        pakete=["A"],
    )
    befund = ac.pruefe(ir)
    (finding,) = [f for f in befund.findings if f.check == "unresolvedReference"]
    assert finding.severity == ac.ERROR
    assert "Ziel 'A::gibt es nicht'" in finding.message
    assert "kein Element" in finding.message


def test_leerer_endpunkt_ist_offene_referenz():
    ir = _ir(
        [_element("A", "Sachbearbeiter", "BusinessActor")],
        [_kante("A::Sachbearbeiter", "", "Serving")],
        pakete=["A"],
    )
    (finding,) = ac.pruefe(ir).findings
    assert finding.check == "unresolvedReference"
    assert "'(leer)'" in finding.message


def test_matrixverstoss_wird_gemeldet():
    """Ein Akteur besteht nicht aus einem Dienst -- Composition ist unzulaessig."""
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Antrag bearbeiten", "BusinessService"),
        ],
        [_kante("A::Sachbearbeiter", "A::Antrag bearbeiten", "Composition", name="besteht aus")],
        pakete=["A"],
    )
    (finding,) = ac.pruefe(ir).findings
    assert finding.check == "matrixViolation"
    assert finding.severity == ac.ERROR
    assert finding.rule == "ArchiMate 3.2 Beziehungsmatrix"
    assert "Composition von BusinessActor nach BusinessService" in finding.message
    assert finding.object == "besteht aus"


def test_matrix_prueft_auch_die_richtung():
    """Serving ist Business->Anwendung erlaubt -- umgekehrt nicht in jedem Fall."""
    matrix = aw.load_matrix()
    erlaubt = aw.matrix_erlaubt(matrix, "ApplicationComponent", "Serving", "BusinessService")
    verboten = aw.matrix_erlaubt(matrix, "BusinessService", "Assignment", "ApplicationComponent")
    assert erlaubt
    assert not verboten


def test_verwaistes_element_wird_gemeldet():
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Dienst", "BusinessService"),
            _element("A", "Altsystem", "ApplicationComponent"),
        ],
        [_kante("A::Sachbearbeiter", "A::Dienst", "Serving")],
        pakete=["A"],
    )
    (finding,) = ac.pruefe(ir).findings
    assert finding.check == "orphanElement"
    assert finding.severity == ac.WARNING
    assert finding.object == "A::Altsystem"
    assert "ApplicationComponent" in finding.message


def test_darstellungselemente_erzeugen_kein_rauschen():
    """Ein Beschriftungstext ohne Beziehung ist kein Qualitaetsmangel."""
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Dienst", "BusinessService"),
            _element("A", "", "Text"),
            _element("A", "", "Note"),
        ],
        [_kante("A::Sachbearbeiter", "A::Dienst", "Serving")],
        pakete=["A"],
    )
    befund = ac.pruefe(ir)
    assert befund.findings == ()
    assert befund.zusammenfassung.ohne_konzept == 2
    assert befund.zusammenfassung.ohne_konzept_grund == {"Darstellung": 2}
    assert befund.zusammenfassung.fachlich == 2


def test_selbstbezug_und_unbenanntes_element():
    ir = _ir(
        [
            _element("A", "Dienst", "BusinessService"),
            _element("A", "", "BusinessObject"),
        ],
        [_kante("A::Dienst", "A::Dienst", "Serving")],
        pakete=["A"],
    )
    befund = ac.pruefe(ir)
    assert sorted(_checks(befund)) == ["orphanElement", "selfReference", "unnamedElement"]


def test_doppelte_kennung_wird_gemeldet():
    ir = _ir(
        [
            _element("A", "Dienst", "BusinessService"),
            _element("A", "Dienst", "BusinessService"),
        ],
        [],
        pakete=["A"],
    )
    # Ohne ausdrueckliche Referenz vergibt der Pruefer #1/#2 -- erst eine
    # doppelt gelieferte Kennung macht Verweise mehrdeutig.
    for element in ir["elements"]:
        element["ref"] = "A::Dienst"
    befund = ac.pruefe(ir)
    (finding,) = [f for f in befund.findings if f.check == "duplicateIdentifier"]
    assert finding.severity == ac.ERROR
    assert "2x vergeben" in finding.message


def test_kante_ohne_art_zaehlt_als_nicht_pruefbar():
    """NoteLink ist Darstellung und keine Beziehung -- zaehlen, nicht urteilen."""
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Notiz", "Note"),
        ],
        [_kante("A::Sachbearbeiter", "A::Notiz", "NoteLink")],
        pakete=["A"],
    )
    befund = ac.pruefe(ir)
    assert befund.findings == ()
    assert befund.zusammenfassung.kanten_ohne_art == 1
    assert befund.zusammenfassung.kanten_ohne_art_typen == {"NoteLink": 1}


def test_paket_als_endpunkt_ist_keine_offene_referenz():
    ir = _ir(
        [_element("A/B", "Dienst", "BusinessService")],
        [_kante("A/B", "A/B::Dienst", "Aggregation")],
        pakete=["A", "A/B"],
    )
    befund = ac.pruefe(ir)
    assert "unresolvedReference" not in _checks(befund)
    assert befund.zusammenfassung.paket_endpunkte == 1


def test_mehrere_meldungen_werden_sortiert_und_entdoppelt():
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Altsystem", "ApplicationComponent"),
        ],
        [],
        pakete=["A"],
    )
    befund = ac.pruefe(ir)
    assert [f.object for f in befund.findings] == ["A::Altsystem", "A::Sachbearbeiter"]
    assert len({(f.check, f.object, f.message) for f in befund.findings}) == len(befund.findings)


# --------------------------------------------------------------------------
# 3. Zusammenfassung
# --------------------------------------------------------------------------
def test_zusammenfassung_zaehlt_schichten_konzepte_und_arten():
    ir = _ir(
        [
            _element("A", "Akteur", "BusinessActor"),
            _element("A", "Dienst", "BusinessService"),
            _element("A", "Anwendung", "ApplicationComponent"),
        ],
        [
            _kante("A::Akteur", "A::Dienst", "Serving"),
            _kante("A::Anwendung", "A::Dienst", "Serving"),
        ],
        pakete=["A"],
    )
    z = ac.zusammenfassen(ir)
    assert z.pakete == 1
    assert z.elemente == 3
    assert z.beziehungen == 2
    assert z.schichten == {"Geschaeft": 2, "Anwendung": 1}
    assert z.konzepte == {"BusinessActor": 1, "BusinessService": 1, "ApplicationComponent": 1}
    assert z.beziehungsarten == {"Serving": 2}
    assert z.herkunft["import"] == 3
    assert z.ohne_beziehung == 0


def test_zusammenfassung_nimmt_kopf_aus_dem_modell():
    z = ac.zusammenfassen(_ir([], name="Mein Modell", kennung="id-42"))
    assert (z.modell, z.kennung) == ("Mein Modell", "id-42")
    assert z.elemente == 0


def test_refs_werden_wie_bei_den_readern_gebildet(tmp_path: Path):
    """IR ohne ``ref``: dieselbe Regel wie ``archimate_reader`` -- inklusive ``#N``."""
    quelle = _xml(
        tmp_path,
        "<elements>"
        '<element identifier="id-1" xsi:type="BusinessActor"><name xml:lang="de">Rolle</name>'
        '<documentation xml:lang="de">zweite</documentation></element>'
        '<element identifier="id-2" xsi:type="BusinessActor"><name xml:lang="de">Rolle</name>'
        '<documentation xml:lang="de">erste</documentation></element>'
        '<element identifier="id-3" xsi:type="BusinessService"><name xml:lang="de">Dienst</name></element>'
        '<element identifier="id-4" xsi:type="BusinessObject"/>'
        "</elements>",
    )
    ir, _report = ar.read_archimate_ex(quelle)
    refs_reader = [element["ref"] for element in ir["elements"]]
    assert refs_reader == ["::Rolle#2", "::Rolle#1", "::Dienst", "::#1"]

    ohne_refs = [
        {schluessel: wert for schluessel, wert in element.items() if schluessel != "ref"}
        for element in ir["elements"]
    ]
    assert ac._refs_ergaenzen(ohne_refs) == refs_reader


# --------------------------------------------------------------------------
# 4. Lesen
# --------------------------------------------------------------------------
def test_liest_xml_und_meldet_offene_referenz(tmp_path: Path):
    quelle = _xml(
        tmp_path,
        "<elements>"
        '<element identifier="id-el-1" xsi:type="BusinessActor"><name xml:lang="de">A</name></element>'
        "</elements><relationships>"
        '<relationship identifier="id-r1" xsi:type="Serving" source="id-el-1" target="id-gibt-es-nicht"/>'
        "</relationships>",
    )
    # Der Export-Pfad bleibt streng: kaputter Verweis ist dort ein Abbruch.
    with pytest.raises(ar.ArchimateReaderError, match="Ziel"):
        ar.read_archimate_ex(quelle)

    ir, format_label = ac.lade_modell(quelle)
    assert "ArchiMate Model Exchange" in format_label
    befund = ac.pruefe(ir)
    (finding,) = befund.findings
    assert finding.check == "unresolvedReference"
    assert "id-gibt-es-nicht" in finding.message


def test_unresolved_keep_haelt_die_kante_im_ir(tmp_path: Path):
    quelle = _xml(
        tmp_path,
        "<elements>"
        '<element identifier="id-el-1" xsi:type="BusinessActor"><name xml:lang="de">A</name></element>'
        "</elements><relationships>"
        '<relationship identifier="id-r1" xsi:type="Serving" source="id-el-1" target="id-weg"/>'
        "</relationships>",
    )
    ir, report = ar.read_archimate_ex(quelle, unresolved="keep")
    (kante,) = ir["connectors"]
    assert kante["target"] == "id-weg"
    assert any("id-weg" in warnung for warnung in report.warnings)

    with pytest.raises(ar.ArchimateReaderError):
        ar.read_archimate_ex(quelle, unresolved="vielleicht")


def test_liest_ir_json_und_qea(tmp_path: Path):
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor", "OperationalPerformer"),
            _element("A", "Dienst", "BusinessService", "ServiceSpecification"),
        ],
        [_kante("A::Sachbearbeiter", "A::Dienst", "Serving")],
        pakete=["A"],
    )
    for element in ir["elements"]:
        element["ref"] = f"{element['package']}::{element['name']}"

    json_pfad = tmp_path / "modell.json"
    json_pfad.write_text(json.dumps(ir), encoding="utf-8")
    gelesen, format_label = ac.lade_modell(json_pfad)
    assert format_label == "IR-JSON"
    assert ac.pruefe(gelesen).summary()["error"] == 0

    qea_pfad = tmp_path / "modell.qea"
    import qea_writer

    qea_writer.write_qea(gelesen, qea_pfad)
    gelesen, format_label = ac.lade_modell(qea_pfad)
    assert format_label == "EA-Repository (.qea)"
    assert ac.pruefe(gelesen).zusammenfassung.elemente == 2


def test_unbekannte_endung_und_kaputtes_ir_brechen_ab(tmp_path: Path):
    text = tmp_path / "modell.txt"
    text.write_text("kein Modell", encoding="utf-8")
    with pytest.raises(ac.ArchimateCheckError, match="Endung"):
        ac.lade_modell(text)

    with pytest.raises(ac.ArchimateCheckError, match="nicht gefunden"):
        ac.lade_modell(tmp_path / "fehlt.xml")

    falsch = tmp_path / "falsch.json"
    falsch.write_text('{"ir_version": 99}', encoding="utf-8")
    with pytest.raises(ac.ArchimateCheckError, match="ir_version"):
        ac.lade_modell(falsch)


# --------------------------------------------------------------------------
# 5. Ausgabe
# --------------------------------------------------------------------------
def test_text_markdown_json_und_prompt_enthalten_denselben_befund():
    ir = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Altsystem", "ApplicationComponent"),
        ],
        [],
        pakete=["A"],
    )
    befund = ac.pruefe(ir, datei="modell.json")

    text = ac.render_text(befund)
    assert "MODELL" in text and "BEFUND" in text
    assert "modell.json" in text
    assert "orphanElement" in text

    markdown = ac.render_markdown(befund)
    assert markdown.startswith("# ArchiMate-Modellbefund")
    assert "| Fehler |" not in markdown  # nur Warnungen in diesem Modell
    assert "`orphanElement`" in markdown

    daten = json.loads(ac.render_json(befund))
    assert daten["summary"] == {"total": 2, "error": 0, "warning": 2, "info": 0}
    assert daten["zusammenfassung"]["datei"] == "modell.json"
    assert daten["nach_pruefung"] == {"orphanElement": 2}
    assert len(daten["findings"]) == 2

    prompt = ac.render_prompt(befund, "Welche Elemente stehen allein?")
    assert ac.PROMPT_KOPF in prompt
    assert "Welche Elemente stehen allein?" in prompt
    assert "Altsystem" in prompt


def test_prompt_regeln_stimmen_mit_dem_frageweg_ueberein():
    """Ein Modell, eine Sprache: der Pruefer darf nicht anders klingen als qea_chat."""
    for regel in (
        "Erfinde keine Elemente, Beziehungen, Zahlen oder Quellen.",
        "Antworte auf Deutsch",
    ):
        assert regel in ac.PROMPT_KOPF
        assert regel in qea_chat.PROMPT_KOPF


def test_bericht_ist_deterministisch():
    ir, _ = ac.lade_modell(BEISPIEL)
    erst = ac.render_json(ac.pruefe(ir))
    zweit = ac.render_json(ac.pruefe(ir))
    assert erst == zweit


def test_limit_kuerzt_und_nennt_den_rest():
    ir = _ir(
        [_element("A", f"Element {nummer}", "BusinessService") for nummer in range(5)],
        [],
        pakete=["A"],
    )
    befund = ac.pruefe(ir)
    text = ac.render_text(befund, limit=2)
    assert "3 weitere Meldungen" in text
    assert "5 Meldungen" in text
    assert len([z for z in ac.render_text(befund, limit=0).splitlines() if "orphanElement" in z]) == 5


def test_beispielbericht_ist_der_echte_bericht():
    """Der abgelegte Beispielbericht muss aus dem Beispielmodell entstehen."""
    ir, format_label = ac.lade_modell(BEISPIEL)
    befund = ac.pruefe(ir, format=format_label, datei=BEISPIEL.name)
    assert ac.render_markdown(befund, limit=0) == BEISPIELBERICHT.read_text(encoding="utf-8")


@pytest.mark.skipif(not MASC.is_file(), reason="Fixture Musterarchitektur fehlt")
def test_masc_beispielbericht_ist_der_echte_bericht():
    """Auch der grosse Beispielbericht bleibt an das Modell gebunden."""
    ir, format_label = ac.lade_modell(MASC)
    befund = ac.pruefe(ir, format=format_label, datei=MASC.name)
    assert befund.summary()["total"] == 232
    # Bytes, nicht Text: Elementnamen tragen eingebettete CRLF aus dem
    # Repository; ``read_text`` wuerde sie stillschweigend normalisieren.
    assert ac.render_markdown(befund).encode("utf-8") == MASCBERICHT.read_bytes()


# --------------------------------------------------------------------------
# 6. CLI
# --------------------------------------------------------------------------
def test_cli_exitcodes(tmp_path: Path, capsys):
    assert ac.main(["--in", str(BEISPIEL), "--format", "json", "--out", str(tmp_path / "b.json")]) == 1
    assert "Fehler" in capsys.readouterr().err

    assert ac.main(["--in", str(tmp_path / "fehlt.xml")]) == 3
    assert "FEHLER" in capsys.readouterr().err

    sauber = _ir(
        [
            _element("A", "Sachbearbeiter", "BusinessActor"),
            _element("A", "Dienst", "BusinessService"),
        ],
        [_kante("A::Sachbearbeiter", "A::Dienst", "Serving")],
        pakete=["A"],
    )
    for element in sauber["elements"]:
        element["ref"] = f"{element['package']}::{element['name']}"
    pfad = tmp_path / "sauber.json"
    pfad.write_text(json.dumps(sauber), encoding="utf-8")
    assert ac.main(["--in", str(pfad)]) == 0
    assert "Keine Meldungen" in capsys.readouterr().out


def test_cli_strict_zaehlt_warnungen_als_fehler(tmp_path: Path, capsys):
    warnend = _ir(
        [_element("A", "Altsystem", "ApplicationComponent")],
        [],
        pakete=["A"],
    )
    for element in warnend["elements"]:
        element["ref"] = f"{element['package']}::{element['name']}"
    pfad = tmp_path / "warnend.json"
    pfad.write_text(json.dumps(warnend), encoding="utf-8")

    assert ac.main(["--in", str(pfad)]) == 0
    capsys.readouterr()
    assert ac.main(["--in", str(pfad), "--strict"]) == 1


def test_cli_schreibt_bericht_und_prompt(tmp_path: Path, capsys):
    ziel = tmp_path / "bericht.md"
    assert ac.main(["--in", str(BEISPIEL), "--format", "md", "--out", str(ziel)]) == 1
    assert ziel.read_text(encoding="utf-8").startswith("# ArchiMate-Modellbefund")
    assert "3 Fehler" in capsys.readouterr().err

    prompt = tmp_path / "prompt.txt"
    assert ac.main(
        ["--in", str(BEISPIEL), "--format", "prompt", "--frage", "Was ist offen?", "--out", str(prompt)]
    ) == 1
    assert "Was ist offen?" in prompt.read_text(encoding="utf-8")


def test_eam_ai_verteilt_den_unterbefehl(tmp_path: Path, capsys):
    """``eam-ai archimate-check`` ist verdrahtet (Parser und Funktion)."""
    import eam_ai

    args = eam_ai.build_parser().parse_args(
        ["archimate-check", "--in", str(BEISPIEL), "--format", "json"]
    )
    assert args.func is eam_ai.cmd_archimate_check
    assert args.limit == 40

    ziel = tmp_path / "befund.json"
    assert eam_ai.main(["archimate-check", "--in", str(BEISPIEL), "--format", "json", "--out", str(ziel)]) == 1
    daten = json.loads(ziel.read_text(encoding="utf-8"))
    assert daten["summary"]["error"] == 3
    capsys.readouterr()


# --------------------------------------------------------------------------
# 7. Zusammenspiel mit dem Writer (Musterarchitektur, falls vorhanden)
# --------------------------------------------------------------------------
@pytest.mark.skipif(not MASC.is_file(), reason="Fixture Musterarchitektur fehlt")
def test_was_der_writer_schreibt_ist_matrix_konform(tmp_path: Path):
    """Der Writer baut unzulaessige Kanten um -- das Ergebnis ist sauber."""
    ir, _report = qea_reader.read_qea_ex(MASC, with_refs=True)

    quelle = ac.pruefe(ir, format="EA-Repository (.qea)")
    # Die .qea enthaelt Kanten, die die Matrix nicht erlaubt (z.B. Abstraction
    # zwischen zwei BusinessProcesses). Der Export repariert sie -- wenn hier
    # nichts mehr gefunden wird, prueft der Pruefer nicht mehr.
    assert quelle.summary()["error"] > 0

    ziel = tmp_path / "masc.xml"
    report = aw.write_archimate(ir, ziel, modellname="MASC")
    exportiert, format_label = ac.lade_modell(ziel)
    befund = ac.pruefe(exportiert, format=format_label)
    assert befund.summary()["error"] == 0
    # Derselbe Bestand: was der Writer geschrieben hat, sieht der Pruefer.
    assert befund.zusammenfassung.elemente == report.elements
    assert befund.zusammenfassung.beziehungen == report.relationships
