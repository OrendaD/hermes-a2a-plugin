---
title: Rate Limiting Middleware — Phase 6 Item 1
created: 2026-05-21
type: change
status: complete
phase: 6
tags: [a2a, hardening, rate-limiting, middleware]
---

# Rate Limiting — Per-Peer Middleware

## Problem

The A2A server had no protection against a misconfigured or flooding peer consuming all server resources. As the mesh grows to include multiple nodes (partners, other agent implementations), a single aggressive peer could degrade service for all others.

## Design

**Protocol-agnostic boundary:** Middleware-level (not handler-level) so it operates before any A2A protocol parsing. Returns HTTP 429 with `Retry-After: 60` header — standard HTTP semantics understood by every client regardless of protocol implementation (Hermes SDK, OpenClaw, raw curl).

**Per-peer tracking:** By SHA256 hash of the `Authorization` header. Middleware runs before BearerTokenContextBuilder resolves token to peer name, so the raw auth header is the best available identifier.

**Fixed 1-minute window:** Sliding window of timestamps, pruned on each request. In-memory (restart resets limits — acceptable for v1).

**Configuration:** `a2a.rate_limit: 30` in config.yaml. `0` or missing = disabled.

## Files

**Created:**
- `src/adapter/rate_limit_middleware.py` — 78 lines, stdlib only (threading, hashlib, time)

**Modified:**
- `src/a2a_plugin/__init__.py` — middleware wired in `_build_app()` alongside `A2AVersionMiddleware`

**Test file:**
- `tests/adapter/test_rate_limit_middleware.py` — 9 tests

## Test Coverage

All 9 pass:
- Under limit (29/30) → passes
- Over limit (31st) → HTTP 429
- Different tokens → separate buckets
- `rate_limit=0` and `-1` → disabled
- `/health` not rate-limited
- Missing auth → tracked as "anonymous" bucket
- Window resets after 60s
- Exact boundary (N passes, N+1 blocked)

## Test Results

- **311 passed, 2 skipped** (up from 302 — 9 new rate limiting tests)
- Zero regressions

## References

- Existing middleware pattern: `src/adapter/version_middleware.py`
- Research: `.hermes/plans/2026-05-21-phase6-research.md` (Item 1 — Rate Limiting)
