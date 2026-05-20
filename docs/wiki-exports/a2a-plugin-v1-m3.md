---
title: M3 — Plugin Integration Implementation Plan
created: 2026-05-19
updated: 2026-05-20
type: planning
status: completed
tags: [a2a, plugin, architecture, milestone, planning]
parent: planning/a2a-plugin-v1
confidence: high
---

# M3 — A2A Plugin: Hermes Plugin + A2A HTTP Server

**Parent goal:** [[planning/a2a-plugin-v1|A2A v1.0 Plugin]]
**Phase:** Phase 3 in the task graph — Adapter (The Plugin)

## What We're Building

A Hermes plugin that starts an A2A HTTP server inside the Hermes agent process. The plugin wires together profile discovery → FleetController → AgentExecutor → Starlette routes → uvicorn background thread.

## Research Findings (source-verified 2026-05-19)

All 8 research items were resolved by reading source code. No assumptions.

### Plugin Entry Point Convention

**Source:** `plugins/observability/langfuse/__init__.py:register(ctx)`, `hermes_cli/plugins.py:1135-1202`

Every plugin needs:
1. `plugin.yaml` — name, version, kind, requires_env, hooks
2. `__init__.py` with `def register(ctx)` — **returns None**, not a server entry point
3. The langfuse plugin only registers hooks — no long-running processes exist in any shipped Hermes plugin

### Plugin Discovery Paths

**Source:** `hermes_cli/plugins.py:770-829`

Four sources, later overrides earlier:
1. **Bundled:** `<repo>/plugins/<name>/plugin.yaml`
2. **User:** `~/.hermes/plugins/<name>/plugin.yaml` ← **development path**
3. **Project:** `./.hermes/plugins/<name>/plugin.yaml` (needs `HERMES_ENABLE_PROJECT_PLUGINS=1`)
4. **Entrypoint:** pip-installed with `hermes_agent.plugins` entry point group

**Development symlink works.** The scanner uses `pathlib.Path.iterdir()` + `.is_dir()` which follows symlinks to target directories.

### Dispatch Tool is Sync (and that's fine)

**Source:** `hermes_cli/plugins.py:468-495`, `tools/registry.py:390-416`

`ctx.dispatch_tool()` returns `str` (sync). When the handler is async (`delegate_task`), the registry bridges via `_run_async()` which spawns a disposable thread if there's already a running event loop.

**Implication for A2A:** Each inbound A2A request runs as its own asyncio task (`active_task.subscribe()` → `asyncio.create_task()`). Blocking one dispatch on a subagent (30+ seconds) doesn't stall concurrent requests — they're independent tasks on the event loop.

### SDK Agent Card Route — Use Our M1.4 Route

**Source:** `venv/.../a2a/server/routes/agent_card_routes.py:31-55`

The SDK's `create_agent_card_routes()` just serializes a pre-built `AgentCard` protobuf at `/.well-known/agent-card.json`. No profile discovery, no signing, no dynamic content.

**Decision:** Use our own `create_agent_card_route()` from the adapter layer (M1.4) — it does the full pipeline: discover profiles → build card → sign with ES256.

### InMemoryTaskStore Defaults

**Source:** `venv/.../a2a/server/tasks/inmemory_task_store.py:25-33`

Constructor with no arguments uses `resolve_user_scope` as default `owner_resolver`. Handles unauthenticated `ServerCallContext` correctly.

### Uvicorn Already Installed

Confirmed: uvicorn 0.41.0 in `~/.hermes/hermes-agent/venv`. No additional dependency needed for the HTTP server layer.

**Note:** The `a2a-sdk[http-server]` extra includes `starlette` and `sse-starlette` but NOT `uvicorn`. Both are already available.

### No Existing Hermes Plugin Starts an HTTP Server

This is uncharted territory. **Approach:** Start uvicorn in a daemon thread during `register(ctx)`. Daemon threads are killed when the main process exits — no orphan risk. No Hermes shutdown hook is needed (no existing hooks for server lifecycle).

## Red-Team Q&A (2026-05-19)

Three questions asked to challenge assumptions before writing conclusions:

