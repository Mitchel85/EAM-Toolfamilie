"""Rauchtest fuer das Open-WebUI-Werkzeug ``eam_qea_analyzer_openwebui.py``.

Der Test braucht **keine** Open-WebUI-Installation und kein Netz: er baut sich
aus dem IR-Writer des Monorepos ein synthetisches Modell mit 55 Elementen,
laedt die ausgelieferte Werkzeugdatei als Python-Modul und ruft die beiden
Funktionen auf, die ein LLM in Open WebUI zuerst benutzt:

* ``Tools.analyze_qea_statistics()``
* ``Tools.find_elements_in_qea()``

Aufruf::

    python -m pytest tests/apps/test_openwebui_werkzeug.py -v

Hinweis zur Zaehlung: Der Writer legt je Unterpaket eine Spiegelzeile in
``t_object`` an (EA-Konvention). Das Modell hat deshalb 55 fachliche Elemente,
aber 58 Zeilen in ``t_object`` (55 + 3 Paketspiegel). Beide Zahlen werden
unten geprueft — die Stereotypensumme ist die Zahl der fachlichen Elemente.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QUELLE = ROOT / "apps" / "mcp" / "eam_qea_tool.py"
AUSLIEFERUNG = ROOT / "dist" / "eam_qea_analyzer_openwebui.py"

sys.path.insert(0, str(ROOT / "packages" / "core"))

import qea_writer  # noqa: E402  (Pfad wird oben gesetzt)

FAEHIGKEITEN = "Rauchtest55/01 Faehigkeiten"
SYSTEME = "Rauchtest55/02 Systeme"
ABLAEUFE = "Rauchtest55/03 Ablaeufe"

ERWARTETE_TYPEN = {"Class": 35, "Activity": 10, "Requirement": 10, "Package": 3}
ERWARTETE_STEREOTYPE = {
    "Capability": 22,
    "System": 13,
    "Requirement": 10,
    "OperationalActivity": 10,
}


# ── Modell ──────────────────────────────────────────────────────────────


def _ir_mit_55_elementen() -> dict:
    """Synthetisches Modell: 55 fachliche Elemente in vier Paketen."""
    elemente: list[dict] = []
    for nummer in range(1, 23):
        elemente.append(
            {
                "package": FAEHIGKEITEN,
                "name": f"Faehigkeit {nummer:02d}",
                "stereotype": "Capability",
                "ea_type": "Class",
                "notes": f"Synthetische Faehigkeit {nummer:02d}.",
                "tags": {"Herkunft": "Rauchtest", "Reifegrad": str(nummer % 5 + 1)},
            }
        )
    for nummer in range(1, 14):
        elemente.append(
            {
                "package": SYSTEME,
                "name": f"System {nummer:02d}",
                "stereotype": "System",
                "ea_type": "Class",
                "notes": f"Synthetisches System {nummer:02d}.",
                "tags": {"Herkunft": "Rauchtest"},
            }
        )
    for nummer in range(1, 11):
        elemente.append(
            {
                "package": ABLAEUFE,
                "name": f"Ablauf {nummer:02d}",
                "stereotype": "OperationalActivity",
                "ea_type": "Activity",
                "notes": f"Synthetischer Ablauf {nummer:02d}.",
            }
        )
    for nummer in range(1, 11):
        elemente.append(
            {
                "package": SYSTEME,
                "name": f"Anforderung {nummer:02d}",
                "stereotype": "Requirement",
                "ea_type": "Requirement",
                "notes": f"Synthetische Anforderung {nummer:02d}.",
            }
        )
    return {
        "ir_version": 1,
        "technology": {
            "profile": "Rauchtestprofil",
            "name": "Rauchtest 55",
            "version": "1.0",
        },
        "meta": {
            "zweck": "Synthetisches 55-Elemente-Modell fuer den Rauchtest des "
            "Open-WebUI-Werkzeugs. Keine echten Modelle, keine Personendaten."
        },
        "packages": [
            {"path": paket, "notes": f"Paket {paket}."}
            for paket in ("Rauchtest55", FAEHIGKEITEN, SYSTEME, ABLAEUFE)
        ],
        "elements": elemente,
        "connectors": [
            {
                "source": f"{SYSTEME}::System 01",
                "target": f"{FAEHIGKEITEN}::Faehigkeit 01",
                "stereotype": "Realization",
                "ea_type": "Realization",
            },
            {
                "source": f"{ABLAEUFE}::Ablauf 01",
                "target": f"{SYSTEME}::System 01",
                "stereotype": "Provides",
                "ea_type": "Dependency",
            },
            {
                "source": f"{SYSTEME}::Anforderung 01",
                "target": f"{SYSTEME}::System 01",
                "stereotype": "Satisfy",
                "ea_type": "Dependency",
            },
        ],
    }


@pytest.fixture(scope="module")
def modell(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Schreibt das 55-Elemente-Modell als .qea und liefert den Pfad."""
    ordner = tmp_path_factory.mktemp("rauchtest55")
    ziel = ordner / "Rauchtest55.qea"
    qea_writer.write_qea(_ir_mit_55_elementen(), ziel)
    return ziel


