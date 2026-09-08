---
legacy_id: knowledge-base-refactor-coverage-expansion
---
# knowledge-base-refactor-coverage-expansion: Knowledge Base Refactor & Coverage Expansion

**Complexity**: Level 3
**Status**: COMPLETE
**Reflection**: memory-bank/reflection/reflection-knowledge-base-refactor-coverage-expansion.md
**Archived**: memory-bank/archive/archive-knowledge-base-refactor-coverage-expansion.md
**Completed**: 2026-05-07
**Roadmap**: FEAT-003
**Branch**: feature/FEAT-003-kb-refactor-coverage
**Worktree**: /Users/joshschauer/Documents/vProMedia/vQA (feature branch: feature/FEAT-003-kb-refactor-coverage)

## Task Description

The KB is the agent's institutional memory and its current quality directly limits what vQA can do autonomously. This task is a targeted refactor (not a rewrite) that improves KB quality across five dimensions:

1. **Deduplication** — `human_guidance.md` has ~75 entries with significant duplication (4 near-identical "Navigate to Compact view" variants, 5 "Save search folder" variants). Merging these into canonical entries improves TF-IDF signal by reducing noise.

2. **Selector timing notes** — 293 of 328 selector entries in `selector_registry.json` are missing `timing_note` guidance. Without these, the planner cannot know it needs to wait 500ms for a PrimeNG dropdown to render or 200ms for Angular to update a table cell, causing preventable timeouts.

3. **Keyword quality** — KEYWORDS lines across both `.md` files contain filler words ("successfully", "already", "because", "there", "know") that dilute TF-IDF vectors. Limiting keywords to 5–8 domain-specific terms improves retrieval precision.

4. **Blueprint coverage** — Only 4 active blueprints exist (`compact_view_navigate`, `p_calendar_range`, `p_calendar_single`, `p_select_column_sort`) for 279+ documented workflows. Four additional YAML files in `knowledge/blueprints/kb_docs/` use a legacy `{variable}` interpolation format and are not loaded by `RecipeRegistry`. Five high-frequency interactions have zero active blueprint coverage: inline cell editing, status dropdown with combobox modal, batch checkbox selection, approvals workflow, and voice form combobox. These cause the most HITL escalations in production.

5. **Unified registry migration** — `unified_registry.py` has a complete Pydantic schema and `unified_components.json` exists with 6 component stubs (`p-calendar`, `p-autocomplete`, `p-select`, `p-table`, `p-toast`, `p-fileupload`), but 5 components from `component_registry.json` are missing (`p-multiselect`, `p-checkbox`, `p-confirmdialog`, `p-tablecheckbox`, `p-table-header`). `planner.py` already imports and queries `unified_registry` (lines 719-722) and does NOT import `component_registry`. The migration work is populating the JSON to full coverage and ensuring no code path still queries `component_registry` directly.

## Specification

**Feature Type**: NFR/Infrastructure
**Primary Persona**: Platform Admin / vProMedia Engineering
**Creative Exploration Needed**: No — implementation approach is fully determined by existing schema and file structure

### Verification Method
- **Test method**: `pytest backend/kb/test_matcher.py backend/storage/test_suites.py -v` (existing test files; no `tests/` root directory exists — test files are co-located with modules); `python -c "from backend.kb.loader import kb; print(len(kb._workflows), 'workflows loaded')"` (KB load smoke test); `python -c "from backend.engine.recipe_runner import recipe_registry; print(recipe_registry.all_recipes())"` (blueprint validation smoke test)
- **Success metrics**:
  - All 328 selector entries have a non-null, non-empty `timing_note` field (currently 293 are missing — verified via `python -c "import json; d=json.load(open('knowledge/selector_registry.json')); print(sum(1 for v in d['selectors'].values() if not v.get('timing_note')))"`)
  - All 328 selector entries have a non-empty `context` field (currently 139 are missing)
  - `human_guidance.md` entry count drops from 75 to ≤ 55 (currently 75 entries, 55 unique names — 20 exact-name duplicates)
  - 65 of 75 `human_guidance.md` entries have keyword bloat — post-refactor, ≤ 5 entries retain any filler word from the set: {successfully, already, because, there, know, from, that, need, type}
  - 5 new blueprint YAML files present at `knowledge/blueprints/` top level and loadable by `RecipeRegistry` (currently 4 active blueprints: `compact_view_navigate.yaml`, `p_calendar_range.yaml`, `p_calendar_single.yaml`, `p_select_column_sort.yaml`)
  - `knowledge/unified_components.json` migrated from 6 components to cover all 11 components currently in `component_registry.json` (`p-calendar`, `p-autocomplete`, `p-multiselect`, `p-checkbox`, `p-table`, `p-toast`, `p-confirmdialog`, `p-fileupload`, `p-tablecheckbox`, `p-table-header`, `p-select`)
  - KB loads without import errors: `python -c "from backend.kb.loader import kb"` exits 0
