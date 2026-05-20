"""Tests for profile discovery — zero production files, uses temp directory."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from adapter.profile_discovery import discover_profiles, _read_display_name


class TestDiscoverProfiles:
    def test_empty_directory(self):
        """An empty profiles directory returns an empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            results = discover_profiles(tmp)
        assert results == []

    def test_profile_without_config_skipped(self):
        """A profile subdirectory without config.yaml is skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "test-agent"
            profile_dir.mkdir()
            results = discover_profiles(tmp)
        assert results == []

    def test_profile_without_a2a_section_skipped(self):
        """A profile with config.yaml but no a2a: section is skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "test-agent"
            profile_dir.mkdir()
            (profile_dir / "config.yaml").write_text(
                "model: claude-sonnet-4\nprovider: anthropic\n"
            )
            results = discover_profiles(tmp)
        assert results == []

    def test_profile_with_empty_a2a_skipped(self):
        """A profile with an empty a2a: section is skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "test-agent"
            profile_dir.mkdir()
            (profile_dir / "config.yaml").write_text(
                "model: claude-sonnet-4\na2a:\n  intents: []\n"
            )
            results = discover_profiles(tmp)
        assert results == []

    def test_valid_profile_returns_capability(self):
        """A profile with a valid a2a: section returns one AgentCapability."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir()
            (profile_dir / "config.yaml").write_text("""\
model: claude-sonnet-4
provider: anthropic
a2a:
  intents: ["consultation", "research"]
  tags: ["research", "perception"]
  description: "Perception and research specialist"
  streaming: false
  push: false
""")
            results = discover_profiles(tmp)

        assert len(results) == 1
        cap = results[0]
        assert cap.profile_name == "sherlock"
        assert cap.node_id == "local"
        assert cap.intents == ["consultation", "research"]
        assert cap.tags == ["research", "perception"]
        assert not cap.supports_streaming
        assert not cap.supports_push

    def test_node_id_passthrough(self):
        """The node_id parameter is passed through to AgentCapability."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "remote-agent"
            profile_dir.mkdir()
            (profile_dir / "config.yaml").write_text("""\
model: claude-sonnet-4
a2a:
  intents: ["consultation"]
""")
            results = discover_profiles(tmp, node_id="100.96.0.5")

        assert len(results) == 1
        assert results[0].node_id == "100.96.0.5"

    def test_multiple_profiles(self):
        """Multiple profiles are all discovered."""
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("sherlock", "builder", "doris"):
                profile_dir = Path(tmp) / name
                profile_dir.mkdir()
                (profile_dir / "config.yaml").write_text(f"""\
model: claude-sonnet-4
a2a:
  intents: ["consultation"]
  description: "{name} profile"
""")
            results = discover_profiles(tmp)

        assert len(results) == 3
        names = {c.profile_name for c in results}
        assert names == {"sherlock", "builder", "doris"}

    def test_invalid_yaml_skipped(self):
        """A profile with invalid YAML is silently skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "broken"
            profile_dir.mkdir()
            (profile_dir / "config.yaml").write_text("invalid: [yaml\n  bad: indent\n")
            results = discover_profiles(tmp)
        assert results == []


class TestReadDisplayName:
    def test_no_soul_file(self):
        """No SOUL.md returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _read_display_name(Path(tmp))
        assert result is None

    def test_convention_style(self):
        """***Name*** convention is parsed."""
        with tempfile.TemporaryDirectory() as tmp:
            soul = Path(tmp) / "SOUL.md"
            soul.write_text("***Sherlock*** — perception and research agent.\n\nMore content.\n")
            result = _read_display_name(Path(tmp))
        assert result == "Sherlock"

    def test_heading_fallback(self):
        """# Name heading is used when no ***Name*** found."""
        with tempfile.TemporaryDirectory() as tmp:
            soul = Path(tmp) / "SOUL.md"
            soul.write_text("# Builder\n\nAgent profile for code generation.\n")
            result = _read_display_name(Path(tmp))
        assert result == "Builder"

    def test_prefers_convention_over_heading(self):
        """***Name*** convention takes priority over # heading."""
        with tempfile.TemporaryDirectory() as tmp:
            soul = Path(tmp) / "SOUL.md"
            soul.write_text("***Doris*** — AI reviewer.\n\n# Doris\n\nMore info.\n")
            result = _read_display_name(Path(tmp))
        assert result == "Doris"
