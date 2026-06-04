# Architecture

sift-pdf is a stateless FastAPI sidecar that answers one question: *given SKU/job rules
and a press context, what is the most efficient step-and-repeat, gang, or nest layout?*
It produces a `SiftImposePlan` and hands it to `compile-pdf.impose` for PDF generation;
it never writes a PDF itself.

## Position in the stack

```
  MIS / synergy
       │  job specs, substrate catalog, quantities
       ▼
  sift-pdf  ◀─────────────────────────────────────────────────────────────────────┐
  POST /v1/sift/solve                                                              │
  POST /v1/sift/suggest      (substrate sweep — returns lowest-waste layout)      │
  POST /v1/sift/estimate     (cheap metrics from an existing plan, no re-solve)   │
       │  SiftImposePlan (JSON)                                                    │
       ▼                                                                           │
  compile-pdf                                                         cache-hit path
  POST /v1/compile/impose                                                          │
       │  PDF bytes                                                                │
       ▼                                                                           │
  caller                         ◀─── content-addressed LRU / Redis cache ────────┘
```

The solver is purely functional: the same inputs always produce the same plan.
Stochastic tiers (T3 nest) pin `seed` and `budget_ms` in the cache key so the same
request returns the cached plan without re-running the solver.

## Solver tiers

Three solver tiers are implemented, gated at runtime by the `SIFT_TIERS` environment
variable:

```
T1  grid    codex_pdf.geom.tile_grid      Uniform or stagger-cut step-and-repeat
T2  gang    OR-Tools CP-SAT               Multi-SKU quantity balancing across forms
T3  nest    spyrrow / sparrow             True-shape irregular-die nesting
```

Requests for a tier not listed in `SIFT_TIERS` receive an RFC 7807 `501 Not Implemented`
response so the caller can degrade gracefully or route to a different instance.

### T1 — uniform grid

T1 delegates layout arithmetic to `codex_pdf.geom.tile_grid`. The repeat length is
snapped to the nearest feasible value for the press type before the grid solve:

- **Geared press**: nearest integer multiple of tooth-count × circular-pitch that fits
  within the web width.
- **Servo press**: clamped to the continuous `[min_repeat_pt, max_repeat_pt]` range with
  no discrete snap.
- **Digital web**: frame length = maximum that fits all jobs in a single pass.
- **Digital sheet / offset sheet**: fixed substrate dimensions; no repeat snapping needed.

### T1 — stagger cuts

`codex_pdf.geom.tile_grid` produces uniform grids only; stagger (half-drop / brick)
patterns are a common prepress requirement that the codex primitive does not cover.
T1 computes stagger positions using `codex_pdf.geom.Box` arithmetic in
`src/sift_pdf/solve/t1_grid.py`:

- `half-drop-x`: odd rows shift right by `(cell_width + gutter_x) / 2`.
- `half-drop-y`: odd columns shift up by `(cell_height + gutter_y) / 2`.
- `custom`: caller-specified `stagger_offset_pt`.

Stagger layouts emit `explicit_placements` rather than `grid_layout` because the
pre-computed positions must be forwarded to compile-pdf's impose engine unchanged.
This requires compile-pdf ≥ 1.1.0 (cross-repo PR pending).

### T2 — gang

T2 models multi-SKU gang imposition as a CP-SAT integer program using OR-Tools.
Decision variables are the up-count and lane assignment per SKU. The solver minimises
a weighted objective (waste, plate count, overrun, changeover) within the caller-supplied
time budget (`X-Sift-Budget-Ms` header or `budget_ms` body field).

### T3 — nest

T3 delegates irregular-die nesting to spyrrow (a Rust-backed sparrow strip-packing
engine). The call pins `seed` and `budget_ms` so that the same request is deterministic;
the spyrrow wheel version is included in the cache key so an engine upgrade automatically
invalidates old entries.

## Request lifecycle

