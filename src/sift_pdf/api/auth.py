"""API key authentication — mirrors compile-pdf's auth pattern.

Set SIFT_AUTH_MODE=api-key (default: none) and SIFT_API_KEY=<token>.
When auth mode is "none" all requests pass through unauthenticated.
"""

from __future__ import annotations

import os
import secrets

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
        if api_key is None or not secrets.compare_digest(api_key, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing X-Sift-Key.")
        return
    # Unknown / unsupported mode: fail CLOSED. A misconfigured SIFT_AUTH_MODE
    # (typo, or a mode that isn't implemented) must reject requests, not
    # silently disable authentication.
    raise HTTPException(
        status_code=500,
        detail=f"Unsupported SIFT_AUTH_MODE={auth_mode!r}; set 'none' or 'api-key'.",
    )


__all__ = ["authenticate"]
