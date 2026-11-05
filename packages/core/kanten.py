"""kanten.py -- Beziehungen prüfen, statt sie fallen zu lassen.

Warum dieses Modul
------------------
Der Modellaufruf schlägt Kanten vor, die die MDG nicht zulässt: ``Exhibits``
mit einer ``Capability`` als Quelle, ``Consumes`` zwischen zwei
``ServiceSpecification``. Der Validator lehnt sie zu Recht ab, ``emit``
verweigert dann den Export -- und der Nutzer sieht "0 Beziehungen".

Dieses Modul entscheidet **nicht** über die Semantik, sondern über die
Zulässigkeit:

1. Eine Kante, die die MDG besteht, bleibt unverändert.
2. Besteht sie nicht, wird der Stereotyp durch den semantisch nächsten
   ersetzt, der mit **denselben** Endpunkten zulässig ist.
3. Findet sich keiner, wird die Kante **verworfen** und mit Begründung
   gemeldet. Eine geratene Beziehung ist schlechter als keine.

Grundsatz: Wo ein Stereotyp ersetzt wird, bleibt der Beleg (source_ref,
notes) erhalten -- die Aussage steht im Quelltext, nur ihre formale
Verknüpfung ändert sich. Der Austausch wird im Bericht ausgewiesen.

Die Kandidatenreihenfolge lehnt sich an ``relation_fill.KANDIDATEN`` an und
beginnt mit den fachlich engsten Beziehungen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import validator

#: Ersatzreihenfolge bei Verstoß gegen die MDG (eng vor allgemein).
ERSATZ: tuple[str, ...] = (
    "Satisfy",
    "Implements",
    "Exhibits",
    "Consumes",
    "Provides",
    "ProvidesServiceFunction",
    "Supports",
    "OperationalExchange",
    "ResourceExchange",
    "ServiceConnector",
    "Association",
    "Composition",
    "Aggregation",
    "Dependency",
    "ConformsTo",
    "IsCapableToPerform",
)


@dataclass(frozen=True)
class KantenBefund:
    """Was mit einer Kante passiert ist."""

    source: str
    target: str
    original: str
    ersatz: str = ""
    stated: str = "kept"       # kept | replaced | dropped
    reason: str = ""

    def as_json(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "original": self.original,
            "ersatz": self.ersatz,
            "status": self.stated,
            "reason": self.reason,
        }


def _passt(ir: Mapping[str, Any], connector: Mapping[str, Any], ruleset: validator.RuleSet) -> bool:
    probe = dict(ir)
    probe["connectors"] = list(ir.get("connectors") or ()) + [dict(connector)]
    label = f"{connector['source']} -> {connector['target']} [{connector['stereotype']}]"
    try:
        findings = validator.validate_model(probe, ruleset)
    except validator.ValidatorError:
        return False
    return not any(
        finding.get("severity") == validator.ERROR
        and finding.get("check") == "forbiddenConnectorEndpoints"
        and finding.get("object") == label
        for finding in findings
    )


def _passt_allein(ir: Mapping[str, Any], connector: Mapping[str, Any], ruleset: validator.RuleSet) -> bool:
    """Prüft nur diese eine Kante, ohne die übrigen Kanten des Modells."""
    probe = dict(ir)
    probe["connectors"] = [dict(connector)]
    label = f"{connector['source']} -> {connector['target']} [{connector['stereotype']}]"
    try:
        findings = validator.validate_model(probe, ruleset)
    except validator.ValidatorError:
        return False
    return not any(
        finding.get("severity") == validator.ERROR
        and finding.get("object") == label
        for finding in findings
    )


def haerte_kanten(
    ir: dict[str, Any],
    ruleset: validator.RuleSet,
    *,
    kandidaten: Sequence[str] = ERSATZ,
    verwerfen: bool = True,
) -> list[KantenBefund]:
    """Kanten gegen die MDG härten (in place).

    Rückgabe: ein Befund je betrachteter Kante, in Eingabereihenfolge.
    """
    elemente = [e for e in ir.get("elements") or () if isinstance(e, Mapping)]
    if not elemente:
        return []
    alte = [c for c in ir.get("connectors") or () if isinstance(c, Mapping)]
    befunde: list[KantenBefund] = []
    behalten: list[dict[str, Any]] = []

    for connector in alte:
        source = str(connector.get("source") or "")
        target = str(connector.get("target") or "")
        stereotype = str(connector.get("stereotype") or "")
        if not stereotype:
            behalten.append(dict(connector))
            continue
        if _passt_allein(ir, connector, ruleset):
            behalten.append(dict(connector))
            befunde.append(KantenBefund(source, target, stereotype, stated="kept"))
            continue
        # Ersatz suchen: nur Stereotype, die es im Regelwerk gibt.
        ersatz: str | None = None
        for kandidat in kandidaten:
            if kandidat not in ruleset.connectors:
                continue
            probe = dict(connector)
            probe["stereotype"] = kandidat
            if _passt_allein(ir, probe, ruleset):
                ersatz = kandidat
                break
        if ersatz:
            neu = dict(connector)
            neu["stereotype"] = ersatz
            behalten.append(neu)
            befunde.append(
                KantenBefund(
                    source,
                    target,
                    stereotype,
                    ersatz=ersatz,
                    stated="replaced",
                    reason=(
                        f"Endpunkte fuer '{stereotype}' nach MDG nicht zulaessig; "
                        f"'{ersatz}' erlaubt dieselben Endpunkte."
                    ),
                )
            )
        elif verwerfen:
            befunde.append(
                KantenBefund(
                    source,
                    target,
                    stereotype,
                    stated="dropped",
                    reason="kein zulaessiger Stereotyp fuer diese Endpunkte -- Kante verworfen statt geraten.",
                )
            )
        else:
            behalten.append(dict(connector))
            befunde.append(KantenBefund(source, target, stereotype, stated="kept", reason="Pruefung ausgesetzt"))
    ir["connectors"] = behalten
    return befunde


def bilanz(befunde: Iterable[KantenBefund]) -> dict[str, int]:
    out = {"kept": 0, "replaced": 0, "dropped": 0}
    for befund in befunde:
        out[befund.stated] = out.get(befund.stated, 0) + 1
    return out


def bericht(befunde: Iterable[KantenBefund], limit: int = 25) -> str:
    zahlen = bilanz(befunde)
    zeilen = [
        f"Beziehungen: {zahlen['kept']} unveraendert, {zahlen['replaced']} ersetzt, "
        f"{zahlen['dropped']} verworfen (Pruefung nach MDG)"
    ]
    shown = 0
    for befund in befunde:
        if befund.stated == "kept":
            continue
        if shown >= limit:
            zeilen.append("  ... weitere")
            break
        zeilen.append(
            f"  {befund.stated:8s} {befund.source.split('::')[-1][:30]} -> "
            f"{befund.target.split('::')[-1][:30]} {befund.original}"
            + (f" => {befund.ersatz}" if befund.ersatz else "")
        )
        shown += 1
    return "\n".join(zeilen)
