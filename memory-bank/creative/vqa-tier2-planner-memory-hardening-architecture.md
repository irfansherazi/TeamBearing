---
task: vqa-tier2-planner-memory-hardening
phase: creative
status: DECIDED
created: 2026-07-28
decides:
  - T2-b trace-parse module boundary (LOW → HIGH confidence)
  - T2-d DomVerifier input contract (LOW → HIGH confidence)
  - Backfill source-selection heuristic (MEDIUM → HIGH confidence)
scope:
  - backend/engine/hitl_trace_parser.py (NEW)
  - backend/engine/verifier.py (SPLIT: DomVerifier + VisionVerifier)
  - backend/engine/state.py (state_expectation on planned_action)
  - backend/engine/planner.py (state_expectation emission surface)
  - scripts/backfill_ac_parse_cache.py (NEW)
---

# Architecture Decision: vQA Tier 2 — Planner & Memory Hardening (Structural)

**Created**: 2026-07-28
**Status**: DECIDED
**Decision Type**: Architecture (Level 4)
**Complexity Justification**: Three new subsystems (HITL trace parser, DOM verifier, cache-source strategy) each affect the LangGraph node topology, cross the planner/executor/verifier seam, and mutate the persistent memory contract (`ActionRecipe` YAML + `storage/ac_parse_cache/`). Any of these seams, mis-designed, becomes a one-way door.

---

## Context

The FEAT-117 spec (see `memory-bank/tasks/vqa-tier2-planner-memory-hardening.md`) identified three seams that Planning could not resolve without design exploration:

1. **T2-b — Where does the trace-parse code live and run?** (LOW confidence in spec)
2. **T2-d — How does `DomVerifier` know what to check?** (LOW confidence in spec)
3. **Backfill — What is the source of raw AC text for prior parses?** (MEDIUM confidence in spec)

This document resolves all three. The FEAT-117 spec is authoritative for **what** we are building and the acceptance criteria (AC-VERIFY-1 through AC-VERIFY-7, AC-INTEGRATION-1, AC-ERROR-1); this document is authoritative for **where the code lives and what its contracts are**.

### Guiding Principles that Constrain This Design

All from `memory-bank/systemPatterns.md`:

- **Programmatic Tier 1 Verification** — DOM checks via Playwright are fast and deterministic; LLM visual verification is fallback only. T2-d reinforces this principle; the design MUST NOT reintroduce vision as the default.
- **HITL as Learning Signal** — Every human takeover produces persistent memory the agent replays on future runs. T2-b's module-boundary decision MUST preserve the "every HITL → Recipe" guarantee.
- **Failure Diary Pattern** — Per-locator failure counts prevent infinite retry. Both T2-b (parse failures) and T2-d (verifier NOT_YET streaks) must interact cleanly with the diary.
- **Semantic Locators First** — Auto-generated recipes MUST prefer `get_by_role`/`get_by_label`/`get_by_text` over brittle CSS selectors when the trace exposes both.

### Non-Functional Constraints from productBrief.md

- **Latency budget**: per-step see-think-act cycle < 15s. T2-d target: DOM-resolved case ≤ 200ms (vs. ~2500ms vision baseline). T2-b synchronous parse target: ≤ 1500ms so `human_takeover_node` finalization stays under human perception.
- **Reliability**: HITL escalation rate should decrease over time. T2-b converts each HITL to a persistent Recipe — a load-bearing metric for the roadmap KPI.
- **Observability**: structured JSON with traceparent per project standard. Every new subsystem below emits `trace_id`, `span_id`, `run_id`, `service="vqa-backend"`.
- **Security**: HITL `.zip` traces may contain live vSuite screenshots. Storage is local-only (`storage/hitl_traces/`), not synced to S3. No new secrets or endpoints.

---

## Question 1 — T2-b: Trace-Parse Module Boundary

### 1.1 Problem Statement

`human_takeover_node()` (`backend/engine/human_takeover.py:1011`) currently swallows every HITL: it appends a text blob to `knowledge/vSuite-actions.md` (line 998–1000) and returns. There is no structured, replayable memory. The `.zip` produced by `page.context.tracing.stop(path=...)` (the Phase-2 addition) needs to be parsed into an `ActionRecipe` YAML under `knowledge/blueprints/generated/` so `RecipeRegistry._load_all()` (`recipe_runner.py:1440`) picks it up on the next planner call and `match(step_goal)` (`recipe_runner.py:1502`) surfaces it — this is what AC-INTEGRATION-1's "second run drives Contest without HITL" claim depends on.

The seam question is: **Does the parser run synchronously inside the node, out-of-band via asyncio, or entirely offline via a script?** The answer decides whether AC-INTEGRATION-1 has a well-defined completion semantic.

### 1.2 Options Explored

#### Option 1A — Synchronous parse inside `human_takeover_node`

```
human_takeover_node()
  ├── tracing.start(...)          # on entry
  ├── await resume_event.wait()
  ├── tracing.stop(path=<zip>)
  ├── result = await hitl_trace_parser.parse(zip_path, ac_step_goal, ...)   # NEW, SYNC
  ├── if result.ok: write recipe YAML
  ├── if result.failed: WARN log + preserve zip + no stub YAML (AC-ERROR-1)
  └── return {...}
```

- **Pros**:
  - "Every HITL → Recipe" guarantee is trivially enforced — the parse finishes before the node returns.
  - AC-INTEGRATION-1's "second run finds the Recipe" has an unambiguous happens-before edge: the parse completes before the planner enters the next AC step on the second run (in fact, before the current run even continues).
  - Failure surfacing (AC-ERROR-1) is a single try/except in one location — no async coordination.
  - Testability: mockable at the parser boundary, no fixture race conditions in `test_hitl_tracing.py`.

- **Cons**:
  - Adds ~500–1500ms to the takeover finalization (parse + YAML write + `os.fsync`). The operator has already clicked "Done" — this shows as latency between click and the run visibly resuming.
  - Blocks the asyncio event loop for the duration if the parser is CPU-bound.

- **Complexity**: LOW.
- **One-way-door risk**: LOW. Migrating from 1A → 1B later (if latency becomes intolerable) is a mechanical change; the parser signature stays the same.

#### Option 1B — Background asyncio task fanned out from the node

```
human_takeover_node()
  ├── tracing.stop(path=<zip>)
  ├── asyncio.create_task(hitl_trace_parser.parse_and_persist(zip_path, ...))
  └── return {...}   # returns immediately
```

- **Pros**:
  - Takeover finalization is instantaneous (~10ms).

- **Cons**:
  - **Breaks AC-INTEGRATION-1's happens-before guarantee**: if the operator immediately re-runs the same ticket (a very common QA workflow — "did my fix take?"), the second run's `RecipeRegistry.match()` may fire *before* the background parse finishes writing the YAML. Result: the second run re-triggers HITL, and the AC fails silently.
  - Exception handling is orphaned — a raised exception in a fire-and-forget task is trapped in the asyncio warning stream, easy to miss.
  - AC-ERROR-1's WARN log is decoupled from the run's log stream — the WebSocket-attached logger context is gone by the time the background task runs.
  - Testing gets a fixture race: `test_trace_parses_to_recipe` needs `asyncio.wait_for(...)` polling with timeouts.

