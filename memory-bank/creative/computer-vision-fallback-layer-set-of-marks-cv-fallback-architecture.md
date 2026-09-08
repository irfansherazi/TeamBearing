# computer-vision-fallback-layer-set-of-marks Architecture Design: CV Fallback Layer (Set-of-Marks)

**Created**: 2026-05-17
**Task**: computer-vision-fallback-layer-set-of-marks
**Feature**: FEAT-037
**Phase**: CREATIVE — Architecture Design
**Status**: COMPLETE

---

## Decision

**Chosen**: Option A — Executor-Side Recovery Path with `CvFallbackResolver` class

The CV fallback is implemented as a self-contained recovery module (`backend/browser/cv_resolver.py`) that is invoked inside `executor.py`'s `_dispatch_action()` **after** the standard failure-aware recovery chain and the debugger node have been exhausted but **before** `human_takeover_node` escalation. This requires zero changes to the LangGraph node graph, zero changes to the evaluator routing table, and zero changes to the planner's action format.

---

## Context: Existing Infrastructure

### What already exists (do not re-implement)

| Component | File | Relevant API |
|-----------|------|-------------|
| SoM overlay injection + screenshot | `backend/browser/vision_utils.py` | `draw_marks_and_snapshot(page) → (b64_jpeg, mark_coordinate_map)` |
| Mark summary formatter | `backend/browser/vision_utils.py` | `format_vision_mark_summary(mark_map) → str` |
| Coordinate map state | `backend/engine/state.py` L926 | `mark_coordinate_map: dict` |
| Coordinate click dispatcher | `backend/engine/executor.py` L2015–2137 | `coordinate_action` path — reads `mark_coordinate_map`, fires `page.mouse.click(x, y)` with CSS fallback |
| Evaluator circuit breaker | `backend/engine/evaluator.py` L829–857 | Fires after `locator_fail_count >= 3` → routes to `debugger` then `human_takeover` |
| Debugger gate | `backend/engine/evaluator.py` | `debugger_attempted: bool` — prevents double-debugger |

### What does NOT yet exist (must build)

1. **`CvFallbackResolver`** — the class encapsulating cost gate logic and stateless vision LLM call
2. **`cv_fallback_state_change_check()`** — post-click DOM delta verifier
3. **VQAState CV fields** — `cv_fallback_invocations`, `cv_fallback_results`
4. **Config flags** — `CV_FALLBACK_ENABLED`, `CV_FALLBACK_MIN_DOM_FAILURES`
5. **KB recipe** — `knowledge/blueprints/cv_fallback.yaml`
6. **Reporter integration** — `🎯 CV Fallback` badge in audit HTML

---

## Architecture: Decision Sequence Diagram

```
executor._dispatch_action() receives action
        │
        ▼
┌───────────────────────────────────────────────┐
│  Standard Playwright dispatch (DOM/ARIA path) │
│  click / get_by_role / get_by_text / etc.     │
└───────────────────────┬───────────────────────┘
                        │ success=True
                        ▼
                   [DONE — normal path]
                        │
                        │ success=False
                        ▼
┌───────────────────────────────────────────────┐
│  Evaluator circuit breaker                    │
│  locator_fail_count >= 3?                     │
│  → debugger_node (if not yet attempted)       │
│  → human_takeover (if debugger exhausted)     │
└───────────────────────┬───────────────────────┘
                        │ failure_type in eligible set AND
                        │ debugger_attempted=True AND
                        │ CvFallbackResolver.should_activate()=True
                        ▼
┌───────────────────────────────────────────────┐
│  CvFallbackResolver.resolve(page, desc, map)  │
│  1. draw_marks_and_snapshot(page)             │
│     → screenshot_b64, mark_coordinate_map     │
│  2. build_vision_prompt(desc, mark_map)       │
│  3. invoke vision LLM (Claude 3.5 Sonnet)    │
│  4. parse mark_id from JSON response          │
└───────────────────────┬───────────────────────┘
                        │ mark_id = None
                        ▼
              [CV_FALLBACK_RESOLUTION_FAILED]
              → human_takeover with cv context
                        │
                        │ mark_id resolved
                        ▼
┌───────────────────────────────────────────────┐
│  Coordinate execution (existing path reused)  │
│  mark_id → (x, y) from mark_coordinate_map   │
│  page.mouse.click(x, y)                       │
│  [CSS selector fallback if out-of-viewport]   │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│  cv_fallback_state_change_check(page, pre)    │
│  Wait 2s, compare:                            │
│    - page.url changed?                         │
│    - ARIA snapshot length delta?               │
│    - DOM element count delta?                  │
└───────────────────────┬───────────────────────┘
                        │ state changed
                        ▼
              [CV_CLICK_SUCCESS]
              update cv_fallback_results in state
              → executor returns success=True
                        │
                        │ no state change
                        ▼
              [CV_CLICK_FAILED]
              → human_takeover with CV_FALLBACK context
```

