"""Job / SKU input schemas and availability snapshot."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveFloat


class _Strict(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}


# --- Die shape variants (discriminated union) --------------------------------


class RectDie(_Strict):
    """Simple rectangular die — the common case."""

    type: Literal["rect"]
    width_pt: PositiveFloat = Field(..., description="Trim width in points.")
    height_pt: PositiveFloat = Field(..., description="Trim height in points.")


class PolygonDie(_Strict):
    """Irregular die described as a closed polygon ring in points.

    Points are in PDF user-space (1/72 inch), origin at lower-left.
    """

    type: Literal["polygon"]
    points: list[tuple[float, float]] = Field(
        ...,
        min_length=3,
        description="Closed polygon ring [[x,y], ...] in PDF points.",
    )


class DielineRefDie(_Strict):
    """Reference to a die already registered in the system / press."""

    type: Literal["dieline-ref"]
    die_id: str = Field(..., description="Die identifier in the inventory.")


DieShape = Annotated[
    RectDie | PolygonDie | DielineRefDie,
    Field(discriminator="type"),
]


# --- Job / SKU ---------------------------------------------------------------


class Job(BaseModel):
    """Single SKU to be planned."""

    model_config = {"extra": "forbid"}

    id: str = Field(..., description="Unique SKU / job identifier.")
    die: DieShape = Field(..., description="Die shape — rect, polygon, or dieline ref.")
    bleed_pt: NonNegativeFloat = Field(default=0.0, description="Bleed extension in points.")
    allowed_rotations: list[Literal[0, 90, 180, 270]] = Field(
        default=[0],
        description="Allowed die rotations in degrees. [0] = no rotation.",
    )
    min_gap_pt: NonNegativeFloat = Field(
        default=0.0, description="Minimum gap to neighbouring cells in points."
    )
    separations: int = Field(
        default=4, ge=1, description="Number of ink separations (for plate cost)."
    )
    quantity: int = Field(..., gt=0, description="Required quantity (units).")
    priority: int = Field(default=0, description="Higher = more important for scheduling.")
    due_date: str | None = Field(
        default=None, description="ISO 8601 due date (used by sift.pool, not by solve)."
    )
    grain_lock: Literal["with-web", "cross-web"] | None = Field(
        default=None, description="Force grain / web-direction orientation."
    )
    must_not_gang_with: list[str] = Field(
        default_factory=list,
        description="Job IDs that must not appear on the same form.",
    )
    allowed_substrate_ids: list[str] = Field(
        default_factory=list,
        description="Restrict to these substrate IDs. Empty = any.",
    )
    required_die_id: str | None = Field(
        default=None, description="Must use this specific die ID (from inventory)."
    )


# --- Availability snapshot (optional, stateless input) ----------------------


class SubstrateStock(_Strict):
    id: str
    width_pt: PositiveFloat
    height_pt: PositiveFloat | None = None  # None = web roll
    qty_on_hand: int = Field(..., ge=0)


class DieStock(_Strict):
    id: str
    mounted_on_press_id: str | None = None
    qty: int = Field(..., ge=0, description="Quantity on hand; 0 = tracked but out of stock.")
    # Optional shape info — required to resolve DielineRefDie in T2/T3 solvers.
    width_pt: PositiveFloat | None = Field(
        default=None, description="Rect die width in pts (for DielineRefDie resolution)."
    )
    height_pt: PositiveFloat | None = Field(
        default=None, description="Rect die height in pts (for DielineRefDie resolution)."
    )
    polygon_points: list[tuple[float, float]] | None = Field(
        default=None,
        description="Polygon die ring [[x,y],...] (for DielineRefDie resolution).",
    )


class PlateStock(_Strict):
    id: str
    teeth: int | None = None
    repeat_pt: PositiveFloat | None = None


class PressSlot(_Strict):
    id: str
    available_from: str | None = None  # ISO 8601
    available_to: str | None = None


class Availability(BaseModel):
    """Optional snapshot of what's on-hand — enables feasibility constraints.

    When absent the solver optimises layout only (no stock/inventory enforcement).
    When present, substrate/die/plate availability become hard constraints and
    prefer-in-stock / prefer-mounted become soft objective terms.
    """

    model_config = {"extra": "forbid"}

    substrates: list[SubstrateStock] = Field(default_factory=list)
    dies: list[DieStock] = Field(default_factory=list)
    plates: list[PlateStock] = Field(default_factory=list)
    presses: list[PressSlot] = Field(default_factory=list)


# --- Objective weights -------------------------------------------------------


class ObjectiveWeights(BaseModel):
    """Relative weights for the multi-objective solver.

    All values are non-negative; zero disables that term.
    """

    model_config = {"extra": "forbid"}

    waste: float = Field(default=1.0, ge=0.0, description="Weight for substrate waste %.")
    material_cost: float = Field(default=0.5, ge=0.0, description="Weight for material cost.")
    run_time: float = Field(default=0.2, ge=0.0, description="Weight for press run time.")
    plate_count: float = Field(
        default=0.5, ge=0.0, description="Weight for number of plates/cylinders."
    )
    overrun_tolerance: float = Field(
        default=0.1,
        ge=0.0,
        description="Acceptable overrun fraction (0.1 = 10% over quantity is OK).",
    )
    changeover_penalty: float = Field(
        default=0.3,
        ge=0.0,
        description="Penalty per substrate/die changeover event.",
    )


__all__ = [
    "RectDie",
    "PolygonDie",
    "DielineRefDie",
    "DieShape",
    "Job",
    "SubstrateStock",
    "DieStock",
    "PlateStock",
    "PressSlot",
    "Availability",
    "ObjectiveWeights",
]
