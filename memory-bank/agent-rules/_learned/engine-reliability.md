---
derived_from: [vqa-tier1-executor-recovery]
evidence_count: 2
last_validated: 2026-07-28
---
# Engine Reliability Patterns

## Stagnation Detection

### stagnation-detection-dual-signal
- **Context**: Autonomous agents often get stuck in "amnesic loops" where they repeat the same action (e.g., scrolling, waiting) because they don't recognize that the UI state isn't changing.
- **Rule**: Combine URL and DOM element count (or other structural hashes) to detect stagnation.
- **Threshold**: 3 consecutive successful actions with zero semantic progress should trigger a circuit breaker.
- **Reset**: Always reset the stagnation counter when `ac_step_index` advances or any semantic change is detected.
- **Action**: Escalate to Human-in-the-Loop (HITL) or dispatch a "Detour Strategy" (e.g., hard refresh, navigate to start URL).

- **multi-signal-delta-check**: Replace single-signal (DOM only) stagnation checks with a composite check of URL, element count, DOM snapshot, and visual delta (via `cv_fallback_state_change_check`). This prevents false "stagnant" flags on subtle UI transitions.
  - _Source_: reflection-TASK-084 (2026-06-01)
  - _Reinforced_: 0x

- **ui-delta-verification-signal**: Use a triple-signal delta (URL, Element Count, ARIA hash) to detect stagnant UI. If no delta is detected post-action, the verifier should default to `NOT_YET` regardless of visual similarity, preventing "already satisfied" hallucinations.
  - _Source_: reflection-TASK-083 (2026-06-01)
  - _Reinforced_: 0x

## DOM Culling & Accessibility Tree Integrity

### overlay-preservation-culling
- **Context**: Aggressive DOM culling in complex SPAs (PrimeNG, Material) can accidentally hide active overlays (modals, dropdowns) that are marked with generic utility classes like `.p-hidden` even when they are semantically visible.
- **Rule**: DOM culling scripts MUST have explicit "active" guards for portal/overlay components (e.g., `.p-connected-overlay-visible`). Never hide a portal node that contains visible interaction state.
  - _Source_: reflection-TASK-084 (2026-06-01)
  - _Reinforced_: 0x

## CV Fallback Verification

### visual-delta-fallback-verification
- **Context**: Coordinate-based interactions (CV fallback) on Canvas, Shadow DOM, or complex SPAs often result in a "DOM-stable" state even if the interaction was successful (e.g., clicking a button on a canvas).
- **Rule**: Use pixel-level screenshot comparison (e.g., PIL `ImageChops.difference`) as the ground truth for success.
- **Threshold**: A 0.5% pixel change ratio is typically sufficient to distinguish meaningful UI updates from JPEG noise and anti-aliasing.
- **Implementation**: Capture a "pre-action" screenshot immediately before the coordinate click and compare it to a "post-action" screenshot.

## State Serialization & Persistence

### serialized-collection-normalization
- **Context**: LangGraph and persistence layers often serialize state structures to standard JSON, transforming rich collections (such as Python `set` objects) into basic arrays/lists when deserialized or re-loaded.
- **Rule**: When using collections (like `set[str]`) inside serializable state schemas, always implement runtime normalization helpers at entry and usage gates. Deserialization across storage boundaries may load sets as lists or strings, requiring safe coercion (`set(raw_list)`) and fallback seeds from legacy variables (e.g., converting legacy `recovery_attempted: bool` into a set that blocks all types).
  - _Source_: reflection-TASK-097 (2026-06-03)
  - _Reinforced_: 0x

## Active Recovery & Escalation

### fault-tolerant-element-not-found-escalation
- **Context**: In automated browser-based execution, target elements (such as the administrative impersonation search box) may be missing or un-rendered due to timing, state transitions, or SPA rendering lag. Instead of raising a fatal runtime error and halting the test run, routing to a recovery or human takeover node preserves the test execution.
- **Rule**: When critical page elements cannot be located during special graph nodes, do not raise a fatal exception immediately. Instead, fall back/escalate to a user-takeover node (`human_takeover_node`) to allow real-time manual correction, saving the run context.
  - _Source_: reflection-TASK-102 (2026-06-03)
  - _Reinforced_: 0x

