---
title: "A2A Plugin — User Manual"
created: 2026-06-16
type: manual
version: 1.0
tags: [a2a, plugin, hermes, mesh, manual]
audience: Hermes Agent users implementing agent-to-agent communication
---

# A2A Plugin — User Manual

## Status

| Capability | Status | Notes |
|------------|--------|-------|
| Single-node profile dispatch | ✅ Working | Local agent-to-agent via A2A protocol |
| Cross-node task dispatch | ✅ Working | Any TCP path between nodes |
| Agent Card discovery | ✅ Working | `/.well-known/agent-card.json` |
| Bearer token auth | ✅ Working | Per-peer tokens, constant-time comparison |
| Rate limiting | ✅ Working | Per-peer, configurable, HTTP 429 |
| Audit logging | ✅ Working | JSONL, 10MB rotation, 3 backups |
| Provenance tracking | ✅ Working | source_node, reference_task_ids |
| Peer reconnection | ✅ Working | Exponential backoff, automatic |
| Agent Card signing | ✅ Working | ES256 (ECDSA P-256) |
| SSRF protection | ✅ Working | Deny-by-default, per-agent exemptions |

**Out of scope (deliberate):**

| Capability | Status | Reason |
|------------|--------|--------|
| gRPC transport | Not planned | HTTP/JSON-RPC only |
| OAuth2/OIDC auth | Not planned | Bearer tokens only |
| Distributed tracing | Not planned | No OpenTelemetry integration |
| Streaming/SSE responses | Not planned | Synchronous request-response |
| Dashboard UI | Not planned | CLI and API only |

**Tested combinations:**

| Component | Version | Notes |
|-----------|---------|-------|
| Hermes Agent | v0.14+ | Plugin entry point requires `register()` API |
| Python | 3.11+ | Required by A2A SDK |
| A2A SDK | 1.0.3+ | Google-maintained, Linux Foundation |
| Starlette | 1.0.1+ | CVE-2026-48710 patched in 1.0.1 |
| Platform | macOS, Linux | Tested on both |

---

# Tutorial — Getting Started

## 1. Prerequisites

Before installing the A2A plugin, confirm:

- **Hermes Agent v0.14+** is installed and running (`hermes --version`)
- **Python 3.11+** is available in the Hermes venv (`~/.hermes/hermes-agent/venv/bin/python3 --version`)
- **Git** is installed (for cloning the plugin repository)
- **Network path** between nodes — or localhost for single-node testing

No Cloudflare mesh, WARP tunnel, or special network configuration is required for basic operation. Any TCP connectivity works — direct IP, VPN, reverse proxy, or localhost.

## 2. Install

```bash
# Clone the plugin
git clone https://github.com/OrendaD/a2a-plugin.git
cd a2a-plugin

# Install into the Hermes venv (includes all dependencies)
~/.hermes/hermes-agent/venv/bin/pip install -e '.[all]'
```

The `[all]` extra installs:
- `a2a-sdk[http-server,signing]` — Google's A2A SDK
- `starlette` — ASGI server framework
- `httpx` — HTTP client for peer communication
- `pyyaml` — YAML config parsing
- `cryptography` — Agent Card signing (ES256)
- `pytest` + `pytest-asyncio` — test framework

## 3. Enable the Plugin

Add `a2a-server` to the enabled plugins list in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - a2a-server
    # ... your other enabled plugins
```

Add the A2A configuration block:

```yaml
a2a:
  port: 9696
  bind: "127.0.0.1"
  node_name: "my-node"
  node_id: "my-node"
  rate_limit: 60
  peers: []
```

Set `node_name` and `node_id` to something unique — these identify your node in the mesh.

## 4. Restart the Gateway

```bash
hermes gateway restart
```

## 5. Verify

```bash
# Health endpoint
curl http://127.0.0.1:9696/health
# Expected: {"status":"ok","service":"a2a-server"}

# Agent Card
curl http://127.0.0.1:9696/.well-known/agent-card.json
# Expected: JSON with your node's capabilities and skills
```

If the health endpoint returns `{"status":"ok","service":"a2a-server"}`, the plugin is running.

## 6. Your First Task

Send a test message to your own node:

```bash
curl -s -X POST http://127.0.0.1:9696/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc": "2.0",
    "id": "test-001",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "ping-001",
        "role": "ROLE_USER",
        "parts": [{"type": "text", "text": "Hello from A2A. Reply with your node name."}]
      }
    }
  }'
