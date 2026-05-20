# A2A Server Deployment — Phase Transition

> How the A2A server moved from standalone test process to plugin-managed service across development phases. Documented because the transition pattern (standalone → watchdog → plugin auto-load) is generalizable for any Hermes plugin that runs an HTTP server.

## Phase 1: Standalone Test (development)

```
python scripts/start-server.py --port 9696
# Starts uvicorn daemon thread in its own process
# Dispatch is MOCK — returns TaskResult directly, no Hermes delegation
```

**When:** Plugin under active development, entry point not yet registered in Hermes venv. Gateway restart would disrupt active WebUI session.

**Pros:** Zero Hermes dependency, fast iteration, easy kill/restart.
**Cons:** No `delegate_task` dispatch (mock only), session-tied if started via `terminal(background=true)`.

## Phase 2: Standalone + Watchdog (interim)

```
cronjob(action='create', name='a2a-server-health', schedule='every 2m',
        no_agent=True, script='a2a-server-watchdog.sh')
```

**When:** Need uptime assurance before permanent solution lands. Server started via `terminal(background=true)` and risks termination when session ends.

**Principle (from macos-services skill):** Watchdog cron is appropriate ONLY as a stopgap for session-tied services. It is NOT a permanent solution on an always-on machine.

**Cleanup trigger:** As soon as the permanent pattern (Phase 3) is verified, kill the watchdog.

## Phase 3: Plugin Auto-Load (permanent)

```
1. pip install -e . in Hermes venv               # entry point registered
2. hermes gateway restart                          # PluginManager re-scans
3. register() fires → server starts in daemon thread inside gateway process
4. Kill standalone server: kill $(lsof -ti :9696)
5. Remove watchdog cron: cronjob list → cronjob remove
```

**When:** Entry point registered in Hermes venv, gateway restarted, plugin confirmed loaded.

**Pros:** `delegate_task` dispatch works, clean lifecycle (daemon thread dies with gateway), no separate process.

## Config Profiles (all phases)

Six profiles with `a2a:` sections in `config.yaml`:

| Profile | Intents | Purpose |
|---------|---------|---------|
| sherlock | consultation, research | Research and perception |
| builder | instruction | Code and artifact execution |
| doris | review | Change review and verification |
| cua-lord | instruction | Computer use testing |
| wiki-checker | action_request | Wiki convention audits |
| wiki-gardener | instruction | Wiki fix execution |

All defined at `~/.hermes/profiles/*/config.yaml`. The `a2a:` key is consumed only by the A2A plugin's `discover_profiles()` — Hermes core ignores unknown keys.

## Verification Sequence

After ANY phase transition, verify the pipeline:

```bash
# 1. Agent Card (profile + skill discovery)
curl -s http://127.0.0.1:9696/.well-known/agent-card.json | python -m json.tool | head -20
# Expected: "skills" array with 6 entries

# 2. SendMessage (JSON-RPC round trip)
python -c "
import urllib.request, json, uuid
data = json.dumps({
    'jsonrpc': '2.0', 'id': 1, 'method': 'SendMessage',
    'params': {
        'message': {
            'message_id': f'msg-{uuid.uuid4().hex[:8]}',
            'role': 'ROLE_USER',
            'parts': [{'text': 'Hello'}],
            'metadata': {'intent_type': 'consultation'},
        },
    },
}).encode()
req = urllib.request.Request('http://127.0.0.1:9696/a2a/jsonrpc',
    data=data, headers={'Content-Type': 'application/json', 'A2A-Version': '1.0'})
resp = urllib.request.urlopen(req, timeout=5)
result = json.loads(resp.read())
msg = result.get('result', {}).get('message', {})
for p in msg.get('parts', []):
    print(p.get('text', p))
"

# 3. Intent routing for each intent type
for intent in consultation instruction review action_request research; do
  python -c "..."  # same as above with metadata.intent_type=$intent
done
```

**Expected routing table:**
| intent_type | profile | 
|---|---|
| consultation | sherlock |
| research | sherlock |
| instruction | builder |
| review | doris |
| action_request | wiki-checker |

## Pitfalls

- **Port conflict on restart:** If the plugin starts a server AND a standalone instance is still running, `register()` fails with "Address already in use". Kill standalone first: `kill $(lsof -ti :9696)`
- **Watchdog restarts a dead server that lost its process:** The watchdog checks port liveness, not dispatch health. A running process that's hung (e.g., Python GIL deadlock on a future dispatch) won't be detected.
- **Phase transitions are one-way:** Once the plugin auto-load works, don't run the standalone simultaneously — they'd compete for the same port. The config port is 9696 in both modes.
