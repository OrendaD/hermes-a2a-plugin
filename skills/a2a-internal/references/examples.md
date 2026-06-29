# A2A Internal — Real Usage Examples

Real examples from testing on 2026-06-29. Verified working.

## Basic Message (no targeting)

Routes to best-match agent by intent type.

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
        "parts": [{"text": "Hello. Respond with confirmation."}]
      }
    }
  }'
```

**Result:** Routed to Poe (best match for "consultation" intent).

## Targeted Message (specific agent)

Uses `metadata.target_profile` to route to a specific agent.

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
        "message_id": "sherlock-test-001",
        "role": 1,
        "parts": [{"text": "Hello Sherlock. Confirm you received this."}],
        "metadata": {"target_profile": "sherlock"}
      }
    }
  }'
```

**Result:** Routed to Sherlock. Response confirmed online and A2A channel active.

## Response Format (success)

```json
{
  "result": {
    "message": {
      "messageId": "7e8fbf1b-...",
      "contextId": "1ac4717f-...",
      "taskId": "793ab68c-...",
      "role": "ROLE_AGENT",
      "parts": [{"text": "Agent response here"}]
    }
  },
  "id": 1,
  "jsonrpc": "2.0"
}
```

Key response fields:
- `result.message.role` — always `"ROLE_AGENT"`
- `result.message.parts` — content array
- `result.message.contextId` — conversation context (use for follow-ups)
- `result.message.taskId` — task tracking ID

## Task Routing (with intent override)

Force a specific intent via metadata.

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
        "message_id": "task-001",
        "role": 1,
        "parts": [{"text": "Review and clean up the file at ~/path/to/file.md"}],
        "metadata": {
          "target_profile": "wiki-gardener",
          "intent_type": "instruction"
        }
      }
    }
  }'
```

**Note:** Wiki-gardener only handles `instruction`. Without `intent_type` override, the default "consultation" would fail.

## Error Responses

### Version missing (-32009)
```json
{"error": {"code": -32009, "message": "Version not supported: missing. Expected: 1.0"}}
```
**Fix:** Add `a2a-version: 1.0` header.

### Invalid role format (-32602)
```json
{"error": {"code": -32602, "message": "Invalid params", "data": "...Invalid enum value user..."}}
```
**Fix:** Use `role: 1` (integer), not `role: "user"` (string).

### Invalid parts format (-32602)
```json
{"error": {"code": -32602, "message": "Invalid params", "data": "...no field named 'type'..."}}
```
**Fix:** Use `{"text": "..."}`, not `{"type": "text", "text": "..."}`.

### Missing message_id (-32602)
```json
{"error": {"code": -32602, "message": "Validation failed", "data": "...message_id: Field is required..."}}
```
**Fix:** Include `"message_id": "<unique-id>"`.

### Profile cannot handle intent
```json
{"result": {"message": {"parts": [{"text": "Profile 'xyz' cannot handle intent 'consultation'"}]}}}
```
**Fix:** Check agent roster. Add `intent_type` override in metadata, or verify target profile has matching intent.
