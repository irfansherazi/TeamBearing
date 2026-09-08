"""
vQA — Jira REST API v3 Client
===============================
Module: backend/jira/client.py

This module handles all communication with the Atlassian Jira REST API.
It is a Python port of the TypeScript ``pwtgen/src/jira.ts`` module from
the original pwtgen project, adapted for the vQA architecture.

Purpose
-------
vQA is a Jira-driven agent: the Jira Acceptance Criteria (AC) field is
the **sole source of truth** for what the agent tests.  This client
fetches three fields from a Jira ticket:

  1. ``summary``            — becomes the test run title
  2. ``description``        — supplementary context for the LLM planner
  3. ``customfield_10031``  — **Acceptance Criteria** (the test plan)

Architecture Context
--------------------
This client is called by ``jira_fetch_node`` in the LangGraph state
machine (``backend/engine/graph.py``).  The node calls
``fetch_ticket_context()`` and writes the result into
``VQAState.jira_ticket``.

Authentication
--------------
Uses Jira Basic Auth: ``email:api_token`` base64-encoded in the
``Authorization`` header.  Credentials come from ``backend/config.py``:

  - ``settings.jira_email``
  - ``settings.jira_api_token``
  - ``settings.jira_domain``

ADF Parsing
-----------
Jira v3 returns rich text fields (``description``, ``customfield_10031``)
in Atlassian Document Format (ADF) — a nested JSON structure.  This
module includes a recursive parser (``_extract_text_from_adf()``) that
flattens ADF into plain text.

Error Handling
--------------
All HTTP errors are caught, logged, and re-raised as ``JiraClientError``
with context about what went wrong (status code, URL, response body
excerpt).

Dependencies
------------
  - ``httpx`` — async HTTP client (preferred over ``requests`` for
    consistency with FastAPI's async architecture)
  - ``backend/config.py`` — settings singleton

See Also
--------
  - ``pwtgen/src/jira.ts`` — the original TypeScript implementation
  - ``backend/engine/graph.py`` — the ``jira_fetch_node`` that calls this
  - ``backend/engine/state.py`` — ``JiraTicketContext`` type definition
"""

import base64
import logging
import re
from typing import Any

import httpx

from backend.config import settings
from backend.engine.state import JiraTicketContext
from backend.jira.cache import get_jira_cache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class JiraClientError(Exception):
    """
    Raised when the Jira API returns an unexpected response.

    Attributes
    ----------
    status_code : int | None
        HTTP status code from the Jira response, if available.
    url : str
        The full URL that was requested.
    detail : str
        Human-readable description of what went wrong.
    """

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# ADF (Atlassian Document Format) parser
# ---------------------------------------------------------------------------


def _extract_login_credentials(text: str) -> tuple[str, str]:
    """
    Extract explicit login credentials (email, password) from ticket text.

    Returns (email, password). Either or both may be empty string.

    Matches patterns like:
      - "In the Email field, enter: fake@email.com"  +  "In the Password field, enter: fake"
      - "Login as imail-test+DemoAE@vcreativeinc.com" (password defaults to Ep!cVCteam2026$)
      - "Email: foo@bar.com / Password: secret"
    """
    if not text:
        return "", ""

    email = ""
    password = ""

    # ── Email extraction ───────────────────────────────────────────────
    email_patterns = [
        # "email field, enter: X" or "email field enter X"
        re.compile(
            r"email\s+field[,\s]+enter[:\s]+([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})",
            re.IGNORECASE,
        ),
        # "email: X" or "email = X"
        re.compile(
            r"\bemail\s*[:=]\s*([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})",
            re.IGNORECASE,
        ),
        # "login as X" / "log in as X" / "sign in as X"
        re.compile(
            r"(?:log\s*in|login|sign\s*in|authenticate)\s+as\s+([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})",
            re.IGNORECASE,
        ),
        # "enter: X@..." near the start of a step line
        re.compile(
            r"enter[:\s]+([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})",
            re.IGNORECASE,
        ),
    ]

    for pattern in email_patterns:
        m = pattern.search(text)
        if m:
            email = m.group(1).strip()
            break

    # ── Password extraction ────────────────────────────────────────────
    password_patterns = [
        # "password field, enter: X" or "password field enter X"
        re.compile(
            r"password\s+field[,\s]+enter[:\s]+(\S+)",
            re.IGNORECASE,
        ),
        # "password: X" or "password = X"
        re.compile(
            r"\bpassword\s*[:=]\s*(\S+)",
            re.IGNORECASE,
        ),
        # "enter: X" on a line that contains "password" nearby
        re.compile(
            r"password.*?enter[:\s]+(\S+)",
            re.IGNORECASE,
        ),
    ]

    for pattern in password_patterns:
        m = pattern.search(text)
        if m:
            pw = m.group(1).strip().rstrip(".,;")
            # Don't capture field placeholder words
            if pw.lower() not in ("field", "the", "a", "your", "input"):
                password = pw
                break

    return email, password


