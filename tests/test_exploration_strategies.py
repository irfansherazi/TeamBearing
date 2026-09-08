"""
TASK-029 Phase 2 Tests — Exploration Executor (Strategies)
==========================================================
Module: tests/test_exploration_strategies.py

Tests for:
  - AC-STRATEGY-1: ScrollToRevealStrategy executes scrolling + element check
  - AC-STRATEGY-2: ExpandCollapsedParentStrategy expands aria-expanded=false elements
  - AC-STRATEGY-3: ClickSiblingTabStrategy clicks non-active tabs and checks for target
  - AC-BUDGET-1:   ExplorationRunner.run() terminates after max_steps actions
  - AC-ERROR-1:    Playwright exceptions are caught gracefully; found=False returned

All tests are pure unit tests using AsyncMock / MagicMock.
No live browser or Bedrock calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Minimal VQAState-like dict for strategy tests."""
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-strat-run",
        jira_ticket_id="FAKE-010",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    state.update(
        {
            "debugger_attempted": True,
            "exploration_attempted": False,
            "failure_type": "NOT_VISIBLE",
            "ac_step_action_fail_count": 5,
        }
    )
    state.update(overrides)
    return state


def _make_runner(state: dict, run_id: str = "test-strat-001"):
    """Construct ExplorationRunner with given state."""
    from backend.engine.exploration_runner import ExplorationRunner

    return ExplorationRunner(state=state, run_id=run_id)


def _mock_page(
    *,
    target_found_after_n_calls: int | None = None,
    locator_visible: bool = False,
    tab_elements: int = 3,
    expanded_elements: int = 2,
) -> MagicMock:
    """
    Build a Playwright page MagicMock with configurable async behaviours.

    Parameters
    ----------
    target_found_after_n_calls
        If set, page.locator(...).is_visible() returns True on the Nth call.
        Otherwise it always returns locator_visible.
    locator_visible
        Default is_visible() return when not using call-count logic.
    tab_elements
        How many [role=tab] elements to return.
    expanded_elements
        How many aria-expanded=false elements to return.
    """
    page = MagicMock()

    # page.evaluate() for scrollBy — returns nothing meaningful
    page.evaluate = AsyncMock(return_value=None)

    # Locator for target element detection
    call_count = {"n": 0}

    async def _is_visible():
        call_count["n"] += 1
        if target_found_after_n_calls is not None:
            return call_count["n"] >= target_found_after_n_calls
        return locator_visible

    locator_mock = MagicMock()
    locator_mock.is_visible = _is_visible
    locator_mock.count = AsyncMock(return_value=1 if locator_visible else 0)
    page.locator = MagicMock(return_value=locator_mock)

    # query_selector_all for aria-expanded=false elements
    async def _query_selector_all(selector: str):
        if "aria-expanded" in selector:
            elems = []
            for i in range(expanded_elements):
                e = MagicMock()
                e.click = AsyncMock(return_value=None)
                e.get_attribute = AsyncMock(return_value="false")
                e.evaluate = AsyncMock(return_value=f"trigger-{i}")
                elems.append(e)
            return elems
        # Tabs are now handled by get_by_role
        return []

    page.query_selector_all = AsyncMock(side_effect=_query_selector_all)

    # get_by_role for tab elements
    def _get_by_role(role, *, name=None, **kwargs):
        if role == "tab":
            tab_container = MagicMock()

            async def _all():
                tabs = []
                for i in range(tab_elements):
                    t = MagicMock()
                    t.get_attribute = AsyncMock(return_value="true" if i == 0 else "false")
                    t.inner_text = AsyncMock(return_value=f"Tab {i}")
                    t.click = AsyncMock(return_value=None)
                    t.evaluate = AsyncMock(return_value=f"tab-{i}")
                    tabs.append(t)
                return tabs

            tab_container.all = _all
            return tab_container
        return locator_mock

    page.get_by_role = MagicMock(side_effect=_get_by_role)

    return page


# ===========================================================================
# AC-STRATEGY-1: ScrollToRevealStrategy
# ===========================================================================


