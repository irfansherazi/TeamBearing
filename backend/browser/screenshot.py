"""
vQA — Screenshot Capture & Upload
===================================
Module: backend/browser/screenshot.py

Captures full-page screenshots from the live Playwright page, encodes
them as base64 PNG strings for the multimodal LLM, and uploads them to
S3 for the audit trail.

Architecture Context
--------------------
Screenshots serve two distinct purposes in vQA:

  1. **LLM input** — before every planner call, a base64-encoded PNG
     is included in the multimodal message to Claude 3.5 Sonnet.  This
     is the "SEE" phase of the see-think-act loop.

  2. **Audit trail** — after every browser action, a post-action
     screenshot is uploaded to S3 and its URL is stored in the
     ``ExecutionStep.screenshot_url`` field of the execution log.

This module provides both functions:
  - ``capture_screenshot_b64()`` — returns the base64 string (for LLM)
  - ``capture_and_upload_screenshot()`` — captures + uploads to S3

Naming Convention
-----------------
Screenshot files on S3 follow this pattern:

    {s3_prefix}/screenshots/step-{index}-{action}-{timestamp}-{hash}.png

Example:
    ``vSuitePlatform/Buildartif/vqa-results/screenshots/step-3-click-20260401T211530Z-abc12345.png``

Dependencies
------------
  - ``playwright.async_api.Page`` — screenshot capture
  - ``backend/storage/s3.py``     — S3 upload
  - ``backend/config.py``         — S3 bucket/prefix settings

See Also
--------
  - ``backend/engine/planner.py``  — consumes base64 screenshots
  - ``backend/engine/executor.py`` — calls capture_and_upload_screenshot()
  - ``backend/engine/state.py``    — ExecutionStep.screenshot_url
"""

import base64
import hashlib
import logging
from datetime import datetime, timezone

from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------


async def capture_screenshot_b64(
    page: Page,
    *,
    full_page: bool = True,
) -> str:
    """
    Capture a screenshot of the current page and return it as a
    base64-encoded PNG string.

    This is the "SEE" step of the see-think-act loop.  The returned
    base64 string is included directly in the multimodal message payload
    sent to Claude 3.5 Sonnet via Bedrock.

    Args
    ----
    page : Page
        The active Playwright page to screenshot.

    full_page : bool
        If ``True`` (default), captures the entire scrollable page.
        If ``False``, captures only the currently visible viewport.
        Full-page is preferred because the LLM can see elements
        below the fold that the user would need to scroll to reach.

    Returns
    -------
    str
        Base64-encoded PNG string (without the ``data:image/png;base64,``
        prefix — Bedrock expects raw base64).

    Raises
    ------
    playwright.async_api.Error
        If the page is closed or an error occurs during capture.

    Example
    -------
    >>> b64 = await capture_screenshot_b64(page)
    >>> len(b64) > 0
    True
    >>> # The LLM receives this as:
    >>> # {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}
    """
    raw_bytes: bytes = await page.screenshot(
        full_page=full_page,
        type="png",
    )

    encoded: str = base64.b64encode(raw_bytes).decode("ascii")

    logger.debug(
        "Captured screenshot: %d bytes raw, %d chars base64",
        len(raw_bytes),
        len(encoded),
    )

    return encoded


async def capture_screenshot_bytes(
    page: Page,
    *,
    full_page: bool = True,
) -> bytes:
    """
    Capture a screenshot of the current page and return raw PNG bytes.

    Used when the caller needs to upload the bytes to S3 directly
    (without the base64 encoding overhead).

    Args
    ----
    page : Page
        The active Playwright page.

    full_page : bool
        If ``True``, captures the entire scrollable page.

    Returns
    -------
    bytes
        Raw PNG image bytes.

    Raises
    ------
    playwright.async_api.Error
        If the page is closed or capture fails.
    """
    return await page.screenshot(full_page=full_page, type="png")


# ---------------------------------------------------------------------------
# S3 upload helper
# ---------------------------------------------------------------------------


