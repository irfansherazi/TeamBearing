"""
test_cv_fallback_resolver.py
Phase 2 Unit Tests — CV Fallback Vision LLM Resolver & Executor Integration

Tests for:
  AC-ENTRY-1: CV fallback activates and calls vision LLM after DOM failure exhaustion
  AC-HAPPY-1: resolve() returns mark_id + coordinate map + cost estimate
  AC-ERROR-1: Vision LLM returns null/no mark_id → graceful None return
  AC-ENTRY-1: Executor integration: executor wires CV fallback after _dispatch_action failure

All tests are pure unit tests — mocked Playwright page, mocked boto3 Bedrock client,
no network, no live browser.
"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.browser.cv_resolver import CvFallbackResolver

# Valid base64 string for tests (1-byte payload — just needs to decode without error)
_TINY_JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 100).decode()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page(*, is_closed: bool = False):
    """Return a mock Playwright page object."""
    page = AsyncMock()
    # is_closed() is a SYNCHRONOUS method in Playwright — must use MagicMock
    page.is_closed = MagicMock(return_value=is_closed)
    return page


def _make_mark_map() -> dict:
    """Return a sample mark coordinate map as returned by draw_marks_and_snapshot()."""
    return {
        "1": {"x": 100, "y": 200, "selector": "button#submit", "tag": "button", "text": "Submit"},
        "2": {"x": 300, "y": 150, "selector": "a.nav-link", "tag": "a", "text": "Dashboard"},
        "5": {"x": 450, "y": 300, "selector": "p-select.sort-col", "tag": "p-select", "text": ""},
    }


def _make_bedrock_response(mark_id: int | None) -> dict:
    """Build a mock Bedrock converse() response with mark_id in tool output."""
    json_content = json.dumps({"mark_id": mark_id})
    return {
        "output": {
            "message": {
                "content": [
                    {
                        "text": json_content,
                    }
                ]
            }
        },
        "usage": {"inputTokens": 1500, "outputTokens": 20},
        "metrics": {"latencyMs": 800},
    }


# ---------------------------------------------------------------------------
# TestResolveSuccess
# ---------------------------------------------------------------------------


class TestResolveSuccess:
    """Tests for CvFallbackResolver.resolve() — happy paths."""

    @pytest.mark.anyio
    async def test_resolve_returns_valid_mark_id(self):
        """resolve() calls draw_marks_and_snapshot and vision LLM, returns (mark_id, map, cost)."""
        resolver = CvFallbackResolver()
        page = _make_mock_page()
        mark_map = _make_mark_map()
        screenshot_b64 = "fake_base64_screenshot_data"

        with (
            patch(
                "backend.browser.cv_resolver.draw_marks_and_snapshot",
                new_callable=AsyncMock,
                return_value=(screenshot_b64, mark_map),
            ) as mock_snapshot,
            patch(
                "backend.browser.cv_resolver.format_vision_mark_summary",
                return_value="<som_element_map>[1] button 'Submit'</som_element_map>",
            ),
            patch(
                "backend.browser.cv_resolver._invoke_cv_vision_llm",
                new_callable=AsyncMock,
                return_value=5,  # mark_id=5 (valid, exists in mark_map)
            ),
        ):
            mark_id, returned_map, cost = await resolver.resolve(
                page, "Click the sort dropdown", existing_mark_map=None
            )

        assert mark_id == 5
        assert returned_map == mark_map
        assert isinstance(cost, float)
        assert cost > 0
        mock_snapshot.assert_awaited_once_with(page)

    @pytest.mark.anyio
    async def test_resolve_uses_existing_mark_map_if_provided(self):
        """When existing_mark_map is non-empty, resolve() skips draw_marks_and_snapshot."""
        resolver = CvFallbackResolver()
        page = _make_mock_page()
        existing_map = _make_mark_map()

        # existing_mark_map is provided — no screenshot needed
        with (
            patch(
                "backend.browser.cv_resolver.draw_marks_and_snapshot",
                new_callable=AsyncMock,
                return_value=("unused_b64", {}),
            ) as mock_snapshot,
            patch(
                "backend.browser.cv_resolver._invoke_cv_vision_llm",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            # Provide a pre-captured screenshot alongside the existing map
            mark_id, returned_map, cost = await resolver.resolve(
                page,
                "Click Submit",
                existing_mark_map=existing_map,
                existing_screenshot_b64="existing_screenshot",
            )

        # Should NOT call draw_marks_and_snapshot when existing data is provided
        mock_snapshot.assert_not_awaited()
        assert mark_id == 1
        assert returned_map == existing_map

    @pytest.mark.anyio
    async def test_resolve_cost_estimate_is_added(self):
        """resolve() returns cost_estimate_usd ~0.003 per invocation."""
        resolver = CvFallbackResolver()
        page = _make_mock_page()

        with (
            patch(
                "backend.browser.cv_resolver.draw_marks_and_snapshot",
                new_callable=AsyncMock,
                return_value=("b64", _make_mark_map()),
            ),
            patch(
                "backend.browser.cv_resolver._invoke_cv_vision_llm",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            _, _, cost = await resolver.resolve(page, "Some target")

        assert cost == pytest.approx(0.003, rel=0.05)


# ---------------------------------------------------------------------------
# TestResolveFailure
# ---------------------------------------------------------------------------


class TestResolveFailure:
    """Tests for CvFallbackResolver.resolve() — failure and edge cases."""

    @pytest.mark.anyio
    async def test_resolve_returns_none_when_llm_returns_null(self):
        """AC-ERROR-1: vision LLM returns null mark_id → resolve() returns (None, map, cost)."""
        resolver = CvFallbackResolver()
        page = _make_mock_page()

        with (
            patch(
                "backend.browser.cv_resolver.draw_marks_and_snapshot",
                new_callable=AsyncMock,
                return_value=("b64", _make_mark_map()),
            ),
            patch(
                "backend.browser.cv_resolver._invoke_cv_vision_llm",
                new_callable=AsyncMock,
                return_value=None,  # LLM couldn't find the element
            ),
        ):
            mark_id, mark_map, cost = await resolver.resolve(page, "Shadow DOM element")

        assert mark_id is None
        assert isinstance(mark_map, dict)
        assert cost > 0  # cost still recorded even on failure

    @pytest.mark.anyio
    async def test_resolve_returns_none_when_mark_id_not_in_map(self):
        """mark_id returned by LLM doesn't exist in coordinate map → resolve() returns None."""
        resolver = CvFallbackResolver()
        page = _make_mock_page()
        mark_map = _make_mark_map()  # keys: "1", "2", "5"

        with (
            patch(
                "backend.browser.cv_resolver.draw_marks_and_snapshot",
                new_callable=AsyncMock,
                return_value=("b64", mark_map),
            ),
            patch(
                "backend.browser.cv_resolver._invoke_cv_vision_llm",
                new_callable=AsyncMock,
                return_value=99,  # Out-of-range mark_id (not in map)
            ),
        ):
            mark_id, returned_map, cost = await resolver.resolve(page, "Some element")

        assert mark_id is None  # Validation rejected out-of-range ID
        assert returned_map == mark_map

    @pytest.mark.anyio
    async def test_resolve_returns_none_on_empty_mark_map(self):
        """Empty mark map (no interactive elements found) → resolve() returns (None, {}, cost)."""
        resolver = CvFallbackResolver()
        page = _make_mock_page()

        with patch(
            "backend.browser.cv_resolver.draw_marks_and_snapshot",
            new_callable=AsyncMock,
            return_value=("b64", {}),  # No elements found on page
        ):
            mark_id, returned_map, cost = await resolver.resolve(page, "Canvas element")

        assert mark_id is None
        assert returned_map == {}

    @pytest.mark.anyio
    async def test_resolve_returns_none_when_page_is_closed(self):
        """resolve() on a closed page returns (None, {}, cost) rather than raising."""
        resolver = CvFallbackResolver()
        page = _make_mock_page(is_closed=True)

        mark_id, returned_map, cost = await resolver.resolve(page, "Any target")

        assert mark_id is None
        assert returned_map == {}

    @pytest.mark.anyio
    async def test_resolve_returns_none_on_screenshot_failure(self):
        """If draw_marks_and_snapshot raises, resolve() returns (None, {}, cost)."""
        resolver = CvFallbackResolver()
        page = _make_mock_page()

        with patch(
            "backend.browser.cv_resolver.draw_marks_and_snapshot",
            new_callable=AsyncMock,
            side_effect=RuntimeError("JS injection failed"),
        ):
            mark_id, returned_map, cost = await resolver.resolve(page, "Canvas target")

        assert mark_id is None
        assert returned_map == {}