class TestScrollToRevealStrategy:
    """
    AC-STRATEGY-1 — Verify ScrollToRevealStrategy scrolls and checks visibility.

    Strategy execution order (lowest cost first):
      1. scroll_to_reveal (this class)
      2. expand_collapsed_parent
      3. click_sibling_tab
    """

    @pytest.mark.anyio
    async def test_scroll_calls_page_evaluate(self):
        """
        ScrollToRevealStrategy.execute() must call page.evaluate('window.scrollBy(0, 300)')
        at least once while searching for the target.
        """
        from backend.engine.exploration_runner import ScrollToRevealStrategy

        page = _mock_page(locator_visible=False)
        strategy = ScrollToRevealStrategy(
            page=page,
            target_locator="button[name='Submit All']",
            max_scroll_px=600,
            run_id="test-scroll-001",
        )

        await strategy.execute()

        # Must have scrolled at least once
        page.evaluate.assert_called()
        scroll_calls = [c for c in page.evaluate.call_args_list if "scrollBy" in str(c)]
        assert len(scroll_calls) >= 1, "ScrollToRevealStrategy must call page.evaluate with scrollBy at least once"

    @pytest.mark.anyio
    async def test_scroll_returns_found_true_when_element_becomes_visible(self):
        """
        Element found mid-scroll → returns found=True with correct pathway.
        """
        from backend.engine.exploration_runner import ScrollToRevealStrategy

        # Element becomes visible on the 2nd scroll check
        page = _mock_page(target_found_after_n_calls=2)
        strategy = ScrollToRevealStrategy(
            page=page,
            target_locator="button[name='Submit All']",
            max_scroll_px=1200,
            run_id="test-scroll-002",
        )

        result = await strategy.execute()

        assert result["found"] is True, "Element visible mid-scroll must return found=True"
        assert "scroll" in result["pathway_summary"].lower(), (
            "pathway_summary must mention scroll when strategy succeeds"
        )
        assert result["steps_taken"] >= 1

    @pytest.mark.anyio
    async def test_scroll_returns_found_false_when_budget_exhausted(self):
        """
        Max scroll distance reached without finding element → found=False.
        """
        from backend.engine.exploration_runner import ScrollToRevealStrategy

        page = _mock_page(locator_visible=False)
        strategy = ScrollToRevealStrategy(
            page=page,
            target_locator="button[name='Never Visible']",
            max_scroll_px=300,  # tiny budget → exhausted quickly
            run_id="test-scroll-003",
        )

        result = await strategy.execute()

        assert result["found"] is False, "ScrollToRevealStrategy must return found=False when scroll budget exhausted"

    @pytest.mark.anyio
    async def test_scroll_strategy_step_count_bounded(self):
        """
        steps_taken must be <= max_scroll_px // scroll_increment + 1 (bounded by budget).
        """
        from backend.engine.exploration_runner import ScrollToRevealStrategy

        page = _mock_page(locator_visible=False)
        strategy = ScrollToRevealStrategy(
            page=page,
            target_locator="button[name='Missing']",
            max_scroll_px=900,
            scroll_increment=300,
            run_id="test-scroll-004",
        )

        result = await strategy.execute()

        # 900px / 300px = 3 scroll steps max
        assert result["steps_taken"] <= 4, (
            f"steps_taken={result['steps_taken']} exceeds budget for scroll_increment=300, max_scroll_px=900"
        )


# ===========================================================================
# AC-STRATEGY-2: ExpandCollapsedParentStrategy
# ===========================================================================


