"""
backend/engine/speculative_planner.py
========================================
SpeculativePlanner — Background Plan Pre-Generation for Next AC Step.

While step N executes in Playwright, SpeculativePlanner spawns a background
asyncio.Task to generate the plan for step N+1. If step N succeeds, the
plan is applied immediately — eliminating one LLM round-trip per step.
If step N fails (changes expected page state), the speculative plan is
discarded and a fresh plan is generated for the corrected state.

Key Design Decisions:
- start_prefetch(): spawns an asyncio.Task — non-blocking
- get_plan(): returns the cached plan IF ready, else None (never blocks)
- discard(): cancels the in-flight task + wipes cached plan (poison signal)
- Error handling: LLM failures are swallowed — get_plan() returns None gracefully

Feature flag: `enabled` param (driven by settings.speculative_planning_enabled).
When disabled, all methods are no-ops / return None.

AC Coverage:
- AC-EDGE-1: Speculative plan discarded on step N failure (discard() called)
- AC-ENTRY-1: enabled=False → no background tasks spawned, zero regression
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)


class SpeculativePlanner:
    """
    Generates plans speculatively for the next AC step while the current step executes.

    Usage
    -----
    >>> planner = SpeculativePlanner(enabled=True, llm_caller=my_llm_fn)
    >>>
    >>> # Step N begins executing — pre-fetch plan for step N+1
    >>> planner.start_prefetch(step_index=N + 1, context={...})
    >>>
    >>> # Step N succeeds — retrieve the speculative plan for N+1
    >>> plan = await planner.get_plan(step_index=N + 1)
    >>> if plan:
    ...     apply_speculative_plan(plan)  # skip one LLM round-trip
    >>> else:
    ...     plan = await generate_plan_fresh(context)  # fallback
    >>>
    >>> # OR: Step N fails — discard the speculative plan
    >>> planner.discard(step_index=N)  # poisoned — state changed
    """

    def __init__(
        self,
        enabled: bool = True,
        llm_caller: Optional[Callable[[dict], Coroutine[Any, Any, dict]]] = None,
    ) -> None:
        """
        Initialize SpeculativePlanner.

        Args:
            enabled: Feature flag. When False, all methods are no-ops.
            llm_caller: Async callable(context: dict) → plan: dict.
                        Used to generate speculative plans in the background.
        """
        self._enabled = enabled
        self._llm_caller = llm_caller
        self._pending_task: Optional[asyncio.Task] = None
        self._cached_plan: Optional[dict] = None
        self._prefetch_step_index: Optional[int] = None

    def start_prefetch(self, step_index: int, context: dict) -> None:
        """
        Start a background asyncio.Task to generate the plan for step N.

        Non-blocking. If a previous prefetch is still running, it is cancelled
        first (only one speculative prefetch is active at a time).

        Args:
            step_index: The step index to pre-generate a plan for.
            context: Planning context (ARIA state, AC step description, etc.)
        """
        if not self._enabled:
            logger.debug("SpeculativePlanner: disabled — skipping prefetch for step %d", step_index)
            return

        # Cancel any in-flight prefetch before starting a new one
        self._cancel_pending()

        self._prefetch_step_index = step_index
        self._cached_plan = None

        logger.debug("SpeculativePlanner: starting prefetch for step %d", step_index)
        self._pending_task = asyncio.ensure_future(
            self._run_prefetch(step_index, context)
        )

    async def get_plan(self, step_index: int) -> Optional[dict]:
        """
        Return the speculative plan for step_index if it is ready.

        This method NEVER blocks. If the prefetch is still running,
        returns None immediately (the caller falls back to synchronous generation).

        Args:
            step_index: The step index to retrieve the plan for.

        Returns:
            The cached plan dict, or None if not ready / wrong index / disabled.
        """
        if not self._enabled:
            return None

        if self._prefetch_step_index != step_index:
            logger.debug(
                "SpeculativePlanner: get_plan(%d) — prefetch is for step %s (mismatch)",
                step_index,
                self._prefetch_step_index,
            )
            return None

        # Check if the task is done without awaiting it
        if self._pending_task is not None and not self._pending_task.done():
            logger.debug(
                "SpeculativePlanner: get_plan(%d) — prefetch still running, returning None",
                step_index,
            )
            return None

        if self._cached_plan is not None:
            logger.info(
                "SpeculativePlanner: get_plan(%d) — returning cached plan (action=%s)",
                step_index,
                self._cached_plan.get("action", "unknown"),
            )
            return self._cached_plan

        return None

    def discard(self, step_index: int) -> None:
        """
        Discard the speculative plan — called when step N fails.

        Cancels the in-flight prefetch task and wipes the cached plan.
        After this call, get_plan() returns None for any step index until
        start_prefetch() is called again for the corrected state.

        This is the "poison signal" in AC-EDGE-1:
            If step N fails and changes expected page state →
            the speculative plan for step N+1 is invalid → discard.

        Args:
            step_index: The index of the step that failed (for logging).
        """
        if not self._enabled:
            return

        logger.info(
            "SpeculativePlanner: discard() called — step %d failed, poisoning prefetch for step %s",
            step_index,
            self._prefetch_step_index,
        )
        self._cancel_pending()
        self._cached_plan = None
        self._prefetch_step_index = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_prefetch(self, step_index: int, context: dict) -> None:
        """
        Execute the LLM call and cache the result.

        Errors are caught and logged — never propagated to the caller.
        After completion, _cached_plan is set (or remains None on error).
        """
        try:
            if self._llm_caller is None:
                logger.warning("SpeculativePlanner: no llm_caller configured")
                return
            plan = await self._llm_caller(context)
            # Only cache if this prefetch hasn't been discarded
            if self._prefetch_step_index == step_index:
                self._cached_plan = plan
                logger.debug(
                    "SpeculativePlanner: prefetch complete for step %d (action=%s)",
                    step_index,
                    plan.get("action", "unknown") if isinstance(plan, dict) else "?",
                )
        except asyncio.CancelledError:
            logger.debug("SpeculativePlanner: prefetch for step %d was cancelled", step_index)
            raise  # Must re-raise CancelledError
        except Exception as e:
            logger.warning(
                "SpeculativePlanner: LLM call failed for step %d: %s",
                step_index,
                e,
            )
            # Swallow error — get_plan() will return None (caller uses synchronous path)

    def _cancel_pending(self) -> None:
        """Cancel and clear any pending prefetch task."""
        if self._pending_task is not None and not self._pending_task.done():
            self._pending_task.cancel()
            logger.debug("SpeculativePlanner: cancelled pending prefetch task")
        self._pending_task = None
