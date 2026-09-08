"""
vQA — LLM-as-a-Judge Verifier Node
=====================================
Module: backend/engine/verifier_node.py

Implements the **Verifier** phase of the orchestrator pipeline.  After the
Surfer executes a browser instruction, the Verifier acts as an impartial
judge: it compares what the Acceptance Criteria *requires* against what the
browser *actually produced*, and delivers a structured, auditable verdict.

Architecture
------------
::

    Surfer → BrowserResult
                  │
                  ▼
    verifier_node(state: OrchestratorState)
         │   ┌───────────────────────────────────────────────────────┐
         │   │  Input context fed to Claude 3.5 Sonnet:              │
         │   │   • ac_step        — what was supposed to happen       │
         │   │   • final_url      — where the browser ended up        │
         │   │   • extracted_text — visible text captured by Surfer   │
         │   │   • steps_taken    — how many agent steps ran          │
         │   │   • error_message  — any browser-use error string      │
         │   └───────────────────────────────────────────────────────┘
         │              │
         │      ChatBedrockConverse (structured output)
         │              │
         │       VerificationResult (Pydantic v2)
         │         • thought_process: str   — chain-of-thought reasoning
         │         • is_verified:    bool   — AC met? True / False
         │         • failure_reason: str    — empty when is_verified=True
         │
         ├─ is_verified=True  → _route = "memory_log"  → END
         └─ is_verified=False → error_log ← failure_reason
                                _route = "debugger"

Structured Output Strategy
---------------------------
Claude 3.5 Sonnet is instructed via a tight system prompt to return a
JSON object matching ``VerificationResult``.  The raw response is parsed
with ``VerificationResult.model_validate_json()``.  A fallback regex path
handles rare cases where the LLM wraps the JSON in markdown fences.

If the LLM call fails entirely (network / quota error), the verifier
defaults to ``is_verified=False`` with ``failure_reason`` set to the
exception string, routing to the Debugger for triage.

Retry Budget
------------
The verifier does not retry the browser task — that is the Debugger's
responsibility.  It simply judges the *current* BrowserResult and routes
accordingly.

Public API
----------
    from backend.engine.verifier_node import verifier_node, VerificationResult

    # As a LangGraph node (primary usage):
    result_patch = await verifier_node(state)

    # Standalone for testing:
    verification = await _call_llm_judge(
        ac_step="Verify 'New Request +' button is visible",
        final_url="https://two-test.vcreative.net/dashboard",
        extracted_text="New Request + button visible in toolbar",
        error_message="",
        steps_taken=3,
        run_id="test-001",
    )
    assert verification.is_verified is True

Configuration (env / .env)
---------------------------
    VERIFIER_MODEL_ID   Bedrock model (default: same as ORCHESTRATOR_MODEL_ID)
    AWS_BEDROCK_REGION  Bedrock region (default: us-west-2)
    VERIFIER_MAX_TOKENS Maximum tokens in the judge response (default: 1024)

Dependencies
------------
    pydantic>=2.7.0,<3.0.0         (already in requirements.txt)
    langchain-aws>=0.2.0,<1.0.0   (already in requirements.txt)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional-import guards
# ---------------------------------------------------------------------------
try:
    from langchain_aws import ChatBedrockConverse
    from langchain_core.messages import HumanMessage, SystemMessage

    _LANGCHAIN_AWS_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    _LANGCHAIN_AWS_AVAILABLE = False
    logger.warning("verifier_node: langchain-aws not installed (%s)", _e)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Maximum characters of extracted_text fed to the judge.
# Browser-use can capture very long pages; we cap here to avoid prompt bloat.
_MAX_EXTRACTED_CHARS = 4000

# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------


class VerificationResult(BaseModel):
    """
    Structured verdict from the LLM-as-a-Judge verifier.

    Produced by parsing Claude's JSON response.  Consumed by the
    LangGraph conditional edge to route to END or Debugger.

    Attributes
    ----------
    thought_process : str
        Step-by-step chain-of-thought reasoning comparing the AC requirement
        to the actual browser output.  Should be 2–6 concise sentences.
        Preserved in state for audit and prompt injection.

    is_verified : bool
        ``True``  — the UI evidence confirms the AC step was met.
        ``False`` — the AC step was NOT met based on the available evidence.

    failure_reason : str
        When ``is_verified`` is ``False``: a precise, one-sentence
        description of what is missing or wrong on the screen.
        Must be specific enough to serve as the ``error_log`` input to
        the Debugger's RAG query.
        When ``is_verified`` is ``True``: empty string.

    Examples
    --------
    Verified success:
    >>> VerificationResult(
    ...     thought_process="The AC requires the 'New Request +' button to be visible. "
    ...                     "The extracted_text contains 'New Request +', confirming it is present.",
    ...     is_verified=True,
    ...     failure_reason="",
    ... )

    Verified failure:
    >>> VerificationResult(
    ...     thought_process="The AC requires sorting by 'Due Days' ascending. "
    ...                     "The extracted_text shows no aria-sort attribute change.",
    ...     is_verified=False,
    ...     failure_reason="The 'Due Days' column does not show ascending sort order "
    ...                    "— aria-sort='ascending' was not found in the table header.",
    ... )
    """

    thought_process: str = Field(
        description=(
            "Step-by-step reasoning comparing the AC requirement to the actual browser output. "
            "2–6 sentences. Always present."
        )
    )
    is_verified: bool = Field(description="True if the UI evidence confirms the AC was met. False otherwise.")
    failure_reason: str = Field(
        default="",
        description=(
            "If is_verified=False: precise description of what is missing or wrong. If is_verified=True: empty string."
        ),
    )

    @field_validator("failure_reason", mode="before")
    @classmethod
    def _coerce_failure_reason(cls, v: Any) -> str:
        """Normalise None → empty string."""
        return str(v) if v is not None else ""

    @field_validator("thought_process", mode="before")
    @classmethod
    def _coerce_thought(cls, v: Any) -> str:
        """Normalise None → placeholder."""
        return str(v) if v else "(no reasoning provided)"

    def to_log_string(self) -> str:
        """Return a compact single-line log representation."""
        verdict = "VERIFIED ✓" if self.is_verified else "FAILED ✗"
        reason = f" | Reason: {self.failure_reason[:120]}" if not self.is_verified else ""
        return f"[{verdict}]{reason}"


# ---------------------------------------------------------------------------
# LLM factory — delegates to centralized provider
# ---------------------------------------------------------------------------


def _get_verifier_llm() -> "ChatBedrockConverse":
    """
    Create an LLM client for the verifier node.

    Delegates to the centralized ``get_llm()`` factory from ``backend.llm``.
    Uses the ``verifier_llm`` purpose preset (512 max_tokens, temp=0).
    """
    from backend.llm import get_llm

    return get_llm("verifier_llm")


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(raw: str) -> str:
    """
    Extract a JSON object from a raw LLM response string.

    Handles three common Claude output patterns:
    1. Raw JSON: ``{"is_verified": true, ...}`` — returned as-is.
    2. Markdown fenced: ````json\\n{...}\\n```` — fence stripped.
    3. Partial: JSON preceded by explanatory text — first ``{...}`` block extracted.

    Args
    ----
    raw : str
        The raw LLM response content.

    Returns
    -------
    str
        The extracted JSON string, ready to pass to ``json.loads`` /
        ``VerificationResult.model_validate_json``.

    Raises
    ------
    ValueError
        If no valid JSON object can be located in the response.
    """
    stripped = raw.strip()

    # Pattern 1: starts directly with JSON
    if stripped.startswith("{"):
        return stripped

    # Pattern 2: markdown fenced block
    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        return fence_match.group(1).strip()

    # Pattern 3: JSON object embedded in prose — find first { ... }
    brace_start = stripped.find("{")
    brace_end = stripped.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        return stripped[brace_start : brace_end + 1]

    raise ValueError(
        f"No JSON object found in verifier LLM response. Raw response (first 300 chars): {stripped[:300]!r}"
    )


# ---------------------------------------------------------------------------
# Core judge call
# ---------------------------------------------------------------------------

# System prompt — defined at module level so it is built once, not per-call.
_VERIFIER_SYSTEM_PROMPT = """\
<GOLDEN_RULES>
1. IDENTITY: You are the Verifier node in a multi-agent browser regression pipeline.
2. MISSION: Judge whether a browser automation result satisfies a given Acceptance Criteria (AC) step.
3. OUTPUT FORMAT: Return ONLY a valid JSON object. No preamble, no markdown fences.
4. EVIDENCE-BASED: Judge ONLY based on the EXTRACTED_TEXT and FINAL_URL provided. Do not assume.
</GOLDEN_RULES>

