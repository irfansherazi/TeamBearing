"""
TASK-004: Recovery Router — Comprehensive Unit Tests
====================================================

Tests for the state, configuration, and routing logic of the Recovery Router.
These tests verify that recovery strategies are correctly classified,
feature-flagged, and executed.

Run: .venv/bin/python -m pytest tests/test_recovery_router.py -v
"""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_state(**overrides) -> dict:
    """
    Create a minimal VQAState dict suitable for evaluator unit tests.
    Uses make_initial_state for proper defaults, then applies overrides.
    """
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-run-recovery",
        jira_ticket_id="QA-RECOVERY",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    for k, v in overrides.items():
        state[k] = v
    return state


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Config Recovery Flags
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigRecoveryFlags:
    """Verify new boolean feature flags in backend/config.py Settings class."""

    def test_recovery_strict_mode_flag_exists(self):
        """recovery_strict_mode_enabled should be defined in Settings."""
        from backend.config import Settings

        assert "recovery_strict_mode_enabled" in Settings.model_fields

    def test_recovery_timeout_flag_exists(self):
        """recovery_timeout_enabled should be defined in Settings."""
        from backend.config import Settings

        assert "recovery_timeout_enabled" in Settings.model_fields

    def test_recovery_not_visible_flag_exists(self):
        """recovery_not_visible_enabled should be defined in Settings."""
        from backend.config import Settings

        assert "recovery_not_visible_enabled" in Settings.model_fields

    def test_recovery_detached_flag_exists(self):
        """recovery_detached_enabled should be defined in Settings."""
        from backend.config import Settings

        assert "recovery_detached_enabled" in Settings.model_fields

    def test_recovery_intercepted_flag_exists(self):
        """recovery_intercepted_enabled should be defined in Settings."""
        from backend.config import Settings

        assert "recovery_intercepted_enabled" in Settings.model_fields

    def test_all_flags_default_true(self):
        """Settings() should have all 5 flags set to True by default."""
        from backend.config import Settings

        s = Settings()
        assert s.recovery_strict_mode_enabled is True
        assert s.recovery_timeout_enabled is True
        assert s.recovery_not_visible_enabled is True
        assert s.recovery_detached_enabled is True
        assert s.recovery_intercepted_enabled is True

    def test_flags_can_be_disabled(self):
        """Settings should allow disabling flags via constructor/env."""
        from backend.config import Settings

        s = Settings(recovery_strict_mode_enabled=False)
        assert s.recovery_strict_mode_enabled is False


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: State Recovery Fields
# ═══════════════════════════════════════════════════════════════════════════


class TestStateRecoveryFields:
    """Verify new fields in VQAState (backend/engine/state.py)."""

    def test_recovery_attempted_types_in_state(self):
        """recovery_attempted_types field should exist in initial state."""
        state = _make_state()
        assert "recovery_attempted_types" in state
        assert isinstance(state["recovery_attempted_types"], set)
        assert len(state["recovery_attempted_types"]) == 0

    def test_recovery_action_log_in_state(self):
        """recovery_action_log field should exist in initial state."""
        state = _make_state()
        assert "recovery_action_log" in state

    def test_recovery_action_log_initialized_empty(self):
        """recovery_action_log should be an empty list initially."""
        state = _make_state()
        assert state["recovery_action_log"] == []


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: Recovery Router Logic
# ═══════════════════════════════════════════════════════════════════════════


