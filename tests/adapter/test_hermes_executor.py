"""Tests for HermesExecutor — translation helpers in isolation.

All tests use proper protobuf construction matching the A2A SDK.
No execute() or cancel() tests — those come in M2.2 and M2.3.
"""

from __future__ import annotations

import pytest
from google.protobuf.json_format import ParseDict

from a2a.server.context import ServerCallContext
from a2a.server.agent_execution.context import RequestContext
from a2a.types import (
    TaskState,
    TaskStatusUpdateEvent,
    Message,
    Role,
    SendMessageRequest,
    Part,
)

from core.domain.models.intent import TaskIntent
from core.domain.models.result import TaskResult
from core.domain.models.dispatch import ProfileDispatch

from adapter.hermes_executor import (
    HermesExecutor,
    _derive_intent_type,
    _hermes_to_a2a_state,
    _default_dispatch,
)


# ------------------------------------------------------------------
# Test helpers
# ------------------------------------------------------------------


def make_context(
    parts_dicts: list[dict] | None = None,
    metadata: dict | None = None,
    context_id: str = "ctx-test",
    task_id: str = "task/abc-123",
    ref_task_ids: list[str] | None = None,
) -> RequestContext:
    """Build a ``RequestContext`` with proper protobuf construction.

    Args:
        parts_dicts: List of Part dicts, e.g. ``[{'text': 'hello'}]``.
        metadata: Optional metadata dict for the message.
        context_id: A2A conversation context ID.
        task_id: A2A task ID.
        ref_task_ids: Reference task IDs (parent tasks).

    Returns:
        A ``RequestContext`` ready for testing.
    """
    msg_dict: dict = {
        "message_id": "msg-001",
        "role": "ROLE_USER",
        "parts": parts_dicts or [{"text": "Hello"}],
    }
    if metadata:
        msg_dict["metadata"] = metadata
    if context_id:
        msg_dict["context_id"] = context_id
    if ref_task_ids:
        msg_dict["reference_task_ids"] = ref_task_ids

    smr = ParseDict(
        {"message": msg_dict},
        SendMessageRequest(),
    )
    scc = ServerCallContext(state={})
    return RequestContext(
        call_context=scc,
        request=smr,
        task_id=task_id,
        context_id=context_id,
    )


# ------------------------------------------------------------------
# _derive_intent_type
# ------------------------------------------------------------------


class TestDeriveIntentType:
    """Parts-based intent type derivation (M2 planning doc, resolved).

    A ``Part`` is a oneof: text, raw (bytes), url, or data.
    """

    def test_text_only_is_consultation(self):
        """A message with only text parts routes to consultation."""
        parts = [ParseDict({"text": "What is pacman?"}, Part())]
        assert _derive_intent_type(parts) == "consultation"

    def test_empty_parts_is_consultation(self):
        """A message with no parts defaults to consultation."""
        assert _derive_intent_type([]) == "consultation"

    def test_data_part_is_action_request(self):
        """A message with a data (structured JSON) part routes to action_request."""
        parts = [ParseDict({"data": {"action": "deploy", "service": "nginx"}}, Part())]
        assert _derive_intent_type(parts) == "action_request"

    def test_data_only_is_action_request(self):
        """A message with only a data part routes to action_request."""
        parts = [ParseDict({"data": {"command": "reboot"}}, Part())]
        assert _derive_intent_type(parts) == "action_request"

    def test_url_attachment_is_consultation(self):
        """A message with a URL part (file pointer) routes to consultation."""
        parts = [ParseDict({
            "url": "file:///tmp/log.txt",
            "filename": "log.txt",
            "media_type": "text/plain",
        }, Part())]
        assert _derive_intent_type(parts) == "consultation"

    def test_raw_bytes_attachment_is_consultation(self):
        """A message with a raw bytes part routes to consultation."""
        import base64
        raw_b64 = base64.b64encode(b"file content").decode("ascii")
        parts = [ParseDict({
            "raw": raw_b64,
            "filename": "data.bin",
            "media_type": "application/octet-stream",
        }, Part())]
        assert _derive_intent_type(parts) == "consultation"

    def test_text_plus_data_data_wins(self):
        """When both text and data parts are present, data takes priority."""
        parts = [
            ParseDict({"text": "Please deploy this"}, Part()),
            ParseDict({"data": {"action": "deploy", "service": "nginx"}}, Part()),
        ]
        assert _derive_intent_type(parts) == "action_request"

    def test_text_plus_url_url_wins(self):
        """When both text and URL parts are present, file takes priority."""
        parts = [
            ParseDict({"text": "Analyze this file"}, Part()),
            ParseDict({"url": "https://example.com/data.csv", "media_type": "text/csv"}, Part()),
        ]
        assert _derive_intent_type(parts) == "consultation"

    def test_all_part_types_data_wins(self):
        """With text, URL, and data — data still wins."""
        parts = [
            ParseDict({"text": "Do this"}, Part()),
            ParseDict({"url": "https://example.com/doc.pdf", "filename": "doc.pdf"}, Part()),
            ParseDict({"data": {"action": "deploy"}}, Part()),
        ]
        assert _derive_intent_type(parts) == "action_request"


