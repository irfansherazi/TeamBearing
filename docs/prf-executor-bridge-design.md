# PRF Executor Bridge — Design

**Status:** Draft — pending user review
**Author:** Claude (opus-4-7)
**Date:** 2026-08-05
**Context:** QA-359 CU-loop run took 24 min / $7.69 / 266 iterations for a flow
a human does in <3 min. The 9 PRF Playwright helpers in `playwright/utils/prf/`
plus their manifest at `knowledge/vpromotions/prf-helpers-manifest.md` are now
in place. This doc designs the runtime bridge that lets vQA **skip the CU loop
entirely** for helper-covered PRF flows.

---

## 1. Executive Summary

**Chosen path: Compile-First (Path A).** For a PRF-creation AC:

1. **AC parser** (existing) parses the AC steps as it does today, BUT the
   manifest lets it recognize helper-eligible steps and emit them as
   `{action: "helper", helper: "createPrfHappyPath", args: {...}}` markers.
2. **Static-test gate** (new, ~150 LOC) matches the parsed AC against the
   registered helper-based tests. On match, sets `state.playwright_test_id`.
3. **Graph** (small rewire, ~10 LOC) routes to `playwright_executor_node`
   (existing) instead of the CU loop.
4. **`playwright_executor_node`** (existing) spawns `npx playwright test <path>`,
   streams output, returns success/failure.
5. **On failure**, the graph falls back to the CU loop with a note
   ("static test failed — attempting CU-loop recovery").

**Why Path A over Path B (in-loop `run_playwright_helper` tool):**
- Path A: 24 min → 15-25s (99% saved), $7.69 → ~$0.05 (99% saved)
- Path B: 24 min → 10-12 min (only saves helper-covered portions),
  ~50% cost savings, model non-determinism preserved
- Path A uses existing infrastructure (`playwright_executor_node`,
  `PlaywrightRegistry`) — smaller code delta
- Path B is complementary — add it later if partial-coverage tickets become common

**Estimated effort:** 2-3 days end-to-end (registry ext + gate + first 2
static tests + graph rewire + fallback path + tests).

**Deliverables:**
- Extended `PlaywrightRegistry` with `ac_triggers` field
- `backend/engine/static_test_gate.py` (new module, ~150 LOC)
- `playwright/tests/vpromotions/create-prf-happy-path.test.ts` (first
  helper-based static test, param-driven)
- `playwright/tests/vpromotions/approve-prf.test.ts` (second)
- Graph edge from parser → gate → (playwright_executor | planner)
- Failure fallback: `playwright_executor` → `planner` when static test fails
- Product-detection tightening in `prompts.py` (already keyword-based; small
  refactor to share code with the gate)

---

## 2. Current State — What Exists

| Component | File | Status | Role in bridge |
|---|---|---|---|
| PRF helpers (TS) | `playwright/utils/prf/*.ts` | ✅ Placed | Called by static tests |
| PRF manifest | `knowledge/vpromotions/prf-helpers-manifest.md` | ✅ Written | Read by parser + gate |
| Model-facing PRF guide | `knowledge/vpromotions/create-prf-helper.md` | ✅ Exists | Injected into CU loop on fallback |
| CU-loop helper injection | `backend/engine/computer_use/prompts.py:83-113` | ✅ Exists | Handles fallback case |
| Playwright executor | `backend/engine/playwright_executor.py` | ✅ Exists (109 LOC) | Subprocess runner, needs no changes |
| Playwright registry | `backend/storage/playwright_registry.py` | ✅ Exists | **Needs `ac_triggers` field** |
| Recipe runner | `backend/engine/recipe_runner.py` | ✅ Exists (1629 LOC) | **Not used** — recipes are pure Playwright primitives, don't support external helper invocation |
| Test codegen | `backend/engine/computer_use/test_codegen.py` | ✅ Exists | **Optional Phase 2** — emit helper calls in `.spec.ts` |
| Static-test gate | — | ❌ Missing | **Build this** |
| Product routing | `_HELPER_TRIGGERS` in prompts.py | ✅ Basic | Extend for gate re-use |
| Graph edges | `backend/engine/graph.py` | ✅ Exists | **Rewire: add parser → gate → executor edge** |
| First static tests | `playwright/tests/vpromotions/` | ❌ Empty | **Author 2-3 helper-based tests** |

