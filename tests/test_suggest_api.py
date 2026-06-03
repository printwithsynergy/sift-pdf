"""Tests for POST /v1/sift/suggest — substrate catalog sweep."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift_pdf.api.main import app
from sift_pdf.cache import cache_clear

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clear() -> None:
    cache_clear()


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def _servo_press(web_width_pt: float = 864.0) -> dict:
    return {
        "id": "servo-press",
        "web_width_pt": web_width_pt,
        "repeat_model": {"type": "servo", "min_repeat_pt": 144.0, "max_repeat_pt": 864.0},
    }


def _sheet_press(sheet_width_pt: float = 612.0, sheet_height_pt: float = 792.0) -> dict:
    return {
        "id": "sheet-press",
        "repeat_model": {
            "type": "offset-sheet",
            "sheet_width_pt": sheet_width_pt,
            "sheet_height_pt": sheet_height_pt,
        },
    }


def _rect_job(width_pt: float = 144.0, height_pt: float = 144.0) -> dict:
    return {
        "id": "sku-1",
        "die": {"type": "rect", "width_pt": width_pt, "height_pt": height_pt},
        "quantity": 500,
    }


def _suggest_payload(
    *,
    press: dict | None = None,
    catalog: list[dict] | None = None,
    jobs: list[dict] | None = None,
    **extras: object,
) -> dict:
    return {
        "jobs": jobs if jobs is not None else [_rect_job()],
        "substrate_catalog": catalog
        if catalog is not None
        else [
            {"id": "narrow", "web_width_pt": 432.0},
            {"id": "wide", "web_width_pt": 864.0},
        ],
        "press_profile": press if press is not None else _servo_press(),
        **extras,
    }


# ---------------------------------------------------------------------------
# Basic response shape
# ---------------------------------------------------------------------------


def test_suggest_returns_200() -> None:
    r = client.post("/v1/sift/suggest", json=_suggest_payload())
    assert r.status_code == 200


def test_suggest_response_has_plan_and_substrate_id() -> None:
    r = client.post("/v1/sift/suggest", json=_suggest_payload())
    body = r.json()
    assert "plan" in body
    assert "substrate_id" in body
    assert "candidates_evaluated" in body


def test_suggest_plan_is_valid_impose_plan() -> None:
    r = client.post("/v1/sift/suggest", json=_suggest_payload())
    plan = r.json()["plan"]
    assert plan["mode"] == "grid"
    assert plan["tier"] == "T1"
    assert "waste_pct" in plan
    assert "cache_key" in plan


def test_suggest_candidates_evaluated_counts_feasible() -> None:
    r = client.post(
        "/v1/sift/suggest",
        json=_suggest_payload(
            catalog=[
                {"id": "a", "web_width_pt": 432.0},
                {"id": "b", "web_width_pt": 576.0},
                {"id": "c", "web_width_pt": 864.0},
            ]
        ),
    )
    assert r.json()["candidates_evaluated"] == 3


# ---------------------------------------------------------------------------
# Best substrate selection
# ---------------------------------------------------------------------------


def test_suggest_selects_lowest_waste_substrate() -> None:
    # Wider web fits more cells → lower waste; solver should pick "wide"
    r = client.post(
        "/v1/sift/suggest",
        json=_suggest_payload(
            press=_servo_press(web_width_pt=864.0),
            catalog=[
                {"id": "narrow", "web_width_pt": 216.0},
                {"id": "wide", "web_width_pt": 864.0},
            ],
            jobs=[_rect_job(width_pt=144.0, height_pt=144.0)],
        ),
    )
    body = r.json()
    assert body["substrate_id"] == "wide"


def test_suggest_substrate_id_matches_best_plan() -> None:
    r = client.post("/v1/sift/suggest", json=_suggest_payload())
    body = r.json()
    assert body["substrate_id"] in {"narrow", "wide"}


# ---------------------------------------------------------------------------
# Web-width override
# ---------------------------------------------------------------------------


def test_suggest_web_width_override_applied() -> None:
    # A single narrow catalog entry; plan sheet width must match 288 pt
    r = client.post(
        "/v1/sift/suggest",
        json=_suggest_payload(
            press=_servo_press(web_width_pt=864.0),
            catalog=[{"id": "narrow", "web_width_pt": 288.0}],
            jobs=[_rect_job(width_pt=144.0, height_pt=144.0)],
        ),
    )
    assert r.status_code == 200
    assert r.json()["plan"]["sheet"]["width_pt"] == pytest.approx(288.0)


# ---------------------------------------------------------------------------
# Sheet press substrate override
# ---------------------------------------------------------------------------


def test_suggest_sheet_press_single_candidate() -> None:
    r = client.post(
        "/v1/sift/suggest",
        json={
            "jobs": [_rect_job(width_pt=144.0, height_pt=144.0)],
            "substrate_catalog": [
                {"id": "letter", "sheet_width_pt": 612.0, "sheet_height_pt": 792.0}
            ],
            "press_profile": _sheet_press(),
        },
    )
    assert r.status_code == 200
    assert r.json()["substrate_id"] == "letter"


def test_suggest_sheet_selects_best_fit_substrate() -> None:
    # small (288×288): 2×2 = 4 cells of 144×144 → 0% waste (perfect fit)
    # large (612×792): 4×5 = 20 cells → ~14% waste
    # solver selects small because waste is lower
    r = client.post(
        "/v1/sift/suggest",
        json={
            "jobs": [_rect_job(width_pt=144.0, height_pt=144.0)],
            "substrate_catalog": [
                {"id": "small", "sheet_width_pt": 288.0, "sheet_height_pt": 288.0},
                {"id": "large", "sheet_width_pt": 612.0, "sheet_height_pt": 792.0},
            ],
            "press_profile": _sheet_press(),
        },
    )
    assert r.status_code == 200
    assert r.json()["substrate_id"] == "small"


# ---------------------------------------------------------------------------
# Infeasible candidates are skipped
# ---------------------------------------------------------------------------


def test_suggest_skips_infeasible_and_returns_feasible() -> None:
    # Die is 200 pt wide — won't fit on 100 pt web but fits on 864 pt
    r = client.post(
        "/v1/sift/suggest",
        json=_suggest_payload(
            press=_servo_press(),
            catalog=[
                {"id": "too-narrow", "web_width_pt": 100.0},
                {"id": "ok", "web_width_pt": 864.0},
            ],
            jobs=[_rect_job(width_pt=200.0, height_pt=100.0)],
        ),
    )
    assert r.status_code == 200
    assert r.json()["substrate_id"] == "ok"
    assert r.json()["candidates_evaluated"] == 1


def test_suggest_returns_400_when_all_infeasible() -> None:
    # Die is wider than all catalog entries
    r = client.post(
        "/v1/sift/suggest",
        json=_suggest_payload(
            press=_servo_press(),
            catalog=[
                {"id": "a", "web_width_pt": 50.0},
                {"id": "b", "web_width_pt": 60.0},
            ],
            jobs=[_rect_job(width_pt=200.0, height_pt=200.0)],
        ),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_suggest_missing_jobs_returns_422() -> None:
    payload = _suggest_payload()
    del payload["jobs"]
    r = client.post("/v1/sift/suggest", json=payload)
    assert r.status_code == 422


def test_suggest_empty_catalog_returns_422() -> None:
    r = client.post("/v1/sift/suggest", json=_suggest_payload(catalog=[]))
    assert r.status_code == 422


def test_suggest_empty_jobs_returns_422() -> None:
    r = client.post("/v1/sift/suggest", json=_suggest_payload(jobs=[]))
    assert r.status_code == 422


def test_suggest_missing_press_returns_422() -> None:
    payload = _suggest_payload()
    del payload["press_profile"]
    r = client.post("/v1/sift/suggest", json=payload)
    assert r.status_code == 422
