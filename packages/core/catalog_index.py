"""Standard-Elementekatalog (StEKa / Modellelementekatalog) als Nachschlagewerk.

Der Katalog liegt als ``.qea`` vor -- in der Musterarchitektur unter
``Modellelementekatalog``, je Stereotyp ein Unterpaket, die Elemente mit fester
``ea_guid``. Dieses Modul liest ihn nur und ordnet Elemente aus einem Lauf den
Katalogeintraegen zu.

Leitregel: Eine Katalog-Kennung wird nie berechnet, nur nachgeschlagen und
woertlich uebernommen. Berechnet wird ausschliesslich fuer neue Elemente, die
im Katalog nicht vorkommen.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = ["Catalog", "CatalogEntry", "CatalogError"]


class CatalogError(Exception):
    """Katalog nicht lesbar oder ohne verwertbare Elemente."""


def _norm(text: Any) -> str:
    """Vergleichsform: Unicode NFC, getrimmt, Mehrfach-Leerzeichen, kleingeschrieben."""
    value = unicodedata.normalize("NFC", str(text or ""))
    return " ".join(value.split()).casefold()


#: NATO-/ADMBw-/StEKa-Identitaets- und Standardelement-Tags, die beim
#: Wiederverwenden aus dem Katalog immer erhalten bleiben muessen.
IDENTITY_TAGS: frozenset[str] = frozenset(
    {
        "OriginalGUID",
        "URI",
        "Uuid",
        "UUID",
        "StandardElement",
        "ElementOwner",
        "ElementStatus",
        "ValidatedBy",
        "ValidatedOn",
        "ValidFrom",
        "ValidUntil",
        "Herkunft",
    }
)


def _parse_custom_props(description: str) -> dict[str, str]:
    """Extrahiert ``@PROP=@NAME=...@ENDNAME;...@VALU=...@ENDVALU;...@ENDPROP;``."""
    out: dict[str, str] = {}
    for block in str(description or "").split("@ENDPROP;"):
        if "@NAME=" not in block:
            continue
        name = block.split("@NAME=", 1)[1].split("@ENDNAME;", 1)[0].strip()
        value = ""
        if "@VALU=" in block:
            value = block.split("@VALU=", 1)[1].split("@ENDVALU;", 1)[0]
        if name:
            out[name] = value
    return out


@dataclass(frozen=True)
class CatalogEntry:
    """Ein Katalogelement: Name, Stereotyp, Kennung, Heimatpaket und Metadaten."""

    name: str
    stereotype: str
    guid: str
    package: str
    ea_type: str = "Class"
    notes: str = ""
    alias: str = ""
    status: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    xref_tags: dict[str, str] = field(default_factory=dict)


@dataclass
class Catalog:
    """Nachschlagewerk ueber die Standardelemente eines Katalogs."""

    entries: list[CatalogEntry] = field(default_factory=list)
    connectors: list[dict[str, Any]] = field(default_factory=list)
    _by_name: dict[str, list[CatalogEntry]] = field(default_factory=dict, repr=False)
    _by_key: dict[tuple[str, str], CatalogEntry] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for entry in self.entries:
            key = (_norm(entry.name), _norm(entry.stereotype))
            self._by_key.setdefault(key, entry)
            self._by_name.setdefault(_norm(entry.name), []).append(entry)

    def __len__(self) -> int:
        return len(self.entries)

    # ------------------------------------------------------------------ lesen
    @classmethod
    def from_qea(cls, path: str | Path) -> "Catalog":
        """Liest den Katalog aus einer ``.qea`` (nur ``t_package``/``t_object``)."""
        pfad = Path(path)
        if not pfad.is_file():
            raise CatalogError(f"{pfad}: Katalog nicht gefunden")
        con = sqlite3.connect(str(pfad))
        con.execute("PRAGMA query_only = ON")
        try:
            pakete = {
                int(pid): str(name or "")
                for pid, name in con.execute("select Package_ID, Name from t_package")
            }
            eltern = {
                int(pid): int(parent or 0)
                for pid, parent in con.execute("select Package_ID, Parent_ID from t_package")
            }

            def pfad_von(pid: int) -> str:
                teile: list[str] = []
                seen: set[int] = set()
                while pid and pid not in seen:
                    seen.add(pid)
                    name = pakete.get(pid)
                    if name:
                        teile.append(name)
                    pid = eltern.get(pid, 0)
                return "/".join(reversed(teile))

            # Optionale Tabellen fuer Tagged Values, CustomProperties und Taxonomie-Kanten
            tabellen = {
                str(r[0]).lower(): str(r[0])
                for r in con.execute("select name from sqlite_master where type='table'")
            }
            tags_by_oid: dict[int, dict[str, str]] = {}
            if "t_objectproperties" in tabellen:
                for oid, prop, val in con.execute(
                    f'select Object_ID, Property, Value from "{tabellen["t_objectproperties"]}"'
                ):
                    p_str = str(prop or "").strip()
                    if oid and p_str:
                        tags_by_oid.setdefault(int(oid), {})[p_str] = str(val if val is not None else "")
            xref_by_guid: dict[str, dict[str, str]] = {}
            if "t_xref" in tabellen:
                for name_col, desc_col, client_col in con.execute(
                    f'select Name, Description, Client from "{tabellen["t_xref"]}"'
                ):
                    if str(name_col or "").strip() == "CustomProperties" and client_col:
                        parsed = _parse_custom_props(str(desc_col or ""))
                        if parsed:
                            xref_by_guid.setdefault(str(client_col).strip().upper(), {}).update(parsed)

            obj_cols = {
                str(r[1]).lower(): str(r[1])
                for r in con.execute("PRAGMA table_info(t_object)")
            }
            note_col = obj_cols.get("note") or obj_cols.get("notes") or "Note"
            alias_col = obj_cols.get("alias")
            status_col = obj_cols.get("status")
            select_sql = (
                f"select Object_ID, Name, Stereotype, Object_Type, ea_guid, Package_ID, "
                f"{note_col}, "
                f"{alias_col if alias_col else 'NULL'}, "
                f"{status_col if status_col else 'NULL'} "
                f"from t_object where Object_Type <> 'Package' and Name is not null and Name <> ''"
            )

            eintraege: list[CatalogEntry] = []
            oid_to_entry: dict[int, CatalogEntry] = {}
            for oid, name, stereotype, obj_type, guid, package_id, notes, alias, status in con.execute(
                select_sql
            ):
                guid_text = str(guid or "").strip()
                if not guid_text:
                    continue
                oid_int = int(oid or 0)
                entry = CatalogEntry(
                    name=str(name).strip(),
                    stereotype=str(stereotype or "").strip(),
                    # Woertlich: die Kennung wird nachgeschlagen, nicht
                    # normalisiert. Eine geaenderte Schreibweise ist fuer den
                    # Versionsabgleich eine andere Kennung.
                    guid=guid_text,
                    package=pfad_von(int(package_id or 0)),
                    ea_type=str(obj_type or "Class").strip() or "Class",
                    notes=str(notes or ""),
                    alias=str(alias or ""),
                    status=str(status or ""),
                    tags=dict(tags_by_oid.get(oid_int, {})),
                    xref_tags=dict(xref_by_guid.get(guid_text.upper(), {})),
                )
                eintraege.append(entry)
                if oid_int:
                    oid_to_entry[oid_int] = entry

            kanten: list[dict[str, Any]] = []
            if "t_connector" in tabellen and oid_to_entry:
                for cid, start_oid, end_oid, c_type, c_stereo, c_name, c_notes, c_guid in con.execute(
                    f'select Connector_ID, Start_Object_ID, End_Object_ID, Connector_Type, '
                    f'Stereotype, Name, Notes, ea_guid from "{tabellen["t_connector"]}"'
                ):
                    s_entry = oid_to_entry.get(int(start_oid or 0))
                    t_entry = oid_to_entry.get(int(end_oid or 0))
                    if s_entry is None or t_entry is None:
                        continue
                    kanten.append(
                        {
                            "source_guid": s_entry.guid,
                            "target_guid": t_entry.guid,
                            "source": f"{s_entry.package}::{s_entry.name}" if s_entry.package else s_entry.name,
                            "target": f"{t_entry.package}::{t_entry.name}" if t_entry.package else t_entry.name,
                            "ea_type": str(c_type or "Dependency").strip() or "Dependency",
                            "stereotype": str(c_stereo or "").strip(),
                            "name": str(c_name or "").strip(),
                            "notes": str(c_notes or ""),
                            "guid": str(c_guid or "").strip(),
                        }
                    )
        except sqlite3.Error as error:
            raise CatalogError(f"{pfad}: Katalog nicht lesbar ({error})") from error
        finally:
            con.close()
        if not eintraege:
            raise CatalogError(f"{pfad}: keine Elemente im Katalog")
        return cls(eintraege, connectors=kanten)

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[Mapping[str, Any]],
        *,
        connectors: Iterable[Mapping[str, Any]] = (),
    ) -> "Catalog":
        """Baut den Katalog aus einfachen Datensaetzen (z. B. JSON im Browser)."""
        gelesen = [
            CatalogEntry(
                name=str(item.get("name") or "").strip(),
                stereotype=str(item.get("stereotype") or "").strip(),
                guid=str(item.get("guid") or "").strip(),
                package=str(item.get("package") or "").strip(),
                ea_type=str(item.get("ea_type") or "Class").strip() or "Class",
                notes=str(item.get("notes") or ""),
                alias=str(item.get("alias") or ""),
                status=str(item.get("status") or ""),
                tags=dict(item.get("tags") or {}),
                xref_tags=dict(item.get("xref_tags") or {}),
            )
            for item in entries
        ]
        gelesen = [eintrag for eintrag in gelesen if eintrag.name and eintrag.guid]
        if not gelesen:
            raise CatalogError("Katalog ohne verwertbare Elemente")
        return cls(gelesen, connectors=[dict(c) for c in connectors])

    # -------------------------------------------------------------- nachschlagen
    def lookup(self, name: str, stereotype: str = "") -> CatalogEntry | None:
        """Sucht ein Element. Mehrdeutige Namen brauchen den Stereotyp."""
        schluessel = _norm(name)
        if not schluessel:
            return None
        if stereotype:
            treffer = self._by_key.get((schluessel, _norm(stereotype)))
            if treffer is not None:
                return treffer
        kandidaten = self._by_name.get(schluessel, [])
        if len(kandidaten) == 1:
            return kandidaten[0]
        if not kandidaten:
            # Zweiter Versuch ohne Stereotyp: haeufig weicht nur die Schreibweise ab.
            return None
        return None

    def inventory(self, limit: int = 400) -> str:
        """Kommentarzeilen fuer den Prompt: die Standardelemente beim Namen nennen."""
        if not self.entries:
            return ""
        zeilen = []
        for eintrag in sorted(self.entries, key=lambda e: (e.stereotype, e.name))[:limit]:
            zeilen.append(f"- {eintrag.name} «{eintrag.stereotype}» ({eintrag.package})")
        rest = len(self.entries) - len(zeilen)
        kopf = (
            "STANDARDELEMENTE AUS DEM KATALOG (diese Namen unveraendert verwenden, "
            "keine neuen Schreibweisen erfinden):"
        )
        return kopf + "\n" + "\n".join(zeilen) + (f"\n… (+{rest} weitere)" if rest > 0 else "")

    # ------------------------------------------------------------------ anwenden
    def apply(self, ir: dict[str, Any]) -> dict[str, int]:
        """Ordnet die Elemente eines IR dem Katalog zu (in place).

        Getroffene Elemente uebernehmen Kennung, Stereotyp und Heimatpaket des
        Katalogs; ihre Paketkette wird im IR ergaenzt. Nicht getroffene Elemente
        bleiben unveraendert -- sie sind neu und werden spaeter abgeleitet.
        """
        elemente = ir.get("elements") or []
        pakete = ir.setdefault("packages", [])
        vorhanden = {str(p.get("path") or "") for p in pakete if isinstance(p, dict)}
        zaehler = {"katalog": 0, "neu": 0, "pakete": 0}

        def _normalisiere_katalogpfad(pfad: str) -> str:
            """Entfernt eine fremde Projektwurzel vor ``Modellelementekatalog``.

            Steht der Katalog in einer Projektdatei (z. B. ``MASC``) unter
            ``<Fremd>/Modellelementekatalog/...`` oder ``<Fremd>/...`` und gibt
            es im Ziel bereits ``StEKa``, darf das fremde Wurzelpaket nicht ins
            Zielmodell kopiert werden -- sonst liegt neben der gebauten
            Architektur eine fremde Projektwurzel (MASC-Bug).
            """
            teile = [teil for teil in str(pfad).split("/") if teil]
            if not teile or "StEKa" not in vorhanden or teile[0] in vorhanden:
                return pfad
            if "Modellelementekatalog" in teile:
                idx = teile.index("Modellelementekatalog")
                rest = teile[idx + 1 :]
                return "/".join(["StEKa", *rest]) if rest else "StEKa"
            return "/".join(["StEKa", *teile[1:]]) if len(teile) > 1 else "StEKa"

        def paket_ergaenzen(pfad: str) -> None:
            teile = [teil for teil in str(pfad).split("/") if teil]
            for index in range(1, len(teile) + 1):
                pfad_teil = "/".join(teile[:index])
                if pfad_teil and pfad_teil not in vorhanden:
                    pakete.append({"path": pfad_teil})
                    vorhanden.add(pfad_teil)
                    zaehler["pakete"] += 1

        #: Name -> neuer Paketpfad; Grundlage fuer die Kantenreparatur.
        umgehaengt: dict[str, str] = {}
        # Ein Name+Stereotyp darf nur einmal die Katalogkennung bekommen.
        # Sonst tragen zwei Elemente (z. B. ein Katalog- und ein Geruestelement
        # "OFFEN") dieselbe GUID, und der Writer bricht bei t_xref ab.
        gesehen: set[tuple[str, str]] = set()
        for element in elemente:
            if not isinstance(element, dict):
                continue
            key = (_norm(element.get("name")), _norm(element.get("stereotype")))
            if key in gesehen:
                zaehler["neu"] += 1
                continue
            gesehen.add(key)
            treffer = self.lookup(str(element.get("name") or ""), str(element.get("stereotype") or ""))
            if treffer is None:
                zaehler["neu"] += 1
                continue
            alt = str(element.get("package") or "")
            element["guid"] = treffer.guid
            element["stereotype"] = treffer.stereotype or element.get("stereotype") or ""
            if treffer.ea_type and not element.get("ea_type"):
                element["ea_type"] = treffer.ea_type
            if treffer.alias and not element.get("alias"):
                element["alias"] = treffer.alias
            if treffer.status and not element.get("status"):
                element["status"] = treffer.status
            if treffer.tags:
                vorhandene_tags = dict(element.get("tags") or {})
                for k, v in treffer.tags.items():
                    # Provenance-Tags (source_ref/doc/confidence) aus dem Lauf
                    # nicht durch alte Katalog-Provenance ueberschreiben;
                    # NATO-/Identitaets-Tags (OriginalGUID, URI, Uuid, ...) und
                    # fehlende Tags aus dem Katalog immer uebernehmen.
                    if k in ("source_ref", "source_doc", "source_confidence") and k in vorhandene_tags:
                        continue
                    if k in IDENTITY_TAGS or k not in vorhandene_tags:
                        vorhandene_tags[k] = v
                if vorhandene_tags:
                    element["tags"] = vorhandene_tags
            if treffer.xref_tags:
                vorhandene_xref = dict(element.get("xref_tags") or {})
                for k, v in treffer.xref_tags.items():
                    vorhandene_xref.setdefault(k, v)
                if vorhandene_xref:
                    element["xref_tags"] = vorhandene_xref
            if treffer.package:
                ziel_paket = _normalisiere_katalogpfad(treffer.package)
                element["package"] = ziel_paket
                paket_ergaenzen(ziel_paket)
                if alt and alt != ziel_paket:
                    umgehaengt[str(element.get("name") or "")] = ziel_paket
            zaehler["katalog"] += 1

        # Kanten haengen an (Paket, Name). Aendert die Uebernahme das Paket
        # eines Elements, zeigt die Kante sonst auf einen Pfad, an dem das
        # Element nicht mehr liegt -- der Export bricht dann mit "zeigt auf
        # kein deklariertes Element" ab. Deshalb werden die Referenzen hier
        # mitgezogen: das Paket stammt immer vom Element, nie vom Lauf.
        if umgehaengt:
            zaehler["kanten"] = 0
            zaehler["sichten"] = 0
            for kante in ir.get("connectors") or ():
                if not isinstance(kante, dict):
                    continue
                for seite in ("source", "target"):
                    ref = str(kante.get(seite) or "")
                    paket, trenner, name = ref.partition("::")
                    if not trenner:
                        continue
                    neu = umgehaengt.get(name)
                    if neu is not None and neu != paket:
                        kante[seite] = f"{neu}::{name}"
                        zaehler["kanten"] += 1
            # Sichtmitglieder sind ebenfalls (Paket, Name)-Verweise. Ohne
            # dieselbe Reparatur zeigt die Sicht nach dem Umhaengen auf ein
            # Element, das im IR nicht mehr unter diesem Paket steht.
            for diagram in ir.get("diagrams") or ():
                if not isinstance(diagram, dict):
                    continue
                members = diagram.get("members")
                if not isinstance(members, list):
                    continue
                for position, member in enumerate(members):
                    if isinstance(member, dict):
                        ref = str(member.get("element") or "")
                    else:
                        ref = str(member)
                    paket, trenner, name = ref.partition("::")
                    if not trenner:
                        continue
                    neu = umgehaengt.get(name)
                    if neu is None or neu == paket:
                        continue
                    if isinstance(member, dict):
                        member["element"] = f"{neu}::{name}"
                    else:
                        members[position] = f"{neu}::{name}"
                    zaehler["sichten"] += 1
        zaehler.setdefault("kanten", 0)
        zaehler.setdefault("sichten", 0)
        return zaehler
