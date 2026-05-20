"""Profile discovery — scans a Hermes profiles directory and builds AgentCapability objects.

Reads config.yaml from each profile subdirectory, extracts the ``a2a:``
section (if present), and constructs AgentCapability domain objects suitable
for Agent Card generation and Fleet Controller registration.

Profiles without an ``a2a:`` section are skipped — they are not A2A-addressable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.domain.models.capability import AgentCapability


def discover_profiles(
    profiles_dir: str | Path,
    node_id: str = "local",
) -> list[AgentCapability]:
    """Scan a Hermes profiles directory and return A2A-capable profiles.

    Args:
        profiles_dir: Path to ``~/.hermes/profiles/`` or equivalent.
        node_id: The node identifier for this Hermes instance.

    Returns:
        List of AgentCapability objects, one per profile that declares
        an ``a2a:`` section in its ``config.yaml``.
    """
    base = Path(profiles_dir)
    if not base.is_dir():
        return []

    capabilities: list[AgentCapability] = []

    for profile_dir in sorted(base.iterdir()):
        if not profile_dir.is_dir():
            continue

        config_path = profile_dir / "config.yaml"
        if not config_path.exists():
            continue

        a2a_config = _read_a2a_config(config_path)
        if a2a_config is None:
            continue

        display_name = _read_display_name(profile_dir)

        capabilities.append(
            AgentCapability(
                profile_name=profile_dir.name,
                node_id=node_id,
                display_name=display_name or profile_dir.name,
                description=a2a_config.get("description", ""),
                intents=a2a_config.get("intents", []),
                tags=a2a_config.get("tags", []),
                examples=a2a_config.get("examples", []),
                input_modes=a2a_config.get("input_modes", ["text"]),
                output_modes=a2a_config.get("output_modes", ["text"]),
                supports_streaming=a2a_config.get("streaming", False),
                supports_push=a2a_config.get("push", False),
            )
        )

    return capabilities


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _read_a2a_config(config_path: Path) -> Optional[dict]:
    """Parse the ``a2a:`` section from a profile's config.yaml.

    Returns None if the section is missing or empty.
    """
    import yaml

    try:
        raw = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    try:
        config = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None

    if not isinstance(config, dict):
        return None

    a2a = config.get("a2a")
    if not isinstance(a2a, dict):
        return None

    # Must have at least one intent to be A2A-addressable
    if not a2a.get("intents"):
        return None

    return a2a


def _read_display_name(profile_dir: Path) -> Optional[str]:
    """Extract a display name from SOUL.md frontmatter, if present.

    SOUL.md is plain markdown (no YAML frontmatter in current Hermes profiles).
    We check for a ``***Name***`` first-line convention used by some profiles,
    then fall back to the first heading ``# Name``, then return None.
    """
    soul_path = profile_dir / "SOUL.md"
    if not soul_path.exists():
        return None

    try:
        text = soul_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Try ***Name*** convention (Doris, Ray profiles)
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("***"):
            # Name is the first ***...*** segment on the line
            rest = stripped[3:]
            if "***" in rest:
                name = rest.split("***")[0].strip()
                if name:
                    return name

    # Try # Name heading
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()

    return None
