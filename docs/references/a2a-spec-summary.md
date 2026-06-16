---
title: "A2A v1.0 Specification — Summary"
created: 2026-06-16
type: reference
tags: [a2a, spec, protocol, reference]
source: https://a2a-protocol.org/latest/specification/
---

# A2A v1.0 Specification — Summary

Condensed reference of the A2A protocol for plugin users. Full specification: https://a2a-protocol.org/latest/specification/

## Overview

The Agent2Agent (A2A) Protocol is an open standard for communication between AI agent systems. It provides a common language for agents built with different frameworks, languages, or vendors.

**Key properties:**
- Transport-agnostic (JSON-RPC, gRPC, HTTP+JSON)
- Capability-based discovery (Agent Cards)
- Task-oriented (not chat-oriented)
- Protocol-agnostic domain layer

## Protocol Layers

| Layer | Purpose | Binding |
|-------|---------|---------|
| Canonical Data Model | Core data structures (protobuf) | Protocol-neutral |
| Abstract Operations | Fundamental capabilities | Binding-independent |
| Protocol Bindings | Transport-specific implementation | JSON-RPC, gRPC, REST |

## Core Operations

| Operation | JSON-RPC Method | Description |
|-----------|----------------|-------------|
| Send Message | `SendMessage` | Send a task to an agent |
| Get Task | `GetTask` | Retrieve task status and results |
| Cancel Task | `CancelTask` | Cancel a running task |
| Set Push Notification | `SetPushNotificationConfig` | Configure push notifications |
| Get Push Notification | `GetPushNotificationConfig` | Get push notification config |
| Get Card | `GetAgentCard` | Retrieve Agent Card (via `/.well-known/agent-card.json`) |

## Data Model

### Task

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique task identifier |
| `sessionId` | string | Conversation session identifier |
| `status` | TaskStatus | Current state and timestamp |
| `artifacts` | Artifact[] | Task outputs |
| `history` | Message[] | Conversation history |

### Task States

```
submitted → working → completed
                      → failed
                      → canceled
                      → input-required → working (resume)
```

### Message

| Field | Type | Description |
|-------|------|-------------|
| `messageId` | string | Unique message identifier |
| `role` | enum | `ROLE_USER` or `ROLE_AGENT` |
| `parts` | Part[] | Content parts (text, file, data) |
| `metadata` | map | Arbitrary key-value pairs |

### Part Types

| Type | Fields | Description |
|------|--------|-------------|
| TextPart | `text` | Plain text content |
| FilePart | `file`, `mimeType` | File content (inline or reference) |
| DataPart | `data`, `mimeType` | Structured data (JSON) |

### Agent Card

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Agent name |
| `description` | string | What the agent does |
| `version` | string | Agent Card version |
| `url` | string | Agent endpoint URL |
| `capabilities` | Capabilities | Supported features |
| `skills` | Skill[] | Available skills/capabilities |
| `authentication` | Auth | Auth requirements |
| `signatures` | Signature[] | JWS signatures (optional) |

### Skill

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique skill identifier |
| `name` | string | Human-readable name |
| `description` | string | What the skill does |
| `tags` | string[] | Keywords for routing |
| `examples` | string[] | Example inputs |
| `inputModes` | string[] | Accepted content types |
| `outputModes` | string[] | Produced content types |

## Error Handling

| Code | Name | Description |
|------|------|-------------|
| `-32700` | ParseError | Malformed JSON |
| `-32600` | InvalidRequest | Not a valid JSON-RPC request |
| `-32601` | MethodNotFound | Unknown method |
| `-32602` | InvalidParams | Missing or wrong-type parameters |
| `-32009` | VersionNotSupported | Unsupported A2A version |
| `-32000` | AuthError | Invalid or missing auth |
| `-32001` | TaskNotFound | Task ID not found |
| `-32002` | TaskNotCancelable | Task cannot be canceled |
| `-32003` | PushNotificationNotSupported | Push notifications not supported |
| `-32004` | UnsupportedOperation | Operation not supported |

## Authentication

A2A relies on standard web security practices:

- **Transport security:** TLS (HTTPS) for all production deployments
- **Authentication:** Bearer tokens, API keys, or OAuth2 (implementation-specific)
- **Authorization:** Implementation-specific policies

The A2A protocol itself does not mandate a specific auth mechanism — it transports auth headers and expects the server to validate them.

## Versioning

- Protocol version: `1.0` (semantic versioning)
- Agent Card `version` field: agent-specific versioning
- Version negotiation via `A2A-Version` header
- Servers return `VersionNotSupportedError` for unsupported versions

## Extensions

The A2A protocol supports extensions for additional functionality:

- Declared in Agent Card `capabilities.extensions`
- Backward-compatible (clients ignore unknown extensions)
- Extension points at message, task, and agent card levels

## References

- Full specification: https://a2a-protocol.org/latest/specification/
- GitHub: https://github.com/google/A2A
- SDK: https://pypi.org/project/a2a-sdk/
- [A2A Protocol Links](a2a-protocol-links.md)
- [Intent Schemas](intent-schemas.md)
