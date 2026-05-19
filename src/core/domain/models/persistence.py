"""TaskRecord and ConversationGraph — runtime task tracking.

These are in-memory structures for the Core Layer's runtime tracking
of active task flows. The adapter owns the SQLite persistence layer;
these stores are ephemeral — they live for the life of the gateway
process.

ConversationGraph tracks the task tree for a single orchestration
flow, enabling audit, recovery, and ListTasks queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .result import TERMINAL_STATUSES, TASK_LIFECYCLE_STATUSES


@dataclass
class TaskRecord:
    """Persisted representation of an A2A task.

    Used by the ConversationGraph for runtime tracking of active
    orchestration flows. The adapter handles SQLite persistence —
    this is the in-memory representation.

    Attributes:
        task_id: Unique task identifier.
        context_id: Groups related tasks into one conversation.
        status: Task state (members of ALL_STATUSES).
        intent_type: What kind of task this is.
        source_node: Which node originated this task.
        target_profile: Which profile is executing this task.
        target_node: Which node the profile lives on.
        payload: The input data for this task.
        result: The output data (set on completion/failure).
        messages: Multi-turn conversation history.
        artifacts: Named output artifacts.
        reference_task_ids: Parent/related task IDs for graph linking.
        metadata: Free-form metadata.
        created_at: When this task was created.
        updated_at: When this task was last updated.
        terminal: True if task is in a terminal state.
    """

    task_id: str
    context_id: str
    status: str
    intent_type: str
    source_node: str
    target_profile: str
    target_node: str
    payload: dict
    result: Optional[dict] = None
    messages: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    reference_task_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    terminal: bool = False

    def __post_init__(self) -> None:
        """Auto-set terminal flag and validate status."""
        if self.status not in TASK_LIFECYCLE_STATUSES:
            valid = ", ".join(sorted(TASK_LIFECYCLE_STATUSES))
            raise ValueError(
                f"Invalid status: '{self.status}'. "
                f"Must be one of: {valid}"
            )
        if self.status in TERMINAL_STATUSES:
            self.terminal = True


@dataclass
class ConversationGraph:
    """An orchestration flow — one root task with linked sub-tasks.

    Recoverable from contextId.

    Attributes:
        context_id: The conversation identifier grouping all tasks.
        root_task_id: The initial task that started this flow.
        tasks: Mapping of task_id → TaskRecord for all linked tasks.
    """

    context_id: str
    root_task_id: str
    tasks: dict[str, TaskRecord] = field(default_factory=dict)

    def add_task(self, record: TaskRecord) -> None:
        """Add a task to the graph.

        Args:
            record: The TaskRecord to add. Must have context_id matching
                this graph's context_id.
        """
        if record.context_id != self.context_id:
            raise ValueError(
                f"Task context_id '{record.context_id}' does not match "
                f"graph context_id '{self.context_id}'"
            )
        self.tasks[record.task_id] = record

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve a task by ID."""
        return self.tasks.get(task_id)

    def get_children(self, task_id: str) -> list[TaskRecord]:
        """Return all direct children of a given task.

        Children are tasks whose reference_task_ids includes task_id.
        """
        return [
            t for t in self.tasks.values()
            if task_id in t.reference_task_ids
        ]

    def get_tree(self) -> dict:
        """Return a nested dict representation of the task tree.

        Useful for serialization, debugging, and ListTasks responses.
        """
        def _build_node(record: TaskRecord) -> dict:
            node = {
                "task_id": record.task_id,
                "status": record.status,
                "intent_type": record.intent_type,
                "terminal": record.terminal,
            }
            children = self.get_children(record.task_id)
            if children:
                node["children"] = [_build_node(c) for c in children]
            return node

        root = self.tasks.get(self.root_task_id)
        if root is None:
            return {"context_id": self.context_id, "error": "root task not found"}

        return {
            "context_id": self.context_id,
            "root_task_id": self.root_task_id,
            "tasks": [_build_node(root)],
        }
