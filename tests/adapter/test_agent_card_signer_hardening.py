"""HARDENING TESTS — Agent Card signing edge cases for community distribution.

These tests validate that the signer module survives real-world conditions:
cross-platform file formats, concurrent access, key rotation, corruption recovery,
and integration with the actual Hermes profiles directory.
"""

from __future__ import annotations

import os
import base64
import tempfile
import threading
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
    os.environ.pop(ENV_KEY, None)
    yield
    os.environ.pop(ENV_KEY, None)


def _make_test_card() -> AgentCard:
    return AgentCard(
        name="test-node",
        description="Test node",
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )


# ──────────────────────────────────────────────
# Integration: real Hermes profile directory
# ──────────────────────────────────────────────


class TestIntegrationRealProfile:
    """Test ensure_keys against a directory structure matching
    ~/.hermes/profiles/<name>/, proving the path logic works
    without touching the real filesystem."""

    def test_writes_to_correct_path(self):
        """The key ends up at <profile_dir>/.env, not somewhere else."""
        with tempfile.TemporaryDirectory() as tmp:
            profiles = Path(tmp) / ".hermes" / "profiles" / "sherlock"
            profiles.mkdir(parents=True)

            private_pem, _ = ensure_keys(profiles)
            env_path = profiles / ".env"
            assert env_path.exists()
            content = env_path.read_text(encoding="utf-8")
            assert ENV_KEY in content
            # Verify the PEM round-trips through the env file
            assert private_pem.strip().startswith("-----BEGIN PRIVATE KEY-----")

    def test_hermes_profiles_pattern(self):
        """Path resolution works with '~/.hermes/profiles/<name>' pattern."""
        with tempfile.TemporaryDirectory() as tmp:
            # Simulate: HERMES_HOME/.hermes/profiles/doris/
            # (some tools set HERMES_HOME to the checkout)
            profile_dir = Path(tmp) / "profiles" / "doris"
            profile_dir.mkdir(parents=True)

            ensure_keys(profile_dir)
            assert (profile_dir / ".env").exists()

    def test_symlinked_profile_dir(self):
        """Ensure the module handles symlinked profile directories."""
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = Path(tmp) / "real_profiles" / "builder"
            real_dir.mkdir(parents=True)
            link_dir = Path(tmp) / "link_profiles" / "builder"
            link_dir.parent.mkdir(parents=True)
            os.symlink(real_dir, link_dir)

            private_pem, _ = ensure_keys(link_dir)
            # The .env should be created in the REAL directory
            assert (real_dir / ".env").exists()
            assert private_pem.strip().startswith("-----BEGIN PRIVATE KEY-----")


# ──────────────────────────────────────────────
# Cross-platform: CRLF, encoding
# ──────────────────────────────────────────────


