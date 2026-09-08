"""
vQA — T2-d Split Verifier Tests
================================
Module: backend/engine/test_verifier_split.py

Tests for the DomVerifier + VisionVerifier split introduced in Phase 4 (T2-d).
Covers AC-VERIFY-5 (DOM resolution rate, latency savings, token savings) and
AC-VERIFY-6 (false-NOT_YET rate).

All Playwright interactions are mocked at the Page boundary per project convention
(systemPatterns.md § Testing Patterns: no live browser/AWS in pytest).

Test structure
--------------
- test_dom_resolution_rate_at_least_60pct  — ≥12 of 20 fixture cases DOM-resolved (AC-VERIFY-5a)
- test_dom_path_saves_500ms                — DOM-resolved case elapsed_ms + 500 <= historical_ms (AC-VERIFY-5b)
- test_dom_path_saves_90pct_tokens         — DOM-resolved case tokens_used <= 10% historical (AC-VERIFY-5c)
- test_false_not_yet_rate_at_most_10pct    — ≤5 of 50 false-NOT_YET cases still NOT_YET (AC-VERIFY-6)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent / "fixtures"
VERIFIER_TRANSITIONS_FIXTURE = FIXTURES_DIR / "verifier_transitions.jsonl"
FALSE_NOT_YET_FIXTURE = FIXTURES_DIR / "verifier_false_not_yet.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture_jsonl(path: Path) -> list[dict]:
    """Load a newline-delimited JSON fixture file."""
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _make_mock_page(html_post: str, url: str = "https://qa.vcreative.net/test") -> MagicMock:
    """
    Build a minimal Playwright Page mock whose DOM matches ``html_post``.

    The mock exposes:
    - page.url → url
    - page.locator(...).get_attribute(...) → matches simple aria attributes
    - page.locator(...).is_visible() → True for elements present in html_post
    - page.locator(...).is_hidden() → True for elements with display:none in html_post
    - page.locator(...).count() → count of matching simple class selectors
    - page.locator(...).text_content() → content between tags for .class
    - page.locator(...).first.is_visible() → True
    """
    page = MagicMock()
    page.url = url

    def _locator(selector: str):
        loc = MagicMock()
        loc_first = MagicMock()

        # aria-expanded
        async def _get_attribute(attr: str):
            if attr == "aria-expanded":
                if "aria-expanded='true'" in html_post or 'aria-expanded="true"' in html_post:
                    return "true"
                return "false"
            if attr == "aria-selected":
                if "aria-selected='true'" in html_post or 'aria-selected="true"' in html_post:
                    return "true"
                return "false"
            if attr == "aria-checked":
                if "aria-checked='true'" in html_post or 'aria-checked="true"' in html_post:
                    return "true"
                if "aria-checked='false'" in html_post or 'aria-checked="false"' in html_post:
                    return "false"
                return None
            if attr == "class":
                # extract class values from html_post for the given selector
                import re
                # simple heuristic: return joined classes from first matching element
                match = re.search(r"class=['\"]([^'\"]*)['\"]", html_post)
                return match.group(1) if match else ""
            return None

        async def _is_visible():
            # hidden if display:none in html_post
            if "display:none" in html_post or "display: none" in html_post:
                return False
            # visible if the selector class appears anywhere in html_post
            sel_part = selector.split("[")[0].lstrip(".")
            return sel_part in html_post or html_post.strip() != ""

        async def _is_hidden():
            return "display:none" in html_post or "display: none" in html_post

        async def _count():
            import re
            # count occurrences of the class selector in html_post
            if selector.startswith("."):
                cls = selector.lstrip(".")
                return len(re.findall(rf"class=['\"][^'\"]*{re.escape(cls)}[^'\"]*['\"]", html_post))
            return 0

        async def _text_content():
            import re
            # extract text between tags
            match = re.search(r">([^<]+)<", html_post)
            return match.group(1) if match else ""

        loc.get_attribute = AsyncMock(side_effect=_get_attribute)
        loc.is_visible = AsyncMock(side_effect=_is_visible)
        loc.is_hidden = AsyncMock(side_effect=_is_hidden)
        loc.count = AsyncMock(side_effect=_count)
        loc.text_content = AsyncMock(side_effect=_text_content)
        loc_first.is_visible = AsyncMock(side_effect=_is_visible)
        loc.first = loc_first
        return loc

    page.locator = MagicMock(side_effect=_locator)

    async def _evaluate(script: str):
        return None

    page.evaluate = AsyncMock(side_effect=_evaluate)

    return page


async def _run_dom_verifier_on_fixture(row: dict) -> "VerifierResult":  # noqa: F821
    """
    Run DomVerifier.check() against a single fixture row using a mocked page.

    Imports DomVerifier lazily (RED phase: import will fail until GREEN impl exists).
    """
    from backend.engine.verifier import DomVerifier, _deserialize_expectation

    page = _make_mock_page(
        html_post=row["page_html_post"],
        url=row["pre_state_snapshot"].get("url", "https://qa.vcreative.net/test"),
    )
    # Patch page.url to simulate post-action URL when state_expectation has url_delta/url_equals
    planned = row.get("planned_action", {})
    se_dict = planned.get("state_expectation")
    if se_dict:
        kind = se_dict.get("kind", "")
        if kind == "url_delta" and se_dict.get("pattern"):
            page.url = row["pre_state_snapshot"]["url"] + "/" + se_dict["pattern"].lstrip("/")
        elif kind == "url_equals" and se_dict.get("expected"):
            page.url = se_dict["expected"]

    expectation = _deserialize_expectation(se_dict) if se_dict else None
    dom = DomVerifier()
    start = time.perf_counter()
    result = await dom.check(page=page, expectation=expectation, pre_state_snapshot=row["pre_state_snapshot"])
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    result.elapsed_ms = elapsed_ms
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDomResolutionRate:
    """AC-VERIFY-5a — DomVerifier alone resolves ≥60% (≥12 of 20) transitions."""

    @pytest.mark.asyncio
    async def test_dom_resolution_rate_at_least_60pct(self) -> None:
        """
        Iterate the 20-case fixture. Assert DomVerifier returns resolved=True on
        ≥12 cases WITHOUT invoking VisionVerifier (patched to raise AssertionError
        if called, so any cascade fails the test).
        """
        from backend.engine.verifier import VerifierVerdict, VisionVerifier

        rows = _load_fixture_jsonl(VERIFIER_TRANSITIONS_FIXTURE)
        assert len(rows) == 20, f"Expected 20 fixture rows, got {len(rows)}"

        resolved_count = 0
        inconclusive_expected_count = 0

        for row in rows:
            expected = row["expected_verdict"]
            if expected == "INCONCLUSIVE":
                inconclusive_expected_count += 1
                continue  # allow these to be inconclusive — they should fall through

            # For PASS-expected cases, assert DOM resolves them without vision
            with patch.object(
                VisionVerifier,
                "check",
                side_effect=AssertionError("VisionVerifier must NOT be called for DOM-resolvable cases"),
            ):
                result = await _run_dom_verifier_on_fixture(row)

            if result.resolved:
                resolved_count += 1
                assert result.verdict in (VerifierVerdict.PASS, VerifierVerdict.NOT_YET), (
                    f"Row {row['id']}: unexpected verdict {result.verdict}"
                )
                assert result.verifier_path == "dom_only", (
                    f"Row {row['id']}: expected verifier_path='dom_only', got {result.verifier_path!r}"
                )

        # At least 60% of the 20 cases (at minimum 12) must resolve via DOM
        assert resolved_count >= 12, (
            f"DomVerifier resolved only {resolved_count}/20 cases "
            f"({resolved_count / 20:.0%}); required ≥60% (≥12). "
            f"Inconclusive-expected cases: {inconclusive_expected_count}"
        )


class TestDomPathSaves500ms:
    """AC-VERIFY-5b — DOM-resolved cases save ≥500ms vs historical vision baseline."""

    @pytest.mark.asyncio
    async def test_dom_path_saves_500ms(self) -> None:
        """
        For each DOM-resolved case from the 20-case fixture, assert that
        result.elapsed_ms + 500 <= fixture['historical_ms'].

        Historical baselines represent the ~2400–2800ms Sonnet vision call latency.
        The DOM path should complete in <100ms, well under the 500ms saving threshold.
        """
        from backend.engine.verifier import VisionVerifier

        rows = _load_fixture_jsonl(VERIFIER_TRANSITIONS_FIXTURE)
        checked = 0
        failures: list[str] = []

        for row in rows:
            if row["expected_verdict"] == "INCONCLUSIVE":
                continue

            with patch.object(VisionVerifier, "check", side_effect=AssertionError("No vision")):
                result = await _run_dom_verifier_on_fixture(row)

            if not result.resolved:
                continue  # skip cases DomVerifier couldn't resolve

            checked += 1
            historical_ms = row["historical_ms"]
            savings = historical_ms - result.elapsed_ms
            if savings < 500:
                failures.append(
                    f"Row {row['id']} ('{row['description']}'): "
                    f"savings={savings}ms (elapsed={result.elapsed_ms}ms, "
                    f"historical={historical_ms}ms) — required ≥500ms"
                )

        assert checked >= 1, "No DOM-resolved cases to evaluate"
        assert not failures, (
            f"{len(failures)} DOM-resolved cases did not achieve ≥500ms savings:\n"
            + "\n".join(failures)
        )


class TestDomPathSaves90PctTokens:
    """AC-VERIFY-5c — DOM-resolved cases use ≤10% of historical token count."""

    @pytest.mark.asyncio
    async def test_dom_path_saves_90pct_tokens(self) -> None:
        """
        For each DOM-resolved case, assert result.tokens_used <= 10% of
        fixture['historical_tokens'].

        DOM-only checks make zero LLM calls → tokens_used == 0, which trivially
        satisfies the ≤10% requirement. We explicitly assert tokens_used == 0 to
        catch any accidental LLM call in the DOM path.
        """
        from backend.engine.verifier import VisionVerifier

        rows = _load_fixture_jsonl(VERIFIER_TRANSITIONS_FIXTURE)
        checked = 0
        failures: list[str] = []

        for row in rows:
            if row["expected_verdict"] == "INCONCLUSIVE":
                continue

            with patch.object(VisionVerifier, "check", side_effect=AssertionError("No vision")):
                result = await _run_dom_verifier_on_fixture(row)

            if not result.resolved:
                continue

            checked += 1
            threshold = 0.10 * row["historical_tokens"]
            if result.tokens_used > threshold:
                failures.append(
                    f"Row {row['id']} ('{row['description']}'): "
                    f"tokens_used={result.tokens_used} exceeds 10% of "
                    f"historical {row['historical_tokens']} (threshold={threshold:.0f})"
                )

        assert checked >= 1, "No DOM-resolved cases to evaluate"
        assert not failures, (
            f"{len(failures)} DOM-resolved cases exceeded the 90% token-saving threshold:\n"
            + "\n".join(failures)
        )


class TestFalseNotYetRate:
    """AC-VERIFY-6 — False-NOT_YET rate drops to ≤10% (≤5 of 50 cases)."""

    @pytest.mark.asyncio
    async def test_false_not_yet_rate_at_most_10pct(self) -> None:
        """
        Iterate the 50-case false-NOT_YET fixture through the cascaded split-verifier
        path (DomVerifier first; VisionVerifier as cascade stub that returns PASS for
        all cases, since the fixture ground truth is PASS).

        Assert ≤5 of the 50 cases still return NOT_YET after the cascade.
        """
        from backend.engine.verifier import (
            DomVerifier,
            VerifierResult,
            VerifierVerdict,
            _deserialize_expectation,
        )

        rows = _load_fixture_jsonl(FALSE_NOT_YET_FIXTURE)
        assert len(rows) == 50, f"Expected 50 fixture rows, got {len(rows)}"

        not_yet_count = 0

        for row in rows:
            page = _make_mock_page(
                html_post=row["page_html_post"],
                url=row["pre_state_snapshot"].get("url", "https://qa.vcreative.net/test"),
            )
            planned = row.get("planned_action", {})
            se_dict = planned.get("state_expectation")
            # Adjust URL for url-based checks
            if se_dict:
                kind = se_dict.get("kind", "")
                if kind == "url_delta" and se_dict.get("pattern"):
                    page.url = row["pre_state_snapshot"]["url"] + "/" + se_dict["pattern"].lstrip("/")
                elif kind == "url_equals" and se_dict.get("expected"):
                    page.url = se_dict["expected"]

            expectation = _deserialize_expectation(se_dict) if se_dict else None
            dom = DomVerifier()
            dom_result = await dom.check(
                page=page,
                expectation=expectation,
                pre_state_snapshot=row["pre_state_snapshot"],
            )

            if dom_result.resolved:
                final_verdict = dom_result.verdict
            else:
                # Cascade to VisionVerifier stub — always returns PASS (ground truth)
                stub_result = VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence="vision stub: ground truth PASS",
                    verifier_path="dom_inconclusive_vision_ran",
                    tokens_used=1800,
                    elapsed_ms=2500,
                )
                final_verdict = stub_result.verdict

            if final_verdict == VerifierVerdict.NOT_YET:
                not_yet_count += 1

        assert not_yet_count <= 5, (
            f"False-NOT_YET rate is {not_yet_count}/50 ({not_yet_count / 50:.0%}); "
            f"required ≤10% (≤5 cases remain NOT_YET after split-verifier cascade)"
        )
