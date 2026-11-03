"""struktur.py -- Prüfer für die Paket- und Sichtenstruktur nach Leitfaden.

Was hier geprüft wird
---------------------
Der MDG-Prüfer (``validator.py``) kennt nur Stereotype und Kantenendpunkte.
Der Leitfaden verlangt mehr und anderes:

* die übergreifende Paketstruktur (Abbildung 1 und die Konventionen
  ``xx-MK01``),
* je Viewpoint ein Diagramm mit festgelegtem Typ und festgelegtem Namen
  ("A1 : Projektkürzel : Meta-Data Definitions"),
* die Startseite als Standarddiagramm,
* beschreibende Notizen an jedem Element (VÜ-MK01).

Dieser Prüfer liest entweder ein IR oder eine geschriebene ``.qea`` und
liefert Findings im selben Format wie ``validator.py`` -- damit man beide
Berichte zusammen auswerten kann.

Grundsatz: Jede Meldung nennt die Konvention (``A1-MK02``) und den Stand des
Leitfadens. Wer eine Abweichung verteidigen will, muss sie gegen die zitierte
Stelle begründen -- nicht gegen dieses Programm.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import leitfaden

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: Elemente, deren Notiz fehlen darf (Leitfaden VÜ-MK01: "Typen").
OHNE_NOTIZ_ERLAUBT = frozenset({"Asset", "AssetRole", "ResourceRole", "OperationalRole",
                               "ServiceSpecificationRole", "ProjectPhaseRole"})


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    object: str
    message: str
    code: str = ""

    def as_json(self) -> dict[str, str]:
        return {
            "check": self.check,
            "severity": self.severity,
            "object": self.object,
            "message": self.message,
            "code": self.code,
        }


def _add(out: list[Finding], severity: str, check: str, obj: str, message: str, code: str = "") -> None:
    out.append(Finding(check=check, severity=severity, object=obj, message=message, code=code))


# ---------------------------------------------------------------------------
# Einlesen: IR oder .qea
# ---------------------------------------------------------------------------


def from_ir(ir: Mapping[str, Any]) -> dict[str, Any]:
    packages = []
    for entry in ir.get("packages") or ():
        if isinstance(entry, Mapping):
            packages.append(
                {
                    "path": str(entry.get("path") or ""),
                    "stereotype": str(entry.get("stereotype") or ""),
                    "notes": str(entry.get("notes") or ""),
                }
            )
    elements = []
    for entry in ir.get("elements") or ():
        if isinstance(entry, Mapping):
            elements.append(
                {
                    "package": str(entry.get("package") or ""),
                    "name": str(entry.get("name") or ""),
                    "stereotype": str(entry.get("stereotype") or ""),
                    "ea_type": str(entry.get("ea_type") or "Class"),
                    "notes": str(entry.get("notes") or ""),
                }
            )
    return {
        "packages": packages,
        "elements": elements,
        "diagrams": [dict(d) for d in ir.get("diagrams") or () if isinstance(d, Mapping)],
    }


def from_qea(path: str | Path) -> dict[str, Any]:
    """Modell aus einer geschriebenen .qea lesen (nur lesend)."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    con = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        rows = cur.execute(
            "SELECT Package_ID, Name, Parent_ID, Notes, ea_guid FROM t_package"
        ).fetchall()
        by_id = {row[0]: row for row in rows}

        def path_of(package_id: int) -> str:
            parts: list[str] = []
            current = package_id
            seen: set[int] = set()
            while current and current in by_id and current not in seen:
                seen.add(current)
                parts.append(str(by_id[current][1] or ""))
                current = by_id[current][2]
            return "/".join(reversed(parts))

        packages = [
            {"path": path_of(row[0]), "notes": str(row[3] or ""), "guid": str(row[4] or "")}
            for row in rows
        ]
        # Paketstereotyp steht in t_xref (element property) am Paket-GUID.
        stereo: dict[str, str] = {}
        for client, description in cur.execute(
            "SELECT Client, Description FROM t_xref WHERE Name='Stereotypes'"
        ):
            if description and "@STEREO;" in description:
                name = ""
                for token in str(description).split(";"):
                    if token.startswith("Name="):
                        name = token.split("=", 1)[1]
                        break
                if name:
                    stereo[str(client or "")] = name
        for package in packages:
            package["stereotype"] = stereo.get(package.get("guid", ""), "")

        elements: list[dict[str, Any]] = []
        for obj_id, name, object_type, note, stereotype, package_id in cur.execute(
            "SELECT Object_ID, Name, Object_Type, Note, Stereotype, Package_ID FROM t_object "
            "WHERE Object_Type <> 'Package'"
        ):
            elements.append(
                {
                    "package": path_of(int(package_id or 0)),
                    "name": str(name or ""),
                    "stereotype": str(stereotype or ""),
                    "ea_type": str(object_type or ""),
                    "notes": str(note or ""),
                }
            )
        default_id = str(_model_default(cur) or "")
        mitglieder: dict[int, int] = {}
        for diagram_id, count in cur.execute(
            "SELECT Diagram_ID, COUNT(*) FROM t_diagramobjects GROUP BY Diagram_ID"
        ):
            mitglieder[int(diagram_id)] = int(count)
        # Die tatsaechlichen Verweise je Sicht -- fuer Pruefungen, die nicht
        # nur die Anzahl brauchen (z. B. St-MK05: Viewpoints auf der
        # Startseite). Der Writer legt je Mitglied eine Zeile in
        # t_diagramobjects ab; Object_ID zeigt auf t_object.
        member_refs: dict[int, list[str]] = {}
        for diagram_id, paket_id, name in cur.execute(
            "SELECT d.Diagram_ID, o.Package_ID, o.Name "
            "FROM t_diagramobjects d JOIN t_object o ON o.Object_ID = d.Object_ID"
        ):
            member_refs.setdefault(int(diagram_id), []).append(
                f"{path_of(int(paket_id or 0))}::{name}"
            )
        diagrams: list[dict[str, Any]] = []
        for diagram_id, package_id, name, diagram_type, style_ex, show_details in cur.execute(
            "SELECT Diagram_ID, Package_ID, Name, Diagram_Type, StyleEx, ShowDetails FROM t_diagram"
        ):
            mdg = ""
            for part in str(style_ex or "").split(";"):
                if part.startswith("MDGDgm="):
                    mdg = part.split("=", 1)[1]
                    break
            diagrams.append(
                {
                    "name": str(name or ""),
                    "type": str(diagram_type or ""),
                    "mdg": mdg,
                    "package": path_of(int(package_id or 0)),
                    "default": (str(diagram_id) == default_id) or bool(show_details),
                    "members": mitglieder.get(int(diagram_id), 0),
                    "member_refs": member_refs.get(int(diagram_id), []),
                }
            )
        return {"packages": packages, "elements": elements, "diagrams": diagrams}
    finally:
        con.close()


