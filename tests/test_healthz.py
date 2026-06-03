"""Tests for /healthz, /readyz, /v1/contract endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sift_pdf.api.main import app

client = TestClient(app, raise_server_exceptions=True)


def test_healthz_root() -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "instance_id" in body
    assert "cache_backend" in body


def test_healthz_v1() -> None:
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz() -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_readyz_v1() -> None:
    r = client.get("/v1/readyz")
    assert r.status_code == 200


def test_contract() -> None:
    r = client.get("/v1/contract")
    assert r.status_code == 200
    body = r.json()
    assert body["contract_name"] == "sift-pdf"
    assert "package_version" in body
    assert "solver_schema_versions" in body
    assert "endpoints" in body


def test_request_id_header_stamped() -> None:
    r = client.get("/healthz")
    assert "x-sift-request-id" in r.headers
    assert "x-sift-instance-id" in r.headers


def test_request_id_forwarded() -> None:
    r = client.get("/healthz", headers={"X-Sift-Request-Id": "test-abc"})
    assert r.headers["x-sift-request-id"] == "test-abc"
