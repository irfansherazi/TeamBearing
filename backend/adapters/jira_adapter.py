"""
vQA — Jira Test Source Adapter
=================================
Module: backend/adapters/jira_adapter.py

Wraps the existing ``backend/jira/client.py`` into the
``TestSourceAdapter`` interface.

This adapter calls the Jira REST API v3 to fetch a ticket's
summary, description, and Acceptance Criteria (``customfield_10031``).

See Also
--------
  - ``backend/jira/client.py``   — the underlying Jira REST client
  - ``backend/adapters/base.py`` — TestSourceAdapter ABC
"""

from __future__ import annotations

import logging

from backend.adapters.base import ACResult, TestSourceAdapter
from backend.jira.client import fetch_ticket_context

logger = logging.getLogger(__name__)


class JiraAdapter(TestSourceAdapter):
    """
    Jira test source adapter.

    Delegates to ``fetch_ticket_context()`` from ``backend.jira.client``
    and wraps the result into an ``ACResult``.
    """

    async def fetch_ac(self, identifier: str) -> ACResult:
        """
        Fetch acceptance criteria from a Jira ticket.

        Parameters
        ----------
        identifier : str
            Jira ticket ID (e.g. ``"VC2-8967"``).

        Returns
        -------
        ACResult
            Populated from the Jira API response.

        Raises
        ------
        ValueError
            If the identifier is empty.
        RuntimeError
            If the Jira API call fails.
        """
        ticket_id = identifier.strip().upper()
        if not ticket_id:
            raise ValueError("JiraAdapter: ticket ID cannot be empty")

        logger.info("JiraAdapter: fetching ticket %s", ticket_id)

        ticket_context = await fetch_ticket_context(ticket_id)

        return ACResult(
            ticket_id=ticket_id,
            summary=ticket_context.get("summary", ""),
            description=ticket_context.get("description", ""),
            acceptance_criteria=ticket_context.get("acceptance_criteria", ""),
            source_type="jira",
            raw_metadata=ticket_context,
        )
