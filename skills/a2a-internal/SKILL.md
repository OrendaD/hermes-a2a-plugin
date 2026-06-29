---
name: a2a-internal
description: "Use when sending messages to other agents via A2A protocol. Internal agent-to-agent messaging over local A2A server."
version: 1.0.0
author: Hermes A2A Plugin
license: MIT
metadata:
  hermes:
    tags: [a2a, messaging, agent-to-agent, internal]
    related_skills: []
---

# A2A Internal Messaging

## Overview

A2A (Agent-to-Agent) protocol enables synchronous messaging between agents running on the same Hermes node. Messages route through the local A2A server at `localhost:9696`, which dispatches to target profiles via the fleet controller.

Each request creates a **fresh, one-shot agent** — no persistent session, no memory of prior interactions.

## When to Use

- Requesting consultation from another agent mid-task
- Delegating a well-scoped subtask to a specialist
- Cross-agent coordination without inbox (synchronous, not async)

**Don't use for:**
- Tasks requiring back-and-forth clarification (use Telegram/WebUI)
- Tasks needing full conversation context (A2A messages are stateless)

## JSON-RPC Message Format

### SendMessage (method: `SendMessage`)

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "SendMessage",
  "params": {
    "message": {
      "message_id": "<unique-id>",
      "role": 1,
      "parts": [{"text": "<your message>"}],
      "metadata": {
        "target_profile": "<agent-name>"
      }
    }
  }
}
```

**Required headers:**
```
Content-Type: application/json
a2a-version: 1.0
```

**Field reference:**

| Field | Type | Notes |
|-------|------|-------|
| `message.role` | int | `1` = USER (you), `2` = AGENT (response) |
| `message.message_id` | string | Unique ID, UUID recommended |
| `message.parts` | array | `[{"text": "content"}]` — text only currently |
| `message.metadata.target_profile` | string | Optional. Route to a specific agent |
| `method` | string | `SendMessage` (PascalCase, not camelCase) |

**Routing:** Without `target_profile`, the fleet controller picks the best match for the intent type. With `target_profile`, it routes to that specific agent.

## curl Test Recipe

```bash
curl -s -X POST http://localhost:9696/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "a2a-version: 1.0" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "SendMessage",
    "params": {
      "message": {
        "message_id": "test-001",
        "role": 1,
        "parts": [{"text": "Hello. Respond with confirmation."}],
        "metadata": {
          "target_profile": "<agent-name>"
        }
      }
    }
  }'
```

## Verify Server Health

```bash
curl -s http://localhost:9696/health
# Expected: {"status":"ok","service":"a2a-server"}

curl -s http://localhost:9696/.well-known/agent-card.json
# Shows all registered agent skills
```

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| Server running | ✅ | Port 9696, daemon thread |
| Agent Card | ✅ | Profile skills registered |
| Profile routing | ✅ | Fleet controller dispatches to correct profile |
| Agent execution | ✅ | Fresh AIAgent created per request |
| Response format | ✅ | Message-only in message mode |
| Local dispatch | ✅ | node_id compared against local_node_id |
| Streaming | ❌ | Not implemented |
| Cross-node | Depends | Requires peer A2A server online and configured |

## Dependencies

- `greenlet` — required by SQLAlchemy async (task store)
- `a2a-sdk` — A2A protocol types and server
- `a2a-core` — this plugin (editable install)

## Common Pitfalls

1. **Forgetting `a2a-version: 1.0` header** → -32009 error
2. **Using `role: "user"` (string)** → must be `role: 1` (integer enum)
3. **Using `{"type": "text", "text": "..."}`** → must be `{"text": "..."}` (no type field)
4. **Missing `message_id`** → -32602 validation error
5. **Gateway restart required** after config changes to `a2a:` sections
6. **Profile config overrides global** — A2A config must be in `~/.hermes/profiles/<name>/config.yaml`

## Memory Convention (Amnesia Prevention)

A2A creates a **fresh, one-shot agent** per request. The receiving agent has no memory of previous interactions. Both sides risk amnesia.

**Two-sided logging convention:**

### Initiator (you)

After receiving a response, log the exchange to your own silo.

### Receiver (in your message)

Append an instruction for the receiver to log to their activity log. Only needed for one-shot agents without a persistent memory contract.

## Agent Card Registration

To make a profile A2A-addressable, add to `~/.hermes/profiles/<name>/config.yaml`:

```yaml
a2a:
  intents:
    - <primary-intent>
  description: "One-line description"
  tags:
    - <keyword1>
```

Profiles without `intents` are skipped by discovery.

## Verification Checklist

- [ ] `curl localhost:9696/health` returns `{"status":"ok"}`
- [ ] Agent card shows target agent in skills list
- [ ] Request includes `a2a-version: 1.0` header
- [ ] `message.role` is integer (1=USER)
- [ ] `message.parts` uses `{"text": "..."}` format
- [ ] `message.message_id` is unique string
- [ ] Target profile has `a2a:` section with `intents` in config.yaml