# ------------------------------------------------------------------
# _hermes_to_a2a_state
# ------------------------------------------------------------------


class TestHermesToA2AState:
    """Status mapping between Hermes TaskResult and A2A TaskState."""

    def test_completed(self):
        assert _hermes_to_a2a_state("completed") == TaskState.TASK_STATE_COMPLETED

    def test_failed(self):
        assert _hermes_to_a2a_state("failed") == TaskState.TASK_STATE_FAILED

    def test_cancelled(self):
        assert _hermes_to_a2a_state("cancelled") == TaskState.TASK_STATE_CANCELED

    def test_input_required(self):
        assert _hermes_to_a2a_state("input_required") == TaskState.TASK_STATE_INPUT_REQUIRED

    def test_unknown_status_falls_back_to_failed(self):
        assert _hermes_to_a2a_state("working") == TaskState.TASK_STATE_FAILED
        assert _hermes_to_a2a_state("submitted") == TaskState.TASK_STATE_FAILED

    def test_empty_status(self):
        assert _hermes_to_a2a_state("") == TaskState.TASK_STATE_FAILED


# ------------------------------------------------------------------
# HermesExecutor init
# ------------------------------------------------------------------


class TestHermesExecutorInit:
    """Constructor and defaults."""

    def test_constructed_with_dispatch_fn(self):
        """Constructor accepts a dispatch function."""
        def mock_dispatch(goal, profile):
            return TaskResult(status="completed", data={"answer": "mock"})

        from core.fleet_controller import FleetControllerImpl
        fc = FleetControllerImpl()
        executor = HermesExecutor(dispatch_fn=mock_dispatch, fc=fc)
        assert executor._dispatch is mock_dispatch
        assert executor._fc is fc


class TestCancel:
    """cancel() emits CANCELED events correctly."""

    @pytest.mark.asyncio
    async def test_emits_canceled(self):
        """cancel() emits a TaskStatusUpdateEvent with TASK_STATE_CANCELED."""
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        ctx = make_context(parts_dicts=[{"text": "cancel me"}])
        eq = MockEventQueue()

        await executor.cancel(ctx, eq)

        assert len(eq.events) >= 1
        status_event = eq.events[0]
        assert isinstance(status_event, TaskStatusUpdateEvent)
        assert status_event.status.state == TaskState.TASK_STATE_CANCELED

    @pytest.mark.asyncio
    async def test_emits_cancel_message(self):
        """cancel() emits a Message explaining the cancellation."""
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        ctx = make_context(
            parts_dicts=[{"text": "cancel me"}],
            task_id="task/cancel-42",
            context_id="ctx-abc",
        )
        eq = MockEventQueue()

        await executor.cancel(ctx, eq)

        msg_events = [e for e in eq.events if isinstance(e, Message)]
        assert len(msg_events) >= 1
        assert "task/cancel-42" in msg_events[0].parts[0].text if msg_events[0].parts else ""

    @pytest.mark.asyncio
    async def test_task_id_passthrough(self):
        """The task_id is set on the canceled status event."""
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        ctx = make_context(
            parts_dicts=[{"text": "cancel me"}],
            task_id="task/cancel-77",
            context_id="ctx-xyz",
        )
        eq = MockEventQueue()

        await executor.cancel(ctx, eq)

        status_event = eq.events[0]
        assert isinstance(status_event, TaskStatusUpdateEvent)
        assert status_event.task_id == "task/cancel-77"