<JUDGEMENT_RULES>
1. The AC defines the GROUND TRUTH. The page evidence either supports it or it does not.
2. If the AC requires a UI element to be visible and it appears in EXTRACTED_TEXT → verified.
3. If the AC requires navigation to a URL and FINAL URL matches → verified.
4. If the AC requires a form submission and EXTRACTED_TEXT contains a success message → verified.
5. If the agent reported failure (AGENT STATUS=False) or the EXTRACTED_TEXT explicitly
   contradicts the AC → NOT verified.
6. Absence of evidence ≠ failure — if the text is ambiguous, lean toward NOT verified
   and explain what specific text / UI indicator is missing.
</JUDGEMENT_RULES>

<MANDATORY_REASONING_WORKFLOW>
1. STEP 1: Identify the CORE REQUIREMENT of the AC step.
2. STEP 2: Scan the EXTRACTED_TEXT for specific indicators (success messages, labels).
3. STEP 3: Check the FINAL_URL against the URL_PATTERN if specified.
4. STEP 4: Compare evidence against requirements and produce a binary verdict.
</MANDATORY_REASONING_WORKFLOW>

<OUTPUT_SCHEMA>
Return a SINGLE JSON object matching this EXACT schema:
{
  "thought_process": "<2-6 sentences of step-by-step reasoning>",
  "is_verified": <true | false>,
  "failure_reason": "<empty string if is_verified=true; precise description if false>"
}
</OUTPUT_SCHEMA>

