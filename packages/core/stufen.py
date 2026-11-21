"""stufen.py -- vierstufiger Lauf: Regelwerk, Elemente, Architektur, Pruefung.

Warum getrennt
--------------
Der Einzelaufruf ``eam-ai build`` schickt das komplette Regelwerk und die
Quelle in einen Lauf. Bei grossen Texten und langsamen Modellen fuehrt das in
Zugriffslimits. Der Stufenlauf trennt die Arbeit:

1. **Regelwerk** -- MDG und Startpaket lesen, als Tabelle ablegen (offline).
2. **Elemente** -- Prosa in Chargen gegen das Regelwerk extrahieren (KI,
   mit Pause zwischen den Aufrufen, jeder Aufruf wird gespeichert).
3. **Architektur** -- aus der Elementtabelle die Leitfaden-Struktur bauen
   (offline, ohne KI).
4. **Pruefung** -- Leitfaden, EA-Geometrie und Integritaet pruefen (offline).

Jede Stufe schreibt ihr Ergebnis in ``workdir``; ein Abbruch kostet nur die
aktuelle Charge. Ein erneuter Aufruf setzt an der ersten fehlenden Charge fort.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

import catalog_index
import ea_check
import eam_ai
import extract
import image_input
import qea_writer
import struktur

STATE = "state.json"
REGELWERK = "01_regelwerk.json"
STARTPAKET = "01_startpaket.json"
KATALOG_TEXT = "01_prompt-katalog.txt"
CHARGEN = "02_chargen"
ELEMENTE = "02_elemente.json"
ANTWORT = "02_antwort.json"
TABELLE = "02_elementtabelle.json"
FORTSCHRITT = "02_fortschritt.json"


class StufenFehler(RuntimeError):
    """Stufenlauf abgebrochen. Immer laut."""


def _wd(workdir: str | Path) -> Path:
    pfad = Path(workdir)
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def _write_json(path: Path, daten: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise StufenFehler(f"{path}: fehlt -- vorherige Stufe laufen lassen") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise StufenFehler(f"{path}: nicht lesbar ({exc})") from exc


def _pause(seconds: float) -> None:
    """Wartezeit ohne ``time`` (der Kernlint verbietet Zeit im Kern)."""
    if seconds > 0:
        threading.Event().wait(float(seconds))


def _katalog_aus_startpaket(pfad: str | Path) -> tuple[catalog_index.Catalog, str]:
    """Startpaket lesen; ohne ``ea_guid`` werden stabile Kennungen abgeleitet.

    Ein StEKa aus einem fremden Werkzeug hat haeufig keine ``ea_guid``. Dann
    ist die Datei kein Katalog im engeren Sinn, aber immer noch eine Liste von
    Standardelementen. Statt mit "keine Elemente" abzubrechen, werden Name,
    Stereotyp und Paket gelesen und die Kennung deterministisch gebildet.
    """
    try:
        return catalog_index.Catalog.from_qea(pfad), ""
    except catalog_index.CatalogError as fehler:
        quelle = Path(pfad)
        con = sqlite3.connect(str(quelle))
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
            rows = con.execute(
                "select Name, ifnull(Stereotype, ''), Package_ID from t_object "
                "where Object_Type <> 'Package' and Name is not null and Name <> ''"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StufenFehler(f"Startpaket {quelle}: nicht lesbar ({exc})") from exc
        finally:
            con.close()

        def pfad_von(pid: int) -> str:
            teile: list[str] = []
            seen: set[int] = set()
            while pid and pid not in seen:
                seen.add(pid)
                if pakete.get(pid):
                    teile.append(pakete[pid])
                pid = eltern.get(pid, 0)
            return "/".join(reversed(teile))

        eintraege = []
        for name, stereotype, package_id in rows:
            name = str(name).strip()
            stereotype = str(stereotype).strip()
            pfad_text = pfad_von(int(package_id or 0))
            eintraege.append(
                {
                    "name": name,
                    "stereotype": stereotype,
                    "guid": qea_writer.guid_for(pfad_text or "StEKa", stereotype, name),
                    "package": pfad_text,
                }
            )
        if not eintraege:
            raise StufenFehler(
                f"Startpaket {quelle}: keine Elemente gefunden ({fehler})"
            )
        return (
            catalog_index.Catalog.from_entries(eintraege),
            "Startpaket ohne ea_guid -- Kennungen aus Paket, Stereotyp und Name abgeleitet",
        )


def _code(viewpoint: Mapping[str, Any]) -> str:
    properties = viewpoint.get("properties") or {}
    code = str(properties.get("diagramID") or "").strip()
    if code:
        return code
    return str(viewpoint.get("name") or "").split(" - ")[0].strip()


def _metaklasse(entry: Mapping[str, Any]) -> str:
    for metaclass in entry.get("metaclasses") or ():
        if str(metaclass).strip().lower() != "package":
            return str(metaclass).strip()
    return ""


# ---------------------------------------------------------------------------
# Stufe 1: Regelwerk und Startpaket
# ---------------------------------------------------------------------------


def stufe1(
    *,
    mdg: str | Path,
    workdir: str | Path,
    startpaket: str | Path | None = None,
    text: str | Path | None = None,
    images: Sequence[str | Path] = (),
    projekt: str = eam_ai.DEFAULT_PACKAGE,
    package: str | None = None,
) -> dict[str, Any]:
    """MDG und Startpaket als Tabellen ablegen -- kein Modellaufruf."""
    wd = _wd(workdir)
    rules = eam_ai.load_technology(mdg)
    rulebook = extract.load_rules(rules)

    viewpoints: list[dict[str, str]] = []
    for eintrag in rules.get("viewpoints") or ():
        if not isinstance(eintrag, Mapping):
            continue
        code = _code(eintrag)
        if not code:
            continue
        viewpoints.append(
            {
                "code": code,
                "name": str(eintrag.get("name") or code),
                "gruppe": str(eintrag.get("group") or ""),
            }
        )

    elemente: list[dict[str, Any]] = []
    for name in sorted(rulebook.elements):
        eintrag = rulebook.elements[name]
        elemente.append(
            {
                "name": name,
                "metaclass": _metaklasse(
                    {
                        "metaclasses": list(eintrag.metaclasses),
                    }
                ),
                "abstract": bool(eintrag.abstract),
                "generalizes": list(eintrag.generalizes),
                "baseStereotypes": list(eintrag.base_stereotypes),
            }
        )

    beziehungen: list[dict[str, Any]] = []
    for name in sorted(rulebook.connectors):
        eintrag = rulebook.connectors[name]
        beziehungen.append(
            {
                "name": name,
                "source": list(eintrag.source),
                "target": list(eintrag.target),
                "metaclass": _metaklasse({"metaclasses": list(eintrag.metaclasses)}),
                "direction": eintrag.direction,
            }
        )

    quelle = rules.get("source") or {}
    regelwerk = {
        "mdg": str(Path(mdg)),
        "technologie": {
            "name": str(quelle.get("technologyName") or ""),
            "version": str(quelle.get("technologyVersion") or ""),
            "id": str(quelle.get("technologyId") or ""),
        },
        "kennzahlen": dict(rules.get("stats") or {}),
        "viewpoints": viewpoints,
        "elemente": elemente,
        "beziehungen": beziehungen,
    }
    _write_json(wd / REGELWERK, regelwerk)

    start: dict[str, Any] = {"datei": "", "elemente": []}
    katalog_datei = ""
    startpaket_hinweis = ""
    if startpaket is not None:
        katalog, startpaket_hinweis = _katalog_aus_startpaket(startpaket)
        eintraege = list(katalog.entries)
        # Ein Startpaket kann ein ganzes Modell sein (MASC). Fuer den Katalog
        # zaehlen nur Standardelemente: Modellelementekatalog und StEKa.
        standard = [
            eintrag
            for eintrag in eintraege
            if "Modellelementekatalog" in eintrag.package
            or eintrag.package.casefold().startswith("steka")
            or "/steka/" in eintrag.package.casefold()
        ]
        if standard:
            eintraege = standard
        start = {
            "datei": str(Path(startpaket)),
            "elemente": [
                {
                    "name": eintrag.name,
                    "stereotype": eintrag.stereotype,
                    "guid": eintrag.guid,
                    "package": eintrag.package,
                    "ea_type": eintrag.ea_type,
                    "notes": eintrag.notes,
                    "alias": eintrag.alias,
                    "status": eintrag.status,
                    "tags": dict(eintrag.tags),
                    "xref_tags": dict(eintrag.xref_tags),
                }
                for eintrag in eintraege
            ],
        }
        _write_json(wd / STARTPAKET, start)

        # Nur den Katalog als eigene StEKa-Wurzel schreiben. Das Startpaket
        # selbst wird nicht ins Modell kopiert -- sonst wandern fremde
        # Wurzelpakete und Sichten mit (MASC-Problem). Die GUIDs, Tags
        # (NATO OriginalGUID, URI, Uuid, ...) und Taxonomie-Kanten bleiben.
        steka_pakete: dict[str, str] = {"StEKa": "StEKa"}
        steka_elemente: list[dict[str, Any]] = []
        gesehen: set[tuple[str, str]] = set()
        guid_to_ref: dict[str, str] = {}
        for eintrag in eintraege:
            key = (eintrag.name, eintrag.stereotype)
            if key in gesehen:
                continue
            gesehen.add(key)
            teile = [t for t in str(eintrag.package or "").split("/") if t]
            if "Modellelementekatalog" in teile:
                idx = teile.index("Modellelementekatalog")
                rest = teile[idx + 1 :]
                paket = "/".join(["StEKa", *rest]) if rest else f"StEKa/{eintrag.stereotype.strip() or 'Ohne Stereotyp'}"
            elif teile and teile[0].casefold().startswith("steka"):
                paket = "/".join(["StEKa", *teile[1:]]) if len(teile) > 1 else f"StEKa/{eintrag.stereotype.strip() or 'Ohne Stereotyp'}"
            else:
                teil = eintrag.stereotype.strip() or "Ohne Stereotyp"
                paket = f"StEKa/{teil}"
            pfad_teile = [t for t in paket.split("/") if t]
            for index in range(1, len(pfad_teile) + 1):
                teil_pfad = "/".join(pfad_teile[:index])
                steka_pakete[teil_pfad] = teil_pfad
            el_dict: dict[str, Any] = {
                "package": paket,
                "name": eintrag.name,
                "stereotype": eintrag.stereotype,
                "ea_type": eintrag.ea_type or "Class",
                "guid": eintrag.guid,
                "notes": eintrag.notes or f"Standardelement aus {startpaket}.",
            }
            if eintrag.alias:
                el_dict["alias"] = eintrag.alias
            if eintrag.status:
                el_dict["status"] = eintrag.status
            if eintrag.tags:
                el_dict["tags"] = dict(eintrag.tags)
            if eintrag.xref_tags:
                el_dict["xref_tags"] = dict(eintrag.xref_tags)
            steka_elemente.append(el_dict)

        temp_elements = [
            qea_writer.Element(
                package_path=el["package"],
                name=el["name"],
                stereotype=el.get("stereotype", ""),
                ea_type=el.get("ea_type", "Class"),
                notes=el.get("notes", ""),
                alias=el.get("alias", ""),
                status=el.get("status", ""),
                tags=el.get("tags", {}),
                guid=el.get("guid"),
            )
            for el in steka_elemente
        ]
        elem_idx = qea_writer._element_index(temp_elements)
        for (pkg_p, nm), grp in elem_idx.items():
            if len(grp) == 1:
                if grp[0].guid:
                    guid_to_ref[grp[0].guid] = f"{pkg_p}::{nm}"
            else:
                for pos, el in enumerate(grp, 1):
                    if el.guid:
                        guid_to_ref[el.guid] = f"{pkg_p}::{nm}#{pos}"

        steka_kanten: list[dict[str, Any]] = []
        gesehene_kanten: set[tuple[str, str, str, str]] = set()
        for kante in getattr(katalog, "connectors", ()):
            s_ref = guid_to_ref.get(str(kante.get("source_guid") or ""))
            t_ref = guid_to_ref.get(str(kante.get("target_guid") or ""))
            if not s_ref or not t_ref:
                continue
            k_key = (
                s_ref,
                t_ref,
                str(kante.get("stereotype") or ""),
                str(kante.get("ea_type") or "Dependency"),
            )
            if k_key in gesehene_kanten:
                continue
            gesehene_kanten.add(k_key)
            c_dict: dict[str, Any] = {
                "source": s_ref,
                "target": t_ref,
                "ea_type": str(kante.get("ea_type") or "Dependency"),
                "stereotype": str(kante.get("stereotype") or ""),
                "name": str(kante.get("name") or ""),
                "notes": str(kante.get("notes") or ""),
            }
            c_guid = str(kante.get("guid") or "").strip()
            if c_guid:
                c_dict["guid"] = c_guid
            steka_kanten.append(c_dict)
        steka_ir = {
            "ir_version": 1,
            "packages": [{"path": pfad} for pfad in sorted(steka_pakete)],
            "elements": steka_elemente,
            "connectors": steka_kanten,
            "diagrams": [],
        }
        katalog_datei = str(wd / "01_steka.qea")
        qea_writer.write_qea(steka_ir, katalog_datei)

    state = {
        "mdg": str(Path(mdg)),
        "startpaket": str(Path(startpaket)) if startpaket is not None else "",
        "startpaket_hinweis": startpaket_hinweis,
        "katalog": katalog_datei,
        "text": str(Path(text)) if text is not None else "",
        "images": [str(Path(p)) for p in images],
        "projekt": str(projekt),
        "package": str(package or projekt),
    }
    _write_json(wd / STATE, state)

    # Kompakter Prompt-Katalog zum Nachlesen und fuer die naechste Stufe.
    zeilen = [
        "# Element-Stereotype",
        *[f"- {e['name']} [{e['metaclass']}]" for e in elemente],
        "",
        "# Beziehungs-Stereotype",
        *[f"- {b['name']}: {'*' if '*' in b['source'] else ', '.join(b['source'])} -> "
          f"{'*' if '*' in b['target'] else ', '.join(b['target'])}" for b in beziehungen],
    ]
    (wd / KATALOG_TEXT).write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    return {
        "regelwerk": str(wd / REGELWERK),
        "startpaket": str(wd / STARTPAKET) if startpaket is not None else "",
        "viewpoints": len(viewpoints),
        "elemente": len(elemente),
        "beziehungen": len(beziehungen),
        "startelemente": len(start["elemente"]),
        "startpaket_hinweis": startpaket_hinweis,
    }


# ---------------------------------------------------------------------------
# Stufe 2: Elemente und Beziehungen in Chargen
# ---------------------------------------------------------------------------


def _element_zeilen(rulebook: extract.RuleBook) -> list[str]:
    out: list[str] = []
    for name in sorted(rulebook.elements):
        entry = rulebook.elements[name]
        metas = [m for m in entry.metaclasses if m.strip().lower() != "package"]
        out.append(f"- {name} [{metas[0] if metas else 'Class'}]")
    return out


def _known_block(known: Sequence[tuple[str, str]]) -> str:
    if not known:
        return ""
    lines = "\n".join(f"- {name} «{stereo}»" for name, stereo in known)
    return (
        "Bereits vorhandene Elemente (Startpaket oder fruehere Charge). Nenne sie\n"
        "mit exakt diesem Namen und Stereotyp, wenn der Quelltext sie nennt:\n"
        f"{lines}\n\n"
    )


def _relevante_bekannte(
    batch: Sequence[extract.Segment],
    known: Sequence[tuple[str, str]],
    limit: int = 60,
) -> tuple[tuple[str, str], ...]:
    """Bestand fuer den Prompt: erst was der Absatz nennt, dann der Rest.

    Der Startkatalog kann ueber tausend Elemente enthalten. Alle in jeden
    Prompt zu schreiben, macht die Stufe wertlos -- gezeigt wird deshalb nur
    eine begrenzte, textnahe Auswahl.
    """
    text = " ".join(segment.text for segment in batch).casefold()
    genannt = [item for item in known if item[0] and item[0].casefold() in text]
    uebrig = [item for item in known if item not in genannt]
    rest = max(0, limit - len(genannt))
    return tuple(genannt + (uebrig[-rest:] if rest else []))


def _source_block(batch: Sequence[extract.Segment]) -> str:
    return "\n".join(f"[{segment.ref}] {segment.text}" for segment in batch)


def element_prompt(
    batch: Sequence[extract.Segment],
    rulebook: extract.RuleBook,
    *,
    package: str,
    known: Sequence[tuple[str, str]] = (),
) -> str:
    """Prompt fuer die Elementtabelle einer Charge -- ohne Beziehungen."""
    element_block = "\n".join(_element_zeilen(rulebook))
    bekannte = _relevante_bekannte(batch, known)
    return (
        "Du bist ein Architektur-Extraktor. Extrahiere aus dem Quelltext\n"
        "ausschliesslich ELEMENTE, keine Beziehungen.\n\n"
        f"Technologieprofil: {rulebook.profile or '(ohne Profil)'}\n"
        f"Zielpaket im Modell: {package}\n\n"
        f"{_known_block(bekannte)}"
        "Erlaubte Element-Stereotype (Name [Metaklasse]):\n"
        f"{element_block}\n\n"
        "Regeln:\n"
        "1. Nur ausdruecklich benannte Elemente; nichts erfinden.\n"
        "2. Jedes Element braucht source_ref (Absatznummer aus dem Quelltext).\n"
        "3. name exakt wie im Text, ohne Erklaerung.\n"
        "4. notes sind die woertlichen Saetze, die das Element belegen.\n"
        "5. confidence ist eine Zahl von 0 bis 1.\n"
        "6. Antworte ausschliesslich mit JSON, ohne Markdown.\n\n"
        'Antwortform: {"elements": [{"name": "...", "stereotype": "...", '
        '"notes": "...", "source_ref": "D1-S1", "confidence": 0.9}], "connectors": []}\n\n'
        "Quelltext:\n"
        f"{_source_block(batch)}\n"
    )


def connector_prompt(
    batch: Sequence[extract.Segment],
    rulebook: extract.RuleBook,
    *,
    elemente: Sequence[Mapping[str, Any]],
    known: Sequence[tuple[str, str]] = (),
) -> str:
    """Prompt fuer die Beziehungen einer Charge -- Endpunkte aus der Tabelle."""
    connector_block = "\n".join(extract._connector_lines(rulebook))
    gesehen: list[str] = []
    for name, stereotype in known:
        if name and name not in gesehen:
            gesehen.append(name)
    for eintrag in elemente:
        name = str(eintrag.get("name") or "").strip()
        if name and name not in gesehen:
            gesehen.append(name)
    text = " ".join(segment.text for segment in batch).casefold()
    genannt = [name for name in gesehen if name.casefold() in text]
    uebrig = [name for name in gesehen if name not in genannt]
    rest = max(0, 120 - len(genannt))
    auswahl = genannt + (uebrig[-rest:] if rest else [])
    element_block = "\n".join(
        f"- {name}" for name in sorted(auswahl, key=lambda item: (item.casefold(), item))
    )
    return (
        "Du bist ein Architektur-Extraktor. Extrahiere aus dem Quelltext\n"
        "ausschliesslich BEZIEHUNGEN zwischen den bereits erfassten Elementen.\n\n"
        "Erlaubte Beziehungs-Stereotype (Name: Quelle -> Ziel):\n"
        f"{connector_block}\n\n"
        "Bereits erfasste Elemente (nur diese Namen als Endpunkte verwenden):\n"
        f"{element_block or '(keine)'}\n\n"
        "Regeln:\n"
        "1. Nur Beziehungen, die der Quelltext ausdruecklich nennt; nichts erfinden.\n"
        "2. Quelle und Ziel muessen in der Elementliste stehen.\n"
        "3. Der Stereotyp muss Quelle und Ziel decken; sonst Beziehung weglassen.\n"
        "4. Jede Beziehung braucht source_ref (Absatznummer).\n"
        "5. notes sind die woertlichen Saetze, die die Beziehung belegen.\n"
        "6. confidence ist eine Zahl von 0 bis 1.\n"
        "7. Antworte ausschliesslich mit JSON, ohne Markdown.\n\n"
        'Antwortform: {"elements": [], "connectors": [{"source": "...", '
        '"target": "...", "stereotype": "...", "notes": "...", '
        '"source_ref": "D1-S1", "confidence": 0.8}]}\n\n'
        "Quelltext:\n"
        f"{_source_block(batch)}\n"
    )


def _charge_name(art: str, number: int) -> str:
    return f"{art}-{number:04d}.json"


def _load_chargen(wd: Path, art: str, anzahl: int) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for number in range(1, anzahl + 1):
        pfad = wd / CHARGEN / _charge_name(art, number)
        if pfad.is_file():
            antwort = _read_json(pfad)
            if isinstance(antwort, Mapping):
                out.append(antwort)
    return out


def _start_known(start: Mapping[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for eintrag in start.get("elemente") or ():
        if not isinstance(eintrag, Mapping):
            continue
        name = str(eintrag.get("name") or "").strip()
        if name:
            out.append((name, str(eintrag.get("stereotype") or "").strip()))
    return out


def stufe2(
    *,
    workdir: str | Path,
    backend_kind: str = "openai",
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
    pause: float = 120.0,
    charge: int = extract.DEFAULT_BATCH_CHARS,
    text: str | Path | None = None,
    images: Sequence[str | Path] = (),
    backend: extract.Backend | None = None,
    log: eam_ai.Log | None = None,
) -> dict[str, Any]:
    """Prosa in Chargen extrahieren; jeder Aufruf wird gespeichert."""
    wd = _wd(workdir)
    state = _read_json(wd / STATE)
    mdg = state["mdg"]
    quelle = str(text or state.get("text") or "")
    img_list = list(images) if images else [Path(p) for p in state.get("images", [])]
    if not quelle and not img_list:
        raise StufenFehler("Stufe 2: keine Quelle gesetzt (--text, --bild oder Stufe 1 mit Quelle)")
    if quelle and not Path(quelle).is_file():
        raise StufenFehler(f"Stufe 2: Quelle {quelle} fehlt")
    rules = eam_ai.load_technology(mdg)
    rulebook = extract.load_rules(rules)
    dokument = eam_ai.read_text_source(quelle) if quelle else ""

    if backend is None:
        backend = extract.make_backend(
            backend_kind, model=model, base_url=base_url, timeout=timeout
        )

    bildbloecke: list[str] = []
    for ip in img_list:
        p_img = Path(ip)
        try:
            desc = image_input.describe_image(p_img, backend)
            bildbloecke.append(f"[Bildquelle: {p_img.name}]\n{desc}")
        except Exception:
            bildbloecke.append(f"[Bildquelle: {p_img.name}]")
    if bildbloecke:
        dokument = "\n\n".join(bildbloecke + ([dokument] if dokument.strip() else []))

    segments = extract.split_documents(dokument)
    batches = extract.plan_batches(segments, charge)
    start = _read_json(wd / STARTPAKET) if (wd / STARTPAKET).is_file() else {"elemente": []}
    known = _start_known(start)
    ausgabe = log or (lambda _message: None)

    # -- Elemente -----------------------------------------------------------
    element_dateien = [wd / CHARGEN / _charge_name("elemente", i) for i in range(1, len(batches) + 1)]
    vorhanden = [i for i, pfad in enumerate(element_dateien, start=1) if pfad.is_file()]
    for i in vorhanden:
        antwort = _read_json(element_dateien[i - 1])
        for eintrag in antwort.get("elements", ()) if isinstance(antwort, Mapping) else ():
            name = str(eintrag.get("name") or "").strip()
            if name:
                known.append((name, str(eintrag.get("stereotype") or "").strip()))
    fehlend = [i for i, pfad in enumerate(element_dateien, start=1) if not pfad.is_file()]
    aufrufe = 0
    for position, i in enumerate(fehlend):
        prompt = element_prompt(batches[i - 1], rulebook, package=str(state.get("package") or "Architektur"), known=known)
        antwort, _versuche = extract._request_answer(backend, prompt, rulebook, allow_empty=True)
        aufrufe += 1
        _write_json(element_dateien[i - 1], antwort)
        for eintrag in antwort.get("elements", ()):
            name = str(eintrag.get("name") or "").strip()
            if name:
                known.append((name, str(eintrag.get("stereotype") or "").strip()))
        ausgabe(f"Elemente {i}/{len(batches)}: {len(antwort.get('elements', ()))} Element(e)")
        if pause > 0 and position + 1 < len(fehlend):
            ausgabe(f"  Pause {pause:g}s")
            _pause(pause)

    element_answers = _load_chargen(wd, "elemente", len(batches))
    elemente = extract.merge_answers(element_answers)
    _write_json(wd / ELEMENTE, elemente)

    # -- Beziehungen --------------------------------------------------------
    beziehung_dateien = [wd / CHARGEN / _charge_name("beziehungen", i) for i in range(1, len(batches) + 1)]
    fehlend = [i for i, pfad in enumerate(beziehung_dateien, start=1) if not pfad.is_file()]
    # Auch zwischen Element- und Beziehungslauf warten: sonst liegen zwei
    # Aufrufe ohne Pause hintereinander, obwohl der Nutzer genau das vermeiden
    # will.
    if pause > 0 and aufrufe > 0 and fehlend:
        ausgabe(f"  Pause {pause:g}s vor den Beziehungen")
        _pause(pause)
    for position, i in enumerate(fehlend):
        prompt = connector_prompt(
            batches[i - 1], rulebook, elemente=elemente.get("elements", ()), known=known
        )
        antwort, _versuche = extract._request_answer(backend, prompt, rulebook, allow_empty=True)
        aufrufe += 1
        _write_json(beziehung_dateien[i - 1], antwort)
        ausgabe(f"Beziehungen {i}/{len(batches)}: {len(antwort.get('connectors', ()))} Beziehung(en)")
        if pause > 0 and position + 1 < len(fehlend):
            ausgabe(f"  Pause {pause:g}s")
            _pause(pause)

    beziehung_answers = _load_chargen(wd, "beziehungen", len(batches))
    gesamt = extract.merge_answers([*element_answers, *beziehung_answers])
    _write_json(wd / ANTWORT, gesamt)
    _write_json(
        wd / TABELLE,
        {
            "elemente": gesamt.get("elements", []),
            "beziehungen": gesamt.get("connectors", []),
        },
    )
    fortschritt = {
        "chargen": len(batches),
        "elemente": len(gesamt.get("elements", ())),
        "beziehungen": len(gesamt.get("connectors", ())),
        "aufrufe": aufrufe,
    }
    _write_json(wd / FORTSCHRITT, fortschritt)
    return {
        "antwort": str(wd / ANTWORT),
        "tabelle": str(wd / TABELLE),
        "chargen": len(batches),
        **fortschritt,
    }


# ---------------------------------------------------------------------------
# Stufe 3: Architektur bauen
# ---------------------------------------------------------------------------


def stufe3(
    *,
    workdir: str | Path,
    out: str | Path,
    startpaket: str | Path | None = None,
    katalog: str | Path | None = None,
    strict: bool = False,
    sidecar: bool = True,
    struktur: bool = True,
    mit_sichten: bool = True,
    sichten_modus: str = "leitfaden",
    wizard_dir: str | Path | None = None,
    log: eam_ai.Log | None = None,
) -> eam_ai.BuildReport:
    """Aus der Elementtabelle die Leitfaden-Architektur bauen (offline)."""
    wd = _wd(workdir)
    state = _read_json(wd / STATE)
    antwort = wd / ANTWORT
    if not antwort.is_file():
        raise StufenFehler(f"Stufe 3: {antwort} fehlt -- Stufe 2 laufen lassen")
    paket = startpaket or (state.get("startpaket") or None)
    katalog_datei = katalog or (state.get("katalog") or None)
    alt_vorlage = os.environ.get("EAM_EA_VORLAGE")
    if paket and not alt_vorlage:
        # Das Startpaket ist eine echte EA-Datei; sie liefert die Tabellenhuelle,
        # damit die Ausgabe in Enterprise Architect zu oeffnen ist. Der Writer
        # leert die Modelltabellen und setzt nur das neue Modell ein.
        os.environ["EAM_EA_VORLAGE"] = str(paket)
    try:
        report = eam_ai.build(
            mdg=state["mdg"],
            text=state.get("text") or None,
            out=out,
            package=str(state.get("package") or "Architektur"),
            backend_kind="datei",
            answer_file=antwort,
            # Das Startpaket wird NICHT als Modell zusammengefuehrt: es liefert
            # nur die EA-Tabellenhuelle und, ueber 01_steka.qea, den Katalog.
            startpaket=None,
            katalog=katalog_datei,
            struktur=struktur,
            mit_sichten=mit_sichten,
            sichten_modus=sichten_modus,
            wizard_dir=wizard_dir,
            strict=strict,
            sidecar=sidecar,
            log=log,
        )
    finally:
        if paket and not alt_vorlage:
            os.environ.pop("EAM_EA_VORLAGE", None)
    state["out"] = str(Path(out))
    _write_json(wd / STATE, state)
    return report


# ---------------------------------------------------------------------------
# Stufe 4: Pruefung
# ---------------------------------------------------------------------------


def stufe4(
    *,
    qea: str | Path,
    projekt: str = "",
    mdg: str | Path | None = None,
    rules: str | Path | None = None,
    bericht: str | Path | None = None,
) -> dict[str, Any]:
    """Leitfaden, EA-Oeffnung, Geometrie und Integritaet pruefen (optional auch MDG)."""
    pfad = Path(qea)
    if not pfad.is_file():
        raise StufenFehler(f"Stufe 4: {pfad} fehlt")
    temp_qea = None
    if pfad.suffix.lower() != ".qea":
        import tempfile
        import model_io
        with tempfile.NamedTemporaryFile(suffix=".qea", prefix="eam-st4-", delete=False) as handle:
            temp_qea = Path(handle.name)
        model_io.convert_model(pfad, temp_qea, out_format="qea")
        pruef_pfad = temp_qea
    else:
        pruef_pfad = pfad

    try:
        modell = struktur.from_qea(pruef_pfad)
        leitfaden = struktur.validate(modell, projekt or pfad.stem)
        lf_zahlen = struktur.summary(leitfaden)
        ea_oeffnung = ea_check.pruefe_datei(pruef_pfad, bereiche=("tabelle", "abfrage"))
        con = sqlite3.connect(str(pruef_pfad))
        con.execute("PRAGMA query_only = ON")
        try:
            geometrie = ea_check.pruefe_geometrie(con)
            integritaet = ea_check.pruefe_integritaet(con)
            zahlen = {
                "pakete": con.execute("SELECT COUNT(*) FROM t_package").fetchone()[0],
                "elemente": con.execute("SELECT COUNT(*) FROM t_object").fetchone()[0],
                "beziehungen": con.execute("SELECT COUNT(*) FROM t_connector").fetchone()[0],
                "sichten": con.execute("SELECT COUNT(*) FROM t_diagram").fetchone()[0],
                "sichtobjekte": con.execute("SELECT COUNT(*) FROM t_diagramobjects").fetchone()[0],
                "integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
            }
        finally:
            con.close()
    finally:
        if temp_qea:
            temp_qea.unlink(missing_ok=True)
    ea_fehler = [b for b in [*geometrie, *integritaet] if b.severity == "FEHLER"]
    ok = lf_zahlen["error"] == 0 and not ea_fehler and zahlen["integrity"] == "ok"

    mdg_ergebnis = None
    if mdg or rules:
        try:
            import validator
            ruleset = validator.load_rules(mdg or rules)
            ir = validator.load_ir(pfad)
            mdg_findings = validator.validate_model(ir, ruleset)
            mdg_summary = validator.summarize_findings(mdg_findings)
            mdg_ergebnis = {
                "summary": mdg_summary,
                "findings": mdg_findings,
            }
            if mdg_summary["error"] > 0:
                ok = False
        except Exception as exc:  # noqa: BLE001
            mdg_ergebnis = {
                "summary": {"total": 1, "error": 1, "warning": 0},
                "findings": [{"id": "MDG_LOAD_ERROR", "severity": "FEHLER", "message": str(exc)}],
            }
            ok = False

    ergebnis = {
        "qea": str(pfad),
        "projekt": projekt or pfad.stem,
        "ok": ok,
        "leitfaden": lf_zahlen,
        "leitfaden_befunde": [f.as_json() for f in leitfaden],
        "ea": {
            "oeffnung_fehler": len([b for b in ea_oeffnung if b.severity == "FEHLER"]),
            "oeffnung_befunde": [b.__dict__ for b in ea_oeffnung],
            "geometrie_fehler": len([b for b in geometrie if b.severity == "FEHLER"]),
            "integritaet_fehler": len([b for b in integritaet if b.severity == "FEHLER"]),
        },
        "geometrie": {"fehler": len([b for b in geometrie if b.severity == "FEHLER"]),
                       "befunde": [b.__dict__ for b in geometrie]},
        "integritaet": {"befunde": [b.__dict__ for b in integritaet]},
        "zahlen": zahlen,
    }
    if mdg_ergebnis is not None:
        ergebnis["mdg"] = mdg_ergebnis
    if bericht is not None:
        _write_json(Path(bericht), ergebnis)
    return ergebnis