```

Expected response: a JSON-RPC result containing a `ROLE_AGENT` message with your node's name.

**What just happened:**
1. Your curl sent a JSON-RPC `SendMessage` to the A2A server
2. The server validated the `A2A-Version: 1.0` header
3. The request was dispatched to your node's main agent
4. The agent processed the message and returned a response
5. The response came back in the same HTTP request (synchronous)

---

# How-to — Working with the Plugin

## 7. Configure Profiles

Each Hermes profile that should be A2A-addressable needs an `a2a:` section in its `config.yaml`.

**Profile location:** `~/.hermes/profiles/<name>/config.yaml`

```yaml
a2a:
  intents: ["consultation", "action_request"]
  tags: ["code", "python", "review"]
  streaming: false
  push: false
```

| Field | Required | Description |
|-------|----------|-------------|
| `intents` | Yes | Intent types this profile handles. At least one required for A2A discovery. |
| `tags` | No | Keywords for tag-based routing fallback. |
| `description` | No | Override description for the Agent Card. |
| `streaming` | No | Whether the profile supports streaming responses (default: false). |
| `push` | No | Whether the profile supports push notifications (default: false). |
| `input_modes` | No | Content types accepted (default: `["text"]`). |
| `output_modes` | No | Content types produced (default: `["text"]`). |

**Verify a profile is visible:**

```bash
curl -s http://127.0.0.1:9696/.well-known/agent-card.json | python3 -m json.tool
```

Each profile with an `a2a:` section appears as a skill in the Agent Card.

## 8. Send Tasks to a Peer

### From curl (direct API)

```bash
curl -s -X POST http://<peer-ip>:<port>/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "jsonrpc": "2.0",
    "id": "task-001",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "msg-001",
        "role": "ROLE_USER",
        "parts": [{"type": "text", "text": "Review the latest commit for security issues."}]
      },
      "metadata": {
        "intent_type": "review"
      }
    }
  }'
```

### From Hermes (agent tools)

If the peer is configured in your `config.yaml` under `a2a.agents`, your agent can use:

```
a2a_discover(name="peer-name")     # Get the peer's Agent Card
a2a_list()                          # List all configured agents
a2a_call(name="peer-name", message="...", intent="consultation")
```

### Intent types

| Intent | Use when |
|--------|----------|
| `consultation` | General questions, coordination, information exchange |
| `action_request` | Imperative tasks — "do X and report back" |
| `research` | Multi-source investigation |
| `diagnose` | Root cause analysis, triage |
| `review` | Verification against a standard |

See [Intent Schemas](references/intent-schemas.md) for payload details and examples.

## 9. Add a Mesh Peer

Three networking paths are available. Choose based on your setup.

### Option A: Direct TCP (simplest)

If both nodes can reach each other by IP:

**Node A — add Node B as a peer:**

```yaml
# ~/.hermes/config.yaml
a2a:
  peers:
    - name: "node-b"
      url: "http://<node-b-ip>:9696"
      api_key: "${NODE_B_API_KEY}"
```

```bash
# ~/.hermes/.env
export NODE_B_API_KEY="<shared-secret>"
```

**Node B — add Node A as a peer (reverse direction):**

```yaml
a2a:
  peers:
    - name: "node-a"
      url: "http://<node-a-ip>:9696"
      api_key: "${NODE_A_API_KEY}"
```

```bash
export NODE_A_API_KEY="<same-shared-secret>"
```

Both nodes must use the same API key for bidirectional auth.

**Firewall:** Open port 9696 (or your configured port) on both nodes.

```bash
# Linux (ufw)
sudo ufw allow 9696/tcp

# macOS
# No firewall config needed if port is open in System Settings
```

### Option B: Reverse Proxy (internet-facing)

For nodes that can't directly reach each other, place a reverse proxy (nginx, Caddy) in front of each A2A server:

```nginx
server {
    listen 443 ssl;
    server_name a2a.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/a2a.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/a2a.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:9696;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
    }

    location /.well-known/ {
        proxy_pass http://127.0.0.1:9696;
    }
}
```

Configure the peer URL to the proxy endpoint:

```yaml
a2a:
  peers:
    - name: "remote-node"
      url: "https://a2a.theirdomain.com"
      api_key: "${REMOTE_API_KEY}"
