# Archive: knowledge-base-refactor-coverage-expansion — Knowledge Base Refactor & Coverage Expansion

## Metadata

- **Task ID**: knowledge-base-refactor-coverage-expansion
- **Complexity**: Level 3
- **Started**: 2026-05-07
- **Completed**: 2026-05-07
- **Roadmap Link**: FEAT-003
- **Branch**: feature/FEAT-003-kb-refactor-coverage

## Summary

knowledge-base-refactor-coverage-expansion was a targeted, data-quality refactor of the vQA agent's institutional memory across five dimensions: selector timing notes, keyword noise reduction, blueprint coverage expansion, entry deduplication, and unified registry migration. The goal was to reduce the HITL escalation rate for high-frequency interactions by ensuring the planner has precise, deduplicated, and well-structured guidance at query time.

All six MUST/SHOULD acceptance criteria were met or exceeded. The final state is a KB that is fully annotated, deduplicated, with blueprint coverage for the five most-escalated interaction patterns, and a complete unified component registry — guarded by 25 automated regression tests that did not exist before this task.

## Requirements

### Original Requirements

1. Add `timing_note` to all 293 null entries in `selector_registry.json` (AC-VERIFY-1)
2. Add `context` to all 139 empty entries in `selector_registry.json` (AC-VERIFY-1 regression)
3. Improve KB TF-IDF retrieval precision — ≥ 8 of 10 test queries return correct result (AC-VERIFY-2)
4. Create 5 new blueprint YAML files for high-frequency interactions (AC-VERIFY-3)
5. Expand `unified_components.json` from 6 to 11 PrimeNG components (AC-VERIFY-4)
6. Deduplicate `human_guidance.md` from 75 to ≤ 55 entries (AC-VERIFY-5)
7. Eliminate keyword bloat from both KB markdown files, ≤ 8 terms per KEYWORDS line (AC-VERIFY-6)

### Success Criteria

| Criterion | Target | Achieved |
|-----------|--------|----------|
| Selector timing_note coverage | 0 missing from 328 | ✅ 0 missing |
| Selector context coverage | 0 missing from 328 | ✅ 0 missing |
| TF-IDF retrieval accuracy | ≥ 8/10 queries correct | ✅ 10/10 correct |
| New blueprints | 5 files, Pydantic valid | ✅ 5 files, 9/9 tests pass |
| Unified registry coverage | 11 components | ✅ 11 components |
| human_guidance.md deduplication | ≤ 55 entries | ✅ 51 entries |
| Keyword bloat elimination | ≤ 5 filler entries; ≤ 8 terms/line | ✅ 0 filler entries |

## Implementation

### Approach

Three sequential phases ordered by risk:
- **Phase 1** (data edits to existing files, lowest risk) — creates regression guard tests before Phases 2–3 touch schema-dependent files
- **Phase 2** (new YAML files, schema-constrained) — validated by Pydantic `ActionRecipe.model_validate()` on each blueprint
- **Phase 3** (deduplication + JSON migration, highest coordination cost) — relies on Phase 1 keyword tests as regression guards

No source code changes to any engine files (`planner.py`, `recipe_runner.py`, `loader.py`, `unified_registry.py`). Pure data-file task.

### Key Components

1. **`knowledge/selector_registry.json`** — 293 timing_notes + 139 contexts added (Phase 1)
   - Timing inference: p-autocomplete → +500ms, p-calendar → +400ms, p-select → +300ms, table sort → +200ms, row/cell → +150ms, form submit → URL-wait, navigation → +300ms
   - 26 corrections applied after code review (22 date-column sort headers misclassified as p-select; 4 non-dropdown inputs)

2. **`knowledge/human_guidance.md`** — 75 → 51 WORKFLOW entries (Phase 1 keywords, Phase 3 dedup)
   - Largest merge: 8 "Navigate to Compact view" variants → 1 canonical (unioned: settings cog method, Sort By dropdown note, visual indicator)
   - Canonical merge strategy: earliest timestamp anchor; union of all distinct instruction sentences; union of domain keywords capped at 8; most-specific selector hint

3. **`knowledge/vSuite-actions.md`** — 52 KEYWORDS lines trimmed to ≤ 8 terms (Phase 1)

4. **Five new blueprints** (Phase 2):
   - `knowledge/blueprints/inline_edit.yaml` — Double-click cell → Ctrl+A → fill → Enter
   - `knowledge/blueprints/status_dropdown.yaml` — Click trigger → wait overlay → click option (scoped to `.p-select-overlay`)
   - `knowledge/blueprints/batch_checkbox.yaml` — CSS `:nth-child($row_index)` trick; fallback to header checkbox when `row_index="0"`
   - `knowledge/blueprints/approvals_workflow.yaml` — Click item → click action button (`"Yes"` quoted to prevent YAML boolean coercion) → wait
   - `knowledge/blueprints/voice_form_combobox.yaml` — Click input → fill (+500ms debounce) → wait overlay (+800ms) → click option

5. **`knowledge/unified_components.json`** — 6 → 11 components (Phase 3)
   - Added: `p-multiselect`, `p-checkbox`, `p-confirmdialog`, `p-tablecheckbox`, `p-table-header`
   - Each entry has selectors, interaction_protocol, forbidden_patterns, angular_quirks, animation_budget, trigger_keywords

6. **Test suite** (all phases):
   - `backend/kb/test_selector_completeness.py` — 4 tests: timing_note/context completeness + keyword max-length guards
   - `backend/engine/test_blueprint_validation.py` — 9 tests: 5 new + 4 regression blueprints
   - `backend/kb/test_matcher.py` — 12 new functions: entry count guard, registry completeness, 10 parametrized retrieval accuracy tests
   - `conftest.py` (new, project root) — Pre-caches numpy/sklearn to fix scipy import-ordering under Python 3.13

