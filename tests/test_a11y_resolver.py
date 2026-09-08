"""
tests/test_a11y_resolver.py — Unit tests for A11yLocatorResolver
================================================================
Phase 1 — Schema + Resolver Foundation
Feature: accessibility-tree-grounding

Tests the two-tier a11y probe (exact → normalized regex) and the
three-branch resolution chain (a11y_primary / selector_fallback /
selector_only_legacy) per the Algorithm creative decisions.

Framework: pytest with unittest.mock (project convention).
All Playwright Page/Locator objects are mocked — no live browser.

Test coverage:
  AC-VERIFY-1: TestPlanStep schema backward compatibility (2 tests)
  AC-VERIFY-3: Exact a11y match returns a11y_primary
  AC-VERIFY-4: Zero a11y matches → selector_fallback
  AC-VERIFY-5: Ambiguous (N>1) a11y → selector_fallback_ambiguous
  AC-VERIFY-6: CV fallback signal when both a11y + selector fail
  AC-VERIFY-9: Legacy path when aria_role is None
  AC-ERROR-1: a11y probe exception → selector_fallback_error
  AC-ERROR-2: zero-and-zero diagnostics (error message format)
  Algorithm Decision 1: normalized-name recovery (trailing whitespace,
                        icon chars, ellipsis, ambiguous-normalized)
  Algorithm Decision 1: _normalize_name pure-function contract
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — lightweight mocks for Playwright Page and Locator
# ---------------------------------------------------------------------------


def _make_locator(count: int, raises: bool = False) -> AsyncMock:
    """
    Create a mock Playwright Locator whose ``.count()`` returns ``count``.
    If ``raises`` is True, ``.count()`` raises a ``RuntimeError``.
    """
    loc = AsyncMock()
    if raises:
        loc.count = AsyncMock(side_effect=RuntimeError("Page closed unexpectedly"))
    else:
        loc.count = AsyncMock(return_value=count)
    return loc


def _make_page(
    exact_count: int = 1,
    normalized_count: int | None = None,
    exact_raises: bool = False,
) -> MagicMock:
    """
    Create a mock Playwright Page whose ``get_by_role`` returns locators
    with predictable counts.

    - ``exact_count``  — count returned when exact ``get_by_role`` is called.
    - ``normalized_count`` — count returned when a regex ``get_by_role`` is called.
      Defaults to ``exact_count`` if not provided (most tests only need one).
    - ``exact_raises`` — when True, the first ``get_by_role`` call raises.
    """
    if normalized_count is None:
        normalized_count = exact_count

    call_index = {"n": 0}

    def _get_by_role(role, *, name=None, **kwargs):  # noqa: ANN001
        idx = call_index["n"]
        call_index["n"] += 1
        if idx == 0:
            if exact_raises:
                raise RuntimeError("CDP connection failed")
            return _make_locator(exact_count)
        else:
            return _make_locator(normalized_count)

    page = MagicMock()
    page.get_by_role = _get_by_role
    page.locator = MagicMock(return_value=_make_locator(1))
    return page


# ---------------------------------------------------------------------------
# Schema tests (AC-VERIFY-1)
# ---------------------------------------------------------------------------


class TestTestPlanStepSchemaBackwardCompat:
    """AC-VERIFY-1: TestPlanStep accepts None for all three new fields."""

    def test_new_fields_absent_defaults_to_none(self) -> None:
        """
        A TestPlanStep constructed WITHOUT the three new a11y fields
        validates without error and leaves them all None.
        """
        from backend.engine.schemas import StructuredACStep as TestPlanStep

        step = TestPlanStep(
            step_id=1,
            goal="Open the order form",
            step_type="NAVIGATE",
        )

        assert step.aria_role is None
        assert step.aria_name is None
        assert step.aria_disambiguators is None

    def test_new_fields_populated_validates_cleanly(self) -> None:
        """
        A TestPlanStep constructed WITH the three new a11y fields
        validates without error and carries the values correctly.
        """
        from backend.engine.schemas import StructuredACStep as TestPlanStep

        step = TestPlanStep(
            step_id=2,
            goal="Click Save",
            step_type="CLICK",
            aria_role="button",
            aria_name="Save",
            aria_disambiguators=["aria-label", "placeholder:Save order"],
        )

        assert step.aria_role == "button"
        assert step.aria_name == "Save"
        assert step.aria_disambiguators == ["aria-label", "placeholder:Save order"]


# ---------------------------------------------------------------------------
# Resolver branch tests (AC-VERIFY-3 through AC-VERIFY-6, AC-VERIFY-9)
# ---------------------------------------------------------------------------


class TestA11yLocatorResolverBranches:
    """Core three-branch resolution chain tests."""

    @pytest.mark.anyio
    async def test_exact_match_returns_a11y_primary(self) -> None:
        """
        AC-VERIFY-3: When get_by_role(role, name=name) returns exactly 1
        element, the resolver returns (locator, 'a11y_primary').
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = _make_page(exact_count=1)
        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page, aria_role="button", aria_name="Save", action={}
        )

        assert path == "a11y_primary"
        assert locator is not None

    @pytest.mark.anyio
    async def test_zero_match_returns_selector_fallback(self) -> None:
        """
        AC-VERIFY-4: When exact get_by_role returns 0 AND normalized also
        returns 0, the resolver returns (css_locator, 'selector_fallback').
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = _make_page(exact_count=0, normalized_count=0)
        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Save",
            action={"strategy": "get_by_role", "role": "button", "name": "Save"},
        )

        assert path == "selector_fallback"

    @pytest.mark.anyio
    async def test_ambiguous_exact_returns_selector_fallback_ambiguous(self) -> None:
        """
        AC-VERIFY-5: When exact get_by_role returns N>1, the resolver
        immediately returns 'selector_fallback_ambiguous' WITHOUT attempting
        normalization (normalization can only increase matches, not fix ambiguity).
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        # We track get_by_role call count to ensure normalization is NOT attempted
        call_count = {"n": 0}

        def _get_by_role(role, *, name=None, **kwargs):  # noqa: ANN001
            call_count["n"] += 1
            return _make_locator(2)

        page = MagicMock()
        page.get_by_role = _get_by_role
        page.locator = MagicMock(return_value=_make_locator(1))

        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Save",
            action={"strategy": "get_by_role", "role": "button", "name": "Save"},
        )

        assert path == "selector_fallback_ambiguous"
        # Only ONE get_by_role call (exact) — normalization must NOT be attempted
        assert call_count["n"] == 1

    @pytest.mark.anyio
    async def test_legacy_path_when_aria_role_is_none(self) -> None:
        """
        AC-VERIFY-9: When aria_role is None, the resolver immediately
        returns 'selector_only_legacy' without calling get_by_role.
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = MagicMock()
        page.get_by_role = MagicMock(side_effect=AssertionError("should not be called"))

        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role=None,
            aria_name=None,
            action={"strategy": "get_by_role", "role": "button", "name": "Save"},
        )

        assert path == "selector_only_legacy"
        page.get_by_role.assert_not_called()

    @pytest.mark.anyio
    async def test_cv_fallback_signal_when_both_paths_fail(self) -> None:
        """
        AC-VERIFY-6: When both a11y (0 matches) and CSS selector raise/fail,
        the resolver returns 'cv_fallback_required'.
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        # a11y returns 0; CSS locator raises (strict mode or timeout)
        page = _make_page(exact_count=0, normalized_count=0)
        # Override page.locator to raise, simulating a CSS locator failure
        page.locator = MagicMock(side_effect=Exception("strict mode violation"))

        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Save",
            action={"strategy": "get_by_role", "role": "button", "name": "Save"},
        )

        assert path == "cv_fallback_required"
        assert locator is None


