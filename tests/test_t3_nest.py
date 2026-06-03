"""Tests for T3 nest solver (spyrrow strip-packing)."""

from __future__ import annotations

import pytest

from sift_pdf.schemas.jobs import Job
from sift_pdf.schemas.press import PressProfile, ServoRepeatModel
from sift_pdf.solve.t3_nest import solve_nest


def _rect_job(id: str, w: float, h: float, qty: int = 1000, **kw: object) -> Job:
    return Job(id=id, die={"type": "rect", "width_pt": w, "height_pt": h}, quantity=qty, **kw)  # type: ignore[arg-type]


def _poly_job(id: str, points: list[tuple[float, float]], qty: int = 500, **kw: object) -> Job:
    return Job(id=id, die={"type": "polygon", "points": points}, quantity=qty, **kw)  # type: ignore[arg-type]


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


CACHE_KEY = "b" * 64


# --- Basic solve -----------------------------------------------------------


def test_rect_nest_returns_plan() -> None:
    jobs = [_rect_job("sku-a", 200.0, 150.0), _rect_job("sku-b", 100.0, 100.0)]
    plan = solve_nest(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY
    )
    assert plan.mode == "nest"
    assert plan.tier == "T3"
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) > 0


def test_waste_pct_in_range() -> None:
    jobs = [_rect_job("sku-a", 200.0, 200.0), _rect_job("sku-b", 100.0, 100.0)]
    plan = solve_nest(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY
    )
    assert 0.0 <= plan.waste_pct <= 100.0


def test_sku_placement_map_covers_all_placements() -> None:
    jobs = [_rect_job("sku-a", 200.0, 150.0), _rect_job("sku-b", 100.0, 100.0)]
    plan = solve_nest(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY
    )
    assert plan.sku_placement_map is not None
    assert plan.explicit_placements is not None
    all_indices = sorted(i for idxs in plan.sku_placement_map.values() for i in idxs)
    assert all_indices == list(range(len(plan.explicit_placements)))


def test_single_sku_nest() -> None:
    plan = solve_nest(
        [_rect_job("sku-1", 144.0, 72.0, qty=200)],
        _sheet_press(),
        None,
        None,
        seed=42,
        budget_ms=3000,
        cache_key=CACHE_KEY,
    )
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) >= 1


# --- Polygon die -----------------------------------------------------------


def test_polygon_die_nest() -> None:
    # Triangle die
    triangle = [(0.0, 0.0), (100.0, 0.0), (50.0, 86.6)]
    jobs = [_poly_job("tri", triangle, qty=10)]
    plan = solve_nest(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY
    )
    assert plan.mode == "nest"
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) >= 1


def test_polygon_and_rect_mixed() -> None:
    quad = [(0.0, 0.0), (150.0, 0.0), (120.0, 100.0), (30.0, 100.0)]
    jobs = [
        _poly_job("para", quad, qty=5),
        _rect_job("rect", 80.0, 60.0, qty=20),
    ]
    plan = solve_nest(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY
    )
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) >= 1


# --- Bounds enforcement ----------------------------------------------------


def test_placements_within_sheet_bounds() -> None:
    press = _sheet_press(sheet_w=612.0, sheet_h=792.0)
    jobs = [_rect_job("sku-a", 100.0, 100.0), _rect_job("sku-b", 150.0, 75.0)]
    plan = solve_nest(jobs, press, None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY)
    assert plan.explicit_placements is not None
    for ep in plan.explicit_placements:
        assert ep.x0_pt >= -1e-6
        assert ep.y0_pt >= -1e-6
        assert ep.x1_pt <= 612.0 + 1e-6
        assert ep.y1_pt <= 792.0 + 1e-6


# --- Dieline-ref skipped ---------------------------------------------------


def test_dieline_ref_skipped_with_rect() -> None:
    dieline_job = Job(
        id="die-ref",
        die={"type": "dieline-ref", "die_id": "d001"},
        quantity=100,
    )
    rect_job = _rect_job("sku-a", 100.0, 100.0, qty=50)
    plan = solve_nest(
        [dieline_job, rect_job],
        _sheet_press(),
        None,
        None,
        seed=42,
        budget_ms=3000,
        cache_key=CACHE_KEY,
    )
    # dieline-ref is skipped; rect job still produces placements
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) >= 1
    assert "die-ref" not in (plan.sku_placement_map or {})


# --- Web press ------------------------------------------------------------


def test_web_press_nest() -> None:
    jobs = [_rect_job("sku-a", 100.0, 100.0), _rect_job("sku-b", 80.0, 80.0)]
    plan = solve_nest(jobs, _web_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY)
    assert plan.mode == "nest"
    assert plan.substrate.web_width_pt is not None


# --- Error cases -----------------------------------------------------------


def test_empty_jobs_raises() -> None:
    with pytest.raises(ValueError, match="At least one job"):
        solve_nest([], _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY)


def test_all_unsupported_dies_raises() -> None:
    jobs = [
        Job(id="d1", die={"type": "dieline-ref", "die_id": "d001"}, quantity=10),
        Job(id="d2", die={"type": "dieline-ref", "die_id": "d002"}, quantity=10),
    ]
    with pytest.raises(ValueError, match="no supported die jobs"):
        solve_nest(jobs, _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY)


# --- Metrics ---------------------------------------------------------------


def test_plate_count_reflects_separations() -> None:
    jobs = [
        _rect_job("sku-a", 150.0, 100.0),
        Job(
            id="sku-b",
            die={"type": "rect", "width_pt": 80.0, "height_pt": 80.0},
            quantity=200,
            separations=2,
        ),
    ]
    plan = solve_nest(
        jobs, _sheet_press(), None, None, seed=42, budget_ms=3000, cache_key=CACHE_KEY
    )
    assert plan.plate_count >= 1


# --- Determinism -----------------------------------------------------------


def test_same_seed_same_plan() -> None:
    jobs = [_rect_job("sku-a", 200.0, 150.0), _rect_job("sku-b", 100.0, 100.0)]
    press = _sheet_press()
    p1 = solve_nest(jobs, press, None, None, seed=7, budget_ms=3000, cache_key=CACHE_KEY)
    p2 = solve_nest(jobs, press, None, None, seed=7, budget_ms=3000, cache_key=CACHE_KEY)
    assert p1.waste_pct == p2.waste_pct
    assert len(p1.explicit_placements or []) == len(p2.explicit_placements or [])
