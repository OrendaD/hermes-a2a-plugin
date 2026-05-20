"""Agent Card HTTP route — serves signed Agent Card at /.well-known/agent-card.json.

Wires together profile discovery, card building, and JWS signing into
a Starlette route with caching headers.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from google.protobuf.json_format import MessageToDict
from starlette.responses import JSONResponse
from starlette.routing import Route

from adapter.agent_card_builder import build_agent_card
from adapter.agent_card_signer import ensure_keys, create_signer
from adapter.profile_discovery import discover_profiles

logger = logging.getLogger(__name__)


def create_agent_card_route(
    profiles_dir: str | Path,
    *,
    signing_profile: Optional[str] = None,
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
        signing_profile: Optional profile name to use for the signing key.
            If None, uses the first profile directory found.
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

        # Sign the card using the configured (or first) profile's signing key.
        # Snapshot os.environ to isolate ensure_keys() pollution — the signer's
        # _load_env_file writes every variable from the profile's .env into the
        # global process environment, which can leak secrets across profiles.
        _saved_env = dict(os.environ)
        signed = False
        signing_reason = ""

        try:
            private_pem = _resolve_signing_key(
                profiles_path, signing_profile,
            )
            if private_pem is not None:
                signer = create_signer(private_pem)
                card = signer(card)
                signed = True
                signing_reason = "signed"
        except Exception:
            logger.exception("Unexpected error signing agent card")
            signing_reason = "signing error"
        finally:
            # Restore environment to prevent leakage of .env vars
            os.environ.clear()
            os.environ.update(_saved_env)

        # Serialize using protobuf field names
        payload = MessageToDict(card, preserving_proto_field_name=True)

        signed_header = "true" if signed else f"false ({signing_reason})"

        return JSONResponse(
            content=payload,
            headers={
                "Cache-Control": f"max-age={cache_max_age}",
                "Content-Type": "application/json",
                "X-Agent-Card-Signed": signed_header,
            },
        )

    return Route("/.well-known/agent-card.json", endpoint=_serve_agent_card)


def _resolve_signing_key(
    profiles_path: Path,
    signing_profile: Optional[str],
) -> Optional[str]:
    """Resolve the PEM private key for signing from the configured profile.

    Returns None (with logging) when no key is available instead of raising.
    """
    if signing_profile:
        profile_dir = profiles_path / signing_profile
        if not profile_dir.is_dir():
            logger.warning(
                "signing_profile '%s' not found under %s — serving unsigned",
                signing_profile, profiles_path,
            )
            return None
        try:
            private_pem, _ = ensure_keys(profile_dir)
            return private_pem
        except FileNotFoundError:
            logger.warning(
                "No A2A_SIGNING_KEY in profile '%s' — serving unsigned",
                signing_profile,
            )
            return None

    # Fall back to first profile directory
    try:
        first_profile = next(p for p in profiles_path.iterdir() if p.is_dir())
    except StopIteration:
        logger.info("No profiles found — serving unsigned agent card")
        return None

    try:
        private_pem, _ = ensure_keys(first_profile)
        return private_pem
    except FileNotFoundError:
        logger.warning("No A2A_SIGNING_KEY in first profile — serving unsigned")
        return None
