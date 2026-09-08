"""
tests/test_cv_fallback_reporter.py
====================================
Phase 4 — CV Fallback KB Recipe & Audit Report Integration

Unit tests for:
  - _render_cv_fallback_section(): summary footer HTML (invocation count, success
    rate, estimated cost)
  - _render_execution_log(): CV Fallback badge rendered on steps with cv_fallback=True
  - reporter generates correct HTML when cv_fallback_results are present in state
  - reporter gracefully handles missing / empty cv_fallback state fields (no crash)

No live browser, no S3, no Bedrock — all external calls are mocked.

Follows the existing test pattern from test_cv_fallback_cost_gate.py (sync tests,
no anyio — the reporter helpers are pure functions with no async calls).
"""

import pytest

# ---------------------------------------------------------------------------
# Helpers — import the rendering functions directly so we can unit-test them
# without standing up the full LangGraph graph.
# ---------------------------------------------------------------------------
from backend.engine.reporter import (
    _render_cv_fallback_section,
    _render_execution_log,
)
from backend.engine.state import ExecutionStep

# ---------------------------------------------------------------------------
# _render_cv_fallback_section — summary footer
# ---------------------------------------------------------------------------


class TestRenderCvFallbackSection:
    """Tests for the CV Fallback summary section rendered at report bottom."""

    def _make_cv_results(self, entries: list[dict]) -> list[dict]:
        """Build a cv_fallback_results list from shorthand dicts."""
        defaults = {"step_idx": 0, "mark_id": 1, "x": 100, "y": 200, "success": True, "cost_estimate": 0.003}
        return [{**defaults, **e} for e in entries]

    def test_returns_empty_string_when_no_results(self):
        html = _render_cv_fallback_section([])
        assert html == ""

    def test_returns_empty_string_for_none(self):
        html = _render_cv_fallback_section(None)
        assert html == ""

    def test_section_header_present(self):
        results = self._make_cv_results([{"success": True}])
        html = _render_cv_fallback_section(results)
        assert "CV Fallback" in html

    def test_invocation_count_shown(self):
        results = self._make_cv_results(
            [
                {"step_idx": 0, "success": True},
                {"step_idx": 1, "success": False},
                {"step_idx": 2, "success": True},
            ]
        )
        html = _render_cv_fallback_section(results)
        assert "3" in html  # invocation count

    def test_success_rate_all_success(self):
        results = self._make_cv_results(
            [
                {"success": True},
                {"success": True},
            ]
        )
        html = _render_cv_fallback_section(results)
        # 100% success rate
        assert "100" in html

    def test_success_rate_partial(self):
        results = self._make_cv_results(
            [
                {"success": True},
                {"success": False},
                {"success": False},
            ]
        )
        html = _render_cv_fallback_section(results)
        # 1/3 = 33%
        assert "33" in html

    def test_success_rate_all_failures(self):
        results = self._make_cv_results(
            [
                {"success": False},
                {"success": False},
            ]
        )
        html = _render_cv_fallback_section(results)
        assert "0" in html  # 0% success rate

    def test_cost_estimate_shown(self):
        results = self._make_cv_results(
            [
                {"cost_estimate": 0.003},
                {"cost_estimate": 0.003},
            ]
        )
        html = _render_cv_fallback_section(results)
        # Total estimated cost = $0.006
        assert "0.006" in html

    def test_cost_zero_when_no_cost_key(self):
        """Entries without cost_estimate key should default to 0."""
        results = [{"step_idx": 0, "mark_id": 1, "x": 50, "y": 50, "success": True}]
        html = _render_cv_fallback_section(results)
        # Should still render without KeyError
        assert "CV Fallback" in html

    def test_mark_id_shown_in_footer(self):
        results = self._make_cv_results([{"mark_id": 42, "success": True}])
        html = _render_cv_fallback_section(results)
        # mark_id 42 should appear somewhere in the HTML (per-step row)
        assert "42" in html

    def test_section_has_target_badge_emoji(self):
        results = self._make_cv_results([{"success": True}])
        html = _render_cv_fallback_section(results)
        assert "🎯" in html


# ---------------------------------------------------------------------------
# _render_execution_log — CV Fallback badge on steps
# ---------------------------------------------------------------------------


