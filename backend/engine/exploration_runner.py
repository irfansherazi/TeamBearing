"""
vQA — Autonomous Exploration Mode (FEAT-040)
=============================================
Module: backend/engine/exploration_runner.py

Implements the ``ExplorationRunner`` class — an inline sub-agent dispatch
layer that fires inside ``evaluator_node`` *after* debugger intervention has
been attempted but *before* HITL escalation.

Architecture
------------
Follows the same pattern as ``rag_debugger.py``:
  - Called from ``evaluator_node`` (not a new LangGraph node)
  - Accepts the current ``VQAState`` and a live Playwright ``page`` reference
  - Returns a structured result dict that the evaluator uses to route next step

Failure Chain Position
----------------------
::

    planner_node → executor_node → evaluator_node
        ├── fail_count < 3:  → planner (retry)
        ├── fail_count == 3: → debugger_node (RAG-informed fix)
        │       └── debugger_attempted=True, fail_count >= threshold:
        │               ├── [THIS MODULE] ExplorationRunner.should_activate()
        │               │       ├── found → resume → planner
        │               │       └── not found → fall through to HITL
        │               └── [EXISTING] → human_takeover
        └── [other circuits] → human_takeover / reporter

Phase 2 Scope
-------------
  - ``ScrollToRevealStrategy``         — scroll page, check element visibility
  - ``ExpandCollapsedParentStrategy``  — click [aria-expanded=false] elements
  - ``ClickSiblingTabStrategy``        — cycle [role=tab] siblings
  - ``ExplorationRunner.run()``        — dispatches strategies in cost order
                                         with global step budget + exception guard

Phase 3 will implement KB injection.
Phase 4 will wire into evaluator_node + reporter badge.

See Also
--------
  - backend/engine/evaluator.py   — integration point (Phase 4)
  - backend/engine/state.py       — VQAState (exploration_outcomes, exploration_attempted)
  - backend/engine/schemas.py     — ExplorationOutcome TypedDict
  - backend/config.py             — ENABLE_EXPLORATION_MODE, EXPLORATION_MAX_STEPS
  - memory-bank/tasks/TASK-029.md — full specification and AC
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from backend.config import settings

if TYPE_CHECKING:
    from backend.engine.state import VQAState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPLORATION_FAILURE_TYPES: frozenset[str] = frozenset(
    {
        "NOT_VISIBLE",
        "DOM_ABSENT",
        "TIMEOUT",
        "",  # unclassified — attempt exploration conservatively
    }
)

EXPLORATION_BLOCKED_FAILURE_TYPES: frozenset[str] = frozenset(
    {
        "AUTH_GATE_BLOCKED",
        "STRICT_MODE",
        "INTERCEPTED",
        "APP_DEFECT",
        "ENV_BLOCKER",
    }
)

_SCROLL_INCREMENT_PX = 300
_SCROLL_MAX_PX = 3000


# ---------------------------------------------------------------------------
# Shared result builder
# ---------------------------------------------------------------------------


async def _capture_dom_snapshot(page: Any) -> dict:
    """Capture a compact DOM snapshot for delta detection and macro validation."""
    try:
        aria_tree = await page.evaluate("window.getvqaAriaTree ? window.getvqaAriaTree() : ''")
        element_count = await page.evaluate("document.querySelectorAll('*').length")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "element_count": element_count,
            "aria_tree_snippet": aria_tree[:2000] if aria_tree else "",
        }
    except Exception:
        return {"timestamp": datetime.now(timezone.utc).isoformat(), "element_count": 0}


def _strategy_result(
    *,
    found: bool,
    steps_taken: int,
    pathway_summary: str = "",
    error_message: str = "",
    action_log: list[dict] = None,
    dom_snapshots: list[dict] = None,
) -> dict:
    return {
        "found": found,
        "steps_taken": steps_taken,
        "pathway_summary": pathway_summary,
        "error_message": error_message,
        "action_log": action_log or [],
        "dom_snapshots": dom_snapshots or [],
    }


# ---------------------------------------------------------------------------
# ScrollToRevealStrategy
# ---------------------------------------------------------------------------


class ScrollToRevealStrategy:
    """
    Scroll the page incrementally and check for target element visibility
    after each scroll action (AC-STRATEGY-1).

    Parameters
    ----------
    page : playwright.async_api.Page
    target_locator : str
        CSS/Playwright locator for the target element.
    max_scroll_px : int
        Maximum scroll distance before giving up.
    scroll_increment : int
        Pixels to scroll per action.
    run_id : str
    """

    def __init__(
        self,
        page: Any,
        target_locator: str,
        max_scroll_px: int = _SCROLL_MAX_PX,
        scroll_increment: int = _SCROLL_INCREMENT_PX,
        run_id: str = "",
    ) -> None:
        self._page = page
        self._target_locator = target_locator
        self._max_scroll_px = max_scroll_px
        self._scroll_increment = scroll_increment
        self._run_id = run_id

    async def execute(self) -> dict:
        steps = 0
        scrolled_px = 0
        action_log = []
        dom_snapshots = []
        try:
            # Initial snapshot
            dom_snapshots.append(await _capture_dom_snapshot(self._page))

            while scrolled_px <= self._max_scroll_px:
                is_vis = await self._page.locator(self._target_locator).is_visible()
                if is_vis:
                    logger.info(
                        "[%s] ScrollToReveal: found after %dpx (%d steps).",
                        self._run_id,
                        scrolled_px,
                        steps,
                    )
                    return _strategy_result(
                        found=True,
                        steps_taken=steps,
                        pathway_summary=f"scroll_{scrolled_px}px → element visible",
                        action_log=action_log,
                        dom_snapshots=dom_snapshots,
                    )
                
                before_count = dom_snapshots[-1]["element_count"]
                await self._page.evaluate(f"window.scrollBy(0, {self._scroll_increment})")
                
                # After scroll snapshot
                snapshot = await _capture_dom_snapshot(self._page)
                dom_snapshots.append(snapshot)
                
                action_log.append({
                    "type": "scroll",
                    "value": self._scroll_increment,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "dom_delta_detected": snapshot["element_count"] != before_count,
                })
                scrolled_px += self._scroll_increment
                steps += 1

            logger.info(
                "[%s] ScrollToReveal: budget exhausted (%dpx, %d steps).",
                self._run_id,
                scrolled_px,
                steps,
            )
            return _strategy_result(
                found=False, 
                steps_taken=steps, 
                action_log=action_log, 
                dom_snapshots=dom_snapshots
            )

        except Exception as exc:
            logger.warning("[%s] ScrollToReveal exception: %s", self._run_id, exc)
            return _strategy_result(
                found=False, 
                steps_taken=steps, 
                error_message=str(exc),
                action_log=action_log,
                dom_snapshots=dom_snapshots
            )


# ---------------------------------------------------------------------------
# ExpandCollapsedParentStrategy
# ---------------------------------------------------------------------------


class ExpandCollapsedParentStrategy:
    """
    Query all ``[aria-expanded='false']`` elements, click each one, and check
    whether the target element becomes visible after each expansion (AC-STRATEGY-2).

    Parameters
    ----------
    page : playwright.async_api.Page
    target_locator : str
    run_id : str
    """

    def __init__(self, page: Any, target_locator: str, run_id: str = "") -> None:
        self._page = page
        self._target_locator = target_locator
        self._run_id = run_id

    async def execute(self) -> dict:
        steps = 0
        action_log = []
        dom_snapshots = []
        try:
            # Initial snapshot
            dom_snapshots.append(await _capture_dom_snapshot(self._page))

            triggers = await self._page.query_selector_all("[aria-expanded='false']")
            if not triggers:
                logger.info("[%s] ExpandCollapsed: no collapsed elements found.", self._run_id)
                return _strategy_result(found=False, steps_taken=0, dom_snapshots=dom_snapshots)

            for trigger in triggers:
                try:
                    # Get a selector for the trigger for macro synthesis
                    selector = await trigger.evaluate(
                        "el => el.getAttribute('data-vqa-id') ? `[data-vqa-id='${el.getAttribute('data-vqa-id')}']` : (el.id ? `#${el.id}` : el.tagName.toLowerCase())"
                    )
                    
                    before_count = dom_snapshots[-1]["element_count"]
                    
                    await trigger.click()
                    steps += 1
                    
                    # Capture after state
                    snapshot = await _capture_dom_snapshot(self._page)
                    dom_snapshots.append(snapshot)
                    
                    dom_delta = before_count != snapshot["element_count"]
                    
                    action_log.append({
                        "type": "click",
                        "selector": selector,
                        "dom_delta_detected": dom_delta,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    
                    is_vis = await self._page.locator(self._target_locator).is_visible()
                    if is_vis:
                        logger.info(
                            "[%s] ExpandCollapsed: found after trigger click (step %d).",
                            self._run_id,
                            steps,
                        )
                        return _strategy_result(
                            found=True,
                            steps_taken=steps,
                            pathway_summary=f"expand_trigger_{steps} → element visible",
                            action_log=action_log,
                            dom_snapshots=dom_snapshots,
                        )
                except Exception as click_exc:
                    logger.debug(
                        "[%s] ExpandCollapsed: trigger click error %s (continuing).",
                        self._run_id,
                        click_exc,
                    )
                    steps += 1
                    continue

            return _strategy_result(
                found=False, 
                steps_taken=steps, 
                action_log=action_log, 
                dom_snapshots=dom_snapshots
            )

        except Exception as exc:
            logger.warning("[%s] ExpandCollapsed exception: %s", self._run_id, exc)
            return _strategy_result(
                found=False, 
                steps_taken=steps, 
                error_message=str(exc),
                action_log=action_log,
                dom_snapshots=dom_snapshots
            )


# ---------------------------------------------------------------------------
# ClickSiblingTabStrategy
# ---------------------------------------------------------------------------


class ClickSiblingTabStrategy:
    """
    Cycle through ``[role='tab']`` sibling elements (skipping the active tab)
    and check whether the target becomes visible after each click (AC-STRATEGY-3).

    Parameters
    ----------
    page : playwright.async_api.Page
    target_locator : str
    run_id : str
    """

    def __init__(self, page: Any, target_locator: str, run_id: str = "") -> None:
        self._page = page
        self._target_locator = target_locator
        self._run_id = run_id

    async def execute(self) -> dict:
        steps = 0
        action_log = []
        dom_snapshots = []
        try:
            # Initial snapshot
            dom_snapshots.append(await _capture_dom_snapshot(self._page))

            # Pre-check: already visible?
            if await self._page.locator(self._target_locator).is_visible():
                return _strategy_result(
                    found=True,
                    steps_taken=0,
                    pathway_summary="already visible",
                    dom_snapshots=dom_snapshots,
                )

            tabs = await self._page.get_by_role("tab").all()
            if not tabs:
                logger.info("[%s] ClickSiblingTab: no tab elements found.", self._run_id)
                return _strategy_result(found=False, steps_taken=0, dom_snapshots=dom_snapshots)

            for tab in tabs:
                # Skip currently active tab
                try:
                    selected = await tab.get_attribute("aria-selected")
                    if selected == "true":
                        continue
                except Exception:
                    pass

                try:
                    tab_name = ""
                    try:
                        tab_name = await tab.inner_text()
                    except Exception:
                        pass

                    # Get selector for macro synthesis
                    selector = await tab.evaluate(
                        "el => el.getAttribute('data-vqa-id') ? `[data-vqa-id='${el.getAttribute('data-vqa-id')}']` : (el.id ? `#${el.id}` : el.tagName.toLowerCase())"
                    )

                    before_count = dom_snapshots[-1]["element_count"]

                    await tab.click()
                    steps += 1

                    # Capture after state
                    snapshot = await _capture_dom_snapshot(self._page)
                    dom_snapshots.append(snapshot)
                    
                    dom_delta = before_count != snapshot["element_count"]

                    action_log.append({
                        "type": "click",
                        "selector": selector,
                        "name": tab_name,
                        "dom_delta_detected": dom_delta,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                    is_vis = await self._page.locator(self._target_locator).is_visible()
                    if is_vis:
                        logger.info(
                            "[%s] ClickSiblingTab: found after clicking tab '%s' (step %d).",
                            self._run_id,
                            tab_name,
                            steps,
                        )
                        return _strategy_result(
                            found=True,
                            steps_taken=steps,
                            pathway_summary=f"click_tab[{tab_name!r}] → element visible",
                            action_log=action_log,
                            dom_snapshots=dom_snapshots,
                        )
                except Exception as tab_exc:
                    logger.debug(
                        "[%s] ClickSiblingTab: tab click error %s (continuing).",
                        self._run_id,
                        tab_exc,
                    )
                    steps += 1
                    continue

            return _strategy_result(
                found=False, 
                steps_taken=steps, 
                action_log=action_log, 
                dom_snapshots=dom_snapshots
            )

        except Exception as exc:
            logger.warning("[%s] ClickSiblingTab exception: %s", self._run_id, exc)
            return _strategy_result(
                found=False, 
                steps_taken=steps, 
                error_message=str(exc),
                action_log=action_log,
                dom_snapshots=dom_snapshots
            )


# ---------------------------------------------------------------------------
# Macro Synthesis & Registry (Phase 2 & 3)
# ---------------------------------------------------------------------------


class MacroSynthesizer:
    """
    Synthesizes successful exploration sequences into re-usable macros.
    (TASK-092 Phase 2).
    """

    @staticmethod
    def synthesize(outcome: dict) -> dict | None:
        """
        Convert a successful ExplorationOutcome into a re-usable macro.
        
        Abstracts raw Playwright steps (clicks, scrolls) into a structured
        sequence that the Planner can use as a high-level recipe.
        """
        if not outcome.get("found") or not outcome.get("action_log"):
            return None

        target = outcome.get("target_element", "unknown_element")
        # Sanitize name for ID
        safe_name = re.sub(r"[^a-z0-9]", "_", target.lower())[:40]
        macro_id = f"macro_{safe_name}_{datetime.now().strftime('%m%d_%H%M')}"

        steps = []
        for action in outcome["action_log"]:
            step = {
                "action": action["type"],
                "timestamp": action.get("timestamp"),
            }
            if action["type"] == "click":
                step["selector"] = action.get("selector")
                step["name"] = action.get("name")
            elif action["type"] == "scroll":
                step["value"] = action.get("value")
            
            steps.append(step)

        return {
            "id": macro_id,
            "name": f"Discover {target}",
            "description": f"Learned sequence to reveal '{target}' via {outcome.get('strategy_used')}.",
            "target_element_hint": outcome.get("target_element_hint", target),
            "strategy_used": outcome.get("strategy_used"),
            "steps": steps,
            "verification": {
                "type": "element_visible",
                "selector": outcome.get("pathway_summary", "").split(" → ")[-1],
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "success_count": 1,
        }


class MacroRegistry:
    """
    Persistent registry for learned macros (TASK-092 Phase 3).
    Stores macros in storage/learned_workflows.json.
    """

    def __init__(self, file_path: str = "storage/learned_workflows.json") -> None:
        self._file_path = file_path
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        if not os.path.exists(self._file_path):
            with open(self._file_path, "w") as f:
                json.dump({"macros": []}, f, indent=2)

    def register(self, macro: dict) -> bool:
        """Add a new macro to the registry or update success count if exists."""
        try:
            with open(self._file_path, "r") as f:
                data = json.load(f)
            
            # Check for duplicate by target hint and steps
            for existing in data["macros"]:
                if (existing["target_element_hint"] == macro["target_element_hint"] and 
                    len(existing["steps"]) == len(macro["steps"])):
                    existing["success_count"] += 1
                    existing["last_used"] = datetime.now(timezone.utc).isoformat()
                    break
            else:
                macro["last_used"] = macro["created_at"]
                data["macros"].append(macro)

            with open(self._file_path, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error("Failed to register macro: %s", e)
            return False

    def list_macros(self) -> list[dict]:
        """Return all registered macros."""
        try:
            with open(self._file_path, "r") as f:
                return json.load(f).get("macros", [])
        except Exception:
            return []


# ---------------------------------------------------------------------------
# ExplorationRunner
# ---------------------------------------------------------------------------


class ExplorationRunner:
    """
    Autonomous Exploration Mode — inline sub-agent called from ``evaluator_node``.

    Dispatches three Playwright strategies in cost-ascending order with a global
    step budget.  All exceptions are caught; run() never raises to the caller.

    Phase 2 Strategy Order:
      1. scroll_to_reveal        — lowest overhead
      2. expand_collapsed_parent — medium overhead
      3. click_sibling_tab       — medium overhead

    Usage (Phase 4 — evaluator_node wiring)::

        from backend.engine.exploration_runner import ExplorationRunner

        _explorer = ExplorationRunner(state=state, run_id=run_id)
        if await _explorer.should_activate():
            _result = await _explorer.run(page=page_ref)
            if _result["found"]:
                return {
                    "_next_node": "planner",
                    "exploration_attempted": True,
                    "exploration_outcomes": [_result["outcome"]],
                    "agent_critique": f"🔍 EXPLORATION SUCCEEDED: {_result['pathway_summary']}",
                    "retry_count": 0,
                    "last_error": "",
                }
            exploration_context = f"🔍 EXPLORATION FAILED: {_result['reason']}. "
        # Fall through to human_takeover
    """

    def __init__(self, state: "VQAState", run_id: str) -> None:
        self._state = state
        self._run_id = run_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def should_activate(self) -> bool:
        """
        Returns True only when all five activation gates pass:
          1. ENABLE_EXPLORATION_MODE feature flag is True
          2. debugger_attempted = True
          3. exploration_attempted = False (re-entry guard)
          4. failure_type is explorable (not AUTH/STRICT_MODE/INTERCEPTED/etc.)
          5. ac_step_action_fail_count >= EXPLORATION_MIN_DOM_FAILURES
        """
        state = self._state

        # Gate 1 — feature flag
        if not settings.enable_exploration_mode:
            logger.debug("[%s] Exploration Mode disabled by feature flag.", self._run_id)
            return False

        # Gate 2 — debugger must have already been attempted
        if not state.get("debugger_attempted", False):
            logger.debug("[%s] Exploration skipped: debugger not yet attempted.", self._run_id)
            return False

        # Gate 3 — prevent re-entry
        if state.get("exploration_attempted", False):
            logger.debug("[%s] Exploration skipped: already attempted this step.", self._run_id)
            return False

        # Gate 4 — failure type must be explorable
        failure_type = state.get("failure_type", "") or ""
        if failure_type in EXPLORATION_BLOCKED_FAILURE_TYPES:
            logger.debug(
                "[%s] Exploration skipped: failure type '%s' is not explorable.",
                self._run_id,
                failure_type,
            )
            return False

        # Gate 5 — minimum fail count threshold
        action_fail_count = state.get("ac_step_action_fail_count", 0)
        if action_fail_count < settings.exploration_min_dom_failures:
            logger.debug(
                "[%s] Exploration skipped: action_fail_count=%d < threshold=%d.",
                self._run_id,
                action_fail_count,
                settings.exploration_min_dom_failures,
            )
            return False

        logger.info(
            "[%s] Exploration Mode ACTIVATING: debugger_attempted=True, failure_type='%s', action_fail_count=%d.",
            self._run_id,
            failure_type,
            action_fail_count,
        )
        return True

    async def run(self, page: Any) -> dict:
        """
        Execute the exploration loop with all three strategies.

        Dispatches strategies in order: scroll → expand → tab.
        Respects the global ``settings.exploration_max_steps`` budget.
        Catches all exceptions — never raises to the caller.

        Returns
        -------
        dict with keys: found, reason, pathway_summary, outcome (ExplorationOutcome)
        """
        ac_step_index = self._state.get("ac_step_index", 0)
        target_element = self._current_target_element()
        max_steps = settings.exploration_max_steps
        total_steps = 0
        target_locator = self._build_target_locator()

        strategies = [
            (
                "scroll_to_reveal",
                ScrollToRevealStrategy(
                    page=page,
                    target_locator=target_locator,
                    max_scroll_px=max(300, (max_steps // 3) * _SCROLL_INCREMENT_PX),
                    scroll_increment=_SCROLL_INCREMENT_PX,
                    run_id=self._run_id,
                ),
            ),
            (
                "expand_collapsed_parent",
                ExpandCollapsedParentStrategy(
                    page=page,
                    target_locator=target_locator,
                    run_id=self._run_id,
                ),
            ),
            (
                "click_sibling_tab",
                ClickSiblingTabStrategy(
                    page=page,
                    target_locator=target_locator,
                    run_id=self._run_id,
                ),
            ),
        ]

        try:
            for strategy_name, strategy in strategies:
                if total_steps >= max_steps:
                    logger.info(
                        "[%s] ExplorationRunner: budget exhausted (%d/%d steps). Stopping.",
                        self._run_id,
                        total_steps,
                        max_steps,
                    )
                    break

                logger.info(
                    "[%s] ExplorationRunner: trying '%s' (used %d/%d steps).",
                    self._run_id,
                    strategy_name,
                    total_steps,
                    max_steps,
                )
                strat_result = await strategy.execute()
                total_steps += strat_result.get("steps_taken", 0)

                if strat_result["found"]:
                    pathway = strat_result.get("pathway_summary", "")
                    logger.info(
                        "[%s] ExplorationRunner: SUCCESS via '%s'. Pathway: %s",
                        self._run_id,
                        strategy_name,
                        pathway,
                    )
                    outcome: dict = {
                        "ac_step_index": ac_step_index,
                        "strategy_used": strategy_name,
                        "steps_taken": total_steps,
                        "found": True,
                        "kb_injected": False,  # Phase 3 sets this to True if registry succeeds
                        "target_element": target_element,
                        "pathway_summary": pathway,
                        "error_message": "",
                        "action_log": strat_result.get("action_log", []),
                        "dom_snapshots": strat_result.get("dom_snapshots", []),
                    }

                    # TASK-092 Phase 4: Macro Synthesis & Registration
                    macro = MacroSynthesizer.synthesize(outcome)
                    if macro:
                        registry = MacroRegistry()
                        if registry.register(macro):
                            logger.info("[%s] ExplorationRunner: Macro registered: %s", self._run_id, macro["id"])
                            outcome["kb_injected"] = True

                    return {
                        "found": True,
                        "reason": f"Element found via {strategy_name}.",
                        "pathway_summary": pathway,
                        "outcome": outcome,
                    }

            # All strategies exhausted
            logger.info(
                "[%s] ExplorationRunner: all strategies exhausted (%d steps). Not found.",
                self._run_id,
                total_steps,
            )
            outcome = {
                "ac_step_index": ac_step_index,
                "strategy_used": "all_failed",
                "steps_taken": total_steps,
                "found": False,
                "kb_injected": False,
                "target_element": target_element,
                "pathway_summary": "",
                "error_message": "All exploration strategies exhausted without finding target.",
            }
            return {
                "found": False,
                "reason": "Exploration exhausted all strategies without finding the target element.",
                "pathway_summary": "",
                "outcome": outcome,
            }

        except Exception as exc:
            logger.error(
                "[%s] ExplorationRunner.run() unexpected exception: %s",
                self._run_id,
                exc,
            )
            outcome = {
                "ac_step_index": ac_step_index,
                "strategy_used": "error",
                "steps_taken": total_steps,
                "found": False,
                "kb_injected": False,
                "target_element": target_element,
                "pathway_summary": "",
                "error_message": str(exc),
            }
            return {
                "found": False,
                "reason": f"Exploration aborted due to exception: {exc}",
                "pathway_summary": "",
                "outcome": outcome,
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _current_target_element(self) -> str:
        """Extract a human-readable name for the element currently being sought."""
        state = self._state
        ac_step_index = state.get("ac_step_index", 0)
        try:
            steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
            if steps and ac_step_index < len(steps):
                return steps[ac_step_index][:80]
        except Exception:
            pass
        critique = state.get("agent_critique", "") or ""
        if critique:
            return critique[:60]
        return f"AC step {ac_step_index}"

    def _build_target_locator(self) -> str:
        """
        Derive a locator string for the target element from the last known error context.
        Falls back to a generic visible-element selector.
        """
        last_error = self._state.get("last_error", "") or ""
        if last_error:
            m = re.search(r"['\"]([^'\"]{3,80})['\"]", last_error)
            if m:
                return f"text={m.group(1)}"
        target = self._current_target_element()
        if target and not target.startswith("AC step"):
            return f"text={target[:50]}"
        return "*[aria-label], button, [role='button'], a"
