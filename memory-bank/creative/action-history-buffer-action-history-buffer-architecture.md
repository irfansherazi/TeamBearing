# Architecture: Action History Buffer

## Decision
**Chosen**: Option 2 — Evaluator-Owned Append with Plain List in VQAState
**Rationale**: Minimises cross-module coupling, leverages the existing evaluator ownership pattern for failure tracking, and avoids introducing new reducer complexity into the LangGraph state machine.

---

## Problem Scope

| Concern | Detail |
|---------|--------|
| **Components affected** | `state.py`, `evaluator.py`, `planner.py` |
| **Data contract** | New `action_history_buffer: list[dict]` field on `VQAState` |
| **Write sites** | Evaluator failure path (append), evaluator advance paths (clear) |
| **Read sites** | Planner `_build_past_actions_block()` → prompt injection |
| **Integration points** | PromptBudget v2 slot system, `SYSTEM_PROMPT_TEMPLATE` v1 |
| **Quality attributes** | Testability (pure functions), maintainability (no reducer), zero regression |

### Constraints
- **LangGraph reducer model**: `operator.add` lists grow unboundedly — the buffer must be capped at 5.
- **Evaluator is the sole routing authority**: All failure/advance state writes go through `evaluator_node`.
- **Planner prompt budget**: New block must fit within the existing `PromptBudget` ceiling without evicting critical sections.
- **Dual prompt paths**: Both `_build_system_prompt` (v1) and `_build_system_prompt_v2` (v2) must inject the block.

---

## Options Explored

### Option 1 — Reducer-Annotated List with `_capped_add`

**Pattern**: Define a custom reducer `_capped_add(a, b) → list` that automatically caps the combined list at 5 entries (evicting from the front). Annotate `action_history_buffer` with `Annotated[list[dict], _capped_add]`.

**Data flow**:
```
evaluator_node returns {"action_history_buffer": [new_entry]}
                           ↓
LangGraph calls _capped_add(existing, [new_entry])
                           ↓
Returns existing + [new_entry], trimmed to last 5
```

**Pros**:
- Automatic cap enforcement by LangGraph — impossible to exceed 5 by construction.
- Follows the established pattern for `ac_steps_completed` (custom `_deduplicated_add`).

**Cons**:
- **Clearing is awkward**: To clear the buffer on AC step advance, the evaluator would need to return a sentinel value (e.g., `[{"__clear__": True}]`) and the reducer would need to detect and handle it. This is a non-standard hack.
- **Append-only semantics conflict**: LangGraph reducers are designed for append-merge. Overwriting the entire list (needed for "clear" and "cap at 5") requires a workaround that breaks the reducer contract.
- **Two failure tracking lists use different reducer patterns**: `ac_step_failure_diary` is already a plain list (no reducer) because the evaluator overwrites the full list. Adding a second failure list with a reducer creates inconsistency.

**Verdict**: Rejected — reducer semantics are wrong for a buffer that needs both cap and clear.

---

### Option 2 — Evaluator-Owned Plain List (Chosen ✓)

**Pattern**: Declare `action_history_buffer: list[dict]` as a plain (unannotated) field. The evaluator owns all mutations — it overwrites the full list on every return, handling both append-and-cap and clear operations explicitly.

**Data flow**:
```
On failure:
  evaluator reads existing buffer
  appends new entry
  trims to last 5
  returns {"action_history_buffer": trimmed_list}

On AC step advance:
  evaluator returns {"action_history_buffer": []}
```

