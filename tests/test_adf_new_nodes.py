from backend.jira.client import _extract_text_from_adf


def test_extract_text_from_media_group():
    """Test that mediaGroup nodes are parsed correctly."""
    adf = {
        "type": "mediaGroup",
        "content": [
            {"type": "media", "attrs": {"filename": "img1.png"}},
            {"type": "media", "attrs": {"filename": "img2.png"}},
        ],
    }
    result = _extract_text_from_adf(adf)
    assert "[media: img1.png]" in result
    assert "[media: img2.png]" in result


def test_extract_text_from_application_card():
    """Test that applicationCard nodes are parsed correctly."""
    adf = {
        "type": "applicationCard",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Embedded Card Content"}]}],
    }
    result = _extract_text_from_adf(adf)
    assert "Embedded Card Content" in result
