"""Agent Card builder — translates AgentCapability list to A2A AgentCard protobuf."""

from __future__ import annotations

from typing import Optional

from google.protobuf.json_format import MessageToDict

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    AgentSkill,
    AgentProvider,
)

from core.domain.models.capability import AgentCapability


def build_agent_card(
    capabilities: list[AgentCapability],
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
) -> AgentCard:
    """Build an A2A AgentCard protobuf from a list of agent capabilities.

    Args:
        capabilities: List of AgentCapability objects from profile discovery.
        node_name: Name of this Hermes node (used in AgentCard.name).
        node_description: Description of the node.
        node_version: Semantic version of this node's AgentCard.
        documentation_url: URL to documentation for this agent.
        interface_url: Base URL for the A2A JSON-RPC endpoint
            (e.g. ``http://100.96.0.2:8081``).
        protocol_binding: Protocol binding identifier (default ``JSONRPC``).
        protocol_version: Protocol version (default ``1.0``).
        provider_name: Provider display name.
        provider_url: Provider URL.
        streaming: Whether this node supports streaming.
        push_notifications: Whether this node supports push notifications.

    Returns:
        An AgentCard protobuf object.
    """
    # Build AgentSkill list from capabilities
    skills: list[AgentSkill] = []
    for cap in capabilities:
        skill = AgentSkill(
            id=f"skill/{cap.profile_name}",
            name=cap.display_name or cap.profile_name,
            description=cap.description or "",
            # Map intents and tags to tags[] and examples[]
            tags=cap.intents + cap.tags,
            examples=cap.examples or [],
        )
        skills.append(skill)

    # Build the card
    card = AgentCard(
        name=node_name,
        description=node_description,
        version=node_version,
        documentation_url=documentation_url,
        capabilities=AgentCapabilities(
            streaming=streaming,
            push_notifications=push_notifications,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=skills,
    )

    if provider_url or provider_name:
        card.provider.CopyFrom(
            AgentProvider(
                url=provider_url,
                organization=provider_name,
            )
        )

    if interface_url:
        interface = AgentInterface(
            url=interface_url.rstrip("/"),
            protocol_binding=protocol_binding,
            protocol_version=protocol_version,
        )
        card.supported_interfaces.append(interface)

    return card


def agent_card_to_dict(card: AgentCard) -> dict:
    """Serialize an AgentCard protobuf to a JSON-compatible dict.

    Uses ``preserving_proto_field_name=True`` so field names use
    ``snake_case`` as specified by the A2A protocol.

    Args:
        card: The AgentCard protobuf to serialize.

    Returns:
        Dict suitable for JSON serialization.
    """
    return _message_to_dict(card)


def _message_to_dict(msg) -> dict:
    """Thin wrapper around MessageToDict with consistent settings."""
    return MessageToDict(msg, preserving_proto_field_name=True)