def generate_screenshot_key(
    run_id: str,
    step_index: int,
    action_type: str,
    s3_prefix: str,
) -> str:
    """
    Generate a unique S3 object key for a screenshot.

    The key includes the step index, action type, timestamp, and a
    short content hash to ensure uniqueness even if the same step is
    retried multiple times.

    Args
    ----
    run_id : str
        The current run's unique identifier.

    step_index : int
        Zero-based step index within the run.

    action_type : str
        The browser action that triggered this screenshot
        (e.g. ``"click"``, ``"fill"``, ``"navigate"``).

    s3_prefix : str
        The base S3 prefix (e.g. ``"vSuitePlatform/Buildartif/vqa-results"``).

    Returns
    -------
    str
        The full S3 object key.

    Example
    -------
    >>> generate_screenshot_key("run-abc", 3, "click", "prefix/results")
    'prefix/results/screenshots/run-abc/step-003-click-20260401T211530Z-abc12345.png'
    """
    timestamp: str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Short hash of run_id + step + timestamp for uniqueness
    hash_input: str = f"{run_id}-{step_index}-{timestamp}"
    short_hash: str = hashlib.md5(hash_input.encode()).hexdigest()[:8]

    filename: str = f"step-{step_index:03d}-{action_type}-{timestamp}-{short_hash}.png"

    return f"{s3_prefix}/screenshots/{run_id}/{filename}"


async def capture_and_upload_screenshot(
    page: Page,
    *,
    run_id: str,
    step_index: int,
    action_type: str,
    s3_prefix: str,
    s3_bucket: str,
) -> tuple[str, str]:
    """
    Capture a screenshot, upload it to S3, and return both the base64
    string and the S3 URL.

    This is the combined operation called by ``executor_node`` after
    every browser action.  It:
    1. Captures the screenshot as raw bytes
    2. Generates a unique S3 key
    3. Uploads the PNG to S3
    4. Encodes the same bytes as base64 (for the LLM)

    This avoids capturing the screenshot twice — one capture serves
    both the audit log and the next planner iteration.

    Args
    ----
    page : Page
        The active Playwright page.

    run_id : str
        Current run identifier.

    step_index : int
        Current step index.

    action_type : str
        The action type that preceded this screenshot.

    s3_prefix : str
        S3 key prefix from settings.

    s3_bucket : str
        S3 bucket name from settings.

    Returns
    -------
    tuple[str, str]
        A tuple of ``(base64_screenshot, s3_url)``.

        - ``base64_screenshot``: raw base64 PNG for the LLM
        - ``s3_url``: full S3 URL of the uploaded screenshot

    Raises
    ------
    Exception
        If screenshot capture or S3 upload fails.  The caller should
        handle this gracefully and log the error.

    Example
    -------
    >>> b64, url = await capture_and_upload_screenshot(
    ...     page,
    ...     run_id="run-abc",
    ...     step_index=3,
    ...     action_type="click",
    ...     s3_prefix="prefix/results",
    ...     s3_bucket="my-bucket",
    ... )
    >>> url
    'https://my-bucket.s3.amazonaws.com/prefix/results/screenshots/run-abc/step-003-click-....png'
    """
    # Import here to avoid circular dependency at module load time
    from backend.storage.s3 import upload_bytes

    # ── Step 1: Capture screenshot ────────────────────────────────────
    raw_bytes: bytes = await capture_screenshot_bytes(page, full_page=True)

    # ── Step 2: Generate S3 key ───────────────────────────────────────
    s3_key: str = generate_screenshot_key(
        run_id=run_id,
        step_index=step_index,
        action_type=action_type,
        s3_prefix=s3_prefix,
    )

    # ── Step 3: Upload to S3 ──────────────────────────────────────────
    s3_url: str = await upload_bytes(
        data=raw_bytes,
        bucket=s3_bucket,
        key=s3_key,
        content_type="image/png",
    )

    logger.info(
        "[%s] Screenshot uploaded: step=%d, action=%s, url=%s",
        run_id,
        step_index,
        action_type,
        s3_url,
    )

    # ── Step 4: Encode as base64 (reusing same bytes) ─────────────────
    b64: str = base64.b64encode(raw_bytes).decode("ascii")

    return b64, s3_url
