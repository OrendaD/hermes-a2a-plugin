"""Orchestrator — stateful multi-task orchestration engine.

Manages live conversation graphs, detects ``input-required``
transitions, recruits specialists across nodes, composes answers,
and resumes blocked tasks.

Depends on FleetController for routing and A2AAdapter for
cross-protocol dispatch. Both are constructor-injected.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .domain.models.intent import TaskIntent
from .domain.models.result import TaskResult
from .domain.models.persistence import TaskRecord, ConversationGraph
from .domain.interfaces.fleet_controller import FleetController
from .domain.interfaces.orchestrator import Orchestrator
from .domain.interfaces.adapter import A2AAdapter


# Maximum recursion depth for specialist recruitment
MAX_SPECIALIST_DEPTH = 3


class OrchestratorImpl(Orchestrator):
    """Concrete Orchestrator.

    Injected with a FleetController (routing) and A2AAdapter (dispatch).
    Manages ConversationGraph instances for active orchestration flows.
    """

    def __init__(
        self,
        fleet_controller: FleetController,
        adapter: A2AAdapter,
    ) -> None:
        self._fc = fleet_controller
        self._adapter = adapter
        # context_id -> ConversationGraph
        self._graphs: dict[str, ConversationGraph] = {}
        # task_id -> depth counter (for recursion limits)
        self._depth: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_task(
        self,
        task_id: str,
        context_id: str,
        parent_task_id: Optional[str] = None,
        target_profile: Optional[str] = None,
        target_node: Optional[str] = None,
    ) -> None:
        """Register a task and attach it to its conversation graph."""
        if context_id not in self._graphs:
            self._graphs[context_id] = ConversationGraph(
                context_id=context_id,
                root_task_id=task_id,
            )
        graph = self._graphs[context_id]

        # Derive intent_type and source from parent if available
        parent = graph.get_task(parent_task_id) if parent_task_id else None
        record = TaskRecord(
            task_id=task_id,
            context_id=context_id,
            status="submitted",
            intent_type=parent.intent_type if parent else "unknown",
            source_node=parent.source_node if parent else "local",
            target_profile=target_profile or (parent.target_profile if parent else ""),
            target_node=target_node or (parent.target_node if parent else ""),
            payload=parent.payload if parent else {},
            reference_task_ids=[parent_task_id] if parent_task_id else [],
        )
        graph.add_task(record)

        # Track recursion depth for specialist chain
        if parent_task_id:
            self._depth[task_id] = self._depth.get(parent_task_id, 0) + 1

    def on_status_change(
        self,
        task_id: str,
        new_state: str,
        task_result: TaskResult,
    ) -> None:
        """Handle task state transitions.

        For ``input_required``: extracts the question, recruits a
        specialist via the Fleet Controller, composes the answer,
        and resumes the parent task.

        For terminal states: updates the graph and releases the
        Fleet Controller slot for the profile.
        """
        graph = self._find_graph_for_task(task_id)
        if graph is None:
            return
        record = graph.get_task(task_id)
        if record is None:
            return

        # Update record
        record.status = new_state
        if task_result.data is not None:
            record.result = task_result.data
        record.messages.extend(task_result.messages)
        record.artifacts.extend(task_result.artifacts)
        record.terminal = task_result.is_terminal
        record.updated_at = datetime.utcnow()

        # --- INPUT_REQUIRED: recruit specialist and resume ---
        if new_state == "input_required" and not task_result.requires_escalation:
            self._handle_input_required(record, task_result)

        # --- Terminal: release FC slot ---
        if task_result.is_terminal:
            self._fc.release(task_id, record.target_profile)

    def recruit_specialist(
        self,
        question: str,
        source_context_id: str,
        parent_task_id: str,
        tags: Optional[list[str]] = None,
    ) -> TaskResult:
        """Find the best specialist and dispatch a sub-task.

        Uses FleetController.discover() to find candidates, then
        dispatches via A2AAdapter.send_task(). Falls back to
        escalation if no specialist is available.
        """
        # Depth guard
        current_depth = self._depth.get(parent_task_id, 0)
        if current_depth >= MAX_SPECIALIST_DEPTH:
            return TaskResult(
                status="input_required",
                data={"question": question},
                requires_escalation=True,
                escalation_reason=(
                    f"Max specialist depth ({MAX_SPECIALIST_DEPTH}) reached "
                    f"for task '{parent_task_id}'"
                ),
            )

        # Discover specialists
        candidates = self._fc.discover("consultation", tags)
        if not candidates:
            candidates = self._fc.discover("action_request", tags)

        if not candidates:
            return TaskResult(
                status="input_required",
                data={"question": question},
                requires_escalation=True,
                escalation_reason=(
                    f"No specialist found for question in task "
                    f"'{parent_task_id}': {question[:200]}"
                ),
            )

        specialist = candidates[0]

        # Dispatch sub-task
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": question},
            target_profile=specialist.profile_name,
            target_node=specialist.node_id,
            context_id=source_context_id,
            reference_task_ids=[parent_task_id],
            source_profile="orchestrator",
            metadata={"tags": tags} if tags else {},
        )

        result = self._adapter.send_task(intent)
        return result

    def get_conversation_graph(self, context_id: str) -> dict:
        """Return the task tree for a conversation."""
        graph = self._graphs.get(context_id)
        if graph is None:
            return {
                "context_id": context_id,
                "error": "no tasks recorded for this context",
            }
        return graph.get_tree()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _handle_input_required(
        self,
        record: TaskRecord,
        task_result: TaskResult,
    ) -> None:
        """Recruit specialist, compose answer, resume parent task."""
        question = ""
        if task_result.data and "question" in task_result.data:
            question = task_result.data["question"]
        if not question:
            question = task_result.data.get("message", str(task_result.data)) if task_result.data else ""

        tags: Optional[list[str]] = None
        if task_result.metadata and "tags" in task_result.metadata:
            tags = task_result.metadata["tags"]

        specialist_result = self.recruit_specialist(
            question=question,
            source_context_id=record.context_id,
            parent_task_id=record.task_id,
            tags=tags,
        )

        # If specialist succeeded, compose answer and resume
        if specialist_result.is_terminal and not specialist_result.requires_escalation:
            resume = TaskIntent(
                intent_type="instruction",
                payload={
                    "answer": specialist_result.data,
                    "resume_task_id": record.task_id,
                },
                target_profile=record.target_profile,
                target_node=record.target_node,
                context_id=record.context_id,
                reference_task_ids=[record.task_id],
                source_profile="orchestrator",
            )
            resume_result = self._adapter.send_task(resume)
            record.status = "working"
            record.updated_at = datetime.utcnow()
            # If resume also failed, mark it
            if resume_result.is_terminal and resume_result.status != "completed":
                record.status = resume_result.status
                record.result = resume_result.data
        elif specialist_result.requires_escalation:
            # Mark parent for human escalation
            record.metadata["escalation"] = True
            record.metadata["escalation_reason"] = specialist_result.escalation_reason
            record.status = "input_required"
        else:
            # Specialist failed — propagate failure
            record.status = specialist_result.status
            record.result = specialist_result.data

    def _find_graph_for_task(self, task_id: str) -> Optional[ConversationGraph]:
        """Find the conversation graph containing a task."""
        for graph in self._graphs.values():
            if graph.get_task(task_id) is not None:
                return graph
        return None