### Design Decisions

No creative phase was required — the implementation approach was fully determined by existing schemas and file structure.

Key non-obvious decisions:
1. **Removed `verify_after` from 4 of 5 new blueprints** — `recipe_runner.py` lines 849–879 have an idempotency pre-check that silently skips any recipe whose `verify_after` selector is already visible before execution. For interaction recipes, the trigger selector is always visible, so the engine would return `{success: true, skipped: true}` without executing any steps. Mitigation: removed `verify_after` from `inline_edit`, `status_dropdown`, `approvals_workflow`, `voice_form_combobox`. `batch_checkbox` retains `verify_after: aria-checked='true'` safely (that state is never present before the click).
2. **Rule-based timing inference** — Applied component-type heuristics rather than per-entry analysis. 7–8% misclassification rate (26/293) caught by code review.
3. **conftest.py pre-cache pattern** — scikit-learn/scipy import chain fails under Python 3.13 when another test file modifies `sys.path[0]` at module level before numpy is first imported. Standard pytest pattern: project-root conftest.py pre-imports the affected packages before collection begins.

## Testing

- **Phase 1**: 4/4 tests passing (`test_selector_completeness.py`)
- **Phase 2**: 9/9 tests passing (`test_blueprint_validation.py`) + 4 regression
- **Phase 3**: 25/25 total tests passing (12 new + 13 regression)
- **Code Review**: APPROVED WITH NOTES in all 3 phases (all issues resolved before commit)

## Files Changed

### Modified
- `knowledge/selector_registry.json` — 293 timing_notes + 139 contexts; 26 label corrections
- `knowledge/human_guidance.md` — 75→51 entries; 13 duplicate groups merged; keyword lines trimmed
- `knowledge/vSuite-actions.md` — 52 KEYWORDS lines trimmed
- `knowledge/unified_components.json` — 6→11 components; 5 new entries added
- `backend/kb/test_matcher.py` — 12 pytest functions appended; import hoisted to module level
- `knowledge/blueprints/compact_view_navigate.yaml` — Pre-existing verify_after selector fix (separate bug)

### New
- `knowledge/blueprints/inline_edit.yaml`
- `knowledge/blueprints/status_dropdown.yaml`
- `knowledge/blueprints/batch_checkbox.yaml`
- `knowledge/blueprints/approvals_workflow.yaml`
- `knowledge/blueprints/voice_form_combobox.yaml`
- `backend/kb/test_selector_completeness.py`
- `backend/engine/test_blueprint_validation.py`
- `conftest.py` (project root)

## Technical Debt Identified

1. **FEAT-004: `recipe_runner.py` idempotency pre-check redesign** (High) — Lines 849–879 conflate "recipe already applied" with "verify_after selector visible before execution." Fix: add a `verify_state_change` field type that asserts a before→after attribute transition, making the pre-check inapplicable to interaction recipes. Once complete, restore `verify_after` to the 4 affected blueprints.

2. **Level 1 cleanup: `component_registry.py` file removal** — The direct import was disabled; the file was left as a deprecation step. File removal is a separate Level 1 task.

3. **TestMatcher class warning** (Low) — `TestMatcher` class in `test_matcher.py` has an `__init__` constructor that triggers a pytest collection warning. Cosmetic only; rename to avoid heuristic or convert to module-level functions.

## Lessons Learned

Key takeaways from the reflection (see `memory-bank/reflection/reflection-knowledge-base-refactor-coverage-expansion.md` for full analysis):

1. **TDD cross-phase regression protection**: Phase 1's `test_human_guidance_keyword_max_length` caught the KEYWORDS regression introduced in Phase 3's merge automatically — without the Phase 3 coding agent needing to remember the constraint. Front-loading test writing in multi-phase data tasks creates a free regression backstop for all later phases.

2. **Code review sub-agent is most valuable for behavioral bugs, not schema bugs**: Schema errors are caught by Pydantic validation tests. Code review caught the semantic issues tests cannot: `verify_after` idempotency semantics, option click not scoped to overlay container, YAML boolean coercion for `"Yes"`. Per-phase code review (not end-of-task) is the right cadence.

3. **YAML boolean coercion trap**: Always quote YAML string fields whose values are English words that YAML parses as booleans (`Yes`, `No`, `True`, `False`, `On`, `Off`).

4. **conftest.py pre-cache pattern**: When co-located test files modify `sys.path` at module level, a project-root conftest.py that pre-imports heavy ML dependencies before collection prevents import-ordering failures under Python 3.13.

5. **Bulk JSON classification rate**: A 7–8% misclassification rate is expected when classifying by key-name heuristics alone. Always run a code-review pass after bulk rule-based JSON edits.

## References

- **Task Plan**: `memory-bank/tasks/knowledge-base-refactor-coverage-expansion.md`
- **Reflection**: `memory-bank/reflection/reflection-knowledge-base-refactor-coverage-expansion.md`
- **Progress Notes**: `memory-bank/progress.md` (Phases 1–3 entries)
- **Learned Rules**: `memory-bank/agent-rules/_learned/data-validation.md`, `memory-bank/agent-rules/_learned/testing-patterns.md`

## Follow-up

- **FEAT-004**: `recipe_runner.py` idempotency pre-check redesign + `verify_state_change` field type
- **FEAT-005**: HITL Learning Loop Fixes (pre-existing, separate task)
- **FEAT-006**: Synonym expansion in `LocalKnowledgeBase._SYNONYM_MAP`
- **Level 1**: `component_registry.py` file removal
