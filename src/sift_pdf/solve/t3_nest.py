"""T3 nest solver — true-shape irregular nesting using spyrrow (MIT).

Invariants (from CLAUDE.md):
- Cell position arithmetic uses codex_pdf.geom.Box. (cited: codex_pdf.geom.Box)
- Polygon bleed offset uses codex_pdf.geom.polygon_offset + Path.
  (cited: codex_pdf.geom.polygon_offset, codex_pdf.geom.Path)
- Never write PDF bytes — that is compile-pdf's job.
- DielineRefDie is not yet supported by T3; only rect and polygon dies.

Solver strategy
---------------
1. Determine form dims (sheet or web × snapped repeat).
2. For each rect/polygon die job: build spyrrow Item with polygon shape.
   - RectDie: simple rect polygon with bleed already in dimensions.
   - PolygonDie: use actual polygon points; bleed expanded via
     codex_pdf.geom.polygon_offset when pyclipr is available, otherwise
     the polygon bounding-box is expanded conservatively.
   demand = min(quantity, area-based ceiling) to cap solver work.
3. spyrrow StripPackingInstance.solve():
   - strip_height = sheet_h (sheet press) or web_width_pt (web press).
   - Config: total_computation_time = max(1, budget_ms//1000), seed = seed.
   - min_items_separation = max press gap + per-job min_gap_pt.
4. Map PlacedItem → ExplicitPlacement via AABB of rotated polygon,
   filtering placements outside [0..sheet_w] × [0..sheet_h].
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

# cited: codex_pdf.geom.Box (position arithmetic for placement bounds)
# cited: codex_pdf.geom.polygon_offset, codex_pdf.geom.Path (polygon bleed expansion)
from codex_pdf.geom import GEOM_SCHEMA_VERSION, Box

from sift_pdf.schemas.impose_plan import (
    CellSpec,
    ExplicitPlacement,
    SheetSpec,
    SiftImposePlan,
    SubstrateChoice,
)
from sift_pdf.schemas.jobs import Availability, Job, ObjectiveWeights, PolygonDie, RectDie
from sift_pdf.schemas.press import PressProfile
from sift_pdf.solve.t1_repeat_snap import achievable_sheet, snap_repeat, usable_width
from sift_pdf.version import VERSION as SIFT_VERSION

if TYPE_CHECKING:
    import spyrrow as _spyrrow


def _polygon_with_bleed(
    points: list[tuple[float, float]], bleed: float
) -> list[tuple[float, float]]:
    """Return polygon points translated to origin with bleed applied.

    For bleed > 0, uses codex_pdf.geom.polygon_offset when pyclipr is
    available (accurate for any polygon shape), otherwise falls back to
    expanding the bounding box (conservative — wastes a little space).
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, y_min = min(xs), min(ys)
    # Translate polygon to origin
    normalized = tuple((p[0] - x_min, p[1] - y_min) for p in points)

    if bleed <= 0:
        return list(normalized)

    try:
        from codex_pdf.geom import Path, polygon_offset

        path = Path(rings=(normalized,))
        result = polygon_offset(path, bleed)
        if result.rings:
            expanded = result.rings[0]
            ex_min = min(p[0] for p in expanded)
            ey_min = min(p[1] for p in expanded)
            return [(p[0] - ex_min, p[1] - ey_min) for p in expanded]
    except Exception:
        pass

    # Bounding-box fallback: inflate the bbox by bleed on all sides
    w = max(xs) - x_min + 2 * bleed
    h = max(ys) - y_min + 2 * bleed
    return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]


def _item_shape_and_area(job: Job) -> tuple[list[tuple[float, float]], float] | None:
    """Return (polygon_shape_at_origin, area) including bleed, or None for unsupported."""
    die = job.die
    bleed = job.bleed_pt

    if isinstance(die, RectDie):
        w = die.width_pt + 2 * bleed
        h = die.height_pt + 2 * bleed
        return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)], w * h

    if isinstance(die, PolygonDie):
        shape = _polygon_with_bleed(die.points, bleed)
        xs = [p[0] for p in shape]
        ys = [p[1] for p in shape]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        return shape, max(area, 1.0)

    # DielineRefDie: not yet supported
    return None


def _die_max_height(job: Job) -> float:
    """Return the die height including bleed (for web repeat calculation)."""
    die = job.die
    bleed = job.bleed_pt
    if isinstance(die, RectDie):
        return die.height_pt + 2 * bleed
    if isinstance(die, PolygonDie):
        ys = [p[1] for p in die.points]
        return max(ys) - min(ys) + 2 * bleed
    return 0.0


def _form_dims(press: PressProfile, jobs: list[Job]) -> tuple[float, float, float | None]:
    """Return (sheet_w, sheet_h, repeat_pt_or_None) for the press."""
    sheet = achievable_sheet(press)
    if sheet:
        return sheet[0], sheet[1], None

    uw = usable_width(press)
    if uw is None or uw <= 0:
        raise ValueError("Cannot determine usable web width from press profile.")

    heights: list[float] = []
    for j in jobs:
        h = _die_max_height(j)
        if h > 0:
            heights.append(h)
    if not heights:
        raise ValueError("No supported die jobs to determine web repeat.")
    repeat = snap_repeat(max(heights), press)
    if repeat is None:
        raise ValueError("Press repeat model returned None for a web press.")
    return uw, repeat, repeat