def _model_default(cur: sqlite3.Cursor) -> str:
    """Kennung des Standarddiagramms (Startseite), falls gesetzt."""
    try:
        row = cur.execute(
            "SELECT Value FROM usys_system WHERE Property='DefaultDiagram'"
        ).fetchone()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row and row[0] is not None else ""


# ---------------------------------------------------------------------------
# Prüfungen
# ---------------------------------------------------------------------------



def _diagrammtyp_passt(gefuehrt: str, mdg: str) -> bool:
    """Verlangter Viewpoint-Name im MDG-Wert enthalten (robust gegen Plural-s)?"""
    if gefuehrt in mdg:
        return True
    def stamm(text: str) -> str:
        return leitfaden.normiere(text).replace("requirements", "requirement")
    return stamm(gefuehrt) in stamm(mdg)



def _match_path(actual: str, wanted: str) -> bool:
    return leitfaden.normiere(actual) == leitfaden.normiere(wanted)


def _match_suffix(actual: str, wanted: str) -> bool:
    """Pfad entspricht, wenn der *Ende* übereinstimmt.

    Der Leitfaden nennt Pakete ohne Projektwurzel
    (``Architecture Foundation/A1/Meta-Data Definitions``); im Modell stehen
    sie unter ``<Projekt> - Projektarchitektur/...``. Verglichen wird deshalb
    der Pfad ab dem ersten gemeinsamen Perspektivnamen.
    """
    a = leitfaden.normiere(actual)
    w = leitfaden.normiere(wanted)
    return a == w or a.endswith("/" + w)


def check_packages(model: Mapping[str, Any], projekt: str) -> list[Finding]:
    """Pflichtpakete des Leitfadens vorhanden? (xx-MK01)"""
    out: list[Finding] = []
    vorhanden = [str(p.get("path") or "") for p in model.get("packages") or ()]
    for rule in leitfaden.PACKAGES:
        wanted = leitfaden.expand_projekt(rule.path, projekt)
        if not any(_match_path(path, wanted) or _match_suffix(path, wanted) for path in vorhanden):
            _add(
                out,
                ERROR,
                "missingPackage",
                wanted,
                f"Paket '{wanted}' fehlt. Der Leitfaden {leitfaden.LEITFADEN_VERSION} "
                f"verlangt es in Konvention {rule.code}.",
                rule.code,
            )
    return out


