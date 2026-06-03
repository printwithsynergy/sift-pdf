"""Tests for T1 grid and stagger-cut solver."""

from __future__ import annotations

import pytest

from sift_pdf.cache import cache_clear
from sift_pdf.schemas.jobs import Job
from sift_pdf.schemas.press import PressProfile, ServoRepeatModel
from sift_pdf.solve.t1_grid import solve_grid


@pytest.fixture(autouse=True)
def clear() -> None:
    cache_clear()


def _servo_press(
    web_width: float = 864.0, min_r: float = 144.0, max_r: float = 864.0
) -> PressProfile:
    return PressProfile(
        id="test-servo",
        web_width_pt=web_width,
        repeat_model=ServoRepeatModel(type="servo", min_repeat_pt=min_r, max_repeat_pt=max_r),
    )


def _rect_job(w: float = 288.0, h: float = 144.0, qty: int = 1000) -> Job:
    return Job(
        id="sku-1",
        die={"type": "rect", "width_pt": w, "height_pt": h},
        quantity=qty,
    )


def _key() -> str:
    return "a" * 64


# --- Uniform grid -----------------------------------------------------------


def test_uniform_grid_row_col_count() -> None:
    job = _rect_job(w=288.0, h=144.0)
    press = _servo_press(web_width=864.0, min_r=144.0, max_r=864.0)
    plan = solve_grid([job], press, None, None, seed=42, budget_ms=5000, cache_key=_key())

    assert plan.tier == "T1"
    assert plan.mode == "grid"
    assert plan.grid_layout is not None
    assert plan.grid_layout.stagger_mode == "none"
    # 864 / 288 = 3 across
    assert plan.grid_layout.cols == 3
    assert plan.explicit_placements is None


def test_uniform_grid_waste_in_range() -> None:
    job = _rect_job(w=288.0, h=144.0)
    press = _servo_press(web_width=864.0)
    plan = solve_grid([job], press, None, None, seed=42, budget_ms=5000, cache_key=_key())
    assert 0.0 <= plan.waste_pct <= 100.0


def test_uniform_grid_plate_count_equals_separations() -> None:
    job = Job(
        id="sku-1",
        die={"type": "rect", "width_pt": 288.0, "height_pt": 144.0},
        separations=6,
        quantity=500,
    )
    press = _servo_press()
    plan = solve_grid([job], press, None, None, seed=42, budget_ms=5000, cache_key=_key())
    assert plan.plate_count == 6


def test_uniform_grid_codex_geom_schema_version_present() -> None:
    job = _rect_job()
    press = _servo_press()
    plan = solve_grid([job], press, None, None, seed=42, budget_ms=5000, cache_key=_key())
    assert plan.codex_geom_schema_version != ""


# --- Stagger cuts -----------------------------------------------------------


def test_half_drop_x_produces_explicit_placements() -> None:
    job = _rect_job(w=288.0, h=144.0)
    press = _servo_press(web_width=864.0)
    plan = solve_grid(
        [job],
        press,
        None,
        None,
        seed=42,
        budget_ms=5000,
        cache_key=_key(),
        stagger_mode="half-drop-x",
    )
    assert plan.grid_layout is not None
    assert plan.grid_layout.stagger_mode == "half-drop-x"
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) > 0


def test_half_drop_y_produces_explicit_placements() -> None:
    job = _rect_job(w=144.0, h=288.0)
    press = _servo_press(web_width=864.0, min_r=288.0, max_r=864.0)
    plan = solve_grid(
        [job],
        press,
        None,
        None,
        seed=42,
        budget_ms=5000,
        cache_key=_key(),
        stagger_mode="half-drop-y",
    )
    assert plan.explicit_placements is not None


def test_custom_stagger_uses_offset() -> None:
    job = _rect_job(w=200.0, h=200.0)
    press = _servo_press(web_width=800.0, min_r=200.0, max_r=800.0)
    plan = solve_grid(
        [job],
        press,
        None,
        None,
        seed=42,
        budget_ms=5000,
        cache_key=_key(),
        stagger_mode="custom",
        stagger_offset_pt=50.0,
    )
    assert plan.explicit_placements is not None
    # Odd-row cells should be shifted by 50pt relative to even-row cells
    placements = plan.explicit_placements
    even_row = [p for p in placements if (p.row or 0) % 2 == 0]
    odd_row = [p for p in placements if (p.row or 0) % 2 == 1]
    if even_row and odd_row:
        # Odd rows start 50pt to the right of even rows (at the same col)
        even_x0s = sorted(p.x0_pt for p in even_row)
        odd_x0s = sorted(p.x0_pt for p in odd_row)
        assert abs(odd_x0s[0] - even_x0s[0] - 50.0) < 1e-3


def test_stagger_placement_bounds_within_sheet() -> None:
    job = _rect_job(w=200.0, h=100.0)
    press = _servo_press(web_width=800.0, min_r=100.0, max_r=800.0)
    plan = solve_grid(
        [job],
        press,
        None,
        None,
        seed=42,
        budget_ms=5000,
        cache_key=_key(),
        stagger_mode="half-drop-x",
    )
    sheet_w = plan.sheet.width_pt
    sheet_h = plan.sheet.height_pt
    for p in plan.explicit_placements or []:
        assert p.x0_pt >= -1e-6
        assert p.y0_pt >= -1e-6
        assert p.x1_pt <= sheet_w + 1e-6
        assert p.y1_pt <= sheet_h + 1e-6


def test_stagger_source_ref_contains_job_id() -> None:
    job = _rect_job(w=288.0, h=144.0)
    press = _servo_press()
    plan = solve_grid(
        [job],
        press,
        None,
        None,
        seed=42,
        budget_ms=5000,
        cache_key=_key(),
        stagger_mode="half-drop-x",
    )
    for p in plan.explicit_placements or []:
        assert "sku-1" in p.source_ref


def test_no_jobs_raises() -> None:
    press = _servo_press()
    with pytest.raises(ValueError, match="At least one job"):
        solve_grid([], press, None, None, seed=42, budget_ms=5000, cache_key=_key())
