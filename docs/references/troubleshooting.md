---
title: "A2A Plugin — Troubleshooting"
created: 2026-06-16
type: reference
tags: [a2a, troubleshooting, debugging]
---

# A2A Plugin — Troubleshooting

## Quick Diagnosis

Run these commands first to identify the failure layer:

```bash
# 1. Is the plugin loaded?
grep "a2a-server" ~/.hermes/logs/agent.log | tail -3

# 2. Is the port listening?
lsof -i :9696

# 3. Health endpoint
curl -s http://127.0.0.1:9696/health

# 4. Agent Card
curl -s http://127.0.0.1:9696/.well-known/agent-card.json | python3 -m json.tool

# 5. Peer connectivity
grep "MeshPeerClient" ~/.hermes/logs/agent.log | tail -5
```

## Symptom → Cause → Fix

### Plugin not loading

| Symptom | Cause | Fix |
|---------|-------|-----|
| `a2a-server` not in `hermes plugins list` | Plugin not in `plugins.enabled` | Add `a2a-server` to `plugins.enabled` in `~/.hermes/config.yaml` |
| `ModuleNotFoundError: a2a_plugin` | Package not installed in venv | Run `pip install -e '.[all]'` in the plugin directory |
| Plugin loads but no port listening | `register()` failed silently | Check `~/.hermes/logs/agent.log` for error trace |
| `entry point not found` | Old plugin version without `register()` | Re-clone and reinstall from the v1.0 repository |

### Connection failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `curl: connection refused` on health endpoint | Server not running or wrong port | Verify `lsof -i :9696`. Check `a2a.port` in config. Restart gateway. |
| `Peer 'X' not connected` in dispatch | Peer unreachable at startup | Verify `curl http://<peer-ip>:9696/health`. Check firewall. The retry loop auto-reconnects. |
| `Connection refused` from peer | Peer's `bind` is `127.0.0.1` | Peer must bind to `0.0.0.0` for network access. Or use a tunnel. |
| `Connection timeout` | Network path blocked | Check firewall rules. Verify DNS resolution. Check for proxy misconfiguration. |
| WARP peer unreachable | Tunnel not active | Run `warp-cli status` on both nodes. Verify split tunnel includes `100.96.0.0/16`. |

### Authentication failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| HTTP 401 Unauthorized | Token mismatch | Verify both nodes use the same API key. Check `.env` is loaded. Restart gateway after changing env vars. |
| `Authorization header missing` | No Bearer token in request | Add `Authorization: Bearer <token>` header to all requests. |
| `Invalid bearer token` | Token doesn't match any configured peer | Check the token value. Check for trailing whitespace. Verify the peer is configured in `a2a.peers`. |

### Request failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| HTTP 429 Rate limit exceeded | Too many requests from one peer | Increase `a2a.rate_limit` or set to `0`. Counters reset on restart. |
| `A2A-Version` error | Missing or wrong version header | Add `A2A-Version: 1.0` header. Case-sensitive. |
| `Method not found` | Wrong method name | Use `"SendMessage"` (camelCase). Not `"send_message"` or `"tasks/send"`. |
| `Invalid params` | Malformed request body | Validate JSON syntax. Check `messageId` is present. Verify `parts` array is non-empty. |
| JSON parse error (-32700) | Invalid JSON | Check for trailing commas, unquoted keys, or encoding issues. |

### Profile and Agent Card issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Profile not in Agent Card | Missing `a2a:` section in profile config | Add `a2a:` with at least one `intent` to `~/.hermes/profiles/<name>/config.yaml`. Restart gateway. |
| Agent Card shows empty skills | No profiles with `a2a:` config | Verify profiles exist. Check `profiles_dir` config. Restart gateway. |
| Profile appears but wrong intents | Typo in `intents` list | Check YAML syntax. Verify intent names match supported values. |

### Provenance and metadata

| Symptom | Cause | Fix |
|---------|-------|-----|
| `source_node: "local"` on remote | Default `node_id` not changed | Set `a2a.node_id` in config or `A2A_NODE_ID` env var. Restart gateway. |
| Missing `reference_task_ids` | Task constructed outside MeshPeerClient | Ensure tasks are dispatched through the standard A2A handler path. |

### Audit and logging

