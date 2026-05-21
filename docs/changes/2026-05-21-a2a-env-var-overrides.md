---
title: Environment Variable Config Overrides — Phase 6 Item 5
created: 2026-05-21
type: change
status: complete
phase: 6
tags: [a2a, hardening, config, env-vars]
---

# Config Overrides via Environment Variables

## Problem

Shared config files are checked into git. Per-node differences (node_name, node_id, port, peer API keys) shouldn't require editing YAML. Container deploys need `-e` flags, not volume-mounted config surgery.

## Fix

Added a post-YAML overlay loop in `_read_a2a_config()`. After reading the YAML baseline, each `A2A_<KEY>` env var overrides the matching config entry if present.

**Pattern:**
```
A2A_NODE_NAME=tesla-vps A2A_PORT=9191 python -m hermes agent ...
```

**Type coercion:** `_coerce_env_value()` maps the string env var to the expected Python type — `int` (with `ValueError` on junk), `str` (pass-through), `list` (JSON parse), `bool` (truthy set: `1`, `true`, `yes`).

**Config keys tracked:**
port (int), bind (str), node_name (str), node_id (str), profiles_dir (str), signing_profile (str), rate_limit (int), peers (list)

Unknown `A2A_<KEY>` values are silently ignored — no config-busting surprises.

## Files Modified

- `src/a2a_plugin/__init__.py` — added `CONFIG_KEYS` dict, `_BOOL_TRUE` frozenset, `_coerce_env_value()` helper, overlay loop in `_read_a2a_config()`

## Test File

- `tests/plugin/test_plugin_config.py` — 27 tests (17 coercion, 10 config)

## Test Coverage

- String, int, bool, list coercion (valid, edge cases, errors)
- Base case: no env vars → YAML as-is
- Env var overrides string, int, boolean keys
- `rate_limit=0` via env
- Unknown env var ignored
- Invalid int raises ValueError
- Env wins over YAML baseline

## Test Results

- **344 passed, 2 skipped** (up from 317 — 27 new config tests)
- Zero regressions

## Usage

```bash
# Tesla startup — two overrides
A2A_NODE_NAME=tesla-vps A2A_NODE_ID=tesla-vps hermes-cli

# Proteus startup — different overrides from same config file
A2A_NODE_NAME=proteus A2A_NODE_ID=proteus A2A_PORT=9191 hermes-cli

# Docker
docker run -e A2A_PORT=9191 -e A2A_NODE_NAME=node2 ...
```

## References

- Research: `.hermes/plans/2026-05-21-phase6-research.md` (Item 5 — Config Overrides via Env Vars)
