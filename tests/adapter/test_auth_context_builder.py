"""Tests for BearerTokenContextBuilder.

Covers:
- Valid token → authenticated user with correct peer name
- Invalid token → UnauthenticatedUser
- Missing auth header → UnauthenticatedUser
- Empty Bearer token → UnauthenticatedUser
- Peer registry empty → all requests unauthenticated
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from a2a.auth.user import UnauthenticatedUser

from adapter.auth_context_builder import BearerTokenContextBuilder
from adapter.peer_registry import PeerConfig, PeerRegistry


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_request(auth_header: str | None = None) -> MagicMock:
    """Build a lightweight Starlette Request mock with an optional Authorization header."""
    request = MagicMock()
    headers = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    request.headers = headers
    return request


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def registry_with_peer() -> PeerRegistry:
    """Registry with a single peer (proteus)."""
    return PeerRegistry([
        PeerConfig(
            name="proteus",
            url="http://100.96.0.1:9696",
            api_key="sk-proteus-key",
        ),
    ])


@pytest.fixture
def empty_registry() -> PeerRegistry:
    """Registry with no peers configured."""
    return PeerRegistry([])


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestBearerTokenContextBuilder:
    """BearerTokenContextBuilder authentication behaviour."""

    def test_valid_token_authenticated(self, registry_with_peer: PeerRegistry) -> None:
        """Valid bearer token yields an authenticated user with the peer name."""
        builder = BearerTokenContextBuilder(registry_with_peer)
        request = _make_request(auth_header="Bearer sk-proteus-key")
        ctx = builder.build(request)

        assert ctx.user.is_authenticated is True
        assert ctx.user.user_name == "proteus"
        assert ctx.state.get("peer_name") == "proteus"

    def test_valid_token_state_contains_headers(
        self, registry_with_peer: PeerRegistry
    ) -> None:
        """State dict includes the request headers."""
        builder = BearerTokenContextBuilder(registry_with_peer)
        request = _make_request(auth_header="Bearer sk-proteus-key")
        ctx = builder.build(request)

        assert "headers" in ctx.state
        assert ctx.state["headers"]["Authorization"] == "Bearer sk-proteus-key"

    def test_invalid_token_unauthenticated(
        self, registry_with_peer: PeerRegistry
    ) -> None:
        """An invalid bearer token yields UnauthenticatedUser."""
        builder = BearerTokenContextBuilder(registry_with_peer)
        request = _make_request(auth_header="Bearer some-bad-token")
        ctx = builder.build(request)

        assert isinstance(ctx.user, UnauthenticatedUser)
        assert ctx.user.is_authenticated is False
        # peer_name should NOT be in state
        assert "peer_name" not in ctx.state

    def test_missing_auth_header_unauthenticated(
        self, registry_with_peer: PeerRegistry
    ) -> None:
        """No Authorization header yields UnauthenticatedUser."""
        builder = BearerTokenContextBuilder(registry_with_peer)
        request = _make_request(auth_header=None)
        ctx = builder.build(request)

        assert isinstance(ctx.user, UnauthenticatedUser)
        assert ctx.user.is_authenticated is False

    def test_empty_bearer_token_unauthenticated(
        self, registry_with_peer: PeerRegistry
    ) -> None:
        """Authorization: Bearer with no token yields UnauthenticatedUser."""
        builder = BearerTokenContextBuilder(registry_with_peer)
        request = _make_request(auth_header="Bearer ")
        ctx = builder.build(request)

        assert isinstance(ctx.user, UnauthenticatedUser)
        assert ctx.user.is_authenticated is False

    def test_auth_header_without_bearer_prefix(
        self, registry_with_peer: PeerRegistry
    ) -> None:
        """Authorization header without 'Bearer ' prefix is treated as missing."""
        builder = BearerTokenContextBuilder(registry_with_peer)
        request = _make_request(auth_header="Basic somecreds")
        ctx = builder.build(request)

        assert isinstance(ctx.user, UnauthenticatedUser)

    def test_empty_registry_all_unauthenticated(
        self, empty_registry: PeerRegistry
    ) -> None:
        """When no peers are configured, every request is unauthenticated."""
        builder = BearerTokenContextBuilder(empty_registry)
        request = _make_request(auth_header="Bearer any-token")
        ctx = builder.build(request)

        assert isinstance(ctx.user, UnauthenticatedUser)
        assert ctx.user.is_authenticated is False

    def test_peer_name_in_authenticated_user(
        self, registry_with_peer: PeerRegistry
    ) -> None:
        """_AuthenticatedUser.user_name returns the peer name."""
        builder = BearerTokenContextBuilder(registry_with_peer)
        request = _make_request(auth_header="Bearer sk-proteus-key")
        ctx = builder.build(request)

        assert ctx.user.user_name == "proteus"
