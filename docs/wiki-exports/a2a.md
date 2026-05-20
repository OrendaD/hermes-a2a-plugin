---
title: A2A Protocol — Investigation & Setup Plan
created: 2026-05-13
status: superseded
type: planning
updated: 2026-05-17
tags: [a2a, agent-communication, mesh, protocol]
---

# A2A (Agent-to-Agent) Protocol

## Status
**Superseded — legacy plugin removed 2026-05-17.** The A2A plugin (`iamagenius00/hermes-a2a-preview`, v0.2.0) has been purged from the filesystem. A clean rebuild targeting A2A Protocol v1.0 with the official `a2a-sdk` is in progress. See [[planning/a2a-plugin-v1|details]] for the current project record.

## What It Is
Google's A2A protocol — peer-to-peer agent coordination. Hermes plugin at `iamagenius00/hermes-a2a-preview` implements it as a drop-in plugin (zero deps, stdlib only).

## System State (May 13)

| Check | Result |
|---|---|
| Plugin installed | ❌ Not in `~/.hermes/plugins/a2a/` |
| Hermes version | `38441a7d7` (May 12) — ≥ v2026.4.23 requirement ✅ |
| A2A config in config.yaml | ❌ None |
| A2A env vars in .env | ❌ None |
| Webhook routes in config.yaml | ❌ None |
| Mesh status | utun4 with `100.96.0.1` — likely Mesh IP |

## Upstream Landscape

| PR | Status | Description |
|---|---|---|
| [#11025](https://github.com/NousResearch/hermes-agent/pull/11025) | **Open** | iamagenius00's native A2A integration. No reviews, no assignee. Labels: P3, comp/gateway, comp/tools. Last push Apr 19 |
| [#4135](https://github.com/NousResearch/hermes-agent/pull/4135) | **Open** | Full a2a-sdk implementation (5 tasks) |
| [#14559](https://github.com/NousResearch/hermes-agent/pull/14559) | **Open** | Bindu — DID identity + OAuth2 + micropayments A2A adapter |
| [#23871](https://github.com/NousResearch/hermes-agent/pull/23871) | **Open** | Agent Card generation for A2A discovery (May 11) |

PR #11025 references the same standalone plugin repo. Native integration is not merged — plugin is the path forward for now.

<!-- SEPARATOR -->
## Plugin Overview (from README)

**`iamagenius00/hermes-a2a-preview`** — M2 developer preview, 8 commits, 2 contributors.

### Architecture
- `plugin/` — 14 modules, zero external deps (stdlib `http.server` + `urllib.request`)
- Module: `__init__.py`, `cli.py`, `friends.py`, `permission.py`, `server.py`, `tools.py`, `security.py`, `ssrf.py`, `provenance.py`, `source_providers.py`, `persistence.py`, `strangers.py`, `schemas.py`, `paths.py`
- Inbound A2A JSON-RPC at port 8081
- Instant wake via HMAC-signed webhook into current Hermes session
- Conversations persist independently (`~/.hermes/a2a_conversations/`) — compaction-safe

### Key Features
- `a2a_discover`, `a2a_call`, `a2a_list` tools
- `/a2a` and `/a2a friends` slash commands
- Per-friend bearer tokens (not one global secret)
- SSRF guard with DNS pinning, 9 prompt injection filters
- Provenance/taint protection — blocks private context leaking outbound
- Stranger capture (sanitized, no raw bodies)
- Audit log (`~/.hermes/a2a_audit.jsonl`)

### Security Model
| Layer | Detail |
|---|---|
| Auth | Per-friend Bearer tokens, `hmac.compare_digest()` |
| Friend lifecycle | pending → active → paused → blocked → expired → removed |
| Rate limit | 20 req/min/IP, thread-safe |
| SSRF/DNS pin | Canonicalize, resolve once, block private/test nets, pinned IP |
| Outbound redaction | API keys, tokens, emails stripped from responses |
| Provenance | Private/unknown-private taint denies auto outbound responses |
| Injection filtering | 9 patterns (ChatML, role prefixes, override variants) |

### Mesh Alignment
- A2A server should bind to Mesh interface so only mesh peers can reach it
- This replaces tunnel URLs, fake-IP workarounds, `--allow-origin` hacks
- Tesla (VPS) has Mesh IP — Proteus may have Mesh IP via utun4 (`100.96.0.1`)

## Setup Plan

### Phase 1: System Check ✅
- [x] Verify Hermes version ≥ v2026.4.23
- [x] Check plugin not already installed
- [x] Check upstream PR #11025 status
- [x] No existing A2A config or env vars

### Phase 2: Install & Loopback Test
- [ ] Clone repo to known location
- [ ] Run `./install.sh` (backup config.yaml + .env first)
- [ ] Verify `curl http://127.0.0.1:8081/health`
- [ ] Test from chat: `/a2a`, `/a2a friends add test_friend`
- [ ] Verify `a2a_discover`, `a2a_call`, `a2a_list` tools present

### Phase 3: Mesh Bind
- [ ] Determine correct Mesh interface IP for Proteus
- [ ] Set `A2A_PORT` and bind to mesh IP (not 127.0.0.1)
- [ ] Verify reachability from Tesla

### Phase 4: Tesla Friend
- [ ] Generate inbound token for Tesla
- [ ] Share out-of-band
- [ ] Add Tesla as friend: `a2a friends add tesla <url>`
- [ ] Test `a2a_discover tesla`
- [ ] Test `a2a_call tesla "notification"`

### Phase 5: Evaluation
- [ ] Compare with GitHub message bus — does A2A replace it entirely?
- [ ] Structured intents: notification vs consultation vs action_request
- [ ] Fallback if mesh is down — store-and-forward needed?

## Open Questions
1. stdlib `ThreadingHTTPServer` — concurrent request handling sufficient for production?
2. Migration path if PR #11025 or #4135 merges upstream
3. Can Tesla run the same plugin, or needs a different A2A endpoint?
4. Provenance system — how does it determine "private" vs shareable?

## Related Pages
- [[planning/ideation]] — Original A2A section (status: investigate)
- [[planning/deployment-doctrine]] — A2A as agent-to-agent coordination layer
- [[Inkbox/cloudflare-mesh]] — Mesh network infrastructure
