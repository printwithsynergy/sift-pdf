# sift-pdf Usage Guide

sift-pdf is a stateless HTTP sidecar that answers one question:

> *Given SKU/job rules + a press/substrate context, what is the most efficient imposition layout?*

It produces a `SiftImposePlan` and hands it to `compile-pdf.impose` for PDF generation.
It never writes PDF bytes itself.

---

## Table of contents

1. [Running the service](#running-the-service)
2. [Authentication](#authentication)
3. [Press profiles](#press-profiles)
4. [Jobs and dies](#jobs-and-dies)
5. [Solving a layout](#solving-a-layout)
   - [Grid (uniform)](#grid-uniform)
   - [Grid (stagger cuts)](#grid-stagger-cuts)
   - [Gang (multi-SKU)](#gang-multi-sku)
   - [Nest (true-shape)](#nest-true-shape)
6. [Substrate suggestion](#substrate-suggestion)
7. [Estimate manifest](#estimate-manifest)
8. [Cache and determinism](#cache-and-determinism)
9. [Handing off to compile-pdf](#handing-off-to-compile-pdf)
10. [Environment variables](#environment-variables)
11. [CLI reference](#cli-reference)

---

## Running the service

```bash
# Development
pip install "sift-pdf[gang,nest]"
uvicorn sift_pdf.api.main:app --reload --port 8100

# Docker
docker run -p 8100:8100 \
  -e SIFT_TIERS=grid,gang,nest \
  sift-pdf:latest
```

Smoke-test:

```bash
curl http://localhost:8100/healthz
curl http://localhost:8100/v1/contract
```

---

## Authentication

By default all requests pass through unauthenticated (`SIFT_AUTH_MODE=none`).

To enable API key auth:

```bash
export SIFT_AUTH_MODE=api-key
export SIFT_API_KEY=your-secret-token
```

Pass the key in every request to `/v1/sift/*` endpoints:

```bash
curl -H "X-Sift-Key: your-secret-token" http://localhost:8100/v1/sift/solve ...
```

Health and contract endpoints are always open (no auth required).

---

## Press profiles

All solve requests require a `press_profile`. The `repeat_model` field is a discriminated union
on `type`.

### Servo (variable-repeat web)

```json
{
  "id": "my-servo-press",
  "web_width_pt": 864.0,
  "repeat_model": {
    "type": "servo",
    "min_repeat_pt": 144.0,
    "max_repeat_pt": 864.0
  },
  "gap_across_pt": 6.0,
  "gap_around_pt": 6.0
}
```

### Geared (flexo/gravure — snapped repeats)

```json
{
  "id": "flexo-press",
  "web_width_pt": 508.0,
  "repeat_model": {
    "type": "geared",
    "gear_set": [
      {"teeth": 80, "circular_pitch_pt": 4.5},
      {"teeth": 96, "circular_pitch_pt": 4.5}
    ]
  }
}
```

### Digital / offset sheet

```json
{
  "id": "offset-sheet-press",
  "repeat_model": {
    "type": "offset-sheet",
    "sheet_width_pt": 792.0,
    "sheet_height_pt": 1224.0
  }
}
```

`type` options: `servo` | `geared` | `digital-web` | `digital-sheet` | `offset-sheet`

---

## Jobs and dies

Each job describes one SKU. `die` is a discriminated union on `type`.

```json
{
  "id": "label-sku-1",
  "die": {
    "type": "rect",
    "width_pt": 288.0,
    "height_pt": 144.0
  },
  "bleed_pt": 9.0,
  "quantity": 5000,
  "separations": 4,
  "min_gap_pt": 3.0,
  "allowed_rotations": [0, 90]
}
```

Die types:
- `rect` — `width_pt`, `height_pt`
- `polygon` — `points: [[x,y], ...]` (closed polygon in points)
- `dieline-ref` — `dieline_id` reference (T3 nest does not yet support this type)

---

## Solving a layout

### Grid (uniform)

Uniform step-and-repeat. Uses `codex_pdf.geom.tile_grid` internally.

```bash
curl -X POST http://localhost:8100/v1/sift/solve \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [{
      "id": "sku-1",
      "die": {"type": "rect", "width_pt": 288, "height_pt": 144},
      "quantity": 1000
    }],
    "press_profile": {
      "id": "servo-1",
      "web_width_pt": 864,
      "repeat_model": {"type": "servo", "min_repeat_pt": 144, "max_repeat_pt": 864}
    },
    "mode": "grid"
  }'
```

Response (abbreviated):

```json
{
  "plan": {
    "mode": "grid",
    "tier": "T1",
    "waste_pct": 0.0,
    "grid_layout": {"rows": 1, "cols": 3, "stagger_mode": "none"},
    "sheet": {"width_pt": 864, "height_pt": 144},
    "cache_key": "a3f9..."
  },
  "cache_hit": false
}
```

The response header `X-Sift-Cache-Key` carries the 64-hex cache key.

### Grid (stagger cuts)

Half-drop and brick patterns for labels, folding cartons, and repeat-cut work.

```json
{
  "mode": "grid",
  "stagger_mode": "half-drop-x",
  "jobs": [...],
  "press_profile": {...}
}
```

`stagger_mode` options:
| Value | Effect |
|---|---|
| `none` | Uniform grid (default) |
| `half-drop-x` | Odd rows shift right by `(cell_width + gutter_x) / 2` |
| `half-drop-y` | Odd columns shift up by `(cell_height + gutter_y) / 2` |
| `custom` | Specify exact `stagger_offset_pt` |

Stagger plans emit `explicit_placements` instead of `grid_layout` and require
compile-pdf ≥1.1.0 for PDF generation (cross-repo PR pending).

### Gang (multi-SKU)

Balances multiple SKUs across a press form using OR-Tools CP-SAT. Requires `[gang]` extra.

```json
{
  "mode": "gang",
  "budget_ms": 5000,
  "jobs": [
    {"id": "sku-1", "die": {"type": "rect", "width_pt": 144, "height_pt": 144}, "quantity": 500},
    {"id": "sku-2", "die": {"type": "rect", "width_pt": 216, "height_pt": 144}, "quantity": 1000}
  ],
  "press_profile": {
    "id": "servo-1",
    "web_width_pt": 864,
    "repeat_model": {"type": "servo", "min_repeat_pt": 144, "max_repeat_pt": 864}
  }
}
```

The solver minimises waste while respecting quantity ratios. Returns `explicit_placements`
and `sku_placement_map` (maps each Job.id to its placement indices).

### Nest (true-shape)

Irregular-die bin packing via spyrrow/sparrow. Requires `[nest]` extra.

```json
{
  "mode": "nest",
  "seed": 42,
  "budget_ms": 10000,
  "jobs": [
    {
      "id": "die-shape",
      "die": {
        "type": "polygon",
        "points": [[0,0],[72,0],[72,108],[36,144],[0,108]]
      },
      "quantity": 200
    }
  ],
  "press_profile": {
    "id": "sheet-press",
    "repeat_model": {"type": "offset-sheet", "sheet_width_pt": 792, "sheet_height_pt": 1224}
  }
}
```

`seed` + `budget_ms` are part of the cache key — identical inputs always return the same plan.

#### Budget and seed headers

Override body values without changing the request JSON:

```bash
curl -H "X-Sift-Seed: 99" -H "X-Sift-Budget-Ms: 3000" \
  -X POST http://localhost:8100/v1/sift/solve -d '{...}'
```

---

## Substrate suggestion

Sweep a catalog of substrate candidates and return the layout with the lowest waste %.

```bash
curl -X POST http://localhost:8100/v1/sift/suggest \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [{"id": "sku-1", "die": {"type": "rect", "width_pt": 144, "height_pt": 144}, "quantity": 500}],
    "substrate_catalog": [
      {"id": "narrow-roll", "web_width_pt": 432},
      {"id": "wide-roll",   "web_width_pt": 864},
      {"id": "extra-wide",  "web_width_pt": 1016}
    ],
    "press_profile": {
      "id": "servo-1",
      "web_width_pt": 864,
      "repeat_model": {"type": "servo", "min_repeat_pt": 144, "max_repeat_pt": 864}
    }
  }'
```

Response:

```json
{
  "plan": { "...": "..." },
  "substrate_id": "wide-roll",
  "candidates_evaluated": 3
}
```

Infeasible candidates (die too large for the substrate) are silently skipped.
Returns HTTP 400 if all candidates are infeasible.

---

## Estimate manifest

Derive billing/cost metrics from an existing plan without running a new solve.

```bash
curl -X POST http://localhost:8100/v1/sift/estimate \
  -H "Content-Type: application/json" \
  -d '{"plan": <SiftImposePlan JSON>}'
```

Response:

```json
{
  "schema_version": "1.0.0",
  "plan_cache_key": "a3f9...",
  "plate_count": 4,
  "cells_total": 12,
  "waste_pct": 8.3,
  "est_material_area_m2": 0.018432,
  "est_cost": null,
  "special_processes": []
}
```

`est_material_area_m2` is converted from the plan's `material_area_pt2` using the
exact factor `(1/72 × 0.0254)²`.

---

## Cache and determinism

Every solve is content-addressed:

```
cache_key = SHA-256(
  availability_sha | budget_ms | codex_pdf_version | geom_schema_version |
  jobs_sha | mode | [nest_engine_fingerprint] | objective_sha | press_sha | seed | sift_version
)
```

Identical requests return the same plan (cache hit, `cache_hit: true` in response).
The `X-Sift-Cache-Key` response header carries the key for downstream lineage tracking.

T3 nest plans additionally include `NEST_ENGINE_FINGERPRINT` (e.g. `spyrrow-0.9.0`) in the
key so cache entries are invalidated when the nest engine version changes.

---

## Handing off to compile-pdf

### Grid fast-path (no explicit placements)

```python
from sift_pdf.handoff.compile import to_compile_impose_plan

compile_plan = to_compile_impose_plan(sift_plan)
# POST compile_plan to compile-pdf /v1/impose/apply
```

### CJD envelope (full pipeline)

Chains compose → marks → impose in compile-pdf's canonical order:

```python
from sift_pdf.handoff.compile import to_cjd_envelope

source_refs = {
    "sku-1": "s3://bucket/artwork/sku-1.pdf",
    "sku-2": "s3://bucket/artwork/sku-2.pdf",
}
cjd = to_cjd_envelope(sift_plan, source_refs)
# POST cjd to compile-pdf /v1/job/run
```

> **Note:** Gang, nest, and stagger explicit-placements mode require compile-pdf ≥1.1.0
> with the additive `explicit_placements` field on `ImposePlan` (cross-repo PR pending).

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SIFT_TIERS` | `grid,gang,nest` | Comma-separated list of enabled solver tiers |
| `SIFT_AUTH_MODE` | `none` | `none` or `api-key` |
| `SIFT_API_KEY` | _(unset)_ | Required when `SIFT_AUTH_MODE=api-key` |
| `SIFT_CACHE_BACKEND` | `memory` | `memory` or `redis` |
| `SIFT_REDIS_URL` | `redis://localhost:6379/0` | Redis URL when backend is `redis` |
| `SIFT_CACHE_TTL_S` | `3600` | Cache TTL in seconds (Redis backend) |
| `PORT` | `8000` | Uvicorn listen port |

---

## CLI reference

```bash
sift-pdf version          # Print package version
sift-pdf health           # JSON health info (codex version, tiers)
sift-pdf contract         # JSON contract surface (schema versions)
```
