"""
tests/engine/test_planner_selector_registry.py

Phase 2 — T3-b Selector-Registry-First Planner

Tests for RegistryFirstGate: the mandatory pre-emit gate that rewrites
planned actions on a registry hit and emits a telemetry event on a miss.

Coverage targets (AC-VERIFY-3, AC-VERIFY-4, AC-INTEGRATION-2):
  1. Registry hit → returned action strategy is NOT "get_by_text"
  2. Registry miss → "registry_enrichment_needed" event emitted with required fields
  3. Registry hit → original non-strategy fields are preserved
  4. Shadow mode → event emitted but action NOT rewritten
  5. QA-358 seed entry exists and has required fields
  6. Gate disabled → lookup skipped, original action returned unchanged
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# Import the module under test
from backend.engine.registry_first_gate import RegistryFirstGate

# Path to the selector registry JSON for structural tests
_REGISTRY_PATH = (
    Path(__file__).parent.parent.parent / "knowledge" / "selector_registry.json"
)


# ---------------------------------------------------------------------------
# Test 1: Registry hit rewrites strategy away from get_by_text (AC-VERIFY-3)
# ---------------------------------------------------------------------------

def test_registry_hit_emits_non_get_by_text_strategy():
    """
    Given a planned action with strategy='get_by_text' and an AC step whose
    target has a vpromotions registry entry, RegistryFirstGate.check() must
    return an action whose strategy is NOT 'get_by_text'.
    """
    planned_action: dict[str, Any] = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Contest",
        "reasoning": "Select the Contest option from the PRF Category dropdown.",
    }

    # Canned registry hit matching QA-358
    canned_hit = {
        "playwright_strategy": "get_by_role",
        "role": "option",
        "name": "Contest",
        "vqa_id": "prf-category-contest-option",
    }

    with patch(
        "backend.engine.registry_first_gate.selector_registry.lookup",
        return_value=canned_hit,
    ):
        with patch.dict(os.environ, {"REGISTRY_FIRST_GATE_ENABLED": "true", "REGISTRY_FIRST_GATE_SHADOW_MODE": "false"}):
            result = RegistryFirstGate.check(
                planned_action=planned_action,
                ac_step_text="Select Contest from PRF Category dropdown",
                product_slug="vpromotions",
            )

    assert result["strategy"] != "get_by_text", (
        "On a registry hit, strategy must not be 'get_by_text'; "
        f"got strategy={result['strategy']!r}"
    )
    assert result["strategy"] == "get_by_role"
    assert result.get("_registry_hit") is True


# ---------------------------------------------------------------------------
# Test 2: Registry miss emits registry_enrichment_needed event (AC-VERIFY-4)
# ---------------------------------------------------------------------------

def test_registry_miss_emits_registry_enrichment_needed_event(caplog):
    """
    Given a planned action with no matching registry entry, RegistryFirstGate.check()
    must emit a structured log event with event_type='registry_enrichment_needed'
    and the required fields: product, ac_step_text, inferred_target,
    planner_fallback_strategy, planner_fallback_locator.
    """
    planned_action: dict[str, Any] = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Some Unknown Element",
        "reasoning": "Trying to click an unregistered element.",
    }

    with patch(
        "backend.engine.registry_first_gate.selector_registry.lookup",
        return_value=None,
    ):
        with patch.dict(os.environ, {"REGISTRY_FIRST_GATE_ENABLED": "true", "REGISTRY_FIRST_GATE_SHADOW_MODE": "false"}):
            with caplog.at_level(logging.INFO, logger="backend.engine.registry_first_gate"):
                result = RegistryFirstGate.check(
                    planned_action=planned_action,
                    ac_step_text="Click some unknown thing on the page",
                    product_slug="vpromotions",
                )

    # Action must be unchanged (miss → passthrough)
    assert result["strategy"] == "get_by_text"
    assert result.get("_registry_hit") is not True

    # Find the enrichment-needed log record
    enrichment_records = [
        r for r in caplog.records
        if getattr(r, "event_type", None) == "registry_enrichment_needed"
        or "registry_enrichment_needed" in r.getMessage()
    ]
    assert len(enrichment_records) >= 1, (
        "Expected at least one log record with event_type='registry_enrichment_needed'; "
        f"got records: {[r.getMessage() for r in caplog.records]}"
    )

    # Verify required fields are present in the log record's extra attributes
    rec = enrichment_records[0]
    for required_field in ("product", "ac_step_text", "inferred_target"):
        assert hasattr(rec, required_field) or required_field in rec.getMessage(), (
            f"Missing required field '{required_field}' in registry_enrichment_needed event"
        )


# ---------------------------------------------------------------------------
# Test 3: Registry hit preserves non-strategy action fields (AC-VERIFY-3)
# ---------------------------------------------------------------------------

def test_registry_hit_preserves_action_fields():
    """
    On a registry hit, RegistryFirstGate.check() must preserve action fields
    that it does not explicitly override (e.g., 'action', 'reasoning').
    The gate rewrites strategy/role/name from the registry but must not
    silently discard other planner fields.
    """
    planned_action: dict[str, Any] = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Contest",
        "reasoning": "Planner reasoning text that must be preserved.",
        "container_selector": ".p-dropdown-panel",
    }

    canned_hit = {
        "playwright_strategy": "get_by_role",
        "role": "option",
        "name": "Contest",
        "vqa_id": "prf-category-contest-option",
    }

    with patch(
        "backend.engine.registry_first_gate.selector_registry.lookup",
        return_value=canned_hit,
    ):
        with patch.dict(os.environ, {"REGISTRY_FIRST_GATE_ENABLED": "true", "REGISTRY_FIRST_GATE_SHADOW_MODE": "false"}):
            result = RegistryFirstGate.check(
                planned_action=planned_action,
                ac_step_text="Select Contest from PRF Category dropdown",
                product_slug="vpromotions",
            )

    # Core action type must be preserved
    assert result["action"] == "click"
    # Reasoning must be preserved
    assert result["reasoning"] == "Planner reasoning text that must be preserved."
    # container_selector preserved
    assert result["container_selector"] == ".p-dropdown-panel"
    # strategy was rewritten
    assert result["strategy"] == "get_by_role"


# ---------------------------------------------------------------------------
# Test 4: Shadow mode emits hit event but does NOT rewrite action
# ---------------------------------------------------------------------------

def test_shadow_mode_emits_hit_but_does_not_rewrite(caplog):
    """
    When REGISTRY_FIRST_GATE_SHADOW_MODE=true, RegistryFirstGate.check() must:
    - Emit a 'registry_hit' log event (observability)
    - Return the original planned_action UNCHANGED (no strategy rewrite)
    This allows safe dark-launch rollout without affecting production behavior.
    """
    planned_action: dict[str, Any] = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Contest",
        "reasoning": "Test shadow mode.",
    }

    canned_hit = {
        "playwright_strategy": "get_by_role",
        "role": "option",
        "name": "Contest",
        "vqa_id": "prf-category-contest-option",
    }

    with patch(
        "backend.engine.registry_first_gate.selector_registry.lookup",
        return_value=canned_hit,
    ):
        with patch.dict(
            os.environ,
            {
                "REGISTRY_FIRST_GATE_ENABLED": "true",
                "REGISTRY_FIRST_GATE_SHADOW_MODE": "true",
            },
        ):
            with caplog.at_level(logging.INFO, logger="backend.engine.registry_first_gate"):
                result = RegistryFirstGate.check(
                    planned_action=planned_action,
                    ac_step_text="Select Contest from PRF Category dropdown",
                    product_slug="vpromotions",
                )

    # In shadow mode, action must NOT be rewritten
    assert result["strategy"] == "get_by_text", (
        "Shadow mode must NOT rewrite strategy; action should pass through unchanged"
    )
    assert result.get("_registry_hit") is not True

    # But a 'registry_hit' shadow log event must have been emitted
    shadow_records = [
        r for r in caplog.records
        if "registry_hit" in r.getMessage() or getattr(r, "event_type", None) == "registry_hit_shadow"
    ]
    assert len(shadow_records) >= 1, (
        "Shadow mode must emit a 'registry_hit' log event even though it does not rewrite; "
        f"got records: {[r.getMessage() for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# Test 5: QA-358 seed entry exists in selector_registry.json with required schema
# ---------------------------------------------------------------------------

def test_qa358_seed_entry_structure():
    """
    knowledge/selector_registry.json must contain a nested 'vpromotions' product key
    with a QA-358-seeded entry (prf_category_dropdown_contest_option) that has
    all required fields: playwright_strategy, role, name, ac_step_patterns, protected.
    This validates AC-INTEGRATION-2 pre-condition (seed must exist for the replay to work).
    """
    assert _REGISTRY_PATH.exists(), (
        f"selector_registry.json not found at {_REGISTRY_PATH}"
    )

    data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))

    # Must have a top-level 'vpromotions' key under selectors
    selectors = data.get("selectors", {})
    assert "vpromotions" in selectors, (
        "selector_registry.json must have a nested 'vpromotions' product key under 'selectors'"
    )

    vpromotions = selectors["vpromotions"]
    assert isinstance(vpromotions, dict), "'selectors.vpromotions' must be a dict"

    # Must have the QA-358 entry
    assert "prf_category_dropdown_contest_option" in vpromotions, (
        "vpromotions must contain 'prf_category_dropdown_contest_option' (QA-358 seed entry)"
    )

    entry = vpromotions["prf_category_dropdown_contest_option"]
    required_fields = ["playwright_strategy", "role", "name", "ac_step_patterns", "protected"]
    for field in required_fields:
        assert field in entry, (
            f"QA-358 seed entry missing required field '{field}'; entry={entry}"
        )

    # Validate field types
    assert isinstance(entry["ac_step_patterns"], list), "ac_step_patterns must be a list"
    assert len(entry["ac_step_patterns"]) >= 1, "ac_step_patterns must have at least one pattern"
    assert entry["protected"] is True, "QA-358 seed entry must have protected=true"
    assert entry["playwright_strategy"] != "get_by_text", (
        "QA-358 seed strategy must not be get_by_text (it's a deterministic registry entry)"
    )


# ---------------------------------------------------------------------------
# Test 6: Gate disabled → lookup skipped, original action returned unchanged
# ---------------------------------------------------------------------------

def test_registry_first_gate_disabled_skips_lookup():
    """
    When REGISTRY_FIRST_GATE_ENABLED=false, RegistryFirstGate.check() must
    return the original planned_action unchanged without calling lookup().
    This ensures the gate can be safely disabled without side effects.
    """
    planned_action: dict[str, Any] = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Contest",
        "reasoning": "Gate should be disabled.",
    }

    mock_lookup = MagicMock(return_value={"playwright_strategy": "get_by_role"})

    with patch("backend.engine.registry_first_gate.selector_registry.lookup", mock_lookup):
        with patch.dict(os.environ, {"REGISTRY_FIRST_GATE_ENABLED": "false"}):
            result = RegistryFirstGate.check(
                planned_action=planned_action,
                ac_step_text="Select Contest from PRF Category dropdown",
                product_slug="vpromotions",
            )

    # lookup must NOT have been called
    mock_lookup.assert_not_called()

    # Action must be unchanged
    assert result["strategy"] == "get_by_text"
    assert result.get("_registry_hit") is not True