- **Complexity**: MEDIUM (asyncio task lifecycle, exception propagation).
- **One-way-door risk**: MEDIUM. The AC-INTEGRATION-1 breakage would only manifest under real-world usage; unit tests with pinned fixtures would hide it.

#### Option 1C — External script (`scripts/parse_hitl_trace.py`) triggered by watcher or admin API

- **Pros**:
  - Complete decoupling. The parser can be developed and iterated independently.

- **Cons**:
  - **Violates the "HITL as Learning Signal" Guiding Principle**: memory now depends on a human remembering to run a script, or on an inotify/fswatch sidecar that must be operationally maintained. The Docker deployment topology (see productBrief.md § Infrastructure — supervisord + Xvfb + noVNC) doesn't have such a watcher; adding one is out of scope.
  - AC-INTEGRATION-1's manual live-run test needs an extra step in the reproducer, and the second-run replay is no longer a natural QA workflow — it's a scripted ceremony.
  - AC-ERROR-1's WARN log is now emitted from a process that isn't the vQA run — plumbing it back to `execution_log.jsonl` requires new machinery.

- **Complexity**: HIGH (new deployment surface, new process lifecycle).
- **One-way-door risk**: HIGH. Once documented as "run this script after HITL," reverting to inline execution requires migrating operator habits and CI harnesses.

### 1.3 Evaluation Matrix

| Criteria (weight) | 1A (sync) | 1B (async task) | 1C (script) |
|---|---|---|---|
| Correctness against AC-INTEGRATION-1 (H) | 10 | 4 | 6 |
| Latency budget alignment (M) | 7 | 10 | 10 |
| "HITL as Learning Signal" alignment (H) | 10 | 8 | 3 |
| AC-ERROR-1 surfacing simplicity (M) | 10 | 5 | 4 |
| Testability (H) | 10 | 6 | 7 |
| One-way-door risk (H) | 10 | 6 | 3 |
| Backward compat (M) | 10 | 8 | 6 |
| **Weighted total** | **9.6** | **6.6** | **5.4** |

### 1.4 Decision — Option 1A (Synchronous parse inside `human_takeover_node`)

The correctness win (AC-INTEGRATION-1 happens-before, AC-ERROR-1 in-context logging) dominates. The ~1500ms latency cost is measured *after* the operator clicks Done — the operator does not perceive this as agent latency, only as "run resuming." Real perceived latency is a non-issue.

Migration lever if latency ever becomes problematic: promote to Option 1B with a `parse_completed` asyncio.Event that the next planner turn `await`s at the top of the state — the parser signature does not change. This is a two-hour refactor, not a redesign.

### 1.5 Trace `.zip` Parsing Approach

Playwright traces are `.zip` archives containing (from Playwright 1.49+ source inspection):
- `trace.trace` — NDJSON event stream (one JSON object per line)
- `trace.network` — NDJSON network events (unused by us)
- `resources/` — screenshots, snapshots as content-addressed blobs

**`playwright show-trace` is a viewer, not a parser.** There is no `playwright parse-trace` CLI. The `trace.trace` NDJSON is Playwright-internal but has been stable across the 1.40–1.49 range. Our parsing strategy:

**Chosen approach**: read `trace.trace` NDJSON directly with `zipfile` + `json.loads` per line. Filter for events with `type` ∈ `{"action", "before", "after"}` and `class` ∈ `{"Frame", "Page", "Locator", "Keyboard"}`. Correlate `before`/`after` by `callId` to identify the *successful* actions (an `after` with no `error` field). This is roughly 50 lines of Python.

**Rejected alternatives**:
- Subprocess to `playwright show-trace` and screen-scrape — fragile, no stable output.
- Use the JS `@playwright/test` trace-viewer package via subprocess — introduces a Node.js dependency.

**Version-bump robustness plan**: pin `playwright==1.49.*` in `backend/requirements.txt` (the version already present per techContext.md). On upgrade, run `test_hitl_tracing.py::test_trace_parses_to_recipe` against a fresh fixture `.zip`; if the schema changed, update the parser. This is a known maintenance cost, accepted because the alternative (external parser tool) has higher operational cost.

### 1.6 Auto-Recipe `trigger_phrases` Synthesis

`ActionRecipe.trigger_keywords` (`recipe_runner.py:276`) is a list-of-strings matched by whole-word Jaccard subset (see `match()` at line 1502–1540). For a human-curated recipe, this list is 1–3 phrases (e.g., `["contest dropdown", "prf category"]`).

For an auto-generated recipe, we synthesize the list from **two sources**, combined:

1. **AC step goal at the point of takeover** (primary) — e.g., "Select Contest from PRF Category dropdown". We extract the noun-heads: `["select contest", "prf category", "contest dropdown"]`. This is what the planner's next call will see, so this is the highest-signal source.
2. **DOM text near the interacted element** (secondary) — from the trace's `snapshot` field on the successful click, we extract `aria-label`, `placeholder`, and immediate text-content of the target selector. This catches paraphrase drift: if the AC says "Contest" but the button reads "Select Contest", both phrases end up in the list.

