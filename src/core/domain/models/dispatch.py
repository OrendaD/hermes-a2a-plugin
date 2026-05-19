"""ProfileDispatch — the Fleet Controller's routing decision.

Tells the adapter which profile to call and how.
"""

from __future__ import annotations

from dataclasses import dataclass


# Valid dispatch statuses
DISPATCH_STATUSES = frozenset({
    "dispatched",
    "queued",
    "unavailable",
    "no_capacity",
})


@dataclass
class ProfileDispatch:
    """The Fleet Controller's routing decision.

    Attributes:
        task_id: Unique task ID for tracking.
        profile_name: Target profile to execute the task.
        node_address: Where the profile lives.
            'local' for same-node, mesh IP (100.96.x.x) for remote.
        endpoint: A2A endpoint URL for remote dispatch, or
            'internal:profile' for local dispatch.
        status: One of: 'dispatched', 'queued', 'unavailable',
            'no_capacity'.
        message: Human-readable status detail.
    """

    task_id: str
    profile_name: str
    node_address: str
    endpoint: str
    status: str
    message: str = ""

    def __post_init__(self) -> None:
        """Validate status on creation."""
        if self.status not in DISPATCH_STATUSES:
            valid = ", ".join(sorted(DISPATCH_STATUSES))
            raise ValueError(
                f"Invalid dispatch status: '{self.status}'. "
                f"Must be one of: {valid}"
            )

    @property
    def is_successful(self) -> bool:
        """True if the task was successfully dispatched."""
        return self.status == "dispatched"
