# Kontroll-Lauf: MASC-Handbuch → Architektur → Handbuch

Datum: 2026-10-25 · Modell: `anthropic/claude-opus-5.5` (OpenRouter) · Kosten gesamt: **0,44 USD** (~0,40 €)
Arbeitsordner: `/root/.hermes/cache/scratch/masc-workflow/`

## Prüfgegenstand

Eingang war das **natürlichsprachliche Handbuch** der Musterarchitektur MASC
(`eam-suite-ai/reports/handbuch_masc.md`, 49.773 Zeichen, 106 Absätze, 9 Kapitel) —
also das Ergebnis des Rückwegs aus dem echten Modell, nicht die `.qea` selbst.
Damit war der Weg vollständig: Prosa → Modell → Prosa.

Bewusste Festlegung: **kein Startpaket (StEKa)** in diesem Lauf, damit die
Extraktionsleistung des Modells gemessen wird und nicht die Trefferquote der
Zeichenkettenzuordnung. Das ist eine Abweichung von Workflowschritt 2 und gehört
zum Urteil dazu.

## Ergebnis der Kette

| Schritt | Ergebnis |
|---|---|
| 1 · MDG rein | NAFv4-ADMBw 2026.05, 180 Element-Stereotype, 138 Konnektor-Regeln |
| 2 · Startpaket | **übersprungen** (Messgründe, siehe oben) |
| 3 · Prosa rein | 106 Absätze, D1-S1 … D1-S106 |
| 4 · Bauen | 112 Elemente, 38 Beziehungen, 450 Herkunfts-Tags, 1 Reparaturrunde, **0 Fehler / 0 Warnungen** |
| 5–6 · Sehen/Bearbeiten | nicht Teil dieses Laufs |
| Rückweg | `handbuch_generator.py` → 27.000 Zeichen Betriebshandbuch, 26 Dienste, 236 Absätze |

Zwei Namen wurden bei der Extraktion verworfen (Doppelnennung), einer per
Reparatur umgestuft: »Multipurpose Armed Spacecraft« von `CapabilityConfiguration`
auf `ActualResource`, weil es als Endpunkt einer verbotenen Kante stand.

## Teil 1 — ADMBw-Konformität: **weitgehend konform**

Prüfung gegen das Regelwerk der MDG, nicht gegen die eigene Validierung:

- **Abstrakte Stereotype instanziiert:** keine. Geprüft für Elemente und Kanten
  (`abstract: true` in der MDG, 43 von 180).
- **Unbekannte Stereotype:** keine. Alle verwendeten Element- und
  Kanten-Stereotype stehen im Regelwerk.
- **Metaconstraints:** **1 Verstoß** — `ResourceExchange` verbindet
  »Rolle R1« (`OperationalRole`) mit »Aktivität A1«
  (`ServiceSpecificationRole`). Die Regel erlaubt
  `ResourcePerformer`/`ResourceRole`/`ServiceSpecificationRole`;
  `OperationalRole` erbt nicht von `ResourceRole` (beide erben nur von `AssetRole`).
  **Gegenprobe:** das MASC-Original hat bei derselben Prüfung **99** Verstöße —
  der Nachbau ist an dieser Stelle sauberer als das Original.
- **Struktur:** 1 Paket, 336 Herkunfts-Properties (`source_ref`, `source_doc`,
  `source_confidence`), 37 der 106 Absätze belegt.

**Einschränkung:** Die Prüfung deckt Stereotype und Metaconstraints ab. Ob ein
Element den richtigen Typ bekommen hat, prüft die MDG nicht — dafür steht das
Ergebnis unten: bei 107 gemeinsam mit dem Original vorhandenen Namen stimmt das
Stereotyp in 94 Fällen (88 %), 13 weichen ab.

## Teil 2 — Semantischer Abgleich: **teilweise**

Das aus dem Nachbau erzeugte Handbuch deckt den Dienstkern ab, verliert aber
weite Teile des Originals — und ordnet Absätze falschen Elementen zu.

**Erhalten:** alle 26 Dienste samt der sechs Einordnungsketten in die
Dienstelandschaft; Selbstbeschreibung des »Spacecraft Information Service Bw«
mit seinen fünf Funktionen, Abhängigkeiten, Nutzung durch »Monitoring Service Bw«
und der Fähigkeit »Fähigkeit F1«; die drei Varianten dieses Dienstes;
»Man in the loop«; drei Konfigurationen; die Beteiligten (Effektor, Bodenkontroll-
station, Schleuse); Fähigkeiten mit ihrer Bündelung.

**Inhaltlich verloren:**

