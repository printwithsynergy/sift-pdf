"""SiftImposePlan — the solver's output document.

This is sift-pdf's OWN output schema, distinct from compile-pdf's ImposePlan.
It targets codex/compile vocabulary (CellPlacement, bleed_handling, etc.) but
adds solver metadata, substrate choice, metrics, and stagger support.

Handoff to compile-pdf happens via sift_pdf.handoff.compile, which translates
this document into compile-pdf's ImposePlan shape (grid fast-path) or the
explicit-placements mode (stagger / gang / nest — requires compile-pdf ≥1.1.0
with the additive explicit_placements field).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveFloat, model_validator


class _Strict(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}


# --- Sub-shapes --------------------------------------------------------------


class SubstrateChoice(_Strict):
    """Solver-chosen substrate dimensions."""

    web_width_pt: PositiveFloat | None = Field(
        default=None, description="Web press: usable web width in points."
    )
    repeat_pt: PositiveFloat | None = Field(
        default=None,
        description="Web press: snapped around-cylinder repeat in points.",
    )
    sheet_width_pt: PositiveFloat | None = Field(
        default=None, description="Sheet press: sheet width in points."
    )
    sheet_height_pt: PositiveFloat | None = Field(
        default=None, description="Sheet press: sheet height in points."
    )


class SheetSpec(_Strict):
    """Resolved output sheet dimensions in points."""

    width_pt: PositiveFloat
    height_pt: PositiveFloat


class CellSpec(_Strict):
    """Per-cell trim dimensions in points (matches the input job TrimBox)."""

    width_pt: PositiveFloat
    height_pt: PositiveFloat


class MarksZoneSpec(_Strict):
    """Reserved sheet margins for marks (slug, color bars, etc.)."""

    top_pt: NonNegativeFloat = 0.0
    right_pt: NonNegativeFloat = 0.0
    bottom_pt: NonNegativeFloat = 0.0
    left_pt: NonNegativeFloat = 0.0


BleedHandling = Literal["none", "trim", "extend"]
StaggerMode = Literal["none", "half-drop-x", "half-drop-y", "custom"]


class GridLayout(_Strict):
    """Uniform or staggered grid — T1 tier output.

    For uniform grids (stagger_mode="none"), maps directly to compile-pdf's
    ImposePlan grid params via handoff.compile.

    For stagger_mode != "none", the explicit_placements field on SiftImposePlan
    carries the pre-computed positions. Handoff requires compile-pdf ≥1.1.0
    with the explicit_placements field (cross-repo PR).

    Future: compile-pdf may grow a native stagger_mode field so the semantic
    intent is preserved through the writer layer — see CLAUDE.md.
    """

    rows: int = Field(..., gt=0)
    cols: int = Field(..., gt=0)
    gutter_x_pt: NonNegativeFloat = 0.0
    gutter_y_pt: NonNegativeFloat = 0.0
    cell_rotation: Literal[0, 90, 180, 270] = 0
    flip_per_row: bool = False
    bleed_handling: BleedHandling = "none"
    stagger_mode: StaggerMode = Field(
        default="none",
        description=(
            "Stagger (half-drop / brick) pattern. 'none' = uniform grid. "
            "'half-drop-x' = odd rows offset right by cell_width/2. "
            "'half-drop-y' = odd columns offset up by cell_height/2. "
            "'custom' = use stagger_offset_pt."
        ),
    )
    stagger_offset_pt: float = Field(
        default=0.0,
        ge=0.0,
        description="Custom stagger offset in points (used only when stagger_mode='custom').",
    )


class ExplicitPlacement(BaseModel):
    """Pre-computed sheet-space cell position from the solver.

    Used for: stagger cuts, gang (T2), nest (T3).
    Targets codex CellPlacement vocabulary: box (x0/y0/x1/y1) + rotation + flip.
    source_ref links back to Job.id for lineage.
    """

    model_config = {"extra": "forbid"}

    source_ref: str = Field(..., description="Job.id + optional ':pageIdx' suffix.")
    x0_pt: float = Field(..., description="Lower-left x in points.")
    y0_pt: float = Field(..., description="Lower-left y in points.")
    x1_pt: float = Field(..., description="Upper-right x in points.")
    y1_pt: float = Field(..., description="Upper-right y in points.")
    rotation: float = Field(default=0.0, description="Rotation in degrees.")
    flip_h: bool = False
    flip_v: bool = False
    row: int | None = Field(default=None, description="Grid row (informational).")
    col: int | None = Field(default=None, description="Grid column (informational).")


class MarksIntent(BaseModel):
    """Intent for the compile.marks producer — forwarded as-is."""

    model_config = {"extra": "forbid"}

    registration_marks: bool = False
    crop_marks: bool = False
    bearer_bars: bool = False
    eye_marks: bool = False


# --- Top-level plan ----------------------------------------------------------


SolveMode = Literal["grid", "gang", "nest", "suggest"]
SolveTier = Literal["T1", "T2", "T3"]


class SiftImposePlan(BaseModel):
    """SiftPDF solver output — complete plan document.

    Distinct from compile-pdf's ImposePlan (the writer's input).
    Handoff via sift_pdf.handoff.compile translates to compile-pdf's shape.
    """

    model_config = {"extra": "forbid"}

    schema_version: Literal["1.0.0"] = "1.0.0"
    mode: SolveMode
    tier: SolveTier
    seed: int = Field(..., description="RNG seed used (determinism pin).")
    budget_ms: int = Field(..., description="Solver budget in milliseconds.")
    cache_key: str = Field(..., description="Content-addressed cache key for this plan.")
    sift_version: str
    codex_geom_schema_version: str

    substrate: SubstrateChoice
    sheet: SheetSpec
    cell: CellSpec
    marks_zone: MarksZoneSpec = Field(default_factory=MarksZoneSpec)

    # Layout — exactly one of grid_layout or explicit_placements is set.
    # grid_layout: T1 uniform grid (stagger_mode="none").
    # explicit_placements: T1-stagger, T2-gang, T3-nest, or T1-stagger fallback.
    grid_layout: GridLayout | None = None
    explicit_placements: list[ExplicitPlacement] | None = None

    bleed_pt: NonNegativeFloat = 0.0
    bleed_handling: BleedHandling = "none"

    # Metrics
    waste_pct: float = Field(..., ge=0.0, le=100.0, description="Substrate waste as %.")
    material_area_pt2: float = Field(..., ge=0.0, description="Total sheet area in pt².")
    est_cost: float | None = Field(default=None, description="Estimated cost (currency-agnostic).")
    est_run_time_sec: float | None = Field(
        default=None, description="Estimated press time in seconds."
    )
    plate_count: int = Field(..., ge=0, description="Total plate/cylinder impressions required.")

    # Gang / nest extras
    sku_placement_map: dict[str, list[int]] | None = Field(
        default=None,
        description="Mapping from Job.id to explicit_placements indices (gang/nest).",
    )
    lane_assignments: list[int] | None = Field(
        default=None, description="Per-placement lane index (digital web)."
    )

    marks_intent: MarksIntent | None = None

    @model_validator(mode="after")
    def _check_layout(self) -> SiftImposePlan:
        if self.grid_layout is None and self.explicit_placements is None:
            raise ValueError("Exactly one of grid_layout or explicit_placements must be set.")
        return self


__all__ = [
    "SubstrateChoice",
    "SheetSpec",
    "CellSpec",
    "MarksZoneSpec",
    "BleedHandling",
    "StaggerMode",
    "GridLayout",
    "ExplicitPlacement",
    "MarksIntent",
    "SolveMode",
    "SolveTier",
    "SiftImposePlan",
]
