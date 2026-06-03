"""Tests for CJD envelope handoff (to_cjd_envelope)."""

from __future__ import annotations

import pytest

from sift_pdf.handoff.compile import to_cjd_envelope
from sift_pdf.schemas.impose_plan import (
    CellSpec,
    ExplicitPlacement,
    GridLayout,
    MarksIntent,
    MarksZoneSpec,
    SheetSpec,
    SiftImposePlan,
    SubstrateChoice,
)


def _grid_plan(marks_intent: MarksIntent | None = None) -> SiftImposePlan:
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
        marks_zone=MarksZoneSpec(),
        grid_layout=GridLayout(rows=1, cols=3, stagger_mode="none"),
        waste_pct=0.0,
        material_area_pt2=864.0 * 432.0,
        plate_count=4,
        marks_intent=marks_intent,
    )


def _explicit_plan() -> SiftImposePlan:
    return SiftImposePlan(
        mode="nest",
        tier="T3",
        seed=7,
        budget_ms=3000,
        cache_key="b" * 64,
        sift_version="0.1.0",
        codex_geom_schema_version="1.1.0",
        substrate=SubstrateChoice(sheet_width_pt=612.0, sheet_height_pt=792.0),
        sheet=SheetSpec(width_pt=612.0, height_pt=792.0),
        cell=CellSpec(width_pt=144.0, height_pt=144.0),
        explicit_placements=[
            ExplicitPlacement(
                source_ref="sku-1", x0_pt=0.0, y0_pt=0.0, x1_pt=144.0, y1_pt=144.0
            ),
            ExplicitPlacement(
                source_ref="sku-2", x0_pt=150.0, y0_pt=0.0, x1_pt=294.0, y1_pt=144.0
            ),
        ],
        waste_pct=30.0,
        material_area_pt2=612.0 * 792.0,
        plate_count=2,
    )


_REFS = {"sku-1": "s3://bucket/sku-1.pdf", "sku-2": "s3://bucket/sku-2.pdf"}


def test_cjd_structure_has_schema_and_steps() -> None:
    env = to_cjd_envelope(_grid_plan(), {"sku-1": "s3://bucket/sku-1.pdf"})
    assert env["schema_version"] == "1.0.0"
    assert "steps" in env
    assert isinstance(env["steps"], list)


def test_cjd_carries_sift_cache_key() -> None:
    plan = _grid_plan()
    env = to_cjd_envelope(plan, {"sku-1": "s3://bucket/sku-1.pdf"})
    assert env["sift_cache_key"] == plan.cache_key


def test_cjd_grid_has_compose_then_impose() -> None:
    env = to_cjd_envelope(_grid_plan(), {"sku-1": "s3://bucket/sku-1.pdf"})
    types = [s["type"] for s in env["steps"]]
    assert types == ["compose", "impose"]


def test_cjd_with_marks_intent_inserts_marks_step() -> None:
    intent = MarksIntent(registration_marks=True, crop_marks=True)
    env = to_cjd_envelope(_grid_plan(marks_intent=intent), {"sku-1": "s3://bucket/sku-1.pdf"})
    types = [s["type"] for s in env["steps"]]
    assert types == ["compose", "marks", "impose"]


def test_cjd_marks_step_fields() -> None:
    intent = MarksIntent(registration_marks=True, crop_marks=False, bearer_bars=True)
    env = to_cjd_envelope(_grid_plan(marks_intent=intent), {"sku-1": "s3://bucket/sku-1.pdf"})
    marks_step = next(s for s in env["steps"] if s["type"] == "marks")
    assert marks_step["registration_marks"] is True
    assert marks_step["crop_marks"] is False
    assert marks_step["bearer_bars"] is True
    assert marks_step["eye_marks"] is False


def test_cjd_no_marks_step_when_marks_intent_none() -> None:
    env = to_cjd_envelope(_grid_plan(marks_intent=None), {"sku-1": "s3://bucket/sku-1.pdf"})
    types = [s["type"] for s in env["steps"]]
    assert "marks" not in types


def test_cjd_compose_step_sources() -> None:
    env = to_cjd_envelope(_explicit_plan(), _REFS)
    compose = env["steps"][0]
    assert compose["type"] == "compose"
    source_map = {s["source_ref"]: s["url"] for s in compose["sources"]}
    assert source_map["sku-1"] == "s3://bucket/sku-1.pdf"
    assert source_map["sku-2"] == "s3://bucket/sku-2.pdf"


def test_cjd_impose_step_has_plan() -> None:
    env = to_cjd_envelope(_explicit_plan(), _REFS)
    impose = env["steps"][-1]
    assert impose["type"] == "impose"
    assert "plan" in impose
    assert impose["plan"]["schema_version"] == "1.0.0"


def test_cjd_explicit_plan_impose_has_placements() -> None:
    env = to_cjd_envelope(_explicit_plan(), _REFS)
    impose_plan = env["steps"][-1]["plan"]
    assert "explicit_placements" in impose_plan
    assert len(impose_plan["explicit_placements"]) == 2


def test_cjd_raises_on_empty_source_refs() -> None:
    with pytest.raises(ValueError, match="source_refs must not be empty"):
        to_cjd_envelope(_grid_plan(), {})


def test_cjd_canonical_step_order_with_marks() -> None:
    """compose → marks → impose is the canonical compile-pdf order."""
    intent = MarksIntent(crop_marks=True)
    env = to_cjd_envelope(_grid_plan(marks_intent=intent), {"sku-1": "s3://bucket/sku-1.pdf"})
    types = [s["type"] for s in env["steps"]]
    assert types.index("compose") < types.index("marks") < types.index("impose")
