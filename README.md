# A2A Plugin — Agent-to-Agent Mesh for Hermes

A Google A2A v1.0 protocol plugin for [Hermes Agent](https://hermes-agent.nousresearch.com). Enables a mesh of agent nodes — Hermes, OpenClaw, or any A2A-compliant implementation — to discover each other, route tasks by capability, and execute cross-node workflows with provenance tracking, audit logging, and rate limiting.

**New to A2A?** Start with the [User Manual](docs/USER-MANUAL.md) — it walks through installation, first task, peer setup, and troubleshooting. The manual covers six networking options: direct TCP, reverse proxy, Cloudflare WARP, Tailscale/Headscale, NetBird, and WireGuard.

> **Disclaimer:** This plugin is presented as-is. It was built for a specific setup and works — but it is not actively maintained. Clone it, fork it, and hack it to fit your needs. If you find bugs or improve it, contributions via PR are welcome but response times are not guaranteed.

---

## What This Enables

Two or more agent nodes connected in a mesh. Each node runs an A2A server (this plugin). Peers are configured in YAML. When node A needs a capability it doesn't have locally, it sends a task to a peer that does. The peer executes, returns results. Provenance chains track which node originated which request.

**Concrete example:**

```
Node A (Hermes) ←→ Node B (Hermes)
                    ↑
               Partner (OpenClaw)
```

Node A sends a task to Node B. Node B routes it to a Partner specialist. The Partner specialist sees `source_node: "node-a"` in the provenance metadata. Everyone knows where the work came from.

## Boundaries

**In scope:**
- Hermes plugin: register/unregister lifecycle, auto-loads with gateway
- Bearer-token auth between peers
- Agent Card discovery (signed or unsigned)
- Task dispatch (SendMessage → execution → result)
- Capability-based routing via FleetController
- Audit logging (JSONL, 10MB rotation, 3 backups)
- Rate limiting (per-peer, configurable, HTTP 429)
- Provenance tracking (reference_task_ids, source_node metadata)
- Peer reconnection (exponential backoff, automatic)
- Env var config overrides (A2A_<KEY>)
- Health monitoring (passive watchdog script)

**Out of scope (deliberate, v1.0):**
- gRPC binding (HTTP/JSON-RPC only)
- OAuth2/OIDC auth (bearer tokens only)
- Distributed tracing (OpenTelemetry)
- Multi-region failover
- Hardware security module

## Success & Failure

**Success looks like:**
- `curl http://127.0.0.1:9696/health` → `{"status":"ok","service":"a2a-server"}`
- Peer sends task → task executes → result returns with provenance metadata
- Retry loop reconnects a peer that came online after our gateway
- Rate-limited peer gets HTTP 429 with `Retry-After: 60`
- Audit log at `~/.hermes/a2a_audit.jsonl` captures each transition

**Failure looks like (all handled cleanly):**
- Peer unreachable → `TaskResult(status="failed", error="Peer 'X' not connected")`
- Rate limit exceeded → HTTP 429 with clear error body
- Malformed request → JSON-RPC parse error (-32700)
- Disk full → audit logger catches the I/O error, continues serving
- Gateway restart → in-flight tasks recovered via task store

---

# Installation

## Prerequisites

- Hermes Agent v0.14+ installed and running
- Python 3.11+
- For peer mesh: any TCP connectivity between nodes (direct, VPN, tunnel, or reverse proxy)

## Install in Hermes Venv

```bash
git clone https://github.com/OrendaD/hermes-a2a-plugin.git
cd hermes-a2a-plugin

# Install the plugin package and all dependencies into Hermes venv
~/.hermes/hermes-agent/venv/bin/pip install -e '.[all]'

# Symlink so Hermes discovers the plugin
ln -sf $(pwd)/src/a2a_plugin ~/.hermes/plugins/a2a-server
```

Dependencies are pulled from PyPI via the `pip install` command. The `[all]` extra installs:
- `a2a-sdk` — Google's A2A SDK (protobuf, client, server types)
- `starlette>=1.0.1` — ASGI server framework (CVE-2026-48710 patched)
- `httpx` — HTTP client for peer communication
- `pyyaml` — YAML config parsing
- `cryptography` — Agent Card signing (ES256)

## Add to Config

```yaml
# ~/.hermes/config.yaml
hermes:
  a2a:
    port: 9696
    bind: "127.0.0.1"
    node_name: "my-node"
    node_id: "my-node"
    rate_limit: 60  # requests/min per peer; 0 = disabled
    peers:
      - name: "peer-node"
        url: "http://peer-node.local:9696"
        api_key: "${PEER_API_KEY}"  # resolved from env at startup
```

## Restart Gateway

```bash
hermes gateway restart
```

Verify the A2A server is live:

```bash
curl http://127.0.0.1:9696/health
# → {"status":"ok","service":"a2a-server"}
```

## First-Run Test

After installation, run the first-run test to verify everything is wired correctly:

```bash
# Run the integration test suite (real HTTP through middleware stack)
python -m pytest tests/integration/ -q --tb=short

# Expected output: 22 passed in ~4s

# Full test suite (366 tests, all layers)
python -m pytest tests/ -q --tb=short
```

An agent can check the exit code (`0` = pass) and parse the output for `"passed"`.

---

# Architecture

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
       │ (Node B, │
       │ Partner) │
       └──────────┘
```

## Middleware Stack (order matters)

Requests arrive at the ASGI app and pass through each middleware in sequence:

1. **`A2AVersionMiddleware`** — validates the `A2A-Version` header. Rejects non-1.0 requests before they reach the handler.
2. **`RateLimitMiddleware`** — checks per-peer rate limit. Returns HTTP 429 with `Retry-After` if exceeded.
3. **Handler** — dispatches to `HermesExecutor` for A2A task execution.

## Strict Layer Boundary

`src/core/` has zero A2A SDK imports — the domain layer is protocol-agnostic. Verify:

```bash
grep -r "from a2a" src/core/   # MUST return zero
```

---

# Configuration

All config keys live under `a2a:` in the Hermes config YAML. Environment variables override at runtime.

## Config Reference

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `port` | int | 9696 | `A2A_PORT` | A2A server listen port |
| `bind` | str | `"127.0.0.1"` | `A2A_BIND` | Listen address (`"0.0.0.0"` for public) |
| `node_name` | str | `"hermes-a2a-node"` | `A2A_NODE_NAME` | Human-readable node name (Agent Card) |
| `node_id` | str | `"local"` | `A2A_NODE_ID` | Provenance identity (seen by peers) |
| `profiles_dir` | str | `"~/.hermes/profiles"` | `A2A_PROFILES_DIR` | Profile discovery directory |
| `signing_profile` | str | null | `A2A_SIGNING_PROFILE` | Profile name for Agent Card signing |
| `rate_limit` | int | 0 (disabled) | `A2A_RATE_LIMIT` | Requests/minute per peer token |
| `peers` | list | [] | `A2A_PEERS` (JSON) | Peer definitions (name, url, api_key) |

## Peer Configuration

Each peer requires three fields:

```yaml
a2a:
  peers:
    - name: "peer-node"                  # Used in routing logs and errors
      url: "http://peer-node.local:9696" # Peer's A2A server URL
      api_key: "${PEER_API_KEY}"         # Bearer token (supports ${VAR} syntax)
```

API keys support `${ENV_VAR}` resolution — values are resolved from the environment at startup, keeping keys out of config files checked into git.

## Env Var Override Rules

- `A2A_<KEY>` matches the config key name uppercased
- Type coercion: int (int(val)), str (as-is), list (JSON parse), bool (1/true/yes)
- Env var wins over YAML when both are set
- Unknown `A2A_<KEY>` values are silently ignored
- Supported keys: `port`, `bind`, `node_name`, `node_id`, `profiles_dir`, `signing_profile`, `rate_limit`, `peers`

---

# Running the Tests

```bash
# Full suite (366 tests)
python -m pytest tests/ -q

# By layer
python -m pytest tests/core/ -q          # Domain models, FC routing, orchestrator
python -m pytest tests/adapter/ -q       # Executor, auth, audit, mesh client, signing
python -m pytest tests/plugin/ -q        # Plugin config, env var parsing
python -m pytest tests/integration/ -q   # Real HTTP through middleware stack

# Integration tests require no running gateway — Starlette TestClient
```

---

## Mesh Health

A passive health check script verifies the server is running and responsive:

```bash
python scripts/mesh-watchdog.py
# ✅ A2A watchdog — all clear
#   ✅  /health: 200 OK
#   ✅  configured peers: 2 (proteus, partner)
#   ✅  disk (~/.hermes): 8GB free
```

The script is stateless per-tick — it checks, reports, exits. No modifications to the running system.

---

## Repo Docs

| Path | Audience | Content |
|------|----------|---------|
| `docs/USER-MANUAL.md` | All | Complete user manual |
| `docs/references/a2a-protocol-links.md` | All | Outbound links to spec, SDK, documentation |
| `docs/references/a2a-spec-summary.md` | All | Condensed A2A v1.0 specification |
| `docs/references/config-reference.md` | Operators | Full configuration reference |
| `docs/references/intent-schemas.md` | Developers | Intent payload contracts |
| `docs/references/troubleshooting.md` | Operators | Symptom→cause→fix matrix |
| `docs/references/architecture.md` | Developers | Layer diagram and design decisions |
| `docs/references/signing-adr.md` | Developers | Agent Card signing decision record |
| `docs/references/partner-onboarding.md` | Operators | Adding peers to your mesh |
| `docs/guides/a2a-peer-setup.md` | Operators | Step-by-step peer enrollment |
| `docs/guides/a2a-plugin-runbook.md` | Operators | Plugin lifecycle and usage |

---

# Troubleshooting

If something isn't working, check the [Troubleshooting Guide](docs/references/troubleshooting.md) — it covers 20 common failure scenarios with symptom→cause→fix tables.

Quick diagnosis:

```bash
# Is the plugin loaded?
grep "a2a-server" ~/.hermes/logs/agent.log | tail -3

# Is the port listening?
lsof -i :9696

# Health endpoint
curl http://127.0.0.1:9696/health

# Agent Card
curl http://127.0.0.1:9696/.well-known/agent-card.json | python3 -m json.tool
```

---

# Getting Help

- **Issues:** [GitHub Issues](https://github.com/OrendaD/hermes-a2a-plugin/issues)
- **A2A Protocol:** [a2a-protocol.org](https://a2a-protocol.org/latest/specification/) | [GitHub](https://github.com/google/A2A)
- **Hermes Agent:** [Documentation](https://hermes-agent.nousresearch.com/docs) | [GitHub](https://github.com/NousResearch/hermes-agent)

---

# License

Apache 2.0 (matching the A2A SDK license)

---

# Acknowledgments

This plugin builds on the work of [iamagenius00/hermes-a2a-preview](https://github.com/iamagenius00/hermes-a2a-preview), the first A2A protocol implementation for Hermes Agent. That project demonstrated the feasibility of A2A-over-Hermes, validated the SSRF protection model, and established the friend-based auth pattern. The v1.0 plugin in this repository is a ground-up rewrite with a different architecture (hexagonal, protocol-agnostic core) but owes its existence to that proof of concept.
