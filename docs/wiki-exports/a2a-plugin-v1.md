---
title: A2A v1.0 Plugin — Rebuild Project Record
created: 2026-05-17
updated: 2026-05-19
type: planning
status: designed
tags: [a2a, protocol, plugin, goal, architecture, planning]
confidence: high
sources:
  - raw/articles/a2a-spec.md
  - "https://dev.to/sreeni5018/the-a2a-protocol-misconception"
  - "https://github.com/NousResearch/hermes-agent/pull/25660"
  - "https://github.com/NousResearch/hermes-agent/issues/25698"
  - "a2a-domain-contracts"  # Tesla — protocol-agnostic models & interfaces
  - "a2a-plugin-architecture"  # Tesla — hexagonal foundation, Agent Card, SSRF
  - "a2a-orchestration-patterns"  # Tesla — dynamic team assembly, input-required, FC vs Orchestrator
---

# A2A v1.0 Plugin — Rebuild Project Record

## Goal & Scope

Build a production-quality Hermes plugin implementing the A2A Protocol v1.0 specification — robust and trustworthy enough for client nodes as well as internal Proteus↔Tesla coordination.

**In scope:**
- v1.0-conformant server (JSON-RPC binding, optional HTTP/REST)
- Dynamic Agent Card generation from Hermes profile capabilities
- Task lifecycle mapping to Hermes session/kanban model
- Multi-tenancy support for client-node isolation
- Agent Card cryptographic signing (JWS)
- Streaming (SSE) for real-time task updates
- Push notification webhooks for long-running tasks

**Out of scope (for now):**
- gRPC protocol binding (add later if needed)
- OpenTelemetry distributed tracing
- SQL persistence backends (start with plugin-native storage)

## Source Materials

| Source | URL | Ingested | Notes |
|--------|-----|----------|-------|
| A2A v1.0 Specification | https://a2a-protocol.org/latest/specification/ | 2026-05-14 (raw ingest), 2026-05-17, 2026-05-19 (re-read) | 13 sections, 6,013 lines, proto-based data model |
| A2A v1.0 Announcement | https://a2a-protocol.org/latest/announcing-1.0/ | 2026-05-17 | Enterprise features: multi-tenancy, signed cards, version negotiation |
| A2A Python SDK | https://github.com/a2aproject/a2a-python | 2026-05-17 | `pip install a2a-sdk` v1.0.3, Google-maintained |
| A2A SDK list | https://a2a-protocol.org/latest/sdk/ | 2026-05-17 | Python, Go, JS, Java, .NET, Rust |
| A2A GitHub | https://github.com/google/A2A | 2026-05-17 | Linux Foundation, Apache 2.0 |
| Legacy Hermes A2A plugin | https://github.com/iamagenius00/hermes-a2a-preview | 2026-05-12 (installed), 2026-05-17 (removed) | v0.2.0 preview, not v1.0 |
| Hermes plugin API | Source: `hermes_cli/plugins.py` in Hermes repo | 2026-05-17 | PluginContext, VALID_HOOKS, tool registration |
| Wiki: Mesh orchestration | N/A (wiki page) | 2026-05-14 | Fleet controller + orchestrator architecture — [[planning/mesh-orchestration|details]] |
| A2A Deployment Architecture (blog) | https://dev.to/sreeni5018/the-a2a-protocol-misconception | 2026-05-17 | Hexagonal adapter pattern; CI-enforceable boundary rules; AgentExecutor trap analysis |
| Hermes PR #25660 | https://github.com/NousResearch/hermes-agent/pull/25660 | 2026-05-17 | Multi-gateway MVP: AgentProfile, use_profile(), declarative routes |
| Hermes Issue #25698 | https://github.com/NousResearch/hermes-agent/issues/25698 | 2026-05-17 | Upstream A2A follow-up (P3, unassigned); same problem, narrower scope |
| Tesla: Domain Contracts | `webgui-files/a2a-domain-contracts.md` | 2026-05-19 | 4 pure dataclasses + 3 interface contracts; development order |
| Tesla: Plugin Architecture | `webgui-files/a2a-plugin-architecture.md` | 2026-05-19 | Hexagonal 3-layer model; profile workspace; Agent Card JSON; SSRF nuance |
| Tesla: Orchestration Patterns | `webgui-files/a2a-orchestration-patterns.md` | 2026-05-19 | Dynamic team assembly; input-required lifecycle; FC vs Orchestrator; Kanban vs A2A |