def check_diagrams(model: Mapping[str, Any], projekt: str) -> list[Finding]:
    """Pflichtdiagramme: Name und Typ je Viewpoint (xx-MK02 ff.)."""
    out: list[Finding] = []
    diagrams = [d for d in model.get("diagrams") or () if isinstance(d, Mapping)]
    for rule in leitfaden.required_diagrams(projekt):
        wanted_name = rule["name"]
        treffer = [d for d in diagrams if leitfaden.normiere(str(d.get("name") or "")) == leitfaden.normiere(wanted_name)]
        if not treffer:
            _add(
                out,
                ERROR,
                "missingDiagram",
                wanted_name,
                f"Diagramm '{wanted_name}' fehlt (Typ '{rule['type']}', Paket '{rule['package']}'). "
                f"Konvention {rule['code']}.",
                rule["code"],
            )
            continue
        diagram = treffer[0]
        mdg = str(diagram.get("mdg") or "")
        # Die MDG schreibt einzelne Viewpoints abweichend vom Leitfaden
        # ("Requirement Dependencies" statt "Requirements Dependencies").
        # Verglichen wird deshalb ohne Plural-s am Wortstamm.
        # MDGDgm = "<Profil>::<Viewpoint>"; verglichen wird nur der Viewpoint.
        if mdg and not _diagrammtyp_passt(rule["type"], mdg.split("::")[-1].strip()):
            _add(
                out,
                WARNING,
                "diagramTypeMismatch",
                wanted_name,
                f"Diagramm '{wanted_name}' hat den MDG-Viewpoint '{mdg}', "
                f"der Leitfaden verlangt '{rule['type']}'.",
                rule["code"],
            )
    return out


def check_startseite(model: Mapping[str, Any], projekt: str) -> list[Finding]:
    """St-MK03: Startseite ist Standarddiagramm; St-MK05: Viewpoints auf der Startseite."""
    out: list[Finding] = []
    name = f"Startseite {projekt}"
    treffer = [d for d in model.get("diagrams") or ()
               if leitfaden.normiere(str(d.get("name") or "")) == leitfaden.normiere(name)]
    if not treffer:
        return out  # fehlendes Diagramm meldet bereits check_diagrams
    if not any(bool(d.get("default")) for d in treffer):
        _add(
            out,
            WARNING,
            "startseiteNichtStandard",
            name,
            f"'{name}' ist nicht als Standarddiagramm (model default) gesetzt (Konvention St-MK03).",
            "St-MK03",
        )
    start_package = f"{projekt} - Startseite"
    views = [
        e for e in model.get("elements") or ()
        if str(e.get("stereotype") or "") == "Viewpoint"
        and _match_path(str(e.get("package") or ""), start_package)
    ]
    if not views:
        # A2-MK05 laesst zu, Viewpoints aus dem Katalog zu entnehmen statt sie
        # im Startseiten-Paket anzulegen. Dann stehen sie als Verweis auf der
        # Sicht -- das erfuellt St-MK05 genauso.
        elemente = {
            (str(e.get("package") or ""), str(e.get("name") or ""))
            for e in model.get("elements") or ()
            if str(e.get("stereotype") or "") == "Viewpoint"
        }
        for diagram in treffer:
            for ref in diagram.get("member_refs") or ():
                paket, _, name = str(ref).rpartition("::")
                if (paket, name) in elemente:
                    views.append({"name": name})
                    break
    if not views:
        _add(
            out,
            WARNING,
            "startseiteOhneViewpoints",
            name,
            f"Auf der Startseite fehlen die Viewpoints (Konvention St-MK05).",
            "St-MK05",
        )
    return out


def check_diagram_members(model: Mapping[str, Any]) -> list[Finding]:
    """Eine Sicht, die nichts zeigt, ist keine Sicht.

    Der Leitfaden verlangt je Diagramm "die Darstellung der ..." (z. B.
    A1-MK02). Ein leeres Diagramm erfüllt den Namen, nicht den Zweck.
    """
    out: list[Finding] = []
    for diagram in model.get("diagrams") or ():
        if not isinstance(diagram, Mapping):
            continue
        if "members" not in diagram:
            continue  # IR-Modell ohne Mitgliederzahlen: nicht bewertbar
        if int(diagram.get("members") or 0) > 0:
            continue
        _add(
            out,
            WARNING,
            "emptyDiagram",
            str(diagram.get("name") or ""),
            f"Sicht '{diagram.get('name')}' hat keine Elemente. Eine Sicht ohne Inhalt "
            f"erfüllt den Zweck des Viewpoints nicht.",
        )
    return out