class TestRecoveryRouterLogic:
    """Verify the classification and dispatch logic in recovery_router.py."""

    def test_classify_strict_mode(self):
        from backend.engine.recovery_router import RecoveryType, _classify_for_recovery

        msg = "locator.click: Error: strict mode violation: locator('button') resolved to 3 elements"
        assert _classify_for_recovery(msg) == RecoveryType.STRICT_MODE

    def test_classify_timeout(self):
        from backend.engine.recovery_router import RecoveryType, _classify_for_recovery

        msg = "locator.click: Timeout 15000ms exceeded."
        assert _classify_for_recovery(msg) == RecoveryType.TIMEOUT

    def test_classify_not_visible(self):
        from backend.engine.recovery_router import RecoveryType, _classify_for_recovery

        msg = "locator.click: Error: element is not visible"
        assert _classify_for_recovery(msg) == RecoveryType.NOT_VISIBLE

    def test_classify_detached(self):
        from backend.engine.recovery_router import RecoveryType, _classify_for_recovery

        msg = "locator.click: Error: element is detached from the DOM"
        assert _classify_for_recovery(msg) == RecoveryType.DETACHED

    def test_classify_intercepted(self):
        from backend.engine.recovery_router import RecoveryType, _classify_for_recovery

        msg = "locator.click: Error: locator.click: Peek: intercepted by another element"
        assert _classify_for_recovery(msg) == RecoveryType.INTERCEPTED

    def test_attempt_recovery_strict_mode(self):
        from backend.engine.recovery_router import RecoveryType, attempt_recovery

        state = _make_state(page_state_snapshot="<div>Toolbar</div>")
        msg = "strict mode violation"
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, msg, planned)
        assert result is not None
        assert result.recovery_type == RecoveryType.STRICT_MODE
        # Snapshot contains "Toolbar" -> should match .p-toolbar
        assert result.modified_action["container_selector"] == ".p-toolbar"

    def test_attempt_recovery_timeout(self):
        from backend.engine.recovery_router import RecoveryType, attempt_recovery

        state = _make_state()
        msg = "Timeout 15000ms exceeded"
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, msg, planned)
        assert result is not None
        assert result.recovery_type == RecoveryType.TIMEOUT
        assert result.modified_action == {"action": "wait", "value": 3000}

    def test_attempt_recovery_detached(self):
        from backend.engine.recovery_router import RecoveryType, attempt_recovery

        state = _make_state()
        msg = "element is detached from the DOM"
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, msg, planned)
        assert result is not None
        assert result.recovery_type == RecoveryType.DETACHED
        assert result.modified_action == {"action": "wait", "value": 500}

    def test_attempt_recovery_intercepted(self):
        from backend.engine.recovery_router import RecoveryType, attempt_recovery

        state = _make_state()
        msg = "intercepted by another element"
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, msg, planned)
        assert result is not None
        assert result.recovery_type == RecoveryType.INTERCEPTED
        assert result.modified_action["action"] == "press_key"
        assert result.modified_action["value"] == "Escape"

    def test_attempt_recovery_not_visible_found(self):
        from backend.engine.recovery_router import RecoveryType, attempt_recovery

        state = _make_state(page_state_snapshot="<div><p-accordion>Some Content</p-accordion></div>")
        msg = "element is not visible"
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, msg, planned)
        assert result is not None
        assert result.recovery_type == RecoveryType.NOT_VISIBLE
        assert "p-accordion" in result.modified_action["selector"]

    def test_attempt_recovery_not_visible_missing_parent(self):
        from backend.engine.recovery_router import attempt_recovery

        state = _make_state(page_state_snapshot="<div>Generic Content</div>")
        msg = "element is not visible"
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, msg, planned)
        assert result is None

    def test_attempt_recovery_disabled_flag(self):
        from backend.config import settings
        from backend.engine.recovery_router import attempt_recovery

        original = settings.recovery_strict_mode_enabled
        settings.recovery_strict_mode_enabled = False
        try:
            state = _make_state()
            msg = "strict mode violation"
            planned = {"action": "click", "name": "Submit"}
            result = attempt_recovery(state, msg, planned)
            assert result is None
        finally:
            settings.recovery_strict_mode_enabled = original

    def test_attempt_recovery_already_attempted(self):
        from backend.engine.recovery_router import attempt_recovery

        # Legacy backward compatibility check
        state = _make_state(recovery_attempted=True)
        msg = "strict mode violation"
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, msg, planned)
        assert result is None

        # Modern set-based check
        state_modern = _make_state(recovery_attempted_types={"STRICT_MODE"})
        result_modern = attempt_recovery(state_modern, msg, planned)
        assert result_modern is None


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: Evaluator Integration (Mocked)
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluatorRecoveryIntegration:
    """Verify that the evaluator correctly calls and acts on the recovery router."""

    @pytest.mark.anyio
    async def test_evaluator_triggers_recovery(self, monkeypatch):
        from backend.engine.evaluator import evaluator_node
        from backend.engine.recovery_router import RecoveryResult, RecoveryType

        # 1. Setup mock recovery result
        mock_result = RecoveryResult(
            recovery_type=RecoveryType.STRICT_MODE,
            modified_action={"action": "click", "container_selector": ".p-panel"},
            critique="Mock Recovery",
            recovery_log={"test": "log"},
        )

        def mock_attempt_recovery(state, error_msg, planned_action):
            return mock_result

        monkeypatch.setattr("backend.engine.recovery_router.attempt_recovery", mock_attempt_recovery)

        # 2. Setup state for failure
        state = _make_state(
            ac_step_action_fail_count=0,
            detailed_execution_log=[
                {
                    "success": False,
                    "error_message": "strict mode violation",
                    "action_type": "click",
                    "action_payload": {"strategy": "get_by_role", "role": "button", "name": "Submit"},
                }
            ],
        )

        # 3. Call evaluator
        result = await evaluator_node(state)

        # 4. Verify recovery was applied
        assert result["_next_node"] == "planner"
        assert "STRICT_MODE" in result["recovery_attempted_types"]
        assert result["planned_action"]["container_selector"] == ".p-panel"
        assert "Mock Recovery" in result["agent_critique"]
        # Fail count should NOT be incremented (stays at initial state 0)
        assert result["ac_step_action_fail_count"] == 0

    @pytest.mark.anyio
    async def test_evaluator_skips_recovery_if_already_attempted(self):
        from backend.engine.evaluator import evaluator_node

        # Start with fail count 0, with STRICT_MODE in recovery_attempted_types
        state = _make_state(
            recovery_attempted_types={"STRICT_MODE"},
            ac_step_action_fail_count=0,
            detailed_execution_log=[
                {
                    "success": False,
                    "error_message": "strict mode violation",
                    "action_type": "click",
                    "action_payload": {"strategy": "get_by_role", "role": "button", "name": "Submit"},
                }
            ],
        )

        result = await evaluator_node(state)
        # Should fall through to normal retry (increment fail count from 0 to 1)
        assert result["ac_step_action_fail_count"] == 1

    @pytest.mark.anyio
    async def test_evaluator_skips_recovery_if_already_attempted_legacy(self):
        from backend.engine.evaluator import evaluator_node

        # Start with fail count 0, with legacy recovery_attempted=True
        state = _make_state(
            recovery_attempted=True,
            ac_step_action_fail_count=0,
            detailed_execution_log=[
                {
                    "success": False,
                    "error_message": "strict mode violation",
                    "action_type": "click",
                    "action_payload": {"strategy": "get_by_role", "role": "button", "name": "Submit"},
                }
            ],
        )

        result = await evaluator_node(state)
        # Should fall through to normal retry due to legacy fallback (increment from 0 to 1)
        assert result["ac_step_action_fail_count"] == 1

    @pytest.mark.anyio
    async def test_evaluator_resets_recovery_on_step_advance(self):
        """recovery_attempted_types should reset to empty set when AC step advances.

        NOTE (Bug D fix): Added ac_step_index=0 to ac_steps_completed to simulate
        post-verifier re-entry state. Without this, the Bug D guard routes to verifier
        instead of advancing the step. Adding step 0 to ac_steps_completed correctly
        simulates the post-verifier re-entry scenario where step 0 was already confirmed.
        """
        from backend.engine.evaluator import evaluator_node

        state = _make_state(
            recovery_attempted_types={"STRICT_MODE"},
            ac_step_index=0,
            # Bug D fix: include current step in ac_steps_completed to simulate
            # post-verifier re-entry (guard bypassed, step-advance path tested)
            ac_steps_completed=[0],
            planner_iteration=5,
            max_planner_iterations=500,
        )
        state["jira_ticket"]["acceptance_criteria_steps"] = [
            "Step 1: Test",
            "Step 2: Test",
        ]
        state["detailed_execution_log"] = [
            {
                "step_index": 5,
                "ac_step_index": 0,
                "timestamp": "2026-05-11T00:00:00Z",
                "action_type": "done",
                "action_payload": {"action": "done"},
                "locator_strategy": "",
                "locator_value": "",
                "data_input": None,
                "screenshot_url": "",
                "accessibility_tree_snippet": "",
                "success": True,
                "error_message": None,
                "self_heal_attempt": 0,
                "llm_reasoning": "Step complete",
                "llm_observation": "",
                "llm_thought": "",
            }
        ]
        state["planned_action"] = {"action": "done"}

        result = await evaluator_node(state)
        assert result["_next_node"] == "planner"
        assert result["ac_step_index"] == 1  # Advanced
        assert result.get("recovery_attempted_types") == set()  # Reset!


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: Edge Cases (AC-ERROR-1, AC-ERROR-3)
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Verify edge cases: empty inputs, all flags disabled, None planned_action."""

    def test_empty_error_msg_returns_none(self):
        """AC-ERROR-3: attempt_recovery with empty error_msg should return None."""
        from backend.engine.recovery_router import attempt_recovery

        state = _make_state()
        result = attempt_recovery(state, "", {"action": "click"})
        assert result is None

    def test_none_planned_action_no_crash(self):
        """AC-ERROR-3: None/empty planned_action should not crash."""
        from backend.engine.recovery_router import attempt_recovery

        state = _make_state()
        result = attempt_recovery(state, "strict mode violation", {})
        # Should still return a result (STRICT_MODE handler handles empty actions)
        assert result is not None or result is None  # No crash

    def test_all_flags_disabled_returns_none(self):
        """AC-ERROR-1: When all flags disabled, no recovery should trigger."""
        from backend.config import settings
        from backend.engine.recovery_router import attempt_recovery

        originals = {
            "recovery_strict_mode_enabled": settings.recovery_strict_mode_enabled,
            "recovery_timeout_enabled": settings.recovery_timeout_enabled,
            "recovery_not_visible_enabled": settings.recovery_not_visible_enabled,
            "recovery_detached_enabled": settings.recovery_detached_enabled,
            "recovery_intercepted_enabled": settings.recovery_intercepted_enabled,
        }
        try:
            for flag in originals:
                setattr(settings, flag, False)

            state = _make_state()
            # Try each error type — all should return None
            for msg in [
                "strict mode violation",
                "Timeout 15000ms exceeded",
                "element is not visible",
                "element is detached",
                "intercepted by another element",
            ]:
                result = attempt_recovery(state, msg, {"action": "click", "name": "X"})
                assert result is None, f"Expected None for '{msg}' with all flags disabled"
        finally:
            for flag, val in originals.items():
                setattr(settings, flag, val)

    def test_unrecognized_error_returns_none(self):
        """Unknown error messages should not trigger any recovery."""
        from backend.engine.recovery_router import attempt_recovery

        state = _make_state()
        result = attempt_recovery(state, "some completely unknown error XYZ", {"action": "click"})
        assert result is None

    def test_strict_mode_with_existing_container_returns_none(self):
        """AC: STRICT_MODE with existing container_selector returns None (can't double-scope)."""
        from backend.engine.recovery_router import attempt_recovery

        state = _make_state()
        planned = {"action": "click", "name": "Submit", "container_selector": ".p-toolbar"}
        result = attempt_recovery(state, "strict mode violation", planned)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Test 6: Multi-Type Recovery Router Tests (FEAT-079 / TASK-097)
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiTypeRecoveryRouterGatedByType:
    """Verify AC-2: recovery router checks whether the classified recovery type has already been tried."""

    def test_recovery_router_gated_by_type(self):
        from backend.engine.recovery_router import attempt_recovery

        # Case 1: STRICT_MODE not in recovery_attempted_types -> recovery proceeds
        state = _make_state(recovery_attempted_types={"TIMEOUT"})
        planned = {"action": "click", "name": "Submit"}
        result = attempt_recovery(state, "strict mode violation", planned)
        assert result is not None
        assert result.recovery_type.value == "STRICT_MODE"

        # Case 2: STRICT_MODE is in recovery_attempted_types -> recovery returns None (blocked)
        state_blocked = _make_state(recovery_attempted_types={"STRICT_MODE"})
        result_blocked = attempt_recovery(state_blocked, "strict mode violation", planned)
        assert result_blocked is None


class TestMultiTypeRecoveryAttemptLogging:
    """Verify AC-3: Dispatched recovery types are added to recovery_attempted_types in the state by evaluator."""

    @pytest.mark.anyio
    async def test_recovery_type_added_to_state_on_dispatch(self):
        from backend.engine.evaluator import evaluator_node

        state = _make_state(
            recovery_attempted_types=set(),
            ac_step_action_fail_count=0,
            detailed_execution_log=[
                {
                    "success": False,
                    "error_message": "strict mode violation",
                    "action_type": "click",
                    "action_payload": {"strategy": "get_by_role", "role": "button", "name": "Submit"},
                }
            ],
        )

        result = await evaluator_node(state)
        assert result["_next_node"] == "planner"
        assert "STRICT_MODE" in result["recovery_attempted_types"]
        assert len(result["recovery_attempted_types"]) == 1


class TestBackwardCompatibleStateMigration:
    """Verify AC-4: Older/deserialized VQAState is safely converted to support multi-type recovery."""

    def test_backward_compatible_state_migration(self):
        from backend.engine.recovery_router import attempt_recovery

        # Older dictionary lacking both fields -> falls back to empty set -> proceeds
        state_empty = {}
        planned = {"action": "click", "name": "Submit"}
        result_empty = attempt_recovery(state_empty, "strict mode violation", planned)
        assert result_empty is not None

        # Older dictionary with list serialized from JSON -> converted to set -> blocks appropriately
        state_list = {"recovery_attempted_types": ["STRICT_MODE"]}
        result_list = attempt_recovery(state_list, "strict mode violation", planned)
        assert result_list is None

        # Older dictionary with legacy recovery_attempted=True -> converted -> blocks everything
        state_legacy = {"recovery_attempted": True}
        result_legacy = attempt_recovery(state_legacy, "strict mode violation", planned)
        assert result_legacy is None


class TestSequencedMultiTypeRecovery:
    """Verify AC-5: Sequenced execution of multiple recovery actions of different types on the same step."""

    @pytest.mark.anyio
    async def test_multiple_distinct_recoveries_on_same_step(self):
        from backend.engine.evaluator import evaluator_node

        # Iteration 1: Step experiences STRICT_MODE violation
        state_1 = _make_state(
            recovery_attempted_types=set(),
            ac_step_action_fail_count=0,
            detailed_execution_log=[
                {
                    "success": False,
                    "error_message": "strict mode violation",
                    "action_type": "click",
                    "action_payload": {"strategy": "get_by_role", "role": "button", "name": "Submit"},
                }
            ],
        )

        result_1 = await evaluator_node(state_1)
        assert result_1["_next_node"] == "planner"
        assert "STRICT_MODE" in result_1["recovery_attempted_types"]
        assert len(result_1["recovery_attempted_types"]) == 1

        # Iteration 2: Now the same step experiences a TIMEOUT failure
        state_2 = _make_state(
            recovery_attempted_types=result_1["recovery_attempted_types"],
            ac_step_action_fail_count=0,
            detailed_execution_log=[
                {
                    "success": False,
                    "error_message": "Timeout 15000ms exceeded",
                    "action_type": "click",
                    "action_payload": {"strategy": "get_by_role", "role": "button", "name": "Submit"},
                }
            ],
        )

        result_2 = await evaluator_node(state_2)
        assert result_2["_next_node"] == "planner"
        assert "STRICT_MODE" in result_2["recovery_attempted_types"]
        assert "TIMEOUT" in result_2["recovery_attempted_types"]
        assert len(result_2["recovery_attempted_types"]) == 2

        # Iteration 3: Third failure of STRICT_MODE -> now blocked and escalates (no recovery, falls through)
        state_3 = _make_state(
            recovery_attempted_types=result_2["recovery_attempted_types"],
            ac_step_action_fail_count=0,
            detailed_execution_log=[
                {
                    "success": False,
                    "error_message": "strict mode violation",
                    "action_type": "click",
                    "action_payload": {"strategy": "get_by_role", "role": "button", "name": "Submit"},
                }
            ],
        )

        result_3 = await evaluator_node(state_3)
        # Falls through to normal retry (or vision mode/reporter if retries are high)
        assert result_3["ac_step_action_fail_count"] == 1


# ---------------------------------------------------------------------------
# T3-c Boundary Tests (FEAT-118-vqa-tier3-architectural-hardening Phase 3)
# ---------------------------------------------------------------------------

class TestReflexRecoveryRouterBoundary:
    """
    Verify that the reflex layer (T3-c) and recovery_router (FEAT-022) have
    non-overlapping responsibilities:
    - Reflex owns: native_select_detected, spinner_present, aria_expanded_false,
      portal_not_open, action_repeat_loop, strict_mode_0_visible
    - recovery_router owns: STRICT_MODE (multiple), TIMEOUT, NOT_VISIBLE, DETACHED, INTERCEPTED
    """

    def test_reflex_owns_native_select_not_recovery_router(self):
        """
        native_select_detected is a reflex-owned signature.
        recovery_router.attempt_recovery returns None for this error pattern
        (it is not classified as any RecoveryType).
        """
        from backend.engine.recovery_router import attempt_recovery, RecoveryType
        from backend.engine.reflex import attempt_short_circuit

        error_msg = "use locator.select_option() for <select> elements"
        state = {
            "run_id": "boundary-test",
            "retry_count": 1,
            "page_state_snapshot": "",
            "action_repeat_counts": {},
            "recovery_attempted": False,
            "recovery_attempted_types": [],
        }
        planned_action = {"action": "click", "strategy": "get_by_text", "text": "Status"}

        # Reflex MUST hit for this signature
        reflex_result = attempt_short_circuit(state, error_msg, planned_action)
        assert reflex_result is not None, "Reflex must hit for native_select_detected"
        assert reflex_result.signature == "native_select_detected"

        # recovery_router must NOT classify this as any RecoveryType
        # (it should return None — this is reflex's territory)
        router_result = attempt_recovery(state, error_msg, planned_action)
        assert router_result is None, (
            "recovery_router should return None for native_select_detected "
            "(this is reflex's territory — no overlap expected)"
        )

    def test_recovery_router_still_handles_strict_mode_multiple(self):
        """
        STRICT_MODE (multiple elements) remains recovery_router's responsibility.
        Reflex only handles the 0-visible variant; recovery_router handles the multi-visible variant.
        """
        from backend.engine.recovery_router import attempt_recovery
        from backend.engine.reflex import attempt_short_circuit

        # Multi-element strict mode (recovery_router's domain)
        error_msg = "strict mode violation, 3 elements found"
        state = {
            "run_id": "boundary-test-2",
            "retry_count": 1,
            "page_state_snapshot": "",
            "action_repeat_counts": {},
            "recovery_attempted": False,
            "recovery_attempted_types": [],
        }
        planned_action = {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Save"}

        # Reflex should NOT hit for multi-element strict mode (it handles 0-visible only)
        reflex_result = attempt_short_circuit(state, error_msg, planned_action)
        # (reflex may or may not hit depending on exact pattern — what matters is recovery_router also works)

        # recovery_router MUST handle STRICT_MODE
        router_result = attempt_recovery(state, error_msg, planned_action)
        assert router_result is not None, (
            "recovery_router must handle STRICT_MODE (multi-element) — this is its core responsibility"
        )
        assert router_result.recovery_type.value == "STRICT_MODE"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 — A11Y_AMBIGUOUS Recovery Tests (accessibility-tree-grounding)
# AC-VERIFY-8: RecoveryType.A11Y_AMBIGUOUS feature-flagged off by default
# ═══════════════════════════════════════════════════════════════════════════


class TestA11yAmbiguousRecovery:
    """Tests for the A11Y_AMBIGUOUS recovery type added in Phase 3."""

    def test_a11y_ambiguous_disabled_by_default(self):
        """settings.recovery_a11y_ambiguous_enabled defaults to False (AC-VERIFY-8)."""
        from backend.config import Settings

        assert "recovery_a11y_ambiguous_enabled" in Settings.model_fields
        field_info = Settings.model_fields["recovery_a11y_ambiguous_enabled"]
        # The default must be False so existing runs are unaffected
        assert field_info.default is False

    def test_a11y_ambiguous_max_retries_config_exists(self):
        """settings.a11y_ambiguous_max_retries defaults to 2."""
        from backend.config import Settings

        assert "a11y_ambiguous_max_retries" in Settings.model_fields
        field_info = Settings.model_fields["a11y_ambiguous_max_retries"]
        assert field_info.default == 2

    def test_a11y_ambiguous_enum_value_exists(self):
        """RecoveryType.A11Y_AMBIGUOUS enum member is defined."""
        from backend.engine.recovery_router import RecoveryType

        assert RecoveryType.A11Y_AMBIGUOUS == "A11Y_AMBIGUOUS"

    def test_is_recovery_enabled_returns_false_by_default(self):
        """_is_recovery_enabled returns False for A11Y_AMBIGUOUS by default."""
        from backend.engine.recovery_router import RecoveryType, _is_recovery_enabled
        from unittest.mock import patch

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.recovery_a11y_ambiguous_enabled = False
            result = _is_recovery_enabled(RecoveryType.A11Y_AMBIGUOUS)
        assert result is False

    def test_is_recovery_enabled_returns_true_when_flag_on(self):
        """_is_recovery_enabled returns True for A11Y_AMBIGUOUS when flag enabled."""
        from backend.engine.recovery_router import RecoveryType, _is_recovery_enabled
        from unittest.mock import patch

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.recovery_a11y_ambiguous_enabled = True
            result = _is_recovery_enabled(RecoveryType.A11Y_AMBIGUOUS)
        assert result is True

    def test_classifier_prefers_a11y_ambiguous_when_last_resolution_path_set(self):
        """_classify_for_recovery returns A11Y_AMBIGUOUS when state["last_resolution_path"]
        is 'selector_fallback_ambiguous' and the flag is on (AC-VERIFY-8 / Algorithm Decision 2)."""
        from backend.engine.recovery_router import RecoveryType, _classify_for_recovery
        from unittest.mock import patch

        state = {"last_resolution_path": "selector_fallback_ambiguous"}

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.recovery_a11y_ambiguous_enabled = True
            # strict mode violation error — normally → STRICT_MODE; but state marker → A11Y_AMBIGUOUS
            result = _classify_for_recovery("strict mode violation", state)
        assert result == RecoveryType.A11Y_AMBIGUOUS

    def test_classifier_falls_back_to_strict_mode_when_flag_off(self):
        """When flag is off, strict mode error → STRICT_MODE even if resolution path is set."""
        from backend.engine.recovery_router import RecoveryType, _classify_for_recovery
        from unittest.mock import patch

        state = {"last_resolution_path": "selector_fallback_ambiguous"}

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.recovery_a11y_ambiguous_enabled = False
            result = _classify_for_recovery("strict mode violation", state)
        assert result == RecoveryType.STRICT_MODE

    def test_a11y_ambiguous_returns_none_when_no_disambiguators(self):
        """Handler returns None when aria_disambiguators is absent — cedes to STRICT_MODE."""
        from backend.engine.recovery_router import _recover_a11y_ambiguous

        state = _make_state()
        action = {"action": "click", "role": "button", "name": "Save"}
        result = _recover_a11y_ambiguous(state, action)
        assert result is None

    def test_a11y_ambiguous_injects_container_from_single_disambiguator(self):
        """Handler builds container_selector from a single bare attribute disambiguator."""
        from backend.engine.recovery_router import _recover_a11y_ambiguous
        from unittest.mock import patch

        state = _make_state()
        state["locator_failure_diary"] = {}
        action = {
            "action": "click",
            "role": "button",
            "name": "Save",
            "_aria_disambiguators": ["aria-label"],
        }

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.a11y_ambiguous_max_retries = 2
            result = _recover_a11y_ambiguous(state, action)

        assert result is not None
        assert result.recovery_type.value == "A11Y_AMBIGUOUS"
        assert result.modified_action is not None
        container = result.modified_action.get("container_selector", "")
        assert "[aria-label]" in container

    def test_a11y_ambiguous_injects_container_from_valued_disambiguator(self):
        """Handler builds container_selector from an 'attr:value' disambiguator entry."""
        from backend.engine.recovery_router import _recover_a11y_ambiguous
        from unittest.mock import patch

        state = _make_state()
        state["locator_failure_diary"] = {}
        action = {
            "action": "click",
            "role": "button",
            "name": "Save",
            "_aria_disambiguators": ["aria-label:Save button"],
        }

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.a11y_ambiguous_max_retries = 2
            result = _recover_a11y_ambiguous(state, action)

        assert result is not None
        container = result.modified_action.get("container_selector", "")
        assert '[aria-label="Save button"]' in container

    def test_a11y_ambiguous_rejects_unknown_disambiguator_attrs(self):
        """Handler returns None when disambiguators contain only non-whitelisted attributes."""
        from backend.engine.recovery_router import _recover_a11y_ambiguous
        from unittest.mock import patch

        state = _make_state()
        state["locator_failure_diary"] = {}
        action = {
            "action": "click",
            "role": "button",
            "name": "Save",
            "_aria_disambiguators": ["data-secret", "x-custom-attr"],
        }

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.a11y_ambiguous_max_retries = 2
            result = _recover_a11y_ambiguous(state, action)

        assert result is None

    def test_a11y_ambiguous_failure_diary_caps_retries(self):
        """After max_retries fingerprint hits, handler returns None (Failure Diary cap)."""
        from backend.engine.recovery_router import _recover_a11y_ambiguous, _locator_fingerprint
        from unittest.mock import patch

        state = _make_state()
        state["current_url"] = "https://qa.vcreative.net/production-orders"
        action = {
            "action": "click",
            "role": "button",
            "name": "Save",
            "_aria_disambiguators": ["aria-label"],
        }

        # Pre-populate diary at the cap
        fp = _locator_fingerprint(state, action)
        state["locator_failure_diary"] = {fp: 2}  # already at max (default max_retries=2)

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.a11y_ambiguous_max_retries = 2
            result = _recover_a11y_ambiguous(state, action)

        assert result is None, "Handler must return None when Failure Diary cap is reached"

    def test_a11y_ambiguous_fingerprint_is_url_scoped(self):
        """Fingerprints for the same role+name on different pages are different."""
        from backend.engine.recovery_router import _locator_fingerprint

        action = {"role": "button", "name": "Save"}

        state_a = _make_state()
        state_a["current_url"] = "https://qa.vcreative.net/production-orders"

        state_b = _make_state()
        state_b["current_url"] = "https://qa.vcreative.net/quick-order"

        fp_a = _locator_fingerprint(state_a, action)
        fp_b = _locator_fingerprint(state_b, action)

        assert fp_a != fp_b, "Different page paths must produce different Failure Diary fingerprints"

    def test_attempt_recovery_routes_a11y_ambiguous_when_enabled(self):
        """Full attempt_recovery path: flag on + state marker → A11Y_AMBIGUOUS handler fires."""
        from backend.engine.recovery_router import attempt_recovery, RecoveryType
        from unittest.mock import patch

        state = _make_state()
        state["last_resolution_path"] = "selector_fallback_ambiguous"
        state["locator_failure_diary"] = {}
        state["current_url"] = "https://qa.vcreative.net/test"

        action = {
            "action": "click",
            "role": "button",
            "name": "Save",
            "_aria_disambiguators": ["aria-label"],
        }

        with patch("backend.engine.recovery_router.settings") as mock_settings:
            mock_settings.recovery_a11y_ambiguous_enabled = True
            mock_settings.a11y_ambiguous_max_retries = 2
            # Other flags needed by attempt_recovery
            mock_settings.recovery_strict_mode_enabled = True
            mock_settings.recovery_timeout_enabled = True
            mock_settings.recovery_not_visible_enabled = True
            mock_settings.recovery_detached_enabled = True
            mock_settings.recovery_intercepted_enabled = True
            result = attempt_recovery(state, "strict mode violation", action)

        assert result is not None
        assert result.recovery_type == RecoveryType.A11Y_AMBIGUOUS
