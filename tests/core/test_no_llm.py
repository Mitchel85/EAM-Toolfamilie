"""Abnahmetests: Betrieb ohne KI -- reiner Regelpfad (kein LLM noetig).

DoD (Karte t_554f9c27):
  * kompletter Lauf mit ``--no-llm`` (Import -> Pruefung -> Export),
  * Netzwerk dabei gesperrt (monkeypatch),
  * keine KI-Abhaengigkeit im Import-Graph, ``extract`` nur bei Bedarf.

Ausschliesslich synthetische Daten (keine echten Modelle, keine Personendaten).
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

ROOT = Path(__file__).resolve().parents[2] / 'packages' / 'core'  # Monorepo: Bezugswurzel umgesetzt (Pfade beim Monorepo-Umzug gesetzt)
RULES_DIR = Path(__file__).resolve().parents[2] / "packages" / "rules"  # einziger MDG-Leser
if str(ROOT) not in sys.path:  # pragma: no cover - Import-Komfort
    sys.path.insert(0, str(ROOT))

import eam_suite  # noqa: E402
import table_import  # noqa: E402
from qea_reader import read_qea, render_json, semantic_equal  # noqa: E402
from qea_writer import QeaWriterError, write_qea  # noqa: E402
from table_import import TableImportError  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures"  # Monorepo
CSV_MIXED = FIXTURES / "no_llm_modell.csv"
CSV_PACKAGES = FIXTURES / "no_llm_pakete.csv"
CSV_ELEMENTS = FIXTURES / "no_llm_elemente.csv"
CSV_CONNECTORS = FIXTURES / "no_llm_kanten.csv"
RULES = FIXTURES / "rules_validator.json"
REQUIREMENTS = FIXTURES / "requirements_validator.json"

# Module, die im reinen Regelpfad nicht vorkommen duerfen. urllib.parse ist
# erlaubt (pathlib nutzt es zum Parsen von Pfaden, kein Netz).
FORBIDDEN_ROOTS = {
    "socket",
    "ssl",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "websocket",
    "websockets",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "openai",
    "anthropic",
    "mistralai",
    "cohere",
    "litellm",
    "transformers",
    "torch",
    "llama_cpp",
    "sentence_transformers",
    "extract",
}
FORBIDDEN_PREFIXES = (
    "urllib.request",
    "urllib.error",
    "google.generativeai",
    "google.cloud.aiplatform",
    "google.oauth2",
)


def _forbidden(module: str) -> bool:
    if module.split(".", 1)[0] in FORBIDDEN_ROOTS:
        return True
    return any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)


def _python(code: str, *, extra_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Der Kern liegt in packages/core, der einzige MDG-Leser in packages/rules.
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(RULES_DIR)])
    if extra_path is not None:
        env["PYTHONPATH"] = str(extra_path) + os.pathsep + env["PYTHONPATH"]
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Jeder Netzaufruf wird zum Testfehler -- auch ohne Suite-Guard."""

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Netzwerkzugriff im Regelpfad")

    import socket

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


# --------------------------------------------------------------------------
# XLSX-Fixture (stdlib, damit kein binaeres Fixture gepflegt werden muss)
# --------------------------------------------------------------------------


def _column(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(ord("A") + rest) + name
    return name


def _sheet_xml(rows: list[list[str]]) -> str:
    body = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column, value in enumerate(row):
            ref = f"{_column(column)}{row_number}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        body.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(body) + "</sheetData></worksheet>"
    )


def write_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    """Schreibt eine minimale .xlsx mit Inline-Strings (nur was der Leser braucht)."""
    names = list(sheets)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, name in enumerate(names, start=1)
        )
        + "</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(names) + 1)
        )
        + "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        for index, name in enumerate(names, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheets[name]))
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
    return path


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


# --------------------------------------------------------------------------
# 1. Import-Graph: kein Netz, keine KI
# --------------------------------------------------------------------------