# ── Werkzeug laden ──────────────────────────────────────────────────────


def _lade_werkzeug(pfad: Path):
    """Laedt die Werkzeugdatei als eigenstaendiges Modul (wie Open WebUI es tut)."""
    name = "openwebui_werkzeug_" + hashlib.sha256(str(pfad).encode()).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(name, pfad)
    assert spec and spec.loader, f"{pfad} ist nicht ladbar"
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _werkzeug(pfad: Path, suchordner: Path):
    modul = _lade_werkzeug(pfad)
    werkzeug = modul.Tools()
    # Statt /app/backend/data (Open-WebUI-Container) den Testordner durchsuchen.
    werkzeug.valves.qea_search_dirs = str(suchordner)
    return werkzeug


def _werkzeugdatei() -> Path:
    """Die Auslieferung, wenn `dist/` eingesammelt ist — sonst die Quelle."""
    return AUSLIEFERUNG if AUSLIEFERUNG.is_file() else QUELLE


def _statistik(werkzeug, **kwargs) -> dict:
    return json.loads(asyncio.run(werkzeug.analyze_qea_statistics(**kwargs)))


def _finde(werkzeug, **kwargs) -> list[dict]:
    ergebnis = json.loads(asyncio.run(werkzeug.find_elements_in_qea(**kwargs)))
    assert isinstance(ergebnis, list), f"Fehlerantwort statt Trefferliste: {ergebnis}"
    return ergebnis


# ── 1. Modell und Auslieferung ──────────────────────────────────────────


def test_modell_hat_55_fachliche_elemente(modell: Path) -> None:
    verbindung = sqlite3.connect(modell)
    try:
        gesamt = verbindung.execute("SELECT COUNT(*) FROM t_object").fetchone()[0]
        fachlich = verbindung.execute(
            "SELECT COUNT(*) FROM t_object WHERE Object_Type <> 'Package'"
        ).fetchone()[0]
        pakete = verbindung.execute("SELECT COUNT(*) FROM t_package").fetchone()[0]
    finally:
        verbindung.close()
    assert fachlich == 55
    assert gesamt == 58, "55 Elemente + 3 Paketspiegel"
    assert pakete == 4


def test_ausgelieferte_fassung_ist_die_quelle() -> None:
    if not AUSLIEFERUNG.is_file():
        pytest.skip("dist/ ist nicht eingesammelt (scripts/collect_releases.py)")
    assert hashlib.sha256(AUSLIEFERUNG.read_bytes()).hexdigest() == hashlib.sha256(
        QUELLE.read_bytes()
    ).hexdigest()


# ── 2. analyze_qea_statistics ───────────────────────────────────────────


@pytest.mark.parametrize("pfad", [QUELLE, AUSLIEFERUNG], ids=["quelle", "dist"])
def test_statistik_des_55_elemente_modells(
    pfad: Path, modell: Path, tmp_path: Path
) -> None:
    if not pfad.is_file():
        pytest.skip(f"{pfad.name} fehlt")
    stats = _statistik(_werkzeug(pfad, tmp_path), qea_path=str(modell))

    assert "error" not in stats, stats.get("error")
    assert stats["Packages"] == 4
    assert stats["Elements"] == 58  # 55 fachliche Elemente + 3 Paketspiegel
    assert stats["Connectors"] == 3
    assert stats["Diagrams"] == 0
    assert stats["ElementTypes"] == ERWARTETE_TYPEN
    assert stats["Stereotypes"] == ERWARTETE_STEREOTYPE
    assert sum(stats["Stereotypes"].values()) == 55


# ── 3. find_elements_in_qea ─────────────────────────────────────────────