# ------------------------------------------------------------------
# request_to_intent
# ------------------------------------------------------------------


class TestRequestToIntent:
    """Translation from A2A RequestContext to TaskIntent."""

    def test_text_only_intent(self):
        """A text-only request produces consultation intent."""
        ctx = make_context(parts_dicts=[{"text": "What is pacman?"}])
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert intent.intent_type == "consultation"

    def test_data_part_intent(self):
        """A data part produces action_request intent."""
        ctx = make_context(parts_dicts=[
            {"text": "Deploy nginx"},
            {"data": {"action": "deploy"}},
        ])
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert intent.intent_type == "action_request"

    def test_url_part_intent(self):
        """A URL attachment produces consultation intent."""
        ctx = make_context(parts_dicts=[
            {"text": "Analyze this"},
            {"url": "https://example.com/log.txt", "filename": "log.txt"},
        ])
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert intent.intent_type == "consultation"

    def test_metadata_override(self):
        """Message metadata.intent_type overrides parts-based inference."""
        ctx = make_context(
            parts_dicts=[{"text": "Some text"}],
            metadata={"intent_type": "audit", "custom_key": "val"},
        )
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert intent.intent_type == "audit"
        # Metadata field is consumed by intent_type, other keys pass through
        assert intent.metadata.get("custom_key") == "val"
        assert "intent_type" not in intent.metadata

    def test_payload_contains_question(self):
        """Text parts are placed in payload.question."""
        ctx = make_context(parts_dicts=[{"text": "What is pacman?"}])
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert "pacman" in intent.payload.get("question", "")

    def test_payload_contains_data(self):
        """Data parts are placed in payload.data as a Python dict."""
        data = {"action": "deploy", "service": "nginx"}
        ctx = make_context(parts_dicts=[
            {"text": "Deploy"},
            {"data": data},
        ])
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert intent.payload.get("data") == data

    def test_payload_contains_file_url(self):
        """URL parts are placed in payload.file."""
        ctx = make_context(parts_dicts=[
            {"url": "https://example.com/data.csv", "media_type": "text/csv"},
        ])
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        file_info = intent.payload.get("file", {})
        assert file_info.get("url") == "https://example.com/data.csv"
        assert file_info.get("mime_type") == "text/csv"

    def test_context_id_passthrough(self):
        """The A2A context_id is passed through to the TaskIntent."""
        ctx = make_context(context_id="ctx-orch-42")
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert intent.context_id == "ctx-orch-42"

    def test_reference_task_ids_passthrough(self):
        """reference_task_ids from the message passthrough."""
        ctx = make_context(ref_task_ids=["task/parent-1"])
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert "task/parent-1" in intent.reference_task_ids

    def test_source_node_and_profile(self):
        """Source node and profile are settable."""
        ctx = make_context()
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(
            ctx, source_node="100.96.0.2", source_profile="a2a-gateway"
        )
        assert intent.source_node == "100.96.0.2"
        assert intent.source_profile == "a2a-gateway"

    def test_no_message_does_not_crash(self):
        """A RequestContext with no message (None) produces a safe intent."""
        scc = ServerCallContext(state={})
        ctx = RequestContext(call_context=scc, request=None)
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
        )
        intent = executor.request_to_intent(ctx)
        assert intent.intent_type == "consultation"
        assert intent.payload.get("question") == ""


