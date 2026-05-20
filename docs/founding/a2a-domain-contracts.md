---
title: A2A Domain Contracts — Protocol-Agnostic Models & Interfaces
created: 2026-05-17
updated: 2026-05-17
type: planning
status: draft
tags: [a2a, domain-models, interfaces, adapter, core]
sources:
  - "https://dev.to/sreeni5018/the-a2a-protocol-misconception-why-your-agent-architecture-matters-more-than-your-framework-3iif"
  - "https://a2a-protocol.org/latest/specification/"
  - "planning/a2a-plugin-architecture"
  - "planning/a2a-orchestration-patterns"
confidence: high
---

# A2A Domain Contracts — Protocol-Agnostic Models & Interfaces

## Purpose

This document defines the domain models and interfaces that form the contract between the A2A Adapter (Hermes plugin) and the Core Layer (Fleet Controller, Orchestrator, Profile Registry).

These models contain ZERO A2A protocol imports. They are pure Python dataclasses that can be used in any context — A2A adapter, REST API, batch job, cron task, or direct function call.

**Rule:**
- `from a2a import ...` MUST never appear in the same file as these models
- The adapter imports these models; these models do not import the adapter
- These models are testable in milliseconds with nothing but Python

## Domain Models

### TaskIntent — What One Agent Asks Another To Do

```python
# domain/models/intent.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TaskIntent:
    """
    A request from one agent to another.

    This is the fundamental unit of work in the system. The adapter
    translates an A2A SendMessageRequest into this; the Fleet Controller
    routes it to a profile; the profile executes it.

    Fields are protocol-agnostic. None contain A2A types.
    """
    intent_type: str
    """High-level intent: 'action_request', 'review', 'consultation',
    'notification', 'instruction'"""

    payload: dict
    """The actual task data. Structure varies by intent_type."""

    target_profile: Optional[str] = None
    """Specific profile to route to. If None, FC finds the best match."""

    target_node: Optional[str] = None
    """Specific node (mesh IP) to route to. If None, FC prefers local."""

    source_node: str = "local"
    """Which node originated this request."""

    source_profile: str = "orchestrator"
    """Which profile on the source node sent this."""

    context_id: Optional[str] = None
    """Groups related tasks into one conversation.
    Same as A2A contextId — but expressed in domain terms."""

    reference_task_ids: list[str] = field(default_factory=list)
    """Parent/related task IDs. Traces the conversation graph.
    Same as A2A referenceTaskIds — but expressed in domain terms."""

    metadata: dict = field(default_factory=dict)
    """Free-form metadata for extensions and custom data."""
```

### TaskResult — What Came Back

```python
# domain/models/result.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TaskResult:
    """
    The outcome of executing a TaskIntent.

    Covers the full A2A state spectrum: success, failure,
    or requests for more information (input-required, auth-required).
    """
    status: str
    """One of: 'completed', 'failed', 'cancelled', 'rejected',
    'input_required', 'auth_required'"""

    data: Optional[dict] = None
    """The result payload. For 'completed', this is the artifact.
    For 'input_required'/'auth_required', this describes what's needed."""

    error: Optional[str] = None
    """Human-readable error message if status == 'failed'."""

    requires_escalation: bool = False
    """True if this task needs human intervention."""

    escalation_reason: Optional[str] = None
    """Why human escalation is needed."""

    messages: list[dict] = field(default_factory=list)
    """Conversation history for multi-turn tasks.
    Each entry: {'role': 'user'|'agent', 'content': str, 'metadata': dict}"""

    artifacts: list[dict] = field(default_factory=list)
    """Named outputs. Each entry: {'name': str, 'content': str|dict,
    'media_type': str}"""

    metadata: dict = field(default_factory=dict)
    """Free-form metadata."""
```

### AgentCapability — What a Profile Can Do

