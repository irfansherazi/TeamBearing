"""
vQA — Evaluator Node
======================
Module: backend/engine/evaluator.py

Implements the **JUDGE** phase of the see-think-act loop.

After the executor dispatches an action, the evaluator inspects the
result and decides what happens next.  This is the branching logic
that drives the graph's conditional edges.

Decision Matrix
---------------
The evaluator returns a ``next_node`` string that the graph's
conditional edge function reads to route execution:

    ┌───────────────────────────────────────┬─────────────────┐
    │ Condition                             │ Routes To       │
    ├───────────────────────────────────────┼─────────────────┤
    │ Action failed, failure #1             │ "planner"       │
    │ Action failed, failure #2+            │ "human_takeover"│
    │ Action failed, failure #10+           │ "reporter"      │
    │ Action="done" (AC step satisfied)     │ (see below)     │
    │   → more AC steps remain             │ "planner"       │
    │   → all AC steps done, more roles    │ "setup_role"    │
    │   → all AC steps done, no more roles │ "reporter"      │
    │ Action succeeded, AC step ongoing     │ "verifier"      │
    │ Max planner iterations reached        │ "reporter"      │
    └───────────────────────────────────────┴─────────────────┘

RBAC Validation
---------------
When an action succeeds, the evaluator also performs RBAC checks
against the role's permission matrix.  If the agent encounters a UI
element the role should NOT have access to, an RBAC violation is
logged in ``bug_log``.

Self-Healing
------------
On failure, the evaluator increments ``retry_count`` and writes a
critique to ``agent_critique``.  The planner reads both fields on the
next pass and attempts a different locator strategy.

Architecture Context
--------------------
This is the most important routing node in the graph.  It is the
ONLY node that decides whether execution continues, retries, or
terminates.  The ``route_after_evaluator`` function is used as the
conditional edge function in ``graph.py``.

CRITICAL: Every branch in evaluator_node MUST return explicitly.
There must be NO fall-through from the failure branch to the success
branch. Failed actions must NEVER reach the "routing to verifier"
path.
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Literal

from backend.config import settings
from backend.engine.cb_telemetry import emit_cb_telemetry
from backend.engine.metrics import get_run_metrics
from backend.engine.state import ExecutionStep, VQAState

logger = logging.getLogger(__name__)

# Lazy import of KB singleton to avoid circular import at module level.
# The KB is a process-level singleton — importing it here is safe once the
# module is loaded.  We use a try/except so evaluator tests can run without
# a full KB on disk.
try:
    from backend.kb.loader import kb as _kb
except Exception:  # pragma: no cover
    _kb = None  # type: ignore

try:
    from backend.memory.skill_library import skill_library as _skill_library
except Exception:  # pragma: no cover
    _skill_library = None  # type: ignore

try:
    from backend.kb.selector_registry import selector_registry as _selector_registry
except Exception:  # pragma: no cover
    _selector_registry = None  # type: ignore


# ---------------------------------------------------------------------------
# Deferred Verification Queue (DVQ) Helpers — FEAT-023
# ---------------------------------------------------------------------------


def _process_deferred_queue(
    dvq: list[dict],
    current_step_index: int,
) -> tuple[list[dict], list[dict]]:
    """
    Partition the deferred verification queue into ripe and remaining entries.

    An entry is "ripe" when ``check_after_step <= current_step_index``.

    Args
    ----
    dvq : list[dict]
        Current deferred_verification_queue from VQAState.
    current_step_index : int
        The AC step index the evaluator is about to advance TO.

    Returns
    -------
    tuple[list[dict], list[dict]]
        ``(ripe_entries, remaining_entries)``
    """
    ripe: list[dict] = []
    remaining: list[dict] = []
    for entry in dvq:
        if entry.get("check_after_step", float("inf")) <= current_step_index:
            ripe.append(entry)
        else:
            remaining.append(entry)
    return ripe, remaining


# ---------------------------------------------------------------------------
# Failure Diary Helpers
# ---------------------------------------------------------------------------


def _classify_error(error_msg: str) -> str:
    """
    Classify a raw Playwright error message into a terse, actionable category.

    These short labels are written into the failure diary entries and injected
    into the planner prompt, giving the LLM structured failure context rather
    than a raw 150-char exception excerpt.

    Categories
    ----------
    STRICT_MODE(N)  — locator matched multiple elements (N = count when available)
    TIMEOUT         — element not found or blocked after 15 s
    NOT_VISIBLE     — element in DOM but not visible / off-screen
    DETACHED        — element removed from DOM between locate and act
    INTERCEPTED     — overlay/modal blocked the click target
    VALIDATION      — Python pre-validation rejected the action (missing role/name)
    UNKNOWN         — anything else (first 80 chars of raw message)
    """
    e = error_msg.lower()
    if "strict mode violation" in e:
        m = re.search(r"(\d+) element", error_msg)
        count = m.group(1) if m else "multiple"
        return f"STRICT_MODE ({count} matches)"
    if "timeout" in e:
        return "TIMEOUT (element not found or still loading)"
    if "not visible" in e or "hidden" in e or "dom_hidden" in e:
        return "NOT_VISIBLE (element in DOM but not visible)"
    if "detach" in e:
        return "DETACHED (element removed from DOM after locate)"
    if "intercept" in e or "blocked" in e or "another element" in e:
        return "INTERCEPTED (overlay or modal blocking click target)"
    if "actionvalidationerror" in e or "validation_blocked" in e:
        return "VALIDATION (action rejected before Playwright call)"
    return f"UNKNOWN ({error_msg[:80]})"


def _generate_suggestion(
    error_msg: str,
    action: str,
    strategy: str,
    role: str,
    name: str,
) -> str:
    """
    Generate a targeted recovery suggestion based on the failure type.

    Written into the diary entry and injected directly under the failing
    locator in the planner prompt — gives the LLM a concrete next step
    rather than requiring it to reason from scratch.
    """
    e = error_msg.lower()
    if "strict mode violation" in e:
        # Parse the match count so we can give a concrete disambiguation hint
        m = re.search(r"(\d+) element", error_msg)
        count_str = m.group(1) if m else "multiple"
        # Suggest container-scoped selector as the primary disambiguation path
        container_example = (
            f'{{"container_selector": ".p-toolbar", "strategy": "get_by_role", '
            f'"role": "{role or "button"}", "name": "{name}"}}'
        )
        return (
            f"DISAMBIGUATION REQUIRED: '{name}' matched {count_str} elements. "
            f"Do NOT repeat the same locator. "
            f"Option A — add container_selector to scope to visible region: {container_example}. "
            f"Option B — use the vqa_id attribute from the INTERACTIVE ELEMENTS list. "
            f"Option C — chain: get_by_role('{role or 'row'}').get_by_role('{role or 'button'}', name='{name}')."
        )
    if "timeout" in e:
        if action == "click":
            return (
                f"'{name}' not found after 15 s. Check: "
                f"(1) is a spinner still present? (2) does a parent dropdown/accordion need opening? "
                f"(3) are you on the correct page?"
            )
        return f"'{name}' timed out. Wait 1500 ms and retry, or check whether a parent element must be clicked first."
    if "not visible" in e or "hidden" in e:
        return (
            f"'{name}' is in the DOM but not visible. "
            f"A parent container (accordion, tab, sidebar) may need to be opened first."
        )
    if "detach" in e:
        return (
            f"'{name}' was detached — Angular re-rendered DOM after the locate. "
            f"Add wait(500 ms) before re-attempting to let Angular stabilize."
        )
    if "intercept" in e or "another element" in e:
        return f"An overlay is blocking '{name}'. Close it first: press Escape, click outside, or click Close/Cancel."
    if "actionvalidationerror" in e:
        if "role" in e:
            return "Add 'role' field. Example: role='button'."
        if "name" in e:
            return "Add 'name' field with the element's visible text."
    return "Try a completely different locator strategy (e.g., switch from get_by_role to get_by_text)."


def _extract_aka_hint(error_msg: str) -> str | None:
    """
    Bug E fix: Extract the Playwright-suggested ``aka get_by_role(...)`` hint
    from a strict mode violation error message and return a planner CORRECTION
    directive.

    Playwright's strict mode violation messages often contain a line like:
        ``1) <a href="/campaigns">Campaigns</a> aka get_by_role("link", name="Campaigns")``
    This hint is the most precise locator recommendation Playwright can provide,
    but the evaluator previously discarded it — forcing the planner to keep
    guessing an alternative locator from scratch.

    Pattern matched (both single- and double-quoted variants):
        ``aka get_by_role(<quote>role<quote>, name=<quote>name<quote>)``

    Returns:
        A correction string like:
            ``CORRECTION: Use get_by_role('link', name='Campaigns') instead of
              get_by_text for navigation elements (Playwright recommended).``
        or ``None`` if the pattern is not found in the error message.
    """
    import re as _re

    _AKA_RE = _re.compile(
        r"""aka\s+get_by_role\(\s*['"]([\w]+)['"]\s*,\s*name\s*=\s*['"]([^'"]+)['"]\s*\)""",
        _re.IGNORECASE,
    )
    m = _AKA_RE.search(error_msg)
    if not m:
        return None
    role = m.group(1)
    name = m.group(2)
    return (
        f"CORRECTION: Use get_by_role('{role}', name='{name}') instead of "
        f"get_by_text for this element (Playwright recommends this more precise locator). "
        f'Example: {{"action": "click", "strategy": "get_by_role", '
        f'"role": "{role}", "name": "{name}"}}'
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_assigned_voicer(state: dict) -> str:
    """
    Scan action history for the talent/voicer name selected from the Add Voice
    dropdown so the human takeover message can say exactly who to log in as.

    Returns the name string (e.g. "Demo Voice Talent") or "" if not found.
    """
    log = state.get("detailed_execution_log", [])
    # Walk backwards — the most recent dropdown selection is most relevant
    for step in reversed(log):
        payload = step.get("action_payload", {}) or {}
        locator = step.get("locator_value", "") or ""
        action = step.get("action_type", "") or ""
        name = payload.get("name", "") or locator

        # The agent clicks "Demo Voice Talent" or similar from a combobox/dropdown
        if (
            action == "click"
            and name
            and any(kw in name.lower() for kw in ("voice talent", "voicer", "voice pool", "talent"))
        ):
            # Skip the pool selection (e.g. "Demo Voice Pool") — we want the person
            if "pool" not in name.lower():
                return name.strip()

    return ""


# ---------------------------------------------------------------------------
# Type alias for routing decisions
# ---------------------------------------------------------------------------

#: Valid routing targets from the evaluator
EvalRoute = Literal[
    "planner", "setup_role", "reporter", "human_takeover", "verifier", "login", "debugger", "switch_actor_mid_run",
    "persona_switch",  # TASK-063: mid-test persona auth context switch
]


# ---------------------------------------------------------------------------
# RBAC violation detection
# ---------------------------------------------------------------------------


def _check_rbac_violations(
    state: VQAState,
    latest_step: ExecutionStep,
) -> list[dict]:
    """
    Check for RBAC violations based on the current role's permissions.

    Scans the latest action for signs that the role has access to UI
    elements it should not.  Violations are logged to ``bug_log``.

    Args
    ----
    state : VQAState
        Current state with role_context.

    latest_step : ExecutionStep
        The most recent execution step to check.

    Returns
    -------
    list[dict]
        List of RBAC violation bug entries.  Empty if no violations.
        Each entry has: ``type``, ``description``, ``severity``,
        ``screenshot_url``.
    """
    violations: list[dict] = []
    permissions = state.get("role_context", {}).get("permissions", {})
    role_name = state.get("role_context", {}).get("role_name", "Unknown")

    # Skip RBAC checks if the action failed (element wasn't even found)
    if not latest_step.get("success", False):
        return violations

    # Check if an action succeeded on a UI surface the role shouldn't access
    action_name = latest_step.get("action_payload", {}).get("name") or ""

    # Example RBAC checks — these map permission flags to UI elements
    rbac_rules: list[tuple[str, str, bool]] = [
        # (UI element name pattern, permission key, expected_value)
        ("View All Spots", "view_all_spots", False),
        ("View All Drafts", "view_all_drafts", False),
        ("Upload", "upload_files", False),
        ("Edit", "line_edit", False),
    ]

    for element_pattern, perm_key, violation_when in rbac_rules:
        if perm_key in permissions:
            perm_value = permissions[perm_key]
            # If the role SHOULD NOT have access (perm is False) but
            # the agent successfully interacted with the element
            if perm_value == violation_when and element_pattern.lower() in action_name.lower():
                violation = {
                    "type": "LOGIC",
                    "description": (
                        f"RBAC violation: {role_name} successfully accessed "
                        f"'{action_name}' but permission '{perm_key}' is "
                        f"{perm_value}. Expected: element should be hidden or disabled."
                    ),
                    "severity": "HIGH",
                    "screenshot_url": latest_step.get("screenshot_url", ""),
                }
                violations.append(violation)
                logger.warning(
                    "[RBAC] %s — %s",
                    role_name,
                    violation["description"],
                )

    return violations


def _get_target_roles_for_step(state: VQAState, index: int) -> list[str]:
    """
    Retrieve the list of target ARIA roles for a given step index.
    """
    test_plan = state.get("test_plan")
    if not test_plan:
        return []
    steps = test_plan.get("steps", [])
    if index < len(steps):
        # StructuredACStep might be a dict or a model
        step = steps[index]
        if hasattr(step, "get"):
            return step.get("target_element_types", [])
        return getattr(step, "target_element_types", [])
    return []


# ---------------------------------------------------------------------------
# MVE-001: CB Telemetry helper
# ---------------------------------------------------------------------------


def _emit_cb(state: VQAState, cb_type: str, cb_reason: str) -> None:
    """Emit circuit breaker telemetry from evaluator state. Fire-and-forget."""
    try:
        run_id = state.get("run_id", "unknown")
        _started = state.get("run_started_at", 0.0)
        _elapsed = time.time() - _started if _started > 0 else 0.0

        # Read live cost from metrics registry
        _cost = 0.0
        try:
            _cost = get_run_metrics(run_id).estimated_cost_usd
        except Exception:
            pass

        emit_cb_telemetry(
            run_id=run_id,
            cb_type=cb_type,
            cb_reason=cb_reason,
            iteration_at_fire=state.get("planner_iteration", 0),
            action_at_fire=state.get("planned_action", {}).get("action", "unknown"),
            ac_step_index=state.get("ac_step_index", 0),
            wall_clock_elapsed_s=_elapsed,
            cost_usd_at_fire=_cost,
        )
    except Exception:
        pass  # Non-blocking — suppress all telemetry errors


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------

async def evaluator_node(state: VQAState) -> dict:
    """
    LangGraph node: JUDGE phase — evaluate the action result and decide routing.

    Inspects the most recent ``ExecutionStep`` in ``detailed_execution_log``
    and determines the next node to execute.

    The routing decision is written to ``state["_next_node"]`` which is
    read by the ``route_after_evaluator()`` conditional edge function.

    IMPORTANT: Every code path MUST return explicitly. There is no implicit
    fall-through. A failed action (success=False) must NEVER reach the
    "action succeeded — routing to verifier" path.
    """
    run_id: str = state["run_id"]

    # ── DR-008: Wall-Clock and Cost-USD Circuit Breakers ─────────────────
    # These must fire BEFORE any other logic to prevent budget overruns.
    _run_started = state.get("run_started_at", 0.0)
    if _run_started > 0:
        _elapsed = time.time() - _run_started
        _wall_limit = int(settings.max_run_wall_clock_seconds)

        # 80% early warning
        if _elapsed >= _wall_limit * 0.8 and _elapsed < _wall_limit:
            logger.warning(
                "[%s] WALL CLOCK WARNING: %.0f/%.0fs elapsed (80%% threshold crossed)",
                run_id, _elapsed, _wall_limit,
            )

        if _elapsed > _wall_limit:
            logger.error(
                "[%s] WALL CLOCK CIRCUIT BREAKER: %.0fs elapsed > %ds limit — terminating run",
                run_id, _elapsed, _wall_limit,
            )
            return {
                "_next_node": "reporter",
                "failure_type": "WALL_CLOCK_EXCEEDED",
                "agent_critique": (
                    f"Run exceeded wall-clock limit: {_elapsed:.0f}s elapsed vs "
                    f"{_wall_limit}s maximum. Run terminated."
                ),
            }

    # Cost check — uses the live RunMetrics registry (not serialized state)
    try:
        _metrics = get_run_metrics(run_id)
        _cost = _metrics.estimated_cost_usd
        _cost_limit = float(settings.max_run_cost_usd)

        # 80% early warning
        if _cost >= _cost_limit * 0.8 and _cost < _cost_limit:
            logger.warning(
                "[%s] COST WARNING: $%.4f/$%.2f spent (80%% threshold crossed)",
                run_id, _cost, _cost_limit,
            )

        if _cost > _cost_limit:
            logger.error(
                "[%s] COST CIRCUIT BREAKER: $%.4f > $%.2f limit — terminating run",
                run_id, _cost, _cost_limit,
            )
            return {
                "_next_node": "reporter",
                "failure_type": "COST_BUDGET_EXCEEDED",
                "agent_critique": (
                    f"Run exceeded cost limit: ${_cost:.4f} spent vs "
                    f"${_cost_limit:.2f} maximum. Run terminated."
                ),
            }
    except Exception:
        pass  # Metrics registry unavailable — skip cost check

    log: list = state.get("detailed_execution_log", [])
    ac_steps: list = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index: int = state.get("ac_step_index", 0)
    struct_index: int = state.get("structured_step_index", 0)
    current_sub_step_idx: int = state.get("current_sub_step_index", 0)
    retry_count: int = state.get("retry_count", 0)
    state.get("max_retries", 3)
    max_iterations: int = state.get("max_planner_iterations", 500)
    iteration: int = state.get("planner_iteration", 0)

    # ── Per-Step Budgeting (FEAT-021) ─────────────────────────────────
    # Prevents a single stuck AC step from consuming the entire global budget.
    step_budget = state.get("ac_step_iteration_budget", 0)
    step_iterations_used = state.get("ac_step_iterations_used", 0) + 1

    # On first action of a new step, calculate its iteration allowance
    if step_budget <= 0:
        remaining_iters = max(1, max_iterations - iteration)
        remaining_steps = max(1, len(ac_steps) - ac_index)
        fair_share = remaining_iters // remaining_steps

        # Use int() cast to handle MagicMocks in unit tests
        step_budget_limit = int(settings.per_step_budget_max)
        step_budget = min(step_budget_limit, fair_share)

        logger.info(
            "[%s] AC step %d budget initialized: %d iterations (fair share of %d remaining)",
            run_id,
            ac_index + 1,
            step_budget,
            remaining_iters,
        )

    # FIX: Initialize existing_diary here — at function scope — so it is always
    # bound regardless of which branch (success / done / verifier) is taken.
    # Without this, the PREMATURE DONE GUARD on the happy-path (success=True,
    # action='done') crashes with UnboundLocalError because existing_diary is
    # only assigned inside the `if not success:` block (Case 1).
    existing_diary: list[dict] = list(state.get("ac_step_failure_diary", []))

    # Get the latest execution step
    if not log:
        logger.error("[%s] Evaluator called with empty execution log", run_id)
        return {"_next_node": "reporter"}

    latest_step: ExecutionStep = log[-1]
    action_type: str = latest_step.get("action_type", "")
    success: bool = latest_step.get("success", False)
    planned_action: dict = state.get("planned_action", {})

    # ── Amnesic Loop Detection (FEAT-062 Pillar 1) ─────────────────
    # Detects loops where actions succeed but have no effect on page state.
    amnesic_loop_count = state.get("amnesic_loop_count", 0)
    prev_state = state.get("_prev_page_state_snapshot", {})

    current_url = latest_step.get("post_url", "")
    current_count = latest_step.get("post_element_count", 0)

    if success and prev_state and action_type not in ("wait", "screenshot", "verify"):
        if current_url == prev_state.get("url") and current_count == prev_state.get("element_count"):
            amnesic_loop_count += 1
            logger.warning(
                "[%s] AMNESIC LOOP detected (%d/3): URL and element count (%d) unchanged after '%s'",
                run_id,
                amnesic_loop_count,
                current_count,
                action_type,
            )
        else:
            amnesic_loop_count = 0
    elif not success:
        # Failure is handled by retry logic/fail budget, don't count as amnesic loop
        pass
    else:
        # First action or wait/verify — don't increment
        pass

    new_prev_snapshot = {"url": current_url, "element_count": current_count}

    def _finalize(updates: dict) -> dict:
        """Inject amnesic loop state into all return dictionaries."""
        if "amnesic_loop_count" not in updates:
            updates["amnesic_loop_count"] = amnesic_loop_count
        if "_prev_page_state_snapshot" not in updates:
            updates["_prev_page_state_snapshot"] = new_prev_snapshot
        return updates

    if amnesic_loop_count >= 3:
        logger.error(
            "[%s] AMNESIC LOOP CIRCUIT BREAKER: 3 stagnant actions — routing to human_takeover",
            run_id,
        )
        _emit_cb(state, "amnesic_loop", f"3 stagnant '{action_type}' actions with no page state change")
        return {
            "_next_node": "human_takeover",
            "awaiting_human_takeover": True,
            "agent_critique": (
                f"AMNESIC LOOP DETECTED: The last 3 actions ({action_type}) succeeded mechanically "
                f"but resulted in NO CHANGE to the URL or page structure. The agent is stuck "
                f"performing null-outcome actions. Human intervention required to break the loop."
            ),
            "amnesic_loop_count": 0,
            "_prev_page_state_snapshot": new_prev_snapshot,
        }

    logger.info(
        "[%s] Evaluating step %d: action=%s, success=%s, ac_step=%d/%d",
        run_id,
        latest_step.get("step_index", -1),
        action_type,
        success,
        ac_index + 1,
        len(ac_steps),
    )

    # ── Check verifier verdict first ──────────────────────────────────
    # If the verifier returned "failed" (e.g. NOT_YET hard cap reached),
    # treat it as a step failure regardless of the executor's success flag.
    # Without this, wait(success=True) → verifier(failed) → evaluator(success=True)
    # → verifier(failed) creates an infinite loop.
    verifier_verdict = state.get("_verifier_verdict", "")
    if verifier_verdict == "failed":
        verifier_error = state.get("last_error", "Verifier marked step as FAILED")
        verifier_critique = state.get("agent_critique", "")

        # ── FIX 1: Do NOT increment the Playwright action-failure budget here.
        # The verifier's own verifier_total_not_yet_count hard-cap (>=5) already
        # handles escalation independently.  This path burned ac_step_fail_counts
        # (the Playwright budget) for scroll/wait/verify actions that Playwright
        # executed successfully, causing premature human_takeover.
        # We now route directly to planner with a strong critique instead.
        logger.warning(
            "[%s] Verifier FAILED for AC step %d/%d — %s",
            run_id,
            ac_index + 1,
            len(ac_steps),
            verifier_error[:100],
        )

        # Route to planner with actionable critique. The verifier's own hard-cap
        # (verifier_total_not_yet_count >= 5) will escalate to evaluator →
        # human_takeover if the step cannot be satisfied after that budget.
        new_retry_count = state.get("retry_count", 0) + 1

        # Auto-escalation observability marker
        from backend.config import settings as _eval_settings

        _esc_threshold = _eval_settings.auto_escalate_threshold
        if _esc_threshold > 0 and new_retry_count == _esc_threshold:
            logger.warning(
                "[%s] Retry count %d reached escalation threshold — next planner call will use heavy model (Sonnet)",
                state.get("run_id", "?"),
                new_retry_count,
            )

        return {
            "_next_node": "planner",
            "ac_step_iteration_budget": step_budget,  # FEAT-021
            "ac_step_iterations_used": step_iterations_used,  # FEAT-021
            "_verifier_verdict": "",  # Clear to prevent re-triggering
            "retry_count": new_retry_count,
            "agent_critique": (
                f"VERIFIER REJECTION: {verifier_critique or verifier_error}. "
                f"The action Playwright executed did NOT produce the expected visual state. "
                f"This is NOT a locator failure — the click/action succeeded mechanically, "
                f"but the app did not react correctly. "
                f"You MUST try a completely DIFFERENT action — waiting/scrolling is not working. "
                f"Click a different element, navigate to a different view, or interact with "
                f"the page in a substantively different way."
            ),
            "last_error": verifier_error,
            "verifier_not_yet_count": 0,
            "verifier_total_not_yet_count": 0,
            "_force_wait_before_next_action": True,
            "_force_wait_ms": 1500,
        }

    # ── FEAT-058: Handle SKIPPED verifier verdict ─────────────────────
    if verifier_verdict == "skipped":
        # Verifier has already advanced ac_step_index in its partial state update.
        # We just need to record the skip and decide if we route to reporter.
        logger.warning(
            "[%s] Verifier SKIPPED AC step — current index is now %d/%d",
            run_id,
            ac_index,
            len(ac_steps),
        )

        # The skip actually happened at ac_index - 1
        skipped_idx = ac_index - 1
        skipped_indices = list(state.get("ac_steps_skipped", []))
        if skipped_idx not in skipped_indices:
            skipped_indices.append(skipped_idx)

        gap_bug = {
            "type": "COVERAGE_GAP",
            "description": (
                f"AC step {skipped_idx + 1} SKIPPED: Goal appears unsatisfiable "
                f"after multiple attempts. Reasoning: {state.get('last_error', 'Unsatisfiable')}"
            ),
            "severity": "MEDIUM",
            "ac_step_index": skipped_idx,
            "reason": "UNSATISFIABLE_GOAL"
        }
        existing_bugs = list(state.get("bug_log", []) or [])
        existing_bugs.append(gap_bug)

        if ac_index >= len(ac_steps):
            return {
                "_next_node": "reporter",
                "ac_steps_skipped": skipped_indices,
                "bug_log": existing_bugs,
                "_verifier_verdict": "",
            }

        return {
            "_next_node": "planner",
            "ac_step_index": ac_index,
            "structured_step_index": ac_index,
            "ac_steps_skipped": skipped_indices,
            "bug_log": existing_bugs,
            "_verifier_verdict": "",
            "retry_count": 0,
            "ac_step_fail_counts": {},
            "ac_step_action_fail_count": 0,
            "current_ac_step_action_count": 0,
            "verifier_not_yet_count": 0,
            "verifier_total_not_yet_count": 0,
        }

    # ── Recipe idempotent-skip fast path ─────────────────────────────────
    # When the executor dispatched a recipe that determined the target state was
    # already correct (e.g. compact_view_navigate found div.po-table-wrapper.compact
    # already present), it returns success=True + skipped=True AND sets
    # _recipe_already_satisfied=True in the state update.
    #
    # In this case, routing to the verifier is harmful: it calls wait_for() on a
    # page/context reference that may be stale after the no-op, returning NOT_YET
    # and causing the planner to re-dispatch the same recipe forever.
    #
    # Instead, treat this exactly like a verifier SATISFIED result — advance the
    # AC step index directly from the evaluator without touching the verifier.
    if state.get("_recipe_already_satisfied", False) and success:
        _ras_ac_index = ac_index
        _ras_new_ac_index = _ras_ac_index + 1
        logger.info(
            "[%s] Recipe idempotent-skip: AC step %d/%d auto-advanced (state was already correct, verifier bypassed).",
            run_id,
            _ras_ac_index + 1,
            len(ac_steps),
        )
        if _ras_new_ac_index >= len(ac_steps):
            return {
                "_next_node": "reporter",
                "ac_steps_completed": [_ras_ac_index],
                "_recipe_already_satisfied": False,
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "ac_step_fail_counts": {},
                "current_ac_step_action_count": 0,  # Reset total action budget
                "verifier_not_yet_count": 0,
                "verifier_total_not_yet_count": 0,
            }
        return {
            "_next_node": "planner",
            "ac_step_index": _ras_new_ac_index,
            "structured_step_index": _ras_new_ac_index,
            "current_sub_step_index": 0,
            "ac_steps_completed": [_ras_ac_index],
            "_recipe_already_satisfied": False,
            "retry_count": 0,
            "agent_critique": "",
            "last_error": "",
            "ac_step_fail_counts": {},
            "ac_step_action_fail_count": 0,
            "vision_mode_fail_count": 0,
            "_force_wait_before_next_action": False,
            "_force_wait_ms": 0,
            "current_ac_step_action_count": 0,  # Reset total action budget for new step
            "verifier_not_yet_count": 0,
            "verifier_total_not_yet_count": 0,
            "ac_step_failure_diary": [],
            "action_repeat_counts": {},
            "recovery_attempted_types": set(),  # FEAT-022: reset multi-type recovery list for new step
            "action_history_buffer": [],  # FEAT-020: clear on step advance
        }

    # ── RBAC violation check ──────────────────────────────────────────
    rbac_violations: list[dict] = _check_rbac_violations(state, latest_step)

    # ── Safety cap: max planner iterations ────────────────────────────
    if iteration >= max_iterations:
        logger.warning(
            "[%s] Max planner iterations (%d) reached — terminating run",
            run_id,
            max_iterations,
        )
        _emit_cb(state, "global_iter", f"Max planner iterations ({max_iterations}) reached")
        return {
            "_next_node": "reporter",
            "bug_log": rbac_violations,
            "agent_critique": f"Run exceeded maximum {max_iterations} planner iterations.",
        }

    # ── Per-Step Budgeting (FEAT-021) ─────────────────────────────────
    # Check if the current AC step has exhausted its allocated iterations.
    # Failing the run rather than skipping so that a broken step doesn't
    # silently let remaining steps execute against a broken app state.
    if step_iterations_used >= step_budget:
        logger.error(
            "[%s] AC step %d budget EXHAUSTED (%d/%d iters). Failing the run.",
            run_id,
            ac_index + 1,
            step_iterations_used,
            step_budget,
        )
        _emit_cb(state, "ac_level_cap", f"AC step {ac_index + 1} budget exhausted ({step_iterations_used}/{step_budget})")
        return {
            "_next_node": "reporter",
            "failure_type": "AGENT_STUCK",
            "agent_critique": (
                f"AC step {ac_index + 1} exhausted its iteration budget ({step_iterations_used}/{step_budget}) "
                f"without completing. The agent could not satisfy the step goal. Failing the run."
            ),
        }

    # ── AC-level total action circuit breaker ────────────────────────────
    # Counts ALL actions on the current AC step (success + failure).
    # Unlike ac_step_action_fail_count (which only tracks Playwright failures),
    # this catches the scenario where the agent intersperses "successful" bad
    # actions (clicking Settings, scrolling randomly) between failures —
    # resetting the consecutive failure counter and evading human_takeover.
    #
    # Use max_actions from the structured test plan step when available —
    # the AC parser sets higher limits (e.g. 20) for complex multi-field forms.
    # Fall back to 20 if no structured plan exists (FEAT-104: raised from 15).
    _ac_cap = 20  # FEAT-104: raised from 15 — matches new StructuredACStep default (15) + buffer
    _test_plan = state.get("test_plan")
    if _test_plan:
        _plan_steps = _test_plan.get("steps", [])
        if ac_index < len(_plan_steps):
            _ac_cap = _plan_steps[ac_index].get("max_actions", 20)

    ac_total_actions = state.get("current_ac_step_action_count", 0)
    # BUG FIX (TASK-071): Allow SUCCESSFUL 'done' actions to pass even if it's the 10th action.
    # Without this exemption, the agent is forced into human takeover on its finishing move.
    # We only exempt if success=True; if the 'done' action itself failed, we still circuit break.
    is_finishing_move = success and (action_type == "done" or planned_action.get("action") == "done")

    if ac_total_actions >= _ac_cap and not is_finishing_move:
        logger.error(
            "[%s] AC-LEVEL CIRCUIT BREAKER: %d/%d total actions taken on AC step %d/%d "
            "— agent is lost. Failing the run.",
            run_id,
            ac_total_actions,
            _ac_cap,
            ac_index + 1,
            len(ac_steps),
        )
        return {
            "_next_node": "reporter",
            "failure_type": "AGENT_STUCK",
            "agent_critique": (
                f"AC step {ac_index + 1} consumed {ac_total_actions}/{_ac_cap} total actions "
                f"without completing. The agent is lost. Failing the run."
            ),
            "bug_log": rbac_violations,
        }

    # ── Case 1: Action FAILED ──────────────────────────────────────────
    # CRITICAL: This block ALWAYS returns. It never falls through to Cases 2/3.
    if not success:
        # ── Fast-path #0a: ALREADY_IN_VIEW — idempotent state confirmation ──
        # When the executor's hard gate confirms we're already in the target
        # view (ALREADY_IN_COMPACT_VIEW / ALREADY_IN_LIST_VIEW), this is NOT
        # a failure — it's a confirmation that the AC step is already satisfied.
        # Auto-advance the AC step immediately instead of wasting retries.
        dom_diag = latest_step.get("dom_failure_diagnosis", "")
        if dom_diag in ("ALREADY_IN_COMPACT_VIEW", "ALREADY_IN_LIST_VIEW"):
            logger.info(
                "[%s] RECIPE_BLOCKED fast-path: '%s' confirmed — auto-advancing AC step %d/%d (view already correct)",
                run_id,
                dom_diag,
                ac_index + 1,
                len(ac_steps),
            )
            new_ac_index = ac_index + 1
            if new_ac_index >= len(ac_steps):
                return {"_next_node": "reporter", "ac_steps_completed": [ac_index]}
            return {
                "_next_node": "planner",
                "ac_step_index": new_ac_index,
                "structured_step_index": new_ac_index,
                "current_sub_step_index": 0,
  # FEAT-025
                "target_element_types": _get_target_roles_for_step(state, new_ac_index),  # FEAT-025
                "ac_steps_completed": [ac_index],
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "ac_step_fail_counts": {},
                "ac_step_action_fail_count": 0,
                "current_ac_step_action_count": 0,
                "verifier_not_yet_count": 0,
                "verifier_total_not_yet_count": 0,
                "ac_step_failure_diary": [],
                "action_repeat_counts": {},
                "action_history_buffer": [],  # FEAT-020: clear on step advance
            }

        error_msg = latest_step.get("error_message", "unknown error")

        # ── Fast-path #0: AUTH_GATE_BLOCKED — re-route to login, not planner ─
        # The executor's _check_auth_state() sets this sentinel when it detects
        # the browser is on /login without a JWT. Routing back to the planner
        # would cause an infinite block loop. Instead, route to login_node so
        # the agent re-authenticates before resuming AC steps.
        # Capped at 2 retries: if login keeps failing (wrong credentials,
        # missing account on this environment), we fail the run rather than
        # spinning up new Chromium instances until a TimeoutError kills the run.
        if "AUTH_GATE_BLOCKED" in error_msg:
            # When the blocked step IS a GHOST_LOGIN, the ghost_login_node is the
            # correct handler — routing to login_node would repeat the "navigate to
            # target URL → redirect to login page" cycle indefinitely. Route directly
            # to ghost_login instead.
            _agg_test_plan = state.get("test_plan") or {}
            _agg_plan_steps = _agg_test_plan.get("steps", [])
            _agg_is_ghost = (
                ac_index < len(_agg_plan_steps)
                and (
                    _agg_plan_steps[ac_index].get("step_type")
                    if isinstance(_agg_plan_steps[ac_index], dict)
                    else getattr(_agg_plan_steps[ac_index], "step_type", "")
                ) == "GHOST_LOGIN"
            )
            if _agg_is_ghost:
                logger.info(
                    "[%s] AUTH_GATE_BLOCKED on GHOST_LOGIN step %d — routing to ghost_login "
                    "(not login_node; credentials were never attempted)",
                    run_id,
                    ac_index + 1,
                )
                return {
                    "_next_node": "ghost_login",
                    "last_error": "",
                    "retry_count": 0,
                    "ac_step_fail_counts": {},
                    "ac_step_action_fail_count": 0,
                }

            auth_retries = state.get("auth_gate_retry_count", 0)
            if auth_retries >= 2:
                logger.error(
                    "[%s] AUTH_GATE_BLOCKED — session could not be established after %d attempt(s). "
                    "Credentials may be invalid or the account does not exist on this environment. "
                    "Failing the run.",
                    run_id,
                    auth_retries,
                )
                return {
                    "_next_node": "reporter",
                    "failure_type": "ENV_BLOCKER",
                    "agent_critique": (
                        f"Authentication blocked {auth_retries} consecutive time(s). "
                        "The session could not be established — the role's credentials may be "
                        "invalid or the account does not exist on this environment. "
                        "Cannot proceed — failing the run."
                    ),
                }
            logger.warning(
                "[%s] AUTH_GATE_BLOCKED detected (attempt %d/2) — routing to login for re-authentication "
                "(NOT back to planner — that would infinite loop)",
                run_id,
                auth_retries + 1,
            )
            return {
                "_next_node": "login",
                "auth_gate_retry_count": auth_retries + 1,
                "agent_critique": (
                    "Session expired mid-run — browser landed on the login page without a JWT. "
                    "Re-authenticating via login_node before resuming AC steps."
                ),
                "last_error": "",  # Clear so login_node doesn't see stale error
                "retry_count": 0,
                "ac_step_fail_counts": {},
                "ac_step_action_fail_count": 0,
            }

        # Resolve current AC step text (needed for KB self-heal query below)
        current_step: str = ac_steps[ac_index] if ac_index < len(ac_steps) else ""

        # Track per-locator failures (for memory / forbidden locators)
        planned = state.get("planned_action", {})
        planned_strategy = planned.get("strategy") or ""
        planned_role = planned.get("role") or ""
        planned_name = planned.get("name") or ""
        locator_key = f"{planned_strategy}:{planned_role}:{planned_name}"

        fail_counts: dict = dict(state.get("ac_step_fail_counts", {}))

        # Per-locator count (for memory / forbidden locators)
        locator_fail_count = fail_counts.get(locator_key, 0) + 1
        fail_counts[locator_key] = locator_fail_count

        # ── FIX 1: Independent Playwright-action failure budget ──────────────
        # ac_step_action_fail_count tracks ONLY success=False from Playwright.
        # It does NOT include verifier rejections (those use verifier_total_not_yet_count).
        # This decouples "agent can't find the element" from "agent found it but
        # the app's response was wrong" — two fundamentally different failure modes.
        action_fail_count = state.get("ac_step_action_fail_count", 0) + 1

        # Tracks consecutive vision-mode failures (FEAT-049 / TASK-054)
        vision_mode_fail_count = state.get("vision_mode_fail_count", 0)
        current_vision_mode = state.get("vision_mode", "dom")
        if current_vision_mode == "som_coordinates":
            vision_mode_fail_count += 1

        # Per-AC-step count — ANY failure on this AC step increments this.
        step_key = f"__step_{ac_index}__"
        step_fail_count = fail_counts.get(step_key, 0) + 1
        fail_counts[step_key] = step_fail_count

        logger.info(
            "[%s] AC step %d: locator '%s' failed %d time(s) | step total failures: %d | action_fail_count: %d",
            run_id,
            ac_index + 1,
            locator_key,
            locator_fail_count,
            step_fail_count,
            action_fail_count,
        )

        # Write to long_term_memory for patterns the planner should learn
        new_memories: list[str] = []
        if planned_strategy == "get_by_role" and planned_role == "link" and locator_fail_count == 1:
            new_memories.append(
                f"LEARNED: get_by_role(link, name='{planned_name}') DOES NOT WORK in Angular "
                f"(no ARIA link role on table rows). "
                f"Use get_by_text('{planned_name}') instead for any list/table item click."
            )

        # ── Build a failure diary entry for this attempt ───────────────────
        # The diary accumulates ALL failed locators on the current AC step.
        # The planner reads the full diary to avoid repeating known-bad approaches.
        # The evaluator overwrites the whole list (not appends via operator.add)
        # so entries cannot be duplicated across retry cycles.
        diary_entry = {
            "attempt": step_fail_count,
            "action": action_type,
            "locator": locator_key,
            "error": _classify_error(error_msg),
            "suggestion": _generate_suggestion(
                error_msg,
                action_type,
                planned_strategy,
                planned_role,
                planned_name,
            ),
        }

        # ── FEAT-031: Circuit Breaker for Sort Actions ────────────────────────
        _SORT_OPTION_NAMES = {"client", "title", "status", "ad type", "due date", "submit date", "date sort"}
        action_repeat_counts = dict(state.get("action_repeat_counts", {}))

        _sort_target = (planned_name or planned.get("target_text", "") or "").lower()
        if action_type in ("click", "coordinate_action") and _sort_target in _SORT_OPTION_NAMES:
            sort_fails = action_repeat_counts.get("sort_action_failure", 0) + 1
            action_repeat_counts["sort_action_failure"] = sort_fails

            if sort_fails >= 5:
                logger.error(
                    "[%s] CIRCUIT BREAKER: Sort action failed %d times. Escalate to human.", run_id, sort_fails
                )
                return {
                    "_next_node": "human_takeover",
                    "awaiting_human_takeover": True,
                    "agent_critique": (
                        f"CIRCUIT BREAKER: Repeated sort action failures ({sort_fails} attempts). "
                        f"The agent is stuck in an infinite loop trying to sort by '{planned_name}'. "
                        f"Human intervention required."
                    ),
                    "ac_step_fail_counts": fail_counts,
                    "last_error": error_msg,
                    "bug_log": rbac_violations,
                    "ac_step_failure_diary": existing_diary,
                    "action_repeat_counts": action_repeat_counts,
                }

        # ── Sort-panel scoping hint for Compact View STRICT_MODE ──────────────
        # If STRICT_MODE happened on a sort option name ("Client", "Title", etc.)
        # and the sort panel is likely open, inject a container_selector hint.
        if "strict mode violation" in error_msg.lower() and _sort_target in _SORT_OPTION_NAMES:
            _hint_name = planned_name or planned.get("target_text", "")
            diary_entry["suggestion"] = (
                f"SORT PANEL SCOPING REQUIRED: '{_hint_name}' matches multiple elements. "
                f"Add container_selector to scope to the sort panel: "
                f'{{"action": "click", "strategy": "get_by_text", '
                f'"name": "{_hint_name}", "container_selector": ".sort-panel"}}'
            )

        existing_diary.append(diary_entry)

        # ── FEAT-035: Limit failure diary size to prevent context bloat ──
        if len(existing_diary) > 5:
            existing_diary = existing_diary[-5:]

        # ── Content-level block for 0-visible STRICT_MODE_VIOLATION ──────────
        # When locator matched N elements but 0 are visible, the element NAME
        # or TEXT is ambiguous across the whole DOM. Blocking just this one
        # strategy:role:name triple is insufficient — the planner will try a
        # different strategy targeting the same text and hit the same wall.
        #
        # Solution: register a strategy-agnostic "__content__:{name}" key so
        # that EVERY locator targeting this text content is considered blocked.
        # The BLOCKED prompt renderer then tells the planner:
        #   ⋗ CONTENT BLOCKED: 'Demo Account Executive' has 0 visible matches
        #     → You MUST use container_selector or vqa_id to scope to a
        #       specific visible ancestor.
        if "strict mode violation" in error_msg.lower() and planned_name:
            # Extract the 0-visible count to decide if content-level block applies
            import re as _re_ev

            _vis_match = _re_ev.search(r"(\d+) visible", error_msg)
            _vis_count = int(_vis_match.group(1)) if _vis_match else 0
            if _vis_count == 0:
                content_block_key = f"__content__:{planned_name}"
                fail_counts[content_block_key] = fail_counts.get(content_block_key, 0) + 1

        # ── FEAT-035: Circuit Breaker for Repeated Locator Failures ──────────
        # If the exact same locator fails 3 times, aggressively cut it off
        # to prevent context blooming and infinite loops.
        if locator_fail_count >= 3:
            logger.warning(
                "[%s] CIRCUIT BREAKER: Locator '%s' failed %d times. Aggressively cutting off.",
                run_id,
                locator_key,
                locator_fail_count,
            )
            _emit_cb(state, "per_locator", f"Locator '{locator_key}' failed {locator_fail_count} times")
            if not state.get("debugger_attempted", False):
                return {
                    "_next_node": "debugger",
                    "agent_critique": (
                        f"CIRCUIT BREAKER: Locator '{locator_key}' has failed {locator_fail_count} times. "
                        f"The agent is stuck in an unproductive loop. Routing to Debugger."
                    ),
                    "ac_step_fail_counts": fail_counts,
                    "ac_step_action_fail_count": action_fail_count,
                    "last_error": error_msg,
                    "bug_log": rbac_violations,
                    "ac_step_failure_diary": existing_diary,
                    "action_repeat_counts": action_repeat_counts,
                }
            else:
                return {
                    "_next_node": "human_takeover",
                    "awaiting_human_takeover": True,
                    "agent_critique": (
                        f"CIRCUIT BREAKER: Locator '{locator_key}' has failed {locator_fail_count} times. "
                        f"The agent is stuck in an unproductive loop. Human intervention required."
                    ),
                    "ac_step_fail_counts": fail_counts,
                    "ac_step_action_fail_count": action_fail_count,
                    "last_error": error_msg,
                    "bug_log": rbac_violations,
                    "ac_step_failure_diary": existing_diary,
                    "action_repeat_counts": action_repeat_counts,
                }

        # ── Fast-path #1: "Invalid User" credential failure ───────────
        # The agent doesn't know this account's credentials — stop guessing
        # immediately and ask the human to log in manually.  Every extra
        # retry just wastes time trying invented email addresses.
        #
        # EXCEPTION: In failed login testing mode, "Invalid User" is the
        # EXPECTED outcome — the test is verifying that the app rejects
        # invalid credentials.  Do NOT escalate to human takeover.
        transient_text = state.get("transient_page_text", "")
        if not state.get("expect_login_failure", False) and (
            "invalid user" in transient_text.lower() or "invalid user" in error_msg.lower()
        ):
            # Extract voicer name from action history for a helpful message
            voicer_hint = _extract_assigned_voicer(state)
            hint_str = f" (assigned voicer: '{voicer_hint}')" if voicer_hint else ""
            logger.warning(
                "[%s] Credential failure 'Invalid User'%s — immediate human takeover",
                run_id,
                hint_str,
            )
            return {
                "_next_node": "human_takeover",
                "awaiting_human_takeover": True,
                "agent_critique": (
                    f"Credentials unknown for this role{hint_str}. "
                    f"The agent cannot guess the correct email — human must log in manually."
                ),
                "ac_step_fail_counts": fail_counts,
                "last_error": f"Invalid User — credentials unknown{hint_str}",
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "ac_step_failure_diary": existing_diary,
            }

        # ── Fast-path #1a: OPTION_NOT_FOUND — wrong option text in portal ──
        # primeng_dropdown enumerates available option texts when the target isn't found.
        # Route immediately to planner with the list so the agent corrects target_text
        # on the very next attempt instead of burning retries on a non-existent option.
        if "OPTION_NOT_FOUND" in error_msg:
            logger.warning(
                "[%s] OPTION_NOT_FOUND on AC step %d — injecting available option list",
                run_id,
                ac_index + 1,
            )
            return {
                "_next_node": "planner",
                "retry_count": state.get("retry_count", 0) + 1,
                "agent_critique": (
                    f"⛔ WRONG OPTION TEXT (attempt {action_fail_count}): {error_msg[:500]}\n"
                    f"The target_text you used does NOT exist in the portal. "
                    f"READ THE AVAILABLE OPTIONS listed above and pick the EXACT matching label. "
                    f"Do NOT invent option text — use only what is listed."
                ),
                "last_error": error_msg,
                "ac_step_fail_counts": fail_counts,
                "ac_step_action_fail_count": action_fail_count,
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "ac_step_failure_diary": existing_diary,
                "action_repeat_counts": action_repeat_counts,
            }

        # ── Fast-path #1b: INTERCEPTOR_BLOCKED — extract the fix from the error ──
        # The Pydantic validator in PlannerAction raises INTERCEPTOR BLOCKED with
        # an embedded fix instruction. The planner sometimes ignores it and retries
        # the same forbidden action repeatedly. Detect this pattern early and
        # inject the fix as agent_critique so it appears prominently in the next prompt.
        if "PRIMENG_DROPDOWN_BLOCKED" in error_msg or "INTERCEPTOR BLOCKED" in error_msg:
            logger.warning(
                "[%s] INTERCEPTOR_BLOCKED on AC step %d (attempt %d) — injecting fix guidance",
                run_id,
                ac_index + 1,
                action_fail_count,
            )
            return {
                "_next_node": "planner",
                "retry_count": state.get("retry_count", 0) + 1,
                "agent_critique": (
                    f"⛔ INTERCEPTOR BLOCKED (attempt {action_fail_count}): {error_msg[:600]}\n"
                    f"READ THE ERROR MESSAGE ABOVE CAREFULLY. It contains the exact correct action format. "
                    f"Do NOT retry the same forbidden action. Follow the prescribed fix exactly."
                ),
                "last_error": error_msg,
                "ac_step_fail_counts": fail_counts,
                "ac_step_action_fail_count": action_fail_count,
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "ac_step_failure_diary": existing_diary,
                "action_repeat_counts": action_repeat_counts,
            }

        # ── Fast-path #2: Native file-picker — unautomatable ─────────
        # Browser native file pickers cannot be controlled by Playwright.
        # Detect by element name and immediately request human intervention.
        FILE_PICKER_NAMES = {"browse", "browse files", "choose file", "upload file", "select file"}
        if action_type == "click" and planned_name.lower() in FILE_PICKER_NAMES:
            logger.warning(
                "[%s] File-picker detected ('%s') — Playwright cannot control native file dialogs "
                "— immediate human takeover",
                run_id,
                planned_name,
            )
            return {
                "_next_node": "human_takeover",
                "awaiting_human_takeover": True,
                "agent_critique": (
                    f"'{planned_name}' opens a native OS file picker that Playwright cannot automate. "
                    f"Human must select and upload the file manually using the browser window."
                ),
                "ac_step_fail_counts": fail_counts,
                "last_error": f"Native file picker '{planned_name}' cannot be automated",
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "ac_step_failure_diary": existing_diary,
                "action_repeat_counts": action_repeat_counts,
            }

        # Safety net: 10+ total step failures → terminate
        if step_fail_count >= 10:
            logger.error(
                "[%s] STUCK LOOP: AC step %d failed %d times total — terminating run",
                run_id,
                ac_index + 1,
                step_fail_count,
            )
            failure_bug = {
                "type": "QA",
                "description": (
                    f"AC step {ac_index + 1} failed after {locator_fail_count} attempts. Last error: {error_msg}"
                ),
                "severity": "CRITICAL",
                "screenshot_url": latest_step.get("screenshot_url", ""),
            }
            return {
                "_next_node": "reporter",
                "agent_critique": f"Step failed after extended retries: {error_msg}",
                "bug_log": rbac_violations + [failure_bug],
                "long_term_memory": new_memories,
                "ac_step_failure_diary": existing_diary,
                "ac_step_action_fail_count": action_fail_count,
                "action_repeat_counts": action_repeat_counts,
            }

        # ── T3-c: Reflex Layer — hard-coded signature recovery (FEAT-118) ──
        # Runs BEFORE recovery_router so deterministic signatures skip Bedrock entirely.
        try:
            from backend.engine.reflex import attempt_short_circuit as _reflex_attempt

            _reflex_result = _reflex_attempt(state, error_msg, planned_action)
            if _reflex_result is not None:
                logger.info(
                    "[%s] REFLEX: signature=%s fired for AC step %d",
                    run_id,
                    _reflex_result.signature,
                    ac_index + 1,
                )
                _reflex_invocations = state.get("reflex_invocations", 0) + 1
                _reflex_hits = list(state.get("reflex_hits", [])) + [
                    {"signature": _reflex_result.signature, "ac_step": ac_index + 1}
                ]
                if _reflex_result.escalate_to_hitl:
                    return {
                        "_next_node": "human_takeover",
                        "reflex_invocations": _reflex_invocations,
                        "reflex_hits": _reflex_hits,
                        "agent_critique": _reflex_result.critique,
                        "last_error": error_msg,
                        "long_term_memory": new_memories,
                        "bug_log": rbac_violations,
                        "ac_step_failure_diary": existing_diary,
                        "action_repeat_counts": action_repeat_counts,
                    }
                return {
                    "_next_node": "planner",
                    "reflex_invocations": _reflex_invocations,
                    "reflex_hits": _reflex_hits,
                    "planned_action": _reflex_result.recovery_action or planned_action,
                    "agent_critique": _reflex_result.critique,
                    "last_error": error_msg,
                    "retry_count": retry_count + 1,
                    "ac_step_fail_counts": state.get("ac_step_fail_counts", {}),
                    "ac_step_action_fail_count": state.get("ac_step_action_fail_count", 0),
                    "long_term_memory": new_memories,
                    "bug_log": rbac_violations,
                    "ac_step_failure_diary": existing_diary,
                    "action_repeat_counts": action_repeat_counts,
                }
        except Exception as _reflex_exc:
            logger.debug("Reflex layer error (non-fatal, continuing): %s", _reflex_exc)
        # ── END T3-c Reflex Layer ───────────────────────────────────────────

        # ── FEAT-022: Recovery Router — multi-type automatic recovery ────
        from backend.engine.recovery_router import attempt_recovery

        _recovery = attempt_recovery(state, error_msg, planned_action)
        if _recovery is not None:
            logger.info(
                "[%s] RECOVERY ROUTER: %s auto-fix applied for AC step %d",
                run_id,
                _recovery.recovery_type.value,
                ac_index + 1,
            )
            # Update the failure diary entry with recovery info
            if existing_diary:
                _recovery_diary = dict(existing_diary[-1])
                _recovery_diary["recovery_attempted"] = _recovery.recovery_type.value
                _recovery_diary["recovery_critique"] = _recovery.critique
                existing_diary[-1] = _recovery_diary

            # Safely retrieve attempted_types from state for state updating
            raw_types = state.get("recovery_attempted_types")
            if isinstance(raw_types, list):
                attempted_types = set(raw_types)
            elif isinstance(raw_types, set):
                attempted_types = raw_types
            else:
                attempted_types = set()

            if state.get("recovery_attempted", False):
                from backend.engine.recovery_router import RecoveryType
                attempted_types = {t.value for t in RecoveryType}

            updated_attempted_types = attempted_types | {_recovery.recovery_type.value}

            # Recovery is a "free attempt" — we return the original fail counts
            # so the next attempt (after recovery) feels like a fresh retry.
            return {
                "_next_node": "planner",
                "recovery_attempted_types": updated_attempted_types,
                "recovery_action_log": state.get("recovery_action_log", []) + [_recovery.recovery_log or {}],
                "planned_action": _recovery.modified_action or planned_action,
                "agent_critique": _recovery.critique,
                "last_error": error_msg,
                "ac_step_fail_counts": state.get("ac_step_fail_counts", {}),
                "ac_step_action_fail_count": state.get("ac_step_action_fail_count", 0),
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "ac_step_failure_diary": existing_diary,
                "action_repeat_counts": action_repeat_counts,
            }

        # ── Vision-mode auto-escalation ─────────────────────────────────────

        # If the agent is stuck failing in DOM mode, "open its eyes" by
        # switching to pure vision (som_coordinates).  This gives the agent
        # a fresh set of retries using annotated screenshots + coordinate clicks
        # before falling through to human_takeover at 5 failures.
        #
        # Threshold: 3 Playwright action failures (not verifier rejections).
        # Only triggers once per AC step (dom → som_coordinates is one-way).
        current_vision_mode = state.get("vision_mode", "dom")
        if current_vision_mode == "dom" and action_fail_count >= 2:
            logger.warning(
                "[%s] AUTO-ESCALATION: AC step %d has %d DOM-mode failures — "
                "switching to vision_mode='som_coordinates' for coordinate-based navigation",
                run_id,
                ac_index + 1,
                action_fail_count,
            )
            return {
                "_next_node": "planner",
                "retry_count": retry_count + 1,
                "vision_mode": "som_coordinates",
                "ac_step_action_fail_count": 0,  # Fresh failure budget for vision mode
                "current_ac_step_action_count": state.get(
                    "current_ac_step_action_count", 0
                ),  # TASK-021: preserve total action budget across transition
                "agent_critique": (
                    f"VISION MODE ACTIVATED: After {action_fail_count} DOM-mode failures, "
                    f"the agent has switched to coordinate-based visual navigation. "
                    f"You will now receive an annotated screenshot with numbered red boxes "
                    f"on interactive elements. Use coordinate_action with mark_id to click. "
                    f"Previous error: {error_msg}"
                ),
                "last_error": error_msg,
                "ac_step_fail_counts": fail_counts,
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "dom_failure_diagnosis": "",
                "ac_step_failure_diary": existing_diary,
                "action_repeat_counts": action_repeat_counts,
            }

        # Trigger human takeover after threshold Playwright action failures (success=False).
        # FEAT-024: Threshold is now failure-type aware and configurable via Settings.
        # action_fail_count = pure Playwright errors (excludes verifier rejections).
        _err_label = _classify_error(error_msg)
        _threshold = settings.hitl_threshold_general
        if "INTERCEPTED" in _err_label:
            _threshold = settings.hitl_threshold_intercepted
        elif "STRICT_MODE" in _err_label:
            _threshold = settings.hitl_threshold_strict_mode

        if action_fail_count >= _threshold or vision_mode_fail_count >= 3:
            # ── FEAT-060 P4B: Confidence-Gated HITL ──────────────────────────
            # Before escalating to debugger/HITL, read _verifier_confidence.
            # Three-band routing based on verifier's normalized confidence score:
            #   Band 1: confidence < threshold_low (0.4 → ≤40/100)
            #     + retries exhausted → proceed to HITL (original behavior)
            #   Band 2: confidence in mid-range (40–70 / 100)
            #     → give one more retry with alternate strategy (defer HITL)
            #   Band 3: confidence > threshold_high (0.7 → ≥70/100)
            #     → treat as SATISFIED (agent misread the outcome — advance step)
            _verifier_confidence_raw = float(state.get("_verifier_confidence", 0.0))
            _verifier_verdict = state.get("_verifier_verdict", "")
            # Normalize: verifier returns 0–100, thresholds are 0.0–1.0
            _confidence_norm = _verifier_confidence_raw / 100.0

            try:
                from backend.config import settings as _s
                _confidence_enabled = _s.confidence_gated_hitl_enabled
                _low_threshold = _s.confidence_hitl_threshold_low
                _high_threshold = _s.confidence_hitl_threshold_high
            except Exception:
                _confidence_enabled = True
                _low_threshold = 0.4
                _high_threshold = 0.7

            if _confidence_enabled and _verifier_confidence_raw > 0:
                if _confidence_norm >= _high_threshold and _verifier_verdict == "satisfied":
                    # Band 3: High confidence and SATISFIED → accept as VERIFIED, advance step
                    _new_ac = ac_index + 1
                    logger.info(
                        "[%s] CONFIDENCE-GATE: High confidence (%.0f/100 ≥ %.0f%%) → "
                        "auto-advancing AC step %d/%d (treating as SATISFIED)",
                        run_id,
                        _verifier_confidence_raw,
                        _high_threshold * 100,
                        ac_index + 1,
                        len(ac_steps),
                    )
                    if _new_ac >= len(ac_steps):
                        return {
                            "_next_node": "reporter",
                            "ac_steps_completed": [ac_index],
                            "retry_count": 0,
                            "agent_critique": "",
                            "last_error": "",
                            "ac_step_fail_counts": {},
                            "verifier_not_yet_count": 0,
                            "verifier_total_not_yet_count": 0,
                            "_verifier_confidence": 0.0,
                        }
                    return {
                        "_next_node": "planner",
                        "ac_step_index": _new_ac,
                        "structured_step_index": _new_ac,
                        "current_sub_step_index": 0,
                        "ac_steps_completed": [ac_index],
                        "retry_count": 0,
                        "agent_critique": "",
                        "last_error": "",
                        "ac_step_fail_counts": {},
                        "ac_step_action_fail_count": 0,
                        "current_ac_step_action_count": 0,
                        "verifier_not_yet_count": 0,
                        "verifier_total_not_yet_count": 0,
                        "ac_step_failure_diary": [],
                        "_verifier_confidence": 0.0,
                    }
                elif _low_threshold <= _confidence_norm < _high_threshold:
                    # Band 2: Mid-range confidence → defer HITL, one more retry
                    logger.info(
                        "[%s] CONFIDENCE-GATE: Mid-range confidence (%.0f/100) → "
                        "deferring HITL, one more retry with alternate strategy (AC step %d/%d)",
                        run_id,
                        _verifier_confidence_raw,
                        ac_index + 1,
                        len(ac_steps),
                    )
                    return {
                        "_next_node": "planner",
                        "retry_count": retry_count + 1,
                        "agent_critique": (
                            f"CONFIDENCE-GATE RETRY: confidence={_verifier_confidence_raw:.0f}/100 (mid-range). "
                            f"The verifier is uncertain — try a different action or wait for page stability. "
                            f"Failure: {error_msg[:100]}"
                        ),
                        "last_error": error_msg,
                        "ac_step_fail_counts": fail_counts,
                        "ac_step_action_fail_count": action_fail_count,
                        "long_term_memory": new_memories,
                        "bug_log": rbac_violations,
                        "ac_step_failure_diary": existing_diary,
                        "action_repeat_counts": action_repeat_counts,
                    }
                # else: Band 1 (low confidence) → fall through to original HITL logic

            # ── Phase 3C: Debugger intervention before human_takeover ─────
            # Give the RAG debugger ONE shot at diagnosing the issue and
            # suggesting an alternative approach before escalating to human.
            if not state.get("debugger_attempted", False):
                _dbg_reason = (
                    f"vision_mode_fail_count={vision_mode_fail_count}"
                    if vision_mode_fail_count >= 3
                    else f"action_fail_count={action_fail_count}"
                )
                logger.warning(
                    "[%s] AC step %d has %s — routing to DEBUGGER "
                    "for RAG-informed fix recommendation before human takeover",
                    run_id,
                    ac_index + 1,
                    _dbg_reason,
                )
                return {
                    "_next_node": "debugger",
                    "agent_critique": (
                        f"AC step {ac_index + 1} stuck after {action_fail_count} failures "
                        f"(vision failures: {vision_mode_fail_count}): {error_msg}. "
                        f"Routing to Debugger for automated diagnosis."
                    ),
                    "ac_step_fail_counts": fail_counts,
                    "ac_step_action_fail_count": action_fail_count,
                    "vision_mode_fail_count": vision_mode_fail_count,
                    "last_error": error_msg,
                    "long_term_memory": new_memories,
                    "bug_log": rbac_violations,
                    "ac_step_failure_diary": existing_diary,
                    "action_repeat_counts": action_repeat_counts,
                }

            # Debugger already attempted — escalate to human
            logger.warning(
                "[%s] AC step %d has exhausted failure budget (action=%d, vision=%d) — requesting human takeover",
                run_id,
                ac_index + 1,
                action_fail_count,
                vision_mode_fail_count,
            )
            return {
                "_next_node": "human_takeover",
                "awaiting_human_takeover": True,
                "exploration_attempted": True,
                "agent_critique": (
                    f"AC step {ac_index + 1} stuck after {action_fail_count} Playwright failures "
                    f"(vision failures: {vision_mode_fail_count}, debugger attempted, exploration attempted): {error_msg}"
                ),
                "ac_step_fail_counts": fail_counts,
                "ac_step_action_fail_count": action_fail_count,
                "vision_mode_fail_count": vision_mode_fail_count,
                "last_error": error_msg,
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "ac_step_failure_diary": existing_diary,
                "action_repeat_counts": action_repeat_counts,
            }

        # First & subsequent failures: route back to planner with a structured critique.
        # Enrich with dom_failure_diagnosis from executor if available.
        # This tells the LLM WHETHER the element exists (DOM_ABSENT/HIDDEN/PRESENT)
        # so it can choose a targeted recovery strategy rather than guessing.
        dom_diag = state.get("dom_failure_diagnosis", "")
        critique_prefix = f"{dom_diag}\n\n" if dom_diag else ""

        # ── DOM_HIDDEN fast-path: element exists but isn't visible yet ─────
        # This is an Angular animation / overlay timing problem, not a selector
        # problem. Don't burn human takeover on a 1-2s wait issue.
        # Only apply when step_fail_count is low (< 7) so we don't spin forever.
        if "DOM_HIDDEN" in dom_diag and step_fail_count < 7:
            logger.info(
                "[%s] AC step %d: DOM_HIDDEN — element exists but not visible "
                "(fail %d) — injecting wait directive instead of escalating",
                run_id,
                ac_index + 1,
                step_fail_count,
            )
            return {
                "_next_node": "planner",  # TASK-024 Phase 3: fixed undefined 'next_node' variable
                "ac_step_iteration_budget": step_budget,  # FEAT-021
                "ac_step_iterations_used": step_iterations_used,  # FEAT-021
                "retry_count": retry_count + 1,
                "agent_critique": (
                    f"{critique_prefix}"
                    f"RECOVERY DIRECTIVE: The element IS in the DOM but not visible. "
                    f"This is typically an Angular animation delay, a closed dropdown, "
                    f"or a parent container that needs to be opened first. "
                    f'Try: (1) {{"action": "wait", "value": 1500}} then retry with same locator, '
                    f"OR (2) click the PARENT element that reveals this one."
                ),
                "last_error": error_msg,
                "ac_step_fail_counts": fail_counts,
                "long_term_memory": new_memories,
                "bug_log": rbac_violations,
                "dom_failure_diagnosis": "",
                "ac_step_failure_diary": existing_diary,
                "action_repeat_counts": action_repeat_counts,
            }

        # ── KB Self-Heal Query ─────────────────────────────────────────────
        # Before routing back to planner, query the KB for any recorded guidance
        # for this exact failure scenario. This surfaces:
        #   1. HITL explanation entries the human typed during a previous takeover
        #   2. vSuite-actions.md workflows that match the step + error combination
        #   3. human_guidance.md entries saved from pre-run user_guidance
        #
        # The KB is hot-reloaded here (mtime check) so explanations saved during
        # THIS run's earlier HITL interventions are immediately available.
        kb_self_heal = ""
        if _kb is not None:
            try:
                _kb.reload_if_updated()  # Hot-reload if HITL wrote new entries
                kb_self_heal = _kb.query_for_failure(
                    ac_step=current_step,
                    error_message=error_msg,
                    last_action=f"{action_type} {locator_key}",
                    max_results=2,
                )
                if kb_self_heal:
                    logger.info(
                        "[%s] KB self-heal: found guidance for step '%s' (error=%s)",
                        run_id,
                        current_step[:60],
                        _classify_error(error_msg),
                    )
            except Exception as _kb_err:
                logger.debug("[%s] KB self-heal query failed (non-fatal): %s", run_id, _kb_err)

        # ── FEAT-013: Classify failure for targeted retry hints ─────────────
        try:
            from backend.engine.failure_classifier import (
                classify_failure as _classify_fc,
            )
            from backend.engine.failure_classifier import (
                get_retry_hint as _get_hint,
            )

            _failure_category = _classify_fc(error_msg)
            _retry_hint = _get_hint(_failure_category)
            _category_label = f"[{_failure_category.value}] "
        except Exception:
            _category_label = ""
            _retry_hint = "Try a completely different locator strategy."

        # Bug E fix: extract the 'aka get_by_role(...)' hint from strict mode
        # violation errors and prepend it as a CORRECTION directive to the critique.
        # Playwright recommends the most precise locator in the error message itself —
        # without this extraction the planner never sees it and keeps guessing.
        _aka_hint = _extract_aka_hint(error_msg)
        _aka_prefix = f"{_aka_hint}\n\n" if _aka_hint else ""

        critique = (
            f"{_aka_prefix}"
            f"{critique_prefix}"
            f"{_category_label}"
            f"Action '{action_type}' with locator '{locator_key}' FAILED: {error_msg}. "
            f"FORBIDDEN (do not retry): {locator_key}. "
            f"{_retry_hint}" + (f"\n\n{kb_self_heal}" if kb_self_heal else "")
        )
        logger.info(
            "[%s] AC step %d: failure %d (%s) — routing to planner for retry",
            run_id,
            ac_index + 1,
            step_fail_count,
            _category_label.strip("[] ") or "UNKNOWN",
        )

        # ── FEAT-020: Action History Buffer — append + cap ─────────────────
        # Build a structured entry for the rolling buffer so the planner
        # can see the last N failed actions and avoid repeating them.
        _ahb = list(state.get("action_history_buffer", []))
        _ahb.append(
            {
                "action": action_type,
                "strategy": planned_strategy,
                "target": planned_name,
                "error_type": _classify_error(error_msg),
                "iteration": state.get("planner_iteration", 0),
            }
        )
        _ahb = _ahb[-5:]  # FIFO: keep only last 5 entries

        return {
            "_next_node": "planner",
            "ac_step_iteration_budget": step_budget,  # FEAT-021
            "ac_step_iterations_used": step_iterations_used,  # FEAT-021
            "retry_count": retry_count + 1,
            "agent_critique": critique,
            "last_error": error_msg,
            "ac_step_fail_counts": fail_counts,
            "ac_step_action_fail_count": action_fail_count,  # Fix 1: write back
            "vision_mode_fail_count": vision_mode_fail_count,  # TASK-054
            "long_term_memory": new_memories,
            "bug_log": rbac_violations,
            "dom_failure_diagnosis": "",  # Clear after use
            "ac_step_failure_diary": existing_diary,
            "action_history_buffer": _ahb,  # FEAT-020
            "action_repeat_counts": action_repeat_counts,  # FEAT-031
        }

    # ── Case 2: Action = "done" (planner says AC step is satisfied) ───
    if planned_action.get("action") == "done" or action_type == "done":
        # ── Post-verifier last-step guard ─────────────────────────────────
        # The verifier routes back to evaluator on the final AC step with
        # ac_step_index already advanced to len(ac_steps).  Without this guard
        # the done handler would re-run and append an out-of-range index to
        # ac_steps_completed (making len(completed) = N+1, triggering a false
        # FAILED status in the reporter even when every step actually passed).
        if ac_index >= len(ac_steps) and ac_steps:
            logger.info(
                "[%s] Post-verifier last-step re-entry (ac_index=%d >= total=%d) — routing directly to reporter",
                run_id,
                ac_index,
                len(ac_steps),
            )

            # ── TASK-101 DVQ Final Recheck ────────────────────────────
            _dvq = list(state.get("deferred_verification_queue", []))
            _dvf = list(state.get("deferred_verification_failures", []))
            _dvs = list(state.get("deferred_verification_successes", []))

            if settings.enable_deferred_verification and _dvq:
                logger.info("[%s] DVQ final recheck: processing %d remaining entries", run_id, len(_dvq))
                from backend.browser.context import get_manager
                from backend.engine.verifier import _check_single_verification

                _manager = get_manager(run_id)
                _page = _manager.page

                for _entry in _dvq:
                    _verdict, _, _ = await _check_single_verification(
                        _page,
                        _entry["verification"],
                        run_id,
                        enable_deferred_verification=False,  # Disable bypass for re-check
                    )
                    _recheck_passed = _verdict == "satisfied"

                    if not _recheck_passed:
                        logger.warning(
                            "[%s] DVQ final recheck: re-check failed for step %d",
                            run_id,
                            _entry["ac_step_index"] + 1,
                        )
                        _dvf.append(
                            {
                                **_entry,
                                "backtracked": False,
                                "consumed_at_step": _entry["ac_step_index"],
                                "failure_reason": f"Deferred final re-check failed (verdict={_verdict})",
                            }
                        )
                    else:
                        logger.info(
                            "[%s] DVQ final recheck: re-check passed for step %d — soft assertion satisfied",
                            run_id,
                            _entry["ac_step_index"] + 1,
                        )
                        _dvs.append(
                            {
                                **_entry,
                                "reason": f"Deferred final re-check passed (verdict={_verdict})",
                            }
                        )
                _dvq = []  # Empty the queue

            return {
                "_next_node": "reporter",
                "bug_log": rbac_violations,
                "deferred_verification_queue": _dvq,
                "deferred_verification_failures": _dvf,
                "deferred_verification_successes": _dvs,
            }

        # ── PREMATURE DONE GUARD ──────────────────────────────────────────
        # Hard state check: the planner CANNOT call 'done' on step N if any
        # earlier step (0..N-1) was never completed. This prevents the agent
        # from hallucinating "All steps complete" when earlier steps failed.
        # Exception: on the last AC step, allow done even with prior failures —
        # the coverage-gap check below will flag them in the report.
        _completed_so_far: list[int] = state.get("ac_steps_completed", [])
        _completed_set = set(_completed_so_far)
        _failed_earlier = [i for i in range(ac_index) if i not in _completed_set]
        _is_last_step = ac_index >= len(ac_steps) - 1 if ac_steps else False
        if _failed_earlier and _is_last_step:
            logger.warning(
                "[%s] PREMATURE DONE GUARD: on last step (%d), allowing done "
                "with %d incomplete prior step(s) %s — coverage gap will be reported",
                run_id,
                ac_index + 1,
                len(_failed_earlier),
                [i + 1 for i in _failed_earlier],
            )
            _failed_earlier = []
        if _failed_earlier:
            _failed_strs = [
                f"Step {i + 1} ('{ac_steps[i][:60]}...')"
                if i < len(ac_steps) and len(ac_steps[i]) > 60
                else f"Step {i + 1} ('{ac_steps[i]}')"
                if i < len(ac_steps)
                else f"Step {i + 1}"
                for i in _failed_earlier
            ]
            _error_msg = (
                f"ERROR: You cannot call 'done'. "
                f"These earlier AC steps are INCOMPLETE and must be resolved first: "
                f"{chr(10).join(_failed_strs)}. "
                f"You are on Step {ac_index + 1}. Complete all prior steps before marking done."
            )
            logger.warning(
                "[%s] PREMATURE DONE BLOCKED: step %d attempted done but steps %s are incomplete",
                run_id,
                ac_index + 1,
                [i + 1 for i in _failed_earlier],
            )
            return {
                "_next_node": "planner",
                "last_error": _error_msg,
                "retry_count": state.get("retry_count", 0) + 1,
                "agent_critique": _error_msg,
                "ac_step_failure_diary": existing_diary
                + [
                    {
                        "attempt": state.get("retry_count", 0) + 1,
                        "action": "done (premature — blocked by guard)",
                        "error": _error_msg[:200],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        # ── Done-spinning guard (tiered escalation) ───────────────────────────
        # When the planner emits "done" repeatedly on an unverified step and
        # the verifier keeps rejecting it, escalate in tiers keyed to the
        # consecutive-done count on the current AC step:
        #
        #   • 3 consecutive dones → trip #1: route to planner with warning 1/2.
        #   • 4 consecutive dones → trip #2: route to planner with warning 2/2.
        #   • 5 consecutive dones → trip #3: HARD FAIL to reporter with
        #     failure_type=AGENT_STUCK.
        #
        # Rationale: the earlier flat guard (return-to-planner on every trip)
        # never terminated because "done" is exempt from the AC-level circuit
        # breaker via is_finishing_move (see ~line 861) and this guard's return
        # dict does not persist ac_step_iterations_used. The planner would
        # therefore re-emit "done" until max_planner_iterations=500 fired
        # (observed on QA-359: 75-iteration log).
        #
        # Original QA-358 case: 13 consecutive done-emissions on vPromotions
        # ghost login exhausted the per-step budget without progress. This
        # tiered escalation terminates cleanly in ~5 iterations.
        _prior_verifier_rejections = state.get("verifier_total_not_yet_count", 0) > 0
        _completed_steps_early: list[int] = state.get("ac_steps_completed", [])
        _step_unverified_early = ac_index not in _completed_steps_early
        if _prior_verifier_rejections and _step_unverified_early:
            _recent_done_count = 0
            for _entry in reversed(state.get("detailed_execution_log", [])):
                if _entry.get("ac_step_index") != ac_index:
                    continue
                if _entry.get("action_type") == "done":
                    _recent_done_count += 1
                else:
                    break

            # Trip #3 (>=5 consecutive dones): planner ignored 2 prior warnings.
            # Hard-fail to reporter with AGENT_STUCK so the run terminates in a
            # bounded number of iterations instead of looping to max_planner_iterations.
            if _recent_done_count >= 5:
                logger.error(
                    "[%s] DONE-SPINNING ESCALATED to AGENT_STUCK for AC step %d/%d: "
                    "%d consecutive done emissions after 2 planner warnings — failing the run",
                    run_id,
                    ac_index + 1,
                    len(ac_steps),
                    _recent_done_count,
                )
                _emit_cb(
                    state,
                    "done_spin_escalated",
                    f"AC step {ac_index + 1}: {_recent_done_count} consecutive done emissions after 2 planner warnings",
                )
                return {
                    "_next_node": "reporter",
                    "failure_type": "AGENT_STUCK",
                    "agent_critique": (
                        f"AC step {ac_index + 1} emitted 'done' {_recent_done_count} times consecutively "
                        f"after 2 planner warnings, but the verifier kept rejecting it. "
                        f"The agent could not identify or interact with the concrete UI element required "
                        f"to complete the step. Failing the run."
                    ),
                    "last_error": (
                        f"done-spinning escalated: {_recent_done_count} consecutive done emissions "
                        f"on unverified step {ac_index + 1}"
                    ),
                    "bug_log": rbac_violations,
                }

            # Trip #1 or #2 (3 or 4 consecutive dones): warn planner and force
            # a concrete alternative action.
            if _recent_done_count >= 3:
                _trip_number = _recent_done_count - 2  # 3 dones → warning 1/2, 4 dones → warning 2/2
                _spin_msg = (
                    f"⛔ DONE-SPINNING BLOCKED (warning {_trip_number}/2): "
                    f"You have emitted 'done' {_recent_done_count} times in a row on this AC step, "
                    f"but the verifier keeps rejecting it. The step is NOT complete. Emitting 'done' "
                    f"again will fail the run. Read the <page_state>, identify the concrete UI element "
                    f"you still need to interact with, and issue a specific click/fill/type action against it. "
                    f"If a select2/dropdown is stuck, remember: click the visible .select2-choice, "
                    f"then TYPE with keyboard (do NOT use fill on the hidden backing input)."
                )
                logger.warning(
                    "[%s] DONE-SPINNING BLOCKED (warning %d/2) for AC step %d/%d: %d consecutive done "
                    "emissions, %d verifier NOT_YET — forcing planner to pick concrete action",
                    run_id,
                    _trip_number,
                    ac_index + 1,
                    len(ac_steps),
                    _recent_done_count,
                    state.get("verifier_total_not_yet_count", 0),
                )
                return {
                    "_next_node": "planner",
                    "retry_count": state.get("retry_count", 0) + 1,
                    "agent_critique": _spin_msg,
                    "last_error": (
                        f"done-spinning: {_recent_done_count} consecutive done emissions "
                        f"on unverified step {ac_index + 1}"
                    ),
                    "verifier_not_yet_count": 0,
                    "_force_wait_before_next_action": True,
                    "_force_wait_ms": 1000,
                }

        # ── Unverified-done guard ─────────────────────────────────────────────
        # Route to the verifier whenever the planner emits "done" AND the current
        # AC step has not been independently confirmed. Two conditions trigger this:
        #
        # 1. Prior failures (original guard): ac_step_fail_counts is non-empty —
        #    means the planner failed at least once before claiming success.
        #
        # 2. Bug D fix — first-attempt done (no prior failures):
        #    ac_step_fail_counts is empty BUT the step is NOT yet in
        #    ac_steps_completed. A planner that emits "done" on the very first
        #    attempt has never been verified. Without this guard, the evaluator
        #    blindly accepts the give-up "done" and the skill_library records a
        #    false-positive skill with no real execution evidence.
        #
        # Exception: steps already present in ac_steps_completed were verified
        # in a previous pass (e.g. post-verifier re-entry on account-switch or
        # role-queue paths). Do NOT re-trigger verifier for those.
        #
        # ac_step_fail_counts is reset to {} when advancing to a new AC step,
        # so a non-empty dict means failures actually occurred on THIS step.
        # It survives vision-mode escalation (which resets action_fail_count
        # but not the fail_counts dict), so the guard is not evaded by escalation.
        _had_action_failures = bool(state.get("ac_step_fail_counts", {}))
        _completed_steps: list[int] = state.get("ac_steps_completed", [])
        _step_not_yet_verified = ac_index not in _completed_steps
        if _had_action_failures or _step_not_yet_verified:
            _failure_count = len(state.get("ac_step_fail_counts", {}))
            if _had_action_failures:
                logger.info(
                    "[%s] Planner emitted 'done' for AC step %d/%d but %d locator failure(s) "
                    "were recorded — routing to verifier for independent confirmation",
                    run_id,
                    ac_index + 1,
                    len(ac_steps),
                    _failure_count,
                )
            else:
                logger.info(
                    "[%s] Planner emitted 'done' for AC step %d/%d on first attempt "
                    "(zero prior failures, step not yet in ac_steps_completed) "
                    "— routing to verifier for independent confirmation (Bug D guard)",
                    run_id,
                    ac_index + 1,
                    len(ac_steps),
                )
            return {
                "_next_node": "verifier",
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "bug_log": rbac_violations,
                "verifier_not_yet_count": 0,
                # Leave verifier_total_not_yet_count alone so the hard cap
                # (total >= 5) can still catch persistent loops.
            }

        logger.info(
            "[%s] AC step %d/%d marked DONE",
            run_id,
            ac_index + 1,
            len(ac_steps),
        )

        # ── Skill Extraction: synthesize successful action sequence into KB ──
        # Pull only the executor steps that belong to THIS ac_step_index
        # and were successful. Fire-and-forget (non-blocking).
        _current_ac_text = ac_steps[ac_index] if ac_index < len(ac_steps) else ""
        if _skill_library and _current_ac_text:
            _step_actions = [
                s
                for s in state.get("detailed_execution_log", [])
                if s.get("ac_step_index") == ac_index and s.get("success", False)
            ]
            if _step_actions:
                try:
                    import asyncio as _asyncio

                    _asyncio.create_task(
                        _asyncio.to_thread(
                            _skill_library.record_skill,
                            _current_ac_text,
                            _step_actions,
                            state.get("jira_ticket", {}).get("id", ""),
                            state.get("role", ""),
                        )
                    )
                except Exception as _skill_err:
                    # Best-effort: skill extraction must never block the graph
                    logger.debug("[%s] Skill extraction error (non-fatal): %s", run_id, _skill_err)

        new_ac_index = ac_index + 1
        completed = [ac_index]  # Will be appended via operator.add

        # ── ACCOUNT_SWITCH: route to switch_actor_mid_run_node ────────────────
        # When the completed step is an ACCOUNT_SWITCH, skip normal advancement
        # and let switch_actor_mid_run_node do the context swap + index advance.
        _is_account_switch_step = False
        _test_plan = state.get("test_plan")
        if _test_plan:
            _plan_steps = _test_plan.get("steps", [])
            if ac_index < len(_plan_steps):
                _is_account_switch_step = _plan_steps[ac_index].get("step_type") == "ACCOUNT_SWITCH"
        if not _is_account_switch_step and ac_index < len(ac_steps):
            from backend.engine.step_classifier import StepType as _ST
            from backend.engine.step_classifier import classify_step as _cls

            _is_account_switch_step = _cls(ac_steps[ac_index]) == _ST.ACCOUNT_SWITCH

        if _is_account_switch_step:
            logger.info(
                "[%s] ACCOUNT_SWITCH step %d/%d complete — routing to switch_actor_mid_run",
                run_id,
                ac_index + 1,
                len(ac_steps),
            )
            return {
                "_next_node": "switch_actor_mid_run",
                "ac_steps_completed": completed,
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "bug_log": rbac_violations,
                "ac_step_failure_diary": [],
                "action_repeat_counts": {},
                "ac_step_fail_counts": {},
                "ac_step_action_fail_count": 0,
                "current_ac_step_action_count": 0,
                "recovery_attempted_types": set(),  # FEAT-022: reset multi-type recovery list for new actor
                "action_history_buffer": [],  # FEAT-020: clear on step advance
            }

        # ── PERSONA_SWITCH: route to persona_switch_node ─────────────────────
        # When the completed step is a PERSONA_SWITCH, skip normal step
        # advancement and let persona_switch_node swap the auth context. The
        # node is responsible for advancing ac_step_index and returning to
        # planner. TASK-063 Phase 3.
        _is_persona_switch_step = False
        if _test_plan:
            if ac_index < len(_plan_steps):
                _is_persona_switch_step = _plan_steps[ac_index].get("step_type") == "PERSONA_SWITCH"
        if not _is_persona_switch_step and ac_index < len(ac_steps):
            try:
                from backend.engine.step_classifier import StepType as _ST2
                from backend.engine.step_classifier import classify_step as _cls2

                _is_persona_switch_step = _cls2(ac_steps[ac_index]) == _ST2.PERSONA_SWITCH
            except (ImportError, AttributeError):
                # StepType.PERSONA_SWITCH may not exist in all code paths — safe default
                _is_persona_switch_step = False

        if _is_persona_switch_step:
            logger.info(
                "[%s] PERSONA_SWITCH step %d/%d complete — routing to persona_switch",
                run_id,
                ac_index + 1,
                len(ac_steps),
            )
            return {
                "_next_node": "persona_switch",
                "ac_steps_completed": completed,
                # Note: ac_step_index is NOT advanced here — persona_switch_node
                # reads the current step for target_persona and then advances
                # ac_step_index itself (matching switch_actor_mid_run_node pattern).
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "bug_log": rbac_violations,
                "ac_step_failure_diary": [],
                "action_repeat_counts": {},
                "ac_step_fail_counts": {},
                "ac_step_action_fail_count": 0,
                "current_ac_step_action_count": 0,
                "recovery_attempted_types": set(),  # FEAT-022: reset multi-type recovery list for new persona
                "action_history_buffer": [],  # FEAT-020: clear on persona switch
            }

        # ── GHOST_LOGIN: route to ghost_login_node ───────────────────────────
        # When we're on a GHOST_LOGIN step and admin auth has NOT yet been
        # established, route to ghost_login_node so it can log in as admin
        # and land on the product URL. Once ghost_admin_authenticated is set,
        # the planner drives the ghost-panel DOM interaction and the step is
        # completed like any other — no need to route back to the node.
        _is_ghost_login_step = False
        if _test_plan:
            if ac_index < len(_plan_steps):
                _is_ghost_login_step = _plan_steps[ac_index].get("step_type") == "GHOST_LOGIN"

        if _is_ghost_login_step and not state.get("ghost_admin_authenticated"):
            logger.info(
                "[%s] GHOST_LOGIN step %d/%d complete — routing to ghost_login",
                run_id,
                ac_index + 1,
                len(ac_steps),
            )
            return {
                "_next_node": "ghost_login",
                "ac_steps_completed": completed,
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "bug_log": rbac_violations,
                "ac_step_failure_diary": [],
                "action_repeat_counts": {},
                "ac_step_fail_counts": {},
                "ac_step_action_fail_count": 0,
                "current_ac_step_action_count": 0,
                "recovery_attempted_types": set(),
                "action_history_buffer": [],
            }

        if new_ac_index >= len(ac_steps):
            # All AC steps complete — check for more roles
            remaining_roles = state.get("role_queue", [])

            if len(remaining_roles) > 1:
                # More roles to test — route back to setup_role
                logger.info(
                    "[%s] All AC done for current role. %d more roles in queue.",
                    run_id,
                    len(remaining_roles) - 1,
                )
                return {
                    "_next_node": "setup_role",
                    "ac_step_index": 0,  # Reset for next role
                    "structured_step_index": 0,
                    "current_sub_step_index": 0,
                    "ac_steps_completed": completed,
                    "retry_count": 0,
                    "agent_critique": "",
                    "last_error": "",
                    "bug_log": rbac_violations,
                    "ac_step_failure_diary": [],  # Clear diary for new role/step
                    "action_repeat_counts": {},  # Reset circuit breaker for new role
                    "ac_step_action_fail_count": 0,
                    "vision_mode_fail_count": 0,
                    "_force_wait_before_next_action": False,
                    "_force_wait_ms": 0,
                    "current_ac_step_action_count": 0,  # Reset total action budget for new role
                    "recovery_attempted_types": set(),  # FEAT-022: reset multi-type recovery list for new role
                    "action_history_buffer": [],  # FEAT-020: clear on role change
                }
            else:
                # Fully done — all AC steps, all roles
                logger.info("[%s] ALL AC steps and roles complete!", run_id)

                # ── TASK-101 DVQ Final Recheck ────────────────────────────
                _dvq = list(state.get("deferred_verification_queue", []))
                _dvf = list(state.get("deferred_verification_failures", []))
                _dvs = list(state.get("deferred_verification_successes", []))

                if settings.enable_deferred_verification and _dvq:
                    logger.info("[%s] DVQ final recheck: processing %d remaining entries", run_id, len(_dvq))
                    from backend.browser.context import get_manager
                    from backend.engine.verifier import _check_single_verification

                    _manager = get_manager(run_id)
                    _page = _manager.page

                    for _entry in _dvq:
                        _verdict, _, _ = await _check_single_verification(
                            _page,
                            _entry["verification"],
                            run_id,
                            enable_deferred_verification=False,  # Disable bypass for re-check
                        )
                        _recheck_passed = _verdict == "satisfied"

                        if not _recheck_passed:
                            logger.warning(
                                "[%s] DVQ final recheck: re-check failed for step %d",
                                run_id,
                                _entry["ac_step_index"] + 1,
                            )
                            _dvf.append(
                                {
                                    **_entry,
                                    "backtracked": False,
                                    "consumed_at_step": _entry["ac_step_index"],
                                    "failure_reason": f"Deferred final re-check failed (verdict={_verdict})",
                                }
                            )
                        else:
                            logger.info(
                                "[%s] DVQ final recheck: re-check passed for step %d — soft assertion satisfied",
                                run_id,
                                _entry["ac_step_index"] + 1,
                            )
                            _dvs.append(
                                {
                                    **_entry,
                                    "reason": f"Deferred final re-check passed (verdict={_verdict})",
                                }
                            )
                    _dvq = []  # Empty the queue

                # ── REC 7: AC step coverage gate ──────────────────────────
                # Verify every AC step index was actually executed before
                # declaring success.  Gaps occur when the agent emits `done`
                # prematurely or the verifier fast-path skips a step.
                all_completed_indices: list[int] = state.get("ac_steps_completed", [])
                uncovered = [i for i in range(len(ac_steps)) if i not in all_completed_indices]
                if uncovered:
                    logger.warning(
                        "[%s] COVERAGE GAP: AC step(s) %s were never executed — marking as skipped in bug_log",
                        run_id,
                        [i + 1 for i in uncovered],
                    )
                    gap_entries = list(rbac_violations or [])
                    for gap_idx in uncovered:
                        gap_step = ac_steps[gap_idx] if gap_idx < len(ac_steps) else f"Step {gap_idx + 1}"
                        gap_entries.append(
                            {
                                "type": "COVERAGE_GAP",
                                "ac_step": gap_step,
                                "ac_step_index": gap_idx,
                                "description": (
                                    f"AC step {gap_idx + 1}/{len(ac_steps)} was never executed. "
                                    f"The agent may have emitted 'done' prematurely on a prior step. "
                                    f"Step text: {gap_step[:100]}"
                                ),
                            }
                        )
                    rbac_violations = gap_entries

                return {
                    "_next_node": "reporter",
                    "ac_steps_completed": completed,
                    "ac_steps_coverage_gap": uncovered,  # TD-002
                    "retry_count": 0,
                    "agent_critique": "",
                    "bug_log": rbac_violations,
                    "ac_step_failure_diary": [],  # Clear diary — run complete
                    "action_repeat_counts": {},  # Clear circuit breaker — run complete
                    "current_ac_step_action_count": 0,  # Reset total action budget
                    "action_history_buffer": [],  # FEAT-020: clear on run complete
                    "deferred_verification_queue": _dvq,
                    "deferred_verification_failures": _dvf,
                    "deferred_verification_successes": _dvs,
                }
        else:
            # More AC steps remain — advance to next step
            logger.info(
                "[%s] Advancing to AC step %d/%d",
                run_id,
                new_ac_index + 1,
                len(ac_steps),
            )

            # ── FEAT-023 DVQ: process deferred verification queue on step advance ──
            _dvq = list(state.get("deferred_verification_queue", []))
            _dvf = list(state.get("deferred_verification_failures", []))
            _dvq_update: dict = {}
            _backtracked_to_index: int | None = None
            if settings.enable_deferred_verification and _dvq:
                _ripe, _remaining = _process_deferred_queue(_dvq, new_ac_index)
                if _ripe:
                    from backend.browser.context import get_manager
                    from backend.engine.verifier import _check_single_verification

                    _manager = get_manager(run_id)
                    _page = _manager.page

                    for _entry in _ripe:
                        # AC-HAPPY-8: Robust re-check
                        # 1. Re-verify the original assertion but WITHOUT auto-satisfy bypass
                        _verdict, _, _ = await _check_single_verification(
                            _page,
                            _entry["verification"],
                            run_id,
                            enable_deferred_verification=False,  # Disable bypass for re-check
                        )

                        _recheck_passed = _verdict == "satisfied"

                        # 2. Robust Look-ahead: if original fails, check if the step just COMPLETED is satisfied
                        # Since we are advancing TO new_ac_index, the step we just "completed" is ac_index.
                        # If ac_index's verification passes, then the previous deferred step was likely fine.
                        if not _recheck_passed:
                            _test_plan = state.get("test_plan")
                            if _test_plan and ac_index < len(_test_plan.get("steps", [])):
                                _cur_step_verifications = _test_plan["steps"][ac_index].get("verification", [])
                                for _v in _cur_step_verifications:
                                    # Ensure we use a dict for the verifier
                                    _v_dict = _v if isinstance(_v, dict) else _v.model_dump()
                                    _v_verdict, _, _ = await _check_single_verification(
                                        _page, _v_dict, run_id, enable_deferred_verification=False
                                    )
                                    if _v_verdict == "satisfied":
                                        _recheck_passed = True
                                        logger.info(
                                            "[%s] DVQ: robust look-ahead passed for step %d via step %d verification",
                                            run_id,
                                            _entry["ac_step_index"] + 1,
                                            ac_index + 1,
                                        )
                                        break

                        if not _recheck_passed:
                            # Re-check failed -> record DVF and consider backtrack
                            _entry_idx = _entry["ac_step_index"]
                            _dist = new_ac_index - _entry_idx
                            _can_backtrack = _dist <= settings.deferred_backtrack_limit

                            _dvf.append(
                                {
                                    **_entry,
                                    "backtracked": _can_backtrack,
                                    "consumed_at_step": new_ac_index,
                                    "failure_reason": f"Deferred re-check failed (verdict={_verdict})",
                                }
                            )

                            if _can_backtrack:
                                if _backtracked_to_index is None or _entry_idx < _backtracked_to_index:
                                    _backtracked_to_index = _entry_idx
                                logger.warning(
                                    "[%s] DVQ: re-check failed for step %d — BACKTRACKING from %d to %d",
                                    run_id,
                                    _entry_idx + 1,
                                    new_ac_index + 1,
                                    _entry_idx + 1,
                                )
                        else:
                            logger.info(
                                "[%s] DVQ: re-check passed for step %d — soft assertion satisfied",
                                run_id,
                                _entry["ac_step_index"] + 1,
                            )

                    _dvq_update = {
                        "deferred_verification_queue": _remaining,
                        "deferred_verification_failures": _dvf,
                    }
                    if _backtracked_to_index is not None:
                        _dvq_update["ac_step_index"] = _backtracked_to_index
                        _dvq_update["structured_step_index"] = _backtracked_to_index  # FEAT-025
                        _dvq_update["target_element_types"] = _get_target_roles_for_step(
                            state, _backtracked_to_index
                        )  # FEAT-025
                        _dvq_update["retry_count"] = retry_count

                    logger.info(
                        "[%s] DVQ: %d ripe entries processed, %d remaining",
                        run_id,
                        len(_ripe),
                        len(_remaining),
                    )

            _step_advance_result = {
                "_next_node": "planner",
                "ac_step_index": new_ac_index,
                "structured_step_index": new_ac_index,
                "current_sub_step_index": 0,
  # FEAT-025
                "target_element_types": _get_target_roles_for_step(state, new_ac_index),  # FEAT-025
                "ac_steps_completed": completed,
                "retry_count": 0,  # Reset retries for new step
                "ac_step_iteration_budget": 0,  # FEAT-021: trigger re-calc
                "ac_step_iterations_used": 0,  # FEAT-021: reset counter
                "agent_critique": "",
                "last_error": "",
                "ac_step_fail_counts": {},  # Reset locator tracking for new step
                "ac_step_action_fail_count": 0,  # Fix 1: reset Playwright-failure budget for new step
                "vision_mode_fail_count": 0,  # FEAT-049: reset vision failure counter
                "_force_wait_before_next_action": False,
                "_force_wait_ms": 0,
                "current_ac_step_action_count": 0,  # Task 3: reset total action budget for new step
                "bug_log": rbac_violations,
                "ac_step_failure_diary": [],  # Clear diary for new step
                "action_repeat_counts": {},  # Reset circuit breaker for new step
                "recovery_attempted_types": set(),  # FEAT-022: reset multi-type recovery list for new step
                "action_history_buffer": [],  # FEAT-020: clear on step advance
            }
            _step_advance_result.update(_dvq_update)
            return _step_advance_result

    # ── Case 3: Action SUCCEEDED, AC step still in progress ──────────
    # Route to the step_verifier_node for semantic completion checking.
    # Only reachable when success=True and action != "done".

    # ── FEAT-063 AC-1: Hard-block "wait" as sole success action ─────────
    # If the only action taken for this AC step was a 'wait' or 'screenshot',
    # do NOT route to the verifier. A 'wait' alone cannot satisfy an AC step
    # unless it's a pure observation step (which should be handled by the
    # planner using action='done' once satisfied).
    # This prevents the agent from stalling by just waiting repeatedly.
    if action_type in ("wait", "screenshot") and success:
        actions_on_step = [
            s for s in log
            if s.get("ac_step_index") == ac_index
            and s.get("action_type") not in ("wait", "screenshot", "verify")
        ]
        if not actions_on_step:
            logger.warning(
                "[%s] AC-1 GUARD: '%s' was the only action on AC step %d. "
                "Skipping verifier and routing back to planner.",
                run_id, action_type, ac_index + 1
            )
            return _finalize({
                "_next_node": "planner",
                "agent_critique": (
                    f"You successfully performed a '{action_type}', but a '{action_type}' "
                    f"alone cannot complete AC step {ac_index + 1}. You MUST perform "
                    f"a real action (click, fill, navigate, etc.) to progress. "
                    f"Waiting again will not help."
                ),
                "ac_step_iteration_budget": step_budget,
                "ac_step_iterations_used": step_iterations_used,
            })

    logger.info(
        "[%s] Action succeeded — routing to verifier for AC step %d/%d",
        run_id,
        ac_index + 1,
        len(ac_steps),
    )

    # Write to long_term_memory when an executor fallback succeeded
    success_memories: list[str] = []
    exec_fallback = state.get("last_executor_fallback", "")
    if exec_fallback:
        success_memories.append(
            f"LEARNED: '{exec_fallback}' fallback succeeded on AC step {ac_index + 1} — "
            f"use this strategy directly next time for similar elements."
        )

    # ── Selector Registry: persist confirmed working selector ─────────────
    # Every successful action that used a non-trivial locator is recorded.
    # This is best-effort — never blocks routing.
    if _selector_registry:
        try:
            _pa = state.get("planned_action", {})
            _sel_strategy = _pa.get("strategy", "")
            _sel_name = _pa.get("name", "") or _pa.get("value", "")
            _sel_role = _pa.get("role", "")
            _sel_css = _pa.get("selector", "")
            _ac_text = ac_steps[ac_index] if ac_index < len(ac_steps) else ""
            if _sel_name and _ac_text:
                _selector_registry.record_verified_selector(
                    ac_step_text=_ac_text,
                    strategy=_sel_strategy,
                    name=_sel_name,
                    selector=_sel_css,
                    role=_sel_role,
                    context=state.get("current_url", ""),
                )
        except Exception as _sel_err:
            logger.debug("[%s] Selector record error (non-fatal): %s", run_id, _sel_err)

    # ── FEAT-057: Sub-step verification deferral ──────────────────────────
    # If the current structured step has sub_steps, only route to the verifier
    # AFTER the final sub-step has been performed.
    sub_steps = []
    test_plan = state.get("test_plan")
    if test_plan:
        plan_steps = test_plan.get("steps", [])
        if struct_index < len(plan_steps):
            step = plan_steps[struct_index]
            sub_steps = step.get("sub_steps", []) if isinstance(step, dict) else getattr(step, "sub_steps", [])

    if sub_steps and current_sub_step_idx < len(sub_steps) - 1:
        next_sub_step = sub_steps[current_sub_step_idx + 1]
        logger.info(
            "[%s] Sub-step %d/%d complete — deferring verification and routing back to planner for: %s",
            run_id,
            current_sub_step_idx + 1,
            len(sub_steps),
            next_sub_step,
        )
        return {
            "_next_node": "planner",
            "current_sub_step_index": current_sub_step_idx + 1,
            "ac_step_iteration_budget": step_budget,
            "ac_step_iterations_used": step_iterations_used,
            "retry_count": 0,
            "agent_critique": f"Sub-step {current_sub_step_idx + 1} complete. Next sub-step: {next_sub_step}",
            "last_error": "",
            "bug_log": rbac_violations,
            "long_term_memory": success_memories,
        }

    return _finalize({
        "_next_node": "verifier",
        "ac_step_iteration_budget": step_budget,  # FEAT-021
        "ac_step_iterations_used": step_iterations_used,  # FEAT-021
        "retry_count": 0,
        "agent_critique": "",
        "last_error": "",
        "bug_log": rbac_violations,
        "long_term_memory": success_memories,
        "verifier_not_yet_count": 0,  # Reset so verifier gets a fresh 3-try budget
    })


# ---------------------------------------------------------------------------
# Conditional edge function (used in graph.py)
# ---------------------------------------------------------------------------


def route_after_evaluator(state: VQAState) -> EvalRoute:
    """
    Conditional edge function that reads the evaluator's routing decision.

    Used as the argument to ``graph.add_conditional_edges()`` in
    ``backend/engine/graph.py``::

        graph.add_conditional_edges(
            "evaluator",
            route_after_evaluator,
            {
                "planner": "planner",
                "setup_role": "setup_role",
                "reporter": "reporter",
                "verifier": "verifier",
                "human_takeover": "human_takeover",
            },
        )
    """
    route = state.get("_next_node", "")
    if not route:
        logger.warning(
            "route_after_evaluator: _next_node is empty — defaulting to 'planner'. "
            "Check that evaluator_node returned _next_node and it is declared in VQAState."
        )
        return "planner"
    return route