def check_notes(model: Mapping[str, Any]) -> list[Finding]:
    """VÜ-MK01: jedes Element trägt eine Beschreibung im Notes-Feld."""
    out: list[Finding] = []
    for element in model.get("elements") or ():
        stereotype = str(element.get("stereotype") or "").strip()
        if not stereotype or stereotype in OHNE_NOTIZ_ERLAUBT:
            continue
        if str(element.get("ea_type") or "") == "Note":
            continue
        if str(element.get("notes") or "").strip():
            continue
        _add(
            out,
            ERROR,
            "missingNotes",
            f"{element.get('package')}::{element.get('name')}",
            f"Element '{element.get('name')}' ({stereotype}) hat keine Beschreibung "
            f"im Notes-Feld (Konvention VÜ-MK01).",
            "VÜ-MK01",
        )
    return out


def check_viewpoint_catalog(model: Mapping[str, Any], projekt: str) -> list[Finding]:
    """Konventionen verlangen Viewpoints "aus dem Modellelementekatalog"."""
    out: list[Finding] = []
    katalog = [e for e in model.get("elements") or ()
               if "Modellelementekatalog" in str(e.get("package") or "")]
    if not katalog:
        _add(
            out,
            WARNING,
            "catalogMissing",
            "Modellelementekatalog",
            "Es gibt keinen Modellelementekatalog. Die Konventionen (z. B. St-MK05, A1-MK11, "
            "C1-MK05) entnehmen Elemente ausdrücklich daraus.",
            "St-MK05",
        )
        return out
    stereotypes = {str(e.get("stereotype") or "") for e in katalog}
    for pflicht in ("Viewpoint", "View", "Classification"):
        if pflicht not in stereotypes:
            _add(
                out,
                WARNING,
                "catalogIncomplete",
                f"Modellelementekatalog::{pflicht}",
                f"Im Modellelementekatalog fehlt der Stereotyp '{pflicht}'.",
                "St-MK05",
            )
    return out


def check_viewpoint_coverage(model: Mapping[str, Any]) -> list[Finding]:
    """Jeder Viewpoint des Registers soll ein eigenes Viewpoint-Element haben."""
    out: list[Finding] = []
    namen = [
        str(e.get("name") or "")
        for e in model.get("elements") or ()
        if str(e.get("stereotype") or "") == "Viewpoint"
    ]
    for rule in leitfaden.DIAGRAMS:
        if not any(_diagrammtyp_passt(rule.diagram_type, name) for name in namen):
            _add(
                out,
                INFO,
                "viewpointElementMissing",
                rule.diagram_type,
                f"Kein Viewpoint-Element '{rule.diagram_type}' (Konvention {rule.code}).",
                rule.code,
            )
    return out


def validate(model: Mapping[str, Any], projekt: str) -> list[Finding]:
    """Alle Leitfaden-Prüfungen in einem Lauf."""
    findings: list[Finding] = []
    findings.extend(check_packages(model, projekt))
    findings.extend(check_diagrams(model, projekt))
    findings.extend(check_startseite(model, projekt))
    findings.extend(check_notes(model))
    findings.extend(check_diagram_members(model))
    findings.extend(check_viewpoint_catalog(model, projekt))
    findings.extend(check_viewpoint_coverage(model))
    return findings


def summary(findings: Sequence[Finding]) -> dict[str, int]:
    counts = {ERROR: 0, WARNING: 0, INFO: 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def render(findings: Sequence[Finding], limit: int = 40) -> str:
    counts = summary(findings)
    lines = [
        f"{leitfaden.LEITFADEN_TITEL} {leitfaden.LEITFADEN_VERSION} "
        f"({leitfaden.LEITFADEN_STAND}): "
        f"{counts[ERROR]} Fehler, {counts[WARNING]} Warnungen, {counts[INFO]} Hinweise",
    ]
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    for finding in sorted(findings, key=lambda f: (order.get(f.severity, 9), f.code, f.object))[:limit]:
        code = f"[{finding.code}] " if finding.code else ""
        lines.append(f"  {finding.severity:7s} {code}{finding.message}")
    if len(findings) > limit:
        lines.append(f"  ... {len(findings) - limit} weitere")
    return "\n".join(lines)
