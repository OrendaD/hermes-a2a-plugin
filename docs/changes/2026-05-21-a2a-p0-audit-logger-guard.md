---
title: Audit Logger I/O Guard — Phase 6 P0
created: 2026-05-21
type: change
status: complete
phase: 6
tags: [a2a, audit, hardening, p0]
---

# P0 — Audit Logger I/O Guard

## Problem

Every `audit_logger.log_event()` call in `HermesExecutor` was unguarded. If the audit log file couldn't be written — disk full, permission denied, missing parent directory — the exception propagated through `execute()` or `cancel()`, crashing the A2A handler. The peer would receive an HTTP 500 / JSON-RPC error instead of a clean task failure.

This was discovered during Phase 6 research interrogation. A health-check "watchdog" (the initial framing) would not have caught this — it's not a monitoring gap, it's a crash vulnerability.

## Fix

**What:** Added a `_safe_log()` helper method to `HermesExecutor` that wraps every `log_event()` call in a `try/except Exception`, logging the failure via `logger.exception()` but never propagating. All 12 call sites were migrated from the `if self._audit_logger: self._audit_logger.log_event(...)` pattern to `self._safe_log(...)`.

**Files modified:**
- `src/adapter/hermes_executor.py` — added `import logging`, `logger = logging.getLogger(__name__)`, `_safe_log()` method, replaced all 12 direct log_event calls

**Files created:**
- None — test added to existing audit logger test file

**Tests added:**
- `tests/adapter/test_audit_logger.py::TestSafeLog` — 3 new tests:
  - `test_broken_logger_does_not_crash_execute` — PermissionError on success path
  - `test_broken_logger_does_not_crash_cancel` — OSError on cancel path
  - `test_broken_logger_no_route` — PermissionError on no-route path

## Verification

- **302 passed, 2 skipped** (up from 299 — 3 new safe-log tests)
- All 3 crash scenarios: execute(), cancel(), no-route — each survives a broken logger without propagating
- The fix leaves only 3 `self._audit_logger` references in the file: constructor store, `_safe_log` null check, and `_safe_log` call itself

## Decision Trail

The research methodology that uncovered this vulnerability (interrogation vs speed-reading) is documented in:
`docs/references/a2a-phase6-research-decision-trail.md`

Key methodological finding: the "watchdog" frame was wrong. The actual vulnerability was a cheap try/except guard, not a health-check loop. The big-feature mental model hid the simple fix.

## References

- Decision trail: `docs/references/a2a-phase6-research-decision-trail.md`
- Phase 6 research: `~/src/a2a-core/.hermes/plans/2026-05-21-phase6-research.md`
- Module: `src/adapter/hermes_executor.py`
- Tests: `tests/adapter/test_audit_logger.py`
- Audit logger: `src/adapter/audit_logger.py`
