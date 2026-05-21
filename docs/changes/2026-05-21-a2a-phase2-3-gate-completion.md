---
title: A2A Plugin — Phase 2+3 Gate Completion
created: 2026-05-21
type: change
status: complete
phase: 2+3
gate: phase-4
tags: [a2a, phase, gate, mesh, routing, architecture]
---

# Phase 2+3 — Gate Completion

## Gate Condition

> *Tesla ↔ Proteus round-trip with full auth, signing, and SSRF verified. All tests pass. Peer registry documented.*

**Status: MET** ✅

## Verification Results

| Check | Result | Evidence |
|-------|--------|----------|
| Local dispatch | ✅ | `SendMessage` → response: "UTC time: 2026-05-21T04:37:09Z — Name: Tesla" |
| Cross-node mesh reachability | ✅ | Agent Card served from `100.96.0.1:9696` with 6 skills |
| Cross-node dispatch (Tesla → Proteus) | ✅ | JSON-RPC `SendMessage` → valid response over WARP tunnel |
| A2A-Version: 1.0 enforcement | ✅ | Non-1.0 requests return `-32009 VersionNotSupportedError` |
| SSRF guard | ✅ | 42 tests pass: blocks RFC 1918, CGNAT, loopback; allows public IPs and mesh CIDRs |
| Agent Card signing | ✅ | Card served with signature — silent-fail removed, signing profile configurable |
| Auth foundation | ✅ | PeerRegistry + BearerTokenContextBuilder — 19 tests |
| Mesh peer client | ✅ | 275 lines — SSRF-guarded transport, Agent Card resolution, capability registration |
| Test suite | ✅ | 254 passed, 2 skipped |

## Routing Architecture Decision

### Problem

The initial design assumed incoming peer messages should route to a sub-agent tagged with the `consultation` intent (e.g., sherlock on Proteus's side). This conflates the peer's interface with internal specialist routing.

### Decision

**Main agents are the front door.** When a peer sends an unqualified `SendMessage`, it routes to the receiving node's main agent (the live AIAgent running the gateway). The main agent processes the message directly and recruits specialists internally if needed.

Rationale:
- Peers talk to peers — Tesla talks to Proteus, not to sherlock
- Sub-agents are internal tooling, not external representatives
- The main agent has full context of its node's capabilities and can make delegation decisions
- Simplifies Phase 4 orchestration: the orchestrator is a main-agent concern, not a routing table issue

### Implementation Note

The FleetController on each node needs a default route: unmatched intent → main agent. On the Tesla VPS, this is the gateway's live AIAgent session. On Proteus's iMac, same pattern.

This is a routing config change (FleetController fallback rule), not a code change. Will be wired during Phase 4 orchestration.

## Documents Created This Phase

- `~/wiki-ops/planning/a2a-phase2-3-research.md` — security research (auth, SSRF, signing, version)
- `docs/runbooks/a2a-peer-setup.md` — how to add a mesh peer
- `docs/runbooks/a2a-plugin-runbook.md` — plugin operations (Phase 1)
- `docs/changes/2026-05-21-a2a-phase2-3-build-complete.md` — build verification + config decisions
- `~/hermes/skills/ops/cloudflare-mesh-enrollment/SKILL.md` — WARP mesh enrollment (Tier 1)

## Gate → Phase 4

Phase 4 builds on this foundation:
- Wire FleetController default routing (main agent as front door)
- Route status change events from HermesExecutor to OrchestratorImpl
- Implement `input-required` → specialist recruitment across peers
- SQLite task persistence for gateway restart recovery

Per plan: Phase 4 requires round-trip verified and documentation complete. Both conditions met.

## References

- Delivery plan: `~/wiki-ops/planning/a2a-plugin-delivery-plan.md`
- Phase 2+3 research: `~/wiki-ops/planning/a2a-phase2-3-research.md`
- Peer setup: `docs/runbooks/a2a-peer-setup.md`
- Phase 2+3 build verification: `docs/changes/2026-05-21-a2a-phase2-3-build-complete.md`
- Cross-node test: Session 2026-05-21, Tesla VPS → Proteus iMac over WARP mesh (100.96.x.x)
