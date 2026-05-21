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
from adapter.hermes_adapter import HermesA2AAdapter
from adapter.hermes_executor import HermesExecutor
from adapter.peer_registry import PeerConfig, PeerRegistry
from adapter.profile_discovery import discover_profiles
from adapter.rate_limit_middleware import RateLimitMiddleware
from adapter.version_middleware import A2AVersionMiddleware
from core.domain.models.result import TaskResult
from core.fleet_controller import FleetControllerImpl
from core.orchestrator import OrchestratorImpl

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

# Known config keys — used by the env-var override logic in
# _read_a2a_config().  Each key maps to a type so A2A_<KEY> env vars
# are properly coerced from string to the expected Python type.
CONFIG_KEYS: dict[str, type] = {
    "port": int,
    "bind": str,
    "node_name": str,
    "node_id": str,
    "profiles_dir": str,
    "signing_profile": str,
    "rate_limit": int,
    "peers": list,
}

# Mapping from type → (coercer, boolish_set) for _coerce_env_value.
# We keep this separate so the coercion logic can be unit-tested and
# extended without touching CONFIG_KEYS.
_BOOL_TRUE = frozenset({"1", "true", "yes"})


def _coerce_env_value(key: str, raw: str, expected_type: type) -> Any:
    """Parse a string from an environment variable into *expected_type*.

    Supported types:
      - ``int``  → ``int(raw)``; raises ``ValueError`` on junk.
      - ``bool`` → ``raw.lower() in ("1", "true", "yes")``.
      - ``str``  → ``raw`` as-is.
      - ``list`` → ``json.loads(raw)`` (must be a JSON array).

    Raises:
        ValueError if the value cannot be coerced.
    """
    if expected_type is int:
        try:
            return int(raw)
        except ValueError:
            raise ValueError(
                f"A2A_{key.upper()}={raw!r} is not a valid integer"
            )

    if expected_type is bool:
        return raw.strip().lower() in _BOOL_TRUE

    if expected_type is list:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"A2A_{key.upper()}={raw!r} is not valid JSON: {exc}"
            )
        if not isinstance(parsed, list):
            raise ValueError(
                f"A2A_{key.upper()}={raw!r} must be a JSON array"
            )
        return parsed

    # str (default fallback)
    return raw


def _read_a2a_config() -> dict[str, Any]:
    """Read the ``a2a:`` section from ``~/.hermes/config.yaml``.

    Falls back to defaults for any missing key so the plugin works
    without explicit configuration.

    Environment variable overrides (applied on top of YAML):

        ``A2A_<KEY>`` — where ``<KEY>`` is any key in ``CONFIG_KEYS``
        uppercased.  Values are coerced to the expected type:

        * ``int`` keys (``port``, ``rate_limit``): ``int()``
        * ``list`` keys (``peers``): ``json.loads()`` (must be array)
        * ``str`` keys: taken as-is

    Unknown env vars (``A2A_<KEY>`` where ``KEY`` is not in
    ``CONFIG_KEYS``) are silently ignored.
    """
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        a2a = cfg.get("a2a", {})
    except Exception:
        logger.warning("a2a-server: could not load Hermes config, using defaults")
        a2a = {}

    config = {
        "port": a2a.get("port", DEFAULT_PORT),
        "bind": a2a.get("bind", DEFAULT_BIND),
        "node_name": a2a.get("node_name", DEFAULT_NODE_NAME),
        "profiles_dir": a2a.get("profiles_dir", DEFAULT_PROFILES_DIR),
        "node_id": a2a.get("node_id", "local"),
        "signing_profile": a2a.get("signing_profile"),
        "peers": a2a.get("peers", []),
        "rate_limit": a2a.get("rate_limit", 0),
    }

    # Overlay environment variable overrides on top of the YAML baseline.
    for key, expected_type in CONFIG_KEYS.items():
        env_val = os.environ.get(f"A2A_{key.upper()}")
        if env_val is not None:
            config[key] = _coerce_env_value(key, env_val, expected_type)

    return config


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
    app.add_middleware(
        RateLimitMiddleware,
        rate_limit=config.get("rate_limit", 0),
    )
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


