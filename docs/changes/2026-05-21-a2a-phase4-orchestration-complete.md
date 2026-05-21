---
title: A2A Plugin — Phase 4 Orchestration Complete
created: 2026-05-21
type: change
status: complete
phase: 4
tags: [a2a, phase, orchestration, build]
---

# Phase 4 — Orchestration Complete

## Build Items

| Item | Status | Files |
|------|--------|-------|
| HermesA2AAdapter | ✅ Created | `src/adapter/hermes_adapter.py` + tests |
| HermesExecutor status transitions | ✅ Modified | `src/adapter/hermes_executor.py` — emits SUBMITTED → WORKING → COMPLETED/INPUT_REQUIRED/FAILED |
| input_required → orchestrator hook | ✅ Wired | Executor calls OrchestratorImpl.on_status_change() for non-terminal states |
| OrchestratorImpl wiring in plugin | ✅ Done | `src/a2a_plugin/__init__.py` — creates OrchestratorImpl with FleetController + HermesA2AAdapter |
| DatabaseTaskStore | ✅ Switched | SQLite at `~/.hermes/a2a_tasks.db`, schema auto-created by SDK |
| Gateway restart recovery | ✅ Built | `_recover_tasks()` reconstructs conversation graphs from SQLite, flags mid-flight tasks for review |

## Test Results

- **268 passed, 2 skipped** (up from 254 — 14 new tests)
- All existing tests preserved
- New tests cover: status transitions, input_required routing, orchestrator hook, adapter dispatch

## Architecture

```
SendMessage → Dispatcher → HermesExecutor
    │                            │
    │                     emit_status(SUBMITTED)
    │                     emit_status(WORKING)
    │                            │
    │                     dispatch_fn() → TaskResult
    │                            │
    │                  ┌── completed ── emit_message + emit_status(COMPLETED)
    │                  ├── failed ───── emit_message + emit_status(FAILED)
    │                  └── input_required ── emit_status(INPUT_REQUIRED)
    │                                         ↓
    │                                  OrchestratorImpl
    │                                         ↓
    │                                  recruit_specialist() via A2AAdapter
    │                                         ↓
    │                                  compose answer + resume parent
```

## Decision Log

- **Message-only → long-running task pattern:** Phase 4 switches from emitting a single Message to emitting TaskStatusUpdateEvent transitions. The SDK's DefaultRequestHandlerV2 handles both patterns, so existing local dispatch still works.
- **Orchestrator is synchronous:** `on_status_change()` runs synchronously within the executor's `execute()` coroutine. Specialist recruitment blocks the original task until the specialist returns. Streaming (Phase 5) will unblock this.
- **DatabaseTaskStore auto-schema:** The SDK creates SQLite tables on first store operation. No migration needed.

## Gate → Phase 5

Per delivery plan, Phase 5 (Partner-Ready Surface) requires:
- End-to-end orchestration flow tested
- Task persistence verified across gateway restart
- Orchestration runbook written

Next: Phase 5 — streaming, partner docs, audit log.

## References

- Implementation plan: `.hermes/plans/2026-05-21-phase4-orchestration.md`
- Delivery plan: `~/wiki-ops/planning/a2a-plugin-delivery-plan.md`
- Phase 4 gate doc: `docs/changes/2026-05-21-a2a-phase2-3-gate-completion.md`
