"""T1 grid solver — uniform and stagger-cut layouts.

Invariants (from CLAUDE.md):
- Rectangular uniform grid: reuse codex_pdf.geom.tile_grid — no layout math here.
  (cited: codex_pdf.geom.tile_grid, TileGrid, TileResult, CellPlacement)
- Stagger cuts: compute ExplicitPlacement positions using codex_pdf.geom.Box
  arithmetic. codex has no stagger primitive; this is new, not a reimplementation.
  (cited: codex_pdf.geom.Box)
- Never write PDF bytes — that is compile-pdf's job.

Stagger modes
-------------
half-drop-x  Odd rows are shifted right by (cell_width + gutter_x) / 2.
             Common for label stock, rounded-corner cards.
half-drop-y  Odd columns are shifted up by (cell_height + gutter_y) / 2.
             Common for web-direction cuts.
custom       Odd rows shifted by stagger_offset_pt (user-specified, any value).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Consumed codex surfaces — cite at use site per consume_surface_audit rules.
from codex_pdf.geom import (  # cited: CellPlacement, TileGrid, TileResult, tile_grid
    GEOM_SCHEMA_VERSION,
    Box,  # cited: Box (used for stagger arithmetic)
    MarksZone,
    TileGrid,
    TileResult,
    tile_grid,
)

from sift_pdf.schemas.impose_plan import (
    BleedHandling,
    CellSpec,
    ExplicitPlacement,
    GridLayout,
    MarksZoneSpec,
    SheetSpec,
    SiftImposePlan,
    StaggerMode,
    SubstrateChoice,
)
from sift_pdf.schemas.jobs import Availability, Job, ObjectiveWeights
from sift_pdf.schemas.press import PressProfile
from sift_pdf.solve.t1_repeat_snap import (
    achievable_sheet,
    snap_repeat,
)
from sift_pdf.version import VERSION as SIFT_VERSION

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def solve_grid(
    jobs: list[Job],
    press: PressProfile,
    availability: Availability | None,
    objective: ObjectiveWeights | None,
    *,
    seed: int,
    budget_ms: int,
    cache_key: str,
    stagger_mode: StaggerMode = "none",
    stagger_offset_pt: float = 0.0,
    bleed_handling: BleedHandling = "none",
) -> SiftImposePlan:
    """Solve a T1 grid or stagger layout for a single dominant SKU.

    When multiple jobs are provided, the first job's die drives the grid geometry.
    Gang (multi-SKU balancing) is a T2 concern.
    """
    if not jobs:
        raise ValueError("At least one job is required for a grid solve.")

    primary = jobs[0]
    cell_w, cell_h = _die_dims(primary)
    bleed = primary.bleed_pt
    gap_x = max(primary.min_gap_pt, press.gap_across_pt)
    gap_y = max(primary.min_gap_pt, press.gap_around_pt)

    sheet_w, sheet_h, repeat_pt = _resolve_sheet(primary, press, cell_w, cell_h, gap_y)

    marks = MarksZoneSpec()
    _ = objective  # reserved for future objective-weighted stagger (T1 uses waste % only)

    if stagger_mode == "none":
        plan = _solve_uniform(
            primary=primary,
            press=press,
            cell_w=cell_w,
            cell_h=cell_h,
            bleed=bleed,
            bleed_handling=bleed_handling,
            gap_x=gap_x,
            gap_y=gap_y,
            sheet_w=sheet_w,
            sheet_h=sheet_h,
            repeat_pt=repeat_pt,
            marks=marks,
            seed=seed,
            budget_ms=budget_ms,
            cache_key=cache_key,
        )
    else:
        plan = _solve_stagger(
            primary=primary,
            press=press,
            cell_w=cell_w,
            cell_h=cell_h,
            bleed=bleed,
            bleed_handling=bleed_handling,
            gap_x=gap_x,
            gap_y=gap_y,
            sheet_w=sheet_w,
            sheet_h=sheet_h,
            repeat_pt=repeat_pt,
            marks=marks,
            stagger_mode=stagger_mode,
            stagger_offset_pt=stagger_offset_pt,
            seed=seed,
            budget_ms=budget_ms,
            cache_key=cache_key,
        )

    return plan


# ---------------------------------------------------------------------------
# Uniform grid (reuse codex tile_grid)
# ---------------------------------------------------------------------------


def _solve_uniform(
    *,
    primary: Job,
    press: PressProfile,
    cell_w: float,
    cell_h: float,
    bleed: float,
    bleed_handling: BleedHandling,
    gap_x: float,
    gap_y: float,
    sheet_w: float,
    sheet_h: float,
    repeat_pt: float | None,
    marks: MarksZoneSpec,
    seed: int,
    budget_ms: int,
    cache_key: str,
) -> SiftImposePlan:
    grid = TileGrid(  # cited: TileGrid
        sheet=Box(0.0, 0.0, sheet_w, sheet_h),  # cited: Box
        cell_width=cell_w,
        cell_height=cell_h,
        gutter_x=gap_x,
        gutter_y=gap_y,
        marks_zone=MarksZone(
            top=marks.top_pt,
            right=marks.right_pt,
            bottom=marks.bottom_pt,
            left=marks.left_pt,
        ),
        bleed_handling=bleed_handling,
        bleed=bleed,
    )
    result: TileResult = tile_grid(grid)  # cited: tile_grid, TileResult

    rows, cols = result.rows, result.cols
    cells_total = rows * cols
    cell_area = cell_w * cell_h
    waste_pct = (
        100.0 * (1.0 - (cells_total * cell_area) / (sheet_w * sheet_h))
        if sheet_w * sheet_h > 0
        else 100.0
    )

    substrate = _substrate_choice(press, sheet_w, sheet_h, repeat_pt)

    return SiftImposePlan(
        mode="grid",
        tier="T1",
        seed=seed,
        budget_ms=budget_ms,
        cache_key=cache_key,
        sift_version=SIFT_VERSION,
        codex_geom_schema_version=GEOM_SCHEMA_VERSION,
        substrate=substrate,
        sheet=SheetSpec(width_pt=sheet_w, height_pt=sheet_h),
        cell=CellSpec(width_pt=cell_w, height_pt=cell_h),
        grid_layout=GridLayout(
            rows=rows,
            cols=cols,
            gutter_x_pt=gap_x,
            gutter_y_pt=gap_y,
            bleed_handling=bleed_handling,
            stagger_mode="none",
        ),
        bleed_pt=bleed,
        bleed_handling=bleed_handling,
        waste_pct=round(waste_pct, 2),
        material_area_pt2=sheet_w * sheet_h,
        plate_count=primary.separations,
    )


# ---------------------------------------------------------------------------
# Stagger grid (explicit placements — codex Box arithmetic)
# ---------------------------------------------------------------------------


def _solve_stagger(
    *,
    primary: Job,
    press: PressProfile,
    cell_w: float,
    cell_h: float,
    bleed: float,
    bleed_handling: BleedHandling,
    gap_x: float,
    gap_y: float,
    sheet_w: float,
    sheet_h: float,
    repeat_pt: float | None,
    marks: MarksZoneSpec,
    stagger_mode: StaggerMode,
    stagger_offset_pt: float,
    seed: int,
    budget_ms: int,
    cache_key: str,
) -> SiftImposePlan:
    """Compute stagger-cut placements using codex Box arithmetic.

    codex_pdf.geom.tile_grid produces uniform grids only; stagger offsets are
    new geometry that codex does not implement. We compute cell positions via
    Box arithmetic (not reimplementing tile_grid — extending it for a new layout type).
    Cited: codex_pdf.geom.Box
    """
    inner_w = sheet_w - marks.left_pt - marks.right_pt
    inner_h = sheet_h - marks.bottom_pt - marks.top_pt
    origin_x = marks.left_pt
    origin_y = marks.bottom_pt

    offset = _stagger_offset(stagger_mode, stagger_offset_pt, cell_w, cell_h, gap_x, gap_y)

    placements: list[ExplicitPlacement] = []
    row = 0
    y0 = origin_y
    while y0 + cell_h <= origin_y + inner_h + 1e-6:
        # Even rows: no x-offset. Odd rows: apply stagger_x offset.
        # For half-drop-y: even cols no y-offset; handled below.
        row_offset_x = offset["row_x"] if row % 2 == 1 else 0.0
        row_offset_y = offset["row_y"] if row % 2 == 1 else 0.0

        col = 0
        x0 = origin_x + row_offset_x
        while x0 + cell_w <= origin_x + inner_w + 1e-6:
            col_offset_y = offset["col_y"] if col % 2 == 1 else 0.0
            cell_y0 = y0 + row_offset_y + col_offset_y

            # cited: codex_pdf.geom.Box — used to validate cell bounds
            cell_box = Box(x0, cell_y0, x0 + cell_w, cell_y0 + cell_h)  # cited: Box
            if cell_box.y1 <= origin_y + inner_h + 1e-6:
                placements.append(
                    ExplicitPlacement(
                        source_ref=f"{primary.id}:0",
                        x0_pt=cell_box.x0,
                        y0_pt=cell_box.y0,
                        x1_pt=cell_box.x1,
                        y1_pt=cell_box.y1,
                        row=row,
                        col=col,
                    )
                )
            col += 1
            x0 += cell_w + gap_x

        row += 1
        y0 += cell_h + gap_y

    cells_total = len(placements)
    waste_pct = (
        100.0 * (1.0 - (cells_total * cell_w * cell_h) / (sheet_w * sheet_h))
        if sheet_w * sheet_h > 0
        else 100.0
    )
    # Approximate row/col count from placements for metadata
    rows = row
    cols = max((p.col or 0) for p in placements) + 1 if placements else 0

    substrate = _substrate_choice(press, sheet_w, sheet_h, repeat_pt)

    return SiftImposePlan(
        mode="grid",
        tier="T1",
        seed=seed,
        budget_ms=budget_ms,
        cache_key=cache_key,
        sift_version=SIFT_VERSION,
        codex_geom_schema_version=GEOM_SCHEMA_VERSION,
        substrate=substrate,
        sheet=SheetSpec(width_pt=sheet_w, height_pt=sheet_h),
        cell=CellSpec(width_pt=cell_w, height_pt=cell_h),
        grid_layout=GridLayout(
            rows=rows,
            cols=cols,
            gutter_x_pt=gap_x,
            gutter_y_pt=gap_y,
            bleed_handling=bleed_handling,
            stagger_mode=stagger_mode,
            stagger_offset_pt=stagger_offset_pt,
        ),
        explicit_placements=placements,
        bleed_pt=bleed,
        bleed_handling=bleed_handling,
        waste_pct=round(waste_pct, 2),
        material_area_pt2=sheet_w * sheet_h,
        plate_count=primary.separations,
    )


def _stagger_offset(
    mode: StaggerMode,
    custom_pt: float,
    cell_w: float,
    cell_h: float,
    gap_x: float,
    gap_y: float,
) -> dict[str, float]:
    """Return per-row and per-column stagger deltas."""
    if mode == "half-drop-x":
        return {"row_x": (cell_w + gap_x) / 2.0, "row_y": 0.0, "col_y": 0.0}
    if mode == "half-drop-y":
        return {"row_x": 0.0, "row_y": 0.0, "col_y": (cell_h + gap_y) / 2.0}
    if mode == "custom":
        return {"row_x": custom_pt, "row_y": 0.0, "col_y": 0.0}
    return {"row_x": 0.0, "row_y": 0.0, "col_y": 0.0}  # none


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _die_dims(job: Job) -> tuple[float, float]:
    """Extract (width_pt, height_pt) from a Job's die shape."""
    from sift_pdf.schemas.jobs import RectDie

    die = job.die
    if isinstance(die, RectDie):
        return die.width_pt, die.height_pt
    if hasattr(die, "points"):
        pts = die.points
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return max(xs) - min(xs), max(ys) - min(ys)
    raise ValueError(
        f"Cannot determine die dimensions for die type {type(die).__name__!r}. "
        "Use rect or polygon die for T1 grid solve."
    )


