"""POST /v1/sift/suggest — sweep substrate catalog and return best layout."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sift_pdf.schemas.impose_plan import SiftImposePlan
from sift_pdf.schemas.jobs import Availability, Job, ObjectiveWeights
from sift_pdf.schemas.press import PressProfile
from sift_pdf.solve.engine import _DEFAULT_BUDGET_MS, _DEFAULT_SEED, solve

router = APIRouter()


class SubstrateCatalogEntry(BaseModel):
    """One substrate candidate for the suggestion sweep."""

    id: str
    web_width_pt: float | None = None
    sheet_width_pt: float | None = None
    sheet_height_pt: float | None = None
    description: str | None = None


class SuggestRequest(BaseModel):
    """Request body for POST /v1/sift/suggest."""

    jobs: list[Job] = Field(..., min_length=1)
    substrate_catalog: list[SubstrateCatalogEntry] = Field(
        ...,
        min_length=1,
        description="List of substrate candidates to sweep.",
    )
    press_profile: PressProfile
    objective: ObjectiveWeights | None = None
    availability: Availability | None = None
    seed: int = _DEFAULT_SEED
    budget_ms: int = Field(default=_DEFAULT_BUDGET_MS, ge=100)


class SuggestResponse(BaseModel):
    """Best plan found across the catalog sweep."""

    plan: SiftImposePlan
    substrate_id: str
    candidates_evaluated: int


@router.post("/suggest", response_model=SuggestResponse, summary="Suggest best substrate")
async def suggest_endpoint(payload: SuggestRequest) -> SuggestResponse:
    """Sweep a substrate catalog and return the layout with lowest waste %.

    Runs a T1 grid solve on each catalog entry; returns the best result.
    Long sweeps may exceed the per-candidate budget_ms if many candidates are provided.

    Responses:
      200: Best layout found.
      400: No feasible layout found for any candidate.
    """
    best: SiftImposePlan | None = None
    best_substrate_id = ""
    evaluated = 0

    for entry in payload.substrate_catalog:
        # Build a modified press profile with this substrate's dimensions
        press_data = payload.press_profile.model_dump()
        if entry.web_width_pt is not None:
            press_data["web_width_pt"] = entry.web_width_pt
        if entry.sheet_width_pt is not None and entry.sheet_height_pt is not None:
            # Inject sheet dims into repeat_model if it's a sheet type
            rm = press_data.get("repeat_model", {})
            if rm.get("type") in ("digital-sheet", "offset-sheet"):
                rm["sheet_width_pt"] = entry.sheet_width_pt
                rm["sheet_height_pt"] = entry.sheet_height_pt
                press_data["repeat_model"] = rm

        try:
            press = PressProfile.model_validate(press_data)
            plan, _ = solve(
                jobs=payload.jobs,
                press=press,
                mode="grid",
                availability=payload.availability,
                objective=payload.objective,
                seed=payload.seed,
                budget_ms=payload.budget_ms,
            )
            evaluated += 1
            if best is None or plan.waste_pct < best.waste_pct:
                best = plan
                best_substrate_id = entry.id
        except (ValueError, RuntimeError):
            continue

    if best is None:
        raise HTTPException(
            status_code=400,
            detail="No feasible layout found for any substrate in the catalog.",
        )

    return SuggestResponse(
        plan=best,
        substrate_id=best_substrate_id,
        candidates_evaluated=evaluated,
    )