def test_import_graph_ohne_ki_und_ohne_netz() -> None:
    """Der Kern laesst sich importieren, ohne Netz- oder KI-Module zu laden."""
    code = (
        "import json, sys\n"
        "import eam_suite, table_import, validator, qea_reader, qea_writer\n"
        "import rules_schema, mdg_parser\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    result = _python(code)
    assert result.returncode == 0, result.stderr
    modules = json.loads(result.stdout)
    forbidden = [module for module in modules if _forbidden(module)]
    assert forbidden == []
    assert "urllib.parse" in modules  # Gegenprobe: pathlib ist erlaubt
    assert "extract" not in modules


def test_kern_laedt_vorhandenes_extract_nicht(tmp_path: Path) -> None:
    """Ein vorhandenes KI-Modul wird vom Regelpfad nicht automatisch importiert."""
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "extract.py").write_text(
        "raise SystemExit('extract wurde ungefragt importiert')\n", encoding="utf-8"
    )
    code = f"""
import sys
sys.path.insert(0, {str(fake)!r})
import eam_suite
ir = eam_suite.import_sources([{str(CSV_MIXED)!r}])
result = eam_suite.run_pipeline(
    [{str(CSV_MIXED)!r}],
    rules_path={str(RULES)!r},
    target={str(tmp_path / "out.qea")!r},
)
assert result.exported
assert "extract" not in sys.modules, "Kern hat extract importiert"
print("OHNE-KI", len(ir["elements"]))
"""
    result = _python(code)
    assert result.returncode == 0, result.stderr
    assert "OHNE-KI 2" in result.stdout
    assert (tmp_path / "out.qea").exists()


def test_no_llm_blockiert_ki_import_und_netz(tmp_path: Path) -> None:
    """--no-llm sperrt den Import von extract und jeden Verbindungsaufbau."""
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "extract.py").write_text("WERT = 1\n", encoding="utf-8")
    code = f"""
import importlib, socket, sys
sys.path.insert(0, {str(fake)!r})
import eam_suite
eam_suite.install_no_llm_guard()
try:
    importlib.import_module("extract")
except eam_suite.NoLlmImportBlocked:
    print("EXTRACT-BLOCKED")
else:
    print("EXTRACT-IMPORTIERT")
try:
    socket.create_connection(("127.0.0.1", 9), timeout=0.05)
except eam_suite.NetworkBlocked:
    print("NET-BLOCKED")
else:
    print("NET-OFFEN")
"""
    result = _python(code, extra_path=fake)
    assert result.returncode == 0, result.stderr
    assert "EXTRACT-BLOCKED" in result.stdout
    assert "NET-BLOCKED" in result.stdout


# --------------------------------------------------------------------------
# 2. Kompletter Lauf mit --no-llm und gesperrtem Netz (DoD)
# --------------------------------------------------------------------------


