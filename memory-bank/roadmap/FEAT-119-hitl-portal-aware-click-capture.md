---
legacy_id: FEAT-119
version: next
linked_tasks: []
status: planned
---

### FEAT-119: HITL Portal-Aware Click Capture

- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 2
- **Origin**: Follow-up from FEAT-117 (T2-b) post-archive verification (see `memory-bank/archive/vqa-tier2-planner-memory-hardening-archive.md` § Post-Archive Verification, 2026-07-28)
- **Description**: The T2-b HITL Playwright Tracing Memory feature (FEAT-117 / vqa-tier2-planner-memory-hardening / phase T2-b) shipped its plumbing correctly but failed AC-INTEGRATION-1 on live validation. Playwright's `browser_context.tracing.start()` records **actions dispatched through the Playwright API** (`page.click`, `page.fill`, `locator.select_option`, etc.) — it does NOT record raw mouse/keyboard input from a human interacting with a headful Chromium window. When the operator takes over a HITL step and clicks in the popped-up browser directly, those events go straight to the renderer without passing through Playwright's dispatcher, so `trace.trace` has only `context-options` + `screencast-frame` entries. The parser correctly returns `NO_INTERACTIVE_EVENTS`, preserves the zip, and refuses to write a stub Recipe (AC-ERROR-1 works as designed) — but no Recipe is ever produced, so no replay is possible.

  This feature restores a JS click-capture listener with a portal-aware attachment strategy — attach on `document.body` in **capture phase**, listen for `pointerdown` / `click` including `composed: true` events (Shadow DOM / portals), and route event data via CDP `Runtime.addBinding` so events survive `stopPropagation()` from PrimeNG p-select components. Keep T2-b's `tracing.start()` invocation as-is for the screencast-video artifact (useful for post-mortem viewing), but don't rely on `trace.trace` for actionable event data.

- **Acceptance Criteria**:
    - **AC-1**: On a HITL takeover for the QA-358 "Select Contest from PRF Category dropdown" step, the operator's real-mouse click on the PrimeNG p-select trigger AND the subsequent "Contest" selection are both captured as `{selector, event_type, value}` entries and written to a Recipe YAML under `knowledge/blueprints/generated/`. The old log line `KB auto-update skipped ... no DOM actions captured during takeover` does NOT appear.
    - **AC-2**: On a fresh run of the same ticket immediately after (no HITL required), `RecipeRegistry` matches the generated Recipe on trigger keywords ("contest", "prf category", etc.), and the executor drives the dropdown open + selects "Contest" via the recorded actions without escalating to HITL. `execution_log.jsonl` records `strategy: "recipe"` for that AC step.
    - **AC-3**: The click-capture listener correctly handles at least these three portal patterns: (a) PrimeNG `p-select` panel (portal appended to `body`), (b) native `<select>` menu (OS-native, may not be capturable — document + surface via `NO_NATIVE_SELECT_EVENTS`), (c) PrimeNG `p-dropdown` overlay. Portal-attached elements' events reach the listener via capture phase + `composed: true`.
    - **AC-4**: The listener uses CDP `Runtime.addBinding` (via `page.expose_binding` or equivalent) to buffer events into a Python-side collector that survives `event.stopPropagation()` from PrimeNG components. Unit test verifies that a stopPropagation'd event still reaches the collector.
    - **AC-5**: Regression: the existing `test_hitl_tracing.py` fixture-based tests still pass. T2-b's parser is unchanged; this feature adds a supplementary event-capture path that produces the events T2-b's parser expects.
    - **AC-6**: The `_takeover_seq` numbering, zip write, and trace-artifact side effects from T2-b are preserved. The Recipe is now populated from JS-listener events (primary) with the Playwright trace kept only as a screencast-video artifact for post-mortem.
    - **AC-INTEGRATION-1** (blocked by AC-2, verified manually): Two consecutive live runs of QA-358 against `two-test.vcreative.net`: run 1 with HITL produces a Recipe; run 2 replays it without HITL. This is the AC-INTEGRATION-1 that FEAT-117 could not deliver.

- **Key Files**:
    - `backend/engine/human_takeover.py` — restore/refactor `_inject_click_capture_listener()`; ensure event data lands in a Python collector via CDP binding
    - `backend/engine/hitl_trace_parser.py` — potentially extend to consume the JS-listener event stream (or keep it as-is if events land directly in the takeover node's state)
    - `backend/engine/test_hitl_click_capture.py` (New) — unit tests for portal-phase capture, stopPropagation survival, composed-event handling
    - `backend/engine/fixtures/hitl_portal_events.jsonl` (New) — captured events from a real p-select interaction, used to test the parser without a live browser
    - `memory-bank/reflection/vqa-tier2-planner-memory-hardening-reflection.md` — reference from § Post-Archive Verification for context

- **Notes / Explicitly Out of Scope**:
    - This feature does NOT re-architect the T2-b tracing path. T2-b's plumbing, error handling, and screencast artifact production stay. The JS listener supplements the trace, it doesn't replace `tracing.start()`.
    - Dashboard-mediated HITL (where operators route clicks through the frontend UI back into Playwright's API) is a possible alternative (option F3 from the post-archive discussion) but a bigger UX shift; explicitly deferred.
    - Native `<select>` element events may not be capturable via JS listeners (they trigger OS-native menus). If AC-3 (b) proves infeasible in the build, document the limitation in the reflection doc and treat it as a known gap for a future task (e.g., "convert native select handling to Playwright API `select_option()` when detected").
