"""Tests for API key authentication (SIFT_AUTH_MODE=api-key)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift_pdf.api.main import app

client = TestClient(app, raise_server_exceptions=False)

_SOLVE_URL = "/v1/sift/solve"
_SOLVE_PAYLOAD = {
    "jobs": [
        {
            "id": "sku-1",
            "die": {"type": "rect", "width_pt": 144.0, "height_pt": 144.0},
            "quantity": 10,
        }
    ],
    "press_profile": {
        "id": "servo",
        "web_width_pt": 864.0,
        "repeat_model": {"type": "servo", "min_repeat_pt": 144.0, "max_repeat_pt": 864.0},
    },
    "mode": "grid",
}


def test_auth_none_mode_passes_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_AUTH_MODE", "none")
    r = client.post(_SOLVE_URL, json=_SOLVE_PAYLOAD)
    assert r.status_code == 200


def test_auth_api_key_correct_key_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_AUTH_MODE", "api-key")
    monkeypatch.setenv("SIFT_API_KEY", "test-secret")
    r = client.post(_SOLVE_URL, json=_SOLVE_PAYLOAD, headers={"X-Sift-Key": "test-secret"})
    assert r.status_code == 200


def test_auth_api_key_wrong_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_AUTH_MODE", "api-key")
    monkeypatch.setenv("SIFT_API_KEY", "test-secret")
    r = client.post(_SOLVE_URL, json=_SOLVE_PAYLOAD, headers={"X-Sift-Key": "wrong-key"})
    assert r.status_code == 401


def test_auth_api_key_missing_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_AUTH_MODE", "api-key")
    monkeypatch.setenv("SIFT_API_KEY", "test-secret")
    r = client.post(_SOLVE_URL, json=_SOLVE_PAYLOAD)
    assert r.status_code == 401


def test_auth_api_key_not_configured_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_AUTH_MODE", "api-key")
    monkeypatch.delenv("SIFT_API_KEY", raising=False)
    r = client.post(_SOLVE_URL, json=_SOLVE_PAYLOAD, headers={"X-Sift-Key": "any"})
    assert r.status_code == 500


def test_auth_healthz_never_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_AUTH_MODE", "api-key")
    monkeypatch.setenv("SIFT_API_KEY", "test-secret")
    r = client.get("/v1/healthz")
    assert r.status_code == 200
