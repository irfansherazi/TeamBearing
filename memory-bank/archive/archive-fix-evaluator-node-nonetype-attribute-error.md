# Archive: Fix evaluator_node NoneType attribute error

## Metadata
- Task ID: fix-evaluator-node-nonetype-attribute-error
- Complexity: Level 1
- Completed: 2026-05-15

## Summary
The vQA engine crashed with an `AttributeError: 'NoneType' object has no attribute 'lower'` at `backend/engine/evaluator.py:761` during execution when both `planned_name` and `target_text` evaluated to `None`. 

## Solution
Implemented a null-coalescing string fallback (`or ""`) directly in the `evaluator_node` to safely pass an empty string to the `.lower()` method. This simple defensive check prevented engine failure while maintaining identical sorting circuit-breaker behavior.

## Files Changed
- `backend/engine/evaluator.py` - Added string fallback to prevent `NoneType` errors.

## Notes
Level 1 quick-fix successfully stabilized execution without modifying the underlying sort logic.