---

## Module Design: `CvFallbackResolver`

**File**: `backend/browser/cv_resolver.py`

```python
class CvFallbackResolver:
    """
    Executor-side CV recovery path.
    
    Responsibilities:
      - Cost gate: should_activate() enforces fail count threshold
      - Vision call: resolve() sends annotated screenshot to vision LLM
      - Cost accounting: estimate_cost() returns USD estimate per invocation
    
    Design constraints:
      - Stateless vision call: one screenshot in, one mark_id out
      - No shared context with planner's main vision session
      - Validates mark_id is within mark_coordinate_map before returning
    """
    
    def should_activate(
        self,
        state: VQAState,
        action: dict,
        *,
        enabled: bool,
        min_dom_failures: int,
    ) -> bool:
        """
        Returns True iff CV fallback should fire for this action.
        
        Cost gate logic:
          1. enabled flag must be True
          2. action_type must be 'click' or 'coordinate_action'
          3. locator_fail_count >= min_dom_failures (default: 3)
             OR (cv_fallback_eligible=True on action AND locator_fail_count >= 1)
          4. cv_fallback_invocations for this step < 1
             (prevent double vision call on same step)
        """
        ...
    
    async def resolve(
        self,
        page: Page,
        target_description: str,
        existing_mark_map: dict | None = None,
    ) -> tuple[int | None, dict, float]:
        """
        Capture annotated screenshot, call vision LLM, return mark_id.
        
        Returns: (mark_id | None, mark_coordinate_map, cost_estimate_usd)
        
        Vision prompt structure:
          system: "You are a UI element locator. Given an annotated screenshot
                   with numbered marks, identify which mark number corresponds
                   to the target element."
          user:   [annotated screenshot as base64 image_url]
                  + format_vision_mark_summary(mark_map)
                  + "Target: <target_description>"
                  + "Respond with JSON: {\"mark_id\": <integer or null>}"
        
        Validation:
          - mark_id must be int
          - mark_id must exist in mark_coordinate_map keys
          - If validation fails → return (None, mark_map, cost)
        """
        ...
    
    def estimate_cost(self) -> float:
        """
        Returns estimated USD cost per vision call.
        Claude 3.5 Sonnet vision: ~$0.003/1024px image.
        """
        return 0.003
```

---

## Invocation Point in Executor

The CV fallback activates inside `_dispatch_action()` in `executor.py`. The **precise insertion point** is immediately before the evaluator's `human_takeover` return path when `debugger_attempted=True`.

**Current flow** (L829–857 in evaluator.py):
```python
if locator_fail_count >= 3:
    if not state.get("debugger_attempted", False):
        return {"_next_node": "debugger", ...}
    else:
        return {"_next_node": "human_takeover", ...}  # ← CV intercepts HERE
```

**Corrected flow** (evaluator.py stays unchanged — CV intercept is in executor):

Actually the architecture clarifies a subtle but important point: **the evaluator's routing happens AFTER the executor returns**. The evaluator sees `success=False` and decides the next node. The CV fallback must happen **inside the executor** before it returns `success=False`.

**Revised insertion point**: In `executor.py`'s `_dispatch_action()`, inside the exception/failure handling block, after all standard retry attempts have failed and the function is about to return `{"success": False, "error": ...}`:

