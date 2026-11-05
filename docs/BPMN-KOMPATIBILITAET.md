# BPMN-Austausch: bpmn.io, ARIS, Enterprise Architect

Stand: 05.11.2026. Dieses Dokument trennt **selbst geprüft** von **nur aus
Dokumenten belegt**. Wo ein Werkzeug hier nicht installiert ist, steht das
ausdrücklich dabei — es wird nichts als getestet ausgegeben, was nur gelesen
wurde.

## Was das Studio schreibt

- BPMN 2.0 XML mit den Namensräumen `bpmn`, `bpmndi`, `dc`, `di`, `xsi`.
- Semantik **und** Diagrammgeometrie (`BPMNDiagram`, `BPMNPlane`, `BPMNShape`,
  `BPMNEdge` mit Wegpunkten) — ohne Geometrie zeigt bpmn.io ein leeres Blatt.
- ADMBw-Erweiterungen ausschließlich in `extensionElements` unter einem eigenen
  Namensraum. Kein Standardelement wird umgedeutet.

## Selbst geprüft (auf diesem Host)

| Prüfung | Ergebnis |
|---|---|
| XSD-Validierung gegen das offizielle BPMN-20-Schema (OMG) | gültig: Fixture-Modell, drei Extraktionsmodelle, beide bpmn.io-Dateien |
| Roundtrip XML → Modell → XML → Modell | byte-stabil, kein Semantikverlust |
| Import in bpmn-js 17 (headless, Chromium) | 51 Elemente, 10/10 Assoziationen, 0 Seitenfehler |
| bpmn-js-Export wieder eingelesen | Conveyed-Bindungen vollständig rekonstruiert, XSD-gültig |
| Externe Anfragen der Einzeldatei | 0 |

Eine beim Test gefundene und behobene Eigenheit: Das Schema erlaubt eine
`association` auf einen Sequenzfluss, **bpmn.io zeichnet sie aber nicht**. Die
Assoziation zeigt deshalb auf den Knoten; die Flussbindung steht als
`admbw:conveyed` daneben und wird beim Lesen wieder aufgelöst.

## bpmn.io / bpmn-js

- Bibliothek unter MIT-Lizenz, gebündelt in `vendor/bpmn-js/`, Lizenztext liegt bei.
- Gelesen und geschrieben wird das Standardformat; bpmn.io ist damit der
  Referenzleser für unsere Dateien.
- Begrenzung: bpmn-js ignoriert unbekannte `extensionElements` beim Bearbeiten,
  behält sie aber beim Speichern. Für die ADMBw-Prüfung heißt das: nach dem
  Bearbeiten in bpmn.io erneut prüfen, nicht auf alte Befunde verlassen.

## ARIS

Belegt aus dem MIWG-Testbestand (<https://bpmn-miwg.github.io/bpmn-miwg-tools/>,
`tools-tested-by-miwg.json` und `submissions.json`, abgerufen 05.11.2026):

- ARIS 10.2025.07: Import, Export und Roundtrip jeweils als bestanden geführt,
  letzte Einreichung 2025, **21 von 21** Testfällen (92 Dateien).

Belegt aus der ARIS-Dokumentation (Software AG):

- Feature-Matrix nennt „Import of BPMN 2.0 and e-BPMN" und „Export BPMN 2.0 and e-BPMN".
- Eigene Hilfeseiten „Import BPMN file" und „Validate BPMN model for export".
- „ARIS Fast-Track BPMN2 Import" grenzt den Umfang ausdrücklich auf
  **„Standard BPMN 2.0 constructs only"** ein.
- Community-Aussage eines Mitarbeiters: unbekannte `extensionElements` bleiben
  beim Roundtrip erhalten.

**Nicht geprüft:** ein echter Import in ARIS — das Werkzeug steht hier nicht zur
Verfügung. Die Aussage ist Dokumentenlage, kein Hands-on-Test.

## Enterprise Architect

Belegt aus dem MIWG-Testbestand:

- Enterprise Architect 12.0.1207: Import, Export und Roundtrip als bestanden
  geführt, letzte Einreichung **2015**, nur **7 Testfälle** (A.1.0, A.2.0, A.3.0,
  A.4.0, A.4.1, B.1.0, B.2.0), **keine** Kategorie C.

Belegt aus dem EA-Benutzerhandbuch 17.2 (<https://sparxsystems.com>):

- Import über *Publish > Model Exchange > Import > BPMN 2.0*.
- Export über *BPMN 2.0 XML*.
- Hinweise: das Paket gilt als selbstständig, Kindpakete werden ignoriert;
  `InputOutputBinding` und `Conversation Association` sind nicht serialisierbar;
  verfügbar in allen Editionen.

**Nicht geprüft:** ein echter Import in Enterprise Architect.

## Offene Punkte

1. **Kein Hands-on-Test in ARIS und Enterprise Architect.** Beide Werkzeuge sind
   hier nicht installiert. Wer es verbindlich braucht, muss je eine Datei dort
   importieren und das Ergebnis zurückmelden.
2. **Fremde Erweiterungen gehen verloren.** `zeebe:taskDefinition` und ähnliche
   Elemente werden beim Lesen nicht übernommen. Das ist bewusst: das Studio
   führt ein ADMBw-Modell, keinen fremden Executable-Dialekt. Wer Camunda-Dateien
   nur ansehen will, verliert beim Speichern diese Angaben.
3. **EA-Version im MIWG-Bestand ist alt (2015, Version 12).** Neuere EA-Fassungen
   sind dort nicht eingereicht; die Abdeckung ist damit schwächer belegt als bei ARIS.
4. **ARIS rechnet intern in EPC.** Der BPMN-Import ist eine Übersetzung, kein
   natives Format. Rundläufe ARIS → BPMN → ARIS sind nicht getestet.
