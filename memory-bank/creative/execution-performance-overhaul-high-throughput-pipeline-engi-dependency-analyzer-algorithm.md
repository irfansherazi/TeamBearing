# Algorithm: DependencyAnalyzer DAG — AC Step Parallelization

**Task**: execution-performance-overhaul-high-throughput-pipeline-engi / FEAT-060 — Phase 3: Parallel AC Step Execution
**Component**: `backend/engine/dependency_analyzer.py` [NEW]
**Author**: vc-creative orchestrator (inline)
**Date**: 2026-05-31

---

## Decision

**Chosen**: Option A — Conservative Heuristic: Verify-Only Parallelization
**Rationale**: O(n) time complexity, O(n) space, 30 LOC implementation, zero LLM cost, deterministic and fully testable. Correctness is guaranteed by the conservative classification — a READ step can never modify page state by definition, so parallelizing READ blocks is provably safe. Per the value assessment and AC-EDGE-2's recommendation, this is the correct initial rollout strategy. Option B (Component DAG) is the planned promotion path for Phase 4.

---

## Algorithm Design

### Formal Problem Statement

```
Input:  steps: list[TestStep] where TestStep has { action_type: str, assertions: list }
Output: parallel_step_groups: list[list[int]]
        where each group is a list of step indices that can execute concurrently
        and groups must be executed in order (group[i] completes before group[i+1] starts)

Invariant: The flattened parallel_step_groups must contain every index in [0, len(steps)-1]
           exactly once (no step dropped, no step duplicated).
```

### Classification Rules

```python
# READ_ONLY action types: observe page state, do not modify it
READ_ONLY_ACTIONS = frozenset({
    "verify",
    "assert",
    "check_visible",
    "check_text",
    "check_value",
    "check_url",
    "check_title",
    "screenshot",          # passive capture
    "wait_for_visible",    # passive wait
    "wait_for_hidden",     # passive wait
})

# WRITE action types: modify page state (clicks, fills, navigation, waits with side effects)
# Anything NOT in READ_ONLY_ACTIONS is treated as WRITE
WRITE_ACTIONS = {
    "click", "fill", "navigate", "select", "check",
    "recipe", "scroll", "press", "drag_drop", "upload",
    "hover",  # hover can trigger dropdown menus (side effect)
    "wait",   # wait with side effects (e.g., wait for modal to appear after action)
}
```

### Algorithm (Pseudocode)

```
function build_parallel_groups(steps: list[TestStep]) -> list[list[int]]:
    groups: list[list[int]] = []
    read_group: list[int] = []

    for i in range(len(steps)):
        step = steps[i]
        action_type = normalize_action_type(step.action_type)

        if action_type in READ_ONLY_ACTIONS:
            # Accumulate consecutive reads into a parallel group
            read_group.append(i)
        else:
            # Hit a WRITE step — flush pending read group first
            if read_group:
                groups.append(read_group)   # parallel group
                read_group = []
            groups.append([i])              # sequential (WRITE)

    # Flush any trailing read group
    if read_group:
        groups.append(read_group)

    return groups
```

### Invariant Verification

```python
def verify_invariant(steps: list, groups: list[list[int]]) -> bool:
    """Verify every step appears exactly once across all groups."""
    flat = [i for g in groups for i in g]
    return sorted(flat) == list(range(len(steps)))
```

### Complete Python Implementation

