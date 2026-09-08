# Archive: headful-playwright-execution-and-test-persistence — Headful Playwright Execution & Test Persistence

**Archived**: 2026-05-19
**Complexity**: Level 3
**Feature**: FEAT-043
**Branch**: feature/FEAT-043-headful-playwright-test-persistence
**Status**: COMPLETE

---

## Task Summary

Two complementary improvements to the vQA AI-driven testing infrastructure:

1. **Headful Playwright Toggle** — `VQA_HEADLESS=0` env-var gate (normalized from partially-wired state) with full unit test coverage, `.env.example` documentation, and `DEPLOYMENT.md` operator instructions.

2. **Test Persistence & Smart Replay** — `POST /runs/{run_id}/accept` endpoint serializes an accepted run's action log into a filesystem-backed JSON spec. On subsequent `/execute` calls for the same ticket+AC hash, the `replay_check_node` short-circuits the LangGraph graph, replaying the deterministic action sequence via the existing `executor.py` dispatch and bypassing the LLM planner entirely. On replay failure, transparent fallback to AI generation with log entry `REPLAY_FAILED: falling back to AI generation`.

---

## Acceptance Criteria Delivery

| Criterion | Priority | Status |
|-----------|----------|--------|
| AC-ENTRY-1: VQA_HEADLESS discoverable in `.env.example` + `DEPLOYMENT.md` | MUST | ✅ |
| AC-HAPPY-1: Headful mode → `chromium.launch(headless=False)` + log line | MUST | ✅ |
| AC-HAPPY-2: `POST /runs/{run_id}/accept` creates file + updates index | MUST | ✅ |
| AC-HAPPY-3: Smart replay bypasses LLM planner | MUST | ✅ |
| AC-ERROR-1: Replay fallback on selector mismatch | MUST | ✅ |
| AC-ERROR-2: Accept endpoint rejects non-terminal runs (400) | MUST | ✅ |
| AC-NAV-1: Accepted tests persist across server restarts | MUST | ✅ |

All 7 MUST criteria satisfied. No scope creep.

---

## Implementation Summary

### Phase 1 — Headful Toggle & Configuration

**Commits**: `91d9bd2`
**Files changed**: 4

- `tests/test_headless_toggle.py` (new) — 13 tests covering `VQA_HEADLESS=0/1/absent`
- `backend/config.py` — Added `is_headless`, `accepted_tests_dir`, `enable_smart_replay` settings
- `.env.example` — `VQA_HEADLESS` documented with full comment
- `DEPLOYMENT.md` — Headful mode setup section added

### Phase 2 — Accepted Test Storage Layer

**Commits**: `64d5772`
**Files changed**: 5

- `backend/storage/spec_serializer.py` (new) — Pure function filtering `success=True` steps to `(action_type, selector, value)` triples
- `backend/storage/accepted_tests.py` (new) — `AcceptedTestStore` with threading lock, JSON index, `accept_run()`, `find_accepted_test()`, `list_accepted_tests()`, `last_used` timestamp
- `backend/api/routes.py` — `POST /runs/{run_id}/accept` endpoint added
- `tests/test_accepted_test_store.py` (new) — 26 tests
- `tests/test_api_accept_endpoint.py` (new) — 6 tests (200/400/404 coverage)

### Phase 3 — Smart Replay Engine

**Commits**: `9372f3e`
**Files changed**: 3

- `backend/engine/replay_engine.py` (new) — `ReplayEngine` with `find_match()` and `replay()` methods; wraps executor dispatch; `TimeoutError`/`PlaywrightError` → `REPLAY_FAILED` fallback
- `backend/engine/graph.py` — `replay_check_node` inserted before `jira_fetch_node` via `add_conditional_edges` with `route_after_replay_check()`
- `tests/test_replay_engine.py` (new) — 12 tests (happy path, fallback, AC hash mismatch, LLM-not-called assertion)

