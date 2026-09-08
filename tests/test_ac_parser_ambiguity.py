import pytest
from backend.engine.ac_parser import _detect_step_ambiguity

def test_detect_step_ambiguity_vague():
    """Verify that vague goals are flagged."""
    bdd_text = "Then verify the table sorts correctly"
    ambiguities = _detect_step_ambiguity(bdd_text)
    assert len(ambiguities) > 0
    assert any("vague" in a.lower() or "ground" in a.lower() for a in ambiguities)

def test_detect_step_ambiguity_specific():
    """Verify that specific goals are NOT flagged."""
    bdd_text = "Then verify the 'Client' column is sorted in 'ascending' order"
    ambiguities = _detect_step_ambiguity(bdd_text)
    assert len(ambiguities) == 0

def test_detect_step_ambiguity_no_subject():
    """Verify that goals without a clear subject are flagged."""
    bdd_text = "When click the button" # Which button?
    ambiguities = _detect_step_ambiguity(bdd_text)
    assert len(ambiguities) > 0