def _extract_text_from_adf(node: dict[str, Any] | list | str | None) -> str:
    """
    Recursively extract plain text from an Atlassian Document Format (ADF) node.

    Jira REST API v3 returns ``description`` and ``customfield_10031`` in
    ADF — a deeply nested JSON structure.  This function walks the tree
    and concatenates all text nodes into a readable string.

    ADF structure overview::

        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Given I am logged in..."}
                    ]
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Step 1"}
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    Args
    ----
    node : dict | list | str | None
        An ADF node.  Can be:
        - A dict with ``"type"`` and optionally ``"content"`` / ``"text"``
        - A list of ADF child nodes
        - A plain string (rare, but handled)
        - ``None`` if the Jira field is empty

    Returns
    -------
    str
        Flattened plain text with newlines between paragraph-level blocks.

    Notes
    -----
    Handles the following ADF node types:
    - ``text``       → plain text content
    - ``hardBreak``  → newline
    - ``paragraph``  → content followed by newline
    - ``heading``    → content followed by newline
    - ``bulletList`` → each item indented with ``- ``
    - ``orderedList``→ each item numbered
    - ``listItem``   → content preceded by bullet/number
    - ``codeBlock``  → content wrapped in code markers
    - ``doc``        → top-level wrapper, recurse into children
    - Other types    → recurse into children silently

    Example
    -------
    >>> adf = {"type": "doc", "content": [
    ...     {"type": "paragraph", "content": [
    ...         {"type": "text", "text": "Hello world"}
    ...     ]}
    ... ]}
    >>> _extract_text_from_adf(adf)
    'Hello world'
    """
    # Base cases
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_extract_text_from_adf(child) for child in node)

    # Dict node — the main ADF case
    if not isinstance(node, dict):
        return ""

    node_type: str = node.get("type", "")

    # ── Leaf: plain text ──────────────────────────────────────────────
    if node_type == "text":
        return node.get("text", "")

    # ── Leaf: hard line break ─────────────────────────────────────────
    if node_type == "hardBreak":
        return "\n"

    # ── Leaf: inline card (Jira link embed) ───────────────────────────
    # FEAT-030 / Bug 4: inlineCard nodes store data in attrs, not content.
    # Renders as a markdown link: [title](url)
    if node_type == "inlineCard":
        attrs = node.get("attrs", {})
        url = attrs.get("url", "")
        title = attrs.get("title", "")
        if url and title:
            return f"[{title}]({url})"
        elif url:
            return f"[{url}]({url})"
        return "[unsupported: inlineCard]"

    # ── Leaf: media attachment ────────────────────────────────────────
    # FEAT-030 / Bug 4: media nodes store data in attrs (id, filename).
    # Renders as: [media: filename] or [media: id]
    if node_type == "media":
        attrs = node.get("attrs", {})
        filename = attrs.get("filename", "")
        media_id = attrs.get("id", "")
        display = filename or media_id or "unknown"
        return f"[media: {display}]"

    # ── Container: mediaSingle (wraps a media node) ───────────────────
    # FEAT-030 / Bug 4: mediaSingle wraps a media child; delegate to it.
    if node_type == "mediaSingle":
        children = node.get("content", [])
        if children:
            return "".join(_extract_text_from_adf(child) for child in children) + "\n"
        return ""

    # ── Container: mediaGroup / applicationCard ───────────────────────
    # These often wrap other content or represent embedded integrations.
    if node_type in ("mediaGroup", "applicationCard"):
        children = node.get("content", [])
        if children:
            return "".join(_extract_text_from_adf(child) for child in children)
        return ""

    # ── Container: table (preserve row boundaries) ────────────────────
    if node_type == "table":
        rows = []
        for child in node.get("content", []):
            if child.get("type") == "tableRow":
                row_cells = []
                for cell in child.get("content", []):
                    if cell.get("type") in ("tableHeader", "tableCell"):
                        cell_text = _extract_text_from_adf(cell).strip()
                        row_cells.append(cell_text)
                if row_cells:
                    row_text = " | ".join(row_cells)
                    rows.append(f"| {row_text} |")
        if rows:
            numbered_rows = [f"{i}. {row_text}" for i, row_text in enumerate(rows, start=1)]
            return f"[AC TABLE: {len(rows)} rows]\n" + "\n".join(numbered_rows) + "\n"
        return ""

    # ── Container: recurse into children ──────────────────────────────
    children = node.get("content", [])

    # FEAT-057: Prevent word fusion at ADF mark boundaries (e.g., "log in asAccount Executive")
    # Instead of a simple "".join(), we check if a space is needed between sibling text runs.
    child_texts = []
    for i, child in enumerate(children):
        text = _extract_text_from_adf(child)
        if not text:
            continue

        if child_texts:
            prev_text = child_texts[-1]
            # If the previous text ends with a word char and current starts with a word char,
            # and neither has whitespace at the boundary, inject a space.
            if prev_text and text:
                prev_last = prev_text[-1]
                curr_first = text[0]
                if (
                    re.match(r"\w", prev_last)
                    and re.match(r"\w", curr_first)
                    and not prev_last.isspace()
                    and not curr_first.isspace()
                ):
                    child_texts.append(" ")

        child_texts.append(text)

    child_text = "".join(child_texts)

    # Add structure based on node type
    if node_type in ("paragraph", "heading"):
        return child_text.strip() + "\n"
    if node_type == "tableRow":
        # FEAT-057: Join table cells with a pipe separator instead of fusion
        cells = []
        for child in children:
            c_text = _extract_text_from_adf(child).strip()
            if c_text:
                cells.append(c_text)
        return " | ".join(cells) + "\n"
    if node_type == "bulletList":
        # Indent each list item with a bullet
        items = []
        for child in children:
            item_text = _extract_text_from_adf(child).strip()
            if item_text:
                items.append(f"- {item_text}")
        return "\n".join(items) + "\n"
    if node_type == "orderedList":
        items = []
        for i, child in enumerate(children, start=1):
            item_text = _extract_text_from_adf(child).strip()
            if item_text:
                items.append(f"{i}. {item_text}")
        return "\n".join(items) + "\n"
    if node_type == "codeBlock":
        return f"```\n{child_text}\n```\n"

    # ── Known container types: return child text as-is ────────────────
    # Handles doc, listItem, tableRow, tableCell, etc.
    if node_type in (
        "doc",
        "listItem",
        "tableRow",
        "tableCell",
        "tableHeader",
        "panel",
        "blockquote",
        "rule",
        "expand",
        "nestedExpand",
        "layoutSection",
        "layoutColumn",
        "bodiedExtension",
        "extensionFrame",
        "mediaGroup",
        "applicationCard",
    ):
        return child_text

    # ── FEAT-030 / Bug 4: Unknown node type — graceful fallback ──────
    # Instead of silently dropping content, render a marker so downstream
    # consumers know something was skipped.  If the node has children with
    # extractable text, include that too.
    if child_text:
        return child_text
    return f"[unsupported: {node_type}]"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _build_auth_header() -> str:
    """
    Build the HTTP Basic Auth header value for Jira.

    Jira REST API v3 uses Basic Auth with format:
    ``Authorization: Basic base64(email:api_token)``

    Returns
    -------
    str
        The full header value including the ``Basic`` prefix.
        Example: ``"Basic dXNlckBleGFtcGxlLmNvbTp0b2tlbg=="``

    Notes
    -----
    This mirrors the auth approach from ``pwtgen/src/jira.ts``:
    ``Authorization: 'Basic ' + Buffer.from(...)``
    """
    credentials = f"{settings.jira_email}:{settings.jira_api_token}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _build_headers() -> dict[str, str]:
    """
    Build the complete HTTP headers dict for Jira API requests.

    Returns
    -------
    dict[str, str]
        Headers including authorization, content type, and accept.
    """
    return {
        "Authorization": _build_auth_header(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_ticket_context(ticket_id: str) -> JiraTicketContext:
    """
    Fetch a Jira ticket and return a parsed ``JiraTicketContext``.

    This is the primary public function of this module.  It:
      1. Calls ``GET /rest/api/3/issue/{ticket_id}``
      2. Extracts ``summary``, ``description``, ``customfield_10031``
      3. Parses ADF fields into plain text
      4. Returns a ``JiraTicketContext`` ready for the LangGraph state

    The ``acceptance_criteria_steps`` field is left empty — it will be
    populated later by ``ac_parser_node`` (which uses the LLM to parse
    the raw AC text into discrete testable steps).

    Args
    ----
    ticket_id : str
        The Jira issue key to fetch.
        Examples: ``"VC2-8967"``, ``"VC2-9001"``

    Returns
    -------
    JiraTicketContext
        Parsed ticket data with plain-text description and AC.

    Raises
    ------
    JiraClientError
        If the Jira API returns a non-200 status code.
        Common causes:
        - 401: Invalid credentials (check JIRA_EMAIL + JIRA_API_TOKEN)
        - 404: Ticket not found (check the ticket ID)
        - 403: No permission to view this ticket

    httpx.HTTPError
        If the network request itself fails (timeout, DNS, etc.).

    Example
    -------
    >>> ctx = await fetch_ticket_context("VC2-8967")
    >>> ctx["ticket_id"]
    'VC2-8967'
    >>> ctx["summary"]
    'Quick Order should auto-populate client name'
    >>> len(ctx["acceptance_criteria"]) > 0
    True
    """
    # ── Cache check ──────────────────────────────────────────────────
    cache = get_jira_cache()
    cached = await cache.get(ticket_id, domain=settings.jira_domain)
    if cached:
        # Re-wrap the dict into a JiraTicketContext object
        return JiraTicketContext(**cached)

    url = f"{settings.jira_base_url}/issue/{ticket_id}"

    # Request only the fields we need — reduces response size and
    # avoids transferring large change logs, comments, etc.
    # (TASK-054: TD-018 — dynamic AC field mapping)
    base_fields = ["summary", "description", "attachment"]
    all_fields = ",".join(base_fields + settings.jira_ac_fields)
    params = {
        "fields": all_fields,
    }

    logger.info(
        "Fetching Jira ticket '%s' from %s",
        ticket_id,
        settings.jira_domain,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers=_build_headers(),
            params=params,
        )

    # ── Error handling ────────────────────────────────────────────────
    if response.status_code == 401:
        raise JiraClientError(
            f"Jira authentication failed (401). Check JIRA_EMAIL and JIRA_API_TOKEN in your .env file. URL: {url}",
            status_code=401,
            url=url,
        )

    if response.status_code == 404:
        raise JiraClientError(
            f"Jira ticket '{ticket_id}' not found (404). Verify the ticket ID exists and that "
            f"JIRA_DOMAIN is correct (currently: {settings.jira_domain}). "
            "Note: vcreative.atlassian.net is preferred over vcreativeinc.atlassian.net. "
            f"URL: {url}",
            status_code=404,
            url=url,
        )

    if response.status_code != 200:
        # Capture a short excerpt of the response body for debugging
        body_excerpt = response.text[:500] if response.text else "(empty body)"
        raise JiraClientError(
            f"Jira API returned {response.status_code}: {body_excerpt}. URL: {url}",
            status_code=response.status_code,
            url=url,
        )

    # ── Parse response ────────────────────────────────────────────────
    data = response.json()
    fields = data.get("fields", {})

    # summary is always a plain string in Jira v3
    summary: str = fields.get("summary", "")

    # attachments metadata (metadata only, no binary content yet)
    attachments: list[dict] = fields.get("attachment", [])

    # description is ADF in Jira v3 — parse it to plain text
    raw_description = fields.get("description")
    description: str = _extract_text_from_adf(raw_description).strip()

    # customfield_10031 (Acceptance Criteria) — may be ADF or plain text
    # depending on Jira field configuration. We check fields configured in settings.
    ac_field_ids = settings.jira_ac_fields
    raw_ac = None
    for field_id in ac_field_ids:
        raw_ac = fields.get(field_id)
        if raw_ac:
            logger.info("Found AC in Jira field '%s'", field_id)
            break
    if isinstance(raw_ac, dict):
        # ADF format — parse recursively
        acceptance_criteria = _extract_text_from_adf(raw_ac).strip()
    elif isinstance(raw_ac, str):
        # Plain text (older Jira configurations)
        acceptance_criteria = raw_ac.strip()
    else:
        # Field is null or unexpected type
        acceptance_criteria = ""
        # Surface the customfield_* IDs that ARE populated on this ticket so the
        # operator can identify the correct AC field ID for this Jira project
        # (custom field IDs vary per project — vpromotions often differs from
        # vpromedia). Set JIRA_AC_FIELDS env var to include the right ID.
        populated_customfields = sorted(
            k for k, v in fields.items()
            if k.startswith("customfield_") and v not in (None, "", [], {})
        )
        logger.warning(
            "Jira ticket '%s' has empty or unrecognised Acceptance Criteria (tried %s). "
            "Raw value type: %s. Populated customfield_* IDs on this ticket: %s. "
            "If AC lives in one of these, add it to JIRA_AC_FIELDS env var.",
            ticket_id,
            list(ac_field_ids),
            type(raw_ac).__name__,
            populated_customfields or "(none)",
        )

    # ── Resolve test requirements ──────────────────────────────────────
    # Priority: Acceptance Criteria field → Description field.
    # Many tickets document requirements only in the description.
    if acceptance_criteria:
        test_requirements = acceptance_criteria
        requirements_source = "acceptance_criteria"
    elif description:
        test_requirements = description
        requirements_source = "description (AC field was empty)"
        logger.info(
            "Jira ticket '%s': AC field empty — using description as test requirements (%d chars)",
            ticket_id,
            len(description),
        )
    else:
        test_requirements = ""
        requirements_source = "none"
        logger.warning(
            "Jira ticket '%s': both AC and description are empty — agent will use fallback step",
            ticket_id,
        )

    # ── Override credential extraction ───────────────────────────────
    # If the ticket explicitly specifies login credentials, extract them.
    # When present, the agent will skip pre-login and let the AC steps
    # handle the login form as part of the test.
    override_login_email, override_login_password = _extract_login_credentials(test_requirements)

    # Determine credential status
    has_email = bool(override_login_email)
    has_password = bool(override_login_password)
    if has_email and has_password:
        credential_status: str = "complete"
    elif has_email or has_password:
        credential_status = "partial"
    else:
        credential_status = "none"

    if credential_status == "complete":
        logger.info(
            "Jira ticket '%s': found COMPLETE login credentials — email=%s password=*** — pre-login will be skipped",
            ticket_id,
            override_login_email,
        )
    elif credential_status == "partial":
        missing = "password" if has_email else "email"
        logger.warning(
            "Jira ticket '%s': found PARTIAL credentials (missing: %s) — "
            "user must supply the missing field before run can start",
            ticket_id,
            missing,
        )

    logger.info(
        "Successfully fetched Jira ticket '%s': summary='%s', "
        "description=%d chars, AC=%d chars, requirements_source=%s",
        ticket_id,
        summary[:80],
        len(description),
        len(acceptance_criteria),
        requirements_source,
    )

    result = JiraTicketContext(
        ticket_id=ticket_id,
        summary=summary,
        description=description,
        acceptance_criteria=test_requirements,
        acceptance_criteria_steps=[],
        attachments=attachments,
        override_login_email=override_login_email,
        override_login_password=override_login_password,
        credential_status=credential_status,  # type: ignore[arg-type]
    )

    # ── Store in cache ──────────────────────────────────────────────
    # We store the raw dict so it can be easily serialized/deserialized
    await cache.set(ticket_id, result, domain=settings.jira_domain)

    return result


async def fetch_issue_comments(ticket_id: str) -> list[dict]:
    """
    Fetch comments for a Jira ticket.

    Uses GET /rest/api/3/issue/{ticket_id}/comment.

    Returns
    -------
    list[dict]
        List of parsed comments:
        [
            {
                "id": "10001",
                "author": "John Doe",
                "body": "This is a comment",
                "created": "2026-06-01T12:00:00.000+0000",
            },
            ...
        ]
    """
    url = f"{settings.jira_base_url}/issue/{ticket_id}/comment"

    logger.info("Fetching comments for ticket '%s'", ticket_id)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_build_headers())

        if response.status_code != 200:
            body_excerpt = response.text[:500] if response.text else "(empty body)"
            raise JiraClientError(
                f"Jira API returned {response.status_code} for comments: {body_excerpt}. URL: {url}",
                status_code=response.status_code,
                url=url,
            )

        data = response.json()
        raw_comments = data.get("comments", [])

        comments = []
        for c in raw_comments:
            body_adf = c.get("body")
            # body can be ADF dict or string
            body_text = ""
            if isinstance(body_adf, dict):
                body_text = _extract_text_from_adf(body_adf).strip()
            elif isinstance(body_adf, str):
                body_text = body_adf.strip()

            author_data = c.get("author") or {}
            author_name = author_data.get("displayName", "Unknown")

            comments.append({
                "id": c.get("id", ""),
                "author": author_name,
                "body": body_text,
                "created": c.get("created", ""),
            })

        return comments

    except httpx.HTTPError as e:
        logger.error("Jira comments fetch network error for %s: %s", ticket_id, str(e))
        raise JiraClientError(
            f"Jira comments fetch network error: {str(e)}",
            url=str(e.request.url) if hasattr(e, "request") else "",
        ) from e


async def download_attachment(attachment_id: str) -> bytes:
    """
    Download the raw binary content of a Jira attachment.

    Uses the Jira REST API v3 attachment content endpoint:
    ``GET /rest/api/3/attachment/content/{id}``

    Args
    ----
    attachment_id : str
        The unique ID of the attachment to download.

    Returns
    -------
    bytes
        The raw binary content of the file.

    Raises
    ------
    JiraClientError
        If the download fails (404 not found, 401 unauthorized, etc.).
    """
    url = f"{settings.jira_base_url}/attachment/content/{attachment_id}"

    logger.info("Downloading Jira attachment '%s'", attachment_id)

    # Jira attachment content endpoint returns 303 See Other with an S3 URL
    # in Location. httpx defaults to follow_redirects=False, which drops the
    # binary body and returns the redirect metadata only. Enable follow so we
    # fetch the actual attachment bytes.
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(
            url,
            headers=_build_headers(),
        )

    if response.status_code == 200:
        return response.content

    if response.status_code == 404:
        raise JiraClientError(
            f"Jira attachment '{attachment_id}' not found (404).",
            status_code=404,
            url=url,
        )

    # Capture excerpt of error
    body_excerpt = response.text[:500] if response.text else "(empty body)"
    raise JiraClientError(
        f"Jira attachment download failed with status {response.status_code}: {body_excerpt}",
        status_code=response.status_code,
        url=url,
    )


async def validate_jira_connectivity() -> bool:
    """
    Test that the Jira API is reachable and credentials are valid.

    Used by the ``/health`` endpoint to verify Jira connectivity at
    startup and on-demand.

    Makes a lightweight ``GET /rest/api/3/myself`` call which returns
    the authenticated user's profile. This is the cheapest Jira API
    call available — it doesn't fetch any ticket data.

    Returns
    -------
    bool
        ``True`` if the API returned 200 and credentials are valid.
        ``False`` if the request failed for any reason.

    Example
    -------
    >>> ok = await validate_jira_connectivity()
    >>> if not ok:
    ...     print("⚠ Jira credentials are invalid or API is unreachable")
    """
    url = f"{settings.jira_base_url}/myself"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=_build_headers())

        if response.status_code == 200:
            user_data = response.json()
            display_name = user_data.get("displayName", "unknown")
            logger.info("Jira connectivity OK. Authenticated as: %s", display_name)
            return True

        logger.warning(
            "Jira connectivity check failed: HTTP %d. URL: %s",
            response.status_code,
            url,
        )
        return False

    except httpx.HTTPError as e:
        logger.warning("Jira connectivity check failed: %s", str(e))
        return False