**Key finding:** ~80% of the plumbing exists. The bridge is mostly:
1. Two data changes (registry field + registry file entries)
2. One new module (~150 LOC gate)
3. One graph rewire (~10 LOC)
4. 2-3 hand-authored static tests

---

## 3. Design — Component by Component

### 3.1 `PlaywrightRegistry` — Add AC-trigger field

**File:** `backend/storage/playwright_registry.py`

**Current schema** (per Explore survey):
```json
{
  "id": "qa-100-create-prf",
  "file": "tests/vpromedia/qa-100-create-prf.test.ts",
  "jira_keys": ["QA-100"],
  "description": "Create a PRF successfully",
  "steps_count": 5,
  "step_names": ["Open PRF drawer", "Fill title", "Select category", "Save"]
}
```

**Proposed extension:**
```json
{
  "id": "vpromotions-create-prf-happy-path",
  "file": "tests/vpromotions/create-prf-happy-path.test.ts",
  "jira_keys": [],
  "description": "Happy-path PRF creation using CreatePrfHelper",
  "steps_count": 7,
  "step_names": [...],

  "ac_triggers": {                                   // NEW
    "product": "vpromotions",                        // gate product filter
    "any_phrase": [                                  // OR-match against AC text
      "create a new prf",
      "create prf",
      "new prf",
      "happy path prf",
      "prf creation"
    ],
    "requires_all_steps": [                          // AC must contain ALL of these
      "category", "station", "title", "save"
    ],
    "excludes_phrases": [                            // reject if any match
      "reject", "cancel", "delete"
    ]
  },
  "helper_params_from_ac": {                         // NEW - how to derive helper args
    "title": { "extract": "quoted_string_after:'title'" },
    "category": { "extract": "phrase_after:'category'", "default": "Contest" },
    "stations": { "extract": "list_after:'stations'", "default": ["XXXX-FM"] }
  }
}
```

**New API:**
```python
class PlaywrightRegistry:
    def match_ac(self, ac_text: str, product: str) -> list[dict]:
        """Return registry entries whose ac_triggers match the given AC text.
        Sorted by specificity (more required phrases = higher priority)."""
```

**Also add:** `PLAYWRIGHT_INDEX_FILE` support already exists — no new env var
needed.

---

### 3.2 New module: `static_test_gate.py`

**File:** `backend/engine/static_test_gate.py` (new, ~150 LOC)

**Responsibility:** Decide whether the current AC can be served by a
registered static test before entering the CU loop.

**Interface:**
```python
async def static_test_gate_node(state: VQAState) -> dict:
    """Match AC text against registered ac_triggers. If a match is found,
    set state.playwright_test_id and route to playwright_executor.
    Otherwise, route to the CU-loop planner as today."""
```

**Algorithm:**
1. Read `state["parsed_ac_steps"]` (joined text) + `state["target_url"]`
2. Detect product (via existing `_HELPER_TRIGGERS` logic — factored out)
3. Query `registry.match_ac(ac_text, product)` → list of eligible entries
4. If 0 matches: emit `{"_next_node": "planner"}` (CU loop as today)
5. If 1+ matches: pick highest-scored entry (specificity ranking)
6. Extract helper params from AC per the entry's `helper_params_from_ac` rules
7. Persist params to a temp JSON file that the static test reads at startup
   (env var `VQA_HELPER_PARAMS_JSON` set on subprocess env)
8. Emit `{"playwright_test_id": entry["id"], "_next_node": "playwright_executor"}`

**Param extraction rules** (initial small set):
- `quoted_string_after:'label'` — text between quotes following the label
- `phrase_after:'label'` — first noun phrase after the label
- `list_after:'label'` — comma/and-separated list after the label
- `default:<value>` — fallback if extraction returns empty

Complex extractions (dates, specific fields) can be added incrementally.

**Fallback behavior:** if extraction fails for a required param, the gate
LOGS the mismatch and falls through to the CU loop rather than dispatching
a broken static test. Rule: **never send a partial args set to a static test.**

---

### 3.3 Static test template — `create-prf-happy-path.test.ts`

**File:** `playwright/tests/vpromotions/create-prf-happy-path.test.ts`

