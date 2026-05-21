---
title: A2A Plugin — Operations Runbook
created: 2026-05-20
type: runbook
status: current
tags: [a2a, plugin, ops, runbook]
---

# A2A Plugin — Operations Runbook

## Overview

The A2A plugin (`a2a-server`) implements the A2A Protocol v1.0 as a Hermes plugin. It enables agent-to-agent communication — profiles on this node can dispatch tasks to each other, and cross-node dispatch to mesh peers (Proteus, partners) is the next phase.

**Port:** 9696
**Bind:** 127.0.0.1 (local only — external access via reverse proxy)
**Plugin kind:** standalone (daemon thread in gateway process)

## Architecture

```
A2A SDK (Google v1.0.3)    — protocol framing, JSON-RPC, AgentCard types
  ^ adapter/                — HermesExecutor, CardBuilder, CardSigner, ProfileDiscovery
  ^ core/                   — domain models, FleetController, Orchestrator (zero A2A imports)
```

**Boundary rule enforced:** `grep -r "from a2a import" src/core/` returns zero.

## How to Verify the Plugin is Running

```bash
# Check plugin registration
hermes plugins list | grep a2a-server

# Check port is listening
ss -tlnp | grep 9696

# Health endpoint
curl http://127.0.0.1:9696/health

# Agent Card (6 Tesla profiles)
curl http://127.0.0.1:9696/.well-known/agent-card.json

# Send a test message (dispatch via AIAgent)
curl -X POST http://127.0.0.1:9696/a2a/jsonrpc \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"SendMessage",
    "params":{
      "message":{
        "message_id":"t1",
        "role":"ROLE_USER",
        "parts":[{"text":"ping"}]
      }
    }
  }'
```

## Plugin Registration

The plugin is installed as a symlink:

```bash
# Symlink from plugins dir to source
ln -sf /home/freetea/src/a2a-core/src/a2a_plugin ~/.hermes/plugins/a2a-server

# Enable in config.yaml (under plugins.enabled)
```

The pip package is installed as editable:

```bash
cd ~/src/a2a-core && \
~/.hermes/hermes-agent/venv/bin/pip install -e '.[all]'
```

## Profile Configuration

Each profile that should be A2A-addressable needs an `a2a:` section at the end of its `config.yaml`. Example (from ray):

```yaml
a2a:
  intents: ["diagnose", "consultation"]
  tags: ["linux", "health-check", "nginx", "diagnostics"]
  streaming: false
  push: false
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `intents` | Yes | Intent types this profile handles. At least one required for A2A discovery. |
| `tags` | No | Keywords for tag-based routing fallback. |
| `description` | No | Override description for the Agent Card. Falls back to profile config. |
| `examples` | No | Example payloads shown in Agent Card for remote orchestrators. |
| `streaming` | No | Whether profile supports streaming responses (default false). |
| `push` | No | Whether profile supports push notifications (default false). |
| `input_modes` | No | Content types the profile accepts (default ["text"]). |
| `output_modes` | No | Content types the profile produces (default ["text"]). |

## Config Reference

The `a2a:` section in `~/.hermes/config.yaml` controls the plugin:

```yaml
a2a:
  port: 9696
  bind: "127.0.0.1"
  node_name: "tesla-vps"
  node_id: "local"
  profiles_dir: "~/.hermes/profiles"
```

## Dispatch Mechanism

Each inbound A2A request creates a fresh `AIAgent` in the daemon thread — the same pattern used by the cron scheduler. The agent targets the FleetController-routed profile and executes the request via `agent.chat(goal)`.

This replaces the earlier `ctx.dispatch_tool("delegate_task", ...)` mechanism, which cannot work from a daemon thread (no active AIAgent session context).

**Key characteristics:**
- Each request gets its own AIAgent session → no state leakage
- Profile's SOUL.md identity is inherited
- Memory is disabled (stateless per request)
- Toolsets are restricted (no delegate_task, clarify, send_message, memory, cronjob)
- Errors produce clean `TaskResult(status="failed")` — never propagate exceptions

## Adding a New Profile to A2A

1. Ensure the profile exists at `~/.hermes/profiles/<name>/` with `config.yaml`
2. Add `a2a:` section with at least one `intent`
3. Restart gateway
4. Verify profile appears in Agent Card: `curl http://127.0.0.1:9696/.well-known/agent-card.json | jq '.skills[] | select(.id == "skill/<name>")'`

## Troubleshooting

### Dispatch returns "delegate_task requires a parent agent context"
This was the G13 gap — now fixed by the AIAgent-based dispatch. If it still occurs, the server is running old code. Restart gateway.

### Plugin not loading
- Check symlink: `ls -la ~/.hermes/plugins/a2a-server`
- Check pip install: `~/.hermes/hermes-agent/venv/bin/pip show a2a-core`
- Check config.yaml: `grep -A 5 'enabled:' ~/.hermes/config.yaml`
- Check logs: `hermes logs --level debug | grep a2a`

### Port conflict
Another process on port 9696. Kill it:
```bash
kill $(lsof -ti :9696)
```
Then restart gateway.

### Profile not appearing in Agent Card
- Verify `a2a:` section has `intents` with at least one value
- Verify YAML is valid: `python3 -c "import yaml; yaml.safe_load(open('/home/freetea/.hermes/profiles/<name>/config.yaml'))"`
- Restart gateway

## File Inventory

| Path | Purpose |
|------|---------|
| `~/src/a2a-core/src/a2a_plugin/` | Plugin entry point (`register()`) |
| `~/src/a2a-core/src/adapter/` | HermesExecutor, CardBuilder, CardSigner, ProfileDiscovery |
| `~/src/a2a-core/src/core/` | Domain models, FleetController, Orchestrator (0 A2A imports) |
| `~/src/a2a-core/tests/` | 177 tests (71 core, 106 adapter) |
| `~/wiki-ops/planning/a2a-plugin-delivery-plan.md` | Full delivery plan with gates |
| `docs/changes/2026-05-20-a2a-phase0-validation.md` | ✅ Found |
| `docs/changes/2026-05-20-a2a-phase1-checkpoint.md` | ✅ Found |
| `docs/changes/2026-05-20-a2a-phase1-complete.md` | ✅ Found |
