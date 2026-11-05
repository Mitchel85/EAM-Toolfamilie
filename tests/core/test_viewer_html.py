"""Tests fuer viewer_html.py -- grafische Pruefung einer .qea als HTML.

Geprueft wird, was die Abgabe verspricht und was still kaputtgehen kann:

* die Seite ist selbsttragend (kein http(s), kein ``<script src>``, kein CDN),
* die Graph-Daten stehen als gueltiges JSON in der Datei und enthalten die
  Elementnamen,
* zwei Laeufe sind byte-identisch (Determinismus),
* Namen mit HTML/Script werden nicht zu Markup (XSS),
* Spiegel-Pakete und Kanten auf Spiegel werden gezaehlt, nicht gezeichnet,
* ``--max-knoten`` kappt und meldet die Kappung,
* kaputte Eingaben enden mit klarer Meldung statt mit einer leeren Seite.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

import viewer_html
from viewer_html import ViewerError, build_html, read_model, render_html

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
SCRIPT = ROOT / "viewer_html.py"
DATA_PATTERN = re.compile(r"/\*DATA-BEGIN\*/(.*?)/\*DATA-END\*/", re.S)
XSS_NAME = "<script>alert(1)</script>"
ODD_NAME = "Ümlaut & <Sonder> \"Zeichen\" 'x'"


# --------------------------------------------------------------------------
# Synthetisches Modell
# --------------------------------------------------------------------------


def make_qea(path: Path) -> Path:
    """Mini-.qea mit drei Unterpaketen, sieben Elementen und acht Kanten.

    Enthalten sind die Faelle, die den Viewer kippen: ein Paketspiegel als
    Elementzeile, eine Kante auf genau diesen Spiegel, ein Element ohne Namen
    und Namen mit HTML bzw. Umlauten.
    """
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE t_package (
                Package_ID INTEGER PRIMARY KEY, Name TEXT, Parent_ID INTEGER, TPos INTEGER
            );
            CREATE TABLE t_object (
                Object_ID INTEGER PRIMARY KEY, Object_Type TEXT, Name TEXT,
                Note TEXT, Package_ID INTEGER, Stereotype TEXT
            );
            CREATE TABLE t_connector (
                Connector_ID INTEGER PRIMARY KEY, Start_Object_ID INTEGER,
                End_Object_ID INTEGER, Connector_Type TEXT, Stereotype TEXT,
                Name TEXT, Notes TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO t_package VALUES (?, ?, ?, ?)",
            [
                (1, "Wurzel", 0, 0),
                (2, "Teil A", 1, 1),
                (3, "Teil B", 1, 2),
                (4, "Teil C", 1, 3),
            ],
        )
        connection.executemany(
            "INSERT INTO t_object VALUES (?, ?, ?, ?, ?, ?)",
            [
                (10, "Class", "Alpha", "Erstes Element.", 2, "Standard"),
                (11, "Class", "Beta", "", 2, ""),
                (12, "Component", "Gamma", "Drittes Element.", 3, "Service"),
                (13, "Class", "Delta", "Viertes Element.", 3, ""),
                (14, "Class", XSS_NAME, "Boeser Name.", 3, ""),
                (15, "Class", ODD_NAME, "Sonderzeichen.", 4, ""),
                (17, "Note", "", "Notiz ohne Namen.", 4, ""),
                # Paketspiegel: steht als Elementzeile in t_object, ist aber
                # kein Element und darf nicht als Knoten erscheinen.
                (16, "Package", "Teil A", "", 2, ""),
            ],
        )
        connection.executemany(
            "INSERT INTO t_connector VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (100, 10, 11, "Dependency", "", "nutzt", ""),
                (101, 11, 12, "Realisation", "", "", ""),
                (102, 12, 13, "Aggregation", "", "", ""),
                (103, 13, 10, "Dependency", "", "", ""),
                (104, 14, 10, "Dependency", "boese", "", ""),
                (105, 15, 13, "InformationFlow", "", "", ""),
                (106, 13, 17, "NoteLink", "", "", ""),
                # Kante auf den Paketspiegel: wird gezaehlt, nicht gezeichnet.
                (107, 16, 11, "Dependency", "", "", ""),
            ],
        )
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture()
def qea(tmp_path: Path) -> Path:
    return make_qea(tmp_path / "mini.qea")


def payload_of(page: str) -> dict:
    match = DATA_PATTERN.search(page)
    assert match, "DATA-Block fehlt in der Seite"
    return json.loads(match.group(1))


class _TagCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tags.append(tag)


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------


def test_graph_zaehlt_elemente_und_kanten(qea: Path) -> None:
    model = read_model(qea)
    assert model.counts["nodes"] == 7  # 8 Objekte minus Paketspiegel
    assert model.counts["edges"] == 7
    assert model.counts["edges_total"] == 8  # inklusive Kante auf den Spiegel
    assert model.counts["skipped_edges"] == 1
    assert model.counts["omitted_edges"] == 0
    assert model.counts["skipped_package_mirrors"] == 1
    assert model.counts["packages"] == 4
    assert {node["name"] for node in model.nodes} >= {"Alpha", "Beta", "Gamma", "Delta"}
    assert "Teil A" not in {
        node["name"] for node in model.nodes if node["type"] == "Package"
    }


def test_paketpfade_und_farbgruppen(qea: Path) -> None:
    model = read_model(qea)
    paths = {node["pkg"] for node in model.nodes}
    assert paths == {"Wurzel/Teil A", "Wurzel/Teil B", "Wurzel/Teil C"}
    # Ein Wurzelpaket -> Farben auf Ebene 2, sonst waere alles einfarbig.
    assert model.counts["color_depth"] == 2
    assert len(model.groups) == 3
    colors = {group["name"]: group["color"] for group in model.groups}
    assert len(set(colors.values())) == 3
    assert all(node["color"] == colors[node["group"]] for node in model.nodes)


def test_paketfilter_kennt_elternpakete(qea: Path) -> None:
    model = read_model(qea)
    paths = {entry["path"]: entry["count"] for entry in model.packages}
    assert paths["Wurzel"] == 7  # Teilbaum: alle Elemente
    assert paths["Wurzel/Teil A"] == 2
    assert paths["Wurzel/Teil B"] == 3
    assert paths["Wurzel/Teil C"] == 2


def test_knoten_haben_endliche_startpositionen(qea: Path) -> None:
    model = read_model(qea)
    for node in model.nodes:
        assert isinstance(node["x"], float) and isinstance(node["y"], float)
        assert abs(node["x"]) < 10000 and abs(node["y"]) < 10000
        assert node["degree"] >= 0


def test_max_knoten_kappt_und_meldet(qea: Path) -> None:
    model = read_model(qea, max_nodes=3)
    assert len(model.nodes) == 3
    assert model.counts["nodes_total"] == 7
    assert model.counts["omitted_nodes"] == 4
    # Nur Kanten zwischen den verbliebenen Knoten.
    index = {node["index"] for node in model.nodes}
    assert all(edge["s"] in index and edge["t"] in index for edge in model.edges)


# --------------------------------------------------------------------------
# Selbsttragend, JSON, Determinismus
# --------------------------------------------------------------------------


def test_seite_ist_selbsttragend(qea: Path) -> None:
    page = build_html(qea)
    lowered = page.lower()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "<script src" not in lowered
    assert "<link" not in lowered
    assert "<img" not in lowered
    assert "cdn" not in lowered
    assert "@import" not in lowered
    # Genau der eine eigene Script-Block, kein zweiter.
    parser = _TagCounter()
    parser.feed(page)
    assert parser.tags.count("script") == 1
    assert page.startswith("<!doctype html>")


def test_json_ist_valide_und_enthaelt_die_namen(qea: Path) -> None:
    page = build_html(qea)
    data = payload_of(page)
    names = {node["name"] for node in data["nodes"]}
    assert {"Alpha", "Beta", "Gamma", "Delta"} <= names
    assert data["counts"]["nodes"] == 7
    assert len(data["edges"]) == 7
    for key in ("nodes", "edges", "packages", "groups", "counts"):
        assert key in data


def test_zwei_laeufe_sind_byte_identisch(qea: Path, tmp_path: Path) -> None:
    first = tmp_path / "a.html"
    second = tmp_path / "b.html"
    for target in (first, second):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(qea), "--out", str(target)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
    assert first.read_bytes() == second.read_bytes()
    assert b"1430" not in first.read_bytes()


def test_umlaute_bleiben_lesbar(qea: Path) -> None:
    page = build_html(qea)
    model = read_model(qea)
    names = [node["name"] for node in model.nodes]
    assert ODD_NAME in names
    assert "Ümlaut" in page  # UTF-8, nicht als Entity zerlegt


def test_script_name_wird_nicht_zum_tag(qea: Path) -> None:
    page = build_html(qea)
    # Der Name steht als JSON-String in der Seite, aber nie als Markup.
    assert "<script>alert(1)</script>" not in page
    assert "<script>alert(1)" not in page
    assert "\\u003cscript\\u003ealert(1)\\u003c/script\\u003e" in page
    parser = _TagCounter()
    parser.feed(page)
    assert parser.tags.count("script") == 1
    # Und nach dem Parsen des JSON ist der Name unveraendert.
    names = [node["name"] for node in payload_of(page)["nodes"]]
    assert XSS_NAME in names


def test_notizen_werden_gekuerzt(qea: Path, tmp_path: Path) -> None:
    long_note = "A" * (viewer_html.NOTE_CHARS + 50)
    target = tmp_path / "lang.qea"
    make_qea(target)
    connection = sqlite3.connect(target)
    try:
        connection.execute("UPDATE t_object SET Note = ? WHERE Object_ID = 10", (long_note,))
        connection.commit()
    finally:
        connection.close()
    model = read_model(target)
    note = next(node["note"] for node in model.nodes if node["name"] == "Alpha")
    assert note.endswith("[...]")
    assert len(note) <= viewer_html.NOTE_CHARS + 8


# --------------------------------------------------------------------------
# Kommandozeile und Fehler
# --------------------------------------------------------------------------


def test_cli_erzeugt_datei_und_meldet_zahlen(qea: Path, tmp_path: Path) -> None:
    target = tmp_path / "viewer.html"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(qea), "--out", str(target)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert target.is_file()
    assert "7 Knoten" in result.stdout
    assert "7 Kanten" in result.stdout


def test_cli_ohne_out_legt_datei_neben_das_modell(qea: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(qea)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert (qea.parent / "mini_viewer.html").is_file()


def test_cli_max_knoten(qea: Path, tmp_path: Path) -> None:
    target = tmp_path / "klein.html"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(qea), "--out", str(target), "--max-knoten", "2"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    data = payload_of(target.read_text(encoding="utf-8"))
    assert data["counts"]["nodes"] == 2
    assert data["counts"]["omitted_nodes"] == 5
    assert data["counts"]["omitted_edges"] >= 1
    assert "nicht gezeichnet" in result.stderr
    assert "nicht geladenen Knoten" in result.stderr


def test_cli_meldet_fehlende_datei(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "gibtsnicht.qea"), "--out", str(tmp_path / "x.html")],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )
    assert result.returncode == 1
    assert "FEHLER" in result.stderr
    assert not (tmp_path / "x.html").exists()


def test_keine_qea_wirft_lauten_fehler(tmp_path: Path) -> None:
    broken = tmp_path / "kaputt.qea"
    broken.write_text("das ist keine datenbank", encoding="utf-8")
    with pytest.raises(ViewerError):
        read_model(broken)


def test_fehlende_tabellen_klare_meldung(tmp_path: Path) -> None:
    empty = tmp_path / "leer.qea"
    connection = sqlite3.connect(empty)
    connection.execute("CREATE TABLE irgendwas (x INTEGER)")
    connection.commit()
    connection.close()
    with pytest.raises(ViewerError) as excinfo:
        read_model(empty)
    assert "t_object" in str(excinfo.value)


def test_render_ist_reine_funktion(qea: Path) -> None:
    model = read_model(qea)
    assert render_html(model) == render_html(model)
    assert render_html(model, title="Anderer Titel") != render_html(model)


def test_html_enthaelt_alle_bedienelemente(qea: Path) -> None:
    page = build_html(qea)
    for element_id in (
        'id="q"', 'id="pkg"', 'id="stereo"', 'id="type"', 'id="legend"',
        'id="detail"', 'id="c"', 'id="all-edges"', 'id="hide-isolated"',
    ):
        assert element_id in page
    assert "Force" in page or "simulate" in page
