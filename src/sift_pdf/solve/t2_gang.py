"""T2 gang solver — multi-SKU quantity balancing using OR-Tools CP-SAT.

Invariants (from CLAUDE.md):
- Cell position arithmetic uses codex_pdf.geom.Box. (cited: codex_pdf.geom.Box)
- Never write PDF bytes — that is compile-pdf's job.
- Polygon and dieline-ref dies are not yet supported by T2; only rect.

Solver strategy
---------------
1. Determine form dimensions (sheet or web × snapped repeat).
2. For each rect-die job: compute bleed box (cell_w, cell_h).
3. CP-SAT quantity allocation:
   - n[i] = integer copies of SKU i on one form (0 .. max_fit_area).
   - Area constraint: sum(n[i] * area[i]) ≤ form_area.
   - mustNotGangWith pairs: used[i] + used[j] ≤ 1.
   - Objective: maximise sum(n[i] * area[i]) (minimise waste).
   - Time budget: budget_ms.
4. Greedy strip-packer to convert quantities into (x,y) ExplicitPlacements.
"""

from __future__ import annotations

from typing import NamedTuple

# cited: codex_pdf.geom.Box (used for strip-packing position arithmetic)
from codex_pdf.geom import GEOM_SCHEMA_VERSION, Box
from ortools.sat.python import cp_model

from sift_pdf.schemas.impose_plan import (
    CellSpec,
    ExplicitPlacement,
    SheetSpec,
    SiftImposePlan,
    SubstrateChoice,
)
from sift_pdf.schemas.jobs import (
    Availability,
    DielineRefDie,
    DieStock,
    Job,
    ObjectiveWeights,
    RectDie,
)
from sift_pdf.schemas.press import PressProfile
from sift_pdf.solve.t1_repeat_snap import achievable_sheet, snap_repeat, usable_width
from sift_pdf.version import VERSION as SIFT_VERSION


class _Cell(NamedTuple):
    job_index: int
    source_ref: str
    w: float
    h: float


def _resolve_dieline_rect(
    die: DielineRefDie, bleed: float, availability: Availability | None
) -> tuple[float, float] | None:
    """Return (w, h) with bleed for a DielineRefDie if shape info is available."""
    if availability is None:
        return None
    stock: DieStock | None = next((d for d in availability.dies if d.id == die.die_id), None)
    if stock is None:
        return None
    if stock.width_pt is not None and stock.height_pt is not None:
        return stock.width_pt + 2 * bleed, stock.height_pt + 2 * bleed
    if stock.polygon_points is not None and len(stock.polygon_points) >= 3:
        xs = [p[0] for p in stock.polygon_points]
        ys = [p[1] for p in stock.polygon_points]
        return (max(xs) - min(xs)) + 2 * bleed, (max(ys) - min(ys)) + 2 * bleed
    return None


def _cell_from_job(job: Job, i: int, availability: Availability | None = None) -> _Cell | None:
    """Return _Cell for a rect or resolved-dieline job, None for unsupported shapes."""
    die = job.die
    if isinstance(die, RectDie):
        return _Cell(
            job_index=i,
            source_ref=job.id,
            w=die.width_pt + 2 * job.bleed_pt,
            h=die.height_pt + 2 * job.bleed_pt,
        )
    if isinstance(die, DielineRefDie):
        dims = _resolve_dieline_rect(die, job.bleed_pt, availability)
        if dims is None:
            return None
        return _Cell(job_index=i, source_ref=job.id, w=dims[0], h=dims[1])
    return None


def _form_dims(press: PressProfile, jobs: list[Job]) -> tuple[float, float, float | None]:
    """Return (sheet_w, sheet_h, repeat_pt_or_None) for the press."""
    sheet = achievable_sheet(press)
    if sheet:
        return sheet[0], sheet[1], None

    uw = usable_width(press)
    if uw is None or uw <= 0:
        raise ValueError("Cannot determine usable web width from press profile.")

    rect_heights = [j.die.height_pt + 2 * j.bleed_pt for j in jobs if isinstance(j.die, RectDie)]
    if not rect_heights:
        raise ValueError("No rect-die jobs to determine web repeat.")
    max_h = max(rect_heights)
    repeat = snap_repeat(max_h, press)
    if repeat is None:
        raise ValueError("Press repeat model returned None for a web press.")
    return uw, repeat, repeat


