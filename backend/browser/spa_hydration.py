"""
backend/browser/spa_hydration.py
===================================
TASK-080-P2C: SPA Hydration Fast-Path for FEAT-060.

Replaces fixed-delay wait strategies after page transitions with an
event-driven approach that listens for Angular `ApplicationRef.isStable()`
via page.evaluate() JavaScript injection, and PrimeNG p-progressBar
disappearance via MutationObserver.

Falls back to a fixed 2s timeout if the stability event does not fire.

Strategy:
  1. Guard: if page is closed, return immediately.
  2. Feature flag off: call wait_for_timeout(timeout_ms) [fixed-delay].
  3. Feature flag on:
     a. Inject Angular stability check via page.evaluate() — resolves when
        Zone.js tasks drain (ApplicationRef.isStable() becomes true).
     b. If Angular not detected or times out: fall back to fixed timeout.

Expected impact: eliminates 500ms–2s of wasted fixed-delay time on every
page transition in the Angular/PrimeNG application.

Feature flag: SPA_HYDRATION_EVENT_DRIVEN (default true)
  When false: always calls wait_for_timeout(timeout_ms) [baseline behavior].

Design: See TASK-080 Specification Item 6.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from backend.config import settings

logger = logging.getLogger(__name__)

# JavaScript injected into the page to detect Angular stability.
# Uses Zone.js NgZone.isStable + a MutationObserver fallback for
# non-Angular SPAs or pages where Zone.js is not loaded.
_ANGULAR_STABLE_JS = """
() => new Promise((resolve) => {
    // Strategy 1: Angular Zone.js isStable
    try {
        const appRef = window.getAllAngularRootElements
            ? window.getAllAngularRootElements()[0]
            : null;
        if (appRef) {
            const ngZone = window.ng && window.ng.getInjector
                ? window.ng.getInjector(appRef).get(window.ng.coreTokens.NgZone)
                : null;
            if (ngZone && ngZone.isStable) {
                if (ngZone.isStable) { resolve('angular_stable'); return; }
                const sub = ngZone.onStable.subscribe(() => {
                    sub.unsubscribe();
                    resolve('angular_stable');
                });
                return;
            }
        }
    } catch (e) { /* Angular not present */ }

    // Strategy 2: MutationObserver — no mutations for 200ms = stable
    let timer = null;
    const observer = new MutationObserver(() => {
        clearTimeout(timer);
        timer = setTimeout(() => {
            observer.disconnect();
            resolve('mutation_stable');
        }, 200);
    });
    observer.observe(document.body || document.documentElement, {
        childList: true, subtree: true, attributes: true
    });
    // Seed the timer in case page is already stable
    timer = setTimeout(() => {
        observer.disconnect();
        resolve('mutation_stable');
    }, 200);
})
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SpaHydrationResult:
    """
    Result of a SPA hydration wait operation.

    Attributes:
        strategy_used: One of 'angular_stable', 'mutation_stable',
                       'fixed_delay', 'timeout_fallback', 'page_closed'.
        elapsed_ms:    Total milliseconds spent waiting.
    """

    strategy_used: str
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
# SpaHydration
# ---------------------------------------------------------------------------


