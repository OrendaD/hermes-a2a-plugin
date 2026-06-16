---
title: "A2A Plugin — Architecture & Design Decisions"
created: 2026-06-16
type: reference
tags: [a2a, architecture, design]
---

# A2A Plugin — Architecture & Design Decisions

## Governing Principle

**A2A is a communication protocol, not an agent framework.** This is the single most important architectural decision. It determines where every piece of code lives and what it's allowed to import.

The A2A v1.0 specification defines three layers:
1. **Canonical Data Model** — protocol-neutral protobuf definitions
2. **Abstract Operations** — binding-independent capabilities
3. **Protocol Bindings** — JSON-RPC, gRPC, HTTP+JSON

Our plugin mirrors this structure with a three-layer hexagonal architecture.

## Layer Architecture

```
┌──────────────────────────────────────────────┐
│  PROTOCOL LAYER — A2A Transport              │
│  SDK-managed: JSON-RPC framing, SSE,         │
│  version negotiation, auth handshake,        │
│  Agent Card serving                          │
├──────────────────────────────────────────────┤
│  ADAPTER LAYER — The Hermes Plugin           │
│  Implements AgentExecutor from a2a-sdk       │
│  Translates: A2A Message → Domain Intent     │
│  Translates: Domain Result → A2A Task        │
│  Wires: Agent Card JSON → Profile Registry   │
│  Wires: A2A auth → Hermes credential pool    │
├──────────────────────────────────────────────┤
│  CORE LAYER — Protocol-Agnostic Intelligence │
│  FleetController — dispatch, availability    │
│  Orchestrator — lifecycle, state machine     │
│  Domain Models — TaskIntent, TaskResult      │
│  ZERO A2A SDK imports                        │
└──────────────────────────────────────────────┘
```

### Core/Adapter boundary rule

`src/core/` has zero `from a2a import` lines. Verified:

```bash
grep -r "from a2a" src/core/
# MUST return zero matches
```

This boundary means the domain models can be used with any transport — A2A, REST, gRPC, or direct function calls. The adapter imports the core; the core never imports the adapter.

## Middleware Stack

Requests arrive at the ASGI app and pass through each middleware in sequence:

```
Request → A2AVersionMiddleware → RateLimitMiddleware → Handler → Response
```

1. **`A2AVersionMiddleware`** — validates the `A2A-Version` header. Rejects non-1.0 requests before they reach the handler. Returns `-32009` (VersionNotSupportedError) on mismatch.

2. **`RateLimitMiddleware`** — checks per-peer rate limit using SHA256 of the bearer token. Returns HTTP 429 with `Retry-After` header if exceeded. In-memory tracking — restart resets counters.

3. **Handler** — dispatches to `HermesExecutor` for A2A task execution.

## Dispatch Mechanism

Each inbound A2A request creates a fresh `AIAgent` in a daemon thread:

```
A2A Request → Handler → HermesExecutor → AIAgent.chat(goal) → TaskResult
```

**Key characteristics:**

| Property | Value | Reason |
|----------|-------|--------|
| Session per request | Fresh `AIAgent` each time | No state leakage between requests |
| Identity | Inherits profile's SOUL.md | Consistent persona |
| Memory | Disabled | Stateless per request |
| Toolsets | Restricted | No delegate_task, clarify, send_message, memory, cronjob |
| Error handling | Clean `TaskResult(status="failed")` | Never propagate exceptions to caller |

This replaces the earlier `ctx.dispatch_tool("delegate_task", ...)` mechanism, which cannot work from a daemon thread (no active AIAgent session context).

## Fleet Controller

The FleetController manages profile routing and capability matching:

```
Inbound Task → FleetController → Profile Discovery → Matching Profile → Executor
```

- Knows what profiles live on this node and their capabilities
- Matches incoming intent types to available profiles
- Falls back to the main agent when no specialist matches
- Tracks profile availability (free/busy)

## Mesh Peer Client

The MeshPeerClient handles outbound communication:

```
Outbound Task → MeshPeerClient → HTTP → Peer A2A Server → Result
```

- Connects to configured peers at plugin registration
- Resolves Agent Cards and registers remote capabilities
- Dispatches tasks via `send_task()`
- Propagates provenance metadata (source_node, reference_task_ids)
- Automatic reconnection with exponential backoff on failure

### Reconnection strategy

| Parameter | Value |
|-----------|-------|
| Base delay | 1 second |
| Max delay | 60 seconds |
| Jitter | Full (uniform random up to current delay) |
| Strategy | Exponential backoff with full jitter |
| Termination | On success or `close()` |

## Security Layers

| Layer | Mechanism | Scope |
|-------|-----------|-------|
| Auth (inbound) | Bearer token + `hmac.compare_digest()` | Per-request |
| Auth (outbound) | Token from peer config | Per-peer |
| Rate limiting | SHA256 of token, rolling 60s window | Per-peer |
| SSRF protection | DNS pinning + private network blocking | Outbound requests |
| Version validation | `A2A-Version: 1.0` header check | Per-request |
| Provenance | source_node, reference_task_ids metadata | Per-outbound-task |
| Audit logging | JSONL with 10MB rotation | All operations |

## Design Decisions

### Why peers route to the main agent (not sub-agents)

Peers talk to peers. Sub-agents are hands, not representatives. An incoming A2A request from a remote node should be handled by the node's main agent — the one with full context, memory, and user-facing chat. Sub-agents are internal tooling spawned by the main agent, not external representatives.

This simplifies the dispatch model: unqualified `SendMessage` → receiving node's live AIAgent.

### Why AIAgent-per-request (not ctx.dispatch_tool)

The A2A server runs in a daemon thread within the gateway process. There is no active AIAgent session context available. Creating a fresh AIAgent per request is the only reliable way to execute work without coupling to the main session's state.

### Why stdlib+Starlette (not FastAPI)

The A2A SDK provides its own request handling via `AgentExecutor`. FastAPI's dependency injection and OpenAPI generation add overhead without benefit — the A2A protocol defines its own schema. Starlette provides the ASGI foundation without opinionated routing.

### Why ES256 for signing

See [Signing ADR](signing-adr.md) for the full decision rationale. Summary: asymmetric (no secret sharing), fast key generation, compact signatures, battle-tested PyJWT support.

## File Map

```
src/
├── a2a_plugin/
│   └── __init__.py              # Plugin entry point, register()
├── adapter/
│   ├── hermes_executor.py       # Task execution via AIAgent
│   ├── hermes_adapter.py        # A2A-to-domain request translation
│   ├── agent_card_builder.py    # Agent Card construction
│   ├── agent_card_signer.py     # ES256 signing
│   ├── agent_card_route.py      # /.well-known/ endpoint
│   ├── mesh_peer_client.py      # Outbound peer communication
│   ├── peer_registry.py         # Peer config management
│   ├── profile_discovery.py     # Profile scanning
│   ├── rate_limit_middleware.py  # Per-peer rate limiting
│   ├── version_middleware.py    # Version header validation
│   ├── auth_context_builder.py  # Bearer token auth
│   ├── audit_logger.py          # JSONL audit trail
│   └── ssrf.py                  # SSRF protection
└── core/
    ├── fleet_controller.py      # Profile routing
    ├── orchestrator.py          # Task lifecycle
    └── domain/
        ├── models/              # Protocol-agnostic dataclasses
        └── interfaces/          # Abstract interfaces
```

## References

- [A2A v1.0 Specification](https://a2a-protocol.org/latest/specification/)
- [Signing ADR](signing-adr.md)
- [Config Reference](config-reference.md)
- [User Manual](../USER-MANUAL.md)