def _allocate(
    cells: list[_Cell],
    form_area: float,
    must_not_gang: dict[int, list[int]],
    objective: ObjectiveWeights | None,
    seed: int,
    budget_ms: int,
) -> list[int]:
    """CP-SAT quantity allocation. Returns n[i] for each cell index.

    Gap enforcement is handled downstream by the strip-packer; the area
    constraint here is conservative (cell bounding-box areas only).
    """
    obj = objective or ObjectiveWeights()
    model = cp_model.CpModel()

    # Quantise to avoid float in CP-SAT (centi-pt² units).
    scale = 100
    areas = [max(1, round((c.w * c.h) / scale)) for c in cells]
    capacity = max(1, round(form_area / scale))

    n = [model.new_int_var(0, max(1, capacity // a), f"n{i}") for i, a in enumerate(areas)]

    # Area constraint
    model.add(sum(n[i] * areas[i] for i in range(len(cells))) <= capacity)

    # Presence booleans for mustNotGangWith
    used = [model.new_bool_var(f"u{i}") for i in range(len(cells))]
    for i in range(len(cells)):
        model.add(n[i] >= 1).only_enforce_if(used[i])
        model.add(n[i] == 0).only_enforce_if(used[i].negated())

    for i, conflicts in must_not_gang.items():
        for j in conflicts:
            if j < len(cells):
                model.add(used[i] + used[j] <= 1)

    # Objective: maximise utilised area (weighted by waste weight)
    w = max(1, round(obj.waste * 1000))
    model.maximize(sum(n[i] * areas[i] * w for i in range(len(cells))))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = budget_ms / 1000.0
    solver.parameters.random_seed = seed % (2**31)

    status = solver.solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [int(solver.value(n[i])) for i in range(len(cells))]

    # Fallback: one copy each if it fits
    return [1 if areas[i] <= capacity else 0 for i in range(len(cells))]


def _strip_pack(
    cells: list[_Cell],
    counts: list[int],
    sheet_w: float,
    sheet_h: float,
    gap: float,
) -> list[ExplicitPlacement]:
    """Greedy height-descending row strip-packer."""
    items: list[_Cell] = []
    for i, c in enumerate(cells):
        items.extend([c] * counts[i])

    if not items:
        return []

    items.sort(key=lambda c: c.h, reverse=True)

    placements: list[ExplicitPlacement] = []
    x = 0.0
    y = 0.0
    row_h = 0.0

    for cell in items:
        if cell.w > sheet_w + 1e-6:
            continue
        if x + cell.w > sheet_w + 1e-6:
            y += row_h + gap
            x = 0.0
            row_h = 0.0
        if y + cell.h > sheet_h + 1e-6:
            break

        # cited: codex_pdf.geom.Box (position arithmetic for placement bounds)
        box = Box(x0=x, y0=y, x1=x + cell.w, y1=y + cell.h)
        placements.append(
            ExplicitPlacement(
                source_ref=cell.source_ref,
                x0_pt=box.x0,
                y0_pt=box.y0,
                x1_pt=box.x1,
                y1_pt=box.y1,
            )
        )
        row_h = max(row_h, cell.h)
        x += cell.w + gap

    return placements


def solve_gang(
    jobs: list[Job],
    press: PressProfile,
    availability: Availability | None,
    objective: ObjectiveWeights | None,
    *,
    seed: int,
    budget_ms: int,
    cache_key: str,
) -> SiftImposePlan:
    """Solve a T2 multi-SKU gang layout.

    Uses CP-SAT to allocate cell counts per SKU (minimising waste), then
    positions them via a greedy height-descending strip-packer.

    Rect and DielineRefDie jobs are supported; DielineRefDie is resolved via
    the availability snapshot (width_pt/height_pt or polygon bounding-box).
    Polygon dies are skipped (not representable in the strip-packer as-is).
    mustNotGangWith constraints are enforced as hard CP-SAT constraints.

    Availability hard constraints enforced:
    - required_die_id: die must be present in availability.dies with qty >= 1.
    - allowed_substrate_ids: at least one listed substrate must be in stock
      (qty_on_hand >= 1) when availability is provided and the list is non-empty.
    """
    if not jobs:
        raise ValueError("At least one job is required for a gang solve.")

    if availability is not None:
        for job in jobs:
            if job.required_die_id is not None:
                stock = next((d for d in availability.dies if d.id == job.required_die_id), None)
                if stock is None:
                    raise ValueError(
                        f"Required die '{job.required_die_id}' for job '{job.id}' "
                        "not found in availability snapshot."
                    )
                if stock.qty < 1:
                    raise ValueError(
                        f"Required die '{job.required_die_id}' for job '{job.id}' "
                        "is out of stock (qty=0)."
                    )
            if job.allowed_substrate_ids:
                in_stock = [
                    s
                    for s in availability.substrates
                    if s.id in job.allowed_substrate_ids and s.qty_on_hand >= 1
                ]
                if not in_stock:
                    raise ValueError(
                        f"No allowed substrate for job '{job.id}' is in stock "
                        f"(allowed: {job.allowed_substrate_ids})."
                    )

    sheet_w, sheet_h, repeat_pt = _form_dims(press, jobs)
    gap = max(press.gap_across_pt, press.gap_around_pt)

    cells: list[_Cell] = []
    for i, job in enumerate(jobs):
        c = _cell_from_job(job, i, availability)
        if c is not None:
            cells.append(c)

    if not cells:
        raise ValueError("solve_gang: no rect-die jobs found in job list.")

    # Build mustNotGangWith index map
    job_id_to_idx: dict[str, int] = {jobs[c.job_index].id: k for k, c in enumerate(cells)}
    must_not_gang: dict[int, list[int]] = {}
    for k, cell in enumerate(cells):
        conflicts = [
            job_id_to_idx[bad]
            for bad in jobs[cell.job_index].must_not_gang_with
            if bad in job_id_to_idx
        ]
        if conflicts:
            must_not_gang[k] = conflicts

    form_area = sheet_w * sheet_h

    counts = _allocate(
        cells=cells,
        form_area=form_area,
        must_not_gang=must_not_gang,
        objective=objective,
        seed=seed,
        budget_ms=budget_ms,
    )

    placements = _strip_pack(cells, counts, sheet_w, sheet_h, gap)
    if not placements:
        raise ValueError(
            "solve_gang: strip-packer produced no placements — "
            "check press dimensions and die sizes."
        )

    used_area = sum((p.x1_pt - p.x0_pt) * (p.y1_pt - p.y0_pt) for p in placements)
    waste_pct = max(0.0, min(100.0, (1.0 - used_area / form_area) * 100.0))

    sku_map: dict[str, list[int]] = {}
    for idx, ep in enumerate(placements):
        sku_map.setdefault(ep.source_ref, []).append(idx)

    dominant = max(cells, key=lambda c: c.w * c.h)

    sheet = achievable_sheet(press)
    if sheet:
        substrate = SubstrateChoice(sheet_width_pt=sheet[0], sheet_height_pt=sheet[1])
    else:
        substrate = SubstrateChoice(web_width_pt=press.web_width_pt, repeat_pt=repeat_pt)

    plate_count = sum(
        jobs[cells[k].job_index].separations for k in range(len(cells)) if counts[k] > 0
    )

    return SiftImposePlan(
        mode="gang",
        tier="T2",
        seed=seed,
        budget_ms=budget_ms,
        cache_key=cache_key,
        sift_version=SIFT_VERSION,
        codex_geom_schema_version=GEOM_SCHEMA_VERSION,
        substrate=substrate,
        sheet=SheetSpec(width_pt=sheet_w, height_pt=sheet_h),
        cell=CellSpec(width_pt=dominant.w, height_pt=dominant.h),
        explicit_placements=placements,
        waste_pct=waste_pct,
        material_area_pt2=form_area,
        plate_count=plate_count,
        sku_placement_map=sku_map,
    )


__all__ = ["solve_gang"]
