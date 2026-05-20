# A2A Adapter Integration Patterns

> Hermes plugin that implements the A2A (Agent-to-Agent) protocol using the `a2a-sdk` library and Tesla's `a2a-core` package.

## SDK Version & Extras

- Package: `a2a-sdk==1.0.3`
- Extras: `[http-server,signing,sqlite]` — Starlette routes, JWS signing, SQLAlchemy persistence
- Pip install: `pip install "a2a-sdk[http-server,signing,sqlite]"`

## Key Import Paths (as of 1.0.3)

| What | Import Path |
|------|-------------|
| Abstract executor | `a2a.server.agent_execution.agent_executor.AgentExecutor` |
| Request handler (v2) | `a2a.server.request_handlers.default_request_handler_v2.DefaultRequestHandlerV2` |
| Context builder | `a2a.server.request_handlers.default_request_handler_v2.SimpleRequestContextBuilder` |
| Starlette routes | `a2a.server.routes.jsonrpc_routes.create_jsonrpc_routes` |
| Task store (SQLite) | `a2a.server.tasks.database_task_store.DatabaseTaskStore` |
| Task store (memory) | `a2a.server.tasks.inmemory_task_store.InMemoryTaskStore` |
| Event queue | `a2a.server.events.event_queue.EventQueue` |
| Request context (input) | `a2a.server.agent_execution.context.RequestContext` |
| Server call context | `a2a.server.context.ServerCallContext` |
| Client | `a2a.client.client.Client` |
| JWS signer/verifier | `a2a.utils.signing.create_agent_card_signer` / `create_signature_verifier` |
| Protocol types | `a2a.types` — Task, TaskState, AgentCard, AgentSkill, Message, Part, etc. |

## AgentCard Construction

AgentCard is a protobuf message. Fields available (per protobuf descriptor):

```
name, description, version, documentation_url, icon_url,
provider (AgentProvider), capabilities (AgentCapabilities),
default_input_modes, default_output_modes,
skills (repeated AgentSkill),
supported_interfaces (repeated AgentInterface),
security_schemes (repeated SecurityScheme),
security_requirements (repeated SecurityRequirement),
signatures (repeated AgentCardSignature)
```

Notably absent: no `url` field. Endpoint is communicated via `supported_interfaces`.

## Wiring Pattern

```python
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from a2a.server.request_handlers.default_request_handler_v2 import (
    DefaultRequestHandlerV2, SimpleRequestContextBuilder,
)
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.agent_execution.agent_executor import AgentExecutor
from sqlalchemy.ext.asyncio import create_async_engine

# 1. Implement AgentExecutor
class MyExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        # Read context.task_id, context.message (SendMessageRequest)
        # Publish Task, TaskStatusUpdateEvent, TaskArtifactUpdateEvent to event_queue
        ...

# 2. Create task store
engine = create_async_engine("sqlite+aiosqlite:///path/to/tasks.db")
task_store = DatabaseTaskStore(engine=engine, create_table=True)

# 3. Build AgentCard
from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from google.protobuf.json_format import MessageToDict
card = AgentCard(
    name="Proteus",
    description="Hermes agent via A2A protocol",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),  # push field name varies
    default_input_modes=["text"],
    default_output_modes=["text"],
)

# 4. Create handler
handler = DefaultRequestHandlerV2(
    agent_executor=MyExecutor(),
    task_store=task_store,
    agent_card=card,
)

# 5. Wire JSON-RPC routes
routes = create_jsonrpc_routes(handler, rpc_url="/a2a/jsonrpc")

# 6. Create Starlette app
app = Starlette(routes=[Route("/.well-known/agent-card.json", ...), *routes])

# 7. Run with uvicorn
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=8081)
```

## Server Lifecycle (Plugin Integration)

Two models:

### V1 — Daemon Thread (simpler, no subprocess management)

Plugin's `register()` builds a Starlette app and starts uvicorn in a daemon thread:

```python
import threading
import uvicorn
from starlette.applications import Starlette

def register(ctx):
    app = Starlette(routes=[...])
    thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": 8081, "log_level": "info"},
        daemon=True,
    )
    thread.start()
    # register() returns immediately — server runs in background
```

**Why daemon thread over subprocess:**
- No `atexit` handler needed — daemon threads are killed when the main process exits
- No stderr pipe management or zombie risk
- Access to the same Python process — imports, config, and PluginContext are shared
- Simpler testing with `TestClient` (no subprocess coordination)

