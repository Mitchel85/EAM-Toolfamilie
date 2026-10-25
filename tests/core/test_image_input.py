"""Tests fuer den Bild-Eingang (multimodale Prosa) -- ohne Netz.

Das Backend wird durch einen Fake ersetzt, der nur die Attribute eines
OpenAI-kompatiblen Endpunkts traegt; der Transport ``_post_vision`` wird
abgefangen. So laesst sich pruefen, dass die base64-Daten tatsaechlich als
``data:image/...;base64,...`` in der Chat-Completions stehen -- und dass
jeder Fehler laut ist (kein stilles Leer-Ergebnis).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest

import eam_ai
import extract as ex
import image_input

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 8
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 12


@dataclass
class FakeBackend:
    model: str = "fake-vision"
    base_url: str = "https://example.invalid/v1"
    api_key: str = ""
    timeout: float = 5.0
    captured: list[dict[str, Any]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"fake:{self.model}"

    def complete(self, prompt: str) -> str:  # pragma: no cover - hier nie benutzt
        raise AssertionError("describe_image darf nur den Bildpfad nutzen")


def _antwort(text: str | list[dict[str, str]]) -> Mapping[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _bild(tmp_path: Path, name: str = "architektur.png", data: bytes = PNG) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_base64_und_data_url_stehen_im_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeBackend()
    pfad = _bild(tmp_path)

    def fake_post(_backend, payload, *, name, base_url, timeout):
        backend.captured.append(dict(payload))
        assert name == "fake:fake-vision"
        assert base_url == "https://example.invalid/v1"
        assert timeout == 5.0
        return _antwort("Ein Dienst A nutzt den Dienst B.")

    monkeypatch.setattr(image_input, "_post_vision", fake_post)
    text = image_input.describe_image(pfad, backend)

    assert text == "Ein Dienst A nutzt den Dienst B."
    payload = backend.captured[0]
    assert payload["model"] == "fake-vision"
    assert payload["temperature"] == 0
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": image_input.BILD_PROMPT}
    erwartet = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
    assert content[1] == {"type": "image_url", "image_url": {"url": erwartet}}
    assert "data:image/png;base64," in content[1]["image_url"]["url"]


def test_jpeg_bekommt_jpeg_mime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(_backend, payload, **_kwargs):
        captured.update(payload)
        return _antwort("Ein Bild.")

    monkeypatch.setattr(image_input, "_post_vision", fake_post)
    image_input.describe_image(_bild(tmp_path, "plan.jpg", JPG), FakeBackend(), prompt="Kurz.")
    content = captured["messages"][0]["content"]
    assert content[0]["text"] == "Kurz."
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_antwort_aus_textteilen_wird_zusammengefuegt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(_backend, _payload, **_kwargs):
        return _antwort([{"type": "text", "text": "Teil eins. "}, {"type": "text", "text": "Teil zwei."}])

    monkeypatch.setattr(image_input, "_post_vision", fake_post)
    assert image_input.describe_image(_bild(tmp_path), FakeBackend()) == "Teil eins. Teil zwei."


def test_backend_ohne_multimodalitaet_ist_laut(tmp_path: Path) -> None:
    with pytest.raises(image_input.ImageInputError, match="multimodal"):
        image_input.describe_image(_bild(tmp_path), ex.StaticBackend(['{"elements": []}']))


def test_ohne_backend_ist_laut(tmp_path: Path) -> None:
    with pytest.raises(image_input.ImageInputError, match="kein Backend"):
        image_input.describe_image(_bild(tmp_path), None)


def test_ollama_ist_laut_statt_404(tmp_path: Path) -> None:
    with pytest.raises(image_input.ImageInputError, match="Ollama"):
        image_input.describe_image(_bild(tmp_path), ex.OllamaBackend(model="llava"))


def test_leere_antwort_ist_laut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_input, "_post_vision", lambda *_a, **_k: _antwort("   "))
    with pytest.raises(image_input.ImageInputError, match="leer"):
        image_input.describe_image(_bild(tmp_path), FakeBackend())


def test_fehlende_antwort_ist_laut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_input, "_post_vision", lambda *_a, **_k: {"choices": []})
    with pytest.raises(image_input.ImageInputError, match="choices"):
        image_input.describe_image(_bild(tmp_path), FakeBackend())


def test_datei_und_formatfehler_sind_laut(tmp_path: Path) -> None:
    with pytest.raises(image_input.ImageInputError, match="existiert nicht"):
        image_input.describe_image(tmp_path / "fehlt.png", FakeBackend())

    falsch = _bild(tmp_path, "bild.gif", b"GIF89a")
    with pytest.raises(image_input.ImageInputError, match="Endung"):
        image_input.describe_image(falsch, FakeBackend())

    leer = _bild(tmp_path, "leer.png", b"")
    with pytest.raises(image_input.ImageInputError, match="leer"):
        image_input.describe_image(leer, FakeBackend())

    umbenannt = _bild(tmp_path, "umbenannt.png", JPG)
    with pytest.raises(image_input.ImageInputError, match="passt nicht"):
        image_input.describe_image(umbenannt, FakeBackend())

    kaputt = _bild(tmp_path, "kaputt.png", b"kein bild")
    with pytest.raises(image_input.ImageInputError, match="Signatur"):
        image_input.describe_image(kaputt, FakeBackend())


def test_zu_grosses_bild_ist_laut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_input, "MAX_BYTES", 4)
    with pytest.raises(image_input.ImageInputError, match="ueberschreiten"):
        image_input.describe_image(_bild(tmp_path), FakeBackend())


def test_payload_prueft_eingaben() -> None:
    with pytest.raises(image_input.ImageInputError, match="kein Bild"):
        image_input.build_vision_payload("m", "p", [])
    with pytest.raises(image_input.ImageInputError, match="MIME"):
        image_input.build_vision_payload("m", "p", [("text/plain", "abc")])
    with pytest.raises(image_input.ImageInputError, match="base64"):
        image_input.build_vision_payload("m", "p", [("image/png", "  ")])
    with pytest.raises(image_input.ImageInputError, match="Modellname"):
        image_input.build_vision_payload("", "p", [("image/png", "abc")])


def test_cli_bild_wird_der_prosa_vorangestellt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--bild: Beschreibung mit Quellenmarke vor dem Text, gleicher Extraktionspfad."""
    mdg = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures" / "admbw_auszug.xml"
    bild = _bild(tmp_path)
    text = tmp_path / "prosa.txt"
    text.write_text("Der Prozess P ist ein Ablauf.", encoding="utf-8")

    monkeypatch.setattr(
        image_input,
        "describe_image",
        lambda pfad, backend: "Die Faehigkeit K wird durch den Dienst D erbracht.",
    )
    antwort = {
        "elements": [
            {
                "name": "Faehigkeit K",
                "stereotype": "Capability",
                "notes": "aus dem Bild",
                "source_ref": "D1-S1",
                "confidence": 0.9,
            }
        ],
        "connectors": [],
    }
    backend = ex.StaticBackend([json.dumps(antwort)])

    report = eam_ai.build(
        mdg=mdg,
        text=text,
        images=[bild],
        out=tmp_path / "modell.qea",
        backend=backend,
        findings_path=tmp_path / "findings.json",
    )

    assert report.exported is True
    assert report.segments == 2, "Bildblock und Text sind zwei Absaetze"
    prompt = backend.prompts[0]
    assert "[Bildquelle: architektur.png]" in prompt
    assert prompt.index("[Bildquelle: architektur.png]") < prompt.index("Der Prozess P")
    quellen = json.loads((tmp_path / "quellen.json").read_text(encoding="utf-8"))
    assert quellen["D1-S1"].startswith("[Bildquelle: architektur.png]")
    # Nur belegte Absaetze stehen in quellen.json: das Element belegt D1-S1.
    assert set(quellen) == {"D1-S1"}
    assert "D1-S2" in backend.prompts[0], "der Text ist der zweite Absatz"


