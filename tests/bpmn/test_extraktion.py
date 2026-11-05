"""Regelbasierte Prosa-Extraktion und optionaler KI-Adapter.

Die drei Beispieltexte sind absichtlich unterschiedlich gebaut: Behoerdenantrag
mit Bedingung, Leasing mit Koordination ("erstellt ... und sendet ...") und
Wartungsticket mit Passivnaehe. Geprueft wird nicht nur, *dass* Schritte
entstehen, sondern welche Rollen, Objekte und Sicherheitsgrade herauskommen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bpmn import admbw, bpmn_xml, extraktion, ki

ANTWORT = """Der Antragsteller reicht den Antrag beim Bauamt ein.
Anschließend prüft der Sachbearbeiter die Unterlagen.
Wenn Unterlagen fehlen, fordert der Sachbearbeiter die Nachweise an.
Danach entscheidet der Sachbearbeiter über den Antrag.
Der Sachbearbeiter erstellt den Bescheid und sendet ihn an den Antragsteller."""

LEASING = """Der Kunde stellt einen Leasingantrag.
Die Leasinggesellschaft prüft die Bonität des Kunden.
Danach erstellt die Leasinggesellschaft ein Angebot und sendet es an den Kunden.
Der Kunde unterschreibt den Leasingvertrag.
Anschließend übergibt die Leasinggesellschaft das Fahrzeug.
Die Buchhaltung bucht die monatliche Rate."""

WARTUNG = """Der Techniker erfasst das Wartungsticket im System.
Falls eine Störung vorliegt, prüft der Techniker die Anlage.
Der Techniker bestellt Ersatzteile.
Nach der Reparatur dokumentiert der Techniker die Arbeiten.
Der Servicedesk informiert den Kunden."""


def _namen(ergebnis: extraktion.Extraktion) -> list[str]:
    return [schritt.name for schritt in ergebnis.schritte]


# --------------------------------------------------------------------------
# Drei Beispieltexte
# --------------------------------------------------------------------------


def test_behoerdenantrag_schritte_rollen_bedingung() -> None:
    ergebnis = extraktion.extrahiere(ANTWORT, "Antragsbearbeitung")

    assert _namen(ergebnis) == [
        "Antrag einreichen",
        "Unterlagen pruefen",
        "Nachweise anfordern",
        "Antrag entscheiden",
        "Bescheid erstellen",
        "Bescheid senden",
    ]
    assert [s.rolle for s in ergebnis.schritte] == [
        "Antragsteller",
        "Sachbearbeiter",
        "Sachbearbeiter",
        "Sachbearbeiter",
        "Sachbearbeiter",
        "Sachbearbeiter",
    ]
    assert ergebnis.schritte[0].objekt == "Antrag"
    assert ergebnis.schritte[2].bedingung == "Unterlagen fehlen"
    assert ergebnis.schritte[2].art == "user_task"
    assert ergebnis.schritte[5].art == "send_task"
    assert all(s.sicherheit == extraktion.SICHER for s in ergebnis.schritte)
    # Das Bauamt ist Empfaenger, aber nicht handelnde Lane.
    assert "Bauamt" in ergebnis.rollen
    lanes = [lane.name for lane in ergebnis.modell.prozesse["Process_1"].alle_lanes()]
    assert lanes == ["Antragsteller", "Sachbearbeiter"]
    assert admbw.pruefe(ergebnis.modell) == []


def test_leasing_schritte_und_koordination() -> None:
    ergebnis = extraktion.extrahiere(LEASING, "Leasingprozess")

    assert _namen(ergebnis) == [
        "Leasingantrag stellen",
        "Bonität pruefen",
        "Angebot erstellen",
        "Angebot senden",
        "Leasingvertrag unterschreiben",
        "Fahrzeug uebergeben",
        "Monatliche Rate buchen",
    ]
    assert ergebnis.rollen == ["Kunde", "Leasinggesellschaft", "Buchhaltung"]
    # "erstellt ... und sendet es" -- das Pronomen wird zum vorigen Objekt.
    assert ergebnis.schritte[3].objekt == "Angebot"
    assert ergebnis.schritte[3].rolle == "Leasinggesellschaft"
    assert all(s.sicherheit == extraktion.SICHER for s in ergebnis.schritte)
    assert admbw.pruefe(ergebnis.modell) == []


def test_wartungsticket_bedingung_und_empfaenger() -> None:
    ergebnis = extraktion.extrahiere(WARTUNG, "Wartungsticket")

    assert _namen(ergebnis) == [
        "Wartungsticket erfassen",
        "Anlage pruefen",
        "Ersatzteile bestellen",
        "Arbeiten dokumentieren",
        "Kunden informieren",
    ]
    assert ergebnis.schritte[1].bedingung == "eine Störung vorliegt"
    assert ergebnis.rollen == ["Techniker", "Servicedesk"]
    assert admbw.pruefe(ergebnis.modell) == []


# --------------------------------------------------------------------------
# Sicherheitsgrade
# --------------------------------------------------------------------------


def test_passiv_ohne_agens_ist_unsicher() -> None:
    ergebnis = extraktion.extrahiere("Der Antrag wird geprüft.", "Passiv")

    assert len(ergebnis.schritte) == 1
    schritt = ergebnis.schritte[0]
    assert schritt.name == "Antrag pruefen"
    assert schritt.sicherheit == extraktion.UNSICHER
    assert "Passiv" in schritt.begruendung
    assert ergebnis.sicherheit[ergebnis.modell.knoten["UserTask_3"].id] == extraktion.UNSICHER


def test_sicherheitsgrad_steht_je_element() -> None:
    ergebnis = extraktion.extrahiere("Der Sachbearbeiter prüft den Antrag.", "Kurz")

    knoten = next(k for k in ergebnis.modell.knoten.values() if k.ist_aufgabe)
    lane = ergebnis.modell.prozesse["Process_1"].alle_lanes()[0]
    start = next(k for k in ergebnis.modell.knoten.values() if k.ist_start)
    assert ergebnis.sicherheit[knoten.id] == extraktion.SICHER
    assert ergebnis.sicherheit[lane.id] == extraktion.SICHER
    assert ergebnis.sicherheit[start.id] == extraktion.UNSICHER
    assert "Sachbearbeiter" in ergebnis.begruendungen[lane.id]


def test_beschreibung_ohne_handlung_liefert_keine_schritte() -> None:
    ergebnis = extraktion.extrahiere(
        "Die Unterlagen sind vollstaendig. Der Antrag ist vom 3. Mai.", "Leer"
    )

    assert ergebnis.schritte == []
    assert any("Kein Prozessschritt" in h for h in ergebnis.hinweise)


def test_nummerierte_liste_wird_prozess() -> None:
    ergebnis = extraktion.extrahiere(
        "1. Antrag erfassen\n2. Antrag prüfen\n3. Bescheid senden", "Liste"
    )

    assert _namen(ergebnis) == ["Antrag erfassen", "Antrag pruefen", "Bescheid senden"]
    assert all(s.quelle == "liste" for s in ergebnis.schritte)
    assert all(s.sicherheit == extraktion.SICHER for s in ergebnis.schritte)
    lane = ergebnis.modell.prozesse["Process_1"].alle_lanes()[0]
    assert lane.name == "Bearbeitung"
    assert ergebnis.sicherheit[lane.id] == extraktion.UNSICHER


def test_extraktion_ist_deterministisch() -> None:
    erst = extraktion.extrahiere(ANTWORT, "Antragsbearbeitung")
    zweit = extraktion.extrahiere(ANTWORT, "Antragsbearbeitung")

    assert bpmn_xml.schreibe_text(erst.modell) == bpmn_xml.schreibe_text(zweit.modell)
    assert erst.als_dict() == zweit.als_dict()


def test_modell_laesst_sich_als_bpmn_lesen() -> None:
    ergebnis = extraktion.extrahiere(ANTWORT, "Antragsbearbeitung")
    xml = bpmn_xml.schreibe_text(ergebnis.modell)
    gelesen = bpmn_xml.lies_text(xml)

    assert len(gelesen.knoten) == len(ergebnis.modell.knoten)
    assert len(gelesen.fluesse) == len(ergebnis.modell.fluesse)
    assert admbw.pruefe(gelesen) == []


# --------------------------------------------------------------------------
# KI-Adapter: aus per Default, kein stiller Rueckfall
# --------------------------------------------------------------------------


@pytest.fixture()
def ki_aus(monkeypatch, tmp_path: Path) -> None:
    for name in ("BPMN_KI_AKTIV", "BPMN_KI_BASIS_URL", "BPMN_KI_MODELL", "BPMN_KI_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ki, "_dotenv_pfade", lambda: [tmp_path / "leer.env"])


@pytest.fixture()
def ki_an(monkeypatch) -> None:
    monkeypatch.setenv("BPMN_KI_AKTIV", "1")
    monkeypatch.setenv("BPMN_KI_BASIS_URL", "https://example.invalid/v1")
    monkeypatch.setenv("BPMN_KI_MODELL", "test-modell")
    monkeypatch.setenv("BPMN_KI_KEY", "geheim-123")


def test_ki_ist_standardmaessig_aus(ki_aus) -> None:
    zustand = ki.status()

    assert zustand["aktiv"] is False
    assert zustand["konfiguriert"] is False
    assert zustand["key"] == "fehlt"
    with pytest.raises(ki.KINichtKonfiguriert):
        ki.extrahiere_mit_ki("Der Sachbearbeiter prueft den Antrag.")


def test_ki_status_zeigt_keinen_schluessel(ki_an) -> None:
    zustand = ki.status()

    assert zustand["konfiguriert"] is True
    assert zustand["key"] == "gesetzt"
    assert "geheim-123" not in json.dumps(zustand)


def test_ki_antwort_wird_zum_modell(ki_an, monkeypatch) -> None:
    gesehen: dict = {}

    def fake_sende(anfrage, konfiguration, opener=None):
        gesehen.update(anfrage)
        inhalt = json.dumps(
            {
                "schritte": [
                    {"rolle": "Sachbearbeiter", "aktion": "pruefen", "objekt": "Antrag", "bedingung": ""},
                    {"rolle": "Sachbearbeiter", "aktion": "senden", "objekt": "Bescheid", "bedingung": ""},
                ]
            }
        )
        return json.dumps({"choices": [{"message": {"content": inhalt}}]})

    monkeypatch.setattr(ki, "_sende", fake_sende)
    ergebnis = ki.extrahiere_mit_ki(ANTWORT, "KI-Prozess")

    assert gesehen["model"] == "test-modell"
    assert gesehen["temperature"] == 0
    assert _namen(ergebnis) == ["Antrag pruefen", "Bescheid senden"]
    assert ergebnis.quelle == "ki"
    assert all(s.sicherheit == extraktion.UNSICHER for s in ergebnis.schritte)
    assert any("KI-Ausgabe" in h for h in ergebnis.hinweise)


def test_ki_verweigert_personenbezug(ki_an) -> None:
    with pytest.raises(ki.KIDatenschutz) as fehler:
        ki.extrahiere_mit_ki("Der Sachbearbeiter mailt an max.mustermann@example.invalid.")

    assert "E-Mail-Adresse" in str(fehler.value)


def test_ki_bricht_bei_kaputter_antwort_ab(ki_an, monkeypatch) -> None:
    monkeypatch.setattr(ki, "_sende", lambda *a, **k: json.dumps({"choices": [{"message": {"content": "kein json"}}]}))

    with pytest.raises(ki.KIAntwortFehler):
        ki.extrahiere_mit_ki("Der Sachbearbeiter prueft den Antrag.")


def test_auftrag_waehlt_den_genannten_abschnitt() -> None:
    """'anbei Handbuch, extrahiere den Prozess X' schneidet genau diesen Abschnitt."""
    text = (
        "Handbuch Antraege\n\n"
        "Prozess Antragsbearbeitung\n"
        "Der Sachbearbeiter nimmt den Antrag an. Danach prueft die Fachabteilung die Unterlagen.\n\n"
        "Prozess Rechnungslauf\n"
        "Die Buchhaltung erstellt die Rechnung. Danach sendet sie die Rechnung an den Kunden.\n"
        "Anschliessend bucht die Buchhaltung den Zahlungseingang.\n"
    )
    ergebnis = extraktion.extrahiere(
        text, anweisung="Anbei das Handbuch, extrahiere den Prozess Rechnungslauf"
    )
    aktionen = [schritt.aktion for schritt in ergebnis.schritte]
    assert "erstellen" in aktionen
    assert "senden" in aktionen
    assert "annehmen" not in aktionen, "Abschnitt Antragsbearbeitung haette nicht zaehlen duerfen"
    assert ergebnis.modell.name == "Rechnungslauf"
    assert any("Abschnitt" in h for h in ergebnis.hinweise)


def test_auftrag_ohne_treffer_nimmt_den_ganzen_text() -> None:
    text = "Der Sachbearbeiter prueft den Antrag. Danach erstellt er den Bescheid."
    ergebnis = extraktion.extrahiere(text, anweisung="extrahiere den Prozess Mondlandung")
    assert len(ergebnis.schritte) >= 1
    assert any("kein passender Abschnitt" in h for h in ergebnis.hinweise)
