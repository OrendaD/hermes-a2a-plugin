"""Tests for a2a_plugin configuration — env-var overrides + coercion."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from a2a_plugin import (
    CONFIG_KEYS,
    _BOOL_TRUE,
    _coerce_env_value,
    _read_a2a_config,
)

# ---------------------------------------------------------------------------
# _coerce_env_value                                                         #
# ---------------------------------------------------------------------------


class TestCoerceEnvValue:
    """Unit tests for the type-coercion helper."""

    def test_int_positive(self) -> None:
        assert _coerce_env_value("port", "8080", int) == 8080

    def test_int_zero(self) -> None:
        assert _coerce_env_value("rate_limit", "0", int) == 0

    def test_int_negative(self) -> None:
        assert _coerce_env_value("port", "-1", int) == -1

    def test_int_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid integer"):
            _coerce_env_value("port", "abc", int)

    def test_int_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid integer"):
            _coerce_env_value("port", "", int)

    def test_str_plain(self) -> None:
        assert _coerce_env_value("node_name", "my-node", str) == "my-node"

    def test_str_empty(self) -> None:
        assert _coerce_env_value("node_name", "", str) == ""

    def test_str_with_whitespace(self) -> None:
        assert _coerce_env_value("bind", " 0.0.0.0 ", str) == " 0.0.0.0 "

    def test_list_valid(self) -> None:
        payload = [{"name": "peer1", "url": "http://peer1"}]
        assert _coerce_env_value("peers", json.dumps(payload), list) == payload

    def test_list_empty(self) -> None:
        assert _coerce_env_value("peers", "[]", list) == []

    def test_list_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            _coerce_env_value("peers", "not-json", list)

    def test_list_not_array_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON array"):
            _coerce_env_value("peers", '"string"', list)

    def test_list_object_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON array"):
            _coerce_env_value("peers", '{"key": "val"}', list)

    def test_bool_true_variants(self) -> None:
        for val in ("1", "true", "yes", "TRUE", "True", "YES"):
            assert _coerce_env_value("key", val, bool) is True, f"failed on {val!r}"

    def test_bool_false_variants(self) -> None:
        for val in ("0", "false", "no", "FALSE", "False", "NO", "", "other"):
            assert _coerce_env_value("key", val, bool) is False, f"failed on {val!r}"

    def test_bool_with_whitespace(self) -> None:
        assert _coerce_env_value("key", "  true  ", bool) is True
        assert _coerce_env_value("key", "  false  ", bool) is False

    def test_unknown_type_falls_back_to_str(self) -> None:
        """If type is not int/bool/list, treat as string."""
        assert _coerce_env_value("bind", "0.0.0.0", str) == "0.0.0.0"


# ---------------------------------------------------------------------------
# _read_a2a_config — env-var overlay
# ---------------------------------------------------------------------------

# Representative YAML baseline returned by hermes_cli.config.load_config()
_YAML_BASELINE: dict[str, object] = {
    "port": 9090,
    "bind": "0.0.0.0",
    "node_name": "yaml-node",
    "profiles_dir": "/tmp/profiles",
    "node_id": "yaml-id",
    "signing_profile": "default",
    "peers": [{"name": "peer1", "url": "http://peer1"}],
    "rate_limit": 10,
}


def _mock_hermes_config(a2a_section: dict) -> dict:
    """Simulate the return value of ``hermes_cli.config.load_config()``."""
    return {"a2a": a2a_section}


class TestReadA2aConfig:
    """Integration tests for _read_a2a_config with mocked YAML + env vars."""

    # -- base case -----------------------------------------------------------

    def test_no_env_vars_returns_yaml_baseline(self) -> None:
        """No A2A_<KEY> env vars set → returns YAML config unchanged."""
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(os.environ, {}, clear=True):
                result = _read_a2a_config()

        for key in CONFIG_KEYS:
            assert result[key] == _YAML_BASELINE[key], f"Mismatch for {key!r}"

    # -- string override -----------------------------------------------------

    def test_env_overrides_string_key(self) -> None:
        """A2A_NODE_NAME overrides YAML value."""
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(os.environ, {"A2A_NODE_NAME": "env-node"}, clear=True):
                result = _read_a2a_config()

        assert result["node_name"] == "env-node"
        # Other keys unaffected
        assert result["port"] == _YAML_BASELINE["port"]

    # -- int override --------------------------------------------------------

    def test_env_overrides_int_key(self) -> None:
        """A2A_PORT overrides YAML value, coerced to int."""
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(os.environ, {"A2A_PORT": "1234"}, clear=True):
                result = _read_a2a_config()

        assert result["port"] == 1234
        assert isinstance(result["port"], int)

    # -- bool/int edge cases -------------------------------------------------

    def test_env_rate_limit_zero(self) -> None:
        """A2A_RATE_LIMIT=0 overrides YAML value, coered to int 0."""
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(os.environ, {"A2A_RATE_LIMIT": "0"}, clear=True):
                result = _read_a2a_config()

        assert result["rate_limit"] == 0
        assert isinstance(result["rate_limit"], int)

    # -- unknown env var -----------------------------------------------------

    def test_unknown_env_var_ignored(self) -> None:
        """A2A_UNKNOWN (not in CONFIG_KEYS) is silently ignored."""
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(
                os.environ,
                {"A2A_UNKNOWN": "some_value", "A2A_ALSO_UNKNOWN": "42"},
                clear=True,
            ):
                result = _read_a2a_config()

        for key in CONFIG_KEYS:
            assert result[key] == _YAML_BASELINE[key], f"Mismatch for {key!r}"

    # -- YAML + env both set — env wins --------------------------------------

    def test_env_wins_over_yaml(self) -> None:
        """When both YAML and env set the same key, env wins."""
        yaml_with_port = dict(_YAML_BASELINE, port=8888)
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(yaml_with_port)
            with patch.dict(os.environ, {"A2A_PORT": "7777"}, clear=True):
                result = _read_a2a_config()

        assert result["port"] == 7777

    # -- invalid int raises --------------------------------------------------

    def test_invalid_int_env_raises_value_error(self) -> None:
        """A2A_PORT=abc raises ValueError."""
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(os.environ, {"A2A_PORT": "not-a-number"}, clear=True):
                with pytest.raises(ValueError, match="not a valid integer"):
                    _read_a2a_config()

    # -- peers override (list) -----------------------------------------------

    def test_env_overrides_peers_list(self) -> None:
        """A2A_PEERS overrides the peers list via JSON."""
        new_peers = [{"name": "env-peer", "url": "http://env-peer"}]
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(
                os.environ,
                {"A2A_PEERS": json.dumps(new_peers)},
                clear=True,
            ):
                result = _read_a2a_config()

        assert result["peers"] == new_peers

    # -- mixed: multiple env overrides at once -------------------------------

    def test_multiple_env_overrides(self) -> None:
        """Several env vars override different keys simultaneously."""
        env = {
            "A2A_PORT": "4321",
            "A2A_NODE_NAME": "multi-env-node",
            "A2A_RATE_LIMIT": "99",
        }
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = _mock_hermes_config(dict(_YAML_BASELINE))
            with patch.dict(os.environ, env, clear=True):
                result = _read_a2a_config()

        assert result["port"] == 4321
        assert result["node_name"] == "multi-env-node"
        assert result["rate_limit"] == 99
        # Unset keys stay at YAML baseline
        assert result["bind"] == _YAML_BASELINE["bind"]
        assert result["node_id"] == _YAML_BASELINE["node_id"]

    # -- fallback when hermes config is absent -------------------------------

    def test_fallback_defaults_with_env_override(self) -> None:
        """When hermes config load fails, defaults apply + env still overrides."""
        with patch("hermes_cli.config.load_config", side_effect=ImportError("no cfg")):
            with patch.dict(os.environ, {"A2A_PORT": "1111"}, clear=True):
                result = _read_a2a_config()

        assert result["port"] == 1111
        assert result["bind"] == "127.0.0.1"  # DEFAULT_BIND
        assert result["node_name"] == "hermes-a2a-node"
        assert result["rate_limit"] == 0
