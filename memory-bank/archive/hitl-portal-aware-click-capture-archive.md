# Archive: HITL Portal-Aware Click Capture

## Metadata
- Task: hitl-portal-aware-click-capture
- Complexity: Level 3
- Started: 2026-07-28
- Completed: 2026-07-29
- Roadmap Link: hitl-portal-aware-click-capture
- Feature Branch: feature/hitl-portal-aware-click-capture
- Feature Type: NFR/Infrastructure

## Summary

Closed a latent correctness gap in the HITL (Human-in-the-Loop) capture pipeline: when a QA operator clicked inside a PrimeNG portal-mounted overlay (dropdown panels, autocomplete lists, tiered menus mounted as `<body>` children via Angular CDK), the existing JS listener recorded the detached leaf element's CSS path — a string the executor could never resolve on replay. The fix extends the injected JS listener with layered portal detection and trigger resolution, derives a `capture_confidence` enum in JS, and adds three serializer branches so full captures emit `primeng_dropdown`, partial captures emit a scoped `click` with `container_selector`, and non-portal clicks remain byte-identical. Phase 2 extends the Playwright trace parser with pattern-based portal detection so trace-derived ActionRecipe YAML also encodes portal actions.

The feature is transparent to the operator — no new UI, no toggle. The acceptance surface is data correctness in the four persistence sinks: `learned_workflows.json`, `human_guidance.md`, ActionRecipe YAML, and `selector_registry.json`. The out-of-scope boundary — the `primeng_dropdown` executor handler at `backend/engine/executor.py:2160` — was verified untouched.

## Requirements

### Original Requirements
- Detect clicks landing in PrimeNG portal-mounted overlays during HITL takeover
- Resolve the logical trigger element (the widget in the main document that opened the portal)
- Enrich captured action records with `portal_class`, `trigger_selector`, `target_text`
- Emit `primeng_dropdown` actions from the autorecord serializer when portal fields are present
- Extend the Playwright trace parser (`hitl_trace_parser`) to encode portal actions in ActionRecipe YAML
- Zero regression on non-portal click capture
- All four persistence sinks receive portal-aware data
- Do NOT modify the `primeng_dropdown` executor handler (out of scope)

### Success Criteria
- [x] AC-VERIFY-1: All 8 known PrimeNG portal container classes covered by detection logic
- [x] AC-VERIFY-2: Trigger resolution grounded in live DOM (aria-owns/aria-controls, focus WeakMap, mutation history)
- [x] AC-VERIFY-3: ActionRecipe YAML from `hitl_trace_parser` correctly encodes portal actions with `container_selector`
- [x] AC-VERIFY-4: Portal click captured as logical two-phase action with `portal_class` + `trigger_selector` + `target_text`
- [x] AC-VERIFY-5: Non-portal clicks produce byte-identical records — no regression
- [x] AC-INTEGRATION-1: Learned workflow directly replayable — serializer output shape matches existing `primeng_dropdown` handler contract
- [x] AC-ERROR-1: Unresolvable trigger emits WARN log and persists partial record with `trigger_selector: ""`; no exception
- [x] AC-ERROR-2: Anonymous portal containers fall through `cdk-overlay-container` path with WARN log
- [x] AC-ASYNC-1: Portal-aware JS is re-injected on `framenavigated` — sub-install idempotency flags prevent duplicate observers

## Implementation

### Approach

Two-phase implementation across two build sessions on 2026-07-29:

**Phase 1 (Portal Detection Layer)** — Extended the injected JS listener in `human_takeover.py` with seven additions (ADDITIONS 1–7) implementing layered portal detection, trigger resolution, target-text extraction, and `capture_confidence` derivation. Added a pure-function Python serializer helper `_maybe_portal_serialize` in `autorecord.py` that dispatches on `capture_confidence` to emit one of three shapes: `primeng_dropdown` (full), scoped `click` with `container_selector` (partial), or byte-identical passthrough (none).

**Phase 2 (Trace Parser Encoding)** — Extended `hitl_trace_parser._extract_selector_from_params()` to return a 3-tuple including `container_selector`; extended `_actions_to_recipe_steps()` to emit `container_selector` on portal-matched steps. Uses regex `_PORTAL_CLASS_PATTERN` for vendor-prefixed portal classes (`.p-*-panel`, `.po-*-panel`, etc.) plus `_PORTAL_EXACT_CLASSES` set for exact matches like `sort-panel`.

