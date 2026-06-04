# Changelog

All notable changes to sift-pdf are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `DielineRefDie` support in T2 gang and T3 nest solvers: when the availability
  snapshot includes shape info (`width_pt`/`height_pt` or `polygon_points`) on the
  matching `DieStock` entry, the die is resolved and placed like any rect or polygon
  die. Silently skipped if no availability snapshot is provided.
- Optional shape fields on `DieStock` (`width_pt`, `height_pt`, `polygon_points`) for
  `DielineRefDie` resolution; `qty` now accepts `0` (tracked-but-out-of-stock).
- Availability hard-constraint enforcement in T2 and T3:
  - `required_die_id`: raises `ValueError` if die is absent from the snapshot or has
    `qty = 0`.
  - `allowed_substrate_ids`: raises `ValueError` if no listed substrate has
    `qty_on_hand >= 1` when an availability snapshot is provided.

## [0.1.0] — 2026-06-03

Initial release. All three solver tiers and the full HTTP API surface.

### Added

#### Solver tiers
- **T1 grid** (`mode=grid`): uniform step-and-repeat via `codex_pdf.geom.tile_grid`; stagger cuts
  (`half-drop-x`, `half-drop-y`, `custom` offset) emitted as `explicit_placements`
- **T2 gang** (`mode=gang`): multi-SKU quantity balancing across press forms using OR-Tools CP-SAT;
  optional `[gang]` extra (`ortools>=9.10`)
- **T3 nest** (`mode=nest`): true-shape irregular-die nesting using spyrrow/sparrow strip packing;
  optional `[nest]` extra (`spyrrow>=0.9.0`)
- Repeat-snapping engine: geared (tooth-count × circular-pitch), servo (continuous range),
  digital-web (max frame), digital-sheet / offset-sheet (fixed dimensions)

#### API
- `POST /v1/sift/solve` — stateless, deterministic layout solve; content-addressed cache;
  `X-Sift-Seed` and `X-Sift-Budget-Ms` header overrides
- `POST /v1/sift/suggest` — sweep a substrate catalog, return the layout with lowest waste %
- `POST /v1/sift/estimate` — derive `EstimateManifest` (plate count, material area m², cost)
  from an existing `SiftImposePlan`; no new solve
- `GET /v1/contract` — published schema versions + codex section versions
- `GET /v1/healthz`, `GET /healthz` — liveness probe
- `GET /v1/readyz`, `GET /readyz` — readiness probe
- `GET /metrics` — Prometheus exposition

#### Handoff
- `sift_pdf.handoff.compile.to_compile_impose_plan` — translates `SiftImposePlan` to
  compile-pdf's `ImposePlan` dict (grid fast-path; explicit-placements requires compile-pdf ≥1.1.0)
- `sift_pdf.handoff.compile.to_cjd_envelope` — builds compile-pdf CJD envelope chaining
  compose → marks → impose in canonical order

#### Infrastructure
- In-memory LRU cache; optional Redis backend (`SIFT_CACHE_BACKEND=redis`, `SIFT_REDIS_URL`)
- API key auth (`SIFT_AUTH_MODE=api-key`, `SIFT_API_KEY`)
- `SIFT_TIERS` env var gates which solver tiers are available (default: `grid,gang,nest`)
- RFC 7807 Problem Details on all error responses
- `X-Sift-Request-Id` middleware
- CLI: `sift-pdf version | health | contract`
- Spectral-clean OpenAPI 3.1 spec at `docs/openapi.yaml`
- Two-stage Dockerfile; tini init; non-root user `sift` (uid 10001)
- Surface audit (`scripts/consume_surface_audit.py`) — CI-enforced ban on reimplementing
  codex geometry primitives

### Dependencies
- `codex-pdf>=1.21.1,<2.0` — in-process geometry (tile_grid, Box, CellPlacement, polygon ops)
- `ortools>=9.10` — T2 gang solver (Apache-2.0, optional `[gang]`)
- `spyrrow>=0.9.0` — T3 nest solver (MIT, optional `[nest]`)
- `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `pydantic>=2.8`

### Known limitations
- Gang/nest/stagger PDF generation requires compile-pdf ≥1.1.0 with `explicit_placements`
  on `ImposePlan` (cross-repo PR pending). Plans are produced correctly; the PDF write step
  is blocked until that PR merges.
- `DielineRefDie` not yet supported by T3 nest (rect and polygon dies only).
- `availability` constraints (substrates, dies, press slots) accepted for interface
  compatibility but not yet enforced by T3 (planned for a future release).