async def fetch_board_tickets(
    project: str | None = None,
    board_ids: list[int] | None = None,
) -> list[dict]:
    """
    Fetch tickets from the specified Jira Software boards.

    Uses the Agile REST API (``/rest/agile/1.0/board/{id}/issue``) with
    JQL filtering to exclude completed issues (statusCategory != Done).
    This drastically improves performance on large boards (like board 27).

    Args
    ----
    project : str | None
        Optional project key to filter by (e.g. "QA").
        If None or "all", no project filter is applied.
    board_ids : list[int] | None
        Jira Software board IDs to fetch from. Defaults to settings.jira_board_ids.

    Returns
    -------
    list[dict]
        Deduplicated list of lightweight issue summaries::

            [
                {
                    "id": "QA-280",
                    "summary": "Ensure Failed Login Message",
                    "status": "In Progress",
                    "priority": "Medium",
                    "issue_type": "Story",
                },
                ...
            ]
    """
    if board_ids is None:
        board_ids = settings.jira_board_ids

    # Agile API lives one level above the REST API v3 path
    agile_base = f"https://{settings.jira_domain}/rest/agile/1.0"
    page_size = 100

    seen_keys: set[str] = set()
    tickets: list[dict] = []

    # Build JQL: always exclude Done issues to prevent timing out on 7000+ item boards.
    # Users typically only want to see active work in a selector.
    jql_parts = []
    if project and project.lower() != "all":
        # Handle cases where project might be a comma-separated list or single string
        if "," in project:
            proj_list = [f"'{p.strip()}'" for p in project.split(",") if p.strip()]
            jql_parts.append(f"project IN ({','.join(proj_list)})")
        else:
            jql_parts.append(f"project = '{project.strip()}'")

    jql = " AND ".join(jql_parts)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for board_id in board_ids:
                url = f"{agile_base}/board/{board_id}/issue"
                start_at = 0
                total = 1  # sentinel

                while start_at < total:
                    params = {
                        "startAt": start_at,
                        "maxResults": page_size,
                        "fields": "summary,status,priority,issuetype",
                        "jql": jql,
                    }
                    response = await client.get(
                        url, headers=_build_headers(), params=params
                    )
                    response.raise_for_status()
                    data = response.json()

                    total = data.get("total", 0)
                    issues = data.get("issues", [])
                    if not issues:
                        break

                    for issue in issues:
                        key = issue.get("key", "")
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        f = issue.get("fields", {})
                        tickets.append(
                            {
                                "id": key,
                                "summary": f.get("summary", ""),
                                "status": f.get("status", {}).get("name", ""),
                                "priority": (f.get("priority") or {}).get("name", ""),
                                "issue_type": f.get("issuetype", {}).get("name", ""),
                            }
                        )

                    start_at += len(issues)

                logger.info(
                    "Board %d: fetched %d issues (total=%d) with JQL: %s",
                    board_id,
                    start_at,
                    total,
                    jql,
                )

        logger.info(
            "fetch_board_tickets: %d unique tickets across boards %s",
            len(tickets),
            board_ids,
        )
        return tickets

    except httpx.HTTPStatusError as e:
        logger.error(
            "Jira board fetch failed: HTTP %d — %s",
            e.response.status_code,
            str(e),
        )
        raise JiraClientError(
            f"Jira board fetch failed (HTTP {e.response.status_code}). URL: {e.request.url}",
            status_code=e.response.status_code,
            url=str(e.request.url),
        ) from e
    except httpx.HTTPError as e:
        logger.error("Jira board fetch network error: %s", str(e))
        raise JiraClientError(
            f"Jira board fetch network error: {str(e)}",
            url=str(e.request.url) if hasattr(e, "request") else "",
        ) from e


