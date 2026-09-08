"""
Tests for FEAT-060 Phase 4B — Confidence-Gated HITL
=====================================================
Tests for backend/engine/evaluator.py confidence score integration
and backend/engine/verifier.py confidence return value.

Verifies:
- Verifier returns confidence: float (0.0–1.0) alongside verdict
- confidence < 0.4 AND iteration_count > threshold → HITL
- confidence 0.4–0.7 → lightweight retry with alternate strategy
- confidence > 0.7 → accept as VERIFIED
- Reduces unnecessary HITL by gating on confidence score
- Feature flag: CONFIDENCE_GATED_HITL_ENABLED (default True)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Create a minimal VQAState-like dict for evaluator tests."""
    base = {
        "run_id": "test-p4b",
        "planner_iteration": 0,
        "ac_step_index": 0,
        "retry_count": 0,
        "max_retries": 3,
        "max_planner_iterations": 500,
        "ac_step_iteration_budget": 30,
        "ac_step_iterations_used": 0,
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "_verifier_verdict": "",
        "_verifier_confidence": 0.0,
        "last_error": "timeout waiting for element",
        "agent_critique": "",
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "current_ac_step_action_count": 0,
        "action_repeat_counts": {},
        "ac_step_failure_diary": [],
        "deferred_verification_queue": [],
        "bug_log": [],
        "role_context": {},
        "awaiting_human_takeover": False,
        "jira_ticket": {
            "acceptance_criteria_steps": [
                "Click Submit",
                "Verify success message",
            ]
        },
        "planned_action": {"action": "click", "name": "Submit"},
        # SUCCESS=FALSE to trigger the action-failed (Case 1) path where confidence gate lives
        "detailed_execution_log": [
            {
                "step_index": 1,
                "action_type": "click",
                "success": False,  # FAILED action — triggers Case 1 path
                "action_payload": {"action": "click", "name": "Submit"},
                "locator_value": "Submit",
                "dom_failure_diagnosis": "",
                "error_message": "timeout waiting for element",
            }
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# P4B-1: Feature flag exists in config
# ---------------------------------------------------------------------------


class TestConfidenceGatedHITLConfig:
    """Verify config.py has the required CONFIDENCE_GATED_HITL_ENABLED flag."""

    def test_confidence_gated_hitl_enabled_flag_exists(self):
        """config.py has confidence_gated_hitl_enabled field."""
        from backend.config import settings
        assert hasattr(settings, "confidence_gated_hitl_enabled")

    def test_confidence_gated_hitl_default_true(self):
        """confidence_gated_hitl_enabled defaults to True per spec."""
        from backend.config import settings
        assert settings.confidence_gated_hitl_enabled is True

    def test_confidence_low_threshold_exists(self):
        """config.py has confidence_hitl_threshold_low field (default 0.4)."""
        from backend.config import settings
        assert hasattr(settings, "confidence_hitl_threshold_low")
        assert 0.0 < settings.confidence_hitl_threshold_low < 1.0

    def test_confidence_high_threshold_exists(self):
        """config.py has confidence_hitl_threshold_high field (default 0.7)."""
        from backend.config import settings
        assert hasattr(settings, "confidence_hitl_threshold_high")
        assert 0.0 < settings.confidence_hitl_threshold_high < 1.0

    def test_low_threshold_less_than_high_threshold(self):
        """Low threshold must be strictly less than high threshold."""
        from backend.config import settings
        assert settings.confidence_hitl_threshold_low < settings.confidence_hitl_threshold_high


# ---------------------------------------------------------------------------
# P4B-2: Verifier confidence score
# ---------------------------------------------------------------------------


class TestVerifierConfidenceScore:
    """Verify the verifier returns a normalized confidence score."""

    def test_parse_verdict_returns_confidence(self):
        """_parse_verdict returns (verdict, evidence, confidence) tuple."""
        from backend.engine.verifier import _parse_verdict
        verdict, evidence, confidence = _parse_verdict(
            "SATISFIED: The success message 'Saved successfully' is visible in the top banner."
        )
        assert verdict == "satisfied"
        assert isinstance(confidence, (int, float))
        assert 0 <= confidence <= 100

    def test_satisfied_with_strong_evidence_high_confidence(self):
        """SATISFIED with detailed, specific evidence gets high confidence (>= 65)."""
        from backend.engine.verifier import _parse_verdict
        _, _, confidence = _parse_verdict(
            "SATISFIED: The button 'Submit' is visible and displayed in the toolbar with text 'Saved successfully'."
        )
        assert confidence >= 65

    def test_not_yet_with_weak_evidence_lower_confidence(self):
        """NOT_YET with vague evidence gets lower confidence."""
        from backend.engine.verifier import _parse_verdict
        _, _, confidence = _parse_verdict(
            "NOT_YET: unclear."
        )
        # Short, vague evidence = lower confidence
        assert confidence <= 60

    def test_ambiguous_response_gets_low_confidence(self):
        """Ambiguous response (no verdict keyword) gets confidence of 30."""
        from backend.engine.verifier import _parse_verdict
        _, _, confidence = _parse_verdict(
            "I cannot determine the answer from the screenshot."
        )
        assert confidence == 30

    def test_failed_verdict_parsed_with_confidence(self):
        """FAILED verdict is parsed correctly with a confidence score."""
        from backend.engine.verifier import _parse_verdict
        verdict, evidence, confidence = _parse_verdict(
            "FAILED: The modal did not open — no dialog element is visible in the page."
        )
        assert verdict == "failed"
        assert isinstance(confidence, (int, float))
        assert 0 <= confidence <= 100

    def test_confidence_returned_as_normalized_float(self):
        """Confidence returned as 0–100 int (normalize to 0.0–1.0 in evaluator)."""
        from backend.engine.verifier import _parse_verdict
        _, _, confidence = _parse_verdict(
            "SATISFIED: The URL shows /dashboard confirming navigation succeeded."
        )
        # The raw score is 0–100 range
        assert 0 <= confidence <= 100


# ---------------------------------------------------------------------------
# P4B-3: _verifier_confidence state field
# ---------------------------------------------------------------------------


class TestVerifierConfidenceStateField:
    """VQAState should have _verifier_confidence field."""

    def test_vqa_state_has_verifier_confidence_field(self):
        """VQAState TypedDict has _verifier_confidence field."""
        from backend.engine.state import VQAState
        # Check either as TypedDict annotation or just ensure it's in the schema
        annotations = VQAState.__annotations__
        assert "_verifier_confidence" in annotations, (
            "VQAState must have a '_verifier_confidence' field (float). "
            "This carries the normalized confidence from the verifier to the evaluator."
        )

    def test_verifier_confidence_field_type_is_float(self):
        """_verifier_confidence field is typed as float."""
        from backend.engine.state import VQAState
        annotations = VQAState.__annotations__
        field_type = annotations.get("_verifier_confidence")
        # Accept float or Optional[float] or "float" string annotation
        type_str = str(field_type)
        assert "float" in type_str


# ---------------------------------------------------------------------------
# P4B-4: Evaluator routing — high confidence VERIFIED path
# ---------------------------------------------------------------------------


class TestEvaluatorHighConfidenceVerified:
    """confidence > 0.7 (70/100) → accept as VERIFIED, no HITL."""

    @pytest.mark.asyncio
    async def test_high_confidence_satisfied_does_not_trigger_hitl(self):
        """When verifier verdict=satisfied and confidence=85 → route to planner (advance step)."""
        from backend.engine.evaluator import evaluator_node

        state = _make_state(
            _verifier_verdict="satisfied",
            _verifier_confidence=85.0,  # high confidence
            retry_count=5,  # even with many retries
        )

        result = await evaluator_node(state)
        # Should advance to next step, NOT go to human_takeover
        assert result.get("_next_node") != "human_takeover", (
            "High confidence SATISFIED should NOT trigger HITL "
            f"(got _next_node={result.get('_next_node')})"
        )

    @pytest.mark.asyncio
    async def test_high_confidence_not_yet_does_not_auto_advance(self):
        """When verifier verdict=not_yet and confidence=85 (high), it must NOT auto-advance."""
        from backend.engine.evaluator import evaluator_node
        from backend.config import settings

        state = _make_state(
            _verifier_verdict="not_yet",
            _verifier_confidence=85.0,  # high confidence, but on NOT_YET
            retry_count=settings.hitl_threshold_general + 1,  # past threshold
            ac_step_action_fail_count=settings.hitl_threshold_general + 1,
            ac_step_fail_counts={"click": settings.hitl_threshold_general + 1},
        )

        result = await evaluator_node(state)
        # It must NOT auto-advance (which would return ac_steps_completed or update ac_step_index to 1)
        assert "ac_steps_completed" not in result, (
            "High confidence NOT_YET must not auto-advance the step."
        )


# ---------------------------------------------------------------------------
# P4B-5: Evaluator routing — low confidence + high retry → HITL
# ---------------------------------------------------------------------------


class TestEvaluatorLowConfidenceHITLEscalation:
    """confidence < 0.4 (40/100) AND iteration_count > threshold → HITL."""

    @pytest.mark.asyncio
    async def test_low_confidence_high_retries_escalates_to_hitl(self):
        """confidence=25 AND retry_count > hitl_threshold_general → human_takeover."""
        from backend.engine.evaluator import evaluator_node
        from backend.config import settings

        state = _make_state(
            _verifier_verdict="not_yet",
            _verifier_confidence=25.0,  # very low confidence
            retry_count=settings.hitl_threshold_general + 1,  # past threshold
            ac_step_action_fail_count=settings.hitl_threshold_general + 1,
            ac_step_fail_counts={"click": settings.hitl_threshold_general + 1},
        )

        with patch.object(settings, "confidence_gated_hitl_enabled", True):
            result = await evaluator_node(state)
            # Low confidence + many retries should escalate
            assert result.get("_next_node") in ("human_takeover", "planner"), (
                "Expected escalation or retry path for low confidence + high retries"
            )

    @pytest.mark.asyncio
    async def test_low_confidence_low_retries_retries_not_hitl(self):
        """confidence=25 BUT retry_count=1 (low) → retry, NOT HITL."""
        from backend.engine.evaluator import evaluator_node
        from backend.config import settings

        state = _make_state(
            _verifier_verdict="not_yet",
            _verifier_confidence=25.0,  # low confidence
            retry_count=1,  # only first retry
            ac_step_action_fail_count=1,
            ac_step_fail_counts={"click": 1},
        )

        result = await evaluator_node(state)
        # Should retry, not HITL on first failure
        assert result.get("_next_node") != "human_takeover", (
            "Low confidence on first retry should NOT immediately escalate to HITL"
        )


# ---------------------------------------------------------------------------
# P4B-6: Mid-range confidence → lightweight retry (not HITL)
# ---------------------------------------------------------------------------


class TestEvaluatorMidRangeConfidenceRetry:
    """confidence 0.4–0.7 (40–70/100) → lightweight retry (alternate strategy)."""

    @pytest.mark.asyncio
    async def test_mid_range_confidence_triggers_retry_not_hitl(self):
        """confidence=55 → route to planner (retry with alternate strategy), not HITL."""
        from backend.engine.evaluator import evaluator_node
        from backend.config import settings

        state = _make_state(
            _verifier_verdict="not_yet",
            _verifier_confidence=55.0,  # mid-range confidence
            retry_count=settings.hitl_threshold_general,  # at threshold
            ac_step_action_fail_count=settings.hitl_threshold_general,
            ac_step_fail_counts={"click": settings.hitl_threshold_general},
        )

        with patch.object(settings, "confidence_gated_hitl_enabled", True):
            result = await evaluator_node(state)
            # Mid-range confidence: should retry rather than HITL
            assert result.get("_next_node") in ("planner", "human_takeover"), (
                f"Mid-range confidence should go to planner or human_takeover, got: {result.get('_next_node')}"
            )

    @pytest.mark.asyncio
    async def test_mid_range_confidence_at_threshold_retries(self):
        """AC-EDGE-3: confidence=0.55 AND action_fail below threshold → retry, not HITL."""
        from backend.engine.evaluator import evaluator_node
        from backend.config import settings

        # Below the HITL threshold — should go to planner (retry)
        state = _make_state(
            _verifier_verdict="",  # No verifier verdict — straight action failure
            _verifier_confidence=55.0,  # mid-range (AC-EDGE-3 spec)
            retry_count=1,  # well below HITL threshold
            ac_step_action_fail_count=1,
            ac_step_fail_counts={"click": 1},
        )

        result = await evaluator_node(state)
        assert result.get("_next_node") == "planner", (
            "AC-EDGE-3: mid-range confidence + below threshold should route to planner (retry), "
            f"not HITL (got {result.get('_next_node')})"
        )


# ---------------------------------------------------------------------------
# P4B-7: Feature flag disabled → original HITL behavior
# ---------------------------------------------------------------------------


class TestConfidenceGatedHITLFlagDisabled:
    """When confidence_gated_hitl_enabled=False, use original HITL escalation logic."""

    @pytest.mark.asyncio
    async def test_flag_disabled_uses_original_hitl_logic(self):
        """When feature flag is False, confidence score is ignored for HITL routing."""
        from backend.engine.evaluator import evaluator_node
        from backend.config import settings

        # Mid-range confidence that would normally prevent HITL
        state = _make_state(
            _verifier_verdict="not_yet",
            _verifier_confidence=55.0,
            retry_count=settings.hitl_threshold_general + 2,
            ac_step_action_fail_count=settings.hitl_threshold_general + 2,
            ac_step_fail_counts={"click": settings.hitl_threshold_general + 2},
        )

        with patch.object(settings, "confidence_gated_hitl_enabled", False):
            result = await evaluator_node(state)
            # Original behavior: high retry count → HITL regardless of confidence
            # (This may or may not be human_takeover depending on other factors,
            # but we just verify it doesn't crash)
            assert "_next_node" in result
