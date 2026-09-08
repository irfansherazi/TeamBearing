"""
backend/engine/model_router.py
================================
TASK-080-P1A: Full Three-Tier Model Router for FEAT-060.

Extracts routing logic from _invoke_planner_with_tools() into a
clean ModelRouter class. Routes LLM invocations to the appropriate
model tier based on action_type, confidence_score, and retry_count.

Tiers:
  Tier 1 (Haiku)  — deterministic actions: click, fill, navigate, scroll, wait
  Tier 2 (Sonnet) — planning with context: verify, dropdown, composite actions
  Tier 3 (Sonnet) — HITL/vision: coordinate_action, recipe (needs full context)

Feature flag: MODEL_ROUTER_ENABLED (default true)
  When false: always returns settings.bedrock_model_id (Haiku).

Design: See TASK-080 Specification Item 1.
"""

import logging
from enum import IntEnum

from backend.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing Tier Enum
# ---------------------------------------------------------------------------


class RoutingTier(IntEnum):
    """
    Execution tier for LLM invocations.

    Higher tier = more capable / more expensive model.
    IntEnum allows comparison: tier >= RoutingTier.TIER_2.
    """

    TIER_1 = 1  # Haiku — fast, cheap, deterministic actions
    TIER_2 = 2  # Sonnet — planning, disambiguation, complex actions
    TIER_3 = 3  # Sonnet Vision full — HITL escalation, CV fallback


# ---------------------------------------------------------------------------
# Action classification sets
# ---------------------------------------------------------------------------

# Tier 1: Deterministic browser interactions — minimal cognitive load
_TIER_1_ACTIONS: frozenset[str] = frozenset(
    {
        "click",
        "fill",
        "navigate",
        "scroll",
        "wait",
        "press_key",
        "check",
        "uncheck",
        "set_input_files",
        "done",
    }
)

# Tier 2: Require planning, disambiguation, or compound logic
_TIER_2_ACTIONS: frozenset[str] = frozenset(
    {
        "verify",
        "select_option",
        "primeng_dropdown",
        "fill_and_submit",
        "click_and_wait",
        "select_and_verify",
        "verify_table_sort",
    }
)

# Tier 3: Vision-mode / full-context / HITL
_TIER_3_ACTIONS: frozenset[str] = frozenset(
    {
        "coordinate_action",
        "recipe",
    }
)

