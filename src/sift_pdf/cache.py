"""Content-addressed plan cache.

Cache key composition (alphabetical-by-name for cross-implementation reproducibility):

1. availability_sha256   — SHA-256 of canonical availability snapshot (or "none")
2. budget_ms             — solver time budget
3. codex_pdf_version     — codex-pdf wheel version
4. geom_schema_version   — codex_pdf.geom.GEOM_SCHEMA_VERSION
5. jobs_sha256           — SHA-256 of canonical jobs list
6. mode                  — solve mode (grid | gang | nest | suggest)
7. objective_sha256      — SHA-256 of canonical objective weights (or "none")
8. press_sha256          — SHA-256 of canonical press profile
9. seed                  — RNG seed
10. sift_version         — sift-pdf package version

A codex section bump auto-invalidates cached plans (load-bearing operational property).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sift_pdf.version import VERSION as SIFT_VERSION

_QUANTIZE = Decimal("1E-12")
_DROPPED_KEYS = frozenset({"comment", "notes", "_dev_meta"})


def canonicalize(
    value: Mapping[str, Any] | list[Any] | str | int | float | bool | None,
) -> Any:
    """Recursively sort keys, normalize floats, strip nulls and decoration keys.

    Matches compile-pdf's canonicalize_plan contract for cross-service
    reproducibility (spec §2.2).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        quantized = Decimal(repr(value)).quantize(_QUANTIZE, rounding=ROUND_HALF_EVEN).normalize()
        s = format(quantized, "f")
        try:
            int_val = int(s)
            if "." not in s:
                return int_val
        except ValueError:
            pass
        return float(s)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    if isinstance(value, Mapping):
        return {
            key: canonicalize(v)
            for key, v in sorted(value.items())
            if key not in _DROPPED_KEYS and v is not None
        }
    raise TypeError(f"Unsupported type: {type(value)!r}")


def _sha256_canonical(obj: Any) -> str:
    """Return the SHA-256 hex of the canonical JSON serialization of obj."""
    canonical = canonicalize(obj) if not isinstance(obj, str) else obj
    serialized = json.dumps(canonical, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def compute_cache_key(
    *,
    mode: str,
    seed: int,
    budget_ms: int,
    jobs: Any,
    press: Any,
    availability: Any | None,
    objective: Any | None,
    sift_version: str = SIFT_VERSION,
    codex_pdf_version: str,
    geom_schema_version: str,
    nest_engine_fingerprint: str = "",
) -> str:
    """Compose the content-addressed cache key for a solve request.

    Returns hex-encoded SHA-256. Components joined with '|' alphabetically
    so the digest is reproducible across language implementations.
    nest_engine_fingerprint is only non-empty for mode='nest'; omitting it
    (empty string) leaves grid/gang cache keys unchanged.
    """
    parts = [
        _sha256_canonical(availability) if availability is not None else "none",
        str(budget_ms),
        codex_pdf_version,
        geom_schema_version,
        _sha256_canonical(jobs),
        mode,
    ]
    # Only include fingerprint when non-empty so grid/gang hashes are unchanged
    if nest_engine_fingerprint:
        parts.append(nest_engine_fingerprint)
    parts.extend(
        [
            _sha256_canonical(objective) if objective is not None else "none",
            _sha256_canonical(press),
            str(seed),
            sift_version,
        ]
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# In-process LRU cache (no I/O dependencies for stateless deployments).
# Set SIFT_CACHE_BACKEND=redis + SIFT_REDIS_URL for distributed caching.
# ---------------------------------------------------------------------------

_MEMORY_CACHE: dict[str, Any] = {}
_MAX_MEMORY_ENTRIES = 1024


def cache_get(key: str) -> Any | None:
    """Return cached plan or None on miss."""
    return _MEMORY_CACHE.get(key)


def cache_put(key: str, value: Any) -> None:
    """Store plan in cache; evict oldest entry when full."""
    if len(_MEMORY_CACHE) >= _MAX_MEMORY_ENTRIES:
        oldest = next(iter(_MEMORY_CACHE))
        del _MEMORY_CACHE[oldest]
    _MEMORY_CACHE[key] = value


def cache_clear() -> None:
    """Clear all entries — for testing only."""
    _MEMORY_CACHE.clear()


__all__ = [
    "canonicalize",
    "compute_cache_key",
    "cache_get",
    "cache_put",
    "cache_clear",
]
