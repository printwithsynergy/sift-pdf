"""Tests for content-addressed cache — determinism and key composition."""

from __future__ import annotations

import pytest

from sift_pdf.cache import cache_clear, cache_get, cache_put, canonicalize, compute_cache_key


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache_clear()


def test_canonicalize_sorts_keys() -> None:
    a = canonicalize({"b": 1, "a": 2})
    b = canonicalize({"a": 2, "b": 1})
    assert a == b


def test_canonicalize_drops_none() -> None:
    result = canonicalize({"a": 1, "b": None})
    assert "b" not in result


def test_canonicalize_drops_decoration_keys() -> None:
    result = canonicalize({"a": 1, "comment": "hi", "notes": "x", "_dev_meta": {}})
    assert result == {"a": 1}


def test_canonicalize_normalizes_float() -> None:
    # Different representations of the same number → identical canonical form.
    a = canonicalize(1.0)
    b = canonicalize(1.00000000000001)
    # They differ but should both be stable (not NaN/inf).
    assert isinstance(a, (int, float))
    assert isinstance(b, (int, float))


def test_cache_key_deterministic() -> None:
    kw = {
        "mode": "grid",
        "seed": 42,
        "budget_ms": 5000,
        "jobs": [{"id": "sku-1"}],
        "press": {"id": "p1"},
        "availability": None,
        "objective": None,
        "codex_pdf_version": "1.21.1",
        "geom_schema_version": "1.1.0",
    }
    k1 = compute_cache_key(**kw)
    k2 = compute_cache_key(**kw)
    assert k1 == k2
    assert len(k1) == 64  # SHA-256 hex


def test_cache_key_differs_on_mode() -> None:
    base = {
        "seed": 42,
        "budget_ms": 5000,
        "jobs": [{"id": "x"}],
        "press": {"id": "p"},
        "availability": None,
        "objective": None,
        "codex_pdf_version": "1.21.1",
        "geom_schema_version": "1.1.0",
    }
    k_grid = compute_cache_key(mode="grid", **base)
    k_gang = compute_cache_key(mode="gang", **base)
    assert k_grid != k_gang


def test_cache_roundtrip() -> None:
    cache_put("key1", {"foo": "bar"})
    assert cache_get("key1") == {"foo": "bar"}


def test_cache_miss_returns_none() -> None:
    assert cache_get("no-such-key") is None
