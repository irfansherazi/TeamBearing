---
legacy_id: vqa-post-v2-1-regression-stabilization
---
# vqa-post-v2-1-regression-stabilization: vQA Post-v2.1 Regression Stabilization

**Complexity**: Level 4
**Status**: COMPLETE
**Reflection**: memory-bank/reflection/reflection-vqa-post-v2-1-regression-stabilization.md
**Archived**: memory-bank/archive/archive-vqa-post-v2-1-regression-stabilization.md
**Completed**: 2026-05-15
**Jira Issue**: FEAT-030
**Issue Type**: Bug (regression stabilization)
**Priority**: High
**Branch**: feature/FEAT-030-vqa-regression-stabilization
**Worktree**: /Users/joshschauer/Documents/vProMedia/vQA
**Roadmap**: FEAT-030
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/12

---

## Task Description

vQA is unstable after rapid delivery of FEAT-020 through FEAT-027. Five interacting bugs have been identified since commit `5cee18f` (last stable baseline):

### Bug 1: Proactive Overlay Dismissal Conflicts with Intentional Dropdowns
**Origin**: FEAT-026 (Proactive Overlay Dismissal)

The overlay dismissal gate in `executor.py` treats PrimeNG dropdowns as "blocking overlays" and sends `Escape` to close them — even when the planner *intentionally* opened the dropdown to select an option. This creates an oscillation loop:
1. Planner clicks dropdown → dropdown opens
2. Executor detects overlay → sends Escape → dropdown closes
3. Planner re-clicks dropdown → cycle repeats until budget exhausted

**Root Cause**: The `PageStateTracker.has_open_overlay()` check does not distinguish between:
- **Blocking overlays** (modals, dialogs, toasts) that obstruct unrelated UI
- **Functional overlays** (dropdowns, comboboxes, date pickers) that are part of the current action flow

### Bug 2: Missing List View Navigation Recipe
**Origin**: Gap in knowledge base

No navigation recipe exists for switching to "List View" in vSuite. The planner falls into an infinite loop trying to navigate to List View because the KB has no guidance for this transition. The ARIA tree shows a radio button group for view switching but the planner doesn't recognize the pattern without KB support.

### Bug 3: Planner Hallucinating Dropdown Option Names
**Origin**: Interaction between FEAT-025 (ARIA Tree Pruning) and planner prompts

After ARIA tree pruning, the planner sometimes generates dropdown option text that doesn't exist in the actual DOM. The pruned tree may not include the dropdown's option list (since options are often in a detached overlay panel, not the main DOM). The planner "guesses" option names based on the AC text rather than grounding in actual DOM content.

### Bug 4: Jira AC Sync API Broken on customfield_10031
**Origin**: Jira adapter

The `jira_fetch_node` fails to parse AC from `customfield_10031` when the field contains Atlassian Document Format (ADF) with nested `inlineCard` or `mediaSingle` nodes. The ADF-to-text converter crashes with a `KeyError` on these node types, causing the entire test run to abort.

### Bug 5: Prompt Budget Dropping Critical Context During Retries
**Origin**: Interaction between FEAT-020 (Action History Buffer) and planner prompt assembly

When the action history buffer fills up (5 entries), the prompt assembly function in `planner.py` exceeds the context window budget. The budget trimming logic drops the `<domain_context>` block (from FEAT-002) and sometimes the `<session_context>` block (from FEAT-028), removing the very context the planner needs to avoid repeating mistakes. The trimming priority order is wrong — it should preserve domain context and drop older history entries instead.

**Last Stable Baseline**: Commit `5cee18f`

---

## Acceptance Criteria

### Bug 1: Overlay Dismissal Fix
- AC-HAPPY-1: When the planner issues a `click` action targeting a dropdown trigger, the overlay dismissal gate does NOT dismiss the resulting dropdown overlay
- AC-HAPPY-2: When a modal dialog is open and the planner targets an element outside the modal, the overlay dismissal gate correctly sends `Escape` to dismiss the modal
- AC-HAPPY-3: PrimeNG `p-dropdown`, `p-multiSelect`, `p-autoComplete`, and `p-calendar` overlays are classified as "functional overlays" and exempt from proactive dismissal
- AC-ERROR-1: If the functional overlay classification fails (unknown overlay type), the system falls back to the existing dismissal behavior (safe default)
- AC-REGRESS-1: FEAT-026 existing test suite still passes — modal and dialog dismissal behavior unchanged