def test_kompletter_lauf_no_llm_mit_gesperrtem_netz(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Import -> Pruefung -> Export mit --no-llm; Netz per monkeypatch zu."""
    _block_network(monkeypatch)
    qea = tmp_path / "modell.qea"
    findings = tmp_path / "findings.json"
    try:
        code = eam_suite.main(
            [
                "--no-llm",
                "-q",
                "run",
                str(CSV_MIXED),
                "--rules",
                str(RULES),
                "--requirements",
                str(REQUIREMENTS),
                "-o",
                str(qea),
                "--findings",
                str(findings),
            ]
        )
    finally:
        eam_suite.remove_no_llm_guard()

    assert code == 0
    assert qea.read_bytes().startswith(b"SQLite format 3\x00")
    assert json.loads(findings.read_text(encoding="utf-8")) == []
    ir = read_qea(qea)
    assert [element["name"] for element in ir["elements"]] == ["Port A", "System A"]
    assert ir["connectors"][0]["stereotype"] == "Provides"
    assert ir["packages"][1]["tags"] == {"Herkunft": "Handbuch"}


def test_cli_no_llm_im_subprozess_mit_netzsperre(tmp_path: Path) -> None:
    """Wie oben, aber als echter CLI-Prozess: PYTHONPATH blockt socket beim Start."""
    preload = tmp_path / "preload"
    preload.mkdir()
    (preload / "sitecustomize.py").write_text(
        "import socket\n"
        "class Blocked(RuntimeError):\n"
        "    pass\n"
        "def _deny(*args, **kwargs):\n"
        "    raise Blocked('Netz gesperrt')\n"
        "socket.socket.connect = _deny\n"
        "socket.socket.connect_ex = _deny\n"
        "socket.socket.sendto = _deny\n"
        "socket.create_connection = _deny\n"
        "socket.getaddrinfo = _deny\n",
        encoding="utf-8",
    )
    qea = tmp_path / "cli.qea"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(preload), str(ROOT), str(RULES_DIR)])
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "eam_suite.py"),
            "--no-llm",
            "run",
            str(CSV_MIXED),
            "--rules",
            str(RULES),
            "-o",
            str(qea),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Netz gesperrt" not in result.stderr
    assert qea.read_bytes().startswith(b"SQLite format 3\x00")


def test_deterministisch_gleicher_input_gleiche_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Zwei Laeufe liefern byte-identische .qea und findings.json."""
    _block_network(monkeypatch)
    hashes = []
    for name in ("a", "b"):
        qea = tmp_path / f"{name}.qea"
        findings = tmp_path / f"{name}.json"
        result = eam_suite.run_pipeline(
            [CSV_MIXED],
            rules_path=RULES,
            requirements_path=REQUIREMENTS,
            target=qea,
            findings_path=findings,
        )
        assert result.exported
        hashes.append(
            (
                hashlib.sha256(qea.read_bytes()).hexdigest(),
                hashlib.sha256(findings.read_bytes()).hexdigest(),
            )
        )
    assert hashes[0] == hashes[1]


# --------------------------------------------------------------------------
# 3. Strukturierte Quellen ohne KI: JSON-IR, QEA, CSV, XLSX
# --------------------------------------------------------------------------


def test_quellen_liefern_dasselbe_ir(tmp_path: Path) -> None:
    """Gemischte CSV, drei Einzel-CSVs und XLSX ergeben identisches IR."""
    mixed = eam_suite.import_sources([CSV_MIXED])
    multi = eam_suite.import_sources([CSV_PACKAGES, CSV_ELEMENTS, CSV_CONNECTORS])
    xlsx = write_xlsx(
        tmp_path / "modell.xlsx",
        {
            "packages": _csv_rows(CSV_PACKAGES),
            "elements": _csv_rows(CSV_ELEMENTS),
            "connectors": _csv_rows(CSV_CONNECTORS),
        },
    )
    from_xlsx = eam_suite.import_sources([xlsx])

    assert mixed == multi
    assert mixed == from_xlsx
    assert table_import.dumps_ir(mixed) == table_import.dumps_ir(from_xlsx)
    assert [package["path"] for package in mixed["packages"]] == [
        "Architektur",
        "Architektur/Ressourcen",
    ]


def test_json_und_qea_roundtrip_ohne_ki(tmp_path: Path) -> None:
    """IR -> .qea -> IR und IR-JSON -> IR bleiben semantisch gleich."""
    ir = eam_suite.import_sources([CSV_MIXED])
    qea = write_qea(ir, tmp_path / "modell.qea")
    from_qea = eam_suite.import_sources([qea])
    assert semantic_equal(ir, from_qea)

    json_path = tmp_path / "modell.json"
    json_path.write_text(render_json(ir), encoding="utf-8")
    from_json = eam_suite.import_sources([json_path])
    assert from_json == ir


def test_validate_und_export_ueber_die_cli(tmp_path: Path) -> None:
    """Pruefen und Exportieren funktionieren ohne KI und ohne Netz."""
    ir = eam_suite.import_sources([CSV_MIXED])
    source = tmp_path / "modell.json"
    source.write_text(render_json(ir), encoding="utf-8")
    findings = tmp_path / "findings.json"
    qea = tmp_path / "modell.qea"

    assert eam_suite.main(["-q", "validate", str(source), str(RULES), "-o", str(findings)]) == 0
    assert json.loads(findings.read_text(encoding="utf-8")) == []
    assert eam_suite.main(["-q", "export", str(source), str(qea)]) == 0
    assert semantic_equal(ir, read_qea(qea))


def test_regelverstoss_bricht_export_ab(tmp_path: Path) -> None:
    """Fehler blockieren den Export (Exit 1, keine .qea); --strict auch Warnungen."""
    ir = eam_suite.import_sources([CSV_MIXED])
    broken = copy.deepcopy(ir)
    broken["elements"][1]["stereotype"] = "Unbekannt"
    source = tmp_path / "broken.json"
    source.write_text(render_json(broken), encoding="utf-8")
    target = tmp_path / "broken.qea"

    assert (
        eam_suite.main(
            ["-q", "run", str(source), "--rules", str(RULES), "-o", str(target)]
        )
        == 1
    )
    assert not target.exists()

    warned = copy.deepcopy(ir)
    warned["elements"][0]["ea_type"] = "Class"  # ServicePort erwartet Port -> Warnung
    warned_source = tmp_path / "warned.json"
    warned_source.write_text(render_json(warned), encoding="utf-8")

    lenient = eam_suite.run_pipeline(
        warned_source, rules_path=RULES, target=tmp_path / "lenient.qea"
    )
    assert lenient.exported
    strict = eam_suite.run_pipeline(
        warned_source, rules_path=RULES, target=tmp_path / "strict.qea", strict=True
    )
    assert not strict.exported
    assert not (tmp_path / "strict.qea").exists()


# --------------------------------------------------------------------------
# 4. Fehler sind laut, nie still
# --------------------------------------------------------------------------


def test_csv_fehler_sind_laut(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.csv"
    unknown.write_text("path,quatsch\nA,B\n", encoding="utf-8")
    with pytest.raises(TableImportError, match="unbekannte Spalte 'quatsch'"):
        eam_suite.import_sources([unknown])

    semicolon = tmp_path / "semicolon.csv"
    semicolon.write_text("path;name\nA;B\n", encoding="utf-8")
    with pytest.raises(TableImportError, match="Semikolon"):
        eam_suite.import_sources([semicolon])

    empty = tmp_path / "leer.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(TableImportError, match="Datei ist leer"):
        eam_suite.import_sources([empty])

    missing = tmp_path / "missing.csv"
    missing.write_text("source,name\nA,B\n", encoding="utf-8")
    with pytest.raises(TableImportError, match="Pflichtspalte"):
        table_import.import_csv(missing, kind="connectors")

    no_elements = tmp_path / "nur_pakete.csv"
    no_elements.write_text("path\nA\n", encoding="utf-8")
    with pytest.raises(TableImportError, match="kein Element"):
        table_import.import_csv(no_elements, kind="packages")

    orphan = tmp_path / "elternlos.csv"
    orphan.write_text(
        "record,path,package,name\n"
        "package,A/B,,\n"
        "element,,A/B,X\n",
        encoding="utf-8",
    )
    with pytest.raises(TableImportError, match="Elternpaket 'A' fehlt"):
        eam_suite.import_sources([orphan])


def test_xlsx_und_quellen_fehler_sind_laut(tmp_path: Path) -> None:
    broken = tmp_path / "kaputt.xlsx"
    broken.write_text("kein ZIP", encoding="utf-8")
    with pytest.raises(TableImportError, match="keine gueltige .xlsx"):
        eam_suite.import_sources([broken])

    unknown_sheet = write_xlsx(tmp_path / "blatt.xlsx", {"Tabelle1": [["path"], ["A"]]})
    with pytest.raises(TableImportError, match="unbekanntes Blatt 'Tabelle1'"):
        eam_suite.import_sources([unknown_sheet])

    old = tmp_path / "alt.xls"
    old.write_text("x", encoding="utf-8")
    with pytest.raises(TableImportError, match="Quellenart nicht erkannt"):
        eam_suite.import_sources([old])

    json_source = tmp_path / "ir.json"
    json_source.write_text(
        render_json(eam_suite.import_sources([CSV_MIXED])), encoding="utf-8"
    )
    with pytest.raises(TableImportError, match="mehrere Quellen"):
        eam_suite.import_sources([json_source, CSV_MIXED])
    with pytest.raises(TableImportError, match="nur fuer Tabellen"):
        eam_suite.import_sources([json_source], table_kind="elements")
    with pytest.raises(TableImportError, match="passt nicht zur Dateiendung"):
        eam_suite.import_sources([CSV_MIXED], kind="xlsx")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text('{"ir_version": 1, "elements": []}', encoding="utf-8")
    with pytest.raises(QeaWriterError):
        eam_suite.import_sources([bad_json])
