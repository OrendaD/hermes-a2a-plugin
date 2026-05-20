"""Tests for PeerRegistry and PeerConfig.

Covers:
- Register peers, look up by name
- Validate bearer token matches
- Token mismatch returns None
- Duplicate peer names rejected at init
- Empty registry returns None for all lookups
"""

from __future__ import annotations

import pytest

from adapter.peer_registry import PeerConfig, PeerRegistry


class TestPeerConfig:
    """PeerConfig dataclass construction."""

    def test_minimal_config(self) -> None:
        """Minimal fields only."""
        cfg = PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="sk-abc")
        assert cfg.name == "proteus"
        assert cfg.url == "http://100.96.0.1:9696"
        assert cfg.api_key == "sk-abc"
        assert cfg.cidr_allow == []

    def test_with_cidr(self) -> None:
        """CIDR allow list is honoured."""
        cfg = PeerConfig(
            name="proteus",
            url="http://100.96.0.1:9696",
            api_key="sk-abc",
            cidr_allow=["100.96.0.0/16", "10.0.0.0/8"],
        )
        assert cfg.cidr_allow == ["100.96.0.0/16", "10.0.0.0/8"]


class TestPeerRegistry:
    """PeerRegistry lookup and validation."""

    def test_get_peer_by_name(self) -> None:
        """Look up a registered peer by name."""
        registry = PeerRegistry([
            PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="key-a"),
            PeerConfig(name="athena", url="http://100.96.0.2:9696", api_key="key-b"),
        ])
        peer = registry.get_peer("proteus")
        assert peer is not None
        assert peer.name == "proteus"
        assert peer.url == "http://100.96.0.1:9696"

    def test_get_peer_missing(self) -> None:
        """Look up a peer that doesn't exist returns None."""
        registry = PeerRegistry([
            PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="key-a"),
        ])
        assert registry.get_peer("unknown") is None

    def test_validate_bearer_token_valid(self) -> None:
        """A matching bearer token returns the peer."""
        registry = PeerRegistry([
            PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="key-a"),
        ])
        peer = registry.validate_bearer_token("key-a")
        assert peer is not None
        assert peer.name == "proteus"

    def test_validate_bearer_token_invalid(self) -> None:
        """A non-matching bearer token returns None."""
        registry = PeerRegistry([
            PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="key-a"),
        ])
        assert registry.validate_bearer_token("wrong-key") is None

    def test_validate_bearer_token_empty_string(self) -> None:
        """Empty string token returns None (not matched against empty api_key)."""
        registry = PeerRegistry([
            PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="key-a"),
        ])
        assert registry.validate_bearer_token("") is None

    def test_all_peers(self) -> None:
        """all_peers returns every registered peer."""
        registry = PeerRegistry([
            PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="key-a"),
            PeerConfig(name="athena", url="http://100.96.0.2:9696", api_key="key-b"),
        ])
        peers = registry.all_peers()
        assert len(peers) == 2
        names = {p.name for p in peers}
        assert names == {"proteus", "athena"}

    def test_duplicate_peer_names_rejected(self) -> None:
        """Duplicate names raise ValueError at construction."""
        with pytest.raises(ValueError, match="Duplicate peer name"):
            PeerRegistry([
                PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="key-a"),
                PeerConfig(name="proteus", url="http://100.96.0.99:9696", api_key="key-b"),
            ])

    def test_last_api_key_wins_on_conflict(self) -> None:
        """If two peers share the same api_key, the last one registered wins."""
        registry = PeerRegistry([
            PeerConfig(name="proteus", url="http://100.96.0.1:9696", api_key="shared-key"),
            PeerConfig(name="athena", url="http://100.96.0.2:9696", api_key="shared-key"),
        ])
        peer = registry.validate_bearer_token("shared-key")
        assert peer is not None
        assert peer.name == "athena"  # last wins

    def test_empty_registry(self) -> None:
        """Empty peer registry returns None for all lookups."""
        registry = PeerRegistry([])
        assert registry.get_peer("anything") is None
        assert registry.validate_bearer_token("token") is None
        assert registry.all_peers() == []
