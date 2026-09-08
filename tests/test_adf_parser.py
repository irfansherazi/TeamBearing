"""
TASK-015 Phase 1: Bug 4 — Jira ADF Parser Fix
==============================================
Tests for the ADF-to-text converter in ``backend/jira/client.py``.

The ``_extract_text_from_adf()`` function currently crashes or silently
drops content when encountering ``inlineCard`` or ``mediaSingle`` ADF
node types.  These tests verify the fix.

Coverage:
  AC-HAPPY-9:   inlineCard ADF nodes → ``[link text](url)``
  AC-HAPPY-10:  mediaSingle ADF nodes → ``[media: filename]``
  AC-ERROR-3:   Unknown ADF node types → ``[unsupported: nodeType]``
  AC-REGRESS-4: Standard ADF parsing (paragraph, text, bulletList,
                orderedList, heading) still works correctly
"""

from backend.jira.client import _extract_text_from_adf

# ---------------------------------------------------------------------------
# AC-HAPPY-9: inlineCard ADF nodes → markdown link
# ---------------------------------------------------------------------------


class TestInlineCardParsing:
    """AC-HAPPY-9: inlineCard nodes should render as [link text](url)."""

    def test_inline_card_with_title_and_url(self):
        """inlineCard with both title and url renders as markdown link."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "See "},
                        {
                            "type": "inlineCard",
                            "attrs": {
                                "url": "https://jira.example.com/browse/VC2-100",
                                "title": "VC2-100",
                            },
                        },
                        {"type": "text", "text": " for details"},
                    ],
                }
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "[VC2-100](https://jira.example.com/browse/VC2-100)" in result
        assert "See" in result
        assert "for details" in result

    def test_inline_card_url_only_no_title(self):
        """inlineCard with url but no title uses url as display text."""
        adf = {
            "type": "inlineCard",
            "attrs": {
                "url": "https://confluence.example.com/page/12345",
            },
        }
        result = _extract_text_from_adf(adf)
        assert "[https://confluence.example.com/page/12345]" in result
        assert "(https://confluence.example.com/page/12345)" in result

    def test_inline_card_no_attrs(self):
        """inlineCard with missing attrs should not crash."""
        adf = {
            "type": "inlineCard",
        }
        result = _extract_text_from_adf(adf)
        # Should produce some fallback text, not crash
        assert isinstance(result, str)

    def test_inline_card_nested_in_paragraph(self):
        """inlineCard embedded inside a paragraph renders inline."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Related: "},
                        {
                            "type": "inlineCard",
                            "attrs": {
                                "url": "https://jira.example.com/browse/QA-500",
                                "title": "QA-500 Login Bug",
                            },
                        },
                    ],
                }
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "Related:" in result
        assert "[QA-500 Login Bug](https://jira.example.com/browse/QA-500)" in result


# ---------------------------------------------------------------------------
# AC-HAPPY-10: mediaSingle ADF nodes → media placeholder
# ---------------------------------------------------------------------------


class TestMediaSingleParsing:
    """AC-HAPPY-10: mediaSingle nodes should render as [media: filename]."""

    def test_media_single_with_filename(self):
        """mediaSingle containing a media node with filename attribute."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "mediaSingle",
                    "attrs": {"layout": "center"},
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "id": "abc-123",
                                "type": "file",
                                "collection": "contentId-12345",
                                "filename": "screenshot.png",
                            },
                        }
                    ],
                }
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "[media: screenshot.png]" in result

    def test_media_single_without_filename(self):
        """mediaSingle with media node missing filename uses id fallback."""
        adf = {
            "type": "mediaSingle",
            "content": [
                {
                    "type": "media",
                    "attrs": {
                        "id": "uuid-456",
                        "type": "file",
                        "collection": "contentId-99999",
                    },
                }
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "[media:" in result
        # Should use the id as fallback when filename is missing
        assert "uuid-456" in result

    def test_media_single_empty_content(self):
        """mediaSingle with no content array should not crash."""
        adf = {
            "type": "mediaSingle",
            "attrs": {"layout": "center"},
        }
        result = _extract_text_from_adf(adf)
        assert isinstance(result, str)

    def test_media_node_standalone(self):
        """media node without mediaSingle wrapper still renders."""
        adf = {
            "type": "media",
            "attrs": {
                "id": "standalone-media",
                "type": "file",
                "filename": "video.mp4",
            },
        }
        result = _extract_text_from_adf(adf)
        assert "[media: video.mp4]" in result


# ---------------------------------------------------------------------------
# AC-ERROR-3: Unknown ADF node types → graceful fallback
# ---------------------------------------------------------------------------


class TestUnknownNodeTypeFallback:
    """AC-ERROR-3: Unknown ADF node types should not crash."""

    def test_unknown_node_type_renders_fallback(self):
        """Unknown node type renders as [unsupported: nodeType]."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Before "},
                        {"type": "mysteryWidget", "attrs": {"data": "foo"}},
                        {"type": "text", "text": " After"},
                    ],
                }
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "[unsupported: mysteryWidget]" in result
        assert "Before" in result
        assert "After" in result

    def test_unknown_node_with_children_extracts_text(self):
        """Unknown node with text children extracts child text too."""
        adf = {
            "type": "customPanel",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Panel content"},
                    ],
                }
            ],
        }
        result = _extract_text_from_adf(adf)
        # Should still extract text from children
        assert "Panel content" in result

    def test_unknown_leaf_node_no_crash(self):
        """Unknown leaf node (no content, no text) doesn't crash."""
        adf = {
            "type": "emoji",
            "attrs": {"shortName": ":thumbsup:"},
        }
        result = _extract_text_from_adf(adf)
        assert isinstance(result, str)
        assert "[unsupported: emoji]" in result