- **Observable at**: inline Python assertions (no pytest runner needed for KB file checks); `recipe_registry.all_recipes()` output; INFO log lines from `loader.py` at startup (`KB TF-IDF index built: N documents`); `unified_registry.py` INFO log (`Unified registry loaded: N components`)
- **Verification frequency**: one-time per KB change (KB hot-reloads at runtime — `loader.py` polls `.md` file mtimes on every query call, `recipe_runner.py` polls YAML mtimes on every `get()` call)

### Acceptance Criteria

#### AC-VERIFY-1: Selector timing_note coverage is complete
**Priority**: MUST
**Given** the `knowledge/selector_registry.json` file with 328 total entries
**When** parsed via `json.load()` and each entry's `timing_note` field is inspected
**Then** zero entries have a `null` or empty string `timing_note` (293 currently missing; verified by script: `sum(1 for v in d['selectors'].values() if not v.get('timing_note')) == 0`)
- **Confidence**: HIGH — selector count of 328 and missing count of 293 verified by direct JSON parse
- **Regression guard**: `context` field must also be non-empty for all 328 entries (139 currently missing)

#### AC-VERIFY-2: KB TF-IDF retrieval precision improves
**Priority**: MUST
**Given** a set of 10 representative AC step queries (covering: sort by due date, login, navigate to compact view, inline cell edit, approve an order, batch select rows, status dropdown combobox, file upload, single date calendar, create quick order)
**When** each query is run through `kb.query_with_expansion(step_text)` (the function used by `planner.py`)
**Then** at least 8 of 10 queries return a non-empty result with the correct KB article as the top-ranked workflow (validated against a ground-truth mapping authored alongside the test)
- **Confidence**: MEDIUM — baseline ~65-75% is from the task description, not a measured benchmark; ground-truth mapping must be authored during test creation
- **Test location**: extend `backend/kb/test_matcher.py` (currently 313 lines, 0 pytest-style test functions; convert or extend with 10 named test cases)

