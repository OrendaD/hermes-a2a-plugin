"""Tests for interface contracts — abstract base classes.

Verifies:
- All abstract methods are defined
- ABCs cannot be instantiated directly
- Concrete subclasses can be created and called (with mocks)
"""

from __future__ import annotations

from abc import ABC
from typing import Optional

import pytest

from core.domain.interfaces import FleetController, Orchestrator, A2AAdapter
from core.domain.models import TaskIntent, TaskResult, AgentCapability, ProfileDispatch
from core.domain.models.result import TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


class TestFleetControllerInterface:
    def test_is_abstract(self):
        """FleetController cannot be instantiated directly."""
        with pytest.raises(TypeError):
            FleetController()  # type: ignore[abstract]

    def test_enforces_all_methods(self):
        """A partial implementation raises TypeError."""
        with pytest.raises(TypeError):

            class PartialFC(FleetController):
                def route(self, intent: TaskIntent) -> ProfileDispatch:
                    ...

            PartialFC()

    def test_concrete_implementation(self):
        """A full implementation can be instantiated."""

        class TestFC(FleetController):
            def route(self, intent):
                return ProfileDispatch(
                    task_id="t1",
                    profile_name="ray",
                    node_address="local",
                    endpoint="internal:ray",
                    status="dispatched",
                )

            def release(self, task_id, profile_name):
                pass

            def register_profile(self, capability):
                pass

            def discover(self, intent_type, tags=None):
                return []

        fc = TestFC()
        dispatch = fc.route(TaskIntent(intent_type="test", payload={}))
        assert dispatch.status == "dispatched"
        assert fc.discover("test") == []


class TestOrchestratorInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            Orchestrator()  # type: ignore[abstract]

    def test_concrete_implementation(self):
        class TestOrch(Orchestrator):
            def __init__(self):
                self.tasks = {}

            def register_task(self, task_id, context_id, parent_task_id=None):
                self.tasks[task_id] = context_id

            def on_status_change(self, task_id, new_state, task_result):
                pass

            def recruit_specialist(self, question, source_context_id, parent_task_id, tags=None):
                return TaskResult(status="completed", data={"answer": "mocked"})

            def get_conversation_graph(self, context_id):
                return {"context_id": context_id, "tasks": []}

        orch = TestOrch()
        orch.register_task("t1", "ctx-1")
        assert "t1" in orch.tasks

        result = orch.recruit_specialist("question?", "ctx-1", "t1")
        assert result.status == "completed"


class TestA2AAdapterInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            A2AAdapter()  # type: ignore[abstract]

    def test_concrete_implementation(self):
        class TestAdapter(A2AAdapter):
            def send_task(self, intent):
                return TaskResult(status="completed", data={"ok": True})

            async def send_streaming_task(self, intent):
                return TaskResult(status="completed", data={"ok": True})

            def cancel_task(self, task_id):
                return True

            def get_capabilities(self):
                return []

        adapter = TestAdapter()
        result = adapter.send_task(TaskIntent(intent_type="test", payload={}))
        assert result.status == "completed"
        assert adapter.get_capabilities() == []


# ---------------------------------------------------------------------------
# Boundary rule check
# ---------------------------------------------------------------------------


class TestBoundaryRule:
    def test_no_a2a_imports_in_core(self):
        """Verify no A2A imports exist in the core package.

        This test checks the runtime imports — the CI-enforceable
        grep check is documented in ARCHITECTURE.md but we verify
        at the Python level too: none of our core modules should
        import 'a2a'.
        """
        import core

        # Walk the core package modules and check no 'a2a' in import stack
        import sys

        core_modules = {
            name for name in sys.modules if name.startswith("core")
        }
        for mod_name in sorted(core_modules):
            mod = sys.modules[mod_name]
            if mod is None:
                continue
            # Check the file itself for a2a imports
            try:
                source = mod.__file__ or ""
            except AttributeError:
                continue
            if source.endswith(".py"):
                with open(source) as f:
                    for i, line in enumerate(f, 1):
                        stripped = line.strip()
                        if stripped.startswith("from a2a") or stripped.startswith("import a2a"):
                            pytest.fail(
                                f"A2A import found in core: {source}:{i}: {stripped}"
                            )