## Terrain Map

### A2A v1.0 Spec Architecture (3 layers)

1. **Canonical Data Model** — Protocol Buffer definitions (`spec/a2a.proto`). Task, Message, Part, Artifact, AgentCard.
2. **Abstract Operations** — 9 methods: Send Message, Stream Message, Get Task, List Tasks, Cancel Task, Subscribe to Task + 4 Push Notification CRUD ops.
3. **Protocol Bindings** — JSON-RPC (primary), gRPC, HTTP/REST. Version negotiation via `A2A-Version: 1.0` header.

### Key Spec Concepts

- **AgentCard** — name, description, skills (id/name/tags/examples/inputModes), capabilities (streaming, pushNotifications, extensions), security schemes (API key, Bearer, OAuth2, OIDC, mTLS), interfaces (url + protocol binding + version), JWS signatures
- **Task lifecycle** — submitted → working → input-required/auth-required (interrupted) → completed/failed/canceled/rejected (terminal). `input-required` is explicitly NOT a failure — it's a request for more information. The client continues by sending a new message on the same taskId+contextId. The spec explicitly supports delegation chains: an agent that hits AUTH_REQUIRED may delegate to another agent via its own task.
- **Three delivery mechanisms** — polling (GetTask), streaming (SSE events), push notifications (webhooks)
- **Multi-tenancy** — `tenant` parameter on all task operations
- **Version negotiation** — clients send `A2A-Version` header; servers match or reject with VersionNotSupportedError
- **Multi-turn** — `contextId` groups related tasks; `taskId` continues an existing task; `referenceTaskIds` links parent→child in the conversation graph

### Hexagonal Architecture — Our 3 Layers

```
┌──────────────────────────────────────────────────────┐
│  PROTOCOL LAYER — A2A Transport                       │
│  SDK-managed: JSON-RPC framing, SSE streaming,        │
│  version negotiation, auth handshake, Agent Card      │
│  serving at /.well-known/agent-card.json               │
├──────────────────────────────────────────────────────┤
│  ADAPTER LAYER — The Hermes Plugin                    │
│  Implements AgentExecutor from a2a-sdk                │
│  Translates: A2A Message → Domain Intent             │
│  Translates: Domain Result → A2A Task/Artifact       │
│  Wires: Agent Card JSON → Profile Registry           │
│  Wires: A2A auth → Hermes credential pool            │
├──────────────────────────────────────────────────────┤
│  CORE LAYER — Protocol-Agnostic Intelligence          │
│  Fleet Controller — dispatch, profile availability   │
│  Orchestrator — mid-flight steering, input-required   │
│    handling, cross-node specialist recruitment        │
│  Profile Registry — capability inventory per profile  │
│  Conversation Graph — task linkage via contextIds     │
│  PURE — zero A2A imports. Testable without infra.    │
└──────────────────────────────────────────────────────┘
```

**Non-negotiable rule:** Nothing from the Protocol Layer crosses into the Core Layer. If core code imports `from a2a import ...`, the architecture is broken.

### Fleet Controller vs Orchestrator — Two Core-Layer Roles

These are separate components, both on the clean side of the boundary:

| Role | Responsibility | Nature |
|------|---------------|--------|
| **Fleet Controller** | Route task to profile, check availability, manage capacity, spawn profile processes | Stateless. Input: `TaskIntent`. Output: task ID + status. |
| **Orchestrator** | Monitor mid-flight tasks, detect `input-required`, recruit specialists, compose answers, resume tasks | Stateful. Tracks live conversation graphs (contextIds → task tree). |

