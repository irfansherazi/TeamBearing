"""
vQA — Webhook Notifications (Phase 5B)
=========================================
Module: backend/engine/webhooks.py

Fire-and-forget HTTP notifications on run completion.

Supports three payload formats:
  - ``generic``  — Plain JSON body (for custom integrations / Zapier / n8n)
  - ``slack``    — Slack Block Kit message
  - ``teams``    — Microsoft Teams Adaptive Card

Usage
-----
    from backend.engine.webhooks import send_completion_webhook

    await send_completion_webhook(
        webhook_url="https://hooks.slack.com/services/...",
        webhook_format="slack",
        run_id="run-abc123",
        ticket_id="VC2-8967",
        status="passed",
        ac_total=5,
        ac_passed=5,
        report_url="https://s3.../report.html",
        video_url="https://s3.../video.webm",
        cost_usd=0.032,
        duration_ms=45000,
    )

See Also
--------
  - ``backend/config.py``            — webhook_url / webhook_format settings
  - ``backend/engine/reporter.py``   — calls this module after S3 upload
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

WebhookFormat = Literal["generic", "slack", "teams"]


def _build_generic_payload(
    run_id: str,
    ticket_id: str,
    status: str,
    ac_total: int,
    ac_passed: int,
    report_url: str,
    video_url: str,
    cost_usd: float,
    duration_ms: int,
    role: str,
    is_regression: bool = False,
) -> dict[str, Any]:
    """Build a plain JSON payload for generic webhooks."""
    return {
        "event": "vqa.run.completed",
        "run_id": run_id,
        "ticket_id": ticket_id,
        "status": status,
        "role": role,
        "regression": is_regression,
        "ac_total": ac_total,
        "ac_passed": ac_passed,
        "ac_failed": ac_total - ac_passed,
        "report_url": report_url,
        "video_url": video_url,
        "estimated_cost_usd": round(cost_usd, 6),
        "duration_ms": duration_ms,
        "duration_human": f"{duration_ms / 1000:.1f}s",
    }


def _build_slack_payload(
    run_id: str,
    ticket_id: str,
    status: str,
    ac_total: int,
    ac_passed: int,
    report_url: str,
    video_url: str,
    cost_usd: float,
    duration_ms: int,
    role: str,
    is_regression: bool = False,
) -> dict[str, Any]:
    """Build a Slack Block Kit message."""
    emoji = "✅" if status == "passed" else "❌"
    color = "#22c55e" if status == "passed" else "#ef4444"
    duration = f"{duration_ms / 1000:.1f}s"
    regression_prefix = "🚨 REGRESSION — " if is_regression else ""

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{regression_prefix}{emoji} vQA Run Complete — {ticket_id}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Status:*\n{status.upper()}"},
                {"type": "mrkdwn", "text": f"*Role:*\n{role}"},
                {"type": "mrkdwn", "text": f"*AC Steps:*\n{ac_passed}/{ac_total} passed"},
                {"type": "mrkdwn", "text": f"*Duration:*\n{duration}"},
                {"type": "mrkdwn", "text": f"*Cost:*\n${cost_usd:.4f}"},
                {"type": "mrkdwn", "text": f"*Run ID:*\n`{run_id[:12]}`"},
            ],
        },
        {
            "type": "actions",
            "elements": [],
        },
    ]

    # Add report and video links as buttons
    actions = blocks[-1]["elements"]
    if report_url:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "📄 View Report"},
                "url": report_url,
            }
        )
    if video_url:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🎬 Watch Recording"},
                "url": video_url,
            }
        )

    # Remove empty actions block
    if not actions:
        blocks.pop()

    return {
        "blocks": blocks,
        "attachments": [{"color": color, "blocks": []}],
    }


def _build_teams_payload(
    run_id: str,
    ticket_id: str,
    status: str,
    ac_total: int,
    ac_passed: int,
    report_url: str,
    video_url: str,
    cost_usd: float,
    duration_ms: int,
    role: str,
    is_regression: bool = False,
) -> dict[str, Any]:
    """Build a Microsoft Teams Adaptive Card."""
    emoji = "✅" if status == "passed" else "❌"
    duration = f"{duration_ms / 1000:.1f}s"
    regression_prefix = "🚨 REGRESSION — " if is_regression else ""

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"{regression_prefix}{emoji} vQA Run Complete — {ticket_id}",
                            "weight": "Bolder",
                            "size": "Large",
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Status", "value": status.upper()},
                                {"title": "Role", "value": role},
                                {"title": "AC Steps", "value": f"{ac_passed}/{ac_total} passed"},
                                {"title": "Duration", "value": duration},
                                {"title": "Cost", "value": f"${cost_usd:.4f}"},
                                {"title": "Run ID", "value": run_id[:12]},
                            ],
                        },
                    ],
                    "actions": [],
                },
            }
        ],
    }

    actions = card["attachments"][0]["content"]["actions"]
    if report_url:
        actions.append(
            {
                "type": "Action.OpenUrl",
                "title": "📄 View Report",
                "url": report_url,
            }
        )
    if video_url:
        actions.append(
            {
                "type": "Action.OpenUrl",
                "title": "🎬 Watch Recording",
                "url": video_url,
            }
        )

    return card


_BUILDERS = {
    "generic": _build_generic_payload,
    "slack": _build_slack_payload,
    "teams": _build_teams_payload,
}


# ---------------------------------------------------------------------------
# Nightly Scheduled Suite — Compact Slack Block Kit Builder
# ---------------------------------------------------------------------------
# Separate from the per-ticket _build_slack_payload above.  This builder
# produces a compact message: one header line + one line per test + a
# "View Report" button.  No cost, role, or AC count columns (those belong
# to ticket-run payloads, not the nightly suite summary).
# ---------------------------------------------------------------------------

_MAX_ERROR_SNIPPET_CHARS = 200


def _build_nightly_slack_payload(
    suite_run_id: str,
    run_data: dict[str, Any],
    report_url: str,
) -> dict[str, Any]:
    """
    Build a compact Slack Block Kit payload for a nightly suite run.

    Parameters
    ----------
    suite_run_id : str
        The identifier of the suite run (used in context / logging).
    run_data : dict
        The suite run record as returned by playwright_suite_run_store.
        Expected keys: outcome, passed, total, results (list of per-test dicts).
    report_url : str
        Full URL to the vQA run report page for this suite_run_id.

    Returns
    -------
    dict
        A Slack Block Kit message dict ready to POST to a webhook URL.
    """
    passed = run_data.get("passed", 0)
    total = run_data.get("total", 0)
    outcome = run_data.get("outcome", "FAIL")
    results = run_data.get("results", [])

    overall_ok = outcome == "PASS"
    header_emoji = "✅" if overall_ok else "❌"
    summary = f"Nightly suite — {passed}/{total} passed"

    # Header block
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{header_emoji} {summary}",
                "emoji": True,
            },
        }
    ]

    # Per-test lines — one section block each so they render as separate rows
    for result in results:
        test_id = result.get("test_id", "unknown")
        status = result.get("status", "FAIL")
        duration_ms = result.get("duration_ms") or 0.0
        error_snippet = result.get("error_snippet") or ""

        test_ok = status == "PASS"
        test_emoji = "✅" if test_ok else "❌"
        duration_s = f"{duration_ms / 1000:.1f}s"

        test_line = f"{test_emoji} {test_id} — {duration_s}"

        # Add error snippet under failing tests (truncated to 200 chars)
        if not test_ok and error_snippet:
            truncated = error_snippet[:_MAX_ERROR_SNIPPET_CHARS]
            test_line += f"\n```{truncated}```"

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": test_line,
                },
            }
        )

    # "View Report" button
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Report"},
                    "url": report_url,
                }
            ],
        }
    )

    return {"blocks": blocks}


async def post_nightly_slack(webhook_url: str, payload: dict[str, Any]) -> bool:
    """
    POST a compact nightly Slack Block Kit payload to the configured webhook URL.

    Fire-and-forget — errors are logged but never raised so the background
    task always completes even if Slack is unreachable.

    Parameters
    ----------
    webhook_url : str
        Slack incoming webhook URL.  If empty, the call is silently skipped.
    payload : dict
        Block Kit payload as returned by _build_nightly_slack_payload.

    Returns
    -------
    bool
        True if the POST succeeded (2xx), False otherwise.
    """
    if not webhook_url:
        logger.warning("[nightly] Slack webhook URL is empty — skipping notification")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            logger.info(
                "[nightly] Slack notification posted successfully (status=%d)",
                resp.status_code,
            )
            return True
    except Exception as exc:
        logger.warning("[nightly] Slack notification failed: %s", exc)
        return False


async def send_completion_webhook(
    webhook_url: str,
    webhook_format: WebhookFormat = "generic",
    *,
    run_id: str = "",
    ticket_id: str = "",
    status: str = "unknown",
    ac_total: int = 0,
    ac_passed: int = 0,
    report_url: str = "",
    video_url: str = "",
    cost_usd: float = 0.0,
    duration_ms: int = 0,
    role: str = "",
    is_regression: bool = False,
) -> bool:
    """
    Send a completion notification to a webhook URL.

    Fire-and-forget — errors are logged but never raised.

    Parameters
    ----------
    webhook_url : str
        Destination URL. If empty, the call is silently skipped.
    webhook_format : WebhookFormat
        Payload format: ``"generic"``, ``"slack"``, or ``"teams"``.
    run_id, ticket_id, status, ...
        Run metadata fields.

    Returns
    -------
    bool
        True if the webhook was sent successfully, False otherwise.
    """
    if not webhook_url:
        return False

    builder = _BUILDERS.get(webhook_format, _build_generic_payload)
    payload = builder(
        run_id=run_id,
        ticket_id=ticket_id,
        status=status,
        ac_total=ac_total,
        ac_passed=ac_passed,
        report_url=report_url,
        video_url=video_url,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        role=role,
        is_regression=is_regression,
    )

    logger.info(
        "[%s] Sending %s webhook to %s",
        run_id,
        webhook_format,
        webhook_url[:60],
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            logger.info(
                "[%s] Webhook sent successfully (status=%d)",
                run_id,
                resp.status_code,
            )
            return True
    except Exception as e:
        logger.warning(
            "[%s] Webhook delivery failed: %s",
            run_id,
            e,
        )
        return False
