---
legacy_id: aria-tree-pruning
---
# aria-tree-pruning: ARIA Tree Pruning

**Complexity**: Level 3
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: High
**Branch**: feature/aria-tree-pruning-aria-tree-pruning
**Worktree**: N/A
**Roadmap**: FEAT-025

---

## Task Description

Filter the ARIA accessibility tree to only include elements relevant to the current AC step's target element types before injecting it into the planner prompt (FM-6). Uses the `target_element_types` output from the AC enrichment engine to prune irrelevant elements. Reduces prompt size from 15K→3K tokens on dense pages (production orders table with 50+ rows).

---

## Acceptance Criteria

- AC-HAPPY-1: ARIA tree is filtered to include only elements matching `target_element_types` from AC enrichment.
- AC-HAPPY-2: Prompt size is significantly reduced (target 15K -> 3K tokens on dense pages).
- AC-HAPPY-3: Planner can still successfully identify and interact with target elements after pruning.
- AC-ERROR-1: System handles cases where `target_element_types` is empty or missing by falling back to a safe default (e.g., viewport-based or no pruning).
- AC-REGRESS-1: No regressions in existing tests for planner and enrichment.

---

## Design Decisions (Resolved)

### DD-1: Pruning Algorithm → Hybrid (role-primary + viewport-secondary)

**Role-only** is too aggressive — drops spatial context the LLM needs to disambiguate elements (e.g., "which Submit button?"). **Viewport-only** doesn't solve the actual problem (50 *in-viewport* table rows on Production Orders). **Hybrid** does role filtering first using `target_element_types` (already computed by the Compiler LLM in `graph_orchestrator.py:_run_compiler_preprocessor()` but never applied as an actual filter), then sorts remaining elements by viewport visibility.

Two-pass filter:
1. **Pass 1 — Role filter**: Keep elements whose role is in `target_element_types ∪ ALWAYS_KEEP_ROLES`.
2. **Pass 2 — Viewport sort**: In-viewport elements go to PRIMARY section, off-screen to SECONDARY (both included, different priority).

### DD-2: Surprise Elements → `ALWAYS_KEEP_ROLES` Safelist

A constant set of ARIA roles **never pruned** regardless of `target_element_types`:
- **Dismissal/overlay**: `dialog`, `alertdialog`
- **Navigation**: `navigation`, `tab`, `tablist`
- **Feedback**: `alert`, `status`, `progressbar`
- **Page structure**: `heading`, `main`, `banner`

Plus name-pattern matching for:
- Dismiss controls: name contains "close", "dismiss", "cancel"
- Pagination: name contains "next page", "previous page"
- Known global actions: "New Request +", "Logout"

Additive, auditable, extensible via HITL feedback.

### DD-3: Where to Prune → Two-Stage Pipeline

- **Stage 1 — `accessibility.py`** (structural, always-on): Apply `ALWAYS_KEEP_ROLES` safelist, viewport sorting, `SKIP_ROLES` removal. No knowledge of current AC step needed.
- **Stage 2 — `planner.py`** (semantic, per-step): Read `target_element_types` from `VQAState`, filter extracted elements to `target_element_types ∪ ALWAYS_KEEP_ROLES`, format as compact summary.
- **Stage 3 — `prompt_budget.py`** (existing): Budget-based truncation as final safety net.

This splits concerns cleanly: `accessibility.py` owns *what* to extract, `planner.py` owns *what's relevant*, `prompt_budget.py` owns *what fits*.

> **Key finding**: `target_element_types` is already computed in `graph_orchestrator.py` L422-487 but only injected as a `<dom_filter>` text hint in the Commander instruction (L641-651). It is never written to `VQAState` or used for actual tree filtering. FEAT-025 closes this gap.

### DD-4: Multiple Strategies → Yes, config-flagged with `"hybrid"` default

Add to `config.py`:
- `aria_pruning_strategy: str = "hybrid"` — options: `"none"` | `"role_only"` | `"viewport_only"` | `"hybrid"`
- `aria_pruning_safelist_enabled: bool = True`
- `aria_pruning_viewport_margin: int = 100` — pixels beyond viewport
- `aria_pruning_max_elements: int = 40` — hard cap on pruned count

`"none"` disables pruning for debugging. Others enable A/B comparison. Follows the same config-flag pattern as FEAT-022 and FEAT-023.

> ⛔ Do NOT implement a per-step dynamic strategy selector — that adds an LLM call and defeats the purpose of reducing LLM cost.

---

## Affected Components

- `backend/config.py` — Add 4 pruning config fields (strategy, safelist, viewport margin, max elements).
- `backend/engine/state.py` — Add `target_element_types: list[str]` to `VQAState` schema.
- `backend/browser/accessibility.py` — Add `ALWAYS_KEEP_ROLES` constant, `viewport_classify()` helper, update `extract_interactive_summary()` for Stage 1 structural pruning.
- `backend/engine/planner.py` — Add `prune_interactive_elements()` function, wire into `_planner_node_inner()` for Stage 2 semantic pruning.
- `backend/engine/graph_orchestrator.py` — Write `target_element_types` from Compiler output to `VQAState` (currently only used as Commander text hint at L641-651).

---

## Test Strategy

### Approach
- **Emphasis**: Unit-heavy for pruning logic; integration tests using static ARIA tree snapshots.
- **Target test count**: 8-10 tests

### Test Targets
- `prune_interactive_elements()` (new function in planner.py)
- `viewport_classify()` (new helper in accessibility.py)
- `extract_interactive_summary()` (updated to support ALWAYS_KEEP_ROLES)
- Config flag toggling (none/role_only/viewport_only/hybrid)

### What NOT to Test
- Actual Playwright browser interactions (unless adding a small smoke test).
- LLM response quality (tested via prompt engineering/evals).

---

## Implementation Roadmap
- [x] Phase 1: Research existing ARIA tree structure and `target_element_types` pipeline. ✅ (Design Decisions resolved — see above)
- [x] Phase 2: Add config fields to `config.py` + `target_element_types` field to `VQAState` in `state.py`.
- [x] Phase 3: Implement Stage 1 structural pruning in `accessibility.py` (`ALWAYS_KEEP_ROLES`, `viewport_classify()`).
- [x] Phase 4: Implement Stage 2 semantic pruning in `planner.py` (`prune_interactive_elements()`).
- [x] Phase 5: Wire `target_element_types` from `graph_orchestrator.py` Compiler output into `VQAState`.
- [x] Phase 6: Write unit tests (8-10 tests) and verify token reduction + planner accuracy.

---

## Execution State

**Build Status**: ARCHIVED
**Last Completed**: N/A
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
(none)