def _recover_tasks(orchestrator, task_store):
    """Reconstruct conversation graphs and flag mid-flight tasks after restart.

    Called at plugin startup after ``DatabaseTaskStore`` is initialized.
    Iterates over stored SDK tasks, reconstructs the orchestrator's
    in-memory conversation graphs, and flags any non-terminal tasks
    for human review (``input_required`` with interruption message).

    This is a best-effort recovery. Tasks with terminal states
    (completed, failed, cancelled) are ignored — they are preserved
    in the DB for history/audit but don't need graph reconstruction.

    Args:
        orchestrator: The ``OrchestratorImpl`` instance to register
            recovered tasks with.
        task_store: The ``DatabaseTaskStore`` instance to scan for
            in-flight tasks.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        logger.warning(
            "a2a-server: no event loop for task recovery — deferring"
        )
        loop = None

    if loop is None or not loop.is_running():
        logger.info(
            "a2a-server: event loop not running, skipping task recovery"
        )
        return

    async def _scan():
        try:
            from a2a.types.a2a_pb2 import TaskState, ListTasksRequest
            from a2a.server.context import ServerCallContext

            # Build a minimal ListTasksRequest to retrieve tasks
            params = ListTasksRequest()
            context = ServerCallContext(state={})
            page = await task_store.list(params, context)

            recovered = 0
            in_flight = 0
            for stored_task in page.tasks:
                recovered += 1
                state = stored_task.status.state
                # Check if this task is in a non-terminal, non-cancelled state
                if state not in (
                    TaskState.TASK_STATE_COMPLETED,
                    TaskState.TASK_STATE_FAILED,
                    TaskState.TASK_STATE_CANCELED,
                ):
                    in_flight += 1
                    task_id = stored_task.id
                    context_id = stored_task.context_id or task_id
                    orchestrator.register_task(
                        task_id=task_id,
                        context_id=context_id,
                    )
                    # Flag for human review
                    orchestrator.on_status_change(
                        task_id,
                        "input_required",
                        TaskResult(
                            status="input_required",
                            data={
                                "question": (
                                    "Task was interrupted by gateway restart. "
                                    "Please review the current state and "
                                    "continue if appropriate."
                                ),
                            },
                        ),
                    )

            logger.info(
                "a2a-server: task recovery complete — %d task(s) scanned, "
                "%d in-flight task(s) flagged for review",
                recovered,
                in_flight,
            )
        except Exception as exc:
            logger.error(
                "a2a-server: task recovery failed: %s",
                exc,
                exc_info=True,
            )

    loop.create_task(_scan())


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

    # ------------------------------------------------------------------
    # DatabaseTaskStore — SQLite persistence (Phase 4)
    # Replaces InMemoryTaskStore so tasks survive gateway restarts.
    # ------------------------------------------------------------------
    from a2a.server.tasks import DatabaseTaskStore
    from sqlalchemy.ext.asyncio import create_async_engine

    db_path = os.path.expanduser("~/.hermes/a2a_tasks.db")
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    db_url = f"sqlite+aiosqlite:///{db_path}"
    db_engine = create_async_engine(db_url)
    task_store = DatabaseTaskStore(engine=db_engine)
    logger.info(
        "a2a-server: using DatabaseTaskStore at %s",
        db_path,
    )

    # ------------------------------------------------------------------
    # AuditLogger — JSONL append-only audit trail (Phase 4)
    # ------------------------------------------------------------------
    from adapter.audit_logger import AuditLogger

    audit_log_path = a2a_config.get("audit_log_path", "~/.hermes/a2a_audit.jsonl")
    audit_logger = AuditLogger(log_path=audit_log_path)
    logger.info("a2a-server: AuditLogger initialized at %s", audit_logger.log_path)

    # ------------------------------------------------------------------
    # Orchestration wiring (Phase 4)
    # ------------------------------------------------------------------
    adapter = HermesA2AAdapter(
        dispatch_fn=_run_via_agent,
        fc=fc,
        mesh_client=mesh_client,
    )
    orchestrator = OrchestratorImpl(
        fleet_controller=fc,
        adapter=adapter,
    )

    # NOTE: dispatch_fn is the module-level _run_via_agent (defined above),
    # which creates a fresh AIAgent directly instead of calling the
    # ctx.dispatch_tool("delegate_task", ...) path that fails outside an
    # active AIAgent session.
    executor = HermesExecutor(
        dispatch_fn=_run_via_agent,
        fc=fc,
        mesh_client=mesh_client,
        orchestrator=orchestrator,
        audit_logger=audit_logger,
        node_id=node_id,
    )

    # Gateway restart recovery — flag in-flight tasks for review
    _recover_tasks(orchestrator, task_store)
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