### Key Components

1. **JS Portal Detection Layer (ADDITIONS 1-7)**
   - Purpose: Detect portal-mounted clicks and resolve triggers in-browser
   - Files: `backend/engine/human_takeover.py` (JS literal within `_inject_click_capture_listener`)
   - Elements:
     - `PORTAL_ALLOWLIST` — 8 class names (`p-select-overlay`, `p-dropdown-panel`, `p-autocomplete-panel`, `p-tieredmenu`, `p-menu`, `p-popover`, `po-sorting-dropdown-panel`, `sort-panel`)
     - `detectPortal(target)` — layered `.closest()` allowlist + `cdk-overlay-container` fallback
     - `resolveTrigger(portalEl)` — layered cascade: aria-owns/aria-controls → focus WeakMap → MutationObserver focus history → confidence-marked partial
     - `extractTargetText(target)` — visible text extraction with `portal_only_degraded` sub-mode for icon-only options
     - `deriveCaptureConfidence(...)` (ADDITION 7) — rolls up granular signals into `full` / `portal_only` / `none` enum for Python consumption
     - Sub-install idempotency flags (`__vqa_portal_observer_installed__`, `__vqa_focus_tracker_installed__`) for re-injection safety

2. **Python Autorecord Serializer Extension**
   - Purpose: Dispatch on `capture_confidence` and emit shape-appropriate action records
   - Files: `backend/engine/autorecord.py` (`_maybe_portal_serialize` helper)
   - Branches:
     - `full` → `primeng_dropdown` with `trigger_selector`, `target_text`, `portal_class`
     - `portal_only` → scoped `click` with `container_selector` (Option A from architecture doc)
     - `none` → byte-identical passthrough (zero-regression contract)
   - `_normalize_portal_class` guard prepends `.` if absent

3. **Playwright Trace Parser Portal Encoding**
   - Purpose: Encode portal actions in ActionRecipe YAML from trace-only capture (T2-b path)
   - Files: `backend/engine/hitl_trace_parser.py`
   - Elements:
     - `_PORTAL_CLASS_PATTERN` regex — matches `.p-*-panel`, `.po-*-panel`, `.p-*-overlay`, `.p-*-menu`, `.p-*-dialog`
     - `_PORTAL_EXACT_CLASSES` set — exact-match fallback for `sort-panel` and other non-prefixed classes
     - `_detect_portal_container(selector)` — returns portal class if match, else None
     - `_extract_selector_from_params()` — now returns `(selector, container_selector, is_portal)` 3-tuple
     - `_actions_to_recipe_steps()` — emits `container_selector` on `RecipeStep` when portal detected

4. **Persistence Sinks (verified, no schema changes)**
   - `knowledge/blueprints/learned_workflows.json` — receives enriched records via `_save_to_learned_workflows`
   - `knowledge/human_guidance.md` — receives KB workflow block via `_save_combined_hitl_entry`
   - `knowledge/blueprints/generated/<slug>.yaml` — ActionRecipe with `container_selector` field (existed on `RecipeStep`; no schema change)
   - `knowledge/selector_registry.json` — receives HITL selector entry with portal-aware `context` grammar

### Design Decisions

Summarized from the two creative docs (see References):

1. **Q1-D: Layered `.closest()` allowlist + CDK fallback** (algorithm doc) — Deterministic allowlist for the 90% case (vendor-prefixed classes vSuite actually uses), `cdk-overlay-container` fallback for anonymous portals. Rejected pure DOM-position heuristic (Q1-C) because vSuite's Angular CDK inserts a wrapper container that makes positional detection structurally wrong.

2. **Q2-D: Layered aria → focus → mutation trigger resolution** (algorithm doc) — Three orthogonal signals in cascade. PrimeNG v19's ARIA attributes are not universal across component types (`.p-tieredmenu` and custom vSuite panels lack `aria-controls`), so the focus WeakMap and MutationObserver layers provide coverage the semantic layer cannot.

