"""Tests fuer den PDF-Leser (Standardbibliothek, ohne Fremdpakete).

Die Fixtures werden im Test erzeugt -- kein Binaerartefakt im Repo, keine
Abhaengigkeit von einem Beispiel-PDF. Geprueft wird der ganze Weg:
Bytes -> Objekte -> Stroeme -> Text, inklusive Umlauten ueber ``/ToUnicode``.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import pytest

import pdf_text
from eam_ai import BuildError, read_text_source


def _build_pdf(
    content: str,
    *,
    cmap: dict[int, str] | None = None,
    compress: bool = True,
    extra_objects: str = "",
) -> bytes:
    """Minimales, gueltiges PDF mit einem Inhaltsstrom bauen."""
    stream = content.encode("latin-1")
    if compress:
        payload = zlib.compress(stream)
        filter_entry = b"/Filter /FlateDecode "
    else:
        payload = stream
        filter_entry = b""

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_number = None
    cmap_number = None
    if cmap:
        entries = "\n".join(
            f"<{code:02X}> <{ord(char):04X}>" for code, char in cmap.items()
        )
        cmap_stream = (
            "/CIDInit /ProcSet findresource begin\n"
            "12 dict begin\nbegincmap\n"
            "/CMapName /Test def\n"
            "1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
            f"{len(cmap)} beginbfchar\n{entries}\nendbfchar\n"
            "endcmap\nend\nend\n"
        ).encode("latin-1")
        cmap_number = add(
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(cmap_stream), cmap_stream)
        )

    to_unicode = f"/ToUnicode {cmap_number} 0 R " if cmap_number else ""
    font_number = add(
        (
            f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica {to_unicode}>>"
        ).encode("latin-1")
    )
    contents_number = add(
        b"<< %s/Length %d >>\nstream\n" % (filter_entry, len(payload))
        + payload
        + b"\nendstream"
    )
    page_number = add(
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/Contents {contents_number} 0 R >>"
        ).encode("latin-1")
    )
    add(f"<< /Type /Pages /Kids [{page_number} 0 R] /Count 1 >>".encode("latin-1"))
    add(b"<< /Type /Catalog /Pages 2 0 R >>")

    header = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body += b"%d 0 obj\n" % index + obj + b"\nendobj\n"
    if extra_objects:
        body += extra_objects.encode("latin-1")

    xref_offset = len(header) + len(body)
    xref = [b"xref\n", b"0 %d\n" % (len(objects) + 1), b"0000000000 65535 f \n"]
    for offset in offsets:
        xref.append(b"%010d 00000 n \n" % offset)
    trailer = (
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, len(objects), xref_offset)
    )
    return header + body + b"".join(xref) + trailer


def test_pdf_liefert_prosa(tmp_path: Path) -> None:
    content = (
        "BT /F1 12 Tf 72 720 Td (Die Anwendung greift auf den Datenbestand zu.) Tj\n"
        "0 -18 Td (Der Datenbestand wird taeglich gesichert.) Tj ET"
    )
    path = tmp_path / "prosa.pdf"
    path.write_bytes(_build_pdf(content))

    text = read_text_source(path)
    assert "Datenbestand" in text
    assert "taeglich gesichert" in text


def test_pdf_umlaute_ueber_tounicode(tmp_path: Path) -> None:
    # Bytes 01..04 stehen fuer Umlaute; ohne ToUnicode waeren sie unlesbar.
    cmap = {0x01: "Ä", 0x02: "ö", 0x03: "ü", 0x04: "ß"}
    content = "BT /F1 12 Tf 72 720 Td (Gr\\002\\004e f\\003r B\\003e) Tj ET"
    path = tmp_path / "umlaut.pdf"
    path.write_bytes(_build_pdf(content, cmap=cmap))

    text = read_text_source(path)
    assert "Größe für Bü" in text


def test_pdf_tj_array_und_absaetze(tmp_path: Path) -> None:
    content = (
        "BT /F1 12 Tf 72 720 Td [(Ein) -20 (Satz)] TJ ET\n"
        "BT /F1 12 Tf 72 680 Td (Zweiter Absatz) Tj ET"
    )
    path = tmp_path / "absaetze.pdf"
    path.write_bytes(_build_pdf(content))

    text = read_text_source(path)
    assert "EinSatz" in text.replace(" ", "") or "Ein Satz" in text
    assert "Zweiter Absatz" in text
    assert "\n\n" in text


def test_pdf_ohne_kompression(tmp_path: Path) -> None:
    content = "BT /F1 10 Tf 72 700 Td (Unkomprimiert) Tj ET"
    path = tmp_path / "roh.pdf"
    path.write_bytes(_build_pdf(content, compress=False))
    assert "Unkomprimiert" in read_text_source(path)


def test_scan_ohne_textebene_bricht_laut_ab(tmp_path: Path) -> None:
    # Inhaltsstrom ohne Textoperatoren: reines Bilddokument.
    content = "q 595 0 0 842 0 0 cm /Im0 Do Q"
    path = tmp_path / "scan.pdf"
    path.write_bytes(_build_pdf(content))

    with pytest.raises(BuildError) as fehler:
        read_text_source(path)
    assert "Scan" in str(fehler.value)


def test_verschluesseltes_pdf_bricht_ab(tmp_path: Path) -> None:
    path = tmp_path / "geschuetzt.pdf"
    basis = _build_pdf("BT /F1 12 Tf 72 720 Td (Geheim) Tj ET")
    path.write_bytes(basis.replace(b"/Root", b"/Encrypt 9 0 R /Root"))
    with pytest.raises(BuildError) as fehler:
        read_text_source(path)
    assert "passwortgeschuetzt" in str(fehler.value)


def test_keine_pdf_datei(tmp_path: Path) -> None:
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"Das ist kein PDF")
    with pytest.raises(pdf_text.PdfError) as fehler:
        pdf_text.extract_text(path)
    assert "keine PDF-Datei" in str(fehler.value)


def test_leere_datei(tmp_path: Path) -> None:
    path = tmp_path / "leer.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(pdf_text.PdfError):
        pdf_text.extract_text(path)
