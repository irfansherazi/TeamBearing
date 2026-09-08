"""
vQA — Adapter Factory (Phase 5E)
===================================
Module: backend/adapters/adapter_factory.py

Unified adapter factory that auto-detects the test source from the
identifier format, removing the need for manual ``source_type`` selection.

Detection Rules
---------------
  1. GitHub URL (``https://github.com/...``) or shorthand (``owner/repo#N``)
     → ``GitHubAdapter``
  2. Jira ticket pattern (``[A-Z]{2,10}-\\d+``)
     → ``JiraAdapter``
  3. Multi-line text or no pattern match
     → ``RawTextAdapter``

Usage
-----
    from backend.adapters.adapter_factory import resolve_adapter

    # Auto-detect from identifier
    adapter = resolve_adapter("VC2-8967")           # → JiraAdapter
    adapter = resolve_adapter("owner/repo#42")      # → GitHubAdapter
    adapter = resolve_adapter("Click the button")   # → RawTextAdapter

    # Explicit override
    adapter = resolve_adapter("...", source_type="jira")

See Also
--------
  - ``backend/adapters/base.py``           — TestSourceAdapter ABC
  - ``backend/adapters/jira_adapter.py``   — Jira REST adapter
  - ``backend/adapters/github_adapter.py`` — GitHub REST adapter
  - ``backend/adapters/raw_text_adapter.py`` — raw text passthrough
"""

from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from backend.adapters.base import TestSourceAdapter

logger = logging.getLogger(__name__)

# Detection patterns
_GITHUB_URL_PATTERN = re.compile(r"https?://github\.com/[^/]+/[^/]+/issues/\d+")
_GITHUB_SHORTHAND_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+#\d+$")
_JIRA_TICKET_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")

SourceType = Literal["jira", "github", "raw_text", "auto"]


def detect_source_type(identifier: str) -> SourceType:
    """
    Auto-detect the test source type from the identifier format.

    Parameters
    ----------
    identifier : str
        The raw identifier string from the user.

    Returns
    -------
    SourceType
        Detected source type: ``"github"``, ``"jira"``, or ``"raw_text"``.
    """
    identifier = identifier.strip()

    # GitHub URL
    if _GITHUB_URL_PATTERN.match(identifier):
        return "github"

    # GitHub shorthand (owner/repo#42)
    if _GITHUB_SHORTHAND_PATTERN.match(identifier):
        return "github"

    # Jira ticket (e.g., VC2-8967, QA-123)
    if _JIRA_TICKET_PATTERN.match(identifier):
        return "jira"

    # Default: raw text
    return "raw_text"


def resolve_adapter(
    identifier: str,
    source_type: Optional[SourceType] = None,
) -> TestSourceAdapter:
    """
    Resolve the appropriate adapter for the given identifier.

    Parameters
    ----------
    identifier : str
        Test source identifier (Jira key, GitHub URL, or raw text).
    source_type : SourceType, optional
        Explicit source type override. If ``None`` or ``"auto"``,
        the type is auto-detected from the identifier format.

    Returns
    -------
    TestSourceAdapter
        The appropriate adapter instance.

    Raises
    ------
    ValueError
        If the source type is unknown.
    """
    if not source_type or source_type == "auto":
        source_type = detect_source_type(identifier)

    logger.info(
        "AdapterFactory: resolved '%s' → %s adapter",
        identifier[:50],
        source_type,
    )

    if source_type == "jira":
        from backend.adapters.jira_adapter import JiraAdapter

        return JiraAdapter()

    if source_type == "github":
        from backend.adapters.github_adapter import GitHubAdapter

        return GitHubAdapter()

    if source_type == "raw_text":
        from backend.adapters.raw_text_adapter import RawTextAdapter

        return RawTextAdapter()

    raise ValueError(f"Unknown source type: {source_type!r}. Expected 'jira', 'github', or 'raw_text'.")
