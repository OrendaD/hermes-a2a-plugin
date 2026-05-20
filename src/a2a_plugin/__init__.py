"""a2a-server — Hermes plugin for A2A Protocol v1.0 HTTP server.

This module is the Hermes plugin entry point. When pip-installed (via
``a2a-core`` package + ``hermes_agent.plugins`` entry point), Hermes discovers
it automatically and calls ``register(ctx)`` at startup.

The plugin wires together:
- ``adapter.hermes_executor.HermesExecutor`` — translates A2A requests to Hermes
- ``adapter.agent_card_route`` — serves the Agent Card at
  ``/.well-known/agent-card.json``
- ``core.fleet_controller.FleetControllerImpl`` — routes intents to profiles
- A uvicorn+Starlette HTTP server daemon thread — handles incoming A2A connections

Milestones:
  3.1 — Stub: log on load (done)
  3.2 — Start uvicorn in daemon thread (done)
  3.3 — Load profiles into FleetController (current)
  3.4 — Wire HermesExecutor + dispatch_fn → full integration
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

import uvicorn
from a2a.types import AgentCard, AgentCapabilities
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from adapter.agent_card_builder import build_agent_card
from adapter.agent_card_route import create_agent_card_route
from adapter.hermes_executor import HermesExecutor
from adapter.profile_discovery import discover_profiles
from core.domain.models.result import TaskResult
from core.fleet_controller import FleetControllerImpl

logger = logging.getLogger(__name__)

# Guard: register() is called once during plugin load, but having a second
# entry avoids risk if Hermes ever adds plugin reloading.
_a2a_server_started: bool = False

# Module-level FleetController instance. Set during register() (M3.3), used
# by HermesExecutor in M3.4. Held here so the dispatch closure captures it.
_fleet_controller: FleetControllerImpl | None = None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8081
DEFAULT_BIND = "127.0.0.1"
DEFAULT_NODE_NAME = "hermes-a2a-node"
DEFAULT_PROFILES_DIR = "~/.hermes/profiles"


def _read_a2a_config() -> dict[str, Any]:
    """Read the ``a2a:`` section from ``~/.hermes/config.yaml``.

    Falls back to defaults for any missing key so the plugin works
    without explicit configuration.
    """
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        a2a = cfg.get("a2a", {})
    except Exception:
        logger.warning("a2a-server: could not load Hermes config, using defaults")
        a2a = {}

    return {
        "port": a2a.get("port", DEFAULT_PORT),
        "bind": a2a.get("bind", DEFAULT_BIND),
        "node_name": a2a.get("node_name", DEFAULT_NODE_NAME),
        "profiles_dir": a2a.get("profiles_dir", DEFAULT_PROFILES_DIR),
        "node_id": a2a.get("node_id", "local"),
    }


# ---------------------------------------------------------------------------
# Server lifecycle helpers
# ---------------------------------------------------------------------------


def _build_app(
    config: dict[str, Any],
    *,
    jsonrpc_routes: list[Route] | None = None,
) -> Starlette:
    """Build the Starlette ASGI app with all A2A routes.

    Mounts:
      • ``GET /health`` — simple liveness check
      • ``GET /.well-known/agent-card.json`` — signed Agent Card (M1.4)
      • ``POST /a2a/jsonrpc`` — A2A JSON-RPC endpoint (M3.4, when wired)

    Args:
        config: Plugin configuration dict.
        jsonrpc_routes: Optional list of Starlette Route objects for the
            A2A JSON-RPC endpoint. Added when HermesExecutor is wired.
    """
    profiles_dir = os.path.expanduser(config.get("profiles_dir", DEFAULT_PROFILES_DIR))
    node_name = config["node_name"]

    agent_card_route = create_agent_card_route(
        profiles_dir,
        node_name=node_name,
        node_description=f"Hermes A2A node ({node_name})",
        interface_url=f"http://{config['bind']}:{config['port']}",
    )

    async def _health(request):
        return JSONResponse({"status": "ok", "service": "a2a-server"})

    routes: list[Route] = [
        Route("/health", endpoint=_health, methods=["GET"]),
        agent_card_route,
    ]

    if jsonrpc_routes:
        routes.extend(jsonrpc_routes)

    return Starlette(routes=routes)


def _start_server(app: Starlette, config: dict[str, Any]) -> threading.Thread:
    """Start the uvicorn server in a daemon thread.

    Daemon threads are killed when the main Hermes process exits,
    so no explicit shutdown hook is needed for v1.
    """
    host = config["bind"]
    port = config["port"]

    thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={
            "host": host,
            "port": port,
            "log_level": "info",
        },
        daemon=True,
    )
    thread.start()
    logger.info(
        "a2a-server: uvicorn started on %s:%s (daemon thread %s)",
        host, port, thread.name,
    )
    return thread


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Register the a2a-server plugin with Hermes.

    Args:
        ctx: Hermes PluginContext for registering hooks/tools/commands.
    """
    global _a2a_server_started, _fleet_controller

    # Guard against double-initialisation
    if _a2a_server_started:
        logger.debug("a2a-server: already started, skipping")
        return
    _a2a_server_started = True

    # Verify a2a-core adapter imports resolve at load time
    try:
        from adapter.hermes_executor import HermesExecutor  # noqa: F401
        from adapter.agent_card_route import create_agent_card_route  # noqa: F401
        from core.fleet_controller import FleetControllerImpl  # noqa: F401
        from core.domain.models.intent import TaskIntent  # noqa: F401

        logger.debug("a2a-core adapter imports verified")
    except ImportError as exc:
        logger.error(
            "a2a-server: a2a-core package not importable (%s). "
            "Run `pip install -e /path/to/a2a-plugin` in the Hermes venv.",
            exc,
        )
        raise

    # Read configuration
    a2a_config = _read_a2a_config()

    logger.info(
        "a2a-server plugin loading (3.3). "
        "PluginContext: register_tool=%s, register_hook=%s, dispatch_tool=%s | "
        "config: %s:%s | profiles: %s",
        hasattr(ctx, "register_tool"),
        hasattr(ctx, "register_hook"),
        hasattr(ctx, "dispatch_tool"),
        a2a_config["bind"],
        a2a_config["port"],
        a2a_config["profiles_dir"],
    )

    # ------------------------------------------------------------------
    # Fleet Controller — profile load & registration (M3.3)
    # ------------------------------------------------------------------
    profiles_dir = os.path.expanduser(a2a_config["profiles_dir"])
    node_id = a2a_config["node_id"]

    fc = FleetControllerImpl()
    fc._local_node_id = node_id

    caps = discover_profiles(profiles_dir, node_id=node_id)
    for cap in caps:
        fc.register_profile(cap)
    logger.info(
        "a2a-server: FleetController loaded — %d profiles registered (node: %s)",
        len(caps), node_id,
    )
    if caps:
        for cap in caps:
            logger.debug(
                "  profile '%s' (%s): intents=%s, tags=%s",
                cap.profile_name, cap.display_name,
                cap.intents, cap.tags,
            )

    _fleet_controller = fc

    # ------------------------------------------------------------------
    # HermesExecutor — A2A dispatch wiring (M3.4)
    # ------------------------------------------------------------------
    from a2a.server.request_handlers import DefaultRequestHandlerV2
    from a2a.server.routes import create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore

    # Build AgentCard for the SDK handler from discovered profiles
    if caps:
        agent_card = build_agent_card(
            caps,
            node_name=a2a_config["node_name"],
            node_description=f"Hermes A2A node ({a2a_config['node_name']})",
            interface_url=f"http://{a2a_config['bind']}:{a2a_config['port']}",
        )
    else:
        agent_card = AgentCard(
            name=a2a_config["node_name"],
            description=f"Hermes A2A node ({a2a_config['node_name']})",
            version="1.0.0",
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            capabilities=AgentCapabilities(
                streaming=False,
                push_notifications=False,
            ),
        )

    task_store = InMemoryTaskStore()

    # Dispatch function: translates a (goal, profile) pair into a
    # Hermes sub-agent invocation via delegate_task.
    # The closure captures ctx (PluginContext) from register().
    def _dispatch_fn(goal: str, profile_name: str | None = None) -> TaskResult:
        args: dict[str, Any] = {"goal": goal}
        if profile_name:
            args["profile"] = profile_name
        try:
            result_json = ctx.dispatch_tool("delegate_task", args)
            result_data = json.loads(result_json)
            summary = result_data.get("summary", str(result_data))
            return TaskResult(
                status="completed",
                data={"answer": summary},
            )
        except Exception as exc:
            logger.error("a2a-server: dispatch_fn failed: %s", exc, exc_info=True)
            return TaskResult(
                status="failed",
                error=f"Dispatch error: {exc}",
            )

    executor = HermesExecutor(dispatch_fn=_dispatch_fn, fc=fc)
    handler = DefaultRequestHandlerV2(
        agent_executor=executor,
        task_store=task_store,
        agent_card=agent_card,
    )
    jsonrpc_routes = create_jsonrpc_routes(
        request_handler=handler,
        rpc_url="/a2a/jsonrpc",
    )

    logger.info(
        "a2a-server: HermesExecutor wired — %d profiles, A2A JSON-RPC at "
        "POST /a2a/jsonrpc",
        len(caps),
    )

    # ------------------------------------------------------------------
    # Starlette app + server (M3.2)
    # ------------------------------------------------------------------
    app = _build_app(a2a_config, jsonrpc_routes=jsonrpc_routes)
    _start_server(app, a2a_config)

    logger.info(
        "a2a-server: plugin ready — %d profiles, Agent Card at "
        "http://%s:%s/.well-known/agent-card.json, "
        "JSON-RPC at http://%s:%s/a2a/jsonrpc",
        len(caps),
        a2a_config["bind"],
        a2a_config["port"],
        a2a_config["bind"],
        a2a_config["port"],
    )