### Bug 2: List View Navigation Recipe
- AC-HAPPY-4: A `list_view_navigation.yaml` blueprint exists in `knowledge/blueprints/` that handles switching between Compact/List/Grid views via the radio button group
- AC-HAPPY-5: The planner can navigate to List View without entering an infinite loop
- AC-HAPPY-6: The recipe handles the case where the target view is already active (no-op)
- AC-REGRESS-2: Existing view navigation patterns (Compact View from FEAT-010) are not broken

### Bug 3: Dropdown Option Hallucination
- AC-HAPPY-7: When the planner needs to select a dropdown option, the pruned ARIA tree includes the dropdown's overlay panel content (option list)
- AC-HAPPY-8: The planner prompt includes a hard constraint: "ONLY select options that appear verbatim in the ARIA tree or DOM snapshot"
- AC-ERROR-2: If the dropdown options are not visible in the ARIA tree (e.g., lazy-loaded), the planner requests a "click to open + re-snapshot" action instead of guessing
- AC-REGRESS-3: FEAT-025 ARIA tree pruning performance gains are preserved — the pruning still reduces token count on dense pages

### Bug 4: Jira ADF Parser Fix
- AC-HAPPY-9: `customfield_10031` with `inlineCard` ADF nodes is parsed without error — inline cards render as `[link text](url)`
- AC-HAPPY-10: `customfield_10031` with `mediaSingle` ADF nodes is parsed without error — media renders as `[media: filename]`
- AC-ERROR-3: Unknown ADF node types render as `[unsupported: nodeType]` instead of crashing
- AC-REGRESS-4: Standard ADF parsing (paragraph, text, bulletList, orderedList, heading) still works correctly

### Bug 5: Prompt Budget Fix
- AC-HAPPY-11: Prompt trimming priority order is: (1) drop oldest history entries first, (2) drop session context, (3) drop domain context LAST
- AC-HAPPY-12: The `<domain_context>` block is never dropped if it fits within the remaining budget after trimming history
- AC-ERROR-4: If the total prompt still exceeds budget after trimming all optional blocks, a WARNING is logged with the budget breakdown
- AC-REGRESS-5: FEAT-020 action history buffer still prevents amnesic retry loops — the most recent 2 entries are always preserved

---

## Open Questions

⚠️ **Review these before starting the build:**

- [ ] **Bug 1**: Should the functional overlay exemption list be hardcoded (PrimeNG component selectors) or dynamically detected via ARIA roles (e.g., `role="listbox"` = functional overlay)?
- [ ] **Bug 1**: Should the executor track "who opened the overlay"? If the planner's last action was `click` on a dropdown trigger, the resulting overlay should always be exempt.
- [ ] **Bug 2**: Does List View exist in all vSuite pages, or only specific modules? Need to scope the recipe accordingly.
- [ ] **Bug 3**: The ARIA tree pruning (FEAT-025) currently filters by `target_element_types` — should dropdown overlays be added as a special "always include" rule, or should the pruning be skipped entirely when the current AC step involves a dropdown?
- [ ] **Bug 5**: What is the actual token budget for the planner prompt? Is it configured in `config.py` or hardcoded in `planner.py`?
- [ ] **General**: Should all 5 bugs be fixed in a single branch, or should each bug get its own branch and be merged sequentially to isolate regressions?

---

## Affected Components

Based on the five bugs, these files/areas are involved:

### Bug 1 — Overlay Dismissal
- `backend/engine/executor.py` — Pre-action overlay dismissal gate logic
- `backend/engine/state_tracker.py` — `has_open_overlay()` method needs a "functional vs. blocking" classification
- `knowledge/selector_registry.json` — May need PrimeNG overlay component selectors for classification

### Bug 2 — List View Recipe
- `knowledge/blueprints/` — New `list_view_navigation.yaml` blueprint
- `knowledge/human_guidance.md` — New entry for List View navigation pattern
- `backend/kb/playwright_rag.py` — Ensure the new recipe is indexed for RAG retrieval

### Bug 3 — Dropdown Hallucination
- `backend/engine/planner.py` — Prompt assembly needs the "verbatim only" constraint for dropdown selections
- `backend/engine/state_tracker.py` — ARIA tree snapshot should include overlay panels when a dropdown is open
- `backend/engine/prompts.py` — System prompt modification for grounding constraint

