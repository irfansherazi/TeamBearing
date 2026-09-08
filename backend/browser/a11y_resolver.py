"""
a11y_resolver.py — Accessibility Tree Locator Resolver
=======================================================
Module: backend/browser/a11y_resolver.py
Feature: accessibility-tree-grounding

Implements the a11y-first locator resolution chain that runs BEFORE
the existing CSS/PrimeNG selector path in ``executor.py:_resolve_locator``.

Resolution chain (three branches):

1. **Legacy fast-path** (``aria_role is None``) — immediate fall-through to
   the existing ``_resolve_locator`` path; zero behavior change for recorded
   tests that lack ARIA fields.  Resolution path: ``"selector_only_legacy"``.

2. **A11y probe** (``aria_role`` is populated) — two-tier:
   - Tier 1 (exact): ``page.get_by_role(role, name=name).count()``
     - 1 match → ``"a11y_primary"``
     - ≥ 2 matches → ``"selector_fallback_ambiguous"`` (skip normalization;
       normalization cannot reduce matches, only increase them)
   - Tier 2 (normalized, only on 0 matches): builds an anchored
     ``re.escape``-safe regex from the NFC-casefolded-stripped name and
     retries.  Result: ``"a11y_normalized"`` (1), ``"selector_fallback_ambiguous"``
     (≥2), or ``"selector_fallback"`` (0).
   - Any exception during the probe → ``"selector_fallback_error"``

3. **CSS/selector fallback** — the existing ``_resolve_locator`` function
   is called when the a11y probe fails.  If that also raises → ``"cv_fallback_required"``.

Architecture (FEAT-037 precedent):
- Mirrors ``backend/browser/cv_resolver.py`` (sibling module).
- Accepts primitives (``aria_role``, ``aria_name``), NOT the full ``TestPlanStep``
  model, to avoid ``browser → engine`` schema import cycles.
- Caller (``executor.py``) unpacks ``step.aria_role`` / ``step.aria_name`` at
  the call site.

Design references:
  - Architecture creative: memory-bank/creative/accessibility-tree-grounding-architecture.md
  - Algorithm creative:    memory-bank/creative/accessibility-tree-grounding-algorithm.md
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical resolution-path string set
# (must match ExecutionStep.locator_strategy vocabulary — Phase 2 threads these)
# ---------------------------------------------------------------------------

ResolutionPath = Literal[
    "a11y_primary",
    "a11y_normalized",
    "selector_fallback",
    "selector_fallback_ambiguous",
    "selector_fallback_error",
    "selector_only_legacy",
    "cv_fallback_required",
]

# ---------------------------------------------------------------------------
# Name normalization helpers (Algorithm Decision 1)
# ---------------------------------------------------------------------------

# PrimeNG chevrons, arrows, and ellipsis glyphs commonly appended to
# accessible names by the component library.  Extend if field data shows
# new variants.
_TRAILING_ICON_CHARS: str = "▾▼◂▸►◆●…⋯"

# Three-dot literal and unicode ellipsis (U+2026) — separate from icon chars
# so we can strip both after removing the icon glyph.
_ELLIPSIS_LITERALS: tuple[str, ...] = ("...", "…")


def _normalize_name(name: str) -> str:
    """
    Deterministic normalization of an ARIA accessible name.

    Applies four transformations documented in the Algorithm creative:
    1. NFC composition (macOS Chromium occasionally emits NFD for accented chars).
    2. Strip trailing icon glyphs (▾, ▼, …) and NBSP.
    3. Strip trailing ellipsis literals (``...``, ``…``).
    4. Case-fold (handles Turkish İ, German ß, etc.).

    The function is injective on clean inputs — it only removes documented
    PrimeNG formatting noise.  It does NOT strip leading content, does NOT
    do substring matching, and NEVER alters the canonical accessible name
    for a verbatim match.

    Returns an empty string if ``name`` is falsy.
    """
    if not name:
        return ""

    # Step 1: NFC composition
    s = unicodedata.normalize("NFC", name)

    # Step 2: Strip trailing icon glyphs + standard whitespace + NBSP (\xa0)
    s = s.rstrip(_TRAILING_ICON_CHARS + " \t\n\r\xa0")

    # Step 3: Strip trailing ellipsis literals (ellipsis icon already removed above)
    for suf in _ELLIPSIS_LITERALS:
        if s.endswith(suf):
            s = s[: -len(suf)].rstrip()
            break  # only strip the outermost suffix

    # Step 4: Case-fold
    return s.casefold()


def _build_normalized_pattern(name: str) -> re.Pattern[str] | None:
    """
    Build an anchored, case-insensitive regex pattern from a normalized name.

    Returns ``None`` if the normalized form is identical to the case-fold-only
    form (meaning normalization changed nothing useful — skip the second tier
    in that case to avoid a redundant Playwright call).

    The pattern allows leading/trailing whitespace to catch minor rendering
    differences that ``_normalize_name`` already handles in the string path
    but Playwright's own name= matching may not.
    """
    norm = _normalize_name(name)
    if not norm:
        return None

    # Only build the pattern if normalization actually changed something
    # beyond a plain casefold.  Compare norm against the raw casefold
    # WITHOUT stripping — this preserves trailing whitespace as a
    # "meaningful difference" that justifies a second Playwright call.
    plain_casefold = name.casefold()
    if norm == plain_casefold.strip() and norm == plain_casefold:
        # Nothing changed from either case-fold form — skip
        return None  # nothing worth retrying

    try:
        # Anchored, case-insensitive, allows surrounding whitespace
        pattern = re.compile(
            rf"^\s*{re.escape(norm)}\s*$",
            re.IGNORECASE,
        )
        return pattern
    except re.error as exc:
        logger.warning(
            "A11Y_RESOLVER: failed to compile normalized pattern for name=%r: %s",
            name,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# A11yLocatorResolver
# ---------------------------------------------------------------------------


class A11yLocatorResolver:
    """
    Executor-side a11y-first locator resolution.

    Single public method: ``async resolve(page, aria_role, aria_name, action)``

    Returns ``(Locator | None, ResolutionPath)`` — never raises.

    Usage (called from executor._resolve_locator_with_a11y, Phase 2)::

        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role=step.aria_role,
            aria_name=step.aria_name,
            action=action,
        )
        # path is one of: a11y_primary, a11y_normalized, selector_fallback,
        #                  selector_fallback_ambiguous, selector_fallback_error,
        #                  selector_only_legacy, cv_fallback_required
    """

    async def resolve(
        self,
        page: Any,  # playwright.async_api.Page
        aria_role: str | None,
        aria_name: str | None,
        action: dict[str, Any],
        run_id: str | None = None,
    ) -> tuple[Any, ResolutionPath]:
        """
        Resolve a Playwright locator using the a11y-first chain.

        Parameters
        ----------
        page:
            The active Playwright ``Page`` object.
        aria_role:
            ARIA role string (e.g. ``"button"``, ``"textbox"``), or ``None``
            to trigger the legacy selector-only path.
        aria_name:
            ARIA accessible name string, or ``None``.  Used as the ``name=``
            argument to ``page.get_by_role()``.
        action:
            The raw LLM action dict — passed to ``_resolve_locator`` on fallback.
        run_id:
            Optional run ID for structured log correlation.

        Returns
        -------
        tuple[Locator | None, ResolutionPath]
            ``(locator, resolution_path)`` where ``resolution_path`` is one of
            the canonical strings documented in ``ResolutionPath``.
            ``locator`` is ``None`` only when ``resolution_path == "cv_fallback_required"``.
        """
        # ── Branch 3: Legacy fast-path ─────────────────────────────────────
        if aria_role is None:
            logger.debug(
                "A11Y_RESOLVER_BRANCH: path=selector_only_legacy "
                "aria_role=None run_id=%s",
                run_id,
            )
            legacy_locator = await self._css_fallback(page, action)
            return legacy_locator, "selector_only_legacy"

        # ── Branch 1 & 2: A11y probe (two-tier) ───────────────────────────
        try:
            # Tier 1: Exact match
            loc_exact = page.get_by_role(aria_role, name=aria_name)
            n_exact = await loc_exact.count()

            if n_exact == 1:
                logger.info(
                    "A11Y_RESOLVER_BRANCH: path=a11y_primary "
                    "aria_role=%s aria_name=%r run_id=%s",
                    aria_role,
                    aria_name,
                    run_id,
                )
                return loc_exact, "a11y_primary"

            if n_exact >= 2:
                # Normalization cannot reduce matches — skip Tier 2
                logger.warning(
                    "A11Y_RESOLVER_FALLBACK: reason=ambiguous n=%d "
                    "aria_role=%s aria_name=%r run_id=%s",
                    n_exact,
                    aria_role,
                    aria_name,
                    run_id,
                )
                css_loc = await self._css_fallback(page, action)
                return css_loc, "selector_fallback_ambiguous"

            # n_exact == 0 → try Tier 2 (normalized regex)
            norm_pattern = _build_normalized_pattern(aria_name or "")
            if norm_pattern is not None:
                loc_norm = page.get_by_role(aria_role, name=norm_pattern)
                n_norm = await loc_norm.count()

                if n_norm == 1:
                    logger.info(
                        "A11Y_RESOLVER_BRANCH: path=a11y_normalized "
                        "aria_role=%s aria_name=%r run_id=%s",
                        aria_role,
                        aria_name,
                        run_id,
                    )
                    return loc_norm, "a11y_normalized"

                if n_norm >= 2:
                    logger.warning(
                        "A11Y_RESOLVER_FALLBACK: reason=ambiguous_normalized n=%d "
                        "aria_role=%s aria_name=%r run_id=%s",
                        n_norm,
                        aria_role,
                        aria_name,
                        run_id,
                    )
                    css_loc = await self._css_fallback(page, action)
                    return css_loc, "selector_fallback_ambiguous"

            # Both tiers returned 0 → CSS fallback
            logger.debug(
                "A11Y_RESOLVER_FALLBACK: reason=zero_matches "
                "aria_role=%s aria_name=%r run_id=%s",
                aria_role,
                aria_name,
                run_id,
            )

        except Exception as exc:  # noqa: BLE001
            # AC-ERROR-1: probe failure must not propagate to LangGraph
            logger.warning(
                "A11Y_RESOLVER_FALLBACK: reason=probe_exception "
                "aria_role=%s aria_name=%r error=%s run_id=%s",
                aria_role,
                aria_name,
                exc,
                run_id,
            )
            css_loc = await self._css_fallback(page, action)
            return css_loc, "selector_fallback_error"

        # ── Branch 2: CSS/selector fallback ───────────────────────────────
        css_loc = await self._css_fallback(page, action)
        if css_loc is None:
            logger.warning(
                "A11Y_RESOLVER_FALLBACK: reason=css_also_failed "
                "aria_role=%s aria_name=%r run_id=%s",
                aria_role,
                aria_name,
                run_id,
            )
            return None, "cv_fallback_required"

        return css_loc, "selector_fallback"

    async def _css_fallback(
        self,
        page: Any,
        action: dict[str, Any],
    ) -> Any | None:
        """
        Attempt the existing CSS/PrimeNG selector path via ``page.locator()``.

        Uses the ``target_component`` or ``name`` field from the action dict
        as a best-effort selector when the a11y probe fails.

        Returns the locator on success, or ``None`` if the page raises.

        In Phase 2, this will be replaced by a direct call to
        ``_resolve_locator(page, action)`` from ``executor.py`` — for now
        we keep a lightweight inline implementation so the resolver is
        independently unit-testable without importing the executor.
        """
        # Phase 1: use a simple page.locator() call.
        # Phase 2 will replace this with executor._resolve_locator().
        selector = (
            action.get("target_component")
            or action.get("name")
            or ""
        )
        if not selector:
            return None
        try:
            return page.locator(selector)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "A11Y_RESOLVER: css_fallback raised for selector=%r: %s",
                selector,
                exc,
            )
            return None