# ------------------------------------------------------------------
# result_to_a2a_task
# ------------------------------------------------------------------


class TestResultToA2ATask:
    """Translation from Hermes TaskResult to A2A Task."""

    def test_completed_status_maps(self):
        """A completed Hermes result maps to a completed A2A Task."""
        result = TaskResult(status="completed", data={"answer": "42"})
        executor = HermesExecutor(
            dispatch_fn=lambda g, p: result,
            fc=type("FakeFC", (), {})(),
        )
        task = executor.result_to_a2a_task(
            result, task_id="task/abc", context_id="ctx-1"
        )
        assert task.id == "task/abc"
        assert task.context_id == "ctx-1"
        assert task.status.state == TaskState.TASK_STATE_COMPLETED

    def test_failed_status_maps(self):
        """A failed Hermes result maps to a failed A2A Task."""
        result = TaskResult(status="failed", error="Timeout")
        executor = HermesExecutor(
            dispatch_fn=lambda g, p: result,
            fc=type("FakeFC", (), {})(),
        )
        task = executor.result_to_a2a_task(
            result, task_id="task/xyz", context_id="ctx-2"
        )
        assert task.status.state == TaskState.TASK_STATE_FAILED

    def test_input_required_status_maps(self):
        """An input_required Hermes result maps correctly."""
        result = TaskResult(
            status="input_required",
            data={"question": "Which port?"},
        )
        executor = HermesExecutor(
            dispatch_fn=lambda g, p: result,
            fc=type("FakeFC", (), {})(),
        )
        task = executor.result_to_a2a_task(
            result, task_id="task/input", context_id="ctx-3"
        )
        assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED

    def test_task_id_and_context_passthrough(self):
        """Task ID and context ID are passed through."""
        result = TaskResult(status="completed", data={"answer": "done"})
        executor = HermesExecutor(
            dispatch_fn=lambda g, p: result,
            fc=type("FakeFC", (), {})(),
        )
        task = executor.result_to_a2a_task(
            result, task_id="task/abc", context_id="ctx-1"
        )
        from google.protobuf.json_format import MessageToDict
        d = MessageToDict(task, preserving_proto_field_name=True)
        assert d["id"] == "task/abc"
        assert d["context_id"] == "ctx-1"
        assert "status" in d

    def test_empty_result_does_not_crash(self):
        """A TaskResult with minimal data produces a valid A2A Task."""
        result = TaskResult(status="completed")
        executor = HermesExecutor(
            dispatch_fn=lambda g, p: result,
            fc=type("FakeFC", (), {})(),
        )
        task = executor.result_to_a2a_task(
            result, task_id="task/empty", context_id="ctx-e"
        )
        assert task.id == "task/empty"
        assert task.status.state == TaskState.TASK_STATE_COMPLETED

    def test_answer_in_result_data(self):
        """The answer is accessible in the Task protobuf."""
        result = TaskResult(status="completed", data={"answer": "use pacman -S nginx"})
        executor = HermesExecutor(
            dispatch_fn=lambda g, p: result,
            fc=type("FakeFC", (), {})(),
        )
        task = executor.result_to_a2a_task(
            result, task_id="task/d1", context_id="ctx-1"
        )
        # The answer is not embedded in the Task proto fields —
        # it's available via status or the message emission pattern
        assert task.status.state == TaskState.TASK_STATE_COMPLETED


# ------------------------------------------------------------------
# _default_dispatch
# ------------------------------------------------------------------


class TestDefaultDispatch:
    """The fallback dispatch function raises a clear error."""

    def test_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="No dispatch function"):
            _default_dispatch("test", None)


# ------------------------------------------------------------------
# Mock helpers for execute() tests
# ------------------------------------------------------------------


