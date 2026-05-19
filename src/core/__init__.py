"""A2A Core Layer — Protocol-agnostic domain models and interfaces.

This package contains ZERO A2A protocol imports. Everything here is
pure Python dataclasses and ABCs, testable in milliseconds with nothing
but pytest.

Boundary rule: if you see ``from a2a import ...`` in this tree,
the architecture is broken.
"""
