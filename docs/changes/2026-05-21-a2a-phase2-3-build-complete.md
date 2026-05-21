---
title: A2A Plugin — Phase 2+3 Build Complete, Cross-Node Dispatch Gated
created: 2026-05-21
type: change
status: partial
phase: 2+3
tags: [a2a, phase, build, gate, ssrf, auth, peer, mesh, warp]
---

# A2A Phase 2+3 — Build Complete

## Build Items Verification

All five build items from the delivery plan are coded, tested, and passing:

| Item | Status | Notes |
|------|--------|-------|
| Auth foundation | ✅ Done | PeerRegistry + BearerTokenContextBuilder + 19 tests |
| Agent Card signing fix | ✅ Done | Removed silent `except Exception: pass`, added logging, configurable `signing_profile` |
| SSRF guard | ✅ Done | Custom httpx transport, `not addr.is_global` catch-all (covers RFC 6598 CGNAT), 42 tests |
| Version negotiation | ✅ Done | Starlette middleware, rejects non-1.0 with `VersionNotSupportedError (-32009)` |
| Mesh peer client | ✅ Done | `MeshPeerClient` with SSRF-guarded transport, Agent Card resolution, capability registration, bearer-token dispatch |
| Cross-node dispatch test | 🔴 Gated | Requires iMac WARP enrollment + bind address change |

**Test suite:** 254 passed, 2 skipped — all existing + new Phase 2+3 tests.

## Config Decisions Documented

### Peer Registry Format

Defined in `~/.hermes/config.yaml` under `a2a.peers`:

```yaml
a2a:
  port: 9696
  bind: "0.0.0.0"          # Changed from 127.0.0.1 for mesh access
  node_name: "tesla-vps"
  signing_profile: "ray"
  peers:
    - name: proteus
      url: http://<mesh-ip>:9696
      api_key: "${PROTEUS_A2A_KEY}"
      cidr_allow: ["100.96.0.0/16"]
```

Key decisions:
- **Peer URL uses mesh IP** (100.96.x.x), not public IP — traffic stays inside WARP tunnel
- **API key via env var** (`${PROTEUS_A2A_KEY}`), not plaintext in config — loaded at startup
- **SSRF allowlist per peer** — `cidr_allow` scopes which IP ranges this peer is allowed to resolve to
- **Port 9696 consistent** across all nodes per Phase 1 convention
- **`node_id: "local"`** — routing sentinel that distinguishes local profiles from remote peers

### SSRF Allowlist Convention

The `AsyncSSRFTransport` accepts a `allow_cidrs` list. The SSRF check is:

1. If destination IP is in any allowlist CIDR → allow
2. If `addr.is_global` → allow (public internet)
3. If `addr.is_multicast or addr.is_reserved` → block (defense-in-depth)
4. Otherwise → block (catches RFC 1918, RFC 6598 CGNAT, loopback, link-local, etc.)

For mesh, each peer's `cidr_allow` should include `100.96.0.0/16` (WARP CGNAT range).

## Gating Issue: Bind Address

The A2A server currently binds to `127.0.0.1:9696`, making it unreachable from the WARP mesh interface (`100.96.0.2`). For cross-node dispatch, the bind address must be `0.0.0.0`.

While the delivery plan lists configurable bind address under Phase 5 (Partner-Ready Surface), the cross-node dispatch gate in Phase 2+3 requires it operationally. Consolidating: Phase 2+3 uses `bind: "0.0.0.0"` with documentation that this is appropriate for the internal mesh (both nodes on same WARP team). Phase 5 will add TLS/proxy documentation for external partners.

## Current Mesh State

- **VPS (this node):** Enrolled. `CloudflareWARP` interface up at `100.96.0.2/32`
- **iMac (Proteus):** Not yet enrolled. Requires: service token provisioned + WARP client installed + mesh enrollment policy covers it
- **Peer config in place:** Points to `http://100.96.0.1:9696` (placeholder — needs the iMac's actual mesh IP)

## Next Action

1. Apply `bind: "0.0.0.0"` config change
2. Write `a2a-peer-setup.md` runbook
3. When iMac is enrolled → update peer URL with actual mesh IP → cross-node dispatch test

## References

- Delivery plan: `~/wiki-ops/planning/a2a-plugin-delivery-plan.md`
- Phase 2+3 research: `~/wiki-ops/planning/a2a-phase2-3-research.md`
- SSRF module: `~/src/a2a-core/src/adapter/ssrf.py`
- Mesh peer client: `~/src/a2a-core/src/adapter/mesh_peer_client.py`
- Runbook: `docs/runbooks/a2a-plugin-runbook.md`
