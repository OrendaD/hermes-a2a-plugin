#!/usr/bin/env python3
"""Passive mesh health watchdog for the A2A server.

Checks (in order, stop on first failure):
  1. /health endpoint — server liveness
  2. Configured peers from config
  3. Disk space on ~/.hermes/

Passive observer — reports findings, never restarts anything.
Stateless per-tick — no state carried between runs.

Designed to run as a cron job. Stdlib only (yaml and hermes_cli are
available in this environment but not required).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PORT = 9696
DEFAULT_BIND = "127.0.0.1"
HEALTH_TIMEOUT = 5  # seconds
DISK_WARN_MB = 100
DISK_PATH = "~/.hermes"

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _find_config() -> str | None:
    """Locate the Hermes config file.

    Search order:
      1. A2A_CONFIG env var
      2. ~/.config/hermes/config.yaml
      3. ~/.hermes/config.yaml
    Returns the first path that exists, or None.
    """
    candidates = [
        os.environ.get("A2A_CONFIG"),
        os.path.expanduser("~/.config/hermes/config.yaml"),
        os.path.expanduser("~/.hermes/config.yaml"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _load_config_section(path: str) -> dict:
    """Load the ``a2a:`` section from *path* as a plain dict.

    Tries ``yaml.safe_load`` first (fast), then falls back to
    ``hermes_cli.config.load_config`` (the canonical Hermes loader),
    then a last-resort JSON decode (some configs are JSON-compatible).

    Returns an empty dict if all methods fail.
    """
    # --- Attempt 1: PyYAML ---
    try:
        import yaml  # type: ignore[import-untyped]

        with open(path) as f:
            parsed = yaml.safe_load(f)
        if isinstance(parsed, dict):
            return parsed.get("a2a", {}) or {}
    except Exception:
        pass

    # --- Attempt 2: hermes_cli canonical loader ---
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        if isinstance(cfg, dict):
            return cfg.get("a2a", {}) or {}
    except Exception:
        pass

    # --- Attempt 3: JSON decode (simple YAML is often valid JSON) ---
    try:
        with open(path) as f:
            parsed = json.load(f)
        if isinstance(parsed, dict):
            return parsed.get("a2a", {}) or {}
    except Exception:
        pass

    return {}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_health(bind: str, port: int) -> tuple[bool, str]:
    """Check the A2A /health endpoint.

    Returns (ok, detail_string).
    """
    url = f"http://{bind}:{port}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT) as resp:
            body = resp.read().decode()
            if resp.status == 200:
                return True, f"200 OK"
            else:
                return False, f"HTTP {resp.status}: {body[:200]}"
    except urllib.error.URLError as e:
        return False, f"not responding — {e.reason}"
    except Exception as e:
        return False, f"error — {e}"


def check_peers(a2a_cfg: dict) -> tuple[bool, str]:
    """Report configured peers from the a2a config section.

    Returns (True, summary_string).  This check never "fails" per se —
    it just reports what's configured.  We return True as long as we
    can parse the peer list.
    """
    raw_peers = a2a_cfg.get("peers", [])
    if not isinstance(raw_peers, list):
        return True, "unparseable (peers is not a list)"

    names: list[str] = []
    for p in raw_peers:
        if isinstance(p, dict):
            name = p.get("name", str(p))
        else:
            name = str(p)
        names.append(name)

    if not names:
        return True, "0 (none configured)"

    return True, f"{len(names)} ({', '.join(names)})"


def check_disk(disk_path: str) -> tuple[bool, str]:
    """Check free disk space on *disk_path*.

    Returns (ok, detail_string).
    """
    expanded = os.path.expanduser(disk_path)
    try:
        st = os.statvfs(expanded)
    except FileNotFoundError:
        # Path doesn't exist yet — try parent
        parent = os.path.dirname(expanded)
        try:
            st = os.statvfs(parent)
        except Exception as e:
            return False, f"cannot stat — {e}"
    except Exception as e:
        return False, f"cannot stat — {e}"

    free_bytes = st.f_frsize * st.f_bavail
    free_mb = free_bytes / (1024 * 1024)
    free_gb = free_bytes / (1024 * 1024 * 1024)

    if free_mb < DISK_WARN_MB:
        return (
            False,
            f"{free_gb:.0f}GB free ({free_mb:.0f}MB) — ⚠️ below {DISK_WARN_MB}MB threshold",
        )

    return True, f"{free_gb:.0f}GB free"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Run all checks and print a compact summary.  Returns 0 (always)."""
    all_ok = True
    lines: list[str] = []

    # --- Resolve config ---
    config_path = _find_config()
    if config_path is None:
        lines.append("⚠️  A2A watchdog — no config found, using defaults")
        a2a_cfg: dict = {}
    else:
        a2a_cfg = _load_config_section(config_path)

    # Extract settings with defaults
    bind = a2a_cfg.get("bind", DEFAULT_BIND)
    port = int(a2a_cfg.get("port", DEFAULT_PORT))

    # --- Check 1: Health endpoint ---
    ok, detail = check_health(bind, port)
    all_ok = all_ok and ok
    prefix = "✅" if ok else "❌"
    lines.append(f"  {prefix}  /health: {detail}")

    if not ok:
        # Server is down — no point continuing
        lines.insert(0, f"❌ A2A watchdog — server not reachable")
        print("\n".join(lines))
        return 0

    # --- Check 2: Peers ---
    ok, detail = check_peers(a2a_cfg)
    all_ok = all_ok and ok
    prefix = "✅" if ok else "⚠️"
    lines.append(f"  {prefix}  configured peers: {detail}")

    # --- Check 3: Disk ---
    ok, detail = check_disk(DISK_PATH)
    all_ok = all_ok and ok
    prefix = "✅" if ok else "⚠️"
    lines.append(f"  {prefix}  disk ({DISK_PATH}): {detail}")

    # --- Summary header ---
    if all_ok:
        lines.insert(0, "✅ A2A watchdog — all clear")
    else:
        lines.insert(0, f"⚠️  A2A watchdog — issues found")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