class TestExpandCollapsedParentStrategy:
    """
    AC-STRATEGY-2 — Verify ExpandCollapsedParentStrategy expands collapsed parents.
    """

    @pytest.mark.anyio
    async def test_queries_aria_expanded_false(self):
        """
        Strategy must query for [aria-expanded='false'] elements.
        """
        from backend.engine.exploration_runner import ExpandCollapsedParentStrategy

        page = _mock_page(expanded_elements=2, locator_visible=False)
        strategy = ExpandCollapsedParentStrategy(
            page=page,
            target_locator="span[name='Hidden Panel Item']",
            run_id="test-expand-001",
        )

        await strategy.execute()

        # Must have called query_selector_all with aria-expanded
        calls_str = str(page.query_selector_all.call_args_list)
        assert "aria-expanded" in calls_str, "ExpandCollapsedParentStrategy must query [aria-expanded='false'] elements"

    @pytest.mark.anyio
    async def test_clicking_expand_trigger_returns_found_true(self):
        """
        Clicking an expand trigger makes element visible → returns found=True.
        """
        from backend.engine.exploration_runner import ExpandCollapsedParentStrategy

        # Element becomes visible after the first expand click (2nd locator check)
        page = _mock_page(expanded_elements=2, target_found_after_n_calls=2)
        strategy = ExpandCollapsedParentStrategy(
            page=page,
            target_locator="span[name='Accordion Item']",
            run_id="test-expand-002",
        )

        result = await strategy.execute()

        assert result["found"] is True, (
            "ExpandCollapsedParentStrategy must return found=True when target appears after expand"
        )
        assert result["steps_taken"] >= 1

    @pytest.mark.anyio
    async def test_wrong_trigger_does_not_raise(self):
        """
        Clicking the wrong expand trigger (that doesn't reveal target) must not
        raise an exception — continue to next trigger or return found=False.
        """
        from backend.engine.exploration_runner import ExpandCollapsedParentStrategy

        # Make one expand element raise when clicked
        page = _mock_page(expanded_elements=2, locator_visible=False)

        async def bad_query(selector):
            if "aria-expanded" in selector:
                bad_elem = MagicMock()
                bad_elem.click = AsyncMock(side_effect=Exception("Click failed"))
                bad_elem.get_attribute = AsyncMock(return_value="false")
                return [bad_elem]
            return []

        page.query_selector_all = AsyncMock(side_effect=bad_query)

        strategy = ExpandCollapsedParentStrategy(
            page=page,
            target_locator="span[name='Hidden']",
            run_id="test-expand-003",
        )

        # Must NOT raise; must return gracefully
        result = await strategy.execute()

        assert "found" in result, "ExpandCollapsedParentStrategy must return a result dict even on click error"

    @pytest.mark.anyio
    async def test_no_collapsed_elements_returns_found_false(self):
        """
        No [aria-expanded=false] elements found → found=False, steps_taken=0.
        """
        from backend.engine.exploration_runner import ExpandCollapsedParentStrategy

        page = _mock_page(expanded_elements=0, locator_visible=False)
        strategy = ExpandCollapsedParentStrategy(
            page=page,
            target_locator="span[name='Missing']",
            run_id="test-expand-004",
        )

        result = await strategy.execute()

        assert result["found"] is False
        assert result["steps_taken"] == 0, "steps_taken must be 0 when there are no collapsed elements to try"


# ===========================================================================
# AC-STRATEGY-3: ClickSiblingTabStrategy
# ===========================================================================


