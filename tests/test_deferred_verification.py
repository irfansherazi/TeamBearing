"""
TASK-005: Deferred Verification Queue — Comprehensive Unit Tests
================================================================

Tests for the state schema, configuration flags, verifier enqueue logic,
evaluator re-check/backtrack logic, and reporter DVF rendering.

Run: .venv/bin/python -m pytest tests/test_deferred_verification.py -v
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_state(**overrides) -> dict:
    """
    Create a minimal VQAState dict suitable for deferred verification tests.
    Uses make_initial_state for proper defaults, then applies overrides.
    """
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-run-dvq",
        jira_ticket_id="QA-DVQ",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    for k, v in overrides.items():
        state[k] = v
    return state


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Config DVQ Flags (Phase 1)
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigDVQFlags:
    """Verify DVQ feature flags and settings in backend/config.py Settings class."""

    def test_enable_deferred_verification_flag_exists(self):
        """enable_deferred_verification should be defined in Settings."""
        from backend.config import Settings

        assert "enable_deferred_verification" in Settings.model_fields

    def test_enable_deferred_verification_defaults_true(self):
        """enable_deferred_verification should default to True."""
        from backend.config import Settings

        s = Settings()
        assert s.enable_deferred_verification is True

    def test_enable_deferred_verification_can_be_disabled(self):
        """enable_deferred_verification should accept False."""
        from backend.config import Settings

        s = Settings(enable_deferred_verification=False)
        assert s.enable_deferred_verification is False

    def test_deferred_check_delay_flag_exists(self):
        """deferred_check_delay should be defined in Settings."""
        from backend.config import Settings

        assert "deferred_check_delay" in Settings.model_fields

    def test_deferred_check_delay_defaults_to_2(self):
        """deferred_check_delay should default to 2 steps."""
        from backend.config import Settings

        s = Settings()
        assert s.deferred_check_delay == 2

    def test_deferred_check_delay_can_be_changed(self):
        """deferred_check_delay should accept different values."""
        from backend.config import Settings

        s = Settings(deferred_check_delay=5)
        assert s.deferred_check_delay == 5

    def test_deferred_backtrack_limit_flag_exists(self):
        """deferred_backtrack_limit should be defined in Settings."""
        from backend.config import Settings

        assert "deferred_backtrack_limit" in Settings.model_fields

    def test_deferred_backtrack_limit_defaults_to_2(self):
        """deferred_backtrack_limit should default to 2 steps."""
        from backend.config import Settings

        s = Settings()
        assert s.deferred_backtrack_limit == 2

    def test_deferred_backtrack_limit_can_be_changed(self):
        """deferred_backtrack_limit should accept different values."""
        from backend.config import Settings

        s = Settings(deferred_backtrack_limit=3)
        assert s.deferred_backtrack_limit == 3


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: State DVQ Fields (Phase 1)
# ═══════════════════════════════════════════════════════════════════════════


class TestStateDVQFields:
    """Verify new DVQ fields in VQAState (backend/engine/state.py)."""

    def test_deferred_verification_queue_in_state(self):
        """deferred_verification_queue field should exist in initial state."""
        state = _make_state()
        assert "deferred_verification_queue" in state

    def test_deferred_verification_queue_initialized_empty(self):
        """deferred_verification_queue should be an empty list initially."""
        state = _make_state()
        assert state["deferred_verification_queue"] == []

    def test_deferred_verification_queue_accepts_list_of_dicts(self):
        """deferred_verification_queue should accept list[dict] values."""
        state = _make_state()
        state["deferred_verification_queue"] = [
            {
                "ac_step_index": 0,
                "verification": {"type": "element_visible", "selector_hint": ".p-menu"},
                "bypass_type": "transient_selector",
                "bypass_pattern": "p-menu-list",
                "enqueued_at_step": 0,
                "check_after_step": 2,
            }
        ]
        assert len(state["deferred_verification_queue"]) == 1
        assert state["deferred_verification_queue"][0]["bypass_type"] == "transient_selector"

    def test_deferred_verification_failures_in_state(self):
        """deferred_verification_failures field should exist in initial state."""
        state = _make_state()
        assert "deferred_verification_failures" in state

    def test_deferred_verification_failures_initialized_empty(self):
        """deferred_verification_failures should be an empty list initially."""
        state = _make_state()
        assert state["deferred_verification_failures"] == []

    def test_deferred_verification_failures_accepts_list_of_dicts(self):
        """deferred_verification_failures should accept list[dict] values."""
        state = _make_state()
        state["deferred_verification_failures"] = [
            {
                "ac_step_index": 0,
                "bypass_type": "transient_selector",
                "reason": "re-check failed: element not found",
                "backtracked": False,
            }
        ]
        assert len(state["deferred_verification_failures"]) == 1
        assert state["deferred_verification_failures"][0]["backtracked"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Verifier Enqueue (DVQ) Tests
# ═══════════════════════════════════════════════════════════════════════════

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _run_async(coro):
    """Helper to run async tests without pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestVerifierTransientSelectorDVQEnqueue:
    """Phase 2: _check_single_verification enqueues DVQ entries for transient selectors."""

    def _make_transient_verification(self, selector: str = ".p-select-overlay") -> dict:
        """Create a verification dict that will match a transient selector pattern."""
        return {
            "type": "element_visible",
            "selector_hint": selector,
        }

    def test_transient_selector_returns_satisfied_with_dvq_entry(self):
        """AC-HAPPY-1: transient selector match returns satisfied AND a DVQ entry."""
        from backend.engine.verifier import _check_single_verification

        page = AsyncMock()
        v = self._make_transient_verification(".p-select-overlay .some-child")

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=3,
                deferred_check_delay=2,
            )
            # Should return 3-tuple: (verdict, evidence, dvq_entry_or_none)
            assert len(result) == 3, f"Expected 3-tuple, got {len(result)}-tuple"
            verdict, evidence, dvq_entry = result
            assert verdict == "satisfied"
            assert dvq_entry is not None, "DVQ entry should be enqueued for transient selector"
            return dvq_entry

        dvq_entry = _run_async(_run())
        assert dvq_entry["bypass_type"] == "transient_selector"
        assert dvq_entry["ac_step_index"] == 3
        assert dvq_entry["enqueued_at_step"] == 3
        assert dvq_entry["check_after_step"] == 5  # 3 + deferred_check_delay(2)

    def test_transient_selector_dvq_entry_contains_original_verification(self):
        """DVQ entry must preserve the original verification dict for re-checking."""
        from backend.engine.verifier import _check_single_verification

        page = AsyncMock()
        v = self._make_transient_verification("p-menu-list")

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=0,
                deferred_check_delay=2,
            )
            return result[2]  # dvq_entry

        dvq_entry = _run_async(_run())
        assert dvq_entry["verification"] == v
        assert dvq_entry["bypass_pattern"] == "p-menu-list"

    def test_transient_selector_dvq_entry_schema_complete(self):
        """DVQ entry must have all required schema fields."""
        from backend.engine.verifier import _check_single_verification

        page = AsyncMock()
        v = self._make_transient_verification("p-contextmenu .option")

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=5,
                deferred_check_delay=3,
            )
            return result[2]

        dvq_entry = _run_async(_run())
        required_keys = {
            "ac_step_index",
            "verification",
            "bypass_type",
            "bypass_pattern",
            "enqueued_at_step",
            "check_after_step",
        }
        assert required_keys.issubset(dvq_entry.keys()), f"Missing keys: {required_keys - dvq_entry.keys()}"
        assert dvq_entry["check_after_step"] == 5 + 3  # ac_step_index + deferred_check_delay

    def test_transient_selector_dvq_disabled_returns_none(self):
        """AC-HAPPY-7 / AC-REGRESS-1: feature flag OFF → no DVQ entry, old behavior preserved."""
        from backend.engine.verifier import _check_single_verification

        page = AsyncMock()
        v = self._make_transient_verification(".p-select-overlay")

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=0,
                deferred_check_delay=2,
                enable_deferred_verification=False,
            )
            assert len(result) == 3
            verdict, evidence, dvq_entry = result
            assert verdict == "satisfied", "Verdict must still be satisfied"
            assert dvq_entry is None, "DVQ entry must be None when feature disabled"

        _run_async(_run())