### Bug 4 — Jira ADF Parser
- `backend/adapters/jira_adapter.py` (or equivalent) — ADF-to-text converter needs `inlineCard` and `mediaSingle` handlers
- `backend/engine/ac_parser.py` — May need fallback handling if ADF conversion returns partial results

### Bug 5 — Prompt Budget
- `backend/engine/planner.py` — Prompt assembly trimming priority logic
- `backend/engine/prompts.py` — Budget allocation constants
- `backend/config.py` — Token budget configuration (if configurable)

---

## Test Strategy

### Approach
- **Emphasis**: Unit-heavy with targeted integration tests for the overlay/planner interaction
- **Target test count**: 20-25 tests across all 5 bugs

### Test Targets

#### Bug 1 Tests (5-6 tests)
- `test_overlay_classification_functional_vs_blocking` — PrimeNG dropdown detected as functional
- `test_overlay_dismissal_skipped_for_functional` — No Escape sent when dropdown is functional
- `test_overlay_dismissal_triggered_for_modal` — Escape sent for blocking modal
- `test_unknown_overlay_falls_back_to_dismissal` — Safe default behavior
- `test_overlay_oscillation_loop_prevented` — Regression test for the original bug

#### Bug 2 Tests (3-4 tests)
- `test_list_view_recipe_exists_and_parses` — YAML blueprint loads correctly
- `test_list_view_recipe_executes` — Steps sequence is valid
- `test_already_on_list_view_noop` — No-op when target view active
- `test_compact_view_recipe_unchanged` — Regression

#### Bug 3 Tests (4-5 tests)
- `test_aria_tree_includes_dropdown_overlay` — Open dropdown options are in snapshot
- `test_planner_prompt_grounding_constraint` — Verbatim-only constraint present
- `test_planner_rejects_hallucinated_option` — Non-existent option triggers re-snapshot
- `test_aria_pruning_still_reduces_tokens` — Performance regression check

#### Bug 4 Tests (4-5 tests)
- `test_adf_inline_card_parsing` — inlineCard → markdown link
- `test_adf_media_single_parsing` — mediaSingle → media placeholder
- `test_adf_unknown_node_graceful` — Unknown type → fallback text
- `test_adf_standard_nodes_unchanged` — Standard paragraph/list/heading regression

#### Bug 5 Tests (4-5 tests)
- `test_prompt_trimming_drops_history_first` — Oldest history entries removed first
- `test_domain_context_preserved_during_trim` — Domain context survives budget cuts
- `test_minimum_history_entries_preserved` — Last 2 entries always kept
- `test_budget_exceeded_warning_logged` — WARNING when all blocks trimmed but still over

### What NOT to Test
- Live Playwright browser interactions
- AWS Bedrock/S3 integrations
- End-to-end LangGraph graph execution
- Frontend React components

---

## Implementation Roadmap

- [x] Phase 1: **Bug 4 — Jira ADF Parser Fix** (isolated, no cross-dependencies)
  - Add `inlineCard` and `mediaSingle` handlers to ADF converter
  - Add graceful fallback for unknown node types
  - Write 4-5 unit tests
- [x] Phase 2: **Bug 5 — Prompt Budget Fix** (isolated, changes trimming logic only)
  - Refactor prompt assembly trimming priority in `planner.py`
  - Ensure domain context is last to be dropped
  - Preserve minimum 2 history entries
  - Write 4-5 unit tests
- [x] Phase 3: **Bug 2 — List View Navigation Recipe** (KB change, low risk)
  - Create `list_view_navigation.yaml` blueprint
  - Add human_guidance.md entry for view switching
  - Verify RAG indexing picks up new content
  - Write 3-4 unit tests
- [x] Phase 4: **Bug 1 — Overlay Dismissal Fix** (touches executor + state tracker)
  - Add functional vs. blocking overlay classification to `state_tracker.py`
  - Modify pre-action gate in `executor.py` to skip functional overlays
  - Write 5-6 unit tests
- [x] Phase 5: **Bug 3 — Dropdown Hallucination Fix** (touches planner + ARIA pruning)
  - Modify ARIA tree snapshot to include open overlay panels
  - Add "verbatim only" grounding constraint to planner prompt
  - Write 4-5 unit tests
- [x] Phase 6: **Integration Validation**
  - Run full test suite to verify no cross-bug regressions
  - Run benchmark pipeline against Golden 10 dataset
  - Verify overlay dismissal + dropdown selection work together end-to-end

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO
**Notes**: Task successfully archived.
**Worktree Cleaned**: YES
**Branch Deleted**: NO (preserved for PR)
