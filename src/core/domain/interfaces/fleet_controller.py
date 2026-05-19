"""Fleet Controller interface — routes TaskIntents to the right profile and node.

The Fleet Controller is STATELESS. It matches intents to capabilities,
checks availability, and returns a dispatch decision. It does NOT
track mid-flight tasks — that's the Orchestrator's job.

Responsibilities:
- Capability-based routing (match intent → profile)
- Node-aware routing (prefer local, fall back to mesh)
- Availability checking (is the profile busy?)
- Capacity management (concurrent task limits)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models.intent import TaskIntent
from ..models.dispatch import ProfileDispatch
from ..models.capability import AgentCapability


class FleetController(ABC):
    """Routes TaskIntents to the right profile and node.

    Decision logic:
    1. If target_profile set: verify it can handle the intent_type
    2. If target_node set: verify node is reachable
    3. Otherwise: match intent_type against all available AgentCapabilities
       across local and mesh profiles
    4. Prefer local profile over remote (lower latency)
    5. Check profile availability (not busy, capacity slots open)
    6. Return dispatch decision or 'unavailable'/'no_capacity'
    """

    @abstractmethod
    def route(self, intent: TaskIntent) -> ProfileDispatch:
        """Find the best profile for this intent.

        Args:
            intent: The task intent to route.

        Returns:
            A ProfileDispatch with the routing decision.
        """
        ...

    @abstractmethod
    def release(self, task_id: str, profile_name: str) -> None:
        """Mark a profile as available after task completion.

        Called by the adapter when a task reaches a terminal state.

        Args:
            task_id: The completed task's ID.
            profile_name: The profile to release.
        """
        ...

    @abstractmethod
    def register_profile(self, capability: AgentCapability) -> None:
        """Register a profile's capability.

        Called at plugin startup when AgentCard is parsed and profile
        directory is discovered.

        Args:
            capability: The profile's capability descriptor.
        """
        ...

    @abstractmethod
    def discover(
        self,
        intent_type: str,
        tags: Optional[list[str]] = None,
    ) -> list[AgentCapability]:
        """Find all profiles that can handle a given intent type.

        Returns profiles from all known nodes (local + mesh peers
        from cached Agent Cards).

        Args:
            intent_type: The intent type to search for.
            tags: Optional tags to narrow the search.

        Returns:
            List of matching AgentCapabilities.
        """
        ...
