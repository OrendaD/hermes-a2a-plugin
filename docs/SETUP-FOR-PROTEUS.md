# A2A Plugin — Cross-Node Test Setup (for Proteus)

## What Changed

I've taken over the A2A plugin development. The plugin has been through Phases 0-2:

- **Phase 0:** Code validated, 254 tests passing
- **Phase 1:** Plugin bootstrapped on Tesla VPS, port 9696, dispatch working via AIAgent per request
- **Phase 2:** Auth (bearer tokens), SSRF guard, Agent Card signing (fixed), version negotiation, outbound peer client

## What We Need From You

Your iMac needs to run the A2A plugin so we can test cross-node dispatch (Tesla → Proteus).

## Setup Steps

### 1. Update the repo

```bash
cd ~/path/to/a2a-plugin  # your local workspace
git pull origin main
```

### 2. Install dependencies

```bash
# Use your Hermes venv
pip install -e '.[all]'
```

### 3. Add a2a: sections to your profiles

Each profile that should be reachable via A2A needs this at the end of its `config.yaml`:

```yaml
a2a:
  intents: ["consultation", "research"]  # at least one intent
  tags: ["research", "wiki", "linux"]
  streaming: false
  push: false
```

Proteus's profiles (builder, sherlock, doris, wiki-checker, wiki-gardener, cua-lord) — add appropriate intents for each.

### 4. Enable the plugin

```bash
# Symlink plugin
ln -sf /path/to/a2a-plugin/src/a2a_plugin ~/.hermes/plugins/a2a-server

# Add to config.yaml
```

In `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - a2a-server

a2a:
  port: 9696
  bind: "127.0.0.1"
  node_name: "proteus-imac"
  node_id: "local"
  peers:
    - name: tesla
      url: http://100.96.0.2:9696
      api_key: "${TESLA_A2A_KEY}"
      cidr_allow: ["100.96.0.0/16"]
```

### 5. Set the shared bearer token

In `~/.hermes/.env`:

```bash
TESLA_A2A_KEY="<same-token-as-Tesla-has-for-Proteus>"
```

I'll share the token out-of-band (or we use a simple shared secret for now).

### 6. Restart gateway

```bash
# Kill any standalone a2a server on 9696 first
kill $(lsof -ti :9696)

# Restart Hermes gateway
hermes gateway restart
```

### 7. Verify

```bash
# Health
curl http://127.0.0.1:9696/health

# Agent Card
curl http://127.0.0.1:9696/.well-known/agent-card.json

# Test local dispatch
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
        "parts":[{"text":"hello from proteus"}]
      }
    }
  }'
```

### 8. Cross-node test

Once we're both up, I'll send a task from Tesla to one of Proteus's profiles. You'll see it arrive as an A2A request on your server.

## Expected Behaviour

- **No auth:** Requests without `Authorization: Bearer <token>` will still be processed (auth context created but not yet enforced)
- **Version:** Missing `A2A-Version: 1.0` header → `-32009 VersionNotSupportedError`
- **Agent Card:** Should show all your A2A-enabled profiles as skills
- **Dispatch:** Tasks route to the right profile via FleetController

## If Something Breaks

Check the gateway logs:

```bash
hermes logs --level debug | grep a2a
```
