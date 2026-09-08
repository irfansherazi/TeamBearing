"""
vQA — S3 Storage Utilities
============================
Module: backend/storage/s3.py

Handles all uploads to and reads from AWS S3 for vQA artifacts:
screenshots, session videos (``.webm``), and HTML audit reports.

Architecture Context
--------------------
vQA persists three categories of artifacts to S3 under the configured
prefix (``settings.s3_prefix``):

  1. ``/screenshots/{run_id}/``  — one PNG per browser action
  2. ``/videos/{run_id}/``       — one ``.webm`` session recording per run
  3. ``/reports/{run_id}/``      — one HTML audit report per run

All uploads return a full HTTPS URL that can be:
  - Embedded in the HTML audit report (``<img src="...">``)
  - Returned via the ``/status/{run_id}`` API endpoint
  - Streamed to the React dashboard via WebSocket

S3 Key Layout
--------------
::

    vcreative-deployments/
    └── vSuitePlatform/Buildartif/vqa-results/
        ├── screenshots/
        │   └── run-abc123/
        │       ├── step-000-navigate-20260401T211500Z-a1b2c3d4.png
        │       ├── step-001-click-20260401T211505Z-e5f6g7h8.png
        │       └── ...
        ├── videos/
        │   └── run-abc123/
        │       └── session-20260401T211500Z.webm
        └── reports/
            └── run-abc123/
                └── audit-VC2-8967-account_executive-20260401T211500Z.html

Thread Safety
-------------
This module uses ``aioboto3`` for async S3 operations to avoid blocking
the FastAPI event loop.  Each function creates its own short-lived
S3 client — no shared global client to worry about.

If ``aioboto3`` is not available, the module falls back to synchronous
``boto3`` wrapped in ``asyncio.to_thread()`` for compatibility.

Dependencies
------------
  - ``boto3``           — AWS SDK for Python
  - ``backend/config.py`` — S3 bucket/prefix/region settings

See Also
--------
  - ``backend/browser/screenshot.py`` — calls ``upload_bytes()``
  - ``backend/engine/reporter.py``    — calls ``upload_report()`` and ``upload_video()``
"""

import asyncio
import logging
from pathlib import Path
from typing import Final

import boto3
from botocore.exceptions import ClientError

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Content type mappings used when uploading artifacts.
CONTENT_TYPES: Final[dict[str, str]] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webm": "video/webm",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
}

#: Default presigned URL expiry time (1 hour).
DEFAULT_PRESIGN_EXPIRY: Final[int] = 3600


# ---------------------------------------------------------------------------
# S3 client factory
# ---------------------------------------------------------------------------


def _get_s3_client():
    """
    Create a boto3 S3 client using settings from config.

    Creates a new client on each call (short-lived usage pattern).
    This avoids thread-safety issues with shared clients and ensures
    fresh credentials are used (important when running with temporary
    IAM credentials).

    Returns
    -------
    botocore.client.S3
        A boto3 S3 client configured with the application's AWS
        credentials and region.

    Notes
    -----
    If ``settings.aws_access_key_id`` is ``None`` (e.g. running on
    EC2/ECS with an instance profile), boto3 will use the default
    credential chain automatically.
    """
    kwargs: dict = {"region_name": settings.aws_region}

    # Only pass explicit credentials if they are set.
    # When running on EC2/ECS, we want boto3 to use the instance profile.
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    return boto3.client("s3", **kwargs)


# ---------------------------------------------------------------------------
# Upload functions
# ---------------------------------------------------------------------------


