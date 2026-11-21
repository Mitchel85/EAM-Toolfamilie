"""Kleiner YAML-Teilparser fuer die Pipeline-Dateien.

Warum kein PyYAML? Die Pipeline muss auch auf einem Runner ohne Netz und ohne
Fremdpakete pruefbar sein. Dieser Parser kennt genau die Teilmenge, die
``.gitlab-ci.yml`` und ``.github/workflows/ci.yml`` verwenden:

* Block-Mappings und Block-Sequenzen (Einrueckung mit Leerzeichen),
* ``- schluessel: wert`` als Sequenzeintrag mit Folgezeilen,
* einfache und doppelte Anfuehrungszeichen,
* Skalare ``true``/``false``/``null`` und Ganzzahlen,
* leere und einfache Fluss-Sequenzen ``[]``/``[a, b]``,
* Kommentare mit ``#``.

Alles andere (Anker, Aliase, Tags, Block-Skalare ``|``/``>``, Fluss-Mappings)
ist ein Fehler. Die Dateien bleiben damit schlicht, und neue Syntax kann nicht
still falsch gedeutet werden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INT_RE = re.compile(r"^-?[0-9]+$")
KEY_RE = re.compile(r"^[A-Za-z_.][A-Za-z0-9_.-]*$")
RESERVED_VALUE_START = {
    "&": "Anker sind nicht erlaubt",
    "*": "Aliase sind nicht erlaubt",
    "!": "Tags sind nicht erlaubt",
    "|": "Block-Skalare (|) sind nicht erlaubt",
    ">": "Block-Skalare (>) sind nicht erlaubt",
    "{": "Fluss-Mappings sind nicht erlaubt",
}


class YamlError(ValueError):
    """YAML ausserhalb der unterstuetzten Teilmenge -- immer laut."""


@dataclass
class _Line:
    number: int
    indent: int
    text: str


def _strip_comment(raw: str, where: str) -> str:
    quote = ""
    for index, char in enumerate(raw):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "#" and (index == 0 or raw[index - 1] in " \t"):
            return raw[:index].rstrip()
    if quote:
        raise YamlError(f"{where}: Anfuehrungszeichen nicht geschlossen")
    return raw.rstrip()


def _prepare(text: str, source: str) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        where = f"{source}:{number}"
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"{where}: Tabulator in der Einrueckung")
        stripped = _strip_comment(raw, where)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append(_Line(number=number, indent=indent, text=stripped[indent:]))
    if not lines:
        raise YamlError(f"{source}: Datei enthaelt keine YAML-Daten")
    return lines


def _split_key(text: str, where: str) -> tuple[str, str]:
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == ":" and (index + 1 == len(text) or text[index + 1] == " "):
            key = text[:index].strip()
            if not key:
                raise YamlError(f"{where}: leerer Schluessel")
            if key[0] in RESERVED_VALUE_START:
                raise YamlError(f"{where}: Schluessel {key!r} beginnt mit Sonderzeichen")
            return key, text[index + 1 :].strip()
    return "", ""


def _scalar(text: str, where: str) -> Any:
    if text == "":
        return None
    if text[0] in RESERVED_VALUE_START:
        raise YamlError(f"{where}: {RESERVED_VALUE_START[text[0]]}")
    if text[0] == "[":
        if not text.endswith("]"):
            raise YamlError(f"{where}: Fluss-Sequenz nicht geschlossen")
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part.strip(), where) for part in inner.split(",")]
    if text[0] == '"':
        if len(text) < 2 or not text.endswith('"'):
            raise YamlError(f"{where}: Anfuehrungszeichen nicht geschlossen")
        body = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return body
    if text[0] == "'":
        if len(text) < 2 or not text.endswith("'"):
            raise YamlError(f"{where}: Anfuehrungszeichen nicht geschlossen")
        return text[1:-1].replace("''", "'")
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if INT_RE.match(text):
        return int(text)
    return text


class _Parser:
    def __init__(self, lines: list[_Line], source: str) -> None:
        self.lines = lines
        self.source = source
        self.pos = 0

    @property
    def current(self) -> _Line:
        return self.lines[self.pos]

    def where(self, line: _Line | None = None) -> str:
        target = line or self.current
        return f"{self.source}:{target.number}"

    def parse(self) -> Any:
        if self.current.text.startswith("- "):
            value = self.parse_sequence(self.current.indent)
        else:
            value = self.parse_mapping(self.current.indent)
        if self.pos < len(self.lines):
            raise YamlError(
                f"{self.where()}: unerwartete Einrueckung (Ebene {self.current.indent})"
            )
        return value

    def parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.pos < len(self.lines) and self.current.indent == indent:
            line = self.current
            if line.text.startswith("- "):
                break
            key, rest = _split_key(line.text, self.where(line))
            if not key:
                raise YamlError(f"{self.where(line)}: 'schluessel: wert' erwartet")
            if key in result:
                raise YamlError(f"{self.where(line)}: Schluessel {key!r} ist doppelt")
            if rest:
                result[key] = _scalar(rest, self.where(line))
                self.pos += 1
                continue
            self.pos += 1
            if self.pos < len(self.lines) and self.current.indent > indent:
                result[key] = self.parse_block()
            else:
                result[key] = None
        if self.pos < len(self.lines) and self.current.indent > indent:
            raise YamlError(f"{self.where()}: unerwartete Einrueckung")
        return result

    def parse_block(self) -> Any:
        if self.current.text.startswith("- "):
            return self.parse_sequence(self.current.indent)
        return self.parse_mapping(self.current.indent)

    def parse_sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while self.pos < len(self.lines) and self.current.indent == indent:
            line = self.current
            if not line.text.startswith("- "):
                raise YamlError(f"{self.where(line)}: '- ' erwartet")
            rest = line.text[2:].strip()
            if not rest:
                self.pos += 1
                if self.pos >= len(self.lines) or self.current.indent <= indent:
                    raise YamlError(f"{self.where(line)}: leerer Sequenzeintrag ohne Block")
                items.append(self.parse_block())
                continue
            key, _ = _split_key(rest, self.where(line))
            if key and KEY_RE.match(key):
                # "- schluessel: wert" -- als Mapping auf Einrueckung + 2 weiterlesen.
                line.indent = indent + 2
                line.text = rest
                items.append(self.parse_mapping(indent + 2))
                continue
            if key:
                raise YamlError(
                    f"{self.where(line)}: Schluessel {key!r} enthaelt unerlaubte Zeichen"
                )
            items.append(_scalar(rest, self.where(line)))
            self.pos += 1
        if self.pos < len(self.lines) and self.current.indent > indent:
            raise YamlError(f"{self.where()}: unerwartete Einrueckung")
        return items


def loads(text: str, source: str = "<text>") -> Any:
    """YAML-Text der unterstuetzten Teilmenge in Python-Daten uebersetzen."""
    if text.lstrip().startswith("---"):
        raise YamlError(f"{source}: Mehrfachdokumente sind nicht erlaubt")
    return _Parser(_prepare(text, source), source).parse()


def load_file(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"), str(path))
