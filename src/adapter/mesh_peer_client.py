"""MeshPeerClient — outbound A2A client for cross-node task dispatch.

Connects to configured mesh peers via the A2A SDK, resolves their Agent
Cards, registers remote capabilities in FleetController, and dispatches
tasks to remote peers using SSRF-guarded transport with bearer-token auth.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

import httpx

from google.protobuf.struct_pb2 import Struct

from a2a.client import (
    Client,
    ClientCallContext,
    ClientConfig,
    ClientFactory,
)
from a2a.client.card_resolver import A2ACardResolver
from a2a.types.a2a_pb2 import (
    AgentCard,
    Message,
    Part,
    Role,
    SendMessageRequest,
)

from adapter.peer_registry import PeerConfig, PeerRegistry
from adapter.ssrf import AsyncSSRFTransport
from core.domain.models.capability import AgentCapability
from core.domain.models.intent import TaskIntent
from core.domain.models.result import TaskResult
from core.domain.interfaces.fleet_controller import FleetController

logger = logging.getLogger(__name__)


class MeshPeerClient:
    """Outbound A2A client for cross-node task dispatch.

    Maintains one SDK ``Client`` per configured peer, resolves each peer's
    ``AgentCard`` on first contact, registers remote capabilities in the
    ``FleetController``, and dispatches tasks via ``send_task()``.

    Args:
        peer_registry: Registry of known peer configurations.
        fc: FleetController to register remote capabilities with.
    """

    def __init__(
        self,
        peer_registry: PeerRegistry,
        fc: FleetController,
    ) -> None:
        self._registry = peer_registry
        self._fc = fc
        self._clients: dict[str, Client] = {}
        self._cards: dict[str, AgentCard] = {}
        self._retry_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect_peer(self, peer_name: str) -> bool:
        """Resolve, authenticate, and register a peer's capabilities.

        Creates an SDK ``Client`` with SSRF-guarded HTTP transport and
        bearer-token auth, resolves the peer's ``AgentCard`` via the
        ``A2ACardResolver``, and registers each skill as an
        ``AgentCapability`` in the ``FleetController``.

        Args:
            peer_name: Name of the peer (must exist in ``PeerRegistry``).

        Returns:
            ``True`` if the peer was connected and registered,
            ``False`` if the peer is unknown or connection failed.
        """
        peer = self._registry.get_peer(peer_name)
        if not peer:
            logger.warning(
                "MeshPeerClient: peer '%s' not found in registry", peer_name
            )
            return False

        try:
            # Create httpx client with SSRF-guarded transport
            ssrf_transport = AsyncSSRFTransport(
                allow_cidrs=peer.cidr_allow,
            )
            httpx_client = httpx.AsyncClient(
                transport=ssrf_transport,
                timeout=httpx.Timeout(30.0),
            )

            # Build SDK ClientFactory with our custom httpx client so that
            # both card resolution and all subsequent RPC calls are SSRF-guarded.
            config = ClientConfig(
                httpx_client=httpx_client,
                streaming=False,  # no streaming needed for dispatch
            )
            factory = ClientFactory(config)

            # Resolve the AgentCard first so we can register capabilities
            resolver = A2ACardResolver(httpx_client, peer.url)
            card = await resolver.get_agent_card()

            # Create SDK client (no auth interceptor — we pass auth via
            # ClientCallContext at call time, which is simpler and works
            # regardless of whether the peer's AgentCard declares security
            # schemes).
            client = factory.create(card)

            self._clients[peer_name] = client
            self._cards[peer_name] = card

            # Register each of the peer's skills as a routing capability
            self._register_peer_capabilities(peer_name, card)

            logger.info(
                "MeshPeerClient: connected peer '%s' at %s "
                "(%d skills registered)",
                peer_name, peer.url, len(card.skills),
            )
            return True

        except Exception as exc:
            logger.error(
                "MeshPeerClient: failed to connect peer '%s': %s",
                peer_name, exc, exc_info=True,
            )
            return False

    async def connect_all(self) -> None:
        """Connect to every peer in the registry.

        Logs per-peer success/failure but does not raise — a peer that
        is unreachable at startup will be retried in the background with
        exponential backoff (full-jitter, 1s base, 60s cap) until it
        reconnects or the client is closed.
        """
        failed = []
        for peer in self._registry.all_peers():
            ok = await self.connect_peer(peer.name)
            if not ok:
                failed.append(peer.name)
        # Schedule background retries for peers that failed
        for name in failed:
            self._schedule_peer_retry(name)

    def _schedule_peer_retry(self, peer_name: str) -> None:
        """Cancel any existing retry task for *peer_name*, start a new one."""
        if peer_name in self._retry_tasks:
            self._retry_tasks[peer_name].cancel()
        self._retry_tasks[peer_name] = asyncio.create_task(
            self._retry_peer_loop(peer_name),
        )

    async def _retry_peer_loop(
        self, peer_name: str, max_interval: float = 60.0,
    ) -> None:
        """Background retry with exponential backoff + full jitter.

        Base interval is 1s, doubling each attempt up to *max_interval*.
        Each wait applies full jitter (random uniform from 0..delay) to
        prevent thundering-herd patterns.  Stops as soon as
        ``connect_peer()`` returns ``True``.
        """
        attempt = 0
        while True:
            attempt += 1
            # Exponential backoff: base=1s, cap=max_interval
            delay = min(max_interval, 1.0 * (2**attempt))
            # Full jitter (uniform from 0 to delay)
            delay = random.uniform(0, delay)
            await asyncio.sleep(delay)

            ok = await self.connect_peer(peer_name)
            if ok:
                logger.info(
                    "MeshPeerClient: reconnected peer '%s' after %d attempts",
                    peer_name,
                    attempt,
                )
                self._retry_tasks.pop(peer_name, None)
                return
            else:
                logger.debug(
                    "MeshPeerClient: retry %d for peer '%s' failed, "
                    "next attempt in ~%.0fs",
                    attempt,
                    peer_name,
                    delay,
                )

    async def close(self) -> None:
        """Close all peer connections and release resources."""
        # Cancel all background retry tasks
        for name, task in list(self._retry_tasks.items()):
            task.cancel()
        self._retry_tasks.clear()

        for name, client in self._clients.items():
            try:
                await client.close()
            except Exception:
                logger.debug(
                    "MeshPeerClient: error closing peer '%s'", name, exc_info=True
                )
        self._clients.clear()
        self._cards.clear()
        logger.info("MeshPeerClient: all peer connections closed")

    # ------------------------------------------------------------------
    # Task dispatch
    # ------------------------------------------------------------------

    async def send_task(self, intent: TaskIntent) -> TaskResult:
        """Dispatch a task to a remote peer.

        Translates the ``TaskIntent`` into an A2A ``SendMessageRequest``,
        sends it via the peer's SDK ``Client``, and translates the
        ``StreamResponse`` back into a ``TaskResult``.

        Args:
            intent: The task intent to dispatch. ``intent.target_node``
                must match a connected peer name.

        Returns:
            A ``TaskResult`` with status ``"completed"`` on success or
            ``"failed"`` if the peer is not connected or the dispatch
            errors.
        """
        peer_name = intent.target_node
        client = self._clients.get(peer_name)
        peer = self._registry.get_peer(peer_name)

        if not client or not peer:
            return TaskResult(
                status="failed",
                error=f"Peer '{peer_name}' not connected",
            )

        question = intent.payload.get("question", "")

        # Build A2A SendMessageRequest — the same structure the
        # remote peer's HermesExecutor expects.
        req = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                parts=[Part(text=question)],
            ),
        )

        # Propagate A2A protocol provenance fields from the intent
        if intent.reference_task_ids:
            req.message.reference_task_ids.extend(intent.reference_task_ids)
        if intent.context_id:
            req.message.context_id = intent.context_id
        # Build provenance metadata (Struct) with source_node/source_profile
        meta = Struct()
        if intent.source_node and intent.source_node != "local":
            meta.fields["source_node"].string_value = intent.source_node
        if intent.source_profile and intent.source_profile != "a2a-adapter":
            meta.fields["source_profile"].string_value = intent.source_profile
        if meta.fields:
            req.message.metadata.CopyFrom(meta)

        # ClientCallContext with bearer-token auth for the remote peer.
        # The A2A SDK's JSON-RPC transport reads service_parameters and
        # attaches them as HTTP headers.
        ctx = ClientCallContext(
            service_parameters={"Authorization": f"Bearer {peer.api_key}"},
        )

        try:
            response_text: list[str] = []
            async for stream_response in client.send_message(req, context=ctx):
                # Extract answer text from returned Message (non-streaming)
                if stream_response.HasField("message"):
                    for part in stream_response.message.parts:
                        if part.HasField("text") and part.text:
                            response_text.append(part.text)

                # Also check for task-level message text
                if stream_response.HasField("task"):
                    for part in stream_response.task.parts:
                        if part.HasField("text") and part.text:
                            response_text.append(part.text)

            answer = "\n".join(response_text).strip()

            return TaskResult(
                status="completed",
                data={"answer": answer} if answer else None,
            )

        except Exception as exc:
            logger.error(
                "MeshPeerClient: dispatch to '%s' failed: %s",
                peer_name, exc, exc_info=True,
            )
            return TaskResult(
                status="failed",
                error=f"Remote dispatch to '{peer_name}' failed: {exc}",
            )

    # ------------------------------------------------------------------
    # Capability registration
    # ------------------------------------------------------------------

    def _register_peer_capabilities(
        self, peer_name: str, card: AgentCard,
    ) -> None:
        """Convert an ``AgentCard``'s skills to ``AgentCapability`` entries
        and register each in the ``FleetController``.

        Each skill is namespaced as ``<peer_name>/<skill.id>`` so that
        profile references are unique across the mesh and clearly identify
        the owning peer.

        Args:
            peer_name: The peer's name (used as ``node_id``).
            card: The resolved AgentCard whose skills to register.
        """
        registered = 0
        for skill in card.skills:
            skill_tags = list(skill.tags) if skill.tags else []
            cap = AgentCapability(
                profile_name=f"{peer_name}/{skill.id}",
                node_id=peer_name,
                display_name=skill.name or skill.id,
                description=skill.description or "",
                intents=skill_tags or ["consultation"],
                tags=skill_tags,
                examples=list(skill.examples) if skill.examples else [],
            )
            self._fc.register_profile(cap)
            registered += 1

        logger.debug(
            "MeshPeerClient: registered %d capabilities for peer '%s'",
            registered, peer_name,
        )