# Confidence threshold below which Tier 1 actions are escalated to Tier 2
_AMBIGUITY_CONFIDENCE_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """
    Route LLM invocations to the appropriate model tier.

    This class is the single source of truth for routing decisions across
    the planner, verifier, and any future LLM call sites in vQA.

    Usage::

        router = ModelRouter(enabled=settings.model_router_enabled)
        model_id = router.get_model_id(
            action_type=action.action,
            confidence_score=action.confidence_score or 1.0,
            retry_count=state.get("retry_count", 0),
        )

    Args:
        enabled: When False, always returns settings.bedrock_model_id regardless
                 of action_type. Equivalent to pre-FEAT-060 behavior.
        escalation_threshold: Number of retries before forcing Tier 2 minimum.
                              Defaults to settings.auto_escalate_threshold.
    """

    def __init__(
        self,
        enabled: bool = True,
        escalation_threshold: int | None = None,
    ) -> None:
        self.enabled = enabled
        self.escalation_threshold = (
            escalation_threshold if escalation_threshold is not None else settings.auto_escalate_threshold
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tier(
        self,
        action_type: str,
        confidence_score: float = 1.0,
        retry_count: int = 0,
        is_verifier_rejected: bool = False,
    ) -> RoutingTier:
        """
        Determine the routing tier for a given action.

        Decision order:
          1. Feature flag off → always Tier 1
          2. retry_count >= escalation_threshold → minimum Tier 2
          3. is_verifier_rejected and retry_count >= 1 → minimum Tier 2 (FEAT-066)
          4. action_type in Tier 3 set → Tier 3
          5. action_type in Tier 2 set → Tier 2
          6. confidence_score < threshold → Tier 2
          7. Default → Tier 1

        Args:
            action_type: The action type from PlannerAction.action.
            confidence_score: Optional confidence [0.0–1.0]. Low confidence
                              triggers escalation from Tier 1 to Tier 2.
            retry_count: Current AC step retry count.
            is_verifier_rejected: True if recovering from a VERIFIER_REJECTED state.

        Returns:
            RoutingTier enum value.
        """
        if not self.enabled:
            return RoutingTier.TIER_1

        action_lower = (action_type or "").lower().strip()

        # Auto-escalation: retry threshold crossed → minimum Tier 2
        threshold = self.escalation_threshold
        if threshold == 0 or (threshold > 0 and retry_count >= threshold):
            min_tier = RoutingTier.TIER_2
        elif is_verifier_rejected and retry_count >= 1:
            # FEAT-066: Immediate escalation to Sonnet when recovering from verifier rejection
            min_tier = RoutingTier.TIER_2
        else:
            min_tier = RoutingTier.TIER_1

        # Classify by action type
        if action_lower in _TIER_3_ACTIONS:
            computed_tier = RoutingTier.TIER_3
        elif action_lower in _TIER_2_ACTIONS:
            computed_tier = RoutingTier.TIER_2
        elif action_lower in _TIER_1_ACTIONS:
            # Confidence check for Tier 1 actions
            if confidence_score < _AMBIGUITY_CONFIDENCE_THRESHOLD:
                computed_tier = RoutingTier.TIER_2
            else:
                computed_tier = RoutingTier.TIER_1
        else:
            # Unknown action type — conservative Tier 1
            logger.debug(
                "model_router: unknown action_type=%r — defaulting to Tier 1",
                action_type,
            )
            computed_tier = RoutingTier.TIER_1

        final_tier = max(computed_tier, min_tier)

        logger.debug(
            "model_router: action=%r confidence=%.2f retry=%d → tier=%d (min_tier=%d)",
            action_type,
            confidence_score,
            retry_count,
            final_tier,
            min_tier,
        )

        return final_tier

    def get_model_id(
        self,
        action_type: str,
        confidence_score: float = 1.0,
        retry_count: int = 0,
        is_verifier_rejected: bool = False,
    ) -> str:
        """
        Return the Bedrock model ID for the given routing inputs.

        When feature flag is disabled, always returns the default model
        (settings.bedrock_model_id — Haiku).

        Tier 1 → settings.bedrock_model_id      (Haiku — fast/cheap)
        Tier 2 → settings.bedrock_model_id_heavy (Sonnet — capable)
        Tier 3 → settings.bedrock_model_id_heavy (Sonnet Vision full)

        Args:
            action_type: The action type from PlannerAction.action.
            confidence_score: Optional confidence [0.0–1.0].
            retry_count: Current AC step retry count.
            is_verifier_rejected: True if recovering from a VERIFIER_REJECTED state.

        Returns:
            Bedrock model identifier string.
        """
        if not self.enabled:
            return settings.bedrock_model_id

        tier = self.get_tier(
            action_type=action_type,
            confidence_score=confidence_score,
            retry_count=retry_count,
            is_verifier_rejected=is_verifier_rejected,
        )

        if tier == RoutingTier.TIER_1:
            model_id = settings.bedrock_model_id
        else:
            # Tier 2 and Tier 3 both use the heavy (Sonnet) model
            model_id = settings.bedrock_model_id_heavy

        logger.debug(
            "model_router: tier=%d → model_id=%s",
            tier,
            model_id,
        )

        return model_id


# ---------------------------------------------------------------------------
# Module-level singleton (lazy — avoids import-time settings access)
# ---------------------------------------------------------------------------


def get_model_router() -> ModelRouter:
    """
    Return the singleton ModelRouter, respecting the feature flag.

    Import pattern::

        from backend.engine.model_router import get_model_router
        router = get_model_router()

    This is intentionally NOT a module-level singleton to keep tests simple
    (tests can construct ModelRouter directly with custom settings).
    """
    return ModelRouter(
        enabled=getattr(settings, "model_router_enabled", True),
        escalation_threshold=settings.auto_escalate_threshold,
    )