async def upload_bytes(
    data: bytes,
    bucket: str,
    key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """
    Upload raw bytes to S3 and return the HTTPS URL.

    This is the lowest-level upload function.  Higher-level helpers
    (``upload_screenshot``, ``upload_video``, ``upload_report``) call
    this under the hood.

    The upload runs in a thread pool via ``asyncio.to_thread()`` to
    avoid blocking the FastAPI event loop.

    Args
    ----
    data : bytes
        The raw file content to upload.

    bucket : str
        S3 bucket name (e.g. ``"vcreative-deployments"``).

    key : str
        Full S3 object key (e.g. ``"prefix/screenshots/run-abc/step-001.png"``).

    content_type : str
        MIME type for the uploaded object.  Defaults to
        ``"application/octet-stream"`` if not specified.

    Returns
    -------
    str
        HTTPS URL of the uploaded object.
        Example: ``"https://vcreative-deployments.s3.amazonaws.com/prefix/screenshots/..."``

    Raises
    ------
    botocore.exceptions.ClientError
        If the S3 upload fails (permissions, bucket not found, etc.).

    Example
    -------
    >>> url = await upload_bytes(
    ...     data=b"PNG content...",
    ...     bucket="my-bucket",
    ...     key="path/to/file.png",
    ...     content_type="image/png",
    ... )
    >>> url
    'https://my-bucket.s3.amazonaws.com/path/to/file.png'
    """

    def _do_upload() -> str:
        """Synchronous upload — runs in thread pool."""
        client = _get_s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        # Construct the HTTPS URL
        url = f"https://{bucket}.s3.amazonaws.com/{key}"
        return url

    url: str = await asyncio.to_thread(_do_upload)

    logger.info(
        "S3 upload complete: bucket=%s, key=%s, size=%d bytes, type=%s",
        bucket,
        key,
        len(data),
        content_type,
    )

    return url


async def upload_file(
    file_path: Path,
    bucket: str,
    key: str,
    content_type: str | None = None,
) -> str:
    """
    Upload a local file to S3 and return the HTTPS URL.

    Reads the file from disk and delegates to ``upload_bytes()``.
    Content type is auto-detected from the file extension if not
    provided.

    Args
    ----
    file_path : Path
        Absolute path to the local file to upload.

    bucket : str
        S3 bucket name.

    key : str
        Full S3 object key.

    content_type : str | None
        MIME type override.  If ``None``, auto-detected from the file
        extension using ``CONTENT_TYPES``.

    Returns
    -------
    str
        HTTPS URL of the uploaded object.

    Raises
    ------
    FileNotFoundError
        If ``file_path`` does not exist.

    botocore.exceptions.ClientError
        If the S3 upload fails.

    Example
    -------
    >>> url = await upload_file(
    ...     Path("/tmp/vqa-videos/session.webm"),
    ...     "my-bucket",
    ...     "prefix/videos/session.webm",
    ... )
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    data: bytes = file_path.read_bytes()

    # Auto-detect content type from extension
    if content_type is None:
        suffix = file_path.suffix.lower()
        content_type = CONTENT_TYPES.get(suffix, "application/octet-stream")

    return await upload_bytes(
        data=data,
        bucket=bucket,
        key=key,
        content_type=content_type,
    )


async def upload_video(
    video_path: Path,
    run_id: str,
    ticket_id: str = "",
) -> str:
    """
    Upload a session recording ``.webm`` file to S3.

    Called by ``reporter_node`` after the browser context is closed
    and the video file is finalised.

    Args
    ----
    video_path : Path
        Absolute path to the ``.webm`` recording.

    run_id : str
        Unique run identifier, used in the S3 key.

    ticket_id : str
        Jira ticket ID, included in the filename for easy identification.

    Returns
    -------
    str
        HTTPS URL of the uploaded video.

    Example
    -------
    >>> url = await upload_video(
    ...     Path("/tmp/vqa-videos/session.webm"),
    ...     run_id="run-abc123",
    ...     ticket_id="VC2-8967",
    ... )
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"session-{ticket_id}-{timestamp}.webm" if ticket_id else f"session-{timestamp}.webm"
    key = f"{settings.s3_prefix}/videos/{run_id}/{filename}"

    url = await upload_file(
        file_path=video_path,
        bucket=settings.s3_bucket,
        key=key,
        content_type="video/webm",
    )

    logger.info(
        "[%s] Video uploaded: %s (%.1f MB)",
        run_id,
        url,
        video_path.stat().st_size / (1024 * 1024),
    )

    return url


async def upload_error_context(
    json_content: str,
    md_content: str,
    run_id: str,
    ticket_id: str,
) -> tuple[str, str]:
    """
    Upload failure analysis context (JSON and Markdown) to S3.

    Args
    ----
    json_content : str
        Structured JSON error context.
    md_content : str
        Human-readable Markdown error context.
    run_id : str
        Unique run identifier.
    ticket_id : str
        Jira ticket ID.

    Returns
    -------
    tuple[str, str]
        (json_url, md_url)
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{settings.s3_prefix}/reports/{run_id}"

    json_key = f"{prefix}/error-context-{ticket_id}-{timestamp}.json"
    md_key = f"{prefix}/error-context-{ticket_id}-{timestamp}.md"

    json_url = await upload_bytes(
        data=json_content.encode("utf-8"),
        bucket=settings.s3_bucket,
        key=json_key,
        content_type="application/json",
    )

    md_url = await upload_bytes(
        data=md_content.encode("utf-8"),
        bucket=settings.s3_bucket,
        key=md_key,
        content_type="text/markdown; charset=utf-8",
    )

    return json_url, md_url


async def upload_report(
    html_content: str,
    run_id: str,
    ticket_id: str,
    role_key: str,
) -> str:
    """
    Upload an HTML audit report to S3.

    Called by ``reporter_node`` after generating the final HTML report.

    Args
    ----
    html_content : str
        The complete HTML report string.

    run_id : str
        Unique run identifier.

    ticket_id : str
        Jira ticket ID (e.g. ``"VC2-8967"``).

    role_key : str
        Role key (e.g. ``"account_executive"``).

    Returns
    -------
    str
        HTTPS URL of the uploaded report.

    Example
    -------
    >>> url = await upload_report(
    ...     "<html>...</html>",
    ...     run_id="run-abc123",
    ...     ticket_id="VC2-8967",
    ...     role_key="account_executive",
    ... )
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"audit-{ticket_id}-{role_key}-{timestamp}.html"
    key = f"{settings.s3_prefix}/reports/{run_id}/{filename}"

    data = html_content.encode("utf-8")

    url = await upload_bytes(
        data=data,
        bucket=settings.s3_bucket,
        key=key,
        content_type="text/html; charset=utf-8",
    )

    logger.info(
        "[%s] Report uploaded: %s (%d bytes)",
        run_id,
        url,
        len(data),
    )

    return url


# ---------------------------------------------------------------------------
# Computer-Use loop uploads
# ---------------------------------------------------------------------------
#
# The CU loop (backend/engine/computer_use/runner.py) writes per-iteration
# screenshots and transcripts to disk under `.logs/computer_use/{run_id}/`
# instead of uploading during the run. At report-render time we hoist those
# artifacts to S3 so the HTML report references CDN URLs (small file, works
# from any browser) instead of embedded base64 (~5-6 MB per report). Same
# key layout as the LangGraph reporter — screenshots under /screenshots/,
# HTML under /reports/ — so the buckets stay uniform across engines.


async def upload_cu_screenshot(
    png_bytes: bytes,
    run_id: str,
    iter_idx: int,
) -> str:
    """
    Upload one CU-loop iteration screenshot and return the HTTPS URL.

    Called from the CU report pipeline (routes.py::_execute_cu_run) once
    per iteration file discovered in the transcript dir. Uses the same
    /screenshots/{run_id}/ prefix as `capture_and_upload_screenshot` so
    both engines land in the same S3 folder tree.

    Args
    ----
    png_bytes : bytes
        Raw PNG content (the same bytes the loop wrote to
        ``.logs/computer_use/{run_id}/{iter:03d}_screenshot.png``).
    run_id : str
        Unique run identifier — becomes the folder name under
        ``/screenshots/``.
    iter_idx : int
        CU loop iteration number this screenshot represents.

    Returns
    -------
    str
        HTTPS URL of the uploaded PNG.
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"cu-iter-{iter_idx:03d}-{timestamp}.png"
    key = f"{settings.s3_prefix}/screenshots/{run_id}/{filename}"

    return await upload_bytes(
        data=png_bytes,
        bucket=settings.s3_bucket,
        key=key,
        content_type="image/png",
    )


async def upload_cu_report(
    html_content: str,
    run_id: str,
    ticket_id: str,
) -> str:
    """
    Upload a CU-loop HTML audit report and return the HTTPS URL.

    Parallel to `upload_report` but without a role_key — the CU loop
    doesn't take a role_context (ghost-login is applied per-step, not
    per-run). Filename layout still mirrors the LangGraph one so
    directory listings sort predictably.

    Args
    ----
    html_content : str
        The complete HTML report string.
    run_id : str
        Unique run identifier.
    ticket_id : str
        Jira ticket ID (used in the filename).

    Returns
    -------
    str
        HTTPS URL of the uploaded report.
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"cu-audit-{ticket_id or 'unknown'}-{timestamp}.html"
    key = f"{settings.s3_prefix}/reports/{run_id}/{filename}"

    data = html_content.encode("utf-8")
    url = await upload_bytes(
        data=data,
        bucket=settings.s3_bucket,
        key=key,
        content_type="text/html; charset=utf-8",
    )

    logger.info(
        "[%s] CU report uploaded: %s (%d bytes)",
        run_id,
        url,
        len(data),
    )

    return url


