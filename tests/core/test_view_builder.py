# -*- coding: utf-8 -*-
"""Tests fuer view_builder und die Sichten-Optionen."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

import view_builder
import qea_writer
import model_io


RULES = {
    "viewpoints": [
        {"name": "C1 - Architecture Description", "code": "C1", "group": "Concepts"},
        {"name": "A2 - Architecture Definition", "code": "A2", "group": "Architecture Foundation"},
    ],
    "elementStereotypes": [
        {"name": "System", "metaclasses": ["Class"]},
        {"name": "Capability", "metaclasses": ["Class"]},
    ],
}

ELEMENTS = [
    {"name": "Knoten 1", "package": "Projekt - Projektarchitektur/Concepts", "stereotype": "System"},
    {"name": "Knoten 2", "package": "Projekt - Projektarchitektur/Architecture Foundation", "stereotype": "Capability"},
]

PACKAGES = [
    {"path": "Projekt"},
    {"path": "Projekt - Projektarchitektur"},
    {"path": "Projekt - Projektarchitektur/Concepts"},
    {"path": "Projekt - Projektarchitektur/Architecture Foundation"},
]


def test_view_builder_aus():
    views = view_builder.build_views(RULES, ELEMENTS, PACKAGES, "Projekt", mode="aus")
    assert views == []


def test_view_builder_leitfaden():
    views = view_builder.build_views(RULES, ELEMENTS, PACKAGES, "Projekt", mode="leitfaden")
    assert len(views) > 0
    for v in views:
        assert "name" in v
        assert "package" in v
        for m in v.get("members", []):
            assert m["top"] > m["bottom"], f"EA-Geometrie verletzt: top={m['top']}, bottom={m['bottom']}"


def test_view_builder_mdg():
    views = view_builder.build_views(RULES, ELEMENTS, PACKAGES, "Projekt", mode="mdg")
    assert len(views) == 2
    names = [v["name"] for v in views]
    assert any("C1" in n for n in names)
    assert any("A2" in n for n in names)


def test_qea_writer_default_diagram_and_geometry(tmp_path: Path):
    target = tmp_path / "test_sichten.qea"
    ir = {
        "ir_version": 1,
        "technology": {"name": "TestProfile"},
        "packages": PACKAGES,
        "elements": ELEMENTS,
        "connectors": [],
        "diagrams": [
            {
                "name": "Hauptsicht",
                "package": "Projekt - Projektarchitektur",
                "type": "Logical",
                "is_default": True,
                "members": [
                    {"element": "Projekt - Projektarchitektur/Concepts::Knoten 1", "left": 100, "top": -50, "right": 300, "bottom": -130},
                    {"element": "Projekt - Projektarchitektur/Architecture Foundation::Knoten 2", "left": 400, "top": -50, "right": 600, "bottom": -130},
                ],
            }
        ],
    }

    qea_writer.write_qea(ir, target)
    assert target.is_file()

    con = sqlite3.connect(target)
    try:
        def_diag = con.execute("SELECT Value FROM usys_system WHERE Property='DefaultDiagram'").fetchone()
        assert def_diag is not None
        assert int(def_diag[0]) > 0

        # Pruefe Geometrie
        rows = con.execute("SELECT RectLeft, RectTop, RectRight, RectBottom FROM t_diagramobjects").fetchall()
        assert len(rows) == 2
        for l, t, r, b in rows:
            assert t > b, f"RectTop muss groesser als RectBottom sein: {t} vs {b}"
    finally:
        con.close()
