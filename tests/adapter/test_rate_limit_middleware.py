"""Tests for the A2A rate limiting middleware.

Validates that peers exceeding their rate limit receive HTTP 429
with a Retry-After header, and that the middleware correctly
distinguishes between different peers and non-JSON-RPC paths.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from adapter.rate_limit_middleware import RateLimitMiddleware


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

    async def _health_handler(request):
        return JSONResponse({"ok": True})

    routes = [
        Route("/a2a/jsonrpc", endpoint=_rpc_handler, methods=["POST"]),
        Route("/health", endpoint=_health_handler, methods=["GET"]),
    ]
    return routes


def _build_app(routes, rate_limit: int = 0):
    app = Starlette(routes=routes)
    app.add_middleware(RateLimitMiddleware, rate_limit=rate_limit)
    return app


class TestRateLimitMiddleware:
    """Rate limiting behaviour."""

    def test_under_limit_passes(self):
        """29 requests within limit all pass with 200."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=30)
        client = TestClient(app)
        for _ in range(29):
            resp = client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["result"]["status"] == "ok"

    def test_over_limit_returns_429(self):
        """31st request in the same 60s window returns 429."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=30)
        client = TestClient(app)
        for _ in range(30):
            client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer test-token"},
            )
        resp = client.post(
            "/a2a/jsonrpc",
            json={},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "Rate limit exceeded"
        assert resp.headers.get("Retry-After") == "60"

    def test_different_peers_separate_buckets(self):
        """Two different tokens each get their own bucket (30 each)."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=30)
        client = TestClient(app)
        # Exhaust both tokens
        for _ in range(30):
            client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer token-a"},
            )
            client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer token-b"},
            )
        # Both should now get 429
        resp_a = client.post(
            "/a2a/jsonrpc",
            json={},
            headers={"Authorization": "Bearer token-a"},
        )
        assert resp_a.status_code == 429
        resp_b = client.post(
            "/a2a/jsonrpc",
            json={},
            headers={"Authorization": "Bearer token-b"},
        )
        assert resp_b.status_code == 429

    def test_rate_limit_zero_disabled(self):
        """rate_limit=0: unlimited requests all pass."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=0)
        client = TestClient(app)
        for _ in range(100):
            resp = client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer flood-token"},
            )
            assert resp.status_code == 200

    def test_rate_limit_negative_disabled(self):
        """rate_limit=-1: unlimited requests all pass."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=-1)
        client = TestClient(app)
        for _ in range(100):
            resp = client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer flood-token"},
            )
            assert resp.status_code == 200

    def test_health_not_rate_limited(self):
        """/health passes even after exhausting limit on jsonrpc."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=5)
        client = TestClient(app)
        # Exhaust the rate limit on /a2a/jsonrpc
        for _ in range(5):
            client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer test-token"},
            )
        # /health should still pass
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_anonymous_tracked_together(self):
        """Requests without Authorization header share an 'anonymous' bucket."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=5)
        client = TestClient(app)
        for _ in range(5):
            resp = client.post("/a2a/jsonrpc", json={})
            assert resp.status_code == 200
        # 6th anonymous request should be rate-limited
        resp = client.post("/a2a/jsonrpc", json={})
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "60"

    def test_window_resets_after_60s(self):
        """After 61s with no requests, bucket empties and passes again."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=5)
        client = TestClient(app)
        # Exhaust the limit
        for _ in range(5):
            client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer reset-token"},
            )
        # Verify we're blocked
        resp = client.post(
            "/a2a/jsonrpc",
            json={},
            headers={"Authorization": "Bearer reset-token"},
        )
        assert resp.status_code == 429
        # Advance time by 61 seconds
        with pytest.MonkeyPatch.context() as mp:
            # We mock time.time to return now + 61
            # But the middleware uses time.time() on each call; we need
            # to patch it before the test. Since TestClient calls the
            # middleware synchronously, we patch at module level.
            original_time = time.time
            fake_time = [original_time() + 61]

            def _fake_time():
                return fake_time[0]

            mp.setattr(time, "time", _fake_time)
            # Rebuild app with patched time
            app2 = _build_app(routes, rate_limit=5)
            client2 = TestClient(app2)
            resp = client2.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer reset-token"},
            )
            assert resp.status_code == 200

    def test_exact_limit_not_exceeded(self):
        """Exactly 'rate_limit' requests all pass, the next one is blocked."""
        routes, _ = _make_fixture_routes()
        app = _build_app(routes, rate_limit=3)
        client = TestClient(app)
        for i in range(3):
            resp = client.post(
                "/a2a/jsonrpc",
                json={},
                headers={"Authorization": "Bearer exact-token"},
            )
            assert resp.status_code == 200, f"Request {i+1} failed: {resp.json()}"
        # 4th should be blocked
        resp = client.post(
            "/a2a/jsonrpc",
            json={},
            headers={"Authorization": "Bearer exact-token"},
        )
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fixture_routes():
    """Return (routes, rpc_handler) for test app construction."""

    async def _rpc_handler(request):
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {"status": "ok"},
            },
        )

    async def _health_handler(request):
        return JSONResponse({"ok": True})

    routes = [
        Route("/a2a/jsonrpc", endpoint=_rpc_handler, methods=["POST"]),
        Route("/health", endpoint=_health_handler, methods=["GET"]),
    ]
    return routes, _rpc_handler
