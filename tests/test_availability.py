"""Tests for availability constraint enforcement in T2 and T3 solvers."""

from __future__ import annotations

import pytest

from sift_pdf.schemas.jobs import (
    Availability,
    DieStock,
    Job,
    RectDie,
    SubstrateStock,
)
from sift_pdf.schemas.press import PressProfile, ServoRepeatModel
from sift_pdf.solve.t2_gang import _cell_from_job, solve_gang
from sift_pdf.solve.t3_nest import _item_shape_and_area, solve_nest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _servo_press(**kw: object) -> PressProfile:
    defaults: dict = {
        "id": "p1",
        "web_width_pt": 612.0,
        "repeat_model": ServoRepeatModel(type="servo", min_repeat_pt=72.0, max_repeat_pt=612.0),
    }
    defaults.update(kw)
    return PressProfile(**defaults)


def _rect_job(job_id: str = "j1", w: float = 72.0, h: float = 72.0, qty: int = 100) -> Job:
    return Job(id=job_id, die=RectDie(type="rect", width_pt=w, height_pt=h), quantity=qty)


def _dieline_job(job_id: str = "dl1", die_id: str = "die-a", qty: int = 100, **kw: object) -> Job:
    from sift_pdf.schemas.jobs import DielineRefDie

    return Job(id=job_id, die=DielineRefDie(type="dieline-ref", die_id=die_id), quantity=qty, **kw)


def _availability(
    dies: list[DieStock] | None = None,
    substrates: list[SubstrateStock] | None = None,
) -> Availability:
    return Availability(dies=dies or [], substrates=substrates or [])


CACHE_KEY = "a" * 64


# ---------------------------------------------------------------------------
# DielineRefDie shape resolution — T2
# ---------------------------------------------------------------------------


def test_t2_cell_from_dieline_rect_die() -> None:
    """DielineRefDie with rect shape in DieStock resolves to a _Cell."""
    job = _dieline_job()
    avail = _availability(dies=[DieStock(id="die-a", qty=1, width_pt=144.0, height_pt=72.0)])
    cell = _cell_from_job(job, 0, avail)
    assert cell is not None
    assert cell.w == pytest.approx(144.0)
    assert cell.h == pytest.approx(72.0)


def test_t2_cell_from_dieline_polygon_die() -> None:
    """DielineRefDie with polygon_points resolves using bounding box."""
    job = _dieline_job()
    avail = _availability(
        dies=[
            DieStock(
                id="die-a",
                qty=1,
                polygon_points=[(0, 0), (100, 0), (100, 50), (0, 50)],
            )
        ]
    )
    cell = _cell_from_job(job, 0, avail)
    assert cell is not None
    assert cell.w == pytest.approx(100.0)
    assert cell.h == pytest.approx(50.0)


def test_t2_cell_from_dieline_no_availability_returns_none() -> None:
    """DielineRefDie without availability snapshot → None (skip)."""
    job = _dieline_job()
    assert _cell_from_job(job, 0, None) is None


def test_t2_cell_from_dieline_unknown_die_id_returns_none() -> None:
    """DielineRefDie with unknown die_id → None (not in snapshot)."""
    job = _dieline_job(die_id="unknown")
    avail = _availability(dies=[DieStock(id="die-a", qty=1, width_pt=72.0, height_pt=72.0)])
    assert _cell_from_job(job, 0, avail) is None


def test_t2_cell_from_dieline_no_shape_info_returns_none() -> None:
    """DielineRefDie with matching DieStock but no shape info → None."""
    job = _dieline_job()
    avail = _availability(dies=[DieStock(id="die-a", qty=1)])
    assert _cell_from_job(job, 0, avail) is None


# ---------------------------------------------------------------------------
# DielineRefDie shape resolution — T3
# ---------------------------------------------------------------------------


def test_t3_item_shape_from_dieline_rect() -> None:
    """DielineRefDie resolved to rect polygon via DieStock width/height."""
    job = _dieline_job()
    avail = _availability(dies=[DieStock(id="die-a", qty=1, width_pt=100.0, height_pt=50.0)])
    result = _item_shape_and_area(job, avail)
    assert result is not None
    shape, area = result
    xs = [p[0] for p in shape]
    ys = [p[1] for p in shape]
    assert max(xs) == pytest.approx(100.0)
    assert max(ys) == pytest.approx(50.0)
    assert area == pytest.approx(5000.0)


def test_t3_item_shape_from_dieline_polygon() -> None:
    """DielineRefDie resolved to polygon via DieStock polygon_points."""
    job = _dieline_job()
    pts = [(0.0, 0.0), (80.0, 0.0), (80.0, 40.0), (0.0, 40.0)]
    avail = _availability(dies=[DieStock(id="die-a", qty=1, polygon_points=pts)])
    result = _item_shape_and_area(job, avail)
    assert result is not None


def test_t3_item_shape_dieline_no_availability_returns_none() -> None:
    job = _dieline_job()
    assert _item_shape_and_area(job, None) is None