**Considerations:**
- Daemon threads are killed abruptly on process exit — in-flight A2A requests get TCP reset. Acceptable for v1 (stateless, no data corruption).
- `uvicorn.run()` internally installs signal handlers, but Python only delivers signals to the main thread — they never fire in the daemon thread. The `should_exit`/`force_exit` flags handle shutdown without signal plumbing.
- Add a module-level `_server_started` guard to prevent double-start if `register()` is ever called twice.
- Mount `GET /health` for a simple liveness check alongside the A2A routes.

**Full pattern from production code (src/ layout, entry-point discovery):**

```python
"""a2a_plugin/__init__.py"""
import threading, uvicorn, os
from pathlib import Path
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

_a2a_server_started = False

def _read_a2a_config():
    try:
        from hermes_cli.config import load_config
        a2a = load_config().get("a2a", {})
    except Exception:
        a2a = {}
    return {"port": a2a.get("port", 8081), "bind": a2a.get("bind", "127.0.0.1")}

def _build_app(config):
    async def _health(request):
        return JSONResponse({"status": "ok", "service": "a2a-server"})
    return Starlette(routes=[Route("/health", endpoint=_health, methods=["GET"])])

def _start_server(app, config):
    thread = threading.Thread(
        target=uvicorn.run, args=(app,),
        kwargs={"host": config["bind"], "port": config["port"], "log_level": "info"},
        daemon=True,
    )
    thread.start()

def register(ctx):
    global _a2a_server_started
    if _a2a_server_started:
        return
    _a2a_server_started = True
    cfg = _read_a2a_config()
    _start_server(_build_app(cfg), cfg)
```

This pattern was proven on macOS 15.7 (Intel) with uvicorn 0.41.0, Starlette 0.46.x, and Hermes WebUI. The server starts in <1 second and responds to /health and /.well-known/agent-card.json requests immediately.

### Alternative — Subprocess (controlled by plugin)

Plugin's `register()` spawns the a2a server as a child process:

```python
import subprocess, atexit

def register(ctx):
    proc = subprocess.Popen(
        [sys.executable, "-m", "a2a_adapter.server"],  # adapter's server module
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    atexit.register(lambda: proc.terminate() or proc.wait(timeout=5))
```

Benefits: clean lifecycle, no Hermes plugin API dependency for server ops. Works identically Linux/macOS. Better for production where `systemd` or `launchd` manages the server independently.

### Production — Standalone systemd/launchd service

A2A server runs as its own service. Plugin becomes a thin client that discovers the server via localhost. Best for multi-node deployments where the server must survive gateway restarts.

## Session Spawn for Task Execution

Use `ctx.dispatch_tool("delegate_task", ...)` to run a Hermes agent session:

```python
result_json = ctx.dispatch_tool("delegate_task", {
    "goal": question,
    "profile": target_profile,       # FC-routed profile name
    "toolsets": ["terminal", "file", "web"],
    "skills": ["systematic-research"],
})
```

Returns JSON string with result summary. Supports profile targeting for Fleet Controller routing. Works in both CLI and gateway modes.

## Profile Capability Discovery

A `a2a:` section in profile `config.yaml` declares A2A capabilities:

```yaml
# ~/.hermes/profiles/ray/config.yaml
a2a:
  intents: ["diagnose", "consultation"]
  tags: ["linux", "nginx", "health-check"]
  streaming: false
  push: false
```

Hermes's `yaml.safe_load` passes through unknown keys — no Hermes code reads the `a2a:` key, so upgrades are safe. Profiles without `a2a.intents` are silently excluded from A2A discovery.

## Pitfalls

- **AgentCard protobuf schema** does not match spec examples exactly. Always inspect `AgentCard.DESCRIPTOR.fields` before building.
- **DatabaseTaskStore requires SQLAlchemy with async engine** — `create_async_engine("sqlite+aiosqlite:///path")`, not `create_engine`.
- **InMemoryTaskStore** is fine for dev but tasks are lost on restart. Use `DatabaseTaskStore` for production.
- **DefaultRequestHandlerV2**, not v1 — v1 may not exist in your SDK version. Check `default_request_handler_v2` module.
- **create_jsonrpc_routes** returns a list of Starlette Route objects — mount them alongside other routes, don't try to run them standalone.
- **`pip install -e`** may resolve to a different Python's site-packages (e.g., anaconda3's 3.12 when venv is 3.11). Use `--target "$(python -c 'import site; print(site.getsitepackages()[0])')"` to force correct venv.
