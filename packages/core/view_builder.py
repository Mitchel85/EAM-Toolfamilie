# -*- coding: utf-8 -*-
"""Sichten-Generator: Sparx-EA-Sichten gemaess MDG, Leitfaden oder Model Wizard.

Unterstuetzt 4 Modi:
  - aus:       Keine Diagramme (fuer reine Daten-Pipelines)
  - leitfaden: Die 52 Standard-Sichten des Leitfadens (Standard)
  - mdg:       Dynamisch aus den MDG-Viewpoints und ModelTemplates abgeleitete Sichten
  - wizard:    Model-Wizard-Vorlagen (aus lokalem Verzeichnis oder MDG-Vorlagenbestand)

Erzeugt deterministische, lesbare Gitter-Layouts mit EA-konformen Koordinaten
(RectTop > RectBottom).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import leitfaden
import wizard


def layout_members(
    elements: Sequence[Mapping[str, Any]],
    columns: int = 4,
    x_gap: int = 260,
    y_gap: int = 110,
    width: int = 220,
    height: int = 70,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Platziert Elemente in einem sauberen, lesbaren Gitter-Layout.
    
    EA-Geometrie: y waechst nach unten, Koordinaten sind negativ.
    RectTop = top, RectBottom = bottom.
    Es gilt stets: top > bottom (top - bottom = height > 0).
    """
    members: list[dict[str, Any]] = []
    for position, el in enumerate(elements[:limit]):
        ref = el.get("ref") or (
            f"{el.get('package')}::{el.get('name')}" if el.get("package") else el.get("name")
        )
        col = position % columns
        row = position // columns
        left = col * x_gap
        top = -(row * y_gap)
        right = left + width
        bottom = top - height
        members.append(
            {
                "element": ref,
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "sequence": position,
            }
        )
    return members


