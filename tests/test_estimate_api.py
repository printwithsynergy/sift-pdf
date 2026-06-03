"""Tests for POST /v1/sift/estimate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift_pdf.api.main import app

client = TestClient(app, raise_server_exceptions=True)

_PT2_TO_M2 = (1 / 72 * 0.0254) ** 2


def _grid_payload(**overrides: object) -> dict:
    base: dict = {
        "plan": {
            "schema_version": "1.0.0",
            "mode": "grid",
            "tier": "T1",
            "seed": 42,
            "budget_ms": 5000,
            "cache_key": "a" * 64,
            "sift_version": "0.1.0",
            "codex_geom_schema_version": "1.1.0",
            "substrate": {"web_width_pt": 864.0, "repeat_pt": 432.0},
            "sheet": {"width_pt": 864.0, "height_pt": 432.0},
            "cell": {"width_pt": 288.0, "height_pt": 144.0},
            "grid_layout": {"rows": 3, "cols": 3, "stagger_mode": "none"},
            "bleed_pt": 0.0,
            "bleed_handling": "none",
            "waste_pct": 10.0,
            "material_area_pt2": 864.0 * 432.0,
            "plate_count": 4,
        }
    }
    if overrides:
        base["plan"].update(overrides)
    return base


def _explicit_payload() -> dict:
    return {
        "plan": {
            "schema_version": "1.0.0",
            "mode": "nest",
            "tier": "T3",
            "seed": 7,
            "budget_ms": 3000,
            "cache_key": "b" * 64,
            "sift_version": "0.1.0",
            "codex_geom_schema_version": "1.1.0",
            "substrate": {"sheet_width_pt": 612.0, "sheet_height_pt": 792.0},
            "sheet": {"width_pt": 612.0, "height_pt": 792.0},
            "cell": {"width_pt": 144.0, "height_pt": 144.0},
            "explicit_placements": [
                {"source_ref": "sku-1", "x0_pt": 0.0, "y0_pt": 0.0, "x1_pt": 144.0, "y1_pt": 144.0},
                {
                    "source_ref": "sku-2",
                    "x0_pt": 150.0,
                    "y0_pt": 0.0,
                    "x1_pt": 294.0,
                    "y1_pt": 144.0,
                },
                {
                    "source_ref": "sku-1",
                    "x0_pt": 0.0,
                    "y0_pt": 150.0,
                    "x1_pt": 144.0,
                    "y1_pt": 294.0,
                },
            ],
            "bleed_pt": 0.0,
            "bleed_handling": "none",
            "waste_pct": 30.0,
            "material_area_pt2": 612.0 * 792.0,
            "plate_count": 2,
        }
    }


def test_estimate_returns_200() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    assert r.status_code == 200


def test_estimate_schema_version() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    assert r.json()["schema_version"] == "1.0.0"


def test_estimate_grid_cells_total() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    # rows=3, cols=3 → 9 cells
    assert r.json()["cells_total"] == 9


def test_estimate_explicit_placements_cells_total() -> None:
    r = client.post("/v1/sift/estimate", json=_explicit_payload())
    # 3 explicit placements
    assert r.json()["cells_total"] == 3


def test_estimate_plate_count() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    assert r.json()["plate_count"] == 4


def test_estimate_waste_pct() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    assert r.json()["waste_pct"] == pytest.approx(10.0)


def test_estimate_material_area_m2_conversion() -> None:
    area_pt2 = 864.0 * 432.0
    expected_m2 = round(area_pt2 * _PT2_TO_M2, 6)
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    assert r.json()["est_material_area_m2"] == pytest.approx(expected_m2, rel=1e-5)


def test_estimate_sheet_dims() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    body = r.json()
    assert body["sheet_width_pt"] == 864.0
    assert body["sheet_height_pt"] == 432.0


def test_estimate_cell_dims() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    body = r.json()
    assert body["cell_width_pt"] == 288.0
    assert body["cell_height_pt"] == 144.0


def test_estimate_plan_cache_key() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    assert r.json()["plan_cache_key"] == "a" * 64


def test_estimate_optional_cost_none_when_absent() -> None:
    r = client.post("/v1/sift/estimate", json=_grid_payload())
    assert r.json()["est_cost"] is None


def test_estimate_optional_cost_passed_through() -> None:
    payload = _grid_payload()
    payload["plan"]["est_cost"] = 42.5
    r = client.post("/v1/sift/estimate", json=payload)
    assert r.json()["est_cost"] == pytest.approx(42.5)


def test_estimate_run_time_passed_through() -> None:
    payload = _grid_payload()
    payload["plan"]["est_run_time_sec"] = 120.0
    r = client.post("/v1/sift/estimate", json=payload)
    assert r.json()["est_run_time_sec"] == pytest.approx(120.0)


def test_estimate_missing_plan_returns_422() -> None:
    r = client.post("/v1/sift/estimate", json={})
    assert r.status_code == 422


def test_estimate_invalid_plan_returns_422() -> None:
    r = client.post("/v1/sift/estimate", json={"plan": {"mode": "grid"}})
    assert r.status_code == 422