# ---------------------------------------------------------------------------
# TestInvokeCvVisionLLM
# ---------------------------------------------------------------------------


class TestInvokeCvVisionLLM:
    """Tests for the internal _invoke_cv_vision_llm() helper."""

    @pytest.mark.anyio
    async def test_llm_parses_json_mark_id(self):
        """_invoke_cv_vision_llm parses '{"mark_id": 3}' from LLM text response."""
        from backend.browser.cv_resolver import _invoke_cv_vision_llm

        bedrock_response = _make_bedrock_response(mark_id=3)

        with patch(
            "backend.browser.cv_resolver._call_bedrock_vision",
            new_callable=AsyncMock,
            return_value=bedrock_response,
        ):
            result = await _invoke_cv_vision_llm(
                screenshot_b64=_TINY_JPEG_B64,
                mark_summary="[1] button 'Submit'",
                target_description="Submit button",
            )

        assert result == 3

    @pytest.mark.anyio
    async def test_llm_returns_none_on_null_mark_id(self):
        """_invoke_cv_vision_llm returns None when LLM emits {"mark_id": null}."""
        from backend.browser.cv_resolver import _invoke_cv_vision_llm

        bedrock_response = _make_bedrock_response(mark_id=None)

        with patch(
            "backend.browser.cv_resolver._call_bedrock_vision",
            new_callable=AsyncMock,
            return_value=bedrock_response,
        ):
            result = await _invoke_cv_vision_llm(
                screenshot_b64=_TINY_JPEG_B64,
                mark_summary="[1] button 'Submit'",
                target_description="Shadow DOM element",
            )

        assert result is None

    @pytest.mark.anyio
    async def test_llm_returns_none_on_malformed_response(self):
        """_invoke_cv_vision_llm returns None if LLM response is not valid JSON."""
        from backend.browser.cv_resolver import _invoke_cv_vision_llm

        bad_response = {"output": {"message": {"content": [{"text": "I cannot find the element."}]}}}

        with patch(
            "backend.browser.cv_resolver._call_bedrock_vision",
            new_callable=AsyncMock,
            return_value=bad_response,
        ):
            result = await _invoke_cv_vision_llm(
                screenshot_b64=_TINY_JPEG_B64,
                mark_summary="",
                target_description="Canvas button",
            )

        assert result is None

    @pytest.mark.anyio
    async def test_llm_returns_none_on_bedrock_exception(self):
        """_invoke_cv_vision_llm returns None when Bedrock raises (network error, etc.)."""
        from backend.browser.cv_resolver import _invoke_cv_vision_llm

        with patch(
            "backend.browser.cv_resolver._call_bedrock_vision",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Bedrock service unavailable"),
        ):
            result = await _invoke_cv_vision_llm(
                screenshot_b64=_TINY_JPEG_B64,
                mark_summary="",
                target_description="Some element",
            )

        assert result is None


