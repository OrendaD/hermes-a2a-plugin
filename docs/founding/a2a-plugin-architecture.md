---
title: A2A Plugin Architecture — Hexagonal Foundation
created: 2026-05-17
updated: 2026-05-17
type: planning
status: draft
tags: [a2a, architecture, hexagonal, profiles, agent-card, mesh]
sources:
  - "https://dev.to/sreeni5018/the-a2a-protocol-misconception-why-your-agent-architecture-matters-more-than-your-framework-3iif"
  - "https://a2a-protocol.org/latest/specification/"
  - "planning/a2a-plugin-v1"
confidence: high
---

# A2A Plugin Architecture — Hexagonal Foundation

## Governing Principle

**A2A is a communication protocol, not an agent framework.** This is the single most important architectural decision. It determines where every piece of code lives and what it's allowed to import.

The spec itself validates this: Section 1.3 defines three explicit layers — Canonical Data Model (protocol-neutral protobuf), Abstract Operations (binding-independent), Protocol Bindings (JSON-RPC/gRPC/REST). The Hexagonal Architecture we adopt mirrors the spec's own structure.

## The Three Layers

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

### The Non-Negotiable Rule

Nothing from the Protocol Layer crosses into the Core Layer. If core code imports `from a2a import ...`, the architecture is broken. The adapter owns every protocol type and is the ONLY bridge.

**Health check (pre-commit hook):**
```bash
grep -r "from a2a import" src/core/   # MUST return zero
grep -r "import a2a" src/core/        # MUST return zero
```

## Profile Workspace Model

Each Hermes profile at `~/.hermes/profiles/<name>/` is a fully independent workspace:

| Resource | Purpose |
|----------|---------|
| `SOUL.md` | Profile identity, role definition, reasoning approach |
| `config.yaml` | Model, provider, tools, terminal settings |
| `.env` | API keys and secrets |
| `sessions/` | Conversation transcripts |
| `skills/` | Reusable procedures specific to this domain |
| `memories/` | Persistent memory stores |
| `workspace/` | Domain runbooks, reference sheets, task-specific documents |
| `cron/` | Scheduled jobs |
| `state.db` | SQLite state database |

**Key insight:** A2A tasks do not carry domain knowledge in the protocol payload. They carry an intent and a task payload. The domain knowledge lives in the profile's workspace — pre-loaded, pre-configured, ready to use. The protocol routes work to the right workspace.

## Agent Card ↔ Profile Mapping

Each profile publishes as an `AgentSkill` on the node's Agent Card:

```json
{
  "name": "Tesla Mesh Node",
  "description": "Hermes agent on VPS (Bali)",
  "skills": [
    {
      "id": "ray",
      "name": "System Diagnostician",
      "description": "Root cause diagnostics with runbook-backed analysis",
      "tags": ["diagnosis", "health-check", "root-cause", "consultation"],
      "examples": [
        "{\"symptoms\": \"Nginx returning 502 on /v1/orders, upstream timeout in logs\", \"scope\": \"full\"}"
      ],
      "inputModes": ["text", "application/json"],
      "outputModes": ["text", "application/json"]
    },
    {
      "id": "ops",
      "name": "Environment Operations",
      "description": "Deployments, config management, systemd, cron",
      "tags": ["deploy", "config", "systemd", "cron"],
      "examples": [
        "{\"action\": \"restart\", \"service\": \"hermes-gateway\", \"reason\": \"config change\"}"
      ],
      "inputModes": ["text", "application/json"],
      "outputModes": ["text", "application/json"]
    },
    {
      "id": "reviewer",
      "name": "Independent Verification",
      "description": "Verification and quality checks against spec",
      "tags": ["review", "verify", "check", "audit"],
      "examples": [
        "{\"check_type\": \"deployment\", \"artifact\": \"/tmp/deploy-v3.2.tar.gz\"}"
      ],
      "inputModes": ["text", "application/json"],
      "outputModes": ["text", "application/json"]
    }
  ],
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "stateTransitionHistory": true
  },
  "securitySchemes": {
    "bearerToken": {
      "httpAuthSecurityScheme": {
        "scheme": "bearer",
        "bearerFormat": "JWT"
      }
    }
  },
  "supportedInterfaces": [
    {
      "url": "http://100.96.0.2:8081",
      "protocolBinding": "JSONRPC"
    }
  ]
}
```

## SSRF and Mesh Networking

Our mesh addresses are **100.96.x.x** (RFC 6598 CGNAT space). This is critical for the transport layer:

- RFC 6598 is NOT RFC 1918. Most SSRF guards and private-IP detectors do NOT block 100.x.x.x by default.
- Some do. The plugin's SSRF layer MUST explicitly allow 100.96.0.0/16 for mesh communication.
- Global allow should be configurable, not hardcoded — client nodes may use different address ranges.

**SSRF model detail:**
- Deny-by-default for any IP that's private, loopback, link-local, or CGNAT
- Explicit allow for configured mesh peers (100.96.0.1, 100.96.0.2)
- Per-peer `allow_private_target` (from legacy plugin pattern) carries forward

## Transport Selection (v1.0)

| Binding | v1.0? | Rationale |
|---------|-------|-----------|
| JSON-RPC | ✅ Primary | SDK optimizes for it, route factories exist, spec's primary binding |
| HTTP/REST | ✅ Auxiliary | Health checks, curl testing, simple integrations (SDK provides `create_rest_routes()`) |
| gRPC | ❌ Later | Codegen overhead, proto compilation, no benefit at our scale |

## Auth Model (v1.0)

| Context | Scheme | Detail |
|---------|--------|--------|
| Mesh peers (Tesla ↔ Proteus) | Bearer token | Pre-shared, stored in each peer's credential store |
| Client nodes | API key | Simpler onboarding, no OAuth complexity |
| In-task escalation | AUTH_REQUIRED state | Task pauses, secondary creds acquired out-of-band |

Auth schemes are declared in `AgentCard.securitySchemes`. Clients read requirements, acquire creds out-of-band, and include in every request.

## Version Negotiation

- Servers MUST accept `A2A-Version: 1.0` header
- Servers MUST validate and return `VersionNotSupportedError` on mismatch
- The SDK handles this — but the plugin must ensure it's forwarded or respected when acting as a client

## Related Pages

- [[planning/a2a-plugin-v1]] — Project record and decision log
- [[planning/a2a-orchestration-patterns]] — Dynamic orchestration model
- [[planning/a2a-domain-contracts]] — Protocol-agnostic domain models
- [[planning/mesh-orchestration]] — Mesh coordination architecture
- [[Inkbox/cloudflare-mesh]] — Cloudflare Mesh network