# ---------------------------------------------------------------------------
# Read / URL generation
# ---------------------------------------------------------------------------


async def get_presigned_url(
    bucket: str,
    key: str,
    expiry_seconds: int = DEFAULT_PRESIGN_EXPIRY,
) -> str:
    """
    Generate a presigned URL for secure temporary access to an S3 object.

    Useful for providing time-limited download links in the React
    dashboard without making the S3 objects publicly accessible.

    Args
    ----
    bucket : str
        S3 bucket name.

    key : str
        S3 object key.

    expiry_seconds : int
        How long the URL remains valid.  Default: 3600 (1 hour).

    Returns
    -------
    str
        A presigned HTTPS URL that grants temporary read access.

    Raises
    ------
    botocore.exceptions.ClientError
        If URL generation fails (object doesn't exist, permissions, etc.).

    Example
    -------
    >>> url = await get_presigned_url("my-bucket", "path/to/report.html")
    >>> "X-Amz-Signature" in url
    True
    """

    def _generate() -> str:
        client = _get_s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry_seconds,
        )

    return await asyncio.to_thread(_generate)


async def validate_s3_connectivity() -> bool:
    """
    Test that S3 is reachable and the configured bucket is accessible.

    Used by the ``/health`` endpoint to verify S3 connectivity
    at startup and on-demand.

    Returns
    -------
    bool
        ``True`` if the bucket is accessible.
        ``False`` if the connection or permissions check fails.

    Example
    -------
    >>> ok = await validate_s3_connectivity()
    >>> if not ok:
    ...     print("⚠ S3 bucket not accessible")
    """

    def _check() -> bool:
        try:
            client = _get_s3_client()
            client.head_bucket(Bucket=settings.s3_bucket)
            logger.info("S3 connectivity OK: bucket '%s' accessible", settings.s3_bucket)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "unknown")
            logger.warning(
                "S3 connectivity check failed: bucket='%s', error=%s",
                settings.s3_bucket,
                error_code,
            )
            return False

    return await asyncio.to_thread(_check)