<CRITICAL_REMINDER>
- failure_reason MUST be empty string "" when is_verified is true.
- failure_reason MUST be a specific, actionable string when is_verified is false.
- Output ONLY valid JSON.
</CRITICAL_REMINDER>
"""


async def _call_llm_judge(
    ac_step: str,
    final_url: str,
    extracted_text: str,
    error_message: str,
    steps_taken: int,
    run_id: str,
) -> VerificationResult:
    """
    Call ChatBedrockConverse to judge whether the AC was met.

    Args
    ----
    ac_step : str
        The Acceptance Criteria step text.
    final_url : str
        The browser's final URL after Surfer execution.
    extracted_text : str
        Page text captured by the browser-use Agent.
    error_message : str
        Any error string from the browser-use Agent (empty on success).
    steps_taken : int
        Number of agent steps executed.
    run_id : str
        Run identifier for logging.

    Returns
    -------
    VerificationResult
        Parsed structured verdict from Claude.

    Raises
    ------
    RuntimeError
        If the LLM call fails or the response cannot be parsed after retries.
    """
    # Truncate extracted_text to avoid prompt bloat
    truncated_text = extracted_text[:_MAX_EXTRACTED_CHARS]
    if len(extracted_text) > _MAX_EXTRACTED_CHARS:
        truncated_text += f"\n… [truncated — {len(extracted_text)} chars total]"

    agent_status = "SUCCESS" if not error_message else f"FAILURE ({error_message[:200]})"

    user_msg = (
        f"AC STEP:\n{ac_step}\n\n"
        f"FINAL URL:\n{final_url or '(none recorded)'}\n\n"
        f"EXTRACTED TEXT:\n{truncated_text or '(no text captured)'}\n\n"
        f"AGENT STATUS: {agent_status}\n"
        f"STEPS TAKEN: {steps_taken}\n\n"
        f"Produce the JSON verdict now:"
    )

    llm = _get_verifier_llm()
    response = await llm.ainvoke(
        [
            SystemMessage(content=_VERIFIER_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ]
    )

    raw: str = (response.content or "").strip()
    if not raw:
        raise RuntimeError("verifier_node: LLM returned an empty response — cannot produce verdict.")

    logger.debug("[%s] Verifier: raw LLM response (%.300s …)", run_id, raw)

    # Extract and parse JSON
    try:
        json_str = _extract_json(raw)
        result = VerificationResult.model_validate_json(json_str)
    except (ValueError, Exception) as parse_exc:
        # Attempt a lenient fallback: try parsing the whole raw string
        try:
            result = VerificationResult.model_validate_json(raw)
        except Exception:
            raise RuntimeError(
                f"verifier_node: failed to parse LLM response as VerificationResult. "
                f"Parse error: {parse_exc}. "
                f"Raw response: {raw[:400]!r}"
            ) from parse_exc

    logger.info("[%s] Verifier: %s", run_id, result.to_log_string())
    return result


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


async def verifier_node(state: dict) -> dict:
    """
    LangGraph node: LLM-as-a-Judge verification of the Surfer's result.

    Reads ``ac_step`` and ``browser_result`` from state, calls
    ``ChatBedrockConverse`` (Claude 3.5 Sonnet) to produce a
    ``VerificationResult``, and writes routing signals back to state.

    State Inputs (read)
    -------------------
    ac_step : str
        The original Acceptance Criteria step being tested.
    browser_result : dict
        Serialised ``BrowserResult`` from ``surfer_node``.
        Keys used: ``final_url``, ``extracted_text``, ``error_message``,
        ``steps_taken``, ``success``.
    run_id : str
        Run identifier for logging and SQLite attribution.
    ticket_id : str
        Optional Jira ticket ID for attribution.

    State Outputs (written)
    -----------------------
    verification_result : dict
        Serialised ``VerificationResult`` fields:
        ``thought_process``, ``is_verified``, ``failure_reason``.
    error_log : str
        Set to ``failure_reason`` when ``is_verified=False``; empty otherwise.
        This field is the primary input to ``debugger_node``.
    _route : str
        ``"memory_log"`` when ``is_verified=True`` → routes to END.
        ``"debugger"``  when ``is_verified=False`` → routes to Debugger.

    Args
    ----
    state : dict
        Current ``OrchestratorState`` (passed as dict by LangGraph).

    Returns
    -------
    dict
        Partial state patch to merge into ``OrchestratorState``.

    Notes
    -----
    On LLM failure, the verifier defaults to ``is_verified=False`` and
    sets ``error_log`` to the exception text.  This conservatively routes
    to the Debugger rather than falsely marking a step as verified.
    """
    run_id: str = state.get("run_id", "")
    ac_step: str = state.get("ac_step", "")
    browser_result: dict = state.get("browser_result", {})
    state.get("ticket_id", "")

    final_url: str = browser_result.get("final_url", "")
    extracted_text: str = browser_result.get("extracted_text", "")
    error_message: str = browser_result.get("error_message", "")
    steps_taken: int = browser_result.get("steps_taken", 0)

    logger.info(
        "[%s] Verifier: judging AC step — %.120s | final_url=%s | text_len=%d",
        run_id,
        ac_step,
        final_url[:80] if final_url else "(none)",
        len(extracted_text),
    )

    # ── Call the LLM judge ──────────────────────────────────────────────────
    try:
        verdict: VerificationResult = await _call_llm_judge(
            ac_step=ac_step,
            final_url=final_url,
            extracted_text=extracted_text,
            error_message=error_message,
            steps_taken=steps_taken,
            run_id=run_id,
        )
    except Exception as exc:
        # Conservative default: treat LLM failure as unverified
        err_str = f"{type(exc).__name__}: {exc}"
        logger.error("[%s] Verifier: judge call failed (%s) — defaulting to UNVERIFIED", run_id, err_str)
        verdict = VerificationResult(
            thought_process=(
                f"Verifier LLM call failed: {err_str}. Unable to judge AC satisfaction. Defaulting to UNVERIFIED."
            ),
            is_verified=False,
            failure_reason=f"Verifier unavailable: {err_str}",
        )

    # ── Build serialisable dict for state storage ───────────────────────────
    verification_dict: dict = {
        "thought_process": verdict.thought_process,
        "is_verified": verdict.is_verified,
        "failure_reason": verdict.failure_reason,
    }

    # ── Route based on verdict ──────────────────────────────────────────────
    if verdict.is_verified:
        logger.info(
            "[%s] Verifier: PASS — AC step verified. Routing to memory_log → END.",
            run_id,
        )
        return {
            "verification_result": verification_dict,
            "error_log": "",  # Clear any previous error
            "_route": "memory_log",  # Signal for conditional edge → END
        }
    else:
        # Map failure_reason → error_log so the Debugger has a precise query
        failure_reason = verdict.failure_reason or (
            "Verifier returned is_verified=False but provided no failure_reason."
        )
        logger.warning(
            "[%s] Verifier: FAIL — %s. Routing to debugger.",
            run_id,
            failure_reason[:120],
        )

        # Enrich error_log with full context for the Debugger's RAG query
        enriched_error_log = (
            f"VERIFIER FAILURE for AC step: {ac_step}\n\n"
            f"Failure Reason: {failure_reason}\n\n"
            f"Verifier Reasoning: {verdict.thought_process}\n\n"
            f"Browser Evidence:\n"
            f"  Final URL: {final_url or '(none)'}\n"
            f"  Agent Status: {'SUCCESS' if not error_message else 'FAILED'}\n"
            f"  Browser Error: {error_message or '(none)'}\n"
            f"  Extracted Text (first 500 chars):\n"
            f"  {extracted_text[:500] or '(no text captured)'}"
        )

        return {
            "verification_result": verification_dict,
            "error_log": enriched_error_log,  # → fed to debugger_node RAG query
            "_route": "debugger",
        }
