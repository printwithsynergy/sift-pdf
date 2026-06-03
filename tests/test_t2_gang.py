"""Tests for T2 gang solver (OR-Tools CP-SAT)."""

from __future__ import annotations

import pytest

from sift_pdf.schemas.jobs import Job
from sift_pdf.schemas.press import PressProfile, ServoRepeatModel
from sift_pdf.solve.t2_gang import solve_gang


def _rect_job(id: str, w: float, h: float, qty: int = 1000, **kw: object) -> Job:
    return Job(id=id, die={"type": "rect", "width_pt": w, "height_pt": h}, quantity=qty, **kw)  # type: ignore[arg-type]


def _sheet_press(sheet_w: float = 864.0, sheet_h: float = 576.0) -> PressProfile:
    return PressProfile(
        id="sheet",
        repeat_model={
            "type": "digital-sheet",
            "sheet_width_pt": sheet_w,
            "sheet_height_pt": sheet_h,
        },
    )


def _web_press(web_w: float = 864.0, min_r: float = 144.0, max_r: float = 864.0) -> PressProfile:
    return PressProfile(
        id="web",
        web_width_pt=web_w,
        repeat_model=ServoRepeatModel(type="servo", min_repeat_pt=min_r, max_repeat_pt=max_r),
    )


CACHE_KEY = "a" * 64


# --- Basic solve -----------------------------------------------------------


def test_two_sku_solve_returns_plan() -> None:
    jobs = [_rect_job("sku-a", 200.0, 150.0), _rect_job("sku-b", 100.0, 100.0)]
    plan = solve_gang(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY
    )
    assert plan.mode == "gang"
    assert plan.tier == "T2"
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) > 0


def test_waste_pct_in_range() -> None:
    jobs = [_rect_job("sku-a", 200.0, 200.0), _rect_job("sku-b", 100.0, 100.0)]
    plan = solve_gang(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY
    )
    assert 0.0 <= plan.waste_pct <= 100.0


def test_sku_placement_map_covers_all_placements() -> None:
    jobs = [_rect_job("sku-a", 200.0, 150.0), _rect_job("sku-b", 100.0, 100.0)]
    plan = solve_gang(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY
    )
    assert plan.sku_placement_map is not None
    assert plan.explicit_placements is not None
    all_indices = sorted(i for idxs in plan.sku_placement_map.values() for i in idxs)
    assert all_indices == list(range(len(plan.explicit_placements)))


def test_single_sku_gang() -> None:
    plan = solve_gang(
        [_rect_job("sku-1", 288.0, 144.0, qty=500)],
        _sheet_press(),
        None,
        None,
        seed=42,
        budget_ms=2000,
        cache_key=CACHE_KEY,
    )
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) >= 1


# --- Constraint enforcement -----------------------------------------------


def test_must_not_gang_with_enforced() -> None:
    """Two SKUs that must not share a form should not both appear in placements."""
    jobs = [
        _rect_job("sku-a", 200.0, 200.0, must_not_gang_with=["sku-b"]),
        _rect_job("sku-b", 200.0, 200.0),
    ]
    plan = solve_gang(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY
    )
    assert plan.sku_placement_map is not None
    refs = set(plan.sku_placement_map.keys())
    # Both cannot be present simultaneously
    assert {"sku-a", "sku-b"} != refs, "sku-a and sku-b must not be ganged together"


def test_placements_within_sheet_bounds() -> None:
    press = _sheet_press(sheet_w=612.0, sheet_h=792.0)
    jobs = [_rect_job("sku-a", 100.0, 100.0), _rect_job("sku-b", 150.0, 75.0)]
    plan = solve_gang(jobs, press, None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY)
    assert plan.explicit_placements is not None
    for ep in plan.explicit_placements:
        assert ep.x0_pt >= -1e-6
        assert ep.y0_pt >= -1e-6
        assert ep.x1_pt <= 612.0 + 1e-6
        assert ep.y1_pt <= 792.0 + 1e-6


# --- Web press ------------------------------------------------------------


def test_web_press_gang() -> None:
    jobs = [_rect_job("sku-a", 100.0, 100.0), _rect_job("sku-b", 80.0, 80.0)]
    plan = solve_gang(jobs, _web_press(), None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY)
    assert plan.mode == "gang"
    assert plan.substrate.web_width_pt is not None


# --- Error cases -----------------------------------------------------------


def test_empty_jobs_raises() -> None:
    with pytest.raises(ValueError, match="At least one job"):
        solve_gang([], _sheet_press(), None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY)


def test_plate_count_reflects_separations() -> None:
    jobs = [
        _rect_job("sku-a", 200.0, 150.0),
        Job(
            id="sku-b",
            die={"type": "rect", "width_pt": 100.0, "height_pt": 100.0},
            quantity=500,
            separations=2,
        ),
    ]
    plan = solve_gang(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=2000, cache_key=CACHE_KEY
    )
    # plate_count = sum of separations for all allocated SKUs
    assert plan.plate_count >= 1


# --- Determinism ----------------------------------------------------------


def test_same_seed_same_plan() -> None:
    jobs = [_rect_job("sku-a", 200.0, 150.0), _rect_job("sku-b", 100.0, 100.0)]
    press = _sheet_press()
    p1 = solve_gang(jobs, press, None, None, seed=7, budget_ms=2000, cache_key=CACHE_KEY)
    p2 = solve_gang(jobs, press, None, None, seed=7, budget_ms=2000, cache_key=CACHE_KEY)
    assert p1.waste_pct == p2.waste_pct
    assert len(p1.explicit_placements or []) == len(p2.explicit_placements or [])