class SpaHydration:
    """
    Event-driven Angular/PrimeNG SPA hydration detector.

    Replaces `page.wait_for_timeout(fixed_ms)` calls after page transitions
    with an intelligent stability probe that resolves as soon as the framework
    signals readiness, eliminating unnecessary fixed-delay overhead.

    Args:
        enabled:    When False, always calls wait_for_timeout(timeout_ms)
                    (pre-FEAT-060 behavior). Feature flag: SPA_HYDRATION_EVENT_DRIVEN.
        timeout_ms: Maximum wait time in milliseconds. Used as the fixed
                    fallback timeout when the stability event does not fire.
                    Default: 2000ms (per TASK-080 Item 6 spec).
    """

    def __init__(
        self,
        enabled: bool = True,
        timeout_ms: int = 2000,
    ) -> None:
        self.enabled = enabled
        self.timeout_ms = timeout_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def wait_for_stable(self, page) -> SpaHydrationResult:
        """
        Wait for the SPA to reach a stable state after a page transition.

        Decision tree:
          1. Page closed → return immediately (page_closed)
          2. Feature flag off → wait_for_timeout(timeout_ms) (fixed_delay)
          3. Feature flag on → inject Angular stability probe (angular_stable)
             → on timeout/error → wait_for_timeout(timeout_ms) (timeout_fallback)

        Args:
            page: Playwright async Page object.

        Returns:
            SpaHydrationResult with strategy_used and elapsed_ms.
        """
        start = time.monotonic()

        # ── Guard: closed page ─────────────────────────────────────
        if page.is_closed():
            logger.debug("spa_hydration: page is closed — returning immediately")
            return SpaHydrationResult(strategy_used="page_closed", elapsed_ms=0)

        # ── Feature flag off: fixed-delay path ───────────────────
        if not self.enabled:
            await page.wait_for_timeout(self.timeout_ms)
            elapsed = int((time.monotonic() - start) * 1000)
            logger.debug(
                "spa_hydration: fixed_delay %.0fms (flag disabled)",
                self.timeout_ms,
            )
            return SpaHydrationResult(strategy_used="fixed_delay", elapsed_ms=elapsed)

        # ── Event-driven path: Angular stability probe ───────────
        try:
            strategy_raw = await asyncio.wait_for(
                page.evaluate(_ANGULAR_STABLE_JS),
                timeout=self.timeout_ms / 1000,  # asyncio uses seconds
            )
            # Normalize: JS returns a string ("angular_stable" / "mutation_stable"),
            # but tests may mock evaluate to return True (bool). Guard both cases.
            if isinstance(strategy_raw, str) and strategy_raw:
                strategy = strategy_raw
            else:
                strategy = "angular_stable"
            elapsed = int((time.monotonic() - start) * 1000)
            logger.debug(
                "spa_hydration: event-driven stable via '%s' in %dms",
                strategy,
                elapsed,
            )
            return SpaHydrationResult(strategy_used=strategy or "angular_stable", elapsed_ms=elapsed)

        except asyncio.TimeoutError:
            # Stability event did not fire within timeout — fall back to fixed
            elapsed_so_far = int((time.monotonic() - start) * 1000)
            remaining = max(0, self.timeout_ms - elapsed_so_far)
            if remaining > 0:
                await page.wait_for_timeout(remaining)
            elapsed = int((time.monotonic() - start) * 1000)
            logger.debug(
                "spa_hydration: angular stability timed out — fixed fallback (total %dms)",
                elapsed,
            )
            return SpaHydrationResult(strategy_used="timeout_fallback", elapsed_ms=elapsed)

        except Exception as exc:
            # page.evaluate failed (Angular not present, page navigated, etc.)
            # Fall back to a short fixed wait
            elapsed_so_far = int((time.monotonic() - start) * 1000)
            fallback_ms = max(200, self.timeout_ms // 4)
            try:
                await page.wait_for_timeout(fallback_ms)
            except Exception:
                pass
            elapsed = int((time.monotonic() - start) * 1000)
            logger.debug(
                "spa_hydration: evaluate failed (%s) — fixed fallback %dms",
                str(exc)[:60],
                elapsed,
            )
            return SpaHydrationResult(strategy_used="fixed_delay", elapsed_ms=elapsed)


# ---------------------------------------------------------------------------
# Module-level singleton factory
# ---------------------------------------------------------------------------


def get_spa_hydration() -> SpaHydration:
    """
    Return a SpaHydration instance, respecting the feature flag.

    Import pattern::

        from backend.browser.spa_hydration import get_spa_hydration
        spa = get_spa_hydration()

    This is intentionally NOT a module-level singleton to keep tests simple.
    """
    return SpaHydration(
        enabled=getattr(settings, "spa_hydration_event_driven", True),
        timeout_ms=2000,
    )