3. **Q3: Option A — scoped `click` with `container_selector` for partial captures** (architecture doc) — Rejected Option C (emit `primeng_dropdown` with empty `trigger_selector`) because `RecipeStep.action` is a Pydantic Literal that excludes `primeng_dropdown` at the YAML sink. Any uniform-shape approach would have required a Pydantic schema change and touched the executor (out of scope). Existing `RecipeStep.container_selector` was literally designed for this use case.

4. **ADDITION 7 — JS derives `capture_confidence`** (algorithm doc, added at design review) — Resolves an interface contract drift between the two parallel creative docs. Algorithm doc emitted granular `trigger_resolution_confidence` + `is_anonymous_portal`; architecture doc's serializer branched on rolled-up `capture_confidence`. Chose to derive in JS at emit time so the Python serializer becomes a pure dispatch over an enum rather than a re-classifier. Granular fields retained as telemetry.

5. **Phase 2 detection: pattern-based, not payload-based** — The trace parser has no access to JS-captured records (it reads the Playwright trace zip). Pattern-matching CSS selectors against vendor-prefix regex plus exact-class set is self-contained and avoids cross-component coupling.

References:
- `memory-bank/creative/hitl-portal-aware-click-capture-algorithm.md`
- `memory-bank/creative/hitl-portal-aware-click-capture-architecture.md`

## Testing

- Phase 1 tests: 38 (in `tests/engine/test_hitl_portal_capture.py` + extensions to `tests/test_autorecord_serialization.py`)
- Phase 2 tests: 48 (in `tests/engine/test_hitl_portal_trace_parser.py`)
- Total: 86 tests, all passing
- Pre-existing failure baseline: 72 (confirmed unchanged before/after via stash-check protocol)
- Integration coverage: Phase 2 tests include an in-memory trace zip construction that exercises the full `parse_trace()` path rather than only internal helpers
- Regression coverage: explicit non-portal serializer tests confirm byte-identical output when `capture_confidence == "none"`

All tests passing: ✓
Commit guard: C2 PASS at Phase 1 completion (prod=2 test=2); zero re-invocations across both phases.

## Files Changed

### Production
- `backend/engine/human_takeover.py` — JS ADDITIONS 1–7 (portal detection, trigger resolution, target text extraction, capture_confidence derivation, sub-install idempotency flags, cleanup closure extension)
- `backend/engine/autorecord.py` — `_maybe_portal_serialize` helper; three-branch dispatch on `capture_confidence`; `_normalize_portal_class` guard
- `backend/engine/hitl_trace_parser.py` — `_PORTAL_CLASS_PATTERN` regex, `_PORTAL_EXACT_CLASSES` set, `_detect_portal_container` helper, 3-tuple return from `_extract_selector_from_params`, `container_selector` emission in `_actions_to_recipe_steps`

### Tests (new)
- `tests/engine/test_hitl_portal_capture.py` — Phase 1 JS detection + serializer tests
- `tests/engine/test_hitl_portal_trace_parser.py` — Phase 2 trace parser tests (48 tests, includes in-memory zip integration)

### Tests (extended)
- `tests/test_autorecord_serialization.py` — portal pass-through + regression tests

### Documentation
- `memory-bank/tasks/hitl-portal-aware-click-capture.md` — full plan + execution state
- `memory-bank/creative/hitl-portal-aware-click-capture-algorithm.md` — Q1/Q2 decisions + ADDITIONS 1–7 pseudocode + ADDITION 7 reconciliation
- `memory-bank/creative/hitl-portal-aware-click-capture-architecture.md` — Q3 decision + four-sink data-flow contract + Option A rationale
- `memory-bank/reflection/hitl-portal-aware-click-capture-reflection.md` — task reflection

## Implementation Timeline (git log)

- **2026-07-28** — Roadmap feature created (Level 3, priority: high). Task auto-provisioned; feature branch cut off origin/main; spec authored (9 ACs).
- **2026-07-29** `98d7689` — Creative phase committed (algorithm + architecture docs + ADDITION 7 reconciliation at design review).
- **2026-07-29** `be99d0e` — Phase 1 committed (JS ADDITIONS 1–7 in `human_takeover.py` + `_maybe_portal_serialize` in `autorecord.py` + 38 tests).
- **2026-07-29** `fe07872` — Phase 2 committed (`hitl_trace_parser.py` portal detection + `container_selector` recipe emission + 48 tests).
- **2026-07-29** `f59bcf8` — Reflection committed.

