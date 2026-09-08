"""
Tests for wall-clock and cost-USD circuit breakers (DR-008).

Validates that the evaluator_node enforces:
1. max_run_wall_clock_seconds — hard wall-clock limit per run
2. max_run_cost_usd — hard USD cost cap per run
3. Config defaults (1800s and $2.00)
4. Env var overrides

See: backend/engine/evaluator.py, backend/config.py
"""

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def base_state():
    """Minimal VQAState dict for evaluator_node tests."""
    return {
        "run_id": "run-test",
        "run_started_at": time.time(),  # Just started — well within limits
        "execution_mode": "headless",
        "active_profile": "vsuite",
        "execution_engine": "ai",
        "planner_iteration": 1,
        "max_planner_iterations": 500,
        "ac_step_index": 0,
        "ac_steps_completed": [],
        "ac_steps_skipped": [],
        "ac_steps_coverage_gap": [],
        "detailed_execution_log": [
            {
                "step_index": 0,
                "ac_step_index": 0,
                "action_type": "click",
                "action_payload": {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Submit"},
                "success": True,
                "error_message": None,
                "post_url": "https://qa.vcreative.net/dashboard",
                "post_element_count": 100,
            }
        ],
        "jira_ticket": {
            "acceptance_criteria_steps": ["Step 1", "Step 2"],
        },
        "role_context": {"role_name": "Account Executive", "role_key": "account_executive", "permissions": {}, "constraints": []},
        "planned_action": {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Submit"},
        "retry_count": 0,
        "max_retries": 3,
        "last_error": "",
        "agent_critique": "",
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "ac_step_failure_diary": [],
        "action_history_buffer": [],
        "action_repeat_counts": {},
        "current_ac_step_action_count": 1,
        "_prev_page_state_snapshot": None,
        "amnesic_loop_count": 0,
        "test_plan": None,
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "_verifier_verdict": "",
        "_verifier_confidence": 0.0,
        "failure_type": "",
        "debugger_attempted": False,
        "vision_mode_fail_count": 0,
        "current_page_url": "https://qa.vcreative.net/dashboard",
        "navigation_history": [],
        "browser_session_active": True,
        "dom_failure_diagnosis": "",
        "bug_log": [],
        "recovery_attempted_types": set(),
        "recovery_action_log": [],
        "deferred_verification_queue": [],
        "deferred_verification_failures": [],
        "deferred_verification_successes": [],
        "last_executor_fallback": "",
        "awaiting_human_takeover": False,
        "target_url": "https://qa.vcreative.net",
        # CV fallback fields
        "cv_fallback_invocations": 0,
        "expect_login_failure": False,
        "auth_gate_retry_count": 0,
        # ARIA pruning
        "target_element_types": [],
        "page_state_snapshot": "",
        "structured_step_index": 0,
        "current_sub_step_index": 0,
        "ac_step_iteration_budget": 30,
        "ac_step_iterations_used": 0,
    }


@pytest.fixture
def mock_metrics():
    """Mock RunMetrics with configurable estimated_cost_usd."""
    metrics = MagicMock()
    metrics.estimated_cost_usd = 0.50  # Under default $2.00 limit
    return metrics


class TestWallClockCircuitBreaker:
    """Tests for the wall-clock time limit."""

    @pytest.mark.asyncio
    async def test_wall_clock_under_limit_no_cb(self, base_state, mock_metrics):
        """Wall clock under limit → evaluator proceeds normally (no CB fired)."""
        from backend.engine.evaluator import evaluator_node

        # run_started_at is time.time() (just now) — well under 1800s
        with (
            patch("backend.engine.evaluator.get_run_metrics", return_value=mock_metrics),
            patch("backend.engine.evaluator.settings") as mock_settings,
        ):
            mock_settings.max_run_wall_clock_seconds = 1800
            mock_settings.max_run_cost_usd = 2.00
            mock_settings.max_retries = 3
            mock_settings.max_planner_iterations = 500

            result = await evaluator_node(base_state)
            # Should NOT fire wall-clock CB — normal evaluator routing
            assert result.get("failure_type") != "WALL_CLOCK_EXCEEDED"

    @pytest.mark.asyncio
    async def test_wall_clock_over_limit_fires_cb(self, base_state, mock_metrics):
        """Wall clock over limit → FAILED verdict with failure_type='WALL_CLOCK_EXCEEDED'."""
        from backend.engine.evaluator import evaluator_node

        # Set run_started_at to 2 hours ago — WAY over 1800s limit
        base_state["run_started_at"] = time.time() - 7200

        with (
            patch("backend.engine.evaluator.get_run_metrics", return_value=mock_metrics),
            patch("backend.engine.evaluator.settings") as mock_settings,
        ):
            mock_settings.max_run_wall_clock_seconds = 1800
            mock_settings.max_run_cost_usd = 2.00
            mock_settings.max_retries = 3
            mock_settings.max_planner_iterations = 500

            result = await evaluator_node(base_state)
            assert result["failure_type"] == "WALL_CLOCK_EXCEEDED"
            assert result["_next_node"] == "reporter"


class TestCostCircuitBreaker:
    """Tests for the cost USD limit."""

    @pytest.mark.asyncio
    async def test_cost_under_limit_no_cb(self, base_state, mock_metrics):
        """Cost under limit → evaluator proceeds normally (no CB fired)."""
        from backend.engine.evaluator import evaluator_node

        mock_metrics.estimated_cost_usd = 0.50  # Under $2.00

        with (
            patch("backend.engine.evaluator.get_run_metrics", return_value=mock_metrics),
            patch("backend.engine.evaluator.settings") as mock_settings,
        ):
            mock_settings.max_run_wall_clock_seconds = 1800
            mock_settings.max_run_cost_usd = 2.00
            mock_settings.max_retries = 3
            mock_settings.max_planner_iterations = 500

            result = await evaluator_node(base_state)
            assert result.get("failure_type") != "COST_BUDGET_EXCEEDED"

    @pytest.mark.asyncio
    async def test_cost_over_limit_fires_cb(self, base_state, mock_metrics):
        """Cost over limit → FAILED verdict with failure_type='COST_BUDGET_EXCEEDED'."""
        from backend.engine.evaluator import evaluator_node

        mock_metrics.estimated_cost_usd = 5.00  # Over $2.00

        with (
            patch("backend.engine.evaluator.get_run_metrics", return_value=mock_metrics),
            patch("backend.engine.evaluator.settings") as mock_settings,
        ):
            mock_settings.max_run_wall_clock_seconds = 1800
            mock_settings.max_run_cost_usd = 2.00
            mock_settings.max_retries = 3
            mock_settings.max_planner_iterations = 500

            result = await evaluator_node(base_state)
            assert result["failure_type"] == "COST_BUDGET_EXCEEDED"
            assert result["_next_node"] == "reporter"


class TestConfigDefaults:
    """Tests that config fields have correct defaults."""

    def test_wall_clock_default(self):
        """max_run_wall_clock_seconds defaults to 1800."""
        from backend.config import Settings

        s = Settings()
        assert s.max_run_wall_clock_seconds == 1800

    def test_cost_default(self):
        """max_run_cost_usd defaults to 2.00."""
        from backend.config import Settings

        s = Settings()
        assert s.max_run_cost_usd == 2.00


class TestEnvVarOverrides:
    """Tests that env vars override config defaults."""

    def test_wall_clock_env_override(self):
        """MAX_RUN_WALL_CLOCK_SECONDS env var overrides default."""
        from backend.config import Settings

        with patch.dict("os.environ", {"MAX_RUN_WALL_CLOCK_SECONDS": "3600"}, clear=False):
            s = Settings()
            assert s.max_run_wall_clock_seconds == 3600

    def test_cost_env_override(self):
        """MAX_RUN_COST_USD env var overrides default."""
        from backend.config import Settings

        with patch.dict("os.environ", {"MAX_RUN_COST_USD": "5.00"}, clear=False):
            s = Settings()
            assert s.max_run_cost_usd == 5.00
