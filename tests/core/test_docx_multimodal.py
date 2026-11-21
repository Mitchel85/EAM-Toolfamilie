"""Tests fuer multimodalen Input (DOCX mit Tabellen und Bildern, CSV-Tabellen, Mehrfachdateien)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
import pytest

import eam_ai
import extract as ex
import image_input

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"


def _build_docx(
    paragraphs: list[str],
    *,
    table: list[list[str]] | None = None,
    header: str = "",
    footer: str = "",
    footnotes: list[str] | None = None,
    media: dict[str, bytes] | None = None,
) -> bytes:
    """Erzeugt ein synthetisches DOCX im Speicher."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Content Types
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        
        # document.xml
        body_xml = []
        for p in paragraphs:
            body_xml.append(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>')
        if table:
            tbl_xml = ['<w:tbl>']
            for row in table:
                tbl_xml.append('<w:tr>')
                for cell in row:
                    tbl_xml.append(f'<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>')
                tbl_xml.append('</w:tr>')
            tbl_xml.append('</w:tbl>')
            body_xml.append("".join(tbl_xml))
            
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{"".join(body_xml)}</w:body></w:document>'
        )
        z.writestr("word/document.xml", doc_xml)
        
        if header:
            z.writestr(
                "word/header1.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>{header}</w:t></w:r></w:p></w:hdr>',
            )
        if footer:
            z.writestr(
                "word/footer1.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>{footer}</w:t></w:r></w:p></w:ftr>',
            )
        if footnotes:
            fn_body = "".join(f'<w:footnote w:id="{i}"><w:p><w:r><w:t>{fn}</w:t></w:r></w:p></w:footnote>' for i, fn in enumerate(footnotes, 1))
            z.writestr(
                "word/footnotes.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{fn_body}</w:footnotes>',
            )
        if media:
            for name, data in media.items():
                z.writestr(f"word/media/{name}", data)
    return buf.getvalue()


def test_docx_extrahiert_tabelle_als_markdown(tmp_path: Path) -> None:
    docx_bytes = _build_docx(
        ["Einleitender Absatz ueber das System."],
        table=[
            ["Element", "Stereotyp", "Beschreibung"],
            ["Zentraler Dienst", "ServiceSpecification", "Erbringt Dienste fuer Klienten."],
            ["Lagebild", "Capability", "Strategische Faehigkeit."],
        ],
    )
    p = tmp_path / "doku.docx"
    p.write_bytes(docx_bytes)
    
    text = eam_ai.read_text_source(p)
    assert "Einleitender Absatz ueber das System." in text
    assert "| Element | Stereotyp | Beschreibung |" in text
    assert "| --- | --- | --- |" in text
    assert "| Zentraler Dienst | ServiceSpecification | Erbringt Dienste fuer Klienten. |" in text


def test_docx_extrahiert_kopf_fusszeilen_und_fussnoten(tmp_path: Path) -> None:
    docx_bytes = _build_docx(
        ["Haupttext."],
        header="Kopfzeile: Vertraulich",
        footer="Fusszeile: Seite 1",
        footnotes=["Fussnote 1: Referenzdokument A"],
    )
    p = tmp_path / "doku.docx"
    p.write_bytes(docx_bytes)
    
    text = eam_ai.read_text_source(p)
    assert "Haupttext." in text
    assert "Kopfzeile: Vertraulich" in text
    assert "Fusszeile: Seite 1" in text
    assert "Fussnote 1: Referenzdokument A" in text


def test_docx_extrahiert_eingebettete_bilder(tmp_path: Path) -> None:
    docx_bytes = _build_docx(
        ["Architekturuebersicht siehe Diagramm."],
        media={"architektur.png": PNG},
    )
    p = tmp_path / "doku.docx"
    p.write_bytes(docx_bytes)
    
    images: list[tuple[bytes, str, str]] = []
    text = eam_ai.read_text_source(p, image_sink=images)
    assert "Architekturuebersicht siehe Diagramm." in text
    assert len(images) == 1
    assert images[0][1] == "architektur.png"
    assert images[0][2] == "image/png"


def test_csv_tabelle_als_markdown_quelle(tmp_path: Path) -> None:
    csv_text = "Name,Stereotyp,Notiz\nDienst A,ServiceSpecification,Zentraler Dienst\nKatalog B,Capability,Faehigkeit\n"
    p = tmp_path / "tabelle.csv"
    p.write_text(csv_text, encoding="utf-8")
    
    text = eam_ai.read_text_source(p)
    assert "| Name | Stereotyp | Notiz |" in text
    assert "| --- | --- | --- |" in text
    assert "| Dienst A | ServiceSpecification | Zentraler Dienst |" in text


def test_build_mit_mehreren_texten_und_bildern(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mdg = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures" / "admbw_auszug.xml"
    
    t1 = tmp_path / "doc1.txt"
    t1.write_text("Dienst Alpha erbringt den Prozess Eins.", encoding="utf-8")
    t2 = tmp_path / "doc2.txt"
    t2.write_text("Dienst Beta unterstuetzt den Prozess Zwei.", encoding="utf-8")
    
    img = tmp_path / "arch.png"
    img.write_bytes(PNG)
    (tmp_path / "arch.txt").write_text("Faehigkeit Gamma ist uebergeordnet.", encoding="utf-8")
    
    antwort = {
        "elements": [
            {"name": "Dienst Alpha", "stereotype": "ServiceSpecification", "notes": "n1", "source_ref": "D2-S1", "confidence": 0.9},
            {"name": "Faehigkeit Gamma", "stereotype": "Capability", "notes": "n2", "source_ref": "D1-S1", "confidence": 0.95},
        ],
        "connectors": [],
    }
    backend = ex.StaticBackend([json.dumps(antwort)])
    
    report = eam_ai.build(
        struktur=False,
        mdg=mdg,
        text=[t1, t2],
        images=[img],
        out=tmp_path / "modell.qea",
        backend=backend,
        findings_path=tmp_path / "findings.json",
    )
    assert report.exported is True
    assert report.elements == 2