```

### Option C: Cloudflare WARP Mesh (encrypted tunnel)

For nodes on the same Cloudflare Zero Trust team, WARP provides an encrypted mesh network without managing TLS or firewall rules.

**Setup:**

1. Both nodes enrolled in the same Cloudflare Zero Trust WARP team
2. Split tunnel includes `100.96.0.0/16` (or `100.64.0.0/10`)
3. Each node gets a virtual IP on the `100.96.x.x` CGNAT range

```bash
# Find your WARP virtual IP
ip addr show CloudflareWARP
# Look for: inet 100.96.x.x/32
```

Configure peers using WARP IPs:

```yaml
a2a:
  peers:
    - name: "warp-peer"
      url: "http://100.96.x.x:9696"
      api_key: "${WARP_PEER_API_KEY}"
```

No additional TLS needed — WARP encrypts traffic between team members.

For detailed CF Zero Trust enrollment, see the [Cloudflare Zero Trust documentation](https://developers.cloudflare/cloudflare-one/connections/connect-networks/).

### Option D: Tailscale / Headscale (mesh VPN)

Tailscale (or its open-source self-hosted counterpart Headscale) creates a mesh VPN with automatic key management and NAT traversal. No firewall rules or port forwarding needed.

```bash
# Install Tailscale
# macOS: brew install tailscale
# Linux: curl -fsSL https://tailscale.com/install.sh | sh

tailscale up
tailscale ip -4  # shows your Tailscale IP (100.x.x.x)
```

```yaml
peers:
  - name: "tailscale-peer"
    url: "http://100.x.x.x:9696"
    api_key: "${PEER_API_KEY}"
```

Headscale is the self-hosted open-source control server for the WireGuard-based Tailscale protocol. Same UX, you manage the coordination layer.

### Option E: NetBird (mesh VPN)

NetBird is an open-source mesh VPN built on WireGuard with NAT traversal, relay fallback, and peer grouping. Fully open-source with a self-hosted control plane.

```bash
# Install NetBird
# macOS: brew install netbird
# Linux: curl -fsSL https://install.netbird.io/install.sh | sh

netbird up
netbird status  # shows your NetBird IP
```

```yaml
peers:
  - name: "netbird-peer"
    url: "http://100.x.x.x:9696"
    api_key: "${PEER_API_KEY}"
```

### Option F: WireGuard (manual mesh)

For full control, WireGuard provides a lightweight VPN tunnel. You manage keys and peer configuration manually.

```yaml
peers:
  - name: "wg-peer"
    url: "http://10.0.0.2:9696"
    api_key: "${PEER_API_KEY}"
```

### Verify peer connection

After restarting the gateway on both nodes:

```bash
# Check peer is connected (look for MeshPeerClient in logs)
grep "MeshPeerClient" ~/.hermes/logs/agent.log | tail -5
# Expected: "connected peer 'node-b' at http://... (N skills registered)"

# Check peer's Agent Card
curl -s http://<peer-ip>:9696/.well-known/agent-card.json | python3 -m json.tool

# Test round-trip
curl -s -X POST http://<peer-ip>:9696/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "jsonrpc": "2.0",
    "id": "ping-001",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "ping-001",
        "role": "ROLE_USER",
        "parts": [{"type": "text", "text": "Ping. Reply with your node name."}]
      }
    }
  }'
```

## 10. Monitor the Mesh

### Health watchdog

A passive health check script verifies the server is running:

```bash
python scripts/mesh-watchdog.py
# ✅ A2A watchdog — all clear
#   ✅  /health: 200 OK
#   ✅  configured peers: 2 (node-a, node-b)
#   ✅  disk (~/.hermes): 8GB free
```

The script is stateless — it checks, reports, exits. No modifications to the running system.

### Audit log

Every A2A operation is logged to `~/.hermes/a2a_audit.jsonl`:

```bash
# View recent entries
tail -20 ~/.hermes/a2a_audit.jsonl | python3 -m json.tool

# Count operations today
grep "$(date +%Y-%m-%d)" ~/.hermes/a2a_audit.jsonl | wc -l
```

The audit log rotates at 10MB with 3 backups retained.

### Rate limiting

If a peer sends too many requests, they receive HTTP 429 with a `Retry-After` header:

```json
{"error": "Rate limit exceeded"}
```

Configure the limit in `config.yaml`:

```yaml
a2a:
  rate_limit: 60  # requests per minute per peer, 0 = disabled