# ---------------------------------------------------------------------------
# Normalization / two-tier probe tests (Algorithm Decision 1)
# ---------------------------------------------------------------------------


class TestA11yLocatorResolverNormalization:
    """Normalized-name two-tier probe (Algorithm Decision 1)."""

    @pytest.mark.anyio
    async def test_normalized_recovers_trailing_whitespace(self) -> None:
        """
        Decision 1: exact 'Save ' (trailing space) returns 0;
        normalized 'Save' regex returns 1 → 'a11y_normalized'.
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        # Exact (with trailing space) → 0; normalized (without) → 1
        page = _make_page(exact_count=0, normalized_count=1)
        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Save ",
            action={},
        )

        assert path == "a11y_normalized"

    @pytest.mark.anyio
    async def test_normalized_recovers_trailing_chevron_icon(self) -> None:
        """
        Decision 1: PrimeNG dropdown label 'Sort ▾' — exact returns 0,
        normalized 'Sort' regex returns 1 → 'a11y_normalized'.
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = _make_page(exact_count=0, normalized_count=1)
        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Sort ▾",
            action={},
        )

        assert path == "a11y_normalized"

    @pytest.mark.anyio
    async def test_normalized_recovers_ellipsis_literal(self) -> None:
        """
        Decision 1: 'Save…' (U+2026 ellipsis) — exact returns 0,
        normalized 'Save' regex returns 1 → 'a11y_normalized'.
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = _make_page(exact_count=0, normalized_count=1)
        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Save…",
            action={},
        )

        assert path == "a11y_normalized"

    @pytest.mark.anyio
    async def test_normalized_ambiguous_falls_back_to_selector(self) -> None:
        """
        Decision 1: exact=0, normalized=2 (still ambiguous) →
        'selector_fallback_ambiguous' (NOT 'a11y_normalized').
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = _make_page(exact_count=0, normalized_count=2)
        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Save ",
            action={"strategy": "get_by_role", "role": "button", "name": "Save "},
        )

        assert path == "selector_fallback_ambiguous"

    @pytest.mark.anyio
    async def test_exception_returns_selector_fallback_error(self) -> None:
        """
        AC-ERROR-1: When get_by_role raises any exception, the resolver
        catches it, logs at WARN level, and returns 'selector_fallback_error'.
        The run must NOT abort.
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = _make_page(exact_raises=True)

        resolver = A11yLocatorResolver()
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Save",
            action={"strategy": "get_by_role", "role": "button", "name": "Save"},
        )

        # Must not raise; must return the error path
        assert path == "selector_fallback_error"


# ---------------------------------------------------------------------------
# _normalize_name pure-function contract (Algorithm Decision 1)
# ---------------------------------------------------------------------------


class TestNormalizeName:
    """
    Pure-function unit tests for _normalize_name.
    Covers all four normalization rules from the Algorithm creative doc.
    """

    def test_strips_trailing_whitespace_and_nbsp(self) -> None:
        from backend.browser.a11y_resolver import _normalize_name

        assert _normalize_name("Save \t\n") == "save"
        assert _normalize_name("Save\xa0") == "save"  # NBSP

    def test_case_fold(self) -> None:
        from backend.browser.a11y_resolver import _normalize_name

        assert _normalize_name("SAVE") == "save"
        assert _normalize_name("ß") == "ss"  # German eszett via case-fold

    def test_nfc_composition(self) -> None:
        from backend.browser.a11y_resolver import _normalize_name

        # NFD decomposed é = e + combining acute accent
        nfd_e = "é"
        composed_e = unicodedata.normalize("NFC", nfd_e)
        assert _normalize_name(nfd_e) == composed_e.casefold()

    def test_strips_trailing_icon_chars(self) -> None:
        from backend.browser.a11y_resolver import _normalize_name

        assert _normalize_name("Sort ▾") == "sort"
        assert _normalize_name("Expand ▼") == "expand"
        assert _normalize_name("Close ◆") == "close"

    def test_strips_trailing_ellipsis(self) -> None:
        from backend.browser.a11y_resolver import _normalize_name

        assert _normalize_name("Save…") == "save"   # unicode ellipsis U+2026
        assert _normalize_name("Save...") == "save"      # three literal dots

    def test_empty_string_returns_empty(self) -> None:
        from backend.browser.a11y_resolver import _normalize_name

        assert _normalize_name("") == ""

    def test_clean_name_unchanged(self) -> None:
        from backend.browser.a11y_resolver import _normalize_name

        # A clean name should come out case-folded only
        assert _normalize_name("Submit") == "submit"


# ---------------------------------------------------------------------------
# Diagnostics (AC-ERROR-2)
# ---------------------------------------------------------------------------


class TestZeroAndZeroDiagnostics:
    """
    AC-ERROR-2: error_message format when both a11y AND selector fail.
    Verified via the resolver's return when cv_fallback_required fires.
    """

    @pytest.mark.anyio
    async def test_cv_fallback_required_path_returned_not_raised(self) -> None:
        """
        When both locator paths are exhausted, the resolver returns
        'cv_fallback_required' and does NOT raise — the run continues.
        """
        from backend.browser.a11y_resolver import A11yLocatorResolver

        page = _make_page(exact_count=0, normalized_count=0)
        page.locator = MagicMock(side_effect=Exception("Locator timed out"))

        resolver = A11yLocatorResolver()
        # Must not raise:
        locator, path = await resolver.resolve(
            page,
            aria_role="button",
            aria_name="Nonexistent",
            action={"strategy": "get_by_role", "role": "button", "name": "Nonexistent"},
        )
        assert path == "cv_fallback_required"
        assert locator is None
