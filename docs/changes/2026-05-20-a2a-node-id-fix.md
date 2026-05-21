---
title: Config fix — node_id must be "local" for correct routing
created: 2026-05-20
type: change
status: complete
tags: [a2a, config, routing, bugfix]
---

# Config Fix: node_id Must Be "local"

## The Bug

The A2A config had `node_id: "tesla"`. The endpoint helper in `FleetController` checks `cap.node_id == "local"` to distinguish local profiles from remote peers. Because profiles were registered with `node_id="tesla"`, the check failed and every dispatch looked remote.

The fix: `node_id` must be the sentinel string `"local"` for all profiles on the local node. It's not a display name — it's a routing discriminator.

## Correction

~/.hermes/config.yaml: `node_id: "tesla"` → `node_id: "local"`

## Lesson

`node_id` in the A2A config is a routing sentinel, not a node identity label. `node_name` holds the human-readable name.
