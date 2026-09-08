"""
backend/kb/prefetcher.py
=========================
TASK-080-P1D: Speculative KB Pre-fetch for FEAT-060.

Pre-fetches KB context for the NEXT AC step while the current step is
being executed. Uses asyncio.create_task() to run the KB query in a
thread pool executor (since LocalKnowledgeBase.query_with_expansion is
synchronous), eliminating KB lookup latency from the critical path.

Architecture:
  1. After planner emits action for step N, executor calls:
       task = prefetcher.start_prefetch(step_index=N+1, steps=test_plan_steps)
  2. Executor carries out the browser action (e.g. click, fill)
  3. Before next planner call, caller does:
       context = await prefetcher.get_or_fetch(step_index=N+1, steps=...)
  4. Cache hit: returns the prefetched context immediately (~0ms)
     Cache miss: falls back to synchronous KB call

Feature flag: SPECULATIVE_PREFETCH_ENABLED (default true)
  When false: start_prefetch() returns None, get_or_fetch() calls KB directly.

Design: See TASK-080 Specification Item 4 (Phase 1D).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PrefetchResult data class
# ---------------------------------------------------------------------------


@dataclass
class PrefetchResult:
    """
    Result of a speculative KB pre-fetch.

    Attributes:
        step_index: The step index this result was pre-fetched for.
        context: The KB context string, or empty string if no match found.
        error: Exception message if the prefetch task failed. None on success.
    """

    step_index: int
    context: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# KBPrefetcher
# ---------------------------------------------------------------------------


class KBPrefetcher:
    """
    Speculative KB pre-fetch engine for the vQA planner.

    Fires asyncio.create_task() to pre-load KB context for the next AC step
    while the current browser action is in flight. This moves KB lookup
    off the critical path, eliminating ~150ms of synchronous TF-IDF
    retrieval from each planner iteration.

    The KB client (LocalKnowledgeBase) is synchronous (TF-IDF + BM25).
    We run it in the default asyncio thread pool executor to avoid blocking
    the event loop.

    Args:
        kb_client: Any object with query_with_expansion(text) → str or
                   Coroutine[str]. Accepts both sync and async clients.
        enabled: Feature flag. When False, start_prefetch() returns None.
    """

    def __init__(
        self,
        kb_client: Any,
        enabled: bool = True,
    ) -> None:
        self.kb_client = kb_client
        self.enabled = enabled
        # Cache: step_index → PrefetchResult
        self._cache: dict[int, PrefetchResult] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_prefetch(
        self,
        step_index: int,
        steps: list[dict],
    ) -> asyncio.Task | None:
        """
        Schedule a background KB pre-fetch for the given step index.

        Must be called while the event loop is running (inside an async
        context). The returned Task runs concurrently in the background —
        do NOT await it immediately; let it run while the browser action
        executes.

        Args:
            step_index: Index of the step to pre-fetch KB context for.
                        Typically N+1 (the next step after the current one).
            steps: The full ordered list of test plan step dicts.
                   Each dict must contain a ``goal`` key (the step text).

        Returns:
            asyncio.Task if feature flag is on and step exists.
            None if feature flag is off or step_index is out of bounds.
        """
        if not self.enabled:
            return None

        if step_index < 0 or not steps or step_index >= len(steps):
            return None

        # Return early if already cached
        if step_index in self._cache:
            logger.debug(
                "kb_prefetcher: step %d already in cache — skipping prefetch",
                step_index,
            )
            return None

        step_goal = steps[step_index].get("goal", "") if steps else ""
        if not step_goal:
            return None

        task = asyncio.create_task(
            self._prefetch_task(step_index=step_index, step_goal=step_goal),
            name=f"kb_prefetch_step_{step_index}",
        )

        logger.debug(
            "kb_prefetcher: scheduled background fetch for step %d — '%s'",
            step_index,
            step_goal[:60],
        )

        return task

    async def get_or_fetch(
        self,
        step_index: int,
        steps: list[dict],
    ) -> PrefetchResult:
        """
        Return cached prefetch result, or fetch synchronously on cache miss.

        Call this immediately before the planner needs the KB context for
        step N. If start_prefetch(N) was called earlier and the task has
        completed, this returns ~immediately from cache. If the task hasn't
        finished or wasn't scheduled, this performs a blocking KB query
        via the thread pool.

        Args:
            step_index: The step to get KB context for.
            steps: The full test plan step list.

        Returns:
            PrefetchResult with context string.
        """
        # Cache hit — prefetch already completed
        if step_index in self._cache:
            logger.debug(
                "kb_prefetcher: cache HIT for step %d",
                step_index,
            )
            return self._cache[step_index]

        # Cache miss — fall back to synchronous fetch
        logger.debug(
            "kb_prefetcher: cache MISS for step %d — falling back to sync fetch",
            step_index,
        )

        step_goal = steps[step_index].get("goal", "") if (steps and 0 <= step_index < len(steps)) else ""
        return await self._prefetch_task(step_index=step_index, step_goal=step_goal)

    def get_cached(self, step_index: int) -> PrefetchResult | None:
        """
        Return the cached PrefetchResult for a step, or None on miss.

        Args:
            step_index: The step to look up.

        Returns:
            PrefetchResult if cached, None if not.
        """
        return self._cache.get(step_index)

    def clear_cache(self) -> None:
        """Clear all cached prefetch results. Call between test runs."""
        self._cache.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _prefetch_task(self, step_index: int, step_goal: str) -> PrefetchResult:
        """
        Run the KB query in the thread pool and cache the result.

        Errors are caught and stored in PrefetchResult.error — they do not
        propagate to the caller, ensuring a background prefetch failure
        never crashes the main execution loop.
        """
        try:
            if not step_goal:
                result = PrefetchResult(step_index=step_index, context="", error=None)
                self._cache[step_index] = result
                return result

            # Detect if kb_client.query_with_expansion is a coroutine or sync
            qwe = self.kb_client.query_with_expansion
            if asyncio.iscoroutinefunction(qwe):
                # Async client (e.g., mock in tests)
                context = await qwe(step_goal)
            else:
                # Sync client — run in thread pool to avoid blocking event loop
                loop = asyncio.get_event_loop()
                context = await loop.run_in_executor(None, qwe, step_goal)

            result = PrefetchResult(
                step_index=step_index,
                context=context or "",
                error=None,
            )

            logger.debug(
                "kb_prefetcher: step %d prefetch complete — %d chars",
                step_index,
                len(result.context),
            )

        except Exception as exc:
            err_msg = str(exc)[:200]
            logger.warning(
                "kb_prefetcher: step %d prefetch FAILED (non-fatal): %s",
                step_index,
                err_msg,
            )
            result = PrefetchResult(
                step_index=step_index,
                context="",
                error=err_msg,
            )

        self._cache[step_index] = result
        return result
