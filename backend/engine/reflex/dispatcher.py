"""
T3-c Reflex Layer Dispatcher — FEAT-118-vqa-tier3-architectural-hardening
=========================================================================

Hard-coded failure-signature → deterministic-recovery dispatcher.
Runs BEFORE recovery_router.attempt_recovery() and BEFORE any Bedrock call
in the evaluator retry path (CQ-C2: reflex first, recovery_router second).

Architecture decision (CQ-C1): YAML catalog for signatures + Python dispatch
table for handler functions. No state machine required.

Entry point: attempt_short_circuit(state, error_msg, planned_action) -> ReflexResult | None
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Catalog loading (singleton, lazy)
# ---------------------------------------------------------------------------

_CATALOG: list[dict] | None = None
_CATALOG_PATH = Path(__file__).parent / "catalog.yaml"


def _load_catalog() -> list[dict]:
    """Load and cache the reflex catalog from catalog.yaml."""
    global _CATALOG
    if _CATALOG is None:
        try:
            with _CATALOG_PATH.open() as f:
                data = yaml.safe_load(f)
            _CATALOG = data.get("signatures", [])
            logger.debug("Reflex catalog loaded: %d signatures", len(_CATALOG))
        except Exception as exc:
            logger.warning("Failed to load reflex catalog: %s — reflex disabled", exc)
            _CATALOG = []
    return _CATALOG


def _reset_catalog() -> None:
    """Reset catalog cache (for testing)."""
    global _CATALOG
    _CATALOG = None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReflexResult:
    """Contract between the Reflex Layer and the evaluator."""

    signature: str
    recovery_action: dict[str, Any]
    critique: str
    escalate_to_hitl: bool = False
    recovery_log: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def _match_error_patterns(sig: dict, error_msg: str) -> bool:
    """Return True if any error_pattern in the signature matches error_msg."""
    patterns = sig.get("error_patterns", [])
    if not patterns:
        return False
    for pattern in patterns:
        try:
            if re.search(pattern, error_msg, re.IGNORECASE):
                return True
        except re.error:
            # Fall back to substring match if regex is invalid
            if pattern.lower() in error_msg.lower():
                return True
    return False


def _match_snapshot_patterns(sig: dict, snapshot: str) -> bool:
    """Return True if any snapshot_contains pattern is found in the snapshot."""
    state_patterns = sig.get("state_patterns", {})
    snapshot_patterns = state_patterns.get("snapshot_contains", [])
    if not snapshot_patterns:
        return False
    for pattern in snapshot_patterns:
        try:
            if re.search(pattern, snapshot, re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in snapshot.lower():
                return True
    return False


def _match_state_check(sig: dict, state: dict[str, Any]) -> bool:
    """Evaluate structured state checks (e.g., action_repeat_threshold)."""
    check = sig.get("state_check")
    if not check:
        return False
    check_type = check.get("type")
    if check_type == "action_repeat_threshold":
        threshold = check.get("threshold", 3)
        repeat_counts: dict = state.get("action_repeat_counts") or {}
        if isinstance(repeat_counts, dict):
            return any(count >= threshold for count in repeat_counts.values())
    return False


def _matches(sig: dict, error_msg: str, snapshot: str, state: dict[str, Any]) -> bool:
    """
    Return True if this signature matches the current error + state context.
    A signature matches if ANY of its declared criteria match.
    """
    has_error_patterns = bool(sig.get("error_patterns"))
    has_snapshot_patterns = bool(sig.get("state_patterns", {}).get("snapshot_contains"))
    has_state_check = bool(sig.get("state_check"))

    if has_error_patterns and _match_error_patterns(sig, error_msg):
        return True
    if has_snapshot_patterns and _match_snapshot_patterns(sig, snapshot):
        return True
    if has_state_check and _match_state_check(sig, state):
        return True
    return False


# ---------------------------------------------------------------------------
# Result builders (one per action_type)
# ---------------------------------------------------------------------------


def _build_result(sig: dict, state: dict[str, Any], planned_action: dict[str, Any]) -> ReflexResult:
    """Map a matched signature entry to a ReflexResult."""
    name = sig["name"]
    recovery = sig.get("recovery", {})
    action_type = recovery.get("action_type", "unknown")
    params = recovery.get("params", {})
    critique = params.get("critique", f"REFLEX: {name} — deterministic recovery applied.")

    action_type_map = {
        "check_parents": _action_check_parents,
        "switch_to_select_option": _action_select_option,
        "wait": _action_wait,
        "click_trigger": _action_click_trigger,
        "dismiss_and_retry": _action_dismiss_and_retry,
        "escalate_to_hitl": _action_escalate_hitl,
    }

    builder = action_type_map.get(action_type, _action_unknown)
    return builder(name, critique, params, state, planned_action)


def _action_check_parents(
    name: str,
    critique: str,
    params: dict,
    state: dict,
    planned_action: dict,
) -> ReflexResult:
    return ReflexResult(
        signature=name,
        recovery_action={
            "action": "click",
            "strategy": "css_selector",
            "selector": ".p-panel, form, main",
            "reasoning": critique,
        },
        critique=critique,
        escalate_to_hitl=False,
        recovery_log={"reflex_signature": name, "action_type": "check_parents"},
    )


def _action_select_option(
    name: str,
    critique: str,
    params: dict,
    state: dict,
    planned_action: dict,
) -> ReflexResult:
    # Build a select_option action from the original planned_action context
    original_text = planned_action.get("text") or planned_action.get("value") or ""
    return ReflexResult(
        signature=name,
        recovery_action={
            "action": "select_option",
            "strategy": "css_selector",
            "selector": "select",
            "value": original_text,
            "reasoning": critique,
        },
        critique=critique,
        escalate_to_hitl=False,
        recovery_log={"reflex_signature": name, "action_type": "switch_to_select_option"},
    )


def _action_wait(
    name: str,
    critique: str,
    params: dict,
    state: dict,
    planned_action: dict,
) -> ReflexResult:
    wait_ms = params.get("value", 500)
    return ReflexResult(
        signature=name,
        recovery_action={
            "action": "wait",
            "value": wait_ms,
            "reasoning": critique,
        },
        critique=critique,
        escalate_to_hitl=False,
        recovery_log={"reflex_signature": name, "action_type": "wait", "wait_ms": wait_ms},
    )


def _action_click_trigger(
    name: str,
    critique: str,
    params: dict,
    state: dict,
    planned_action: dict,
) -> ReflexResult:
    # Click the trigger element that has aria-expanded=false
    return ReflexResult(
        signature=name,
        recovery_action={
            "action": "click",
            "strategy": "css_selector",
            "selector": '[aria-expanded="false"]',
            "reasoning": critique,
        },
        critique=critique,
        escalate_to_hitl=False,
        recovery_log={"reflex_signature": name, "action_type": "click_trigger"},
    )


def _action_dismiss_and_retry(
    name: str,
    critique: str,
    params: dict,
    state: dict,
    planned_action: dict,
) -> ReflexResult:
    return ReflexResult(
        signature=name,
        recovery_action={
            "action": "press_key",
            "value": "Escape",
            "reasoning": critique,
        },
        critique=critique,
        escalate_to_hitl=False,
        recovery_log={"reflex_signature": name, "action_type": "dismiss_and_retry"},
    )


def _action_escalate_hitl(
    name: str,
    critique: str,
    params: dict,
    state: dict,
    planned_action: dict,
) -> ReflexResult:
    return ReflexResult(
        signature=name,
        recovery_action={},
        critique=critique,
        escalate_to_hitl=True,
        recovery_log={"reflex_signature": name, "action_type": "escalate_to_hitl"},
    )


def _action_unknown(
    name: str,
    critique: str,
    params: dict,
    state: dict,
    planned_action: dict,
) -> ReflexResult:
    logger.warning("Unknown reflex action_type for signature %s — treating as miss", name)
    return ReflexResult(
        signature=name,
        recovery_action=planned_action,
        critique=critique,
        escalate_to_hitl=False,
        recovery_log={"reflex_signature": name, "action_type": "unknown"},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def attempt_short_circuit(
    state: dict[str, Any],
    error_msg: str,
    planned_action: dict[str, Any],
) -> "ReflexResult | None":
    """
    T3-c entry point — called by evaluator BEFORE recovery_router.attempt_recovery().

    Returns ReflexResult on a catalog hit (evaluator skips Bedrock retry for this iteration).
    Returns None on a miss (fall through to recovery_router and normal retry path).

    Feature-flagged via REFLEX_LAYER_ENABLED env var (default: true).
    Wrapped in broad try/except in evaluator so a reflex bug never crashes the eval loop.
    """
    enabled = os.getenv("REFLEX_LAYER_ENABLED", "true").strip().lower()
    if enabled not in ("true", "1", "yes"):
        return None

    catalog = _load_catalog()
    if not catalog:
        return None

    snapshot: str = state.get("page_state_snapshot") or ""
    error_str: str = error_msg or ""

    for sig in catalog:
        if _matches(sig, error_str, snapshot, state):
            result = _build_result(sig, state, planned_action)
            logger.info(
                "Reflex hit: signature=%s action_type=%s escalate=%s",
                result.signature,
                sig.get("recovery", {}).get("action_type"),
                result.escalate_to_hitl,
            )
            return result

    return None
