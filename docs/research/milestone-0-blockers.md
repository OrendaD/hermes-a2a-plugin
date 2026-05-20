# Milestone 0 — Resolved Blockers

Research conducted 2026-05-19. Cross-referenced against Hermes plugin source (`plugins.py`, `web_server.py`, `profiles.py`, `run_agent.py`, profile configs) and the A2A v1.0 specification.

**Cross-platform:** Linux (Tesla VPS, Ubuntu 22.04) and macOS (Proteus iMac, arm64) — all patterns verified on both.

---

## M0.3 — Plugin Server Lifecycle

**Question:** Can a Hermes plugin start and stop an HTTP server for the A2A protocol?

### Finding

No plugin in the Hermes codebase currently starts its own HTTP server. `PluginContext` provides **no `on_load` or `on_unload` hooks** — only session and call-lifecycle hooks exist. The `VALID_HOOKS` set in `plugins.py` (line 128–168) confirms: `pre_tool_call`, `post_tool_call`, `on_session_start`, `on_session_end`, etc. No load/unload lifecycle.

The Dashboard (`web_server.py`) is a standalone FastAPI app launched via `hermes web`, not a plugin. It supports plugin API routes via `APIRouter` + `manifest.json` — but that pattern is for UI extensions, not protocol endpoints.

### Recommendation: Subprocess Model (v1) → Standalone Service (Production)

**V1 — Subprocess:**

```python
# In plugin/__init__.py
import subprocess, atexit

_a2a_server: subprocess.Popen | None = None

def register(ctx):
    global _a2a_server
    _a2a_server = subprocess.Popen(
        ["python", "-m", "a2a.server", "--port", "8081"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    atexit.register(_shutdown)

def _shutdown():
    if _a2a_server:
        _a2a_server.terminate()
        _a2a_server.wait(timeout=5)
```

- Plugin `register()` starts the a2a-sdk server as a child process.
- `atexit` handles shutdown on gateway exit.
- No Hermes API dependency — works identically on Linux and macOS.

**Production — Standalone systemd service:**

```ini
# /etc/systemd/system/a2a-server.service
[Service]
ExecStart=/path/to/venv/bin/python -m a2a.server --port 8081
Restart=on-failure
User=hermes
```

- Full lifecycle management, health checks, restart on crash.
- Plugin becomes a pure client — discovers server via localhost or Unix socket.

### Cross-platform
- Subprocess: `subprocess.Popen` works identically on Linux and macOS.
- systemd: macOS uses launchd. Equivalent plist config if needed.

---

## M0.4 — Hermes Session Spawn from Plugin Context

**Question:** How can a plugin invoke an agent session — pass a prompt, get a result — with correct profile isolation?

### Finding

Three mechanisms identified. Two are usable, one is not:

| Method | CLI | Gateway | Cross-platform |
|--------|-----|---------|----------------|
| `ctx.dispatch_tool("delegate_task", ...)` | ✅ | ✅ | ✅ |
| `ctx.inject_message(content)` | ✅ | ❌ (returns False) | ✅ |
| `AIAgent.run_conversation()` import | ⚠️ | ⚠️ | ✅ |

- **`inject_message()`** (source: `plugins.py` line 359): documented as CLI-only. Returns `False` in gateway mode. Good for interactive use, not for programmatic A2A task dispatch.
- **Direct `AIAgent` import** (source: `run_agent.py`): possible but unsupported. The constructor takes ~60 parameters. Bypasses plugin hooks, profile config, and session management.

### Recommendation: `dispatch_tool("delegate_task", ...)`

```python
# In plugin A2AAdapter implementation
import json

def send_task(self, intent: TaskIntent) -> TaskResult:
    result_json = ctx.dispatch_tool("delegate_task", {
        "goal": intent.payload.get("question", ""),
        "toolsets": ["terminal", "file", "web"],
        "skills": ["systematic-research"],
    })
    result_data = json.loads(result_json)  # dict with summary
    return TaskResult(
        status="completed",
        data=result_data.get("summary", {"answer": result_data}),
    )
```

