"""Orchestrator interface — manages live multi-task orchestration flows.

The Orchestrator is STATEFUL. It tracks live conversation graphs,
detects ``input-required`` status transitions, recruits specialists,
composes answers, and resumes blocked tasks.

Responsibilities:
- Monitor mid-flight tasks for status transitions
- Handle INPUT_REQUIRED by recruiting specialists
- Compose answers and resume blocked tasks
- Track conversation graphs (contextId → task tree)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models.intent import TaskIntent
from ..models.result import TaskResult


class Orchestrator(ABC):
    """Manages live multi-task orchestration flows."""

    @abstractmethod
    def register_task(
        self,
        task_id: str,
        context_id: str,
        parent_task_id: Optional[str] = None,
        target_profile: Optional[str] = None,
        target_node: Optional[str] = None,
    ) -> None:
        """Register a task for lifecycle monitoring.

        Args:
            task_id: The task to track.
            context_id: Conversation grouping identifier.
            parent_task_id: If this is a sub-task, the parent's task ID.
            target_profile: The profile executing this task (for FC release).
            target_node: The node the profile lives on.
        """
        ...

    @abstractmethod
    def on_status_change(
        self,
        task_id: str,
        new_state: str,
        task_result: TaskResult,
    ) -> None:
        """Called by adapter when any tracked task changes state.

        If new_state == 'input_required':
          1. Parse the request from task_result.data
          2. Call recruit_specialist() or route to human
          3. Compose the answer as a new TaskIntent
          4. Resume the original task

        If new_state == 'completed' | 'failed' | 'cancelled':
          1. Log the outcome
          2. Notify parent task if this was a sub-task
          3. Clean up tracking

        Args:
            task_id: The task that changed state.
            new_state: The new state value.
            task_result: The result containing any data or error info.
        """
        ...

    @abstractmethod
    def recruit_specialist(
        self,
        question: str,
        source_context_id: str,
        parent_task_id: str,
        tags: Optional[list[str]] = None,
    ) -> TaskResult:
        """Find the right profile for a sub-question and dispatch a new task.

        Uses the Fleet Controller's discover() to find candidates.
        Dispatches via the adapter's send_task().
        Waits for completion (or first result for streaming).

        Args:
            question: The sub-question to answer.
            source_context_id: The parent task's context ID.
            parent_task_id: The blocked task that needs this answer.
            tags: Optional tags to narrow specialist search.

        Returns:
            The specialist's answer as a TaskResult.
        """
        ...

    @abstractmethod
    def get_conversation_graph(self, context_id: str) -> dict:
        """Return the task tree for a context_id.

        Shows all linked tasks, their statuses, and parent-child links.
        Used for audit, debugging, and recovery after restart.

        Args:
            context_id: The conversation to inspect.

        Returns:
            Nested dict representing the task tree.
        """
        ...
