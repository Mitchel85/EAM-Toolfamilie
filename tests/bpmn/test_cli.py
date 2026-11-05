"""Die Kommandozeile ist der Python-Zugang zum BPMN Studio."""

from __future__ import annotations

from pathlib import Path

from bpmn import cli


def test_alle_vier_befehle_laufen_auf_einer_datei(tmp_path: Path) -> None:
    text = tmp_path / "text.txt"
    text.write_text(
        "Der Sachbearbeiter nimmt den Antrag an. Danach prueft die Fachabteilung "
        "die Unterlagen. Anschliessend entscheidet der Referatsleiter.",
        encoding="utf-8",
    )
    roh = tmp_path / "prozess.bpmn"
    assert cli.main(["extrahieren", str(text), "-o", str(roh)]) == 0
    assert roh.is_file() and roh.read_text(encoding="utf-8").startswith("<?xml")

    assert cli.main(["pruefen", str(roh)]) in (0, 1)

    konform = tmp_path / "konform.bpmn"
    assert cli.main(["konform", str(roh), "-o", str(konform)]) == 0

    svg = tmp_path / "bild.svg"
    assert cli.main(["export", str(konform), "--format", "svg", "-o", str(svg)]) == 0
    assert "<svg" in svg.read_text(encoding="utf-8")[:400]

    png = tmp_path / "bild.png"
    assert cli.main(["export", str(konform), "--format", "png", "-o", str(png)]) == 0
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    xml = tmp_path / "kopie.bpmn"
    assert cli.main(["export", str(konform), "--format", "xml", "-o", str(xml)]) == 0
    assert xml.read_text(encoding="utf-8") == konform.read_text(encoding="utf-8")
