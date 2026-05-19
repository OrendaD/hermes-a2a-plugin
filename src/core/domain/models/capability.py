"""AgentCapability — describes a profile's capability for discovery and routing.

Maps closely to A2A's AgentSkill, but is protocol-agnostic.
The adapter translates this TO the AgentCard JSON; the core
never sees the JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentCapability:
    """Describes a profile's capability for discovery and routing.

    Attributes:
        profile_name: Unique identifier. Maps to
            ``~/.hermes/profiles/<profile_name>/``
        node_id: Mesh IP or node identity. Determines addressability.
        display_name: Human-readable name (e.g., 'System Diagnostician').
        description: What this profile does and when to use it.
        intents: Intent types this profile handles.
            Examples: 'action_request', 'review', 'consultation',
            'notification', 'instruction'.
        tags: Keywords for discovery-based routing.
        examples: Example payloads showing expected input format.
            Critical for remote orchestrators formulating their calls.
        input_modes: Content types the profile can accept.
        output_modes: Content types the profile can produce.
        supports_streaming: True if this profile can stream results.
        supports_push: True if this profile can send push notifications.
    """

    profile_name: str
    node_id: str
    display_name: str
    description: str
    intents: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    input_modes: list[str] = field(
        default_factory=lambda: ["text", "application/json"]
    )
    output_modes: list[str] = field(
        default_factory=lambda: ["text", "application/json"]
    )
    supports_streaming: bool = False
    supports_push: bool = False

    def can_handle(self, intent_type: str, tags: Optional[list[str]] = None) -> bool:
        """Check if this capability can handle a given intent type.

        Matching logic:
        1. Exact match on intent_type in self.intents
        2. Tag overlap if intent_type doesn't match directly
           (fallback for loosely-typed routing)

        Args:
            intent_type: The intent type to check.
            tags: Optional tags to match against for fallback routing.

        Returns:
            True if this capability can handle the request.
        """
        if intent_type in self.intents:
            return True
        if tags and any(t in self.tags for t in tags):
            return True
        return False
