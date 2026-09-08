"""
vQA — Critic Pass LLM Evaluator Node
=====================================
Module: backend/engine/critic_node.py

Implements the **Critic Pass LLM Evaluator** — a new LangGraph node that fires
between ``ac_parser`` and ``setup_role`` on every AI-mode run.

The critic re-reads the raw AC text + compiled TestPlan with a cheap Haiku model
and emits a structured CriticVerdict. On ``verdict="mismatch"``, it routes back
to ``ac_parser`` with structured feedback for up to ``max_critic_retries`` cycles.
On ``verdict="pass"`` (or API error/feature disabled), it routes to ``setup_role``.

Design Decisions
----------------
See ``memory-bank/creative/critic-pass-llm-evaluator-architecture.md``:

  Q1 verdict schema: flat Literal[...] reason_codes + peer feedback_summary field.
  Q2 feedback grammar: HumanMessage in 2-turn conversation (preserves Bedrock prompt cache).
  Q3 retry counter: per-run retry_count on CriticVerdict (matches existing pattern).
  Q4 pipeline placement: ac_parser → critic → setup_role (role_name from ROLE_REGISTRY).

Nodes exported
--------------
  critic_node(state)       — async LangGraph node function.
  route_after_critic(state) — conditional-edge routing function.

See Also
--------
  - backend/engine/schemas.py   — CriticVerdict Pydantic model
  - backend/engine/state.py     — critic_result / critic_feedback VQAState fields
  - backend/engine/graph.py     — node registration + conditional edges (Phase 2)
  - backend/config.py           — critic_enabled, max_critic_retries, bedrock_model_id_critic
"""

import json
import logging
from typing import Any

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from backend.config import settings
from backend.engine.schemas import CriticVerdict
from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Synthetic pass (used on API error or when feature is disabled)
# ---------------------------------------------------------------------------

