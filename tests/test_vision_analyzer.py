from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from backend.engine.vision_analyzer import VisionAnalyzer


@pytest.mark.anyio
async def test_vision_analyzer_analyze_image_success():
    """Verify VisionAnalyzer returns LLM summary on success."""
    analyzer = VisionAnalyzer()

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="Visual Fact: Blue button labeled 'Submit'.")
    analyzer.llm = mock_llm

    summary = await analyzer.analyze_image(
        image_bytes=b"fake-image", mime_type="image/png", ac_text="Click the primary button."
    )

    assert "Blue button labeled 'Submit'" in summary
    assert mock_llm.ainvoke.called

    # Verify content structure
    args, kwargs = mock_llm.ainvoke.call_args
    messages = args[0]
    content = messages[0].content

    assert content[0]["image"]["format"] == "png"
    assert content[0]["image"]["source"]["bytes"] == b"fake-image"
    assert "Click the primary button" in content[1]["text"]


@pytest.mark.anyio
async def test_vision_analyzer_unsupported_mime_type():
    """Verify VisionAnalyzer rejects unsupported mime types."""
    analyzer = VisionAnalyzer()

    summary = await analyzer.analyze_image(image_bytes=b"fake-pdf", mime_type="application/pdf", ac_text="AC")

    assert summary == ""


@pytest.mark.anyio
async def test_vision_analyzer_error_handling():
    """Verify VisionAnalyzer handles LLM failures gracefully."""
    analyzer = VisionAnalyzer()

    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = Exception("Bedrock Timeout")
    analyzer.llm = mock_llm

    summary = await analyzer.analyze_image(image_bytes=b"fake-image", mime_type="image/jpeg", ac_text="AC")

    assert summary == ""
