
import pytest
from backend.jira.client import _extract_text_from_adf

def test_adf_mark_boundary_word_fusion():
    """
    Reproduce the word fusion bug at ADF mark boundaries.
    """
    adf = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "log in as"},
            {"type": "text", "text": "Account Executive", "marks": [{"type": "strong"}]}
        ]
    }
    
    # Current behavior (buggy): "log in asAccount Executive\n"
    # Desired behavior: "log in as Account Executive\n"
    result = _extract_text_from_adf(adf)
    assert result == "log in as Account Executive\n"

def test_adf_multiple_marks_spacing():
    """
    Test multiple adjacent marks and plain text nodes.
    """
    adf = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "Click"},
            {"type": "text", "text": "Submit", "marks": [{"type": "code"}]},
            {"type": "text", "text": "then"},
            {"type": "text", "text": "Close", "marks": [{"type": "strong"}]}
        ]
    }
    
    result = _extract_text_from_adf(adf)
    assert result == "Click Submit then Close\n"

def test_adf_marks_with_existing_spaces_preserved():
    """
    Ensure we don't add double spaces if spaces already exist.
    """
    adf = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "log in as "},
            {"type": "text", "text": "Account Executive", "marks": [{"type": "strong"}]},
            {"type": "text", "text": " ."}
        ]
    }
    
    result = _extract_text_from_adf(adf)
    # Should NOT be "log in as  Account Executive  ."
    assert result == "log in as Account Executive .\n"