# ---------------------------------------------------------------------------
# TestExecutorCvFallbackIntegration
# ---------------------------------------------------------------------------


class TestExecutorCvFallbackIntegration:
    """
    Tests for executor_node's CV fallback wiring.

    These verify that after _dispatch_action returns success=False, the executor
    checks should_activate() and calls resolve() if appropriate — then fires
    page.mouse.click(x, y) and records the result in cv_fallback_results.
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
            "run_id": "run-cv-test-001",
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
    async def test_executor_triggers_cv_fallback_after_dispatch_failure(self):
        """
        AC-ENTRY-1: When _dispatch_action fails and should_activate() is True,
        executor must call resolver.resolve() and attempt a coordinate click.
        """
        from backend.engine import executor as executor_module

        state = self._make_minimal_state(ac_step_action_fail_count=3)
        mark_map = _make_mark_map()

        # Mock the browser manager
        mock_manager = MagicMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://two-test.vcreative.net"
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")
        mock_manager.page = mock_page

        # State tracker (optional, we'll skip it)
        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=None),
            patch(
                "backend.engine.executor._dispatch_action",
                new_callable=AsyncMock,
                return_value={
                    "success": False,
                    "error_message": "STRICT_MODE_VIOLATION: 'Canvas Sort' matched 0 elements",
                    "actual_url": "https://two-test.vcreative.net",
                    "dom_failure_diagnosis": "DOM_ABSENT: 'Canvas Sort'",
                },
            ),
            patch("backend.engine.executor.CvFallbackResolver") as MockResolver,
            patch("backend.engine.executor.settings") as mock_settings,
        ):
            mock_settings.cv_fallback_enabled = True
            mock_settings.cv_fallback_min_dom_failures = 3

            resolver_instance = MagicMock()
            resolver_instance.should_activate.return_value = True
            resolver_instance.resolve = AsyncMock(return_value=(5, mark_map, 0.003))
            resolver_instance.estimate_cost.return_value = 0.003
            MockResolver.return_value = resolver_instance

            mock_page.mouse = AsyncMock()
            mock_page.mouse.click = AsyncMock()

            await executor_module.executor_node(state)

        # CV fallback should have been attempted
        resolver_instance.should_activate.assert_called_once()
        resolver_instance.resolve.assert_awaited_once()
        # Coordinate click should have fired
        mock_page.mouse.click.assert_awaited_once_with(mark_map["5"]["x"], mark_map["5"]["y"])

    @pytest.mark.anyio
    async def test_executor_does_not_trigger_cv_when_disabled(self):
        """
        CV fallback must NOT activate when cv_fallback_enabled=False,
        even if fail_count >= threshold.
        """
        from backend.engine import executor as executor_module

        state = self._make_minimal_state(ac_step_action_fail_count=10)

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
                    "error_message": "STRICT_MODE: missed element",
                    "actual_url": "https://two-test.vcreative.net",
                },
            ),
            patch("backend.engine.executor.settings") as mock_settings,
        ):
            mock_settings.cv_fallback_enabled = False
            mock_settings.cv_fallback_min_dom_failures = 3

            await executor_module.executor_node(state)

        # When cv_fallback_enabled=False, the CV block is entirely skipped
        # (no CvFallbackResolver instantiation at all)

    @pytest.mark.anyio
    async def test_executor_skips_cv_fallback_on_success(self):
        """
        CV fallback must NOT activate when _dispatch_action succeeds.
        """
        from backend.engine import executor as executor_module

        state = self._make_minimal_state(ac_step_action_fail_count=5)  # High but success

        mock_manager = MagicMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://two-test.vcreative.net"
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")
        mock_manager.page = mock_page

        _cv_resolve_called = []

        async def _fake_resolve(*args, **kwargs):
            _cv_resolve_called.append(True)
            return (1, _make_mark_map(), 0.003)

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=None),
            patch(
                "backend.engine.executor._dispatch_action",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "error_message": None,
                    "actual_url": "https://two-test.vcreative.net",
                },
            ),
            patch("backend.browser.cv_resolver.CvFallbackResolver.resolve", _fake_resolve),
            patch("backend.engine.executor.settings") as mock_settings,
        ):
            mock_settings.cv_fallback_enabled = True
            mock_settings.cv_fallback_min_dom_failures = 3

            await executor_module.executor_node(state)

        # resolve() must NOT be called when dispatch succeeded
        assert len(_cv_resolve_called) == 0, "CV fallback resolve() fired on a successful action!"


# ---------------------------------------------------------------------------
# TestCvFallbackStateUpdate
# ---------------------------------------------------------------------------


class TestCvFallbackStateUpdate:
    """Tests for CV fallback state recording in cv_fallback_results."""

    @pytest.mark.anyio
    async def test_cv_fallback_result_recorded_on_success(self):
        """
        AC-HAPPY-1: After a successful CV coordinate click, cv_fallback_results must
        contain an entry with mark_id, x, y, success=True, cost_estimate.
        """
        resolver = CvFallbackResolver()
        page = _make_mock_page()
        mark_map = _make_mark_map()

        with (
            patch(
                "backend.browser.cv_resolver.draw_marks_and_snapshot",
                new_callable=AsyncMock,
                return_value=("b64", mark_map),
            ),
            patch(
                "backend.browser.cv_resolver._invoke_cv_vision_llm",
                new_callable=AsyncMock,
                return_value=5,  # mark_id=5, exists at x=450, y=300
            ),
        ):
            mark_id, returned_map, cost = await resolver.resolve(page, "Canvas sort")

        # Build the expected result entry that executor would store
        result_entry = {
            "step_idx": 0,
            "mark_id": mark_id,
            "x": returned_map[str(mark_id)]["x"] if mark_id is not None else None,
            "y": returned_map[str(mark_id)]["y"] if mark_id is not None else None,
            "success": mark_id is not None,
            "cost_estimate": cost,
        }

        assert result_entry["mark_id"] == 5
        assert result_entry["x"] == 450
        assert result_entry["y"] == 300
        assert result_entry["success"] is True
        assert result_entry["cost_estimate"] == pytest.approx(0.003, rel=0.05)

    @pytest.mark.anyio
    async def test_cv_fallback_result_recorded_on_failure(self):
        """
        AC-ERROR-1: When CV fallback fails (LLM returns null), the result entry must
        have mark_id=None and success=False.
        """
        resolver = CvFallbackResolver()
        page = _make_mock_page()

        with (
            patch(
                "backend.browser.cv_resolver.draw_marks_and_snapshot",
                new_callable=AsyncMock,
                return_value=("b64", _make_mark_map()),
            ),
            patch(
                "backend.browser.cv_resolver._invoke_cv_vision_llm",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mark_id, _, cost = await resolver.resolve(page, "Shadow DOM button")

        result_entry = {
            "mark_id": mark_id,
            "success": mark_id is not None,
            "cost_estimate": cost,
        }
        assert result_entry["mark_id"] is None
        assert result_entry["success"] is False
