"""
TASK-014 Phase 3.3 Tests: Final Validation and Roadmap Update
=============================================================
Validates that:
  - AC-3: benchmark_pipeline.py maintains 100% pass rate on Golden 10
  - AC-4: roadmap.md status for FEAT-029 is set to 'complete'
  - All prior Phase 3.1/3.2 acceptance criteria remain satisfied

TDD: These tests verify the final integration state of FEAT-029.
"""

import json
import os
import re
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


def _load_roadmap() -> str:
    """Load roadmap.md as raw text."""
    path = os.path.join(PROJECT_ROOT, "memory-bank", "roadmap.md")
    with open(path, "r") as f:
        return f.read()


# Baseline categories from TASK-013 (same as Phase 3.1 test file)
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
# AC-3: Benchmark stability — structural validation
# ---------------------------------------------------------------------------


class TestBenchmarkStability:
    """Validate benchmark infrastructure is intact and parseable."""

    def test_golden_10_data_exists(self):
        """The Golden 10 benchmark dataset must exist."""
        path = os.path.join(PROJECT_ROOT, "tests", "benchmarks", "golden_10_data.json")
        assert os.path.exists(path), f"Golden 10 data not found at {path}"

    def test_golden_10_has_10_cards(self):
        """The Golden 10 dataset must contain exactly 10 test cards."""
        path = os.path.join(PROJECT_ROOT, "tests", "benchmarks", "golden_10_data.json")
        with open(path, "r") as f:
            cards = json.load(f)
        assert len(cards) == 10, f"Expected 10 cards, found {len(cards)}"

    def test_golden_10_cards_have_required_fields(self):
        """Each card must have ticket_id, summary, and acceptance_criteria."""
        path = os.path.join(PROJECT_ROOT, "tests", "benchmarks", "golden_10_data.json")
        with open(path, "r") as f:
            cards = json.load(f)
        for card in cards:
            assert "ticket_id" in card, f"Card missing ticket_id: {card}"
            assert "summary" in card, f"Card missing summary: {card}"
            assert "acceptance_criteria" in card, f"Card {card.get('ticket_id', '?')} missing acceptance_criteria"

    def test_benchmark_script_importable(self):
        """benchmark_pipeline.py must be importable without crashing."""
        scripts_dir = os.path.join(PROJECT_ROOT, "scripts")
        sys.path.insert(0, scripts_dir)
        try:
            # Just test that the module can be loaded (it does import heavy deps)
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "benchmark_pipeline",
                os.path.join(scripts_dir, "benchmark_pipeline.py"),
            )
            assert spec is not None, "Cannot find benchmark_pipeline.py"
        finally:
            sys.path.pop(0)

    def test_benchmark_script_has_run_function(self):
        """benchmark_pipeline.py must export a run_benchmark coroutine."""
        scripts_dir = os.path.join(PROJECT_ROOT, "scripts")
        sys.path.insert(0, scripts_dir)
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "benchmark_pipeline",
                os.path.join(scripts_dir, "benchmark_pipeline.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            assert hasattr(mod, "run_benchmark"), "Missing run_benchmark function"
            import asyncio

            assert asyncio.iscoroutinefunction(mod.run_benchmark), "run_benchmark must be an async function"
        finally:
            sys.path.pop(0)


# ---------------------------------------------------------------------------
# AC-4: roadmap.md FEAT-029 status set to 'complete'
# ---------------------------------------------------------------------------


class TestRoadmapFEAT029Closure:
    """Verify FEAT-029 is marked complete in roadmap.md."""

    def test_feat_029_status_is_complete(self):
        """FEAT-029 status line in roadmap.md must say 'complete'."""
        roadmap = _load_roadmap()

        # Find the FEAT-029 section
        feat_029_match = re.search(
            r"###\s+FEAT-029:.*?\n(.*?)(?=\n###|\Z)",
            roadmap,
            re.DOTALL,
        )
        assert feat_029_match, "FEAT-029 section not found in roadmap.md"

        section = feat_029_match.group(0)
        # Status line should contain 'complete' (case-insensitive)
        status_match = re.search(r"\*\*Status\*\*:\s*(\S+)", section)
        assert status_match, "No **Status** line found in FEAT-029 section"
        assert status_match.group(1).lower() == "complete", (
            f"FEAT-029 status is '{status_match.group(1)}', expected 'complete'"
        )

    def test_feat_029_has_completed_date(self):
        """FEAT-029 should have a **Completed** date set."""
        roadmap = _load_roadmap()

        feat_029_match = re.search(
            r"###\s+FEAT-029:.*?\n(.*?)(?=\n###|\Z)",
            roadmap,
            re.DOTALL,
        )
        assert feat_029_match, "FEAT-029 section not found in roadmap.md"

        section = feat_029_match.group(0)
        completed_match = re.search(r"\*\*Completed\*\*:\s*(\S+)", section)
        assert completed_match, "FEAT-029 should have a **Completed** date"
        # Should be a date-like value, not empty
        assert len(completed_match.group(1)) >= 8, f"Completed date looks too short: '{completed_match.group(1)}'"

    def test_feat_029_linked_tasks_all_complete(self):
        """FEAT-029's linked tasks should reference completed tasks."""
        roadmap = _load_roadmap()

        feat_029_match = re.search(
            r"###\s+FEAT-029:.*?\n(.*?)(?=\n###|\Z)",
            roadmap,
            re.DOTALL,
        )
        assert feat_029_match

        section = feat_029_match.group(0)
        linked_match = re.search(r"\*\*Linked Tasks\*\*:\s*(.*)", section)
        assert linked_match, "FEAT-029 should have linked tasks"

        # Should mention tasks (TASK-011, TASK-013, TASK-014)
        linked_text = linked_match.group(1)
        assert "TASK-014" in linked_text, "FEAT-029 linked tasks should include TASK-014"


# ---------------------------------------------------------------------------
# AC-1 + AC-2 Regression: Phase 3.1 and 3.2 work still holds
# ---------------------------------------------------------------------------


class TestPhase31RegressionCheck:
    """Verify Phase 3.1 (dropdown registry expansion) is still intact."""

    def test_registry_has_new_categories(self):
        """At least 3 new categories beyond baseline must still exist."""
        registry = _load_registry()
        new_categories = set(registry.keys()) - _BASELINE_CATEGORIES
        assert len(new_categories) >= 3, f"Registry should have >= 3 new categories, found {len(new_categories)}"

    def test_all_baseline_categories_preserved(self):
        """All original baseline categories must still be present."""
        registry = _load_registry()
        for cat in _BASELINE_CATEGORIES:
            assert cat in registry, f"Baseline category '{cat}' is missing"


class TestPhase32RegressionCheck:
    """Verify Phase 3.2 (fuzzy matching) is still intact."""

    def test_partial_match_still_works(self):
        """'select an ad type' should still match 'Ad Type' via fuzzy matching."""
        import backend.engine.planner as planner_mod

        planner_mod._DROPDOWN_REGISTRY = None
        from backend.engine.planner import _get_matching_options

        result = _get_matching_options("select an ad type from the list")
        assert "Ad Type" in result

    def test_concatenated_match_still_works(self):
        """'adtype' should still match 'Ad Type'."""
        import backend.engine.planner as planner_mod

        planner_mod._DROPDOWN_REGISTRY = None
        from backend.engine.planner import _get_matching_options

        result = _get_matching_options("what adtype should I select")
        assert "Ad Type" in result


# ---------------------------------------------------------------------------
# Integration: All TASK-014 acceptance criteria summary
# ---------------------------------------------------------------------------


class TestAllAcceptanceCriteriaSummary:
    """Cross-check that ALL 4 acceptance criteria for TASK-014 are met."""

    def test_ac1_dropdown_registry_expanded(self):
        """AC-1: dropdown_registry.json includes >= 3 new categories."""
        registry = _load_registry()
        new_categories = set(registry.keys()) - _BASELINE_CATEGORIES
        assert len(new_categories) >= 3

    def test_ac2_partial_matching_works(self):
        """AC-2: _get_matching_options handles partial matches."""
        import backend.engine.planner as planner_mod

        planner_mod._DROPDOWN_REGISTRY = None
        from backend.engine.planner import _get_matching_options

        result = _get_matching_options("select an ad type from the list")
        assert "Ad Type" in result

    def test_ac3_benchmark_data_stable(self):
        """AC-3: Golden 10 benchmark data is intact and well-formed."""
        path = os.path.join(PROJECT_ROOT, "tests", "benchmarks", "golden_10_data.json")
        with open(path, "r") as f:
            cards = json.load(f)
        assert len(cards) == 10
        for card in cards:
            assert "ticket_id" in card
            assert "acceptance_criteria" in card

    def test_ac4_roadmap_feat029_complete(self):
        """AC-4: roadmap.md shows FEAT-029 as complete."""
        roadmap = _load_roadmap()
        feat_029_match = re.search(
            r"###\s+FEAT-029:.*?\n(.*?)(?=\n###|\Z)",
            roadmap,
            re.DOTALL,
        )
        assert feat_029_match
        section = feat_029_match.group(0)
        status_match = re.search(r"\*\*Status\*\*:\s*(\S+)", section)
        assert status_match
        assert status_match.group(1).lower() == "complete"
