# A2A Plugin — Complete Project Handoff to Tesla

**Handoff date:** 2026-05-20
**From:** Proteus | **To:** Tesla
**Priority:** Critical — work to standard required before any forward progress

---

## 1. Project at a Glance

| Item | Value |
|------|-------|
| Workspace | `/Users/fleety/webgui-files/a2a-plugin/` |
| Test count | **177 tests, all passing** (71 core, 106 adapter) |
| Run time | 1.3s total |
| SDK | `a2a-sdk==1.0.3` (Google-maintained, Linux Foundation) |
| Package | `a2a-core==0.1.0` (entry point: `a2a-server`) |
| Installed in | Hermes venv at `~/.hermes/hermes-agent/venv/` |
| Active server | **Standalone** on port **9696** (PID 2265, started 4:01PM) |
| Plugin auto-load | **NOT active** — gateway not restarted since entry point fix |
| Profiles w/ A2A | **6 profiles** (sherlock, builder, doris, cua-lord, wiki-checker, wiki-gardener) |

### Architecture (3-Layer Hexagonal)

```
A2A SDK (Google v1.0.3)    — protocol framing, JSON-RPC, AgentCard types
  ^ adapter (src/adapter/)  — HermesExecutor, ProfileDiscovery, CardBuilder, CardSigner
  ^ core (src/core/)        — domain models, FleetController, Orchestrator (zero A2A imports)
```

**Boundary rule:** `src/core/` has **zero** `from a2a import` lines. Verified.

---

## 2. Current State (Truth)

### What Actually Works

1. **Domain models** (TaskIntent, TaskResult, AgentCapability, ProfileDispatch, TaskRecord, ConversationGraph) — pure dataclasses with validation
2. **FleetController** — 244-line stateless routing engine: explicit profile routing, node-aware fallback, availability tracking, intent-based capability matching
3. **Orchestrator** — 257-line stateful flow manager: conversation graph tracking, status transitions, specialist recruitment, depth guard
4. **Profile discovery** — scans `~/.hermes/profiles/*/config.yaml` for `a2a:` sections
5. **Agent Card builder** — translates capabilities to AgentCard protobuf
6. **Agent Card HTTP route** — serves dynamic signed card at `/.well-known/agent-card.json`
7. **HermesExecutor** — implements AgentExecutor with intent derivation, FC routing, `dispatch_tool("delegate_task")`, event emission
8. **Wiring tests** — 106 adapter tests proving handler-to-executor-to-FC pipeline (mock dispatch)
9. **Standalone server** — `scripts/start-server.py` on port 9696 with Agent Card + JSON-RPC endpoint

### What Does NOT Actually Work

- **Real dispatch** — NOT live. Running server returns placeholder text. Real dispatch only activates when plugin auto-loads inside gateway process.
- **Plugin auto-load** — NOT active. Gateway predates entry point fix.
- **Cross-node A2A** — NOT tested. No outbound client, no mesh peers.
- **Auth / SSRF / Version Negotiation** — NOT implemented. Zero.
- **SQLite persistence** — NOT implemented. All tasks lost on restart.
- **Agent Card signatures** — NOT validated. Signing silently fails, serves unsigned cards.
- **Streaming / Push** — NOT implemented.

---

## 3. Comprehensive Problems List

### G1–G14: Architectural Gaps

**G1: No Outbound A2A Client — Mesh is One-Way**

Fleet Controller can route to remote nodes but nothing resolves that to an HTTP call. No A2A client, no Agent Card fetcher, no mesh peer registry, no heartbeat for peer availability.

What exists: `a2a.client.client.Client` in SDK (not wired). What's needed: MeshPeerRegistry that fetches remote Agent Cards, caches protobufs, registers in FC. Requires bearer token auth first (G5).

**G2: Dispatch Is Mock on Running Server**

`scripts/start-server.py` returns placeholder: `[profile] Dispatched: {goal}`. The real dispatch closure with `ctx.dispatch_tool("delegate_task")` is in `src/a2a_plugin/__init__.py` but unreachable because:
- Gateway hasn't been restarted (plugin won't auto-load)
- Port 9696 is taken by standalone server
- Gateway restart before killing standalone = port conflict

**G3: InMemoryTaskStore — No Persistence**

All tasks die on gateway restart. D-005 said "SQLite deferred to Phase 3b" — Phase 3b never created. Need: DatabaseTaskStore with SQLAlchemy + aiosqlite.

**G4: No Agent Card Signature Validation**

ADR-001 specifies ES256 with per-profile .env keys. But `create_agent_card_route()` wraps signing in try/except/pass — silently serves unsigned cards. No verification on receiving end either.

**G5: Zero Auth**

No bearer tokens, no A2A-Version header validation, no rate limiting, no request validation. Port 9696 is 127.0.0.1-only by luck, not enforcement.

