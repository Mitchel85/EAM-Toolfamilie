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


@dataclass(frozen=True)
class CatalogEntry:
    """Ein Katalogelement: Name, Stereotyp, Kennung und Heimatpaket."""

    name: str
    stereotype: str
    guid: str
    package: str


@dataclass
class Catalog:
    """Nachschlagewerk ueber die Standardelemente eines Katalogs."""

    entries: list[CatalogEntry] = field(default_factory=list)
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
        con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
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

            eintraege: list[CatalogEntry] = []
            for name, stereotype, guid, package_id in con.execute(
                "select Name, Stereotype, ea_guid, Package_ID from t_object"
                " where Object_Type <> 'Package' and Name is not null and Name <> ''"
            ):
                guid_text = str(guid or "").strip()
                if not guid_text:
                    continue
                eintraege.append(
                    CatalogEntry(
                        name=str(name).strip(),
                        stereotype=str(stereotype or "").strip(),
                        guid=guid_text.upper(),
                        package=pfad_von(int(package_id or 0)),
                    )
                )
        except sqlite3.Error as error:
            raise CatalogError(f"{pfad}: Katalog nicht lesbar ({error})") from error
        finally:
            con.close()
        if not eintraege:
            raise CatalogError(f"{pfad}: keine Elemente im Katalog")
        return cls(eintraege)

    @classmethod
    def from_entries(cls, entries: Iterable[Mapping[str, Any]]) -> "Catalog":
        """Baut den Katalog aus einfachen Datensaetzen (z. B. JSON im Browser)."""
        gelesen = [
            CatalogEntry(
                name=str(item.get("name") or "").strip(),
                stereotype=str(item.get("stereotype") or "").strip(),
                guid=str(item.get("guid") or "").strip().upper(),
                package=str(item.get("package") or "").strip(),
            )
            for item in entries
        ]
        gelesen = [eintrag for eintrag in gelesen if eintrag.name and eintrag.guid]
        if not gelesen:
            raise CatalogError("Katalog ohne verwertbare Elemente")
        return cls(gelesen)

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

        def paket_ergaenzen(pfad: str) -> None:
            teile = [teil for teil in str(pfad).split("/") if teil]
            for index in range(1, len(teile) + 1):
                pfad_teil = "/".join(teile[:index])
                if pfad_teil and pfad_teil not in vorhanden:
                    pakete.append({"path": pfad_teil})
                    vorhanden.add(pfad_teil)
                    zaehler["pakete"] += 1

        for element in elemente:
            if not isinstance(element, dict):
                continue
            treffer = self.lookup(str(element.get("name") or ""), str(element.get("stereotype") or ""))
            if treffer is None:
                zaehler["neu"] += 1
                continue
            element["guid"] = treffer.guid
            element["stereotype"] = treffer.stereotype or element.get("stereotype") or ""
            if treffer.package:
                element["package"] = treffer.package
                paket_ergaenzen(treffer.package)
            zaehler["katalog"] += 1
        return zaehler
