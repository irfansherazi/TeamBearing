# Algorithm Decision: Circuit Breaker Key Design

**Created**: 2026-05-15
**Status**: DECIDED
**Decision Type**: Algorithm

## Problem Statement

The vQA engine currently suffers from infinite loops when the agent repeats "successful" but unproductive actions, notably `coordinate_action` (in vision mode) and `press_key` ("Escape"). The existing identical-action circuit breaker ignores vision-specific parameters like `mark_id` when generating its deduplication key and only increments the repeat count when `success=False`. Because these actions technically succeed at the Playwright level but fail to satisfy the acceptance criteria, the agent evades the budget and loops until hitting the 500-step graph recursion limit.

## Inputs & Outputs

### Inputs
| Name | Type | Size/Range | Source |
|------|------|------------|--------|
| `planned_action` | Dictionary | ~10 keys | LLM Planner output |
| `success` | Boolean | True/False | Playwright execution result |

### Outputs
| Name | Type | Description |
|------|------|-------------|
| `_selector_key` | String | A deterministic hash/string identifying the uniqueness of the action. |
| `increment_flag` | Boolean | Whether to increment the repeat counter for this action attempt. |

### Edge Cases
1. Missing optional fields (e.g., `value`, `mark_id`) - Should default to empty strings to maintain consistent keys.
2. Actions that change state implicitly but look identical - Handled by the existing budget of 5 repeats.
3. Successful actions that don't advance the step - Must be counted to prevent loops.

## Constraints

### Performance Requirements
- **Maximum Latency**: < 1ms (pure string manipulation and dictionary access).
- **Throughput**: Called once per action step (minimal load).
- **Memory Budget**: Negligible (stores a dictionary of string counts).

### Scale Requirements
- **Current Data Size**: Max 500 actions per run.
- **Expected Growth**: Stable.
- **Peak Load**: Parallel runs, but state is isolated per run.

## Options Explored

### Option 1: Universal Inclusion Strategy
- **Approach**: Include every possible identifier field (`action`, `strategy`, `role`, `name`, `value`, `mark_id`, `trigger_mark_id`, `target_text`) in the string key. Increment the circuit breaker count for *every* action attempt, regardless of whether it succeeded or failed at the Playwright level.
- **Time Complexity**:
  - Best/Average/Worst: O(1) - simple string interpolation.
- **Space Complexity**: O(1) - single string allocation.
- **Data Structures**: String formatting.
- **Pros**:
  - Captures exact identical actions including all vision mode specifics.
  - Resolves the "successful loop" issue universally by tracking all repeated attempts.
- **Cons**:
  - Minor variations in non-critical fields (e.g., LLM slightly varying `target_text`) might evade the deduplication.
- **Best For**: Preventing exact-match infinite loops.

### Option 2: Action-Type Specific Key & Increment Logic
- **Approach**: Tailor the key based on the `action_type`. For `coordinate_action`, include `mark_id`. For DOM actions, include `role` and `name`. Only increment successful actions for specific loop-prone types (`coordinate_action`, `press_key`).
- **Time Complexity**: O(1)
- **Space Complexity**: O(1)
- **Data Structures**: String formatting with conditionals.
- **Pros**:
  - More resilient to LLM hallucinations on irrelevant fields.
  - Avoids overly aggressive circuit breaking on valid repeated successes (like scrolling).
- **Cons**:
  - More complex to maintain.
  - Might miss new types of loop-prone actions introduced later.

## Complexity Comparison

| Metric | Option 1 | Option 2 |
|--------|----------|----------|
| Time (Best) | O(1) | O(1) |
| Time (Avg) | O(1) | O(1) |
| Time (Worst) | O(1) | O(1) |
| Space | O(1) | O(1) |
| Implementation | Simple | Medium |

## Decision

**Chosen**: Option 1 - Universal Inclusion Strategy (with a slight modification to handle the success increment).

### Rationale
Including all potential identifiers in the `_selector_key` (`mark_id`, `trigger_mark_id`, `target_text`) guarantees that we can uniquely identify identical vision-mode actions without adding brittle conditional logic. Furthermore, incrementing the repeat counter for EVERY action attempt, regardless of Playwright `success`, is the correct paradigm. If an agent repeats the exact same action 5 times—whether it "succeeded" by clicking empty space or failed by timing out—it is objectively stuck and must be escalated.

### Trade-offs Accepted
- Legitimate identical actions (e.g., clicking a "Next" button 6 times) will trip the circuit breaker. This is acceptable because vQA relies on structured AC steps; a single step should not require 6 identical clicks. If it does, the AC parsing or recipe engine should handle it, not the raw planner loop.

## Implementation Details

### Data Structures
| Structure | Purpose | Operations Used |
|-----------|---------|-----------------|
| String | Unique key generation | `f"{a}:{b}:{c}"` O(1) |
| Dictionary | Tracking repeat counts | `dict.get()`, assignment O(1) |

### Algorithm Steps
1. In `executor.py` or where the key is generated, extract `mark_id`, `trigger_mark_id`, and `target_text` from the action.
2. Append these to the existing `_selector_key` format.
3. In `evaluator.py`, remove the `if not success:` condition around the `action_repeat_counts` increment logic, ensuring it increments for all identical actions.

### Edge Case Handling
| Edge Case | Handling |
|-----------|----------|
| Missing fields | Use `.get('field', '')` to ensure empty strings instead of `None`. |
| Legitimate repeats | The limit of 5 is high enough to absorb minor retries but low enough to prevent 124-step loops. |

## Validation Checklist

- [x] Meets latency requirements
- [x] Meets memory requirements
- [x] Handles all edge cases
- [x] Scales to expected data size
- [x] Implementation feasible
- [x] Respects Guiding Principles and data flow patterns in systemPatterns.md
