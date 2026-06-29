"""HermesExecutor — translates A2A requests to Hermes sessions and back.

SDK-pure. No Hermes imports. Injected with dispatch function and
Fleet Controller at construction time.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    Message,
    Part,
    Role,
)

from core.domain.models.intent import TaskIntent
from core.domain.models.result import TaskResult
from core.domain.models.dispatch import ProfileDispatch
from core.domain.interfaces.fleet_controller import FleetController

# Signature of the injected dispatch function.
# Takes a goal string and optional profile name, returns a TaskResult.
DispatchFn = Callable[
    [str, Optional[str]],
    TaskResult,
]


class HermesExecutor(AgentExecutor):
    """Translates A2A requests into Hermes agent sessions via
    an injected dispatch function.

    The dispatch function is provided by the plugin at construction time
    and encapsulates the Hermes-specific session spawn logic. In tests,
    a mock dispatch function is used instead.

    When the FleetController routes to a remote node (``endpoint``
    starting with ``\"a2a://\"``), the executor delegates to an optional
    ``MeshPeerClient`` instead of calling the local dispatch function.

    When an ``orchestrator`` is provided, ``input_required`` results
    trigger the orchestrator to recruit a specialist sub-agent, compose
    the answer, and resume the blocked task.

    Args:
        dispatch_fn: A callable that accepts ``(goal, profile)`` and
            returns a ``TaskResult``. The plugin wires this to
            ``ctx.dispatch_tool(\"delegate_task\", ...)`` at startup.
        fc: A FleetController instance used for routing decisions and
            availability tracking.
        mesh_client: Optional ``MeshPeerClient`` for dispatching tasks
            to remote mesh peers. If ``None``, remote endpoints are
            treated as failures.
        orchestrator: Optional ``OrchestratorImpl`` for handling
            ``input_required`` status transitions by recruiting
            specialist sub-agents and resuming blocked tasks.
    """

    def __init__(
        self,
        dispatch_fn: DispatchFn,
        fc: FleetController,
        mesh_client: Any = None,
        orchestrator: Any = None,
        audit_logger: Any = None,
        node_id: str = "local",
        node_profile: str = "a2a-adapter",
    ) -> None:
        self._dispatch = dispatch_fn
        self._fc = fc
        self._mesh_client = mesh_client
        self._orchestrator = orchestrator
        self._audit_logger = audit_logger
        self._node_id = node_id
        self._node_profile = node_profile

    # ------------------------------------------------------------------
    # AgentExecutor contract
    # ------------------------------------------------------------------

    def _safe_log(self, event: str, **extra: Any) -> None:
        """Log an audit event, swallowing I/O errors.

        Prevents a disk-full or permissions error on the audit log from
        crashing the A2A handler. All ``audit_logger.log_event()`` calls
        go through this helper.

        Args:
            event: Event type name (e.g. ``"task_completed"``).
            **extra: Event-specific fields forwarded to the logger.
        """
        if not self._audit_logger:
            return
        try:
            self._audit_logger.log_event(event, **extra)
        except Exception:
            logger.exception("audit: failed to log event '%s'", event)

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Execute an A2A request through the Hermes dispatch pipeline.

        Flow:
        1. Translate ``RequestContext`` → ``TaskIntent``
        2. Route via ``FleetController.route()``
        3. If no route found: emit ``FAILED``, return
        4. If ``endpoint`` starts with ``\"a2a://\"``: dispatch via
           ``MeshPeerClient.send_task(intent)`` → ``TaskResult``
        5. Otherwise: call ``dispatch_fn(goal, profile)`` → ``TaskResult``
        6. Emit result ``Message`` + ``TaskStatusUpdateEvent``

        Args:
            context: The SDK request context.
            event_queue: The SDK event queue.
        """
        # 1. Translate
        intent = self.request_to_intent(context)

        # 2. Route
        dispatch = self._fc.route(intent)

        # 3. Check if routed successfully
        if not dispatch.is_successful:
            error_msg = (
                dispatch.message
                or f"No profile available for intent '{intent.intent_type}' "
                f"(status: {dispatch.status})"
            )
            await event_queue.enqueue_event(Message(
                message_id=str(uuid.uuid4()),
                task_id=context.task_id,
                context_id=context.context_id or "",
                role=Role.ROLE_AGENT,
                parts=[Part(text=error_msg)],
            ))
            # Audit: no route found
            _tid = context.task_id or "unknown"
            _cid = context.context_id or ""
            self._safe_log("task_submitted", task_id=_tid, context_id=_cid)
            self._safe_log(
                "task_failed", task_id=_tid, context_id=_cid,
                error=error_msg, reason="no_route",
            )
            return

        # 4. Dispatch — remote or local?
        is_remote = dispatch.endpoint.startswith("a2a://")
        goal = intent.payload.get("question", "")
        profile = dispatch.profile_name
        # Pre-compute task/context IDs for audit logging (needed before
        # the result-handling section below).
        _audit_tid = context.task_id or intent.context_id or "unknown"
        _audit_cid = context.context_id or ""
        self._safe_log("task_submitted", task_id=_audit_tid, context_id=_audit_cid)
        self._safe_log(
            "task_in_progress", task_id=_audit_tid, context_id=_audit_cid,
            profile=profile, is_remote=is_remote,
            source_node=intent.source_node,
            source_profile=intent.source_profile,
        )
        try:
            if is_remote:
                # Remote dispatch via mesh peer client
                if self._mesh_client is None:
                    raise RuntimeError(
                        "Remote dispatch required but no MeshPeerClient configured"
                    )
                result = await self._mesh_client.send_task(intent)
            else:
                # Local dispatch via Hermes AIAgent
                result = self._dispatch(goal, profile)
        except Exception as exc:
            await event_queue.enqueue_event(Message(
                message_id=str(uuid.uuid4()),
                task_id=context.task_id,
                context_id=context.context_id or "",
                role=Role.ROLE_AGENT,
                parts=[Part(text=f"Execution error: {exc}")],
            ))
            self._safe_log(
                "task_failed", task_id=_audit_tid, context_id=_audit_cid,
                error=str(exc),
            )
            # Release profile on exception
            self._fc.release(_audit_tid, profile)
            return

        # 5. Handle result — status transitions + orchestration
        task_id = context.task_id or intent.context_id or "unknown"
        context_id = context.context_id or ""

        if result.status == "input_required":
            # Emit INPUT_REQUIRED status — no final Message
            # The orchestrator will recruit a specialist and resume
            await self.emit_status_event(
                task_id, TaskState.TASK_STATE_INPUT_REQUIRED,
                event_queue,
            )
            self._safe_log(
                "task_in_progress", task_id=task_id, context_id=context_id,
                status="input_required",
            )
            if self._orchestrator:
                self._safe_log(
                    "orchestrator_recruit", task_id=task_id, context_id=context_id,
                    status="input_required",
                )
                self._orchestrator.on_status_change(
                    task_id, "input_required", result,
                )
            return

        # Emit terminal result — Message + status event
        if result.status == "completed":
            answer = ""
            if result.data and "answer" in result.data:
                answer = str(result.data["answer"])
            elif result.data:
                answer = str(result.data)

            if answer:
                await self.emit_message(
                    task_id, context_id,
                    [Part(text=answer)],
                    event_queue,
                )
            else:
                await self.emit_message(
                    task_id, context_id,
                    [Part(text="Task completed.")],
                    event_queue,
                )
            self._safe_log(
                "message_sent", task_id=task_id, context_id=context_id,
                role="agent",
            )
            # NOTE: Do NOT emit TaskStatusUpdateEvent here.
            # The first Message sets task_mode=False (message mode) in the
            # SDK's ActiveTaskConsumer. Emitting a TaskStatusUpdateEvent
            # after that raises InvalidAgentResponseError. The Message
            # alone is the correct terminal response in message mode.
            self._safe_log(
                "task_completed", task_id=task_id, context_id=context_id,
                status="completed",
            )
            # Release the profile so it can accept new tasks
            self._fc.release(task_id, profile)
        else:
            # FAILED, CANCELLED, or unknown
            status_text = result.error or f"Status: {result.status}"
            await self.emit_message(
                task_id, context_id,
                [Part(text=status_text)],
                event_queue,
            )
            self._safe_log(
                "message_sent", task_id=task_id, context_id=context_id,
                role="agent",
            )
            # NOTE: Same as above — no TaskStatusUpdateEvent in message mode.
            self._safe_log(
                "task_failed", task_id=task_id, context_id=context_id,
                status=result.status, error=result.error or "",
            )
            # Release the profile even on failure
            self._fc.release(task_id, profile)

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Cancel a running task.

        Emits a ``TaskStatusUpdateEvent`` with ``TASK_STATE_CANCELED``
        and a brief ``Message`` explaining the cancellation.

        Full Hermes session cancellation (killing the subagent process)
        requires the dispatch function to support a cancel counterpart.
        Until that's wired, this satisfies the A2A protocol contract by
        emitting the required events.

        Args:
            context: The request context containing the task ID to cancel.
            event_queue: The queue to publish the cancellation events to.
        """
        task_id = context.task_id or "unknown"
        context_id = context.context_id or ""

        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=task_id,
            status=TaskStatus(state=TaskState.TASK_STATE_CANCELED)),
        )
        await event_queue.enqueue_event(Message(
            message_id=str(uuid.uuid4()),
            task_id=task_id,
            context_id=context_id,
            role=Role.ROLE_AGENT,
            parts=[Part(text=f"Task {task_id} cancelled by user request.")],
        ))

        # Notify orchestrator if wired
        if self._orchestrator:
            self._orchestrator.on_status_change(
                task_id,
                "cancelled",
                TaskResult(status="cancelled", data={"message": "Cancelled by user request"}),
            )

        self._safe_log(
            "task_cancelled", task_id=task_id, context_id=context_id,
        )

    # ------------------------------------------------------------------
    # Translation helpers
    # ------------------------------------------------------------------

    def request_to_intent(
        self,
        request_context: RequestContext,
        source_node: str | None = None,
        source_profile: str | None = None,
    ) -> TaskIntent:
        """Translate an A2A ``RequestContext`` into a ``TaskIntent``.

        Intent type is derived from the message's parts using parts-based
        inference (``_derive_intent_type``) unless the message metadata
        contains an ``intent_type`` override.

        Args:
            request_context: The SDK request context.
            source_node: Node ID of this Hermes instance.
                Defaults to ``self._node_id``.
            source_profile: Profile name for the source field.
                Defaults to ``self._node_profile``.

        Returns:
            A ``TaskIntent`` ready for Fleet Controller routing.
        """
        source_node = source_node or self._node_id
        source_profile = source_profile or self._node_profile
        message = request_context.message
        parts = list(message.parts) if message else []

        # Metadata override — message.metadata is a google.protobuf.Struct
        metadata: dict[str, Any] = {}
        intent_type: str | None = None
        if message and message.HasField("metadata"):
            for key, value in message.metadata.fields.items():
                metadata[key] = _struct_value_to_python(value)
            intent_type = metadata.pop("intent_type", None)
            logger.info("a2a-debug: metadata=%s, target_profile=%s", metadata, metadata.get("target_profile"))
            logger.info("a2a-debug: metadata=%s, target_profile=%s", metadata, metadata.get("target_profile"))
        if not intent_type:
            intent_type = _derive_intent_type(parts)

        # Build payload from parts
        payload: dict[str, Any] = {"question": ""}
        for part in parts:
            if part.HasField("text"):
                payload["question"] = part.text
            if part.HasField("data"):
                from google.protobuf.json_format import MessageToDict
                payload["data"] = MessageToDict(
                    part.data, preserving_proto_field_name=True
                )
            if part.HasField("url"):
                file_info: dict[str, str | bytes] = {"url": part.url}
                if part.filename:
                    file_info["name"] = part.filename
                if part.media_type:
                    file_info["mime_type"] = part.media_type
                payload["file"] = file_info
            if part.HasField("raw"):
                file_info = {"raw": part.raw}
                if part.filename:
                    file_info["name"] = part.filename
                if part.media_type:
                    file_info["mime_type"] = part.media_type
                payload["file"] = file_info

        return TaskIntent(
            intent_type=intent_type,
            payload=payload,
            source_node=source_node,
            source_profile=source_profile,
            target_profile=metadata.pop("target_profile", None),  # allow caller to target a specific profile
            target_node=metadata.pop("target_node", None),
            context_id=request_context.context_id or "",
            reference_task_ids=list(message.reference_task_ids) if message else [],
            metadata=metadata,
        )

    def result_to_a2a_task(
        self,
        task_result: TaskResult,
        task_id: str,
        context_id: str,
    ) -> Task:
        """Translate a Hermes ``TaskResult`` into an A2A ``Task``.

        Args:
            task_result: The result from the Hermes session dispatch.
            task_id: The A2A task ID to use.
            context_id: The A2A context (conversation) ID.

        Returns:
            An A2A ``Task`` protobuf ready for the event queue.
        """
        state = _hermes_to_a2a_state(task_result.status)
        a2a_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=state),
        )

        # Map result data and messages as A2A parts
        parts: list[Part] = []

        if task_result.data:
            if isinstance(task_result.data, dict) and "answer" in task_result.data:
                parts.append(Part(text=str(task_result.data["answer"])))
            else:
                parts.append(Part(text=str(task_result.data)))

        if task_result.messages:
            for msg in task_result.messages:
                if isinstance(msg, dict):
                    content = msg.get("content") or msg.get("text") or str(msg)
                    parts.append(Part(text=str(content)))

        if task_result.artifacts:
            for artifact in task_result.artifacts:
                if isinstance(artifact, dict):
                    parts.append(Part(
                        text=artifact.get("content", ""),
                        metadata={"name": artifact.get("name", "")},
                    ))

        if parts:
            # Emit these as a message alongside the task
            pass  # handled by emit_status_event

        return a2a_task

    async def emit_status_event(
        self,
        task_id: str,
        state: TaskState.ValueType,
        event_queue: EventQueue,
        final: bool = False,
    ) -> None:
        """Emit a ``TaskStatusUpdateEvent`` to the event queue.

        The SDK's ``DefaultRequestHandlerV2`` picks this up and
        translates it into the appropriate A2A response.

        Args:
            task_id: The A2A task ID.
            state: The terminal or intermediate state.
            event_queue: The SDK event queue.
            final: Whether this is the final event for this task.
        """
        update = TaskStatusUpdateEvent(
            task_id=task_id,
            status=TaskStatus(state=state),
        )
        await event_queue.enqueue_event(update)

    async def emit_message(
        self,
        task_id: str,
        context_id: str,
        parts: list[Part],
        event_queue: EventQueue,
        role: Role.ValueType = Role.ROLE_AGENT,
    ) -> None:
        """Emit an A2A ``Message`` to the event queue.

        Args:
            task_id: The A2A task ID.
            context_id: The A2A context (conversation) ID.
            parts: The message parts to include.
            event_queue: The SDK event queue.
            role: The message role (default ``ROLE_AGENT``).
        """
        msg = Message(
            message_id=str(uuid.uuid4()),
            task_id=task_id,
            context_id=context_id,
            role=role,
            parts=parts,
        )
        await event_queue.enqueue_event(msg)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _derive_intent_type(parts: list) -> str:
    """Derive an A2A intent type from the message's parts.

    A ``Part`` is a oneof of ``text``, ``raw``, ``url``, ``data``.
    We check all parts in the message:

    - Any part with ``HasField('data')`` → ``"action_request"``
    - Any part with ``HasField('url')`` or ``HasField('raw')`` → ``"consultation"``
    - Any part with ``HasField('text')`` (or empty) → ``"consultation"``
    """
    for part in parts:
        if part.HasField("data"):
            return "action_request"

    has_text = False
    for part in parts:
        if part.HasField("url") or part.HasField("raw"):
            return "consultation"
        if part.HasField("text"):
            has_text = True

    if has_text or not parts:
        return "consultation"
    return "consultation"


def _hermes_to_a2a_state(hermes_status: str) -> TaskState.ValueType:
    """Map a Hermes ``TaskResult.status`` to an A2A ``TaskState``."""
    mapping: dict[str, TaskState.ValueType] = {
        "completed": TaskState.TASK_STATE_COMPLETED,
        "failed": TaskState.TASK_STATE_FAILED,
        "cancelled": TaskState.TASK_STATE_CANCELED,
        "input_required": TaskState.TASK_STATE_INPUT_REQUIRED,
    }
    return mapping.get(hermes_status, TaskState.TASK_STATE_FAILED)


def _default_dispatch(goal: str, profile: Optional[str]) -> TaskResult:
    """fallback dispatch for use when no real dispatch is wired.

    Raises RuntimeError if called. Exists so the executor can be
    constructed without a dispatch function for testing purposes.
    """
    raise RuntimeError(
        "No dispatch function configured. "
        "Wire one via HermesExecutor(dispatch_fn=...) at plugin startup."
    )


def _struct_value_to_python(value: Any) -> Any:
    """Convert a ``google.protobuf.Value`` to a native Python type.

    Handles nested structs, lists, strings, numbers, booleans, and null.
    """
    from google.protobuf.struct_pb2 import Value, ListValue, Struct

    if isinstance(value, Value):
        which = value.WhichOneof("kind")
        if which == "struct_value":
            return {
                k: _struct_value_to_python(v)
                for k, v in value.struct_value.fields.items()
            }
        if which == "list_value":
            return [
                _struct_value_to_python(v) for v in value.list_value.values
            ]
        if which == "string_value":
            return value.string_value
        if which == "number_value":
            return value.number_value
        if which == "bool_value":
            return value.bool_value
        if which == "null_value":
            return None
        return None

    if isinstance(value, Struct):
        return {
            k: _struct_value_to_python(v)
            for k, v in value.fields.items()
        }

    if isinstance(value, ListValue):
        return [_struct_value_to_python(v) for v in value.values]

    return value
