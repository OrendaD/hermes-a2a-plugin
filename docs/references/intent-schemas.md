---
title: "A2A Intent Schemas — Payload Contracts"
created: 2026-06-16
type: reference
tags: [a2a, intents, schema, api-contract]
---

# A2A Intent Schemas — Payload Contracts

## Overview

A2A tasks carry an intent that determines how the receiving node routes and processes the work. The intent is specified in the `metadata.intent_type` field of the JSON-RPC params.

## Node Info

| Field | Value |
|-------|-------|
| Protocol | A2A v1.0, JSON-RPC binding |
| Endpoint | `POST /a2a/jsonrpc` |
| Auth | Bearer token via `Authorization` header |
| Version header | `A2A-Version: 1.0` (required) |

## Intent Definitions

### consultation

**Semantics:** "Receive this message, process it, send a reply." Catch-all for unstructured requests, questions, or coordination messages.

**Routing:** Routes to the main agent. The main agent processes directly or recruits a specialist internally.

**Payload:**

```json
{
  "jsonrpc": "2.0",
  "id": "task-001",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-001",
      "role": "ROLE_USER",
      "parts": [
        {"type": "text", "text": "What's the status of the deployment?"}
      ]
    }
  }
}
```

**Response:**

```json
{
  "jsonrpc": "2.0",
  "id": "task-001",
  "result": {
    "id": "task-001",
    "status": {"state": "completed"},
    "artifacts": [
      {
        "parts": [
          {"type": "text", "text": "Deployment is live. 3/3 pods healthy."}
        ]
      }
    ]
  }
}
```

### action_request

**Semantics:** "Perform this action and report back." Imperative tasks with side effects.

**Routing:** Routes to a specialist profile tagged with matching capabilities.

**Payload:**

```json
{
  "jsonrpc": "2.0",
  "id": "task-002",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-002",
      "role": "ROLE_USER",
      "parts": [
        {"type": "text", "text": "Review the SSRF guard and ensure RFC 6598 is handled."}
      ]
    },
    "metadata": {
      "intent_type": "action_request"
    }
  }
}
```

**Routing hints via tags:**
- `code`, `patch`, `python`, `feature` → coding specialist
- `deploy`, `config`, `systemd`, `cron`, `ops` → operations specialist

### research

**Semantics:** "Investigate this topic and report findings." Multi-source intelligence gathering.

**Routing:** Routes to a research specialist profile.

**Payload:**

```json
{
  "jsonrpc": "2.0",
  "id": "task-003",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-003",
      "role": "ROLE_USER",
      "parts": [
        {"type": "text", "text": "Find the latest kernel CVE for Ubuntu 22.04"}
      ]
    },
    "metadata": {
      "intent_type": "research"
    }
  }
}
```

### diagnose

**Semantics:** "Find the root cause of this problem." Triage and analysis.

**Routing:** Routes to a diagnostics specialist profile.

**Payload:**

```json
{
  "jsonrpc": "2.0",
  "id": "task-004",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-004",
      "role": "ROLE_USER",
      "parts": [
        {"type": "text", "text": "Nginx returning 502 since last reboot"}
      ]
    },
    "metadata": {
      "intent_type": "diagnose"
    }
  }
}
```

### review

**Semantics:** "Check this output against a standard." Verification and structured review.

**Routing:** Routes to a review specialist profile.

**Payload:**

```json
{
  "jsonrpc": "2.0",
  "id": "task-005",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-005",
      "role": "ROLE_USER",
      "parts": [
        {"type": "text", "text": "Verify the audit logger tests cover all 12 event types"}
      ]
    },
    "metadata": {
      "intent_type": "review"
    }
  }
}
```

## Implicit Routing

If `metadata.intent_type` is omitted, the intent is derived from the message parts:

- `data` parts → `action_request`
- `url` or `raw` parts → `consultation`
- `text` only → `consultation`

Unqualified messages route to the main agent. This is the default entry point for peer-to-peer coordination.

## Error Responses

All error responses follow JSON-RPC error format:

```json
{
  "jsonrpc": "2.0",
  "id": "task-001",
  "error": {
    "code": -32602,
    "message": "Invalid params",
    "data": "Missing required field: message"
  }
}
```

| Code | Meaning |
|------|---------|
| `-32700` | Parse error — malformed JSON |
| `-32600` | Invalid request — not a valid JSON-RPC request |
| `-32601` | Method not found — unknown method name |
| `-32602` | Invalid params — missing or wrong-type parameters |
| `-32009` | Version not supported — A2A-Version header missing or unsupported |
| `-32000` | Auth failure — invalid or missing bearer token |

## Versioning

This intent schema is versioned via the Agent Card's `version` field. Breaking changes increment the minor version. Peers should check the Agent Card version on each reconnection.

## References

- [A2A v1.0 Specification](https://a2a-protocol.org/latest/specification/) — Section 3.2 (Operations)
- [User Manual](../USER-MANUAL.md) — Section 12 (Agent Card Format)
- [Config Reference](config-reference.md) — Profile configuration