```

Or via environment variable:

```bash
export A2A_RATE_LIMIT=60
```

Rate limit tracking is in-memory — counters reset on gateway restart.

---

# Reference — Configuration

## 11. Config Reference

All config keys live under `a2a:` in `~/.hermes/config.yaml`.

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `port` | int | `9696` | `A2A_PORT` | Server listen port |
| `bind` | str | `"127.0.0.1"` | `A2A_BIND` | Bind address (`"0.0.0.0"` for public) |
| `node_name` | str | `"hermes-a2a-node"` | `A2A_NODE_NAME` | Human-readable node name (Agent Card) |
| `node_id` | str | `"local"` | `A2A_NODE_ID` | Provenance identity (seen by peers) |
| `profiles_dir` | str | `"~/.hermes/profiles"` | `A2A_PROFILES_DIR` | Profile discovery directory |
| `signing_profile` | str | `null` | `A2A_SIGNING_PROFILE` | Profile for Agent Card signing |
| `rate_limit` | int | `0` | `A2A_RATE_LIMIT` | Requests/min per peer (0 = disabled) |
| `peers` | list | `[]` | `A2A_PEERS` (JSON) | Peer definitions |

### Env var override rules

- Format: `A2A_<KEY>` where `KEY` is the config key uppercased
- Type coercion: int (`int(val)`), str (as-is), list (JSON parse), bool (`1`/`true`/`yes`)
- Env var wins over YAML when both are set
- Unknown `A2A_<KEY>` values are silently ignored

### Peer config

Each peer entry requires:

```yaml
peers:
  - name: "peer-name"              # Unique identifier
    url: "http://<ip>:<port>"      # Peer's A2A server URL
    api_key: "${ENV_VAR_NAME}"     # Bearer token (${VAR} syntax)
```

API keys support `${ENV_VAR}` resolution — values are resolved from the environment at startup, keeping keys out of config files checked into version control.

See [Config Reference](references/config-reference.md) for full details.

## 12. Agent Card Format

The Agent Card is served at `/.well-known/agent-card.json` on the A2A port. It describes your node's capabilities to remote peers.

```bash
curl -s http://127.0.0.1:9696/.well-known/agent-card.json | python3 -m json.tool
```

Key fields:

| Field | Description |
|-------|-------------|
| `name` | Node name (from `a2a.node_name`) |
| `version` | Protocol version |
| `skills` | Array of capabilities (one per profile with `a2a:` config) |
| `skills[].id` | Skill identifier (e.g., `skill/my-profile`) |
| `skills[].intents` | Supported intent types |
| `skills[].tags` | Keywords for routing |

The Agent Card can be signed (ES256) if `a2a.signing_profile` is configured. Unsigned cards are served as plain JSON.

See [A2A Spec Summary](references/a2a-spec-summary.md) for the full Agent Card schema.

---

# Explanation — Architecture & Design

## 13. How It Works

### Layer architecture

```
┌─────────────────────────────────────────────┐
│              Hermes Gateway                  │
│  ┌──────────────────────────────────────┐   │
│  │  A2A Plugin (a2a_plugin/__init__.py) │   │
│  │  ┌──────────┐  ┌────────────────┐   │   │
│  │  │ Starlette │  │ RateLimit      │   │   │
│  │  │ App      │──│ Middleware     │   │   │
│  │  └────┬─────┘  └───────┬────────┘   │   │
│  │       │                 │            │   │
│  │  ┌────▼─────────────────▼──────┐    │   │
│  │  │   A2A Handler (JSON-RPC)    │    │   │
│  │  └────┬────────────────────────┘    │   │
│  │       │                             │   │
│  │  ┌────▼────────────────────────┐   │   │
│  │  │   HermesExecutor            │   │   │
│  │  │   · request_to_intent()     │   │   │
│  │  │   · execute(AI session)     │   │   │
│  │  │   · audit logging           │   │   │
│  │  └────┬───────────┬───────────┘   │   │
│  │       │           │               │   │
│  │  ┌────▼───┐  ┌────▼──────┐      │   │
│  │  │  Fleet │  │  Mesh     │      │   │
│  │  │Control │  │  Peer    │      │   │
│  │  │  ler   │  │  Client  │      │   │
│  │  └───┬────┘  └────┬──────┘      │   │
│  │      │            │             │   │
│  │  ┌───▼────┐  ┌────▼──────┐    │   │
│  │  │ Profile│  │ Retry     │    │   │
│  │  │ Discov │  │ Loop     │    │   │
│  │  └────────┘  └──────────┘    │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
            │  A2A JSON-RPC / HTTP
            ▼
       ┌──────────┐
       │  Peers   │
       └──────────┘