```python
# domain/models/capability.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentCapability:
    """
    Describes a profile's capability for discovery and routing.

    Maps closely to A2A's AgentSkill, but is protocol-agnostic.
    The adapter translates this TO the AgentCard JSON; the core
    never sees the JSON.
    """
    profile_name: str
    """Unique identifier. Maps to ~/.hermes/profiles/<profile_name>/"""

    node_id: str
    """Mesh IP or node identity. Determines addressability."""

    display_name: str
    """Human-readable name (e.g., 'System Diagnostician')."""

    description: str
    """What this profile does and when to use it."""

    intents: list[str] = field(default_factory=list)
    """Intent types this profile handles.
    Examples: 'action_request', 'review', 'consultation',
    'notification', 'instruction'"""

    tags: list[str] = field(default_factory=list)
    """Keywords for discovery-based routing."""

    examples: list[str] = field(default_factory=list)
    """Example payloads showing expected input format.
    Critical for remote orchestrators formulating their calls."""

    input_modes: list[str] = field(default_factory=lambda: ["text", "application/json"])
    """Content types the profile can accept."""

    output_modes: list[str] = field(default_factory=lambda: ["text", "application/json"])
    """Content types the profile can produce."""

    supports_streaming: bool = False
    """True if this profile can stream results."""

    supports_push: bool = False
    """True if this profile can send push notifications."""
```

### ProfileDispatch — Fleet Controller Response

```python
# domain/models/dispatch.py
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProfileDispatch:
    """
    The Fleet Controller's routing decision.
    Tells the adapter which profile to call and how.
    """
    task_id: str
    """Unique task ID for tracking."""

    profile_name: str
    """Target profile to execute the task."""

    node_address: str
    """Where the profile lives. 'local' for same-node,
    mesh IP (100.96.x.x) for remote."""

    endpoint: str
    """A2A endpoint URL for remote dispatch, or
    'internal:profile' for local dispatch."""

    status: str
    """'dispatched', 'queued', 'unavailable', 'no_capacity'"""

    message: str = ""
    """Human-readable status detail."""
```

## Core Layer Interfaces

These are the method signatures that the adapter calls. They contain zero protocol types.

### Fleet Controller Interface

```python
# domain/interfaces/fleet_controller.py

class FleetController:
    """
    Routes TaskIntents to the right profile and node.

    Responsibilities:
    - Capability-based routing (match intent → profile)
    - Node-aware routing (prefer local, fall back to mesh)
    - Availability checking (is the profile busy?)
    - Capacity management (concurrent task limits)
    """

    def route(self, intent: TaskIntent) -> ProfileDispatch:
        """
        Find the best profile for this intent.

        Decision logic:
        1. If target_profile set: verify it can handle the intent_type
        2. If target_node set: verify node is reachable
        3. Otherwise: match intent_type against all available AgentCapabilities
           across local and mesh profiles
        4. Prefer local profile over remote (lower latency)
        5. Check profile availability (not busy, capacity slots open)
        6. Return dispatch decision or 'unavailable'/'no_capacity'
        """
        ...

    def release(self, task_id: str, profile_name: str) -> None:
        """
        Mark a profile as available after task completion.
        Called by the adapter when a task reaches a terminal state.
        """
        ...

    def register_profile(self, capability: AgentCapability) -> None:
        """
        Register a profile's capability. Called at plugin startup
        when AgentCard is parsed and profile directory is discovered.
        """
        ...

    def discover(self, intent_type: str,
                 tags: list[str] | None = None) -> list[AgentCapability]:
        """
        Find all profiles that can handle a given intent type,
        optionally filtered by tags. Returns profiles from all
        known nodes (local + mesh peers from cached Agent Cards).
        """
        ...
```

### Orchestrator Interface

```python
# domain/interfaces/orchestrator.py

class Orchestrator:
    """
    Manages live multi-task orchestration flows.

    Responsibilities:
    - Monitor mid-flight tasks for status transitions
    - Handle INPUT_REQUIRED by recruiting specialists
    - Compose answers and resume blocked tasks
    - Track conversation graphs (contextId → task tree)
    """

    def register_task(self, task_id: str, context_id: str,
                      parent_task_id: str | None = None) -> None:
        """Register a task for lifecycle monitoring."""
        ...

    def on_status_change(self, task_id: str, new_state: str,
                         task_result: TaskResult) -> None:
        """
        Called by adapter when any tracked task changes state.

        If new_state == 'input_required':
          1. Parse the request from task_result.data
          2. Call recruit_specialist() or route to human
          3. Compose the answer as a new TaskIntent
          4. Resume the original task

        If new_state == 'completed' | 'failed' | 'cancelled':
          1. Log the outcome
          2. Notify parent task if this was a sub-task
          3. Clean up tracking
        """
        ...

    def recruit_specialist(self, question: str,
                           source_context_id: str,
                           parent_task_id: str,
                           tags: list[str] | None = None) -> TaskResult:
        """
        Find the right profile for a sub-question and dispatch
        a new task. Returns the specialist's answer.

        Uses the Fleet Controller's discover() to find candidates.
        Dispatches via the adapter's send_task().
        Waits for completion (or first result for streaming).
        """
        ...

    def get_conversation_graph(self, context_id: str) -> dict:
        """
        Return the task tree for a context_id.
        Shows all linked tasks, their statuses, and parent-child links.
        Used for audit, debugging, and recovery after restart.
        """
        ...
```

