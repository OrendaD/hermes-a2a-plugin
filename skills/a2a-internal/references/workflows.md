# A2A Internal — Collaboration Patterns

Real workflows tested 2026-06-29. Each pattern has a trigger, flow, and verification.

## Pattern 1: Research Consultation

**Trigger:** Agent needs information outside its expertise mid-task.

```
Atlas ──A2A──> Sherlock (target_profile: sherlock)
                   │
              Sherlock researches, responds
                   │
Atlas <──A2A──── Sherlock (response)
```

**Use when:** You need subject-matter expertise and don't have it yourself.

**Example:**
- Atlas asks Sherlock about A2A architecture decisions
- Sherlock reads source code, provides analysis, proposes fixes
- Atlas integrates findings into ongoing work

**Key:** `metadata.target_profile: "sherlock"` ensures the right agent handles it.

## Pattern 2: Task Handoff

**Trigger:** Agent needs a specialist to execute a defined task.

```
Atlas ──A2A──> Wiki-gardener (target_profile: wiki-gardener, intent_type: instruction)
                   │
              Wiki-gardener executes, responds
                   │
Atlas <──A2A──── Wiki-gardener (confirmation)
```

**Use when:** Task is well-scoped, specialist is known, no discussion needed.

**Example:**
- Atlas asks Wiki-gardener to clean up a wiki file
- Wiki-gardener executes and confirms

**Key:** Must set `intent_type: "instruction"` if target only handles that intent.

## Pattern 3: Wiki Update Pipeline

**Trigger:** Content needs to go into the wiki.

```
Atlas ──A2A──> Poe (target_profile: poe)
                   │
              Poe writes to standard, hands to Wiki-gardener
                   │
Poe ──inbox──> Wiki-gardener (filing task)
                   │
              Wiki-gardener indexes and files
```

**Use when:** Any wiki content creation or update.

**Example:**
- Atlas sends change spec to Poe via A2A
- Poe's one-shot agent reads spec, routes to Poe's persistent inbox
- When Poe wakes, applies changes, hands to Wiki-gardener

**Key:** One-shot agents can't write to wiki directly (write approval gate). Always route through persistent agent.

## Pattern 4: Cross-Agent Discussion

**Trigger:** Need back-and-forth on a design or architecture question.

```
Atlas ──A2A──> Agent (target_profile, multiple turns)
                   │
              Agent responds with analysis
                   │
Atlas ──A2A──> Agent (follow-up, challenges/rebuilds on points)
                   │
              Agent responds with refined position
                   │
Atlas <──── multiple rounds ────> Agent
```

**Use when:** The question is complex, needs multiple perspectives, or requires iteration.

**Example:**
- Atlas sends 3 questions to Sherlock about A2A design
- Sherlock responds with detailed analysis
- Atlas pushes back on specific points
- Sherlock reads source code, concedes and refines

**Key:** Each turn is a separate SendMessage. Context is per-conversation (contextId), not persistent.

## Pattern 5: Silent Routing (no targeting)

**Trigger:** You don't care which agent handles it, just need the right capability.

```
Caller ──A2A──> Fleet Controller (no target_profile)
                   │
              Best-match by intent type
                   │
              Selected agent executes
                   │
Caller <──A2A──── Selected agent
```

**Use when:** You need "someone who handles consultation" and don't have a preference.

**Example:**
- Generic question about system status
- Fleet controller picks the best match

**Risk:** May route to wrong agent if intent keywords overlap. Use targeting for critical tasks.

## Anti-Patterns

### Don't: One-shot agent writes to wiki
The write approval gate blocks it. Route through persistent agent instead.

### Don't: One-shot agent writes to protected paths
Same issue — no user to approve. Use inboxes or workspace paths.

### Don't: Assume one-shot agent remembers context
Each request is a fresh agent. No session history. Use message context for continuity.

### Don't: Forget intent_type override
If target only handles specific intents (e.g., wiki-gardener only handles "instruction"), you must set `intent_type` in metadata.
