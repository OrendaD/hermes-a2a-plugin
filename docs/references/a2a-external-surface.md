---
title: A2A External Surface — Network Configuration
created: 2026-05-21
type: reference
tags: [a2a, network, tls, reverse-proxy, config]
---

# A2A External Surface

## Server Configuration

The A2A server is configured under `a2a:` in `~/.hermes/config.yaml`:

```yaml
a2a:
  port: 9696
  bind: "0.0.0.0"
```

The server binds to `0.0.0.0:9696` for mesh accessibility. Do not expose port 9696 directly to the internet — use a reverse proxy for external access.

## Network Layers

| Layer | Protocol | Port | Purpose |
|-------|----------|------|---------|
| Internal mesh | HTTP | 9696 | WARP mesh peers (100.96.x.x) |
| External (optional) | HTTPS | 9898 | Partners behind reverse proxy |
| Health check | HTTP | 9696 | `/health` endpoint |

## Reverse Proxy Setup

See `~/wiki-ops/runbooks/a2a-partner-onboarding.md` for nginx/Caddy configuration.

Key points:
- TLS termination at the proxy, not the A2A server
- Proxy `http://127.0.0.1:9696` (not `0.0.0.0` — loopback from proxy)
- Must proxy `.well-known/` paths for Agent Card discovery
- Rate limiting at proxy level (Phase 6 if needed internally)

## Firewall

```bash
sudo ufw allow 9696/tcp     # Mesh peers
sudo ufw allow 9898/tcp     # External partners (if used)
```

## DNS

Internal mesh peers resolve via mesh IP (100.96.x.x). External partners should use a DNS A record pointing to the VPS public IP, with the reverse proxy handling TLS and routing.

## References

- Reverse proxy setup: `~/wiki-ops/runbooks/a2a-partner-onboarding.md`
- Firewall rules: `~/wiki-ops/runbooks/server-backup-restore.md`
- Mesh enrollment: `~/wiki-ops/runbooks/cloudflare-mesh-enrollment.md`
