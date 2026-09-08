"""
vQA — Raw Text Test Source Adapter
=====================================
Module: backend/adapters/raw_text_adapter.py

Passes raw acceptance criteria text directly into the pipeline
without any external API call.

This adapter supports non-Jira users or scenarios where AC text
is pasted manually into the vQA UI.

See Also
--------
  - ``backend/adapters/base.py`` — TestSourceAdapter ABC
"""

from __future__ import annotations

import logging
import uuid

from backend.adapters.base import ACResult, TestSourceAdapter

logger = logging.getLogger(__name__)


class RawTextAdapter(TestSourceAdapter):
    """
    Raw text test source adapter.

    Wraps plain AC text into an ``ACResult`` with a generated
    ticket ID.  No external API calls.
    """

    async def fetch_ac(self, identifier: str) -> ACResult:
        """
        Wrap raw AC text into an ACResult.

        Parameters
        ----------
        identifier : str
            The raw acceptance criteria text.

        Returns
        -------
        ACResult
            Populated with the raw text as acceptance_criteria.

        Raises
        ------
        ValueError
            If the text is empty.
        """
        text = identifier.strip()
        if not text:
            raise ValueError("RawTextAdapter: AC text cannot be empty")

        # Generate a synthetic ticket ID for traceability
        synthetic_id = f"RAW-{uuid.uuid4().hex[:8].upper()}"

        logger.info(
            "RawTextAdapter: wrapping %d chars of raw AC text as %s",
            len(text),
            synthetic_id,
        )

        # Use the first line as the summary
        lines = text.split("\n")
        summary = lines[0][:120] if lines else "Raw AC Test"

        return ACResult(
            ticket_id=synthetic_id,
            summary=summary,
            description="",
            acceptance_criteria=text,
            source_type="raw_text",
            raw_metadata={"original_text_length": len(text)},
        )
