#!/usr/bin/env python3
"""repair_loop.py -- MDG-Fehler selbsttaetig beheben, bis das Modell sauber ist.

Zweck
-----
Der Validator meldet, was gegen die Technologie verstoesst, repariert aber
nichts. Dieser Baustein schliesst die Luecke: er liest die Findings, uebersetzt
sie in konkrete Aenderungen am IR und laesst erneut pruefen -- Runde um Runde,
bis keine Fehler mehr bleiben oder das Rundenlimit erreicht ist.

Zwei Arten von Reparatur
------------------------
* **Regelbasiert, ohne KI (Pflichtpfad).** Deckt die Fehlerklassen ab, die sich
  aus dem Regelwerk eindeutig ableiten lassen:
  - ``unknownElementStereotype`` / ``unknownPackageStereotype``: Stereotyp
    entfernen, wenn er nicht in der Technologie vorkommt.
  - ``forbiddenConnectorEndpoints``: Endpunkt-Stereotyp auf den naechsten
    erlaubten Verwandten umstellen (Nachfahre des erlaubten Stereotyps bevorzugt,
    sonst der erlaubte Stereotyp selbst), weil die Kante die Aussage traegt.
  - ``invalidConnectorStereotype`` / ``unknownConnectorStereotype``: Kante
    entfernen, wenn ihr Stereotyp in der Technologie nicht existiert.
  - ``missingRequiredRelationship`` / ``forbiddenElementMetaclass``: bleiben
    stehen und werden als Handarbeit gemeldet -- hier raet das Werkzeug nicht.
* **Mit KI (optional).** Wird ein Backend uebergeben, bekommt es die verbleibenden
  Findings und das betroffene Element und darf einen Stereotyp aus der
  Technologie vorschlagen. Der Vorschlag wird gegen das Regelwerk geprueft --
  ein Vorschlag, der nicht in der Technologie steht, wird verworfen.

Grenzen, die bewusst bleiben
----------------------------
* Es wird nie eine Kante erfunden, nur um eine Pflichtbeziehung zu erfuellen.
* Das IR wird nur an Feldern geaendert, die der Fehler benennt.
* Jede Runde ist deterministisch; gleicher Ausgangslage + gleiche Regeln =
  gleiche Aenderungen. Kein Zeitstempel, keine Zufallswerte.

Nutzung
-------
    python3 repair_loop.py --mdg fixtures/...xml --ir modell.json \
        --out modell_sauber.json --max-runden 6
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import validator as val


class RepairError(RuntimeError):
    """Reparatur nicht moeglich; Meldung nennt den Grund im Klartext."""


# --------------------------------------------------------------------------
# Datenmodell
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """Eine einzelne Aenderung am IR."""

    kind: str          # stereotype_removed, stereotype_changed, connector_removed
    target: str        # Element- oder Kantenbezeichnung
    before: str
    after: str
    reason: str        # Finding-Check, die die Aenderung ausgeloest hat

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "target": self.target,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
        }


@dataclass
class Round:
    """Ergebnis einer Runde."""

    number: int
    errors_before: int
    errors_after: int
    changes: list[Change] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runde": self.number,
            "fehler_vorher": self.errors_before,
            "fehler_nachher": self.errors_after,
            "aenderungen": [c.as_dict() for c in self.changes],
        }


@dataclass
class RepairResult:
    """Gesamtergebnis des Reparaturlaufs."""

    ir: dict[str, Any]
    findings: list[dict[str, str]]
    rounds: list[Round]

    @property
    def clean(self) -> bool:
        return not any(f.get("severity") == val.ERROR for f in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sauber": self.clean,
            "runden": [r.as_dict() for r in self.rounds],
            "verbleibende_findings": self.findings,
        }


# --------------------------------------------------------------------------
# Regelwerk-Zugriff
# --------------------------------------------------------------------------


def _ea_type_for(ruleset: Any, stereotype: str) -> str | None:
    """Objektart zu einem Stereotyp.

    Aendert die Reparatur den Stereotyp, muss die Objektart mitziehen: ein
    ``ResourceRole`` ist ein ``Part``, kein ``Object``. Bleibt die alte Art
    stehen, entsteht ein Modell, das gegen die eigene Technologie verstossen
    wuerde - der Validator meldet das als Warnung, nicht als Fehler.
    """
    rule = _element_rule(ruleset, stereotype)
    if rule is None:
        return None
    for metaclass in getattr(rule, "metaclasses", ()) or ():
        if str(metaclass).strip().lower() != "package":
            return str(metaclass)
    return None


def _element_rule(ruleset: Any, stereotype: str) -> Any:
    elements = getattr(ruleset, "elements", {})
    return elements.get(stereotype) or elements.get(val._local_name(stereotype))


def _connector_rule(ruleset: Any, stereotype: str) -> Any:
    connectors = getattr(ruleset, "connectors", {})
    return connectors.get(stereotype) or connectors.get(val._local_name(stereotype))


def _descendants(ruleset: val.RuleSet, wanted: str) -> list[str]:
    """Alle Stereotype, die (transitiv) von ``wanted`` abstammen, ohne ``wanted``."""
    wanted_local = val._local_name(wanted)
    found: list[str] = []
    for name, rule in ruleset.elements.items():
        if val._local_name(name) == wanted_local:
            continue
        closure = ruleset.closures.get(name, frozenset({name}))
        if wanted_local in closure:
            found.append(name)
    return sorted(found)


def _closest_allowed(
    ruleset: val.RuleSet,
    actual: str,
    allowed: Sequence[str],
) -> str | None:
    """Waehlt den naechsten erlaubten Stereotyp fuer einen unzulaessigen Endpunkt.

    Reihenfolge:
    1. Ein Nachfahre des erlaubten Stereotyps, der selbst ein Nachfahre des
       bisherigen ist -- die Aussage des Elements bleibt erhalten, seine
       Einordnung wird praezisiert.
    2. Der erlaubte Stereotyp selbst, wenn er nicht abstrakt ist.
    3. Ein konkreter Nachfahre des erlaubten Stereotyps (alphabetisch erster).
    """
    if val.ANY in allowed:
        return None
    actual_local = val._local_name(actual)
    actual_closure = ruleset.closures.get(actual_local, frozenset({actual_local}))

    # 1. Praezisierung innerhalb beider Hullen
    for candidate in allowed:
        candidate_local = val._local_name(candidate)
        for descendant in _descendants(ruleset, candidate):
            if descendant in actual_closure:
                rule = _element_rule(ruleset, descendant)
                if rule is not None and not rule.abstract:
                    return descendant

    # 2. Der erlaubte Stereotyp selbst
    for candidate in allowed:
        rule = _element_rule(ruleset, candidate)
        if rule is not None and not rule.abstract:
            return rule.name

    # 3. Erster konkreter Nachfahre des erlaubten Stereotyps
    for candidate in allowed:
        for descendant in _descendants(ruleset, candidate):
            rule = _element_rule(ruleset, descendant)
            if rule is not None and not rule.abstract:
                return rule.name
    return None


# --------------------------------------------------------------------------
# IR-Zugriff
# --------------------------------------------------------------------------


def _iter_elements(ir: Mapping[str, Any]):
    for index, element in enumerate(ir.get("elements") or ()):
        if isinstance(element, dict):
            yield index, element


def _iter_connectors(ir: Mapping[str, Any]):
    for index, connector in enumerate(ir.get("connectors") or ()):
        if isinstance(connector, dict):
            yield index, connector


def _element_label(element: Mapping[str, Any]) -> str:
    package = str(element.get("package") or "").strip()
    name = str(element.get("name") or "").strip() or "(unbenannt)"
    return f"{package}::{name}" if package else name


def _connector_label(connector: Mapping[str, Any]) -> str:
    return f"{connector.get('source')} -> {connector.get('target')} [{connector.get('stereotype')}]"


def _find_element(ir: Mapping[str, Any], label: str) -> dict[str, Any] | None:
    for _, element in _iter_elements(ir):
        if _element_label(element) == label:
            return element
    # Zweiter Versuch ohne Paket (Validator nennt bei Paketfehlern nur das Paket)
    for _, element in _iter_elements(ir):
        if str(element.get("name") or "").strip() == label:
            return element
    return None


def _find_packages(ir: Mapping[str, Any], label: str) -> list[dict[str, Any]]:
    hit = []
    for package in ir.get("packages") or ():
        if isinstance(package, dict) and str(package.get("path") or "").strip() == label:
            hit.append(package)
    return hit


# --------------------------------------------------------------------------
# Reparaturregeln (ohne KI)
# --------------------------------------------------------------------------


def _repair_unknown_stereotype(ir: dict[str, Any], finding: Mapping[str, str]) -> Change | None:
    """Stereotyp entfernen, den die Technologie nicht kennt."""
    label = str(finding.get("object") or "")
    message = str(finding.get("message") or "")
    token = ""
    if "'" in message:
        parts = message.split("'")
        # Meldung: "... Stereotyp '<token>' ist im Regelwerk ..."
        for position, part in enumerate(parts):
            if part.strip().lower().startswith("stereotyp") and position + 1 < len(parts):
                token = parts[position + 1]
                break
        if not token and len(parts) >= 2:
            token = parts[1]

    element = _find_element(ir, label)
    if element is not None:
        before = str(element.get("stereotype") or "")
        if token and token not in before:
            return None
        element["stereotype"] = ""
        return Change(
            kind="stereotype_removed",
            target=label,
            before=before,
            after="",
            reason=str(finding.get("check") or ""),
        )

    packages = _find_packages(ir, label)
    for package in packages:
        before = str(package.get("stereotype") or "")
        package["stereotype"] = ""
        return Change(
            kind="stereotype_removed",
            target=label,
            before=before,
            after="",
            reason=str(finding.get("check") or ""),
        )
    return None


def _repair_connector_endpoints(
    ir: dict[str, Any],
    finding: Mapping[str, str],
    ruleset: val.RuleSet,
) -> list[Change]:
    """Unzulaessige Endpunkt-Stereotype auf den naechsten erlaubten umstellen."""
    label = str(finding.get("object") or "")
    rule_id = str(finding.get("rule") or "")
    rule = ruleset.connectors.get(rule_id) or _connector_rule(ruleset, rule_id)
    if rule is None:
        # Findings nennen die Regel-ID (``cr:Exhibits``), der Katalog fuehrt nur
        # den Stereotyp (``Exhibits``). Ohne diesen Schritt bliebe jede
        # Endpunkt-Reparatur wirkungslos.
        rule = _connector_rule(ruleset, rule_id.split(":")[-1])
    if rule is None:
        return []

    target_connector = None
    target_index = -1
    for index, connector in _iter_connectors(ir):
        if _connector_label(connector) == label:
            target_connector = connector
            target_index = index
            break
    if target_connector is None:
        return []

    message = str(finding.get("message") or "")
    changes: list[Change] = []
    for role, endpoint_key, allowed in (
        ("Quelle", "source", rule.source),
        ("Ziel", "target", rule.target),
    ):
        if role not in message:
            continue
        ref = str(target_connector.get(endpoint_key) or "")
        element = _find_element(ir, ref)
        if element is None:
            continue
        before = str(element.get("stereotype") or "")
        new = _closest_allowed(ruleset, before, allowed)
        if not new or new == before:
            continue
        element["stereotype"] = new
        neue_art = _ea_type_for(ruleset, new)
        if neue_art:
            element["ea_type"] = neue_art
        changes.append(
            Change(
                kind="stereotype_changed",
                target=f"{_element_label(element)} ({role} von Kante {target_index + 1})",
                before=before,
                after=new,
                reason=str(finding.get("check") or ""),
            )
        )
    return changes


def _repair_connector_stereotype(
    ir: dict[str, Any],
    finding: Mapping[str, str],
    ruleset: val.RuleSet,
) -> Change | None:
    """Kante entfernen, deren Stereotyp die Technologie nicht kennt."""
    label = str(finding.get("object") or "")
    message = str(finding.get("message") or "")
    token = ""
    parts = message.split("'")
    for position, part in enumerate(parts):
        if part.strip().lower().startswith("stereotyp") and position + 1 < len(parts):
            token = parts[position + 1]
            break

    connectors = ir.get("connectors")
    if not isinstance(connectors, list):
        return None
    for index, connector in enumerate(connectors):
        if not isinstance(connector, dict):
            continue
        if _connector_label(connector) != label:
            continue
        if token and _connector_rule(ruleset, token) is not None:
            return None
        before = str(connector.get("stereotype") or "")
        del connectors[index]
        return Change(
            kind="connector_removed",
            target=label,
            before=before,
            after="",
            reason=str(finding.get("check") or ""),
        )
    return None


# --------------------------------------------------------------------------
# KI-Reparatur (optional)
# --------------------------------------------------------------------------


def allowed_stereotypes(
    rulebook: Any,
    connector_stereotype: str,
    role: str,
) -> list[str]:
    """Zulaessige, instanziierbare Stereotype fuer eine Kantenrolle.

    Das Regelwerk der Extraktion kennt keine Vererbungs-Huellen; hier zaehlt
    nur, was die Regel an dieser Rolle ausdruecklich nennt. Abstrakte
    Stereotype fliegen raus, weil sie nicht instanziiert werden koennen.
    """
    rule = _connector_rule(rulebook, connector_stereotype)
    if rule is None:
        return []
    allowed = rule.source if role == "Quelle" else rule.target
    names: list[str] = []
    for name in allowed:
        if name == val.ANY:
            continue
        element = _element_rule(rulebook, name)
        if element is not None and not element.abstract:
            names.append(name)
    names.sort()
    return names


def _stereotypes_match_in(stereotype: str, allowed: Sequence[str]) -> bool:
    """Prueft einen Endpunkt gegen die erlaubte Liste der Regel (lokal)."""
    current = val._local_name(stereotype)
    return any(val._local_name(name) == current for name in allowed)


def _parse_verdict(raw: str, allowed: Sequence[str]) -> str | None:
    """Liest aus einer KI-Antwort genau einen erlaubten Stereotyp."""
    text = (raw or "").strip()
    if not text:
        return None
    # JSON-Antwort bevorzugen, sonst gilt der erste erlaubte Treffer im Text.
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        for key in ("klasse", "class", "stereotype", "name"):
            value = parsed.get(key)
            if isinstance(value, str):
                text = value
                break
    allowed_by_lower = {name.lower(): name for name in allowed}
    # Erst nach exakten Treffern suchen, laengste zuerst, damit
    # "ActualResourceRole" nicht von "ActualResource" geschluckt wird.
    for name in sorted(allowed_by_lower.values(), key=len, reverse=True):
        if name.lower() in text.lower():
            return name
    return None


def make_ai_fix(
    backend: Any,
    rulebook: Any,
    *,
    max_requests: int = 25,
) -> Callable[[list[dict[str, str]], dict[str, Any]], list[Change]]:
    """Baut eine Reparaturfunktion, die die KI nach einem Stereotyp fragt.

    Die KI bekommt nur Elementname, bisherigen Stereotyp, Rollenbezeichnung und
    die endliche Liste der erlaubten Stereotype. Ein Vorschlag ausserhalb dieser
    Liste wird verworfen -- die KI entscheidet, was fachlich passt, die Technologie
    entscheidet, was zulaessig ist.
    """
    if backend is None or not hasattr(backend, "complete"):
        raise RepairError("KI-Reparatur ohne verwendbares Sprachmodell")

    seen_cache: dict[str, str] = {}

    def ai_fix(
        findings: list[dict[str, str]],
        ir: dict[str, Any],
    ) -> list[Change]:
        changes: list[Change] = []
        requests = 0
        seen: set[str] = set()
        errors: list[str] = []
        if isinstance(rulebook, val.RuleSet):
            ruleset = rulebook
        elif hasattr(rulebook, "elements") and hasattr(rulebook, "connectors"):
            # extract.RuleBook: schon aufbereitet, keine zweite Ableitung noetig
            ruleset = rulebook
        else:
            ruleset = val.build_rules(rulebook)

        for finding in findings:
            if requests >= max_requests:
                break
            if finding.get("check") != "forbiddenConnectorEndpoints":
                continue
            message = str(finding.get("message") or "")
            label = str(finding.get("object") or "")
            rule_id = str(finding.get("rule") or "")
            rule = ruleset.connectors.get(rule_id) or _connector_rule(ruleset, rule_id)
            if rule is None:
                rule = _connector_rule(ruleset, rule_id.split(":")[-1])
            if rule is None:
                continue

            connector = None
            connector_index = -1
            for position, candidate in _iter_connectors(ir):
                if _connector_label(candidate) == label:
                    connector = candidate
                    connector_index = position
                    break
            if connector is None:
                continue

            subject = _endpoint_name(str(connector.get("source") or ""))
            if _belongs_to_other_title(subject):
                # Das Subjekt ist ein Element, das bloss zufaellig denselben
                # Namen wie ein Kapitel traegt (Titelknoten). Es gehoert nicht
                # in die fachliche Reparatur; die Kante wird verworfen.
                removed = _remove_connector(ir, connector_index)
                if removed is not None:
                    changes.append(removed)
                continue

            for role, key, allowed_raw in (
                ("Quelle", "source", rule.source),
                ("Ziel", "target", rule.target),
            ):
                if role not in message:
                    continue
                element = _find_element(ir, str(connector.get(key) or ""))
                if element is None:
                    continue
                before = str(element.get("stereotype") or "")
                # Nach einer Aenderung kann derselbe Endpunkt in einer anderen
                # Regel erneut auftauchen; dann gilt der aktuelle Stand.
                if before and _stereotypes_match_in(before, allowed_raw):
                    continue
                allowed = allowed_stereotypes(
                    rulebook, getattr(rule, "stereotype", None) or getattr(rule, "name", ""), role
                )
                if not allowed:
                    # Die Technologie nennt an dieser Rolle nur abstrakte
                    # Stereotype: fachlich nicht reparierbar. Statt zu raten
                    # wird die Kante verworfen und der Grund gemeldet.
                    removed = _remove_connector(ir, connector_index)
                    if removed is not None:
                        changes.append(removed)
                    if len(seen) < 20:
                        errors.append(
                            f"kein instanziierbarer Stereotyp fuer {rule_id} ({role}); Kante entfernt"
                        )
                    break
                if before in allowed:
                    continue
                if len(allowed) == 1:
                    # Nur eine Moeglichkeit: keine KI noetig.
                    allowed = allowed
                cache_key = f"{before}|{rule_id}|{role}"
                if cache_key in seen:
                    new = _parse_verdict(seen_cache.get(cache_key, ""), allowed)
                else:
                    prompt = (
                        "Ordne ein Element einer zulaessigen Klasse zu.\n"
                        f"Element: {_element_label(element)}\n"
                        f"Bisherige Klasse: {before or '(keine)'}\n"
                        f"Verbindung: {rule_id} (Rolle {role})\n"
                        f"Zulaessig sind ausschliesslich: {', '.join(allowed)}\n"
                        'Antworte als JSON: {"klasse": "<Name>"}'
                    )
                    requests += 1
                    try:
                        raw = backend.complete(prompt)
                    except Exception as exc:  # noqa: BLE001 - KI ist eine Zugabe, kein Muss
                        # Grund merken, damit der Ausfall nicht still bleibt.
                        errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                        continue
                    seen.add(cache_key)
                    seen_cache[cache_key] = raw
                    new = _parse_verdict(raw, allowed)
                if new and new != before:
                    element["stereotype"] = new
                    neue_art = _ea_type_for(ruleset, new)
                    if neue_art:
                        element["ea_type"] = neue_art
                    changes.append(
                        Change(
                            kind="stereotype_changed",
                            target=f"{_element_label(element)} ({role} von Kante '{rule_id}')",
                            before=before,
                            after=new,
                            reason="forbiddenConnectorEndpoints (KI)",
                        )
                    )
                break
        return changes

    return ai_fix



TITLE_MARKERS = (
    " Seite ",
    " | ",
    " — ",
    " – ",
    "(",
)


def _endpoint_name(ref: str) -> str:
    """Letzter Namensbestandteil einer Endpunkt-Referenz."""
    return ref.rsplit("::", 1)[-1].strip()


def _belongs_to_other_title(name: str) -> bool:
    """Heuristik: Namen mit Kapitel-/Tabellenresten sind keine Fachbegriffe."""
    text = f" {name} "
    return any(marker in text for marker in TITLE_MARKERS) or len(name) > 110


def _remove_connector_by_label(ir: dict[str, Any], label: str) -> Change | None:
    for index, connector in _iter_connectors(ir):
        if _connector_label(connector) == label:
            return _remove_connector(ir, index)
    return None


def _remove_connector(ir: dict[str, Any], index: int) -> Change | None:
    connectors = ir.get("connectors")
    if not isinstance(connectors, list) or not (0 <= index < len(connectors)):
        return None
    connector = connectors[index]
    label = _connector_label(connector)
    before = str(connector.get("stereotype") or "")
    del connectors[index]
    return Change(
        kind="connector_removed",
        target=label,
        before=before,
        after="",
        reason="forbiddenConnectorEndpoints (Titelknoten)",
    )


# --------------------------------------------------------------------------
# Ablauf
# --------------------------------------------------------------------------


REPAIRABLE = {
    "unknownElementStereotype",
    "unknownPackageStereotype",
    "forbiddenConnectorEndpoints",
    "invalidConnectorStereotype",
    "unknownConnectorStereotype",
}



def _concrete_allowed(ruleset: val.RuleSet, names: Sequence[str]) -> set[str]:
    """Nur instanziierbare Stereotype aus einer Regel-Seite."""
    result: set[str] = set()
    for name in names:
        if name == val.ANY:
            continue
        rule = _element_rule(ruleset, name)
        if rule is not None and not rule.abstract:
            result.add(val._local_name(rule.name))
    return result


def _rule_for_finding(ruleset: val.RuleSet, rule_id: str):
    rule = ruleset.connectors.get(rule_id) or _connector_rule(ruleset, rule_id)
    if rule is None:
        rule = _connector_rule(ruleset, rule_id.split(":")[-1])
    return rule


def _global_element_fix(
    ir: dict[str, Any],
    findings: Sequence[Mapping[str, str]],
    ruleset: val.RuleSet,
    pinned: dict[str, str],
) -> list[Change]:
    """Ordnet jedes beanstandete Element **einmal** so ein, dass es zu allen
    seinen Kanten passt.

    Der Unterschied zur Einzelreparatur: hier werden alle Bedingungen eines
    Elements gleichzeitig geschnitten. Damit kann eine Korrektur nicht die
    naechste Kante kaputt machen -- genau das liess die Reparatur vorher
    zwischen zwei Zustaenden hin und her springen.
    """
    constraints: dict[str, list[set[str]]] = {}
    labels: dict[str, str] = {}
    for finding in findings:
        if finding.get("severity") != val.ERROR:
            continue
        if finding.get("check") != "forbiddenConnectorEndpoints":
            continue
        rule = _rule_for_finding(ruleset, str(finding.get("rule") or ""))
        if rule is None:
            continue
        connector = None
        for _, candidate in _iter_connectors(ir):
            if _connector_label(candidate) == str(finding.get("object") or ""):
                connector = candidate
                break
        if connector is None:
            continue
        message = str(finding.get("message") or "")
        for role, key, names in (
            ("Quelle", "source", rule.source),
            ("Ziel", "target", rule.target),
        ):
            if role not in message:
                continue
            element = _find_element(ir, str(connector.get(key) or ""))
            if element is None:
                continue
            label = _element_label(element)
            allowed = _concrete_allowed(ruleset, names)
            if not allowed:
                continue
            constraints.setdefault(label, []).append(allowed)
            labels[label] = str(connector.get(key) or "")

    changes: list[Change] = []
    for label in sorted(constraints):
        element = _find_element(ir, label)
        if element is None:
            continue
        sets = constraints[label]
        before = str(element.get("stereotype") or "")
        current = val._local_name(before)
        if label in pinned:
            continue  # einmal festgelegt, bleibt festgelegt
        # Nicht der Schnitt (der ist oft leer), sondern die Einordnung, die die
        # meisten Kanten erfuellt. Bei Gleichstand bleibt der bestehende Wert.
        candidates: set[str] = set()
        for allowed in sets:
            candidates |= allowed
        if not candidates:
            continue
        best_score = -1
        chosen = ""
        for candidate in sorted(candidates):
            score = sum(1 for allowed in sets if candidate in allowed)
            if score > best_score or (
                score == best_score and candidate == current
            ):
                best_score = score
                chosen = candidate
        if not chosen:
            continue
        pinned[label] = chosen
        if chosen == current:
            continue
        element["stereotype"] = chosen
        neue_art = _ea_type_for(ruleset, chosen)
        if neue_art:
            element["ea_type"] = neue_art
        changes.append(
            Change(
                kind="stereotype_changed",
                target=f"{label} (global, {len(constraints[label])} Bedingung(en))",
                before=before,
                after=chosen,
                reason="forbiddenConnectorEndpoints (Schnitt aller Kanten)",
            )
        )
    return changes



def _prune_invalid(ir: dict[str, Any], ruleset: val.RuleSet) -> list[Change]:
    """Entfernt alle Kanten, deren Endpunkte nach ihrer Regel nicht passen.

    Wird nach der globalen Zuordnung ausgefuehrt: was dann noch unzulaessig
    ist, passt fachlich nicht zu dieser Einordnung. Das geschieht in **einem**
    Durchlauf, nicht Kante fuer Kante ueber viele Runden.
    """
    changes: list[Change] = []
    connectors = ir.get("connectors")
    if not isinstance(connectors, list):
        return changes
    keep: list[Any] = []
    for connector in connectors:
        if not isinstance(connector, dict):
            keep.append(connector)
            continue
        rule = _connector_rule(ruleset, str(connector.get("stereotype") or ""))
        if rule is None:
            keep.append(connector)
            continue
        source = _find_element(ir, str(connector.get("source") or ""))
        target = _find_element(ir, str(connector.get("target") or ""))
        if source is None or target is None:
            keep.append(connector)
            continue
        ok_source = val._stereotypes_match(
            (str(source.get("stereotype") or ""),), rule.source, ruleset.closures
        )
        ok_target = val._stereotypes_match(
            (str(target.get("stereotype") or ""),), rule.target, ruleset.closures
        )
        if ok_source and ok_target:
            keep.append(connector)
            continue
        label = _connector_label(connector)
        changes.append(
            Change(
                kind="connector_removed",
                target=label,
                before=str(connector.get("stereotype") or ""),
                after="",
                reason="forbiddenConnectorEndpoints (passt nicht zur Einordnung)",
            )
        )
    if len(keep) != len(connectors):
        ir["connectors"] = keep
    return changes


def _apply_round(
    ir: dict[str, Any],
    findings: Sequence[Mapping[str, str]],
    ruleset: val.RuleSet,
    pinned: dict[str, str] | None = None,
) -> list[Change]:
    """Wendet alle Reparaturen einer Runde an (jede Stelle hoechstens einmal)."""
    # Zuerst die globale Zuordnung: ein Element, eine Klasse, alle Kanten.
    pinned = pinned if pinned is not None else {}
    changes: list[Change] = _global_element_fix(ir, findings, ruleset, pinned)
    touched: set[str] = set()

    for finding in findings:
        if finding.get("severity") != val.ERROR:
            continue
        check = str(finding.get("check") or "")
        if check not in REPAIRABLE:
            continue
        label = str(finding.get("object") or "")
        key = f"{check}|{label}|{finding.get('rule')}"
        if key in touched:
            continue

        change: Change | None = None
        if check in ("unknownElementStereotype", "unknownPackageStereotype"):
            change = _repair_unknown_stereotype(ir, finding)
        if check == "forbiddenConnectorEndpoints":
            # Die Einordnung eines Elements wird global entschieden. Bleibt eine
            # Kante trotzdem unzulaessig, passt sie nicht zu dieser Einordnung
            # und wird entfernt -- nicht das Element erneut umetikettiert.
            if changes:
                continue
            removed = _remove_connector_by_label(ir, str(finding.get("object") or ""))
            if removed is not None:
                changes.append(removed)
            touched.add(key)
            continue
        elif check in ("invalidConnectorStereotype", "unknownConnectorStereotype"):
            change = _repair_connector_stereotype(ir, finding, ruleset)
        if change is not None:
            changes.append(change)
            touched.add(key)

    # Aufraeumen in einem Zug: alles, was jetzt nicht mehr passt, fliegt raus.
    changes.extend(_prune_invalid(ir, ruleset))
    return changes


def repair(
    ir: Mapping[str, Any],
    rules: Mapping[str, Any] | val.RuleSet,
    *,
    max_rounds: int = 6,
    ai_fix: Callable[[list[dict[str, str]], dict[str, Any]], list[Change]] | None = None,
) -> RepairResult:
    """Repariert ein IR, bis es keine Fehler mehr gibt oder das Limit erreicht ist.

    ``ai_fix`` ist optional: bekommt die verbleibenden Findings und das IR und
    liefert weitere Aenderungen. Ohne ``ai_fix`` laeuft alles regelbasiert.
    """
    if max_rounds < 1:
        raise RepairError("max_rounds muss mindestens 1 sein")

    ruleset = rules if isinstance(rules, val.RuleSet) else val.build_rules(rules)
    work = copy.deepcopy(dict(ir))
    rounds: list[Round] = []
    pinned: dict[str, str] = {}
    findings = val.validate_model(work, ruleset)

    for number in range(1, max_rounds + 1):
        errors_before = sum(1 for f in findings if f.get("severity") == val.ERROR)
        if errors_before == 0:
            break
        changes = _apply_round(work, findings, ruleset, pinned)
        if ai_fix is not None:
            # Auch nach regelbasierten Aenderungen bleibt meist ein Rest, den
            # nur die fachliche Zuordnung loesen kann.
            remaining = [f for f in findings if f.get("severity") == val.ERROR]
            changes.extend(ai_fix(remaining, work))
        if not changes:
            break
        findings = val.validate_model(work, ruleset)
        errors_after = sum(1 for f in findings if f.get("severity") == val.ERROR)
        rounds.append(
            Round(
                number=number,
                errors_before=errors_before,
                errors_after=errors_after,
                changes=changes,
            )
        )
        if errors_after >= errors_before:
            # Kein Fortschritt: nicht weiterdrehen, sonst aendert sich still etwas.
            break

    return RepairResult(ir=work, findings=list(findings), rounds=rounds)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _load_rules(path: Path) -> Mapping[str, Any]:
    import mdg_parser

    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return mdg_parser.parse_mdg(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="IR mit MDG-Regelwerk selbsttaetig reparieren.",
    )
    parser.add_argument("--mdg", required=True, help="MDG-XML oder rules.json")
    parser.add_argument("--ir", required=True, help="IR als JSON")
    parser.add_argument("--out", required=True, help="Ziel der reparierten IR")
    parser.add_argument("--bericht", default=None, help="Bericht als JSON")
    parser.add_argument("--max-runden", type=int, default=6)
    args = parser.parse_args(argv)

    ir = json.loads(Path(args.ir).read_text(encoding="utf-8"))
    rules = _load_rules(Path(args.mdg))
    result = repair(ir, rules, max_rounds=args.max_runden)

    Path(args.out).write_text(
        json.dumps(result.ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.bericht:
        Path(args.bericht).write_text(
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    for runde in result.rounds:
        print(
            f"Runde {runde.number}: {runde.errors_before} -> {runde.errors_after} Fehler, "
            f"{len(runde.changes)} Aenderung(en)"
        )
    rest = [f for f in result.findings if f.get("severity") == val.ERROR]
    print(f"Ergebnis: {len(rest)} Fehler verbleiben; {'sauber' if result.clean else 'nicht sauber'}")
    return 0 if result.clean else 1


if __name__ == "__main__":
    sys.exit(main())