## Lessons Learned

Three extractable learnings promoted into `_learned/` topic files:

1. **parallel-creative-contract** (`workflow-compliance.md`) — When two parallel creative sub-agents own adjacent payload surfaces (JS emits, Python consumes), require each doc to include a canonical "Payload Fields" table and diff the two tables in the design-review pass before marking creative complete. The `capture_confidence` vs `trigger_resolution_confidence` drift was caught but only at a manual reconciliation step; a systemic diff would have surfaced it earlier.

2. **portal-detection-pattern** (`browser-patterns.md`) — For PrimeNG portal detection in Playwright-injected JS, use a layered `.closest()` allowlist (vendor-prefixed class names) as primary with `cdk-overlay-container` as fallback; reject DOM-position heuristics (direct body-child detection) because Angular CDK inserts a wrapper container that makes positional detection one level too coarse.

3. **pydantic-literal-action-constraint** (`data-validation.md`) — Before designing a serializer output shape, verify whether the downstream Pydantic model's action field is a `Literal` type; if so, any new action name requires a schema change and must be treated as out-of-scope unless the task explicitly includes it — use `container_selector` on an existing Literal-compatible action type as the escape hatch.

Additional non-extracted findings:
- Two `.closest()` calls per click adds ~0.08ms overhead (well within 1ms budget); accepted trade-off for correctness.
- Code review value validated: caught dead `_PORTAL_CLASS_RE` regex (superseded by `_detect_portal_container`), normalized `Optional[str]` → `str | None`, added `_PORTAL_EXACT_CLASSES` for `sort-panel` (would have failed regex-only matching).
- Out-of-scope boundary held: `executor.py:2160` untouched; identified early in architecture doc.

Reference: `memory-bank/reflection/hitl-portal-aware-click-capture-reflection.md`

## References

- Reflection: `memory-bank/reflection/hitl-portal-aware-click-capture-reflection.md`
- Creative (algorithm): `memory-bank/creative/hitl-portal-aware-click-capture-algorithm.md`
- Creative (architecture): `memory-bank/creative/hitl-portal-aware-click-capture-architecture.md`
- Task file: `memory-bank/tasks/hitl-portal-aware-click-capture.md`
- Roadmap: `memory-bank/roadmap/hitl-portal-aware-click-capture.md`
- Out-of-scope contract: `backend/engine/executor.py:2160` (`primeng_dropdown` handler, verified untouched)

## Follow-up

- **Phase 3 E2E replay test not implemented** — The architecture doc's validation checklist has one unchecked item: an E2E replay test exercising the full `portal_only → learned_workflows → planner → executor` cycle, particularly for the `portal_only_degraded` icon-only fallback path. Was noted as "Phase 3 build task" but no Phase 3 was planned for this task. Recommended follow-up.
- **`sort-panel` test coverage in JS layer** — Phase 2 added `_PORTAL_EXACT_CLASSES` for `sort-panel` in the parser, but the corresponding Phase 1 JS `PORTAL_ALLOWLIST` test coverage for `sort-panel` is indirect (covered by the 8-class allowlist literal). A dedicated test case would harden this.
- **Hover-triggered portal timing edge case** — `p-tieredmenu` sub-menus opened on `mouseenter` may open portals after the 2000ms MutationObserver focus TTL has elapsed since the last `mousedown`. Algorithm doc acknowledges this with a 500ms `mousedown` TTL mitigation, but no test exists for hover-triggered portal trigger resolution under real timing conditions.
- **Banyan workflow: pre-TDD interface contract check step** — When creative phases produce two parallel docs with cross-doc payload surfaces, add a "contract lint" step to compare producer/consumer field tables before dispatching TDD. This was the notable ecosystem-level finding from this task.
- **Banyan workflow: by-task log symlink automation** — The by-task log directory for this task was absent, making reflection Build Session Analysis qualitative. Automating symlink creation at plan or first-build invocation would make every reflection fully evidenced.
