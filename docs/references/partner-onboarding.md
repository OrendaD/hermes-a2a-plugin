---
title: "A2A Partner Onboarding — Adding a Peer"
created: 2026-06-16
type: reference
tags: [a2a, partner, onboarding, mesh, operations]
---

# A2A Partner Onboarding — Adding a Peer

Step-by-step guide for adding a new peer to your A2A mesh. Works with any network path — direct TCP, VPN, reverse proxy, or Cloudflare WARP.

## Prerequisites

- Both nodes running the A2A plugin (v1.0+)
- Network connectivity between nodes (any TCP path)
- A shared API key (generated out of band)

## Step 1 — Generate an API Key

On one node, generate a shared secret:

```bash
openssl rand -hex 32
```

Share this key with the peer operator out of band (encrypted chat, email, Signal). Do not send it over the A2A channel.

## Step 2 — Add the Peer

On **your** node, edit `~/.hermes/config.yaml`:

```yaml
a2a:
  peers:
    - name: "partner-name"
      url: "http://<partner-ip>:9696"
      api_key: "${PARTNER_API_KEY}"
```

Add the API key to `~/.hermes/.env`:

```bash
export PARTNER_API_KEY="<the-shared-secret>"
```

## Step 3 — Share Your Agent Card URL

Give your peer your Agent Card URL so they can configure their side:

- **Direct TCP:** `http://<your-ip>:9696/.well-known/agent-card.json`
- **Reverse proxy:** `https://yourdomain.com/.well-known/agent-card.json`
- **WARP mesh:** `http://<your-warp-ip>:9696/.well-known/agent-card.json`

The Agent Card lists your node's skills, intents, and input/output modes.

## Step 4 — Peer Adds You (Reverse Direction)

The peer follows the same steps on their side:

1. Generate or receive your API key
2. Add you as a peer in their `config.yaml`
3. Set the API key in their `.env`
4. Restart their gateway

Both nodes must use the same API key for bidirectional auth.

## Step 5 — Restart Gateways

```bash
hermes gateway restart
```

On restart, the plugin connects to all configured peers. Check the logs:

```bash
grep "MeshPeerClient" ~/.hermes/logs/agent.log
# Expected: "connected peer 'partner-name' at http://... (N skills registered)"
```

## Step 6 — Verify Round-Trip

```bash
# From your node, test dispatch to the peer
curl -s -X POST http://<partner-ip>:9696/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -H "Authorization: Bearer *** \
  -d '{
    "jsonrpc": "2.0",
    "id": "onboard-001",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "onboard-001",
        "role": "ROLE_USER",
        "parts": [{"type": "text", "text": "Ping from onboarding test. Reply with your node name."}]
      }
    }
  }'
```

Expected: JSON-RPC response with `ROLE_AGENT` message containing the peer's node name.

## Network Options

### Option A: Direct TCP

Simplest setup. Both nodes must be reachable by IP.

```yaml
peers:
  - name: "peer"
    url: "http://192.168.1.100:9696"
    api_key: "${PEER_API_KEY}"
```

**Requirements:**
- Open port 9696 on both nodes (or your configured port)
- No NAT traversal needed if on the same LAN

### Option B: Reverse Proxy (internet-facing)

For nodes that can't directly reach each other. TLS termination at the proxy.

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

**Peer URL:** `https://a2a.yourdomain.com`

