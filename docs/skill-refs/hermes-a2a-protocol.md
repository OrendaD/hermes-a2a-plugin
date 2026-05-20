# Hermes A2A Protocol — Phase 3 Rebuild

> **Phase 3 is complete (May 20, 2026).** 177 tests. Three live endpoints: `GET /health`, `GET /.well-known/agent-card.json`, `POST /a2a/jsonrpc`. Full A2A v1.0 round-trip verified: SendMessage → FleetController routing → dispatch closure → TaskResult → A2A Message response.

## Architecture (Phase 3)

Three-layer design:

```
A2A SDK (Google v1.0.3)     — protocol framing, JSON-RPC, SSE, Agent Card signing
  ⬆
Proteus Adapter (this plugin) — Hermes-specific translation
  ⬆
Tesla Core (a2a-core v0.1)  — protocol-agnostic domain models + orchestration
```

| Layer | Repo | Responsibility | Tests |
|-------|------|---------------|-------|
| **Tesla Core** | `src/core/` in `a2a-plugin` | `TaskIntent`, `TaskResult`, `AgentCapability`, `FleetController`, `Orchestrator`, `ConversationGraph`. Zero A2A SDK imports. | 71 |
| **Proteus Adapter** | `src/adapter/` in `a2a-plugin` | Profile discovery → Agent Card building + JWS signing. `HermesExecutor` implementation (dispatch closure, FC routing). Session spawn via `ctx.dispatch_tool("delegate_task")`. | 106 |
| **Plugin Entry** | `src/a2a_plugin/` in `a2a-plugin` | `register()` orchestrates FC loading → handler construction → Starlette app → uvicorn daemon thread. Entry point `hermes_agent.plugins: a2a-server`. | — |
| **A2A SDK** | `a2a-sdk==1.0.3` in Hermes venv | Protobuf types, JSON-RPC dispatcher, Starlette routes, `InMemoryTaskStore`, `AgentExecutor` ABC. | — |

### Profile Discovery

Each Hermes profile declares its A2A capabilities in `config.yaml` under an `a2a:` section:

```yaml
# ~/.hermes/profiles/sherlock/config.yaml
model: claude-sonnet-4
a2a:
  intents: ["consultation", "research"]
  tags: ["research", "perception"]
  description: "Perception and research specialist"
  streaming: false
  push: false
```

Profiles without `a2a.intents` are skipped — not A2A-addressable.

The `discover_profiles()` function (in `src/adapter/profile_discovery.py`) scans a profiles directory, parses the `a2a:` section, and returns `list[AgentCapability]`. Used at plugin startup to register capabilities with the Fleet Controller and build the Agent Card.

### Agent Card Building

`build_agent_card()` (in `src/adapter/agent_card_builder.py`) translates `list[AgentCapability]` → `AgentCard` protobuf:

| AgentCapability → | AgentSkill |
|---|---|
| `profile_name` | `id = "skill/<name>"` |
| `display_name` | `name` |
| `description` | `description` |
| `intents + tags` | `tags[]` |
| `examples` | `examples[]` |

### Signing Key Management

Each profile has its own EC P-256 signing key stored in `~/.hermes/profiles/<name>/.env` as `A2A_SIGNING_KEY`:

```
# ~/.hermes/profiles/sherlock/.env
A2A_SIGNING_KEY=TFMwdExTMUNSV...
```

**Storage format:** The full PEM-encoded private key, base64-encoded into a single dotenv-safe line. No multiline PEM issues, no platform-specific Keychain/DPAPI/GNOME Keyring dependency.

**Lifecycle:**
1. First call to `ensure_keys(profile_dir)` → generates EC P-256 key via `cryptography` → base64-encodes PEM → appends to `<profile_dir>/.env`
2. Subsequent calls → reads `A2A_SIGNING_KEY` from env via `_load_env_file()` (internal `.env` parser, no `python-dotenv` need) → base64-decodes → uses PEM for JWS signing
3. `load_keys(profile_dir)` → same load path, raises `FileNotFoundError` if absent

**Key derivation:** `_derive_public_pem(private_pem)` extracts the public key from the private PEM via `cryptography.hazmat`. Only the private key is stored; the public key is derived on each load.

