import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.jira.client import fetch_issue_comments, JiraClientError
from backend.jira.negotiator import JiraACNegotiator
from backend.engine.state import JiraTicketContext
from backend.engine.ac_quality_gate import ACQualityResult

@pytest.mark.asyncio
async def test_fetch_issue_comments_success():
    """Verify that fetch_issue_comments retrieves and processes Jira comments successfully."""
    mock_comments_resp = {
        "comments": [
            {
                "id": "10001",
                "author": {"displayName": "Developer Bob"},
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Please use selector "}, {"type": "text", "text": "#my-btn"}]
                        }
                    ]
                },
                "created": "2026-06-01T12:00:00.000+0000"
            },
            {
                "id": "10002",
                "author": {"displayName": "QA Alice"},
                "body": "Plain text comment here",
                "created": "2026-06-01T12:05:00.000+0000"
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_comments_resp

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        comments = await fetch_issue_comments("QA-185")
        
        assert len(comments) == 2
        assert comments[0]["id"] == "10001"
        assert comments[0]["author"] == "Developer Bob"
        assert comments[0]["body"] == "Please use selector #my-btn"
        assert comments[1]["body"] == "Plain text comment here"


@pytest.mark.asyncio
async def test_fetch_issue_comments_error():
    """Verify that fetch_issue_comments handles API errors gracefully by raising JiraClientError."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        with pytest.raises(JiraClientError) as exc_info:
            await fetch_issue_comments("QA-185")
        assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_negotiator_fetches_and_filters_high_signal_comments():
    """Verify that negotiator filters comments and appends high-signal ones to the description."""
    mock_ticket_ctx = {
        "ticket_id": "QA-185",
        "summary": "Fix validation",
        "description": "Initial description text.",
        "acceptance_criteria": "Given I am logged in"
    }

    mock_comments = [
        {
            "id": "1",
            "author": "Alice",
            "body": "This is low signal comment"
        },
        {
            "id": "2",
            "author": "Bob",
            "body": "Use selector #my-dropdown-panel to check popup"
        }
    ]

    negotiator = JiraACNegotiator("QA-185", "run-123")

    with patch("backend.jira.negotiator.fetch_ticket_context", new_callable=AsyncMock, return_value=mock_ticket_ctx), \
         patch("backend.jira.negotiator.fetch_issue_comments", new_callable=AsyncMock, return_value=mock_comments), \
         patch("backend.jira.negotiator.post_jira_comment", new_callable=AsyncMock) as mock_post:
        
        ticket_ctx, quality_result = await negotiator.fetch_and_gate_ac()
        
        assert ticket_ctx is not None
        # Should have appended only the high-signal comment
        assert "Initial description text." in ticket_ctx["description"]
        assert "Use selector #my-dropdown-panel to check popup" in ticket_ctx["description"]
        assert "This is low signal comment" not in ticket_ctx["description"]


@pytest.mark.asyncio
async def test_negotiator_prevents_duplicate_test_plans():
    """Verify that negotiator checks comments and does not post a duplicate Proposed Test Plan."""
    mock_ticket_ctx = {
        "ticket_id": "QA-185",
        "summary": "Fix validation",
        "description": "Initial description.",
        "acceptance_criteria": "Given I am logged in"
    }

    quality_result = ACQualityResult(
        raw_text="Given I am logged in",
        quality_grade="good",
        overall_score=8,
        warnings=[]
    )

    # 1. Existing comments contains Proposed Test Plan
    mock_comments = [
        {
            "id": "1",
            "author": "vQA",
            "body": "vQA Proposed Test Plan:\n\n```gherkin\nGiven user is logged in\n```"
        }
    ]

    negotiator = JiraACNegotiator("QA-185", "run-123")

    with patch("backend.jira.negotiator.fetch_issue_comments", new_callable=AsyncMock, return_value=mock_comments), \
         patch("backend.jira.negotiator.post_jira_comment", new_callable=AsyncMock) as mock_post, \
         patch("backend.jira.negotiator._stage_1_normalize", new_callable=AsyncMock, return_value="Given user is logged in"):
        
        await negotiator.propose_test_plan(mock_ticket_ctx, quality_result)
        # Should NOT call post_jira_comment since the plan already exists in comments
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_negotiator_posts_test_plan_if_no_duplicate():
    """Verify that negotiator posts a Proposed Test Plan if one doesn't exist yet."""
    mock_ticket_ctx = {
        "ticket_id": "QA-185",
        "summary": "Fix validation",
        "description": "Initial description.",
        "acceptance_criteria": "Given I am logged in"
    }

    quality_result = ACQualityResult(
        raw_text="Given I am logged in",
        quality_grade="good",
        overall_score=8,
        warnings=[]
    )

    mock_comments = [
        {
            "id": "1",
            "author": "Alice",
            "body": "Normal discussion comment"
        }
    ]

    negotiator = JiraACNegotiator("QA-185", "run-123")

    with patch("backend.jira.negotiator.fetch_issue_comments", new_callable=AsyncMock, return_value=mock_comments), \
         patch("backend.jira.negotiator.post_jira_comment", new_callable=AsyncMock) as mock_post, \
         patch("backend.jira.negotiator._stage_1_normalize", new_callable=AsyncMock, return_value="Given user is logged in"):
        
        await negotiator.propose_test_plan(mock_ticket_ctx, quality_result)
        # Should call post_jira_comment since the plan does NOT exist
        mock_post.assert_called_once()
        assert "vQA Proposed Test Plan:" in mock_post.call_args[0][1]


@pytest.mark.asyncio
async def test_negotiator_sync_requires_confirmation_gate():
    """Verify that sync_modified_ac respects requires_confirmation flag and gates sync in HITL."""
    negotiator = JiraACNegotiator("QA-185", "run-123")

    # If requires_confirmation is True, the negotiator should gate updating/syncing or raise an exception/gate it.
    # Wait, how does the plan describe the HITL gate:
    # "AC Sync Gate: Add a requires_confirmation: bool flag to the sync_modified_ac flow in negotiator.py.
    # In HITL mode, this will pause for user approval before pushing updates to Jira."
    # Let's verify that if requires_confirmation=True, it behaves differently (e.g. returns False or triggers/asks for confirmation).
    # Wait, the method signature:
    # async def sync_modified_ac(self, new_ac_text: str, requires_confirmation: bool = False) -> bool
    # Let's test that if requires_confirmation is True, it returns False or requires confirmation before syncing.
    # Wait! Let's mock or implement a mechanism where if requires_confirmation is True, it registers the action/updates but returns False or returns a specific state.
    # Let's check how the plan defines it: "Add requires_confirmation: bool = False to sync_modified_ac in negotiator.py. If active, pause for user confirmation."
    # How does pause for user confirmation work in our async/HITL environment?
    # In a backend API, it usually raises an exception, triggers a takeover/HITL block, or returns False/raises an exception.
    # Let's see: if requires_confirmation is True, maybe we return False and don't call update_ticket_ac (or raise ValueError/HITL gate)?
    # Wait, let's look at negotiator.py again. In negotiator.py, it's called by an API or LangGraph node.
    # In an interactive app, if a flag `requires_confirmation` is set and it's running in HITL, we might raise an error or return a status indicating "confirmation_required".
    # Let's see what is requested exactly:
    # "AC Sync Gate: Add a requires_confirmation: bool flag to the sync_modified_ac flow in negotiator.py.
    # In HITL mode, this will pause for user approval before pushing updates to Jira."
    # Let's implement sync_modified_ac as:
    # async def sync_modified_ac(self, new_ac_text: str, requires_confirmation: bool = False) -> bool:
    #     if requires_confirmation:
    #         logger.info("Sync requires confirmation. Pausing for human in the loop approval.")
    #         # Returns False to indicate it didn't push yet, or we could handle it via a specific return.
    #         # Let's check if the plan has more details.
    #         return False
    # If requires_confirmation=False, it executes.
    
    with patch("backend.jira.negotiator.update_ticket_ac", new_callable=AsyncMock, return_value=True) as mock_update, \
         patch("backend.jira.negotiator.post_jira_comment", new_callable=AsyncMock) as mock_post:
        
        # When requires_confirmation = True, should not call update
        success = await negotiator.sync_modified_ac("new AC text", requires_confirmation=True)
        assert success is False
        mock_update.assert_not_called()

        # When requires_confirmation = False, should call update
        success = await negotiator.sync_modified_ac("new AC text", requires_confirmation=False)
        assert success is True
        mock_update.assert_called_once_with("QA-185", "new AC text")
