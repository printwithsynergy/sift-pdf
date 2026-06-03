"""API key authentication — mirrors compile-pdf's auth pattern.

Set SIFT_AUTH_MODE=api-key (default: none) and SIFT_API_KEY=<token>.
When auth mode is "none" all requests pass through unauthenticated.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-Sift-Key", auto_error=False)


def authenticate(api_key: str | None = Security(_api_key_header)) -> None:
    """Dependency — validates X-Sift-Key when SIFT_AUTH_MODE=api-key."""
    auth_mode = os.environ.get("SIFT_AUTH_MODE", "none").strip().lower()
    if auth_mode == "none":
        return
    if auth_mode == "api-key":
        expected = os.environ.get("SIFT_API_KEY", "")
        if not expected:
            raise HTTPException(status_code=500, detail="SIFT_API_KEY not configured.")
        if api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing X-Sift-Key.")
    # Unknown mode: fail open with a warning (don't lock out in misconfigured deploys).


__all__ = ["authenticate"]