### adaptive-action-limit-scaling
- **Context**: In automated browser execution, complex multi-step fields, nested SPA page navigation, or pagination checks easily exceed low action limits (e.g. 8 planner actions), triggering premature takeover circuit breakers.
- **Rule**: Raise default step execution limits (e.g., set default `max_actions` to 15, and fallback evaluator limits to 20) to prevent premature takeover triggers on complex pages, while retaining a guardrail against infinite loops. Allow step-specific plan definitions to override defaults when deeper paths are required.
  - _Source_: reflection-TASK-103 (2026-06-03)
  - _Reinforced_: 0x

## Executor Precondition Gates & Fallback Discipline

### component-aware-precondition-gate
- **Context** (`backend/engine/executor.py`): Text-target clicks (`get_by_text("Contest")`) against SPA pages with pre-rendered but hidden matches inside a closed dropdown/overlay component (`<p-select>`, `<p-dropdown>`, `<p-autocomplete>`) trigger Playwright strict-mode violations. The failure is deterministic once the LLM chooses that strategy: 41 pre-rendered options, 0 visible, `scroll_into_view` cannot help.
- **Rule**: Before dispatching a text-target click, run a precondition gate that queries a maintained table of known "closed container" selector signatures for the target framework. If the target text is inside a closed container, return an actionable error (`TARGET_INSIDE_CLOSED_CONTAINER` with the concrete `trigger_selector`) instead of allowing the click to proceed into a strict-mode stack trace. This converts a run-terminating loop into a next-step planner instruction.
- **Signature-table shape**: `List[Tuple[container_selector, trigger_selector_expr]]` — start with the framework's confirmed patterns, extend after live incident replay. Ship with a `# TODO: extend with confirmed <framework> variants` comment; the list is deliberately conservative because a false positive (flagging an open container as closed) silently blocks valid clicks.
  - _Source_: reflection-vqa-tier1-executor-recovery (2026-07-28)
  - _Reinforced_: 0x

### exception-safe-precondition-gates
- **Context** (`backend/engine/executor.py`): A precondition gate that raises on unrecognized DOM shapes blocks the main execution path — worse than the original problem it was meant to prevent.
- **Rule**: Every locator query inside a precondition gate must be wrapped in try/except (per-selector, not gate-wide). The gate can only fire on positive matches; any unexpected DOM state passes through silently to the normal click dispatch. Log the exception at DEBUG (not WARN) — these are expected on non-target pages and should not create log noise.
- **Test invariant**: assert the gate is exception-safe against an unknown DOM shape (mock the page such that every locator query raises) and confirm the click dispatch still runs. This test locks in the non-blocking property against future gate additions.
  - _Source_: reflection-vqa-tier1-executor-recovery (2026-07-28)
  - _Reinforced_: 0x

### futile-scroll-short-circuit
- **Context** (`backend/engine/executor.py:986-1040`): The 0-visible strict-mode branch's `scroll_into_view_if_needed` fallback is nearly always futile when `total_count > 5` on modern SPAs (Angular / PrimeNG pre-render options that are semantically hidden — scrolling reveals nothing). Each attempt costs ~3s × 3 retries + fallback timeout ≈ 10s per failure. This time is spent producing no signal.
- **Rule**: Short-circuit the scroll fallback when `total_count > 5` and `visible_count == 0`: return `STRICT_MODE_AMBIGUOUS` immediately with a strategy-switch hint (`container_selector` + `get_by_role='option'`). The scroll path **must be preserved** for `total_count <= 5` — small counts are potentially recoverable and the ~9-second savings only apply when scroll is genuinely futile.
- **Verification**: unit-test the mock `scroll_into_view_if_needed` and assert it is NEVER called on the short-circuit path. Time-bound the entire branch to ≤ 500ms wall-clock in the test.
  - _Source_: reflection-vqa-tier1-executor-recovery (2026-07-28)
  - _Reinforced_: 0x
