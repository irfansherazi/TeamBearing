"""
vQA — GitHub Test Source Adapter
===================================
Module: backend/adapters/github_adapter.py

Fetches acceptance criteria from GitHub Issues via the REST API.

Supported identifier formats:
  - ``https://github.com/owner/repo/issues/42``
  - ``owner/repo#42``

AC Extraction
-------------
Extracts acceptance criteria from the issue body using these strategies
(tried in order):

1. **Heading section** — Text under ``## Acceptance Criteria`` heading
2. **Checkbox list** — Lines matching ``- [ ] step text``
3. **Full body fallback** — The entire issue body as raw AC text

Authentication
--------------
  - Public repos: no token needed
  - Private repos: set ``GITHUB_TOKEN`` env var (personal access token)

See Also
--------
  - ``backend/adapters/base.py`` — TestSourceAdapter ABC
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from backend.adapters.base import ACResult, TestSourceAdapter
from backend.config import settings

logger = logging.getLogger(__name__)

# Regex patterns for identifier parsing
_URL_PATTERN = re.compile(r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)")
_SHORTHAND_PATTERN = re.compile(r"^(?P<owner>[^/]+)/(?P<repo>[^/#]+)#(?P<number>\d+)$")

# Regex patterns for AC extraction from issue body
_AC_HEADING_PATTERN = re.compile(
    r"##\s*Acceptance\s+Criteria\s*\n(.*?)(?=\n##\s|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_CHECKBOX_PATTERN = re.compile(
    r"^\s*-\s*\[[ xX]?\]\s*(.+)$",
    re.MULTILINE,
)


class GitHubAdapter(TestSourceAdapter):
    """
    GitHub Issues test source adapter.

    Fetches issue data via the GitHub REST API and extracts
    acceptance criteria from the issue body.

    Attributes
    ----------
    _timeout : int
        HTTP request timeout in seconds.
    """

    _timeout: int = 15

    def _parse_identifier(self, identifier: str) -> tuple[str, str, int]:
        """
        Parse a GitHub issue identifier into (owner, repo, number).

        Parameters
        ----------
        identifier : str
            GitHub issue URL or ``owner/repo#number`` shorthand.

        Returns
        -------
        tuple[str, str, int]
            (owner, repo, issue_number)

        Raises
        ------
        ValueError
            If the identifier format is unrecognised.
        """
        identifier = identifier.strip()

        # Try full URL first
        url_match = _URL_PATTERN.match(identifier)
        if url_match:
            return (
                url_match.group("owner"),
                url_match.group("repo"),
                int(url_match.group("number")),
            )

        # Try shorthand
        short_match = _SHORTHAND_PATTERN.match(identifier)
        if short_match:
            return (
                short_match.group("owner"),
                short_match.group("repo"),
                int(short_match.group("number")),
            )

        raise ValueError(
            f"Invalid GitHub issue identifier: {identifier!r}. "
            f"Expected 'https://github.com/owner/repo/issues/42' "
            f"or 'owner/repo#42'."
        )

    def _extract_ac_from_body(self, body: str) -> str:
        """
        Extract acceptance criteria text from a GitHub issue body.

        Tries three strategies in order:

        1. ``## Acceptance Criteria`` heading section
        2. Checkbox list items (``- [ ] step``)
        3. Full body fallback

        Parameters
        ----------
        body : str
            The raw issue body markdown.

        Returns
        -------
        str
            Extracted AC text.
        """
        if not body:
            return ""

        # Strategy 1: Heading section
        heading_match = _AC_HEADING_PATTERN.search(body)
        if heading_match:
            section = heading_match.group(1).strip()
            if section:
                logger.debug(
                    "GitHubAdapter: extracted AC from heading section (%d chars)",
                    len(section),
                )
                return section

        # Strategy 2: Checkbox list
        checkboxes = _CHECKBOX_PATTERN.findall(body)
        if len(checkboxes) >= 2:  # At least 2 checkboxes = likely AC
            ac_text = "\n".join(f"- {item.strip()}" for item in checkboxes)
            logger.debug(
                "GitHubAdapter: extracted %d checkbox items as AC",
                len(checkboxes),
            )
            return ac_text

        # Strategy 3: Full body
        logger.debug(
            "GitHubAdapter: no structured AC found — using full body (%d chars)",
            len(body),
        )
        return body.strip()

    async def fetch_ac(self, identifier: str) -> ACResult:
        """
        Fetch acceptance criteria from a GitHub issue.

        Parameters
        ----------
        identifier : str
            GitHub issue URL or ``owner/repo#42`` shorthand.

        Returns
        -------
        ACResult
            Structured result with AC text and GitHub metadata.

        Raises
        ------
        ValueError
            If the identifier is invalid.
        RuntimeError
            If the GitHub API request fails.
        """
        owner, repo, number = self._parse_identifier(identifier)
        api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"

        logger.info(
            "GitHubAdapter: fetching %s/%s#%d → %s",
            owner,
            repo,
            number,
            api_url,
        )

        # Build headers
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        token = getattr(settings, "github_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Fetch issue
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(api_url, headers=headers)
                resp.raise_for_status()
                issue_data: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"GitHub issue not found: {owner}/{repo}#{number}. "
                    f"Check the identifier and ensure the repo is accessible."
                ) from e
            if e.response.status_code == 401:
                raise RuntimeError(
                    f"GitHub authentication failed for {owner}/{repo}#{number}. "
                    f"Set GITHUB_TOKEN env var for private repos."
                ) from e
            raise RuntimeError(f"GitHub API error ({e.response.status_code}): {e}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"GitHub API request failed: {e}") from e

        # Extract fields
        title = issue_data.get("title", "")
        body = issue_data.get("body", "") or ""
        labels = [lb.get("name", "") for lb in issue_data.get("labels", [])]
        state = issue_data.get("state", "")

        logger.info(
            "GitHubAdapter: fetched '%s' (state=%s, labels=%s, body=%d chars)",
            title,
            state,
            labels,
            len(body),
        )

        # Extract AC from body
        ac_text = self._extract_ac_from_body(body)

        # Also check comments for AC (some teams post AC in comments)
        if not ac_text or ac_text == body.strip():
            comments_url = issue_data.get("comments_url", "")
            if comments_url and issue_data.get("comments", 0) > 0:
                try:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        resp = await client.get(comments_url, headers=headers)
                        resp.raise_for_status()
                        comments = resp.json()

                    for comment in comments:
                        comment_body = comment.get("body", "")
                        heading_match = _AC_HEADING_PATTERN.search(comment_body)
                        if heading_match:
                            ac_text = heading_match.group(1).strip()
                            logger.info(
                                "GitHubAdapter: found AC in comment by %s",
                                comment.get("user", {}).get("login", "?"),
                            )
                            break
                except Exception as e:
                    logger.warning("GitHubAdapter: failed to fetch comments: %s", e)

        return ACResult(
            ticket_id=f"{owner}/{repo}#{number}",
            summary=title,
            description=body,
            acceptance_criteria=ac_text,
            source_type="github",
            raw_metadata={
                "owner": owner,
                "repo": repo,
                "number": number,
                "labels": labels,
                "state": state,
                "url": issue_data.get("html_url", ""),
            },
        )
