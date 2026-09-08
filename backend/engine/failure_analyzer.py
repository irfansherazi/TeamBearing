"""
vQA — Failure Analyzer
========================
Module: backend/engine/failure_analyzer.py

When a test run fails, this module performs a second LLM pass to
classify WHY it failed.  The result helps the product team distinguish
between two root causes:

  Product Bug       — The application code doesn't match the Jira AC
                      (e.g. a button is missing, a toast doesn't appear).

  Agent Issue       — The Jira card is ambiguous/incomplete, causing the
                      agent to misinterpret what to test.

The analyzer:
1. Takes the full execution log, AC steps, and last screenshot.
2. Summarises what the agent DID vs what the AC EXPECTED.
3. Calls the Claude LLM (via Bedrock) to classify each failed AC step.
4. Returns a ``FailureAnalysis`` dict that the reporter embeds in
   the HTML report and posts to Jira as a comment.

Architecture
------------
  reporter_node (reporter.py)
      └─▶ run_failure_analysis()   ← this module
              └─▶ Bedrock / Claude  (async, ≤5s budget)

The analysis is best-effort: if the LLM call fails or times out it
returns a graceful fallback rather than crashing the run.
"""

import json
import logging
import re
from typing import TypedDict

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class Lesson(TypedDict):
    diagnosis: str
    suggestion: str
    suggested_selector: str
    confidence: float


class StepClassification(TypedDict):
    ac_step: str  # The original AC step text
    ac_index: int  # 0-based index
    classification: str  # "product_bug" | "agent_issue" | "passed"
    confidence: str  # "high" | "medium" | "low"
    reason: str  # 1-2 sentence explanation
    visual_observation: str  # LLM vision summary of the state
    lesson: Lesson | None  # Actionable self-healing feedback


class FailureAnalysis(TypedDict):
    overall: str  # "product_bug" | "agent_issue" | "mixed" | "unknown"
    summary: str  # 2-3 sentence executive summary for the product team
    steps: list[StepClassification]
    jira_comment: str  # Pre-formatted Atlassian wiki-markup comment
    error_context: dict | None  # JSON-safe structured failure context


_FALLBACK: FailureAnalysis = {
    "overall": "unknown",
    "summary": "Automated triage was unable to classify this failure. Please review the execution log manually.",
    "steps": [],
    "jira_comment": "",
    "error_context": None,
}


# Regex fallbacks for when the LLM returns near-valid JSON but chokes on an
# embedded control char, unescaped newline in a string, or trailing garbage
# that `_repair_json` cannot rescue. These extract just the top-level scalar
# fields so the reporter can show a real verdict + summary instead of
# "overall=unknown". Kept intentionally conservative — DOTALL so `.` crosses
# newlines inside quoted strings; the value is trimmed to a safe length.
_OVERALL_RE = re.compile(r'"overall"\s*:\s*"([^"]{1,64})"')
_SUMMARY_RE = re.compile(r'"summary"\s*:\s*"((?:[^"\\]|\\.){0,2000})"', re.DOTALL)


def _extract_partial(raw: str) -> tuple[str, str]:
    """Best-effort extraction of overall + summary from malformed LLM JSON.

    Returns ("", "") when nothing usable is found so the caller falls back
    to the generic ``_FALLBACK``.
    """
    if not raw:
        return "", ""
    overall = ""
    m_overall = _OVERALL_RE.search(raw)
    if m_overall:
        candidate = m_overall.group(1).strip()
        if candidate in ("product_bug", "agent_issue", "mixed", "unknown"):
            overall = candidate

    summary = ""
    m_summary = _SUMMARY_RE.search(raw)
    if m_summary:
        # Decode the captured JSON string manually via json.loads on a wrapped
        # value so escape sequences (\n, \", \\) are handled correctly.
        try:
            summary = json.loads('"' + m_summary.group(1) + '"')
        except json.JSONDecodeError:
            summary = m_summary.group(1)
        summary = summary.strip()

    return overall, summary


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------


