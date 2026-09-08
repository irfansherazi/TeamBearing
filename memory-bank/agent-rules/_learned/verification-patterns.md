---
name: Deferred Verification Patterns
globs: ["backend/engine/*.py"]
paths: ["backend/engine/"]
topics: ["verification", "transient-states", "reliability", "loops"]
priority: high
auto_generated: true
evidence_count: 5
last_reinforced: 2026-07-28
source_tasks: ["TASK-005", "TASK-013", "TASK-077", "TASK-106", "vqa-tier2-planner-memory-hardening"]
derived_from: ["vqa-tier2-planner-memory-hardening"]
last_validated: 2026-07-28
---


# Deferred Verification Patterns

Use deferred "soft assertions" for UI states that are transient or visually ambiguous, avoiding brittle auto-satisfy bypasses.

- **Transient State Handling**: When an element (e.g., a menu or toast) closes too fast for the verifier, enqueue it in a `deferred_verification_queue` rather than auto-satisfying.
- **Look-ahead Verification**: If a deferred re-check fails, attempt to verify the *consequence* of the action (the next step's success) before triggering a backtrack.
- **Backtrack Integrity**: When backtracking due to a deferred failure, preserve the `retry_count` to maintain the original failure budget for that step.
- **Standalone Verify Helpers**: Extract verification logic into standalone async functions (e.g., `verify_action`) that accept a minimal state dict + page object instead of full VQAState. This enables unit testing without LangGraph bootstrapping.
- **Goal Satisfiability Check**: For AC steps where the action succeeds but verification consistently fails (NOT_YET), implement a "progress check". If the DOM state remains unchanged over 3 attempts, emit a `SKIPPED` verdict to break infinite retry loops caused by untestable/vague AC.
- **Framework Settle Time**: For modern SPA frameworks (Angular, PrimeNG), introduce a explicit `post_action_wait_ms` buffer. This accounts for asynchronous re-renders that occur after the Playwright action resolves but before the DOM settles into its final verifiable state.
- **evaluator-to-verifier-success-gating**: Never invoke the verifier node if the executor has not reported mechanical success. Verifiers are prone to confirmation bias; gating prevents "optimistic hallucinations."
- **human-correction-feedback-signal**: Treat human "False Positive" flags as the highest-priority grounding signal. Inject the correction directly into the next planner iteration's context to prevent repeat hallucinations.
- **AsyncMock Guard**: When testing async code that may be run with real or mocked Playwright pages, use `inspect.isawaitable()` on locator return values. `page.get_by_text()` is sync in real Playwright but returns a coroutine under `AsyncMock`.
- **predictive-verification-fast-fail**: Intercept action completion with a lightweight DOM/URL checklist matching the planner's state expectation, raising a `PredictiveVerificationError` immediately on mismatch. This short-circuits execution straight to the self-healing recovery route, bypassing standard 30-second Playwright timeouts and drastically accelerating feedback loops.
- **multi-signal-stagnant-ui-detection**: Compute state deltas before and after actions using a combination of 4 independent telemetry signals (URL, element count, ARIA tree snapshot hash, and overlay marker boundaries) via a shared utility (`ui_delta.py`). This filters out cosmetic animations, loading spinners, and modal blinks, reducing false-positive stagnant UI alerts by over 90%.
- **dom-first-vision-fallback-cascade** (`backend/engine/verifier.py`, `backend/engine/test_verifier_split.py`): When splitting a monolithic LLM verifier, introduce a `DomVerifier → VisionVerifier` cascade with a structured `StateExpectation` tagged union as input and a `verifier_path` telemetry field ("dom_only" | "dom_inconclusive_vision_ran" | "vision_only") in the output. A default probe set (url_delta, element_count, aria_expanded, dialog_open, toast_visible) should resolve >= 60% of transitions without any LLM call — vision runs only when DOM is INCONCLUSIVE. Pin probe fixtures (`verifier_transitions.jsonl`, `verifier_false_not_yet.jsonl`) so latency and false-NOT_YET regressions are CI-gateable. Use a closed taxonomy of check kinds (require ADR to add new kinds).
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x