**Deduplication + capping**: max 5 trigger phrases, each 1–4 tokens. Lower-cased, punctuation-stripped. If step goal and DOM text overlap, keep the DOM-text version (it's what the user will actually see in the accessibility tree).

**Backward compat guarantee**: this synthesis path is only invoked when writing to `knowledge/blueprints/generated/`. Human-curated recipes under `knowledge/blueprints/*.yaml` are untouched. `RecipeRegistry._load_all()` already walks both by glob — no code change needed to accept the new subdirectory once the parser writes there.

### 1.7 Implementation Guide (T2-b)

**New file: `backend/engine/hitl_trace_parser.py`** (~250 lines)

```python
"""
vQA — HITL Playwright Trace → ActionRecipe parser (FEAT-117 / T2-b)
====================================================================

Consumes a Playwright trace .zip produced by tracing.start()/stop()
in human_takeover_node(), extracts the last successful DOM
interaction sequence, and emits an ActionRecipe YAML under
knowledge/blueprints/generated/.

Invoked SYNCHRONOUSLY from human_takeover_node.complete_takeover
finalization path. Failures produce a WARN log + preserved .zip;
no stub Recipe is written (AC-ERROR-1).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TraceParseFailureReason(str, Enum):
    CORRUPTED_ZIP = "corrupted_zip"
    NO_TRACE_FILE = "no_trace_file"
    NO_INTERACTIVE_EVENTS = "no_interactive_events"
    UNRESOLVABLE_SELECTOR = "unresolvable_selector"
    SCHEMA_MISMATCH = "schema_mismatch"  # trace schema unrecognized


@dataclass
class ExtractedAction:
    """One DOM interaction extracted from the trace."""
    event_type: str            # "click" | "fill" | "select" | "press"
    selector: str              # semantic locator preferred; CSS fallback
    selector_kind: str         # "role" | "label" | "text" | "css"
    value: str | None          # for fill/select/press
    aria_label: str | None     # for trigger phrase synthesis
    timestamp_ms: int          # relative to trace start
    call_id: str               # trace callId for debugging


@dataclass
class TraceParserResult:
    """Return value of hitl_trace_parser.parse(). Never raises."""
    ok: bool
    actions: list[ExtractedAction] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)
    recipe_yaml_path: Path | None = None
    failure_reason: TraceParseFailureReason | None = None
    failure_detail: str = ""
    zip_path: Path | None = None            # preserved on failure
    parse_duration_ms: int = 0


async def parse_trace(
    zip_path: Path,
    ac_step_goal: str,
    run_id: str,
    takeover_seq: int,
    output_dir: Path = Path("knowledge/blueprints/generated"),
) -> TraceParserResult:
    """
    Parse a Playwright trace .zip and, on success, write an ActionRecipe YAML.

    Contract:
    - Returns TraceParserResult; never raises to caller.
    - On failure, .zip is left in place (not deleted). No stub YAML written.
    - Structured log emitted with run_id, trace_id, span_id.
    - Wall-clock target: < 1500ms for a typical HITL trace (< 50 actions).
    """
    ...
```

**Modification: `backend/engine/human_takeover.py:1011` (`human_takeover_node`)**

Insert between the resume-event `await` and the return statement:

```python
# ── T2-b: Parse trace to Recipe (sync, in-band) ──────────────────
try:
    from backend.engine.hitl_trace_parser import parse_trace
    zip_path = Path(f"storage/hitl_traces/{run_id}-{takeover_seq}.zip")
    result = await parse_trace(
        zip_path=zip_path,
        ac_step_goal=current_step,
        run_id=run_id,
        takeover_seq=takeover_seq,
    )
    if not result.ok:
        logger.warning(
            "[%s] hitl_trace_parse_failed: reason=%s detail=%s zip_preserved=%s",
            run_id, result.failure_reason, result.failure_detail, result.zip_path,
        )
        # AC-ERROR-1: log emitted, .zip preserved on disk, no stub YAML
    else:
        logger.info(
            "[%s] hitl_trace_parse_ok: %d actions, recipe=%s",
            run_id, len(result.actions), result.recipe_yaml_path,
        )
except Exception as parse_err:
    # Belt-and-braces: parser itself is designed not to raise, but catch anyway
    logger.warning("[%s] hitl_trace_parser exception: %s", run_id, parse_err)
```

**Modification: `backend/engine/recipe_runner.py:1440` (`RecipeRegistry._load_all()`)**

Extend the glob to walk both directories:

```python
def _load_all(self) -> None:
    for base in (self._dir, self._dir / "generated"):
        if not base.exists():
            continue
        for yaml_path in sorted(base.glob("*.yaml")):
            self._load_file(yaml_path)
```

`match()` (line 1502) is unchanged — auto-generated recipes participate in the same Jaccard-subset scoring as human-curated ones. **Ordering rule**: on tie in `best_len`, human-curated recipes (parent dir) win. This is enforced by adding a `_provenance` field to loaded recipes and using it as a tiebreaker in the sort at line 1540.

### 1.8 Testability Hooks (T2-b)

- `test_hitl_tracing.py::test_trace_zip_produced` — mocks `page.context.tracing.start/stop`; asserts `stop(path=<expected>)` invocation. No parser called.
- `test_hitl_tracing.py::test_trace_parses_to_recipe` — feeds `fixtures/hitl_trace_sample.zip` to `parse_trace()`; asserts `result.ok`, at least one `ExtractedAction`, and a YAML file at the expected path.
- `test_hitl_tracing.py::test_trace_parse_failure_surfaces_and_preserves_zip` — feeds `fixtures/hitl_trace_empty.zip`; asserts `result.ok == False`, `result.failure_reason == NO_INTERACTIVE_EVENTS`, `zip_path.exists() == True`, no YAML file created.

All three tests use `TraceParserResult` as the observable — the dataclass is the test contract.

---

## Question 2 — T2-d: DomVerifier Input Contract

### 2.1 Problem Statement

`step_verifier_node()` (`backend/engine/verifier.py:1631`) currently burns a Sonnet vision call on every AC step transition. That's ~2500ms wall-clock and ~2000 input-tokens per step. The Contest false-NOT_YET burns this cost for zero value: the operator sees "Contest" is selected, but the verifier LLM says NOT_YET because it can't tell.

The split-verifier design (spec T2-d) puts a `DomVerifier` in front. But the input contract — *how does it know what to check?* — is undefined. `PredictiveVerifier.verify_expectation()` at `verifier.py:2419` already consumes a free-form string called `state_expectation` (regex-scans for URL, quoted text, and CSS selectors), but the string is currently only emitted by the planner when it feels like it, and its taxonomy is loose.

### 2.2 Options Explored

#### Option 2A — Planner emits a structured `state_expectation` field per action

Extend `planned_action` (the dict returned by `planner_node`) with a `state_expectation: StateExpectation` field. `DomVerifier.check(page, expectation)` consumes it as the sole input. Planner prompt is updated to emit this via structured output.

- **Pros**:
  - Cleanest architecture — planner *knows* what state change it intended (it just chose the action).
  - Deterministic input to the verifier → deterministic evidence signals → matches "Programmatic Tier 1 Verification" principle.
  - Reuses existing `PredictiveVerifier` prompt-integration surface at `verifier.py:2419` — we generalize it, not replace it.

- **Cons**:
  - Requires planner prompt engineering. If the planner reliably emits `state_expectation` today (via `PredictiveVerifier`, which it already partially does per `verifier.py:2419`), the coverage rate is <100%. AC-VERIFY-5 needs ≥60% DOM-resolved cases; on cases where the planner omits `state_expectation`, DomVerifier has no input → falls back to vision → the 60% target is unmet.
  - Prompt-engineering cost is real: adding one more required-JSON-field increases parse-failure rate.

- **Complexity**: MEDIUM.
- **One-way-door risk**: LOW. Adding new check kinds later is additive.

#### Option 2B — Verifier infers expectation from AC step text via rules

`DomVerifier.check(page, ac_step_text)` runs a keyword rule set: "opens" → look for `aria-expanded` delta; "selects" → look for `aria-selected`; "navigates to X" → check URL; and so on.

- **Pros**:
  - Zero planner-prompt changes.
  - Fully deterministic input (AC step text is fixed post-parse).

- **Cons**:
  - AC step text describes *user intent*, not *machine-verifiable state*. "Select Contest from PRF Category dropdown" doesn't tell the verifier *which* `<p-select>` (there are 3 dropdowns on that page).
  - Under-specification → fallback to vision → AC-VERIFY-5 60% target unmet.
  - Rule set grows brittle over time; every new PrimeNG component needs a new rule.

- **Complexity**: HIGH (rule-set maintenance).
- **One-way-door risk**: MEDIUM. Once shipped, the rule set accretes; ripping it out later is hard.

#### Option 2C — Hybrid: planner emits when possible, verifier falls back to a default probe set

`DomVerifier.check(page, ac_step_text, expectation: StateExpectation | None)`:
1. If `expectation` is present, use it (Option 2A path).
2. Else, run a **default probe set** and check for any material delta from `pre_state_snapshot`:
   - URL delta
   - Element-count delta
   - `aria-expanded=true` count delta
   - Dialog-open state delta
3. If default probes are all null-delta → verdict `INCONCLUSIVE` → cascade to `VisionVerifier`.

- **Pros**:
  - Best of both. Planner-provided expectations are precise; default probes catch the common "something visibly changed" cases without prompt-engineering the planner.
  - AC-VERIFY-5 60% target achievable: even if planner emits `state_expectation` only 40% of the time, the default probe set alone resolves the other 20%+.
  - Backward-compatible with `PredictiveVerifier` — that class becomes the internal implementation of the "planner-emitted expectation" branch.

- **Cons**:
  - Two failure modes to reason about (planner emitted vs. default probe path). Test matrix doubles.

- **Complexity**: MEDIUM.
- **One-way-door risk**: LOW.

### 2.3 Evaluation Matrix

| Criteria (weight) | 2A (planner emits) | 2B (rules from AC text) | 2C (hybrid) |
|---|---|---|---|
| AC-VERIFY-5 60% target reachability (H) | 6 | 5 | 10 |
| "Programmatic Tier 1" principle (H) | 10 | 8 | 10 |
| Prompt-engineering burden (M) | 5 | 10 | 8 |
| Rule-set maintenance burden (M) | 10 | 3 | 8 |
| Backward compat with `PredictiveVerifier` (M) | 9 | 4 | 10 |
| Testability (H) | 9 | 8 | 9 |
| One-way-door risk (H) | 9 | 6 | 10 |
| **Weighted total** | **8.0** | **6.3** | **9.4** |

### 2.4 Decision — Option 2C (Hybrid)

The hybrid path is the only design that hits the AC-VERIFY-5 60% target *and* preserves the Programmatic Tier 1 Verification principle. The two-failure-mode cost is bounded — each mode is a discrete code path with its own tests.

### 2.5 The DOM Expectation Taxonomy (closed set)

`StateExpectation` is a tagged union (Python dataclass with a `kind` discriminator). The taxonomy below is the **closed set** — new kinds require an ADR, not just a code change. Every kind maps to exactly one Playwright API call so fixtures can pin expected behavior.

| Kind | Discriminator | Fields | Playwright API | Applies to |
|---|---|---|---|---|
| `aria_expanded` | `"aria_expanded"` | `selector: str`, `expected: bool` | `page.locator(selector).get_attribute("aria-expanded")` | `<p-select>`, `<p-dropdown>`, menu buttons, accordions |
| `aria_selected` | `"aria_selected"` | `selector: str`, `expected: bool` | `.get_attribute("aria-selected")` | menu items, tabs, tree nodes |
| `aria_checked` | `"aria_checked"` | `selector: str`, `expected: bool \| "mixed"` | `.get_attribute("aria-checked")` | checkboxes, radios, toggles |
| `url_delta` | `"url_delta"` | `pattern: str` (regex or substring), `mode: "contains" \| "regex"` | `page.url` | navigation |
| `url_equals` | `"url_equals"` | `expected: str` | `page.url` | strict route change |
| `element_count` | `"element_count"` | `selector: str`, `op: ">" \| "<" \| "==" \| "!="`, `count: int` | `page.locator(selector).count()` | tables (row added), lists |
| `element_visible` | `"element_visible"` | `selector: str`, `expected: bool` | `.is_visible()` | dialogs, panels, banners |
| `element_hidden` | `"element_hidden"` | `selector: str` | `.is_hidden()` (or `.count() == 0`) | close/dismiss verification |
| `text_content` | `"text_content"` | `selector: str`, `contains: str` (case-insensitive) | `.text_content()` | toast messages, labels |
| `class_contains` | `"class_contains"` | `selector: str`, `class_name: str`, `expected_present: bool` | `.get_attribute("class")` | active/selected class toggles |
| `focus_on` | `"focus_on"` | `selector: str` | `page.evaluate("document.activeElement...")` | tab-order, keyboard-nav asserts |
| `dialog_open` | `"dialog_open"` | `title: str \| None` | `page.locator(".p-dialog").is_visible()` | modal appearance |
| `toast_visible` | `"toast_visible"` | `severity: "success" \| "error" \| "info" \| "warn" \| None`, `contains: str \| None` | `page.locator(".p-toast-message").is_visible()` + text check | notification asserts |

**Composite expectations**: `StateExpectation` also supports `kind: "all_of"` and `kind: "any_of"` with a `children: list[StateExpectation]` field. This lets the planner express "URL changed AND toast appeared" without duplicating check kinds.

**Default probe set** (when `state_expectation` is `None`) — probed in this order, stop on first `resolved=True`:
1. `url_delta` from `pre_state_snapshot.url`
2. `element_count` on `body *` from `pre_state_snapshot.element_count`
3. `aria_expanded` scan across all `[aria-expanded]` elements — any delta
4. `dialog_open` state delta
5. `toast_visible` any-severity

If all 5 default probes return null-delta after the action executed, verdict is `INCONCLUSIVE` and vision cascades.

### 2.6 Implementation Guide (T2-d)

**Modification: `backend/engine/state.py`** — extend `VQAState` and `planned_action` schema:

```python
# In state.py (VQAState TypedDict)
class VQAState(TypedDict, total=False):
    ...
    # T2-d: planner-emitted or verifier-computed pre-state snapshot
    pre_action_state_snapshot: dict  # {url, element_count, aria_expanded_count, ...}
```

The `planned_action` dict grows an optional key:
```python
planned_action = {
    "action": "click",
    ...
    "state_expectation": {                # optional; None or dict
        "kind": "aria_expanded",
        "selector": "p-select[formcontrolname='prfCategory']",
        "expected": True,
    },
}
```

**Modification: `backend/engine/verifier.py`** — split the module:

```python
# ── NEW dataclasses at top of verifier.py ─────────────────────────

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Union


@dataclass(frozen=True)
class AriaExpandedCheck:
    kind: Literal["aria_expanded"] = "aria_expanded"
    selector: str = ""
    expected: bool = True

@dataclass(frozen=True)
class UrlDeltaCheck:
    kind: Literal["url_delta"] = "url_delta"
    pattern: str = ""
    mode: Literal["contains", "regex"] = "contains"

# ... (one dataclass per taxonomy row, plus AllOfCheck/AnyOfCheck)

StateExpectation = Union[
    AriaExpandedCheck, AriaSelectedCheck, AriaCheckedCheck,
    UrlDeltaCheck, UrlEqualsCheck, ElementCountCheck,
    ElementVisibleCheck, ElementHiddenCheck, TextContentCheck,
    ClassContainsCheck, FocusOnCheck, DialogOpenCheck, ToastVisibleCheck,
    AllOfCheck, AnyOfCheck,
]


class VerifierVerdict(str, Enum):
    PASS = "PASS"
    NOT_YET = "NOT_YET"
    INCONCLUSIVE = "INCONCLUSIVE"   # → cascade to VisionVerifier


@dataclass
class VerifierResult:
    """Return shape of DomVerifier.check() and VisionVerifier.check()."""
    resolved: bool                   # True if verdict is authoritative
    verdict: VerifierVerdict
    evidence: str                    # human-readable one-liner for logs/report
    verifier_path: Literal["dom_only", "dom_inconclusive_vision_ran", "vision_only"]
    check_kind: str = ""             # e.g. "aria_expanded" (for telemetry)
    elapsed_ms: int = 0
    tokens_used: int = 0             # 0 for pure-DOM; nonzero when vision ran


# ── NEW class: DomVerifier ────────────────────────────────────────

class DomVerifier:
    """
    Deterministic DOM-only verifier. Never calls Bedrock.
    Runs BEFORE VisionVerifier per T2-d.
    """

    async def check(
        self,
        page: Page,
        expectation: StateExpectation | None,
        pre_state_snapshot: dict | None,
    ) -> VerifierResult:
        """
        Contract:
        - If expectation is provided, dispatch to the kind-specific probe.
        - Else, run the default probe set against pre_state_snapshot.
        - Returns VerifierResult; never raises (all Playwright errors caught).
        - verifier_path is set to "dom_only" on resolved=True.
        - On resolved=False, caller MUST cascade to VisionVerifier and set
          verifier_path="dom_inconclusive_vision_ran" on the final result.
        """
        ...


# ── NEW class: VisionVerifier (wraps existing Bedrock call) ──────

class VisionVerifier:
    """Thin wrapper around the existing Sonnet vision verification call."""

    async def check(
        self,
        page: Page,
        screenshot_b64: str,
        ac_step: str,
    ) -> VerifierResult:
        ...
```

**Modification: `step_verifier_node()` (line 1631)** — cascade logic:

```python
# After the pre-state snapshot + fresh screenshot capture:

dom = DomVerifier()
state_expectation = planned_action.get("state_expectation")  # dict or None
if state_expectation is not None:
    state_expectation = _deserialize_expectation(state_expectation)

dom_result = await dom.check(
    page=_page,
    expectation=state_expectation,
    pre_state_snapshot=state.get("pre_action_state_snapshot"),
)

if dom_result.resolved:
    result = dom_result  # verifier_path="dom_only"
else:
    vision = VisionVerifier()
    vision_result = await vision.check(_page, screenshot_b64, current_step)
    vision_result.verifier_path = "dom_inconclusive_vision_ran"
    result = vision_result

# Emit telemetry
logger.info(
    json.dumps({
        "event": "verifier_result",
        "run_id": run_id,
        "ac_index": ac_index,
        "verifier_path": result.verifier_path,
        "verdict": result.verdict.value,
        "check_kind": result.check_kind,
        "elapsed_ms": result.elapsed_ms,
        "tokens_used": result.tokens_used,
        "evidence": result.evidence,
    })
)
```

**Modification: `planner.py` (state_expectation emission)** — extend the tool-call JSON schema returned by the DOM-mode and Vision-mode planner around lines 4498–4536 (the SoM prompt-fragment injection surface, per the spec's T2-c pointer). Add `state_expectation` as an optional field in the structured output schema. The system prompt gains a short section (target: ~150 tokens) titled "State Expectation (optional)" listing 4–5 of the most common taxonomy kinds with examples. This is intentionally under-specified in the prompt — we want the planner to emit expectations opportunistically, and rely on the default probe set for the rest.

**Backward compat**: `PredictiveVerifier` at `verifier.py:2419` is *not deleted*. It becomes the fallback implementation invoked when `state_expectation` is a plain string (legacy format) rather than a dict — `DomVerifier` detects this and delegates. Existing callers of `PredictiveVerifier` remain functional.

### 2.7 Testability Hooks (T2-d)

- `fixtures/verifier_transitions.jsonl` — 20 rows, each with `{ac_step, planned_action, pre_state_snapshot, page_html_pre, page_html_post, historical_ms, historical_tokens, expected_verdict}`. Fixtures cover: 5 `aria_expanded`, 5 `url_delta`, 5 `element_count`, 3 `dialog_open`, 2 `toast_visible`. Loaded into a headless in-process Playwright page for the test.
- `fixtures/verifier_false_not_yet.jsonl` — 50 rows sampled from `execution_log.jsonl` history where historical verdict was `NOT_YET` but human-ground-truth was `PASS`. Same schema as above.
- `test_verifier_split.py::test_dom_resolution_rate_at_least_60pct` — iterates the 20-case fixture, asserts ≥12 return `resolved=True` without invoking `VisionVerifier` (patched to raise).
- `test_verifier_split.py::test_dom_path_saves_500ms` — for each `resolved=True` case, asserts `result.elapsed_ms + 500 <= fixture["historical_ms"]`.
- `test_verifier_split.py::test_dom_path_saves_90pct_tokens` — asserts `result.tokens_used <= 0.10 * fixture["historical_tokens"]` (which is 0 for pure-DOM cases).
- `test_verifier_split.py::test_false_not_yet_rate_at_most_10pct` — iterates the 50-case fixture through the cascaded path, asserts ≤ 5 return `NOT_YET`.
- `test_verifier_split.py::test_verifier_path_telemetry_field` — asserts the JSON log line contains `verifier_path ∈ {"dom_only", "dom_inconclusive_vision_ran", "vision_only"}`.

The `VerifierResult.verifier_path` field is the load-bearing telemetry pinned in the spec (AC "Observable at → new JSONL field `verifier_path`"). It has a stable home now.

### 2.8 Interaction with Failure Diary Pattern

When `DomVerifier` resolves `NOT_YET`, the failure diary at `state["ac_step_failure_diary"]` gains a new entry kind:

```python
{
    "kind": "verifier_not_yet",
    "verifier_path": "dom_only",
    "check_kind": "aria_expanded",
    "evidence": "aria-expanded=false, expected true",
    "ac_step_index": 5,
}
```

This gives the planner ground-truth-shaped feedback: instead of "vision says NOT_YET, try again," it now sees "the p-select never opened; try a different trigger." This is the specific defect the spec's T2-d addresses — the planner burning retries because the verifier's error signal was too generic.

---

## Question 3 — Backfill Script Source Selection

### 3.1 Problem Statement

`scripts/backfill_ac_parse_cache.py` needs to pre-populate `storage/ac_parse_cache/<sha256_of_raw_ac>.json` from prior successful parses so the first cache-hit after deploy isn't a cold miss. The question: **where does the historical raw AC text come from?**

Codebase inspection (see § 3.2 below) reveals the load-bearing fact: **`backend/storage/run_history.py` does not persist raw AC text** — its SQLite schema at line 78 stores only `ticket_id`, `role`, `status`, and aggregates. Neither does `execution_log.jsonl`. The only place raw AC text lives after a run is:

1. **Jira** (source of truth) — re-fetchable via `customfield_10031` for any prior `ticket_id` in `run_history`. Rate-limited (60 req/min per Jira Cloud plan).
2. **In-memory `ACStepCache`** at `backend/jira/cache.py:68` — populated at runtime, lost on process restart. Not persistent.
3. **HTML audit reports** on S3 (`vcreative-deployments/.../vqa-results/`) — these embed the parsed steps but not the raw text.

`storage/qa/` (per `find`) contains Playwright `storageState_*.json` auth blobs, NOT archived AC parses. This corrects an assumption in the spec's Migration Path section.

### 3.2 Options Explored

#### Option 3A — Jira re-fetch every historical ticket

Iterate `SELECT DISTINCT ticket_id FROM runs` from `run_history.db`; for each, fetch via `backend/jira/client.py`, parse (running the same Stage 1 + Stage 2 pipeline), write to `storage/ac_parse_cache/`.

- **Pros**:
  - Complete coverage — every ticket ever run gets a cache entry.
  - Uses production code paths for parsing → cache entries are guaranteed compatible with the runtime.

- **Cons**:
  - **Cost**: N tickets × (2 Bedrock calls + 1 Jira fetch). For ~500 historical tickets: ~1000 Sonnet calls (~$5–$15) + 500 Jira reads (well within rate limit if paced at 10/min → 50 min wall-clock).
  - **Determinism concern**: Jira tickets change. A ticket that was parsed 3 months ago may have updated AC today — backfilling the *current* AC under a hash keyed to the *current* text is correct (that's the invalidation semantic of T2-a), but this means we're not really "backfilling," we're "pre-warming with current state."
  - Requires Jira credentials at script-run time.

- **Complexity**: LOW.
- **One-way-door risk**: LOW.

#### Option 3B — Skip pre-existing tickets; let cache warm organically

Ship T2-a with an empty `storage/ac_parse_cache/`. First run of each ticket is a miss + parse + write. Subsequent runs hit the cache.

- **Pros**:
  - Zero cost, zero script.
  - No Jira dependency at deploy time.
  - Simplest — the cache warms itself.

- **Cons**:
  - AC-VERIFY-2's "cache hit under 50ms" is only observable *after* a first-miss populates it. This is trivially satisfiable in the test (mock a warm cache), but the *live* cache-hit rate starts at 0% and climbs over the first few sprints.
  - Every historical ticket re-runs the full Stage 1 + Stage 2 pipeline the first time it's touched after deploy → determinism regression for those specific runs unless T2-a's temperature=0.0 already fixed it (which it did).

- **Complexity**: TRIVIAL.
- **One-way-door risk**: NONE.

#### Option 3C — Hybrid: opportunistic Jira fetch for the top-N most-run tickets

Query `run_history.db` for the top-N (default 20) most-run ticket_ids in the last 90 days. Jira-fetch and cache-pre-warm those. Skip the rest with a log line `backfill_skipped: {n_skipped} tickets left to warm organically`.

- **Pros**:
  - Amortizes the cost — pre-warms the tickets that matter, skips one-offs.
  - AC-VERIFY-2 live-observable within one deploy for the tickets the team actually reruns.
  - Naturally handles the "un-migratable" case (older tickets that no longer exist in Jira) — they're either in the top-N (fail-fast on 404 with a log) or the tail (skipped by default).

- **Cons**:
  - Two code paths (warm-list vs. skip-list) — slightly more test surface.

- **Complexity**: LOW.
- **One-way-door risk**: NONE.

### 3.3 Evaluation Matrix

| Criteria (weight) | 3A (all) | 3B (skip all) | 3C (top-N) |
|---|---|---|---|
| AC-VERIFY-2 live observability (H) | 10 | 5 | 9 |
| Cost (M) | 5 | 10 | 8 |
| Jira dependency at deploy (M) | 5 | 10 | 7 |
| Determinism preservation (H) | 8 | 6 | 9 |
| Handles un-migratable tickets (M) | 6 | 10 | 10 |
| Complexity (M) | 9 | 10 | 8 |
| **Weighted total** | **7.4** | **8.1** | **8.6** |

### 3.4 Decision — Option 3C (Top-N pre-warm)

The top-N heuristic dominates on the live-observability axis while preserving cost proportionality. Ship with `N=20` as the default; `--top-n` CLI flag overrides.

### 3.5 Implementation Guide (Backfill)

**New file: `scripts/backfill_ac_parse_cache.py`** (~150 lines)

```python
"""
vQA — Pre-warm storage/ac_parse_cache/ from prior runs.

Selects the top-N most-run ticket_ids in the last 90 days from
run_history.db, fetches current AC text from Jira, parses via
the production Stage 1 + Stage 2 pipeline (temperature=0.0),
and writes {sha256(raw_ac)}.json entries to the cache dir.

Skipped tickets are logged, not fatal. Jira 404s are logged and skipped.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--cache-dir", default="storage/ac_parse_cache")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ticket_ids = _query_top_n_tickets(args.top_n, args.days)
    print(f"[backfill] Selected {len(ticket_ids)} tickets to pre-warm")

    warmed, skipped_404, skipped_error = 0, 0, 0
    for ticket_id in ticket_ids:
        try:
            raw_ac = await _fetch_raw_ac_from_jira(ticket_id)
        except JiraNotFound:
            skipped_404 += 1
            print(f"[backfill] SKIP {ticket_id} — Jira 404")
            continue
        except Exception as e:
            skipped_error += 1
            print(f"[backfill] SKIP {ticket_id} — {e}")
            continue

        content_hash = hashlib.sha256(raw_ac.encode()).hexdigest()
        cache_path = Path(args.cache_dir) / f"{content_hash}.json"
        if cache_path.exists():
            print(f"[backfill] EXISTS {ticket_id} — hash={content_hash[:8]}")
            continue

        if args.dry_run:
            print(f"[backfill] DRY {ticket_id} → {cache_path}")
            continue

        # Re-parse using the same pipeline the runtime uses
        test_plan = await _parse_with_production_pipeline(raw_ac, ticket_id)
        cache_path.write_text(json.dumps({
            "ticket_id": ticket_id,
            "raw_ac_hash": content_hash,
            "test_plan": test_plan,
            "backfilled_at": _utc_now_iso(),
            "backfill_version": "1.0",
        }, indent=2))
        warmed += 1

    print(f"[backfill] Complete: warmed={warmed}, 404s={skipped_404}, errors={skipped_error}")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

**Coordination with T2-a**: the runtime cache-read at `ac_parser_node` (Phase 1) checks `storage/ac_parse_cache/{sha256(raw_ac)}.json` FIRST, falling through to `ACStepCache` (the in-memory tier at `jira/cache.py:68`), then to the LLM pipeline. The backfill script populates only the content-hash layer, never touching the in-memory tier. This preserves the layering documented in the spec's T2-a section.

### 3.6 Un-Migratable Ticket Policy

Explicit contract for tickets that cannot be re-warmed:

- **Jira 404** (ticket deleted): logged as `backfill_skipped: {ticket_id} reason=jira_404`; NO cache entry written; NO failure raised. The next runtime encounter of this ticket (if any) will produce a cache miss and re-parse from whatever Jira returns.
- **Ticket AC changed since original run**: expected and correct. The new hash gets a new cache entry; the old parse is effectively unreachable (its hash won't be queried). This is the invalidation semantic the T2-a design already requires.
- **Ticket present but AC field missing**: logged as `backfill_skipped: {ticket_id} reason=no_ac_field`; skipped.

No stub cache entries are ever written on error. This matches the AC-ERROR-1 non-poisoning principle (any state that would poison future matches is surfaced, not persisted).

---

## Cross-Cutting Concerns

### Observability (all three subsystems)

Per project OpenTelemetry standards (CLAUDE.md § Observability Standards):

- All new INFO/WARN log lines are structured JSON with fields: `event`, `run_id`, `trace_id`, `span_id`, `service="vqa-backend"`, plus subsystem-specific fields.
- New events:
  - `hitl_trace_parse_ok` / `hitl_trace_parse_failed` (T2-b)
  - `verifier_result` with `verifier_path` field (T2-d — the load-bearing telemetry pinned in the spec's Observable-at bullet)
  - `backfill_warmed` / `backfill_skipped` (Backfill)
- No `console.log`/print in production code paths (backfill script uses `print` because it's a CLI, matching techContext.md convention for scripts).
- No sensitive data (role credentials, S3 presigned URLs) in any new log.

### Backward Compatibility Guarantees

- `RecipeRegistry` for human-curated recipes (`knowledge/blueprints/*.yaml`): behavior UNCHANGED. Only the `_load_all()` glob is extended to walk `generated/` in addition to the parent.
- `PredictiveVerifier` at `verifier.py:2419`: retained. Callers unchanged. Becomes an internal implementation branch of `DomVerifier` for string-formatted `state_expectation` values.
- `planned_action` dict schema: `state_expectation` is optional. Missing → default probe set. Existing planner code paths that don't emit it continue to work.
- `ACStepCache` at `jira/cache.py:68`: in-memory tier UNCHANGED. Content-hash tier is a new *outer* layer, not a replacement.
- No API changes (`/execute`, `/execute-batch`, WebSocket schema): none of these three subsystems touch the HTTP surface.

### Interaction with the Failure Diary

Both T2-b and T2-d write to the diary, but with distinct entry kinds so the planner-side consumer (see `planner.py` failure-diary rendering, referenced from CLAUDE.md § Failure Diary Pattern) can render them differently:

- T2-d `verifier_not_yet` (Q2, § 2.8) — informs the planner that the intended DOM state didn't materialize; suggests trying a different trigger element.
- T2-b — the trace-parse process itself does not write to the diary. Trace parse failure (AC-ERROR-1) writes a WARN log only. Rationale: the human already unblocked the step; a diary entry would poison future retries with a "recovery failed" signal.

### Guiding-Principle Deviations

**None.** All three decisions strengthen existing principles:

| Principle | How this design reinforces it |
|---|---|
| Programmatic Tier 1 Verification | T2-d puts DOM checks in front of vision; principle is now enforced in code, not just aspiration |
| HITL as Learning Signal | T2-b's Option 1A (sync parse) guarantees every HITL → Recipe; no orphan takeovers |
| Semantic Locators First | T2-b's trigger-phrase synthesis (§ 1.6) prefers `aria-label` and `role`-derived text over CSS |
| Failure Diary Pattern | T2-d adds a new diary entry kind (`verifier_not_yet`) that gives the planner shape-of-failure feedback the current generic "NOT_YET" signal lacks |

---

## Consolidated Contract Definitions (Load-Bearing Code Blocks)

### `TraceParserResult` (T2-b intermediate output — enables AC-ERROR-1)

```python
# backend/engine/hitl_trace_parser.py

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TraceParseFailureReason(str, Enum):
    CORRUPTED_ZIP = "corrupted_zip"
    NO_TRACE_FILE = "no_trace_file"
    NO_INTERACTIVE_EVENTS = "no_interactive_events"
    UNRESOLVABLE_SELECTOR = "unresolvable_selector"
    SCHEMA_MISMATCH = "schema_mismatch"


@dataclass
class ExtractedAction:
    event_type: str            # "click" | "fill" | "select" | "press"
    selector: str
    selector_kind: str         # "role" | "label" | "text" | "css"
    value: str | None
    aria_label: str | None
    timestamp_ms: int
    call_id: str


@dataclass
class TraceParserResult:
    ok: bool
    actions: list[ExtractedAction] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)
    recipe_yaml_path: Path | None = None
    failure_reason: TraceParseFailureReason | None = None
    failure_detail: str = ""
    zip_path: Path | None = None
    parse_duration_ms: int = 0
```

### `StateExpectation` (T2-d input — the closed taxonomy)

```python
# backend/engine/verifier.py (new dataclasses)

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Union


@dataclass(frozen=True)
class AriaExpandedCheck:
    kind: Literal["aria_expanded"] = "aria_expanded"
    selector: str = ""
    expected: bool = True

@dataclass(frozen=True)
class AriaSelectedCheck:
    kind: Literal["aria_selected"] = "aria_selected"
    selector: str = ""
    expected: bool = True

@dataclass(frozen=True)
class AriaCheckedCheck:
    kind: Literal["aria_checked"] = "aria_checked"
    selector: str = ""
    expected: bool | Literal["mixed"] = True

@dataclass(frozen=True)
class UrlDeltaCheck:
    kind: Literal["url_delta"] = "url_delta"
    pattern: str = ""
    mode: Literal["contains", "regex"] = "contains"

@dataclass(frozen=True)
class UrlEqualsCheck:
    kind: Literal["url_equals"] = "url_equals"
    expected: str = ""

@dataclass(frozen=True)
class ElementCountCheck:
    kind: Literal["element_count"] = "element_count"
    selector: str = ""
    op: Literal[">", "<", "==", "!="] = "=="
    count: int = 0

@dataclass(frozen=True)
class ElementVisibleCheck:
    kind: Literal["element_visible"] = "element_visible"
    selector: str = ""
    expected: bool = True

@dataclass(frozen=True)
class ElementHiddenCheck:
    kind: Literal["element_hidden"] = "element_hidden"
    selector: str = ""

@dataclass(frozen=True)
class TextContentCheck:
    kind: Literal["text_content"] = "text_content"
    selector: str = ""
    contains: str = ""

@dataclass(frozen=True)
class ClassContainsCheck:
    kind: Literal["class_contains"] = "class_contains"
    selector: str = ""
    class_name: str = ""
    expected_present: bool = True

@dataclass(frozen=True)
class FocusOnCheck:
    kind: Literal["focus_on"] = "focus_on"
    selector: str = ""

@dataclass(frozen=True)
class DialogOpenCheck:
    kind: Literal["dialog_open"] = "dialog_open"
    title: str | None = None

@dataclass(frozen=True)
class ToastVisibleCheck:
    kind: Literal["toast_visible"] = "toast_visible"
    severity: Literal["success", "error", "info", "warn"] | None = None
    contains: str | None = None

@dataclass(frozen=True)
class AllOfCheck:
    kind: Literal["all_of"] = "all_of"
    children: tuple["StateExpectation", ...] = ()

@dataclass(frozen=True)
class AnyOfCheck:
    kind: Literal["any_of"] = "any_of"
    children: tuple["StateExpectation", ...] = ()


StateExpectation = Union[
    AriaExpandedCheck, AriaSelectedCheck, AriaCheckedCheck,
    UrlDeltaCheck, UrlEqualsCheck, ElementCountCheck,
    ElementVisibleCheck, ElementHiddenCheck, TextContentCheck,
    ClassContainsCheck, FocusOnCheck, DialogOpenCheck, ToastVisibleCheck,
    AllOfCheck, AnyOfCheck,
]
```

### `VerifierResult` (T2-d output — houses the `verifier_path` telemetry field)

```python
# backend/engine/verifier.py

class VerifierVerdict(str, Enum):
    PASS = "PASS"
    NOT_YET = "NOT_YET"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass
class VerifierResult:
    """
    Shared return shape of DomVerifier.check() and VisionVerifier.check().

    verifier_path is the load-bearing telemetry field pinned in FEAT-117's
    spec — it lands in execution_log.jsonl and drives the AC-VERIFY-5
    resolution-rate assertions.
    """
    resolved: bool                                             # True → verdict is authoritative
    verdict: VerifierVerdict
    evidence: str                                              # human-readable one-liner
    verifier_path: Literal[
        "dom_only",
        "dom_inconclusive_vision_ran",
        "vision_only",
    ]
    check_kind: str = ""                                       # e.g. "aria_expanded"
    elapsed_ms: int = 0
    tokens_used: int = 0
```

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Playwright trace schema changes in a minor version bump | Medium | Medium | Pin `playwright==1.49.*`; fixture-based test detects schema drift on upgrade |
| Planner rarely emits `state_expectation` → default probe set carries the load | Medium | Low | Default probe set is designed to hit AC-VERIFY-5 60% alone; planner emission is upside, not required |
| Auto-generated recipes with bad triggers pollute matching | Low | Medium | `_provenance` field + human-curated recipes win ties; `match()` scoring unchanged |
| Backfill script fails partway through (Jira outage) | Low | Low | Idempotent — re-run resumes from where it left off (skips existing hashes) |
| Sync parse in `human_takeover_node` blocks event loop too long | Low | Low | 1500ms target with hard cap; migration path to async is a 2-hour refactor |
| AC-VERIFY-5 fixture set (20 cases) doesn't reflect production distribution | Medium | Medium | Sample from `execution_log.jsonl` history, spanning all 13 taxonomy kinds; document sampling procedure in fixture header |

---

## Validation Checklist

- [x] Meets AC-VERIFY-3 and AC-INTEGRATION-1 requirements (Option 1A synchronous parse)
- [x] Meets AC-VERIFY-5 (Option 2C hybrid + closed taxonomy)
- [x] Meets AC-VERIFY-6 (default probe set + planner-emitted expectations both cascade to vision)
- [x] Meets AC-ERROR-1 (parser returns TraceParserResult, never raises; `.zip` preserved on failure)
- [x] Respects Guiding Principles: Programmatic Tier 1 Verification (reinforced), HITL as Learning Signal (reinforced), Failure Diary Pattern (extended), Semantic Locators First (preferred in trigger synthesis)
- [x] Backward compatible: RecipeRegistry human-curated behavior unchanged, PredictiveVerifier retained, planned_action optional field, ACStepCache in-memory tier untouched
- [x] Observability: structured JSON logs with traceparent, `verifier_path` telemetry field pinned in a documented shape
- [x] All contracts are Python dataclasses (not free-form dicts) — Pydantic-compatible for future serialization

---

## Next Steps

1. **Phase 2 build (`/bmb:build`)** implements T2-b per § 1.7 using this contract. Existing task file `Test Strategy → Phase 2` lists 3 tests — all three reference the `TraceParserResult` dataclass defined here.
2. **Phase 4 build** implements T2-d per § 2.6 using the `StateExpectation` union and `VerifierResult` dataclass. Fixtures `verifier_transitions.jsonl` and `verifier_false_not_yet.jsonl` are created during Phase 4 per the sampling procedure documented above.
3. **Backfill script** is a one-off, implemented alongside Phase 1 (T2-a) since it depends on `storage/ac_parse_cache/` being the runtime source of truth.
4. This document is referenced from the task file's `## Creative Phases` section at archive time.

---

## NEW_TERMS_INTRODUCED

Consider these for the project glossary (`memory-bank/glossary.md` if it exists, or the taxonomy sections of `systemPatterns.md`):

- **`StateExpectation`** — Tagged union of DOM check kinds emitted by the planner (or synthesized as a default probe set) and consumed by `DomVerifier`. See § 2.5 for the closed taxonomy.
- **`VerifierResult`** — Shared return shape of `DomVerifier.check()` and `VisionVerifier.check()`. Carries the `verifier_path` telemetry field.
- **`VerifierVerdict`** — Enum of `PASS | NOT_YET | INCONCLUSIVE`. `INCONCLUSIVE` is the DOM-tier signal that vision should be consulted.
- **`TraceParserResult`** — Return type of `hitl_trace_parser.parse_trace()`. Never raises. Carries `ok: bool`, extracted actions, or a `TraceParseFailureReason` on failure.
- **`ExtractedAction`** — A single DOM interaction extracted from a Playwright trace (event type, semantic selector, value, aria-label, timestamp).
- **`TraceParseFailureReason`** — Enum of parse-failure kinds (`CORRUPTED_ZIP`, `NO_TRACE_FILE`, `NO_INTERACTIVE_EVENTS`, `UNRESOLVABLE_SELECTOR`, `SCHEMA_MISMATCH`).
- **`generated recipe`** — An `ActionRecipe` YAML written to `knowledge/blueprints/generated/` by the HITL trace parser. Distinguished from human-curated recipes under `knowledge/blueprints/*.yaml` by directory and by an internal `_provenance` field. Human-curated recipes win ties in `RecipeRegistry.match()`.
- **`default probe set`** — The ordered sequence of 5 deterministic DOM checks (`url_delta`, `element_count`, `aria_expanded` scan, `dialog_open`, `toast_visible`) that `DomVerifier` runs when no `state_expectation` is provided by the planner. See § 2.5.
- **`verifier_path`** — Structured-log telemetry field indicating which verifier tier resolved the check: `"dom_only" | "dom_inconclusive_vision_ran" | "vision_only"`. Emitted on every verifier call, drives AC-VERIFY-5 assertions.