#### AC-VERIFY-3: Five new blueprints load and validate without error
**Priority**: MUST
**Given** each of the 5 new blueprint YAML files placed at `knowledge/blueprints/` (top level, alongside existing 4)
**When** `RecipeRegistry._load_file(path)` processes each file via `ActionRecipe.model_validate(raw)`
**Then** Pydantic validation succeeds (no `ValidationError`), `recipe.name` is non-empty, `recipe.steps` is non-empty, every `RecipeStep.action` is one of the 6 allowed literals (`click`, `fill`, `select_option`, `press_key`, `wait`, `set_input_files`), and every declared `$variable` in step fields appears in `recipe.parameters`
- **Required blueprints**: `inline_edit.yaml`, `status_dropdown.yaml`, `batch_checkbox.yaml`, `approvals_workflow.yaml`, `voice_form_combobox.yaml`
- **Confidence**: HIGH — `RecipeRegistry._load_file` and `ActionRecipe` schema are well-defined in `recipe_runner.py`; validation path is deterministic
- **Note on kb_docs/**: the 4 files in `knowledge/blueprints/kb_docs/` (login.yaml, create_quick_order.yaml, table_sorting.yaml, upload_file.yaml) use `{variable}` interpolation format and are NOT loaded by `RecipeRegistry` (which only globs `*.yaml` at the top level). New blueprints must use `$variable` Template syntax to be loadable.

#### AC-VERIFY-4: Unified registry covers all legacy component_registry entries
**Priority**: MUST
**Given** `knowledge/unified_components.json` (currently contains 6 components: `p-calendar`, `p-autocomplete`, `p-select`, `p-table`, `p-toast`, `p-fileupload`)
**When** `UnifiedRegistry._ensure_loaded()` parses the file
**Then** all 11 components from `knowledge/component_registry.json` are present in `unified_components.json` as keys: `p-calendar`, `p-autocomplete`, `p-multiselect`, `p-checkbox`, `p-table`, `p-toast`, `p-confirmdialog`, `p-fileupload`, `p-tablecheckbox`, `p-table-header`, `p-select`
- **Confidence**: HIGH — both JSON files are parseable; component keys are enumerable
- **Planner migration note**: `planner.py` already imports `unified_registry` (line 135) and calls `_unified_registry.is_loaded` / `detect_components` / `get_rules_for_prompt` (lines 719-722). `component_registry` is NOT imported in `planner.py`. The migration target is `loader.py` and any remaining direct imports of `component_registry` in the codebase.

#### AC-VERIFY-5: human_guidance.md deduplication reduces entry count
**Priority**: SHOULD
**Given** the `knowledge/human_guidance.md` file (currently 75 entries, 55 unique workflow names, 13 duplicate-named workflow groups)
**When** counted with `grep -c "^## WORKFLOW:"` 
**Then** entry count is ≤ 55, with the 6 "Navigate to Compact view" duplicates consolidated into 1 canonical entry, the 4 "Navigate to Production Orders compact view" duplicates into 1, and the 3 "Navigate to Production Orders list view" duplicates into 1, with all distinct information from merged entries preserved in the canonical entry
- **Confidence**: HIGH — duplicate names are verified; canonical merge strategy is straightforward (union the instruction bodies)

#### AC-VERIFY-6: Keyword bloat eliminated from both MD KB files
**Priority**: SHOULD
**Given** `knowledge/human_guidance.md` (65 of 75 entries have filler keywords) and `knowledge/vSuite-actions.md` (51 of 103 entries have filler keywords)
**When** each KEYWORDS line is parsed and checked for the filler set {successfully, already, because, there, know, type, named, need}
**Then** filler words appear in ≤ 5 entries total across both files, and no KEYWORDS line has more than 8 total terms
- **Confidence**: HIGH — filler word presence is directly measurable; 8-term limit is deterministic

### Scope Boundaries
- **In scope**:
  - `knowledge/selector_registry.json` — add `timing_note` to all 293 null entries and `context` to all 139 empty entries
  - `knowledge/human_guidance.md` — deduplicate 13 duplicate-named workflow groups; trim KEYWORDS to ≤ 8 domain-specific terms
  - `knowledge/vSuite-actions.md` — trim KEYWORDS to ≤ 8 domain-specific terms on the 51 bloated entries
  - `knowledge/blueprints/` — add 5 new YAML blueprint files (`inline_edit.yaml`, `status_dropdown.yaml`, `batch_checkbox.yaml`, `approvals_workflow.yaml`, `voice_form_combobox.yaml`) using `$variable` Template syntax
  - `knowledge/unified_components.json` — add the 5 missing components from `component_registry.json` (`p-multiselect`, `p-checkbox`, `p-confirmdialog`, `p-tablecheckbox`, `p-table-header`) plus promote the 6 existing stubs to full `ComponentInteraction` schema with `interaction_protocol`, `forbidden_patterns`, and `animation_budget` populated
  - Test files: extend `backend/kb/test_matcher.py` with 10-query ground-truth retrieval test cases; add `backend/kb/test_selector_completeness.py` and `backend/engine/test_blueprint_validation.py`
- **Out of scope**:
  - `backend/engine/planner.py` source code changes — `planner.py` already uses `unified_registry`; this task only populates the JSON it reads
  - `backend/kb/component_registry.py` source code deletion — deprecation (disabling import) is in scope; file removal is a separate cleanup task
  - `knowledge/blueprints/kb_docs/` — the 4 files there use a different format and are not loaded by `RecipeRegistry`; converting them is out of scope for this task
  - New synonym entries to `LocalKnowledgeBase._SYNONYM_MAP` in `loader.py` — that is FEAT-006 scope
  - Bedrock KB sync — `make kb-human-sync` pipeline is a deployment step, not part of this refactor
  - HITL escalation rate measurement — no live vSuite instance available; rate improvement is directional only
- **Dependencies**:
  - No external dependencies; all files are local to the repository
  - `backend/engine/recipe_runner.py` `RecipeRegistry` and `ActionRecipe` Pydantic schema must not change during this task (they define blueprint validation)
  - `backend/kb/unified_registry.py` `ComponentInteraction` dataclass schema must not change during this task (it defines the target JSON structure)
- **NFR implications**:
  - KB loads at module import time — adding 293 `timing_note` strings to `selector_registry.json` increases file size but does not affect `LocalKnowledgeBase` (which does not load this file; it is used by `selector_registry.py`)
  - `unified_components.json` is lazy-loaded by `UnifiedRegistry._ensure_loaded()` on first `lookup()` call — no startup performance impact from expanding to 11 components

### Implementation Guide Required
Yes — three-phase KB refactoring process with specific file targets and verification steps.

- **Phase 1** (Selector registry + keyword cleanup): Edit `knowledge/selector_registry.json` to add `timing_note` to 293 null entries (infer timing from component type: PrimeNG autocomplete → 500ms, p-select dropdown → 300ms, table cell render → 200ms, form submit → wait for URL change) and `context` to 139 empty entries. Edit KEYWORDS lines in `human_guidance.md` (75 entries) and `vSuite-actions.md` (103 entries) to remove filler words and cap at 8 terms.
- **Phase 2** (Five new blueprints): Create `knowledge/blueprints/inline_edit.yaml`, `status_dropdown.yaml`, `batch_checkbox.yaml`, `approvals_workflow.yaml`, `voice_form_combobox.yaml` following the `p_calendar_single.yaml` schema (name, description, trigger_keywords, parameters, steps with `$variable` Template syntax, cleanup_on_failure, verify_after).
- **Phase 3** (Deduplication + unified registry): Merge 13 duplicate-named workflow groups in `human_guidance.md` to canonical entries. Expand `knowledge/unified_components.json` from 6 to 11 components by migrating `component_registry.json` content into the `ComponentInteraction` dataclass schema.

---

## User Journey Definition

**Feature Type**: NFR/Infrastructure
**Creative Phase Required**: No — implementation approach is clear; no UX or architectural design decisions needed

### NFR Verification
- **Test method**: `pytest backend/kb/test_matcher.py backend/storage/test_suites.py -v` (note: test files are co-located with modules, not in a root `tests/` directory); `python -c "from backend.kb.loader import kb"` (KB load smoke test); manual HITL escalation rate observation over 5+ test runs
- **Success metrics**:
  - TF-IDF retrieval accuracy improvement: ≥ 85% of test queries return the correct KB article (up from ~65–75% baseline)
  - HITL escalation rate on known workflows drops by ≥ 30% after blueprint coverage added
  - All 328 selector entries have a populated `timing_note` field (293 currently missing)
  - All 328 selector entries have a populated `context` field (139 currently missing)
  - `unified_components.json` expanded from 6 to 11 components covering all `component_registry.json` entries
  - KB loads without errors: `python -c "from backend.kb.loader import kb"` exits 0
- **Observable at**: inline Python assertions; `recipe_registry.all_recipes()` output; KB loader startup INFO logs

### Acceptance Criteria

#### AC-VERIFY-1: Selector registry is complete
**Priority**: MUST
**Given** the `knowledge/selector_registry.json` file
**When** the file is loaded by `backend/kb/loader.py`
**Then** all 328 entries have a non-empty `timing_note` field and `context` field

#### AC-VERIFY-2: KB TF-IDF retrieval precision improves
**Priority**: MUST
**Given** a set of 10 representative AC step queries (covering sort, login, navigation, inline edit, approvals, batch select, status dropdown, file upload, calendar, quick order)
**When** each query is run through `kb.query_with_expansion(step_text)`
**Then** ≥ 8 of 10 queries return the most relevant KB article as the top result (validated against ground-truth mapping)

#### AC-VERIFY-3: All 5 new blueprints execute without error
**Priority**: MUST
**Given** each of the 5 new blueprint YAML files
**When** loaded and validated by `backend/engine/recipe_runner.py`
**Then** the YAML parses correctly, all required fields are present, and `$variable` Template syntax is used (not `{variable}` format used in `kb_docs/`)

#### AC-VERIFY-4: Unified registry covers all legacy component_registry entries
**Priority**: MUST
**Given** `backend/kb/unified_registry.py` and `knowledge/unified_components.json`
**When** `UnifiedRegistry._ensure_loaded()` parses the file
**Then** all 11 components from `component_registry.json` are present as keys in `unified_components.json`

#### AC-VERIFY-5: human_guidance.md deduplication reduces entry count
**Priority**: SHOULD
**Given** the `knowledge/human_guidance.md` file
**When** counted with `grep -c "^## WORKFLOW:"`
**Then** entry count is ≤ 55 (from 75 before), with the 6 "Navigate to Compact view" duplicates, 4 "Navigate to Production Orders compact view" duplicates, and 3 "Navigate to Production Orders list view" duplicates each consolidated into single canonical entries

## Test Strategy

### Approach
- **Emphasis**: Unit (KB loader correctness, blueprint validation) + integration (query accuracy)
- **Target test count**: 12–18 tests total

### File Organization
- **Extend existing**: `backend/kb/test_matcher.py` — add 10 named pytest-style test functions for the query accuracy ground-truth set (file currently has 313 lines but 0 pytest-style `def test_` functions)
- **New test files**: `backend/engine/test_blueprint_validation.py` — validate all 9 blueprint YAML files (4 existing + 5 new) parse and pass `ActionRecipe.model_validate()`; `backend/kb/test_selector_completeness.py` — assert `timing_note` and `context` coverage across all 328 selector entries

### What NOT to Test
- Actual vSuite page interactions — requires live browser and vSuite instance
- Bedrock KB sync (`scripts/sync_human_kb.py`) — external service, not unit-testable
- TF-IDF model internals — scikit-learn is well-tested; test our query accuracy, not the algorithm

### Per-Phase Test Guidance
- Phase 1 (Selector + keyword cleanup): 3 tests — `test_all_selectors_have_timing_note`, `test_all_selectors_have_context`, `test_keyword_line_max_length` (assert KEYWORDS lines have ≤ 8 comma-separated terms after strip)
- Phase 2 (Blueprints): 6 tests — validate each of 5 new blueprints (assert `ActionRecipe.model_validate()` succeeds, `recipe.steps` non-empty, no undeclared `$variables`) + regression on existing 4 active blueprints (`compact_view_navigate`, `p_calendar_range`, `p_calendar_single`, `p_select_column_sort`)
- Phase 3 (Dedup + unified registry): 5 tests — `test_human_guidance_entry_count` (≤ 55), 10-query retrieval ground-truth set in `test_matcher.py`, `test_unified_registry_covers_all_legacy_components` (all 11 keys present)

## Implementation Roadmap

- [x] Phase 1: Selector registry completion + keyword quality cleanup ✓
  - **Test Results**: 4/4 tests passing
  - **Code Review**: APPROVED WITH NOTES (21 timing label fixes applied)
  - **Completed**: 2026-05-07
- [x] Phase 2: Five new blueprint YAML files ✓
  - **Test Results**: 9/9 tests passing (13/13 total including Phase 1)
  - **Code Review**: APPROVED (after fixing idempotency pre-check bypass, option click scoping, test coverage gap)
  - **Completed**: 2026-05-07
- [x] Phase 3: human_guidance.md deduplication + unified_components.json population + loader migration ✓
  - **Test Results**: 25/25 tests passing (12 new + 13 Phase 1+2 regression)
  - **Code Review**: APPROVED WITH NOTES (import hoisted to module level; deferred import comment added)
  - **Completed**: 2026-05-07

## Implementation Plan

### Overview

Three sequential phases, each ending with passing tests before the next begins. Phases are ordered by risk: Phase 1 edits existing data files (safest, no schema changes), Phase 2 creates new YAML files (schema is fixed by `RecipeRegistry`), Phase 3 touches the deduplication logic and JSON schema migration (highest coordination cost).

No source code changes to `planner.py` — it already imports `unified_registry`. No HTTP endpoints affected. No observability requirements (KB is pure data).

### Component Analysis

#### Modified Files
| File | Change | Risk |
|---|---|---|
| `knowledge/selector_registry.json` | Add `timing_note` to 293 entries, `context` to 139 | Low — data only |
| `knowledge/human_guidance.md` | Strip keyword bloat (75 entries), dedup 13 groups | Medium — information loss risk on merge |
| `knowledge/vSuite-actions.md` | Strip keyword bloat (51 of 103 entries) | Low — keywords only |
| `knowledge/unified_components.json` | Add 5 components, promote 6 stubs to full schema | Medium — schema must match `ComponentInteraction` dataclass |

#### New Files
| File | Purpose |
|---|---|
| `knowledge/blueprints/inline_edit.yaml` | Double-click inline cell → type → Enter/Escape |
| `knowledge/blueprints/status_dropdown.yaml` | Click status badge → combobox modal → select option |
| `knowledge/blueprints/batch_checkbox.yaml` | Row checkbox selection (single or bulk) |
| `knowledge/blueprints/approvals_workflow.yaml` | Open approval → review → approve/deny → confirm |
| `knowledge/blueprints/voice_form_combobox.yaml` | Type search → wait for suggestions → click option |
| `backend/kb/test_selector_completeness.py` | Completeness assertions on selector_registry.json |
| `backend/engine/test_blueprint_validation.py` | Pydantic validate all 9 blueprints (4 existing + 5 new) |

#### Extended Files
| File | Change |
|---|---|
| `backend/kb/test_matcher.py` | Add 10 ground-truth retrieval test functions (currently 0 pytest functions despite 313 lines) |

### Dependencies & Risks

- **Risk: Merge loses information from duplicated entries.** Mitigation — read all N variants before writing canonical; union the instruction bodies; keep the most specific selector hint from all variants.
- **Risk: Blueprint $variable typo causes `RecipeConfigurationError` at runtime.** Mitigation — test `ActionRecipe.model_validate()` + parameter completeness before committing each file.
- **Risk: unified_components.json field names don't match `ComponentInteraction` dataclass.**  Mitigation — check `unified_registry.py` dataclass field names before writing JSON; run `UnifiedRegistry._ensure_loaded()` smoke test after.
- **Risk: Keyword cleanup removes a term the planner relies on for gate matching in `planner.py`.** Mitigation — `planner.py` keyword gates use `_AC_STEP_KEYWORDS` (separate hardcoded dict in `planner.py`), not the KB KEYWORDS lines. KB KEYWORDS only affect TF-IDF retrieval. Safe to strip.

### Observability Requirements
- **Applies**: No — no HTTP handlers, no workers, no external calls modified

### API Requirements
- **REST API**: No
- **GraphQL API**: No

---

### Work Items

#### WI-knowledge-base-refactor-coverage-expansion-001: Add timing_note to 293 null selector entries
**Status**: Pending
**Phase**: 1
**Dependencies**: None
**Files**: `knowledge/selector_registry.json`
**Implementation**:
- Apply timing inference rules by component type:
  - `p-autocomplete` (autocomplete panel): `"+500ms — wait for options overlay to render"`
  - `p-select` / `p-dropdown` (select overlay): `"+300ms — wait for dropdown overlay animation"`
  - `p-calendar` / `p-datepicker` (calendar panel): `"+400ms — wait for calendar panel animation"`
  - `p-multiselect` (multiselect overlay): `"+300ms — wait for options overlay to render"`
  - `p-confirmdialog` (confirm modal): `"+400ms — wait for dialog animation to complete"`
  - `p-fileupload` (file upload): `"No wait — synchronous DOM update"`
  - Table column header sort click: `"+200ms — wait for Angular sort pipe to re-render rows"`
  - Table row / cell: `"+150ms — wait for Angular change detection on row data"`
  - Form submit button: `"Wait for URL change or toast — do not use fixed wait"`
  - Navigation link / menu item: `"+300ms — wait for Angular router transition"`
  - Modal close / dismiss button: `"+300ms — wait for close animation"`
  - Generic button (no overlay): `"+100ms — single Angular CD cycle"`
- Entries that already have a non-empty `timing_note` must not be modified

#### WI-knowledge-base-refactor-coverage-expansion-002: Add context to 139 empty selector entries
**Status**: Pending
**Phase**: 1
**Dependencies**: WI-knowledge-base-refactor-coverage-expansion-001 (same file — do in one pass)
**Files**: `knowledge/selector_registry.json`
**Implementation**:
- For each entry with empty `context`, write a one-sentence description of when to use this selector, e.g.:
  - Sort column header: `"Use to click a sortable table column header in List View. Not available in Compact View."`
  - Status dropdown trigger: `"Use to open the status dropdown on a Quick Order row. Requires the row to be in editable state."`
  - Login email field: `"Use on the /login page before any authentication has occurred."`
- Follow the style of the 35 entries that already have good `context` text

#### WI-knowledge-base-refactor-coverage-expansion-003: Strip keyword bloat from human_guidance.md
**Status**: Pending
**Phase**: 1
**Dependencies**: None
**Files**: `knowledge/human_guidance.md`
**Implementation**:
- For each of the 75 entries, parse the `KEYWORDS:` line
- Remove any term from the filler set: {successfully, already, because, there, know, from, that, need, type, named, now, this, have, was, were, been, about}
- If resulting term count > 8, keep the 8 most domain-specific terms (prefer PrimeNG component names, vSuite feature names, and UI interaction verbs)
- Minimum 3 terms must remain after stripping

#### WI-knowledge-base-refactor-coverage-expansion-004: Strip keyword bloat from vSuite-actions.md
**Status**: Pending
**Phase**: 1
**Dependencies**: None (parallel with WI-003)
**Files**: `knowledge/vSuite-actions.md`
**Implementation**:
- Same filler-set removal as WI-003, applied to the 51 of 103 entries that have bloat
- Leave the 52 already-clean entries untouched

#### WI-knowledge-base-refactor-coverage-expansion-005: Write Phase 1 tests
**Status**: Pending
**Phase**: 1 (write after WI-001 through WI-004)
**Dependencies**: WI-knowledge-base-refactor-coverage-expansion-001, WI-knowledge-base-refactor-coverage-expansion-002, WI-knowledge-base-refactor-coverage-expansion-003, WI-knowledge-base-refactor-coverage-expansion-004
**Files**: `backend/kb/test_selector_completeness.py` (new)
**Implementation**:
```python
# 4 pytest test functions:
def test_all_selectors_have_timing_note():
    # Load knowledge/selector_registry.json
    # Assert sum(1 for v in selectors.values() if not v.get("timing_note")) == 0

def test_all_selectors_have_context():
    # Assert sum(1 for v in selectors.values() if not v.get("context")) == 0

def test_human_guidance_keyword_max_length():
    # Parse each KEYWORDS: line in human_guidance.md
    # Assert len(terms) <= 8 for all entries

def test_vsuite_actions_keyword_max_length():
    # Same for vSuite-actions.md
```

---

#### WI-knowledge-base-refactor-coverage-expansion-006: Create inline_edit.yaml
**Status**: Pending
**Phase**: 2
**Dependencies**: None
**Files**: `knowledge/blueprints/inline_edit.yaml`
**Implementation**:
- Parameters: `container_selector` (CSS selector for the table row or editable cell container), `value` (text to type)
- Steps:
  1. Double-click the cell (triggers inline edit mode in PrimeNG p-table): `click_count: 2`, `wait_after_ms: 300`
  2. Clear any existing text: `press_key: Control+a`, `wait_after_ms: 100`
  3. `fill` the input that appeared inside the cell with `$value`, `wait_after_ms: 200`
  4. `press_key: Enter` to commit, `wait_after_ms: 400` (Angular CD saves the row)
- `cleanup_on_failure`: press Escape to cancel edit mode
- `verify_after`: `element_visible` on cell text matching `$value`
- `trigger_keywords`: inline edit, edit cell, edit row, click to edit, inline input

#### WI-knowledge-base-refactor-coverage-expansion-007: Create status_dropdown.yaml
**Status**: Pending
**Phase**: 2
**Dependencies**: None
**Files**: `knowledge/blueprints/status_dropdown.yaml`
**Implementation**:
- Parameters: `trigger_selector` (the status badge/button), `option_text` (visible text of the target option)
- Steps:
  1. Click the status trigger to open the overlay/modal, `wait_after_ms: 400`
  2. Wait for the overlay to render (CSS: `.p-select-overlay`, `.p-dropdown-panel`, or `[role=listbox]`)
  3. `click` option matching `$option_text` using `get_by_role("option", name="$option_text")` with fallback `get_by_text("$option_text")`, `wait_after_ms: 300`
  4. Wait for overlay close animation, `wait_after_ms: 300`
- `cleanup_on_failure`: press Escape, then click body to dismiss overlay
- `verify_after`: `element_visible` on trigger element now showing `$option_text`
- `trigger_keywords`: status dropdown, select status, change status, status combobox, update status

#### WI-knowledge-base-refactor-coverage-expansion-008: Create batch_checkbox.yaml
**Status**: Pending
**Phase**: 2
**Dependencies**: None
**Files**: `knowledge/blueprints/batch_checkbox.yaml`
**Implementation**:
- Parameters: `table_selector` (CSS selector for the p-table container), `mode` (`"all"` for header checkbox, `"row"` for individual row), `row_index` (integer, only used when `mode="row"`)
- Steps (mode="all"):
  1. Click `$table_selector th .p-checkbox-box` or `$table_selector [data-p-highlight="false"].p-checkbox` (header checkbox), `wait_after_ms: 200`
  2. Wait for all row checkboxes to reflect selected state, `wait_after_ms: 300`
- Steps (mode="row"):
  1. Click `$table_selector tr:nth-child($row_index) .p-checkbox-box`, `wait_after_ms: 200`
- `cleanup_on_failure`: click the same checkbox again to deselect
- `verify_after`: `element_visible` on selection count badge or `[aria-checked="true"]` attribute
- `trigger_keywords`: select all, batch select, checkbox, select rows, check all, multi-select rows

#### WI-knowledge-base-refactor-coverage-expansion-009: Create approvals_workflow.yaml
**Status**: Pending
**Phase**: 2
**Dependencies**: None
**Files**: `knowledge/blueprints/approvals_workflow.yaml`
**Implementation**:
- Parameters: `item_selector` (CSS selector for the approval item row or card), `action` (`"approve"` or `"deny"`)
- Steps:
  1. Click the approval item to open the detail panel/modal, `wait_after_ms: 500`
  2. Click the `$action` button (`get_by_role("button", name="Approve")` or `get_by_role("button", name="Deny")`), `wait_after_ms: 300`
  3. If confirm dialog appears: click `get_by_role("button", name="Yes")` or `get_by_role("button", name="Confirm")`, `wait_after_ms: 400`
  4. Wait for status badge to update, `wait_after_ms: 500`
- `cleanup_on_failure`: press Escape to close modal/panel
- `verify_after`: `element_visible` on status badge showing "Approved" or "Denied"
- `trigger_keywords`: approve, deny, approve order, deny request, approval workflow, review and approve

#### WI-knowledge-base-refactor-coverage-expansion-010: Create voice_form_combobox.yaml
**Status**: Pending
**Phase**: 2
**Dependencies**: None
**Files**: `knowledge/blueprints/voice_form_combobox.yaml`
**Implementation**:
- Parameters: `combobox_selector` (CSS selector for the p-autocomplete input), `search_text` (text to type into the combobox), `option_text` (exact text of the option to select)
- Steps:
  1. Click the combobox input to focus it, `wait_after_ms: 200`
  2. `fill` with `$search_text`, `wait_after_ms: 500` (debounce — autocomplete fires API call)
  3. Wait for suggestions overlay to appear: `wait_for_selector: .p-autocomplete-panel, .p-autocomplete-items`, timeout 3000ms
  4. Click the option matching `$option_text`: `get_by_role("option", name="$option_text")` with fallback `get_by_text("$option_text")`, `wait_after_ms: 300`
  5. Wait for input to update with the selected value, `wait_after_ms: 200`
- `cleanup_on_failure`: press Escape, then clear the input with triple-click + Delete
- `verify_after`: `element_state` on input field showing `$option_text` as value
- `trigger_keywords`: voice combobox, voice autocomplete, search voice, select voice talent, voice form, voicer, talent combobox

#### WI-knowledge-base-refactor-coverage-expansion-011: Write Phase 2 tests
**Status**: Pending
**Phase**: 2 (after WI-006 through WI-010)
**Dependencies**: WI-knowledge-base-refactor-coverage-expansion-006 through WI-knowledge-base-refactor-coverage-expansion-010
**Files**: `backend/engine/test_blueprint_validation.py` (new)
**Implementation**:
```python
# 9 pytest test functions — 5 new + 4 existing regression:
# For each blueprint:
#   1. Load YAML file
#   2. Call ActionRecipe.model_validate(raw)
#   3. Assert recipe.name is non-empty
#   4. Assert recipe.steps is non-empty
#   5. For each step, assert step.action in {"click","fill","select_option","press_key","wait","set_input_files","wait_for_selector"}
#   6. Assert every $variable in step fields appears in [p.name for p in recipe.parameters]
# New: test_inline_edit_blueprint, test_status_dropdown_blueprint,
#      test_batch_checkbox_blueprint, test_approvals_workflow_blueprint,
#      test_voice_form_combobox_blueprint
# Regression: test_compact_view_navigate_blueprint, test_p_calendar_single_blueprint,
#             test_p_calendar_range_blueprint, test_p_select_column_sort_blueprint
```

---

#### WI-knowledge-base-refactor-coverage-expansion-012: Deduplicate human_guidance.md
**Status**: Pending
**Phase**: 3
**Dependencies**: WI-knowledge-base-refactor-coverage-expansion-003 (Phase 1 keyword cleanup must be done first)
**Files**: `knowledge/human_guidance.md`
**Implementation**:
- Identify the 13 duplicate-name groups. The 3 largest are the priority:
  - **6 × "Navigate to Compact view"** → merge into 1 canonical entry with all distinct instructions unioned; keep best selector hints
  - **4 × "Navigate to Production Orders compact view"** → merge into 1
  - **3 × "Navigate to Production Orders list view"** → merge into 1
- For each merge: read all N variant entries → union the instruction bodies (dedup identical sentences) → write a single canonical entry with the merged content → delete the N-1 duplicates
- Target: ≤ 55 total entries after all merges (from 75)
- Do NOT lose any instruction that appears in only one variant

#### WI-knowledge-base-refactor-coverage-expansion-013: Expand unified_components.json to 11 components
**Status**: Pending
**Phase**: 3
**Dependencies**: None (can run parallel with WI-012)
**Files**: `knowledge/unified_components.json`
**Implementation**:
- Read the 5 missing components from `knowledge/component_registry.json` (`p-multiselect`, `p-checkbox`, `p-confirmdialog`, `p-tablecheckbox`, `p-table-header`) and translate each into the `ComponentInteraction` dataclass schema:
  ```json
  {
    "key": "p-multiselect",
    "description": "...",
    "primeng_versions": ["v17","v18","v19"],
    "selectors": [{"method":"css_selector","selector":"p-multiselect","confidence":0.8,...}],
    "interaction_protocol": [{"action":"click","wait_after_ms":300,...}],
    "forbidden_patterns": [...],
    "angular_quirks": [...],
    "animation_budget": {"open_ms":300,"close_ms":200,"debounce_ms":0,"verifier_wait_ms":400},
    "trigger_keywords": [...],
    "related_recipe": ""
  }
  ```
- Promote the 6 existing stubs (`p-calendar`, `p-autocomplete`, `p-select`, `p-table`, `p-toast`, `p-fileupload`) from minimal stubs to full `ComponentInteraction` entries — add `interaction_protocol`, `forbidden_patterns`, `angular_quirks`, `animation_budget`, `trigger_keywords`, and `related_recipe` where applicable (e.g., `p-calendar` → `related_recipe: "p_calendar_single"`)

#### WI-knowledge-base-refactor-coverage-expansion-014: Write Phase 3 tests
**Status**: Pending
**Phase**: 3 (after WI-012 and WI-013)
**Dependencies**: WI-knowledge-base-refactor-coverage-expansion-012, WI-knowledge-base-refactor-coverage-expansion-013
**Files**: `backend/kb/test_matcher.py` (extend), inline assertions
**Implementation**:
- Add to `backend/kb/test_matcher.py`:
  ```python
  # 10 ground-truth retrieval tests:
  @pytest.mark.parametrize("query,expected_workflow_substring", [
      ("Sort the table by due date", "sort"),
      ("Log in as Account Executive", "login"),
      ("Navigate to compact view", "compact"),
      ("Double-click inline cell to edit", "inline"),
      ("Approve the pending order", "approv"),
      ("Select multiple rows with checkbox", "batch"),
      ("Select status from dropdown combobox", "status"),
      ("Upload a file to the order", "upload"),
      ("Enter due date in calendar picker", "calendar"),
      ("Create a new quick order", "quick order"),
  ])
  def test_kb_retrieval_accuracy(query, expected_workflow_substring):
      result = kb.query_with_expansion(query)
      assert result is not None and expected_workflow_substring.lower() in result.lower()

  def test_human_guidance_entry_count():
      count = human_guidance_md.count("## WORKFLOW:")
      assert count <= 55

  def test_unified_registry_covers_all_legacy_components():
      from backend.kb.unified_registry import unified_registry
      expected = {"p-calendar","p-autocomplete","p-multiselect","p-checkbox",
                  "p-table","p-toast","p-confirmdialog","p-fileupload",
                  "p-tablecheckbox","p-table-header","p-select"}
      loaded = {c.key for c in unified_registry.all_components()}
      assert expected.issubset(loaded)
  ```

## Creative Phases

(none required)

---

## Execution State

**Build Status**: IDLE
**Current Build**: knowledge-base-refactor-coverage-expansion — COMPLETE
**Build Started**: 2026-05-07
**Phase Number**: 3 of 3
**Is Multi-Phase**: YES
**Current Phase**: COMPLETE

### Current Build Step
**Step**: Phase 3 - COMPLETE
**Status**: COMPLETE
**Completed**: 2026-05-07
**Output**: 25/25 tests passing, code review APPROVED, all 3 phases complete

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/1
**Notes**: Task COMPLETE (2026-05-07). PR #1 created: feature/FEAT-003-kb-refactor-coverage → main.

### Active Sub-Agents
(none)

### Completed Steps
- [x] Step 3 — Spec Writer Agent (COMPLETE — 2026-05-07)
- [x] Step 5 — Implementation Plan (COMPLETE — 2026-05-07)
- [x] Step 0.5 — Git Setup: COMPLETE (2026-05-07) — Feature branch feature/FEAT-003-kb-refactor-coverage created
- [x] Step 1 — Read Task Context: COMPLETE (2026-05-07) — Phase 1 of 3 identified
- [x] Phase 1 — COMPLETE (2026-05-07) — 293 timing_notes, 139 contexts, 125 keyword lines trimmed; 4/4 tests pass; code review APPROVED
- [x] Phase 2 — COMPLETE (2026-05-07) — 5 blueprints created (inline_edit, status_dropdown, batch_checkbox, approvals_workflow, voice_form_combobox); idempotency pre-check bypass applied; 9/9 tests pass; code review APPROVED
- [x] Phase 3 — COMPLETE (2026-05-07) — human_guidance.md 75→51 entries; unified_components.json 6→11 components; 25/25 tests pass; code review APPROVED
