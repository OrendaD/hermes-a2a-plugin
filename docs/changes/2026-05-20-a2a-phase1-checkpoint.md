---
title: A2A Plugin — Phase 1 Checkpoint
created: 2026-05-20
|type: status
|status: checkpoint
tags: [a2a, phase1, checkpoint]
---

## Phase 1 State

**Plugin:** ✅ Loaded, enabled, serving on :9696
**Agent Card:** ✅ Serves 6 Tesla profiles with correct intents, tags, signatures
**Health:** ✅ Responds 200
**SendMessage endpoint:** ✅ Accepts requests, routes through FleetController
**Dispatch:** ❌ Fails — `'delegate_task requires a parent agent context.'`

## Root Cause

The A2A server runs in a daemon thread inside the gateway process. `ctx.dispatch_tool("delegate_task", ...)` resolves the parent agent from `cli._manager._cli_ref.agent`, which is None in the daemon thread (no active AIAgent session). The delegate_task tool then checks `if parent_agent is None: return error`.

## Fix Required

Switch from `ctx.dispatch_tool("delegate_task", ...)` to direct AIAgent construction — the same pattern used by the cron scheduler (`cron/scheduler.py:1437`). The dispatch function creates an AIAgent for each inbound A2A task, targeting the FC-routed profile.

This is the G13 gap from the handoff doc ("No graceful degradation outside gateway"). Fixing it is the bridge to Phase 2+3 — once AIAgent-based dispatch works, the same mechanism handles cross-node dispatch (the outbound client creates an AIAgent for the remote peer's task).

## Gate Status

The Phase 1 gate requires "local dispatch returns real results." The dispatch mechanism needs the G13 fix before this gate passes. Since this fix is tightly coupled to Phase 2+3 (secure peer mesh), recommend merging the remainder of Phase 1 into Phase 2+3 work.
