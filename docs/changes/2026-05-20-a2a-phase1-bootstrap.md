---
title: A2A Plugin — Phase 1 Bootstrap Complete
created: 2026-05-20
type: change
status: complete
tags: [a2a, phase1, config, profiles, plugin]
---

# Phase 1 — Plugin Bootstrap

## Configuration Changes

### Main config.yaml (`~/.hermes/config.yaml`)
- Added `a2a-server` to enabled plugins list
- Added `a2a:` section with:
  - `port: 9696` — standardized across all nodes
  - `bind: "127.0.0.1"` — localhost-only until Phase 2+3
  - `node_name: "tesla-vps"`
  - `node_id: "tesla"`

### Profile a2a: sections added (6 profiles)

| Profile | Intents | Tags |
|---------|---------|------|
| ray | diagnose, consultation | linux, health-check, nginx, diagnostics |
| ops | action_request | deploy, config, systemd, cron, ops |
| reviewer | review, audit | verify, check, audit, review |
| cody | action_request | code, patch, python, feature |
| odin | consultation, research | linux, research, knowledge, arch |
| alex | consultation | wiki, knowledge, archive, documentation |

### Code change
- `src/a2a_plugin/__init__.py`: Changed `DEFAULT_PORT` from 8081 to 9696

## Plugin Infrastructure
- Symlink: `~/.hermes/plugins/a2a-server/` → `~/src/a2a-core/src/a2a_plugin/`
- Package: `a2a-core` pip-installed editable in Hermes venv
- Dependency: `a2a-sdk[http-server,signing,sqlite]` installed in Hermes venv

## Pending
- Gateway restart required to load plugin
- Verify: `hermes plugins list` shows a2a-server
- Verify: `curl http://127.0.0.1:9696/.well-known/agent-card.json` returns valid Agent Card with 6 skills
- Verify: SendMessage dispatch to local profile returns result