**Component design**:
```
┌──────────────────────────────────────────────────────────────┐
│                         VQAState                             │
│  action_history_buffer: list[dict]   ← plain field (no      │
│                                         reducer, overwrite   │
│                                         semantics)           │
└──────────────────────────────────────────────────────────────┘
              │ reads                        │ writes
              ▼                              ▼
┌────────────────────┐          ┌─────────────────────────────┐
│ planner.py          │         │ evaluator.py                 │
│ ─────────────────── │         │ ───────────────────────────── │
│ _build_past_actions │         │ Case 1 (failure):            │
│ _block(state)       │         │   append entry + cap at 5    │
│   → <past_actions>  │         │ Case 2 (done/advance):       │
│     XML block       │         │   clear to []                │
│   → "" if empty     │         │ Case 3 (verifier satisfied): │
│                     │         │   clear to []                │
│ Injected at:        │         │                              │
│   v1: after FAILURE │         │ Also clears on:              │
│       DIARY in      │         │   - recipe idempotent-skip   │
│       <context>     │         │   - setup_role (new role)    │
│   v2: Slot 9        │         │   - ALREADY_IN_VIEW fast-path│
│       (ACTIVE tier) │         │                              │
└────────────────────┘          └─────────────────────────────┘
```

**Pros**:
- **Matches existing pattern**: `ac_step_failure_diary` uses the exact same approach — plain list, evaluator overwrites. Zero conceptual overhead.
- **Clear is trivial**: `return {"action_history_buffer": []}`. No sentinel values.
- **Cap is trivial**: Python slice `buffer[-5:]` before returning.
- **Testable**: Both append/cap and prompt-building are pure functions.
- **No LangGraph reducer changes**: Zero risk to existing state merge behaviour.

**Cons**:
- If a node _other than evaluator_ ever needed to append to the buffer, it would overwrite instead of merge. (Mitigated: only the evaluator writes to this field, by design.)
- Evaluator must remember to clear the buffer on every advance path (4-5 return statements). Forgetting one would leave stale entries. (Mitigated: same risk exists for `ac_step_failure_diary` which already works correctly.)

**Verdict**: ✅ Chosen — simplest, safest, consistent with existing patterns.

---

### Option 3 — Separate Buffer Manager Class

**Pattern**: Create a `ActionHistoryBuffer` class in `backend/engine/action_buffer.py` that encapsulates the buffer logic (append, cap, clear, render). The evaluator and planner call its methods instead of manipulating raw lists.

**Data flow**:
```
On failure:
  buffer = ActionHistoryBuffer.from_state(state)
  buffer.append(entry)
  evaluator returns {"action_history_buffer": buffer.to_list()}

In planner:
  buffer = ActionHistoryBuffer.from_state(state)
  prompt_block = buffer.render_xml()
```

**Pros**:
- Encapsulates all buffer logic in one place (DRY).
- The `render_xml()` method is a natural unit-test target.

**Cons**:
- **Over-engineering**: The buffer logic is ~15 lines of Python (append + slice + format). Creating a class, module, import chain, and serialization layer adds 80+ lines for no real benefit.
- **Introduces cross-import**: Both evaluator and planner import the buffer class, creating a new dependency.
- **Breaks the "state is data" principle**: LangGraph state is a TypedDict — all other fields are manipulated as raw dicts/lists. Introducing a domain object violates the architectural norm.

**Verdict**: Rejected — unnecessary abstraction for a trivially simple data structure.

---

## Evaluation Matrix

| Criteria | Weight | Option 1 (Reducer) | Option 2 (Plain List) ✓ | Option 3 (Manager Class) |
|----------|--------|--------------------|-----------------------|-------------------------|
| Fits existing patterns | **High** | ⚠️ Mixed (uses reducer for capped list, but clearing is non-standard) | ✅ Perfect match (`ac_step_failure_diary` pattern) | ❌ No precedent for domain objects in state |
| Maintainability | **High** | ⚠️ Sentinel clear logic is fragile | ✅ Simple overwrite + slice | ✅ Encapsulated but over-indirected |
| Testability | **High** | ⚠️ Reducer is testable but clear-sentinel adds edge cases | ✅ Pure functions, trivial to test | ✅ Class methods are testable |
| Implementation effort | **Medium** | ⚠️ Medium (reducer + sentinel handling) | ✅ Low (~40 lines across 3 files) | ❌ High (new module, imports, serialization) |
| Regression risk | **High** | ⚠️ Modifying reducer infrastructure affects all list fields | ✅ Zero — additive only | ✅ Zero — additive only |
| Performance | Low | ✅ O(1) reducer merge | ✅ O(1) slice | ✅ O(1) equivalent |