**G6: No SSRF Guard**

Legacy v0.2.0 had full `ssrf.py` with DNS pinning, private-network blocking, per-agent allow rules. v1.0 has nothing.

**G7: No `cancel()` Implementation**

`HermesExecutor.cancel()` raises `NotImplementedError`. CancelTask RPC returns 500.

**G8: No Streaming (SSE)**

All profiles declare `streaming: false`. No incremental updates for long-running tasks.

**G9: No Push Notification Webhooks**

`supports_push: false` on all profiles. Webhook registration path absent.

**G10: No Task-to-Kanban Mapping**

A2A tasks invisible to `hermes-ops` board.

**G11: Orchestrator Is Built but Unreachable**

257-line `OrchestratorImpl` is never instantiated. `register()` creates FleetControllerImpl and HermesExecutor but not OrchestratorImpl. Multi-turn tasks, input-required flow, and specialist recruitment don't work.

**G12: pyproject.toml Has Zero Dependencies**

Missing: `a2a-sdk[http-server,signing,sqlite]`, `uvicorn`, `cryptography`. Works by accidental venv state.

**G13: No Graceful Degradation Outside Gateway**

Dispatch closure calls `ctx.dispatch_tool` without guard. Would fail with `AttributeError` if `register()` ever called outside gateway.

**G14: Config Is Hardcoded, Not Overridable**

No env var overrides (A2A_PORT, A2A_HOST documented in legacy plugin but not implemented in v1.0). No profile-level overrides. No CLI passthrough.

---

### C1–C6: Contract Violations

These violate the founding documents (a2a-domain-contracts.md, a2a-plugin-architecture.md, a2a-orchestration-patterns.md, a2a-core-scope-tesla.md).

**C1: Orchestrator Bypassed** — Contract says Orchestrator manages mid-flight tasks. Reality: never instantiated. See G11.

**C2: A2AAdapter Interface Not Implemented** — Contract says A2AAdapter (`src/core/domain/interfaces/adapter.py`) is the plugin's contract to the Core layer. Interface exists (82 lines, 4 abstract methods). No concrete implementation exists. HermesExecutor extends SDK's AgentExecutor, not the domain A2AAdapter.

**C3: No SSRF** — Architecture doc has full SSRF section. Zero lines of code.

**C4: No Version Negotiation** — No A2A-Version response header. No v0.3 fallback.

**C5: No Profile Workspace Isolation** — Contract says each profile is independent workspace. Sub-agent isolation depends entirely on Hermes's profile mechanism, never tested.

**C6: No Conversation Graph Persistence** — Contract says tasks survive restarts. InMemoryTaskStore.

---

### S1–S6: Security & Auth

| ID | Issue | Severity |
|----|-------|----------|
| S1 | No authentication on any endpoint | CRITICAL |
| S2 | No SSRF guard on outbound calls | CRITICAL |
| S3 | Agent Card signatures silently skipped | HIGH |
| S4 | Rate limiting absent | MEDIUM |
| S5 | No audit log | MEDIUM |
| S6 | No provenance/taint tracking | MEDIUM |

Legacy v0.2.0 had all of these. D-001 said clean rebuild but the patterns were supposed to be ported. They weren't.

---

### I1–I6: Implementation Flaws

**I1: AgentCard Route Signing Is Flawed** — Grabs alphabetically first profile dir for signing, not the one with keys. Each card request generates new key if selected profile has none.

**I2: FleetController Busy-Tracker Has No Concurrency Protection** — `set[str]` modified without locks from both sync and async paths.

**I3: `_best_match()` Returns First Match, Not Best** — No ranking, no capacity score, no latency preference beyond "prefer local."

**I4: ConversationGraph Tree Output Truncates Data** — `get_tree()` omits result, payload, messages, artifacts, source/target node, timing.

**I5: `register()` Creates Server But Never Shuts It Down** — No `on_shutdown` handler. Daemon threads killed mid-request on exit.

**I6: cua-lord/start-a2a.py References Deleted Legacy Plugin** — Line 21: `from a2a import register` — will ImportError.

---

### T1–T6: Test Gaps

