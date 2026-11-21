"""SVG- und PNG-Export: deterministisch, ohne Browser, ohne Netz."""

from __future__ import annotations

import hashlib
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from bpmn import exporte
from bpmn import modell as m

WURZEL = Path(__file__).resolve().parents[2]


def test_svg_ist_deterministisch(modell: m.Modell) -> None:
    assert exporte.svg_text(modell) == exporte.svg_text(modell)


def test_svg_ohne_zeitstempel_und_zufall(modell: m.Modell) -> None:
    text = exporte.svg_text(modell)
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert "Z\"" not in text
    assert "Math.random" not in text
    assert "Date(" not in text


def test_svg_ist_wohlgeformt(modell: m.Modell) -> None:
    import xml.etree.ElementTree as ET

    text = exporte.svg_text(modell)
    wurzel = ET.fromstring(text)
    assert wurzel.tag == "{http://www.w3.org/2000/svg}svg"
    assert wurzel.get("viewBox")
    assert float(wurzel.get("width")) > 100


def test_svg_zeichnet_alle_elementarten(modell: m.Modell) -> None:
    text = exporte.svg_text(modell)
    assert text.count("<circle") >= 2          # Startereignis und Endereignis
    assert 'marker-end="url(#pfeil)"' in text  # Kontrollfluss
    assert "stroke-dasharray" in text          # Nachrichtenfluss
    assert "<rect" in text
    assert 'rx="8"' in text                    # Aufgabe
    assert "<polyline" in text


def test_svg_enthaelt_namen(modell: m.Modell) -> None:
    text = exporte.svg_text(modell)
    for name in ("Antrag erfassen", "Antrag pruefen", "vollstaendig?"):
        assert name in text


def test_svg_escaped_sonderzeichen() -> None:
    modell = m.Modell(name="A & B <C>")
    prozess = modell.neuer_prozess("P")
    start = modell.neuer_knoten("start_event", "Start & Ende", prozess)
    modell.neuer_knoten("task", "Prüfen <jetzt>", prozess)
    from bpmn import layout

    layout.verteile(modell)
    text = exporte.svg_text(modell)
    assert "&amp;" in text
    assert "&lt;jetzt&gt;" in text
    assert "<jetzt>" not in text
    assert start.id  # nur zur Sicherheit, dass das Modell gebaut wurde


def test_svg_in_zwei_prozessen_gleich(modell: m.Modell) -> None:
    """Hash-Streuung darf die Ausgabe nicht beeinflussen."""
    skript = (
        "import sys, hashlib;"
        "sys.path.insert(0, 'packages');"
        "from bpmn import bpmn_xml, exporte;"
        "m = bpmn_xml.lies(sys.argv[1]);"
        "print(hashlib.sha256(exporte.svg_text(m).encode()).hexdigest())"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as ordner:
        pfad = Path(ordner) / "m.bpmn"
        from bpmn import bpmn_xml

        bpmn_xml.schreibe(modell, str(pfad))
        hashes = []
        for seed in ("0", "12345"):
            umgebung = {"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}
            ergebnis = subprocess.run(
                [sys.executable, "-c", skript, str(pfad)],
                cwd=WURZEL,
                capture_output=True,
                text=True,
                env=umgebung,
                check=True,
            )
            hashes.append(ergebnis.stdout.strip())
    assert hashes[0] == hashes[1]


def test_png_hat_gueltiges_format(modell: m.Modell) -> None:
    daten = exporte.exportiere_png(modell, backend="intern")
    assert daten[:8] == b"\x89PNG\r\n\x1a\n"
    breite, hoehe = struct.unpack(">II", daten[16:24])
    assert breite > 100 and hoehe > 100


def test_png_ist_byte_gleich(modell: m.Modell) -> None:
    assert exporte.exportiere_png(modell, backend="intern") == exporte.exportiere_png(
        modell, backend="intern"
    )


def test_png_auto_backend_ist_deterministisch(modell: m.Modell) -> None:
    assert exporte.exportiere_png(modell) == exporte.exportiere_png(modell)


def test_png_über_pfad(tmp_path, modell: m.Modell) -> None:
    ziel = tmp_path / "prozess.png"
    exporte.exportiere_png(modell, ziel, backend="intern")
    assert ziel.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_png_skalierung_veraendert_die_groesse(modell: m.Modell) -> None:
    klein = exporte.exportiere_png(modell, backend="intern", skalierung=1.0)
    gross = exporte.exportiere_png(modell, backend="intern", skalierung=2.0)
    assert struct.unpack(">II", gross[16:24])[0] > struct.unpack(">II", klein[16:24])[0]


def test_unbekannter_backend_meldet_sich() -> None:
    with pytest.raises(RuntimeError):
        exporte.exportiere_png(m.Modell(), backend="gibtsnicht")


def test_backends_listet_intern_immer() -> None:
    assert "intern" in exporte.backends()


def test_exportiere_alle_schreibt_beide(tmp_path, modell: m.Modell) -> None:
    pfade = exporte.exportiere_alle(modell, tmp_path, "antrag")
    assert pfade["svg"].is_file() and pfade["png"].is_file()
    assert pfade["svg"].read_text(encoding="utf-8").startswith("<?xml")


def test_leeres_modell_erzeugt_trotzdem_svg() -> None:
    text = exporte.svg_text(m.Modell(name="leer"))
    assert "<svg" in text and "</svg>" in text


def test_png_hash_stabil_über_prozesse(modell: m.Modell) -> None:
    """Auch der Rueckfallrasterer darf nicht von der Prozessstreuung abhaengen."""
    skript = (
        "import sys, hashlib;"
        "sys.path.insert(0, 'packages');"
        "from bpmn import bpmn_xml, exporte;"
        "m = bpmn_xml.lies(sys.argv[1]);"
        "print(hashlib.sha256(exporte.exportiere_png(m, backend='intern')).hexdigest())"
    )
    import tempfile

    from bpmn import bpmn_xml

    with tempfile.TemporaryDirectory() as ordner:
        pfad = Path(ordner) / "m.bpmn"
        bpmn_xml.schreibe(modell, str(pfad))
        hashes = []
        for seed in ("0", "999"):
            ergebnis = subprocess.run(
                [sys.executable, "-c", skript, str(pfad)],
                cwd=WURZEL,
                capture_output=True,
                text=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                check=True,
            )
            hashes.append(ergebnis.stdout.strip())
    assert hashes[0] == hashes[1]
    assert hashlib.sha256(hashes[0].encode()).hexdigest()
