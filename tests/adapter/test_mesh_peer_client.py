"""Tests for MeshPeerClient — outbound mesh peer connections.

Uses mocks at the httpx/SDK boundary so no real network is needed.
"""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from a2a.types.a2a_pb2 import (
    AgentCard,
    AgentSkill,
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskState,
)

from adapter.mesh_peer_client import MeshPeerClient
from adapter.peer_registry import PeerConfig, PeerRegistry
from core.domain.models.capability import AgentCapability
from core.domain.models.intent import TaskIntent
from core.domain.models.result import TaskResult
from core.domain.interfaces.fleet_controller import FleetController


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def fc() -> FleetController:
    from core.fleet_controller import FleetControllerImpl
    return FleetControllerImpl()


@pytest.fixture
def peer_alpha() -> PeerConfig:
    return PeerConfig(
        name="alpha",
        url="http://100.96.0.1:9696",
        api_key="sk-alpha-secret",
        cidr_allow=["100.96.0.0/16"],
    )


@pytest.fixture
def peer_beta() -> PeerConfig:
    return PeerConfig(
        name="beta",
        url="http://100.96.0.2:9696",
        api_key="sk-beta-secret",
        cidr_allow=["100.96.0.0/16"],
    )


@pytest.fixture
def registry(peer_alpha: PeerConfig, peer_beta: PeerConfig) -> PeerRegistry:
    return PeerRegistry([peer_alpha, peer_beta])


@pytest.fixture
def mock_agent_card() -> AgentCard:
    """A minimal AgentCard with two skills for capability registration tests."""
    return AgentCard(
        name="alpha-node",
        description="Test peer node",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="diagnostician",
                name="System Diagnostician",
                description="Root cause diagnostics",
                tags=["diagnose", "consultation"],
                examples=['{"symptoms": "503"}'],
            ),
            AgentSkill(
                id="ops",
                name="Operations",
                description="Deploy and manage",
                tags=["deploy", "action_request"],
                examples=['{"action": "restart"}'],
            ),
        ],
    )


@pytest.fixture
def mock_stream_response() -> StreamResponse:
    """Simulate a non-streaming A2A response with a message part."""
    msg = Message(
        message_id="resp-001",
        role=Role.ROLE_AGENT,
        parts=[Part(text="Remote diagnostics complete.")],
    )
    sr = StreamResponse()
    sr.message.CopyFrom(msg)
    return sr


# ------------------------------------------------------------------
# connect_peer
# ------------------------------------------------------------------


class TestConnectPeer:
    """Tests for ``MeshPeerClient.connect_peer()``."""

    async def test_connects_and_registers_capabilities(
        self, registry: PeerRegistry, fc: FleetController, mock_agent_card: AgentCard,
    ):
        """Successful connection registers the peer's skills in the FC."""
        with patch(
            "adapter.mesh_peer_client.A2ACardResolver"
        ) as mock_resolver_cls, patch(
            "adapter.mesh_peer_client.ClientFactory"
        ) as mock_factory_cls:
            # Mock card resolver
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card = AsyncMock(return_value=mock_agent_card)
            mock_resolver_cls.return_value = mock_resolver

            # Mock factory
            mock_client = AsyncMock()
            mock_factory_cls.return_value.create.return_value = mock_client

            client = MeshPeerClient(registry, fc)
            result = await client.connect_peer("alpha")

            assert result is True
            assert "alpha" in client._clients
            assert client._clients["alpha"] is mock_client

            # Verify capabilities registered in FC
            caps = fc._capabilities
            assert "alpha/diagnostician" in caps
            assert "alpha/ops" in caps
            assert caps["alpha/diagnostician"].node_id == "alpha"
            assert caps["alpha/diagnostician"].intents == ["diagnose", "consultation"]

    async def test_returns_false_for_unknown_peer(
        self, registry: PeerRegistry, fc: FleetController,
    ):
        """Unknown peer names return False without error."""
        client = MeshPeerClient(registry, fc)
        result = await client.connect_peer("nonexistent")
        assert result is False

    async def test_returns_false_on_connection_failure(
        self, registry: PeerRegistry, fc: FleetController,
    ):
        """Transport/network errors during connect return False."""
        with patch(
            "adapter.mesh_peer_client.A2ACardResolver"
        ) as mock_resolver_cls:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card = AsyncMock(
                side_effect=ConnectionError("Peer unreachable")
            )
            mock_resolver_cls.return_value = mock_resolver

            client = MeshPeerClient(registry, fc)
            result = await client.connect_peer("alpha")

            assert result is False
            assert "alpha" not in client._clients

    async def test_connect_all(
        self, registry: PeerRegistry, fc: FleetController,
    ):
        """connect_all connects every configured peer."""
        with patch(
            "adapter.mesh_peer_client.A2ACardResolver"
        ) as mock_resolver_cls, patch(
            "adapter.mesh_peer_client.ClientFactory"
        ) as mock_factory_cls:
            # Return the same mock card for both peers
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card = AsyncMock(
                return_value=AgentCard(
                    name="node",
                    description="node",
                    version="1.0.0",
                    default_input_modes=["text"],
                    default_output_modes=["text"],
                )
            )
            mock_resolver_cls.return_value = mock_resolver

            mock_client = AsyncMock()
            mock_factory_cls.return_value.create.return_value = mock_client

            client = MeshPeerClient(registry, fc)
            await client.connect_all()

            assert "alpha" in client._clients
            assert "beta" in client._clients
            assert len(client._clients) == 2


# ------------------------------------------------------------------
# send_task
# ------------------------------------------------------------------


