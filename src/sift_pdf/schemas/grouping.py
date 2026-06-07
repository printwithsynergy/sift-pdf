"""Custom grouping criteria — partition (hard) or affinitise (soft) a solve.

A ``GroupingCriterion`` names a key in ``Job.attributes`` and declares how the
solver should treat jobs that share (or differ on) that attribute's value:

- ``mode="hard"`` — jobs are bucketed by the criterion's value and each bucket
  is solved as an independent press form; values never mix across forms.
- ``mode="soft"`` — jobs stay in one solve, but the solver is biased (in gang
  mode) to keep same-value jobs together and avoid mixing different values on
  one form. A nudge, not a constraint.

Multiple criteria compose: hard criteria form a composite partition key (one
bucket per distinct combination of their values); soft criteria are forwarded
to the per-mode solver. The value space is open — any ``AttributeValue``
(ISO-8601 date strings, booleans, numbers, free strings, null) — giving an
effectively unbounded set of custom groupings over any scalar the caller's data
model supports.
"""

from __future__ import annotations

import json
from typing import Literal, cast

from pydantic import BaseModel, Field

from sift_pdf.cache import canonicalize
from sift_pdf.schemas.jobs import AttributeValue, Job

# An ordered partition key: a tuple of (attribute-name, canonical-value) pairs,
# one per hard criterion, in criterion-declaration order.
GroupKey = tuple[tuple[str, AttributeValue], ...]


class GroupingError(ValueError):
    """A grouping criterion cannot be applied to the given jobs (→ HTTP 422).

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers still
    catch it; routes that want a 422 (rather than 400) catch ``GroupingError``
    first.
    """


class GroupingCriterion(BaseModel):
    """One custom grouping rule over a ``Job.attributes`` key."""

    model_config = {"extra": "forbid"}

    key: str = Field(
        ...,
        description="Attribute name to group by (looked up in Job.attributes).",
    )
    mode: Literal["hard", "soft"] = Field(
        default="hard",
        description=(
            "'hard' partitions jobs into independent forms by this value; "
            "'soft' biases the solver to keep same-value jobs together without "
            "forbidding a mix."
        ),
    )
    missing: Literal["own_group", "skip", "error"] = Field(
        default="own_group",
        description=(
            "How to treat a job that lacks this attribute (hard criteria only): "
            "'own_group' = bucket it under a null value; 'skip' = exclude the job "
            "from the grouped solve entirely; 'error' = reject the request (422)."
        ),
    )
    bucket: Literal["exact"] = Field(
        default="exact",
        description=(
            "Bucketing strategy for the value. 'exact' = group by equal value. "
            "(Seam for future strategies such as date windows or numeric ranges.)"
        ),
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Soft-affinity strength (soft criteria only); higher = stronger "
            "preference to avoid mixing values on one form. 0 disables. Ignored "
            "for hard criteria."
        ),
    )


def split_criteria(
    criteria: list[GroupingCriterion] | None,
) -> tuple[list[GroupingCriterion], list[GroupingCriterion]]:
    """Split criteria into (hard, soft), preserving declaration order."""
    if not criteria:
        return [], []
    hard = [c for c in criteria if c.mode == "hard"]
    soft = [c for c in criteria if c.mode == "soft"]
    return hard, soft


def _value_for(job: Job, key: str) -> AttributeValue:
    """Return the canonicalized attribute value for ``key`` (None if absent)."""
    return cast(AttributeValue, canonicalize(job.attributes.get(key)))


def group_key_to_dict(key: GroupKey) -> dict[str, AttributeValue]:
    """Render a composite GroupKey as a plain {attribute: value} mapping."""
    return dict(key)


def partition_jobs(
    jobs: list[Job],
    hard_criteria: list[GroupingCriterion],
) -> list[tuple[GroupKey, list[Job]]]:
    """Partition ``jobs`` into buckets by the composite hard-criteria key.

    Returns an ordered list of ``(group_key, jobs)`` pairs. Ordering is
    deterministic (buckets sorted by the canonical JSON of their key) so the
    grouped solve output is reproducible. ``missing`` policy is applied per
    criterion: ``own_group`` treats an absent attribute as ``None``, ``skip``
    drops the job, ``error`` raises ``ValueError`` (mapped to 422 by the route).
    """
    if not hard_criteria:
        return [((), list(jobs))]

    buckets: dict[str, tuple[GroupKey, list[Job]]] = {}
    for job in jobs:
        key_parts: list[tuple[str, AttributeValue]] = []
        skip_job = False
        for crit in hard_criteria:
            present = crit.key in job.attributes
            if not present and crit.missing == "error":
                raise GroupingError(
                    f"Job '{job.id}' is missing grouping attribute '{crit.key}' "
                    "(criterion missing='error')."
                )
            if not present and crit.missing == "skip":
                skip_job = True
                break
            key_parts.append((crit.key, _value_for(job, crit.key)))
        if skip_job:
            continue
        group_key: GroupKey = tuple(key_parts)
        bucket_id = json.dumps([list(p) for p in group_key], separators=(",", ":"), sort_keys=True)
        if bucket_id not in buckets:
            buckets[bucket_id] = (group_key, [])
        buckets[bucket_id][1].append(job)

    return [buckets[bid] for bid in sorted(buckets)]


__all__ = [
    "AttributeValue",
    "GroupKey",
    "GroupingCriterion",
    "GroupingError",
    "group_key_to_dict",
    "partition_jobs",
    "split_criteria",
]
