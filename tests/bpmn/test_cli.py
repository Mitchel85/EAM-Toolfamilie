"""Die Kommandozeile ist der Python-Zugang zum BPMN Studio."""

from __future__ import annotations

import io
import zipfile
import zlib
from pathlib import Path
import pytest

from bpmn import cli

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"


def _build_docx(paragraphs: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        )
        body_xml = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body_xml}</w:body></w:document>',
        )
    return buf.getvalue()


def _build_pdf(content: str) -> bytes:
    stream = content.encode("latin-1")
    payload = zlib.compress(stream)
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(payload)} /Filter /FlateDecode >>\nstream\n".encode("latin-1")
        + payload
        + b"\nendstream\nendobj\n",
    ]
    xref_pos = 9
    offsets = [0]
    out = [b"%PDF-1.4\n"]
    for obj in objects:
        offsets.append(xref_pos)
        out.append(obj)
        xref_pos += len(obj)
    startxref = xref_pos
    xref = [f"xref\n0 {len(offsets)}\n".encode("latin-1")]
    xref.append(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("latin-1"))
    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{startxref}\n%%EOF\n"
    ).encode("latin-1")
    return b"".join(out) + b"".join(xref) + trailer


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


def test_extrahieren_aus_docx(tmp_path: Path) -> None:
    docx_bytes = _build_docx([
        "Der Sachbearbeiter nimmt den Antrag an.",
        "Danach prueft die Fachabteilung die Unterlagen.",
    ])
    doku = tmp_path / "prozess.docx"
    doku.write_bytes(docx_bytes)
    out_bpmn = tmp_path / "aus_docx.bpmn"
    assert cli.main(["extrahieren", str(doku), "-o", str(out_bpmn)]) == 0
    assert out_bpmn.is_file()
    inhalt = out_bpmn.read_text(encoding="utf-8")
    assert "Sachbearbeiter" in inhalt or "Fachabteilung" in inhalt or "task" in inhalt


def test_extrahieren_aus_pdf(tmp_path: Path) -> None:
    pdf_bytes = _build_pdf("BT /F1 12 Tf (Der Sachbearbeiter nimmt den Antrag an.) Tj ET")
    doku = tmp_path / "prozess.pdf"
    doku.write_bytes(pdf_bytes)
    out_bpmn = tmp_path / "aus_pdf.bpmn"
    assert cli.main(["extrahieren", str(doku), "-o", str(out_bpmn)]) == 0
    assert out_bpmn.is_file()


def test_extrahieren_bild_ohne_ki_wirft_fehler(tmp_path: Path) -> None:
    img = tmp_path / "diagramm.png"
    img.write_bytes(PNG)
    out_bpmn = tmp_path / "aus_bild.bpmn"
    with pytest.raises(ValueError, match="Flag --ki"):
        cli.main(["extrahieren", str(img), "-o", str(out_bpmn)])


def test_extrahieren_bild_mit_ki_begleiter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    img = tmp_path / "diagramm.png"
    img.write_bytes(PNG)
    (tmp_path / "diagramm.txt").write_text(
        "Der Sachbearbeiter nimmt den Antrag an. Danach prueft die Fachabteilung die Unterlagen.",
        encoding="utf-8",
    )
    monkeypatch.setenv("BPMN_KI_AKTIV", "1")
    monkeypatch.setenv("BPMN_KI_BASIS_URL", "https://api.example.com/v1")
    monkeypatch.setenv("BPMN_KI_MODELL", "dummy-model")
    monkeypatch.setenv("BPMN_KI_KEY", "secret-test-key")

    called = []

    def dummy_extrahiere(text, **kwargs):
        called.append(text)
        from bpmn import extraktion
        return extraktion.extrahiere(text)

    monkeypatch.setattr("bpmn.ki.extrahiere_mit_ki", dummy_extrahiere)

    out_bpmn = tmp_path / "aus_bild.bpmn"
    assert cli.main(["extrahieren", str(img), "-o", str(out_bpmn), "--ki"]) == 0
    assert out_bpmn.is_file()
    assert len(called) == 1
    assert "Sachbearbeiter" in called[0]
