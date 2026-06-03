# sift-pdf

Stateless, deterministic imposition planning solver for the Print With Synergy stack.

Given SKU/job rules + press context, produces the most efficient **step-and-repeat / stagger / gang / nest layout** — the logic behind the SNR. Hands an `ImposePlan` to `compile-pdf.impose` for PDF generation; never writes bytes itself.

## Solver tiers

| Mode | Tier | Engine | Layouts |
|---|---|---|---|
| `grid` | T1 | codex tile_grid | Uniform + stagger cuts (half-drop-x, half-drop-y, custom offset) |
| `gang` | T2 | OR-Tools CP-SAT | Multi-SKU quantity balancing |
| `nest` | T3 | spyrrow/sparrow | True-shape irregular-die nesting |

## API

```
POST /v1/sift/solve      → SiftImposePlan
POST /v1/sift/suggest    → SiftImposePlan (substrate sweep)
POST /v1/sift/estimate   → EstimateManifest
GET  /v1/contract
GET  /healthz  /readyz
```

## Quick start

```bash
pip install "sift-pdf[gang]"
uvicorn sift_pdf.api.main:app --port 8100
```

```bash
curl -X POST http://localhost:8100/v1/sift/solve \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [{"id":"sku-1","die":{"type":"rect","width_pt":288,"height_pt":144},"quantity":1000}],
    "press_profile": {"id":"p1","web_width_pt":864,"repeat_model":{"type":"servo","min_repeat_pt":144,"max_repeat_pt":864}},
    "mode": "grid"
  }'
```

## Stagger cuts

```bash
curl -X POST http://localhost:8100/v1/sift/solve \
  -d '{ ..., "stagger_mode": "half-drop-x" }'
```

Supported: `half-drop-x`, `half-drop-y`, `custom` (with `stagger_offset_pt`).

## Development

```bash
uv sync --extra dev
uv run pytest --cov=sift_pdf --cov-fail-under=70
```

## License

AGPL-3.0-or-later. See LICENSE and NOTICE for dependency licenses.
