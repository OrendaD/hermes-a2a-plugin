"""Fleet Controller — stateless task routing engine.

Matches TaskIntents to the right profile and node based on
capability declarations. Prefers local profiles, falls back
to mesh peers. Tracks availability to avoid overcommitting
a profile.
"""

from __future__ import annotations

import uuid
from typing import Optional

from .domain.models.intent import TaskIntent
from .domain.models.dispatch import ProfileDispatch
from .domain.models.capability import AgentCapability
from .domain.interfaces.fleet_controller import FleetController


class FleetControllerImpl(FleetController):
    """Concrete Fleet Controller.

    Maintains a registry of AgentCapabilities (from local profiles
    and cached mesh-peer Agent Cards) and an availability tracker
    that marks profiles busy during task execution.

    Routing priority:
    1. Explicit target_profile + target_node (if both given)
    2. Explicit target_profile (any node)
    3. Explicit target_node (best profile on that node)
    4. Best match across all nodes, preferring local
    """

    def __init__(self) -> None:
        # profile_name -> AgentCapability
        self._capabilities: dict[str, AgentCapability] = {}
        # profile_name -> True if currently dispatched
        self._busy: set[str] = set()
        # Node ID of this instance (set externally after init)
        self._local_node_id: str = "local"
        # Per-profile max concurrent tasks (default 1)
        self._max_concurrent: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, intent: TaskIntent) -> ProfileDispatch:
        task_id = _generate_task_id()

        # --- Priority 1: explicit target_profile ---
        if intent.target_profile:
            cap = self._capabilities.get(intent.target_profile)
            if cap is None:
                return ProfileDispatch(
                    task_id=task_id,
                    profile_name=intent.target_profile,
                    node_address="unknown",
                    endpoint="",
                    status="unavailable",
                    message=f"Profile '{intent.target_profile}' not found in registry",
                )

            # If target_node also given, verify it matches
            if intent.target_node and cap.node_id != intent.target_node:
                return ProfileDispatch(
                    task_id=task_id,
                    profile_name=intent.target_profile,
                    node_address=intent.target_node,
                    endpoint="",
                    status="unavailable",
                    message=(
                        f"Profile '{intent.target_profile}' is on node "
                        f"'{cap.node_id}', not '{intent.target_node}'"
                    ),
                )

            # Check capability match
            if not cap.can_handle(intent.intent_type):
                return ProfileDispatch(
                    task_id=task_id,
                    profile_name=intent.target_profile,
                    node_address=cap.node_id,
                    endpoint=_endpoint_for(cap),
                    status="unavailable",
                    message=(
                        f"Profile '{intent.target_profile}' cannot handle "
                        f"intent '{intent.intent_type}'"
                    ),
                )

            # Check availability
            if self._is_busy(intent.target_profile):
                return ProfileDispatch(
                    task_id=task_id,
                    profile_name=intent.target_profile,
                    node_address=cap.node_id,
                    endpoint=_endpoint_for(cap),
                    status="no_capacity",
                    message=f"Profile '{intent.target_profile}' is busy",
                )

            self._mark_busy(intent.target_profile)
            return ProfileDispatch(
                task_id=task_id,
                profile_name=intent.target_profile,
                node_address=cap.node_id,
                endpoint=_endpoint_for(cap),
                status="dispatched",
            )

        # --- Priority 2: explicit target_node ---
        if intent.target_node:
            candidates = _filter_by_node(self._capabilities, intent.target_node)
            match = _best_match(candidates, intent.intent_type, intent.metadata.get("tags"))
        else:
            # --- Priority 3: best match across all nodes, prefer local ---
            candidates = list(self._capabilities.values())
            match = _best_match(candidates, intent.intent_type, intent.metadata.get("tags"))

        if match is None:
            return ProfileDispatch(
                task_id=task_id,
                profile_name="",
                node_address=intent.target_node or "any",
                endpoint="",
                status="unavailable",
                message=(
                    f"No profile can handle intent '{intent.intent_type}'"
                ),
            )

        # For any-node routing, prefer local
        if not intent.target_node and match.node_id != self._local_node_id:
            local_candidates = _filter_by_node(
                self._capabilities, self._local_node_id
            )
            local_match = _best_match(
                local_candidates, intent.intent_type, intent.metadata.get("tags")
            )
            # Only prefer local if it can ACTUALLY handle the intent
            if local_match is not None \
                    and local_match.can_handle(intent.intent_type) \
                    and not self._is_busy(local_match.profile_name):
                match = local_match

        if self._is_busy(match.profile_name):
            return ProfileDispatch(
                task_id=task_id,
                profile_name=match.profile_name,
                node_address=match.node_id,
                endpoint=_endpoint_for(match),
                status="no_capacity",
                message=f"Profile '{match.profile_name}' is busy",
            )

        self._mark_busy(match.profile_name)
        return ProfileDispatch(
            task_id=task_id,
            profile_name=match.profile_name,
            node_address=match.node_id,
            endpoint=_endpoint_for(match),
            status="dispatched",
        )

    def release(self, task_id: str, profile_name: str) -> None:
        """Mark a profile as available after task completion."""
        self._mark_free(profile_name)

    def register_profile(self, capability: AgentCapability) -> None:
        """Register a profile's capability."""
        self._capabilities[capability.profile_name] = capability

    def discover(
        self,
        intent_type: str,
        tags: Optional[list[str]] = None,
    ) -> list[AgentCapability]:
        """Find all profiles that can handle a given intent type."""
        results: list[AgentCapability] = []
        for cap in self._capabilities.values():
            if cap.can_handle(intent_type, tags):
                results.append(cap)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_busy(self, profile_name: str) -> bool:
        return profile_name in self._busy

    def _mark_busy(self, profile_name: str) -> None:
        self._busy.add(profile_name)

    def _mark_free(self, profile_name: str) -> None:
        self._busy.discard(profile_name)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _generate_task_id() -> str:
    return f"task/{uuid.uuid4().hex[:12]}"


def _endpoint_for(cap: AgentCapability) -> str:
    """Return the dispatch endpoint string for a capability."""
    if cap.node_id == "local":
        return f"internal:{cap.profile_name}"
    return f"a2a://{cap.node_id}/{cap.profile_name}"


def _filter_by_node(
    capabilities: dict[str, AgentCapability],
    node_id: str,
) -> list[AgentCapability]:
    return [c for c in capabilities.values() if c.node_id == node_id]


def _best_match(
    candidates: list[AgentCapability],
    intent_type: str,
    tags: Optional[object] = None,
) -> Optional[AgentCapability]:
    """Find the best candidate for an intent type.

    Returns None if no candidate can handle the intent.
    Prefers exact intent_type match over tag fallback.
    """
    # Prefer exact intent type matches
    for cap in candidates:
        if intent_type in cap.intents:
            return cap
    # Fall back to tag matching
    tag_list: list[str] = list(tags) if isinstance(tags, list) else []
    if tag_list:
        for cap in candidates:
            if any(t in cap.tags for t in tag_list):
                return cap
    # No match found
    return None