**Total**: 13 files touched, 57 new tests, 3 commits

---

## Test Coverage Added

| Test File | Test Count | Coverage |
|-----------|-----------|----------|
| `tests/test_headless_toggle.py` | 13 | `VQA_HEADLESS` env-var logic, `_get_slow_mo()` |
| `tests/test_accepted_test_store.py` | 26 | `AcceptedTestStore.accept_run()`, `find_accepted_test()`, index persistence, threading |
| `tests/test_api_accept_endpoint.py` | 6 | `POST /runs/{run_id}/accept` — 200, 400, 404 |
| `tests/test_replay_engine.py` | 12 | Replay happy path, fallback on error, AC hash matching, LLM bypass |
| **Total** | **57** | |

Final suite: **340/340 passing** (1 pre-existing unrelated failure in `test_kb_matcher.py`)

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Filesystem-backed index (not SQLite) | Small index, thread-locked, matches existing `SuiteStore` precedent; no new infra dependency |
| Reuse `executor.py` dispatch in ReplayEngine | Preserves all existing guards (slowMo, video recording, toast observer); zero code duplication |
| Identity key = `ticket_id` + SHA-256(ac_text)[:8] | Negligible collision probability for vQA scale; full hash in index for debugging |
| `replay_check_node` before `jira_fetch_node` | Avoids redundant Jira API call for cache hits; <1ms overhead on misses |
| `ACCEPTED_TESTS_DIR` env-var | 12-Factor; enables future S3/Postgres migration without code changes |

---

## Key Learnings Extracted

### New Rules Added to Learned Rule Files

**`storage-layer-pattern.md`** (2 new rules):
- `storage-layer-pattern`: Threading-lock + JSON-index pattern for filesystem stores
- `replay-spec-filter`: Filter success-only steps when serializing for replay

**`testing-patterns.md`** (1 new rule):
- `env-var-normalization`: Normalize boolean env-vars to 3 cases (0/1/absent), test all three

**`evaluator-routing.md`** (reinforced):
- `langgraph-node-insertion`: LangGraph `add_conditional_edges` pattern for pre-check nodes

### Workflow Learnings

1. **Phase boundary discipline pays off** — Clean 3-phase separation (config/docs → storage → replay) yielded independently-reviewable commits with linear test growth and zero cross-phase rework.
2. **Pre-wired env-vars need explicit test coverage** — `VQA_HEADLESS` existed without tests; normalized and covered as part of this task.

---

## Technical Debt Carried Forward

| Item | Priority | Notes |
|------|----------|-------|
| `last_used` pruning logic | Low | `last_used` timestamp is written; prune-on-startup for entries >30 days is not yet implemented |
| Shared storage for multi-operator deployments | Low | `ACCEPTED_TESTS_DIR` env-var enables future S3/Postgres backend; current filesystem approach requires NFS mount for shared usage |
| Accept partial-success runs | Low | Currently only fully-PASS runs can be accepted; future: accept N-of-M AC steps |

---

## Commits

| Commit | Message |
|--------|---------|
| `91d9bd2` | `feat(headful-playwright-execution-and-test-persistence): Phase 1 — VQA_HEADLESS toggle, accepted_tests_dir/enable_smart_replay config, deployment docs` |
| `64d5772` | `feat(headful-playwright-execution-and-test-persistence): Phase 2 — AcceptedTestStore, spec_serializer, accept API endpoints` |
| `9372f3e` | `feat(headful-playwright-execution-and-test-persistence): Phase 3 — ReplayEngine, replay_check_node, Smart Replay graph integration` |

---

## References

- **Task**: `memory-bank/tasks/headful-playwright-execution-and-test-persistence.md`
- **Reflection**: `memory-bank/reflection/reflection-headful-playwright-execution-and-test-persistence.md`
- **Feature**: FEAT-043 in `memory-bank/roadmap.md`
- **Branch**: `feature/FEAT-043-headful-playwright-test-persistence`
