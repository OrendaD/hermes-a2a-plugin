# A2A Internal — Limitations and Constraints

Discovered during testing 2026-06-29. Document what the system CAN'T do so agents don't fight it.

## Write Approval Gate

**What:** The terminal tool blocks writes to certain paths (dotfiles, sensitive dirs, config files) and requires user approval. In A2A one-shot sessions, there is no user to approve.

**Effect:** One-shot agents cannot write to:
- Wiki files (`~/Documents/Hermes Wiki/`)
- Config files (`~/.hermes/config.yaml`)
- Any path the terminal tool flags as requiring approval

**What works:** One-shot agents CAN write to:
- Inboxes (`~/.hermes/inboxes/*/task-log.md`) via `patch` tool
- Workspace files (`~/webgui-files/`, `~/Documents/Hermes Config/`)
- Memory silos (`~/.memory-hive/hive/agents/*/log.md`)

**Workaround:** Route writes through persistent agents that have full user context.

## One-Shot Agent Amnesia

**What:** Each A2A request creates a fresh agent with no session history, no loaded context, no memory of prior interactions.

**Effect:**
- Agent doesn't know what it discussed last time
- Agent doesn't know what other agents told it
- Agent only knows what's in the current message

**Workaround:** Memory hook convention (see SKILL.md). Initiator logs exchange. Persistent agents handle multi-step workflows.

## No Human in the Loop

**What:** A2A one-shot agents run autonomously. They cannot:
- Ask clarifying questions (no `clarify` tool)
- Request approval for risky actions
- Pause and wait for human input

**Workaround:** Use A2A for well-scoped, unambiguous tasks. For tasks needing clarification, use Telegram/WebUI.

## Context Window Limitations

**What:** Long messages with extensive instructions may get truncated or poorly processed.

**Workaround:** Keep messages focused. One task per message. Reference files by path rather than embedding content.

## No Persistent State Between Calls

**What:** Each SendMessage creates a new conversation. No session persistence across calls.

**Workaround:** Include relevant context in each message. Reference prior exchanges by summary.

## Intent Routing Limitations

**What:** If multiple agents share an intent, first match wins based on registration order.

**Workaround:** Use `metadata.target_profile` for critical tasks. Reserve silent routing for low-stakes queries.

## Cross-Node Limitations

**What:** Requires both nodes online, configured as peers, network connectivity, matching auth tokens.

**Workaround:** Check peer health. Implement retry logic. Use inbox fallback for critical tasks.

## Gateway Restart Required

**What:** A2A config changes require gateway restart to take effect.

**Workaround:** After config changes, restart gateway.