---

## Detailed Integration Design (Option 2)

### 1. State Field (`state.py`)

```python
# ── Action History Buffer (FEAT-020: Action History Buffer) ─────────────
# Rolling window of the last 5 failed actions with structured metadata.
# Used by the planner to enforce a hard "NEVER repeat failed strategy"
# constraint. Plain field (no reducer) — evaluator overwrites the full
# list on each update (same pattern as ac_step_failure_diary).
# Cleared to [] when ac_step_index advances.
action_history_buffer: list[dict]
```

**Location**: After `ac_step_failure_diary` (line ~729), within the self-healing section.

**Initial value in `make_initial_state`**: `action_history_buffer=[]`

### 2. Evaluator Write Sites (`evaluator.py`)

**Append site** (Case 1 — action failed):
```python
# After existing diary_entry construction (~line 649)
existing_buffer = list(state.get("action_history_buffer", []))
buffer_entry = {
    "action": action_type,
    "strategy": planned_strategy,
    "target": planned_name,
    "error_type": _classify_error(error_msg),
    "iteration": state.get("planner_iteration", 0),
}
existing_buffer.append(buffer_entry)
# Cap at 5 entries (FIFO eviction)
if len(existing_buffer) > 5:
    existing_buffer = existing_buffer[-5:]
```

Then include `"action_history_buffer": existing_buffer` in every failure-path return dict.

**Clear sites** (all AC-step-advance paths):
Include `"action_history_buffer": []` in every return dict that also sets `ac_step_failure_diary: []` — these are the same advance paths.

### 3. Planner Prompt Injection (`planner.py`)

**New function** `_build_past_actions_block(state: VQAState) -> str`:
```python
def _build_past_actions_block(state: VQAState) -> str:
    buffer = state.get("action_history_buffer", [])
    if not buffer:
        return ""  # AC-HAPPY-6: no empty XML tags
    
    lines = [
        "<past_actions>",
        "HARD CONSTRAINT: NEVER repeat an action+strategy+target combination "
        "that appears below with outcome=FAILED.",
    ]
    for entry in buffer:
        lines.append(
            f'  <failed_action action="{entry["action"]}" '
            f'strategy="{entry["strategy"]}" '
            f'target="{entry["target"]}" '
            f'error="{entry["error_type"]}" '
            f'iteration="{entry["iteration"]}" '
            f'outcome="FAILED" />'
        )
    lines.append("</past_actions>")
    return "\n".join(lines)
```

**v1 injection**: In `_build_system_prompt()`, call `_build_past_actions_block(state)` and insert the result after the failure diary block, within the `<context>` section.

**v2 injection**: In `_build_system_prompt_v2()`, add as a budget section:
```python
past_actions_block = _build_past_actions_block(state)
if past_actions_block:
    budget.add("past_actions", Tier.ACTIVE, past_actions_block,
               slot=9)  # Between ACTIVE_CONSTRAINTS (8) and LEARNED_WORKFLOW (10)
```

### 4. Prompt Slot Position

New slot constant in `Slot`:
```python
PAST_ACTIONS = 9  # After failure diary (8), before learned workflow (10)
```

This places the `<past_actions>` block at Priority 2 (ACTIVE tier) — immediately after the failure diary, matching the task specification.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Evaluator forgets to clear buffer on an advance path | Low | Medium (stale entries on new step) | Grep for all `ac_step_failure_diary: []` sites and add `action_history_buffer: []` at each |
| Buffer entries inflate prompt beyond budget | Very Low | Low (5 entries × ~120 chars = 600 chars) | ACTIVE tier with max_chars=1500 ensures it's never dropped silently but also bounded |
| Conflict with existing `ac_step_failure_diary` | None | N/A | Separate fields, separate prompt blocks, separate purposes (diary = suggestions, buffer = hard constraint) |
