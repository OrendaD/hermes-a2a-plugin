# Phase 2 — Core Implementation Plan

## Implementation Order

Cody implements in order: 1 → 2 → 3. Each builds on the previous.

---

## 1. Fleet Controller (`src/core/fleet_controller.py`)

### What it does
Routes `TaskIntent`s to the right profile and node. Stateless — tracks only availability (`_busy` set).

### Lessons from implementation bugs (DO NOT REPEAT)

**Bug A: `_best_match` fell through to "first candidate" as last resort**
- Bad: `return candidates[0] if candidates else None`
- Correct: return `None` when no candidate can handle the intent type (by intent or tag)
- Routing MUST NOT dispatch to a profile that can't handle the intent

**Bug B: Local-preference override ignored capability match**
- Bad: preferred local profile even when it couldn't handle the intent type
- Correct: before preferring local, verify `local_match.can_handle(intent.intent_type)` is True

### Routing priority (exact order)

1. **Explicit `target_profile`**: verify capability + node + availability → dispatch or return error
2. **Explicit `target_node`**: filter candidates to node, find best match
3. **No target**: best match across all profiles. Prefer local ONLY IF local can handle the intent. Fall back to remote.
4. **No match at all**: return `unavailable` — never invent a destination

### Availability logic
- `_busy: set[str]` — profile_name → currently dispatched
- `route()` marks profile busy on successful dispatch
- `release(task_id, profile_name)` marks free
- A busy profile returns `status="no_capacity"`

### Endpoint resolution
- Local: `internal:<profile_name>`
- Remote: `a2a://<node_id>/<profile_name>`

---

## 2. Orchestrator (`src/core/orchestrator.py`)

### What it does
Manages live orchestration flows. Stateful — tracks `ConversationGraph` instances per `context_id`. Injected with `FleetController` + `A2AAdapter`.

### Key lesson

**Bug C: `register_task` didn't capture routing context.**
- Bad: `target_profile` defaulted to empty string. `on_status_change` called `FC.release("", empty_profile)` which released nothing.
- Fix: `register_task` accepts optional `target_profile` and `target_node`. When set, stores them on the `TaskRecord`. `on_status_change` uses them to call `FC.release()`.

### Workflow

**`register_task(task_id, context_id, parent_task_id=None, target_profile=None, target_node=None)`**
- Get or create `ConversationGraph` for `context_id`
- Create `TaskRecord` with routing info from params (or parent if child task)
- Track recursion depth for specialist chain

**`on_status_change(task_id, new_state, task_result)`**
- Update the `TaskRecord` in the graph
- If `input_required`: call `_handle_input_required()`
- If terminal: call `FC.release(task_id, record.target_profile)`

**`_handle_input_required(record, task_result)`**
1. Extract `question` from `task_result.data["question"]`
2. Call `recruit_specialist()`
3. If specialist returned `completed` with no escalation:
   - Compose a `resume` TaskIntent (`intent_type="instruction"`)
   - `resume.payload = {"answer": specialist.data, "resume_task_id": record.task_id}`
   - Send via `adapter.send_task(resume)`
   - Set record status → `"working"`
4. If specialist returned `input_required` with escalation:
   - Mark parent record with escalation metadata
   - Leave status as `input_required`
5. If specialist failed: propagate failure status

**`recruit_specialist(question, source_context_id, parent_task_id, tags=None)`**
- Check depth guard (`MAX_SPECIALIST_DEPTH = 3`)
- Call `FC.discover("consultation", tags)`, fall back to `"action_request"`
- If no candidates: return escalated `input_required`
- Dispatch `TaskIntent` with `target_profile` and `target_node` from first candidate
- Return the specialist's result

---

## 3. Test Fixes — 3 Known Failures to Fix

### Test A: FC routing to remote when no local match
**File:** `tests/core/test_fleet_controller.py`
**Method:** `test_route_to_remote_when_no_local_match`
**Fix:** Already correct after Bug A+B fix. When `intent_type="research"` only odin (remote) matches. FC routes to odin. Just needs to pass.

### Test B: FC routing with unknown intent
**File:** `tests/core/test_fleet_controller.py`
**Method:** `test_route_no_match`
**Fix:** Already correct after Bug A fix. No profile handles `intent_type="sing"`. FC returns `unavailable`. Just needs to pass.

### Test C: FC slot release via orchestrator
**File:** `tests/core/test_orchestrator.py`
**Method:** `test_terminal_state_releases_fc_slot`
**Fix:** Pass `target_profile="ray"` to `orch.register_task()` so the FC release call targets the right profile.

### Test D: on_status_change status assertion
**File:** `tests/core/test_orchestrator.py`
**Method:** `test_on_status_change_known_task`
**Fix:** Pass `new_state="completed"` (not `"working"`) to match the TaskResult status that the test asserts against.

### Test E: Specialist escalation test
**File:** `tests/core/test_orchestrator.py`
**Method:** `test_input_required_no_specialist_escalates`
**Fix:** The sparse FC has ops with `action_request` intent. `recruit_specialist` discovers ops via the `action_request` fallback. Either remove ops from the sparse FC, or set it up so NO profile matches.
- Better fix: create an empty FC with zero registered profiles.

---

## 4. Verification

```bash
cd ~/src/a2a-core && python -m pytest tests/ -v --tb=short

# Boundary rule — must return zero
grep -r "from a2a" src/core/
grep -r "import a2a" src/core/

# Timing — must complete in < 5s
time python -m pytest tests/
```