**Why:** `dispatch_tool()` is the documented, supported public API (`plugins.py` line 468):
- Auto-wires parent agent context in CLI mode
- Degrades gracefully in gateway mode
- `delegate_task` spawns a sub-agent with full profile isolation (SOUL.md, config, tools, memory)
- Returns JSON string containing the result summary
- Profile targeting: pass `"profile": "ray"` in args

**For profile-targeted dispatch** (routing to a specific profile per FC decision):
```python
result_json = ctx.dispatch_tool("delegate_task", {
    "goal": intent.payload.get("question", ""),
    "profile": intent.target_profile,
})
```

---

## M1.1 — Intent Derivation from Hermes Profiles

**Question:** How do profiles declare what A2A intents they can handle?

### Finding

**SOUL.md has NO YAML frontmatter** — all profiles use plain markdown (verified: Tesla, Cody, Odin, Ray, Reviewer). The first line is `***Tesla / Ray***` — no `---` delimited metadata block. Structured intent data cannot be extracted from SOUL.md.

**Config.yaml silently accepts unknown keys.** Hermes uses `yaml.safe_load(f) or {}` (source: `profiles.py` line 441, `config.py` line 4305). Unknown top-level keys pass through untouched. No Hermes code iterates config keys — access is always via `data.get("key")`.

**A2A spec alignment:** `AgentSkill` (the wire-protocol type) has `id, name, description, tags, examples` — no `intents` field. Our `intents[]` is an **internal routing abstraction** for the Fleet Controller, not a wire-protocol concern. The adapter translates between them.

### Recommendation: `a2a:` section in profile `config.yaml`

```yaml
# At end of ~/.hermes/profiles/ray/config.yaml
a2a:
  intents: ["diagnose", "consultation"]
  tags: ["linux", "nginx", "health-check"]
  streaming: false
  push: false
```

```yaml
# At end of ~/.hermes/profiles/odin/config.yaml
a2a:
  intents: ["consultation", "research"]
  tags: ["linux", "research", "arch"]
  streaming: false
  push: false
```

**Why this over alternatives:**
- **Not a separate file** — one less thing to manage per profile. Survival through profile clone, backup, restore.
- **Not inference** — explicit beats implicit. Toolsets could infer some intents but would miss domain-specific ones (e.g., "audit" from a reviewer profile).
- **Not SOUL.md** — SOUL.md has no frontmatter. Adding YAML frontmatter to existing files risks breaking Hermes's markdown parser.
- **Hermes-safe** — `yaml.safe_load` passes through unknown keys. Survives version upgrades. No Hermes code accesses the `a2a:` key.
- **Cross-platform** — YAML is platform-agnostic. Same file on Linux and macOS.

The Phase 3 `A2AAdapter.get_capabilities()` implementation reads:
```python
import yaml
from pathlib import Path

def get_capabilities(self) -> list[AgentCapability]:
    profiles_dir = Path.home() / ".hermes" / "profiles"
    capabilities = []
    for profile_dir in profiles_dir.iterdir():
        config_path = profile_dir / "config.yaml"
        if not config_path.exists():
            continue
        config = yaml.safe_load(config_path.read_text()) or {}
        a2a_config = config.get("a2a", {})
        if not a2a_config.get("intents"):
            continue  # Skip profiles that don't declare A2A capabilities
        capabilities.append(AgentCapability(
            profile_name=profile_dir.name,
            node_id="local",
            display_name=_get_display_name(profile_dir),
            description=a2a_config.get("description", ""),
            intents=a2a_config.get("intents", []),
            tags=a2a_config.get("tags", []),
            examples=a2a_config.get("examples", []),
            supports_streaming=a2a_config.get("streaming", False),
            supports_push=a2a_config.get("push", False),
        ))
    return capabilities
```

---

## Appendix: v1.0 AgentCard Field Mapping

> **Note on key storage:** The original M1.1 recommendation "a2a: section in profile config.yaml" was replaced by ADR-001. Signing keys live in per-profile `.env` files, not config.yaml or a separate keys directory. See [ADR-001](../decisions/adr-001-signing.md) for the full decision record.

