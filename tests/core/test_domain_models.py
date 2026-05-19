"""Tests for domain models — pure dataclass unit tests.

Zero infrastructure. No A2A imports. Millisecond execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from core.domain.models import (
    TaskIntent,
    TaskResult,
    AgentCapability,
    ProfileDispatch,
    TaskRecord,
    ConversationGraph,
)
from core.domain.models.result import TERMINAL_STATUSES, INTERRUPTED_STATUSES
from core.domain.models.dispatch import DISPATCH_STATUSES


# ---------------------------------------------------------------------------
# TaskIntent
# ---------------------------------------------------------------------------


class TestTaskIntent:
    def test_minimal_creation(self):
        """A TaskIntent can be created with only required fields."""
        intent = TaskIntent(intent_type="consultation", payload={"question": "test"})
        assert intent.intent_type == "consultation"
        assert intent.payload == {"question": "test"}

    def test_default_values(self):
        """Defaults are set correctly."""
        intent = TaskIntent(intent_type="action_request", payload={})
        assert intent.source_node == "local"
        assert intent.source_profile == "orchestrator"
        assert intent.target_profile is None
        assert intent.target_node is None
        assert intent.context_id is None
        assert intent.reference_task_ids == []
        assert intent.metadata == {}

    def test_full_creation(self):
        """All fields can be set at creation."""
        intent = TaskIntent(
            intent_type="review",
            payload={"artifact": "/tmp/test.tar.gz"},
            target_profile="reviewer",
            target_node="100.96.0.2",
            source_node="100.96.0.1",
            source_profile="orchestrator",
            context_id="ctx-abc-123",
            reference_task_ids=["task/ray-456"],
            metadata={"priority": "high"},
        )
        assert intent.target_profile == "reviewer"
        assert intent.target_node == "100.96.0.2"
        assert intent.context_id == "ctx-abc-123"
        assert intent.reference_task_ids == ["task/ray-456"]

    def test_default_factory_independence(self):
        """Each instance gets its own mutable default list."""
        a = TaskIntent(intent_type="test", payload={})
        b = TaskIntent(intent_type="test", payload={})
        a.reference_task_ids.append("task-1")
        assert len(b.reference_task_ids) == 0


# ---------------------------------------------------------------------------
# TaskResult
# ---------------------------------------------------------------------------


class TestTaskResult:
    def test_valid_statuses(self):
        """All valid statuses can be set."""
        for status in TERMINAL_STATUSES | INTERRUPTED_STATUSES:
            result = TaskResult(status=status)
            assert result.status == status

    def test_invalid_status_raises(self):
        """An invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            TaskResult(status="not_a_status")

    def test_is_terminal(self):
        """is_terminal reflects terminal statuses."""
        for status in TERMINAL_STATUSES:
            assert TaskResult(status=status).is_terminal
        for status in INTERRUPTED_STATUSES:
            assert not TaskResult(status=status).is_terminal

    def test_requires_input(self):
        """requires_input reflects interrupted statuses."""
        for status in INTERRUPTED_STATUSES:
            assert TaskResult(status=status).requires_input
        for status in TERMINAL_STATUSES:
            assert not TaskResult(status=status).requires_input

    def test_artifacts_defaults(self):
        """messages and artifacts are empty by default."""
        result = TaskResult(status="completed")
        assert result.messages == []
        assert result.artifacts == []

    def test_completed_with_data(self):
        """A completed result carries data."""
        result = TaskResult(
            status="completed",
            data={"answer": "42"},
            artifacts=[{"name": "report", "content": "...", "media_type": "text"}],
        )
        assert result.data == {"answer": "42"}
        assert len(result.artifacts) == 1

    def test_failed_with_error(self):
        """A failed result carries an error message."""
        result = TaskResult(status="failed", error="Timeout connecting to upstream")
        assert result.error is not None
        assert "Timeout" in result.error

    def test_input_required_carrying_question(self):
        """input_required carries the question in data."""
        result = TaskResult(
            status="input_required",
            data={"question": "What port is nginx running on?"},
        )
        assert result.requires_input
        assert result.data["question"] is not None

    def test_escalation_flag(self):
        """requires_escalation can be set with a reason."""
        result = TaskResult(
            status="input_required",
            requires_escalation=True,
            escalation_reason="Need human to check physical server LED",
        )
        assert result.requires_escalation
        assert "LED" in result.escalation_reason


