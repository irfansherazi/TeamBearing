#!/usr/bin/env python3
"""
vQA — Needle-in-a-Haystack Prompt Limit Diagnostic
====================================================
scripts/test_prompt_limits.py

Tests whether Claude (via AWS Bedrock) can reliably recall information injected
at the START and END of a fully-assembled vQA prompt. Catch two failure modes:

  1. TRUNCATION   — Bedrock silently drops tokens beyond the context window.
  2. LOST-IN-MIDDLE — Claude attends to start/end but ignores the middle
                      (here we inject needles at start AND end to detect this).

Usage
-----
  python scripts/test_prompt_limits.py --ticket VC2-8967
  python scripts/test_prompt_limits.py --ticket VC2-196 --verbose
  python scripts/test_prompt_limits.py --ticket VC2-196 --step 1 --verbose

Prerequisites
-------------
  - AWS credentials configured (same as the main vQA run)
  - vQA backend dependencies installed (boto3, python-dotenv)
  - Run from the vQA project root: ``cd /path/to/vQA && python scripts/test_prompt_limits.py``
"""

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

# ── Add project root to sys.path so backend package imports work ─────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Load .env before importing backend modules that read settings ────────────
try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on env vars directly

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("needle_test")


# ---------------------------------------------------------------------------
# Needle generator
# ---------------------------------------------------------------------------


def _make_needle() -> str:
    """Return a random 8-char alphanumeric token unlikely to appear elsewhere."""
    return uuid.uuid4().hex[:8].upper()


# ---------------------------------------------------------------------------
# Minimal VQAState fixture
# ---------------------------------------------------------------------------


def _build_minimal_state(ticket_id: str, step_idx: int) -> dict:
    """
    Build a minimal VQAState-compatible dict sufficient to call
    ``_build_system_prompt``.

    All non-essential fields are set to empty/zero values to keep the
    prompt as close as possible to a real run WITHOUT a live browser.
    """
    return {
        "run_id": f"needle-test-{uuid.uuid4().hex[:6]}",
        "jira_ticket": {
            "ticket_id": ticket_id,
            "summary": f"Needle test for {ticket_id}",
            "acceptance_criteria": "",
            "acceptance_criteria_steps": [
                "Login to the application",
                "Navigate to Production Orders",
                "Click the first order",
                "Verify the order details panel is visible",
                "Sort the table by Due Date ascending",
            ],
            "description": "Diagnostic run — not a real ticket",
            "override_login_email": "",
            "override_login_password": "",
            "credential_status": "none",
        },
        "role_context": {
            "role_key": "account_executive",
            "role_name": "Account Executive",
            "login_email": "test@example.com",
            "login_password": "TestPass123",
            "constraints": [],
        },
        "target_url": "https://two-test.vcreative.net",
        "ac_step_index": step_idx,
        "ac_steps_completed": [],
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "planner_iteration": 0,
        "retry_count": 0,
        "detailed_execution_log": [],
        "screenshots": [],
        "current_page_url": "https://two-test.vcreative.net/production-orders",
        "current_screenshot_b64": "",
        "current_accessibility_tree": "",
        "planned_action": {},
        "last_error": "",
        "long_term_memory": [],
        "run_memory": {},
        "global_run_context": "",
        "transient_page_text": "",
        "test_plan": None,
        "user_guidance": "",
        "som_element_map": {},
        "_human_guidance_raw_": "",
        "ac_step_failure_diary": [],
        "forbidden_locators": [],
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "action_repeat_counts": {},
    }


# ---------------------------------------------------------------------------
# Main diagnostic
# ---------------------------------------------------------------------------