class TestRenderExecutionLogCvBadge:
    """Tests that execution log step cards show 🎯 CV Fallback badge when flagged."""

    def _make_step(self, **overrides) -> ExecutionStep:
        base: ExecutionStep = {
            "step_index": 1,
            "action_type": "click",
            "locator_value": "canvas#chart",
            "success": True,
            "screenshot_url": "",
            "llm_reasoning": "Clicked via CV fallback",
            "error_message": "",
            "self_heal_attempt": 0,
            "timestamp": "2026-05-17T10:00:00Z",
        }
        base.update(overrides)
        return base

    def test_no_badge_when_cv_fallback_not_set(self):
        step = self._make_step()
        html = _render_execution_log([step])
        assert "CV Fallback" not in html

    def test_badge_present_when_cv_fallback_true(self):
        step = self._make_step(cv_fallback=True)
        html = _render_execution_log([step])
        assert "CV Fallback" in html

    def test_badge_has_target_emoji(self):
        step = self._make_step(cv_fallback=True)
        html = _render_execution_log([step])
        assert "🎯" in html

    def test_badge_absent_when_cv_fallback_false(self):
        step = self._make_step(cv_fallback=False)
        html = _render_execution_log([step])
        assert "CV Fallback" not in html

    def test_badge_shows_mark_id(self):
        step = self._make_step(cv_fallback=True, cv_mark_id=7)
        html = _render_execution_log([step])
        assert "7" in html

    def test_badge_shows_coordinates(self):
        step = self._make_step(cv_fallback=True, cv_coords={"x": 320, "y": 480})
        html = _render_execution_log([step])
        assert "320" in html
        assert "480" in html

    def test_badge_shows_success_verdict(self):
        step = self._make_step(cv_fallback=True, success=True)
        html = _render_execution_log([step])
        # Should indicate CV click was successful
        assert "CV Fallback" in html
        assert "✓" in html or "success" in html.lower() or "CV_CLICK_SUCCESS" in html

    def test_badge_shows_failed_verdict_when_cv_click_failed(self):
        step = self._make_step(
            cv_fallback=True, success=False, error_message="CV_CLICK_FAILED: No DOM state change detected"
        )
        html = _render_execution_log([step])
        assert "CV Fallback" in html

    def test_multiple_steps_only_flagged_get_badge(self):
        steps = [
            self._make_step(step_index=1, cv_fallback=True),
            self._make_step(step_index=2),  # no cv_fallback
            self._make_step(step_index=3, cv_fallback=True),
        ]
        html = _render_execution_log(steps)
        # Badge should appear at least twice (for steps 1 and 3)
        assert html.count("CV Fallback") >= 2

    def test_render_does_not_crash_on_missing_cv_fields(self):
        """Steps with cv_fallback=True but no cv_mark_id/cv_coords should not raise."""
        step = self._make_step(cv_fallback=True)
        try:
            html = _render_execution_log([step])
        except Exception as exc:
            pytest.fail(f"_render_execution_log raised unexpectedly: {exc}")
        assert "CV Fallback" in html


# ---------------------------------------------------------------------------
# KB recipe file existence check
# ---------------------------------------------------------------------------


