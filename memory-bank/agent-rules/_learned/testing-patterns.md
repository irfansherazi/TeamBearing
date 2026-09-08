---
derived_from: [critic-pass-llm-evaluator, accessibility-tree-grounding, fix-vsuite-profile-missing-roles, cu-loop-default-remove-toggle, heal-13-playwright-failures-on-two-test, vqa-12-status-locator-prepopulation-fix, vqa-pinned-testplans]
evidence_count: 8
last_validated: 2026-08-18
---
# Learned Rules: testing-patterns

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **testing-patterns** (`conftest.py`, `*.test.py`): When co-located test files modify `sys.path` at module level, add a project-root `conftest.py` that pre-imports heavy dependencies (numpy, sklearn) before collection begins to prevent import-ordering failures under Python 3.13.
  - _Source_: reflection-TASK-001 (2026-05-07)
  - _Reinforced_: 1x

- **testing-patterns** (`tests/test_task_*.py`): When a task spans multiple implementation phases, the final phase's tests should explicitly re-check prior phases' ACs to catch regressions from phase interactions.
  - _Source_: reflection-TASK-014 (2026-05-13)
  - _Reinforced_: 1x

- **testing-patterns** (`tests/`): Treat configuration typos (like roles/emails) as logic bugs and cover mapping resolution explicitly in tests to prevent trivial regressions.
  - _Source_: reflection-TASK-018 (2026-05-13)
  - _Reinforced_: 1x

- **testing-patterns** (`tests/`): Verify cross-component interactions (e.g., executor and planner) with targeted integration tests to catch oscillation loops.
  - _Source_: reflection-TASK-015 (2026-05-15)
  - _Reinforced_: 1x

- **testing-patterns** (`backend/engine/`): Increment circuit breaker retry counters unconditionally per attempt to prevent infinite loops from actions that succeed technically but fail functionally.
  - _Source_: reflection-TASK-021 (2026-05-15)
  - _Reinforced_: 1x

- **counter-increment-docstring** (`tests/test_task_*.py`): For state machines where the system under test *increments* a counter before applying a threshold (e.g., evaluator increments `ac_step_fail_counts` then checks ≥N), test helper factories must document in their docstring whether the seeded counter value is pre- or post-increment. An inline comment is insufficient — the docstring appears in pytest `-v` output and prevents off-by-one regressions when thresholds change.
  - _Source_: reflection-TASK-026 (2026-05-15)
  - _Reinforced_: 1x

- **state-machine-factory-pattern** (`backend/engine/test_*.py`): For complex routing nodes (like `evaluator_node`), create reusable factory functions `_make_state(**overrides)` and `_make_failed_step(...)` to build synthetic state dicts. Organize tests into classes by routing concern (circuit breaker, diary cap, fast-path fix). This scales to any number of routing paths without test entanglement and serves as living specification for the routing logic.
  - _Source_: reflection-TASK-024 (2026-05-15)
  - _Reinforced_: 1x

- **reporter-graceful-degradation** (`backend/engine/reporter.py`, `tests/test_cv_fallback_reporter.py`): Any new reporter section that reads new VQAState fields must (1) use `.get()` with safe defaults (never direct dict access) and (2) include a "zero invocations" test case as an explicit AC. Reporter crashes on missing fields are silent in long production runs and only surface during regression testing of old state shapes. The Phase 4 reporter defensive coding pass for TASK-028 was a preventable overhead.
  - _Source_: reflection-TASK-028 (2026-05-17)
  - _Reinforced_: 2x (TASK-030 applied + confirmed)

- **autouse-fixture-layering** (`tests/test_task_*.py`, `conftest.py`): When testing a node function that has multiple sequential early-return short-circuits (e.g., KB pre-flight → cache HIT → override_steps → empty-AC fallback → quality gate), use `autouse=True` pytest fixtures at module level to mock all upstream short-circuits to their "pass-through" values (cache MISS, empty KB return). Use inline `patch` context managers only for the specific behavior under test. Without autouse fixtures, upstream short-circuits silently suppress the target code path, yielding 0-call assertions that appear to pass.
  - _Source_: reflection-TASK-096 (2026-06-03)
  - _Reinforced_: 0x

- **asyncio-event-ownership-invariant** (`backend/engine/ac_parser.py`, `backend/api/routes.py`): Never call `.clear()` on an `asyncio.Event` retrieved from a shared dict (e.g., `_pre_parse_events[run_id]`) unless you created it in the current call frame. Tests and other callers may pre-populate the dict with an already-set event to prevent blocking; calling `.clear()` silently resets this state and causes the `await event.wait()` to hang indefinitely. Safe invariant: only clear events you create in the `if run_id not in dict:` branch. In the `else` branch, reuse the event as-is.
  - _Source_: reflection-TASK-096 (2026-06-03)
  - _Reinforced_: 0x