async def run_needle_test(
    ticket_id: str,
    step_idx: int = 0,
    verbose: bool = False,
) -> bool:
    """
    Run the needle-in-a-haystack test.

    Returns True if the LLM recalled both needles, False otherwise.
    """
    logger.info("=== vQA Needle-in-a-Haystack Diagnostic ===")
    logger.info("Ticket: %s | Step: %d", ticket_id, step_idx + 1)

    # ── Step 1: Build the real assembled system prompt ────────────────────
    try:
        from backend.config import settings
        from backend.engine.planner import _build_system_prompt
    except ImportError as e:
        logger.error("Cannot import backend modules: %s", e)
        logger.error("Run from the vQA project root: cd %s && python scripts/test_prompt_limits.py", _PROJECT_ROOT)
        return False

    state = _build_minimal_state(ticket_id, step_idx)

    logger.info("Building system prompt from vQAState fixture...")
    try:
        system_prompt = _build_system_prompt(state)
    except Exception as e:
        logger.warning("_build_system_prompt raised %s — using minimal placeholder prompt.", e)
        system_prompt = (
            f"You are vQA. Testing ticket {ticket_id}, step {step_idx + 1}. "
            + ("X " * 5000)  # pad with ~10k chars of filler
        )

    prompt_len = len(system_prompt)
    logger.info("Assembled system prompt: %d chars (~%d tokens)", prompt_len, prompt_len // 4)

    # ── Step 2: Inject two unique needles ─────────────────────────────────
    needle_start = _make_needle()
    needle_end = _make_needle()

    needle_start_block = (
        f"\n\n[DIAGNOSTIC_START_NEEDLE: {needle_start}]\n"
        f"Remember this token — you will be asked to recall it: NEEDLE_START={needle_start}\n"
        f"[END_DIAGNOSTIC_START_NEEDLE]\n\n"
    )
    needle_end_block = (
        f"\n\n[DIAGNOSTIC_END_NEEDLE: {needle_end}]\n"
        f"Remember this token — you will be asked to recall it: NEEDLE_END={needle_end}\n"
        f"[END_DIAGNOSTIC_END_NEEDLE]\n"
    )

    # Prepend start needle, append end needle
    instrumented_prompt = needle_start_block + system_prompt + needle_end_block

    # ── Step 3: Build the diagnostic user message ─────────────────────────
    diagnostic_question = (
        "DIAGNOSTIC QUESTION (answer this FIRST before any tool call):\n"
        "I injected two needle tokens into this prompt.\n"
        "What is the NEEDLE_START token? (it was near the very beginning)\n"
        "What is the NEEDLE_END token? (it was near the very end)\n"
        "Reply in this exact format:\n"
        "NEEDLE_START_RECALLED: <token>\n"
        "NEEDLE_END_RECALLED: <token>\n"
        "\nIf you cannot find a needle, write NEEDLE_X_RECALLED: NOT_FOUND\n"
    )

    instrumented_len = len(instrumented_prompt)
    logger.info(
        "Instrumented prompt: %d chars (~%d tokens) | NEEDLE_START=%s | NEEDLE_END=%s",
        instrumented_len,
        instrumented_len // 4,
        needle_start,
        needle_end,
    )

    if verbose:
        logger.info("--- Prompt preview (first 500 chars) ---")
        logger.info(instrumented_prompt[:500])
        logger.info("--- Prompt preview (last 500 chars) ---")
        logger.info(instrumented_prompt[-500:])

    # ── Step 4: Call Bedrock ──────────────────────────────────────────────
    import boto3

    logger.info("Calling Bedrock model: %s", settings.bedrock_model_id)
    bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_bedrock_region)

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: bedrock.converse(
                modelId=settings.bedrock_model_id,
                system=[{"text": instrumented_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": diagnostic_question}],
                    }
                ],
                inferenceConfig={
                    "maxTokens": 256,
                    "temperature": 0.0,
                },
            ),
        )
    except Exception as e:
        logger.error("Bedrock API call failed: %s", e)
        return False

    # ── Step 5: Parse recalled tokens ─────────────────────────────────────
    output_text = ""
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            output_text += block["text"]

    logger.info("Claude's response:\n%s", output_text)

    start_recalled = "NOT_FOUND"
    end_recalled = "NOT_FOUND"

    for line in output_text.splitlines():
        line = line.strip()
        if line.startswith("NEEDLE_START_RECALLED:"):
            start_recalled = line.split(":", 1)[1].strip()
        elif line.startswith("NEEDLE_END_RECALLED:"):
            end_recalled = line.split(":", 1)[1].strip()

    # ── Step 6: Report results ─────────────────────────────────────────────
    start_ok = start_recalled.upper() == needle_start.upper()
    end_ok = end_recalled.upper() == needle_end.upper()

    logger.info("")
    logger.info("=== NEEDLE TEST RESULTS ===")
    logger.info("Prompt length : %d chars (%d tokens approx.)", instrumented_len, instrumented_len // 4)
    logger.info(
        "NEEDLE_START  : expected=%s | recalled=%s | %s",
        needle_start,
        start_recalled,
        "✓ PASS" if start_ok else "✗ FAIL",
    )
    logger.info(
        "NEEDLE_END    : expected=%s | recalled=%s | %s", needle_end, end_recalled, "✓ PASS" if end_ok else "✗ FAIL"
    )

    if start_ok and end_ok:
        logger.info("RESULT: ✓ PASS — Both needles recalled. Prompt is within context window.")
    elif not start_ok and end_ok:
        logger.warning(
            "RESULT: ✗ PARTIAL FAIL — NEEDLE_START not recalled.\n"
            "  Diagnososis: 'Lost in the middle' syndrome OR start was truncated.\n"
            "  The model attends to the END but misses the START.\n"
            "  Fix: Move critical instructions to the END of the prompt (recency effect)."
        )
    elif start_ok and not end_ok:
        logger.warning(
            "RESULT: ✗ PARTIAL FAIL — NEEDLE_END not recalled.\n"
            "  Diagnososis: Prompt truncation at the end (context window overflow).\n"
            "  Fix: Reduce total prompt length below the model's token limit."
        )
    else:
        logger.error(
            "RESULT: ✗ FULL FAIL — Neither needle recalled.\n"
            "  Diagnososis: Severe truncation OR model did not process the system prompt.\n"
            "  Check AWS Bedrock region, model ID, and prompt length."
        )

    logger.info("===========================")

    return start_ok and end_ok


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="vQA Needle-in-a-Haystack Prompt Limit Diagnostic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ticket",
        required=True,
        help="Jira ticket ID to use when assembling the prompt (e.g. VC2-196).",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=1,
        help="1-based AC step index to use for prompt assembly (default: 1).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print first/last 500 chars of the instrumented prompt.",
    )
    args = parser.parse_args()

    passed = asyncio.run(
        run_needle_test(
            ticket_id=args.ticket,
            step_idx=args.step - 1,  # Convert to 0-based
            verbose=args.verbose,
        )
    )
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
