"""SiftPDF FastAPI application.

Exposes:
  GET  /healthz          — liveness + version + cache backend
  GET  /readyz           — readiness probe
  GET  /v1/contract      — contract surface (solver schema versions, codex versions)
  GET  /metrics          — Prometheus exposition

Producer routers mounted lazily under /v1/sift/ when the corresponding
tier is enabled via SIFT_TIERS (comma-separated: grid,gang,nest).
Default: all tiers attempted, but unavailable deps degrade gracefully.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from sift_pdf.api.auth import authenticate
from sift_pdf.api.middleware import INSTANCE_ID, RequestIdMiddleware
from sift_pdf.version import (
    CODEX_DOCUMENT_SCHEMA_VERSION_PIN,
    SOLVER_SCHEMA_VERSIONS,
    VERSION,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# RFC 7807 helpers — reuse codex_pdf.errors (cross-stack canonical shape)
# ---------------------------------------------------------------------------
try:
    from codex_pdf.errors import PROBLEM_CONTENT_TYPE, build_problem

    _HAS_CODEX_ERRORS = True
except ImportError:  # pragma: no cover
    _HAS_CODEX_ERRORS = False
    PROBLEM_CONTENT_TYPE = "application/problem+json"

    def build_problem(
        status: int,
        title: str,
        detail: str,
        *,
        instance: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "type": f"https://docs.printwithsynergy.com/problems/status-{status}",
            "title": title,
            "status": status,
            "detail": detail,
        }
        if instance:
            body["instance"] = instance
        if extras:
            body.update(extras)
        return type("PD", (), {"model_dump": lambda self, **_kw: body})()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    instance_id: str
    cache_backend: str
    enabled_tiers: list[str] = Field(default_factory=list)
    codex_pdf_version: str
    codex_section_versions: dict[str, str] = Field(default_factory=dict)


class ContractResponse(BaseModel):
    contract_name: str
    schema_version: str
    package_version: str
    endpoints: list[str]
    solver_schema_versions: dict[str, str] = Field(default_factory=dict)
    codex_section_versions: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _codex_pdf_version() -> str:
    try:
        from codex_pdf import __version__ as v

        return str(v)
    except ImportError:
        return "unknown"


def _codex_section_versions() -> dict[str, str]:
    try:
        from codex_pdf.geom import GEOM_SCHEMA_VERSION

        return {
            "geom": GEOM_SCHEMA_VERSION,
            "codex-document": CODEX_DOCUMENT_SCHEMA_VERSION_PIN,
        }
    except ImportError:
        return {}


def _enabled_tiers() -> list[str]:
    raw = os.environ.get("SIFT_TIERS", "grid,gang,nest").strip()
    return [t.strip().lower() for t in raw.split(",") if t.strip()]


def _cache_backend() -> str:
    return os.environ.get("SIFT_CACHE_BACKEND", "memory").strip()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
    logger.info(
        "sift_api.startup",
        version=VERSION,
        tiers=_enabled_tiers(),
        instance_id=INSTANCE_ID,
    )
    yield
    logger.info("sift_api.shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="sift-pdf",
    version=VERSION,
    description="Stateless imposition planning solver for the Print With Synergy stack.",
    lifespan=lifespan,
)
app.add_middleware(RequestIdMiddleware)


# ---------------------------------------------------------------------------
# RFC 7807 exception handlers (mirrors compile-pdf/api/main.py)
# ---------------------------------------------------------------------------


def _title_for(status: int) -> str:
    return {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        422: "Unprocessable Entity",
        429: "Too Many Requests",
        500: "Internal Server Error",
        501: "Not Implemented",
        502: "Bad Gateway",
        503: "Service Unavailable",
    }.get(status, f"HTTP {status}")


@app.exception_handler(StarletteHTTPException)
async def _problem_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    body = build_problem(
        exc.status_code,
        _title_for(exc.status_code),
        str(exc.detail) if exc.detail else _title_for(exc.status_code),
        instance=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
        headers=getattr(exc, "headers", None) or {},
    )


@app.exception_handler(RequestValidationError)
async def _problem_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = build_problem(
        422,
        "Unprocessable Entity",
        "Request body failed schema validation.",
        instance=request.url.path,
        extras={"errors": exc.errors()},
    )
    return JSONResponse(
        status_code=422,
        content=body.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


@app.exception_handler(Exception)
async def _problem_unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception", path=request.url.path)
    body = build_problem(
        500,
        "Internal Server Error",
        f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
        instance=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content=body.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


# ---------------------------------------------------------------------------
# Contract endpoints (always open — no auth)
# ---------------------------------------------------------------------------


@app.get("/healthz", response_model=HealthResponse, include_in_schema=False)
async def healthz_alias() -> HealthResponse:
    return await healthz()


@app.get("/v1/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness probe — returns 'ok' as long as process is running."""
    return HealthResponse(
        status="ok",
        version=VERSION,
        instance_id=INSTANCE_ID,
        cache_backend=_cache_backend(),
        enabled_tiers=_enabled_tiers(),
        codex_pdf_version=_codex_pdf_version(),
        codex_section_versions=_codex_section_versions(),
    )


@app.get("/readyz", include_in_schema=False)
async def readyz_alias() -> dict[str, str]:
    return await readyz()


@app.get("/v1/readyz")
async def readyz() -> dict[str, str]:
    """Readiness probe."""
    return {"status": "ready"}


@app.get("/v1/contract", response_model=ContractResponse)
async def contract() -> ContractResponse:
    """Published contract surface — solver schema versions + codex section versions."""
    return ContractResponse(
        contract_name="sift-pdf",
        schema_version="1.0.0",
        package_version=VERSION,
        endpoints=[r.path for r in app.routes if hasattr(r, "path")],
        solver_schema_versions=SOLVER_SCHEMA_VERSIONS,
        codex_section_versions=_codex_section_versions(),
    )


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus exposition."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Producer routers — lazy mount, gated by SIFT_TIERS
# ---------------------------------------------------------------------------

_AUTH_DEPS = [Depends(authenticate)]


def _mount_routers() -> None:
    enabled = set(_enabled_tiers())

    try:
        from sift_pdf.solve.api import router as solve_router

        app.include_router(solve_router, prefix="/v1/sift", tags=["solve"], dependencies=_AUTH_DEPS)
    except ImportError:
        logger.debug("solve_router_not_available")

    try:
        from sift_pdf.suggest.api import router as suggest_router

        app.include_router(
            suggest_router, prefix="/v1/sift", tags=["suggest"], dependencies=_AUTH_DEPS
        )
    except ImportError:
        logger.debug("suggest_router_not_available")

    try:
        from sift_pdf.estimate.api import router as estimate_router

        app.include_router(
            estimate_router, prefix="/v1/sift", tags=["estimate"], dependencies=_AUTH_DEPS
        )
    except ImportError:
        logger.debug("estimate_router_not_available")

    _ = enabled  # referenced when per-tier gating is added in Wave 2+


_mount_routers()
