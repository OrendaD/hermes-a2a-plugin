---
title: A2A Plugin — Phase 0 Code Validation
created: 2026-05-20
type: change
status: complete
tags: [a2a, phase0, validation, code-review]
---

# Phase 0 — Code Validation Results

## Summary

**Decision:** Proteus's reference code is structurally sound. Proceed to Phase 1.

**Test results:** 177/177 passed, 4.95s on VPS (Ubuntu 22.04, 3GB RAM)

**Hexagonal boundary:** Verified. Zero A2A imports in `src/core/` source files. All 13 A2A imports are in `src/adapter/` (7) and `src/a2a_plugin/` (1) — exactly where they should be.

**Dependencies installed:**
- a2a-sdk 1.0.3 [http-server, signing, sqlite]
- a2a-core 0.1.0 (editable install from ~/src/a2a-core/)

## Code Quality Assessment

### FleetController (244 lines) — ✅ Sound
Routing priority: explicit profile → explicit node → best match across peers, preferring local. Capability matching via `can_handle()`. Availability tracking. `discover()` for cross-node queries.

Gaps (hardening, not structural):
- `_busy` set has no concurrency protection (both sync/async paths)
- `_best_match()` returns first match, not ranked
- No capacity scoring, no latency preference beyond local bias

### Orchestrator (257 lines) — ✅ Sound
Clean DI (FleetController + A2AAdapter injected). Proper input-required → specialist recruitment flow. Depth guard (MAX_SPECIALIST_DEPTH=3). Conversation graph tracking. Human escalation path.

Gap: Never instantiated in register(). A2AAdapter interface has no concrete implementation (HermesExecutor extends SDK's AgentExecutor, not the domain A2AAdapter).

### HermesExecutor (490 lines) — ✅ Sound
Clean SDK integration. RequestContext → TaskIntent translation with parts-based intent derivation. Protobuf struct value conversion. Status mapping. Clear execute() flow.

Gaps: cancel() emits SDK events but doesn't kill Hermes session. Message-only emission (non-standard but functional). No streaming. No guard for dispatch outside gateway.

### Agent Card Signer (217 lines) — ⚠️ Flawed
The try/except/pass pattern is verified. `agent_card_route.py` wraps signing in a try block, silently serves unsigned on failure. `agent_card_signer.py` itself is well-structured. Fix required before signing is usable.

## Other Architecture Checks

- **pyproject.toml:** Has proper dependencies declared (unlike handoff doc claimed)
- **Profile discovery:** Reads config.yaml `a2a:` sections correctly per M0.3 research
- **Plugin entry point:** `register(ctx)` properly importable
- **setup.sh:** exists for automation (contains full setup pipeline)
- **scripts/start-server.py:** standalone mode exists for development

## Gate Status

✅ All 177 tests pass
✅ Hexagonal boundary clean
✅ No critical structural issues found
✅ Known gaps documented

**Gate → Phase 1: PASS**
