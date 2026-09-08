
import pytest
from backend.jira.client import _extract_text_from_adf

def test_adf_table_row_separator():
    """
    Test that table cells are separated by a pipe.
    """
    adf = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Header 1"}]}]
                    },
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Header 2"}]}]
                    }
                ]
            },
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Value 1"}]}]
                    },
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Value 2"}]}]
                    }
                ]
            }
        ]
    }
    
    result = _extract_text_from_adf(adf)
    
    # Expected output should have the [AC TABLE: 2 rows] sentinel and numbered, piped rows
    expected = (
        "[AC TABLE: 2 rows]\n"
        "1. | Header 1 | Header 2 |\n"
        "2. | Value 1 | Value 2 |\n"
    )
    
    assert result == expected
