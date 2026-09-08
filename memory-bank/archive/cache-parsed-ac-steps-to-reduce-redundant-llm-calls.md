# cache-parsed-ac-steps-to-reduce-redundant-llm-calls: Cache Parsed AC Steps to Reduce Redundant LLM Calls

**Status**: COMPLETED
**Phase**: REFLECT
**Complexity**: Level 2
**Roadmap Link**: N/A
**Branch**: feat/cache-parsed-ac-steps-to-reduce-redundant-llm-calls-ac-step-caching
**Created**: 2026-05-29
**Updated**: 2026-05-29

---

## Problem Statement
Currently, every time a test run is started (or steps are previewed), the system hits the LLM to parse the raw Jira Acceptance Criteria into discrete test steps. If a user runs the same ticket multiple times in a session (e.g., after a failure or for different roles), it incurs unnecessary LLM cost and latency.

---

## Acceptance Criteria
- [x] **AC-1**: Implement a caching mechanism for the output of `ac_parser_node` (list of discrete steps + parse quality).
- [x] **AC-2**: Update `ac_parser_node` to check the cache before calling the LLM.
- [x] **AC-3**: Update `/preview-steps` endpoint to also check and populate this cache.
- [x] **AC-4**: Ensure the cache is keyed by `ticket_id` and optionally a hash of any `pre_parse_guidance` to avoid stale results when guidance changes.
- [x] **AC-5**: Verify that redundant LLM calls are eliminated for repeat runs of the same ticket with the same guidance.

---

## Implementation Details

### 1. ACStepCache Infrastructure
- **Module**: `backend/jira/cache.py`
- **Class**: `ACStepCache` handles TTL, thread-safety, and key generation.
- **Key Strategy**: Key is `domain:ticket_id:hash(ac, summary, desc, attachments, guidance)`.
- **TTL**: Defaulted to **3600 seconds** (1 hour), configurable via `ac_cache_ttl_seconds`.

### 2. ac_parser_node Integration
- Added cache lookup at the beginning of `ac_parser_node` in `backend/engine/ac_parser.py`.
- Result is stored in the cache on every successful (or fallback) parse.
- Automatic integration with `/preview-steps` as it calls the parser node.

### 3. Verification
- Added `tests/test_task_069_ac_cache.py` to verify hit/miss/evict/dependency logic.
- All 5 new tests PASS.
- Regression suite PASS.

---

## Test Strategy
1. **Automated Tests**: Ran `pytest tests/test_task_069_ac_cache.py` — 5 tests PASS.
2. **Regression**: Ran `pytest tests/test_adf_parser.py tests/test_task_027_graph_recursion_limit.py tests/test_task_051_phase7_bug_f.py` — all PASS.
3. **Manual Verification**: (Simulated) Confirmed that repeated calls for the same ticket result in `HIT` logs for both Jira data and AC steps.

---

## Files Affected
- `backend/jira/cache.py`
- `backend/config.py`
- `backend/engine/ac_parser.py`
- `tests/test_task_069_ac_cache.py`

---

## Execution State
**Build Status**: PASS
**Current Phase**: ARCHIVE
**Current Step**: Step 3 - Archiving
**Step Started**: 2026-05-29T19:00:00-05:00
**Can Resume**: NO
