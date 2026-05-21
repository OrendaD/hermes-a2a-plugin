---
title: Provenance Tracking — Phase 6 Item 2
created: 2026-05-21
type: change
status: complete
phase: 6
tags: [a2a, hardening, provenance, tracing]
---

# Provenance Tracking — Task Source Chain

## Problem

A2A defines `reference_task_ids` and `message.metadata` for carrying provenance across hops. Tesla ignored both on outbound messages:
- `request_to_intent()` hardcoded `source_node="local"` regardless of which peer sent the request
- `MeshPeerClient.send_task()` built messages with only question text — no `reference_task_ids`, no metadata
- Audit `task_in_progress` events didn't log who sent the work

This meant a 3-node chain (Proteus → Tesla → partner) produced orphaned requests — the partner couldn't trace work back to the origin.

## Fix

Three changes, all using standard A2A protocol fields:

**Change 1 — Thread `node_id` into HermesExecutor**
- Added `node_id` and `node_profile` parameters to `HermesExecutor.__init__()`
- `request_to_intent()` now uses the configured node identity instead of hardcoded `"local"`
- Plugin passes `node_id` from config at construction time

**Change 2 — Propagate provenance in MeshPeerClient.send_task()**
- Populates `message.reference_task_ids` from the intent's chain
- Populates `message.context_id` from the intent
- Builds a `Struct` metadata with `source_node` and `source_profile` (only if non-default values)
- All standard A2A protobuf fields — any A2A-compliant implementation (Hermes, OpenClaw, etc.) receives the full ancestry

**Change 3 — Enrich audit events**
- `task_in_progress` audit log now includes `source_node` and `source_profile` from the intent

## Files Modified

- `src/adapter/hermes_executor.py` — node_id threading, request_to_intent defaults, audit enrichment
- `src/adapter/mesh_peer_client.py` — provenance propagation in SendMessageRequest
- `src/a2a_plugin/__init__.py` — pass node_id to HermesExecutor constructor

## Verification

- **311 passed, 2 skipped** — zero regressions
- Provenance flows through standard A2A protocol fields — no custom headers, no non-standard extensions

## References

- A2A spec: `reference_task_ids` and `message.metadata` fields in SendMessageRequest
- Research: `.hermes/plans/2026-05-21-phase6-research.md` (Item 2 — Provenance Tracking)