**Design rationale (from user conversation 2026-05-19):**
- `.env` is the existing Hermes pattern for per-profile secrets — `0o600`, no VC, cross-platform
- Base64 is pure ASCII, dotenv-safe (standard `.env` parsers can't handle multiline PEM values)
- No platform-specific API needed (macOS Keychain, DPAPI, GNOME Keyring all have different semantics)
- For enterprise KMS/HSM compliance: upgrade path is to replace `_load_env_file()` with a KMS-decrypt call, same `create_signer()` downstream
- Per-profile keys mean each Hermes profile has its own signing identity — no shared-key cross-profile contamination

### Session Spawn

`AgentExecutor.execute()` translates A2A `RequestContext` → Hermes `delegate_task` call:

```python
result_json = ctx.dispatch_tool("delegate_task", {
    "goal": payload["question"],
    "profile": target_profile,  # from Fleet Controller routing
})
```

Returns JSON with `summary`, `api_calls`, `tool_trace`, `tokens`. Adapter maps to `TaskResult` domain model.

### Server Model (V1)

Daemon thread — plugin `register()` starts uvicorn in a `threading.Thread(daemon=True)`:

```python
thread = threading.Thread(
    target=uvicorn.run,
    args=(app,),
    kwargs={"host": config.bind, "port": config.port, "log_level": "info"},
    daemon=True,
)
thread.start()
```

- Daemon threads are killed when the main Hermes process exits — no orphan risk
- No Hermes shutdown hook exists (VALID_HOOKS doesn't include load/unload)
- uvicorn 0.41.0 already present in Hermes venv (a2a-sdk[http-server] includes starlette, NOT uvicorn — installed separately)

### M3 Plugin Integration — The Full `register()` Pipeline

The plugin entry point (`src/a2a_plugin/__init__.py:register(ctx)`) runs four stages in order:

**M3.1 — Import verification.** All adapter and core imports resolved at load time. If pip install is stale, plugin fails early with a clear error message.

**M3.2 — Server lifecycle.** Starlette app built, uvicorn daemon thread started. Two routes:
- `GET /health` — liveness check
- `GET /.well-known/agent-card.json` — signed Agent Card via dynamic profile discovery (M1.4 route, not SDK's static route)

**M3.3 — FleetController + profile loading.** `discover_profiles()` scans `~/.hermes/profiles/` for `a2a:` config sections. Each discovered capability registered via `FleetControllerImpl.register_profile()`. Module-level `_fleet_controller` stored for M3.4 dispatch closure.

**M3.4 — HermesExecutor + handler wiring.**
- `build_agent_card(caps)` → AgentCard protobuf for SDK handler
- `InMemoryTaskStore()` — task persistence (SQLite deferred to Phase 3b)
- Dispatch closure captures `ctx.dispatch_tool("delegate_task", ...)`
- `HermesExecutor(dispatch_fn, fc)` → SDK-pure by constructor-injection
- `DefaultRequestHandlerV2(executor, task_store, agent_card)`
- `create_jsonrpc_routes(handler, "/a2a/jsonrpc")` → mounted on Starlette app

#### Dispatch Closure Pattern

```python
# Captures ctx (PluginContext) from register(). Called from HermesExecutor.execute()
# inside an A2A SDK asyncio task — sync dispatch_tool blocks only its own task.
def _dispatch_fn(goal: str, profile_name: str | None = None) -> TaskResult:
    args: dict[str, Any] = {"goal": goal}
    if profile_name:
        args["profile"] = profile_name
    try:
        result_json = ctx.dispatch_tool("delegate_task", args)
        result_data = json.loads(result_json)
        return TaskResult(
            status="completed",
            data={"answer": result_data.get("summary", str(result_data))},
        )
    except Exception as exc:
        return TaskResult(status="failed", error=f"Dispatch error: {exc}")
```

### Key SDK v1.0 Mapping (discovered during M0.3 validation)

| Item | Assumption | Actual (a2a-sdk 1.0.3) |
|------|-----------|----------------------|
| AgentCard.url | Top-level field | **Removed** — use `supported_interfaces[].url` |
| AgentProvider.origin | Named field | **Removed** — use `.url` and `.organization` |
| Task.state | Top-level field | **Removed** — use `Task.status(state=TaskState...)` |
| JSON-RPC method names | `tasks/get`, `message/send` | **PascalCase** — `GetTask`, `ListTasks`, `SendMessage` |
| Role enum | `user`, `agent` | **SCREAMING_SNAKE** — `ROLE_USER`, `ROLE_AGENT` |
| A2A-Version header | Optional | **Required** — defaults to `0.3`; must send `A2A-Version: 1.0` |
| AgentExecutor | `execute()` only | **`execute()` + `cancel()`** — both abstract |
| Descriptor truth | Spec docs are reliable | **`DESCRIPTOR.fields` is the single source of truth** — protobuf field names differ from spec examples |
| AgentCapabilities.push_notifications | Possibly absent | **Present** — field exists in protobuf descriptor |
| JSON serialization | `.to_json()` method | **`MessageToDict(card, preserving_proto_field_name=True)`** |
| SendMessage required fields | Minimal | **Requires** `message.message_id`, `role` as enum, `A2A-Version` header |

### Protobuf Field Introspection

Always validate field names against the actual installed SDK — not spec docs, not README, not memory:

```python
from a2a.types import AgentCard, Task, TaskStatus
for f in AgentCard.DESCRIPTOR.fields:
    print(f'{f.name}: type={f.type} label={f.label}')
for f in TaskStatus.DESCRIPTOR.fields:
    print(f'{f.name}')
```

This pattern saved M0.3 from assuming `Task.state` existed → found `Task.status(state=...)` instead.

### M2 — Agent Executor SDK Learnings (discovered 2026-05-19)

The M2.2 implementation revealed several SDK surface mismatches that a 30-second `python -c "from a2a.types import ..."` pass would've caught:

#### `TaskStatusUpdateEvent` Field Verification

```python
from a2a.types import TaskStatusUpdateEvent
print([f.name for f in TaskStatusUpdateEvent.DESCRIPTOR.fields])
# → ['task_id', 'context_id', 'status', 'metadata']
# NOT: 'id', 'final'
```

- **`id` is `task_id`** — protobuf field name differs from the parameter name in SDK examples
- **No `final` field** — terminal state is implicit in the `TaskState` enum value. Remove `final=True` from construction
- **`status` takes `TaskStatus(state=...)`** — same as M0.3's `Task`

#### `Part` Oneof Structure

```python
from a2a.types import Part
print([f.name for f in Part.DESCRIPTOR.fields])
# → ['text', 'raw', 'url', 'data', 'metadata', 'filename', 'media_type']
print([o.name for o in Part.DESCRIPTOR.oneofs])
# → ['content']
```

Key points:
- **No `file` field** — file attachments use a `url` or `raw` part + `filename` + `media_type` top-level fields
- **Oneof constraint** — a single `Part` can hold only one of `{text, raw, url, data}`. Creating `Part(text="hello", data={...})` via `ParseDict` raises `ParseError: should not have multiple content oneof fields`
- **`data` is `google.protobuf.Value`** — not a Python dict. Convert via `MessageToDict(part.data, preserving_proto_field_name=True)`
- **`metadata` is `google.protobuf.Struct`** — iterate via `.fields.items()` and convert each `Value` to Python

#### `Message` Construction

Use `ParseDict` for complex Messages (avoids oneof issues):

```python
from google.protobuf.json_format import ParseDict
from a2a.types import Message

msg = ParseDict({
    'message_id': 'msg-001',
    'role': 'ROLE_USER',          # string name works
    'parts': [{'text': 'hello'}],
    'metadata': {'intent_type': 'audit'}
}, Message())
```

- **`role` accepts string names** (`'ROLE_USER'`) — not just enum ints
- **`reference_task_ids` is `repeated string`** — pass as list

#### `RequestContext` Construction (for tests)

```python
from a2a.server.context import ServerCallContext
from a2a.server.agent_execution.context import RequestContext
from a2a.types import SendMessageRequest

smr = ParseDict({"message": msg_dict}, SendMessageRequest())
scc = ServerCallContext(state={})
ctx = RequestContext(
    call_context=scc,
    request=smr,
    task_id="task/abc",
    context_id="ctx-1",
)
```

- **Requires `call_context`** (ServerCallContext) — not optional
- **Requires `request`** (SendMessageRequest) — not just a `Message`
- **Properties** (`ctx.message`, `ctx.task_id`, `ctx.context_id`) derive from the `request` at construction

#### Event Emission Order in `execute()`

The `HermesExecutor.execute()` implementation emits events in a specific order that tests must match:

| Path | Order | `events[0]` | `events[-1]` |
|------|-------|-------------|-------------|
| No route / exception / failed result | `TaskStatusUpdateEvent(FAILED)` → `Message(error)` | `TaskStatusUpdateEvent` | `Message` |
| Success with answer | `Message(answer)` → `TaskStatusUpdateEvent(COMPLETED)` | `Message` | `TaskStatusUpdateEvent` |
| Success without answer | `TaskStatusUpdateEvent(COMPLETED)` | — | `TaskStatusUpdateEvent` |

Test pattern:

```python
# Failure path — check events[0] (first = status event)
first = eq.events[0]
assert isinstance(first, TaskStatusUpdateEvent)
assert first.status.state == TaskState.TASK_STATE_FAILED

# Success path — check events[-1] (last = status event)
last = eq.events[-1]
assert isinstance(last, TaskStatusUpdateEvent)
assert last.status.state == TaskState.TASK_STATE_COMPLETED
```

### Discovery Path (Debugging M0.3)
