---
title: Phase 6 Research Methodology — Interrogation vs Speed-Reading
created: 2026-05-21
type: reference
tags: [a2a, phase-6, research, methodology, decision-trail]
---

# Phase 6 Research — Methodology and Decision Trail

## Context

Phase 6 hardening research was initiated with 7 items from the delivery plan. The first pass produced surface-level findings — accurate summaries but no depth. The user (Fleety) flagged that the research was "speed-reading" not "interrogation" — reading code without asking what breaks, what misconfiguration looks like, or what the failure modes are.

This document captures the corrected methodology and the decisions that resulted.

## The Correction

Fleety's framing:

> *"Research isn't reading alone. There's a big difference between speed reading and asking questions about how to implement on each point, ask what breaks this, what's a sensible way to apply this, what would misconfiguration look like? Only the second method brings readiness."*

Applied to code research: read the source, then for each finding, ask:
- What actually fails here? (not "can it fail?" — "what IS the failure mode?")
- What does misconfiguration look like? (not "could there be bugs?" — "what does a real operator error produce?")
- Is the proposed fix the right fix? (not "is there a fix?" — "does this actually solve the problem it claims to?")
- Is this problem worth solving NOW? (vs "is this technically correct?")

## What Changed Between Pass 1 and Pass 2

### Provenance Tracking (Item 2)

**Pass 1 finding:** "5 gaps found. Thread node_id into executor, propagate via mesh metadata, enrich audit events, add root_task_id."

**Interrogation that changed it:**
- Read `request_to_intent()` — hardcodes `source_node="local"`. Read plugin `register()` — `node_id` is read from config for FleetController but never passed to HermesExecutor. Gap confirmed.
- Read `MeshPeerClient.send_task()` — builds `SendMessageRequest` with only `message` field, no provenance. Gap confirmed.
- Then asked: **who actually consumes this provenance?** Answer: nobody. We have no external partners. The only consumer is the audit log. All 6 specialists are local. The chain is: peer → us → specialist (same process). There is no multi-hop routing. The `reference_task_ids` are carried by the A2A SDK's request context naturally.
- **Decision:** Gaps 1-3 and 5 are premature. Only Gap 4 (audit enrichment) has a consumer today — the operator reading the audit log.
- **Priority:** P5 in the second pass, P2 in the first pass. Demoted because the proposed work added complexity (new parameter to executor, metadata propagation in protocol messages) for zero immediate value.

### Graceful Peer-Offline (Item 3)

**Pass 1 finding:** "Exponential backoff with full jitter, per-peer circuit breaker, custom `_retry_async()` wrapper."

**Interrogation that changed it:**
- Read `MeshPeerClient.connect_peer()` — callers: `connect_all()` at startup, fire-and-forget. No retry. If peer is offline at startup, it stays undiscovered.
- Read `MeshPeerClient.send_task()` — callers: `HermesExecutor.execute()` on each A2A dispatch. No retry. On failure, returns `TaskResult(status="failed")`.
- Then asked: **what's the worst thing that happens without each fix?**
  - No reconnection: peer starts 30s after our gateway → never contacted until operator restarts gateway. Fix is high value.
  - No send_task retry: user re-sends their question. Fine.
  - No circuit breaker: peer flapping causes a ~30s timeout per task when peer is down. Annoying, not catastrophic.
- Then asked about send_task retry idempotency: `consultation` and `research` are idempotent (read-only). `action_request` is not (e.g., "deploy the change"). A blanket retry policy is wrong.
- **Decision:** Deferred peer reconnection (P1). Circuit breaker and send_task retry are P4 — not needed at 2-node mesh scale.

### Graceful Degradation (Item 6)

**Pass 1 finding (from Cody):** "dispatch_tool path already dead. Add startup probe and fast-fail guard."

**Interrogation that changed it:**
- Read `_run_via_agent()` — full try/except wrapper. If `run_agent` is missing, returns a clean `TaskResult(status="failed")` with error message.
- Then asked: **what does "failed" look like to the caller?** The peer gets a JSON-RPC response with error message. The A2A server continues serving Agent Cards. Other core functions work. This IS graceful degradation — the non-core function fails cleanly without crashing the plugin.
- The startup probe would catch the issue at plugin load vs first request. Nice-to-have, not critical.
- **Decision:** Startup probe is P2. The current behavior is already correct for our maturity level. The per-call AIAgent cost (3-15s per dispatch) is an accepted tradeoff for v1.0.

