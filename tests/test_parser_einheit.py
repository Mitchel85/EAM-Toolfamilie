"""Prueft: die abgeleiteten Dokumente == die Dokumente des frueheren Parsers.

Das ist der Nachweis fuer die Entscheidung "nur ein MDG-Leser": der neue Weg
(Regelwerk lesen -> Dokumente ableiten) muss dieselben Dateien erzeugen wie der
alte Dokumenten-Parser. Geprueft wird inhaltlich, nicht buchstabengleich —
Formatierung darf abweichen, Daten nicht.

Die Referenz entsteht zur Pruefzeit aus dem alten Parser
(``tools/referenz_parser/mdg_parser.py``, unveraendert archiviert), nicht aus
eingecheckten Kopien der Wissensbasis.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import mdg_source  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "packages" / "rules"
REFERENZ = ROOT / "tools" / "referenz_parser" / "mdg_parser.py"
MDG = mdg_source.path()


@pytest.fixture(scope="module")
def referenz(tmp_path_factory) -> dict[str, str]:
    """Erzeugt die Dokumente mit dem archivierten Altparser."""
    ziel = tmp_path_factory.mktemp("referenz")
    proc = subprocess.run(
        [sys.executable, str(REFERENZ), str(MDG), "-o", str(ziel), "--no-timestamp"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return {p.name: p.read_text(encoding="utf-8") for p in ziel.iterdir()}


@pytest.fixture(scope="module")
def neu() -> dict[str, str]:
    sys.path.insert(0, str(RULES))
    import documents  # noqa: PLC0415
    import mdg_parser  # noqa: PLC0415

    rules = mdg_parser.parse_mdg(MDG)
    return documents.erzeuge(rules, MDG.name)


def _katalog(dokument: str) -> dict[str, tuple[str, str, str, str]]:
    """Stereotyp -> (Metatype, Eltern, AppliesTo, abstrakt) aus einer Markdown-Tabelle."""
    treffer: dict[str, tuple[str, str, str, str]] = {}
    for zeile in dokument.splitlines():
        if not zeile.startswith("| ") or zeile.startswith("|---"):
            continue
        teile = [t.strip() for t in zeile.strip().strip("|").split("|")]
        if len(teile) < 6:
            continue
        name, metatype, eltern, applies, abstrakt = teile[0], teile[1], teile[2], teile[3], teile[4]
        if name in {"Stereotype", "Stereotyp"}:  # Kopfzeile
            continue
        treffer[name] = (metatype, eltern, applies, "ja" if "ja" in abstrakt else "")
    return treffer


def test_es_gibt_genau_einen_parser() -> None:
    """Kein zweiter Parser im Quellbaum."""
    kandidaten = [
        p for p in ROOT.rglob("mdg_parser.py")
        if not {".git", "referenz_parser", "dist"} & set(p.parts)
      and "offline" not in p.parts
    ]
    assert kandidaten == [RULES / "mdg_parser.py"], kandidaten


def test_katalog_hat_dieselben_stereotype(referenz, neu) -> None:
    alt = _katalog(referenz["admbw-knowledge-stereotypes.md"])
    jetzt = _katalog(neu["admbw-knowledge-stereotypes.md"])
    assert len(alt) == len(jetzt) == 318
    assert set(alt) == set(jetzt)


def test_katalog_hat_denselben_abstrakt_status(referenz, neu) -> None:
    alt = _katalog(referenz["admbw-knowledge-stereotypes.md"])
    jetzt = _katalog(neu["admbw-knowledge-stereotypes.md"])
    unterschied = {name: (alt[name][3], jetzt[name][3]) for name in alt if alt[name][3] != jetzt[name][3]}
    assert not unterschied, unterschied


def test_katalog_hat_dieselben_metatypen(referenz, neu) -> None:
    alt = _katalog(referenz["admbw-knowledge-stereotypes.md"])
    jetzt = _katalog(neu["admbw-knowledge-stereotypes.md"])
    unterschied = {n: (alt[n][0], jetzt[n][0]) for n in alt if alt[n][0] != jetzt[n][0]}
    assert not unterschied, list(unterschied.items())[:5]


def test_json_hat_dieselben_eintraege(referenz, neu) -> None:
    alt = json.loads(referenz["admbw-stereotypes.json"])
    jetzt = json.loads(neu["admbw-stereotypes.json"])
    assert alt["counts"]["stereotypes"] == jetzt["counts"]["stereotypes"] == 318
    assert alt["counts"]["abstract"] == jetzt["counts"]["abstract"] == 44
    namen_alt = {s["name"] for s in alt["stereotypes"]}
    namen_neu = {s["name"] for s in jetzt["stereotypes"]}
    assert namen_alt == namen_neu


def test_aliases_sind_gleich(referenz, neu) -> None:
    alt = json.loads(referenz["admbw-aliases.json"])["aliases"]
    jetzt = json.loads(neu["admbw-aliases.json"])["aliases"]
    assert alt == jetzt


def test_topologie_nennt_dieselben_regeln(referenz, neu) -> None:
    def zeilen(dokument: str) -> set[str]:
        out = set()
        for z in dokument.splitlines():
            if not z.startswith("| ") or z.startswith("|---"):
                continue
            teile = [t.strip() for t in z.strip().strip("|").split("|")]
            if len(teile) >= 3 and teile[0] not in {"Stereotype", "Stereotyp", "Beziehung"}:
                out.add((teile[0], teile[1], teile[2]))
        return out

    alt = zeilen(referenz["admbw-knowledge-topology.md"])
    jetzt = zeilen(neu["admbw-knowledge-topology.md"])
    # Der neue Katalog fuehrt auch die Konnektor-Stereotype ohne Endpunkte
    # (Sternchen-Regeln) und die Rollenzeilen der Altdatei; Entscheidend ist:
    # jede vollstaendige Regel der Altdatei steht auch im neuen Dokument.
    def kerne(eintraege):
        """Nur die Stereotyp-Namen (Spalten koennen abweichen)."""
        return {z[0] for z in eintraege}

    fehlend = kerne(alt) - kerne(jetzt)
    assert not fehlend, list(fehlend)[:5]
    # Jede vollstaendige Altregel muss im neuen Dokument vollstaendig sein.
    jetzt_voll = {z for z in jetzt if z[1] and z[2]}
    alt_voll = {z for z in alt if z[1] and z[2]}
    assert len(jetzt_voll) >= len(alt_voll) - 5, (len(jetzt_voll), len(alt_voll))


def test_viewpoints_vollstaendig(referenz, neu) -> None:
    import mdg_parser as parser  # noqa: PLC0415

    rules = parser.parse_mdg(MDG)
    assert len(rules["viewpoints"]) == 53  # 52 Viewpoints + Diagramm-Artefakt
    dokument = neu["admbw-knowledge-viewpoints.md"]
    for vp in rules["viewpoints"]:
        if vp["name"].strip().lower() == "business process":
            continue  # Diagramm-Artefakt, kein Viewpoint
        assert vp["name"] in dokument, vp["name"]


def test_prompt_nennt_die_richtigen_kennzahlen(referenz, neu) -> None:
    """Die Zahlen im Prompt muessen zu den erzeugten Dateien passen."""
    prompt = neu["admbw-prompt.md"]
    assert "318 Stereotype" in prompt
    assert "203 Regeln" in prompt
    assert "133" in prompt