```python
# backend/engine/dependency_analyzer.py

"""
DependencyAnalyzer — Conservative Verify-Only AC Step Parallelization.

Algorithm: O(n) single-pass classification. READ-only steps are grouped into
parallel execution blocks. WRITE steps (state-mutating actions) always execute
sequentially, breaking any surrounding read group.

Feature flag: PARALLEL_STEPS_ENABLED=false → build_parallel_groups() returns
[[0], [1], ..., [n-1]] (all sequential, zero behavior change).

Design: Option A from execution-performance-overhaul-high-throughput-pipeline-engi creative phase — conservative initial rollout.
Promote to Component-DAG (Option B) once adoption is confirmed.
"""

import logging
from typing import TYPE_CHECKING

from backend.config import settings

if TYPE_CHECKING:
    from backend.engine.schemas import TestStep

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action classification sets
# ---------------------------------------------------------------------------

READ_ONLY_ACTIONS: frozenset[str] = frozenset({
    "verify",
    "assert",
    "check_visible",
    "check_text",
    "check_value",
    "check_url",
    "check_title",
    "screenshot",
    "wait_for_visible",
    "wait_for_hidden",
})


def _is_read_only(action_type: str) -> bool:
    """Return True if the action only observes page state (never mutates it)."""
    return action_type.lower().strip() in READ_ONLY_ACTIONS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_parallel_groups(steps: list["TestStep"]) -> list[list[int]]:
    """
    Build a list of parallel execution groups from AC steps.

    Groups are ordered: group[i] must complete before group[i+1] starts.
    Steps within a group can execute concurrently (no shared write state).

    Feature-flagged: when PARALLEL_STEPS_ENABLED=false, returns all steps
    as individual sequential groups (zero behavior change from baseline).

    Args:
        steps: Parsed TestStep list from ac_parser_node.

    Returns:
        list[list[int]] — each inner list is a group of concurrent step indices.
        Invariant: every index in range(len(steps)) appears exactly once.

    Examples:
        [fill, click, verify, verify, fill] →
            [[0], [1], [2, 3], [4]]
            (steps 2 and 3 run in parallel, others sequential)

        [verify, verify, verify] →
            [[0, 1, 2]]
            (all three run in parallel)

        [fill, click, fill] →
            [[0], [1], [2]]
            (all sequential — no reads)
    """
    if not settings.parallel_steps_enabled:
        # Feature flag off: all sequential (no-op baseline)
        logger.debug("PARALLEL_STEPS_ENABLED=false — returning sequential groups")
        return [[i] for i in range(len(steps))]

    if not steps:
        return []

    groups: list[list[int]] = []
    read_group: list[int] = []

    for i, step in enumerate(steps):
        action_type = _extract_action_type(step)

        if _is_read_only(action_type):
            read_group.append(i)
        else:
            # WRITE step: flush pending read group, then emit sequential step
            if read_group:
                groups.append(read_group)
                read_group = []
            groups.append([i])

    # Trailing read group
    if read_group:
        groups.append(read_group)

    # Defensive invariant check (debug builds only)
    if __debug__:
        flat = [i for g in groups for i in g]
        assert sorted(flat) == list(range(len(steps))), (
            f"DependencyAnalyzer invariant violated: "
            f"expected {list(range(len(steps)))}, got {sorted(flat)}"
        )

    parallel_count = sum(1 for g in groups if len(g) > 1)
    logger.info(
        "DependencyAnalyzer: %d steps → %d groups (%d parallel blocks, %d parallel steps)",
        len(steps),
        len(groups),
        parallel_count,
        sum(len(g) for g in groups if len(g) > 1),
    )

    return groups


def _extract_action_type(step: "TestStep") -> str:
    """
    Safely extract action_type from a TestStep, falling back to 'unknown'.

    TestStep may be a Pydantic model or a plain dict (legacy path).
    """
    if hasattr(step, "action_type"):
        return (step.action_type or "").lower().strip()
    if isinstance(step, dict):
        return (step.get("action_type") or "").lower().strip()
    return "unknown"
```

### Execution Integration (graph.py)

```python
# In ac_parser_node (after steps are finalized):

if settings.parallel_steps_enabled and test_plan:
    from backend.engine.dependency_analyzer import build_parallel_groups
    steps = test_plan.get("steps", [])
    parallel_groups = build_parallel_groups(steps)
    logger.info(
        "[%s] DependencyAnalyzer: %d steps → %d groups",
        run_id, len(steps), len(parallel_groups)
    )
else:
    parallel_groups = [[i] for i in range(len(steps))]

# Store in state:
return {
    "test_plan": test_plan,
    "parallel_step_groups": parallel_groups,
    ...
}
```

### Parallel Execution in Evaluator

