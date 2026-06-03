"""POST /v1/sift/estimate — derive EstimateManifest from a SiftImposePlan."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from sift_pdf.schemas.estimate import EstimateManifest
from sift_pdf.schemas.impose_plan import SiftImposePlan

router = APIRouter()

_PT2_TO_M2 = (1 / 72 * 0.0254) ** 2  # 1 pt = 1/72 inch = 0.0254/72 m


class EstimateRequest(BaseModel):
    plan: SiftImposePlan


@router.post("/estimate", response_model=EstimateManifest, summary="Derive estimate manifest")
async def estimate_endpoint(payload: EstimateRequest) -> EstimateManifest:
    """Compute an EstimateManifest from an existing SiftImposePlan.

    Pure calculation — no new solve. Suitable for billing integration and
    nodes-mis ticket cost estimation.

    Responses:
      200: Manifest computed.
    """
    plan = payload.plan
    gl = plan.grid_layout

    if gl is not None:
        cells_total = gl.rows * gl.cols
    elif plan.explicit_placements is not None:
        cells_total = len(plan.explicit_placements)
    else:
        cells_total = 1

    material_area_m2 = plan.material_area_pt2 * _PT2_TO_M2

    return EstimateManifest(
        plan_cache_key=plan.cache_key,
        plate_count=plan.plate_count,
        sheet_width_pt=plan.sheet.width_pt,
        sheet_height_pt=plan.sheet.height_pt,
        cell_width_pt=plan.cell.width_pt,
        cell_height_pt=plan.cell.height_pt,
        cells_total=cells_total,
        waste_pct=plan.waste_pct,
        est_material_area_m2=round(material_area_m2, 6),
        est_cost=plan.est_cost,
        est_run_time_sec=plan.est_run_time_sec,
    )
