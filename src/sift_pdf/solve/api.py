"""POST /v1/sift/solve — solve a layout for given jobs + press."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from sift_pdf.schemas.grouping import AttributeValue, GroupingCriterion, GroupingError
from sift_pdf.schemas.impose_plan import (
    BleedHandling,
    SiftImposePlan,
    SolveMode,
    StaggerMode,
)
from sift_pdf.schemas.jobs import Availability, Job, ObjectiveWeights
from sift_pdf.schemas.press import PressProfile
from sift_pdf.solve.engine import _DEFAULT_BUDGET_MS, _DEFAULT_SEED, solve, solve_grouped

router = APIRouter()


class SolveRequest(BaseModel):
    """Request body for POST /v1/sift/solve."""

    jobs: list[Job] = Field(..., min_length=1, description="SKUs to lay out.")
    press_profile: PressProfile = Field(..., description="Press / substrate specification.")
    availability: Availability | None = Field(
        default=None, description="Optional on-hand inventory snapshot."
    )
    objective: ObjectiveWeights | None = Field(
        default=None, description="Objective weight overrides."
    )
    mode: SolveMode = Field(
        default="grid",
        description="Solver tier: grid | gang | nest | suggest.",
    )
    stagger_mode: StaggerMode = Field(
        default="none",
        description=(
            "Stagger (half-drop / brick) pattern for grid mode. "
            "'none' = uniform grid. 'half-drop-x' = odd rows offset right by half cell-pitch. "
            "'half-drop-y' = odd columns offset up by half cell-pitch. "
            "'custom' = use stagger_offset_pt."
        ),
    )
    stagger_offset_pt: float = Field(
        default=0.0,
        ge=0.0,
        description="Custom stagger offset in points (used only when stagger_mode='custom').",
    )
    bleed_handling: BleedHandling = Field(
        default="none",
        description="How bleed extends beyond the cell trim box.",
    )
    seed: int = Field(
        default=_DEFAULT_SEED,
        description="RNG seed for deterministic results (T3 nest).",
    )
    budget_ms: int = Field(
        default=_DEFAULT_BUDGET_MS,
        ge=100,
        description="Solver time budget in milliseconds.",
    )
    grouping_criteria: list[GroupingCriterion] | None = Field(
        default=None,
        description=(
            "Custom grouping rules over Job.attributes. 'hard' criteria "
            "partition jobs into independent press forms (one solved plan per "
            "distinct value combination); 'soft' criteria bias the gang solver "
            "to keep same-value jobs together. When present, the response "
            "returns 'groups' instead of a single 'plan'. Supports any typed "
            "attribute value (dates, booleans, numbers, strings)."
        ),
    )


class GroupResult(BaseModel):
    """One bucket of a grouped solve: its partition key + the plan for it."""

    group_key: dict[str, AttributeValue] = Field(
        ...,
        description="The attribute values that define this group (hard criteria).",
    )
    plan: SiftImposePlan = Field(..., description="The solved layout for this group.")
    cache_hit: bool = Field(default=False, description="True if served from cache.")


class SolveResponse(BaseModel):
    """Solve response envelope.

    Exactly one of ``plan`` (ungrouped solve) or ``groups`` (one plan per
    grouped bucket) is populated. Ungrouped requests keep the original shape
    (``plan`` set, ``groups`` null) for full backward compatibility.
    """

    plan: SiftImposePlan | None = Field(
        default=None, description="The solved layout (ungrouped requests)."
    )
    groups: list[GroupResult] | None = Field(
        default=None,
        description="Per-group solved layouts (set when grouping_criteria is given).",
    )
    cache_hit: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> SolveResponse:
        if (self.plan is None) == (self.groups is None):
            raise ValueError("Exactly one of 'plan' or 'groups' must be set.")
        return self


@router.post("/solve", response_model=SolveResponse, summary="Solve an imposition layout")
async def solve_endpoint(
    payload: SolveRequest,
    request: Request,
    x_sift_seed: int | None = Header(default=None, alias="X-Sift-Seed"),
    x_sift_budget_ms: int | None = Header(default=None, alias="X-Sift-Budget-Ms"),
) -> SolveResponse:
    """Stateless, deterministic layout solve.

    Given jobs + press profile (+ optional availability snapshot), returns the
    most efficient ImposePlan for the requested mode. Identical requests return
    the same plan (content-addressed cache).

    **Stagger cuts** are supported in grid mode via `stagger_mode`:
    - `half-drop-x`: odd rows shifted right by half the cell+gutter pitch
    - `half-drop-y`: odd columns shifted up by half the cell+gutter pitch
    - `custom`: specify exact `stagger_offset_pt`

    Stagger layouts emit `explicit_placements` rather than `grid_layout` and
    require compile-pdf ≥1.1.0 (explicit-placements mode) for PDF generation.

    **Custom grouping** via `grouping_criteria`: group jobs by any typed
    `Job.attributes` value (dates, booleans, numbers, strings). `hard`
    criteria partition jobs into independent press forms (the response returns
    `groups`, one solved plan per distinct value combination); `soft` criteria
    bias the gang solver to keep same-value jobs on the same form. Without
    `grouping_criteria` the response is unchanged (`plan` populated).

    The `X-Sift-Cache-Key` header carries the plan's cache key (ungrouped) or a
    composite digest of the per-group cache keys (grouped).

    Responses:
      200: Plan solved (or cache hit).
      400: Invalid request geometry or press constraints.
      422: Invalid grouping criteria (e.g. missing required attribute).
      501: Requested solver tier not available (missing optional dep).
    """
    # Header values override body values (deterministic pinning channel)
    seed = x_sift_seed if x_sift_seed is not None else payload.seed
    budget_ms = x_sift_budget_ms if x_sift_budget_ms is not None else payload.budget_ms

    if budget_ms < 100:
        raise HTTPException(
            status_code=422,
            detail=f"X-Sift-Budget-Ms must be >= 100; got {budget_ms}.",
        )

    if payload.mode == "suggest":
        raise HTTPException(
            status_code=422,
            detail="Use POST /v1/sift/suggest for mode=suggest.",
        )

    if payload.grouping_criteria:
        content, cache_key = _solve_grouped(payload, seed, budget_ms)
    else:
        content, cache_key = _solve_single(payload, seed, budget_ms)

    from fastapi.responses import JSONResponse

    return JSONResponse(  # type: ignore[return-value]
        content=content.model_dump(mode="json"),
        status_code=200,
        headers={"X-Sift-Cache-Key": cache_key},
    )


def _solve_single(payload: SolveRequest, seed: int, budget_ms: int) -> tuple[SolveResponse, str]:
    """Ungrouped solve — returns (response, cache_key)."""
    try:
        plan, hit = solve(
            jobs=payload.jobs,
            press=payload.press_profile,
            mode=payload.mode,
            availability=payload.availability,
            objective=payload.objective,
            seed=seed,
            budget_ms=budget_ms,
            stagger_mode=payload.stagger_mode,
            stagger_offset_pt=payload.stagger_offset_pt,
            bleed_handling=payload.bleed_handling,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    return SolveResponse(plan=plan, cache_hit=hit), plan.cache_key


def _solve_grouped(payload: SolveRequest, seed: int, budget_ms: int) -> tuple[SolveResponse, str]:
    """Grouped solve — one plan per hard-partition bucket. Returns (response, key)."""
    assert payload.grouping_criteria is not None
    try:
        results = solve_grouped(
            jobs=payload.jobs,
            press=payload.press_profile,
            mode=payload.mode,
            grouping_criteria=payload.grouping_criteria,
            availability=payload.availability,
            objective=payload.objective,
            seed=seed,
            budget_ms=budget_ms,
            stagger_mode=payload.stagger_mode,
            stagger_offset_pt=payload.stagger_offset_pt,
            bleed_handling=payload.bleed_handling,
        )
    except GroupingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    if not results:
        raise HTTPException(
            status_code=400,
            detail="grouping_criteria produced no groups (all jobs skipped).",
        )

    groups = [
        GroupResult(group_key=r.group_key, plan=r.plan, cache_hit=r.cache_hit) for r in results
    ]
    # Composite cache key: deterministic digest of the per-bucket keys.
    composite = hashlib.sha256("|".join(g.plan.cache_key for g in groups).encode()).hexdigest()
    response = SolveResponse(groups=groups, cache_hit=all(g.cache_hit for g in groups))
    return response, composite