### Watchdog (Item 7)

**Pass 1 finding:** "Periodic health check every 60s — /health, peer count, task store writability."

**Interrogation that changed it:**
- Read the plugin's `register()` with `_start_server()` — uvicorn runs in a daemon thread. If the thread dies silently, the plugin registers "success" but never serves requests.
- Then asked: **is a built-in loop the right mechanism?** A cronjob can check /health externally. But a cronjob can't catch the audit logger vulnerability...
- **Wait — what audit logger vulnerability?** Read HermesExecutor.execute(): `audit_logger.log_event()` is called at lines 126-133, 144-151, 171-176, 189-198, 225-228, 234-238, 247-250, 256-260 — inside and outside try/except blocks. If the audit log file can't be written (disk full, permissions), the exception crashes `execute()`. The peer gets an HTTP 500.
- **Decision:** The audit logger crash vulnerability is P0 — single exception kills the entire A2A handler for that request. The actual watchdog loop is P4 — better served as a cronjob.

## Revised Priorities

| Priority | Item | Rationale |
|----------|------|-----------|
| P0 | Audit logger I/O guard | Unguarded `log_event()` → crash on disk full |
| P1 | Peer reconnection with backoff | Peer coming online after gateway is never discovered |
| P1 | Peer connectivity observability | No way to see peer state without log grepping |
| P2 | Rate limiting middleware | Needed before partners, not urgent for internal mesh |
| P2 | Startup probe for run_agent | Catches missing dep at load time vs first request |
| P3 | Audit event enrichment | source_node + endpoint in audit, nice for traceability |
| P3 | Config env var overrides | Mechanical, low risk, no urgent need |
| P4 | Circuit breaker | Over-engineering for 2-node mesh |
| P4 | send_task retry | Idempotency-per-intent-type analysis needed first |
| P4 | Health-check watchdog loop | Better as a cronjob |
| P5 | Provenance chain (node_id threading, metadata propagation) | Premature without external partners |

## What to Do Differently Next Time

1. **Before accepting any finding, read the code path.** Not the summary — the actual lines. Cody's report was thorough, but I should have verified each claim against the source before incorporating it.

2. **For each proposed fix, ask "who consumes this?"** Provenance tracking has a consumer (audit log), but the specific fields and their propagation depth matter. The consumer defines the output contract, not the theoretical completeness of the chain.

3. **Distinguish "technically correct" from "worth doing now."** The 5 provenance gaps are technically accurate. Only 1 of them has an immediate consumer. The other 4 are premature engineering.

4. **Watch for vulnerability patterns that look like feature work.** The audit logger I/O vulnerability looks like "need a watchdog" but is actually a cheap guard (try/except around log_event calls) that prevents a specific crash. The "big feature" mental model hid the cheap fix.

5. **When retroactively demoting items, preserve the reasoning.** This document exists so that if provenance gaps bite us later with partners, we know why they were deferred and can restart from the correct jump-off point — not from zero.

## The Jump-Off Points

If any of these items become urgent later, the research is already done:

- **Provenance chain (P5 → re-prioritize):** Read `MeshPeerClient.send_task()` at the point where `SendMessageRequest` is built. Add `source_node`, `source_profile` to `message.metadata` (protobuf Struct) and `intent.reference_task_ids` to the message's `reference_task_ids` field. On the receiving side, read `request_to_intent()` and thread the metadata through `TaskIntent.source_node`. Also need to pass `node_id` config through `HermesExecutor.__init__()`.

- **Circuit breaker (P4 → re-prioritize):** Add `_failure_counts`, `_circuit_open`, `_last_attempt` dicts to MeshPeerClient. On each connect/send failure, increment count and check threshold. On open, refuse attempts for 30s. Reset on success. Details in `~/src/a2a-core/.hermes/plans/2026-05-21-phase6-research.md`.

- **send_task retry (P4 → re-prioritize):** Read `intent.intent_type` before deciding to retry. `consultation` and `research` are safe. `action_request` is not. Default to no retry. Make retry configurable per-peer in config.
