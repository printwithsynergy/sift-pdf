"""EstimateManifest — cheap metrics output for nodes-mis / billing consumers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, NonNegativeFloat


class EstimateManifest(BaseModel):
    """Output of POST /v1/sift/estimate — derived from a SiftImposePlan.

    Pure calculation from plan metrics; no new solve. Consumed by
    nodes-mis (ticket cost estimate) and artworkPDF billing integration.
    """

    model_config = {"extra": "forbid"}

    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_cache_key: str = Field(..., description="Cache key of the source SiftImposePlan.")

    plate_count: int = Field(..., ge=0, description="Plate/cylinder impressions required.")
    substrate_id: str | None = Field(
        default=None, description="Matched substrate ID from availability (if provided)."
    )
    sheet_width_pt: float
    sheet_height_pt: float
    cell_width_pt: float
    cell_height_pt: float
    cells_total: int = Field(..., ge=1, description="Total cells on the sheet.")
    waste_pct: NonNegativeFloat

    est_material_area_m2: float = Field(
        ..., ge=0.0, description="Estimated material area in m² (converted from pt²)."
    )
    est_cost: float | None = None
    est_run_time_sec: float | None = None

    special_processes: list[str] = Field(
        default_factory=list,
        description="E.g. ['lamination', 'hot-foil'] — pass-through from job specs.",
    )


__all__ = ["EstimateManifest"]
