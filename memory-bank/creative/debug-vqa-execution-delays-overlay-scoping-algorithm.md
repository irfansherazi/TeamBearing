# Algorithm Decision: Overlay Scoping Logic

**Created**: 2026-05-15
**Status**: DECIDED
**Decision Type**: Algorithm

## Problem Statement

The Proactive Overlay Dismissal logic (FEAT-026) is too aggressive. It identifies open overlays (like primeNG dropdowns or dialogs) and presses `Escape` before the planner's action if the target element is deemed to be "outside" the overlay. However, it lacks context for `coordinate_action` (used in vision mode) and mistakenly dismisses functional dropdowns just before the agent attempts to interact with them via coordinates, leading to a loop of opening and immediately closing the dropdown. Additionally, its "is_inside" check fails when the `container_selector` exactly matches the `overlay_selector`.

## Inputs & Outputs

### Inputs
| Name | Type | Size/Range | Source |
|------|------|------------|--------|
| `action_type` | String | e.g. "click", "coordinate_action" | LLM Planner output |
| `container_selector` | String | CSS Selector | LLM Planner output |
| `overlay_selector` | String | CSS Selector | `PageStateTracker` |
| `is_functional` | Boolean | True/False | `PageStateTracker` |

### Outputs
| Name | Type | Description |
|------|------|-------------|
| `should_dismiss` | Boolean | Whether to proactively press `Escape` to close the overlay. |

### Edge Cases
1. Target is the overlay itself.
2. Action is `coordinate_action` where DOM containment is unknown.
3. Overlays that are actual Dialogs/Modals that *must* be completed, not dismissed.

## Constraints

### Performance Requirements
- **Maximum Latency**: < 1ms (pure boolean logic).

### Scale Requirements
- **Current Data Size**: Evaluated once per action.

## Options Explored

### Option 1: Action-Aware Containment Logic
- **Approach**: 
  1. Skip proactive dismissal if `action_type == "coordinate_action"`.
  2. Improve the `is_inside` check: allow `overlay_selector == container_selector` or `overlay_selector in container_selector`.
  3. Mark `dialog` roles as `is_functional=True` in `state_tracker.py` so they are not aggressively dismissed when the agent is trying to interact within them.
- **Time Complexity**: O(1)
- **Space Complexity**: O(1)
- **Pros**:
  - Solves the exact bug where vision mode actions are sabotaged by the dismissal logic.
  - Prevents dialogs from being closed prematurely.
- **Cons**:
  - A blocking overlay might remain open if the agent mistakenly uses `coordinate_action` targeting something behind it. (Acceptable, as the action will fail and retry, eventually breaking out).

### Option 2: DOM-based Coordinate Hit Testing
- **Approach**: Inject JavaScript to evaluate if the coordinates in `coordinate_action` fall within the bounding box of the active `overlay_selector`.
- **Time Complexity**: O(1) but involves Playwright async bridge overhead.
- **Space Complexity**: O(1)
- **Pros**:
  - Highly accurate containment checking for coordinates.
- **Cons**:
  - Adds latency.
  - Unnecessary complexity since `coordinate_action` is typically used *because* the agent wants to interact with the tricky visual element (like a dropdown list).

## Complexity Comparison

| Metric | Option 1 | Option 2 |
|--------|----------|----------|
| Time (Best) | O(1) | O(1) (plus JS bridge latency) |
| Implementation | Simple | Complex |

## Decision

**Chosen**: Option 1 - Action-Aware Containment Logic

### Rationale
Simplicity and exact alignment with the problem constraints. When the agent resorts to `coordinate_action`, it is explicitly trying to bypass DOM-based strictness to interact with what it *sees*. Sabotaging this by pressing Escape based on DOM assumptions defeats the purpose of vision mode. Furthermore, `container_selector` equality is a valid indication that the action is scoped to the overlay. Marking dialogs as functional ensures that full-page modals are not blindly dismissed.

### Trade-offs Accepted
- If the agent uses `coordinate_action` to click something *behind* an overlay, the click will be intercepted. This is an acceptable failure mode; the agent will receive an `INTERCEPTED` error and can learn to dismiss it explicitly.

## Implementation Details

### Data Structures
None required beyond basic conditionals.

### Algorithm Steps
In `executor.py`'s `_dispatch_action`:
1. Check if `action_type == "coordinate_action"`. If true, `is_inside = True` (skip dismissal).
2. Otherwise, check `is_inside = (overlay_selector and (overlay_selector in target_container or overlay_selector == target_container))`.
3. In `state_tracker.py` `_OVERLAY_SELECTORS`, ensure `{ "role": "dialog" }` maps to `is_functional: True`.

### Edge Case Handling
| Edge Case | Handling |
|-----------|----------|
| `target_container` is empty | Evaluates to `False` (not inside), proceeds to dismiss unless `is_functional` is True. |

## Validation Checklist

- [x] Meets latency requirements
- [x] Handles all edge cases
- [x] Implementation feasible
- [x] Respects Guiding Principles and data flow patterns in systemPatterns.md
