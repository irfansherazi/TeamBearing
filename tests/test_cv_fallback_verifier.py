"""
test_cv_fallback_verifier.py
Phase 3 Unit Tests — CV Fallback Verifier Adaptation & State Change Detection

Tests for:
  AC-HAPPY-1: Post-click state change detected → CV step marked CV_CLICK_SUCCESS
  AC-HAPPY-1: URL change after CV click → state change detected
  AC-HAPPY-1: ARIA snapshot diff after CV click → state change detected
  AC-HAPPY-1: Element count delta after CV click → state change detected
  AC-ERROR-2: No DOM state change within 2 s → CV_CLICK_FAILED, escalate to HITL
  AC-HAPPY-1: cv_fallback entry records correct success flag in executor after state check
  AC-ENTRY-1: State change check skipped when CV click itself failed (no mark_id)

All tests are pure unit tests — mocked Playwright page, no live browser, no network.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.verifier import cv_fallback_state_change_check

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page(
    *,
    url: str = "https://two-test.vcreative.net/production-orders",
    is_closed: bool = False,
):
    """Return a mock Playwright page object."""
    page = AsyncMock()
    page.is_closed = MagicMock(return_value=is_closed)
    page.url = url
    return page


def _make_pre_state(
    *,
    url: str = "https://two-test.vcreative.net/production-orders",
    aria_snapshot: str = "<generic> Production Orders </generic>",
    element_count: int = 42,
) -> dict:
    """Return a pre-click state snapshot dict."""
    return {
        "url": url,
        "aria_snapshot": aria_snapshot,
        "element_count": element_count,
    }


# ---------------------------------------------------------------------------
# TestCvFallbackStateChangeCheck — Happy Paths
# ---------------------------------------------------------------------------


class TestCvFallbackStateChangeCheck:
    """Tests for verifier.cv_fallback_state_change_check() — all detection modes."""

    @pytest.mark.anyio
    async def test_url_change_detected(self):
        """AC-HAPPY-1: URL change after CV click → returns True."""
        page = _make_mock_page(url="https://two-test.vcreative.net/orders/123")
        pre_state = _make_pre_state(url="https://two-test.vcreative.net/production-orders")

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert result is True, "URL change should be detected as state change"

    @pytest.mark.anyio
    async def test_aria_snapshot_diff_detected(self):
        """AC-HAPPY-1: ARIA snapshot diff after CV click → returns True."""
        page = _make_mock_page()
        # Simulate page.accessibility.snapshot() returning a different tree
        page.accessibility = AsyncMock()
        page.accessibility.snapshot = AsyncMock(
            return_value={"role": "WebArea", "name": "Orders", "children": [{"role": "dialog"}]}
        )
        pre_state = _make_pre_state(
            aria_snapshot='{"role": "WebArea", "name": "Orders", "children": []}',
        )

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert result is True, "ARIA diff should be detected as state change"

    @pytest.mark.anyio
    async def test_element_count_delta_detected(self):
        """AC-HAPPY-1: Element count increase after CV click → returns True."""
        page = _make_mock_page()
        # Same URL, same ARIA snapshot — but element count changed
        page.accessibility = AsyncMock()
        page.accessibility.snapshot = AsyncMock(return_value=None)

        # Simulate DOM element count (via evaluate) increasing
        page.evaluate = AsyncMock(return_value=55)  # was 42

        pre_state = _make_pre_state(element_count=42, aria_snapshot="")

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert result is True, "Element count delta should be detected as state change"

    @pytest.mark.anyio
    async def test_no_state_change_returns_false(self):
        """AC-ERROR-2: No URL, ARIA, or count change → returns False."""
        pre_url = "https://two-test.vcreative.net/production-orders"
        pre_count = 42
        # Pre-aria must be the json.dumps() of what the mock snapshot returns
        # so that current_aria == pre_aria (no diff detected)
        _snapshot_dict = {"role": "WebArea", "name": "Orders", "children": []}
        import json

        pre_aria = json.dumps(_snapshot_dict, sort_keys=True)

        page = _make_mock_page(url=pre_url)
        page.accessibility = AsyncMock()
        page.accessibility.snapshot = AsyncMock(return_value=_snapshot_dict)
        page.evaluate = AsyncMock(return_value=pre_count)  # same count

        pre_state = _make_pre_state(url=pre_url, aria_snapshot=pre_aria, element_count=pre_count)

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert result is False, "Identical state should return False"

    @pytest.mark.anyio
    async def test_element_count_decrease_detected(self):
        """Element count decrease (e.g. modal closed, overlay removed) is also a state change."""
        page = _make_mock_page()
        page.accessibility = AsyncMock()
        page.accessibility.snapshot = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=30)  # was 42 → decrease

        pre_state = _make_pre_state(element_count=42, aria_snapshot="")

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert result is True, "Element count decrease should also be detected as state change"

    @pytest.mark.anyio
    async def test_page_closed_returns_false(self):
        """cv_fallback_state_change_check on a closed page returns False without raising."""
        page = _make_mock_page(is_closed=True)
        pre_state = _make_pre_state()

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert result is False

    @pytest.mark.anyio
    async def test_snapshot_exception_falls_back_gracefully(self):
        """If accessibility.snapshot() raises, function still returns False (no crash)."""
        page = _make_mock_page()
        page.accessibility = AsyncMock()
        page.accessibility.snapshot = AsyncMock(side_effect=Exception("CDP error"))
        page.evaluate = AsyncMock(side_effect=Exception("JS error"))

        pre_state = _make_pre_state()

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        # Should return False (no detectable state change), not raise
        assert result is False

    @pytest.mark.anyio
    async def test_waits_before_checking(self):
        """cv_fallback_state_change_check must wait ~2 seconds before asserting state."""
        page = _make_mock_page()
        page.accessibility = AsyncMock()
        page.accessibility.snapshot = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=42)

        pre_state = _make_pre_state()

        sleep_calls = []

        async def _capture_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("backend.engine.verifier.asyncio.sleep", side_effect=_capture_sleep):
            await cv_fallback_state_change_check(page, pre_state)

        # Must have slept for at least 2 seconds total
        assert sum(sleep_calls) >= 2.0, (
            f"cv_fallback_state_change_check must wait >=2s before checking, but only waited {sum(sleep_calls):.1f}s"
        )


# ---------------------------------------------------------------------------
# TestCvFallbackStateCheckSignature
# ---------------------------------------------------------------------------


class TestCvFallbackStateCheckSignature:
    """Validates the function signature and return contract."""

    @pytest.mark.anyio
    async def test_returns_bool_true_on_url_change(self):
        """Return type must be exactly bool, not truthy value."""
        page = _make_mock_page(url="https://two-test.vcreative.net/new-url")
        pre_state = _make_pre_state(url="https://two-test.vcreative.net/old-url")

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert isinstance(result, bool), f"Expected bool, got {type(result)}"
        assert result is True

    @pytest.mark.anyio
    async def test_returns_bool_false_on_no_change(self):
        """Return type must be exactly bool, not falsy value."""
        page = _make_mock_page()
        page.accessibility = AsyncMock()
        page.accessibility.snapshot = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=42)

        pre_state = _make_pre_state(element_count=42, aria_snapshot="")

        with patch("backend.engine.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await cv_fallback_state_change_check(page, pre_state)

        assert isinstance(result, bool), f"Expected bool, got {type(result)}"
        assert result is False


# ---------------------------------------------------------------------------
# TestExecutorCvFallbackPhase3Integration
# ---------------------------------------------------------------------------


class TestExecutorCvFallbackPhase3Integration:
    """
    Tests for Phase 3 executor wiring:
    - After CV click succeeds, cv_fallback_state_change_check() is called
    - CV_CLICK_SUCCESS when state changes
    - CV_CLICK_FAILED when no state change → HITL escalation with CV context
    """

    def _make_minimal_state(
        self,
        *,
        ac_step_action_fail_count: int = 3,
        planned_action: dict | None = None,
        cv_fallback_results: list | None = None,
    ) -> dict:
        """Build a minimal VQAState for executor integration tests."""
        return {
            "run_id": "run-cv-p3-test-001",
            "ac_step_index": 0,
            "ac_step_action_fail_count": ac_step_action_fail_count,
            "cv_fallback_invocations": 0,
            "cv_fallback_results": cv_fallback_results or [],
            "planned_action": planned_action
            or {
                "action": "click",
                "strategy": "get_by_role",
                "role": "button",
                "name": "Canvas Sort",
                "reasoning": "Click the canvas sort button",
            },
            "jira_ticket": {
                "acceptance_criteria_steps": ["Click the canvas sort button"],
                "id": "VC2-9999",
            },
            "detailed_execution_log": [],
            "screenshots": [],
            "current_page_url": "https://two-test.vcreative.net",
            "current_screenshot_b64": "",
            "navigation_history": [],
            "retry_count": 3,
            "action_repeat_counts": {},
            "transient_page_text": "",
            "dom_snapshot_before": "",
            "ac_steps_completed": set(),
        }

    @pytest.mark.anyio
    async def test_executor_calls_state_change_check_after_cv_click(self):
        """
        AC-HAPPY-1: After a successful CV coordinate click, executor must call
        cv_fallback_state_change_check() to confirm DOM transition.
        """
        from backend.engine import executor as executor_module

        state = self._make_minimal_state(ac_step_action_fail_count=3)
        mark_map = {
            "5": {"x": 450, "y": 300, "selector": "canvas#chart", "tag": "canvas", "text": ""},
        }

        mock_manager = MagicMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://two-test.vcreative.net"
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")
        mock_page.mouse = AsyncMock()
        mock_page.mouse.click = AsyncMock()
        mock_manager.page = mock_page

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=None),
            patch(
                "backend.engine.executor._dispatch_action",
                new_callable=AsyncMock,
                return_value={
                    "success": False,
                    "error_message": "STRICT_MODE: Canvas Sort matched 0 elements",
                    "actual_url": "https://two-test.vcreative.net",
                    "dom_failure_diagnosis": "DOM_ABSENT",
                },
            ),
            patch("backend.engine.executor.CvFallbackResolver") as MockResolver,
            patch(
                "backend.engine.executor.cv_fallback_state_change_check", new_callable=AsyncMock, return_value=True
            ) as mock_state_check,
            patch("backend.engine.executor.settings") as mock_settings,
        ):
            mock_settings.cv_fallback_enabled = True
            mock_settings.cv_fallback_min_dom_failures = 3

            resolver_instance = MagicMock()
            resolver_instance.should_activate.return_value = True
            resolver_instance.resolve = AsyncMock(return_value=(5, mark_map, 0.003))
            MockResolver.return_value = resolver_instance

            await executor_module.executor_node(state)

        # state_change_check MUST have been called after the CV click
        mock_state_check.assert_awaited_once()

    @pytest.mark.anyio
    async def test_executor_marks_cv_success_when_state_changes(self):
        """
        AC-HAPPY-1: When state_change_check returns True, the cv_fallback_results
        entry must have success=True.
        """
        from backend.engine import executor as executor_module

        state = self._make_minimal_state(ac_step_action_fail_count=3)
        mark_map = {
            "5": {"x": 450, "y": 300, "selector": "canvas#chart", "tag": "canvas", "text": ""},
        }

        mock_manager = MagicMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://two-test.vcreative.net"
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")
        mock_page.mouse = AsyncMock()
        mock_page.mouse.click = AsyncMock()
        mock_manager.page = mock_page

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=None),
            patch(
                "backend.engine.executor._dispatch_action",
                new_callable=AsyncMock,
                return_value={
                    "success": False,
                    "error_message": "STRICT_MODE: Canvas Sort",
                    "actual_url": "https://two-test.vcreative.net",
                },
            ),
            patch("backend.engine.executor.CvFallbackResolver") as MockResolver,
            patch("backend.engine.executor.cv_fallback_state_change_check", new_callable=AsyncMock, return_value=True),
            patch("backend.engine.executor.settings") as mock_settings,
        ):
            mock_settings.cv_fallback_enabled = True
            mock_settings.cv_fallback_min_dom_failures = 3

            resolver_instance = MagicMock()
            resolver_instance.should_activate.return_value = True
            resolver_instance.resolve = AsyncMock(return_value=(5, mark_map, 0.003))
            MockResolver.return_value = resolver_instance

            result_update = await executor_module.executor_node(state)

        # cv_fallback_results must contain a success=True entry
        # The detailed_execution_log returns ExecutionStep objects which may be
        # stored as dataclass instances (with .success) or dicts (with ["success"])
        steps = result_update.get("detailed_execution_log", [])
        assert len(steps) >= 1
        last_step = steps[-1]
        # Handle both ExecutionStep dataclass and dict forms
        step_success = last_step.success if hasattr(last_step, "success") else last_step.get("success")
        assert step_success is True, (
            f"Step should be success=True when CV click + state_change=True, got success={step_success}"
        )

    @pytest.mark.anyio
    async def test_executor_marks_cv_failed_when_no_state_change(self):
        """
        AC-ERROR-2: When state_change_check returns False, the executor must:
        - Mark the step as failed (success=False)
        - Include 'CV_CLICK_FAILED' in the error message for HITL context
        """
        from backend.engine import executor as executor_module

        state = self._make_minimal_state(ac_step_action_fail_count=3)
        mark_map = {
            "5": {"x": 450, "y": 300, "selector": "canvas#chart", "tag": "canvas", "text": ""},
        }

        mock_manager = MagicMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://two-test.vcreative.net"
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")
        mock_page.mouse = AsyncMock()
        mock_page.mouse.click = AsyncMock()
        mock_manager.page = mock_page

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=None),
            patch(
                "backend.engine.executor._dispatch_action",
                new_callable=AsyncMock,
                return_value={
                    "success": False,
                    "error_message": "NOT_VISIBLE: Canvas Sort",
                    "actual_url": "https://two-test.vcreative.net",
                },
            ),
            patch("backend.engine.executor.CvFallbackResolver") as MockResolver,
            patch("backend.engine.executor.cv_fallback_state_change_check", new_callable=AsyncMock, return_value=False),
            patch("backend.engine.executor.settings") as mock_settings,
        ):
            mock_settings.cv_fallback_enabled = True
            mock_settings.cv_fallback_min_dom_failures = 3

            resolver_instance = MagicMock()
            resolver_instance.should_activate.return_value = True
            resolver_instance.resolve = AsyncMock(return_value=(5, mark_map, 0.003))
            MockResolver.return_value = resolver_instance

            result_update = await executor_module.executor_node(state)

        # Step must be failure with HITL context
        steps = result_update.get("detailed_execution_log", [])
        assert len(steps) >= 1
        last_step = steps[-1]
        # Handle both ExecutionStep dataclass and dict forms
        step_success = last_step.success if hasattr(last_step, "success") else last_step.get("success")
        error_msg = (
            last_step.error_message if hasattr(last_step, "error_message") else last_step.get("error_message", "")
        ) or ""
        assert step_success is False, "Step should be failure when CV click fires but no state change detected"
        # Error message must carry CV_CLICK_FAILED context for HITL
        assert "CV_CLICK_FAILED" in error_msg or "CV_FALLBACK" in error_msg, (
            f"Error message must contain CV_CLICK_FAILED/CV_FALLBACK context, got: {error_msg!r}"
        )

    @pytest.mark.anyio
    async def test_state_change_check_not_called_when_cv_resolve_fails(self):
        """
        AC-ENTRY-1: When CV resolve() returns mark_id=None (LLM couldn't find target),
        cv_fallback_state_change_check() should NOT be called.
        """
        from backend.engine import executor as executor_module

        state = self._make_minimal_state(ac_step_action_fail_count=3)

        mock_manager = MagicMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://two-test.vcreative.net"
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")
        mock_manager.page = mock_page

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=None),
            patch(
                "backend.engine.executor._dispatch_action",
                new_callable=AsyncMock,
                return_value={
                    "success": False,
                    "error_message": "STRICT_MODE: Canvas Sort",
                    "actual_url": "https://two-test.vcreative.net",
                },
            ),
            patch("backend.engine.executor.CvFallbackResolver") as MockResolver,
            patch(
                "backend.engine.executor.cv_fallback_state_change_check", new_callable=AsyncMock, return_value=False
            ) as mock_state_check,
            patch("backend.engine.executor.settings") as mock_settings,
        ):
            mock_settings.cv_fallback_enabled = True
            mock_settings.cv_fallback_min_dom_failures = 3

            resolver_instance = MagicMock()
            resolver_instance.should_activate.return_value = True
            # mark_id=None → LLM resolution failed, no coordinate click fires
            resolver_instance.resolve = AsyncMock(return_value=(None, {}, 0.003))
            MockResolver.return_value = resolver_instance

            await executor_module.executor_node(state)

        # state_change_check must NOT be called when there's no CV click to verify
        mock_state_check.assert_not_awaited()
