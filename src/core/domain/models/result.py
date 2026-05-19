"""TaskResult — the outcome of executing a TaskIntent.

Covers the full A2A state spectrum: success, failure,
or requests for more information (input-required, auth-required).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Valid terminal statuses
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "rejected"})

# Valid interrupted statuses (agent can resume)
INTERRUPTED_STATUSES = frozenset({"input_required", "auth_required"})

# Non-terminal lifecycle states (task is still in progress)
LIFECYCLE_STATUSES = frozenset({"submitted", "working"})

# All valid statuses (outcome-oriented — for TaskResult)
ALL_STATUSES = TERMINAL_STATUSES | INTERRUPTED_STATUSES

# Full lifecycle statuses (for TaskRecord tracking)
TASK_LIFECYCLE_STATUSES = ALL_STATUSES | LIFECYCLE_STATUSES


@dataclass
class TaskResult:
    """The outcome of executing a TaskIntent.

    Attributes:
        status: One of: 'completed', 'failed', 'cancelled', 'rejected',
            'input_required', 'auth_required'
        data: The result payload. For 'completed', this is the artifact.
            For 'input_required'/'auth_required', describes what's needed.
        error: Human-readable error message if status == 'failed'.
        requires_escalation: True if this task needs human intervention.
        escalation_reason: Why human escalation is needed.
        messages: Conversation history for multi-turn tasks.
            Each entry: {'role': str, 'content': str, 'metadata': dict}
        artifacts: Named outputs.
            Each entry: {'name': str, 'content': str | dict, 'media_type': str}
        metadata: Free-form metadata.
    """

    status: str
    data: Optional[dict] = None
    error: Optional[str] = None
    requires_escalation: bool = False
    escalation_reason: Optional[str] = None
    messages: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate status on creation."""
        if self.status not in ALL_STATUSES:
            valid = ", ".join(sorted(ALL_STATUSES))
            raise ValueError(
                f"Invalid status: '{self.status}'. "
                f"Must be one of: {valid}"
            )

    @property
    def is_terminal(self) -> bool:
        """True if this result represents a terminal task state."""
        return self.status in TERMINAL_STATUSES

    @property
    def requires_input(self) -> bool:
        """True if this result indicates the task needs more information."""
        return self.status in INTERRUPTED_STATUSES
