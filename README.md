# A2A Core — Hermes Plugin for Agent-to-Agent Protocol v1.0

Implementation of Google's [A2A Protocol v1.0](https://a2a-protocol.org/) as a Hermes plugin. Protocol-agnostic domain models with hexagonal adapter architecture.

## Quick Start

```bash
git clone https://github.com/OrendaD/a2a-plugin.git
cd a2a-plugin
bash setup.sh          # bootstrap: install deps, run tests, configure profiles
python scripts/start-server.py --port 9696   # standalone server (mock dispatch)
```

## Architecture

Three strict layers with a **non-negotiable boundary** — `src/core/` has zero A2A SDK imports:

```
A2A SDK (Google v1.0.3)    — protocol framing, JSON-RPC, AgentCard types
  ^ src/adapter/            — HermesExecutor, ProfileDiscovery, CardBuilder, CardSigner
  ^ src/core/               — domain models, FleetController, Orchestrator
```

**Verify boundary:**
```bash
grep -r "from a2a" src/core/    # MUST return zero
```

## Where to Start (for Tesla)

| Read first | What you'll learn |
|------------|-------------------|
| `docs/A2A-PLUGIN-HANDOFF-TO-TESLA.md` | Complete state: what works, what's broken, what's urgent |
| `docs/founding/a2a-domain-contracts.md` | Original contract — the spec we're building to |
| `docs/founding/a2a-core-scope-tesla.md` | What was scoped for you specifically |
| `docs/founding/a2a-plugin-architecture.md` | Hexagonal architecture, SSRF, auth design |
| `docs/founding/a2a-orchestration-patterns.md` | FC vs Orchestrator, specialist recruitment |

## Repo Structure

```
a2a-plugin/
  src/
    a2a_plugin/          # Plugin entry point — register() wires everything
      __init__.py        # 319 lines — full integration (dispatch, FC, server)
      plugin.yaml        # Hermes plugin manifest
    adapter/             # A2A SDK integration layer
      hermes_executor.py      # AgentExecutor implementation (733 lines)
      agent_card_builder.py   # Capabilities → AgentCard protobuf
      agent_card_route.py     # Starlette route for /.well-known/agent-card.json
      agent_card_signer.py    # ES256 key generation, signing, verification
      profile_discovery.py    # Scans profile config.yaml for a2a: sections
    core/                # Domain layer — zero A2A imports
      fleet_controller.py     # Routing engine (244 lines)
      orchestrator.py         # Stateful flow management (257 lines, NOT YET WIRED)
      domain/models/          # TaskIntent, TaskResult, AgentCapability, etc.
      domain/interfaces/      # A2AAdapter, FleetController, Orchestrator ABCs
  tests/
    core/                 # 71 tests — dataclasses, FC routing, Orchestrator, interfaces
    adapter/              # 106 tests — builder, signer, executor, profile discovery, wiring
  scripts/
    start-server.py       # Standalone server (mock dispatch until gateway restart)
  docs/
    founding/             # Founding contract documents (Tesla's original scope docs)
    wiki-exports/         # Exported Hermes Wiki pages for offline reference
    skill-refs/           # Hermes skill reference files for A2A integration
    decisions/            # ADR-001: signing algorithm & key storage
    research/             # Milestone 0 blockers research
    A2A-PLUGIN-HANDOFF-TO-TESLA.md  # Complete handoff document
  setup.sh               # One-command environment bootstrap (idempotent)
```

## Test Suite

```bash
# All tests (177)
python -m pytest tests/ -q

# By layer
python -m pytest tests/core/ -q    # 71 tests — < 0.2s
python -m pytest tests/adapter/ -q # 106 tests — < 2s
```

## Gateway Integration

The plugin auto-loads when Hermes gateway starts:

```bash
hermes gateway restart    # plugin auto-loads with real dispatch
```

Until gateway restart, the standalone server (`scripts/start-server.py`) returns mock responses. See the handoff doc for the handover sequence.

## Running Server

| Mode | Dispatch | Port | Lifecycle |
|------|----------|------|-----------|
| Standalone (`scripts/start-server.py`) | Mock placeholder | 9696 | Manual kill/restart |
| Plugin (after `hermes gateway restart`) | Real `delegate_task` | 9696 | Tied to gateway process |

Verify server is live:

```bash
curl http://127.0.0.1:9696/.well-known/agent-card.json
curl -X POST http://127.0.0.1:9696/a2a/jsonrpc \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"message_id":"t1","role":"ROLE_USER","parts":[{"text":"ping"}]}}}'
```

## Key Gaps to Close

| Priority | Gap | Effort |
|----------|-----|--------|
| P0 | Real dispatch (gateway restart) | 30 min |
| P0 | Bearer token auth | 1-2 days |
| P0 | Outbound A2A client + mesh peering | 2-3 days |
| P1 | SQLite persistence | 1 day |
| P1 | Implement cancel() | 4 hours |
| P1 | Fix Agent Card signing | 4 hours |
| P2 | SSRF guard | 1 day |
| P2 | Wire Orchestrator | 4 hours |

Full details: `docs/A2A-PLUGIN-HANDOFF-TO-TESLA.md`

## License

Apache 2.0 (matching A2A SDK license)
