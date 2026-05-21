---
title: A2A Plugin — Phase 5 Partner-Ready Surface Complete
created: 2026-05-21
type: change
status: complete
phase: 5
tags: [a2a, phase, partner, audit, docs]
---

# Phase 5 — Partner-Ready Surface Complete

## Build Items

| Item | Status | Notes |
|------|--------|-------|
| Audit logger | ✅ Built | `src/adapter/audit_logger.py` — JSONL, rotation, 12 event types |
| Audit logger wiring | ✅ Done | HermesExecutor logs all state transitions. Plugin creates logger. |
| Audit logger tests | ✅ 31 new tests | Thread safety, rotation, integration |
| Intent schemas doc | ✅ Published | `docs/references/a2a-intent-schemas.md` |
| Partner onboarding runbook | ✅ Published | `~/wiki-ops/runbooks/a2a-partner-onboarding.md` |
| External surface reference | ✅ Published | `docs/references/a2a-external-surface.md` |

## Test Results

- **299 passed, 2 skipped** (up from 268 — 31 new audit logger tests)
- All existing A2A plugin tests preserved

## Documentation Published

- `docs/references/a2a-intent-schemas.md` — 5 intent types with payload schemas, examples, error codes
- `~/wiki-ops/runbooks/a2a-partner-onboarding.md` — 5-step onboarding from API key to round-trip test
- `docs/references/a2a-external-surface.md` — port config, reverse proxy, firewall, DNS

## Out of Scope (Phase 6)

- Rate limiting
- Streaming (SSE) — HermesExecutor.on_streaming_event()
- Per-partner key rotation tooling
- Circuit breakers for peer unavailability

## References

- Research doc: `.hermes/plans/2026-05-21-phase5-research.md`
- Intent schemas: `docs/references/a2a-intent-schemas.md`
- Partner onboarding: `~/wiki-ops/runbooks/a2a-partner-onboarding.md`
- External surface: `docs/references/a2a-external-surface.md`
- Audit logger: `~/src/a2a-core/src/adapter/audit_logger.py`
