---
title: A2A Intent Schemas — Tesla Node Capabilities
created: 2026-05-21
type: reference
tags: [a2a, intents, schema, api-contract, partner]
---

# A2A Intent Schemas — Tesla Node

This document defines the supported intents, their payload schemas, and examples for the Tesla VPS A2A node. External partners code against this contract.

## Node Info

| Field | Value |
|-------|-------|
| Node name | tesla-vps |
| Agent Card URL | `http://100.96.0.2:9696/.well-known/agent-card.json` |
| Protocol | A2A v1.0, JSON-RPC binding |
| Endpoint | `POST /a2a/jsonrpc` |
| Default auth | Bearer token via Authorization header |

## Intent Definitions

### consultation

**Semantics:** "Receive this message, process it, send a reply." Catch-all for unstructured requests, questions, or coordination messages.

**Routing:** Routes to the main agent (Tesla). The main agent processes directly or recruits a specialist internally.

**Payload:**

```json
{
  "message": {
    "role": "ROLE_USER",
    "parts": [
      {"text": "What's the status of the mesh deployment?"}
    ]
  }
}
```

**Response:**

```json
{
  "result": {
    "message": {
      "role": "ROLE_AGENT",
      "parts": [
        {"text": "Mesh is live. Both nodes connected on 100.96.0.0/16."}
      ]
    }
  }
}
```

### action_request

**Semantics:** "Perform this action and report back." Imperative tasks with side effects.

**Routing:** Routes to a specialist profile tagged `action_request` (Cody for code, Ops for environment).

**Payload:**

```json
{
  "message": {
    "role": "ROLE_USER",
    "parts": [
      {"text": "Review the SSRF guard and ensure RFC 6598 is handled."}
    ]
  },
  "metadata": {
    "intent_type": "action_request"
  }
}
```

**Tags to target specific profiles:**
- `code`, `patch`, `python`, `feature` → Cody
- `deploy`, `config`, `systemd`, `cron`, `ops` → Ops

### research

**Semantics:** "Investigate this topic and report findings." Multi-source intelligence gathering.

**Routing:** Routes to Odin (research profile).

**Payload:**

```json
{
  "message": {
    "role": "ROLE_USER",
    "parts": [
      {"text": "Find the latest kernel CVE for Ubuntu 22.04"}
    ]
  },
  "metadata": {
    "intent_type": "research"
  }
}
```

### diagnose

**Semantics:** "Find the root cause of this problem." Triage and analysis.

**Routing:** Routes to Ray (diagnostics profile).

**Payload:**

```json
{
  "message": {
    "role": "ROLE_USER",
    "parts": [
      {"text": "Nginx returning 502 since last reboot"}
    ]
  },
  "metadata": {
    "intent_type": "diagnose"
  }
}
```

### review / audit

**Semantics:** "Check this output against a standard." Verification and structured review.

**Routing:** Routes to Reviewer.

**Payload:**

```json
{
  "message": {
    "role": "ROLE_USER",
    "parts": [
      {"text": "Verify the audit logger tests cover all 12 event types"}
    ]
  },
  "metadata": {
    "intent_type": "review"
  }
}
```

## Implicit Routing

If `metadata.intent_type` is omitted, the intent is derived from the message parts:
- `data` parts → `action_request`
- `url` or `raw` parts → `consultation`
- `text` only → `consultation`

Unqualified messages route to the main agent (Tesla). This is the default entry point for peer-to-peer coordination.

## Common Message Structures

### Error Response

```json
{
  "error": {
    "code": -32602,
    "message": "Invalid params",
    "data": "..."
  }
}
```

| Code | Meaning |
|------|---------|
| -32601 | Method not found |
| -32602 | Invalid params |
| -32009 | Version not supported |
| -32000 | Auth failure |

### Auth Failure

```json
{
  "error": {
    "code": -32000,
    "message": "Unauthorized: invalid or missing bearer token"
  }
}
```

## Versioning

This intent schema is versioned via the Agent Card's `version` field. Breaking changes increment the minor version. Partners should check the Agent Card version on each reconnection.

## References

- Profile configs: `~/.hermes/profiles/*/config.yaml`
- Agent Card: `http://100.96.0.2:9696/.well-known/agent-card.json`
- A2A spec: https://google.github.io/A2A/#/
