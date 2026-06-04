# Deployment

## Running the service

Install the base package and start the server:

```bash
pip install "sift-pdf[gang,nest]"
uvicorn sift_pdf.api.main:app --host 0.0.0.0 --port 8100
```

Or using Docker:

```bash
docker build -t sift-pdf .
docker run -p 8100:8100 sift-pdf
```

The container is a two-stage build (`python:3.12-slim`, uv) with tini as the init process
and a non-root `sift` user (uid 10001). The `SIFT_TIERS` build arg controls which solver
extras are installed:

```bash
docker build --build-arg SIFT_TIERS=grid,gang -t sift-pdf .
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SIFT_TIERS` | `grid,gang,nest` | Comma-separated list of enabled solver tiers. Requests for a disabled tier return 501. |
| `SIFT_CACHE_BACKEND` | `memory` | Cache backend. `memory` = in-process LRU; `redis` = Redis. |
| `SIFT_REDIS_URL` | — | Redis connection URL. Required when `SIFT_CACHE_BACKEND=redis`. |
| `SIFT_AUTH_MODE` | `none` | Authentication mode. `none` = open; `api-key` = bearer token required on `/v1/sift/*` routes. |
| `SIFT_API_KEY` | — | API key value. Required when `SIFT_AUTH_MODE=api-key`. |
| `LOG_LEVEL` | `info` | structlog level (`debug`, `info`, `warning`, `error`). |

## Optional extras

The base package ships T1 (grid + stagger). Additional solver tiers require optional extras:

```bash
pip install "sift-pdf[gang]"    # T2 — OR-Tools CP-SAT (Apache-2.0)
pip install "sift-pdf[nest]"    # T3 — spyrrow / sparrow (MIT)
pip install "sift-pdf[geom]"    # polygon ops via codex_pdf.geom (pyclipr, MIT)
```

The Docker image installs the extras matching the `SIFT_TIERS` build arg. A deployment
that only needs grid imposition can set `SIFT_TIERS=grid` to skip the OR-Tools and
spyrrow wheels (~200 MB combined).

## Healthcheck and readiness

Kubernetes liveness and readiness probes:

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8100
  initialDelaySeconds: 5
  periodSeconds: 15

readinessProbe:
  httpGet:
    path: /readyz
    port: 8100
  initialDelaySeconds: 2
  periodSeconds: 5
```

`/healthz` returns the package version, enabled tiers, cache backend, and the codex-pdf
version currently in the process. `/readyz` returns `{"status": "ready"}` as soon as the
ASGI app is serving. Neither endpoint requires authentication.

## Authentication

API key auth applies only to `/v1/sift/*` routes. Health, readiness, contract, and metrics
endpoints are always open.

```bash
SIFT_AUTH_MODE=api-key SIFT_API_KEY=mysecretkey uvicorn sift_pdf.api.main:app --port 8100
```

Callers pass the key in the `Authorization` header:

```
Authorization: Bearer mysecretkey
```

## Solver budget

By default T2 (gang) and T3 (nest) solvers run for up to 5 000 ms. Override per-request
via the `X-Sift-Budget-Ms` header (minimum 100 ms) or the `budget_ms` body field. The
header takes precedence when both are supplied.

## Cache

The in-memory LRU cache persists only within a single process. For multi-replica
deployments, configure a shared Redis backend:

```bash
SIFT_CACHE_BACKEND=redis SIFT_REDIS_URL=redis://redis:6379/0 uvicorn sift_pdf.api.main:app
```

Cache keys are 64-character SHA-256 hex digests that incorporate the sift-pdf version,
codex-pdf version, geom schema version, and all solver inputs. Upgrading any of these
components automatically invalidates old entries. The key is returned in the
`X-Sift-Cache-Key` response header so callers can log it for debugging.

## Contract surface

`GET /v1/contract` returns the published schema versions:

```json
{
  "contract_name": "sift-pdf",
  "package_version": "0.1.0",
  "schema_version": "1.0.0",
  "solver_schema_versions": {
    "solve": "1.0.0",
    "suggest": "1.0.0",
    "estimate": "1.0.0"
  },
  "codex_section_versions": {
    "geom": "1.1.0",
    "codex-document": "1.3.0"
  }
}
```

The codex section versions are pinned at build time in `src/sift_pdf/version.py` and
rotate when a codex major bump changes the cache-key scheme. The compile-pdf sidecar
consumes this endpoint to confirm schema compatibility before forwarding plans.

## CLI

The `sift-pdf` CLI is available in the installed environment:

```bash
sift-pdf version    # print the package version
sift-pdf health     # print codex version and enabled tiers as JSON
sift-pdf contract   # print the /v1/contract surface as JSON
```

## Prometheus metrics

`GET /metrics` exposes Prometheus text exposition. Scrape configuration:

```yaml
scrape_configs:
  - job_name: sift-pdf
    static_configs:
      - targets: ["sift-pdf:8100"]
    metrics_path: /metrics
```

## Local development

```bash
uv sync --extra dev
uvicorn sift_pdf.api.main:app --reload --port 8100

uv run ruff check src tests scripts
uv run ruff format src tests scripts
uv run mypy src
uv run python scripts/consume_surface_audit.py
uv run pytest --cov=sift_pdf --cov-fail-under=70
npx @stoplight/spectral-cli lint docs/openapi.yaml
```
