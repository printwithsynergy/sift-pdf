# sift-pdf — agent notes

> **Cross-stack context**: see [`lint-pdf/STACK.md`](https://github.com/printwithsynergy/lint-pdf/blob/main/STACK.md) for the org-level stack overview — who-calls-whom, where shared things live (codex), cross-stack conventions (RFC 7807 + `/healthz`+`/readyz`+`/v1/contract` + service-skip + service-ownership tripwires).

## Scope

SiftPDF is the **stateless, deterministic imposition planning solver** in the Print With Synergy stack. It answers one question headlessly, API-first:

> *Given SKU/job rules + data and a press/substrate context, what is the most efficient step-and-repeat / gang / nest layout?*

It produces an **`ImposePlan`** — the logic behind the SNR — and hands it to **`compile-pdf.impose`** which writes the PDF. SiftPDF never writes a PDF.

### Solver tiers

| Tier | Mode | Engine | Description |
|---|---|---|---|
| T1 | `grid` | `codex.geom.tile_grid` | Uniform or stagger-cut step-and-repeat |
| T2 | `gang` | OR-Tools CP-SAT | Multi-SKU quantity balancing across press forms |
| T3 | `nest` | spyrrow/sparrow | True-shape irregular-die nesting |

`SIFT_TIERS` env var (default: `grid,gang,nest`) gates which tiers are enabled.

### Non-goals

- **Never write a PDF.** That is `compile-pdf`'s job.
- **Never reimplement codex geometry.** Rectangular grid → `codex.geom.tile_grid`. Placement vocabulary → `codex.geom.CellPlacement` + `flip_per_row` + `bleed_handling`. Polygon ops → `codex.geom.polygon_*`. The only new engine code is the gang ILP and true-shape nest.
- **Never own state.** No queue, no inventory, no due-date storage. Those live in MIS/synergy (`sift.pool`).

## Public contracts

- **HTTP API** (FastAPI): `/v1/sift/solve`, `/v1/sift/suggest`, `/v1/sift/estimate`
- **Contract endpoint**: `GET /v1/contract` — solver schema versions + codex section versions
- **CLI**: `sift-pdf version | health | contract`

## Cross-repo contracts

### codex-pdf (mandatory, in-process Python import)

Pinned via `pyproject.toml`: `codex-pdf>=1.21.1,<2.0`. The `<2.0` cap is **load-bearing** — codex major bumps rotate `/v1/contract` + cache-key VERSION scheme.

Consumed surfaces (cite at use site in source):
- `codex_pdf.geom.tile_grid`, `TileGrid`, `TileResult`, `CellPlacement` — T1 uniform grid
- `codex_pdf.geom.Box` — T1 stagger arithmetic
- `codex_pdf.geom.MarksZone` — marks-zone forwarding
- `codex_pdf.geom.GEOM_SCHEMA_VERSION` — cache key component
- `codex_pdf.errors.build_problem`, `problems`, `PROBLEM_CONTENT_TYPE` — RFC 7807

### compile-pdf (handoff target)

SiftPDF's output is handed to `compile-pdf.impose` for PDF generation.

**Grid fast-path** (`stagger_mode="none"`): translate `SiftImposePlan.grid_layout` to
compile-pdf's native `ImposePlan` dict (no pre-computed placements needed).

**Stagger / gang / nest path**: emits the additive `explicit_placements` list on
`ImposePlan`, consumed by **compile-pdf-impose ≥ 0.2.0** (impose schema 1.1.0).
The end-to-end handoff is unblocked — sift produces the plan and compile writes
the PDF. (The `ImposePlan` wire `schema_version` stays `"1.0.0"`; the new fields
are backward-compatible optional additions.)

**Stagger in compile-pdf**: compile-pdf-impose's `ImposePlan` now exposes a
first-class `stagger_mode` field, and `handoff.compile._explicit_plan` forwards
it, so the solver's stagger intent is preserved through the writer's lineage —
not just as pre-computed coordinates.

## Surface audits (mechanical, CI-enforced)

`scripts/consume_surface_audit.py` runs in CI and **bans**:
- Re-defining `Box`, `Point`, `Polygon`, `Path`, `CellPlacement`, `MarksZone`
- Direct `pyclipr` imports (use `codex_pdf.geom` polygon ops)

When a new codex symbol is consumed, add it to the allowlist in the same commit.

## Stagger cuts

Stagger (half-drop / brick) patterns offset alternating rows or columns:

- `half-drop-x`: odd rows shift right by `(cell_width + gutter_x) / 2`
- `half-drop-y`: odd columns shift up by `(cell_height + gutter_y) / 2`
- `custom`: user-specified `stagger_offset_pt`

codex's `tile_grid` produces uniform grids only; stagger positions are computed
via `codex_pdf.geom.Box` arithmetic in `solve/t1_grid.py` (new geometry, not
a reimplementation). Stagger layouts emit `explicit_placements` rather than
`grid_layout` for the compile-pdf handoff.

## Determinism + cache

Every solve is content-addressed:

```
cache_key = SHA-256(
  availability_sha256 | budget_ms | codex_pdf_version | geom_schema_version |
  jobs_sha256 | mode | objective_sha256 | press_sha256 | seed | sift_version
)
```

Same inputs → same plan. Stochastic solvers (T3 nest) pin `seed` + `budget_ms`
so the same request returns the cached plan.

## Local dev

```bash
uv sync --extra dev                                   # install
uv run ruff check src tests scripts                   # lint
uv run ruff format src tests scripts                  # format
uv run mypy src                                       # strict types
uv run python scripts/consume_surface_audit.py        # surface check
uv run pytest --cov=sift_pdf --cov-fail-under=70      # tests
uvicorn sift_pdf.api.main:app --reload --port 8100    # local server
```

CI gates: ruff + mypy + consume_surface_audit + pytest ≥70% + Spectral.

## Code review protocol

- Run code-review-graph impact on changed symbols before edits.
- Never disable crg-watch.
- Keep surface audit allowlist current.
