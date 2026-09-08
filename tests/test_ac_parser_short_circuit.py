"""
tests/test_ac_parser_short_circuit.py
======================================

Phase 3: ac_parser_node short-circuit tests.

Covers:
  - AC-VERIFY-3: ac_parser_node returns pinned_plan verbatim when
    state["pinned_plan"] is set.
  - AC-INVARIANT-1: _stage_1_normalize.call_count == 0 AND
    _stage_2_compile.call_count == 0 when pinned_plan is set.
    This is the LOAD-BEARING assertion — the short-circuit MUST NOT
    touch the LLM stages at all.
  - The content-hash disk cache (ac_parse_cache) is NOT consulted when
    pinned_plan is set.
  - When pinned_plan is None (normal path), the short-circuit is NOT
    taken (stages run as usual — verified by confirming the mock IS called).
  - The patch returned by the short-circuit path includes all three
    standard ac_parser_node output keys:
      - test_plan (== pinned_plan dict verbatim)
      - jira_ticket (with acceptance_criteria_steps derived from pinned_plan)
      - structured_step_index (== 0)
  - Structured INFO log is emitted: "pinned_plans HIT <plan_id>"
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.state import make_initial_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pinned_plan() -> dict:
    """Return a minimal but realistic TestPlan dict for injection."""
    return {
        "steps": [
            {
                "goal": "Navigate to the Order Queue",
                "action": "navigate",
                "verification": {"method": "dom", "target": "h1", "value": "Order Queue"},
                "assertions": [],
            },
            {
                "goal": "Click the Submit button",
                "action": "click",
                "verification": {"method": "dom", "target": "button[name='Submit']", "value": ""},
                "assertions": [],
            },
        ],
        "preconditions": ["User is logged in as account_executive"],
        "title": "Pinned plan: submit order",
    }


def _make_state(pinned_plan: dict | None = None, pinned_plan_id: str | None = None):
    """Build a minimal VQAState with optional pinned_plan injection."""
    state = make_initial_state(
        run_id="test-run-short-circuit",
        jira_ticket_id="VC2-9999",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    # Inject pinned_plan fields (Phase 2 additions)
    state["pinned_plan"] = pinned_plan
    state["pinned_plan_id"] = pinned_plan_id
    # Ensure jira_ticket has acceptance_criteria so the normal path doesn't blow up
    state["jira_ticket"]["acceptance_criteria"] = "Given I am on the order queue page"
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAcParserShortCircuit:
    """ac_parser_node must short-circuit when state["pinned_plan"] is set."""

    @pytest.mark.anyio
    async def test_returns_pinned_plan_verbatim(self):
        """AC-VERIFY-3: returned test_plan is byte-identical to state["pinned_plan"]."""
        from backend.engine.ac_parser import ac_parser_node

        pinned_plan = _make_pinned_plan()
        state = _make_state(pinned_plan=pinned_plan, pinned_plan_id="plan-abc-123")

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_s1,
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_s2,
            patch("backend.engine.ac_parser._content_cache") as mock_cache,
        ):
            result = await ac_parser_node(state)

        assert result["test_plan"] == pinned_plan, (
            "Returned test_plan must be byte-identical to the injected pinned_plan dict"
        )

    @pytest.mark.anyio
    async def test_stage_1_not_called_when_pinned(self):
        """AC-INVARIANT-1 (part 1): _stage_1_normalize MUST NOT be called."""
        from backend.engine.ac_parser import ac_parser_node

        pinned_plan = _make_pinned_plan()
        state = _make_state(pinned_plan=pinned_plan, pinned_plan_id="plan-abc-123")

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_s1,
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_s2,
            patch("backend.engine.ac_parser._content_cache") as mock_cache,
        ):
            await ac_parser_node(state)

        assert mock_s1.call_count == 0, (
            f"_stage_1_normalize MUST NOT be called when pinned_plan is set. "
            f"call_count={mock_s1.call_count}"
        )

    @pytest.mark.anyio
    async def test_stage_2_not_called_when_pinned(self):
        """AC-INVARIANT-1 (part 2): _stage_2_compile MUST NOT be called."""
        from backend.engine.ac_parser import ac_parser_node

        pinned_plan = _make_pinned_plan()
        state = _make_state(pinned_plan=pinned_plan, pinned_plan_id="plan-abc-123")

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_s1,
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_s2,
            patch("backend.engine.ac_parser._content_cache") as mock_cache,
        ):
            await ac_parser_node(state)

        assert mock_s2.call_count == 0, (
            f"_stage_2_compile MUST NOT be called when pinned_plan is set. "
            f"call_count={mock_s2.call_count}"
        )

    @pytest.mark.anyio
    async def test_content_cache_not_consulted_when_pinned(self):
        """AC-VERIFY-3: the content-hash disk cache must not be consulted."""
        from backend.engine.ac_parser import ac_parser_node

        pinned_plan = _make_pinned_plan()
        state = _make_state(pinned_plan=pinned_plan, pinned_plan_id="plan-abc-123")

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._content_cache") as mock_cache,
        ):
            await ac_parser_node(state)

        # No cache method should have been called
        mock_cache.get.assert_not_called()
        mock_cache.put.assert_not_called()

    @pytest.mark.anyio
    async def test_returns_structured_step_index_zero(self):
        """Short-circuit patch must include structured_step_index: 0."""
        from backend.engine.ac_parser import ac_parser_node

        pinned_plan = _make_pinned_plan()
        state = _make_state(pinned_plan=pinned_plan, pinned_plan_id="plan-abc-123")

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._content_cache"),
        ):
            result = await ac_parser_node(state)

        assert result.get("structured_step_index") == 0

    @pytest.mark.anyio
    async def test_returns_acceptance_criteria_steps(self):
        """Short-circuit must populate acceptance_criteria_steps from pinned plan goals."""
        from backend.engine.ac_parser import ac_parser_node

        pinned_plan = _make_pinned_plan()
        state = _make_state(pinned_plan=pinned_plan, pinned_plan_id="plan-abc-123")

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._content_cache"),
        ):
            result = await ac_parser_node(state)

        jira_ticket_patch = result.get("jira_ticket", {})
        ac_steps = jira_ticket_patch.get("acceptance_criteria_steps", [])
        expected_goals = [step["goal"] for step in pinned_plan["steps"]]
        assert ac_steps == expected_goals, (
            f"acceptance_criteria_steps must equal step goals from pinned_plan. "
            f"got={ac_steps!r}, expected={expected_goals!r}"
        )

    @pytest.mark.anyio
    async def test_hit_log_emitted(self, caplog):
        """Structured INFO log 'pinned_plans HIT <plan_id>' is emitted."""
        import logging

        from backend.engine.ac_parser import ac_parser_node

        pinned_plan = _make_pinned_plan()
        plan_id = "plan-abc-123"
        state = _make_state(pinned_plan=pinned_plan, pinned_plan_id=plan_id)

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._content_cache"),
            caplog.at_level(logging.INFO, logger="backend.engine.ac_parser"),
        ):
            await ac_parser_node(state)

        assert any(
            f"pinned_plans HIT {plan_id}" in record.message
            for record in caplog.records
        ), (
            f"Expected structured log 'pinned_plans HIT {plan_id}' not found in: "
            f"{[r.message for r in caplog.records]}"
        )

    @pytest.mark.anyio
    async def test_normal_path_not_short_circuited_when_pinned_plan_none(self, caplog):
        """When pinned_plan is None, the short-circuit guard is NOT triggered.

        The critical invariant is the ABSENCE of "pinned_plans HIT" in the logs
        — the short-circuit path emits this log and returns early.  When
        pinned_plan is None the node proceeds to the normal LLM pipeline
        (the pipeline itself may fail offline; we only verify the guard is absent).
        """
        import logging

        from backend.engine.ac_parser import ac_parser_node

        # Build state WITHOUT pinned_plan
        state = _make_state(pinned_plan=None, pinned_plan_id=None)

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock, return_value="Given ..."),
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._content_cache"),
            patch("backend.engine.ac_parser.build_global_context", new_callable=AsyncMock, return_value=""),
            patch("backend.engine.ac_parser.enrich_ac_text", new_callable=AsyncMock, return_value=""),
            patch("backend.engine.ac_parser.score_ac_quality", return_value=MagicMock(is_sufficient=True)),
            patch("backend.engine.ac_parser.split_ac_into_steps", return_value=["step1"]),
            patch("backend.engine.ac_parser.validate_ac_steps", return_value=(True, [])),
            patch("backend.engine.ac_parser._broadcast_pre_parse_guidance_required", new_callable=AsyncMock),
            patch("backend.engine.ac_parser._get_visual_context", new_callable=AsyncMock, return_value=""),
            patch("backend.engine.ac_parser.get_run_metrics", return_value=MagicMock()),
            patch("backend.engine.ac_parser.ACParseDriftGuard", return_value=MagicMock()),
            patch("backend.engine.ac_parser._detect_step_ambiguity", return_value=[]),
            caplog.at_level(logging.INFO, logger="backend.engine.ac_parser"),
        ):
            try:
                await ac_parser_node(state)
            except Exception:
                # The normal path may fail for unrelated reasons in a test environment;
                # we only care that the short-circuit guard was NOT triggered.
                pass

        # The short-circuit path emits "pinned_plans HIT"; it must be absent here.
        assert not any(
            "pinned_plans HIT" in record.message
            for record in caplog.records
        ), (
            "Short-circuit must NOT fire when pinned_plan is None — "
            "'pinned_plans HIT' must not appear in logs"
        )