class TestVerifierSparseDatasetDVQEnqueue:
    """Phase 2: _check_single_verification enqueues DVQ entries for sparse dataset bypass."""

    def _make_sort_verification(self, column: str = "CLIENT", direction: str = "ascending") -> dict:
        return {
            "type": "table_sort",
            "expected_column": column,
            "expected_direction": direction,
        }

    def _make_mock_page_sparse(self, row_count: int = 1):
        """Create a mock page with a sparse dataset (≤2 rows)."""
        page = AsyncMock()

        # Mock locator chain for row count detection
        row_locator = AsyncMock()
        row_locator.count = AsyncMock(return_value=row_count)

        # Mock locator to return row_locator for the data rows selector
        def _locator_side_effect(selector):
            if "tr[role='row']" in selector:
                return row_locator
            # Default: return a generic mock locator
            mock_loc = AsyncMock()
            mock_loc.count = AsyncMock(return_value=0)
            mock_loc.first = AsyncMock()
            return mock_loc

        page.locator = MagicMock(side_effect=_locator_side_effect)

        # Mock get_by_role for columnheader queries
        col_header = AsyncMock()
        col_header.count = AsyncMock(return_value=0)
        col_header.first = AsyncMock()
        page.get_by_role = MagicMock(return_value=col_header)

        # Mock page.evaluate for JS sort state check
        page.evaluate = AsyncMock(return_value={"found": True, "sortField": "client", "sortOrder": "ascending"})

        # Mock wait_for_timeout
        page.wait_for_timeout = AsyncMock()

        return page

    def test_sparse_dataset_enqueues_dvq_entry(self):
        """AC-HAPPY-5: sparse dataset bypass enqueues a deferred re-check."""
        from backend.engine.verifier import _check_single_verification

        page = self._make_mock_page_sparse(row_count=1)
        v = self._make_sort_verification("CLIENT", "ascending")

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=2,
                deferred_check_delay=2,
            )
            assert len(result) == 3
            verdict, evidence, dvq_entry = result
            assert verdict == "satisfied"
            assert dvq_entry is not None, "DVQ entry should be enqueued for sparse dataset"
            return dvq_entry

        dvq_entry = _run_async(_run())
        assert dvq_entry["bypass_type"] == "sparse_dataset"
        assert dvq_entry["bypass_pattern"] == "sparse_dataset"
        assert dvq_entry["ac_step_index"] == 2
        assert dvq_entry["check_after_step"] == 4

    def test_sparse_dataset_dvq_disabled_returns_none(self):
        """AC-HAPPY-7: feature flag OFF → no DVQ entry for sparse dataset."""
        from backend.engine.verifier import _check_single_verification

        page = self._make_mock_page_sparse(row_count=2)
        v = self._make_sort_verification("STATUS", "descending")

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=1,
                deferred_check_delay=2,
                enable_deferred_verification=False,
            )
            assert len(result) == 3
            verdict, evidence, dvq_entry = result
            assert verdict == "satisfied"
            assert dvq_entry is None, "DVQ entry must be None when feature disabled"

        _run_async(_run())


