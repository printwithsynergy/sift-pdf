"""Tests for custom grouping criteria — partition + helpers."""

from __future__ import annotations

import pytest

from sift_pdf.schemas.grouping import (
    GroupingCriterion,
    GroupingError,
    group_key_to_dict,
    partition_jobs,
    split_criteria,
)
from sift_pdf.schemas.jobs import Job


def _job(job_id: str, attributes: dict | None = None) -> Job:
    return Job(
        id=job_id,
        die={"type": "rect", "width_pt": 100.0, "height_pt": 100.0},  # type: ignore[arg-type]
        quantity=100,
        attributes=attributes or {},
    )


def _keys(buckets: list) -> list[dict]:
    return [group_key_to_dict(k) for k, _ in buckets]


# --- hard partition by each scalar type ------------------------------------


def test_partition_by_string_value() -> None:
    jobs = [
        _job("a", {"customer": "acme"}),
        _job("b", {"customer": "globex"}),
        _job("c", {"customer": "acme"}),
    ]
    crit = [GroupingCriterion(key="customer", mode="hard")]
    buckets = partition_jobs(jobs, crit)
    assert _keys(buckets) == [{"customer": "acme"}, {"customer": "globex"}]
    assert [j.id for j in buckets[0][1]] == ["a", "c"]
    assert [j.id for j in buckets[1][1]] == ["b"]


def test_partition_by_boolean_value() -> None:
    jobs = [_job("a", {"rush": True}), _job("b", {"rush": False}), _job("c", {"rush": True})]
    buckets = partition_jobs(jobs, [GroupingCriterion(key="rush")])
    keys = _keys(buckets)
    assert {"rush": False} in keys and {"rush": True} in keys
    by_val = {
        tuple(d.items()): [j.id for j in jb] for d, (_, jb) in zip(keys, buckets, strict=True)
    }
    assert by_val[(("rush", True),)] == ["a", "c"]
    assert by_val[(("rush", False),)] == ["b"]


def test_partition_by_numeric_value() -> None:
    jobs = [_job("a", {"lane": 1}), _job("b", {"lane": 2}), _job("c", {"lane": 1})]
    buckets = partition_jobs(jobs, [GroupingCriterion(key="lane")])
    assert len(buckets) == 2


def test_partition_by_date_string() -> None:
    jobs = [
        _job("a", {"ship_date": "2026-06-10"}),
        _job("b", {"ship_date": "2026-06-11"}),
        _job("c", {"ship_date": "2026-06-10"}),
    ]
    buckets = partition_jobs(jobs, [GroupingCriterion(key="ship_date")])
    assert _keys(buckets) == [{"ship_date": "2026-06-10"}, {"ship_date": "2026-06-11"}]


def test_partition_composite_multi_criteria() -> None:
    jobs = [
        _job("a", {"ship_date": "2026-06-10", "rush": True}),
        _job("b", {"ship_date": "2026-06-10", "rush": False}),
        _job("c", {"ship_date": "2026-06-10", "rush": True}),
    ]
    crit = [GroupingCriterion(key="ship_date"), GroupingCriterion(key="rush")]
    buckets = partition_jobs(jobs, crit)
    # Two buckets: (date,rush=True) -> a,c ; (date,rush=False) -> b
    assert len(buckets) == 2
    sizes = sorted(len(jb) for _, jb in buckets)
    assert sizes == [1, 2]


# --- missing-attribute policies --------------------------------------------


def test_missing_own_group_buckets_nulls_together() -> None:
    jobs = [_job("a", {"k": "x"}), _job("b", {}), _job("c", {})]
    buckets = partition_jobs(jobs, [GroupingCriterion(key="k", missing="own_group")])
    null_bucket = [jb for k, jb in buckets if group_key_to_dict(k) == {"k": None}]
    assert len(null_bucket) == 1
    assert [j.id for j in null_bucket[0]] == ["b", "c"]


def test_missing_skip_drops_job() -> None:
    jobs = [_job("a", {"k": "x"}), _job("b", {})]
    buckets = partition_jobs(jobs, [GroupingCriterion(key="k", missing="skip")])
    all_ids = [j.id for _, jb in buckets for j in jb]
    assert all_ids == ["a"]


def test_missing_error_raises() -> None:
    jobs = [_job("a", {"k": "x"}), _job("b", {})]
    with pytest.raises(GroupingError):
        partition_jobs(jobs, [GroupingCriterion(key="k", missing="error")])


# --- no hard criteria + determinism ----------------------------------------


def test_no_hard_criteria_single_bucket() -> None:
    jobs = [_job("a"), _job("b")]
    buckets = partition_jobs(jobs, [])
    assert len(buckets) == 1
    assert group_key_to_dict(buckets[0][0]) == {}
    assert [j.id for j in buckets[0][1]] == ["a", "b"]


def test_bucket_order_is_deterministic() -> None:
    jobs = [_job(x, {"k": x}) for x in ("c", "a", "b", "a")]
    b1 = _keys(partition_jobs(jobs, [GroupingCriterion(key="k")]))
    b2 = _keys(partition_jobs(jobs, [GroupingCriterion(key="k")]))
    assert b1 == b2
    # sorted by canonical key
    assert b1 == [{"k": "a"}, {"k": "b"}, {"k": "c"}]


# --- split_criteria ---------------------------------------------------------


def test_split_criteria_preserves_order() -> None:
    crit = [
        GroupingCriterion(key="a", mode="hard"),
        GroupingCriterion(key="b", mode="soft"),
        GroupingCriterion(key="c", mode="hard"),
    ]
    hard, soft = split_criteria(crit)
    assert [c.key for c in hard] == ["a", "c"]
    assert [c.key for c in soft] == ["b"]


def test_split_criteria_none() -> None:
    assert split_criteria(None) == ([], [])
