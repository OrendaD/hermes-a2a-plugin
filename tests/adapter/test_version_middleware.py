"""Tests for the A2A version negotiation middleware.

Validates that requests with missing or unsupported A2A-Version headers
are rejected with the correct JSON-RPC error format.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from adapter.version_middleware import A2AVersionMiddleware, VERSION_NOT_SUPPORTED_CODE


@pytest.fixture
def app():
    """A minimal Starlette app with one JSON-RPC route and the middleware."""
    async def _rpc_handler(request):
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {"status": "ok"},
            },
        )

    routes = [
        Route("/a2a/jsonrpc", endpoint=_rpc_handler, methods=["POST"]),
        Route("/health", endpoint=lambda r: JSONResponse({"ok": True}), methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(A2AVersionMiddleware)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestA2AVersionMiddleware:
    def test_accepts_v1_0(self, client):
        """Requests with A2A-Version: 1.0 pass through."""
        resp = client.post("/a2a/jsonrpc", json={}, headers={"A2A-Version": "1.0"})
        assert resp.status_code == 200
        body = resp.json()
        assert "result" in body
        assert body["result"]["status"] == "ok"

    def test_accepts_v1_0_with_variant(self, client):
        """Requests with A2A-Version: 1.0-something still match (startswith)."""
        resp = client.post("/a2a/jsonrpc", json={}, headers={"A2A-Version": "1.0-draft"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["status"] == "ok"

    def test_rejects_missing_header(self, client):
        """Requests without A2A-Version header are rejected."""
        resp = client.post("/a2a/jsonrpc", json={})
        assert resp.status_code == 200  # JSON-RPC always returns 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] is None
        assert body["error"]["code"] == VERSION_NOT_SUPPORTED_CODE
        assert "missing" in body["error"]["message"]

    def test_rejects_v0_3(self, client):
        """Requests with A2A-Version: 0.3 are rejected."""
        resp = client.post("/a2a/jsonrpc", json={}, headers={"A2A-Version": "0.3"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] is None
        assert body["error"]["code"] == VERSION_NOT_SUPPORTED_CODE
        assert "0.3" in body["error"]["message"]

    def test_rejects_v2_0(self, client):
        """Requests with A2A-Version: 2.0 are rejected."""
        resp = client.post("/a2a/jsonrpc", json={}, headers={"A2A-Version": "2.0"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == VERSION_NOT_SUPPORTED_CODE
        assert "2.0" in body["error"]["message"]

    def test_health_endpoint_not_blocked(self, client):
        """Non-JSON-RPC endpoints are not blocked by the middleware."""
        resp = client.get("/health", headers={"A2A-Version": "0.3"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_rejects_bogus_header(self, client):
        """Requests with garbage A2A-Version values are rejected."""
        resp = client.post(
            "/a2a/jsonrpc",
            json={},
            headers={"A2A-Version": "banana"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == VERSION_NOT_SUPPORTED_CODE
        assert "banana" in body["error"]["message"]
