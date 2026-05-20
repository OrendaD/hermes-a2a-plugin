---
title: A2A Orchestration Patterns — Knowledge Router Model
created: 2026-05-17
updated: 2026-05-17
type: planning
status: draft
tags: [a2a, orchestration, input-required, cross-node, kanban, conversation-graph]
sources:
  - "https://dev.to/sreeni5018/the-a2a-protocol-misconception-why-your-agent-architecture-matters-more-than-your-framework-3iif"
  - "https://a2a-protocol.org/latest/specification/"
  - "planning/a2a-plugin-architecture"
confidence: high
---

# A2A Orchestration Patterns — Knowledge Router Model

## Meta Goal: Composable Inter-Node Agent Teams

The system is not a set of isolated agents each doing their own thing. It's a **composable knowledge network** where the orchestrator dynamically assembles specialist teams across nodes to solve problems, then disbands them when the task completes.

An orchestrator (Tesla or Proteus, depending on context):
1. Receives a goal
2. Breaks it into sub-tasks
3. Dispatches to the right profiles on the right nodes
4. Monitors mid-flight for deviation, blocks, or knowledge gaps
5. Intervenes dynamically — recruiting new specialists, feeding information, unblocking
6. Steers to completion

This is the opposite of a fire-and-forget pipeline.

## Two Coordination Models: Kanban vs A2A Orchestration

| Aspect | Kanban | A2A Orchestration |
|--------|--------|-------------------|
| Workflow shape | Fixed pipeline (A→B→C) | Dynamic conversation graph |
| Handoffs | Predefined column transitions | Runtime discovery (`input-required`) |
| Blocking | Stalls the board | Pauses task, recruits help, resumes |
| Team composition | Fixed per board | Assembled per task, cross-node |
| Best for | Known-repeatable sequences | Adaptive, discovery-driven work |
| Example | Deploy → Test → Review | Diagnose → research needed → resume |

### Kanban Domain — Known Pipelines

Kanban remains the right tool for workflows with a predictable handoff order:

- **Deployment pipeline:** Ray validates health → Ops deploys → Reviewer confirms
- **Code change lifecycle:** Cody writes → Reviewer approves → Ops deploys
- **Standard maintenance:** Ops runs upgrade → Ray verifies → Reviewer signs off

These are stable enough that the column model adds value — visual progress tracking, WIP limits, explicit gates.

### A2A Domain — Adaptive Orchestration

A2A orchestration handles everything that can't be pre-planned:

- **Diagnosis with knowledge gaps:** Ray starts on an Arch Linux issue → hits a gap (`input-required`) → orchestrator recruits Odin → Odin researches → orchestrator feeds answer → Ray resumes
- **Multi-node investigation:** Tesla's Ray needs a config file from Proteus's filesystem → Proteus's builder fetches it → Tesla's Ray continues with the data
- **Human escalation:** Agent hits `input-required` with a question only a human can answer → orchestrator formats the question → routes to Telegram → human responds → task resumes

## The `input-required` Pattern

This is the core enabler of dynamic orchestration. It is NOT a failure state — it is a **request for more information**.

### Protocol Semantics

From A2A v1.0 spec (Section 4.1.3):
- `TASK_STATE_INPUT_REQUIRED` — "Represents the status that the task requires information to complete. This is an interrupted state."
- Not terminal. Task resumes when client responds with a new message on the same task.

### Orchestrator Handler

```
When Task.status == INPUT_REQUIRED:

  1. INSPECT
     - Read the latest message in task.history (what's being asked)
     - Parse the structured request (DataPart) or text question (TextPart)

  2. ASSESS
     - Can I answer from my own knowledge?
     - Does a specialist profile exist?
     - Does a specialist profile exist on a different node?
     - Does a human need to be asked?

  3. IF SPECIALIST NEEDED:
     a. Find profile: which profile can answer this?
        - Match against Agent Card skills/tags/examples
        - Prefer local (same node), fall back to remote
     b. Dispatch new A2A task with:
        - metadata.referenceTaskIds = [original_task_id]
        - metadata.contextId = original_task.contextId  (conversation grouping)
        - Payload = what Ray is asking for
     c. Wait for completion
     d. Extract answer from result

  4. COMPOSE & RESUME
     - Package answer + any useful context
     - Send as new Message on original task
     - Task transitions back to WORKING

  5. IF HUMAN NEEDED:
     - Format the question for display
     - Route to Telegram/Discord/supported platform
     - Await human response
     - Send answer as new Message on task
```

### Example Trace

