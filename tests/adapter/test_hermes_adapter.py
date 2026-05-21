"""Tests for HermesA2AAdapter — A2AAdapter implementation.

Covers local dispatch, remote dispatch (mesh), cancellation, capability
listing, and sync↔async bridging.
"""

from __future__ import annotations

import pytest

from core.domain.models.capability import AgentCapability
from core.domain.models.intent import TaskIntent
from core.domain.models.result import TaskResult

from adapter.hermes_adapter import HermesA2AAdapter


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mock_dispatch():
    """A dispatch function that returns predictable results."""
    def dispatch(goal: str, profile: str | None = None) -> TaskResult:
        return TaskResult(
            status="completed",
            data={"answer": f"processed: {goal} via {profile or 'default'}"},
        )
    return dispatch


@pytest.fixture
def mock_fc():
    """A minimal FleetController-like object for capabilities."""
    class MockFC:
        def discover(self, intent_type, tags=None):
            return [
                AgentCapability(
                    profile_name="sherlock",
                    node_id="local",
                    display_name="Diagnostician",
                    description="System diagnostics",
                    intents=["consultation"],
                    tags=["linux"],
                ),
            ]
    return MockFC()


@pytest.fixture
def mesh_client():
    """A mock MeshPeerClient with configurable result."""
    class MockMeshClient:
        def __init__(self):
            self.sent_intents = []

        async def send_task(self, intent):
            self.sent_intents.append(intent)
            return TaskResult(
                status="completed",
                data={"answer": f"remote: {intent.payload.get('question', '')}"},
            )
    return MockMeshClient()


# ------------------------------------------------------------------
# Local dispatch
# ------------------------------------------------------------------


class TestLocalDispatch:
    """send_task with local target_node."""

    def test_dispatch_local_no_target_node(self, mock_dispatch, mock_fc):
        """When target_node is None, dispatch locally."""
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "What is pacman?"},
            target_node=None,
        )
        result = adapter.send_task(intent)
        assert result.status == "completed"
        assert "What is pacman?" in result.data.get("answer", "")

    def test_dispatch_local_explicit_local(self, mock_dispatch, mock_fc):
        """When target_node is 'local', dispatch locally."""
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "Hello"},
            target_node="local",
        )
        result = adapter.send_task(intent)
        assert result.status == "completed"

    def test_dispatch_local_with_profile(self, mock_dispatch, mock_fc):
        """target_profile is passed to the dispatch function."""
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "Deploy nginx"},
            target_node="local",
            target_profile="ops",
        )
        result = adapter.send_task(intent)
        assert result.status == "completed"
        assert "ops" in result.data.get("answer", "")

    def test_dispatch_with_empty_payload(self, mock_dispatch, mock_fc):
        """An intent with no question still dispatches."""
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        intent = TaskIntent(
            intent_type="consultation",
            payload={},
            target_node="local",
        )
        result = adapter.send_task(intent)
        assert result.status == "completed"


# ------------------------------------------------------------------
# Remote (mesh) dispatch
# ------------------------------------------------------------------


class TestRemoteDispatch:
    """send_task with a remote target_node."""

    def test_dispatch_remote_via_mesh(self, mock_dispatch, mock_fc, mesh_client):
        """When target_node is remote, dispatches via mesh_client."""
        adapter = HermesA2AAdapter(
            dispatch_fn=mock_dispatch,
            fc=mock_fc,
            mesh_client=mesh_client,
        )
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "Analyze logs"},
            target_node="100.96.0.1",
            target_profile="odin",
        )
        result = adapter.send_task(intent)
        assert result.status == "completed"
        assert "remote:" in result.data.get("answer", "")

    def test_remote_without_mesh_client_fails(self, mock_dispatch, mock_fc):
        """Without a mesh_client, remote dispatch returns failed."""
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "Hello"},
            target_node="remote-peer",
        )
        result = adapter.send_task(intent)
        assert result.status == "failed"
        assert "No MeshPeerClient" in (result.error or "")

    def test_remote_sends_intent_to_mesh(self, mock_dispatch, mock_fc, mesh_client):
        """The TaskIntent is passed through to mesh_client.send_task."""
        adapter = HermesA2AAdapter(
            dispatch_fn=mock_dispatch,
            fc=mock_fc,
            mesh_client=mesh_client,
        )
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "Check status"},
            target_node="odin-node",
        )
        adapter.send_task(intent)
        assert len(mesh_client.sent_intents) == 1
        assert mesh_client.sent_intents[0].target_node == "odin-node"
        assert mesh_client.sent_intents[0].payload.get("question") == "Check status"


# ------------------------------------------------------------------
# get_capabilities
# ------------------------------------------------------------------


class TestGetCapabilities:
    """get_capabilities returns registered profiles."""

    def test_returns_capabilities(self, mock_dispatch, mock_fc):
        """Discovers capabilities from the fleet controller."""
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        caps = adapter.get_capabilities()
        assert len(caps) >= 1
        assert any(c.profile_name == "sherlock" for c in caps)

    def test_empty_fc_returns_empty(self, mock_dispatch):
        """With no FC, returns empty list."""
        fc = type("EmptyFC", (), {"discover": lambda self, it, t=None: []})()
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=fc)
        caps = adapter.get_capabilities()
        assert caps == []

    def test_fc_exception_returns_empty(self, mock_dispatch):
        """If FC.discover raises, returns empty list gracefully."""

        class BrokenFC:
            def discover(self, intent_type, tags=None):
                raise RuntimeError("Broken")
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=BrokenFC())
        caps = adapter.get_capabilities()
        assert caps == []


# ------------------------------------------------------------------
# cancel_task and send_streaming_task
# ------------------------------------------------------------------


class TestCancelAndStreaming:
    """cancel_task and send_streaming_task stubs (Phase 5)."""

    def test_cancel_returns_false(self, mock_dispatch, mock_fc):
        """cancel_task returns False (Phase 5 stub)."""
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        assert adapter.cancel_task("task/abc") is False

    def test_send_streaming_delegates_to_send(self, mock_dispatch, mock_fc):
        """send_streaming_task currently delegates to send_task."""
        import asyncio
        adapter = HermesA2AAdapter(dispatch_fn=mock_dispatch, fc=mock_fc)
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "Stream test"},
        )
        result = asyncio.run(adapter.send_streaming_task(intent))
        assert result.status == "completed"