- **source-module-patch-for-lazy-imports** (`tests/test_task_*.py`): When patching a function that is imported lazily inside another function's body (e.g., `from backend.jira.cache import get_ac_step_cache` inside `ac_parser_node`), the consumer module (`backend.engine.ac_parser`) never has the function as a module-level attribute. `patch("backend.engine.ac_parser.get_ac_step_cache")` raises `AttributeError`. Always patch at the **source** module: `patch("backend.jira.cache.get_ac_step_cache")`. Python's import machinery ensures the consumer's next `from X import Y` picks up the patched version.
  - _Source_: reflection-TASK-096 (2026-06-03)
  - _Reinforced_: 0x

- **isolated-async-node-testing-with-browser-mocking** (`tests/test_task_*.py`): When writing unit/integration tests for orchestrator nodes (like `evaluator_node`) that depend on active browser pages and external step verifications, do not launch a real browser. Instead, patch the browser context manager (`get_manager`) and the individual step verification function (`_check_single_verification`) to yield sequence-based mock verifications (e.g., sequential `("satisfied", ...)` and `("not_yet", ...)`). This tests complex routing, list merging, and dynamic overrides in milliseconds with zero browser startup overhead.
  - _Source_: reflection-TASK-101 (2026-06-03)
  - _Reinforced_: 0x

- **pytest-model-collection-silencing** (`backend/engine/schemas.py`, `backend/kb/test_matcher.py`): Pydantic or helper classes that contain "Test" in their name (e.g. `TestPlan`, `TestMatcher`) are mistakenly collected as test classes by Pytest, raising warnings or errors during collection because they don't have test methods. To prevent Pytest from collecting them, explicitly set `__test__ = False` on the class definition, or rename them (e.g. `JiraTestMatcher`) to ensure a zero-warning test suite.
  - _Source_: reflection-TASK-103 (2026-06-03)
  - _Reinforced_: 0x

- **pre-build-api-unit-testing** (`tests/test_playwright_*.py`): When building features requiring new frontend-to-backend routing interfaces, write and verify backend unit tests for the endpoints and registry lookup logic *before* wiring client-side calls. This creates a rock-solid, fully documented API layer first, drastically reducing integration debugging and frontend test failures.
  - _Source_: reflection-TASK-108 (2026-06-08)
  - _Reinforced_: 1x (TASK-121: Phase 1 backend tests locked analysis dict shape before Phase 2 frontend type was authored)

- **async-service-boundary-mocking** (`tests/test_codegen_*.py`, `tests/test_*_transformer.py`): When testing async functions that delegate to external services (Bedrock, OpenAI, boto3), patch at the internal `_call_*` coroutine boundary (`patch("module._call_bedrock", new_callable=AsyncMock)`) rather than at the SDK client level. This avoids mocking the full SDK session and response shape, keeps tests fast and isolated, and survives refactors of the underlying SDK call pattern.
  - _Source_: reflection-TASK-121 (2026-07-14)
  - _Reinforced_: 0x

- **prompt-level-unit-testing** (`tests/test_ghost_login.py`, `backend/engine/prompts.py`): For LLM system prompt modifications, write unit tests that import the prompt string directly (`from backend.engine.prompts import BDD_NORMALIZER_PROMPT`) and assert on section-anchored substring presence. This catches prompt regressions at O(1) cost with zero LLM calls and runs safely in CI — far cheaper than integration tests that invoke the full AC parser pipeline.
  - _Source_: reflection-TASK-125 (2026-07-22)
  - _Reinforced_: 0x

- **pytest-asyncio-not-legacy-event-loop** (`tests/engine/test_*.py`, `tests/test_*.py`): Never use `asyncio.get_event_loop().run_until_complete(coro())` in test bodies to invoke async node functions — this API is deprecated in Python 3.12+ and produces `DeprecationWarning`. Always use `@pytest.mark.asyncio` on an `async def` test function and `await coro()` directly. The pattern is already documented in `tests/test_preflight_check.py`; repeat violations indicate this needs a pre-commit lint rule (e.g., `ruff`/`flake8-async` check for `get_event_loop().run_until_complete` in `tests/**`), not just a convention.
  - _Source_: reflection-critic-pass-llm-evaluator (2026-07-30)
  - _Reinforced_: 0x

- **test-count-per-resolution-variant** (`tests/test_*_resolver.py`, `tests/test_*_router.py`, mechanism modules with branching): When planning test counts for mechanism modules (resolvers, recovery handlers, dispatchers), count per resolution-path variant — one test per normalization rule, one per error condition, one per recovery-strategy combination — NOT per branch. Per-branch counting underestimates by 2-4x for modules with N inputs × M outcomes. Example: `A11yLocatorResolver` planned at ~10 tests, delivered 20 (2 tiers × 4 normalization variants + error paths). Per-variant counting predicts delivery within 20%.
  - _Source_: reflection-accessibility-tree-grounding (2026-07-30)
  - _Reinforced_: 0x

