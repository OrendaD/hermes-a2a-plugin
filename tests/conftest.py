"""Shared test fixtures — mock adapter, test capabilities, factory functions.

The MockAdapter records all sent intents and returns configurable
results, enabling verification of what the FC and Orchestrator
dispatch without hitting a real A2A endpoint.
"""

from __future__ import annotations

from typing import Optional

import pytest

from core.domain.models.intent import TaskIntent
from core.domain.models.result import TaskResult
from core.domain.models.capability import AgentCapability
from core.domain.models.dispatch import ProfileDispatch
from core.domain.interfaces.fleet_controller import FleetController
from core.domain.interfaces.adapter import A2AAdapter


# ------------------------------------------------------------------
# Mock adapter
# ------------------------------------------------------------------


class MockAdapter(A2AAdapter):
    """A2AAdapter stub that records calls and returns canned results.

    Attributes:
        sent_intents: List of every TaskIntent passed to send_task().
        results: Queue of TaskResults to return on send_task calls.
            Cycles if exhausted (repeats the last result).
    """

    def __init__(self, default_result: Optional[TaskResult] = None) -> None:
        self.sent_intents: list[TaskIntent] = []
        self.results: list[TaskResult] = []
        if default_result is None:
            default_result = TaskResult(
                status="completed", data={"answer": "mock answer"}
            )
        self._default = default_result
        self._index = 0

    def send_task(self, intent: TaskIntent) -> TaskResult:
        self.sent_intents.append(intent)
        return self._next_result()

    async def send_streaming_task(self, intent: TaskIntent) -> TaskResult:
        self.sent_intents.append(intent)
        return self._next_result()

    def cancel_task(self, task_id: str) -> bool:
        return True

    def get_capabilities(self) -> list[AgentCapability]:
        return []

    def _next_result(self) -> TaskResult:
        if self._index < len(self.results):
            result = self.results[self._index]
            self._index += 1
            return result
        return self._default

    def reset(self) -> None:
        """Clear recorded intents and reset result index."""
        self.sent_intents.clear()
        self._index = 0


# ------------------------------------------------------------------
# Sample capabilities — our known profiles
# ------------------------------------------------------------------


@pytest.fixture
def ray_cap() -> AgentCapability:
    return AgentCapability(
        profile_name="ray",
        node_id="local",
        display_name="System Diagnostician",
        description="Root cause diagnostics with runbook-backed analysis",
        intents=["diagnose", "consultation"],
        tags=["diagnosis", "health-check", "linux", "nginx"],
        examples=[
            '{"symptoms": "Nginx returning 502"}'
        ],
    )


@pytest.fixture
def ops_cap() -> AgentCapability:
    return AgentCapability(
        profile_name="ops",
        node_id="local",
        display_name="Environment Operations",
        description="Deployments, config management, systemd, cron",
        intents=["action_request", "deploy"],
        tags=["deploy", "config", "systemd", "cron"],
        examples=[
            '{"action": "restart", "service": "hermes-gateway"}'
        ],
    )


@pytest.fixture
def odin_cap() -> AgentCapability:
    return AgentCapability(
        profile_name="odin",
        node_id="100.96.0.1",  # Remote — Proteus's node
        display_name="Researcher",
        description="Gathers intelligence, judges sources, extracts content",
        intents=["consultation", "research"],
        tags=["research", "linux", "arch"],
    )


@pytest.fixture
def reviewer_cap() -> AgentCapability:
    return AgentCapability(
        profile_name="reviewer",
        node_id="local",
        display_name="Independent Verification",
        description="Verification and quality checks against spec",
        intents=["review", "audit"],
        tags=["review", "verify", "check"],
    )


# ------------------------------------------------------------------
# Fixtures: FC + Orchestrator with fresh mock adapter per test
# ------------------------------------------------------------------


@pytest.fixture
def mock_adapter() -> MockAdapter:
    return MockAdapter()


@pytest.fixture
def populated_fc(
    ray_cap: AgentCapability,
    ops_cap: AgentCapability,
    odin_cap: AgentCapability,
    reviewer_cap: AgentCapability,
) -> FleetController:
    """A FleetController pre-loaded with all four test profiles."""
    from core.fleet_controller import FleetControllerImpl
    fc = FleetControllerImpl()
    for cap in (ray_cap, ops_cap, odin_cap, reviewer_cap):
        fc.register_profile(cap)
    return fc


@pytest.fixture
def orchestrator_with_mocks(
    populated_fc: FleetController,
    mock_adapter: MockAdapter,
) -> tuple:
    """Return (Orchestrator, MockAdapter) for test access to sent intents."""
    from core.orchestrator import OrchestratorImpl
    orch = OrchestratorImpl(
        fleet_controller=populated_fc,
        adapter=mock_adapter,
    )
    return orch, mock_adapter