def build_views(
    rules: Mapping[str, Any],
    elements: Sequence[Mapping[str, Any]],
    packages: Sequence[Mapping[str, Any]],
    projekt: str,
    *,
    mode: str = "leitfaden",
    wizard_dir: str | Path | None = None,
    max_elemente_je_sicht: int = 30,
    mit_startseite: bool = True,
) -> list[dict[str, Any]]:
    """Erzeugt Sichten gemaess gewaehltem Modus."""
    mode = str(mode or "leitfaden").lower().strip()
    if mode == "aus" or mode == "none" or mode == "ohne":
        return []

    vorhandene_pakete = {str(p.get("path") or "") for p in packages}
    arch_pfad = f"{projekt} - Projektarchitektur"
    start_pfad = f"{projekt} - Startseite"
    diagrams: list[dict[str, Any]] = []

    # Map von Elementen nach Paket und Stereotyp
    by_package: dict[str, list[Mapping[str, Any]]] = {}
    by_stereo: dict[str, list[Mapping[str, Any]]] = {}
    for el in elements:
        pkg = str(el.get("package") or "")
        st = str(el.get("stereotype") or "")
        by_package.setdefault(pkg, []).append(el)
        if st:
            by_stereo.setdefault(st, []).append(el)

    viewpoints = {}
    for vp in rules.get("viewpoints") or ():
        vp_code = vp.get("code") or (vp.get("name") or "").split(" ")[0].strip()
        if vp_code:
            viewpoints[vp_code] = vp

    def find_target_package(desired_subpath: str) -> str:
        kand = f"{arch_pfad}/{desired_subpath}"
        if kand in vorhandene_pakete:
            return kand
        for p in vorhandene_pakete:
            if desired_subpath in p:
                return p
        return arch_pfad if arch_pfad in vorhandene_pakete else (list(vorhandene_pakete)[0] if vorhandene_pakete else "")

    if mode == "wizard" and wizard_dir and Path(wizard_dir).is_dir():
        # Echte Model-Wizard-Vorlagen aus lokalem Verzeichnis
        vorlagen = wizard.lade_alle(wizard_dir)
        for code, vorlage in sorted(vorlagen.items()):
            target_pkg = find_target_package(code)
            # Passende Elemente fuer diese Vorlage sammeln
            kand_elements: list[Mapping[str, Any]] = []
            seen_refs = set()
            for st in vorlage.stereotype:
                for el in by_stereo.get(st, ()):
                    r = el.get("name")
                    if r and r not in seen_refs:
                        seen_refs.add(r)
                        kand_elements.append(el)

            d_name = f"{projekt} : {vorlage.name}"
            members = layout_members(kand_elements, limit=max_elemente_je_sicht)
            diagrams.append(
                {
                    "name": d_name,
                    "package": target_pkg,
                    "type": "Logical",
                    "mdg": f"NAFv4-ADMBw-MDG-2026.05::{code}",
                    "notes": f"Model Wizard Vorlage {code}: {vorlage.name}",
                    "default": (code in ("C1", "A2") and len(diagrams) == 0),
                    "is_default": (code in ("C1", "A2") and len(diagrams) == 0),
                    "members": members,
                }
            )
        return diagrams

    if mode == "mdg":
        # Sichten rein aus MDG-Viewpoints / ModelTemplates
        mdg_vps = rules.get("viewpoints") or []
        for vp in sorted(mdg_vps, key=lambda x: str(x.get("name") or "")):
            vp_name = str(vp.get("name") or "")
            vp_code = vp.get("code") or vp_name.split(" ")[0].strip()
            target_pkg = find_target_package(vp_code)
            group = str(vp.get("group") or "")
            mdg_ref = f"{group}::{vp_name}" if group else vp_name

            # Elemente sammeln
            kand_elements = []
            seen_names = set()
            for p, p_els in by_package.items():
                if vp_code in p:
                    for el in p_els:
                        en = el.get("name")
                        if en and en not in seen_names:
                            seen_names.add(en)
                            kand_elements.append(el)

            members = layout_members(kand_elements, limit=max_elemente_je_sicht)
            diagrams.append(
                {
                    "name": f"{projekt} : {vp_name}",
                    "package": target_pkg,
                    "type": "Custom",
                    "mdg": mdg_ref,
                    "notes": f"MDG-Sicht fuer Viewpoint {vp_name}",
                    "default": (vp_code in ("C1", "A2") and len(diagrams) == 0),
                    "is_default": (vp_code in ("C1", "A2") and len(diagrams) == 0),
                    "members": members,
                }
            )
        return diagrams

    # Standard-Modus: leitfaden (52 Standard-Sichten)
    already = set()
    for rule in leitfaden.DIAGRAMS:
        name = leitfaden.expand_projekt(rule.name, projekt)
        pkg_cand = f"{arch_pfad}/{rule.package}"
        target = pkg_cand if pkg_cand in vorhandene_pakete else find_target_package(rule.viewpoint)
        if not target:
            continue
        key = (target, name)
        if key in already:
            continue
        already.add(key)

        # Elemente sammeln
        kand_elements = []
        seen_names = set()
        pflicht_stereos = set(leitfaden.PFLICHT_STEREOTYPE.get(rule.viewpoint, ()))
        if pflicht_stereos:
            for st in pflicht_stereos:
                for el in by_stereo.get(st, ()):
                    en = el.get("name")
                    if en and en not in seen_names:
                        seen_names.add(en)
                        kand_elements.append(el)

        for el in by_package.get(target, ()):
            en = el.get("name")
            if en and en not in seen_names:
                seen_names.add(en)
                kand_elements.append(el)

        vp_def = viewpoints.get(rule.viewpoint)
        mdg_vp = ""
        if vp_def:
            grp = vp_def.get("group") or ""
            mdg_vp = f"{grp}::{vp_def.get('name')}" if grp else str(vp_def.get("name") or "")

        is_def = (rule.viewpoint == "St" or (rule.viewpoint in ("C1", "A2") and len(diagrams) == 0))
        members = layout_members(kand_elements, limit=max_elemente_je_sicht)
        diagrams.append(
            {
                "name": name,
                "package": target,
                "type": leitfaden.DIAGRAM_EA_TYPE,
                "mdg": mdg_vp,
                "notes": f"{rule.code}: {rule.diagram_type}",
                "default": is_def,
                "is_default": is_def,
                "members": members,
            }
        )

    return diagrams


def enrich_ir_with_views(
    ir: Mapping[str, Any],
    mode: str = "leitfaden",
    *,
    wizard_dir: str | Path | None = None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reichert ein IR-Dict mit Sichten gemaess gewaehltem Modus an."""
    if rules is None:
        rules = {}
    projekt = "Architektur"
    if ir.get("packages"):
        pkgs = ir["packages"]
        if pkgs and isinstance(pkgs[0], Mapping):
            projekt = pkgs[0].get("name") or pkgs[0].get("path") or "Architektur"
    diagrams = build_views(
        rules,
        ir.get("elements", []),
        ir.get("packages", []),
        projekt,
        mode=mode,
        wizard_dir=wizard_dir,
    )
    result = dict(ir)
    result["diagrams"] = list(ir.get("diagrams", [])) + diagrams
    return result
