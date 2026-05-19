"""TaskIntent — a request from one agent to another.

This is the fundamental unit of work in the system. The adapter
translates an A2A SendMessageRequest into this; the Fleet Controller
routes it to a profile; the profile executes it.

Fields are protocol-agnostic. None contain A2A types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TaskIntent:
    """A request from one agent to another.

    Attributes:
        intent_type: High-level intent. One of:
            'action_request', 'review', 'consultation',
            'notification', 'instruction'
        payload: The actual task data. Structure varies by intent_type.
        target_profile: Specific profile to route to.
            If None, FC finds the best match.
        target_node: Specific node (mesh IP) to route to.
            If None, FC prefers local.
        source_node: Which node originated this request.
        source_profile: Which profile on the source node sent this.
        context_id: Groups related tasks into one conversation.
            Maps to A2A contextId in the adapter layer.
        reference_task_ids: Parent/related task IDs.
            Traces the conversation graph.
            Maps to A2A referenceTaskIds in the adapter layer.
        metadata: Free-form metadata for extensions and custom data.
    """

    intent_type: str
    payload: dict
    target_profile: Optional[str] = None
    target_node: Optional[str] = None
    source_node: str = "local"
    source_profile: str = "orchestrator"
    context_id: Optional[str] = None
    reference_task_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
