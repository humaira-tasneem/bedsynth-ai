"""Retired guest and AI Assistant routes stay unavailable without touching legacy data."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def retired_routes_client(monkeypatch):
    @asynccontextmanager
    async def isolated_lifespan(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", isolated_lifespan)
    with TestClient(app) as client:
        yield client


def test_guest_and_assistant_api_routes_are_not_active(retired_routes_client: TestClient) -> None:
    client = retired_routes_client
    assert client.post("/api/v1/guest/sessions").status_code == 404
    assert client.get("/api/v1/guest/session").status_code == 404
    assert client.post("/api/v1/guest/hospitals/1/generation-runs/preview", json={}).status_code == 404
    assert client.get("/api/v1/assistant/status").status_code == 404
    assert client.post("/api/v1/assistant/chat", json={}).status_code == 404
    assert client.post("/api/v1/assistant/validate-config", json={}).status_code == 404


def test_retired_routes_are_absent_from_openapi(retired_routes_client: TestClient) -> None:
    paths = retired_routes_client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/api/v1/guest/") for path in paths)
    assert not any(path.startswith("/api/v1/assistant/") for path in paths)