```python
# After all standard dispatch paths have failed...
# Before returning success=False to the evaluator:

_cv_resolver = CvFallbackResolver()
if _cv_resolver.should_activate(
    state,
    action,
    enabled=config.CV_FALLBACK_ENABLED,
    min_dom_failures=config.CV_FALLBACK_MIN_DOM_FAILURES,
):
    logger.info("CV_FALLBACK_ACTIVATED: step_idx=%d fail_count=%d", ...)
    mark_id, mark_map, cost = await _cv_resolver.resolve(
        page,
        target_description=action.get("name") or action.get("target_text", ""),
        existing_mark_map=state.get("mark_coordinate_map", {}),
    )
    if mark_id is not None:
        # Reuse existing coordinate_action path
        x, y = mark_map[str(mark_id)]["x"], mark_map[str(mark_id)]["y"]
        pre_state = await _capture_pre_click_state(page)
        await page.mouse.click(x, y)
        success = await cv_fallback_state_change_check(page, pre_state)
        _cv_result = {
            "step_idx": state.get("current_ac_index", 0),
            "mark_id": mark_id, "x": x, "y": y,
            "success": success, "cost_estimate": cost,
        }
        if success:
            logger.info("CV_FALLBACK_CLICK_SUCCESS: mark_id=%d at (%d, %d)", ...)
            return {
                "success": True,
                "cv_fallback": True,
                "cv_fallback_invocations": state.get("cv_fallback_invocations", 0) + 1,
                "cv_fallback_results": [_cv_result],
                "mark_coordinate_map": mark_map,
            }
        else:
            logger.warning("CV_FALLBACK_CLICK_FAILED: no state change detected")
            return {
                "success": False,
                "error": "CV_FALLBACK_CLICK_FAILED: coordinate click produced no detectable state change",
                "cv_fallback": True,
                "cv_fallback_invocations": state.get("cv_fallback_invocations", 0) + 1,
                "cv_fallback_results": [_cv_result],
            }
    else:
        logger.warning("CV_FALLBACK_RESOLUTION_FAILED: vision LLM returned no valid mark_id")
        return {
            "success": False,
            "error": "CV_FALLBACK_RESOLUTION_FAILED",
            "cv_fallback_attempted": True,
            "cv_fallback_invocations": state.get("cv_fallback_invocations", 0) + 1,
        }

# Normal failure return (CV not activated or not eligible)
return {"success": False, "error": error_msg}
```

---

## State Change Detection: `cv_fallback_state_change_check()`

**File**: Added to `backend/engine/verifier.py` as a standalone async function (not a node).

```python
async def cv_fallback_state_change_check(
    page: Page,
    pre_state: dict,  # {url, element_count, aria_snapshot_len}
    *,
    wait_ms: int = 2000,
) -> bool:
    """
    Detects DOM state change after a CV fallback coordinate click.
    
    Three detection signals (any one suffices):
    1. URL changed
    2. DOM element count delta (± any change in document.querySelectorAll('*').length)
    3. ARIA snapshot length delta (page.accessibility.snapshot() length ± 50 chars)
    
    Returns True if any signal fires within wait_ms.
    """
    await page.wait_for_timeout(wait_ms)
    post_url = page.url
    if post_url != pre_state["url"]:
        return True
    post_count = await page.evaluate("document.querySelectorAll('*').length")
    if abs(post_count - pre_state["element_count"]) > 0:
        return True
    try:
        post_aria = await page.accessibility.snapshot()
        post_len = len(str(post_aria or ""))
        if abs(post_len - pre_state["aria_snapshot_len"]) > 50:
            return True
    except Exception:
        pass  # ARIA snapshot failure is non-fatal
    return False
```

**Pre-click state capture** helper (in executor.py):
```python
async def _capture_pre_click_state(page: Page) -> dict:
    return {
        "url": page.url,
        "element_count": await page.evaluate("document.querySelectorAll('*').length"),
        "aria_snapshot_len": len(str(await page.accessibility.snapshot() or "")),
    }
```

---

## Vision Prompt Design

The vision LLM call is **stateless and minimally scoped** — no conversation history, no planner context. It receives only:

```
System:
You are a precise UI element locator. You are given an annotated browser screenshot 
where interactive elements are numbered with red boxes. Identify which numbered mark 
corresponds to the described target element.

Respond ONLY with valid JSON: {"mark_id": <integer>} or {"mark_id": null} if not found.
Do not include any explanation.

User:
[base64 annotated screenshot as image_url]

<som_element_map>
[1] button "Save"
[2] input (no text)
[3] canvas
[4] div "Submit Form"
</som_element_map>

Target element to locate: "Submit button in the radio commercial form"

Respond with: {"mark_id": <integer or null>}
```

