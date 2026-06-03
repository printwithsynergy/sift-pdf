"""Tests for compile-pdf handoff translation."""

from __future__ import annotations

from sift_pdf.handoff.compile import to_compile_impose_plan
from sift_pdf.schemas.impose_plan import (
    CellSpec,
    ExplicitPlacement,
    GridLayout,
    SheetSpec,
    SiftImposePlan,
    SubstrateChoice,
)


def _uniform_plan() -> SiftImposePlan:
    return SiftImposePlan(
        mode="grid",
        tier="T1",
        seed=42,
        budget_ms=5000,
        cache_key="a" * 64,
        sift_version="0.1.0",
        codex_geom_schema_version="1.1.0",
        substrate=SubstrateChoice(web_width_pt=864.0, repeat_pt=432.0),
        sheet=SheetSpec(width_pt=864.0, height_pt=432.0),
        cell=CellSpec(width_pt=288.0, height_pt=432.0),
        grid_layout=GridLayout(rows=1, cols=3, stagger_mode="none"),
        waste_pct=0.0,
        material_area_pt2=864.0 * 432.0,
        plate_count=4,
    )


def _stagger_plan() -> SiftImposePlan:
    return SiftImposePlan(
        mode="grid",
        tier="T1",
        seed=42,
        budget_ms=5000,
        cache_key="b" * 64,
        sift_version="0.1.0",
        codex_geom_schema_version="1.1.0",
        substrate=SubstrateChoice(web_width_pt=864.0, repeat_pt=432.0),
        sheet=SheetSpec(width_pt=864.0, height_pt=432.0),
        cell=CellSpec(width_pt=288.0, height_pt=216.0),
        grid_layout=GridLayout(rows=2, cols=3, stagger_mode="half-drop-x"),
        explicit_placements=[
            ExplicitPlacement(source_ref="sku-1:0", x0_pt=0.0, y0_pt=0.0, x1_pt=288.0, y1_pt=216.0),
            ExplicitPlacement(
                source_ref="sku-1:0", x0_pt=144.0, y0_pt=216.0, x1_pt=432.0, y1_pt=432.0
            ),
        ],
        waste_pct=5.0,
        material_area_pt2=864.0 * 432.0,
        plate_count=4,
    )


def test_uniform_grid_produces_grid_params() -> None:
    plan = _uniform_plan()
    d = to_compile_impose_plan(plan)
    assert d["sheet"]["width_pt"] == 864.0
    assert d["cell"]["width_pt"] == 288.0
    assert "explicit_placements" not in d


def test_uniform_grid_schema_version() -> None:
    d = to_compile_impose_plan(_uniform_plan())
    assert d["schema_version"] == "1.0.0"


def test_stagger_plan_produces_explicit_placements() -> None:
    plan = _stagger_plan()
    d = to_compile_impose_plan(plan)
    assert "explicit_placements" in d
    assert len(d["explicit_placements"]) == 2


def test_stagger_placement_fields() -> None:
    plan = _stagger_plan()
    d = to_compile_impose_plan(plan)
    ep = d["explicit_placements"][0]
    assert ep["source_ref"] == "sku-1:0"
    assert ep["x0_pt"] == 0.0
    assert ep["y1_pt"] == 216.0
    assert "rotation" in ep
    assert "flip_h" in ep
