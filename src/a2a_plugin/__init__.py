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
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from a2a.types import AgentCard, AgentCapabilities
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from adapter.agent_card_builder import build_agent_card
from adapter.agent_card_route import create_agent_card_route
from adapter.auth_context_builder import BearerTokenContextBuilder
from adapter.hermes_executor import HermesExecutor
from adapter.peer_registry import PeerConfig, PeerRegistry
from adapter.profile_discovery import discover_profiles
from adapter.version_middleware import A2AVersionMiddleware
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

DEFAULT_PORT = 9696
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
        "signing_profile": a2a.get("signing_profile"),
        "peers": a2a.get("peers", []),
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
        signing_profile=config.get("signing_profile"),
    )

    async def _health(request):
        return JSONResponse({"status": "ok", "service": "a2a-server"})

    routes: list[Route] = [
        Route("/health", endpoint=_health, methods=["GET"]),
        agent_card_route,
    ]

    if jsonrpc_routes:
        routes.extend(jsonrpc_routes)

    app = Starlette(routes=routes)
    app.add_middleware(A2AVersionMiddleware)
    return app


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


# ---------------------------------------------------------------------------
# Dispatch: AIAgent-based (replaces old dispatch_tool closure)
# ---------------------------------------------------------------------------


def _resolve_runtime(profile_name: str, a2a_config: dict) -> dict:
    """Read runtime config from a profile's ``config.yaml``.

    Args:
        profile_name: The profile name (subdirectory under ``profiles_dir``).
        a2a_config: Plugin configuration dict (from ``_read_a2a_config()``).

    Returns:
        Dict with optional keys: ``model``, ``provider``, ``base_url``,
        ``api_mode``. Returns empty dict if the profile config doesn't exist
        or can't be read.
    """
    profiles_dir = Path(
        os.path.expanduser(a2a_config.get("profiles_dir", DEFAULT_PROFILES_DIR))
    )
    config_path = profiles_dir / profile_name / "config.yaml"
    if not config_path.exists():
        return {}

    try:
        import yaml

        cfg = yaml.safe_load(config_path.read_text())
        if not isinstance(cfg, dict):
            return {}
        model_cfg = cfg.get("model", {})
        if not isinstance(model_cfg, dict):
            return {}
        return {
            "model": model_cfg.get("default"),
            "provider": model_cfg.get("provider"),
            "base_url": model_cfg.get("base_url"),
            "api_mode": model_cfg.get("api_mode"),
        }
    except Exception as exc:
        logger.debug(
            "a2a-server: failed to read profile config %s: %s",
            config_path,
            exc,
        )
        return {}


def _run_via_agent(
    goal: str,
    profile_name: str | None = None,
) -> TaskResult:
    """Dispatch a goal through a fresh ``AIAgent`` in the daemon thread.

    Replaces the old ``_dispatch_fn`` closure that called ``ctx.dispatch_tool``
    (``"delegate_task", ...)``, which fails in the A2A daemon thread because
    there is no active ``AIAgent`` session.

    Follows the ``AIAgent`` construction pattern from ``cron/scheduler.py:1437``.

    Args:
        goal: The user's request text to process.
        profile_name: Optional target profile name for routing.

    Returns:
        ``TaskResult(status="completed", data={"answer": response})`` on success,
        or ``TaskResult(status="failed", error=...)`` on failure.
    """
    task_id = str(uuid.uuid4())
    session_id = f"a2a_{task_id[:12]}"

    try:
        # 1. Resolve profile-level runtime config
        a2a_config = _read_a2a_config()
        runtime = _resolve_runtime(profile_name, a2a_config) if profile_name else {}

        # 2. Fall back to main Hermes config defaults for missing values
        from hermes_cli.config import load_config

        main_cfg = load_config()
        model_cfg = main_cfg.get("model", {}) if isinstance(main_cfg, dict) else {}
        if not isinstance(model_cfg, dict):
            model_cfg = {}

        model = runtime.get("model") or model_cfg.get("default") or ""
        provider = runtime.get("provider") or model_cfg.get("provider") or ""
        base_url = runtime.get("base_url") or model_cfg.get("base_url") or ""
        api_mode = runtime.get("api_mode") or model_cfg.get("api_mode") or ""

        # 3. Lazy-import AIAgent (avoids loading the full agent machinery
        #    at plugin registration time — same pattern as cron/scheduler.py)
        from run_agent import AIAgent

        agent = AIAgent(
            model=model or None,
            api_key=None,  # AIAgent resolves from env / config internally
            base_url=base_url or None,
            provider=provider or None,
            api_mode=api_mode or None,
            max_iterations=60,
            enabled_toolsets=[
                "terminal",
                "file",
                "web",
            ],
            disabled_toolsets=[
                "delegate_task",
                "clarify",
                "send_message",
                "memory",
                "cronjob",
            ],
            quiet_mode=True,
            load_soul_identity=True,
            skip_memory=True,
            skip_context_files=True,
            platform="a2a",
            session_id=session_id,
        )

        # 4. Run the agent and return the result
        response = agent.chat(goal)
        return TaskResult(
            status="completed",
            data={"answer": response},
        )

    except Exception as exc:
        logger.error(
            "a2a-server: _run_via_agent failed for profile '%s': %s",
            profile_name,
            exc,
            exc_info=True,
        )
        return TaskResult(
            status="failed",
            error=f"A2A dispatch error: {exc}",
        )