def test_finde_nach_stereotyp(modell: Path, tmp_path: Path) -> None:
    werkzeug = _werkzeug(_werkzeugdatei(), tmp_path)
    treffer = _finde(werkzeug, qea_path=str(modell), stereotype="Capability")

    assert len(treffer) == 22
    assert {t["Object_Type"] for t in treffer} == {"Class"}
    assert {t["Package_Name"] for t in treffer} == {"01 Faehigkeiten"}
    assert treffer[0]["ea_guid"].startswith("{")
    assert treffer[0]["Object_ID"] > 0


def test_finde_nach_typ_und_grenze(modell: Path, tmp_path: Path) -> None:
    werkzeug = _werkzeug(_werkzeugdatei(), tmp_path)

    aktivitaeten = _finde(werkzeug, qea_path=str(modell), object_type="Activity")
    assert len(aktivitaeten) == 10
    assert {a["Stereotype"] for a in aktivitaeten} == {"OperationalActivity"}

    alle_klassen = _finde(
        werkzeug, qea_path=str(modell), object_type="Class", limit=200
    )
    assert len(alle_klassen) == 35

    begrenzt = _finde(werkzeug, qea_path=str(modell), object_type="Class", limit=5)
    assert len(begrenzt) == 5

    # Vorgabe der Werkzeugfunktion ist limit=50: ohne Filter bleiben von 58
    # Zeilen nur 50 uebrig. Wer alles will, muss limit setzen.
    ohne_filter = _finde(werkzeug, qea_path=str(modell))
    assert len(ohne_filter) == 50

    alles = _finde(werkzeug, qea_path=str(modell), limit=200)
    assert len(alles) == 58


def test_finde_nach_namensteil(modell: Path, tmp_path: Path) -> None:
    werkzeug = _werkzeug(_werkzeugdatei(), tmp_path)
    treffer = _finde(werkzeug, qea_path=str(modell), name="Faehigkeit 0")

    # "Faehigkeit 01" bis "Faehigkeit 09" — die 10 bis 22 haben zwei Ziffern davor.
    assert len(treffer) == 9
    assert sorted(t["Name"] for t in treffer) == [
        f"Faehigkeit {nummer:02d}" for nummer in range(1, 10)
    ]


def test_autoerkennung_ohne_pfad(modell: Path) -> None:
    """Ohne qea_path findet das Werkzeug die Datei im Suchordner selbst."""
    werkzeug = _werkzeug(_werkzeugdatei(), modell.parent)
    stats = _statistik(werkzeug)

    assert "error" not in stats, stats.get("error")
    assert stats["Elements"] == 58

    liste = json.loads(asyncio.run(werkzeug.list_available_qea_files()))
    assert [eintrag["name"] for eintrag in liste["files"]] == ["Rauchtest55.qea"]


def test_falscher_pfad_meldet_fehler_statt_ausnahme(modell: Path) -> None:
    """Bekannter Suchordner, falscher Dateiname: das Werkzeug antwortet mit JSON."""
    werkzeug = _werkzeug(_werkzeugdatei(), modell.parent)
    antwort = _statistik(werkzeug, qea_path="/tmp/gibt-es-nicht/Anderes.qea")

    # Kein Treffer im Pfad, im Suchordner liegt nur Rauchtest55.qea.
    assert "error" in antwort
    assert "No file found matching the provided qea_path" in antwort["error"]


# ── 4. Elementdetail (Beziehungen) ──────────────────────────────────────


def test_elementdetail_liefert_beziehungen(modell: Path, tmp_path: Path) -> None:
    werkzeug = _werkzeug(_werkzeugdatei(), tmp_path)
    treffer = _finde(werkzeug, qea_path=str(modell), name="System 01")
    assert len(treffer) == 1

    detail = json.loads(
        asyncio.run(
            werkzeug.get_element_detail_from_qea(
                qea_path=str(modell), element_id=treffer[0]["Object_ID"]
            )
        )
    )
    assert "error" not in detail, detail.get("error")
    assert detail["Name"] == "System 01"
    assert detail["Object_Type"] == "Class"
    assert detail["Stereotype"] == "System"
    assert detail["Package_Name"] == "02 Systeme"
    # Kanten des Modells: System 01 -> Faehigkeit 01 (Realization, ausgehend),
    # Ablauf 01 -> System 01 (Provides) und Anforderung 01 -> System 01 (Satisfy).
    assert len(detail["outgoing_relationships"]) == 1
    assert detail["outgoing_relationships"][0]["target_name"] == "Faehigkeit 01"
    assert sorted(k["Stereotype"] for k in detail["incoming_relationships"]) == [
        "Provides",
        "Satisfy",
    ]
