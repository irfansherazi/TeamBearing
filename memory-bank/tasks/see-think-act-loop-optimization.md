---
legacy_id: see-think-act-loop-optimization
---
# see-think-act-loop-optimization: See-Think-Act Loop Optimization

**Complexity**: Level 4
**Status**: COMPLETE
**Roadmap**: [FEAT-071: See-Think-Act Loop Optimization](../roadmap.md#feat-071-see-think-act-loop-optimization)
**Branch**: feature/FEAT-071-loop-optimization
**Worktree**: .worktrees/FEAT-071
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/33

## Task Description

Optimize the core reasoning and execution loop of the vQA agent to improve token efficiency, retrieval accuracy, and browser execution performance. This is achieved through three architectural pillars:
1. **Dense Semantic Embeddings**: Replace TF-IDF retrieval in `loader.py` with a ChromaDB-backed vector store using `all-MiniLM-L6-v2` embeddings in `backend/kb/rag.py` to query `human_guidance.md` based on semantic intent rather than keyword/literal matching.
2. **Semantic DOM Culling**: Filter out structural boilerplate and non-interactive container nodes from the accessibility tree in `planner.py`, aiming for a ≥40% reduction in token consumption while preserving critical interaction points.
3. **VLM/Local Model Split-Execution**: Implement a split-execution coordinate-based action path where the planner VLM (Claude Sonnet) outputs high-level semantic targets (e.g. `{"action": "semantic_click", "target": "Save button"}`) on a clean screenshot, and a local resolver calculates the exact screen coordinates of the target using local layout extraction, bypassing the slow and cluttered visual Set-of-Marks overlay.

---

## User Journey Definition

**Feature Type**: NFR/Infrastructure
**Creative Phase Required**: Yes - Architecture & User Journey

### Verification Method
- **Test method**: Run the custom pytest suite:
  ```bash
  .venv/bin/pytest tests/test_task_094_loop_optimization.py -v
  ```
- **Success metrics**:
  - Semantic RAG retrieves relevant human guidance entries for queries with zero exact keyword overlaps (e.g., "how to sort due date in list view" matches "List View Sorting").
  - Semantic DOM Culling reduces character/token footprint of the formatted ARIA tree by ≥40% compared to raw snapshots.
  - Split-Execution successfully maps a semantic action `{"action": "semantic_click", "target": "Submit button"}` to the correct viewport coordinates using local DOM mapping.
- **Observable at**:
  - `backend/kb/rag.py` and `backend/kb/loader.py` logs confirming ChromaDB query hits.
  - `planner.py` debug logs showing the size comparison before and after culling (e.g. `Pruned ARIA tree from 25000 chars to 12500 chars (50.0% reduction)`).
  - `executor.py` executing a mouse click on resolved coordinates.

---

## Acceptance Criteria

### AC-VERIFY-1: Dense Semantic Embeddings for Guidance
**Priority**: MUST

**Given** a user query representing intent (e.g., "sorting compact view client")
**When** queried against the knowledge base
**Then**:
- The retrieval system queries a ChromaDB vector store collection named `human_guidance` initialized in `backend/kb/rag.py`.
- The vector store uses local `all-MiniLM-L6-v2` embeddings.
- The retrieval returns relevant workflows from `human_guidance.md` even when literal keyword matches are absent.

**Verification**:
- [x] Unit tests verify `HumanGuidanceVault` indexing and query.
- [x] Integration tests verify `loader.py` routes queries through the new vault.

### AC-VERIFY-2: Semantic DOM Culling
**Priority**: MUST

**Given** a raw ARIA accessibility tree text snapshot
**When** processed before inclusion in the planner prompt
**Then**:
- Boilerplate structural tags (e.g., empty `[generic]`, `[none]`, `[presentation]` nodes, and deeply nested container branches with no interactive children) are filtered.
- The total character count of the tree is reduced by ≥40%.
- Interactive elements (links, buttons, textboxes, comboboxes) and safety container elements (such as `dialog`, `alert`, `navigation`, `tab`) are fully preserved.

**Verification**:
- [x] Unit tests verify culling logic on sample dense ARIA trees.
- [x] Logs print the size reduction percentage on every planner iteration.

### AC-VERIFY-3: VLM/Local Model Split-Execution
**Priority**: MUST

**Given** a clean browser screenshot and a step goal
**When** the multimodal VLM planner decides to interact with an element
**Then**:
- The planner outputs a semantic action: `{"action": "semantic_click", "target": "Save button"}` or `{"action": "semantic_fill", "target": "Folder name input", "value": "Beta Folder"}`.
- A local element resolver uses Playwright's handle evaluation or local DOM bounds querying to locate the element matching the target description.
- The executor performs a mouse click on the exact resolved canvas coordinates.
- Pre-drawing and rendering visual SoM bounding boxes is bypassed.

**Verification**:
- [x] Mock tests verify that a planner semantic action is successfully resolved to (x, y) coordinates.
- [x] Integration tests verify the executor dispatches mouse actions to the resolved coordinate coordinates.

---

## Test Strategy

### Approach
- **Emphasis**: Unit-heavy for the culler and vector database querying, mock integration tests for the split-execution coordinates resolver.
- **Target test count**: 6-8 total tests.

### File Organization
- **New test files**:
  - `tests/test_task_094_loop_optimization.py`: Verifies `HumanGuidanceVault`, `semantic_dom_cull`, and `LocalObjectDetector` coordinate resolution.

### What NOT to Test
- We will not test live Bedrock API network calls or real coordinate-based clicks on a live browser. These will be mocked out using standard unittest mocks.

---

## Implementation Roadmap

- [x] **Phase 1: Dense Semantic Embeddings for Guidance**
  - [x] Implement `HumanGuidanceVault` in `backend/kb/rag.py` using ChromaDB and `all-MiniLM-L6-v2`.
  - [x] Parse and index `human_guidance.md` sections (split on `## WORKFLOW:`) into the collection on startup or hot-reload.
  - [x] Update `loader.py` to route query logic through `HumanGuidanceVault` for guidance matching.
- [x] **Phase 2: Semantic DOM Culling**
  - [x] Implement a `SemanticDOMCuller` utility inside `backend/engine/culler.py`.
  - [x] Filter non-interactive layout wrapper nodes while protecting interactive controls and safety landmarks.
  - [x] Integrate culler in `planner.py` before prompting Bedrock, logging character reduction statistics.
- [x] **Phase 3: Split-Execution Coordinate Resolution**
  - [x] Extend the planner actions schema to support semantic actions: `semantic_click` and `semantic_fill`.
  - [x] Implement `LocalObjectDetector` in `backend/browser/vision_utils.py` that maps a target description (role, name, text) to exact canvas coordinates.
  - [x] Wire executor to resolve semantic targets and execute coordinate-based clicks/actions.

---

## Execution State

**Build Status**: COMPLETE
**Current Phase**: None
**Current Step**: None
**Step Started**: None
**Can Resume**: NO
**Worktree Cleaned**: YES
**Branch Deleted**: NO (preserved for PR)

### Active Sub-Agents
- User Journey Design: COMPLETE
- Architecture Design: COMPLETE

### Completed Steps
- User Journey Creative Design: COMPLETE (2026-06-02T10:20:00-05:00) - Output: memory-bank/creative/see-think-act-loop-optimization-loop-optimization-user-journey.md
- Architecture Creative Design: COMPLETE (2026-06-02T10:20:00-05:00) - Output: memory-bank/creative/see-think-act-loop-optimization-loop-optimization-architecture.md