```

### Middleware stack (order matters)

1. **`A2AVersionMiddleware`** — validates the `A2A-Version` header. Rejects non-1.0 requests before they reach the handler.
2. **`RateLimitMiddleware`** — checks per-peer rate limit. Returns HTTP 429 with `Retry-After` if exceeded.
3. **Handler** — dispatches to `HermesExecutor` for A2A task execution.

### Dispatch mechanism

Each inbound A2A request creates a fresh `AIAgent` in a daemon thread — the same pattern used by the cron scheduler. The agent targets the FleetController-routed profile and executes the request via `agent.chat(goal)`.

**Key characteristics:**
- Each request gets its own A2A session — no state leakage between requests
- Profile's SOUL.md identity is inherited
- Memory is disabled (stateless per request)
- Toolsets are restricted (no delegate_task, clarify, send_message, memory, cronjob)
- Errors produce clean `TaskResult(status="failed")` — never propagate exceptions

### Core/adapter boundary

`src/core/` has zero A2A SDK imports — the domain layer is protocol-agnostic. Verify:

```bash
grep -r "from a2a" src/core/
# MUST return zero matches
```

This boundary means the domain models (TaskIntent, TaskResult, FleetController, Orchestrator) can be used with any transport — A2A, REST, gRPC, or direct function calls.

## 14. Security Model

### Auth (inbound)

- Bearer tokens matched against configured peers via `hmac.compare_digest()` (constant-time)
- Unmatched tokens: 401 with audit log entry
- Tokenless requests: rejected by default

### Auth (outbound)

- Token from peer config (`peers[].api_key`) sent as Bearer header
- Empty token = no auth — only works if remote server has an open endpoint

### SSRF protection

Outbound requests to peers are protected by the SSRF guard:

- DNS pinning — resolves hostname once, connects to pinned IP
- Private network blocking — RFC 1918, link-local, metadata IPs blocked by default
- Per-agent exemptions — add `allow_private_target` + `allow_private_reason` for local dev agents
- Redirect following disabled

### Provenance tracking

Every outbound task carries metadata identifying its origin:

| Field | Description |
|-------|-------------|
| `source_node` | The originating node's `node_id` |
| `source_profile` | The profile that initiated the task |
| `reference_task_ids` | Chain of task IDs for tracing |
| `context_id` | Conversation context identifier |

This lets remote peers see where work originated without inspecting the message content.

### What's not covered

- **OAuth2/OIDC** — not implemented. Bearer tokens only.
- **Encryption in transit** — depends on your network. Use TLS reverse proxy or WARP for encryption.
- **Key rotation** — manual. Delete the signing key from `.env`, restart, new keypair generated automatically.

See [Architecture](references/architecture.md) for design rationale and [Signing ADR](references/signing-adr.md) for the signing algorithm decision.

---

# Appendix

## 15. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Health endpoint returns connection refused | Plugin not loaded or port conflict | Check `grep -A5 "enabled:" ~/.hermes/config.yaml`. Check `lsof -i :9696` for port conflicts. |
| `A2A-Version` error | Missing or wrong version header | Add `A2A-Version: 1.0` header to all requests. |
| Peer shows "not connected" | Peer unreachable or not configured | Verify `curl http://<peer-ip>:9696/health`. Check `a2a.peers` in config. Restart gateway. |
| HTTP 401 Unauthorized | Token mismatch | Verify both nodes use the same API key. Check `.env` is loaded. Restart gateway after changing env vars. |
| HTTP 429 Rate limit exceeded | Too many requests from one peer | Increase `a2a.rate_limit` or set to `0` to disable. Counters reset on restart. |
| Profile not in Agent Card | Missing `a2a:` section in profile config | Add `a2a:` with at least one `intent` to `~/.hermes/profiles/<name>/config.yaml`. Restart gateway. |
| `Peer 'X' not connected` in dispatch | Peer was never connected at startup | Check peer URL, API key, and network reachability. The retry loop auto-reconnects within 1-2 minutes if peer comes online. |
| Agent Card shows empty skills | No profiles with `a2a:` config | Add `a2a:` sections to profiles. Verify with `curl http://127.0.0.1:9696/.well-known/agent-card.json`. |
| Audit log not writing | Permission or disk issue | Check `~/.hermes/a2a_audit.jsonl` permissions. Check disk space. Audit logger catches I/O errors gracefully. |
| `Invalid params` JSON-RPC error | Malformed request body | Validate JSON syntax. Check `method` is `"SendMessage"` (case-sensitive). Verify `messageId` is present. |
| Provenance shows `source_node: "local"` | Default node_id not changed | Set `a2a.node_id` in config.yaml or `A2A_NODE_ID` env var. Restart gateway. |
| Config env var override not working | Wrong key name or type | Only `port`, `bind`, `node_name`, `node_id`, `profiles_dir`, `signing_profile`, `rate_limit`, `peers` are supported. Check uppercase. |
| Plugin not loading after install | Entry point not registered | Verify `pip show a2a-core` shows the package. Check `~/.hermes/plugins/a2a-server` symlink exists. |
| WARP peer unreachable | Tunnel not active or split tunnel misconfigured | Verify `warp-cli status` on both nodes. Check split tunnel includes `100.96.0.0/16`. |
| Remote dispatch timeout | Network latency or peer overloaded | Check peer's `/health` endpoint. Increase HTTP client timeout if needed. Check peer logs for processing delays. |