| # | Question | Answer | Source |
|---|----------|--------|--------|
| Q1 | Does the plugin scanner follow symlinks? | Yes — `iterdir()` + `.is_dir()` on `pathlib.Path` follows symlinks to target directories | `plugins.py:973-974` |
| Q2 | Does sync `dispatch_tool` block the entire A2A event loop? | No — each request gets its own asyncio task. `_run_async()` spawns a thread if a running loop is detected | `plugins.py:468-495`, `tools/registry.py:83-93` |
| Q3 | How to avoid orphan HTTP servers on Hermes exit? | Daemon thread (`threading.Thread(daemon=True)`). Killed on main process exit. No Hermes shutdown hook exists for this. | Physical reasoning + `plugins.py:142-144` (hooks don't include shutdown) |

## Configuration

Read from `~/.hermes/config.yaml` under an `a2a:` key, same pattern as all other plugins:

```python
from hermes_cli.config import load_config

def get_a2a_config():
    config = load_config()
    a2a = config.get("a2a", {})
    return {
        "port": a2a.get("port", 8081),
        "bind": a2a.get("bind", "127.0.0.1"),
        "profiles_dir": a2a.get("profiles_dir", "~/.hermes/profiles"),
        "node_name": a2a.get("node_name", "hermes-a2a-node"),
    }
```

## Dependencies

```toml
[project]
dependencies = [
    "a2a-sdk[http-server]>=1.0.0",
    "uvicorn>=0.30.0",
]
```

(uvicorn 0.41.0 already present in Hermes venv — listed for explicit declaration in pyproject.toml)

## Implementation Order

### 3.1 — Plugin scaffolding
- `src/a2a_plugin/plugin.yaml`: name `a2a-server`, kind `standalone`, no hooks
- `src/a2a_plugin/__init__.py`: `register(ctx)` that logs success and verifies adapter imports
- `pyproject.toml`: entry point `hermes_agent.plugins → a2a-server = a2a_plugin`
- `python -m pip install -e .` in Hermes venv
- Verify: `hermes plugins list` shows a2a-server as enabled

### 3.2 — Server lifecycle ✅
- ✅ Start uvicorn in daemon thread during `register(ctx)`
  - `_build_app()` constructs Starlette app with `/health` + M1.4 Agent Card route
  - `_start_server()` launches uvicorn via daemon thread
  - Double-register guard prevents startup on hot-reload
- ✅ Daemon tear-down handles Hermes exit (no orphan risk)
- ✅ Verified: `GET /health` → 200, `GET /.well-known/agent-card.json` → signed Agent Card
- ✅ Full test suite: 177/177 pass, 1.62s

### 3.3 — FleetController + profile loading ✅
- ✅ Construct `FleetControllerImpl` in `register(ctx)`, set local node_id
- ✅ Call `discover_profiles(profiles_dir)` and register each capability
- ✅ Handle empty profile directory gracefully — 0 profiles registered, server still starts
- ✅ Module-level `_fleet_controller` held for M3.4 dispatch closure
- ✅ Config-driven profiles_dir path (defaults to `~/.hermes/profiles`)
- ✅ Tested: 0 profiles when none have `a2a:` config, FC routes return `unavailable` cleanly

### 3.4 — Full integration ✅
- ✅ `HermesExecutor(dispatch_fn, fc)` wired in `register()`
  - Dispatch closure captures `ctx.dispatch_tool("delegate_task", ...)`
  - Maps sub-agent JSON result → `TaskResult` with `data["answer"]`
  - Error handling: dispatch failures return `TaskResult(status="failed")`
- ✅ `DefaultRequestHandlerV2(executor, task_store, agent_card)` constructed
  - AgentCard built from discovered profiles via `build_agent_card()` (M1.2)
  - Falls back to minimal AgentCard when 0 profiles discovered
  - `InMemoryTaskStore()` for task persistence (SQLite deferred)
- ✅ JSON-RPC routes mounted at `POST /a2a/jsonrpc`
- ✅ Full smoke test: `SendMessage` → FC routes → dispatch → response
- ✅ Agent Card dynamic profile inclusion verified
- ✅ All 177 tests pass, 1.39s
- ⏳ Cross-node test (Proteus ↔ Tesla) — requires Tesla client setup and profile configs
- ⏳ SQLite persistence — deferred to Phase 3b

## Research Checklist

- [x] **P1** — Read langfuse plugin `register()` pattern — simple hook registration, no server lifecycle
- [x] **P1** — Read `PluginContext.dispatch_tool()` — sync, bridges async via `_run_async()`
- [x] **P1** — Check `create_agent_card_routes()` — too simple, use our M1.4 route
- [x] **P1** — Check `create_jsonrpc_routes()` — returns `list[Route]`, takes `RequestHandler` + `rpc_url`
- [x] **P2** — Read `InMemoryTaskStore.__init__()` — default `owner_resolver` handles unauthenticated users
- [x] **P2** — Plugin discovery paths — symlinks work, `iterdir()` follows them
- [x] **P2** — Verify `a2a-sdk[http-server]` — includes starlette + sse-starlette, NOT uvicorn
- [x] **P3** — No existing HTTP server plugin — daemon thread is the right pattern
- [x] Config pattern — `from hermes_cli.config import load_config` then `config.get("a2a", {})`
- [x] Uvicorn available? — Yes, 0.41.0 in Hermes venv

## Related Pages

- [[planning/a2a-plugin-v1]] — Parent goal: overall project record, decisions, task graph
- [[subsystem/a2a]] — Deprecated legacy plugin architecture (historical reference only)
- `webgui-files/m3-planning.md` — Working doc in session workspace (may not survive)
