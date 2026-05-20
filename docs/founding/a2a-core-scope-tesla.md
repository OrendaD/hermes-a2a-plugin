---
title: A2A Core Layer — Scope & Deliverables (Tesla)
created: 2026-05-19
type: planning
status: assigned
assignee: Tesla
sources:
  - planning/a2a-plugin-v1
  - a2a-domain-contracts
  - a2a-plugin-architecture
  - a2a-orchestration-patterns
---

# A2A Core Layer — Scope & Deliverables

## What You Own

The **Core Layer** — everything above the protocol boundary. Pure Python. Zero A2A imports. Testable in milliseconds with nothing but `pytest`.

The **Adapter Layer** (plugin) is Proteus's responsibility. It translates A2A protocol objects into your domain objects and back. You define the contracts; the adapter implements against them.

## Boundary Rule

```
Core Layer (yours)          │  Adapter Layer (Proteus)
                             │
TaskIntent, TaskResult       │  ← Adapter translates FROM A2A Message
AgentCapability              │  ← Adapter translates TO AgentCard JSON
ProfileDispatch              │  ← Adapter routes to local/remote
                             │
send_task(intent) → TaskResult  │  ← Adapter implements this contract
get_capabilities() → [AgentCapability] │  ← Adapter implements this contract
cancel_task(task_id) → bool  │  ← Adapter implements this contract
```

**You never import `from a2a import ...`.** If core code touches an A2A SDK type, the architecture is broken.

## Phase 1 — Domain Models & Tests (Day 1)

### Deliverables

1. **Finalize the four dataclasses** in a Python package at `src/core/domain/models/`:
   - `TaskIntent` — intent_type, payload, routing fields, context_id, reference_task_ids
   - `TaskResult` — status, data, error, escalation, messages[], artifacts[], metadata
   - `AgentCapability` — profile_name, node_id, intents[], tags[], examples[], modes, streaming/push flags
   - `ProfileDispatch` — task_id, profile_name, node_address, endpoint, status

2. **Define the three interface contracts** in `src/core/domain/interfaces/`:
   - `FleetController` — `route(intent) → ProfileDispatch`, `release(task_id, profile)`, `register_profile(capability)`, `discover(intent_type, tags) → [AgentCapability]`
   - `Orchestrator` — `monitor(task_id, context_id)`, `on_status_change(...)`, `recruit_specialist(question, context_id, parent_task_id) → TaskResult`
   - `A2AAdapter` — `send_task(intent) → TaskResult`, `send_streaming_task(intent)`, `cancel_task(task_id) → bool`, `get_capabilities() → [AgentCapability]` (this is the contract Proteus implements; you define the signature)

3. **Write pure unit tests** — zero infrastructure, millisecond execution:
   - TaskIntent creation and field defaults
   - TaskResult status mapping (completed/failed/input_required/auth_required)
   - AgentCapability intent matching
   - Conversation graph linking (contextId + referenceTaskIds)
   - Fleet Controller stubs with mock adapter
   - Orchestrator input_required handler with mock adapter

### Acceptance Criteria

- `pytest tests/core/ -q` completes in **< 1 second**
- `grep -r "from a2a" src/core/` returns **zero**
- `grep -r "import a2a" src/core/` returns **zero**

## Phase 2 — Core Implementation (Days 2-3)

### Deliverables

1. **Fleet Controller implementation:**
   - Capability-based routing (match `intent.intent_type` against `AgentCapability.intents[]`)
   - Tag-based fallback (match against `AgentCapability.tags[]`)
   - Node-aware routing (prefer local profile, fall back to mesh peer)
   - Availability checking (is profile busy? capacity slots available?)
   - `discover()` for cross-node capability queries
   - `register_profile()` for startup registration from Agent Card parsing

2. **Orchestrator implementation:**
   - Task lifecycle monitoring (`monitor(task_id, context_id)`)
   - `on_status_change()` handler — detects `input_required` and fires `recruit_specialist()`
   - `recruit_specialist()` — calls `FleetController.discover()`, dispatches via `A2AAdapter.send_task()`, composes answer, resumes parent task
   - Conversation graph tracking (contextId → task tree)

3. **Conversation Graph storage:**
   - `ConversationGraph` dataclass — context_id, root_task_id, tasks{} dict
   - `TaskRecord` dataclass — task_id, context_id, status, intent_type, source_node, target_profile, payload, result, messages[], artifacts[], reference_task_ids[], timestamps
   - In-memory store for v1 (the adapter will persist to SQLite via the SDK — your store is for runtime tracking)

4. **Core-layer integration tests:**
   - FC routes intent to correct profile
   - FC prefers local over remote when both available
   - FC returns 'unavailable' when profile is at capacity
   - Orchestrator detects input_required and recruits specialist
   - Orchestrator spawns sub-task with correct contextId + referenceTaskIds
   - Conversation graph correctly links parent→child tasks

### Acceptance Criteria

- All tests pass without A2A infrastructure
- All tests complete in < 5 seconds total
- `A2AAdapter` is mocked — never hits the network
- Fleet Controller and Orchestrator are independently testable

## What NOT to Do

- **Do NOT write an A2A server.** The adapter handles all protocol concerns — JSON-RPC framing, SSE streaming, Agent Card HTTP serving, auth handshake. Your code never sees a `SendMessageRequest` or a `TaskState` enum.
- **Do NOT depend on a2a-sdk.** Your requirements.txt / pyproject.toml must not include `a2a-sdk` or any of its transitive dependencies.
- **Do NOT implement persistence.** The `ConversationGraph` and `TaskRecord` in-memory store is for runtime tracking. The adapter owns the SQLite persistence layer via the a2a-sdk's SQLAlchemy extra. Your store is ephemeral — lives for the life of the gateway process.
- **Do NOT handle auth.** Bearer token validation, API key checking, OAuth flows — all adapter territory. You receive a validated `TaskIntent` with `source_node` and `source_profile` already populated.

## Handoff Format

Your deliverables should be:
- A Python package at `src/core/` with `domain/models/`, `domain/interfaces/`, `fleet_controller.py`, `orchestrator.py`, `conversation_graph.py`
- Tests at `tests/core/`
- A `requirements.txt` (should be empty or near-empty — just `pytest` and stdlib)
- An `ARCHITECTURE.md` note confirming the boundary clean check passed

Proteus will import your package into the Hermes plugin's venv and implement `A2AAdapter` against your interfaces. No dependency inversion needed — the adapter depends on your interfaces, not the other way around.

## References

- `planning/a2a-plugin-v1` — Full project record, 6 decisions, terrain map
- `a2a-domain-contracts.md` — Your domain model draft (starting point for Phase 1)
- `a2a-plugin-architecture.md` — Your hexagonal architecture, Agent Card JSON, SSRF
- `a2a-orchestration-patterns.md` — Your orchestration model, input-required lifecycle