# ---------------------------------------------------------------------------
# AC-REGRESS-4: Standard ADF parsing regression
# ---------------------------------------------------------------------------


class TestStandardADFRegression:
    """AC-REGRESS-4: Standard ADF node types still parse correctly."""

    def test_paragraph_text(self):
        """Standard paragraph with text content."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Hello world"}],
                }
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "Hello world" in result

    def test_heading(self):
        """Heading node renders with text followed by newline."""
        adf = {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [
                {"type": "text", "text": "Section Title"},
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "Section Title" in result

    def test_bullet_list(self):
        """Bullet list renders with - prefix."""
        adf = {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Item one"},
                            ],
                        }
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Item two"},
                            ],
                        }
                    ],
                },
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "- Item one" in result
        assert "- Item two" in result

    def test_ordered_list(self):
        """Ordered list renders with numbers."""
        adf = {
            "type": "orderedList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "First"},
                            ],
                        }
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Second"},
                            ],
                        }
                    ],
                },
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "1. First" in result
        assert "2. Second" in result

    def test_hard_break(self):
        """hardBreak renders as newline."""
        adf = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Line 1"},
                {"type": "hardBreak"},
                {"type": "text", "text": "Line 2"},
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 1\nLine 2" in result

    def test_code_block(self):
        """Code block wraps content in triple backticks."""
        adf = {
            "type": "codeBlock",
            "content": [
                {"type": "text", "text": "const x = 1;"},
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "```" in result
        assert "const x = 1;" in result

    def test_none_input(self):
        """None input returns empty string."""
        assert _extract_text_from_adf(None) == ""

    def test_plain_string_input(self):
        """Plain string input returned as-is."""
        assert _extract_text_from_adf("plain text") == "plain text"

    def test_list_input(self):
        """List input concatenates results."""
        nodes = [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "World"},
        ]
        result = _extract_text_from_adf(nodes)
        assert result == "Hello World"

    def test_complex_adf_document(self):
        """Full complex ADF document with multiple node types."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [
                        {"type": "text", "text": "Test Plan"},
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Given I am logged in"},
                    ],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Navigate to Orders"},
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Click New Request"},
                                    ],
                                }
                            ],
                        },
                    ],
                },
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "Test Plan" in result
        assert "Given I am logged in" in result
        assert "- Navigate to Orders" in result
        assert "- Click New Request" in result


# ---------------------------------------------------------------------------
# Integration: inlineCard + mediaSingle mixed with standard nodes
# ---------------------------------------------------------------------------


class TestMixedADFDocument:
    """Integration test: document mixing standard and new node types."""

    def test_document_with_inline_cards_and_media(self):
        """Full document with inlineCard and mediaSingle mixed in."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Refer to "},
                        {
                            "type": "inlineCard",
                            "attrs": {
                                "url": "https://jira.example.com/browse/VC2-200",
                                "title": "VC2-200",
                            },
                        },
                        {"type": "text", "text": " for the design spec."},
                    ],
                },
                {
                    "type": "mediaSingle",
                    "attrs": {"layout": "center"},
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "id": "media-uuid",
                                "type": "file",
                                "collection": "col-1",
                                "filename": "mockup.png",
                            },
                        }
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Acceptance Criteria:"},
                    ],
                },
                {
                    "type": "orderedList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Login as producer"},
                                    ],
                                }
                            ],
                        },
                    ],
                },
            ],
        }
        result = _extract_text_from_adf(adf)
        assert "Refer to" in result
        assert "[VC2-200](https://jira.example.com/browse/VC2-200)" in result
        assert "for the design spec." in result
        assert "[media: mockup.png]" in result
        assert "Acceptance Criteria:" in result
        assert "1. Login as producer" in result
