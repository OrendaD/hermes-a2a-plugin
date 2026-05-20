"""Peer registry — manages configured A2A peers and validates bearer tokens.

A peer represents another A2A node that this node communicates with.
The registry holds known peers and supports:
- Looking up peers by name for outbound routing
- Validating bearer tokens against known peer API keys for inbound auth
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PeerConfig:
    """Configuration for a single peer A2A node.

    Attributes:
        name: Unique identifier, used for routing and logging.
        url: Base URL for the peer's A2A server (e.g. ``http://100.96.0.1:9696``).
        api_key: Shared secret / bearer token for authenticating requests.
        cidr_allow: Optional list of CIDR blocks allowed for SSRF protection.
    """

    name: str
    url: str
    api_key: str
    cidr_allow: list[str] = field(default_factory=list)


class PeerRegistry:
    """Holds configured peers and validates incoming credentials.

    Maintains two lookup maps:
    - name → PeerConfig for outbound routing
    - api_key → PeerConfig for inbound bearer-token validation

    Duplicate peer names are rejected at construction time.
    """

    def __init__(self, peers: list[PeerConfig]) -> None:
        self._peers: dict[str, PeerConfig] = {}
        self._tokens: dict[str, PeerConfig] = {}

        for p in peers:
            if p.name in self._peers:
                raise ValueError(f"Duplicate peer name: {p.name!r}")
            self._peers[p.name] = p
            # If two peers share the same api_key, the last one wins
            self._tokens[p.api_key] = p

    def validate_bearer_token(self, token: str) -> Optional[PeerConfig]:
        """Return the peer if *token* matches a known peer's api_key, else None.

        Args:
            token: The bearer token extracted from the Authorization header.

        Returns:
            The matching PeerConfig, or None if no peer has this token.
        """
        return self._tokens.get(token)

    def get_peer(self, name: str) -> Optional[PeerConfig]:
        """Return the peer with the given name, or None if not found."""
        return self._peers.get(name)

    def all_peers(self) -> list[PeerConfig]:
        """Return a list of all registered peers."""
        return list(self._peers.values())
