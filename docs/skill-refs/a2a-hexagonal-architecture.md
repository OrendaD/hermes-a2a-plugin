# Hexagonal Architecture for Protocol Integration — A2A Plugin Case Study

> Source: "The A2A Protocol Misconception" by Sreeni Ramadorai (dev.to)
> Session: 2026-05-19 — A2A v1.0 plugin rebuild research
> Researchers: Proteus (upstream GitHub), Tesla (spec + practitioner articles)

## The Core Pattern

A2A is a **communication protocol**, not an agent framework. Teams that treat it as the latter build systems that collapse in 6 months. The correct architecture is **Ports and Adapters (Hexagonal Architecture)** with three strict layers:

```
┌─────────────────────────────────────┐
│  Agent Core (Domain Layer)          │
│  - Pure business logic              │
│  - Zero protocol imports            │
│  - Domain entities (ExpenseRequest) │
│  - Testable in milliseconds         │
└──────────────┬──────────────────────┘
               │ pure domain objects
               ▼
┌─────────────────────────────────────┐
│  Adapter / AgentExecutor            │
│  - Protocol ↔ Domain translation    │
│  - Zero business logic              │
│  - Boring data converter            │
└──────────────┬──────────────────────┘
               │ A2A protocol objects
               ▼
┌─────────────────────────────────────┐
│  A2A Protocol Layer                 │
│  - SendMessageRequest, Task, etc.   │
│  - HTTP/JSON-RPC/SSE transport      │
│  - Agent Cards, task lifecycle      │
└─────────────────────────────────────┘
```

## The Non-Negotiable Rule

**Nothing from the protocol layer crosses into the agent core layer.**

If your agent core imports A2A SDK types (`from a2a import Task`), your architecture is broken. The domain layer must be pure Python dataclasses and business logic — swappable between A2A, REST, gRPC, or batch jobs.

## The Three Failure Modes This Prevents

| Failure | Cause | Symptom |
|---------|-------|---------|
| Untestable logic | Business rules inside AgentExecutor | Need A2A server to test a policy change |
| Unreusable intelligence | Logic hardwired to protocol objects | Can't extract approval rules for batch job |
| Unevolvable system | Protocol + logic entangled | Changing SDK version requires rewriting business code |

## Why This Matters for Our A2A Plugin

Our legacy v0.2.0 plugin (`iamagenius00/hermes-a2a-preview`) violated this boundary — the AgentExecutor directly handled Hermes tool calls, session state, and delivery logic alongside A2A protocol objects. This was a root cause of the plugin's failure to reach production.

**The v1.0 rebuild must enforce:**

1. **Domain models** — Pure dataclasses for AgentTask, AgentQuery, AgentResponse, AgentCard. Zero A2A SDK imports.
2. **Agent core service** — Business logic: route task to correct Hermes agent, handle capability matching, manage task lifecycle decisions. Pure Python, testable.
3. **A2A adapter** — Translate between domain objects and A2A SDK types (`Task`, `Message`, `AgentCard`, `SendMessageRequest`). Thin, boring, swappable.
4. **Hermes adapter** — Translate between domain objects and Hermes-specific concepts (`delegate_task`, `kanban_create`, profile routing).

## Relationship to PR #25660 Upstream Architecture

Upstream Hermes PR #25660 introduces `AgentProfile` + `ContextVar` (`use_profile()`) for per-agent isolation within a single gateway process. Our A2A plugin should align with this model:

| Our Concept | Upstream Concept (PR #25660) |
|---|---|
| Agent identity / capabilities | `AgentProfile` (id, home_dir, model, toolsets) |
| Per-agent context propagation | `use_profile()` ContextVar |
| A2A Agent Card | Derived from `AgentProfile` + registered tools |
| Cross-instance routing | Outside upstream scope (they're same-gateway only) |

**Key insight:** Upstream's A2A scope is **intra-gateway** (agents sharing one process). Our scope is **cross-instance** (different Hermes nodes). The Ports-and-Adapters pattern lets us build both — the domain layer stays the same, only the adapters differ.

## Health Checks (from the original article)

```bash
# Check #1: No protocol imports in domain code
grep -r "from a2a import" src/domain/       # Expected: zero matches

# Check #4: No business logic in adapters
grep -r "if.*>" src/adapters/               # Expected: zero matches
```

## References

- Original article: https://dev.to/sreeni5018/the-a2a-protocol-misconception-why-your-agent-architecture-matters-more-than-your-framework-3iif
- Upstream PR #25660: https://github.com/NousResearch/hermes-agent/pull/25660
- Upstream Issue #25698: https://github.com/NousResearch/hermes-agent/issues/25698
- A2A Spec: https://github.com/google/A2A
- Project record: [[planning/a2a-plugin-v1]] (Hermes Wiki)
