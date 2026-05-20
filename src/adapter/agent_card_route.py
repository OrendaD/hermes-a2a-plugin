"""Agent Card HTTP route — serves signed Agent Card at /.well-known/agent-card.json.

Wires together profile discovery, card building, and JWS signing into
a Starlette route with caching headers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from google.protobuf.json_format import MessageToDict
from starlette.responses import JSONResponse
from starlette.routing import Route

from adapter.agent_card_builder import build_agent_card
from adapter.agent_card_signer import ensure_keys, create_signer
from adapter.profile_discovery import discover_profiles


def create_agent_card_route(
    profiles_dir: str | Path,
    *,
    node_name: str = "hermes-node",
    node_description: str = "Hermes Agent node",
    node_version: str = "1.0.0",
    documentation_url: str = "",
    interface_url: str = "",
    protocol_binding: str = "JSONRPC",
    protocol_version: str = "1.0",
    provider_name: str = "Hermes",
    provider_url: str = "",
    streaming: bool = False,
    push_notifications: bool = False,
    node_id: str = "local",
    cache_max_age: int = 300,
) -> Route:
    """Create a Starlette Route for ``/.well-known/agent-card.json``.

    On each request, re-discovers profiles and rebuilds the card.
    Caching is handled via HTTP ``Cache-Control`` headers (the
    ``cache_max_age`` parameter, default 300s / 5 minutes).

    Args:
        profiles_dir: Path to the Hermes profiles directory
            (e.g. ``~/.hermes/profiles``).
        node_name: Name of this node.
        node_description: Description of the node.
        node_version: Semantic version of the Agent Card.
        documentation_url: URL to node documentation.
        interface_url: Base URL for the A2A JSON-RPC endpoint.
        protocol_binding: Protocol binding identifier.
        protocol_version: Protocol version string.
        provider_name: Provider / organization name.
        provider_url: Provider URL.
        streaming: Whether this node supports streaming.
        push_notifications: Whether this node supports push notifications.
        node_id: Node identifier used during profile discovery.
        cache_max_age: ``Cache-Control: max-age`` value in seconds.

    Returns:
        A Starlette ``Route`` object ready to mount on an ``app``.
    """
    profiles_path = Path(profiles_dir)

    async def _serve_agent_card(request):
        # Discovers profiles and loads signing key
        caps = discover_profiles(profiles_path, node_id=node_id)

        card = build_agent_card(
            caps,
            node_name=node_name,
            node_description=node_description,
            node_version=node_version,
            documentation_url=documentation_url,
            interface_url=interface_url,
            protocol_binding=protocol_binding,
            protocol_version=protocol_version,
            provider_name=provider_name,
            provider_url=provider_url,
            streaming=streaming,
            push_notifications=push_notifications,
        )

        # Sign the card — we use the first profile dir's signing key.
        # In a multi-key setup, this would be a separate keystore lookup.
        # For now, use the first profile found, or fall back to no signature.
        try:
            first_profile = next(p for p in profiles_path.iterdir() if p.is_dir())
            private_pem, _ = ensure_keys(first_profile)
            signer = create_signer(private_pem)
            card = signer(card)
        except (StopIteration, FileNotFoundError, Exception):
            # No profiles, no signing key — serve unsigned (dev only)
            pass

        # Serialize using protobuf field names
        payload = MessageToDict(card, preserving_proto_field_name=True)

        return JSONResponse(
            content=payload,
            headers={
                "Cache-Control": f"max-age={cache_max_age}",
                "Content-Type": "application/json",
            },
        )

    return Route("/.well-known/agent-card.json", endpoint=_serve_agent_card)
