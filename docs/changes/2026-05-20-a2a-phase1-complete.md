---
title: Phase 1 Complete — Plugin Bootstrap + Dispatch Fix
created: 2026-05-20
type: change
status: complete
tags: [a2a, phase1, dispatch, bootstrap]
---

# Phase 1: Plugin Bootstrap — Complete

## Summary

Phase 1 delivered a running A2A server on Tesla VPS, port 9696, serving a dynamic Agent Card with 6 profiles, accepting SendMessage requests, and dispatching them through a fresh AIAgent session.

## What Changed

### Plugin Installation
- Created symlink: `~/.hermes/plugins/a2a-server` → `~/src/a2a-core/src/a2a_plugin/`
- Added `a2a-server` to `plugins.enabled` in config.yaml
- Registered pip editable install: `pip install -e '.[all]'` in Hermes venv

### Profile Configs
Proteus had already added `a2a:` sections to all 6 Tesla profiles (alex, cody, odin, ops, ray, reviewer). These specify intents, tags, and descriptions for Agent Card generation.

### Dispatch Fix
Replaced the broken `ctx.dispatch_tool("delegate_task", ...)` closure with `_run_via_agent()` — a module-level function that creates a fresh AIAgent per request (same pattern as `cron/scheduler.py:1437`).

**Why:** `ctx.dispatch_tool` resolves parent_agent from the CLI context, which is None in the A2A daemon thread. The delegate_task tool guards against this with `if parent_agent is None: return error`.

**The fix:**
- Reads target profile's runtime config (model/provider/base_url)
- Falls back to main Hermes config defaults
- Creates AIAgent with profile identity, restricted toolsets, clean session
- Calls `agent.chat(goal)` and wraps result in `TaskResult`
- Catches all exceptions → clean `TaskResult(status="failed")`

**Files modified:** `src/a2a_plugin/__init__.py` (3 edits: imports, new functions, executor wiring)

### Verification
- 177 tests pass (3.04s)
- Plugin loads and registers
- Agent Card serves all 6 profiles
- SendMessage `"ping"` returns `"**pong** 🏓 Everything's alive and responsive."`

## Config Created

- `docs/runbooks/a2a-plugin-runbook.md` — operations reference
- `~/wiki-ops/planning/a2a-plugin-delivery-plan.md` — delivery plan with gates

## Known Gaps (Deferred to Phase 2+3)

- No auth (bearer tokens not implemented)
- Agent Card signing silently fails (try/except/pass in agent_card_route.py)
- No SSRF guard
- No version negotiation
- No outbound client (cross-node dispatch)
- No peer registry