| Symptom | Cause | Fix |
|---------|-------|-----|
| Audit log not writing | Permission or disk issue | Check `~/.hermes/a2a_audit.jsonl` permissions. Check disk space. The logger catches I/O errors gracefully. |
| Audit log growing fast | High request volume | Rotate manually: `truncate -s 0 ~/.hermes/a2a_audit.jsonl`. Or adjust rotation settings. |
| No entries in audit log | Audit logger not initialized | Verify plugin loaded. Check `~/.hermes/logs/agent.log` for audit logger errors. |

### Config override issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Env var `A2A_<KEY>` has no effect | Wrong key name or type | Only `port`, `bind`, `node_name`, `node_id`, `profiles_dir`, `signing_profile`, `rate_limit`, `peers` are supported. Check uppercase. |
| `ValueError` on startup from env var | Type mismatch | `A2A_PORT` must be an integer. `A2A_PEERS` must be a JSON array string. |
| Peer env var not resolved | `${VAR}` syntax error | Use `${VAR_NAME}` in YAML. The var must be set in the same shell that runs Hermes. |

### Gateway restart issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| In-flight tasks lost after restart | Tasks not in task store | One-shot dispatches without orchestrator tracking are lost. Save task IDs before restart. |
| Peer reconnection slow after restart | Retry loop restarting | The exponential backoff starts at 1s. Most peers reconnect within 1-2 minutes. Check logs for `reconnected peer` messages. |

## Health Checks

### Self-diagnostic script

```bash
python scripts/mesh-watchdog.py
# ✅ A2A watchdog — all clear
#   ✅  /health: 200 OK
#   ✅  configured peers: 2
#   ✅  disk (~/.hermes): 8GB free
```

### Manual health check

```bash
# Server health
curl -s http://127.0.0.1:9696/health | python3 -m json.tool

# Peer health (for each configured peer)
curl -s http://<peer-ip>:9696/health | python3 -m json.tool

# Port check
lsof -i :9696

# Process check
ps aux | grep -i a2a | grep -v grep
```

## Log Locations

| Log | Path | Purpose |
|-----|------|---------|
| Agent log | `~/.hermes/logs/agent.log` | Plugin lifecycle, peer connections, errors |
| Audit log | `~/.hermes/a2a_audit.jsonl` | All A2A operations (JSONL, auto-rotating) |
| Error log | `~/.hermes/logs/errors.log` | Uncaught exceptions |

## Key Files

| File | Purpose |
|------|---------|
| `~/.hermes/config.yaml` | Plugin configuration |
| `~/.hermes/.env` | Environment variables (API keys, secrets) |
| `~/.hermes/a2a_audit.jsonl` | Audit trail |
| `~/.hermes/a2a_tasks.db` | Task store (if DatabaseTaskStore enabled) |
| `~/.hermes/profiles/<name>/config.yaml` | Per-profile A2A config |
| `~/.hermes/profiles/<name>/.env` | Per-profile signing key |


### `InvalidAgentResponseError: Received TaskStatusUpdateEvent in message mode`

**Cause:** The executor emitted a `TaskStatusUpdateEvent` after a `Message` in message mode. The SDK's `ActiveTaskConsumer` sets mode on the first event — `Message` sets message mode, `Task`/`TaskStatusUpdateEvent` sets task mode. Mixing them violates the contract.

**Fix:** Update to plugin version >= 2026-06-29. The executor no longer emits `TaskStatusUpdateEvent` in message mode.

**If still occurring:** Check that the gateway is running the updated plugin code. Restart the gateway after updating.

### Profiles dispatch as remote (`a2a://`) instead of local (`internal:`)

**Cause:** `_endpoint_for()` compared `cap.node_id` against hardcoded `"local"`, but profiles get their `node_id` from A2A config (e.g., `"my-node"`). The mismatch caused all profiles to be treated as remote peers.

**Fix:** Update to plugin version >= 2026-06-29. The function now compares against `self._local_node_id` from config.

**Verify:** Check audit log — `task_in_progress` entries should show `is_remote=false` for local profiles.

### Agent not appearing in Agent Card

**Cause:** Profile `config.yaml` missing `a2a:` section, or `a2a:` section has no `intents` list.

**Fix:** Add to `~/.hermes/profiles/<name>/config.yaml`:
```yaml
a2a:
  intents:
    - <intent-type>
  description: "One-line description"
```

Profiles without `intents` are skipped by discovery.

### `Peer 'X' not connected` in dispatch

## Related

- [Config Reference](config-reference.md)
- [Partner Onboarding](partner-onboarding.md)
- [User Manual](../USER-MANUAL.md)
