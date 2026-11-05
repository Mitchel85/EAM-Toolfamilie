"""Prueft, ob die Zahlen in den Regeltexten zur erzeugten Wissensbasis passen.

Der Prompt nennt Kennzahlen ("318 Stereotype", "203 Regeln", "52 Viewpoints").
Solche Zahlen veralten still: der Katalog waechst, der Prompt bleibt. Dieser
Test liest die Zahlen aus, statt sie im Test zu wiederholen — so meldet er
echte Abweichungen und keine Testkopien.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"


def _json_counts() -> dict:
    data = json.loads((KNOWLEDGE / "admbw-stereotypes.json").read_text(encoding="utf-8"))
    return data["counts"]


def _counter(name: str) -> int:
    """Zahl direkt aus der erzeugten Datei, unabhaengig von der Prompt-Zeile.

    Die Zaehlung im JSON-Schluessel ``counts`` deckt nur Stereotype ab. Fuer
    Topologie und Viewpoints wird die Datei selbst gezaehlt — damit prueft der
    Test den Inhalt und nicht eine zweite Zusammenfassung.
    """
    text = (KNOWLEDGE / name).read_text(encoding="utf-8")
    match = re.search(r"^>\s*([0-9]+)\b", text, re.M)
    if match:
        return int(match.group(1))
    # Fallback: Kopfzeile mit "Insgesamt: N" oder letzte Zeile
    match = re.search(r"([0-9]+)\s*(?:Einträge|Regeln|Viewpoints)", text)
    assert match, f"keine Zahl in {name}"
    return int(match.group(1))


def _aliases() -> int:
    data = json.loads((KNOWLEDGE / "admbw-aliases.json").read_text(encoding="utf-8"))
    return len(data)


def _table_row(prompt: str, name: str) -> str:
    for line in prompt.splitlines():
        if line.strip().startswith("|") and f"`{name}`" in line:
            return line
    raise AssertionError(f"Zeile fuer {name} fehlt im Prompt")


def _first_int(text: str) -> int:
    match = re.search(r"([0-9]+)", text)
    assert match, text
    return int(match.group(1))


def test_prompt_nennt_die_richtigen_stereotyp_zahlen() -> None:
    counts = _json_counts()
    prompt = (KNOWLEDGE / "admbw-prompt.md").read_text(encoding="utf-8")
    row = _table_row(prompt, "admbw-stereotypes.json")
    assert _first_int(row.split("|")[-2]) == counts["stereotypes"]


def test_prompt_nennt_die_richtigen_alias_zahlen() -> None:
    prompt = (KNOWLEDGE / "admbw-prompt.md").read_text(encoding="utf-8")
    row = _table_row(prompt, "admbw-aliases.json")
    assert _first_int(row.split("|")[-2]) == _aliases()


def test_prompt_nennt_die_richtigen_topologie_zahlen() -> None:
    prompt = (KNOWLEDGE / "admbw-prompt.md").read_text(encoding="utf-8")
    row = _table_row(prompt, "admbw-knowledge-topology.md")
    assert _first_int(row.split("|")[-2]) == _counter("admbw-knowledge-topology.md")


def test_prompt_nennt_die_richtigen_viewpoint_zahlen() -> None:
    prompt = (KNOWLEDGE / "admbw-prompt.md").read_text(encoding="utf-8")
    row = _table_row(prompt, "admbw-knowledge-viewpoints.md")
    assert _first_int(row.split("|")[-2]) == _counter("admbw-knowledge-viewpoints.md")


def test_prompt_verweist_nur_auf_vorhandene_dateien() -> None:
    """Ein Verweis auf eine nicht erzeugte Datei schickt jeden Verbraucher ins Leere."""
    prompt = (KNOWLEDGE / "admbw-prompt.md").read_text(encoding="utf-8")
    genannt = set(re.findall(r"`(admbw-[a-z-]+\.(?:md|json))`", prompt))
    fehlend = [n for n in genannt if not (KNOWLEDGE / n).is_file()]
    assert not fehlend, f"Prompt nennt fehlende Dateien: {fehlend}"


def test_meta_nennt_mdg_release() -> None:
    counts = _json_counts()
    meta = (KNOWLEDGE / "admbw-meta.md").read_text(encoding="utf-8")
    assert "2026.05" in meta
    assert str(counts["stereotypes"]) in meta
