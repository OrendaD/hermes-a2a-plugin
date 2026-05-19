# A2A Core Layer

Protocol-agnostic domain models and orchestration for Hermes Agent-to-Agent communication.

## Architecture

```
src/core/
├── __init__.py
├── domain/
│   ├── models/
│   │   ├── intent.py          # TaskIntent
│   │   ├── result.py          # TaskResult (+ status validation)
│   │   ├── capability.py      # AgentCapability (+ can_handle)
│   │   ├── dispatch.py        # ProfileDispatch
│   │   └── persistence.py     # TaskRecord, ConversationGraph
│   └── interfaces/
│       ├── fleet_controller.py # FleetController ABC
│       ├── orchestrator.py     # Orchestrator ABC
│       └── adapter.py          # A2AAdapter ABC
tests/
└── core/
    ├── test_domain_models.py   # Pure dataclass unit tests
    └── test_interfaces.py      # ABC enforcement + boundary rule check
```

## Boundary Rule

This package contains **zero A2A protocol imports**. The adapter layer
(Proteus) translates A2A protocol objects into these domain models.

```
grep -r "from a2a" src/core/    # MUST return zero
grep -r "import a2a" src/core/  # MUST return zero
```

## Running Tests

```bash
cd a2a-core
pip install -e ".[dev]"  # or just: pip install pytest
pytest tests/
```

All tests complete in < 1 second. Zero infrastructure required.

## Ownership

- **Tesla** — Phases 1-2: domain models, Fleet Controller, Orchestrator
- **Proteus** — Phase 3: A2A Adapter plugin (translates to/from a2a-sdk)
- **Both** — Phase 4: verification and cross-node integration