def _resolve_sheet(
    job: Job,
    press: PressProfile,
    cell_w: float,
    cell_h: float,
    gap_y: float,
) -> tuple[float, float, float | None]:
    """Return (sheet_w, sheet_h, repeat_pt) for the given press and die."""
    sheet = achievable_sheet(press)
    if sheet is not None:
        return sheet[0], sheet[1], None

    # Web press — determine sheet_w from web_width and sheet_h from snapped repeat.
    web_w = press.web_width_pt
    if web_w is None:
        raise ValueError("Press has no web_width_pt and is not a sheet press.")

    target_repeat = cell_h + job.bleed_pt * 2 + gap_y
    repeat = snap_repeat(target_repeat, press)
    if repeat is None:
        repeat = target_repeat

    usable_h = press.usable_margin_top_pt + press.usable_margin_bottom_pt
    sheet_h = repeat - usable_h if repeat > usable_h else repeat
    return web_w, sheet_h, repeat


def _substrate_choice(
    press: PressProfile,
    sheet_w: float,
    sheet_h: float,
    repeat_pt: float | None,
) -> SubstrateChoice:
    from sift_pdf.schemas.impose_plan import SubstrateChoice

    web_w = press.web_width_pt
    return SubstrateChoice(
        web_width_pt=web_w,
        repeat_pt=repeat_pt,
        sheet_width_pt=sheet_w if web_w is None else None,
        sheet_height_pt=sheet_h if web_w is None else None,
    )


__all__ = ["solve_grid"]
