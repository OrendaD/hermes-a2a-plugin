---
title: Mesh Health Watchdog — Phase 6 Item 7
created: 2026-05-21
type: change
status: complete
phase: 6
tags: [a2a, hardening, watchdog, observability]
---

# Mesh Health Watchdog

## Problem

Production mesh needs health observability beyond process-level monitoring (systemd). Three gaps identified:
1. Uvicorn runs in a daemon thread — silent death means the gateway registers success but never accepts requests
2. Peer reconnection (Item 3a) runs in background — no visibility if retries keep failing
3. Disk can fill up, and while the audit logger crash (P0) is fixed, there's no proactive warning

## Fix

Created `scripts/mesh-watchdog.py` — a passive health observer. Runs as a stateless per-tick check, never auto-restarts.

**Checks, in order (stop on first failure):**
1. **/health endpoint** — `GET http://{bind}:{port}/health` via `urllib.request`. Expected: 200.
2. **Configured peers** — Parses `a2a.peers` from config YAML, extracts peer names.
3. **Disk space** — `os.statvfs` on `~/.hermes/`. Warning threshold: 100MB free.

**Config discovery:** `A2A_CONFIG` env var → `~/.config/hermes/config.yaml` → `~/.hermes/config.yaml` → defaults (127.0.0.1:9696).

**No A2A plugin imports** — confirmed clean. Stdlib only (`urllib.request`, `os`, `sys`, `json`).

## Files Created

- `scripts/mesh-watchdog.py` — standalone health check script (~120 lines)

## Verification

```bash
$ python3 scripts/mesh-watchdog.py
✅ A2A watchdog — all clear
  ✅  /health: 200 OK
  ✅  configured peers: 1 (proteus)
  ✅  disk (~/.hermes): 8GB free
```

Degraded scenarios (simulated): server down, empty config, peer configured — all produce appropriate warnings.

## References

- Research: `.hermes/plans/2026-05-21-phase6-research.md` (Item 7 — Watchdog for Plugin Health)
