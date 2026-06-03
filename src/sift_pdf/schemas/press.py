"""Press profile schemas — discriminated union on repeatModel.type."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveFloat, model_validator


class _Strict(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}


# --- Repeat model variants ---------------------------------------------------


class GearSpec(_Strict):
    """One available gear: number of teeth × circular pitch → repeat circumference."""

    teeth: int = Field(..., gt=0, description="Number of gear teeth.")
    circular_pitch_pt: PositiveFloat = Field(
        ..., description="Circular pitch in points (π / diametral_pitch)."
    )


class GearedRepeatModel(_Strict):
    """Flexographic / gravure: available repeats are locked to the gear set.

    The solver snaps the target die height to the closest achievable repeat:
    N_teeth × circular_pitch_pt.
    """

    type: Literal["geared"]
    gear_set: list[GearSpec] = Field(..., min_length=1)


class ServoRepeatModel(_Strict):
    """Variable-repeat press (servo-driven): continuous range, no snap required."""

    type: Literal["servo"]
    min_repeat_pt: PositiveFloat
    max_repeat_pt: PositiveFloat

    @model_validator(mode="after")
    def _check_range(self) -> ServoRepeatModel:
        if self.min_repeat_pt > self.max_repeat_pt:
            raise ValueError(
                f"min_repeat_pt ({self.min_repeat_pt}) must be <= max_repeat_pt ({self.max_repeat_pt})"
            )
        return self


class DigitalWebRepeatModel(_Strict):
    """Digital web (inkjet / electrophotographic): max frame length per impression.

    Layout uses strip packing; the solver minimises web length consumed.
    """

    type: Literal["digital-web"]
    max_frame_pt: PositiveFloat = Field(..., description="Max impression length in points.")
    lane_limit: int = Field(default=1, ge=1, description="Max lanes across web width.")


class DigitalSheetRepeatModel(_Strict):
    """Digital cut-sheet: fixed sheet W×H; solver bins jobs onto sheets."""

    type: Literal["digital-sheet"]
    sheet_width_pt: PositiveFloat
    sheet_height_pt: PositiveFloat


class OffsetSheetRepeatModel(_Strict):
    """Offset / litho cut-sheet: fixed press sheet W×H."""

    type: Literal["offset-sheet"]
    sheet_width_pt: PositiveFloat
    sheet_height_pt: PositiveFloat


RepeatModel = Annotated[
    GearedRepeatModel
    | ServoRepeatModel
    | DigitalWebRepeatModel
    | DigitalSheetRepeatModel
    | OffsetSheetRepeatModel,
    Field(discriminator="type"),
]


# --- Press profile -----------------------------------------------------------


class PressProfile(BaseModel):
    """Complete press specification used by the solver."""

    model_config = {"extra": "forbid"}

    id: str = Field(..., description="Press identifier (for availability matching).")
    web_width_pt: PositiveFloat | None = Field(
        default=None,
        description="Usable web width in points (web presses only).",
    )
    repeat_model: RepeatModel = Field(
        ..., description="Discriminated union describing how repeats are constrained."
    )
    usable_margin_top_pt: NonNegativeFloat = Field(
        default=0.0, description="Top unusable margin in points."
    )
    usable_margin_bottom_pt: NonNegativeFloat = Field(
        default=0.0, description="Bottom unusable margin in points."
    )
    usable_margin_left_pt: NonNegativeFloat = Field(
        default=0.0, description="Left unusable margin in points."
    )
    usable_margin_right_pt: NonNegativeFloat = Field(
        default=0.0, description="Right unusable margin in points."
    )
    gap_around_pt: NonNegativeFloat = Field(
        default=0.0,
        description="Minimum gap in the around-cylinder (repeat) direction in points.",
    )
    gap_across_pt: NonNegativeFloat = Field(
        default=0.0, description="Minimum gap across-web in points."
    )
    max_colors: int = Field(default=4, ge=1, description="Maximum ink stations / colors per form.")
    material_cost_per_pt2: float = Field(
        default=0.0, ge=0.0, description="Material cost per square point (for estimate)."
    )
    makeready_cost: float = Field(default=0.0, ge=0.0, description="Fixed makeready cost per form.")
    plate_cost: float = Field(
        default=0.0, ge=0.0, description="Cost per plate/cylinder (per color per form)."
    )


__all__ = [
    "GearSpec",
    "GearedRepeatModel",
    "ServoRepeatModel",
    "DigitalWebRepeatModel",
    "DigitalSheetRepeatModel",
    "OffsetSheetRepeatModel",
    "RepeatModel",
    "PressProfile",
]
