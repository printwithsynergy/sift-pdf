"""Tests for T1 repeat snapping."""

from __future__ import annotations

import pytest

from sift_pdf.schemas.press import (
    DigitalSheetRepeatModel,
    DigitalWebRepeatModel,
    GearedRepeatModel,
    GearSpec,
    OffsetSheetRepeatModel,
    PressProfile,
    ServoRepeatModel,
)
from sift_pdf.solve.t1_repeat_snap import (
    achievable_sheet,
    cells_across,
    snap_repeat,
    usable_width,
)


def _press(repeat_model: object, web_width: float | None = 864.0) -> PressProfile:
    return PressProfile(id="p", web_width_pt=web_width, repeat_model=repeat_model)  # type: ignore[arg-type]


# --- Geared snap -----------------------------------------------------------


def test_geared_snaps_to_nearest_above() -> None:
    rm = GearedRepeatModel(
        type="geared",
        gear_set=[
            GearSpec(teeth=30, circular_pitch_pt=10.0),  # repeat = 300
            GearSpec(teeth=40, circular_pitch_pt=10.0),  # repeat = 400
        ],
    )
    press = _press(rm)
    # Target 320 → nearest above is 400
    assert snap_repeat(320.0, press) == 400.0


def test_geared_snaps_exact_match() -> None:
    rm = GearedRepeatModel(
        type="geared",
        gear_set=[GearSpec(teeth=30, circular_pitch_pt=10.0)],
    )
    press = _press(rm)
    assert snap_repeat(300.0, press) == 300.0


def test_geared_raises_when_oversized() -> None:
    rm = GearedRepeatModel(
        type="geared",
        gear_set=[GearSpec(teeth=20, circular_pitch_pt=10.0)],
    )
    press = _press(rm)
    # Target 250 > max gear 200 → die is oversized, must raise
    with pytest.raises(ValueError, match="oversized"):
        snap_repeat(250.0, press)


# --- Servo snap -----------------------------------------------------------


def test_servo_passes_through_in_range() -> None:
    rm = ServoRepeatModel(type="servo", min_repeat_pt=144.0, max_repeat_pt=864.0)
    press = _press(rm)
    assert snap_repeat(500.0, press) == 500.0


def test_servo_clamps_to_min() -> None:
    rm = ServoRepeatModel(type="servo", min_repeat_pt=200.0, max_repeat_pt=800.0)
    press = _press(rm)
    assert snap_repeat(100.0, press) == 200.0


def test_servo_raises_above_max() -> None:
    rm = ServoRepeatModel(type="servo", min_repeat_pt=100.0, max_repeat_pt=500.0)
    press = _press(rm)
    with pytest.raises(ValueError, match="servo maximum"):
        snap_repeat(600.0, press)


# --- Digital web -----------------------------------------------------------


def test_digital_web_passes_within_frame() -> None:
    rm = DigitalWebRepeatModel(type="digital-web", max_frame_pt=1200.0)
    press = _press(rm)
    assert snap_repeat(900.0, press) == 900.0


def test_digital_web_raises_over_frame() -> None:
    rm = DigitalWebRepeatModel(type="digital-web", max_frame_pt=600.0)
    press = _press(rm)
    with pytest.raises(ValueError, match="max frame"):
        snap_repeat(700.0, press)


# --- Sheet press returns None -------------------------------------------


def test_sheet_press_returns_none() -> None:
    rm = DigitalSheetRepeatModel(type="digital-sheet", sheet_width_pt=612.0, sheet_height_pt=792.0)
    press = _press(rm, web_width=None)
    assert snap_repeat(400.0, press) is None


def test_achievable_sheet_digital() -> None:
    rm = DigitalSheetRepeatModel(type="digital-sheet", sheet_width_pt=612.0, sheet_height_pt=792.0)
    press = _press(rm, web_width=None)
    assert achievable_sheet(press) == (612.0, 792.0)


def test_achievable_sheet_offset() -> None:
    rm = OffsetSheetRepeatModel(type="offset-sheet", sheet_width_pt=1224.0, sheet_height_pt=936.0)
    press = _press(rm, web_width=None)
    assert achievable_sheet(press) == (1224.0, 936.0)


# --- usable_width -----------------------------------------------------------


def test_usable_width_web() -> None:
    rm = ServoRepeatModel(type="servo", min_repeat_pt=100.0, max_repeat_pt=800.0)
    press = PressProfile(
        id="p",
        web_width_pt=900.0,
        repeat_model=rm,
        usable_margin_left_pt=18.0,
        usable_margin_right_pt=18.0,
    )
    assert usable_width(press) == 864.0


def test_cells_across() -> None:
    rm = ServoRepeatModel(type="servo", min_repeat_pt=100.0, max_repeat_pt=800.0)
    press = PressProfile(id="p", web_width_pt=864.0, repeat_model=rm)
    # 864 / 288 = 3 cells (no gap)
    assert cells_across(288.0, press, gap_pt=0.0) == 3
    # 864 / (288 + 9) = 2 cells with 9pt gap
    assert cells_across(288.0, press, gap_pt=9.0) == 2