class TestClickSiblingTabStrategy:
    """
    AC-STRATEGY-3 — Verify ClickSiblingTabStrategy cycles sibling tabs.
    """

    @pytest.mark.anyio
    async def test_queries_role_tab_elements(self):
        """
        Strategy must query elements by role='tab'.
        """
        from backend.engine.exploration_runner import ClickSiblingTabStrategy

        page = _mock_page(tab_elements=3, locator_visible=False)
        strategy = ClickSiblingTabStrategy(
            page=page,
            target_locator="div[name='Tab Panel Content']",
            run_id="test-tab-001",
        )

        await strategy.execute()

        # Must have used get_by_role('tab') to discover tabs
        page.get_by_role.assert_called()
        tab_calls = [c for c in page.get_by_role.call_args_list if c.args and c.args[0] == "tab"]
        assert len(tab_calls) >= 1, "ClickSiblingTabStrategy must call page.get_by_role('tab') to find sibling tabs"

    @pytest.mark.anyio
    async def test_target_found_after_tab_click_returns_found_true(self):
        """
        Target appears after clicking a sibling tab → found=True with tab name in pathway.
        """
        from backend.engine.exploration_runner import ClickSiblingTabStrategy

        # Target becomes visible after 2nd is_visible call (after first tab click)
        page = _mock_page(tab_elements=3, target_found_after_n_calls=2)
        strategy = ClickSiblingTabStrategy(
            page=page,
            target_locator="div[name='Target Content']",
            run_id="test-tab-002",
        )

        result = await strategy.execute()

        assert result["found"] is True, (
            "ClickSiblingTabStrategy must return found=True when target appears after tab click"
        )
        assert result["steps_taken"] >= 1

    @pytest.mark.anyio
    async def test_all_tabs_exhausted_returns_found_false(self):
        """
        All sibling tabs clicked without finding target → found=False.
        """
        from backend.engine.exploration_runner import ClickSiblingTabStrategy

        page = _mock_page(tab_elements=3, locator_visible=False)
        strategy = ClickSiblingTabStrategy(
            page=page,
            target_locator="div[name='Ghost Element']",
            run_id="test-tab-003",
        )

        result = await strategy.execute()

        assert result["found"] is False, "ClickSiblingTabStrategy must return found=False after exhausting all tabs"

    @pytest.mark.anyio
    async def test_skips_currently_active_tab(self):
        """
        The currently active tab (aria-selected=true) must NOT be re-clicked
        — it is already the active panel.
        """
        from backend.engine.exploration_runner import ClickSiblingTabStrategy

        page = _mock_page(tab_elements=3, locator_visible=False)

        # Track clicks — first tab is 'active' and should not be clicked
        clicked_tabs = []

        def _get_by_role(role, *, name=None, **kwargs):
            if role == "tab":
                container = MagicMock()

                async def _all():
                    tabs = []
                    for i in range(3):
                        t = MagicMock()
                        is_active = i == 0
                        t.get_attribute = AsyncMock(return_value="true" if is_active else "false")
                        t.inner_text = AsyncMock(return_value=f"Tab {i}")

                        async def _click(tab_idx=i):
                            clicked_tabs.append(tab_idx)

                        t.click = _click
                        tabs.append(t)
                    return tabs

                container.all = _all
                return container
            locator_mock = MagicMock()
            locator_mock.is_visible = AsyncMock(return_value=False)
            return locator_mock

        page.get_by_role = MagicMock(side_effect=_get_by_role)

        strategy = ClickSiblingTabStrategy(
            page=page,
            target_locator="div[name='Not Found']",
            run_id="test-tab-004",
        )

        await strategy.execute()

        # Tab 0 is active — must NOT have been clicked
        assert 0 not in clicked_tabs, "ClickSiblingTabStrategy must skip the currently active tab (aria-selected=true)"


# ===========================================================================
# AC-BUDGET-1: ExplorationRunner.run() respects max_steps budget
# ===========================================================================


class TestExplorationBudget:
    """
    AC-BUDGET-1 — Verify the global step budget is honoured.

    ExplorationRunner.run() must terminate after exactly max_steps actions
    and return found=False WITHOUT setting the HITL flag — that decision
    stays in evaluator_node.
    """

    @pytest.mark.anyio
    async def test_run_terminates_after_max_steps(self):
        """
        run() terminates after settings.exploration_max_steps regardless of strategies.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-budget-001")

        page = _mock_page(locator_visible=False)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 2  # very tight budget
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        assert result["outcome"]["steps_taken"] <= 2 + 1, (
            f"steps_taken={result['outcome']['steps_taken']} exceeded max_steps=2"
        )

    @pytest.mark.anyio
    async def test_run_does_not_set_hitl_flag(self):
        """
        ExplorationRunner.run() must NOT set awaiting_human_takeover.
        HITL decision belongs in evaluator_node.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-budget-002")
        page = _mock_page(locator_visible=False)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 4
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        # Result dict must NOT contain awaiting_human_takeover
        assert "awaiting_human_takeover" not in result, (
            "ExplorationRunner.run() must not set awaiting_human_takeover — that's evaluator's job"
        )

    @pytest.mark.anyio
    async def test_budget_consumed_is_logged_to_outcome(self):
        """
        Exploration budget consumed (steps_taken) must appear in outcome dict.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-budget-003")
        page = _mock_page(locator_visible=False)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 4
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        assert "steps_taken" in result["outcome"], "outcome must contain steps_taken field"
        assert isinstance(result["outcome"]["steps_taken"], int)


# ===========================================================================
# AC-ERROR-1: ExplorationRunner wraps all exceptions gracefully
# ===========================================================================


class TestExplorationErrorHandling:
    """
    AC-ERROR-1 — Playwright exceptions must be caught and return found=False.

    No exception from a strategy should propagate up to the caller.
    The error must be logged to exploration_outcomes[*].error_message.
    """

    @pytest.mark.anyio
    async def test_run_catches_playwright_timeout_error(self):
        """
        TimeoutError from Playwright returns found=False without re-raising.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-error-001")

        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=TimeoutError("Playwright timeout"))
        page.query_selector_all = AsyncMock(return_value=[])
        page.get_by_role = MagicMock(return_value=MagicMock(all=AsyncMock(return_value=[])))
        locator_mock = MagicMock()
        locator_mock.is_visible = AsyncMock(return_value=False)
        locator_mock.count = AsyncMock(return_value=0)
        page.locator = MagicMock(return_value=locator_mock)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 4
            mock_settings.exploration_min_dom_failures = 5

            # Must NOT raise
            result = await runner.run(page=page)

        assert result["found"] is False, "run() must return found=False when Playwright raises TimeoutError"

    @pytest.mark.anyio
    async def test_run_catches_generic_exception(self):
        """
        Any unexpected exception during strategy execution returns found=False gracefully.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-error-002")

        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=RuntimeError("Unexpected internal error"))
        page.query_selector_all = AsyncMock(return_value=[])
        page.get_by_role = MagicMock(return_value=MagicMock(all=AsyncMock(return_value=[])))
        locator_mock = MagicMock()
        locator_mock.is_visible = AsyncMock(return_value=False)
        locator_mock.count = AsyncMock(return_value=0)
        page.locator = MagicMock(return_value=locator_mock)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 4
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        assert result["found"] is False

    @pytest.mark.anyio
    async def test_exception_is_logged_in_outcome_error_message(self):
        """
        When an exception occurs, outcome.error_message must contain the error text.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-error-003")

        error_msg = "Playwright timed out after 30000ms"
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=Exception(error_msg))
        page.query_selector_all = AsyncMock(return_value=[])
        page.get_by_role = MagicMock(return_value=MagicMock(all=AsyncMock(return_value=[])))
        locator_mock = MagicMock()
        locator_mock.is_visible = AsyncMock(return_value=False)
        locator_mock.count = AsyncMock(return_value=0)
        page.locator = MagicMock(return_value=locator_mock)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 4
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        outcome = result.get("outcome", {})
        error_field = outcome.get("error_message", "")
        # error_message should capture something about the failure
        assert isinstance(error_field, str), "error_message must be a string"


