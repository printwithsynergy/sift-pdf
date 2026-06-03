"""Translate SiftImposePlan → compile-pdf ImposePlan dict.

Two paths:

Grid fast-path (stagger_mode="none"):
  Emit compile-pdf's ImposePlan dict directly.  Compile's impose engine
  calls codex.tile_grid internally; no pre-computed placements needed.

Explicit-placements path (stagger, gang, nest):
  Emit an extended compile-pdf ImposePlan with ``explicit_placements`` list.
  Requires compile-pdf ≥1.1.0 with the additive explicit_placements field
  (cross-repo PR — see CLAUDE.md § Cross-repo PRs).

The returned dict is suitable for:
  compile-pdf CLI:  compile-pdf impose apply --plan <json>
  HTTP API:         POST /v1/impose/apply  { "input_pdf_b64": "...", "plan": <dict> }
"""

from __future__ import annotations

from typing import Any

from sift_pdf.schemas.impose_plan import SiftImposePlan


def to_compile_impose_plan(plan: SiftImposePlan) -> dict[str, Any]:
    """Return a compile-pdf-compatible ImposePlan dict from a SiftImposePlan.

    For grid (no stagger): uses compile-pdf's native grid params.
    For stagger / gang / nest: uses explicit_placements (requires compile-pdf ≥1.1.0).
    """
    gl = plan.grid_layout

    if gl is not None and gl.stagger_mode == "none" and plan.explicit_placements is None:
        return _grid_plan(plan, gl)
    return _explicit_plan(plan)


def _grid_plan(plan: SiftImposePlan, gl: Any) -> dict[str, Any]:
    """Compile-pdf native grid ImposePlan — no explicit placements needed."""
    return {
        "schema_version": "1.0.0",
        "sheet": {
            "width_pt": plan.sheet.width_pt,
            "height_pt": plan.sheet.height_pt,
        },
        "cell": {
            "width_pt": plan.cell.width_pt,
            "height_pt": plan.cell.height_pt,
        },
        "gutter": {
            "x_pt": gl.gutter_x_pt,
            "y_pt": gl.gutter_y_pt,
        },
        "marks_zone": {
            "top_pt": plan.marks_zone.top_pt,
            "right_pt": plan.marks_zone.right_pt,
            "bottom_pt": plan.marks_zone.bottom_pt,
            "left_pt": plan.marks_zone.left_pt,
        },
        "cell_rotation": gl.cell_rotation,
        "flip_per_row": gl.flip_per_row,
        "bleed_pt": plan.bleed_pt,
        "bleed_handling": plan.bleed_handling,
        "page_mapping": "sequential",
        "back_side": "none",
    }


def _explicit_plan(plan: SiftImposePlan) -> dict[str, Any]:
    """Extended compile-pdf ImposePlan with explicit_placements.

    Requires compile-pdf ≥1.1.0. Until that cross-repo PR lands, this dict
    will be rejected by compile-pdf's schema validator.
    """
    placements: list[dict[str, Any]] = []
    if plan.explicit_placements:
        for ep in plan.explicit_placements:
            placements.append(
                {
                    "source_ref": ep.source_ref,
                    "x0_pt": ep.x0_pt,
                    "y0_pt": ep.y0_pt,
                    "x1_pt": ep.x1_pt,
                    "y1_pt": ep.y1_pt,
                    "rotation": ep.rotation,
                    "flip_h": ep.flip_h,
                    "flip_v": ep.flip_v,
                }
            )

    base: dict[str, Any] = (
        _grid_plan(plan, plan.grid_layout)
        if plan.grid_layout
        else {
            "schema_version": "1.0.0",
            "sheet": {"width_pt": plan.sheet.width_pt, "height_pt": plan.sheet.height_pt},
            "cell": {"width_pt": plan.cell.width_pt, "height_pt": plan.cell.height_pt},
            "gutter": {"x_pt": 0.0, "y_pt": 0.0},
            "marks_zone": {
                "top_pt": plan.marks_zone.top_pt,
                "right_pt": plan.marks_zone.right_pt,
                "bottom_pt": plan.marks_zone.bottom_pt,
                "left_pt": plan.marks_zone.left_pt,
            },
            "cell_rotation": 0,
            "flip_per_row": False,
            "bleed_pt": plan.bleed_pt,
            "bleed_handling": plan.bleed_handling,
            "page_mapping": "sequential",
            "back_side": "none",
        }
    )
    base["explicit_placements"] = placements
    return base


__all__ = ["to_compile_impose_plan"]
