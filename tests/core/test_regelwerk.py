"""Das Regelwerk-Artefakt: eine Quelle fuer alle Pipelines.

Geprueft wird nicht die Fachlichkeit, sondern die Geschlossenheit: deckt das
Artefakt die Quellen ab, stimmen die Kennzahlen, laesst es sich reproduzieren.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "core"))

import regelwerk  # noqa: E402

ARTEFAKT = ROOT / "knowledge" / "regelwerk.json"


@pytest.fixture(scope="module")
def daten() -> dict:
    return regelwerk.lade()


def test_artefakt_liegt_vor() -> None:
    assert ARTEFAKT.is_file(), "knowledge/regelwerk.json fehlt -- scripts/build_regelwerk.py laufen lassen"


def test_kennzahlen_passen_zu_den_eintraegen(daten: dict) -> None:
    s = daten["summary"]
    assert s["viewpoints"] == len(daten["viewpoints"])
    assert s["mit_mdg"] == sum(1 for v in daten["viewpoints"].values() if v["mdg"]["elemente"])
    assert s["mit_model_wizard"] == sum(1 for v in daten["viewpoints"].values() if v["model_wizard"])
    assert s["konflikte"] == len(daten["konflikte"])


def test_jeder_viewpoint_hat_alle_schichten(daten: dict) -> None:
    for code, eintrag in daten["viewpoints"].items():
        assert eintrag["titel"], code
        assert set(eintrag) >= {"titel", "gruppe", "mdg", "leitfaeden", "model_wizard", "luecken"}, code
        assert set(eintrag["leitfaeden"]) == {"ffmlv", "pbn"}, code
        for key in ("ffmlv", "pbn"):
            assert isinstance(eintrag["leitfaeden"][key]["konventionen"], int), (code, key)


def test_quellen_hashes_stimmen(daten: dict) -> None:
    import hashlib

    mdg = daten["quellen"]["mdg"]
    pfad = ROOT / mdg["datei"]
    assert hashlib.sha256(pfad.read_bytes()).hexdigest() == mdg["sha256"], "MDG-Hash passt nicht"
    for key, wert in daten["quellen"]["leitfaeden"].items():
        pfad = ROOT / wert["datei"]
        assert hashlib.sha256(pfad.read_bytes()).hexdigest() == wert["sha256"], key


def test_konventionen_vollstaendig_uebernommen(daten: dict) -> None:
    for key in ("ffmlv", "pbn"):
        datei = ROOT / daten["quellen"]["leitfaeden"][key]["datei"]
        roh = json.loads(datei.read_text(encoding="utf-8"))
        im_artefakt = sum(
            v["leitfaeden"][key]["konventionen"] for v in daten["viewpoints"].values()
        )
        assert im_artefakt == len(roh), (
            f"{key}: {im_artefakt} im Artefakt, {len(roh)} in der Quelle"
        )


def test_artefakt_ist_reproduzierbar() -> None:
    if not any((ROOT / "knowledge" / "modelwizard").glob("*.xml")):
        pytest.skip("Model-Wizard-Vorlagen fehlen (nicht versioniert, 7,3 MB)")
    ergebnis = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_regelwerk.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr


def test_keine_stereotype_ausserhalb_der_mdg(daten: dict) -> None:
    fremd = [k for k in daten["konflikte"] if k["typ"] == "stereotyp_nicht_in_mdg"]
    assert fremd == [], fremd


def test_nur_wizard_sichten_sind_begruendet(daten: dict) -> None:
    """Viewpoints ohne Leitfaden sind erlaubt -- aber sie muessen im Wizard stehen."""
    for code, eintrag in daten["viewpoints"].items():
        if not eintrag["leitfaeden"]["ffmlv"]["konventionen"] and not eintrag["leitfaeden"]["pbn"]["konventionen"]:
            assert eintrag["model_wizard"] is not None, f"{code} haengt in der Luft"


def test_pruefung_ist_im_artefakt(daten: dict) -> None:
    """Pakete, Sichten und Pflichtstereotype gehoeren zum Artefakt."""
    p = daten["pruefung"]
    assert len(p["packages"]) == 43
    assert len(p["diagrams"]) == 41
    assert len(p["pflicht"]) == 20
    assert daten["quellen"]["pruefung"]["pakete"] == 43


def test_leitfaden_liest_aus_dem_artefakt(daten: dict) -> None:
    """leitfaden.py haelt keine eigene Kopie der Tabellen mehr."""
    import leitfaden  # noqa: PLC0415

    assert len(leitfaden.PACKAGES) == len(daten["pruefung"]["packages"])
    assert len(leitfaden.DIAGRAMS) == len(daten["pruefung"]["diagrams"])
    assert len(leitfaden.PFLICHT_STEREOTYPE) == len(daten["pruefung"]["pflicht"])
    # Stichprobe: die erste Regel muss Zeichen fuer Zeichen dieselbe sein.
    artefakt = daten["pruefung"]["packages"][0]
    gelesen = leitfaden.PACKAGES[0]
    assert (gelesen.code, gelesen.path, gelesen.viewpoint, gelesen.family) == (
        artefakt["code"], artefakt["path"], artefakt["viewpoint"], artefakt["family"],
    )


def test_konventionen_dateien_bleiben_unabhaengig(daten: dict) -> None:
    """Die Konventionstexte sind kein Teil des Artefakts, werden aber verwiesen."""
    for key in ("ffmlv", "pbn"):
        assert daten["quellen"]["leitfaeden"][key]["eintraege"] > 0


def test_html_suite_daten_entsprechen_dem_regelwerk() -> None:
    """Die HTML-Suite traegt keinen eigenen, gealterten Regelsatz."""
    ergebnis = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_html_data.py"), "--pruefen"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
