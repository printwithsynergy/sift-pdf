"""Solve engine — dispatches to T1/T2/T3 based on mode, handles cache."""

from __future__ import annotations

from typing import NamedTuple

import structlog

from sift_pdf.cache import _sha256_canonical, cache_get, cache_put, compute_cache_key
from sift_pdf.schemas.grouping import (
    GroupingCriterion,
    group_key_to_dict,
    partition_jobs,
    split_criteria,
)
from sift_pdf.schemas.impose_plan import BleedHandling, SiftImposePlan, StaggerMode
from sift_pdf.schemas.jobs import AttributeValue, Availability, Job, ObjectiveWeights
from sift_pdf.schemas.press import PressProfile

logger = structlog.get_logger(__name__)

_DEFAULT_SEED = 42
_DEFAULT_BUDGET_MS = 5000


def _codex_versions() -> tuple[str, str]:
    """Return (codex_pdf_version, geom_schema_version)."""
    try:
        from codex_pdf import __version__ as cv
        from codex_pdf.geom import GEOM_SCHEMA_VERSION

        return str(cv), GEOM_SCHEMA_VERSION
    except ImportError:
        return "unknown", "unknown"


def solve(
    *,
    jobs: list[Job],
    press: PressProfile,
    mode: str,
    availability: Availability | None = None,
    objective: ObjectiveWeights | None = None,
    seed: int = _DEFAULT_SEED,
    budget_ms: int = _DEFAULT_BUDGET_MS,
    stagger_mode: StaggerMode = "none",
    stagger_offset_pt: float = 0.0,
    bleed_handling: BleedHandling = "none",
    soft_affinity: list[tuple[str, float]] | None = None,
) -> tuple[SiftImposePlan, bool]:
    """Dispatch to the correct solver tier and manage the cache.

    Returns (plan, cache_hit).

    ``soft_affinity`` carries soft grouping criteria as ``(key, weight)`` pairs;
    they bias the gang solver (no-op in grid/nest for v1) and are folded into
    the cache key so a soft-affinity change misses cleanly. When empty, the
    cache key is byte-identical to an ungrouped solve.
    """
    codex_pdf_version, geom_schema_version = _codex_versions()

    from sift_pdf.version import NEST_ENGINE_FINGERPRINT

    grouping_sha256 = _sha256_canonical([[k, w] for k, w in soft_affinity]) if soft_affinity else ""

    cache_key = compute_cache_key(
        mode=mode,
        seed=seed,
        budget_ms=budget_ms,
        jobs=[j.model_dump() for j in jobs],
        press=press.model_dump(),
        availability=availability.model_dump() if availability else None,
        objective=objective.model_dump() if objective else None,
        codex_pdf_version=codex_pdf_version,
        geom_schema_version=geom_schema_version,
        nest_engine_fingerprint=NEST_ENGINE_FINGERPRINT if mode == "nest" else "",
        grouping_sha256=grouping_sha256,
    )

    cached = cache_get(cache_key)
    if cached is not None:
        logger.info("solve.cache_hit", mode=mode, cache_key=cache_key[:16])
        return SiftImposePlan.model_validate(cached), True

    plan = _dispatch(
        jobs=jobs,
        press=press,
        mode=mode,
        availability=availability,
        objective=objective,
        seed=seed,
        budget_ms=budget_ms,
        cache_key=cache_key,
        stagger_mode=stagger_mode,
        stagger_offset_pt=stagger_offset_pt,
        bleed_handling=bleed_handling,
        soft_affinity=soft_affinity,
    )

    cache_put(cache_key, plan.model_dump())
    logger.info("solve.complete", mode=mode, tier=plan.tier, waste_pct=plan.waste_pct)
    return plan, False


def _dispatch(
    *,
    jobs: list[Job],
    press: PressProfile,
    mode: str,
    availability: Availability | None,
    objective: ObjectiveWeights | None,
    seed: int,
    budget_ms: int,
    cache_key: str,
    stagger_mode: StaggerMode,
    stagger_offset_pt: float,
    bleed_handling: BleedHandling,
    soft_affinity: list[tuple[str, float]] | None = None,
) -> SiftImposePlan:
    if mode == "grid":
        from sift_pdf.solve.t1_grid import solve_grid

        return solve_grid(
            jobs,
            press,
            availability,
            objective,
            seed=seed,
            budget_ms=budget_ms,
            cache_key=cache_key,
            stagger_mode=stagger_mode,
            stagger_offset_pt=stagger_offset_pt,
            bleed_handling=bleed_handling,
        )
    if mode == "gang":
        try:
            from sift_pdf.solve.t2_gang import solve_gang
        except ImportError as exc:
            raise RuntimeError(
                "T2 gang solver requires the [gang] extra (ortools). "
                "Install with: pip install sift-pdf[gang]"
            ) from exc
        return solve_gang(
            jobs,
            press,
            availability,
            objective,
            seed=seed,
            budget_ms=budget_ms,
            cache_key=cache_key,
            soft_affinity=soft_affinity,
        )
    if mode == "nest":
        try:
            from sift_pdf.solve.t3_nest import solve_nest
        except ImportError as exc:
            raise RuntimeError(
                "T3 nest solver requires the [nest] extra (spyrrow). "
                "Install with: pip install sift-pdf[nest]"
            ) from exc
        return solve_nest(
            jobs,
            press,
            availability,
            objective,
            seed=seed,
            budget_ms=budget_ms,
            cache_key=cache_key,
        )
    raise ValueError(f"Unknown solve mode: {mode!r}. Expected: grid, gang, nest.")


class GroupSolveResult(NamedTuple):
    """One bucket of a grouped solve: its partition key + the plan for it."""

    group_key: dict[str, AttributeValue]
    plan: SiftImposePlan
    cache_hit: bool


def solve_grouped(
    *,
    jobs: list[Job],
    press: PressProfile,
    mode: str,
    grouping_criteria: list[GroupingCriterion],
    availability: Availability | None = None,
    objective: ObjectiveWeights | None = None,
    seed: int = _DEFAULT_SEED,
    budget_ms: int = _DEFAULT_BUDGET_MS,
    stagger_mode: StaggerMode = "none",
    stagger_offset_pt: float = 0.0,
    bleed_handling: BleedHandling = "none",
) -> list[GroupSolveResult]:
    """Solve once per hard-partition bucket, biased by any soft criteria.

    Hard criteria partition ``jobs`` into independent press forms (each a
    separate, individually-cached :func:`solve`). Soft criteria are forwarded to
    the per-bucket solve as affinity hints. Returns one
    :class:`GroupSolveResult` per non-empty bucket, in deterministic key order.

    Reuses the existing per-mode solvers + content-addressed cache untouched:
    each bucket is a distinct jobs list, so its cache key already distinguishes
    it (no cross-bucket cache collisions).
    """
    hard, soft = split_criteria(grouping_criteria)
    soft_affinity = [(c.key, c.weight) for c in soft]

    results: list[GroupSolveResult] = []
    for group_key, bucket_jobs in partition_jobs(jobs, hard):
        if not bucket_jobs:
            continue
        plan, hit = solve(
            jobs=bucket_jobs,
            press=press,
            mode=mode,
            availability=availability,
            objective=objective,
            seed=seed,
            budget_ms=budget_ms,
            stagger_mode=stagger_mode,
            stagger_offset_pt=stagger_offset_pt,
            bleed_handling=bleed_handling,
            soft_affinity=soft_affinity or None,
        )
        results.append(GroupSolveResult(group_key_to_dict(group_key), plan, hit))
    return results


__all__ = ["GroupSolveResult", "solve", "solve_grouped"]
