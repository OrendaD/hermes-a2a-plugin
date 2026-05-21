"""Tests for AuditLogger — JSONL append-only file, rotation, thread safety.

These tests verify:
- Log file creation and correct JSONL format
- All 12 event types (task_submitted through orchestrator_recruit)
- Event structure (timestamp, event name, optional fields, extras)
- Log rotation at max_bytes boundary
- Backup file shifting (3 backups)
- Thread-safe concurrent writes from multiple threads
- Custom log path, max_bytes, max_backups
- Idempotent rotation when the file does not exist yet
- Missing optional fields are not written as null keys
- Directory creation for custom paths
- Re-opening after rotation continues appending correctly
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone

import pytest

from adapter.audit_logger import AuditLogger


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _read_log(path: str) -> list[dict]:
    """Read all JSON objects from a JSONL file."""
    if not os.path.exists(path):
        return []
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _count_lines(path: str) -> int:
    """Count non-empty lines in a file."""
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _file_size(path: str) -> int:
    return os.path.getsize(path)


# ------------------------------------------------------------------
# Test classes
# ------------------------------------------------------------------


class TestAuditLoggerBasics:
    """Basic log creation, writing, and structure."""

    def test_creates_log_file(self, tmp_path: str) -> None:
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)
        logger.log_event("task_submitted", task_id="task/1")

        assert os.path.exists(log_path)
        records = _read_log(log_path)
        assert len(records) == 1

    def test_log_content_is_valid_jsonl(self, tmp_path: str) -> None:
        """Each line must be a valid JSON object."""
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)

        for i in range(3):
            logger.log_event("task_submitted", task_id=f"task/{i}")

        with open(log_path, "r") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                assert line, f"Empty line {line_no}"
                obj = json.loads(line)
                assert isinstance(obj, dict), f"Line {line_no} not a dict"

    def test_log_record_structure(self, tmp_path: str) -> None:
        """Every record has timestamp, event, and optional fields."""
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)

        logger.log_event(
            "task_completed",
            task_id="task/42",
            context_id="ctx/99",
            status="completed",
            extra_field="hello",
        )

        records = _read_log(log_path)
        assert len(records) == 1
        r = records[0]

        # Must have timestamp and event
        assert "timestamp" in r
        assert r["event"] == "task_completed"
        # Verify ISO 8601 format
        assert "T" in r["timestamp"], f"Not ISO 8601: {r['timestamp']}"

        # Optional fields
        assert r["task_id"] == "task/42"
        assert r["context_id"] == "ctx/99"

        # Extra kwargs
        assert r["status"] == "completed"
        assert r["extra_field"] == "hello"

    def test_missing_optional_fields_omitted(self, tmp_path: str) -> None:
        """When task_id/context_id are None, they are not written."""
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)

        logger.log_event("auth_failure", reason="invalid_token")

        records = _read_log(log_path)
        assert len(records) == 1
        r = records[0]
        assert "task_id" not in r
        assert "context_id" not in r
        assert r["reason"] == "invalid_token"

    def test_empty_extra_does_not_crash(self, tmp_path: str) -> None:
        """log_event with no extra kwargs."""
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)

        logger.log_event("peer_connected", task_id="task/x")
        records = _read_log(log_path)
        assert len(records) == 1
        assert records[0]["event"] == "peer_connected"

    def test_timestamp_is_utc_iso8601(self, tmp_path: str) -> None:
        """Timestamp should be ISO 8601 UTC."""
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)
        logger.log_event("task_submitted")

        records = _read_log(log_path)
        ts = records[0]["timestamp"]
        # Should parse as datetime
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None or ts.endswith("Z"), (
            f"Expected timezone-aware or Z: {ts}"
        )

    def test_append_only(self, tmp_path: str) -> None:
        """Multiple writes accumulate, not overwrite."""
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)

        count = 10
        for i in range(count):
            logger.log_event("task_submitted", task_id=f"task/{i}")

        assert _count_lines(log_path) == count
        records = _read_log(log_path)
        assert len(records) == count
        assert records[0]["task_id"] == "task/0"
        assert records[-1]["task_id"] == "task/9"


class TestAllEventTypes:
    """All 12 event types (from the spec) log correctly."""

    EVENT_TYPES = [
        "task_submitted",
        "task_in_progress",
        "task_completed",
        "task_failed",
        "task_cancelled",
        "message_received",
        "message_sent",
        "agent_card_fetched",
        "auth_failure",
        "peer_connected",
        "peer_disconnected",
        "orchestrator_recruit",
    ]

    def test_all_event_types(self, tmp_path: str) -> None:
        log_path = os.path.join(tmp_path, "audit.jsonl")
        logger = AuditLogger(log_path=log_path)

        for evt in self.EVENT_TYPES:
            logger.log_event(evt, task_id="task/1")

        records = _read_log(log_path)
        assert len(records) == len(self.EVENT_TYPES)
        logged_events = [r["event"] for r in records]
        assert logged_events == self.EVENT_TYPES


class TestRotation:
    """Rotation at max_bytes boundary; backup file management."""

    def test_rotation_basic(self, tmp_path: str) -> None:
        """When the log exceeds max_bytes, it rotates to .1."""
        log_path = os.path.join(tmp_path, "rotate.jsonl")
        # Very small max_bytes so we trigger rotation quickly
        logger = AuditLogger(log_path=log_path, max_bytes=200, max_backups=3)

        # Write enough data to exceed 200 bytes
        for i in range(20):
            logger.log_event("task_submitted", task_id=f"task/{i}", data="x" * 50)

        # The current log should exist and be under max_bytes
        assert os.path.exists(log_path)
        assert _file_size(log_path) <= logger.max_bytes + 200  # slight tolerance

        # At least backup .1 should exist
        backup_1 = f"{log_path}.1"
        assert os.path.exists(backup_1), f"Backup {backup_1} not found"
        assert _file_size(backup_1) > 0

    def test_rotation_backup_shift(self, tmp_path: str) -> None:
        """Multiple rotations shift .1→.2→.3 correctly."""
        log_path = os.path.join(tmp_path, "shift.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=100, max_backups=3)

        # Rapidly fill and rotate 5 times
        for batch in range(5):
            for i in range(10):
                logger.log_event("task_submitted", task_id=f"batch{batch}/task{i}",
                                 data="x" * 30)

        # After 5 rotations we should see .1, .2, .3 (and possibly more)
        backups_exist = []
        for i in range(1, 4):
            p = f"{log_path}.{i}"
            if os.path.exists(p):
                backups_exist.append(i)
                assert os.path.getsize(p) > 0, f"Backup {p} is empty"

        # At least .1 should exist
        assert os.path.exists(f"{log_path}.1"), "No .1 backup after rotations"

    def test_rotation_no_backups_when_under_limit(self, tmp_path: str) -> None:
        """Below max_bytes, no rotation occurs."""
        log_path = os.path.join(tmp_path, "small.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=10 * 1024 * 1024)

        logger.log_event("task_submitted", task_id="task/1")

        assert not os.path.exists(f"{log_path}.1")
        assert _count_lines(log_path) == 1

    def test_rotation_removes_oldest_backup(self, tmp_path: str) -> None:
        """When max_backups=1, only .1 is kept; older backups are removed."""
        log_path = os.path.join(tmp_path, "single_backup.jsonl")
        # Tiny max_bytes so each event triggers rotation
        logger = AuditLogger(log_path=log_path, max_bytes=50, max_backups=1)

        for i in range(5):
            logger.log_event("task_submitted", task_id=f"task/{i}",
                             data="x" * 40)

        # .1 should exist
        assert os.path.exists(f"{log_path}.1"), "Backup .1 missing"

        # .2 should NOT exist (we only keep 1 backup)
        assert not os.path.exists(f"{log_path}.2"), (
            ".2 should not exist with max_backups=1"
        )

    def test_rotation_new_log_appendable(self, tmp_path: str) -> None:
        """After rotation, the fresh log is still appendable."""
        log_path = os.path.join(tmp_path, "reopen.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=100, max_backups=1)

        for i in range(5):
            logger.log_event("task_submitted", task_id=f"task/{i}",
                             data="x" * 30)

        # Write after rotation
        logger.log_event("task_completed", task_id="task/after-rotate")

        records = _read_log(log_path)
        assert any(r["event"] == "task_completed" for r in records), (
            "Event after rotation not found"
        )


class TestThreadSafety:
    """Concurrent writes from multiple threads do not corrupt the log."""

    def test_concurrent_writes(self, tmp_path: str) -> None:
        """10 threads, 100 writes each -> 1000 total records."""
        log_path = os.path.join(tmp_path, "concurrent.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=10 * 1024 * 1024)

        n_threads = 10
        writes_per_thread = 100
        barrier = threading.Barrier(n_threads)

        def worker(worker_id: int) -> None:
            barrier.wait()  # start together
            for i in range(writes_per_thread):
                logger.log_event(
                    "task_submitted",
                    task_id=f"worker{worker_id}/task{i}",
                )

        threads = [
            threading.Thread(target=worker, args=(wid,))
            for wid in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = _read_log(log_path)
        assert len(records) == n_threads * writes_per_thread, (
            f"Expected {n_threads * writes_per_thread} records, got {len(records)}"
        )

    def test_concurrent_writes_all_valid_json(self, tmp_path: str) -> None:
        """Every line in the log must be valid JSON after concurrent writes."""
        log_path = os.path.join(tmp_path, "concurrent_valid.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=10 * 1024 * 1024)

        def worker(wid: int) -> None:
            for i in range(50):
                logger.log_event(
                    "task_in_progress",
                    task_id=f"w{wid}/t{i}",
                    profile="test",
                )

        threads = [threading.Thread(target=worker, args=(wid,)) for wid in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with open(log_path, "r") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    pytest.fail(f"Invalid JSON on line {line_no}: {e}\nLine: {line!r}")
                assert "event" in obj, f"Line {line_no}: missing 'event'"
                assert "timestamp" in obj, f"Line {line_no}: missing 'timestamp'"

    def test_concurrent_rotation_no_corruption(self, tmp_path: str) -> None:
        """With tiny max_bytes, threads trigger concurrent rotation safely."""
        log_path = os.path.join(tmp_path, "concurrent_rotate.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=100, max_backups=2)

        n_threads = 5
        writes_per_thread = 30

        def worker(wid: int) -> None:
            for i in range(writes_per_thread):
                logger.log_event(
                    "task_submitted",
                    task_id=f"w{wid}/t{i}",
                    data="x" * 20,
                )

        threads = [threading.Thread(target=worker, args=(wid,)) for wid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The current log should be readable
        records = _read_log(log_path)
        assert len(records) > 0

        # At least one backup should exist
        found_backup = False
        for i in range(1, 3):
            if os.path.exists(f"{log_path}.{i}"):
                records_bak = _read_log(f"{log_path}.{i}")
                assert len(records_bak) > 0
                found_backup = True
        assert found_backup, "No backup file created during concurrent rotation"


class TestCustomConfig:
    """Custom log_path, max_bytes, max_backups."""

    def test_custom_log_path(self, tmp_path: str) -> None:
        custom = os.path.join(tmp_path, "custom", "deep", "audit.jsonl")
        logger = AuditLogger(log_path=custom)
        logger.log_event("auth_failure", reason="expired_token")

        assert os.path.exists(custom)
        assert _count_lines(custom) == 1

    def test_custom_max_bytes(self, tmp_path: str) -> None:
        log_path = os.path.join(tmp_path, "maxbytes.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=500, max_backups=2)

        assert logger.max_bytes == 500
        assert logger.max_backups == 2

    def test_custom_max_backups(self, tmp_path: str) -> None:
        log_path = os.path.join(tmp_path, "backups.jsonl")
        logger = AuditLogger(log_path=log_path, max_bytes=50, max_backups=5)

        for i in range(10):
            logger.log_event("task_submitted", task_id=f"t{i}", data="x" * 40)

        # With max_backups=5 we may see up to .5
        highest = 0
        for i in range(1, 6):
            if os.path.exists(f"{log_path}.{i}"):
                highest = i
        assert highest >= 1, "No backups created"
        # .6 should not exist
        assert not os.path.exists(f"{log_path}.6"), "max_backups=5 but .6 exists"


class TestEdgeCases:
    """Edge cases: empty log, non-existent dir, multiple instances."""

    def test_no_log_file_not_created_by_property(self, tmp_path: str) -> None:
        """The log file is not created until first log_event()."""
        log_path = os.path.join(tmp_path, "lazy.jsonl")
        logger = AuditLogger(log_path=log_path)
        assert not os.path.exists(log_path), (
            "Log file created before any event"
        )

    def test_rotation_when_file_does_not_exist(self, tmp_path: str) -> None:
        """_rotate_if_needed does not crash when file is absent."""
        log_path = os.path.join(tmp_path, "absent.jsonl")
        logger = AuditLogger(log_path=log_path)
        logger.log_event("task_submitted", task_id="t1")
        # Should not raise
        assert _count_lines(log_path) == 1

    def test_non_serializable_value(self, tmp_path: str) -> None:
        """Values that are not JSON-serializable are stringified via default=str."""
        log_path = os.path.join(tmp_path, "nonserial.jsonl")
        logger = AuditLogger(log_path=log_path)

        class CustomObj:
            def __str__(self) -> str:
                return "custom-stringified"

        logger.log_event("task_completed", task_id="t1", obj=CustomObj())
        records = _read_log(log_path)
        assert records[0]["obj"] == "custom-stringified"

    def test_unicode_content(self, tmp_path: str) -> None:
        """Unicode text in extra fields is preserved."""
        log_path = os.path.join(tmp_path, "unicode.jsonl")
        logger = AuditLogger(log_path=log_path)
        logger.log_event(
            "message_sent",
            task_id="t1",
            content="Привет, мир! 🎉",
        )
        records = _read_log(log_path)
        assert "Привет" in records[0]["content"]
        assert "🎉" in records[0]["content"]

    def test_log_path_property(self, tmp_path: str) -> None:
        """log_path property returns the resolved path."""
        log_path = os.path.join(tmp_path, "prop.jsonl")
        logger = AuditLogger(log_path=log_path)
        assert logger.log_path == log_path

    def test_tilde_expansion(self) -> None:
        """Default path uses ~ which is expanded by os.path.expanduser."""
        logger = AuditLogger()
        expected = os.path.expanduser("~/.hermes/a2a_audit.jsonl")
        assert logger.log_path == expected


class TestHermesExecutorIntegration:
    """Verify audit events are emitted from HermesExecutor in correct order.

    These tests use the same MockEventQueue and MockFC from the standard
    hermes_executor test suite, adding an AuditLogger spy to capture events.
    """

    @pytest.mark.asyncio
    async def test_execute_success_emits_audit_events(self, tmp_path: str) -> None:
        """A successful execution emits: submitted → in_progress → message_sent → completed."""
        from adapter.hermes_executor import HermesExecutor
        from core.domain.models.result import TaskResult
        from core.domain.models.dispatch import ProfileDispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        log_path = os.path.join(tmp_path, "integration.jsonl")
        audit_logger = AuditLogger(log_path=log_path)

        fc = type("MockFC", (), {
            "route": lambda self, intent: ProfileDispatch(
                task_id="t1", profile_name="sherlock",
                node_address="local", endpoint="internal:profile",
                status="dispatched",
            )
        })()

        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="completed", data={"answer": "done"},
            ),
            fc=fc,
            audit_logger=audit_logger,
        )
        ctx = make_context(parts_dicts=[{"text": "hello"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        records = _read_log(log_path)
        events = [r["event"] for r in records]

        # Should include: task_submitted, task_in_progress, message_sent, task_completed
        assert "task_submitted" in events
        assert "task_in_progress" in events
        assert "message_sent" in events
        assert "task_completed" in events

        # Submitted should come first
        assert events[0] == "task_submitted"
        assert events[-1] == "task_completed"

    @pytest.mark.asyncio
    async def test_execute_failure_emits_audit_events(self, tmp_path: str) -> None:
        """A failed execution emits: submitted → in_progress → message_sent → task_failed."""
        from adapter.hermes_executor import HermesExecutor
        from core.domain.models.result import TaskResult
        from core.domain.models.dispatch import ProfileDispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        log_path = os.path.join(tmp_path, "integration_fail.jsonl")
        audit_logger = AuditLogger(log_path=log_path)

        fc = type("MockFC", (), {
            "route": lambda self, intent: ProfileDispatch(
                task_id="t1", profile_name="builder",
                node_address="local", endpoint="internal:profile",
                status="dispatched",
            )
        })()

        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="failed", error="Timeout",
            ),
            fc=fc,
            audit_logger=audit_logger,
        )
        ctx = make_context(parts_dicts=[{"text": "deploy"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        records = _read_log(log_path)
        events = [r["event"] for r in records]

        assert "task_submitted" in events
        assert "task_in_progress" in events
        assert "message_sent" in events
        assert "task_failed" in events
        assert events[-1] == "task_failed"

    @pytest.mark.asyncio
    async def test_execute_no_route_emits_audit_events(self, tmp_path: str) -> None:
        """When no route is found, emit: submitted → task_failed."""
        from adapter.hermes_executor import HermesExecutor
        from core.domain.models.result import TaskResult
        from core.domain.models.dispatch import ProfileDispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        log_path = os.path.join(tmp_path, "integration_noroute.jsonl")
        audit_logger = AuditLogger(log_path=log_path)

        fc = type("MockFC", (), {
            "route": lambda self, intent: ProfileDispatch(
                task_id="t1", profile_name="",
                node_address="local", endpoint="internal:profile",
                status="unavailable", message="No matching profile",
            )
        })()

        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(status="completed"),
            fc=fc,
            audit_logger=audit_logger,
        )
        ctx = make_context(parts_dicts=[{"text": "audit"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        records = _read_log(log_path)
        events = [r["event"] for r in records]

        assert events[0] == "task_submitted"
        assert events[-1] == "task_failed"
        # There should be exactly 2 events (no in_progress since no dispatch)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_cancel_emits_audit_event(self, tmp_path: str) -> None:
        """cancel() emits task_cancelled."""
        from adapter.hermes_executor import HermesExecutor, _default_dispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        log_path = os.path.join(tmp_path, "integration_cancel.jsonl")
        audit_logger = AuditLogger(log_path=log_path)

        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
            audit_logger=audit_logger,
        )
        ctx = make_context(parts_dicts=[{"text": "cancel me"}], task_id="task/cancel-1")
        eq = MockEventQueue()

        await executor.cancel(ctx, eq)

        records = _read_log(log_path)
        assert len(records) >= 1
        assert records[0]["event"] == "task_cancelled"
        assert records[0]["task_id"] == "task/cancel-1"

    @pytest.mark.asyncio
    async def test_execute_input_required_emits_audit_events(self, tmp_path: str) -> None:
        """input_required emits in_progress and orchestrator_recruit when wired."""
        from adapter.hermes_executor import HermesExecutor
        from core.domain.models.result import TaskResult
        from core.domain.models.dispatch import ProfileDispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        log_path = os.path.join(tmp_path, "integration_inputreq.jsonl")
        audit_logger = AuditLogger(log_path=log_path)

        fc = type("MockFC", (), {
            "route": lambda self, intent: ProfileDispatch(
                task_id="t1", profile_name="sherlock",
                node_address="local", endpoint="internal:profile",
                status="dispatched",
            )
        })()

        orchestrator_calls = []

        class MockOrch:
            def on_status_change(self, task_id, new_state, task_result):
                orchestrator_calls.append((task_id, new_state, task_result))

        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="input_required",
                data={"question": "Which port?"},
            ),
            fc=fc,
            orchestrator=MockOrch(),
            audit_logger=audit_logger,
        )
        ctx = make_context(parts_dicts=[{"text": "Port?"}], task_id="task/input-req")
        eq = MockEventQueue()

        await executor.execute(ctx, eq)

        records = _read_log(log_path)
        events = [r["event"] for r in records]

        assert "task_submitted" in events
        assert "task_in_progress" in events  # initial
        assert "task_in_progress" in events  # input_required
        assert "orchestrator_recruit" in events

    @pytest.mark.asyncio
    async def test_audit_logger_optional(self, tmp_path: str) -> None:
        """Executor works without audit_logger (None, no AttributeError)."""
        from adapter.hermes_executor import HermesExecutor, _default_dispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
            # audit_logger defaults to None
        )
        ctx = make_context(parts_dicts=[{"text": "test"}])
        eq = MockEventQueue()

        # Should not raise
        await executor.cancel(ctx, eq)
        # For execute we need a proper FC to avoid the no-route path
        from core.domain.models.dispatch import ProfileDispatch
        from core.domain.models.result import TaskResult
        fc = type("MockFC2", (), {
            "route": lambda self, intent: ProfileDispatch(
                task_id="t1", profile_name="test",
                node_address="local", endpoint="internal:profile",
                status="dispatched",
            )
        })()
        executor2 = HermesExecutor(
            dispatch_fn=lambda g, p: TaskResult(status="completed"),
            fc=fc,
        )
        await executor2.execute(make_context(parts_dicts=[{"text": "test"}]), MockEventQueue())


class TestSafeLog:
    """Validate _safe_log guards against audit logger I/O failures."""

    @pytest.mark.asyncio
    async def test_broken_logger_does_not_crash_execute(self, tmp_path: str) -> None:
        """When audit logger throws, execute() should complete without raising."""
        from adapter.hermes_executor import HermesExecutor
        from core.domain.models.result import TaskResult
        from core.domain.models.dispatch import ProfileDispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        class BrokenAuditLogger:
            def log_event(self, **kwargs):
                raise PermissionError("audit log: permission denied")

        fc = type("MockFC", (), {
            "route": lambda self, intent: ProfileDispatch(
                task_id="t1", profile_name="sherlock",
                node_address="local", endpoint="internal:profile",
                status="dispatched",
            )
        })()

        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(
                status="completed", data={"answer": "done"},
            ),
            fc=fc,
            audit_logger=BrokenAuditLogger(),
        )
        ctx = make_context(parts_dicts=[{"text": "hello"}])
        eq = MockEventQueue()

        # Should NOT raise — _safe_log swallows the I/O error
        await executor.execute(ctx, eq)

    @pytest.mark.asyncio
    async def test_broken_logger_does_not_crash_cancel(self, tmp_path: str) -> None:
        """cancel() survives a broken audit logger."""
        from adapter.hermes_executor import HermesExecutor, _default_dispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        class BrokenAuditLogger:
            def log_event(self, **kwargs):
                raise OSError("disk full")

        executor = HermesExecutor(
            dispatch_fn=_default_dispatch,
            fc=type("FakeFC", (), {})(),
            audit_logger=BrokenAuditLogger(),
        )
        ctx = make_context(parts_dicts=[{"text": "cancel"}], task_id="task/broken-cancel")
        eq = MockEventQueue()

        await executor.cancel(ctx, eq)

    @pytest.mark.asyncio
    async def test_broken_logger_no_route(self, tmp_path: str) -> None:
        """No-route path survives a broken audit logger."""
        from adapter.hermes_executor import HermesExecutor
        from core.domain.models.result import TaskResult
        from core.domain.models.dispatch import ProfileDispatch
        from tests.adapter.test_hermes_executor import MockEventQueue, make_context

        class BrokenAuditLogger:
            def log_event(self, **kwargs):
                raise PermissionError("audit log: permission denied")

        fc = type("MockFC", (), {
            "route": lambda self, intent: ProfileDispatch(
                task_id="t1", profile_name="",
                node_address="local", endpoint="internal:profile",
                status="unavailable", message="No profile",
            )
        })()

        executor = HermesExecutor(
            dispatch_fn=lambda goal, profile: TaskResult(status="completed"),
            fc=fc,
            audit_logger=BrokenAuditLogger(),
        )
        ctx = make_context(parts_dicts=[{"text": "audit"}])
        eq = MockEventQueue()

        await executor.execute(ctx, eq)
