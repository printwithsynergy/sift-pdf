"""Version pins for sift-pdf and codex section contracts."""

from __future__ import annotations

VERSION = "0.1.1"

SOLVE_SCHEMA_VERSION = "1.0.0"
SUGGEST_SCHEMA_VERSION = "1.0.0"
ESTIMATE_SCHEMA_VERSION = "1.0.0"
SIFT_DOCUMENT_SCHEMA_VERSION = "1.0.0"

# Pinned at build time — rotate when a codex major bump changes /v1/contract
# or the cache-key VERSION scheme. Match the version compiled against.
CODEX_DOCUMENT_SCHEMA_VERSION_PIN = "1.3.0"

SOLVER_SCHEMA_VERSIONS: dict[str, str] = {
    "solve": SOLVE_SCHEMA_VERSION,
    "suggest": SUGGEST_SCHEMA_VERSION,
    "estimate": ESTIMATE_SCHEMA_VERSION,
}

# Rotate this pin whenever the spyrrow wheel version changes to invalidate
# nest-mode cache keys that may have been produced by an earlier engine.
NEST_ENGINE_FINGERPRINT = "spyrrow-0.9.0"