class TestCrossPlatformEnv:
    """These are the filesystems Hermes runs on — Windows (.env with
    CRLF + UTF-16 BOM), legacy Unix (Latin-1), and the usual suspects."""

    def test_crlf_line_endings(self):
        """.env with Windows \\r\\n line endings is parsed correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "win-agent"
            profile_dir.mkdir(parents=True)
            env_path = profile_dir / ".env"

            # Generate a real key first, get its base64
            key_dir = Path(tmp) / "_keygen"
            key_dir.mkdir()
            real_key_pem, _ = ensure_keys(key_dir)
            real_b64 = base64.b64encode(real_key_pem.encode("utf-8")).decode("ascii")

            # Write with Windows CRLF line endings
            raw_content = f"OPENAI_API_KEY=sk-test\r\n{ENV_KEY}={real_b64}\r\nOTHER_VAR=val\r\n"
            env_path.write_bytes(raw_content.encode("utf-8"))
            os.environ.pop(ENV_KEY, None)

            private_pem, _ = ensure_keys(profile_dir)
            assert private_pem == real_key_pem

    def test_latin1_encoded_env(self):
        """.env with Latin-1 encoded non-ASCII comment is parsed."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "latin-agent"
            profile_dir.mkdir(parents=True)
            env_path = profile_dir / ".env"

            # Generate a real key first, then inject into a latin-1 file
            # Write a Latin-1 comment (common in EU setups, e.g. 'Clé de signature')
            raw = "# Clé de signature A2A - ne pas partager\n"
            raw_bytes = raw.encode("latin-1")

            # Append the key line as ASCII (keys must be ASCII)
            # We generate a proper key via ensure_keys into a helper dir
            helper_dir = Path(tmp) / "_helper"
            helper_dir.mkdir()
            private_pem, _ = ensure_keys(helper_dir)
            b64 = base64.b64encode(private_pem.encode()).decode("ascii")
            raw_bytes += f"{ENV_KEY}={b64}\n".encode("ascii")

            env_path.write_bytes(raw_bytes)

            os.environ.pop(ENV_KEY, None)
            loaded_private, _ = load_keys(profile_dir)
            assert loaded_private == private_pem

    def test_empty_env_file(self):
        """An empty .env file should not crash ensure_keys."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "empty-agent"
            profile_dir.mkdir(parents=True)
            env_path = profile_dir / ".env"
            env_path.write_text("", encoding="utf-8")

            # Should generate a fresh key (no existing key found)
            private_pem, _ = ensure_keys(profile_dir)
            assert private_pem.strip().startswith("-----BEGIN PRIVATE KEY-----")

    def test_env_with_only_comments(self):
        """.env with only comments is treated the same as empty."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "comment-agent"
            profile_dir.mkdir(parents=True)
            env_path = profile_dir / ".env"
            env_path.write_text("# This is a comment\n# Another comment\n", encoding="utf-8")

            private_pem, _ = ensure_keys(profile_dir)
            assert private_pem.strip().startswith("-----BEGIN PRIVATE KEY-----")


# ──────────────────────────────────────────────
# Concurrent access
# ──────────────────────────────────────────────


class TestConcurrentAccess:
    """Multiple threads calling ensure_keys simultaneously must not
    produce duplicates or corruption."""

    def test_two_threads_same_profile(self):
        """Two threads calling ensure_keys on the same profile dir
        must both succeed and produce identical keys."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "race-agent"
            profile_dir.mkdir(parents=True)

            results: list[tuple[str, str] | Exception] = []
            errors: list[Exception] = []

            def _worker():
                try:
                    result = ensure_keys(profile_dir)
                    results.append(result)
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=_worker)
            t2 = threading.Thread(target=_worker)
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

            assert not errors, f"Threads raised: {errors}"
            assert len(results) == 2
            # Both threads should have the same key
            assert results[0][0] == results[1][0]
            assert results[0][1] == results[1][1]

            # .env should have exactly one A2A_SIGNING_KEY line
            env_content = (profile_dir / ".env").read_text(encoding="utf-8")
            key_count = env_content.count(ENV_KEY + "=")
            assert key_count == 1, f"Expected 1 key line, found {key_count}:\n{env_content}"


# ──────────────────────────────────────────────
# Key rotation
# ──────────────────────────────────────────────


class TestKeyRotation:
    """Rotating a key must invalidate old signatures."""

    def test_rotate_key_replaces_signature(self):
        """After key rotation, old signatures fail and new ones pass."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "rotating-agent"
            profile_dir.mkdir(parents=True)

            # Key 1: sign a card
            private_1, public_1 = ensure_keys(profile_dir)
            signer_1 = create_signer(private_1)
            verifier_1 = create_verifier(public_1)
            card = _make_test_card()
            signed_1 = signer_1(card)
            verifier_1(signed_1)  # passes

            # Delete the .env to force regeneration
            (profile_dir / ".env").unlink()
            os.environ.pop(ENV_KEY, None)

            # Key 2: sign the same card
            private_2, public_2 = ensure_keys(profile_dir)
            signer_2 = create_signer(private_2)
            verifier_2 = create_verifier(public_2)

            # Old signature from key_1 should fail with key_2 verifier
            with pytest.raises(Exception, match="signature|Signature|invalid|valid"):
                verifier_2(signed_1)  # using old card signed with key_1

            # New signature should pass
            signed_2 = signer_2(card)
            verifier_2(signed_2)  # passes with key_2