```
POST /v1/sift/solve
       │
       ├─ validate request body (Pydantic)
       │
       ├─ apply header overrides (X-Sift-Seed, X-Sift-Budget-Ms)
       │
       ├─ compute SHA-256 cache key
       │   mode | seed | budget_ms | sift_version | geom_schema_version |
       │   codex_pdf_version | jobs_sha256 | press_sha256 | avail_sha256
       │
       ├─ cache hit? ──yes──▶ return cached SiftImposePlan (cache_hit=true)
       │
       ├─ dispatch to solver (T1 / T2 / T3)
       │
       ├─ write plan to cache
       │
       └─ return SiftImposePlan
            X-Sift-Cache-Key: <64-char hex>
            X-Sift-Request-Id: <ulid>
```

## Schema design

sift-pdf defines its own `SiftImposePlan` schema (in `src/sift_pdf/schemas/impose_plan.py`)
which is distinct from compile-pdf's `ImposePlan`. The sift schema is richer — it carries
solver metadata, substrate choice, metrics, marks intent, and per-SKU placement maps.
The handoff layer (`src/sift_pdf/handoff/compile.py`) translates a `SiftImposePlan` into
compile-pdf's wire format.

Two layout representations are supported:

- **`grid_layout`**: carries rows, cols, gutter, rotation, stagger mode, and stagger offset.
  compile-pdf's grid engine interprets this directly (fast path).
- **`explicit_placements`**: a flat list of pre-computed `(x0, y0, x1, y1, rotation, flip_h,
  flip_v, source_ref)` tuples. Used by stagger, gang, and nest output. Requires
  compile-pdf ≥ 1.1.0.

## Codex surface consumed

sift-pdf is not permitted to reimplement codex geometry primitives (enforced by
`scripts/consume_surface_audit.py` in CI). The codex symbols it consumes are:

| Symbol | Purpose |
|---|---|
| `codex_pdf.geom.tile_grid` | T1 uniform grid layout |
| `codex_pdf.geom.TileGrid` | Grid parameter model |
| `codex_pdf.geom.TileResult` | Grid solve output |
| `codex_pdf.geom.CellPlacement` | Placement vocabulary |
| `codex_pdf.geom.Box` | T1 stagger offset arithmetic |
| `codex_pdf.geom.MarksZone` | Marks-zone forwarding |
| `codex_pdf.geom.GEOM_SCHEMA_VERSION` | Cache key component |
| `codex_pdf.errors.build_problem` | RFC 7807 error shaping |
| `codex_pdf.errors.PROBLEM_CONTENT_TYPE` | RFC 7807 content type |

Polygon ops (`polygon_intersect`, `polygon_union`, `polygon_offset`) are available via
`codex_pdf.geom` when the `[geom]` extra is installed; direct `pyclipr` imports are banned.

## CJD handoff

`src/sift_pdf/handoff/compile.py` exposes two functions:

- `to_compile_impose_plan(plan)` — translates `SiftImposePlan` to compile-pdf's
  `ImposePlan` dict for the grid fast path or the explicit-placements path.
- `to_cjd_envelope(plan, source_refs)` — builds a compile-pdf Compile Job Description
  envelope that chains `compose → marks → impose` in canonical order. The `marks` step
  is only included when at least one flag in `marks_intent` is set.

## Error contract

All error responses conform to RFC 7807 Problem Details (`application/problem+json`)
with `type`, `title`, `status`, `detail`, and `instance` fields, using
`codex_pdf.errors.build_problem` as the canonical constructor. This matches compile-pdf,
codex-pdf, and the rest of the Print With Synergy stack.

## Observability

- `GET /metrics` — Prometheus exposition (counter + histogram per endpoint).
- `X-Sift-Request-Id` header (ULID) on every response for log correlation.
- structlog structured logging throughout.
- `INSTANCE_ID` (UUID, set at startup) distinguishes replicas in shared log streams.
