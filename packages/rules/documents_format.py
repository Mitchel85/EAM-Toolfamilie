"""Abgeleitete Dokumente in der Form der Verbraucher-Erwartung.

Der fruehere Dokumenten-Parser ist entfernt; die Formen, die Batch, Extractor
und Script-Maker lesen, bleiben trotzdem Schuld dieses Moduls. Hier stehen sie
an einer Stelle, damit kein Verbraucher eigene Parser braucht.
"""

from __future__ import annotations

import json
from typing import Any

ALIAS_PAARE = {
    "PropertySetGeneralisation": "PropertySetGeneralization",
    "ServiceSpecificationGeneralization": "ServiceGeneralization",
}

QUELLROLLEN = {"client", "source", "end[0].role", "informationSource"}
ZIELROLLEN = {"supplier", "target", "end[1].role", "informationTarget"}


def zelle(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def werte(werte: Any) -> str:
    if not werte:
        return ""
    if isinstance(werte, (list, tuple)):
        return ", ".join(str(w) for w in werte)
    return str(werte)


def abstract_mark(ja: bool) -> str:
    return "🔒 ja" if ja else "–"


# ---------------------------------------------------------------- Katalog

def katalog(rules: dict) -> list[dict]:
    """Element- und Konnektor-Stereotype als eine Liste (318 Zeilen)."""
    zeilen = []
    for s in rules.get("elementStereotypes") or []:
        zeilen.append(
            {
                "name": s.get("name"),
                "metatype": s.get("metatype") or "",
                "parents": list(s.get("generalizes") or []),
                "appliesTo": [a.get("metaclass") for a in (s.get("appliesTo") or []) if a.get("metaclass")],
                "abstract": bool(s.get("abstract")),
                "notes": s.get("notes") or "",
                "tags": s.get("taggedValues") or [],
                "art": "Element",
            }
        )
    for c in rules.get("connectorRules") or []:
        zeilen.append(
            {
                "name": c.get("stereotype"),
                "metatype": c.get("metatype") or "",
                "parents": list(c.get("generalizes") or []),
                "appliesTo": [a.get("metaclass") for a in (c.get("appliesTo") or []) if a.get("metaclass")],
                "abstract": bool(c.get("abstract")),
                "notes": c.get("notes") or "",
                "tags": c.get("taggedValues") or [],
                "art": "Beziehung",
            }
        )
    zeilen.sort(key=lambda e: str(e["name"]).lower())
    return zeilen


def kind_zu_nachfahren(katalog_liste: list[dict]) -> dict[str, list[str]]:
    """Stereotyp -> konkrete Nachfahren (Baum, ohne Zyklen)."""
    kinder: dict[str, list[str]] = {}
    for e in katalog_liste:
        for eltern in e["parents"]:
            kinder.setdefault(eltern, []).append(e["name"])

    def nachfahren(name: str, tiefe: int = 0) -> list[str]:
        if tiefe > 12:
            return []
        out = []
        for kind in sorted(kinder.get(name, [])):
            if kind == name:
                continue
            out.append(kind)
            out.extend(k for k in nachfahren(kind, tiefe + 1) if k not in out)
        return out

    return {e["name"]: nachfahren(e["name"]) for e in katalog_liste if e["abstract"]}


# ---------------------------------------------------------------- Topologie

def topologie(rules: dict) -> list[dict]:
    """Alle Stereotype mit Beziehungsregeln, Altformat (203 Zeilen)."""
    zeilen = []
    for s in rules.get("elementStereotypes") or []:
        quellen, ziele, rollen = [], [], []
        for mc in s.get("metaconstraints") or []:
            rolle = str(mc.get("role") or "")
            werte = mc.get("constraints") or []
            if rolle in QUELLROLLEN:
                quellen += [w for w in werte if w not in quellen]
            elif rolle in ZIELROLLEN:
                ziele += [w for w in werte if w not in ziele]
            elif rolle:
                eintrag = f"{rolle} → {', '.join(werte)}"
                if eintrag not in rollen:
                    rollen.append(eintrag)
        if quellen or ziele or rollen:
            zeilen.append({"stereotype": s.get("name"), "quelle": quellen, "ziel": ziele, "rollen": rollen})
    for c in rules.get("connectorRules") or []:
        q = [x for x in (c.get("source") or []) if x != "*"]
        z = [x for x in (c.get("target") or []) if x != "*"]
        zeilen.append({"stereotype": c.get("stereotype"), "quelle": q, "ziel": z, "rollen": []})
    zeilen.sort(key=lambda e: str(e["stereotype"]).lower())
    return zeilen


# ---------------------------------------------------------------- Tags

def tags_zeilen(rules: dict) -> list[tuple[str, dict]]:
    """Alle Tags als (Stereotyp, Tag) in Katalogreihenfolge."""
    out = []
    for e in katalog(rules):
        for tag in e["tags"]:
            out.append((e["name"], tag))
    return out