**Model**: Claude 3.5 Sonnet (vision) — same model already used in planner vision mode.  
**Max tokens**: 50 (JSON response only).  
**Temperature**: 0 (deterministic).

---

## VQAState Schema Additions

```python
# In backend/engine/state.py — added to VQAState TypedDict

# ── CV Fallback Tracking ─────────────────────────────────────────────
# Rolling count of CV fallback invocations in this run.
# Used for cost reporting and the ≤5% rate gate.
cv_fallback_invocations: int  # default: 0

# Per-invocation results for the audit report.
# Each entry: {step_idx, mark_id, x, y, success, cost_estimate}
# Uses Annotated[list, operator.add] for LangGraph reducer compatibility.
cv_fallback_results: Annotated[list, operator.add]  # default: []
```

---

## Config Additions

```python
# In backend/engine/config.py

CV_FALLBACK_ENABLED: bool = Field(
    default=True,
    description="Enable executor-side CV fallback after DOM failure exhaustion."
)
CV_FALLBACK_MIN_DOM_FAILURES: int = Field(
    default=3,
    description=(
        "Minimum consecutive DOM action failures before CV fallback activates. "
        "Steps with cv_fallback_eligible=True use threshold=1."
    )
)
```

Environment variables:
- `CV_FALLBACK_ENABLED=true|false`
- `CV_FALLBACK_MIN_DOM_FAILURES=3`

---

## KB Recipe Design

**File**: `knowledge/blueprints/cv_fallback.yaml`

```yaml
name: cv_fallback
description: >
  Use for Canvas elements, Shadow DOM components, and iFrame-hosted widgets that
  have no accessible DOM locator. Declares the action as cv_fallback_eligible,
  which lowers the CV activation threshold from 3 to 1 failure, minimizing
  retry budget waste before visual resolution.
when_to_use:
  - target_element_type: canvas
  - target_element_type: shadow_dom
  - target_element_type: iframe_widget
  - error_pattern: "STRICT_MODE_VIOLATION.*0 visible"
steps:
  - action: click
    cv_fallback_eligible: true
    note: "Executor will attempt CV fallback after 1 DOM failure instead of 3."
```

**Planner integration**: The planner retrieves this recipe via the existing KB lookup. When emitting an action for a Canvas/ShadowDOM element, the recipe instructs the planner to include `"cv_fallback_eligible": true` in the action JSON. The executor reads this flag in `CvFallbackResolver.should_activate()` to lower the threshold from `CV_FALLBACK_MIN_DOM_FAILURES` to 1.

---

## Audit Report Integration

**Reporter changes** (`backend/engine/reporter.py`):

1. **Per-step badge**: In the HTML step row generation, if `step.get("cv_fallback")` is truthy, prepend a `🎯 CV Fallback` badge to the step title. Include `mark_id` and `(x,y)` in the step detail.

2. **Run-level summary**: In the report footer, add a `CV Fallback Summary` section:
   ```
   🎯 CV Fallback Summary
   ─────────────────────
   Invocations: 2
   Successes:   1 (50%)
   Failures:    1
   Est. Cost:   $0.006
   ```

---

## Risk Mitigations

| Risk | Mitigation | Implementation |
|------|-----------|----------------|
| Vision LLM hallucinates out-of-range mark_id | Validate `mark_id in mark_coordinate_map` before click | `CvFallbackResolver.resolve()` validation step |
| CV fires on every step (cost runaway) | `cv_fallback_invocations` per-step gate + `CV_FALLBACK_ENABLED` flag | `should_activate()` check #4 |
| Double vision call on same step | `cv_fallback_invocations` checked per step, not per run | `should_activate()` reads `cv_fallback_results` to check if step already attempted |
| Canvas element center wrong | `vision_utils.py` uses `getBoundingClientRect()` (accurate for Canvas) | Already implemented; no change needed |
| Shadow DOM element missing from SoM overlay | Document as known limitation; SoM pierces `[role=button]` generics but not arbitrary web-component internals | Noted in `cv_fallback.yaml` recipe + KB doc |
| Playwright `page.accessibility.snapshot()` fails in post-click check | Non-fatal `try/except` in `cv_fallback_state_change_check()` | Implementation detail in Phase 3 |

