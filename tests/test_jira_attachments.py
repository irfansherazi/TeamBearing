from unittest.mock import MagicMock, patch

import pytest

from backend.engine.state import JiraTicketContext
from backend.jira.client import JiraClientError, download_attachment, fetch_ticket_context


@pytest.mark.anyio
async def test_jira_ticket_context_schema_with_attachments():
    """Verify that JiraTicketContext can hold attachment metadata."""
    ctx = JiraTicketContext(
        ticket_id="QA-123",
        summary="Test",
        description="Desc",
        acceptance_criteria="AC",
        acceptance_criteria_steps=[],
        attachments=[
            {
                "id": "1001",
                "filename": "screenshot.png",
                "mimeType": "image/png",
                "size": 1024,
                "created": "2026-05-20T10:00:00.000+0000",
            }
        ],
    )
    assert len(ctx["attachments"]) == 1
    assert ctx["attachments"][0]["filename"] == "screenshot.png"


@pytest.mark.anyio
async def test_fetch_ticket_context_with_attachments():
    """Verify fetch_ticket_context extracts attachment metadata from Jira response."""
    mock_response = {
        "id": "10001",
        "key": "QA-123",
        "fields": {
            "summary": "Test Ticket",
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]}],
            },
            "customfield_10031": "AC steps",
            "attachment": [
                {
                    "id": "att-1",
                    "filename": "image.png",
                    "mimeType": "image/png",
                    "size": 5000,
                    "created": "2026-05-20T12:00:00.000+0000",
                },
                {
                    "id": "att-2",
                    "filename": "log.txt",
                    "mimeType": "text/plain",
                    "size": 100,
                    "created": "2026-05-20T12:01:00.000+0000",
                },
            ],
        },
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: mock_response)

        ctx = await fetch_ticket_context("QA-123")

        assert "attachments" in ctx
        assert len(ctx["attachments"]) == 2
        assert ctx["attachments"][0]["id"] == "att-1"
        assert ctx["attachments"][1]["filename"] == "log.txt"

        # Verify correct fields were requested
        args, kwargs = mock_get.call_args
        params = kwargs.get("params", {})
        assert "attachment" in params.get("fields", "")


@pytest.mark.anyio
async def test_download_attachment_success():
    """Verify download_attachment returns binary content on success."""
    mock_content = b"fake-image-binary-data"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, content=mock_content)

        content = await download_attachment("att-1")
        assert content == mock_content

        # Verify URL
        args, kwargs = mock_get.call_args
        url = args[0]
        assert "attachment/content/att-1" in url


@pytest.mark.anyio
async def test_download_attachment_error():
    """Verify download_attachment raises JiraClientError on failure."""
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, text="Not Found")

        with pytest.raises(JiraClientError) as excinfo:
            await download_attachment("invalid-id")

        assert excinfo.value.status_code == 404
        assert "not found" in excinfo.value.detail.lower()


@pytest.mark.anyio
async def test_download_attachment_follows_redirects():
    """Jira /attachment/content/<id> returns 303 → S3. Client must follow it."""
    with patch("backend.jira.client.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        # Coerce __aenter__/__aexit__ to be awaitables
        async def _aenter(self=None):
            return mock_client
        async def _aexit(self=None, *a, **kw):
            return None
        mock_client_cls.return_value.__aenter__ = _aenter
        mock_client_cls.return_value.__aexit__ = _aexit

        async def _get(url, headers=None):
            return MagicMock(status_code=200, content=b"post-redirect-body")
        mock_client.get = _get

        await download_attachment("att-follow-1")

        # Assert AsyncClient was constructed with follow_redirects=True
        _, kwargs = mock_client_cls.call_args
        assert kwargs.get("follow_redirects") is True, (
            f"httpx.AsyncClient must be constructed with follow_redirects=True "
            f"to fetch attachments through Jira's 303→S3 redirect. Got kwargs={kwargs}"
        )
