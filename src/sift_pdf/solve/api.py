"""POST /v1/sift/solve — solve a layout for given jobs + press."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from sift_pdf.schemas.impose_plan import (
    BleedHandling,
    SiftImposePlan,
    SolveMode,
    StaggerMode,
)
from sift_pdf.schemas.jobs import Availability, Job, ObjectiveWeights
from sift_pdf.schemas.press import PressProfile
from sift_pdf.solve.engine import _DEFAULT_BUDGET_MS, _DEFAULT_SEED, solve

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


class SolveResponse(BaseModel):
    """Solve response envelope."""

    plan: SiftImposePlan
    cache_hit: bool = False


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

    Responses:
      200: Plan solved (or cache hit).
      400: Invalid request geometry or press constraints.
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

    from fastapi.responses import JSONResponse

    content = SolveResponse(plan=plan, cache_hit=hit)
    headers = {"X-Sift-Cache-Key": plan.cache_key}
    return JSONResponse(  # type: ignore[return-value]
        content=content.model_dump(mode="json"),
        status_code=200,
        headers=headers,
    )
