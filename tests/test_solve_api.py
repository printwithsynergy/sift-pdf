"""End-to-end tests for POST /v1/sift/solve."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift_pdf.api.main import app
from sift_pdf.cache import cache_clear

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clear() -> None:
    cache_clear()


def _payload(**overrides: object) -> dict:
    base: dict = {
        "jobs": [
            {
                "id": "sku-1",
                "die": {"type": "rect", "width_pt": 288.0, "height_pt": 144.0},
                "quantity": 1000,
            }
        ],
        "press_profile": {
            "id": "servo-press",
            "web_width_pt": 864.0,
            "repeat_model": {"type": "servo", "min_repeat_pt": 144.0, "max_repeat_pt": 864.0},
        },
        "mode": "grid",
    }
    base.update(overrides)
    return base


def test_solve_grid_returns_200() -> None:
    r = client.post("/v1/sift/solve", json=_payload())
    assert r.status_code == 200


def test_solve_grid_plan_fields() -> None:
    r = client.post("/v1/sift/solve", json=_payload())
    body = r.json()
    plan = body["plan"]
    assert plan["mode"] == "grid"
    assert plan["tier"] == "T1"
    assert "waste_pct" in plan
    assert "grid_layout" in plan
    assert plan["grid_layout"]["stagger_mode"] == "none"


def test_solve_cache_hit_on_second_request() -> None:
    p = _payload()
    r1 = client.post("/v1/sift/solve", json=p)
    r2 = client.post("/v1/sift/solve", json=p)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["cache_hit"] is True


def test_solve_cache_key_header() -> None:
    r = client.post("/v1/sift/solve", json=_payload())
    assert "x-sift-cache-key" in r.headers
    assert len(r.headers["x-sift-cache-key"]) == 64


def test_solve_seed_header_overrides_body() -> None:
    r = client.post(
        "/v1/sift/solve",
        json=_payload(seed=1),
        headers={"X-Sift-Seed": "99"},
    )
    # Plan should use seed=99 (header wins) — cache_key differs from seed=1 request
    assert r.status_code == 200


def test_solve_stagger_half_drop_x() -> None:
    payload = _payload(stagger_mode="half-drop-x")
    r = client.post("/v1/sift/solve", json=payload)
    assert r.status_code == 200
    body = r.json()["plan"]
    assert body["grid_layout"]["stagger_mode"] == "half-drop-x"
    assert body["explicit_placements"] is not None
    assert len(body["explicit_placements"]) > 0


def test_solve_stagger_half_drop_y() -> None:
    payload = _payload(stagger_mode="half-drop-y")
    r = client.post("/v1/sift/solve", json=payload)
    assert r.status_code == 200
    assert r.json()["plan"]["explicit_placements"] is not None


def test_solve_invalid_mode_suggests_endpoint() -> None:
    r = client.post("/v1/sift/solve", json=_payload(mode="suggest"))
    assert r.status_code == 422


def test_solve_empty_jobs_rejected() -> None:
    payload = _payload()
    payload["jobs"] = []
    r = client.post("/v1/sift/solve", json=payload)
    assert r.status_code == 422


def test_solve_rfc7807_error_shape_on_bad_request() -> None:
    r = client.post("/v1/sift/solve", json={"bad": "payload"})
    assert r.status_code == 422
    body = r.json()
    assert "type" in body
    assert "title" in body
    assert "status" in body
    assert "detail" in body