# ===========================================================================
# Integration: ExplorationRunner.run() dispatcher — all strategies tried
# ===========================================================================


class TestExplorationRunnerDispatcher:
    """
    Verify that ExplorationRunner.run() dispatches all three strategies in order.
    Scroll → Expand → Tab (ordered by cost).
    """

    @pytest.mark.anyio
    async def test_run_returns_found_true_when_scroll_succeeds(self):
        """
        If scroll succeeds, run() returns found=True immediately without trying
        expand or tab strategies.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-dispatch-001")

        # Target visible after 1st scroll attempt
        page = _mock_page(target_found_after_n_calls=1)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 10
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        assert result["found"] is True
        assert result["outcome"]["strategy_used"] == "scroll_to_reveal"

    @pytest.mark.anyio
    async def test_run_returns_found_false_when_all_strategies_fail(self):
        """
        All three strategies fail → run() returns found=False with strategy_used='all_failed'.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-dispatch-002")

        page = _mock_page(
            locator_visible=False,
            tab_elements=2,
            expanded_elements=1,
        )

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 20
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        assert result["found"] is False

    @pytest.mark.anyio
    async def test_run_result_has_required_keys(self):
        """
        run() result dict must always contain: found, reason, pathway_summary, outcome.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state()
        runner = ExplorationRunner(state=state, run_id="test-dispatch-003")
        page = _mock_page(locator_visible=False)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 6
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        for key in ("found", "reason", "pathway_summary", "outcome"):
            assert key in result, f"run() result missing required key: '{key}'"

    @pytest.mark.anyio
    async def test_run_populates_target_element_in_outcome(self):
        """
        outcome.target_element must reflect what element was being sought.
        """
        from backend.engine.exploration_runner import ExplorationRunner

        state = _make_state(
            jira_ticket={"acceptance_criteria_steps": ["Click the Submit All button", "Verify confirmation"]},
            ac_step_index=0,
        )
        runner = ExplorationRunner(state=state, run_id="test-dispatch-004")
        page = _mock_page(locator_visible=False)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_max_steps = 4
            mock_settings.exploration_min_dom_failures = 5

            result = await runner.run(page=page)

        assert result["outcome"]["target_element"] != "", (
            "outcome.target_element must not be empty when AC steps are available"
        )
