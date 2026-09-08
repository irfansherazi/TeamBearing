import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.jira.client import _extract_text_from_adf
from backend.engine.prompts import BDD_NORMALIZER_PROMPT
from backend.engine.ac_parser import _stage_1_normalize


def test_single_row_table_extraction():
    """
    Verify that an ADF table with a single row is parsed gracefully.
    """
    adf = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Cell 1"}]}]
                    },
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Cell 2"}]}]
                    }
                ]
            }
        ]
    }
    result = _extract_text_from_adf(adf)
    expected = (
        "[AC TABLE: 1 rows]\n"
        "1. | Cell 1 | Cell 2 |\n"
    )
    assert result == expected


def test_multi_row_table_extraction():
    """
    Verify that an ADF table with multiple rows is parsed gracefully.
    """
    adf = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableHeader",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Header A"}]}]
                    },
                    {
                        "type": "tableHeader",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Header B"}]}]
                    }
                ]
            },
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Row 1 Col A"}]}]
                    },
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Row 1 Col B"}]}]
                    }
                ]
            },
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Row 2 Col A"}]}]
                    },
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Row 2 Col B"}]}]
                    }
                ]
            }
        ]
    }
    result = _extract_text_from_adf(adf)
    expected = (
        "[AC TABLE: 3 rows]\n"
        "1. | Header A | Header B |\n"
        "2. | Row 1 Col A | Row 1 Col B |\n"
        "3. | Row 2 Col A | Row 2 Col B |\n"
    )
    assert result == expected


def test_nested_and_empty_cells_extraction():
    """
    Verify that tables with nested structures and empty/missing cells are handled gracefully.
    """
    adf = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": ""}]}]
                    },
                    {
                        "type": "tableCell",
                        "content": []
                    },
                    {
                        "type": "tableCell",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Nested part 1"},
                                    {"type": "hardBreak"},
                                    {"type": "text", "text": "Nested part 2"}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    result = _extract_text_from_adf(adf)
    expected = (
        "[AC TABLE: 1 rows]\n"
        "1. |  |  | Nested part 1\nNested part 2 |\n"
    )
    assert result == expected


@pytest.mark.anyio
async def test_stage_1_normalize_prompt_integration():
    """
    Verify that BDD Normalizer prompt includes the custom AC table rule,
    and that `_stage_1_normalize` correctly formats the system message with it.
    """
    # Verify BDD_NORMALIZER_PROMPT has rule 3 targeting "[AC TABLE: N rows]"
    assert "[AC TABLE: N rows]" in BDD_NORMALIZER_PROMPT
    assert "generate separate Given/When/Then scenarios" in BDD_NORMALIZER_PROMPT

    mock_response = MagicMock()
    mock_response.content = "Given some state\nWhen action happens\nThen outcome occurs"
    mock_response.response_metadata = {"usage": {"input_tokens": 10, "output_tokens": 10}}

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    raw_ac = "[AC TABLE: 2 rows]\n1. | Role | Action |\n2. | User | Click |"
    summary = "Table Test Ticket"
    description = "Test Description"
    run_id = "test-099"

    with patch("backend.engine.ac_parser._get_parser_llm", return_value=mock_llm):
        result = await _stage_1_normalize(
            raw_ac=raw_ac,
            summary=summary,
            description=description,
            run_id=run_id
        )

        assert result == "Given some state\nWhen action happens\nThen outcome occurs"
        mock_llm.ainvoke.assert_called_once()
        system_msg = mock_llm.ainvoke.call_args[0][0][0]
        assert "[AC TABLE: 2 rows]" in system_msg.content
        assert "generate separate Given/When/Then scenarios for each row/role" in system_msg.content
