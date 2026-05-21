---
title: A2A Peer Setup — Add a Mesh Peer
created: 2026-05-21
type: runbook
tags: [a2a, peer, mesh, config, operations]
---

# A2A Peer Setup

How to add a new peer node to the A2A mesh.

## Prerequisites

- Both nodes enrolled in the same Cloudflare Zero Trust WARP team
- Both nodes running the A2A plugin (port 9696)
- A2A API key pre-shared between nodes (out of band)

## Step 1 — Get the Peer's Mesh IP

On the peer node, run:

```bash
ip addr show CloudflareWARP
# Look for: inet 100.96.x.x/32
```

This is the peer's mesh-routable IP. Both nodes must be on the `100.96.0.0/16` CGNAT range.

## Step 2 — Configure the Peer

Edit `~/.hermes/config.yaml` on your node. Add a peer entry under `a2a.peers`:

```yaml
a2a:
  peers:
    - name: <peer-name>
      url: http://<peer-mesh-ip>:9696
      api_key: "${PEER_API_KEY_ENV_VAR}"
      cidr_allow: ["100.96.0.0/16"]
```

Field reference:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique peer identifier (e.g. "proteus", "partner-alpha") |
| `url` | Yes | Full URL: `http://<mesh-ip>:9696` |
| `api_key` | Yes | Bearer token for auth. Use `${ENV_VAR}` syntax, never plaintext |
| `cidr_allow` | Yes | CIDRs the SSRF guard allows for this peer. Mesh: `["100.96.0.0/16"]` |

## Step 3 — Set the API Key

Add to `~/.hermes/.env`:

```bash
export PROTEUS_A2A_KEY="<the-shared-secret>"
```

**Important:** Both nodes must use the same API key for bidirectional auth until per-connection key pairs are implemented (Phase 5+).

## Step 4 — Restart Gateway

Fleety handles gateway restarts. Flag the need after config is ready.

## Step 5 — Verify

### Peer connects at startup

Check the plugin logs:

```bash
journalctl --user -u hermes-gateway --no-pager -n 50 | grep -i "MeshPeerClient"
# Expected: "connected peer 'proteus' at http://100.96.x.x:9696 (N skills registered)"
```

### Peer capabilities registered

```bash
curl http://127.0.0.1:9696/.well-known/agent-card.json | jq '.skills[].name'
# Should show peer's skills prefixed with <peer-name>/
```

### Cross-node dispatch

```bash
curl -X POST http://127.0.0.1:9696/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tasks/send",
    "params": {
      "id": "test-001",
      "sessionId": "test-session",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "hello"}]
      }
    }
  }'
```

## Troubleshooting

### "Peer 'X' not connected"

1. Verify peer URL is correct (mesh IP, not localhost)
2. Verify both nodes on same WARP team: `warp-cli --accept-tos status`
3. Check peer's A2A server is listening: `ss -tlnp | grep 9696`
4. Check SSRF isn't blocking: look for "Blocked SSRF target" in gateway logs

### Connection refused

1. Remote peer's A2A server must bind to `0.0.0.0` (not `127.0.0.1`)
2. Verify firewall: port 9696 open on both nodes (ufw allow 9696)
3. Check WARP tunnel status on both nodes

### Auth failure (401)

1. Verify `api_key` env var is set in `.env`
2. Both nodes must use matching keys
3. Restart gateway after changing env vars

## References

- Config: `~/.hermes/config.yaml` — `a2a.peers` section
- SSRF module: `src/adapter/ssrf.py`
- Mesh peer client: `src/adapter/mesh_peer_client.py`
- Peer registry: `src/adapter/peer_registry.py`