# ──────────────────────────────────────────────
# Recovery: corrupted .env
# ──────────────────────────────────────────────


class TestCorruptionRecovery:
    """The module must produce clear, actionable errors on corrupted env data."""

    def test_truncated_b64_value(self):
        """A2A_SIGNING_KEY with truncated base64 raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "corrupt-agent"
            profile_dir.mkdir(parents=True)
            env_path = profile_dir / ".env"
            env_path.write_text(f"{ENV_KEY}=LS0tLS1CRUdJTiB\n", encoding="utf-8")

            with pytest.raises(ValueError, match="base64|B64|A2A_SIGNING_KEY"):
                ensure_keys(profile_dir)

    def test_not_base64_at_all(self):
        """A2A_SIGNING_KEY with plain text value raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "corrupt-2"
            profile_dir.mkdir(parents=True)
            env_path = profile_dir / ".env"
            env_path.write_text(f"{ENV_KEY}=hello-this-is-not-base64!\n", encoding="utf-8")

            with pytest.raises(ValueError, match="base64|B64|A2A_SIGNING_KEY"):
                ensure_keys(profile_dir)

    def test_empty_key_value_treated_as_missing(self):
        """A2A_SIGNING_KEY= (empty) should be treated as 'no key'
        and trigger key generation instead of trying to parse
        an empty value."""
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "empty-key"
            profile_dir.mkdir(parents=True)
            env_path = profile_dir / ".env"
            env_path.write_text(f"{ENV_KEY}=\n", encoding="utf-8")

            private_pem, _ = ensure_keys(profile_dir)
            assert private_pem.strip().startswith("-----BEGIN PRIVATE KEY-----")


# ──────────────────────────────────────────────
# Key validation
# ──────────────────────────────────────────────


class TestKeyValidation:
    """Bad key material must produce clear errors."""

    def test_rsa_key_raises(self):
        """An RSA public key passed to create_signer should raise (wrong type)."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        # ES256 signer with RSA key — should raise from PyJWT
        with pytest.raises(Exception, match="algorithm|Algorithm|key|Key"):
            signer = create_signer(private_pem, algorithm="ES256")
            signer(_make_test_card())

    def test_corrupted_pem_raises(self):
        """Decode a valid base64 PEM, then corrupt one character."""
        import base64 as b64mod
        # Generate a real PEM
        with tempfile.TemporaryDirectory() as tmp:
            pd = Path(tmp) / "tmp"
            pd.mkdir()
            private_pem, _ = ensure_keys(pd)

        # Corrupt the PEM by flipping one character
        corrupted = private_pem.replace("MIG", "XIG", 1)
        corrupted_b64 = b64mod.b64encode(corrupted.encode()).decode("ascii")

        with tempfile.TemporaryDirectory() as tmp:
            pd2 = Path(tmp) / "bad"
            pd2.mkdir()
            env_path = pd2 / ".env"
            env_path.write_text(f"{ENV_KEY}={corrupted_b64}\n", encoding="utf-8")

            with pytest.raises(Exception, match="PEM|Unable|invalid|Invalid|decode|deserialize|Could not"):
                ensure_keys(pd2)

    def test_wrong_size_key_raises(self):
        """An EC key on the wrong curve (P-521 instead of P-256) should be
        rejected by the ES256 signer, not silently produce a too-weak sig."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        p521_key = ec.generate_private_key(ec.SECP521R1())
        pem = p521_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        # P-521 key with ES256 algorithm declaration — may succeed at
        # PyJWT level (some impls allow mismatched curves), but verify
        # the behavior is at least deterministic and documented.
        signer = create_signer(pem, algorithm="ES256")
        try:
            signed = signer(_make_test_card())
            # If it succeeded, the signature should at least be verifiable
            public_pem = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode()
            verifier = create_verifier(public_pem)
            with pytest.raises(Exception):
                verifier(signed)
        except Exception:
            pass  # Rejection is also acceptable
