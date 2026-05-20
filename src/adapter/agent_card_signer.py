"""Agent Card signing — key management via per-profile .env files.

Keys stored as base64-encoded PEM in ``~/.hermes/profiles/<name>/.env``.
Single-line, dotenv-safe, cross-platform.

On first use: generates EC P-256 key, base64-encodes PEM, writes to
the profile's ``.env``. On subsequent loads: reads ``A2A_SIGNING_KEY``,
base64-decodes to PEM.
"""

from __future__ import annotations

import base64
import fcntl
import os
from pathlib import Path
from typing import Callable, Optional

from a2a.types import AgentCard
from a2a.utils.signing import (
    create_agent_card_signer,
    create_signature_verifier,
    ProtectedHeader,
)


ENV_KEY = "A2A_SIGNING_KEY"

DEFAULT_ALGORITHM = "ES256"
DEFAULT_KEY_ID = "a2a-key-v1"


def ensure_keys(profile_dir: str | Path) -> tuple[str, str]:
    """Generate or load the signing key pair for a profile.

    If ``A2A_SIGNING_KEY`` is already set in the environment (via
    the profile's ``.env``), loads and returns it.
    Otherwise, generates a new EC P-256 key, base64-encodes the PEM,
    writes to ``<profile>/.env``, loads into ``os.environ``, and returns.

    Args:
        profile_dir: Path to the profile directory
            (e.g. ``~/.hermes/profiles/sherlock``).

    Returns:
        Tuple of (private_pem, public_pem) as strings.
    """
    profile_path = Path(profile_dir)
    env_path = profile_path / ".env"

    # Load the profile's .env into os.environ if it exists
    if env_path.exists():
        _load_env_file(env_path)

    # Check if key is already loaded
    b64_pem = os.environ.get(ENV_KEY)
    if b64_pem and b64_pem.strip():
        private_pem = _decode_key(b64_pem)
        public_pem = _derive_public_pem(private_pem)
        return private_pem, public_pem

    # Acquire exclusive lock on the .env file to prevent concurrent
    # generate-and-write races.  If multiple processes start simultaneously,
    # only one generates — the rest fall through to the load path after
    # the lock is released.
    lock_path = env_path.with_name(".env.lock")
    try:
        lock_fd = os.open(
            str(lock_path), os.O_CREAT | os.O_RDWR, 0o600
        )
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Re-check after acquiring lock — the other thread may have
        # written the key while we were waiting.
        if env_path.exists():
            _load_env_file(env_path)
        b64_pem = os.environ.get(ENV_KEY)
        if b64_pem and b64_pem.strip():
            private_pem = _decode_key(b64_pem)
            public_pem = _derive_public_pem(private_pem)
            os.close(lock_fd)
            return private_pem, public_pem

        # Generate new key pair
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        priv_key = ec.generate_private_key(ec.SECP256R1())
        private_pem = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        public_pem = priv_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        # Base64-encode the PEM (single line for .env compatibility)
        b64_pem = base64.b64encode(private_pem.encode("utf-8")).decode("ascii")
        line = f"{ENV_KEY}={b64_pem}\n"

        # Write to profile's .env
        env_path.parent.mkdir(parents=True, exist_ok=True)
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            if f"{ENV_KEY}=" in content:
                lines = content.split("\n")
                new_lines = [l for l in lines if not l.startswith(f"{ENV_KEY}=")]
                new_lines.append(line.strip())
                env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            else:
                with open(env_path, "a", encoding="utf-8") as f:
                    f.write(line)
        else:
            env_path.write_text(line, encoding="utf-8")

        env_path.chmod(0o600)

        # Load into environment for this process
        os.environ[ENV_KEY] = b64_pem

    finally:
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    return private_pem, public_pem


def load_keys(profile_dir: str | Path) -> tuple[str, str]:
    """Load an existing key pair from a profile's .env.

    Args:
        profile_dir: Path to the profile directory.

    Returns:
        Tuple of (private_pem, public_pem) as strings.

    Raises:
        FileNotFoundError: If ``A2A_SIGNING_KEY`` is not set in env
            and no ``.env`` file exists.
    """
    profile_path = Path(profile_dir)
    env_path = profile_path / ".env"

    if env_path.exists():
        _load_env_file(env_path)

    b64_pem = os.environ.get(ENV_KEY)
    if not b64_pem:
        raise FileNotFoundError(
            f"No signing key found for profile '{profile_path.name}'. "
            f"Set {ENV_KEY} in {env_path} or run ensure_keys()."
        )

    private_pem = _decode_key(b64_pem)
    public_pem = _derive_public_pem(private_pem)
    return private_pem, public_pem


def create_signer(
    private_pem: str,
    key_id: str = DEFAULT_KEY_ID,
    algorithm: str = DEFAULT_ALGORITHM,
) -> Callable[[AgentCard], AgentCard]:
    """Create a signing function for an AgentCard.

    Args:
        private_pem: PEM-encoded private key (PKCS8 format).
        key_id: Key identifier for the ``kid`` JWS header.
        algorithm: JWS algorithm (default ``ES256``).

    Returns:
        A callable that takes an AgentCard and returns a signed AgentCard.
    """
    return create_agent_card_signer(
        signing_key=private_pem,
        protected_header=ProtectedHeader(
            kid=key_id,
            alg=algorithm,
        ),
    )


def create_verifier(
    public_pem: str,
    algorithms: Optional[list[str]] = None,
) -> Callable[[AgentCard], None]:
    """Create a signature verification function for an AgentCard.

    Args:
        public_pem: PEM-encoded public key.
        algorithms: Accepted JWS algorithms (default ``["ES256"]``).

    Returns:
        A callable that takes an AgentCard and raises on invalid signature.
    """
    if algorithms is None:
        algorithms = ["ES256"]

    def _key_provider(kid: Optional[str], jku: Optional[str]) -> str:
        return public_pem

    return create_signature_verifier(_key_provider, algorithms)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _load_env_file(env_path: Path) -> None:
    """Load a ``KEY=VALUE`` file into ``os.environ``.

    No python-dotenv dependency. Handles quoted values and
    ignores comments and blank lines.
    """
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = env_path.read_text(encoding="latin-1")
        except OSError:
            return
    except OSError:
        return

    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes if present
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ[key] = value


def _decode_key(b64_pem: str) -> str:
    """Base64-decode a PEM string."""
    import binascii
    try:
        pem_bytes = base64.b64decode(b64_pem, validate=True)
        return pem_bytes.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(
            f"{ENV_KEY} is not valid base64-encoded PEM: {exc}"
        ) from exc


def _derive_public_pem(private_pem: str) -> str:
    """Derive the public key PEM from a private key PEM."""
    from cryptography.hazmat.primitives import serialization
    private_key = serialization.load_pem_private_key(
        private_pem.encode("utf-8"),
        password=None,
    )
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
