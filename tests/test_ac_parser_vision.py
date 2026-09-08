from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.ac_parser import ac_parser_node
from backend.engine.state import make_initial_state


@pytest.mark.anyio
async def test_ac_parser_calls_vision_analyzer():
    """Verify ac_parser_node calls VisionAnalyzer when attachments are present."""
    state = make_initial_state(
        run_id="test-run", jira_ticket_id="QA-123", role="admin", target_url="http://test.com", mode="headless"
    )

    # Add attachments to state
    state["jira_ticket"]["attachments"] = [
        {"id": "att-1", "filename": "screenshot.png", "mimeType": "image/png", "size": 1024}
    ]
    state["jira_ticket"]["acceptance_criteria"] = "Click the button"
    state["jira_ticket"]["summary"] = "Test"

    # Mock download and vision analysis
    with (
        patch("backend.engine.ac_parser.download_attachment", new_callable=AsyncMock) as mock_download,
        patch("backend.engine.ac_parser.VisionAnalyzer") as mock_vision_cls,
    ):
        mock_vision_instance = MagicMock()
        mock_vision_instance.analyze_image = AsyncMock(return_value="Visual context: Blue button.")
        mock_vision_cls.return_value = mock_vision_instance

        mock_download.return_value = b"fake-bytes"

        # Mock Stage 1 and 2 to avoid full LLM calls
        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_stage1,
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_stage2,
        ):
            mock_stage1.return_value = "BDD text"
            mock_stage2.return_value = MagicMock(steps=[], test_title="Test", model_dump=lambda: {})

            await ac_parser_node(state)

            # Verify VisionAnalyzer was called
            assert mock_vision_instance.analyze_image.called
            assert mock_download.called

            # Verify Stage 1 was called with visual context
            args, kwargs = mock_stage1.call_args
            assert "visual_context" in kwargs
            assert "Blue button" in kwargs["visual_context"]


@pytest.mark.anyio
async def test_ac_parser_handles_vision_failure():
    """Verify ac_parser_node still proceeds if vision analysis fails."""
    state = make_initial_state(
        run_id="test-run", jira_ticket_id="QA-123", role="admin", target_url="http://test.com", mode="headless"
    )
    state["jira_ticket"]["attachments"] = [{"id": "att-1", "mimeType": "image/png"}]
    state["jira_ticket"]["acceptance_criteria"] = (
        "Given I am on the login page, When I enter credentials and click the login button, Then I should see the dashboard."
    )

    with (
        patch("backend.engine.ac_parser.download_attachment", side_effect=Exception("Download failed")),
        patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_stage1,
        patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_stage2,
    ):
        mock_stage1.return_value = "BDD text"
        mock_stage2.return_value = MagicMock(steps=[], test_title="Test", model_dump=lambda: {})

        # Should not raise exception
        result = await ac_parser_node(state)

        assert "visual_context" in result
        assert result["visual_context"] == ""
        assert mock_stage1.called


@pytest.mark.anyio
async def test_stage_1_normalize_prompt_formatting():
    """Verify _stage_1_normalize formats the prompt with visual context."""
    from backend.engine.ac_parser import _stage_1_normalize

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="BDD Output")

    with patch("backend.engine.ac_parser._get_parser_llm", return_value=mock_llm):
        await _stage_1_normalize(
            raw_ac="AC", summary="Title", description="Desc", run_id="run-1", visual_context="FACT: The button is red."
        )

        args, kwargs = mock_llm.ainvoke.call_args
        system_prompt = args[0][0].content

        assert "FACT: The button is red." in system_prompt
        assert "Acceptance Criteria:" in system_prompt