def _build_prompt(state: VQAState) -> str:
    ticket = state.get("jira_ticket", {})
    ac_steps: list[str] = ticket.get("acceptance_criteria_steps", [])
    completed: list[int] = state.get("ac_steps_completed", [])
    log = state.get("detailed_execution_log", [])
    role_name = state.get("role_context", {}).get("role_name", "Unknown")
    ticket_id = ticket.get("ticket_id", "?")
    ticket_summary = ticket.get("summary", "")
    ticket_description = ticket.get("description", "")[:1500]  # cap for tokens

    failed_indices = [i for i in range(len(ac_steps)) if i not in completed]

    # Build a concise execution summary for context
    step_summaries = []
    for step in log:
        action = step.get("action_type", "?")
        success = "✓" if step.get("success") else "✗"
        reasoning = step.get("reasoning", "")[:200]
        error = step.get("error_message", "")
        line = f"  [{success}] {action}"
        if error:
            line += f" — ERROR: {error[:120]}"
        if reasoning:
            line += f"\n       Reasoning: {reasoning}"
        step_summaries.append(line)

    steps_text = "\n".join(step_summaries) if step_summaries else "  (no steps recorded)"
    ac_list = "\n".join(
        f"  {i + 1}. [{('PASSED' if i in completed else 'FAILED')}] {s}" for i, s in enumerate(ac_steps)
    )
    failed_list = "\n".join(f"  Step {i + 1}: {ac_steps[i]}" for i in failed_indices if i < len(ac_steps))

    return f"""You are a senior QA engineer performing post-mortem triage on an automated test failure.

## Jira Ticket
ID: {ticket_id}
Summary: {ticket_summary}
Description:
{ticket_description}

## Role Under Test
{role_name}

## Acceptance Criteria (with pass/fail status)
{ac_list}

## Failed Steps
{failed_list}

## What the Agent Did (execution log)
{steps_text}

## Your Task
For EACH FAILED AC step, classify the root cause and provide actionable feedback for self-healing.
Classifications:
- "product_bug"   — The application itself doesn't behave as specified in the AC.
- "agent_issue"   — The agent misunderstood or couldn't interpret the AC step (AC is vague, selector issues, etc.)

Respond ONLY with a valid JSON object in this exact schema:
{{
  "overall": "<product_bug | agent_issue | mixed | unknown>",
  "summary": "<2-3 sentences executive summary>",
  "steps": [
    {{
      "ac_index": <0-based int>,
      "ac_step": "<exact AC step text>",
      "classification": "<product_bug | agent_issue | passed>",
      "confidence": "<high | medium | low>",
      "reason": "<1-2 sentences explaining why>",
      "visual_observation": "<Brief summary of the UI state at time of failure>",
      "lesson": {{
        "diagnosis": "<Detailed technical diagnosis of why the step failed>",
        "suggestion": "<Actionable fix: e.g. use a different selector, wait for an element, etc.>",
        "suggested_selector": "<A specific Playwright-style selector if applicable, else empty string>",
        "confidence": <float between 0.0 and 1.0>
      }}
    }}
  ]
}}

Include ONLY failed steps in the "steps" array.
Be precise. Respond with JSON only."""