### Adapter Interface (What the Core Expects From the Adapter)

```python
# domain/interfaces/adapter.py

class A2AAdapter:
    """
    The plugin's contract to the Core layer.

    The Core calls these methods when it needs to send or
    receive across the protocol boundary. The Adapter implementation
    translates to/from A2A protocol objects.
    """

    def send_task(self, intent: TaskIntent) -> TaskResult:
        """
        Send a task to a profile, either locally (spawn profile)
        or remotely (A2A call to a mesh peer).
        Returns the result when the task reaches a terminal state.
        """
        ...

    async def send_streaming_task(self, intent: TaskIntent) -> TaskResult:
        """
        Like send_task but with streaming updates.
        The Core provides a callback for intermediate results.
        """
        ...

    def cancel_task(self, task_id: str) -> bool:
        """Request cancellation of an in-flight task."""
        ...

    def get_capabilities(self) -> list[AgentCapability]:
        """
        Return this node's capabilities by reading the profile
        directories and loading their SOUL.md + config.
        Called at plugin startup to build the AgentCard.
        """
        ...
```

## Storage Models (Task Persistence)

```python
# domain/models/persistence.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TaskRecord:
    """
    Persisted representation of an A2A task.

    The adapter persists incoming/outgoing tasks so they survive
    gateway restarts and are queryable via ListTasks.
    """
    task_id: str
    context_id: str
    status: str  # A2A TaskState string
    intent_type: str
    source_node: str
    target_profile: str
    target_node: str
    payload: dict
    result: Optional[dict] = None
    messages: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    reference_task_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    terminal: bool = False


@dataclass
class ConversationGraph:
    """
    An orchestration flow — one root task with zero or more sub-tasks.
    Recoverable from contextId.
    """
    context_id: str
    root_task_id: str
    tasks: dict[str, TaskRecord] = field(default_factory=dict)
    # task_id → TaskRecord, includes all linked tasks
```

## Development Order

Per the article's guidance: define domain layer FIRST, write tests, build adapter last.

### Phase 1 — Models & Tests (Day 1)

1. Define all domain models in `core/domain/models/`
2. Write pure unit tests:
   - `test_task_intent_creation()`
   - `test_task_result_status_mapping()`
   - `test_agent_capability_match_intent()`
   - `test_conversation_graph_linking()`
3. Tests run in microseconds, zero infrastructure needed

### Phase 2 — Core Interfaces (Days 1-2)

1. Define `FleetController` interface with stubs
2. Define `Orchestrator` interface with stubs
3. Define `A2AAdapter` interface (what the Core expects)
4. Write interface-level tests:
   - `test_fleet_controller_routes_to_matching_profile()`
   - `test_orchestrator_handles_input_required()`
   - Mock the adapter for test isolation

### Phase 3 — Adapter (Days 3-5)

1. Implement `A2AAdapter` using a2a-sdk
2. Implement `AgentCard` builder from `AgentCapability` list
3. Wire to Fleet Controller and Orchestrator
4. Integration test with local loopback A2A call
5. Integration test with mesh peer (Proteus ↔ Tesla)

### Phase 4 — Verification (Day 5+)

```bash
# Protocol imports in core — MUST be zero
grep -r "from a2a import" src/core/ || echo "Clean: no A2A imports in core"

# Business logic in adapter — MUST be zero
grep -r "if.*>" src/adapter/  # Should show nothing policy-related

# Core logic tests without infrastructure
pytest tests/core/ -q  # Should complete in < 1 second

# Adapter tests with mock A2A server
pytest tests/adapter/ -q
```

## Related Pages

- [[planning/a2a-plugin-architecture]] — Hexagonal foundation and 3-layer model
- [[planning/a2a-orchestration-patterns]] — Dynamic orchestration model
- [[planning/a2a-plugin-v1]] — Project record and decision log