- Zustandsfolgen (Zugang Schleuse, Software, Space Situation Awareness Service)
- die 5 Dienstrollen
- die 3 Schnittstellen und 6 Zugänge
- 20 Meilensteine mit 16 Freigabe-/Rückzugsbeziehungen, 5 Projekte
- 23 Forderungen in 12 Kategorien
- 9 Randbedingungen des Betriebs
- Phasenzuordnung der Fähigkeiten
- der einzige Dienst, der eine Fähigkeit trägt

**Falsch zugeordnet:** Die Selbstbeschreibung des Spacecraft Information Service
erscheint als Beschreibung von »Element E1«; die
Bereichsnotiz der Idealtypischen Architektur als Beschreibung des »Operationellen
Architekten Bundeswehr«; die Kettenübersicht als Eigenbeschreibung einzelner
Dienste. Ursache: Der Generator nimmt den **nächstgelegenen Absatz** als Notiz —
bei Prosa, die generiert wurde statt von Hand geschrieben, greift er daneben.

**Hinzugefügt (nicht in der Vorlage angelegt):** »Ein ausformulierter Auftrag ist
nicht festgehalten« (widerspricht der Vorlage), 7 Baugruppen, abweichende
Beziehungszählungen, zwei Betriebsregeln ohne Grundlage.

**Keine Erfindung von Elementen:** 107 der 112 Namen stehen im Original. Die
übrigen fünf sind Schreibvarianten (Zeilenumbrüche in EA-Namen, »MASC« in
Klammern). Kein Element wurde frei erfunden.

## Die eigentliche Ursache

**69 von 106 Absätzen haben kein Element erzeugt** — die Extraktion hat 37
Absätze ausgewertet. Genau in den 69 liegen Zustandsfolgen, Rollen, Schnitt-
stellen, Meilensteine, Forderungen und Randbedingungen. Es ist also **kein
Fehler des Rückwegs**, sondern ein **Deckungsverlust im Bau-Schritt**: das Modell
enthält nur den Dienstkern. Der Rückweg gibt korrekt wieder, was im Modell steht.

Zwei Gründe, beide belegbar:

1. **Prompt-Budget.** Der Extraktions-Prompt umfasst 75.000 Zeichen (19.000
   Tokens) mit dem vollständigen Regelwerk; der Modellantwort war auf 4.000
   Tokens begrenzt. Bei 106 Absätzen reicht das für den Kern, nicht für die
   Randbereiche.
2. **Die Quelle ist selbst schon Prosa aus einem Modell.** Absätze wie
   »### Dienstrollen« sind Gliederung, keine Aussage; der Extraktor soll
   ausdrücklich nichts erfinden und lässt sie fallen.

## Was daraus folgt

- Die **Kette selbst ist in Ordnung**: MDG wirkt, Konformität wird geprüft,
  Reparatur greift, Herkunft wird getaggt, der Rückweg ist deterministisch.
- **Skalierung ist die offene Flanke.** Ein Handbuch dieser Größe in einem
  Aufruf zu extrahieren, verliert die Randbereiche. Nötig ist eine Aufteilung
  der Quelle in Abschnitte (Kapitel- oder Paketweise) mit je eigenem Aufruf und
  anschließender Zusammenführung — dann bleibt das Budget pro Aufruf klein.
- **Der Handbuch-Generator braucht eine Zuordnungsprüfung.** Er übernimmt den
  nächstgelegenen Absatz als Notiz; bei maschinell erzeugter Prosa führt das zu
  den sieben Fehlzuordnungen. Ein Abgleich »Notiz nennt das Element, dem sie
  zugeordnet wird« würde das abfangen.

## Prüfmaßstab

Die Bewertung stammt von Opus 5.5 in zwei getrennten Aufrufen (Detailprüfung
Teilkopf, Vollprüfung mit 45.000 Zeichen je Seite). **Fehlalarm-Korrektur:**
Der Prüfer hat im ersten Aufruf sieben angeblich erfundene Elemente gemeldet —
alle sieben stehen im Eingangstext; der Prompt hatte Namen nur in Anführungs-
zeichen gelten lassen. Nach Gegenprüfung am Original entfällt der Vorwurf
»halluziniert« vollständig.

Reproduzierbar mit:

```bash
export OPENAI_API_KEY="$OPENROUTER_API_KEY"   # eam-ai liest OPENAI_API_KEY
eam-ai build --mdg packages/rules/$(cat packages/rules/CURRENT) \
  --text handbuch_masc.md --out architektur.qea --package MASC-Nachbau \
  --backend openai --base-url https://openrouter.ai/api/v1 \
  --model anthropic/claude-opus-5.5 --timeout 900 \
  --repair --repair-bericht repair.json --quellen quellen.json
python packages/core/handbuch_generator.py architektur.qea --md rueck-handbuch.md
```