async def run_failure_analysis(state: VQAState) -> FailureAnalysis:
    """
    Run the failure analysis LLM pass for a failed test run.

    This is called from ``reporter_node`` only when ``all_passed`` is False.
    The analysis is best-effort — any exception returns a fallback dict.

    Delegates to the centralized ``get_llm()`` factory from ``backend.llm``.

    Args
    ----
    state : VQAState
        The final graph state after the run completed.

    Returns
    -------
    FailureAnalysis
        Structured dict with overall classification, per-step breakdown,
        and a pre-formatted Jira comment.
    """
    run_id = state.get("run_id", "?")
    ticket_id = state.get("jira_ticket", {}).get("ticket_id", "?")
    logger.info("[%s] Running failure analysis for %s...", run_id, ticket_id)

    raw_content = ""
    try:
        prompt = _build_prompt(state)

        # MIGRATION: use centralized get_llm instead of raw boto3 invoke_model
        from langchain_core.messages import HumanMessage as _HM

        from backend.llm import get_llm

        llm = get_llm("failure_analyzer")
        response = await llm.ainvoke([_HM(content=prompt)])
        raw_content = (response.content or "").strip()

        from backend.engine.ac_parser import _repair_json

        content = _repair_json(raw_content)

        parsed: dict = json.loads(content)

        # Validate and coerce
        overall = parsed.get("overall", "unknown")
        if overall not in ("product_bug", "agent_issue", "mixed", "unknown"):
            overall = "unknown"

        steps: list[StepClassification] = []
        for s in parsed.get("steps", []):
            cls = s.get("classification", "unknown")
            if cls not in ("product_bug", "agent_issue", "passed"):
                cls = "unknown"

            lesson_raw = s.get("lesson")
            lesson: Lesson | None = None
            if lesson_raw and isinstance(lesson_raw, dict):
                lesson = {
                    "diagnosis": str(lesson_raw.get("diagnosis", "")),
                    "suggestion": str(lesson_raw.get("suggestion", "")),
                    "suggested_selector": str(lesson_raw.get("suggested_selector", "")),
                    "confidence": float(lesson_raw.get("confidence", 0.0)),
                }

            steps.append(
                {
                    "ac_index": int(s.get("ac_index", 0)),
                    "ac_step": str(s.get("ac_step", "")),
                    "classification": cls,
                    "confidence": s.get("confidence", "low"),
                    "reason": str(s.get("reason", "")),
                    "visual_observation": str(s.get("visual_observation", "")),
                    "lesson": lesson,
                }
            )

        summary = str(parsed.get("summary", ""))
        jira_comment = _build_jira_comment(state, overall, summary, steps)

        # Build structured error context for self-healing (Phase 3 persistence)
        error_context = {
            "run_id": run_id,
            "ticket": ticket_id,
            "overall_classification": overall,
            "failed_steps": [
                {
                    "index": s["ac_index"],
                    "text": s["ac_step"],
                    "visual_observation": s["visual_observation"],
                    "lesson": s["lesson"],
                }
                for s in steps
            ],
        }

        result: FailureAnalysis = {
            "overall": overall,
            "summary": summary,
            "steps": steps,
            "jira_comment": jira_comment,
            "error_context": error_context,
        }

        logger.info(
            "[%s] Failure analysis complete: overall=%s, %d step(s) classified",
            run_id,
            overall,
            len(steps),
        )
        return result

    except Exception as exc:
        logger.error("[%s] Failure analysis error: %s", run_id, exc)
        overall_partial, summary_partial = _extract_partial(raw_content)
        if overall_partial or summary_partial:
            logger.warning(
                "[%s] Failure analysis: JSON parse failed but recovered "
                "partial fields (overall=%r, summary_len=%d) via regex fallback",
                run_id,
                overall_partial or "unknown",
                len(summary_partial),
            )
            partial: FailureAnalysis = {
                "overall": overall_partial or "unknown",
                "summary": (
                    summary_partial
                    or "Automated triage returned malformed JSON; partial fields recovered."
                ),
                "steps": [],
                "jira_comment": _build_jira_comment(
                    state,
                    overall_partial or "unknown",
                    summary_partial or "",
                    [],
                ),
                "error_context": {
                    "run_id": run_id,
                    "parse_error": str(exc)[:200],
                    "recovered_via": "regex_partial",
                },
            }
            return partial
        return _FALLBACK


# ---------------------------------------------------------------------------
# Jira comment builder
# ---------------------------------------------------------------------------


_ICON = {
    "product_bug": "🐛",
    "agent_issue": "📝",
    "mixed": "⚠️",
    "unknown": "❓",
    "passed": "✅",
}

_LABEL = {
    "product_bug": "Product Bug",
    "agent_issue": "Jira Card Unclear",
    "mixed": "Mixed",
    "unknown": "Unknown",
    "passed": "Passed",
}


def _build_jira_comment(
    state: VQAState,
    overall: str,
    summary: str,
    steps: list[StepClassification],
) -> str:
    """Build an Atlassian wiki-markup comment for posting to Jira."""
    ticket_id = state.get("jira_ticket", {}).get("ticket_id", "?")
    role_name = state.get("role_context", {}).get("role_name", "Unknown")
    run_id = state.get("run_id", "?")
    report_url = state.get("s3_report_url", "")

    icon = _ICON.get(overall, "❓")
    label = _LABEL.get(overall, "Unknown")

    lines = [
        f"h3. {icon} vQA Automated Test Failure — {label}",
        "",
        f"*Ticket:* {ticket_id}  |  *Role:* {role_name}  |  *Run:* {run_id}",
        "",
        f"*Summary:* {summary}",
        "",
        "h4. Failed Step Analysis",
        "",
        "|| Step || AC Criteria || Classification || Reason ||",
    ]

    for s in steps:
        step_num = s["ac_index"] + 1
        cls = s["classification"]
        cls_label = f"{_ICON.get(cls, '?')} {_LABEL.get(cls, cls)}"
        reason = s["reason"].replace("|", "\\|")
        ac_text = s["ac_step"][:120].replace("|", "\\|")

        # Add actionable lesson if available
        lesson = s.get("lesson")
        if lesson and lesson.get("diagnosis"):
            reason += f" \\\\ *Diagnosis:* {lesson['diagnosis']} \\\\ *Suggestion:* {lesson['suggestion']}"
            if lesson.get("suggested_selector"):
                reason += f" \\\\ *Code:* {{code}}{lesson['suggested_selector']}{{code}}"

        lines.append(f"| {step_num} | {ac_text} | {cls_label} | {reason} |")

    lines += [
        "",
        "----",
        "_Generated by vQA Autonomous Agent_",
    ]

    if report_url:
        lines.append(f"[Full Report|{report_url}]")

    return "\n".join(lines)