**Requirements:**
- TLS certificate (Let's Encrypt, etc.)
- Proxy must forward `/.well-known/` paths for Agent Card discovery
- A2A server binds to `127.0.0.1` (proxy connects locally)

### Option C: Cloudflare WARP Mesh

Encrypted mesh network for teams. No TLS management, no firewall rules.

```bash
# Find your WARP virtual IP
ip addr show CloudflareWARP
# inet 100.96.x.x/32
```

```yaml
peers:
  - name: "warp-peer"
    url: "http://100.96.x.x:9696"
    api_key: "${WARP_PEER_API_KEY}"
```

**Requirements:**
- Both nodes enrolled in the same Cloudflare Zero Trust WARP team
- Split tunnel includes `100.96.0.0/16`
- No additional TLS — WARP encrypts traffic

For enrollment instructions, see [Cloudflare Zero Trust documentation](https://developers.cloudflare/cloudflare-one/connections/connect-networks/).

### Option D: SSH Tunnel (temporary/testing)

For quick testing without network configuration:

```bash
# On your machine, tunnel to the peer
ssh -L 9696:127.0.0.1:9696 user@peer-host
```

```yaml
peers:
  - name: "ssh-peer"
    url: "http://127.0.0.1:9696"
    api_key: "${PEER_API_KEY}"
```

### Option E: Tailscale / Headscale (mesh VPN)

Tailscale (or its open-source self-hosted counterpart Headscale) creates a mesh VPN with automatic key management and NAT traversal. No firewall rules or port forwarding needed.

```bash
# Install Tailscale on both nodes
# macOS: brew install tailscale
# Linux: curl -fsSL https://tailscale.com/install.sh | sh

# Start Tailscale
tailscale up

# Find your Tailscale IP
tailscale ip -4
# 100.x.x.x
```

```yaml
peers:
  - name: "tailscale-peer"
    url: "http://100.x.x.x:9696"
    api_key: "${PEER_API_KEY}"
```

**Headscale** is a self-hosted open-source implementation of the Tailscale control server. Same wireguard protocol, you manage the coordination server. Good for teams that want Tailscale's UX without the SaaS dependency.

**Requirements:**
- Tailscale installed on both nodes
- Both nodes authenticated to the same Tailscale network (or Headscale instance)
- No additional firewall config — Tailscale handles NAT traversal

### Option F: NetBird (mesh VPN)

NetBird is an open-source mesh VPN built on WireGuard with additional features: NAT traversal, relay fallback, and peer grouping. Similar to Tailscale but fully open-source with a self-hosted control plane option.

```bash
# Install NetBird on both nodes
# macOS: brew install netbird
# Linux: curl -fsSL https://install.netbird.io/install.sh | sh

# Connect
netbird up

# Find your NetBird IP
netbird status
```

```yaml
peers:
  - name: "netbird-peer"
    url: "http://100.x.x.x:9696"
    api_key: "${PEER_API_KEY}"
```

**Requirements:**
- NetBird installed on both nodes
- Both nodes connected to the same NetBird network
- No additional firewall config

### Option G: WireGuard (manual mesh)

For full control, WireGuard provides a lightweight VPN tunnel. You manage keys and peer configuration manually.

```ini
# /etc/wireguard/wg0.conf (on each node)
[Interface]
PrivateKey = <private-key>
Address = 10.0.0.1/24

[Peer]
PublicKey = <peer-public-key>
Endpoint = <peer-public-ip>:51820
AllowedIPs = 10.0.0.2/32
```

```yaml
peers:
  - name: "wg-peer"
    url: "http://10.0.0.2:9696"
    api_key: "${PEER_API_KEY}"
```

**Requirements:**
- WireGuard installed on both nodes
- Manual key generation and exchange
- Firewall: UDP port 51820 (or your chosen port)

## Troubleshooting

### Peer not connecting

```
MeshPeerClient: failed to connect peer 'X': ...
```

1. Check network: `curl http://<peer-ip>:9696/health`
2. Check peer's A2A server: `ss -tlnp | grep 9696`
3. Check firewall: port open on both nodes
4. Check SSRF: peer IP not in blocked range

### Auth failure (401)

1. Verify both sides have matching API keys
2. Check env var is set in `~/.hermes/.env`
3. Restart gateway after setting env var

### Agent Card unreachable (404)

1. Verify path: `/.well-known/agent-card.json` (not `/agent-card.json`)
2. Check reverse proxy routing if using external URL
3. Verify peer's A2A server is running

### Connection refused

1. Remote peer's `bind` must be `0.0.0.0` for network access
2. Verify firewall: port open on both nodes
3. Check network path (VPN, tunnel, WARP status)

## References

- [Config Reference](config-reference.md) — peer configuration details
- [Troubleshooting](troubleshooting.md) — expanded troubleshooting
- [Architecture](architecture.md) — mesh peer client design
- [User Manual](../USER-MANUAL.md) — Section 9 (Add a Mesh Peer)
