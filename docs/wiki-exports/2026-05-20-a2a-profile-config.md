---
title: A2A Profile Config Format — Capability Declaration
created: 2026-05-20
updated: 2026-05-20
type: config
tags: [a2a, plugin, profiles, configuration, discovery]
confidence: high
---

# [2026-05-20] A2A Profile Config Format

**What changed:** Added `a2a:` YAML section to all 6 Hermes profile configs at `~/.hermes/profiles/*/config.yaml`.

**Why:** The A2A plugin's profile discovery (`discover_profiles()` in `adapter/profile_discovery.py`) reads `a2a:` sections from each profile's `config.yaml` to build the routing table (FleetController) and AgentCard. Without this section, profiles are invisible to A2A.

**What it replaced:** Previously no A2A capability metadata existed in profiles. The old v0.2.0 plugin used a flat `a2a.agents` list in `~/.hermes/config.yaml`.

## Format

```yaml
# A2A protocol capabilities (discovered by a2a-server plugin)
a2a:
  intents: ["consultation", "research"]     # which TaskIntent types this profile handles
  tags: ["research", "perception"]          # arbitrary tags for AgentCard skill metadata
  description: "Research and perception agent"  # human-readable
  streaming: false                          # not yet supported
  push: false                               # not yet supported
```

Appended at end of each profile's `config.yaml` (after all existing keys). The `a2a:` section is a top-level YAML key alongside `model:`, `toolsets:`, `agent:`, etc.

## Per-Profile Assignments

| Profile | Intents | Tags | Description |
|---------|---------|------|-------------|
| sherlock | consultation, research | research, perception | Research and perception agent |
| builder | instruction | build, implementation | Build executor |
| doris | review | review, audit, verification | Review and verification agent |
| cua-lord | instruction | computer-use, testing | Computer use test executor |
| wiki-checker | action_request | wiki, audit, check | Wiki convention checker |
| wiki-gardener | instruction | wiki, fix | Wiki fix executor |

## Design Decisions

- **Intents map to existing profile roles** — each profile's `a2a.intents` reflects its SOUL.md purpose (e.g., doris reviews → `review`, builder builds → `instruction`). No new intents invented.
- **`action_request` vs `instruction`** — wiki-checker gets `action_request` (inspection, no side effects) while wiki-gardener gets `instruction` (executes approved changes). This lets the FC split audit vs execute without an extra classification step.
- **Tags dupe profile names** — `tags` carries the profile name plus role keywords. The AgentCard uses tags as skill metadata for A2A discovery; keeping the profile name allows remote nodes to target a specific profile by tag.

## Discovery Mechanism

```python
# adapter/profile_discovery.py
def discover_profiles(profiles_dir, node_id):
    for config_file in profiles_dir.glob("*/config.yaml"):
        config = yaml.safe_load(config_file.read_text())
        a2a_config = config.get("a2a")
        if not a2a_config:
            continue                           # skip profiles without a2a: section
        yield A2ACapability(
            profile_name=config_file.parent.name,
            intents=a2a_config.get("intents", []),
            tags=a2a_config.get("tags", []),
            ...
        )
```

## Verify

```bash
source ~/.hermes/hermes-agent/venv/bin/activate
cd /Users/fleety/webgui-files/a2a-plugin
python -c "
import sys; sys.path.insert(0, 'src')
from adapter.profile_discovery import discover_profiles
caps = list(discover_profiles(os.path.expanduser('~/.hermes/profiles'), node_id='local'))
print(f'{len(caps)} profiles discovered')
for c in caps:
    print(f'  {c.profile_name}: intents={list(c.intents)} tags={c.tags}')
"
```

Expected: 6 profiles, each showing its intents and tags.

## Related

- [[planning/a2a-plugin-v1-m3]] — M3 implementation that consumes this format
- [[config/2026-05-20-a2a-standalone-server]] — Port conflict note: standalone server claims port 9696 before plugin
- `adapter/profile_discovery.py` in `a2a-plugin/src/adapter/`