---

## Phase-to-File Mapping (Implementation Traceability)

| Phase | New/Modified Files | Key Interface |
|-------|--------------------|---------------|
| Phase 1 | `config.py`, `state.py`, `cv_resolver.py` (skeleton), `tests/test_cv_fallback_cost_gate.py` | `CvFallbackResolver.should_activate()` |
| Phase 2 | `cv_resolver.py` (resolve impl), `executor.py` (integration), `tests/test_cv_fallback_resolver.py` | `CvFallbackResolver.resolve()`, executor wiring |
| Phase 3 | `verifier.py` (state change check), `executor.py` (post-click check), `tests/test_cv_fallback_verifier.py` | `cv_fallback_state_change_check()` |
| Phase 4 | `cv_fallback.yaml`, `reporter.py`, `tests/test_cv_fallback_reporter.py` | KB recipe, HTML badge |

---

## Architecture Alternatives Considered

### Option B: New LangGraph Node (`cv_fallback_node`)
- **Rejected**: Requires LangGraph node graph changes + routing table updates. Given fix-graphrecursionerror-recursion-limit-too-low-for-node-vis's `GraphRecursionError` history (fixed by raising `recursion_limit` to 3000), adding nodes increases graph complexity and recursion risk. The executor-side approach achieves the same result with zero graph changes.

### Option C: Planner-Side Vision Mode Extension
- **Rejected**: Adding a second vision call to the planner loop doubles per-iteration LLM cost. The planner already invokes Claude Sonnet for its reasoning — a fallback that also uses the same model for element resolution would compound cost unpredictably. The executor-side approach is stateless and gated.

### Option D: Evaluator Pre-Route to CV Node
- **Considered**: Evaluator could check CV eligibility and route to a new `cv_fallback_evaluator` sub-path before escalating to human_takeover.
- **Rejected**: Requires evaluator changes and adds a new routing target. The executor approach is cleaner — it's a transparent recovery inside a single `_dispatch_action()` call, invisible to the evaluator's routing logic.

---

## Cross-Cutting: Observability Checklist

All log events use structured fields (no f-string interpolation in production log calls where possible):

| Event Key | Log Level | Fields |
|-----------|-----------|--------|
| `CV_FALLBACK_ACTIVATED` | INFO | `step_idx`, `fail_count`, `threshold`, `reason` |
| `CV_FALLBACK_VISION_CALL` | INFO | `run_id`, `mark_id`, `cost_estimate`, `latency_ms` |
| `CV_FALLBACK_CLICK` | INFO | `mark_id`, `x`, `y`, `success` |
| `CV_FALLBACK_STATE_CHANGE` | DEBUG | `signal` (url\|aria\|element_count), `delta` |
| `CV_FALLBACK_CLICK_SUCCESS` | INFO | `mark_id`, `x`, `y` |
| `CV_FALLBACK_CLICK_FAILED` | WARNING | `mark_id`, `x`, `y`, `reason` |
| `CV_FALLBACK_RESOLUTION_FAILED` | WARNING | `reason` (null_mark_id\|out_of_map\|llm_error) |

All events also include `run_id` via the existing logger context.

---

## Final Decision Summary

| Dimension | Decision |
|-----------|----------|
| **Invocation layer** | Executor-side (`_dispatch_action()`) |
| **Activation trigger** | Post-debugger exhaustion, pre-human_takeover escalation |
| **Threshold** | `locator_fail_count >= 3` (or `1` if `cv_fallback_eligible=True`) |
| **Vision model** | Claude 3.5 Sonnet (vision), stateless, 0-temperature |
| **Success signal** | Any of: URL change, element count delta, ARIA diff > 50 chars |
| **Failure path** | HITL with `CV_FALLBACK_RESOLUTION_FAILED` context |
| **Cost gate** | `CV_FALLBACK_ENABLED` flag + `CV_FALLBACK_MIN_DOM_FAILURES` + per-step invocation guard |
| **Graph impact** | Zero — no new LangGraph nodes, no routing changes |
| **State additions** | `cv_fallback_invocations: int`, `cv_fallback_results: list` |
| **Test strategy** | 4 unit test files (one per phase), all mocked (no live browser/LLM) |