class TestSendTask:
    """Tests for ``MeshPeerClient.send_task()``."""

    async def test_sends_and_returns_answer(
        self,
        registry: PeerRegistry,
        fc: FleetController,
        mock_agent_card: AgentCard,
        mock_stream_response: StreamResponse,
    ):
        """A successful remote dispatch returns a completed TaskResult."""
        with patch(
            "adapter.mesh_peer_client.A2ACardResolver"
        ) as mock_resolver_cls, patch(
            "adapter.mesh_peer_client.ClientFactory"
        ) as mock_factory_cls:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card = AsyncMock(return_value=mock_agent_card)
            mock_resolver_cls.return_value = mock_resolver

            mock_client = AsyncMock()

            async def mock_send_message(*args, **kwargs):
                async for item in _async_iter([mock_stream_response]):
                    yield item

            mock_client.send_message = mock_send_message
            mock_factory_cls.return_value.create.return_value = mock_client

            client = MeshPeerClient(registry, fc)
            await client.connect_peer("alpha")

            intent = TaskIntent(
                intent_type="consultation",
                payload={"question": "Diagnose the issue"},
                target_node="alpha",
            )
            result = await client.send_task(intent)

            assert result.status == "completed"
            assert result.data is not None
            assert "Remote diagnostics complete." in result.data["answer"]

    async def test_fails_for_unconnected_peer(
        self, registry: PeerRegistry, fc: FleetController,
    ):
        """Sending to a peer that was never connected returns failed."""
        client = MeshPeerClient(registry, fc)

        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "Hello"},
            target_node="nonexistent",
        )
        result = await client.send_task(intent)

        assert result.status == "failed"
        assert "not connected" in (result.error or "")

    async def test_fails_on_remote_error(
        self,
        registry: PeerRegistry,
        fc: FleetController,
        mock_agent_card: AgentCard,
    ):
        """Network/transport errors during dispatch return failed."""
        with patch(
            "adapter.mesh_peer_client.A2ACardResolver"
        ) as mock_resolver_cls, patch(
            "adapter.mesh_peer_client.ClientFactory"
        ) as mock_factory_cls:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card = AsyncMock(return_value=mock_agent_card)
            mock_resolver_cls.return_value = mock_resolver

            mock_client = AsyncMock()

            async def mock_send_message_error(*args, **kwargs):
                if False:
                    yield  # make this an async generator
                raise ConnectionError("Remote down")

            mock_client.send_message = mock_send_message_error
            mock_factory_cls.return_value.create.return_value = mock_client

            client = MeshPeerClient(registry, fc)
            await client.connect_peer("alpha")

            intent = TaskIntent(
                intent_type="consultation",
                payload={"question": "Ping"},
                target_node="alpha",
            )
            result = await client.send_task(intent)

            assert result.status == "failed"
            assert "Remote down" in (result.error or "")


# ------------------------------------------------------------------
# Capability registration
# ------------------------------------------------------------------


class TestCapabilityRegistration:
    """Tests for ``_register_peer_capabilities``."""

    def test_skills_become_capabilities(self, fc: FleetController):
        """Each AgentSkill is registered as an AgentCapability with
        the correct naming convention."""
        from adapter.mesh_peer_client import MeshPeerClient
        from adapter.peer_registry import PeerRegistry

        client = MeshPeerClient(PeerRegistry([]), fc)

        card = AgentCard(
            name="test-node",
            description="Test",
            version="1.0.0",
            default_input_modes=["text"],
            default_output_modes=["text"],
            skills=[
                AgentSkill(
                    id="web-search",
                    name="Web Search",
                    description="Search the web",
                    tags=["research", "consultation"],
                    examples=["example query"],
                ),
            ],
        )

        client._register_peer_capabilities("proteus", card)

        assert "proteus/web-search" in fc._capabilities
        cap = fc._capabilities["proteus/web-search"]
        assert cap.node_id == "proteus"
        assert cap.display_name == "Web Search"
        assert cap.intents == ["research", "consultation"]
        assert cap.tags == ["research", "consultation"]
        assert cap.examples == ["example query"]

    def test_empty_skills_registers_nothing(self, fc: FleetController):
        """A card with no skills results in no new capabilities."""
        from adapter.mesh_peer_client import MeshPeerClient
        from adapter.peer_registry import PeerRegistry

        pre_count = len(fc._capabilities)
        client = MeshPeerClient(PeerRegistry([]), fc)

        card = AgentCard(
            name="empty-node",
            description="No skills",
            version="1.0.0",
            default_input_modes=["text"],
            default_output_modes=["text"],
        )

        client._register_peer_capabilities("empty", card)
        assert len(fc._capabilities) == pre_count


# ------------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------------


class TestLifecycle:
    """Lifecycle tests: close, edge cases."""

    async def test_close_cleans_up(
        self, registry: PeerRegistry, fc: FleetController, mock_agent_card: AgentCard,
    ):
        """Close disconnects all peers and clears internal state."""
        with patch(
            "adapter.mesh_peer_client.A2ACardResolver"
        ) as mock_resolver_cls, patch(
            "adapter.mesh_peer_client.ClientFactory"
        ) as mock_factory_cls:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card = AsyncMock(return_value=mock_agent_card)
            mock_resolver_cls.return_value = mock_resolver

            mock_client = AsyncMock()
            mock_factory_cls.return_value.create.return_value = mock_client

            client = MeshPeerClient(registry, fc)
            await client.connect_all()
            assert len(client._clients) == 2

            await client.close()

            assert len(client._clients) == 0
            mock_client.close.assert_called()

    async def test_close_no_clients_does_not_raise(self, registry, fc):
        """Calling close with no connected peers is a no-op."""
        client = MeshPeerClient(registry, fc)
        await client.close()  # should not raise


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _async_iter(items):
    """Convert a list into an async iterator."""
    for item in items:
        yield item
