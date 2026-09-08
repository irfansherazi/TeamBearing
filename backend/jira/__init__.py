"""
vQA Jira — Jira REST API Client Package
========================================

This package contains the Jira REST API v3 integration.  vQA
is a Jira-driven agent: the Acceptance Criteria field
(``customfield_10031``) is the sole source of test requirements.

Modules
-------
client.py
    Async HTTP client that fetches ticket data, parses Atlassian
    Document Format (ADF) to plain text, and returns a
    ``JiraTicketContext`` ready for the LangGraph state.

    Key functions:
    - ``fetch_ticket_context(ticket_id)`` — main fetch + parse
    - ``validate_jira_connectivity()``    — health check endpoint
"""