def _rotated_aabb(
    shape: list[tuple[float, float]],
    rotation_deg: float,
    tx: float,
    ty: float,
) -> tuple[float, float, float, float]:
    """AABB of shape after rotation around origin (0,0) and translation."""
    rad = math.radians(rotation_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    xs = [px * cos_a - py * sin_a + tx for px, py in shape]
    ys = [px * sin_a + py * cos_a + ty for px, py in shape]
    return min(xs), min(ys), max(xs), max(ys)


def solve_nest(
    jobs: list[Job],
    press: PressProfile,
    availability: Availability | None,
    objective: ObjectiveWeights | None,
    *,
    seed: int,
    budget_ms: int,
    cache_key: str,
) -> SiftImposePlan:
    """Solve a T3 true-shape nest layout using spyrrow.

    Maps rect and polygon dies to spyrrow Items; packs them into a strip of
    height = sheet_h (sheet) or web_width_pt (web) and reads back AABB
    positions as ExplicitPlacements.

    DielineRefDie jobs are silently skipped.
    availability is accepted for interface compatibility with T1/T2 but not
    yet used — substrate/die/press-slot constraints are planned for wave4.
    """
    # TODO(wave4): enforce availability.substrates, .dies, .presses constraints
    if not jobs:
        raise ValueError("At least one job is required for a nest solve.")

    try:
        import spyrrow
    except ImportError as exc:
        raise RuntimeError(
            "T3 nest solver requires the [nest] extra (spyrrow). "
            "Install with: pip install sift-pdf[nest]"
        ) from exc

    sheet_w, sheet_h, repeat_pt = _form_dims(press, jobs)
    form_area = sheet_w * sheet_h

    gap = max(press.gap_across_pt, press.gap_around_pt)
    for job in jobs:
        gap = max(gap, job.min_gap_pt)

    # Build spyrrow Items
    items: list[_spyrrow.Item] = []
    shapes: list[list[tuple[float, float]]] = []
    item_job_map: dict[str, int] = {}

    for i, job in enumerate(jobs):
        result = _item_shape_and_area(job)
        if result is None:
            continue
        shape, area = result
        demand = min(job.quantity, max(1, round(form_area / area)))
        items.append(
            spyrrow.Item(
                id=job.id,
                shape=shape,
                demand=demand,
                allowed_orientations=[float(r) for r in job.allowed_rotations],
            )
        )
        shapes.append(shape)
        item_job_map[job.id] = i

    if not items:
        raise ValueError("solve_nest: no supported die jobs found (rect or polygon only).")

    instance = spyrrow.StripPackingInstance(
        name=cache_key[:16],
        strip_height=sheet_h,
        items=items,
    )
    config = spyrrow.StripPackingConfig(
        total_computation_time=max(1, budget_ms // 1000),
        seed=seed % (2**31),
        min_items_separation=gap if gap > 0 else None,
    )
    solution = instance.solve(config)

    # Build shape lookup by item id
    shape_by_id: dict[str, list[tuple[float, float]]] = {
        item.id: shape for item, shape in zip(items, shapes, strict=True)
    }

    placements: list[ExplicitPlacement] = []
    for placed in solution.placed_items:
        shape = shape_by_id[placed.id]
        tx, ty = placed.translation
        x0, y0, x1, y1 = _rotated_aabb(shape, placed.rotation, tx, ty)

        # Skip placements outside the sheet bounds
        if x1 > sheet_w + 1e-6 or y1 > sheet_h + 1e-6 or x0 < -1e-6 or y0 < -1e-6:
            continue

        # cited: codex_pdf.geom.Box (position arithmetic for placement bounds)
        box = Box(x0=x0, y0=y0, x1=x1, y1=y1)
        placements.append(
            ExplicitPlacement(
                source_ref=placed.id,
                x0_pt=box.x0,
                y0_pt=box.y0,
                x1_pt=box.x1,
                y1_pt=box.y1,
                rotation=placed.rotation,
            )
        )

    if not placements:
        raise ValueError(
            "solve_nest: no placements fit within sheet bounds — "
            "check press dimensions and die sizes."
        )

    used_area = sum((p.x1_pt - p.x0_pt) * (p.y1_pt - p.y0_pt) for p in placements)
    waste_pct = max(0.0, min(100.0, (1.0 - used_area / form_area) * 100.0))

    sku_map: dict[str, list[int]] = {}
    for idx, ep in enumerate(placements):
        sku_map.setdefault(ep.source_ref, []).append(idx)

    dominant = max(placements, key=lambda p: (p.x1_pt - p.x0_pt) * (p.y1_pt - p.y0_pt))

    placed_ids = set(sku_map.keys())
    plate_count = sum(
        jobs[item_job_map[jid]].separations for jid in placed_ids if jid in item_job_map
    )

    sheet = achievable_sheet(press)
    if sheet:
        substrate = SubstrateChoice(sheet_width_pt=sheet[0], sheet_height_pt=sheet[1])
    else:
        substrate = SubstrateChoice(web_width_pt=press.web_width_pt, repeat_pt=repeat_pt)

    return SiftImposePlan(
        mode="nest",
        tier="T3",
        seed=seed,
        budget_ms=budget_ms,
        cache_key=cache_key,
        sift_version=SIFT_VERSION,
        codex_geom_schema_version=GEOM_SCHEMA_VERSION,
        substrate=substrate,
        sheet=SheetSpec(width_pt=sheet_w, height_pt=sheet_h),
        cell=CellSpec(
            width_pt=dominant.x1_pt - dominant.x0_pt,
            height_pt=dominant.y1_pt - dominant.y0_pt,
        ),
        explicit_placements=placements,
        waste_pct=waste_pct,
        material_area_pt2=form_area,
        plate_count=plate_count,
        sku_placement_map=sku_map,
    )


__all__ = ["solve_nest"]