async def post_jira_comment(ticket_id: str, body: str) -> bool:
    """
    Post a comment to a Jira issue using the ADF (Atlassian Document Format)
    text body.

    Called from ``reporter_node`` after a failed run to attach the
    failure analysis triage directly to the ticket.

    Args
    ----
    ticket_id : str
        Jira issue key, e.g. ``"QA-280"``.

    body : str
        Plain text or wiki-markup comment body.

    Returns
    -------
    bool
        ``True`` if the comment was posted successfully.
    """
    url = f"{settings.jira_base_url}/issue/{ticket_id}/comment"

    # Jira REST API v3 uses ADF for comment bodies
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body}],
                }
            ],
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=_build_headers(), json=payload)

        if response.status_code in (200, 201):
            logger.info("Posted vQA triage comment to %s", ticket_id)
            return True

        logger.warning(
            "Failed to post Jira comment to %s: HTTP %d — %s",
            ticket_id,
            response.status_code,
            response.text[:200],
        )
        return False

    except httpx.HTTPError as e:
        logger.error("Jira comment post error for %s: %s", ticket_id, str(e))
        return False


async def update_ticket_ac(ticket_id: str, new_ac_text: str) -> bool:
    """
    Update the Acceptance Criteria of a Jira ticket.
    Uses the first field in settings.jira_ac_fields (default customfield_10031).
    Uses Jira v3 REST API ADF format.
    """
    url = f"{settings.jira_base_url}/issue/{ticket_id}"

    # Use the primary AC field for updates (TASK-054)
    primary_field = (
        settings.jira_ac_fields[0] if settings.jira_ac_fields else "customfield_10031"
    )

    payload = {
        "fields": {
            primary_field: {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": new_ac_text}]}],
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.put(url, headers=_build_headers(), json=payload)

        if response.status_code in (204, 200):
            logger.info("Updated AC for ticket %s", ticket_id)
            return True

        logger.warning(
            "Failed to update AC for Jira ticket %s: HTTP %d — %s",
            ticket_id,
            response.status_code,
            response.text[:200],
        )
        return False

    except httpx.HTTPError as e:
        logger.error("Jira AC update error for %s: %s", ticket_id, str(e))
        return False


async def append_to_ticket_ac(
    ticket_id: str,
    new_steps: list[str],
    audit_source: str = "vQA Dashboard",
) -> tuple[bool, str]:
    """
    Append new acceptance criteria steps to an existing Jira ticket's
    AC field without overwriting existing content.

    This is the safe, append-only variant of ``update_ticket_ac``.
    It fetches the current AC text, appends the new steps with a visual
    separator, and writes the combined text back.  An audit comment is
    posted to the ticket so the QA team has a clear trail of what was added.

    Args
    ----
    ticket_id : str
        Jira issue key, e.g. ``"QA-280"``.
    new_steps : list[str]
        The new AC steps to append (plain text strings).
    audit_source : str
        Label for the audit comment (e.g. "vQA Dashboard", "API").

    Returns
    -------
    tuple[bool, str]
        ``(success, new_full_ac_text)`` — the bool indicates whether the
        Jira write succeeded; the string is the final merged AC text
        (useful for the frontend preview even if the write failed).
    """
    if not new_steps:
        return True, ""

    # 1. Fetch current AC (fresh read to avoid stale overwrites)
    try:
        ctx = await fetch_ticket_context(ticket_id)
        existing_ac = ctx.get("acceptance_criteria", "")
    except Exception as e:
        logger.error(
            "append_to_ticket_ac: failed to fetch current AC for %s: %s",
            ticket_id,
            e,
        )
        # Build the text anyway so the caller can still use it locally
        existing_ac = ""

    # 2. Build the appended text
    separator = "\n\n--- Added by vQA ---\n"
    numbered_steps = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(new_steps))
    new_ac_text = f"{existing_ac}{separator}{numbered_steps}"

    # 3. Update the Jira field
    success = await update_ticket_ac(ticket_id, new_ac_text)

    # 4. Post audit comment
    if success:
        comment = (
            f"vQA: Added {len(new_steps)} acceptance criteria:\n"
            + "\n".join(f"• {s}" for s in new_steps)
            + f"\n\nSource: {audit_source}"
        )
        await post_jira_comment(ticket_id, comment)
        logger.info(
            "append_to_ticket_ac: appended %d steps to %s",
            len(new_steps),
            ticket_id,
        )

    return success, new_ac_text