_SYNTHETIC_PASS: dict = {
    "verdict": "pass",
    "reason_codes": [],
    "feedback_summary": "",
    "retry_count": 0,
    "critic_skipped": True,
}


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def _get_critic_llm() -> ChatBedrockConverse:
    """
    Return a Haiku LLM client for the critic node.

    Uses ``settings.bedrock_model_id_critic`` (default: Haiku 4.5) with a
    small token budget — the critic emits a short structured verdict, not prose.
    Temperature 0 for deterministic evaluation.
    """
    return ChatBedrockConverse(
        model=settings.bedrock_model_id_critic,
        region_name=settings.aws_bedrock_region,
        max_tokens=200,
        temperature=0,
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_CRITIC_SYSTEM_PROMPT = """\
You are a QA plan auditor. Your job is to compare a compiled TestPlan against the \
original Acceptance Criteria (AC) and detect drift before browser execution begins.

Emit a JSON object with this exact shape:
{{
  "verdict": "pass" | "mismatch",
  "reason_codes": [ ... ],
  "feedback_summary": "..."
}}

verdict:
  "pass"     — The TestPlan faithfully covers all AC steps with no hallucinated \
steps or persona errors.
  "mismatch" — One or more discrepancies detected.

reason_codes (array, any subset, empty on pass):
  "missing_step"     — A step present in the AC has no goal-matching entry in the \
TestPlan.
  "hallucinated_ac"  — A TestPlan step has no traceable origin in the AC text.
  "persona_mismatch" — A step's target_persona contradicts the expected role \
({expected_role_name}).
  "order_violation"  — Steps are in a different order than the AC specifies.
  "ambiguous_step"   — A TestPlan step is so vague that test execution cannot \
succeed deterministically.

feedback_summary:
  On mismatch: one paragraph quoting the specific AC text and the discrepant \
TestPlan step, so the parser can fix it.
  On pass: empty string "".

Respond ONLY with the JSON object — no markdown, no prose before or after it.\
"""


def _build_critic_prompt(
    acceptance_criteria_steps: list[str],
    test_plan: dict,
    expected_role_name: str,
) -> tuple[str, str]:
    """
    Build the system prompt and user message text for the Haiku critic call.

    Returns (system_prompt, user_message_text).
    """
    system_prompt = _CRITIC_SYSTEM_PROMPT.format(
        expected_role_name=expected_role_name,
    )

    # Compact TestPlan summary — step goals + target_persona.
    # We do NOT send the full TestPlan dict (too many tokens);
    # the critic only needs goals and personas to detect drift.
    steps = test_plan.get("steps", [])
    steps_summary = "\n".join(
        f"  [{i + 1}] goal={s.get('goal', '?')!r}  persona={s.get('target_persona', '?')!r}"
        for i, s in enumerate(steps)
    )

    ac_text = "\n".join(
        f"  [{i + 1}] {step}" for i, step in enumerate(acceptance_criteria_steps)
    )

    user_message = (
        f"ACCEPTANCE CRITERIA STEPS:\n{ac_text}\n\n"
        f"COMPILED TEST PLAN STEPS:\n{steps_summary}\n\n"
        "Audit the TestPlan against the AC and emit the verdict JSON."
    )
    return system_prompt, user_message


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def _parse_critic_response(response: Any, previous_retry_count: int) -> CriticVerdict:
    """
    Parse the Haiku LLM response into a validated CriticVerdict.

    Raises ValidationError if the response cannot be mapped to a valid verdict
    (the caller's try/except converts this to a synthetic pass per AC-ERROR-1).
    """
    raw_text = response.content if isinstance(response.content, str) else str(response.content)
    raw_text = raw_text.strip()

    # Strip markdown code fences if the model wrapped the JSON
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    payload = json.loads(raw_text)

    # Clamp retry_count from the payload — we manage it ourselves
    # (the LLM should not increment the counter; we do that below).
    payload.pop("retry_count", None)

    verdict = CriticVerdict.model_validate(payload)
    return verdict


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------


async def critic_node(state: VQAState) -> dict:
    """
    LangGraph node: Critic Pass LLM Evaluator.

    Fires between ``ac_parser`` and ``setup_role`` on every AI-mode run.
    Returns a partial VQAState update with ``critic_result`` (and optionally
    ``critic_feedback`` when verdict="mismatch" and retries remain).

    Routing is handled by ``route_after_critic`` — this node only writes state.

    Failure handling (AC-ERROR-1):
      Any exception (Bedrock error, JSON parse error, ValidationError) is caught
      and returned as a synthetic pass with critic_skipped=True. The run continues.
    """
    run_id = state.get("run_id", "unknown")

    # ── Feature flag ────────────────────────────────────────────────────────
    if not settings.critic_enabled:
        logger.debug("[%s] critic_node: feature disabled — returning synthetic pass", run_id)
        return {"critic_result": dict(_SYNTHETIC_PASS), "critic_feedback": None}

    # ── Static Playwright bypass ─────────────────────────────────────────────
    # Static runs do not produce a TestPlan via ac_parser; the critic has no
    # plan to evaluate. Route directly to setup_role (same as pre-critic behavior).
    execution_engine = state.get("execution_engine", "ai")
    if execution_engine == "static":
        logger.debug(
            "[%s] critic_node: static execution — bypassing critic (no TestPlan)", run_id
        )
        return {"critic_result": dict(_SYNTHETIC_PASS), "critic_feedback": None}

    test_plan = state.get("test_plan")
    acceptance_criteria_steps = state.get("acceptance_criteria_steps") or []

    # ── Guard: no test_plan → synthetic pass (cannot evaluate) ──────────────
    if not test_plan:
        logger.warning(
            "[%s] critic_node: test_plan is None — cannot evaluate, returning synthetic pass",
            run_id,
        )
        return {"critic_result": dict(_SYNTHETIC_PASS), "critic_feedback": None}

    # ── Derive expected role name from ROLE_REGISTRY ─────────────────────────
    # Per creative decision Q4: role_key available in initial state via role_queue[0].
    # ROLE_REGISTRY lookup gives role_name for persona_mismatch validation at position A
    # (before setup_role fires) — no login cost needed.
    try:
        from backend.engine.roles import ROLE_REGISTRY  # lazy import to avoid circular

        role_queue = state.get("role_queue") or []
        role_key = role_queue[0] if role_queue else "account_executive"
        expected_role_name = ROLE_REGISTRY.get(role_key, {}).get("role_name", role_key)
    except Exception as exc:
        logger.warning("[%s] critic_node: ROLE_REGISTRY lookup failed (%s) — using role_key", run_id, exc)
        expected_role_name = (state.get("role_queue") or ["account_executive"])[0]

    # ── Determine current retry_count from previous critic_result ────────────
    previous_critic = state.get("critic_result") or {}
    current_retry_count = previous_critic.get("retry_count", 0)

    logger.info(
        "[%s] critic_node: evaluating TestPlan (%d steps) against AC (%d steps) "
        "— role=%s retry=%d",
        run_id,
        len(test_plan.get("steps", [])),
        len(acceptance_criteria_steps),
        expected_role_name,
        current_retry_count,
    )

    # ── Build prompt ─────────────────────────────────────────────────────────
    system_prompt, user_message = _build_critic_prompt(
        acceptance_criteria_steps=acceptance_criteria_steps,
        test_plan=test_plan,
        expected_role_name=expected_role_name,
    )

    # ── Invoke Haiku ─────────────────────────────────────────────────────────
    try:
        llm = _get_critic_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        response = await llm.ainvoke(messages)
        verdict = _parse_critic_response(response, current_retry_count)

    except Exception as exc:
        exc_type = type(exc).__name__
        logger.warning(
            "[%s] critic_node: Haiku call failed (%s: %s) — critic skipped, routing to setup_role",
            run_id,
            exc_type,
            exc,
        )
        return {"critic_result": dict(_SYNTHETIC_PASS), "critic_feedback": None}

    # ── Write verdict to state ───────────────────────────────────────────────
    verdict_dict = verdict.model_dump()

    if verdict.verdict == "pass":
        logger.info(
            "[%s] critic_node: verdict=pass reason_codes=%s retry=%d",
            run_id,
            verdict.reason_codes,
            current_retry_count,
        )
        verdict_dict["retry_count"] = current_retry_count
        return {"critic_result": verdict_dict, "critic_feedback": None}

    # verdict == "mismatch"
    next_retry_count = current_retry_count + 1
    verdict_dict["retry_count"] = next_retry_count

    if current_retry_count >= settings.max_critic_retries:
        # Retry cap exhausted — proceed with imperfect plan (AC-VERIFY-5)
        logger.warning(
            "[%s] critic_node: max retries exhausted (retry_count=%d) — proceeding with imperfect plan "
            "reason_codes=%s",
            run_id,
            current_retry_count,
            verdict.reason_codes,
        )
        return {"critic_result": verdict_dict, "critic_feedback": None}

    # Retries remain — set critic_feedback for ac_parser (AC-VERIFY-4)
    critic_feedback = {
        "reason_codes": verdict.reason_codes,
        "guidance": verdict.feedback_summary,
    }
    logger.info(
        "[%s] critic_node: verdict=mismatch reason_codes=%s retry=%d→%d — routing to ac_parser",
        run_id,
        verdict.reason_codes,
        current_retry_count,
        next_retry_count,
    )

    # AC-ASYNC-1: broadcast critic_mismatch event over WebSocket within 500 ms.
    # Non-fatal — failure to broadcast does not abort the run.
    await _broadcast_critic_mismatch(
        run_id=run_id,
        retry_count=next_retry_count,
        reason_codes=verdict.reason_codes,
    )

    return {"critic_result": verdict_dict, "critic_feedback": critic_feedback}


# ---------------------------------------------------------------------------
# WebSocket broadcast (AC-ASYNC-1)
# ---------------------------------------------------------------------------


async def _broadcast_critic_mismatch(
    run_id: str,
    retry_count: int,
    reason_codes: list[str],
) -> None:
    """
    Broadcast a critic_mismatch event over WebSocket to all connected clients.

    Non-fatal: any exception is logged at DEBUG and swallowed so the run continues.
    Uses lazy import of _ws_connections from routes.py to avoid circular import
    (same pattern as persona_switch_node.broadcast_ws_message).

    Emits within ~0ms of being called (in-process async send) — well within the
    500ms SLA required by AC-ASYNC-1.
    """
    import json as _json

    msg = {
        "event_type": "critic_mismatch",
        "run_id": run_id,
        "retry_count": retry_count,
        "reason_codes": reason_codes,
    }
    try:
        from backend.api.routes import _ws_connections  # lazy import — avoid circular

        connections = _ws_connections.get(run_id, [])
        if not connections:
            return
        msg_json = _json.dumps(msg)
        disconnected = []
        for ws in connections:
            try:
                await ws.send_text(msg_json)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            if ws in connections:
                connections.remove(ws)
    except Exception as exc:
        logger.debug(
            "[%s] critic_node: _broadcast_critic_mismatch failed (non-fatal): %s", run_id, exc
        )


# ---------------------------------------------------------------------------
# Conditional-edge routing function
# ---------------------------------------------------------------------------


def route_after_critic(state: VQAState) -> str:
    """
    LangGraph conditional-edge function for the critic node.

    Routing table (AC-VERIFY-3, AC-VERIFY-4, AC-VERIFY-5):
      - verdict="pass"                        → "setup_role"
      - verdict="mismatch" + retry_count < 2  → "ac_parser"  (feedback already in state)
      - verdict="mismatch" + retry_count >= 2 → "setup_role" (exhausted — proceed anyway)
      - critic_skipped=True                   → "setup_role" (API error path, AC-ERROR-1)

    NOTE: The retry_count in critic_result is the count AFTER the current mismatch
    (incremented by critic_node). So retry_count=1 means "one retry has been scheduled;
    max_critic_retries=2 — one more attempt available".
    """
    critic_result = state.get("critic_result") or {}

    verdict = critic_result.get("verdict", "pass")
    retry_count = critic_result.get("retry_count", 0)
    critic_skipped = critic_result.get("critic_skipped", False)

    if critic_skipped:
        return "setup_role"

    if verdict == "pass":
        return "setup_role"

    # verdict == "mismatch"
    max_retries = getattr(settings, "max_critic_retries", 2)
    if retry_count < max_retries:
        return "ac_parser"

    return "setup_role"
