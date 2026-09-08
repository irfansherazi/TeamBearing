# Algorithm: Action History Buffer — Rolling Window & Deduplication

## Decision
**Chosen**: Option 2 — Append-Then-Slice with (action, strategy, target) Tuple Key
**Rationale**: Maximally simple O(1) amortized operations, zero external dependencies, and the deduplication tuple exactly matches the failure mode described in the task (same-target retries with cosmetic strategy changes).

---

## Problem Space

### Input
- On each failed action, the evaluator produces a structured entry:
  ```python
  {
      "action": "click",           # action type
      "strategy": "get_by_role",   # locator strategy used
      "target": "Submit All",      # element name/role
      "error_type": "STRICT_MODE", # classified error
      "iteration": 7               # planner iteration
  }
  ```
- Buffer size cap: **5 entries** (specified in task)
- Clear trigger: `ac_step_index` advances (new AC step)

### Output
- `action_history_buffer: list[dict]` in VQAState — at most 5 entries
- Planner reads the buffer and renders it as an XML block — no computation, just format

### Performance Targets
- Append: Must be O(1) — called on every failed action (hot path)
- Clear: Must be O(1) — called on every AC step advance
- Render: Must be O(N) where N ≤ 5 — called on every planner iteration
- Memory: Negligible (5 small dicts)

### Scale Expectations
- Max 5 entries by design
- Typically 1-3 entries before escalation to human_takeover
- Buffer is per-AC-step (cleared on advance), so total lifetime entries = failures_per_step

---

## Options Explored

### Option 1 — Deque with maxlen

**Algorithm**:
```python
from collections import deque
buffer = deque(maxlen=5)
buffer.append(entry)  # Oldest auto-evicted
```

**Pros**:
- Built-in FIFO eviction via `maxlen` — impossible to exceed 5.
- Standard library, well-understood.

**Cons**:
- `deque` is not JSON-serializable. LangGraph state is a TypedDict that must be JSON-serializable for checkpoint/resume. Would need `list(buffer)` on every write and `deque(state["..."], maxlen=5)` on every read — adding conversion overhead and potential bugs.
- `deque` does not support slice syntax (`deque[-3:]` raises TypeError).
- Introduces a data structure that doesn't exist anywhere else in VQAState.

**Complexity**: O(1) append, O(N) serialize/deserialize
**Space**: O(5) = O(1)

**Verdict**: Rejected — serialization friction outweighs the auto-eviction benefit.

---

### Option 2 — Append-Then-Slice (Chosen ✓)

**Algorithm**:
```python
# On failure
buffer = list(state.get("action_history_buffer", []))
entry = {
    "action": action_type,
    "strategy": planned_strategy,
    "target": planned_name,
    "error_type": _classify_error(error_msg),
    "iteration": state.get("planner_iteration", 0),
}
buffer.append(entry)
if len(buffer) > 5:
    buffer = buffer[-5:]  # FIFO: keep newest 5

# On AC step advance
buffer = []
```

**Step-by-step**:
1. Copy the current buffer from state (defensive copy to avoid mutation)
2. Construct the new entry from the current failure context
3. Append the entry
4. If length > 5, slice to keep only the last 5 (FIFO eviction)
5. Return the full list — LangGraph overwrites the field

**Deduplication logic**: The buffer stores the **raw tuple** `(action, strategy, target)` — this is the deduplication key the planner uses. The prompt block says "NEVER repeat an action+strategy+target combination with outcome=FAILED." This catches:
- Same locator with same strategy → exact match
- Same target with different strategy → different entry, but `target` field is the same, so the planner sees both failed strategies for "Submit All" and must try a completely different target

**Edge cases**:
1. **Empty buffer** (first action on a new step): `_build_past_actions_block()` returns `""` — no XML tags injected (AC-ERROR-1).
2. **Buffer exactly at 5**: Next append creates 6 → `buffer[-5:]` trims to 5.
3. **Clear on advance**: `buffer = []` — trivially correct.
4. **Multiple failures with identical tuple**: Each is stored independently (no dedup in the buffer itself). The planner sees multiple entries with the same strategy, reinforcing the "don't repeat" constraint.
5. **Non-string values in entry**: All values are strings or ints — JSON-safe by construction.

**Complexity**: 
- Append: O(1) amortized (list.append is amortized O(1); slice is O(5) = O(1))
- Clear: O(1)
- Render: O(5) = O(1)

**Space**: O(5) = O(1)

**Verdict**: ✅ Chosen — maximally simple, zero dependencies, O(1) everything.

---

### Option 3 — Ring Buffer with Index Tracking

**Algorithm**:
```python
BUFFER_SIZE = 5
buffer = [None] * BUFFER_SIZE  # Fixed-size array
write_idx = 0

def append(entry):
    buffer[write_idx % BUFFER_SIZE] = entry
    write_idx += 1

def to_list():
    # Return entries in insertion order
    if write_idx <= BUFFER_SIZE:
        return [e for e in buffer[:write_idx] if e is not None]
    start = write_idx % BUFFER_SIZE
    return buffer[start:] + buffer[:start]
```

