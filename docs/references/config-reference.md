---
title: "A2A Plugin — Configuration Reference"
created: 2026-06-16
type: reference
tags: [a2a, config, reference]
---

# A2A Plugin — Configuration Reference

## Top-level Structure

All A2A configuration lives under the `a2a:` key in `~/.hermes/config.yaml`:

```yaml
a2a:
  port: 9696
  bind: "127.0.0.1"
  node_name: "hermes-a2a-node"
  node_id: "local"
  profiles_dir: "~/.hermes/profiles"
  signing_profile: null
  rate_limit: 0
  peers: []
```

## Config Keys

### `port`

- **Type:** int
- **Default:** `9696`
- **Env override:** `A2A_PORT`
- **Description:** Port the A2A server listens on for JSON-RPC requests, health checks, and Agent Card serving.

### `bind`

- **Type:** str
- **Default:** `"127.0.0.1"`
- **Env override:** `A2A_BIND`
- **Description:** Bind address for the A2A server. Use `"0.0.0.0"` for public access (requires firewall rules). Use `"127.0.0.1"` when behind a reverse proxy or tunnel.

### `node_name`

- **Type:** str
- **Default:** `"hermes-a2a-node"`
- **Env override:** `A2A_NODE_NAME`
- **Description:** Human-readable name for this node. Used in Agent Card identity. Should be unique per mesh node.

### `node_id`

- **Type:** str
- **Default:** `"local"`
- **Env override:** `A2A_NODE_ID`
- **Description:** Operational identity for provenance tracking. Stamped on outbound task metadata as `source_node`. Should be unique per mesh node. When set correctly, remote peers see the originating node name instead of `"local"`.

### `profiles_dir`

- **Type:** str
- **Default:** `"~/.hermes/profiles"`
- **Env override:** `A2A_PROFILES_DIR`
- **Description:** Directory containing Hermes profile configs for specialist agents. Used by FleetController to discover available agents.

### `signing_profile`

- **Type:** str
- **Default:** `null` (Agent Card NOT signed)
- **Env override:** `A2A_SIGNING_PROFILE`
- **Description:** Name of the profile whose signing key is used to sign the Agent Card (`/.well-known/agent-card.json`). If null, the Agent Card is served unsigned.

### `rate_limit`

- **Type:** int
- **Default:** `0` (disabled)
- **Env override:** `A2A_RATE_LIMIT`
- **Description:** Per-peer request limit per rolling 60-second window. `0` or negative = disabled. Tracks by SHA256 of the Authorization bearer token. In-memory tracking — restart resets counters.

### `peers`

- **Type:** list of dicts
- **Default:** `[]`
- **Env override:** `A2A_PEERS` (JSON string)
- **Description:** List of remote mesh peers. Each entry requires `name`, `url`, and `api_key`. See Peer Configuration below.

## Peer Configuration

Each peer entry is a dict with three required fields:

```yaml
peers:
  - name: "proteus"                    # Unique peer name
    url: "http://proteus.local:9696"   # Peer's A2A server URL
    api_key: "${PROTEUS_API_KEY}"      # Bearer token (${VAR} syntax)
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Unique peer identifier used in routing logs and errors |
| `url` | str | Yes | Full URL of the peer's A2A server |
| `api_key` | str | Yes | Bearer token for authentication. Supports `${ENV_VAR}` resolution |

API keys support `${ENV_VAR}` syntax — the value is resolved from the environment at plugin registration time. This keeps keys out of config files checked into version control.

## Env Var Override Rules

1. **Format:** `A2A_<KEY>` where `KEY` is the config key name uppercased (e.g., `A2A_PORT`, `A2A_NODE_NAME`)
2. **Type coercion:** Strings coerced to the config key's expected type:
   - **int:** `A2A_PORT=9090` → port=9090. Raises `ValueError` on invalid input.
   - **bool:** `A2A_RATE_LIMIT=0` → rate_limit=0. Truthy set: `1`, `true`, `yes`.
   - **list:** `A2A_PEERS='[{"name":"...","url":"...","api_key":"..."}]'` → JSON array.
   - **str:** Pass-through as-is.
3. **Env wins over YAML:** If both are set, the env var value is used.
4. **Unknown keys ignored:** `A2A_UNKNOWN_KEY=foo` has no effect.
5. **Only `CONFIG_KEYS` accepted:** `port`, `bind`, `node_name`, `node_id`, `profiles_dir`, `signing_profile`, `rate_limit`, `peers`.

## Profile Configuration

Each Hermes profile that should be A2A-addressable needs an `a2a:` section in its `config.yaml` at `~/.hermes/profiles/<name>/config.yaml`.

```yaml
a2a:
  intents: ["consultation", "action_request"]
  tags: ["code", "python", "review"]
  description: "Code review specialist"
  streaming: false
  push: false
  input_modes: ["text"]
  output_modes: ["text"]
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `intents` | list | Yes | — | Intent types this profile handles. At least one required. |
| `tags` | list | No | `[]` | Keywords for tag-based routing fallback. |
| `description` | str | No | `""` | Override description for the Agent Card. |
| `streaming` | bool | No | `false` | Whether the profile supports streaming responses. |
| `push` | bool | No | `false` | Whether the profile supports push notifications. |
| `input_modes` | list | No | `["text"]` | Content types the profile accepts. |
| `output_modes` | list | No | `["text"]` | Content types the profile produces. |

## Example Production Config

```yaml
a2a:
  port: 9090
  bind: "0.0.0.0"
  node_name: "production-node"
  node_id: "prod-1"
  signing_profile: "default"
  rate_limit: 60
  peers:
    - name: "staging"
      url: "http://10.0.1.10:9090"
      api_key: "${STAGING_A2A_KEY}"
    - name: "partner"
      url: "https://a2a.partner.example.com"
      api_key: "${PARTNER_A2A_KEY}"
```

With env var overrides for per-startup differences:

```bash
# Same config file, different node
A2A_NODE_NAME="failover" A2A_NODE_ID="prod-2" A2A_PORT=9091 hermes gateway restart
```

## Internal Architecture

- **Config loading:** YAML → `_read_a2a_config()` → env var overlay → `register()`
- **Env var resolution in peer API keys:** `${VAR}` syntax resolved by `_resolve_env()` at registration time
- **Rate limiting:** `RateLimitMiddleware` (Starlette `BaseHTTPMiddleware`) — runs on every request before handler dispatch
- **Audit logger:** JSONL at `~/.hermes/a2a_audit.jsonl`, 10MB rotation, 3 backups
- **Watchdog:** `scripts/mesh-watchdog.py` — passive health observer

## Related

- [Troubleshooting](../troubleshooting.md)
- [Partner Onboarding](../partner-onboarding.md)
- [User Manual](../USER-MANUAL.md)