# ---------------------------------------------------------------------------
# AgentCapability
# ---------------------------------------------------------------------------


class TestAgentCapability:
    def test_minimal_creation(self):
        cap = AgentCapability(
            profile_name="ray",
            node_id="100.96.0.2",
            display_name="System Diagnostician",
            description="Root cause diagnostics",
        )
        assert cap.profile_name == "ray"
        assert cap.intents == []
        assert cap.tags == []
        assert cap.input_modes == ["text", "application/json"]

    def test_can_handle_intent_exact_match(self):
        cap = AgentCapability(
            profile_name="reviewer",
            node_id="100.96.0.2",
            display_name="Reviewer",
            description="Verification and quality checks",
            intents=["review", "audit"],
            tags=["verify", "check"],
        )
        assert cap.can_handle("review")
        assert cap.can_handle("audit")

    def test_can_handle_tag_fallback(self):
        cap = AgentCapability(
            profile_name="ray",
            node_id="100.96.0.2",
            display_name="Diagnostician",
            description="Diagnostics",
            intents=["consultation"],
            tags=["diagnosis", "linux", "nginx"],
        )
        # tag fallback
        assert cap.can_handle("action_request", tags=["diagnosis"])
        # no match
        assert not cap.can_handle("deploy")
        assert not cap.can_handle("deploy", tags=["frontend"])

    def test_can_handle_no_tags(self):
        """When no tags provided, only intent_type is matched."""
        cap = AgentCapability(
            profile_name="ops",
            node_id="100.96.0.2",
            display_name="Operations",
            description="Deployments and config",
            intents=["action_request"],
            tags=["deploy", "config"],
        )
        assert cap.can_handle("action_request")
        assert not cap.can_handle("deploy")  # Not in intents, tags not checked

    def test_default_modes(self):
        cap = AgentCapability(
            profile_name="test",
            node_id="local",
            display_name="Test",
            description="Test",
        )
        assert cap.input_modes == ["text", "application/json"]
        assert cap.output_modes == ["text", "application/json"]
        assert not cap.supports_streaming
        assert not cap.supports_push


# ---------------------------------------------------------------------------
# ProfileDispatch
# ---------------------------------------------------------------------------


class TestProfileDispatch:
    def test_minimal_creation(self):
        dispatch = ProfileDispatch(
            task_id="task-1",
            profile_name="ray",
            node_address="local",
            endpoint="internal:ray",
            status="dispatched",
        )
        assert dispatch.task_id == "task-1"
        assert dispatch.is_successful

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid dispatch status"):
            ProfileDispatch(
                task_id="task-1",
                profile_name="ray",
                node_address="local",
                endpoint="internal:ray",
                status="pending",
            )

    def test_unavailable_status(self):
        dispatch = ProfileDispatch(
            task_id="task-2",
            profile_name="ray",
            node_address="local",
            endpoint="internal:ray",
            status="unavailable",
            message="Ray is currently diagnosing another issue",
        )
        assert not dispatch.is_successful
        assert dispatch.status == "unavailable"

    def test_all_dispatch_statuses_valid(self):
        for status in DISPATCH_STATUSES:
            dispatch = ProfileDispatch(
                task_id="task-x",
                profile_name="p",
                node_address="local",
                endpoint="internal:p",
                status=status,
            )
            assert dispatch.status == status


# ---------------------------------------------------------------------------
# TaskRecord
# ---------------------------------------------------------------------------


