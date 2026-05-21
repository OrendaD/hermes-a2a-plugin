"""HermesA2AAdapter — A2AAdapter implementation for Hermes plugin.

Wraps the injected dispatch function and MeshPeerClient into the
A2AAdapter interface that OrchestratorImpl depends on. Handles
local → dispatch_fn and remote → MeshPeerClient routing.

The dispatch_fn is synchronous (Hermes AIAgent chat in the daemon thread).
The MeshPeerClient.send_task is async — the adapter bridges sync↔async
using a short-lived thread + event loop for remote dispatches, since
this is called from synchronous OrchestratorImpl methods that run within
an active asyncio event loop (uvicorn's loop).
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable, Optional

from core.domain.models.capability import AgentCapability
from core.domain.models.intent import TaskIntent
from core.domain.models.result import TaskResult
from core.domain.interfaces.adapter import A2AAdapter
from core.domain.interfaces.fleet_controller import FleetController

logger = logging.getLogger(__name__)

# Shared thread pool for sync→async bridging (max 4 concurrent remote dispatches)
_SYNC_BRIDGE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="a2a-adapter")


class HermesA2AAdapter(A2AAdapter):
    """A2AAdapter implementation wrapping dispatch_fn + optional MeshPeerClient.

    Args:
        dispatch_fn: Synchronous callable ``(goal, profile) → TaskResult``
            for local agent dispatch.
        fc: FleetController for capability listing and routing metadata.
        mesh_client: Optional MeshPeerClient for outbound remote dispatch
            via the A2A protocol. If ``None``, remote routing fails with
            a clear error.
    """

    def __init__(
        self,
        dispatch_fn: Callable[[str, Optional[str]], TaskResult],
        fc: FleetController,
        mesh_client: Any = None,
    ) -> None:
        self._dispatch = dispatch_fn
        self._fc = fc
        self._mesh_client = mesh_client

    # ------------------------------------------------------------------
    # A2AAdapter contract
    # ------------------------------------------------------------------

    def send_task(self, intent: TaskIntent) -> TaskResult:
        """Dispatch a task — locally or to a remote mesh peer.

        If ``intent.target_node`` is set and is not ``"local"``, the
        task is dispatched via ``MeshPeerClient.send_task()`` (bridging
        sync→async). Otherwise the local ``dispatch_fn`` is called.

        Args:
            intent: The task intent to dispatch.

        Returns:
            The result of the dispatch.
        """
        target_node = intent.target_node
        target_profile = intent.target_profile

        # --- Remote dispatch via mesh peer ---
        if target_node and target_node not in (None, "", "local"):
            if self._mesh_client is None:
                return TaskResult(
                    status="failed",
                    error=(
                        f"No MeshPeerClient configured for remote dispatch "
                        f"to node '{target_node}'"
                    ),
                )

            logger.debug(
                "HermesA2AAdapter: dispatching to remote node '%s' "
                "(profile=%s, intent=%s)",
                target_node,
                target_profile,
                intent.intent_type,
            )
            return self._run_async(self._mesh_client.send_task(intent))

        # --- Local dispatch via AIAgent ---
        goal = intent.payload.get("question", "")
        logger.debug(
            "HermesA2AAdapter: local dispatch (profile=%s, intent=%s, goal=%.80s)",
            target_profile,
            intent.intent_type,
            goal,
        )
        return self._dispatch(goal, target_profile)

    async def send_streaming_task(self, intent: TaskIntent) -> TaskResult:
        """Streaming stub — delegates to ``send_task`` for now.

        Phase 5 will add proper streaming support.
        """
        return self.send_task(intent)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel stub — returns ``False``.

        Phase 5 will propagate cancellation to the running AIAgent.
        """
        return False

    def get_capabilities(self) -> list[AgentCapability]:
        """Return this node's capabilities via the FleetController.

        Iterates over known intent types to discover registered profiles.
        Deduplicates by profile_name. Returns an empty list if the FC
        is unavailable or raises.

        Note: Phase 4 does not call this method — the AgentCard is built
        separately in the plugin's ``register()`` from the discovered
        profile capabilities list. This implementation exists to satisfy
        the ``A2AAdapter`` interface contract.
        """
        try:
            seen: set[str] = set()
            results: list[AgentCapability] = []
            for intent_type in (
                "consultation", "action_request", "review",
                "notification", "instruction",
            ):
                for cap in self._fc.discover(intent_type):
                    if cap.profile_name not in seen:
                        seen.add(cap.profile_name)
                        results.append(cap)
            return results
        except Exception as exc:
            logger.error(
                "HermesA2AAdapter: get_capabilities failed: %s", exc
            )
            return []

    # ------------------------------------------------------------------
    # Sync→async bridge
    # ------------------------------------------------------------------

    @staticmethod
    def _run_async(coro) -> TaskResult:
        """Execute a coroutine synchronously from a sync context.

        If called from a thread with a running event loop (the normal
        case — called from ``HermesExecutor.execute`` inside uvicorn's
        loop), the coroutine runs in a short-lived thread with its own
        event loop. Otherwise ``asyncio.run()`` is used directly.

        A 120-second timeout prevents hung remote dispatches from
        blocking the caller indefinitely.

        Args:
            coro: The coroutine to execute.

        Returns:
            The coroutine's result as a ``TaskResult``, or a failed
            ``TaskResult`` on timeout/exception.
        """
        try:
            asyncio.get_running_loop()
            in_running_loop = True
        except RuntimeError:
            in_running_loop = False

        if not in_running_loop:
            # No running loop — straightforward
            try:
                return asyncio.run(coro)
            except Exception as exc:
                logger.error(
                    "HermesA2AAdapter: async bridge failed: %s", exc
                )
                return TaskResult(
                    status="failed",
                    error=f"Async dispatch error: {exc}",
                )

        # Running loop — use a separate thread with its own event loop
        def _run():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()

        future = _SYNC_BRIDGE_POOL.submit(_run)
        try:
            return future.result(timeout=120)
        except TimeoutError:
            logger.error(
                "HermesA2AAdapter: remote dispatch timed out after 120s"
            )
            return TaskResult(
                status="failed",
                error="Remote dispatch timed out after 120 seconds",
            )
        except Exception as exc:
            logger.error(
                "HermesA2AAdapter: remote dispatch failed: %s", exc
            )
            return TaskResult(
                status="failed",
                error=f"Remote dispatch error: {exc}",
            )
