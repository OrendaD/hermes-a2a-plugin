"""Protocol-agnostic domain models.

These models contain ZERO A2A protocol imports. They are pure Python
dataclasses that can be used in any context — A2A adapter, REST API,
batch job, cron task, or direct function call.

Rule:
- ``from a2a import ...`` MUST never appear in the same file as these models
- The adapter imports these models; these models do not import the adapter
- These models are testable in milliseconds with nothing but Python
"""

from .intent import TaskIntent
from .result import TaskResult
from .capability import AgentCapability
from .dispatch import ProfileDispatch
from .persistence import TaskRecord, ConversationGraph

__all__ = [
    "TaskIntent",
    "TaskResult",
    "AgentCapability",
    "ProfileDispatch",
    "TaskRecord",
    "ConversationGraph",
]
