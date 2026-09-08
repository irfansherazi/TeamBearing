"""
tests/test_model_router.py
===========================
Unit tests for backend/engine/model_router.py (TASK-080-P1A).

Tests cover:
- Tier 1 (Haiku): deterministic actions — click, fill, navigate, scroll, wait
- Tier 2 (Sonnet): planning with partial context / recipe disambiguation
- Tier 3 (Sonnet Vision full): HITL escalation / CV fallback
- Auto-escalation boundary: retry_count >= threshold → Tier 2 minimum
- Feature flag: MODEL_ROUTER_ENABLED=false → always returns bedrock_model_id
- Unknown action_type → Tier 1 (conservative default)
"""

import pytest

from backend.engine.model_router import ModelRouter, RoutingTier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def router():
    """Return a fresh ModelRouter with feature flag ON."""
    return ModelRouter(enabled=True)


@pytest.fixture()
def disabled_router():
    """Return a ModelRouter with feature flag OFF (disabled)."""
    return ModelRouter(enabled=False)


# ---------------------------------------------------------------------------
# Tier Classification Tests
# ---------------------------------------------------------------------------


class TestTier1Routing:
    """Deterministic actions should route to Tier 1 (Haiku)."""

    @pytest.mark.parametrize(
        "action_type",
        [
            "click",
            "fill",
            "navigate",
            "scroll",
            "wait",
            "press_key",
            "check",
            "uncheck",
            "set_input_files",
        ],
    )
    def test_deterministic_actions_route_to_tier1(self, router, action_type):
        tier = router.get_tier(action_type=action_type, confidence_score=1.0, retry_count=0)
        assert tier == RoutingTier.TIER_1

    def test_tier1_returns_haiku_model_id(self, router):
        model_id = router.get_model_id(action_type="click", confidence_score=1.0, retry_count=0)
        assert "haiku" in model_id.lower()

    def test_unknown_action_type_defaults_to_tier1(self, router):
        """Unknown action types are conservatively routed to Tier 1."""
        tier = router.get_tier(action_type="xyzzy_unknown", confidence_score=1.0, retry_count=0)
        assert tier == RoutingTier.TIER_1


class TestTier2Routing:
    """Planning with partial context / multi-match should route to Tier 2."""

    @pytest.mark.parametrize(
        "action_type",
        [
            "primeng_dropdown",
            "select_option",
            "verify",
            "fill_and_submit",
            "click_and_wait",
            "select_and_verify",
        ],
    )
    def test_complex_actions_route_to_tier2(self, router, action_type):
        tier = router.get_tier(action_type=action_type, confidence_score=1.0, retry_count=0)
        assert tier == RoutingTier.TIER_2

    def test_tier2_returns_sonnet_model_id(self, router):
        model_id = router.get_model_id(action_type="verify", confidence_score=1.0, retry_count=0)
        assert "sonnet" in model_id.lower()

    def test_low_confidence_escalates_to_tier2(self, router):
        """confidence_score below threshold escalates click to Tier 2."""
        # Below the ambiguity threshold
        tier = router.get_tier(action_type="click", confidence_score=0.3, retry_count=0)
        assert tier >= RoutingTier.TIER_2


class TestTier3Routing:
    """HITL escalation / coordinate actions should route to Tier 3."""

    @pytest.mark.parametrize(
        "action_type",
        [
            "coordinate_action",
            "recipe",
        ],
    )
    def test_vision_actions_route_to_tier3(self, router, action_type):
        tier = router.get_tier(action_type=action_type, confidence_score=1.0, retry_count=0)
        assert tier == RoutingTier.TIER_3

    def test_tier3_returns_sonnet_model_id(self, router):
        """Tier 3 still uses Sonnet (heavy model) for vision full."""
        model_id = router.get_model_id(action_type="coordinate_action", confidence_score=1.0, retry_count=0)
        assert "sonnet" in model_id.lower()


# ---------------------------------------------------------------------------
# Auto-Escalation Boundary Tests
# ---------------------------------------------------------------------------


