"""qea_chat.py -- Frage-Antwort-Weg ueber eine vorhandene .qea.

Der Rueckweg zum Bau: statt Prosa in ein Modell zu uebersetzen, wird ein
Modell befragt. Gelesen wird ausschliesslich lesend ueber die bestehenden
Module:

* ``qea_reader.read_qea`` liefert das IR (Technologie, Pakete, Elemente),
* ``roundtrip_export.lade_modell`` liefert das Darstellungsmodell,
* ``roundtrip_export.erstelle_markdown`` liefert fuer das ganze Modell die
  lesbare Beschreibung; fuer einen Ausschnitt werden dieselben Bausteine
  (``_element_lines``) verwendet.

Ein Ausschnitt (``scope``) begrenzt den Prompt: ``{"package": "Pfad"}``
nimmt das Paket mit Unterpaketen, ``{"element": "Pfad::Name"}`` das Element
mit seinen direkten Beziehungen. Nichts ausserhalb dieses Ausschnitts geht
in den Prompt.

Ohne Backend wird nichts erfunden: die Antwort ist dann die lesbare
Beschreibung des Ausschnitts, ausdruecklich als "ohne KI" markiert.

Oeffentliche API::

    from qea_chat import ask_qea, export_answer

    answer = ask_qea("modell.qea", "Welche Dienste erbringt Paket X?",
                     scope={"package": "Architektur/Dienste"})
    export_answer(answer, "antwort.md")

CLI::

    eam-ai frage --qea modell.qea --frage "..." [--paket P | --element E] \\
        [--out antwort.md] [--backend openai]

Kein ``time``/``datetime``: die Ausgabe ist deterministisch und traegt keinen
Zeitstempel.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import extract
import qea_reader
import roundtrip_export

#: Kennung, wenn bewusst kein Sprachmodell beteiligt war.
OHNE_KI = "ohne KI"

#: Obergrenze fuer den Ausschnitt im Prompt. Groessere Ausschnitte werden mit
#: sichtbarem Hinweis gekuerzt; kleinere Ausschnitte sind der bessere Weg.
MAX_PROMPT_CHARS = 120_000

#: Obergrenze fuer Quellen im Prompt (die Beschreibung nennt sie ohnehin).
MAX_PROMPT_SOURCES = 50

PROMPT_KOPF = (
    "Du beantwortest Fragen zu einem EAM-Architekturmodell. "
    "Grundlage ist ausschliesslich der folgende Auszug aus dem Modell. "
    "Erfinde keine Elemente, Beziehungen, Zahlen oder Quellen. "
    "Wenn der Auszug die Frage nicht beantwortet, sage das ausdruecklich. "
    "Nenne als Quellen die Paketpfade oder '<Paket>::<Element>' aus dem Auszug. "
    "Antworte auf Deutsch in vollstaendigen Saetzen."
)


class QeaChatError(ValueError):
    """Frage, Ausschnitt oder Antwort taugen nicht. Immer laut."""


@dataclass
class Answer:
    """Antwort mit Ausschnitt und Quellen (alles, was zum Nachpruefen noetig ist)."""

    text: str
    scope: Mapping[str, str] | None
    sources: list[str]
    model: str
    question: str = ""
    quelle: str = ""

    @property
    def scope_label(self) -> str:
        if not self.scope:
            return "ganzes Modell"
        if "package" in self.scope:
            return f"Paket {self.scope['package']}"
        if "element" in self.scope:
            return f"Element {self.scope['element']}"
        return "Ausschnitt"


# --------------------------------------------------------------------------
# Ausschnitt
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Excerpt:
    modell: roundtrip_export.Modell
    beschreibung: str
    label: str
    sources: list[str]


def _normalize_scope(scope: Mapping[str, str] | None) -> dict[str, str] | None:
    if scope is None:
        return None
    if not isinstance(scope, Mapping):
        raise QeaChatError(
            f"scope: Objekt erwartet, gefunden {type(scope).__name__}"
        )
    keys = sorted(scope)
    if keys not in (["package"], ["element"]):
        raise QeaChatError(
            "scope: genau ein Schluessel 'package' oder 'element' erwartet, "
            f"gefunden {keys or 'nichts'}"
        )
    key = keys[0]
    value = scope[key]
    if not isinstance(value, str) or not value.strip():
        raise QeaChatError(f"scope.{key}: nicht-leerer Name erwartet")
    return {key: value.strip()}


def _resolve_package(modell: roundtrip_export.Modell, name: str) -> roundtrip_export.Paket:
    exact = [paket for paket in modell.pakete.values() if paket.path == name]
    if exact:
        return exact[0]
    by_name = [paket for paket in modell.pakete.values() if paket.name == name]
    if len(by_name) == 1:
        return by_name[0]
    paths = sorted(paket.path for paket in modell.pakete.values())
    if not by_name:
        sample = ", ".join(paths[:10]) + (" ..." if len(paths) > 10 else "")
        raise QeaChatError(
            f"Paket {name!r} nicht gefunden ({len(paths)} Pakete im Modell: {sample})"
        )
    raise QeaChatError(
        f"Paket {name!r} ist mehrdeutig: "
        + ", ".join(sorted(paket.path for paket in by_name))
        + " -- bitte den vollstaendigen Pfad angeben"
    )


def _element_candidates(
    modell: roundtrip_export.Modell, name: str
) -> list[roundtrip_export.Element]:
    exact_rel = [element for element in modell.elemente if element.ref == name]
    if exact_rel:
        return exact_rel
    exact_name = [element for element in modell.elemente if element.name == name]
    if exact_name:
        return exact_name
    folded = name.casefold()
    return [element for element in modell.elemente if element.name.casefold() == folded]


def _resolve_element(modell: roundtrip_export.Modell, name: str) -> roundtrip_export.Element:
    candidates = _element_candidates(modell, name)
    if not candidates:
        sample = ", ".join(element.ref for element in modell.elemente[:10])
        raise QeaChatError(
            f"Element {name!r} nicht gefunden ({len(modell.elemente)} Elemente; "
            f"beispielhafte Referenzen: {sample}{' ...' if len(modell.elemente) > 10 else ''})"
        )
    if len(candidates) > 1:
        raise QeaChatError(
            f"Element {name!r} ist mehrdeutig: "
            + ", ".join(sorted(element.ref for element in candidates))
            + " -- bitte '<Paket>::<Name>' angeben"
        )
    return candidates[0]


def _beziehungen(kanten: Sequence[roundtrip_export.Kante]) -> list[str]:
    lines: list[str] = []
    for kante in kanten:
        name = f" \u00b7 Name: `{kante.name}`" if kante.name else ""
        lines.append(
            f"- `{kante.quelle}` \u2192 `{kante.ziel}`"
            f" \u2014 Typ: `{kante.typ or roundtrip_export.LEER}`"
            f" \u00b7 Stereotyp: `{kante.stereotype or roundtrip_export.LEER}`{name}"
        )
    return lines


def _beschreibe_paket(
    modell: roundtrip_export.Modell, paket: roundtrip_export.Paket
) -> tuple[str, list[str]]:
    subtree = [
        item
        for item in modell.pakete.values()
        if item.path == paket.path or item.path.startswith(paket.path + "/")
    ]
    paket_ids = {item.id for item in subtree}
    elemente = sorted(
        (element for element in modell.elemente if element.paket_id in paket_ids),
        key=lambda element: (element.paket_id, element.name.casefold(), element.name, element.id),
    )
    ids = {element.id for element in elemente}
    kanten = [
        kante
        for kante in modell.kanten
        if kante.start_id in ids and kante.end_id in ids
    ]
    sichten = [sicht for sicht in modell.sichten if sicht.paket_id in paket_ids]

    lines: list[str] = [
        f"## Ausschnitt: Paket `{paket.path}` (einschliesslich Unterpaketen)",
        "",
    ]
    if paket.notes:
        lines.extend([f"Notiz: {roundtrip_export._md(paket.notes)}", ""])
    lines.append("Pakete im Ausschnitt:")
    for item in sorted(subtree, key=lambda entry: entry.path.casefold()):
        lines.append(f"- `{item.path}`")
    lines.extend(["", "Elemente im Ausschnitt:"])
    if not elemente:
        lines.append("_Keine Elemente in diesem Ausschnitt._")
    for element in elemente:
        lines.extend(
            roundtrip_export._element_lines(
                element,
                modell.tags_own.get(element.id, {}),
                modell.attribute.get(element.id, ()),
                modell.tags_xref.get(element.id, {}),
            )
        )
    lines.extend(["", "Beziehungen im Ausschnitt:"])
    relation_lines = _beziehungen(kanten)
    lines.extend(relation_lines or ["_Keine Beziehungen im Ausschnitt._"])
    if sichten:
        lines.extend(["", "Sichten im Ausschnitt:"])
        for sicht in sichten:
            lines.append(f"- {roundtrip_export._md(sicht.name)} \u2014 Typ: `{sicht.typ}`")
    sources = sorted({item.path for item in subtree})
    sources.extend(sorted({element.ref for element in elemente if element.ref}))
    return "\n".join(lines).rstrip() + "\n", sources


def _beschreibe_element(
    modell: roundtrip_export.Modell, element: roundtrip_export.Element
) -> tuple[str, list[str]]:
    paket = modell.pakete.get(element.paket_id)
    paket_path = paket.path if paket is not None else ""
    ids = {element.id}
    kanten = [
        kante
        for kante in modell.kanten
        if kante.start_id == element.id or kante.end_id == element.id
    ]
    lines = [f"## Ausschnitt: Element `{element.ref or element.name}`", ""]
    if paket_path:
        lines.extend([f"Paket: `{paket_path}`", ""])
    lines.extend(
        roundtrip_export._element_lines(
            element,
            modell.tags_own.get(element.id, {}),
            modell.attribute.get(element.id, ()),
            modell.tags_xref.get(element.id, {}),
        )
    )
    lines.extend(["", "Direkte Beziehungen:"])
    relation_lines = _beziehungen(kanten)
    lines.extend(relation_lines or ["_Keine Beziehungen._"])
    sources = [element.ref] if element.ref else []
    for kante in kanten:
        if kante.quelle and kante.quelle != element.ref:
            sources.append(kante.quelle)
        if kante.ziel and kante.ziel != element.ref:
            sources.append(kante.ziel)
    return "\n".join(lines).rstrip() + "\n", sorted(set(sources))


def _ausschnitt(modell: roundtrip_export.Modell, scope: dict[str, str] | None) -> _Excerpt:
    if scope is None:
        return _Excerpt(
            modell=modell,
            beschreibung=roundtrip_export.erstelle_markdown(modell),
            label="ganzes Modell",
            sources=sorted(paket.path for paket in modell.pakete.values()),
        )
    if "package" in scope:
        paket = _resolve_package(modell, scope["package"])
        beschreibung, sources = _beschreibe_paket(modell, paket)
        return _Excerpt(modell=modell, beschreibung=beschreibung, label=f"Paket {paket.path}", sources=sources)
    element = _resolve_element(modell, scope["element"])
    beschreibung, sources = _beschreibe_element(modell, element)
    return _Excerpt(
        modell=modell,
        beschreibung=beschreibung,
        label=f"Element {element.ref or element.name}",
        sources=sources,
    )


# --------------------------------------------------------------------------
# Prompt und Antwort
# --------------------------------------------------------------------------


def _technologie(ir: Mapping[str, Any], quelle: Path) -> str:
    technology = ir.get("technology")
    if isinstance(technology, Mapping):
        for key in ("name", "profile"):
            value = technology.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return quelle.stem


def build_prompt(
    question: str,
    label: str,
    beschreibung: str,
    *,
    technologie: str = "",
    sources: Sequence[str] = (),
    max_chars: int = MAX_PROMPT_CHARS,
) -> str:
    """Prompt aus Frage und Ausschnitt; nur der Ausschnitt geht hinein."""
    if not isinstance(question, str) or not question.strip():
        raise QeaChatError("Frage darf nicht leer sein")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
        raise QeaChatError("max_chars: ganze Zahl >= 1 erwartet")

    text = beschreibung
    hinweis = ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n"
        hinweis = (
            f"\n[Hinweis: Der Ausschnitt wurde nach {max_chars} Zeichen gekuerzt. "
            "Fuer eine vollstaendige Antwort --paket oder --element verwenden.]"
        )

    lines = [PROMPT_KOPF, ""]
    if technologie:
        lines.extend([f"Technologie: {technologie}", ""])
    lines.extend(["FRAGE:", question.strip(), "", f"AUSSCHNITT ({label}):", text])
    if hinweis:
        lines.append(hinweis)
    if sources:
        lines.extend(["", "QUELLEN IM AUSSCHNITT:"])
        for source in list(sources)[:MAX_PROMPT_SOURCES]:
            lines.append(f"- {source}")
        if len(sources) > MAX_PROMPT_SOURCES:
            lines.append(
                f"- ... {len(sources) - MAX_PROMPT_SOURCES} weitere "
                "(in der Ausschnittsbeschreibung enthalten)"
            )
    return "\n".join(lines).rstrip() + "\n"


def _ohne_ki_text(question: str, label: str, beschreibung: str) -> str:
    return (
        "# Ohne KI: Beschreibung des Ausschnitts\n\n"
        "Kein Sprachmodell beteiligt. Dies ist die lesbare Beschreibung des "
        f"Ausschnitts ({label}), keine Antwort der KI auf die Frage.\n\n"
        f"Frage: {question.strip()}\n\n"
        "---\n\n"
        f"{beschreibung.rstrip()}\n"
    )


def ask_qea(
    path: str | Path,
    question: str,
    backend: extract.Backend | None = None,
    scope: Mapping[str, str] | None = None,
) -> Answer:
    """Frage zu einer .qea beantworten -- mit Ausschnitt, Quellen und Modell.

    Ohne ``backend`` bleibt der Aufruf offline: die Antwort ist die lesbare
    Beschreibung des Ausschnitts, markiert als "ohne KI".
    """
    if not isinstance(question, str) or not question.strip():
        raise QeaChatError("Frage darf nicht leer sein")
    quelle = Path(path)
    normalized = _normalize_scope(scope)

    try:
        ir = qea_reader.read_qea(quelle)
    except qea_reader.QeaReaderError as exc:
        raise QeaChatError(f"{quelle}: {exc}") from exc
    try:
        modell = roundtrip_export.lade_modell(quelle)
    except roundtrip_export.RoundtripExportError as exc:
        raise QeaChatError(str(exc)) from exc

    excerpt = _ausschnitt(modell, normalized)
    technologie = _technologie(ir, quelle)

    if backend is None:
        return Answer(
            text=_ohne_ki_text(question, excerpt.label, excerpt.beschreibung),
            scope=normalized,
            sources=list(excerpt.sources),
            model=OHNE_KI,
            question=question.strip(),
            quelle=quelle.name,
        )

    prompt = build_prompt(
        question,
        excerpt.label,
        excerpt.beschreibung,
        technologie=technologie,
        sources=excerpt.sources,
    )
    try:
        raw = backend.complete(prompt)
    except extract.ExtractionError as exc:
        raise QeaChatError(f"Backend {getattr(backend, 'name', '?')}: {exc}") from exc
    if not isinstance(raw, str) or not raw.strip():
        raise QeaChatError(
            f"Backend {getattr(backend, 'name', '?')}: leere Antwort -- kein stilles Ergebnis"
        )
    name = getattr(backend, "name", "") or type(backend).__name__
    return Answer(
        text=raw.strip(),
        scope=normalized,
        sources=list(excerpt.sources),
        model=str(name),
        question=question.strip(),
        quelle=quelle.name,
    )


# --------------------------------------------------------------------------
# Markdown-Export
# --------------------------------------------------------------------------


def export_answer(answer: Answer, path: str | Path) -> Path:
    """Antwort als Markdown schreiben und den Pfad zurueckgeben."""
    if not isinstance(answer, Answer):
        raise QeaChatError(f"export_answer: Answer erwartet, gefunden {type(answer).__name__}")
    if not isinstance(answer.text, str) or not answer.text.strip():
        raise QeaChatError("export_answer: Antworttext ist leer")
    target = Path(path)
    if target.exists() and target.is_dir():
        raise QeaChatError(f"export_answer: {target} ist ein Verzeichnis")

    lines = ["# Frage-Antwort zum Architekturmodell", ""]
    if answer.question:
        frage = " ".join(answer.question.split())
        lines.append(f"- **Frage:** {frage}")
    if answer.quelle:
        lines.append(f"- **Modell:** `{answer.quelle}`")
    lines.append(f"- **Ausschnitt:** {answer.scope_label}")
    lines.append(f"- **Grundlage:** `{answer.model}`")
    lines.append("- **Quellen:**")
    if answer.sources:
        lines.extend(f"  - `{source}`" for source in answer.sources)
    else:
        lines.append("  - (keine)")
    lines.extend(["", "---", "", answer.text.strip(), ""])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise QeaChatError(f"export_answer: {target} nicht schreibbar ({exc})") from exc
    return target
