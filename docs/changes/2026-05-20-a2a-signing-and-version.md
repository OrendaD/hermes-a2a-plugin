---
title: Signing Fix + Version Negotiation — Phase 2+3
created: 2026-05-20
type: change
status: complete
tags: [a2a, phase2, phase3, signing, version]
---

# Signing Fix + Version Negotiation

## Signing Fix

**Problem:** `agent_card_route.py:88-95` caught every exception with `except Exception: pass` — served unsigned cards silently. Plus non-deterministic profile selection via `next(iterdir())`.

**Fix:**
- Silent catch replaced with specific logging per failure type
- Added configurable `signing_profile` key in `a2a:` config section
- Added `X-Agent-Card-Signed: true/false (reason)` response header
- Fixed `os.environ` pollution from key loading (snapshot/restore pattern in route handler)

**Files:** `src/adapter/agent_card_route.py` (modified)

## Version Negotiation

**Problem:** No A2A-Version header enforcement. SDK defaults missing headers to 0.3.

**Fix:** Added `A2AVersionMiddleware` — Starlette middleware that rejects requests without `A2A-Version: 1.0` header. Returns JSON-RPC error -32009 (VersionNotSupportedError).

**Files:** `src/adapter/version_middleware.py` (created), `src/a2a_plugin/__init__.py` (mounted on app)

## Test Coverage

- 7 version middleware tests
- All existing 93 adapter tests still pass
- Signing route tests updated for new header

## Next

- SSRF guard (httpx custom transport with `not is_global` pattern)
- Outbound client + peer wiring
- Cross-node test with Proteus