class TestAutoEscalation:
    """retry_count >= threshold forces minimum Tier 2 routing."""

    def test_retry_count_at_threshold_escalates_tier1_to_tier2(self, router):
        """A Tier 1 action at retry_count==threshold should get Tier 2."""
        # Default threshold is 3 (from settings)
        tier = router.get_tier(action_type="click", confidence_score=1.0, retry_count=3)
        assert tier >= RoutingTier.TIER_2

    def test_retry_count_below_threshold_stays_tier1(self, router):
        """Below threshold, no escalation."""
        tier = router.get_tier(action_type="click", confidence_score=1.0, retry_count=2)
        assert tier == RoutingTier.TIER_1

    def test_retry_count_above_threshold_escalates(self, router):
        """High retry count also escalates."""
        tier = router.get_tier(action_type="fill", confidence_score=1.0, retry_count=10)
        assert tier >= RoutingTier.TIER_2

    def test_threshold_zero_always_uses_heavy(self, router):
        """threshold=0 means always heavy (Tier 2+ minimum)."""
        r = ModelRouter(enabled=True, escalation_threshold=0)
        tier = r.get_tier(action_type="click", confidence_score=1.0, retry_count=0)
        assert tier >= RoutingTier.TIER_2


# ---------------------------------------------------------------------------
# FEAT-066 Verifier Rejection Escalation Tests
# ---------------------------------------------------------------------------


class TestVerifierRejectionEscalation:
    """Immediate escalation to Tier 2 (Sonnet) starting from the first retry on verifier rejection."""

    def test_rejection_escalates_at_retry_1(self, router):
        """
        Baseline: retry_count=1 without rejection is Tier 1 (threshold is 3).
        FEAT-066: retry_count=1 WITH rejection is Tier 2.
        """
        # Normal path (no rejection)
        tier_normal = router.get_tier(action_type="click", retry_count=1, is_verifier_rejected=False)
        assert tier_normal == RoutingTier.TIER_1

        # Rejection path
        tier_rejected = router.get_tier(action_type="click", retry_count=1, is_verifier_rejected=True)
        assert tier_rejected == RoutingTier.TIER_2

    def test_get_model_id_respects_rejection_flag(self, router):
        """get_model_id should return Sonnet when is_verifier_rejected=True and retry_count >= 1."""
        model_rejected = router.get_model_id(action_type="click", retry_count=1, is_verifier_rejected=True)
        assert "sonnet" in model_rejected.lower()


# ---------------------------------------------------------------------------
# Feature Flag Tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    """When MODEL_ROUTER_ENABLED=false, always return the default model ID."""

    def test_disabled_router_returns_default_model_for_tier1_action(self, disabled_router):
        """Disabled router ignores tier — always Tier 1 model."""
        model_id = disabled_router.get_model_id(action_type="click", confidence_score=1.0, retry_count=0)
        assert "haiku" in model_id.lower()

    def test_disabled_router_returns_default_model_for_tier3_action(self, disabled_router):
        """Even coordinate_action returns default model when disabled."""
        model_id = disabled_router.get_model_id(action_type="coordinate_action", confidence_score=1.0, retry_count=0)
        # When disabled, always returns settings.bedrock_model_id (Haiku)
        assert "haiku" in model_id.lower()

    def test_disabled_router_get_tier_returns_tier1(self, disabled_router):
        """Disabled router reports Tier 1 for everything."""
        tier = disabled_router.get_tier(action_type="coordinate_action", confidence_score=1.0, retry_count=0)
        assert tier == RoutingTier.TIER_1

    def test_disabled_router_ignores_low_confidence(self, disabled_router):
        """Feature flag off — confidence_score has no effect."""
        tier = disabled_router.get_tier(action_type="click", confidence_score=0.0, retry_count=0)
        assert tier == RoutingTier.TIER_1

    def test_disabled_router_ignores_retry_count(self, disabled_router):
        """Feature flag off — retry_count has no effect."""
        tier = disabled_router.get_tier(action_type="fill", confidence_score=1.0, retry_count=100)
        assert tier == RoutingTier.TIER_1


# ---------------------------------------------------------------------------
# Model ID Selection Tests
# ---------------------------------------------------------------------------


class TestModelIdSelection:
    """Verify correct model IDs are returned for each tier."""

    def test_get_model_id_tier1(self, router):
        model_id = router.get_model_id(action_type="click", confidence_score=1.0, retry_count=0)
        assert model_id  # non-empty
        assert "haiku" in model_id.lower()

    def test_get_model_id_tier2(self, router):
        model_id = router.get_model_id(action_type="verify", confidence_score=1.0, retry_count=0)
        assert model_id
        assert "sonnet" in model_id.lower()

    def test_routing_log_info(self, router, caplog):
        """ModelRouter logs the routing decision at DEBUG level."""
        import logging

        with caplog.at_level(logging.DEBUG, logger="backend.engine.model_router"):
            router.get_model_id(action_type="click", confidence_score=1.0, retry_count=0)
        # Should have logged something
        assert any("model_router" in r.name or "tier" in r.message.lower() for r in caplog.records)
