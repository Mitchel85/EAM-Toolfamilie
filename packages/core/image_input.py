"""image_input.py -- Bilder als multimodale Prosa-Quelle.

Ein Bild wird base64-kodiert als ``image_url`` an eine OpenAI-kompatible
Chat-Completions geschickt (Multimodalitaet). Zurueck kommt Prosa, die
anschliessend durch denselben Extraktionspfad geht wie Text
(``extract.answer_to_ir``) -- es gibt keinen zweiten Extraktionsweg.

Oeffentliche API::

    from image_input import describe_image

    text = describe_image("architektur.png", backend)

``backend`` ist ein vorbereitetes Backend aus ``extract.make_backend``
(``openai``/``openai-kompatibel``). Nicht-multimodale Backends (``datei``,
``ollama``) brechen laut ab: ein leeres Ergebnis waere ein stiller Verlust.

Bildformate: PNG und JPEG. Die Endung muss zur Signatur passen; eine
umbenannte Datei ist ein Eingabefehler, kein Ratefall.

Kein ``time``/``datetime``; nur Standardbibliothek (base64, pathlib, urllib
ueber ``extract._post_json``). Der API-Schluessel steht im Backend und wird
weder protokolliert noch in Fehlermeldungen aufgenommen.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any, Mapping, Sequence

import extract

#: Obergrenze fuer eine Bilddatei. Groessere Bilder werden nicht still
#: verkleinert, sondern abgelehnt (der Aufrufer soll bewusst entscheiden).
MAX_BYTES = 20 * 1024 * 1024

#: Auftrag an das Modell. Bewusst nur Beschreibung, keine Extraktion:
#: die Struktur entsteht danach im gemeinsamen Extraktionspfad.
BILD_PROMPT = (
    "Beschreibe dieses Bild als zusammenhaengende deutsche Architektur-Prosa "
    "fuer die spaetere Extraktion von Elementen und Beziehungen. Nenne nur, "
    "was im Bild tatsaechlich sichtbar ist: Bezeichner, Typen oder Stereotype, "
    "Beschriftungen, Verbindungen und deren Richtung. Erfinde nichts und "
    "ergaenze kein Vorwissen. Antworte als Fliesstext ohne Aufzaehlung."
)

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

_SUFFIX_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class ImageInputError(ValueError):
    """Bild unlesbar, Format falsch oder Backend nicht multimodal. Immer laut."""


# --------------------------------------------------------------------------
# Bild lesen und kodieren
# --------------------------------------------------------------------------


def _sniff(data: bytes) -> str:
    for signature, mime in _SIGNATURES:
        if data.startswith(signature):
            return mime
    return ""


def read_image(path: str | Path) -> tuple[bytes, str]:
    """Bild lesen und ``(bytes, mime)`` liefern; jeder Zweifel bricht ab."""
    source = Path(path)
    if not source.exists():
        raise ImageInputError(f"Bild {source}: Datei existiert nicht")
    if not source.is_file():
        raise ImageInputError(f"Bild {source}: keine regulaere Datei")
    suffix = source.suffix.lower()
    if suffix not in _SUFFIX_MIME:
        raise ImageInputError(
            f"Bild {source}: Endung {suffix or '(keine)'} wird nicht unterstuetzt "
            f"(erlaubt: {', '.join(sorted(_SUFFIX_MIME))})"
        )
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise ImageInputError(f"Bild {source}: nicht lesbar ({exc})") from exc
    if not data:
        raise ImageInputError(f"Bild {source}: Datei ist leer")
    if len(data) > MAX_BYTES:
        raise ImageInputError(
            f"Bild {source}: {len(data)} Bytes ueberschreiten die Grenze "
            f"von {MAX_BYTES} Bytes"
        )
    mime = _sniff(data)
    if not mime:
        raise ImageInputError(
            f"Bild {source}: keine PNG-/JPEG-Signatur -- Inhalt passt nicht zum Format"
        )
    if mime != _SUFFIX_MIME[suffix]:
        raise ImageInputError(
            f"Bild {source}: Endung {suffix} passt nicht zum Inhalt ({mime})"
        )
    return data, mime


def encode_image(data: bytes, mime: str) -> str:
    """Base64 ohne Zeilenumbrueche (gueltig fuer ``data:``-URLs)."""
    if not data:
        raise ImageInputError("Bilddaten sind leer -- kein data:-URL aus nichts")
    if not mime:
        raise ImageInputError("MIME-Typ fehlt -- kein data:-URL aus nichts")
    try:
        return base64.b64encode(data).decode("ascii")
    except (binascii.Error, UnicodeEncodeError) as exc:  # pragma: no cover - defensiv
        raise ImageInputError(f"Bilddaten nicht base64-kodierbar: {exc}") from exc


def data_url(data: bytes, mime: str) -> str:
    """Vollstaendige ``data:image/...;base64,...``-Quelle."""
    return f"data:{mime};base64,{encode_image(data, mime)}"


def build_vision_payload(
    model: str, prompt: str, images: Sequence[tuple[str, str]]
) -> dict[str, Any]:
    """Chat-Completions-Nutzlast mit Text- und Bildteil.

    ``images`` sind Paare ``(mime, base64)``. Mindestens ein Bild ist Pflicht:
    ein Aufruf ohne Bild waere eine Textabfrage und gehoert nicht hierher.
    """
    if not isinstance(model, str) or not model.strip():
        raise ImageInputError("build_vision_payload: Modellname fehlt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageInputError("build_vision_payload: Auftrag (prompt) fehlt")
    if not images:
        raise ImageInputError("build_vision_payload: kein Bild uebergeben")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt.strip()}]
    for index, pair in enumerate(images):
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ImageInputError(
                f"build_vision_payload: Bild {index} ist kein (mime, base64)-Paar"
            )
        mime, encoded = pair
        if not isinstance(mime, str) or not mime.startswith("image/"):
            raise ImageInputError(
                f"build_vision_payload: Bild {index} hat keinen Bild-MIME-Typ ({mime!r})"
            )
        if not isinstance(encoded, str) or not encoded.strip():
            raise ImageInputError(f"build_vision_payload: Bild {index} ohne base64-Inhalt")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
    return {
        "model": model.strip(),
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "stream": False,
    }


# --------------------------------------------------------------------------
# Backend
# --------------------------------------------------------------------------


def _backend_name(backend: Any) -> str:
    name = getattr(backend, "name", "")
    return name if isinstance(name, str) and name.strip() else type(backend).__name__


def _endpoint(backend: Any) -> tuple[str, str, str, float]:
    """``(name, model, basis-url, timeout)`` eines multimodalen Backends."""
    if backend is None:
        raise ImageInputError(
            "describe_image: kein Backend uebergeben -- ohne Modell keine Bildbeschreibung"
        )
    if isinstance(backend, extract.OllamaBackend):
        raise ImageInputError(
            f"Backend {_backend_name(backend)}: Ollama unterstuetzt diesen Bildpfad nicht; "
            "nutze ein OpenAI-kompatibles multimodales Backend (--backend openai)"
        )
    model = getattr(backend, "model", "")
    base_url = getattr(backend, "base_url", "")
    if not isinstance(model, str) or not model.strip():
        raise ImageInputError(
            f"Backend {_backend_name(backend)}: kein Modellname -- kein multimodales "
            "Backend; Bildbeschreibung nicht moeglich"
        )
    if not isinstance(base_url, str) or not base_url.strip():
        raise ImageInputError(
            f"Backend {_backend_name(backend)}: kein multimodaler Chat-Endpunkt "
            "(base_url fehlt) -- Bildbeschreibung nicht moeglich"
        )
    timeout = getattr(backend, "timeout", 120.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        timeout = 120.0
    return _backend_name(backend), model.strip(), base_url.strip(), float(timeout)


def _post_vision(
    backend: Any, payload: Mapping[str, Any], *, name: str, base_url: str, timeout: float
) -> Mapping[str, Any]:
    """Ein POST an ``/chat/completions``; fuer Tests ersetzbar."""
    url = base_url.rstrip("/") + "/chat/completions"
    api_key = getattr(backend, "api_key", "")
    headers = {"Authorization": f"Bearer {api_key}"} if isinstance(api_key, str) and api_key else {}
    try:
        return extract._post_json(url, payload, headers, timeout, name)
    except extract.ExtractionError as exc:
        raise ImageInputError(str(exc)) from exc


def _content_text(parsed: Mapping[str, Any], name: str) -> str:
    choices = parsed.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise ImageInputError(f"{name}: Antwort enthaelt keine choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ImageInputError(f"{name}: choices[0] ist kein Objekt")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ImageInputError(f"{name}: choices[0].message fehlt")
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, Sequence):
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        text = "".join(parts).strip()
    else:
        text = ""
    if not text:
        raise ImageInputError(
            f"{name}: Bildbeschreibung ist leer -- kein stilles Leer-Ergebnis"
        )
    return text


def describe_image(
    path: str | Path,
    backend: Any,
    *,
    prompt: str = BILD_PROMPT,
) -> str:
    """Bild an ein multimodales Backend geben und die Beschreibung liefern."""
    name, model, base_url, timeout = _endpoint(backend)
    data, mime = read_image(path)
    payload = build_vision_payload(model, prompt, [(mime, encode_image(data, mime))])
    parsed = _post_vision(backend, payload, name=name, base_url=base_url, timeout=timeout)
    return _content_text(parsed, name)
