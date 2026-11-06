"""Die amtliche MDG kommt per Knopfdruck — ohne CORS-Umweg.

Der Browser darf bundeswehr.de nicht direkt laden (die Gegenseite sendet keine
CORS-Freigabe). Deshalb liefert die Projektseite dieselbe Datei aus, die der
Regelwerk-Wächter pflegt, zusammen mit einem Manifest. Der Test hält die drei
Glieder dieser Kette fest: Knopf im Werkzeug, Manifest-Erzeugung, Auslieferung
über die Pages-Arbeitsabläufe.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "admbw-extractor" / "html" / "index.html"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
RULES = ROOT / "packages" / "rules"


def _lade_manifest_modul():
    pfad = ROOT / "scripts" / "mdg_manifest.py"
    spec = importlib.util.spec_from_file_location("mdg_manifest", pfad)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_knopf_und_ladelogik_sind_vorhanden() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert 'id="btn-mdg"' in text
    assert "Amtliche MDG laden" in text
    assert "mdg/manifest.json" in text
    assert "ladeAmtlicheMdg" in text
    # Prüfsumme wird im Browser geprüft, bevor verarbeitet wird.
    assert "crypto.subtle.digest" in text


def test_datei_modus_faellt_sauber_zurueck() -> None:
    """Ohne HTTP gibt es kein Manifest — dann muss der Knopf deaktiviert werden."""
    text = SRC.read_text(encoding="utf-8")
    assert "btn-mdg').disabled = true" in text
    assert "bitte Datei wählen" in text


def test_manifest_traegt_version_und_pruefsumme() -> None:
    modul = _lade_manifest_modul()
    aktuell = (RULES / "CURRENT").read_text(encoding="utf-8").strip()
    xml = RULES / aktuell
    manifest = modul.baue_manifest(xml)

    daten = xml.read_bytes()
    assert manifest["datei"] == aktuell
    assert manifest["bytes"] == len(daten)
    assert manifest["sha256"] == hashlib.sha256(daten).hexdigest()
    assert manifest["version"] == modul.version_aus_name(aktuell)
    assert manifest["version"], "Version muss aus dem Dateinamen kommen"
    assert manifest["quelle"].startswith("https://www.bundeswehr.de/")


def test_manifest_ist_deterministisch(tmp_path: Path) -> None:
    modul = _lade_manifest_modul()
    aktuell = (RULES / "CURRENT").read_text(encoding="utf-8").strip()
    xml = RULES / aktuell

    erste = tmp_path / "a.json"
    zweite = tmp_path / "b.json"
    for ziel in (erste, zweite):
        manifest = modul.baue_manifest(xml)
        ziel.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    assert erste.read_bytes() == zweite.read_bytes()


def test_pages_liefert_mdg_und_manifest_aus() -> None:
    text = PAGES.read_text(encoding="utf-8")
    assert "seite/admbw-extraktor/mdg" in text
    assert "packages/rules/CURRENT" in text
    assert "scripts/mdg_manifest.py" in text
    assert "manifest.json" in text


def test_veroeffentlichungs_job_hat_repo_checkout() -> None:
    """Der Publish-Job bekommt nur `dist` — ohne Checkout fehlt packages/rules.

    Genau daran ist der erste Lauf gescheitert: 'packages/rules/CURRENT:
    No such file or directory', weil der Job ohne Arbeitskopie startet.
    """
    try:
        import yaml
    except ModuleNotFoundError:  # pragma: no cover - Umgebungen ohne PyYAML
        # Ohne YAML-Parser genügt der Blick auf den Abschnitt des Jobs.
        text = PAGES.read_text(encoding="utf-8")
        abschnitt = text.split("veroeffentlichen:", 1)[1]
        assert "actions/checkout" in abschnitt, "Publish-Job ohne Checkout"
        return

    daten = yaml.safe_load(PAGES.read_text(encoding="utf-8"))
    schritte = daten["jobs"]["veroeffentlichen"]["steps"]
    uses = [str(s.get("uses", "")) for s in schritte]
    assert any("actions/checkout" in u for u in uses), "Publish-Job ohne Checkout"

    # Der Checkout muss vor dem Schritt stehen, der packages/rules liest.
    index_checkout = next(i for i, u in enumerate(uses) if "actions/checkout" in u)
    index_nutzung = next(
        i for i, s in enumerate(schritte)
        if "packages/rules" in str(s.get("run", ""))
    )
    assert index_checkout < index_nutzung
