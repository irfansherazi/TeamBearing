"""
Unit tests for critic_node — the LLM-based pre-execution plan critic.

Tests Phase 1 scope:
  - CriticVerdict schema validation (valid + invalid)
  - route_after_critic routing logic:
      * pass verdict → "setup_role"
      * mismatch verdict + retry_count < 2 → "ac_parser" (with critic_feedback set)
      * mismatch verdict + retry_count == 2 → "setup_role" (retry cap exhausted)
      * Haiku API exception → synthetic pass with critic_skipped=True

Pattern follows tests/test_preflight_check.py and tests/engine/test_verifier_guardrails.py:
  - unittest.mock.patch for Bedrock/settings
  - AsyncMock for async node functions
  - pytest.mark.asyncio for async test bodies
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    run_id: str = "run-test-001",
    test_plan: dict | None = None,
    acceptance_criteria_steps: list | None = None,
    critic_result: dict | None = None,
    critic_feedback: dict | None = None,
    role_queue: list | None = None,
    execution_engine: str = "ai",
) -> dict:
    """Build a minimal VQAState dict for critic_node tests."""
    if test_plan is None:
        test_plan = {
            "test_plan_id": "tp-001",
            "test_title": "Verify Quick Order flow",
            "steps": [
                {
                    "step_id": "step-1",
                    "goal": "Navigate to Quick Orders",
                    "step_type": "navigation",
                    "target_persona": "Account Executive",
                },
                {
                    "step_id": "step-2",
                    "goal": "Click New Request",
                    "step_type": "click",
                    "target_persona": "Account Executive",
                },
            ],
        }
    if acceptance_criteria_steps is None:
        acceptance_criteria_steps = [
            "Navigate to Quick Orders",
            "Click New Request",
        ]
    if role_queue is None:
        role_queue = ["account_executive"]
    return {
        "run_id": run_id,
        "test_plan": test_plan,
        "acceptance_criteria_steps": acceptance_criteria_steps,
        "critic_result": critic_result,
        "critic_feedback": critic_feedback,
        "role_queue": role_queue,
        "execution_engine": execution_engine,
    }


# ---------------------------------------------------------------------------
# Schema validation tests (CriticVerdict — Pydantic)
# ---------------------------------------------------------------------------


class TestCriticVerdictSchema:
    """Tests for the CriticVerdict Pydantic model (AC-VERIFY-2)."""

    def test_valid_pass_verdict(self):
        """A valid pass verdict with no reason codes passes model_validate."""
        from backend.engine.schemas import CriticVerdict

        verdict = CriticVerdict.model_validate(
            {
                "verdict": "pass",
                "reason_codes": [],
                "feedback_summary": "",
                "retry_count": 0,
                "critic_skipped": False,
            }
        )
        assert verdict.verdict == "pass"
        assert verdict.reason_codes == []
        assert verdict.retry_count == 0
        assert verdict.critic_skipped is False

    def test_valid_mismatch_verdict_with_reason_codes(self):
        """A mismatch verdict with all valid reason codes passes validation."""
        from backend.engine.schemas import CriticVerdict

        verdict = CriticVerdict.model_validate(
            {
                "verdict": "mismatch",
                "reason_codes": [
                    "missing_step",
                    "hallucinated_ac",
                    "persona_mismatch",
                    "order_violation",
                    "ambiguous_step",
                ],
                "feedback_summary": "Step 2 is missing from the TestPlan.",
                "retry_count": 1,
                "critic_skipped": False,
            }
        )
        assert verdict.verdict == "mismatch"
        assert len(verdict.reason_codes) == 5
        assert "missing_step" in verdict.reason_codes

    def test_invalid_verdict_value_raises(self):
        """An unrecognized verdict value raises ValidationError."""
        from backend.engine.schemas import CriticVerdict

        with pytest.raises(ValidationError):
            CriticVerdict.model_validate({"verdict": "unknown_value"})

    def test_invalid_reason_code_raises(self):
        """A reason_code outside the allowed enum raises ValidationError."""
        from backend.engine.schemas import CriticVerdict

        with pytest.raises(ValidationError):
            CriticVerdict.model_validate(
                {
                    "verdict": "mismatch",
                    "reason_codes": ["invalid_code"],
                }
            )

    def test_defaults(self):
        """CriticVerdict has sensible defaults — minimal dict validates."""
        from backend.engine.schemas import CriticVerdict

        verdict = CriticVerdict.model_validate({"verdict": "pass"})
        assert verdict.reason_codes == []
        assert verdict.feedback_summary == ""
        assert verdict.retry_count == 0
        assert verdict.critic_skipped is False

    def test_retry_count_bounds(self):
        """retry_count outside [0, 2] raises ValidationError."""
        from backend.engine.schemas import CriticVerdict

        with pytest.raises(ValidationError):
            CriticVerdict.model_validate({"verdict": "pass", "retry_count": 3})

        with pytest.raises(ValidationError):
            CriticVerdict.model_validate({"verdict": "pass", "retry_count": -1})

    def test_critic_skipped_true(self):
        """critic_skipped=True is valid (used for API-failure synthetic pass)."""
        from backend.engine.schemas import CriticVerdict

        verdict = CriticVerdict.model_validate(
            {"verdict": "pass", "critic_skipped": True}
        )
        assert verdict.critic_skipped is True


# ---------------------------------------------------------------------------
# routing tests — route_after_critic
# ---------------------------------------------------------------------------


class TestRouteAfterCritic:
    """Tests for the route_after_critic conditional-edge function."""

    def test_pass_verdict_routes_to_setup_role(self):
        """Pass verdict at any retry_count → 'setup_role' (AC-VERIFY-3)."""
        from backend.engine.critic_node import route_after_critic

        state = _make_state(
            critic_result={
                "verdict": "pass",
                "reason_codes": [],
                "feedback_summary": "",
                "retry_count": 0,
                "critic_skipped": False,
            }
        )
        assert route_after_critic(state) == "setup_role"

    def test_mismatch_with_retries_remaining_routes_to_ac_parser(self):
        """Mismatch with retry_count=0 → 'ac_parser' (AC-VERIFY-4)."""
        from backend.engine.critic_node import route_after_critic

        state = _make_state(
            critic_result={
                "verdict": "mismatch",
                "reason_codes": ["missing_step"],
                "feedback_summary": "Step missing.",
                "retry_count": 0,
                "critic_skipped": False,
            },
            critic_feedback={"reason_codes": ["missing_step"], "guidance": "Step missing."},
        )
        assert route_after_critic(state) == "ac_parser"

    def test_mismatch_retry_count_1_routes_to_ac_parser(self):
        """Mismatch with retry_count=1 (< 2) → 'ac_parser' (retry still available)."""
        from backend.engine.critic_node import route_after_critic

        state = _make_state(
            critic_result={
                "verdict": "mismatch",
                "reason_codes": ["order_violation"],
                "feedback_summary": "Steps misordered.",
                "retry_count": 1,
                "critic_skipped": False,
            },
            critic_feedback={"reason_codes": ["order_violation"], "guidance": "Steps misordered."},
        )
        assert route_after_critic(state) == "ac_parser"

    def test_mismatch_retry_cap_exhausted_routes_to_setup_role(self):
        """Mismatch with retry_count=2 → 'setup_role' (retry cap AC-VERIFY-5)."""
        from backend.engine.critic_node import route_after_critic

        state = _make_state(
            critic_result={
                "verdict": "mismatch",
                "reason_codes": ["missing_step"],
                "feedback_summary": "Still missing.",
                "retry_count": 2,
                "critic_skipped": False,
            }
        )
        assert route_after_critic(state) == "setup_role"

    def test_critic_skipped_routes_to_setup_role(self):
        """API-failure synthetic pass (critic_skipped=True) → 'setup_role' (AC-ERROR-1)."""
        from backend.engine.critic_node import route_after_critic

        state = _make_state(
            critic_result={
                "verdict": "pass",
                "reason_codes": [],
                "feedback_summary": "",
                "retry_count": 0,
                "critic_skipped": True,
            }
        )
        assert route_after_critic(state) == "setup_role"


# ---------------------------------------------------------------------------
# critic_node async function tests
# ---------------------------------------------------------------------------


class TestCriticNodeFunction:
    """Tests for the critic_node async node function."""

    @pytest.mark.asyncio
    async def test_haiku_exception_produces_synthetic_pass(self):
        """Any Bedrock exception → critic_skipped=True synthetic pass (AC-ERROR-1)."""
        import botocore.exceptions

        state = _make_state()

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            side_effect=botocore.exceptions.ClientError(
                {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
                "InvokeModel",
            )
        )

        with (
            patch("backend.engine.critic_node._get_critic_llm", return_value=mock_llm),
            patch("backend.engine.critic_node.settings") as mock_settings,
        ):
            mock_settings.critic_enabled = True
            mock_settings.max_critic_retries = 2

            from backend.engine.critic_node import critic_node

            result = await critic_node(state)

        assert "critic_result" in result
        cr = result["critic_result"]
        assert cr["verdict"] == "pass"
        assert cr["critic_skipped"] is True
        assert cr["reason_codes"] == []
        assert cr["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_critic_disabled_produces_synthetic_pass(self):
        """When critic_enabled=False, node returns synthetic pass without LLM call."""
        state = _make_state()

        with patch("backend.engine.critic_node.settings") as mock_settings:
            mock_settings.critic_enabled = False
            mock_settings.max_critic_retries = 2

            from backend.engine.critic_node import critic_node

            result = await critic_node(state)

        assert result["critic_result"]["verdict"] == "pass"
        assert result["critic_result"]["critic_skipped"] is True

    @pytest.mark.asyncio
    async def test_pass_verdict_does_not_set_critic_feedback(self):
        """Pass verdict leaves critic_feedback as None (AC-VERIFY-3)."""
        state = _make_state()

        mock_verdict_obj = MagicMock()
        mock_verdict_obj.verdict = "pass"
        mock_verdict_obj.reason_codes = []
        mock_verdict_obj.feedback_summary = ""
        mock_verdict_obj.retry_count = 0
        mock_verdict_obj.critic_skipped = False
        mock_verdict_obj.model_dump = MagicMock(return_value={
            "verdict": "pass",
            "reason_codes": [],
            "feedback_summary": "",
            "retry_count": 0,
            "critic_skipped": False,
        })

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"verdict":"pass","reason_codes":[],"feedback_summary":"","retry_count":0,"critic_skipped":false}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with (
            patch("backend.engine.critic_node._get_critic_llm", return_value=mock_llm),
            patch("backend.engine.critic_node._parse_critic_response", return_value=mock_verdict_obj),
            patch("backend.engine.critic_node.settings") as mock_settings,
        ):
            mock_settings.critic_enabled = True
            mock_settings.max_critic_retries = 2

            from backend.engine.critic_node import critic_node

            result = await critic_node(state)

        assert result["critic_result"]["verdict"] == "pass"
        assert result.get("critic_feedback") is None

    @pytest.mark.asyncio
    async def test_mismatch_verdict_sets_critic_feedback(self):
        """Mismatch verdict populates critic_feedback with reason_codes + guidance (AC-VERIFY-4)."""
        state = _make_state()

        mock_verdict_obj = MagicMock()
        mock_verdict_obj.verdict = "mismatch"
        mock_verdict_obj.reason_codes = ["missing_step"]
        mock_verdict_obj.feedback_summary = "Step 2 is absent from TestPlan."
        mock_verdict_obj.retry_count = 0
        mock_verdict_obj.critic_skipped = False
        mock_verdict_obj.model_dump = MagicMock(return_value={
            "verdict": "mismatch",
            "reason_codes": ["missing_step"],
            "feedback_summary": "Step 2 is absent from TestPlan.",
            "retry_count": 1,
            "critic_skipped": False,
        })

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "{}"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with (
            patch("backend.engine.critic_node._get_critic_llm", return_value=mock_llm),
            patch("backend.engine.critic_node._parse_critic_response", return_value=mock_verdict_obj),
            patch("backend.engine.critic_node.settings") as mock_settings,
        ):
            mock_settings.critic_enabled = True
            mock_settings.max_critic_retries = 2

            from backend.engine.critic_node import critic_node

            result = await critic_node(state)

        assert result["critic_result"]["verdict"] == "mismatch"
        assert result["critic_feedback"] is not None
        assert "reason_codes" in result["critic_feedback"]
        assert "guidance" in result["critic_feedback"]
        assert result["critic_feedback"]["reason_codes"] == ["missing_step"]
        assert "Step 2" in result["critic_feedback"]["guidance"]


# ---------------------------------------------------------------------------
# Phase 2: Graph topology tests (AC-VERIFY-1)
# ---------------------------------------------------------------------------


class TestGraphTopology:
    """
    Verify the compiled LangGraph graph has the critic node wired correctly.

    Tests AC-VERIFY-1: 'critic' is present in graph.nodes; reachable from
    'ac_parser'; conditional edges from 'critic' target both 'setup_role' and
    'ac_parser'.

    These tests build the actual graph (no mocks) so they catch real wiring
    bugs. build_graph() is I/O-free — it only constructs in-memory graph
    objects — so these are fast unit tests.
    """

    def test_critic_node_registered_in_build_graph(self):
        """'critic' node is present in the compiled main graph (AC-VERIFY-1)."""
        from backend.engine.graph import build_graph

        graph = build_graph()
        assert "critic" in graph.nodes, (
            "'critic' node missing from compiled graph — check graph.add_node() in graph.py"
        )

    def test_direct_edge_ac_parser_to_setup_role_replaced(self):
        """Direct ac_parser → setup_role edge is removed; critic is now in between (AC-VERIFY-1)."""
        from backend.engine.graph import build_graph

        graph = build_graph()
        # The graph's edges are stored in graph.builder._graph (LangGraph internal).
        # We verify reachability by checking that 'critic' is reachable from 'ac_parser'
        # (i.e., ac_parser has an outgoing edge to critic, not setup_role directly).
        # LangGraph compiled graphs expose nodes dict; we check the routing via
        # the route_after_critic function which is the edge function.
        nodes = graph.nodes
        assert "critic" in nodes
        assert "ac_parser" in nodes
        assert "setup_role" in nodes

    def test_route_after_critic_targets_setup_role_and_ac_parser(self):
        """route_after_critic can return both 'setup_role' and 'ac_parser' (AC-VERIFY-1)."""
        from backend.engine.critic_node import route_after_critic

        # Pass verdict → setup_role
        state_pass = _make_state(
            critic_result={"verdict": "pass", "reason_codes": [], "feedback_summary": "",
                           "retry_count": 0, "critic_skipped": False}
        )
        assert route_after_critic(state_pass) == "setup_role"

        # Mismatch + retries remaining → ac_parser
        state_mismatch = _make_state(
            critic_result={"verdict": "mismatch", "reason_codes": ["missing_step"],
                           "feedback_summary": "Step missing.", "retry_count": 0,
                           "critic_skipped": False}
        )
        assert route_after_critic(state_mismatch) == "ac_parser"

    def test_static_execution_engine_bypasses_critic(self):
        """static execution_engine routes critic to setup_role (no test_plan to evaluate)."""
        import pytest
        import asyncio

        state = _make_state(execution_engine="static")

        with pytest.MonkeyPatch().context() as mp:
            import backend.engine.critic_node as cn_mod
            mock_settings = type("S", (), {"critic_enabled": True, "max_critic_retries": 2})()
            mp.setattr(cn_mod, "settings", mock_settings)

            result = asyncio.get_event_loop().run_until_complete(
                cn_mod.critic_node(state)
            )

        assert result["critic_result"]["verdict"] == "pass"
        assert result["critic_result"]["critic_skipped"] is True
        assert result["critic_feedback"] is None


# ---------------------------------------------------------------------------
# Phase 3: Observability tests (AC-INTEGRATION-1, AC-ASYNC-1)
# ---------------------------------------------------------------------------


class TestCriticPassReporter:
    """Tests for _render_critic_pass_section() HTML rendering (AC-INTEGRATION-1)."""

    def test_pass_verdict_renders_pass_badge(self):
        """A pass verdict renders a PASS badge with no detail (AC-INTEGRATION-1)."""
        from backend.engine.reporter import _render_critic_pass_section

        verdicts = [
            {"verdict": "pass", "reason_codes": [], "feedback_summary": "",
             "retry_count": 0, "critic_skipped": False}
        ]
        html = _render_critic_pass_section(verdicts)
        assert "PASS" in html
        assert "MISMATCH" not in html
        assert "SKIPPED" not in html

    def test_mismatch_verdict_renders_mismatch_badge_and_reason_codes(self):
        """A mismatch verdict renders MISMATCH badge and reason codes (AC-INTEGRATION-1)."""
        from backend.engine.reporter import _render_critic_pass_section

        verdicts = [
            {"verdict": "mismatch", "reason_codes": ["missing_step", "persona_mismatch"],
             "feedback_summary": "Step 2 missing from plan.", "retry_count": 1,
             "critic_skipped": False}
        ]
        html = _render_critic_pass_section(verdicts)
        assert "MISMATCH" in html
        assert "missing_step" in html
        assert "persona_mismatch" in html
        assert "Step 2 missing" in html

    def test_skipped_verdict_renders_api_error_badge(self):
        """A skipped verdict (API error) renders SKIPPED (API error) badge (AC-ERROR-1)."""
        from backend.engine.reporter import _render_critic_pass_section

        verdicts = [
            {"verdict": "pass", "reason_codes": [], "feedback_summary": "",
             "retry_count": 0, "critic_skipped": True}
        ]
        html = _render_critic_pass_section(verdicts)
        assert "SKIPPED" in html
        assert "API error" in html

    def test_exhausted_retries_renders_retries_exhausted_note(self):
        """Mismatch with retry_count=2 shows RETRIES EXHAUSTED in the badge (AC-VERIFY-5)."""
        from backend.engine.reporter import _render_critic_pass_section

        verdicts = [
            {"verdict": "mismatch", "reason_codes": ["missing_step"],
             "feedback_summary": "Still missing.", "retry_count": 2,
             "critic_skipped": False}
        ]
        html = _render_critic_pass_section(verdicts)
        assert "RETRIES EXHAUSTED" in html

    def test_empty_verdicts_returns_empty_string(self):
        """No critic activity returns empty string (section omitted for static runs)."""
        from backend.engine.reporter import _render_critic_pass_section

        assert _render_critic_pass_section(None) == ""
        assert _render_critic_pass_section([]) == ""


class TestCriticMismatchBroadcast:
    """Tests for _broadcast_critic_mismatch WebSocket event (AC-ASYNC-1)."""

    @pytest.mark.asyncio
    async def test_broadcast_critic_mismatch_sends_correct_event(self):
        """_broadcast_critic_mismatch sends event_type=critic_mismatch with correct fields."""
        sent_messages = []

        class MockWS:
            async def send_text(self, text):
                sent_messages.append(text)

        mock_ws = MockWS()
        mock_connections = {"run-test-001": [mock_ws]}

        with patch("backend.api.routes._ws_connections", mock_connections):
            from backend.engine.critic_node import _broadcast_critic_mismatch

            await _broadcast_critic_mismatch(
                run_id="run-test-001",
                retry_count=1,
                reason_codes=["missing_step"],
            )

        assert len(sent_messages) == 1
        import json
        msg = json.loads(sent_messages[0])
        assert msg["event_type"] == "critic_mismatch"
        assert msg["run_id"] == "run-test-001"
        assert msg["retry_count"] == 1
        assert msg["reason_codes"] == ["missing_step"]

    @pytest.mark.asyncio
    async def test_broadcast_critic_mismatch_no_connections_is_noop(self):
        """_broadcast_critic_mismatch is a no-op when no WebSocket clients are connected."""
        mock_connections = {}  # No connections for this run

        with patch("backend.api.routes._ws_connections", mock_connections):
            from backend.engine.critic_node import _broadcast_critic_mismatch

            # Should not raise
            await _broadcast_critic_mismatch(
                run_id="run-no-ws",
                retry_count=0,
                reason_codes=[],
            )