**Design principle:** Tests must be **parameter-driven** (read `VQA_HELPER_PARAMS_JSON`)
so a single test file serves many tickets. No per-ticket hand-coding.

```typescript
/**
 * AUTO-INVOKED by vQA static-test gate for PRF-creation ACs.
 *
 * Reads args from $VQA_HELPER_PARAMS_JSON:
 *   { title, category, stations, salesAssignment?, description?, ... }
 *
 * See knowledge/vpromotions/prf-helpers-manifest.md for the AC-trigger
 * mapping.
 */
import { test } from '../../utils/setup';
import { loginAndWaitForHomeReady } from '../../utils/prf/AuthHelper';
import { ghostLogin } from '../../utils/prf/GhostLoginHelper';
import { createPrfHappyPath, CreatePrfDetails } from '../../utils/prf/CreatePrfHelper';
import * as fs from 'fs';

function loadHelperParams(): CreatePrfDetails & {
    ghostAs?: string;
    useAppTest?: boolean;
} {
    const path = process.env.VQA_HELPER_PARAMS_JSON;
    if (!path || !fs.existsSync(path)) {
        throw new Error('VQA_HELPER_PARAMS_JSON not set or missing');
    }
    return JSON.parse(fs.readFileSync(path, 'utf-8'));
}

test('vpromotions — create PRF happy path', async ({ page, baseURL }) => {
    const args = loadHelperParams();

    await loginAndWaitForHomeReady(page, baseURL!, {
        useAppTest: args.useAppTest ?? true,
    });

    if (args.ghostAs) {
        await ghostLogin(page, args.ghostAs);
        await loginAndWaitForHomeReady(page, baseURL!, {
            useAppTest: args.useAppTest ?? true,
        });
    }

    const result = await createPrfHappyPath(page, args, {
        verifyOnCalendar: true,
    });

    if (!result.recordId) {
        throw new Error('createPrfHappyPath returned no recordId');
    }
    console.log(`✅ PRF created: id=${result.recordId}`);
});
```

**Registry entry:**
```json
{
  "id": "vpromotions-create-prf-happy-path",
  "file": "tests/vpromotions/create-prf-happy-path.test.ts",
  "description": "Happy-path PRF creation using CreatePrfHelper",
  "steps_count": 7,
  "step_names": ["auth", "ghost", "open drawer", "title", "category",
                 "stations", "save"],
  "ac_triggers": {
    "product": "vpromotions",
    "any_phrase": ["create a new prf", "create prf", "new prf",
                    "happy path prf"],
    "requires_all_steps": ["category", "title", "save"],
    "excludes_phrases": ["reject", "delete", "revise"]
  },
  "helper_params_from_ac": {
    "title": { "extract": "quoted_string_after:'title'",
                "default": "Test PRF for ${TICKET_ID}" },
    "category": { "extract": "phrase_after:'category'",
                   "default": "Contest" },
    "stations": { "extract": "list_after:'stations'",
                   "default": ["XXXX-FM"] },
    "ghostAs": { "extract": "phrase_after:'ghost as'" },
    "description": { "extract": "quoted_string_after:'description'",
                      "default": "Test description for ${TICKET_ID}" }
  }
}
```

---

### 3.4 Graph rewire

**File:** `backend/engine/graph.py`

**Current flow (paraphrased):**
```
ac_parser → planner → executor → evaluator → (verifier / retry)
                ↘  playwright_executor  (if playwright_test_id preset)
```

**Proposed flow:**
```
ac_parser → static_test_gate → { playwright_executor  (if match)
                                { planner              (CU loop, if no match)
                                     ↓
                                (existing pipeline)

playwright_executor → { reporter  (if success)
                       { planner  (if failure — CU-loop fallback)
```

