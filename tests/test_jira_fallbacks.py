from unittest.mock import MagicMock, patch

import pytest

from backend.jira.client import fetch_ticket_context


@pytest.mark.anyio
async def test_fetch_ticket_context_fallback_fields():
    """Test that fetch_ticket_context checks fallback custom fields for AC."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    # customfield_10031 is missing, but customfield_10010 has the AC
    mock_response.json.return_value = {
        "fields": {
            "summary": "Test Summary",
            "description": {"type": "doc", "content": []},
            "customfield_10010": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Fallback AC Content"}]}],
            },
        }
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        ctx = await fetch_ticket_context("QA-123-FALLBACK")
        assert ctx["acceptance_criteria"] == "Fallback AC Content"
        assert ctx["summary"] == "Test Summary"


@pytest.mark.anyio
async def test_fetch_ticket_context_priority_fields():
    """Test that customfield_10031 still has priority over others."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "fields": {
            "summary": "Test Summary",
            "description": {"type": "doc", "content": []},
            "customfield_10031": "Primary AC",
            "customfield_10010": "Secondary AC",
        }
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        ctx = await fetch_ticket_context("QA-123-PRIORITY")
        assert ctx["acceptance_criteria"] == "Primary AC"


@pytest.mark.anyio
async def test_fetch_ticket_context_logs_populated_customfields_when_ac_empty(caplog):
    """When configured AC fields are empty, the warning must list the populated
    customfield_* IDs on the ticket so operators can identify the correct field ID
    to add to JIRA_AC_FIELDS. Reproduces the vpromotions QA-358 diagnostic gap."""
    import logging as _logging
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "fields": {
            "summary": "vpromotions ticket",
            "description": {"type": "doc", "content": []},
            # Configured fields are absent/empty
            "customfield_10031": None,
            "customfield_10010": None,
            # But other customfields ARE populated — this is where vpromotions AC likely lives
            "customfield_11234": "vpromotions AC content here",
            "customfield_11500": {"type": "doc", "content": []},
            "customfield_12000": "another populated field",
        }
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        with caplog.at_level(_logging.WARNING, logger="backend.jira.client"):
            await fetch_ticket_context("QA-VPROMOTIONS")

    warnings = [r for r in caplog.records if r.levelno >= _logging.WARNING]
    joined = " | ".join(r.getMessage() for r in warnings)
    assert "empty or unrecognised Acceptance Criteria" in joined
    # The populated customfield IDs must appear so operators can pick the right one
    assert "customfield_11234" in joined
    assert "customfield_12000" in joined
    assert "JIRA_AC_FIELDS" in joined