The Orchestrator's `recruit_specialist()` is the bridge to A2A: finds a profile on any node that can answer a sub-question, dispatches a new A2A task, waits for completion, composes the answer, and resumes the blocked parent task. The Kanban system remains for predictable pipelines; A2A handles adaptive, discovery-driven work.

### Profile Workspace Model

Each Hermes profile at `~/.hermes/profiles/<name>/` is a fully independent workspace with its own SOUL.md, config.yaml, .env, sessions/, skills/, memories/, workspace/, cron/, and state.db. Key insight: A2A tasks carry intent + payload, not domain knowledge. The knowledge lives in the profile workspace — pre-loaded, pre-configured, ready to use. The protocol routes work to the right workspace.

### Agent Card → Profile Mapping

Each profile publishes as an `AgentSkill` on the node's Agent Card with: id (profile name), name (display name), description, tags (for discovery routing), examples (formatting hints for remote orchestrators), and inputModes/outputModes. Intent originates from the requesting node (not derived from the profile): the orchestrator formulates `intent_type` and the Fleet Controller matches against profile capabilities. Profiles self-declare what they can handle via `AgentCapability.intents[]`.

### Transport Selection

| Binding | v1.0? | Rationale |
|---------|-------|-----------|
| JSON-RPC | ✅ Primary | SDK route factories exist, spec's primary binding |
| HTTP/REST | ✅ Auxiliary | Health checks, curl testing, simple integrations |
| gRPC | ❌ Later | Codegen overhead, no benefit at our scale |

### Auth Model

| Context | Scheme | Detail |
|---------|--------|--------|
| Mesh peers (Tesla ↔ Proteus) | Bearer token | Pre-shared, stored in each peer's credential store |
| Client nodes | API key | Simpler onboarding, no OAuth complexity |
| In-task escalation | AUTH_REQUIRED state | Task pauses, secondary creds acquired out-of-band |

### SSRF and Mesh Networking

Our mesh addresses are **100.96.x.x** (RFC 6598 CGNAT space). Critical nuance: RFC 6598 is NOT RFC 1918. Most SSRF guards and private-IP detectors do NOT block 100.x.x.x by default. The plugin's SSRF layer MUST explicitly allow `100.96.0.0/16` for mesh communication. Per-peer `allow_private_target` pattern from the legacy plugin carries forward.

### Official Python SDK (a2a-sdk v1.0.3)

**Core dependencies (9 packages):** protobuf 6.x, pydantic ≥2.11, httpx + httpx-sse, json-rpc 1.15, google-api-core + googleapis-common-protos, culsans, packaging. Zero conflicts with Hermes dependency graph.

**Key SDK components we'll use:**
- `AgentExecutor` — abstract class; implement `execute(context, event_queue)` once
- `AgentCard` builder — proto-based, type-safe, JWS-signable
- `RequestContext` — carries task_id, context_id, message, referenced tasks
- `EventQueue` — publish Task/Message/StatusUpdate/ArtifactUpdate events
- Route factories — `create_agent_card_routes()`, `create_jsonrpc_routes()`, `create_rest_routes()`
- Client — full client with card resolution, auth, transports

