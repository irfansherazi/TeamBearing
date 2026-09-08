"""
backend/engine/dependency_analyzer.py
========================================
DependencyAnalyzer — Conservative Verify-Only AC Step Parallelization.

Algorithm: O(n) single-pass classification. READ-only steps (VERIFY_ONLY,
VERIFY_TABLE_SORT) are grouped into parallel execution blocks. WRITE steps
(all other step_types) always execute sequentially, breaking any surrounding
read group.

Design: Option A from TASK-080 creative phase — conservative initial rollout.
Promote to Component-DAG (Option B) once adoption is confirmed.

Feature flag: `enabled` param (driven by settings.parallel_steps_enabled).
When disabled, returns [[i] for i in range(n)] — fully sequential, zero
behavior change from pre-FEAT-060 baseline.

AC Coverage:
- AC-EDGE-2: Dependent steps (WRITE) are serialized — no race on shared state
- AC-ENTRY-1: enabled=False → sequential groups, zero regression
- AC-NFR-1: Conservative approach (READ-only parallel) prevents false parallelism
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action classification sets (using StructuredACStep.step_type values)
# ---------------------------------------------------------------------------

#: READ-only step types: observe page state, never mutate it.
#: Any step_type NOT in this set is treated as WRITE (conservative default).
READ_ONLY_STEP_TYPES: frozenset[str] = frozenset({
    "verify_only",
    "verify_table_sort",
})


def _is_read_only(step_type: str | None) -> bool:
    """Return True if the step only observes page state (never mutates it)."""
    if not step_type:
        return False
    return step_type.lower().strip() in READ_ONLY_STEP_TYPES


# ---------------------------------------------------------------------------
# Step type extraction
# ---------------------------------------------------------------------------


def _extract_step_type(step: object) -> str | None:
    """
    Safely extract step_type from a step object.

    Handles:
    - StructuredACStep (Pydantic model with .step_type attribute)
    - dict (legacy dict-form steps)
    - Any other object → returns None (treated as WRITE)
    """
    if hasattr(step, "step_type"):
        return getattr(step, "step_type", None)
    if isinstance(step, dict):
        return step.get("step_type")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_parallel_groups(steps: list, enabled: bool = True) -> list[list[int]]:
    """
    Build a list of parallel execution groups from AC steps.

    Groups are ordered: group[i] must complete before group[i+1] starts.
    Steps within a group can execute concurrently (no shared write state).

    Args:
        steps: Parsed StructuredACStep list from ac_parser_node.
        enabled: Feature flag — when False, returns all steps as individual
                 sequential groups (zero behavior change from baseline).

    Returns:
        list[list[int]] — each inner list is a group of concurrent step indices.
        Invariant: every index in range(len(steps)) appears exactly once.

    Examples:
        [FILL, CLICK, VERIFY_ONLY, VERIFY_ONLY, FILL] →
            [[0], [1], [2, 3], [4]]
            (steps 2 and 3 run in parallel, others sequential)

        [VERIFY_ONLY, VERIFY_ONLY, VERIFY_ONLY] →
            [[0, 1, 2]]
            (all three run in parallel)

        [FILL, CLICK, FILL] →
            [[0], [1], [2]]
            (all sequential — no reads)
    """
    if not enabled:
        # Feature flag off: all sequential (no-op baseline)
        logger.debug(
            "DependencyAnalyzer: PARALLEL_STEPS_ENABLED=false — returning sequential groups"
        )
        return [[i] for i in range(len(steps))]

    if not steps:
        return []

    groups: list[list[int]] = []
    read_group: list[int] = []

    for i, step in enumerate(steps):
        step_type = _extract_step_type(step)

        if _is_read_only(step_type):
            # Accumulate consecutive reads into a parallel group
            read_group.append(i)
        else:
            # WRITE step: flush pending read group, then emit sequential step
            if read_group:
                groups.append(read_group)
                read_group = []
            groups.append([i])

    # Flush any trailing read group
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
    parallel_steps = sum(len(g) for g in groups if len(g) > 1)
    logger.info(
        "DependencyAnalyzer: %d steps → %d groups (%d parallel blocks, %d parallel steps)",
        len(steps),
        len(groups),
        parallel_count,
        parallel_steps,
    )

    return groups
