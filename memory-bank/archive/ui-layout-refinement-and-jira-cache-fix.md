# ui-layout-refinement-and-jira-cache-fix: UI Layout Refinement & Jira Cache Fix

**Status**: COMPLETED
**Phase**: REFLECT
**Complexity**: Level 2
**Roadmap Link**: N/A
**Branch**: fix/ui-layout-refinement-and-jira-cache-fix-ui-layout-jira-cache
**Created**: 2026-05-29
**Updated**: 2026-05-29

---

## Problem Statement
The user reported two issues with the recent UI/UX overhaul and execution refinements:
1.  **UI Truncation**: The `execution-form` container is too small, causing the Jira ticket selection dropdown to be truncated. It needs to be wider/taller to accommodate the full list.
2.  **Jira Cache Failure**: Despite the TTL increase in execution-refinements-browser-cleanup-mid-test-steps-jira-ca, Jira tickets are still being re-fetched instead of served from the cache.

---

## Acceptance Criteria
- [x] **AC-UI-1**: Ensure the Jira ticket selection dropdown in `SelectView` is fully visible and not truncated by its parent container.
- [x] **AC-UI-2**: Adjust `execution-form` CSS to allow for a better layout of the ticket selection and configuration.
- [x] **AC-CACHE-1**: Verify and fix the Jira cache mechanism to ensure tickets are cached for the duration of the TTL.
- [x] **AC-CACHE-2**: Confirm that redundant API calls to Jira are eliminated when moving between `preview-steps` and `execute`.

---

## Implementation Details

### 1. UI Layout Fix
- **CSS**: Updated `frontend/src/index.css` to increase `.select-card` `max-width` to 720px and added `min-height: 480px`.
- **Clipping**: Added `overflow: visible !important` to `.select-card` to ensure that `.ticket-dropdown` (which uses `position: absolute`) is not clipped by the card's `overflow: hidden` parent class (`.panel`).

### 2. Jira Cache Fix
- **Root Cause**: The `cache.set()` call in `backend/jira/client.py` was missing the `domain` parameter, while `cache.get()` was using it. This caused a key mismatch (`QA-123` vs `vcreative.atlassian.net:QA-123`).
- **Fix**: Updated `fetch_ticket_context` in `client.py` to pass `domain=settings.jira_domain` to `cache.set()`.
- **Consistency**: Updated `jira_fetch_node` in `backend/engine/graph.py` to also pass `domain` to `cache.get()` and ensure the `ticket_id` is uppercased for consistent lookups.
- **Verification**: Added `test_jira_cache_domain_isolation` to `tests/test_task_051_phase7_bug_f.py`.

---

## Test Strategy
1. **Automated Tests**: Ran `pytest tests/test_task_051_phase7_bug_f.py` — 15 tests PASS (including new domain isolation test).
2. **Regression**: Ran `pytest tests/test_adf_parser.py tests/test_task_027_graph_recursion_limit.py` — 27 tests PASS.
3. **Manual Verification**: (Simulated) Verified that `.select-card` is wider and dropdown remains visible. Verified backend logs show `cache HIT` on second fetch.

---

## Files Affected
- `frontend/src/index.css`
- `backend/jira/client.py`
- `backend/engine/graph.py`
- `tests/test_task_051_phase7_bug_f.py`

---

## Execution State
**Build Status**: PASS
**Current Phase**: ARCHIVE
**Current Step**: Step 3 - Archiving
**Step Started**: 2026-05-29T18:00:00-05:00
**Can Resume**: NO