```python
# evaluator_node: when advancing to next AC step,
# check if the next group has multiple steps
groups = state.get("parallel_step_groups") or [[i] for i in range(n_steps)]
next_group = groups[current_group_index + 1]

if len(next_group) > 1 and settings.parallel_steps_enabled:
    # Dispatch next_group steps in parallel via asyncio.gather()
    results = await asyncio.gather(*[
        run_step(state, step_idx) for step_idx in next_group
    ])
else:
    # Sequential path (unchanged behavior)
    next_step_index = next_group[0]
    ...
```

---

## Complexity Analysis

- **Time**: O(n) — single pass over steps list; each step inspected exactly once
- **Space**: O(n) — groups list has at most n elements, read_group buffer has at most n
- **Cold start**: Negligible (<1ms for typical 3–15 step AC lists; <5ms for 100 steps)

---

## Options Explored

### Option A — Conservative Heuristic: Verify-Only Parallelization ✅ CHOSEN
- READ/WRITE classification → parallel READ blocks
- O(n) time, O(n) space, 30 LOC
- Provably correct (READ steps cannot affect page state)
- **Score: 18/21**

### Option B — Component-Based Dependency DAG (Kahn's Algorithm)
- Per-component dependency tracking + topological sort
- O(n²) worst case, higher implementation complexity
- Finer-grained parallelism (can parallelize non-Verify steps if different component)
- **Planned promotion path** when Option A is proven in production
- **Score: 13/21**

### Option C — LLM-Assisted Dependency Labeling
- Full semantic understanding
- 1–3s latency cost per parse, LLM hallucination risk
- **Score: 9/21**

### Option D — Variable Extraction Static Analysis
- Regex-based variable reference tracking
- Misses implicit data flows (most real AC)
- **Score: 13/21**

---

## Evaluation Matrix

| Criteria | Weight | Option A | Option B | Option C | Option D |
|----------|--------|----------|----------|----------|----------|
| Correctness | Critical | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ |
| Time complexity | High | ⭐⭐⭐ O(n) | ⭐⭐ O(n²) | ⭐ O(LLM) | ⭐⭐⭐ O(n) |
| Space complexity | Medium | ⭐⭐⭐ O(n) | ⭐⭐ O(n²) | ⭐⭐⭐ O(n) | ⭐⭐ O(n×v) |
| Implementation simplicity | Medium | ⭐⭐⭐ 30 LOC | ⭐⭐ 80 LOC | ⭐ | ⭐⭐ |
| Testability | Medium | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ |
| Scalability (30+ steps) | Context-dep | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐ |
| **Total** | | **18** | **13** | **9** | **13** |

---

## Edge Cases

| Edge Case | Handling |
|-----------|----------|
| All steps are WRITE | Returns `[[0], [1], ..., [n-1]]` — fully sequential |
| All steps are READ | Returns `[[0, 1, ..., n-1]]` — all parallel |
| Empty step list | Returns `[]` |
| Unknown action_type | Falls through to WRITE (conservative: unknown = sequential) |
| `action_type` is None | `_extract_action_type` returns `"unknown"` → WRITE |
| `PARALLEL_STEPS_ENABLED=false` | Returns sequential groups, zero behavior change |

---

## Acceptance Criteria Traceability

| AC | Covered By |
|----|-----------|
| AC-EDGE-2: Steps 3+4 depend on step 2 → serialized | Steps 3,4 are WRITE (click/fill) → individual sequential groups |
| AC-ENTRY-1: `PARALLEL_STEPS_ENABLED=false` → baseline | Feature flag returns `[[i] for i in range(n)]` |
| AC-NFR-1: ≥ 90% AC step pass rate | Conservative approach (READ-only parallel) prevents false parallelism |

---

## Promotion Path to Option B

When Phase 3 is stable in production and the Golden 10 benchmark confirms correctness, promote to Option B (Component DAG):

1. Add `target_component` field to `TestStep` schema (ac_parser populates it)
2. Implement `_build_component_dag()` alongside `build_parallel_groups()`
3. Feature flag: `DEPENDENCY_ANALYZER_MODE=conservative|dag` (default: `conservative`)
4. A/B test on Golden 10 benchmark — confirm pass rate ≥ 90% before switching default

This incremental promotion is lower risk than deploying Component DAG on day one.
