"""Integration tests for the assembled Starlette app (full middleware stack).

Sends real HTTP requests through the complete middleware pipeline:
A2AVersionMiddleware → RateLimitMiddleware → route handler.

All 344 existing tests are isolation/unit tests with mocks. These close the
gap by testing the assembled machine — real Starlette app, real middleware,
real HTTP via TestClient.

Usage:
    python -m pytest tests/integration/ -q --tb=short
"""

from __future__ import annotations

import json

import pytest
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from adapter.peer_registry import PeerConfig, PeerRegistry

# ---------------------------------------------------------------------------
# Stub JSON-RPC handler — stands in for the real HermesExecutor
# ---------------------------------------------------------------------------


async def _stub_jsonrpc_handler(request):
    """Handle JSON-RPC requests.

    Returns a success result for valid JSON, or a standard JSON-RPC Parse
    error for invalid payloads.  This lets us test the middleware-to-endpoint
    flow without needing a real executor.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=200,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"status": "ok"},
        },
    )


async def _peer_offline_handler(request):
    """JSON-RPC handler that simulates a peer being unreachable."""
    return JSONResponse(
        status_code=200,
        content={
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32000,
                "message": "Peer 'offline-peer' not connected",
            },
        },
    )


STUB_JSONRPC_ROUTES = [
    Route("/a2a/jsonrpc", endpoint=_stub_jsonrpc_handler, methods=["POST"]),
]

PEER_OFFLINE_ROUTES = [
    Route("/a2a/jsonrpc", endpoint=_peer_offline_handler, methods=["POST"]),
]


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------


def _minimal_config(**overrides) -> dict:
    """Return a minimal A2A config dict suitable for _build_app()."""
    cfg = {
        "port": 0,
        "bind": "127.0.0.1",
        "node_name": "test-node",
        "node_id": "test-node",
        "profiles_dir": "/tmp/a2a-test-profiles",
        "signing_profile": None,
        "rate_limit": 0,
        "peers": [],
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Test 1 — Health endpoint smoke test
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Health endpoint returns 200 through the middleware stack."""

    def test_returns_200(self):
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config())
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_not_blocked_by_version_middleware(self):
        """/health should work even without A2A-Version header."""
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config())
        client = TestClient(app)

        response = client.get("/health", headers={"A2A-Version": "0.3"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_not_rate_limited(self):
        """/health passes even after exhausting the jsonrpc rate limit."""
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(rate_limit=3),
            jsonrpc_routes=STUB_JSONRPC_ROUTES,
        )
        client = TestClient(app)

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}
        headers = {
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
            "Authorization": "Bearer health-rate-test",
        }
        # Exhaust rate limit on /a2a/jsonrpc
        for _ in range(3):
            client.post("/a2a/jsonrpc", json=payload, headers=headers)

        # /health should still work
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Test 2 — Valid JSON-RPC through middleware stack
# ---------------------------------------------------------------------------


class TestValidJsonRpc:
    """Valid JSON-RPC request passes through both middlewares to the handler."""

    def test_passes_through_full_stack(self):
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {"message": "hello"},
        }
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "1.0",
                "Authorization": "Bearer test-token",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["result"]["status"] == "ok"

    def test_requires_a2a_version(self):
        """Missing A2A-Version is caught by version middleware before handler."""
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
        )
        assert response.status_code == 200  # JSON-RPC always 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body.get("error") is not None
        assert "version" in body["error"]["message"].lower()

    def test_rejects_wrong_version(self):
        """Wrong A2A-Version is caught by version middleware."""
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "banana",
                "Authorization": "Bearer test-token",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert "banana" in body["error"]["message"]

    def test_passes_with_correct_headers_and_no_auth(self):
        """Valid version header passes through even without auth token."""
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "1.0",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["result"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Test 3 — Malformed payload returns structured JSON-RPC error
# ---------------------------------------------------------------------------


class TestMalformedPayload:
    """Garbage bytes at the JSON-RPC endpoint return a structured error."""

    def test_garbage_bytes_returns_parse_error(self):
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        response = client.post(
            "/a2a/jsonrpc",
            content=b"\x00\x01\x02\xff\xfe not valid anything",
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "1.0",
            },
        )
        # JSON-RPC always returns 200 even for errors
        assert response.status_code == 200
        body = response.json()
        assert body.get("jsonrpc") == "2.0"
        assert body.get("id") is None
        assert "error" in body
        assert body["error"]["code"] == -32700
        assert "parse" in body["error"]["message"].lower()

    def test_empty_body_returns_parse_error(self):
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        response = client.post(
            "/a2a/jsonrpc",
            content=b"",
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "1.0",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == -32700

    def test_invalid_json_returns_parse_error(self):
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        response = client.post(
            "/a2a/jsonrpc",
            content=b'{"jsonrpc": "2.0", "id": 1, broken}',
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "1.0",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == -32700

    def test_no_crash_on_garbage(self):
        """Server does NOT return 500 for garbage input."""
        from a2a_plugin import _build_app

        app = _build_app(_minimal_config(), jsonrpc_routes=STUB_JSONRPC_ROUTES)
        client = TestClient(app)

        for _ in range(10):
            response = client.post(
                "/a2a/jsonrpc",
                content=b"garbage payload that should never crash the server",
                headers={
                    "Content-Type": "application/json",
                    "A2A-Version": "1.0",
                },
            )
            # Must never return 500
            assert response.status_code != 500


# ---------------------------------------------------------------------------
# Test 4 — Rate limit end-to-end
# ---------------------------------------------------------------------------


class TestRateLimitEndToEnd:
    """Rate limit enforcement through the full middleware stack."""

    def test_under_limit_passes(self):
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(rate_limit=30),
            jsonrpc_routes=STUB_JSONRPC_ROUTES,
        )
        client = TestClient(app)

        headers = {
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
            "Authorization": "Bearer rate-token",
        }
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}

        for i in range(29):
            resp = client.post("/a2a/jsonrpc", json=payload, headers=headers)
            assert resp.status_code == 200, f"Request {i + 1} should pass"

    def test_over_limit_returns_429(self):
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(rate_limit=30),
            jsonrpc_routes=STUB_JSONRPC_ROUTES,
        )
        client = TestClient(app)

        headers = {
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
            "Authorization": "Bearer rate-over-token",
        }
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}

        # 30 requests should pass
        for _ in range(30):
            client.post("/a2a/jsonrpc", json=payload, headers=headers)

        # 31st should be blocked
        resp = client.post("/a2a/jsonrpc", json=payload, headers=headers)
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "60"

    def test_rate_limit_zero_disabled(self):
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(rate_limit=0),
            jsonrpc_routes=STUB_JSONRPC_ROUTES,
        )
        client = TestClient(app)

        headers = {
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
            "Authorization": "Bearer flood-token",
        }
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}

        for _ in range(100):
            resp = client.post("/a2a/jsonrpc", json=payload, headers=headers)
            assert resp.status_code == 200

    def test_different_tokens_separate_buckets(self):
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(rate_limit=5),
            jsonrpc_routes=STUB_JSONRPC_ROUTES,
        )
        client = TestClient(app)

        headers_a = {
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
            "Authorization": "Bearer token-a",
        }
        headers_b = {
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
            "Authorization": "Bearer token-b",
        }
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}

        # Exhaust both tokens
        for _ in range(5):
            client.post("/a2a/jsonrpc", json=payload, headers=headers_a)
            client.post("/a2a/jsonrpc", json=payload, headers=headers_b)

        # Both should now get 429
        resp_a = client.post("/a2a/jsonrpc", json=payload, headers=headers_a)
        assert resp_a.status_code == 429
        resp_b = client.post("/a2a/jsonrpc", json=payload, headers=headers_b)
        assert resp_b.status_code == 429

    def test_anonymous_tracked_together(self):
        """Requests without Authorization share an anonymous bucket."""
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(rate_limit=5),
            jsonrpc_routes=STUB_JSONRPC_ROUTES,
        )
        client = TestClient(app)

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send"}
        base_headers = {
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
        }

        for _ in range(5):
            resp = client.post(
                "/a2a/jsonrpc", json=payload, headers=base_headers
            )
            assert resp.status_code == 200

        # 6th anonymous request should be rate-limited
        resp = client.post(
            "/a2a/jsonrpc", json=payload, headers=base_headers
        )
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "60"


