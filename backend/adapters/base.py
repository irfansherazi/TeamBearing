"""
vQA — Test Source Adapter Base
=================================
Module: backend/adapters/base.py

Defines the ``TestSourceAdapter`` abstract base class and the ``ACResult``
dataclass returned by all adapters.

Every test source (Jira, raw text, GitHub, etc.) implements
``TestSourceAdapter.fetch_ac()`` so the engine can retrieve AC text
from any source using the same interface.

See Also
--------
  - ``backend/adapters/jira_adapter.py``     — Jira REST API
  - ``backend/adapters/raw_text_adapter.py`` — raw text passthrough
  - ``backend/adapters/github_adapter.py``   — GitHub issues (skeleton)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ACResult:
    """
    Structured result from a test source adapter.

    Attributes
    ----------
    ticket_id : str
        Source-specific identifier (Jira key, GitHub issue #, or
        auto-generated UUID for raw text).
    summary : str
        One-line summary of the test item.
    description : str
        Full description / body text.
    acceptance_criteria : str
        The raw acceptance criteria text for the AC parser.
    source_type : str
        Adapter type that produced this result (``"jira"``, ``"raw_text"``,
        ``"github"``).
    raw_metadata : dict[str, Any]
        Adapter-specific metadata (e.g., Jira fields, GitHub labels).
        Consumers should not depend on specific keys here.
    """

    ticket_id: str
    summary: str = ""
    description: str = ""
    acceptance_criteria: str = ""
    source_type: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class TestSourceAdapter(ABC):
    """
    Abstract base class for test source adapters.

    Implementations must provide ``fetch_ac()`` which retrieves
    acceptance criteria from a specific test source.
    """

    @abstractmethod
    async def fetch_ac(self, identifier: str) -> ACResult:
        """
        Fetch acceptance criteria from the test source.

        Parameters
        ----------
        identifier : str
            Source-specific identifier.
            - Jira: ticket ID (e.g. ``"VC2-8967"``)
            - Raw text: the AC text itself
            - GitHub: issue URL or ``owner/repo#number``

        Returns
        -------
        ACResult
            Structured result with AC text and metadata.

        Raises
        ------
        ValueError
            If the identifier is invalid or empty.
        RuntimeError
            If the source is unreachable or returns an error.
        """
        ...
