---
title: Peer Reconnection with Backoff — Phase 6 Item 3a
created: 2026-05-21
type: change
status: complete
phase: 6
tags: [a2a, hardening, peer, retry, reconnection]
---

# Peer Reconnection — Exponential Backoff

## Problem

When `MeshPeerClient.connect_all()` runs at startup, any peer that is temporarily offline returns `False` and is never retried. The peer remains "dead" until an operator restarts the gateway. If a peer boots 30 seconds after our gateway, it's undiscovered for minutes or hours.

## Fix

Added a background retry loop to `MeshPeerClient`. After `connect_all()` completes, any peer that failed gets an asyncio task that retries `connect_peer()` with exponential backoff + full jitter:

- Base interval: 1 second
- Doubles each attempt: 1, 2, 4, 8, 16, 32, 60, 60... (capped at 60s)
- Full jitter: `random.uniform(0, delay)` prevents thundering herd on mesh-wide recovery
- On success: log "reconnected X after N attempts", stop retrying
- On sustained failure: continue at 60s intervals
- On `close()`: cancel all retry tasks to prevent dangling coroutines

## Files Modified

- `src/adapter/mesh_peer_client.py` — added `_retry_tasks` dict, `_schedule_peer_retry()`, `_retry_peer_loop()`, modified `connect_all()` and `close()`

## Test File

- `tests/adapter/test_mesh_peer_client.py` — 6 new tests in `TestRetryLoop` class (17 total in file)

## Test Coverage

- Failed peer schedules retry task
- Successful peers don't schedule retries
- Retry loop reconnects on first success
- Retry loop continues on repeated failure (3 attempts verified)
- `close()` cancels all pending retry tasks
- Multiple failed peers each get independent retry loops

## Test Results

- **317 passed, 2 skipped** (up from 311 — 6 new retry tests)
- Zero regressions

## References

- Research: `.hermes/plans/2026-05-21-phase6-research.md` (Item 3 — Graceful Peer-Offline, lines 68-100)
