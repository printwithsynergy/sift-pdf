"""T1 repeat snapping — translate target die size to achievable press repeat.

Each repeat model constrains the around-cylinder dimension differently:
- geared: N_teeth × circular_pitch_pt; snap to nearest achievable
- servo: continuous in [min, max]; no snap needed
- digital-web: max frame length; use target directly (strip-packing decides length)
- digital-sheet / offset-sheet: fixed sheet; no repeat concept
"""

from __future__ import annotations

import math

from sift_pdf.schemas.press import (
    DigitalSheetRepeatModel,
    DigitalWebRepeatModel,
    GearedRepeatModel,
    OffsetSheetRepeatModel,
    PressProfile,
    RepeatModel,
    ServoRepeatModel,
)


def snap_repeat(target_pt: float, press: PressProfile) -> float | None:
    """Return the achievable repeat in points for the given target.

    Returns None for sheet presses (repeat concept does not apply).

    Raises ValueError when the target cannot be satisfied (e.g. exceeds servo range).
    """
    rm: RepeatModel = press.repeat_model
    if isinstance(rm, GearedRepeatModel):
        return _snap_geared(target_pt, rm)
    if isinstance(rm, ServoRepeatModel):
        return _snap_servo(target_pt, rm)
    if isinstance(rm, DigitalWebRepeatModel):
        return _snap_digital_web(target_pt, rm)
    if isinstance(rm, (DigitalSheetRepeatModel, OffsetSheetRepeatModel)):
        return None  # sheet press — no repeat
    raise TypeError(f"Unknown repeat model type: {type(rm)!r}")  # pragma: no cover


def _snap_geared(target_pt: float, rm: GearedRepeatModel) -> float:
    """Choose the gear that gives the closest achievable repeat ≥ target_pt.

    Achievable repeat = N_teeth × circular_pitch_pt.
    Prefer the smallest achievable repeat that fits the die (i.e. ≥ target_pt).
    If no gear is large enough, return the largest available.
    """
    candidates: list[float] = []
    for gear in rm.gear_set:
        repeat = gear.teeth * gear.circular_pitch_pt
        candidates.append(repeat)
    candidates.sort()

    # First candidate ≥ target
    for c in candidates:
        if c >= target_pt - 1e-6:
            return c
    return candidates[-1]  # largest available (die oversized for press)


def _snap_servo(target_pt: float, rm: ServoRepeatModel) -> float:
    """Clamp target to [min_repeat_pt, max_repeat_pt] — no quantisation."""
    if target_pt < rm.min_repeat_pt:
        return rm.min_repeat_pt
    if target_pt > rm.max_repeat_pt:
        raise ValueError(
            f"Target repeat {target_pt:.1f}pt exceeds servo maximum {rm.max_repeat_pt:.1f}pt."
        )
    return target_pt


def _snap_digital_web(target_pt: float, rm: DigitalWebRepeatModel) -> float:
    """Digital web: target repeat cannot exceed max_frame_pt."""
    if target_pt > rm.max_frame_pt + 1e-6:
        raise ValueError(
            f"Target repeat {target_pt:.1f}pt exceeds digital-web max frame {rm.max_frame_pt:.1f}pt."
        )
    return target_pt


def achievable_sheet(press: PressProfile) -> tuple[float, float] | None:
    """Return (width_pt, height_pt) for sheet presses, None for web presses."""
    rm = press.repeat_model
    if isinstance(rm, DigitalSheetRepeatModel):
        return (rm.sheet_width_pt, rm.sheet_height_pt)
    if isinstance(rm, OffsetSheetRepeatModel):
        return (rm.sheet_width_pt, rm.sheet_height_pt)
    return None


def usable_width(press: PressProfile) -> float | None:
    """Return the usable web width in points, accounting for press margins."""
    w = press.web_width_pt
    if w is None:
        sheet = achievable_sheet(press)
        if sheet is None:
            return None
        w = sheet[0]
    return w - press.usable_margin_left_pt - press.usable_margin_right_pt


def cells_across(cell_w_pt: float, press: PressProfile, gap_pt: float) -> int:
    """Count how many cells fit across the usable width."""
    uw = usable_width(press)
    if uw is None or uw <= 0:
        return 0
    if cell_w_pt <= 0:
        return 0
    return max(0, math.floor((uw + gap_pt) / (cell_w_pt + gap_pt)))


def cells_around(cell_h_pt: float, repeat_pt: float, gap_pt: float) -> int:
    """Count how many cells fit in one around-cylinder repeat."""
    if cell_h_pt <= 0 or repeat_pt <= 0:
        return 0
    return max(0, math.floor((repeat_pt + gap_pt) / (cell_h_pt + gap_pt)))


__all__ = [
    "snap_repeat",
    "achievable_sheet",
    "usable_width",
    "cells_across",
    "cells_around",
]