```
Orchestrator (Tesla, VPS) dispatches to Ray (Tesla, VPS):
  Intent: diagnose
  Payload: "Nginx 502 on /v1/orders, upstream timeout in logs"
  contextId: ctx-abc-123

Ray processes, hits Arch Linux knowledge gap:
  Status: WORKING → INPUT_REQUIRED
  Message: "Need: equivalent of `apt install nginx` on Arch Linux"
  Task: tasks/ray-456 (contextId: ctx-abc-123)

Orchestrator sees INPUT_REQUIRED on tasks/ray-456:
  → Needs package manager translation
  → Odin's Agent Card lists tag "linux" with skill "research"
  → Odin is on Proteus's iMac (100.96.0.1)

Orchestrator dispatches to Odin (Proteus, iMac):
  Intent: consultation
  Payload: "What is the pacman equivalent of `apt install nginx` on Arch Linux?"
  contextId: ctx-abc-123
  referenceTaskIds: ["tasks/ray-456"]

Odin completes:
  Status: COMPLETED
  Artifact: "`pacman -S nginx`. Arch uses pacman, not apt."

Orchestrator composes and resumes Ray:
  Message on tasks/ray-456:
    "Arch Linux uses `pacman -S <package>` instead of `apt install`.
     The equivalent is `pacman -S nginx`. Proceed."

  Status: INPUT_REQUIRED → WORKING → COMPLETED
```

## Fleet Controller vs Orchestrator

These are two separate roles in the Core layer:

| Role | Responsibility | Interface |
|------|---------------|-----------|
| **Fleet Controller** | Route task to profile, check availability, manage capacity, spawn profile processes | Stateless. Input: `TaskIntent`. Output: task ID + status. |
| **Orchestrator** | Monitor mid-flight tasks, detect `input-required`, recruit specialists, compose answers, resume tasks | Stateful. Tracks live conversation graphs (contextIds → task tree). |

### Fleet Controller Interface (Pure)

```python
# Core layer — zero A2A imports
@dataclass
class DispatchResult:
    task_id: str
    profile_assigned: str
    node_assigned: str  # local node ID or remote mesh address
    initial_status: str

class FleetController:
    def route(self, intent: TaskIntent) -> DispatchResult:
        """Find the best profile+node for this intent.
        Checks profile availability, capacity, node reachability."""
        ...

    def release(self, task_id: str, profile: str) -> None:
        """Mark a profile as available after task completion."""
        ...
```

### Orchestrator Interface

```python
# Core layer — zero A2A imports. Adapter provides the transport.
class Orchestrator:
    def monitor(self, task_id: str, context_id: str) -> None:
        """Register a task for mid-flight observation."""

    def on_status_change(self, task_id: str, new_state: str,
                         message: Message, history: list[Message]) -> None:
        """Called by adapter when a task's state transitions."""

    def recruit_specialist(self, question: str,
                           context_id: str,
                           parent_task_id: str) -> TaskResult:
        """Find the right profile for a sub-question and dispatch
        a new task. Returns the specialist's answer."""
        ...
```

## Conversation Graph Model

Every orchestration flow produces a tree of linked tasks:

```
Orchestration (contextId: ctx-abc-123)
├── Task: Ray diagnoses Arch Linux issue (task/ray-456)
│     └── INPUT_REQUIRED → spawns sub-task
├── Task: Odin researches Arch package manager (task/odin-789)
│     └── COMPLETED → answer fed back to parent
└── Task: Ray resumes, completes (task/ray-456)
      └── COMPLETED → flow done
```

This graph is stored and queryable:
- **`contextId`** groups all tasks in one orchestration
- **`referenceTaskIds`** on each task links parent→child
- **`ListTasks(contextId=ctx-abc-123)`** returns the full tree
- The orchestrator can reconstruct any flow for audit or debugging

## Task Delivery Mechanisms (How the Orchestrator Waits)

| Mechanism | Use Case | Implementation |
|-----------|----------|---------------|
| Polling | Simple checks, low-frequency | `GetTask` every N seconds |
| Streaming | Actively waiting for a specialist | SSE connection, events pushed |
| Push notification | Long wait, orchestrator has other work | Webhook POST on status change |

For the dynamic orchestration pattern, the orchestrator typically uses **polling** when it's actively managing the flow or **streaming** when it's waiting on a specific specialist response. Push notifications scale to many concurrent orchestrations.

## When Kanban and A2A Coexist

The system does not choose one model — it uses both:

- **Predictable handoffs** → Kanban board (visual progress, WIP limits, gate checks)
- **Discovery-driven work** → A2A orchestration (dynamic team assembly, knowledge routing)
- **Hybrid flows** → Kanban for the stable skeleton, A2A `input-required` resolution as a sub-pattern within a Kanban card

Example: A deployment Kanban card has a column "Pre-deploy health check." The health check step uses A2A orchestration to adaptively diagnose any issues found. When diagnosis completes, the Kanban card advances. The Kanban board sees the pipeline; the A2A layer sees the adaptive resolution within each step.

## Related Pages

- [[planning/a2a-plugin-architecture]] — Hexagonal foundation and 3-layer model
- [[planning/a2a-plugin-v1]] — Project record and decision log
- [[planning/a2a-domain-contracts]] — Protocol-agnostic domain models
- [[planning/mesh-orchestration]] — Mesh coordination architecture