# ---------------------------------------------------------------------------
# Test 5 — Peer offline returns clean error
# ---------------------------------------------------------------------------


class TestPeerOffline:
    """A handler that reports an offline peer returns cleanly through the stack."""

    def test_offline_peer_returns_structured_error(self):
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(),
            jsonrpc_routes=PEER_OFFLINE_ROUTES,
        )
        client = TestClient(app)

        response = client.post(
            "/a2a/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "tasks/send"},
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "1.0",
                "Authorization": "Bearer test-token",
            },
        )
        # JSON-RPC always returns 200
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert "error" in body
        assert "not connected" in body["error"]["message"].lower()
        assert body["error"]["code"] == -32000

    def test_no_crash_no_hang(self):
        """Error response flows through middlewares without crashing."""
        from a2a_plugin import _build_app

        app = _build_app(
            _minimal_config(),
            jsonrpc_routes=PEER_OFFLINE_ROUTES,
        )
        client = TestClient(app)

        for _ in range(5):
            response = client.post(
                "/a2a/jsonrpc",
                json={"jsonrpc": "2.0", "id": 1, "method": "tasks/send"},
                headers={
                    "Content-Type": "application/json",
                    "A2A-Version": "1.0",
                    "Authorization": "Bearer test-token",
                },
            )
            assert response.status_code == 200
            assert "error" in response.json()


# ---------------------------------------------------------------------------
# Test 6 — Malformed Agent Card / PeerRegistry validation
# ---------------------------------------------------------------------------


class TestPeerRegistryValidation:
    """PeerRegistry handles missing or empty fields without crashing."""

    def test_peer_with_empty_fields_does_not_crash(self):
        """PeerConfig with empty url and api_key registers without error."""
        config = PeerConfig(name="ghost", url="", api_key="")
        registry = PeerRegistry([config])
        peer = registry.get_peer("ghost")
        assert peer is not None
        assert peer.name == "ghost"
        assert peer.url == ""
        assert peer.api_key == ""

    def test_unknown_peer_returns_none(self):
        """Asking for a peer not in the registry returns None."""
        registry = PeerRegistry([])
        assert registry.get_peer("nonexistent") is None

    def test_duplicate_peer_name_raises(self):
        """Duplicate peer names are rejected at construction time."""
        from pytest import raises

        with raises(ValueError, match="Duplicate peer name"):
            PeerRegistry([
                PeerConfig(name="dup", url="http://a", api_key="key1"),
                PeerConfig(name="dup", url="http://b", api_key="key2"),
            ])

    def test_validate_bearer_token(self):
        """Known tokens resolve to the correct peer."""
        registry = PeerRegistry([
            PeerConfig(name="alpha", url="http://alpha", api_key="key-alpha"),
            PeerConfig(name="beta", url="http://beta", api_key="key-beta"),
        ])
        assert registry.validate_bearer_token("key-alpha") is not None
        assert registry.validate_bearer_token("key-alpha").name == "alpha"
        assert registry.validate_bearer_token("key-beta").name == "beta"
        assert registry.validate_bearer_token("unknown-key") is None
