"""Abgleich: abgeleitete Dokumente gegen die Erwartungen der Verbraucher.

Die drei ADMBw-Werkzeuge (Batch, Extractor, Script-Maker) lesen die
Wissensbasis als Text. Dieser Abgleich prueft jede Datei einzeln — fehlt eine
Struktur, steht hier welche, nicht nur "verify.py ist rot".
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import mdg_source  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "packages" / "rules"
MDG = mdg_source.path()


@pytest.fixture(scope="module")
def dok() -> dict[str, str]:
    sys.path.insert(0, str(RULES))
    import documents  # noqa: PLC0415
    import mdg_parser  # noqa: PLC0415

    return documents.erzeuge(mdg_parser.parse_mdg(MDG), MDG.name)


def _rows(text: str) -> list[list[str]]:
    """Tabellenzeilen einer Markdown-Datei (ohne Kopf und Trennzeilen)."""
    out = []
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] in {"Stereotyp", "Stereotype", "Beziehung", "Property", "Tag"}:
            continue
        out.append(cells)
    return out


def test_katalog_hat_318_datenzeilen(dok) -> None:
    assert len(_rows(dok["admbw-knowledge-stereotypes.md"])) == 318


def test_topologie_hat_203_zeilen_und_70_rollenzeilen(dok) -> None:
    # Nur die Regeltabelle zaehlen; "Abstrakte Endpunkte" ist ein eigener Abschnitt.
    text = dok["admbw-knowledge-topology.md"].split("## Abstrakte Endpunkte")[0]
    rows = _rows(text)
    assert len(rows) == 203, len(rows)
    rollen = [r for r in rows if not r[1] and not r[2]]
    assert len(rollen) == 70, len(rollen)


def test_topologie_lesart_bleibt(dok) -> None:
    text = dok["admbw-knowledge-topology.md"]
    assert "client" in text and "supplier" in text and "end[0]" in text
    assert "informationSource" in text


def test_viewpoints_mit_ueberschriften(dok) -> None:
    text = dok["admbw-knowledge-viewpoints.md"]
    assert len(re.findall(r"^## ", text, re.M)) == 52


def test_tagtypes_hat_27_typen(dok) -> None:
    assert len(_rows(dok["admbw-knowledge-tagtypes.md"])) == 27


def test_tags_haben_das_altformat(dok) -> None:
    text = dok["admbw-knowledge-stereotype-tags.md"]
    rows = _rows(text)
    assert "| Stereotype | Tag | Typ | Erlaubte Werte | Default | Beschreibung |" in text
    assert len(rows) == 225, len(rows)


def test_json_hat_alte_felder(dok) -> None:
    data = json.loads(dok["admbw-stereotypes.json"])
    assert set(data["counts"]) >= {"stereotypes", "abstract"}
    for eintrag in data["stereotypes"]:
        for feld in ("name", "metatype", "abstract", "parents", "appliesTo", "concreteDescendants"):
            assert feld in eintrag, (eintrag["name"], feld)
    per_name = {e["name"]: e for e in data["stereotypes"]}
    assert "CapabilityConfiguration" in per_name["ResourcePerformer"]["concreteDescendants"]
    assert "FunctionalRequirement" in per_name["BWRequirement"]["concreteDescendants"]


def test_prompt_hat_altformat(dok) -> None:
    prompt = dok["admbw-prompt.md"]
    assert "Du bist Modellierungsassistent" in prompt
    assert "## Eiserne Regeln" in prompt
    assert "203 Regeln" in prompt
    assert "318 Stereotype" in prompt


def test_verbraucher_pruefungen_sind_gruen(tmp_path) -> None:
    """Batch und Extractor lesen die eingecheckte Wissensbasis."""
    for app in ("admbw-batch", "admbw-extractor"):
        result = subprocess.run(
            [sys.executable, "checks/verify.py"],
            cwd=ROOT / "apps" / app,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout[-3000:]
        # Nur echte Befundzeilen zaehlen: "PASS ... PASS/FAIL" enthaelt das Wort
        # FAIL als Spaltennamen, nicht als Befund.
        befund = [z for z in result.stdout.splitlines() if z.startswith("FAIL")]
        assert not befund, befund
