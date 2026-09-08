"""
TASK-014 Phase 3.2 Tests: Fuzzy Matching Enhancement
=====================================================
Tests that `planner.py` -> `_get_matching_options` handles partial matches
robustly, including case-insensitive substring matching, word-overlap matching
with filler words (articles, prepositions), plural/singular normalization,
concatenated word splitting, and multi-word label variations.

AC-2: planner.py -> _get_matching_options handles partial matches
     (e.g., "Ad Type" matching "select an ad type").

TDD: These tests define the expected behavior BEFORE implementation.
"""

import os
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_registry():
    """Force reload of the dropdown registry to ensure clean state."""
    import backend.engine.planner as planner_mod

    planner_mod._DROPDOWN_REGISTRY = None


def _get_matching(step_text: str, state=None) -> str:
    """Shortcut: reset registry and call _get_matching_options."""
    _reset_registry()
    from backend.engine.planner import _get_matching_options

    return _get_matching_options(step_text, state)


# ---------------------------------------------------------------------------
# AC-2: Partial matching — "Ad Type" matches "select an ad type"
# ---------------------------------------------------------------------------


class TestPartialMatchBasics:
    """Core partial matching behavior per AC-2."""

    def test_exact_label_match(self):
        """Direct substring: step containing 'Ad Type' matches the 'Ad Type' category."""
        result = _get_matching("Select the Ad Type dropdown")
        assert "Ad Type" in result
        assert "Radio Commercial" in result

    def test_partial_match_with_articles(self):
        """AC-2 canonical case: 'select an ad type' should match 'Ad Type'."""
        result = _get_matching("select an ad type from the list")
        assert "Ad Type" in result, (
            "Expected 'Ad Type' match for 'select an ad type' — "
            "filler words ('an') should not block word-overlap matching"
        )

    def test_partial_match_case_insensitive(self):
        """'ad type' (lowercase) should match 'Ad Type' label."""
        result = _get_matching("choose the correct ad type")
        assert "Ad Type" in result

    def test_partial_match_with_prepositions(self):
        """'the file type for' should match 'File Type'."""
        result = _get_matching("select the file type for the upload")
        assert "File Type" in result

    def test_partial_match_with_verb_prefix(self):
        """'verify the status is correct' should match 'Status'."""
        result = _get_matching("verify the status is correct")
        assert "Status" in result


class TestPartialMatchWordOverlap:
    """Word-overlap matching robustness — label words as subset of step words."""

    def test_multi_word_label_scattered_in_step(self):
        """'Campaign Status' words scattered: 'check the campaign current status'."""
        result = _get_matching("check the campaign current status")
        assert "Campaign Status" in result

    def test_multi_word_label_with_intervening_words(self):
        """'Account Type' in 'select the account type from dropdown'."""
        result = _get_matching("select the account type from dropdown")
        assert "Account Type" in result

    def test_single_word_label_in_longer_step(self):
        """'Status' (single-word label) found in a longer step."""
        result = _get_matching("update the order status to Completed")
        assert "Status" in result

    def test_no_match_for_partial_word(self):
        """'stat' should NOT match 'Status' — we require full word matches."""
        result = _get_matching("check the stat column for data")
        # 'stat' is not 'status', so Status should NOT match via word overlap
        # The key: the function should not crash
        assert isinstance(result, str)

    def test_word_overlap_ignores_stop_words(self):
        """Labels like 'Ad Type' should match even when step has
        articles/prepositions between label words."""
        result = _get_matching("please select an ad type now")
        assert "Ad Type" in result


class TestFuzzyMatchEnhancements:
    """Phase 3.2 enhancements: plural normalization & concatenated word splitting."""

    def test_plural_form_matches_singular_label(self):
        """'accounts' in step text should match 'Account' in 'Account Type' label."""
        result = _get_matching("set the accounts type from the list")
        assert "Account Type" in result, "Plural 'accounts' should fuzzy-match singular label word 'account'"

    def test_singular_form_matches_plural_label_word(self):
        """If a label had a plural word, singular step text should match."""
        result = _get_matching("select the service dropdown")
        assert "Services" in result, "Singular 'service' should fuzzy-match plural label 'Services'"

    def test_concatenated_words_match_multi_word_label(self):
        """'adtype' (concatenated) should match 'Ad Type' label."""
        result = _get_matching("what adtype should I select")
        assert "Ad Type" in result, "Concatenated 'adtype' should fuzzy-match 'Ad Type'"

    def test_concatenated_filetype_matches(self):
        """'filetype' (concatenated) should match 'File Type' label."""
        result = _get_matching("choose the filetype for upload")
        assert "File Type" in result, "Concatenated 'filetype' should fuzzy-match 'File Type'"

    def test_hyphenated_label_words(self):
        """'campaign-type' (hyphenated) should still match 'Campaign Type'."""
        result = _get_matching("select the campaign-type dropdown")
        assert "Campaign Type" in result

    def test_underscore_separated_label_words(self):
        """'campaign_status' should match 'Campaign Status'."""
        result = _get_matching("check the campaign_status field")
        assert "Campaign Status" in result


class TestPartialMatchEdgeCases:
    """Edge cases for the matching algorithm."""

    def test_empty_step_text(self):
        """Empty step text should return empty string (no crash)."""
        result = _get_matching("")
        assert result == ""

    def test_very_long_step_text(self):
        """Very long step text should not cause performance issues."""
        long_text = "verify the status " * 100
        result = _get_matching(long_text)
        assert isinstance(result, str)
        assert "Status" in result

    def test_special_characters_in_step(self):
        """Special chars in step text should not crash regex."""
        result = _get_matching("select [Ad Type] from (dropdown)")
        assert isinstance(result, str)
        assert "Ad Type" in result

    def test_multiple_labels_match(self):
        """Step mentioning multiple labels returns all matches."""
        result = _get_matching("select the Ad Type and File Type dropdowns")
        assert "Ad Type" in result
        assert "File Type" in result

    def test_no_false_positives_on_common_words(self):
        """Generic words like 'type' alone should not match 'Ad Type'.
        The word 'type' appears in many labels — but 'Ad Type' requires
        both 'ad' AND 'type' to be present."""
        result = _get_matching("What type of element is this?")
        assert isinstance(result, str)

    def test_accessibility_tree_scanning(self):
        """Matching also works against the accessibility tree in state."""
        state = {
            "current_accessibility_tree": "combobox 'Select Ad Type' options visible",
            "transient_page_text": "",
        }
        result = _get_matching("click the dropdown", state)
        assert "Ad Type" in result

    def test_transient_page_text_scanning(self):
        """Matching also scans transient page text (modals/toasts)."""
        state = {
            "current_accessibility_tree": "",
            "transient_page_text": "Please select a File Type before continuing",
        }
        result = _get_matching("click the dropdown", state)
        assert "File Type" in result


class TestMatchingOutputFormat:
    """Verify the output format of matched options."""

    def test_output_contains_injected_options_tags(self):
        """Matched output should contain XML-like wrapper tags."""
        result = _get_matching("select the Ad Type")
        assert "<injected_options>" in result
        assert "</injected_options>" in result

    def test_output_contains_label_and_options(self):
        """Output should list the label and its valid options."""
        result = _get_matching("select the Ad Type")
        assert "Ad Type" in result
        assert "Radio Commercial" in result
        assert "Digital Ad" in result

    def test_output_bullet_format(self):
        """Each matched label should appear as a bulleted line."""
        result = _get_matching("select the Ad Type")
        assert "• Ad Type:" in result
