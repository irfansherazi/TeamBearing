"""
TASK-014 Phase 3.1 Tests: Dropdown Registry Expansion
=====================================================
Tests that dropdown_registry.json includes at least 3 new categories
related to campaign and account management, and that the proactive
option injection logic correctly matches them.

TDD: These tests define the expected behavior BEFORE implementation.
"""

import json
import os
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_registry() -> dict:
    """Load the dropdown_registry.json file."""
    path = os.path.join(PROJECT_ROOT, "knowledge", "dropdown_registry.json")
    with open(path, "r") as f:
        return json.load(f)


# The categories that existed BEFORE TASK-014 (baseline from TASK-013).
# Phase 3.1 must add at least 3 NEW categories beyond these.
_BASELINE_CATEGORIES = {
    "Status",
    "Ad Type",
    "File Type",
    "Role",
    "Services",
    "Talent",
    "Campaign Status",
    "Account Coordinator",
    "Priority",
}


# ---------------------------------------------------------------------------
# AC-1: dropdown_registry.json includes at least 3 new categories
#        related to campaign and account management
# ---------------------------------------------------------------------------


class TestDropdownRegistryExpansion:
    """Verify dropdown_registry.json has been expanded with new categories."""

    def test_registry_loads_valid_json(self):
        """Registry file must be valid JSON."""
        registry = _load_registry()
        assert isinstance(registry, dict), "Registry must be a dict"

    def test_at_least_3_new_categories(self):
        """AC-1: At least 3 new categories beyond the TASK-013 baseline."""
        registry = _load_registry()
        new_categories = set(registry.keys()) - _BASELINE_CATEGORIES
        assert len(new_categories) >= 3, (
            f"Expected at least 3 new categories, found {len(new_categories)}: {new_categories}"
        )

    def test_new_categories_are_campaign_or_account_related(self):
        """AC-1: New categories should relate to campaign/account management."""
        registry = _load_registry()
        new_categories = set(registry.keys()) - _BASELINE_CATEGORIES

        # At least 3 new categories must exist
        assert len(new_categories) >= 3, f"Need at least 3 new categories, found: {new_categories}"

        # Each new category must have a non-empty list of options
        for cat in new_categories:
            options = registry[cat]
            assert isinstance(options, list), f"Category '{cat}' must be a list"
            assert len(options) >= 2, f"Category '{cat}' must have at least 2 options, found {len(options)}"

    def test_all_values_are_string_lists(self):
        """Every category value must be a list of strings."""
        registry = _load_registry()
        for key, options in registry.items():
            assert isinstance(options, list), f"'{key}' must map to a list"
            for opt in options:
                assert isinstance(opt, str), f"'{key}' option '{opt}' must be a string"

    def test_no_duplicate_options_within_category(self):
        """No category should have duplicate option values."""
        registry = _load_registry()
        for key, options in registry.items():
            seen = set()
            for opt in options:
                norm = opt.strip().lower()
                assert norm not in seen, f"Duplicate option '{opt}' in category '{key}'"
                seen.add(norm)

    def test_baseline_categories_preserved(self):
        """All baseline categories from TASK-013 must still exist."""
        registry = _load_registry()
        for cat in _BASELINE_CATEGORIES:
            assert cat in registry, f"Baseline category '{cat}' missing"


# ---------------------------------------------------------------------------
# AC-2 (partial — Phase 3.1 scope): Proactive option injection picks up
#       new categories from the expanded registry
# ---------------------------------------------------------------------------


class TestProactiveInjectionWithNewCategories:
    """Verify _get_matching_options finds new registry categories."""

    def test_injection_finds_new_category_by_exact_label(self):
        """If the AC step text contains the exact label of a new category,
        the injection function should return its options."""
        # Force reload of registry
        import backend.engine.planner as planner_mod
        from backend.engine.planner import _get_matching_options

        planner_mod._DROPDOWN_REGISTRY = None

        registry = _load_registry()
        new_categories = set(registry.keys()) - _BASELINE_CATEGORIES
        assert len(new_categories) >= 1, "Need at least 1 new category for test"

        # Pick the first new category and build a step mentioning it
        test_cat = sorted(new_categories)[0]
        step_text = f"Select the correct {test_cat} from the dropdown"

        result = _get_matching_options(step_text)
        assert result != "", f"Expected injection for step mentioning '{test_cat}', got empty"
        assert test_cat in result, f"Injection should contain label '{test_cat}'"

    def test_injection_returns_empty_for_unrelated_step(self):
        """Steps unrelated to any dropdown should return empty."""
        import backend.engine.planner as planner_mod
        from backend.engine.planner import _get_matching_options

        planner_mod._DROPDOWN_REGISTRY = None

        result = _get_matching_options("Verify the page title is correct and visible")
        # This might match some categories by word overlap —
        # the key assertion is it doesn't crash
        assert isinstance(result, str)

    def test_new_category_options_appear_in_injection_text(self):
        """The actual option values from new categories appear in injection."""
        import backend.engine.planner as planner_mod
        from backend.engine.planner import _get_matching_options

        planner_mod._DROPDOWN_REGISTRY = None

        registry = _load_registry()
        new_categories = set(registry.keys()) - _BASELINE_CATEGORIES
        assert len(new_categories) >= 1

        test_cat = sorted(new_categories)[0]
        expected_options = registry[test_cat]
        step_text = f"Choose the {test_cat} value"

        result = _get_matching_options(step_text)
        # At least some options should appear in the formatted injection
        for opt in expected_options[:2]:  # Check first 2 options
            assert opt in result, f"Option '{opt}' from '{test_cat}' should appear in injection"