## 16. File Inventory

| Path | Purpose |
|------|---------|
| `src/a2a_plugin/__init__.py` | Plugin entry point (`register()`) |
| `src/adapter/hermes_executor.py` | Task execution via AIAgent sessions |
| `src/adapter/hermes_adapter.py` | A2A-to-domain request translation |
| `src/adapter/agent_card_builder.py` | Agent Card construction from profiles |
| `src/adapter/agent_card_signer.py` | ES256 Agent Card signing |
| `src/adapter/agent_card_route.py` | `/.well-known/agent-card.json` endpoint |
| `src/adapter/mesh_peer_client.py` | Outbound peer communication |
| `src/adapter/peer_registry.py` | Peer configuration management |
| `src/adapter/profile_discovery.py` | Profile scanning and capability extraction |
| `src/adapter/rate_limit_middleware.py` | Per-peer rate limiting |
| `src/adapter/version_middleware.py` | A2A-Version header validation |
| `src/adapter/auth_context_builder.py` | Bearer token authentication |
| `src/adapter/audit_logger.py` | JSONL audit trail |
| `src/adapter/ssrf.py` | SSRF protection (DNS pinning, private network blocking) |
| `src/core/fleet_controller.py` | Profile routing and capability matching |
| `src/core/orchestrator.py` | Task lifecycle management |
| `src/core/domain/models/` | Protocol-agnostic domain models |
| `tests/` | 366 tests across core, adapter, plugin, integration |
| `scripts/mesh-watchdog.py` | Passive health check script |
| `docs/` | Documentation (this manual + references) |

## 17. Test Commands

```bash
# Full suite (366 tests)
python -m pytest tests/ -q

# By layer
python -m pytest tests/core/ -q          # Domain models, FC routing, orchestrator
python -m pytest tests/adapter/ -q       # Executor, auth, audit, mesh client, signing
python -m pytest tests/plugin/ -q        # Plugin config, env var parsing
python -m pytest tests/integration/ -q   # Real HTTP through middleware stack

# Integration tests use Starlette TestClient — no running gateway required
```

## 18. Related

- [A2A Protocol Links](references/a2a-protocol-links.md) — spec, SDK, documentation
- [A2A Spec Summary](references/a2a-spec-summary.md) — condensed protocol reference
- [Config Reference](references/config-reference.md) — full configuration details
- [Intent Schemas](references/intent-schemas.md) — payload contracts and examples
- [Troubleshooting](references/troubleshooting.md) — expanded troubleshooting guide
- [Architecture](references/architecture.md) — design decisions and rationale
- [Signing ADR](references/signing-adr.md) — Agent Card signing algorithm decision
- [Partner Onboarding](references/partner-onboarding.md) — adding peers to your mesh

## License

Apache 2.0 (matching the A2A SDK license)