class TestTaskRecord:
    def test_minimal_creation(self):
        record = TaskRecord(
            task_id="task/ray-456",
            context_id="ctx-abc-123",
            status="submitted",
            intent_type="diagnose",
            source_node="100.96.0.2",
            target_profile="ray",
            target_node="local",
            payload={"symptoms": "502 upstream timeout"},
        )
        assert record.task_id == "task/ray-456"
        assert not record.terminal  # 'submitted' is not terminal
        assert isinstance(record.created_at, datetime)

    def test_terminal_auto_set(self):
        record = TaskRecord(
            task_id="task/ray-456",
            context_id="ctx-abc-123",
            status="completed",
            intent_type="diagnose",
            source_node="local",
            target_profile="ray",
            target_node="local",
            payload={},
        )
        assert record.terminal is True

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status"):
            TaskRecord(
                task_id="task/bad",
                context_id="ctx-bad",
                status="unknown_status",
                intent_type="test",
                source_node="local",
                target_profile="t",
                target_node="local",
                payload={},
            )

    def test_default_collections(self):
        record = TaskRecord(
            task_id="t1",
            context_id="c1",
            status="working",
            intent_type="consultation",
            source_node="local",
            target_profile="odin",
            target_node="100.96.0.1",
            payload={},
        )
        assert record.messages == []
        assert record.artifacts == []
        assert record.reference_task_ids == []
        assert record.metadata == {}


# ---------------------------------------------------------------------------
# ConversationGraph
# ---------------------------------------------------------------------------


class TestConversationGraph:
    def test_root_task_added(self):
        root = TaskRecord(
            task_id="task/root-1",
            context_id="ctx-orch-1",
            status="submitted",
            intent_type="diagnose",
            source_node="local",
            target_profile="ray",
            target_node="local",
            payload={},
        )
        graph = ConversationGraph(context_id="ctx-orch-1", root_task_id="task/root-1")
        graph.add_task(root)
        assert graph.get_task("task/root-1") is root

    def test_adding_child_task(self):
        graph = _make_orchestration_graph()
        # Verify child was added
        child = graph.get_task("task/odin-research")
        assert child is not None
        assert "pacman" in str(child.payload)

    def test_get_children(self):
        graph = _make_orchestration_graph()
        children = graph.get_children("task/ray-diagnose")
        assert len(children) == 1
        assert children[0].task_id == "task/odin-research"

    def test_get_tree_structure(self):
        graph = _make_orchestration_graph()
        tree = graph.get_tree()
        assert tree["context_id"] == "ctx-orch-1"
        assert tree["root_task_id"] == "task/ray-diagnose"
        assert len(tree["tasks"]) == 1
        root_node = tree["tasks"][0]
        assert root_node["task_id"] == "task/ray-diagnose"
        assert "children" in root_node
        assert len(root_node["children"]) == 1
        assert root_node["children"][0]["task_id"] == "task/odin-research"

    def test_context_id_mismatch_raises(self):
        graph = ConversationGraph(context_id="ctx-orch-1", root_task_id="task/root-1")
        wrong = TaskRecord(
            task_id="task/wrong",
            context_id="ctx-different",
            status="submitted",
            intent_type="test",
            source_node="local",
            target_profile="t",
            target_node="local",
            payload={},
        )
        with pytest.raises(ValueError, match="does not match"):
            graph.add_task(wrong)

    def test_missing_root_in_tree(self):
        graph = ConversationGraph(context_id="ctx-orphan", root_task_id="task/ghost")
        tree = graph.get_tree()
        assert "error" in tree

    def test_get_task_nonexistent(self):
        graph = ConversationGraph(context_id="ctx-1", root_task_id="task/r")
        assert graph.get_task("does-not-exist") is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestration_graph() -> ConversationGraph:
    """Create a realistic orchestration flow for testing.

    Mirrors the example from the orchestration patterns doc:
    Ray diagnoses → hits knowledge gap → Odin researches → answer flows back
    """
    root = TaskRecord(
        task_id="task/ray-diagnose",
        context_id="ctx-orch-1",
        status="input_required",
        intent_type="diagnose",
        source_node="100.96.0.2",
        target_profile="ray",
        target_node="local",
        payload={
            "symptoms": "Arch Linux, need equivalent of apt install nginx",
        },
    )
    child = TaskRecord(
        task_id="task/odin-research",
        context_id="ctx-orch-1",
        status="completed",
        intent_type="consultation",
        source_node="100.96.0.2",
        target_profile="odin",
        target_node="100.96.0.1",
        payload={"question": "pacman equivalent of apt install nginx?"},
        reference_task_ids=["task/ray-diagnose"],
        result={"answer": "pacman -S nginx"},
    )

    graph = ConversationGraph(context_id="ctx-orch-1", root_task_id="task/ray-diagnose")
    graph.add_task(root)
    graph.add_task(child)
    return graph
