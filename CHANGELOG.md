# a2a-core — Build Changelog

Chronological log of build steps for the A2A plugin project (a2a-core).

## 2026-05-20

### Phase 0 — Validation and foundation
- **What:** Validated A2A SDK integration paths, verified protobuf/capability domain models, confirmed Starlette app construction. AIAgent seeding and protocol-agnostic executor pattern validated.
- **Doc:** `docs/changes/2026-05-20-a2a-phase0-validation.md`

### Phase 1 — Bootstrap and core models
- **What:** Plugin structure scaffolded, `_read_a2a_config()` integrated, Starlette uvicorn server started in daemon thread. FleetController, Orchestrator, A2AAdapter interfaces defined. TaskIntent, TaskResult, ProfileDispatch, AgentCapability domain models created. HermesA2AAdapter, HermesExecutor stubs in place. SOUL.md-based display name extraction added.
- **Doc:** `docs/changes/2026-05-20-a2a-phase1-bootstrap.md`

### Phase 1 checkpoint
- **What:** 157 tests pass (all existing). 4 new tests for profile discovery with SOUL.md display names. Agent Card building via Discovery → Card builder confirmed end-to-end. Phase 2 scope clarified: authentication + Agent Card signing.
- **Doc:** `docs/changes/2026-05-20-a2a-phase1-checkpoint.md`

### Phase 1 — Complete
- **What:** HermesA2AAdapter request_to_intent(), input_required → on_status_change hook, orchestrator resume chain. All existing tests still pass. No new tests added (core interfaces already covered in phase 0).
- **Doc:** `docs/changes/2026-05-20-a2a-phase1-complete.md`

### Node ID fix
- **What:** `node_id` config threaded into FleetController via `_local_node_id`. Profiles now correctly identify which node they belong to. Fixes remote vs local routing for ProfileDispatch.
- **Doc:** `docs/changes/2026-05-20-a2a-node-id-fix.md`

### Signing and version middleware
- **What:** Agent Card signing with Ed25519 key. Version middleware validates A2A-Version header on every request. Config extended with `signing_key`, `min_version`.
- **Doc:** `docs/changes/2026-05-20-a2a-signing-and-version.md`

### Outbound client — MeshPeerClient
- **What:** `MeshPeerClient` built — connects to configured peers via SDK Client, resolves Agent Cards, registers remote capabilities in FleetController, dispatches tasks via `send_task()`. PeerRegistry and PeerConfig created.
- **Doc:** `docs/changes/2026-05-20-a2a-outbound-client.md`

## 2026-05-21

### Phase 2+3 — Auth, SSRF, version, mesh peer
- **What:** Auth foundation (BearerTokenContextBuilder validates tokens), Agent Card signing fix, SSRF guard (42 tests), version middleware, mesh peer client (275 lines).
- **New tests:** 42 — 254 total passing
- **Pending at gate:** Cross-node dispatch test — gated on iMac WARP enrollment + gateway restart
- **Doc:** `docs/changes/2026-05-21-a2a-phase2-3-build-complete.md`

### Routing architecture decision
- **Decision:** Peers route to main agent (not sub-agents). Unqualified `SendMessage` → receiving node's live AIAgent. Sub-agents are internal tooling, not external representatives.
- **Why:** Peers talk to peers. Sub-agents are hands, not representatives. Simplifies Phase 4 orchestration.

### Bind address changed for mesh access
- **What:** `a2a.bind` changed from `127.0.0.1` to `0.0.0.0` for mesh interface accessibility.

### Cross-node dispatch test — success
- **Result:** `SendMessage("Ping from Tesla VPS")` → protocol/mesh/auth/SSRF/version all work end-to-end.

### Phase 2+3 gate complete
- **What:** Tesla ↔ Proteus mesh round-trip verified over WARP tunnel. Cross-node SendMessage returns valid JSON-RPC response.
- **Gate:** ✅ MET — Phase 4 unblocked
- **Doc:** `docs/changes/2026-05-21-a2a-phase2-3-gate-completion.md`

### Phase 4 — Orchestration
- **What:** HermesExecutor emits SUBMITTED → WORKING → COMPLETED/INPUT_REQUIRED/FAILED. OrchestratorImpl wired in plugin. DatabaseTaskStore at `~/.hermes/a2a_tasks.db`. Gateway restart recovery built.
- **New tests:** 14 — 268 total passing (+14 from 254)
- **Files:** `src/adapter/hermes_adapter.py` (new), `src/adapter/hermes_executor.py` (modified), `src/a2a_plugin/__init__.py` (modified)
- **Doc:** `docs/changes/2026-05-21-a2a-phase4-orchestration-complete.md`