def test_t3_item_shape_dieline_with_bleed() -> None:
    """Bleed is added to resolved DielineRefDie dimensions."""
    from sift_pdf.schemas.jobs import DielineRefDie

    job = Job(
        id="dl",
        die=DielineRefDie(type="dieline-ref", die_id="die-a"),
        bleed_pt=9.0,
        quantity=100,
    )
    avail = _availability(dies=[DieStock(id="die-a", qty=1, width_pt=72.0, height_pt=72.0)])
    result = _item_shape_and_area(job, avail)
    assert result is not None
    shape, _ = result
    xs = [p[0] for p in shape]
    ys = [p[1] for p in shape]
    assert max(xs) == pytest.approx(72.0 + 18.0)
    assert max(ys) == pytest.approx(72.0 + 18.0)


# ---------------------------------------------------------------------------
# required_die_id enforcement — T2
# ---------------------------------------------------------------------------


def test_t2_required_die_not_in_snapshot_raises() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        required_die_id="missing-die",
    )
    avail = _availability()
    with pytest.raises(ValueError, match="not found in availability snapshot"):
        solve_gang([job], _servo_press(), avail, None, seed=0, budget_ms=1000, cache_key=CACHE_KEY)


def test_t2_required_die_out_of_stock_raises() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        required_die_id="die-a",
    )
    avail = _availability(dies=[DieStock(id="die-a", qty=0)])
    with pytest.raises(ValueError, match="out of stock"):
        solve_gang([job], _servo_press(), avail, None, seed=0, budget_ms=1000, cache_key=CACHE_KEY)


def test_t2_required_die_in_stock_passes() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        required_die_id="die-a",
    )
    avail = _availability(dies=[DieStock(id="die-a", qty=2)])
    plan = solve_gang(
        [job], _servo_press(), avail, None, seed=0, budget_ms=1000, cache_key=CACHE_KEY
    )
    assert plan.tier == "T2"


# ---------------------------------------------------------------------------
# allowed_substrate_ids enforcement — T2
# ---------------------------------------------------------------------------


def test_t2_allowed_substrate_none_in_stock_raises() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        allowed_substrate_ids=["sub-premium"],
    )
    avail = _availability(
        substrates=[SubstrateStock(id="sub-economy", width_pt=612.0, qty_on_hand=10)]
    )
    with pytest.raises(ValueError, match="No allowed substrate"):
        solve_gang([job], _servo_press(), avail, None, seed=0, budget_ms=1000, cache_key=CACHE_KEY)


def test_t2_allowed_substrate_zero_qty_raises() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        allowed_substrate_ids=["sub-a"],
    )
    avail = _availability(substrates=[SubstrateStock(id="sub-a", width_pt=612.0, qty_on_hand=0)])
    with pytest.raises(ValueError, match="No allowed substrate"):
        solve_gang([job], _servo_press(), avail, None, seed=0, budget_ms=1000, cache_key=CACHE_KEY)


def test_t2_allowed_substrate_in_stock_passes() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        allowed_substrate_ids=["sub-a"],
    )
    avail = _availability(substrates=[SubstrateStock(id="sub-a", width_pt=612.0, qty_on_hand=5)])
    plan = solve_gang(
        [job], _servo_press(), avail, None, seed=0, budget_ms=1000, cache_key=CACHE_KEY
    )
    assert plan.tier == "T2"


# ---------------------------------------------------------------------------
# required_die_id enforcement — T3
# ---------------------------------------------------------------------------


def test_t3_required_die_not_in_snapshot_raises() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        required_die_id="missing-die",
    )
    avail = _availability()
    with pytest.raises(ValueError, match="not found in availability snapshot"):
        solve_nest([job], _servo_press(), avail, None, seed=0, budget_ms=500, cache_key=CACHE_KEY)


def test_t3_required_die_out_of_stock_raises() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        required_die_id="die-a",
    )
    avail = _availability(dies=[DieStock(id="die-a", qty=0)])
    with pytest.raises(ValueError, match="out of stock"):
        solve_nest([job], _servo_press(), avail, None, seed=0, budget_ms=500, cache_key=CACHE_KEY)


def test_t3_allowed_substrate_none_in_stock_raises() -> None:
    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=72.0, height_pt=72.0),
        quantity=10,
        allowed_substrate_ids=["sub-premium"],
    )
    avail = _availability(
        substrates=[SubstrateStock(id="sub-economy", width_pt=612.0, qty_on_hand=10)]
    )
    with pytest.raises(ValueError, match="No allowed substrate"):
        solve_nest([job], _servo_press(), avail, None, seed=0, budget_ms=500, cache_key=CACHE_KEY)


def test_t3_no_availability_skips_constraints() -> None:
    """Without an availability snapshot, no constraints are enforced."""
    from sift_pdf.schemas.press import DigitalSheetRepeatModel

    job = Job(
        id="j1",
        die=RectDie(type="rect", width_pt=144.0, height_pt=144.0),
        quantity=10,
        required_die_id="any-die",
        allowed_substrate_ids=["any-substrate"],
    )
    sheet_press = PressProfile(
        id="sheet",
        repeat_model=DigitalSheetRepeatModel(
            type="digital-sheet", sheet_width_pt=612.0, sheet_height_pt=792.0
        ),
    )
    plan = solve_nest([job], sheet_press, None, None, seed=42, budget_ms=1000, cache_key=CACHE_KEY)
    assert plan.tier == "T3"
