---
title: A2A Standalone Server — Plugin Entry Point Fix — Restart Sequence
created: 2026-05-20
updated: 2026-05-20
type: config
tags: [a2a, plugin, server, entry-point, port-conflict, restart]
confidence: high
---

# [2026-05-20] A2A Standalone Server — Entry Point Fix — Restart Sequence

## Problem

The A2A plugin server needs to run inside the Hermes gateway process to access `ctx.dispatch_tool("delegate_task", ...)` for real delegation. Two issues prevented this:

### 1. Entry point mislocated

`a2a-core` was installed via `pip install -e .` during M3.1 (May 19), but the system `pip` targeted `/opt/anaconda3/lib/python3.12/site-packages` — **not** the Hermes venv at `~/.hermes/hermes-agent/venv/lib/python3.11/site-packages`.

The entry point (`hermes_agent.plugins.a2a-server = a2a_plugin`) was therefore invisible to the Hermes gateway process.

**Fix (May 20):** Re-installed explicitly in the Hermes venv:
```bash
cd /Users/fleety/webgui-files/a2a-plugin
source ~/.hermes/hermes-agent/venv/bin/activate
python -m pip install -e .
```

Verified: `PluginManager.discover_and_load(force=True)` finds and loads `a2a-server` successfully.

### 2. Gateway process predates the fix

The Hermes gateway (PID 9151, started Tue 1PM) started before the entry point was fixed. The plugin manager's `discover_and_load()` only runs once at startup — it does not re-scan entry points after process start. The `force=True` parameter re-scans bundled/user/entry-point manifests within the same process, but the running gateway process is a separate address space.

**Therefore:** The a2a-server plugin will only auto-load after a gateway restart.

## Standalone Server (Stopgap)

`scripts/start-server.py` runs the A2A server as an independent process, bypassing the plugin system entirely:

```bash
cd /Users/fleety/webgui-files/a2a-plugin
source ~/.hermes/hermes-agent/venv/bin/activate
python scripts/start-server.py --port 9696
```

Currently running as a background process (PID ~2265, port 9696).

### Limitations

| Aspect | Standalone Server | Plugin (after restart) |
|--------|------------------|----------------------|
| Dispatch | **Mock** — `[profile_name] Dispatched: {goal}` — no actual Hermes sub-agent runs | `ctx.dispatch_tool("delegate_task")` — real Hermes delegation |
| Lifecycle | Manual start, watchdog covers restarts | Auto-starts with gateway |
| Port | 9696 | 9696 (same port — **will conflict**) |
| Config | Reads `a2a:` from config.yaml directly | Same |

### Watchdog Cron

A `no_agent` watchdog cron (`a2a-server-health`) runs every 2 minutes via `~/.hermes/scripts/a2a-server-watchdog.sh`:

```bash
#!/bin/bash
/usr/sbin/lsof -i :9696 -P 2>/dev/null | grep -q LISTEN
if [ $? -eq 0 ]; then
  exit 0  # Running — stay silent
fi
cd /Users/fleety/webgui-files/a2a-plugin || exit 1
source ~/.hermes/hermes-agent/venv/bin/activate
nohup python scripts/start-server.py --port 9696 > /tmp/a2a-server.log 2>&1 &
echo "A2A server was down — restarted on port 9696 (PID $!)"
```

The watchdog is **duct tape** — it only exists because the gateway hasn't been restarted. Once the plugin auto-loads, the watchdog becomes harmful.

## Port Conflict — Required Sequence for Gateway Restart

The standalone server and the plugin server both target port 9696. Before restarting the gateway:

```
1. Kill the standalone server:   kill 2265
2. Optionally disable watchdog:  hermes cron list → cronjob(action="remove", job_id="...")
3. Restart gateway:              hermes gateway stop && hermes gateway run
4. Verify plugin loaded:         curl http://127.0.0.1:9696/.well-known/agent-card.json
```

After step 3, the plugin's `register()` function runs, which calls `_start_server(app, config)`, binding uvicorn to port 9696 inside the gateway process. The dispatch function now has access to `ctx.dispatch_tool("delegate_task")`.

## Remaining After Restart

- The dispatch still returns placeholder responses (`[profile] Dispatched: {goal}`) until the forward-pass from Phase 4 is implemented. The `_dispatch_fn` closure in `register()` calls `ctx.dispatch_tool("delegate_task", args)`, which triggers the Hermes delegation — but the sub-agent result needs to be mapped back to A2A `TaskResult` properly.
- Auth between peers (bearer tokens) is not yet implemented. Currently uses tokenless loopback (`A2A_DEV_LOCALHOST_TRUST_UNTIL` pattern from old plugin — not yet ported to v1.0).
- Profile `a2a:` configs need to exist on Tesla side for cross-node routing to work.

## Verify

```bash
# Check port 9696 ownership
lsof -i :9696 -P

# Expected after restart: python (gateway process), not scripts/start-server.py

# Test A2A round-trip
curl -X POST http://127.0.0.1:9696/a2a/jsonrpc \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"message_id":"test-001","role":"ROLE_USER","parts":[{"text":"ping"}],"metadata":{"intent_type":"consultation"}}}}'
```

## Related

- [[config/2026-05-20-a2a-profile-config]] — Profile config format consumed by the server
- [[planning/a2a-plugin-v1-m3]] — M3 implementation plan (Phase 3 complete)
