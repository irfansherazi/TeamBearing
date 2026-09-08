# fix-production-jira-ticket-retrieval-issue: Fix Production Jira Ticket Retrieval Issue

**Complexity**: Level 3
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: Critical
**Branch**: bugfix/fix-production-jira-ticket-retrieval-issue-jira-retrieval
**Worktree**: N/A
**Roadmap**: N/A

---

## Problem Statement

Users reported that after logging in on production, no Jira tickets were being pulled into the application, preventing them from selecting tickets for test execution. 

The investigation revealed that Jira board IDs were hardcoded in the backend client, and silent error suppression masked configuration issues (like Pydantic settings parsing failures from environment variables).

---

## Acceptance Criteria

- [x] AC-HAPPY-1: Jira tickets are successfully fetched and displayed in the `ExecutionPanel` dropdown in production.
- [x] AC-HAPPY-2: The system gracefully handles Jira API errors or timeouts with user-friendly messaging.
- [x] AC-DEBUG-1: Enhanced logging and error propagation implemented to identify failure points.
- [x] AC-REGRESS-1: Jira ticket retrieval continues to work correctly in the development environment.

---

## Implementation Roadmap

### Phase 1: Configuration Updates - COMPLETED
- [x] Added `jira_board_ids` to `backend/config.py`.
- [x] Updated type hints to `list[str] | str` and `list[int] | str` for environment variable list fields to support comma-separated strings without Pydantic JSON failure.
- [x] Implemented a `parse_comma_separated_list` validator to handle hybrid input types.

### Phase 2: Backend Logic Updates - COMPLETED
- [x] Updated `fetch_board_tickets` in `backend/jira/client.py` to use configurable IDs from settings.
- [x] Modified error handling in `fetch_board_tickets` to raise `JiraClientError` instead of returning an empty list, ensuring failures are visible.
- [x] Updated `list_tickets` in `backend/api/routes.py` to catch `JiraClientError` and return a 502 Bad Gateway response with detailed diagnostics.

### Phase 3: Frontend Resilience - COMPLETED
- [x] Updated `frontend/src/components/ExecutionPanel.tsx` to handle 502 responses from the ticket API.
- [x] Added state to display the specific backend error message when ticket retrieval fails.

### Phase 4: Diagnostic Updates - COMPLETED
- [x] Updated `scripts/validate_env.py` to use the correct REST API v3 authentication headers.
- [x] Added a specific check for the Jira Agile API connectivity to verify board access.

---

## Test Strategy

- **Reproduction**: Created a reproduction test case that simulated the hardcoded ID failure and confirmed the silent failure behavior.
- **Unit Tests**:
    - Verified `Settings` validation for comma-separated environment variables.
    - Verified `JiraClientError` propagation from the backend client to the API layer.
- **Integration**:
    - Verified that 502 responses are correctly mapped from backend exceptions.
    - Verified that the frontend displays the error message to the user.
- **Environment Validation**:
    - Ran `scripts/validate_env.py` to confirm connectivity to both Classic and Agile Jira APIs.
