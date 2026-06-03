"""Tests for Pydantic schemas — validation and round-trip."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sift_pdf.schemas.impose_plan import GridLayout, SiftImposePlan
from sift_pdf.schemas.jobs import Job
from sift_pdf.schemas.press import GearedRepeatModel, GearSpec, PressProfile, ServoRepeatModel

# --- Press profile -----------------------------------------------------------


def test_geared_press_profile() -> None:
    p = PressProfile(
        id="press-1",
        web_width_pt=864.0,
        repeat_model=GearedRepeatModel(
            type="geared",
            gear_set=[GearSpec(teeth=30, circular_pitch_pt=10.472)],
        ),
    )
    assert p.repeat_model.type == "geared"


def test_servo_press_profile() -> None:
    p = PressProfile(
        id="press-2",
        web_width_pt=1008.0,
        repeat_model=ServoRepeatModel(type="servo", min_repeat_pt=144.0, max_repeat_pt=864.0),
    )
    assert p.repeat_model.min_repeat_pt == 144.0


def test_press_profile_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PressProfile(
            id="x",
            repeat_model=ServoRepeatModel(type="servo", min_repeat_pt=1, max_repeat_pt=2),
            unknown_field="bad",
        )  # type: ignore[call-arg]


# --- Job schema -----------------------------------------------------------


def test_rect_job() -> None:
    j = Job(
        id="sku-1",
        die={"type": "rect", "width_pt": 288.0, "height_pt": 432.0},
        quantity=1000,
    )
    assert j.die.type == "rect"  # type: ignore[union-attr]


def test_job_defaults() -> None:
    j = Job(id="x", die={"type": "rect", "width_pt": 72.0, "height_pt": 72.0}, quantity=50)
    assert j.bleed_pt == 0.0
    assert j.allowed_rotations == [0]
    assert j.separations == 4


# --- GridLayout stagger ----------------------------------------------------


def test_grid_layout_stagger_modes() -> None:
    for mode in ("none", "half-drop-x", "half-drop-y", "custom"):
        gl = GridLayout(rows=4, cols=3, stagger_mode=mode)  # type: ignore[arg-type]
        assert gl.stagger_mode == mode


def test_grid_layout_rejects_bad_rotation() -> None:
    with pytest.raises(ValidationError):
        GridLayout(rows=2, cols=2, cell_rotation=45)  # type: ignore[arg-type]


# --- SiftImposePlan round-trip ----------------------------------------------


def _make_plan(**overrides: object) -> SiftImposePlan:
    base: dict = {
        "mode": "grid",
        "tier": "T1",
        "seed": 42,
        "budget_ms": 5000,
        "cache_key": "a" * 64,
        "sift_version": "0.1.0",
        "codex_geom_schema_version": "1.1.0",
        "substrate": {"web_width_pt": 864.0, "repeat_pt": 432.0},
        "sheet": {"width_pt": 864.0, "height_pt": 432.0},
        "cell": {"width_pt": 288.0, "height_pt": 432.0},
        "grid_layout": {"rows": 3, "cols": 1, "stagger_mode": "none"},
        "waste_pct": 12.5,
        "material_area_pt2": 864.0 * 432.0,
        "plate_count": 4,
    }
    base.update(overrides)
    return SiftImposePlan.model_validate(base)


def test_plan_json_roundtrip() -> None:
    plan = _make_plan()
    restored = SiftImposePlan.model_validate_json(plan.model_dump_json())
    assert restored.cache_key == plan.cache_key
    assert restored.waste_pct == plan.waste_pct


def test_plan_with_explicit_placements() -> None:
    plan = _make_plan(
        grid_layout={"rows": 2, "cols": 2, "stagger_mode": "half-drop-x"},
        explicit_placements=[
            {"source_ref": "sku-1:0", "x0_pt": 0.0, "y0_pt": 0.0, "x1_pt": 100.0, "y1_pt": 200.0}
        ],
    )
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) == 1
