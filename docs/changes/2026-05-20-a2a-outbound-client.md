---
title: Outbound Mesh Peer Client — Phase 2+3
created: 2026-05-20
type: change
status: complete
tags: [a2a, phase2, phase3, mesh, client, ssrf]
---

# Outbound Mesh Peer Client — Phase 2+3

## What Was Built

The outbound mesh peer client — the final piece connecting Phase 2+3 components into a working cross-node dispatch pipeline.

## New Component: MeshPeerClient

**File:** `src/adapter/mesh_peer_client.py`

- `connect_peer(peer_name)` — resolves peer AgentCard via SDK, creates authenticated SDK Client with SSRF transport, registers all peer skills as capabilities in FleetController
- `connect_all()` — connects every peer in the registry
- `send_task(intent)` — translates TaskIntent → A2A SendMessageRequest, sends with bearer token auth, translates response back to TaskResult
- `close()` — clean shutdown of peer clients

## Integration Points

**`src/adapter/hermes_executor.py`** — HermesExecutor.execute() now checks the FleetController route: if `endpoint` starts with `"a2a://"`, delegates to MeshPeerClient; otherwise uses local AIAgent dispatch.

**`src/a2a_plugin/__init__.py`** — Creates MeshPeerClient after PeerRegistry, schedules async peer connections at startup, wires MeshPeerClient into HermesExecutor.

## What Each Component Contributes

| Component | Files | Role in Dispatch |
|---|---|---|
| Peer Registry | `peer_registry.py` | Config → known peers + credentials |
| Auth Context | `auth_context_builder.py` | Validates inbound bearer tokens on server |
| SSRF Transport | `ssrf.py` | Blocks outbound non-global destinations |
| Version Middleware | `version_middleware.py` | Rejects non-1.0 headers |
| Mesh Peer Client | `mesh_peer_client.py` | Connects, auths, sends to remote peers |
| Executor | `hermes_executor.py` | Routes local vs remote dispatch |

## Test Results

- 254 tests pass (2 skipped — network-dependent)
- 11 new tests for MeshPeerClient

## Next

Cross-node dispatch test with Proteus — requires his A2A server to be running and accessible on the mesh.