def test_cli_nimmt_mehrere_bilder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mdg = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures" / "admbw_auszug.xml"
    erstes = _bild(tmp_path, "eins.png")
    zweites = _bild(tmp_path, "zwei.jpg", JPG)
    gesehen: list[str] = []

    def fake_describe(pfad, _backend):
        gesehen.append(Path(pfad).name)
        return f"Beschreibung zu {Path(pfad).name}."

    monkeypatch.setattr(image_input, "describe_image", fake_describe)
    antwort = {
        "elements": [
            {
                "name": "Capability",
                "stereotype": "Capability",
                "notes": "aus Bildern",
                "source_ref": "D1-S1",
                "confidence": 0.9,
            }
        ],
        "connectors": [],
    }
    antwort_datei = tmp_path / "antwort.json"
    antwort_datei.write_text(json.dumps(antwort), encoding="utf-8")

    code = eam_ai.main(
        [
            "build",
            "--mdg",
            str(mdg),
            "--bild",
            str(erstes),
            "--bild",
            str(zweites),
            "--out",
            str(tmp_path / "modell.qea"),
            "--backend",
            "datei",
            "--antwort",
            str(antwort_datei),
            "--quiet",
        ]
    )
    assert code == 0
    assert gesehen == ["eins.png", "zwei.jpg"]
    quellen = json.loads((tmp_path / "quellen.json").read_text(encoding="utf-8"))
    assert "eins.png" in quellen["D1-S1"]
    assert "zwei.jpg" not in quellen["D1-S1"], "beide Bilder sind eigene Absaetze"


def test_nur_bild_ist_eine_quelle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mdg = Path(__file__).resolve().parents[2] / "packages" / "core" / "fixtures" / "admbw_auszug.xml"
    monkeypatch.setattr(
        image_input, "describe_image", lambda pfad, backend: "Der Dienst D ist ein Dienst."
    )
    antwort = {
        "elements": [
            {
                "name": "Dienst D",
                "stereotype": "ServiceSpecification",
                "notes": "aus dem Bild",
                "source_ref": "D1-S1",
                "confidence": 0.8,
            }
        ],
        "connectors": [],
    }
    report = eam_ai.build(
        mdg=mdg,
        images=[_bild(tmp_path)],
        out=tmp_path / "modell.qea",
        backend=ex.StaticBackend([json.dumps(antwort)]),
        findings_path=tmp_path / "findings.json",
    )
    assert report.exported is True
    assert report.segments == 1
    assert report.elements == 1