**Optional extras (install when needed):**
- ~~`http-server`~~ (starlette) — will install for JSON-RPC/REST server routes ✅
- `grpc` (grpcio x5) — gRPC protocol binding (deferred — [[planning/a2a-plugin-v1#D-002|D-002]])
- ~~`signing`~~ (pyjwt) — JWS Agent Card signing → will install for v1 ✅
- ~~`sqlite`~~ (sqlalchemy) — persistent task storage → will install for v1 per [[planning/a2a-plugin-v1#D-005|D-005]] ✅
- `telemetry` (opentelemetry) — distributed tracing (deferred)

### Hermes Plugin API (what we hook into)

**Available hooks:** pre_tool_call, post_tool_call, transform_terminal_output, transform_tool_result, transform_llm_output, pre_llm_call, post_llm_call, pre_api_request, post_api_request, on_session_start, on_session_end, on_session_finalize, on_session_reset, subagent_stop, pre_gateway_dispatch + approval hooks

**PluginContext capabilities:** register_tool, register_command, register_hook, inject_message, dispatch_tool, llm facade, context engines, image/video gen providers, web search providers

## Decision Log

### D-001: Clean rebuild — no reuse of legacy plugin

**Date:** 2026-05-17
**Decision:** Remove all legacy A2A plugin artifacts and start fresh with v1.0 spec + official SDK.
**Why:** The legacy plugin (`iamagenius00/hermes-a2a-preview`) is v0.2.0 with hardcoded Agent Card, no streaming, no multi-tenancy, no cryptographic identity. Retrofitting v1.0 onto stdlib-only code would produce an unmaintainable system. Clean slate.
**Alternatives considered:** Fork and upgrade the legacy plugin — rejected because the architecture mismatch (stdlib ThreadingHTTPServer vs FastAPI async, hardcoded Agent Card vs dynamic) would require rewriting most modules anyway.
**Artifacts removed:** `~/.hermes/plugins/a2a/`, `~/.hermes/a2a_conversations/`, `~/.hermes/a2a_friends.json`, `~/.hermes/a2a_audit.jsonl`, all A2A config sections in `config.yaml`, all A2A_ env vars in `.env`.
**Backups:** `config.yaml.bak-20260517-*`, `.env.bak-20260517-*`
**Unblocks:** Clean terrain to design against v1.0 without legacy constraints.

### D-002: Build on a2a-sdk, not from scratch

**Date:** 2026-05-17
**Decision:** Use the official `a2a-sdk` (v1.0.3, Google-maintained, Linux Foundation) as the foundation rather than implementing v1.0 protocol semantics ourselves.
**Why:** The SDK provides protocol conformance, Agent Card signing, version negotiation, route factories, and client/server abstractions that would take weeks to implement correctly. Google and the TSC (AWS, Cisco, IBM, Microsoft, Salesforce, SAP, ServiceNow) maintain it. Dependencies are pure Python, no conflicts with Hermes.
**Alternatives considered:** Pure stdlib implementation — rejected because v1.0 is a complex spec (9 operations, 5 auth schemes, signed cards, multi-tenancy) and getting conformance right without the reference SDK risks interop failures with other v1.0 agents.
**Unblocks:** Architecture decisions about the server layer now build on known abstractions.

### D-003: Hexagonal adapter boundary — no A2A imports in Hermes core

**Date:** 2026-05-17
**Decision:** Enforce a strict package boundary. The Hermes agent core (`run_agent.py`, prompt builder, tools, skills, memory) must never import `a2a` or `a2a-sdk` types. The plugin is the sole adapter layer — it translates A2A protocol objects (Task, Message, AgentCard, RequestContext) into Hermes API calls (session dispatch, tool invocation, kanban operations) and back. The Hermes core has zero awareness that A2A exists.
**Why:** Prevents the "AgentExecutor trap" identified by production A2A deployers (Sreeni Ramadorai, 2026-05-17). Without this boundary, business logic migrates into the protocol layer over time. With the boundary, every Hermes session can be fired and tested independently of A2A — the plugin is one entry point, not the only one.
**Validation check (CI-enforceable):** `grep -r "from a2a" hermes/` (core) must return zero. `grep -r "from a2a" plugins/a2a/` is expected.
**Source:** dev.to/sreeni5018/the-a2a-protocol-misconception (production A2A deployment patterns)
**Unblocks:** Clean design for Agent Card → profile mapping (pure adapter work) and task lifecycle → session dispatch (no core entanglement).

### D-004: Align with upstream `use_profile()` architecture when PR #25660 lands

**Date:** 2026-05-17
**Decision:** Design the plugin to treat the Hermes `AgentProfile` (via `use_profile()`) as the unit of A2A agent identity. When the upstream multi-agent PR merges — enabling profile-based filesystem isolation, per-profile SOUL.md, and per-profile cron/delivery — the plugin will generate Agent Cards from profile capabilities, route inbound A2A tasks to the correct profile, and scope A2A session state per profile. Until then, the plugin operates on the single "main" profile and is forward-compatible.
**Why:** PR #25660 (02356abc, May 14, 2026) introduces `AgentProfile`, `use_profile()` ContextVar, and declarative `routes:` — the infrastructure our plugin needs for multi-agent + cross-instance A2A. The upstream follow-up issue #25698 ("feat(gateway): design A2A communication between gateway agent profiles", P3, unassigned) is the *same* problem space we're solving but at P3 priority with no activity — so we build our plugin but design it to snap into the upstream profile model rather than inventing a parallel one.
**Upstream scope note:** #25698 contemplates same-gateway profile-to-profile A2A. Our scope is broader: cross-instance A2A between distinct Hermes nodes (Proteus ↔ Tesla). The `use_profile()` machinery handles the per-profile isolation on each node; the plugin handles the cross-instance transport.
**Unblocks:** Multi-tenancy and auth integration should assume a multi-profile deployment even when we start with single-profile.

### D-005: SQLite storage via a2a-sdk SQLAlchemy extra

**Date:** 2026-05-19
**Decision:** Use the a2a-sdk's optional SQLAlchemy path with SQLite backend for task persistence. Not in-memory (dies on gateway restart), not file-per-task JSON (no query capability).
**Why:** Gateway restarts are routine on this node — mid-flight task state must survive. SQLite provides crash survivability plus query capability (`ListTasks(contextId=…)`, status filtering, `ConversationGraph` reconstruction). The SDK already provides the SQLAlchemy integration; SQLAlchemy is already in Hermes's dependency graph.
**Unblocks:** Storage backend is now a known integration point. Plugin's `startup()` initializes the DB; `AgentExecutor.execute()` reads/writes through the SDK's persistence layer.

### D-006: Single-tenant for v1 — multi-tenancy deferred

**Date:** 2026-05-19
**Decision:** Start single-tenant. Wire the spec's `tenant` field as a reserved field in the data model (defaulting to a single tenant) for forward-compatibility. Build the tenant isolation layer when client nodes exist.
**Why:** The mesh currently has two peers (Proteus, Tesla) — all internal operations. No client nodes. Premature multi-tenancy adds auth surface, routing complexity, and isolation testing overhead with zero operational benefit. The `tenant` field is reserved in the schema from day one so adding it later is a data migration, not a schema migration.
**Unblocks:** v1 auth surface simplified to mesh bearer tokens only. Fleet Controller routing stays single-tenant. No tenant-scoped ListTasks/CancelTask guards needed.

## Open Questions

⏤ All 7 resolved. No blockers remaining before decomposition.

### Q1: Agent Card → Hermes profile mapping ✅ Resolved

Agent Card skills map 1:1 to Hermes profiles. Each profile at `~/.hermes/profiles/<name>/` publishes as one `AgentSkill` with id=profile_name, tags for discovery routing, examples for payload format hints, and inputModes/outputModes matching the profile's capabilities. The intermediate representation is `AgentCapability` — a protocol-agnostic dataclass the adapter translates to/from AgentCard JSON. Intent originates from the orchestrator (requesting node), not derived from the profile.

### Q2: Task lifecycle → Hermes model ✅ Resolved

A2A tasks are managed by the core-layer `FleetController` and `Orchestrator`. FC handles stateless routing (TaskIntent → profile + node dispatch). Orchestrator handles stateful flow management (monitors mid-flight tasks, detects `input-required`, recruits specialists, composes answers, resumes). Task state transitions trigger agent work via `send_task(intent)` — the adapter translates the A2A Message into a `TaskIntent`, routes it through the Fleet Controller, and translates the `TaskResult` back. The `ConversationGraph` tracks linked tasks via contextId + referenceTaskIds for audit, recovery, and `ListTasks` queries.

### Q3: Server architecture ✅ Resolved

Plugin-embedded server using `a2a-sdk` with `http-server` extra (Starlette). The SDK provides ready-made route factories (`create_jsonrpc_routes()`, `create_agent_card_routes()`). The open sub-question is now operational: how the plugin manages the server process lifecycle (start on plugin load, bind to configured port, graceful shutdown).

### Q4: Transport selection ✅ Resolved

JSON-RPC primary. HTTP/REST via `create_rest_routes()` as auxiliary (health checks, curl testing). gRPC deferred — codegen overhead, no benefit at our scale.

### Q6: Auth integration ✅ Resolved

Two schemes initially: Bearer token for mesh peers (pre-shared, stored in each peer's credential store), API key for client nodes (simpler onboarding). AUTH_REQUIRED state for in-task escalation (delegates to human or another agent out-of-band). The 5-scheme SDK surface is available for future expansion.

### Q5: Multi-tenancy model ✅ Resolved — deferred to post-v1

**Decision (2026-05-19):** Single-tenant for v1. The mesh currently has two peers (Proteus, Tesla) — all internal operations. No client nodes exist yet. The spec's `tenant` field will be wired as a reserved field in the data model (accepts and stores the value, defaulting to a single tenant) for forward-compatibility without building the isolation layer. Multi-tenancy adds auth surface and routing complexity with zero operational benefit until client nodes exist. Add tenant isolation when there are actual clients to isolate.

### Q7: Storage ✅ Resolved — SQLite via SDK's SQLAlchemy extra

**Decision (2026-05-19):** SQLite. Crash survivability across gateway restarts is a hard requirement (gateway hangs are routine on this node). In-memory loses mid-flight tasks. File-based JSON survives but has zero query capability — no `ListTasks(contextId=…)`, no status filtering, no `ConversationGraph` reconstruction. SQLite gives both persistence and queryability. The a2a-sdk's optional SQLAlchemy path handles the schema and lifecycle. SQLAlchemy is already in Hermes's dependency graph.

## Task Graph

All 7 open questions resolved. Architecture locked (6 decisions). Ready for decomposition.

### Phase 1 — Domain Models & Tests
1. Define `TaskIntent`, `TaskResult`, `AgentCapability`, `ProfileDispatch` dataclasses
2. Write pure unit tests (zero infrastructure, millisecond execution)
3. Define `FleetController`, `Orchestrator`, `A2AAdapter` interfaces

### Phase 2 — Core Implementation
1. Implement Fleet Controller (capability matching, node-aware routing, availability checking)
2. Implement Orchestrator (task monitoring, input-required detection, specialist recruitment)
3. Implement Conversation Graph storage (contextId → task tree)
4. Core-layer integration tests (mock adapter)

### Phase 3 — Adapter (The Plugin)
1. → Detailed plan: [[planning/a2a-plugin-v1-m3]]
2. Implement `A2AAdapter` using a2a-sdk AgentExecutor
3. Implement Agent Card builder from `AgentCapability` list
4. Wire to Fleet Controller and Orchestrator
5. Local loopback integration test
6. Cross-node integration test (Proteus ↔ Tesla)

### Phase 4 — Verification
- Protocol boundary health check (`grep -r "from a2a import" src/core/` == zero)
- Core logic tests complete in < 1 second (no infrastructure)
- Adapter tests with mock A2A server

**Board:** `hermes-ops` (or new `a2a-plugin` board if task volume warrants)
**Profiles:** Proteus (orchestrator), builder, Doris (reviewer)

## Lessons Learned

*(Populated as we go. Retro added after each significant phase.)*

---

## Related Pages

- [[planning/a2a|details]] — Original A2A investigation (superseded by this page)
- [[subsystem/a2a|details]] — Legacy plugin operation reference (deprecated 2026-05-17)
- [[planning/mesh-orchestration|details]] — Mesh coordination architecture (the system this transport serves)
- [[planning/a2a-domain-contracts|details]] (Tesla) — Protocol-agnostic domain models & interfaces
- [[planning/a2a-plugin-architecture|details]] (Tesla) — Hexagonal foundation, Agent Card, SSRF
- [[planning/a2a-orchestration-patterns|details]] (Tesla) — Dynamic team assembly, input-required lifecycle
- [[planning/deployment-doctrine|details]] — Harness-first deployment doctrine
- [[Inkbox/cloudflare-mesh|details]] — Cloudflare Mesh network infrastructure
- [[raw/articles/a2a-spec.md]] — Full v1.0 spec (6,013 lines, ingested 2026-05-14)
