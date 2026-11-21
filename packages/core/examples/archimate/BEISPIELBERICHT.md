# ArchiMate-Modellbefund

- **Datei:** beispiel_fehlermodell.xml
- **Modell:** Beispiel: Pruefmodell mit drei Fehlerklassen
- **Kennung:** id-beispiel-pruefung
- **Format:** ArchiMate Model Exchange (http://www.opengroup.org/xsd/archimate/3.0/)
- **Groesse:** 0 Pakete, 6 Elemente (6 fachlich), 6 Beziehungen, 0 Sichten

## Zusammenfassung

| Schicht | Elemente |
| --- | ---: |
| Anwendung | 3 |
| Geschaeft | 3 |

| Konzept | Elemente |
| --- | ---: |
| ApplicationComponent | 2 |
| BusinessActor | 1 |
| BusinessObject | 1 |
| BusinessService | 1 |
| DataObject | 1 |

| Beziehungsart | Kanten |
| --- | ---: |
| Serving | 3 |
| Access | 1 |
| Assignment | 1 |
| Composition | 1 |

## Pruefbarkeit

- Elemente ohne Konzept: **0**
- Kanten ohne Beziehungsart: **0**
- Elemente ohne Beziehung: **2**
- Pakete als Kantenendpunkt: **0**

## Qualitaetsbefund

**7 Meldungen:** 3 Fehler, 4 Warnungen, 0 Hinweise.

| Schwere | Pruefung | Objekt | Befund |
| --- | --- | --- | --- |
| Fehler | `matrixViolation` | Assignment Sachbearbeiter -> Fachverfahren (#4) | Assignment von BusinessActor nach ApplicationComponent ist nicht erlaubt (Sachbearbeiter -> Fachverfahren). |
| Fehler | `matrixViolation` | besteht aus | Composition von BusinessActor nach BusinessService ist nicht erlaubt (Sachbearbeiter -> Antrag bearbeiten). |
| Fehler | `unresolvedReference` | zeigt ins Leere | Ziel 'id-el-99' zeigt auf kein Element und kein Paket des Modells. |
| Warnung | `orphanElement` | #1 | BusinessObject haengt an keiner aufloesbaren Beziehung (weder Quelle noch Ziel). |
| Warnung | `orphanElement` | Altsystem | ApplicationComponent haengt an keiner aufloesbaren Beziehung (weder Quelle noch Ziel). |
| Warnung | `selfReference` | Serving Antrag bearbeiten -> Antrag bearbeiten (#6) | Quelle und Ziel sind dasselbe Element. |
| Warnung | `unnamedElement` | #1 | BusinessObject ohne Namen. |