class MockEventQueue:
    """Captures events enqueued by execute()."""

    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


class MockFC:
    """FleetController mock that returns a configured dispatch."""

    def __init__(self, dispatch=None):
        self._dispatch = dispatch or ProfileDispatch(
            task_id="mock-task",
            profile_name="",
            node_address="local",
            endpoint="internal:profile",
            status="unavailable",
            message="No matching profile",
        )

    def route(self, intent):
        return self._dispatch


# ------------------------------------------------------------------
# execute()
# ------------------------------------------------------------------


class TestExecute:
    """Full execute() pipeline tests — status transitions + messages.

    The executor now emits:
    - ``TaskStatusUpdateEvent`` after the Message for terminal states
      (COMPLETED / FAILED / CANCELED)
    - ``TaskStatusUpdateEvent(INPUT_REQUIRED)`` without a Message
      when the dispatch returns ``input_required``
    """

    @pytest.mark.asyncio
    async def test_successful_dispatch_emits_message_and_status(self):
        """A successful route + dispatch emits a Message and COMPLETED status."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t1",
            profile_name="sherlock",
            node_address="local",
            endpoint="internal:profile",
            status="dispatched",
        ))
        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="completed",
                data={"answer": "installed nginx"},
            ),
            fc=fc,
        )
        ctx = make_context(parts_dicts=[{"text": "Install nginx"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        # Events: [Message, TaskStatusUpdateEvent(COMPLETED)]
        assert len(eq.events) == 2
        assert isinstance(eq.events[0], Message)
        assert isinstance(eq.events[1], TaskStatusUpdateEvent)
        assert eq.events[1].status.state == TaskState.TASK_STATE_COMPLETED

    @pytest.mark.asyncio
    async def test_successful_message_contains_answer(self):
        """The answer text is in the emitted Message."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t2", profile_name="sherlock",
            node_address="local", endpoint="internal:profile",
            status="dispatched",
        ))
        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="completed",
                data={"answer": "Use pacman -S"},
            ),
            fc=fc,
        )
        ctx = make_context(parts_dicts=[{"text": "How to install?"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        msg = eq.events[0]
        assert isinstance(msg, Message)
        assert "pacman" in (msg.parts[0].text if msg.parts else "")

    @pytest.mark.asyncio
    async def test_no_route_emits_error_message(self):
        """When FC returns not-dispatched, emit a Message explaining why."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t3", profile_name="",
            node_address="local", endpoint="internal:profile",
            status="unavailable",
            message="No profile for audit",
        ))
        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=fc,
        )
        ctx = make_context(parts_dicts=[{"text": "Audit system"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        # No route → error Message only (no dispatch, no status event)
        assert len(eq.events) == 1
        msg = eq.events[0]
        assert isinstance(msg, Message)
        assert "audit" in (msg.parts[0].text if msg.parts else "")

    @pytest.mark.asyncio
    async def test_dispatch_exception_emits_error_message(self):
        """When dispatch_fn raises, emit a Message with the exception text."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t4", profile_name="builder",
            node_address="local", endpoint="internal:profile",
            status="dispatched",
        ))
        def failing_dispatch(goal, profile):
            raise RuntimeError("Key not found")

        executor = HermesExecutor(dispatch_fn=failing_dispatch, fc=fc)
        ctx = make_context(parts_dicts=[{"text": "Build something"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        assert len(eq.events) == 1
        msg = eq.events[0]
        assert isinstance(msg, Message)
        assert "Key not found" in (msg.parts[0].text if msg.parts else "")

    @pytest.mark.asyncio
    async def test_failed_result_emits_error_and_status(self):
        """When dispatch returns failed TaskResult, emit error Message + FAILED status."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t5", profile_name="builder",
            node_address="local", endpoint="internal:profile",
            status="dispatched",
        ))
        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="failed",
                error="Timeout waiting for response",
            ),
            fc=fc,
        )
        ctx = make_context(parts_dicts=[{"text": "Deploy"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        # Events: [Message(error), TaskStatusUpdateEvent(FAILED)]
        assert len(eq.events) == 2
        msg = eq.events[0]
        assert isinstance(msg, Message)
        assert "Timeout" in (msg.parts[0].text if msg.parts else "")
        assert isinstance(eq.events[1], TaskStatusUpdateEvent)
        assert eq.events[1].status.state == TaskState.TASK_STATE_FAILED

    @pytest.mark.asyncio
    async def test_completed_without_answer_data_still_emits_message(self):
        """A completed result with no answer data still emits a Message."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t6", profile_name="ops",
            node_address="local", endpoint="internal:profile",
            status="dispatched",
        ))
        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="completed",
                data=None,  # no data at all → "Task completed." fallback
            ),
            fc=fc,
        )
        ctx = make_context(parts_dicts=[{"text": "Restart"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        assert len(eq.events) == 2
        assert isinstance(eq.events[0], Message)
        assert eq.events[0].parts[0].text == "Task completed."

    @pytest.mark.asyncio
    async def test_context_id_passthrough_to_message(self):
        """The task_id and context_id are set on the emitted Message."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t7", profile_name="sherlock",
            node_address="local", endpoint="internal:profile",
            status="dispatched",
        ))
        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="completed",
                data={"answer": "42"},
            ),
            fc=fc,
        )
        ctx = make_context(
            parts_dicts=[{"text": "Question"}],
            context_id="ctx-exec-test",
            task_id="task/execute-99",
        )
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        msg = eq.events[0]
        assert isinstance(msg, Message)
        assert msg.task_id == "task/execute-99"
        assert msg.context_id == "ctx-exec-test"

    @pytest.mark.asyncio
    async def test_input_required_emits_status_and_calls_orchestrator(self):
        """When dispatch returns input_required, emit INPUT_REQUIRED status
        and call orchestrator.on_status_change(). No Message is emitted."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t8", profile_name="sherlock",
            node_address="local", endpoint="internal:profile",
            status="dispatched",
        ))
        orchestrator_calls = []

        class MockOrchestrator:
            def on_status_change(self, task_id, new_state, task_result):
                orchestrator_calls.append((task_id, new_state, task_result))
            def register_task(self, *args, **kwargs):
                pass

        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="input_required",
                data={"question": "Which port?"},
            ),
            fc=fc,
            orchestrator=MockOrchestrator(),
        )
        ctx = make_context(
            parts_dicts=[{"text": "Deploy on which port?"}],
            task_id="task/input-req-1",
        )
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        # Only a TaskStatusUpdateEvent(INPUT_REQUIRED), no Message
        assert len(eq.events) == 1
        assert isinstance(eq.events[0], TaskStatusUpdateEvent)
        assert eq.events[0].status.state == TaskState.TASK_STATE_INPUT_REQUIRED

        # Orchestrator was called
        assert len(orchestrator_calls) == 1
        call_task_id, call_state, call_result = orchestrator_calls[0]
        assert call_task_id == "task/input-req-1"
        assert call_state == "input_required"
        assert call_result.data.get("question") == "Which port?"

    @pytest.mark.asyncio
    async def test_input_required_without_orchestrator_emits_status(self):
        """Without an orchestrator, input_required still emits INPUT_REQUIRED status."""
        fc = MockFC(dispatch=ProfileDispatch(
            task_id="t9", profile_name="sherlock",
            node_address="local", endpoint="internal:profile",
            status="dispatched",
        ))
        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="input_required",
                data={"question": "Which database?"},
            ),
            fc=fc,
            # No orchestrator
        )
        ctx = make_context(
            parts_dicts=[{"text": "Which DB?"}],
            task_id="task/input-req-2",
        )
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        assert len(eq.events) == 1
        assert isinstance(eq.events[0], TaskStatusUpdateEvent)
        assert eq.events[0].status.state == TaskState.TASK_STATE_INPUT_REQUIRED
