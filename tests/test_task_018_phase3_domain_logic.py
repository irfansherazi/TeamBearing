from backend.engine.ac_quality_gate import score_ac_quality


def test_ac_domain_nouns_not_generic():
    """
    AC-DOMAIN-1: Domain-specific nouns (campaign, talent, toast, voice, file)
    should not be penalized as generic components.
    """
    # These should score 0 for specificity because they are no longer in _GENERIC_COMPONENT_PATTERNS
    # wait, if they are removed, they will score 0, which gives a warning: "No UI component referenced"
    # Let's verify they do NOT trigger the generic component warning specifically.

    # Test with a step containing just the word
    result = score_ac_quality("Select the campaign")

    # Check that there is NO "Generic UI reference detected ('campaign')" warning
    warnings = " ".join(result.warnings)
    assert "Generic UI reference detected ('campaign')" not in warnings

    result2 = score_ac_quality("Add a talent")
    warnings2 = " ".join(result2.warnings)
    assert "Generic UI reference detected ('talent')" not in warnings2

    result3 = score_ac_quality("See the toast")
    warnings3 = " ".join(result3.warnings)
    assert "Generic UI reference detected ('toast')" not in warnings3

    result4 = score_ac_quality("Click the client column")
    # "client column" is specific, but "client" is still in generic
    warnings4 = " ".join(result4.warnings)
    # The warning should be for something else, or if it says "Generic UI reference detected ('client')"
    # Wait, "client column" is in SPECIFIC_COMPONENT_PATTERNS, so it should score 2 and have no generic warning.
    assert "Generic UI reference detected" not in warnings4
