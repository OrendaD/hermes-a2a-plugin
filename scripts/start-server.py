#!/usr/bin/env python3
"""Start the A2A server as an independent process.

Usage:
    python start-server.py [--port PORT]

Runs independently of the Hermes plugin system. For the plugin-based
auto-loading (on gateway startup), the entry point is registered at:
    hermes_agent.plugins.a2a-server = a2a_plugin

The dispatch function currently returns mock responses. Replace with
a real Hermes delegation mechanism when running inside the gateway.
"""

import sys
import os
import json
import time
import argparse

# Add plugin src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from adapter.hermes_executor import HermesExecutor
from adapter.agent_card_builder import build_agent_card
from adapter.profile_discovery import discover_profiles
from core.fleet_controller import FleetControllerImpl
from core.domain.models.result import TaskResult
from core.domain.models.intent import TaskIntent

from a2a.types import AgentCard, AgentCapabilities
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore


def real_dispatch(goal: str, profile_name: str | None = None) -> TaskResult:
    """Dispatch a goal via Hermes delegation.

    In standalone mode, this is a placeholder. When running inside the
    Hermes gateway process, replace with ctx.dispatch_tool('delegate_task').
    """
    # TODO: Replace with actual Hermes delegation.
    #   The delegate_task tool requires the Hermes gateway's tool registry,
    #   which is only available inside the gateway process.
    #   Options:
    #     1. Run server via PluginManager (auto-load on gateway restart)
    #     2. Use Hermes MCP server mode for delegation
    #     3. Communicate via gateway socket/API
    return TaskResult(
        status="completed",
        data={
            "answer": f"[{profile_name or 'default'}] Dispatched: {goal}",
            "_mode": "standalone",
        },
    )


def build_app(port: int = 9696):
    """Build and return the A2A Starlette application."""
    config = {
        "bind": "127.0.0.1",
        "port": port,
        "node_name": "proteus-a2a",
        "node_id": "local",
        "profiles_dir": os.path.expanduser("~/.hermes/profiles"),
        "log_level": "INFO",
        "cors": {"origins": ["*"]},
    }

    # Fleet Controller with local profiles
    fc = FleetControllerImpl()
    fc._local_node_id = config["node_id"]
    caps = discover_profiles(config["profiles_dir"], node_id=config["node_id"])
    for cap in caps:
        fc.register_profile(cap)

    print(f"Profiles loaded: {len(caps)}")
    for cap in caps:
        print(f"  {cap.profile_name}: intents={list(cap.intents)}")

    # AgentCard
    agent_card = build_agent_card(
        caps,
        node_name=config["node_name"],
        interface_url=f"http://{config['bind']}:{config['port']}",
    )

    # Executor with dispatch function
    executor = HermesExecutor(dispatch_fn=real_dispatch, fc=fc)
    handler = DefaultRequestHandlerV2(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    jsonrpc_routes = create_jsonrpc_routes(handler, "/a2a/jsonrpc")
    from a2a_plugin import _build_app as _build_starlette_app
    return _build_starlette_app(config, jsonrpc_routes=jsonrpc_routes), config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start A2A server")
    parser.add_argument("--port", type=int, default=9696, help="Port to bind")
    args = parser.parse_args()

    app, config = build_app(port=args.port)

    import uvicorn
    print(f"\nStarting A2A server on {config['bind']}:{config['port']}")
    print(f"  Agent Card: http://{config['bind']}:{config['port']}/.well-known/agent-card.json")
    print(f"  JSON-RPC:   POST http://{config['bind']}:{config['port']}/a2a/jsonrpc")
    print(f"  Profiles:   {config['profiles_dir']}")
    print()

    uvicorn.run(
        app,
        host=config["bind"],
        port=config["port"],
        log_level=config["log_level"].lower(),
    )