Clarifications discovered during M0.3 validation testing. The a2a-sdk v1.0.3 protobuf types differ from the spec documentation examples in several field names.

### AgentCard

```python
from a2a.types import AgentCard, AgentCapabilities, AgentSkill, AgentInterface

card = AgentCard(
    name="Tesla Mesh Node",
    description="Hermes agent on VPS",
    url="",                                    # ❌ Removed in v1.0
    version="1.0.0",                           # ✅ Still present
    default_input_modes=["text/plain"],         # ✅ Moved from AgentCapabilities
    default_output_modes=["text/plain"],        # ✅ Moved from AgentCapabilities
    capabilities=AgentCapabilities(
        streaming=True,
        # push_notifications=True              # ❌ Field named differently or absent
    ),
    skills=[AgentSkill(...)],
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            protocol_version="1.0",
            url="http://100.96.0.2:8081",      # ✅ url lives here now
        )
    ],
)
```

### Key Deltas (from v0.3 to v1.0)

| Field | v0.3 | v1.0 |
|-------|------|------|
| `AgentCard.url` | Top-level field | Removed — use `supported_interfaces[i].url` |
| `AgentCapabilities.push_notifications` | Named field | `push_notifications` (verified: protobuf descriptor has it) |
| `AgentCapabilities.input_modes` | On Capabilities | Moved to `AgentCard.default_input_modes` |
| `AgentCapabilities.output_modes` | On Capabilities | Moved to `AgentCard.default_output_modes` |
| `TaskState` enum | `snake_case` | `SCREAMING_SNAKE_CASE` |
|| `Task.status` field | `state` | `status` (a `TaskStatus` message object, not a string enum) |
|| `Role` enum | lowercase (`user`, `agent`) | `ROLE_USER`, `ROLE_AGENT` — SCREAMING_SNAKE |
|| JSON-RPC method names | kebab-case (`message/send`, `tasks/get`) | PascalCase (`SendMessage`, `GetTask`, `ListTasks`) |
|| `AgentExecutor` ABC | `execute()` only | `execute()` + `cancel()` |
|| `SendMessage` handler | No config needed | Requires `return_immediately` logic in handler |
|| `A2A-Version` header | Default: none | **Required.** Defaults to `0.3` if missing. Must send `A2A-Version: 1.0` |
|| `AgentProvider.origin` | Named field | **Removed.** Use `AgentProvider.url` for URL, `AgentProvider.organization` for name |
|| `AgentSkill` fields | Spec docs show `id`, `name`, `description`, `tags`, `examples` | ✅ Matches — verified by `build_agent_card()` |
|| `SendMessage` required fields | Minimal | **Requires** `message.message_id`, `A2A-Version` header, `role` as `ROLE_USER`/`ROLE_AGENT` |

### How to discover exact fields on your machine (macOS or Linux)

**Protobuf descriptor (always authoritative):**
```bash
python -c "
from a2a.types import AgentCard, AgentCapabilities, AgentSkill, AgentProvider, AgentInterface
for name, cls in [('AgentCard', AgentCard), ('AgentCapabilities', AgentCapabilities),
                  ('AgentSkill', AgentSkill), ('AgentProvider', AgentProvider),
                  ('AgentInterface', AgentInterface)]:
    print(f'{name} fields:')
    for f in cls.DESCRIPTOR.fields:
        print(f'  {f.name} (type={f.type})')
    print()
"
```

**For protobuf wrappers (no `DESCRIPTOR`):**
```bash
python -c "
from google.protobuf.json_format import ParseDict
from a2a.types import ExampleType
# Construct an instance and use MessageToDict to discover keys
"
```

---

## Summary

| Blocker | v1 Recommendation | Production Path |
|---------|-------------------|-----------------|
| M0.3 Server lifecycle | Subprocess via `subprocess.Popen` + `atexit` | Standalone systemd service |
| M0.4 Session spawn | `ctx.dispatch_tool("delegate_task", ...)` | Same (public API, no change needed) |
| M1.1 Intent derivation | `a2a:` section in profile `config.yaml` | Same (declarative config, no change needed) |