**Fallback wiring:** `playwright_executor` currently routes to `reporter`
unconditionally. Change: on failure, route to `planner` with a note
attached to state (so the CU-loop planner sees "static test failed with X,
attempting UI-driven recovery"). Add a **loop guard**: once the CU loop
starts after a static-test failure, do NOT re-enter the static gate on
the same run.

---

### 3.5 AC parser — helper-aware plan emission (optional Phase 2)

**File:** `backend/engine/ac_parser.py`

**Current:** Parser emits atomic UI steps. For a PRF-creation AC with 8
sub-steps, it emits 8 atomic actions.

**Proposed (optional):** When the parser detects a helper-eligible AC (via
the same manifest phrase matching), it can OPTIONALLY collapse the steps
into one high-level helper-step in the plan JSON. This is only relevant if
we DON'T take the static-test-gate path (i.e., partial coverage).

**Note:** For the Compile-First path (static-test gate), the parser DOES NOT
need to know about helpers — the gate handles routing after parsing. The
parser stays untouched in Phase 1.

**Recommendation:** Defer this to Phase 2. Ship the gate + static tests
first, evaluate coverage, then decide if the parser needs helper awareness.

---

### 3.6 test_codegen — emit helper calls (optional Phase 3)

**File:** `backend/engine/computer_use/test_codegen.py`

**Current:** Emits raw `page.getByLabel(...).click()` / `.fill()` / etc.
tool-by-tool from CU transcripts.

**Proposed (Phase 3):** When CU-loop is used AND completes successfully,
detect helper-mappable subsequences (e.g., a series of clicks + fills that
match the pattern of `createPrfHappyPath`) and emit ONE helper call instead
of the atomic sequence.

**Detection:** Match tool sequences against helper "signatures" — e.g.,
`{click "+ New PRF"}` + `{fill title}` + `{click Category}` + `{...}` +
`{click .prf_submit}` = `createPrfHappyPath` call.

**Effort:** ~1-2 days. **Value:** improves the quality of auto-generated
tests without changing runtime behavior. **Recommendation:** Ship Phase 1
(gate) first. Do Phase 3 only if auto-generated tests are being actively
consumed as regression tests.

---

## 4. Migration Plan (Order of Operations)

**Day 1: Foundation**
1. Extend `PlaywrightRegistry` with `ac_triggers` + `helper_params_from_ac`
   fields. Add `match_ac(ac_text, product)` method. Unit tests.
2. Author `create-prf-happy-path.test.ts` — the first parameter-driven
   static test. Verify manually with a `VQA_HELPER_PARAMS_JSON` env var
   pointing to a stub JSON file.
3. Add registry entry for the test.

**Day 2: Gate + Graph**
4. Write `static_test_gate.py` — the AC-matching + param-extraction logic.
   Unit test with fixtures.
5. Rewire `graph.py`: add gate node, add `playwright_executor → planner`
   fallback edge with loop guard. Integration test.
6. Add `VQA_HELPER_PARAMS_JSON` env var setter in `playwright_executor.py`
   (single line — env is already copied).

**Day 3: Second test + coverage widening**
7. Author `approve-prf.test.ts` (second helper-based test).
8. Registry entry + gate coverage.
9. Manual test on QA-359 — verify wall-clock is <30s and cost is <$0.10.
10. Update `create-prf-helper.md` to note the static path is preferred
    (falls back only when the gate doesn't match).

**Phase 2 (later):** AC parser helper-awareness.
**Phase 3 (later):** test_codegen helper emission.

---

## 5. Testing Strategy

### 5.1 Unit tests
- `test_playwright_registry_match_ac.py` — matching logic, specificity
  ranking, exclude phrases.
- `test_static_test_gate.py` — full gate flow with mocked registry +
  various AC inputs.
- `test_helper_params_extraction.py` — the `quoted_string_after`,
  `phrase_after`, `list_after`, `default` rules.

### 5.2 Integration tests
- `test_graph_static_test_success.py` — full graph run where gate matches,
  static test succeeds → reporter called.
- `test_graph_static_test_failure_fallback.py` — gate matches, static test
  fails → falls back to CU loop, does NOT re-enter gate.
- `test_graph_no_gate_match_cu_flow.py` — gate doesn't match → normal CU
  flow, static test never invoked.

### 5.3 End-to-end test
- Run QA-359 through the full pipeline. Assert:
  - Wall-clock < 30s
  - Cost < $0.10
  - `playwright_test_id` set in state
  - `.toast-success` observed in test output
  - PRF appears on calendar
- Compare to baseline: previous CU run at 24min / $7.69 / 266 iters.

### 5.4 Regression test
- Run 5 non-PRF tickets to verify the gate correctly falls through to
  the CU loop. Baseline: unchanged behavior.

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Static test brittle to vPromotions UI changes | Medium | High | Helper library encapsulates selectors; tests only touch helpers. Selector changes = 1 helper file update, not N tests. |
| Param extraction misinterprets AC text → runs test with wrong args | Medium | Medium | **Never dispatch with partial args** — gate falls back to CU loop when extraction fails. Log extraction misses to `.claude-logs/`. |
| Infinite loop between static → fail → CU → fail → static | Low | High | Loop guard in graph: once static failed, mark state and skip gate on retry. |
| Static test passes but doesn't fully satisfy AC (e.g., missed edge case in AC that helper doesn't cover) | Medium | Medium | Post-run verifier still checks AC completeness. If a step wasn't covered, verifier fails and CU-loop takes over. |
| Helpers export types that break under strict tsconfig | Low | Low | Copy of type-check pass in CI. `@ts-expect-error` annotations are already in the helpers. |
| test_codegen emits raw primitives even when helpers were used (Phase 1) | High | Low | Acceptable — codegen enhancement is Phase 3. Static-test wins are the priority. |
| The `PLAYWRIGHT_INDEX_FILE` requires manual regeneration | Medium | Low | Add a filesystem watcher OR pre-commit hook that runs the existing `scripts/sync_playwright_index.py` when tests change. |

---

## 7. Cost/Impact Projection

### Baseline (QA-359 today):
- Wall-clock: 24 min
- Cost: $7.69
- Iterations: 266
- Success rate: 100% (helper doc worked, but slow)

### Post-bridge (QA-359 via static test):
- Wall-clock: 15-25s (99% reduction)
- Cost: ~$0.05 (99% reduction) — only the AC parse + gate + reporter
- Iterations: 0 CU iters (test is direct subprocess)
- Success rate: expected 95%+ (static tests are deterministic once helpers are solid)

### Post-bridge on failure fallback:
- Wall-clock: 25s (static attempt) + 24 min (CU fallback) = 24.5 min
- Cost: $0.05 + $7.69 = $7.74 (marginally more expensive on failures)
- Success rate: same as today (CU fallback is unchanged)

### Portfolio impact (rough estimate):
- If 40% of PRF tickets match helper coverage → 40% get 99% savings
- If 60% fall through to CU → unchanged
- Blended savings: ~40% × 99% + 60% × 0% = **~40% cost reduction across all PRF tickets**
- Adding more helper-based tests (Phase 2+) grows this share

---

## 8. Open Questions for Josh

1. **Test env target confirmation** — the helpers use `useAppTest: true` by
   default which routes to `/app_test.php/promo`. Confirm this is the right
   default for CI runs.
2. **Auth pattern** — the test uses `test.use({ user: 'Admin' })` fixture.
   Does vPromotions have `storageState_Admin.json` for the test env, or
   should we ghost from a base admin session? (Storage generator lives at
   `playwright/utils/generateStorageStates.mjs`.)
3. **Failure-mode preference** — when a static test fails, should we:
   - (a) Fall through to CU loop silently (current design) OR
   - (b) Fail loudly and NOT run CU (helpful when we're validating helper
     coverage; annoying in prod)
   Suggest starting with (a) but adding a `VQA_STRICT_STATIC` env flag for
   (b) in dev.
4. **Registry regeneration** — the existing index file is populated by
   `scripts/sync_playwright_index.py`. Should the gate refresh it at
   startup (~50ms), or trust the on-disk copy? (Recommend startup refresh
   for dev, on-disk trust for prod.)

---

## 9. Non-Goals

- **Recipe runner integration.** Recipes are pure Playwright primitives; they
  do not compose with TypeScript helpers, and extending them to invoke external
  code would double the moving parts. Recipes stay for their current use
  (PrimeNG sort/multiselect/etc.); PRF gets its own path.
- **In-loop `run_playwright_helper` tool.** Deferred — the Compile-First path
  handles the QA-359 class of tickets. If partial-coverage tickets become
  common, revisit as Path B (see §1).
- **Auto-authoring static tests from ACs.** Deferred to Phase 3 —
  test_codegen enhancement.
- **Rewriting `create-prf-helper.md`** — that document remains the CU-loop's
  fallback playbook when the gate doesn't match. It stays authoritative for
  the model.