async def _connect_peers(mesh_client) -> None:
    """Background task: connect all configured mesh peers.

    Called fire-and-forget from the synchronous ``register()``. Logs
    per-peer success/failure — does not raise.
    """
    try:
        await mesh_client.connect_all()
    except Exception as exc:
        logger.error(
            "a2a-server: peer connection background task failed: %s",
            exc, exc_info=True,
        )


def _schedule_peer_connections(mesh_client) -> None:
    """Schedule peer connections if an event loop is running.

    ``register()`` is synchronous so we cannot ``await``. We fire
    the connect as a background asyncio task so it runs on the server's
    event loop. If no loop is running yet (rare at import time), the
    connections are deferred — the first A2A request will have to
    connect on-demand, which ``send_task`` handles gracefully by
    returning ``failed`` for unconnected peers.
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_connect_peers(mesh_client))
            logger.debug("a2a-server: scheduled async peer connections")
        else:
            logger.info(
                "a2a-server: event loop not yet running, "
                "peer connections deferred"
            )
    except RuntimeError:
        logger.info(
            "a2a-server: no event loop available, "
            "peer connections deferred"
        )


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
    # Peer Registry — load configured peers (Phase 2)
    # ------------------------------------------------------------------
    def _resolve_env(val: str) -> str:
        """Resolve ``${VAR_NAME}`` references in config values from env vars."""
        if val.startswith("${") and val.endswith("}"):
            return os.environ.get(val[2:-1], "")
        return val

    raw_peers: list[dict] = a2a_config.get("peers", [])
    peer_configs = [
        PeerConfig(
            name=p["name"],
            url=p["url"],
            api_key=_resolve_env(p.get("api_key", "")),
            cidr_allow=p.get("cidr_allow", []),
        )
        for p in raw_peers
    ]
    peer_registry = PeerRegistry(peer_configs)

    if peer_configs:
        logger.info(
            "a2a-server: PeerRegistry loaded — %d peer(s) configured: %s",
            len(peer_configs),
            ", ".join(p.name for p in peer_configs),
        )

    # ------------------------------------------------------------------
    # MeshPeerClient — outbound connections to configured peers (Phase 2+3)
    # ------------------------------------------------------------------
    from adapter.mesh_peer_client import MeshPeerClient

    mesh_client = MeshPeerClient(peer_registry, fc)

    # Fire-and-forget peer connections. We cannot await here because
    # register() is synchronous. If there is a running event loop we
    # schedule the connections; otherwise they are silently deferred
    # until the first A2A request arrives (lazy-fallback pattern below).
    _schedule_peer_connections(mesh_client)

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

    # NOTE: dispatch_fn is the module-level _run_via_agent (defined above),
    # which creates a fresh AIAgent directly instead of calling the
    # ctx.dispatch_tool("delegate_task", ...) path that fails outside an
    # active AIAgent session.
    executor = HermesExecutor(dispatch_fn=_run_via_agent, fc=fc, mesh_client=mesh_client)
    handler = DefaultRequestHandlerV2(
        agent_executor=executor,
        task_store=task_store,
        agent_card=agent_card,
    )
    context_builder = BearerTokenContextBuilder(peer_registry)
    jsonrpc_routes = create_jsonrpc_routes(
        request_handler=handler,
        rpc_url="/a2a/jsonrpc",
        context_builder=context_builder,
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
