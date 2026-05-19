"""Interface contracts for the Core Layer.

These are abstract base classes defining the contracts between the
Core Layer (Phase 1-2, Tesla) and the Adapter Layer (Phase 3, Proteus).

Contain ZERO A2A imports. The adapter depends on these interfaces;
they do not depend on the adapter.
"""

from .fleet_controller import FleetController
from .orchestrator import Orchestrator
from .adapter import A2AAdapter

__all__ = [
    "FleetController",
    "Orchestrator",
    "A2AAdapter",
]