- **canonical-source-invariant-test** (`tests/test_task_*.py`, `backend/profiles/*.py`, any module maintaining a mirrored registry): When a module maintains a role/entity/route/component registry that MUST agree with a canonical config source (e.g., `products.yaml` roles vs. `_VSUITE_ROLES` profile entries; `openapi.yaml` routes vs. router registrations; `schema.sql` tables vs. ORM models), add a data-driven invariant test that iterates the canonical source and asserts each entry is present in the mirror registry. Do NOT hardcode the expected list in the test — read it from the canonical source at test time. This catches silent drift as soon as one side is updated without the other, and requires zero test maintenance when new entries are added.
  - _Source_: reflection-fix-vsuite-profile-missing-roles (2026-07-30)
  - _Reinforced_: 0x

- **regression-guard-for-ui-deletion** (`*.test.tsx`, `*.test.ts`): For code-deletion tasks whose primary deliverable is removal of a UI element (toggle, banner, deprecated form field), the idiomatic RED step in TDD is a **regression guard** that asserts the deleted element's selector (id, `data-testid`, role, or label text) is ABSENT — e.g., `expect(screen.queryByText(/Use Computer-Use loop/i)).toBeNull()`. This is the correct adaptation of RED/GREEN when there is no new behavior to specify. Guards double as living documentation of the invariant "this element must stay removed" and catch re-introduction in code review. Trade-off: guards provide NO positive coverage of the surviving code path — pair with existing behavioral tests, don't rely on guards alone.
  - _Source_: reflection-cu-loop-default-remove-toggle (2026-08-11)
  - _Reinforced_: 0x

- **loud-boundary-failures** (`**/*.ts`, `**/*.py`, `**/*.mjs` — any code that reads an artifact expected to be produced by another tool): When a function returns `false`/`undefined`/`null` because an expected artifact is missing (cache file not found, storage state absent, config not set), it silently hides the real problem as a downstream flaky-test symptom. Prefer either (a) a specific, actionable warning that names the missing artifact and points at how to create it, or (b) throwing a typed error with the same info. Same pattern applies to tool wrappers: don't print "all succeeded" after a parallel job when one branch failed — track per-item outcomes, print a structured summary, exit non-zero. `heal-13-playwright-failures-on-two-test` evidence: three examples surfaced in one investigation — `FirmOptionsHelper.checkFirmSettingCached` returning false-on-missing-file (hid the entire Family C root cause), `generateStorageStates.mjs` catching per-user errors inside `Promise.all` and printing "all generated" (hid a persistent Admin login failure across every env for months), `setup.ts:ENV_TIMEOUT_MULTIPLIER` defaulting `test` env to 1× with a stale comment claiming "localhost" (hid the fact that two-test needed the same 2.5× headroom as qa). Each silent fallback cost multiple hours of investigation that a one-line warning would have prevented.
  - _Source_: reflection-heal-13-playwright-failures-on-two-test (2026-08-12)
  - _Reinforced_: 0x

- **canonical-helper-for-multi-state-form-fields** (`playwright/tests/vpromedia/*.test.ts`, `playwright/tests/**/*.ts`): For form fields with documented multi-state render behavior (empty placeholder / prepopulated target / prepopulated non-target — e.g., the QO Status field), never hand-roll `page.getByLabel(...)` + click + text-select in recorded or hand-written tests. If a canonical helper exists in `playwright/utils/OrderHelper.ts` (like `selectQOStatus()`), import it and call it at the top of the file. Recorded tests capture a single render state and will silently fail as soon as another state renders in CI. Applies to Status, Adtype, and any other state-driven dropdown the helper covers.
  - _Source_: reflection-vqa-12-status-locator-prepopulation-fix (2026-08-17)
  - _Reinforced_: 0x

- **assert-mechanism-not-just-output-for-invariants** (`tests/test_*.py`, `tests/**/test_*.py` — pipeline determinism, idempotency, never-silent-fallback guarantees): For correctness-critical pipeline primitives where the invariant is "code path X must not run under condition Y" (deterministic replay, cache-bypass, no-silent-fallback), assert **mechanism** — `mock.call_count == 0` on the forbidden code path — not just output equality. An output-equality test passes whenever the forbidden path happens to produce identical output to the pinned path; a `call_count == 0` assertion proves the forbidden path was **unreachable by construction**. The distinction is "probably deterministic" vs. "provably deterministic," and matters most when the forbidden path is an LLM call at `temperature=0.0` on Bedrock (where `T=0` is not bit-exact). Concrete example from this task: `AC-INVARIANT-1` asserts `_stage_1_normalize.call_count == 0` and `_stage_2_compile.call_count == 0` when `state["pinned_plan"]` is set — this proves the pinned-plan short-circuit, whereas asserting only "output matches" would silently pass if Bedrock happened to reproduce the parse.
  - _Source_: reflection-vqa-pinned-testplans (2026-08-18)
  - _Reinforced_: 0x
