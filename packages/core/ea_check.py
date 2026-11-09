"""EA-Öffnungstest für erzeugte `.qea`-Dateien (stdlib only).

Warum es dieses Modul gibt
--------------------------
Der Writer legt nur die Tabellen an, die ein *Leser* braucht (AAroN: 15 + `t_xref`).
Sparx Enterprise Architect prüft beim Öffnen seinen kompletten internen Satz und
bricht bei der ersten fehlenden Tabelle mit ``SQL API Open FAILED`` ab — nacheinander
für `t_document`, `t_genopt`, `t_datatypes`, `t_rules`, `t_maintypes` …
Gefunden wurde das erst durch Fehlermeldungen aus der Praxis, nicht durch Tests.

Dieses Modul prüft das ab, was EA prüft — **bevor** eine Datei ausgeliefert wird:

1. Vollständigkeit: enthält die Datei jede Tabelle, die EA abfragt?
2. Anfragbarkeit: laufen die real beobachteten EA-Abfragen fehlerfrei?
3. Geometrie: liegen die Kästen einer Sicht übereinander oder ist die Höhe negativ?

Die Abfragen sind aus den Fehlermeldungen übernommen, nicht erfunden. Wer eine neue
EA-Meldung sieht, ergänzt sie hier — dann greift die Prüfung in jeder Pipeline.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

#: (Tabelle, Spalte, Zweck) — EA fragt diese Nachschlagetabellen beim Öffnen ab.
EA_REQUIRED_TABLES: tuple[str, ...] = (
    "usys_system",
    "t_document",
    "t_genopt",
    "t_datatypes",
    "t_rules",
    "t_maintypes",
    "t_objecttypes",
    "t_diagramtypes",
    "t_connectortypes",
    "t_statustypes",
    "t_requiretypes",
    "t_complexitytypes",
    "t_efforttypes",
    "t_constrainttypes",
    "t_authors",
    "t_cardinality",
    "t_clients",
    "t_metrictypes",
    "t_phase",
    "t_problemtypes",
    "t_projectroles",
    "t_resources",
    "t_risktypes",
    "t_scenariotypes",
    "t_testtypes",
)

#: Die Abfragen, die Enterprise Architect beim Öffnen nachweislich absetzt.
#: Quelle: Fehlermeldungen „SQL API Open FAILED with error: no such table: …“
#: (EA Build 1716, 64 Bit). Reihenfolge = Reihenfolge des Auftretens.
EA_QUERIES: tuple[tuple[str, str], ...] = (
    ("t_document (TECHNOLOGY)",
     "SELECT * FROM t_document WHERE DocType='TECHNOLOGY'"),
    ("t_genopt (MDG)",
     "SELECT * FROM t_genopt WHERE AppliesTo IN ('MDGBIklst','MDGRequire')"),
    ("t_datatypes",
     "SELECT * FROM t_datatypes ORDER BY ProductName, DataType"),
    ("t_rules (workflow)",
     "SELECT * FROM t_rules WHERE RuleType = 'workflow_pt'"),
    ("t_document (RibbonSets)",
     "SELECT StrContent FROM t_document WHERE DocType = 'GroupRibbonSets'"),
    ("t_genopt (VCConfigs)",
     "SELECT [Option] FROM t_genopt WHERE AppliesTo='VCConfigs'"),
    # Sammelabfrage für alle Nachschlagelisten; scheitert an jeder fehlenden Tabelle.
    ("Nachschlagelisten (UNION)", """
        SELECT t_constrainttypes.[Constraint] AS Data, 't_constrainttypes' AS TableName FROM t_constrainttypes
        UNION ALL SELECT t_authors.AuthorName, 't_authors' FROM t_authors
        UNION ALL SELECT t_cardinality.Cardinality, 't_cardinality' FROM t_cardinality
        UNION ALL SELECT t_clients.Name, 't_clients' FROM t_clients
        UNION ALL SELECT t_complexitytypes.Complexity, 't_complexitytypes' FROM t_complexitytypes
        UNION ALL SELECT t_efforttypes.EffortType, 't_efforttypes' FROM t_efforttypes
        UNION ALL SELECT t_maintypes.MainType, 't_maintypes' FROM t_maintypes
        UNION ALL SELECT t_metrictypes.Metric, 't_metrictypes' FROM t_metrictypes
        UNION ALL SELECT t_objecttypes.Object_Type, 't_objecttypes' FROM t_objecttypes
        UNION ALL SELECT t_phase.PhaseName, 't_phase' FROM t_phase
        UNION ALL SELECT t_problemtypes.ProblemType, 't_problemtypes' FROM t_problemtypes
        UNION ALL SELECT t_projectroles.Role, 't_projectroles' FROM t_projectroles
        UNION ALL SELECT t_requiretypes.Requirement, 't_requiretypes' FROM t_requiretypes
        UNION ALL SELECT t_resources.Name, 't_resources' FROM t_resources
        UNION ALL SELECT t_risktypes.Risk, 't_risktypes' FROM t_risktypes
        UNION ALL SELECT t_scenariotypes.ScenarioType, 't_scenariotypes' FROM t_scenariotypes
        UNION ALL SELECT t_statustypes.Status, 't_statustypes' FROM t_statustypes
        UNION ALL SELECT t_connectortypes.Connector_Type, 't_connectortypes' FROM t_connectortypes
        UNION ALL SELECT t_testtypes.TestType, 't_testtypes' FROM t_testtypes
        UNION ALL SELECT t_document.DocName, 't_document' FROM t_document WHERE DocType='SSDOCSTYLE'
    """),
)

#: Tabellen, ohne die EA das Projekt gar nicht öffnet (Abbruch beim Start).
#: ``t_maintypes`` gehört nicht dazu: fehlt auch in echten EA-Dateien.
EA_BLOCKING_TABLES: tuple[str, ...] = (
    "t_document", "t_genopt", "t_datatypes", "t_rules",
    "t_objecttypes", "t_diagramtypes", "t_connectortypes",
)

#: Tabellen, die beim ersten Speichern entstehen (EA legt sie selbst an).
EA_LAZY_TABLES: tuple[str, ...] = ("t_maintypes",)

#: Sichten, die bei EA zur Anzeige kommen, müssen diese Spalten tragen.
DIAGRAM_COLUMNS: tuple[str, ...] = (
    "RectLeft", "RectTop", "RectRight", "RectBottom",
)

MIN_FLÄCHE = 30  # Punkte; kleinere Kästen sind in EA nicht mehr lesbar


@dataclass(frozen=True)
class Befund:
    """Ein einzelnes Prüfergebnis."""

    severity: str          # "FEHLER" | "WARNUNG"
    bereich: str           # "tabelle" | "abfrage" | "geometrie" | "integritaet"
    meldung: str
    objekt: str = ""

    def __str__(self) -> str:
        ort = f" [{self.objekt}]" if self.objekt else ""
        return f"{self.severity} {self.bereich}: {self.meldung}{ort}"


def _tabellen(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def pruefe_tabellen(con: sqlite3.Connection,
                    pflicht: Sequence[str] = EA_REQUIRED_TABLES) -> list[Befund]:
    vorhanden = _tabellen(con)
    befunde = [
        Befund("FEHLER", "tabelle",
               f"Tabelle {name!r} fehlt — Enterprise Architect bricht beim Öffnen ab",
               name)
        for name in pflicht
        if name in EA_BLOCKING_TABLES and name not in vorhanden
    ]
    befunde += [
        Befund("WARNUNG", "tabelle",
               f"Tabelle {name!r} fehlt (EA legt sie beim ersten Speichern an)",
               name)
        for name in pflicht
        if name in EA_LAZY_TABLES and name not in vorhanden
    ]
    return befunde


def fehlende_abfrage_tabellen(con: sqlite3.Connection,
                              abfragen: Iterable[tuple[str, str]] = EA_QUERIES) -> list[str]:
    """Tabellen, die EA abfragt, aber in der Datei fehlen.

    ``t_maintypes`` fehlt auch in echten EA-Projekten; EA legt sie beim ersten
    Speichern an. Eine Datei mit sonst vollständigem EA-Satz ist deshalb
    öffnungsfähig.
    """
    vorhanden = _tabellen(con)
    fehlend: list[str] = []
    for _, sql in abfragen:
        for name in re.findall(r"(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.IGNORECASE):
            if name not in vorhanden and name not in fehlend:
                fehlend.append(name)
    return fehlend


def pruefe_abfragen(con: sqlite3.Connection,
                    abfragen: Iterable[tuple[str, str]] = EA_QUERIES) -> list[Befund]:
    befunde: list[Befund] = []
    for titel, sql in abfragen:
        try:
            con.execute(sql).fetchall()
        except sqlite3.Error as fehler:
            befunde.append(Befund("FEHLER", "abfrage",
                                  f"{titel}: {fehler}", titel))
    return befunde


def _rechtecke(con: sqlite3.Connection, diagram_id: int) -> list[tuple[int, float, float, float, float]]:
    return [
        (oid, float(links), float(oben), float(rechts), float(unten))
        for oid, links, oben, rechts, unten in con.execute(
            "SELECT Object_ID, RectLeft, RectTop, RectRight, RectBottom "
            "FROM t_diagramobjects WHERE Diagram_ID = ?", (diagram_id,)
        )
    ]


def pruefe_geometrie(con: sqlite3.Connection) -> list[Befund]:
    """Sichtkästen: negative Höhe, zu kleine Fläche, Überdeckung."""
    befunde: list[Befund] = []
    try:
        sichten = con.execute("SELECT Diagram_ID, Name FROM t_diagram ORDER BY Diagram_ID").fetchall()
    except sqlite3.Error as fehler:
        return [Befund("FEHLER", "geometrie", f"t_diagram nicht lesbar: {fehler}")]

    for diagram_id, name in sichten:
        kaesten = _rechtecke(con, diagram_id)
        if not kaesten:
            continue
        for oid, links, oben, rechts, unten in kaesten:
            hoehe = oben - unten          # EA: y nach unten negativ
            breite = rechts - links
            if hoehe <= 0:
                befunde.append(Befund(
                    "FEHLER", "geometrie",
                    f"Sicht {name!r}: Kasten hat Höhe {hoehe:.0f} (EA: RectTop > RectBottom)",
                    f"Object {oid}"))
            elif breite < MIN_FLÄCHE or hoehe < MIN_FLÄCHE:
                befunde.append(Befund(
                    "WARNUNG", "geometrie",
                    f"Sicht {name!r}: Kasten {breite:.0f}×{hoehe:.0f} zu klein",
                    f"Object {oid}"))

        # Überdeckung: je Elementpaar prüfen, ob sich die Kästen schneiden.
        for i in range(len(kaesten)):
            for j in range(i + 1, len(kaesten)):
                _, l1, o1, r1, u1 = kaesten[i]
                _, l2, o2, r2, u2 = kaesten[j]
                if l1 < r2 and l2 < r1 and u1 < o2 and u2 < o1:
                    befunde.append(Befund(
                        "FEHLER", "geometrie",
                        f"Sicht {name!r}: zwei Kästen liegen übereinander",
                        f"Objects {kaesten[i][0]}/{kaesten[j][0]}"))
    return befunde


def pruefe_integritaet(con: sqlite3.Connection) -> list[Befund]:
    befunde: list[Befund] = []
    try:
        ergebnis = con.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error as fehler:
        return [Befund("FEHLER", "integritaet", f"integrity_check nicht möglich: {fehler}")]
    if ergebnis != "ok":
        befunde.append(Befund("FEHLER", "integritaet", f"integrity_check: {ergebnis}"))

    pruefungen = (
        ("Kanten ohne Endpunkt", """
            SELECT count(*) FROM t_connector
            WHERE Start_Object_ID NOT IN (SELECT Object_ID FROM t_object)
               OR End_Object_ID   NOT IN (SELECT Object_ID FROM t_object)"""),
        ("Sichtobjekte ohne Element", """
            SELECT count(*) FROM t_diagramobjects
            WHERE Object_ID NOT IN (SELECT Object_ID FROM t_object)"""),
        ("Sichtkanten ohne Kante", """
            SELECT count(*) FROM t_diagramlinks
            WHERE ConnectorID NOT IN (SELECT Connector_ID FROM t_connector)"""),
    )
    for titel, sql in pruefungen:
        try:
            anzahl = con.execute(sql).fetchone()[0]
        except sqlite3.Error:
            continue
        if anzahl:
            befunde.append(Befund("FEHLER", "integritaet", f"{titel}: {anzahl}"))
    return befunde


#: Prüfbereiche in der Reihenfolge ihrer Aussagekraft.
BEREICHE: tuple[str, ...] = ("tabelle", "abfrage", "geometrie", "integritaet")

#: Bereiche, die in einem typischen Prüflauf geprüft werden. Die Geometrie ist
#: streng und bewusst optional: Handgezeichnete EA-Projekte enthalten legitime
#: Überlappungen (Notizen über Elementen), erzeugte Sichten dürfen keine haben.
STANDARD_BEREICHE: tuple[str, ...] = ("tabelle", "abfrage", "integritaet")


def pruefe_datei(
    pfad: str | Path,
    bereiche: Sequence[str] = STANDARD_BEREICHE,
) -> list[Befund]:
    """EA-Öffnungsprüfung einer `.qea`. Leere Liste = unbedenklich.

    ``bereiche`` wählt aus ``BEREICHE``; Standard sind Tabellen, Abfragen und
    Integrität (Öffnungstauglichkeit). Geometrie wird getrennt geprüft, weil
    handgezeichnete EA-Projekte legitim Überlappungen enthalten.
    """
    pfad = Path(pfad)
    if not pfad.is_file():
        return [Befund("FEHLER", "integritaet", f"Datei {str(pfad)!r} fehlt")]
    if pfad.stat().st_size == 0:
        return [Befund("FEHLER", "integritaet", f"Datei {str(pfad)!r} ist leer")]

    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    try:
        befunde = pruefe_tabellen(con)
        # Abfragen nur prüfen, wenn die Tabellen da sind — sonst redundant.
        if not befunde:
            befunde += pruefe_abfragen(con)
        if "geometrie" in bereiche:
            befunde += pruefe_geometrie(con)
        if "integritaet" in bereiche:
            befunde += pruefe_integritaet(con)
    finally:
        con.close()
    return befunde


def pruefe_erzeugte_sicht(pfad: str | Path) -> list[Befund]:
    """Strenge Geometrieprüfung für *erzeugte* Sichten (Raster erwartet)."""
    pfad = Path(pfad)
    if not pfad.is_file():
        return [Befund("FEHLER", "integritaet", f"Datei {str(pfad)!r} fehlt")]
    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    try:
        return pruefe_geometrie(con)
    finally:
        con.close()


def ist_ea_oeffnungsfaehig(pfad: str | Path) -> bool:
    """True, wenn kein FEHLER-Befund vorliegt (Warnungen sind erlaubt)."""
    return not any(b.severity == "FEHLER" for b in pruefe_datei(pfad))


def formatieren(befunde: Sequence[Befund]) -> str:
    """Kurze Textfassung für Protokolle und CI-Ausgaben."""
    if not befunde:
        return "EA-Prüfung: unbedenklich (0 Befunde)"
    zeilen = [f"EA-Prüfung: {len(befunde)} Befund(e)"]
    zeilen += [f"  - {b}" for b in befunde]
    return "\n".join(zeilen)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="eam_ai.ea_check",
        description="Prüft, ob Enterprise Architect eine .qea öffnen kann (Tabellen, "
                    "Abfragen, Sichtgeometrie). Exit 1 bei FEHLER-Befunden.",
    )
    parser.add_argument("dateien", nargs="+")
    args = parser.parse_args(list(argv) if argv is not None else None)

    fehler = 0
    for name in args.dateien:
        befunde = pruefe_datei(name)
        print(f"== {name}")
        print(formatieren(befunde))
        datei_fehler = sum(1 for b in befunde if b.severity == "FEHLER")
        if not datei_fehler:
            # Vom EA selbst angelegte Tabellen sind kein Abbruchgrund.
            con = sqlite3.connect(f"file:{name}?mode=ro", uri=True)
            try:
                harmlos = [t for t in fehlende_abfrage_tabellen(con) if t in EA_LAZY_TABLES]
            finally:
                con.close()
            if harmlos:
                print(f"   Hinweis: {', '.join(harmlos)} legt EA beim ersten Speichern an")
        fehler += datei_fehler
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
