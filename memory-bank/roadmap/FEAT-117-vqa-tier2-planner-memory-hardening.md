---
legacy_id: FEAT-117
version: next
linked_tasks: [vqa-tier2-planner-memory-hardening]
status: completed
---

### FEAT-117: vQA Tier 2 — Planner & Memory Hardening (Structural)
- **Version**: next
- **Status**: completed
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Address the structural failure modes surfaced by the 2026-07-27 QA-358 analysis: non-deterministic AC parsing (same ticket → 17, 33, 48, 51, 55 steps across runs), amnesic HITL (human takeovers produce no replayable memory because the JS click listener misses PrimeNG portal clicks), a CV-vision fallback that silently converts "vision saw no target" back into another DOM strict-mode violation, a verifier that burns a Sonnet vision call per AC step with ~30% false-negative rate, and a PromptBudget that evicts core planner instructions before it evicts retry noise. These are the "why is vQA getting worse under pressure" failure modes.

  Implementation is phased:
  1. **Deterministic AC Parsing (T2-a)** — Two complementary mechanisms: (i) cache parsed step arrays by content hash of the raw AC text — reuse on cache hit, only invalidate on ticket update; (ii) lower parser temperature to 0.0 and add a schema-constrained retry with a heuristic `min_steps`/`max_steps` gate ("split on ordered-list markers, one step per list item"). Result: same ticket → same steps across runs, and regressions become gate-able in CI.
  2. **HITL Playwright Tracing Memory (T2-b)** — Replace the JS click-capture listener in `_inject_click_capture_listener` (`human_takeover.py:503`) with a full Playwright tracing session started when HITL begins and stopped when it ends. Playwright traces capture every action at the CDP level — including OS-native `<select>` menu selections and PrimeNG portal clicks that the JS listener misses. Parse the trace into a `Recipe` that is registered for future replay. Every HITL becomes a permanent, replayable fix instead of a one-shot rescue.
  3. **Route mark_id=None Diagnostically (T2-c)** — When CV vision returns `mark_id=None`, do NOT re-emit a `get_by_text` DOM click in the executor (current `executor.py:678-684` behavior). Instead, route back to the planner with a diagnostic prompt fragment: "Vision saw N marks; none matched '<target>'. Options: (a) a container must be opened, (b) the page needs to scroll, (c) the target text is a paraphrase — try synonyms." Prohibit repeating the previous `get_by_text` strategy in the same AC step.
  4. **Split Verifier — DOM-first, Vision as Tie-Breaker (T2-d)** — Introduce a fast DOM verifier that re-queries the page for a known selector or aria-state change (e.g., "did the `<p-select>`'s `aria-expanded` toggle?"). Run it BEFORE any Sonnet vision call. Vision only runs when the DOM check is inconclusive. Kills the Contest false-NOT_YET in ~50ms instead of ~2500ms, and reduces per-step LLM cost.
  5. **Fix PromptBudget Eviction Priority (T2-e)** — Add an `evictable: bool` field to each budget section. Mark `reasoning_workflow`, the current AC step description, and the interactive-elements list as `evictable=False`. The failure diary and `global_run_context` become the trimming candidates. Enforce in `prompt_budget.py`. The planner keeps its thinking framework when it needs it most.

- **Acceptance Criteria**:
    - AC-1: Parsing the same Jira ticket (fixed content) via `ac_parser.parse()` twice returns identical step arrays (same count, same titles). Verified across 5 back-to-back runs of QA-358 and a matched fixture set — no drift within a ±0 step budget on the cached path.
    - AC-2: When AC content changes (verified by SHA-256 of the raw AC text), the parse cache invalidates and re-parses. When it does not change, cached parse is reused with < 50ms round trip.
    - AC-3: Playwright tracing produces a `.zip` trace file on every HITL takeover. A trace parser converts the recorded actions into a `Recipe` JSON that includes the selectors, values, and event types (click, fill, change) for at least the last successful DOM interaction before takeover completion.
    - AC-4: A HITL takeover for the QA-358 "Select Contest from PRF Category dropdown" step produces a Recipe entry that, when replayed on a fresh run, drives the dropdown open and selects "Contest" without further HITL. The old "KB auto-update skipped: no DOM actions captured" log line no longer appears for portal/select interactions.
    - AC-5: When CV vision returns `mark_id=None`, the executor does NOT re-emit a DOM click on the target text. The planner receives a diagnostic prompt fragment containing at least one of "open a parent container", "scroll", "try synonyms". Prompt logs (`.logs/prompts/`) show the fragment.
    - AC-6: The verifier splits into `DomVerifier.check()` and `VisionVerifier.check()`. On 20 sampled successful AC-step-transition cases from log history, the DOM verifier alone resolves ≥ 60% without invoking vision. Wall-clock reduction ≥ 500ms per resolved case; token cost reduction ≥ 90% per resolved case.
    - AC-7: The verifier's false-NOT_YET rate (measured on a curated set of 50 previously-observed post-action states) drops from the current ~30% baseline to ≤ 10%.
    - AC-8: PromptBudget's `evictable` mechanism is enforced: `reasoning_workflow`, `interactive_elements`, and `current_ac_step` are NEVER dropped, even when the diary + global_run_context are both non-empty. Failure diary is trimmed first when over budget.

- **Key Files**:
    - `backend/engine/ac_parser.py` — T2-a: content-hash cache, temperature=0.0, min/max step gate
    - `backend/engine/human_takeover.py` (line 503 area) — T2-b: Playwright tracing session, trace-to-Recipe parser
    - `backend/engine/recipe_runner.py` — T2-b: consume auto-generated recipes from HITL traces
    - `backend/browser/cv_resolver.py` — T2-c: return diagnostic reason with `mark_id=None`, not a fallback text click
    - `backend/engine/planner.py` (lines 4504-4536) — T2-c: consume vision diagnostic reason as prompt fragment
    - `backend/engine/executor.py` (lines 678-684) — T2-c: remove `get_by_text` fallback when planner returned `mark_id=None`
    - `backend/engine/verifier.py` — T2-d: split into DomVerifier + VisionVerifier; run DOM check first
    - `backend/engine/prompt_budget.py` — T2-e: `evictable` field + enforced ordering
    - `storage/ac_parse_cache/` (New) — content-hash-keyed parse cache
    - `scripts/backfill_ac_parse_cache.py` (New) — pre-populate cache from prior successful runs
    - `backend/engine/test_ac_parser_determinism.py` (New) — parse determinism regression tests
    - `backend/engine/test_hitl_tracing.py` (New) — HITL trace-to-Recipe integration tests
    - `backend/engine/test_verifier_split.py` (New) — DOM verifier vs. vision verifier coverage tests
- **Linked Tasks**: None
- **Branch**: feature/FEAT-117-vqa-tier2-planner-memory-hardening
- **Created**: 2026-07-28
- **Depends On**: FEAT-116 (Tier 1 executor recovery — some Tier 2 tests rely on the actionable errors T1-a introduces)
