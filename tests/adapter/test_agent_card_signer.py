"""Tests for Agent Card signing — key stored in per-profile .env.

All tests use temp directories, never touch the real ~/.hermes.
Test env isolation: each test cleans up A2A_SIGNING_KEY from os.environ.
"""

from __future__ import annotations

import os
import base64
import tempfile
from pathlib import Path

import pytest

from a2a.types import AgentCard, AgentCapabilities

from adapter.agent_card_signer import (
    ensure_keys,
    load_keys,
    create_signer,
    create_verifier,
    ENV_KEY,
)


@pytest.fixture(autouse=True)
def _clean_env():
    """Remove A2A_SIGNING_KEY from os.environ before and after each test."""
    os.environ.pop(ENV_KEY, None)
    yield
    os.environ.pop(ENV_KEY, None)


def _make_test_card() -> AgentCard:
    """Create a minimal AgentCard for testing."""
    return AgentCard(
        name="test-node",
        description="Test node for signing validation",
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )


class TestEnsureKeys:
    def test_generates_key_and_writes_env(self):
        """ensure_keys generates a key and writes it to profile/.env."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            private_pem, public_pem = ensure_keys(profile_dir)

            assert private_pem.strip().startswith("-----BEGIN PRIVATE KEY-----")
            assert public_pem.strip().startswith("-----BEGIN PUBLIC KEY-----")

            env_path = profile_dir / ".env"
            assert env_path.exists()
            content = env_path.read_text(encoding="utf-8")
            assert ENV_KEY in content

    def test_reuses_existing_key(self):
        """Calling ensure_keys twice returns the same key."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            private1, public1 = ensure_keys(profile_dir)
            os.environ.pop(ENV_KEY, None)
            private2, public2 = ensure_keys(profile_dir)

            assert private1 == private2
            assert public1 == public2

    def test_env_file_permissions(self):
        """The .env file gets mode 0o600."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            ensure_keys(profile_dir)
            env_path = profile_dir / ".env"
            mode = env_path.stat().st_mode & 0o777
            assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_appends_to_existing_env(self):
        """If .env already exists with other vars, the key is appended."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            env_path = profile_dir / ".env"
            env_path.write_text(
                "OPENAI_API_KEY=sk-abc123\nSOME_OTHER_VAR=val\n",
                encoding="utf-8",
            )

            private_pem, _ = ensure_keys(profile_dir)

            content = env_path.read_text(encoding="utf-8")
            assert "OPENAI_API_KEY=sk-abc123" in content
            assert ENV_KEY in content
            assert private_pem

    def test_replaces_key_in_existing_env(self):
        """If .env already has A2A_SIGNING_KEY, it's replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            # Write a real key first
            private_orig, _ = ensure_keys(profile_dir)
            os.environ.pop(ENV_KEY, None)

            # Now call again — should load existing, not regenerate
            private_loaded, _ = ensure_keys(profile_dir)
            assert private_loaded == private_orig

    def test_key_round_trip_signing(self):
        """Sign with generated key, verify."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            private_pem, public_pem = ensure_keys(profile_dir)
            signer = create_signer(private_pem)
            verifier = create_verifier(public_pem)

            card = _make_test_card()
            signed = signer(card)
            assert len(signed.signatures) == 1
            verifier(signed)


class TestLoadKeys:
    def test_loads_existing_key(self):
        """load_keys reads back a key written by ensure_keys."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            private_orig, public_orig = ensure_keys(profile_dir)
            os.environ.pop(ENV_KEY, None)

            private_loaded, public_loaded = load_keys(profile_dir)
            assert private_loaded == private_orig
            assert public_loaded == public_orig

    def test_raises_when_no_key(self):
        """load_keys raises FileNotFoundError when no .env exists."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "nobody"
            profile_dir.mkdir(parents=True)

            with pytest.raises(FileNotFoundError, match="signing key"):
                load_keys(profile_dir)

    def test_sign_and_verify_round_trip(self):
        """Full round trip: ensure → load → sign → verify."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "sherlock"
            profile_dir.mkdir(parents=True)

            ensure_keys(profile_dir)
            os.environ.pop(ENV_KEY, None)

            private_pem, public_pem = load_keys(profile_dir)
            signer = create_signer(private_pem)
            verifier = create_verifier(public_pem)

            card = _make_test_card()
            signed = signer(card)
            verifier(signed)

            # Tampered card fails
            signed.name = "tampered"
            with pytest.raises(Exception, match="signature|Signature|invalid"):
                verifier(signed)
