"""PDF-Text lesen -- ohne Fremdbibliothek, nur Standardbibliothek.

Warum eigener Leser: Der Kern ist bewusst abhaengigkeitsfrei (siehe README).
Ein PDF ist ein Behaelter aus Objekten, deren Inhaltsstroeme meist mit zlib
gepackt sind. Fuer Prosa genuegt es, diese Stroeme zu entpacken und die
Textoperatoren (``Tj``, ``TJ``, ``'``, ``"``) auszulesen. Schriften mit
Teilmenge bringen eine ``/ToUnicode``-Tabelle mit; ohne sie waeren Umlaute
und Sonderzeichen falsch. Beides wird hier bedient.

Grenzen, die bewusst laut gemeldet werden statt still falschen Text zu liefern:

* verschluesselte PDFs (Passwort) -- nicht lesbar,
* Scans ohne Textebene -- es gibt nichts zu extrahieren,
* Stroeme mit Filtern ausser ``FlateDecode`` (z. B. JPEG2000-Bilder) --
  die tragen ohnehin keinen Text.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path


class PdfError(ValueError):
    """PDF nicht lesbar -- Meldung ist fuer den Benutzer gedacht."""


# --------------------------------------------------------------------------
# Objekte und Stroeme
# --------------------------------------------------------------------------

_OBJ_RE = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj\b", re.S)
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\n?endstream", re.S)
_REF_RE = re.compile(rb"(\d+)\s+\d+\s+R")


@dataclass
class PdfObject:
    number: int
    body: bytes
    stream: bytes | None = None

    @property
    def dictionary(self) -> bytes:
        if self.stream is None:
            return self.body
        head, sep, _ = self.body.partition(b"stream")
        return head if sep else self.body


def _decode_stream(obj: PdfObject) -> bytes:
    """Stream entpacken, sofern ein bekannter Filter gesetzt ist."""
    data = obj.stream
    if data is None:
        return b""
    dictionary = obj.dictionary
    if b"/FlateDecode" in dictionary:
        try:
            return zlib.decompress(data)
        except zlib.error:
            # Manche Erzeuger schreiben den zlib-Kopf nicht mit.
            try:
                return zlib.decompress(data, -15)
            except zlib.error:
                return b""
    if b"/Filter" in dictionary:
        # Andere Filter (Bilder, LZW, RunLength) tragen keinen Fliesstext.
        return b""
    return data


def _parse_objects(raw: bytes) -> dict[int, PdfObject]:
    objects: dict[int, PdfObject] = {}
    for match in _OBJ_RE.finditer(raw):
        number = int(match.group(1))
        body = match.group(3)
        stream_match = _STREAM_RE.search(body)
        stream = stream_match.group(1) if stream_match else None
        objects[number] = PdfObject(number=number, body=body, stream=stream)
    return objects


def _expand_object_streams(objects: dict[int, PdfObject]) -> None:
    """Objekte aus komprimierten Objektstroemen (``/Type /ObjStm``) nachziehen.

    Viele Erzeuger legen Schriften, Seiten und ``/ToUnicode``-Tabellen nicht
    als freie Objekte ab, sondern gepackt in einem Objektstrom. Ohne dieses
    Auspacken findet der Leser weder Schrift noch Zeichentabelle -- der Text
    kaeme dann als Zeichensalat heraus.
    """
    additions: dict[int, PdfObject] = {}
    for container in list(objects.values()):
        if container.stream is None or b"/ObjStm" not in container.dictionary:
            continue
        payload = _decode_stream(container)
        if not payload:
            continue
        count_match = re.search(rb"/N\s+(\d+)", container.dictionary)
        first_match = re.search(rb"/First\s+(\d+)", container.dictionary)
        if not count_match or not first_match:
            continue
        count = int(count_match.group(1))
        first = int(first_match.group(1))
        header = payload[:first].split()
        if len(header) < count * 2:
            continue
        for index in range(count):
            try:
                number = int(header[index * 2])
                offset = int(header[index * 2 + 1])
            except (IndexError, ValueError):
                continue
            start = first + offset
            end = first + int(header[(index + 1) * 2 + 1]) if index + 1 < count else len(payload)
            body = payload[start:end]
            if number not in objects:
                additions[number] = PdfObject(number=number, body=body, stream=None)
    objects.update(additions)


def _resolve(objects: dict[int, PdfObject], token: bytes) -> PdfObject | None:
    match = _REF_RE.search(token)
    if not match:
        return None
    return objects.get(int(match.group(1)))


# --------------------------------------------------------------------------
# ToUnicode-Tabellen
# --------------------------------------------------------------------------

_HEX_PAIR_RE = re.compile(rb"<([0-9A-Fa-f]+)>")
_BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)


def _utf16be(code: bytes) -> str:
    try:
        return code.decode("utf-16-be", errors="ignore")
    except Exception:  # pragma: no cover - defensiv
        return ""


def _parse_cmap(payload: bytes) -> dict[int, str]:
    """``beginbfchar``/``beginbfrange`` in eine Code->Zeichen-Tabelle uebersetzen."""
    table: dict[int, str] = {}

    for block in _BFCHAR_RE.findall(payload):
        pairs = re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block)
        for source, target in pairs:
            try:
                table[int(source, 16)] = _utf16be(bytes.fromhex(target.decode()))
            except ValueError:
                continue

    for block in _BFRANGE_RE.findall(payload):
        for source_low, source_high, rest in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)",
            block,
        ):
            try:
                low, high = int(source_low, 16), int(source_high, 16)
            except ValueError:
                continue
            if high < low or high - low > 65535:
                continue
            if rest.startswith(b"["):
                targets = _HEX_PAIR_RE.findall(rest)
                for offset, target in enumerate(targets[: high - low + 1]):
                    table[low + offset] = _utf16be(bytes.fromhex(target.decode()))
            else:
                base = bytes.fromhex(rest.strip(b"<>").decode())
                if not base:
                    continue
                start = int.from_bytes(base, "big")
                width = len(base)
                for offset in range(high - low + 1):
                    value = (start + offset).to_bytes(width, "big")
                    table[low + offset] = _utf16be(value)
    return table


def _font_cmaps(objects: dict[int, PdfObject]) -> tuple[dict[str, dict[int, str]], dict[int, dict[int, str]]]:
    """Schriftname -> Tabelle und Objektnummer -> Tabelle."""
    by_name: dict[str, dict[int, str]] = {}
    by_object: dict[int, dict[int, str]] = {}

    for number, obj in objects.items():
        dictionary = obj.dictionary
        if b"/Font" not in dictionary and b"/BaseFont" not in dictionary:
            continue
        match = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", dictionary)
        if not match:
            continue
        target = objects.get(int(match.group(1)))
        if target is None:
            continue
        table = _parse_cmap(_decode_stream(target))
        if table:
            by_object[number] = table

    # Ressourcen fuehren Namen auf Objekte: /Font << /F1 5 0 R /F2 7 0 R >>
    # Die Klammerung wird gezaehlt, weil Schrift-Diktionare selbst verschachtelt
    # sein koennen (DescendantFonts, FontDescriptor) -- ein Regex bis zum ersten
    # ">>" schneidet sonst mitten im Eintrag ab.
    for obj in objects.values():
        for match in re.finditer(rb"/Font\s*<<", obj.body):
            start = match.end() - 2
            depth = 0
            end = start
            while end < len(obj.body):
                if obj.body[end : end + 2] == b"<<":
                    depth += 1
                    end += 2
                    continue
                if obj.body[end : end + 2] == b">>":
                    depth -= 1
                    end += 2
                    if depth == 0:
                        break
                    continue
                end += 1
            block = obj.body[start:end]
            for name, number in re.findall(rb"/([A-Za-z0-9_.+-]+)\s+(\d+)\s+\d+\s+R", block):
                table = by_object.get(int(number))
                if table:
                    by_name[name.decode("latin-1", "ignore")] = table
    return by_name, by_object


# --------------------------------------------------------------------------
# Inhaltsstroeme
# --------------------------------------------------------------------------

_TEXT_ESCAPES = {
    ord("n"): b"\n",
    ord("r"): b"\r",
    ord("t"): b"\t",
    ord("b"): b"\b",
    ord("f"): b"\f",
    ord("("): b"(",
    ord(")"): b")",
    ord("\\"): b"\\",
}


def _unescape(payload: bytes) -> bytes:
    out = bytearray()
    index = 0
    while index < len(payload):
        byte = payload[index]
        if byte != 0x5C:  # backslash
            out.append(byte)
            index += 1
            continue
        index += 1
        if index >= len(payload):
            break
        nxt = payload[index]
        if nxt in _TEXT_ESCAPES:
            out.extend(_TEXT_ESCAPES[nxt])
            index += 1
        elif 0x30 <= nxt <= 0x37:  # oktal
            digits = bytearray()
            while index < len(payload) and len(digits) < 3 and 0x30 <= payload[index] <= 0x37:
                digits.append(payload[index])
                index += 1
            out.append(int(digits.decode(), 8) & 0xFF)
        elif nxt in (0x0A, 0x0D):  # Zeilenfortsetzung
            index += 1
            if nxt == 0x0D and index < len(payload) and payload[index] == 0x0A:
                index += 1
        else:
            out.append(nxt)
            index += 1
    return bytes(out)


def _decode_with(table: dict[int, str] | None, payload: bytes) -> str:
    if not table:
        return payload.decode("latin-1", errors="replace")
    if max(table) > 0xFF:
        width = 2
    else:
        width = 1
    chars: list[str] = []
    for offset in range(0, len(payload) - width + 1, width):
        code = int.from_bytes(payload[offset : offset + width], "big")
        if code in table:
            chars.append(table[code])
        elif width == 1 and 0x20 <= code < 0x7F:
            # Teilmenge der Tabelle: ASCII-Zeichen unveraendert durchreichen,
            # sonst gingen Ziffern und Satzzeichen in Mischschnitten verloren.
            chars.append(chr(code))
    return "".join(chars)


_TOKEN_RE = re.compile(
    rb"""
    (?P<literal>\((?:\\.|[^\\()])*\))      # (Text)
  | (?P<hex><[0-9A-Fa-f\s]*>)              # <48656C6C6F>
  | (?P<array>\[)                          # [ ... ] TJ
  | (?P<array_end>\])
  | (?P<name>/[^\s/\[\]()<>{}]+)           # /F1
  | (?P<number>-?\d+(?:\.\d+)?)            # 12.5
  | (?P<operator>[A-Za-z'"*]+)             # Tj, TJ, Td, Tf ...
  | (?P<other>\S)
    """,
    re.X | re.S,
)


def _extract_from_stream(
    payload: bytes,
    cmaps_by_name: dict[str, dict[int, str]],
    cmaps_by_object: dict[int, dict[int, str]],
) -> str:
    """Text aus einem Inhaltsstrom lesen. Gibt Prosa mit Zeilenumbruechen zurueck."""
    current: dict[int, str] | None = None
    pending_name: str | None = None
    pieces: list[str] = []
    array_buffer: list[str] | None = None
    operands: list[str] = []

    def newline() -> None:
        if pieces and pieces[-1] != "\n":
            pieces.append("\n")

    def paragraph_break() -> None:
        while pieces and pieces[-1] in ("\n", "\n\n"):
            pieces.pop()
        if pieces:
            pieces.append("\n\n")

    for match in _TOKEN_RE.finditer(payload):
        kind = match.lastgroup
        token = match.group()

        if kind == "name":
            name = token[1:].decode("latin-1", "ignore")
            if name in cmaps_by_name:
                current = cmaps_by_name[name]
            pending_name = name
            continue

        if kind == "array":
            array_buffer = []
            continue

        if kind == "array_end":
            if array_buffer is not None:
                operands.append("".join(array_buffer))
            array_buffer = None
            continue

        if kind == "literal":
            raw = _unescape(token[1:-1])
            text = _decode_with(current, raw)
            if array_buffer is not None:
                array_buffer.append(text)
            else:
                operands.append(text)
            continue

        if kind == "hex":
            cleaned = re.sub(rb"[^0-9A-Fa-f]", b"", token[1:-1])
            if len(cleaned) % 2:
                cleaned += b"0"
            raw = bytes.fromhex(cleaned.decode())
            text = _decode_with(current, raw)
            if array_buffer is not None:
                array_buffer.append(text)
            else:
                operands.append(text)
            continue

        if kind == "operator":
            # Nur Textoperatoren geben ihre Operanden aus. Ein Literal in einem
            # Markierungs-Diktionar (``/P<</Lang(de-DE)>>BDC``) ist *kein* Text --
            # ohne diese Trennung landen Sprachkuerzel wie "de-DE" tausendfach
            # mitten in der Prosa.
            if token == b"Tf" and pending_name is not None:
                current = cmaps_by_name.get(pending_name, current)
            elif token == b"BT":
                newline()
            elif token == b"ET":
                paragraph_break()
            elif token in (b"Td", b"TD", b"T*"):
                newline()
            elif token in (b"Tj", b"TJ", b"'", b'"'):
                if operands:
                    if token in (b"'", b'"'):
                        newline()
                    pieces.append("".join(operands))
            operands.clear()
            pending_name = None
    return "".join(pieces)


def _looks_like_content(payload: bytes) -> bool:
    if b"BT" not in payload:
        return False
    return b"Tj" in payload or b"TJ" in payload


def _content_streams(objects: dict[int, PdfObject]) -> list[bytes]:
    """Seiteninhalte in Dokumentreihenfolge.

    Zuerst ueber ``/Contents`` der Seitenobjekte, danach als Rueckfall alle
    Stroeme, die wie Inhaltsstroeme aussehen. Der Rueckfall hilft bei PDFs mit
    ungewoehnlicher Objektordnung, ohne Bilddaten einzuschleusen.
    """
    ordered: list[bytes] = []
    seen: set[int] = set()

    for obj in objects.values():
        if b"/Type" not in obj.body or b"/Page" not in obj.body:
            continue
        if b"/Pages" in obj.body:
            continue
        match = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", obj.body)
        if not match:
            continue
        for number in re.findall(rb"(\d+)\s+\d+\s+R", match.group(1)):
            index = int(number)
            if index in seen:
                continue
            target = objects.get(index)
            if target is None or target.stream is None:
                continue
            payload = _decode_stream(target)
            if payload:
                seen.add(index)
                ordered.append(payload)

    if ordered:
        return ordered

    for obj in objects.values():
        if obj.stream is None:
            continue
        payload = _decode_stream(obj)
        if payload and _looks_like_content(payload):
            ordered.append(payload)
    return ordered


# --------------------------------------------------------------------------
# Oeffentliche Schnittstelle
# --------------------------------------------------------------------------

@dataclass
class PdfText:
    text: str
    pages: int = 0
    tables: int = 0
    warnings: list[str] = field(default_factory=list)


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if line:
            buffer.append(line)
        elif buffer:
            paragraphs.append(" ".join(buffer))
            buffer = []
    if buffer:
        paragraphs.append(" ".join(buffer))
    # Silbentrennung am Zeilenende aufloesen: "Architek-\ntur" -> "Architektur".
    joined = "\n\n".join(paragraphs)
    return re.sub(r"(\w)-\n(\w)", r"\1\2", joined)


def extract_text(source: str | Path, *, max_chars: int = 2_000_000) -> PdfText:
    """Text aus einem PDF lesen.

    :raises PdfError: Datei fehlt, ist verschluesselt, beschaedigt oder ein
        Scan ohne Textebene.
    """
    path = Path(source)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise PdfError(f"PDF {path}: Datei nicht gefunden") from exc
    except OSError as exc:
        raise PdfError(f"PDF {path}: nicht lesbar ({exc})") from exc

    if not raw.startswith(b"%PDF"):
        raise PdfError(f"PDF {path}: keine PDF-Datei (Kopfzeile %PDF fehlt)")
    if b"/Encrypt" in raw[-4000:] or re.search(rb"\btrailer\b[^>]*?/Encrypt", raw):
        raise PdfError(
            f"PDF {path}: passwortgeschuetzt -- bitte ohne Schutz exportieren"
        )
    if b"%%EOF" not in raw[-2000:]:
        # Kein harter Abbruch: manche Erzeuger lassen die Marke weg.
        pass

    objects = _parse_objects(raw)
    if not objects:
        raise PdfError(f"PDF {path}: keine lesbaren Objekte -- Datei beschaedigt?")
    _expand_object_streams(objects)

    cmaps_by_name, cmaps_by_object = _font_cmaps(objects)
    page_count = sum(
        1
        for obj in objects.values()
        if b"/Type" in obj.body and b"/Page" in obj.body and b"/Pages" not in obj.body
    )

    # Inhaltsstroeme einer Seite sind Teil desselben Zeichenzustands: Schrift-
    # wechsel (``Tf``) und Textposition gelten ueber die Stroemgrenze hinweg.
    # Getrennt ausgewertet ginge die Schrift verloren, sobald ein Strom mitten
    # im Text beginnt -- genau das passiert bei Word-Exporten haeufig.
    payload = b"\n".join(_content_streams(objects))
    text = _normalise(_extract_from_stream(payload, cmaps_by_name, cmaps_by_object))
    if not text.strip():
        raise PdfError(
            f"PDF {path}: kein Text enthalten -- vermutlich ein Scan ohne Textebene. "
            "Bitte durchsuchbares PDF exportieren oder Text als .txt/.docx liefern."
        )
    if len(text) > max_chars:
        text = text[:max_chars]
    return PdfText(text=text, pages=page_count)