| ID | Gap |
|----|-----|
| T1 | No cancel() tests (method is NotImplementedError) |
| T2 | No auth tests (nothing to test) |
| T3 | No SSRF tests (nothing to test) |
| T4 | No persistence tests (test_persistence.py doesn't exist) |
| T5 | No integration test for register() (all tests use HermesExecutor directly) |
| T6 | No cross-node test (requires two nodes) |

---

### D1–D3: Deployment & Operations

**D1: Watchdog Cron Applies to Standalone Only** — `a2a-server-health` (every 2min) restarts standalone server. After gateway restart, watchdog re-spawns standalone on same port = port conflict.

**D2: Standalone Server Must Die Before Gateway Restart** — Correct sequence: kill standalone, remove watchdog, restart gateway, verify plugin loaded.

**D3: Tesla Has No A2A Profile Configs** — Cross-node routing requires `a2a:` sections on Tesla's profile configs.

---

### W1–W5: Wiki & Documentation

**W1: `planning/a2a-plugin-v1.md` Says Phase 3 Complete** — It isn't. Missing: auth, version negotiation, SSRF, signing (broken), persistence, streaming, push, orchestrator integration, A2AAdapter implementation.

**W2: `planning/a2a-plugin-v1-m3.md` Has Stale Confidence** — Checkmarks on M3.1-M3.4 but cross-node test shows not started, SQLite shows deferred to phantom Phase 3b.

**W3: `subsystem/a2a.md` Deprecated But Documents Unported Patterns** — SSRF guard, friend lifecycle, audit log, provenance, injection filter, rate limiting all existed in legacy plugin. No migration plan.

**W4: No Restart Runbook** — No automation script, no restart checklist with rollback steps.

**W5: Skill Reference Docs Overclaim Phase Completion** — `hermes-a2a-protocol.md` says "Phase 3 is complete (May 20, 2026). 177 tests. Three live endpoints..." — misleading.

---

## 4. Running Processes & Cron Jobs

### Active Processes

| PID | Process | Started | Port | Purpose |
|-----|---------|---------|------|---------|
| 2265 | python scripts/start-server.py --port 9696 | 4:01PM | 9696 | Standalone A2A server (mock dispatch) |
| 2252 | bash wrapper (parent of 2265) | 4:01PM | - | Shell parent |
| 29390 | Python stub executor on port 18081 | Tue 1PM | 18081 | Test process (not real plugin) |

### Active Cron Jobs

| Job ID | Name | Schedule | Script | Notes |
|--------|------|----------|--------|-------|
| e5f2c46ee733 | a2a-server-health | every 2m | a2a-server-watchdog.sh | Must remove before gateway restart |
| ad5f1829f9da | Friday SOUL+AGENTS audit | 0 9 * * 5 | - | Unrelated |
| 37ed546a10ea | Daily LCM diagnostic | 0 20 * * * | - | Unrelated |
| 7d034a1347b8 | Wiki Health Checker | 0 */6 * * * | wiki-health-cron-wrapper.sh | Unrelated |

### Config Files

| File | Path |
|------|------|
| Main config (no a2a: section yet) | ~/.hermes/config.yaml |
| Pre-install config backup | ~/.hermes/config.yaml.a2a-preinstall.bak |
| Pre-install env backup | ~/.hermes/.env.a2a-preinstall.bak |
| 6 profile configs | ~/.hermes/profiles/*/config.yaml (all have a2a: sections) |

---

## 5. File Inventory

### Source: `a2a-plugin/src/`

```
src/a2a_plugin/
  __init__.py      # 319 lines — register() entry point, full wiring
  plugin.yaml      # Plugin manifest

src/adapter/
  __init__.py
  agent_card_builder.py       # 119 lines — capabilities to AgentCard protobuf
  agent_card_route.py         # 108 lines — Starlette route for /.well-known/agent-card.json
  agent_card_signer.py        # 217 lines — ES256 key gen/sign/verify
  hermes_executor.py          # 733 lines — AgentExecutor implementation
  profile_discovery.py        # 148 lines — scans config.yaml for a2a: sections

src/core/
  __init__.py
  fleet_controller.py          # 244 lines — routing engine (works)
  orchestrator.py              # 257 lines — flow management (NOT WIRED)
  domain/
    __init__.py
    interfaces/
      adapter.py            # 82 lines — A2AAdapter ABC (NOT IMPLEMENTED)
      fleet_controller.py   # 91 lines — FleetController ABC
      orchestrator.py       # 111 lines — Orchestrator ABC
    models/
      __init__.py
      intent.py             # 47 lines — TaskIntent
      result.py             # 74 lines — TaskResult with status validation
      capability.py         # 71 lines — AgentCapability with can_handle()
      dispatch.py           # 55 lines — ProfileDispatch
      persistence.py        # 146 lines — TaskRecord, ConversationGraph
```

### Tests: `a2a-plugin/tests/`

```
tests/
  __init__.py
  conftest.py                        # MockAdapter, fixture factories
  core/
    test_domain_models.py             # 443 lines
    test_fleet_controller.py          # 199 lines
    test_interfaces.py                # 163 lines — ABC enforcement
    test_orchestrator.py              # 248 lines
    test_persistence.py               # DOES NOT EXIST
  adapter/
    test_agent_card_builder.py        # 168 lines
    test_agent_card_route.py          # 170 lines — Starlette TestClient integration
    test_agent_card_signer.py         # 183 lines
    test_agent_card_signer_hardening.py # 386 lines — edge cases, concurrency
    test_hermes_executor.py           # 733 lines — SDK integration
    test_profile_discovery.py         # 148 lines
    test_wiring.py                    # 176 lines — full handler-to-executor pipeline
```

### Supporting Files

| File | Lines | Purpose |
|------|-------|---------|
| pyproject.toml | 19 | Zero dependencies declared |
| README.md | ~60 | Architecture overview |
| .gitignore | 8 | Standard |
| CODY_PHASE2.md | 130 | Bug fix notes |
| docs/decisions/adr-001-signing.md | 82 | Signing decision record |
| docs/research/milestone-0-blockers.md | 275 | M0 research findings |
| scripts/start-server.py | 155 | Standalone server (mock dispatch) |
| .hermes/plans/2026-05-20_1700-phase4-verification.md | - | Stale plan |

### Wiki Pages

| Page | Status | Notes |
|------|--------|-------|
| planning/a2a-plugin-v1.md | shows "designed" | Overclaims Phase 3 completion |
| planning/a2a-plugin-v1-m3.md | shows "completed" | Missing auth/signing/persistence |
| planning/a2a.md | superseded | Legacy plugin history |
| config/2026-05-20-a2a-profile-config.md | current | Config format reference |
| config/2026-05-20-a2a-standalone-server.md | current | Handover sequence, port conflict |
| subsystem/a2a.md | deprecated | Legacy patterns not yet ported |
| raw/articles/a2a-spec.md | raw | Full v1.0 spec, 6,013 lines |

### Tesla Reference Docs (in workspace root `/Users/fleety/webgui-files/`)

| File | Description |
|------|-------------|
| a2a-core-scope-tesla.md | Tesla's original scope |
| a2a-domain-contracts.md | Domain model contracts |
| a2a-orchestration-patterns.md | FC vs Orchestrator patterns |
| a2a-plugin-architecture.md | Hexagonal architecture, SSRF, auth |

### Skill References

| Skill | Path |
|-------|------|
| hermes-plugins | references/a2a-server-deployment.md |
| hermes-plugins | references/a2a-adapter-integration.md |
| playbook-orchestration | references/hermes-a2a-protocol.md (overclaims) |
| systematic-troubleshooting | references/a2a-sdk-proto-mapping.md |
| systematic-research | references/a2a-hexagonal-architecture.md |

---

## 6. Handoff Sequence

### Immediate Actions (in order)

1. Kill standalone server: `kill $(lsof -ti :9696)`
2. Disable watchdog: `hermes cron list` then `hermes cron remove <job_id>`
3. Restart gateway: `hermes gateway restart`
4. Verify plugin loaded: `curl http://127.0.0.1:9696/.well-known/agent-card.json`
5. Add `a2a:` sections to Tesla's profile configs

### Priority Order for Closing Gaps

| Priority | Gap | Description | Est. Effort |
|----------|-----|-------------|-------------|
| P0 | G2 | Activate real dispatch (gateway restart sequence) | 30 min |
| P0 | G5 | Bearer token auth | 1-2 days |
| P0 | G1 | Outbound A2A client + remote peer registry | 2-3 days |
| P1 | G3 | SQLite persistence (DatabaseTaskStore) | 1 day |
| P1 | G7 | Implement cancel() + tests | 4 hours |
| P1 | G4 | Fix Agent Card signing + add verification | 4 hours |
| P2 | G6 | SSRF guard | 1 day |
| P2 | G11 | Wire OrchestratorImpl into register() | 4 hours |
| P2 | G12 | Declare dependencies in pyproject.toml | 15 min |
| P2 | G14 | Env var overrides for config | 30 min |
| P3 | G8 | Streaming/SSE support | 2-3 days |
| P3 | G9 | Push notification webhooks | 2 days |
| P3 | C1-C6 | Contract compliance sweep | 1-2 days |
| P3 | I1-I6 | Implementation hardening | 2-3 days |
| P3 | T1-T6 | Test gap closure | 1-2 days |
| P4 | G10 | Task-to-Kanban mapping | 1 day |
| P4 | S3-S6 | Security hardening (audit log, rate limit, provenance) | 2 days |

### What NOT to Do

- Don't rewrite domain models — TaskIntent, TaskResult, AgentCapability, ProfileDispatch, TaskRecord, ConversationGraph are clean, tested, contract-compliant
- Don't replace FleetController — routing logic is correct. Needs concurrency hardening and better scoring, not replacement
- Don't replace AgentCard builder — clean protobuf translation. Needs verification layer
- Don't replace HermesExecutor — SDK integration pattern is correct. Needs cancel() and streaming
- Don't refactor hexagonal boundary — src/core/ has zero A2A imports, boundary is clean

---

*End of Handoff Document*
