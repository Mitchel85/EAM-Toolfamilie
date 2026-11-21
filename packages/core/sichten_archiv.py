"""Sichten-Archiv: Diagramme und Layout aus einer .qea auslagern und verlustfrei zurueckspielen.

Warum ein Archiv und kein Loeschen
----------------------------------
Sichten sind keine Kopie der Modelldaten. ``t_diagram`` traegt Name, Typ und
Diagramm-Eigenschaften, ``t_diagramobjects`` die Position und Groesse jedes
Elements auf der Flaeche, ``t_diagramlinks`` die auf der Sicht gezeichneten
Kanten samt Linienfuehrung, ``t_image`` eingebettete Bilder. Diese Information
steht nirgends sonst im Modell und laesst sich aus Elementen und Kanten NICHT
rekonstruieren.

Ein Werkzeug, das die Tabellen einfach loescht, verkleinert die Datei und
zerstoert das Layout. Dieses Modul loest das anders:

1. **archivieren** schreibt alle Sichtzeilen in eine eigene SQLite-Datei
   (plus Pruefsummen und Zaehler),
2. danach werden die Sichtzeilen in einer KOPIE der .qea geleert und die Kopie
   per ``VACUUM`` verdichtet,
3. **zurueckspielen** schreibt die Zeilen aus dem Archiv wieder in eine Kopie
   des Modells -- mit identischen IDs, also ohne Neuvergabe von Kennungen.

Die Tabellen werden geleert, nicht geloescht: AAroN fragt sie bedingungslos ab
und bricht bei einer fehlenden Tabelle mit ``SQLException`` ab.

Grenzen
-------
* Nur auf einer Kopie arbeiten; die Quelldatei wird nie beschrieben.
* Direkte Schreibzugriffe auf .qea sind von Sparx nicht freigegeben.
* Stufe A entfernt Sichtdaten und Bilder, Stufe B zusaetzlich Verbindungs-Tags
  und Diagramm-Eigenschaften aus ``t_xref``. Beides ist im Archiv gesichert.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

#: Reine Sichtdaten: Positionen, Groessen, gezeichnete Kanten, Bilder.
STUFE_A = ("t_diagramobjects", "t_diagramlinks", "t_diagram", "t_image")

#: Zusaetzliche Darstellungs-Metadaten (Verbindungs-Tags).
STUFE_B_ZUSATZ = ("t_connectortag",)

#: Zeilen in ``t_xref``, die zur Darstellung gehoeren.
XREF_DIAGRAM_TYP = "diagram properties"


def _oeffne(pfad: Path, schreibbar: bool = False) -> sqlite3.Connection:
    if schreibbar:
        return sqlite3.connect(str(pfad))
    return sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)


def _tabellen(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _spalten(conn: sqlite3.Connection, tabelle: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{tabelle}")')]


def _ddl(conn: sqlite3.Connection, tabelle: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabelle,)
    ).fetchone()
    return row[0] if row else None


def _zeilen_hash(zeilen: list[tuple]) -> str:
    """Stabiler Hash ueber eine Zeilenmenge -- Reihenfolge zaehlt nicht."""
    def norm(v):
        if isinstance(v, (bytes, bytearray, memoryview)):
            return {"blob": bytes(v).hex()}
        return v

    daten = sorted(
        json.dumps([norm(v) for v in zeile], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        for zeile in zeilen
    )
    h = hashlib.sha256()
    for d in daten:
        h.update(d.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _zaehle(conn: sqlite3.Connection, tabelle: str) -> int:
    if tabelle not in _tabellen(conn):
        return 0
    return conn.execute(f'SELECT COUNT(*) FROM "{tabelle}"').fetchone()[0]


def _sicht_tabellen(stufe: str) -> tuple[str, ...]:
    stufe = stufe.upper()
    if stufe == "A":
        return STUFE_A
    if stufe == "B":
        return STUFE_A + STUFE_B_ZUSATZ
    raise ValueError(f"Unbekannte Stufe: {stufe!r} (erlaubt: A, B)")


def _default_diagram(conn: sqlite3.Connection) -> str | None:
    if "usys_system" not in _tabellen(conn):
        return None
    row = conn.execute(
        "SELECT Value FROM usys_system WHERE Property='DefaultDiagram'"
    ).fetchone()
    return row[0] if row else None


def _setze_default_diagram(conn: sqlite3.Connection, wert: str) -> None:
    if "usys_system" not in _tabellen(conn):
        return
    vorhanden = conn.execute(
        "SELECT 1 FROM usys_system WHERE Property='DefaultDiagram'"
    ).fetchone()
    if vorhanden:
        conn.execute(
            "UPDATE usys_system SET Value=? WHERE Property='DefaultDiagram'", (wert,)
        )
    else:
        conn.execute(
            "INSERT INTO usys_system (Property, Value) VALUES ('DefaultDiagram', ?)",
            (wert,),
        )


def _sequenz_nachziehen(conn: sqlite3.Connection) -> None:
    """AUTOINCREMENT-Zaehler auf den hoechsten vorhandenen Wert heben."""
    if "sqlite_sequence" not in _tabellen(conn):
        return
    for tabelle in ("t_diagram", "t_diagramobjects"):
        if tabelle not in _tabellen(conn):
            continue
        spalte = "Diagram_ID" if tabelle == "t_diagram" else "Instance_ID"
        if spalte not in _spalten(conn, tabelle):
            continue
        maximal = conn.execute(f'SELECT COALESCE(MAX("{spalte}"), 0) FROM "{tabelle}"').fetchone()[0]
        eintrag = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name=?", (tabelle,)
        ).fetchone()
        if eintrag is None:
            conn.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (tabelle, maximal)
            )
        elif eintrag[0] < maximal:
            conn.execute(
                "UPDATE sqlite_sequence SET seq=? WHERE name=?", (maximal, tabelle)
            )


def archiviere(
    quelle: str | os.PathLike,
    archiv: str | os.PathLike,
    ziel: str | os.PathLike | None = None,
    stufe: str = "A",
) -> dict:
    """Sichtdaten aus ``quelle`` in ``archiv`` sichern und in ``ziel`` entfernen.

    ``ziel`` ist eine Kopie der Quelle ohne Sichtdaten. Wird ``ziel`` nicht
    angegeben, bleibt es bei der Archivierung -- die Quelle wird nie veraendert.
    """
    quelle, archiv = Path(quelle), Path(archiv)
    tabellen = _sicht_tabellen(stufe)  # Stufe zuerst pruefen: Fehler vor Dateizugriff
    if not quelle.is_file():
        raise FileNotFoundError(quelle)

    quelle_hash = hashlib.sha256(quelle.read_bytes()).hexdigest()
    meta: dict[str, Any] = {
        "quelle": str(quelle),
        "quelle_sha256": quelle_hash,
        "stufe": stufe.upper(),
        "tabellen": list(tabellen),
    }

    if archiv.exists():
        archiv.unlink()
    a = sqlite3.connect(str(archiv))
    try:
        a.execute("CREATE TABLE _meta (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL)")
        a.execute(
            "CREATE TABLE _zeilen (tabelle TEXT NOT NULL, anzahl INTEGER NOT NULL, "
            "sha256 TEXT NOT NULL, PRIMARY KEY (tabelle))"
        )

        q = _oeffne(quelle)
        try:
            vorhandene = _tabellen(q)
            for tabelle in tabellen:
                if tabelle not in vorhandene:
                    meta.setdefault("fehlend", []).append(tabelle)
                    continue
                ddl = _ddl(q, tabelle)
                if not ddl:
                    continue
                a.execute(ddl)
                spalten = _spalten(q, tabelle)
                sql = (
                    f'SELECT {", ".join(chr(34) + s + chr(34) for s in spalten)} '
                    f'FROM "{tabelle}"'
                )
                zeilen = q.execute(sql).fetchall()
                platzhalter = ", ".join("?" for _ in spalten)
                a.executemany(
                    f'INSERT INTO "{tabelle}" VALUES ({platzhalter})', zeilen
                )
                a.execute(
                    "INSERT INTO _zeilen (tabelle, anzahl, sha256) VALUES (?, ?, ?)",
                    (tabelle, len(zeilen), _zeilen_hash(zeilen)),
                )

            # Stufe B: nur die Darstellungs-Zeilen aus t_xref.
            if "B" == stufe.upper() and "t_xref" in vorhandene:
                ddl = _ddl(q, "t_xref")
                if ddl:
                    a.execute(ddl)
                    spalten = _spalten(q, "t_xref")
                    sql = (
                        f'SELECT {", ".join(chr(34) + s + chr(34) for s in spalten)} '
                        f'FROM t_xref WHERE Type=?'
                    )
                    zeilen = q.execute(sql, (XREF_DIAGRAM_TYP,)).fetchall()
                    platzhalter = ", ".join("?" for _ in spalten)
                    a.executemany(f'INSERT INTO "t_xref" VALUES ({platzhalter})', zeilen)
                    a.execute(
                        "INSERT INTO _zeilen (tabelle, anzahl, sha256) VALUES (?, ?, ?)",
                        ("t_xref:" + XREF_DIAGRAM_TYP, len(zeilen), _zeilen_hash(zeilen)),
                    )

            default = _default_diagram(q)
            if default is not None:
                meta["default_diagram"] = default
        finally:
            q.close()

        for k, v in meta.items():
            a.execute(
                "INSERT INTO _meta (schluessel, wert) VALUES (?, ?)",
                (k, json.dumps(v, ensure_ascii=False)),
            )
        a.commit()
    finally:
        a.close()

    ergebnis: dict[str, Any] = {
        "archiv": str(archiv),
        "archiv_bytes": archiv.stat().st_size,
        "quelle_bytes": quelle.stat().st_size,
        "stufe": stufe.upper(),
        "gesichert": {},
    }
    a = sqlite3.connect(str(archiv))
    try:
        for tabelle, anzahl, _ in a.execute(
            "SELECT tabelle, anzahl, sha256 FROM _zeilen"
        ):
            ergebnis["gesichert"][tabelle] = anzahl
    finally:
        a.close()

    if ziel is not None:
        ziel = Path(ziel)
        if ziel.exists():
            ziel.unlink()
        shutil.copy2(quelle, ziel)
        m = sqlite3.connect(str(ziel))
        try:
            vorhandene = _tabellen(m)
            for tabelle in tabellen:
                if tabelle in vorhandene:
                    m.execute(f'DELETE FROM "{tabelle}"')
            if "B" == stufe.upper() and "t_xref" in vorhandene:
                m.execute("DELETE FROM t_xref WHERE Type=?", (XREF_DIAGRAM_TYP,))
            if "default_diagram" in meta:
                _setze_default_diagram(m, "0")
            m.commit()
            m.execute("VACUUM")
            m.commit()
            # Nach dem Leeren sind die Tabellen weiterhin vorhanden (AAroN).
            ergebnis["ziel"] = str(ziel)
            ergebnis["ziel_bytes"] = ziel.stat().st_size
            ergebnis["ziel_tabellen_vorhanden"] = {
                t: (t in _tabellen(m)) for t in tabellen
            }
            ergebnis["ziel_zeilen"] = {t: _zaehle(m, t) for t in tabellen}
        finally:
            m.close()

    if ergebnis.get("quelle_bytes"):
        qb = int(ergebnis["quelle_bytes"])
        if "ziel_bytes" in ergebnis:
            zb = int(ergebnis["ziel_bytes"])
            ergebnis["ersparnis_bytes"] = qb - zb
            ergebnis["ersparnis_prozent"] = round((qb - zb) / qb * 100, 1)
    return ergebnis


def zurueckspielen(
    modell: str | os.PathLike,
    archiv: str | os.PathLike,
    ziel: str | os.PathLike,
    erzwingen: bool = False,
) -> dict:
    """Sichtzeilen aus ``archiv`` in eine Kopie von ``modell`` zurueckschreiben."""
    modell, archiv, ziel = Path(modell), Path(archiv), Path(ziel)
    if not modell.is_file() or not archiv.is_file():
        raise FileNotFoundError(modell if not modell.is_file() else archiv)

    a = sqlite3.connect(str(archiv))
    try:
        meta = {
            k: json.loads(v)
            for k, v in a.execute("SELECT schluessel, wert FROM _meta")
        }
        tabellen = [
            t for t in meta.get("tabellen", []) if t not in meta.get("fehlend", [])
        ]
        zeilen_archiv = {
            t: n for t, n in a.execute("SELECT tabelle, anzahl FROM _zeilen")
        }
    finally:
        a.close()

    if ziel.exists():
        ziel.unlink()
    shutil.copy2(modell, ziel)

    m = sqlite3.connect(str(ziel))
    try:
        vorhandene = _tabellen(m)
        for tabelle in tabellen:
            if tabelle not in vorhandene:
                raise RuntimeError(
                    f"Zieltabelle fehlt: {tabelle} -- falsches Modell oder beschädigte Datei"
                )
            ist = m.execute(f'SELECT COUNT(*) FROM "{tabelle}"').fetchone()[0]
            if ist and not erzwingen:
                raise RuntimeError(
                    f"{tabelle} enthält bereits {ist} Zeilen -- mit erzwingen=True ersetzen"
                )
            if ist and erzwingen:
                m.execute(f'DELETE FROM "{tabelle}"')

        a = sqlite3.connect(str(archiv))
        try:
            for tabelle in tabellen:
                if tabelle not in _tabellen(a):
                    continue
                spalten = _spalten(a, tabelle)
                zeilen = a.execute(
                    f'SELECT {", ".join(chr(34) + s + chr(34) for s in spalten)} '
                    f'FROM "{tabelle}"'
                ).fetchall()
                platzhalter = ", ".join("?" for _ in spalten)
                m.executemany(
                    f'INSERT INTO "{tabelle}" VALUES ({platzhalter})', zeilen
                )
            if "t_xref:diagram properties" in zeilen_archiv and "t_xref" in _tabellen(a):
                spalten = _spalten(a, "t_xref")
                zeilen = a.execute(
                    f'SELECT {", ".join(chr(34) + s + chr(34) for s in spalten)} FROM t_xref'
                ).fetchall()
                platzhalter = ", ".join("?" for _ in spalten)
                m.executemany(f'INSERT INTO "t_xref" VALUES ({platzhalter})', zeilen)
        finally:
            a.close()

        if "default_diagram" in meta:
            _setze_default_diagram(m, str(meta["default_diagram"]))
        _sequenz_nachziehen(m)
        m.commit()
        m.execute("VACUUM")
        m.commit()

        bericht: dict[str, Any] = {
            "ziel": str(ziel),
            "ziel_bytes": ziel.stat().st_size,
            "zeilen": {},
            "pruefsummen": {},
        }
        a = sqlite3.connect(str(archiv))
        try:
            soll = {t: h for t, h in a.execute("SELECT tabelle, sha256 FROM _zeilen")}
        finally:
            a.close()
        for tabelle in tabellen:
            if tabelle not in _tabellen(m):
                continue
            spalten = _spalten(m, tabelle)
            zeilen = m.execute(
                f'SELECT {", ".join(chr(34) + s + chr(34) for s in spalten)} '
                f'FROM "{tabelle}"'
            ).fetchall()
            ist_hash = _zeilen_hash(zeilen)
            bericht["zeilen"][tabelle] = len(zeilen)
            bericht["pruefsummen"][tabelle] = {
                "soll": soll.get(tabelle),
                "ist": ist_hash,
                "gleich": soll.get(tabelle) == ist_hash,
            }

        # Stufe B: auch die zurueckgeschriebenen t_xref-Zeilen gegenpruefen.
        xref_key = "t_xref:" + XREF_DIAGRAM_TYP
        if xref_key in soll and "t_xref" in _tabellen(m):
            spalten = _spalten(m, "t_xref")
            zeilen = m.execute(
                f'SELECT {", ".join(chr(34) + s + chr(34) for s in spalten)} '
                f"FROM t_xref WHERE Type=?",
                (XREF_DIAGRAM_TYP,),
            ).fetchall()
            ist_hash = _zeilen_hash(zeilen)
            bericht["zeilen"][xref_key] = len(zeilen)
            bericht["pruefsummen"][xref_key] = {
                "soll": soll.get(xref_key),
                "ist": ist_hash,
                "gleich": soll.get(xref_key) == ist_hash,
            }
        bericht["identisch"] = all(
            v["gleich"] for v in bericht["pruefsummen"].values()
        )
        return bericht
    finally:
        m.close()


def pruefe(archiv: str | os.PathLike) -> dict:
    """Archiv gegen sich selbst pruefen (Zaehler, Lesbarkeit, Soll-Hashes)."""
    archiv = Path(archiv)
    if not archiv.is_file():
        raise FileNotFoundError(archiv)
    a = sqlite3.connect(str(archiv))
    try:
        meta = {k: json.loads(v) for k, v in a.execute("SELECT schluessel, wert FROM _meta")}
        bericht: dict[str, Any] = {"archiv": str(archiv), "meta": meta, "tabellen": {}}
        for tabelle, anzahl, soll in a.execute("SELECT tabelle, anzahl, sha256 FROM _zeilen"):
            name = tabelle.split(":")[0]
            if name not in _tabellen(a):
                bericht["tabellen"][tabelle] = {"fehlt": True}
                continue
            spalten = _spalten(a, name)
            sql = f'SELECT {", ".join(chr(34) + s + chr(34) for s in spalten)} FROM "{name}"'
            parameter: tuple = ()
            if ":" in tabelle:
                sql += " WHERE Type=?"
                parameter = (tabelle.split(":", 1)[1],)
            zeilen = a.execute(sql, parameter).fetchall()
            ist = _zeilen_hash(zeilen)
            bericht["tabellen"][tabelle] = {
                "zeilen": len(zeilen),
                "soll_zeilen": anzahl,
                "hash_gleich": ist == soll,
            }
        bericht["ok"] = all(
            v.get("hash_gleich") and v.get("zeilen") == v.get("soll_zeilen")
            for v in bericht["tabellen"].values()
        )
        return bericht
    finally:
        a.close()


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="sichten-archiv",
        description="Sichten und Layout aus einer .qea auslagern und verlustfrei zurueckspielen.",
    )
    sub = p.add_subparsers(dest="befehl", required=True)

    pa = sub.add_parser("archivieren", help="Sichtdaten sichern und aus einer Kopie entfernen")
    pa.add_argument("quelle")
    pa.add_argument("archiv")
    pa.add_argument("--ziel", help="Kopie ohne Sichtdaten (optional)")
    pa.add_argument("--stufe", choices=("A", "B"), default="A")

    pz = sub.add_parser("zurueckspielen", help="Sichtdaten aus dem Archiv wieder einsetzen")
    pz.add_argument("modell")
    pz.add_argument("archiv")
    pz.add_argument("ziel")
    pz.add_argument("--erzwingen", action="store_true")

    pp = sub.add_parser("pruefen", help="Archiv pruefen")
    pp.add_argument("archiv")

    args = p.parse_args(argv)
    if args.befehl == "archivieren":
        print(json.dumps(archiviere(args.quelle, args.archiv, args.ziel, args.stufe),
                         indent=2, ensure_ascii=False))
    elif args.befehl == "zurueckspielen":
        print(json.dumps(zurueckspielen(args.modell, args.archiv, args.ziel, args.erzwingen),
                         indent=2, ensure_ascii=False))
    else:
        print(json.dumps(pruefe(args.archiv), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