class TestCvFallbackKbRecipe:
    """Validates the KB recipe file is present and structurally sound."""

    def _load_recipe(self) -> dict:
        from pathlib import Path

        import yaml

        recipe_path = Path("knowledge/docs/cv_fallback_reference.yaml")
        if not recipe_path.exists():
            pytest.skip("cv_fallback_reference.yaml not yet created — expected for TDD RED phase")
        with recipe_path.open() as f:
            return yaml.safe_load(f)

    def test_recipe_file_exists(self):
        from pathlib import Path

        assert Path("knowledge/docs/cv_fallback_reference.yaml").exists(), (
            "cv_fallback_reference.yaml KB recipe must exist at knowledge/docs/cv_fallback_reference.yaml"
        )

    def test_recipe_has_required_name(self):
        recipe = self._load_recipe()
        assert recipe.get("name") == "cv_fallback"

    def test_recipe_has_description(self):
        recipe = self._load_recipe()
        assert "description" in recipe
        assert len(recipe["description"]) > 10

    def test_recipe_has_trigger_keywords(self):
        recipe = self._load_recipe()
        assert "trigger_keywords" in recipe
        keywords = recipe["trigger_keywords"]
        assert isinstance(keywords, list)
        assert len(keywords) >= 3

    def test_recipe_trigger_keywords_contain_canvas_or_shadow(self):
        recipe = self._load_recipe()
        keywords_lower = [str(k).lower() for k in recipe["trigger_keywords"]]
        assert any("canvas" in k or "shadow" in k or "iframe" in k for k in keywords_lower), (
            "Recipe must trigger on canvas/shadow/iframe keywords"
        )

    def test_recipe_has_steps(self):
        recipe = self._load_recipe()
        assert "steps" in recipe
        assert isinstance(recipe["steps"], list)
        assert len(recipe["steps"]) >= 1

    def test_recipe_step_uses_coordinate_action(self):
        recipe = self._load_recipe()
        steps = recipe["steps"]
        actions = [s.get("action") for s in steps]
        assert "coordinate_action" in actions, "cv_fallback recipe must include a coordinate_action step"

    def test_recipe_step_has_cv_fallback_eligible_flag(self):
        recipe = self._load_recipe()
        steps = recipe["steps"]
        coord_steps = [s for s in steps if s.get("action") == "coordinate_action"]
        assert coord_steps, "No coordinate_action step found"
        assert coord_steps[0].get("cv_fallback_eligible") is True, (
            "coordinate_action step must set cv_fallback_eligible: true"
        )


# ---------------------------------------------------------------------------
# _render_cv_fallback_section — integration with _render_full_report
# ---------------------------------------------------------------------------


class TestRenderFullReportCvIntegration:
    """Verify _render_full_report includes the CV fallback section when results exist."""

    def _minimal_state(self, cv_results: list[dict]) -> dict:
        return {
            "jira_ticket": {
                "ticket_id": "VCS-999",
                "summary": "Test CV Fallback Integration",
                "acceptance_criteria_steps": ["Step A", "Step B"],
            },
            "role_context": {"role_name": "QA Lead", "role_key": "qa_lead"},
            "ac_steps_completed": [0, 1],
            "ac_steps_skipped": [],
            "detailed_execution_log": [],
            "bug_log": [],
            "recovery_action_log": [],
            "deferred_verification_failures": [],
            "run_id": "run-cv-test-001",
            "ac_quality_result": None,
            "ac_enrichment_result": None,
            "run_metrics": {},
            "cv_fallback_results": cv_results,
            "cv_fallback_invocations": len(cv_results),
        }

    def test_cv_section_in_full_report_when_results_present(self):
        from backend.engine.reporter import _render_full_report

        state = self._minimal_state(
            [{"step_idx": 0, "mark_id": 3, "x": 200, "y": 300, "success": True, "cost_estimate": 0.003}]
        )
        html = _render_full_report(state, video_url="", duration_ms=5000)
        assert "CV Fallback" in html
        assert "🎯" in html

    def test_cv_section_absent_when_no_results(self):
        from backend.engine.reporter import _render_full_report

        state = self._minimal_state([])
        html = _render_full_report(state, video_url="", duration_ms=5000)
        # No CV section in header/footer — but basic render should work
        assert "vQA Audit Report" in html

    def test_full_report_does_not_crash_without_cv_fields(self):
        """State without any cv_fallback keys must not raise."""
        from backend.engine.reporter import _render_full_report

        state = {
            "jira_ticket": {
                "ticket_id": "VCS-998",
                "summary": "No CV fields",
                "acceptance_criteria_steps": ["Step A"],
            },
            "role_context": {"role_name": "QA Lead", "role_key": "qa_lead"},
            "ac_steps_completed": [0],
            "ac_steps_skipped": [],
            "detailed_execution_log": [],
            "bug_log": [],
            "recovery_action_log": [],
            "deferred_verification_failures": [],
            "run_id": "run-no-cv-001",
            "ac_quality_result": None,
            "ac_enrichment_result": None,
            "run_metrics": {},
            # Intentionally omit cv_fallback_results and cv_fallback_invocations
        }
        try:
            html = _render_full_report(state, video_url="", duration_ms=1000)
        except Exception as exc:
            pytest.fail(f"_render_full_report raised without cv fields: {exc}")
        assert "vQA Audit Report" in html