**Pros**:
- True O(1) append (no slice ever).
- Fixed memory footprint (no list growth/shrink).

**Cons**:
- **Serialization complexity**: Must serialize both `buffer` array AND `write_idx` to VQAState. Two fields instead of one.
- **Reconstruction on read**: `to_list()` requires modular arithmetic to produce correct insertion order.
- **Overkill**: For N=5, the performance difference between ring buffer and list+slice is meaningless (~50 nanoseconds).
- **No precedent**: No other state field uses a ring buffer. Introduces unfamiliar complexity.

**Complexity**: O(1) append (true, no amortized), O(N) serialize
**Space**: O(5) = O(1)

**Verdict**: Rejected — unnecessary complexity for buffer size 5.

---

### Option 4 — Deduplicated Buffer (Dict-Keyed by Tuple)

**Algorithm**:
```python
buffer_dict = {}  # key: (action, strategy, target) → value: entry
def append(entry):
    key = (entry["action"], entry["strategy"], entry["target"])
    buffer_dict[key] = entry  # Upsert: latest error_type wins
    if len(buffer_dict) > 5:
        # Remove oldest by insertion order (Python 3.7+ dicts are ordered)
        oldest_key = next(iter(buffer_dict))
        del buffer_dict[oldest_key]

entries = list(buffer_dict.values())
```

**Pros**:
- Natural deduplication: two failures on `(click, get_by_role, Submit All)` produce only one entry.
- Maximises diversity in the buffer (each entry represents a unique strategy).

**Cons**:
- **Loses repetition signal**: If the agent tried the exact same (action, strategy, target) 3 times, the buffer shows it as 1 entry. The planner loses the "how many times did I try this?" signal.
- **Serialization**: Must convert dict → list for VQAState, then list → dict on read. Same friction as deque.
- **Different semantics from task spec**: The task says "rolling buffer of the last 5 failed actions" — this implies ordered-by-time, not keyed-by-uniqueness. The buffer is a timeline, not a set.
- **Ordering ambiguity**: When rendering in the prompt, the agent needs to see entries in chronological order to understand the failure progression. Dict ordering is by insertion/update, which may not match chronological order after upserts.

**Complexity**: O(1) amortized append, O(N) serialize
**Space**: O(5) = O(1)

**Verdict**: Rejected — loses the repetition signal and violates the "rolling window" specification.

---

## Evaluation Matrix

| Criteria | Weight | Option 1 (Deque) | Option 2 (List+Slice) ✓ | Option 3 (Ring Buffer) | Option 4 (Dict-Keyed) |
|----------|--------|-------------------|------------------------|----------------------|----------------------|
| Correctness | **Critical** | ✅ | ✅ | ✅ | ⚠️ Loses repetition count |
| Time complexity | High | O(1) + O(N) ser | O(1) amortized | O(1) true | O(1) amortized |
| Space complexity | Medium | O(5) | O(5) | O(5) | O(5) |
| Implementation simplicity | **High** | ⚠️ ser/deser | ✅ 3 lines | ❌ Modular arithmetic | ⚠️ ser/deser + upsert |
| Testability | Medium | ✅ | ✅ | ⚠️ Ring reconstruction | ✅ |
| JSON serialization | **High** | ❌ Needs conversion | ✅ Native list[dict] | ❌ Needs conversion | ❌ Needs conversion |

---

## Chosen Algorithm — Full Pseudocode

```
FUNCTION append_to_buffer(state, action_type, strategy, target, error_msg, iteration):
    buffer ← copy(state.action_history_buffer)
    entry ← {
        action:     action_type,
        strategy:   strategy,
        target:     target,
        error_type: classify_error(error_msg),
        iteration:  iteration
    }
    buffer.append(entry)
    IF len(buffer) > 5:
        buffer ← buffer[-5:]    # FIFO eviction
    RETURN buffer

FUNCTION clear_buffer():
    RETURN []

FUNCTION render_xml(buffer):
    IF buffer is empty:
        RETURN ""
    xml ← "<past_actions>\n"
    xml += "HARD CONSTRAINT: NEVER repeat an action+strategy+target "
    xml += "combination that appears below with outcome=FAILED.\n"
    FOR entry IN buffer:
        xml += f"  <failed_action action='{entry.action}' "
        xml += f"strategy='{entry.strategy}' "
        xml += f"target='{entry.target}' "
        xml += f"error='{entry.error_type}' "
        xml += f"iteration='{entry.iteration}' "
        xml += "outcome='FAILED' />\n"
    xml += "</past_actions>"
    RETURN xml
```

**Invariants**:
- `len(buffer) <= 5` — always, after every operation
- `buffer == []` after any AC step advance
- `render_xml([]) == ""` — no empty XML tags ever
- Each entry has exactly 5 keys: action, strategy, target, error_type, iteration
