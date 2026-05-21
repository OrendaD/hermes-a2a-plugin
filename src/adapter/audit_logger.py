"""A2A Audit Logger — JSONL append-only file with rotation.

Writes structured audit events to a JSONL file at ``~/.hermes/a2a_audit.jsonl``
(default, configurable). Thread-safe via a write lock. Rotates automatically
when the log file exceeds ``max_bytes`` (default 10 MB), keeping up to
``max_backups`` (default 3) rotated archive files.

Event types
-----------
- ``task_submitted`` — task was received and queued
- ``task_in_progress`` — task dispatch started (local or remote)
- ``task_completed`` — task finished with a successful result
- ``task_failed`` — task finished with an error
- ``task_cancelled`` — task was cancelled by user or system
- ``message_received`` — an A2A message was received from a client
- ``message_sent`` — an A2A message was emitted to the client
- ``agent_card_fetched`` — agent card was requested
- ``auth_failure`` — authentication or authorisation check failed
- ``peer_connected`` — outbound mesh peer connection established
- ``peer_disconnected`` — outbound mesh peer connection lost
- ``orchestrator_recruit`` — orchestrator recruited a specialist sub-agent
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional


class AuditLogger:
    """Thread-safe JSONL audit logger with automatic log rotation.

    Writes one JSON object per line, append-only.  Rotates at *max_bytes*
    (default 10 MB), keeps *max_backups* (default 3) rotated files.
    Uses a ``threading.Lock`` so concurrent writers (daemon threads,
    async tasks) do not corrupt the log.

    Args:
        log_path: Path to the JSONL log file.  ``~`` is expanded to the
            user's home directory.  Default: ``~/.hermes/a2a_audit.jsonl``.
        max_bytes: Maximum file size in bytes before rotation.
            Default: 10 MB (10 * 1024 * 1024).
        max_backups: Number of rotated backup files to retain.
            Default: 3 (producing ``.1``, ``.2``, ``.3`` suffixes).
    """

    def __init__(
        self,
        log_path: str = "~/.hermes/a2a_audit.jsonl",
        max_bytes: int = 10 * 1024 * 1024,
        max_backups: int = 3,
    ) -> None:
        self._log_path = os.path.expanduser(log_path)
        self._max_bytes = max_bytes
        self._max_backups = max_backups
        self._lock = threading.Lock()

        # Ensure parent directory exists
        log_dir = os.path.dirname(self._log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_event(
        self,
        event: str,
        task_id: Optional[str] = None,
        context_id: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """Write a structured audit event to the log.

        Args:
            event: Event type name (e.g. ``"task_completed"``).
            task_id: Optional A2A task ID associated with the event.
            context_id: Optional A2A context (conversation) ID.
            **extra: Additional event-specific fields (e.g. ``status``,
                ``error``, ``profile_name``, ``message_id``).  Values
                are converted via ``json.dumps(..., default=str)`` so
                non-serialisable types are stringified.
        """
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        if task_id is not None:
            record["task_id"] = task_id
        if context_id is not None:
            record["context_id"] = context_id
        if extra:
            record.update(extra)

        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"

        with self._lock:
            self._rotate_if_needed()
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def log_path(self) -> str:
        """The resolved path of the JSONL log file."""
        return self._log_path

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def max_backups(self) -> int:
        return self._max_backups

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rotate_if_needed(self) -> None:
        """Rotate the log file if it exceeds ``max_bytes``.

        Rotation scheme (for *max_bytes* = 10 MB, *max_backups* = 3):

            1. Delete ``a2a_audit.jsonl.3`` (oldest backup)
            2. Rename ``.2`` → ``.3``
            3. Rename ``.1`` → ``.2``
            4. Rename current file → ``.1``

        After rotation a fresh (empty) log file is created on the next
        ``log_event()`` call via the ``open("a")`` mode.

        **Thread safety**: This method must only be called while
        ``self._lock`` is held (by ``log_event``).
        """
        if not os.path.exists(self._log_path):
            return

        try:
            size = os.path.getsize(self._log_path)
        except OSError:
            return  # file disappeared between exists() and getsize()

        if size < self._max_bytes:
            return

        # 1. Remove the oldest backup
        oldest = f"{self._log_path}.{self._max_backups}"
        try:
            if os.path.exists(oldest):
                os.remove(oldest)
        except OSError:
            pass

        # 2. Shift backups: .N → .N+1 for N = max_backups-1 … 1
        for i in range(self._max_backups - 1, 0, -1):
            src = f"{self._log_path}.{i}"
            dst = f"{self._log_path}.{i + 1}"
            try:
                if os.path.exists(src):
                    os.rename(src, dst)
            except OSError:
                pass

        # 3. Rename current log to .1
        try:
            os.rename(self._log_path, f"{self._log_path}.1")
        except OSError:
            pass