### Phase 5 — Partner-ready surface
- **What:** JSONL audit logger at `~/.hermes/a2a_audit.jsonl` (12 event types, 10MB rotation, 3 backups). Intent schemas published. Partner onboarding runbook written.
- **New tests:** 31 — 299 total passing (+31 from 268)
- **Files:** `src/adapter/audit_logger.py` (new), `src/adapter/hermes_executor.py` (modified), `src/a2a_plugin/__init__.py` (modified)
- **Docs:** `docs/references/a2a-intent-schemas.md`, `docs/runbooks/a2a-partner-onboarding.md`, `docs/references/a2a-external-surface.md`

### Phase 6, P0 — Audit logger I/O guard
- **What:** Added `_safe_log()` helper to HermesExecutor wrapping all 12 `log_event()` calls in try/except. Prevents disk-full/permission errors from crashing the A2A handler.
- **New tests:** 3 — 302 total passing (+3 from 299)
- **Files:** `src/adapter/hermes_executor.py` (modified), `tests/adapter/test_audit_logger.py` (modified)
- **Doc:** `docs/changes/2026-05-21-a2a-p0-audit-logger-guard.md`

### Phase 6, Item 1 — Rate limiting middleware
- **What:** Per-peer rate limiting middleware on the A2A server. HTTP 429 with Retry-After header. Tracks by SHA256 of bearer token. Configurable via `a2a.rate_limit` (default 30/min). `rate_limit: 0` = disabled. Middleware-level, protocol-agnostic — works for Hermes, OpenClaw, any HTTP client.
- **New tests:** 9 — 311 total passing (+9 from 302)
- **Files:** `src/adapter/rate_limit_middleware.py` (new), `src/a2a_plugin/__init__.py` (modified), `tests/adapter/test_rate_limit_middleware.py` (new)
- **Doc:** `docs/changes/2026-05-21-a2a-rate-limiting.md`

### Phase 6, Item 2 — Provenance tracking
- **What:** A2A protocol-compliant task source chain. Threaded `node_id` from config into HermesExecutor (no more hardcoded `"local"`). MeshPeerClient.send_task() now propagates `reference_task_ids`, `context_id`, `source_node`, `source_profile` via standard A2A protocol fields. Audit `task_in_progress` enriched with source identity.
- **Tests:** 311 passing — zero regressions
- **Files:** `src/adapter/hermes_executor.py` (modified), `src/adapter/mesh_peer_client.py` (modified), `src/a2a_plugin/__init__.py` (modified)
- **Doc:** `docs/changes/2026-05-21-a2a-provenance-tracking.md`

### Phase 6, Item 3a — Peer reconnection with exponential backoff
- **What:** Automatic retry for failed peer connections. When `connect_all()` fails on a peer, schedules a background asyncio task that retries `connect_peer()` with exponential backoff + full jitter (1s base, 60s cap). On success: peer becomes available automatically — no operator intervention needed. On `close()`: all retry tasks cancelled.
- **New tests:** 6 — 317 total passing (+6 from 311)
- **Files:** `src/adapter/mesh_peer_client.py` (modified), `tests/adapter/test_mesh_peer_client.py` (modified)
- **Doc:** `docs/changes/2026-05-21-a2a-peer-reconnection.md`

### Phase 6, Item 5 — Config overrides via env vars
- **What:** `A2A_<KEY>` environment variables override YAML config at runtime. Type coercion for int, bool, str, list. Unknown keys silently ignored. Enables containerisation and per-node differentiation from a single config file.
- **New tests:** 27 — 344 total passing (+27 from 317)
- **Files:** `src/a2a_plugin/__init__.py` (modified), `tests/plugin/test_plugin_config.py` (new)
- **Doc:** `docs/changes/2026-05-21-a2a-env-var-overrides.md`

### Phase 6, Item 7 — Mesh health watchdog
- **What:** Passive health observer for production mesh. Checks: /health endpoint, configured peers, disk space on ~/.hermes/. Stateless per-tick. Stdlib only. No auto-restart.
- **Files:** `scripts/mesh-watchdog.py` (new)
- **Doc:** `docs/changes/2026-05-21-a2a-mesh-watchdog.md`

### Phase 6, Item 6 — Graceful degradation
- **What:** Already satisfied — `send_task()` returns `TaskResult(status="failed")` with descriptive error on peer-offline and dispatch errors. No hangs, no crashes, no blocking. No code change needed.
