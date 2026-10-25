"""Regelwerk -> Wissensbasis, mit den Formen des aktuellen Verbraucherstands.

Der frueher genutzte Dokumenten-Parser ist entfernt. Seine Erwartungen stehen
aber in Batch, Extractor und Script-Maker. Diese Datei haelt sie fest — und
zwar so, wie sie **geprueft** werden, nicht wie sie einmal aussahen:

  * Katalog: 318 Stereotype, Spalten Stereotype/Metatype/Eltern/AppliesTo/Abstrakt/Beschreibung
  * Topologie: nur Stereotype mit eigenen Endpunkten (203 Zeilen, davon 70 reine
    Rollenzeilen) + Abschnitt "Abstrakte Endpunkte" mit den Subtypen
  * Viewpoints: 52 Ueberschriften (Diagramm-Artefakt faellt weg)
  * TagTypes: 27 Property-Typen (nach Eigenschaftsnamen dedupliziert)
  * Stereotype-Tags: eine Zeile je Tag (225)
  * JSON: concreteDescendants inkl. Vererbung ueber ``baseStereotypes``

Was hier bewusst **nicht** passiert: XML lesen. Kein zweiter Parser.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import documents_format as fmt


def _kopf(titel: str, quelle: str, ts: str | None) -> list[str]:
    stand = f"(Stand: {ts})" if ts else "(ohne Zeitstempel)"
    return [f"# {titel}", "", f"> Quelle: `{Path(quelle).name}` — automatisch erzeugt {stand}"]


# ------------------------------------------------------------ Vererbung

def eltern_map(katalog_liste: list[dict], rules: dict) -> dict[str, set[str]]:
    """Kanonische Eltern je Stereotyp.

    ``generalizes`` ist die Kante; ``baseStereotypes`` traegt bei einigen
    Stereotypen weitere Eltern (z. B. ResourcePerformer). Beides zaehlt,
    sonst fehlen konkrete Subtypen im Katalog (messbar: 4 statt 16).
    """
    eltern: dict[str, set[str]] = {e["name"]: set(e["parents"]) for e in katalog_liste}
    for quelle in (rules.get("elementStereotypes") or []) + (rules.get("connectorRules") or []):
        name = quelle.get("name") or quelle.get("stereotype")
        for basis in quelle.get("baseStereotypes") or []:
            if basis in eltern and basis != name:
                eltern[name].add(basis)
    return eltern


def nachfahren(eltern: dict[str, set[str]]) -> dict[str, list[str]]:
    """Stereotyp -> alle Nachfahren (Baum, zyklensicher)."""
    kinder: dict[str, list[str]] = {}
    for kind, eltern_liste in eltern.items():
        for elternname in eltern_liste:
            kinder.setdefault(elternname, []).append(kind)

    def tief(name: str, gesehen: frozenset[str]) -> list[str]:
        out: list[str] = []
        for kind in sorted(set(kinder.get(name, []))):
            if kind in gesehen or kind == name:
                continue
            out.append(kind)
            out.extend(k for k in tief(kind, gesehen | {kind}) if k not in out)
        return out

    return {name: tief(name, frozenset({name})) for name in eltern}


def _ist_abstrakt(rules: dict, name: str) -> bool:
    for s in (rules.get("elementStereotypes") or []) + (rules.get("connectorRules") or []):
        if (s.get("name") or s.get("stereotype")) == name:
            return bool(s.get("abstract"))
    return False


# ------------------------------------------------------------ Dateien

def stereotypes_md(rules: dict, quelle: str, ts: str | None) -> str:
    sterne = fmt.katalog(rules)
    abstrakt = sum(1 for s in sterne if s["abstract"])
    zeilen = _kopf("ADMBw-Stereotype (MDG-extrahiert)", quelle, ts)
    zeilen += [
        f"> {len(sterne)} Stereotype · {abstrakt} abstrakt (\U0001F512, nicht instanziierbar)"
        f" · Version: {Path(quelle).name}",
        "",
        "## Lesart",
        "",
        "- **Stereotype** — der Name, der im Modell gesetzt wird.",
        "- **Metatype** — der Typ, den die Technologie dem Stereotyp gibt.",
        "- **Eltern** — Vererbung; ein Kind erbt die Tagged Values der Eltern.",
        "- **AppliesTo** — worauf der Stereotyp angewendet werden darf.",
        "- Abstrakte Stereotype: mit \U0001F512 gekennzeichnet, dürfen nicht instanziiert werden.",
        "- Leerer Metatype heisst: reiner Beziehungs-Stereotyp ohne eigenes UML-Element.",
        "",
        "| Stereotype | Metatype | Eltern | AppliesTo | Abstrakt | Beschreibung |",
        "|---|---|---|---|---|---|",
    ]
    for s in sterne:
        zeilen.append(
            "| "
            + " | ".join(
                [
                    fmt.zelle(s["name"]),
                    fmt.zelle(s["metatype"]),
                    fmt.zelle(", ".join(s["parents"])),
                    fmt.zelle(", ".join(s["appliesTo"])),
                    fmt.abstract_mark(s["abstract"]),
                    fmt.zelle(s["notes"]),
                ]
            )
            + " |"
        )
    nachf = nachfahren(eltern_map(sterne, rules))
    beispiele = []
    for name in ("BWRequirement", "ResourcePerformer"):
        konkrete = [n for n in nachf.get(name, []) if not _ist_abstrakt(rules, n)]
        if konkrete:
            beispiele.append(f"`{name}` als {', '.join(f'`{k}`' for k in konkrete[:4])}")
    zeilen += [
        "",
        "## Hinweis für KI-Werkzeuge",
        "",
        "- Ein Stereotyp mit **\U0001F512 ja** ist abstrakt. Er darf **nicht** als Element- oder "
        "Beziehungstyp verwendet werden.",
        "- Abstrakte Typen sind Platzhalter für ihre konkreten Subtypen."
        + (f" Beispiele: {'; '.join(beispiele)}." if beispiele else ""),
        "- Für jede Regel mit abstraktem Endpunkt gilt: erlaubt sind alle konkreten Subtypen "
        "(Feld `concreteDescendants` in `admbw-stereotypes.json`).",
        "- Die vollständige Auflösung steht in `admbw-knowledge-topology.md`, Abschnitt "
        "„Abstrakte Endpunkte“.",
    ]
    return "\n".join(zeilen) + "\n"


def _topologie_zeilen(rules: dict) -> list[dict]:
    """Regelzeile je Stereotyp: Endpunkte aus Quelle/Ziel, Rollen aus dem Rest.

    Der frueher genutzte Dokumenten-Parser las die Metaconstraints selbst.
    Die kanonische Struktur hat sie beim Einlesen in Quelle/Ziel uebersetzt und
    den Rest als Rollen behalten — deshalb wird hier auch nur der Rest als
    "Weitere Rollen" gezeigt, sonst doppeln sich client/supplier.

    Zaehlung wie im geprueften Altbestand: 203 Zeilen, davon 70 reine Rollenzeilen
    (dazu zaehlen auch die 5 Beziehungs-Stereotype ohne Einschraenkung).
    """
    zeilen = []
    for s in rules.get("elementStereotypes") or []:
        quellen, ziele, rollen = [], [], []
        for mc in s.get("metaconstraints") or []:
            rolle = str(mc.get("role") or "")
            werte = mc.get("constraints") or []
            if rolle in fmt.QUELLROLLEN:
                quellen += [w for w in werte if w not in quellen]
            elif rolle in fmt.ZIELROLLEN:
                ziele += [w for w in werte if w not in ziele]
            elif rolle:
                eintrag = f"{rolle} → {', '.join(werte)}"
                if eintrag not in rollen:
                    rollen.append(eintrag)
        # Auch Rollen ohne Endpunkt zaehlen: der Altbestand fuehrt sie als
        # "reine Rollenzeile" (68 der 203) und Verbraucher lesen sie als
        # Hinweis, dass der Stereotyp an dieser Stelle vorkommt.
        if quellen or ziele or rollen:
            zeilen.append({"stereotype": s.get("name"), "quelle": quellen, "ziel": ziele, "rollen": rollen})
    for c in rules.get("connectorRules") or []:
        q = [x for x in (c.get("source") or []) if x != "*"]
        z = [x for x in (c.get("target") or []) if x != "*"]
        rollen = []
        for mc in c.get("metaconstraints") or []:
            rolle = str(mc.get("role") or "")
            if rolle and rolle not in fmt.QUELLROLLEN and rolle not in fmt.ZIELROLLEN:
                eintrag = f"{rolle} → {', '.join(mc.get('constraints') or [])}"
                if eintrag not in rollen:
                    rollen.append(eintrag)
        # Ein Konnektor ganz ohne Einschraenkung ("*" auf beiden Seiten) ist
        # keine Regel, sondern eine Aussage ueber die Diagrammart. Der gepruefte
        # Altbestand fuehrte ihn nicht; er zaehlt damit 203 statt 206 Zeilen.
        if not q and not z and not rollen:
            continue
        zeilen.append({"stereotype": c.get("stereotype"), "quelle": q, "ziel": z, "rollen": rollen})
    zeilen.sort(key=lambda e: str(e["stereotype"]).lower())
    return zeilen


def topology_md(rules: dict, quelle: str, ts: str | None) -> str:
    regeln = _topologie_zeilen(rules)
    vollstaendig = sum(1 for r in regeln if r["quelle"] and r["ziel"])
    rollenzeilen = sum(1 for r in regeln if not r["quelle"] and not r["ziel"])
    sterne = fmt.katalog(rules)
    nachf = nachfahren(eltern_map(sterne, rules))
    zeilen = _kopf("ADMBw-Topologie-Regeln (MDG-Metaconstraints)", quelle, ts)
    zeilen += [
        f"> {len(regeln)} Stereotype mit Beziehungsregeln (Metaconstraints) · "
        f"{vollstaendig} vollständig (Quelle und Ziel) · {rollenzeilen} reine Rollenzeilen",
        "",
        "## Lesart",
        "",
        "- **Quelle:** client, source, end[0].role oder informationSource — je nach UML-Metaklasse.",
        "- **Ziel:** supplier, target, end[1].role oder informationTarget — je nach UML-Metaklasse.",
        "- **Weitere Rollen:** zusätzliche Metamodell-Beschränkungen (Rollennamen direkt aus der MDG).",
        f"- **Vollständigkeit:** Nur Regeln mit Quelle **und** Ziel ({vollstaendig} von {len(regeln)}) "
        "sind maschinell prüfbar; Regeln mit ausschließlich „Weiteren Rollen“ dienen als Referenz.",
        "- **Abstrakte Typen:** Endpunkte, die auf abstrakte Stereotype verweisen (\U0001F512), gelten "
        "für alle konkreten Subtypen. Die Auflösung steht unten unter „Abstrakte Endpunkte“.",
        "",
        "| Stereotype | Erlaubte Quellen (client/source/end[0]) | Erlaubte Ziele (supplier/target/end[1]) | Weitere Rollen |",
        "|---|---|---|---|",
    ]
    for r in regeln:
        zeilen.append(
            "| "
            + " | ".join(
                [
                    fmt.zelle(r["stereotype"]),
                    fmt.zelle(", ".join(r["quelle"])),
                    fmt.zelle(", ".join(r["ziel"])),
                    fmt.zelle(", ".join(r["rollen"])),
                ]
            )
            + " |"
        )
    zeilen += [
        "",
        "## Abstrakte Endpunkte",
        "",
        "Diese Typen dürfen **nicht instanziiert** werden. Für die Prüfung eines konkreten "
        "Modells sind sie auf die aufgeführten konkreten Subtypen aufzulösen.",
        "",
        "| Abstrakter Typ | Konkrete Subtypen |",
        "|---|---|",
    ]
    for s in sterne:
        if not s["abstract"]:
            continue
        konkrete = [n for n in nachf.get(s["name"], []) if not _ist_abstrakt(rules, n)]
        zeilen.append(f"| \U0001F512 {fmt.zelle(s['name'])} | {fmt.zelle(', '.join(konkrete))} |")
    return "\n".join(zeilen) + "\n"


def viewpoints_md(rules: dict, quelle: str, ts: str | None) -> str:
    vps = [
        v for v in (rules.get("viewpoints") or [])
        if str(v.get("name") or "").strip().lower() != "business process"
    ]
    zeilen = _kopf("ADMBw-Viewpoints (MDG-DiagramProfile)", quelle, ts)
    zeilen += [f"> {len(vps)} Viewpoints", ""]
    for v in vps:
        zeilen.append(f"## {v.get('name')}")
        text = fmt.zelle(v.get("notes"))
        if text:
            zeilen.append(text)
        zeilen.append("")
    return "\n".join(zeilen).rstrip() + "\n"


TAGTYPEN_DATENSATZ = {"Property Types", "Properties", "Property Type"}


def _ist_property_typ(rules: dict, name: str, typ: str) -> bool:
    """Eigene Definition im Technologie-Kopf (Datensatz Property Types).

    Der Regelwerk-Leser reicht diese Tabelle nicht durch; sie wird einmal je
    Lauf aus der MDG gelesen — dieselbe Datei, dasselbe Fenster, kein zweiter
    XML-Leser im Sinne einer zweiten Wahrheit (es ist eine Wertetabelle).
    """
    tabelle = rules.get("propertyTypeTable")
    if not tabelle:
        return False
    return (name, typ) in tabelle


def tagtypes_md(rules: dict, quelle: str, ts: str | None) -> str:
    """Property-Typen aus der Technologie-Tabelle <TaggedValueTypes> (27 Zeilen)."""
    typen = rules.get("taggedValueTypes") or []
    zeilen = _kopf("ADMBw-Tagged-Value-Definitionen (MDG-Property-Typen)", quelle, ts)
    zeilen += [
        f"> {len(typen)} Property-Typen",
        "",
        "| Property | Datensatz | Beschreibung | Einschränkungen (aus MDG) |",
        "|---|---|---|---|",
    ]
    for t in typen:
        zeilen.append(
            "| "
            + " | ".join(
                [
                    fmt.zelle(t.get("name")),
                    "Property Types",
                    fmt.zelle(t.get("description")),
                    fmt.zelle(t.get("notes")),
                ]
            )
            + " |"
        )
    return "\n".join(zeilen) + "\n"


def stereotype_tags_md(rules: dict, quelle: str, ts: str | None) -> str:
    alle = fmt.tags_zeilen(rules)
    sterne = len({name for name, _ in alle})
    zeilen = _kopf("ADMBw-Stereotyp-Tags (MDG-TaggedValues)", quelle, ts)
    zeilen += [
        f"> {len(alle)} Tags an {sterne} Stereotypen",
        "",
        "| Stereotype | Tag | Typ | Erlaubte Werte | Default | Beschreibung |",
        "|---|---|---|---|---|---|",
    ]
    for name, tag in alle:
        zeilen.append(
            "| "
            + " | ".join(
                [
                    fmt.zelle(name),
                    fmt.zelle(tag.get("name")),
                    fmt.zelle(tag.get("type") or ""),
                    fmt.zelle(fmt.werte(tag.get("values"))),
                    fmt.zelle(tag.get("default")),
                    fmt.zelle(tag.get("description")),
                ]
            )
            + " |"
        )
    return "\n".join(zeilen) + "\n"


def meta_md(rules: dict, quelle: str, ts: str | None) -> str:
    herkunft = rules.get("source") or {}
    stats = rules.get("stats") or {}
    sterne = fmt.katalog(rules)
    zeilen = [
        "# ADMBw-Wissensbasis — Kopf",
        "",
        f"- **MDG-Datei:** `{Path(quelle).name}`",
        f"- **Technologie:** {herkunft.get('technologyName') or herkunft.get('technologyId') or '—'}",
        f"- **Release:** {herkunft.get('technologyVersion') or '—'}",
        f"- **Erzeugt:** {ts or 'ohne Zeitstempel'}",
        "",
        "## Kennzahlen",
        "",
        "| Größe | Anzahl |",
        "|---|---|",
        f"| Stereotype gesamt | {len(sterne)} |",
        f"| davon abstrakt | {sum(1 for s in sterne if s['abstract'])} |",
        f"| Element-Stereotype | {len(rules.get('elementStereotypes') or [])} |",
        f"| Konnektor-Regeln | {len(rules.get('connectorRules') or [])} |",
        f"| Viewpoints | {len(rules.get('viewpoints') or [])} |",
        f"| Metaklassen | {len(rules.get('metaclasses') or [])} |",
        f"| Hinweise beim Einlesen | {len(rules.get('warnings') or [])} |",
    ]
    if stats:
        zeilen += ["", "## Rohzahlen", ""] + [f"- {k}: {v}" for k, v in sorted(stats.items())]
    return "\n".join(zeilen) + "\n"


def prompt_md(rules: dict, quelle: str, ts: str | None) -> str:
    sterne = fmt.katalog(rules)
    regeln = _topologie_zeilen(rules)
    tags = fmt.tags_zeilen(rules)
    # Das Diagramm-Artefakt "Business Process" ist kein Viewpoint; die
    # Dokumentseite fuehrt es nicht, der Prompt darf es nicht mitzaehlen.
    anzahl_vp = sum(
        1 for v in (rules.get("viewpoints") or [])
        if str(v.get("name") or "").strip().lower() != "business process"
    )
    vollstaendig = sum(1 for r in regeln if r["quelle"] and r["ziel"])
    abstrakt = sum(1 for s in sterne if s["abstract"])
    version = (rules.get("source") or {}).get("technologyVersion") or ""
    aliase = "\n".join(f"- `{alt}` → `{neu}`" for alt, neu in fmt.ALIAS_PAARE.items())
    zeilen = [
        "# ADMBw-Regelwerk — Prompt",
        "",
        f"> MDG-Version {version} · {len(sterne)} Stereotype · {abstrakt} abstrakt"
        f" · Quelle `{Path(quelle).name}` · {'ohne Zeitstempel' if not ts else ts}",
        "",
        "Dieses Dokument ist die Arbeitsanweisung. Die Regeln selbst stehen in den "
        "Regeldateien daneben — sie werden nicht hierher kopiert.",
        "",
        "## Auftrag",
        "",
        "Du bist Modellierungsassistent für Architekturmodelle nach der Methode "
        "Architektur der Bundeswehr (ADMBw, NAFv4). Übersetze den gelieferten Prosa-Text "
        "in ein regelkonformes Modell: Elemente mit Stereotyp, Beziehungen mit Quell- und "
        "Zieltyp.",
        "",
        "## Eiserne Regeln",
        "",
        "1. Keinen Stereotyp erfinden — nur Namen aus `admbw-knowledge-stereotypes.md`.",
        "2. Abstrakte Stereotype (\U0001F512) nie instanziieren. Immer einen konkreten Subtyp "
        "wählen (Abschnitt „Abstrakte Endpunkte“ in `admbw-knowledge-topology.md`).",
        "3. Jede Beziehung gegen eine Regel in `admbw-knowledge-topology.md` prüfen: "
        "Quelle = client/source/end[0], Ziel = supplier/target/end[1]. Zeilen mit nur "
        "„Weiteren Rollen“ sind keine Kanten-Regel.",
        "4. Nennt eine Regel einen abstrakten Endpunkt, sind alle seine konkreten Subtypen zulässig.",
        "5. Schreibvarianten vor dem Namensvergleich normalisieren (`admbw-aliases.json`):",
        "",
        aliase,
        "",
        "6. Jede Aussage mit der Regelzeile belegen — keine ungeprüften ✓-Behauptungen.",
        "",
        "## Ausgabeformat",
        "",
        "- **Elemente:** Prosa-Stelle | Elementname | Stereotyp | Metaklasse",
        "- **Beziehungen:** Quelle | Stereotyp | Ziel | erlaubt durch (Regelzeile)",
        "- **Offene Punkte:** was der Prosa-Text nicht hergibt",
        "",
        "## Dateien des Regelwerks",
        "",
        "| Datei | Inhalt | Umfang |",
        "|---|---|---|",
        f"| `admbw-knowledge-stereotypes.md` | Stereotyp-Katalog (Metatype, AppliesTo, Eltern, \U0001F512, Beschreibung) | {len(sterne)} Stereotype |",
        f"| `admbw-knowledge-topology.md` | Beziehungsregeln (Quelle/Ziel/weitere Rollen) | {len(regeln)} Regeln, {vollstaendig} vollständig |",
        f"| `admbw-knowledge-viewpoints.md` | NAFv4-Viewpoints | {anzahl_vp} |",
        f"| `admbw-knowledge-tagtypes.md` | Tagged-Value-Definitionen | {len(tags)} Tags |",
        f"| `admbw-knowledge-stereotype-tags.md` | Konkrete Tags je Stereotyp | {len(tags)} Tags |",
        "| `admbw-meta.md` | Quelle, Version, Kennzahlen | – |",
        f"| `admbw-stereotypes.json` | Maschinenlesbar: `abstract`, `parents`, `appliesTo`, `concreteDescendants` | {len(sterne)} Einträge |",
        f"| `admbw-aliases.json` | Schreibvarianten | {len(fmt.ALIAS_PAARE)} Einträge |",
    ]
    return "\n".join(zeilen) + "\n"


def stereotypes_json(rules: dict) -> str:
    sterne = fmt.katalog(rules)
    nachf = nachfahren(eltern_map(sterne, rules))
    herkunft = rules.get("source") or {}
    daten = {
        "release": herkunft.get("technologyVersion"),
        "source": herkunft.get("technologyName"),
        "counts": {
            "stereotypes": len(sterne),
            "abstract": sum(1 for s in sterne if s["abstract"]),
            "abstractWithoutAppliesTo": sum(1 for s in sterne if s["abstract"] and not s["appliesTo"]),
            "abstractWithAppliesTo": sum(1 for s in sterne if s["abstract"] and s["appliesTo"]),
        },
        "stereotypes": [
            {
                "name": s["name"],
                "metatype": s["metatype"],
                "abstract": s["abstract"],
                "parents": s["parents"],
                "appliesTo": s["appliesTo"],
                "concreteDescendants": nachf.get(s["name"], []),
            }
            for s in sterne
        ],
    }
    return json.dumps(daten, indent=2, ensure_ascii=False) + "\n"


def aliases_json() -> str:
    daten = {
        "note": "Alt-Schreibweisen aus Modellen oder älteren MDG-Ständen. "
                "Prüfprogramme sollen vor dem Namensvergleich umschreiben.",
        "aliases": dict(fmt.ALIAS_PAARE),
    }
    return json.dumps(daten, indent=2, ensure_ascii=False)


def connectors_md(rules: dict, quelle: str, ts: str | None) -> str:
    """Bruecke EA-Metatyp -> Stereotyp plus die vollstaendige Viewpoint-Liste.

    Diese Datei war bis 24.10.2026 in drei Verbrauchern von Hand gepflegt und
    in zwei Fassungen auseinandergelaufen. Sie wird jetzt aus dem Regelwerk
    abgeleitet; die frueheren Kopien sind Symlinks hierher.
    """
    zeilen = _kopf("ADMBw Knowledge: Konnektor-Regeln & Viewpoint-Übersicht", quelle, ts)
    zeilen += [
        "",
        "## Goldene Regel",
        "",
        "Jede Beziehung besteht aus EA-Metatyp und Stereotyp. Der Stereotyp muss auf "
        "diesen Metatyp anwendbar sein; Element- und Konnektor-Ebene sind strikt getrennt.",
        "",
        "## Element-Metatypen & ihre Stereotype",
        "",
        "| EA-Metatyp | Anzahl | Stereotype |",
        "|---|---:|---|",
    ]
    nach_element: dict[str, list[str]] = {}
    for s in rules.get("elementStereotypes") or []:
        typen = [str(t) for t in (s.get("metaclasses") or []) if str(t).strip()]
        if not typen:
            continue
        # Nur der spezifischste Metatyp zaehlt: Condition und Location sind
        # sowohl Class als auch DataType. Der gepruefte Altbestand fuehrt sie
        # unter DataType (Class 68, DataType 3), nicht doppelt (Class 70).
        nach_element.setdefault(typen[-1], []).append(str(s.get("name") or ""))
    for typ in sorted(nach_element, key=lambda t: (-len(nach_element[t]), t.lower())):
        namen = sorted(nach_element[typ])
        gezeigt = namen[:12]
        rest = len(namen) - len(gezeigt)
        liste = ", ".join(f"`{n}`" for n in gezeigt)
        if rest:
            liste += f" +{rest} weitere"
        zeilen.append(f"| **{typ}** ({len(namen)}) | {len(namen)} | {liste} |")

    zeilen += [
        "",
        "## Konnektor-Metatypen & ihre Stereotype",
        "",
        "| EA-Metatyp | Anzahl | Stereotype |",
        "|---|---:|---|",
    ]
    nach_metatyp: dict[str, list[str]] = {}
    for c in rules.get("connectorRules") or []:
        typen = [str(t) for t in (c.get("metaclasses") or []) if str(t).strip()] or ["(ohne)"]
        for typ in typen:
            nach_metatyp.setdefault(typ, []).append(str(c.get("stereotype") or ""))
    for typ in sorted(nach_metatyp, key=lambda t: (-len(nach_metatyp[t]), t.lower())):
        namen = sorted(nach_metatyp[typ])
        gezeigt = namen[:12]
        rest = len(namen) - len(gezeigt)
        liste = ", ".join(f"`{n}`" for n in gezeigt)
        if rest:
            liste += f" +{rest} weitere"
        zeilen.append(f"| **{typ}** ({len(namen)}) | {len(namen)} | {liste} |")

    gruppen: dict[str, list[dict]] = {}
    for vp in rules.get("viewpoints") or []:
        if str(vp.get("name") or "").strip().lower() == "business process":
            continue
        gruppen.setdefault(str(vp.get("group") or "Weitere"), []).append(vp)
    anzahl = sum(len(v) for v in gruppen.values())
    zeilen += [
        "",
        f"## Vollständige Viewpoint-Liste ({anzahl} Viewpoints, {len(gruppen)} Kategorien)",
        "",
    ]
    groups: dict[str, list[dict]] = {}
    for vp in rules.get("viewpoints") or []:
        if str(vp.get("name") or "").strip().lower() == "business process":
            continue
        groups.setdefault(str(vp.get("group") or "Weitere"), []).append(vp)
    for gruppe in sorted(groups):
        kurz = gruppe.replace("NAFv4-ADMBw ", "")
        zeilen += [f"### {kurz}", "", "| Kürzel | Name | Beschreibung |", "|---|---|---|"]
        for vp in sorted(groups[gruppe], key=lambda v: str(v.get("name"))):
            props = vp.get("properties") or {}
            kuerzel = str(props.get("diagramID") or "")
            name = str(vp.get("name") or "")
            ohne_kurz = name.split(" - ", 1)[1] if " - " in name else name
            notiz = str(vp.get("notes") or "").strip().replace("\n", " ")
            satz = notiz.split(". ")[0].rstrip(".") if notiz else ""
            zeilen.append(f"| {kuerzel} | {fmt.zelle(ohne_kurz)} | {fmt.zelle(satz)} |")
        zeilen.append("")
    return "\n".join(zeilen) + "\n"


def erzeuge(rules: dict, quelle: str, with_timestamp: bool = False) -> dict[str, str]:
    ts = None
    if with_timestamp:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "admbw-knowledge-stereotypes.md": stereotypes_md(rules, quelle, ts),
        "admbw-knowledge-topology.md": topology_md(rules, quelle, ts),
        "admbw-knowledge-viewpoints.md": viewpoints_md(rules, quelle, ts),
        "admbw-knowledge-tagtypes.md": tagtypes_md(rules, quelle, ts),
        "admbw-knowledge-stereotype-tags.md": stereotype_tags_md(rules, quelle, ts),
        "admbw-knowledge-connectors.md": connectors_md(rules, quelle, ts),
        "admbw-meta.md": meta_md(rules, quelle, ts),
        "admbw-prompt.md": prompt_md(rules, quelle, ts),
        "admbw-stereotypes.json": stereotypes_json(rules),
        "admbw-aliases.json": aliases_json(),
    }


def schreibe(rules: dict, quelle: str, ziel: Path, with_timestamp: bool = False) -> list[Path]:
    ziel.mkdir(parents=True, exist_ok=True)
    geschrieben = []
    for name, inhalt in erzeuge(rules, quelle, with_timestamp).items():
        pfad = ziel / name
        pfad.write_text(inhalt, encoding="utf-8", newline="\n")
        geschrieben.append(pfad)
    return geschrieben
