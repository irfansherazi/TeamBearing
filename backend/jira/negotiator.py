"""
vQA — Jira AC Negotiator
==========================
Module: backend/jira/negotiator.py

Implements the Bidirectional Jira AC Synchronization (The Feedback Loop)
as defined in the High-Reliability Strategy.

Responsibilities:
1. Parsing: Fetches and evaluates raw ACs from Jira using the Quality Gate.
2. Negotiation: Generates a proposed Test Plan and posts it to the Jira ticket.
3. Confirmation & Auto-Sync: Updates the Jira card ACs and regenerates the test plan.
"""

import logging
import re
from typing import Optional

from backend.engine.ac_parser import _stage_1_normalize
from backend.engine.ac_quality_gate import ACQualityResult, score_ac_quality
from backend.engine.state import JiraTicketContext
from backend.jira.client import fetch_ticket_context, post_jira_comment, update_ticket_ac, fetch_issue_comments

logger = logging.getLogger(__name__)


def _is_high_signal_comment(text: str) -> bool:
    """Check if a comment contains technical instructions, selectors, or code blocks."""
    if not text:
        return False
    if "```" in text or "code" in text.lower():
        return True

    # Heuristics for high-signal technical content
    high_signal_patterns = [
        r"\bselector\b",
        r"\bcss\b",
        r"\bxpath\b",
        r"\bplaywright\b",
        r"\bbutton\b",
        r"\bclick\b",
        r"\bfill\b",
        r"\bpress\b",
        r"\bassert\b",
        r"\bverify\b",
        r"\btestid\b",
        r"\bdata-testid\b",
        r"\bid\s*=\s*",
        r"\bclass\s*=\s*",
        r"use\s+selector",
        r"p-dropdown",
        r"p-select",
    ]
    for pattern in high_signal_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


class JiraACNegotiator:
    """Service handling the AC negotiation loop."""

    def __init__(self, ticket_id: str, run_id: str, dry_run: bool = False):
        self.ticket_id = ticket_id
        self.run_id = run_id
        self.dry_run = dry_run
        self.pending_comments: list[str] = []

    async def _post_or_queue(self, comment: str) -> None:
        """Post comment to Jira immediately, or queue it for user confirmation in dry_run mode."""
        if self.dry_run:
            self.pending_comments.append(comment)
        else:
            await post_jira_comment(self.ticket_id, comment)

    async def fetch_and_gate_ac(self) -> tuple[Optional[JiraTicketContext], Optional[ACQualityResult]]:
        """
        Fetch the ticket and run the AC Quality Gate.
        Rejects ambiguous ACs *before* the planner receives them.
        Enriches the ticket context description with high-signal comments (e.g. BDD hints, selectors).
        """
        try:
            ticket_ctx = await fetch_ticket_context(self.ticket_id)
        except Exception as e:
            logger.error("[%s] Negotiator failed to fetch ticket: %s", self.run_id, e)
            return None, None

        # Fetch comments and enrich context with high-signal comments
        try:
            comments = await fetch_issue_comments(self.ticket_id)
            high_signal_comments = []
            for c in comments:
                body = c.get("body", "")
                if _is_high_signal_comment(body):
                    high_signal_comments.append(f"Comment by {c.get('author', 'Unknown')}:\n{body}")

            if high_signal_comments:
                comments_text = "\n\n=== High-Signal Comments ===\n" + "\n---\n".join(high_signal_comments)
                if "description" in ticket_ctx:
                    ticket_ctx["description"] = ticket_ctx["description"] + comments_text
                else:
                    ticket_ctx["description"] = comments_text
                logger.info(
                    "[%s] Enriched ticket %s description with %d high-signal comments",
                    self.run_id,
                    self.ticket_id,
                    len(high_signal_comments)
                )
        except Exception as e:
            logger.warning("[%s] Failed to fetch comments for context enrichment: %s", self.run_id, e)

        raw_ac = ticket_ctx.get("acceptance_criteria", "")
        if not raw_ac:
            raw_ac = ticket_ctx.get("description", "")

        quality_result = score_ac_quality(raw_ac)

        # If POOR, we automatically reject
        if quality_result.quality_grade == "poor":
            logger.warning(
                "[%s] Negotiator rejected AC for %s: %s", self.run_id, self.ticket_id, quality_result.warnings
            )

            rejection_comment = (
                f"vQA Auto-Rejection: The Acceptance Criteria for this ticket is too ambiguous to test.\n"
                f"Quality Score: {quality_result.overall_score}/10 (POOR)\n\n"
                f"Issues found:\n" + "\n".join(f"- {w}" for w in quality_result.warnings) + "\n\n"
                "Please update the AC with specific components and observable outcomes."
            )
            await self._post_or_queue(rejection_comment)
            return ticket_ctx, quality_result

        return ticket_ctx, quality_result

    async def propose_test_plan(self, ticket_ctx: JiraTicketContext, quality_result: ACQualityResult) -> str:
        """
        Generates a Test Plan based on the ACs and posts it to the Jira ticket if it doesn't already exist.
        """
        raw_ac = ticket_ctx.get("acceptance_criteria", "") or ticket_ctx.get("description", "")

        # Stage 1 normalization to formulate the plan
        bdd_plan = await _stage_1_normalize(
            raw_ac, ticket_ctx.get("summary", ""), ticket_ctx.get("description", ""), self.run_id
        )

        # Check existing comments to prevent posting duplicates
        try:
            comments = await fetch_issue_comments(self.ticket_id)
            for c in comments:
                if "vQA Proposed Test Plan:" in c.get("body", ""):
                    logger.info("[%s] vQA Proposed Test Plan already exists in comments on %s. Skipping posting duplicate.", self.run_id, self.ticket_id)
                    return bdd_plan
        except Exception as e:
            logger.warning("[%s] Failed to fetch comments for de-duplication check: %s", self.run_id, e)

        proposal_comment = (
            f"vQA Proposed Test Plan:\n\n"
            f"```gherkin\n{bdd_plan}\n```\n\n"
            f"Quality Grade: {quality_result.quality_grade.upper()} ({quality_result.overall_score}/10)\n"
            f"Please confirm this plan or modify the Acceptance Criteria. If AC is modified, vQA will auto-sync."
        )

        await self._post_or_queue(proposal_comment)
        if not self.dry_run:
            logger.info("[%s] Posted proposed test plan to %s", self.run_id, self.ticket_id)
        else:
            logger.info("[%s] Queued proposed test plan for %s (dry_run)", self.run_id, self.ticket_id)

        return bdd_plan

    async def sync_modified_ac(self, new_ac_text: str, requires_confirmation: bool = False) -> bool:
        """
        Auto-Sync: Updates the Jira card ACs with new negotiated text.
        If requires_confirmation is True, gates the push until user confirms.
        """
        if requires_confirmation:
            logger.info("[%s] Sync requires user confirmation before updating Jira for %s", self.run_id, self.ticket_id)
            return False

        success = await update_ticket_ac(self.ticket_id, new_ac_text)
        if success:
            logger.info("[%s] Auto-synced AC for %s", self.run_id, self.ticket_id)
            sync_comment = "vQA Auto-Sync: The Acceptance Criteria has been updated based on negotiation."
            await self._post_or_queue(sync_comment)
        return success

