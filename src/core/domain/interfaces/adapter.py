"""A2AAdapter — the plugin's contract to the Core layer.

The Core calls these methods when it needs to send or receive across
the protocol boundary. The Adapter implementation (Phase 3, Proteus)
translates to/from A2A protocol objects.

The Core does NOT implement this interface — it calls it. The adapter
implements it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.intent import TaskIntent
from ..models.result import TaskResult
from ..models.capability import AgentCapability


class A2AAdapter(ABC):
    """The plugin's contract to the Core layer.

    The Core calls these methods when it needs to send or receive
    across the protocol boundary. The Adapter implementation translates
    to/from A2A protocol objects.
    """

    @abstractmethod
    def send_task(self, intent: TaskIntent) -> TaskResult:
        """Send a task to a profile.

        Either locally (spawn profile) or remotely (A2A call to a
        mesh peer). Returns the result when the task reaches a
        terminal state.

        Args:
            intent: The task intent to send.

        Returns:
            The result when the task reaches a terminal state.
        """
        ...

    @abstractmethod
    async def send_streaming_task(self, intent: TaskIntent) -> TaskResult:
        """Like send_task but with streaming updates.

        The Core provides a callback for intermediate results via
        intent.metadata['on_partial'].

        Args:
            intent: The task intent to send, with streaming metadata.

        Returns:
            The final result when the task reaches a terminal state.
        """
        ...

    @abstractmethod
    def cancel_task(self, task_id: str) -> bool:
        """Request cancellation of an in-flight task.

        Args:
            task_id: The task to cancel.

        Returns:
            True if cancellation was accepted, False otherwise.
        """
        ...

    @abstractmethod
    def get_capabilities(self) -> list[AgentCapability]:
        """Return this node's capabilities.

        Reads the profile directories and loads their SOUL.md + config
        to build AgentCapability objects. Called at plugin startup to
        build the AgentCard.

        Returns:
            List of AgentCapability objects for this node.
        """
        ...