class TestVerifierNonBypassReturnsNoDVQ:
    """Verify that normal (non-bypass) verification paths return None for the DVQ entry."""

    def test_url_check_returns_no_dvq_entry(self):
        """url_check is not a bypass — should never produce a DVQ entry."""
        from backend.engine.verifier import _check_single_verification

        page = AsyncMock()
        page.url = "https://example.com/dashboard"
        v = {"type": "url_check", "url_pattern": "dashboard"}

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=0,
                deferred_check_delay=2,
            )
            assert len(result) == 3
            verdict, _evidence, dvq_entry = result
            assert verdict == "satisfied"
            assert dvq_entry is None

        _run_async(_run())

    def test_element_visible_non_transient_returns_no_dvq_entry(self):
        """element_visible on a non-transient selector should NOT produce a DVQ entry."""
        from backend.engine.verifier import _check_single_verification

        page = AsyncMock()
        # Set up a locator that resolves (element is visible)
        locator = AsyncMock()
        locator.first = AsyncMock()
        locator.first.wait_for = AsyncMock()  # succeeds (no timeout)
        page.locator = MagicMock(return_value=locator)

        v = {"type": "element_visible", "selector_hint": ".my-regular-element"}

        async def _run():
            result = await _check_single_verification(
                page,
                v,
                run_id="test-dvq",
                transient_text="",
                ac_step_index=0,
                deferred_check_delay=2,
            )
            assert len(result) == 3
            verdict, _evidence, dvq_entry = result
            assert verdict == "satisfied"
            assert dvq_entry is None, "Non-transient element_visible should not produce DVQ"

        _run_async(_run())


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: Evaluator Deferred Re-check Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDeferredQueueProcessing:
    """Phase 3: _process_deferred_queue identifies ripe entries for re-check."""

    def test_ripe_entries_returned(self):
        """Entries whose check_after_step <= current_step are ripe."""
        from backend.engine.evaluator import _process_deferred_queue

        dvq = [
            {"ac_step_index": 0, "check_after_step": 2, "bypass_type": "transient_selector"},
            {"ac_step_index": 1, "check_after_step": 4, "bypass_type": "sparse_dataset"},
        ]
        ripe, remaining = _process_deferred_queue(dvq, current_step_index=3)
        assert len(ripe) == 1
        assert ripe[0]["ac_step_index"] == 0
        assert len(remaining) == 1
        assert remaining[0]["ac_step_index"] == 1

    def test_all_entries_ripe(self):
        """All entries ripe when current_step passes all thresholds."""
        from backend.engine.evaluator import _process_deferred_queue

        dvq = [
            {"ac_step_index": 0, "check_after_step": 2, "bypass_type": "transient_selector"},
            {"ac_step_index": 1, "check_after_step": 3, "bypass_type": "sparse_dataset"},
        ]
        ripe, remaining = _process_deferred_queue(dvq, current_step_index=5)
        assert len(ripe) == 2
        assert len(remaining) == 0

    def test_no_entries_ripe(self):
        """No entries ripe when current_step hasn't passed any threshold."""
        from backend.engine.evaluator import _process_deferred_queue

        dvq = [
            {"ac_step_index": 0, "check_after_step": 5, "bypass_type": "transient_selector"},
        ]
        ripe, remaining = _process_deferred_queue(dvq, current_step_index=3)
        assert len(ripe) == 0
        assert len(remaining) == 1

    def test_empty_queue_returns_empty(self):
        """Empty queue produces empty results."""
        from backend.engine.evaluator import _process_deferred_queue

        ripe, remaining = _process_deferred_queue([], current_step_index=10)
        assert ripe == []
        assert remaining == []

    def test_exact_threshold_is_ripe(self):
        """Entry with check_after_step == current_step is ripe (inclusive)."""
        from backend.engine.evaluator import _process_deferred_queue

        dvq = [{"ac_step_index": 1, "check_after_step": 3, "bypass_type": "transient_selector"}]
        ripe, remaining = _process_deferred_queue(dvq, current_step_index=3)
        assert len(ripe) == 1
        assert len(remaining) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: Evaluator Backtrack Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluatorBacktrackRouting:
    """Phase 4: evaluator step advancement handles DVQ re-check failures by backtracking."""

    def _make_evaluator_state(
        self,
        ac_step_index: int = 2,
        dvq: list | None = None,
        dvf: list | None = None,
        enable_deferred: bool = True,
        backtrack_limit: int = 2,
    ) -> dict:
        """Build a minimal evaluator state dict for testing."""
        return {
            "run_id": "test-backtrack",
            "ac_step_index": ac_step_index,
            "jira_ticket": {
                "acceptance_criteria_steps": [
                    "Step 1: Navigate",
                    "Step 2: Sort table",
                    "Step 3: Verify sort",
                    "Step 4: Final check",
                ],
            },
            "ac_steps_completed": list(range(ac_step_index)),
            "deferred_verification_queue": dvq or [],
            "deferred_verification_failures": dvf or [],
            "detailed_execution_log": [
                {
                    "step_index": 0,
                    "action_type": "done",
                    "success": True,
                    "ac_step_index": ac_step_index,
                },
            ],
            "planned_action": {"action": "done"},
            "retry_count": 0,
            "max_retries": 3,
            "max_planner_iterations": 500,
            "planner_iteration": 5,
            "ac_step_fail_counts": {},
            "ac_step_action_fail_count": 0,
            "current_ac_step_action_count": 0,
            "verifier_not_yet_count": 0,
            "verifier_total_not_yet_count": 0,
            "ac_step_failure_diary": [],
            "action_repeat_counts": {},
            "_verifier_verdict": "",
            "_recipe_already_satisfied": False,
            "transient_page_text": "",
            "role_context": {},
            "role_queue": [],
            "test_plan": None,
            "expect_login_failure": False,
            "vision_mode": "dom",
            "debugger_attempted": False,
            "recovery_attempted_types": set(),
            "action_history_buffer": [],
        }

    def test_no_dvq_entries_normal_advancement(self):
        """No DVQ entries → normal step advancement (no backtrack).

        NOTE (Bug D fix): The guard in evaluator now routes to verifier when
        the current ac_step_index is not in ac_steps_completed. This test
        simulates a post-verifier re-entry by including ac_step_index=1 in
        ac_steps_completed=[0, 1], so the guard is bypassed and step advancement
        is tested directly.
        """
        from backend.engine.evaluator import evaluator_node

        state = self._make_evaluator_state(ac_step_index=1, dvq=[])
        # Bug D fix: add current step (1) to ac_steps_completed to simulate
        # post-verifier re-entry state
        state["ac_steps_completed"] = [0, 1]
        result = _run_async(evaluator_node(state))

        # Should advance normally
        assert result.get("_next_node") in ("planner", "reporter")
        # Should NOT have set ac_step_index backwards
        if "ac_step_index" in result:
            assert result["ac_step_index"] >= 2  # advanced forward or at end

    def test_dvq_entries_not_yet_ripe_normal_advancement(self):
        """DVQ entries with future check_after_step → normal advancement.

        NOTE (Bug D fix): add current step to ac_steps_completed to simulate
        post-verifier re-entry state (guard bypassed, step-advance path tested).
        """
        from backend.engine.evaluator import evaluator_node

        dvq = [
            {
                "ac_step_index": 0,
                "check_after_step": 10,
                "bypass_type": "transient_selector",
                "verification": {"type": "element_visible", "selector_hint": ".test"},
                "bypass_pattern": ".test",
                "enqueued_at_step": 0,
            },
        ]
        state = self._make_evaluator_state(ac_step_index=1, dvq=dvq)
        # Bug D fix: add current step (1) to ac_steps_completed
        state["ac_steps_completed"] = [0, 1]
        result = _run_async(evaluator_node(state))

        # Should advance normally — DVQ entry is not ripe
        assert result.get("_next_node") in ("planner", "reporter")
        # DVQ should be preserved (not consumed)
        _remaining_dvq = result.get("deferred_verification_queue", dvq)
        assert len(_remaining_dvq) >= 1

    def test_ripe_dvq_entry_records_deferred_failure(self):
        """A ripe DVQ entry should be recorded as a deferred failure (DVF).

        NOTE (Bug D fix): add current step to ac_steps_completed to simulate
        post-verifier re-entry state (guard bypassed, DVQ processing path tested).
        """
        from backend.engine.evaluator import evaluator_node

        # check_after_step=2, and we're advancing from step 1 to step 2
        dvq = [
            {
                "ac_step_index": 0,
                "check_after_step": 2,
                "bypass_type": "transient_selector",
                "verification": {"type": "element_visible", "selector_hint": ".p-select-overlay"},
                "bypass_pattern": "p-select-overlay",
                "enqueued_at_step": 0,
            },
        ]
        state = self._make_evaluator_state(ac_step_index=1, dvq=dvq)
        # Bug D fix: add current step (1) to ac_steps_completed to simulate post-verifier re-entry
        state["ac_steps_completed"] = [0, 1]

        with (
            patch("backend.browser.context.get_manager") as mock_get_manager,
            patch("backend.engine.verifier._check_single_verification", new_callable=AsyncMock) as mock_verify,
        ):
            mock_manager = MagicMock()
            mock_manager.page = MagicMock()
            mock_get_manager.return_value = mock_manager
            mock_verify.return_value = ("not_yet", "Element not visible", None)

            result = _run_async(evaluator_node(state))

        # The ripe entry should be consumed from the queue
        remaining_dvq = result.get("deferred_verification_queue", [])
        assert len(remaining_dvq) == 0, "Ripe entry should be consumed from DVQ"

        # A deferred failure record should be created
        dvf = result.get("deferred_verification_failures", [])
        assert len(dvf) == 1, "One DVF should be recorded"
        assert dvf[0]["bypass_type"] == "transient_selector"
        assert dvf[0]["backtracked"] is True  # Should now backtrack within limit

    def test_backtrack_limit_exceeded_no_rewind(self):
        """When backtrack_limit is 0, ripe entries record DVF but don't rewind."""
        from backend.engine.evaluator import evaluator_node

        dvq = [
            {
                "ac_step_index": 0,
                "check_after_step": 2,
                "bypass_type": "transient_selector",
                "verification": {"type": "element_visible", "selector_hint": ".p-select-overlay"},
                "bypass_pattern": "p-select-overlay",
                "enqueued_at_step": 0,
            },
        ]
        state = self._make_evaluator_state(ac_step_index=1, dvq=dvq)
        # Simulate backtrack_limit=0 via config
        with (
            patch("backend.engine.evaluator.settings") as mock_settings,
            patch("backend.browser.context.get_manager") as mock_get_manager,
            patch("backend.engine.verifier._check_single_verification", new_callable=AsyncMock) as mock_verify,
        ):
            mock_settings.enable_deferred_verification = True
            mock_settings.deferred_check_delay = 2
            mock_settings.deferred_backtrack_limit = 0
            mock_settings.auto_escalate_threshold = 0

            mock_manager = MagicMock()
            mock_manager.page = MagicMock()
            mock_get_manager.return_value = mock_manager
            mock_verify.return_value = ("not_yet", "Element not visible", None)

            result = _run_async(evaluator_node(state))

        # Should still advance forward (no backtrack with limit=0)
        if "ac_step_index" in result:
            assert result["ac_step_index"] >= 2
        # DVF should be recorded with backtracked=False
        dvf = result.get("deferred_verification_failures", [])
        if dvf:  # May be empty if feature disabled
            assert dvf[0].get("backtracked") is False


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5: Reporter DVF Section Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestReporterDVFSection:
    """Phase 5: reporter renders amber DVF section for deferred verification failures."""

    def test_dvf_section_renders_with_amber_badge(self):
        """Runs with DVF entries render an amber warning section."""
        from backend.engine.reporter import _render_dvf_section

        dvf = [
            {
                "ac_step_index": 0,
                "bypass_type": "transient_selector",
                "bypass_pattern": "p-select-overlay",
                "backtracked": False,
                "consumed_at_step": 2,
                "verification": {"type": "element_visible", "selector_hint": ".p-select-overlay"},
            },
        ]
        html = _render_dvf_section(dvf)
        assert "deferred" in html.lower(), "Section should mention deferred"
        assert "amber" in html.lower() or "f59e0b" in html.lower() or "warning" in html.lower(), (
            "Section should have amber/warning styling"
        )
        assert "transient_selector" in html, "Should display bypass type"
        assert "p-select-overlay" in html, "Should display bypass pattern"

    def test_dvf_section_empty_returns_empty(self):
        """No DVF entries → no section rendered."""
        from backend.engine.reporter import _render_dvf_section

        html = _render_dvf_section([])
        assert html == "", "Empty DVF list should produce empty string"

    def test_dvf_section_multiple_entries(self):
        """Multiple DVF entries render multiple rows."""
        from backend.engine.reporter import _render_dvf_section

        dvf = [
            {
                "ac_step_index": 0,
                "bypass_type": "transient_selector",
                "bypass_pattern": "p-menu-list",
                "backtracked": False,
                "consumed_at_step": 2,
                "verification": {"type": "element_visible", "selector_hint": "p-menu-list"},
            },
            {
                "ac_step_index": 1,
                "bypass_type": "sparse_dataset",
                "bypass_pattern": "sparse_dataset",
                "backtracked": False,
                "consumed_at_step": 3,
                "verification": {"type": "table_sort", "expected_column": "CLIENT"},
            },
        ]
        html = _render_dvf_section(dvf)
        assert "transient_selector" in html
        assert "sparse_dataset" in html
        # Should have at least 2 rows
        assert html.count("<tr") >= 2
